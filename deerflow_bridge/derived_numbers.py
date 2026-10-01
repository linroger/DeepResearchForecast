"""Declarative derived figures for v3 research findings (RESEARCH-8).

With RESEARCH_DERIVED_FINDINGS on, a research agent that states a figure it
calculated (a growth rate, a ratio, a share) ends the finding with the
calculation instead of presenting the figure as reported::

    … grew about 185% [S12] (DERIVED: (a-b)/b*100; a=37 GW [S12], b=13 GW [S12])

The engine (``linear_research.postprocess_notes``) checks every operand on the
cited fetched page and recomputes the formula with this module; no model call
and no agent tool is involved.  This module is the pure, stdlib-only part:

* :func:`parse_derivation` reads a clause (also the Chinese form
  ``（推算：…）``) into its formula and named operands; ``years(Y1,Y2)`` is a
  whole-year period, the only operand that cites no source (the engine
  still looks for both years on the derivation's page);
* :func:`evaluate` computes a formula over Decimal operands with a hardened
  AST whitelist: only the literals 0, 1, 100 and 1000 (every other number must
  be a named operand, so it can be checked on its page), names of the operand
  set, ``+ - * / **``, unary minus and the calls abs, min, max, sqrt, ln, exp
  and log10, in an explicit Decimal context that traps overflow, invalid
  operations and division by zero; size, depth, exponent and result bounds
  keep it fast on any input, and every intermediate value must be finite
  (``exp(ln(0))`` fails rather than yielding 0);
* :func:`token_matches` tells whether a number a finding states is the result
  at its own display precision (one reading: the result as it is, or a ratio
  as a percentage; :func:`scales_to_percent` tells whether a formula yields
  a percentage already, :func:`is_additive` whether it only adds and
  subtracts, so percentages give percentage points, and :func:`keeps_unit`
  whether its result is in the unit of its data operands);
  :func:`format_exact` writes a result with 12 significant digits and no
  exponent notation.

Every failure is a :class:`CalcError`.  Idea credit: FinanceHarness's
AST-whitelisted calculator (no licence); only the whitelist idea is used, the
evaluator, the literal policy and the clause grammar are DRF's own and no
FinanceHarness code is copied.
"""

from __future__ import annotations

import ast
import keyword
import re
import unicodedata
from decimal import (ROUND_HALF_EVEN, Context, Decimal, DecimalException, DivisionByZero, InvalidOperation,
                     Overflow, localcontext)
from typing import Callable, Collection, Mapping

__all__ = [
    "CLAUSE_OPEN_RE",
    "KIND_DATA",
    "KIND_PERIOD",
    "CalcError",
    "evaluate",
    "format_exact",
    "is_additive",
    "keeps_unit",
    "parse_derivation",
    "period_value",
    "period_years",
    "scales_to_percent",
    "token_matches",
]

MAX_EXPR_CHARS = 300
MAX_NODES = 60          # every node ast.walk yields (operators and contexts included)
MAX_DEPTH = 20
MAX_EXPONENT = 100      # |y| of x ** y, checked before the power is computed
RESULT_LIMIT = Decimal("1e15")
MAX_OPERANDS = 8
ALLOWED_LITERALS = frozenset({0, 1, 100, 1000})
FORMAT_DIGITS = 12
KIND_DATA = "data"      # a value read from a source page
KIND_PERIOD = "period"  # years(Y1,Y2): a whole-year difference that cites no source
FIRST_YEAR, LAST_YEAR = 1900, 2100

# A derivation clause opener: "(DERIVED:" as the prompt writes it (upper case
# only, so prose such as "(derived: from licensing)" is no clause) or the
# Chinese "（推算：" (either bracket and colon width).  linear_research finds
# the LAST one in a finding.
CLAUSE_OPEN_RE = re.compile(r"[(（]\s?(?:DERIVED|推算)\s?[:：]")
_OPERAND_NAME = r"[a-z][a-z0-9_]{0,15}"
# Where an operand starts: the start of the operand list or a separator ("、"
# too), then "name=".  A value runs up to the next start, so a value may hold
# commas ("1,234 GW", "years(2019,2024)") but never a separator followed by
# "name=".
_OPERAND_START_RE = re.compile(rf"(?:^|[,;、])\s*({_OPERAND_NAME})\s*=")
_MARKER_RE = re.compile(r"\[S(\d{1,9})\]")
_YEARS_RE = re.compile(r"years\(\s*(\d{4})\s*,\s*(\d{4})\s*\)")
# Typographic operators a formula may be written with.
_OPERATOR_SPELLINGS = str.maketrans({"×": "*", "÷": "/", "−": "-", "–": "-"})


class CalcError(Exception):
    """A derivation that cannot be read or computed."""


def _context() -> Context:
    return Context(prec=28, Emax=999, Emin=-999, traps=[Overflow, InvalidOperation, DivisionByZero])


def _min_max(pick: Callable[..., Decimal]) -> Callable[..., Decimal]:
    def call(*args: Decimal) -> Decimal:
        if len(args) < 2:
            raise CalcError(f"{pick.__name__} needs at least two arguments")
        return pick(args)
    return call


def _one(apply: Callable[[Decimal], Decimal], name: str) -> Callable[..., Decimal]:
    def call(*args: Decimal) -> Decimal:
        if len(args) != 1:
            raise CalcError(f"{name} takes exactly one argument")
        return apply(args[0])
    return call


# Decimal methods and operators use the active (local) context.
_FUNCTIONS: Mapping[str, Callable[..., Decimal]] = {
    "abs": _one(abs, "abs"),
    "min": _min_max(min),
    "max": _min_max(max),
    "sqrt": _one(lambda x: x.sqrt(), "sqrt"),
    "ln": _one(lambda x: x.ln(), "ln"),
    "exp": _one(lambda x: x.exp(), "exp"),
    "log10": _one(lambda x: x.log10(), "log10"),
}
_BINARY: Mapping[type, Callable[[Decimal, Decimal], Decimal]] = {
    ast.Add: lambda x, y: x + y,
    ast.Sub: lambda x, y: x - y,
    ast.Mult: lambda x, y: x * y,
    ast.Div: lambda x, y: x / y,
    ast.Pow: lambda x, y: x ** y,
}


def evaluate(expr: str, operands: Mapping[str, Decimal]) -> Decimal:
    """The value of formula ``expr`` over ``operands`` (name → finite Decimal).

    Raises :class:`CalcError` for anything outside the whitelist (see the
    module docstring), a literal other than 0, 1, 100 or 1000 (the message
    names it), an unknown name, an exponent above MAX_EXPONENT in magnitude, a
    step that is not finite, a final magnitude of RESULT_LIMIT or more, and
    any other failure."""
    try:
        return _evaluate(expr, operands)
    except CalcError:
        raise
    except DecimalException as exc:
        raise CalcError(f"arithmetic error ({type(exc).__name__})") from exc
    except Exception as exc:  # noqa: BLE001 — every failure of a derivation is a CalcError
        raise CalcError(f"{type(exc).__name__}: {exc}") from exc


def _evaluate(expr: str, operands: Mapping[str, Decimal]) -> Decimal:
    if not isinstance(expr, str) or not expr.strip():
        raise CalcError("empty formula")
    if len(expr) > MAX_EXPR_CHARS:
        raise CalcError(f"formula longer than {MAX_EXPR_CHARS} characters")
    for name, value in operands.items():
        if not isinstance(value, Decimal) or not value.is_finite():
            raise CalcError(f"operand {name} is not a finite Decimal")
    tree = ast.parse(expr.strip(), mode="eval")
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise CalcError(f"formula has more than {MAX_NODES} syntax nodes")
    if _depth(tree) > MAX_DEPTH:
        raise CalcError(f"formula nests deeper than {MAX_DEPTH} levels")
    with localcontext(_context()):
        result = _node(tree.body, operands)
        if abs(result) >= RESULT_LIMIT:
            raise CalcError("result magnitude is 1e15 or more")
    return result


def _depth(node: ast.AST) -> int:
    """Nesting depth of a tree already bounded by MAX_NODES."""
    return 1 + max((_depth(child) for child in ast.iter_child_nodes(node)), default=0)


def _node(node: ast.AST, operands: Mapping[str, Decimal]) -> Decimal:
    """One whitelisted node's value; every value must be finite."""
    if isinstance(node, ast.Constant):
        value = node.value
        if type(value) is bool or type(value) not in (int, float) or value not in ALLOWED_LITERALS:
            raise CalcError(f"literal {value!r} is not allowed: write it as a named operand "
                            "(only 0, 1, 100 and 1000 may appear as numbers)")
        result = Decimal(int(value))
    elif isinstance(node, ast.Name):
        if node.id not in operands:
            raise CalcError(f"unknown name {node.id!r}: not an operand")
        result = operands[node.id]
    elif isinstance(node, ast.BinOp):
        apply = _BINARY.get(type(node.op))
        if apply is None:
            raise CalcError(f"operator {type(node.op).__name__} is not allowed")
        left = _node(node.left, operands)
        right = _node(node.right, operands)
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_EXPONENT:
            raise CalcError(f"exponent {right} is larger than {MAX_EXPONENT} in magnitude")
        result = apply(left, right)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, ast.USub):
            raise CalcError(f"operator {type(node.op).__name__} is not allowed")
        result = -_node(node.operand, operands)
    elif isinstance(node, ast.Call):
        function = _FUNCTIONS.get(node.func.id) if isinstance(node.func, ast.Name) else None
        if function is None:
            raise CalcError("only abs, min, max, sqrt, ln, exp and log10 may be called")
        if node.keywords:
            raise CalcError("keyword arguments are not allowed")
        result = function(*(_node(arg, operands) for arg in node.args))
    else:
        raise CalcError(f"{type(node).__name__} is not allowed")
    if not result.is_finite():
        raise CalcError("a step of the formula is not finite")
    return result


def period_years(raw: str) -> tuple[int, int]:
    """``years(Y1,Y2)`` → ``(Y1, Y2)``, whole years (1900 <= Y1 < Y2 <= 2100)."""
    match = _YEARS_RE.fullmatch(" ".join(str(raw or "").split()))
    if match is None:
        raise CalcError(f"period {raw!r} is not years(Y1,Y2)")
    first, last = int(match.group(1)), int(match.group(2))
    if not FIRST_YEAR <= first < last <= LAST_YEAR:
        raise CalcError(f"period {raw!r} needs {FIRST_YEAR} <= Y1 < Y2 <= {LAST_YEAR}")
    return first, last


def period_value(raw: str) -> Decimal:
    """``years(Y1,Y2)`` → Y2 - Y1 (:func:`period_years`)."""
    first, last = period_years(raw)
    return Decimal(last - first)


def parse_derivation(clause: str) -> tuple[str, list[tuple[str, str, int | None, str]]]:
    """``(formula, [(name, value, sid, kind)])`` of a derivation clause.

    ``clause`` is ``(DERIVED: <formula>; a=<value> [S<n>], b=…)`` (or
    ``（推算：…；…）``, or the same without its opener and closing bracket).
    NFKC first (full-width brackets, colons, separators and digits); the
    formula is the text before the first ``;`` without code backticks, with
    ×, ÷, − and – read as operators and ``^`` as ``**``.  Each operand is
    ``name=value``: the name matches ``[a-z][a-z0-9_]{0,15}`` (no keyword, no
    function name, no repeat; at most MAX_OPERANDS), the value is its text
    without its [S<n>] marker; ``sid`` is that marker (None without one);
    ``kind`` is KIND_PERIOD for ``years(Y1,Y2)`` (sid None), else KIND_DATA.
    Raises CalcError for anything else (no formula, no operand, text before
    the first operand, an empty value, a value citing two sources, a bad
    period)."""
    text = unicodedata.normalize("NFKC", str(clause or "")).strip()
    opener = CLAUSE_OPEN_RE.match(text)
    if opener is not None:
        text = text[opener.end():].rstrip()
        if text.endswith(")") and text.count(")") > text.count("("):
            text = text[:-1]
    formula, separator, rest = text.partition(";")
    expr = " ".join(formula.translate(_OPERATOR_SPELLINGS).replace("^", "**").replace("`", "").split())
    if not expr:
        raise CalcError("no formula")
    if not separator or not rest.strip():
        raise CalcError("no operands")
    starts = list(_OPERAND_START_RE.finditer(rest))
    if not starts or rest[:starts[0].start()].strip(" ,;、"):
        raise CalcError("the operands must be written as name=value")
    if len(starts) > MAX_OPERANDS:
        raise CalcError(f"more than {MAX_OPERANDS} operands")
    operands: list[tuple[str, str, int | None, str]] = []
    for index, start in enumerate(starts):
        name = start.group(1)
        if keyword.iskeyword(name) or name in _FUNCTIONS:
            raise CalcError(f"{name!r} cannot name an operand")
        if any(name == seen for seen, _, _, _ in operands):
            raise CalcError(f"operand {name} is defined twice")
        end = starts[index + 1].start() if index + 1 < len(starts) else len(rest)
        body = rest[start.end():end]
        sids = list(dict.fromkeys(int(sid) for sid in _MARKER_RE.findall(body)))
        value = " ".join(_MARKER_RE.sub(" ", body).split()).strip(" ,;、")
        if not value:
            raise CalcError(f"operand {name} has no value")
        if len(sids) > 1:
            raise CalcError(f"operand {name} cites more than one source")
        if _YEARS_RE.fullmatch(value):
            period_value(value)
            operands.append((name, value, None, KIND_PERIOD))
        else:
            operands.append((name, value, sids[0] if sids else None, KIND_DATA))
    return expr, operands


def _decimals(token: str) -> int:
    return len(token.partition(".")[2])


def token_matches(stated_token: str, result: Decimal, percent: bool = False) -> bool:
    """Whether a stated number token (unsigned, as a finding writes it:
    "185", "184.6") is ``result`` at the token's display precision:
    |t - r| <= 0.5 x 10^-decimals(t).  The result keeps its sign, and an
    unsigned token states only a non-negative one: a decline is written in
    its own direction ("(b-a)/b*100" for "fell 12%"), never certified from
    "(a-b)/b*100".  One reading per call: with ``percent`` the result is a
    ratio the token states as a percentage and the token is compared with
    result x 100 only ((a-b)/b = 1.846 is "185%", never "1.8%"); without it,
    with the result as it is.  Never raises: anything unreadable is no
    match."""
    token = str(stated_token).strip()
    try:
        with localcontext(Context(prec=28)):
            stated = Decimal(token)
            if not stated.is_finite() or stated < 0 or not isinstance(result, Decimal) or not result.is_finite():
                return False
            reading = result * 100 if percent else result
            if reading < 0:
                return False
            return abs(stated - reading) <= Decimal(5).scaleb(-_decimals(token) - 1)
    except (ArithmeticError, ValueError):
        return False


def scales_to_percent(expr: str) -> bool:
    """Whether formula ``expr`` multiplies by the literal 100 ("(a-b)/b*100",
    "100*a/b"): its result is a percentage already, never a ratio to read
    x 100.  Never raises: an unreadable formula does not."""
    if not isinstance(expr, str) or len(expr) > MAX_EXPR_CHARS:
        return False
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    return any(isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult)
               and any(_is_hundred(side) for side in (node.left, node.right)) for node in ast.walk(tree))


# Calls that keep their arguments' unit: abs, min and max of percentages are percentages.
_UNIT_KEEPING_CALLS = frozenset({"abs", "min", "max"})
# The other nodes an additive formula may hold (ast.walk yields operators and contexts too).
_ADDITIVE_NODES = (ast.Expression, ast.Name, ast.Constant, ast.Load, ast.Add, ast.Sub, ast.USub)


def is_additive(expr: str) -> bool:
    """Whether formula ``expr`` only adds and subtracts its terms ("a-b",
    "100-a", "abs(a-b)", "max(a,b)-c"): names and literals combined by
    ``+``, ``-`` and unary minus, and no call but abs, min and max, which
    keep their arguments' unit.  Over percentages such a formula gives
    percentage points; a product, quotient or power gives a ratio or a
    product.  Never raises: an unreadable formula is not additive."""
    if not isinstance(expr, str) or len(expr) > MAX_EXPR_CHARS:
        return False
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp):
            additive = isinstance(node.op, (ast.Add, ast.Sub))
        elif isinstance(node, ast.UnaryOp):
            additive = isinstance(node.op, ast.USub)
        elif isinstance(node, ast.Call):
            additive = (isinstance(node.func, ast.Name) and node.func.id in _UNIT_KEEPING_CALLS
                        and not node.keywords)
        else:
            additive = isinstance(node, _ADDITIVE_NODES)
        if not additive:
            return False
    return True


# The two dimensions keeps_unit tells apart: a bare literal and a value in the data operands' unit.
_LITERAL, _UNIT = "literal", "unit"


def keeps_unit(expr: str, data_names: Collection[str]) -> bool:
    """Whether formula ``expr`` gives a result in the unit of its data
    operands (``data_names``): sums and differences of data operands and
    literals (as :func:`is_additive` reads them: "a-b", "max(a,b)-c"), times
    or divided by literals ("a*1000": 2.5 GW is 2,500 MW; "(a-b)/1000").  A
    ratio, product or power of operands ("a/b", "a*b"), a literal divided by
    one, any other call, a name that is no data operand (a ``years()``
    period: "(a-b)/n" is a rate per year) and a formula of literals only keep
    no unit.  Never raises: an unreadable formula keeps no unit."""
    if not isinstance(expr, str) or len(expr) > MAX_EXPR_CHARS:
        return False
    try:
        tree = ast.parse(expr.strip(), mode="eval")
        return _dimension(tree.body, frozenset(data_names)) == _UNIT
    except (SyntaxError, ValueError, TypeError, RecursionError, MemoryError):
        return False


def _dimension(node: ast.AST, data_names: frozenset[str]) -> str | None:
    """_LITERAL, _UNIT or None (no unit-keeping reading) of one formula node."""
    if isinstance(node, ast.Constant):
        return _LITERAL if type(node.value) in (int, float) else None
    if isinstance(node, ast.Name):
        return _UNIT if node.id in data_names else None
    if isinstance(node, ast.UnaryOp):
        return _dimension(node.operand, data_names) if isinstance(node.op, ast.USub) else None
    if isinstance(node, ast.Call):
        if (not isinstance(node.func, ast.Name) or node.func.id not in _UNIT_KEEPING_CALLS or node.keywords
                or not node.args):
            return None
        parts = {_dimension(arg, data_names) for arg in node.args}
        return None if None in parts else (_UNIT if _UNIT in parts else _LITERAL)
    if not isinstance(node, ast.BinOp):
        return None
    left, right = _dimension(node.left, data_names), _dimension(node.right, data_names)
    if left is None or right is None:
        return None
    if isinstance(node.op, (ast.Add, ast.Sub)):
        return _UNIT if _UNIT in (left, right) else _LITERAL
    if isinstance(node.op, ast.Mult):
        return None if left == right == _UNIT else (_UNIT if _UNIT in (left, right) else _LITERAL)
    if isinstance(node.op, ast.Div):
        return left if right == _LITERAL else None
    return None


def _is_hundred(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and type(node.value) in (int, float) and node.value == 100


def format_exact(value: Decimal) -> str:
    """``value`` with FORMAT_DIGITS significant digits, no exponent notation
    and no trailing zeros ("184.615384615", "1200000000000", "0")."""
    if not isinstance(value, Decimal) or not value.is_finite():
        raise CalcError("only a finite Decimal can be formatted")
    with localcontext(Context(prec=FORMAT_DIGITS, rounding=ROUND_HALF_EVEN)):
        rounded = (+value).normalize()
    return "0" if rounded.is_zero() else format(rounded, "f")
