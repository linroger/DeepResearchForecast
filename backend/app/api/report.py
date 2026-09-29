"""
Report API路由
提供模拟报告生成、获取、对话等接口
"""

import hashlib
import os
import time
import traceback
import threading
from flask import request, jsonify, send_file, send_from_directory, Response

from . import report_bp
from ..config import Config
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.pipeline_orchestrator import load_research_dossier_for_simulation
from ..services.simulation_manager import SimulationManager
from ..models.project import ProjectManager
from ..models.task import TaskManager, TaskStatus
from ..utils.chart_html import inline_plotly_bundle
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.report')


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


def _report_publication_payload(report):
    """Return report metadata without leaking an unaudited draft body.

    Unpublishable reports keep their state and outline skeleton, but both the
    assembled Markdown and every outline section's draft content are withheld.
    """
    publication = ReportManager.publication_status(report.report_id)
    payload = report.to_dict()
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
    return payload


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


def _active_translation_task(report_id: str, lang: str):
    """Return the newest in-flight task for exactly one report/language pair."""
    for task in TaskManager().list_tasks(task_type="report_translate"):
        metadata = task.get("metadata") or {}
        if (metadata.get("report_id") == report_id
                and metadata.get("lang") == lang
                and task.get("status") in {
                    TaskStatus.PENDING.value, TaskStatus.PROCESSING.value,
                }):
            return task
    return None


def _launch_translation_thread(target) -> None:
    """Small seam kept explicit so API tests can run the worker synchronously."""
    threading.Thread(target=target, daemon=True).start()


# ============== 报告生成接口 ==============

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
        
        simulation_requirement = project.simulation_requirement
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
                _dossier = load_research_dossier_for_simulation(simulation_id)
                agent = ReportAgent(
                    graph_id=graph_id,
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    situation_brief=_dossier.get("situation_brief"),
                    actors=_dossier.get("actors"),
                    sources=_dossier.get("sources"),
                    research_report=_dossier.get("research_report"),
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
    if lang is None:
        forecast = ReportManager.load_structured_forecast(report_id)
        localization = {"requested_lang": None, "localized": False}
    else:
        forecast, localization = ReportManager.load_localized_forecast(report_id, lang)
    return jsonify({
        "success": True,
        "data": {
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "forecast": forecast,
            "available": forecast is not None,
            "localization": localization,
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

        md_path = ReportManager._get_report_translation_path(report_id, lang)
        if not os.path.exists(md_path):
            return jsonify({
                "success": False,
                "error": f"该报告暂无 {lang} 版本: {report_id}"
            }), 404
        if not ReportManager.is_publishable(report_id, lang):
            return _publication_rejection(report_id, lang)

        return send_file(
            md_path,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=f"{report_id}.{lang}.md",
        )

    except Exception as e:
        logger.error(f"获取双语报告失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@report_bp.route('/<report_id>/translations/<lang>', methods=['POST'])
def generate_report_translation(report_id: str, lang: str):
    """Start one publication-gated, deduplicated language-variant retry.

    Report completion still attempts translation automatically.  This endpoint
    exists so a rejected/temporarily failed sidecar remains recoverable from the
    UI without rerunning research, graph, simulation, or the English report.
    """
    lang = (lang or "").strip().lower()
    if lang not in ReportManager._TRANSLATION_LANGS:
        return jsonify({
            "success": False,
            "error": f"不支持的语种: {lang}（仅 en / zh）",
        }), 400
    report = ReportManager.get_report(report_id)
    if report is None:
        return jsonify({
            "success": False,
            "error": f"报告不存在: {report_id}",
        }), 404
    # ?force=1 regenerates a published variant (e.g. one an older translation engine
    # produced — translation_status reports it as outdated); the published variant
    # stays until the new one passes the audit.
    force = (request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}
    task_manager = TaskManager()

    def _in_progress_response(state, active):
        return jsonify({
            "success": True,
            "data": {
                **state,
                # A task-bound answer describes the task: an update of a published
                # variant is not "available" until the task itself succeeds.
                "available": False,
                "status": active["status"],
                "task_id": active["task_id"],
                "progress": active.get("progress", 0),
                "message": active.get("message", ""),
            },
        }), 202

    # A running generation holds the lease below for its whole run (minutes).
    # Answer a duplicate request (second tab, click after a reload) from the task
    # and durable runtime state first, instead of blocking it on that lease.
    active = _active_translation_task(report_id, lang)
    if active:
        state = ReportManager.translation_status(report_id, lang, report=report)
        return _in_progress_response(state, active)
    state = ReportManager.translation_status(report_id, lang, report=report)
    if state.get("status") == "generating":
        return jsonify({"success": True, "data": state}), 202

    with ReportManager._translation_generation_lease(report_id, lang):
        # Re-read under the cross-process lease.  This makes the durable task
        # record the deduplication authority even when another worker owns the
        # in-memory TaskManager entry.
        state = ReportManager.translation_status(report_id, lang, report=report)
        regenerate = bool(force and state.get("available"))
        if state.get("available") and not regenerate:
            return jsonify({"success": True, "data": state})
        active = _active_translation_task(report_id, lang)
        if active:
            return _in_progress_response(state, active)
        if state.get("status") == "generating":
            return jsonify({"success": True, "data": state}), 202
        if not state.get("can_generate"):
            return jsonify({
                "success": False,
                "error": "该报告当前不能生成所请求的翻译版本",
                "data": state,
            }), 409

        task_id = task_manager.create_task(
            task_type="report_translate",
            metadata={"report_id": report_id, "lang": lang},
        )
        source_sha = hashlib.sha256(
            (report.markdown_content or "").encode("utf-8")
        ).hexdigest()
        owner = f"pid:{os.getpid()}"
        ReportManager._set_translation_runtime_status(
            report_id,
            lang,
            TaskStatus.PENDING.value,
            source_markdown_sha256=source_sha,
            task_id=task_id,
            owner=owner,
            progress=0,
            message="翻译任务已排队",
            issues=[],
        )

    def run_translation() -> None:
        try:
            task_manager.update_task(
                task_id,
                status=TaskStatus.PROCESSING,
                progress=5,
                message="正在生成并审计翻译版本",
            )
            result = ReportManager.generate_translation_variant(
                report_id,
                lang,
                progress_callback=lambda progress, message: task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=progress,
                    message=message,
                ),
                force=regenerate,
            )
            if result.get("available") and result.get("updated", True):
                ReportManager._set_translation_runtime_status(
                    report_id,
                    lang,
                    "available",
                    source_markdown_sha256=source_sha,
                    task_id=task_id,
                    owner=owner,
                    markdown_sha256=result.get("markdown_sha256"),
                    progress=100,
                    message="translation passed isolated publication audit",
                    issues=[],
                )
                task_manager.complete_task(task_id, result=result)
                return
            issues = "; ".join(result.get("issues") or [])
            ReportManager._set_translation_runtime_status(
                report_id,
                lang,
                "failed",
                source_markdown_sha256=source_sha,
                task_id=task_id,
                owner=owner,
                progress=100,
                message=issues or "翻译版本未通过发布审计",
                issues=list(result.get("issues") or [])[:12],
            )
            task_manager.fail_task(task_id, issues or "翻译版本未通过发布审计")
        except Exception as exc:  # noqa: BLE001 — task captures exact terminal failure
            logger.error(
                "报告翻译任务失败 report_id=%s lang=%s: %s",
                report_id,
                lang,
                exc,
            )
            ReportManager._set_translation_runtime_status(
                report_id,
                lang,
                "failed",
                source_markdown_sha256=source_sha,
                task_id=task_id,
                owner=owner,
                progress=100,
                message=str(exc),
                issues=[str(exc)],
            )
            task_manager.fail_task(task_id, str(exc))

    _launch_translation_thread(run_translation)
    return jsonify({
        "success": True,
        "data": {
            **state,
            "available": False,
            "status": TaskStatus.PENDING.value,
            "task_id": task_id,
            "progress": 0,
            "message": "翻译任务已启动",
        },
    }), 202


@report_bp.route('/<report_id>/translations/<lang>/status', methods=['GET'])
def get_report_translation_status(report_id: str, lang: str):
    """Return durable artifact state plus optional in-memory task progress."""
    lang = (lang or "").strip().lower()
    if lang not in ReportManager._TRANSLATION_LANGS:
        return jsonify({"success": False, "error": "不支持的语种"}), 400
    report = ReportManager.get_report(report_id)
    if report is None:
        return jsonify({
            "success": False,
            "error": f"报告不存在: {report_id}",
        }), 404
    state = ReportManager.translation_status(report_id, lang, report=report)
    task_id = (request.args.get("task_id") or "").strip()
    task = TaskManager().get_task(task_id) if task_id else None
    if task is not None:
        task_data = task.to_dict()
        metadata = task_data.get("metadata") or {}
        if metadata.get("report_id") != report_id or metadata.get("lang") != lang:
            return jsonify({
                "success": False,
                "error": "任务与报告或语种不匹配",
            }), 409
        task_result = task_data.get("result")
        task_result = task_result if isinstance(task_result, dict) else {}
        return jsonify({
            "success": True,
            "data": {
                **state,
                # Availability of *this task's* output: while updating a published
                # variant the old one stays available, which must not read as done.
                "available": bool(
                    task_data["status"] == TaskStatus.COMPLETED.value
                    and task_result.get("available")
                    and task_result.get("updated", True)
                ),
                "status": task_data["status"],
                "task_id": task_id,
                "progress": task_data.get("progress", 0),
                "message": task_data.get("message", ""),
                "error": task_data.get("error"),
                "result": task_data.get("result"),
            },
        })
    if state.get("available"):
        return jsonify({"success": True, "data": state})

    active = _active_translation_task(report_id, lang)
    if active:
        state.update({
            "status": active["status"],
            "task_id": active["task_id"],
            "progress": active.get("progress", 0),
            "message": active.get("message", ""),
        })
    return jsonify({"success": True, "data": state})


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
        if raw_lang is not None and lang and lang not in ReportManager._TRANSLATION_LANGS:
            return jsonify({
                "success": False,
                "error": f"不支持的语种: {lang}（仅 en / zh）",
            }), 400
        lang = lang if lang in ReportManager._TRANSLATION_LANGS else None

        if not getattr(Config, "REPORT_PDF_EXPORT", True):
            return jsonify({
                "success": False,
                "error": "PDF 导出服务未启用",
                "code": "pdf_export_disabled",
            }), 503

        if not ReportManager.is_publishable(report_id, lang):
            return _publication_rejection(report_id, lang)

        pdf_path = ReportManager.export_pdf(report_id, lang=lang)
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({
                "success": False,
                "error": "PDF 构建未通过渲染或内容完整性门",
                "code": "pdf_build_failed",
            }), 503

        download_name = f"{report_id}.{lang}.pdf" if lang else f"{report_id}.pdf"
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

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
    成稿 + forecast.json 抽取），随后按源 mtime 缓存复用。REPORT_EXEC_BRIEF 关闭 / 报告缺失 / 简报
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

        if not ReportManager.is_publishable(report_id, lang):
            return _publication_rejection(report_id, lang)

        report_dir = ReportManager._get_report_folder(report_id)
        ExecBriefBuilder.build(report_id, report_dir)

        brief_path = ExecBriefBuilder.brief_path(report_dir, lang)
        if not os.path.exists(brief_path):
            return jsonify({
                "success": False,
                "error": "执行简报不可用（未开启 REPORT_EXEC_BRIEF、缺该语种版本或构建失败）"
            }), 404

        return send_file(
            brief_path,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=(f"{report_id}.exec_brief.{lang}.md" if lang
                           else f"{report_id}.exec_brief.md"),
        )

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
    页），按简报 md 的 mtime 缓存。REPORT_EXEC_BRIEF / REPORT_PDF_EXPORT 关闭、报告/简报缺失、构建
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

        if not ReportManager.is_publishable(report_id, lang):
            return _publication_rejection(report_id, lang)

        report_dir = ReportManager._get_report_folder(report_id)
        # 先构建 md（PDF 依赖简报 md），再导 PDF。
        ExecBriefBuilder.build(report_id, report_dir)
        pdf_path = ExecBriefBuilder.build_pdf(report_id, report_dir, lang=lang)
        if not pdf_path or not os.path.exists(pdf_path):
            return jsonify({
                "success": False,
                "error": "执行简报 PDF 不可用（未开启 REPORT_EXEC_BRIEF/REPORT_PDF_EXPORT、缺该语种版本或构建失败）"
            }), 404

        download_name = (f"{report_id}.exec_brief.{lang}.pdf" if lang
                         else f"{report_id}.exec_brief.pdf")
        return send_file(
            pdf_path,
            as_attachment=True,
            download_name=download_name,
            mimetype="application/pdf",
        )

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

    与 /exec-brief 同源（build 一次同时产简报 + 速览），按 full_report.md / forecast.json 的 mtime
    缓存。REPORT_EXEC_BRIEF 关闭 / 报告缺失 / 速览未生成 → 404（degrade-safe）。
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

        if not ReportManager.is_publishable(report_id):
            return _publication_rejection(report_id)

        report_dir = ReportManager._get_report_folder(report_id)
        ExecBriefBuilder.build(report_id, report_dir)

        digest_path = ExecBriefBuilder.digest_path(report_dir)
        if not os.path.exists(digest_path):
            return jsonify({
                "success": False,
                "error": "速览不可用（未开启 REPORT_EXEC_BRIEF 或构建失败）"
            }), 404

        return send_file(
            digest_path,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=f"{report_id}.digest.md",
        )

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
        
        simulation_requirement = project.simulation_requirement or ""
        
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
