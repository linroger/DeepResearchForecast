"""Explicitly registered offline v2 contender/crash/resume process."""
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.services.official_data import bridge_module

sp = bridge_module("run_spending")
control = json.loads(Path(sys.argv[1]).read_text())
b = sp.binding_from_environment()
sp.activate_binding(b)


def send():
    db = sqlite3.connect(Path(b["db_path"]).as_uri() + "?mode=ro", uri=True)
    retained = db.execute("SELECT count(*),sum(reserved),sum(token_envelope_units),sum(catalog_attempt_units),sum(followup_attempt_units) FROM attempts WHERE scope_id=?", (b["active_scope_id"],)).fetchone()
    db.close()
    assert retained[0] >= 1 and retained[1] > 0
    Path(control["sent"]).write_text(json.dumps(list(retained)))
    if control["mode"] == "after-send":
        os._exit(83)
    return "synthetic-response"


def usage(_):
    return ({"kind": "provider_reported", "input_tokens": 1, "output_tokens": 1}
            if control["route"] == "model" else {"kind": "provider_reported", "tool_units": 1})


def dispatch():
    return sp.dispatch(control["route"], control["request"], send, usage=usage,
                       catalog_lookup_id=control.get("catalog_lookup_id"), followup_operation_id=control.get("followup_operation_id"))


if control["mode"] == "resume":
    with sp.run_lock(b):
        fresh = sp.resume_existing(b, control["proof"])
        sp.activate_binding(fresh)
        b = sp.begin_anchor_scope(fresh, session=control["session"])["binding"]
        try:
            dispatch()
            code = "sent"
        except sp.SpendingStop as exc:
            code = exc.code
        print(json.dumps({"outcome": code, "binding": b, "summary": sp.scope_summary(b)}))
    raise SystemExit(0)

if control["mode"] == "before-commit":
    with sp._tx(b, active=True) as (db, _, _):
        db.execute("INSERT INTO attempts(attempt_id,logical_hash,ordinal,generation,participant_id,stage_hash,route_id,request_sha256,envelope,reserved,scope_id,scope_session_id,admission_epoch,model_attempt_units,token_envelope_units) VALUES('crash',?,1,?,?,?,'model',?,?,600000,?,'session-1',?,1,600)",
                   (sp.hash_payload("crash"), b["generation"], b["participant_id"], sp.hash_payload("stage"), control["request"]["payload_sha256"], json.dumps(control["request"]), b["active_scope_id"], b["admission_epoch"]))
        os._exit(81)
if control["mode"] == "after-commit":
    sp.reserve_and_claim(b, control["route"], control["request"], stage="child", logical_key="crash",
                         catalog_lookup_id=control.get("catalog_lookup_id"), followup_operation_id=control.get("followup_operation_id"))
    os._exit(82)
if control["mode"] == "race":
    Path(control["ready"]).write_text("ready")
    deadline = time.monotonic() + 15
    while not Path(control["go"]).exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
try:
    dispatch()
    print(json.dumps({"outcome": "sent"}))
except sp.SpendingStop as exc:
    print(json.dumps({"outcome": exc.code}))
