"""Verbatim evidence spans for v3 research findings (RESEARCH-7).

With RESEARCH_EVIDENCE_QUOTES on, a research agent ends each finding with
``EVIDENCE: "<passage>"``: a passage it says it copied from a page or a search
result it was shown.  This module decides, deterministically and without any
model call, whether such a passage really is in the stored text of the cited
source, and where:

* :func:`normalize_for_match` maps text to a comparison form that ignores what
  copying legitimately changes — Unicode compatibility forms (full-width
  digits, ligatures), markdown emphasis, links, images and heading/quote
  leads, bare URLs, table pipes, quote marks, dash variants, the page's own
  ``[S<n>]`` labels and the ``page-`` prefix the tool layer writes into them
  (``research_gateway.neutralize_citation_markers``), case and whitespace
  (zero-width characters, whitespace next to CJK text and whitespace inside
  punctuation included) — with a map from normalized positions back to raw
  offsets;
* :func:`split_quote` cuts a quote at its elisions: ``…``, ``...`` and the
  gateway's instruction-removal marker;
* :func:`locate_span` finds a quote exactly, normalized, or as ordered elided
  segments no more than ``max_gap`` normalized characters apart;
  :func:`quote_in_bounds` tells a quote it never looks for (too short to be
  specific, or too long) from one it did not find;
* :func:`near_miss` tells a quote that starts or ends verbatim (a paraphrase)
  from an invention — telemetry only;
* :func:`evidence_window` is the page text around a located span (widened to
  the whole markdown table and up to three caption lines when the span sits in
  a table) whose numbers a VERIFIED finding must state.

Linear time: every regular expression below is anchored on a literal or a
line start and uses bounded, bracket-free repetition; substring search is
``str.find`` (bounded to a window for segmented quotes, which try at most
MAX_ANCHOR_TRIES placements of their first segment); normalization is a fixed
number of passes over the text.

The idea of asking the model for verbatim evidence is FinanceHarness's; the
verification is DRF's own (patterned on the legacy
``deerflow_research._supporting_span``, which stays untouched) and no
FinanceHarness code or prompt text is used.
"""

from __future__ import annotations

import re
import unicodedata
from array import array
from dataclasses import dataclass
from typing import Any, Sequence

from research_gateway import INSTRUCTION_REMOVED

__all__ = [
    "BASIS_EXACT",
    "BASIS_NORMALIZED",
    "BASIS_SEGMENTED",
    "MatchText",
    "SpanMatch",
    "evidence_window",
    "locate_span",
    "near_miss",
    "normalize_for_match",
    "quote_in_bounds",
    "split_quote",
]

BASIS_EXACT = "exact"
BASIS_NORMALIZED = "normalized"
BASIS_SEGMENTED = "segmented"
# Normalized length bounds of a quote :func:`locate_span` looks for: a shorter
# one ("176 GW in 2023") would match by coincidence, a longer one is no span.
MIN_QUOTE_CHARS = 20
MAX_QUOTE_CHARS = 500
# Head and tail probes of :func:`near_miss` (normalized characters).
NEAR_MISS_PROBE_CHARS = 24
# Placements of a segmented quote's first segment that are tried before the
# quote counts as not found (a page repeating that segment more often than this
# is boilerplate, and the bound keeps the search linear).
MAX_ANCHOR_TRIES = 64
# Lines of the paragraph right above a markdown table (its last ones) that
# :func:`evidence_window` keeps as the table's caption.
CAPTION_LINES = 3

# Markdown images and links (the link's anchor text is kept), bare URLs (ASCII
# only, so CJK text written right after a URL survives), the page's own source
# labels and the "page-" prefix the tool layer writes into them, and heading /
# blockquote leads.
_IMAGE_RE = re.compile(r"!\[[^\[\]\n]{0,300}\]\([^()\s]{0,500}\)")
_LINK_RE = re.compile(r"\[([^\[\]\n]{0,300})\]\([^()\s]{0,500}\)")
_URL_RE = re.compile(r"(?:https?://|www\.)[!-~]+", re.I)
_LABEL_RE = re.compile(r"\[(?:page-)?S\d{1,9}\]", re.I)
_PAGE_PREFIX_RE = re.compile(r"page-(?=S\d)", re.I)
_LINE_LEAD_RE = re.compile(r"^[ \t]*((?:[#>][ \t]*)+)", re.M)
# Characters copying may add or lose: emphasis/code markers, every quote-mark
# family (straight, curly, low-9, CJK corner, guillemets) and zero-width
# characters (soft hyphen included).
_DROPPED = frozenset("*_`" "\"'\u201c\u201d\u2018\u2019\u201e\u201f\u201a\u201b\u300c\u300d\u300e\u300f"
                     "\u00ab\u00bb\u2039\u203a\u301d\u301e\u301f\uff02\uff07"
                     "\u200b\u200c\u200d\u2060\ufeff\u00ad")
_DASHES = {ch: "-" for ch in "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"}
# Whitespace is dropped before closing and after opening punctuation, so a
# deleted label or link target ("in 2022 [S1], according") leaves no space the
# copied text lacks ("in 2022, according").
_NO_SPACE_BEFORE = frozenset(",.;:!?)]}%")
_NO_SPACE_AFTER = frozenset("([{")
# A quote's elisions: three or more dots, the ellipsis character and the
# gateway's instruction-removal marker; the brackets an elision is often
# written in ("[...]", "(…)") are trimmed from the segments' edges.
_ELISION_RE = re.compile(r"\.{3,}|…+|" + re.escape(INSTRUCTION_REMOVED))
_SEGMENT_EDGES = " \t\r\n[]()（）【】<>"


@dataclass(frozen=True)
class SpanMatch:
    """A located quote: how it matched and its raw ``[start, end)`` offsets
    in the text it was located in."""

    basis: str
    start: int
    end: int


def _is_cjk(ch: str) -> bool:
    code = ord(ch)
    return (0x2E80 <= code <= 0x9FFF or 0xAC00 <= code <= 0xD7AF or 0xF900 <= code <= 0xFAFF
            or 0xFE30 <= code <= 0xFE4F or 0xFF00 <= code <= 0xFFEF or 0x20000 <= code <= 0x3FFFF)


def _nfkc(text: str) -> tuple[str, array | None, array | None]:
    """NFKC of ``text`` with each output character's raw ``[start, end)``;
    ``None`` maps mean the identity (the text was already normalized).
    Normalized per base character plus its combining marks, so a raw offset
    is never inside a character the output merged."""
    if text.isascii() or unicodedata.is_normalized("NFKC", text):
        return text, None, None
    out: list[str] = []
    starts = array("q")
    ends = array("q")
    i, n = 0, len(text)
    while i < n:
        j = i + 1
        while j < n and unicodedata.combining(text[j]):
            j += 1
        piece = text[i] if j == i + 1 and ord(text[i]) < 128 else unicodedata.normalize("NFKC", text[i:j])
        for ch in piece:
            out.append(ch)
            starts.append(i)
            ends.append(j)
        i = j
    return "".join(out), starts, ends


def _deleted(text: str) -> bytearray:
    """1 for every character of (NFKC) ``text`` that matching ignores: images,
    link syntax around its anchor, bare URLs, source labels, the ``page-``
    prefix and heading/blockquote leads."""
    dead = bytearray(len(text))

    def kill(start: int, end: int) -> None:
        if end > start:
            dead[start:end] = b"\x01" * (end - start)

    for match in _IMAGE_RE.finditer(text):
        kill(match.start(), match.end())
    for match in _LINK_RE.finditer(text):
        kill(match.start(), match.start() + 1)
        kill(match.end(1), match.end())
    for pattern in (_URL_RE, _LABEL_RE, _PAGE_PREFIX_RE):
        for match in pattern.finditer(text):
            kill(match.start(), match.end())
    for match in _LINE_LEAD_RE.finditer(text):
        kill(match.start(1), match.end(1))
    return dead


def _normalize(text: str, *, need_map: bool = True) -> tuple[str, array | None, array | None]:
    """``(normalized text, raw starts, raw ends)`` of each normalized
    character (see the module docstring); the maps are ``None`` without
    ``need_map``."""
    mid, mid_starts, mid_ends = _nfkc(str(text or ""))
    dead = _deleted(mid)
    out: list[str] = []
    starts = array("q") if need_map else None
    ends = array("q") if need_map else None
    pending = -1  # mid index of the first whitespace of a run not yet emitted
    previous_cjk = False
    for j, ch in enumerate(mid):
        if dead[j] or ch in _DROPPED:
            continue
        if ch == "|" or ch.isspace():
            if out and pending < 0:
                pending = j
            continue
        ch = _DASHES.get(ch, ch)
        cjk = _is_cjk(ch)
        if pending >= 0:
            if not (previous_cjk or cjk or ch in _NO_SPACE_BEFORE or out[-1] in _NO_SPACE_AFTER):
                out.append(" ")
                if need_map:
                    starts.append(pending if mid_starts is None else mid_starts[pending])
                    ends.append(pending + 1 if mid_ends is None else mid_ends[pending])
            pending = -1
        folded = ch.casefold()
        out.append(folded)
        if need_map:
            start = j if mid_starts is None else mid_starts[j]
            end = j + 1 if mid_ends is None else mid_ends[j]
            for _ in folded:
                starts.append(start)
                ends.append(end)
        previous_cjk = cjk
    return "".join(out), starts, ends


def normalize_for_match(text: Any) -> tuple[str, Sequence[int]]:
    """``(normalized text, idx)``: the comparison form of ``text`` and, for
    each normalized character, the raw offset it came from."""
    norm, starts, _ = _normalize(str(text or ""))
    return norm, starts


class MatchText:
    """A text quotes are located in, normalized once on first need (a page is
    matched against every quote of every finding that cites it)."""

    __slots__ = ("raw", "_normalized")

    def __init__(self, raw: Any) -> None:
        self.raw = str(raw or "")
        self._normalized: tuple[str, array | None, array | None] | None = None

    def normalized(self) -> tuple[str, array | None, array | None]:
        if self._normalized is None:
            self._normalized = _normalize(self.raw)
        return self._normalized


def _as_match_text(text: Any) -> MatchText:
    return text if isinstance(text, MatchText) else MatchText(text)


def split_quote(quote: Any) -> list[str]:
    """The segments of a quote between its elisions (``…``, ``...``,
    :data:`research_gateway.INSTRUCTION_REMOVED`), NFKC-normalized, with
    elision brackets and whitespace trimmed from their edges; empty ones
    dropped."""
    text = unicodedata.normalize("NFKC", str(quote or ""))
    pieces = (piece.strip(_SEGMENT_EDGES) for piece in _ELISION_RE.split(text))
    return [piece for piece in pieces if piece]


def _quote_segments(quote: Any) -> list[str]:
    """The normalized, non-empty segments of a quote (:func:`split_quote`)."""
    return [norm for norm in (_normalize(piece, need_map=False)[0] for piece in split_quote(quote)) if norm]


def quote_in_bounds(quote: Any, min_chars: int = MIN_QUOTE_CHARS, max_chars: int = MAX_QUOTE_CHARS) -> bool:
    """Whether the normalized length of ``quote`` (its segments together) lies
    within ``[min_chars, max_chars]``: :func:`locate_span` never locates a
    quote outside these bounds, wherever it is."""
    return min_chars <= sum(len(segment) for segment in _quote_segments(quote)) <= max_chars


def locate_span(page: Any, quote: Any, min_chars: int = MIN_QUOTE_CHARS, max_chars: int = MAX_QUOTE_CHARS,
                max_gap: int = 400, min_segment: int = 12) -> SpanMatch | None:
    """Where ``quote`` is in ``page`` (a str or a :class:`MatchText`), or None.

    The quote's normalized length (its segments together) must lie within
    ``[min_chars, max_chars]`` (:func:`quote_in_bounds`).  Tried in order:

    * ``exact`` — the stripped quote is a substring of the raw page;
    * ``normalized`` — a quote without elisions is a substring of the page
      once both are normalized (:func:`normalize_for_match`);
    * ``segmented`` — a quote with elisions: its segments of at least
      ``min_segment`` normalized characters (shorter ones are ignored; they
      must still total ``min_chars``) appear in order, each starting at most
      ``max_gap`` normalized characters after the previous one ends.

    Offsets are raw page offsets from the first located character to the end
    of the last."""
    text = _as_match_text(page)
    raw_quote = str(quote or "").strip()
    if not text.raw or not raw_quote:
        return None
    segments = _quote_segments(raw_quote)
    if not min_chars <= sum(len(segment) for segment in segments) <= max_chars:
        return None
    position = text.raw.find(raw_quote)
    if position >= 0:
        return SpanMatch(BASIS_EXACT, position, position + len(raw_quote))
    norm, starts, ends = text.normalized()
    if len(segments) == 1:
        position = norm.find(segments[0])
        if position < 0:
            return None
        return SpanMatch(BASIS_NORMALIZED, starts[position], ends[position + len(segments[0]) - 1])
    kept = [segment for segment in segments if len(segment) >= min_segment]
    if not kept or sum(len(segment) for segment in kept) < min_chars:
        return None
    first = kept[0]
    anchor = norm.find(first)
    tries = 0
    while anchor >= 0 and tries < MAX_ANCHOR_TRIES:
        tries += 1
        end = anchor + len(first)
        for segment in kept[1:]:
            found = norm.find(segment, end, end + max_gap + len(segment))
            if found < 0:
                break
            end = found + len(segment)
        else:
            return SpanMatch(BASIS_SEGMENTED, starts[anchor], ends[end - 1])
        anchor = norm.find(first, anchor + 1)
    return None


def near_miss(page: Any, quote: Any) -> bool:
    """True when a quote that was not located starts or ends verbatim: the
    first NEAR_MISS_PROBE_CHARS normalized characters of its first segment or
    the last ones of its last segment are in the normalized page (a
    paraphrase of a real passage rather than an invention).  Telemetry only."""
    segments = _quote_segments(quote)
    if not segments:
        return False
    norm = _as_match_text(page).normalized()[0]
    probes = [probe for probe in (segments[0][:NEAR_MISS_PROBE_CHARS], segments[-1][-NEAR_MISS_PROBE_CHARS:])
              if len(probe) == NEAR_MISS_PROBE_CHARS]
    return any(probe in norm for probe in probes)


def _line_start(text: str, position: int) -> int:
    return text.rfind("\n", 0, position) + 1


def _line_end(text: str, position: int) -> int:
    end = text.find("\n", position)
    return len(text) if end < 0 else end


def _is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|")


def _table_bounds(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Raw ``[top, bottom)`` of the markdown table a span starts or ends in,
    with its caption (the last CAPTION_LINES lines at most of the paragraph
    right above it, blank lines between them skipped), or None."""
    first = _line_start(text, start)
    last = _line_start(text, max(start, end - 1))
    if not (_is_table_row(text[first:_line_end(text, first)]) or _is_table_row(text[last:_line_end(text, last)])):
        return None
    top = first
    while top > 0:
        above = _line_start(text, top - 1)
        if not _is_table_row(text[above:top - 1]):
            break
        top = above
    bottom = _line_end(text, last)
    while bottom < len(text):
        below_end = _line_end(text, bottom + 1)
        if not _is_table_row(text[bottom + 1:below_end]):
            break
        bottom = below_end
    captions = 0
    cursor = top
    while cursor > 0 and captions < CAPTION_LINES:
        above = _line_start(text, cursor - 1)
        line = text[above:cursor - 1]
        if _is_table_row(line) or (captions and not line.strip()):
            break
        if line.strip():
            captions += 1
            top = above
        cursor = above
    return top, bottom


def _widen_number(text: str, start: int, end: int) -> tuple[int, int]:
    """``[start, end)`` moved outward off any digit run it cuts, so a window
    never holds a partial number ("234" of "1,234")."""
    def in_number(ch: str) -> bool:
        return ch.isdigit() or ch in ".,"

    while start > 0 and in_number(text[start - 1]) and in_number(text[start]):
        start -= 1
    while end < len(text) and in_number(text[end - 1]) and in_number(text[end]):
        end += 1
    return start, end


def evidence_window(page: Any, match: SpanMatch, radius: int = 200) -> str:
    """The raw page text within ``radius`` characters of a located span (cut
    off no number), widened to the whole markdown table and up to
    CAPTION_LINES caption lines above it when the span starts or ends in a
    table row."""
    text = _as_match_text(page).raw
    if not text:
        return ""
    start = max(0, min(match.start, len(text)))
    end = max(start, min(match.end, len(text)))
    top, bottom = _widen_number(text, max(0, start - radius), min(len(text), end + radius))
    table = _table_bounds(text, start, end) if end > start else None
    if table is not None:
        top, bottom = min(top, table[0]), max(bottom, table[1])
    return text[top:bottom]
