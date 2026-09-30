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
The scorecard is never a gate: failed contracts do not change the exit code of
``score``.

EVAL-16 cross-run aggregate:
    python scripts/stage_scorecard.py aggregate [--since YYYY-MM-DD] [-o]

Re-projects every terminal pipeline in memory with the current scorecard
(sidecars are neither read nor written, so runs scored before a contract
existed and runs without a sidecar are scored alike) and groups the runs by
their run.json ``repo_git_sha`` and resolved per-stage provider/model (the
scorecard's ``identity.backbone``).  ``--since`` keeps runs created on or after
that UTC date.  Groups are ordered by their first run's ``created_at`` (a run
without one sorts as the oldest); the last group is the latest.  Per group and
stage it reports the runs, the contract pass rate (passed over passed + failed,
with the unevaluable runs beside it) and, for every rate in
``RATE_METRICS``, the pooled num/den with its Wilson interval
(``eval_stats.wilson_interval``) and the per-run median/min/max: the run, not
the fact or the claim, is the unit of analysis.  A regression is flagged only
when at least ``MIN_REGRESSION_RUNS`` runs of a group feed the measure and its
Wilson interval lies entirely on the worse side of the previous group's point
estimate (upper bound below it; lower bound above it for a lower-is-better
rate).  ``-o`` / ``--write`` also writes the aggregate to
``<PIPELINE_DATA_DIR>/_stage_scorecard_aggregate.json``.

Aggregate exit codes, judged on the latest group (first match wins): 1 a run
has a failed contract, 2 drift only (a regression flag), 3 inconclusive (more
than 20% of the scored stage verdicts are unevaluable, no run at all, or a
pipeline could not be scored), 0 clean; 4 the aggregate could not be written.
A malformed command line (such as an invalid ``--since`` date) is rejected by
argparse before any scoring: usage on stderr, nothing on stdout, exit 2.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import statistics
import sys
from typing import Any, Iterable, Optional

# Import backend's app package regardless of the calling cwd (same as resolution_monitor.py).
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from app.config import Config  # noqa: E402
from app.services import stage_scorecard as scorecard  # noqa: E402
from app.services.eval_stats import wilson_interval  # noqa: E402
from app.services.pipeline_orchestrator import PipelineManager  # noqa: E402
from app.utils.atomic import write_json_atomic  # noqa: E402

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
PIPELINE_AUTHORED = "pipeline-authored sidecar"

AGGREGATE_SCHEMA_VERSION = "stage-scorecard-aggregate/v1"
AGGREGATE_FILENAME = "_stage_scorecard_aggregate.json"
MIN_REGRESSION_RUNS = 3
MAX_UNEVALUABLE_SHARE = 0.2
# Wilson bounds carry float noise (wilson_interval(6, 6) has an upper bound of
# 0.9999999999999999): a bound must clear the previous value by more than this.
_BOUND_TOLERANCE = 1e-9
EXIT_CLEAN, EXIT_CONTRACT_FAILURES, EXIT_DRIFT, EXIT_INCONCLUSIVE, EXIT_WRITE_FAILED = range(5)
_VERDICTS = {EXIT_CLEAN: "clean", EXIT_CONTRACT_FAILURES: "contract_failures",
             EXIT_DRIFT: "drift", EXIT_INCONCLUSIVE: "inconclusive"}
_OLDEST = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


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


# ------------------------------------------------------------------ aggregate
def _created_at(value: Any) -> Optional[dt.datetime]:
    """A pipeline state's ``created_at`` as an aware UTC datetime; None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.strip())
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.astimezone(dt.timezone.utc)
    except (ValueError, OverflowError):
        return None


def _iso_date(value: str) -> dt.date:
    """argparse type of ``--since``."""
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected a YYYY-MM-DD date, got {value!r}") from exc


def _collect_runs(since: Optional[dt.date]) -> tuple[list[dict], list[dict], list[dict]]:
    """(runs, skipped, errors): every terminal pipeline re-projected in memory."""
    ids, skipped, errors = _terminal_pipeline_ids()
    runs: list[dict] = []
    for pipeline_id in ids:
        try:
            created = _created_at((PipelineManager.load(pipeline_id) or {}).get("created_at"))
            if since is not None and (created is None or created.date() < since):
                skipped.append({"pipeline_id": pipeline_id, "reason": (
                    "created before --since" if created else "no parseable created_at")})
                continue
            card = scorecard.build_stage_scorecard(scorecard.resolve_inputs(pipeline_id))
        except Exception as exc:  # noqa: BLE001 — one bad pipeline never aborts the aggregate
            errors.append({"pipeline_id": pipeline_id, "error": _error_text(exc)})
            continue
        runs.append({"pipeline_id": pipeline_id, "created_at": created, "card": card})
    return runs, skipped, errors


def _group_runs(runs: Iterable[dict]) -> list[dict]:
    """Runs grouped by (repo_git_sha, backbone), oldest first; groups in first-run order."""
    groups: dict[str, dict] = {}
    for run in sorted(runs, key=lambda run: (run["created_at"] or _OLDEST, run["pipeline_id"])):
        identity = _identity(run["card"])
        sha, backbone = identity.get("repo_git_sha"), identity.get("backbone")
        sha = sha if isinstance(sha, str) and sha else None
        backbone = backbone if isinstance(backbone, dict) and backbone else None
        key = json.dumps({"repo_git_sha": sha, "backbone": backbone}, sort_keys=True)
        group = groups.setdefault(key, {"repo_git_sha": sha, "backbone": backbone, "runs": []})
        group["runs"].append(run)
    return list(groups.values())


def _scored_stages(run: dict) -> Iterable[tuple[str, dict, dict]]:
    """(stage, stage block, check) for every stage the run's scorecard scored."""
    card = run["card"]
    for stage in scorecard.STAGES:
        block = card["stages"].get(stage) or {}
        if block.get("status") == scorecard.STAGE_SCORED:
            yield stage, block, card["checks"].get(stage) or {}


def _stage_summary(runs: list[dict], stage: str) -> dict:
    """One stage of one group: contract pass rate and every RATE_METRICS rate, run as the unit."""
    directions = scorecard.RATE_METRICS.get(stage, {})
    verdicts: list[Any] = []
    values: dict[str, list[float]] = {name: [] for name in directions}
    pooled: dict[str, list[int]] = {name: [0, 0, 0] for name in directions}  # num, den, runs
    for run in runs:
        for scored, block, check in _scored_stages(run):
            if scored != stage:
                continue
            verdicts.append(check.get("passed"))
            metrics = block.get("metrics") or {}
            for name in directions:
                record = metrics.get(name)
                if not isinstance(record, dict) or record.get("status") != scorecard.MEASURED:
                    continue
                value = scorecard._as_float(record.get("value"))
                if value is not None:
                    values[name].append(value)
                num, den = scorecard._as_count(record.get("num")), scorecard._as_count(record.get("den"))
                if num is not None and den and num <= den:
                    pooled[name][0] += num
                    pooled[name][1] += den
                    pooled[name][2] += 1
    passed = sum(1 for verdict in verdicts if verdict is True)
    evaluable = passed + sum(1 for verdict in verdicts if verdict is False)
    rates: dict[str, dict] = {}
    for name, better in directions.items():
        num, den, pooled_runs = pooled[name]
        series = values[name]
        rates[name] = {
            "better": better,
            "runs": len(series),
            "per_run": {"median": statistics.median(series), "min": min(series),
                        "max": max(series)} if series else None,
            "pooled": {"runs": pooled_runs, "num": num, "den": den, "value": num / den,
                       "wilson": wilson_interval(num, den)} if den else None,
        }
    return {
        "runs": len(verdicts),
        "contract": {"passed": passed, "failed": evaluable - passed,
                     "unevaluable": len(verdicts) - evaluable, "evaluable_runs": evaluable,
                     "pass_rate": passed / evaluable if evaluable else None,
                     "wilson": wilson_interval(passed, evaluable)},
        "rates": rates,
    }


def _summarize_group(group: dict, index: int) -> dict:
    runs = group["runs"]
    stages = {stage: _stage_summary(runs, stage) for stage in scorecard.STAGES}
    failures = [{"pipeline_id": run["pipeline_id"], "stage": stage, "failed": list(check.get("failed") or [])}
                for run in runs for stage, _block, check in _scored_stages(run)
                if check.get("passed") is False]
    verdicts = sum(summary["runs"] for summary in stages.values())
    unevaluable = sum(summary["contract"]["unevaluable"] for summary in stages.values())
    created = [run["created_at"] for run in runs if run["created_at"] is not None]
    return {
        "group": index,
        "repo_git_sha": group["repo_git_sha"],
        "backbone": group["backbone"],
        "runs": len(runs),
        "pipelines": [run["pipeline_id"] for run in runs],
        "first_created_at": min(created).isoformat() if created else None,
        "last_created_at": max(created).isoformat() if created else None,
        "stages": stages,
        "contract_failures": failures,
        "unevaluable_share": unevaluable / verdicts if verdicts else None,
        "compared_to": None,
        "regressions": [],
    }


def _regressions(group: dict, previous: dict) -> list[dict]:
    """Measures whose Wilson interval lies wholly on the worse side of the previous group's value.

    Only a measure fed by at least MIN_REGRESSION_RUNS runs of ``group`` is judged.
    """
    flags: list[dict] = []
    for stage in scorecard.STAGES:
        contract = group["stages"][stage]["contract"]
        before = previous["stages"][stage]["contract"]["pass_rate"]
        if (contract["evaluable_runs"] >= MIN_REGRESSION_RUNS and before is not None
                and contract["wilson"][1] < before - _BOUND_TOLERANCE):
            flags.append({"stage": stage, "measure": "contract_pass_rate",
                          "better": scorecard.HIGHER_IS_BETTER, "value": contract["pass_rate"],
                          "wilson": contract["wilson"], "previous": before,
                          "runs": contract["evaluable_runs"]})
        for name, rate in group["stages"][stage]["rates"].items():
            pooled = rate["pooled"]
            before = (previous["stages"][stage]["rates"][name]["pooled"] or {}).get("value")
            if pooled is None or before is None or pooled["runs"] < MIN_REGRESSION_RUNS:
                continue
            low, high = pooled["wilson"]
            if (high < before - _BOUND_TOLERANCE if rate["better"] == scorecard.HIGHER_IS_BETTER
                    else low > before + _BOUND_TOLERANCE):
                flags.append({"stage": stage, "measure": name, "better": rate["better"],
                              "value": pooled["value"], "wilson": pooled["wilson"],
                              "previous": before, "runs": pooled["runs"]})
    return flags


def _aggregate_exit_code(latest: Optional[dict], errors: list[dict]) -> int:
    """The latest group's verdict: contract failures > drift > inconclusive > clean."""
    if latest is None:
        return EXIT_INCONCLUSIVE
    if latest["contract_failures"]:
        return EXIT_CONTRACT_FAILURES
    if latest["regressions"]:
        return EXIT_DRIFT
    share = latest["unevaluable_share"]
    if share is None or share > MAX_UNEVALUABLE_SHARE or errors:
        return EXIT_INCONCLUSIVE
    return EXIT_CLEAN


def _rounded(value: Any) -> Any:
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def aggregate(runs: list[dict], *, since: Optional[dt.date] = None,
              skipped: Iterable[dict] = (), errors: Iterable[dict] = ()) -> dict:
    """The ``stage-scorecard-aggregate/v1`` envelope of ``runs`` (in any order).

    Each run is ``{"pipeline_id", "created_at" (aware datetime or None), "card"}``
    with ``card`` a ``stage-scorecard/v1`` envelope.  Pure: no disk access.
    """
    errors = sorted(errors, key=lambda row: row["pipeline_id"])
    groups: list[dict] = []
    for index, group in enumerate(_group_runs(runs)):
        summary = _summarize_group(group, index)
        if groups:
            summary["compared_to"] = index - 1
            summary["regressions"] = _regressions(summary, groups[-1])
        groups.append(summary)
    exit_code = _aggregate_exit_code(groups[-1] if groups else None, errors)
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "since": since.isoformat() if since else None,
        "min_regression_runs": MIN_REGRESSION_RUNS,
        "max_unevaluable_share": MAX_UNEVALUABLE_SHARE,
        "count": len(runs),
        "groups": _rounded(groups),
        "latest_group": len(groups) - 1 if groups else None,
        "verdict": _VERDICTS[exit_code],
        "exit_code": exit_code,
        "skipped": sorted(skipped, key=lambda row: row["pipeline_id"]),
        "errors": errors,
    }


def aggregate_path() -> str:
    return os.path.join(Config.PIPELINE_DATA_DIR, AGGREGATE_FILENAME)


def _cmd_aggregate(args: argparse.Namespace) -> int:
    runs, skipped, errors = _collect_runs(args.since)
    result = aggregate(runs, since=args.since, skipped=skipped, errors=errors)
    output = _render_json(result)
    if args.write:
        try:
            write_json_atomic(aggregate_path(), result, allow_nan=False)
        except Exception as exc:  # noqa: BLE001 — the printed aggregate is still the result
            print(output)
            print(f"cannot write {aggregate_path()}: {_error_text(exc)}", file=sys.stderr)
            return EXIT_WRITE_FAILED
        print(f"wrote {aggregate_path()}", file=sys.stderr)
    print(output)
    return result["exit_code"]


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
    agg = sub.add_parser("aggregate", help="group terminal runs by code sha and backbone; flag "
                                           "contract failures and regressions")
    agg.add_argument("--since", type=_iso_date, default=None,
                     help="only runs created on or after this UTC date (YYYY-MM-DD)")
    agg.add_argument("-o", "--write", action="store_true",
                     help=f"also write <PIPELINE_DATA_DIR>/{AGGREGATE_FILENAME}")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.cmd == "score":
        return _cmd_score(args)
    if args.cmd == "aggregate":
        return _cmd_aggregate(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
