"""Linear research engine (RESEARCH_ENGINE=linear): offline regressions.

Covers the two defects that made the opt-in engine unusable:

* its page fetch called the bridge's async LangChain ``web_fetch`` tool as a
  plain function, so every fetch failed;
* the default three-lane topology launched it as evidence-only lanes and a
  --synthesis-manifest child, modes it does not implement.

No network, no provider keys, no DeerFlow install.
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[2]
BRIDGE_DIR = REPO / "deerflow_bridge"
PAGE_TEXT = "Official filing: capacity reached 42 GW as of 2026-06-30. " * 12


def _load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def dr():
    return _load("deerflow_research_linear_engine_test",
                 BRIDGE_DIR / "deerflow_research.py")


@pytest.fixture
def cached_fetch_mod(monkeypatch):
    """The real bridge cached_fetch module, registered under its bare name."""
    module = _load("cached_fetch", BRIDGE_DIR / "cached_fetch.py")
    monkeypatch.setitem(sys.modules, "cached_fetch", module)
    return module


@pytest.fixture
def linear(dr, monkeypatch):
    # linear_research imports the bridge by its deployed bare module name.
    monkeypatch.setitem(sys.modules, "deerflow_research", dr)
    return _load("linear_research_under_test", BRIDGE_DIR / "linear_research.py")


class _Plog:
    def __init__(self) -> None:
        self.lines: list[tuple[str, str]] = []

    def write(self, kind: str, msg: str) -> None:
        self.lines.append((kind, msg))

    def close(self) -> None:
        pass


class _AsyncOnlyTool:
    """Shape of ``@tool`` over an ``async def`` in langchain-core 1.x.

    Not callable, no sync implementation; only ``ainvoke(dict)`` works.
    """

    def __init__(self, result: str) -> None:
        self.result = result
        self.inputs: list[dict] = []

    def invoke(self, _input, config=None, **_kw):  # noqa: ARG002
        raise NotImplementedError("StructuredTool does not support sync invocation.")

    async def ainvoke(self, tool_input, config=None, **_kw):  # noqa: ARG002
        self.inputs.append(dict(tool_input))
        await asyncio.sleep(0)
        return self.result


def _tools(linear, tmp_path):
    ledger = linear._SourceLedger(tmp_path, _Plog())
    return linear._AgentTools(ledger, threading.Semaphore(5)), ledger


# ---------------------------------------------------------------------------
# Page fetch
# ---------------------------------------------------------------------------

def test_fetch_drives_async_tool_through_ainvoke(
        linear, cached_fetch_mod, monkeypatch, tmp_path):
    tool = _AsyncOnlyTool(PAGE_TEXT)
    monkeypatch.setattr(cached_fetch_mod, "web_fetch_tool", tool)
    tools, ledger = _tools(linear, tmp_path)
    url = "https://www.sec.gov/filing/example"

    out = tools.fetch(url)

    assert tool.inputs == [{"url": url}]
    assert out.startswith("[S1] ")
    assert "capacity reached 42 GW" in out
    row = ledger.as_list()[0]
    assert row["url"] == url and row["fetched"] is True
    assert row["fetched_text_chars"] == len(PAGE_TEXT)

    # A second request is answered from the ledger, not re-fetched.
    again = tools.fetch(url)
    assert "already fetched earlier this run" in again
    assert len(tool.inputs) == 1


def test_fetch_works_when_caller_thread_runs_an_event_loop(
        linear, cached_fetch_mod, monkeypatch, tmp_path):
    tool = _AsyncOnlyTool(PAGE_TEXT)
    monkeypatch.setattr(cached_fetch_mod, "web_fetch_tool", tool)
    tools, ledger = _tools(linear, tmp_path)

    async def _inside_loop() -> str:
        return tools.fetch("https://example.org/report")

    out = asyncio.run(_inside_loop())

    assert out.startswith("[S1] ")
    assert ledger.as_list()[0]["fetched"] is True


@pytest.mark.parametrize("result", [
    "Error: Jina primary failed: ReadTimeout: " + "upstream timed out " * 20,
    json.dumps({
        "error": "research_budget_exhausted",
        "tool": "web_fetch",
        "url": "https://example.org/report",
        "message": "The shared fetch allowance for this run is exhausted. " * 4,
    }),
    json.dumps({
        "status": "already_available",
        "artifact_id": "fetch-123",
        "message": "This exact page was already returned in full earlier. " * 4,
    }),
    "404 Not Found. " + "The requested page could not be located. " * 10,
    "too short",
    "",
])
def test_fetch_does_not_cite_failure_or_control_results(
        linear, cached_fetch_mod, monkeypatch, tmp_path, result):
    monkeypatch.setattr(cached_fetch_mod, "web_fetch_tool", _AsyncOnlyTool(result))
    tools, ledger = _tools(linear, tmp_path)

    out = tools.fetch("https://example.org/report")

    assert json.loads(out) == {"error": "page empty or unreadable"}
    assert ledger.as_list()[0]["fetched"] is False


def test_fetch_reports_unavailable_tool_instead_of_raising(
        linear, cached_fetch_mod, monkeypatch, tmp_path):
    monkeypatch.setattr(cached_fetch_mod, "web_fetch_tool", None)
    tools, ledger = _tools(linear, tmp_path)

    out = tools.fetch("https://example.org/report")

    assert json.loads(out) == {"error": "fetch failed: RuntimeError"}
    assert ledger.as_list()[0]["fetched"] is False


def test_fetch_with_real_langchain_web_fetch_tool(
        linear, cached_fetch_mod, monkeypatch, tmp_path):
    """End to end through the real ``cached_fetch.web_fetch_tool`` object."""
    pytest.importorskip("langchain_core.tools")
    real_tool = cached_fetch_mod.web_fetch_tool
    assert real_tool is not None
    # The pre-fix call shape: a StructuredTool is not callable.
    with pytest.raises(TypeError):
        real_tool("https://example.org/report")

    seen: list[tuple[str, str]] = []

    async def fake_cached_fetch(url, fetch_fn, revisit_reason=""):  # noqa: ARG001
        seen.append((url, revisit_reason))
        return PAGE_TEXT

    # The tool body resolves ``cached_fetch`` from its module globals.
    monkeypatch.setattr(cached_fetch_mod, "cached_fetch", fake_cached_fetch)
    tools, ledger = _tools(linear, tmp_path)

    out = tools.fetch("https://example.org/report")

    assert seen == [("https://example.org/report", "")]
    assert out.startswith("[S1] ")
    assert ledger.as_list()[0]["fetched"] is True


# ---------------------------------------------------------------------------
# Dispatch: the linear engine runs only as a single full-mode lane
# ---------------------------------------------------------------------------

@pytest.fixture
def linear_stub(monkeypatch):
    calls: list[dict] = []
    stub = ModuleType("linear_research")

    def run(question, out_dir, args, meta, plog, write_meta):
        calls.append({"question": question, "out_dir": out_dir, "args": args,
                      "workflow_mode": meta.get("workflow_mode")})
        plog.close()
        return 0

    stub.run = run
    monkeypatch.setitem(sys.modules, "linear_research", stub)
    return calls


def _run_bridge_main(dr, monkeypatch, out_dir: Path, *extra: str) -> int:
    monkeypatch.setenv("RESEARCH_ENGINE", "linear")
    # main() writes this; register it so monkeypatch restores it afterwards.
    monkeypatch.setenv("RESEARCH_EVIDENCE_ONLY", "false")
    monkeypatch.delenv("DRF_RUNTIME_SKILL_SYNC_REQUIRED", raising=False)
    monkeypatch.delenv("DRF_RUNTIME_SKILL_SYNC", raising=False)
    monkeypatch.setattr(sys, "argv", [
        "deerflow_research.py", "--prompt", "Will X happen by 2030?",
        "--out-dir", str(out_dir), *extra,
    ])
    return dr.main()


def test_linear_engine_full_mode_dispatches_one_linear_run(
        dr, monkeypatch, tmp_path, linear_stub):
    rc = _run_bridge_main(dr, monkeypatch, tmp_path)

    assert rc == 0
    assert len(linear_stub) == 1
    call = linear_stub[0]
    assert call["question"] == "Will X happen by 2030?"
    assert call["workflow_mode"] == "full"
    assert call["args"].evidence_only is False
    assert call["args"].synthesis_manifest is None


@pytest.mark.parametrize("extra, flag", [
    (("--evidence-only",), "--evidence-only"),
    (("--synthesis-manifest", "evidence_synthesis_manifest.json"),
     "--synthesis-manifest"),
])
def test_linear_engine_refuses_lane_modes_loudly(
        dr, monkeypatch, tmp_path, linear_stub, capsys, extra, flag):
    rc = _run_bridge_main(dr, monkeypatch, tmp_path, *extra)

    assert rc == 3
    assert linear_stub == []  # the engine never started
    meta = json.loads((tmp_path / dr.META_FILENAME).read_text(encoding="utf-8"))
    assert meta["status"] == "failed"
    assert flag in meta["error"]
    assert "RESEARCH_PARALLEL_TRACKS=1" in meta["error"]
    assert flag in capsys.readouterr().err
    # No artifact the orchestrator could mistake for lane or report output.
    assert not (tmp_path / "evidence_pack.md").exists()
    assert not (tmp_path / dr.REPORT_FILENAME).exists()


def test_linear_unsupported_mode_helper(dr):
    full = SimpleNamespace(evidence_only=False, synthesis_manifest=None)
    assert dr._linear_engine_unsupported_mode(full) is None
    lane = SimpleNamespace(evidence_only=True, synthesis_manifest=None)
    assert "--evidence-only" in dr._linear_engine_unsupported_mode(lane)
    synth = SimpleNamespace(evidence_only=False, synthesis_manifest="m.json")
    assert "--synthesis-manifest" in dr._linear_engine_unsupported_mode(synth)


# ---------------------------------------------------------------------------
# Orchestrator: forces one full-mode lane for the linear engine
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def po():
    from app.services import pipeline_orchestrator
    return pipeline_orchestrator


@pytest.mark.parametrize("value", [None, "", "linear", " Linear ", "LINEAR",
                                   "agentic", "linear-v2"])
def test_orchestrator_and_bridge_engine_selectors_agree(dr, po, monkeypatch, value):
    if value is None:
        monkeypatch.delenv("RESEARCH_ENGINE", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_ENGINE", value)
    assert po.research_engine_is_linear() is dr._research_engine_is_linear()
    expected = value is not None and value.strip().lower() == "linear"
    assert po.research_engine_is_linear() is expected


class _StopAfterLaunch(RuntimeError):
    pass


def _drive_research_stage(po, monkeypatch, tmp_path, *, engine):
    """Run the real research stage until the first research launch."""
    if engine is None:
        monkeypatch.delenv("RESEARCH_ENGINE", raising=False)
    else:
        monkeypatch.setenv("RESEARCH_ENGINE", engine)
    monkeypatch.setattr(po.Config, "PIPELINE_DATA_DIR",
                        str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(po.Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"),
                        raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_PARALLEL_TRACKS", 3, raising=False)
    monkeypatch.setattr(po.Config, "RESEARCH_GLOBAL_SYNTHESIS", True, raising=False)
    for name in ("_start_heartbeat", "_init_telemetry_flush", "_write_run_manifest",
                 "_flush_run_telemetry"):
        monkeypatch.setattr(po.PipelineOrchestrator, name,
                            lambda self, *a, **k: None)

    launches: list[tuple[str, dict]] = []

    def fake_parallel(self, state, handoff_dir, upd, n_tracks):
        launches.append(("parallel", {"n_tracks": n_tracks}))
        raise _StopAfterLaunch("stop after parallel launch")

    def fake_runner_run(prompt, handoff_dir, **kwargs):
        launches.append(("single", kwargs))
        raise _StopAfterLaunch("stop after single-lane launch")

    monkeypatch.setattr(po.PipelineOrchestrator, "_run_parallel_research_tracks",
                        fake_parallel)
    monkeypatch.setattr(po.DeerFlowResearchRunner, "run",
                        staticmethod(fake_runner_run))

    pid = f"pipe_linear_{engine or 'default'}"
    po.PipelineManager.ensure_dirs(pid)
    state = po.PipelineState(pipeline_id=pid, prompt="Will X happen by 2030?",
                             mode="full", status="running")
    state.handoff_dir = po.PipelineManager.handoff_dir(pid)
    po.PipelineOrchestrator._run(state)
    assert "stop after" in (state.error or "")
    return launches


def test_research_stage_runs_linear_engine_as_one_full_mode_lane(
        po, monkeypatch, tmp_path):
    launches = _drive_research_stage(po, monkeypatch, tmp_path, engine="linear")

    assert [kind for kind, _ in launches] == ["single"]
    kwargs = launches[0][1]
    assert not kwargs.get("evidence_only")
    assert not kwargs.get("synthesis_manifest_path")
    assert kwargs.get("budget_lane_id") == "outer-track-1"


def test_research_stage_default_engine_keeps_three_lanes(po, monkeypatch, tmp_path):
    launches = _drive_research_stage(po, monkeypatch, tmp_path, engine=None)

    assert launches == [("parallel", {"n_tracks": 3})]
