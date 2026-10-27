"""Private-fixture review of parent-owned PDF integration boundaries.

Run through main_offline_pytest.py. Synthetic worker output tests admission and
lifecycle only; it is deliberately not evidence of real rendering/model review.
"""

import json
import sys
import threading
from pathlib import Path

import pytest

pytestmark = pytest.mark.guarded_runner

from app.config import Config
from app.services.research_pdf import jobs as job_module
from app.services.research_pdf import sources
from app.services.research_pdf.contracts import PdfExportError
from app.services.research_pdf.jobs import PdfExportJobs
from app.utils.atomic import write_json_atomic
from test_research_pdf_jobs import source_root as parent_source_root
from test_research_pdf_jobs import synthetic_result

source_root = parent_source_root


@pytest.fixture(scope="module", autouse=True)
def record_reviewed_sources() -> None:
    guard = sys.modules.get("main_offline_guard")
    assert guard is not None, "Use the existing guarded offline runner"
    repo = Path(__file__).resolve().parents[2]
    paths = [
        "backend/app/services/research_pdf/contracts.py",
        "backend/app/services/research_pdf/sources.py",
        "backend/app/services/research_pdf/jobs.py",
        "backend/app/api/research_pdf.py",
        "backend/app/__init__.py",
        "backend/app/config.py",
        "backend/tests/test_research_pdf_jobs.py",
    ]
    for relative in paths:
        path = repo / relative
        guard.source_hashes[str(path)] = sources.sha(path.read_bytes())


@pytest.mark.parametrize("cancel_before_error", [False, True])
def test_unknown_dispatch_remains_nonretryable_after_cancel(
    source_root: Path, tmp_path: Path, cancel_before_error: bool
) -> None:
    entered, release = threading.Event(), threading.Event()
    calls = []

    def run(*args: object, **kwargs: object) -> dict:
        calls.append(1)
        entered.set()
        assert release.wait(5)
        raise PdfExportError("dispatch_unknown", "Unknown dispatch outcome", retryable=False)

    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda: {"v": 1})
    first = jobs.start("dossier", "pipe_one")
    assert entered.wait(5)
    try:
        if cancel_before_error:
            assert jobs.cancel("dossier", "pipe_one", first["job_id"])["state"] == "cancelled"
    finally:
        release.set()
    assert jobs.wait(first["job_id"], 5)
    retried = jobs.start("dossier", "pipe_one", retry=True)
    assert jobs.wait(retried["job_id"], 5)
    assert len(calls) == 1, "Cancellation discarded the later nonretryable dispatch outcome"


@pytest.mark.parametrize("poll_changed_source", [False, True])
def test_source_poll_cannot_erase_unknown_dispatch_barrier(
    source_root: Path, tmp_path: Path, poll_changed_source: bool
) -> None:
    calls = []

    def run(*args: object, **kwargs: object) -> dict:
        calls.append(1)
        raise PdfExportError("dispatch_unknown", "Unknown dispatch outcome", retryable=False)

    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda: {"v": 1})
    first = jobs.start("dossier", "pipe_one")
    assert jobs.wait(first["job_id"], 5)
    if poll_changed_source:
        source = source_root / "research_report.md"
        original = source.read_bytes()
        source.write_text("# Changed report\n\nChanged while a reader polls.\n")
        assert jobs.status("dossier", "pipe_one", first["job_id"])["state"] == "stale"
        source.write_bytes(original)
    retried = jobs.start("dossier", "pipe_one", retry=True)
    assert jobs.wait(retried["job_id"], 5)
    assert len(calls) == 1, "A GET/source change replaced a durable nonretryable error"


@pytest.mark.parametrize("mutation", ["none", "non_json_receipt", "missing_input_digest"])
def test_result_requires_parseable_receipt_and_bound_input(
    source_root: Path, tmp_path: Path, mutation: str
) -> None:
    def run(snapshot: dict, directory: Path, **kwargs: object) -> dict:
        result = synthetic_result(snapshot, directory)
        if mutation == "non_json_receipt":
            receipt = Path(result["agent_receipt_path"])
            receipt.write_bytes(b"This is not an agent receipt or JSON.")
            result["agent_receipt_sha256"] = sources.sha(receipt.read_bytes())
        elif mutation == "missing_input_digest":
            result.pop("input_sha256")
            path = Path(result["review_path"])
            review = json.loads(path.read_text())
            review.pop("input_sha256")
            write_json_atomic(str(path), review)
            result["review_sha256"] = sources.sha(path.read_bytes())
        return result

    jobs = PdfExportJobs(tmp_path / "jobs", runner=run, policy=lambda: {"v": 1})
    job = jobs.start("dossier", "pipe_one")
    assert jobs.wait(job["job_id"], 5)
    status = jobs.status("dossier", "pipe_one", job["job_id"])
    if mutation == "none":
        assert status["state"] == "completed"
        assert jobs.download("dossier", "pipe_one", job["job_id"])[0].startswith(b"%PDF-")
    else:
        if status["state"] == "completed":
            raw, _, _ = jobs.download("dossier", "pipe_one", job["job_id"])
            assert raw.startswith(b"%PDF-"), "The malformed receipt reached download admission"
        assert status["state"] == "failed", f"Invalid {mutation} was admitted as {status}"
        with pytest.raises(PdfExportError):
            jobs.download("dossier", "pipe_one", job["job_id"])


@pytest.fixture
def real_source_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    from app.services.report_agent import ReportManager

    pipelines = tmp_path / "pipelines"
    reports = tmp_path / "reports"
    pipelines.mkdir()
    reports.mkdir()
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(pipelines))
    monkeypatch.setattr(ReportManager, "REPORTS_DIR", str(reports))
    return pipelines, reports


def test_real_forecast_admission_and_revocation(
    real_source_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    from app.services.report_agent import ReportManager

    _, reports = real_source_roots
    report = reports / "report_one"
    report.mkdir()
    markdown = "# Forecast\n\nGrowth remains conditional on demand.\n"
    (report / "full_report.md").write_text(markdown)
    write_json_atomic(str(report / "meta.json"), {"status": "completed"})
    write_json_atomic(
        str(report / "final_audit.json"),
        {
            "hard_passed": True,
            "policy_version": Config.REPORT_FINAL_AUDIT_POLICY_VERSION,
            "markdown_sha256": sources.sha(markdown.encode()),
        },
    )
    assert ReportManager.publication_status("report_one")["publishable"] is True
    snapshot = sources.capture_source("forecast", "report_one", None, tmp_path / "snapshot")
    assert snapshot["markdown"] == markdown
    sources.assert_current(snapshot)
    (report / "full_report.md").write_text(markdown + "\nUnreviewed change.\n")
    with pytest.raises(PdfExportError, match="publication"):
        sources.inspect_source("forecast", "report_one")
    with pytest.raises(PdfExportError, match="publication review"):
        sources.assert_current(snapshot)


def test_real_fork_dossier_and_translation_revocation(
    real_source_roots: tuple[Path, Path], tmp_path: Path
) -> None:
    from app.api.research import _research_variant

    pipelines, _ = real_source_roots
    handoff = pipelines / "pipe_base" / "handoff"
    handoff.mkdir(parents=True)
    fork = pipelines / "pipe_fork"
    fork.mkdir()
    write_json_atomic(str(fork / "pipeline_state.json"), {"handoff_dir": str(handoff)})
    markdown = "# Research\n\nDemand remains uncertain.\n"
    translated = "# 深度研究\n\n需求仍然不确定。\n"
    (handoff / "research_report.md").write_text(markdown)
    (handoff / "research_report.zh.md").write_text(translated)
    audit = handoff / "research_report.final_audit.zh.json"
    write_json_atomic(str(audit), {"hard_passed": True})
    status = handoff / "research_report.translation.zh.json"
    write_json_atomic(
        str(status),
        {
            "status": "available",
            "schema_version": 2,
            "target_lang": "zh",
            "source_sha256": sources.sha(markdown.encode()),
            "markdown_sha256": sources.sha(translated.encode()),
            "audit_sha256": sources.sha(audit.read_bytes()),
        },
    )
    assert _research_variant(str(handoff), "zh")[1] == translated
    primary = sources.capture_source("dossier", "pipe_fork", None, tmp_path / "primary")
    assert primary["markdown"] == markdown and primary["resource_id"] == "pipe_fork"
    snapshot = sources.capture_source("dossier", "pipe_fork", "zh", tmp_path / "translated")
    assert snapshot["markdown"] == translated and snapshot["language"] == "zh-CN"
    sources.assert_current(snapshot)
    status.unlink()
    with pytest.raises(PdfExportError, match="missing, stale"):
        sources.inspect_source("dossier", "pipe_fork", "zh")
    with pytest.raises(PdfExportError, match="publication review"):
        sources.assert_current(snapshot)


@pytest.mark.parametrize("fail_interrupted_write", [False, True])
def test_failed_interrupted_state_write_releases_owner(
    source_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fail_interrupted_write: bool
) -> None:
    jobs = PdfExportJobs(tmp_path / "jobs", policy=lambda: {"v": 1}, start_threads=False)
    job = jobs.start("dossier", "pipe_one")
    original_write = jobs._write

    def write(directory: Path, value: dict) -> None:
        if fail_interrupted_write and value["state"] == "interrupted":
            raise OSError("Private-fixture persistence failure")
        return original_write(directory, value)

    monkeypatch.setattr(jobs, "_write", write)
    acquired = []
    original_acquire = job_module._acquire

    def acquire(path: Path, **kwargs: object) -> int | None:
        fd = original_acquire(path, **kwargs)
        if fd is not None and Path(path).name == ".owner.lock":
            acquired.append(fd)
        return fd

    monkeypatch.setattr(job_module, "_acquire", acquire)
    try:
        if fail_interrupted_write:
            with pytest.raises(OSError, match="persistence failure"):
                jobs.start("dossier", "pipe_one", retry=True)
        else:
            jobs.start("dossier", "pipe_one", retry=True)
        owner = tmp_path / "jobs" / job["job_id"] / ".owner.lock"
        fd = original_acquire(owner, blocking=False)
        try:
            assert fd is not None, "A failed atomic state write leaked live ownership"
        finally:
            job_module._release(fd)
    finally:
        # Cleanup the leaked descriptor in this failing regression's private fixture.
        for fd in acquired:
            try:
                job_module._release(fd)
            except OSError:
                pass


@pytest.mark.parametrize("change_during_capture", [False, True])
def test_changed_capture_does_not_poison_original_identity(
    source_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change_during_capture: bool
) -> None:
    source = source_root / "research_report.md"
    original = source.read_bytes()
    capture = sources.capture_source

    def capture_after_change(*args: object) -> dict:
        if change_during_capture:
            source.write_text(
                "# New version\n\nA stable revision captured after the initial read.\n"
            )
        return capture(*args)

    jobs = PdfExportJobs(tmp_path / "jobs", policy=lambda: {"v": 1}, start_threads=False)
    monkeypatch.setattr(sources, "capture_source", capture_after_change)
    if change_during_capture:
        with pytest.raises(PdfExportError, match="changed before export"):
            jobs.start("dossier", "pipe_one")
    else:
        jobs.start("dossier", "pipe_one")
    source.write_bytes(original)
    monkeypatch.setattr(sources, "capture_source", capture)
    # Restore the selected version: a retry must recover this cache identity.
    try:
        job = jobs.start("dossier", "pipe_one", retry=True)
    except PdfExportError as exc:
        pytest.fail(f"A rejected capture stranded the original identity: {exc.code}")
    assert job["state"] == "queued"


def test_separate_managers_share_duplicate_ownership_and_concurrency(
    source_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Config, "RESEARCH_PDF_MAX_CONCURRENT", 1)
    entered, release, second_entered = threading.Event(), threading.Event(), threading.Event()
    calls = []

    def run(snapshot: dict, directory: Path, **kwargs: object) -> dict:
        calls.append(snapshot["resource_id"])
        if snapshot["resource_id"] == "pipe_one":
            entered.set()
            assert release.wait(5)
        else:
            second_entered.set()
        return synthetic_result(snapshot, directory)

    root = tmp_path / "jobs"
    first_manager = PdfExportJobs(root, runner=run, policy=lambda: {"v": 1})
    second_manager = PdfExportJobs(root, runner=run, policy=lambda: {"v": 1})
    first = first_manager.start("dossier", "pipe_one")
    assert entered.wait(5)
    try:
        duplicate = second_manager.start("dossier", "pipe_one")
        assert duplicate["job_id"] == first["job_id"]
        second = second_manager.start("dossier", "pipe_two")
        assert not second_entered.wait(0.2)
        assert calls == ["pipe_one"]
        assert (
            second_manager.cancel("dossier", "pipe_two", second["job_id"])["state"] == "cancelled"
        )
    finally:
        release.set()
    assert first_manager.wait(first["job_id"], 5)
    assert second_manager.wait(second["job_id"], 5)
    assert calls == ["pipe_one"]
    assert first_manager.status("dossier", "pipe_one", first["job_id"])["state"] == "completed"
    assert second_manager.status("dossier", "pipe_two", second["job_id"])["state"] == "cancelled"
