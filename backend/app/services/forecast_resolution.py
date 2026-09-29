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
- The resolution date is the LATEST ISO date the binary names
  (``settlement_resolution_date``): a baseline date written before the deadline
  must not trigger a premature terminal or end-date mismatch, which are
  append-only facts.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from ..utils.point_in_time import parse_stamp_strict
from ..utils.prediction_markets import current_uma_status, parse_market_end
from .forecast_extractor import (
    _MARKET_EQUIVALENCE_RANK,
    _market_anchor_complete,
    audit_market_anchor_integrity,
)
from .forecast_ledger import (
    _ISO_DATE_RE,
    MARKET_RESOLUTION_EVENT_SCHEMA_VERSION,
    binary_resolution_date,
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
# A market may end up to a week after the binary's resolution date (settlement lag);
# a later end means the market resolves a different window.
END_DATE_TOLERANCE = timedelta(days=7)
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


def settlement_resolution_date(binary: Any) -> Optional[str]:
    """The binary's resolution date for settlement: the LATEST real calendar date
    (``YYYY-MM-DD``) named in ``resolution_criteria``, ``resolution_source`` or
    ``statement``, else 31 Dec of ``horizon_year``; None when there is neither.

    ``forecast_ledger.binary_resolution_date`` takes the FIRST date, so a
    baseline written before the deadline ('exceeds the 2024-12-31 level by
    2027-06-30') would read as the resolution date. Settlement writes
    append-only facts from this date (a grace terminal, an end-date mismatch):
    a late date only delays them, an early one records them wrongly for good,
    so the latest date wins (the rule of resolution_date_for_horizon).
    """
    if not isinstance(binary, dict):
        return None
    named: List[str] = []
    for key in ("resolution_criteria", "resolution_source", "statement"):
        for match in _ISO_DATE_RE.finditer(str(binary.get(key) or "")):
            try:
                date.fromisoformat(match.group(1))
            except ValueError:
                continue  # '2026-02-30' is not a date; it can be neither deadline nor baseline
            named.append(match.group(1))
    if named:
        return max(named)
    return binary_resolution_date({"horizon_year": binary.get("horizon_year")})


def market_eligibility(binary: Any, anchor: Any,
                       min_equivalence: str = "exact") -> Tuple[bool, Optional[str]]:
    """``(ok, reason)``: may this anchor's market settlement label ``binary``?

    Reasons, checked in order: ``anchor_incomplete`` (forecast_extractor's
    completeness contract, which admits only an ``exact`` or ``near``
    equivalence, so a ``loose`` or missing one always stops here),
    ``binding_invalid`` (the anchor-integrity audit: wrong proposition, or a
    contract hash that no longer matches the binary's statement and criteria),
    ``equivalence_<level>`` below the ``min_equivalence`` floor (unknown floors
    act as ``exact``; a ``loose`` floor therefore admits what ``near`` does),
    ``end_date_unverifiable`` (an unparseable market end or a binary without a
    resolution date) and ``end_date_mismatch`` (the market ends more than
    END_DATE_TOLERANCE after the binary's ``settlement_resolution_date``).
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
    resolution_end = parse_market_end(settlement_resolution_date(binary))
    if market_end is None or resolution_end is None:
        return False, "end_date_unverifiable"
    if market_end > resolution_end + END_DATE_TOLERANCE:
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
    eligible, eligibility_reason = market_eligibility(binary, anchor, min_equivalence)
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


def _settled_forecast_ids(report_id: str, events: Optional[Iterable[Any]]) -> Set[str]:
    """Forecast ids of ``report_id`` that already hold a non-terminal event in the ledger."""
    out: Set[str] = set()
    for event in events or []:
        if (isinstance(event, dict) and str(event.get("report_id") or "") == report_id
                and event.get("market_id") != TERMINAL_MARKET_ID
                and event.get("source_kind") != SOURCE_KIND_TERMINAL):
            out.add(str(event.get("forecast_id") or ""))
    return out


def recorded_items(events: Optional[Iterable[Any]]) -> Set[Tuple[str, str]]:
    """``(report_id, forecast_id)`` pairs that already hold any resolutions row: a
    settled, ambiguous or terminal event, or a legacy settled row. Such an item is
    final; nothing a later sweep decides can be appended for it as a new fact."""
    out: Set[Tuple[str, str]] = set()
    for event in events or []:
        if isinstance(event, dict):
            out.add((str(event.get("report_id") or ""), str(event.get("forecast_id") or "")))
    return out


def has_open_items(report_id: Any, binaries: Any, recorded: Set[Tuple[str, str]]) -> bool:
    """True when some binary of the target can still receive an event: it has an id,
    no row in ``recorded`` (see ``recorded_items``) and either a market anchor to
    settle on or a resolution date whose grace period can expire. A target with no
    such binary has nothing left to settle and must not use up a sweep's cap."""
    rid = str(report_id or "").strip()
    for binary in binaries if isinstance(binaries, list) else []:
        if not isinstance(binary, dict):
            continue
        forecast_id = str(binary.get("id") or "").strip()
        if not forecast_id or (rid, forecast_id) in recorded:
            continue
        anchor = binary.get("market_anchor")
        if (isinstance(anchor, dict) and str(anchor.get("market_id") or "").strip()) or (
                settlement_resolution_date(binary)):
            return True
    return False


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
    terminal one. ``answered_market_ids`` are the markets the source answered
    for (``PolymarketClient.fetch_resolutions_answered``: every id of a request
    batch that succeeded, returned or confirmed missing); None means only the
    markets present in ``resolutions``.

    Returns ``{events, terminal, pending_by_reason, ineligible_by_reason}``.
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
    already_settled = _settled_forecast_ids(rid, existing_events)
    events: List[Dict[str, Any]] = []
    terminal: List[Dict[str, Any]] = []
    pending: Counter = Counter()
    ineligible: Counter = Counter()
    for binary in binaries if isinstance(binaries, list) else []:
        if not isinstance(binary, dict):
            continue
        forecast_id = str(binary.get("id") or "").strip()
        if not forecast_id:
            pending["missing_forecast_id"] += 1
            continue
        anchor = binary.get("market_anchor") if isinstance(binary.get("market_anchor"), dict) else None
        market_id = str((anchor or {}).get("market_id") or "").strip()
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
    }
