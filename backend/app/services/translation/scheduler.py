"""Single elected local coordinator. GET never starts or resumes provider work."""
from __future__ import annotations

import contextvars
import logging
from pathlib import Path
import threading

from .contracts import TranslationError, safe_error
from .store import Store, database_path, file_lock

_handlers = {}
_threads = {}
_guard = threading.RLock()
_wake = threading.Event()
_task_id = contextvars.ContextVar("translation_task_id", default=None)
_task_epoch = contextvars.ContextVar("translation_task_epoch", default=None)
_stops = {}
_logger = logging.getLogger("mirofish.translation")


def current_task_id():
    return _task_id.get()


def register_handler(kind, handler):
    if not isinstance(kind, str) or not kind or not callable(handler):
        raise ValueError("translation handler requires a name and callable")
    with _guard:
        _handlers[kind] = handler
    _wake.set()


def _run(path, stop):
    try:
        with file_lock(str(path) + ".scheduler.lock", blocking=False):
            with Store(path) as store:
                epoch = store.elect()
                while not stop.is_set():
                    with _guard:
                        handlers = dict(_handlers)
                    claimed = store.claim_task(epoch, handlers)
                    if claimed is None:
                        _wake.wait(0.5)
                        _wake.clear()
                        continue
                    task_id, kind, payload = claimed
                    token = _task_id.set(task_id)
                    epoch_token = _task_epoch.set(epoch)
                    try:
                        result = handlers[kind](payload)
                        if (store.task(task_id) or {}).get("job_state") == "running":
                            store.finish_task(task_id, epoch, result=result)
                    except Exception as exc:
                        error = safe_error(exc, "operation")
                        if (store.task(task_id) or {}).get("job_state") == "running":
                            store.finish_task(task_id, epoch, error=error)
                        _logger.warning("Translation operation failed id=%s code=%s", task_id, error["code"])
                    finally:
                        _task_id.reset(token)
                        _task_epoch.reset(epoch_token)
    except BlockingIOError:
        # Another process owns the dispatcher. It sees our committed queue rows.
        return
    except Exception as exc:
        _logger.error("Translation coordinator stopped (%s)", type(exc).__name__)


def start_scheduler():
    path = database_path()
    key = str(path.resolve())
    with _guard:
        thread = _threads.get(key)
        if thread is not None and thread.is_alive():
            _wake.set()
            return
        # Validate/create storage before starting a detached worker so failures
        # remain actionable at the mutation boundary.
        with Store(path):
            pass
        stop = threading.Event()
        _stops[key] = stop
        thread = threading.Thread(target=_run, args=(path, stop), name="translation-coordinator", daemon=True)
        _threads[key] = thread
        thread.start()


def submit(kind, identity, payload, *, force=False):
    with _guard:
        if kind not in _handlers:
            raise TranslationError("unknown_operation", "Translation operation is not registered.")
    with Store(database_path()) as store:
        task_id = store.create_task(kind, identity, payload, force=force)
        summary = store.task(task_id)
    start_scheduler()
    _wake.set()
    return summary


def status(job_id):
    path = database_path()
    if not Path(path).is_file():
        return None
    with Store(path, read_only=True) as store:
        return store.task(job_id)


def retry(job_id: str, *, expected_revision: int | None = None) -> dict | None:
    """Retry an admitted task; None intentionally targets latest state.

    Resource-specific callers own their resource/visibility admission. Generic
    routes must supply the observed revision after their resource authorizer.
    Lock order matches publication/cancel: publication lock, then DB transaction.
    """
    path = database_path()
    with file_lock(path.parent / "locks" / (job_id + ".publish.lock")):
        with Store(path) as store:
            summary = store.retry_task(job_id, expected_revision=expected_revision)
    if summary is not None and summary["job_state"] == "queued":
        start_scheduler()
        _wake.set()
    return summary


def stop_schedulers(timeout=2):
    """Application/test shutdown: do not interrupt an in-flight provider call."""
    with _guard:
        pairs = list(_threads.items())
        for stop in _stops.values():
            stop.set()
        _wake.set()
    for _, thread in pairs:
        if thread is not threading.current_thread():
            thread.join(timeout)


def assert_current_task_active():
    task_id = current_task_id()
    if task_id:
        with Store(database_path(), read_only=True) as store:
            task = store.db.execute("SELECT state,epoch FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not task or task["state"] != "running" or task["epoch"] != _task_epoch.get():
            raise TranslationError("operation_cancelled", "Translation operation was cancelled or superseded.")


def update_progress(summary):
    task_id = current_task_id()
    if task_id:
        # Do not expose per-entry review messages/text through the generic job
        # endpoint. Those remain available from the resource's scoped reader.
        public = {key: value for key, value in summary.items() if key != "issues"}
        with Store(database_path()) as store:
            store.update_task_progress(task_id, _task_epoch.get(), public)


from contextlib import contextmanager


@contextmanager
def publication_guard():
    """Final artifact activation and cancellation share this short lock."""
    task_id = current_task_id()
    if not task_id:
        yield
        return
    with file_lock(database_path().parent / "locks" / (task_id + ".publish.lock")):
        assert_current_task_active()
        yield


def cancel(job_id: str, *, expected_revision: int | None = None) -> dict | None:
    """Cancel an admitted task under its publication lock.

    None intentionally targets latest state for resource-specific callers that
    already performed their own identity/visibility checks. Generic routes require
    an observed revision; the store compares it within the mutation transaction.
    """
    path = database_path()
    with file_lock(path.parent / "locks" / (job_id + ".publish.lock")):
        with Store(path) as store:
            return store.cancel_task(job_id, expected_revision=expected_revision)
