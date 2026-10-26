"""Local transactional work journal; publication is independently verified.

Transactions are short and never span a model call. OS locks establish actual
single-host ownership; monotonically increasing fences reject stale completions.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .contracts import SCHEMA, TranslationError, canonical, digest, now


def database_path():
    from ...config import Config
    return Path(Config.UPLOAD_FOLDER) / "translations" / "jobs.sqlite3"


@contextmanager
def file_lock(path, *, blocking=True):
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        yield
    finally:
        os.close(fd)


class Store:
    def __init__(self, path=":memory:", *, read_only=False):
        self.db = None
        try:
            self._initialize(path, read_only=read_only)
        except (sqlite3.Error, OSError) as exc:
            if self.db is not None:
                self.db.close()
            raise TranslationError("store_unavailable", "Translation job storage is unavailable; existing published reports remain readable.", retryable=True) from exc

    def _initialize(self, path, *, read_only=False):
        self.path = str(path)
        self.read_only = read_only
        if self.path != ":memory:" and not read_only:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        target = self.path if not read_only else Path(self.path).absolute().as_uri() + "?mode=ro"
        self.db = sqlite3.connect(target, uri=read_only, timeout=5, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        if not read_only:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS translation_schema(version INTEGER NOT NULL);
                INSERT INTO translation_schema SELECT 2 WHERE NOT EXISTS(SELECT 1 FROM translation_schema);
                CREATE TABLE IF NOT EXISTS jobs(
                    id TEXT PRIMARY KEY, identity TEXT NOT NULL, pairs TEXT NOT NULL,
                    lang TEXT NOT NULL, context TEXT NOT NULL, max_calls INTEGER NOT NULL,
                    calls INTEGER NOT NULL DEFAULT 0, fence INTEGER NOT NULL DEFAULT 0,
                    state TEXT NOT NULL, phase TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS units(
                    job_id TEXT NOT NULL REFERENCES jobs(id), key TEXT NOT NULL,
                    position INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(job_id,key));
                CREATE TABLE IF NOT EXISTS attempts(
                    id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
                    fence INTEGER NOT NULL, stage TEXT NOT NULL, keys_json TEXT NOT NULL,
                    state TEXT NOT NULL, started TEXT NOT NULL, ended TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS tasks(
                    id TEXT PRIMARY KEY, dedup TEXT NOT NULL UNIQUE, kind TEXT NOT NULL,
                    identity TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL,
                    phase TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
                    epoch INTEGER NOT NULL DEFAULT 0, result TEXT, error TEXT,
                    created TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS owner(id INTEGER PRIMARY KEY CHECK(id=1),epoch INTEGER NOT NULL);
                INSERT OR IGNORE INTO owner VALUES(1,0);
            """)
            with self.transaction():
                columns = {row[1] for row in self.db.execute("PRAGMA table_info(tasks)")}
                if "progress" not in columns:
                    self.db.execute("ALTER TABLE tasks ADD COLUMN progress TEXT")
        version = self.db.execute("SELECT version FROM translation_schema").fetchone()
        if not version or version[0] != 2:
            self.close()
            raise TranslationError("unsupported_store", "Translation store schema is unsupported.")

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def create_job(self, identity, pairs, lang, context, max_calls):
        job_id = "tr_" + digest([SCHEMA, identity, pairs, lang, context])
        with self.transaction():
            self.db.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,0,0,'queued','translating',?)",
                            (job_id, canonical(identity), canonical(pairs), lang, context, max_calls, now()))
            for index, (key, source) in enumerate(pairs):
                unit = {"source": source, "stage": "pending", "candidate": None, "receipt": None,
                        "issues": [], "repair_count": 0, "protocol_failures": {}, "diagnostic": None}
                self.db.execute("INSERT OR IGNORE INTO units VALUES(?,?,?,?)",
                                (job_id, key, index, canonical(unit)))
        return job_id

    def claim(self, job_id, additional_budget=None):
        with self.transaction():
            previous = self.job(job_id)
            # This call occurs only after exclusive job ownership is obtained
            # and an adapter explicitly invokes generation/resume. A new bounded
            # allowance does not reset the cumulative attempt/cost record.
            if additional_budget is not None and previous["state"] in {"failed", "interrupted", "running"}:
                self.db.execute("UPDATE jobs SET max_calls=? WHERE id=?",
                                (previous["calls"] + max(0, int(additional_budget)), job_id))
            self.db.execute("UPDATE jobs SET fence=fence+1,state='running',updated=? WHERE id=?", (now(), job_id))
            fence = self.job(job_id)["fence"]
            self.db.execute("UPDATE attempts SET state='unknown',ended=? WHERE job_id=? AND state='started'",
                            (now(), job_id))
        return fence

    def job(self, job_id):
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def units(self, job_id):
        return {row["key"]: json.loads(row["data"]) for row in self.db.execute(
            "SELECT key,data FROM units WHERE job_id=? ORDER BY position", (job_id,))}

    def require_fence(self, job_id, fence):
        row = self.job(job_id)
        if not row or row["fence"] != fence:
            raise TranslationError("stale_owner", "Translation worker no longer owns this job.")
        return row

    def checkpoint(self, job_id, fence, units, *, state=None, phase=None, returned_attempt=None):
        with self.transaction():
            row = self.require_fence(job_id, fence)
            for key, data in units.items():
                self.db.execute("UPDATE units SET data=? WHERE job_id=? AND key=?", (canonical(data), job_id, key))
            self.db.execute("UPDATE jobs SET state=?,phase=?,updated=? WHERE id=?",
                            (state or row["state"], phase or row["phase"], now(), job_id))
            if returned_attempt:
                self.db.execute("UPDATE attempts SET state='returned',ended=? WHERE id=? AND job_id=? AND fence=?",
                                (now(), returned_attempt, job_id, fence))

    def reserve(self, job_id, fence, stage, keys):
        with self.transaction():
            row = self.require_fence(job_id, fence)
            if row["calls"] >= row["max_calls"]:
                raise TranslationError("budget_exhausted", "Translation call budget exhausted.")
            attempt_id = uuid.uuid4().hex
            self.db.execute("UPDATE jobs SET calls=calls+1,phase=?,updated=? WHERE id=?", (stage, now(), job_id))
            self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,'started',?,NULL,NULL)",
                            (attempt_id, job_id, fence, stage, canonical(keys), now()))
        return attempt_id

    def finish_attempt(self, job_id, fence, attempt_id, error=None):
        with self.transaction():
            self.require_fence(job_id, fence)
            outcome = ("unknown" if error and error.get("code") in {"provider_timeout", "provider_failure"}
                       else "failed" if error else "returned")
            self.db.execute("UPDATE attempts SET state=?,ended=?,error=? WHERE id=? AND fence=?",
                            (outcome, now(), canonical(error) if error else None, attempt_id, fence))

    def summary(self, job_id):
        job, units = self.job(job_id), self.units(job_id)
        accepted = sum(u["stage"] == "accepted" for u in units.values())
        preserved = sum(u["stage"] == "accepted" and (u.get("receipt") or {}).get("preserved") is True for u in units.values())
        review = sum(u["stage"] in {"validate", "review", "review_returned"} for u in units.values())
        failed = sum(u["stage"] == "failed" for u in units.values())
        total = len(units)
        return {"schema": SCHEMA, "job_id": job_id, "job_revision": job["fence"],
                "job_state": job["state"], "phase": job["phase"], "calls_used": job["calls"],
                "call_budget": job["max_calls"], "content_state": "available" if accepted == total else "partial" if accepted else "source_only",
                "coverage": {"required": total, "accepted": accepted, "pending_review": review,
                             "failed": failed, "pending_translation": total - accepted - review - failed,
                             "preserved": preserved},
                "issues": [{"entry": key, **u["error"]} for key, u in units.items() if u.get("error")],
                "updated_at": job["updated"]}

    def create_task(self, kind, identity, payload, force=False):
        key = digest([kind, identity, payload])
        with self.transaction():
            existing = self.db.execute("SELECT * FROM tasks WHERE dedup=?", (key,)).fetchone()
            if existing and not (force and existing["state"] not in {"queued", "running"}):
                return existing["id"]
            if existing:
                self.db.execute("UPDATE tasks SET dedup=? WHERE id=?", (key + ":retired:" + existing["id"], existing["id"]))
            task_id = "tj_" + uuid.uuid4().hex
            self.db.execute("INSERT INTO tasks(id,dedup,kind,identity,payload,state,phase,revision,epoch,result,error,created,updated) VALUES(?,?,?,?,?,'queued','queued',1,0,NULL,NULL,?,?)",
                            (task_id, key, kind, canonical(identity), canonical(payload), now(), now()))
        return task_id

    def task(self, task_id):
        row = self.db.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if not row:
            return None
        result = json.loads(row["result"]) if row["result"] else None
        error = json.loads(row["error"]) if row["error"] else None
        progress = json.loads(row["progress"]) if "progress" in row.keys() and row["progress"] else {}
        status = {"queued": "generating", "running": "generating", "completed": "available"}.get(row["state"], row["state"])
        return {"schema": SCHEMA, "job_id": task_id, "job_revision": row["revision"],
                "job_state": row["state"], "status": status, "phase": row["phase"],
                "kind": row["kind"], "identity": json.loads(row["identity"]), "result": result,
                "issues": [error["message"]] if error else [], "error": error,
                "actions": {"retry": row["state"] in {"failed", "interrupted", "cancelled"},
                            "stop": row["state"] in {"queued", "running"}},
                "progress": progress, "coverage": progress.get("coverage", {}),
                "created_at": row["created"], "updated_at": row["updated"]}

    def update_task_progress(self, task_id, epoch, summary):
        with self.transaction():
            self.db.execute("UPDATE tasks SET phase=?,progress=?,revision=revision+1,updated=? WHERE id=? AND epoch=? AND state='running'",
                            (summary["phase"], canonical(summary), now(), task_id, epoch))

    def elect(self):
        with self.transaction():
            self.db.execute("UPDATE owner SET epoch=epoch+1 WHERE id=1")
            epoch = self.db.execute("SELECT epoch FROM owner WHERE id=1").fetchone()[0]
            error = canonical({"code": "interrupted", "message": "Translation worker stopped; resume saved work.", "retryable": True})
            self.db.execute("UPDATE tasks SET state='interrupted',error=?,revision=revision+1,updated=? WHERE state='running'",
                            (error, now()))
        return epoch

    def claim_task(self, epoch, kinds):
        if not kinds:
            return None
        with self.transaction():
            if self.db.execute("SELECT epoch FROM owner WHERE id=1").fetchone()[0] != epoch:
                raise TranslationError("stale_owner", "Translation coordinator was superseded.")
            placeholders = ",".join("?" for _ in kinds)
            row = self.db.execute(f"SELECT * FROM tasks WHERE state='queued' AND kind IN ({placeholders}) ORDER BY created LIMIT 1", tuple(kinds)).fetchone()
            if not row:
                return None
            self.db.execute("UPDATE tasks SET state='running',phase='translating',epoch=?,revision=revision+1,updated=? WHERE id=?",
                            (epoch, now(), row["id"]))
        return row["id"], row["kind"], json.loads(row["payload"])

    def finish_task(self, task_id, epoch, result=None, error=None):
        with self.transaction():
            cursor = self.db.execute("UPDATE tasks SET state=?,phase=?,result=?,error=?,revision=revision+1,updated=? WHERE id=? AND epoch=? AND state='running'",
                ("failed" if error else "completed", "failed" if error else "completed",
                 canonical(result) if result is not None else None, canonical(error) if error else None, now(), task_id, epoch))
            if cursor.rowcount != 1:
                raise TranslationError("stale_owner", "Translation operation no longer owns its result.")

    def retry_task(self, task_id: str, *, expected_revision: int | None = None) -> dict | None:
        """Compare and mutate atomically; None explicitly means latest state."""
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise TranslationError("invalid_revision", "A positive integer job_revision is required.")
        with self.transaction():
            current = self.task(task_id)
            if current is None:
                return None
            revision = current["job_revision"]
            if expected_revision is not None and expected_revision != revision:
                raise TranslationError("stale_job", "Translation job changed; check status again.")
            self.db.execute(
                "UPDATE tasks SET state='queued',phase='queued',error=NULL,"
                "revision=revision+1,updated=? WHERE id=? AND revision=? "
                "AND state IN ('failed','interrupted','cancelled')",
                (now(), task_id, revision),
            )
            return self.task(task_id)

    def cancel_task(self, task_id: str, *, expected_revision: int | None = None) -> dict | None:
        """Caller holds the publication lock; compare and cancel in one transaction."""
        if expected_revision is not None and (
            type(expected_revision) is not int or expected_revision < 1
        ):
            raise TranslationError("invalid_revision", "A positive integer job_revision is required.")
        with self.transaction():
            current = self.task(task_id)
            if current is None:
                return None
            revision = current["job_revision"]
            if expected_revision is not None and expected_revision != revision:
                raise TranslationError("stale_job", "Translation job changed; check status again.")
            self.db.execute(
                "UPDATE tasks SET state='cancelled',phase='cancelled',"
                "revision=revision+1,updated=? WHERE id=? AND revision=? "
                "AND state IN ('queued','running')",
                (now(), task_id, revision),
            )
            return self.task(task_id)
