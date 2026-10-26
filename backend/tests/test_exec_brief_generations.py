"""Generation-bound executive brief consumers; model transport is scripted only."""
import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from app.config import Config
from app.services.exec_brief import ExecBriefBuilder
from app.services.report_agent import ReportManager
from app.services.translation import scheduler
from app.services.translation.artifacts import ArtifactError
from test_forecast_feedback_sdk import published
from test_model_translation_workflow import ScriptedModel
from test_exec_brief import _make_report_dir, _forecast_fixture, _write_passing_audit


@pytest.fixture
def admitted(published, tmp_path, monkeypatch):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "translation-store"))
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", True)
    monkeypatch.setattr(Config, "REPORT_EXEC_BRIEF", True)
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True)
    rid, folder = published["report"].report_id, published["folder"]
    source = {name: (folder / name).read_bytes() for name in (
        "full_report.md", "forecast.json", "final_audit.json", "citations.json")}
    model = ScriptedModel()
    generate = ReportManager.generate_translation_variant
    result = generate(rid, "zh", llm_client=model)
    assert result["available"], result
    snapshot = ReportManager.resolve_translation(rid, "zh")
    assert snapshot and not (folder / "full_report.zh.md").exists()
    # Old named briefs must never shadow a newly admitted generation or be overwritten.
    old = {name: b"retained legacy brief" for name in ("exec_brief.zh.md", "exec_brief.zh.pdf")}
    for name, data in old.items():
        (folder / name).write_bytes(data)
    def forbidden(*args, **kwargs):
        raise AssertionError("executive brief reads must not start model/provider/translation work")
    monkeypatch.setattr("app.utils.llm_client.LLMClient", forbidden)
    monkeypatch.setattr(ReportManager, "generate_translation_variant", forbidden)
    monkeypatch.setattr(scheduler, "submit", forbidden)
    monkeypatch.setattr(scheduler, "start_scheduler", forbidden)
    # Renderer behavior is isolated in route/cache tests; native rendering is
    # covered by the parent-owned verifier, not claimed by these synthetic bytes.
    monkeypatch.setattr(ReportManager, "_pdf_renderer_fingerprint", lambda: {"renderer": "fixture"})
    guard = sys.modules.get("main_offline_guard")
    if guard:
        from app.api import report as api
        from app.services import exec_brief
        for name in (api.__file__, exec_brief.__file__):
            guard.source_hashes[name] = hashlib.sha256(Path(name).read_bytes()).hexdigest()
    return {**published, "rid": rid, "snapshot": snapshot, "source": source,
            "old": old, "generate": generate, "model": model}


def _preserved(case):
    folder = case["folder"]
    assert all((folder / name).read_bytes() == data for name, data in case["old"].items())
    assert all((folder / name).read_bytes() == data for name, data in case["source"].items())


def test_new_generation_brief_and_public_read_use_admitted_markdown_and_forecast(admitted, monkeypatch):
    case = admitted
    rid, folder = case["rid"], case["folder"]
    seen = []
    original = ReportManager.load_localized_forecast
    def record(rid, lang, *, snapshot=None):
        seen.append(snapshot)
        return original(rid, lang, snapshot=snapshot)
    monkeypatch.setattr(ReportManager, "load_localized_forecast", record)
    before = len(case["model"].trace)
    result = ExecBriefBuilder.build(rid, str(folder), lang="zh")
    path = Path(result["exec_brief.zh"])
    brief = path.read_text()
    assert path != folder / "exec_brief.zh.md"
    assert "高管简报" in brief and "委员会可能批准该提案" in brief
    assert brief.splitlines()[0] == "# 高管简报 — 委员会展望"
    assert "**预测问题:** 委员会展望" in brief
    assert "基准情景" in brief and "70%" in brief
    assert seen and all(s and s.generation == case["snapshot"].generation for s in seen)
    response = case["client"].get(f"/api/report/{rid}/exec-brief?lang=zh")
    assert response.status_code == 200, response.json
    assert response.get_data(as_text=True) == brief
    assert len(case["model"].trace) == before
    assert case["client"].get(f"/api/report/{rid}/exec-brief?lang=zh&generation_id=old").status_code == 409
    _preserved(case)


def test_translated_brief_title_and_question_use_sealed_display_without_model_work(admitted):
    c = admitted
    before = len(c["model"].trace)
    ReportManager.refresh_translation_assets(c["rid"], "zh", {
        "display.json": {"title": "委员会决策摘要"}})
    response = c["client"].get(f"/api/report/{c['rid']}/exec-brief?lang=zh")
    assert response.status_code == 200, response.json
    text = response.get_data(as_text=True)
    assert text.splitlines()[0] == "# 高管简报 — 委员会决策摘要"
    assert "**预测问题:** 委员会决策摘要" in text
    assert "**预测问题:** Committee" not in text
    assert len(c["model"].trace) == before
    _preserved(c)


def test_generation_change_gets_new_derived_path_without_changing_previous_brief(admitted):
    c = admitted
    first = Path(ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"])
    before = first.read_bytes()
    newer = ReportManager.refresh_translation_assets(c["rid"], "zh", {"brief-test.json": {"revision": 2}})
    assert newer.generation != c["snapshot"].generation
    second = Path(ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"])
    assert first != second and first.read_bytes() == before
    assert second.read_bytes() == before
    _preserved(c)


def test_failed_translation_refresh_keeps_accepted_brief_readable(admitted):
    c = admitted
    first = Path(ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"])
    before = first.read_bytes()
    refused = ScriptedModel(mutate=lambda source, target, repair: target + " invented 9999 MW")
    result = c["generate"](c["rid"], "zh", llm_client=refused, force=True)
    assert not result.get("updated", True), result
    assert ReportManager.resolve_translation(c["rid"], "zh").generation == c["snapshot"].generation
    response = c["client"].get(f"/api/report/{c['rid']}/exec-brief?lang=zh")
    assert response.status_code == 200 and response.data == before
    assert first.read_bytes() == before
    _preserved(c)


@pytest.mark.parametrize("removed", ["generation", "pointer", "source"])
def test_missing_or_stale_generation_never_serves_old_brief(admitted, removed):
    c = admitted
    old = Path(ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"])
    before = old.read_bytes()
    if removed == "generation":
        (Path(c["snapshot"].path) / "document.md").unlink()
    elif removed == "pointer":
        (Path(c["snapshot"].path).parent.parent / "current.json").unlink()
    else:
        (c["folder"] / "full_report.md").write_text("# Changed canonical source\n")
    for suffix in ("exec-brief", "exec-brief.pdf"):
        response = c["client"].get(f"/api/report/{c['rid']}/{suffix}?lang=zh")
        assert response.status_code in {404, 409}, response.json
        assert response.data != before
    assert old.read_bytes() == before
    assert all((c["folder"] / name).read_bytes() == data for name, data in c["old"].items())


def test_render_time_source_drift_is_typed_and_does_not_replace_existing_brief(admitted, monkeypatch):
    c = admitted
    old = Path(ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"])
    before = old.read_bytes()
    render = ExecBriefBuilder._render_brief
    def drift(*args, **kwargs):
        text = render(*args, **kwargs)
        (c["folder"] / "full_report.md").write_text("# Changed during extraction\n")
        return text
    monkeypatch.setattr(ExecBriefBuilder, "_render_brief", drift)
    response = c["client"].get(f"/api/report/{c['rid']}/exec-brief?lang=zh")
    assert response.status_code == 409, response.json
    assert old.read_bytes() == before


def test_generation_pdf_cache_and_failed_new_render_preserve_previous_pdf(admitted, monkeypatch):
    c = admitted
    calls = []
    def render(rid, md, folder, path):
        calls.append(md)
        Path(path).write_bytes(b"%PDF-1.4\nsynthetic brief rendering\n%%EOF")
        return True
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", render)
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", lambda *a: (True, {}))
    path = ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh")
    assert path and Path(path).is_file()
    assert "委员会可能批准该提案" in calls[0]
    first = Path(path).read_bytes()
    assert ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh") == path
    response = c["client"].get(f"/api/report/{c['rid']}/exec-brief.pdf?lang=zh")
    assert response.status_code == 200 and response.data == first
    assert len(calls) == 1
    ReportManager.refresh_translation_assets(c["rid"], "zh", {"brief-test.json": {"revision": 2}})
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", lambda *a: False)
    monkeypatch.setattr(ReportManager, "_export_pdf_pymupdf", lambda *a: False)
    assert ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh") is None
    assert c["client"].get(f"/api/report/{c['rid']}/exec-brief.pdf?lang=zh").status_code == 404
    assert Path(path).read_bytes() == first
    _preserved(c)


def test_primary_content_change_with_unchanged_mtime_invalidates_brief(tmp_path, monkeypatch):
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    rid, folder = _make_report_dir(str(tmp_path), forecast=_forecast_fixture())
    result = ExecBriefBuilder.build(rid, folder)
    before = Path(result["exec_brief"]).read_text()
    source = Path(folder) / "full_report.md"
    stamp = source.stat()
    changed = source.read_text().replace("four-scenario spine", "changed scenario foundation")
    source.write_text(changed)
    os.utime(source, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    _write_passing_audit(rid, changed)
    result = ExecBriefBuilder.build(rid, folder)
    after = Path(result["exec_brief"]).read_text()
    assert after != before and "changed scenario foundation" in after


def test_real_pymupdf_brief_fallback_keeps_report_chart(admitted, monkeypatch):
    import pymupdf as fitz
    c = admitted
    chart = c["folder"] / "charts" / "scenario_probabilities.png"
    chart.parent.mkdir(exist_ok=True)
    with fitz.open() as image_source:
        page = image_source.new_page(width=240, height=120)
        page.draw_rect(fitz.Rect(20, 30, 90, 110), color=(0, 0, 1), fill=(0, 0, 1))
        page.draw_rect(fitz.Rect(130, 70, 200, 110), color=(1, 0, 0), fill=(1, 0, 0))
        page.get_pixmap().save(str(chart))
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", lambda *a: False)
    actual_fallback = ReportManager._export_pdf_pymupdf
    seen = []
    audits = []
    validate = ReportManager._validate_pdf_content
    def record_validation(path, md):
        result = validate(path, md)
        audits.append(result)
        return result
    monkeypatch.setattr(ReportManager, "_validate_pdf_content", record_validation)
    def fallback(md, archive, output):
        seen.append((archive, output))
        return actual_fallback(md, archive, output)
    monkeypatch.setattr(ReportManager, "_export_pdf_pymupdf", fallback)
    path = ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh")
    assert path is not None, audits
    assert seen[0][0] == str(c["folder"])
    assert Path(seen[0][1]).parent.name.startswith(".exec-brief-stage-")
    with fitz.open(path) as pdf:
        images = [image for page in pdf for image in page.get_images(full=True)]
        assert any(image[2:4] == (240, 120) for image in images)
        assert all(pdf.extract_image(image[0])["image"] for image in images)
    _preserved(c)


def test_snapshot_capture_and_delivery_reject_revoked_publication_policy(admitted, monkeypatch):
    c = admitted
    path = ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"]
    original = Path(path).read_bytes()
    monkeypatch.setattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION",
                        int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION) + 1)
    assert not ReportManager.is_publishable(c["rid"], "zh")
    assert ReportManager.resolve_translation(c["rid"], "zh").generation == c["snapshot"].generation
    with pytest.raises(ArtifactError, match="publication"):
        ExecBriefBuilder._capture(c["rid"], str(c["folder"]), "zh")
    with pytest.raises(ArtifactError, match="publication"):
        ExecBriefBuilder.assert_current(c["rid"], str(c["folder"]), path, "zh")
    assert Path(path).read_bytes() == original
    _preserved(c)


@pytest.mark.parametrize("suffix", ["exec-brief", "exec-brief.pdf"])
def test_policy_change_after_route_precheck_cannot_serve_cached_brief(admitted, monkeypatch, suffix):
    c = admitted
    path = ExecBriefBuilder.build(c["rid"], str(c["folder"]), lang="zh")["exec_brief.zh"]
    original = Path(path).read_bytes()
    capture = ExecBriefBuilder._capture
    changed = []
    def after_precheck(*args, **kwargs):
        if not changed:
            changed.append(True)
            monkeypatch.setattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION",
                                int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION) + 1)
        return capture(*args, **kwargs)
    monkeypatch.setattr(ExecBriefBuilder, "_capture", after_precheck)
    response = c["client"].get(f"/api/report/{c['rid']}/{suffix}?lang=zh")
    assert changed and response.status_code == 409, response.json
    assert response.json["code"] == "stale_artifact"
    assert Path(path).read_bytes() == original
    _preserved(c)


def test_digest_failed_replacement_does_not_serve_previous_file(admitted, monkeypatch):
    from app.services import exec_brief as module
    c = admitted
    produced = ExecBriefBuilder.build(c["rid"], str(c["folder"]))
    path = Path(produced["digest"])
    before = path.read_bytes()
    render = ExecBriefBuilder._render_digest
    writer = module._write_text_atomic
    monkeypatch.setattr(ExecBriefBuilder, "_render_digest", lambda *a, **kw: render(*a, **kw) + "\nReplacement summary.\n")
    attempted = []
    def fail_digest(output, text):
        if Path(output).name == "digest.md":
            attempted.append(True)
            return False
        return writer(output, text)
    monkeypatch.setattr(module, "_write_text_atomic", fail_digest)
    response = c["client"].get(f"/api/report/{c['rid']}/digest")
    assert attempted and response.status_code == 404, response.get_data(as_text=True)
    assert path.read_bytes() == before
    _preserved(c)


@pytest.mark.parametrize("changed", ["source", "policy", "output"])
def test_digest_rechecks_capture_output_and_publication_before_delivery(admitted, monkeypatch, changed):
    c = admitted
    build = ExecBriefBuilder.build
    def after_build(*args, **kwargs):
        produced = build(*args, **kwargs)
        if changed == "policy":
            monkeypatch.setattr(Config, "REPORT_FINAL_AUDIT_POLICY_VERSION",
                                int(Config.REPORT_FINAL_AUDIT_POLICY_VERSION) + 1)
        elif changed == "source":
            with (c["folder"] / "full_report.md").open("a") as handle:
                handle.write("\nAdditional canonical source outside digest selection.\n")
        else:
            Path(produced["digest"]).write_text("Replaced digest after successful build")
        return produced
    monkeypatch.setattr(ExecBriefBuilder, "build", after_build)
    response = c["client"].get(f"/api/report/{c['rid']}/digest")
    assert response.status_code == 409, response.get_data(as_text=True)
    assert response.json["code"] == "stale_artifact"


@pytest.mark.parametrize("broken", ["malformed", "content_loss"])
def test_pdf_content_gate_rejects_bad_output_and_preserves_prior_cache(admitted, monkeypatch, broken):
    import pymupdf as fitz
    c = admitted
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", lambda *a: False)
    original = ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh")
    assert original
    before = Path(original).read_bytes()
    pointer = Path(original).parent.parent / "pdf.json"
    original_pointer = pointer.read_bytes()
    def corrupt(rid, md, folder, path):
        if broken == "malformed":
            Path(path).write_bytes(b"%PDF-1.4\nNot a parseable document\n")
        else:
            with fitz.open() as document:
                page = document.new_page()
                page.insert_text((72, 72), "Unrelated output with missing report content")
                document.save(path)
        return True
    monkeypatch.setattr(ExecBriefBuilder, "_export_pdf_pandoc_no_toc", corrupt)
    assert ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh", force=True) is None
    assert Path(original).read_bytes() == before
    assert pointer.read_bytes() == original_pointer
    assert ExecBriefBuilder.build_pdf(c["rid"], str(c["folder"]), lang="zh") == original
    _preserved(c)


@pytest.mark.parametrize("suffix,key", [("exec-brief", "exec_brief"), ("digest", "digest")])
def test_markdown_delivery_uses_verified_bytes_after_legacy_path_replacement(admitted, monkeypatch, suffix, key):
    from app.api import report as api
    c = admitted
    produced = ExecBriefBuilder.build(c["rid"], str(c["folder"]))
    path = Path(produced[key])
    expected = path.read_bytes()
    replaced = []
    response_type, send_file = api.Response, api.send_file
    def replace_path():
        replaced.append(True)
        path.write_bytes(b"Another generation replaced the mutable path at send time")
    def snapshot_response(*args, **kwargs):
        replace_path()
        return response_type(*args, **kwargs)
    def reopening_response(*args, **kwargs):
        replace_path()
        return send_file(*args, **kwargs)
    monkeypatch.setattr(api, "Response", snapshot_response)
    monkeypatch.setattr(api, "send_file", reopening_response)
    response = c["client"].get(f"/api/report/{c['rid']}/{suffix}")
    assert replaced and path.read_bytes() != expected
    assert response.status_code == 200 and response.data == expected
    assert "attachment" in response.headers["Content-Disposition"]
    _preserved(c)
