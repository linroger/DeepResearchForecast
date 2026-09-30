"""RESEARCH-13 (P09): deterministic context packs for the two probability prompts.

The binary draw read the research dossier through a 48k head+tail slice and the spine read
``situation_brief[:2000]``. On stored handoffs the slice dropped the analyst's
binary/resolution-ready section in half the runs while most of its tail went to References
and the Visual Annex, and the brief slice carried no dated timeline at all. This module
builds the replacement evidence packs; it is pure (no LLM, no IO, no clock), so the same
inputs always give the same text and the same SHAs.

* ``split_h2`` / ``classify_heading`` / ``dedupe_sections``: a fence-aware H1/H2 splitter
  (H3+ stays with its section) with bilingual heading classes. References, Visual Annex and
  How-to-Read are never packed; near-duplicate sections of concatenated multi-dossier
  reports are dropped.
* ``priority_fill``: per-stream caps as budget fractions, leftover redistributed in priority
  order, whole sections in document order and the last one cut at a paragraph/line boundary.
* ``developments_lane`` / ``scheduled_lane`` / ``split_chronology``: as_of-labelled timeline
  lanes. Dates are periods (``parse_dated_period``; a date range covers both endpoints): a row
  counts as past only when its whole period ended on or before as_of. The lane certifies event
  dates, not when a source became available, and its header says so. Rows dated after as_of
  are shown only for a live run (``scheduled_guard_open``), never in a hindcast.
* ``audit_temporal_contract``: re-parses every lane item's full date; a segment with any item
  that breaks its header's contract is withheld, so a false "on or before" header is never
  emitted.
* ``build_binary_pack`` / ``build_spine_pack`` -> ``PackResult``. An invalid as_of (not a day,
  or after today), a non-positive budget, a binary dossier without H2 headings or with
  nothing packable returns a ``fallback:*`` status and the caller keeps its legacy prompt.

Not named ``forecast_evidence_pack``: that module name is reserved for ADR 0002 WP6, whose
strict-xfail characterization tests would start passing.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Mapping, NamedTuple, Optional, Sequence, Tuple

from ..utils.canonical_json import canonical_json_sha256
from ..utils.dates import date_period
from .forecast_extractor import MarkdownFenceState, markdown_fence_transition, slice_head_tail

SCHEMA = "drf.context_pack/1"
STATUS_OK = "ok"
STATUS_NO_H2 = "fallback:no_h2"
STATUS_AS_OF_INVALID = "fallback:as_of_invalid"
STATUS_EMPTY = "fallback:empty"
STATUS_BUDGET_INVALID = "fallback:budget_invalid"

CONTRACT_ON_OR_BEFORE = "on_or_before"
CONTRACT_AFTER = "after"

CLASS_EXCLUDED = "excluded"
CLASS_APPENDIX = "appendix"
CLASS_EXECUTIVE_SUMMARY = "executive_summary"
CLASS_ANALYST_FORECASTS = "analyst_forecasts"
CLASS_SCENARIO = "scenario"
CLASS_BODY = "body"

# Binary pack: stream priority order and caps (fractions of the dossier budget). The
# appendix stream has no cap entry, so it only receives leftover budget.
BINARY_PRIORITY = (CLASS_ANALYST_FORECASTS, CLASS_EXECUTIVE_SUMMARY, CLASS_SCENARIO,
                   CLASS_BODY, CLASS_APPENDIX)
BINARY_CAPS: Dict[str, float] = {
    CLASS_ANALYST_FORECASTS: 0.35, CLASS_EXECUTIVE_SUMMARY: 0.15, CLASS_SCENARIO: 0.20,
    CLASS_BODY: 1.0,
}
# Spine pack: shares of the whole spine budget, in priority order.
SPINE_PRIORITY = (CLASS_EXECUTIVE_SUMMARY, CLASS_SCENARIO, "situation", "developments",
                  "scheduled", "key_metrics")
SPINE_CAPS: Dict[str, float] = {
    CLASS_EXECUTIVE_SUMMARY: 0.25, CLASS_SCENARIO: 0.15, "situation": 0.15,
    "developments": 0.20, "scheduled": 0.05, "key_metrics": 0.20,
}

# Binary lanes are budget-exempt, so their size is bounded here: at most about 12 x 462 +
# 5 x 361 chars plus two headers (~7.6k), about 5.6k net of the 2,000-char situation brief the
# pack replaces in the binary prompt (the full 7.6k when the run had no brief).
BINARY_DEV_MAX_ITEMS = 12
BINARY_DEV_ITEM_CHARS = 400
BINARY_SCHED_MAX_ITEMS = 5
BINARY_SCHED_ITEM_CHARS = 300
# Spine lanes are one stream each and are cut to their share, so they can start longer.
SPINE_DEV_MAX_ITEMS = 15
SPINE_DEV_ITEM_CHARS = 400
SPINE_SCHED_MAX_ITEMS = 8
SPINE_SCHED_ITEM_CHARS = 300

TRUNC_MARKER = "\n…[truncated]"
PIECE_SEP = "\n\n"
MIN_PARTIAL_CHARS = 80
DEDUP_PREFIX_CHARS = 2000
DEDUP_JACCARD = 0.9
_LANE_DATE_CHARS = 32

_HEADERS = {
    "en": {
        "developments": ("[DEVELOPMENTS — events dated on or before {as_of}; newest first; "
                         "event dates only, source availability not verified]"),
        "scheduled": "[SCHEDULED — dated after {as_of}: not yet occurred; catalysts, not evidence]",
        "dossier": ("[DOSSIER EXCERPT — sections selected by priority (resolution-ready "
                    "forecasts, executive summary, scenarios, body); references and annexes "
                    "omitted. Projections and forecasts in it are expectations, not events that "
                    "have occurred]"),
        "dev_line": "- {date} ({days} days before as-of): {event}",
        "sched_line": "- {date} ({days} days after as-of): {event}",
        "absence": ("no dated development on or before {as_of} in the research timeline "
                    "({undated} undated, {straddle} straddling)"),
    },
    "zh": {
        "developments": ("[近期进展 — 日期在 {as_of} 当日或之前的事件；由新到旧；"
                         "仅核对事件日期，未核实来源的可得时间]"),
        "scheduled": "[已排期 — 日期在 {as_of} 之后：尚未发生；是催化剂，不是证据]",
        "dossier": ("[研究档案摘录 — 按优先级节选执行摘要与情景；参考文献与附录已略去。"
                    "其中的预测与推演是预期，不是已发生的事件]"),
        "dev_line": "- {date}（as-of 前 {days} 天）：{event}",
        "sched_line": "- {date}（as-of 后 {days} 天）：{event}",
        "absence": ("研究时间线中没有日期在 {as_of} 当日或之前的进展"
                    "（{undated} 条无日期，{straddle} 条跨越 as-of）"),
    },
}


def _lang_key(lang: Any) -> str:
    return "zh" if str(lang or "").strip().lower().startswith("zh") else "en"


# ----------------------------------------------------------------------- dated periods
class DatedPeriod(NamedTuple):
    """A date read as the calendar period it covers; gating uses ``end``."""
    start: date
    end: date
    precision: str  # day | month | quarter | half | year | range


# The per-form regexes run on one token (``_DATE_TOKEN_RE``) of whitespace-collapsed text, so
# their ``\s*`` runs are at most one char long and every search is linear.
_Q_RANGE_RE = re.compile(r"(\d{4})\s*[-/ ]?\s*Q([1-4])\s*(?:-|–|—|~|to|至|到)\s*Q([1-4])", re.I)
_Q_REV_RANGE_RE = re.compile(
    r"(?<![A-Za-z])Q([1-4])\s*(?:-|–|—|~|to|至|到)\s*Q([1-4])\s*[-/ ]?\s*(\d{4})", re.I)
_Q_RE = re.compile(r"(\d{4})\s*[-/ ]?\s*Q([1-4])(?![0-9])", re.I)
_Q_REV_RE = re.compile(r"(?<![A-Za-z])Q([1-4])\s*[-/ ]?\s*(\d{4})", re.I)
_Q_CJK_RE = re.compile(r"(\d{4})\s*年\s*第?\s*([一二三四1-4])\s*季度")
_H_RE = re.compile(r"(\d{4})\s*[-/ ]?\s*H([12])(?![0-9])", re.I)
_H_REV_RE = re.compile(r"(?<![A-Za-z])H([12])\s*[-/ ]?\s*(\d{4})", re.I)
_H_CJK_RE = re.compile(r"(\d{4})\s*年\s*(上|下)半年")
_CJK_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4}
# Every date form parse_dated_period reads, as one alternation: at a given position the
# earlier alternative wins, so a full date is never read as its month or year.
_DATE_TOKEN_RE = re.compile("|".join((
    r"\d{4} ?年 ?第? ?[一二三四1-4] ?季度",                        # 2026年第三季度
    r"\d{4} ?年 ?[上下]半年",                                     # 2026年上半年
    r"\d{4} ?年 ?\d{1,2} ?月 ?\d{1,2} ?日?",                      # 2026年9月15日
    r"\d{4} ?年 ?\d{1,2} ?月",                                    # 2026年9月
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}",                             # 2026-09-15, 2026/09/15
    r"\d{4} ?[-/ ]? ?Q[1-4] ?(?:-|–|—|~|to|至|到) ?Q[1-4]",        # 2026-Q3-Q4
    r"\d{4} ?[-/ ]? ?Q[1-4](?![0-9])",                            # 2026-Q3
    r"\d{4} ?[-/ ]? ?H[12](?![0-9])",                             # 2026-H2
    r"\d{4}[-/.]\d{1,2}(?!\d)",                                   # 2026-09
    r"(?<![A-Za-z])Q[1-4] ?(?:-|–|—|~|to|至|到) ?Q[1-4] ?[-/ ]? ?\d{4}",  # Q3-Q4 2026
    r"(?<![A-Za-z])Q[1-4] ?[-/ ]? ?\d{4}",                        # Q3 2026
    r"(?<![A-Za-z])H[12] ?[-/ ]? ?\d{4}",                         # H2 2026
    r"\b\d{4}\b",                                                 # 2026
)), re.I)
# A time of day never changes the date's period ("2026-09-15T08:00:00+0800").
_TIME_OF_DAY_RE = re.compile(r"(?<=\d)[T ]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?",
                             re.I)
# A range separator right after the last date: the row runs to the endpoint that follows.
# '-', '至' and '到' count only before a digit ("2026年9月到期" is a month, not a range); an open
# end ("至今", "to date", "– present") leaves no endpoint, so the row is undated.
_RANGE_SEP_RE = re.compile(
    r" ?(?:–|—|~|〜) ?| (?:to|until|through|till)\b ?| ?(?:-|至|到) ?(?=\d)"
    r"| ?起? ?(?:至|到|迄) ?(?:今|现在|目前)", re.I)
# The end of a range written without the parts it shares with its start.
_TAIL_MONTH_DAY_RE = re.compile(r"(\d{1,2}) ?(?:月|[-/.]) ?(\d{1,2})(?!\d)")   # 10月20日, 10-01
_TAIL_MONTH_RE = re.compile(r"(\d{1,2}) ?月")                                  # 10月
_TAIL_NUMBER_RE = re.compile(r"(\d{1,2})(?![\d月])")                           # 20日, 20


def _month_span(year: int, first_month: int, last_month: int) -> Optional[Tuple[date, date]]:
    try:
        start = date(year, first_month, 1)
        end = date(year, last_month, calendar.monthrange(year, last_month)[1])
    except ValueError:
        return None
    return start, end


def _quarters(year: int, first: int, last: int) -> Optional[DatedPeriod]:
    if last < first:
        return None
    span = _month_span(year, 3 * first - 2, 3 * last)
    return DatedPeriod(span[0], span[1], "quarter") if span else None


def _half(year: int, half: int) -> Optional[DatedPeriod]:
    span = _month_span(year, 1 if half == 1 else 7, 6 if half == 1 else 12)
    return DatedPeriod(span[0], span[1], "half") if span else None


def _token_period(value: Any) -> Optional[DatedPeriod]:
    """One date token (or a ``date``) as its period: the quarter and half-year forms, else
    ``dates.date_period`` (day / month / year by the token's own precision)."""
    if isinstance(value, str):
        m = _Q_RANGE_RE.search(value)
        if m:
            return _quarters(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        m = _Q_REV_RANGE_RE.search(value)
        if m:
            return _quarters(int(m.group(3)), int(m.group(1)), int(m.group(2)))
        m = _Q_RE.search(value)
        if m:
            return _quarters(int(m.group(1)), int(m.group(2)), int(m.group(2)))
        m = _Q_REV_RE.search(value)
        if m:
            return _quarters(int(m.group(2)), int(m.group(1)), int(m.group(1)))
        m = _Q_CJK_RE.search(value)
        if m:
            q = _CJK_DIGITS.get(m.group(2)) or int(m.group(2))
            return _quarters(int(m.group(1)), q, q)
        m = _H_RE.search(value)
        if m:
            return _half(int(m.group(1)), int(m.group(2)))
        m = _H_REV_RE.search(value)
        if m:
            return _half(int(m.group(2)), int(m.group(1)))
        m = _H_CJK_RE.search(value)
        if m:
            return _half(int(m.group(1)), 1 if m.group(2) == "上" else 2)
    try:
        span = date_period(value)
    except Exception:  # noqa: BLE001 — a malformed date is undated, never an error
        return None
    if span is None:
        return None
    start, end = span
    if start == end:
        precision = "day"
    elif (start.year, start.month) == (end.year, end.month):
        precision = "month"
    else:
        precision = "year"
    return DatedPeriod(start, end, precision)


def _range_end(rest: str, first: DatedPeriod) -> Optional[DatedPeriod]:
    """The endpoint after a range separator when it omits what it shares with ``first``
    ("2026年9月15日-20日", "2026-09-15 to 10-01", "2026年9月-10月"); None when ``rest`` holds
    no such endpoint or it would end before ``first`` starts (never guessed across a year)."""
    if first.precision not in ("day", "month"):
        return None
    day: Optional[int]
    m = _TAIL_MONTH_DAY_RE.match(rest)
    if m:
        month, day = int(m.group(1)), int(m.group(2))
    else:
        m = _TAIL_MONTH_RE.match(rest)
        if m:
            month, day = int(m.group(1)), None
        else:
            m = _TAIL_NUMBER_RE.match(rest)
            if not m:
                return None
            number = int(m.group(1))
            month, day = (first.start.month, number) if first.precision == "day" else (number, None)
    if day is None:
        span = _month_span(first.start.year, month, month)
        if span is None:
            return None
        period = DatedPeriod(span[0], span[1], "month")
    else:
        try:
            period = DatedPeriod(date(first.start.year, month, day),
                                 date(first.start.year, month, day), "day")
        except ValueError:
            return None
    return period if period.end >= first.start else None


def parse_dated_period(value: Any) -> Optional[DatedPeriod]:
    """``value`` as ``(start, end, precision)``, or None when it carries no date.

    Forms: ``YYYY-MM-DD``, ``YYYY/MM/DD``, CJK 年月日 / 年月, ``YYYY-MM``, quarters
    (``YYYY-Qn``, ``YYYY-Qn-Qm``, ``Qn YYYY``, ``Qn-Qm YYYY``, ``YYYY年第n季度``), halves
    (``YYYY-Hn``, ``Hn YYYY``, ``YYYY年上/下半年``) and ``YYYY``; a coarse date is never read
    as a single day. A value holding several dates, or one date and a range end written
    after it ("2026-09-15 to 2026-10-01", "2025–2026", "2026年9月15日-20日"), covers all of
    them (precision ``range``), so gating on its end never calls an unfinished range past.
    A range whose end cannot be read ("2026-09-15 至今", "… to date") or any unreadable
    date token makes the value undated. Linear in the input length; never raises.
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (date, datetime)):
        return _token_period(value)
    text = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value))).strip()
    text = _TIME_OF_DAY_RE.sub("", text)
    tokens = list(_DATE_TOKEN_RE.finditer(text))
    if not tokens:
        return None
    periods: List[DatedPeriod] = []
    for token in tokens:
        period = _token_period(token.group(0))
        if period is None:
            return None
        periods.append(period)
    sep = _RANGE_SEP_RE.match(text, tokens[-1].end())
    if sep:
        end = _range_end(text[sep.end():], periods[-1])
        if end is None:
            return None
        periods.append(end)
    if len(periods) == 1:
        return periods[0]
    return DatedPeriod(min(p.start for p in periods), max(p.end for p in periods), "range")


def temporal_class(period: Optional[DatedPeriod], as_of: date) -> str:
    """past (period ended on or before as_of) | future (starts after) | straddle | undated."""
    if period is None:
        return "undated"
    if period.end <= as_of:
        return "past"
    if period.start > as_of:
        return "future"
    return "straddle"


def _as_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return (value.astimezone(timezone.utc) if value.tzinfo else value).date()
    if isinstance(value, date):
        return value
    return None


def validate_pack_as_of(as_of_raw: Any, now: Any) -> Optional[date]:
    """The pack's as_of, or None unless it reads as a single day on or before ``now``'s date."""
    today = _as_date(now)
    period = parse_dated_period(as_of_raw)
    if today is None or period is None or period.precision != "day":
        return None
    return period.start if period.start <= today else None


# ----------------------------------------------------------------------- dossier sections
@dataclass(frozen=True)
class Section:
    """One H1/H2 section of a markdown dossier; ``text`` starts with its heading line."""
    ordinal: int
    level: int      # 0 = preamble before the first heading, else 1 or 2
    heading: str
    cls: str
    start: int      # char offset of the section in the source text
    text: str


# Only the opening run is matched here; the closing run is trimmed in _heading_text, which
# keeps the match linear on a heading line of any length.
_SPLIT_HEADING_RE = re.compile(r"^(#{1,2})[ \t]+(.*)$")
_HEADING_NUMBERING_RE = re.compile(
    r"^(?:\d+(?:\.\d+)*[.)、:：]?|[ivxlc]+[.)]|[一二三四五六七八九十]+[、.．]"
    r"|第[一二三四五六七八九十\d]+[章节部分])\s*", re.I)
_APPENDIX_PREFIX_RE = re.compile(r"^(?:appendix|annex|附录)\s*[a-z0-9一二三四五]?\s*[:：.\-—–]\s*", re.I)
# A trailing parenthetical is often a gloss of the heading ("参考资料 (References)").
_TRAILING_GLOSS_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)$")

_EXCLUDED_RE = re.compile(
    r"^(?:references?|reference\s+list|bibliography|sources\s+cited|works\s+cited)"
    r"(?:\s*(?:and|&)\s*(?:notes|sources|links))?\s*(?:\(.*\))?$"
    r"|^visual\s+(?:annex|appendix)\b|^how\s+to\s+read\b"
    r"|^(?:参考文献|参考来源|参考资料)|图表附录|阅读说明|阅读指南|^如何阅读", re.I)
_APPENDIX_RE = re.compile(
    r"^(?:data\s+)?sources?\b(?!\s+of\b)|\bmethodology\b|^methods?\b(?!\s+(?:of|for|to)\b)"
    r"|^(?:appendix|annex)\b"
    r"|^(?:研究)?方法|方法论|^(?:资料)?来源|来源说明|来源清单|数据来源|^附录", re.I)
_EXEC_SUMMARY_RE = re.compile(r"\bexecutive\s+summary\b|^summary\b|执行摘要|^(?:内容)?摘要", re.I)
# DRF's brief asks for "Part 1 — the forecasts": a heading of that shape is the analyst's
# binary section even when it does not say "binary".
_ANALYST_RE = re.compile(
    r"\bbinary\b|\byes\s*[/-]\s*no\b|\byes\s+or\s+no\b|resolution[\s-]*ready"
    r"|resolution\s+criteria|forecasts?\s+to\s+(?:track|watch)"
    r"|^part\s+(?:1|one|i)\b\s*[:：.\-—–]*\s*(?:the\s+|your\s+)?forecasts?\b"
    r"|二元|可判定|判定标准", re.I)
_SCENARIO_RE = re.compile(r"\bscenarios?\b|情景", re.I)


def normalize_heading(heading: Any) -> str:
    """Casefolded heading without emphasis marks, leading numbering or trailing colon."""
    h = unicodedata.normalize("NFKC", str(heading or "")).casefold()
    h = re.sub(r"[*_`]+", "", h)
    h = re.sub(r"\s+", " ", h).strip()
    h = _HEADING_NUMBERING_RE.sub("", h, count=1)
    return h.rstrip(" :：.。").strip()


def _classify_plain(h: str) -> str:
    if _EXCLUDED_RE.search(h):
        return CLASS_EXCLUDED
    if _APPENDIX_RE.search(h):
        return CLASS_APPENDIX
    if _EXEC_SUMMARY_RE.search(h):
        return CLASS_EXECUTIVE_SUMMARY
    if _ANALYST_RE.search(h):
        return CLASS_ANALYST_FORECASTS
    if _SCENARIO_RE.search(h):
        return CLASS_SCENARIO
    return CLASS_BODY


def _classify_core(h: str) -> str:
    # "Appendix A: …" is an appendix unless what it holds classifies more specifically
    # ("附录A：概率情景汇总表" is a scenario table, "Appendix: References" is excluded).
    rest = _APPENDIX_PREFIX_RE.sub("", h, count=1)
    if rest != h:
        inner = _classify_plain(rest) if rest else CLASS_APPENDIX
        return CLASS_APPENDIX if inner == CLASS_BODY else inner
    return _classify_plain(h)


def classify_heading(heading: Any) -> str:
    """The pack class of a section heading (bilingual; body when nothing matches).

    Precedence: excluded, appendix, executive summary, analyst forecasts, scenario, body. A
    trailing parenthetical gloss ("来源清单 (References)") excludes the section when the gloss
    names an excluded class, and otherwise classifies a heading that is body on its own."""
    h = normalize_heading(heading)
    if not h:
        return CLASS_BODY
    m = _TRAILING_GLOSS_RE.match(h)
    if m and m.group(1).strip():
        main, gloss = _classify_core(m.group(1).strip()), _classify_core(m.group(2).strip())
        if gloss == CLASS_EXCLUDED:
            return CLASS_EXCLUDED
        return gloss if main == CLASS_BODY else main
    return _classify_core(h)


def _heading_text(raw: str) -> str:
    """ATX heading text without its optional closing ``#`` run, which (as in CommonMark)
    counts only after a space or tab: "Why C#" keeps its ``#``, "Title ##" loses them."""
    text = raw.rstrip(" \t")
    core = text.rstrip("#")
    if core != text and (not core or core[-1] in " \t"):
        text = core
    return text.strip()


def split_h2(md: Any) -> List[Section]:
    """Split markdown at H1/H2 headings outside fenced code blocks; H3+ stays in place.

    Text before the first heading becomes a level-0 preamble section (dropped when blank).
    Offsets refer to the input with CRLF/CR line endings normalized to LF.
    """
    text = str(md or "").replace("\r\n", "\n").replace("\r", "\n")
    sections: List[Section] = []
    fence: MarkdownFenceState = None
    cur_start, cur_level, cur_heading = 0, 0, ""
    offset = 0

    def flush(end: int) -> None:
        body = text[cur_start:end]
        if cur_level == 0 and not body.strip():
            return
        sections.append(Section(
            ordinal=len(sections), level=cur_level, heading=cur_heading,
            cls=classify_heading(cur_heading) if cur_level else CLASS_BODY,
            start=cur_start, text=body.rstrip()))

    for line in text.split("\n"):
        was_in_fence = fence is not None
        fence, is_fence_line = markdown_fence_transition(line, fence)
        if not (is_fence_line or was_in_fence):
            m = _SPLIT_HEADING_RE.match(line)
            if m:
                flush(offset)
                cur_start, cur_level, cur_heading = offset, len(m.group(1)), _heading_text(m.group(2))
        offset += len(line) + 1
    flush(len(text))
    return sections


def _token_set(text: str) -> set:
    return set(re.findall(r"[0-9a-z]+|[㐀-鿿]",
                          unicodedata.normalize("NFKC", text[:DEDUP_PREFIX_CHARS]).casefold()))


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def dedupe_sections(sections: Sequence[Section]) -> Tuple[List[Section], List[Section]]:
    """Drop later sections duplicating an earlier kept one: same class, same normalized
    heading and >= 0.9 token-Jaccard over the first 2,000 chars (concatenated multi-dossier
    reports repeat their executive summary / forecast sections). Returns (kept, dropped)."""
    kept: List[Section] = []
    dropped: List[Section] = []
    seen: Dict[Tuple[str, str], List[set]] = {}
    for sec in sections:
        key = (sec.cls, normalize_heading(sec.heading))
        tokens = _token_set(sec.text)
        if sec.level and any(_jaccard(tokens, prior) >= DEDUP_JACCARD for prior in seen.get(key, [])):
            dropped.append(sec)
            continue
        seen.setdefault(key, []).append(tokens)
        kept.append(sec)
    return kept, dropped


# ----------------------------------------------------------------------- priority fill
class FillResult(NamedTuple):
    kept: Dict[str, List[Tuple[int, str]]]   # stream -> [(piece index, kept text)]
    telemetry: Dict[str, Dict[str, Any]]


def _cut_at_boundary(text: str, limit: int) -> str:
    """The longest prefix of ``text`` within ``limit`` chars that ends at a paragraph break,
    else a line break, else (no boundary in the second half of the window) at the limit."""
    if limit <= 0:
        return ""
    window = text[:limit + 1]
    for boundary in (PIECE_SEP, "\n"):
        cut = window.rfind(boundary)
        if cut >= limit // 2:
            return text[:cut].rstrip()
    return text[:limit].rstrip()


def _piece_cost(piece: str) -> int:
    return len(piece) + len(PIECE_SEP)


def priority_fill(streams: Sequence[Tuple[str, Sequence[str]]], budget: int,
                  caps: Mapping[str, float]) -> FillResult:
    """Allocate ``budget`` chars across ``streams`` (given in priority order).

    Pass 1: each stream gets min(raw, cap x budget) while budget remains. Pass 2: the leftover
    goes, in priority order, to streams with raw chars still unallocated. A stream without a
    cap entry is leftover-only. Each stream then keeps whole pieces in their given order; the
    first piece that does not fit is cut at a paragraph or line boundary with the truncation
    marker (skipped when the partial would be under 80 chars) and nothing after it is kept.
    A piece costs its length plus one separator, so the joined text of every kept piece is
    within its stream's allocation and the allocations sum to at most ``budget``.
    """
    budget = max(0, int(budget))
    raw = {name: sum(_piece_cost(p) for p in pieces) for name, pieces in streams}
    alloc: Dict[str, int] = {}
    remaining = budget
    for name, _pieces in streams:
        cap = max(0.0, float(caps.get(name, 0.0) or 0.0))
        give = min(raw[name], int(cap * budget), remaining)
        alloc[name] = give
        remaining -= give
    for name, _pieces in streams:
        if remaining <= 0:
            break
        give = min(raw[name] - alloc[name], remaining)
        alloc[name] += give
        remaining -= give
    kept: Dict[str, List[Tuple[int, str]]] = {}
    telemetry: Dict[str, Dict[str, Any]] = {}
    for name, pieces in streams:
        used = 0
        rows: List[Tuple[int, str]] = []
        truncated = False
        for idx, piece in enumerate(pieces):
            cost = _piece_cost(piece)
            if used + cost <= alloc[name]:
                rows.append((idx, piece))
                used += cost
                continue
            limit = alloc[name] - used - len(PIECE_SEP) - len(TRUNC_MARKER)
            partial = _cut_at_boundary(piece, limit)
            if len(partial) >= MIN_PARTIAL_CHARS:
                rows.append((idx, partial + TRUNC_MARKER))
                used += _piece_cost(partial + TRUNC_MARKER)
                truncated = True
            break
        kept[name] = rows
        telemetry[name] = {
            "raw_chars": raw[name], "allocated_chars": alloc[name], "kept_chars": used,
            "sections_kept": len(rows), "sections_dropped": len(pieces) - len(rows),
            "truncated": truncated,
        }
    return FillResult(kept, telemetry)


# ----------------------------------------------------------------------- timeline lanes
@dataclass(frozen=True)
class LaneItem:
    """One lane line: ``date`` is the display date (clipped to 32 chars), ``raw_date`` the
    full normalized date the row was classified by (the audit re-parses it; an item built
    without one is audited on its display date)."""
    date: str
    event: str
    days: int
    raw_date: str = ""


@dataclass(frozen=True)
class Segment:
    """A dated lane: its header states the temporal contract every item must satisfy."""
    name: str
    contract: str
    header: str
    items: Tuple[LaneItem, ...]
    lines: Tuple[str, ...]
    absence: str
    stats: Mapping[str, Any]

    def render(self) -> str:
        body = list(self.lines) if self.lines else ([self.absence] if self.absence else [])
        return "\n".join([self.header, *body]) if body else ""


def _norm_text(value: Any) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip()


def _clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: max(0, n - 1)].rstrip() + "…"


def _timeline_rows(timeline: Any) -> Tuple[List[Tuple[str, str, Optional[DatedPeriod]]], int]:
    """(date, event, period) for every row with an event, plus the count of rows without one."""
    rows: List[Tuple[str, str, Optional[DatedPeriod]]] = []
    skipped = 0
    for row in timeline if isinstance(timeline, (list, tuple)) else []:
        if not isinstance(row, Mapping):
            skipped += 1
            continue
        event = _norm_text(row.get("event"))
        if not event:
            skipped += 1
            continue
        raw_date = _norm_text(row.get("date"))
        rows.append((raw_date, event, parse_dated_period(raw_date) if raw_date else None))
    return rows, skipped


def _dedupe_sorted(rows: List[Tuple[str, str, DatedPeriod]]) -> Tuple[List[Tuple[str, str, DatedPeriod]], int]:
    out: List[Tuple[str, str, DatedPeriod]] = []
    seen = set()
    for raw_date, event, period in rows:
        key = (raw_date.casefold(), event.casefold()[:80])
        if key in seen:
            continue
        seen.add(key)
        out.append((raw_date, event, period))
    return out, len(rows) - len(out)


def _classified(timeline: Any, as_of: date) -> Dict[str, Any]:
    rows, skipped = _timeline_rows(timeline)
    buckets: Dict[str, list] = {"past": [], "future": [], "straddle": [], "undated": []}
    for raw_date, event, period in rows:
        buckets[temporal_class(period, as_of)].append((raw_date, event, period))
    return {"rows": len(rows), "skipped": skipped, **buckets}


def _past_sorted(past: List[Tuple[str, str, DatedPeriod]]) -> List[Tuple[str, str, DatedPeriod]]:
    # Newest period end first, then the later start (the narrower period); ties broken on
    # the event text and the raw date, so the order never depends on the input order.
    return sorted(past, key=lambda r: (-r[2].end.toordinal(), -r[2].start.toordinal(),
                                       r[1].casefold(), r[1], r[0]))


def _future_sorted(future: List[Tuple[str, str, DatedPeriod]]) -> List[Tuple[str, str, DatedPeriod]]:
    return sorted(future, key=lambda r: (r[2].start, r[2].end, r[1].casefold(), r[1], r[0]))


def developments_lane(timeline: Any, as_of: date, max_items: int = 12, item_chars: int = 400,
                      lang: str = "en") -> Segment:
    """Past-dated rows only (period ended on or before as_of), newest first, deduplicated on
    (date, first 80 normalized chars). Nothing eligible -> an explicit absence line."""
    tpl = _HEADERS[_lang_key(lang)]
    buckets = _classified(timeline, as_of)
    ordered, duplicates = _dedupe_sorted(_past_sorted(buckets["past"]))
    chosen = ordered[:max(0, int(max_items))]
    items = tuple(LaneItem(_clip(d, _LANE_DATE_CHARS), _clip(e, item_chars), (as_of - p.end).days,
                           raw_date=d) for d, e, p in chosen)
    lines = tuple(tpl["dev_line"].format(date=i.date, days=i.days, event=i.event) for i in items)
    absence = "" if items else tpl["absence"].format(
        as_of=as_of.isoformat(), undated=len(buckets["undated"]), straddle=len(buckets["straddle"]))
    stats = {"rows": buckets["rows"], "past": len(buckets["past"]), "kept": len(items),
             "undated": len(buckets["undated"]), "straddle": len(buckets["straddle"]),
             "future": len(buckets["future"]), "duplicates": duplicates,
             "over_cap": max(0, len(ordered) - len(items))}
    return Segment("developments", CONTRACT_ON_OR_BEFORE,
                   tpl["developments"].format(as_of=as_of.isoformat()), items, lines, absence, stats)


def scheduled_guard_open(as_of: date, now: Any, window_days: int,
                         retrospective: bool = False) -> bool:
    """Future rows are shown only for a live run: as_of within ``window_days`` of today. In a
    retrospective run they may have been written with hindsight, so they are withheld; a
    known hindcast (``retrospective``, the cutoff is a pinned past as-of while the research
    ran later) withholds them however recent its cutoff is."""
    today = _as_date(now)
    if today is None or retrospective:
        return False
    return (today - as_of).days <= max(0, int(window_days))


def scheduled_lane(timeline: Any, as_of: date, now: Any, window_days: int, max_items: int = 12,
                   item_chars: int = 400, lang: str = "en", *,
                   retrospective: bool = False) -> Segment:
    """Rows dated after as_of (soonest first), shown only while the scheduled guard is open;
    otherwise every such row is withheld and counted as ``post_as_of_rows_withheld``."""
    tpl = _HEADERS[_lang_key(lang)]
    buckets = _classified(timeline, as_of)
    guard_open = scheduled_guard_open(as_of, now, window_days, retrospective)
    ordered, duplicates = _dedupe_sorted(_future_sorted(buckets["future"]))
    chosen = ordered[:max(0, int(max_items))] if guard_open else []
    items = tuple(LaneItem(_clip(d, _LANE_DATE_CHARS), _clip(e, item_chars), (p.start - as_of).days,
                           raw_date=d) for d, e, p in chosen)
    lines = tuple(tpl["sched_line"].format(date=i.date, days=i.days, event=i.event) for i in items)
    stats = {"future": len(buckets["future"]), "kept": len(items), "duplicates": duplicates,
             "guard": "open" if guard_open else "withheld", "window_days": int(window_days),
             "retrospective": bool(retrospective),
             "post_as_of_rows_withheld": 0 if guard_open else len(buckets["future"]),
             "over_cap": max(0, len(ordered) - len(items)) if guard_open else 0}
    return Segment("scheduled", CONTRACT_AFTER, tpl["scheduled"].format(as_of=as_of.isoformat()),
                   items, lines, "", stats)


def audit_temporal_contract(segments: Sequence[Segment], as_of: date
                            ) -> Tuple[List[Segment], List[Dict[str, Any]]]:
    """Re-parse every item's date against its segment's header contract (fail closed).

    ``on_or_before`` items must be past; ``after`` items must be future. A segment with any
    violation is withheld whole, so its header is never emitted over an item it misdescribes.
    Returns (kept segments, violations)."""
    kept: List[Segment] = []
    violations: List[Dict[str, Any]] = []
    for seg in segments:
        want = {CONTRACT_ON_OR_BEFORE: "past", CONTRACT_AFTER: "future"}.get(seg.contract)
        bad = []
        for item in seg.items:
            got = temporal_class(parse_dated_period(item.raw_date or item.date), as_of)
            if want is None or got != want:
                bad.append({"segment": seg.name, "contract": seg.contract,
                            "date": _clip(item.raw_date or item.date, 80),
                            "class": got, "event_head": item.event[:60]})
        if bad:
            violations.extend(bad)
        else:
            kept.append(seg)
    return kept, violations


def split_chronology(timeline: Any, as_of: date, now: Any, max_past: int = 15,
                     window_days: int = 30, max_scheduled: int = 10, *,
                     retrospective: bool = False) -> Dict[str, Any]:
    """Section-prompt chronology split at as_of: the newest ``max_past`` past rows (returned in
    chronological order) and, under the same live-run guard as the scheduled lane, the soonest
    future rows. Undated and straddling rows appear in neither list and are counted."""
    buckets = _classified(timeline, as_of)
    past, _dup = _dedupe_sorted(_past_sorted(buckets["past"]))
    guard_open = scheduled_guard_open(as_of, now, window_days, retrospective)
    future, _fdup = _dedupe_sorted(_future_sorted(buckets["future"]))
    return {
        "past": [{"date": d, "event": e} for d, e, _p in reversed(past[:max(0, int(max_past))])],
        "scheduled": ([{"date": d, "event": e} for d, e, _p in future[:max(0, int(max_scheduled))]]
                      if guard_open else []),
        "post_as_of_rows_withheld": 0 if guard_open else len(buckets["future"]),
        "undated": len(buckets["undated"]), "straddle": len(buckets["straddle"]),
    }


# ----------------------------------------------------------------------- pack results
@dataclass(frozen=True)
class PackResult:
    text: str
    status: str
    telemetry: Mapping[str, Any]
    input_sha256: str
    text_sha256: str

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK and bool(self.text)

    def digest(self, kind: str) -> Dict[str, Any]:
        """The sidecar record without the text (what forecast.json carries)."""
        return {"schema": SCHEMA, "kind": kind, "status": self.status,
                "input_sha256": self.input_sha256, "text_sha256": self.text_sha256,
                "text_chars": len(self.text), "telemetry": dict(self.telemetry)}

    def sidecar(self, kind: str) -> Dict[str, Any]:
        return dict(self.digest(kind), text=self.text)


def _text_sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _input_sha(kind: str, **inputs: Any) -> str:
    """Hash of the pack inputs; timeline rows are sorted canonically first, so the SHA does
    not depend on their order."""
    rows = inputs.pop("timeline", None)
    canon_rows = sorted(json.dumps(r, ensure_ascii=False, sort_keys=True, default=str)
                        for r in (rows if isinstance(rows, (list, tuple)) else []))
    payload = {"kind": kind, "timeline": canon_rows,
               **{k: (v if isinstance(v, (int, float, bool)) or v is None else str(v))
                  for k, v in inputs.items()}}
    return canonical_json_sha256(payload)


def _result(text: str, status: str, telemetry: Dict[str, Any], input_sha: str) -> PackResult:
    telemetry = dict(telemetry, status=status, text_chars=len(text))
    return PackResult(text, status, telemetry, input_sha, _text_sha(text))


def _sections_telemetry(sections: Sequence[Section], dropped: Sequence[Section]) -> Dict[str, Any]:
    classes: Dict[str, int] = {}
    for sec in sections:
        classes[sec.cls] = classes.get(sec.cls, 0) + 1
    return {
        "total": len(sections) + len(dropped),
        "classes": dict(sorted(classes.items())),
        "excluded_headings": [s.heading for s in sections if s.cls == CLASS_EXCLUDED],
        "excluded_chars": sum(len(s.text) for s in sections if s.cls == CLASS_EXCLUDED),
        "duplicates_dropped": len(dropped),
    }


def _lanes(timeline: Any, as_of: date, now: Any, window_days: int, lang: str, *,
           dev_items: int, dev_chars: int, sched_items: int, sched_chars: int,
           retrospective: bool) -> Tuple[Dict[str, Segment], Dict[str, Any]]:
    dev = developments_lane(timeline, as_of, max_items=dev_items, item_chars=dev_chars, lang=lang)
    sched = scheduled_lane(timeline, as_of, now, window_days, max_items=sched_items,
                           item_chars=sched_chars, lang=lang, retrospective=retrospective)
    kept, violations = audit_temporal_contract([dev, sched], as_of)
    kept_names = {s.name for s in kept}
    telemetry = {
        "developments": dict(dev.stats), "scheduled": dict(sched.stats),
        "audit": {"violations": violations,
                  "withheld_segments": [s.name for s in (dev, sched) if s.name not in kept_names]},
    }
    return {s.name: s for s in kept}, telemetry


def _render_dossier(fill: FillResult, stream_sections: Mapping[str, Sequence[Section]]
                    ) -> List[str]:
    """Kept texts (possibly truncated) of the dossier streams in ``stream_sections``, in
    their original document order."""
    placed: List[Tuple[int, str]] = []
    for name, secs in stream_sections.items():
        for idx, text in fill.kept.get(name, []):
            placed.append((secs[idx].ordinal, text))
    return [text for _ordinal, text in sorted(placed)]


def _budget(value: Any) -> Optional[int]:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def build_binary_pack(research_report: Any, timeline: Any, as_of_raw: Any, now: Any,
                      budget: int = 48000, lang: str = "en", *,
                      window_days: int = 30, retrospective: bool = False) -> PackResult:
    """The binary draw's dossier context: dated lanes (budget-exempt) + a section-aware
    dossier excerpt within ``budget`` chars. ``retrospective`` (a hindcast) keeps the
    scheduled lane withheld (``scheduled_guard_open``).

    Fallbacks (the caller keeps its legacy prompt): an invalid as_of, a non-positive budget,
    a dossier without H2 headings (the text is then the legacy head+tail slice, for replay
    comparison only) and a dossier with nothing packable."""
    report = str(research_report or "")
    today = _as_date(now)
    budget_n = _budget(budget)
    input_sha = _input_sha("binary", research_report=report, timeline=timeline,
                           as_of=as_of_raw, now=today.isoformat() if today else None,
                           budget=budget_n, lang=_lang_key(lang), window_days=int(window_days),
                           retrospective=bool(retrospective))
    telemetry: Dict[str, Any] = {"kind": "binary", "budget": budget_n,
                                 "as_of": str(as_of_raw or ""), "lang": _lang_key(lang)}
    as_of = validate_pack_as_of(as_of_raw, now)
    if as_of is None:
        return _result("", STATUS_AS_OF_INVALID, telemetry, input_sha)
    telemetry["as_of"] = as_of.isoformat()
    if budget_n is None:
        return _result("", STATUS_BUDGET_INVALID, telemetry, input_sha)
    sections = split_h2(report)
    if not any(s.level == 2 for s in sections):
        fallback = slice_head_tail(report, budget_n)
        return _result(fallback, STATUS_NO_H2, dict(telemetry, dossier_chars=len(report)), input_sha)
    kept_sections, dropped = dedupe_sections(sections)
    tpl = _HEADERS[_lang_key(lang)]
    header = tpl["dossier"]
    by_class: Dict[str, List[Section]] = {name: [] for name in BINARY_PRIORITY}
    for sec in kept_sections:
        if sec.cls in by_class:
            by_class[sec.cls].append(sec)
    streams = [(name, [s.text for s in by_class[name]]) for name in BINARY_PRIORITY]
    fill = priority_fill(streams, max(0, budget_n - len(header) - 1), BINARY_CAPS)
    excerpt = _render_dossier(fill, by_class)
    lanes, lane_telemetry = _lanes(
        timeline, as_of, now, window_days, lang, dev_items=BINARY_DEV_MAX_ITEMS,
        dev_chars=BINARY_DEV_ITEM_CHARS, sched_items=BINARY_SCHED_MAX_ITEMS,
        sched_chars=BINARY_SCHED_ITEM_CHARS, retrospective=retrospective)
    dossier_block = (header + "\n" + PIECE_SEP.join(excerpt)) if excerpt else ""
    telemetry.update({
        "dossier_chars": len(report), "sections": _sections_telemetry(kept_sections, dropped),
        "streams": fill.telemetry, "lanes": lane_telemetry, "excerpt_chars": len(dossier_block),
    })
    if not dossier_block:
        # Lanes alone would drop the dossier from the prompt: keep the legacy view instead.
        return _result("", STATUS_EMPTY, telemetry, input_sha)
    blocks = [seg.render() for seg in (lanes.get("developments"), lanes.get("scheduled")) if seg]
    text = PIECE_SEP.join([b for b in blocks if b] + [dossier_block])
    return _result(text, STATUS_OK, telemetry, input_sha)


def build_spine_pack(research_report: Any, situation_text: Any, key_metrics_text: Any,
                     timeline: Any, as_of_raw: Any, now: Any, budget: int = 14000,
                     lang: str = "zh", *, window_days: int = 30,
                     retrospective: bool = False) -> PackResult:
    """The spine's evidence pack within ``budget`` chars: dossier executive summary and
    scenario sections, the situation brief, the as_of-split timeline lanes and key metrics,
    filled by share (SPINE_CAPS) with leftover in SPINE_PRIORITY order. A lane cut to its
    share loses its oldest (developments) or latest (scheduled) lines, never its header.
    ``retrospective`` as in ``build_binary_pack``."""
    report = str(research_report or "")
    situation = str(situation_text or "").strip()
    metrics = str(key_metrics_text or "").strip()
    today = _as_date(now)
    budget_n = _budget(budget)
    input_sha = _input_sha("spine", research_report=report, situation_text=situation,
                           key_metrics_text=metrics, timeline=timeline, as_of=as_of_raw,
                           now=today.isoformat() if today else None, budget=budget_n,
                           lang=_lang_key(lang), window_days=int(window_days),
                           retrospective=bool(retrospective))
    telemetry: Dict[str, Any] = {"kind": "spine", "budget": budget_n,
                                 "as_of": str(as_of_raw or ""), "lang": _lang_key(lang)}
    as_of = validate_pack_as_of(as_of_raw, now)
    if as_of is None:
        return _result("", STATUS_AS_OF_INVALID, telemetry, input_sha)
    telemetry["as_of"] = as_of.isoformat()
    if budget_n is None:
        return _result("", STATUS_BUDGET_INVALID, telemetry, input_sha)
    tpl = _HEADERS[_lang_key(lang)]
    kept_sections, dropped = dedupe_sections(split_h2(report))
    dossier = {cls: [s for s in kept_sections if s.cls == cls]
               for cls in (CLASS_EXECUTIVE_SUMMARY, CLASS_SCENARIO)}
    lanes, lane_telemetry = _lanes(timeline, as_of, now, window_days, lang,
                                   dev_items=SPINE_DEV_MAX_ITEMS, dev_chars=SPINE_DEV_ITEM_CHARS,
                                   sched_items=SPINE_SCHED_MAX_ITEMS,
                                   sched_chars=SPINE_SCHED_ITEM_CHARS, retrospective=retrospective)
    lane_text = {name: (lanes[name].render() if name in lanes else "")
                 for name in ("developments", "scheduled")}
    header = tpl["dossier"]
    reserve = (len(header) + 1 + len(PIECE_SEP)) if any(dossier.values()) else 0
    streams = [
        (CLASS_EXECUTIVE_SUMMARY, [s.text for s in dossier[CLASS_EXECUTIVE_SUMMARY]]),
        (CLASS_SCENARIO, [s.text for s in dossier[CLASS_SCENARIO]]),
        ("situation", [situation] if situation else []),
        ("developments", [lane_text["developments"]] if lane_text["developments"] else []),
        ("scheduled", [lane_text["scheduled"]] if lane_text["scheduled"] else []),
        ("key_metrics", [metrics] if metrics else []),
    ]
    fill = priority_fill(streams, max(0, budget_n - reserve), SPINE_CAPS)
    excerpt = _render_dossier(fill, dossier)
    blocks: List[str] = []
    if excerpt:
        blocks.append(header + "\n" + PIECE_SEP.join(excerpt))
    for name in ("situation", "developments", "scheduled", "key_metrics"):
        blocks.extend(text for _idx, text in fill.kept.get(name, []))
    text = PIECE_SEP.join(blocks)
    telemetry.update({
        "dossier_chars": len(report), "sections": _sections_telemetry(kept_sections, dropped),
        "streams": fill.telemetry, "lanes": lane_telemetry,
    })
    if not text:
        return _result("", STATUS_EMPTY, telemetry, input_sha)
    return _result(text, STATUS_OK, telemetry, input_sha)
