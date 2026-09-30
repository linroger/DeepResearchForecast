from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.export_demo_site_data as exporter
from app.services.graphiti_client import ApiError
from scripts.export_demo_site_data import (
    MARKDOWN_LINK_RE,
    RUNS,
    copy_markdown_assets,
    copy_report_assets,
    export_research_log,
    rebase_markdown_assets,
    rebase_report_assets,
    validate_retained_graph,
    validate_publishable_run,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_project_artifact(
    uploads: Path,
    *,
    project_id: str = "proj_ok",
    graph_id: str = "graph_ok",
) -> None:
    _write_json(
        uploads / "projects" / project_id / "project.json",
        {
            "project_id": project_id,
            "graph_id": graph_id,
            "ontology": {"entity_types": [], "edge_types": []},
            "analysis_summary": "Audited project",
        },
    )


def _completed_state(report_id: str = "report_ok") -> dict:
    return {
        "pipeline_id": "pipe_ok",
        "status": "completed",
        "project_id": "proj_ok",
        "report_id": report_id,
        "simulation_id": "sim_ok",
        "graph_id": "graph_ok",
        "stages": {
            name: {"status": "completed", "error": None}
            for name in ("research", "ontology", "graph", "prepare", "run", "report")
        },
    }


def _write_report_artifacts(
    uploads: Path,
    *,
    report_id: str = "report_ok",
    simulation_id: str = "sim_ok",
    graph_id: str = "graph_ok",
    publish_gate_passed: bool = True,
) -> dict:
    report_dir = uploads / "reports" / report_id
    report_dir.mkdir(parents=True)
    report_bytes = b"# Audited report\n"
    forecast_bytes = b'{"scenarios": []}\n'
    (report_dir / "full_report.md").write_bytes(report_bytes)
    (report_dir / "forecast.json").write_bytes(forecast_bytes)
    _write_json(
        report_dir / "meta.json",
        {
            "report_id": report_id,
            "simulation_id": simulation_id,
            "graph_id": graph_id,
            "status": "completed",
        },
    )
    audit = {
        "report_id": report_id,
        "read_only": True,
        "disk_matches_memory": True,
        "hard_passed": True,
        "publish_gate": {"passed": publish_gate_passed},
        "scenario_contract": {"valid": True},
        "markdown_sha256": hashlib.sha256(report_bytes).hexdigest(),
        "forecast_sha256": hashlib.sha256(forecast_bytes).hexdigest(),
    }
    _write_json(report_dir / "final_audit.json", audit)
    return audit


def _write_simulation_artifacts(
    uploads: Path,
    *,
    simulation_id: str = "sim_ok",
    project_id: str = "proj_ok",
    graph_id: str = "graph_ok",
    run_summary: dict | None = None,
) -> None:
    simulation_dir = uploads / "simulations" / simulation_id
    _write_json(
        simulation_dir / "state.json",
        {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": graph_id,
            "status": "completed",
            "error": None,
        },
    )
    _write_json(
        simulation_dir / "simulation_config.json",
        {
            "simulation_id": simulation_id,
            "project_id": project_id,
            "graph_id": graph_id,
        },
    )
    _write_json(
        simulation_dir / "run_state.json",
        {"simulation_id": simulation_id},
    )
    healthy_summary = {
        "simulation_id": simulation_id,
        "agent_count": 3,
        "total_actions": 12,
        "organic_action_count": 8,
        "rounds_executed": 4,
        "simulation_health": "ok",
    }
    if run_summary is not None:
        healthy_summary.update(run_summary)
    _write_json(simulation_dir / "run_summary.json", healthy_summary)


@pytest.fixture
def healthy_publishable_run(tmp_path: Path) -> tuple[Path, dict, dict]:
    state = _completed_state()
    _write_project_artifact(tmp_path)
    _write_simulation_artifacts(tmp_path)
    audit = _write_report_artifacts(tmp_path)
    return tmp_path, state, audit


def test_ev_demo_points_to_latest_verified_pipeline() -> None:
    assert RUNS["ev-2035"] == "pipe_91aaf91f6392"


def test_export_research_log_merges_root_and_tracks_with_exact_metadata(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    output = tmp_path / "site"
    track = handoff / "track_1"
    track.mkdir(parents=True)
    (handoff / "research_progress.log").write_text(
        "2026-01-01T00:00:02+00:00 [done] root\n",
        encoding="utf-8",
    )
    (track / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [init] opening\n"
        "2026-01-01T00:00:01+00:00 [tool] search\n",
        encoding="utf-8",
    )

    metadata = export_research_log(str(handoff), str(output))

    published = (output / "research_log.txt").read_text(encoding="utf-8").splitlines()
    assert len(published) == 3
    assert published[0].endswith("[track:1] [init] opening")
    assert published[-1].endswith("[done] root")
    assert metadata == {
        "line_count": 3,
        "source_count": 2,
        "complete": True,
        "event_fidelity": "summarized_progress_events",
    }


def test_export_research_log_retains_but_downgrades_legacy_artifact_without_sources(
    tmp_path: Path,
) -> None:
    handoff = tmp_path / "handoff"
    output = tmp_path / "site"
    handoff.mkdir()
    output.mkdir()
    retained = output / "research_log.txt"
    retained.write_text("old first\nold second\n", encoding="utf-8")

    metadata = export_research_log(
        str(handoff),
        str(output),
        retain_existing_if_missing=True,
    )

    assert retained.read_text(encoding="utf-8") == "old first\nold second\n"
    assert metadata == {
        "line_count": 2,
        "source_count": 0,
        "complete": False,
        "event_fidelity": "summarized_progress_events",
        "retained_legacy_artifact": True,
    }


def test_research_log_only_refresh_preserves_unrelated_demo_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = tmp_path / "uploads"
    output_root = tmp_path / "site"
    pipeline_id = "pipe_observable"
    handoff = uploads / "pipelines" / pipeline_id / "handoff"
    handoff.mkdir(parents=True)
    _write_json(
        uploads / "pipelines" / pipeline_id / "pipeline_state.json",
        {"pipeline_id": pipeline_id, "prompt": "Exact initial prompt"},
    )
    (handoff / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [done] complete\n",
        encoding="utf-8",
    )
    demo = output_root / "demo"
    demo.mkdir(parents=True)
    sentinel = demo / "verified-chart.png"
    sentinel.write_bytes(b"verified-chart-bytes")
    _write_json(
        demo / "meta.json",
        {
            "pipeline_id": pipeline_id,
            "prompt": "stale",
            "artifact_sha256": {"verified-chart.png": "sealed"},
        },
    )
    monkeypatch.setattr(exporter, "UPLOADS", str(uploads))
    monkeypatch.setattr(exporter, "OUT_ROOT", str(output_root))

    metadata = exporter.refresh_demo_research_log("demo", pipeline_id)

    refreshed = json.loads((demo / "meta.json").read_text(encoding="utf-8"))
    assert sentinel.read_bytes() == b"verified-chart-bytes"
    assert refreshed["artifact_sha256"]["verified-chart.png"] == "sealed"
    assert refreshed["prompt"] == "Exact initial prompt"
    assert refreshed["research_log"] == metadata
    assert refreshed["artifact_sha256"]["research_log.txt"] == hashlib.sha256(
        (demo / "research_log.txt").read_bytes()
    ).hexdigest()


def test_validate_publishable_run_accepts_healthy_fixture(
    healthy_publishable_run: tuple[Path, dict, dict],
) -> None:
    uploads, state, expected_audit = healthy_publishable_run

    audit = validate_publishable_run("pipe_ok", state, uploads=str(uploads))

    assert audit == expected_audit


def test_validate_publishable_run_requires_project_artifact(
    healthy_publishable_run: tuple[Path, dict, dict],
) -> None:
    uploads, state, _audit = healthy_publishable_run
    (uploads / "projects" / "proj_ok" / "project.json").unlink()

    with pytest.raises(RuntimeError, match="project artifact is missing or invalid"):
        validate_publishable_run("pipe_ok", state, uploads=str(uploads))


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        (
            "project_id",
            "proj_other",
            "project artifact project id does not match pipeline project id",
        ),
        (
            "graph_id",
            "graph_other",
            "project artifact graph id does not match pipeline graph id",
        ),
    ],
)
def test_validate_publishable_run_rejects_project_identity_disagreement(
    healthy_publishable_run: tuple[Path, dict, dict],
    field: str,
    value: str,
    expected_error: str,
) -> None:
    uploads, state, _audit = healthy_publishable_run
    project_path = uploads / "projects" / "proj_ok" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project[field] = value
    _write_json(project_path, project)

    with pytest.raises(RuntimeError, match=expected_error):
        validate_publishable_run("pipe_ok", state, uploads=str(uploads))


@pytest.mark.parametrize(
    ("relative_path", "updates", "expected_error"),
    [
        (
            "reports/report_ok/meta.json",
            {"simulation_id": "sim_other"},
            "report simulation id does not match pipeline simulation id",
        ),
        (
            "reports/report_ok/meta.json",
            {"graph_id": "graph_other"},
            "report graph id does not match pipeline graph id",
        ),
        (
            "reports/report_ok/meta.json",
            {"report_id": "report_other"},
            "report metadata report id does not match",
        ),
        (
            "simulations/sim_ok/state.json",
            {"simulation_id": "sim_other"},
            "simulation durable state id does not match pipeline/report simulation id",
        ),
        (
            "simulations/sim_ok/state.json",
            {"project_id": "proj_other"},
            "simulation durable state project id does not match pipeline project id",
        ),
        (
            "simulations/sim_ok/state.json",
            {"graph_id": "graph_other"},
            "simulation durable state graph id does not match pipeline/report graph id",
        ),
        (
            "simulations/sim_ok/simulation_config.json",
            {"simulation_id": "sim_other"},
            "simulation config id does not match pipeline/report simulation id",
        ),
        (
            "simulations/sim_ok/simulation_config.json",
            {"project_id": "proj_other"},
            "simulation config project id does not match pipeline project id",
        ),
        (
            "simulations/sim_ok/simulation_config.json",
            {"graph_id": "graph_other"},
            "simulation config graph id does not match pipeline/report graph id",
        ),
        (
            "simulations/sim_ok/run_state.json",
            {"simulation_id": "sim_other"},
            "run state simulation id does not match pipeline/report simulation id",
        ),
        (
            "simulations/sim_ok/run_summary.json",
            {"simulation_id": "sim_other"},
            "run summary simulation id does not match pipeline/report simulation id",
        ),
        (
            "reports/report_ok/final_audit.json",
            {"report_id": "report_other"},
            "final audit report id does not match",
        ),
        (
            "reports/report_ok/meta.json",
            {"status": "running"},
            "report status is 'running', not 'completed'",
        ),
        (
            "simulations/sim_ok/state.json",
            {"status": "ready"},
            "simulation durable state status is 'ready', not 'completed'",
        ),
    ],
)
def test_validate_publishable_run_rejects_identity_or_status_disagreement(
    healthy_publishable_run: tuple[Path, dict, dict],
    relative_path: str,
    updates: dict,
    expected_error: str,
) -> None:
    uploads, state, _audit = healthy_publishable_run
    artifact_path = uploads / relative_path
    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    payload.update(updates)
    _write_json(artifact_path, payload)

    with pytest.raises(RuntimeError, match=expected_error):
        validate_publishable_run("pipe_ok", state, uploads=str(uploads))


@pytest.mark.parametrize(
    ("field", "value", "expected_error"),
    [
        ("pipeline_id", None, "pipeline id does not match its state"),
        ("project_id", None, "project id is missing"),
    ],
)
def test_validate_publishable_run_rejects_missing_pipeline_identity(
    healthy_publishable_run: tuple[Path, dict, dict],
    field: str,
    value: str | None,
    expected_error: str,
) -> None:
    uploads, state, _audit = healthy_publishable_run
    state[field] = value

    with pytest.raises(RuntimeError, match=expected_error):
        validate_publishable_run("pipe_ok", state, uploads=str(uploads))


def test_validate_publishable_run_rejects_nonexistent_pipeline_simulation(
    tmp_path: Path,
) -> None:
    _write_report_artifacts(tmp_path)

    with pytest.raises(RuntimeError, match="pipeline simulation does not exist"):
        validate_publishable_run("pipe_ok", _completed_state(), uploads=str(tmp_path))


def test_validate_publishable_run_rejects_hollow_simulation_report_pair(
    tmp_path: Path,
) -> None:
    _write_simulation_artifacts(
        tmp_path,
        run_summary={
            "agent_count": 0,
            "total_actions": 0,
            "organic_action_count": 0,
            "rounds_executed": 0,
            "simulation_health": "hollow",
        },
    )
    _write_report_artifacts(tmp_path)

    with pytest.raises(RuntimeError) as exc_info:
        validate_publishable_run("pipe_ok", _completed_state(), uploads=str(tmp_path))

    message = str(exc_info.value)
    assert "run summary reports a hollow simulation" in message
    for field in (
        "agent_count",
        "rounds_executed",
        "total_actions",
        "organic_action_count",
    ):
        assert f"run summary {field}" in message


def test_validate_publishable_run_fails_closed_on_publish_gate(tmp_path: Path) -> None:
    _write_simulation_artifacts(tmp_path)
    _write_report_artifacts(tmp_path, publish_gate_passed=False)

    with pytest.raises(RuntimeError, match="publish gate did not pass"):
        validate_publishable_run("pipe_ok", _completed_state(), uploads=str(tmp_path))


def test_report_assets_are_copied_and_rebased_without_touching_external_images(
    tmp_path: Path,
) -> None:
    report_dir = tmp_path / "report"
    output_dir = tmp_path / "site"
    chart = report_dir / "charts" / "scenario.png"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"png")
    markdown = (
        "![Scenario](charts/scenario.png)\n"
        "![External](https://example.com/chart.png)\n"
    )

    copied = copy_report_assets(markdown, str(report_dir), str(output_dir))
    rebased = rebase_report_assets(markdown, "ev-2035")

    assert copied == ["charts/scenario.png"]
    assert (output_dir / "charts" / "scenario.png").read_bytes() == b"png"
    assert "![Scenario](demos/ev-2035/charts/scenario.png)" in rebased
    assert "![External](https://example.com/chart.png)" in rebased


def test_report_asset_copy_rejects_missing_referenced_files(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="referenced Markdown asset is missing"):
        copy_report_assets(
            "![Missing](charts/missing.png)\n",
            str(tmp_path / "report"),
            str(tmp_path / "site"),
        )


def test_dossier_images_and_links_use_an_isolated_asset_namespace(tmp_path: Path) -> None:
    source_dir = tmp_path / "handoff"
    output_dir = tmp_path / "site"
    (source_dir / "charts").mkdir(parents=True)
    (source_dir / "charts" / "timeline.png").write_bytes(b"png")
    (source_dir / "charts" / "timeline.html").write_text(
        "<html>  \n<body>ok</body>\t\n</html>\n",
        encoding="utf-8",
    )
    markdown = (
        "![Timeline](charts/timeline.png)\n"
        "[Interactive version](charts/timeline.html)\n"
    )

    copied = copy_markdown_assets(
        markdown,
        str(source_dir),
        str(output_dir),
        destination_namespace="research-charts",
    )
    rebased = rebase_markdown_assets(
        markdown,
        "ev-2035",
        destination_namespace="research-charts",
    )

    assert copied == [
        "research-charts/timeline.png",
        "research-charts/timeline.html",
    ]
    assert (output_dir / "research-charts" / "timeline.png").read_bytes() == b"png"
    assert (output_dir / "research-charts" / "timeline.html").read_text(encoding="utf-8") == (
        "<html>\n<body>ok</body>\n</html>\n"
    )
    assert "![Timeline](demos/ev-2035/research-charts/timeline.png)" in rebased
    assert "[Interactive version](demos/ev-2035/research-charts/timeline.html)" in rebased


@pytest.mark.parametrize(
    "target",
    [
        "charts/../../secret.png",
        "charts/%2e%2e/secret.png",
        "charts/chart name.png",
        "assets/unsupported.png",
        "/charts/absolute.png",
        r"charts\backslash.png",
    ],
)
def test_report_asset_parser_fails_closed_on_unsafe_local_targets(target: str) -> None:
    with pytest.raises(ValueError, match="unsafe local Markdown asset"):
        rebase_report_assets(f"![Unsafe]({target})\n", "ev-2035")


def test_report_asset_query_and_fragment_are_preserved_safely(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    output_dir = tmp_path / "site"
    chart = report_dir / "charts" / "scenario.png"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"png")
    markdown = "![Scenario](charts/scenario.png?v=20260713#probability)\n"

    copied = copy_report_assets(markdown, str(report_dir), str(output_dir))
    rebased = rebase_report_assets(markdown, "ev-2035")

    assert copied == ["charts/scenario.png"]
    assert (output_dir / "charts" / "scenario.png").is_file()
    assert (
        "![Scenario](demos/ev-2035/charts/scenario.png?v=20260713#probability)"
        in rebased
    )


def test_report_asset_quoted_markdown_title_is_preserved(tmp_path: Path) -> None:
    report_dir = tmp_path / "report"
    output_dir = tmp_path / "site"
    chart = report_dir / "charts" / "scenario.png"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"png")
    markdown = '[Scenario](charts/scenario.png "Probability chart")\n'

    copied = copy_report_assets(markdown, str(report_dir), str(output_dir))
    rebased = rebase_report_assets(markdown, "ev-2035")

    assert copied == ["charts/scenario.png"]
    assert (
        '[Scenario](demos/ev-2035/charts/scenario.png "Probability chart")'
        in rebased
    )


def test_strict_skip_graph_accepts_only_the_current_graph(tmp_path: Path) -> None:
    _write_json(tmp_path / "graph.json", {"graph_id": "graph_current"})

    validate_retained_graph(str(tmp_path), "graph_current")

    with pytest.raises(RuntimeError, match="stale graph.json"):
        validate_retained_graph(str(tmp_path), "graph_stale")


def test_publishable_graph_404_fails_closed_without_rebuild(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = tmp_path / "uploads"
    output_root = tmp_path / "site"
    state = _completed_state()
    _write_json(
        uploads / "pipelines" / "pipe_ok" / "pipeline_state.json",
        state,
    )
    handoff = uploads / "pipelines" / "pipe_ok" / "handoff"
    handoff.mkdir(parents=True)
    (handoff / "research_report.md").write_text(
        "# Audited dossier\n",
        encoding="utf-8",
    )
    (handoff / "research_progress.log").write_text(
        "2026-01-01T00:00:00+00:00 [done] research complete\n",
        encoding="utf-8",
    )
    _write_project_artifact(uploads)
    _write_simulation_artifacts(uploads)
    _write_report_artifacts(uploads)

    original_validator = exporter.validate_publishable_run
    monkeypatch.setattr(exporter, "UPLOADS", str(uploads))
    monkeypatch.setattr(exporter, "OUT_ROOT", str(output_root))
    monkeypatch.setattr(
        exporter,
        "validate_publishable_run",
        lambda pipeline_id, pipeline_state: original_validator(
            pipeline_id,
            pipeline_state,
            uploads=str(uploads),
        ),
    )

    rebuild_calls = []

    def _missing_graph(graph_id: str, graph_api: str | None = None) -> dict:
        assert graph_id == "graph_ok"
        assert graph_api is None
        raise ApiError("missing", status_code=404)

    def _forbidden_rebuild(key: str, out_dir: str) -> str:
        rebuild_calls.append((key, out_dir))
        return "graph_substitute"

    monkeypatch.setattr(exporter, "export_graph", _missing_graph)
    monkeypatch.setattr(exporter, "rebuild_graph", _forbidden_rebuild)

    with pytest.raises(
        RuntimeError,
        match=r"publication-bound graph 'graph_ok' is unavailable \(404\)",
    ):
        exporter.export_run(
            "test-run",
            "pipe_ok",
            skip_graph=False,
            require_publishable=True,
        )

    assert rebuild_calls == []
    assert not (output_root / "test-run" / "graph.json").exists()
    assert not (output_root / "test-run" / "meta.json").exists()


def test_published_ev_markdown_assets_resolve_and_match_manifest_hashes() -> None:
    docs_root = Path(__file__).resolve().parents[2] / "docs"
    demo_dir = docs_root / "demos" / "ev-2035"
    meta = json.loads((demo_dir / "meta.json").read_text(encoding="utf-8"))

    for relative_path, expected_sha256 in meta["artifact_sha256"].items():
        artifact = demo_dir / relative_path
        assert artifact.is_file(), relative_path
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_sha256

    expected_targets = {
        f"demos/ev-2035/{relative_path}"
        for relative_path in meta["dossier_assets"] + meta["report_assets"]
    }
    actual_targets = set()
    for markdown_name in ("dossier.md", "report.md"):
        markdown = (demo_dir / markdown_name).read_text(encoding="utf-8")
        for match in MARKDOWN_LINK_RE.finditer(markdown):
            target = match.group("target")
            if target.startswith("demos/ev-2035/"):
                actual_targets.add(target.split("?", 1)[0].split("#", 1)[0])

    assert actual_targets == expected_targets


# ───────────────────── language versions (report / dossier translations) ─────────────────────
def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_bilingual_report(uploads: Path, report_id: str = "report_lang") -> Path:
    report_dir = uploads / "reports" / report_id
    (report_dir / "charts").mkdir(parents=True)
    (report_dir / "charts" / "scenario.png").write_bytes(b"scenario-png")
    (report_dir / "charts" / "timeline.png").write_bytes(b"timeline-png")
    (report_dir / "full_report.md").write_text(
        "# Quantum outlook\n\n![Scenario](charts/scenario.png)\n\n"
        "The base case holds through the decade according to the committee.\n",
        encoding="utf-8",
    )
    (report_dir / "full_report.zh.md").write_text(
        "# 量子展望\n\n![情景](charts/scenario.png)\n\n![时间线](charts/timeline.png)\n\n"
        "基准情景在整个十年间保持成立。\n",
        encoding="utf-8",
    )
    return report_dir


def _publishable(monkeypatch: pytest.MonkeyPatch, uploads: Path, langs: set) -> list:
    from app.services.report_agent import ReportManager

    seen = []

    def _is_publishable(cls, report_id, lang=None):
        seen.append(ReportManager.REPORTS_DIR)
        return lang in langs

    monkeypatch.setattr(ReportManager, "is_publishable", classmethod(_is_publishable))
    monkeypatch.setattr(exporter, "UPLOADS", str(uploads))
    return seen


def test_report_export_publishes_the_audited_translation_with_shared_charts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = tmp_path / "uploads"
    _write_bilingual_report(uploads)
    seen = _publishable(monkeypatch, uploads, {"zh"})
    out = tmp_path / "site" / "quantum"
    out.mkdir(parents=True)

    assets, languages = exporter.export_report("quantum", "report_lang", str(out))

    assert languages == {"en": "report.md", "zh": "report.zh.md"}
    # One copy for both languages: the Chinese-only timeline chart survives too.
    assert assets == ["charts/scenario.png", "charts/timeline.png"]
    assert (out / "charts" / "timeline.png").read_bytes() == b"timeline-png"
    zh = (out / "report.zh.md").read_text(encoding="utf-8")
    assert "demos/quantum/charts/timeline.png" in zh
    assert "demos/quantum/charts/scenario.png" in (out / "report.md").read_text(encoding="utf-8")
    # The publication check reads the uploads being exported, not the app default.
    assert seen and all(path == str(uploads / "reports") for path in seen)


def test_unpublished_translation_is_withheld_and_a_stale_copy_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = tmp_path / "uploads"
    _write_bilingual_report(uploads)
    _publishable(monkeypatch, uploads, set())
    out = tmp_path / "site" / "quantum"
    out.mkdir(parents=True)
    (out / "report.zh.md").write_text("stale translation", encoding="utf-8")

    assets, languages = exporter.export_report("quantum", "report_lang", str(out))

    assert languages == {"en": "report.md"}
    assert assets == ["charts/scenario.png"]
    assert not (out / "report.zh.md").exists()


def test_dossier_translation_is_exported_only_for_the_current_source(tmp_path: Path) -> None:
    handoff = tmp_path / "handoff"
    handoff.mkdir()
    source = handoff / "research_report.md"
    source.write_text("# Research dossier\n\nEnglish findings.\n", encoding="utf-8")
    variant = handoff / "research_report.zh.md"
    variant.write_text("# 研究档案\n\n中文结论。\n", encoding="utf-8")
    _write_json(handoff / "research_report.translation.zh.json", {
        "status": "available", "available": True, "source_sha256": _sha(source),
    })
    _write_json(handoff / "research_report.final_audit.zh.json", {
        "hard_passed": True, "markdown_sha256": _sha(variant),
    })

    assert exporter.published_dossier_variants(str(handoff), "en") == {
        "zh": "# 研究档案\n\n中文结论。\n"
    }
    source.write_text("# Research dossier\n\nEdited after translating.\n", encoding="utf-8")
    assert exporter.published_dossier_variants(str(handoff), "en") == {}


def test_missing_chart_fails_without_deleting_the_published_charts(tmp_path: Path) -> None:
    site = tmp_path / "site"
    (site / "charts").mkdir(parents=True)
    (site / "charts" / "published.png").write_bytes(b"published")
    with pytest.raises(FileNotFoundError, match="referenced Markdown asset is missing"):
        copy_report_assets(
            "![Missing](charts/missing.png)\n", str(tmp_path / "report"), str(site)
        )
    assert (site / "charts" / "published.png").read_bytes() == b"published"


def test_refresh_keeps_a_published_chart_only_while_it_matches_the_manifest(
    tmp_path: Path,
) -> None:
    site = tmp_path / "site"
    (site / "charts").mkdir(parents=True)
    chart = site / "charts" / "dotplot.png"
    chart.write_bytes(b"sealed-chart")
    manifest = {"charts/dotplot.png": _sha(chart)}
    markdown = "![Dotplot](charts/dotplot.png)\n"
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    assert copy_report_assets(markdown, str(report_dir), str(site), manifest) == [
        "charts/dotplot.png"
    ]
    assert chart.read_bytes() == b"sealed-chart"

    chart.write_bytes(b"tampered")
    with pytest.raises(FileNotFoundError, match="referenced Markdown asset is missing"):
        copy_report_assets(markdown, str(report_dir), str(site), manifest)


def test_reports_only_refresh_adds_languages_and_preserves_other_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploads = tmp_path / "uploads"
    _write_bilingual_report(uploads)
    _publishable(monkeypatch, uploads, {"zh"})
    pipeline_id = "pipe_lang"
    _write_json(uploads / "pipelines" / pipeline_id / "pipeline_state.json", {
        "pipeline_id": pipeline_id, "report_id": "report_lang",
    })
    handoff = uploads / "pipelines" / pipeline_id / "handoff"
    handoff.mkdir(parents=True)
    (handoff / "research_report.md").write_text(
        "# Research dossier\n\nEnglish findings about the committee.\n", encoding="utf-8"
    )
    output_root = tmp_path / "site"
    demo = output_root / "quantum"
    demo.mkdir(parents=True)
    (demo / "graph.json").write_text('{"nodes": []}', encoding="utf-8")
    (demo / "meta.json").write_text(json.dumps({
        "pipeline_id": pipeline_id,
        "artifact_sha256": {"graph.json": "sealed-graph", "report.md": "old"},
    }, indent=1), encoding="utf-8")
    monkeypatch.setattr(exporter, "OUT_ROOT", str(output_root))

    exporter.refresh_demo_reports("quantum", pipeline_id)

    raw = (demo / "meta.json").read_text(encoding="utf-8")
    meta = json.loads(raw)
    assert raw.split("\n")[1].startswith(' "') and raw.endswith("}\n")
    assert meta["report_languages"] == {"en": "report.md", "zh": "report.zh.md"}
    assert list(meta["artifact_sha256"])[:2] == ["graph.json", "report.md"]
    assert meta["artifact_sha256"]["graph.json"] == "sealed-graph"
    for name in ("report.md", "report.zh.md", "charts/timeline.png"):
        assert meta["artifact_sha256"][name] == _sha(demo / name)
    assert (demo / "graph.json").read_text(encoding="utf-8") == '{"nodes": []}'
    # A dossier without a published translation is left exactly as published.
    assert "dossier_languages" not in meta and not (demo / "dossier.md").exists()

    # Once its translation is published, the dossier is exported in both languages.
    source = handoff / "research_report.md"
    variant = handoff / "research_report.zh.md"
    variant.write_text("# 研究档案\n\n关于委员会的中文结论。\n", encoding="utf-8")
    _write_json(handoff / "research_report.translation.zh.json", {
        "status": "available", "source_sha256": _sha(source),
    })
    _write_json(handoff / "research_report.final_audit.zh.json", {
        "hard_passed": True, "markdown_sha256": _sha(variant),
    })
    exporter.refresh_demo_reports("quantum", pipeline_id)
    meta = json.loads((demo / "meta.json").read_text(encoding="utf-8"))
    assert meta["dossier_languages"] == {"en": "dossier.md", "zh": "dossier.zh.md"}
    for name in ("dossier.md", "dossier.zh.md"):
        assert meta["artifact_sha256"][name] == _sha(demo / name)


def test_every_published_demo_bundle_matches_its_manifest() -> None:
    demos_root = Path(__file__).resolve().parents[2] / "docs" / "demos"
    checked = 0
    for meta_path in sorted(demos_root.glob("*/meta.json")):
        demo_dir = meta_path.parent
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        hashes = meta.get("artifact_sha256") or {}
        for relative_path, expected in hashes.items():
            artifact = demo_dir / relative_path
            assert artifact.is_file(), (demo_dir.name, relative_path)
            assert _sha(artifact) == expected, (demo_dir.name, relative_path)
        assets = set(meta.get("report_assets") or []) | set(meta.get("dossier_assets") or [])
        for kind in ("report", "dossier"):
            for lang, name in (meta.get(f"{kind}_languages") or {}).items():
                document = demo_dir / name
                assert document.is_file(), (demo_dir.name, lang, name)
                assert name in hashes, (demo_dir.name, name)
                for match in MARKDOWN_LINK_RE.finditer(document.read_text(encoding="utf-8")):
                    target = match.group("target").split("?", 1)[0].split("#", 1)[0]
                    prefix = f"demos/{demo_dir.name}/"
                    if target.startswith(prefix):
                        local = target[len(prefix):].split(" ", 1)[0]
                        assert local in assets, (demo_dir.name, name, local)
                        assert (demo_dir / local).is_file(), (demo_dir.name, local)
                checked += 1
    assert checked, "no demo declares a language map"
