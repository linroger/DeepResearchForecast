"""Allowlisted child for parent adoption of real retained scope transitions."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from app.services.official_data import bridge_module

sp = bridge_module("run_spending")
control_path = Path(sys.argv[1])
control = json.loads(control_path.read_text())
binding = sp.binding_from_environment()
sp.activate_binding(binding)
entered = sp.begin_anchor_scope(binding, session=control["session"])
packet = {"schema_version": "world-anchor-scope-handoff/v1",
          "receipts": [entered["transition_receipt"]], "completion": None}
if control["complete"]:
    budget = sp.seal_anchor_budget(entered["binding"], seal={
        "session_id": control["session"]["session_id"],
        "participants_exited_sha256": sp.hash_payload([]),
        "workers_joined_sha256": sp.hash_payload("no-workers")})
    completion = {"session_id": budget["session_id"],
        "artifact_manifest_sha256": sp.hash_payload("synthetic-output-manifest"),
        "budget_receipt_sha256": sp.hash_payload(budget), "result": "non_ready"}
    exited = sp.finish_anchor_scope(entered["binding"], completion=completion)
    packet["receipts"].append(exited["transition_receipt"])
    packet["completion"] = completion
(control_path.parent / "world_anchor_scope_handoff.json").write_text(json.dumps(packet))
print(json.dumps({"completed": control["complete"]}))
