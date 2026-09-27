"""Round-3 parent regressions: research lint on bridge-finalized reports.

P1 stopped ``_research_report_is_judge_bound`` from raising on single-lane runs
(no research contract manifest), which made the parent's research lint live on
every v3 run and every single-lane legacy run.  Lint then rewrote reports whose
citations, References and positional ``sources.json`` the bridge had already
finalized: it deleted a section lead restated by the executive summary together
with its ``[S#]`` (C16/C42), cut ``(... pass 12 ... [S3])`` parentheticals down
to a dangling ``)`` (C41) and turned legacy ``(S1)`` tier labels into citation
markers (C44).  Without a manifest lint is audit-only now, like the judge-bound
case; a manifest-owned (multi-lane) generation still adopts the cleaned text in
memory for its private finalization.

Offline and deterministic: the research child is faked, no network or LLM.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from app.services import pipeline_orchestrator as _po
from app.services.report_lint import lint_report

_LEAD = ("Installed data-centre capacity reached 176 GW at the end of 2023 "
         "according to the operator census")

# v3 shape: the executive summary (written last, placed first) restates the
# Market Baseline lead with a different marker, and a cited parenthetical
# carries "pass <number>" legislative wording.
V3_REPORT = f"""# Will global data-centre capacity exceed 250 GW by the end of 2027?

## Executive Summary

{_LEAD} [S1]. Federal support is uncertain (Congress must pass 12 appropriations bills by 30 September [S3]).

## Market Baseline

{_LEAD} [S2]. Operators added 26 GW in 2023 alone, the largest annual increase on record [S1].

## Grid Constraints

Connection queues now exceed 40 months in several regions, which caps near-term additions [S2]. Utilities have filed for accelerated transmission upgrades in the most congested regions [S1].

## References

- [S1] Operator census — https://census.example.org/a (tier 1; fetched)
- [S2] Grid operator note — https://grid.example.org/b (tier 1; fetched)
- [S3] Budget office brief — https://budget.example.gov/c (tier 2; search snippet)
"""

# Legacy shape: the legacy prompts teach "primary (S1) ... secondary (S2)" tier
# wording, which finalize_report_citations (validates only [S<n>]) leaves alone.
LEGACY_REPORT = """# Research report

## Evidence quality

The evidence base is dominated by primary (S1) filings; secondary (S2) press coverage and one low-tier (S4) blog were discounted. Capacity reached 176 GW in 2023 [S3].

## Outlook

Operators expect a further 40 GW of additions by 2026, driven by hyperscaler campus expansions [S1]. Grid connection queues remain the binding constraint on the pace of additions [S2]. Regulators are reviewing interconnection rules that could shorten the queues [S1].

## References

- [S1] Utility filing — https://ferc.example.gov/a
- [S2] Reuters story — https://news.example.com/b
- [S3] IEA capacity — https://iea.example.org/c
"""


def _markers(text: str) -> list[str]:
    return re.findall(r"\[S\d+\]", text.split("\n## References\n")[0])


def _drive_research_stage(monkeypatch, tmp_path, *, engine, tracks, report, manifest=None):
    """Run the real ``_run`` for a fresh research-only pipeline whose research
    layer is faked to publish ``report`` (plus ``manifest`` as the research
    contract manifest, when given).  Return the state, the published handoff
    report bytes and every report handed to ``_finalize_research_contract``."""
    for name, value in {
        "PIPELINE_DATA_DIR": str(tmp_path / "pipelines"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "RESEARCH_ENGINE": engine,
        "RESEARCH_PARALLEL_TRACKS": tracks,
        "DEERFLOW_RESEARCH_LANGUAGE": None,
        "REPORT_LINT": True,
        "CAST_RECONCILE": False,
        "EMBED_WARM_AT_RESEARCH": False,
        "PIPELINE_VIZ_ARTIFACTS": False,
    }.items():
        monkeypatch.setattr(_po.Config, name, value, raising=False)
    for name, replacement in {
        "_start_heartbeat": lambda self, state: None,
        "_init_telemetry_flush": lambda self, state: None,
        "_write_run_manifest": lambda self, state: None,
        "_update_manifest": lambda self, state, stage, **kwargs: None,
        "_record_research_telemetry": lambda self, state, value: None,
        "_maybe_warm_embedder": lambda self, state, actors: None,
        "_surface_research_quality": lambda self, state, handoff_dir: {},
        "_surface_forecast_confidence_penalty": lambda self, state, handoff_dir: None,
        "_flush_run_telemetry": lambda self, state, **kwargs: None,
    }.items():
        monkeypatch.setattr(_po.PipelineOrchestrator, name, replacement)
    finalized: list[str] = []
    monkeypatch.setattr(_po, "_finalize_research_contract",
                        lambda handoff_dir, research: finalized.append(research["report"]))

    def fake_single(prompt, handoff_dir, **kwargs):
        path = os.path.join(handoff_dir, "research_report.md")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(report)
        if manifest is not None:
            with open(_po._research_contract_path(handoff_dir), "w", encoding="utf-8") as fh:
                json.dump(manifest, fh)
        return {
            "report": report, "report_path": path,
            "evidence_pack": None, "actor_dossier": "", "actors": None,
            "sources": None, "timeline": None, "exit_code": 0,
            "research_telemetry": {"tokens_in": 0, "tokens_out": 0},
        }

    monkeypatch.setattr(_po.DeerFlowResearchRunner, "run", staticmethod(fake_single))
    monkeypatch.setattr(_po.PipelineOrchestrator, "_run_parallel_research_tracks",
                        lambda self, state, handoff_dir, upd, n_tracks:
                        fake_single(state.prompt, handoff_dir))

    pid = "pipe_r3lint_" + re.sub(r"\W", "_", tmp_path.name)
    _po.PipelineManager.ensure_dirs(pid)
    state = _po.PipelineState(
        pipeline_id=pid, prompt="Will global data-centre capacity exceed 250 GW by 2027?",
        mode="research_only", status="running", options={"research_language": None},
    )
    state.handoff_dir = _po.PipelineManager.handoff_dir(pid)
    os.makedirs(state.handoff_dir, exist_ok=True)
    _po.PipelineOrchestrator._run(state)
    assert state.status == "completed", state.error
    published = Path(state.handoff_dir, "research_report.md").read_bytes()
    return state, published, finalized


def test_lint_would_rewrite_both_fixture_reports():
    """Guard the fixtures: each exercises the lint rewrites the parent must not
    adopt on a single-lane report."""
    v3_cleaned, v3_rep = lint_report(V3_REPORT, "English", mode="research")
    assert v3_rep["duplicate_sentences_removed"] == 1
    assert "appropriations" not in v3_cleaned and "[S3]" not in _markers(v3_cleaned)
    assert v3_cleaned.count(_LEAD) == 1  # the Market Baseline lead is gone
    legacy_cleaned, legacy_rep = lint_report(LEGACY_REPORT, "English", mode="research")
    assert legacy_rep["citation_variants"] == 3
    assert _markers(legacy_cleaned) == ["[S1]", "[S2]", "[S4]", "[S3]", "[S1]", "[S2]", "[S1]"]


@pytest.mark.parametrize("engine,tracks,report", [
    ("v3", 3, V3_REPORT),          # v3 always forces a single outer lane
    ("legacy", 1, LEGACY_REPORT),  # legacy single-lane (RESEARCH_PARALLEL_TRACKS=1)
], ids=["v3", "legacy-single-lane"])
def test_single_lane_report_is_published_byte_identical_and_lint_is_audit_only(
        monkeypatch, tmp_path, engine, tracks, report):
    state, published, finalized = _drive_research_stage(
        monkeypatch, tmp_path, engine=engine, tracks=tracks, report=report)

    assert published == report.encode("utf-8")
    assert finalized == [report]  # the in-memory report downstream consumes
    lint = state.options["research_lint"]
    assert lint["audit_only"] is True and lint["changed"] is True
    assert "post_judge_mutation_suppressed" not in lint


def test_manifest_owned_multi_lane_report_still_adopts_lint_in_memory(monkeypatch, tmp_path):
    manifest = {"version": 1, "files": {"research_report.md": {"sha256": "0" * 64}}}
    state, published, finalized = _drive_research_stage(
        monkeypatch, tmp_path, engine="legacy", tracks=3, report=LEGACY_REPORT,
        manifest=manifest)

    cleaned, _ = lint_report(LEGACY_REPORT, "English", mode="research")
    assert finalized == [cleaned]  # sealed later in a private generation
    assert published == LEGACY_REPORT.encode("utf-8")  # never written in place
    assert state.options["research_lint"]["audit_only"] is False


def test_judge_bound_report_keeps_the_judged_bytes_and_records_audit_only(monkeypatch, tmp_path):
    manifest = {"version": 1, "files": {"research_report.md": {"sha256": "0" * 64},
                                        "research_report_judge.json": {"sha256": "1" * 64}}}
    state, published, finalized = _drive_research_stage(
        monkeypatch, tmp_path, engine="legacy", tracks=3, report=LEGACY_REPORT,
        manifest=manifest)

    assert finalized == [LEGACY_REPORT] and published == LEGACY_REPORT.encode("utf-8")
    lint = state.options["research_lint"]
    assert lint["audit_only"] is True and lint["post_judge_mutation_suppressed"] is True
