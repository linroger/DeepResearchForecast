"""Guarded process fixture: both processes submit the same durable operation."""
import json
from pathlib import Path
import sys
import time

from app.config import Config
from app.services.translation.scheduler import register_handler, submit, status, stop_schedulers

root = Path(sys.argv[1])
Config.UPLOAD_FOLDER = str(root / "uploads")


def handler(payload):
    # SQLite below is the only side effect and makes duplicate execution visible.
    import sqlite3
    with sqlite3.connect(root / "effects.sqlite3") as db:
        db.execute("CREATE TABLE IF NOT EXISTS effects(value TEXT)")
        db.execute("INSERT INTO effects VALUES('executed')")
    time.sleep(.2)
    return {"complete": True}


register_handler("two-process", handler)
result = submit("two-process", {"kind": "test", "ref_id": "same"}, {"source": "same"})
deadline = time.monotonic() + 10
while time.monotonic() < deadline:
    result = status(result["job_id"])
    if result["job_state"] == "completed":
        break
    time.sleep(.05)
print(json.dumps({"job_id": result["job_id"], "state": result["job_state"]}), flush=True)
stop_schedulers()
if result["job_state"] != "completed":
    raise SystemExit(2)
