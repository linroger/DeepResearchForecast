"""Job/source/API lifecycle tests with an explicitly synthetic renderer worker.

Native layout and real agent transport are exercised by their separate suites.
"""
import json
from pathlib import Path
import threading

import pytest
from flask import Flask

from app.config import Config
from app.services.research_pdf import sources
from app.services.research_pdf.contracts import PdfExportError
from app.services.research_pdf.jobs import PdfExportJobs, _QA_CHECKS
from app.utils.atomic import write_json_atomic


@pytest.fixture
def source_root(tmp_path, monkeypatch):
    root = tmp_path / "canonical"
    root.mkdir()
    (root / "research_report.md").write_text("# Full report\n\nRevenue is 12.5 and the forecast remains conditional.\n")

    def locate(kind, resource_id, requested_lang):
        if resource_id == "missing":
            raise PdfExportError("source_missing", "No report")
        return (root, "research_report.md", {"created_at":"2026-10-26T00:00:00Z"}, {},
                ["research_report.md"], {"rule":"synthetic-admitted-source"}, requested_lang or "en")
    monkeypatch.setattr(sources, "_locate", locate)
    monkeypatch.setattr(Config, "RESEARCH_PDF_EXPORT_ENABLED", True)
    monkeypatch.setattr(Config, "REPORT_PDF_EXPORT", True)
    monkeypatch.setattr(Config, "RESEARCH_PDF_MAX_CONCURRENT", 2)
    monkeypatch.setattr(Config, "RESEARCH_PDF_TIMEOUT_SECONDS", 30)
    return root


def synthetic_result(snapshot, directory):
    """Only a transport/lifecycle stub, never evidence of actual PDF quality."""
    directory.mkdir(parents=True, exist_ok=True)
    pdf = directory / "test.pdf"
    pdf.write_bytes(b"%PDF-1.7\nSYNTHETIC UNIT-TEST TRANSPORT\n" + snapshot["markdown"].encode())
    png = directory / "page-1.png"
    png.write_bytes(b"SYNTHETIC PAGE EVIDENCE")
    checksum = sources.sha(pdf.read_bytes())
    input_sha = sources.sha(b"synthetic-input")
    qa = {"sha256":checksum,"input_sha256":input_sha,"checks":dict.fromkeys(_QA_CHECKS, True)}
    qa_path = directory / "qa.json"
    write_json_atomic(str(qa_path), qa)
    review = {"schema":"research-pdf-agent-review/v1", "accepted":True,
              "source_digest":snapshot["source_digest"], "language":snapshot["language"],
              "pdf_sha256":checksum, "input_sha256":input_sha, "page_count":1, "policy":{"v":1},
              "page_reviews":[{"page":1,"page_sha256":sources.sha(png.read_bytes()),"verdict":"pass","issues":[]}],
              "reviewer":"SYNTHETIC TEST ONLY; NOT A REAL REVIEW"}
    review_path = directory / "review.json"
    write_json_atomic(str(review_path), review)
    receipt = directory / "agent.json"
    write_json_atomic(str(receipt), {"schema":"research-pdf-agent/v1","status":"reviewed",
        "source_digest":snapshot["source_digest"],"pdf_sha256":checksum,"review_sha256":sources.sha(review_path.read_bytes()),
        "policy_sha256":sources.canonical_hash({"v":1}),"skill_sha256":sources.sha(b"synthetic-skill"),
        "calls_used":1,"test_only":"SYNTHETIC TEST ONLY"})
    return {"pdf_path":str(pdf), "pdf_sha256":checksum, "qa_path":str(qa_path), "qa":qa,
            "source_digest":snapshot["source_digest"], "language":snapshot["language"],
            "input_sha256":input_sha, "review_path":str(review_path),
            "review_sha256":sources.sha(review_path.read_bytes()), "agent_receipt_path":str(receipt),
            "agent_receipt_sha256":sources.sha(receipt.read_bytes()), "calls_used":1,
            "pages":[{"page":1,"path":str(png),"sha256":sources.sha(png.read_bytes())}]}


def test_duplicate_post_and_cache_use_one_worker(source_root, tmp_path):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def run(snapshot, directory, *, progress, is_cancelled):
        calls.append(snapshot["source_digest"])
        progress("planning")
        entered.set()
        assert release.wait(5)
        return synthetic_result(snapshot, directory)
    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda:{"v":1})
    first = jobs.start("dossier", "pipe_one")
    assert entered.wait(5)
    second = jobs.start("dossier", "pipe_one")
    assert first["job_id"] == second["job_id"]
    assert len(calls) == 1
    release.set()
    assert jobs.wait(first["job_id"], 5)
    assert jobs.status("dossier", "pipe_one", first["job_id"])["state"] == "completed"
    again = jobs.start("dossier", "pipe_one")
    assert again["job_id"] == first["job_id"] and again["state"] == "completed"
    assert len(calls) == 1
    raw, name, _ = jobs.download("dossier", "pipe_one", first["job_id"])
    assert raw.startswith(b"%PDF-") and name.endswith(".en.pdf")


def test_source_change_rejects_late_completion(source_root, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def run(snapshot, directory, **_):
        entered.set()
        assert release.wait(5)
        return synthetic_result(snapshot, directory)
    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda:{"v":1})
    first = jobs.start("forecast", "report_one", "en")
    assert entered.wait(5)
    (source_root / "research_report.md").write_text("# Changed report\n\nValue 99 is different.\n")
    release.set()
    assert jobs.wait(first["job_id"], 5)
    assert jobs.status("forecast", "report_one", first["job_id"])["state"] == "stale"
    with pytest.raises(PdfExportError):
        jobs.download("forecast", "report_one", first["job_id"])


def test_cancellation_does_not_publish_late_result(source_root, tmp_path):
    entered, release = threading.Event(), threading.Event()
    def run(snapshot, directory, **_):
        entered.set()
        assert release.wait(5)
        return synthetic_result(snapshot, directory)
    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda:{"v":1})
    job = jobs.start("dossier", "pipe_one")
    assert entered.wait(5)
    assert jobs.cancel("dossier", "pipe_one", job["job_id"])["state"] == "cancelled"
    release.set()
    assert jobs.wait(job["job_id"], 5)
    assert jobs.status("dossier", "pipe_one", job["job_id"])["state"] == "cancelled"


def test_restart_marks_interrupted_without_starting_work(source_root, tmp_path):
    jobs = PdfExportJobs(tmp_path / "jobs", policy=lambda:{"v":1}, start_threads=False)
    job = jobs.start("dossier", "pipe_one")
    restarted = PdfExportJobs(tmp_path / "jobs", policy=lambda:{"v":1}, start_threads=False)
    status = restarted.status("dossier", "pipe_one", job["job_id"])
    assert status["state"] == "interrupted"
    assert restarted.start("dossier", "pipe_one")["state"] == "interrupted"


def test_resource_scope_and_corrupt_result_are_refused(source_root, tmp_path):
    jobs = PdfExportJobs(tmp_path / "jobs", runner=lambda s,d,**k:synthetic_result(s,d), policy=lambda:{"v":1})
    job = jobs.start("forecast", "report_one", "zh")
    assert jobs.wait(job["job_id"], 5)
    with pytest.raises(PdfExportError, match="does not belong"):
        jobs.download("forecast", "report_two", job["job_id"])
    with pytest.raises(PdfExportError):
        jobs.status("dossier", "report_one", job["job_id"])
    data = json.loads((tmp_path / "jobs" / job["job_id"] / "job.json").read_text())
    Path(data["result"]["pdf_path"]).write_bytes(b"%PDF-tampered")
    with pytest.raises(PdfExportError, match="changed"):
        jobs.download("forecast", "report_one", job["job_id"])
    assert jobs.status("forecast", "report_one", job["job_id"])["state"] == "failed"


def test_unreviewed_output_cannot_complete(source_root, tmp_path):
    def run(snapshot, directory, **_):
        result = synthetic_result(snapshot, directory)
        review_path = Path(result["review_path"])
        review = json.loads(review_path.read_text())
        review["accepted"] = False
        write_json_atomic(str(review_path), review)
        result["review_sha256"] = sources.sha(review_path.read_bytes())
        return result
    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda:{"v":1})
    job = jobs.start("dossier", "pipe_one")
    assert jobs.wait(job["job_id"], 5)
    status = jobs.status("dossier", "pipe_one", job["job_id"])
    assert status["state"] == "failed" and status["error"]["code"] == "export_review_incomplete"


def test_nonretryable_unknown_dispatch_is_not_replayed(source_root, tmp_path):
    calls = []
    def run(*args, **kwargs):
        calls.append(1)
        raise PdfExportError("dispatch_unknown", "The previous provider outcome is unknown.", retryable=False)
    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda:{"v":1})
    job = jobs.start("dossier", "pipe_one")
    assert jobs.wait(job["job_id"], 5)
    again = jobs.start("dossier", "pipe_one", retry=True)
    assert again["state"] == "failed" and len(calls) == 1


def test_both_resource_api_paths_use_persisted_jobs(source_root, tmp_path, monkeypatch):
    from app.api import research_pdf as routes
    jobs = PdfExportJobs(tmp_path / "jobs", runner=lambda s,d,**k:synthetic_result(s,d), policy=lambda:{"v":1})
    monkeypatch.setattr(routes, "get_jobs", lambda:jobs)
    app = Flask(__name__)
    app.register_blueprint(routes.research_pdf_bp, url_prefix="/api")
    client = app.test_client()
    for base in ("/api/research/pipe_one/dossier/pdf-export", "/api/report/report_one/pdf-export"):
        response = client.post(base, json={"lang":None})
        assert response.status_code == 202
        job = response.json["data"]
        assert jobs.wait(job["job_id"], 5)
        status = client.get(base+"/"+job["job_id"])
        assert status.json["data"]["state"] == "completed"
        downloaded = client.get(status.json["data"]["download_url"])
        assert downloaded.status_code == 200 and downloaded.mimetype == "application/pdf"
        assert downloaded.data.startswith(b"%PDF-")
        assert downloaded.headers["X-PDF-Source-Digest"] == job["source_digest"]
    assert client.post("/api/report/report_one/pdf-export", json={"html":"untrusted"}).status_code == 400


def test_snapshot_preserves_original_and_rejects_escape(source_root, tmp_path):
    body = (source_root / "research_report.md").read_bytes()
    snapshot = sources.capture_source("dossier", "pipe_one", None, tmp_path / "snapshot")
    assert (source_root / "research_report.md").read_bytes() == body
    assert Path(snapshot["markdown_path"]).read_bytes() == body
    (source_root / "research_report.md").write_text("# Report\n\n![secret](../outside.png)\n")
    with pytest.raises(PdfExportError, match="source folder"):
        sources.inspect_source("dossier", "pipe_one")


def test_snapshot_mutation_leaves_no_partial_destination(source_root, tmp_path, monkeypatch):
    original = sources.inspect_source
    calls = []
    def inspect(*args):
        value = original(*args)
        calls.append(1)
        if len(calls) == 2:
            value["source_digest"] = "changed"
        return value
    monkeypatch.setattr(sources, "inspect_source", inspect)
    with pytest.raises(PdfExportError, match="changed"):
        sources.capture_source("dossier", "pipe_one", None, tmp_path / "snapshot")
    assert not (tmp_path / "snapshot").exists()


def test_disabled_download_and_invalid_language(source_root, tmp_path, monkeypatch):
    jobs = PdfExportJobs(tmp_path / "jobs", policy=lambda:{"v":1}, start_threads=False)
    with pytest.raises(PdfExportError):
        jobs.start("dossier", "pipe_one", "fr")
    monkeypatch.setattr(Config, "RESEARCH_PDF_EXPORT_ENABLED", False)
    with pytest.raises(PdfExportError, match="disabled"):
        jobs.download("dossier", "pipe_one", "pdf_"+"a"*40)
