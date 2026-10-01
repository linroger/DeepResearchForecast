"""EVAL-19: backfill and verify frozen evaluation bundles (app/services/eval_bundle.py).

    python backend/scripts/eval_bundle.py backfill --pipeline PID [--force [--replace-in-pipeline]]
    python backend/scripts/eval_bundle.py backfill --all-recent N [--force [--replace-in-pipeline]]
    python backend/scripts/eval_bundle.py verify <bundle_dir>

backfill rebuilds a published report's bundle from its stored handoff (no LLM, no
network; manifest ``capture: backfill``): brief / forecast_inputs / quant from
actors.json, dossier from research_report.md, market from prediction_markets.json
rendered as the research table at the snapshot time (block note
``backfill_research_snapshot``: the exact report-time market pack is not persisted), sim
and graph ``unavailable:not_persisted``, targets from the audit-sealed forecast only
(``ReportManager.load_structured_forecast``; none when unsealed). as_of is resolved as
the ledger commit resolved it (``ledger_commit.resolve_as_of`` at the report's
completion time), and run.record_class as the orchestrator keys the pipeline's own report
(evaluation / conditional_scenario / production). The handoff is the state's
containment-checked one (``PipelineManager.resolve_handoff_dir``: a what-if fork reads
its base's). Only publishable reports are bundled. An existing bundle is kept
unless --force; a bundle captured in the pipeline (higher fidelity) is replaced only
with --force --replace-in-pipeline. One pipeline's failure is reported as an ``error``
row and never aborts the others; the exit code is 1 when any row errored, else 0.

verify re-hashes a bundle: exit 0 when intact, 4 on any integrity failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import eval_bundle  # noqa: E402

EXIT_BACKFILL_ERROR = 1
EXIT_INTEGRITY = 4


def _read_json(path: str) -> Any:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def _report_completed_at(report_id: str) -> Optional[datetime]:
    """When the report completed (meta.json ``completed_at``; a naive stamp is local
    time, as generate_report writes it), in UTC; None when unknown."""
    from app.services.report_agent import ReportManager
    meta = _read_json(ReportManager._get_report_path(report_id))
    stamp = meta.get("completed_at") if isinstance(meta, dict) else None
    if not isinstance(stamp, str) or not stamp.strip():
        return None
    try:
        return datetime.fromisoformat(stamp.strip()).astimezone(timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None


def _record_class(pipeline_id: str, state: Dict[str, Any], handoff: str) -> str:
    """The ledger record class of a pipeline's own report, derived as the orchestrator
    keys it (``PipelineOrchestrator._report_ledger_context``): the run's evaluation pin
    (options, else its handoff marker; EVAL-13) re-classes it ``evaluation``, a what-if
    fork is ``conditional_scenario``, anything else ``production``."""
    from app.services.ledger_commit import _record_class as ledger_record_class
    from app.services.ledger_commit import apply_evaluation_context
    from app.services.pipeline_orchestrator import _evaluation_pin_of, _scenario_ledger_identity
    options = state.get("options") if isinstance(state.get("options"), dict) else {}
    context = apply_evaluation_context(
        _scenario_ledger_identity(options),
        _evaluation_pin_of(pipeline_id, {"options": options, "handoff_dir": handoff}))
    return ledger_record_class(context, None)


def backfill_pipeline(pipeline_id: str, *, force: bool = False,
                      replace_in_pipeline: bool = False) -> Dict[str, Any]:
    """Bundle one pipeline's published report from its handoff; returns a result row."""
    from app.services.ledger_commit import resolve_as_of
    from app.services.pipeline_orchestrator import PipelineManager, validated_as_of_from_options
    from app.services.report_agent import ReportManager

    state = PipelineManager.load(pipeline_id)
    if not isinstance(state, dict):
        return {"pipeline": pipeline_id, "status": "skipped", "reason": "pipeline_not_found"}
    report_id = state.get("report_id")
    if not report_id:
        return {"pipeline": pipeline_id, "status": "skipped", "reason": "no_report"}
    if not ReportManager.publication_status(report_id).get("publishable"):
        return {"pipeline": pipeline_id, "report": report_id, "status": "skipped", "reason": "not_publishable"}
    report_dir = ReportManager._get_report_folder(report_id)
    target_dir = eval_bundle.bundle_dir_for(report_dir)
    manifest_path = os.path.join(target_dir, eval_bundle.MANIFEST_NAME)
    if os.path.exists(manifest_path):
        if not force:
            return {"pipeline": pipeline_id, "report": report_id, "status": "skipped", "reason": "bundle_exists"}
        existing = _read_json(manifest_path)
        if (isinstance(existing, dict) and existing.get("capture") == eval_bundle.CAPTURE_IN_PIPELINE
                and not replace_in_pipeline):
            return {"pipeline": pipeline_id, "report": report_id, "status": "skipped",
                    "reason": "in_pipeline_bundle_exists"}
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    actors = _read_json(os.path.join(handoff, "actors.json"))
    built = eval_bundle.research_blocks(
        actors, _read_text(os.path.join(handoff, "research_report.md")), eval_bundle.dossier_chars())
    options = state.get("options") if isinstance(state.get("options"), dict) else {}
    as_of, as_of_source = resolve_as_of({"as_of_date": validated_as_of_from_options(options)}, actors,
                                        _report_completed_at(report_id))
    built["market"] = eval_bundle.research_market_block(
        _read_json(os.path.join(handoff, "prediction_markets.json")),
        fallback_as_of=as_of if as_of_source != "commit_date" else None)
    built["sim"] = (None, eval_bundle.unavailable("not_persisted"))
    built["graph"] = (None, eval_bundle.unavailable("not_persisted"))
    forecast = ReportManager.load_structured_forecast(report_id)
    meta = {
        "capture": eval_bundle.CAPTURE_BACKFILL,
        "ids": {"pipeline": pipeline_id, "report": report_id, "simulation": state.get("simulation_id"),
                "graph": state.get("graph_id")},
        "as_of": as_of,
        "as_of_source": as_of_source,
        "central_question": state.get("prompt"),
        "upstream_models": eval_bundle.upstream_models(pipeline_id),
        # The pipeline's own report; the simulation seed it ran with is not persisted.
        "run": {"record_class": _record_class(pipeline_id, state, handoff), "run_kind": "pipeline",
                "seed": None},
        "publication": eval_bundle.publication_hashes(report_dir, forecast_sealed=isinstance(forecast, dict)),
    }
    manifest = eval_bundle.write_bundle(
        target_dir, blocks={n: built[n][0] for n in eval_bundle.BLOCK_NAMES},
        statuses={n: built[n][1] for n in eval_bundle.BLOCK_NAMES},
        targets=eval_bundle.select_targets(forecast), meta=meta,
        notes=({"market": "backfill_research_snapshot"}
               if built["market"][1] == eval_bundle.STATUS_OK else None))
    return {"pipeline": pipeline_id, "report": report_id, "status": "written", "bundle_dir": target_dir,
            "bundle_sha256": manifest["bundle_sha256"]}


def cmd_backfill(args: argparse.Namespace) -> int:
    from app.services.pipeline_orchestrator import PipelineManager
    if args.pipeline:
        ids: List[str] = [args.pipeline]
    else:
        ids = [str(e.get("pipeline_id")) for e in PipelineManager.list_pipelines()
               if e.get("pipeline_id")][:max(0, int(args.all_recent))]
    results: List[Dict[str, Any]] = []
    for pid in ids:
        try:
            results.append(backfill_pipeline(pid, force=args.force,
                                             replace_in_pipeline=args.replace_in_pipeline))
        except Exception as exc:  # noqa: BLE001 — one pipeline never aborts the batch
            results.append({"pipeline": pid, "status": "error",
                            "reason": f"{type(exc).__name__}: {exc}"[:300]})
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return EXIT_BACKFILL_ERROR if any(r.get("status") == "error" for r in results) else 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        manifest, _texts = eval_bundle.load_bundle(args.bundle_dir)
    except eval_bundle.BundleIntegrityError as exc:
        print(json.dumps({"bundle_dir": args.bundle_dir, "intact": False, "error": str(exc)}, ensure_ascii=False))
        return EXIT_INTEGRITY
    print(json.dumps({"bundle_dir": args.bundle_dir, "intact": True,
                      "bundle_sha256": manifest["bundle_sha256"]}, ensure_ascii=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EVAL-19 frozen evaluation bundles")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="bundle published reports from their stored handoffs")
    who = b.add_mutually_exclusive_group(required=True)
    who.add_argument("--pipeline", default=None, help="one pipeline id")
    who.add_argument("--all-recent", type=int, default=None, metavar="N", help="the N newest pipelines")
    b.add_argument("--force", action="store_true", help="rewrite an existing backfilled bundle")
    b.add_argument("--replace-in-pipeline", action="store_true",
                   help="with --force, also replace a bundle captured in the pipeline")
    b.set_defaults(func=cmd_backfill)
    v = sub.add_parser("verify", help=f"re-hash a bundle (exit {EXIT_INTEGRITY} on any mismatch)")
    v.add_argument("bundle_dir")
    v.set_defaults(func=cmd_verify)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
