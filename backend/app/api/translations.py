"""Common translation observation/actions; content stays with scoped resource APIs."""

from collections.abc import Callable
import re
import threading

from flask import Blueprint, jsonify, request

from ..services.translation import scheduler
from ..services.translation.contracts import TranslationError, canonical

translations_bp = Blueprint("translation_jobs", __name__)
_ID = re.compile(r"tj_[a-f0-9]{32}\Z")
_authorizers: dict[str, Callable[[dict, str], dict | None]] = {}
_authorizer_lock = threading.RLock()


def register_resource_authorizer(
    kind: str,
    resolver: Callable[[dict, str], dict | None],
) -> None:
    """Register a resource reader for generic retry/cancel, without starting work.

    ``resolver(selection, action)`` must enforce the current request's resource
    and visibility authority, then return its server-derived current job identity
    or None. Selection is untrusted client input, not an identity assertion. The
    reader must not simply echo it or treat possession of a job ID as authority.
    Unregistered kinds cannot be mutated through this generic API; resource routes
    retain their own admission checks and scheduler entrypoints.
    """
    if not isinstance(kind, str) or not kind or not callable(resolver):
        raise ValueError("translation authorizer requires an operation kind and callable")
    with _authorizer_lock:
        _authorizers[kind] = resolver


@translations_bp.errorhandler(TranslationError)
def service_error(exc):
    status = {"stale_job": 409, "invalid_revision": 400}.get(exc.code, 503)
    return jsonify(success=False, code=exc.code, error=exc.safe_message), status


def _read(job_id):
    if not _ID.fullmatch(job_id):
        return None
    return scheduler.status(job_id)


def _public(summary):
    # A job identifier never grants access to a private simulation projection.
    # Payload/result text is returned only by its resource/visibility reader.
    return {key: value for key, value in summary.items() if key not in {"result", "identity"}}


@translations_bp.get("/jobs/<job_id>")
def job_status(job_id):
    state = _read(job_id)
    if state is None:
        return jsonify(success=False, error="Translation job not found."), 404
    return jsonify(success=True, data=_public(state))


def _action(job_id, action, operation):
    state = _read(job_id)
    if state is None:
        return jsonify(success=False, error="Translation job not found."), 404
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(success=False, code="invalid_request", error="Expected a JSON object."), 400
    revision = payload.get("job_revision")
    if type(revision) is not int or revision < 1:
        return jsonify(
            success=False,
            code="invalid_revision",
            error="A positive integer job_revision is required.",
        ), 400
    selection = payload.get("resource")
    with _authorizer_lock:
        resolver = _authorizers.get(state["kind"])
    identity = (
        resolver(selection, operation)
        if resolver and isinstance(selection, dict) and selection
        else None
    )
    try:
        admitted = isinstance(identity, dict) and canonical(identity) == canonical(
            state["identity"]
        )
    except (TypeError, ValueError):
        admitted = False
    if not admitted:
        return jsonify(
            success=False,
            code="resource_forbidden",
            error="Use an authorized resource view to manage this translation job.",
        ), 403
    # Authority is resolved above, but revision admission must occur in the same
    # transaction as the mutation. A second action may have changed the task.
    updated = action(job_id, expected_revision=revision)
    if updated is None:
        return jsonify(success=False, error="Translation job not found."), 404
    return jsonify(success=True, data=_public(updated))


@translations_bp.post("/jobs/<job_id>/retry")
def retry_job(job_id):
    return _action(job_id, scheduler.retry, "retry")


@translations_bp.post("/jobs/<job_id>/cancel")
def cancel_job(job_id):
    return _action(job_id, scheduler.cancel, "cancel")
