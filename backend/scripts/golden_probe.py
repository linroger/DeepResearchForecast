"""EVAL-12 (P03): contamination probes for the golden question set.

Every golden question resolved before current model cutoffs, so a backbone may simply
remember the answer. Two closed-book arms per question measure that before a golden
score is trusted:

- ``nd`` (no-dossier forecast): the forecaster-visible fields only
  (``golden_set.forecaster_view``; a curated ``probe_question`` /
  ``probe_resolution_criteria`` replaces a hindsight-framed wording) and "forecast as of
  {as_of_date} using only information available then", JSON ``{p_yes}``;
- ``recall``: "what happened with <question> between {as_of_date} and {window end}? if
  you do not know, answer UNKNOWN", JSON ``{knows, stated_outcome, details}``. The window
  end is the last day of the month that contains resolution_date + 31 days: it covers
  that window but discloses only roughly when the question resolved, never the day (a
  resolution date can be a leak marker) nor how; that is why a bare correct answer is
  only a weak signal.

A question is ``likely_memorized`` when the recall arm states the correct outcome AND its
details (the whole reply field, whatever its length) contain one of the row's curated
``leak_markers`` (``backend/tests/eval/golden_probe_meta.json``): realized details that
were unknowable at as_of and follow neither from the question nor from the prompt, each
row with a ``marker_rationale``. A row without such a detail (a hold at an unchanged
rate) carries no markers and ``recall_uninformative: true``: it is reported as not
recall-checkable instead of being given a weak marker. ``nd_confident_correct`` (p on
the realized side >= GOLDEN_PROBE_CONFIDENT_P) and ``recall_claimed`` are weak signals
only. The set is ``flagged`` when any question is likely memorized; ``none_detected``
only when both arms reach coverage >= 0.8, at least 0.8 of the probed rows are
recall-checkable, the nd probabilities are not collapsed (``eval_stats.dispersion``), the
recall claims are not left unverified (fewer than 0.8 of the probed rows claim the
correct outcome without a marker, and not every NO row does: such claims cannot be told
from memory, so they never rest on a clean verdict) and the run was closed-book (an
OpenAI-compatible provider: CLI providers are agentic, so they are stamped
``closed_book_attested: false``, run but never certified); otherwise ``inconclusive``
with reasons.

Prompts are built from forecaster_view and the probe meta only; ``assert_answer_free``
blocks any rendered prompt containing a leak marker (arm status
``prompt_leak_blocked``, no call). Parsers never default: a refusal, garbage or an
out-of-range value is ``parse_failed`` ('85%' reads as 0.85), including a reply that
LLMClient.chat_json rejects as non-JSON after its repair turn (a transport error stays
``call_failed``). The backbone model is recorded as the transport requests it
(``model_provenance.effective_model_label``: a CLI provider not given a model it accepts
runs its account default, ``cli-default``). Calls are capped at
GOLDEN_PROBE_MAX_CALLS (each chat attempt counts, the repair turn included); once the
cap is reached the remaining arms are ``skipped_budget``, the status is inconclusive and
the CLI exits 4. Nothing is written to any ledger: artifacts go under
``forecast_ledger.evaluation_ledger_dir()/probes/<provider>__<model>__<golden_sha8>/``
(``arms/<qid>/<arm>.json`` and ``probe_report.json``), and an ``ok`` arm artifact with
the same arm schema, prompt hash, provider and model and a value that still parses is
reused on a rerun (zero calls). The leak guard runs before that reuse, so a prompt that
contains a marker curated after the first run is blocked, never answered from disk.

Opt-in: without GOLDEN_PROBE_ENABLED=true or --live the CLI prints how to opt in and
exits 0 without building a client.

Usage:
    python backend/scripts/golden_probe.py probe [--provider P] [--model M] [--live]
        [--arms nd,recall] [-o DIR] [--golden PATH] [--meta PATH]
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence

_SCRIPTS = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_SCRIPTS)
for _path in (_BACKEND, _SCRIPTS):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.config import Config  # noqa: E402
from app.services import eval_stats, golden_set  # noqa: E402
from app.utils.atomic import write_json_atomic  # noqa: E402

REPORT_SCHEMA = "drf.golden_probe.v1"
# An arm artifact is reused only under this schema: bump it when a parser's semantics change.
ARM_SCHEMA = "drf.golden_probe.arm.v1"
META_PATH = os.path.join(_BACKEND, "tests", "eval", "golden_probe_meta.json")
GOLDEN_PATH = os.path.join(_BACKEND, "tests", "eval", "golden_questions.json")

ARM_ND = "nd"
ARM_RECALL = "recall"
ARMS = (ARM_ND, ARM_RECALL)

STATUS_OK = "ok"
STATUS_PARSE_FAILED = "parse_failed"
STATUS_CALL_FAILED = "call_failed"
STATUS_PROMPT_LEAK = "prompt_leak_blocked"
STATUS_SKIPPED_BUDGET = "skipped_budget"
STATUS_SKIPPED_UNLABELLED = "skipped_unlabelled"

SET_FLAGGED = "flagged"
SET_NONE_DETECTED = "none_detected"
SET_INCONCLUSIVE = "inconclusive"
ND_COLLAPSED = "inconclusive_collapsed"

COVERAGE_MIN = 0.8
RECALL_WINDOW_DAYS = 31
DETAILS_MAX_WORDS = 60
RAW_EXCERPT_MAX = 600
MAX_TOKENS = 1024
EXIT_BUDGET = 4
# LLMClient.chat_json's final miss (the INFRA-2 repair path and the legacy loop raise a
# ValueError with this prefix): the model answered, twice, but not with a JSON object. A
# refusal or garbage is parse_failed, not a transport failure (call_failed).
_JSON_MISS_PREFIX = "LLM返回的JSON格式无效"

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹘﹣－"), "-")
_WS_RE = re.compile(r"\s+")


class PromptLeak(ValueError):
    """A rendered probe prompt contains a curated leak marker (the call is not made)."""


class BudgetExhausted(RuntimeError):
    """GOLDEN_PROBE_MAX_CALLS reached: the next model call is refused."""


# ------------------------------------------------------------------ text
def normalize(text: Any) -> str:
    """NFKC, casefold, unified dashes and collapsed whitespace (marker matching)."""
    folded = unicodedata.normalize("NFKC", str(text or "")).casefold().translate(_DASHES)
    return _WS_RE.sub(" ", folded).strip()


def _marker_re(marker: str) -> "re.Pattern[str]":
    """A marker as a whole token: not glued to a letter or digit on either side, so
    '53' never matches inside '2053' and '4-1' never inside '14-12'."""
    return re.compile(r"(?<![0-9a-z])" + re.escape(normalize(marker)) + r"(?![0-9a-z])")


def contains_marker(text: Any, markers: Sequence[str]) -> Optional[str]:
    """The first marker that occurs (normalized, whole token) in ``text``, else None."""
    haystack = normalize(text)
    for marker in markers:
        if normalize(marker) and _marker_re(marker).search(haystack):
            return marker
    return None


# ------------------------------------------------------------------ meta
def load_meta(path: str = META_PATH) -> Dict[str, Dict[str, Any]]:
    """The probe meta file without its ``_meta`` block."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"probe meta {path} is not an object")
    return {key: value for key, value in data.items() if key != "_meta"}


def probe_view(q: Dict[str, Any], meta_row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """forecaster_view with the curated outcome-free wording, when given."""
    view = golden_set.forecaster_view(q)
    row = meta_row or {}
    if row.get("probe_question"):
        view["question"] = row["probe_question"]
    if row.get("probe_resolution_criteria"):
        view["resolution_criteria"] = row["probe_resolution_criteria"]
    return view


def recall_checkable(meta_row: Optional[Dict[str, Any]]) -> bool:
    """Whether the row has leak markers, i.e. a recall answer can be checked at all."""
    return bool((meta_row or {}).get("leak_markers"))


def validate_meta(meta: Dict[str, Dict[str, Any]], questions: Sequence[Dict[str, Any]]) -> List[str]:
    """Errors: every golden row needs an entry with a ``marker_rationale`` and either a
    non-empty marker list or ``recall_uninformative: true`` with an empty one (never a weak
    marker invented to fill the list); a hindsight-framed row needs a probe_question; no
    marker may occur in the probe view the model is shown (the forecaster view with any
    probe rewording) nor anywhere in an arm's rendered prompt (the template text and the
    recall window included: assert_answer_free would block that arm)."""
    errors: List[str] = []
    by_id = {q.get("id"): q for q in questions}
    for qid in sorted(set(meta) - set(by_id)):
        errors.append(f"{qid}: not a golden id")
    for qid, q in by_id.items():
        row = meta.get(qid)
        if not isinstance(row, dict):
            errors.append(f"{qid}: no probe meta")
            continue
        rationale = row.get("marker_rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            errors.append(f"{qid}: marker_rationale must say why each marker was unknowable at as_of "
                          "(or why the row has none)")
        markers = row.get("leak_markers")
        if not isinstance(markers, list) or not all(isinstance(m, str) and normalize(m) for m in markers):
            errors.append(f"{qid}: leak_markers must be a list of non-blank strings")
            continue
        uninformative = row.get("recall_uninformative", False)
        if not isinstance(uninformative, bool):
            errors.append(f"{qid}: recall_uninformative must be true or false")
        elif uninformative and markers:
            errors.append(f"{qid}: a recall_uninformative row carries no leak_markers")
        elif not uninformative and not markers:
            errors.append(f"{qid}: no leak_markers; mark the row recall_uninformative: true when no "
                          "realized detail was unknowable at as_of")
        if q.get("hindsight_framed") and not row.get("probe_question"):
            errors.append(f"{qid}: hindsight-framed row needs a probe_question")
        view = probe_view(q, row)
        shown = " ".join(str(view.get(k) or "") for k in ("question", "resolution_criteria", "as_of_date"))
        hit = contains_marker(shown, markers)
        if hit is not None:
            errors.append(f"{qid}: leak marker {hit!r} occurs in the forecaster-visible text")
            continue
        for arm in ARMS:
            try:
                assert_answer_free(build_messages(arm, q, row), markers)
            except PromptLeak as exc:
                errors.append(f"{qid}: the {arm} {exc} (template text or the recall window)")
    return errors


# ------------------------------------------------------------------ prompts
def _month_end(day: date) -> date:
    return (day.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)


def _recall_until(q: Dict[str, Any]) -> str:
    """The recall window end (ISO day): the last day of the month that contains
    resolution_date + RECALL_WINDOW_DAYS (as_of_date + 1 year without one). It still covers
    resolution_date + 31 days, but the resolution day, which some leak markers state,
    cannot be computed back from it."""
    for key, extra in (("resolution_date", RECALL_WINDOW_DAYS), ("as_of_date", 365)):
        try:
            end = date.fromisoformat(str(q.get(key))[:10]) + timedelta(days=extra)
        except (TypeError, ValueError):
            continue
        return _month_end(end).isoformat()
    return "the present"


def build_messages(arm: str, q: Dict[str, Any], meta_row: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    """The probe prompt of ``arm`` for ``q``: forecaster_view + probe meta only (never
    resolution_note or resolved_outcome)."""
    view = probe_view(q, meta_row)
    question, criteria, as_of = view["question"], view["resolution_criteria"], view["as_of_date"]
    if arm == ARM_ND:
        user = (f"Question: {question}\nResolution criteria: {criteria}\n\n"
                f"Forecast as of {as_of}, using only information available then. "
                'Reply with JSON only: {"p_yes": <probability between 0 and 1 that the answer is YES>}')
        system = "You are a careful forecaster. Answer with calibrated probabilities."
    elif arm == ARM_RECALL:
        user = (f"What happened with this question between {as_of} and {_recall_until(q)}?\n"
                f"Question: {question}\nResolution criteria: {criteria}\n\n"
                "If you do not know, answer UNKNOWN. Reply with JSON only: "
                '{"knows": true|false, "stated_outcome": "YES"|"NO"|"UNKNOWN", '
                f'"details": "<at most {DETAILS_MAX_WORDS} words>"}}')
        system = "Answer from memory only. Do not guess: say UNKNOWN when you do not know."
    else:
        raise ValueError(f"unknown probe arm {arm!r}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def assert_answer_free(messages: Sequence[Dict[str, str]], markers: Sequence[str]) -> None:
    """Raise PromptLeak when the rendered prompt contains a leak marker."""
    rendered = "\n".join(str(m.get("content") or "") for m in messages)
    hit = contains_marker(rendered, markers)
    if hit is not None:
        raise PromptLeak(f"probe prompt contains leak marker {hit!r}")


def prompt_sha256(messages: Sequence[Dict[str, str]]) -> str:
    return hashlib.sha256(json.dumps(list(messages), ensure_ascii=False, sort_keys=True)
                          .encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ parsers
def parse_probability(value: Any) -> Optional[float]:
    """A probability in [0, 1] (a number, a numeric string or 'NN%'), else None. Never a default."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        scale = 1.0
        if text.endswith("%"):
            text, scale = text[:-1].strip(), 100.0
        try:
            number = float(text) / scale
        except ValueError:
            return None
    elif isinstance(value, (int, float)):
        number = float(value)
    else:
        return None
    return number if math.isfinite(number) and 0.0 <= number <= 1.0 else None


def parse_nd(reply: Any) -> Optional[float]:
    """``reply['p_yes']`` as a probability, else None (parse_failed)."""
    return parse_probability(reply.get("p_yes")) if isinstance(reply, dict) else None


def parse_recall(reply: Any) -> Optional[Dict[str, Any]]:
    """``{knows, stated_outcome, details}`` with stated_outcome YES|NO|UNKNOWN, else None
    (parse_failed). ``details`` keeps the whole reply field (whitespace collapsed): the
    DETAILS_MAX_WORDS limit is only asked for in the prompt, and a marker after it must
    still be found."""
    if not isinstance(reply, dict):
        return None
    stated = str(reply.get("stated_outcome") or "").strip().upper()
    if stated not in ("YES", "NO", "UNKNOWN"):
        return None
    knows = reply.get("knows")
    if isinstance(knows, str):
        knows = {"true": True, "false": False}.get(knows.strip().lower())
    if not isinstance(knows, bool):
        return None
    details = " ".join(str(reply.get("details") or "").split())
    return {"knows": knows, "stated_outcome": stated, "details": details}


# ------------------------------------------------------------------ flags
def question_flags(q: Dict[str, Any], markers: Sequence[str], nd: Optional[float],
                   recall: Optional[Dict[str, Any]], confident_p: float) -> Dict[str, bool]:
    """likely_memorized (recall states the correct outcome AND a marker is in its details),
    and the weak signals nd_confident_correct and recall_claimed."""
    label = golden_set.expected_label(q)
    realized_yes = label == golden_set.LABEL_YES
    correct = recall is not None and label in (golden_set.LABEL_YES, golden_set.LABEL_NO) \
        and recall["stated_outcome"] == label
    hit = correct and contains_marker(recall["details"], markers) is not None
    return {
        "likely_memorized": bool(hit),
        "nd_confident_correct": nd is not None and label in (golden_set.LABEL_YES, golden_set.LABEL_NO)
        and (nd if realized_yes else 1.0 - nd) >= confident_p,
        "recall_claimed": recall is not None and (recall["knows"] or recall["stated_outcome"] != "UNKNOWN"),
    }


# ------------------------------------------------------------------ budget
_METERED = ("chat", "chat_json")


@contextlib.contextmanager
def meter_calls(client: Any, max_calls: int) -> Iterator[Dict[str, Any]]:
    """Count every model attempt and refuse the one that would exceed ``max_calls``.

    chat() is wrapped on the client itself (LLMClient.chat_json calls self.chat, so its
    repair turn is counted; a proxy object would miss it); a chat_json that never reached
    chat() (a test double) counts once. Yields the shared state ``{calls, refused,
    max_calls, last_reply}`` (``last_reply``: the latest text chat() returned). On exit
    the client's own attributes are restored, so a client probed twice is metered afresh."""
    state: Dict[str, Any] = {"calls": 0, "refused": False, "max_calls": max_calls, "last_reply": None}
    own = getattr(client, "__dict__", {})
    saved = {name: own[name] for name in _METERED if name in own}
    inner_chat = getattr(client, "chat", None)
    inner_json = client.chat_json

    def chat(*args: Any, **kwargs: Any) -> Any:
        if state["calls"] >= max_calls:
            state["refused"] = True
            raise BudgetExhausted(f"GOLDEN_PROBE_MAX_CALLS={max_calls} reached")
        state["calls"] += 1
        reply = inner_chat(*args, **kwargs)
        state["last_reply"] = reply
        return reply

    def chat_json(*args: Any, **kwargs: Any) -> Any:
        if state["calls"] >= max_calls:
            state["refused"] = True
            raise BudgetExhausted(f"GOLDEN_PROBE_MAX_CALLS={max_calls} reached")
        before = state["calls"]
        try:
            return inner_json(*args, **kwargs)
        finally:
            if state["calls"] == before:
                state["calls"] += 1

    if callable(inner_chat):
        client.chat = chat
    client.chat_json = chat_json
    try:
        yield state
    finally:
        for name in _METERED:
            if name in saved:
                setattr(client, name, saved[name])
            elif name in own:
                delattr(client, name)


# ------------------------------------------------------------------ run
def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _arm_path(out_dir: str, qid: str, arm: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", qid)
    return os.path.join(out_dir, "arms", safe, f"{arm}.json")


def _parsed_value(arm: str, value: Any) -> bool:
    """Whether ``value`` is exactly what the arm's parser returns for it (a stored ok value)."""
    if arm == ARM_ND:
        return isinstance(value, (int, float)) and parse_probability(value) == value
    return isinstance(value, dict) and parse_recall(value) == value


def _reusable(path: str, arm: str, sha: str, provider: str, model: str) -> Optional[Dict[str, Any]]:
    """The ok artifact at ``path`` when it was written under ARM_SCHEMA for the same arm,
    prompt hash, provider and model and its value still parses; else None (call again)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if (isinstance(doc, dict) and doc.get("schema") == ARM_SCHEMA and doc.get("status") == STATUS_OK
            and doc.get("arm") == arm and doc.get("prompt_sha256") == sha
            and doc.get("provider") == provider and doc.get("model") == model
            and _parsed_value(arm, doc.get("value"))):
        return doc
    return None


def _run_arm(client: Any, state: Dict[str, Any], arm: str, q: Dict[str, Any],
             meta_row: Dict[str, Any], *, provider: str, model: str, out_dir: str,
             counters: Dict[str, int]) -> Dict[str, Any]:
    messages = build_messages(arm, q, meta_row)
    sha = prompt_sha256(messages)
    path = _arm_path(out_dir, q["id"], arm)
    base = {"schema": ARM_SCHEMA, "question_id": q["id"], "arm": arm, "provider": provider,
            "model": model, "prompt_sha256": sha}
    try:
        # Before any reuse: a leaking prompt is answered neither by a new call nor by an
        # artifact a previous run wrote before the marker was curated.
        assert_answer_free(messages, meta_row.get("leak_markers") or [])
    except PromptLeak:
        doc = dict(base, status=STATUS_PROMPT_LEAK, value=None, raw_excerpt="", created_at=_now())
        write_json_atomic(path, doc)
        return doc
    reused = _reusable(path, arm, sha, provider, model)
    if reused is not None:
        counters["reused"] += 1
        return reused
    if state["calls"] >= state["max_calls"]:
        state["refused"] = True
        return dict(base, status=STATUS_SKIPPED_BUDGET, value=None, raw_excerpt="", created_at=_now())
    refused_before = state["refused"]
    state["last_reply"] = None
    try:
        reply = client.chat_json(messages, temperature=0.0, max_tokens=MAX_TOKENS,
                                 label=f"golden_probe:{arm}")
    except BudgetExhausted:
        return dict(base, status=STATUS_SKIPPED_BUDGET, value=None, raw_excerpt="", created_at=_now())
    except Exception as exc:  # noqa: BLE001 — a failed call is recorded, never fatal
        if isinstance(exc, ValueError) and str(exc).startswith(_JSON_MISS_PREFIX):
            # The model replied, but chat_json found no JSON object, its repair turn included.
            replied = state["last_reply"]
            doc = dict(base, status=STATUS_PARSE_FAILED, value=None,
                       raw_excerpt=str(replied if replied is not None else exc)[:RAW_EXCERPT_MAX],
                       created_at=_now())
        else:
            doc = dict(base, status=STATUS_CALL_FAILED, value=None,
                       raw_excerpt=f"{type(exc).__name__}: {exc}"[:RAW_EXCERPT_MAX], created_at=_now())
        write_json_atomic(path, doc)
        return doc
    if state["refused"] and not refused_before:
        # The cap stopped a repair turn inside chat_json: the reply is not a full attempt.
        return dict(base, status=STATUS_SKIPPED_BUDGET, value=None, raw_excerpt="", created_at=_now())
    value = parse_nd(reply) if arm == ARM_ND else parse_recall(reply)
    doc = dict(base, status=STATUS_OK if value is not None else STATUS_PARSE_FAILED, value=value,
               raw_excerpt=json.dumps(reply, ensure_ascii=False)[:RAW_EXCERPT_MAX], created_at=_now())
    write_json_atomic(path, doc)
    return doc


def run_probe(questions: Sequence[Dict[str, Any]], meta: Dict[str, Dict[str, Any]], *,
              client: Any, provider: str, model: str, out_dir: str, golden_sha256: str,
              arms: Sequence[str] = ARMS, max_calls: int = 120, confident_p: float = 0.85,
              closed_book_attested: bool = False) -> Dict[str, Any]:
    """Probe every labelled question on ``arms`` and write probe_report.json; returns it.

    ``client`` is any object with chat_json (an LLMClient in production); it is metered
    by :func:`meter_calls` for the duration of the run. Unlabelled (ambiguous) rows are
    skipped. A repeated arm is run once."""
    arms = list(dict.fromkeys(arms))
    counters = {"reused": 0}
    rows: List[Dict[str, Any]] = []
    with meter_calls(client, max_calls) as state:
        for q in questions:
            meta_row = meta.get(q.get("id")) or {}
            label = golden_set.expected_label(q)
            if label not in (golden_set.LABEL_YES, golden_set.LABEL_NO):
                rows.append({"question_id": q.get("id"), "arms": dict.fromkeys(arms, STATUS_SKIPPED_UNLABELLED),
                             "flags": None})
                continue
            results = {arm: _run_arm(client, state, arm, q, meta_row, provider=provider, model=model,
                                     out_dir=out_dir, counters=counters) for arm in arms}
            nd = (results[ARM_ND]["value"]
                  if ARM_ND in results and results[ARM_ND]["status"] == STATUS_OK else None)
            recall = (results[ARM_RECALL]["value"]
                      if ARM_RECALL in results and results[ARM_RECALL]["status"] == STATUS_OK else None)
            rows.append({"question_id": q["id"], "label": label,
                         "arms": {arm: doc["status"] for arm, doc in results.items()},
                         "nd_p_yes": nd, "recall": recall, "recall_checkable": recall_checkable(meta_row),
                         "flags": question_flags(q, meta_row.get("leak_markers") or [], nd, recall,
                                                 confident_p)})
    report = {
        "schema": REPORT_SCHEMA,
        "golden_sha256": golden_sha256,
        "backbone": {"provider": provider, "model": model},
        "closed_book_attested": bool(closed_book_attested),
        "arms": list(arms),
        "questions": rows,
        "summary": summarize(rows, arms, closed_book_attested=closed_book_attested,
                             budget_exhausted=state["refused"]),
        "cost": {"calls": state["calls"], "reused_arms": counters["reused"], "max_calls": max_calls},
        "created_at": _now(),
    }
    write_json_atomic(os.path.join(out_dir, "probe_report.json"), report)
    return report


def summarize(rows: Sequence[Dict[str, Any]], arms: Sequence[str], *, closed_book_attested: bool,
              budget_exhausted: bool) -> Dict[str, Any]:
    """The set verdict (see the module docstring) with per-arm coverage and the nd collapse check."""
    probed = [r for r in rows if r.get("flags") is not None]
    flagged = sorted(r["question_id"] for r in probed if r["flags"]["likely_memorized"])
    reasons: List[str] = []
    arm_summary: Dict[str, Any] = {}
    for arm in arms:
        ok = [r for r in probed if r["arms"].get(arm) == STATUS_OK]
        coverage = round(len(ok) / len(probed), 4) if probed else 0.0
        arm_summary[arm] = {"coverage": coverage, "ok": len(ok), "probed": len(probed)}
        if coverage < COVERAGE_MIN:
            reasons.append(f"{arm}_coverage_below_{COVERAGE_MIN}")
        if any(r["arms"].get(arm) == STATUS_PROMPT_LEAK for r in probed):
            reasons.append(f"{arm}_prompt_leak_blocked")
    uninformative = sorted(r["question_id"] for r in probed if not r.get("recall_checkable"))
    if ARM_RECALL in arms:
        checkable = len(probed) - len(uninformative)
        share = round(checkable / len(probed), 4) if probed else 0.0
        arm_summary[ARM_RECALL].update(checkable=checkable, checkable_share=share)
        if share < COVERAGE_MIN:
            # Rows without markers can never be flagged: too many of them and a clean recall
            # arm says nothing.
            reasons.append(f"recall_checkable_below_{COVERAGE_MIN}")
    if ARM_ND in arms:
        nd_rows = [r for r in probed if r.get("nd_p_yes") is not None]
        disp = eval_stats.dispersion([r["nd_p_yes"] for r in nd_rows],
                                     [r["label"] == golden_set.LABEL_YES for r in nd_rows])
        arm_summary[ARM_ND]["dispersion"] = disp
        if disp.get("collapsed"):
            arm_summary[ARM_ND]["status"] = ND_COLLAPSED
            reasons.append("nd_collapsed")
    for arm in (ARM_ND, ARM_RECALL):
        if arm not in arms:
            reasons.append(f"{arm}_arm_not_run")
    if not closed_book_attested:
        reasons.append("not_closed_book_attested")
    if budget_exhausted:
        reasons.append("budget_exhausted")
    claimed_correct = sorted(r["question_id"] for r in probed if r["flags"]["recall_claimed"]
                             and r["recall"]["stated_outcome"] == r["label"])
    if ARM_RECALL in arms and probed:
        no_ids = {r["question_id"] for r in probed if r["label"] == golden_set.LABEL_NO}
        if (len(claimed_correct) / len(probed) >= COVERAGE_MIN
                or (no_ids and no_ids <= set(claimed_correct))):
            # A correct outcome without a marker is no proof of memory (most rows are YES),
            # but nearly every outcome, or every NO, claimed correctly is no clean result.
            reasons.append("recall_claims_unverified")
    weak = {"nd_confident_correct": sorted(r["question_id"] for r in probed if r["flags"]["nd_confident_correct"]),
            "recall_claimed": sorted(r["question_id"] for r in probed if r["flags"]["recall_claimed"]),
            "recall_claimed_correct": claimed_correct}
    if flagged:
        status = SET_FLAGGED
    elif not reasons:
        status = SET_NONE_DETECTED
    else:
        status = SET_INCONCLUSIVE
    return {"status": status, "flagged_ids": flagged,
            "inconclusive_reasons": [] if status == SET_NONE_DETECTED else reasons,
            "recall_uninformative_ids": uninformative, "arms": arm_summary, "weak_signals": weak}


# ------------------------------------------------------------------ CLI
def golden_sha256_of(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _model_slug(model: Optional[str]) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "-", str(model or "default")).strip("-") or "default"


def build_client(provider: Optional[str], model: Optional[str]) -> Any:
    """A pinned, cache-free client (EVAL-10): the configured key and endpoint for the
    default provider, forecast_extractor._build_ensemble_client for any other."""
    from app.utils.llm_client import LLMClient
    p = str(provider or "").strip().lower()
    if not p or p == str(Config.LLM_PROVIDER or "").strip().lower():
        return LLMClient(model=model or None, pinned=True, use_cache=False)
    from app.services.forecast_extractor import _build_ensemble_client
    client = _build_ensemble_client(p)
    if model:
        client.model = model
    client._pinned = True
    client.use_cache = False
    return client


def cmd_probe(args: argparse.Namespace, *, client_factory: Callable[[Optional[str], Optional[str]], Any]
              = build_client) -> int:
    if not (getattr(Config, "GOLDEN_PROBE_ENABLED", False) or args.live):
        print("golden_probe: probes make paid model calls; set GOLDEN_PROBE_ENABLED=true or pass "
              "--live to run them. No call was made.")
        return 0
    from app.utils.llm_client import OPENAI_COMPATIBLE_PROVIDERS
    from app.utils.model_provenance import effective_model_label
    from app.services.forecast_ledger import evaluation_ledger_dir
    from app.utils.telemetry import get_run_context, set_run_context
    from golden_eval import load_golden_file

    _version, questions = load_golden_file(args.golden)
    meta = load_meta(args.meta)
    errors = validate_meta(meta, questions)
    if errors:
        print("golden_probe: invalid probe meta:\n  " + "\n  ".join(errors), file=sys.stderr)
        return 2
    arms = [a.strip() for a in str(args.arms or "").split(",") if a.strip()] or list(ARMS)
    unknown = [a for a in arms if a not in ARMS]
    if unknown:
        print(f"golden_probe: unknown arm(s) {unknown}; choose from {list(ARMS)}", file=sys.stderr)
        return 2
    provider = str(args.provider or Config.LLM_PROVIDER or "").strip().lower()
    try:
        client = client_factory(provider, args.model)
    except ValueError as exc:
        # An unknown provider, or one without its API key (_build_ensemble_client / LLMClient).
        print(f"golden_probe: cannot build client for {provider}: {exc}", file=sys.stderr)
        return 2
    # The model the transport requests: a CLI provider runs its account default unless given
    # a model it accepts (claude_cli_model_arg), so client.model would name the wrong backbone.
    model = effective_model_label(provider, args.model or getattr(client, "model", None))
    sha = golden_sha256_of(args.golden)
    out_dir = args.out or os.path.join(evaluation_ledger_dir(), "probes",
                                       f"{provider}__{_model_slug(model)}__{sha[:8]}")
    previous_context = get_run_context()
    set_run_context("golden_probe:" + sha[:8], "golden_probe")
    try:
        report = run_probe(questions, meta, client=client, provider=provider, model=model, out_dir=out_dir,
                           golden_sha256=sha, arms=arms,
                           max_calls=int(getattr(Config, "GOLDEN_PROBE_MAX_CALLS", 120)),
                           confident_p=float(getattr(Config, "GOLDEN_PROBE_CONFIDENT_P", 0.85)),
                           closed_book_attested=provider in OPENAI_COMPATIBLE_PROVIDERS)
    finally:
        set_run_context(None, None)
        if previous_context[0]:
            set_run_context(*previous_context)
    summary = report["summary"]
    print(json.dumps({"status": summary["status"], "flagged_ids": summary["flagged_ids"],
                      "inconclusive_reasons": summary["inconclusive_reasons"], "cost": report["cost"],
                      "report": os.path.join(out_dir, "probe_report.json")}, ensure_ascii=False, indent=2))
    return EXIT_BUDGET if "budget_exhausted" in summary["inconclusive_reasons"] else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="EVAL-12 golden-set contamination probes")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("probe", help="run the closed-book probes against one backbone")
    p.add_argument("--provider", default=None, help="provider id (default: LLM_PROVIDER)")
    p.add_argument("--model", default=None, help="model id (default: the provider's)")
    p.add_argument("--live", action="store_true", help="make the paid calls (else GOLDEN_PROBE_ENABLED)")
    p.add_argument("--arms", default="nd,recall", help="comma list of arms: nd, recall")
    p.add_argument("-o", "--out", default=None, help="artifact directory (default: the evaluation ledger)")
    p.add_argument("--golden", default=GOLDEN_PATH, help="golden question set JSON")
    p.add_argument("--meta", default=META_PATH, help="probe meta JSON")
    p.set_defaults(func=cmd_probe)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
