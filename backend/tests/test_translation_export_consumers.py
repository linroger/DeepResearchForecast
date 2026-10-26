"""Static export follows admitted generations instead of old literal sidecars."""
import hashlib
import json
from pathlib import Path

import pytest

from scripts import export_demo_site_data as exporter
from app.services.report_agent import ReportManager
from app.services.translation.artifacts import publish_generation
from app.services.model_translation import ENGINE, translate_document
from tests.test_translation_job_v2 import Model


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def test_report_demo_reads_immutable_generation_and_rejects_stale_pointer(tmp_path, monkeypatch):
    uploads = tmp_path / "uploads"
    folder = uploads / "reports" / "report_generation"
    folder.mkdir(parents=True)
    source = folder / "full_report.md"
    source.write_text("# Outlook\n\nValue remains unchanged.")
    # The publication-policy gate is controlled; real generation/hash resolution
    # and export consumption remain active in this focused consumer scenario.
    monkeypatch.setattr(exporter, "UPLOADS", str(uploads))
    monkeypatch.setattr(ReportManager, "is_publishable", classmethod(lambda cls, *args: True))
    target = "# 展望\n\n数值保持不变。"
    snapshot = publish_generation(folder, kind="forecast_report", ref_id="report_generation", lang="zh",
        source_sha256=sha(source.read_text()), markdown=target,
        audit={"hard_passed": True, "markdown_sha256": sha(target), "source_markdown_sha256": sha(source.read_text())},
        source_path=source, assets={"figures.json": b"{}"})
    assert not (folder / "full_report.zh.md").exists()
    assert exporter.published_report_variants("report_generation", str(folder), "en") == {"zh": snapshot.markdown}
    (folder / "full_report.zh.md").write_text("obsolete sidecar")
    source.write_text(source.read_text() + " Changed source.")
    assert exporter.published_report_variants("report_generation", str(folder), "en") == {}


def test_dossier_demo_resolves_new_generation_with_real_source_review(tmp_path, monkeypatch):
    from app.api import research
    from app.config import Config
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    source = handoff / "research_report.md"
    source.write_text("## Outlook\n\nValue remains unchanged.")
    identity = research._research_body_identity("pipe_generation", sha(source.read_text()), {})
    target, proof = translate_document(Model(), source.read_text(), "zh", identity=identity)
    audit = {"hard_passed": True, "report_id": "research::pipe_generation", "language": "zh", "source_language": "en",
             "source_markdown_sha256": sha(source.read_text()), "markdown_sha256": sha(target),
             "model_translation": proof, "translator_version": ENGINE}
    root = research._research_generation_root(str(handoff), "pipe_generation")
    publish_generation(root, kind="research", ref_id="pipe_generation", lang="zh",
        source_sha256=sha(source.read_text()), markdown=target, audit=audit, source_path=source,
        assets={"figures.json": b"{}"})
    assert exporter.published_dossier_variants(str(handoff), "en", pipeline_id="pipe_generation") == {"zh": target}
    assert exporter.published_dossier_variants(str(handoff), "en", pipeline_id="pipe_other") == {}
    source.write_text(source.read_text() + " Changed.")
    assert exporter.published_dossier_variants(str(handoff), "en", pipeline_id="pipe_generation") == {}
