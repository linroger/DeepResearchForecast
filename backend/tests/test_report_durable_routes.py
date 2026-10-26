"""Report facade scenarios against the real durable store, with dispatch paused.

Run only with the repository's guarded runner. Report/domain producers are small
synthetic substitutes; no provider or production report is accessed.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from flask import Flask

from app.api import report as api
from app.api.translations import translations_bp
from app.config import Config
from app.services.report_agent import ReportManager
from app.services.translation import scheduler
from app.services.translation.artifacts import ArtifactError
from app.services.translation.contracts import safe_error
from app.services.translation.store import Store, database_path


def queue_only_scheduler(monkeypatch, root):
    """Keep real submit/status/retry persistence; prevent background dispatch."""
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(root))
    monkeypatch.setattr(scheduler, "start_scheduler", lambda: None)
    api.register_translation_handler()


def run_queued_report():
    """Exercise the registered production handler under a real durable claim."""
    with Store(database_path()) as store:
        epoch = store.elect()
        job_id, kind, payload = store.claim_task(epoch, {api._REPORT_TRANSLATION_KIND})
        token = scheduler._task_id.set(job_id)
        epoch_token = scheduler._task_epoch.set(epoch)
        try:
            result = scheduler._handlers[kind](payload)
        except Exception as exc:
            store.finish_task(job_id, epoch, error=safe_error(exc, "operation"))
        else:
            store.finish_task(job_id, epoch, result=result)
        finally:
            scheduler._task_id.reset(token)
            scheduler._task_epoch.reset(epoch_token)
        return store.task(job_id)


@pytest.fixture
def route_case(tmp_path, monkeypatch):
    queue_only_scheduler(monkeypatch, tmp_path)
    root = tmp_path / "reports"
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(root))
    folder = root / "report_route"
    folder.mkdir(parents=True)
    for name, text in {"full_report.md": "# Forecast\n\nSource claim.\n",
                       "forecast.json": '{"headline":"Source forecast"}',
                       "final_audit.json": '{"hard_passed":true}',
                       "citations.json": '{}', "full_report.zh.md": "accepted old body"}.items():
        (folder / name).write_text(text)
    report = SimpleNamespace(report_id="report_route", markdown_content=(folder / "full_report.md").read_text(),
                             simulation_id="sim_route", graph_id="graph_route")
    env = SimpleNamespace(report=report, folder=folder, body=False, complete=False,
                          publishable=True, generation="generation_1", calls=[], repair_succeeds=True)
    monkeypatch.setattr(ReportManager, "get_report", lambda rid: report if rid == report.report_id else None)
    monkeypatch.setattr(ReportManager, "load_world_result", lambda rid: None)
    monkeypatch.setattr(ReportManager, "load_report_news_market_context", lambda rid: None)
    monkeypatch.setattr(ReportManager, "is_publishable", lambda rid, lang=None: env.publishable and (lang is None or env.body))

    def publication(rid, lang=None):
        return {"publishable": env.publishable and (lang is None or env.body),
                "generation_id": env.generation if lang else None,
                "markdown_sha256": hashlib.sha256(("# 不可变译文\n" if lang else report.markdown_content).encode()).hexdigest(),
                "source_markdown_sha256": hashlib.sha256(report.markdown_content.encode()).hexdigest(),
                "reasons": []}
    monkeypatch.setattr(ReportManager, "publication_status", publication)

    def state(rid, lang=None, report=None):
        return {"report_id": rid, "requested_lang": lang, "source_lang": "en", "target_lang": "zh",
                "available": env.body, "status": "available" if env.body else "missing",
                "can_generate": env.publishable, "partial": False, "issues": []}
    monkeypatch.setattr(ReportManager, "translation_status", state)

    def structured(report, lang, **kwargs):
        fingerprint = hashlib.sha256((folder / "forecast.json").read_bytes()).hexdigest()
        detail = {"complete": env.complete, "partial": not env.complete,
                  "status": "available" if env.complete else "partial", "pending": int(not env.complete),
                  "retryable": not env.complete, "issues": [], "source_fingerprint": fingerprint,
                  "coverage": {"complete": env.complete, "translated": int(env.complete), "total": 1}}
        return {"structured_translation": detail, "translation_status": detail,
                "display": {"title": "标题", "translation_status": detail}}
    monkeypatch.setattr(api, "_report_structured", structured)

    def generate(rid, lang, *, force=False):
        env.calls.append(("body", force))
        env.body = True
        env.generation = "replacement_body"
        return {"available": True, "updated": True}
    monkeypatch.setattr(ReportManager, "generate_translation_variant", generate)

    def repair(report, lang, force=False, *, expected_identity):
        env.calls.append(("structured", force))
        env.complete = env.repair_succeeds
    monkeypatch.setattr(api, "_repair_report_structured", repair)

    def refresh(rid, lang, assets):
        env.calls.append(("assets", json.loads(assets["display.json"])))
        env.generation = "generation_2"
        return SimpleNamespace(generation=env.generation)
    monkeypatch.setattr(ReportManager, "refresh_translation_assets", refresh)

    def forbidden(*args, **kwargs):
        raise AssertionError("route must not acquire legacy tasks, leases, or providers")
    monkeypatch.setattr(api, "TaskManager", forbidden)
    monkeypatch.setattr(ReportManager, "_translation_generation_lease", forbidden)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", forbidden)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    app.register_blueprint(translations_bp, url_prefix="/api/translations")
    env.client = app.test_client()
    env.url = "/api/report/report_route/translations/zh"
    guard = __import__("sys").modules.get("main_offline_guard")
    if guard:
        source = Path(api.__file__)
        guard.source_hashes[str(source)] = hashlib.sha256(source.read_bytes()).hexdigest()
    return env


def test_duplicate_start_and_reload_use_persisted_scheduler_not_task_manager(route_case):
    c = route_case
    first = c.client.post(c.url)
    assert first.status_code == 202, first.json
    data = first.json["data"]
    assert data["status"] == "pending"
    assert data["translation_job"]["identity"]["scope"] == "body"
    for response in (c.client.post(c.url), c.client.get(c.url + "/status")):
        assert response.json["data"]["task_id"] == data["task_id"]
        assert response.json["data"]["translation_job"]["job_state"] == "queued"
    with Store(database_path(), read_only=True) as store:
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    assert c.calls == []


def test_named_handler_completes_body_then_structured_then_seals_assets(route_case):
    c = route_case
    first = c.client.post(c.url).json["data"]
    job = run_queued_report()
    assert job["job_state"] == "completed", job
    assert [call[0] for call in c.calls] == ["body", "structured", "assets"]
    polled = c.client.get(c.url + "/status?task_id=" + first["task_id"])
    assert polled.json["data"]["status"] == "completed"
    assert polled.json["data"]["available"]
    assert polled.json["data"]["structured_translation"]["complete"]


def test_structured_retry_preserves_body_and_reuses_failed_operation(route_case):
    c = route_case
    c.body, c.repair_succeeds = True, False
    original = (c.folder / "full_report.zh.md").read_bytes()
    first = c.client.post(c.url)
    assert first.status_code == 200 and first.json["data"]["available"]
    job_id = first.json["data"]["task_id"]
    assert first.json["data"]["translation_job"]["identity"]["scope"] == "structured"
    failed = run_queued_report()
    assert failed["job_state"] == "failed"
    assert failed["error"]["code"] == "translation_structured_incomplete"
    assert c.client.get(c.url + "/status").json["data"]["available"]
    c.repair_succeeds = True
    resumed = c.client.post(c.url)
    assert resumed.json["data"]["task_id"] == job_id
    assert run_queued_report()["job_state"] == "completed"
    assert not any(call[0] == "body" for call in c.calls)
    assert (c.folder / "full_report.zh.md").read_bytes() == original
    assert c.calls[-1][0] == "assets"


def test_force_refresh_keeps_published_body_available_but_task_not_done(route_case):
    c = route_case
    c.body = c.complete = True
    assert c.client.post(c.url).status_code == 200
    assert c.calls == []
    response = c.client.post(c.url + "?force=1")
    assert response.status_code == 202
    assert response.json["data"]["available"] is False
    assert response.json["data"]["published_available"] is True
    run_queued_report()
    assert c.calls[0] == ("body", True)


@pytest.mark.parametrize("change", ["body", "file", "structured"])
def test_source_drift_rejects_task_lookup_retry_and_dispatch(route_case, change):
    c = route_case
    job_id = c.client.post(c.url).json["data"]["task_id"]
    if change == "body":
        c.report.markdown_content += "Updated claim"
    elif change == "file":
        (c.folder / "full_report.md").write_text("Different on-disk source")
    else:
        (c.folder / "forecast.json").write_text('{"headline":"Changed forecast"}')
    for response in (c.client.get(c.url + "/status?task_id=" + job_id),
                     c.client.post(c.url + "?task_id=" + job_id)):
        assert response.status_code == 409
        assert response.json["code"] == "translation_source_changed"
    job = run_queued_report()
    assert job["job_state"] == "failed" and job["error"]["code"] == "translation_source_changed"
    assert c.calls == []


@pytest.mark.parametrize("key,value", [("ref_id", "report_elsewhere"), ("target_lang", "en"), ("scope", "private")])
def test_foreign_job_identity_is_rejected_without_disclosing_result(route_case, key, value):
    c = route_case
    identity = api._report_translation_identity(c.report, "zh", "body")
    identity[key] = value
    job = scheduler.submit(api._REPORT_TRANSLATION_KIND, identity, {"secret": "must not disclose"})
    for response in (c.client.get(c.url + "/status?task_id=" + job["job_id"]),
                     c.client.post(c.url + "?task_id=" + job["job_id"])):
        assert response.status_code == 409
        assert response.json["code"] == "translation_job_mismatch"
        assert "secret" not in response.get_data(as_text=True)


def test_unknown_task_and_invalid_resources_fail_closed(route_case):
    c = route_case
    assert c.client.get(c.url + "/status?task_id=missing").status_code == 404
    assert c.client.post("/api/report/no_report/translations/zh").status_code == 404
    assert c.client.post("/api/report/report_route/translations/fr").status_code == 400
    assert c.client.post("/api/report/%2E%2E/translations/zh").status_code == 400
    assert c.client.get("/api/report/bad%5Cpath/translations/zh/status").status_code == 400
    assert c.calls == []


def test_reads_never_resume_interrupted_work(route_case):
    c = route_case
    job_id = c.client.post(c.url).json["data"]["task_id"]
    with Store(database_path()) as store:
        epoch = store.elect()
        store.claim_task(epoch, {api._REPORT_TRANSLATION_KIND})
        store.elect()  # Model a coordinator restart; the old claim is interrupted.
    for _ in range(2):
        data = c.client.get(c.url + "/status").json["data"]
        assert data["translation_job"]["job_state"] == "interrupted"
    assert c.calls == []
    response = c.client.post(c.url)
    assert response.json["data"]["task_id"] == job_id
    assert response.json["data"]["translation_job"]["job_state"] == "queued"


def test_legacy_runtime_state_cannot_assert_active_ownership(route_case, monkeypatch):
    c = route_case
    old = ReportManager.translation_status
    monkeypatch.setattr(ReportManager, "translation_status", lambda *a, **kw: {
        **old(*a, **kw), "status": "generating", "task_id": "retired-memory-task"})
    data = c.client.get(c.url + "/status").json["data"]
    assert data["status"] == "interrupted" and data["task_id"] is None
    assert c.client.post(c.url).status_code == 202


def test_scheduler_unavailable_is_safe_service_error_and_no_fallback_worker(route_case, monkeypatch):
    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("sensitive internal path")
    monkeypatch.setattr(scheduler, "submit", unavailable)
    response = route_case.client.post(route_case.url)
    assert response.status_code == 503
    assert response.json["code"] == "translation_service_unavailable"
    assert "sensitive" not in response.get_data(as_text=True)
    assert route_case.calls == []


@pytest.mark.parametrize("code", ["stale_artifact", "artifact_busy"])
@pytest.mark.parametrize("route", ["status", "pdf", "markdown"])
def test_typed_artifact_errors_remain_409(route_case, monkeypatch, code, route):
    c = route_case
    c.body = True
    def fail(*args, **kwargs):
        raise ArtifactError(code, "Reload or retry")
    if route == "status":
        monkeypatch.setattr(ReportManager, "translation_status", fail)
        url = c.url + "/status"
    elif route == "pdf":
        monkeypatch.setattr(ReportManager, "export_pdf", fail)
        url = "/api/report/report_route/pdf?lang=zh"
    else:
        monkeypatch.setattr(ReportManager, "resolve_translation", fail)
        url = "/api/report/report_route/full_report.zh.md"
    response = c.client.get(url)
    assert response.status_code == 409, response.json
    assert response.json["code"] == code
    assert c.calls == []


def test_markdown_serves_one_resolved_generation_and_never_reopens_sidecar(route_case, monkeypatch):
    c = route_case
    c.body = True
    monkeypatch.setattr(ReportManager, "resolve_translation", lambda *a: SimpleNamespace(
        markdown="# 不可变译文\n", generation="generation_1",
        source_sha256=hashlib.sha256(c.report.markdown_content.encode()).hexdigest()))
    def forbidden(*args, **kwargs):
        raise AssertionError("must not reopen a legacy or mutable Markdown path")
    monkeypatch.setattr(ReportManager, "read_translation_markdown", forbidden)
    monkeypatch.setattr(ReportManager, "_get_report_translation_path", forbidden)
    url = "/api/report/report_route/full_report.zh.md"
    response = c.client.get(url + "?generation_id=generation_1")
    assert response.status_code == 200
    assert response.mimetype == "text/markdown"
    assert "不可变译文" in response.get_data(as_text=True)
    assert c.client.get(url + "?generation_id=old").status_code == 409
    assert c.calls == []


def test_missing_legacy_markdown_is_404_and_does_not_generate(route_case, monkeypatch):
    monkeypatch.setattr(ReportManager, "resolve_translation", lambda *a: None)
    def missing(*args):
        raise FileNotFoundError("no legacy file")
    monkeypatch.setattr(ReportManager, "read_translation_markdown", missing)
    assert route_case.client.get("/api/report/report_route/full_report.zh.md").status_code == 404
    assert route_case.calls == []


def test_pdf_uses_immutable_cache_and_rejects_publication_drift(route_case, monkeypatch):
    c = route_case
    c.body = True
    cache = c.folder / "immutable.pdf"
    cache.write_bytes(b"%PDF-1.4\nfixture only\n%%EOF")
    monkeypatch.setattr(ReportManager, "export_pdf", lambda *a, **kw: str(cache))
    url = "/api/report/report_route/pdf?lang=zh"
    response = c.client.get(url + "&generation_id=generation_1")
    assert response.status_code == 200 and response.data == cache.read_bytes()
    assert response.mimetype == "application/pdf"
    assert "report_route.zh.pdf" in response.headers["Content-Disposition"]
    assert c.client.get(url + "&generation_id=old").status_code == 409
    def changed(*args, **kwargs):
        c.generation = "generation_2"
        return str(cache)
    monkeypatch.setattr(ReportManager, "export_pdf", changed)
    assert c.client.get(url).status_code == 409
    assert c.calls == []


def test_published_body_repairs_real_display_then_seals_and_consumes_generation(tmp_path, monkeypatch):
    """Real domain producers and immutable assets with a deterministic model stub."""
    from test_artifact_translation_routes import CombinedTranslator
    from test_report_bilingual import _publish_primary, _publish_variant
    queue_only_scheduler(monkeypatch, tmp_path)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    rid = "report_structured_generation"
    _publish_primary(rid, "# EV Forecast\n\nAn audited English forecast.\n")
    target = "# 电动车预测\n\n经过审核的预测正文。\n"
    path = Path(ReportManager._get_report_translation_path(rid, "zh"))
    path.write_text(target)
    _publish_variant(rid, "zh", target)
    report = ReportManager.get_report(rid)
    monkeypatch.setattr("app.utils.llm_client.LLMClient", CombinedTranslator)
    # The real display adapter has a translatable title; no canonical forecast
    # exists in this legacy fixture, which must remain an optional projection.
    before = {p.name: p.read_bytes() for p in path.parent.iterdir() if p.is_file()}
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    client = app.test_client()
    url = f"/api/report/{rid}/translations/zh"
    started = client.post(url)
    assert started.status_code == 200, started.json
    assert started.json["data"]["translation_job"]["identity"]["scope"] == "structured"
    def forbidden(*args, **kwargs):
        raise AssertionError("structured repair must not regenerate admitted Markdown")
    monkeypatch.setattr(ReportManager, "generate_translation_variant", forbidden)
    job = run_queued_report()
    assert job["job_state"] == "completed", job
    snapshot = ReportManager.resolve_translation(rid, "zh")
    assert snapshot.markdown == target
    assert json.loads(snapshot.assets["display.json"])["title"] != "EV Forecast"
    assert client.get(url + "/status").json["data"]["structured_translation"]["complete"]
    assert all((path.parent / name).read_bytes() == data for name, data in before.items())
    assert client.post(url).status_code == 200
    with Store(database_path(), read_only=True) as store:
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1

    # A newer mutable display cache cannot replace the selected body's assets.
    from app.services import artifact_translation
    raw_reader = artifact_translation.display_document
    def newer_candidate(*args, **kwargs):
        result = raw_reader(*args, **kwargs)
        result["display"]["title"] = "Newer mutable candidate"
        return result
    monkeypatch.setattr(artifact_translation, "display_document", newer_candidate)
    observed = []
    forecast_reader = ReportManager.load_localized_forecast
    def observe_forecast(*args, snapshot=None):
        observed.append(snapshot)
        return forecast_reader(*args, snapshot=snapshot)
    monkeypatch.setattr(ReportManager, "load_localized_forecast", observe_forecast)
    response = client.get(f"/api/report/{rid}/forecast?lang=zh")
    assert response.status_code == 200, response.json
    assert response.json["data"]["display"]["title"] == json.loads(snapshot.assets["display.json"])["title"]
    assert response.json["data"]["generation_id"] == snapshot.generation
    assert observed and all(item and item.generation == snapshot.generation for item in observed)
    public = client.get(url + "/status").json["data"]
    assert public["display"]["title"] == response.json["data"]["display"]["title"]
    assert api._report_structured(report, "zh")["display"]["title"] == "Newer mutable candidate"
    assert observed[-1] is None, "repair probes must continue to see current candidates"

    # Without a matching sealed display, disclose canonical fallback instead of
    # mixing the selected body with that newer mutable candidate.
    missing = SimpleNamespace(**{**snapshot.__dict__, "assets": {}})
    fallback = api._report_structured(report, "zh", snapshot=missing)
    assert fallback["display"]["title"] == "EV Forecast"
    assert not fallback["structured_translation"]["complete"]
    report.markdown_content = "# Changed canonical title\n\nChanged source.\n"
    changed = api._report_structured(report, "zh", snapshot=snapshot)
    assert changed["display"]["title"] == "Changed canonical title"
    assert not changed["structured_translation"]["complete"]


def test_disabled_translation_rejects_force_refresh(route_case, monkeypatch):
    route_case.body = route_case.complete = True
    monkeypatch.setattr(Config, "REPORT_BILINGUAL", False)
    assert route_case.client.post(route_case.url + "?force=1").status_code == 409
    assert route_case.calls == []


def test_retry_after_body_refresh_only_repairs_incomplete_structured_work(route_case):
    c = route_case
    c.body, c.complete, c.repair_succeeds = True, False, False
    first = c.client.post(c.url + "?force=1")
    job_id = first.json["data"]["task_id"]
    assert run_queued_report()["job_state"] == "failed"
    assert [call for call in c.calls if call[0] == "body"] == [("body", True)]
    c.repair_succeeds = True
    assert c.client.post(c.url).json["data"]["task_id"] == job_id
    assert run_queued_report()["job_state"] == "completed"
    assert [call for call in c.calls if call[0] == "body"] == [("body", True)]


@pytest.mark.parametrize("failure", ["none", "busy"])
def test_retry_completes_asset_publication_even_when_body_and_display_are_complete(route_case, monkeypatch, failure):
    c = route_case
    c.body = True
    original = ReportManager.refresh_translation_assets
    def interrupted(*args, **kwargs):
        if failure == "busy":
            raise ArtifactError("artifact_busy", "Another publisher owns the artifact")
        return None
    monkeypatch.setattr(ReportManager, "refresh_translation_assets", interrupted)
    job_id = c.client.post(c.url).json["data"]["task_id"]
    assert run_queued_report()["job_state"] == "failed"
    assert c.complete and c.body
    monkeypatch.setattr(ReportManager, "refresh_translation_assets", original)
    resumed = c.client.post(c.url + "?task_id=" + job_id)
    assert resumed.json["data"]["task_id"] == job_id
    assert resumed.json["data"]["translation_job"]["job_state"] == "queued"
    assert run_queued_report()["job_state"] == "completed"
    assert not any(call[0] == "body" for call in c.calls)


@pytest.mark.parametrize("change", ["generation", "source", "legacy_bytes"])
def test_markdown_rechecks_exact_publication_identity_before_delivery(route_case, monkeypatch, change):
    c = route_case
    c.body = True
    source_sha = hashlib.sha256(c.report.markdown_content.encode()).hexdigest()
    def resolve(*args):
        if change == "legacy_bytes":
            return None
        snapshot = SimpleNamespace(markdown="# 不可变译文\n", generation=c.generation, source_sha256=source_sha)
        if change == "generation":
            c.generation = "replacement"
        else:
            c.report.markdown_content = "changed source after snapshot"
        return snapshot
    monkeypatch.setattr(ReportManager, "resolve_translation", resolve)
    monkeypatch.setattr(ReportManager, "read_translation_markdown", lambda *a: "different legacy bytes")
    response = c.client.get("/api/report/report_route/full_report.zh.md")
    assert response.status_code == 409, response.json
    assert response.json["code"] == "stale_artifact"
    assert c.calls == []


def test_implicit_read_survives_store_outage_but_explicit_task_lookup_is_503(route_case, monkeypatch):
    c = route_case
    job_id = c.client.post(c.url).json["data"]["task_id"]
    c.body = c.complete = True
    snapshot = SimpleNamespace(generation=c.generation, assets={},
        source_sha256=hashlib.sha256(c.report.markdown_content.encode()).hexdigest())
    monkeypatch.setattr(ReportManager, "resolve_translation", lambda *a: snapshot)
    seen = []
    def forecast(*args, snapshot=None):
        seen.append(snapshot)
        return {"headline": "已发布预测"}, {"localized": True, "complete": True}
    monkeypatch.setattr(ReportManager, "load_localized_forecast", forecast)
    def unavailable(*args):
        raise sqlite3.OperationalError("private database path")
    monkeypatch.setattr(scheduler, "status", unavailable)
    status = c.client.get(c.url + "/status")
    assert status.status_code == 200 and status.json["data"]["available"]
    assert status.json["data"]["generation_id"] == c.generation
    forecast_response = c.client.get("/api/report/report_route/forecast?lang=zh")
    assert forecast_response.status_code == 200
    assert forecast_response.json["data"]["forecast"]["headline"] == "已发布预测"
    assert seen == [snapshot]
    explicit = c.client.get(c.url + "/status?task_id=" + job_id)
    assert explicit.status_code == 503
    assert "private database" not in explicit.get_data(as_text=True)
    assert c.calls == []


@pytest.mark.parametrize("query", ["lang=", "lang=%20", "lang=fr", "lang=zh&lang=en", "lang=zh&lang=zh"])
def test_pdf_rejects_empty_unknown_or_repeated_language(route_case, monkeypatch, query):
    def forbidden(*args, **kwargs):
        raise AssertionError("invalid query must not render a PDF")
    monkeypatch.setattr(ReportManager, "export_pdf", forbidden)
    assert route_case.client.get("/api/report/report_route/pdf?" + query).status_code == 400


@pytest.mark.parametrize("lang,source", [("en", "# Forecast\n\nThe audited English report."),
                                        ("zh", "# 中国市场预测\n\n经过独立审核的中文市场前景分析报告。")])
def test_pdf_explicit_primary_language_uses_primary_export(route_case, monkeypatch, lang, source):
    c = route_case
    c.report.markdown_content = source
    path = c.folder / "primary-immutable.pdf"
    path.write_bytes(b"%PDF-1.4\nprimary\n%%EOF")
    seen = []
    def export(rid, *, lang=None):
        seen.append(lang)
        return str(path)
    monkeypatch.setattr(ReportManager, "export_pdf", export)
    response = c.client.get("/api/report/report_route/pdf?lang=" + lang)
    assert response.status_code == 200, response.json
    assert seen == [None]
    assert f"report_route.{lang}.pdf" in response.headers["Content-Disposition"]


@pytest.mark.parametrize("generation_key", ["generation", "generation_id"])
@pytest.mark.parametrize("source_key", ["source_sha256", "source_markdown_sha256"])
def test_pdf_accepts_display_identity_aliases_and_rejects_stale_source(route_case, monkeypatch, generation_key, source_key):
    c = route_case
    c.body = True
    path = c.folder / "immutable.pdf"
    path.write_bytes(b"%PDF-1.4\nfixture\n%%EOF")
    monkeypatch.setattr(ReportManager, "export_pdf", lambda *a, **kw: str(path))
    source = hashlib.sha256(c.report.markdown_content.encode()).hexdigest()
    base = f"/api/report/report_route/pdf?lang=zh&{generation_key}={c.generation}&{source_key}="
    assert c.client.get(base + source).status_code == 200
    assert c.client.get(base + "stale").status_code == 409
    assert c.calls == []


def test_forced_structured_repair_refreshes_already_complete_forecast(tmp_path, monkeypatch):
    from app.services.report_agent import ReportAgent
    report = SimpleNamespace(report_id="report_force", simulation_id="sim_force", graph_id="graph_force",
                             markdown_content="# English primary report\n")
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path))
    (tmp_path / report.report_id).mkdir()
    monkeypatch.setattr(api, "_check_report_translation_source", lambda *a: report)
    monkeypatch.setattr(ReportManager, "is_publishable", lambda *a: True)
    monkeypatch.setattr(ReportManager, "load_localized_forecast", lambda *a: ({"headline": "已完成"}, {"complete": True}))
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: object())
    seen = []
    monkeypatch.setattr(ReportAgent, "_ensure_localized_forecast", lambda self, rid, lang, *, force=False: seen.append(("forecast", force)))
    monkeypatch.setattr(api, "_report_display", lambda *a, **kw: seen.append(("display", kw["force"])))
    api._repair_report_structured(report, "zh", force=True, expected_identity={})
    assert seen == [("forecast", True), ("display", True)]


@pytest.mark.parametrize("when", ["before_dispatch", "during_body"])
def test_canonical_figure_changes_invalidate_operation_identity(route_case, monkeypatch, when):
    c = route_case
    assert api._report_translation_identity(c.report, "zh", "body")["source_figures"] == {}
    chart = c.folder / "charts" / "out.png"
    chart.parent.mkdir()
    chart.write_bytes(b"synthetic original image bytes")
    c.report.markdown_content += "\n![Chart](charts/out.png)\n"
    (c.folder / "full_report.md").write_text(c.report.markdown_content)
    first = c.client.post(c.url).json["data"]
    expected = {"charts/out.png": hashlib.sha256(chart.read_bytes()).hexdigest()}
    assert first["translation_job"]["identity"]["source_figures"] == expected
    if when == "before_dispatch":
        chart.write_bytes(b"replacement figure with unchanged Markdown")
        response = c.client.get(c.url + "/status?task_id=" + first["task_id"])
        assert response.status_code == 409 and response.json["code"] == "translation_source_changed"
        second = c.client.post(c.url).json["data"]
        assert second["task_id"] != first["task_id"]
        assert second["translation_job"]["identity"]["source_figures"] != expected
    else:
        def changed_while_translating(*args, **kwargs):
            chart.write_bytes(b"changed during synthetic translation")
            c.body = True
            return {"available": True, "updated": True}
        monkeypatch.setattr(ReportManager, "generate_translation_variant", changed_while_translating)
    result = run_queued_report()
    assert result["job_state"] == "failed"
    assert result["error"]["code"] == "translation_source_changed"
    assert not c.calls, "stale source must not proceed to structured work or asset publication"


@pytest.mark.parametrize("automatic_first", [True, False])
def test_automatic_enqueue_and_manual_post_attach_same_durable_operation(route_case, automatic_first):
    from flask import has_request_context
    c = route_case
    assert not has_request_context()
    if automatic_first:
        automatic = api.enqueue_report_translation(c.report.report_id, "zh")
        manual = c.client.post(c.url).json["data"]["translation_job"]
    else:
        manual = c.client.post(c.url).json["data"]["translation_job"]
        automatic = api.enqueue_report_translation(c.report.report_id, "zh")
    assert not has_request_context()
    assert automatic["job_id"] == manual["job_id"]
    assert automatic["identity"] == manual["identity"]
    assert automatic["identity"]["scope"] == "body"
    with Store(database_path(), read_only=True) as store:
        assert store.db.execute("SELECT count(*) FROM tasks").fetchone()[0] == 1
    locator = ReportManager._load_translation_runtime_status(c.report.report_id, "zh")
    assert locator["translation_job_id"] == automatic["job_id"]
    assert c.calls == [], "enqueue only schedules; it must not run a provider inline"


def test_enqueue_rejects_unpublished_source_before_creating_job_or_locator(route_case):
    c = route_case
    c.publishable = False
    with pytest.raises(ArtifactError) as error:
        api.enqueue_report_translation(c.report.report_id, "zh")
    assert error.value.code == "translation_source_unpublished"
    assert not database_path().exists()
    assert ReportManager._load_translation_runtime_status(c.report.report_id, "zh") is None
    assert c.calls == []


def test_automatic_enqueue_does_not_retry_failed_operation(route_case):
    c = route_case
    first = api.enqueue_report_translation(c.report.report_id, "zh")
    c.repair_succeeds = False
    assert run_queued_report()["job_state"] == "failed"
    calls = list(c.calls)
    attached = api.enqueue_report_translation(c.report.report_id, "zh")
    assert attached["job_id"] == first["job_id"]
    assert attached["job_state"] == "failed"
    assert c.calls == calls
    resumed = c.client.post(c.url).json["data"]["translation_job"]
    assert resumed["job_id"] == first["job_id"]
    assert resumed["job_state"] == "queued"


@pytest.mark.parametrize("mode", ["body", "structured"])
@pytest.mark.parametrize("scope_key", ["scope", "mode"])
def test_generic_actions_authorize_current_report_selection_and_enforce_revision(route_case, mode, scope_key):
    c = route_case
    c.body = mode == "structured"
    job = api.enqueue_report_translation(c.report.report_id, "zh", mode=mode)
    selection = {"report_id": c.report.report_id, "lang": "zh", scope_key: mode}
    base = "/api/translations/jobs/" + job["job_id"]
    cancelled = c.client.post(base + "/cancel", json={
        "job_revision": job["job_revision"], "resource": selection})
    assert cancelled.status_code == 200, cancelled.json
    current = cancelled.json["data"]
    assert current["job_state"] == "cancelled"
    assert "identity" not in current and "result" not in current
    stale = c.client.post(base + "/retry", json={
        "job_revision": job["job_revision"], "resource": selection})
    assert stale.status_code == 409 and stale.json["code"] == "stale_job"
    assert scheduler.status(job["job_id"])["job_revision"] == current["job_revision"]
    resumed = c.client.post(base + "/retry", json={
        "job_revision": current["job_revision"], "resource": selection})
    assert resumed.status_code == 200, resumed.json
    assert resumed.json["data"]["job_state"] == "queued"
    assert resumed.json["data"]["job_revision"] > current["job_revision"]
    assert "identity" not in resumed.json["data"] and "result" not in resumed.json["data"]
    assert c.calls == []


@pytest.mark.parametrize("action", ["retry", "cancel"])
@pytest.mark.parametrize("reason", ["changed_source", "wrong_resource", "unpublished", "client_identity"])
def test_generic_report_actions_reject_invalid_resource_authority_without_mutation(route_case, monkeypatch, action, reason):
    c = route_case
    job = api.enqueue_report_translation(c.report.report_id, "zh")
    if action == "retry":
        job = scheduler.cancel(job["job_id"])
    selection = {"report_id": c.report.report_id, "lang": "zh", "scope": "body"}
    if reason == "changed_source":
        (c.folder / "forecast.json").write_text('{"headline":"Source changed after submission"}')
    elif reason == "wrong_resource":
        other = SimpleNamespace(**{**c.report.__dict__, "report_id": "report_other"})
        folder = c.folder.parent / other.report_id
        folder.mkdir()
        for path in c.folder.iterdir():
            if path.is_file() and not path.name.startswith("translation_status"):
                (folder / path.name).write_bytes(path.read_bytes())
        monkeypatch.setattr(ReportManager, "get_report", lambda rid: {
            c.report.report_id: c.report, other.report_id: other}.get(rid))
        selection["report_id"] = other.report_id
    elif reason == "unpublished":
        c.publishable = False
    else:
        # A previously disclosed full job identity is not a resource selection.
        selection = job["identity"]
    response = c.client.post(f"/api/translations/jobs/{job['job_id']}/{action}", json={
        "job_revision": job["job_revision"], "resource": selection})
    assert response.status_code == 403, response.json
    assert response.json["code"] == "resource_forbidden"
    current = scheduler.status(job["job_id"])
    assert current["job_state"] == job["job_state"]
    assert current["job_revision"] == job["job_revision"]
    assert c.calls == []


@pytest.mark.parametrize("force", [False, True])
def test_primary_language_structured_retry_repairs_mixed_canonical_forecast(tmp_path, monkeypatch, force):
    from test_report_forecast_localization import _seal_forecast
    queue_only_scheduler(monkeypatch, tmp_path)
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(tmp_path / "reports"))
    rid = "report_primary_mixed"
    source = {"headline": "委员会决策", "horizon": "2026-12-31",
              "scenarios": [{"name": "Base case", "probability": 0.7},
                            {"name": "Other", "probability": 0.3}],
              "binary_forecasts": [{"id": "F1", "statement": "The proposal is approved.", "probability": 0.7}]}
    _seal_forecast(rid, source, "# Committee outlook\n\n## Decision\n\nAn English primary report.\n")
    assert ReportManager.is_publishable(rid)
    folder = Path(ReportManager._get_report_folder(rid))
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    class EnglishModel:
        model, provider = "scripted-english", "fixture"
        def __init__(self):
            self.calls = 0
        def chat_json(self, messages=None, **kwargs):
            self.calls += 1
            payload = json.loads(messages[-1]["content"])
            assert payload["target_language"] == "en"
            def translate(text):
                return text.replace("委员会决策", "Committee decision")
            if "entries" in payload:
                return {"translations": {key: translate(text) for key, text in payload["entries"].items()}}
            return {"reviews": {key: {"faithful": pair["translation"] == translate(pair["source"]),
                "complete": True, "target_language": True, "issues": []}
                for key, pair in payload["pairs"].items()}}
        def chat(self, **kwargs):
            return json.dumps(self.chat_json(**kwargs))
    model = EnglishModel()
    monkeypatch.setattr("app.utils.llm_client.LLMClient", lambda: model)
    def forbidden(*args, **kwargs):
        raise AssertionError("primary-language repair must not generate a body or target-body generation")
    monkeypatch.setattr(ReportManager, "generate_translation_variant", forbidden)
    monkeypatch.setattr(ReportManager, "refresh_translation_assets", forbidden)
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(api.report_bp, url_prefix="/api/report")
    client = app.test_client()
    base = f"/api/report/{rid}"
    initial = client.get(base + "/forecast?lang=en")
    assert initial.status_code == 200 and not initial.json["data"]["localization"]["complete"]
    assert model.calls == 0
    started = client.post(base + "/translations/en" + ("?force=1" if force else ""))
    assert started.status_code == 200, started.json
    job_id = started.json["data"]["task_id"]
    assert started.json["data"]["translation_job"]["identity"]["scope"] == "structured"
    completed = run_queued_report()
    assert completed["job_state"] == "completed", completed
    polled = client.get(base + "/translations/en/status?task_id=" + job_id).json["data"]
    assert polled["status"] == "completed" and polled["available"]
    assert polled["structured_translation"]["complete"]
    final = client.get(base + "/forecast?lang=en").json["data"]
    assert final["localization"]["complete"]
    assert final["forecast"]["headline"] == "Committee decision"
    assert [row["probability"] for row in final["forecast"]["scenarios"]] == [0.7, 0.3]
    assert model.calls > 0
    assert all((folder / name).read_bytes() == data for name, data in before.items())
    assert not (folder / "full_report.en.md").exists()
    assert ReportManager.resolve_translation(rid, "en") is None
