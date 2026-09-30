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
# call the model makes lands in exactly one of the first four; ``repaired``
# counts dispatched calls that needed at least one repair token.
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
# blocks right after a closing brace); JSON does not treat them as whitespace.
_INVISIBLE_CHARS = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"))
# json raises RecursionError (not ValueError) on pathologically deep nesting.
_JSON_ERRORS = (ValueError, RecursionError)

# ---------------------------------------------------------------- observations

# Shown to the model in place of a tool result (Chinese, like the other ReAct prompts).
_TOOL_CALL_EXAMPLE = '<tool_call>{"name":...,"parameters":{...}}</tool_call>'
CHARGED_NOTE = "（无效调用次数已超出免费额度，本次计入工具调用额度）"


def parse_tool_call_block(text: str) -> Tuple[Optional[dict], Optional[str], Optional[str]]:
    """Parse the JSON inside one ``<tool_call>`` block, repairing what is safe to repair.

    Returns ``(obj, repair_kind, error)``: ``obj`` is a dict (``error`` None) or None
    (``error`` says why). Steps, first success wins:

    1. ``json.loads`` of the whole block (no repair);
    2. ``JSONDecoder.raw_decode`` from the first ``{`` - ``first_object_of_many``
       when content follows the object (several calls in one block, trailing
       prose), ``leading_text_skipped`` when only text before it was dropped;
    3. append the missing ``}``/``]`` closers (``brace_balanced``). A block that
       ends inside a string is not repaired: closing it would silently truncate
       an argument value.

    Steps 2-3 run on the block with zero-width/BOM characters removed; when that
    removal alone makes it parse, the repair is ``invisible_chars_removed``.
    """
    s = (text or "").strip()
    if not s:
        return None, None, "empty tool call block"
    try:
        obj = json.loads(s)
    except _JSON_ERRORS as exc:
        first_error = str(exc)
    else:
        if isinstance(obj, dict):
            return obj, None, None
        first_error = f"JSON value is a {type(obj).__name__}, not an object"

    cleaned = s.translate(_INVISIBLE_CHARS).strip()
    if cleaned != s:
        try:
            obj = json.loads(cleaned)
        except _JSON_ERRORS:
            obj = None
        if isinstance(obj, dict):
            return obj, REPAIR_INVISIBLE_CHARS, None
        s = cleaned

    start = s.find("{")
    if start < 0:
        return None, None, first_error
    try:
        obj, end = json.JSONDecoder().raw_decode(s, start)
    except _JSON_ERRORS:
        obj = None
    if isinstance(obj, dict):
        return obj, (REPAIR_FIRST_OBJECT if s[end:].strip() else REPAIR_LEADING_TEXT), None

    balanced = _balance_brackets(s[start:])
    if balanced is not None:
        try:
            obj = json.loads(balanced)
        except _JSON_ERRORS:
            obj = None
        if isinstance(obj, dict):
            return obj, REPAIR_BRACE_BALANCED, None
    return None, None, first_error


def _balance_brackets(fragment: str) -> Optional[str]:
    """``fragment`` plus the closers its unclosed ``{``/``[`` need, or None when that cannot help.

    None when a closer does not match its opener, when the outermost value closes
    before the end (not a missing-closer case), when the text ends inside a
    string, or when nothing is left open. A dangling comma before the appended
    closers is dropped.
    """
    stack: List[str] = []
    in_string = False
    escaped = False
    for index, ch in enumerate(fragment):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in _CLOSERS:
            stack.append(ch)
        elif ch in ("}", "]"):
            if not stack or _CLOSERS[stack.pop()] != ch:
                return None
            if not stack and fragment[index + 1:].strip():
                return None
    if in_string or not stack:
        return None
    body = fragment.rstrip()
    if body.endswith(","):
        body = body[:-1]
    return body + "".join(_CLOSERS[opener] for opener in reversed(stack))


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


def _has_value(params: Dict[str, Any], tool: str, name: str) -> bool:
    """True when ``params`` carries a non-blank value for ``name`` or one of its fallbacks."""
    for key in (name,) + PARAM_FALLBACKS.get((tool, name), ()):
        value = params.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        if isinstance(value, (list, tuple, dict)) and not value:
            continue
        return True
    return False


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
    object; every REQUIRED_PARAMS entry is non-empty (PARAM_FALLBACKS honoured);
    one ALTERNATIVE_REQUIRED_PARAMS group is complete; a non-empty ``as_of``
    parses with :func:`parse_as_of`; INT_PARAMS are whole numbers >= 1 (numeric
    strings are coerced in place, so the dispatched params carry the int).
    Unknown tools only get the generic checks - the caller owns the unknown-name
    decision.
    """
    if not isinstance(params, dict):
        return f"parameters 必须是 JSON 对象（收到 {type(params).__name__}）"
    tool = TOOL_ALIASES.get(name, name)
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
