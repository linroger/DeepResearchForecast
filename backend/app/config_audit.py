"""INFRA-14: strict audit of the environment knobs that ``app.config`` reads.

``Config`` parses most boolean knobs with ``.strip().lower() == 'true'``, so ``1``,
``yes`` and ``on`` silently mean false; a blank or malformed value in an unguarded
``int(...)``/``float(...)`` parse crashed the backend at import; an unknown enum
value or an out-of-range threshold fell back or misbehaved without a word.  This
module is the single parser of config.py's knobs and the audit over an environment:

* ``extract_knobs`` walks config.py's AST (no import, no regex): every literal
  ``os.environ`` read in the module, typed from its ``Config`` assignment as
  bool / int / float / str with its literal default.  ``scripts/check_env_drift.py``
  and ``tests/_hermetic.py`` read the same table.
* ``sanitize_numeric_env`` runs in config.py before ``class Config``: a blank,
  unparseable or non-finite value of an int/float knob is popped from the
  environment, so the code default applies and the import never crashes, and is
  reported as an error.
* ``audit_env`` reports non-canonical booleans, enum / range / coupled-pair
  violations, a malformed ``LLM_COST_PER_MTOK`` and grandfathered ghost knobs
  set in the environment.

``Config.config_issues()`` combines both.  Errors refuse pipeline admission
(``preflight_pipeline`` and ``PipelineOrchestrator.start``) while
``CONFIG_STRICT_VALIDATION`` is on; the server itself always starts and prints
them as warnings.  Stdlib only, with no ``app`` import: config.py imports this
module before ``Config`` exists (``app.utils`` would be circular), and
check_env_drift / the test harness load it by path without the app package.
"""

from __future__ import annotations

import ast
import json
import math
import os
from collections import namedtuple
from typing import Any, Mapping, MutableMapping, Optional

CONFIG_SOURCE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")

ERROR = "error"
WARNING = "warning"

# level: 'error' (refuses admission under CONFIG_STRICT_VALIDATION) or 'warning';
# knob: the env name; message: names the knob and says what to write instead.
Issue = namedtuple("Issue", "level knob message")

# The closed boolean vocabulary: a token outside it is never a boolean.
TRUE_TOKENS = ("true", "1", "yes", "on")
FALSE_TOKENS = ("false", "0", "no", "off")
_BOOL_VOCABULARY = frozenset(TRUE_TOKENS + FALSE_TOKENS)
# str methods that keep a value's identity for classification (x.strip().lower()).
_STR_METHODS = frozenset({"strip", "lstrip", "rstrip", "lower", "upper", "casefold"})


class ConfigurationError(RuntimeError):
    """Strict config validation refused a pipeline run; ``errors`` lists the reasons."""

    def __init__(self, errors):
        self.errors = [str(error) for error in errors]
        super().__init__(
            "configuration errors refuse this run (CONFIG_STRICT_VALIDATION=true; set it to "
            "false to downgrade them to warnings): " + "; ".join(self.errors))


# low / high: bounds (None = unbounded); *_inclusive: whether the bound itself is allowed.
Range = namedtuple("Range", "low low_inclusive high high_inclusive")
_UNIT_INTERVAL = Range(0.0, True, 1.0, True)
_NON_NEGATIVE = Range(0.0, True, None, False)

RANGE_RULES: dict[str, Range] = {
    "REPORT_PUBLISH_GATE_MIN_COVERAGE": _UNIT_INTERVAL,
    # 0 disables the floor: derive_forecast_spine applies it only when it is > 0.
    "FORECAST_PROB_FLOOR": Range(0.0, True, 0.5, False),
    "RESEARCH_QUALITY_FLOOR": _UNIT_INTERVAL,
    "GRAPH_PRUNE_MIN_CORE_COVERAGE": _UNIT_INTERVAL,
    "GRAPH_RESOLVE_SIM_THRESHOLD": _UNIT_INTERVAL,
    "GRAPH_MAX_SKIPPED_RATIO": _UNIT_INTERVAL,
    "FORECAST_ENSEMBLE_SPREAD_THRESHOLD": _UNIT_INTERVAL,
    "FORECAST_MARKET_DIVERGENCE_MIN_CONFIDENCE": _UNIT_INTERVAL,
    "SIM_DECISION_INERTIA": _UNIT_INTERVAL,
    "ENSEMBLE_EXTREMIZE_A": Range(0.0, False, None, False),
    "REPORT_MAX_CITATIONS_PER_SOURCE": Range(1, True, None, False),
    # Every LLM_RUN_BUDGET_* knob (0 = no budget).
    "LLM_RUN_BUDGET_TOKENS": _NON_NEGATIVE,
    "LLM_RUN_BUDGET_USD": _NON_NEGATIVE,
}

# Accepted values (compared after .strip().lower(), as Config reads them).
ENUM_RULES: dict[str, tuple[str, ...]] = {
    "SIMULATION_FORECAST_EFFECT": ("diagnostic_only", "no_update", "validated_update", "legacy_prompt"),
    "SIM_TEMPORAL_MODE": ("calendar", "hours"),
    "GRAPH_CHUNK_SOURCE": ("both", "dossier_only", "report_only"),
}

# (lower, upper): the effective lower value must not exceed the effective upper value.
COUPLED_RULES: tuple[tuple[str, str], ...] = (
    ("SIM_CALENDAR_TARGET_MAX_ROUNDS", "SIM_CALENDAR_HARD_MAX_ROUNDS"),
    ("REPORT_AGENT_MIN_TOOL_CALLS", "REPORT_AGENT_MAX_TOOL_CALLS"),
)

# JSON {provider: [input, output]} $/Mtok table (telemetry._cost_overrides skips a
# malformed table or entry without a word, so the audit names it instead).
COST_TABLE_KNOB = "LLM_COST_PER_MTOK"

# Names read only with getattr(Config, NAME, default) that Config does not declare
# (and no process reads from the environment), so an .env value never reaches the
# reader.  Each stays code-only for the reason given; the audit warns when one is set
# in the environment.  test_config_audit scans the backend for such reads and fails
# on any name missing here, so a new ghost is declared as a knob instead.
GRANDFATHERED_GHOST_KNOBS: dict[str, str] = {
    "CAL_MIN_RESOLVED": "calibration policy constant; changes only through the Foglamp promotion gate",
    "PERSONA_EGO_MAX_NEIGHBORS": "internal persona-context tuning constant",
    "PREDICTION_MARKETS_REQUOTE_CHUNK": "internal market re-quote batch size",
    "PROFILE_ZEP_SEARCH_MAX_RETRIES": "internal graph-search retry constant",
    "PROFILE_ZEP_SEARCH_RETRY_DELAY_SECONDS": "internal graph-search retry constant",
    "REPORT_MIN_ACTOR_COVERAGE": "internal retrieval coverage constant",
    "REPORT_PDF_CJK_FONT": "PDF font override read only through Config attributes",
    "REPORT_PDF_MAIN_FONT": "PDF font override read only through Config attributes",
    "REPORT_PDF_MONO_FONT": "PDF font override read only through Config attributes",
    "REPORT_PREMORTEM": "forecast policy switch; changes only through the Foglamp promotion gate",
    "REPORT_PURITY_MAX_SEGMENTS": "internal language-purity repair bound",
    "REPORT_PURITY_TRANSLATION_BATCH_SIZE": "internal language-purity repair batch size",
    "REPORT_REQUIRE_ANCHOR": "forecast policy switch; changes only through the Foglamp promotion gate",
    "REPORT_REQUIRE_SHARP_CRITERIA": "forecast policy switch; changes only through the Foglamp promotion gate",
    "REPORT_RESURRECT_FAILED_SECTIONS": "internal report-recovery switch",
    "REPORT_RETRIEVAL_CACHE": "internal retrieval switch",
    "REPORT_RETRIEVAL_PARALLEL": "internal retrieval switch",
    "REPORT_RETRIEVAL_PARALLEL_WORKERS": "internal retrieval fan-out",
    "REPORT_SPINE_INPUT_CAP_BRIEF": "forecast-spine prompt budget constant",
    "REPORT_SPINE_INPUT_CAP_FACTS": "forecast-spine prompt budget constant",
    "REPORT_SPINE_INPUT_CAP_INPUTS": "forecast-spine prompt budget constant",
    "REPORT_SPINE_INPUT_CAP_SIGNAL": "forecast-spine prompt budget constant",
    "REPORT_SPINE_MAX_TOKENS": "forecast-spine completion budget constant",
    "REPORT_TRANSLATION_CONTAMINATION_RETRIES": "internal translation repair bound",
    "REPORT_VIZ_PLOTLYJS_INLINE": "report-visualizer override read only through Config attributes",
    "SCHEDULER_DEFAULT_MAX_RUNS": "scheduled_rerun reads its knobs with getattr defaults by design",
    "SIM_AUDIENCE_ACTIVE_CAP": "legacy attribute-injection hook of the simulation config generator",
    "SIM_RUNSTATE_SAVE_INTERVAL": "internal run-state write throttle",
}


# ---------------------------------------------------------------------------
# config.py source -> knob table
# ---------------------------------------------------------------------------

def _is_str(node: Optional[ast.AST]) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, str)


def _is_os_environ(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _env_read(node: ast.AST) -> Optional[tuple[str, Optional[str]]]:
    """``(name, literal default or None)`` when ``node`` reads one literal env name.

    Recognised: ``os.environ.get('X'[, default])``, ``os.getenv('X'[, default])``
    and ``os.environ['X']`` (a load).  A non-literal name is not a knob.
    """
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
        func = node.func
        is_get = func.attr == "get" and _is_os_environ(func.value)
        is_getenv = (func.attr == "getenv" and isinstance(func.value, ast.Name)
                     and func.value.id == "os")
        if (is_get or is_getenv) and _is_str(node.args[0]):
            default = node.args[1] if len(node.args) > 1 else None
            return node.args[0].value, (default.value if _is_str(default) else None)
        return None
    if (isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load)
            and _is_os_environ(node.value) and _is_str(node.slice)):
        return node.slice.value, None
    return None


def _env_chain(node: ast.AST) -> Optional[tuple[str, Optional[str]]]:
    """``(env name, blank fallback)`` for an env read wrapped in str methods and
    ``or '<literal>'`` fallbacks (``(os.environ.get('X', '').strip().lower() or 'true')``)."""
    blank = None
    while True:
        if (isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or)
                and len(node.values) == 2 and _is_str(node.values[1])):
            if blank is None:
                blank = node.values[1].value
            node = node.values[0]
        elif (isinstance(node, ast.Call) and not node.args and not node.keywords
              and isinstance(node.func, ast.Attribute) and node.func.attr in _STR_METHODS):
            node = node.func.value
        else:
            break
    read = _env_read(node)
    return (read[0], blank) if read else None


def _bool_spec(node: ast.Compare) -> Optional[tuple[str, dict[str, Any]]]:
    """The knob a boolean comparison parses and how, else None.

    ``form`` 'in': the value is true iff its token is in ``tokens``
    (``== 'true'`` is 'in' ('true',)); 'not_in': true iff it is not.  ``blank``
    is the ``or '<literal>'`` token a blank value is read as.
    """
    if len(node.ops) != 1:
        return None
    chain = _env_chain(node.left)
    if chain is None:
        return None
    op, right = node.ops[0], node.comparators[0]
    if isinstance(op, (ast.Eq, ast.NotEq)) and _is_str(right):
        tokens = (right.value.lower(),)
        form = "in" if isinstance(op, ast.Eq) else "not_in"
    elif (isinstance(op, (ast.In, ast.NotIn)) and isinstance(right, (ast.Tuple, ast.List, ast.Set))
          and right.elts and all(_is_str(elt) for elt in right.elts)):
        tokens = tuple(elt.value.lower() for elt in right.elts)
        form = "in" if isinstance(op, ast.In) else "not_in"
    else:
        return None
    if not set(tokens) <= _BOOL_VOCABULARY:
        return None                     # an enum membership test, not a boolean
    name, blank = chain
    return name, {"kind": "bool", "form": form, "tokens": tokens, "blank": blank}


def _classify(node: ast.AST, out: dict[str, dict[str, Any]]) -> None:
    """Type every env read inside a Config assignment's value expression."""
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in ("int", "float") and len(node.args) == 1):
        for sub in ast.walk(node.args[0]):
            read = _env_read(sub)
            if read is not None:
                out.setdefault(read[0], {"kind": node.func.id})
        return
    if isinstance(node, ast.Compare):
        spec = _bool_spec(node)
        if spec is not None:
            out.setdefault(spec[0], spec[1])
            return
    for child in ast.iter_child_nodes(node):
        _classify(child, out)


def _class_assignments(body: list[ast.stmt]):
    """Single-name assignments of a class body, including those nested in if/try
    blocks (never inside a method)."""
    for stmt in body:
        if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
            yield stmt.targets[0].id, stmt.value
        elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and isinstance(stmt.target, ast.Name):
            yield stmt.target.id, stmt.value
        elif isinstance(stmt, ast.If):
            yield from _class_assignments(stmt.body)
            yield from _class_assignments(stmt.orelse)
        elif isinstance(stmt, ast.Try):
            yield from _class_assignments(stmt.body)
            for handler in stmt.handlers:
                yield from _class_assignments(handler.body)
            yield from _class_assignments(stmt.orelse)
            yield from _class_assignments(stmt.finalbody)


def extract_knobs(config_source_path: str = CONFIG_SOURCE_PATH, *,
                  source: Optional[str] = None) -> dict[str, dict[str, Any]]:
    """Env name -> knob for every literal env read in config.py (``source`` overrides the file).

    A knob is ``{kind, default, line, attr}``: ``kind`` is 'bool' / 'int' / 'float'
    from its ``Config`` assignment, else 'str' (module-level reads such as
    DRF_TEST_PROCESS are 'str' with ``attr`` None); ``default`` is the first
    literal default among the name's reads (None when there is none); ``line`` is
    the first read; ``attr`` the Config attribute it feeds.  A bool also carries
    ``form`` / ``tokens`` / ``blank`` (see ``_bool_spec``).  Insertion order is
    source order.  Raises OSError / SyntaxError on an unreadable source.
    """
    if source is None:
        with open(config_source_path, encoding="utf-8") as fh:
            source = fh.read()
    tree = ast.parse(source)
    reads = []
    for node in ast.walk(tree):
        read = _env_read(node)
        if read is not None:
            reads.append((node.lineno, node.col_offset, read))
    knobs: dict[str, dict[str, Any]] = {}
    for line, _col, (name, default) in sorted(reads, key=lambda item: (item[0], item[1])):
        knob = knobs.get(name)
        if knob is None:
            knobs[name] = {"kind": "str", "default": default, "line": line, "attr": None}
        elif knob["default"] is None and default is not None:
            knob["default"] = default
    config_class = next((node for node in tree.body
                         if isinstance(node, ast.ClassDef) and node.name == "Config"), None)
    if config_class is not None:
        for attr, value in _class_assignments(config_class.body):
            typed: dict[str, dict[str, Any]] = {}
            _classify(value, typed)
            for sub in ast.walk(value):
                read = _env_read(sub)
                if read is not None and knobs[read[0]]["attr"] is None:
                    knobs[read[0]]["attr"] = attr
            for name, spec in typed.items():
                if knobs[name]["kind"] == "str":
                    knobs[name].update(spec)
    return knobs


# ---------------------------------------------------------------------------
# Environment audit
# ---------------------------------------------------------------------------

def _shown(raw: str) -> str:
    """A value as quoted in a message (bounded; knob values here are never secrets)."""
    text = str(raw)
    return text if len(text) <= 60 else text[:57] + "..."


def _default_text(knob: Mapping[str, Any]) -> str:
    default = knob.get("default")
    return "the code default" if default is None else f"the default {default!r}"


def _bool_reads(knob: Mapping[str, Any], raw: str) -> bool:
    """How Config reads ``raw`` for this boolean knob."""
    token = raw.strip().lower() or (knob.get("blank") or "")
    tokens = knob.get("tokens") or ("true",)
    return token in tokens if knob.get("form", "in") == "in" else token not in tokens


def _bool_issue(name: str, knob: Mapping[str, Any], raw: str) -> Optional[Issue]:
    token = raw.strip().lower()
    read_word = "true" if _bool_reads(knob, raw) else "false"
    if not token:
        default = knob.get("default")
        if default is not None and not default.strip():
            return None                 # blank is this knob's own default
        default_value = _bool_reads(knob, default or "")
        if _bool_reads(knob, raw) != default_value:
            return Issue(ERROR, name, (
                f"{name} is blank, which is read as {read_word} instead of its default "
                f"{'true' if default_value else 'false'}; write canonical true/false or remove the line"))
        return Issue(WARNING, name, (
            f"{name} is blank; its default ({read_word}) applies. Write canonical true/false "
            "or remove the line"))
    if token in _BOOL_VOCABULARY:
        if _bool_reads(knob, raw) != (token in TRUE_TOKENS):
            return Issue(ERROR, name, f"{name}={_shown(raw)} is read as {read_word}; write canonical true/false")
        return None
    return Issue(ERROR, name, (
        f"{name}={_shown(raw)} is not a boolean (read as {read_word}); write canonical true/false"))


def _parse_number(kind: str, raw: str) -> float:
    """Parse like Config does (``int()`` / ``float()``); raises ValueError."""
    text = raw.strip()
    if not text:
        raise ValueError("blank")
    value = int(text) if kind == "int" else float(text)
    if not math.isfinite(value):
        raise ValueError("not finite")
    return value


def _numeric_problem(name: str, knob: Mapping[str, Any], raw: str) -> Optional[str]:
    """Why ``raw`` cannot be this int/float knob's value, else None."""
    try:
        _parse_number(knob["kind"], raw)
    except (ValueError, OverflowError):
        applies = f"it is ignored and {_default_text(knob)} applies"
        if not raw.strip():
            return f"{name} is blank; {applies}. Write a number or remove the line"
        expected = "an integer" if knob["kind"] == "int" else "a finite number"
        return f"{name}={_shown(raw)} is not {expected}; {applies}"
    return None


def _describe(rule: Range) -> str:
    if rule.low is not None and rule.high is not None:
        return (f"{'[' if rule.low_inclusive else '('}{rule.low:g}, "
                f"{rule.high:g}{']' if rule.high_inclusive else ')'}")
    if rule.low is not None:
        return f"{'>=' if rule.low_inclusive else '>'} {rule.low:g}"
    return f"{'<=' if rule.high_inclusive else '<'} {rule.high:g}"


def _in_range(value: float, rule: Range) -> bool:
    if rule.low is not None and (value < rule.low or (value == rule.low and not rule.low_inclusive)):
        return False
    if rule.high is not None and (value > rule.high or (value == rule.high and not rule.high_inclusive)):
        return False
    return True


def _numeric_issue(name: str, knob: Mapping[str, Any], raw: str) -> Optional[Issue]:
    problem = _numeric_problem(name, knob, raw)
    if problem is not None:
        return Issue(ERROR, name, problem)
    rule = RANGE_RULES.get(name)
    if rule is not None and not _in_range(_parse_number(knob["kind"], raw), rule):
        return Issue(ERROR, name, f"{name}={_shown(raw)} is outside its valid range {_describe(rule)}")
    return None


def _enum_issue(name: str, raw: str) -> Optional[Issue]:
    choices = ENUM_RULES[name]
    if raw.strip().lower() in choices:
        return None
    return Issue(ERROR, name, f"{name}={_shown(raw)} is not one of {', '.join(choices)}")


def _cost_table_issue(raw: str) -> Optional[Issue]:
    """LLM_COST_PER_MTOK: blank, or a JSON object of [input, output] non-negative prices."""
    text = raw.strip()
    if not text:
        return None
    name = COST_TABLE_KNOB
    try:
        table = json.loads(text)
    except ValueError as exc:
        return Issue(ERROR, name, f"{name} is not valid JSON ({exc}); write e.g. "
                                  '{"openai": [5.0, 15.0]} ($/Mtok input, output)')
    if not isinstance(table, dict):
        return Issue(ERROR, name, f"{name} must be a JSON object of provider: [input, output] $/Mtok prices")
    for provider, pair in table.items():
        valid = (isinstance(pair, list) and len(pair) == 2
                 and all(isinstance(price, (int, float)) and not isinstance(price, bool)
                         and math.isfinite(price) and price >= 0 for price in pair))
        if not valid:
            return Issue(ERROR, name, (
                f"{name} entry {provider!r} must be [input, output] non-negative $/Mtok prices, "
                f"got {_shown(json.dumps(pair))}"))
    return None


def _effective_number(name: str, knobs: Mapping[str, Mapping[str, Any]],
                      environ: Mapping[str, str]) -> Optional[float]:
    """The value Config ends up with: a parseable env value, else the literal default."""
    knob = knobs.get(name)
    if knob is None or knob.get("kind") not in ("int", "float"):
        return None
    for raw in (environ.get(name), knob.get("default")):
        if raw is None:
            continue
        try:
            return _parse_number(knob["kind"], raw)
        except (ValueError, OverflowError):
            continue
    return None


def _coupled_issues(environ: Mapping[str, str], knobs: Mapping[str, Mapping[str, Any]]) -> list[Issue]:
    issues = []
    for lower_name, upper_name in COUPLED_RULES:
        if lower_name not in environ and upper_name not in environ:
            continue
        lower = _effective_number(lower_name, knobs, environ)
        upper = _effective_number(upper_name, knobs, environ)
        if lower is not None and upper is not None and lower > upper:
            issues.append(Issue(ERROR, lower_name, (
                f"{lower_name}={lower:g} exceeds {upper_name}={upper:g}; it must be <= {upper_name}")))
    return issues


def audit_env(environ: Mapping[str, str], knobs: Mapping[str, Mapping[str, Any]]) -> list[Issue]:
    """Issues of the knob values set in ``environ`` (a knob left unset is never an issue).

    Booleans: a canonical-vocabulary token Config reads against its meaning
    (``X=1`` is read as false) or a token outside the vocabulary is an error; a
    blank value is an error when it flips the default, else a warning.  Numbers:
    blank / unparseable / non-finite, or outside RANGE_RULES, is an error.
    ENUM_RULES, COUPLED_RULES and the LLM_COST_PER_MTOK shape are errors; a
    grandfathered ghost knob set in the environment is a warning.
    """
    issues: list[Issue] = []
    for name, knob in knobs.items():
        raw = environ.get(name)
        if raw is None:
            continue
        kind = knob.get("kind")
        issue = None
        if kind == "bool":
            issue = _bool_issue(name, knob, raw)
        elif kind in ("int", "float"):
            issue = _numeric_issue(name, knob, raw)
        elif name in ENUM_RULES:
            issue = _enum_issue(name, raw)
        elif name == COST_TABLE_KNOB:
            issue = _cost_table_issue(raw)
        if issue is not None:
            issues.append(issue)
    issues.extend(_coupled_issues(environ, knobs))
    for name, reason in GRANDFATHERED_GHOST_KNOBS.items():
        if name in environ:
            issues.append(Issue(WARNING, name, (
                f"{name} is read via getattr default; not a declared knob, so the environment "
                f"cannot set it ({reason})")))
    return issues


def sanitize_numeric_env(environ: MutableMapping[str, str],
                         knobs: Mapping[str, Mapping[str, Any]]) -> list[Issue]:
    """Pop every blank, unparseable or non-finite int/float knob value from ``environ``.

    config.py calls this before ``class Config`` so ``int(os.environ.get(...))``
    sees the default instead of raising at import; each popped value is an error.
    """
    issues: list[Issue] = []
    for name, knob in knobs.items():
        if knob.get("kind") not in ("int", "float"):
            continue
        raw = environ.get(name)
        if raw is None:
            continue
        problem = _numeric_problem(name, knob, raw)
        if problem is not None:
            environ.pop(name, None)
            issues.append(Issue(ERROR, name, problem))
    return issues


# ---------------------------------------------------------------------------
# Run options (API payloads, schedule records)
# ---------------------------------------------------------------------------

def parse_int_option(value: Any, name: str) -> int:
    """A run option that must be an integer: an int, an integral finite float or an int string.

    A bool (``int(True) == 1``), a non-integral float (``int(3.5) == 3``) or any
    other value raises ValueError naming ``name``.
    """
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not a boolean")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if math.isfinite(value) and value.is_integer():
            return int(value)
        raise ValueError(f"{name} must be an integer, got {value!r}")
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            raise ValueError(f"{name} must be an integer, got {value!r}") from None
    raise ValueError(f"{name} must be an integer, got {type(value).__name__}")
