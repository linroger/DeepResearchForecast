"""EVAL-2: deterministic settlement events for market-anchored binary forecasts.

Nothing in DRF ever resolved a forecast target, so calibration stayed at n=0.
This module is the pure writer-side decision logic (no LLM, no network, no
clock, no I/O): given the binaries of one published forecast and the Gamma
resolution states that ``scripts/resolution_monitor.py`` fetched, it decides
which items settled, which stay pending (and why), and which are past their
grace period with no settlement. The monitor appends the resulting events to
``resolutions.jsonl`` through ``forecast_ledger.append_market_resolution``
(same idempotency key and lock), so every v2 fact is an additive field on the
existing row shape.

Honesty rules (all fail closed):

- ``outcome_known_at`` is the Gamma ``closedTime`` when it is not after
  processing (``known_at_basis='source'``); otherwise it is the processing time,
  an upper bound (``'processing_upper_bound'``). ``endDate`` is a scheduled end,
  never a known-at time.
- ``prospective`` needs a lower-bound proof that the outcome was unknown at the
  forecast origin, max(end of the as-of day, created_at): a source/attested
  known-at after it, or, on the upper-bound basis, a research-time market price
  strictly inside (0.01, 0.99) with a market end after the as-of date. Anything
  else is ``'unknown'`` and never scored.
- ``scoring_eligible`` needs a production primary forecast target, a complete,
  byte-bound anchor at the configured equivalence floor whose end date matches
  the binary's resolution date, a proven-prospective item and a YES/NO
  settlement. UMA proposals or disputes, open markets and unconverged prices
  stay pending; 50/50 settlements are recorded but never scored; items still
  unsettled ``grace_days`` after their resolution date get one never-scored
  terminal event, and an item whose market the source never answered for is
  never ended.
- Each use of a binary's resolution date fails closed on its own side, because
  both write append-only facts. Dates are read by ``utils.deadline_dates`` in
  every written form (ISO, 'June 30, 2027', '2028年12月31日', '30.06.2027',
  'Q2 2027', 'mid-2027', '2027-06', 'end-2027' ...), never ISO only. A grace
  terminal waits for the LATEST plausible deadline: every date the binary names
  and the end of its ``horizon_year`` (``settlement_resolution_date``), so a
  baseline or a missed date never ends an item early. The end-date check holds
  a market's end to a window (``eligibility_window``): no later than a week
  after the EARLIEST deadline named on or after the forecast origin (or the end
  of ``horizon_year``), so a later publication date never admits a market that
  resolves a later window; and no earlier than a week before the deadline the
  statement itself commits to (the latest date it names, else the end of its
  ``horizon_year``), so a market that closes while the binary can still resolve
  YES never labels it. A range names its end as the deadline. A
  deadline-shaped date that is not a real or pinnable day ('2027-02-30',
  'early 2027'), or a statement whose every date lies before the origin, makes
  the end date unverifiable.
- An item that already holds a terminal row is final: a market that settles
  later never adds a second fact for it (``already_terminal``).

EVAL-3 adds the reader side (no I/O, inputs never mutated; the only clock is
``admissible``'s default ``now`` when no as-of date is given):
``fold_binary_items`` and ``resolved_view`` fold the events of one item into a
single fact (scoring-eligible settled > ineligible settled > terminal; eligible
events that disagree are a ``conflict``), ``admissible`` is the one
point-in-time gate every calibration consumer calls, and
``is_scoreable_resolution`` keeps unmatched or ambiguous scenario outcomes from
being scored as an all-miss.
"""

from __future__ import annotations

import copy
import math
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from ..utils.deadline_dates import DateMention, scan_date_mentions
from ..utils.point_in_time import parse_stamp_strict
from ..utils.prediction_markets import current_uma_status, parse_market_end
from .ensemble import _norm_name
from .forecast_extractor import (
    _MARKET_EQUIVALENCE_RANK,
    _market_anchor_complete,
    audit_market_anchor_integrity,
)
from .forecast_ledger import (
    _RANGE_JOIN,
    MARKET_RESOLUTION_EVENT_SCHEMA_VERSION,
    binary_resolution_date,
    is_production_primary_commit,
)

BASIS_SOURCE = "source"
BASIS_ATTESTED = "attested"
BASIS_PROCESSING_UPPER_BOUND = "processing_upper_bound"
SOURCE_KIND_MARKET = "polymarket"
SOURCE_KIND_TERMINAL = "terminal"
TERMINAL_MARKET_ID = "terminal"
TERMINAL_REASON = "unresolvable_after_grace"
# The forecast target is an ensemble member, what-if, comparison, revision or evaluation
# commit: its settlement must never label production calibration (I-21).
NOT_PRODUCTION_PRIMARY = "not_production_primary"
ITEM_KIND_BINARY = "binary"
# A market may end up to a week on either side of the binary's deadline (settlement lag,
# time zones); outside that window it resolves a different period.
END_DATE_TOLERANCE = timedelta(days=7)
# Two dates joined like this name a window whose START is no deadline: the connectors of
# forecast_ledger's range regex, plus 'through'/'until'/'到'.
_RANGE_GAP_RE = re.compile(rf"{_RANGE_JOIN}|\s*(?:through|thru|until|till|到)\s*", re.IGNORECASE)
_BETWEEN_AND_RE = re.compile(r"\s*(?:and|&|与|和)\s*", re.IGNORECASE)
_BETWEEN_BEFORE_RE = re.compile(r"(?:between|介于)\s*$", re.IGNORECASE)
_BETWEEN_AFTER_RE = re.compile(r"^\s*之间")
# A research-time price strictly inside this band proves the market was unsettled then.
_UNSETTLED_PRICE_LO = 0.01
_UNSETTLED_PRICE_HI = 0.99
# UMA statuses that are not final: a proposal can still be disputed, a dispute re-voted.
_UMA_PENDING_MARKERS = ("propos", "disput")
_RESOLUTION_STATUSES = ("settled", "ambiguous", "unknown")

Prospective = Union[bool, str]


def _finite(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _end_of_utc_day(value: Any) -> Optional[datetime]:
    """Last instant of the UTC day a strict stamp falls on (a date covers its whole day)."""
    moment = parse_stamp_strict(value)
    if moment is None:
        return None
    start = datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)
    try:
        return start + timedelta(days=1) - timedelta(microseconds=1)
    except OverflowError:  # 9999-12-31: no representable end of day → unreadable stamp
        return None


def _latest_instant(value: Any) -> Optional[datetime]:
    """Latest instant a strict stamp can denote: a date-time itself, a bare date its day's end."""
    moment = parse_stamp_strict(value, allow_date=False)
    return moment if moment is not None else _end_of_utc_day(value)


def known_at(resolution: Optional[Dict[str, Any]], processed_at: str) -> Tuple[str, str, bool]:
    """``(outcome_known_at, known_at_basis, known_at_clamped)`` for one market resolution.

    A source close time (``resolution['closed_time']``) not after processing is
    exact (``'source'``). A close time after processing cannot be right for an
    outcome already observed, so it is clamped to the processing time
    (``'processing_upper_bound'``, clamped). A missing one falls back to the
    processing time as an upper bound, unclamped. Raises ``ValueError`` when
    ``processed_at`` is not an offset-aware ISO date-time.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    raw = resolution.get("closed_time") if isinstance(resolution, dict) else None
    closed = parse_stamp_strict(raw, allow_date=False)
    if closed is not None and closed <= processed:
        return closed.isoformat(), BASIS_SOURCE, False
    return processed.isoformat(), BASIS_PROCESSING_UPPER_BOUND, closed is not None


def _range_starts(text: str, mentions: List[DateMention]) -> Set[int]:
    """Indexes of the mentions that open a range ('between A and B', 'A to B', 'A–B',
    'A至B'): a window's start, never its deadline. Its end stays a deadline."""
    starts: Set[int] = set()
    for index in range(len(mentions) - 1):
        first, second = mentions[index], mentions[index + 1]
        gap = text[first.end:second.start]
        if _RANGE_GAP_RE.fullmatch(gap) or (
                _BETWEEN_AND_RE.fullmatch(gap)
                and (_BETWEEN_BEFORE_RE.search(text[:first.start])
                     or _BETWEEN_AFTER_RE.match(text[second.end:]))):
            starts.add(index)
    return starts


def _horizon_year_end(binary: Dict[str, Any]) -> Optional[str]:
    try:
        return binary_resolution_date({"horizon_year": binary.get("horizon_year")})
    except OverflowError:  # horizon_year 'inf': no year, so no resolution date
        return None


def settlement_resolution_date(binary: Any) -> Optional[str]:
    """The date a grace terminal waits for: the LATEST of every date named in
    ``resolution_criteria``, ``resolution_source`` or ``statement`` (in any written
    form, each at the latest day it can plausibly mean, so an invalid '2027-02-30'
    counts as 2027-02-28 and a vague 'early 2027' as 2027-06-30) and 31 Dec of
    ``horizon_year``; None when there is none of them.

    A grace terminal is an append-only fact: a late date only delays it, an early
    one ends an item that can still resolve, for good. So nothing named can pull
    the date earlier: not a baseline ('FYE 2026-05-31') beside a deadline written
    as '2028年12月31日', not a deadline the scanner reads as a period end, and not a
    ``horizon_year`` later than every named date. The end-date check needs the
    opposite direction and uses ``eligibility_window``.
    """
    if not isinstance(binary, dict):
        return None
    latest = [mention.latest
              for key in ("resolution_criteria", "resolution_source", "statement")
              for mention in scan_date_mentions(str(binary.get(key) or ""))]
    horizon_end = _horizon_year_end(binary)
    if horizon_end:
        latest.append(date.fromisoformat(horizon_end))
    return max(latest).isoformat() if latest else None


def _deadline_candidates(text: str, origin_day: Optional[date]
                         ) -> Tuple[bool, List[date], bool]:
    """``(names_a_date, deadlines, unverifiable)`` for one field of a binary.

    ``deadlines`` are the pinned days on or after ``origin_day`` (all of them without
    an origin) that do not open a range. ``unverifiable`` is True when a date-shaped
    span that is not a real or pinnable day ('2027-02-30', '06/07/2027', 'early 2027')
    could be on or after the origin: it may be the deadline, so no market can be
    checked against this binary.
    """
    mentions = scan_date_mentions(text)
    starts = _range_starts(text, mentions)
    deadlines: List[date] = []
    for index, mention in enumerate(mentions):
        if mention.day is None:
            if origin_day is None or mention.latest >= origin_day:
                return bool(mentions), [], True
            continue
        if index not in starts and (origin_day is None or mention.day >= origin_day):
            deadlines.append(mention.day)
    return bool(mentions), deadlines, False


def eligibility_window(binary: Any, origin: Any = None) -> Optional[Tuple[str, str]]:
    """``(earliest, latest)``: the deadlines a market's end date is held to; None when
    the binary's deadline cannot be verified.

    Candidates are the dates named in ``statement`` and ``resolution_criteria`` (any
    written form) on or after the UTC day of ``origin`` (the forecast's as-of date or
    creation stamp); a range contributes its end only. Without a readable origin every
    named date counts. ``resolution_source`` says where and when the answer is
    published, so it is never read.

    - ``earliest`` = the earliest candidate or 31 Dec of ``horizon_year``, whichever
      is first. A later date may be a publication or verification date ('on
      2027-12-31 ... published by 2028-03-31'), so it can never loosen the late side:
      an early deadline only costs a label, a late one lets a market that resolves a
      later window label the binary for good.
    - ``latest`` = the deadline the statement itself commits to: the latest
      candidate it names, else 31 Dec of ``horizon_year`` (the period a dateless
      statement covers), else the latest candidate the criteria name. An earlier
      date may be an interim observation point ('any quarter from Q3 2026 ... before
      the end of 2027'), so it can never loosen the early side: a market that closes
      before the binary's own deadline could label as NO a binary that can still
      resolve YES. Criteria dates never set this side when the statement or
      ``horizon_year`` does, because a criteria date after the period is usually its
      publication date ('calendar year 2030 ... published by 2031-06-30').

    None (unverifiable) when a deadline-shaped date could not be pinned (see
    ``_deadline_candidates``), when the statement names dates but every one of them
    lies before the origin (the forecast was issued after its own deadline, so no
    later date in the text can stand in for it), or when there is neither a
    candidate nor a readable ``horizon_year``.
    """
    if not isinstance(binary, dict):
        return None
    origin_moment = parse_stamp_strict(origin)
    origin_day = origin_moment.date() if origin_moment is not None else None
    statement_named, statement_deadlines, statement_blocked = _deadline_candidates(
        str(binary.get("statement") or ""), origin_day)
    _, criteria_deadlines, criteria_blocked = _deadline_candidates(
        str(binary.get("resolution_criteria") or ""), origin_day)
    if statement_blocked or criteria_blocked:
        return None
    if statement_named and not statement_deadlines:
        return None
    horizon_iso = _horizon_year_end(binary)
    horizon_end = date.fromisoformat(horizon_iso) if horizon_iso else None
    candidates = statement_deadlines + criteria_deadlines
    late_side = candidates + ([horizon_end] if horizon_end else [])
    if not late_side:
        return None
    earliest = min(late_side)
    if statement_deadlines:
        latest = max(statement_deadlines)
    else:
        latest = horizon_end or max(criteria_deadlines)
    return earliest.isoformat(), latest.isoformat()


def eligibility_deadline(binary: Any, origin: Any = None) -> Optional[str]:
    """The earliest deadline of ``eligibility_window`` (None when unverifiable)."""
    window = eligibility_window(binary, origin)
    return window[0] if window else None


def market_eligibility(binary: Any, anchor: Any, min_equivalence: str = "exact", *,
                       origin: Any = None) -> Tuple[bool, Optional[str]]:
    """``(ok, reason)``: may this anchor's market settlement label ``binary``?

    Reasons, checked in order: ``anchor_incomplete`` (forecast_extractor's
    completeness contract, which admits only an ``exact`` or ``near``
    equivalence, so a ``loose`` or missing one always stops here),
    ``binding_invalid`` (the anchor-integrity audit: wrong proposition, or a
    contract hash that no longer matches the binary's statement and criteria),
    ``equivalence_<level>`` below the ``min_equivalence`` floor (unknown floors
    act as ``exact``; a ``loose`` floor therefore admits what ``near`` does),
    ``end_date_unverifiable`` (an unparseable market end, or a binary whose
    deadline ``eligibility_window`` cannot verify) and ``end_date_mismatch`` (the
    market ends more than END_DATE_TOLERANCE after the window's earliest deadline
    or before its latest one), where ``origin`` is the forecast's as-of date, else
    its creation stamp.
    """
    if not isinstance(binary, dict) or not isinstance(anchor, dict):
        return False, "anchor_incomplete"
    if not _market_anchor_complete(anchor):
        return False, "anchor_incomplete"
    probe = dict(binary)
    probe["market_anchor"] = anchor
    if audit_market_anchor_integrity({"binary_forecasts": [probe]}).get("issue_count"):
        return False, "binding_invalid"
    floor = _MARKET_EQUIVALENCE_RANK.get(str(min_equivalence or "").strip().lower(),
                                         _MARKET_EQUIVALENCE_RANK["exact"])
    equivalence = str(anchor.get("resolution_equivalence") or "").strip().lower()
    if _MARKET_EQUIVALENCE_RANK.get(equivalence, 0) < floor:
        level = equivalence if equivalence in _MARKET_EQUIVALENCE_RANK else "missing"
        return False, f"equivalence_{level}"
    market_end = parse_market_end(anchor.get("endDate"))
    window = eligibility_window(binary, origin)
    if market_end is None or window is None:
        return False, "end_date_unverifiable"
    earliest_end = parse_market_end(window[0])  # the end of that UTC day
    latest_day = date.fromisoformat(window[1])
    latest_start = datetime(latest_day.year, latest_day.month, latest_day.day,
                            tzinfo=timezone.utc)
    if earliest_end is None or market_end > earliest_end + END_DATE_TOLERANCE:
        return False, "end_date_mismatch"
    if market_end < latest_start - END_DATE_TOLERANCE:
        return False, "end_date_mismatch"
    return True, None


def prospective_status(known_at_iso: Any, basis: Any, target_as_of: Any,
                       target_created_at: Any, anchor: Any) -> Prospective:
    """True, False or ``'unknown'``: was the outcome unknown at the forecast origin?

    The origin is max(end of the ``target_as_of`` UTC day, ``target_created_at``),
    so a replay run after its outcome was knowable is never prospective. A
    present but unparseable origin stamp, or no origin at all, is ``'unknown'``.
    Source/attested bases compare the known-at time with the origin. The
    processing upper bound proves nothing about the lower side, so it is True
    only when the anchor's research-time price lies strictly inside (0.01, 0.99)
    and the market ends after the as-of day (after created_at when there is no
    as-of date); otherwise ``'unknown'``.
    """
    as_of_end: Optional[datetime] = None
    if target_as_of not in (None, ""):
        as_of_end = _end_of_utc_day(target_as_of)
        if as_of_end is None:
            return "unknown"
    created: Optional[datetime] = None
    if target_created_at not in (None, ""):
        created = _latest_instant(target_created_at)
        if created is None:
            return "unknown"
    bounds = [bound for bound in (as_of_end, created) if bound is not None]
    if not bounds:
        return "unknown"
    origin = max(bounds)
    if basis in (BASIS_SOURCE, BASIS_ATTESTED):
        known = parse_stamp_strict(known_at_iso)
        return "unknown" if known is None else known > origin
    if basis == BASIS_PROCESSING_UPPER_BOUND and isinstance(anchor, dict):
        price = _finite(anchor.get("price_at_research"))
        market_end = parse_market_end(anchor.get("endDate"))
        reference = as_of_end if as_of_end is not None else created
        if (price is not None and _UNSETTLED_PRICE_LO < price < _UNSETTLED_PRICE_HI
                and market_end is not None and market_end > reference):
            return True
    return "unknown"


def _resolution_status(resolution: Dict[str, Any]) -> str:
    status = resolution.get("resolution_status")
    if status in _RESOLUTION_STATUSES:
        return status
    # Rows without the EVAL-2 key (older parsers, injected fixtures): resolved ⇒ settled.
    return "settled" if resolution.get("resolved") is True else "unknown"


def _market_price_at_research(anchor: Dict[str, Any]) -> Optional[float]:
    price = _finite(anchor.get("price_at_research"))
    return price if price is not None else _finite(anchor.get("implied_yes_prob"))


def _market_event(report_id: str, forecast_id: str, binary: Dict[str, Any],
                  anchor: Dict[str, Any], market_id: str, resolution: Any, *,
                  meta: Dict[str, Any], processed_at: str,
                  min_equivalence: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(event, None)`` for a settled or ambiguous market, else ``(None, pending_reason)``."""
    if not isinstance(resolution, dict):
        return None, "no_resolution_data"
    if resolution.get("closed") is not True and resolution.get("resolved") is not True:
        return None, "market_open"
    status = _resolution_status(resolution)
    yes_price = _finite(resolution.get("resolved_yes_price"))
    y: Optional[int] = None
    if status != "ambiguous":
        # The CURRENT stage: a status history ending in 'resolved' is no longer pending.
        uma = current_uma_status(resolution.get("uma_status"))
        if any(marker in uma for marker in _UMA_PENDING_MARKERS):
            return None, "uma_pending"
        if status != "settled":
            return None, "not_converged"
        if yes_price is None:
            return None, "no_yes_outcome"
        # Same truth rule as the legacy monitor: the final YES price decides the label.
        y = 1 if yes_price >= 0.5 else 0
    known_iso, basis, clamped = known_at(resolution, processed_at)
    prospective = prospective_status(known_iso, basis, meta.get("as_of"),
                                     meta.get("created_at"), anchor)
    # The as-of date (never after created_at) is the earlier origin: the fewer named dates
    # read as baselines, the stricter the end-date check (fail closed).
    origin = meta.get("as_of") if meta.get("as_of") not in (None, "") else meta.get("created_at")
    eligible, eligibility_reason = market_eligibility(binary, anchor, min_equivalence,
                                                      origin=origin)
    if meta.get("production_primary") is False:
        ineligible_reason: Optional[str] = NOT_PRODUCTION_PRIMARY
    elif status == "ambiguous":
        ineligible_reason = "ambiguous_settlement"
    elif not eligible:
        ineligible_reason = eligibility_reason
    elif prospective is not True:
        ineligible_reason = "not_prospective" if prospective is False else "prospective_unknown"
    else:
        ineligible_reason = None
    model_p = _finite(binary.get("probability"))
    brier = round((model_p - y) ** 2, 4) if (model_p is not None and y is not None) else None
    return {
        "report_id": report_id,
        "forecast_id": forecast_id,
        "market_id": market_id,
        "resolved_outcome": resolution.get("resolved_outcome") if y is not None else None,
        "resolved_yes_price": round(yes_price, 4) if yes_price is not None else None,
        "model_p": model_p,
        "market_p_at_research": _market_price_at_research(anchor),
        "brier_contribution": brier,
        "resolved_at": processed_at,
        "schema_version": MARKET_RESOLUTION_EVENT_SCHEMA_VERSION,
        "item_kind": ITEM_KIND_BINARY,
        "source_kind": SOURCE_KIND_MARKET,
        "outcome": None if y is None else ("YES" if y == 1 else "NO"),
        "y": y,
        "outcome_known_at": known_iso,
        "known_at_basis": basis,
        "known_at_clamped": clamped,
        "processed_at": processed_at,
        "prospective": prospective,
        "scoring_eligible": ineligible_reason is None,
        "ineligible_reason": ineligible_reason,
        "resolution_status": status,
        "report_publishable_at_issue": True,
        "target_commit_id": meta.get("commit_id"),
        "evidence": {"market_url": anchor.get("url") or None,
                     "uma_status": resolution.get("uma_status"),
                     "closed_time": resolution.get("closed_time")},
        "terminal_reason": None,
    }, None


def _terminal_event(report_id: str, forecast_id: str, binary: Dict[str, Any],
                    anchor: Optional[Dict[str, Any]], *, meta: Dict[str, Any],
                    processed_at: str, resolution_date: str,
                    grace_days: int) -> Dict[str, Any]:
    """The never-scored event of an item still unsettled after its grace period."""
    source_anchor = anchor or {}
    return {
        "report_id": report_id,
        "forecast_id": forecast_id,
        "market_id": TERMINAL_MARKET_ID,
        "resolved_outcome": None,
        "resolved_yes_price": None,
        "model_p": _finite(binary.get("probability")),
        "market_p_at_research": _market_price_at_research(source_anchor),
        "brier_contribution": None,
        "resolved_at": processed_at,
        "schema_version": MARKET_RESOLUTION_EVENT_SCHEMA_VERSION,
        "item_kind": ITEM_KIND_BINARY,
        "source_kind": SOURCE_KIND_TERMINAL,
        "outcome": None,
        "y": None,
        "outcome_known_at": None,
        "known_at_basis": None,
        "known_at_clamped": False,
        "processed_at": processed_at,
        "prospective": None,
        "scoring_eligible": False,
        "ineligible_reason": TERMINAL_REASON,
        "resolution_status": "terminal",
        "report_publishable_at_issue": True,
        "target_commit_id": meta.get("commit_id"),
        "evidence": {"market_url": source_anchor.get("url") or None,
                     "uma_status": None,
                     "anchor_market_id": str(source_anchor.get("market_id") or "") or None,
                     "resolution_date": resolution_date,
                     "grace_days": grace_days},
        "terminal_reason": TERMINAL_REASON,
    }


def _grace_expired(binary: Dict[str, Any], processed: datetime,
                   grace_days: int) -> Optional[str]:
    """The binary's settlement resolution date when date + grace lies before the processing day."""
    resolution_date = settlement_resolution_date(binary)
    if not resolution_date:
        return None
    try:
        expired = date.fromisoformat(resolution_date) + timedelta(days=grace_days) < processed.date()
    except (ValueError, OverflowError):
        return None
    return resolution_date if expired else None


def _is_terminal_row(event: Dict[str, Any]) -> bool:
    return (event.get("market_id") == TERMINAL_MARKET_ID
            or event.get("source_kind") == SOURCE_KIND_TERMINAL)


def _held_forecast_ids(report_id: str, events: Optional[Iterable[Any]]
                       ) -> Tuple[Set[str], Set[str]]:
    """``(settled, terminal)``: forecast ids of ``report_id`` that already hold a
    non-terminal event, and those that already hold a terminal row, in the ledger."""
    settled: Set[str] = set()
    terminal: Set[str] = set()
    for event in events or []:
        if isinstance(event, dict) and str(event.get("report_id") or "") == report_id:
            forecast_id = str(event.get("forecast_id") or "")
            (terminal if _is_terminal_row(event) else settled).add(forecast_id)
    return settled, terminal


def recorded_items(events: Optional[Iterable[Any]]) -> Set[Tuple[str, str]]:
    """``(report_id, forecast_id)`` pairs that already hold any resolutions row: a
    settled, ambiguous or terminal event, or a legacy settled row. Such an item is
    final; nothing a later sweep decides can be appended for it as a new fact."""
    out: Set[Tuple[str, str]] = set()
    for event in events or []:
        if isinstance(event, dict):
            out.add((str(event.get("report_id") or ""), str(event.get("forecast_id") or "")))
    return out


def anchor_market_id(binary: Any) -> str:
    """The market id of ``binary``'s market anchor ('' when it has none)."""
    anchor = binary.get("market_anchor") if isinstance(binary, dict) else None
    return str(anchor.get("market_id") or "").strip() if isinstance(anchor, dict) else ""


def overdue_since(binaries: Any, processed_at: str) -> Optional[str]:
    """The earliest ``settlement_resolution_date`` among ``binaries``' market-anchored items
    that lies before the processing day, else None: those markets should be closed by now,
    so a capped sweep fetches them first (their grace terminals need a fetch too). Raises
    ``ValueError`` when ``processed_at`` is not an offset-aware ISO date-time."""
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    today = processed.date().isoformat()
    overdue = [day for day in (settlement_resolution_date(binary)
                               for binary in (binaries if isinstance(binaries, list) else [])
                               if anchor_market_id(binary))
               if day and day < today]
    return min(overdue) if overdue else None


def due_binaries(report_id: Any, binaries: Any, recorded: Set[Tuple[str, str]], *,
                 processed_at: str, grace_days: int = 180) -> List[Dict[str, Any]]:
    """The binaries of one target that a settle sweep can act on at ``processed_at``, in order.

    A binary qualifies when it has an id, no row in ``recorded`` (see
    ``recorded_items``) and either a market anchor (only the market source can
    say whether it settled) or no anchor and an expired grace period (its
    terminal needs no network). An unanchored binary still inside its grace
    period has nothing to do yet: a target holding only such items must not
    take a sweep's cap slot for years while older targets wait for their
    terminals. Raises ``ValueError`` when ``processed_at`` is not an
    offset-aware ISO date-time.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    rid = str(report_id or "").strip()
    grace = max(0, int(grace_days))
    due: List[Dict[str, Any]] = []
    for binary in binaries if isinstance(binaries, list) else []:
        if not isinstance(binary, dict):
            continue
        forecast_id = str(binary.get("id") or "").strip()
        if not forecast_id or (rid, forecast_id) in recorded:
            continue
        if anchor_market_id(binary) or _grace_expired(binary, processed, grace):
            due.append(binary)
    return due


def settle_binaries(report_id: Any, binaries: Any, resolutions: Any, *,
                    target_meta: Optional[Dict[str, Any]] = None, processed_at: str,
                    min_equivalence: str = "exact", grace_days: int = 180,
                    existing_events: Optional[Iterable[Any]] = None,
                    answered_market_ids: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """Settlement decisions for one forecast target's binaries.

    ``resolutions`` maps market_id to ``prediction_markets._parse_resolution``
    output; ``target_meta`` is ``{as_of, created_at, commit_id,
    production_primary}`` of the forecast origin, where ``production_primary``
    False (a non-production, revision or evaluation target) makes every market
    event ineligible ``not_production_primary`` and True/None (proven, or a
    legacy report with no ledger row) changes nothing; ``processed_at``
    (offset-aware, ``ValueError`` otherwise) is the only clock, so every
    decision is replayable. ``existing_events`` are the ledger's resolutions
    rows: an item that already holds a non-terminal event never gets a
    terminal one, and an item that already holds a terminal row is final and
    gets nothing (counted in ``already_terminal``): the terminal is an
    append-only fact, so a market that settles after it must not add a second,
    contradicting one (the sweep's ``due_binaries`` skips such items the same
    way). ``answered_market_ids`` are the markets the source answered
    for (``PolymarketClient.fetch_resolutions_answered``: returned, or confirmed
    missing by a successful request for that id alone); None means only the
    markets present in ``resolutions``.

    Returns ``{events, terminal, pending_by_reason, ineligible_by_reason,
    already_terminal}``.
    ``events`` are settled or ambiguous market events (append-ready rows with
    every v2 field); ``terminal`` are grace-expired items without a settlement
    (market_id 'terminal', never scored). Pending reasons: ``no_resolution_data``,
    ``market_open``, ``uma_pending``, ``not_converged``, ``no_yes_outcome``,
    ``no_market_anchor`` and ``missing_forecast_id``. An anchored item without
    resolution data turns terminal only when the source answered for its
    market: a failed request batch (source unreachable) never ends an item.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    processed_iso = processed.isoformat()
    rid = str(report_id or "").strip()
    meta = target_meta if isinstance(target_meta, dict) else {}
    by_market = resolutions if isinstance(resolutions, dict) else {}
    answered = {str(mid or "").strip() for mid in (
        answered_market_ids if answered_market_ids is not None else by_market)}
    grace = max(0, int(grace_days))
    already_settled, already_ended = _held_forecast_ids(rid, existing_events)
    events: List[Dict[str, Any]] = []
    terminal: List[Dict[str, Any]] = []
    pending: Counter = Counter()
    ineligible: Counter = Counter()
    already_terminal = 0
    for binary in binaries if isinstance(binaries, list) else []:
        if not isinstance(binary, dict):
            continue
        forecast_id = str(binary.get("id") or "").strip()
        if not forecast_id:
            pending["missing_forecast_id"] += 1
            continue
        if forecast_id in already_ended:
            already_terminal += 1
            continue
        anchor = binary.get("market_anchor") if isinstance(binary.get("market_anchor"), dict) else None
        market_id = anchor_market_id(binary)
        if market_id:
            event, reason = _market_event(rid, forecast_id, binary, anchor, market_id,
                                          by_market.get(market_id), meta=meta,
                                          processed_at=processed_iso,
                                          min_equivalence=min_equivalence)
            if event is not None:
                events.append(event)
                if not event["scoring_eligible"]:
                    ineligible[event["ineligible_reason"]] += 1
                continue
        else:
            reason = "no_market_anchor"
        resolution_date = _grace_expired(binary, processed, grace)
        if (resolution_date and forecast_id not in already_settled
                and (reason != "no_resolution_data" or market_id in answered)):
            terminal.append(_terminal_event(rid, forecast_id, binary, anchor, meta=meta,
                                            processed_at=processed_iso,
                                            resolution_date=resolution_date,
                                            grace_days=grace))
            continue
        pending[reason] += 1
    return {
        "events": events,
        "terminal": terminal,
        "pending_by_reason": dict(sorted(pending.items())),
        "ineligible_by_reason": dict(sorted(ineligible.items())),
        "already_terminal": already_terminal,
    }


# ---------------------------------------------------------------------------
# EVAL-3: reader side (settlement fold, point-in-time gate, scoreability)
# ---------------------------------------------------------------------------

ITEM_KIND_SCENARIO_SET = "scenario_set"
# The folded status of an item whose scoring-eligible events disagree on the outcome.
RESOLUTION_CONFLICT = "conflict"
# Fields resolved_view fills on each production primary commit row, from its folded
# scenario_set events only (a row with no event gets the unresolved defaults).
_VIEW_DEFAULTS: Dict[str, Any] = {
    "resolved": False, "outcome": None, "outcome_known_at": None, "known_at_basis": None,
    "processed_at": None, "scoring_eligible": False, "prospective": None,
    "resolution_status": None, "ineligible_reason": None,
}
_LATEST_ORDER_KEY = datetime.max.replace(tzinfo=timezone.utc)


def _event_item(event: Dict[str, Any]) -> Dict[str, Any]:
    """One schema_version 2 event as a fold candidate (a new dict; the event is untouched)."""
    status = "terminal" if _is_terminal_row(event) else str(
        event.get("resolution_status") or "unknown")
    return {
        "report_id": str(event.get("report_id") or "").strip(),
        "item_id": str(event.get("forecast_id") or "").strip(),
        "item_kind": event.get("item_kind") or ITEM_KIND_BINARY,
        "market_id": str(event.get("market_id") or "").strip(),
        "source_kind": event.get("source_kind"),
        "resolution_status": status,
        "outcome": event.get("outcome"),
        "y": event.get("y"),
        "model_p": event.get("model_p"),
        "outcome_known_at": event.get("outcome_known_at"),
        "known_at_basis": event.get("known_at_basis"),
        "processed_at": event.get("processed_at"),
        "prospective": event.get("prospective"),
        "scoring_eligible": event.get("scoring_eligible") is True,
        "ineligible_reason": event.get("ineligible_reason"),
        "target_commit_id": event.get("target_commit_id"),
        "schema_version": event.get("schema_version"),
        "legacy": False,
    }


def _legacy_outcome(event: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """``(outcome, reason)`` of a legacy row: the converged final YES price decides
    (>= 0.99 YES, <= 0.01 NO, as the legacy monitor only recorded converged markets);
    without a price, a 'Yes'/'No' resolved_outcome label; anything else has no outcome."""
    yes_price = _finite(event.get("resolved_yes_price"))
    if yes_price is not None:
        if yes_price >= _UNSETTLED_PRICE_HI:
            return "YES", None
        if yes_price <= _UNSETTLED_PRICE_LO:
            return "NO", None
        return None, "not_converged"
    label = str(event.get("resolved_outcome") or "").strip().upper()
    return (label, None) if label in ("YES", "NO") else (None, "no_yes_outcome")


def _binary_targets(targets: Optional[Iterable[Any]]
                    ) -> Dict[Tuple[str, str], Optional[Tuple[Dict[str, Any], Dict[str, Any]]]]:
    """``(report_id, binary id) -> (commit row, binary)`` over the production primary commit
    rows in ``targets``; a key that two rows register maps to None (it proves nothing)."""
    index: Dict[Tuple[str, str], Optional[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}
    for row in targets or []:
        if not is_production_primary_commit(row):
            continue
        report_id = str(row.get("report_id") or "").strip()
        binaries = row.get("binary_forecasts")
        for binary in binaries if isinstance(binaries, list) else []:
            item_id = str(binary.get("id") or "").strip() if isinstance(binary, dict) else ""
            if report_id and item_id:
                key = (report_id, item_id)
                index[key] = None if key in index else (row, binary)
    return index


def _legacy_binary_item(event: Dict[str, Any], targets: Dict[Tuple[str, str], Any]
                        ) -> Dict[str, Any]:
    """A legacy (schema_version 1) row as a fold candidate.

    Its only stamp is ``resolved_at``, a processing time, so the basis is always
    ``processing_upper_bound``. It is scoring-eligible only when a production primary
    v2 commit row registers the binary with this very market as its anchor, the anchor
    passes ``market_eligibility`` at the ``exact`` floor and ``prospective_status``
    proves the outcome was unknown at the forecast origin (research price strictly
    inside (0.01, 0.99), market end after the as-of date); otherwise it is ineligible.
    """
    report_id = str(event.get("report_id") or "").strip()
    item_id = str(event.get("forecast_id") or "").strip()
    market_id = str(event.get("market_id") or "").strip()
    resolved_at = event.get("resolved_at")
    outcome, reason = _legacy_outcome(event)
    prospective: Prospective = "unknown"
    if reason is None:
        target = targets.get((report_id, item_id))
        if target is None:
            reason = "no_v2_target"
        else:
            row, binary = target
            anchor = binary.get("market_anchor")
            if anchor_market_id(binary) != market_id:
                reason = "market_mismatch"
            else:
                as_of, created_at = row.get("as_of_date"), row.get("created_at")
                origin = as_of if as_of not in (None, "") else created_at
                eligible, eligibility_reason = market_eligibility(binary, anchor, "exact",
                                                                  origin=origin)
                prospective = prospective_status(resolved_at, BASIS_PROCESSING_UPPER_BOUND,
                                                 as_of, created_at, anchor)
                if not eligible:
                    reason = eligibility_reason
                elif prospective is not True:
                    reason = "not_prospective" if prospective is False else "prospective_unknown"
    return {
        "report_id": report_id,
        "item_id": item_id,
        "item_kind": ITEM_KIND_BINARY,
        "market_id": market_id,
        "source_kind": SOURCE_KIND_MARKET,
        "resolution_status": "settled" if outcome is not None else "unknown",
        "outcome": outcome,
        "y": None if outcome is None else (1 if outcome == "YES" else 0),
        "model_p": event.get("model_p"),
        "outcome_known_at": resolved_at,
        "known_at_basis": BASIS_PROCESSING_UPPER_BOUND,
        "processed_at": resolved_at,
        "prospective": prospective,
        "scoring_eligible": reason is None,
        "ineligible_reason": reason,
        "target_commit_id": None,
        "schema_version": event.get("schema_version"),
        "legacy": True,
    }


def effective_known_at(item: Any) -> Optional[datetime]:
    """The instant an item's outcome counts as known, or None when it is unverifiable.

    ``outcome_known_at`` on a ``source`` or ``attested`` basis, else ``processed_at``
    (an upper bound). Read with ``parse_stamp_strict`` at the latest instant it can
    denote: a bare date is the end of its UTC day, and a naive, partial or missing
    stamp is None.
    """
    if not isinstance(item, dict):
        return None
    if item.get("known_at_basis") in (BASIS_SOURCE, BASIS_ATTESTED):
        return _latest_instant(item.get("outcome_known_at"))
    return _latest_instant(item.get("processed_at"))


def _fold_tier(item: Dict[str, Any]) -> int:
    """Fold precedence: 2 = scoring-eligible settled outcome, 1 = any other settlement
    fact (ineligible, ambiguous, ...), 0 = grace terminal."""
    if item.get("resolution_status") == "terminal":
        return 0
    if (item.get("scoring_eligible") is True and item.get("resolution_status") == "settled"
            and _norm_name(item.get("outcome"))):
        return 2
    return 1


def _fold_order(item: Dict[str, Any]) -> Tuple[bool, datetime, str, str]:
    """Earliest effective known-at first (an unverifiable stamp last); ties by stamp text
    and market id, so the fold never depends on the order events were appended."""
    known = effective_known_at(item)
    return (known is None, known or _LATEST_ORDER_KEY,
            str(item.get("processed_at") or ""), str(item.get("market_id") or ""))


def _fold(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One item's events → one folded fact (a new dict).

    The highest tier wins; within it the earliest effective known-at, which is the
    tightest upper bound on when the outcome became known. Two or more scoring-eligible
    settlements whose outcomes differ (after ``ensemble._norm_name``) make the item a
    ``conflict``: never scored, whichever outcome is right.
    """
    best = max(_fold_tier(item) for item in items)
    top = sorted((item for item in items if _fold_tier(item) == best), key=_fold_order)
    folded = dict(top[0])
    folded["n_events"] = len(items)
    outcomes = {_norm_name(item.get("outcome")) for item in top}
    if best == 2 and len(outcomes) > 1:
        folded.update({
            "resolution_status": RESOLUTION_CONFLICT, "outcome": None, "y": None,
            "scoring_eligible": False, "ineligible_reason": RESOLUTION_CONFLICT,
            "conflicting_outcomes": sorted({str(item.get("outcome")) for item in top}),
        })
    return folded


def fold_binary_items(events: Optional[Iterable[Any]], targets: Optional[Iterable[Any]] = None
                      ) -> Dict[Tuple[str, str], Dict[str, Any]]:
    """``{(report_id, item_id): folded item}`` over the binary settlement events.

    ``events`` are resolutions.jsonl rows; scenario_set and other non-binary kinds are
    skipped. schema_version 2 events keep the writer's facts. Legacy rows (any other
    schema_version) are rebuilt by ``_legacy_binary_item`` and can only be proven
    eligible through ``targets`` (ledger rows; only production primary commit rows
    count); without targets they are ineligible (``no_v2_target``). Each item folds by
    ``_fold``: scoring-eligible settled > ineligible settled > terminal, and
    disagreeing eligible events make a ``conflict``.
    """
    proofs = _binary_targets(targets)
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for event in events or []:
        if not isinstance(event, dict) or event.get("item_kind") not in (None, ITEM_KIND_BINARY):
            continue
        if event.get("schema_version") == MARKET_RESOLUTION_EVENT_SCHEMA_VERSION:
            item = _event_item(event)
        else:
            item = _legacy_binary_item(event, proofs)
        if item["report_id"] and item["item_id"]:
            grouped[(item["report_id"], item["item_id"])].append(item)
    return {key: _fold(items) for key, items in grouped.items()}


def resolved_view(entries: Optional[Iterable[Any]], events: Optional[Iterable[Any]]
                  ) -> List[Dict[str, Any]]:
    """Copies of the production primary commit rows of ``entries``, each with its folded
    ``scenario_set`` settlement filled in: ``resolved``, ``outcome``, ``outcome_known_at``,
    ``known_at_basis``, ``processed_at``, ``scoring_eligible``, ``prospective``,
    ``resolution_status`` and ``ineligible_reason``.

    An event belongs to a row by ``report_id`` and, when it names one, by
    ``target_commit_id``. A row with no event gets the unresolved defaults, so a hand-marked
    ``resolved`` on disk never counts; only a grace terminal leaves ``resolved`` False.
    Other rows are left out. Never mutates ``entries`` or ``events`` and never touches disk.
    """
    by_report: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for event in events or []:
        if isinstance(event, dict) and event.get("item_kind") == ITEM_KIND_SCENARIO_SET:
            item = _event_item(event)
            if item["report_id"]:
                by_report[item["report_id"]].append(item)
    view: List[Dict[str, Any]] = []
    for row in entries or []:
        if not is_production_primary_commit(row):
            continue
        commit_id = str(row.get("commit_id") or "").strip()
        candidates = [item for item in by_report.get(str(row.get("report_id") or "").strip(), [])
                      if not item["target_commit_id"]
                      or str(item["target_commit_id"]).strip() == commit_id]
        out = copy.deepcopy(row)
        out.update(_VIEW_DEFAULTS)
        if candidates:
            folded = _fold(candidates)
            out.update({key: folded.get(key) for key in _VIEW_DEFAULTS})
            out["resolved"] = folded["resolution_status"] != "terminal"
        view.append(out)
    return view


def _as_of_cutoff(as_of: Any) -> Optional[datetime]:
    """00:00Z of the UTC day ``as_of`` names (a canonical date, an offset-aware stamp,
    or a ``date``/aware ``datetime``); None when it names no unambiguous day."""
    if isinstance(as_of, datetime):
        moment = as_of.astimezone(timezone.utc) if as_of.tzinfo is not None else None
    elif isinstance(as_of, date):
        moment = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
    else:
        moment = parse_stamp_strict(as_of)
    if moment is None:
        return None
    return datetime(moment.year, moment.month, moment.day, tzinfo=timezone.utc)


def admissible(item: Any, as_of: Any = None, *,
               now: Optional[datetime] = None) -> Tuple[bool, Optional[str]]:
    """``(ok, reason)``: may this folded item (or ``resolved_view`` row) enter calibration?

    The single point-in-time gate: every calibration consumer calls it and nothing else
    decides. Checked in order, first failure wins:

    - ``conflict``: its scoring-eligible events disagree on the outcome;
    - not ``scoring_eligible``: the writer's ``ineligible_reason`` when it recorded one
      (``not_prospective``, ``ambiguous_settlement``, ``unresolvable_after_grace`` ...),
      else ``not_scoring_eligible``;
    - ``not_prospective``: ``prospective`` is not True (no proof the outcome was unknown
      at the forecast origin);
    - ``unverifiable_stamp``: no strict effective known-at (``effective_known_at``);
    - with ``as_of`` None, ``known_after_now`` unless known-at <= ``now`` (offset-aware,
      default the current UTC time); otherwise ``known_on_or_after_as_of`` unless
      known-at is strictly before 00:00Z of the ``as_of`` day, so an outcome known on the
      as-of day itself is excluded; ``unverifiable_as_of`` when ``as_of`` names no day.
    """
    if not isinstance(item, dict):
        return False, "not_an_item"
    if item.get("resolution_status") == RESOLUTION_CONFLICT:
        return False, RESOLUTION_CONFLICT
    if item.get("scoring_eligible") is not True:
        reason = item.get("ineligible_reason")
        return False, reason if isinstance(reason, str) and reason else "not_scoring_eligible"
    if item.get("prospective") is not True:
        return False, "not_prospective"
    known = effective_known_at(item)
    if known is None:
        return False, "unverifiable_stamp"
    if as_of is None:
        current = now if now is not None else datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be an offset-aware datetime")
        return (True, None) if known <= current else (False, "known_after_now")
    cutoff = _as_of_cutoff(as_of)
    if cutoff is None:
        return False, "unverifiable_as_of"
    return (True, None) if known < cutoff else (False, "known_on_or_after_as_of")


def unscoreable_reason(entry: Any) -> Optional[str]:
    """Why a resolved scenario row cannot be scored, or None when it can.

    ``not_resolved``; ``not_settled`` (a ``resolution_status`` other than absent or
    'settled'); ``no_outcome``; ``unmatched_outcome`` (the outcome names no scenario) and
    ``ambiguous_outcome`` (it names several), both under ``ensemble._norm_name``, the
    scorer's own normaliser. Scoring either would count every scenario as a miss or two
    as hits, so such a row never enters calibration.
    """
    if not isinstance(entry, dict) or not entry.get("resolved"):
        return "not_resolved"
    if entry.get("resolution_status") not in (None, "settled"):
        return "not_settled"
    target = _norm_name(entry.get("outcome") or "")
    if not target:
        return "no_outcome"
    matches = sum(1 for scenario in (entry.get("scenarios") or [])
                  if isinstance(scenario, dict) and _norm_name(scenario.get("name")) == target)
    if matches == 0:
        return "unmatched_outcome"
    return "ambiguous_outcome" if matches > 1 else None


def is_scoreable_resolution(entry: Any) -> bool:
    """True when a resolved scenario row can be scored (see ``unscoreable_reason``)."""
    return unscoreable_reason(entry) is None
