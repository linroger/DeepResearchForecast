#!/usr/bin/env python3
"""Offline, read-only replay of world-v1 automatic modeling over saved research dossiers.

Subcommands:

  snapshot  copy the files world-v1 modeling reads (report, actors.json, ontology,
            prompt, engine) for the N newest completed pipelines into a new folder,
            so a replay never reads a live deployment while it writes.
  profiles  derive the replayed policy profiles from a pinned live policy file:
            ``before`` (as pinned), ``after`` (+ thinking disabled, + policy.modeler)
            and ``after_unpinned`` (+ thinking, no modeler envelope).
  replay    run the real preparation path of one source tree
            (WorldSimulationService.prepare_model -> generate_candidate ->
            build_compiler_messages -> strict modeler transport -> compile_world_spec)
            per dossier and scenario. Only the provider is scripted: the SDK client
            gets an httpx.MockTransport whose model builds a deterministic candidate
            from the request it receives. An audit hook refuses sockets, processes,
            reads under --deny roots and writes outside the work/output folders.
  compare   render a per-dossier Markdown table from a before and an after replay.

Every dossier ends as ``valid_spec`` or ``typed_gap`` (a WorldError code and the
stage that raised it); anything else is recorded as ``untyped_failure``.

Example (the 2026-10-18 evidence; see docs/handoff/world-engines-consolidation):

  PY=/path/to/backend/.venv/bin/python
  $PY -I -B backend/scripts/world_dossier_replay.py snapshot --pipelines DEPLOY/backend/uploads/pipelines \\
      --projects DEPLOY/backend/uploads/projects --newest 12 --to SNAP
  $PY -I -B backend/scripts/world_dossier_replay.py profiles --live-policy POLICY.json --out profiles.json
  $PY -I -B backend/scripts/world_dossier_replay.py replay --src FROZEN_TREE --dossiers SNAP --work NEW_DIR \\
      --out after.json --profiles profiles.json --runs after:compliant,after:repair --deny DEPLOY --allow-read DEPLOY/backend/.venv
  $PY -I -B backend/scripts/world_dossier_replay.py compare --before before.json --after after.json
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import inspect
import json
import os
import re
import shutil
import sys
import time
import traceback
import unicodedata
from datetime import date, timedelta
from pathlib import Path

HANDOFF_FILES = ("research_report.md", "actors.json", "ontology.json", "prediction_requirement.txt",
                 "meta.json", "sources.json", "actor_dossier.md")
REPAIR_MARKER = "Compiler feedback on your previous proposal"
STOP_SCENARIOS = {"content_filter", "truncate", "sensitive"}


def _sha(data):
    return hashlib.sha256(data if isinstance(data, bytes) else data.encode("utf-8")).hexdigest()


def _norm(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _within(path, roots):
    return any(path == root or path.startswith(root + os.sep) for root in roots)


def _guard(*, writable, denied, readable):
    writable = [os.path.realpath(p) for p in writable]
    denied = [os.path.realpath(p) for p in denied]
    readable = [os.path.realpath(p) for p in readable]

    def hook(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.bind"}:
            raise RuntimeError(f"replay guard: network refused ({event})")
        if event in {"subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.fork"}:
            raise RuntimeError(f"replay guard: process creation refused ({event})")
        if event != "open" or isinstance(args[0], int) or args[0] is None:
            return
        mode = args[1] if len(args) > 1 else "r"
        if isinstance(mode, int):
            writing = bool(mode & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
        else:
            writing = isinstance(mode, str) and any(flag in mode for flag in "wax+")
        real = os.path.realpath(os.fsdecode(args[0]))
        if _within(real, denied) and not (not writing and _within(real, readable)):
            raise RuntimeError(f"replay guard: refused path {real}")
        if writing and not _within(real, writable):
            raise RuntimeError(f"replay guard: write outside the work folders refused: {real}")

    sys.addaudithook(hook)


# --------------------------------------------------------------------------- snapshot

def snapshot(args):
    pipelines, target = Path(args.pipelines), Path(args.to)
    target.mkdir(parents=True, exist_ok=False)
    rows = []
    for state_path in pipelines.glob("pipe_*/pipeline_state.json"):
        handoff = state_path.parent / "handoff"
        if not ((handoff / "research_report.md").is_file() and (handoff / "actors.json").is_file()):
            continue
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("status") == "completed" and state.get("mode", "full") == "full":
            rows.append((state.get("created_at") or "", state_path.parent.name, state.get("project_id")))
    rows.sort(reverse=True)
    chosen = [row for row in rows if not args.ids or row[1] in args.ids][: args.newest]
    manifest = {"takenAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": str(pipelines), "dossiers": []}
    for created, pipeline_id, project_id in chosen:
        source, dest = pipelines / pipeline_id, target / pipeline_id
        (dest / "handoff").mkdir(parents=True)
        files = {"pipeline_state.json": source / "pipeline_state.json"}
        files.update({f"handoff/{name}": source / "handoff" / name for name in HANDOFF_FILES})
        if args.projects and project_id:
            files["project/project.json"] = Path(args.projects) / project_id / "project.json"
        digests = {}
        for relative, path in files.items():
            if path.is_file():
                (dest / relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, dest / relative)
                digests[relative] = _sha((dest / relative).read_bytes())
        manifest["dossiers"].append({"pipeline": pipeline_id, "createdAt": created, "files": digests})
    (target / "snapshot_manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("\n".join(f"{row['createdAt']}  {row['pipeline']}" for row in manifest["dossiers"]))


# --------------------------------------------------------------------------- profiles

def profiles(args):
    live = json.loads(Path(args.live_policy).read_text(encoding="utf-8"))
    policy = live["policy"]
    before = {"policy": copy.deepcopy(policy), "forecastEffect": "diagnostic_only",
              "limits": {"maxTokens": live["maxTokensPerCase"], "maxCostUsd": "5",
                         "maxOutputTokens": live["maxOutputTokens"]}}
    after_policy = copy.deepcopy(policy)
    after_policy.pop("reasoningEffort", None)  # cannot be combined with thinking: disabled
    after_policy["thinking"] = "disabled"
    after_policy["modeler"] = {"maxInputTokens": args.modeler_input, "maxOutputTokens": args.modeler_output,
                               "timeoutSeconds": args.modeler_timeout}
    after = {"policy": after_policy, "forecastEffect": "diagnostic_only",
             "limits": {"maxTokens": args.max_tokens, "maxCostUsd": args.max_cost,
                        "maxOutputTokens": live["maxOutputTokens"]}}
    unpinned = copy.deepcopy(after)
    unpinned["policy"].pop("modeler")
    Path(args.out).write_text(json.dumps({"before": before, "after": after, "after_unpinned": unpinned}, indent=1),
                              encoding="utf-8")


# --------------------------------------------------------------------------- scripted model

def flat_claims(payload):
    """Claims as flat rows, for the grouped (by actor) and the older flat payload."""
    rows = []
    for item in payload.get("claims") or []:
        if isinstance(item, dict) and isinstance(item.get("claims"), list):
            rows.extend({**row, "actorId": item["actorId"]} for row in item["claims"])
        else:
            rows.append(item)
    return rows


def _quote(report):
    """First prose line of the report (>= 40 chars, no table or heading), cut to <= 160 chars."""
    for line in report.splitlines():
        text = line.strip()
        if len(text) >= 40 and not text.startswith(("#", "|", ">", "-", "*", "<", "!", "[")) and "|" not in text:
            return text[:160].rstrip()
    return report.strip()[:160]


def _periods(document):
    raw = document.get("as_of_date") if isinstance(document, dict) else None
    start = (date.fromisoformat(raw.strip()) if isinstance(raw, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw.strip())
             else date(2026, 11, 1))
    periods = []
    for _ in range(3):
        end = start + timedelta(days=30)
        periods.append({"start": f"{start.isoformat()}T00:00:00Z", "end": f"{end.isoformat()}T00:00:00Z"})
        start = end
    return periods


def scripted_candidate(payload, *, defect=None):
    """What a compliant model returns under the request's contract.

    Actors cite their own claims (identity from role/description/stance, up to
    three sourced objectives, other profile fields omitted so the compiler fills
    them), one analyst metric cites the report by quote, and numbers are declared
    assumptions. ``defect="paraphrase"`` rewords one objective, a typical model
    slip, so the repair path runs.
    """
    claims, roster = flat_claims(payload), payload.get("actors") or []
    limits = payload.get("limits") if isinstance(payload.get("limits"), dict) else {}
    chosen = roster[:limits["maxActors"] if type(limits.get("maxActors")) is int else 20]
    ids = [row["actorId"] for row in chosen]
    by_actor = {}
    for claim in claims:
        by_actor.setdefault(claim["actorId"], []).append(claim)

    def text_of(claim):
        if "text" in claim:
            return claim["text"]
        inner = claim.get("claim")
        return inner.get("claim") if isinstance(inner, dict) else inner

    actors, paraphrased = [], False
    for row in chosen:
        own = [claim for claim in by_actor.get(row["actorId"], []) if claim.get("actorAllowed")]
        identity = next((claim for claim in own if claim.get("claimId") in {"role", "description", "stance"}
                         or claim.get("dimension") in {"role", "description", "stance"}), own[0] if own else None)
        actor = {"actorId": row["actorId"], "name": row["name"], "capabilities": ["wait", "statement"],
                 "controlledAccounts": [],
                 "basis": ({"kind": "source_claim", "refs": [{"actorId": row["actorId"], "claimId": identity["claimId"]}]}
                           if identity else {"kind": "scenario_assumption", "refs": ["replay/cast"]})}
        goals = [claim for claim in own if claim.get("profileField") == "objectives"
                 or claim.get("dimension") == "motivations"][:3]
        if goals:
            actor["objectives"] = []
            for goal in goals:
                text = text_of(goal)
                if defect == "paraphrase" and not paraphrased:
                    text, paraphrased = "In short: " + text, True
                actor["objectives"].append({"text": text, "basis": {
                    "kind": "source_claim", "refs": [{"actorId": row["actorId"], "claimId": goal["claimId"]}]}})
        actors.append(actor)
    menu = {"kind": "scenario_assumption", "refs": ["replay/menu"]}
    return {
        "periods": _periods(payload.get("actorCandidatesForModelerOnly")),
        "actors": actors,
        "initialState": {"accounts": {}, "rules": {}, "relations": {}, "metrics": {
            "scenario_index": {"kind": "quantity", "unit": "index", "value": "100", "visibility": {"kind": "public"},
                               "basis": {"kind": "scenario_assumption", "refs": ["replay/index"]},
                               "description": "Scenario tension index, a declared modelling convention."},
            "research_anchor": {"kind": "category", "unit": "text", "value": None, "visibility": {"kind": "analyst"},
                                "basis": {"kind": "report_excerpt", "refs": [{"quote": _quote(payload.get("report") or "")}]},
                                "description": "Analyst-only anchor to the research report."}}},
        "actionCatalog": [
            {"templateId": "wait", "kind": "wait", "actorIds": ids, "description": "Wait until the next decision period.",
             "parameters": {}, "inputs": {}, "basis": copy.deepcopy(menu), "visibility": {"kind": "public"}},
            {"templateId": "statement", "kind": "message", "actorIds": ids,
             "description": "Make a public statement to the other actors.", "parameters": {"recipientIds": ids},
             "inputs": {"text": {"type": "string", "required": True, "max": "600"}},
             "basis": copy.deepcopy(menu), "visibility": {"kind": "public"}},
        ],
        "assumptions": [
            {"assumptionId": "replay/cast", "visibility": {"kind": "public"},
             "description": "Actors without citable research claims are included as scenario actors."},
            {"assumptionId": "replay/menu", "visibility": {"kind": "public"},
             "description": "Each actor may wait or make a public statement in each period."},
            {"assumptionId": "replay/index", "visibility": {"kind": "public"},
             "description": "The scenario index starts at 100 by convention; it is not a sourced value."},
        ],
        "scheduledEvents": [], "flows": [],
    }


class ScriptedProvider:
    """httpx.MockTransport handler: one scripted provider behaviour per scenario."""

    def __init__(self, scenario, model):
        self.scenario, self.model, self.requests = scenario, model, []

    def __call__(self, request):
        import httpx
        body = json.loads(request.content.decode("utf-8"))
        system, user = body["messages"][0]["content"], body["messages"][1]["content"]
        repair = REPAIR_MARKER in system
        cap = body.get("max_completion_tokens", body.get("max_tokens"))
        self.requests.append({"bytes": len(request.content), "maxOutput": cap, "thinking": body.get("thinking"),
                              "reasoningEffort": body.get("reasoning_effort"), "repair": repair,
                              "systemSha256": _sha(system)[:16], "userSha256": _sha(user)[:16]})
        if self.scenario == "content_filter":
            return httpx.Response(400, json={"error": {"code": "1301", "message": "replay: content filtered"}})
        candidate = scripted_candidate(json.loads(user), defect="paraphrase" if self.scenario == "repair" and not repair else None)
        content = json.dumps(candidate, ensure_ascii=False)
        completion, prompt, finish = max(1, len(content.encode("utf-8")) // 3), max(1, len(request.content) // 4), "stop"
        if self.scenario == "truncate":
            finish = "length"
        elif self.scenario == "sensitive":
            finish, content = "sensitive", ""
        if cap is not None and completion > cap:
            finish, completion = "length", cap  # the reply would not fit the pinned output cap
        return httpx.Response(200, json={
            "id": "replay", "object": "chat.completion", "created": 0, "model": self.model,
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}})


# --------------------------------------------------------------------------- replay

def load_dossier(path):
    handoff = path / "handoff"
    report_bytes, actors_bytes = (handoff / "research_report.md").read_bytes(), (handoff / "actors.json").read_bytes()
    report, actors = report_bytes.decode("utf-8"), json.loads(actors_bytes)
    meta = json.loads((handoff / "meta.json").read_text(encoding="utf-8")) if (handoff / "meta.json").exists() else {}
    state = json.loads((path / "pipeline_state.json").read_text(encoding="utf-8"))
    project_path = path / "project" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8")) if project_path.exists() else {}
    generation = "research_" + _sha(json.dumps({"report": report, "actors": actors}, ensure_ascii=False,
                                               sort_keys=True, separators=(",", ":"), allow_nan=False))
    rows = actors.get("actors") if isinstance(actors, dict) else actors
    return {"pipeline": path.name, "report": report, "actors": actors, "generation": generation,
            # An unsealed dossier can only compile as v3; older runs predate the engine label.
            "engine": meta.get("engine") if meta.get("engine") in {"v3", "linear"} else "v3",
            "prompt": state.get("prompt") or "", "ontology": project.get("ontology"),
            "actorCount": len(rows) if isinstance(rows, list) else None,
            "inputs": {"research_report.md": _sha(report_bytes), "actors.json": _sha(actors_bytes)}}


def summarize(spec, denied, world):
    from collections import Counter
    items = Counter(f"{field}:{item['basis']['kind']}" for actor in spec["actors"]
                    for field in ("objectives", "values", "incentives", "constraints", "beliefs") for item in actor[field])
    excerpts = [ref for section in spec["initialState"].values() for record in section.values()
                if record.get("basis", {}).get("kind") == "report_excerpt" for ref in record["basis"]["refs"]]
    snapshot = world["initial_snapshot"](spec)
    leaks = 0
    for actor in spec["actors"]:
        text = _norm(world["canonical_json"](world["build_observation"](spec, snapshot, actor["actorId"], 1)))
        leaks += sum(1 for value in denied if len(value) >= 16 and value in text)
    return {"actors": len(spec["actors"]), "evidenceGrades": dict(Counter(a["evidenceGrade"] for a in spec["actors"])),
            "profileItems": dict(items), "reportExcerpts": excerpts, "deniedTextInObservations": leaks,
            "specSha256": world["digest"](spec)}


def replay_one(dossier, profile, scenario, root, world):
    from app.services.world_simulation.contracts import WorldError
    from app.services.world_simulation.service import WorldSimulationService
    result = {"pipeline": dossier["pipeline"], "scenario": scenario, "inputs": dossier["inputs"]}
    provider = ScriptedProvider(scenario, profile["policy"]["model"])
    world["install"](provider)
    sim_id = "sim_replay_" + dossier["pipeline"].split("_", 1)[1] + "_" + scenario
    kwargs = dict(research_report=dossier["report"], research_generation_id=dossier["generation"],
                  research_engine=dossier["engine"], actor_bundle=dossier["actors"],
                  ontology=dossier["ontology"], simulation_requirement=dossier["prompt"])

    def prepare():
        return WorldSimulationService.prepare_model(sim_id, raw_spec=None, root=root,
                                                    policy_spec=copy.deepcopy(profile), **kwargs)
    stage = "build_messages"
    try:
        build = world["build_compiler_messages"]
        extra = {"max_actors": profile["limits"].get("maxActors")} if "max_actors" in inspect.signature(build).parameters else {}
        messages = build(**kwargs, **extra)
        claims = flat_claims(json.loads(messages[1]["content"]))
        result.update(userBytes=len(messages[1]["content"].encode("utf-8")),
                      # What the strict transport counts (one token per serialized byte), before overhead.
                      requestBytes=len(json.dumps(messages, ensure_ascii=False, sort_keys=True,
                                                  separators=(",", ":")).encode("utf-8")),
                      claims=len(claims), actorAllowedClaims=sum(1 for c in claims if c.get("actorAllowed")))
        denied = [_norm(c.get("text") or (c.get("claim") or {}).get("claim") or "") for c in claims if not c.get("actorAllowed")]
        stage = "prepare_model"
        result.update(status="valid_spec", summary=summarize(prepare()["spec"], denied, world))
    except WorldError as error:
        result.update(status="typed_gap", code=error.code, message=str(error), details=error.details, stage=stage)
    except Exception as error:  # noqa: BLE001 - recorded, never hidden
        result.update(status="untyped_failure", type=type(error).__name__, message=str(error)[:500], stage=stage,
                      traceback=traceback.format_exc()[-3000:])
    ledger = Path(root) / sim_id / "world_modeling_receipts.json"
    if ledger.exists():
        result["attempts"] = [{key: row.get(key) for key in ("number", "kind", "status", "errorCode", "usage")}
                              for row in json.loads(ledger.read_text(encoding="utf-8")).get("attempts", [])]
    if scenario in STOP_SCENARIOS and result["status"] == "typed_gap" and result["stage"] == "prepare_model":
        sent = len(provider.requests)
        try:
            prepare()
            result["resume"] = {"status": "valid_spec"}
        except WorldError as error:
            result["resume"] = {"status": "typed_gap", "code": error.code}
        except Exception as error:  # noqa: BLE001
            result["resume"] = {"status": "untyped_failure", "type": type(error).__name__}
        result["resume"]["newRequests"] = len(provider.requests) - sent
    result["requests"] = provider.requests
    return result


def replay(args):
    work, src, out = Path(args.work).resolve(), Path(args.src).resolve(), Path(args.out).resolve()
    work.mkdir(parents=True, exist_ok=False)
    os.environ["DRF_TEST_PROCESS"] = "1"  # never load a .env
    _guard(writable=[str(work), str(src), str(out.parent)], denied=args.deny or [], readable=args.allow_read or [])
    sys.path.insert(0, str(src / "backend"))
    import httpx
    from openai import OpenAI
    import app.services.world_simulation.policy as policy_module
    from app.services.world_simulation.compiler import build_compiler_messages
    from app.services.world_simulation.contracts import canonical_json, digest, initial_snapshot
    from app.services.world_simulation.observations import build_observation

    current = {}

    class ReplayModeler(policy_module.StrictHTTPModeler):
        def __init__(self, spec, *, client=None, pricing=None):
            http = httpx.Client(transport=httpx.MockTransport(current["provider"]), follow_redirects=False, trust_env=False)
            super().__init__(spec, client=OpenAI(api_key="replay-offline", base_url=spec["policy"]["baseUrl"],
                                                 max_retries=0, http_client=http), pricing=pricing)

    policy_module.StrictHTTPModeler = ReplayModeler
    world = {"build_compiler_messages": build_compiler_messages, "canonical_json": canonical_json, "digest": digest,
             "initial_snapshot": initial_snapshot, "build_observation": build_observation,
             "install": lambda provider: current.update(provider=provider)}
    profile_set = json.loads(Path(args.profiles).read_text(encoding="utf-8"))
    dossiers = [load_dossier(path) for root in args.dossiers for path in sorted(Path(root).iterdir())
                if (path / "handoff" / "research_report.md").exists()]
    results = {"src": str(src), "startedAt": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "profiles": profile_set, "runs": {}}
    for item in args.runs.split(","):
        name, scenario = item.split(":")
        root = work / name / scenario
        root.mkdir(parents=True)
        rows = []
        for dossier in dossiers:
            started = time.monotonic()
            row = replay_one(dossier, profile_set[name], scenario, root, world)
            row.update(seconds=round(time.monotonic() - started, 3), engine=dossier["engine"], actorCount=dossier["actorCount"])
            rows.append(row)
        results["runs"][item] = rows
    results["finishedAt"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    for key, rows in results["runs"].items():
        counts = {}
        for row in rows:
            counts[row["status"]] = counts.get(row["status"], 0) + 1
        print(key, counts)


# --------------------------------------------------------------------------- compare

def _outcome(row):
    if row["status"] == "valid_spec":
        attempts = row.get("attempts") or []
        return f"valid spec ({len(attempts)} request{'s' if len(attempts) != 1 else ''})"
    if row["status"] == "typed_gap":
        return f"typed gap `{row['code']}` at {row['stage']}"
    return f"UNTYPED `{row.get('type')}` at {row.get('stage')}"


def compare(args):
    before = json.loads(Path(args.before).read_text(encoding="utf-8"))["runs"][args.before_run]
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))["runs"][args.after_run]
    by_pipeline = {row["pipeline"]: row for row in after}
    print("| Pipeline | Actors | Before | After | Claims (actor-allowed) | Request bytes before → after |")
    print("|---|---|---|---|---|---|")
    for row in before:
        new = by_pipeline.get(row["pipeline"], {"status": "missing", "pipeline": row["pipeline"]})
        print(f"| `{row['pipeline']}` | {row.get('actorCount')} | {_outcome(row)} | {_outcome(new)} | "
              f"{new.get('claims')} ({new.get('actorAllowedClaims')}) | {row.get('requestBytes')} → {new.get('requestBytes')} |")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--pipelines", required=True)
    s.add_argument("--projects")
    s.add_argument("--to", required=True)
    s.add_argument("--newest", type=int, default=12)
    s.add_argument("--ids", nargs="*")
    p = sub.add_parser("profiles")
    p.add_argument("--live-policy", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--modeler-input", type=int, default=400000)
    p.add_argument("--modeler-output", type=int, default=32768)
    p.add_argument("--modeler-timeout", type=int, default=900)
    p.add_argument("--max-tokens", type=int, default=3000000)
    p.add_argument("--max-cost", default="25")
    r = sub.add_parser("replay")
    r.add_argument("--src", required=True)
    r.add_argument("--dossiers", action="append", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--out", required=True)
    r.add_argument("--profiles", required=True)
    r.add_argument("--runs", required=True, help="comma list of profile:scenario "
                   "(scenarios: compliant, repair, content_filter, truncate, sensitive)")
    r.add_argument("--deny", action="append", help="refuse every open under this root")
    r.add_argument("--allow-read", action="append", help="read-only exception inside a denied root")
    c = sub.add_parser("compare")
    c.add_argument("--before", required=True)
    c.add_argument("--after", required=True)
    c.add_argument("--before-run", default="before:compliant")
    c.add_argument("--after-run", default="after:compliant")
    args = parser.parse_args()
    {"snapshot": snapshot, "profiles": profiles, "replay": replay, "compare": compare}[args.command](args)


if __name__ == "__main__":
    main()
