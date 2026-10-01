"""EVAL-19: backfill and verify frozen evaluation bundles (app/services/eval_bundle.py).

    python backend/scripts/eval_bundle.py backfill --pipeline PID
    python backend/scripts/eval_bundle.py backfill --all-recent N
    python backend/scripts/eval_bundle.py verify <bundle_dir>

backfill rebuilds a published report's bundle from its stored handoff (no LLM, no
network): brief / forecast_inputs / quant from actors.json, dossier from
research_report.md, market from prediction_markets.json rendered as the research
table (block note ``backfill_research_snapshot``: the exact report-time market pack
is not persisted), sim and graph ``unavailable:not_persisted``. Only publishable
reports are bundled; an existing bundle is kept unless --force.

verify re-hashes a bundle: exit 0 when intact, 4 on any integrity failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import eval_bundle  # noqa: E402

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


def backfill_pipeline(pipeline_id: str, *, force: bool = False) -> Dict[str, Any]:
    """Bundle one pipeline's published report from its handoff; returns a result row."""
    from app.services.pipeline_orchestrator import PipelineManager, validated_as_of_from_options
    from app.services.report_agent import ReportManager
    from app.utils.prediction_markets import render_markets_block

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
    if os.path.exists(os.path.join(target_dir, eval_bundle.MANIFEST_NAME)) and not force:
        return {"pipeline": pipeline_id, "report": report_id, "status": "skipped", "reason": "bundle_exists"}
    handoff = state.get("handoff_dir") or PipelineManager.handoff_dir(pipeline_id)
    actors = _read_json(os.path.join(handoff, "actors.json"))
    built = eval_bundle.research_blocks(
        actors, _read_text(os.path.join(handoff, "research_report.md")),
        int(getattr(Config, "EVAL_DOSSIER_CHARS", eval_bundle.DEFAULT_DOSSIER_CHARS)))
    snapshot = _read_json(os.path.join(handoff, "prediction_markets.json"))
    markets = snapshot.get("markets") if isinstance(snapshot, dict) else snapshot
    rows = [m for m in (markets or []) if isinstance(m, dict)] if isinstance(markets, list) else []
    market_text = render_markets_block(rows) if rows else ""
    built["market"] = ((market_text, eval_bundle.STATUS_OK) if market_text.strip()
                       else (None, eval_bundle.unavailable("no_research_snapshot")))
    built["sim"] = (None, eval_bundle.unavailable("not_persisted"))
    built["graph"] = (None, eval_bundle.unavailable("not_persisted"))
    options = state.get("options") if isinstance(state.get("options"), dict) else {}
    as_of = validated_as_of_from_options(options) or (actors.get("as_of_date") if isinstance(actors, dict) else None)
    meta = {
        "ids": {"pipeline": pipeline_id, "report": report_id, "simulation": state.get("simulation_id"),
                "graph": state.get("graph_id")},
        "as_of": as_of,
        "central_question": state.get("prompt"),
        "upstream_models": eval_bundle._upstream_models(pipeline_id),
        "publication": eval_bundle._publication(report_dir),
    }
    manifest = eval_bundle.write_bundle(
        target_dir, blocks={n: built[n][0] for n in eval_bundle.BLOCK_NAMES},
        statuses={n: built[n][1] for n in eval_bundle.BLOCK_NAMES},
        targets=eval_bundle.select_targets(_read_json(os.path.join(report_dir, "forecast.json"))),
        meta=meta, notes={"market": "backfill_research_snapshot"} if market_text.strip() else None)
    return {"pipeline": pipeline_id, "report": report_id, "status": "written", "bundle_dir": target_dir,
            "bundle_sha256": manifest["bundle_sha256"]}


def cmd_backfill(args: argparse.Namespace) -> int:
    from app.services.pipeline_orchestrator import PipelineManager
    if args.pipeline:
        ids: List[str] = [args.pipeline]
    else:
        ids = [str(e.get("pipeline_id")) for e in PipelineManager.list_pipelines()
               if e.get("pipeline_id")][:max(0, int(args.all_recent))]
    results = [backfill_pipeline(pid, force=args.force) for pid in ids]
    print(json.dumps({"results": results}, ensure_ascii=False, indent=2))
    return 0


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
    b.add_argument("--force", action="store_true", help="rewrite an existing bundle")
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
