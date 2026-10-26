"""
Report API路由
提供模拟报告生成、获取、对话等接口
"""

import hashlib
import json
import os
import re
import sqlite3
import time
import traceback
import threading
from flask import request, jsonify, send_file, send_from_directory, Response

from . import report_bp
from ..config import Config
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus, load_simulation_world
from ..services import simulation_record_contract as _src
from ..services.exec_brief import _load_pinned_simulation_policy as _pinned_simulation_policy
from ..services.pipeline_orchestrator import load_research_dossier_for_simulation
from ..services.backtest_mode import pipeline_for_simulation
from ..services.simulation_manager import SimulationManager
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..services.translation import scheduler as translation_scheduler
from ..services.translation.artifacts import ArtifactError
from ..services.translation.contracts import TranslationError
from ..utils.chart_html import inline_plotly_bundle
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.report')


@report_bp.errorhandler(ArtifactError)
def _artifact_error_response(exc):
    return jsonify({"success": False, "error": str(exc), "code": exc.code}), exc.status_code


@report_bp.errorhandler(sqlite3.Error)
@report_bp.errorhandler(TranslationError)
def _translation_service_error_response(exc):
    return jsonify({"success": False, "error": "Translation coordination is unavailable; retry shortly",
                    "code": "translation_service_unavailable"}), 503


def _validate_report_id(report_id):
    if not isinstance(report_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", report_id):
        raise ArtifactError("invalid_report_id", "Invalid report identity", 400)


def _requested_artifact_identity(*names):
    values = [value for name in names for value in request.args.getlist(name)]
    if any(len(request.args.getlist(name)) > 1 for name in names) or (
            values and (not values[0] or any(value != values[0] for value in values))):
        raise ArtifactError("invalid_artifact_identity", "Conflicting or empty artifact identity", 400)
    return values[0] if values else None


@report_bp.before_request
def _verify_world_report_request():
    """One read-only world gate for normal, cached and auxiliary consumers."""
    from ..services.world_simulation.contracts import WorldError
    if request.method == "OPTIONS":
        return None  # CORS preflight carries no report data
    try:
        report_id = (request.view_args or {}).get("report_id")
        if report_id:
            _validate_report_id(report_id)
        if report_id and request.method != "DELETE":
            ReportManager.load_world_result(report_id)
        elif request.endpoint in {"report.generate_report", "report.chat_with_report_agent"}:
            data = request.get_json(silent=True) or {}
            if data.get("simulation_id"):
                load_simulation_world(data["simulation_id"])
    except (WorldError, OSError, ValueError, KeyError, TypeError):
        return jsonify({"success": False, "error": "World result integrity verification failed",
                        "code": "world_result_integrity"}), 409


@report_bp.route('/<report_id>/world-result', methods=['GET'])
def get_report_world_result(report_id: str):
    """Public frozen diagnostics remain available even under no_update."""
    world = ReportManager.load_world_result(report_id)
    if world is None:
        return jsonify({"success": False, "error": "Report has no world result"}), 404
    return jsonify({"success": True, "data": world})


def _withhold_outline_drafts(outline):
    """Keep the outline skeleton (title/summary, section titles/descriptions), drop section prose.

    Report.to_dict() 序列化的 outline.sections[*].content 就是各章节正文草稿（报告完成时
    save_report 连同大纲一起落盘到 meta.json），未通过发布审计时必须与 markdown_content
    同一闸门隐去。
    """
    if not isinstance(outline, dict) or not isinstance(outline.get("sections"), list):
        return outline
    return {
        **outline,
        "sections": [
            {**section, "content": "", "draft_withheld": True}
            if isinstance(section, dict) else section
            for section in outline["sections"]
        ],
    }


def _report_forecast_effect(report):
    """The pinned SIMULATION_FORECAST_EFFECT this report was generated under (ADR 0003).

    Read from the sealed ``forecast.json`` first (``simulation_bridge.forecast_effect`` is
    written under ``diagnostic_only``), then from the run's pinned ``safety_policy_v1`` by
    the same lookup the executive brief uses; ``None`` when neither records it — the
    payload never asserts a policy it did not read.
    """
    try:
        forecast = ReportManager.load_structured_forecast(report.report_id)
    except Exception:  # noqa: BLE001 — an unreadable forecast never hides the report
        forecast = None
    bridge = (forecast or {}).get("simulation_bridge") if isinstance(forecast, dict) else None
    if isinstance(bridge, dict) and bridge.get("forecast_effect"):
        return str(bridge["forecast_effect"])
    quality = forecast.get("quality") if isinstance(forecast, dict) else None
    final = quality.get("final_audit") if isinstance(quality, dict) else None
    audited = final.get("simulation_bridge") if isinstance(final, dict) else None
    if isinstance(audited, dict) and audited.get("policy") in {"diagnostic_only", "no_update", "legacy_prompt"}:
        return audited["policy"]
    try:
        return _pinned_simulation_policy(ReportManager._get_report_folder(report.report_id))
    except Exception:  # noqa: BLE001
        return None


def _simulation_record_ref(report):
    """``{sha256, url}`` of this report's gate-passed Simulation After-Action Record, or
    ``None`` (absent record, failed or missing gate, or an unsafe simulation id)."""
    sim_id = str(getattr(report, "simulation_id", "") or "").strip()
    if not sim_id or sim_id in (".", "..") or "/" in sim_id or os.sep in sim_id:
        return None
    sim_dir = os.path.join(getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "", sim_id)
    try:
        record, _status = _src.load_published_record(sim_dir)
        if record is None:
            return None
        sha = _src.record_sha256(record)
    except (OSError, ValueError, TypeError):
        return None
    return {"sha256": sha, "url": f"/api/simulation/{sim_id}/record"}


def _report_publication_payload(report):
    """Return report metadata without leaking an unaudited draft body.

    Unpublishable reports keep their state and outline skeleton, but both the
    assembled Markdown and every outline section's draft content are withheld.

    ADR 0003 (S3): the payload carries ``forecast_effect`` (the pinned policy, or
    ``None``) and, only when the Simulation After-Action Record passed its gate,
    ``simulation_record_ref`` ``{sha256, url}``; the frontend renders the record anchor
    from the latter and never infers a policy the payload did not state.
    """
    publication = ReportManager.publication_status(report.report_id)
    if any("news context" in str(reason) for reason in publication.get("reasons") or []):
        raise ValueError("Report news context generation is invalid")
    payload = report.to_dict()
    payload["news_market_context"] = ReportManager.load_report_news_market_context(report.report_id)
    payload["publishable"] = bool(publication.get("publishable"))
    payload["publication_issues"] = list(publication.get("reasons") or [])
    payload["draft_withheld"] = not payload["publishable"]
    if payload["draft_withheld"]:
        payload["markdown_content"] = ""
        payload["outline"] = _withhold_outline_drafts(payload.get("outline"))
    payload["translation_status"] = ReportManager.translation_status(
        report.report_id, report=report
    )
    verified = payload["translation_status"].get("translation")
    payload["translations"] = []
    if (isinstance(verified, dict)
            and verified.get("available") is True
            and verified.get("audit_verified") is True
            and verified.get("source_markdown_sha256")
            and verified.get("markdown_sha256")
            and verified.get("final_audit_sha256")):
        payload["translations"] = [verified]
    payload["forecast_effect"] = _report_forecast_effect(report)
    record_ref = (_simulation_record_ref(report)
                  if payload["forecast_effect"] == "diagnostic_only" else None)
    if record_ref:
        payload["simulation_record_ref"] = record_ref
    return payload


def _report_display_document(report):
    """Canonical public display inventory, shared by identity and render readers."""
    directory = ReportManager._get_report_folder(report.report_id)
    manifest = []
    try:
        with open(os.path.join(directory, "viz_manifest.json"), encoding="utf-8") as handle:
            manifest = json.load(handle)
        if isinstance(manifest, dict):
            manifest = manifest.get("items") or manifest.get("charts") or []
    except (OSError, ValueError):
        pass
    # The display must obey the same chart-path admission as the normal API.
    from pathlib import PurePosixPath
    def chart_path(value):
        if (not isinstance(value, str) or "\\" in value or "%" in value
                or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            return None
        path = PurePosixPath(value.strip().removeprefix("./"))
        return path.as_posix() if (not path.is_absolute() and ".." not in path.parts
            and len(path.parts) > 1 and path.parts[0] == "charts") else None
    safe_manifest = []
    for item in manifest if isinstance(manifest, list) else []:
        if not isinstance(item, dict) or not chart_path(item.get("path")):
            continue
        item = {**item, "path": chart_path(item["path"])}
        if "png_path" in item:
            if chart_path(item["png_path"]):
                item["png_path"] = chart_path(item["png_path"])
            else:
                item.pop("png_path")
        safe_manifest.append(item)
    outline = report.outline.to_dict() if getattr(report, "outline", None) else {}
    heading = (report.markdown_content or "").split("\n", 1)[0].lstrip("# ")
    document = {"title": outline.get("title") or heading,
        "news_market_context": ReportManager.load_report_news_market_context(report.report_id),
        "viz_manifest": safe_manifest, "failed_sections": list(getattr(report, "failed_sections", None) or [])}
    return document


def _report_structured_source_fingerprint(report):
    source = {"display": _report_display_document(report),
              "forecast_sha256": ReportManager._sha256_file(
                  os.path.join(ReportManager._get_report_folder(report.report_id), "forecast.json"))}
    return hashlib.sha256(json.dumps(source, sort_keys=True, ensure_ascii=False,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def _report_display(report, lang, *, generate=False, force=False, snapshot=None):
    """Use one sealed display for public readers; workers inspect current candidates."""
    from ..services.artifact_translation import display_document
    directory = ReportManager._get_report_folder(report.report_id)
    document = _report_display_document(report)
    result = display_document(directory, "report", report.report_id, lang, document,
                              generate=generate, force=force)
    state = {**result["structured_translation"], "complete": result["coverage"]["complete"],
             "coverage": result["coverage"]}
    if snapshot is not None and not generate:
        raw = snapshot.assets.get("display.json")
        try:
            sealed = json.loads(raw) if raw is not None else None
        except (ValueError, TypeError) as exc:
            raise ArtifactError("invalid_artifact", "Published display asset is invalid") from exc
        sealed_state = sealed.get("structured_translation") if isinstance(sealed, dict) else None
        if (isinstance(sealed_state, dict)
                and sealed_state.get("source_fingerprint") == _report_structured_source_fingerprint(report)):
            coverage = sealed_state.get("coverage", {}).get("display")
            if not isinstance(coverage, dict) or not {"complete", "translated", "total"} <= coverage.keys():
                raise ArtifactError("invalid_artifact", "Published display coverage is invalid")
            state = {**state, "coverage": coverage, "complete": coverage["complete"],
                     "partial": not coverage["complete"],
                     "pending": max(0, coverage["total"] - coverage["translated"]),
                     "issues": list(sealed_state.get("issues") or [])}
            result["display"] = sealed
        else:
            # Never borrow a mutable sidecar for a body whose generation lacks a
            # matching display. Show canonical text with explicit pending coverage.
            total = result["coverage"]["total"]
            state = {**state, "coverage": {"translated": 0, "total": total, "complete": not total},
                     "complete": not total, "partial": bool(total), "pending": total,
                     "issues": ["Published display needs translation for the current source"] if total else []}
            result["display"] = document
    return {"display": {**result["display"], "translation_status": state},
            "translation_status": state, "structured_translation": state}


def _report_structured(report, lang, *, forecast_state=None, snapshot=None):
    """Read the combined forecast/display projection; this never acquires work."""
    display = _report_display(report, lang, snapshot=snapshot)
    view = display["translation_status"]
    forecast, localization = (forecast_state if forecast_state is not None
                              else ReportManager.load_localized_forecast(report.report_id, lang, snapshot=snapshot))
    present = isinstance(forecast, dict)
    fields = list(ReportAgent._forecast_text_fields(forecast)) if present else []
    forecast_complete = not present or localization.get("complete") is True
    unresolved = sum(ReportAgent._forecast_text_is_residual(text, lang) for _path, text in fields)
    forecast_pending = max(1, unresolved) if present and not forecast_complete else 0
    # Identity is canonical even before a localized sidecar exists, so repair
    # progress itself cannot invalidate the enclosing durable operation.
    source_sha = ReportManager._sha256_file(
        os.path.join(ReportManager._get_report_folder(report.report_id), "forecast.json"))
    complete = view["complete"] and forecast_complete
    partial = bool(view.get("partial")) or not complete
    issues = list(view.get("issues") or [])
    if not forecast_complete:
        issues.append("Forecast dashboard text remains untranslated or its localization proof is incomplete; retry structured translation.")
    coverage = {
        "translated": view["coverage"]["translated"] + max(0, len(fields) - forecast_pending),
        "total": view["coverage"]["total"] + len(fields), "complete": complete,
        "display": view["coverage"],
        "forecast": {"translated": max(0, len(fields) - forecast_pending), "total": len(fields),
                     "complete": forecast_complete},
    }
    state = {**view, "status": "partial" if partial else "available",
        "complete": complete, "partial": partial,
        "pending": view["pending"] + forecast_pending, "retryable": partial,
        "coverage": coverage, "issues": issues, "display_complete": view["complete"],
        "forecast": {**localization, "present": present, "complete": forecast_complete,
                     "pending": forecast_pending, "source_forecast_sha256": source_sha},
        "source_fingerprint": _report_structured_source_fingerprint(report)}
    return {"display": {**display["display"], "translation_status": state, "structured_translation": state},
            "translation_status": state, "structured_translation": state}


def _repair_report_structured(report, lang, force=False, *, expected_identity):
    """Run only inside the elected scheduler; never rewrite the accepted body."""
    from ..utils.llm_client import LLMClient
    from ..utils.telemetry import LLMCache
    directory = ReportManager._get_report_folder(report.report_id)
    lock_path = os.path.join(directory, "structured_translation." + lang + ".lock")
    with ReportManager._advisory_file_lock(lock_path), LLMCache.bypass():
        _check_report_translation_source(report.report_id, lang, expected_identity)
        if not ReportManager.is_publishable(report.report_id, _report_publication_lang(report, lang)):
            raise ArtifactError("translation_unpublished", "Translation is not admitted for display repair")
        forecast, localization = ReportManager.load_localized_forecast(report.report_id, lang)
        if isinstance(forecast, dict) and (force or localization.get("complete") is not True):
            worker = ReportAgent.__new__(ReportAgent)
            worker.llm = LLMClient()
            worker.output_language = "Chinese" if lang == "zh" else "English"
            worker.simulation_id, worker.graph_id = report.simulation_id, report.graph_id
            worker._forecast_spine = forecast
            worker._ensure_localized_forecast(report.report_id, lang, force=force)
        report = _check_report_translation_source(report.report_id, lang, expected_identity)
        if not ReportManager.is_publishable(report.report_id, _report_publication_lang(report, lang)):
            raise ArtifactError("translation_unpublished", "Translation publication changed during repair")
        _report_display(report, lang, generate=True, force=force)
        _check_report_translation_source(report.report_id, lang, expected_identity)


def _assert_report_snapshot_current(report_id, lang, snapshot):
    if snapshot is None:
        return
    publication = ReportManager.publication_status(report_id, lang)
    primary = ReportManager.publication_status(report_id)
    if (not publication.get("publishable") or publication.get("generation_id") != snapshot.generation
            or primary.get("markdown_sha256") != snapshot.source_sha256):
        raise ArtifactError("stale_artifact", "Report publication changed while reading; reload")


def _with_report_display_status(state, report, lang, *, public=False):
    # No generation pointer retains the historical, source-validated legacy
    # readers. Once a pointer exists, public reads cannot mix candidate sidecars.
    snapshot = (ReportManager.resolve_translation(report.report_id, lang)
                if public and _report_publication_lang(report, lang) is not None else None)
    if snapshot and state.get("generation_id") not in (None, snapshot.generation):
        raise ArtifactError("stale_artifact", "Report publication changed while reading; reload")
    display = _report_structured(report, lang, snapshot=snapshot)
    if snapshot:
        _assert_report_snapshot_current(report.report_id, lang, snapshot)
        display["generation_id"] = snapshot.generation
    structured = display["structured_translation"]
    return {**state, **display,
            "partial": bool(state.get("partial")) or bool(structured.get("partial")) or not structured["complete"],
            "issues": list(state.get("issues") or []) + structured["issues"]}


def _publication_rejection(report_id: str, lang=None, publication=None):
    """Build the shared fail-closed response for customer-facing artifacts."""
    if publication is None:
        publication = ReportManager.publication_status(report_id, lang)
    return jsonify({
        "success": False,
        "error": "报告尚未通过最终发布审计",
        "publishable": False,
        "publication_issues": list(publication.get("reasons") or []),
    }), 409


# agent_log.jsonl 中承载报告正文草稿的字段。报告仍在活跃生成时照常实时下发（与
# sections-partial 的渐进发布一致）；未通过发布审计时（生成结束、元信息不可读、或生成中断
# 超时，见 _draft_exposure_gate）这些字段一律隐去，只保留事件骨架（action/stage/章节标题/
# 长度/遥测），与 sections/section 端点同一闸门。
_AGENT_LOG_DRAFT_FIELDS = {
    "section_content": ("content",),
    "section_complete": ("content",),
    "llm_response": ("response",),
    "react_thought": ("thought",),
}
_REPORT_IN_PROGRESS = (ReportStatus.PENDING, ReportStatus.PLANNING, ReportStatus.GENERATING)

# 「生成中实时下发草稿」豁免的有效期（秒）。生成器崩溃 / 进程被杀时 meta.json 永远停在
# pending/planning/generating，若豁免不设期限，草稿会被无限期当作「生成中」下发。生成器每次
# 工具调用、LLM 响应、章节落盘都会刷新下方的活动文件（agent_log.jsonl / console_log.txt 逐事件
# 追加；单次 LLM HTTP 请求读超时为 600s，见 utils/llm_client.py），正常生成中两次写入的间隔
# 远小于 30 分钟；超过此时长毫无写入即判定生成已中断，按「未通过发布审计」处理，不再下发任何
# 草稿。心跳取文件 mtime 而非 progress.json 的 updated_at：后者只在阶段/章节边界刷新（单章节
# 检索可能很久，并发生成时更久），且为无时区的本地时间。
REPORT_IN_PROGRESS_STALE_SECONDS = 30 * 60

# 只有报告生成器会写入的活动文件（查看 / 导出等读路径不刷新它们），外加 section_XX.md。
# 其最新 mtime 即生成心跳。
_REPORT_ACTIVITY_FILES = frozenset({
    "meta.json", "progress.json", "outline.json", "agent_log.jsonl", "console_log.txt",
})

_STALE_GENERATION_REASON = (
    "report generation stalled: no generator activity for over "
    f"{REPORT_IN_PROGRESS_STALE_SECONDS // 60} minutes"
)
_UNLOADABLE_METADATA_REASON = "report metadata (meta.json) could not be loaded"


def _report_last_activity(report_id: str):
    """Return the newest mtime (epoch seconds) among generator-written files, or None."""
    latest = None
    try:
        with os.scandir(ReportManager._get_report_folder(report_id)) as entries:
            for entry in entries:
                name = entry.name
                if name not in _REPORT_ACTIVITY_FILES and not (
                        name.startswith("section_") and name.endswith(".md")):
                    continue
                try:
                    mtime = entry.stat().st_mtime
                except OSError:
                    continue
                if latest is None or mtime > latest:
                    latest = mtime
    except OSError:
        return None
    return latest


def _report_generation_live(report_id: str) -> bool:
    """True iff the generator wrote an activity file within REPORT_IN_PROGRESS_STALE_SECONDS.

    A timestamp more than the window in the future (clock jump / tampering) is not
    trusted as proof of liveness either.
    """
    last = _report_last_activity(report_id)
    if last is None:
        return False
    return abs(time.time() - last) <= REPORT_IN_PROGRESS_STALE_SECONDS


def _draft_exposure_gate(report_id: str):
    """Return (withhold_drafts, report, publication): the single draft-exposure gate.

    Section drafts (section_XX.md, agent-log prose) are served only when the exact
    report bytes are publishable, or while the report is demonstrably still being
    generated: loadable metadata with an in-flight status AND generator activity
    within REPORT_IN_PROGRESS_STALE_SECONDS.  Everything else fails closed:
    missing / unreadable / malformed meta.json, a finished-but-unpublishable
    report, and an in-flight status whose generator went silent (crashed).
    """
    try:
        report = ReportManager.get_report(report_id)
    except Exception as e:  # noqa: BLE001 - 结构损坏的 meta.json 与缺失同等对待（fail closed）
        logger.warning(f"报告元信息不可读，按不可发布处理: {report_id}: {e}")
        report = None
    try:
        publication = ReportManager.publication_status(report_id)
    except Exception as e:  # noqa: BLE001 - 结构异常的 meta.json（非对象等）→ fail closed，不 500
        logger.warning(f"报告发布状态无法判定，按不可发布处理: {report_id}: {e}")
        publication = {"publishable": False, "reasons": [_UNLOADABLE_METADATA_REASON]}
    if report is None and publication.get("publishable"):
        # publication_status 只读 meta.json 的 status 等少数字段；元信息无法还原为 Report
        # （缺字段等）时即便审计看似通过，也没有可信的报告可言 → 同样不可发布。
        publication = {
            **publication,
            "publishable": False,
            "reasons": [*(publication.get("reasons") or []), _UNLOADABLE_METADATA_REASON],
        }
    live = False
    if report is not None and report.status in _REPORT_IN_PROGRESS:
        live = _report_generation_live(report_id)
        if not live:
            publication = {
                **publication,
                "reasons": [*(publication.get("reasons") or []), _STALE_GENERATION_REASON],
            }
    withhold = not live and not publication.get("publishable")
    return withhold, report, publication


# 生成器在控制台日志里会引用草稿原文的几类审计/修订行：标记 → 引文开始处的分隔符。
# 草稿被扣留时只保留分隔符之前的计数摘要，引文部分替换为扣留标记（诊断信息仍可见）。
_CONSOLE_DRAFT_QUOTE_MARKERS = (
    ("引用接地审计", ": "),
    ("概率一致性审计", ": "),
    ("统计合理性审计", ": "),
    ("反思修订已采纳", " ｜指令"),
)
_CONSOLE_DRAFT_WITHHELD = " [draft excerpt withheld until the report passes its final audit]"


def _withhold_console_log_drafts(lines):
    """Redact the draft excerpts some generator log lines quote, keeping their summaries."""
    result = []
    for line in lines:
        if isinstance(line, str):
            for marker, separator in _CONSOLE_DRAFT_QUOTE_MARKERS:
                start = line.find(marker)
                if start < 0:
                    continue
                cut = line.find(separator, start + len(marker))
                if cut >= 0:
                    line = line[:cut] + _CONSOLE_DRAFT_WITHHELD
                break
        result.append(line)
    return result


def _withhold_agent_log_drafts(logs):
    """Drop draft prose from agent-log entries, keeping the event skeleton."""
    result = []
    for entry in logs:
        fields = _AGENT_LOG_DRAFT_FIELDS.get(entry.get("action")) if isinstance(entry, dict) else None
        details = entry.get("details") if fields else None
        if isinstance(details, dict) and any(name in details for name in fields):
            details = {k: v for k, v in details.items() if k not in fields}
            details["draft_withheld"] = True
            entry = {**entry, "details": details}
        result.append(entry)
    return result


def _gate_agent_log(report_id: str, logs):
    """Apply the publication gate to agent-log entries; returns (logs, gate fields)."""
    withhold, _report, publication = _draft_exposure_gate(report_id)
    if withhold:
        logs = _withhold_agent_log_drafts(logs)
    return logs, {
        "publishable": bool(publication.get("publishable")),
        "publication_issues": list(publication.get("reasons") or []),
        "draft_withheld": withhold,
    }


_REPORT_TRANSLATION_KIND = "report_translation"
_TRANSLATION_ACTIVE = {"queued", "pending", "running", "processing", "waiting_provider"}
_TRANSLATION_RETRYABLE = {"failed", "interrupted", "cancelled"}


def _translation_report(report_id, lang):
    _validate_report_id(report_id)
    if lang not in ReportManager._TRANSLATION_LANGS:
        raise ArtifactError("unsupported_language", "Unsupported translation language", 400)
    report = ReportManager.get_report(report_id)
    if report is None:
        raise ArtifactError("report_not_found", "Report does not exist", 404)
    if report.report_id != report_id:
        raise ArtifactError("report_identity_mismatch", "Report identity does not match the requested resource")
    return report


def _report_publication_lang(report, lang):
    """The primary language uses the canonical body, not a translation sidecar."""
    source_lang = ReportAgent._detect_translation_target(report.markdown_content or "")[0]
    return None if lang == source_lang else lang


def _report_translation_identity(report, lang, mode):
    # Identity depends only on canonical source, never translated cache contents.
    from ..services.translation.artifacts import figure_inventory
    directory = ReportManager._get_report_folder(report.report_id)
    return {
        "kind": _REPORT_TRANSLATION_KIND, "ref_id": report.report_id,
        "target_lang": lang, "scope": mode,
        "source_markdown_sha256": hashlib.sha256((report.markdown_content or "").encode()).hexdigest(),
        "source_structured_sha256": _report_structured_source_fingerprint(report),
        "source_figures": figure_inventory(report.markdown_content or "",
                                           ReportManager._get_report_markdown_path(report.report_id)),
        "source_files": {name: ReportManager._sha256_file(os.path.join(directory, name))
                         for name in ("full_report.md", "final_audit.json", "citations.json")},
    }


def _check_report_translation_source(report_id, lang, identity):
    translation_scheduler.assert_current_task_active()
    report = _translation_report(report_id, lang)
    ReportManager.load_world_result(report_id)
    if identity.get("scope") not in {"body", "structured"}:
        raise ArtifactError("translation_job_mismatch", "Invalid report translation scope")
    if identity != _report_translation_identity(report, lang, identity["scope"]):
        raise ArtifactError("translation_source_changed", "Report source changed; reload before retrying")
    if not ReportManager.is_publishable(report_id):
        raise ArtifactError("translation_source_unpublished", "Report source is no longer publishable")
    return report


def _report_translation_handler(payload):
    """Named durable operation; all provider work starts after source admission."""
    try:
        return _run_report_translation(payload)
    except ArtifactError as exc:
        raise TranslationError(exc.code, str(exc), retryable=exc.code not in {
            "translation_source_changed", "translation_job_mismatch", "report_not_found",
            "translation_source_unpublished",
        }) from exc


def _run_report_translation(payload):
    report_id, lang = payload["report_id"], payload["lang"]
    identity = payload["identity"]
    report = _check_report_translation_source(report_id, lang, identity)
    force = payload.get("force") is True
    # This flag selects the replacement namespace, keyed by current_task_id in
    # the core service. Replaying it on the same durable task resumes candidates;
    # dropping it would switch to the old accepted job and abandon the refresh.
    publication_lang = _report_publication_lang(report, lang)
    publication = ReportManager.publication_status(report_id, publication_lang)
    replacement_pending = force and publication.get("generation_id") == payload.get("previous_generation_id")
    if identity["scope"] == "body" and (not publication.get("publishable") or replacement_pending):
        result = ReportManager.generate_translation_variant(report_id, lang, force=force)
        _check_report_translation_source(report_id, lang, identity)
        if not (result.get("available") and result.get("updated", True)
                and ReportManager.is_publishable(report_id, lang)):
            raise TranslationError("translation_not_admitted", "Translation did not pass publication checks", retryable=True)
    _repair_report_structured(report, lang, force=force, expected_identity=identity)
    report = _check_report_translation_source(report_id, lang, identity)
    state = _with_report_display_status(
        ReportManager.translation_status(report_id, lang, report=report), report, lang)
    if not state["structured_translation"]["complete"]:
        raise TranslationError("translation_structured_incomplete", "Structured translation remains incomplete; retry pending work", retryable=True)
    if publication_lang is not None:
        snapshot = ReportManager.refresh_translation_assets(report_id, lang, {
            "display.json": json.dumps(state["display"], ensure_ascii=False, sort_keys=True).encode("utf-8"),
        })
        if snapshot is None:
            raise TranslationError("translation_assets_unpublished", "Structured assets could not be published", retryable=True)
    _check_report_translation_source(report_id, lang, identity)
    state = _with_report_display_status(
        ReportManager.translation_status(report_id, lang, report=report), report, lang)
    return state


def _authorize_report_translation_resource(selection, action):
    """Resolve untrusted resource selection using the report facade's gates."""
    if (action not in {"retry", "cancel"} or not isinstance(selection, dict)
            or set(selection) - {"report_id", "lang", "scope", "mode"}):
        return None
    report_id, lang = selection.get("report_id"), selection.get("lang")
    mode = selection.get("scope", selection.get("mode"))
    if (not isinstance(report_id, str) or not isinstance(lang, str)
            or not isinstance(mode, str) or mode not in {"body", "structured"}
            or ("mode" in selection and selection["mode"] != mode)):
        return None
    lang = lang.strip().lower()
    try:
        report = _translation_report(report_id, lang)
        ReportManager.load_world_result(report_id)
        if not ReportManager.is_publishable(report_id):
            return None
        if action == "retry":
            if mode == "body" and not getattr(Config, "REPORT_BILINGUAL", True):
                return None
            if mode == "structured" and not ReportManager.is_publishable(report_id, _report_publication_lang(report, lang)):
                return None
        return _report_translation_identity(report, lang, mode)
    except (ArtifactError, OSError, ValueError, TypeError, KeyError):
        # Generic actions expose neither inaccessible resource details nor a
        # stored identity as authority. Their route supplies the stable 403.
        return None


def register_translation_handler():
    """Idempotently register execution and resource-scoped generic actions."""
    from .translations import register_resource_authorizer
    translation_scheduler.register_handler(_REPORT_TRANSLATION_KIND, _report_translation_handler)
    register_resource_authorizer(_REPORT_TRANSLATION_KIND, _authorize_report_translation_resource)


def _remember_report_translation_job(report_id, lang, job):
    """Persist only the reconnect locator; the scheduler retains job authority."""
    ReportManager._set_translation_runtime_status(report_id, lang, "scheduled",
        translation_job_id=job["job_id"], task_id=job["job_id"],
        source_markdown_sha256=job["identity"]["source_markdown_sha256"])
    return job


def enqueue_report_translation(report_id, lang, *, force=False, mode="body"):
    """Enqueue or attach after primary publication, without a Flask request.

    Automatic completion and manual POST use the same source identity, payload,
    handler and reconnect locator. Failed/interrupted work is only attached here;
    explicit retry remains the POST/scheduler retry boundary.
    """
    lang = str(lang or "").strip().lower()
    if mode not in {"body", "structured"}:
        raise ArtifactError("translation_job_mismatch", "Invalid report translation scope", 400)
    report = _translation_report(report_id, lang)
    ReportManager.load_world_result(report_id)
    if not ReportManager.is_publishable(report_id):
        raise ArtifactError("translation_source_unpublished", "Report source is not publishable")
    publication_lang = _report_publication_lang(report, lang)
    if publication_lang is None:
        mode = "structured"
    if (force or mode == "body") and not getattr(Config, "REPORT_BILINGUAL", True):
        raise ArtifactError("translation_disabled", "Report translation is disabled")
    publication = ReportManager.publication_status(report_id, publication_lang)
    if mode == "structured" and not publication.get("publishable"):
        raise ArtifactError("translation_unpublished", "Structured repair requires an admitted body")
    identity = _report_translation_identity(report, lang, mode)
    existing = _report_translation_job(report, lang)
    if existing and ((existing.get("job_state") or existing.get("status")) in _TRANSLATION_ACTIVE
                     or (not force and existing.get("identity") == identity)):
        return _remember_report_translation_job(report_id, lang, existing)
    regenerate = bool(force and publication.get("publishable"))
    register_translation_handler()
    job = translation_scheduler.submit(_REPORT_TRANSLATION_KIND, identity,
        {"report_id": report_id, "lang": lang, "identity": identity, "force": regenerate,
         "previous_generation_id": publication.get("generation_id")}, force=regenerate)
    return _remember_report_translation_job(report_id, lang, job)


def _report_translation_job(report, lang, task_id=None, *, tolerate_unavailable=False):
    """The legacy runtime file is a locator only, never execution authority."""
    explicit = bool(task_id)
    if not explicit:
        locator = ReportManager._load_translation_runtime_status(report.report_id, lang) or {}
        task_id = locator.get("translation_job_id")
    if not task_id:
        return None
    try:
        job = translation_scheduler.status(task_id)
    except (OSError, sqlite3.Error, TranslationError) as exc:
        if tolerate_unavailable and not explicit:
            return None  # Accepted publication is independent of coordination storage.
        raise TranslationError("store_unavailable", "Translation coordination is unavailable") from exc
    if job is None:
        if explicit:
            raise ArtifactError("translation_job_not_found", "Translation job does not exist", 404)
        return None
    identity = job.get("identity") or {}
    if (job.get("kind") != _REPORT_TRANSLATION_KIND
            or identity.get("ref_id") != report.report_id or identity.get("target_lang") != lang
            or identity.get("scope") not in {"body", "structured"}):
        raise ArtifactError("translation_job_mismatch", "Task does not match this report and language")
    if identity != _report_translation_identity(report, lang, identity["scope"]):
        if explicit:
            raise ArtifactError("translation_source_changed", "Report source changed; reload before retrying")
        return None  # A source edit must not reconnect to an old-source operation.
    return job


def _with_translation_job(state, job):
    if job is None:
        if state.get("status") in {"generating", "pending", "processing"}:
            # Legacy PID/heartbeat files cannot assert live ownership after cutover.
            return {**state, "status": "interrupted", "task_id": None}
        return state
    execution = job.get("job_state") or job.get("status")
    legacy = {"queued": "pending", "running": "processing", "waiting_provider": "processing"}.get(execution, execution)
    structured = dict(state["structured_translation"])
    if execution in _TRANSLATION_ACTIVE:
        structured.update(status="generating", retryable=False)
    elif execution in _TRANSLATION_RETRYABLE and not structured["complete"]:
        structured.update(status="partial", retryable=True)
    display = {**state["display"], "translation_status": structured, "structured_translation": structured}
    result = job.get("result") or {}
    # A structured repair retains the audited body. A body refresh's task-bound
    # availability describes its own outcome; published_available remains explicit.
    available = bool(state.get("available"))
    if (job.get("identity") or {}).get("scope") == "body":
        available = bool(available and execution == "completed" and result.get("available")
                         and result.get("updated", True))
    return {**state, "published_available": bool(state.get("available")), "available": available,
            "status": legacy, "task_id": job["job_id"], "translation_job": job,
            "progress": job.get("progress", 100 if execution == "completed" else 0),
            "message": job.get("message", ""), "error": job.get("error"), "result": job.get("result"),
            "display": display, "translation_status": structured, "structured_translation": structured}


# ============== 报告生成接口 ==============

def _manual_report_owner_kwargs(owner):
    """Use the saved scenario and report policy of the verified run owner."""
    from ..services.pipeline_orchestrator import PipelineManager
    options = owner["options"] if owner else {}
    base_simulation_id = None
    if options.get("base_pipeline_id"):
        baseline = PipelineManager.load(options["base_pipeline_id"]) or {}
        base_simulation_id = baseline.get("simulation_id")
    return {"report_policy": options.get("safety_policy_v1"),
            "scenario_label": options.get("scenario_label"),
            "base_simulation_id": base_simulation_id}


@report_bp.route('/generate', methods=['POST'])
def generate_report():
    """
    生成模拟分析报告（异步任务）
    
    这是一个耗时操作，接口会立即返回task_id，
    使用 GET /api/report/generate/status 查询进度
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",    // 必填，模拟ID
            "force_regenerate": false        // 可选，强制重新生成
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",
                "status": "generating",
                "message": "报告生成任务已启动"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400
        
        force_regenerate = data.get('force_regenerate', False)
        
        # 获取模拟信息
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404

        _owner = pipeline_for_simulation(simulation_id)
        _dossier = load_research_dossier_for_simulation(simulation_id)
        _owner_kwargs = _manual_report_owner_kwargs(_owner)
        
        # 检查是否已有报告
        if not force_regenerate:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if (existing_report and existing_report.status == ReportStatus.COMPLETED
                    and ReportManager.is_publishable(existing_report.report_id)):
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "message": "报告已存在",
                        "already_generated": True
                    }
                })
        
        # 获取项目信息
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {state.project_id}"
            }), 404
        
        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "缺少图谱ID，请确保已构建图谱"
            }), 400
        
        simulation_requirement = _owner.get("prompt") if _owner else project.simulation_requirement
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "缺少模拟需求描述"
            }), 400
        
        # 提前生成 report_id，以便立即返回给前端
        import uuid
        report_id = f"report_{uuid.uuid4().hex[:12]}"
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="report_generate",
            metadata={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "report_id": report_id
            }
        )
        
        # 定义后台任务
        def run_generate():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="初始化Report Agent..."
                )
                
                # 创建Report Agent（T4.1: best-effort 钉入研究档案，找不到则回退冷图路径）
                agent = ReportAgent(
                    graph_id=graph_id,
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    situation_brief=_dossier.get("situation_brief"),
                    actors=_dossier.get("actors"),
                    sources=_dossier.get("sources"),
                    research_report=_dossier.get("research_report"),
                    official_data=_dossier.get("official_data"),
                    news_market_context=_dossier.get("news_market_context"),
                    **_owner_kwargs,
                    **(_dossier.get("report_artifacts") or {}),
                )
                
                # 进度回调
                def progress_callback(stage, progress, message):
                    task_manager.update_task(
                        task_id,
                        progress=progress,
                        message=f"[{stage}] {message}"
                    )
                
                # 生成报告（传入预先生成的 report_id）
                report = agent.generate_report(
                    progress_callback=progress_callback,
                    report_id=report_id
                )
                
                # 保存报告
                ReportManager.save_report(report)

                # EXECPLAN2 F-7-0: force_regenerate 成功后清理同 simulation 的旧报告文件夹，
                # 避免遗留多份导致 get_report_by_simulation 返回过期/不确定的报告。
                publishable = (
                    report.status == ReportStatus.COMPLETED
                    and ReportManager.is_publishable(report.report_id)
                )
                if force_regenerate and publishable:
                    try:
                        removed = ReportManager.delete_other_reports_for_simulation(
                            simulation_id, keep_report_id=report.report_id
                        )
                        if removed:
                            logger.info(f"已清理 {removed} 份同 simulation 旧报告: {simulation_id}")
                    except Exception as _e:
                        logger.warning(f"清理旧报告失败（忽略）: {_e}")

                if publishable:
                    task_manager.complete_task(
                        task_id,
                        result={
                            "report_id": report.report_id,
                            "simulation_id": simulation_id,
                            "status": "completed"
                        }
                    )
                else:
                    publication = ReportManager.publication_status(report.report_id)
                    reasons = "; ".join(publication.get("reasons") or [])
                    task_manager.fail_task(
                        task_id,
                        report.error or reasons or "报告生成失败或未通过最终发布审计",
                    )
                
            except Exception as e:
                logger.error(f"报告生成失败: {str(e)}")
                task_manager.fail_task(task_id, str(e))
        
        # 启动后台线程
        thread = threading.Thread(target=run_generate, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "report_id": report_id,
                "task_id": task_id,
                "status": "generating",
                "message": "报告生成任务已启动，请通过 /api/report/generate/status 查询进度",
                "already_generated": False
            }
        })
        
    except Exception as e:
        logger.error(f"启动报告生成任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/generate/status', methods=['POST'])
def get_generate_status():
    """
    查询报告生成任务进度
    
    请求（JSON）：
        {
            "task_id": "task_xxxx",         // 可选，generate返回的task_id
            "simulation_id": "sim_xxxx"     // 可选，模拟ID
        }
    
    返回：
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|failed",
                "progress": 45,
                "message": "..."
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # 如果提供了simulation_id，先检查是否已有完成的报告
        if simulation_id:
            existing_report = ReportManager.get_report_by_simulation(simulation_id)
            if (existing_report and existing_report.status == ReportStatus.COMPLETED
                    and ReportManager.is_publishable(existing_report.report_id)):
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "report_id": existing_report.report_id,
                        "status": "completed",
                        "progress": 100,
                        "message": "报告已生成",
                        "already_completed": True
                    }
                })
        
        if not task_id:
            return jsonify({
                "success": False,
                "error": "请提供 task_id 或 simulation_id"
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            return jsonify({
                "success": False,
                "error": f"任务不存在: {task_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": task.to_dict()
        })
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== 报告获取接口 ==============

@report_bp.route('/<report_id>', methods=['GET'])
def get_report(report_id: str):
    """
    获取报告详情
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "simulation_id": "sim_xxxx",
                "status": "completed",
                "outline": {...},
                "markdown_content": "...",
                "created_at": "...",
                "completed_at": "..."
            }
        }
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": _report_publication_payload(report)
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/forecast', methods=['GET'])
def get_report_forecast(report_id: str):
    """Return the optional structured forecast used by the local report UI.

    The stable ``/api/v1`` SDK is intentionally feature-gated and may be
    disabled on a local installation.  The first-party SPA, however, is always
    allowed to read a *publishable* report's forecast dashboard.  Returning a
    successful ``forecast: null`` payload for audited legacy reports keeps that
    optional dashboard degrade-safe without creating expected 404/409 console
    noise before a new run.
    """
    report = ReportManager.get_report(report_id)
    if report is None:
        return jsonify({
            "success": False,
            "error": f"报告不存在: {report_id}",
        }), 404
    if not ReportManager.is_publishable(report_id):
        return _publication_rejection(report_id)

    # ?lang=en|zh returns the dashboard strings in that language when a localized
    # copy bound to the sealed forecast.json exists; otherwise the sealed original.
    lang = (request.args.get("lang") or "").strip().lower() or None
    if lang is not None and lang not in ReportManager._TRANSLATION_LANGS:
        return jsonify({
            "success": False,
            "error": f"不支持的语种: {lang}（仅 en / zh）",
        }), 400
    snapshot = (ReportManager.resolve_translation(report_id, lang)
                if lang and _report_publication_lang(report, lang) is not None else None)
    if lang is None:
        forecast = ReportManager.load_structured_forecast(report_id)
        localization = {"requested_lang": None, "localized": False}
    else:
        forecast, localization = ReportManager.load_localized_forecast(report_id, lang, snapshot=snapshot)
    display = _report_structured(report, lang, forecast_state=(forecast, localization), snapshot=snapshot) if lang else {}
    if snapshot:
        _assert_report_snapshot_current(report_id, lang, snapshot)
        display["generation_id"] = snapshot.generation
    if lang:
        job = _report_translation_job(report, lang, tolerate_unavailable=True)
        if job:
            display = _with_translation_job(display, job)
            # Forecast availability is independent of a body refresh's outcome.
            display.pop("available", None)
    return jsonify({
        "success": True,
        "data": {
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "forecast": forecast,
            "available": forecast is not None,
            "localization": localization,
            **display,
        },
    })


@report_bp.route('/<report_id>/official-data', methods=['GET'])
def get_report_official_data(report_id: str):
    """Return the stored official data a publishable report was written from.

    RPT-12 (fix contract §1.7): ``official_data`` is the exact report-local
    carrier (digest-checked) and ``indicators`` its deterministic summaries
    (label, latest observed value and period, year-over-year change, five-year
    range, newest publisher value, recent history, [S#] tag) in ``?lang=en|zh``
    (default: the report's language). Reports without official data return
    ``available: false``; nothing is fetched.
    """
    from ..services.exec_brief import _detect_lang
    from ..services.report_agent import official_indicator_rows

    report = ReportManager.get_report(report_id)
    if report is None:
        return jsonify({
            "success": False,
            "error": f"报告不存在: {report_id}",
        }), 404
    if not ReportManager.is_publishable(report_id):
        return _publication_rejection(report_id)
    lang = (request.args.get("lang") or "").strip().lower() or None
    if lang is not None and lang not in ReportManager._TRANSLATION_LANGS:
        return jsonify({
            "success": False,
            "error": f"不支持的语种: {lang}（仅 en / zh）",
        }), 400
    lang = lang or _detect_lang(report.markdown_content or "")
    record = ReportManager.load_report_official_data(report_id)
    if record is None:
        return jsonify({
            "success": True,
            "data": {"report_id": report_id, "simulation_id": report.simulation_id,
                     "available": False, "sha256": None, "official_data": None,
                     "indicators": [], "lang": lang},
        })
    tags = record["source_tags"]
    indicators = official_indicator_rows(record["official_data"], lang=lang,
                                         tag_for=lambda row: tags.get(row["series"], ""))
    binding = record.get("research_binding")
    return jsonify({
        "success": True,
        "data": {
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "available": bool(indicators),
            "sha256": record.get("sha256"),
            "saved_at": record.get("saved_at"),
            "research_binding": binding if isinstance(binding, dict) else None,
            "official_data": record["official_data"],
            "indicators": indicators,
            "lang": lang,
        },
    })


@report_bp.route('/by-simulation/<simulation_id>', methods=['GET'])
def get_report_by_simulation(simulation_id: str):
    """
    根据模拟ID获取报告
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                ...
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"该模拟暂无报告: {simulation_id}",
                "has_report": False
            }), 404
        
        return jsonify({
            "success": True,
            "data": _report_publication_payload(report),
            "has_report": True
        })
        
    except Exception as e:
        logger.error(f"获取报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/list', methods=['GET'])
def list_reports():
    """
    列出所有报告
    
    Query参数：
        simulation_id: 按模拟ID过滤（可选）
        limit: 返回数量限制（默认50）
    
    返回：
        {
            "success": true,
            "data": [...],
            "count": 10
        }
    """
    try:
        simulation_id = request.args.get('simulation_id')
        limit = request.args.get('limit', 50, type=int)
        
        reports = ReportManager.list_reports(
            simulation_id=simulation_id,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": [_report_publication_payload(r) for r in reports],
            "count": len(reports)
        })
        
    except Exception as e:
        logger.error(f"列出报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    下载报告（Markdown格式）
    
    返回Markdown文件
    """
    try:
        report = ReportManager.get_report(report_id)
        
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404

        if not ReportManager.is_publishable(report_id):
            return _publication_rejection(report_id)
        
        md_path = ReportManager._get_report_markdown_path(report_id)
        
        if not os.path.exists(md_path):
            # EXECPLAN2 F-7-4: MD文件不存在时直接以内存流返回，避免遗留临时文件导致磁盘/inode泄漏
            return Response(
                report.markdown_content or "",
                mimetype="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="{report_id}.md"'
                },
            )
        
        return send_file(
            md_path,
            as_attachment=True,
            download_name=f"{report_id}.md"
        )
        
    except Exception as e:
        logger.error(f"下载报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 双语报告 Markdown 接口（BILINGUAL）==============

@report_bp.route('/<report_id>/full_report.<lang>.md', methods=['GET'])
def get_report_translation_md(report_id: str, lang: str):
    """服务自动生成的双语版本 reports/{id}/full_report.<lang>.md（lang ∈ {en, zh}）。

    镜像 /download 的原文件返回约定：文件存在则以 text/markdown 返回，否则 404。lang 非
    {en, zh} 或该语种版本未生成（REPORT_BILINGUAL 关闭 / 同语种 / 翻译失败）→ 404（degrade-safe）。
    """
    try:
        lang = (lang or '').strip().lower()
        if lang not in ReportManager._TRANSLATION_LANGS:
            return jsonify({
                "success": False,
                "error": f"不支持的语种: {lang}（仅 en / zh）"
            }), 404

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}",
            }), 404

        snapshot = ReportManager.resolve_translation(report_id, lang)
        expected = _requested_artifact_identity("generation_id", "generation")
        if expected and (snapshot is None or snapshot.generation != expected):
            raise ArtifactError("stale_artifact", "Displayed translation changed; reload before downloading")
        markdown = snapshot.markdown if snapshot else ReportManager.read_translation_markdown(report_id, lang)
        if not markdown:
            return jsonify({
                "success": False,
                "error": f"该报告暂无 {lang} 版本: {report_id}"
            }), 404
        publication = ReportManager.publication_status(report_id, lang)
        if not publication.get("publishable"):
            return _publication_rejection(report_id, lang, publication)
        markdown_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        source_sha = ReportManager.publication_status(report_id).get("markdown_sha256")
        expected_source = _requested_artifact_identity("source_sha256", "source_markdown_sha256")
        if (publication.get("markdown_sha256") != markdown_sha
                or (expected_source is not None and expected_source != source_sha)
                or (snapshot and (publication.get("generation_id") != snapshot.generation
                    or source_sha != snapshot.source_sha256))):
            raise ArtifactError("stale_artifact", "Translation publication changed while reading; reload")

        return Response(
            markdown,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.{lang}.md"'},
        )

    except ArtifactError as exc:
        return _artifact_error_response(exc)
    except FileNotFoundError:
        return jsonify({"success": False, "error": "Requested translation does not exist"}), 404
    except Exception as e:
        logger.error(f"获取双语报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/translations/<lang>', methods=['POST'])
def generate_report_translation(report_id: str, lang: str):
    """Explicit start/retry/refresh boundary for one source-bound durable job."""
    lang = (lang or "").strip().lower()
    report = _translation_report(report_id, lang)
    force = (request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}
    task_id = (request.args.get("task_id") or "").strip()
    job = _report_translation_job(report, lang, task_id)
    state = _with_report_display_status(
        ReportManager.translation_status(report_id, lang, report=report), report, lang, public=True)
    if job and (job.get("job_state") or job.get("status")) in _TRANSLATION_ACTIVE:
        return jsonify({"success": True, "data": _with_translation_job(state, job)}), (200 if state.get("available") and job["identity"]["scope"] == "structured" else 202)
    if not ReportManager.is_publishable(report_id):
        return _publication_rejection(report_id)
    retrying = bool(job and not force and
                    (job.get("job_state") or job.get("status")) in _TRANSLATION_RETRYABLE)
    if not force and not retrying and state.get("available") and state["structured_translation"]["complete"]:
        return jsonify({"success": True, "data": state}), 200
    if (force or not state.get("available")) and not getattr(Config, "REPORT_BILINGUAL", True):
        return jsonify({"success": False, "error": "Report translation is disabled", "data": state}), 409
    if state.get("status") == "source_language" and not state.get("available"):
        return jsonify({"success": False, "error": "Requested language is not a translation target", "data": state}), 409
    if retrying:
        register_translation_handler()
        job = translation_scheduler.retry(job["job_id"])
        _remember_report_translation_job(report_id, lang, job)
    else:
        mode = "structured" if state.get("available") and not force else "body"
        job = enqueue_report_translation(report_id, lang, force=force, mode=mode)
    data = _with_translation_job(state, job)
    return jsonify({"success": True, "data": data}), (200 if data["available"] else 202)


@report_bp.route('/<report_id>/translations/<lang>/status', methods=['GET'])
def get_report_translation_status(report_id: str, lang: str):
    """Read admitted content and scheduler state without acquiring provider work."""
    lang = (lang or "").strip().lower()
    report = _translation_report(report_id, lang)
    job = _report_translation_job(report, lang, (request.args.get("task_id") or "").strip(),
                                  tolerate_unavailable=True)
    state = _with_report_display_status(
        ReportManager.translation_status(report_id, lang, report=report), report, lang, public=True)
    return jsonify({"success": True, "data": _with_translation_job(state, job)})


# ============== 报告 PDF 导出接口（PDF-1）==============

@report_bp.route('/<report_id>/pdf', methods=['GET'])
def get_report_pdf(report_id: str):
    """Build and return one publication-bound PDF artifact.

    Cache reuse is content-addressed across Markdown, audits, citations, charts,
    fonts, and renderer configuration. A PDF is served only after parse/text/glyph
    integrity checks and an exact output manifest have passed.

    BILINGUAL：可选 ?lang=en|zh 从双语版 full_report.<lang>.md 构建 full_report.<lang>.pdf
    （复用同一套 export 机制）；缺省走主报告，显式非法 lang 返回 400。

    与同蓝图的 /download（Markdown）、/charts（图表资源）共用 /api/report/<id>/... 前缀约定。
    """
    try:
        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404

        # BILINGUAL：缺省走主报告；显式非法语种必须失败，绝不静默回退为
        # English/primary PDF 后仍让调用方误以为拿到了所请求的语言。
        raw_lang = request.args.get('lang')
        lang = (raw_lang or '').strip().lower()
        if raw_lang is not None and (lang not in ReportManager._TRANSLATION_LANGS
                                     or len(request.args.getlist("lang")) != 1):
            return jsonify({
                "success": False,
                "error": f"不支持的语种: {lang}（仅 en / zh）",
            }), 400
        requested_lang = lang if lang in ReportManager._TRANSLATION_LANGS else None
        primary_lang = ReportAgent._detect_translation_target(report.markdown_content or "")[0]
        lang = requested_lang if requested_lang != primary_lang else None

        if not getattr(Config, "REPORT_PDF_EXPORT", True):
            return jsonify({
                "success": False,
                "error": "PDF 导出服务未启用",
                "code": "pdf_export_disabled",
            }), 503

        primary = ReportManager.publication_status(report_id)
        publication = ReportManager.publication_status(report_id, lang) if lang else primary
        if not publication.get("publishable"):
            return _publication_rejection(report_id, lang, publication)
        expected = _requested_artifact_identity("generation_id", "generation")
        if expected is not None and expected != publication.get("generation_id"):
            raise ArtifactError("stale_artifact", "Displayed translation changed; reload before exporting")
        expected_source = _requested_artifact_identity("source_sha256", "source_markdown_sha256")
        if expected_source is not None and expected_source != primary.get("markdown_sha256"):
            raise ArtifactError("stale_artifact", "Displayed report source changed; reload before exporting")

        pdf_path = ReportManager.export_pdf(report_id, lang=lang)
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({
                "success": False,
                "error": "PDF 构建未通过渲染或内容完整性门",
                "code": "pdf_build_failed",
            }), 503

        current = ReportManager.publication_status(report_id, lang)
        if (not current.get("publishable")
                or ReportManager.publication_status(report_id).get("markdown_sha256") != primary.get("markdown_sha256")
                or any(current.get(key) != publication.get(key)
                for key in ("generation_id", "markdown_sha256", "source_markdown_sha256"))):
            raise ArtifactError("stale_artifact", "Report publication changed while exporting; retry")

        download_name = f"{report_id}.{requested_lang}.pdf" if requested_lang else f"{report_id}.pdf"
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

    except ArtifactError as exc:
        return _artifact_error_response(exc)
    except Exception:  # noqa: BLE001 - return a stable public error contract
        logger.exception("导出报告 PDF 发生未预期错误 report_id=%s", report_id)
        return jsonify({
            "success": False,
            "error": "PDF 导出发生内部错误",
            "code": "pdf_internal_error",
        }), 500


# ============== 执行交付物接口（DELIV-1）==============

@report_bp.route('/<report_id>/exec-brief', methods=['GET'])
def get_report_exec_brief(report_id: str):
    """惰性构建并返回一页高管简报 reports/{id}/exec_brief[.<lang>].md（DELIV-1）。

    与 /pdf 同思路：首次访问（或 full_report.md / forecast.json 更新后）确定性再生（NO LLM，只从
    成稿 + forecast.json 抽取），译文按内容与发布代际缓存复用。REPORT_EXEC_BRIEF 关闭 / 报告缺失 / 简报
    未生成 → 404（degrade-safe）。

    BILINGUAL：可选 ?lang=en|zh 从译文简报 exec_brief.<lang>.md 取（缺省/非法 → 主语言简报，行为默认）。
    与同蓝图的 /pdf、/charts、/download 共用 /api/report/<id>/... 前缀约定。
    """
    try:
        from ..services.exec_brief import ExecBriefBuilder

        if not getattr(Config, "REPORT_EXEC_BRIEF", True):
            return jsonify({
                "success": False,
                "error": "执行简报不可用（REPORT_EXEC_BRIEF 未开启）",
            }), 404

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404

        lang = (request.args.get('lang') or '').strip().lower()
        lang = lang if lang in ExecBriefBuilder._TRANSLATION_LANGS else None
        if lang == ReportAgent._detect_translation_target(report.markdown_content or "")[0]:
            lang = None

        publication = ReportManager.publication_status(report_id, lang)
        if not publication.get("publishable"):
            return _publication_rejection(report_id, lang, publication)
        expected = _requested_artifact_identity("generation_id", "generation")
        if expected is not None and expected != publication.get("generation_id"):
            raise ArtifactError("stale_artifact", "Displayed report generation changed; reload")

        report_dir = ReportManager._get_report_folder(report_id)
        produced = ExecBriefBuilder.build(report_id, report_dir, lang=lang)
        brief_path = produced.get(f"exec_brief.{lang}" if lang else "exec_brief")
        if not brief_path or not os.path.exists(brief_path):
            return jsonify({
                "success": False,
                "error": "执行简报不可用（未开启 REPORT_EXEC_BRIEF、缺该语种版本或构建失败）"
            }), 404
        brief_bytes = ExecBriefBuilder.read_current(report_id, report_dir, brief_path, lang)
        current = ReportManager.publication_status(report_id, lang)
        if (not current.get("publishable") or any(current.get(key) != publication.get(key)
                for key in ("generation_id", "markdown_sha256"))):
            raise ArtifactError("stale_artifact", "Report publication changed while building the brief")

        return Response(
            brief_bytes,
            mimetype="text/markdown",
            headers={"Content-Disposition": 'attachment; filename="' + (
                f"{report_id}.exec_brief.{lang}.md" if lang else f"{report_id}.exec_brief.md") + '"'},
        )

    except ArtifactError as exc:
        return _artifact_error_response(exc)
    except Exception as e:
        logger.error(f"获取执行简报失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/exec-brief.pdf', methods=['GET'])
def get_report_exec_brief_pdf(report_id: str):
    """惰性构建并返回一页高管简报 PDF reports/{id}/exec_brief[.<lang>].pdf（DELIV-1）。

    先确保简报 md 存在（build），再复用 pandoc 引擎选择 + PyMuPDF 回退导出（去 --toc、收紧边距做单
    页），按内容与发布代际缓存。REPORT_EXEC_BRIEF / REPORT_PDF_EXPORT 关闭、报告/简报缺失、构建
    失败 → 404（degrade-safe）。BILINGUAL：?lang=en|zh 取译文简报 PDF。
    """
    try:
        from ..services.exec_brief import ExecBriefBuilder

        if (not getattr(Config, "REPORT_EXEC_BRIEF", True)
                or not getattr(Config, "REPORT_PDF_EXPORT", True)):
            return jsonify({
                "success": False,
                "error": "执行简报 PDF 不可用（导出功能未开启）",
            }), 404

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404

        lang = (request.args.get('lang') or '').strip().lower()
        lang = lang if lang in ExecBriefBuilder._TRANSLATION_LANGS else None
        if lang == ReportAgent._detect_translation_target(report.markdown_content or "")[0]:
            lang = None

        publication = ReportManager.publication_status(report_id, lang)
        if not publication.get("publishable"):
            return _publication_rejection(report_id, lang, publication)
        expected = _requested_artifact_identity("generation_id", "generation")
        if expected is not None and expected != publication.get("generation_id"):
            raise ArtifactError("stale_artifact", "Displayed report generation changed; reload")

        report_dir = ReportManager._get_report_folder(report_id)
        pdf_path = ExecBriefBuilder.build_pdf(report_id, report_dir, lang=lang)
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({
                "success": False,
                "error": "执行简报 PDF 不可用（未开启 REPORT_EXEC_BRIEF/REPORT_PDF_EXPORT、缺该语种版本或构建失败）"
            }), 404
        current = ReportManager.publication_status(report_id, lang)
        if (not current.get("publishable") or any(current.get(key) != publication.get(key)
                for key in ("generation_id", "markdown_sha256"))):
            raise ArtifactError("stale_artifact", "Report publication changed while rendering the brief")

        download_name = (f"{report_id}.exec_brief.{lang}.pdf" if lang
                         else f"{report_id}.exec_brief.pdf")
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

    except ArtifactError as exc:
        return _artifact_error_response(exc)
    except Exception as e:
        logger.error(f"导出执行简报 PDF 失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/digest', methods=['GET'])
def get_report_digest(report_id: str):
    """惰性构建并返回 ~15 行 newsletter 式速览 reports/{id}/digest.md（DELIV-1）。

    与 /exec-brief 同源（build 一次同时产简报 + 速览），验证构建返回的内容与源指纹。
    REPORT_EXEC_BRIEF 关闭 / 报告缺失 / 本次速览构建失败 → 404。
    """
    try:
        from ..services.exec_brief import ExecBriefBuilder

        if not getattr(Config, "REPORT_EXEC_BRIEF", True):
            return jsonify({
                "success": False,
                "error": "速览不可用（REPORT_EXEC_BRIEF 未开启）",
            }), 404

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404

        publication = ReportManager.publication_status(report_id)
        if not publication.get("publishable"):
            return _publication_rejection(report_id, publication=publication)

        report_dir = ReportManager._get_report_folder(report_id)
        produced = ExecBriefBuilder.build(report_id, report_dir)
        digest_path = produced.get("digest")
        if not digest_path or not os.path.exists(digest_path):
            return jsonify({
                "success": False,
                "error": "速览不可用（未开启 REPORT_EXEC_BRIEF 或构建失败）"
            }), 404
        digest_bytes = ExecBriefBuilder.read_current(report_id, report_dir, digest_path)
        current = ReportManager.publication_status(report_id)
        if (not current.get("publishable")
                or current.get("markdown_sha256") != publication.get("markdown_sha256")):
            raise ArtifactError("stale_artifact", "Report publication changed while building the digest")

        return Response(
            digest_bytes,
            mimetype="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{report_id}.digest.md"'},
        )

    except ArtifactError as exc:
        return _artifact_error_response(exc)
    except Exception as e:
        logger.error(f"获取速览失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 报告可视化资源接口（VIZ-1）==============

@report_bp.route('/<report_id>/charts/<path:filename>', methods=['GET'])
def get_report_chart(report_id: str, filename: str):
    """服务报告可视化产物 reports/{id}/charts/<file>（PNG 图表 / Mermaid .mmd 代码块）。

    与 full_report.md 同源：文件都落在报告文件夹下，这里以 charts/ 子目录暴露。viz_manifest.json
    里的相对路径（'charts/xxx.png'）对 Web（经此端点）与 PDF（相对 report_dir 的文件系统路径）
    都成立。每次请求都重新做 realpath containment 并拒绝 symlink，防止登记后换链绕过。
    """
    try:
        if not ReportManager.get_report(report_id):
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}",
            }), 404
        if not ReportManager.is_publishable(report_id):
            return _publication_rejection(report_id)
        reports_root = os.path.realpath(ReportManager.REPORTS_DIR)
        report_dir = os.path.realpath(ReportManager._get_report_folder(report_id))
        if ReportManager.load_world_result(report_id):
            from ..services.world_simulation.artifacts import read_json
            from pathlib import Path
            manifest = read_json(Path(report_dir) / "viz_manifest.json")
            requested = "charts/" + str(filename or "")
            registered = any(
                requested in (item.get("path"), item.get("png_path"))
                and requested in (item.get("artifact_sha256") or {})
                for item in manifest.get("items", []) if isinstance(item, dict)
            )
            if not registered:
                return jsonify({"success": False, "error": "Chart is not in the sealed report manifest"}), 404
        charts_dir = os.path.realpath(os.path.join(report_dir, "charts"))
        raw = str(filename or "")
        parts = raw.split("/")
        allowed = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".html"}
        if (not raw or raw.startswith("/") or "\\" in raw or "%" in raw
                or any(ord(char) < 32 or ord(char) == 127 for char in raw)
                or any(part in ("", ".", "..") for part in parts)
                or os.path.splitext(parts[-1])[1].lower() not in allowed
                or os.path.commonpath([report_dir, reports_root]) != reports_root
                or os.path.commonpath([charts_dir, report_dir]) != report_dir
                or not os.path.isdir(charts_dir) or os.path.islink(charts_dir)):
            return jsonify({
                "success": False,
                "error": f"报告无可视化产物: {report_id}"
            }), 404
        candidate = os.path.join(charts_dir, *parts)
        candidate_real = os.path.realpath(candidate)
        if (os.path.commonpath([candidate_real, charts_dir]) != charts_dir
                or not os.path.isfile(candidate_real)
                or any(os.path.islink(os.path.join(charts_dir, *parts[:i]))
                       for i in range(1, len(parts) + 1))):
            return jsonify({"success": False, "error": f"图表不存在: {filename}"}), 404
        ext = os.path.splitext(candidate_real)[1].lower()
        if ext == ".html":
            # Interactive charts may contain agent-produced inline JS. Run them
            # in an opaque sandboxed origin: scripts work, app cookies/storage
            # and network access do not. The sandbox blocks external scripts,
            # so directory-mode charts get their sibling plotly.min.js spliced
            # in at serve time rather than a relaxed policy (utils/chart_html).
            inlined = inline_plotly_bundle(candidate_real)
            response = (Response(inlined, mimetype="text/html")
                        if inlined is not None else send_file(candidate_real))
        else:
            response = send_file(candidate_real)
        if ext == ".html":
            response.headers["Content-Security-Policy"] = (
                "sandbox allow-scripts; default-src 'none'; "
                "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                "img-src data: blob:; font-src data:; connect-src 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        elif ext == ".svg":
            # SVG is an active document format when opened top-level. Keep it in
            # an opaque sandbox and explicitly disable scripts/network access.
            response.headers["Content-Security-Policy"] = (
                "sandbox; default-src 'none'; script-src 'none'; "
                "style-src 'unsafe-inline'; img-src data:; font-src data:"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response
    except Exception as e:
        # werkzeug 对非法路径抛 NotFound（404）；其余异常统一 404 避免泄漏路径细节
        logger.warning(f"获取报告图表失败: report_id={report_id}, file={filename}, err={e}")
        return jsonify({
            "success": False,
            "error": f"图表不存在: {filename}"
        }), 404


@report_bp.route('/<report_id>/viz-manifest', methods=['GET'])
def get_report_viz_manifest(report_id: str):
    """获取报告可视化清单，兼容 legacy list 与 ReportVisualizer schema-v2。

    无清单（未开启可视化 / 无可渲染工件）→ 返回空列表（degrade-safe，前端据此不渲染图区）。
    """
    def safe_chart_path(value):
        from pathlib import PurePosixPath
        if (not isinstance(value, str) or not value.strip() or '\\' in value
                or '%' in value or any(ord(char) < 32 or ord(char) == 127 for char in value)):
            return None
        raw = value.strip().removeprefix('./')
        path = PurePosixPath(raw)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            return None
        # 报告图表端点只服务 report-owned charts/；其它相对路径不能借 manifest
        # 变成浏览器请求或泄漏本机绝对路径。
        if path.parts[0] != 'charts' or len(path.parts) < 2:
            return None
        return path.as_posix()

    def normalize_items(value):
        if not isinstance(value, list):
            return []
        out = []
        for row in value:
            if not isinstance(row, dict):
                continue
            primary = safe_chart_path(row.get('path'))
            if not primary:
                continue
            item = dict(row)
            item['path'] = primary
            if 'png_path' in item:
                png_path = safe_chart_path(item.get('png_path'))
                if png_path:
                    item['png_path'] = png_path
                else:
                    item.pop('png_path', None)
            out.append(item)
        return out

    try:
        import json as _json
        if not ReportManager.get_report(report_id):
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}",
            }), 404
        if not ReportManager.is_publishable(report_id):
            return _publication_rejection(report_id)
        manifest_path = os.path.join(
            ReportManager._get_report_folder(report_id), "viz_manifest.json"
        )
        if not os.path.exists(manifest_path):
            return jsonify({
                "success": True,
                "schema_version": 1,
                "data": [],
                "count": 0,
                "skipped": [],
            })
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = _json.load(f)
        if isinstance(manifest, dict):
            try:
                schema_version = int(manifest.get('schema_version', 2) or 2)
            except (TypeError, ValueError):
                schema_version = 2
            items = normalize_items(manifest.get('items'))
            skipped = manifest.get('skipped')
            if not isinstance(skipped, list):
                skipped = []
        else:
            schema_version = 1
            items = normalize_items(manifest)
            skipped = []
        return jsonify({
            "success": True,
            "schema_version": schema_version,
            "data": items,
            "count": len(items),
            "skipped": skipped,
        })
    except Exception as e:
        logger.error(f"获取可视化清单失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@report_bp.route('/<report_id>', methods=['DELETE'])
def delete_report(report_id: str):
    """删除报告"""
    try:
        success = ReportManager.delete_report(report_id)
        
        if not success:
            return jsonify({
                "success": False,
                "error": f"报告不存在: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "message": f"报告已删除: {report_id}"
        })
        
    except Exception as e:
        logger.error(f"删除报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Report Agent对话接口 ==============

@report_bp.route('/chat', methods=['POST'])
def chat_with_report_agent():
    """
    与Report Agent对话
    
    Report Agent可以在对话中自主调用检索工具来回答问题
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",        // 必填，模拟ID
            "message": "请解释一下舆情走向",    // 必填，用户消息
            "chat_history": [                   // 可选，对话历史
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."}
            ]
        }
    
    返回：
        {
            "success": true,
            "data": {
                "response": "Agent回复...",
                "tool_calls": [调用的工具列表],
                "sources": [信息来源]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        message = data.get('message')
        chat_history = data.get('chat_history', [])
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400
        
        if not message:
            return jsonify({
                "success": False,
                "error": "请提供 message"
            }), 400
        
        # 获取模拟和项目信息
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {state.project_id}"
            }), 404
        
        graph_id = state.graph_id or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "缺少图谱ID"
            }), 400
        
        _owner = pipeline_for_simulation(simulation_id)
        simulation_requirement = (_owner.get("prompt") if _owner else project.simulation_requirement) or ""
        
        # 创建Agent并进行对话（T4.1: best-effort 钉入研究档案）
        _dossier = load_research_dossier_for_simulation(simulation_id)
        agent = ReportAgent(
            graph_id=graph_id,
            simulation_id=simulation_id,
            simulation_requirement=simulation_requirement,
            situation_brief=_dossier.get("situation_brief"),
            actors=_dossier.get("actors"),
            sources=_dossier.get("sources"),
            research_report=_dossier.get("research_report"),
            official_data=_dossier.get("official_data"),
            news_market_context=_dossier.get("news_market_context"),
            **_manual_report_owner_kwargs(_owner),
            **(_dossier.get("report_artifacts") or {}),
        )

        result = agent.chat(message=message, chat_history=chat_history)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"对话失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 报告进度与分章节接口 ==============

@report_bp.route('/<report_id>/progress', methods=['GET'])
def get_report_progress(report_id: str):
    """
    获取报告生成进度（实时）
    
    返回：
        {
            "success": true,
            "data": {
                "status": "generating",
                "progress": 45,
                "message": "正在生成章节: 关键发现",
                "current_section": "关键发现",
                "completed_sections": ["执行摘要", "模拟背景"],
                "updated_at": "2025-12-09T..."
            }
        }
    """
    try:
        progress = ReportManager.get_progress(report_id)
        
        if not progress:
            return jsonify({
                "success": False,
                "error": f"报告不存在或进度信息不可用: {report_id}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": progress
        })
        
    except Exception as e:
        logger.error(f"获取报告进度失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/sections', methods=['GET'])
def get_report_sections(report_id: str):
    """
    获取已生成的章节列表（分章节输出）
    
    前端可以轮询此接口获取已生成的章节内容，无需等待整个报告完成
    
    返回：
        {
            "success": true,
            "data": {
                "report_id": "report_xxxx",
                "sections": [
                    {
                        "filename": "section_01.md",
                        "section_index": 1,
                        "content": "## 执行摘要\\n\\n..."
                    },
                    ...
                ],
                "total_sections": 3,
                "is_complete": false,
                "draft_withheld": false
            }
        }

    草稿闸门（_draft_exposure_gate）：只有已通过发布审计、或元信息可读且仍在活跃生成中的
    报告才下发章节正文；元信息缺失/损坏、终态未发布、生成中断（超时无活动）一律返回空章节。
    """
    try:
        withhold, report, publication = _draft_exposure_gate(report_id)
        sections = [] if withhold else ReportManager.get_generated_sections(report_id)
        is_complete = bool(
            report is not None
            and report.status == ReportStatus.COMPLETED
            and publication.get("publishable")
        )

        return jsonify({
            "success": True,
            "data": {
                "report_id": report_id,
                "sections": sections,
                "total_sections": len(sections),
                "is_complete": is_complete,
                "publishable": bool(publication.get("publishable")),
                "publication_issues": list(publication.get("reasons") or []),
                "draft_withheld": withhold,
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节列表失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/sections-partial', methods=['GET'])
def get_report_sections_partial(report_id: str):
    """ITEM-17：为「仍在生成中」的报告增量返回已完成章节，供前端 2s 轮询渐进式发布。

    返回契约（前端据此逐章渲染，无需等整篇完成）：
        {
            "success": true,
            "sections": [
                {"index": 1, "title": "执行摘要", "status": "completed",
                 "content_md": "## 执行摘要\\n\\n..."},
                {"index": 2, "title": "预测场景", "status": "generating", "content_md": ""}
            ],
            "done": false
        }

    实现完全基于磁盘文件读取（cheap，安全用于 2s 轮询）：
      · sections 取自已落盘的 section_XX.md（每个即一段已完成章节，status='completed'）；
        title 从章节正文首个 markdown 标题行解析，缺失回退 'Section N'。
      · 若 progress.json 记录了 current_section 且不在已完成集合中，追加一个占位条目
        （status='generating'，content_md=''），让前端能显示「正在生成: X」。
      · done=true 当且仅当 full_report.md 已落盘（终稿组装完成）。
      · 草稿闸门（_draft_exposure_gate）：元信息缺失/损坏、终态未发布、生成中断（超时无活动）
        的报告一律返回空 sections（draft_withheld=true），不读取章节文件。
    任一底层读取异常都 degrade 成安全空集（不 500，保证轮询稳定）。
    """
    try:
        import re as _re

        # ⓪ 草稿闸门先行：不得下发时直接返回空集，连章节文件都不读。
        withhold, _report, publication = _draft_exposure_gate(report_id)
        done = bool(publication.get("publishable"))
        if withhold:
            return jsonify({
                "success": True,
                "sections": [],
                "done": done,
                "publishable": done,
                "publication_issues": list(publication.get("reasons") or []),
                "draft_withheld": True,
            })

        def _parse_title(md: str, fallback: str) -> str:
            """从章节正文抽首个 markdown 标题（# ~ ######）作为标题；无标题 → fallback。"""
            for line in (md or "").splitlines():
                m = _re.match(r'^\s*#{1,6}\s+(.+?)\s*$', line)
                if m:
                    return m.group(1).strip()
            return fallback

        # ① 已完成章节（section_XX.md）——每段 status='completed'
        raw_sections = ReportManager.get_generated_sections(report_id)
        sections = []
        completed_titles = set()
        for s in raw_sections:
            idx = s.get("section_index")
            content = s.get("content", "") or ""
            title = _parse_title(content, fallback=f"Section {idx}")
            completed_titles.add(title)
            sections.append({
                "index": idx,
                "title": title,
                "status": "completed",
                "content_md": content,
            })

        # ② 正在生成的章节（来自 progress.json 的 current_section，占位、无正文）
        try:
            progress = ReportManager.get_progress(report_id)
        except Exception:  # noqa: BLE001 - 进度文件缺失/损坏不影响已完成章节返回
            progress = None
        if isinstance(progress, dict):
            current = (progress.get("current_section") or "").strip()
            status = progress.get("status")
            # 仅当报告仍在生成、当前章节有名且尚未落盘时，追加 generating 占位。
            if current and current not in completed_titles and status not in ("completed", "failed"):
                next_index = (max((s["index"] for s in sections if isinstance(s["index"], int)),
                                  default=0) + 1)
                sections.append({
                    "index": next_index,
                    "title": current,
                    "status": "generating",
                    "content_md": "",
                })

        # ③ done：最终 Markdown 的存在只是候选；只有 exact-byte audit
        # 通过才可向客户宣告完成（已由 ⓪ 的闸门一并算出）。
        return jsonify({
            "success": True,
            "sections": sections,
            "done": done,
            "publishable": done,
            "publication_issues": list(publication.get("reasons") or []),
            "draft_withheld": False,
        })

    except Exception as e:
        logger.error(f"获取分章节增量失败: {str(e)}")
        # degrade-safe：轮询端点即便异常也返回稳定空集，避免前端轮询中断
        return jsonify({
            "success": False,
            "sections": [],
            "done": False,
            "error": str(e),
        }), 500


@report_bp.route('/<report_id>/section/<int:section_index>', methods=['GET'])
def get_single_section(report_id: str, section_index: int):
    """
    获取单个章节内容
    
    返回：
        {
            "success": true,
            "data": {
                "filename": "section_01.md",
                "content": "## 执行摘要\\n\\n..."
            }
        }

    草稿闸门同 /sections：不得下发草稿时（元信息缺失/损坏、终态未发布、生成中断）返回 409。
    """
    try:
        withhold, _report, publication = _draft_exposure_gate(report_id)
        if withhold:
            return _publication_rejection(report_id, publication=publication)
        section_path = ReportManager._get_section_path(report_id, section_index)
        
        if not os.path.exists(section_path):
            return jsonify({
                "success": False,
                "error": f"章节不存在: section_{section_index:02d}.md"
            }), 404
        
        with open(section_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return jsonify({
            "success": True,
            "data": {
                "filename": f"section_{section_index:02d}.md",
                "section_index": section_index,
                "content": content
            }
        })
        
    except Exception as e:
        logger.error(f"获取章节内容失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 报告状态检查接口 ==============

@report_bp.route('/check/<simulation_id>', methods=['GET'])
def check_report_status(simulation_id: str):
    """
    检查模拟是否有报告，以及报告状态
    
    用于前端判断是否解锁Interview功能
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "has_report": true,
                "report_status": "completed",
                "report_id": "report_xxxx",
                "interview_unlocked": true
            }
        }
    """
    try:
        report = ReportManager.get_report_by_simulation(simulation_id)
        
        has_report = report is not None
        report_status = report.status.value if report else None
        report_id = report.report_id if report else None
        
        publication = (
            ReportManager.publication_status(report_id) if report_id else
            {"publishable": False, "reasons": []}
        )
        # 只有报告的 exact bytes 通过最终发布屏障后才解锁 interview。
        interview_unlocked = bool(publication.get("publishable"))
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "has_report": has_report,
                "report_status": report_status,
                "report_id": report_id,
                "interview_unlocked": interview_unlocked,
                "publishable": interview_unlocked,
                "publication_issues": list(publication.get("reasons") or []),
            }
        })
        
    except Exception as e:
        logger.error(f"检查报告状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Agent 日志接口 ==============

@report_bp.route('/<report_id>/agent-log', methods=['GET'])
def get_agent_log(report_id: str):
    """
    获取 Report Agent 的详细执行日志
    
    实时获取报告生成过程中的每一步动作，包括：
    - 报告开始、规划开始/完成
    - 每个章节的开始、工具调用、LLM响应、完成
    - 报告完成或失败
    
    发布闸门（_draft_exposure_gate）：未通过发布审计时——生成结束（completed/failed）、
    元信息缺失/损坏、或 pending/planning/generating 却超过 REPORT_IN_PROGRESS_STALE_SECONDS
    无生成活动（生成器崩溃）——章节正文草稿、LLM 原始响应与 ReACT 思考字段被隐去
    （draft_withheld=true，条目骨架保留）；活跃生成中照常实时下发。

    Query参数：
        from_line: 从第几行开始读取（可选，默认0，用于增量获取）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [
                    {
                        "timestamp": "2025-12-13T...",
                        "elapsed_seconds": 12.5,
                        "report_id": "report_xxxx",
                        "action": "tool_call",
                        "stage": "generating",
                        "section_title": "执行摘要",
                        "section_index": 1,
                        "details": {
                            "tool_name": "insight_forge",
                            "parameters": {...},
                            ...
                        }
                    },
                    ...
                ],
                "total_lines": 25,
                "from_line": 0,
                "has_more": false,
                "publishable": false,
                "publication_issues": [...],
                "draft_withheld": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_agent_log(report_id, from_line=from_line)
        log_data["logs"], gate = _gate_agent_log(report_id, log_data.get("logs") or [])
        log_data.update(gate)

        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"获取Agent日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/agent-log/stream', methods=['GET'])
def stream_agent_log(report_id: str):
    """
    获取完整的 Agent 日志（一次性获取全部；与 /agent-log 同一发布闸门）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 25
            }
        }
    """
    try:
        logs, gate = _gate_agent_log(report_id, ReportManager.get_agent_log_stream(report_id))

        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs),
                **gate,
            }
        })
        
    except Exception as e:
        logger.error(f"获取Agent日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 控制台日志接口 ==============

@report_bp.route('/<report_id>/console-log', methods=['GET'])
def get_console_log(report_id: str):
    """
    获取 Report Agent 的控制台输出日志
    
    实时获取报告生成过程中的控制台输出（INFO、WARNING等），
    这与 agent-log 接口返回的结构化 JSON 日志不同，
    是纯文本格式的控制台风格日志。
    
    Query参数：
        from_line: 从第几行开始读取（可选，默认0，用于增量获取）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [
                    "[19:46:14] INFO: 搜索完成: 找到 15 条相关事实",
                    "[19:46:14] INFO: 图谱搜索: graph_id=xxx, query=...",
                    ...
                ],
                "total_lines": 100,
                "from_line": 0,
                "has_more": false
            }
        }
    """
    try:
        from_line = request.args.get('from_line', 0, type=int)
        
        log_data = ReportManager.get_console_log(report_id, from_line=from_line)
        withhold, _report, _publication = _draft_exposure_gate(report_id)
        if withhold and isinstance(log_data, dict):
            log_data = {**log_data, "logs": _withhold_console_log_drafts(log_data.get("logs") or []),
                        "draft_withheld": True}
        
        return jsonify({
            "success": True,
            "data": log_data
        })
        
    except Exception as e:
        logger.error(f"获取控制台日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/console-log/stream', methods=['GET'])
def stream_console_log(report_id: str):
    """
    获取完整的控制台日志（一次性获取全部）
    
    返回：
        {
            "success": true,
            "data": {
                "logs": [...],
                "count": 100
            }
        }
    """
    try:
        logs = ReportManager.get_console_log_stream(report_id)
        withhold, _report, _publication = _draft_exposure_gate(report_id)
        if withhold:
            logs = _withhold_console_log_drafts(logs)
        
        return jsonify({
            "success": True,
            "data": {
                "logs": logs,
                "count": len(logs),
                "draft_withheld": withhold,
            }
        })
        
    except Exception as e:
        logger.error(f"获取控制台日志失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 工具调用接口（供调试使用）==============

@report_bp.route('/tools/search', methods=['POST'])
def search_graph_tool():
    """
    图谱搜索工具接口（供调试使用）
    
    请求（JSON）：
        {
            "graph_id": "mirofish_xxxx",
            "query": "搜索查询",
            "limit": 10
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        query = data.get('query')
        limit = data.get('limit', 10)
        
        if not graph_id or not query:
            return jsonify({
                "success": False,
                "error": "请提供 graph_id 和 query"
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.search_graph(
            graph_id=graph_id,
            query=query,
            limit=limit
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"图谱搜索失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/tools/statistics', methods=['POST'])
def get_graph_statistics_tool():
    """
    图谱统计工具接口（供调试使用）
    
    请求（JSON）：
        {
            "graph_id": "mirofish_xxxx"
        }
    """
    try:
        data = request.get_json() or {}
        
        graph_id = data.get('graph_id')
        
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "请提供 graph_id"
            }), 400
        
        from ..services.zep_tools import ZepToolsService
        
        tools = ZepToolsService()
        result = tools.get_graph_statistics(graph_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取图谱统计失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
