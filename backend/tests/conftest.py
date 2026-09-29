"""Shared pytest fixtures (EXECPLAN2 I-7-0 / I-7-4, INFRA-12).

Offline-first: no test here may hit a real LLM or network. The FakeLLMClient
fixture lets generator/report code be exercised deterministically without
burning API calls (I-7-4: record/replay-style stub).

Hermetic (INFRA-12, helpers in tests/_hermetic.py): the developer's shell is
scrubbed before ``app`` is imported, collection may not mutate os.environ,
sockets / DNS / provider-CLI spawns are refused from this file's import on
(test-module imports included) unless a test opts in with a marker
(localhost, subprocess_egress, integration), process-global breakers and
caches are reset around every test, and Config._persist_env never writes the
real .env.

No ``pytest_plugins`` here: pytest rejects it in a conftest that is not
top-level (``pytest .`` from the repo root); test_suite_isolation.py loads
pytester itself.
"""

import os
import sys

import pytest

import _hermetic

# INFRA-12: pop every ambient name that could steer DRF code (names the DRF
# sources read, Config knobs, .env names, credentials, egress endpoints) before
# anything imports ``app``, so an exported LLM_PROVIDER, API key or feature flag
# cannot change test behaviour.  Runs once per process: `from tests.conftest
# import ...` re-executes this file under a second module name and must not pop
# names that app modules set since.
_FIRST_CONFTEST_LOAD = _hermetic.ENV_BASELINE is None
if _FIRST_CONFTEST_LOAD:
    _hermetic.scrub_ambient_env(os.environ)
    # Arm the egress guard before any test module (or app module it imports) is
    # imported: an import-time download or DNS lookup is refused and recorded,
    # and pytest_collection_finish stops the session over it.
    _hermetic.EGRESS_GUARD.install()

# Hard test-process boundary: importing or constructing the Flask app runs
# lifecycle recovery hooks in production.  Without this marker, a pytest
# process can scan the real uploads tree, mistake a simulator owned by the live
# localhost backend for an orphan, and terminate it.  Set this at conftest
# import time (before test modules are imported), not in a fixture, so even
# module-level app construction remains non-destructive.
os.environ["DRF_TEST_PROCESS"] = "1"

# Baseline for pytest_collection_finish: collection must not change os.environ.
if _FIRST_CONFTEST_LOAD:
    _hermetic.ENV_BASELINE = dict(os.environ)

# Make `import app...` work when running pytest from the backend/ dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeLLMClient:
    """Drop-in stand-in for app.utils.llm_client.LLMClient.

    Returns scripted responses in order (or a default), and records every call
    so tests can assert what was sent. Mirrors the real public surface (chat,
    chat_json, chat_with_tools, supports_native_tools, last_call_meta); every
    parameter name of the real methods is accepted, which
    test_suite_isolation.py pins with a signature-subset meta-test.
    """

    def __init__(self, responses=None, json_responses=None, provider="fake", model="fake-1",
                 *, tool_responses=None):
        self.provider = provider
        self.model = model
        self._responses = list(responses or [])
        self._json_responses = list(json_responses or [])
        self._tool_responses = list(tool_responses or [])
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None,
             tier=None, **kwargs):
        self.calls.append({"kind": "chat", "messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "response_format": response_format,
                           "tier": tier})
        if self._responses:
            return self._responses.pop(0)
        return "FAKE_RESPONSE"

    def chat_json(self, messages, temperature=0.3, max_tokens=4096, tier=None, **kwargs):
        self.calls.append({"kind": "chat_json", "messages": messages, "temperature": temperature,
                           "max_tokens": max_tokens, "tier": tier})
        if self._json_responses:
            return self._json_responses.pop(0)
        return {}

    def chat_with_tools(self, messages, tools_schema=None, temperature=0.4, max_tokens=4096,
                        tier=None, **kwargs):
        """Scripted native tool-calling turn: tool_responses FIFO, then a final no-tool reply."""
        self.calls.append({"kind": "chat_with_tools", "messages": messages,
                           "temperature": temperature, "max_tokens": max_tokens,
                           "tools_schema": tools_schema, "tier": tier})
        if self._tool_responses:
            return self._tool_responses.pop(0)
        return {"content": "FAKE_RESPONSE", "tool_calls": []}

    def supports_native_tools(self):
        return False

    def last_call_meta(self):
        return None


@pytest.fixture(autouse=True)
def _no_prediction_market_network(monkeypatch):
    """预测市场客户端离线化（offline-first 契约）：Polymarket 公开 API 是 keyless 的，
    任何走到 PolymarketClient 兜底现抓的路径都可能发真实请求。测试一律关闭
    PREDICTION_MARKETS_ENABLED → client.enabled=False → 快速降级为空结果。
    需要 client 行为的测试显式打开旗标并 mock httpx（见 test_prediction_markets.py）。"""
    monkeypatch.setenv("PREDICTION_MARKETS_ENABLED", "false")
    try:
        from app.config import Config
        monkeypatch.setattr(Config, "PREDICTION_MARKETS_ENABLED", False, raising=False)
    except Exception:  # noqa: BLE001 — Config 不可导入时旗标已由环境变量兜底
        pass


@pytest.fixture(autouse=True)
def _no_ambient_firecrawl_key(monkeypatch):
    """Firecrawl 凭据离线化（offline-first 契约）：app.config 以 override=True 加载 .env，
    真实 FIRECRAWL_API_KEY 会泄入 pytest 进程并把 search/fetch 调度路由到付费直连后端，
    使既有 delegate/DDG 断言按环境漂移。测试一律剥离该 key；需要 firecrawl 路由的测试
    显式 setenv 假 key 并 mock httpx（见 test_sessionb_firecrawl.py）。"""
    monkeypatch.delenv("FIRECRAWL_API_KEY", raising=False)


@pytest.fixture(autouse=True)
def _no_ambient_research_engine_selection(monkeypatch):
    """Research-engine dispatch is explicit in tests.

    ``app.config`` does not load the developer ``.env`` under DRF_TEST_PROCESS,
    and since INFRA-12 neither do the simulation scripts imported by some tests
    (load_project_dotenv is a no-op here; the ambient scrub and the collection
    env check cover the rest).  This per-test belt stays because a stray
    ``RESEARCH_ENGINE`` / ``RESEARCH_LINEAR_MODE`` set by one test would silently
    reroute ``deerflow_research.main()`` in the next.  Tests that exercise a
    specific engine set the variable explicitly with ``monkeypatch.setenv``.
    """
    for name in ("RESEARCH_ENGINE", "RESEARCH_LINEAR_MODE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def fake_llm():
    """Factory: fake_llm(responses=[...], json_responses=[...]) -> FakeLLMClient."""
    def _make(**kwargs):
        return FakeLLMClient(**kwargs)
    return _make


@pytest.fixture
def tmp_run_dir(tmp_path):
    """A throwaway run directory for artifact-write tests."""
    d = tmp_path / "run"
    d.mkdir()
    return str(d)


# ---------------------------------------------------------------------------
# pytest must not pollute production logs (backend/logs/mirofish.log*).
# Test runs previously logged through the real 'mirofish' logger hierarchy into
# backend/logs/mirofish.log — the 2026-07-22 rotated file is 3.2MB of pure
# pytest noise, corrupting run forensics. Quarantine for the whole session:
# every FileHandler pointing into backend/logs is swapped for one shared
# handler under the pytest tmp dir (NullHandler if even that fails), and
# app.utils.logger.LOG_DIR is repointed so loggers first created mid-session
# also land in tmp. Nothing is restored afterwards — session end == process
# end. Defensive throughout: a logging hiccup must never fail the test session.
# ---------------------------------------------------------------------------

_BACKEND_LOGS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")


@pytest.fixture(scope="session", autouse=True)
def _quarantine_mirofish_log_handlers(tmp_path_factory):
    import logging

    sink_dir = None
    try:
        sink_dir = str(tmp_path_factory.mktemp("mirofish-logs"))
    except Exception:  # noqa: BLE001 — tmp unavailable → NullHandler below
        sink_dir = None

    sink_handler = None
    if sink_dir:
        try:
            sink_handler = logging.FileHandler(
                os.path.join(sink_dir, "mirofish.log"), encoding="utf-8")
            sink_handler.setLevel(logging.DEBUG)
        except Exception:  # noqa: BLE001
            sink_handler = None
    if sink_handler is None:
        sink_handler = logging.NullHandler()

    # Loggers created later in the session call setup_logger(), which reads
    # LOG_DIR at call time — repoint it so their new FileHandlers also land in
    # the tmp sink instead of backend/logs.
    if sink_dir:
        try:
            from app.utils import logger as _app_logger_module
            _app_logger_module.LOG_DIR = sink_dir
        except Exception:  # noqa: BLE001 — app package not importable: nothing to repoint
            pass

    logs_root = os.path.abspath(_BACKEND_LOGS_DIR)
    try:
        names = {n for n in list(logging.Logger.manager.loggerDict)
                 if n == "mirofish" or n.startswith("mirofish.")}
        names.add("mirofish")
        for name in sorted(names):
            lg = logging.getLogger(name)
            for handler in list(getattr(lg, "handlers", None) or []):
                base = getattr(handler, "baseFilename", None)
                if not base:
                    continue  # console/NullHandler etc. — leave untouched
                try:
                    inside = os.path.commonpath(
                        [os.path.abspath(base), logs_root]) == logs_root
                except ValueError:  # e.g. different drives on Windows
                    inside = False
                if not inside:
                    continue
                lg.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass
                if sink_handler not in lg.handlers:
                    lg.addHandler(sink_handler)
    except Exception:  # noqa: BLE001 — never fail the session over log plumbing
        pass
    yield


@pytest.fixture(autouse=True)
def _isolate_telemetry_active_runs():
    """FOG-TEL-1: the single-active-run fallback registry is process-global.

    Tests that call set_run_context()/LLMMeter without deregistering would
    otherwise leak "active" runs into later tests, silently absorbing their
    unattributed records (observed: pipe_translation_context lingering across
    files in the full suite). Clear the registry around every test.
    """
    try:
        from app.utils import telemetry as _telemetry
        _telemetry._clear_active_runs()
    except Exception:  # noqa: BLE001 — telemetry not importable in this test's env
        _telemetry = None
    yield
    if _telemetry is not None:
        try:
            _telemetry._clear_active_runs()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# INFRA-12 hermetic harness: collection env check, egress guard, global-state
# reset and the .env persistence stub.  Helpers live in tests/_hermetic.py.
# ---------------------------------------------------------------------------

def pytest_collection_finish(session):
    """Importing test modules must not change os.environ or reach out; then the
    between-tests policy takes over.

    An import-time mutation leaks into every later test (the sim scripts'
    load_dotenv once injected the developer's .env this way).  Known DRF and
    third-party import-time settings are allowlisted in
    _hermetic.IMPORT_TIME_ENV_ALLOWLIST and empty values are ignored; anything
    else stops the session.  Values are never printed: they may be credentials.

    The socket / DNS / subprocess patches went in when this file was imported
    and stay for the whole run (a test that monkeypatches the same attributes
    restores the guard, not the raw originals).  Egress refused since then, even
    if the importing module swallowed the error, stops the session too.  The
    install() here is a no-op except in a second session in one process: the
    conftest arms the guard on its first import only, and the first session's
    end uninstalled it.  The runtest hooks below switch policy per test.
    """
    guard = _hermetic.EGRESS_GUARD
    guard.install()
    refusals = guard.take_refusals()
    guard.idle()
    problems = []
    mutated = _hermetic.env_mutations(_hermetic.ENV_BASELINE, os.environ)
    if mutated:
        problems.append(
            "test collection mutated os.environ at import time: " + ", ".join(mutated)
            + ". Set environment variables inside a fixture (monkeypatch.setenv), "
            "not at module import.")
    if refusals:
        problems.append(
            "egress refused during pytest start-up or test collection: " + "; ".join(refusals)
            + ". Reach the network inside a marked test or stub it, not at module import.")
    if problems:
        raise pytest.UsageError(" ".join(problems))


class _ExemptItemsOutsideTheHarness:
    """Runs the tests this conftest does not own exempt from the egress guard.

    pytest calls a conftest's runtest hooks only for the items under its
    directory, but the guard is process-wide.  A session that also collects
    tests elsewhere (``pytest .`` from the repo root collects
    backend/scripts/test_*.py) would run those under the between-tests policy
    and charge their refusals to the next backend test.  So every item is
    exempted as its setup starts (a wrapper runs ahead of the plain hooks);
    the conftest's own pytest_runtest_setup below then applies the harness
    policy to the items it owns before any fixture is set up, and every
    teardown ends in the between-tests policy.
    """

    @pytest.hookimpl(wrapper=True, tryfirst=True)
    def pytest_runtest_setup(self, item):
        _hermetic.EGRESS_GUARD.exempt()
        return (yield)

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_teardown(self, item, nextitem):
        try:
            return (yield)
        finally:
            _hermetic.EGRESS_GUARD.idle()


_OUTSIDE_ITEMS_PLUGIN_NAME = "drf-egress-exempt-outside-the-harness"


def pytest_configure(config):
    """Register _ExemptItemsOutsideTheHarness for the whole session."""
    if not config.pluginmanager.has_plugin(_OUTSIDE_ITEMS_PLUGIN_NAME):
        config.pluginmanager.register(_ExemptItemsOutsideTheHarness(), _OUTSIDE_ITEMS_PLUGIN_NAME)


@pytest.hookimpl(wrapper=True, trylast=True)
def pytest_sessionfinish(session):
    """Fail the session for egress refused after the last test, then restore the originals.

    The innermost wrapper: its finally runs after pytest has torn down whatever
    fixtures remained (an interrupted run) and before the terminal summary.  A
    refusal recorded this late (a thread that outlived the last test, a
    session fixture torn down here) has no test left to fail, so it is printed
    and turns a passing exit status into TESTS_FAILED.
    """
    try:
        return (yield)
    finally:
        guard = _hermetic.EGRESS_GUARD
        refusals = guard.take_refusals()
        guard.uninstall()
        if refusals:
            _report_session_refusals(session, refusals)


def _report_session_refusals(session, refusals):
    message = "egress refused after the last test's teardown: " + "; ".join(refusals)
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_sep("=", "egress refused outside any test", red=True)
        reporter.write_line(message, red=True)
    else:
        print(message, file=sys.stderr)
    if session.exitstatus in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item):
    """Apply the test's egress policy before any of its fixtures (any scope) is set up.

    pytest calls this only for the items under this directory (the others run
    exempt, see _ExemptItemsOutsideTheHarness).  The policy:

    - AF_INET/AF_INET6 connects and datagrams are refused, loopback included,
      unless the test is marked @pytest.mark.localhost (loopback only);
    - the resolvers refuse every hostname except localhost and IP literals, and
      reverse lookups of non-loopback addresses;
    - Popen / os.system / os.posix_spawn / os.exec* refuse claude, codex, curl,
      wget, the macOS keychain CLI (security) and the pipeline children
      (run_*_simulation.py, deerflow_research.py, resolution_monitor.py), also
      behind sh -c, env, timeout, uv run or npx/node, unless the test is marked
      @pytest.mark.subprocess_egress;
    - @pytest.mark.integration tests are exempt.
    """
    guard = _hermetic.EGRESS_GUARD
    if item.get_closest_marker("integration") is not None:
        guard.exempt()
    else:
        guard.activate(
            allow_loopback=item.get_closest_marker("localhost") is not None,
            allow_subprocess=item.get_closest_marker("subprocess_egress") is not None,
        )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_teardown(item, nextitem):
    """Fail this teardown for egress refused while its fixtures were torn down, then
    return to the between-tests policy (refuse everything).

    _no_egress checks when the function-scoped fixtures unwind; this catches what
    is torn down after it: autouse fixtures set up before it and the class,
    module and session fixtures this item's teardown finalizes (pytest charges
    those to the item whose teardown runs them, as it does for their errors).
    """
    guard = _hermetic.EGRESS_GUARD
    try:
        return (yield)
    finally:
        refusals = guard.take_refusals()
        guard.idle()
        if refusals:
            pytest.fail(
                "egress refused while tearing down this test's fixtures (any scope): "
                + "; ".join(refusals), pytrace=False)


@pytest.fixture(autouse=True)
def _no_egress():
    """Fail the test at teardown if any egress was refused while it ran.

    A refusal raises EgressRefused (a PermissionError) and is recorded; DRF's
    degrade-safe paths often swallow OSError, so the record is what makes a
    swallowed attempt fail loudly.  A refusal recorded between tests (a thread
    that outlived its test) is reported by the next test, labelled as such.
    Tests that provoke a refusal on purpose request this fixture and call
    take_refusals().
    """
    guard = _hermetic.EGRESS_GUARD
    yield guard
    refusals = guard.take_refusals()
    if refusals:
        pytest.fail(
            "egress refused during this test (even if the code under test swallowed the error): "
            + "; ".join(refusals), pytrace=False)


@pytest.fixture
def real_socket_connect():
    """The unguarded socket.socket.connect; call as real_socket_connect(sock, address)."""
    return _hermetic.EGRESS_GUARD.real_connect


@pytest.fixture
def real_popen():
    """Build a subprocess.Popen through the original constructor, bypassing the guard."""
    return _hermetic.EGRESS_GUARD.popen_unguarded


@pytest.fixture(autouse=True)
def _reset_process_globals():
    """Clear llm_client breakers / fallback caches, LLMCache, the cost-override cache
    and the orchestrator outage probe + breakers before and after every test."""
    _hermetic.reset_process_globals()
    yield
    _hermetic.reset_process_globals()


@pytest.fixture(scope="session", autouse=True)
def _stub_persist_env():
    """Config._persist_env upserts into the real repo-root .env; no test may write it.

    Stubbed for the whole session so a test that monkeypatches it restores the
    stub, never the writer.  Yields the original bound method (real_persist_env).
    """
    try:
        from app.config import Config
    except Exception:  # noqa: BLE001 — Config not importable: nothing can write .env
        yield None
        return
    original = Config.__dict__["_persist_env"].__get__(None, Config)
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(Config, "_persist_env", classmethod(lambda cls, updates, *args, **kwargs: None))
        yield original


@pytest.fixture
def real_persist_env(_stub_persist_env):
    """The original Config._persist_env; it writes the real repo-root .env."""
    return _stub_persist_env
