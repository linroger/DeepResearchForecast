"""INFRA-13 (N04): import fences - which modules may reach an LLM SDK, an LLM factory, an HTTP
client or a data-vendor SDK.

DRF's accounting and honesty rest on every model and network call going through a metered
transport: LLMClient (usage ledger, budget, typed transport errors), the research gateway
ledger, and cached_fetch / search_tools (fetch cache, spend ceilings, circuit breakers).
Nothing stopped a new module - least of all a report-stage module, whose model calls must go
through LLMClient - from importing openai, httpx or DeerFlow's create_chat_model directly and
bypassing all of that.

This test walks the non-test source tree (SCAN_ROOTS in _import_fence_policy.py) and collects
every import that reaches a fenced capability: module-level or function-local (with the
enclosing def/class qualname), ``from a import b`` expanded to ``a.b``, a star or bare import
of a fenced parent, literal ``importlib.import_module`` / ``__import__`` targets, and the
string values of the dynamic import tables. Each hit needs an ALLOW row (file, capability,
optional scope / symbol pins, a reason and the ledger that meters the call). It also pins that
the report-stage modules (and the eval/diagnostic modules as they land) import no capability
directly, that a ``claude -p`` / ``codex exec`` argv literal appears only in llm_client.py, that
no ALLOW row is stale, and that the scanner still finds its landing baseline, so a broken
scanner cannot pass silently.

Non-goals (follow-ups): ``camel.agents`` (the sim's reaction agent reuses an oasis_llm model
backend), re-export laundering (``from app.utils.prediction_markets import httpx``), transitive
egress through an allowlisted transport (report_agent fetches and re-quotes Polymarket markets
through prediction_markets.PolymarketClient) and dynamic imports whose target is not a literal.

Offline: ast over source text, except the sim-script check, which executes the three sim
scripts' module level with oasis stubbed and camel.models / camel.types blocked.
"""

from __future__ import annotations

import ast
import importlib.util
import itertools
import logging
import os
import py_compile
import sys
import types
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import _import_fence_policy as policy

_REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Hit:
    """One imported dotted name that reaches a fenced capability."""

    path: str        # repo-relative, POSIX separators
    line: int
    target: str      # ``a.b`` for ``from a import b``, ``a.*`` for a star import, else the module
    capability: str
    scope: str       # enclosing def/class qualname, policy.MODULE_SCOPE at top level

    def describe(self) -> str:
        return f"{self.path}:{self.line}: {self.target} [{self.capability}] in {self.scope}"


@dataclass(frozen=True)
class ArgvHit:
    """A list/tuple literal holding a provider-CLI argv pair such as ``'claude', '-p'``."""

    path: str
    line: int
    argv: tuple[str, str]

    def describe(self) -> str:
        return f"{self.path}:{self.line}: argv literal {' '.join(self.argv)!r}"


@dataclass(frozen=True)
class FileScan:
    path: str
    hits: tuple[Hit, ...] = ()
    argv_hits: tuple[ArgvHit, ...] = ()
    error: str | None = None   # unreadable or unparseable: the fence cannot vouch for the file


def _under(name: str, prefix: str) -> bool:
    return name == prefix or name.startswith(prefix + ".")


def capabilities_of(target: str, *, parent_rule: bool = False) -> set[str]:
    """Capabilities a dotted import target reaches.

    A target is fenced when it is, or sits under, a capability prefix (``openai.types`` is
    under ``openai``). With ``parent_rule`` (bare ``import``, star imports, dynamic imports) a
    proper parent of a prefix is fenced too: ``import deerflow`` or ``from deerflow import *``
    reach ``deerflow.models``.
    """
    return {
        capability
        for capability, prefixes in policy.CAPABILITIES.items()
        for prefix in prefixes
        if _under(target, prefix) or (parent_rule and _under(prefix, target))
    }


def _dynamic_import_target(call: ast.Call) -> str | None:
    """The literal module name of an ``import_module(...)`` / ``__import__(...)`` call, else None.

    Matched by callee name (``importlib.import_module``, a bare ``import_module`` imported from
    importlib, ``__import__``, ``builtins.__import__``); the name is the first positional
    argument or the ``name=`` keyword.
    """
    func = call.func
    callee = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
    if callee not in ("import_module", "__import__"):
        return None
    name = call.args[0] if call.args else next(
        (keyword.value for keyword in call.keywords if keyword.arg == "name"), None)
    if isinstance(name, ast.Constant) and isinstance(name.value, str):
        return name.value
    return None


class _FenceVisitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.hits: list[Hit] = []
        self.argv_hits: list[ArgvHit] = []
        self._scope: list[str] = []

    def _record(self, line: int, target: str, capabilities: set[str]) -> None:
        scope = ".".join(self._scope) or policy.MODULE_SCOPE
        self.hits.extend(Hit(self.path, line, target, capability, scope)
                         for capability in sorted(capabilities))

    def _visit_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> None:
        """Only the body belongs to the def/class scope. Decorators, default arguments,
        annotations, type parameters and class bases/keywords belong to the enclosing scope (they
        run when the def or class statement executes), so a scope pin must not admit an import
        made there."""
        if isinstance(node, ast.ClassDef):
            header: list[ast.AST] = [*node.decorator_list, *node.bases, *node.keywords]
        else:
            header = [*node.decorator_list, node.args, *([node.returns] if node.returns else [])]
        for child in (*header, *node.type_params):
            self.visit(child)
        self._scope.append(node.name)
        for statement in node.body:
            self.visit(statement)
        self._scope.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = visit_ClassDef = _visit_scope

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(node.lineno, alias.name, capabilities_of(alias.name, parent_rule=True))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = "." * node.level + (node.module or "")
        for alias in node.names:
            if alias.name == "*":
                self._record(node.lineno, f"{module}.*", capabilities_of(module, parent_rule=True))
                continue
            target = f"{module}{alias.name}" if module.endswith(".") else f"{module}.{alias.name}"
            capabilities = capabilities_of(target)
            if alias.name in policy.FENCED_SYMBOLS:
                capabilities.add(policy.FENCED_SYMBOLS[alias.name])
            self._record(node.lineno, target, capabilities)

    def visit_Call(self, node: ast.Call) -> None:
        target = _dynamic_import_target(node)
        if target:
            self._record(node.lineno, target, capabilities_of(target, parent_rule=True))
        self.generic_visit(node)

    def _visit_import_table(self, targets: list[ast.expr], value: ast.expr | None) -> None:
        named = any(isinstance(t, ast.Name) and t.id in policy.DYNAMIC_IMPORT_TABLES
                    for t in targets)
        if named and isinstance(value, ast.Dict):
            for entry in value.values:
                if isinstance(entry, ast.Constant) and isinstance(entry.value, str):
                    self._record(entry.lineno, entry.value,
                                 capabilities_of(entry.value, parent_rule=True))

    def visit_Assign(self, node: ast.Assign) -> None:
        self._visit_import_table(node.targets, node.value)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        self._visit_import_table([node.target], node.value)
        self.generic_visit(node)

    def _visit_sequence(self, node: ast.List | ast.Tuple) -> None:
        literals = [e.value if isinstance(e, ast.Constant) and isinstance(e.value, str) else None
                    for e in node.elts]
        for pair in itertools.pairwise(literals):
            if pair in policy.CLI_ARGV_RULE["pairs"]:
                self.argv_hits.append(ArgvHit(self.path, node.lineno, pair))
        self.generic_visit(node)

    visit_List = visit_Tuple = _visit_sequence


def scan_source(source: str | bytes, path: str) -> FileScan:
    """Scan one file's source; ``path`` is the repo-relative name hits are reported under.

    Pass raw bytes for a file on disk: ast.parse then decodes them as the interpreter does (a
    UTF-8 BOM, a PEP 263 coding cookie), so a valid file is never reported unparseable.
    """
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as exc:   # bytes that fail to decode raise SyntaxError
        return FileScan(path, error=f"{type(exc).__name__}: {exc}")
    visitor = _FenceVisitor(path)
    visitor.visit(tree)
    return FileScan(path, tuple(visitor.hits), tuple(visitor.argv_hits))


def _excluded_dir(name: str) -> bool:
    return name in policy.EXCLUDED_DIR_NAMES or name.startswith(policy.EXCLUDED_DIR_PREFIXES)


def iter_source_files(repo_root: Path) -> list[Path]:
    """Every .py file under the scan roots that exist in ``repo_root`` (sorted, tests excluded)."""
    files: list[Path] = []
    for root in policy.SCAN_ROOTS:
        for dirpath, dirnames, filenames in os.walk(repo_root / root):
            dirnames[:] = sorted(d for d in dirnames if not _excluded_dir(d))
            files.extend(Path(dirpath) / name for name in sorted(filenames)
                         if name.endswith(".py"))
    return files


def scan_tree(repo_root: Path) -> tuple[FileScan, ...]:
    scans: list[FileScan] = []
    for file in iter_source_files(repo_root):
        rel = file.relative_to(repo_root).as_posix()
        try:
            source = file.read_bytes()
        except OSError as exc:
            scans.append(FileScan(rel, error=f"{type(exc).__name__}: {exc}"))
            continue
        scans.append(scan_source(source, rel))
    return tuple(scans)


# ---------------------------------------------------------------------------
# Policy checks
# ---------------------------------------------------------------------------

def _in_scope(scope: str, pinned: tuple[str, ...]) -> bool:
    """A pinned def covers the closures nested in it (``f`` covers ``f.inner``)."""
    return any(scope == pin or scope.startswith(pin + ".") for pin in pinned)


def row_admits(row: dict, hit: Hit) -> bool:
    return (row["file"] == hit.path and row["capability"] == hit.capability
            and (not row.get("scopes") or _in_scope(hit.scope, row["scopes"]))
            and (not row.get("symbols") or any(_under(hit.target, s) for s in row["symbols"])))


def unapproved(scans: tuple[FileScan, ...], allow: tuple[dict, ...] = policy.ALLOW) -> list[str]:
    """Unparseable files and every hit no ALLOW row admits, as ``file:line`` descriptions."""
    violations = [f"{scan.path}: unparseable, the fence cannot vouch for it ({scan.error})"
                  for scan in scans if scan.error]
    violations += [hit.describe() for scan in scans for hit in scan.hits
                   if not any(row_admits(row, hit) for row in allow)]
    return violations


def egress_in(scans: tuple[FileScan, ...], paths: tuple[str, ...]) -> list[str]:
    """Any capability hit, provider-CLI argv literal or parse failure in the named files."""
    wanted = set(paths)
    found: list[str] = []
    for scan in scans:
        if scan.path not in wanted:
            continue
        if scan.error:
            found.append(f"{scan.path}: unparseable ({scan.error})")
        found += [hit.describe() for hit in scan.hits]
        found += [argv.describe() for argv in scan.argv_hits]
    return found


def argv_outside_llm_client(scans: tuple[FileScan, ...]) -> list[str]:
    allowed = set(policy.CLI_ARGV_RULE["allowed_files"])
    return [argv.describe() for scan in scans for argv in scan.argv_hits
            if argv.path not in allowed]


@pytest.fixture(scope="module")
def tree_scans() -> tuple[FileScan, ...]:
    return scan_tree(_REPO)


def _write(root: Path, rel: str, source: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")


# ---------------------------------------------------------------------------
# Scanner unit tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source, expected", [
    ("def f():\n    import openai\n", {("openai", "llm_sdk", "f")}),
    ("import importlib\nm = importlib.import_module('httpx')\n",
     {("httpx", "http_client", policy.MODULE_SCOPE)}),
    ("from deerflow import models\n", {("deerflow.models", "llm_factory", policy.MODULE_SCOPE)}),
    ("def g():\n    from deerflow.models import create_chat_model\n",
     {("deerflow.models.create_chat_model", "llm_factory", "g")}),
    ("from .factory import create_chat_model\n",
     {(".factory.create_chat_model", "llm_factory", policy.MODULE_SCOPE)}),
    ("from deerflow import *\n", {("deerflow.*", "llm_factory", policy.MODULE_SCOPE),
                                  ("deerflow.*", "data_vendor", policy.MODULE_SCOPE)}),
    ("import graphiti_core\n", {("graphiti_core", "llm_sdk", policy.MODULE_SCOPE)}),
    ("import graphiti_core.llm_client.client as c\n",
     {("graphiti_core.llm_client.client", "llm_sdk", policy.MODULE_SCOPE)}),
    ("from urllib import request as r\n", {("urllib.request", "http_client", policy.MODULE_SCOPE)}),
    ("import urllib.request\n", {("urllib.request", "http_client", policy.MODULE_SCOPE)}),
    ("x = __import__('requests')\n", {("requests", "http_client", policy.MODULE_SCOPE)}),
    ("from importlib import import_module\nm = import_module('exa_py')\n",
     {("exa_py", "data_vendor", policy.MODULE_SCOPE)}),
    ("import importlib\nm = importlib.import_module(name='openai')\n",
     {("openai", "llm_sdk", policy.MODULE_SCOPE)}),
    ("import builtins\nm = builtins.__import__('aiohttp')\n",
     {("aiohttp", "http_client", policy.MODULE_SCOPE)}),
    ("class C:\n    async def m(self):\n        def inner():\n            import aiohttp\n",
     {("aiohttp", "http_client", "C.m.inner")}),
    # decorators, defaults and class bases/keywords run in the enclosing scope, not the def's
    ("import importlib\n@deco(importlib.import_module('httpx'))\ndef f():\n    pass\n",
     {("httpx", "http_client", policy.MODULE_SCOPE)}),
    ("class C:\n    def m(self, x=__import__('requests')) -> None:\n        import aiohttp\n",
     {("requests", "http_client", "C"), ("aiohttp", "http_client", "C.m")}),
    ("class C(__import__('openai').OpenAI, metaclass=M):\n    import anthropic\n",
     {("openai", "llm_sdk", policy.MODULE_SCOPE), ("anthropic", "llm_sdk", "C")}),
    ("try:\n    from langchain_anthropic import ChatAnthropic\nexcept ImportError:\n    pass\n",
     {("langchain_anthropic.ChatAnthropic", "llm_sdk", policy.MODULE_SCOPE)}),
    ("_PROVIDER_MODULES = {'serper': 'deerflow.community.serper.tools', 'x': 'json'}\n",
     {("deerflow.community.serper.tools", "data_vendor", policy.MODULE_SCOPE)}),
    ("_PROVIDER_MODULES: dict = {'fc': 'firecrawl'}\n",
     {("firecrawl", "data_vendor", policy.MODULE_SCOPE)}),
])
def test_scanner_detects_every_import_shape(source, expected):
    scan = scan_source(source, "backend/app/services/example.py")
    assert scan.error is None
    assert {(hit.target, hit.capability, hit.scope) for hit in scan.hits} == expected


@pytest.mark.parametrize("source", [
    "from urllib.parse import urlparse\nimport urllib.parse\nimport urllib.error\n",
    "from graphiti_core import Graphiti\nfrom graphiti_core.nodes import EntityNode\n",
    "from deerflow.agents.middlewares.title_middleware import TitleMiddleware\n",
    "from deerflow.config.app_config import AppConfig\n",
    "from camel.agents import ChatAgent\nfrom camel.types import OpenAIBackendRole\n",
    "from app.utils.llm_client import LLMClient\nfrom ..utils import llm_client\n",
    "import importlib\nm = importlib.import_module(name)\nn = importlib.import_module('json')\n",
    "PROVIDERS = {'serper': 'deerflow.community.serper.tools'}\n",
    "docs = 'import openai; import httpx'\nmodel = 'openai'\n",
])
def test_scanner_ignores_non_egress_imports(source):
    assert scan_source(source, "backend/app/services/example.py").hits == ()


def test_unparseable_file_is_a_violation():
    scan = scan_source("def broken(:\n", "backend/app/services/example.py")
    assert scan.error and scan.error.startswith("SyntaxError")
    assert unapproved((scan,)) == [
        f"backend/app/services/example.py: unparseable, the fence cannot vouch for it "
        f"({scan.error})"]


def test_scope_and_symbol_pins_are_enforced():
    """An allowlisted file gains no blanket licence: pins bind the def and the imported names."""
    gateway = ("def _default_gateway_factory():\n"
               "    from deerflow.models import create_chat_model\n"
               "def _other_path():\n"
               "    from deerflow.models import create_chat_model\n")
    assert unapproved((scan_source(gateway, "deerflow_bridge/linear_research.py"),)) == [
        "deerflow_bridge/linear_research.py:4: deerflow.models.create_chat_model [llm_factory] "
        "in _other_path"]
    adapter = "from openai import RateLimitError\nfrom openai import OpenAI\n"
    assert unapproved((scan_source(
        adapter, "backend/app/services/graphiti_client/llm_adapter.py"),)) == [
        "backend/app/services/graphiti_client/llm_adapter.py:2: openai.OpenAI [llm_sdk] "
        "in <module>"]
    nested = ("def run_actor_ontology_stage():\n"
              "    def _synthesize():\n"
              "        from deerflow.models import create_chat_model\n")
    assert unapproved((scan_source(nested, "deerflow_bridge/deerflow_research.py"),)) == []
    # a decorator argument runs at import time, outside the pinned def
    decorated = ("import importlib\n"
                 "@retry(importlib.import_module('httpx'))\n"
                 "def _http_get():\n"
                 "    import httpx\n")
    assert unapproved((scan_source(decorated, "deerflow_bridge/market_tools.py"),)) == [
        f"deerflow_bridge/market_tools.py:2: httpx [http_client] in {policy.MODULE_SCOPE}"]
    # the same import in a file with no ALLOW row
    assert unapproved((scan_source(gateway, "deerflow_bridge/research_budget.py"),)) != []


def test_scan_tree_decodes_files_like_the_interpreter(tmp_path):
    """Files are read as bytes: a UTF-8 BOM or a PEP 263 coding cookie is not a parse failure,
    while a file the interpreter cannot decode still fails closed."""
    undecodable = "backend/app/services/bad.py"
    bom = "backend/app/services/bom.py"
    latin = "backend/app/services/latin.py"
    (tmp_path / bom).parent.mkdir(parents=True)
    (tmp_path / undecodable).write_bytes(b"label = '\xe9'\n")
    (tmp_path / bom).write_bytes(b"\xef\xbb\xbfimport openai\n")
    (tmp_path / latin).write_bytes(b"# -*- coding: latin-1 -*-\nlabel = '\xe9'\nimport httpx\n")
    scans = scan_tree(tmp_path)
    assert [scan.path for scan in scans] == [undecodable, bom, latin]
    assert [bool(scan.error) for scan in scans] == [True, False, False]
    assert unapproved(scans) == [
        f"{undecodable}: unparseable, the fence cannot vouch for it ({scans[0].error})",
        f"{bom}:1: openai [llm_sdk] in {policy.MODULE_SCOPE}",
        f"{latin}:3: httpx [http_client] in {policy.MODULE_SCOPE}"]


# ---------------------------------------------------------------------------
# The tree against the policy
# ---------------------------------------------------------------------------

def test_no_unapproved_egress_imports(tree_scans):
    violations = unapproved(tree_scans)
    assert violations == [], (
        "egress imports without an ALLOW row in backend/tests/_import_fence_policy.py (route the "
        "call through LLMClient / the research gateway, or add a row naming the reason and the "
        "ledger that meters it):\n" + "\n".join(violations))


def test_report_stage_file_importing_httpx_fails_the_fence(tmp_path):
    """The scanner fed a tmp tree: a report-stage module importing httpx is refused twice over."""
    report_agent = "backend/app/services/report_agent.py"
    _write(tmp_path, report_agent, '"""Report stage."""\n\ndef fetch():\n    import httpx\n')
    _write(tmp_path, "backend/app/services/tests/test_ignored.py", "import httpx\n")
    scans = scan_tree(tmp_path)
    assert [scan.path for scan in scans] == [report_agent]
    expected = [f"{report_agent}:4: httpx [http_client] in fetch"]
    assert unapproved(scans) == expected
    assert egress_in(scans, policy.REPORT_STAGE_MODULES) == expected


def test_no_egress_module_importing_an_sdk_is_flagged(tmp_path):
    """An eval/diagnostic module that lands with a direct SDK import is caught the same way."""
    counter_case = "backend/app/services/forecast_counter_case.py"
    _write(tmp_path, counter_case, "from openai import OpenAI\n")
    scans = scan_tree(tmp_path)
    assert egress_in(scans, policy.NO_EGRESS_MODULES) == [
        f"{counter_case}:1: openai.OpenAI [llm_sdk] in {policy.MODULE_SCOPE}"]


def test_report_stage_modules_have_no_egress(tree_scans):
    scanned = {scan.path for scan in tree_scans}
    for path in policy.REPORT_STAGE_MODULES:
        assert path in scanned, f"report-stage module moved or renamed: {path}"
    present = tuple(path for path in policy.NO_EGRESS_MODULES if path in scanned)
    fenced = policy.REPORT_STAGE_MODULES + present
    found = egress_in(tree_scans, fenced)
    assert found == [], (
        "report-stage and eval/diagnostic modules must import no capability directly (their "
        "model calls go through LLMClient; transitive egress through an allowlisted transport, "
        "e.g. report_agent -> prediction_markets.PolymarketClient fetch/re-quote, is out of "
        "scope):\n" + "\n".join(found))
    licensed = sorted({row["file"] for row in policy.ALLOW} & set(
        policy.REPORT_STAGE_MODULES + policy.NO_EGRESS_MODULES))
    assert licensed == [], f"ALLOW rows must never license a no-egress module: {licensed}"


def test_cli_argv_only_in_llm_client(tree_scans):
    assert argv_outside_llm_client(tree_scans) == []
    in_client = {argv.argv for scan in tree_scans for argv in scan.argv_hits
                 if argv.path in policy.CLI_ARGV_RULE["allowed_files"]}
    assert in_client == set(policy.CLI_ARGV_RULE["pairs"]), (
        "llm_client.py no longer spawns the provider CLIs with literal argv: update CLI_ARGV_RULE")
    for source in ("cmd = ['claude', '-p', '--output-format', 'json']\n",
                   "subprocess.run(('codex', 'exec', '--skip-git-repo-check'))\n"):
        flagged = scan_source(source, "backend/app/services/report_agent.py")
        assert argv_outside_llm_client((flagged,)) == [flagged.argv_hits[0].describe()]
        assert egress_in((flagged,), policy.REPORT_STAGE_MODULES) != []
        in_client_scan = scan_source(source, "backend/app/utils/llm_client.py")
        assert argv_outside_llm_client((in_client_scan,)) == []
    for source in ("cmd = ['ps', '-p', str(pid)]\n", "cmd = [cli, '-p']\n",
                   "cmd = ['claude', '--version']\n"):
        assert scan_source(source, "backend/app/services/x.py").argv_hits == ()


def test_allow_rows_are_well_formed(tree_scans):
    scanned = {scan.path for scan in tree_scans}
    required = {"file", "capability", "reason", "ledger"}
    for row in policy.ALLOW:
        label = f"{row.get('file')} [{row.get('capability')}]"
        assert required <= set(row) <= required | {"scopes", "symbols"}, label
        assert row["file"] in scanned, f"{label}: not a scanned file"
        assert row["capability"] in policy.CAPABILITIES, label
        for field in ("reason", "ledger"):
            assert isinstance(row[field], str) and row[field].strip(), f"{label}: empty {field}"
        for field in ("scopes", "symbols"):
            if field in row:
                values = row[field]
                assert isinstance(values, tuple) and values, f"{label}: {field} must be a tuple"
                assert all(isinstance(v, str) and v for v in values), f"{label}: {field}"


def test_no_stale_allow_rows(tree_scans):
    hits = [hit for scan in tree_scans for hit in scan.hits]
    stale = [f"{row['file']} [{row['capability']}] scopes={row.get('scopes')} "
             f"symbols={row.get('symbols')}"
             for row in policy.ALLOW if not any(row_admits(row, hit) for hit in hits)]
    assert stale == [], "ALLOW rows that match no import (delete or narrow them):\n" + "\n".join(
        stale)


def test_scanner_floor(tree_scans):
    for root in policy.SCAN_ROOTS:
        assert (_REPO / root).is_dir(), f"scan root missing: {root}"
    hits = [hit for scan in tree_scans for hit in scan.hits]
    assert [scan.path for scan in tree_scans if scan.error] == []
    assert len(tree_scans) >= policy.SCANNER_FLOOR["files"], len(tree_scans)
    assert len(hits) >= policy.SCANNER_FLOOR["hits"], len(hits)
    assert {hit.capability for hit in hits} == set(policy.CAPABILITIES)
    assert not any("/tests/" in f"/{scan.path}" for scan in tree_scans)


# ---------------------------------------------------------------------------
# Sim scripts: the dead camel.models / camel.types probes are gone
# ---------------------------------------------------------------------------

_SIM_SCRIPTS = ("run_parallel_simulation.py", "run_reddit_simulation.py",
                "run_twitter_simulation.py")
_OASIS_NAMES = ("ActionType", "LLMAction", "ManualAction", "generate_reddit_agent_graph",
                "generate_twitter_agent_graph")


def _stub_module(name: str, attributes: tuple[str, ...]) -> types.ModuleType:
    module = types.ModuleType(name)
    for attribute in attributes:
        setattr(module, attribute, MagicMock(name=f"{name}.{attribute}"))
    return module


@pytest.mark.parametrize("script", _SIM_SCRIPTS)
def test_sim_scripts_import_without_camel_models(script, monkeypatch, tmp_path):
    """Each sim script byte-compiles and its module level runs with camel.models and camel.types
    unimportable. The removed ModelFactory / ModelPlatformType imports sat in the oasis ``try``
    block, so a leftover one would end the import in its ``sys.exit(1)`` branch.

    oasis is stubbed (the real package imports camel.models itself), and so is
    app.utils.oasis_llm: it is the allowlisted camel.models adapter, and this check is about the
    script's own imports. The scripts' module-level side effects (sys.path inserts, a root-logger
    filter, a TOKENIZERS_PARALLELISM default) are undone at teardown.
    """
    path = _REPO / "backend" / "scripts" / script
    py_compile.compile(str(path), cfile=str(tmp_path / f"{path.stem}.pyc"), doraise=True)

    for blocked in ("camel.models", "camel.types"):
        monkeypatch.setitem(sys.modules, blocked, None)
    monkeypatch.setitem(sys.modules, "oasis", _stub_module("oasis", _OASIS_NAMES))
    monkeypatch.setitem(sys.modules, "app.utils.oasis_llm", _stub_module(
        "app.utils.oasis_llm", ("create_oasis_model", "get_oasis_semaphore")))
    monkeypatch.setattr(sys, "path", list(sys.path))
    root_logger = logging.getLogger()
    monkeypatch.setattr(root_logger, "filters", list(root_logger.filters))
    # delenv records no undo for an absent variable, so set it first: teardown then restores the
    # original state, absent or not, after the script's setdefault.
    monkeypatch.setenv("TOKENIZERS_PARALLELISM", "unset-by-test")
    monkeypatch.delenv("TOKENIZERS_PARALLELISM")

    name = f"_import_fence_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, module)
    try:
        spec.loader.exec_module(module)
    except SystemExit as exc:
        pytest.fail(f"{script} exited while importing (code {exc.code}): its dependency probe "
                    "still needs a module outside oasis (camel.models / camel.types?)")
    assert module.oasis is sys.modules["oasis"]
    assert module.create_oasis_model is sys.modules["app.utils.oasis_llm"].create_oasis_model
    assert not hasattr(module, "ModelFactory") and not hasattr(module, "ModelPlatformType")
