"""Agent-backed PDF job routes; generation starts only on an explicit POST."""
from io import BytesIO

from flask import Blueprint, jsonify, request, send_file

from ..services.research_pdf.contracts import PdfExportError
from ..services.research_pdf.jobs import get_jobs

research_pdf_bp = Blueprint("research_pdf", __name__)


def _error(error):
    code = error.code
    if code in {"invalid_resource", "invalid_language", "invalid_request"}:
        status = 400
    elif code in {"source_missing", "export_not_found"}:
        status = 404
    elif code in {"pdf_export_disabled", "export_configuration", "export_busy"}:
        status = 503
    else:
        status = 409
    return jsonify({"success": False, "error": error.message, "code": code,
                    "retryable": error.retryable}), status


def _handle(kind, resource_id, job_id=None, action="start"):
    try:
        service = get_jobs()
        if action == "start":
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or set(body) - {"lang", "retry"}:
                raise PdfExportError("invalid_request", "Supply only the selected language and optional retry flag.")
            job = service.start(kind, resource_id, body.get("lang"), retry=body.get("retry", False))
            return jsonify({"success": True, "data": job}), 200 if job["state"] == "completed" else 202
        if action == "download":
            raw, name, job = service.download(kind, resource_id, job_id)
            response = send_file(BytesIO(raw), mimetype="application/pdf", as_attachment=True,
                                 download_name=name, max_age=0)
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-PDF-Export-Job"] = job["job_id"]
            response.headers["X-PDF-Export-Language"] = job["language"]
            response.headers["X-PDF-Source-Digest"] = job["source_digest"]
            return response
        job = service.cancel(kind, resource_id, job_id) if action == "cancel" else service.status(kind, resource_id, job_id)
        return jsonify({"success": True, "data": job})
    except PdfExportError as exc:
        return _error(exc)
    except (OSError, ValueError, TypeError, KeyError):
        return jsonify({"success": False, "error": "The PDF export could not be processed. Its source files are unchanged.",
                        "code": "export_internal_error", "retryable": True}), 500


@research_pdf_bp.post("/research/<resource_id>/dossier/pdf-export")
def start_dossier_pdf(resource_id):
    return _handle("dossier", resource_id)


@research_pdf_bp.get("/research/<resource_id>/dossier/pdf-export/<job_id>")
def dossier_pdf_status(resource_id, job_id):
    return _handle("dossier", resource_id, job_id, "status")


@research_pdf_bp.get("/research/<resource_id>/dossier/pdf-export/<job_id>/download")
def download_dossier_pdf(resource_id, job_id):
    return _handle("dossier", resource_id, job_id, "download")


@research_pdf_bp.post("/research/<resource_id>/dossier/pdf-export/<job_id>/cancel")
def cancel_dossier_pdf(resource_id, job_id):
    return _handle("dossier", resource_id, job_id, "cancel")


@research_pdf_bp.post("/report/<resource_id>/pdf-export")
def start_forecast_pdf(resource_id):
    return _handle("forecast", resource_id)


@research_pdf_bp.get("/report/<resource_id>/pdf-export/<job_id>")
def forecast_pdf_status(resource_id, job_id):
    return _handle("forecast", resource_id, job_id, "status")


@research_pdf_bp.get("/report/<resource_id>/pdf-export/<job_id>/download")
def download_forecast_pdf(resource_id, job_id):
    return _handle("forecast", resource_id, job_id, "download")


@research_pdf_bp.post("/report/<resource_id>/pdf-export/<job_id>/cancel")
def cancel_forecast_pdf(resource_id, job_id):
    return _handle("forecast", resource_id, job_id, "cancel")
