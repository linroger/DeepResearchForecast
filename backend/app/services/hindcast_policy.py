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
labelled; the pin's ``search`` / ``fetch`` labels above stay as admitted.

TIME-9 adds the research audit: the gated v3 child writes ``point_in_time.json``
(an independent date re-check of the sources its report cites), and the parent
records its verdict once per research generation as the pin's ``research_audit``
(:func:`research_audit_record`: ``status`` plus the file's ``sha256``, for an audit
of this pin's as-of and policies whose verdict its own counts imply) before the
report stage reads the pin.  For a pin whose gates ran, :func:`hindcast_forecast_block`
maps that verdict to ``forecast['hindcast']['integrity']`` and
:func:`as_of_enforcement_record` to run.json's ``retrieval_clamped`` /
``audit_status``; without a (valid) audit, or without gates, both keep their TIME-6
values.  A violated audit fails nothing: a hindcast is evaluation-only and the
verdict labels it.

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
# TIME-9: the gated v3 child's research audit (linear_research.POINT_IN_TIME_FILENAME
# / POINT_IN_TIME_SCHEMA; the processes share no code) and the verdicts it can state.
POINT_IN_TIME_FILENAME = "point_in_time.json"
POINT_IN_TIME_SCHEMA = "drf-point-in-time/v1"
AUDIT_DATE_VERIFIED = "date_verified"
AUDIT_DATE_VERIFIED_WITH_UNVERIFIABLE = "date_verified_with_unverifiable"
AUDIT_VIOLATED = "violated"
# research_audit.status -> forecast['hindcast']['integrity'].
_AUDIT_INTEGRITY = {
    AUDIT_DATE_VERIFIED: "date_verified",
    AUDIT_DATE_VERIFIED_WITH_UNVERIFIABLE: "date_verified_with_unverifiable",
    AUDIT_VIOLATED: "leak_suspected",
}
# The counters of the audit's ``streams.cited`` re-check: ``checked`` and its split.
_CITED_COUNTERS = ("checked", "admitted", "same_day", "unverifiable", "late")


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


def research_audit_record(payload: Any, sha256: Any, *,
                          pin: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    """The ``research_audit`` of ``pin`` for a parsed ``point_in_time.json`` (TIME-9), or None.

    ``{'status', 'sha256'}`` when ``pin``'s gates ran (``pit.gates``), ``payload`` is
    an object of POINT_IN_TIME_SCHEMA audited for this pin (its ``as_of`` is the pin's
    and its ``same_day_policy`` / ``undated_policy`` are the ones
    :func:`pit_research_env` launched the research with), its ``status`` is the verdict
    its own ``streams.cited`` counts imply (:func:`_cited_verdict`) and ``sha256`` is
    the file's hex digest.  Anything else, such as an audit of another run's research
    left in the handoff or a hand-edited verdict, vouches for nothing (None: the report
    stays labelled).
    """
    env = pit_research_env(pin.get("pit")) if isinstance(pin, Mapping) else {}
    if not env or not isinstance(payload, Mapping) or payload.get("schema") != POINT_IN_TIME_SCHEMA:
        return None
    as_of = pin.get("as_of")
    if (not isinstance(as_of, str) or payload.get("as_of") != as_of
            or payload.get("same_day_policy") != env["RESEARCH_PIT_SAME_DAY"]
            or payload.get("undated_policy") != env["RESEARCH_PIT_UNDATED"]):
        return None
    status = payload.get("status")
    if (status not in _AUDIT_INTEGRITY or status != _cited_verdict(payload)
            or not isinstance(sha256, str) or not sha256):
        return None
    return {"status": status, "sha256": sha256}


def _cited_verdict(payload: Mapping[str, Any]) -> Optional[str]:
    """The verdict ``payload``'s ``streams.cited`` counts and undated policy imply, or None.

    The v3 child's rule (``linear_research.pit_audit_status``): ``violated`` when a cited
    source is late, else ``date_verified_with_unverifiable`` when one is undated, the
    undated policy is ``flag`` or nothing was cited, else ``date_verified``.  None when
    the counts are not non-negative integers whose split sums to ``checked``.
    """
    streams = payload.get("streams")
    cited = streams.get("cited") if isinstance(streams, Mapping) else None
    if not isinstance(cited, Mapping):
        return None
    counts = [cited.get(key) for key in _CITED_COUNTERS]
    if not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts):
        return None
    checked, _admitted, _same_day, unverifiable, late = counts
    if checked != sum(counts[1:]):
        return None
    if late:
        return AUDIT_VIOLATED
    if unverifiable or payload.get("undated_policy") == "flag" or not checked:
        return AUDIT_DATE_VERIFIED_WITH_UNVERIFIABLE
    return AUDIT_DATE_VERIFIED


def _audit_status(pin: Mapping[str, Any], research_audit: Any) -> Optional[str]:
    """The verdict of ``pin``'s research audit, or None.

    None for a missing or unrecognised audit, and for any audit on a pin whose gates did
    not run (``pit.gates`` not True: a hand-edited or migrated pin): without the gates no
    audit vouches for the retrieval.
    """
    pit = pin.get("pit") if isinstance(pin, Mapping) else None
    if (not isinstance(pit, Mapping) or pit.get("gates") is not True
            or not isinstance(research_audit, Mapping)):
        return None
    status = research_audit.get("status")
    return status if status in _AUDIT_INTEGRITY else None


def hindcast_forecast_block(pin: Mapping[str, Any], *,
                            research_audit: Optional[Mapping[str, Any]] = None) -> dict[str, Any]:
    """``forecast['hindcast']``: how a hindcast report was contained and what was not checked.

    Markets were withheld and contamination was not assessed, so the forecast is
    characterization-only.  ``research_audit`` is the pin's research audit (TIME-9):
    with a recognised verdict on a pin whose gates ran (``pit.gates``), retrieval was
    ``date_gated`` and ``integrity`` is ``date_verified``,
    ``date_verified_with_unverifiable`` or, for a ``violated`` audit,
    ``leak_suspected``.  Without one (no gates, an audit that was not written, or an
    unrecognised value) retrieval is ``live_labelled`` and ``integrity``
    ``labelled``, exactly as before TIME-9.
    """
    status = _audit_status(pin, research_audit)
    return {
        "as_of": pin.get("as_of"),
        "policy_version": pin.get("version"),
        "markets": "withheld",
        "retrieval": "date_gated" if status is not None else "live_labelled",
        "integrity": _AUDIT_INTEGRITY[status] if status is not None else "labelled",
        "contamination": "not_assessed",
        "characterization_only": True,
    }


def as_of_enforcement_record(pin: Mapping[str, Any]) -> dict[str, Any]:
    """``run.json`` ``resolved.as_of_enforcement`` for a pinned hindcast run.

    Live market data is withheld from the report stage.  Retrieval counts as
    clamped to the as-of date only when the pin's gates ran (``pit.gates``) and its
    research audit (TIME-9) is not ``violated``; the audit's verdict is then
    recorded as ``audit_status``.  Without a recognised audit on a gated pin (the
    same rule as :func:`hindcast_forecast_block`) the record is the TIME-6 one (not
    clamped, no ``audit_status``).
    """
    record: dict[str, Any] = {
        "schema": AS_OF_ENFORCEMENT_SCHEMA,
        "as_of": pin.get("as_of"),
        "retrieval_clamped": False,
        "live_data_withheld": True,
        "research_engine": pin.get("research_engine"),
    }
    status = _audit_status(pin, pin.get("research_audit"))
    if status is not None:
        record["retrieval_clamped"] = status != AUDIT_VIOLATED
        record["audit_status"] = status
    return record
