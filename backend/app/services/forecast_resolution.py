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

EVAL-4 adds the manual settlement path, the only label source for the scenario
set and for binaries without an exact market anchor. ``validate_manual_settlement``
and ``build_manual_event`` turn a human attestation (a scenario name matched under
``ensemble._norm_name``, or YES/NO for one binary, with a strict past known-at and
an http(s) URL or a 20-character note as evidence) into an append-ready event on
the ``attested`` basis; ``plan_manual_settlement`` adds the revision protocol:
the first attestation of an item is market id 'manual', each correction or
retraction 'manual:r<n>' naming the latest one it replaces in ``supersedes``, and
an identical repeat is a no-op. The fold counts only the manual events no later
revision supersedes and never a retraction, so a wrong attestation can be
corrected or withdrawn although every key is first-write-wins; an eligible manual
outcome that disagrees with an eligible market settlement stays a ``conflict``.
A manual row never makes an item final for the market sweep (``recorded_items``):
an anchored item is still fetched until a market event or its grace terminal
closes its market channel, so that conflict can actually be written, and a
standing attestation spares only an unanchored item its grace terminal (the fold
ranks any attestation above a terminal). ``load_manual_target`` (the one reader
of disk here) resolves the forecast target that ``forecast_tools resolve`` and
``POST /api/v1/resolve`` both attest against.
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
from urllib.parse import urlsplit

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
    _route_dir,
    _unit_probability,
    binary_resolution_date,
    is_production_calibration_row,
    is_production_primary_commit,
    read_ledger,
)

BASIS_SOURCE = "source"
BASIS_ATTESTED = "attested"
BASIS_PROCESSING_UPPER_BOUND = "processing_upper_bound"
SOURCE_KIND_MARKET = "polymarket"
SOURCE_KIND_TERMINAL = "terminal"
# EVAL-4: a human attestation (forecast_tools resolve, POST /api/v1/resolve).
SOURCE_KIND_MANUAL = "manual"
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
                       ) -> Tuple[Set[str], Set[str], Set[str]]:
    """``(settled, terminal, attested)``: forecast ids of ``report_id`` that already hold
    a non-terminal market-side row (settled, ambiguous or legacy), a terminal row, and
    (EVAL-4) a standing manual attestation, in the ledger. A superseded or retracted
    attestation no longer stands (``standing_events``), so it never keeps an item from
    its grace terminal."""
    settled: Set[str] = set()
    terminal: Set[str] = set()
    attested: Set[str] = set()
    for event in standing_events(events):
        if str(event.get("report_id") or "") == report_id:
            forecast_id = str(event.get("forecast_id") or "")
            if is_manual_event(event):
                attested.add(forecast_id)
            else:
                (terminal if _is_terminal_row(event) else settled).add(forecast_id)
    return settled, terminal, attested


def recorded_items(events: Optional[Iterable[Any]]) -> Set[Tuple[str, str]]:
    """``(report_id, forecast_id)`` pairs that already hold a market-side resolutions
    row: a settled, ambiguous or terminal event, or a legacy settled row. Such an item
    is final; nothing a later sweep decides can be appended for it as a new fact.
    EVAL-4: manual rows never count. An attestation is a human label, not the market's
    answer: the sweep keeps fetching an anchored item so that a disagreeing market
    settlement folds into a ``conflict`` (see ``attested_items`` and ``due_binaries``)."""
    out: Set[Tuple[str, str]] = set()
    for event in events or []:
        if isinstance(event, dict) and not is_manual_event(event):
            out.add((str(event.get("report_id") or ""), str(event.get("forecast_id") or "")))
    return out


def attested_items(events: Optional[Iterable[Any]]) -> Set[Tuple[str, str]]:
    """EVAL-4: ``(report_id, forecast_id)`` pairs that hold a standing manual attestation
    (``standing_events``: neither superseded nor a retraction)."""
    return {_item_key(event) for event in standing_events(events) if is_manual_event(event)}


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
                 processed_at: str, grace_days: int = 180,
                 attested: Optional[Set[Tuple[str, str]]] = None) -> List[Dict[str, Any]]:
    """The binaries of one target that a settle sweep can act on at ``processed_at``, in order.

    A binary qualifies when it has an id, no row in ``recorded`` (see
    ``recorded_items``) and either a market anchor (only the market source can
    say whether it settled) or no anchor and an expired grace period (its
    terminal needs no network). An unanchored binary still inside its grace
    period has nothing to do yet: a target holding only such items must not
    take a sweep's cap slot for years while older targets wait for their
    terminals. EVAL-4: an attestation leaves an anchored item's market channel
    open (it stays due until a market event or its grace terminal closes it, so
    a disagreeing settlement becomes a ``conflict``), while an unanchored item in
    ``attested`` (``attested_items``: a standing manual attestation) has nothing
    left to do: it needs no terminal. Raises ``ValueError`` when
    ``processed_at`` is not an offset-aware ISO date-time.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    rid = str(report_id or "").strip()
    grace = max(0, int(grace_days))
    labelled = attested or set()
    due: List[Dict[str, Any]] = []
    for binary in binaries if isinstance(binaries, list) else []:
        if not isinstance(binary, dict):
            continue
        forecast_id = str(binary.get("id") or "").strip()
        if not forecast_id or (rid, forecast_id) in recorded:
            continue
        if anchor_market_id(binary) or (_grace_expired(binary, processed, grace)
                                        and (rid, forecast_id) not in labelled):
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
    rows: an item that already holds a non-terminal market-side event never
    gets a terminal one; nor does an unanchored item holding a standing manual
    attestation (EVAL-4; a superseded or retracted one no longer counts). An
    anchored item's terminal only closes its market channel, which an
    attestation leaves open: the fold still ranks the attestation above the
    terminal. An item that already holds a terminal row is final and
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
    already_settled, already_ended, attested = _held_forecast_ids(rid, existing_events)
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
                and (market_id or forecast_id not in attested)
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
# resolved_view: a scenario_set attestation that does not identify exactly one production
# primary commit row labels none of them (never one outcome scored twice).
AMBIGUOUS_TARGET = "ambiguous_target"
# EVAL-4: the status of a manual row that withdraws an attestation (never scored).
RESOLUTION_RETRACTED = "retracted"
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


def _item_key(event: Dict[str, Any]) -> Tuple[str, str]:
    return (str(event.get("report_id") or "").strip(), str(event.get("forecast_id") or "").strip())


def is_manual_event(event: Any) -> bool:
    """EVAL-4: a manual attestation row (``source_kind`` 'manual')."""
    return isinstance(event, dict) and event.get("source_kind") == SOURCE_KIND_MANUAL


def is_retraction(event: Any) -> bool:
    """EVAL-4: a manual row that withdraws an attestation instead of making one."""
    return isinstance(event, dict) and (event.get("retracted") is True
                                        or event.get("resolution_status") == RESOLUTION_RETRACTED)


def standing_events(events: Optional[Iterable[Any]]) -> List[Dict[str, Any]]:
    """EVAL-4: the settlement rows of ``events`` that still stand (a new list; rows untouched).

    Every market, terminal and legacy row stands. A manual attestation stands unless it
    is a retraction or a manual row of the same item (report_id, forecast_id) names its
    market id in ``supersedes``: a revision chain 'manual' <- 'manual:r1' <- ... leaves
    only its latest revision, and nothing at all once that revision is a retraction.
    Only manual rows can supersede, and only manual rows can be superseded, so a manual
    outcome never hides a market settlement: eligible ones that disagree fold into a
    ``conflict``. Should hand edits ever leave two unsuperseded attestations for one
    item, both stand and the fold scores neither when they disagree (fail closed).
    """
    rows = [event for event in events or [] if isinstance(event, dict)]
    superseded: Dict[Tuple[str, str], Set[str]] = defaultdict(set)
    for event in rows:
        pointer = str(event.get("supersedes") or "").strip() if is_manual_event(event) else ""
        if pointer:
            superseded[_item_key(event)].add(pointer)
    return [event for event in rows if not is_manual_event(event) or not (
        is_retraction(event)
        or str(event.get("market_id") or "").strip() in superseded.get(_item_key(event), ()))]


def _fold_tier(item: Dict[str, Any]) -> int:
    """Fold precedence: 2 = scoring-eligible settled outcome, 1 = any other settlement
    fact (ineligible, ambiguous, ...), 0 = grace terminal."""
    if item.get("resolution_status") == "terminal":
        return 0
    if (item.get("scoring_eligible") is True and item.get("resolution_status") == "settled"
            and _norm_name(item.get("outcome"))):
        return 2
    return 1


def _fold_order(item: Dict[str, Any]) -> Tuple[bool, datetime, str, str, str]:
    """Earliest effective known-at first (an unverifiable stamp last); ties by stamp text,
    market id and finally the whole item's canonical JSON, a total order, so the fold
    never depends on the order events were appended."""
    known = effective_known_at(item)
    return (known is None, known or _LATEST_ORDER_KEY,
            str(item.get("processed_at") or ""), str(item.get("market_id") or ""),
            json.dumps(item, sort_keys=True, default=str))


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
    disagreeing eligible events make a ``conflict``. EVAL-4: only the standing manual
    attestations take part (``standing_events``), so a correction replaces what it
    supersedes and a retraction removes the attestation.
    """
    proofs = _binary_targets(targets)
    grouped: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for event in standing_events(events):
        if not isinstance(event, dict) or event.get("item_kind") not in (None, ITEM_KIND_BINARY):
            continue
        if event.get("schema_version") == MARKET_RESOLUTION_EVENT_SCHEMA_VERSION:
            item = _event_item(event)
        else:
            item = _legacy_binary_item(event, proofs)
        if item["report_id"] and item["item_id"]:
            grouped[(item["report_id"], item["item_id"])].append(item)
    return {key: _fold(items) for key, items in grouped.items()}


def _judged_against_row(item: Dict[str, Any], row: Dict[str, Any]) -> Dict[str, Any]:
    """EVAL-4: the fold candidate of an attestation recorded against the report itself
    (``target_source`` TARGET_SOURCE_REPORT: the report had no production primary row
    yet, so its origin was the report creation stamp with no as-of date) for the one row
    it binds to: prospective and eligibility are re-derived from that row's origin (its
    as-of date and creation stamp). An item that is not a settled outcome is returned as
    is. A new dict; ``item`` is untouched."""
    if item.get("resolution_status") != "settled":
        return item
    prospective = prospective_status(item.get("outcome_known_at"), item.get("known_at_basis"),
                                     row.get("as_of_date"), row.get("created_at"), None)
    eligible = prospective is True
    return dict(item, prospective=prospective, scoring_eligible=eligible,
                ineligible_reason=None if eligible else (
                    "not_prospective" if prospective is False else "prospective_unknown"))


def resolved_view(entries: Optional[Iterable[Any]], events: Optional[Iterable[Any]]
                  ) -> List[Dict[str, Any]]:
    """Copies of the production primary commit rows of ``entries``, each with its folded
    ``scenario_set`` settlement filled in: ``resolved``, ``outcome``, ``outcome_known_at``,
    ``known_at_basis``, ``processed_at``, ``scoring_eligible``, ``prospective``,
    ``resolution_status`` and ``ineligible_reason``.

    An event belongs to a row by ``report_id`` and, when it names one, by
    ``target_commit_id``, and binds only when it identifies exactly one row: an event
    without a target when the report has a single production primary row, one naming a
    commit when a single production primary row carries it. A row reached only by events
    that fail this is resolved but never scoring-eligible (``ambiguous_target``), so one
    attestation is never scored twice. A row with no event gets the unresolved defaults,
    so a hand-marked ``resolved`` on disk never counts; only a grace terminal leaves
    ``resolved`` False. Other rows are left out. Never mutates ``entries`` or ``events``
    and never touches disk. EVAL-4: superseded manual attestations and retractions
    never label a row (``standing_events``), and an attestation recorded against the
    report itself (``target_source`` TARGET_SOURCE_REPORT) is judged against the row it
    binds to (``_judged_against_row``); every other event keeps the writer's facts.
    """
    def key(value: Any) -> str:
        return str(value or "").strip()

    by_report: Dict[str, List[Tuple[Dict[str, Any], bool]]] = defaultdict(list)
    for event in standing_events(events):
        if isinstance(event, dict) and event.get("item_kind") == ITEM_KIND_SCENARIO_SET:
            item = _event_item(event)
            if item["report_id"]:
                by_report[item["report_id"]].append(
                    (item, event.get("target_source") == TARGET_SOURCE_REPORT))
    rows = [row for row in entries or [] if is_production_primary_commit(row)]
    n_by_report = Counter(key(row.get("report_id")) for row in rows)
    n_by_commit = Counter((key(row.get("report_id")), key(row.get("commit_id"))) for row in rows)
    view: List[Dict[str, Any]] = []
    for row in rows:
        report_id, commit_id = key(row.get("report_id")), key(row.get("commit_id"))
        bound: List[Dict[str, Any]] = []
        ambiguous: List[Dict[str, Any]] = []
        for item, provisional in by_report.get(report_id, []):
            target = key(item["target_commit_id"])
            if target and target != commit_id:
                continue
            unique = (n_by_commit[(report_id, commit_id)] if target else n_by_report[report_id]) == 1
            if unique:
                bound.append(_judged_against_row(item, row) if provisional else item)
            else:
                ambiguous.append(item)
        out = copy.deepcopy(row)
        out.update(_VIEW_DEFAULTS)
        if bound or ambiguous:
            folded = _fold(bound or ambiguous)
            out.update({field: folded.get(field) for field in _VIEW_DEFAULTS})
            out["resolved"] = folded["resolution_status"] != "terminal"
            if not bound:
                out.update({"outcome": None, "scoring_eligible": False,
                            "ineligible_reason": AMBIGUOUS_TARGET})
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


# ---------------------------------------------------------------------------
# EVAL-4: manual settlement path (attested scenario / binary outcomes)
# ---------------------------------------------------------------------------

# The ``item`` naming a target's scenario set; any other item is a binary id.
SCENARIO_ITEM = "scenario"
# forecast_id of a scenario_set event: the whole set resolves at once, to one scenario.
SCENARIO_SET_FORECAST_ID = "__scenarios__"
# market_id of an item's first attestation; its n-th correction or retraction is 'manual:r<n>'.
MANUAL_MARKET_ID = "manual"
MANUAL_EVIDENCE_MIN_CHARS = 20
# A note is evidence on a ledger row that every calibration pass reads, not a document.
MANUAL_EVIDENCE_MAX_CHARS = 2000
_MANUAL_REVISION_RE = re.compile(r"manual:r([1-9][0-9]*)", re.ASCII)
# load_manual_target's refusal reasons besides AMBIGUOUS_TARGET / NOT_PRODUCTION_PRIMARY.
TARGET_MISSING_REPORT_ID = "missing_report_id"
TARGET_NOT_PUBLISHABLE = "not_publishable"
TARGET_NOT_SEALED = "not_sealed"
TARGET_EVALUATION_RUN = "evaluation_run"
# load_manual_target's ``source`` values, kept on each manual event as ``target_source``.
TARGET_SOURCE_LEDGER = "ledger"
TARGET_SOURCE_REPORT = "report"
# A scenario-set attestation of a report-fallback target (manual_not_bindable_reason).
MANUAL_NOT_BINDABLE = ("recorded_not_bindable: enters no calibration while the report has no "
                       "production primary ledger row")
# The fields that make two attestations of one item the same one (a repeat is a no-op).
_ATTESTATION_FIELDS = ("item_kind", "outcome", "outcome_known_at", "evidence")
# A manual binary whose target probability is missing or outside [0, 1]: recorded, never scored
# (binary_calibration_summary's exclusion reason for the same defect).
INVALID_MODEL_PROBABILITY = "invalid_model_probability"


def match_scenario_name(scenarios: Any, outcome: Any) -> Tuple[Optional[str], Optional[str]]:
    """``(canonical name, None)`` when ``outcome`` names exactly one of ``scenarios`` under
    ``ensemble._norm_name`` (the scorer's own normaliser), else ``(None, reason)`` with the
    reasons of ``unscoreable_reason``: ``no_outcome``, ``unmatched_outcome`` or
    ``ambiguous_outcome``."""
    wanted = _norm_name(outcome) if isinstance(outcome, str) else ""
    if not wanted:
        return None, "no_outcome"
    names = [scenario.get("name") for scenario in (scenarios if isinstance(scenarios, list) else [])
             if isinstance(scenario, dict) and _norm_name(scenario.get("name")) == wanted]
    if not names:
        return None, "unmatched_outcome"
    if len(names) > 1:
        return None, "ambiguous_outcome"
    return str(names[0]), None


def _scenario_names(target: Dict[str, Any]) -> List[str]:
    scenarios = target.get("scenarios")
    return [str(scenario.get("name")) for scenario in (scenarios if isinstance(scenarios, list) else [])
            if isinstance(scenario, dict)]


def _target_binary(target: Dict[str, Any], item_id: str
                   ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(binary, None)`` for the one target binary whose id is ``item_id``, else ``(None, error)``."""
    binaries = target.get("binary_forecasts")
    matches = [binary for binary in (binaries if isinstance(binaries, list) else [])
               if isinstance(binary, dict) and str(binary.get("id") or "").strip() == item_id]
    if not matches:
        return None, f"binary {item_id!r} is not in the forecast target"
    if len(matches) > 1:
        return None, f"binary id {item_id!r} is not unique in the forecast target"
    return matches[0], None


def _binary_outcome(outcome: Any) -> Optional[str]:
    label = outcome.strip().upper() if isinstance(outcome, str) else ""
    return label if label in ("YES", "NO") else None


def _is_http_url(text: str) -> bool:
    if any(char.isspace() for char in text):
        return False
    try:
        parts = urlsplit(text)
    except ValueError:
        return False
    return parts.scheme.lower() in ("http", "https") and bool(parts.hostname)


def _evidence_record(evidence: Any) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``({url, note}, None)`` for admissible evidence, else ``(None, error)``: an http(s)
    URL, or a note of MANUAL_EVIDENCE_MIN_CHARS to MANUAL_EVIDENCE_MAX_CHARS characters
    (both measured after stripping surrounding whitespace)."""
    requirement = (f"evidence must be an http(s) URL or a note of at least "
                   f"{MANUAL_EVIDENCE_MIN_CHARS} characters")
    text = evidence.strip() if isinstance(evidence, str) else ""
    if not text:
        return None, requirement
    if len(text) > MANUAL_EVIDENCE_MAX_CHARS:
        return None, f"evidence is longer than {MANUAL_EVIDENCE_MAX_CHARS} characters"
    if _is_http_url(text):
        return {"url": text, "note": None}, None
    if len(text) < MANUAL_EVIDENCE_MIN_CHARS:
        return None, requirement
    return {"url": None, "note": text}, None


def validate_manual_attestation(outcome_known_at: Any, evidence: Any, *, retract: bool = False,
                                now: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """``(ok, errors)`` for the target-independent part of a manual attestation, so a
    caller can refuse invalid input (400 / exit 2) before it looks for a target.

    ``outcome_known_at`` must pass ``parse_stamp_strict`` (a canonical date, or an ISO
    date-time with a Z or an explicit offset) and not lie after ``now`` (offset-aware,
    default the current UTC time); a retraction (``retract=True``) carries none.
    ``evidence`` must be an http(s) URL or a note of at least MANUAL_EVIDENCE_MIN_CHARS
    characters. Raises ``ValueError`` for a naive ``now``.
    """
    errors: List[str] = []
    if retract:
        if outcome_known_at not in (None, ""):
            errors.append("a retraction carries no outcome_known_at")
    else:
        known = parse_stamp_strict(outcome_known_at)
        current = now if now is not None else datetime.now(timezone.utc)
        if current.tzinfo is None:
            raise ValueError("now must be an offset-aware datetime")
        if known is None:
            errors.append("outcome_known_at must be a canonical YYYY-MM-DD date or an ISO "
                          "date-time with a Z or an explicit UTC offset")
        elif known > current:
            errors.append("outcome_known_at lies in the future")
    _, error = _evidence_record(evidence)
    if error:
        errors.append(error)
    return not errors, errors


def validate_manual_settlement(target: Any, item: Any, outcome: Any, outcome_known_at: Any,
                               evidence: Any, *, retract: bool = False,
                               now: Optional[datetime] = None) -> Tuple[bool, List[str]]:
    """``(ok, errors)`` for one manual attestation against its forecast ``target``
    (``load_manual_target``'s shape).

    ``item`` SCENARIO_ITEM ('scenario') attests the scenario set: ``outcome`` must name
    exactly one of the target's scenarios under ``ensemble._norm_name``. Any other
    ``item`` is a binary id that must appear exactly once in the target, with
    ``outcome`` YES or NO (any case); SCENARIO_SET_FORECAST_ID is reserved for the
    scenario set's events and never a binary id. ``outcome_known_at`` and ``evidence``
    are checked by ``validate_manual_attestation``. A retraction (``retract=True``)
    names the item and its evidence but neither an outcome nor a known-at. Every
    failure is listed and nothing is coerced into validity. Raises ``ValueError`` for a
    naive ``now``.
    """
    if not isinstance(target, dict) or not str(target.get("report_id") or "").strip():
        return False, ["no forecast target to attest against"]
    errors: List[str] = []
    item_id = item.strip() if isinstance(item, str) else ""
    has_outcome = outcome not in (None, "")
    if not item_id:
        errors.append(f"item is required: {SCENARIO_ITEM!r} or a binary id")
    elif item_id == SCENARIO_SET_FORECAST_ID:
        errors.append(f"{SCENARIO_SET_FORECAST_ID!r} is reserved for the scenario set; "
                      f"attest it as {SCENARIO_ITEM!r}")
    elif retract:
        if item_id != SCENARIO_ITEM:
            _, error = _target_binary(target, item_id)
            if error:
                errors.append(error)
        if has_outcome:
            errors.append("a retraction names no outcome")
    elif item_id == SCENARIO_ITEM:
        _, reason = match_scenario_name(target.get("scenarios"), outcome)
        if reason == "no_outcome":
            errors.append("a scenario outcome is required")
        elif reason is not None:
            verb = "matches no" if reason == "unmatched_outcome" else "matches more than one"
            errors.append(f"outcome {outcome!r} {verb} scenario of the forecast target "
                          f"({', '.join(repr(name) for name in _scenario_names(target))})")
    else:
        _, error = _target_binary(target, item_id)
        if error:
            errors.append(error)
        if _binary_outcome(outcome) is None:
            errors.append("a binary outcome must be YES or NO")
    errors += validate_manual_attestation(outcome_known_at, evidence, retract=retract, now=now)[1]
    return not errors, errors


def manual_revision(market_id: Any) -> Optional[int]:
    """The revision number of a manual event's market id: 0 for 'manual', n for
    'manual:r<n>' (n >= 1), None for anything else."""
    text = str(market_id or "").strip()
    if text == MANUAL_MARKET_ID:
        return 0
    match = _MANUAL_REVISION_RE.fullmatch(text)
    return int(match.group(1)) if match else None


def manual_events(events: Optional[Iterable[Any]], report_id: Any,
                  forecast_id: Any) -> List[Dict[str, Any]]:
    """The manual rows recorded for one item (report_id, forecast_id), in ledger order."""
    key = (str(report_id or "").strip(), str(forecast_id or "").strip())
    return [event for event in events or []
            if is_manual_event(event) and _item_key(event) == key]


def latest_manual_event(rows: Iterable[Any]) -> Optional[Dict[str, Any]]:
    """The manual row with the highest revision number (the later one on a tie), or None."""
    ranked = [(manual_revision(row.get("market_id")), index, row)
              for index, row in enumerate(rows) if isinstance(row, dict)]
    ranked = [entry for entry in ranked if entry[0] is not None]
    return max(ranked, key=lambda entry: (entry[0], entry[1]))[2] if ranked else None


def _forecast_id_for(item: Any) -> str:
    item_id = item.strip() if isinstance(item, str) else ""
    return SCENARIO_SET_FORECAST_ID if item_id == SCENARIO_ITEM else item_id


def disagreeing_attestations(events: Optional[Iterable[Any]], report_id: Any, item: Any,
                             outcome: Any) -> List[Dict[str, Any]]:
    """The standing manual attestations (``standing_events``) of one item of ``report_id``
    (``item`` 'scenario' or a binary id) whose outcome differs from ``outcome`` under
    ``ensemble._norm_name``, in ledger order. ``POST /api/v1/resolve`` refuses to write a
    resolved.json that contradicts one."""
    wanted = _norm_name(outcome) if isinstance(outcome, str) else ""
    return [row for row in manual_events(standing_events(events), report_id,
                                         _forecast_id_for(item))
            if _norm_name(row.get("outcome")) != wanted]


def validate_manual_revision(existing_events: Optional[Iterable[Any]], report_id: Any,
                             item: Any, *, supersedes: Any = None,
                             retract: bool = False) -> Tuple[bool, List[str]]:
    """``(ok, errors)``: does a correction or retraction of ``item`` follow the protocol?

    A retraction must name what it retracts (``supersedes``). ``supersedes`` must be the
    market id of the item's latest manual event (``latest_manual_event``), so a revision
    chain stays linear; a retraction of a retraction is refused; and the new revision's
    market id 'manual:r<n>' (n = the item's manual events so far, counting the original)
    must still be free. Without ``supersedes`` there is nothing to check here.
    """
    rows = [row for row in existing_events or [] if isinstance(row, dict)]
    forecast_id = _forecast_id_for(item)
    manual = manual_events(rows, report_id, forecast_id)
    pointer = str(supersedes or "").strip()
    errors: List[str] = []
    if retract and not pointer:
        errors.append("a retraction must name the attestation it retracts (supersedes)")
    if not pointer:
        return not errors, errors
    latest = latest_manual_event(manual)
    latest_id = str(latest.get("market_id")).strip() if latest is not None else None
    if latest_id is None:
        errors.append("supersedes names nothing: no manual attestation is recorded for this item")
    elif pointer != latest_id:
        errors.append(f"supersedes must name the latest manual event of this item "
                      f"({latest_id!r}), not {pointer!r}")
    else:
        if retract and is_retraction(latest):
            errors.append(f"{latest_id!r} is already a retraction")
        new_id = f"{MANUAL_MARKET_ID}:r{len(manual)}"
        key = (str(report_id or "").strip(), forecast_id)
        if any(_item_key(row) == key and str(row.get("market_id") or "").strip() == new_id
               for row in rows):
            errors.append(f"revision id {new_id!r} is already taken: the manual events of "
                          f"this item do not form one chain")
    return not errors, errors


def build_manual_event(*, target: Dict[str, Any], item: str, outcome: Any,
                       outcome_known_at: Any, evidence: Any, supersedes: Optional[str] = None,
                       retract: bool = False, processed_at: str,
                       existing_events: Optional[Iterable[Any]] = None) -> Dict[str, Any]:
    """One manual settlement event, append-ready (``forecast_ledger.append_settlement_event``).

    - forecast_id SCENARIO_SET_FORECAST_ID, item_kind 'scenario_set', the target's
      canonical scenario name as outcome and model_p None; or the binary id, item_kind
      'binary', outcome YES/NO with y 1/0, model_p the target binary's probability and
      its brier_contribution. A probability that is missing or outside [0, 1] gets no
      Brier and makes the row ineligible (``invalid_model_probability``): the outcome is
      still recorded, but a fabricated score never is;
    - market_id 'manual' without ``supersedes``, else 'manual:r<n>' with n the number
      of manual events ``existing_events`` already hold for the item, and
      ``supersedes`` that superseded market id;
    - source_kind 'manual', known_at_basis 'attested' (``outcome_known_at`` kept as
      given, so a bare date keeps both of its conservative readings), prospective from
      ``prospective_status`` against the target's as-of date and creation stamp,
      scoring_eligible exactly when prospective is True (and, for a binary, its
      probability is valid), resolution_status 'settled';
    - a retraction has outcome, y and outcome_known_at None, resolution_status
      'retracted', retracted True and is never scoring-eligible;
    - target_commit_id and target_source are the target's commit id and ``source``
      (TARGET_SOURCE_LEDGER or TARGET_SOURCE_REPORT): a scenario attestation recorded
      against the report itself is judged again against the production primary row it
      later binds to (``resolved_view``).

    Raises ``ValueError`` when ``processed_at`` (the only clock, also the ``now`` of
    validation) is not an offset-aware ISO date-time, or when
    ``validate_manual_settlement`` or ``validate_manual_revision`` rejects the input:
    no invalid attestation can be built.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    rows = [row for row in existing_events or [] if isinstance(row, dict)]
    ok, errors = validate_manual_settlement(target, item, outcome, outcome_known_at, evidence,
                                            retract=retract, now=processed)
    if ok:
        ok, errors = validate_manual_revision(rows, target.get("report_id"), item,
                                              supersedes=supersedes, retract=retract)
    if not ok:
        raise ValueError("; ".join(errors))
    report_id = str(target.get("report_id")).strip()
    item_id = item.strip()
    scenario_set = item_id == SCENARIO_ITEM
    forecast_id = _forecast_id_for(item_id)
    pointer = str(supersedes or "").strip() or None
    revision = len(manual_events(rows, report_id, forecast_id))
    label: Optional[str] = None
    y: Optional[int] = None
    model_p: Optional[float] = None
    brier: Optional[float] = None
    if scenario_set:
        if not retract:
            label, _ = match_scenario_name(target.get("scenarios"), outcome)
    else:
        binary, _ = _target_binary(target, item_id)
        model_p = _finite((binary or {}).get("probability"))
        if not retract:
            label = _binary_outcome(outcome)
            y = 1 if label == "YES" else 0
            if _unit_probability(model_p) is not None:
                brier = round((model_p - y) ** 2, 4)
    evidence_record, _ = _evidence_record(evidence)
    known_iso = None if retract else outcome_known_at
    prospective: Optional[Prospective] = None
    if retract:
        ineligible_reason: Optional[str] = RESOLUTION_RETRACTED
    else:
        prospective = prospective_status(known_iso, BASIS_ATTESTED, target.get("as_of"),
                                         target.get("created_at"), None)
        if not scenario_set and brier is None:
            ineligible_reason = INVALID_MODEL_PROBABILITY
        elif prospective is True:
            ineligible_reason = None
        else:
            ineligible_reason = "not_prospective" if prospective is False else "prospective_unknown"
    processed_iso = processed.isoformat()
    return {
        "report_id": report_id,
        "forecast_id": forecast_id,
        "market_id": MANUAL_MARKET_ID if pointer is None else f"{MANUAL_MARKET_ID}:r{revision}",
        "resolved_outcome": label,
        "resolved_yes_price": None,
        "model_p": model_p,
        "market_p_at_research": None,
        "brier_contribution": brier,
        "resolved_at": processed_iso,
        "schema_version": MARKET_RESOLUTION_EVENT_SCHEMA_VERSION,
        "item_kind": ITEM_KIND_SCENARIO_SET if scenario_set else ITEM_KIND_BINARY,
        "source_kind": SOURCE_KIND_MANUAL,
        "outcome": label,
        "y": y,
        "outcome_known_at": known_iso,
        "known_at_basis": BASIS_ATTESTED,
        "known_at_clamped": False,
        "processed_at": processed_iso,
        "prospective": prospective,
        "scoring_eligible": ineligible_reason is None,
        "ineligible_reason": ineligible_reason,
        "resolution_status": RESOLUTION_RETRACTED if retract else "settled",
        "report_publishable_at_issue": True,
        "target_commit_id": target.get("commit_id"),
        "target_source": target.get("source"),
        "evidence": evidence_record,
        "terminal_reason": None,
        "supersedes": pointer,
        "retracted": bool(retract),
    }


def _same_attestation(recorded: Dict[str, Any], event: Dict[str, Any]) -> bool:
    """Do two manual rows of one item attest the same thing (``_ATTESTATION_FIELDS``, and
    both or neither a retraction)?"""
    return (is_retraction(recorded) == is_retraction(event)
            and all(recorded.get(field) == event.get(field) for field in _ATTESTATION_FIELDS))


def _is_recorded_revision(target: Any, item: Any, outcome: Any, outcome_known_at: Any,
                          evidence: Any, *, rows: List[Dict[str, Any]],
                          latest: Optional[Dict[str, Any]], supersedes: Any, retract: bool,
                          processed_at: str) -> bool:
    """Is this correction or retraction a retry of the one that already is the item's
    latest revision?

    That is the case when ``latest`` itself supersedes the event ``supersedes`` names and
    the revision, replayed against the ledger as it stood before ``latest`` was
    appended, gets ``latest``'s market id and attests the same thing
    (``_same_attestation``). A retry whose first response was lost is then a no-op,
    like a repeated first attestation, instead of a revision error. The caller has
    validated the attestation itself (``validate_manual_settlement``).
    """
    pointer = str(supersedes or "").strip()
    if not pointer or latest is None or str(latest.get("supersedes") or "").strip() != pointer:
        return False
    before = [row for row in rows if row is not latest]
    report_id = target.get("report_id") if isinstance(target, dict) else None
    if not validate_manual_revision(before, report_id, item, supersedes=pointer, retract=retract)[0]:
        return False
    replay = build_manual_event(target=target, item=item, outcome=outcome,
                                outcome_known_at=outcome_known_at, evidence=evidence,
                                supersedes=pointer, retract=retract, processed_at=processed_at,
                                existing_events=before)
    return (replay["market_id"] == str(latest.get("market_id") or "").strip()
            and _same_attestation(latest, replay))


def plan_manual_settlement(target: Any, item: Any, outcome: Any, outcome_known_at: Any,
                           evidence: Any, *, existing_events: Optional[Iterable[Any]],
                           supersedes: Optional[str] = None, retract: bool = False,
                           processed_at: str) -> Dict[str, Any]:
    """What one manual attestation would do to the ledger, decided before anything is written.

    Returns ``{status, errors, event, latest}``, ``latest`` being the item's latest
    manual row in ``existing_events`` (None when it has none). ``status``:

    - ``invalid``: ``validate_manual_settlement`` or ``validate_manual_revision``
      rejects it; ``errors`` say why;
    - ``exists``: the item already holds a manual attestation, no ``supersedes`` names
      it and the new one differs from its latest revision. Its first-write-wins key
      would drop the new one silently, so the caller must correct explicitly;
    - ``noop``: the same attestation (``_ATTESTATION_FIELDS``, and both or neither a
      retraction) already is the item's latest revision, so there is nothing to write:
      a repeated first attestation, or a retried correction or retraction whose
      ``supersedes`` names the event that latest revision superseded
      (``_is_recorded_revision``);
    - ``append``: ``event`` (``build_manual_event``) is the one row to append.

    Raises ``ValueError`` when ``processed_at`` is not an offset-aware ISO date-time.
    """
    processed = parse_stamp_strict(processed_at, allow_date=False)
    if processed is None:
        raise ValueError("processed_at must be an offset-aware ISO date-time")
    rows = [row for row in existing_events or [] if isinstance(row, dict)]
    report_id = target.get("report_id") if isinstance(target, dict) else None
    manual = manual_events(rows, report_id, _forecast_id_for(item))
    latest = latest_manual_event(manual)
    result: Dict[str, Any] = {"status": "invalid", "errors": [], "event": None, "latest": latest}
    _, errors = validate_manual_settlement(target, item, outcome, outcome_known_at, evidence,
                                           retract=retract, now=processed)
    if not errors and _is_recorded_revision(target, item, outcome, outcome_known_at, evidence,
                                            rows=rows, latest=latest, supersedes=supersedes,
                                            retract=retract, processed_at=processed.isoformat()):
        result["status"] = "noop"
        return result
    _, revision_errors = validate_manual_revision(rows, report_id, item,
                                                  supersedes=supersedes, retract=retract)
    result["errors"] = errors + revision_errors
    if result["errors"]:
        return result
    event = build_manual_event(target=target, item=item, outcome=outcome,
                               outcome_known_at=outcome_known_at, evidence=evidence,
                               supersedes=supersedes, retract=retract,
                               processed_at=processed.isoformat(), existing_events=rows)
    if event["supersedes"] is None and manual:
        if latest is not None and _same_attestation(latest, event):
            result["status"] = "noop"
        else:
            latest_id = latest.get("market_id") if latest is not None else None
            result.update(status="exists", errors=[
                f"a manual attestation is already recorded for this item (latest: "
                f"{latest_id!r}); to correct or retract it, name that event in supersedes"])
        return result
    result.update(status="append", event=event)
    return result


def _publishable_at_issue(report_id: str) -> Any:
    from .report_agent import ReportManager  # lazy: report_agent imports this package's modules
    return ReportManager.publishable_at_issue(report_id)


def proves_publishable(result: Any) -> bool:
    """True only for an explicit proof of publication: ``True`` itself, or a
    ``ReportManager.publishable_at_issue`` / ``publication_status`` dict whose
    ``publishable`` is ``True``. Anything else (False, None, a truthy string, a dict
    without the key) proves nothing, so the gate fails closed."""
    if isinstance(result, dict):
        return result.get("publishable") is True
    return result is True


def _sealed_forecast(report_id: str) -> Any:
    from .report_agent import ReportManager
    return ReportManager.load_structured_forecast(report_id, allow_stale_policy=True)


def local_stamp_to_utc(value: Any) -> Optional[str]:
    """A report meta.json ``created_at`` in UTC (ISO). It is written by
    ``datetime.now().isoformat()`` (host local time, no zone), so a naive stamp reads as
    local time and an aware one converts; anything else is None. The resolution monitor
    and ``load_manual_target`` share it."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.strip()).astimezone(timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def _report_created_at(report_id: str) -> Optional[str]:
    """meta.json's ``created_at`` in UTC (``local_stamp_to_utc``); unreadable is None."""
    try:
        from .report_agent import ReportManager
        with open(os.path.join(ReportManager._get_report_folder(report_id), "meta.json"),
                  encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError, TypeError):
        return None
    return local_stamp_to_utc(meta.get("created_at") if isinstance(meta, dict) else None)


def report_ledger_rows(report_id: str, ledger_dir: Optional[str] = None) -> List[Dict[str, Any]]:
    """The report's rows in the production ledger (``ledger_dir``, default the production
    ledger) and in the evaluation ledger that record-class routing (Foglamp WP1,
    ``forecast_ledger._route_dir``) sends evaluation rows to; an injected non-default
    ``ledger_dir`` is not redirected, so its evaluation rows are in it. Reading both is
    what recognises an evaluation or golden report. The resolution monitor and
    ``load_manual_target`` share it."""
    dirs: List[str] = []
    for directory in (_route_dir(ledger_dir, "production"), _route_dir(ledger_dir, "evaluation")):
        if os.path.abspath(directory) not in {os.path.abspath(seen) for seen in dirs}:
            dirs.append(directory)
    return [row for directory in dirs for row in read_ledger(directory)
            if isinstance(row, dict) and row.get("report_id") == report_id]


def load_manual_target(report_id: Any, *, ledger_dir: Optional[str] = None,
                       publishable_fn: Optional[Callable[[str], Any]] = None,
                       load_forecast_fn: Optional[Callable[[str], Any]] = None,
                       ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """``(target, None)``: the forecast a manual attestation of ``report_id`` is checked
    against, else ``(None, reason)``. ``forecast_tools resolve`` and
    ``POST /api/v1/resolve`` share it. A target is ``{report_id, commit_id, as_of,
    created_at, scenarios, binary_forecasts, source}`` (fresh copies).

    - The report's production primary commit row (EVAL-1; ``ledger_dir``, default the
      production ledger) is the target, ``source`` 'ledger'. It is self-contained, so
      it still works after the report folder is gone. Two such rows are
      ``ambiguous_target``.
    - Rows of the report (production or evaluation ledger) none of which is a
      production primary (an ensemble member, what-if, comparison or evaluation run, a
      revision, an unpublished terminal) are ``not_production_primary``: such a
      settlement must never label production calibration (I-21).
    - No row, or legacy schema_version 1 production rows only (they prove nothing): the
      report itself, ``source`` 'report', when ``publishable_fn(report_id)`` (default
      ``ReportManager.publishable_at_issue``; it returns a bool or that method's dict,
      read by ``proves_publishable``: only an explicit True or ``{'publishable': True}``
      passes) proves it was publishable at issue (``not_publishable`` otherwise, also
      when the check raises) and
      ``load_forecast_fn`` (default ``ReportManager.load_structured_forecast`` with
      ``allow_stale_policy=True``) returns its sealed forecast (``not_sealed``
      otherwise). An evaluation run's forecast is ``evaluation_run``. The as-of date is
      unknown (None), ``created_at`` is meta.json's stamp in UTC and ``commit_id`` None.
    """
    rid = str(report_id or "").strip()
    if not rid:
        return None, TARGET_MISSING_REPORT_ID
    rows = report_ledger_rows(rid, ledger_dir)
    primaries = [row for row in rows if is_production_primary_commit(row)]
    if len(primaries) > 1:
        return None, AMBIGUOUS_TARGET
    if primaries:
        row = primaries[0]
        return {"report_id": rid, "commit_id": row.get("commit_id"),
                "as_of": row.get("as_of_date"), "created_at": row.get("created_at"),
                "scenarios": copy.deepcopy(row.get("scenarios") or []),
                "binary_forecasts": copy.deepcopy(row.get("binary_forecasts") or []),
                "source": TARGET_SOURCE_LEDGER}, None
    if any("row_type" in row or not is_production_calibration_row(row) for row in rows):
        return None, NOT_PRODUCTION_PRIMARY
    try:
        publishable = proves_publishable((publishable_fn or _publishable_at_issue)(rid))
    except Exception:  # noqa: BLE001 — a gate that cannot prove publication refuses (fail closed)
        publishable = False
    if not publishable:
        return None, TARGET_NOT_PUBLISHABLE
    try:
        forecast = (load_forecast_fn or _sealed_forecast)(rid)
    except Exception:  # noqa: BLE001 — an unreadable seal proves nothing (fail closed)
        forecast = None
    if not isinstance(forecast, dict):
        return None, TARGET_NOT_SEALED
    stamp = forecast.get("evaluation")
    if isinstance(stamp, dict) and stamp.get("record_class") == "evaluation":
        return None, TARGET_EVALUATION_RUN
    return {"report_id": rid, "commit_id": None, "as_of": None,
            "created_at": _report_created_at(rid),
            "scenarios": copy.deepcopy(forecast.get("scenarios") or []),
            "binary_forecasts": copy.deepcopy(forecast.get("binary_forecasts") or []),
            "source": TARGET_SOURCE_REPORT}, None


def manual_not_bindable_reason(target: Any, item: Any) -> Optional[str]:
    """MANUAL_NOT_BINDABLE when ``item`` attests the scenario set of a report-fallback
    target (``load_manual_target`` source 'report'), else None. ``resolved_view`` labels
    production primary commit rows only, so such an event is recorded but enters no
    calibration while the report has no such row; callers must say so instead of
    reporting a plain success. Once exactly one such row exists (a later commit, e.g.
    ``ledger_commit.recommit_reused_report``), the event labels it, judged against that
    row's origin (``resolved_view``). Binary events fold without a commit row
    (``fold_binary_items``), so they are never affected."""
    item_id = item.strip() if isinstance(item, str) else ""
    if (isinstance(target, dict) and target.get("source") == TARGET_SOURCE_REPORT
            and item_id == SCENARIO_ITEM):
        return MANUAL_NOT_BINDABLE
    return None
