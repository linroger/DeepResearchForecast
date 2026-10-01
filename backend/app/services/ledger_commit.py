"""EVAL-1: post-publication steps of a finished report, starting with the ledger commit.

``ReportAgent.generate_report`` calls :func:`run_post_publication` once the
report reached its final terminal status and its bytes are on disk (after
``save_report``, ``update_progress`` and the closing progress callback), because
``publication_status`` reads meta.json and a report that still flips to FAILED
must not own a scored row.

The first step is the forecast-ledger commit.  In
``FORECAST_LEDGER_COMMIT_MODE=published`` (the default) the scored ledger row is
written only for a report whose exact published bytes passed the final audit,
and it copies the audit-SEALED forecast.json (post-gate confidence included),
never the in-memory draft.  A terminal report that is not publishable leaves one
never-scored ``unpublished_terminal`` row with its reasons instead.

The publication seal is the committing authority: a later seed-ensemble or
``_enforce_pipeline_health`` failure of the surrounding pipeline does not
retract a committed row (the ledger is append-only).

Every entry point keys the same forecast target identically: a report without
orchestrator context (``/api/report/generate`` regenerations) takes its as-of
anchor, what-if identity and (for a seed-ensemble simulation) member class and
seed from the pipeline that ran its simulation, so it becomes a revision of that
report's commit instead of a second primary. A resumed pipeline that reuses its
report repairs a commit that never landed (:func:`recommit_reused_report`).

EVAL-13: a report of an evaluation run (``agent._resolve_evaluation_context()``,
the orchestrator's pin or the owning pipeline's persisted marker) is re-classed by
:func:`apply_evaluation_context`: record_class ``evaluation``,
``characterization_only`` and eval_run_id / cell_id provenance, committed to
``forecast_ledger.evaluation_ledger_dir()``. The production ledger.jsonl never
receives such a row.

Later post-publication steps are appended inside :func:`run_post_publication`
after the ledger step, each in its own try/except and NOT behind the ledger
gate.  This module must not import ``report_agent`` at module level (circular
import); the agent passes ``ReportManager`` callables in.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from ..config import Config
from ..utils.logger import get_logger
from ..utils.point_in_time import validate_as_of
from . import forecast_ledger

logger = get_logger("mirofish.ledger_commit")

COMMIT_MODES = ("published", "legacy", "off")
EVALUATION_RECORD_CLASS = "evaluation"
# EVAL-13: why an evaluation context claims no run (pipeline_orchestrator's fail-closed
# contexts): the report was routed to the evaluation lane because it could not be shown to
# be production. First flag set wins.
EVALUATION_FAIL_CLOSED_REASONS = ("lookup_failed", "foreign_marker", "marker_unreadable",
                                  "pin_unreadable")


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


def _status_value(report_status: Any) -> str:
    return str(getattr(report_status, "value", report_status) or "").strip().lower()


def _scenario_label(context: Mapping[str, Any], scenario_label: Optional[str]) -> str:
    return str(scenario_label or context.get("scenario_label") or "").strip()


def _record_class(context: Mapping[str, Any], scenario_label: Optional[str]) -> str:
    explicit = str(context.get("record_class") or "").strip()
    if explicit:
        return explicit
    return "conditional_scenario" if _scenario_label(context, scenario_label) else "production"


def evaluation_fail_closed(evaluation: Optional[Mapping[str, Any]]
                           ) -> Tuple[Optional[str], Optional[str]]:
    """EVAL-13: ``(reason, marker_pipeline_id)`` of a fail-closed evaluation context.

    ``(None, None)`` for a run's own pin (or no context). ``marker_pipeline_id`` is
    the evaluation run whose admission a ``foreign_marker`` context inherits.
    """
    if not isinstance(evaluation, Mapping):
        return None, None
    reason = next((flag for flag in EVALUATION_FAIL_CLOSED_REASONS
                   if evaluation.get(flag) is True), None)
    if reason is None:
        return None, None
    marker_pipeline_id = str(evaluation.get("marker_pipeline_id") or "").strip() or None
    return reason, marker_pipeline_id


def apply_evaluation_context(context: Optional[Mapping[str, Any]],
                             evaluation: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """EVAL-13: a copy of ``context`` re-classed for an evaluation run.

    With an evaluation context the report belongs to the evaluation lane only:
    ``record_class='evaluation'`` (which :func:`commit_report` commits
    ``characterization_only`` into ``forecast_ledger.evaluation_ledger_dir()``)
    plus the run's ``eval_run_id`` / ``cell_id`` provenance. A fail-closed context
    (no run identity) instead records why as ``evaluation_fail_closed`` (plus
    ``evaluation_marker_pipeline_id``), so an operator can find the demoted rows.
    The class it replaces is kept as ``evaluated_record_class``, so an ensemble
    member keeps its seed and a compared provider its provider in its target.
    Idempotent; without an evaluation context the copy is unchanged.
    """
    out: Dict[str, Any] = dict(context) if isinstance(context, Mapping) else {}
    if not isinstance(evaluation, Mapping):
        return out
    prior = str(out.get("record_class") or "").strip()
    if prior and prior != EVALUATION_RECORD_CLASS:
        out["evaluated_record_class"] = prior
    out["record_class"] = EVALUATION_RECORD_CLASS
    for key in ("eval_run_id", "cell_id"):
        value = str(evaluation.get(key) or "").strip()
        if value:
            out[key] = value
    reason, marker_pipeline_id = evaluation_fail_closed(evaluation)
    if reason:
        out["evaluation_fail_closed"] = reason
        if marker_pipeline_id:
            out["evaluation_marker_pipeline_id"] = marker_pipeline_id
    return out


def _agent_evaluation_context(agent: Any) -> Optional[Mapping[str, Any]]:
    """The evaluation context of a report agent (its pin, else the owning pipeline's marker)."""
    resolve = getattr(agent, "_resolve_evaluation_context", None)
    evaluation = resolve() if callable(resolve) else getattr(agent, "evaluation_context", None)
    return evaluation if isinstance(evaluation, Mapping) else None


def _target_variant(record_class: str, context: Mapping[str, Any],
                    scenario_label: Optional[str]) -> Optional[Dict[str, Any]]:
    """What splits one question's non-production commits into separate targets.

    A what-if scenario (its overlay fingerprint, else its label), an ensemble
    member's seed and a compared provider are distinct forecasts, not revisions
    of one another. So are two evaluation runs or cells (EVAL-13): each is its
    own sample, never a revision of another run's commit. Production keys never
    carry a variant.
    """
    if record_class == "production":
        return None
    variant: Dict[str, Any] = {}
    scenario_key = str(context.get("scenario_key") or "").strip()
    label = _scenario_label(context, scenario_label)
    if scenario_key:
        variant["scenario"] = scenario_key
    elif label:
        variant["scenario"] = forecast_ledger.question_sha256(label)
    member_class = record_class
    if record_class == EVALUATION_RECORD_CLASS:
        for key in ("eval_run_id", "cell_id"):
            value = str(context.get(key) or "").strip()
            if value:
                variant[key] = value
        member_class = str(context.get("evaluated_record_class") or "").strip()
    if member_class == "ensemble_member":
        try:
            variant["seed"] = int(context.get("seed"))
        except (TypeError, ValueError):
            pass
    if member_class == "comparison":
        provider = str(context.get("provider") or "").strip()
        if provider:
            variant["provider"] = provider
    return variant or None


def _final_audit_reasons(report_id: str,
                         final_audit_path_fn: Optional[Callable[[str], str]]) -> List[str]:
    """The failing final audit's own issues, which the report error truncates.

    Mirrors ``ReportAgent._require_final_publish_audit``: hard issues (audit and
    publish gate) always fail; the publish gate's quality issues fail only when
    the gate is enabled and did not pass. [] when no audit ran (best-effort).
    """
    if final_audit_path_fn is None:
        return []
    try:
        with open(final_audit_path_fn(report_id), encoding="utf-8") as fh:
            audit = json.load(fh)
    except (OSError, ValueError, TypeError):
        return []
    if not isinstance(audit, dict):
        return []
    gate = audit.get("publish_gate") if isinstance(audit.get("publish_gate"), dict) else {}
    groups: List[Tuple[str, Any]] = [("final_audit", audit.get("hard_issues")),
                                     ("publish_gate", gate.get("hard_issues"))]
    if gate.get("enabled") and gate.get("passed") is False:
        groups.append(("publish_gate", gate.get("issues")))
    reasons: List[str] = []
    seen: set[str] = set()
    for prefix, issues in groups:
        for issue in issues if isinstance(issues, list) else []:
            text = str(issue)
            if text not in seen:  # the gate repeats the audit's hard issues
                seen.add(text)
                reasons.append(f"{prefix}: {text}")
    return reasons


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
            # The full list: the row applies the same caps and records what they removed.
            reasons=reasons,
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
                  now: Optional[datetime] = None,
                  final_audit_path_fn: Optional[Callable[[str], str]] = None,
                  ) -> Dict[str, Any]:
    """Commit one terminal report to the ledger; returns a receipt.

    Receipt: ``{status, commit_id, target_key, record_class, reasons}`` with
    ``status`` one of ``committed | revision | duplicate`` (see
    ``forecast_ledger.commit_published_forecast``), ``unpublished`` (failed or not
    publishable; an ``unpublished_terminal`` row is recorded unless
    FORECAST_LEDGER_RECORD_UNPUBLISHED is off, see ``unpublished_row``),
    ``no_structured_forecast`` (publishable but without a sealed forecast; log
    only) or ``error``. ``publication_status_fn`` is called at most once, and
    exactly once for a completed report. A failed report's reasons also carry
    its final audit's issues when ``final_audit_path_fn`` locates one. Unknown
    context keys are ignored. An ``evaluation`` record class (EVAL-13) writes
    ``characterization_only`` rows into ``forecast_ledger.evaluation_ledger_dir()``
    unless ``d`` names another directory. REPORT-11: a committed row carries the
    sealed forecast's ``quality.probability_shape`` as
    ``objective_signals.probability_shape`` while FORECAST_PROBABILITY_SHAPE is on.
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
    evaluation_row = receipt["record_class"] == EVALUATION_RECORD_CLASS
    if evaluation_row and d is None:
        d = forecast_ledger.evaluation_ledger_dir()
    if _status_value(report_status) != "completed":
        reasons = [f"report_failed: {str(error or '')[:200]}"]
        reasons.extend(_final_audit_reasons(report_id, final_audit_path_fn))
        return _record_unpublished(
            receipt, report_id=report_id, question=q_text, context=ctx,
            reasons=reasons, d=d, now_utc=now_utc)

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
    if isinstance(forecast, dict) and forecast.get("probability_status") == "needs_review":
        # REPORT-1 marks unreadable probabilities needs_review and fails the publish gate on
        # them; with that gate disabled the report can still be publishable, but its
        # probabilities are not scoreable, so it never becomes a scored row.
        return _record_unpublished(
            receipt, report_id=report_id, question=q_text, context=ctx,
            reasons=["probability_status: needs_review (probabilities unreadable, not scoreable)"],
            d=d, now_utc=now_utc)

    as_of_date, as_of_source = resolve_as_of(ctx, actors, now_utc)
    # REPORT-11: the sealed forecast's probability-shape telemetry rides on the row as
    # objective_signals; with FORECAST_PROBABILITY_SHAPE off (or a forecast without it)
    # the call and the row are unchanged.
    signal_kwargs: Dict[str, Any] = {}
    quality = forecast.get("quality")
    shape = quality.get("probability_shape") if isinstance(quality, dict) else None
    if isinstance(shape, dict) and getattr(Config, "FORECAST_PROBABILITY_SHAPE", True):
        signal_kwargs["objective_signals"] = {"probability_shape": shape}
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
        target_variant=_target_variant(receipt["record_class"], ctx, scenario_label),
        characterization_only=evaluation_row,
        **signal_kwargs,
    )
    receipt["status"] = status
    if isinstance(row, dict):
        receipt["commit_id"] = row.get("commit_id")
        receipt["target_key"] = row.get("target_key")
    if status == "error":
        receipt["reasons"] = ["ledger commit failed: invalid sealed forecast or I/O error"]
    return receipt


def _owner_identity(simulation_id: Any) -> Dict[str, Any]:
    """Identity fields of the pipeline that owns ``simulation_id`` ({} when unknown).

    See ``pipeline_orchestrator.ledger_identity_for_simulation``. Imported lazily:
    the orchestrator imports report_agent, which calls into this module.
    """
    if not simulation_id:
        return {}
    try:
        from .pipeline_orchestrator import ledger_identity_for_simulation
        identity = ledger_identity_for_simulation(str(simulation_id))
    except Exception as exc:  # noqa: BLE001 — identity enrichment is best-effort
        logger.warning(f"[ledger] owner-pipeline lookup for {simulation_id} failed (ignored): {exc}")
        return {}
    return dict(identity) if isinstance(identity, Mapping) else {}


def _published_mode_on() -> bool:
    return bool(getattr(Config, "REPORT_FORECAST_LEDGER", True)) and commit_mode() == "published"


def _ledger_step(agent: Any, report_id: str, *, report_status: Any, error: Optional[str],
                 publication_status_fn: Callable[[str], Dict[str, Any]],
                 load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                 final_audit_path_fn: Optional[Callable[[str], str]],
                 now: Optional[datetime]) -> Dict[str, Any]:
    if not _published_mode_on():
        return {"status": "disabled"}
    raw_context = getattr(agent, "ledger_context", None)
    context = dict(raw_context) if isinstance(raw_context, Mapping) else {}
    context.setdefault("simulation_id", getattr(agent, "simulation_id", None))
    if "as_of_date" not in context:
        # No orchestrator context (/api/report/generate, model comparison): key the
        # target exactly as the owning pipeline's own report does — its validated
        # as-of anchor, not the raw actors.json date, its what-if identity, and an
        # ensemble member's class and seed.
        for key, value in _owner_identity(context.get("simulation_id")).items():
            context.setdefault(key, value)
    context = apply_evaluation_context(context, _agent_evaluation_context(agent))
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
        final_audit_path_fn=final_audit_path_fn,
    )


def run_post_publication(agent: Any, report_id: str, *, report_status: Any,
                         error: Optional[str],
                         publication_status_fn: Callable[[str], Dict[str, Any]],
                         load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                         now: Optional[datetime] = None,
                         final_audit_path_fn: Optional[Callable[[str], str]] = None,
                         ) -> Dict[str, Any]:
    """Run every post-publication step for one terminal report; returns the ledger receipt.

    Each step is isolated (degrade-safe): a failure is logged and never changes
    the report's status or its sealed artifacts. The ledger receipt always names
    its ``report_id`` and is ``{'status': 'disabled', 'report_id': ...}`` unless
    REPORT_FORECAST_LEDGER is on and the commit mode is 'published'.
    """
    try:
        receipt = _ledger_step(
            agent, report_id, report_status=report_status, error=error,
            publication_status_fn=publication_status_fn,
            load_forecast_fn=load_forecast_fn, final_audit_path_fn=final_audit_path_fn,
            now=now)
    except Exception as exc:  # noqa: BLE001 — ledger bookkeeping must never break a report
        logger.warning(f"[ledger] commit step failed for {report_id} (ignored): {exc}")
        receipt = {"status": "error", "commit_id": None, "target_key": None,
                   "record_class": None, "reasons": [f"{type(exc).__name__}: {exc}"[:300]]}
    receipt["report_id"] = report_id
    _eval_bundle_step(agent, report_id, publication_status_fn=publication_status_fn,
                      load_forecast_fn=load_forecast_fn, now=now)
    return receipt


def _eval_bundle_step(agent: Any, report_id: str, *,
                      publication_status_fn: Callable[[str], Dict[str, Any]],
                      load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                      now: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """EVAL-19 (EVAL_BUNDLE_CAPTURE, default off): freeze the evaluation bundle of a
    publishable report next to it (``eval_bundle.capture_from_agent``) after the ledger
    commit. Best effort: never changes the report, its status or its artifacts; returns
    the manifest, or None when off, unpublishable or failed."""
    if not getattr(Config, "EVAL_BUNDLE_CAPTURE", False):
        return None
    try:
        if not (publication_status_fn(report_id) or {}).get("publishable"):
            return None
        from . import eval_bundle
        from .report_agent import ReportManager
        manifest = eval_bundle.capture_from_agent(
            agent, report_id, report_dir=ReportManager._get_report_folder(report_id),
            forecast=load_forecast_fn(report_id), now=now)
        logger.info(f"[eval-bundle] {report_id}: bundle {manifest['bundle_sha256'][:12]} written")
        return manifest
    except Exception as exc:  # noqa: BLE001 — capture must never break a report
        logger.warning(f"[eval-bundle] capture failed for {report_id} (ignored): {exc}")
        return None


def recommit_reused_report(report_id: str, *, report_status: Any, question: Optional[str],
                           language: Optional[str], actors: Any,
                           scenario_label: Optional[str],
                           ledger_context: Optional[Mapping[str, Any]],
                           publication_status_fn: Callable[[str], Dict[str, Any]],
                           load_forecast_fn: Callable[[str], Optional[Dict[str, Any]]],
                           d: Optional[str] = None,
                           now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
    """Repair the ledger step of a report the orchestrator reuses on resume.

    A resumed pipeline reuses its finished report instead of regenerating it, so
    a commit that never landed (the step returned 'error' on ledger I/O, or the
    process died between ``update_progress`` and the commit) would stay missing
    from both the scored ledger and the unpublished denominator. Only a
    COMPLETED report with no ledger row at all is retried: any existing row for
    it — a commit, an unpublished terminal, or a pre-EVAL-1 schema_version 1 row —
    already represents it, and a second one would count it twice. Returns the
    receipt (``repaired: True``), or None when there is nothing to repair or the
    ledger is not in 'published' mode.
    """
    rid = str(report_id or "").strip()
    if not rid or not _published_mode_on() or _status_value(report_status) != "completed":
        return None
    ctx: Mapping[str, Any] = ledger_context if isinstance(ledger_context, Mapping) else {}
    if forecast_ledger.has_report_row(rid, record_class=_record_class(ctx, scenario_label), d=d):
        return None
    receipt = commit_report(
        report_id=rid, report_status=report_status, error=None, question=question,
        language=language, actors=actors, scenario_label=scenario_label,
        ledger_context=ctx, publication_status_fn=publication_status_fn,
        load_forecast_fn=load_forecast_fn, d=d, now=now)
    receipt["report_id"] = rid
    receipt["repaired"] = True
    return receipt
