"""Disposable documents for the guarded, real-API browser translation harness.

Call ``install_documents(root, monkeypatch, app, model)`` only after installing
``main_offline_guard`` and mounting the production research/report blueprints.
``model`` is the parent's controlled model_protocol/raw_fixture_zh transport.
No translation is generated during installation: browser POSTs exercise the real
scheduler, durable units, publication receipts, and subsequent readers.

Only the native PDF renderer and its dependency fingerprint are substituted.
The real PDF exporter still resolves publication, checks source/generation drift,
audits extracted content, and publishes its immutable cache. This proves browser
download transport and language selection, not Pandoc/XeLaTeX typography.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys


DOSSIER_MARKDOWN = (
    "# Capacity outlook\n\n"
    "## Public plan\n\n"
    "The committee plans 25 MW of capacity by 2030.\n\n"
    "The infrastructure agency supplies equipment for the expansion.\n"
)
REPORT_MARKDOWN = (
    "# Capacity forecast\n\n"
    "## Capacity scenario\n\n"
    "The committee may deliver 25 MW of capacity by 2030.\n\n"
    "The forecast depends on equipment supply and construction progress.\n"
)
PDF_MARKERS = {"en": "BROWSER PDF ENGLISH", "zh": "BROWSER PDF MANDARIN"}


def install_documents(root, monkeypatch, app, model):
    """Seed real public documents and return their IDs and canonical dossier.

    ``root`` must be inside the already installed guard's disposable root.
    ``monkeypatch`` is the parent's live pytest.MonkeyPatch, retained until server
    shutdown. ``model`` may be a fake-LLM instance or a class/factory; the same
    supplied transport is wired into both local and module-level LLM imports.
    This function never installs guards, registers Flask routes, or starts jobs.
    """
    root = Path(root).resolve()
    guard = sys.modules.get("main_offline_guard")
    if guard is None or not getattr(guard, "configured", False):
        raise RuntimeError("Install the offline/browser guard before document fixtures")
    if not root.is_relative_to(Path(guard.root).resolve()):
        raise ValueError("Document fixture root must be inside the guarded disposable root")

    # Application and fixture-builder imports must remain after the guard check.
    from app.config import Config
    from app.services import report_agent
    from app.services.pipeline_orchestrator import PipelineManager, PipelineState, StageState
    from app.services.report_agent import ReportAgent, ReportManager
    from app.utils import llm_client
    from test_report_bilingual import _publish_primary
    import pymupdf as fitz

    if isinstance(model, type):
        factory = model
    elif callable(getattr(model, "chat", None)):
        factory = lambda *args, **kwargs: model
    elif callable(model):
        factory = model
    else:
        raise TypeError("model must be the supplied controlled LLM instance or factory")
    monkeypatch.setattr(llm_client, "LLMClient", factory)
    monkeypatch.setattr(report_agent, "LLMClient", factory)

    upload_root = Path(Config.UPLOAD_FOLDER).resolve()
    if not upload_root.is_relative_to(root):
        raise ValueError("Config.UPLOAD_FOLDER must already point inside the fixture root")
    pipeline_root = upload_root / "pipelines"
    reports_root = upload_root / "reports"
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipeline_root))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports_root))
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True)

    pipeline_id, report_id = "pipe_browser", "report_browser"
    handoff = Path(PipelineManager.handoff_dir(pipeline_id))
    report_folder = Path(ReportManager._get_report_folder(report_id))
    if handoff.exists() or report_folder.exists():
        raise FileExistsError("Browser document fixtures require unused document IDs")
    handoff.mkdir(parents=True)
    actors = {
        "central_question": "Will the committee deliver 25 MW of capacity by 2030?",
        "as_of_date": "2026-10-26",
        "actors": [{
            "id": "actor_infrastructure", "name": "Infrastructure Agency",
            "type": "Organization", "influence": "high",
            "role": "Supplies equipment for the capacity expansion.",
            "stance": "Supports the public construction plan.",
        }],
        "situation_brief": {"current_situation": "Equipment orders are being reviewed."},
        "hot_topics": ["Capacity expansion"],
    }
    documents = {
        "actors.json": actors,
        "sources.json": [{"source_id": "S1", "title": "Public capacity plan",
                          "url": "https://example.test/capacity"}],
        "timeline.json": [{"date": "2029-06-01", "event": "Construction begins."}],
    }
    (handoff / "research_report.md").write_bytes(DOSSIER_MARKDOWN.encode("utf-8"))
    for name, value in documents.items():
        (handoff / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    PipelineManager.save(PipelineState(
        pipeline_id=pipeline_id, prompt=actors["central_question"],
        mode="research_only", status="completed", global_progress=100,
        current_stage="research", report_id=report_id, handoff_dir=str(handoff),
        stages={"research": StageState(name="research", status="completed", progress=100)},
        artifacts={"dossier": "research_report.md", "actors": "actors.json",
                   "sources": "sources.json", "timeline": "timeline.json"},
    ))
    _publish_primary(report_id, REPORT_MARKDOWN)
    if not ReportManager.is_publishable(report_id):
        raise AssertionError("Authoritative primary-report fixture failed publication admission")

    pdf_renders = []

    def render_pdf(cls, label, markdown, folder, pdf_path):
        destination = Path(pdf_path).resolve()
        if not destination.is_relative_to(root):
            raise ValueError("Fixture renderer destination escaped disposable storage")
        language = ReportAgent._detect_translation_target(markdown)[0]
        if language not in PDF_MARKERS:
            raise ValueError("Fixture renderer needs an English or Mandarin document")
        visible = ReportManager._markdown_visible_text(markdown)
        marker = PDF_MARKERS[language]
        with fitz.open() as document:
            page = document.new_page(width=595, height=842)
            page.insert_text((48, 48), marker, fontname="helv", fontsize=14)
            remaining = page.insert_textbox(
                fitz.Rect(48, 82, 547, 790), visible,
                fontname="china-s", fontsize=11, lineheight=1.5,
            )
            if remaining < 0:
                raise AssertionError("Minimal browser PDF fixture overflowed its single page")
            document.set_metadata({"title": marker, "producer": "browser-pdf-fixture/v1",
                                   "creationDate": "D:20260101000000Z", "modDate": "D:20260101000000Z"})
            content = document.tobytes(garbage=4, deflate=True, no_new_id=True)
        destination.write_bytes(content)
        # The production exporter repeats its own content audit after this return.
        # This receipt lets browser evidence correlate the rendered accepted bytes.
        with fitz.open(stream=content, filetype="pdf") as parsed:
            extracted = "\n".join(page.get_text("text") for page in parsed)
            if marker not in extracted or "\ufffd" in extracted or "\x00" in extracted:
                raise AssertionError("Fixture PDF lost its language marker or glyphs")
        pdf_renders.append({"label": label, "language": language, "marker": marker,
                            "markdown_sha256": hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
                            "pdf_sha256": hashlib.sha256(content).hexdigest(), "pages": 1})
        return True

    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(render_pdf))
    monkeypatch.setattr(ReportManager, "_pdf_renderer_fingerprint", classmethod(lambda cls: {
        "version": "browser-pdf-fixture/v1", "renderer": "pymupdf",
        "pymupdf_version": fitz.VersionBind, "font": "builtin-china-s", "page_size": "a4",
    }))

    # Read through the actual mounted endpoint rather than hand-assembling its
    # response envelope. It includes the source digest and untouched typed fields.
    response = app.test_client().get(f"/api/research/{pipeline_id}/dossier")
    payload = response.get_json()
    if response.status_code != 200 or not payload or payload.get("success") is not True:
        raise AssertionError("Mount the real research blueprint before installing document fixtures")
    dossier = payload["data"]
    if dossier["report"] != DOSSIER_MARKDOWN:
        raise AssertionError("Canonical dossier reader returned unexpected fixture bytes")
    result = {
        "pipeline_id": pipeline_id, "report_id": report_id, "dossier": dossier,
        "pdf_markers": dict(PDF_MARKERS), "pdf_renders": pdf_renders,
        "pdf_limit": "Real publication/export/content checks with a deterministic PyMuPDF renderer; no Pandoc layout claim.",
    }
    app.extensions["translation_browser_documents"] = result
    return result
