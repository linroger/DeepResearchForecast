"""Regression tests for the postprocessed research contract boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from app.services import pipeline_orchestrator as po


def _write_generation(
    folder: Path,
    *,
    report: str,
    actors: dict | None = None,
    sources: list[dict] | None = None,
) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research_report.md").write_text(report, encoding="utf-8")
    (folder / "meta.json").write_text(
        json.dumps({"producer": "global-synthesis"}), encoding="utf-8"
    )
    if actors is not None:
        (folder / "actors.json").write_text(
            json.dumps(actors), encoding="utf-8"
        )
    if sources is not None:
        (folder / "sources.json").write_text(
            json.dumps(sources), encoding="utf-8"
        )


def _write_judged_generation(
    folder: Path,
    *,
    verdict: str = "PASS",
    summary_passed: bool | None = None,
    corrupt_prose_hash: bool = False,
) -> str:
    prose = "# Judged dossier\n\n" + "sourced forecast evidence " * 60
    report = prose + "\n## Visual Annex\n\n![Chart](charts/chart.png)\n"
    prose_hash = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    if summary_passed is None:
        summary_passed = verdict == "PASS"
    scores = dict.fromkeys(po._RESEARCH_JUDGE_DIMS, 5)
    judge = {
        "verdict": verdict,
        "scores": scores,
        "gaps": [] if verdict == "PASS" else ["remaining gap"],
        "_judge_input": {
            "report_chars": len(prose),
            "input_chars": len(prose),
            "input_sha256": prose_hash,
            "truncated": False,
        },
        "_judged_prose": {
            "sha256": "0" * 64 if corrupt_prose_hash else prose_hash,
            "chars": len(prose),
            "stage": "global-synthesis-final",
            "scope": "llm-prose",
        },
    }
    summary = {
        "verdict": verdict,
        "scores": scores,
        "passed": summary_passed,
        "judged_prose_sha256": prose_hash,
        "judged_prose_chars": len(prose),
        "judge_scope": "llm-prose",
        "stage": "global-synthesis-final",
    }
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "research_report.md").write_text(report, encoding="utf-8")
    (folder / "research_report_judge.json").write_text(
        json.dumps(judge), encoding="utf-8"
    )
    (folder / "meta.json").write_text(
        json.dumps({
            "depth": "deep",
            "status": "completed",
            "research_report_judge": summary,
            "global_synthesis_judge": summary,
        }),
        encoding="utf-8",
    )
    return report


def test_deep_research_contract_requires_complete_exact_judge(tmp_path):
    handoff = tmp_path / "handoff"
    source = tmp_path / "source"
    _write_generation(
        source,
        report="# Deep dossier\n\n" + "evidence " * 100,
    )
    (source / "meta.json").write_text(
        json.dumps({"depth": "deep", "status": "completed"}),
        encoding="utf-8",
    )

    with pytest.raises(
        RuntimeError, match="judge_required_artifact_missing"
    ):
        po._promote_research_contract(str(source), str(handoff))
    assert not (handoff / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_research_contract_accepts_exact_judged_prefix_and_deterministic_annex(
    tmp_path,
):
    handoff = tmp_path / "handoff"
    source = tmp_path / "source"
    report = _write_judged_generation(source)

    po._promote_research_contract(str(source), str(handoff))

    assert po._validate_research_contract(str(handoff)) is True
    assert (handoff / "research_report.md").read_text(encoding="utf-8") == report


def test_research_contract_accepts_honest_exact_fail_scorecard(tmp_path):
    handoff = tmp_path / "handoff"
    source = tmp_path / "source"
    _write_judged_generation(source, verdict="FAIL", summary_passed=False)

    po._promote_research_contract(str(source), str(handoff))

    assert po._validate_research_contract(str(handoff)) is True


@pytest.mark.parametrize(
    ("verdict", "summary_passed", "corrupt_prose_hash"),
    [
        ("FAIL", True, False),
        ("PASS", True, True),
    ],
)
def test_research_contract_rejects_inconsistent_or_unbound_judge(
    tmp_path, verdict, summary_passed, corrupt_prose_hash
):
    handoff = tmp_path / "handoff"
    source = tmp_path / "source"
    _write_judged_generation(
        source,
        verdict=verdict,
        summary_passed=summary_passed,
        corrupt_prose_hash=corrupt_prose_hash,
    )

    expected = (
        "judge_meta_summary_mismatch"
        if verdict == "FAIL"
        else "judge_prose_hash_mismatch"
    )
    with pytest.raises(RuntimeError, match=expected):
        po._promote_research_contract(str(source), str(handoff))
    assert not (handoff / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_finalization_seals_lint_cast_and_effective_sources_together(tmp_path):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    original_report = "# Producer dossier\n\n" + "original evidence " * 60
    original_actors = {
        "actors": [{"name": "Actor A"}, {"name": "Actor A Inc."}],
        "relationships": [],
    }
    _write_generation(
        producer,
        report=original_report,
        actors=original_actors,
        # The producer omitted the effective merged ledger.  Finalization must
        # persist the exact in-memory union before sealing the new generation.
        sources=None,
    )
    first = po._promote_research_contract(str(producer), str(handoff))

    final_report = "# Final dossier\n\n" + "linted outcome evidence " * 60
    final_actors = {
        "actors": [{"name": "Actor A", "aliases": ["Actor A Inc."]}],
        "relationships": [],
    }
    final_sources = [{
        "url": "https://example.gov/evidence",
        "title": "Primary evidence",
        "tier": "S1",
    }]
    final_meta = {
        "producer": "global-synthesis",
        "research_budget": {"denials": 2},
    }

    # Sanctioned edits remain in memory while the producer root stays valid.
    assert po._validate_research_contract(str(handoff)) is True
    assert (handoff / "research_report.md").read_text() == original_report
    assert not (handoff / "sources.json").exists()

    finalized = po._finalize_research_contract(str(handoff), {
        "report": final_report,
        "actors": final_actors,
        "sources": final_sources,
        "meta": final_meta,
    })

    assert finalized is not None
    assert finalized["generation"] != first["generation"]
    assert po._validate_research_contract(str(handoff)) is True
    assert (handoff / "research_report.md").read_text() == final_report
    assert json.loads((handoff / "actors.json").read_text()) == final_actors
    assert json.loads((handoff / "sources.json").read_text()) == final_sources
    assert json.loads((handoff / "meta.json").read_text()) == final_meta
    assert finalized["files"]["research_report.md"]["sha256"] == (
        po._sha256_file(str(handoff / "research_report.md"))
    )
    assert finalized["files"]["actors.json"]["sha256"] == po._sha256_file(
        str(handoff / "actors.json")
    )
    assert finalized["files"]["sources.json"]["sha256"] == po._sha256_file(
        str(handoff / "sources.json")
    )
    assert not list(handoff.glob(".research-final-*"))
    assert not list(handoff.glob(".research-stage-*"))
    assert not list(handoff.glob(".research-rollback-*"))


def test_judge_bound_finalization_rejects_post_judge_report_mutation(tmp_path):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    original_report = _write_judged_generation(producer)
    original = po._promote_research_contract(str(producer), str(handoff))

    with pytest.raises(RuntimeError, match="post-judge research report mutation"):
        po._finalize_research_contract(str(handoff), {
            "report": original_report.replace("[Chart]", "[Chart linted]"),
            "actors": None,
            "sources": None,
            "meta": json.loads((handoff / "meta.json").read_text()),
        })

    assert po._validate_research_contract(str(handoff)) is True
    assert (handoff / "research_report.md").read_text() == original_report
    assert json.loads(
        (handoff / po._RESEARCH_CONTRACT_FILENAME).read_text()
    )["generation"] == original["generation"]


def test_judge_bound_finalization_can_seal_non_report_artifacts(tmp_path):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    report = _write_judged_generation(producer)
    po._promote_research_contract(str(producer), str(handoff))
    actors = {"actors": [{"name": "Bound Actor"}], "relationships": []}
    sources = [{"url": "https://example.gov/bound", "tier": "S1"}]
    meta = json.loads((handoff / "meta.json").read_text())
    meta["research_budget"] = {"denials": 3}

    po._finalize_research_contract(str(handoff), {
        "report": report,
        "actors": actors,
        "sources": sources,
        "meta": meta,
    })

    assert po._validate_research_contract(str(handoff)) is True
    assert (handoff / "research_report.md").read_text() == report
    assert json.loads((handoff / "actors.json").read_text()) == actors
    assert json.loads((handoff / "sources.json").read_text()) == sources


def test_unchanged_resume_keeps_existing_generation(tmp_path, monkeypatch):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    report = "# Stable dossier\n\n" + "stable evidence " * 60
    actors = {"actors": [{"name": "Stable"}], "relationships": []}
    sources = [{"url": "https://example.gov/stable"}]
    _write_generation(
        producer, report=report, actors=actors, sources=sources
    )
    original = po._promote_research_contract(str(producer), str(handoff))
    monkeypatch.setattr(
        po.tempfile,
        "mkdtemp",
        lambda *args, **kwargs: pytest.fail(
            "unchanged resume should not stage or recopy a generation"
        ),
    )

    finalized = po._finalize_research_contract(str(handoff), {
        "report": report,
        "actors": actors,
        "sources": sources,
        "meta": {"producer": "global-synthesis"},
    })

    assert finalized == original
    assert po._validate_research_contract(str(handoff)) is True


def test_budget_quality_patch_waits_for_atomic_contract_finalization(
    tmp_path, monkeypatch
):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    report = "# Budget dossier\n\n" + "budget evidence " * 60
    actors = {"actors": [{"name": "Budget Actor"}], "relationships": []}
    sources = [{"url": "https://example.gov/budget"}]
    _write_generation(
        producer, report=report, actors=actors, sources=sources
    )
    (producer / "meta.json").write_text(json.dumps({
        "producer": "global-synthesis",
        "research_quality": {"score": 0.9, "degraded": False},
    }), encoding="utf-8")
    po._promote_research_contract(str(producer), str(handoff))
    (handoff / "research_budget.json").write_text(json.dumps({
        "degraded": False,
        "global": {"attempts": 2, "denied_search_global": 1},
    }), encoding="utf-8")
    original_meta = (handoff / "meta.json").read_text()
    state = po.PipelineState(
        pipeline_id="pipe-budget-finalize", prompt="x", handoff_dir=str(handoff)
    )
    monkeypatch.setattr(
        po.PipelineManager, "save", classmethod(lambda cls, value: None)
    )

    final_meta = po.PipelineOrchestrator._surface_research_quality(
        None, state, str(handoff)
    )

    assert isinstance(final_meta, dict)
    assert final_meta["research_quality"]["degraded"] is True
    # Surface telemetry must not invalidate the currently published contract.
    assert (handoff / "meta.json").read_text() == original_meta
    assert po._validate_research_contract(str(handoff)) is True

    po._finalize_research_contract(str(handoff), {
        "report": report,
        "actors": actors,
        "sources": sources,
        "meta": final_meta,
    })

    assert json.loads((handoff / "meta.json").read_text()) == final_meta
    assert po._validate_research_contract(str(handoff)) is True


def test_finalization_install_failure_restores_prior_valid_generation(
    tmp_path, monkeypatch
):
    handoff = tmp_path / "handoff"
    producer = tmp_path / "producer"
    original_report = "# Producer dossier\n\n" + "stable evidence " * 60
    original_actors = {"actors": [{"name": "Original"}], "relationships": []}
    original_sources = [{"url": "https://example.gov/original"}]
    _write_generation(
        producer,
        report=original_report,
        actors=original_actors,
        sources=original_sources,
    )
    po._promote_research_contract(str(producer), str(handoff))
    original_manifest = (handoff / po._RESEARCH_CONTRACT_FILENAME).read_text()
    real_replace = po.os.replace

    def fail_during_final_install(src, dst):
        if (
            ".research-stage-" in str(src)
            and str(src).endswith("actors.json")
            and Path(dst) == handoff / "actors.json"
        ):
            raise OSError("simulated final contract install failure")
        return real_replace(src, dst)

    monkeypatch.setattr(po.os, "replace", fail_during_final_install)

    with pytest.raises(OSError, match="final contract install failure"):
        po._finalize_research_contract(str(handoff), {
            "report": "# Final dossier\n\n" + "new evidence " * 60,
            "actors": {"actors": [{"name": "Final"}], "relationships": []},
            "sources": [{"url": "https://example.gov/final"}],
        })

    assert (handoff / "research_report.md").read_text() == original_report
    assert json.loads((handoff / "actors.json").read_text()) == original_actors
    assert json.loads((handoff / "sources.json").read_text()) == original_sources
    assert (handoff / po._RESEARCH_CONTRACT_FILENAME).read_text() == original_manifest
    assert po._validate_research_contract(str(handoff)) is True
    assert not list(handoff.glob(".research-final-*"))
    assert not list(handoff.glob(".research-stage-*"))
    assert not list(handoff.glob(".research-rollback-*"))


def test_finalization_is_noop_for_legacy_unmanifested_handoff(tmp_path):
    handoff = tmp_path / "legacy"
    handoff.mkdir()
    original = "# Legacy dossier\n\n" + "legacy evidence " * 60
    (handoff / "research_report.md").write_text(original, encoding="utf-8")

    result = po._finalize_research_contract(str(handoff), {
        "report": "# Changed\n\n" + "changed evidence " * 60,
        "actors": None,
        "sources": None,
    })

    assert result is None
    assert (handoff / "research_report.md").read_text() == original
    assert not (handoff / po._RESEARCH_CONTRACT_FILENAME).exists()


def test_research_data_directory_pins_config_style_parent_pair(tmp_path):
    # Config joins roots as <app>/../uploads, so runtime handoff paths carry a
    # benign lexical parent pair; pinning must resolve it against the pinned
    # parent instead of failing, and must match the kernel-resolved target.
    uploads = tmp_path / "uploads" / "pipelines" / "pipe_x" / "handoff"
    uploads.mkdir(parents=True)
    (tmp_path / "app").mkdir()
    config_style = os.path.join(str(tmp_path / "app"), "..", str(uploads.relative_to(tmp_path)))

    fd = po._research_data_directory(config_style)
    assert fd >= 0
    os.close(fd)
    assert os.path.samefile(config_style, os.path.realpath(config_style))

    fresh = tmp_path / "uploads" / "pipelines" / "pipe_y" / "handoff"
    fresh_style = os.path.join(str(tmp_path / "app"), "..", str(fresh.relative_to(tmp_path)))
    fd = po._research_data_directory(fresh_style, create=True)
    assert fd >= 0
    os.close(fd)
    assert fresh.is_dir()

    with pytest.raises(ValueError, match="parent traversal"):
        po._research_data_directory("handoff/../../elsewhere")

    # A symlink hiding inside link/.. would resolve outside its lexical parent;
    # the pinned walk must refuse it even though normalization would collapse it.
    elsewhere = tmp_path / "elsewhere"
    (elsewhere / "nested").mkdir(parents=True)
    base = tmp_path / "base"
    base.mkdir()
    (base / "link").symlink_to(elsewhere / "nested", target_is_directory=True)
    with pytest.raises(ValueError, match="parent traversal"):
        po._research_data_directory(str(base) + "/link/../target")
