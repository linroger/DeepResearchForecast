"""RESEARCH-1: a hard wall-clock bound for every v3 web_fetch, and the direct
fallback's PDF extraction (pypdf, else pdfplumber, off the event loop).

``asyncio.run`` waits for the loop's default executor when it shuts down, so a
hung ``asyncio.to_thread`` (a readability parse, the Exa SDK, getaddrinfo) held
a fetch far past every provider ``wait_for``.  The bounded runner returns
"Error: fetch call deadline exceeded" at the deadline without waiting for the
leftover thread; RESEARCH_FETCH_CALL_TIMEOUT_S=0 keeps the asyncio.run path.
Offline: coroutines, providers, httpx and the PDF libraries are fakes.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time
import types

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE = os.path.join(os.path.dirname(_BACKEND), "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import cached_fetch as cf  # noqa: E402
import research_gateway as rg  # noqa: E402
from app.services import pipeline_orchestrator as po  # noqa: E402


async def _hung_page() -> str:
    await asyncio.to_thread(time.sleep, 3)
    return "late page"


# ============================================================== bounded runner

def test_bounded_runner_returns_the_deadline_error_without_waiting_for_the_thread():
    started = time.monotonic()
    assert rg._run_coroutine_bounded(_hung_page, 0.3) == "Error: fetch call deadline exceeded"
    assert time.monotonic() - started < 1.5


def test_bounded_runner_is_bounded_inside_a_running_loop_too():
    async def caller():
        started = time.monotonic()
        result = rg._run_coroutine_bounded(_hung_page, 0.3)
        return result, time.monotonic() - started

    result, elapsed = asyncio.run(caller())
    assert result == rg.FETCH_DEADLINE_ERROR and elapsed < 1.5


def test_bounded_runner_returns_results_and_cleans_up_the_loop():
    cancelled = threading.Event()

    async def background():
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()

    async def page():
        asyncio.get_running_loop().create_task(background())
        await asyncio.sleep(0)
        return "page text"

    assert rg._run_coroutine_bounded(page, 5) == "page text"
    assert cancelled.is_set()                      # pending tasks are cancelled, not leaked


def test_a_timeout_raised_by_the_fetch_itself_is_not_the_deadline():
    async def provider_timeout():
        raise TimeoutError("read timed out")

    with pytest.raises(TimeoutError, match="read timed out"):
        rg._run_coroutine_bounded(provider_timeout, 5)


def test_deadline_slug_is_not_transient():
    reason = rg.ResearchTools._failure_reason(rg.FETCH_DEADLINE_ERROR, None)
    assert reason == "fetch_call_deadline_exceeded"
    assert not rg._TRANSIENT_FETCH_REASON_RE.search(reason)


# ============================================================== _default_fetch_fn routing

def _fake_cached_fetch(monkeypatch, coroutine_fn):
    calls: list[str] = []

    async def cached_fetch(url, fetch_fn, revisit_reason=""):
        calls.append(url)
        return await fetch_fn(url)

    fake = types.ModuleType("cached_fetch")
    fake.cached_fetch = cached_fetch
    fake._resilient_fetch = coroutine_fn
    monkeypatch.setitem(sys.modules, "cached_fetch", fake)
    return calls


@pytest.mark.parametrize("raw, expected", [
    (None, 150.0), ("", 150.0), ("150", 150.0), ("0.3", 0.3), ("0", 0.0), ("-5", 0.0),
    ("banana", 150.0), ("inf", 150.0), ("nan", 150.0),
])
def test_fetch_call_timeout_knob(monkeypatch, raw, expected):
    if raw is None:
        monkeypatch.delenv("RESEARCH_FETCH_CALL_TIMEOUT_S", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_FETCH_CALL_TIMEOUT_S", raw)
    assert rg._fetch_call_timeout_s() == expected


def test_default_fetch_fn_uses_the_bounded_runner_by_default(monkeypatch):
    async def page(url):
        return "# Page\n\n" + "Body text with 2030 numbers. " * 20

    _fake_cached_fetch(monkeypatch, page)
    monkeypatch.delenv("RESEARCH_FETCH_CALL_TIMEOUT_S", raising=False)
    seen: list[float] = []
    real = rg._run_coroutine_bounded

    def spy(factory, timeout_s):
        seen.append(timeout_s)
        return real(factory, timeout_s)

    monkeypatch.setattr(rg, "_run_coroutine_bounded", spy)
    monkeypatch.setattr(rg, "_run_coroutine_blocking",
                        lambda factory: pytest.fail("the unbounded runner must not be used"))
    assert rg._default_fetch_fn("https://example.org/a").startswith("# Page")
    assert seen == [150.0]


def test_zero_timeout_routes_to_the_asyncio_run_path(monkeypatch):
    async def page(url):
        return "# Page\n\nbody"

    _fake_cached_fetch(monkeypatch, page)
    monkeypatch.setenv("RESEARCH_FETCH_CALL_TIMEOUT_S", "0")
    used: list[str] = []
    real = rg._run_coroutine_blocking

    def spy(factory):
        used.append("blocking")
        return real(factory)

    monkeypatch.setattr(rg, "_run_coroutine_blocking", spy)
    monkeypatch.setattr(rg, "_run_coroutine_bounded",
                        lambda factory, timeout_s: pytest.fail("the bounded runner must not be used"))
    assert rg._default_fetch_fn("https://example.org/a") == "# Page\n\nbody"
    assert used == ["blocking"]


def test_hung_provider_chain_fails_once_within_the_bound_and_is_not_retried(monkeypatch, tmp_path):
    async def hung_chain(url):
        await asyncio.to_thread(time.sleep, 2)
        return "# Late page\n\n" + "text " * 100

    calls = _fake_cached_fetch(monkeypatch, hung_chain)
    monkeypatch.setenv("RESEARCH_FETCH_CALL_TIMEOUT_S", "0.3")
    tools = rg.ResearchTools(rg.SourceLedger(tmp_path / "ledger.json"), tmp_path / "pages",
                             search_fn=lambda q, n: "{}")
    started = time.monotonic()
    first = tools.fetch("https://example.org/slow", agent_id="K1")
    assert time.monotonic() - started < 0.3 + 5
    assert first == "FETCH_FAILED(fetch_call_deadline_exceeded): try another source."
    second = tools.fetch("https://example.org/slow", agent_id="K2")
    assert "already failed in this run" in second
    assert calls == ["https://example.org/slow"]    # never retried
    assert not any(row.get("fetched") for row in tools.ledger.rows())


# ============================================================== PDF extraction

class _FakePdfPage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class _FakePdf:
    def __init__(self, pages) -> None:
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def _fake_pdfplumber(pages_text: list[str]) -> types.ModuleType:
    module = types.ModuleType("pdfplumber")
    module.opened = []

    def open_(stream):
        module.opened.append(stream.read(4))
        return _FakePdf([_FakePdfPage(text) for text in pages_text])

    module.open = open_
    return module


def test_pdf_text_falls_back_to_pdfplumber_when_pypdf_is_absent(monkeypatch):
    plumber = _fake_pdfplumber(["page one text", "page two text", "page three text"])
    monkeypatch.setitem(sys.modules, "pypdf", None)         # import raises ImportError
    monkeypatch.setitem(sys.modules, "pdfplumber", plumber)
    assert cf._extract_pdf_text(b"%PDF-1.7 body", max_pages=2) == "page one text\n\npage two text"
    assert plumber.opened == [b"%PDF"]


def test_pdf_text_reports_the_parse_error_when_every_library_fails(monkeypatch):
    broken = types.ModuleType("pypdf")

    class PdfReader:
        def __init__(self, stream):
            raise ValueError("corrupt xref table")

    broken.PdfReader = PdfReader
    monkeypatch.setitem(sys.modules, "pypdf", broken)
    monkeypatch.setitem(sys.modules, "pdfplumber", None)
    with pytest.raises(ValueError, match="corrupt xref"):
        cf._extract_pdf_text(b"%PDF-1.7")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(ImportError):
        cf._extract_pdf_text(b"%PDF-1.7")


class _FakeResponse:
    status_code = 200
    headers = {"content-type": "application/pdf"}
    content = b"%PDF-1.7 fake body"
    text = ""


def _fake_httpx(monkeypatch) -> None:
    class AsyncClient:
        def __init__(self, **kwargs) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc) -> None:
            return None

        async def get(self, url):
            return _FakeResponse()

    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=AsyncClient))

    async def public(host):
        return True

    monkeypatch.setattr(cf, "_host_is_public", public)


def test_direct_fallback_pdf_extracts_through_pdfplumber(monkeypatch):
    _fake_httpx(monkeypatch)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    monkeypatch.setitem(sys.modules, "pdfplumber", _fake_pdfplumber(["Capacity reached 176 GW in 2023. " * 12]))
    text = asyncio.run(cf._direct_http_fetch("https://agency.example/report.pdf"))
    assert text.startswith("Capacity reached 176 GW in 2023.") and len(text) >= 200


def test_direct_fallback_pdf_without_text_keeps_the_200_char_rule(monkeypatch):
    _fake_httpx(monkeypatch)
    monkeypatch.setitem(sys.modules, "pypdf", None)
    monkeypatch.setitem(sys.modules, "pdfplumber", _fake_pdfplumber(["", "scan"]))
    assert asyncio.run(cf._direct_http_fetch("https://agency.example/scan.pdf")) == (
        "Error: direct fallback PDF had no extractable text")


def test_direct_fallback_pdf_parse_is_bounded(monkeypatch):
    _fake_httpx(monkeypatch)

    def slow_parse(content, max_pages=80):
        time.sleep(2.0)
        return "never used " * 50

    monkeypatch.setattr(cf, "_extract_pdf_text", slow_parse)
    monkeypatch.setattr(cf, "PDF_PARSE_TIMEOUT_S", 0.1)
    started = time.monotonic()
    result = rg._run_coroutine_bounded(lambda: cf._direct_http_fetch("https://agency.example/big.pdf"), 5)
    assert result == "Error: direct fallback PDF parse timed out"
    assert time.monotonic() - started < 1.5     # never waits for the 2 s parse thread


# ============================================================== knob plumbing

def _run_research_child(monkeypatch, tmp_path) -> dict:
    deerflow_dir = tmp_path / "deer-flow"
    deerflow_dir.mkdir()
    (deerflow_dir / "deerflow_research.py").write_text("# test entrypoint\n", encoding="utf-8")
    handoff_dir = tmp_path / "handoff"
    handoff_dir.mkdir()
    (handoff_dir / "research_report.md").write_text("research evidence " * 40, encoding="utf-8")
    captured: dict = {}

    class CompletedProcess:
        pid = 4321
        stdout: list = []

        @staticmethod
        def poll():
            return 0

        @staticmethod
        def wait(timeout=None):
            return 0

    def fake_popen(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return CompletedProcess()

    monkeypatch.setattr(po.Config, "DEERFLOW_DIR", str(deerflow_dir))
    monkeypatch.setattr(po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"))
    monkeypatch.setattr(po, "_sync_deerflow_bridge_if_stale", lambda _path: None)
    monkeypatch.setattr(po.subprocess, "Popen", fake_popen)
    po.DeerFlowResearchRunner.run("forecast question", str(handoff_dir),
                                  on_progress=lambda _pct, _message: None, timeout=10)
    return captured["env"]


@pytest.mark.parametrize("detection, timeout_s, expected", [
    (True, 150, ("true", "150")),
    (False, 0, ("false", "0")),
])
def test_research_runner_forwards_both_fetch_knobs_from_config(monkeypatch, tmp_path, detection, timeout_s,
                                                               expected):
    monkeypatch.setenv("RESEARCH_FETCH_SHELL_DETECTION", "ambient-value-must-not-win")
    monkeypatch.setenv("RESEARCH_FETCH_CALL_TIMEOUT_S", "999")
    monkeypatch.setattr(po.Config, "RESEARCH_FETCH_SHELL_DETECTION", detection)
    monkeypatch.setattr(po.Config, "RESEARCH_FETCH_CALL_TIMEOUT_S", timeout_s)
    env = _run_research_child(monkeypatch, tmp_path)
    assert (env["RESEARCH_FETCH_SHELL_DETECTION"], env["RESEARCH_FETCH_CALL_TIMEOUT_S"]) == expected
