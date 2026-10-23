#!/usr/bin/env python3
"""Backtest driver: run golden questions through the pipeline at their as-of dates
and score the forecasts per ablation arm (design: docs/handoff/backtest/design.md).

    plan            questions × arms, the request each pipeline gets, no network
    run             submit them to a backend (POST /api/v1/run with a ``backtest``
                    block), wait, record runs.jsonl; refuses without --confirm-paid
    score           map each report's binary forecasts to its golden question and
                    write eval_report.json (+ markdown): Brier, log score, ECE and
                    accuracy per arm, the model-knowledge split, paired deltas
                    against research_only
    forward-check   validate a 2–12-week forward question file, print its prompts
    forward-score   score the live binaries the resolution monitor has resolved
    forward-enroll  freeze a two-arm prospective design before forecast deadlines
    forward-record  bind a published binary or a final failed/abstained/void disposition

Use forward-score --enrollment PATH for the full prospective denominator. Enrollment
and recording are local-only; neither command starts a pipeline or acquires outcomes.
All three forward commands accept --ledger-dir for the same publication registry.
Enrollment and new prediction bindings reject settlements already known anywhere
in that registry, including terminal market anchors. Late failure accounting remains available.
The design contains cohort_id, policy_version, two arms (id/method/budget_usd), a
contrast (kind/baseline/candidate), and questions (question_id/event_family_id,
statement/resolution_criteria, forecast_due_at/outcome_not_before/resolution_date,
resolution_source with kind and the exact published anchor). Equal-cost contrasts
also require cost_tolerance_usd; investigation requires practical_brier_margin.
Official-data anchors require frequency (D/W/M/Q/A); their sources require
outcome_vintage (an exact YYYY-MM-DD outcome dataset
vintage, separate from the forecast anchor's provenance). Publications must carry
the enrolled resolution_date; market deadlines can also use the registry's date
extraction. Unsupported or mismatched outcome vintages remain unscored.
Trial JSON contains question_id, arm, status and all disjoint costs_usd components:
acquisition/simulation/verification/retries/failures/synthesis (null means unknown).
Published trials additionally require report_id, forecast_id, evidence_sha256 and
forecast_request_sha256. Other terminal dispositions require a reason. Publication
bindings must be recorded before forecast_due_at, and cannot be revised afterward.
A published trial may later receive one void/disputed disposition through
forward-record, preserving its costs and original probability with an explicit reason.

Every backtest pipeline cuts its inputs at the question's ``as_of_date`` (search,
fetch, official data, market prices); the LLM's own training knowledge is not cut,
so ``score`` reports the knowledge split of golden_eval.py.  A run costs one full
pipeline per question and arm: ``run`` caps the batch (--max-pipelines) and needs
--confirm-paid.  Example::

    python backend/scripts/backtest_eval.py plan --ids us-pres-2024-trump,fed-2024-09-cut
    python backend/scripts/backtest_eval.py run --ids us-pres-2024-trump --arms research_only,markets \\
        --base-url http://127.0.0.1:5011 --run-dir backtest_runs/2026-10-21 --confirm-paid
    python backend/scripts/backtest_eval.py score --run-dir backtest_runs/2026-10-21 \\
        --model-knowledge-cutoff 2025-06-30 -o eval_report.json --markdown eval_report.md
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import golden_eval as ge  # noqa: E402
from app.services.backtest_mode import ABLATION_ARMS, ARMS  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FORWARD_TEMPLATE = os.path.join(REPO_ROOT, "backend", "tests", "eval", "forward_questions_template.json")
BASELINE_ARM = "research_only"
TERMINAL = ("completed", "failed", "cancelled")
DEFAULT_MAX_PIPELINES = 8
FORWARD_MIN_DAYS, FORWARD_MAX_DAYS = 14, 84
MANIFEST = "runs.jsonl"


@dataclass(frozen=True)
class Profile:
    """The cheap backtest profile every pipeline of a batch runs at."""
    depth: str = "quick"
    max_rounds: int = 4
    language: str = "English"
    strict: bool = True
    archive: str = "wayback"


# ============================================================ requests

def build_prompt(question: Mapping[str, Any]) -> str:
    """The pipeline prompt for one golden question at its as-of date."""
    as_of = question["as_of_date"]
    lines = [f"Forecast question (backtest as of {as_of}): {question['question']}"]
    if question.get("resolution_criteria"):
        lines.append(f"Resolution criteria: {question['resolution_criteria']}")
    if question.get("resolution_date"):
        lines.append(f"Resolves on: {question['resolution_date']}")
    lines.append(f"Treat {as_of} as today. Use only information published on or before {as_of} and no "
                 "knowledge of later events. Give a calibrated probability that the question resolves YES.")
    return "\n".join(lines)


def build_request(question: Mapping[str, Any], arm: str, profile: Profile, *, label: str = "") -> dict:
    """The POST /api/v1/run body for one question and arm."""
    if arm not in ARMS:
        raise ValueError(f"unknown arm {arm!r}")
    return {
        "prompt": build_prompt(question), "mode": "full", "depth": profile.depth,
        "max_rounds": profile.max_rounds, "language": profile.language,
        "backtest": {
            "as_of": question["as_of_date"], "strict": profile.strict, "archive": profile.archive, "arm": arm,
            "target": {"golden_id": question["id"], "question": question["question"],
                       "resolution_criteria": question.get("resolution_criteria") or "",
                       "resolution_date": question.get("resolution_date")},
            "run_label": label[:120],
        },
    }


def select_questions(questions: Sequence[Mapping[str, Any]], ids: Optional[Sequence[str]] = None,
                     limit: Optional[int] = None) -> List[Mapping[str, Any]]:
    """The questions named by ``ids`` (in that order; unknown ids raise), else the
    first ``limit`` ones, else all."""
    if ids:
        index = ge.index_golden([dict(q) for q in questions])
        missing = [gid for gid in ids if gid not in index]
        if missing:
            raise ValueError(f"unknown golden id(s): {', '.join(missing)}")
        return [index[gid] for gid in ids]
    return list(questions)[:limit] if limit else list(questions)


def parse_arms(text: Optional[str]) -> List[str]:
    arms = [arm.strip() for arm in str(text or ",".join(ABLATION_ARMS)).split(",") if arm.strip()]
    unknown = [arm for arm in arms if arm not in ARMS]
    if unknown:
        raise ValueError(f"unknown arm(s): {', '.join(unknown)} (choose from {', '.join(ARMS)})")
    return list(dict.fromkeys(arms))


# ============================================================ mapping

_STOPWORDS = frozenset("""
a an the and or of to in on at by for with from as is are was were be been being will would
shall should can could may might do does did this that these those it its their his her than
then there what which who whom whose when where how whether if yes no vs via per into over under
""".split())
_NEGATIONS = frozenset({"not", "never", "fail", "fails", "failed", "without", "neither", "nor",
                        "won't", "doesn't", "isn't", "aren't", "cannot", "can't", "no"})
_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9'.-]*")
LEXICAL_MIN = 0.75
LEXICAL_MARGIN = 0.10


def _tokens(text: Any) -> List[str]:
    return [token.strip(".-'") for token in _TOKEN_RE.findall(str(text or "").lower())]


def content_tokens(text: Any) -> set:
    """Lower-cased content words and numbers, light plural stripping."""
    out = set()
    for token in _tokens(text):
        if not token or token in _STOPWORDS or token in _NEGATIONS:
            continue
        if not token[0].isdigit() and len(token) < 3:
            continue
        out.add(token[:-1] if len(token) > 3 and token.endswith("s") and not token.endswith("ss") else token)
    return out


def negated(text: Any) -> bool:
    return any(token in _NEGATIONS for token in _tokens(text))


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def map_forecast(binaries: Sequence[Mapping[str, Any]], question: Mapping[str, Any], *,
                 lexical: bool = True) -> Dict[str, Any]:
    """The binary forecast that answers ``question``, and how it was found.

    Exact keys first: ``golden_id`` (the pinned question the report stage marks),
    ``proposition_id`` (its slug), ``id``.  Otherwise, when ``lexical``, the
    statement covering at least ``LEXICAL_MIN`` of the question's content words,
    ahead of the runner-up by ``LEXICAL_MARGIN``, and agreeing on negation.
    Returns ``{row, method, score}`` or ``{row: None, reason, best_score}``."""
    gid = str(question["id"])
    rows = [row for row in binaries if isinstance(row, Mapping)]
    for method, matches in (("golden_id", lambda row: str(row.get("golden_id") or "") == gid),
                            ("proposition_id", lambda row: str(row.get("proposition_id") or "") == _slug(gid)),
                            ("id", lambda row: str(row.get("id") or "").strip() == gid)):
        hits = [row for row in rows if matches(row)]
        if hits:
            return {"row": hits[0], "method": method, "score": 1.0, "duplicates": len(hits) - 1}
    if not lexical:
        return {"row": None, "reason": "no_exact_match", "best_score": None}
    wanted = content_tokens(question.get("question"))
    if not wanted:
        return {"row": None, "reason": "no_question_words", "best_score": None}
    ranked = sorted(((len(wanted & content_tokens(row.get("statement"))) / len(wanted), index, row)
                     for index, row in enumerate(rows)), key=lambda item: (-item[0], item[1]))
    if not ranked or ranked[0][0] < LEXICAL_MIN:
        return {"row": None, "reason": "no_match", "best_score": round(ranked[0][0], 3) if ranked else None}
    best, _, row = ranked[0]
    if len(ranked) > 1 and best - ranked[1][0] < LEXICAL_MARGIN:
        return {"row": None, "reason": "ambiguous", "best_score": round(best, 3)}
    if negated(question.get("question")) != negated(row.get("statement")):
        return {"row": None, "reason": "negation_mismatch", "best_score": round(best, 3)}
    return {"row": row, "method": "lexical", "score": round(best, 3), "duplicates": 0}


# ============================================================ runs

class ApiTransport:
    """JSON over HTTP to a backend's SDK routes (``/api/v1``)."""

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Any = None) -> Tuple[int, Any]:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.base_url + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 — operator URL
                return response.status, json.loads(response.read().decode("utf-8") or "null")
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read().decode("utf-8") or "null")
            except ValueError:
                return exc.code, None

    def post(self, path: str, body: Any) -> Tuple[int, Any]:
        return self._call("POST", path, body)

    def get(self, path: str) -> Tuple[int, Any]:
        return self._call("GET", path)


def read_manifest(run_dir: str) -> List[Dict[str, Any]]:
    """Latest record per (golden_id, arm) in ``runs.jsonl`` (append-only)."""
    latest: Dict[Tuple[str, str], Dict[str, Any]] = {}
    path = os.path.join(run_dir, MANIFEST)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and row.get("golden_id") and row.get("arm"):
                latest[(row["golden_id"], row["arm"])] = row
    return list(latest.values())


def _append_manifest(run_dir: str, row: Mapping[str, Any]) -> None:
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, MANIFEST), "a", encoding="utf-8") as stream:
        stream.write(json.dumps(dict(row), ensure_ascii=False, sort_keys=True) + "\n")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_batch(questions: Sequence[Mapping[str, Any]], arms: Sequence[str], profile: Profile, *,
              transport: Any, run_dir: str, label: str = "", poll_seconds: float = 30.0,
              timeout_seconds: float = 6 * 3600.0, sleep: Callable[[float], None] = time.sleep,
              clock: Callable[[], float] = time.monotonic, log: Callable[[str], None] = print) -> List[Dict[str, Any]]:
    """Run each (question, arm) one pipeline at a time; resumable.

    A pair already completed in the manifest is skipped; one recorded as
    submitted is polled again instead of being submitted twice.  Every state
    change is appended to ``runs.jsonl``.  Returns the final records."""
    done = {(row["golden_id"], row["arm"]): row for row in read_manifest(run_dir)}
    results: List[Dict[str, Any]] = []
    for question in questions:
        for arm in arms:
            key = (question["id"], arm)
            record = dict(done.get(key) or {})
            if record.get("status") == "completed":
                log(f"skip {key[0]} / {arm}: completed ({record.get('report_id')})")
                results.append(record)
                continue
            if record.get("status") not in ("submitted", "running"):
                status, body = transport.post("/api/v1/run", build_request(question, arm, profile, label=label))
                data = (body or {}).get("data") if isinstance(body, dict) else None
                if status != 200 or not isinstance(data, dict) or not data.get("pipeline_id"):
                    error = (body or {}).get("error") if isinstance(body, dict) else None
                    record = {"golden_id": key[0], "arm": arm, "status": "rejected", "http_status": status,
                              "error": str(error or body)[:500], "at": _now()}
                    _append_manifest(run_dir, record)
                    log(f"rejected {key[0]} / {arm}: HTTP {status} {record['error']}")
                    results.append(record)
                    continue
                record = {"golden_id": key[0], "arm": arm, "status": "submitted",
                          "pipeline_id": data["pipeline_id"], "as_of": question["as_of_date"], "at": _now()}
                _append_manifest(run_dir, record)
                log(f"submitted {key[0]} / {arm}: {record['pipeline_id']}")
            record = _wait(record, transport=transport, poll_seconds=poll_seconds, timeout_seconds=timeout_seconds,
                           sleep=sleep, clock=clock)
            _append_manifest(run_dir, record)
            log(f"{record['status']} {key[0]} / {arm}: report {record.get('report_id')}")
            results.append(record)
    return results


def _wait(record: Dict[str, Any], *, transport: Any, poll_seconds: float, timeout_seconds: float,
          sleep: Callable[[float], None], clock: Callable[[], float]) -> Dict[str, Any]:
    started = clock()
    while True:
        status, body = transport.get(f"/api/v1/status/{record['pipeline_id']}")
        data = (body or {}).get("data") if isinstance(body, dict) else None
        if status == 200 and isinstance(data, dict) and data.get("status") in TERMINAL:
            return {**record, "status": data["status"], "report_id": data.get("report_id"),
                    "simulation_id": data.get("simulation_id"), "error": data.get("error"), "at": _now()}
        if clock() - started > timeout_seconds:
            return {**record, "status": "timed_out", "error": f"no terminal status after {timeout_seconds:.0f}s",
                    "at": _now()}
        sleep(poll_seconds)


# ============================================================ scoring

def _reports_dir(override: Optional[str]) -> str:
    if override:
        return override
    from app.config import Config
    return os.path.join(Config.UPLOAD_FOLDER, "reports")


def load_forecast(reports_dir: str, report_id: Any) -> Optional[Dict[str, Any]]:
    rid = str(report_id or "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", rid):
        return None
    try:
        with open(os.path.join(reports_dir, rid, "forecast.json"), encoding="utf-8") as stream:
            value = json.load(stream)
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _paired_delta(arm_rows: Mapping[str, Mapping[str, Any]], base_rows: Mapping[str, Mapping[str, Any]]) -> dict:
    shared = sorted(set(arm_rows) & set(base_rows))
    if not shared:
        return {"n_pairs": 0}
    brier = [arm_rows[gid]["brier"] - base_rows[gid]["brier"] for gid in shared]
    logs = [arm_rows[gid]["log_score"] - base_rows[gid]["log_score"] for gid in shared]
    return {"n_pairs": len(shared),
            "mean_brier_delta": round(sum(brier) / len(brier), 4),           # < 0 = the arm is better
            "mean_log_score_delta": round(sum(logs) / len(logs), 4),         # > 0 = the arm is better
            "better": sum(1 for value in brier if value < 0), "worse": sum(1 for value in brier if value > 0),
            "ties": sum(1 for value in brier if value == 0), "ids": shared}


def score_runs(records: Iterable[Mapping[str, Any]], golden: Sequence[Mapping[str, Any]], *,
               forecast_loader: Callable[[Any], Optional[Dict[str, Any]]], model_cutoff: Optional[str] = None,
               bins: int = ge.DEFAULT_BINS, lexical: bool = True) -> Dict[str, Any]:
    """The ``eval_report.json`` body for a set of run records (pure apart from the loader)."""
    index = ge.index_golden([dict(q) for q in golden])
    by_arm: Dict[str, Dict[str, Any]] = {}
    questions_out: List[Dict[str, Any]] = []
    for record in sorted(records, key=lambda row: (str(row.get("arm")), str(row.get("golden_id")))):
        arm, gid = str(record.get("arm")), str(record.get("golden_id"))
        bucket = by_arm.setdefault(arm, {"flags": dict(ARMS.get(arm, {})), "runs": 0, "completed": 0,
                                         "rows": [], "unmatched": [], "not_scored": [], "methods": {}})
        bucket["runs"] += 1
        question = index.get(gid)
        if question is None:
            bucket["not_scored"].append({"id": gid, "reason": "not_in_golden_set"})
            continue
        if record.get("status") != "completed" or not record.get("report_id"):
            reason = "no_report" if record.get("status") == "completed" else f"run_{record.get('status')}"
            bucket["not_scored"].append({"id": gid, "reason": reason, "error": record.get("error")})
            continue
        bucket["completed"] += 1
        forecast = forecast_loader(record["report_id"])
        if forecast is None:
            bucket["not_scored"].append({"id": gid, "reason": "forecast_missing", "report_id": record["report_id"]})
            continue
        block = forecast.get("backtest") if isinstance(forecast.get("backtest"), dict) else None
        if block is None or block.get("as_of") != question.get("as_of_date"):
            # A report without the cutoff (or another one) is not evidence of this backtest.
            bucket["not_scored"].append({"id": gid, "reason": "not_a_backtest_forecast_for_this_question",
                                         "report_id": record["report_id"]})
            continue
        mapping = map_forecast(ge.extract_binary_forecasts(forecast), question, lexical=lexical)
        row = mapping.get("row")
        probability = ge._coerce_prob(row.get("probability")) if row else None
        if row is None or probability is None:
            bucket["unmatched"].append({"id": gid, "report_id": record["report_id"],
                                        "reason": mapping.get("reason") or "invalid_probability",
                                        "best_score": mapping.get("best_score")})
            continue
        outcome = bool(question["resolved_outcome"])
        scored = {"id": gid, "probability": probability, "outcome": outcome,
                  "category": question.get("category"), "difficulty": question.get("difficulty"),
                  "knowledge_cutoff": question.get("knowledge_cutoff"),
                  "brier": round(ge.binary_brier(probability, outcome), 4),
                  "log_score": round(ge.binary_log_score(probability, outcome), 4)}
        bucket["rows"].append(scored)
        bucket["methods"][mapping["method"]] = bucket["methods"].get(mapping["method"], 0) + 1
        questions_out.append({**scored, "arm": arm, "pipeline_id": record.get("pipeline_id"),
                              "report_id": record["report_id"], "statement": row.get("statement"),
                              "match_method": mapping["method"], "match_score": mapping["score"],
                              "knowledge_group": ge.knowledge_group(question.get("knowledge_cutoff"), model_cutoff)})
    arms_out: Dict[str, Any] = {}
    for arm, bucket in by_arm.items():
        arms_out[arm] = {"flags": bucket["flags"], "runs": bucket["runs"], "completed": bucket["completed"],
                         "scored": len(bucket["rows"]), "match_methods": bucket["methods"],
                         "metrics": ge.score_pairs(bucket["rows"], bins=bins),
                         "knowledge_split": ge.knowledge_split(bucket["rows"], model_cutoff, bins=bins),
                         "unmatched": bucket["unmatched"], "not_scored": bucket["not_scored"]}
    deltas = {}
    base = {row["id"]: row for row in by_arm.get(BASELINE_ARM, {}).get("rows", [])}
    for arm, bucket in by_arm.items():
        if arm != BASELINE_ARM:
            deltas[arm] = _paired_delta({row["id"]: row for row in bucket["rows"]}, base)
    return {"mode": "backtest-eval", "generated_at": _now(), "golden_count": len(golden),
            "model_knowledge_cutoff": model_cutoff, "lexical_mapping": lexical,
            "leakage_note": ("Inputs were cut at each question's as-of date; the model's training knowledge "
                             "was not. Compare knowledge_split groups: only post_model_cutoff is clean."),
            "arms": arms_out,
            "ablation": {"baseline": BASELINE_ARM, "order": [arm for arm in ARMS if arm in by_arm],
                         "deltas": deltas,
                         "reading": "mean_brier_delta < 0 and mean_log_score_delta > 0 mean the arm beat "
                                    "research_only on the same questions"},
            "questions": questions_out}


def render_markdown(report: Mapping[str, Any]) -> str:
    fmt = ge._fmt
    lines = ["# Backtest evaluation", "",
             f"- generated: {report.get('generated_at')}",
             f"- golden questions: {report.get('golden_count')}",
             f"- model knowledge cutoff: {report.get('model_knowledge_cutoff') or 'not given'}",
             f"- {report.get('leakage_note')}", "",
             "## Per arm", "",
             "| arm | markets | simulation | world channel | runs | scored | Brier | log score | ECE | accuracy |",
             "|---|---|---|---|---|---|---|---|---|---|"]
    order = (report.get("ablation") or {}).get("order") or list((report.get("arms") or {}).keys())
    for arm in order:
        data = report["arms"][arm]
        flags, metrics = data.get("flags") or {}, data.get("metrics") or {}
        lines.append(f"| {arm} | {flags.get('markets')} | {flags.get('simulation')} | {flags.get('world_channel')} "
                     f"| {data.get('runs')} | {data.get('scored')} | {fmt(metrics.get('mean_brier'))} "
                     f"| {fmt(metrics.get('mean_log_score'))} | {fmt((metrics.get('calibration') or {}).get('ece'))} "
                     f"| {fmt(metrics.get('resolution_accuracy'))} |")
    deltas = (report.get("ablation") or {}).get("deltas") or {}
    if deltas:
        lines += ["", f"## Paired against {BASELINE_ARM}", "",
                  "| arm | pairs | Brier Δ (<0 better) | log Δ (>0 better) | better | worse | ties |",
                  "|---|---|---|---|---|---|---|"]
        for arm in order:
            if arm in deltas:
                d = deltas[arm]
                lines.append(f"| {arm} | {d.get('n_pairs')} | {fmt(d.get('mean_brier_delta'))} "
                             f"| {fmt(d.get('mean_log_score_delta'))} | {d.get('better', '—')} "
                             f"| {d.get('worse', '—')} | {d.get('ties', '—')} |")
    lines += ["", "## Model-knowledge split", "", "| arm | group | n | Brier | log score |", "|---|---|---|---|---|"]
    for arm in order:
        groups = ((report["arms"][arm].get("knowledge_split") or {}).get("groups") or {})
        for name in ge.KNOWLEDGE_GROUPS:
            g = groups.get(name) or {}
            if g.get("n"):
                lines.append(f"| {arm} | {name} | {g.get('n')} | {fmt(g.get('mean_brier'))} "
                             f"| {fmt(g.get('mean_log_score'))} |")
    lines += ["", "## Questions", "", "| arm | id | p(YES) | outcome | Brier | match |", "|---|---|---|---|---|---|"]
    for row in report.get("questions") or []:
        lines.append(f"| {row['arm']} | {row['id']} | {row['probability']:.2f} | {'YES' if row['outcome'] else 'NO'} "
                     f"| {fmt(row['brier'])} | {row['match_method']} |")
    problems = [(arm, item) for arm in order for key in ("unmatched", "not_scored")
                for item in report["arms"][arm].get(key) or []]
    if problems:
        lines += ["", "## Not scored", "", "| arm | id | reason |", "|---|---|---|"]
        lines += [f"| {arm} | {item.get('id')} | {item.get('reason')} |" for arm, item in problems]
    return "\n".join(lines) + "\n"


# ============================================================ forward testing

def load_forward_questions(path: str) -> List[Dict[str, Any]]:
    with open(path, encoding="utf-8") as stream:
        data = json.load(stream)
    questions = data.get("questions") if isinstance(data, dict) else data
    if not isinstance(questions, list):
        raise ValueError(f"{path}: no 'questions' list")
    return [q for q in questions if isinstance(q, dict)]


def check_forward_question(question: Mapping[str, Any]) -> List[str]:
    """Problems that keep a forward question from resolving in 2–12 weeks unattended."""
    problems = []
    for name in ("id", "question", "resolution_criteria", "asked_on", "resolution_date"):
        if not str(question.get(name) or "").strip():
            problems.append(f"missing {name}")
    try:
        asked = date.fromisoformat(str(question.get("asked_on")))
        resolves = date.fromisoformat(str(question.get("resolution_date")))
        horizon = (resolves - asked).days
        if not FORWARD_MIN_DAYS <= horizon <= FORWARD_MAX_DAYS:
            problems.append(f"horizon {horizon} days is outside {FORWARD_MIN_DAYS}-{FORWARD_MAX_DAYS}")
    except ValueError:
        problems.append("asked_on and resolution_date must be YYYY-MM-DD")
    source = question.get("resolution_source") if isinstance(question.get("resolution_source"), dict) else {}
    kind = source.get("kind")
    if kind == "official_data":
        for name in ("series", "observation", "comparator", "threshold"):
            if source.get(name) in (None, ""):
                problems.append(f"official_data source needs {name}")
        if source.get("comparator") not in (None, "", ">", ">=", "<", "<="):
            problems.append("comparator must be one of > >= < <=")
    elif kind == "polymarket":
        if not re.fullmatch(r"\d{1,12}", str(source.get("market_id") or "")):
            problems.append("polymarket source needs a numeric market_id")
    else:
        problems.append("resolution_source.kind must be official_data or polymarket "
                        "(the resolution monitor settles nothing else unattended)")
    return problems


def forward_prompt(question: Mapping[str, Any]) -> str:
    source: Mapping[str, Any] = question.get("resolution_source") or {}
    if source.get("kind") == "official_data":
        settle = (f"the official series {source.get('series')} for {source.get('observation')} "
                  f"({source.get('comparator')} {source.get('threshold')})")
    else:
        settle = f"Polymarket market {source.get('market_id')}"
    return (f"Forecast question: {question['question']}\nResolution criteria: {question['resolution_criteria']}\n"
            f"Resolves on or before {question['resolution_date']}; settled by {settle}. Include this question "
            "among the binary forecasts, anchored to that source, with a calibrated probability.")


def forward_score(ledger_dir: Optional[str] = None, bins: int = ge.DEFAULT_BINS) -> Dict[str, Any]:
    """Brier / log score / ECE of the live binaries the resolution monitor resolved."""
    from app.services import forecast_ledger
    rows: List[Dict[str, Any]] = []
    skipped = 0
    sources = (("market", forecast_ledger.read_market_resolutions(ledger_dir)),
               ("official_data", forecast_ledger.read_data_resolutions(ledger_dir)))
    for kind, records in sources:
        for record in records:
            probability = ge._coerce_prob(record.get("model_p"))
            outcome = record.get("resolved_outcome")
            if isinstance(outcome, str):
                outcome = {"yes": True, "no": False}.get(outcome.strip().lower())
            if probability is None or not isinstance(outcome, bool):
                skipped += 1
                continue
            rows.append({"id": f"{record.get('report_id')}:{record.get('forecast_id')}", "probability": probability,
                         "outcome": outcome, "category": kind, "difficulty": None})
    return {"mode": "forward-score", "generated_at": _now(), "ledger_dir": ledger_dir or "(default)",
            "interpretation": "Legacy resolved-only descriptive scores; no enrollment denominator or probability-lift claim.",
            "skipped_unusable": skipped, "metrics": ge.score_pairs(rows, bins=bins)}


def prospective_score(enrollment: str, ledger_dir: Optional[str] = None,
                      bins: int = ge.DEFAULT_BINS) -> Dict[str, Any]:
    """Public CLI consumer: join full enrollment, then reuse the existing scorer."""
    from app.services.backtest import evaluation_report
    report = evaluation_report(path=enrollment, ledger_dir=ledger_dir)
    for arm, data in report["arms"].items():
        resolved = [r for r in report["questions"] if r["arm"] == arm and r["status"] == "resolved"]
        data["metrics"] = ge.score_pairs(resolved, bins=bins)
        data["coverage"] = len(resolved) / data["enrolled"]
    return report


def cmd_forward_enroll(args: argparse.Namespace) -> int:
    from app.services.backtest import enroll_evaluation
    with open(args.design, encoding="utf-8") as stream:
        result = enroll_evaluation(json.load(stream), path=args.enrollment, ledger_dir=args.ledger_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def cmd_forward_record(args: argparse.Namespace) -> int:
    from app.services.backtest import record_evaluation_trial
    with open(args.trial, encoding="utf-8") as stream:
        result = record_evaluation_trial(json.load(stream), path=args.enrollment, ledger_dir=args.ledger_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


# ============================================================ CLI

def _profile(args: argparse.Namespace) -> Profile:
    return Profile(depth=args.depth, max_rounds=args.max_rounds, language=args.language,
                   strict=not args.lenient, archive=args.archive)


def _selection(args: argparse.Namespace) -> Tuple[List[Mapping[str, Any]], List[str]]:
    questions = ge.load_golden_set(args.golden)
    ids = [gid.strip() for gid in (args.ids or "").split(",") if gid.strip()] or None
    return select_questions(questions, ids, args.limit), parse_arms(args.arms)


def cmd_plan(args: argparse.Namespace) -> int:
    questions, arms = _selection(args)
    profile = _profile(args)
    plan = {"profile": profile.__dict__, "arms": {arm: ARMS[arm] for arm in arms},
            "pipelines": len(questions) * len(arms),
            "requests": [build_request(q, arm, profile, label=args.label) for q in questions for arm in arms]}
    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as stream:
            stream.write(payload)
        print(f"wrote {args.out} ({plan['pipelines']} pipelines)")
    else:
        print(payload)
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    questions, arms = _selection(args)
    count = len(questions) * len(arms)
    if not args.confirm_paid:
        print(f"refused: {count} full pipelines spend model, search and fetch credits; "
              "rerun with --confirm-paid once the owner approved the run", file=sys.stderr)
        return 2
    if count > args.max_pipelines:
        print(f"refused: {count} pipelines exceed --max-pipelines {args.max_pipelines}", file=sys.stderr)
        return 2
    records = run_batch(questions, arms, _profile(args), transport=ApiTransport(args.base_url),
                        run_dir=args.run_dir, label=args.label, poll_seconds=args.poll_seconds,
                        timeout_seconds=args.timeout_hours * 3600.0)
    failed = [row for row in records if row.get("status") != "completed"]
    return 1 if failed else 0


def cmd_score(args: argparse.Namespace) -> int:
    records = read_manifest(args.run_dir)
    if not records:
        print(f"no runs recorded in {os.path.join(args.run_dir, MANIFEST)}", file=sys.stderr)
        return 3
    reports_dir = _reports_dir(args.reports_dir)
    report = score_runs(records, ge.load_golden_set(args.golden),
                        forecast_loader=lambda rid: load_forecast(reports_dir, rid),
                        model_cutoff=ge.model_knowledge_cutoff(args.model_knowledge_cutoff),
                        bins=args.bins, lexical=not args.exact_only)
    report.update(golden_path=args.golden, run_dir=args.run_dir, reports_dir=reports_dir)
    with open(args.out, "w", encoding="utf-8") as stream:
        stream.write(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"wrote {args.out}")
    if args.markdown:
        with open(args.markdown, "w", encoding="utf-8") as stream:
            stream.write(render_markdown(report))
        print(f"wrote {args.markdown}")
    return 0 if any(arm["scored"] for arm in report["arms"].values()) else 3


def cmd_forward_check(args: argparse.Namespace) -> int:
    questions = [q for q in load_forward_questions(args.questions) if not q.get("example") or args.include_examples]
    bad = 0
    for question in questions:
        problems = check_forward_question(question)
        if problems:
            bad += 1
            print(f"✗ {question.get('id')}: " + "; ".join(problems))
        else:
            print(f"✓ {question['id']}\n{forward_prompt(question)}\n")
    return 1 if bad else 0


def cmd_forward_score(args: argparse.Namespace) -> int:
    enrollment = getattr(args, "enrollment", None)
    report = (prospective_score(enrollment, args.ledger_dir, bins=args.bins) if enrollment
              else forward_score(args.ledger_dir, bins=args.bins))
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as stream:
            stream.write(payload)
        print(f"wrote {args.out}")
    else:
        print(payload)
    return 0


def _cutoff(value: str) -> str:
    try:
        return ge.model_knowledge_cutoff(value) or ""
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="backtest driver: golden questions × ablation arms")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def selection(p: argparse.ArgumentParser) -> None:
        p.add_argument("--golden", default=ge.GOLDEN_PATH)
        p.add_argument("--ids", default=None, help="comma-separated golden ids (default: all, or --limit)")
        p.add_argument("--limit", type=int, default=None, help="the first N golden questions")
        p.add_argument("--arms", default=None, help=f"comma-separated arms (default: {','.join(ABLATION_ARMS)})")
        p.add_argument("--depth", default=Profile.depth, choices=("quick", "standard", "deep"))
        p.add_argument("--max-rounds", type=int, default=Profile.max_rounds)
        p.add_argument("--language", default=Profile.language)
        p.add_argument("--lenient", action="store_true", help="keep undated sources (flagged) instead of dropping them")
        p.add_argument("--archive", default=Profile.archive, choices=("wayback", "off"))
        p.add_argument("--label", default="", help="run_label stored on every pipeline")

    p = sub.add_parser("plan", help="list the pipelines a run would start (no network)")
    selection(p)
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("run", help="submit the pipelines to a backend and wait (paid)")
    selection(p)
    p.add_argument("--base-url", required=True, help="backend URL, e.g. http://127.0.0.1:5011")
    p.add_argument("--run-dir", required=True, help="where runs.jsonl is kept (resumable)")
    p.add_argument("--confirm-paid", action="store_true", help="required: the run spends provider credits")
    p.add_argument("--max-pipelines", type=int, default=DEFAULT_MAX_PIPELINES)
    p.add_argument("--poll-seconds", type=float, default=30.0)
    p.add_argument("--timeout-hours", type=float, default=6.0)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("score", help="write eval_report.json from a run directory")
    p.add_argument("--run-dir", required=True)
    p.add_argument("--golden", default=ge.GOLDEN_PATH)
    p.add_argument("--reports-dir", default=None, help="default: <UPLOAD_FOLDER>/reports")
    p.add_argument("--model-knowledge-cutoff", default=None, type=_cutoff, metavar="YYYY-MM-DD")
    p.add_argument("--exact-only", action="store_true", help="map by golden_id/proposition_id/id only")
    p.add_argument("--bins", type=int, default=ge.DEFAULT_BINS)
    p.add_argument("-o", "--out", default="eval_report.json")
    p.add_argument("--markdown", default=None)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("forward-check", help="validate a short-horizon forward question file")
    p.add_argument("--questions", default=FORWARD_TEMPLATE)
    p.add_argument("--include-examples", action="store_true", help="also check entries marked example")
    p.set_defaults(func=cmd_forward_check)

    p = sub.add_parser("forward-enroll", help="freeze prospective questions and arms locally; no dispatch")
    p.add_argument("--design", required=True, help="prospective design JSON; see module docstring for schema")
    p.add_argument("--enrollment", required=True, help="immutable enrollment/trial JSONL journal")
    p.add_argument("--ledger-dir", default=None, help="registry checked for already known settlements; default: FORECAST_LEDGER_DIR")
    p.set_defaults(func=cmd_forward_enroll)

    p = sub.add_parser("forward-record", help="bind one publication or final disposition; no provider calls")
    p.add_argument("--trial", required=True, help="trial JSON with costs and publication reference or reason")
    p.add_argument("--enrollment", required=True)
    p.add_argument("--ledger-dir", default=None, help="existing publication/resolution registry")
    p.set_defaults(func=cmd_forward_record)

    p = sub.add_parser("forward-score", help="score prospective enrollment, or legacy resolved-only binaries")
    p.add_argument("--enrollment", default=None, help="retain every enrolled trial, including unresolved and failed")
    p.add_argument("--ledger-dir", default=None, help="default: FORECAST_LEDGER_DIR")
    p.add_argument("--bins", type=int, default=ge.DEFAULT_BINS)
    p.add_argument("-o", "--out", default=None)
    p.set_defaults(func=cmd_forward_score)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OSError) as exc:
        print(f"{args.cmd}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
