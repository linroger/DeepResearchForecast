"""INFRA-9: finished pipeline runs leave nothing behind in the process-wide registries.

Covers the orchestrator thread / cancel-event registries, telemetry's active-run
registry, LLMMeter's per-run meters (after the final telemetry write) and the
per-run outage breakers, for two runs executed one after the other and two runs
executed concurrently. SimulationRunner registries are owned elsewhere and are
out of scope. Offline: the real ``_run`` drives a research_only pipeline whose
research child is faked; the fake meters one LLM call on the pipeline thread.
"""

from __future__ import annotations

import json
import os
import threading

import pytest

from app.config import Config
from app.services import pipeline_orchestrator as po
from app.utils import telemetry

REPORT = "# Research\n\n" + ("Capacity reached 176 GW in 2023 [S1]. " * 20) + "\n"
_WAIT_S = 30


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Point every artifact root the orchestrator resolves at tmp_path."""
    sims = str(tmp_path / "simulations")
    monkeypatch.setattr(Config, "PIPELINE_DATA_DIR", str(tmp_path / "pipelines"), raising=False)
    monkeypatch.setattr(Config, "UPLOAD_FOLDER", str(tmp_path / "uploads"), raising=False)
    monkeypatch.setattr(Config, "OASIS_SIMULATION_DATA_DIR", sims, raising=False)
    monkeypatch.setattr(po.SimulationRunner, "RUN_STATE_DIR", sims, raising=False)
    monkeypatch.setattr(po.ReportManager, "REPORTS_DIR", str(tmp_path / "reports"),
                        raising=False)
    monkeypatch.setattr(po, "_repo_git_sha", lambda: "gitsha")
    monkeypatch.setattr(po, "_deerflow_ref", lambda: None)
    monkeypatch.delenv("LLM_OUTAGE_HALT_CONSECUTIVE", raising=False)
    for name, value in {
        "RESEARCH_ENGINE": "v3",
        "RESEARCH_PARALLEL_TRACKS": 1,
        "DEERFLOW_RESEARCH_LANGUAGE": None,
        "REPORT_LINT": False,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
        "STAGE_SCORECARD_ENABLED": False,
        "LLM_OUTAGE_HALT_CONSECUTIVE": 10,  # every attempt registers an outage breaker
    }.items():
        monkeypatch.setattr(Config, name, value, raising=False)
    return tmp_path


def _registries(pipeline_id):
    """Which process-wide registries currently hold ``pipeline_id``."""
    with po._RUN_OUTAGE_LOCK:
        breaker = pipeline_id in po._RUN_OUTAGE_BREAKERS
    with telemetry.LLMMeter._lock:
        meter = pipeline_id in telemetry.LLMMeter._runs
    return {
        "threads": pipeline_id in po.PipelineOrchestrator._threads,
        "cancel_events": pipeline_id in po.PipelineOrchestrator._cancel_events,
        "active_runs": pipeline_id in telemetry.active_run_ids(),
        "llm_meter": meter,
        "outage_breakers": breaker,
    }


HELD = dict.fromkeys(("threads", "cancel_events", "active_runs", "llm_meter",
                      "outage_breakers"), True)
RELEASED = dict.fromkeys(HELD, False)


def _stub_research(monkeypatch, *, overlap=None, overrides=None):
    """Fake the research child: meter one LLM call, snapshot the registries mid-run.

    ``overlap`` is a Barrier the in-flight runs wait on twice, so every
    mid-run snapshot is taken while all of them are still running.
    """
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        **(overrides or {}),
    }.items():
        monkeypatch.setattr(po.PipelineOrchestrator, name, replacement)
    monkeypatch.setattr(po, "_finalize_research_contract", lambda handoff_dir, research: None)
    mid_run: dict[str, dict] = {}

    def fake_research(prompt, handoff_dir, **kwargs):
        telemetry.LLMMeter.record("fake", "fake-1", 100, 50, 1.0)
        pipeline_id = telemetry.get_run_context()[0]
        if overlap is not None:
            overlap.wait()
        mid_run[pipeline_id] = _registries(pipeline_id)
        if overlap is not None:
            overlap.wait()
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(REPORT)
        return {"report": REPORT, "report_path": path, "evidence_pack": None,
                "actor_dossier": "", "actors": None, "sources": None, "timeline": None,
                "exit_code": 0, "research_telemetry": {}}

    monkeypatch.setattr(po.DeerFlowResearchRunner, "run", staticmethod(fake_research))
    return mid_run


def _start():
    return po.PipelineOrchestrator.start("Will capacity exceed 250 GW by 2027?",
                                         mode="research_only").pipeline_id


def _wait(pipeline_id):
    """Join the pipeline thread; it deregisters itself as the last step of ``_run``."""
    thread = po.PipelineOrchestrator._threads.get(pipeline_id)
    if thread is not None:
        thread.join(timeout=_WAIT_S)
        assert not thread.is_alive(), f"{pipeline_id} did not finish"


def _assert_clean_after_completion(pipeline_ids, mid_run):
    for pipeline_id in pipeline_ids:
        persisted = po.PipelineManager.load(pipeline_id)
        assert persisted["status"] == "completed", persisted.get("error")
        # The registries really held the run while it was in flight ...
        assert mid_run[pipeline_id] == HELD
        # ... its usage was written out before the meter was reset ...
        with open(os.path.join(po.PipelineManager._dir(pipeline_id), "run_telemetry.json"),
                  encoding="utf-8") as handle:
            assert json.load(handle)["total"]["calls"] == 1
        # ... and nothing of it is left behind.
        assert _registries(pipeline_id) == RELEASED


def test_sequential_runs_leave_no_registry_entries(roots, monkeypatch):
    mid_run = _stub_research(monkeypatch)
    finished = []
    for _ in range(2):
        pipeline_id = _start()
        _wait(pipeline_id)
        finished.append(pipeline_id)
        # The first run is already fully released while the second one runs.
        _assert_clean_after_completion(finished, mid_run)
    assert telemetry.active_run_ids() == []


def test_concurrent_runs_leave_no_registry_entries(roots, monkeypatch):
    mid_run = _stub_research(monkeypatch, overlap=threading.Barrier(2, timeout=_WAIT_S))
    pipeline_ids = [_start(), _start()]
    for pipeline_id in pipeline_ids:
        _wait(pipeline_id)
    _assert_clean_after_completion(pipeline_ids, mid_run)
    assert telemetry.active_run_ids() == []


def test_failing_telemetry_finalization_still_releases_the_run(roots, monkeypatch):
    """A raise anywhere in the final telemetry block must not skip the meter reset.

    Before INFRA-9 the reset sat inside that block: the run kept its LLMMeter
    entry and its active-run registration for the life of the process, so every
    later single run saw two "active" runs and lost its fallback attribution.
    """
    def flush(self, state, *, final=False, extra=None):
        if final:
            raise OSError("disk full")

    mid_run = _stub_research(monkeypatch, overrides={"_flush_run_telemetry": flush})
    pipeline_id = _start()
    _wait(pipeline_id)
    assert po.PipelineManager.load(pipeline_id)["status"] == "completed"
    assert mid_run[pipeline_id] == HELD
    assert _registries(pipeline_id) == RELEASED
    assert telemetry.active_run_ids() == []
