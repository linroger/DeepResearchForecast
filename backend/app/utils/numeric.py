"""Non-finite number guards for JSON artifacts and LLM JSON (INFRA-4).

Python's ``json`` accepts and emits ``NaN`` / ``Infinity`` / ``-Infinity`` by
default, but they are not JSON (RFC 8259): a browser's ``JSON.parse`` rejects a
forecast.json carrying one, and a model reply such as ``{"p": NaN}`` or
``{"p": 1e999}`` decodes into a float that later poisons arithmetic.  This
module is the shared vocabulary for both directions:

* reading: :func:`reject_nonfinite_constant` and :func:`parse_finite_float` are
  ``json.loads`` hooks (``parse_constant`` / ``parse_float``) that turn a
  non-finite token into a ``json.JSONDecodeError``, so the caller's existing
  invalid-JSON handling (chat_json's repair turn) runs;
* writing: :func:`find_nonfinite` names every non-finite float by JSON path,
  :func:`dumps_strict` serializes with ``allow_nan=False`` and raises
  :class:`NonFiniteJSONError` naming those paths, and :func:`null_nonfinite`
  returns a copy with each such leaf set to ``None`` (for writers that must
  still produce a standards-compliant artifact).

Only floats can be non-finite: ints (arbitrary precision) are always finite and
bools are not numbers here.  Dict keys are not inspected (a JSON object key is a
string).  Pure and stdlib-only; no I/O.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, List, NoReturn, Optional, Set, Tuple

# Message of the JSONDecodeError raised by the decode hooks below.
NONFINITE_CONSTANT_MSG = "non-finite constant"
# Paths named in a NonFiniteJSONError message (the exception keeps all of them).
_MESSAGE_PATHS = 10
# The json encoder's ValueError text for a non-finite float under allow_nan=False.
_ENCODER_NONFINITE_TEXT = "out of range float values"
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def is_finite_number(x: Any) -> bool:
    """True for an int or a finite float; False for bools, NaN, +/-Infinity and non-numbers."""
    if isinstance(x, bool) or not isinstance(x, (int, float)):
        return False
    return isinstance(x, int) or math.isfinite(x)


def _is_nonfinite_float(x: Any) -> bool:
    return isinstance(x, float) and not math.isfinite(x)


def _child_path(path: str, key: Any) -> str:
    """``$.a`` for identifier-like keys, ``$["a b"]`` for any other key."""
    text = str(key)
    if _IDENTIFIER_RE.match(text):
        return f"{path}.{text}"
    return f"{path}[{json.dumps(text, ensure_ascii=False)}]"


def _walk(obj: Any, path: str, active: Set[int], found: List[str]) -> None:
    if _is_nonfinite_float(obj):
        found.append(path)
        return
    if not isinstance(obj, (dict, list, tuple)) or id(obj) in active:
        return  # a leaf, or a container already on the current path (a cycle)
    active.add(id(obj))
    try:
        if isinstance(obj, dict):
            for key, value in obj.items():
                _walk(value, _child_path(path, key), active, found)
        else:
            for index, value in enumerate(obj):
                _walk(value, f"{path}[{index}]", active, found)
    finally:
        active.discard(id(obj))


def find_nonfinite(obj: Any, path: str = "$") -> List[str]:
    """JSON paths of every NaN / +/-Infinity float in nested dicts, lists and tuples.

    ``find_nonfinite({'a': [1, float('nan')], 'b': {'c': float('inf')}})`` is
    ``['$.a[1]', '$.b.c']`` (document order).  A container that contains itself
    is visited once per path, so a cyclic structure never recurses forever.
    """
    found: List[str] = []
    _walk(obj, path, set(), found)
    return found


class NonFiniteJSONError(ValueError):
    """A value holds NaN / +/-Infinity where standard JSON is required.

    ``paths`` lists every offending JSON path (the message names the first ten).
    A ``ValueError`` subclass, so callers that caught json.dumps' ValueError keep working.
    """

    def __init__(self, paths: List[str], *, artifact: Optional[str] = None) -> None:
        self.paths = list(paths)
        self.artifact = artifact
        shown = ", ".join(self.paths[:_MESSAGE_PATHS]) or "a dict key or a default() result"
        extra = len(self.paths) - _MESSAGE_PATHS
        if extra > 0:
            shown += f" (+{extra} more)"
        where = f" in {artifact}" if artifact else ""
        super().__init__(f"non-finite number (NaN/Infinity) is not valid JSON{where}: {shown}")


def raise_nonfinite(obj: Any, exc: ValueError, *, artifact: Optional[str] = None) -> NoReturn:
    """Re-raise json.dumps' ``allow_nan=False`` ValueError as :class:`NonFiniteJSONError`.

    Any other ValueError (a circular reference) is re-raised unchanged.
    """
    paths = find_nonfinite(obj)
    if paths or _ENCODER_NONFINITE_TEXT in str(exc).lower():
        raise NonFiniteJSONError(paths, artifact=artifact) from exc
    raise exc


def dumps_strict(obj: Any, **kw: Any) -> str:
    """``json.dumps(obj, allow_nan=False, **kw)``; a non-finite float raises NonFiniteJSONError.

    For finite input the text equals ``json.dumps(obj, **kw)`` byte for byte.
    """
    try:
        return json.dumps(obj, allow_nan=False, **kw)
    except ValueError as exc:
        raise_nonfinite(obj, exc)


def _nulled(obj: Any, path: str, active: Set[int], found: List[str]) -> Any:
    if _is_nonfinite_float(obj):
        found.append(path)
        return None
    if not isinstance(obj, (dict, list, tuple)) or id(obj) in active:
        return obj
    active.add(id(obj))
    try:
        if isinstance(obj, dict):
            return {key: _nulled(value, _child_path(path, key), active, found)
                    for key, value in obj.items()}
        items = [_nulled(value, f"{path}[{index}]", active, found)
                 for index, value in enumerate(obj)]
        return tuple(items) if isinstance(obj, tuple) else items
    finally:
        active.discard(id(obj))


def null_nonfinite(obj: Any) -> Tuple[Any, List[str]]:
    """(copy, paths): a copy of the dict/list/tuple skeleton with every non-finite float
    replaced by ``None``, and the JSON paths replaced (as :func:`find_nonfinite` names them).

    The input is never mutated; leaves other than non-finite floats are shared, not copied.
    """
    found: List[str] = []
    copy = _nulled(obj, "$", set(), found)
    return copy, found


def reject_nonfinite_constant(name: str) -> NoReturn:
    """``json.loads(parse_constant=...)`` hook: NaN, Infinity and -Infinity are invalid JSON."""
    raise json.JSONDecodeError(NONFINITE_CONSTANT_MSG, "", 0)


def parse_finite_float(text: str) -> float:
    """``json.loads(parse_float=...)`` hook: a float literal that overflows (``1e999``) is invalid.

    A finite literal decodes to exactly the value ``float(text)`` json gives by default.
    """
    value = float(text)
    if not math.isfinite(value):
        raise json.JSONDecodeError(NONFINITE_CONSTANT_MSG, "", 0)
    return value
