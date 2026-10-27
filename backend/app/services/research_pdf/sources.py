"""Read admitted report bytes and copy immutable, resource-owned export inputs."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import unquote, urlsplit

from .contracts import PdfExportError

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
_ASSETS = {".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".mmd", ".html"}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical_hash(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())


def validate_identity(kind, resource_id, lang):
    if kind not in {"dossier", "forecast"} or not isinstance(resource_id, str) or not _ID.fullmatch(resource_id):
        raise PdfExportError("invalid_resource", "Invalid report export resource.")
    if lang not in (None, "en", "zh"):
        raise PdfExportError("invalid_language", "Choose the original report, English, or Mandarin.")


def _contained(root, path):
    root, path = Path(root).absolute(), Path(path).absolute()
    try:
        rel = path.relative_to(root)
    except ValueError as exc:
        raise PdfExportError("unsafe_asset", "A report asset escapes its source folder.") from exc
    cursor = root
    if root.is_symlink():
        raise PdfExportError("unsafe_source", "The report source folder must not be a symbolic link.")
    for part in rel.parts:
        cursor = cursor / part
        if part in {"..", "."} or cursor.is_symlink():
            raise PdfExportError("unsafe_asset", "Report assets must remain inside their source folder.")
    if not path.resolve().is_relative_to(root.resolve()):
        raise PdfExportError("unsafe_asset", "A report asset escapes its source folder.")
    return path


def _read(root, path, *, required=True, limit=32 * 1024 * 1024):
    path = _contained(root, path)
    if not path.is_file():
        if not required:
            return None
        raise PdfExportError("source_missing", "The report or a required asset is unavailable.")
    if path.stat().st_size > limit:
        raise PdfExportError("source_too_large", "An export input exceeds the supported file size; split it explicitly.")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise PdfExportError("source_too_large", "An export input changed beyond the supported size.")
    return raw


def _json(raw, default=None):
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (ValueError, UnicodeError) as exc:
        raise PdfExportError("invalid_source_metadata", "Report source metadata is not valid JSON.") from exc


def _locate(kind, resource_id, requested_lang):
    """Reuse this checkout's admission rules; no generation or translation calls."""
    from app.services.report_agent import ReportAgent, ReportManager

    if kind == "forecast":
        root = Path(ReportManager._get_report_folder(resource_id)).absolute()
        primary = _read(root, root / "full_report.md")
        source_lang = ReportAgent._detect_translation_target(primary.decode("utf-8"))[0]
        selected = None if requested_lang in (None, source_lang) else requested_lang
        admission = ReportManager.publication_status(resource_id, selected)
        if not admission.get("publishable"):
            raise PdfExportError("source_not_publishable", "This report version has not passed its publication checks.")
        name = f"full_report.{selected}.md" if selected else "full_report.md"
        metadata = _json(_read(root, root / "meta.json"), {})
        deps = ["full_report.md", f"final_audit.{selected}.json" if selected else "final_audit.json",
                f"citations.{selected}.json" if selected else "citations.json", "viz_manifest.json", "forecast.json"]
        if selected:
            deps.append("final_audit.json")
        citation_name = f"citations.{selected}.json" if selected else "citations.json"
        ledger = _json(_read(root, root / citation_name, required=False), {})
        if not isinstance(ledger, dict):
            raise PdfExportError("invalid_source_metadata", "The report citation ledger must be an object.")
        citations = {}
        for row in ledger.get("markers") or []:
            if not isinstance(row, dict) or not isinstance(row.get("tag"), str):
                raise PdfExportError("invalid_source_metadata", "A report citation marker is invalid.")
            tag = row["tag"].strip().strip("[]").upper()
            if tag in citations:
                raise PdfExportError("invalid_source_metadata", "A report citation marker is duplicated.")
            citations[tag] = row
        proof = {"rule": "forecast_publication", "publishable": True, "language": selected or source_lang,
                 "source_language": source_lang, "publication": admission}
    else:
        from app.services.pipeline_orchestrator import PipelineManager
        from app.api.research import _research_variant

        root = Path(PipelineManager.resolve_handoff_dir(resource_id)).absolute()
        primary = _read(root, root / "research_report.md")
        source_lang = ReportAgent._detect_translation_target(primary.decode("utf-8"))[0]
        selected = None if requested_lang in (None, source_lang) else requested_lang
        name = f"research_report.{selected}.md" if selected else "research_report.md"
        if selected:
            status, admitted = _research_variant(str(root), selected)
            if admitted is None:
                raise PdfExportError("translation_not_ready", "This language version is missing, stale, or has not passed review.")
            raw = _read(root, root / name)
            if raw.decode("utf-8") != admitted:
                raise PdfExportError("source_changed", "The translation changed while preparing the export.", retryable=True)
            proof = {"rule": "dossier_translation", "available": True, "language": selected,
                     "source_language": source_lang, "partial": bool(status.get("partial")),
                     "verbatim_chunks": status.get("verbatim_chunks") or []}
            admitted_proof = status if status.get("status") == "available" else status.get("previous") or {}
            proof["binding"] = {key: admitted_proof.get(key) for key in
                                ("schema_version", "source_sha256", "markdown_sha256", "audit_sha256", "target_lang")}
        else:
            proof = {"rule": "primary_dossier_readable", "available": True, "language": source_lang,
                     "judge_admission_claimed": False}
        # Pipeline status is not export input. Retain only source-derived display metadata.
        state = PipelineManager.load(resource_id) or {}
        metadata = {k: state.get(k) for k in ("created_at", "title", "topic", "prompt")}
        deps = ["research_report.md", "sources.json", "charts.json"]
        if selected:
            deps.append(f"research_report.final_audit.{selected}.json")
        source_rows = _json(_read(root, root / "sources.json", required=False), [])
        if isinstance(source_rows, dict):
            source_rows = source_rows.get("sources", source_rows)
        citations = ({f"S{i}": row for i, row in enumerate(source_rows, 1)}
                     if isinstance(source_rows, list) else source_rows)
    if (selected or source_lang) not in ("en", "zh"):
        raise PdfExportError("unsupported_source_language", "This exporter requires an English or Mandarin source report.")
    return root, name, metadata, citations, deps, proof, selected or source_lang


def _image_refs(markdown):
    import mistune
    parser = mistune.create_markdown(renderer="ast", plugins=["table", "footnotes", "strikethrough", "url"])
    refs = []

    def visit(items):
        for item in items:
            if item.get("type") == "image":
                refs.append(item.get("attrs", {}).get("url", ""))
            visit(item.get("children") or [])
    visit(parser(markdown))
    # HTML handling is still the renderer's responsibility; preflight its image assets too.
    from html.parser import HTMLParser

    class Images(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag.lower() == "img":
                refs.append(dict(attrs).get("src", ""))
    Images().feed(markdown)
    return sorted(set(refs))


def inspect_source(kind, resource_id, requested_lang=None):
    validate_identity(kind, resource_id, requested_lang)
    root, name, metadata, citations, dependency_names, admission, lang = _locate(kind, resource_id, requested_lang)
    raw = _read(root, root / name)
    try:
        markdown = raw.decode("utf-8")
    except UnicodeError as exc:
        raise PdfExportError("invalid_source_encoding", "The report must be valid UTF-8.") from exc
    if not markdown.strip():
        raise PdfExportError("source_empty", "The selected report is empty.")
    paths, asset_map = {}, {}
    charts = root / "charts"
    if charts.exists():
        _contained(root, charts)
        for path in sorted(charts.rglob("*")):
            if path.suffix.lower() in _ASSETS:
                data = _read(root, path)
                paths[path.relative_to(root).as_posix()] = data
    for ref in _image_refs(markdown):
        parsed = urlsplit(ref)
        if parsed.scheme or parsed.netloc:
            raise PdfExportError("external_image", "A report image is external. Save it as a report-owned asset before export.")
        path_text = unquote(parsed.path)
        if path_text.startswith("/api/report/"):
            prefix = f"/api/report/{resource_id}/charts/"
            if kind != "forecast" or not path_text.startswith(prefix):
                raise PdfExportError("asset_owner_mismatch", "A figure belongs to another report.")
            path_text = "charts/" + path_text[len(prefix):]
        elif path_text.startswith("/api/research/"):
            owners = {resource_id, root.parent.name}
            match = re.fullmatch(r"/api/research/([^/]+)/artifact/chart_([^/]+)", path_text)
            if kind != "dossier" or not match or match.group(1) not in owners:
                raise PdfExportError("asset_owner_mismatch", "A figure belongs to another research report.")
            path_text = "charts/" + match.group(2)
        path = Path(path_text)
        path = _contained(root, path if path.is_absolute() else root / path)
        relative = path.relative_to(root).as_posix()
        if path.suffix.lower() not in _ASSETS:
            raise PdfExportError("unsupported_asset", "A required figure has an unsupported file format.")
        paths[relative] = _read(root, path)
        asset_map[ref] = relative
    if sum(len(value) for value in paths.values()) > 256 * 1024 * 1024:
        raise PdfExportError("assets_too_large", "This report's figure bundle exceeds the export size limit.")
    dependencies = {name: sha(raw)}
    for dependency in sorted(set(dependency_names)):
        data = _read(root, root / dependency, required=False)
        dependencies[dependency] = sha(data) if data is not None else None
    title_match = re.search(r"^#\s+(.+)$", markdown, re.MULTILINE)
    title = (title_match.group(1).strip() if title_match else metadata.get("title") or metadata.get("topic"))
    title = str(title or ("深度研究报告" if kind == "dossier" and lang == "zh" else
                          "预测报告" if lang == "zh" else "Deep research report" if kind == "dossier" else "Forecast report"))
    timestamp = str(metadata.get("created_at") or "")
    provenance = "source_metadata"
    try:
        document_date = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        document_date = datetime.fromtimestamp((root / name).stat().st_mtime, timezone.utc).date().isoformat()
        provenance = "source_artifact_modified_date"
    assets = [{"relative_path": path, "sha256": sha(data)} for path, data in sorted(paths.items())]
    manifest_name = "charts.json" if kind == "dossier" else "viz_manifest.json"
    chart_manifest = _json(_read(root, root / manifest_name, required=False), [])
    descriptor = {"schema": "research-pdf-source/v1", "kind": kind, "resource_id": resource_id,
        "requested_lang": requested_lang, "language": "zh-CN" if lang == "zh" else "en",
        "markdown_sha256": sha(raw), "title": title, "publisher": "DeepResearchForecast",
        "report_type": ("深度研究" if kind == "dossier" else "预测报告") if lang == "zh" else
                       ("Deep research" if kind == "dossier" else "Forecast report"),
        "date": document_date, "date_provenance": provenance, "citations": citations or {},
        "dependencies": dependencies, "assets": assets, "asset_map": asset_map,
        "chart_manifest": chart_manifest, "admission": admission}
    descriptor["source_digest"] = canonical_hash(descriptor)
    return {**descriptor, "markdown": markdown, "_origin_folder": str(root), "_asset_bytes": paths}


def capture_source(kind, resource_id, requested_lang, directory):
    """Copy a complete snapshot and detect mutation during copying/admission."""
    from app.utils.atomic import write_json_atomic
    directory = Path(directory).absolute()
    current = inspect_source(kind, resource_id, requested_lang)
    if directory.exists():
        raise PdfExportError("export_snapshot_exists", "An export snapshot already exists at this generation.")
    directory.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".source-", dir=directory.parent))
    try:
        (stage / "source.md").write_bytes(current["markdown"].encode("utf-8"))
        for relative, raw in current["_asset_bytes"].items():
            path = stage / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        latest = inspect_source(kind, resource_id, requested_lang)
        if latest["source_digest"] != current["source_digest"]:
            raise PdfExportError("source_changed", "The report changed while its export snapshot was being prepared.", retryable=True)
        snapshot = {k: v for k, v in current.items() if not k.startswith("_")}
        snapshot.update(folder=str(directory), markdown_path=str(directory / "source.md"))
        write_json_atomic(str(stage / "snapshot.json"), snapshot, allow_nan=False)
        stage.rename(directory)
        return snapshot
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def assert_current(snapshot):
    try:
        current = inspect_source(snapshot["kind"], snapshot["resource_id"], snapshot["requested_lang"])
    except (PdfExportError, OSError, ValueError) as exc:
        raise PdfExportError("source_changed", "The source or its publication review is no longer available.", retryable=True) from exc
    if current["source_digest"] != snapshot["source_digest"]:
        raise PdfExportError("source_changed", "The source report changed. Start a new export of the current version.", retryable=True)
