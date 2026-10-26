"""Publication and export scenarios using isolated fixtures, never saved reports."""
import hashlib
import json
from pathlib import Path
import threading

import pytest

from app.services.translation import artifacts
from app.services.report_agent import ReportManager


def _publication(tmp_path, markdown="# 中文报告\n\n风险为20%。\n", **extra):
    source = tmp_path / "source.md"
    if not source.exists():
        source.write_text("# English report\n\nThe risk is 20%.\n")
    sha = artifacts.file_digest(source)
    audit = {"hard_passed": True, "source_markdown_sha256": sha,
             "markdown_sha256": artifacts.digest(markdown.encode())}
    return dict(root=str(tmp_path), kind="forecast_report", ref_id="report_fixture", lang="zh",
                source_sha256=sha, markdown=markdown, audit=audit, source_path=str(source), **extra)


def _resolve(args):
    return artifacts.resolve_generation(**{key: args[key] for key in
        ("root", "kind", "ref_id", "lang", "source_sha256", "source_path")})


def test_restart_after_pointer_commit_reads_without_coordination_store(tmp_path, monkeypatch):
    args = _publication(tmp_path, assets={"citations.json": {"markers": []}})
    first = artifacts.publish_generation(**args)
    # The scheduler may crash before finishing its DB task: the pointer is sufficient.
    monkeypatch.setattr("app.services.translation.scheduler.status",
                        lambda *a: pytest.fail("read must not access scheduler"))
    read = _resolve(args)
    assert read.generation == first.generation
    assert read.markdown == args["markdown"]
    assert json.loads(read.assets["citations.json"]) == {"markers": []}
    assert artifacts.publish_generation(**args).generation == first.generation


def test_crash_before_pointer_replace_retains_whole_previous_generation(tmp_path, monkeypatch):
    args = _publication(tmp_path)
    old = artifacts.publish_generation(**args)
    replacement = _publication(tmp_path, markdown="# 新报告\n\n风险为20%。\n")
    atomic = artifacts.atomic_bytes
    def crash(path, value):
        if Path(path).name == "current.json":
            raise OSError("fixture pointer commit interruption")
        atomic(path, value)
    monkeypatch.setattr(artifacts, "atomic_bytes", crash)
    with pytest.raises(OSError):
        artifacts.publish_generation(**replacement)
    assert _resolve(args).generation == old.generation
    assert _resolve(args).audit == old.audit


def test_source_drift_and_cancelled_owner_cannot_publish(tmp_path):
    args = _publication(tmp_path)
    old = artifacts.publish_generation(**args)
    def cancelled():
        raise artifacts.ArtifactError("cancelled", "Operation was cancelled")
    with artifacts.publication_fence(cancelled), pytest.raises(artifacts.ArtifactError, match="cancelled"):
        artifacts.publish_generation(**_publication(tmp_path, markdown="# 新报告\n"))
    assert _resolve(args).generation == old.generation
    Path(args["source_path"]).write_text("# A different canonical source\n")
    with pytest.raises(artifacts.ArtifactError) as caught:
        artifacts.publish_generation(**args)
    assert caught.value.code == "stale_artifact"


def test_corrupt_generation_never_falls_back_to_legacy(tmp_path):
    args = _publication(tmp_path)
    snap = artifacts.publish_generation(**args)
    (tmp_path / "full_report.zh.md").write_text("# Legacy body\n")
    (Path(snap.path) / "document.md").write_text("# Modified bytes\n")
    with pytest.raises(artifacts.ArtifactError) as caught:
        _resolve(args)
    assert caught.value.code == "invalid_artifact"


def test_generation_binds_figures_before_export(tmp_path, renderer):
    charts = tmp_path / "charts"
    charts.mkdir()
    figure = charts / "capacity.png"
    figure.write_bytes(b"original figure fixture")
    args = _publication(tmp_path, markdown="# 中文报告\n\n![产能](charts/capacity.png)\n")
    snapshot = artifacts.publish_generation(**args)
    inventory = json.loads(snapshot.assets["figures.json"])
    assert inventory == {"charts/capacity.png": artifacts.file_digest(figure)}
    figure.write_bytes(b"changed figure fixture")
    with pytest.raises(artifacts.ArtifactError) as caught:
        ReportManager.export_document_pdf(snapshot.markdown, str(tmp_path), str(tmp_path / "r.pdf"),
            snapshot=snapshot, source_path=args["source_path"])
    assert caught.value.code == "stale_artifact"
    assert renderer == []


@pytest.mark.parametrize("reference", [
    '![产能](charts/capacity.png "Capacity title")',
    '![产能][capacity]\n\n[capacity]: charts/capacity.png "Capacity title"',
])
def test_figure_inventory_resolves_reference_images_and_titles(tmp_path, reference):
    (tmp_path / "charts").mkdir()
    figure = tmp_path / "charts" / "capacity.png"
    figure.write_bytes(b"figure")
    args = _publication(tmp_path, markdown="# 报告\n\n" + reference + "\n")
    snapshot = artifacts.publish_generation(**args)
    assert json.loads(snapshot.assets["figures.json"]) == {"charts/capacity.png": artifacts.file_digest(figure)}
    figure.write_bytes(b"new figure")
    with pytest.raises(artifacts.ArtifactError) as caught:
        _resolve(args)
    assert caught.value.code == "stale_artifact"
    figure.unlink()
    with pytest.raises(artifacts.ArtifactError) as missing:
        _resolve(args)
    assert missing.value.code == "stale_artifact" and missing.value.status_code == 409


def test_first_mermaid_export_stages_derived_assets_without_source_drift(tmp_path, monkeypatch, renderer):
    source = tmp_path / "source.md"
    source.write_text("# Diagram\n\n```mermaid\ngraph TD\n A-->B\n```\n")
    staging_roots = []
    def prepare(md, folder):
        staging_roots.append(folder)
        charts = Path(folder) / "charts"
        charts.mkdir()
        (charts / "derived.mmd").write_text("graph TD\n A-->B")
        (charts / "derived.png").write_bytes(b"derived fixture")
        return md.replace("```mermaid\ngraph TD\n A-->B\n```", "![](" + str(charts / "derived.png") + ")")
    monkeypatch.setattr(ReportManager, "_prerender_mermaid_for_pdf", staticmethod(prepare))
    result = ReportManager.export_document_pdf(source.read_text(), str(tmp_path), str(tmp_path / "r.pdf"),
                                               source_path=str(source))
    assert result and Path(result).exists()
    assert not (tmp_path / "charts").exists()
    assert len(staging_roots) == 1 and not Path(staging_roots[0]).exists()
    assert ReportManager.export_document_pdf(source.read_text(), str(tmp_path), str(tmp_path / "r.pdf"),
                                               source_path=str(source)) == result
    assert len(staging_roots) == 1  # cached generation needs no derived preprocessing


@pytest.fixture
def renderer(monkeypatch):
    calls = []
    def render(cls, label, md, folder, path):
        calls.append(md)
        Path(path).write_bytes(b"%PDF-1.4\n" + md.encode())
        return True
    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(render))
    monkeypatch.setattr(ReportManager, "_pdf_renderer_fingerprint", classmethod(lambda cls: {"fixture": 1}))
    monkeypatch.setattr(ReportManager, "_prerender_mermaid_for_pdf", staticmethod(lambda md, folder: md))
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", staticmethod(lambda path, md:
                        (True, {"page_count": 1, "issues": []})))
    return calls


def test_pdf_snapshot_cache_and_failed_refresh_preserve_previous_bytes(tmp_path, monkeypatch, renderer):
    args = _publication(tmp_path)
    snap = artifacts.publish_generation(**args)
    requested = str(tmp_path / "report.zh.pdf")
    export = lambda: ReportManager.export_document_pdf(snap.markdown, str(tmp_path), requested,
        source_path=args["source_path"], snapshot=snap)
    first = export()
    assert first and first == export() and len(renderer) == 1
    previous = Path(first).read_bytes()
    manifest = (tmp_path / "report.zh.pdf.manifest.json").read_bytes()
    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(lambda *a: False))
    monkeypatch.setattr(ReportManager, "_export_pdf_pymupdf", classmethod(lambda *a: False))
    assert ReportManager.export_document_pdf(snap.markdown, str(tmp_path), requested,
        source_path=args["source_path"], snapshot=snap, force=True) is None
    assert Path(first).read_bytes() == previous
    assert (tmp_path / "report.zh.pdf.manifest.json").read_bytes() == manifest


def test_pdf_source_drift_returns409_without_cache_commit(tmp_path, monkeypatch, renderer):
    args = _publication(tmp_path)
    snap = artifacts.publish_generation(**args)
    def render(cls, label, md, folder, path):
        assert md == snap.markdown
        Path(path).write_bytes(b"%PDF-1.4 fixture")
        Path(args["source_path"]).write_text("# Changed source\n")
        return True
    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(render))
    with pytest.raises(artifacts.ArtifactError) as caught:
        ReportManager.export_document_pdf(snap.markdown, str(tmp_path), str(tmp_path / "report.pdf"),
            source_path=args["source_path"], snapshot=snap)
    assert caught.value.code == "stale_artifact" and caught.value.status_code == 409
    assert not (tmp_path / "report.pdf.manifest.json").exists()


def test_pdf_concurrent_export_gets_typed_conflict(tmp_path, monkeypatch, renderer):
    entered, release = threading.Event(), threading.Event()
    output, errors = [], []
    def render(cls, label, md, folder, path):
        entered.set()
        assert release.wait(5)
        Path(path).write_bytes(b"%PDF-1.4 fixture")
        return True
    monkeypatch.setattr(ReportManager, "_export_pdf_pandoc", classmethod(render))
    def export():
        try:
            output.append(ReportManager.export_document_pdf("# Fixture", str(tmp_path), str(tmp_path / "r.pdf")))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=export)
    thread.start()
    try:
        assert entered.wait(5)
        with pytest.raises(artifacts.ArtifactError) as caught:
            ReportManager.export_document_pdf("# Fixture", str(tmp_path), str(tmp_path / "r.pdf"))
        assert caught.value.code == "artifact_busy" and caught.value.status_code == 409
    finally:
        release.set()
        thread.join(5)
    assert not errors and len(output) == 1


@pytest.mark.parametrize("lang", ["en", "zh"])
def test_real_guarded_pdf_exact_language_figures_symbols_and_pagination(tmp_path, monkeypatch, lang):
    """Real installed PyMuPDF output; no native renderer subprocess is launched.

    Rich tables/footnotes require Pandoc and remain a separately documented gate.
    This checks the real simple-document fallback and its full content validator.
    """
    fitz = pytest.importorskip("fitz")
    monkeypatch.setattr(ReportManager, "_resolve_pandoc", classmethod(lambda cls: (None, None)))
    monkeypatch.setattr(ReportManager, "_pdf_renderer_fingerprint",
                        classmethod(lambda cls: {"renderer": "pymupdf", "version": fitz.VersionBind}))
    charts = tmp_path / "charts"
    charts.mkdir()
    chart = fitz.open()
    page = chart.new_page(width=300, height=120)
    page.draw_rect(fitz.Rect(30, 20, 90, 110), color=(0, .3, .6), fill=(0, .3, .6))
    page.draw_rect(fitz.Rect(120, 50, 180, 110), color=(.1, .6, .3), fill=(.1, .6, .3))
    page.get_pixmap().save(str(charts / "fixture.png"))
    chart.close()
    heading = "Demand forecast" if lang == "en" else "需求预测报告"
    paragraph = ("The scenario projects demand between 10% and 20%, with uncertainty ± 2%. "
                 "The measured range is ≥ 10 and ≤ 20. Source [S1]." if lang == "en" else
                 "该情景预计需求增长介于10%和20%之间，不确定性为± 2%。测量范围为≥ 10和≤ 20。来源[S1]。")
    md = "# " + heading + "\n\n![" + heading + "](charts/fixture.png)\n\n"
    md += "\n\n".join(f"## {heading} {i}\n\n{paragraph}" for i in range(30)) + "\n"
    source = tmp_path / (lang + ".md")
    source.write_text(md)
    output = ReportManager.export_document_pdf(md, str(tmp_path), str(tmp_path / (lang + ".pdf")),
                                               source_path=str(source), label="guarded-fixture-" + lang)
    assert output
    with fitz.open(output) as document:
        assert document.page_count >= 2
        assert sum(len(page.get_images()) for page in document) >= 1
        text = "".join(page.get_text() for page in document)
        assert heading in text and "\ufffd" not in text
        for glyph in "≥≤±":
            assert glyph in text
        document[0].get_pixmap(matrix=fitz.Matrix(1, 1)).save(str(tmp_path / (lang + "-page1.png")))
    assert ReportManager._validate_pdf_content(output, md)[0]
