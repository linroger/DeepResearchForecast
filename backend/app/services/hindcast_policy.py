"""Hindcast policy pin and its report-stage labels (TIME-6).

A hindcast answers a question as of a past date. Its admission (TIME-7) pins one
``hindcast_policy_v1`` snapshot into ``state.options``; everything downstream reads
that pin instead of today's environment, so a hindcast can never reach a report
stage that requotes live Polymarket odds or falls back to a live market fetch.

Search and fetch are not clamped to the as-of date (``search: 'unbounded'``,
``fetch: 'label'``): the run is labelled as characterization-only instead, and
contamination is reported as ``not_assessed`` until an assessor exists.

``markets: 'withheld'`` (and run.json ``live_data_withheld``) speaks for the whole
run together with admission (TIME-7), the only creator of a pin, which also runs
the research child with ``PREDICTION_MARKETS_ENABLED=false``: no research-time
market snapshot (``prediction_markets.json``, ``market_price_history.json``) then
exists for the simulation's market priors, the persona market block or the report
visualizer to read, and the report stage never reads, requotes or live-fetches one.

An as-of equal to today is pinned but live (``hindcast`` False), so
:func:`hindcast_policy` returns None for it and nothing changes.

TIME-8 adds the pin's ``pit`` block (:func:`capture_pit_policy_v1`): the
point-in-time evidence gates of the hindcast's v3 research, read from Config once
at admission.  :func:`pit_research_env` turns it into the research child's
``RESEARCH_PIT_*`` env; a pin without ``pit`` (admitted before TIME-8) runs without
gates.  With ``pit.gates`` on, search and fetch are date-gated rather than only
labelled; the ``search`` / ``fetch`` labels above and the report's integrity label
stay as they are until the research audit (TIME-9) can vouch for the gates.

Pure and stdlib-only apart from :func:`capture_pit_policy_v1`, which reads Config;
nothing here touches the network or the filesystem.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Mapping, Optional

HINDCAST_POLICY_VERSION = "hindcast-policy/v1"
# Key of the pin in PipelineState.options.
HINDCAST_POLICY_OPTION = "hindcast_policy_v1"
AS_OF_ENFORCEMENT_SCHEMA = "as-of-enforcement/v1"
# TIME-8: the research child env a gated hindcast gets (see pit_research_env).
PIT_RESEARCH_ENV_PREFIX = "RESEARCH_PIT_"
# The one backend clamp of PIT_SEARCH_OVERFETCH (the v3 child's PitPolicy bound is
# research_gateway.PIT_OVERFETCH_MAX; the processes share no code).
PIT_OVERFETCH_MAX = 4


def capture_hindcast_policy_v1(as_of: str, *, research_engine: str,
                               today_utc: Optional[date] = None) -> dict[str, Any]:
    """The ``hindcast_policy_v1`` admission pin for ``as_of`` (canonical ``YYYY-MM-DD``).

    The caller validates ``as_of`` (``utils.point_in_time.validate_as_of``); an
    unparseable value raises ValueError here. ``hindcast`` is True only when the
    as-of date lies strictly before today's UTC date (``today_utc`` injects it; a
    ``datetime`` is reduced to its UTC date: an aware one is converted to UTC
    first, a naive one is taken as UTC).
    """
    if today_utc is None:
        today = datetime.now(timezone.utc).date()
    elif isinstance(today_utc, datetime):
        if today_utc.utcoffset() is not None:
            today_utc = today_utc.astimezone(timezone.utc)
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
        "pit": capture_pit_policy_v1(),
    }


def _pit_overfetch(value: Any) -> int:
    """``value`` as an over-fetch multiplier clamped to 1..PIT_OVERFETCH_MAX (1 when unreadable)."""
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError):
        return 1
    return max(1, min(PIT_OVERFETCH_MAX, number))


def capture_pit_policy_v1() -> dict[str, Any]:
    """The pin's ``pit`` block: Config's point-in-time gate knobs (TIME-8) at admission.

    ``gates`` (PIT_GATES), ``same_day`` (``exclude``/``include``), ``undated``
    (``drop``/``flag``), ``provider_bounds`` and ``overfetch`` (clamped to
    1..PIT_OVERFETCH_MAX).  Values outside those sets read as the strict choice.  The
    only reader of Config.PIT_*: the research launch reads the pin, so a resume after a
    config change keeps the admitted gates.
    """
    from ..config import Config

    return {
        "gates": bool(Config.PIT_GATES),
        "same_day": "include" if Config.PIT_SAME_DAY_POLICY == "include" else "exclude",
        "undated": "flag" if Config.PIT_UNDATED_POLICY == "flag" else "drop",
        "provider_bounds": bool(Config.PIT_PROVIDER_DATE_BOUNDS),
        "overfetch": _pit_overfetch(Config.PIT_SEARCH_OVERFETCH),
    }


def pit_research_env(pit: Any) -> dict[str, str]:
    """The research child env of a pin's ``pit`` block (TIME-8); ``{}`` unless ``gates`` is True.

    ``RESEARCH_PIT_GATES`` / ``_SAME_DAY`` / ``_UNDATED`` / ``_PROVIDER_BOUNDS`` /
    ``_OVERFETCH`` plus ``RESEARCH_SOURCE_DATES=true`` (the gates read source dates).
    Values are normalized the way :func:`capture_pit_policy_v1` writes them, so a
    hand-edited pin still reads strict (a missing or unreadable ``provider_bounds``
    reads as its default, on).  The caller writes this only for a pinned
    hindcast and removes every ambient ``RESEARCH_PIT_*`` key first.
    """
    if not isinstance(pit, Mapping) or pit.get("gates") is not True:
        return {}
    return {
        "RESEARCH_PIT_GATES": "true",
        "RESEARCH_PIT_SAME_DAY": "include" if pit.get("same_day") == "include" else "exclude",
        "RESEARCH_PIT_UNDATED": "flag" if pit.get("undated") == "flag" else "drop",
        # The provider bound is off only when the pin says False (its default is on).
        "RESEARCH_PIT_PROVIDER_BOUNDS": "false" if pit.get("provider_bounds") is False else "true",
        "RESEARCH_PIT_OVERFETCH": str(_pit_overfetch(pit.get("overfetch", 1))),
        "RESEARCH_SOURCE_DATES": "true",
    }


def as_hindcast_pin(value: Any) -> Optional[dict[str, Any]]:
    """``value`` as a hindcast pin (a copy), or None when it is not one.

    A pin counts only when it is an object of this policy version whose
    ``hindcast`` flag is True: an as-of equal to today is pinned but live, and a
    missing, empty or foreign value is no pin.
    """
    if not isinstance(value, Mapping):
        return None
    if value.get("version") != HINDCAST_POLICY_VERSION or value.get("hindcast") is not True:
        return None
    return dict(value)


def hindcast_policy(options: Any) -> Optional[dict[str, Any]]:
    """The run's hindcast pin (a copy), or None for a live run.

    ``options`` is a pipeline's ``state.options``; its ``hindcast_policy_v1``
    value counts as described in :func:`as_hindcast_pin`.
    """
    if not isinstance(options, Mapping):
        return None
    return as_hindcast_pin(options.get(HINDCAST_POLICY_OPTION))


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
