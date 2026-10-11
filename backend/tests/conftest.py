"""Shared pytest fixtures (EXECPLAN2 I-7-0 / I-7-4).

Offline-first: no test here may hit a real LLM or network. The FakeLLMClient
fixture lets generator/report code be exercised deterministically without
burning API calls (I-7-4: record/replay-style stub).
"""

import os
import sys

import pytest

# Hard test-process boundary: importing or constructing the Flask app runs
# lifecycle recovery hooks in production.  Without this marker, a pytest
# process can scan the real uploads tree, mistake a simulator owned by the live
# localhost backend for an orphan, and terminate it.  Set this at conftest
# import time (before test modules are imported), not in a fixture, so even
# module-level app construction remains non-destructive.
os.environ["DRF_TEST_PROCESS"] = "1"

# Make `import app...` work when running pytest from the backend/ dir.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class FakeLLMClient:
    """Drop-in stand-in for app.utils.llm_client.LLMClient.

    Returns scripted responses in order (or a default), and records every call
    so tests can assert what was sent. Mirrors the real surface: chat(),
    chat_json(), supports_native_tools().
    """

    def __init__(self, responses=None, json_responses=None, provider="fake", model="fake-1"):
        self.provider = provider
        self.model = model
        self._responses = list(responses or [])
        self._json_responses = list(json_responses or [])
        self.calls = []

    def chat(self, messages, temperature=0.7, max_tokens=4096, response_format=None):
        self.calls.append({"kind": "chat", "messages": messages, "temperature": temperature})
        if self._responses:
            return self._responses.pop(0)
        return "FAKE_RESPONSE"

    def chat_json(self, messages, temperature=0.3, max_tokens=4096):
        self.calls.append({"kind": "chat_json", "messages": messages, "temperature": temperature})
        if self._json_responses:
            return self._json_responses.pop(0)
        return {}

    def supports_native_tools(self):
        return False


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

    ``app.config`` no longer loads the developer ``.env`` under DRF_TEST_PROCESS,
    but simulation scripts imported by some tests call ``load_dotenv`` themselves
    (without override), which would still inject ``RESEARCH_ENGINE`` /
    ``RESEARCH_LINEAR_MODE`` into ``os.environ`` for the rest of the session and
    silently reroute ``deerflow_research.main()``.  Tests that exercise a specific
    engine set the variable explicitly with ``monkeypatch.setenv``.
    """
    for name in ("RESEARCH_ENGINE", "RESEARCH_LINEAR_MODE"):
        monkeypatch.delenv(name, raising=False)


# 官方数据源的 key 名与路径旋钮（design §12）：key 不是 Config 属性，经 os.environ 透传。
_DATA_SOURCE_ENV_NAMES = (
    "FRED_API_KEY", "BLS_API_KEY", "EIA_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY",
    "DATA_GOV_API_KEY", "SEC_CONTACT_EMAIL",
    "DATA_SOURCES", "DATA_SOURCES_DIR", "DATA_SOURCES_NODE", "DATA_SOURCES_CACHE_DIR",
)


def _reset_data_mcp_hubs():
    """关闭并遗忘 data_mcp 的进程级 hub 单例（连同其 MCP 子进程）。

    data_mcp 经 deerflow_bridge/ 上 sys.path 后按裸名导入，或按文件路径以 *data_mcp 别名加载；
    只处理已导入的模块（未导入即不存在单例，无需重置，也不为此把 bridge 目录塞进 sys.path）。
    """
    # Clients retain an environment/cache view in addition to the transport.
    # Reset them first so an opt-in test cannot reuse a prior disabled client
    # (or a client holding the hub that is about to be closed).
    for name, module in list(sys.modules.items()):
        if module is None or not name.endswith("data_sources"):
            continue
        reset = getattr(module, "reset_data_sources_for_tests", None)
        if callable(reset):
            try:
                reset()
            except Exception:  # test cleanup must not mask the original failure
                pass
    for name, module in list(sys.modules.items()):
        if module is None or not name.endswith("data_mcp"):
            continue
        reset = getattr(module, "reset_hub_for_tests", None)
        if callable(reset):
            try:
                reset()
            except Exception:  # noqa: BLE001 — 清理失败不能让无关测试失败
                pass


@pytest.fixture(autouse=True)
def _no_ambient_data_sources(monkeypatch):
    """官方数据源离线化（offline-first 契约）：六个数据 MCP 服务会联网、依赖 node 与已构建的
    datamcps/，且 FRED_API_KEY 等 key 可能经开发者 shell profile 泄入 pytest 进程。测试一律
    DATA_SOURCES_ENABLED=false，剥离 key 与路径旋钮，并在每个测试前后重置 data_mcp 的进程级
    hub 单例（不留 MCP 子进程、不跨测试串状态）。需要数据层行为的测试自行 setenv / monkeypatch
    Config 打开，并用 fake stdio MCP server fixture 代替真实服务。"""
    monkeypatch.setenv("DATA_SOURCES_ENABLED", "false")
    for name in _DATA_SOURCE_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    try:
        from app.config import Config
        monkeypatch.setattr(Config, "DATA_SOURCES_ENABLED", False, raising=False)
    except Exception:  # noqa: BLE001 — Config 不可导入时旗标已由环境变量兜底
        pass
    _reset_data_mcp_hubs()
    yield
    _reset_data_mcp_hubs()


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
