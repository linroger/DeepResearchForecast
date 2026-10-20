"""稳定版程序化 API 表面（/api/v1）——供 headless / 自动化消费方使用。

EXECPLAN2 I-9-5（programmatic API + Python SDK）。

动机
----
现有 /api/research、/api/graph、/api/simulation、/api/report 蓝图是为本机 Vue SPA
设计的：路由命名随前端演进、未承诺稳定、{success,data,error} 信封是隐式约定而非
文档化契约。CI 回测、定时重跑、第三方集成若直接打这些路由，会随前端重构而碎裂。

本模块把核心生命周期（run / status / list / dossier / forecast / resolve）收敛成一个
**版本化、文档化、薄别名** 的 /api/v1 表面。它**不复制业务逻辑**——一律委托给与
SPA 路由相同的 service 层（PipelineOrchestrator / PipelineManager / ReportManager +
backtest 评分器），从而杜绝 v1 与底层路由的语义漂移（见 design_sketch 的反漂移要求）。

可选降级 / 默认关
----------------
整个蓝图默认 **不注册**：仅当 Config.API_V1_ENABLED 为真时，create_app 才挂载它
（见 backend/app/__init__.py 的标注接线）。未开启时本机 SPA 与现有路由行为逐字节不变。

鉴权 / 暴露面
------------
不在此处重复鉴权——/api/* 的统一闸门（环回放行；非环回需 X-API-Token，常量时间比较）
已在 create_app 的 before_request 中实现（EXECPLAN2 F-13-0），/api/v1/* 自动继承。

稳定契约（所有 /api/v1/* 响应）
------------------------------
成功: {"success": true, "data": <对象>}
失败: {"success": false, "error": "<人类可读消息>"}（HTTP 4xx/5xx）
该信封与 SPA 路由一致；前端 frontend/src/api/index.js 解包逻辑同样适用于 SDK。

随附 Python SDK（sdk/deepagentforecast/client.py，本仓库外置薄封装）按本表面驱动：
    Client(base_url, api_token).run(prompt, depth=...).wait(pipeline_id)
    .forecast(report_id) / .resolve(report_id, outcome)
"""

import json
import os
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..config import Config
from ..services.pipeline_orchestrator import (
    PipelineManager,
    PipelineOrchestrator,
    preflight_pipeline,
    simulation_admission_error,
)
from ..services.world_simulation.contracts import WorldError
from ..services.report_agent import ReportManager
from ..services import forecast_feedback, forecast_ledger
from ..utils.atomic import write_json_atomic
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.v1')

# /api/v1 稳定表面蓝图。仅在 Config.API_V1_ENABLED 时由 create_app 注册（默认关）。
# EXECPLAN2 I-9-5
sdk_bp = Blueprint('sdk_v1', __name__)

# 入参取值域——与 research.py 的 POST /run 保持一致，避免 v1 与 SPA 路由校验漂移。
_VALID_DEPTH = {"quick", "standard", "deep"}
_VALID_MODE = {"full", "research_only"}
_VALID_LANGUAGES = {"Chinese", "English", "auto"}


def _ok(data, status: int = 200):
    """统一成功信封。"""
    return jsonify({"success": True, "data": data}), status


def _err(message: str, status: int = 400):
    """统一失败信封。"""
    return jsonify({"success": False, "error": message}), status


@sdk_bp.route('/run', methods=['POST'])
def v1_run():
    """启动统一研究→预测管线，立即返回 {pipeline_id, task_id, mode, status}。

    EXECPLAN2 I-9-5。委托 PipelineOrchestrator.start（与 /api/research/run 同一入口），
    校验逻辑刻意与之对齐：起飞前做 preflight 体检，避免拼错模型名后烧完研究额度才报错。

    请求 (application/json):
        prompt: str       预测/研究问题（必填）
        mode: str         full | research_only（默认 full）
        depth: str        quick | standard | deep（默认取 Config.DEERFLOW_RESEARCH_DEPTH）
        project_name: str 可选
        max_rounds: int   OASIS 最大轮数（可选）
        language: str     Chinese | English | auto（可选）
        model: str        研究模型（可选；须在 Config.SUPPORTED_DEERFLOW_MODELS 内）
        simulation_engine: str  可选；省略采用 fresh default，显式 null 无效
        world_spec / world_policy_spec: dict  可选；使用同一 fresh admission 契约
    """
    try:
        data = request.get_json(silent=True) or {}
        prompt = (data.get('prompt') or '').strip()
        if not prompt:
            return _err("缺少 prompt")

        mode = (data.get('mode') or 'full').strip().lower()
        if mode not in _VALID_MODE:
            return _err(f"mode 必须是 {sorted(_VALID_MODE)} 之一")

        depth = (data.get('depth') or Config.DEERFLOW_RESEARCH_DEPTH).strip().lower()
        if depth not in _VALID_DEPTH:
            return _err(f"depth 必须是 {sorted(_VALID_DEPTH)} 之一")

        max_rounds = data.get('max_rounds')
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
            except (TypeError, ValueError):
                return _err("max_rounds 必须是整数")

        language = (data.get('language') or '').strip() or None
        if language is not None and language not in _VALID_LANGUAGES:
            return _err(f"language 必须是 {sorted(_VALID_LANGUAGES)} 之一")
        if language == 'auto':
            language = ''  # 空串 → 不传 --target-language，交给模型自选

        model = (data.get('model') or '').strip() or None
        if model is not None and model.lower() not in Config.SUPPORTED_DEERFLOW_MODELS:
            return _err(
                f"model 必须是 {', '.join(Config.SUPPORTED_DEERFLOW_MODELS)} 之一"
            )
        if model:
            model = model.lower()

        # 起飞前体检（与 SPA 路由同一套，杜绝漂移）
        preflight_errors = preflight_pipeline(mode=mode, model=model)
        if preflight_errors:
            return jsonify({
                "success": False,
                "error": "启动前检查未通过：\n" + "\n".join(f"• {e}" for e in preflight_errors),
                "preflight_errors": preflight_errors,
            }), 400

        state = PipelineOrchestrator.start(
            prompt=prompt,
            mode=mode,
            project_name=data.get('project_name'),
            depth=depth,
            max_rounds=max_rounds,
            language=language,
            model=model,
            **{key: data[key] for key in
               ('simulation_engine', 'world_spec', 'world_policy_spec') if key in data},
        )
        return _ok({
            "pipeline_id": state.pipeline_id,
            "task_id": state.task_id,
            "mode": state.mode,
            "status": state.status,
        })
    except WorldError as error:
        body, status = simulation_admission_error(error)
        return jsonify(body), status
    except Exception as e:
        logger.error(f"[v1] 启动管线失败: {e}", exc_info=True)
        return _err(str(e), 500)


@sdk_bp.route('/status/<pipeline_id>', methods=['GET'])
def v1_status(pipeline_id: str):
    """返回管线聚合进度（直接读 pipeline_state.json，可在后端重启后存活）。

    EXECPLAN2 I-9-5。委托 PipelineManager.load。SDK 的 .wait() 轮询此端点直至 status
    进入终态（completed / failed / cancelled）。
    """
    try:
        data = PipelineManager.load(pipeline_id)
        if data is None:
            return _err("管线不存在", 404)
        return _ok(data)
    except Exception as e:
        logger.error(f"[v1] 查询管线状态失败: {e}", exc_info=True)
        return _err(str(e), 500)


@sdk_bp.route('/list', methods=['GET'])
def v1_list():
    """返回最近管线列表。

    EXECPLAN2 I-9-5。委托 PipelineManager.list_pipelines（与 /api/research/list 同源）。
    """
    try:
        return _ok({"pipelines": PipelineManager.list_pipelines()})
    except Exception as e:
        logger.error(f"[v1] 列出管线失败: {e}", exc_info=True)
        return _err(str(e), 500)


@sdk_bp.route('/dossier/<pipeline_id>', methods=['GET'])
def v1_dossier(pipeline_id: str):
    """返回深度研究产出的研究报告 + 结构化 actors/sources/timeline。

    EXECPLAN2 I-9-5。读取与 /api/research/<id>/dossier 相同的 handoff 产物，保持契约一致。
    """
    try:
        handoff = PipelineManager.handoff_dir(pipeline_id)
        if not os.path.isdir(handoff):
            return _err("管线不存在", 404)

        def _read(name):
            p = os.path.join(handoff, name)
            if os.path.exists(p):
                try:
                    with open(p, 'r', encoding='utf-8') as f:
                        return f.read()
                except OSError:
                    return None
            return None

        report = _read('research_report.md')
        actors_raw = _read('actors.json')
        sources_raw = _read('sources.json')
        timeline_raw = _read('timeline.json')
        return _ok({
            "report": report,
            "actors": json.loads(actors_raw) if actors_raw else None,
            "sources": json.loads(sources_raw) if sources_raw else None,
            "timeline": json.loads(timeline_raw) if timeline_raw else None,
            "has_report": report is not None,
        })
    except Exception as e:
        logger.error(f"[v1] 获取研究档案失败: {e}", exc_info=True)
        return _err(str(e), 500)


def _forecast_path(report_id: str) -> str:
    """报告文件夹下的结构化预测对象路径（report_agent 在 REPORT_STRUCTURED_FORECAST 开启时落盘）。"""
    return os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")


def _resolved_path(report_id: str) -> str:
    """预测判定结果落盘路径（resolve 端点写入；backtest 工具可消费）。"""
    return os.path.join(ReportManager._get_report_folder(report_id), "resolved.json")


def _load_forecast(report_id: str):
    """读取并解析某报告的结构化预测对象；不存在/损坏返回 None。"""
    return ReportManager.load_structured_forecast(report_id)


@sdk_bp.route('/forecast/<report_id>', methods=['GET'])
def v1_forecast(report_id: str):
    """返回某报告的机器可读结构化预测对象（情景 + 概率 + 判定标准 + 引用审计）。

    EXECPLAN2 I-9-5 / I-3-0。该对象由 report_agent 在 Config.REPORT_STRUCTURED_FORECAST
    开启后随报告完成落盘到 forecast.json。若报告存在但无结构化预测，返回 409 并提示如何开启，
    而不是 404，以便调用方区分「报告不存在」与「未启用结构化预测」。
    """
    try:
        report = ReportManager.get_report(report_id)
        if report is None:
            return _err(f"报告不存在: {report_id}", 404)
        publication = ReportManager.publication_status(report_id)
        if not publication.get("publishable"):
            return _err(
                "该报告未通过当前发布完整性门，结构化预测不可对外读取："
                + "；".join(publication.get("reasons") or []),
                409,
            )
        forecast = _load_forecast(report_id)
        if forecast is None:
            return _err(
                "该报告无结构化预测（需在生成报告时启用 REPORT_STRUCTURED_FORECAST=true）",
                409,
            )
        # 若已有判定结果，一并附上，便于 SDK 单次拉全。
        resolved = None
        rpath = _resolved_path(report_id)
        if os.path.exists(rpath):
            try:
                with open(rpath, 'r', encoding='utf-8') as f:
                    resolved = json.load(f)
            except (OSError, json.JSONDecodeError):
                resolved = None
        return _ok({
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "forecast": forecast,
            "resolved": resolved,
        })
    except Exception as e:
        logger.error(f"[v1] 获取结构化预测失败: {e}", exc_info=True)
        return _err(str(e), 500)


@sdk_bp.route('/resolve/<report_id>', methods=['POST'])
def v1_resolve(report_id: str):
    """人工判定已登记的发布预测，并返回原始概率的 Brier/log-loss 评分。

    不可变发布账本是判定事实的权威来源；resolved.json 是可在重试时修复的镜像。
    同一结果重试保留最初的时间与证据，冲突返回 409。未登记的旧报告禁止事后补录。

    请求 (application/json):
        outcome: str   发布快照中唯一、完全匹配的情景名（区分大小写）
        outcomes: str | [str]   兼容别名；列表必须只有一项
        evidence / source: 可选的人工判定依据，未经外部核验

    返回:
        {report_id, outcome, scoring: {brier, realized_probability, log_loss, ...}}
    """
    try:
        report = ReportManager.get_report(report_id)
        if report is None:
            return _err(f"报告不存在: {report_id}", 404)

        publication = ReportManager.publication_status(report_id)
        if not publication.get("publishable"):
            return _err(
                "该报告未通过当前发布完整性门，禁止写入判定/校准账本："
                + "；".join(publication.get("reasons") or []),
                409,
            )

        published = forecast_ledger.read_published_forecast(report_id)
        if published is None:
            return _err(
                "该报告没有发布时保留的原始预测快照，禁止在结果已知后补录。"
                "请重新生成并发布报告以保留原始快照 "
                "(regenerate/publish with a retained original forecast snapshot)。",
                409,
            )

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return _err("请求必须是 JSON 对象，包含 outcome 或 outcomes")
        outcome = data.get("outcome")
        if "outcomes" in data:
            alias = data["outcomes"]
            if isinstance(alias, list):
                if len(alias) != 1:
                    return _err("outcomes 列表必须包含且仅包含一个情景名")
                alias = alias[0]
            if not isinstance(alias, str) or not alias.strip():
                return _err("outcomes 必须是情景名字符串或单元素字符串列表")
            if outcome is not None and outcome != alias:
                return _err("outcome 与 outcomes 指定了不同的结果，无法唯一判定")
            outcome = alias
        if not isinstance(outcome, str) or not outcome.strip():
            return _err("缺少有效 outcome（实际发生的情景名字符串）")

        forecast = published["forecast"]
        matches = [
            scenario for scenario in forecast.get("scenarios", [])
            if isinstance(scenario, dict) and scenario.get("name") == outcome
        ]
        if len(matches) != 1:
            return _err("outcome 必须完全匹配发布快照中唯一的情景名（区分大小写）")

        # A caller's citation is retained as submitted, never promoted to a
        # verified external outcome. Older calls need no additional fields.
        evidence = {"adjudication": "manual_user", "externally_verified": False}
        for field in ("evidence", "source"):
            if field in data:
                evidence[field] = data[field]
        resolution = forecast_ledger.resolve_published_scenario(
            report_id,
            outcome,
            evidence=evidence,
            resolved_at=datetime.now(timezone.utc).isoformat(),
        )
        scoring = resolution["score"]
        record = {
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "outcome": resolution["outcome"],
            "scoring": scoring,
            "resolved_at": resolution["resolved_at"],
            "kind": resolution["kind"],
            "publication_sha256": resolution["publication_sha256"],
            "evidence": resolution["evidence"],
            "forecast": forecast,
        }
        # Persist the authoritative outcome first. If the mirror fails, expose
        # the failure; a same-outcome retry after restart repairs it from the
        # ledger's original timestamp, evidence, probabilities and score.
        write_json_atomic(_resolved_path(report_id), record, allow_nan=False)
        logger.info(
            f"[v1] 预测已判定: {report_id} outcome='{outcome}' "
            f"brier={scoring.get('brier')} matched={scoring.get('outcome_matched_a_scenario')}"
        )
        return _ok({
            "report_id": report_id,
            "outcome": resolution["outcome"],
            "scoring": scoring,
            "resolved_at": resolution["resolved_at"],
            "evidence": resolution["evidence"],
        })
    # Look up the live class: a module reload can leave the ledger's re-export
    # pointing at an older class while its functions raise the replacement.
    except forecast_feedback.ForecastFeedbackError as e:
        return _err(f"{e.code}: {e}", 409)
    except Exception as e:
        logger.error(f"[v1] 判定预测失败: {e}", exc_info=True)
        return _err(str(e), 500)
