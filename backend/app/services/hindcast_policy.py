"""Hindcast policy pin and its report-stage labels (TIME-6).

A hindcast answers a question as of a past date. Its admission (TIME-7) pins one
``hindcast_policy_v1`` snapshot into ``state.options``; everything downstream reads
that pin instead of today's environment, so a hindcast can never reach a report
stage that requotes live Polymarket odds or falls back to a live market fetch.

Search and fetch are not clamped to the as-of date (``search: 'unbounded'``,
``fetch: 'label'``): the run is labelled as characterization-only instead, and
contamination is reported as ``not_assessed`` until an assessor exists.

An as-of equal to today is pinned but live (``hindcast`` False), so
:func:`hindcast_policy` returns None for it and nothing changes.

Pure and stdlib-only; nothing here touches the network or the filesystem.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

HINDCAST_POLICY_VERSION = "hindcast-policy/v1"
# Key of the pin in PipelineState.options.
HINDCAST_POLICY_OPTION = "hindcast_policy_v1"
AS_OF_ENFORCEMENT_SCHEMA = "as-of-enforcement/v1"


def capture_hindcast_policy_v1(as_of: str, *, research_engine: str,
                               today_utc: Optional[date] = None) -> dict[str, Any]:
    """The ``hindcast_policy_v1`` admission pin for ``as_of`` (canonical ``YYYY-MM-DD``).

    The caller validates ``as_of`` (``utils.point_in_time.validate_as_of``); an
    unparseable value raises ValueError here. ``hindcast`` is True only when the
    as-of date lies strictly before today's UTC date (``today_utc`` injects it; a
    ``datetime`` is reduced to its date).
    """
    if today_utc is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(today_utc, datetime):
        today = today_utc.date()
    else:
        today = today_utc
    return {
        "version": HINDCAST_POLICY_VERSION,
        "origin": "admission",
        "pinned_at": datetime.now(timezone.utc).isoformat(),
        "as_of": as_of,
        "hindcast": date.fromisoformat(as_of) < today,
        "research_engine": research_engine,
        "markets": "withheld",
        "fetch": "label",
        "search": "unbounded",
    }


def hindcast_policy(options: Any) -> Optional[dict[str, Any]]:
    """The run's hindcast pin (a copy), or None for a live run.

    ``options`` is a pipeline's ``state.options``. The pin counts only when it is
    an object of this policy version whose ``hindcast`` flag is True: an as-of
    equal to today is pinned but live, and a missing or foreign value is no pin.
    """
    if not isinstance(options, Mapping):
        return None
    pin = options.get(HINDCAST_POLICY_OPTION)
    if not isinstance(pin, Mapping):
        return None
    if pin.get("version") != HINDCAST_POLICY_VERSION or pin.get("hindcast") is not True:
        return None
    return dict(pin)


def hindcast_forecast_block(pin: Mapping[str, Any], *,
                            research_audit: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """``forecast['hindcast']``: how a hindcast report was contained and what was not checked.

    Markets were withheld, retrieval ran live and is labelled rather than clamped,
    and contamination was not assessed, so the forecast is characterization-only.
    ``research_audit`` is the pin's research audit; TIME-9 maps it to ``integrity``.
    Until then every hindcast is reported as ``integrity: 'labelled'``.
    """
    return {
        "as_of": pin.get("as_of"),
        "policy_version": pin.get("version"),
        "markets": "withheld",
        "retrieval": "live_labelled",
        "integrity": "labelled",
        "contamination": "not_assessed",
        "characterization_only": True,
    }


def as_of_enforcement_record(pin: Mapping[str, Any]) -> dict[str, Any]:
    """``run.json`` ``resolved.as_of_enforcement`` for a pinned hindcast run.

    Retrieval is not clamped to the as-of date (TIME-9 updates the flag when it
    is); live market data is withheld from the report stage.
    """
    return {
        "schema": AS_OF_ENFORCEMENT_SCHEMA,
        "as_of": pin.get("as_of"),
        "retrieval_clamped": False,
        "live_data_withheld": True,
        "research_engine": pin.get("research_engine"),
    }
