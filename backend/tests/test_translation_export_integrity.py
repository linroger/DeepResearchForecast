"""Generation precedence and refresh discovery; no real demo publishing or provider work."""
import hashlib
import json
from pathlib import Path

import pytest

from app.config import Config
from app.api import research
from app.services import model_translation
from app.services.report_agent import ReportManager
from app.services.translation import scheduler
from app.services.translation.artifacts import publish_generation
from scripts import export_demo_site_data as exporter
from tests.test_translation_job_v2 import Model


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def forbidden(*args, **kwargs):
    raise AssertionError("export consumer attempted provider/scheduler acquisition")


def fixture(tmp_path, monkeypatch, kind):
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(uploads))
    monkeypatch.setattr(exporter, "UPLOADS", str(uploads))
    folder = (uploads / "reports" / "report_fixture" if kind == "report"
              else uploads / "pipelines" / "pipe_fixture" / "handoff")
    folder.mkdir(parents=True)
    source = folder / ("full_report.md" if kind == "report" else "research_report.md")
    source.write_text("## Outlook\n\nValue remains unchanged.")
    if kind == "report":
        # Publication-policy decisions are controlled; manifest, source, pointer
        # resolution and final revalidation stay real, as in the new parent test.
        monkeypatch.setattr(ReportManager, "is_publishable", classmethod(lambda cls, *args: True))
        target = "## 展望\n\n数值保持不变。"
        root, ref_id, artifact_kind = folder, "report_fixture", "forecast_report"
        audit = {"hard_passed": True, "markdown_sha256": sha(target),
                 "source_markdown_sha256": sha(source.read_text())}
    else:
        ref_id, artifact_kind = "pipe_fixture", "research"
        identity = research._research_body_identity(ref_id, sha(source.read_text()), {})
        target, proof = model_translation.translate_document(Model(), source.read_text(), "zh", identity=identity)
        audit = {"hard_passed": True, "report_id": "research::" + ref_id, "language": "zh", "source_language": "en",
                 "source_markdown_sha256": sha(source.read_text()), "markdown_sha256": sha(target),
                 "model_translation": proof, "translator_version": model_translation.ENGINE}
        root = research._research_generation_root(str(folder), ref_id)
    snapshot = publish_generation(root, kind=artifact_kind, ref_id=ref_id, lang="zh",
        source_sha256=sha(source.read_text()), markdown=target, audit=audit,
        source_path=source, assets={"figures.json": b"{}"})
    monkeypatch.setattr(model_translation, "_chat", forbidden)
    monkeypatch.setattr(scheduler, "start_scheduler", forbidden)
    return folder, source, target, snapshot


def eligible_legacy(folder, source, kind):
    legacy = "旧的可导出侧车文本。"
    if kind == "report":
        (folder / "full_report.zh.md").write_text(legacy)
    else:
        (folder / "research_report.zh.md").write_text(legacy)
        (folder / "research_report.translation.zh.json").write_text(json.dumps({
            "status": "available", "source_sha256": sha(source.read_text())}))
        (folder / "research_report.final_audit.zh.json").write_text(json.dumps({
            "hard_passed": True, "markdown_sha256": sha(legacy)}))
    return legacy


def read(folder, kind):
    if kind == "report":
        return exporter.published_report_variants("report_fixture", str(folder), "en")
    return exporter.published_dossier_variants(str(folder), "en", pipeline_id="pipe_fixture")


@pytest.mark.parametrize("kind", ["report", "dossier"])
@pytest.mark.parametrize("damage", ["corrupt_pointer", "stale_source", "tampered_body"])
def test_invalid_generation_never_uses_otherwise_eligible_legacy(tmp_path, monkeypatch, kind, damage):
    folder, source, target, snapshot = fixture(tmp_path, monkeypatch, kind)
    assert read(folder, kind) == {"zh": target}
    pointer = Path(snapshot.path).parent.parent / "current.json"
    if damage == "corrupt_pointer":
        pointer.write_text("{corrupt")
    elif damage == "stale_source":
        source.write_text(source.read_text() + " Changed source.")
    else:
        (Path(snapshot.path) / "document.md").write_text("tampered generation")
    legacy = eligible_legacy(folder, source, kind)
    # With no v2 pointer, the old sidecar would really be exportable. Restore
    # the invalid pointer before the negative assertion to exercise precedence.
    raw = pointer.read_bytes()
    pointer.unlink()
    assert read(folder, kind) == {"zh": legacy}
    pointer.write_bytes(raw)
    assert read(folder, kind) == {}


@pytest.mark.parametrize("kind", ["report", "dossier"])
def test_pointer_invalidated_after_resolution_is_not_exported(tmp_path, monkeypatch, kind):
    folder, source, target, snapshot = fixture(tmp_path, monkeypatch, kind)
    eligible_legacy(folder, source, kind)
    pointer = Path(snapshot.path).parent.parent / "current.json"
    if kind == "report":
        def policy(cls, *args):
            pointer.write_text("{changed-after-resolution")
            return True
        monkeypatch.setattr(ReportManager, "is_publishable", classmethod(policy))
    else:
        original = research._research_artifact
        def resolve_then_change(*args, **kwargs):
            result = original(*args, **kwargs)
            pointer.write_text("{changed-after-resolution")
            return result
        monkeypatch.setattr(research, "_research_artifact", resolve_then_change)
    assert read(folder, kind) == {}


def test_export_dossier_forwards_pipeline_id_and_uses_generation(tmp_path, monkeypatch):
    folder, source, target, snapshot = fixture(tmp_path, monkeypatch, "dossier")
    monkeypatch.setattr(exporter, "RUNS", {"fixture-demo": "pipe_fixture"})
    monkeypatch.setattr(exporter, "copy_markdown_assets", lambda *args, **kwargs: [])
    captured = []
    def capture(out, stem, primary_md, variants, primary_lang):
        captured.append((stem, variants))
        return {"en": "dossier.md", "zh": "dossier.zh.md"}
    monkeypatch.setattr(exporter, "_write_language_set", capture)
    assets, languages = exporter.export_dossier("fixture-demo", str(folder), str(tmp_path / "unused-site"))
    assert captured == [("dossier", {"zh": target})]
    assert languages["zh"] == "dossier.zh.md" and assets == []
    assert not (tmp_path / "unused-site").exists()


def test_reports_refresh_discovers_generation_only_dossier_without_old_language_map(tmp_path, monkeypatch):
    folder, source, target, snapshot = fixture(tmp_path, monkeypatch, "dossier")
    assert read(folder, "dossier") == {"zh": target}
    assert not (folder / "research_report.zh.md").exists()
    (folder.parent / "pipeline_state.json").write_text(json.dumps({
        "pipeline_id": "pipe_fixture", "report_id": "report_fixture"}))
    site = tmp_path / "temporary-site"
    out = site / "fixture-demo"
    out.mkdir(parents=True)
    (out / "report.md").write_text("synthetic report")
    (out / "dossier.md").write_text(source.read_text())
    (out / "dossier.zh.md").write_text(target)
    metadata = {"pipeline_id": "pipe_fixture", "artifact_sha256": {}}
    (out / "meta.json").write_text(json.dumps(metadata))
    monkeypatch.setattr(exporter, "RUNS", {"fixture-demo": "pipe_fixture"})
    monkeypatch.setattr(exporter, "OUT_ROOT", str(site))
    monkeypatch.setattr(exporter, "export_report", lambda *a, **kw: ([], {"en": "report.md"}))
    calls = []
    def dossier(*args, **kwargs):
        calls.append(args)
        return [], {"en": "dossier.md", "zh": "dossier.zh.md"}
    monkeypatch.setattr(exporter, "export_dossier", dossier)
    exporter.refresh_demo_reports("fixture-demo", "pipe_fixture")
    without_old_map = len(calls)
    # Valid control: the same new generation is reachable when metadata already
    # has a dossier map. No real site or provider is used by either path.
    metadata["dossier_languages"] = {"en": "dossier.md"}
    (out / "meta.json").write_text(json.dumps(metadata))
    calls.clear()
    exporter.refresh_demo_reports("fixture-demo", "pipe_fixture")
    assert len(calls) == 1
    assert without_old_map == 1, "generation-only dossier was skipped by the preflight lookup without pipeline_id"
