"""EVAL-18: rebuild a pipeline's slim cost card offline.

Rebuilds the drf-cost-card/v1 card (app/utils/cost_accounting.py) from the durable
files a pipeline leaves behind, with the same gatherer the orchestrator's ``_run``
finally block uses (pipeline_orchestrator.pipeline_cost_card): pipeline_state.json
(options with the report stage's ``config_hash_v1`` pin, stage timestamps and
statuses), run_telemetry.json and run.json. Offline: it reads files under
uploads/ only - no network, no LLM, no Flask.

The unattributed-spend baseline (process-wide unattributed LLM calls when the
attempt started) exists only in memory while the attempt runs, so it is carried
over from the card already on disk when there is one; otherwise the card reports
an unknown baseline.

Usage:
    python scripts/cost_card.py build <pipeline_id> [-o]

Prints the card as JSON. ``-o`` / ``--write`` also writes
``<pipeline_dir>/cost_card.json``, for terminal pipelines only (a running
pipeline's own finally block writes its card). Exit codes: 0 built, 1 the
pipeline could not be read, built or written, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Optional

# Import backend's app package regardless of the calling cwd (same as stage_scorecard.py).
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.services.pipeline_orchestrator import (  # noqa: E402
    PipelineManager, PipelineState, pipeline_cost_card,
)
from app.utils.atomic import write_json_atomic  # noqa: E402
from app.utils.cost_accounting import COST_CARD_FILENAME  # noqa: E402

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def card_path(pipeline_id: str) -> str:
    return os.path.join(PipelineManager._dir(pipeline_id), COST_CARD_FILENAME)


def _existing_baseline(pipeline_id: str) -> Optional[int]:
    """calls_at_attempt_start of the card already on disk (None when absent/unreadable)."""
    try:
        with open(card_path(pipeline_id), encoding="utf-8") as handle:
            card = json.load(handle)
    except (OSError, ValueError):
        return None
    block = card.get("unattributed_process") if isinstance(card, dict) else None
    value = block.get("calls_at_attempt_start") if isinstance(block, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def load_state(pipeline_id: str) -> PipelineState:
    """The pipeline's state; ValueError for an invalid id, an unreadable or newer-schema state."""
    if not PipelineManager._PIPELINE_ID_RE.fullmatch(str(pipeline_id or "")):
        raise ValueError(f"not a pipeline id: {pipeline_id!r}")
    data = PipelineManager.load(pipeline_id)
    if not isinstance(data, dict):
        raise ValueError(f"no readable pipeline_state.json for {pipeline_id}")
    incompatible = PipelineManager.is_incompatible(data)
    if incompatible is not None:
        raise ValueError(f"{pipeline_id} has a newer state schema: {incompatible}")
    return PipelineState.from_dict(data)


def rebuild(pipeline_id: str) -> dict[str, Any]:
    """The pipeline's cost card rebuilt from its durable files (nothing is written)."""
    return pipeline_cost_card(load_state(pipeline_id),
                              unattributed_calls_at_start=_existing_baseline(pipeline_id))


def _cmd_build(args: argparse.Namespace) -> int:
    try:
        card = rebuild(args.pipeline_id)
        if args.write and card.get("status") not in TERMINAL_STATUSES:
            print(f"{args.pipeline_id} is {card.get('status')!r}: only a terminal pipeline's "
                  "card is written (a running pipeline writes its own)", file=sys.stderr)
            return 1
        output = json.dumps(card, indent=2, ensure_ascii=False, allow_nan=False)
        if args.write:
            write_json_atomic(card_path(args.pipeline_id), card, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 — report any failure as "could not be built"
        print(f"cannot build the cost card of {args.pipeline_id}: "
              f"{type(exc).__name__}: {exc}"[:400], file=sys.stderr)
        return 1
    print(output)
    if args.write:
        print(f"wrote {card_path(args.pipeline_id)}", file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    build = sub.add_parser("build", help="rebuild one pipeline's drf-cost-card/v1 card")
    build.add_argument("pipeline_id", help="pipeline id (pipe_...)")
    build.add_argument("-o", "--write", action="store_true",
                       help="also write <pipeline_dir>/cost_card.json (terminal pipelines only)")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "build":
        return _cmd_build(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
