#!/usr/bin/env python3
"""Export full pipeline artifacts for the live demo site (docs/demos/<run>/).

For each showcased run this dumps every stage of the workflow:
    research_log.txt   deep-research console log (stage 1)
    dossier.md         research brief (stage 1 output)
    actors.json        researched actor profiles (if extracted)
    sources.json       cited web sources (if extracted)
    ontology.json      entity/edge types + analysis summary (stage 2)
    graph.json         Zep knowledge-graph nodes + edges (stage 3)
    forum.json         simulated Twitter/Reddit feed from actions.jsonl (stage 5)
    report.md          final forecast report (stage 6), placeholder sections stripped
    meta.json          prompt, dates, rounds, persona count

Graph export hits the Zep API (read-only) and respects the same 429
retry-after handling as the app. Use --skip-graph to re-export everything
else without network calls.

Language variants: a report or research dossier that has a published translation
(report: the variant passes the publication audit; dossier: its translation status is
"available" for the current source bytes) is exported beside the primary as
report.<lang>.md / dossier.<lang>.md, and meta.json maps each language to its file
(``report_languages`` / ``dossier_languages``).

Usage:
    cd backend && uv run python scripts/export_demo_site_data.py [--skip-graph] [--only RUN_KEY]
    cd backend && uv run python scripts/export_demo_site_data.py --only RUN_KEY --research-log-only
    cd backend && uv run python scripts/export_demo_site_data.py --only RUN_KEY --reports-only
    # read the graph through a running backend instead of opening the graph store
    cd backend && uv run python scripts/export_demo_site_data.py --only RUN_KEY \
        --graph-api http://127.0.0.1:5001
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from urllib.parse import unquote, urlsplit

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config  # noqa: E402
from app.services.research_progress import merged_research_progress_full  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
UPLOADS = os.path.join(ROOT, "backend", "uploads")
OUT_ROOT = os.path.join(ROOT, "docs", "demos")

# run key (used in site URLs) -> pipeline id
RUNS = {
    "us-ai-2030": "pipe_2a5b07f9f8c1",
    "ev-2035": "pipe_91aaf91f6392",
    "russia-ukraine": "pipe_8b47373016f1",
    "semiconductors-2030": "pipe_f01ed9fe06de",
    "memory-semi-2030": "pipe_e2egold02",
    "china-storage-2035": "pipe_764249df9c38",
    "us-iran-2026": "pipe_a90b338fdfa0",
    # MiniMax (minimax-m3) demo runs — added 2026-06-21
    "storage-semi-2028": "pipe_41522d5d9790",
    "cloud-2030": "pipe_85d91bafe6fd",
    "collision-decade-2031": "pipe_a335177097fb",
    # added 2026-07-04 — GRAPH-12 schema-echo-unwrap validation runs
    "us-trade-2028": "pipe_bf2bb3095d11",
    "us-midterms-2026": "pipe_aa0fb94abe92",
    # added 2026-07-16 — MiniMax run with additive decision-channel simulation,
    # forecast-data charts (no source-quality), and groupable metric trajectories
    "grid-storage-2040": "pipe_0e1b84d2682a",
    # added 2026-09-19 — first completed GLM-5.3 run (Chinese report, English variant)
    "datacenter-2030": "pipe_1ee2fae33f8c",
    # added 2026-09-29 — GLM-5.3 run with the per-round reply step; English report
    # with a published Chinese variant
    "quantum-2040": "pipe_6c4190b31f0b",
}
LANGUAGES = ("en", "zh")

PLACEHOLDER_MARKER = "本章节生成失败"
REQUIRED_STAGES = ("research", "ontology", "graph", "prepare", "run", "report")
RUN_SUMMARY_HEALTH_VALUES = frozenset(
    {"ok", "llm_degraded", "truncated", "errored", "hollow"}
)
MARKDOWN_LINK_RE = re.compile(
    r"(?P<prefix>!?\[[^\]\r\n]*\]\()(?P<target>[^)\r\n]*)(?P<suffix>\))"
)
MARKDOWN_TARGET_RE = re.compile(
    r'''^(?P<url><[^>\r\n]+>|[^\s\r\n]+)(?P<title>\s+(?:"[^"\r\n]*"|'[^'\r\n]*'))?$'''
)


def _read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_research_log(
    handoff_dir: str, output_dir: str, *, retain_existing_if_missing: bool = False,
) -> dict:
    """Publish the complete canonical recorded root/track/attempt history.

    A provenance-only refresh is strict. The broad legacy demo exporter may,
    however, encounter an old pipeline whose source progress logs have already
    been garbage-collected. In that case it can retain a pre-existing published
    log, but must explicitly downgrade ``complete`` instead of claiming that the
    retained bytes were re-verified against canonical sources.
    """
    snapshot = merged_research_progress_full(handoff_dir)
    if snapshot.source_count == 0:
        retained_path = os.path.join(output_dir, "research_log.txt")
        if retain_existing_if_missing and os.path.isfile(retained_path):
            with open(retained_path, encoding="utf-8") as handle:
                retained_lines = handle.read().splitlines()
            return {
                "line_count": len(retained_lines),
                "source_count": 0,
                "complete": False,
                "event_fidelity": "summarized_progress_events",
                "retained_legacy_artifact": True,
            }
        raise RuntimeError("no research progress logs found for static export")
    os.makedirs(output_dir, exist_ok=True)
    rendered = "\n".join(snapshot.lines)
    if rendered:
        rendered += "\n"
    with open(os.path.join(output_dir, "research_log.txt"), "w", encoding="utf-8") as f:
        f.write(rendered)
    return {
        "line_count": len(snapshot.lines),
        "source_count": snapshot.source_count,
        "complete": True,
        "event_fidelity": "summarized_progress_events",
    }


def refresh_demo_research_log(
    key: str, pipeline_id: str, *, require_publishable: bool = False,
) -> dict:
    """Refresh prompt/log provenance without regenerating unrelated demo assets."""
    state = _read_json(os.path.join(UPLOADS, "pipelines", pipeline_id, "pipeline_state.json"))
    if not isinstance(state, dict):
        raise RuntimeError(f"pipeline state missing for {pipeline_id}")
    if require_publishable:
        validate_publishable_run(pipeline_id, state)

    output_dir = os.path.join(OUT_ROOT, key)
    metadata_path = os.path.join(output_dir, "meta.json")
    metadata = _read_json(metadata_path)
    if not isinstance(metadata, dict):
        raise RuntimeError(f"demo metadata missing for {key}")
    if metadata.get("pipeline_id") != pipeline_id:
        raise RuntimeError(
            f"demo metadata pipeline id {metadata.get('pipeline_id')!r} does not match {pipeline_id!r}"
        )

    log_metadata = export_research_log(
        os.path.join(UPLOADS, "pipelines", pipeline_id, "handoff"),
        output_dir,
    )
    metadata["prompt"] = state.get("prompt", "")
    metadata["research_log"] = log_metadata
    artifact_sha256 = metadata.get("artifact_sha256")
    if not isinstance(artifact_sha256, dict):
        artifact_sha256 = {}
        metadata["artifact_sha256"] = artifact_sha256
    artifact_sha256["research_log.txt"] = _sha256_file(
        os.path.join(output_dir, "research_log.txt")
    )
    # The tracked demo metadata is human-reviewed and conventionally uses a
    # two-space indent. Preserve that presentation so a provenance-only refresh
    # does not create a whole-file formatting diff.
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return log_metadata


def _load_bound_project(uploads: str, project_id: str, graph_id: str) -> dict:
    """Load the project artifact only when it matches the publication identity."""
    project_path = os.path.join(uploads, "projects", project_id, "project.json")
    try:
        project = _read_json(project_path)
    except (OSError, ValueError, TypeError):
        project = None

    issues = []
    if not isinstance(project, dict):
        issues.append("project artifact is missing or invalid")
    else:
        if project.get("project_id") != project_id:
            issues.append(
                "project artifact project id does not match pipeline project id"
            )
        if project.get("graph_id") != graph_id:
            issues.append(
                "project artifact graph id does not match pipeline graph id"
            )

    if issues:
        raise RuntimeError("; ".join(issues))
    return project


def validate_publishable_run(pipeline_id: str, state: dict, uploads: str = UPLOADS) -> dict:
    """Fail closed unless a pipeline's immutable final artifacts are publishable."""
    issues = []
    if state.get("pipeline_id") != pipeline_id:
        issues.append("pipeline id does not match its state")
    if state.get("status") != "completed":
        issues.append(f"pipeline status is {state.get('status')!r}, not 'completed'")

    stages = state.get("stages") or {}
    for name in REQUIRED_STAGES:
        stage = stages.get(name) or {}
        if stage.get("status") != "completed" or stage.get("error"):
            issues.append(f"stage {name!r} is not cleanly completed")

    report_id = state.get("report_id")
    simulation_id = state.get("simulation_id")
    graph_id = state.get("graph_id")
    project_id = state.get("project_id")
    if not project_id:
        issues.append("project id is missing")
    if not report_id:
        issues.append("report id is missing")
    if not simulation_id:
        issues.append("simulation id is missing")
    if not graph_id:
        issues.append("graph id is missing")

    if project_id and graph_id:
        try:
            _load_bound_project(uploads, project_id, graph_id)
        except RuntimeError as exc:
            issues.append(str(exc))

    report_dir = os.path.join(uploads, "reports", str(report_id or ""))
    report_path = os.path.join(report_dir, "full_report.md")
    forecast_path = os.path.join(report_dir, "forecast.json")
    audit_path = os.path.join(report_dir, "final_audit.json")

    try:
        report_meta = _read_json(os.path.join(report_dir, "meta.json"))
    except (OSError, ValueError, TypeError):
        report_meta = None
    if not isinstance(report_meta, dict):
        issues.append("report metadata is missing or invalid")
    else:
        if report_meta.get("report_id") != report_id:
            issues.append("report metadata report id does not match")
        if report_meta.get("simulation_id") != simulation_id:
            issues.append("report simulation id does not match pipeline simulation id")
        if report_meta.get("graph_id") != graph_id:
            issues.append("report graph id does not match pipeline graph id")
        if report_meta.get("status") != "completed":
            issues.append(
                f"report status is {report_meta.get('status')!r}, not 'completed'"
            )

    simulation_dir = os.path.join(uploads, "simulations", str(simulation_id or ""))
    if simulation_id and not os.path.isdir(simulation_dir):
        issues.append("pipeline simulation does not exist")
    elif simulation_id:
        try:
            simulation_state = _read_json(os.path.join(simulation_dir, "state.json"))
        except (OSError, ValueError, TypeError):
            simulation_state = None
        if not isinstance(simulation_state, dict):
            issues.append("simulation durable state is missing or invalid")
        else:
            if simulation_state.get("simulation_id") != simulation_id:
                issues.append(
                    "simulation durable state id does not match "
                    "pipeline/report simulation id"
                )
            if simulation_state.get("project_id") != project_id:
                issues.append(
                    "simulation durable state project id does not match "
                    "pipeline project id"
                )
            if simulation_state.get("graph_id") != graph_id:
                issues.append(
                    "simulation durable state graph id does not match "
                    "pipeline/report graph id"
                )
            if simulation_state.get("status") != "completed":
                issues.append(
                    "simulation durable state status is "
                    f"{simulation_state.get('status')!r}, not 'completed'"
                )

        try:
            simulation_config = _read_json(
                os.path.join(simulation_dir, "simulation_config.json")
            )
        except (OSError, ValueError, TypeError):
            simulation_config = None
        if not isinstance(simulation_config, dict):
            issues.append("simulation config is missing or invalid")
        else:
            if simulation_config.get("simulation_id") != simulation_id:
                issues.append(
                    "simulation config id does not match pipeline/report simulation id"
                )
            if simulation_config.get("project_id") != project_id:
                issues.append(
                    "simulation config project id does not match pipeline project id"
                )
            if simulation_config.get("graph_id") != graph_id:
                issues.append(
                    "simulation config graph id does not match pipeline/report graph id"
                )

        try:
            run_state = _read_json(os.path.join(simulation_dir, "run_state.json"))
        except (OSError, ValueError, TypeError):
            run_state = None
        if not isinstance(run_state, dict):
            issues.append("run state is missing or invalid")
        elif run_state.get("simulation_id") != simulation_id:
            issues.append(
                "run state simulation id does not match pipeline/report simulation id"
            )

        try:
            run_summary = _read_json(os.path.join(simulation_dir, "run_summary.json"))
        except (OSError, ValueError, TypeError):
            run_summary = None
        if not isinstance(run_summary, dict):
            issues.append("run summary is missing or invalid")
        else:
            if run_summary.get("simulation_id") != simulation_id:
                issues.append(
                    "run summary simulation id does not match "
                    "pipeline/report simulation id"
                )
            simulation_health = run_summary.get("simulation_health")
            if simulation_health == "hollow":
                issues.append("run summary reports a hollow simulation")
            elif (
                not isinstance(simulation_health, str)
                or simulation_health not in RUN_SUMMARY_HEALTH_VALUES
            ):
                issues.append("run summary simulation_health is missing or invalid")
            for field in (
                "agent_count",
                "rounds_executed",
                "total_actions",
                "organic_action_count",
            ):
                value = run_summary.get(field)
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    issues.append(
                        f"run summary {field} is {value!r}, not a positive integer"
                    )

    audit = _read_json(audit_path)
    if not isinstance(audit, dict):
        issues.append("final read-only audit is missing or invalid")
        audit = {}
    else:
        if audit.get("report_id") != report_id:
            issues.append("final audit report id does not match")
        if audit.get("read_only") is not True:
            issues.append("final audit is not read-only")
        if audit.get("disk_matches_memory") is not True:
            issues.append("final audit did not prove disk/memory parity")
        if audit.get("hard_passed") is not True:
            issues.append("hard publication gate did not pass")
        if (audit.get("publish_gate") or {}).get("passed") is not True:
            issues.append("publish gate did not pass")
        if (audit.get("scenario_contract") or {}).get("valid") is not True:
            issues.append("scenario contract did not pass")

    for label, path, expected in (
        ("report", report_path, audit.get("markdown_sha256")),
        ("forecast", forecast_path, audit.get("forecast_sha256")),
    ):
        if not os.path.isfile(path):
            issues.append(f"{label} artifact is missing")
        elif not expected:
            issues.append(f"{label} audit hash is missing")
        elif _sha256_file(path) != expected:
            issues.append(f"{label} artifact hash does not match the final audit")

    if issues:
        raise RuntimeError(f"{pipeline_id} is not publishable: " + "; ".join(issues))
    return audit


def _validate_namespace(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9._-]+", value or ""):
        raise ValueError(f"unsafe {label}: {value!r}")
    return value


def _parse_local_markdown_target(target: str) -> tuple[str, str, str] | None:
    """Return (source path, URL suffix, optional title) for a safe local chart link."""
    raw = (target or "").strip()
    if not raw or raw.startswith("#"):
        return None
    target_match = MARKDOWN_TARGET_RE.fullmatch(raw)
    if target_match is None:
        if urlsplit(raw).scheme:
            return None
        raise ValueError(f"unsafe local Markdown asset: {target}")

    url = target_match.group("url")
    title = target_match.group("title") or ""
    if url.startswith("<") and url.endswith(">"):
        url = url[1:-1]
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc or url.startswith("//"):
        return None
    if any(char.isspace() for char in url):
        raise ValueError(f"unsafe local Markdown asset: {target}")

    decoded_path = unquote(parsed.path)
    if not re.fullmatch(r"charts/[A-Za-z0-9._-]+", decoded_path or ""):
        raise ValueError(f"unsafe local Markdown asset: {target}")
    suffix = (f"?{parsed.query}" if parsed.query else "") + (
        f"#{parsed.fragment}" if parsed.fragment else ""
    )
    return decoded_path, suffix, title


def _markdown_asset_paths(markdown: str) -> list[str]:
    paths = []
    seen = set()
    for match in MARKDOWN_LINK_RE.finditer(markdown or ""):
        parsed = _parse_local_markdown_target(match.group("target"))
        if parsed is None:
            continue
        path, _suffix, _title = parsed
        if path not in seen:
            paths.append(path)
            seen.add(path)
    return paths


def _copy_static_asset(source: str, destination: str) -> None:
    """Copy binary assets byte-for-byte and normalize generated HTML whitespace."""
    if os.path.splitext(source)[1].lower() != ".html":
        shutil.copyfile(source, destination)
        return
    with open(source, encoding="utf-8") as f:
        html = f.read()
    normalized = re.sub(r"[ \t]+(?=\r?$)", "", html, flags=re.MULTILINE)
    with open(destination, "w", encoding="utf-8") as f:
        f.write(normalized)


def copy_markdown_assets(
    markdown: str,
    source_dir: str,
    output_dir: str,
    destination_namespace: str,
    retained_sha256: dict | None = None,
) -> list[str]:
    """Copy all safe local chart links into one isolated static-site namespace.

    Every referenced asset is resolved before the namespace is replaced, so a
    missing chart fails the export without deleting the published ones.
    ``retained_sha256`` (the published manifest, for a refresh) keeps a published
    chart whose source file is gone, but only while its bytes match the manifest.
    """
    namespace = _validate_namespace(destination_namespace, "asset namespace")
    source_root = os.path.realpath(source_dir)
    plan = []
    for relative_path in _markdown_asset_paths(markdown):
        source = os.path.realpath(os.path.join(source_root, relative_path))
        if os.path.commonpath([source, source_root]) != source_root:
            raise ValueError(f"unsafe local Markdown asset: {relative_path}")
        output_relative = f"{namespace}/{os.path.basename(relative_path)}"
        published = os.path.join(output_dir, output_relative)
        expected = (retained_sha256 or {}).get(output_relative)
        if os.path.isfile(source):
            plan.append((output_relative, source))
        elif expected and os.path.isfile(published) and _sha256_file(published) == expected:
            plan.append((output_relative, published))
        else:
            raise FileNotFoundError(f"referenced Markdown asset is missing: {relative_path}")

    output_assets = os.path.join(output_dir, namespace)
    staging = output_assets + ".staging"
    if os.path.isdir(staging):
        shutil.rmtree(staging)
    for output_relative, source in plan:
        os.makedirs(staging, exist_ok=True)
        _copy_static_asset(source, os.path.join(staging, os.path.basename(output_relative)))
    if os.path.isdir(output_assets):
        shutil.rmtree(output_assets)
    if plan:
        os.replace(staging, output_assets)
    return [output_relative for output_relative, _source in plan]


def rebase_markdown_assets(
    markdown: str,
    run_key: str,
    destination_namespace: str,
) -> str:
    """Make local Markdown links resolve relative to docs/demo.html."""
    key = _validate_namespace(run_key, "run key")
    namespace = _validate_namespace(destination_namespace, "asset namespace")

    def _replace(match: re.Match) -> str:
        parsed = _parse_local_markdown_target(match.group("target"))
        if parsed is None:
            return match.group(0)
        path, suffix, title = parsed
        destination = f"demos/{key}/{namespace}/{os.path.basename(path)}{suffix}{title}"
        return f"{match.group('prefix')}{destination}{match.group('suffix')}"

    return MARKDOWN_LINK_RE.sub(_replace, markdown or "")


def copy_report_assets(
    markdown: str,
    report_dir: str,
    output_dir: str,
    retained_sha256: dict | None = None,
) -> list[str]:
    """Copy report-local chart assets, removing stale report charts."""
    return copy_markdown_assets(
        markdown,
        report_dir,
        output_dir,
        destination_namespace="charts",
        retained_sha256=retained_sha256,
    )


def rebase_report_assets(markdown: str, run_key: str) -> str:
    """Make fetched report assets resolve relative to docs/demo.html."""
    return rebase_markdown_assets(markdown, run_key, destination_namespace="charts")


def validate_retained_graph(output_dir: str, expected_graph_id: str) -> None:
    """Prevent strict --skip-graph exports from retaining another run's graph."""
    existing_graph = _read_json(os.path.join(output_dir, "graph.json")) or {}
    if existing_graph.get("graph_id") != expected_graph_id:
        raise RuntimeError(
            "--skip-graph cannot publish over stale graph.json "
            f"(expected {expected_graph_id!r}, found {existing_graph.get('graph_id')!r})"
        )


def strip_placeholder_sections(md: str) -> str:
    """Drop H2 sections whose entire body is a generation-failure placeholder."""
    parts = re.split(r"(?m)^(## .+)$", md)
    # parts: [prefix, h2, body, h2, body, ...]
    out = [parts[0]]
    for i in range(1, len(parts), 2):
        heading, body = parts[i], parts[i + 1] if i + 1 < len(parts) else ""
        stripped = body.strip()
        if PLACEHOLDER_MARKER in stripped and len(stripped) < 300:
            continue
        out.append(heading + body)
    return "".join(out)


def export_forum(sim_dir: str) -> dict:
    """Parse twitter/reddit actions.jsonl into a compact feed for the site."""
    feed = {}
    for plat in ("twitter", "reddit"):
        rows = []
        path = os.path.join(sim_dir, plat, "actions.jsonl")
        if not os.path.exists(path):
            feed[plat] = rows
            continue
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if e.get("event_type"):  # round_start / simulation_start markers
                    continue
                args = e.get("action_args") or {}
                content = args.get("content") or args.get("text") or ""
                rows.append({
                    "round": e.get("round"),
                    "agent": e.get("agent_name") or f"Agent_{e.get('agent_id')}",
                    "type": (e.get("action_type") or "").upper(),
                    "content": content,
                    "ok": bool(e.get("success", True)),
                })
        feed[plat] = rows
    return feed


def rebuild_graph(key: str, out_dir: str) -> str:
    """Re-create the run's knowledge graph on Zep from its saved dossier + ontology.

    Used when the original graph no longer exists on the Zep account (account
    rotation / retention). This re-runs the pipeline's stage-3 on identical
    inputs — same dossier text, same chunking, same ontology — so the exported
    graph is a faithful reconstruction of what the run built.
    """
    from app.services.graph_builder import GraphBuilderService
    from app.services.text_processor import TextProcessor

    dossier = open(os.path.join(out_dir, "dossier.md"), encoding="utf-8").read()
    ontology = _read_json(os.path.join(out_dir, "ontology.json")) or {}

    builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
    graph_id = builder.create_graph(name=f"demo_{key}")
    builder.set_ontology(graph_id, {
        "entity_types": ontology.get("entity_types", []),
        "edge_types": ontology.get("edge_types", []),
    })
    chunks = TextProcessor.split_text(dossier, Config.DEFAULT_CHUNK_SIZE, Config.DEFAULT_CHUNK_OVERLAP)
    print(f"   rebuilding graph for {key}: {len(chunks)} chunks -> {graph_id}")
    uuids = builder.add_text_batches(graph_id, chunks, batch_size=10,
                                     progress_callback=lambda m, r: None)
    builder._wait_for_episodes(uuids, lambda m, r: print(f"   … {m}", flush=True) if r in (0.0, 1.0) else None)
    return graph_id


def export_graph(graph_id: str, graph_api: str | None = None) -> dict:
    """Fetch nodes/edges and trim to what the site renderer needs.

    ``graph_api`` (e.g. http://127.0.0.1:5001) reads the graph through a running
    backend's /api/graph/data endpoint, so the export never opens the embedded
    graph store that the backend process owns.
    """
    if graph_api:
        import urllib.error
        import urllib.parse
        import urllib.request

        url = (
            graph_api.rstrip("/") + "/api/graph/data/"
            + urllib.parse.quote(graph_id, safe="") + "?full=true"
        )
        try:
            with urllib.request.urlopen(url, timeout=120) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"graph API returned HTTP {exc.code} for {graph_id}") from exc
        if not payload.get("success"):
            raise RuntimeError(f"graph API error for {graph_id}: {payload.get('error')}")
        data = payload.get("data") or {}
    else:
        from app.services.graph_builder import GraphBuilderService

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        data = builder.get_graph_data(graph_id)
    nodes = [{
        "id": n["uuid"],
        "name": n.get("name") or "",
        "labels": [l for l in (n.get("labels") or []) if l != "Entity"],
        "summary": (n.get("summary") or "")[:600],
    } for n in data.get("nodes", [])]
    node_ids = {n["id"] for n in nodes}
    links = [{
        "source": e.get("source_node_uuid"),
        "target": e.get("target_node_uuid"),
        "name": e.get("name") or "",
        "fact": (e.get("fact") or "")[:400],
    } for e in data.get("edges", [])
        if e.get("source_node_uuid") in node_ids and e.get("target_node_uuid") in node_ids]
    return {"nodes": nodes, "links": links}


def _markdown_language(markdown: str) -> str | None:
    """'en' / 'zh' for an English or Chinese report, else None."""
    from app.services.report_agent import ReportAgent

    source_lang, _target, _name = ReportAgent._detect_translation_target(markdown or "")
    return source_lang


def published_report_variants(
    report_id: str, report_dir: str, primary_lang: str | None,
) -> dict:
    """{lang: markdown} for report translations that pass the publication audit.

    Placeholder sections are stripped exactly like the primary report.  A variant
    that is not publishable (missing, failed or stale audit) is never exported.
    """
    from app.services.report_agent import ReportManager

    previous_root = ReportManager.REPORTS_DIR
    ReportManager.REPORTS_DIR = os.path.join(UPLOADS, "reports")
    try:
        variants = {}
        for lang in LANGUAGES:
            if lang == primary_lang:
                continue
            path = os.path.join(report_dir, f"full_report.{lang}.md")
            if not os.path.isfile(path) or not ReportManager.is_publishable(report_id, lang):
                continue
            with open(path, encoding="utf-8") as f:
                variants[lang] = strip_placeholder_sections(f.read())
        return variants
    finally:
        ReportManager.REPORTS_DIR = previous_root


def published_dossier_variants(handoff: str, primary_lang: str | None) -> dict:
    """{lang: markdown} for research-dossier translations bound to the current source.

    Requires the translation status "available" for the current research_report.md
    bytes and a hard-passed audit whose fingerprint matches the variant bytes.
    """
    source = os.path.join(handoff, "research_report.md")
    if not os.path.isfile(source):
        return {}
    source_sha = _sha256_file(source)
    variants = {}
    for lang in LANGUAGES:
        if lang == primary_lang:
            continue
        variant = os.path.join(handoff, f"research_report.{lang}.md")
        status = _read_json(os.path.join(handoff, f"research_report.translation.{lang}.json")) or {}
        audit = _read_json(os.path.join(handoff, f"research_report.final_audit.{lang}.json")) or {}
        if not (
            os.path.isfile(variant)
            and status.get("status") == "available"
            and status.get("source_sha256") == source_sha
            and audit.get("hard_passed") is True
            and audit.get("markdown_sha256") == _sha256_file(variant)
        ):
            continue
        with open(variant, encoding="utf-8") as f:
            variants[lang] = f.read()
    return variants


def _write_language_set(
    out: str,
    stem: str,
    primary_md: str,
    variants: dict,
    primary_lang: str | None,
) -> dict:
    """Write <stem>.md plus <stem>.<lang>.md; return {lang: file name}."""
    with open(os.path.join(out, f"{stem}.md"), "w", encoding="utf-8") as f:
        f.write(primary_md)
    languages = {primary_lang or "und": f"{stem}.md"}
    for lang, markdown in sorted(variants.items()):
        name = f"{stem}.{lang}.md"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(markdown)
        languages[lang] = name
    for lang in LANGUAGES:  # drop variants that are no longer published
        stale = os.path.join(out, f"{stem}.{lang}.md")
        if lang not in languages and os.path.isfile(stale):
            os.remove(stale)
    return languages


def export_dossier(
    key: str, handoff: str, out: str, retained_sha256: dict | None = None,
) -> tuple[list, dict]:
    """Export dossier.md (+ published translations) and their research charts."""
    with open(os.path.join(handoff, "research_report.md"), encoding="utf-8") as f:
        dossier_md = f.read()
    primary_lang = _markdown_language(dossier_md)
    variants = published_dossier_variants(handoff, primary_lang)
    # One copy for every language: the asset namespace is rebuilt from scratch, so
    # copying per language would delete the charts another language references.
    assets = copy_markdown_assets(
        "\n\n".join([dossier_md, *variants.values()]),
        handoff,
        out,
        destination_namespace="research-charts",
        retained_sha256=retained_sha256,
    )
    rebased = {
        lang: rebase_markdown_assets(markdown, key, destination_namespace="research-charts")
        for lang, markdown in variants.items()
    }
    languages = _write_language_set(
        out,
        "dossier",
        rebase_markdown_assets(dossier_md, key, destination_namespace="research-charts"),
        rebased,
        primary_lang,
    )
    return assets, languages


def export_report(
    key: str, report_id: str, out: str, retained_sha256: dict | None = None,
) -> tuple[list, dict]:
    """Export report.md (+ published translations) and their charts."""
    report_dir = os.path.join(UPLOADS, "reports", report_id)
    with open(os.path.join(report_dir, "full_report.md"), encoding="utf-8") as f:
        cleaned = strip_placeholder_sections(f.read())
    primary_lang = _markdown_language(cleaned)
    variants = published_report_variants(report_id, report_dir, primary_lang)
    assets = copy_report_assets(
        "\n\n".join([cleaned, *variants.values()]), report_dir, out, retained_sha256
    )
    languages = _write_language_set(
        out,
        "report",
        rebase_report_assets(cleaned, key),
        {lang: rebase_report_assets(markdown, key) for lang, markdown in variants.items()},
        primary_lang,
    )
    return assets, languages


def _publication_summary(audit) -> dict | None:
    if not isinstance(audit, dict):
        return None
    return {
        "hard_passed": audit.get("hard_passed"),
        "publish_passed": (audit.get("publish_gate") or {}).get("passed"),
        "scenario_contract_valid": (audit.get("scenario_contract") or {}).get("valid"),
        "citation_coverage": (audit.get("citation_grounding") or {}).get("resolved_coverage"),
        "semantic_citations_passed": (audit.get("semantic_citations") or {}).get("passed"),
        "markdown_sha256": audit.get("markdown_sha256"),
        "forecast_sha256": audit.get("forecast_sha256"),
    }


def refresh_demo_reports(key: str, pipeline_id: str) -> dict:
    """Refresh report/dossier text and their language variants only.

    Graph, forum, ontology, research log and actors stay exactly as published; the
    report (and a dossier that has a published translation) is re-exported from its
    current bytes together with every published translation, and meta.json records
    the language maps and the new hashes.  A translation that is no longer published
    is removed with its hash.
    """
    state = _read_json(os.path.join(UPLOADS, "pipelines", pipeline_id, "pipeline_state.json"))
    if not isinstance(state, dict):
        raise RuntimeError(f"pipeline state missing for {pipeline_id}")
    out = os.path.join(OUT_ROOT, key)
    metadata_path = os.path.join(out, "meta.json")
    metadata = _read_json(metadata_path)
    if not isinstance(metadata, dict):
        raise RuntimeError(f"demo metadata missing for {key}")
    if metadata.get("pipeline_id") != pipeline_id:
        raise RuntimeError(
            f"demo metadata pipeline id {metadata.get('pipeline_id')!r} does not match {pipeline_id!r}"
        )
    refreshed_prefixes = ["charts/", "report."]
    published = metadata.get("artifact_sha256") or {}
    report_assets, report_languages = export_report(key, state["report_id"], out, published)
    metadata["report_assets"] = report_assets
    metadata["report_languages"] = report_languages
    handoff = os.path.join(UPLOADS, "pipelines", pipeline_id, "handoff")
    source = os.path.join(handoff, "research_report.md")
    dossier_variants = {}
    if os.path.isfile(source):
        with open(source, encoding="utf-8") as f:
            dossier_variants = published_dossier_variants(handoff, _markdown_language(f.read()))
    # Only a dossier with a published (or previously published) translation is
    # re-exported: a refresh never rewrites a single-language dossier it has no
    # reason to touch.
    if dossier_variants or metadata.get("dossier_languages"):
        dossier_assets, dossier_languages = export_dossier(key, handoff, out, published)
        metadata["dossier_assets"] = dossier_assets
        metadata["dossier_languages"] = dossier_languages
        refreshed_prefixes += ["research-charts/", "dossier."]
    refreshed = {
        path: _sha256_file(os.path.join(out, path))
        for path in (
            *report_languages.values(),
            *report_assets,
            *(metadata.get("dossier_languages") or {}).values(),
            *(metadata.get("dossier_assets") or []),
        )
        if os.path.isfile(os.path.join(out, path))
    }
    # Existing entries keep their order; refreshed ones get new digests, entries
    # for files no longer published are dropped, and new files are appended.
    artifact_sha256 = {}
    for path, digest in published.items():
        if path in refreshed:
            artifact_sha256[path] = refreshed[path]
        elif not path.startswith(tuple(refreshed_prefixes)):
            artifact_sha256[path] = digest
    for path, digest in refreshed.items():
        artifact_sha256.setdefault(path, digest)
    metadata["artifact_sha256"] = artifact_sha256
    audit = _read_json(os.path.join(UPLOADS, "reports", state["report_id"], "final_audit.json"))
    metadata["publication"] = _publication_summary(audit)
    # Keep the file's existing indentation so a refresh does not reformat it.
    with open(metadata_path, encoding="utf-8") as f:
        second_line = (f.read().split("\n", 2) + ["", ""])[1]
    indent = len(second_line) - len(second_line.lstrip(" ")) or 2
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=indent)
        f.write("\n")
    return metadata


def export_run(
    key: str,
    pipeline_id: str,
    skip_graph: bool,
    require_publishable: bool = False,
    graph_api: str | None = None,
) -> None:
    state = _read_json(os.path.join(UPLOADS, "pipelines", pipeline_id, "pipeline_state.json"))
    if not state:
        print(f"!! {key}: pipeline state missing, skipped")
        return
    audit = (
        validate_publishable_run(pipeline_id, state)
        if require_publishable
        else _read_json(os.path.join(UPLOADS, "reports", state.get("report_id", ""), "final_audit.json"))
    )
    out = os.path.join(OUT_ROOT, key)
    os.makedirs(out, exist_ok=True)
    handoff = os.path.join(UPLOADS, "pipelines", pipeline_id, "handoff")

    # stage 1 — research log + dossier (+ structured extraction when present)
    research_log = export_research_log(
        handoff,
        out,
        retain_existing_if_missing=True,
    )
    dossier_assets, dossier_languages = export_dossier(key, handoff, out)
    for name in ("actors.json", "sources.json"):
        src = os.path.join(handoff, name)
        if os.path.exists(src):
            shutil.copyfile(src, os.path.join(out, name))

    # stage 2 — ontology
    project = _load_bound_project(
        UPLOADS,
        state["project_id"],
        state["graph_id"],
    )
    ontology = project.get("ontology") or {}
    _write_json(os.path.join(out, "ontology.json"), {
        "entity_types": ontology.get("entity_types", []),
        "edge_types": ontology.get("edge_types", []),
        "analysis_summary": project.get("analysis_summary", ""),
    })

    # stage 3 — knowledge graph (network call; resilient to Zep 429s). Strict
    # publication exports preserve the graph identity validated above: a 404
    # aborts instead of substituting a nondeterministic reconstruction.
    exported_graph_id = state["graph_id"]
    if not skip_graph:
        from app.services.graphiti_client import ApiError

        graph_id = state["graph_id"]
        try:
            graph = export_graph(graph_id, graph_api=graph_api)
        except ApiError as e:
            if getattr(e, "status_code", None) != 404:
                raise
            if require_publishable:
                raise RuntimeError(
                    f"publication-bound graph {graph_id!r} is unavailable (404); "
                    "refusing to rebuild or substitute a different graph"
                ) from e
            print(f"   original graph {graph_id} is gone (404) — rebuilding from dossier")
            graph_id = rebuild_graph(key, out)
            graph = export_graph(graph_id)
        exported_graph_id = graph_id
        graph["graph_id"] = graph_id
        _write_json(os.path.join(out, "graph.json"), graph)
        print(f"   graph: {len(graph['nodes'])} nodes / {len(graph['links'])} edges")
    elif require_publishable:
        validate_retained_graph(out, state["graph_id"])

    # stage 5 — forum feed
    forum = export_forum(os.path.join(UPLOADS, "simulations", state["simulation_id"]))
    _write_json(os.path.join(out, "forum.json"), forum)

    # stage 6 — final report (placeholder sections stripped for presentation) and
    # every published translation of it
    report_assets, report_languages = export_report(key, state["report_id"], out)

    # run metadata for the site cards/header
    run_state = _read_json(os.path.join(UPLOADS, "simulations", state["simulation_id"], "run_state.json")) or {}
    cfg = _read_json(os.path.join(UPLOADS, "simulations", state["simulation_id"], "simulation_config.json")) or {}
    agents = cfg.get("agent_configs") or cfg.get("agents") or []
    artifact_paths = [
        "research_log.txt",
        *dossier_languages.values(),
        "actors.json",
        "sources.json",
        "ontology.json",
        "graph.json",
        "forum.json",
        *report_languages.values(),
        *dossier_assets,
        *report_assets,
    ]
    artifact_sha256 = {
        path: _sha256_file(os.path.join(out, path))
        for path in artifact_paths
        if os.path.isfile(os.path.join(out, path))
    }
    _write_json(os.path.join(out, "meta.json"), {
        "pipeline_id": pipeline_id,
        "report_id": state.get("report_id"),
        "simulation_id": state.get("simulation_id"),
        "graph_id": exported_graph_id,
        "status": state.get("status"),
        "prompt": state.get("prompt", ""),
        "created_at": state.get("created_at", ""),
        "mode": state.get("mode", "full"),
        "rounds": run_state.get("total_rounds"),
        "personas": len(agents) if isinstance(agents, list) else None,
        "has_actors": os.path.exists(os.path.join(handoff, "actors.json")),
        "research_log": research_log,
        "dossier_assets": dossier_assets,
        "report_assets": report_assets,
        "dossier_languages": dossier_languages,
        "report_languages": report_languages,
        "artifact_sha256": artifact_sha256,
        "publication": _publication_summary(audit),
    })
    print(f"ok {key}: exported -> {out}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-graph", action="store_true", help="skip the Zep graph export (no network)")
    ap.add_argument("--only", help="export a single run key")
    ap.add_argument(
        "--require-publishable",
        action="store_true",
        help="fail unless the pipeline and final read-only publication audit pass",
    )
    ap.add_argument(
        "--research-log-only",
        action="store_true",
        help="refresh only prompt + exact merged research log metadata/assets",
    )
    ap.add_argument(
        "--reports-only",
        action="store_true",
        help="refresh only report/dossier text and their published translations",
    )
    ap.add_argument(
        "--graph-api",
        help="read the knowledge graph from a running backend (e.g. http://127.0.0.1:5001)",
    )
    args = ap.parse_args()

    runs = {args.only: RUNS[args.only]} if args.only else RUNS
    for key, pid in runs.items():
        if args.research_log_only:
            metadata = refresh_demo_research_log(
                key,
                pid,
                require_publishable=args.require_publishable,
            )
            print(f"ok {key}: refreshed research provenance ({metadata['line_count']} lines)")
        elif args.reports_only:
            metadata = refresh_demo_reports(key, pid)
            dossier_languages = sorted(metadata.get("dossier_languages") or {})
            print(
                f"ok {key}: refreshed report {sorted(metadata['report_languages'])}"
                f", dossier {dossier_languages or 'unchanged'}"
            )
        else:
            export_run(
                key,
                pid,
                skip_graph=args.skip_graph,
                require_publishable=args.require_publishable,
                graph_api=args.graph_api,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
