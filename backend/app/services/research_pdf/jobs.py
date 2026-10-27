"""Persistent, resource-scoped jobs for reviewed PDF exports.

Atomic JSON stores observations; advisory file locks carry live ownership across
threads/processes. GETs never start a worker or replay a provider request.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

from app.config import Config
from app.utils.atomic import write_json_atomic
from .contracts import PdfExportError
from . import sources

_JOB_ID = re.compile(r"^pdf_[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE = {"queued", "running"}
_PHASES = {"reading_source", "planning", "rendering", "checking_content", "reviewing_pages", "repairing", "publishing"}
_QA_CHECKS = {"all_text_present", "all_components_drawn", "figure_pixels_present", "links_present",
              "used_fonts_embedded", "safe_bounds", "no_component_overlap", "component_text_regions",
              "independent_parser", "page_numbers"}


def _now():
    return datetime.now(timezone.utc).isoformat()


def _read_json(path):
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PdfExportError("export_state_invalid", "The saved export state is unavailable or damaged.", retryable=False) from exc
    if not isinstance(value, dict):
        raise PdfExportError("export_state_invalid", "The saved export state is invalid.")
    return value


def _acquire(path, *, blocking=True):
    path = Path(path)
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        return fd
    except BlockingIOError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise


def _release(fd):
    if fd is not None:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


@contextmanager
def _lock(path):
    fd = _acquire(path)
    try:
        yield
    finally:
        _release(fd)


class PdfExportJobs:
    def __init__(self, root=None, *, runner=None, policy=None, start_threads=True):
        self.root = Path(root or Path(Config.UPLOAD_FOLDER) / "pdf_exports").absolute()
        self.runner = runner
        self.policy = policy
        self.start_threads = start_threads
        self._threads = {}
        self._thread_guard = threading.Lock()

    def _ensure_root(self):
        if self.root.is_symlink():
            raise PdfExportError("export_storage_unsafe", "Export storage must not be a symbolic link.")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _dir(self, job_id):
        if not isinstance(job_id, str) or not _JOB_ID.fullmatch(job_id):
            raise PdfExportError("export_not_found", "The requested export was not found.")
        path = self.root / job_id
        if path.is_symlink():
            raise PdfExportError("export_storage_unsafe", "The saved export directory is unsafe.")
        return path

    def _policy(self):
        if self.policy is not None:
            return self.policy()
        from .agent import policy_fingerprint
        return policy_fingerprint()

    def _limits(self):
        concurrent = int(getattr(Config, "RESEARCH_PDF_MAX_CONCURRENT", 2))
        timeout = int(getattr(Config, "RESEARCH_PDF_TIMEOUT_SECONDS", 900))
        if not 1 <= concurrent <= 16 or not 1 <= timeout <= 7200:
            raise PdfExportError("export_configuration", "PDF concurrency must be 1–16 and timeout 1–7200 seconds.")
        return concurrent, timeout

    def _write(self, directory, job):
        job["updated_at"] = _now()
        write_json_atomic(str(directory / "job.json"), job, allow_nan=False)

    def _load(self, kind, resource_id, job_id):
        sources.validate_identity(kind, resource_id, None)
        directory = self._dir(job_id)
        if not (directory / "job.json").is_file():
            raise PdfExportError("export_not_found", "The requested export was not found.")
        job = _read_json(directory / "job.json")
        if (job.get("schema") != "research-pdf-job/v1" or job.get("job_id") != job_id
                or job.get("kind") != kind or job.get("resource_id") != resource_id):
            raise PdfExportError("export_not_found", "The requested export does not belong to this report.")
        return directory, job

    def _public(self, job):
        base = (f"/api/research/{job['resource_id']}/dossier/pdf-export" if job["kind"] == "dossier"
                else f"/api/report/{job['resource_id']}/pdf-export")
        return {key: job.get(key) for key in ("job_id", "kind", "resource_id", "requested_lang", "language",
                "source_digest", "state", "phase", "progress", "error")} | {
                "error": job.get("replay_barrier") or job.get("error"),
                "download_url": f"{base}/{job['job_id']}/download" if job["state"] == "completed" and not job.get("replay_barrier") else None}

    def _snapshot(self, directory, job):
        path = sources._contained(directory, directory / "source" / "snapshot.json")
        snapshot = _read_json(path)
        if (snapshot.get("source_digest") != job["source_digest"] or snapshot.get("kind") != job["kind"]
                or snapshot.get("resource_id") != job["resource_id"] or snapshot.get("requested_lang") != job["requested_lang"]):
            raise PdfExportError("export_snapshot_invalid", "The export snapshot identity is invalid.")
        folder = directory / "source"
        if Path(snapshot.get("folder", "")).resolve() != folder.resolve():
            raise PdfExportError("export_snapshot_invalid", "The export snapshot folder is invalid.")
        if sources.sha((folder / "source.md").read_bytes()) != snapshot["markdown_sha256"]:
            raise PdfExportError("export_snapshot_invalid", "The saved report snapshot changed.")
        if sources.sha(snapshot["markdown"].encode()) != snapshot["markdown_sha256"]:
            raise PdfExportError("export_snapshot_invalid", "The saved report text changed.")
        for asset in snapshot["assets"]:
            path = sources._contained(folder, folder / asset["relative_path"])
            if not path.is_file() or sources.sha(path.read_bytes()) != asset["sha256"]:
                raise PdfExportError("export_snapshot_invalid", "A saved export figure changed.")
        return snapshot

    def _artifact(self, directory, value, expected):
        if not isinstance(value, str) or not isinstance(expected, str) or not _DIGEST.fullmatch(expected):
            raise PdfExportError("export_artifact_invalid", "Export evidence is incomplete.")
        path = sources._contained(directory, Path(value))
        if not path.is_file():
            raise PdfExportError("export_artifact_invalid", "A verified export artifact is missing.", retryable=True)
        raw = path.read_bytes()
        if sources.sha(raw) != expected:
            raise PdfExportError("export_artifact_invalid", "A verified export artifact changed.", retryable=True)
        return raw

    def _verify_result(self, directory, job, result):
        if not isinstance(result, dict) or job.get("replay_barrier"):
            raise PdfExportError("export_review_incomplete", "The export agent did not complete its checks.")
        for key in ("source_digest", "input_sha256", "pdf_sha256"):
            if not isinstance(result.get(key), str) or not _DIGEST.fullmatch(result[key]):
                raise PdfExportError("export_review_incomplete", "The export is missing a required content binding.")
        if result["source_digest"] != job["source_digest"] or result.get("language") != job["language"]:
            raise PdfExportError("export_review_incomplete", "The export belongs to a different source or language.")
        pdf = self._artifact(directory, result.get("pdf_path"), result.get("pdf_sha256"))
        if not pdf.startswith(b"%PDF-"):
            raise PdfExportError("export_artifact_invalid", "The completed export is not a PDF.")
        raw_review = self._artifact(directory, result.get("review_path"), result.get("review_sha256"))
        raw_agent = self._artifact(directory, result.get("agent_receipt_path"), result.get("agent_receipt_sha256"))
        try:
            review, agent_receipt = json.loads(raw_review), json.loads(raw_agent)
        except (ValueError, UnicodeError) as exc:
            raise PdfExportError("export_review_incomplete", "Export review evidence is not valid JSON.") from exc
        expected = {"schema": "research-pdf-agent-review/v1", "accepted": True,
                    "source_digest": job["source_digest"], "language": job["language"],
                    "pdf_sha256": result.get("pdf_sha256"), "input_sha256": result.get("input_sha256")}
        if (not isinstance(review, dict) or review.get("accepted") is not True
                or any(review.get(key) != val for key, val in expected.items()) or review.get("policy") != job["policy"]):
            raise PdfExportError("export_review_incomplete", "The PDF is not bound to a complete agent review.")
        agent_expected = {"schema":"research-pdf-agent/v1", "status":"reviewed", "source_digest":job["source_digest"],
                          "pdf_sha256":result["pdf_sha256"], "review_sha256":result["review_sha256"],
                          "policy_sha256":sources.canonical_hash(job["policy"])}
        if (not isinstance(agent_receipt, dict) or any(agent_receipt.get(k) != v for k,v in agent_expected.items())
                or type(agent_receipt.get("calls_used")) is not int or agent_receipt["calls_used"] < 1
                or agent_receipt["calls_used"] != result.get("calls_used")
                or not isinstance(agent_receipt.get("skill_sha256"), str)
                or not _DIGEST.fullmatch(agent_receipt["skill_sha256"])):
            raise PdfExportError("export_review_incomplete", "The export agent receipt is incomplete or belongs to other inputs.")
        if job["policy"].get("skill_sha256") and agent_receipt["skill_sha256"] != job["policy"]["skill_sha256"]:
            raise PdfExportError("export_review_incomplete", "The agent used a different export skill.")
        pages = result.get("pages")
        if not isinstance(pages, list) or not pages or review.get("page_count") != len(pages):
            raise PdfExportError("export_review_incomplete", "The page review inventory is incomplete.")
        for number, page in enumerate(pages, 1):
            if page.get("page") != number:
                raise PdfExportError("export_review_incomplete", "The page review order is invalid.")
            self._artifact(directory, page.get("path"), page.get("sha256"))
        page_reviews = review.get("page_reviews")
        if not isinstance(page_reviews, list) or len(page_reviews) != len(pages):
            raise PdfExportError("export_review_incomplete", "Every PDF page requires an actual review record.")
        for page, verdict in zip(pages, page_reviews, strict=True):
            if (not isinstance(verdict, dict) or verdict.get("page") != page["page"]
                    or verdict.get("page_sha256") != page["sha256"] or verdict.get("verdict") != "pass"
                    or verdict.get("issues") != []):
                raise PdfExportError("export_review_incomplete", "A PDF page has no passing source-bound review.")
        qa_path = sources._contained(directory, Path(result.get("qa_path", "")))
        qa = _read_json(qa_path)
        checks = qa.get("checks", {})
        if not isinstance(checks, dict) or any(checks.get(key) is not True for key in _QA_CHECKS):
            raise PdfExportError("export_review_incomplete", "The PDF has not passed every required content and layout check.")
        if qa.get("sha256") != result["pdf_sha256"] or qa != result.get("qa") or qa.get("input_sha256") != result["input_sha256"]:
            raise PdfExportError("export_review_incomplete", "The PDF check receipt belongs to different bytes.")
        return pdf

    def _check_current(self, directory, job):
        snapshot = self._snapshot(directory, job)
        sources.assert_current(snapshot)
        if canonical := job.get("policy"):
            if canonical != self._policy():
                raise PdfExportError("export_policy_changed", "The export skill or model settings changed. Start a fresh export.", retryable=True)
        return snapshot

    def _finish_error(self, directory, job, error, *, state="failed"):
        job.update(state=state, error=error.public(), finished_at=_now())
        self._write(directory, job)

    def start(self, kind, resource_id, lang=None, *, retry=False):
        if not getattr(Config, "REPORT_PDF_EXPORT", True) or not getattr(Config, "RESEARCH_PDF_EXPORT_ENABLED", True):
            raise PdfExportError("pdf_export_disabled", "PDF export is disabled.")
        sources.validate_identity(kind, resource_id, lang)
        if type(retry) is not bool:
            raise PdfExportError("invalid_request", "retry must be a boolean.")
        self._limits()
        source = sources.inspect_source(kind, resource_id, lang)
        policy = self._policy()
        identity = sources.canonical_hash({"source": source["source_digest"], "policy": policy})
        job_id = "pdf_" + identity[:40]
        self._ensure_root()
        directory = self._dir(job_id)
        owner_fd = None
        with _lock(self.root / ".create.lock"):
            directory.mkdir(exist_ok=True, mode=0o700)
        with _lock(directory / ".metadata.lock"):
            path = directory / "job.json"
            if path.exists():
                job = _read_json(path)
                if job.get("identity") != identity or job.get("resource_id") != resource_id or job.get("kind") != kind:
                    raise PdfExportError("export_state_invalid", "The cached export identity is invalid.")
                if job.get("replay_barrier"):
                    return self._public(job)
                if job["state"] == "completed":
                    try:
                        self._check_current(directory, job)
                        self._verify_result(directory, job, job.get("result"))
                        return self._public(job)
                    except PdfExportError as exc:
                        self._finish_error(directory, job, exc)
                if job["state"] in _ACTIVE:
                    owner_fd = _acquire(directory / ".owner.lock", blocking=False)
                    if owner_fd is None:
                        return self._public(job)
                    try:
                        self._finish_error(directory, job, PdfExportError("export_interrupted", "The previous export stopped. Retry to resume eligible work.", retryable=True), state="interrupted")
                    except BaseException:
                        _release(owner_fd)
                        raise
                    if not retry:
                        _release(owner_fd)
                        return self._public(job)
                if not retry:
                    return self._public(job)
                if not (job.get("error") or {}).get("retryable", False):
                    return self._public(job)
                owner_fd = owner_fd if owner_fd is not None else _acquire(directory / ".owner.lock", blocking=False)
                if owner_fd is None:
                    return self._public(job)
                try:
                    snapshot = self._snapshot(directory, job)
                    sources.assert_current(snapshot)
                except BaseException:
                    _release(owner_fd)
                    raise
                job["attempt"] += 1
            else:
                owner_fd = _acquire(directory / ".owner.lock", blocking=False)
                if owner_fd is None:
                    raise PdfExportError("export_busy", "This export is being prepared. Try again shortly.", retryable=True)
                try:
                    if (directory / "source" / "snapshot.json").is_file():
                        try:
                            snapshot = self._snapshot(directory, {"source_digest":source["source_digest"],
                                "kind":kind, "resource_id":resource_id, "requested_lang":lang})
                            sources.assert_current(snapshot)
                        except PdfExportError:
                            (directory / "source").rename(directory / (".rejected-source-"+uuid.uuid4().hex))
                            snapshot = sources.capture_source(kind, resource_id, lang, directory / "source")
                    else:
                        snapshot = sources.capture_source(kind, resource_id, lang, directory / "source")
                    if snapshot["source_digest"] != source["source_digest"]:
                        (directory / "source").rename(directory / (".rejected-source-"+uuid.uuid4().hex))
                        raise PdfExportError("source_changed", "The report changed before export started.", retryable=True)
                except BaseException:
                    _release(owner_fd)
                    raise
                job = {"schema": "research-pdf-job/v1", "job_id": job_id, "identity": identity,
                       "kind": kind, "resource_id": resource_id, "requested_lang": lang,
                       "language": snapshot["language"], "source_digest": snapshot["source_digest"],
                       "policy": policy, "created_at": _now(), "attempt": 1}
            job.update(state="queued", phase="reading_source", error=None, progress={}, result=None,
                       attempt_token=uuid.uuid4().hex, started_at=_now())
            try:
                self._write(directory, job)
            except BaseException:
                _release(owner_fd)
                raise
        if self.start_threads:
            thread = threading.Thread(target=self._run, args=(directory, job["attempt_token"], owner_fd),
                                      name=f"pdf-export-{job_id[-8:]}", daemon=True)
            with self._thread_guard:
                self._threads[job_id] = thread
            try:
                thread.start()
            except BaseException:
                _release(owner_fd)
                raise
        else:
            _release(owner_fd)
        return self._public(job)

    def _cancelled(self, directory, token):
        job = _read_json(directory / "job.json")
        return job.get("attempt_token") != token or job.get("state") not in _ACTIVE

    def _run(self, directory, token, owner_fd):
        slot_fd = None
        try:
            concurrent, timeout = self._limits()
            deadline = time.monotonic() + timeout
            while slot_fd is None:
                if self._cancelled(directory, token):
                    return
                if time.monotonic() >= deadline:
                    raise PdfExportError("export_timeout", "The export queue timed out. Retry later.", retryable=True)
                for slot in range(concurrent):
                    slot_fd = _acquire(self.root / f".slot-{slot}.lock", blocking=False)
                    if slot_fd is not None:
                        break
                if slot_fd is None:
                    threading.Event().wait(.1)

            def progress(phase, detail=None):
                if phase not in _PHASES:
                    raise PdfExportError("export_protocol", "The export agent reported an invalid phase.")
                if time.monotonic() >= deadline:
                    raise PdfExportError("export_timeout", "The export exceeded its time limit.", retryable=True)
                with _lock(directory / ".metadata.lock"):
                    job = _read_json(directory / "job.json")
                    if job.get("attempt_token") != token or job["state"] not in _ACTIVE:
                        raise PdfExportError("export_cancelled", "Export was cancelled.", retryable=True)
                    self._check_current(directory, job)
                    # Only bounded counters are exposed; never provider text or source excerpts.
                    detail = detail if isinstance(detail, dict) else {}
                    counters = {key: value for key, value in detail.items() if key in
                                {"completed", "total", "completed_pages", "total_pages", "calls_used", "attempt"}
                                and type(value) is int and value >= 0}
                    job.update(state="running", phase=phase, progress=counters)
                    self._write(directory, job)

            progress("reading_source")
            job = _read_json(directory / "job.json")
            snapshot = self._snapshot(directory, job)
            work = directory / "work"
            work.mkdir(exist_ok=True, mode=0o700)
            if self.runner is None:
                from .agent import run_export
                runner = run_export
            else:
                runner = self.runner
            result = runner(snapshot, work, progress=progress,
                            is_cancelled=lambda: self._cancelled(directory, token))
            progress("publishing")
            with _lock(directory / ".metadata.lock"):
                job = _read_json(directory / "job.json")
                if job.get("attempt_token") != token or job["state"] not in _ACTIVE:
                    return
                self._check_current(directory, job)
                self._verify_result(directory, job, result)
                job.update(state="completed", phase="complete", result=result, error=None, finished_at=_now())
                self._write(directory, job)
        except BaseException as exc:
            error = exc if isinstance(exc, PdfExportError) else PdfExportError(
                "export_internal_error", "The export could not finish. Its source files are unchanged.", retryable=True)
            with _lock(directory / ".metadata.lock"):
                job = _read_json(directory / "job.json")
                if job.get("attempt_token") == token:
                    # Execution replay eligibility is independent of cancellation
                    # and source-freshness observations written by status readers.
                    job["execution_error"] = error.public()
                    if not error.retryable and error.code != "export_cancelled":
                        job["replay_barrier"] = error.public()
                    if job["state"] in _ACTIVE:
                        state = "stale" if error.code in {"source_changed", "export_policy_changed"} else "failed"
                        self._finish_error(directory, job, error, state=state)
                    else:
                        self._write(directory, job)
        finally:
            _release(slot_fd)
            _release(owner_fd)
            with self._thread_guard:
                self._threads.pop(directory.name, None)

    def status(self, kind, resource_id, job_id):
        directory, _ = self._load(kind, resource_id, job_id)
        with _lock(directory / ".metadata.lock"):
            _, job = self._load(kind, resource_id, job_id)
            try:
                self._check_current(directory, job)
                if job["state"] == "completed":
                    self._verify_result(directory, job, job.get("result"))
            except PdfExportError as exc:
                self._finish_error(directory, job, exc, state="stale" if exc.code in {"source_changed", "export_policy_changed"} else "failed")
            if job["state"] in _ACTIVE:
                fd = _acquire(directory / ".owner.lock", blocking=False)
                if fd is not None:
                    _release(fd)
                    self._finish_error(directory, job, PdfExportError("export_interrupted", "The export worker stopped. Retry to resume eligible work.", retryable=True), state="interrupted")
            return self._public(job)

    def cancel(self, kind, resource_id, job_id):
        directory, _ = self._load(kind, resource_id, job_id)
        with _lock(directory / ".metadata.lock"):
            _, job = self._load(kind, resource_id, job_id)
            if job["state"] in _ACTIVE:
                self._finish_error(directory, job, PdfExportError("export_cancelled", "Export cancelled; an already dispatched model call may still finish.", retryable=True), state="cancelled")
            return self._public(job)

    def download(self, kind, resource_id, job_id):
        if not getattr(Config, "REPORT_PDF_EXPORT", True) or not getattr(Config, "RESEARCH_PDF_EXPORT_ENABLED", True):
            raise PdfExportError("pdf_export_disabled", "PDF export is disabled.")
        directory, _ = self._load(kind, resource_id, job_id)
        with _lock(directory / ".metadata.lock"):
            _, job = self._load(kind, resource_id, job_id)
            if job["state"] != "completed":
                raise PdfExportError("export_not_ready", "The reviewed PDF is not ready to download.", retryable=job["state"] in _ACTIVE)
            self._check_current(directory, job)
            raw = self._verify_result(directory, job, job.get("result"))
            self._check_current(directory, job)
            return raw, f"{resource_id}.{job['language']}.pdf", self._public(job)

    def wait(self, job_id, timeout=30):
        """Bounded join for controlled tests/explicit shutdown; never used by GET."""
        with self._thread_guard:
            thread = self._threads.get(job_id)
        if thread:
            thread.join(timeout)
            return not thread.is_alive()
        return True


_managers = {}
_managers_lock = threading.Lock()


def get_jobs():
    root = str(Path(Config.UPLOAD_FOLDER).absolute() / "pdf_exports")
    with _managers_lock:
        if root not in _managers:
            _managers[root] = PdfExportJobs(root)
        return _managers[root]
