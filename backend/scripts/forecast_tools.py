#!/usr/bin/env python3
"""CLI for ensemble aggregation + backtest/calibration over structured forecasts
(EXECPLAN2 I-9-0/I-2-4/I-3-3/I-9-2).

Operates on the forecast.json files emitted by report generation when
REPORT_STRUCTURED_FORECAST=true. The N-seed *runs* themselves are produced by
re-running the pipeline (the existing PREPARE-fork) with different SIM_SEED; this
tool aggregates/scores their forecasts.

Examples:
    # aggregate several runs' forecasts into one probabilistic ensemble forecast
    python backend/scripts/forecast_tools.py ensemble run1/forecast.json run2/forecast.json ... -o ensemble.json

    # score resolved forecasts (a JSON list of {"forecast": {...}, "outcome": "scenario name"})
    python backend/scripts/forecast_tools.py backtest resolved.json

    # EVAL-4: attest a report's outcome for calibration (one manual settlement event in
    # resolutions.jsonl), then correct or retract it by naming the event it replaces
    python backend/scripts/forecast_tools.py resolve --report-id R --scenario "Status quo" \
        --known-at 2026-09-15T12:00:00Z --evidence https://example.org/official-result
    python backend/scripts/forecast_tools.py resolve --report-id R --binary F3 --outcome NO \
        --known-at 2026-09-15 --evidence "Official gazette of 2026-09-15, notice 42"
    python backend/scripts/forecast_tools.py resolve --report-id R --scenario "Escalation" \
        --known-at 2026-09-15T12:00:00Z --evidence https://example.org/corrected --supersedes manual
    python backend/scripts/forecast_tools.py resolve --report-id R --scenario --retract \
        --supersedes manual:r1 --evidence "The cited result was later annulled by the court."

resolve exit codes: 0 appended, identical repeat (no-op) or --dry-run; 1 the ledger did not
take the event; 2 invalid attestation (nothing written); 4 no settleable target (no
production primary ledger row and no report publishable at issue with a sealed forecast).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.ensemble import aggregate_forecasts  # noqa: E402
from app.services.backtest import calibration_report, score_forecast  # noqa: E402
from app.services import forecast_ledger, forecast_resolution  # noqa: E402

# resolve exit codes beyond 0 (see the module docstring).
EXIT_NOT_APPENDED = 1
EXIT_INVALID = 2
EXIT_NO_TARGET = 4


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd_ensemble(args) -> int:
    forecasts = [_load(p) for p in args.files]
    agg = aggregate_forecasts(forecasts)
    out = json.dumps(agg, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out)
        print(f"wrote {args.out} ({agg['n_runs']} runs, {len(agg['scenarios'])} scenarios, agreement={agg['agreement']})")
    else:
        print(out)
    return 0


def cmd_backtest(args) -> int:
    resolved = _load(args.resolved)
    if not isinstance(resolved, list):
        print("resolved file must be a JSON list of {forecast, outcome}", file=sys.stderr)
        return 2
    rep = calibration_report(resolved, bins=args.bins)
    rep["per_forecast"] = [score_forecast(r.get("forecast", {}), r.get("outcome", "")) for r in resolved]
    print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


def _print_json(payload) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_resolve(args) -> int:
    """EVAL-4: attest one outcome of a report as a manual settlement event.

    The known-at and evidence are validated first (exit 2 even without a target). The
    target is forecast_resolution.load_manual_target (the report's production primary
    ledger row, else the report itself when publishable at issue and sealed);
    forecast_resolution.plan_manual_settlement validates the attestation and its
    revision chain before anything is written, and the event is appended through the
    ledger's first-write-wins lock. The appended event (or, for an identical repeat,
    the recorded one; for --dry-run, the one that would be appended) goes to stdout; a
    scenario attestation that no production primary ledger row can carry into
    calibration is still written, with a warning on stderr.
    """
    if args.scenario is not None:
        if args.outcome is not None:
            print("error: --outcome applies to --binary; --scenario names the outcome itself",
                  file=sys.stderr)
            return EXIT_INVALID
        item, outcome = forecast_resolution.SCENARIO_ITEM, args.scenario
    else:
        item, outcome = args.binary, args.outcome
        if item.strip() in (forecast_resolution.SCENARIO_ITEM,
                            forecast_resolution.SCENARIO_SET_FORECAST_ID):
            print(f"error: {item.strip()!r} names the scenario set, not a binary; "
                  f"use --scenario", file=sys.stderr)
            return EXIT_INVALID
    # Invalid input is exit 2 whether or not the report has a target.
    ok, errors = forecast_resolution.validate_manual_attestation(args.known_at, args.evidence,
                                                                 retract=args.retract)
    if not ok:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return EXIT_INVALID
    target, reason = forecast_resolution.load_manual_target(args.report_id,
                                                            ledger_dir=args.ledger_dir)
    if target is None:
        print(f"error: no settleable forecast target for {args.report_id!r}: {reason}",
              file=sys.stderr)
        return EXIT_NO_TARGET
    plan = forecast_resolution.plan_manual_settlement(
        target, item, outcome, args.known_at, args.evidence,
        existing_events=forecast_ledger.read_market_resolutions(args.ledger_dir),
        supersedes=args.supersedes, retract=args.retract,
        processed_at=datetime.now(timezone.utc).isoformat())
    if plan["status"] in ("invalid", "exists"):
        for error in plan["errors"]:
            print(f"error: {error}", file=sys.stderr)
        return EXIT_INVALID
    unbound = forecast_resolution.manual_not_bindable_reason(target, item)
    if unbound and not args.retract:
        print(f"warning: {unbound}: the report has no production primary ledger row, so "
              f"this scenario attestation enters no calibration", file=sys.stderr)
    if plan["status"] == "noop":
        print(f"no-op: the same attestation is already recorded as "
              f"{plan['latest'].get('market_id')!r}", file=sys.stderr)
        _print_json(plan["latest"])
        return 0
    if args.dry_run:
        print("dry run: nothing written", file=sys.stderr)
        _print_json(plan["event"])
        return 0
    written = forecast_ledger.append_settlement_event(plan["event"], d=args.ledger_dir)
    if written is None:
        print(f"error: the ledger did not take {plan['event']['market_id']!r} (the key is "
              f"already recorded or resolutions.jsonl is not writable)", file=sys.stderr)
        return EXIT_NOT_APPENDED
    _print_json(written)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="ensemble + backtest for structured forecasts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("ensemble", help="aggregate N forecast.json into one probabilistic forecast")
    e.add_argument("files", nargs="+")
    e.add_argument("-o", "--out", default=None)
    e.set_defaults(func=cmd_ensemble)
    b = sub.add_parser("backtest", help="score + calibrate resolved forecasts")
    b.add_argument("resolved")
    b.add_argument("--bins", type=int, default=5)
    b.set_defaults(func=cmd_backtest)
    r = sub.add_parser("resolve", help="attest a scenario or binary outcome for calibration "
                                       "(one manual settlement event)")
    r.add_argument("--report-id", required=True)
    item = r.add_mutually_exclusive_group(required=True)
    item.add_argument("--scenario", nargs="?", const="", default=None, metavar="NAME",
                      help="the scenario that occurred (matched like the scorer does); "
                           "no NAME with --retract")
    item.add_argument("--binary", metavar="ID", help="a binary forecast id, e.g. F3")
    r.add_argument("--outcome", help="YES or NO (with --binary; none with --retract)")
    r.add_argument("--known-at", help="when the outcome became known: YYYY-MM-DD or an ISO "
                                      "date-time with Z or an offset; not with --retract")
    r.add_argument("--evidence", help="an http(s) URL or a note of at least 20 characters")
    r.add_argument("--supersedes", metavar="EVENT",
                   help="correct or retract the item's latest manual event "
                        "('manual' or 'manual:r<n>')")
    r.add_argument("--retract", action="store_true",
                   help="withdraw the attestation named by --supersedes")
    r.add_argument("--ledger-dir", default=None,
                   help="ledger directory (default: the production forecast ledger)")
    r.add_argument("--dry-run", action="store_true", help="validate and print, write nothing")
    r.set_defaults(func=cmd_resolve)
    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
