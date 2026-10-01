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
recall-checkable instead of being given a weak marker. Fail closed: a marker anywhere
else in what the recall arm got back (every attempt, the repair turn's and a reply
chat_json rejected included, every field, whatever the arm status) is the row's
``recall_unverified_marker``: the outcome it rests on is unverified, so the row is not
flagged, but the set is never ``none_detected``. ``nd_confident_correct`` (p on the
realized side >= GOLDEN_PROBE_CONFIDENT_P) and ``recall_claimed`` are weak signals only.
The set is ``flagged`` when any question is likely memorized; ``none_detected`` only when
both arms reach coverage >= 0.8, at least 0.8 of the probed rows are recall-checkable,
the nd probabilities are not collapsed (``eval_stats.dispersion``), no recall reply
carries an unverified marker, the recall claims are not left unverified (fewer than 0.8
of the probed rows claim the correct outcome without a marker, and not every NO row
does: such claims cannot be told from memory, so they never rest on a clean verdict;
``weak_signals.recall_claimed_correct`` lists them, the likely memorized rows being in
``flagged_ids``) and the run was closed-book (an OpenAI-compatible provider: CLI
providers are agentic, so they are stamped ``closed_book_attested: false``, run but never
certified); otherwise ``inconclusive`` with reasons.

Prompts are built from forecaster_view and the probe meta only; ``assert_answer_free``
blocks any rendered prompt containing a leak marker (arm status
``prompt_leak_blocked``, no call), and ``validate_meta`` also runs EVAL-9's structural
leak lint (``golden_set.leak_findings``) over every curated rewording. Parsers never
default: a refusal, garbage or an out-of-range value is ``parse_failed`` ('85%' reads as
0.85; a stated_outcome 'YES.' as YES; a ``knows`` that is missing or unreadable is kept as
None, since it only feeds recall_claimed), including a reply that LLMClient.chat_json
rejects as non-JSON after its repair turn (a transport error stays ``call_failed``).
Every arm artifact keeps the model's whole reply text (``reply_text``, uncut; the
``raw_excerpt`` is cut at RAW_EXCERPT_MAX). The backbone model is recorded as the
transport requests it (``model_provenance.effective_model_label``: a CLI provider not
given a model it accepts runs its account default, ``cli-default``). Calls are capped at
GOLDEN_PROBE_MAX_CALLS (each chat attempt counts, the repair turn included); once the
cap is reached the remaining arms are ``skipped_budget``, the status is inconclusive and
the CLI exits 4. Nothing is written to any ledger: artifacts go under
``forecast_ledger.evaluation_ledger_dir()/probes/<provider>__<model>__<golden_sha8>/``
(``arms/<qid>/<arm>.json`` and ``probe_report.json``), and an ``ok`` arm artifact with
the same arm schema, prompt hash, provider and model, a value that still parses and its
reply text is reused on a rerun (zero calls). The leak guard runs before that reuse, so a
prompt that contains a marker curated after the first run is blocked, never answered
from disk, and the flags and the unverified-marker check are recomputed from the stored
value and reply text against the current meta.

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
# v2: parse_recall keeps an unreadable ``knows`` as None and reads 'YES.'; reply_text added.
ARM_SCHEMA = "drf.golden_probe.arm.v2"
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
# A JSON string escape in a raw reply text: \uXXXX or a backslash and one character.
_JSON_ESCAPE_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.S)
_JSON_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}
_KNOWS = {"true": True, "yes": True, "false": False, "no": False}


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


def _unescape_json(text: str) -> str:
    """JSON string escapes in a raw reply decoded ('won\\n411' -> 'won', newline, '411';
    '2\\u20130' -> '2–0'), so a marker next to one still reads as a whole token."""
    def decode(match: "re.Match[str]") -> str:
        escape = match.group(1)
        if len(escape) == 5:
            return chr(int(escape[1:], 16))
        return _JSON_ESCAPES.get(escape, escape)
    return _JSON_ESCAPE_RE.sub(decode, text)


def _reply_text(reply: Any) -> str:
    """Every key and value of a reply object as plain text (no JSON escaping)."""
    if isinstance(reply, dict):
        return " ".join(f"{_reply_text(key)} {_reply_text(value)}" for key, value in reply.items())
    if isinstance(reply, (list, tuple)):
        return " ".join(_reply_text(value) for value in reply)
    return "" if reply is None else str(reply)


def reply_marker(text: Any, markers: Sequence[str]) -> Optional[str]:
    """The first marker in a stored reply text, read as it is and with JSON escapes decoded."""
    raw = str(text or "")
    return contains_marker(raw, markers) or contains_marker(_unescape_json(raw), markers)


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
    marker invented to fill the list); a hindsight-framed row needs a probe_question; a
    probe_question or probe_resolution_criteria, when given, is a non-blank string that
    passes ``golden_set.leak_findings`` in place of the golden text; no marker may occur in
    the probe view the model is shown (the forecaster view with any probe rewording) nor
    anywhere in an arm's rendered prompt (the template text and the recall window included:
    assert_answer_free would block that arm)."""
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
        reworded = [key for key in ("probe_question", "probe_resolution_criteria") if key in row]
        blank = [key for key in reworded if not isinstance(row[key], str) or not row[key].strip()]
        if blank:
            errors += [f"{qid}: {key} must be a non-blank string" for key in blank]
            continue
        view = probe_view(q, row)
        if reworded:
            # A rewording replaces the golden text in both prompts: it passes the same EVAL-9
            # structural lint (one '?' question, one 'YES if' sentence, reviewed parentheticals,
            # no resolution_note sentence) as the golden row it stands in for.
            errors += [f"{qid}: probe rewording fails the golden leak lint: {f['code']} in {f['field']}: "
                       f"{f['text']!r}" for f in golden_set.leak_findings(dict(q, **view))]
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
    """``{knows, stated_outcome, details}`` with stated_outcome YES|NO|UNKNOWN (any case,
    a trailing '.' or '!' ignored), else None (parse_failed). ``knows`` is a boolean or
    'true'/'false'/'yes'/'no', and None when missing or unreadable: it only feeds the weak
    recall_claimed, so it never rejects a reply that states an outcome. ``details`` keeps
    the whole reply field (whitespace collapsed): the DETAILS_MAX_WORDS limit is only asked
    for in the prompt, and a marker after it must still be found."""
    if not isinstance(reply, dict):
        return None
    stated = str(reply.get("stated_outcome") or "").strip().rstrip(".!").strip().upper()
    if stated not in ("YES", "NO", "UNKNOWN"):
        return None
    knows = reply.get("knows")
    if isinstance(knows, str):
        knows = _KNOWS.get(knows.strip().lower())
    if not isinstance(knows, bool):
        knows = None
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
        "recall_claimed": recall is not None and (recall["knows"] is True or recall["stated_outcome"] != "UNKNOWN"),
    }


def unverified_marker(recall_doc: Optional[Dict[str, Any]], markers: Sequence[str],
                      likely_memorized: bool) -> Optional[str]:
    """Fail closed: a marker in the recall arm's whole reply text (``reply_text``: every
    attempt and field, whatever the arm status) that likely_memorized did not already count:
    an off-schema reply, a reply chat_json rejected, a marker outside ``details`` or beside a
    wrong or UNKNOWN outcome. Such a row is not flagged (its outcome is unverified), but it
    keeps the set from ``none_detected``."""
    if recall_doc is None or likely_memorized:
        return None
    return reply_marker(recall_doc.get("reply_text"), markers)


# ------------------------------------------------------------------ budget
_METERED = ("chat", "chat_json")


@contextlib.contextmanager
def meter_calls(client: Any, max_calls: int) -> Iterator[Dict[str, Any]]:
    """Count every model attempt and refuse the one that would exceed ``max_calls``.

    chat() is wrapped on the client itself (LLMClient.chat_json calls self.chat, so its
    repair turn is counted; a proxy object would miss it); a chat_json that never reached
    chat() (a test double) counts once. Yields the shared state ``{calls, refused,
    max_calls, replies}`` (``replies``: every text chat() returned, in order; _run_arm
    empties it before each arm). On exit the client's own attributes are restored, so a
    client probed twice is metered afresh."""
    state: Dict[str, Any] = {"calls": 0, "refused": False, "max_calls": max_calls, "replies": []}
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
        state["replies"].append(reply)
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
    prompt hash, provider and model, its value still parses and it keeps its reply text
    (the marker check reads it); else None (call again)."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    if (isinstance(doc, dict) and doc.get("schema") == ARM_SCHEMA and doc.get("status") == STATUS_OK
            and doc.get("arm") == arm and doc.get("prompt_sha256") == sha
            and doc.get("provider") == provider and doc.get("model") == model
            and _parsed_value(arm, doc.get("value")) and isinstance(doc.get("reply_text"), str)):
        return doc
    return None


def _run_arm(client: Any, state: Dict[str, Any], arm: str, q: Dict[str, Any],
             meta_row: Dict[str, Any], *, provider: str, model: str, out_dir: str,
             counters: Dict[str, int]) -> Dict[str, Any]:
    messages = build_messages(arm, q, meta_row)
    sha = prompt_sha256(messages)
    path = _arm_path(out_dir, q["id"], arm)
    base = {"schema": ARM_SCHEMA, "question_id": q["id"], "arm": arm, "provider": provider,
            "model": model, "prompt_sha256": sha, "reply_text": ""}
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
    state["replies"] = []

    def answered(status: str, value: Any, excerpt: str, *more: str) -> Dict[str, Any]:
        # reply_text: everything the model returned on this arm, uncut, whatever the status
        # (every chat() attempt, the repair turn's included, plus ``more``), for the marker check.
        texts = [str(text) for text in state["replies"]] + list(more)
        return dict(base, status=status, value=value, raw_excerpt=excerpt[:RAW_EXCERPT_MAX],
                    reply_text="\n".join(texts), created_at=_now())
    try:
        reply = client.chat_json(messages, temperature=0.0, max_tokens=MAX_TOKENS,
                                 label=f"golden_probe:{arm}")
    except BudgetExhausted:
        return answered(STATUS_SKIPPED_BUDGET, None, "")
    except Exception as exc:  # noqa: BLE001 — a failed call is recorded, never fatal
        replies = state["replies"]
        if isinstance(exc, ValueError) and str(exc).startswith(_JSON_MISS_PREFIX):
            # The model replied, but chat_json found no JSON object, its repair turn included
            # (a client that never reached chat() leaves the reply in the error text only).
            doc = answered(STATUS_PARSE_FAILED, None, str(replies[-1] if replies else exc),
                           *([] if replies else [str(exc)]))
        else:
            # A transport error text is no reply; an earlier attempt's reply still counts.
            doc = answered(STATUS_CALL_FAILED, None, f"{type(exc).__name__}: {exc}")
        write_json_atomic(path, doc)
        return doc
    if state["refused"] and not refused_before:
        # The cap stopped a repair turn inside chat_json: the reply is not a full attempt.
        return answered(STATUS_SKIPPED_BUDGET, None, "", _reply_text(reply))
    value = parse_nd(reply) if arm == ARM_ND else parse_recall(reply)
    doc = answered(STATUS_OK if value is not None else STATUS_PARSE_FAILED, value,
                   json.dumps(reply, ensure_ascii=False), _reply_text(reply))
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
            markers = meta_row.get("leak_markers") or []
            flags = question_flags(q, markers, nd, recall, confident_p)
            rows.append({"question_id": q["id"], "label": label,
                         "arms": {arm: doc["status"] for arm, doc in results.items()},
                         "nd_p_yes": nd, "recall": recall, "recall_checkable": recall_checkable(meta_row),
                         "recall_unverified_marker": unverified_marker(results.get(ARM_RECALL), markers,
                                                                       flags["likely_memorized"]),
                         "flags": flags})
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
    unverified = sorted(r["question_id"] for r in probed if r.get("recall_unverified_marker"))
    if unverified:
        # Fail closed: the backbone named a detail unknowable at as_of, but not as a parsed
        # correct outcome with the marker in its details, so the row is not flagged.
        reasons.append("recall_unverified_marker")
    # Correct claims without a marker (a likely memorized row is in flagged_ids instead).
    claimed_correct = sorted(r["question_id"] for r in probed if r["flags"]["recall_claimed"]
                             and not r["flags"]["likely_memorized"]
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
            "recall_claimed_correct": claimed_correct, "recall_unverified_marker": unverified}
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
