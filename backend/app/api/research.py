"""统一研究→预测管线 API (Step 0)

一个 prompt 进：DeerFlow 深度研究 → MiroFish 知识图谱 → OASIS 模拟 → 预测报告。

路由（挂载于 /api/research）：
    POST   /run                      启动管线，立即返回 {pipeline_id, task_id}
    POST   /<pipeline_id>/cancel     取消在飞管线（杀研究子进程 / 停 OASIS 模拟）
    POST   /<pipeline_id>/resume     从失败/取消的管线继续（复用已完成产物）
    DELETE /<pipeline_id>            删除已结束的管线记录（含 handoff 产物）
    POST   /clean                    批量清理失败/已取消的管线记录
    GET    /status/<pipeline_id>     聚合的五阶段进度
    GET    /list                     最近管线列表
    GET    /<pipeline_id>/dossier    研究报告 markdown + actors/sources
    GET    /<pipeline_id>/progress   研究子进程进度日志（bounded tail / exact full snapshot）
"""

import os
import sqlite3
import traceback

from flask import jsonify, request

from . import research_bp
from ..config import Config
from ..services.pipeline_orchestrator import (
    PipelineManager,
    PipelineOrchestrator,
    PipelineState,
    preflight_pipeline,
    simulation_admission_error,
    simulation_readiness,
    refresh_research_artifact_manifest,
    research_dossier_is_sealed,
)
from ..services.world_simulation.admission import UNSET
from ..services.world_simulation.contracts import WorldError
from ..services.backtest_mode import BacktestRequestError
from ..services.research_progress import (
    ResearchProgressLimitError,
    merged_research_progress_full,
    merged_research_progress_tail,
)
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.research')

_VALID_DEPTH = {"quick", "standard", "deep"}
_VALID_MODE = {"full", "research_only"}
# T5.5: 每次运行可选的研究语言（与 DeerFlow --target-language 对齐；auto=交给模型自选）
_VALID_LANGUAGES = {"Chinese", "English", "auto"}
# B2: 人工编辑档案时报告的最小字符门。与编排器 research_report>=400 复用守卫语义一致：
# <400 字符（含 LLM 降级/错误短串）一律拒绝，避免空/垃圾报告悄悄退化下游本体/图谱/模拟。
MIN_DOSSIER_CHARS = 400


@research_bp.route('/run', methods=['POST'])
def run_pipeline():
    """启动统一管线。

    请求 (application/json):
        prompt: str            预测/研究问题（必填）
        mode: str              full | research_only（默认 full）
        project_name: str      可选
        depth: str             quick | standard | deep（默认 standard）
        max_rounds: int        OASIS 最大轮数（可选，截断模拟）
    """
    try:
        data = request.get_json(silent=True) or {}
        prompt = (data.get('prompt') or '').strip()
        if not prompt:
            return jsonify({"success": False, "error": "缺少 prompt"}), 400

        mode = (data.get('mode') or 'full').strip().lower()
        if mode not in _VALID_MODE:
            return jsonify({"success": False, "error": f"mode 必须是 {_VALID_MODE} 之一"}), 400

        depth = (data.get('depth') or Config.DEERFLOW_RESEARCH_DEPTH).strip().lower()
        if depth not in _VALID_DEPTH:
            return jsonify({"success": False, "error": f"depth 必须是 {_VALID_DEPTH} 之一"}), 400

        max_rounds = data.get('max_rounds')
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "max_rounds 必须是整数"}), 400

        # T5.5: 每次运行可覆盖研究语言/模型（缺省回退 Config）。在任何子进程启动前校验，杜绝
        # 一个拼错的模型名烧完研究额度后才暴露。
        # research_language 是内部字段名（PipelineState.options/scheduled_rerun.py 用它）；
        # 接口契约字段是 language——同时接受两者，避免调用方按内部命名类比误传后静默退回默认语言。
        language = (data.get('language') or data.get('research_language') or '').strip() or None
        if language is not None and language not in _VALID_LANGUAGES:
            return jsonify({"success": False, "error": f"language 必须是 {sorted(_VALID_LANGUAGES)} 之一"}), 400
        if language == 'auto':
            language = ''  # 空串 → 研究子进程不传 --target-language，交给模型自选
        model = (data.get('model') or '').strip() or None
        if model is not None and model.lower() not in Config.SUPPORTED_DEERFLOW_MODELS:
            return jsonify({
                "success": False,
                "error": f"model 必须是 {', '.join(Config.SUPPORTED_DEERFLOW_MODELS)} 之一",
            }), 400
        if model:
            model = model.lower()

        # Preserve omission versus explicit null. start() resolves and revalidates
        # against the current configuration before creating any pipeline state.
        run_options = {key: data[key] for key in
                       ('simulation_engine', 'world_spec', 'world_policy_spec', 'backtest') if key in data}

        # 起飞前体检：把"研究跑完 40 分钟后才发现 Zep Key 是占位符"这类失败提前到现在
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
            **run_options,
        )
        return jsonify({
            "success": True,
            "data": {
                "pipeline_id": state.pipeline_id,
                "task_id": state.task_id,
                "mode": state.mode,
                "status": state.status,
            },
        })
    except BacktestRequestError as error:
        return jsonify({"success": False, "error": f"Invalid backtest request: {error}"}), 400
    except WorldError as error:
        body, status = simulation_admission_error(error)
        return jsonify(body), status
    except Exception as e:
        logger.error(f"启动管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@research_bp.route('/<pipeline_id>/cancel', methods=['POST'])
def cancel_pipeline(pipeline_id: str):
    """取消在飞管线。研究阶段杀子进程组；模拟阶段停 OASIS；其余阶段在下个取消点退出。"""
    try:
        result = PipelineOrchestrator.cancel(pipeline_id)
        if result["status"] == "not_found":
            return jsonify({"success": False, "error": "管线不存在"}), 404
        if result["status"] == "not_running":
            return jsonify({"success": False, "error": "管线已结束，无法取消"}), 409
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"取消管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/<pipeline_id>/resume', methods=['POST'])
def resume_pipeline(pipeline_id: str):
    """恢复失败/取消的管线，尽量复用已有研究、图谱、模拟等阶段产物。"""
    try:
        existing = PipelineManager.load(pipeline_id)
        if existing is None:
            return jsonify({"success": False, "error": "管线不存在"}), 404
        preflight_errors = preflight_pipeline(mode=existing.get("mode") or "full")
        if preflight_errors:
            return jsonify({
                "success": False,
                "error": "恢复前检查未通过：\n" + "\n".join(f"• {e}" for e in preflight_errors),
                "preflight_errors": preflight_errors,
            }), 400
        # ORCH-3: force=true 允许恢复一条 completed 但 pipeline_health 降级/失败的管线
        # （仅重置 REPORT 阶段重生成报告）；默认请求形状不变。
        _force = bool((request.get_json(silent=True) or {}).get("force"))
        state = PipelineOrchestrator.resume(pipeline_id, force=_force)
        return jsonify({
            "success": True,
            "data": {
                "pipeline_id": state.pipeline_id,
                "task_id": state.task_id,
                "mode": state.mode,
                "status": state.status,
                "resumed": True,
            },
        })
    except FileNotFoundError:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        logger.error(f"恢复管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@research_bp.route('/<pipeline_id>/continue', methods=['POST'])
def continue_pipeline(pipeline_id: str):
    """T6.2: 把一条已完成的 research_only 管线继续跑成完整管线（复用研究产物，不重跑研究）。"""
    try:
        existing = PipelineManager.load(pipeline_id)
        if existing is None:
            return jsonify({"success": False, "error": "管线不存在"}), 404
        # 继续会跑完整管线（建图/模拟/报告），按 full 模式预检配置
        preflight_errors = preflight_pipeline(
            mode="full", model=(existing.get("options") or {}).get("research_model"))
        if preflight_errors:
            return jsonify({
                "success": False,
                "error": "继续前检查未通过：\n" + "\n".join(f"• {e}" for e in preflight_errors),
                "preflight_errors": preflight_errors,
            }), 400
        state = PipelineOrchestrator.continue_to_full(pipeline_id)
        return jsonify({
            "success": True,
            "data": {
                "pipeline_id": state.pipeline_id,
                "task_id": state.task_id,
                "mode": state.mode,
                "status": state.status,
                "continued": True,
            },
        })
    except FileNotFoundError:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    except WorldError as error:
        body, status = simulation_admission_error(error)
        return jsonify(body), status
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        logger.error(f"继续管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@research_bp.route('/<pipeline_id>/scenario', methods=['POST'])
def fork_scenario(pipeline_id: str):
    """T4.6: 在 PREPARE 处分叉一个 what-if 情景管线（复用 base 研究/本体/图谱，仅重跑 prepare/run/report）。

    body: {label, max_rounds?, influence_overrides{name:weight}, stance_overrides{name:stance},
           injected_events[{round,poster_name,content}], as_of_shift?}
    """
    try:
        existing = PipelineManager.load(pipeline_id)
        if existing is None:
            return jsonify({"success": False, "error": "基础管线不存在"}), 404
        overlay = request.get_json(silent=True) or {}
        if not (overlay.get("label") or "").strip():
            return jsonify({"success": False, "error": "缺少情景标签 label"}), 400
        preflight_errors = preflight_pipeline(mode="full")
        if preflight_errors:
            return jsonify({
                "success": False,
                "error": "情景分叉前检查未通过：\n" + "\n".join(f"• {e}" for e in preflight_errors),
                "preflight_errors": preflight_errors,
            }), 400
        state = PipelineOrchestrator.fork(pipeline_id, overlay)
        return jsonify({
            "success": True,
            "data": {
                "pipeline_id": state.pipeline_id,
                "base_pipeline_id": pipeline_id,
                "task_id": state.task_id,
                "label": overlay.get("label"),
                "status": state.status,
            },
        })
    except FileNotFoundError:
        return jsonify({"success": False, "error": "基础管线不存在"}), 404
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 409
    except Exception as e:
        logger.error(f"情景分叉失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e), "traceback": traceback.format_exc()}), 500


@research_bp.route('/<pipeline_id>', methods=['DELETE'])
def delete_pipeline(pipeline_id: str):
    """删除一条已结束的管线记录（含 handoff 产物）。在飞管线须先取消。

    若有 fork（what-if 情景）依赖其共享 handoff 目录，默认拒绝（409 has_dependents）；
    传 ?force=true 可强制删除（会同时破坏这些 fork 的恢复/产物复用）。
    """
    try:
        force = str(request.args.get('force', '')).strip().lower() in ('1', 'true', 'yes')
        result = PipelineOrchestrator.delete_pipeline(pipeline_id, force=force)
        if result["status"] == "not_found":
            return jsonify({"success": False, "error": "管线不存在"}), 404
        if result["status"] == "still_running":
            return jsonify({"success": False, "error": "管线正在运行，请先取消再删除"}), 409
        if result["status"] == "has_dependents":
            deps = result.get("dependents", [])
            return jsonify({
                "success": False,
                "error": f"仍有 {len(deps)} 个 fork 依赖其 handoff 目录，请先删除这些 fork 或加 ?force=true 强制删除",
                "data": result,
            }), 409
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"删除管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/clean', methods=['POST'])
def clean_pipelines():
    """批量清理失败/已取消的管线记录。请求体可选 {statuses: ["failed","cancelled"]}。"""
    try:
        data = request.get_json(silent=True) or {}
        statuses = data.get('statuses') or ["failed", "cancelled"]
        if not isinstance(statuses, list) or not statuses:
            return jsonify({"success": False, "error": "statuses 必须是非空列表"}), 400
        allowed = {"failed", "cancelled"}
        bad = [s for s in statuses if s not in allowed]
        if bad:
            return jsonify({"success": False, "error": f"只允许清理终态 {sorted(allowed)}，收到 {bad}"}), 400
        result = PipelineOrchestrator.clean_terminal(tuple(statuses))
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"清理管线失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/status/<pipeline_id>', methods=['GET'])
def pipeline_status(pipeline_id: str):
    """返回管线聚合进度（直接读 pipeline_state.json，可在后端重启后存活）。

    OBS-1/I-5-6 落地：状态响应额外拼一个计算出的 ``live`` 块（heartbeat 年龄、owner 存活、
    ETA/staleness、进程内累计花费、预算余量）。此前这些助手（heartbeat_status/estimate_eta/
    LLMMeter.status_snapshot）没有任何生产调用方，UI 无从显示「还活着吗/还要多久/烧了多少」。
    纯附加键，state 原文不动；任何助手失败只丢 ``live``，绝不拖垮状态端点。"""
    data = PipelineManager.load(pipeline_id)
    if data is None:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    try:
        live = PipelineOrchestrator().heartbeat_status(PipelineState.from_dict(data))
        budget_tokens = int(getattr(Config, "LLM_RUN_BUDGET_TOKENS", 0) or 0)
        if budget_tokens > 0:
            spent = int((live.get("spend_so_far") or {}).get("tokens") or 0)
            live["budget"] = {
                "limit_tokens": budget_tokens,
                "spent_tokens": spent,
                "remaining_tokens": max(0, budget_tokens - spent),
            }
        data = dict(data)
        data["live"] = live
    except Exception as _live_exc:  # noqa: BLE001 — best-effort 附加块
        logger.debug(f"status live 块计算失败（忽略）: {_live_exc}")
    response = jsonify({"success": True, "data": data})
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    return response


@research_bp.route('/list', methods=['GET'])
def list_pipelines():
    return jsonify({"success": True, "data": {"pipelines": PipelineManager.list_pipelines()}})


@research_bp.route('/resolution-monitor/run', methods=['POST'])
def run_resolution_monitor():
    """i8：手动触发一轮 MON-1 判定监测（后台子进程，`run --all-recent`）。

    脚本此前从未被任何调度方跑过（LOOP-017「resolution monitor never ran」）。202=已启动；
    409=上一轮仍在飞（在飞去重，绝不并发双跑）。周期自动跑由 RESOLUTION_MONITOR_AUTORUN_HOURS
    控制（默认关），本端点独立于该旋钮随时可用。"""
    from ..services import resolution_autorun
    if resolution_autorun.trigger_once():
        return jsonify({"success": True, "data": {"started": True}}), 202
    return jsonify({"success": False, "error": "上一轮判定监测仍在运行", "inflight": True}), 409


@research_bp.route('/preflight', methods=['GET'])
def preflight():
    """T5.6: 启动前就绪检查（不发起管线）。复用 POST /run 的同一套检查，避免漂移。

    EXECPLAN2 I-8-0: 默认行为不变（返回 {ready, errors, mode}）。可选 ?format=full
    走单一真源的 environment_report()（与 doctor.sh / preflight CLI 共用），返回带
    provider/deerflow_model/graph_backend + 结构化 checks[{id,severity,ok,message,fix}]
    的就绪文档，供前端设置页渲染实时就绪面板；?deep=true 追加 live 凭据/嵌入缓存/磁盘探针。
    """
    mode = request.args.get('mode', 'full')
    if mode not in ('full', 'research_only'):
        mode = 'full'
    model = (request.args.get('model') or '').strip() or None
    engine = request.args.get('simulation_engine', UNSET)

    if (request.args.get('format') or '').strip().lower() == 'full':
        # 复用 backend/scripts/preflight.py 的 environment_report()（同一引擎，零漂移）。
        # 容错降级：脚本不可导入时回退到旧版精简响应，绝不让设置页因此 500。
        try:
            import sys
            _scripts_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'scripts')
            _scripts_dir = os.path.abspath(_scripts_dir)
            if _scripts_dir not in sys.path:
                sys.path.insert(0, _scripts_dir)
            from preflight import environment_report  # type: ignore
            deep = (request.args.get('deep') or '').strip().lower() in ('1', 'true', 'yes')
            report = environment_report(mode=mode, model=model, deep=deep, simulation_engine=engine)
            return jsonify({"success": True, "data": report})
        except Exception:
            logger.warning("preflight format=full 降级到精简响应")

    simulation = simulation_readiness(mode=mode, simulation_engine=engine)
    errors = preflight_pipeline(mode=mode, model=model) + simulation["errors"]
    return jsonify({"success": True, "data": {
        **simulation, "ready": not errors, "errors": errors, "mode": mode,
    }})


@research_bp.route('/<pipeline_id>/dossier', methods=['GET'])
def get_dossier(pipeline_id: str):
    """返回深度研究产出的研究报告 + 结构化 actors/sources。"""
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    if not os.path.isdir(handoff):
        return jsonify({"success": False, "error": "管线不存在"}), 404

    def _read(name):
        p = os.path.join(handoff, name)
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8', newline='') as f:
                    return f.read()
            except Exception:
                return None
        return None

    import json as _json
    import hashlib
    report = _read('research_report.md')
    actors_raw = _read('actors.json')
    sources_raw = _read('sources.json')
    timeline_raw = _read('timeline.json')  # T5.2: 一等公民时间线
    quantitative_raw = _read('quantitative.json')
    contested_raw = _read('contested.json')
    markets_raw = _read('prediction_markets.json')
    charts_raw = _read('charts.json')

    def _decode(raw):
        try:
            return _json.loads(raw) if raw else None
        except (TypeError, ValueError):
            return None

    from ..services.news_market_context import load_context
    try:
        news_market_context = load_context(handoff) or None
    except ValueError:
        return jsonify({"success": False, "error": "Research news context is invalid"}), 409

    lang = (request.args.get("lang") or "").strip().lower()
    if lang and lang not in ("en", "zh"):
        return jsonify({"success": False, "error": "unsupported language"}), 400
    display = _research_display(handoff, pipeline_id, lang) if lang else {}
    return jsonify({
        "success": True,
        "data": {
            **display,
            "report": report,
            "source_sha256": hashlib.sha256(report.encode("utf-8")).hexdigest() if report is not None else None,
            "news_market_context": news_market_context,
            "actors": _decode(actors_raw),
            "sources": _decode(sources_raw),
            "timeline": _decode(timeline_raw),
            "quantitative": _decode(quantitative_raw),
            "contested": _decode(contested_raw),
            # Market signals are useful even when none are semantically exact
            # enough to become a model-vs-market forecast anchor.  Surface the
            # canonical status rather than hiding the entire lane behind the
            # final report's comparison matcher.
            "prediction_markets": _decode(markets_raw),
            "charts": _decode(charts_raw),
            "has_report": report is not None,
            # 封存的研究不可编辑（见 edit_dossier）；前端据此隐藏「编辑」入口。
            "sealed": research_dossier_is_sealed(handoff),
        },
    })


_RESEARCH_TRANSLATION_LANGS = ("en", "zh")
_RESEARCH_TRANSLATION_OPERATION = "research_dossier_translation"


def _research_report_paths(handoff: str, lang: str):
    """Return (source_md, variant_md, audit_json, status_json, pdf) paths for a lang."""
    return (
        os.path.join(handoff, "research_report.md"),
        os.path.join(handoff, f"research_report.{lang}.md"),
        os.path.join(handoff, f"research_report.final_audit.{lang}.json"),
        os.path.join(handoff, f"research_report.translation.{lang}.json"),
        os.path.join(handoff, f"research_report.{lang}.pdf"),
    )


def _research_source_sha(src_path: str):
    import hashlib
    try:
        with open(src_path, "rb") as handle:
            return hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        return None


def _read_research_status(status_path: str):
    import json as _json
    try:
        with open(status_path, encoding="utf-8") as handle:
            data = _json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _research_display_source(handoff):
    """Read display inputs without touching their canonical bytes or seal."""
    import json
    fields = {"actors": "actors.json", "sources": "sources.json", "timeline": "timeline.json",
              "quantitative": "quantitative.json", "contested": "contested.json",
              "prediction_markets": "prediction_markets.json", "charts": "charts.json",
              "datasets": "data/datasets.json"}
    document = {}
    for key, name in fields.items():
        try:
            with open(os.path.join(handoff, name), encoding="utf-8") as handle:
                document[key] = json.load(handle)
        except (OSError, ValueError):
            document[key] = None
    from ..services.news_market_context import load_context
    document["news_market_context"] = load_context(handoff) or None
    return document


def _research_display(handoff, pipeline_id, lang, *, generate=False, force=False):
    from ..services.artifact_translation import display_document
    document = _research_display_source(handoff)
    source_sha = _research_source_sha(_research_report_paths(handoff, lang)[0])
    checkpoint = _read_research_status(_research_proof_path(handoff, lang, source_sha, pipeline_id)) or {}
    ref_id = pipeline_id
    if checkpoint.get("display_source_sha256") == _research_digest(document):
        ref_id = checkpoint.get("display_ref_id") or pipeline_id
    result = display_document(handoff, "dossier", ref_id, lang,
        document, generate=generate, force=force)
    return {"dossier": result["display"], "structured_translation": {
        **result["structured_translation"], "complete": result["coverage"]["complete"],
        "coverage": result["coverage"]}}


def _research_digest(value):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _research_source(handoff):
    """Decode exactly the bytes whose digest travels with the operation."""
    import hashlib
    from ..services.translation.artifacts import ArtifactError
    path = _research_report_paths(handoff, "zh")[0]
    try:
        with open(path, "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        raise ArtifactError("research_missing", "研究报告不存在", status_code=404)
    try:
        markdown = raw.decode("utf-8")
    except UnicodeError:
        raise ArtifactError("research_invalid", "研究报告不是有效 UTF-8", status_code=400)
    if not markdown.strip():
        raise ArtifactError("research_missing", "研究报告为空", status_code=404)
    return path, markdown, hashlib.sha256(raw).hexdigest()


def _research_identity(handoff, pipeline_id, lang, source_sha):
    from ..services.translation.artifacts import figure_inventory
    source_path, markdown, _ = _research_source(handoff)
    return {"kind": "research", "ref_id": pipeline_id, "target_lang": lang,
            "source_sha256": source_sha, "scope": {"view": "dossier",
            "display_sha256": _research_digest(_research_display_source(handoff)),
            "figures": figure_inventory(markdown, source_path)}}


def _research_generation_root(handoff, pipeline_id):
    # Fork pipelines may share canonical handoff bytes. Their publication pointers
    # and resume proofs must still have separate resource ownership.
    PipelineManager._validate_id(pipeline_id)
    return os.path.join(handoff, ".research-translations", pipeline_id)


def _research_body_identity(pipeline_id, source_sha, figures):
    return {"kind": "research_body", "ref_id": pipeline_id, "scope": "dossier_body",
            "source_sha256": source_sha, "figures": figures}


def _research_proof_scope(proof, source, lang, identity):
    """Classify complete or incomplete proof without laundering a foreign receipt."""
    import hashlib
    from ..services.model_translation import ENGINE, _document_context, split_document
    from ..services.translation.contracts import scope_digest
    if (not isinstance(proof, dict) or proof.get("engine") != ENGINE
            or proof.get("source_sha256") != hashlib.sha256(source.encode("utf-8")).hexdigest()
            or proof.get("target_lang") != lang or proof.get("context") != _document_context(source)):
        return None
    rows, chunks = proof.get("sections"), split_document(source)
    if (not isinstance(rows, list) or len(rows) != len(chunks) or not rows
            or any(not isinstance(row, dict) or row.get("source") != chunk
                   or not isinstance(row.get("target"), str) for row, chunk in zip(rows, chunks))):
        return None
    target = "\n\n".join(row["target"] for row in rows).strip() + "\n"
    if proof.get("target_sha256") != hashlib.sha256(target.encode("utf-8")).hexdigest():
        return None
    expected = scope_digest(identity)
    scopes = [proof.get("resource_scope_sha256")]
    for row in rows:
        receipt = row.get("receipt")
        if receipt is not None:
            if not isinstance(receipt, dict):
                return None
            scopes.append(receipt.get("resource_scope_sha256"))
    if all(scope == expected for scope in scopes):
        return "bound"
    if all(scope is None for scope in scopes):
        return "legacy"
    return None


def _research_audit_binding(audit, source, lang, identity):
    from ..services.report_agent import ReportAgent
    return (isinstance(audit, dict)
            and audit.get("report_id") == "research::" + identity["ref_id"]
            and audit.get("source_markdown_sha256") == identity["source_sha256"]
            and audit.get("source_language") == ReportAgent._detect_translation_target(source)[0]
            and audit.get("language") == lang
            and isinstance(audit.get("model_translation"), dict)
            and audit.get("markdown_sha256") == audit["model_translation"].get("target_sha256"))


def _validate_research_generation(source, markdown, lang, audit, *, identity):
    from ..services.report_agent import ReportAgent
    from ..services.model_translation import valid_document_receipt
    from ..services.translation.artifacts import ArtifactError
    import hashlib
    if (not _research_audit_binding(audit, source, lang, identity)
            or _research_proof_scope(audit.get("model_translation"), source, lang, identity) is None
            or audit.get("hard_passed") is not True or audit.get("language") != lang
            or audit.get("source_language") != ReportAgent._detect_translation_target(source)[0]
            or audit.get("source_markdown_sha256") != hashlib.sha256(source.encode("utf-8")).hexdigest()
            or audit.get("markdown_sha256") != hashlib.sha256(markdown.encode("utf-8")).hexdigest()
            or not valid_document_receipt(source, markdown, lang, audit.get("model_translation"))):
        raise ArtifactError("invalid_artifact", "research translation review receipt or language is invalid")


def _research_sealed_display(snapshot, handoff):
    import json
    from ..services.translation.artifacts import ArtifactError
    if snapshot is None or "display.json" not in snapshot.assets:
        return None
    try:
        saved = json.loads(snapshot.assets["display.json"])
        display = saved["display"]
        if (not isinstance(display.get("dossier"), dict)
                or display["structured_translation"]["complete"] is not True):
            raise ValueError("invalid display coverage")
        if saved["source_sha256"] != _research_digest(_research_display_source(handoff)):
            return None
        return display
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise ArtifactError("invalid_artifact", "research display publication is invalid") from exc


def _research_artifact(handoff, lang, pipeline_id=None):
    """Resolve one generation; only an absent generation permits legacy fallback."""
    import hashlib
    import json
    from ..services.translation.artifacts import resolve_generation
    src, variant, audit_path, status_path, _ = _research_report_paths(handoff, lang)
    source_sha = _research_source_sha(src)
    if pipeline_id is not None and source_sha:
        snapshot = resolve_generation(_research_generation_root(handoff, pipeline_id), kind="research", ref_id=pipeline_id,
            lang=lang, source_sha256=source_sha, source_path=src)
        if snapshot is not None:
            audit = snapshot.audit
            _, source, _ = _research_source(handoff)
            body_identity = _research_body_identity(pipeline_id, source_sha,
                json.loads(snapshot.assets["figures.json"]))
            _validate_research_generation(source, snapshot.markdown, lang, audit, identity=body_identity)
            partial = audit.get("partial") if isinstance(audit.get("partial"), dict) else {}
            verbatim = list(partial.get("verbatim_regions") or [])
            return ({"status": "available", "available": True, "target_lang": lang,
                     "source_sha256": snapshot.source_sha256, "generation": snapshot.generation,
                     "source_lang": audit.get("source_language"), "partial": bool(verbatim),
                     "verbatim_chunks": verbatim, "issues": []},
                    snapshot.markdown, snapshot, audit)
    status = _read_research_status(status_path) or {"status": "unavailable"}
    # Historical workers cannot own a v2 operation after migration/restart.
    if status.get("status") == "generating":
        status = {**status, "status": "interrupted",
                  "issues": ["legacy translation stopped; resume with the durable scheduler"]}
    proof = status if status.get("status") == "available" else status.get("previous")
    if not isinstance(proof, dict):
        return status, None, None, {}
    if not source_sha or proof.get("source_sha256") != source_sha:
        return {**status, "status": "stale", "available": False,
                "issues": ["research source changed; retry current translation"]}, None, None, {}
    if proof.get("schema_version") != 2 or proof.get("target_lang") != lang:
        return {**status, "status": "outdated", "available": False}, None, None, {}
    try:
        # Hash the very bytes returned, never a preceding read of a mutable file.
        with open(variant, "rb") as handle:
            markdown_bytes = handle.read()
        with open(audit_path, "rb") as handle:
            audit_bytes = handle.read()
        if (proof.get("markdown_sha256") != hashlib.sha256(markdown_bytes).hexdigest()
                or proof.get("audit_sha256") != hashlib.sha256(audit_bytes).hexdigest()):
            return {**status, "status": "outdated", "available": False}, None, None, {}
        markdown, audit = markdown_bytes.decode("utf-8"), json.loads(audit_bytes)
        if not isinstance(audit, dict) or audit.get("hard_passed") is not True:
            return {**status, "status": "failed", "available": False}, None, None, {}
        from ..services.model_translation import ENGINE, valid_document_receipt
        if audit.get("translator_version") == ENGINE or "model_translation" in audit:
            with open(src, encoding="utf-8", newline="") as handle:
                current_source = handle.read()
            if not valid_document_receipt(current_source, markdown, lang, audit.get("model_translation")):
                return {**status, "status": "failed", "available": False,
                        "issues": ["research translation review receipt is invalid"]}, None, None, {}
        if _research_source_sha(src) != source_sha:
            return {**status, "status": "stale", "available": False}, None, None, {}
        return {**status, "source_sha256": source_sha, "target_lang": lang,
                "markdown_sha256": proof["markdown_sha256"], "audit_sha256": proof["audit_sha256"],
                "source_lang": proof.get("source_lang")}, markdown, None, audit
    except (OSError, ValueError, TypeError):
        return {**status, "status": "failed", "available": False}, None, None, {}


def _research_variant(handoff, lang, pipeline_id=None):
    status, markdown, _, _ = _research_artifact(handoff, lang, pipeline_id)
    return status, markdown


def _research_job_path(handoff, identity):
    # A job reference is routing metadata only. Execution state lives in SQLite.
    return os.path.join(handoff, "translations", "research-operation." +
                        _research_digest(identity) + ".json")


def _research_job(handoff, identity):
    from ..services.translation import scheduler
    reference = _read_research_status(_research_job_path(handoff, identity)) or {}
    if reference.get("identity") != identity or not isinstance(reference.get("job_id"), str):
        return None
    job = scheduler.status(reference["job_id"])
    if job is not None and (job.get("identity") != identity
                            or job.get("kind") != _RESEARCH_TRANSLATION_OPERATION
                            or job.get("job_id") != reference["job_id"]):
        return None
    return job


def _research_proof_path(handoff, lang, source_sha, pipeline_id):
    return os.path.join(_research_generation_root(handoff, pipeline_id),
                        f"research-proof.{lang}.{source_sha}.json")


def _research_previous_proof(handoff, lang, source_sha, pipeline_id, *, identity):
    """Only a resource-audited legacy proof receives an in-process import capability."""
    from ..services.model_translation import _document_context
    from ..services.translation.artifacts import figure_inventory
    from ..services.translation.contracts import trusted_import
    source_path, source, current_sha = _research_source(handoff)
    if (current_sha != source_sha or identity != _research_body_identity(
            pipeline_id, current_sha, figure_inventory(source, source_path))):
        return None
    checkpoint = _research_proof_path(handoff, lang, source_sha, pipeline_id)
    saved = _read_research_status(checkpoint) or {}
    audit = _read_research_status(_research_report_paths(handoff, lang)[2]) or {}
    candidates = []
    if (saved.get("source_sha256") == source_sha and saved.get("identity") == identity
            and saved.get("context") == _document_context(source)):
        candidates.append(saved)
    candidates.append(audit)
    for candidate in candidates:
        proof = candidate.get("model_translation")
        if not _research_audit_binding(candidate, source, lang, identity):
            continue
        scope = _research_proof_scope(proof, source, lang, identity)
        if scope == "bound":
            return proof
        if scope == "legacy":
            # Individual receipts are still validated by the shared executor.
            return trusted_import(proof, identity)
    return None


def _research_proof_record(audit, identity, operation_id):
    proof = audit.get("model_translation")
    return {"identity": identity, "operation_id": operation_id,
            "report_id": audit.get("report_id"), "language": audit.get("language"),
            "source_language": audit.get("source_language"),
            "source_sha256": identity["source_sha256"],
            "source_markdown_sha256": audit.get("source_markdown_sha256"),
            "markdown_sha256": audit.get("markdown_sha256"),
            "context": proof.get("context") if isinstance(proof, dict) else None,
            "model_translation": proof}


def _run_research_translation(payload: dict) -> dict:
    """Named scheduler handler; provider work is reachable only through submission."""
    from ..services.translation.artifacts import ArtifactError
    from ..services.translation.contracts import TranslationError
    try:
        return _translate_research_operation(payload)
    except ArtifactError as exc:
        code = "source_changed" if exc.code == "stale_artifact" else exc.code
        raise TranslationError(code, str(exc), retryable=False) from exc


def _translate_research_operation(payload: dict) -> dict:
    import json
    from ..services.report_agent import ReportAgent
    from ..services.translation.artifacts import ArtifactError, publish_generation
    from ..services.translation.scheduler import current_task_id
    from ..services.artifact_translation import _save_cache
    from ..utils.llm_client import LLMClient
    pipeline_id, lang = payload["pipeline_id"], payload["lang"]
    if lang not in _RESEARCH_TRANSLATION_LANGS:
        raise ArtifactError("unsupported_language", "unsupported language", status_code=400)
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    source_path, markdown, source_sha = _research_source(handoff)
    identity = _research_identity(handoff, pipeline_id, lang, source_sha)
    if identity != payload.get("identity"):
        raise ArtifactError("source_changed", "research source or display changed before translation")
    body_identity = _research_body_identity(pipeline_id, source_sha, identity["scope"]["figures"])
    force = payload.get("force") is True
    operation_id = current_task_id()
    checkpoint_path = _research_proof_path(handoff, lang, source_sha, pipeline_id)
    checkpoint = _read_research_status(checkpoint_path) or {}
    try:
        state, accepted, snapshot, audit = _research_artifact(handoff, lang, pipeline_id)
    except ArtifactError as exc:
        if exc.code != "stale_artifact":
            raise
        # A changed canonical source needs a new job, while the old generation
        # remains untouched until its replacement passes admission.
        state, accepted, snapshot, audit = {}, None, None, {}
    source_lang, target_lang, _ = ReportAgent._detect_translation_target(markdown)
    if lang == source_lang:
        accepted = markdown
    elif lang != target_lang:
        raise ArtifactError("unsupported_language", "requested language is not this report's translation target",
                            status_code=400)
    elif not accepted or (force and not (snapshot and operation_id
            and checkpoint.get("operation_id") == operation_id
            and (checkpoint.get("published_generation") == snapshot.generation
                 or checkpoint.get("published_body_digest") ==
                    _research_digest([snapshot.markdown, snapshot.audit])))):
        worker = ReportAgent.__new__(ReportAgent)
        worker.llm, worker.output_language, worker._forecast_spine = LLMClient(), "English", None
        previous_proof = _research_previous_proof(handoff, lang, source_sha, pipeline_id,
                                                identity=body_identity)
        if force and checkpoint.get("operation_id") != operation_id:
            previous_proof = None
        result = worker.translate_research_markdown(markdown, label=f"research::{pipeline_id}",
            identity=body_identity,
            previous_proof=previous_proof, force=force)
        audit = result.get("audit") or {}
        proof = audit.get("model_translation")
        if isinstance(proof, dict):
            _save_cache(checkpoint_path, _research_proof_record(audit, body_identity, operation_id))
        if result.get("tgt") != lang:
            raise ArtifactError("unsupported_language", "translation returned a different language", status_code=400)
        if not result.get("available") or audit.get("hard_passed") is not True:
            # The scheduler retains the safe failure; previously accepted files survive.
            from ..services.translation.contracts import TranslationError
            raise TranslationError("translation_rejected", "research translation did not pass publication audit",
                                   retryable=True)
        _validate_research_generation(markdown, result["translated_md"], lang, audit, identity=body_identity)
        # Bind pre-provider figures; activation must reject changed image bytes.
        assets = {"figures.json": json.dumps(identity["scope"]["figures"],
                                             sort_keys=True).encode("utf-8")}
        if snapshot is not None and _research_sealed_display(snapshot, handoff) is not None:
            # Content availability is separate from replacement execution. A failed
            # structured refresh must not hide the previous admitted display.
            assets["display.json"] = snapshot.assets["display.json"]
        if isinstance(result.get("citations"), dict):
            assets["citations.json"] = json.dumps(result["citations"], ensure_ascii=False).encode("utf-8")
        # publish_generation owns the source recheck and per-artifact publication lock.
        snapshot = publish_generation(_research_generation_root(handoff, pipeline_id), kind="research", ref_id=pipeline_id, lang=lang,
            source_sha256=source_sha, markdown=result["translated_md"], audit=audit,
            source_path=source_path, assets=assets)
        accepted = snapshot.markdown
        _save_cache(checkpoint_path, {**_research_proof_record(audit, body_identity, operation_id),
                    "published_generation": snapshot.generation,
                    "published_body_digest": _research_digest([snapshot.markdown, snapshot.audit])})
    # Body publication precedes display repair: failed display work cannot discard it.
    if force:
        checkpoint = _read_research_status(checkpoint_path) or {}
        # A new scope initializes a refresh once, even across crashes before/after
        # overlay publication. Ordinary replay never passes force to the overlay.
        _save_cache(checkpoint_path, {**checkpoint, **_research_proof_record(audit, body_identity, operation_id),
            "display_ref_id": f"{pipeline_id}:refresh:{operation_id}",
            "display_source_sha256": identity["scope"]["display_sha256"]})
    display = _research_display(handoff, pipeline_id, lang, generate=True, force=False)
    if _research_identity(handoff, pipeline_id, lang, _research_source_sha(source_path)) != identity:
        raise ArtifactError("source_changed", "research source or display changed during translation")
    if not display["structured_translation"]["complete"]:
        from ..services.translation.contracts import TranslationError
        raise TranslationError("structured_translation_incomplete",
                               "research display translation is incomplete; retry pending fields", retryable=True)
    if snapshot is not None:
        assets = {**snapshot.assets, "display.json": json.dumps({
            "source_sha256": identity["scope"]["display_sha256"], "display": display},
            ensure_ascii=False).encode("utf-8")}
        snapshot = publish_generation(_research_generation_root(handoff, pipeline_id),
            kind="research", ref_id=pipeline_id, lang=lang, source_sha256=source_sha,
            markdown=snapshot.markdown, audit=snapshot.audit, source_path=source_path, assets=assets)
        checkpoint = _read_research_status(checkpoint_path) or {}
        _save_cache(checkpoint_path, {**checkpoint, **_research_proof_record(snapshot.audit, body_identity, operation_id),
                    "published_generation": snapshot.generation})
    return {"status": "available", "available": bool(accepted), "source_sha256": source_sha,
            "target_lang": lang, "source_lang": source_lang,
            "generation": snapshot.generation if snapshot else None,
            "structured_translation": display["structured_translation"]}


def _authorize_research_translation(selection, action):
    """Apply the dossier route's resource admission to a minimal client selection.

    The application request gate supplies authentication for both route families;
    handoff resolution and current source reads supply resource authority here.
    No client hash, filesystem path, or asserted job identity is trusted.
    """
    from ..services.translation.artifacts import ArtifactError
    if (action not in {"retry", "cancel"} or not isinstance(selection, dict)
            or set(selection) - {"pipeline_id", "lang", "scope", "mode"}):
        return None
    pipeline_id, lang = selection.get("pipeline_id"), selection.get("lang")
    if (not isinstance(pipeline_id, str) or not isinstance(lang, str)
            or selection.get("scope", "dossier") != "dossier"
            or selection.get("mode", "dossier") != "dossier"):
        return None
    lang = lang.strip().lower()
    if lang not in _RESEARCH_TRANSLATION_LANGS:
        return None
    try:
        PipelineManager._validate_id(pipeline_id)
        handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
        source_path, _, source_sha = _research_source(handoff)
        identity = _research_identity(handoff, pipeline_id, lang, source_sha)
        if _research_source_sha(source_path) != source_sha:
            return None
        return identity
    except (ArtifactError, OSError, ValueError, TypeError):
        return None


def register_translation_handler():
    """Idempotent lifecycle registration; registration never starts a worker."""
    from .translations import register_resource_authorizer
    from ..services.translation.scheduler import register_handler
    register_handler(_RESEARCH_TRANSLATION_OPERATION, _run_research_translation)
    register_resource_authorizer(_RESEARCH_TRANSLATION_OPERATION, _authorize_research_translation)


def _research_translation_data(handoff, pipeline_id, lang, source_sha, *, job=None):
    from ..services.report_agent import ReportAgent
    from ..services.translation.artifacts import ArtifactError
    try:
        state, markdown, snapshot, _ = _research_artifact(handoff, lang, pipeline_id)
    except ArtifactError as exc:
        if exc.code not in {"stale_artifact", "invalid_artifact"}:
            raise
        state = {"status": "stale" if exc.code == "stale_artifact" else "failed", "issues": [str(exc)]}
        markdown, snapshot = None, None
    _, source, current_sha = _research_source(handoff)
    if current_sha != source_sha:
        raise ArtifactError("source_changed", "research source changed during read")
    source_lang = ReportAgent._detect_translation_target(source)[0]
    if lang == source_lang:
        markdown = source
        state = {"status": "available", "source_lang": source_lang}
    sealed_display = _research_sealed_display(snapshot, handoff)
    display = sealed_display or _research_display(handoff, pipeline_id, lang)
    structured = display["structured_translation"]
    display = {**display, "structured_translation": {**structured, "sealed": sealed_display is not None}}
    execution = (job or {}).get("job_state")
    status = state.get("status", "unavailable")
    if execution in {"queued", "running", "waiting_provider"}:
        status = "generating"
    elif execution in {"failed", "interrupted", "cancelled"}:
        status = execution
    elif markdown:
        status = "available"
    return {"status": status, "available": bool(markdown), "report": markdown,
            "source_lang": state.get("source_lang") or source_lang, "target_lang": lang,
            "source_sha256": source_sha, "generation": snapshot.generation if snapshot else None,
            "generation_id": snapshot.generation if snapshot else None,
            "partial": bool(state.get("partial")) or not structured["complete"]
                       or (snapshot is not None and sealed_display is None),
            "verbatim_chunks": state.get("verbatim_chunks") or [],
            "issues": list(state.get("issues") or []) + list((job or {}).get("issues") or [])
                      + list(structured.get("issues") or []),
            "translation_job": job, **display}


def _research_error(exc):
    return jsonify({"success": False, "code": exc.code, "error": str(exc)}), exc.status_code


@research_bp.route('/<pipeline_id>/dossier/translations/<lang>', methods=['POST'])
def start_research_translation(pipeline_id: str, lang: str):
    import fcntl
    from ..services.translation import scheduler
    from ..services.translation.artifacts import ArtifactError
    from ..services.artifact_translation import _save_cache
    lang = (lang or "").strip().lower()
    if lang not in _RESEARCH_TRANSLATION_LANGS:
        return jsonify({"success": False, "error": "unsupported language"}), 400
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    try:
        _, _, source_sha = _research_source(handoff)
        identity = _research_identity(handoff, pipeline_id, lang, source_sha)
        force = (request.args.get("force") or "").lower() in {"1", "true", "yes"}
        try:
            existing = _research_job(handoff, identity)
        except (OSError, RuntimeError, sqlite3.Error):
            existing = None
        data = _research_translation_data(handoff, pipeline_id, lang, source_sha, job=existing)
        retryable = existing and existing.get("job_state") in {"failed", "interrupted", "cancelled"}
        if data["available"] and not data["partial"] and not force and not retryable:
            return jsonify({"success": True, "data": data}), 200
        path = _research_job_path(handoff, identity)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        register_translation_handler()
        # Serialize reference replacement across Flask processes, never provider work.
        with open(path + ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            existing = _research_job(handoff, identity)
            if existing and existing.get("job_state") in {"queued", "running", "waiting_provider"}:
                job = existing
            elif existing and not force and existing.get("job_state") in {"failed", "interrupted", "cancelled"}:
                job = scheduler.retry(existing["job_id"])
            else:
                job = scheduler.submit(_RESEARCH_TRANSLATION_OPERATION, identity,
                    {"pipeline_id": pipeline_id, "lang": lang, "identity": identity, "force": force},
                    force=force or bool(existing and existing.get("job_state") == "completed"))
                if not force and job.get("job_state") in {"failed", "interrupted", "cancelled"}:
                    job = scheduler.retry(job["job_id"])
            _save_cache(path, {"identity": identity, "job_id": job["job_id"]})
        data = _research_translation_data(handoff, pipeline_id, lang, source_sha, job=job)
        return jsonify({"success": True, "data": data}), 202
    except ArtifactError as exc:
        return _research_error(exc)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        logger.error("研究翻译调度不可用: %s", type(exc).__name__)
        return jsonify({"success": False, "code": "translation_scheduler_unavailable",
                        "error": "translation scheduler unavailable"}), 503


@research_bp.route('/<pipeline_id>/dossier/translations/<lang>', methods=['GET'])
def get_research_translation(pipeline_id: str, lang: str):
    from ..services.translation.artifacts import ArtifactError
    lang = (lang or "").strip().lower()
    if lang not in _RESEARCH_TRANSLATION_LANGS:
        return jsonify({"success": False, "error": "unsupported language"}), 400
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    try:
        _, _, source_sha = _research_source(handoff)
        identity = _research_identity(handoff, pipeline_id, lang, source_sha)
        try:
            job = _research_job(handoff, identity)
        except (OSError, RuntimeError, sqlite3.Error):
            job = None  # Accepted publications remain readable during a store outage.
        data = _research_translation_data(handoff, pipeline_id, lang, source_sha, job=job)
        return jsonify({"success": True, "data": data})
    except ArtifactError as exc:
        return _research_error(exc)


@research_bp.route('/<pipeline_id>/dossier/pdf', methods=['GET'])
def get_research_pdf(pipeline_id: str):
    """Export exactly the admitted displayed bytes, without starting translation."""
    from io import BytesIO
    from flask import send_file
    from ..services.report_agent import ReportAgent, ReportManager
    from ..services.translation.artifacts import ArtifactError, assert_current
    if not getattr(Config, "REPORT_PDF_EXPORT", True):
        return jsonify({"success": False, "code": "pdf_export_disabled"}), 503
    lang = (request.args.get("lang") or "").strip().lower() or None
    if "lang" in request.args and (lang not in _RESEARCH_TRANSLATION_LANGS or len(request.args.getlist("lang")) != 1):
        return jsonify({"success": False, "error": "unsupported language"}), 400
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    try:
        source_path, source, source_sha = _research_source(handoff)
        primary_lang = ReportAgent._detect_translation_target(source)[0]
        snapshot, state, markdown, audit = None, {}, source, {}
        if lang and lang != primary_lang:
            state, markdown, snapshot, audit = _research_artifact(handoff, lang, pipeline_id)
            if markdown is None:
                stale = state.get("status") in {"stale", "outdated", "failed"}
                raise ArtifactError("translation_stale" if stale else "translation_missing",
                    "该语种译文尚未通过发布审计", status_code=409 if stale else 404)
        if request.args.get("source_sha256") not in (None, source_sha):
            raise ArtifactError("source_changed", "displayed research source changed")
        generation = snapshot.generation if snapshot else None
        if request.args.get("generation") not in (None, generation):
            raise ArtifactError("generation_changed", "displayed research generation changed")

        def check_current():
            if _research_source_sha(source_path) != source_sha:
                raise ArtifactError("source_changed", "research source changed during export")
            if snapshot is not None:
                assert_current(snapshot, source_path)
            elif lang and lang != primary_lang:
                current, current_md, current_snapshot, current_audit = _research_artifact(handoff, lang, pipeline_id)
                if (current_snapshot is not None or current_md != markdown or current_audit != audit
                        or current.get("markdown_sha256") != state.get("markdown_sha256")
                        or current.get("audit_sha256") != state.get("audit_sha256")
                        or current.get("source_sha256") != source_sha):
                    raise ArtifactError("generation_changed", "research translation changed during export")

        suffix = f".{lang}" if lang else ""
        out_pdf = os.path.join(handoff, f"research_report{suffix}.pdf")
        check_current()
        result = ReportManager.export_document_pdf(markdown, handoff, out_pdf,
            label=f"research::{pipeline_id}{'::' + lang if lang else ''}",
            source_path=source_path, snapshot=snapshot, check_current=check_current)
        if not result:
            return jsonify({"success": False, "code": "pdf_render_failed", "error": "PDF 生成失败"}), 500
        # The exporter returns an immutable cache path, which may differ from out_pdf.
        with open(result, "rb") as handle:
            pdf = handle.read()
        if not pdf.startswith(b"%PDF-"):
            return jsonify({"success": False, "code": "pdf_invalid"}), 500
        check_current()
        return send_file(BytesIO(pdf), mimetype="application/pdf", as_attachment=True,
                         download_name=f"research_report{suffix}.pdf")
    except ArtifactError as exc:
        return _research_error(exc)
    except (OSError, ValueError) as exc:
        logger.error("研究报告 PDF 导出异常: %s", type(exc).__name__)
        return jsonify({"success": False, "code": "pdf_internal_error"}), 500


@research_bp.route('/<pipeline_id>/dossier', methods=['PUT'])
def edit_dossier(pipeline_id: str):
    """T5.4: 编辑研究档案（research_report.md / actors.json），人类介入后再继续。

    仅当 status==completed && mode==research_only（或失败于建图之前）时允许，避免改动已下游消费的档案。
    原子写（tmp + os.replace）。body: {report?: str, actors?: object}。

    已封存的研究一律拒绝（409, sealed=true，判定见 research_dossier_is_sealed）：
    报告/actors 字节被研究 contract 清单、judge 文本绑定或 actor-intelligence 契约/血缘封存，
    直接改写会让下一次「继续/恢复」重跑综合覆盖编辑，或在 actor 接收校验处失败。
    未封存（旧版）研究的编辑会同步刷新 handoff/manifest.json 中对应条目，使复用校验接受编辑。
    """
    import json as _json
    data = PipelineManager.load(pipeline_id)
    if data is None:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    status = data.get("status")
    mode = data.get("mode")
    graph_done = bool((data.get("stages") or {}).get("graph", {}).get("status") == "completed")
    # 允许：已完成的 research_only；或失败/取消且尚未建图（编辑后可继续）
    allowed = (status == "completed" and mode == "research_only") or (
        status in ("failed", "cancelled") and not graph_done
    )
    if not allowed:
        return jsonify({"success": False, "error": "当前状态不允许编辑档案（仅完成的 research_only 或建图前的失败管线可编辑）"}), 409

    body = request.get_json(silent=True) or {}
    handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    if not os.path.isdir(handoff):
        return jsonify({"success": False, "error": "管线产物目录不存在"}), 404
    if research_dossier_is_sealed(handoff):
        return jsonify({
            "success": False,
            "sealed": True,
            "error": (
                "该研究已封存（研究 contract 清单 / judge 绑定 / actor-intelligence 血缘），不能直接编辑："
                "改动会让「继续」重跑综合覆盖编辑，或在 actor 接收校验处失败。请用修订后的问题重新发起研究。"
                " This research is sealed (research contract, judge binding or actor-intelligence"
                " lineage), so it cannot be edited in place: Continue would re-run synthesis over"
                " the edit or fail the actor-lineage check. Start a new research run with a"
                " refined question instead."
            ),
        }), 409

    # B2: 写入前质量门。若提交了 report，去空白后须 >= MIN_DOSSIER_CHARS，否则硬拒绝（400），
    # 杜绝空/过短报告被原子写入后悄悄退化下游本体/图谱/模拟。actors/sources 为可选，缺失不拦。
    if isinstance(body.get("report"), str):
        if len(body["report"].strip()) < MIN_DOSSIER_CHARS:
            return jsonify({
                "success": False,
                "error": (
                    f"研究报告过短（去空白后须 >= {MIN_DOSSIER_CHARS} 字符），拒绝写入以免退化下游。"
                    f" Research report too short (must be >= {MIN_DOSSIER_CHARS} chars after trimming)."
                ),
            }), 400

    def _atomic_write(name, text):
        path = os.path.join(handoff, name)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

    wrote = []
    try:
        if isinstance(body.get("report"), str):
            _atomic_write("research_report.md", body["report"])
            wrote.append("research_report.md")
        if body.get("actors") is not None:
            _atomic_write("actors.json", _json.dumps(body["actors"], ensure_ascii=False, indent=2))
            wrote.append("actors.json")
    except Exception as e:
        logger.error(f"编辑档案写入失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500
    if not wrote:
        return jsonify({"success": False, "error": "未提供 report 或 actors"}), 400
    try:
        refresh_research_artifact_manifest(pipeline_id, handoff, wrote)
    except Exception as e:  # noqa: BLE001 — 清单刷新失败会让「继续」重跑研究，必须显式报错
        logger.error(f"编辑档案后刷新产物清单失败: {e}", exc_info=True)
        return jsonify({
            "success": False,
            "error": f"档案已写入，但产物清单刷新失败，继续时编辑可能被重跑覆盖: {e}",
        }), 500
    return jsonify({"success": True, "data": {"updated": wrote}})


# T6.3: 各阶段产物深链。artifacts 映射在 pipeline_state.json 里维护（_record_stage_artifacts）：
# dossier/timeline/sources/ontology/communities/initial_posts/personas/run_summary/simulation_record
# （ADR 0003：模拟事后记录 simulation_record.json，与 run_summary 同在 RUN 阶段登记）。
@research_bp.route('/<pipeline_id>/artifact/<name>', methods=['GET'])
def get_artifact(pipeline_id: str, name: str):
    """T6.3: 返回某阶段产物（JSON 解析后内容；csv/未知按纯文本）。"""
    data = PipelineManager.load(pipeline_id)
    if data is None:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    if name in {"simulation_record", "simulation_record_partial"}:
        # This derivative has a publication gate, unlike ordinary research JSON.
        # Resolve it by the pipeline's simulation identity, never by a stored path.
        from .simulation import _contained_sim_dir
        from ..services import simulation_record_contract as record_contract
        sim_dir = _contained_sim_dir(data.get("simulation_id") or "")
        if sim_dir is None:
            return jsonify({"success": False, "error": "模拟事后记录尚未生成"}), 404
        record, status = record_contract.load_published_record(sim_dir)
        if record is None:
            missing = not os.path.isfile(record_contract.record_paths(sim_dir)["json"])
            return jsonify({"success": False, "error": "模拟事后记录尚未通过发布审计",
                            "publication_status": status}), 404 if missing else 409
        return jsonify({"success": True, "data": {"name": name, "content": record}})
    artifacts = (data.get("artifacts") or {})
    path = artifacts.get(name)
    # Live scans store provisional assets as <name>_partial; chart URLs stay
    # stable before and after stage completion by accepting that pointer until
    # the completion boundary registers the formal key.
    if not path and name.startswith("chart_"):
        path = artifacts.get(f"{name}_partial")
    if not path and name.startswith("chart_"):
        # fork 情景的 artifacts 注册表生而为空（fork() 不复制 base 的指针）；研究阶段
        # 图表实际躺在共享 handoff/charts 下。按解析后的目录直推候选路径，交给下方与
        # 注册表指针完全相同的 basename/symlink/收容复验（此回退只在指针缺失时触发，
        # 非 fork 管线的既有注册表行为不变）。
        _cand = os.path.join(PipelineManager.resolve_handoff_dir(pipeline_id),
                             "charts", name[len("chart_"):])
        if os.path.exists(_cand):
            path = _cand
    if not path or not os.path.exists(path):
        return jsonify({"success": False, "error": f"产物 '{name}' 不存在"}), 404
    try:
        # GATE-W9：二进制图表产物（VIZ-2 登记的 chart_*.png / *.svg）按原始字节 + 正确
        # mimetype 直出——此前统一按 utf-8 文本读取，PNG 解码即抛 500，注册了也取不到。
        _ext = os.path.splitext(path)[1].lower()
        _asset_mime = {
            '.png': 'image/png',
            '.svg': 'image/svg+xml',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.webp': 'image/webp',
            '.html': 'text/html; charset=utf-8',
        }.get(_ext)
        if _asset_mime:
            if name.startswith("chart_"):
                # Revalidate the persisted pointer at serve time. A renderer can
                # replace a once-regular chart with a symlink after a live scan;
                # formal/partial registration is therefore not a trust boundary.
                handoff = os.path.realpath(PipelineManager.resolve_handoff_dir(pipeline_id))
                charts_root = os.path.realpath(os.path.join(handoff, "charts"))
                resolved = os.path.realpath(path)
                expected_file = name[len("chart_"):]
                if (os.path.basename(path) != expected_file
                        or os.path.basename(resolved) != expected_file
                        or os.path.islink(path)
                        or not os.path.isfile(resolved)
                        or os.path.commonpath([resolved, charts_root]) != charts_root):
                    return jsonify({
                        "success": False,
                        "error": f"产物 '{name}' 不存在",
                    }), 404
                path = resolved
            from flask import send_file, Response as _FlaskResponse
            from ..utils.chart_html import inline_plotly_bundle
            if _ext == '.html':
                # 沙箱 CSP（见下）拦截外部脚本；directory 模式图表在服务时把同目录
                # plotly.min.js 内联进 HTML，而不是放宽沙箱（utils/chart_html）。
                _inlined = inline_plotly_bundle(path)
                response = (_FlaskResponse(_inlined, mimetype=_asset_mime)
                            if _inlined is not None
                            else send_file(path, mimetype=_asset_mime))
            else:
                response = send_file(path, mimetype=_asset_mime)
            if _ext == '.html':
                response.headers["Content-Security-Policy"] = (
                    "sandbox allow-scripts; default-src 'none'; "
                    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                    "img-src data: blob:; font-src data:; connect-src 'none'"
                )
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
            elif _ext == '.svg':
                response.headers["Content-Security-Policy"] = (
                    "sandbox; default-src 'none'; script-src 'none'; "
                    "style-src 'unsafe-inline'; img-src data:; font-src data:"
                )
                response.headers["X-Content-Type-Options"] = "nosniff"
                response.headers["Referrer-Policy"] = "no-referrer"
            return response
        with open(path, 'r', encoding='utf-8') as f:
            raw = f.read()
        import json as _json
        if path.endswith('.json'):
            return jsonify({"success": True, "data": {"name": name, "content": _json.loads(raw)}})
        return jsonify({"success": True, "data": {"name": name, "content": raw}})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@research_bp.route('/<pipeline_id>/progress', methods=['GET'])
def get_progress_log(pipeline_id: str):
    """返回研究子进程日志的有界尾部或全部已记录事件快照。

    并行研究时 producer 写在 ``handoff/track_N/research_progress.log``；根目录日志直到
    单轨/收尾路径才可能存在。默认 ``scope=tail`` 每个文件只读有界尾部，因此周期轮询
    不会随数小时运行产生的多 MB 日志线性变慢。``scope=full`` 是一次性 hydration / 审计
    契约：读取并合并全部可信的已记录进度事件，保留重复行和完整持久化行；事件本身是适合
    人类阅读的工具载荷摘要，并非原始模型 transcript。超过安全上限则明确 413，绝不把截断
    结果冒充完整记录。
    """
    if PipelineManager.load(pipeline_id) is None:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    try:
        handoff = PipelineManager.resolve_handoff_dir(pipeline_id)
    except ValueError:
        return jsonify({"success": False, "error": "管线不存在"}), 404
    scope = str(request.args.get('scope', 'tail') or 'tail').strip().lower()
    if scope not in {'tail', 'full'}:
        return jsonify({"success": False, "error": "scope 必须是 tail 或 full"}), 400
    try:
        limit = int(request.args.get('lines', '200'))
    except ValueError:
        limit = 200
    try:
        snapshot = (
            merged_research_progress_full(handoff)
            if scope == 'full'
            else merged_research_progress_tail(handoff, limit)
        )
        total_exact = scope == 'full'
        response = jsonify({"success": True, "data": {
            "scope": scope,
            "lines": snapshot.lines,
            "returned": len(snapshot.lines),
            # Exact historical line counts require an O(file) scan and are
            # deliberately unavailable on the recurring bounded endpoint.
            "total": len(snapshot.lines) if total_exact else None,
            "total_exact": total_exact,
            "snapshot_exact": total_exact,
            "event_fidelity": "summarized_progress_events",
            "source_count": snapshot.source_count,
            "truncated": snapshot.truncated,
        }})
        response.headers["Cache-Control"] = "no-store, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
    except ResearchProgressLimitError as e:
        return jsonify({"success": False, "error": str(e)}), 413
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500
