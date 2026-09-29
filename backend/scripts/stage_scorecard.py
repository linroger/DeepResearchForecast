"""EVAL-15: offline stage-scorecard scoring and backfill.

Scores existing pipelines with the same deterministic projection the
orchestrator writes at every terminal state (app/services/stage_scorecard.py).
Runs that were reconciled as orphans at startup never reach the ``_run``
finally block, so this CLI is how they (and pre-EVAL-15 runs) get a sidecar.
Offline: it reads files under uploads/ only - no network, no LLM, no Flask.

Usage:
    python scripts/stage_scorecard.py score --pipeline <pipeline_id> [--thresholds FILE] [-o [--force]]
    python scripts/stage_scorecard.py score --all [--thresholds FILE] [-o [--force]]

``--pipeline`` prints the full scorecard JSON; ``--all`` scores every terminal
pipeline (completed / failed / cancelled) and prints a compact summary per
run.  ``-o`` / ``--write`` also writes ``<pipeline_dir>/stage_scorecard.json``.
The runtime_gates block records the gate values the report's final_audit.json
recorded and, for the rest, the current configuration (``source:
"process_config"``, ``scored_by: "backfill"``), since run.json does not pin the
gate values of the original run.

``-o`` is a backfill: a sidecar the pipeline wrote itself (``scored_by:
"pipeline"``) for its current attempt (same ``identity.task_id`` and
``status`` as the pipeline state) is the only record of the process gates that
run was published under, so it is kept and reported as skipped.  A
pipeline-authored sidecar from an earlier attempt (a later attempt ran with
STAGE_SCORECARD_ENABLED=false, or died as an orphan) is stale and rewritten.
``--force`` rewrites a current one too.  A rewrite keeps the replaced
pipeline-authored record (``scored_by`` / ``task_id`` / ``status`` /
``runtime_gates``) under ``identity.previous``, and any rewrite carries an
existing ``identity.previous`` forward.

Exit codes: 0 scored (a kept pipeline-authored sidecar is a skip, not an
error), 1 a pipeline could not be scored, 2 usage error.
The scorecard is never a gate: failed contracts do not change the exit code.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

# Import backend's app package regardless of the calling cwd (same as resolution_monitor.py).
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services import stage_scorecard as scorecard  # noqa: E402
from app.services.pipeline_orchestrator import PipelineManager  # noqa: E402
from app.utils.atomic import write_json_atomic  # noqa: E402

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
PIPELINE_AUTHORED = "pipeline-authored sidecar"


def _render_json(payload: Any) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False)


def _error_text(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"[:300]


def _terminal_pipeline_ids() -> tuple[list[str], list[dict], list[dict]]:
    """(terminal pipeline ids, skipped rows, error rows) under PIPELINE_DATA_DIR, sorted by id."""
    root = Config.PIPELINE_DATA_DIR
    if not os.path.isdir(root):
        return [], [], []
    ids: list[str] = []
    skipped: list[dict] = []
    errors: list[dict] = []
    for name in sorted(os.listdir(root)):
        if not PipelineManager._PIPELINE_ID_RE.fullmatch(name):
            continue
        try:
            data = PipelineManager.load(name)
        except Exception as exc:  # noqa: BLE001 — one corrupt state never aborts the backfill
            errors.append({"pipeline_id": name, "error": _error_text(exc)})
            continue
        if not isinstance(data, dict):
            skipped.append({"pipeline_id": name, "reason": "no readable pipeline_state.json"})
        elif PipelineManager.is_incompatible(data) is not None:
            skipped.append({"pipeline_id": name, "reason": "newer state schema"})
        elif data.get("status") in TERMINAL_STATUSES:
            ids.append(name)
        else:
            skipped.append({"pipeline_id": name, "reason": f"status {data.get('status')!r}"})
    return ids, skipped, errors


def _existing_sidecar(pipeline_id: str) -> Optional[dict]:
    """The sidecar already on disk, or None when it is absent or unparseable."""
    try:
        with open(scorecard.sidecar_path(pipeline_id), encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _identity(card: Optional[dict]) -> dict:
    identity = card.get("identity") if isinstance(card, dict) else None
    return identity if isinstance(identity, dict) else {}


def _pipeline_record(existing: Optional[dict]) -> Optional[dict]:
    """The pipeline-authored gate record an existing sidecar holds (itself or identity.previous)."""
    identity = _identity(existing)
    if identity.get("scored_by") == "pipeline":
        return {"scored_by": "pipeline", "task_id": identity.get("task_id"),
                "status": identity.get("status"),
                "runtime_gates": existing.get("runtime_gates")}
    previous = identity.get("previous")
    return previous if isinstance(previous, dict) else None


def _is_current_pipeline_sidecar(existing: Optional[dict], inputs: dict) -> bool:
    """True when the pipeline wrote the sidecar for the attempt its state now describes."""
    identity = _identity(existing)
    return (identity.get("scored_by") == "pipeline"
            and identity.get("task_id") == inputs.get("task_id")
            and identity.get("status") == inputs.get("status"))


def _score(pipeline_id: str, thresholds: Optional[dict], *, write: bool,
           force: bool) -> tuple[Optional[dict], Optional[str]]:
    """(scorecard, skip reason).  A write never silently replaces pipeline-authored evidence."""
    inputs = scorecard.resolve_inputs(pipeline_id)
    existing = _existing_sidecar(pipeline_id) if write else None
    if write and not force and _is_current_pipeline_sidecar(existing, inputs):
        return None, PIPELINE_AUTHORED
    card = scorecard.build_stage_scorecard(inputs, thresholds)
    if write:
        previous = _pipeline_record(existing)
        if previous is not None:
            card["identity"]["previous"] = previous
        write_json_atomic(scorecard.sidecar_path(pipeline_id), card, allow_nan=False)
    return card, None


def _summary_row(card: dict, written: Optional[str]) -> dict:
    row = {
        "pipeline_id": card["identity"]["pipeline_id"],
        "status": card["identity"]["status"],
        "passed": scorecard.summarize_checks(card),
        "failed": {stage: check["failed"] for stage, check in card["checks"].items()
                   if check["failed"]},
        "relaxed_gates": sorted(name for name, gate in card["runtime_gates"].items()
                                if gate.get("relaxed")),
    }
    if written:
        row["written"] = written
    return row


def _cmd_score(args: argparse.Namespace) -> int:
    if args.force and not args.write:
        print("--force only applies with -o/--write", file=sys.stderr)
        return 2
    thresholds: Optional[dict] = None
    if args.thresholds:
        try:
            thresholds = scorecard.load_thresholds(args.thresholds)
        except (OSError, ValueError) as exc:
            print(f"invalid thresholds file {args.thresholds}: {exc}", file=sys.stderr)
            return 2
    if args.pipeline:
        try:
            card, skip = _score(args.pipeline, thresholds, write=args.write, force=args.force)
            if skip:
                output = _render_json({"pipeline_id": args.pipeline, "skipped": skip})
            elif args.write:
                output = _render_json(_summary_row(card, scorecard.sidecar_path(args.pipeline)))
            else:
                output = _render_json(card)
        except Exception as exc:  # noqa: BLE001 — report any failure as "could not be scored"
            print(f"cannot score {args.pipeline}: {_error_text(exc)}", file=sys.stderr)
            return 1
        if skip:
            print(f"kept {scorecard.sidecar_path(args.pipeline)} ({skip}); "
                  "pass --force to rewrite it", file=sys.stderr)
        print(output)
        return 0

    ids, skipped, errors = _terminal_pipeline_ids()
    rows: list[dict] = []
    for pipeline_id in ids:
        try:
            card, skip = _score(pipeline_id, thresholds, write=args.write, force=args.force)
        except Exception as exc:  # noqa: BLE001 — one bad pipeline never aborts the backfill
            errors.append({"pipeline_id": pipeline_id, "error": _error_text(exc)})
            continue
        if skip:
            skipped.append({"pipeline_id": pipeline_id, "reason": skip})
            continue
        rows.append(_summary_row(card, scorecard.sidecar_path(pipeline_id) if args.write else None))
    print(_render_json({"count": len(rows), "pipelines": rows,
                        "skipped": sorted(skipped, key=lambda row: row["pipeline_id"]),
                        "errors": sorted(errors, key=lambda row: row["pipeline_id"])}))
    return 1 if errors else 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    score = sub.add_parser("score", help="score pipelines with the stage-scorecard/v1 projection")
    target = score.add_mutually_exclusive_group(required=True)
    target.add_argument("--pipeline", help="one pipeline id (pipe_...)")
    target.add_argument("--all", action="store_true", help="every terminal pipeline")
    score.add_argument("--thresholds", help="JSON object overriding DEFAULT_THRESHOLDS keys")
    score.add_argument("-o", "--write", action="store_true",
                       help="write <pipeline_dir>/stage_scorecard.json (backfill; keeps "
                            "pipeline-authored sidecars)")
    score.add_argument("--force", action="store_true",
                       help="with -o: also rewrite pipeline-authored sidecars, keeping their "
                            "runtime_gates under identity.previous")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "score":
        return _cmd_score(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
