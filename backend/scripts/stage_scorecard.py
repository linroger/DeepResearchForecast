"""EVAL-15: offline stage-scorecard scoring and backfill.

Scores existing pipelines with the same deterministic projection the
orchestrator writes at every terminal state (app/services/stage_scorecard.py).
Runs that were reconciled as orphans at startup never reach the ``_run``
finally block, so this CLI is how they (and pre-EVAL-15 runs) get a sidecar.
Offline: it reads files under uploads/ only - no network, no LLM, no Flask.

Usage:
    python scripts/stage_scorecard.py score --pipeline <pipeline_id> [--thresholds FILE] [-o]
    python scripts/stage_scorecard.py score --all [--thresholds FILE] [-o]

``--pipeline`` prints the full scorecard JSON; ``--all`` scores every terminal
pipeline (completed / failed / cancelled) and prints a compact summary per
run.  ``-o`` / ``--write`` also writes ``<pipeline_dir>/stage_scorecard.json``.
The runtime_gates block records the current configuration (``scored_by:
"backfill"``), since run.json does not pin the gate values of the original run.
Exit codes: 0 scored, 1 a pipeline could not be scored, 2 usage error.
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


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False))


def _terminal_pipeline_ids() -> tuple[list[str], list[dict]]:
    """(terminal pipeline ids, skipped rows) under PIPELINE_DATA_DIR, sorted by id."""
    root = Config.PIPELINE_DATA_DIR
    if not os.path.isdir(root):
        return [], []
    ids: list[str] = []
    skipped: list[dict] = []
    for name in sorted(os.listdir(root)):
        if not PipelineManager._PIPELINE_ID_RE.fullmatch(name):
            continue
        data = PipelineManager.load(name)
        if not isinstance(data, dict):
            continue
        if PipelineManager.is_incompatible(data) is not None:
            skipped.append({"pipeline_id": name, "reason": "newer state schema"})
        elif data.get("status") in TERMINAL_STATUSES:
            ids.append(name)
        else:
            skipped.append({"pipeline_id": name, "reason": f"status {data.get('status')!r}"})
    return ids, skipped


def _score(pipeline_id: str, thresholds: Optional[dict], write: bool) -> dict:
    card = scorecard.build_stage_scorecard(scorecard.resolve_inputs(pipeline_id), thresholds)
    if write:
        write_json_atomic(scorecard.sidecar_path(pipeline_id), card, allow_nan=False)
    return card


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
    thresholds: Optional[dict] = None
    if args.thresholds:
        try:
            thresholds = scorecard.load_thresholds(args.thresholds)
        except (OSError, ValueError) as exc:
            print(f"invalid thresholds file {args.thresholds}: {exc}", file=sys.stderr)
            return 2
    if args.pipeline:
        try:
            card = _score(args.pipeline, thresholds, args.write)
        except (OSError, ValueError) as exc:
            print(f"cannot score {args.pipeline}: {exc}", file=sys.stderr)
            return 1
        if args.write:
            _print_json(_summary_row(card, scorecard.sidecar_path(args.pipeline)))
        else:
            _print_json(card)
        return 0

    ids, skipped = _terminal_pipeline_ids()
    rows: list[dict] = []
    errors: list[dict] = []
    for pipeline_id in ids:
        try:
            card = _score(pipeline_id, thresholds, args.write)
        except (OSError, ValueError, TypeError) as exc:
            errors.append({"pipeline_id": pipeline_id, "error": str(exc)[:300]})
            continue
        rows.append(_summary_row(card, scorecard.sidecar_path(pipeline_id) if args.write else None))
    _print_json({"count": len(rows), "pipelines": rows, "skipped": skipped, "errors": errors})
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
                       help="write <pipeline_dir>/stage_scorecard.json (backfill)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "score":
        return _cmd_score(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
