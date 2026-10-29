"""Exact allowlisted offline child: synthetic race and crash receipt scenarios."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.services.official_data import bridge_module

sp = bridge_module("run_spending")
mode, control_path = sys.argv[1:]
control = json.loads(Path(control_path).read_text())
if mode == "create":
    Path(control["ready"]).write_text("ready")
    deadline = time.monotonic() + 10
    while not Path(control["go"]).exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    try:
        sp.create_authorization(control["manifest_path"], registry_dir=control["registry_dir"])
        print(json.dumps({"outcome": "created"}))
    except sp.SpendingStop as exc:
        print(json.dumps({"outcome": exc.code}))
    raise SystemExit(0)
binding = sp.binding_from_environment()
sp.activate_binding(binding)
request = control["request"]
marker = Path(control["marker"])


def send():
    db = sqlite3.connect(Path(binding["db_path"]).as_uri() + "?mode=ro", uri=True)
    reserved = db.execute("SELECT sum(reserved) FROM attempts").fetchone()[0]
    count = db.execute("SELECT count(*) FROM attempts WHERE state='unknown'").fetchone()[0]
    db.close()
    assert reserved >= 600_000 and count >= 1
    marker.write_text("committed-before-send")
    if mode == "after-send":
        os._exit(73)
    return object()


if mode == "before-commit":
    with sp._tx(binding, active=True) as (db, row, manifest):
        quote = sp._quote(manifest, "model-main", request)
        db.execute("INSERT INTO attempts(attempt_id,logical_hash,ordinal,generation,participant_id,stage_hash,route_id,request_sha256,envelope,reserved) VALUES('crash-attempt',?,1,?,?,?,'model-main',?,?,?)",
                   (sp.hash_payload("crash"), binding["generation"], binding["participant_id"], sp.hash_payload("research"), request["payload_sha256"], json.dumps(request), quote["reserved_max_microusd"]))
        os._exit(71)
if mode == "after-commit":
    claim = sp.reserve_and_claim(binding, "model-main", request, stage="research", logical_key="crash", attempt_id="crash-attempt")
    Path(control["claim_path"]).write_text(json.dumps(claim))
    os._exit(72)
if mode == "race":
    Path(control["ready"]).write_text("ready")
    deadline = time.monotonic() + 10
    while not Path(control["go"]).exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
try:
    sp.dispatch("model-main", request, send)
    print(json.dumps({"outcome": "sent"}))
except sp.SpendingStop as exc:
    print(json.dumps({"outcome": exc.code}))
