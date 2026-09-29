"""EVAL-1: post-publication steps of a finished report, starting with the ledger commit.

``ReportAgent.generate_report`` calls :func:`run_post_publication` once the
report reached a terminal status and its bytes are on disk (after ``save_report``
and ``update_progress``), because ``publication_status`` reads meta.json.

The first step is the forecast-ledger commit.  In
``FORECAST_LEDGER_COMMIT_MODE=published`` (the default) the scored ledger row is
written only for a report whose exact published bytes passed the final audit,
and it copies the audit-SEALED forecast.json (post-gate confidence included),
never the in-memory draft.  A terminal report that is not publishable leaves one
never-scored ``unpublished_terminal`` row with its reasons instead.

The publication seal is the committing authority: a later seed-ensemble or
``_enforce_pipeline_health`` failure of the surrounding pipeline does not
retract a committed row (the ledger is append-only).

Later post-publication steps are appended inside :func:`run_post_publication`
after the ledger step, each in its own try/except and NOT behind the ledger
gate.  This module must not import ``report_agent`` at module level (circular
import); the agent passes ``ReportManager`` callables in.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger
from ..utils.point_in_time import validate_as_of
from . import forecast_ledger

logger = get_logger("mirofish.ledger_commit")

COMMIT_MODES = ("published", "legacy", "off")


def commit_mode() -> str:
    """The effective FORECAST_LEDGER_COMMIT_MODE; unknown values act as 'published'."""
    mode = str(getattr(Config, "FORECAST_LEDGER_COMMIT_MODE", "published") or "").strip().lower()
    return mode if mode in COMMIT_MODES else "published"


def _utc(now: Optional[datetime]) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if now.tzinfo is None:
        return now.replace(tzinfo=timezone.utc)
    return now.astimezone(timezone.utc)


def resolve_as_of(context: Optional[Mapping[str, Any]], actors: Any,
                  now: Optional[datetime] = None) -> Tuple[str, str]:
    """The pre-registration as-of date of a forecast and where it came from.

    Order: the orchestrator's validated graph anchor (``'validated'``), then the
    research actors' ``as_of_date`` when it is already a strict canonical date
    (``'actors'``; lenient parsing is never used for an identity key), else the
    UTC commit date (``'commit_date'``). Future dates are rejected at every step.
    """
    today = _utc(now).date()
    ctx = context if isinstance(context, Mapping) else {}
    act = actors if isinstance(actors, Mapping) else {}
    for value, source in ((ctx.get("as_of_date"), "validated"),
                          (act.get("as_of_date"), "actors")):
        try:
            return validate_as_of(value, today_utc=today), source
        except ValueError:
            continue
    return today.isoformat(), "commit_date"


def _record_class(context: Mapping[str, Any], scenario_label: Optional[str]) -> str:
    explicit = str(context.get("record_class") or "").strip()
    if explicit:
        return explicit
    return "conditional_scenario" if str(scenario_label or "").strip() else "production"


def _bounded_reasons(reasons: Any) -> List[str]:
    if isinstance(reasons, str):
        reasons = [reasons]
    return [str(r)[:forecast_ledger.UNPUBLISHED_REASON_MAX_CHARS]
            for r in list(reasons or [])[:forecast_ledger.UNPUBLISHED_MAX_REASONS]]


def _record_unpublished(receipt: Dict[str, Any], *, report_id: str, question: str,
                        context: Mapping[str, Any], reasons: List[str],
                        d: Optional[str], now_utc: datetime) -> Dict[str, Any]:
    receipt["status"] = "unpublished"
    receipt["reasons"] = _bounded_reasons(reasons)
    if getattr(Config, "FORECAST_LEDGER_RECORD_UNPUBLISHED", True):
        row_status, _row = forecast_ledger.record_unpublished_terminal(
            report_id=report_id,
            question_sha256=forecast_ledger.question_sha256(question),
            record_class=receipt["record_class"],
            run_ref=forecast_ledger.run_ref_for(dict(context)),
            reasons=receipt["reasons"],
            d=d,
            recorded_at=now_utc.isoformat(),
        )
    else:
        row_status = "disabled"
    receipt["unpublished_row"] = row_status
    return receipt


def commit_report(*, report_id: str, report_status: Any, error: Optional[str],
                  question: Optional[str], language: Optional[str], actors: Any,
                  scenario_label: Optional[str],
                  ledger_context: Optional[Mapping[str, Any]],
                  publication_status_fn: Callable[[str], Dict[str, Any]],
                  load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                  d: Optional[str] = None,
                  now: Optional[datetime] = None) -> Dict[str, Any]:
    """Commit one terminal report to the ledger; returns a receipt.

    Receipt: ``{status, commit_id, target_key, record_class, reasons}`` with
    ``status`` one of ``committed | revision | duplicate`` (see
    ``forecast_ledger.commit_published_forecast``), ``unpublished`` (failed or not
    publishable; an ``unpublished_terminal`` row is recorded unless
    FORECAST_LEDGER_RECORD_UNPUBLISHED is off, see ``unpublished_row``),
    ``no_structured_forecast`` (publishable but without a sealed forecast; log
    only) or ``error``. ``publication_status_fn`` is called at most once, and
    exactly once for a completed report. Unknown context keys are ignored.
    """
    ctx: Mapping[str, Any] = ledger_context if isinstance(ledger_context, Mapping) else {}
    now_utc = _utc(now)
    q_text = str(question or "")
    receipt: Dict[str, Any] = {
        "status": "error",
        "commit_id": None,
        "target_key": None,
        "record_class": _record_class(ctx, scenario_label),
        "reasons": [],
    }
    status_value = str(getattr(report_status, "value", report_status) or "").strip().lower()
    if status_value != "completed":
        return _record_unpublished(
            receipt, report_id=report_id, question=q_text, context=ctx,
            reasons=[f"report_failed: {str(error or '')[:200]}"], d=d, now_utc=now_utc)

    publication = publication_status_fn(report_id)
    if not isinstance(publication, Mapping) or publication.get("publishable") is not True:
        reasons = (list(publication.get("reasons") or [])
                   if isinstance(publication, Mapping) else [])
        return _record_unpublished(
            receipt, report_id=report_id, question=q_text, context=ctx,
            reasons=reasons or ["publication_status: not publishable"], d=d, now_utc=now_utc)

    forecast = load_forecast_fn(report_id)
    forecast_sha = str(publication.get("forecast_sha256") or "").strip()
    has_scenarios = isinstance(forecast, dict) and any(
        isinstance(s, dict) for s in (forecast.get("scenarios") or []))
    if not has_scenarios or not forecast_sha:
        receipt["status"] = "no_structured_forecast"
        logger.info(f"[ledger] {report_id} is publishable but has no sealed structured "
                    "forecast; nothing committed")
        return receipt

    as_of_date, as_of_source = resolve_as_of(ctx, actors, now_utc)
    status, row = forecast_ledger.commit_published_forecast(
        forecast,
        report_id=report_id,
        question=q_text,
        language=language,
        as_of_date=as_of_date,
        as_of_source=as_of_source,
        publication={
            "authority": "final_audit",
            "policy_version": int(getattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3)),
            "markdown_sha256": publication.get("markdown_sha256"),
            "forecast_sha256": forecast_sha,
        },
        record_class=receipt["record_class"],
        provenance=dict(ctx),
        d=d,
        committed_at=now_utc.isoformat(),
    )
    receipt["status"] = status
    if isinstance(row, dict):
        receipt["commit_id"] = row.get("commit_id")
        receipt["target_key"] = row.get("target_key")
    if status == "error":
        receipt["reasons"] = ["ledger commit failed: invalid sealed forecast or I/O error"]
    return receipt


def _ledger_step(agent: Any, report_id: str, *, report_status: Any, error: Optional[str],
                 publication_status_fn: Callable[[str], Dict[str, Any]],
                 load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                 now: Optional[datetime]) -> Dict[str, Any]:
    if not (getattr(Config, "REPORT_FORECAST_LEDGER", True) and commit_mode() == "published"):
        return {"status": "disabled"}
    raw_context = getattr(agent, "ledger_context", None)
    context = dict(raw_context) if isinstance(raw_context, Mapping) else {}
    context.setdefault("simulation_id", getattr(agent, "simulation_id", None))
    return commit_report(
        report_id=report_id,
        report_status=report_status,
        error=error,
        question=getattr(agent, "simulation_requirement", ""),
        language=getattr(agent, "output_language", None),
        actors=getattr(agent, "actors", None),
        scenario_label=getattr(agent, "scenario_label", ""),
        ledger_context=context,
        publication_status_fn=publication_status_fn,
        load_forecast_fn=load_forecast_fn,
        now=now,
    )


def run_post_publication(agent: Any, report_id: str, *, report_status: Any,
                         error: Optional[str],
                         publication_status_fn: Callable[[str], Dict[str, Any]],
                         load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                         now: Optional[datetime] = None) -> Dict[str, Any]:
    """Run every post-publication step for one terminal report; returns the ledger receipt.

    Each step is isolated (degrade-safe): a failure is logged and never changes
    the report's status or its sealed artifacts. The ledger receipt is
    ``{'status': 'disabled'}`` unless REPORT_FORECAST_LEDGER is on and the commit
    mode is 'published'.
    """
    try:
        receipt = _ledger_step(
            agent, report_id, report_status=report_status, error=error,
            publication_status_fn=publication_status_fn,
            load_forecast_fn=load_forecast_fn, now=now)
    except Exception as exc:  # noqa: BLE001 — ledger bookkeeping must never break a report
        logger.warning(f"[ledger] commit step failed for {report_id} (ignored): {exc}")
        receipt = {"status": "error", "commit_id": None, "target_key": None,
                   "record_class": None, "reasons": [f"{type(exc).__name__}: {exc}"[:300]]}
    return receipt
