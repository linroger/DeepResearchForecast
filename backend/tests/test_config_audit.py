"""INFRA-14: config audit (strict bool / numeric / enum / range validation, ghost
knob promotion) and run-option validation.

app/config_audit.py parses config.py's knobs with an AST walk and audits an
environment: a non-canonical boolean (``X=1`` is read as false), a blank or
malformed number (popped at import, so the default applies and the import never
crashes), an enum / range / coupled-pair violation or a malformed
LLM_COST_PER_MTOK is an error that refuses pipeline admission while
CONFIG_STRICT_VALIDATION is on; the server itself still starts.  The run API
rejects a bool or non-integral max_rounds, resume checks the pinned research
model, and scheduled reruns validate depth / model / language.

Offline: pure functions, a Flask test client with a no-op background run, a
child interpreter for the import-time checks and per-test data dirs.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask

import app.config as config_module
from app import config_audit as ca
from app.api import research as research_api
from app.api import research_bp, sdk_bp
from app.api import sdk as sdk_api
from app.config import Config
from app.services import pipeline_orchestrator as po

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND / "scripts"))

import check_env_drift as ed  # noqa: E402
import scheduled_rerun as sr  # noqa: E402

KNOBS = config_module.CONFIG_KNOBS
QUESTION = "Will the ECB cut its deposit rate below 3% by the end of 2024?"


def _only(issues):
    assert len(issues) == 1, issues
    return issues[0]


@pytest.fixture
def clean_env(monkeypatch):
    """No knob, ghost knob or import-time issue: the audit sees a default configuration."""
    # Config knobs only: DRF_TEST_PROCESS (a module-level read) keeps the test-process marker.
    for name in (*(n for n, knob in KNOBS.items() if knob["attr"]), *ca.GRANDFATHERED_GHOST_KNOBS):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config_module, "CONFIG_IMPORT_ISSUES", [])
    monkeypatch.setattr(Config, "CONFIG_STRICT_VALIDATION", True)


# ───────────────────────────── extract_knobs ─────────────────────────────
def test_extract_knobs_types_representative_config_knobs():
    assert KNOBS["REPORT_NATIVE_TOOLS"] == {
        "kind": "bool", "default": "true", "line": KNOBS["REPORT_NATIVE_TOOLS"]["line"],
        "attr": "REPORT_NATIVE_TOOLS", "form": "in", "tokens": ("true",), "blank": None}
    assert (KNOBS["GRAPH_MAX_ENTITIES"]["kind"], KNOBS["GRAPH_MAX_ENTITIES"]["default"]) == ("int", "400")
    assert (KNOBS["FORECAST_PROB_FLOOR"]["kind"], KNOBS["FORECAST_PROB_FLOOR"]["default"]) == ("float", "0.03")
    # max(1, int(os.environ.get(...) or ...)) and a parse inside a class-body try block.
    assert (KNOBS["N_FORECAST_SEEDS"]["kind"], KNOBS["N_FORECAST_SEEDS"]["default"]) == ("int", "1")
    assert KNOBS["GRAPH_CHOKEPOINT_MAX_NODES"]["kind"] == "int"
    # A nested fallback read is typed too; the outer read has no literal default.
    assert KNOBS["SIM_AUDIENCE_SIZE"]["kind"] == "int" and KNOBS["SIM_AUDIENCE_AGENTS"]["default"] is None
    assert KNOBS["SIM_AUDIENCE_SIZE"]["attr"] == "SIM_AUDIENCE_AGENTS"
    # The env name, not the attribute, keys the table.
    assert KNOBS["FLASK_DEBUG"]["attr"] == "DEBUG" and KNOBS["FLASK_DEBUG"]["kind"] == "bool"
    # Fail-closed and bridge-compatible boolean forms.
    assert (KNOBS["APP_HOST_CHECK"]["form"], KNOBS["APP_HOST_CHECK"]["tokens"]) == (
        "not_in", ("false", "0", "no", "off"))
    assert (KNOBS["RESEARCH_FORECAST_INPUTS"]["form"], KNOBS["RESEARCH_FORECAST_INPUTS"]["blank"]) == ("in", "true")
    # An enum membership test is not a boolean; module-level reads are str knobs.
    assert KNOBS["SIMULATION_FORECAST_EFFECT"]["kind"] == "str"
    assert KNOBS["DRF_TEST_PROCESS"] == {"kind": "str", "default": None,
                                         "line": KNOBS["DRF_TEST_PROCESS"]["line"], "attr": None}
    assert list(KNOBS).index("SECRET_KEY") < list(KNOBS).index("SIMULATION_FORECAST_EFFECT")


def test_extract_knobs_reads_source_text_and_ignores_comments():
    source = "\n".join([
        "import os",
        "FLAG = os.environ.get('MODULE_FLAG')",
        "class Config:",
        "    A = os.environ.get('A_BOOL', 'True').strip().lower() == 'true'",
        "    B = max(1, int(os.environ.get('B_INT', '3') or '3'))",
        "    C = float(os.environ.get('C_FLOAT', '0.5'))",
        "    D = os.environ.get('D_GUARD', 'true').strip().lower() not in ('0', 'false', 'no', 'off')",
        "    E = (os.environ.get('E_TRUTHY', '').strip().lower() or 'true') in ('1', 'true', 'yes', 'on')",
        "    F = os.environ['F_STR']",
        "    G = os.environ.get('G_ENUM', 'x').strip().lower() in ('x', 'y')",
        "    # os.environ.get('COMMENT_ONLY', 'ignored')",
        "    def method(self):",
        "        return int(os.environ.get('IN_METHOD', '1'))",
    ])
    knobs = ca.extract_knobs(source=source)
    assert {name: knob["kind"] for name, knob in knobs.items()} == {
        "MODULE_FLAG": "str", "A_BOOL": "bool", "B_INT": "int", "C_FLOAT": "float", "D_GUARD": "bool",
        "E_TRUTHY": "bool", "F_STR": "str", "G_ENUM": "str", "IN_METHOD": "str"}
    assert knobs["A_BOOL"]["default"] == "True" and knobs["B_INT"]["default"] == "3"
    assert knobs["E_TRUTHY"]["default"] == "" and knobs["E_TRUTHY"]["blank"] == "true"
    assert knobs["IN_METHOD"]["attr"] is None and knobs["B_INT"]["line"] == 5


def test_check_env_drift_reads_config_through_extract_knobs(tmp_path):
    """check_env_drift parses Config with config_audit.extract_knobs (INFRA-14)."""
    assert ed.config_knobs() == KNOBS
    assert ed.config_defaults()["LLM_HTTP_TIMEOUT_S"] == "600"
    assert {"CONFIG_STRICT_VALIDATION", "LLM_HTTP_TIMEOUT_S", "RESEARCH_EVIDENCE_GRADING",
            "DRF_TEST_PROCESS"} <= ed.config_env_vars()


def test_check_env_drift_strict_passes_on_the_repo(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["check_env_drift.py", "--strict"])
    assert ed.main() == 0
    assert "every Config env var is documented in .env.example" in capsys.readouterr().out


# ───────────────────────────── audit_env: booleans ─────────────────────────
def test_non_canonical_true_token_is_an_error_naming_the_fix():
    issue = _only(ca.audit_env({"REPORT_NATIVE_TOOLS": "1"}, KNOBS))
    assert issue == ca.Issue("error", "REPORT_NATIVE_TOOLS",
                             "REPORT_NATIVE_TOOLS=1 is read as false; write canonical true/false")
    for token in ("yes", "on", "YES"):
        assert _only(ca.audit_env({"REPORT_NATIVE_TOOLS": token}, KNOBS)).level == "error"


@pytest.mark.parametrize("value", ["true", " TRUE ", "false", "0", "no", "off", "OFF"])
def test_canonical_and_false_tokens_are_accepted(value):
    assert ca.audit_env({"REPORT_NATIVE_TOOLS": value}, KNOBS) == []


def test_unknown_boolean_token_is_an_error():
    issue = _only(ca.audit_env({"REPORT_NATIVE_TOOLS": "maybe"}, KNOBS))
    assert issue.level == "error"
    assert issue.message == ("REPORT_NATIVE_TOOLS=maybe is not a boolean (read as false); "
                             "write canonical true/false")


def test_blank_boolean_is_an_error_only_when_it_flips_the_default():
    flips = _only(ca.audit_env({"REPORT_NATIVE_TOOLS": ""}, KNOBS))          # default true
    assert flips.level == "error" and "read as false instead of its default true" in flips.message
    keeps = _only(ca.audit_env({"RESEARCH_QUESTION_SPEC": "  "}, KNOBS))     # default false
    assert keeps.level == "warning" and "its default (false) applies" in keeps.message
    # Blank is this knob's own default (blank = true in the bridge-compatible form).
    assert ca.audit_env({"RESEARCH_FORECAST_INPUTS": ""}, KNOBS) == []


def test_fail_closed_and_truthy_forms_accept_every_token_they_read_as_meant():
    for value in ("1", "yes", "on", "true", "0", "off"):
        assert ca.audit_env({"APP_HOST_CHECK": value, "RESEARCH_FORECAST_INPUTS": value,
                             "CONFIG_STRICT_VALIDATION": value}, KNOBS) == []
    issue = _only(ca.audit_env({"APP_HOST_CHECK": "ture"}, KNOBS))
    assert issue.level == "error" and "read as true" in issue.message
    assert _only(ca.audit_env({"CONFIG_STRICT_VALIDATION": ""}, KNOBS)).level == "warning"


# ───────────────────────────── numbers ─────────────────────────────
@pytest.mark.parametrize("value, fragment", [
    ("", "GRAPH_MAX_ENTITIES is blank; it is ignored and the default '400' applies"),
    ("   ", "GRAPH_MAX_ENTITIES is blank"),
    ("abc", "GRAPH_MAX_ENTITIES=abc is not an integer; it is ignored and the default '400' applies"),
    ("nan", "GRAPH_MAX_ENTITIES=nan is not an integer"),
    ("5.0", "GRAPH_MAX_ENTITIES=5.0 is not an integer"),
])
def test_sanitize_numeric_env_pops_malformed_int_with_a_named_error(value, fragment):
    environ = {"GRAPH_MAX_ENTITIES": value, "REPORT_NATIVE_TOOLS": "1", "UNRELATED": "x"}
    issue = _only(ca.sanitize_numeric_env(environ, KNOBS))
    assert issue.level == "error" and issue.knob == "GRAPH_MAX_ENTITIES" and fragment in issue.message
    # Only the malformed number is popped; booleans are audit_env's job.
    assert environ == {"REPORT_NATIVE_TOOLS": "1", "UNRELATED": "x"}


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "1e999", "x"])
def test_sanitize_numeric_env_pops_non_finite_float(value):
    environ = {"GRAPH_PRUNE_MIN_CORE_COVERAGE": value}
    issue = _only(ca.sanitize_numeric_env(environ, KNOBS))
    assert "is not a finite number" in issue.message and environ == {}


def test_sanitize_numeric_env_keeps_valid_numbers():
    environ = {"GRAPH_MAX_ENTITIES": " 250 ", "GRAPH_PRUNE_MIN_CORE_COVERAGE": "0.5", "LLM_HTTP_TIMEOUT_S": "90"}
    assert ca.sanitize_numeric_env(environ, KNOBS) == []
    assert environ == {"GRAPH_MAX_ENTITIES": " 250 ", "GRAPH_PRUNE_MIN_CORE_COVERAGE": "0.5",
                       "LLM_HTTP_TIMEOUT_S": "90"}


_CONFIG_IMPORT_CHILD = r"""
import importlib, json, os, sys
import dotenv
dotenv.load_dotenv = lambda *a, **k: False  # the repo .env must not decide
import app.config as config_module
out = []
for env in json.loads(sys.argv[1]):
    for name, value in env.items():
        os.environ[name] = value
    config = importlib.reload(config_module).Config
    out.append({"GRAPH_MAX_ENTITIES": config.GRAPH_MAX_ENTITIES,
                "GRAPH_PRUNE_MIN_CORE_COVERAGE": config.GRAPH_PRUNE_MIN_CORE_COVERAGE,
                "REPORT_AGENT_MAX_TOOL_CALLS": config.REPORT_AGENT_MAX_TOOL_CALLS,
                "left_in_environ": sorted(n for n in env if n in os.environ),
                "import_issues": [list(i) for i in config_module.CONFIG_IMPORT_ISSUES],
                "errors": config.config_errors()})
    for name in env:
        os.environ.pop(name, None)
print("<<<JSON>>>" + json.dumps(out))
"""


def test_malformed_numeric_env_never_crashes_the_config_import():
    """Before INFRA-14 each of these raised ValueError while importing app.config."""
    cases = [{"GRAPH_MAX_ENTITIES": "abc"},
             {"GRAPH_MAX_ENTITIES": "", "GRAPH_PRUNE_MIN_CORE_COVERAGE": "nan",
              "REPORT_AGENT_MAX_TOOL_CALLS": "twelve"},
             {"GRAPH_MAX_ENTITIES": "250"}]
    proc = subprocess.run([sys.executable, "-c", _CONFIG_IMPORT_CHILD, json.dumps(cases)],
                          cwd=str(BACKEND), capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("<<<JSON>>>")][-1]
    abc, blank, valid = json.loads(line[len("<<<JSON>>>"):])
    assert (abc["GRAPH_MAX_ENTITIES"], abc["left_in_environ"]) == (400, [])
    assert abc["import_issues"] == [["error", "GRAPH_MAX_ENTITIES",
                                     "GRAPH_MAX_ENTITIES=abc is not an integer; it is ignored and "
                                     "the default '400' applies"]]
    assert abc["errors"] == [abc["import_issues"][0][2]]
    assert (blank["GRAPH_MAX_ENTITIES"], blank["GRAPH_PRUNE_MIN_CORE_COVERAGE"],
            blank["REPORT_AGENT_MAX_TOOL_CALLS"]) == (400, 0.8, 12)
    assert sorted(issue[1] for issue in blank["import_issues"]) == [
        "GRAPH_MAX_ENTITIES", "GRAPH_PRUNE_MIN_CORE_COVERAGE", "REPORT_AGENT_MAX_TOOL_CALLS"]
    assert (valid["GRAPH_MAX_ENTITIES"], valid["import_issues"], valid["errors"]) == (250, [], [])


# ───────────────────────────── range / enum / coupled / cost table ───────────
@pytest.mark.parametrize("name, value, ok", [
    ("FORECAST_PROB_FLOOR", "0.7", False),
    ("FORECAST_PROB_FLOOR", "0.5", False),     # [0, 0.5): 0.5 itself is out
    ("FORECAST_PROB_FLOOR", "0", True),        # 0 disables the floor
    ("REPORT_PUBLISH_GATE_MIN_COVERAGE", "1.2", False),
    ("REPORT_PUBLISH_GATE_MIN_COVERAGE", "1", True),
    ("SIM_DECISION_INERTIA", "-0.1", False),
    ("ENSEMBLE_EXTREMIZE_A", "0", False),
    ("ENSEMBLE_EXTREMIZE_A", "2.5", True),
    ("REPORT_MAX_CITATIONS_PER_SOURCE", "0", False),
    ("LLM_RUN_BUDGET_USD", "-1", False),
    ("LLM_RUN_BUDGET_TOKENS", "0", True),
])
def test_range_rules(name, value, ok):
    issues = ca.audit_env({name: value}, KNOBS)
    if ok:
        assert issues == []
    else:
        issue = _only(issues)
        assert issue.level == "error" and issue.message.startswith(f"{name}={value} is outside its valid range")


def test_range_message_names_the_interval():
    assert _only(ca.audit_env({"FORECAST_PROB_FLOOR": "0.7"}, KNOBS)).message == (
        "FORECAST_PROB_FLOOR=0.7 is outside its valid range [0, 0.5)")


def test_enum_rules():
    assert _only(ca.audit_env({"SIM_TEMPORAL_MODE": "weeks"}, KNOBS)).message == (
        "SIM_TEMPORAL_MODE=weeks is not one of calendar, hours")
    assert _only(ca.audit_env({"SIMULATION_FORECAST_EFFECT": "update"}, KNOBS)).level == "error"
    assert _only(ca.audit_env({"GRAPH_CHUNK_SOURCE": ""}, KNOBS)).level == "error"
    assert ca.audit_env({"SIM_TEMPORAL_MODE": " Hours ", "GRAPH_CHUNK_SOURCE": "both",
                         "SIMULATION_FORECAST_EFFECT": "no_update"}, KNOBS) == []


def test_coupled_rules_use_the_effective_values():
    issue = _only(ca.audit_env({"SIM_CALENDAR_TARGET_MAX_ROUNDS": "50",
                                "SIM_CALENDAR_HARD_MAX_ROUNDS": "40"}, KNOBS))
    assert issue.level == "error" and issue.message == (
        "SIM_CALENDAR_TARGET_MAX_ROUNDS=50 exceeds SIM_CALENDAR_HARD_MAX_ROUNDS=40; "
        "it must be <= SIM_CALENDAR_HARD_MAX_ROUNDS")
    # One side set: the other keeps its default (hard cap 48, max tool calls 12).
    assert _only(ca.audit_env({"SIM_CALENDAR_TARGET_MAX_ROUNDS": "50"}, KNOBS)).knob == (
        "SIM_CALENDAR_TARGET_MAX_ROUNDS")
    assert _only(ca.audit_env({"REPORT_AGENT_MIN_TOOL_CALLS": "20"}, KNOBS)).level == "error"
    assert ca.audit_env({"SIM_CALENDAR_TARGET_MAX_ROUNDS": "40"}, KNOBS) == []
    # A malformed side is reported once (as a number), and the pair uses its default.
    assert [i.knob for i in ca.audit_env({"SIM_CALENDAR_HARD_MAX_ROUNDS": "x"}, KNOBS)] == [
        "SIM_CALENDAR_HARD_MAX_ROUNDS"]


@pytest.mark.parametrize("value, ok", [
    ("", True),
    ('{"openai": [5.0, 15.0], "myprov": [0, 1]}', True),
    ("{bad", False),
    ("[1, 2]", False),
    ('{"openai": [-1, 2]}', False),
    ('{"openai": [1]}', False),
    ('{"openai": ["5", "15"]}', False),
    ('{"openai": [true, 1]}', False),
    ('{"openai": [NaN, 1]}', False),
])
def test_cost_table_must_be_an_object_of_non_negative_price_pairs(value, ok):
    issues = ca.audit_env({"LLM_COST_PER_MTOK": value}, KNOBS)
    if ok:
        assert issues == []
    else:
        issue = _only(issues)
        assert issue.level == "error" and issue.knob == "LLM_COST_PER_MTOK"
        assert issue.message.startswith("LLM_COST_PER_MTOK")


def test_rules_name_real_knobs_whose_defaults_pass():
    for name, rule in ca.RANGE_RULES.items():
        assert KNOBS[name]["kind"] in ("int", "float"), name
        assert ca._in_range(float(KNOBS[name]["default"]), rule), name
    budget_knobs = {name for name in KNOBS if name.startswith("LLM_RUN_BUDGET_")}
    assert budget_knobs and budget_knobs <= set(ca.RANGE_RULES)
    for name, choices in ca.ENUM_RULES.items():
        assert KNOBS[name]["kind"] == "str" and KNOBS[name]["default"] in choices, name
    for lower, upper in ca.COUPLED_RULES:
        assert KNOBS[lower]["kind"] == KNOBS[upper]["kind"] == "int"
        assert int(KNOBS[lower]["default"]) <= int(KNOBS[upper]["default"])
    # Every knob set to its own literal default audits clean.
    defaults = {name: knob["default"] for name, knob in KNOBS.items() if knob["default"] is not None}
    assert ca.audit_env(defaults, KNOBS) == []
    assert ca.audit_env({}, KNOBS) == []


# ───────────────────────────── ghost knobs ─────────────────────────────
def test_grandfathered_ghost_set_in_env_is_a_warning():
    issue = _only(ca.audit_env({"REPORT_PREMORTEM": "true"}, KNOBS))
    assert issue.level == "warning"
    assert issue.message.startswith("REPORT_PREMORTEM is read via getattr default; not a declared knob")
    # A getattr read of a name some process also reads from the environment is not a
    # ghost: SIM_AUDIENCE_SIZE (config.py's fallback of SIM_AUDIENCE_AGENTS) and
    # REPORT_META_CHARTS (report_visualizer falls back to the env) take effect.
    assert ca.audit_env({"SIM_AUDIENCE_SIZE": "3", "REPORT_META_CHARTS": "true"}, KNOBS) == []


def test_promoted_knobs_are_declared_documented_and_not_grandfathered():
    assert Config.LLM_HTTP_TIMEOUT_S == 600.0 and isinstance(Config.LLM_HTTP_TIMEOUT_S, float)
    assert Config.RESEARCH_EVIDENCE_GRADING is True and Config.RESEARCH_FORECAST_INPUTS is True
    assert Config.CONFIG_STRICT_VALIDATION is True
    assert (KNOBS["LLM_HTTP_TIMEOUT_S"]["kind"], KNOBS["RESEARCH_EVIDENCE_GRADING"]["kind"]) == ("float", "bool")
    documented = ed.documented_env_vars()
    for name in ("CONFIG_STRICT_VALIDATION", "LLM_HTTP_TIMEOUT_S", "RESEARCH_EVIDENCE_GRADING",
                 "RESEARCH_FORECAST_INPUTS"):
        assert name in documented, name
        assert name not in ca.GRANDFATHERED_GHOST_KNOBS, name
    for name in ca.GRANDFATHERED_GHOST_KNOBS:
        assert not hasattr(Config, name), f"{name} is declared now: drop it from GRANDFATHERED_GHOST_KNOBS"


def _is_config_getattr(node):
    return (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr"
            and len(node.args) >= 2 and isinstance(node.args[0], ast.Name) and node.args[0].id == "Config")


def _is_os_environ(node):
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _reads_env_by(node, param):
    """os.environ.get(param) / os.getenv(param) / os.environ[param]."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.args:
        func, arg = node.func, node.args[0]
        reader = ((func.attr == "get" and _is_os_environ(func.value))
                  or (func.attr == "getenv" and isinstance(func.value, ast.Name) and func.value.id == "os"))
        return reader and isinstance(arg, ast.Name) and arg.id == param
    return (isinstance(node, ast.Subscript) and _is_os_environ(node.value)
            and isinstance(node.slice, ast.Name) and node.slice.id == param)


def _config_only_helpers(tree):
    """Functions that read getattr(Config, <first param>) and never the env first."""
    helpers = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or not fn.args.args:
            continue
        param = fn.args.args[0].arg
        nodes = list(ast.walk(fn))
        reads_config = any(_is_config_getattr(n) and isinstance(n.args[1], ast.Name) and n.args[1].id == param
                           for n in nodes)
        if reads_config and not any(_reads_env_by(n, param) for n in nodes):
            helpers.add(fn.name)
    return helpers


def _python_files(*roots):
    for root in roots:
        yield from (path for path in sorted(root.rglob("*.py")) if ".venv" not in path.parts)


def _config_getattr_names():
    """Every NAME read as getattr(Config, 'NAME', ...) or through a Config-only helper."""
    names = set()
    for path in [BACKEND / "run.py", *_python_files(BACKEND / "app", BACKEND / "scripts")]:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        helpers = _config_only_helpers(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            arg = None
            if _is_config_getattr(node):
                arg = node.args[1]
            elif isinstance(node.func, ast.Name) and node.func.id in helpers and node.args:
                arg = node.args[0]
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch(r"[A-Z][A-Z0-9_]+", arg.value):
                names.add(arg.value)
    return names


def _env_read_names():
    """Every literal env name read by the backend or a child process it spawns."""
    names = set()
    roots = (BACKEND / "app", BACKEND / "scripts", REPO_ROOT / "deerflow_bridge", REPO_ROOT / "drf2")
    for path in _python_files(*roots):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            read = ca._env_read(node)
            if read is not None:
                names.add(read[0])
    return names


def test_every_ghost_knob_is_grandfathered():
    """A name read with a getattr default that Config does not declare, and that no
    process reads from the environment, never sees .env: declare it as a knob (and
    document it), or grandfather it with a reason."""
    ghosts = {name for name in _config_getattr_names() if not hasattr(Config, name)} - _env_read_names()
    assert ghosts == set(ca.GRANDFATHERED_GHOST_KNOBS)
    assert all(reason.strip() for reason in ca.GRANDFATHERED_GHOST_KNOBS.values())


# ───────────────────────────── Config / preflight / start ───────────────────
def test_default_configuration_has_no_issue_and_validate_is_unchanged(clean_env, monkeypatch):
    """CONFIG_STRICT_VALIDATION defaults on; with a clean environment it changes nothing."""
    assert config_module.CONFIG_IMPORT_ISSUES == [] and Config.config_issues() == []
    assert Config.config_errors() == []
    assert Config.validate() == Config.validate(include_audit=False)
    strict = po.preflight_pipeline(mode="research_only")
    monkeypatch.setattr(Config, "CONFIG_STRICT_VALIDATION", False)
    assert po.preflight_pipeline(mode="research_only") == strict


def test_validate_includes_audit_errors_unless_strict_is_off(clean_env, monkeypatch):
    message = "REPORT_NATIVE_TOOLS=1 is read as false; write canonical true/false"
    monkeypatch.setenv("REPORT_NATIVE_TOOLS", "1")
    monkeypatch.setenv("REPORT_PREMORTEM", "true")
    import_issue = ca.Issue("error", "GRAPH_MAX_ENTITIES", "GRAPH_MAX_ENTITIES=abc is not an integer")
    monkeypatch.setattr(config_module, "CONFIG_IMPORT_ISSUES", [import_issue])

    assert Config.config_errors() == [import_issue.message, message]
    assert Config.validate()[-2:] == [import_issue.message, message]
    assert message not in Config.validate(include_audit=False)
    assert [i.level for i in Config.config_issues()] == ["error", "error", "warning"]

    monkeypatch.setattr(Config, "CONFIG_STRICT_VALIDATION", False)
    issues = Config.config_issues()
    assert [(i.level, i.message) for i in issues[:2]] == [("warning", import_issue.message), ("warning", message)]
    assert Config.config_errors() == [] and message not in Config.validate()


def test_preflight_lists_enum_range_and_coupled_errors_when_strict(clean_env, monkeypatch):
    monkeypatch.setenv("SIM_TEMPORAL_MODE", "weeks")
    monkeypatch.setenv("FORECAST_PROB_FLOOR", "0.7")
    monkeypatch.setenv("REPORT_AGENT_MIN_TOOL_CALLS", "20")
    messages = ["FORECAST_PROB_FLOOR=0.7 is outside its valid range [0, 0.5)",
                "SIM_TEMPORAL_MODE=weeks is not one of calendar, hours",
                "REPORT_AGENT_MIN_TOOL_CALLS=20 exceeds REPORT_AGENT_MAX_TOOL_CALLS=12; "
                "it must be <= REPORT_AGENT_MAX_TOOL_CALLS"]
    report = po.preflight_pipeline(mode="research_only")
    assert all(message in report for message in messages)
    assert sorted(Config.config_errors()) == sorted(messages)
    monkeypatch.setattr(Config, "CONFIG_STRICT_VALIDATION", False)
    report = po.preflight_pipeline(mode="research_only")
    assert not any(message in report for message in messages)


@pytest.fixture
def run_env(monkeypatch, tmp_path, clean_env):
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path), raising=False)
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(po.PipelineOrchestrator, "_run", classmethod(lambda cls, state: None))
    monkeypatch.setattr(research_api, "preflight_pipeline", lambda **kwargs: [])
    monkeypatch.setattr(sdk_api, "preflight_pipeline", lambda **kwargs: [])
    return tmp_path


def _settle(pipeline_id):
    thread = po.PipelineOrchestrator._threads.pop(pipeline_id, None)
    if thread is not None:
        thread.join(timeout=5)
    po.PipelineOrchestrator._cancel_events.pop(pipeline_id, None)


def test_start_refuses_an_invalid_enum_before_anything_exists(run_env, monkeypatch):
    monkeypatch.setenv("SIM_TEMPORAL_MODE", "weeks")

    class _NoTasks:
        def __init__(self):
            pytest.fail("a task was created for a refused run")

    monkeypatch.setattr(po, "TaskManager", _NoTasks)
    threads_before = dict(po.PipelineOrchestrator._threads)
    with pytest.raises(po.ConfigurationError) as refused:
        po.PipelineOrchestrator.start(QUESTION, mode="full")
    assert isinstance(refused.value, RuntimeError)
    assert refused.value.errors == ["SIM_TEMPORAL_MODE=weeks is not one of calendar, hours"]
    assert "SIM_TEMPORAL_MODE=weeks" in str(refused.value)
    assert not os.path.exists(Config.PIPELINE_DATA_DIR)
    assert po.PipelineOrchestrator._threads == threads_before


def test_start_proceeds_when_strict_validation_is_off(run_env, monkeypatch):
    monkeypatch.setenv("SIM_TEMPORAL_MODE", "weeks")
    monkeypatch.setattr(Config, "CONFIG_STRICT_VALIDATION", False)
    state = po.PipelineOrchestrator.start(QUESTION, mode="full")
    _settle(state.pipeline_id)
    assert state.status == "running"


# ───────────────────────────── run API ─────────────────────────────
@pytest.fixture
def client(run_env):
    app = Flask(__name__)
    app.register_blueprint(research_bp, url_prefix="/api/research")
    app.register_blueprint(sdk_bp, url_prefix="/api/v1")
    return app.test_client()


def _post(client, route, **fields):
    return client.post(route, data=json.dumps({"prompt": QUESTION, **fields}), content_type="application/json")


@pytest.mark.parametrize("route", ["/api/research/run", "/api/v1/run"])
@pytest.mark.parametrize("max_rounds", [True, False, 3.5, "3.5", "ten", [10], float("inf")])
def test_run_rejects_a_bool_or_non_integral_max_rounds(client, monkeypatch, route, max_rounds):
    monkeypatch.setattr(po.PipelineOrchestrator, "start",
                        classmethod(lambda cls, *a, **k: pytest.fail("start() ran for a bad max_rounds")))
    payload = json.dumps({"prompt": QUESTION, "max_rounds": max_rounds}, allow_nan=True)
    response = client.post(route, data=payload, content_type="application/json")
    assert response.status_code == 400
    assert response.get_json()["error"] == "max_rounds 必须是整数"


@pytest.mark.parametrize("route", ["/api/research/run", "/api/v1/run"])
@pytest.mark.parametrize("max_rounds, expected", [(10, 10), (10.0, 10), ("12", 12), (None, None)])
def test_run_accepts_an_integral_max_rounds(client, route, max_rounds, expected):
    response = _post(client, route, max_rounds=max_rounds)
    assert response.status_code == 200, response.get_json()
    pipeline_id = response.get_json()["data"]["pipeline_id"]
    _settle(pipeline_id)
    assert po.PipelineManager.load(pipeline_id)["options"]["max_rounds"] == expected


def test_resume_preflight_checks_the_pinned_research_model(client, monkeypatch):
    seen = []

    def preflight(**kwargs):
        seen.append(kwargs)
        return ["stop here"]

    monkeypatch.setattr(research_api, "preflight_pipeline", preflight)
    states = {"pipe_pinned": {"mode": "research_only", "options": {"research_model": "minimax"}},
              "pipe_default": {"mode": "full", "options": {"research_model": None}},
              "pipe_legacy": {"mode": "full"}}
    monkeypatch.setattr(research_api.PipelineManager, "load", classmethod(lambda cls, pid: states.get(pid)))
    for pipeline_id in states:
        assert client.post(f"/api/research/{pipeline_id}/resume").status_code == 400
    assert seen == [{"mode": "research_only", "model": "minimax"},
                    {"mode": "full", "model": None},
                    {"mode": "full", "model": None}]


@pytest.mark.parametrize("value, expected", [(7, 7), (7.0, 7), (" 7 ", 7), ("-2", -2)])
def test_parse_int_option_accepts_integers(value, expected):
    assert ca.parse_int_option(value, "max_rounds") == expected


@pytest.mark.parametrize("value", [True, False, 3.5, float("nan"), "3.5", "", None, [1], {"n": 1}])
def test_parse_int_option_rejects_everything_else(value):
    with pytest.raises(ValueError, match="max_rounds must be an integer"):
        ca.parse_int_option(value, "max_rounds")


# ───────────────────────────── scheduled reruns ─────────────────────────────
@pytest.fixture
def schedules(monkeypatch, tmp_path):
    monkeypatch.setattr(sr.ScheduleStore, "SCHEDULES_DIR", str(tmp_path / "schedules"))
    return tmp_path


@pytest.mark.parametrize("kwargs, fragment", [
    ({"depth": "bogus"}, "depth must be one of quick, standard, deep"),
    ({"model": "gpt-9"}, "model must be one of"),
    ({"language": "French"}, "language must be one of Chinese, English, auto"),
    ({"options": {"max_rounds": True}}, "options.max_rounds must be an integer"),
    ({"options": {"max_rounds": 2.5}}, "options.max_rounds must be an integer"),
    ({"options": {"mode": "partial"}}, "options.mode must be one of full, research_only"),
])
def test_schedule_create_rejects_invalid_run_options(schedules, kwargs, fragment):
    with pytest.raises(ValueError, match=re.escape(fragment)):
        sr.ScheduleStore.create(QUESTION, interval_minutes=60, **kwargs)
    assert sr.ScheduleStore.list_schedules() == []


def test_schedule_create_normalises_like_the_run_api(schedules):
    record = sr.ScheduleStore.create(QUESTION, interval_minutes=60, depth=" Deep ", model="MiniMax",
                                     language="auto", options={"max_rounds": 12.0})
    assert (record["depth"], record["research_model"], record["research_language"]) == ("deep", "minimax", "")
    assert record["options"] == {"max_rounds": 12}
    default = sr.ScheduleStore.create(QUESTION, interval_minutes=60)
    assert (default["depth"], default["research_model"], default["research_language"], default["options"]) == (
        None, None, None, {})


def test_schedule_cli_add_reports_invalid_options(schedules, capsys):
    assert sr.main(["add", "--prompt", QUESTION, "--interval-minutes", "60", "--depth", "bogus"]) == 2
    assert "depth must be one of" in capsys.readouterr().err


class _RecordingOrchestrator:
    calls: list = []
    error = None

    @classmethod
    def start(cls, prompt, **kwargs):
        cls.calls.append(kwargs)
        if cls.error is not None:
            raise cls.error
        return types.SimpleNamespace(pipeline_id=f"pipe_{len(cls.calls):012d}")


@pytest.fixture
def orchestrator(monkeypatch):
    monkeypatch.setattr(_RecordingOrchestrator, "calls", [])
    monkeypatch.setattr(_RecordingOrchestrator, "error", None)
    monkeypatch.setattr(sr, "PipelineOrchestrator", _RecordingOrchestrator)
    return _RecordingOrchestrator


NOW = datetime(2026, 9, 30, 12, 0, tzinfo=timezone.utc)


def test_launch_skips_an_invalid_stored_schedule(schedules, orchestrator):
    record = sr.ScheduleStore.create(QUESTION, interval_minutes=30)
    record["depth"] = "bogus"            # written before validation existed, or edited by hand
    sr.ScheduleStore.save(record)

    assert sr.Scheduler._launch(sr.ScheduleStore.load(record["schedule_id"]), NOW) is None
    assert orchestrator.calls == []
    stored = sr.ScheduleStore.load(record["schedule_id"])
    assert stored["last_error"] == "invalid schedule: depth must be one of quick, standard, deep, got 'bogus'"
    assert stored["next_run_at"] == (NOW + timedelta(minutes=30)).isoformat()
    assert stored["run_pipeline_ids"] == []


def test_launch_starts_a_valid_schedule_with_normalised_options(schedules, orchestrator):
    record = sr.ScheduleStore.create(QUESTION, interval_minutes=30, depth="quick", model="claude",
                                     language="English", options={"max_rounds": 8})
    stored = sr.ScheduleStore.load(record["schedule_id"])
    stored["research_language"] = "auto"      # a record stored before 'auto' was normalised
    stored["last_error"] = "launch failed: earlier"
    sr.ScheduleStore.save(stored)

    pipeline_id = sr.Scheduler._launch(sr.ScheduleStore.load(record["schedule_id"]), NOW)
    assert pipeline_id == "pipe_000000000001"
    assert orchestrator.calls == [{"mode": "full", "project_name": None, "depth": "quick", "max_rounds": 8,
                                   "language": "", "model": "claude"}]
    stored = sr.ScheduleStore.load(record["schedule_id"])
    assert "last_error" not in stored and stored["run_pipeline_ids"] == [pipeline_id]


def test_launch_records_a_start_refusal(schedules, orchestrator):
    orchestrator.error = ca.ConfigurationError(["SIM_TEMPORAL_MODE=weeks is not one of calendar, hours"])
    record = sr.ScheduleStore.create(QUESTION, interval_minutes=30)
    assert sr.Scheduler._launch(record, NOW) is None
    stored = sr.ScheduleStore.load(record["schedule_id"])
    assert stored["last_error"].startswith("launch failed: configuration errors refuse this run")
    assert stored["run_pipeline_ids"] == []


# ───────────────────────────── research child forwarding ────────────────────
def test_research_child_env_forwards_evidence_grading_from_config(monkeypatch):
    assert ("RESEARCH_EVIDENCE_GRADING", "bool") in po.RESEARCH_CHILD_KNOBS
    for configured, expected in ((False, "false"), (True, "true")):
        monkeypatch.setattr(Config, "RESEARCH_EVIDENCE_GRADING", configured)
        env = {"RESEARCH_EVIDENCE_GRADING": "yes"}    # an ambient value never decides
        po._forward_research_knobs(env, po.RESEARCH_CHILD_KNOBS)
        assert env["RESEARCH_EVIDENCE_GRADING"] == expected


@pytest.mark.parametrize("raw", [None, "", "  ", "true", "1", "yes", "ON", "false", "0", "no", "off", "maybe"])
def test_config_reads_evidence_grading_like_the_legacy_bridge(monkeypatch, raw):
    """The child now receives Config's verdict, so Config reads the knob exactly as the
    bridge did from the raw env (unset or blank = true, else only 1/true/yes/on)."""
    if raw is None:
        monkeypatch.delenv("RESEARCH_EVIDENCE_GRADING", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_EVIDENCE_GRADING", raw)
    if str(REPO_ROOT / "deerflow_bridge") not in sys.path:
        sys.path.insert(0, str(REPO_ROOT / "deerflow_bridge"))
    import deerflow_research as dr

    spec = importlib.util.spec_from_file_location("_infra14_config_probe", BACKEND / "app" / "config.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)      # a fresh Config; app.config itself is untouched
    assert probe.Config.RESEARCH_EVIDENCE_GRADING is dr._env_flag("RESEARCH_EVIDENCE_GRADING", True)


# ───────────────────────────── run.py startup ─────────────────────────────
def test_run_py_prints_audit_issues_and_keeps_its_exit_gate(clean_env, monkeypatch, capsys):
    import run as backend_run

    class _Stop(Exception):
        pass

    def create_app():
        raise _Stop

    monkeypatch.setenv("REPORT_NATIVE_TOOLS", "1")
    monkeypatch.setattr(backend_run, "create_app", create_app)
    with pytest.raises(_Stop):          # validation passed: the audit error did not exit
        backend_run.main()
    out = capsys.readouterr().out
    assert "WARN config error: REPORT_NATIVE_TOOLS=1 is read as false; write canonical true/false" in out
    assert "配置错误" not in out
