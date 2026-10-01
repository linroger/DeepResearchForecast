#!/usr/bin/env python3
"""RESEARCH-13 (P09): offline replay of the forecast-prompt context packs over stored handoffs.

For each research handoff this compares the context the two probability prompts get today
(legacy) with the RESEARCH-13 packs (packed):

* binary draw: legacy = ``[Situation brief]`` (situation_brief()[:2000]) + the 48k head+tail
  dossier slice; packed = ``build_binary_pack`` (as_of lanes + section-aware excerpt);
* spine: legacy = the ``[态势简报]`` slice (REPORT_SPINE_INPUT_CAP_BRIEF chars of the same
  brief); packed = ``build_spine_pack``.

Metrics per handoff and kind: ``analyst_section_present`` (binary only: a heading of the
analyst binary/resolution-ready section is in the context, each one reported under
``analyst_headings``; the analyst-class H1/H2 headings, else the analyst-class H3-H6 ones inside
packable sections; None when the dossier has neither), ``references_chars`` (chars of
References / Visual Annex / How-to-Read lines in the context, counting only lines that occur
nowhere else in the dossier), ``newest_past_row_in_lane`` (the newest timeline row dated on or
before as_of, found by parse_dated_period alone rather than the lane code, is in the context;
None without one), the pack's per-stream sizes, its temporal-audit violations and the
scheduled-lane guard state. The packs are built by ``ReportAgent._context_pack_result``, the
method a report uses, with the handoff's actors, timeline.json and quantitative.json; a
hindcast pin in ``<pipeline>/pipeline_state.json`` is honoured as in a report. As in a live
report, the spine's key-metrics slot carries REPORT-8's verified-figures block instead of the
key-metrics table when quantitative.json rows carry page-verification labels and
REPORT_VERIFIED_FACTS_BLOCK is on (FU-4): sources.json resolves its [S#] tags, and the block is
rendered in the run's output language, resolved as a report resolves it from the pipeline
prompt (pipeline_state.json), the dossier and the situation brief (REPORT_OUTPUT_LANGUAGE
overrides). No live market pack exists offline, so the REPORT-10 market-table strip is not
applied.

The replay date defaults to each handoff's own as_of day (``--now as_of``): a live report runs
close to its research as_of, so its scheduled lane is open, and replaying an older run with
today's date would close the guard and hide the lane the report carried. ``--now YYYY-MM-DD``
replays every handoff at one fixed date instead; a handoff whose as_of is not a day is replayed
at today's date (its packs fall back anyway).

Promotion of FORECAST_CONTEXT_PACK_BINARY / _SPINE rests on these metrics plus a manual review
of five packed prompts (``--json`` carries each pack's text sha; the text itself is printed with
``--show-text``); a golden Brier comparison is informational only (ADR-0002 I-21).

Offline: no LLM client is constructed and nothing touches the network; handoff files are only
read. Log lines go to stderr, so stdout carries only the replay's output (``--json`` stays
parseable).

Usage:
    python backend/scripts/context_pack_replay.py --handoff DIR [DIR ...] [--json]
        [--now as_of|YYYY-MM-DD] [--show-text]

DIR is a handoff directory (holding research_report.md) or a pipeline directory holding one
under handoff/. Exit status 1 when any handoff could not be replayed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import sys
import unicodedata
from datetime import date, datetime, time, timezone
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

# scripts/ -> backend/ on sys.path (mirror of scripts/model_comparison.py)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import Config  # noqa: E402
from app.services import forecast_context_packer as cp  # noqa: E402
from app.services.forecast_extractor import slice_head_tail  # noqa: E402
from app.services.hindcast_policy import hindcast_policy  # noqa: E402
from app.services.report_agent import ReportAgent  # noqa: E402
from app.utils import actors as actors_utils  # noqa: E402

_MIN_LINE_CHARS = 20
_EVENT_PROBE_CHARS = 60


def _read_json(path: str) -> Any:
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def resolve_handoff_dir(path: str) -> str:
    """``path`` when it holds research_report.md, else ``path``/handoff (FileNotFoundError
    when neither does)."""
    for candidate in (path, os.path.join(path, "handoff")):
        if os.path.isfile(os.path.join(candidate, "research_report.md")):
            return candidate
    raise FileNotFoundError(f"no research_report.md under {path} or {path}/handoff")


def load_handoff(path: str) -> Dict[str, Any]:
    """The report-stage inputs of one stored handoff."""
    directory = resolve_handoff_dir(path)
    with open(os.path.join(directory, "research_report.md"), encoding="utf-8") as handle:
        report = handle.read()
    actors = _read_json(os.path.join(directory, "actors.json"))
    timeline = _read_json(os.path.join(directory, "timeline.json"))
    quantitative = _read_json(os.path.join(directory, "quantitative.json"))
    sources = _read_json(os.path.join(directory, "sources.json"))
    state = _read_json(os.path.join(os.path.dirname(os.path.abspath(directory)),
                                    "pipeline_state.json"))
    options = state.get("options") if isinstance(state, dict) else None
    prompt = state.get("prompt") if isinstance(state, dict) else None
    return {
        "handoff": directory,
        "prompt": prompt if isinstance(prompt, str) else "",
        "research_report": report,
        "actors": actors if isinstance(actors, dict) else None,
        "timeline": timeline if isinstance(timeline, list) else None,
        "quantitative": quantitative if isinstance(quantitative, list) else None,
        "sources": sources if isinstance(sources, list) else [],
        "hindcast": hindcast_policy(options),
    }


def _agent(handoff: Dict[str, Any]) -> ReportAgent:
    """A ReportAgent carrying only the fields the packs read (no LLM client, no graph)."""
    agent = ReportAgent.__new__(ReportAgent)
    agent.research_report = handoff["research_report"]
    agent.actors = handoff["actors"]
    agent.timeline_events = handoff["timeline"] or None
    agent.quantitative = handoff["quantitative"] or None
    agent.hindcast = handoff["hindcast"]
    agent.simulation_id = None
    # FU-4: the spine pack builds REPORT-8's verified-figures block from these, as a report
    # does: sources.json resolves its [S#] tags, and it is rendered in the language
    # ReportAgent.__init__ resolves from the pipeline prompt, the dossier and the brief.
    agent.sources = handoff.get("sources") or []
    agent.output_language = ReportAgent.resolve_output_language(
        handoff.get("prompt") or "", handoff["research_report"],
        actors_utils.situation_brief(handoff["actors"]))
    return agent


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text or "")


def _excluded_lines(sections: Sequence[cp.Section]) -> List[str]:
    """Lines (>= 20 chars) of excluded sections that occur in no other section."""
    elsewhere = {line.strip() for sec in sections if sec.cls != cp.CLASS_EXCLUDED
                 for line in sec.text.split("\n")}
    lines: List[str] = []
    seen = set()
    for sec in sections:
        if sec.cls != cp.CLASS_EXCLUDED:
            continue
        for line in sec.text.split("\n"):
            stripped = line.strip()
            if len(stripped) >= _MIN_LINE_CHARS and stripped not in elsewhere and stripped not in seen:
                seen.add(stripped)
                lines.append(stripped)
    return lines


def _references_chars(context: str, excluded_lines: Sequence[str]) -> int:
    return sum(len(line) for line in excluded_lines if line in context)


def _analyst_headings(sections: Sequence[cp.Section]) -> Tuple[str, List[str]]:
    """The heading lines of the run's analyst binary/resolution-ready section: its
    analyst-class H1/H2 sections ("section"), else the analyst-class H3-H6 headings inside
    packable sections ("sub_heading": pipe_0f2b's "### Part 1 — Forecasts (12 binary calls
    …)" sits under a body H2); ("", []) when the dossier has none."""
    top = [sec.text.split("\n", 1)[0] for sec in sections if sec.cls == cp.CLASS_ANALYST_FORECASTS]
    if top:
        return "section", top
    sub = [line for sec in sections if sec.cls != cp.CLASS_EXCLUDED
           for line, text in cp.sub_headings(sec)
           if cp.classify_heading(text) == cp.CLASS_ANALYST_FORECASTS]
    return ("sub_heading", sub) if sub else ("", [])


def _analyst_present(context: str, headings: Sequence[str]) -> Dict[str, Any]:
    present = [line in context for line in headings]
    return {"analyst_sections_present": sum(present),
            "analyst_section_present": any(present) if headings else None,
            "analyst_headings": [{"heading": line, "present": hit}
                                 for line, hit in zip(headings, present, strict=True)]}


def _newest_past_row(timeline: Any, as_of: Optional[date]) -> Optional[Dict[str, Any]]:
    """The newest timeline row dated on or before as_of, found without the lane code (so the
    metric can catch a lane ordering or classification bug): each row's period from
    parse_dated_period, kept when it ended on or before as_of, the greatest end then the
    latest start. Every row tied on both is a candidate (the lane breaks that tie on the
    event text); None when no row qualifies."""
    if as_of is None:
        return None
    best: Optional[Tuple[date, date]] = None
    tied: List[Tuple[str, str]] = []
    for row in timeline if isinstance(timeline, list) else []:
        if not isinstance(row, dict):
            continue
        event = _squash(unicodedata.normalize("NFKC", str(row.get("event") or ""))).strip()
        raw_date = _squash(unicodedata.normalize("NFKC", str(row.get("date") or ""))).strip()
        period = cp.parse_dated_period(raw_date) if event and raw_date else None
        if period is None or period.end > as_of:
            continue
        key = (period.end, period.start)
        if best is None or key > best:
            best, tied = key, []
        if key == best:
            tied.append((event, raw_date))
    if best is None:
        return None
    tied.sort(key=lambda pair: (pair[0].casefold(), pair[0], pair[1]))
    probes = sorted({event[:_EVENT_PROBE_CHARS] for event, _raw in tied})
    return {"date": tied[0][1], "days_before_as_of": (as_of - best[0]).days,
            "probe": tied[0][0][:_EVENT_PROBE_CHARS], "tied_rows": len(tied), "probes": probes}


def _row_in(context: str, newest: Optional[Dict[str, Any]]) -> Optional[bool]:
    if newest is None:
        return None
    squashed = _squash(context)
    return any(probe in squashed for probe in newest["probes"])


def _pack_metrics(result: Any, excluded_lines: Sequence[str],
                  newest: Optional[Dict[str, Any]], legacy_chars: int) -> Dict[str, Any]:
    telemetry = result.telemetry
    lanes = telemetry.get("lanes") or {}
    audit = lanes.get("audit") or {}
    streams = {name: {k: row.get(k) for k in ("raw_chars", "kept_chars", "sections_kept",
                                              "sections_dropped", "truncated")}
               for name, row in (telemetry.get("streams") or {}).items()}
    return {
        "status": result.status,
        "chars": len(result.text),
        "growth_chars": len(result.text) - legacy_chars if result.ok else 0,
        "references_chars": _references_chars(result.text, excluded_lines),
        "newest_past_row_in_lane": _row_in(result.text, newest) if result.ok else None,
        "streams": streams,
        "audit_violations": len(audit.get("violations") or []),
        "withheld_segments": list(audit.get("withheld_segments") or []),
        "post_as_of_rows_withheld": (lanes.get("scheduled") or {}).get("post_as_of_rows_withheld"),
        "scheduled_guard": (lanes.get("scheduled") or {}).get("guard"),
        "input_sha256": result.input_sha256,
        "text_sha256": result.text_sha256,
    }


def _replay_now(as_of_raw: Any, now: Optional[datetime]) -> Tuple[datetime, str]:
    """The replay date of one handoff and how it was chosen: ``now`` when fixed, else the
    handoff's as_of day (noon UTC), else today when that as_of is not a single day."""
    if now is not None:
        return now, "fixed"
    period = cp.parse_dated_period(as_of_raw)
    if period is not None and period.precision == "day":
        return datetime.combine(period.start, time(12, 0), tzinfo=timezone.utc), "as_of"
    return datetime.now(timezone.utc), "today"


def replay_handoff(handoff: Dict[str, Any], now: Optional[datetime] = None) -> Dict[str, Any]:
    """Legacy vs packed metrics for one loaded handoff (see the module docstring); ``now``
    None replays it at its own as_of day."""
    agent = _agent(handoff)
    report = handoff["research_report"]
    sections = cp.split_h2(report)
    analyst_level, analyst = _analyst_headings(sections)
    excluded = _excluded_lines(sections)
    as_of_raw, as_of_source = agent._context_pack_as_of()
    now, now_mode = _replay_now(as_of_raw, now)
    as_of = cp.validate_pack_as_of(as_of_raw, now)
    newest = _newest_past_row(agent._context_pack_timeline(), as_of)

    brief = actors_utils.situation_brief(handoff["actors"]) if handoff["actors"] else ""
    head_ratio = float(getattr(Config, "FORECAST_EXTRACT_HEAD_RATIO", 0.6))
    legacy_dossier = slice_head_tail(report, int(getattr(Config, "FORECAST_BINARY_EXTRACT_BUDGET",
                                                         48000)), head_ratio)
    legacy_binary = (f"[Situation brief]\n{brief[:2000]}\n\n" if brief else "") + legacy_dossier
    legacy_spine = brief[:int(getattr(Config, "REPORT_SPINE_INPUT_CAP_BRIEF", 2000))]

    binary, binary_provenance = agent._context_pack_result("binary", now=now)
    spine, spine_provenance = agent._context_pack_result("spine", now=now)
    binary_packed = _pack_metrics(binary, excluded, newest, len(legacy_binary))
    binary_packed.update(_analyst_present(binary.text, analyst))
    binary_legacy = {"chars": len(legacy_binary),
                     "references_chars": _references_chars(legacy_binary, excluded),
                     "newest_past_row_in_lane": _row_in(legacy_binary, newest),
                     **_analyst_present(legacy_binary, analyst)}
    return {
        "handoff": handoff["handoff"],
        "dossier_chars": len(report),
        "as_of": as_of.isoformat() if as_of else None,
        "as_of_raw": None if as_of_raw is None else str(as_of_raw),
        "as_of_source": as_of_source,
        "now": now.date().isoformat(),
        "now_mode": now_mode,
        "analyst_sections": len(analyst),
        "analyst_level": analyst_level or None,
        "newest_past_row": newest,
        "binary": {"legacy": binary_legacy, "packed": binary_packed},
        "spine": {
            "legacy": {"chars": len(legacy_spine),
                       "references_chars": _references_chars(legacy_spine, excluded),
                       "newest_past_row_in_lane": _row_in(legacy_spine, newest)},
            "packed": _pack_metrics(spine, excluded, newest, len(legacy_spine)),
        },
        "provenance": {"binary": binary_provenance, "spine": spine_provenance},
        "_texts": {"binary": binary.text, "spine": spine.text},
    }


def summarize(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The replay acceptance checks over every handoff whose pack was built (status ok)."""
    summary: Dict[str, Any] = {"handoffs": len(rows)}
    for kind in ("binary", "spine"):
        packed = [r[kind]["packed"] for r in rows if r[kind]["packed"]["status"] == cp.STATUS_OK]
        checks = {
            "packed_runs": len(packed),
            "fallback_runs": len(rows) - len(packed),
            "zero_references_chars": all(p["references_chars"] == 0 for p in packed),
            "newest_past_row_in_every_lane": all(p["newest_past_row_in_lane"] is not False
                                                 for p in packed),
            "temporal_audit_clean": all(p["audit_violations"] == 0 for p in packed),
            "max_growth_chars": max((p["growth_chars"] for p in packed), default=0),
        }
        if kind == "binary":
            checks["analyst_section_in_every_run_with_one"] = all(
                p["analyst_section_present"] is not False for p in packed)
        summary[kind] = checks
    return summary


def _fmt(value: Any) -> str:
    return "-" if value is None else str(value)


def _print_text(rows: Sequence[Dict[str, Any]], summary: Dict[str, Any], show_text: bool) -> None:
    for row in rows:
        print(f"== {row['handoff']}  dossier={row['dossier_chars']}  as_of={_fmt(row['as_of'])}"
              f" ({row['as_of_source']})  now={row['now']} ({row['now_mode']})"
              f"  analyst_sections={row['analyst_sections']} ({_fmt(row['analyst_level'])})")
        for kind in ("binary", "spine"):
            legacy, packed = row[kind]["legacy"], row[kind]["packed"]
            print(f"  {kind:6s} legacy: chars={legacy['chars']} refs={legacy['references_chars']}"
                  f" analyst={_fmt(legacy.get('analyst_section_present'))}"
                  f" newest_row={_fmt(legacy['newest_past_row_in_lane'])}")
            print(f"  {kind:6s} packed: status={packed['status']} chars={packed['chars']}"
                  f" growth={packed['growth_chars']} refs={packed['references_chars']}"
                  f" analyst={_fmt(packed.get('analyst_section_present'))}"
                  f" newest_row={_fmt(packed['newest_past_row_in_lane'])}"
                  f" audit_violations={packed['audit_violations']}"
                  f" scheduled={_fmt(packed['scheduled_guard'])}"
                  f" withheld={_fmt(packed['post_as_of_rows_withheld'])}")
            sizes = ", ".join(f"{name} {s['kept_chars']}/{s['raw_chars']}"
                              for name, s in packed["streams"].items())
            if sizes:
                print(f"         streams kept/raw: {sizes}")
            if show_text:
                print(row["_texts"][kind])
    print("== summary")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


@contextlib.contextmanager
def _stdout_reserved() -> Iterator[None]:
    """Keep stdout for the replay's own output while the replay runs: console log handlers
    bound to stdout (app/utils/logger.py's, e.g. the INFO line REPORT-8's verified-figures
    builder logs for the spine pack) write to stderr, as does anything printed, so ``--json``
    stays one parseable document. The handlers get their stream back afterwards."""
    stdout = [stream for stream in (sys.stdout, sys.__stdout__) if stream is not None]
    loggers = [logging.getLogger(), *(lg for lg in logging.Logger.manager.loggerDict.values()
                                      if isinstance(lg, logging.Logger))]
    moved: List[Tuple[logging.StreamHandler, Any]] = []
    for lg in loggers:
        for handler in lg.handlers:
            if (isinstance(handler, logging.StreamHandler)
                    and any(handler.stream is stream for stream in stdout)):
                moved.append((handler, handler.stream))
                handler.setStream(sys.stderr)
    try:
        with contextlib.redirect_stdout(sys.stderr):
            yield
    finally:
        for handler, stream in moved:
            handler.setStream(stream)


def _now_arg(value: str) -> Optional[datetime]:
    """``--now``: None for the per-handoff as_of mode, else the fixed replay day (noon UTC);
    anything else is a usage error."""
    text = value.strip()
    if text.lower() == "as_of":
        return None
    try:
        day = date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected 'as_of' or a YYYY-MM-DD date, got {value!r}") from None
    return datetime.combine(day, time(12, 0), tzinfo=timezone.utc)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--handoff", nargs="+", required=True, metavar="DIR",
                        help="handoff directories (or pipeline directories holding handoff/)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON")
    parser.add_argument("--now", type=_now_arg, default="as_of",
                        help="replay date: 'as_of' (default: each handoff's own as_of day, as a "
                             "live report ran) or a fixed YYYY-MM-DD")
    parser.add_argument("--show-text", action="store_true",
                        help="include each pack's text (for the manual prompt review)")
    args = parser.parse_args(argv)
    now = args.now
    rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []
    with _stdout_reserved():
        for path in args.handoff:
            try:
                rows.append(replay_handoff(load_handoff(path), now))
            except Exception as exc:  # noqa: BLE001 — one unreadable handoff must not hide the rest
                errors.append({"handoff": path, "error": f"{type(exc).__name__}: {exc}"})
    summary = summarize(rows)
    if args.json:
        payload_rows = [{k: v for k, v in row.items() if k != "_texts"} for row in rows]
        if args.show_text:
            for payload, row in zip(payload_rows, rows, strict=True):
                payload["texts"] = row["_texts"]
        print(json.dumps({"now": now.date().isoformat() if now else "as_of",
                          "handoffs": payload_rows, "errors": errors, "summary": summary},
                         ensure_ascii=False, indent=2))
    else:
        _print_text(rows, summary, args.show_text)
        for err in errors:
            print(f"!! {err['handoff']}: {err['error']}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
