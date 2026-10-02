"""ReportAgent tool-call boundary: tolerant argument parsing, envelope
normalization and pre-dispatch validation (INFRA-5).

Pure and offline: stdlib plus ``app.utils.dates.parse_as_of``, no LLM and no
``Config`` read. ``report_agent`` wires these helpers into the ReAct loop, the
chat() dispatch and the native function-calling loop behind
``REPORT_TOOL_ARG_REPAIR``.

Why: open-weight models write ``<tool_call>`` blocks that the strict parser
dropped without a word (several JSON objects in one block, a missing closing
brace) or dispatched with empty parameters (flat arguments next to ``name``,
``arguments``/``args``/``input`` instead of ``parameters``). Here a block is
either repaired deterministically, with a repair token per fix, or turned into
an explicit error the model is shown, and a call whose parameters cannot work
is rejected before it spends tool budget. Offline replay of 2,085 logged ReAct
replies that carry a tool call: the strict parser produced 1,950 calls, 1,565
with non-empty parameters; with these repairs 2,081 calls, 1,992 with
parameters (the rest are the parameterless coalition_map and a model-invented
'Final Answer' tool), and the 4 unrecoverable blocks are surfaced, not dropped.

Every ReportAgent tool parameter is a scalar, so there is no container or
list coercion here; the repairs are limited to what the call envelope needs.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Dict, List, Optional, Tuple

from ..utils.dates import parse_as_of

# ---------------------------------------------------------------- repair tokens

REPAIR_FIRST_OBJECT = "first_object_of_many"
REPAIR_LEADING_TEXT = "leading_text_skipped"
REPAIR_BRACE_BALANCED = "brace_balanced"
REPAIR_INVISIBLE_CHARS = "invisible_chars_removed"
REPAIR_UNTERMINATED_BLOCK = "unterminated_block"
REPAIR_ALIASED_KEYS = "aliased_keys"
REPAIR_FLATTENED = "flattened_envelope"
REPAIR_STRINGIFIED = "stringified_parameters"

# ---------------------------------------------------------------- rejection kinds

KIND_ARGS_NOT_JSON = "args_not_json"
KIND_MISSING_NAME = "missing_name"
KIND_INVALID_PARAMS = "invalid_params"

# Outcome counters kept per report (telemetry.json totals.tool_dispatch). Every
# call the loops act on (the selected call of a ReAct turn, each native tool call,
# and up to SKIPPED_BLOCKS_ITEMIZED unparseable blocks skipped beside a ReAct turn's
# selected call) lands in exactly one of the first four; ``repaired`` counts
# dispatched calls that needed at least one repair token.
TOOL_OUTCOME_KEYS = ("dispatched", "rejected_parse", "rejected_params", "rejected_unknown", "repaired")
OUTCOME_FOR_KIND = {
    KIND_ARGS_NOT_JSON: "rejected_parse",
    KIND_MISSING_NAME: "rejected_parse",
    KIND_INVALID_PARAMS: "rejected_params",
}

# ---------------------------------------------------------------- tool contracts

# Required parameters per tool, read from ReportAgent._define_tools / _execute_tool:
# the three retrieval tools run an (expensive) empty search without a query, and
# the actor/entity tools have nothing to look up without their subject.
REQUIRED_PARAMS: Dict[str, Tuple[str, ...]] = {
    "insight_forge": ("query",),
    "panorama_search": ("query",),
    "quick_search": ("query",),
    "interview_agents": ("interview_topic",),
    "opinion_shift": ("actor_name",),
    "get_entity_summary": ("entity_name",),
    "get_entities_by_type": ("entity_type",),
}
# Legacy aliases that _execute_tool redirects with the parameters unchanged; they
# are validated as their target. get_simulation_context also redirects (to
# insight_forge) but supplies its own query when none is given, so it has no entry.
TOOL_ALIASES: Dict[str, str] = {"search_graph": "quick_search"}
# Required parameters that _execute_tool also reads from another name.
PARAM_FALLBACKS: Dict[Tuple[str, str], Tuple[str, ...]] = {
    ("interview_agents", "interview_topic"): ("query",),
    ("opinion_shift", "actor_name"): ("query",),
}
# Tools that need one complete group out of several (trace_cascade: a
# source+target path, or a center neighbourhood).
ALTERNATIVE_REQUIRED_PARAMS: Dict[str, Tuple[Tuple[str, ...], ...]] = {
    "trace_cascade": (("source", "target"), ("center",)),
}
# Optional count parameters: coerced to int in place, rejected when not a whole number >= 1.
INT_PARAMS: Tuple[str, ...] = ("limit", "top_k")

_PARAM_KEY_ALIASES = ("params", "arguments", "args", "input")
# Envelope keys never lifted into parameters by the flat-arguments repair.
_ENVELOPE_KEYS = frozenset({"name", "tool", "id", "type"})
_CLOSERS = {"{": "}", "[": "]"}
# Zero-width / BOM characters some models emit between JSON tokens (seen in logged GLM
# blocks right after a closing brace); JSON does not treat them as whitespace. They are
# removed only outside string literals: inside a value a ZWNJ/ZWJ carries meaning
# (Persian, Indic scripts, emoji sequences).
_INVISIBLE_TEXT = "\u200b\u200c\u200d\u2060\ufeff"
_INVISIBLE_CHARS = dict.fromkeys(map(ord, _INVISIBLE_TEXT))
# json raises RecursionError (not ValueError) on pathologically deep nesting.
_JSON_ERRORS = (ValueError, RecursionError)
# Stateless, so one instance serves every thread.
_DECODER = json.JSONDecoder()

_OPEN_TAG = "<tool_call>"
_CLOSE_TAG = "</tool_call>"
# Start of a bare (untagged) tool-call object. Linear: each candidate's whitespace run is its own.
_BARE_CALL_START_RE = re.compile(r'\{"(?:name|tool)"\s*:')
# Start of a call object inside a block or at the head of a reply (whitespace after the brace
# allowed). Linear for the same reason: a whitespace run belongs to the one brace before it.
_CALL_OPENER_RE = re.compile(r'\{\s*"(?:name|tool)"\s*:')
# The same opener with the tool name as a complete string literal (group 1).
_CALL_NAME_RE = re.compile(r'\{\s*"(?:name|tool)"\s*:\s*"([^"\\\r\n]{1,80})"')
# Call openers after a block's first ``{`` that raw_decode tries when the text from that brace
# is not one object (leading prose with its own braces); bounds the work on degenerate blocks.
_MAX_OPENER_ATTEMPTS = 8
# The ReAct answer marker: a reply that carries one is an answer, not a bare call.
_FINAL_ANSWER_MARKER = "Final Answer"

# tool_rejected rows keep at most this much of the call text (agent_log, not draft-gated).
REJECTION_EXCERPT_CHARS = 300
# Where the call text ends and model prose may begin: the ReAct answer marker, or a blank line.
_EXCERPT_PROSE_BOUNDARY_RE = re.compile(_FINAL_ANSWER_MARKER + r"|\n[ \t\r]*\n")
# Tokens the excerpt keeps outside string literals (see _call_text_prefix).
_IDENT_START = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ_")
_IDENT_CHARS = _IDENT_START | frozenset("0123456789")
_NUMBER_START = frozenset("-0123456789")
_NUMBER_CHARS = frozenset("0123456789+-.eE")
_JSON_LITERALS = frozenset({"true", "false", "null"})
_JSON_WHITESPACE = frozenset(" \t\r\n")
# Unparseable blocks skipped beside a reply's selected call that get their own tool_rejected
# row and outcome count; the rest of a degenerate reply's blocks share one summary row.
SKIPPED_BLOCKS_ITEMIZED = 3

# ---------------------------------------------------------------- observations

# Shown to the model in place of a tool result (Chinese, like the other ReAct prompts).
_TOOL_CALL_EXAMPLE = '<tool_call>{"name":...,"parameters":{...}}</tool_call>'
CHARGED_NOTE = "（无效调用次数已超出免费额度，本次计入工具调用额度）"


def split_tool_call_blocks(text: str) -> List[Tuple[str, Optional[str]]]:
    """The ``<tool_call>`` blocks of a reply, in order, as ``(inner text stripped, block repair)``.

    A block runs from an opener to the next closer, so an opener inside a block is part of its
    text. When an opener follows the last closed block and no closer does (reply cut off at
    max_tokens, or closed with ``</invoke>``), the text after the *last* such opener is one more
    block, tagged ``unterminated_block``.

    A linear ``str.find`` scan: the equivalent lazy regex ``<tool_call>\\s*(.*?)\\s*</tool_call>``
    backtracks cubically when an unclosed opener is followed by a long whitespace run (a
    truncated or degenerate reply), and _sre holds the GIL for the whole match.
    """
    text = text or ""
    blocks: List[Tuple[str, Optional[str]]] = []
    pos = last_end = 0
    while True:
        start = text.find(_OPEN_TAG, pos)
        if start < 0:
            break
        body_start = start + len(_OPEN_TAG)
        end = text.find(_CLOSE_TAG, body_start)
        if end < 0:
            break
        blocks.append((text[body_start:end].strip(), None))
        pos = last_end = end + len(_CLOSE_TAG)
    open_tag = text.rfind(_OPEN_TAG)
    if open_tag >= last_end:
        blocks.append((text[open_tag + len(_OPEN_TAG):].strip(), REPAIR_UNTERMINATED_BLOCK))
    return blocks


def bare_tool_call_candidates(text: str) -> List[str]:
    """Bare-JSON fallback candidates when a reply has no ``<tool_call>`` block, in trial order.

    The whole stripped reply when it is one ``{...}``; then, when it ends with ``}``, the tail
    from the first ``{"name":`` / ``{"tool":``. These are exactly the legacy parser's candidates:
    its ``(\\{"(?:name|tool)"\\s*:.*?\\})\\s*$`` search can only end at the reply's final ``}``,
    so the match always runs from the leftmost key to the end - here found in linear time
    (the regex is quadratic in the number of ``{"name":`` occurrences).
    """
    stripped = (text or "").strip()
    candidates: List[str] = []
    if stripped.startswith("{") and stripped.endswith("}"):
        candidates.append(stripped)
    if stripped.endswith("}"):
        match = _BARE_CALL_START_RE.search(stripped)
        if match:
            candidates.append(stripped[match.start():])
    return candidates


def broken_bare_call(text: str) -> Optional[Tuple[str, str]]:
    """A reply that is one bare call object that does not decode: ``(stripped reply, declared
    tool name)``, else None. The caller tries it after :func:`bare_tool_call_candidates` failed.

    Those candidates only exist for replies that end with ``}``, so a bare call cut short of its
    outer brace (``{"name": "quick_search", "query": "gold"``) was dropped without a word. Only a
    reply that *starts* with a ``{"name": "<tool>"`` / ``{"tool": "<tool>"`` key qualifies, and
    only when the object there does not decode (a complete call followed by prose keeps the
    legacy behaviour) and the reply carries no ``Final Answer`` (then it is an answer). Prose
    braces never qualify.
    """
    stripped = (text or "").strip()
    match = _CALL_NAME_RE.match(stripped)
    if not match or _FINAL_ANSWER_MARKER in stripped:
        return None
    try:
        _DECODER.raw_decode(stripped)
    except _JSON_ERRORS:
        return stripped, match.group(1)
    return None


def parse_tool_call_block(text: str) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Parse the JSON inside one ``<tool_call>`` block, repairing what is safe to repair.

    Returns ``(obj, repair_kind, error)``: ``obj`` is a dict (``error`` None) or None
    (``error`` says why). ``repair_kind`` is the deciding repair - the last token
    :func:`parse_tool_call_block_repairs` reports - or None when none was needed.
    """
    obj, repairs, error = parse_tool_call_block_repairs(text)
    return obj, (repairs[-1] if repairs else None), error


def parse_tool_call_block_repairs(text: str) -> Tuple[Optional[dict], List[str], Optional[str]]:
    """:func:`parse_tool_call_block` with every repair token applied, in order.

    Returns ``(obj, repairs, error)`` (``repairs`` empty on failure). Steps, first success wins:

    1. ``json.loads`` of the whole block (no repair);
    2. ``JSONDecoder.raw_decode`` from the first ``{`` - ``first_object_of_many``
       when content follows the object (several calls in one block, trailing
       prose), ``leading_text_skipped`` when only text before it was dropped;
       when that brace does not start an object (leading prose such as
       ``我用 {query} 检索``), the same from each later ``{"name":`` / ``{"tool":``
       opener that sits outside every bracket opened before it (never a call-shaped
       object nested inside the first one), at most ``_MAX_OPENER_ATTEMPTS``;
    3. append the missing ``}``/``]`` closers (``brace_balanced``) to the text from
       the first ``{``, else from the last such opener. A block that ends inside a
       string is not repaired: closing it would silently truncate an argument value.

    Steps 2-3 run on the block with zero-width/BOM characters removed outside string
    literals, so argument values are never altered; whenever that removal changed the
    text, ``invisible_chars_removed`` leads the repairs (alone when it was the whole fix).
    """
    s = (text or "").strip()
    if not s:
        return None, [], "empty tool call block"
    try:
        obj = json.loads(s)
    except _JSON_ERRORS as exc:
        first_error = str(exc)
    else:
        if isinstance(obj, dict):
            return obj, [], None
        first_error = f"JSON value is a {type(obj).__name__}, not an object"

    repairs: List[str] = []
    cleaned = _strip_invisible_chars(s).strip()
    if cleaned != s:
        repairs.append(REPAIR_INVISIBLE_CHARS)
        s = cleaned
        try:
            obj = json.loads(s)
        except _JSON_ERRORS:
            obj = None
        if isinstance(obj, dict):
            return obj, repairs, None

    start = s.find("{")
    if start < 0:
        return None, [], first_error
    decoded = _decode_object_at(s, start)
    openers: List[int] = []
    if decoded is None:
        openers = _top_level_call_openers(s, start)
        for origin in openers:
            decoded = _decode_object_at(s, origin)
            if decoded is not None:
                break
    if decoded is not None:
        obj, end = decoded
        return obj, repairs + [REPAIR_FIRST_OBJECT if s[end:].strip() else REPAIR_LEADING_TEXT], None

    # Only the last top-level opener can still be open at the end of the block.
    for origin in [start] + openers[-1:]:
        balanced = _balance_brackets(s[origin:])
        if balanced is None:
            continue
        try:
            obj = json.loads(balanced)
        except _JSON_ERRORS:
            obj = None
        if isinstance(obj, dict):
            return obj, repairs + [REPAIR_BRACE_BALANCED], None
    return None, [], first_error


def _decode_object_at(text: str, index: int) -> Optional[Tuple[dict, int]]:
    """``(object, end offset)`` when a complete JSON object starts at ``text[index]``, else None."""
    try:
        obj, end = _DECODER.raw_decode(text, index)
    except _JSON_ERRORS:
        return None
    return (obj, end) if isinstance(obj, dict) else None


def _top_level_call_openers(text: str, start: int) -> List[int]:
    """Offsets of the ``{"name":`` / ``{"tool":`` openers after ``text[start]`` (a ``{``) that sit
    outside every bracket opened from ``start`` on, string literals ignored; at most
    ``_MAX_OPENER_ATTEMPTS``.

    Depth 0 is what keeps a call-shaped object nested inside the first one (a parameter that
    happens to carry a ``name`` key) from being taken for the call. Stray closers in prose do
    not push the depth below 0.
    """
    fragment = text[start:]
    mask, _ = _string_literal_mask(fragment)
    openers: List[int] = []
    depth = 0
    for index, ch in enumerate(fragment):
        if mask[index]:
            continue
        if ch in _CLOSERS:
            if depth == 0 and index and _CALL_OPENER_RE.match(fragment, index):
                openers.append(start + index)
                if len(openers) >= _MAX_OPENER_ATTEMPTS:
                    break
            depth += 1
        elif ch in ("}", "]"):
            depth = max(0, depth - 1)
    return openers


def _string_literal_mask(text: str) -> Tuple[bytearray, bool]:
    """Per character of ``text``: 1 inside a JSON string literal (quotes included), else 0;
    plus whether ``text`` ends inside an unterminated string. JSON escapes are honoured."""
    mask = bytearray(len(text))
    in_string = False
    escaped = False
    for index, ch in enumerate(text):
        if in_string:
            mask[index] = 1
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            mask[index] = 1
            in_string = True
    return mask, in_string


def _strip_invisible_chars(text: str) -> str:
    """``text`` without zero-width/BOM characters outside JSON string literals.

    String state is tracked from the first ``{`` (the JSON); invisible characters in any text
    before it are removed unconditionally.
    """
    if not any(ch in text for ch in _INVISIBLE_TEXT):
        return text
    start = text.find("{")
    if start < 0:
        return text.translate(_INVISIBLE_CHARS)
    body = text[start:]
    mask, _ = _string_literal_mask(body)
    kept = "".join(ch for index, ch in enumerate(body) if mask[index] or ord(ch) not in _INVISIBLE_CHARS)
    return text[:start].translate(_INVISIBLE_CHARS) + kept


def _balance_brackets(fragment: str) -> Optional[str]:
    """``fragment`` plus the closers its unclosed ``{``/``[`` need, or None when that cannot help.

    None when a closer does not match its opener, when the outermost value closes
    before the end (not a missing-closer case), when the text ends inside a
    string, or when nothing is left open. A dangling comma before the appended
    closers is dropped.
    """
    mask, ends_in_string = _string_literal_mask(fragment)
    if ends_in_string:
        return None
    stack: List[str] = []
    for index, ch in enumerate(fragment):
        if mask[index]:
            continue
        if ch in _CLOSERS:
            stack.append(ch)
        elif ch in ("}", "]"):
            if not stack or _CLOSERS[stack.pop()] != ch:
                return None
            if not stack and fragment[index + 1:].strip():
                return None
    if not stack:
        return None
    body = fragment.rstrip()
    if body.endswith(","):
        body = body[:-1]
    return body + "".join(_CLOSERS[opener] for opener in reversed(stack))


def rejection_excerpt(raw: Any, limit: int = REJECTION_EXCERPT_CHARS) -> str:
    """The call text a ``tool_rejected`` agent_log row keeps: skeleton only, never draft prose.

    Fails closed, because an unterminated block runs to the end of the reply and can carry the
    section body: the text is first cut at the first ``Final Answer`` or blank line; the excerpt
    then starts at the first call opener (``{"name":`` / ``{"tool":``), else at the first ``{``,
    and is ``""`` when there is none; from there it keeps at most ``limit`` characters of
    call-syntax tokens (:func:`_call_text_prefix`), ending right after the first complete object.
    """
    text = "" if raw is None else str(raw)
    boundary = _EXCERPT_PROSE_BOUNDARY_RE.search(text)
    if boundary:
        text = text[:boundary.start()]
    opener = _CALL_OPENER_RE.search(text)
    start = opener.start() if opener else text.find("{")
    if start < 0:
        return ""
    return _call_text_prefix(text[start:start + max(0, limit)]).rstrip()


def _call_text_prefix(fragment: str) -> str:
    """The longest prefix of ``fragment`` (which starts with ``{``) made of call-syntax tokens,
    up to and including the closer of its first value.

    Kept: brackets, ``:`` and ``,``, whitespace, numbers, ``true``/``false``/``null``, quoted
    strings (double or single quotes, as models write both) and unquoted keys (an ASCII
    identifier followed by ``:``). A raw line break inside a string ends the prefix (a JSON
    string cannot hold one, so the string never closed and what follows is prose), and so does
    any other character outside a string: CJK text, a Markdown heading, an English word.
    """
    depth = 0
    index = 0
    length = len(fragment)
    while index < length:
        ch = fragment[index]
        if ch in _CLOSERS:
            depth += 1
        elif ch in ("}", "]"):
            depth -= 1
            if depth <= 0:
                return fragment[:index + 1]
        elif ch in ('"', "'"):
            end = index + 1
            while end < length and fragment[end] != ch:
                step = 2 if fragment[end] == "\\" else 1  # an escape covers the next character
                if "\r" in fragment[end:end + step] or "\n" in fragment[end:end + step]:
                    return fragment[:end]
                end += step
            index = end + 1
            continue
        elif ch in _NUMBER_START:
            end = index + 1
            while end < length and fragment[end] in _NUMBER_CHARS:
                end += 1
            index = end
            continue
        elif ch in _IDENT_START:
            end = index + 1
            while end < length and fragment[end] in _IDENT_CHARS:
                end += 1
            probe = end
            while probe < length and fragment[probe] in _JSON_WHITESPACE:
                probe += 1
            if fragment[index:end] not in _JSON_LITERALS and fragment[probe:probe + 1] != ":":
                return fragment[:index]
            index = end
            continue
        elif ch not in _JSON_WHITESPACE and ch not in (":", ","):
            return fragment[:index]
        index += 1
    return fragment


def normalize_envelope(obj: Any) -> Tuple[Dict[str, Any], List[str]]:
    """Normalize one parsed call to ``{"name": ..., "parameters": {...}, ...}``.

    Returns a new dict (the input is not mutated) and the repair tokens applied:

    * ``tool`` -> ``name`` and ``params``/``arguments``/``args``/``input`` ->
      ``parameters`` (``aliased_keys``);
    * no parameters key at all but a ``name``: every other top-level key except
      ``tool``/``id``/``type`` is lifted into ``parameters`` (``flattened_envelope``),
      so ``{"name": "quick_search", "query": "x"}`` no longer runs with ``{}``;
    * ``parameters`` given as a JSON-object string is decoded
      (``stringified_parameters``); ``"parameters": null`` becomes ``{}``.

    A ``parameters`` value of any other type is left for :func:`validate_call` to reject.
    """
    call: Dict[str, Any] = dict(obj) if isinstance(obj, dict) else {}
    repairs: List[str] = []
    if "name" not in call and "tool" in call:
        call["name"] = call.pop("tool")
        repairs.append(REPAIR_ALIASED_KEYS)
    if "parameters" not in call:
        for alias in _PARAM_KEY_ALIASES:
            if alias in call:
                call["parameters"] = call.pop(alias)
                if REPAIR_ALIASED_KEYS not in repairs:
                    repairs.append(REPAIR_ALIASED_KEYS)
                break
    if "parameters" not in call and call.get("name"):
        lifted = {key: call.pop(key) for key in list(call) if key not in _ENVELOPE_KEYS}
        call["parameters"] = lifted
        if lifted:
            repairs.append(REPAIR_FLATTENED)
    params = call.get("parameters")
    if isinstance(params, str):
        try:
            decoded = json.loads(params)
        except _JSON_ERRORS:
            decoded = None
        if isinstance(decoded, dict):
            call["parameters"] = decoded
            repairs.append(REPAIR_STRINGIFIED)
    elif params is None and "parameters" in call:
        call["parameters"] = {}
    return call, repairs


def _is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return isinstance(value, (list, tuple, dict)) and not value


def _has_value(params: Dict[str, Any], tool: str, name: str) -> bool:
    """True when ``params`` carries a non-blank value for ``name`` or one of its fallbacks."""
    return any(not _is_blank(params.get(key)) for key in (name,) + PARAM_FALLBACKS.get((tool, name), ()))


def _apply_param_fallbacks(params: Dict[str, Any], tool: str) -> None:
    """Replace a present-but-blank required value by its fallback's value, in place.

    _execute_tool reads a fallback only when the primary key is absent
    (``parameters.get("interview_topic", parameters.get("query", ""))``), so
    ``{"interview_topic": "", "query": "x"}`` would pass the fallback-aware check and
    still run with the blank topic.
    """
    for (fallback_tool, name), fallbacks in PARAM_FALLBACKS.items():
        if fallback_tool != tool or name not in params or not _is_blank(params[name]):
            continue
        for fallback in fallbacks:
            if not _is_blank(params.get(fallback)):
                params[name] = params[fallback]
                break


def _coerce_int_param(params: Dict[str, Any], name: str) -> Optional[str]:
    """Coerce ``params[name]`` to an int >= 1 in place; an error message when it is not one.

    A blank or null value is removed so the tool's own default applies.
    """
    value = params[name]
    if value is None or (isinstance(value, str) and not value.strip()):
        del params[name]
        return None
    number: Optional[int] = None
    if isinstance(value, bool):
        number = None
    elif isinstance(value, int):
        number = value
    elif isinstance(value, (float, str)):
        try:
            as_float = float(value.strip() if isinstance(value, str) else value)
        except ValueError:
            as_float = math.nan
        if math.isfinite(as_float) and as_float.is_integer():
            number = int(as_float)
    if number is None:
        return f"{name} 必须是正整数（收到 {value!r}）"
    if number < 1:
        return f"{name} 必须 >= 1（收到 {value!r}）"
    params[name] = number
    return None


def validate_call(name: str, params: Any) -> Optional[str]:
    """Check one call before dispatch; None when it may run, else the problems (Chinese).

    ``name`` is resolved through TOOL_ALIASES first. Checks: ``params`` is an
    object; every REQUIRED_PARAMS entry is non-empty (PARAM_FALLBACKS honoured: a
    blank required value is replaced in place by its fallback's value);
    one ALTERNATIVE_REQUIRED_PARAMS group is complete; a non-empty ``as_of``
    parses with :func:`parse_as_of`; INT_PARAMS are whole numbers >= 1 (numeric
    strings are coerced in place, so the dispatched params carry the int).
    Unknown tools only get the generic checks - the caller owns the unknown-name
    decision.
    """
    if not isinstance(params, dict):
        return f"parameters 必须是 JSON 对象（收到 {type(params).__name__}）"
    tool = TOOL_ALIASES.get(name, name)
    _apply_param_fallbacks(params, tool)
    problems: List[str] = []
    missing = [param for param in REQUIRED_PARAMS.get(tool, ()) if not _has_value(params, tool, param)]
    if missing:
        problems.append("缺少必填参数 " + "、".join(missing))
    groups = ALTERNATIVE_REQUIRED_PARAMS.get(tool)
    if groups and not any(all(_has_value(params, tool, param) for param in group) for group in groups):
        problems.append("需提供以下参数组之一：" + " 或 ".join("+".join(group) for group in groups))
    as_of = params.get("as_of")
    if as_of is not None and not (isinstance(as_of, str) and not as_of.strip()):
        if parse_as_of(as_of) is None:
            problems.append(f"as_of 无法解析为日期（收到 {as_of!r}，请用 YYYY-MM-DD 或年份）")
    for param in INT_PARAMS:
        if param in params:
            error = _coerce_int_param(params, param)
            if error:
                problems.append(error)
    return "；".join(problems) or None


def rejection_observation(kind: str, detail: str = "", tool_name: str = "", charged: bool = False) -> str:
    """The corrective observation the model sees for a rejected call (instead of a result)."""
    if kind == KIND_ARGS_NOT_JSON:
        text = f"工具调用参数不是有效的 JSON：{detail}。请只输出一个 {_TOOL_CALL_EXAMPLE}。"
    elif kind == KIND_MISSING_NAME:
        text = f"工具调用缺少工具名（name 字段）。请只输出一个 {_TOOL_CALL_EXAMPLE}。"
    else:
        text = (f"工具 {tool_name} 的参数无效：{detail}。请修正参数后重新调用，"
                f"格式为 {_TOOL_CALL_EXAMPLE}。")
    return text + (CHARGED_NOTE if charged else "")


def skipped_blocks_note(errors: List[str]) -> str:
    """Observation prefix for the unparseable blocks of a reply that were not acted on because
    another block of the same reply was (``""`` when there are none): the model is told they
    were not run instead of the blocks vanishing. At most SKIPPED_BLOCKS_ITEMIZED distinct
    reasons are listed, so a degenerate reply cannot blow up the next prompt."""
    if not errors:
        return ""
    distinct = list(dict.fromkeys(str(error) for error in errors))
    reasons = "；".join(distinct[:SKIPPED_BLOCKS_ITEMIZED])
    if len(distinct) > SKIPPED_BLOCKS_ITEMIZED:
        reasons += "；…"
    return (f"（本次回复中另有 {len(errors)} 个工具调用块无法解析（{reasons}），未执行；"
            f"每次回复只输出一个 {_TOOL_CALL_EXAMPLE}。）\n")


def new_tool_outcomes() -> Dict[str, int]:
    return dict.fromkeys(TOOL_OUTCOME_KEYS, 0)


class RejectionBudget:
    """Per-section count of rejected tool calls: the first ``free`` are not charged.

    Past the cap every further rejection is charged against the tool budget, so a
    model that keeps emitting unusable calls cannot loop for free.
    """

    def __init__(self, free: int):
        self.free = max(0, int(free))
        self.count = 0

    def register(self) -> bool:
        """Record one rejection; True when it is charged."""
        self.count += 1
        return self.count > self.free


def evidence_floor_unmet(dispatched: int, charged: int, floor: int, cap: int) -> bool:
    """Whether a section still owes tool calls before its body can be accepted.

    ``dispatched`` counts the calls that ran; ``charged`` is the tool budget spent, which also
    holds the rejections charged past the free cap. Only dispatched calls meet the floor: a
    charged rejection spends budget but gathers no evidence. When charged rejections have used
    up the budget (``charged >= cap``) no further call can run, so the floor is waived instead
    of sending the model back and forth between "call more tools" and "no tool budget left".
    Without charged rejections (``dispatched == charged``, always the case with
    REPORT_TOOL_ARG_REPAIR off) this is exactly the legacy ``charged < floor``.
    """
    if dispatched >= floor:
        return False
    return dispatched == charged or charged < cap
