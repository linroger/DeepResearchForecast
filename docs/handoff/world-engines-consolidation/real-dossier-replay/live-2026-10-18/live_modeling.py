"""One owner-approved paid world-v1 modeling run (modeling only, no actor rounds).

Runs WorldSimulationService.prepare_model on one dossier snapshot with the real
strict GLM transport. Guard: DNS only for the pinned provider host, no process
creation, deployment reads limited to its interpreter and .env, writes only to
the run folder. Prints and stores no credential.
"""
import json
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path

SRC, DOSSIER, PROFILES, WORK = (Path(arg).resolve() for arg in sys.argv[1:5])
PROFILE = sys.argv[5] if len(sys.argv) > 5 else "after"
DEPLOY = "/Users/rogerlin/Downloads/DeepResearchForecast/"
ENV_FILE = DEPLOY + ".env"
ALLOWED_HOST = "open.bigmodel.cn"

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ENV_FILE, override=True)  # values stay inside this process
os.environ["DRF_TEST_PROCESS"] = "1"  # the app itself loads no .env


def guard():
    writable = [str(WORK), str(SRC)]

    def hook(event, args):
        if event == "socket.getaddrinfo" and args[0] not in (ALLOWED_HOST, None):
            raise RuntimeError(f"live guard: DNS refused for {args[0]!r}")
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
            raise RuntimeError(f"live guard: process creation refused ({event})")
        if event != "open" or isinstance(args[0], int) or args[0] is None:
            return
        mode = args[1] if len(args) > 1 else "r"
        writing = (bool(mode & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
                   if isinstance(mode, int) else any(flag in str(mode) for flag in "wax+"))
        real = os.path.realpath(os.fsdecode(args[0]))
        if real.startswith(DEPLOY) and not (not writing and (real.startswith(DEPLOY + "backend/.venv/")
                                                            or real == ENV_FILE)):
            raise RuntimeError(f"live guard: deployment path refused: {real}")
        if writing and not any(real == root or real.startswith(root + os.sep) for root in writable):
            raise RuntimeError(f"live guard: write refused: {real}")

    sys.addaudithook(hook)


def main():
    WORK.mkdir(parents=True, exist_ok=False)
    guard()
    sys.path.insert(0, str(SRC / "backend"))
    from app.services.world_simulation.contracts import WorldError, canonical_json, digest, initial_snapshot
    from app.services.world_simulation.observations import build_observation
    from app.services.world_simulation.service import WorldSimulationService

    handoff = DOSSIER / "handoff"
    report = (handoff / "research_report.md").read_text(encoding="utf-8")
    actors = json.loads((handoff / "actors.json").read_text(encoding="utf-8"))
    state = json.loads((DOSSIER / "pipeline_state.json").read_text(encoding="utf-8"))
    project = json.loads((DOSSIER / "project" / "project.json").read_text(encoding="utf-8"))
    generation = "research_" + __import__("hashlib").sha256(json.dumps(
        {"report": report, "actors": actors}, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    profile = json.loads(PROFILES.read_text(encoding="utf-8"))[PROFILE]
    sim_id = "sim_live_" + DOSSIER.name.split("_", 1)[1]
    root = WORK / "sims"
    root.mkdir()
    out = {"pipeline": DOSSIER.name, "simulationId": sim_id, "profile": PROFILE, "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    started = time.monotonic()
    try:
        prepared = WorldSimulationService.prepare_model(
            sim_id, raw_spec=None, root=root, policy_spec=profile, research_report=report,
            research_generation_id=generation, research_engine="v3", actor_bundle=actors,
            ontology=project.get("ontology"), simulation_requirement=state.get("prompt") or "")
        spec = prepared["spec"]
        out["status"] = "valid_spec"
        items = Counter(f"{field}:{item['basis']['kind']}" for actor in spec["actors"]
                        for field in ("objectives", "values", "incentives", "constraints", "beliefs") for item in actor[field])
        snapshot = initial_snapshot(spec)
        observations = [canonical_json(build_observation(spec, snapshot, actor["actorId"], 1)) for actor in spec["actors"]]
        bases = Counter(record["basis"]["kind"] for section in spec["initialState"].values() for record in section.values())
        out["summary"] = {
            "actors": len(spec["actors"]), "actorNames": [actor["name"] for actor in spec["actors"]],
            "evidenceGrades": dict(Counter(actor["evidenceGrade"] for actor in spec["actors"])),
            "profileItems": dict(items), "periods": len(spec["periods"]), "asOf": spec["asOf"], "horizon": spec["horizon"],
            "initialState": {section: len(records) for section, records in spec["initialState"].items()},
            "initialStateBases": dict(bases),
            "actionKinds": dict(Counter(template["kind"] for template in spec["actionCatalog"])),
            "scheduledEvents": len(spec["scheduledEvents"]), "flows": len(spec["flows"]),
            "assumptions": len(spec["assumptions"]),
            "maxObservationBytes": max(len(text.encode("utf-8")) for text in observations),
            "specSha256": digest(spec), "manifestSha256": prepared["manifest_sha256"],
            "modelPreparation": spec["sourceBindings"].get("modelPreparation", {}).get("used"),
        }
    except WorldError as error:
        out.update(status="typed_gap", code=error.code, message=str(error), details=error.details)
    except Exception as error:  # noqa: BLE001 - recorded, never hidden
        out.update(status="untyped_failure", type=type(error).__name__, traceback=traceback.format_exc()[-4000:])
    out["seconds"] = round(time.monotonic() - started, 1)
    ledger_path = root / sim_id / "world_modeling_receipts.json"
    if ledger_path.exists():
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        out["attempts"] = [{key: row.get(key) for key in ("number", "kind", "status", "errorCode", "errorMessage", "reservation", "usage", "rejection")}
                           for row in ledger["attempts"]]
    (WORK / "live.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({key: out.get(key) for key in ("status", "code", "message", "details", "seconds", "attempts")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
