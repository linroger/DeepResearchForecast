"""Golden-set v2 data contract (EVAL-9, candidate P17).

The v1 golden file stored an asserted outcome and let the forecaster-visible
``resolution_criteria`` carry it too: 25 of 30 criteria embedded the realized
result ("(they won 53)", "It held rates steady."), so any replay brief that
copied the criteria leaked the answer, and no label could be recomputed from a
source. Schema v2 separates what a forecaster may see from what only the grader
may read, lints the visible text structurally, and lets an evidence-backed row
recompute its own label so a mistyped outcome fails loudly.

- ``forecaster_view(q)`` is the only sanctioned prompt input for replays,
  probes and briefs: exactly ``id``, ``question``, ``resolution_criteria`` and
  ``as_of_date``. Everything else is grader-only.
- ``leak_findings(q)`` is structural, never a marker-word list (a word list
  flags legitimate criteria such as a Fed "cut" or "convicted"): the criteria
  must be one sentence starting ``YES if`` (a line break always ends a
  sentence); every parenthetical in the question or criteria must be listed
  verbatim in ``reviewed_parentheticals``; no ``resolution_note`` sentence and no
  ``resolution_evidence.raw_value`` string or number may appear in the visible
  text. Each rule fails closed: an ambiguous shape is flagged for review.
- ``validate_question(q, strict)`` checks the contract; ``strict`` also requires
  ``verification == 'verified'`` and non-empty ``resolution_evidence``.
- ``recompute_label(q)`` recomputes YES / NO / AMBIGUOUS / UNVERIFIABLE from the
  evidence. A dead band comes only from a pre-registered ``resolution_tolerance``
  (default none) and only for numeric_threshold evidence: counts, winners and
  settlements use epsilon 0. A tolerance inside the evidence rule is rejected,
  because a band chosen after seeing ``raw_value`` can move any near-threshold
  label.
- ``balance_audit(qs)`` is report-only: YES rate, category shares, event
  clusters, lead buckets and advisory violations. It never gates anything.

Pure and stdlib-only apart from the equally pure ``eval_stats`` date helpers:
no Config, disk, LLM or network access. It deliberately lives outside
``app.evaluation`` (that namespace is reserved for WP14's sealed case registry).
"""

from __future__ import annotations

import math
import numbers
import operator
import re
import unicodedata
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services import eval_stats

SCHEMA_VERSION = 2
LEGACY_SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (LEGACY_SCHEMA_VERSION, SCHEMA_VERSION)

VISIBLE_FIELDS = ("id", "question", "resolution_criteria", "as_of_date")
GRADER_ONLY_FIELDS = (
    "resolved_outcome", "resolution_note", "resolution_date", "resolve_time",
    "resolve_time_precision", "resolution_evidence", "resolution_tolerance",
    "scoring_status", "verification", "event_cluster", "primary_entity", "shift_axis",
    "hindsight_framed", "reviewed_parentheticals", "category", "difficulty",
)
# resolved_outcome is required too, as a boolean unless scoring_status is 'ambiguous'.
REQUIRED_TEXT_FIELDS = VISIBLE_FIELDS + (
    "resolution_date", "resolve_time", "resolve_time_precision", "verification",
    "event_cluster", "category", "difficulty",
)

SCORING_SCORED = "scored"
SCORING_AMBIGUOUS = "ambiguous"
SCORING_STATUSES = (SCORING_SCORED, SCORING_AMBIGUOUS)
VERIFIED = "verified"
VERIFICATION_STATES = (VERIFIED, "unverified", "legacy_unverified")
RESOLVE_TIME_PRECISIONS = ("day", "minute")
SHIFT_AXES = ("none", "time", "domain")

KIND_NUMERIC = "numeric_threshold"
KIND_COUNT = "count_threshold"
KIND_CATEGORICAL = "categorical"
KIND_MARKET = "market_settlement"
KIND_OCCURRENCE = "event_occurrence"
EVIDENCE_KINDS = (KIND_NUMERIC, KIND_COUNT, KIND_CATEGORICAL, KIND_MARKET, KIND_OCCURRENCE)
THRESHOLD_KINDS = (KIND_NUMERIC, KIND_COUNT)
RULE_REQUIRED_KINDS = (KIND_NUMERIC, KIND_COUNT, KIND_CATEGORICAL)
# P17 source verifier: a fixed per-kind policy with epsilon 0 for counts, winners and
# settlements. On an integer count a band can only turn an exact result AMBIGUOUS.
TOLERANCE_KINDS = (KIND_NUMERIC,)
TOLERANCE_KEYS = ("epsilon_abs", "epsilon_rel")

_NUMERIC_OPS: Dict[str, Callable[[float, float], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt,
    "<=": operator.le, "==": operator.eq, "!=": operator.ne,
}
CATEGORICAL_COMPARATORS = ("==", "!=", "in", "not_in")
# "value" reads a scalar; the others reduce a [{t, v}] series inside the rule window
# ("count" counts its entries, so a list of dated events needs no "v").
AGGREGATIONS = ("value", "max", "min", "first", "last", "sum", "mean", "count")

LABEL_YES = "YES"
LABEL_NO = "NO"
LABEL_AMBIGUOUS = "AMBIGUOUS"
LABEL_UNVERIFIABLE = "UNVERIFIABLE"
LABELS = (LABEL_YES, LABEL_NO, LABEL_AMBIGUOUS, LABEL_UNVERIFIABLE)

# Mirrors app.utils.prediction_markets._RESOLVED_PRICE_HI / _RESOLVED_PRICE_LO: a
# settled market's Yes price converges to ~1 or ~0. A 50-50 (void) settlement pays
# 0.5; any other price is not a settlement, so it recomputes as UNVERIFIABLE.
MARKET_SETTLED_YES = 0.99
MARKET_SETTLED_NO = 0.01
MARKET_VOID_PRICE = 0.5
MARKET_VOID_BAND = 0.01
MARKET_DEFAULT_FIELD = "resolved_yes_price"
OCCURRENCE_DEFAULT_FIELD = "occurred"

LEAK_CRITERIA_FORM = "criteria_not_yes_if"
LEAK_EXTRA_SENTENCE = "extra_sentence"
LEAK_UNREVIEWED_PARENTHETICAL = "unreviewed_parenthetical"
LEAK_UNBALANCED_PARENTHESIS = "unbalanced_parenthesis"
LEAK_OUTCOME_IN_VISIBLE_TEXT = "outcome_in_visible_text"
CRITERIA_PREFIX = "YES if "

# balance_audit advisory thresholds (report-only; nothing gates on them).
DEFAULT_MAX_CATEGORY_SHARE = 0.25
DEFAULT_YES_RATE_BAND = (0.35, 0.65)
DEFAULT_MAX_CLUSTER_SIZE = 2

_END_OF_DAY = time(23, 59, 59, tzinfo=timezone.utc)
# The last representable instant of a day: an inclusive date-only window end.
_LAST_INSTANT = time.max.replace(tzinfo=timezone.utc)


class RecomputeMismatchError(ValueError):
    """An evidence-backed golden row whose recomputed label disagrees with its recorded one."""


# ================================================================ schema basics

def schema_version(payload: Any) -> int:
    """Declared schema version of a loaded golden file: ``_meta.schema_version``, else 1.

    A bare list or a file without the key is v1. A declared version that is not a
    supported integer raises ValueError: a file claiming an unknown contract must
    never be scored under a guessed one.
    """
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict) or "schema_version" not in meta:
        return LEGACY_SCHEMA_VERSION
    version = meta["schema_version"]
    if isinstance(version, bool) or version not in SUPPORTED_SCHEMA_VERSIONS:
        raise ValueError(f"unsupported golden _meta.schema_version {version!r} "
                         f"(supported: {', '.join(map(str, SUPPORTED_SCHEMA_VERSIONS))})")
    return int(version)


def forecaster_view(q: Dict[str, Any]) -> Dict[str, Any]:
    """Exactly ``{id, question, resolution_criteria, as_of_date}``: the only prompt-safe fields."""
    return {key: q.get(key) for key in VISIBLE_FIELDS}


def is_ambiguous(q: Any) -> bool:
    """True when the row's ``scoring_status`` is 'ambiguous' (never scored)."""
    return isinstance(q, dict) and str(q.get("scoring_status") or "").strip() == SCORING_AMBIGUOUS


def expected_label(q: Dict[str, Any]) -> Optional[str]:
    """The recorded label: AMBIGUOUS for an ambiguous row, else YES/NO from a boolean outcome."""
    if is_ambiguous(q):
        return LABEL_AMBIGUOUS
    outcome = q.get("resolved_outcome")
    if isinstance(outcome, bool):
        return LABEL_YES if outcome else LABEL_NO
    return None


# ============================================================ time and numbers

def parse_utc_instant(value: Any) -> Optional[datetime]:
    """An ISO-8601 timestamp with an explicit UTC offset ('Z' or '+00:00'); None otherwise."""
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def end_of_day(day: date) -> datetime:
    """``day`` at 23:59:59 UTC: how a date-only as_of or resolution is placed in time."""
    return datetime.combine(day, _END_OF_DAY)


def _instant(value: Any, *, day_end: bool) -> Optional[datetime]:
    """A canonical date or any aware timestamp as a UTC instant; None otherwise.

    A date is its first instant, or with ``day_end`` its last representable one
    (23:59:59.999999), so an inclusive date-only bound also covers sub-second times.
    """
    day = eval_stats.parse_iso_date(value)
    if day is not None:
        return datetime.combine(day, _LAST_INSTANT if day_end else time(0, 0, tzinfo=timezone.utc))
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
        return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None
    except (OverflowError, ValueError):   # unparseable, or shifted out of datetime's range
        return None


def _finite(value: Any) -> Optional[float]:
    """A finite real number (never a bool) as float; None otherwise (also when too large for a float)."""
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    try:
        number = float(value)
    except (OverflowError, ValueError):
        return None
    return number if math.isfinite(number) else None


# ================================================================== leak lint

# Sentence breaks. Western terminal punctuation ends a sentence when whitespace and
# more text follow, or when a capitalized word follows with no space at all
# ("seats.They won 53"); decimals ("3.5"), domains ("example.com"), tickers
# ("BRK.B") and initials ("U.S.") are never breaks of that second form. The
# lookbehind anchors each match to the first mark of a run, so the scan stays linear
# on long punctuation runs. A CJK terminator ends a sentence with or without
# following whitespace, and a line break always ends one (split_sentences splits
# lines first).
_CJK_TERMINATORS = "。！？"
_CLOSERS = r"[\"'”’)\]）」』]"
_SENTENCE_BREAK = re.compile(
    r"(?<![.!?。！？])(?:[.!?]+" + _CLOSERS + r"*(?:(?P<gap>\s+)(?=\S)|(?=[^\W\d_]))"
    r"|[。！？]+" + _CLOSERS + r"*\s*(?=\S))")
_OPENERS = "(\"'[“‘（「『"
_INITIALS = re.compile(r"(?:[^\W\d_]\.)*[^\W\d_]")
# Longest token worth testing as an abbreviation or initial; a longer one is a word,
# so the break stands (this also bounds the backward scan per candidate break).
_MAX_ABBREVIATION_TOKEN = 24
# Titles precede a name, so a capitalized word after them never opens a sentence.
_TITLE_ABBREVIATIONS = frozenset({
    "mr", "mrs", "ms", "dr", "prof", "st", "gov", "sen", "rep", "gen", "vs",
})
# These also end sentences ("... by Dec. It passed.", "... Acme Inc. It closed."), so
# they hide a break only before a numeral or a lowercase word ("Dec. 31", "Inc. shares").
_TRAILING_ABBREVIATIONS = frozenset({
    "jr", "sr", "inc", "corp", "ltd", "co", "approx", "est", "dept",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec",
})
# "No." abbreviates "number" only before a numeral ("No. 5"); anywhere else "no." is
# the word ending its sentence, and hiding that break would let outcome prose through.
_NUMBER_ABBREVIATION = "no"
# A number (digits with internal '.' / ',' separators) and a letter run are separate
# words, so a number glued to a unit, currency or suffix ("50bps", "$3.47T", "53rd")
# still matches the raw value it spells, while a decimal stays one word: a raw 3 is
# never found inside "3.47", nor a raw 5 inside a "3.5" threshold.
_WORD = re.compile(r"\d+(?:[.,]\d+)*|[^\W\d_]+")


def _token_before(text: str, lo: int, hi: int) -> Optional[Tuple[str, int]]:
    """The whitespace-free token ending at ``text[hi]`` (not before ``lo``) and its start.

    None when it is longer than ``_MAX_ABBREVIATION_TOKEN``: no abbreviation is.
    """
    i = hi
    while i > lo and not text[i - 1].isspace():
        if hi - i >= _MAX_ABBREVIATION_TOKEN:
            return None
        i -= 1
    return text[i:hi], i


def _is_abbreviation(text: str, lo: int, hi: int, following: str) -> bool:
    """True when the '.' at ``text[hi]`` closes an abbreviation or initial, not a sentence.

    ``following`` is the first character after the break. Fails closed: an
    abbreviation that can also end a sentence hides the break only when the next
    word cannot open one, and a lone capital is an initial only after a capitalized
    word ("Donald J. Trump", never "group A. They won.").
    """
    found = _token_before(text, lo, hi)
    if found is None:
        return False
    token, token_start = found
    word = token.lstrip(_OPENERS)
    key = word.casefold()
    if key == _NUMBER_ABBREVIATION:
        return following.isdigit()
    if key in _TITLE_ABBREVIATIONS:
        return True
    if key in _TRAILING_ABBREVIATIONS:
        return following.isdigit() or following.islower()
    if not _INITIALS.fullmatch(word):
        return False
    if len(word) > 1:                                  # "U.S", "J.K", "e.g"
        return True
    j = token_start
    while j > lo and text[j - 1].isspace() and token_start - j < _MAX_ABBREVIATION_TOKEN:
        j -= 1
    previous = _token_before(text, lo, j) if j < token_start else None
    return previous is not None and previous[0].lstrip(_OPENERS)[:1].isupper()


def _is_sentence_break(text: str, lo: int, match: "re.Match[str]") -> bool:
    mark = text[match.start()]
    if mark in _CJK_TERMINATORS:
        return True
    following = text[match.end():match.end() + 2]
    if match.group("gap") is None:
        # no whitespace: only a capitalized word ("They") or an uncased letter (CJK)
        # opens a sentence; "U.S.", "ASP.NET" and "BRK.B" do not
        first, second = following[:1], following[1:2]
        if not ((first.isupper() and second.islower())
                or (first.isalpha() and not first.isupper() and not first.islower())):
            return False
    if mark != ".":
        return True                                    # '!' and '?' end a sentence
    return not _is_abbreviation(text, lo, match.start(), following[:1])


def _split_line(line: str) -> List[str]:
    line = line.strip()
    sentences: List[str] = []
    start = 0
    for match in _SENTENCE_BREAK.finditer(line):
        if _is_sentence_break(line, start, match):
            sentences.append(line[start:match.end()].strip())
            start = match.end()
    tail = line[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_sentences(text: str) -> List[str]:
    """Split prose into sentences (stripped, terminal punctuation kept).

    A line break always ends a sentence. Linear in the length of ``text``.
    """
    sentences: List[str] = []
    for line in (text or "").splitlines():
        sentences += _split_line(line)
    return sentences


_OPEN_PARENS = "(（"
_CLOSE_PARENS = ")）"


def parentheticals(text: str) -> Tuple[List[str], bool]:
    """Top-level ``(...)`` / ``（...）`` spans of ``text`` verbatim, and whether they balance."""
    spans: List[str] = []
    depth, start, balanced = 0, 0, True
    for i, ch in enumerate(text or ""):
        if ch in _OPEN_PARENS:
            if depth == 0:
                start = i
            depth += 1
        elif ch in _CLOSE_PARENS:
            if depth == 0:
                balanced = False
                continue
            depth -= 1
            if depth == 0:
                spans.append(text[start:i + 1])
    return spans, balanced and depth == 0


def _normalize(text: Any) -> str:
    """NFKC-casefolded numbers and letter runs joined by single spaces, for phrase matching.

    Other punctuation is dropped: "$3.47T" -> "3.47 t", "50bps" -> "50 bps",
    full-width "５３" -> "53".
    """
    return " ".join(_WORD.findall(unicodedata.normalize("NFKC", str(text)).casefold()))


def _contains_phrase(haystack: str, needle: str) -> bool:
    """Whole-word phrase containment over ``_normalize``d strings."""
    return bool(needle) and f" {needle} " in f" {haystack} "


def _value_phrases(value: Any) -> List[str]:
    """Normalized spellings of a raw string or number.

    A number is matched as written plainly, with thousands separators and as a float
    literal: 100000 -> "100000", "100,000", "100000.0"; 1e-05 -> "0.00001", "1e-05".
    """
    if isinstance(value, str):
        phrase = _normalize(value)
        return [phrase] if len(phrase) > 1 else []
    number = _finite(value)
    if number is None:
        return []
    spellings = {repr(number)}
    if number.is_integer():
        whole = int(value) if isinstance(value, numbers.Integral) else int(number)
        spellings |= {str(whole), f"{whole:,}"}
    else:
        fixed = format(Decimal(repr(number)), "f")        # exact, never rounded: 1e-07 -> "0.0000001"
        head, _, tail = fixed.partition(".")
        spellings |= {fixed, f"{int(head):,}.{tail}"}
    return sorted({p for p in map(_normalize, spellings) if p})


def _raw_leaves(value: Any) -> Iterable[Any]:
    """Every string and number (never a bool) nested in a raw_value."""
    if isinstance(value, dict):
        for item in value.values():
            yield from _raw_leaves(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _raw_leaves(item)
    elif isinstance(value, str) or _finite(value) is not None:
        yield value


def _raw_value_phrases(evidence: Any) -> List[Tuple[str, str]]:
    """``(phrase, original)`` for each raw_value leaf that would reveal the outcome if visible.

    The rule's own threshold is exempt (the criteria state it by construction). Of a
    market settlement only the Yes price itself is exempt (a 0 / 0.5 / 1 price, not
    prose); any other raw_value key, such as a winner, is checked.
    """
    if not isinstance(evidence, dict):
        return []
    rule = evidence.get("rule") if isinstance(evidence.get("rule"), dict) else {}
    threshold = rule.get("threshold")
    exempt = {p for t in (threshold if isinstance(threshold, list) else [threshold])
              for p in _value_phrases(t)}
    raw = evidence.get("raw_value")
    if evidence.get("kind") == KIND_MARKET:
        price_field = rule.get("field") or MARKET_DEFAULT_FIELD
        if isinstance(raw, dict):
            raw = {key: value for key, value in raw.items() if key != price_field}
        elif _finite(raw) is not None:
            raw = None                                   # a bare settlement price
    out: List[Tuple[str, str]] = []
    for leaf in _raw_leaves(raw):
        out += [(p, str(leaf)) for p in _value_phrases(leaf) if p not in exempt]
    return out


def _finding(code: str, field: str, text: str) -> Dict[str, str]:
    return {"code": code, "field": field, "text": text}


def leak_findings(q: Dict[str, Any]) -> List[Dict[str, str]]:
    """Structural leak findings over the forecaster-visible text: ``[{code, field, text}]``.

    - ``criteria_not_yes_if`` / ``extra_sentence``: the criteria must be a single
      sentence starting ``YES if`` (outcome prose usually rides in a second sentence;
      a line break always starts one);
    - ``unreviewed_parenthetical`` / ``unbalanced_parenthesis``: every parenthetical in
      the question or criteria must be listed verbatim in ``reviewed_parentheticals``;
    - ``outcome_in_visible_text``: a ``resolution_note`` sentence, or a raw_value string
      or number of the ``resolution_evidence``, appears in the question or criteria
      (whole words, punctuation-insensitive; a number glued to a unit still counts).
    """
    visible = {field: q[field] for field in ("question", "resolution_criteria")
               if isinstance(q.get(field), str)}
    findings: List[Dict[str, str]] = []
    criteria = visible.get("resolution_criteria")
    if criteria is not None:
        if not criteria.strip().startswith(CRITERIA_PREFIX):
            findings.append(_finding(LEAK_CRITERIA_FORM, "resolution_criteria", criteria.strip()[:80]))
        for extra in split_sentences(criteria)[1:]:
            findings.append(_finding(LEAK_EXTRA_SENTENCE, "resolution_criteria", extra))

    reviewed = q.get("reviewed_parentheticals")
    reviewed_set = {r for r in reviewed if isinstance(r, str)} if isinstance(reviewed, list) else set()
    for field, text in visible.items():
        spans, balanced = parentheticals(text)
        if not balanced:
            findings.append(_finding(LEAK_UNBALANCED_PARENTHESIS, field, text))
        findings += [_finding(LEAK_UNREVIEWED_PARENTHETICAL, field, span)
                     for span in spans if span not in reviewed_set]

    normalized = {field: _normalize(text) for field, text in visible.items()}
    note = q.get("resolution_note")
    note_phrases = ([(_normalize(s), s) for s in split_sentences(note)]
                    if isinstance(note, str) else [])
    for phrase, original in note_phrases + _raw_value_phrases(q.get("resolution_evidence")):
        for field, text in normalized.items():
            if _contains_phrase(text, phrase):
                findings.append(_finding(LEAK_OUTCOME_IN_VISIBLE_TEXT, field, original))
    seen = set()
    unique: List[Dict[str, str]] = []
    for finding in findings:
        key = (finding["code"], finding["field"], finding["text"])
        if key not in seen:
            seen.add(key)
            unique.append(finding)
    return unique


# ================================================================= validation

def _nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _numeric_op(comparator: Any) -> Optional[Callable[[float, float], bool]]:
    """The operator a numeric comparator names; None for anything else (never raises)."""
    return _NUMERIC_OPS.get(comparator) if isinstance(comparator, str) else None


def _rule_errors(kind: str, rule: Any) -> List[str]:
    if rule is None:
        return ([f"resolution_evidence.rule is required for kind {kind!r}"]
                if kind in RULE_REQUIRED_KINDS else [])
    if not isinstance(rule, dict):
        return ["resolution_evidence.rule must be an object"]
    errors = [f"resolution_evidence.rule.{key} is not allowed: a tolerance must be pre-registered "
              "in resolution_tolerance, never set next to the raw value"
              for key in TOLERANCE_KEYS if key in rule]
    if "field" in rule and not _nonempty_str(rule["field"]):
        errors.append("resolution_evidence.rule.field must be a non-empty string")
    comparator, threshold = rule.get("comparator"), rule.get("threshold")
    if kind in THRESHOLD_KINDS:
        if _numeric_op(comparator) is None:
            errors.append(f"resolution_evidence.rule.comparator must be one of {', '.join(_NUMERIC_OPS)}")
        if _finite(threshold) is None:
            errors.append("resolution_evidence.rule.threshold must be a finite number")
    elif kind == KIND_CATEGORICAL:
        if comparator not in CATEGORICAL_COMPARATORS:
            errors.append("resolution_evidence.rule.comparator must be one of "
                          + ", ".join(CATEGORICAL_COMPARATORS))
        elif comparator in ("in", "not_in"):
            if not (isinstance(threshold, list) and threshold and all(_nonempty_str(t) for t in threshold)):
                errors.append("resolution_evidence.rule.threshold must be a non-empty list of strings "
                              f"for comparator {comparator!r}")
        elif not _nonempty_str(threshold):
            errors.append("resolution_evidence.rule.threshold must be a non-empty string")
    aggregation = rule.get("aggregation")
    if aggregation is not None and aggregation not in AGGREGATIONS:
        errors.append(f"resolution_evidence.rule.aggregation must be one of {', '.join(AGGREGATIONS)}")
    bounds: Dict[str, Optional[datetime]] = {}
    for bound, day_end in (("window_start", False), ("window_end", True)):
        if rule.get(bound) is not None:
            bounds[bound] = _instant(rule[bound], day_end=day_end)
            if bounds[bound] is None:
                errors.append(f"resolution_evidence.rule.{bound} must be a YYYY-MM-DD date or an aware timestamp")
    start, end = bounds.get("window_start"), bounds.get("window_end")
    if start and end and start > end:
        errors.append("resolution_evidence.rule.window_start must not be after window_end")
    return errors


def _evidence_errors(evidence: Any) -> List[str]:
    if evidence is None:
        return []
    if not isinstance(evidence, dict) or not evidence:
        return ["resolution_evidence must be a non-empty object or null"]
    kind = evidence.get("kind")
    if kind not in EVIDENCE_KINDS:
        return [f"resolution_evidence.kind must be one of {', '.join(EVIDENCE_KINDS)}"]
    errors: List[str] = []
    if not _nonempty_str(evidence.get("source_url")):
        errors.append("resolution_evidence.source_url is required")
    if evidence.get("archived_url") is not None and not _nonempty_str(evidence["archived_url"]):
        errors.append("resolution_evidence.archived_url must be a non-empty string or null")
    raw, rule = evidence.get("raw_value"), evidence.get("rule")
    if raw is None:
        errors.append("resolution_evidence.raw_value is required")
    if (kind in RULE_REQUIRED_KINDS and isinstance(raw, dict) and isinstance(rule, dict)
            and "field" not in rule):
        errors.append("resolution_evidence.rule.field must name the raw_value key the rule reads")
    return errors + _rule_errors(kind, rule)


def _tolerance_errors(tolerance: Any, kind: Any) -> List[str]:
    if tolerance is None:
        return []
    if not isinstance(tolerance, dict):
        return ["resolution_tolerance must be an object or null"]
    errors: List[str] = []
    keys = [key for key in TOLERANCE_KEYS if key in tolerance]
    if len(keys) != 1:
        errors.append("resolution_tolerance must set exactly one of epsilon_abs or epsilon_rel")
    elif _finite(tolerance[keys[0]]) is None or tolerance[keys[0]] < 0:
        errors.append(f"resolution_tolerance.{keys[0]} must be a finite number >= 0")
    if not _nonempty_str(tolerance.get("basis")):
        errors.append("resolution_tolerance.basis must state why the band was chosen")
    if kind is not None and kind not in TOLERANCE_KINDS:
        errors.append(f"resolution_tolerance applies only to {' / '.join(TOLERANCE_KINDS)} evidence "
                      "(counts, winners and settlements use epsilon 0)")
    return errors


def _date_errors(q: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    as_of = eval_stats.parse_iso_date(q.get("as_of_date"))
    resolved = eval_stats.parse_iso_date(q.get("resolution_date"))
    for field, parsed in (("as_of_date", as_of), ("resolution_date", resolved)):
        if q.get(field) is not None and parsed is None:
            errors.append(f"{field} must be a canonical YYYY-MM-DD date")
    if as_of and resolved and not as_of < resolved:
        errors.append(f"as_of_date {as_of.isoformat()} must be strictly before resolution_date "
                      f"{resolved.isoformat()}")
    resolve_time = parse_utc_instant(q.get("resolve_time"))
    if q.get("resolve_time") is not None and resolve_time is None:
        errors.append("resolve_time must be an ISO-8601 UTC timestamp (...Z or +00:00)")
    # Compared by UTC calendar date: "after the end of the as_of day" must also reject
    # a sub-second time on that day (23:59:59.5Z), and dates never overflow.
    if as_of and resolve_time and not resolve_time.date() > as_of:
        errors.append(f"resolve_time {q.get('resolve_time')} must be after the end of the as_of day "
                      f"{as_of.isoformat()} (UTC)")
    precision = q.get("resolve_time_precision")
    if precision is not None and precision not in RESOLVE_TIME_PRECISIONS:
        errors.append(f"resolve_time_precision must be one of {', '.join(RESOLVE_TIME_PRECISIONS)}")
    if resolve_time and resolved and resolve_time.date() != resolved:
        errors.append(f"resolve_time {q.get('resolve_time')} must fall on resolution_date "
                      f"{resolved.isoformat()} (resolution_date is its UTC calendar date)")
    elif precision == "day" and resolve_time and resolved and resolve_time != end_of_day(resolved):
        errors.append(f"a day-precision resolve_time must be {resolved.isoformat()}T23:59:59Z")
    return errors


def _reviewed_errors(q: Dict[str, Any]) -> List[str]:
    reviewed = q.get("reviewed_parentheticals")
    if reviewed is None:
        return []
    if not isinstance(reviewed, list):
        return ["reviewed_parentheticals must be a list"]
    visible = " ".join(str(q.get(f) or "") for f in ("question", "resolution_criteria"))
    errors: List[str] = []
    for item in reviewed:
        if not (isinstance(item, str) and len(item) >= 2
                and item[0] in _OPEN_PARENS and item[-1] in _CLOSE_PARENS):
            errors.append(f"reviewed parenthetical {item!r} must be a verbatim '(...)' span")
        elif item not in visible:
            errors.append(f"reviewed parenthetical {item!r} does not appear in the question or criteria")
    return errors


def validate_question(q: Any, strict: bool = False) -> List[str]:
    """Schema v2 contract errors for one golden row (empty list when valid).

    Checks: required fields; canonical dates with as_of_date strictly before
    resolution_date; a UTC resolve_time after the end of the as_of day and on
    resolution_date (its UTC calendar date; 23:59:59Z at 'day' precision);
    enumerated statuses; evidence shape (a window that does not end before it
    starts) and tolerance shape (numeric_threshold evidence only); zero leak
    findings; a boolean resolved_outcome unless scoring_status is 'ambiguous'
    (boolean or null there). ``strict`` also requires ``verification ==
    'verified'`` and non-empty ``resolution_evidence``. Whether the evidence
    recomputes the recorded label is ``recompute_mismatch``'s job.
    """
    if not isinstance(q, dict):
        return ["entry is not an object"]
    errors = [f"missing required field {field!r}" for field in REQUIRED_TEXT_FIELDS
              if not _nonempty_str(q.get(field))]
    status = q.get("scoring_status", SCORING_SCORED)
    if status not in SCORING_STATUSES:
        errors.append(f"scoring_status must be one of {', '.join(SCORING_STATUSES)}")
    outcome = q.get("resolved_outcome")
    if status != SCORING_AMBIGUOUS and not isinstance(outcome, bool):
        errors.append("resolved_outcome must be a boolean unless scoring_status is 'ambiguous'")
    elif status == SCORING_AMBIGUOUS and outcome is not None and not isinstance(outcome, bool):
        errors.append("an ambiguous row's resolved_outcome must be a boolean or null")
    if _nonempty_str(q.get("verification")) and q["verification"] not in VERIFICATION_STATES:
        errors.append(f"verification must be one of {', '.join(VERIFICATION_STATES)}")
    if q.get("shift_axis") is not None and q["shift_axis"] not in SHIFT_AXES:
        errors.append(f"shift_axis must be one of {', '.join(SHIFT_AXES)}")
    if q.get("hindsight_framed") is not None and not isinstance(q["hindsight_framed"], bool):
        errors.append("hindsight_framed must be a boolean")
    for field in ("resolution_note", "primary_entity"):
        if q.get(field) is not None and not isinstance(q[field], str):
            errors.append(f"{field} must be a string or null")
    errors += _date_errors(q)
    errors += _reviewed_errors(q)
    evidence = q.get("resolution_evidence")
    errors += _evidence_errors(evidence)
    kind = evidence.get("kind") if isinstance(evidence, dict) else None
    errors += _tolerance_errors(q.get("resolution_tolerance"), kind)
    errors += [f"leak {f['code']} in {f['field']}: {f['text']}" for f in leak_findings(q)]
    if strict:
        if q.get("verification") != VERIFIED:
            errors.append(f"strict: verification must be {VERIFIED!r}, got {q.get('verification')!r}")
        if not (isinstance(evidence, dict) and evidence):
            errors.append("strict: resolution_evidence is required")
    return errors


# ================================================================== recompute

def _field_value(raw: Any, field: Any) -> Any:
    """``raw[field]`` for an object raw_value, the raw value itself otherwise (None if unset)."""
    if isinstance(raw, dict):
        return raw.get(field) if _nonempty_str(field) else None
    return raw


def _window(rule: Dict[str, Any]) -> Optional[Tuple[Optional[datetime], Optional[datetime]]]:
    """Inclusive (start, end) bounds of the rule window.

    None when a given bound is malformed or the window ends before it starts: an
    inverted window would silently empty every series and label every event NO.
    """
    bounds = []
    for key, day_end in (("window_start", False), ("window_end", True)):
        value = rule.get(key)
        parsed = _instant(value, day_end=day_end) if value is not None else None
        if value is not None and parsed is None:
            return None
        bounds.append(parsed)
    start, end = bounds
    if start and end and start > end:
        return None
    return start, end


def _aggregate(value: Any, rule: Dict[str, Any]) -> Optional[float]:
    """The number the comparator judges: a scalar, or a reduction of a [{t, v}] series."""
    aggregation = rule.get("aggregation") or "value"
    if aggregation == "value":
        return _finite(value)
    if aggregation not in AGGREGATIONS or not isinstance(value, list):
        return None
    window = _window(rule)
    if window is None:
        return None
    start, end = window
    points: List[Tuple[Optional[datetime], Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            return None
        stamp = _instant(entry.get("t"), day_end=False) if entry.get("t") is not None else None
        if stamp is None and (start or end or aggregation in ("first", "last")):
            return None
        if (start and stamp < start) or (end and stamp > end):
            continue
        points.append((stamp, entry.get("v")))
    if aggregation == "count":
        return float(len(points))
    if aggregation in ("first", "last"):
        points.sort(key=lambda point: point[0])
    values = [_finite(v) for _, v in points]
    if any(v is None for v in values):
        return None
    if aggregation == "sum":
        return float(sum(values))
    if not values:
        return None
    if aggregation == "mean":
        return sum(values) / len(values)
    reducers: Dict[str, Callable[[List[float]], float]] = {
        "max": max, "min": min, "first": lambda vs: vs[0], "last": lambda vs: vs[-1]}
    return reducers[aggregation](values)


def _tolerance_eps(tolerance: Any, threshold: float) -> Optional[float]:
    """Half-width of the pre-registered dead band (0.0 without one); None when malformed."""
    if tolerance is None:
        return 0.0
    if not isinstance(tolerance, dict):
        return None
    keys = [key for key in TOLERANCE_KEYS if key in tolerance]
    if len(keys) != 1:
        return None
    eps = _finite(tolerance[keys[0]])
    if eps is None or eps < 0:
        return None
    return eps if keys[0] == "epsilon_abs" else eps * abs(threshold)


def _threshold_label(value: Optional[float], rule: Dict[str, Any], tolerance: Any) -> str:
    op, threshold = _numeric_op(rule.get("comparator")), _finite(rule.get("threshold"))
    if value is None or threshold is None or op is None:
        return LABEL_UNVERIFIABLE
    eps = _tolerance_eps(tolerance, threshold)
    if eps is None:
        return LABEL_UNVERIFIABLE
    if eps > 0 and abs(value - threshold) <= eps:
        return LABEL_AMBIGUOUS
    return LABEL_YES if op(value, threshold) else LABEL_NO


def _category(text: Any) -> Optional[str]:
    return " ".join(text.split()).casefold() if isinstance(text, str) and text.strip() else None


def _categorical_label(value: Any, rule: Dict[str, Any]) -> str:
    actual, comparator, threshold = _category(value), rule.get("comparator"), rule.get("threshold")
    if actual is None or comparator not in CATEGORICAL_COMPARATORS:
        return LABEL_UNVERIFIABLE
    if comparator in ("in", "not_in"):
        options = [_category(t) for t in threshold] if isinstance(threshold, list) and threshold else [None]
        if any(o is None for o in options):
            return LABEL_UNVERIFIABLE
        hit = actual in options
        return LABEL_YES if hit == (comparator == "in") else LABEL_NO
    expected = _category(threshold)
    if expected is None:
        return LABEL_UNVERIFIABLE
    return LABEL_YES if (actual == expected) == (comparator == "==") else LABEL_NO


def _market_label(value: Any) -> str:
    price = _finite(value)
    if price is None or not 0.0 <= price <= 1.0:
        return LABEL_UNVERIFIABLE
    if price >= MARKET_SETTLED_YES:
        return LABEL_YES
    if price <= MARKET_SETTLED_NO:
        return LABEL_NO
    if abs(price - MARKET_VOID_PRICE) <= MARKET_VOID_BAND:
        return LABEL_AMBIGUOUS
    return LABEL_UNVERIFIABLE


def _occurrence_label(raw: Any, rule: Dict[str, Any]) -> str:
    occurred = _field_value(raw, rule.get("field") or OCCURRENCE_DEFAULT_FIELD)
    if not isinstance(occurred, bool):
        return LABEL_UNVERIFIABLE
    if not occurred:
        return LABEL_NO
    window = _window(rule)
    if window is None:
        return LABEL_UNVERIFIABLE
    start, end = window
    if not (start or end):
        return LABEL_YES
    stamp = _instant(raw.get("occurred_at"), day_end=False) if isinstance(raw, dict) else None
    if stamp is None:
        return LABEL_UNVERIFIABLE
    return LABEL_NO if (start and stamp < start) or (end and stamp > end) else LABEL_YES


def recompute_label(q: Dict[str, Any]) -> str:
    """Recompute YES / NO / AMBIGUOUS / UNVERIFIABLE from ``resolution_evidence``.

    - numeric_threshold / count_threshold: ``rule.comparator`` applied to
      ``raw_value[rule.field]`` (a scalar, or a [{t, v}] series reduced by
      ``rule.aggregation`` inside ``window_start..window_end``, both inclusive)
      against ``rule.threshold``. Only a pre-registered ``resolution_tolerance``
      on numeric_threshold evidence opens a dead band: ``|value - threshold| <=
      eps`` is AMBIGUOUS (inclusive, symmetric; eps = epsilon_abs or epsilon_rel *
      |threshold|; default none). A count is always judged exactly (epsilon 0). A
      tolerance written into the rule, or set on a count, is ignored here and
      rejected by ``validate_question``. An inverted window is UNVERIFIABLE.
    - categorical: ``==`` / ``!=`` against a string, ``in`` / ``not_in`` against a
      list, compared casefolded with collapsed whitespace.
    - market_settlement: the Yes price (``raw_value.resolved_yes_price`` unless the
      rule names a field): 1.0 -> YES, 0.0 -> NO, 0.5 -> AMBIGUOUS, anything else
      UNVERIFIABLE (not a settlement).
    - event_occurrence: ``raw_value.occurred`` false -> NO; true -> YES, or, with a
      rule window, YES only when ``occurred_at`` falls inside it.

    Missing evidence, or evidence that cannot be evaluated, is UNVERIFIABLE.
    """
    evidence = q.get("resolution_evidence") if isinstance(q, dict) else None
    if not isinstance(evidence, dict) or not evidence:
        return LABEL_UNVERIFIABLE
    kind = evidence.get("kind")
    rule = evidence.get("rule") if isinstance(evidence.get("rule"), dict) else {}
    raw = evidence.get("raw_value")
    if kind in THRESHOLD_KINDS:
        tolerance = q.get("resolution_tolerance") if kind in TOLERANCE_KINDS else None
        return _threshold_label(_aggregate(_field_value(raw, rule.get("field")), rule), rule, tolerance)
    if kind == KIND_CATEGORICAL:
        return _categorical_label(_field_value(raw, rule.get("field")), rule)
    if kind == KIND_MARKET:
        return _market_label(_field_value(raw, rule.get("field") or MARKET_DEFAULT_FIELD))
    if kind == KIND_OCCURRENCE:
        return _occurrence_label(raw, rule)
    return LABEL_UNVERIFIABLE


def is_evidence_backed(q: Any) -> bool:
    evidence = q.get("resolution_evidence") if isinstance(q, dict) else None
    return isinstance(evidence, dict) and bool(evidence)


def recompute_mismatch(q: Dict[str, Any]) -> Optional[str]:
    """Why an evidence-backed row's recomputed label disagrees with its record; None when it agrees.

    Rows without evidence are never a mismatch (they are unverified, not wrong). An
    evidence-backed row whose evidence cannot recompute any label is a mismatch:
    evidence that cannot reproduce its own answer is a data defect (fail loud).
    """
    if not is_evidence_backed(q):
        return None
    label, recorded = recompute_label(q), expected_label(q)
    if label == recorded:
        return None
    if label == LABEL_UNVERIFIABLE:
        return f"resolution_evidence cannot recompute a label (UNVERIFIABLE); recorded {recorded}"
    return f"recomputed label {label} from resolution_evidence disagrees with the recorded {recorded}"


# ================================================================ balance audit

def _cluster(q: Dict[str, Any]) -> str:
    return str(q.get("event_cluster") or "").strip() or str(q.get("id") or "").strip()


def balance_audit(questions: Sequence[Any], *,
                  max_category_share: float = DEFAULT_MAX_CATEGORY_SHARE,
                  yes_rate_band: Tuple[float, float] = DEFAULT_YES_RATE_BAND,
                  max_cluster_size: int = DEFAULT_MAX_CLUSTER_SIZE) -> Dict[str, Any]:
    """Report-only composition audit: ``{n, yes_rate, category_shares, n_event_clusters,
    clusters_with_multiple_questions, lead_buckets, advisory_violations}``.

    ``yes_rate`` is over scored rows with a boolean outcome (ambiguous rows excluded).
    ``lead_buckets`` count as_of -> resolution_date days in the eval_stats horizon
    buckets. ``advisory_violations`` lists category shares above
    ``max_category_share``, a YES rate outside ``yes_rate_band``, event clusters with
    more than ``max_cluster_size`` questions and hindsight-framed rows. Nothing gates
    on it: rebalancing needs human curation with verified sources.
    """
    rows = [q for q in questions if isinstance(q, dict)]
    n = len(rows)
    outcomes = [q["resolved_outcome"] for q in rows
                if not is_ambiguous(q) and isinstance(q.get("resolved_outcome"), bool)]
    yes_rate = eval_stats.round4(sum(outcomes) / len(outcomes)) if outcomes else None
    categories = Counter(str(q.get("category") or "unknown") for q in rows)
    category_shares = {key: eval_stats.round4(categories[key] / n) for key in sorted(categories)}
    clusters: Dict[str, List[str]] = {}
    for q in rows:
        clusters.setdefault(_cluster(q), []).append(str(q.get("id") or ""))
    multi = {key: sorted(ids) for key, ids in sorted(clusters.items()) if len(ids) > 1}
    leads = Counter(eval_stats.horizon_bucket(eval_stats.horizon_days(q.get("as_of_date"),
                                                                      q.get("resolution_date")))
                    for q in rows)

    violations: List[Dict[str, str]] = []
    for key, share in category_shares.items():
        if share > max_category_share:
            violations.append({"code": "category_share",
                               "detail": f"{key} {share:.4f} > {max_category_share:.2f}"})
    lo, hi = yes_rate_band
    if yes_rate is not None and not lo <= yes_rate <= hi:
        violations.append({"code": "yes_rate",
                           "detail": f"YES rate {yes_rate:.4f} outside [{lo:.2f}, {hi:.2f}]"})
    for key, ids in multi.items():
        if len(ids) > max_cluster_size:
            violations.append({"code": "cluster_size",
                               "detail": f"{key} has {len(ids)} questions > {max_cluster_size}"})
    for q in rows:
        if q.get("hindsight_framed") is True:
            violations.append({"code": "hindsight_framed", "detail": str(q.get("id") or "")})
    return {
        "n": n,
        "yes_rate": yes_rate,
        "category_shares": category_shares,
        "n_event_clusters": len(clusters),
        "clusters_with_multiple_questions": multi,
        "lead_buckets": {label: leads.get(label, 0) for label in eval_stats.horizon_bucket_labels()},
        "advisory_violations": violations,
    }
