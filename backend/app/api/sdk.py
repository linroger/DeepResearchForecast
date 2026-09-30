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
import traceback
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from ..config import Config
from ..services import forecast_ledger, forecast_resolution
from ..services.pipeline_orchestrator import (
    PipelineManager,
    PipelineOrchestrator,
    preflight_pipeline,
)
from ..services.report_agent import ReportManager
from ..services.backtest import score_forecast
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
# EVAL-4：未携带 outcome_known_at + evidence 的判定只写 resolved.json，不进校准账本。
_SETTLEMENT_NEEDS_ATTESTATION = "outcome_known_at and evidence required to enter calibration"
_SUPERSEDES_HINT = "（请用 forecast_tools resolve --supersedes 更正或撤回）"


def _plan_scenario_attestation(target, outcome, known_at, evidence):
    """EVAL-4：按当前账本规划一条情景集人工证明（forecast_resolution.plan_manual_settlement）。"""
    return forecast_resolution.plan_manual_settlement(
        target, forecast_resolution.SCENARIO_ITEM, outcome, known_at, evidence,
        existing_events=forecast_ledger.read_market_resolutions(),
        processed_at=datetime.now(timezone.utc).isoformat())


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
        )
        return _ok({
            "pipeline_id": state.pipeline_id,
            "task_id": state.task_id,
            "mode": state.mode,
            "status": state.status,
        })
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
    """对一条结构化预测做判定（horizon 到期、真实结果已知后），返回 Brier/log-loss 评分。

    EXECPLAN2 I-9-5 / I-9-2。委托 backtest.score_forecast（与 forecast_tools.py CLI 同源
    评分器），并把 {outcome, scoring, resolved_at} 原子落盘到 resolved.json，供后续
    calibration_report 跨多条已判定预测做校准。

    请求 (application/json):
        outcome: str            实际发生的情景名（按评分器的 ensemble._norm_name 归一后须恰好
                                匹配 forecast.scenarios[*].name 之一）
        outcome_known_at: str   可选（EVAL-4）：结果为人所知的时刻（YYYY-MM-DD 或带 Z/时区偏移的
                                ISO 时刻，不得晚于当前）
        evidence: str           可选（EVAL-4）：http(s) URL 或不少于 20 字符的说明

    EVAL-4（人工结算）：
    - outcome 未匹配任何情景（或同时匹配多个）→ 400，且不写 resolved.json（此前会落盘并被
      计为全错）。
    - 同时携带 outcome_known_at 与 evidence：先校验这两项（validate_manual_attestation，
      与目标无关，非法 → 400）；判定目标取 load_manual_target（生产 primary 账本行，否则发布时
      可发布且已封印的报告本身；取不到 → 409）；再按 forecast_resolution 的人工结算规则校验
      （非法 → 400）；该情景集已有不同的人工证明 → 409（须用 forecast_tools resolve
      --supersedes 更正/撤回）。通过后先向 resolutions.jsonl 追加一条 attested 基准的
      scenario_set 事件（与 CLI 同一构造器），再写 resolved.json：账本未接受时按最新账本
      重判——并发请求已写入相同证明 → 视同 no-op；不同证明 → 409；账本不可写 → 500；
      后两者都不写 resolved.json。只给其一 → 400。
    - 两者都不带：保持只写 resolved.json 的旧行为。

    返回:
        {report_id, outcome, scoring: {brier, realized_probability, log_loss, ...},
         settlement: {recorded, event_key, reason}}
        event_key 为该事件的 market_id（'manual' 或 'manual:r<n>'，即 --supersedes 的取值）。
        reason：None（已入账）；'already_recorded'（相同证明已在账）；缺证明时为
        _SETTLEMENT_NEEDS_ATTESTATION；目标是无生产 primary 账本行的报告本身时为
        forecast_resolution.MANUAL_NOT_BINDABLE（已入账，但 resolved_view 只标注生产 primary
        commit 行，故不进任何校准）。
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

        forecast = _load_forecast(report_id)
        if forecast is None:
            return _err(
                "该报告无结构化预测，无法判定（需在生成报告时启用 REPORT_STRUCTURED_FORECAST=true）",
                409,
            )

        data = request.get_json(silent=True) or {}
        # 接受 outcome（单一实际情景名）。design_sketch 写作 resolve(report_id, outcomes)，
        # 故同时容忍 outcomes 别名（取列表首项或字符串），向后兼容更宽的调用方。
        outcome = data.get('outcome')
        if outcome is None and 'outcomes' in data:
            raw = data.get('outcomes')
            if isinstance(raw, list):
                outcome = raw[0] if raw else None
            else:
                outcome = raw
        outcome = (str(outcome).strip() if outcome is not None else "")
        if not outcome:
            return _err("缺少 outcome（实际发生的情景名）")

        # EVAL-4：未匹配 / 多重匹配的 outcome 会被评分器当作全错，绝不落盘。
        _, unmatched = forecast_resolution.match_scenario_name(forecast.get("scenarios"), outcome)
        if unmatched is not None:
            names = [str(s.get("name")) for s in (forecast.get("scenarios") or [])
                     if isinstance(s, dict)]
            return _err(f"outcome 须恰好匹配一个情景名（{unmatched}）：{names}", 400)

        known_at = data.get('outcome_known_at')
        evidence = data.get('evidence')
        target = plan = None
        if known_at is not None or evidence is not None:
            if known_at is None or evidence is None:
                return _err("outcome_known_at 与 evidence 须同时提供", 400)
            # 与目标无关的输入先校验：非法输入一律 400，不因缺目标先报 409。
            ok, errors = forecast_resolution.validate_manual_attestation(known_at, evidence)
            if not ok:
                return _err("；".join(errors), 400)
            target, reason = forecast_resolution.load_manual_target(report_id)
            if target is None:
                return _err(f"该报告没有可入账校准的预测目标：{reason}", 409)
            plan = _plan_scenario_attestation(target, outcome, known_at, evidence)
            if plan["status"] == "invalid":
                return _err("；".join(plan["errors"]), 400)
            if plan["status"] == "exists":
                return _err("；".join(plan["errors"]) + _SUPERSEDES_HINT, 409)

        scoring = score_forecast(forecast, outcome)

        record = {
            "report_id": report_id,
            "simulation_id": report.simulation_id,
            "outcome": outcome,
            "scoring": scoring,
            "resolved_at": datetime.now().isoformat(),
            # 内嵌当时的预测快照，便于把多条 resolved.json 直接喂给 backtest 校准（{forecast, outcome}）。
            "forecast": forecast,
        }
        settlement = {"recorded": False, "event_key": None,
                      "reason": _SETTLEMENT_NEEDS_ATTESTATION}
        if plan is not None and plan["status"] == "append":
            # 先入账、后写 resolved.json：并发的另一请求若抢先写入了不同证明，本请求 409 且
            # 不落盘，resolved.json 永不与账本里的人工证明相左。
            if forecast_ledger.append_settlement_event(plan["event"]) is None:
                plan = _plan_scenario_attestation(target, outcome, known_at, evidence)
                if plan["status"] == "exists":
                    return _err("；".join(plan["errors"]) + _SUPERSEDES_HINT, 409)
                if plan["status"] != "noop":
                    return _err("结算账本未接受该事件（resolutions.jsonl 未写入），未写入判定", 500)
            else:
                settlement = {
                    "recorded": True, "event_key": plan["event"]["market_id"],
                    "reason": forecast_resolution.manual_not_bindable_reason(
                        target, forecast_resolution.SCENARIO_ITEM)}
        if plan is not None and plan["status"] == "noop":
            settlement = {"recorded": False, "event_key": plan["latest"].get("market_id"),
                          "reason": "already_recorded"}
        # 原子落盘（write_json_atomic：tmp + fsync + os.replace），避免轮询读取读到半截文件。
        write_json_atomic(_resolved_path(report_id), record)

        logger.info(
            f"[v1] 预测已判定: {report_id} outcome='{outcome}' "
            f"brier={scoring.get('brier')} matched={scoring.get('outcome_matched_a_scenario')} "
            f"settlement={settlement}"
        )
        return _ok({
            "report_id": report_id,
            "outcome": outcome,
            "scoring": scoring,
            "settlement": settlement,
        })
    except Exception as e:
        logger.error(f"[v1] 判定预测失败: {e}", exc_info=True)
        return _err(str(e), 500)
