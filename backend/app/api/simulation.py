"""
模拟相关API路由
Step2: Zep实体读取与过滤、OASIS模拟准备与运行（全程自动化）
"""

import os
import re
import traceback
from flask import request, jsonify, send_file, Response

from . import simulation_bp
from ..config import Config
from ..services.zep_entity_reader import ZepEntityReader
from ..services.oasis_profile_generator import OasisProfileGenerator
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.simulation_runner import SimulationRunner, RunnerStatus
from ..utils.logger import get_logger
from ..models.project import ProjectManager

logger = get_logger('mirofish.api.simulation')


# Interview prompt 优化前缀
# 添加此前缀可以避免Agent调用工具，直接用文本回复
INTERVIEW_PROMPT_PREFIX = "结合你的人设、所有的过往记忆与行动，不调用任何工具直接用文本回复我："


def optimize_interview_prompt(prompt: str) -> str:
    """
    优化Interview提问，添加前缀避免Agent调用工具
    
    Args:
        prompt: 原始提问
        
    Returns:
        优化后的提问
    """
    if not prompt:
        return prompt
    # 避免重复添加前缀
    if prompt.startswith(INTERVIEW_PROMPT_PREFIX):
        return prompt
    return f"{INTERVIEW_PROMPT_PREFIX}{prompt}"


# ============== 实体读取接口 ==============

@simulation_bp.route('/entities/<graph_id>', methods=['GET'])
def get_graph_entities(graph_id: str):
    """
    获取图谱中的所有实体（已过滤）
    
    只返回符合预定义实体类型的节点（Labels不只是Entity的节点）
    
    Query参数：
        entity_types: 逗号分隔的实体类型列表（可选，用于进一步过滤）
        enrich: 是否获取相关边信息（默认true）
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY未配置"
            }), 500
        
        entity_types_str = request.args.get('entity_types', '')
        entity_types = [t.strip() for t in entity_types_str.split(',') if t.strip()] if entity_types_str else None
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        logger.info(f"获取图谱实体: graph_id={graph_id}, entity_types={entity_types}, enrich={enrich}")
        
        reader = ZepEntityReader()
        result = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": result.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取图谱实体失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/<entity_uuid>', methods=['GET'])
def get_entity_detail(graph_id: str, entity_uuid: str):
    """获取单个实体的详细信息"""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY未配置"
            }), 500
        
        reader = ZepEntityReader()
        entity = reader.get_entity_with_context(graph_id, entity_uuid)
        
        if not entity:
            return jsonify({
                "success": False,
                "error": f"实体不存在: {entity_uuid}"
            }), 404
        
        return jsonify({
            "success": True,
            "data": entity.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取实体详情失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/entities/<graph_id>/by-type/<entity_type>', methods=['GET'])
def get_entities_by_type(graph_id: str, entity_type: str):
    """获取指定类型的所有实体"""
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY未配置"
            }), 500
        
        enrich = request.args.get('enrich', 'true').lower() == 'true'
        
        reader = ZepEntityReader()
        entities = reader.get_entities_by_type(
            graph_id=graph_id,
            entity_type=entity_type,
            enrich_with_edges=enrich
        )
        
        return jsonify({
            "success": True,
            "data": {
                "entity_type": entity_type,
                "count": len(entities),
                "entities": [e.to_dict() for e in entities]
            }
        })
        
    except Exception as e:
        logger.error(f"获取实体失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 模拟管理接口 ==============

@simulation_bp.route('/create', methods=['POST'])
def create_simulation():
    """
    创建新的模拟
    
    注意：max_rounds等参数由LLM智能生成，无需手动设置
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",      // 必填
            "graph_id": "mirofish_xxxx",    // 可选，如不提供则从project获取
            "enable_twitter": true,          // 可选，默认true
            "enable_reddit": true            // 可选，默认true
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "project_id": "proj_xxxx",
                "graph_id": "mirofish_xxxx",
                "status": "created",
                "enable_twitter": true,
                "enable_reddit": true,
                "created_at": "2025-12-01T10:00:00"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        project_id = data.get('project_id')
        if not project_id:
            return jsonify({
                "success": False,
                "error": "请提供 project_id"
            }), 400
        
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {project_id}"
            }), 404
        
        graph_id = data.get('graph_id') or project.graph_id
        if not graph_id:
            return jsonify({
                "success": False,
                "error": "项目尚未构建图谱，请先调用 /api/graph/build"
            }), 400
        
        manager = SimulationManager()
        state = manager.create_simulation(
            project_id=project_id,
            graph_id=graph_id,
            enable_twitter=data.get('enable_twitter', True),
            enable_reddit=data.get('enable_reddit', True),
            simulation_engine=data.get('simulation_engine', 'oasis-legacy'),
        )
        # 项目归属于已完成研究的管线时，把手动模拟绑定到该管线的研究代际，
        # 使世界简报、手动报告与对话获得同一份研究档案与官方数据（失败仅记日志）。
        from ..services.official_data import bind_project_simulation
        binding = bind_project_simulation(state.simulation_id, project_id)
        logger.info(f"手动模拟 {state.simulation_id} 研究绑定: {binding}")
        
        return jsonify({
            "success": True,
            "data": state.to_dict()
        })
        
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    except Exception as e:
        logger.error(f"创建模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _check_simulation_prepared(simulation_id: str) -> tuple:
    """
    检查模拟是否已经准备完成
    
    检查条件：
    1. state.json 存在且 status 为 "ready"
    2. 必要文件存在：reddit_profiles.json, twitter_profiles.csv, simulation_config.json
    
    注意：运行脚本(run_*.py)保留在 backend/scripts/ 目录，不再复制到模拟目录
    
    Args:
        simulation_id: 模拟ID
        
    Returns:
        (is_prepared: bool, info: dict)
    """
    import os
    from ..config import Config
    
    manager = SimulationManager()
    state = manager.get_simulation(simulation_id)
    if state is not None and state.simulation_engine == 'world-v1':
        manager.validate_prepared_simulation_config(simulation_id)
        return True, {"simulation_engine": "world-v1", "world_generation_id": state.world_generation_id}

    simulation_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
    
    # 检查目录是否存在
    if not os.path.exists(simulation_dir):
        return False, {"reason": "模拟目录不存在"}
    
    # 必要文件列表（不包括脚本，脚本位于 backend/scripts/）
    required_files = [
        "state.json",
        "simulation_config.json",
        "reddit_profiles.json",
        "twitter_profiles.csv"
    ]
    
    # 检查文件是否存在
    existing_files = []
    missing_files = []
    for f in required_files:
        file_path = os.path.join(simulation_dir, f)
        if os.path.exists(file_path):
            existing_files.append(f)
        else:
            missing_files.append(f)
    
    if missing_files:
        return False, {
            "reason": "缺少必要文件",
            "missing_files": missing_files,
            "existing_files": existing_files
        }
    
    # 检查state.json中的状态
    state_file = os.path.join(simulation_dir, "state.json")
    try:
        import json
        with open(state_file, 'r', encoding='utf-8') as f:
            state_data = json.load(f)
        
        status = state_data.get("status", "")
        config_generated = state_data.get("config_generated", False)

        role_count = int(state_data.get("actor_role_count", 0) or 0)
        if role_count:
            cast_path = os.path.join(simulation_dir, "actor_cast_manifest.json")
            try:
                import hashlib
                with open(cast_path, "rb") as cast_handle:
                    cast_sha = hashlib.sha256(cast_handle.read()).hexdigest()
                if cast_sha != state_data.get("actor_cast_manifest_sha256"):
                    raise ValueError("actor cast manifest fingerprint mismatch")
                role_manifest_shas = state_data.get("actor_role_manifest_sha256")
                if not isinstance(role_manifest_shas, dict):
                    raise ValueError("prepared role manifest fingerprints are missing")
                for profile_name in ("reddit_profiles.json", "twitter_profiles.csv"):
                    profile_path = os.path.join(simulation_dir, profile_name)
                    platform_name = "twitter" if profile_name.endswith(".csv") else "reddit"
                    role_manifest_path = OasisProfileGenerator._role_manifest_path(
                        profile_path
                    )
                    with open(role_manifest_path, "rb") as role_manifest_handle:
                        role_manifest_sha = hashlib.sha256(
                            role_manifest_handle.read()
                        ).hexdigest()
                    if role_manifest_shas.get(platform_name) != role_manifest_sha:
                        raise ValueError(
                            f"{platform_name} role manifest fingerprint mismatch"
                        )
                    OasisProfileGenerator.validate_role_prompt_manifest(
                        profile_path,
                        expected_role_count=role_count,
                        expected_cast_manifest_sha256=cast_sha,
                    )
            except (OSError, ValueError, TypeError) as exc:
                return False, {
                    "reason": "角色提示词完整性校验失败",
                    "error": str(exc),
                }
        
        # 详细日志
        logger.debug(f"检测模拟准备状态: {simulation_id}, status={status}, config_generated={config_generated}")
        
        # 如果 config_generated=True 且文件存在，认为准备完成
        # 以下状态都说明准备工作已完成：
        # - ready: 准备完成，可以运行
        # - preparing: 如果 config_generated=True 说明已完成
        # - running: 正在运行，说明准备早就完成了
        # - completed: 运行完成，说明准备早就完成了
        # - stopped: 已停止，说明准备早就完成了
        # - failed: 运行失败（但准备是完成的）
        prepared_statuses = ["ready", "preparing", "running", "completed", "stopped", "failed"]
        if status in prepared_statuses and config_generated:
            # 获取文件统计信息
            profiles_file = os.path.join(simulation_dir, "reddit_profiles.json")
            config_file = os.path.join(simulation_dir, "simulation_config.json")
            
            profiles_count = 0
            if os.path.exists(profiles_file):
                with open(profiles_file, 'r', encoding='utf-8') as f:
                    profiles_data = json.load(f)
                    profiles_count = len(profiles_data) if isinstance(profiles_data, list) else 0
            
            # 如果状态是preparing但文件已完成，自动更新状态为ready
            if status == "preparing":
                try:
                    state_data["status"] = "ready"
                    from datetime import datetime
                    state_data["updated_at"] = datetime.now().isoformat()
                    # 原子写入（tmp + os.replace），避免并发实时端点读到半截 JSON，
                    # 与 SimulationManager / SimulationRunner 的写入保持一致（EXECPLAN2 F-6-13）。
                    from ..utils.atomic import write_json_atomic
                    from ..services.simulation_runner import SimulationRunner
                    with SimulationRunner._run_state_lock:
                        write_json_atomic(state_file, state_data)
                    logger.info(f"自动更新模拟状态: {simulation_id} preparing -> ready")
                    status = "ready"
                except Exception as e:
                    logger.warning(f"自动更新状态失败: {e}")
            
            logger.info(f"模拟 {simulation_id} 检测结果: 已准备完成 (status={status}, config_generated={config_generated})")
            return True, {
                "status": status,
                "entities_count": state_data.get("entities_count", 0),
                "profiles_count": profiles_count,
                "entity_types": state_data.get("entity_types", []),
                "config_generated": config_generated,
                "created_at": state_data.get("created_at"),
                "updated_at": state_data.get("updated_at"),
                "existing_files": existing_files
            }
        else:
            logger.warning(f"模拟 {simulation_id} 检测结果: 未准备完成 (status={status}, config_generated={config_generated})")
            return False, {
                "reason": f"状态不在已准备列表中或config_generated为false: status={status}, config_generated={config_generated}",
                "status": status,
                "config_generated": config_generated
            }
            
    except Exception as e:
        return False, {"reason": f"读取状态文件失败: {str(e)}"}


@simulation_bp.route('/prepare', methods=['POST'])
def prepare_simulation():
    """
    准备模拟环境（异步任务，LLM智能生成所有参数）
    
    这是一个耗时操作，接口会立即返回task_id，
    使用 GET /api/simulation/prepare/status 查询进度
    
    特性：
    - 自动检测已完成的准备工作，避免重复生成
    - 如果已准备完成，直接返回已有结果
    - 支持强制重新生成（force_regenerate=true）
    
    步骤：
    1. 检查是否已有完成的准备工作
    2. 从Zep图谱读取并过滤实体
    3. 为每个实体生成OASIS Agent Profile（带重试机制）
    4. LLM智能生成模拟配置（带重试机制）
    5. 保存配置文件和预设脚本
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",                   // 必填，模拟ID
            "entity_types": ["Student", "PublicFigure"],  // 可选，指定实体类型
            "use_llm_for_profiles": true,                 // 可选，是否用LLM生成人设
            "parallel_profile_count": 5,                  // 可选，并行生成人设数量，默认5
            "force_regenerate": false                     // 可选，强制重新生成，默认false
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "task_id": "task_xxxx",           // 新任务时返回
                "status": "preparing|ready",
                "message": "准备任务已启动|已有完成的准备工作",
                "already_prepared": true|false    // 是否已准备完成
            }
        }
    """
    import threading
    import os
    from ..models.task import TaskManager, TaskStatus
    from ..config import Config
    
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400
        
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        
        from ..services.simulation_manager import validate_simulation_engine
        from ..services.world_simulation.contracts import WorldError
        requested_engine = validate_simulation_engine(data.get('simulation_engine', state.simulation_engine))
        if requested_engine != state.simulation_engine:
            return jsonify({"success": False, "error": "Engine mismatch with saved simulation"}), 409
        if requested_engine == 'world-v1':
            try:
                if state.world_input_manifest_sha256:
                    if data.get('force_regenerate'):
                        raise WorldError('generation_exists', 'Prepared world is immutable; fork instead')
                    manager.validate_prepared_simulation_config(simulation_id)
                    return jsonify({"success": True, "data": {
                        **state.to_dict(), "already_prepared": True}})
                state = manager.prepare_world_simulation(
                    simulation_id, raw_spec=data.get('world_spec'),
                    research_report=data.get('research_report'),
                    research_generation_id=data.get('research_generation_id'),
                    research_engine=data.get('research_engine', 'v3'),
                    actor_bundle=data.get('actors'), policy_spec=data.get('world_policy_spec'),
                    ontology=data.get('ontology'),
                    simulation_requirement=data.get('simulation_requirement', ''))
                return jsonify({"success": True, "data": {
                    **state.to_dict(), "already_prepared": False}})
            except WorldError as exc:
                return jsonify({"success": False, "error": str(exc), "code": exc.code}), 409

        from ..services.backtest_mode import pipeline_for_simulation
        from ..services.pipeline_orchestrator import load_research_dossier_for_simulation, _calendar_mode
        owner = pipeline_for_simulation(simulation_id)
        context = load_research_dossier_for_simulation(simulation_id)
        options = owner["options"] if owner else {}

        # 检查是否强制重新生成
        force_regenerate = data.get('force_regenerate', False)
        logger.info(f"开始处理 /prepare 请求: simulation_id={simulation_id}, force_regenerate={force_regenerate}")
        
        # 检查是否已经准备完成（避免重复生成）
        if not force_regenerate:
            logger.debug(f"检查模拟 {simulation_id} 是否已准备完成...")
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            logger.debug(f"检查结果: is_prepared={is_prepared}, prepare_info={prepare_info}")
            if is_prepared:
                logger.info(f"模拟 {simulation_id} 已准备完成，跳过重复生成")
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "message": "已有完成的准备工作，无需重复生成",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
            else:
                logger.info(f"模拟 {simulation_id} 未准备完成，将启动准备任务")
        
        # 从项目获取必要信息
        project = ProjectManager.get_project(state.project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {state.project_id}"
            }), 404
        
        # Bound secondary/manual simulations consume the same research and run
        # options as their owner. Never resolve this through today's project.
        simulation_requirement = (owner.get("prompt") if owner else project.simulation_requirement) or ""
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "项目缺少模拟需求描述 (simulation_requirement)"
            }), 400
        
        # 获取文档文本
        document_text = (context.get("research_report") if owner else None)
        if document_text is None:
            document_text = ProjectManager.get_extracted_text(state.project_id) or ""
        round_budget = options.get("max_rounds") or (
            None if _calendar_mode() else (Config.OASIS_DEFAULT_MAX_ROUNDS or None))
        
        entity_types_list = data.get('entity_types')
        use_llm_for_profiles = data.get('use_llm_for_profiles', True)
        parallel_profile_count = data.get('parallel_profile_count', 5)
        
        # ========== 同步获取实体数量（在后台任务启动前） ==========
        # 这样前端在调用prepare后立即就能获取到预期Agent总数
        try:
            logger.info(f"同步获取实体数量: graph_id={state.graph_id}")
            reader = ZepEntityReader()
            # 快速读取实体（不需要边信息，只统计数量）
            filtered_preview = reader.filter_defined_entities(
                graph_id=state.graph_id,
                defined_entity_types=entity_types_list,
                enrich_with_edges=False  # 不获取边信息，加快速度
            )
            # 保存实体数量到状态（供前端立即获取）
            state.entities_count = filtered_preview.filtered_count
            state.entity_types = list(filtered_preview.entity_types)
            logger.info(f"预期实体数量: {filtered_preview.filtered_count}, 类型: {filtered_preview.entity_types}")
        except Exception as e:
            logger.warning(f"同步获取实体数量失败（将在后台任务中重试）: {e}")
            # 失败不影响后续流程，后台任务会重新获取
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="simulation_prepare",
            metadata={
                "simulation_id": simulation_id,
                "project_id": state.project_id
            }
        )
        
        # 更新模拟状态（包含预先获取的实体数量）
        state.status = SimulationStatus.PREPARING
        manager._save_simulation_state(state)
        
        # 定义后台任务
        def run_prepare():
            try:
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.PROCESSING,
                    progress=0,
                    message="开始准备模拟环境..."
                )
                
                # 准备模拟（带进度回调）
                # 存储阶段进度详情
                stage_details = {}
                
                def progress_callback(stage, progress, message, **kwargs):
                    # 计算总进度
                    stage_weights = {
                        "reading": (0, 20),           # 0-20%
                        "generating_profiles": (20, 70),  # 20-70%
                        "generating_config": (70, 90),    # 70-90%
                        "copying_scripts": (90, 100)       # 90-100%
                    }
                    
                    start, end = stage_weights.get(stage, (0, 100))
                    current_progress = int(start + (end - start) * progress / 100)
                    
                    # 构建详细进度信息
                    stage_names = {
                        "reading": "读取图谱实体",
                        "generating_profiles": "生成Agent人设",
                        "generating_config": "生成模拟配置",
                        "copying_scripts": "准备模拟脚本"
                    }
                    
                    stage_index = list(stage_weights.keys()).index(stage) + 1 if stage in stage_weights else 1
                    total_stages = len(stage_weights)
                    
                    # 更新阶段详情
                    stage_details[stage] = {
                        "stage_name": stage_names.get(stage, stage),
                        "stage_progress": progress,
                        "current": kwargs.get("current", 0),
                        "total": kwargs.get("total", 0),
                        "item_name": kwargs.get("item_name", "")
                    }
                    
                    # 构建详细进度信息
                    detail = stage_details[stage]
                    progress_detail_data = {
                        "current_stage": stage,
                        "current_stage_name": stage_names.get(stage, stage),
                        "stage_index": stage_index,
                        "total_stages": total_stages,
                        "stage_progress": progress,
                        "current_item": detail["current"],
                        "total_items": detail["total"],
                        "item_description": message
                    }
                    
                    # 构建简洁消息
                    if detail["total"] > 0:
                        detailed_message = (
                            f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: "
                            f"{detail['current']}/{detail['total']} - {message}"
                        )
                    else:
                        detailed_message = f"[{stage_index}/{total_stages}] {stage_names.get(stage, stage)}: {message}"
                    
                    task_manager.update_task(
                        task_id,
                        progress=current_progress,
                        message=detailed_message,
                        progress_detail=progress_detail_data
                    )
                
                result_state = manager.prepare_simulation(
                    simulation_id=simulation_id,
                    simulation_requirement=simulation_requirement,
                    document_text=document_text,
                    defined_entity_types=entity_types_list,
                    use_llm_for_profiles=use_llm_for_profiles,
                    progress_callback=progress_callback,
                    parallel_profile_count=parallel_profile_count,
                    actors=context.get("actors"),
                    graph_priors=(context.get("report_artifacts") or {}).get("graph_priors"),
                    research_language=options.get("research_language"),
                    max_rounds=int(round_budget) if round_budget else None,
                )
                if result_state.status != SimulationStatus.READY:
                    raise ValueError(result_state.error or "Simulation preparation did not reach ready")
                
                # 任务完成
                task_manager.complete_task(
                    task_id,
                    result=result_state.to_simple_dict()
                )
                
            except Exception as e:
                logger.error(f"准备模拟失败: {str(e)}")
                task_manager.fail_task(task_id, str(e))
                
                # 更新模拟状态为失败
                state = manager.get_simulation(simulation_id)
                if state:
                    state.status = SimulationStatus.FAILED
                    state.error = str(e)
                    manager._save_simulation_state(state)
        
        # 启动后台线程
        thread = threading.Thread(target=run_prepare, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "task_id": task_id,
                "status": "preparing",
                "message": "准备任务已启动，请通过 /api/simulation/prepare/status 查询进度",
                "already_prepared": False,
                "expected_entities_count": state.entities_count,  # 预期的Agent总数
                "entity_types": state.entity_types  # 实体类型列表
            }
        })
        
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    except Exception as e:
        logger.error(f"启动准备任务失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/prepare/status', methods=['POST'])
def get_prepare_status():
    """
    查询准备任务进度
    
    支持两种查询方式：
    1. 通过task_id查询正在进行的任务进度
    2. 通过simulation_id检查是否已有完成的准备工作
    
    请求（JSON）：
        {
            "task_id": "task_xxxx",          // 可选，prepare返回的task_id
            "simulation_id": "sim_xxxx"      // 可选，模拟ID（用于检查已完成的准备）
        }
    
    返回：
        {
            "success": true,
            "data": {
                "task_id": "task_xxxx",
                "status": "processing|completed|ready",
                "progress": 45,
                "message": "...",
                "already_prepared": true|false,  // 是否已有完成的准备
                "prepare_info": {...}            // 已准备完成时的详细信息
            }
        }
    """
    from ..models.task import TaskManager
    
    try:
        data = request.get_json() or {}
        
        task_id = data.get('task_id')
        simulation_id = data.get('simulation_id')
        
        # 如果提供了simulation_id，先检查是否已准备完成
        if simulation_id:
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
            if is_prepared:
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "ready",
                        "progress": 100,
                        "message": "已有完成的准备工作",
                        "already_prepared": True,
                        "prepare_info": prepare_info
                    }
                })
        
        # 如果没有task_id，返回错误
        if not task_id:
            if simulation_id:
                # 有simulation_id但未准备完成
                return jsonify({
                    "success": True,
                    "data": {
                        "simulation_id": simulation_id,
                        "status": "not_started",
                        "progress": 0,
                        "message": "尚未开始准备，请调用 /api/simulation/prepare 开始",
                        "already_prepared": False
                    }
                })
            return jsonify({
                "success": False,
                "error": "请提供 task_id 或 simulation_id"
            }), 400
        
        task_manager = TaskManager()
        task = task_manager.get_task(task_id)
        
        if not task:
            # 任务不存在，但如果有simulation_id，检查是否已准备完成
            if simulation_id:
                is_prepared, prepare_info = _check_simulation_prepared(simulation_id)
                if is_prepared:
                    return jsonify({
                        "success": True,
                        "data": {
                            "simulation_id": simulation_id,
                            "task_id": task_id,
                            "status": "ready",
                            "progress": 100,
                            "message": "任务已完成（准备工作已存在）",
                            "already_prepared": True,
                            "prepare_info": prepare_info
                        }
                    })
            
            return jsonify({
                "success": False,
                "error": f"任务不存在: {task_id}"
            }), 404
        
        task_dict = task.to_dict()
        task_dict["already_prepared"] = False
        
        return jsonify({
            "success": True,
            "data": task_dict
        })
        
    except Exception as e:
        logger.error(f"查询任务状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@simulation_bp.route('/<simulation_id>', methods=['GET'])
def get_simulation(simulation_id: str):
    """获取模拟状态"""
    try:
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        
        if not state:
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        
        result = state.to_dict()
        
        # 如果模拟已准备好，附加运行说明
        if state.status == SimulationStatus.READY:
            result["run_instructions"] = manager.get_run_instructions(simulation_id)
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取模拟状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/list', methods=['GET'])
def list_simulations():
    """
    列出所有模拟
    
    Query参数：
        project_id: 按项目ID过滤（可选）
    """
    try:
        project_id = request.args.get('project_id')
        
        manager = SimulationManager()
        simulations = manager.list_simulations(project_id=project_id)
        
        return jsonify({
            "success": True,
            "data": [s.to_dict() for s in simulations],
            "count": len(simulations)
        })
        
    except Exception as e:
        logger.error(f"列出模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


def _retire_report_cache_for_simulation_restart(simulation_id: str) -> None:
    """Retire current simulation cache before cleanup or replacement execution.

    Historical publication seals and ledger snapshots remain unchanged. A
    retirement write failure aborts restart before runtime artifacts change.
    """
    from ..services.report_agent import ReportManager
    ReportManager.retire_reports_for_simulation(simulation_id)


def _get_report_id_for_simulation(simulation_id: str) -> str:
    """Return the latest current report, using the manager's storage and cache policy."""
    from ..services.report_agent import ReportManager
    report = ReportManager.get_report_by_simulation(simulation_id)
    return report.report_id if report else None


@simulation_bp.route('/history', methods=['GET'])
def get_simulation_history():
    """
    获取历史模拟列表（带项目详情）
    
    用于首页历史项目展示，返回包含项目名称、描述等丰富信息的模拟列表
    
    Query参数：
        limit: 返回数量限制（默认20）
    
    返回：
        {
            "success": true,
            "data": [
                {
                    "simulation_id": "sim_xxxx",
                    "project_id": "proj_xxxx",
                    "project_name": "武大舆情分析",
                    "simulation_requirement": "如果武汉大学发布...",
                    "status": "completed",
                    "entities_count": 68,
                    "profiles_count": 68,
                    "entity_types": ["Student", "Professor", ...],
                    "created_at": "2024-12-10",
                    "updated_at": "2024-12-10",
                    "total_rounds": 120,
                    "current_round": 120,
                    "report_id": "report_xxxx",
                    "version": "v1.0.2"
                },
                ...
            ],
            "count": 7
        }
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        
        manager = SimulationManager()
        simulations = manager.list_simulations(skip_unverifiable_worlds=True)[:limit]
        
        # 增强模拟数据，只从 Simulation 文件读取
        enriched_simulations = []
        for sim in simulations:
            sim_dict = sim.to_dict()
            
            # 获取模拟配置信息（从 simulation_config.json 读取 simulation_requirement）
            config = manager.get_simulation_config(sim.simulation_id)
            if config:
                sim_dict["simulation_requirement"] = config.get("simulation_requirement", "")
                time_config = config.get("time_config", {})
                sim_dict["total_simulation_hours"] = time_config.get("total_simulation_hours", 0)
                # 推荐轮数（后备值）
                recommended_rounds = int(
                    time_config.get("total_simulation_hours", 0) * 60 / 
                    max(time_config.get("minutes_per_round", 60), 1)
                )
            else:
                sim_dict["simulation_requirement"] = ""
                sim_dict["total_simulation_hours"] = 0
                recommended_rounds = 0
            
            # 获取运行状态（从 run_state.json 读取用户设置的实际轮数）
            run_state = SimulationRunner.get_run_state(sim.simulation_id)
            if run_state:
                sim_dict["current_round"] = run_state.current_round
                sim_dict["runner_status"] = run_state.runner_status.value
                # 使用用户设置的 total_rounds，若无则使用推荐轮数
                sim_dict["total_rounds"] = run_state.total_rounds if run_state.total_rounds > 0 else recommended_rounds
            else:
                sim_dict["current_round"] = 0
                sim_dict["runner_status"] = "idle"
                sim_dict["total_rounds"] = recommended_rounds
            
            # 获取关联项目的文件列表（最多3个）
            project = ProjectManager.get_project(sim.project_id)
            if project and hasattr(project, 'files') and project.files:
                sim_dict["files"] = [
                    {"filename": f.get("filename", "未知文件")} 
                    for f in project.files[:3]
                ]
            else:
                sim_dict["files"] = []
            
            # 获取关联的 report_id（查找该 simulation 最新的 report）
            sim_dict["report_id"] = _get_report_id_for_simulation(sim.simulation_id)
            
            # 添加版本号
            sim_dict["version"] = "v1.0.2"
            
            # 格式化日期
            try:
                created_date = sim_dict.get("created_at", "")[:10]
                sim_dict["created_date"] = created_date
            except:
                sim_dict["created_date"] = ""
            
            enriched_simulations.append(sim_dict)
        
        return jsonify({
            "success": True,
            "data": enriched_simulations,
            "count": len(enriched_simulations)
        })
        
    except Exception as e:
        logger.error(f"获取历史模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles', methods=['GET'])
def get_simulation_profiles(simulation_id: str):
    """
    获取模拟的Agent Profile
    
    Query参数：
        platform: 平台类型（reddit/twitter，默认reddit）
    """
    try:
        platform = request.args.get('platform', 'reddit')
        
        manager = SimulationManager()
        profiles = manager.get_profiles(simulation_id, platform=platform)
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(profiles),
                "profiles": profiles
            }
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 404
        
    except Exception as e:
        logger.error(f"获取Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/profiles/realtime', methods=['GET'])
def get_simulation_profiles_realtime(simulation_id: str):
    """
    实时获取模拟的Agent Profile（用于在生成过程中实时查看进度）
    
    与 /profiles 接口的区别：
    - 直接读取文件，不经过 SimulationManager
    - 适用于生成过程中的实时查看
    - 返回额外的元数据（如文件修改时间、是否正在生成等）
    
    Query参数：
        platform: 平台类型（reddit/twitter，默认reddit）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "platform": "reddit",
                "count": 15,
                "total_expected": 93,  // 预期总数（如果有）
                "is_generating": true,  // 是否正在生成
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "profiles": [...]
            }
        }
    """
    import json
    import csv
    from datetime import datetime
    
    try:
        platform = request.args.get('platform', 'reddit')
        
        # 获取模拟目录
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        
        # 确定文件路径
        if platform == "reddit":
            profiles_file = os.path.join(sim_dir, "reddit_profiles.json")
        else:
            profiles_file = os.path.join(sim_dir, "twitter_profiles.csv")
        
        # 检查文件是否存在
        file_exists = os.path.exists(profiles_file)
        profiles = []
        file_modified_at = None
        
        if file_exists:
            # 获取文件修改时间
            file_stat = os.stat(profiles_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                if platform == "reddit":
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        profiles = json.load(f)
                else:
                    with open(profiles_file, 'r', encoding='utf-8') as f:
                        reader = csv.DictReader(f)
                        profiles = list(reader)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"读取 profiles 文件失败（可能正在写入中）: {e}")
                profiles = []
        
        # 检查是否正在生成（通过 state.json 判断）
        is_generating = False
        total_expected = None
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    total_expected = state_data.get("entities_count")
            except Exception:
                pass
        
        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "platform": platform,
                "count": len(profiles),
                "total_expected": total_expected,
                "is_generating": is_generating,
                "file_exists": file_exists,
                "file_modified_at": file_modified_at,
                "profiles": profiles
            }
        })
        
    except Exception as e:
        logger.error(f"实时获取Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/realtime', methods=['GET'])
def get_simulation_config_realtime(simulation_id: str):
    """
    实时获取模拟配置（用于在生成过程中实时查看进度）
    
    与 /config 接口的区别：
    - 直接读取文件，不经过 SimulationManager
    - 适用于生成过程中的实时查看
    - 返回额外的元数据（如文件修改时间、是否正在生成等）
    - 即使配置还没生成完也能返回部分信息
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "file_exists": true,
                "file_modified_at": "2025-12-04T18:20:00",
                "is_generating": true,  // 是否正在生成
                "generation_stage": "generating_config",  // 当前生成阶段
                "config": {...}  // 配置内容（如果存在）
            }
        }
    """
    import json
    from datetime import datetime
    
    try:
        # 获取模拟目录
        sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, simulation_id)
        
        if not os.path.exists(sim_dir):
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        
        # 配置文件路径
        config_file = os.path.join(sim_dir, "simulation_config.json")
        
        # 检查文件是否存在
        file_exists = os.path.exists(config_file)
        config = None
        file_modified_at = None
        
        if file_exists:
            # 获取文件修改时间
            file_stat = os.stat(config_file)
            file_modified_at = datetime.fromtimestamp(file_stat.st_mtime).isoformat()
            
            try:
                with open(config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"读取 config 文件失败（可能正在写入中）: {e}")
                config = None
        
        # 检查是否正在生成（通过 state.json 判断）
        is_generating = False
        generation_stage = None
        config_generated = False
        
        state_file = os.path.join(sim_dir, "state.json")
        if os.path.exists(state_file):
            try:
                with open(state_file, 'r', encoding='utf-8') as f:
                    state_data = json.load(f)
                    status = state_data.get("status", "")
                    is_generating = status == "preparing"
                    config_generated = state_data.get("config_generated", False)
                    
                    # 判断当前阶段
                    if is_generating:
                        if state_data.get("profiles_generated", False):
                            generation_stage = "generating_config"
                        else:
                            generation_stage = "generating_profiles"
                    elif status == "ready":
                        generation_stage = "completed"
            except Exception:
                pass
        
        # 构建返回数据
        response_data = {
            "simulation_id": simulation_id,
            "file_exists": file_exists,
            "file_modified_at": file_modified_at,
            "is_generating": is_generating,
            "generation_stage": generation_stage,
            "config_generated": config_generated,
            "config": config
        }
        
        # 如果配置存在，提取一些关键统计信息
        if config:
            response_data["summary"] = {
                "total_agents": len(config.get("agent_configs", [])),
                "simulation_hours": config.get("time_config", {}).get("total_simulation_hours"),
                "initial_posts_count": len(config.get("event_config", {}).get("initial_posts", [])),
                "hot_topics_count": len(config.get("event_config", {}).get("hot_topics", [])),
                "has_twitter_config": "twitter_config" in config,
                "has_reddit_config": "reddit_config" in config,
                "generated_at": config.get("generated_at"),
                "llm_model": config.get("llm_model")
            }
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except Exception as e:
        logger.error(f"实时获取Config失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config', methods=['GET'])
def get_simulation_config(simulation_id: str):
    """
    获取模拟配置（LLM智能生成的完整配置）
    
    返回包含：
        - time_config: 时间配置（模拟时长、轮次、高峰/低谷时段）
        - agent_configs: 每个Agent的活动配置（活跃度、发言频率、立场等）
        - event_config: 事件配置（初始帖子、热点话题）
        - platform_configs: 平台配置
        - generation_reasoning: LLM的配置推理说明
    """
    try:
        manager = SimulationManager()
        config = manager.get_simulation_config(simulation_id)
        
        if not config:
            return jsonify({
                "success": False,
                "error": f"模拟配置不存在，请先调用 /prepare 接口"
            }), 404
        
        return jsonify({
            "success": True,
            "data": config
        })
        
    except Exception as e:
        logger.error(f"获取配置失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/config/download', methods=['GET'])
def download_simulation_config(simulation_id: str):
    """下载模拟配置文件"""
    try:
        manager = SimulationManager()
        sim_dir = manager._get_simulation_dir(simulation_id)
        config_path = os.path.join(sim_dir, "simulation_config.json")
        
        if not os.path.exists(config_path):
            return jsonify({
                "success": False,
                "error": "配置文件不存在，请先调用 /prepare 接口"
            }), 404
        
        return send_file(
            config_path,
            as_attachment=True,
            download_name="simulation_config.json"
        )
        
    except Exception as e:
        logger.error(f"下载配置失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/script/<script_name>/download', methods=['GET'])
def download_simulation_script(script_name: str):
    """
    下载模拟运行脚本文件（通用脚本，位于 backend/scripts/）
    
    script_name可选值：
        - run_twitter_simulation.py
        - run_reddit_simulation.py
        - run_parallel_simulation.py
        - action_logger.py
    """
    try:
        # 脚本位于 backend/scripts/ 目录
        scripts_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../scripts'))
        
        # 验证脚本名称
        allowed_scripts = [
            "run_twitter_simulation.py",
            "run_reddit_simulation.py", 
            "run_parallel_simulation.py",
            "action_logger.py"
        ]
        
        if script_name not in allowed_scripts:
            return jsonify({
                "success": False,
                "error": f"未知脚本: {script_name}，可选: {allowed_scripts}"
            }), 400
        
        script_path = os.path.join(scripts_dir, script_name)
        
        if not os.path.exists(script_path):
            return jsonify({
                "success": False,
                "error": f"脚本文件不存在: {script_name}"
            }), 404
        
        return send_file(
            script_path,
            as_attachment=True,
            download_name=script_name
        )
        
    except Exception as e:
        logger.error(f"下载脚本失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Profile生成接口（独立使用） ==============

@simulation_bp.route('/generate-profiles', methods=['POST'])
def generate_profiles():
    """
    直接从图谱生成OASIS Agent Profile（不创建模拟）
    
    请求（JSON）：
        {
            "graph_id": "mirofish_xxxx",     // 必填
            "entity_types": ["Student"],      // 可选
            "use_llm": true,                  // 可选
            "platform": "reddit"              // 可选
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
        
        entity_types = data.get('entity_types')
        use_llm = data.get('use_llm', True)
        platform = data.get('platform', 'reddit')
        
        reader = ZepEntityReader()
        filtered = reader.filter_defined_entities(
            graph_id=graph_id,
            defined_entity_types=entity_types,
            enrich_with_edges=True
        )
        
        if filtered.filtered_count == 0:
            return jsonify({
                "success": False,
                "error": "没有找到符合条件的实体"
            }), 400
        
        generator = OasisProfileGenerator()
        profiles = generator.generate_profiles_from_entities(
            entities=filtered.entities,
            use_llm=use_llm
        )
        
        if platform == "reddit":
            profiles_data = [p.to_reddit_format() for p in profiles]
        elif platform == "twitter":
            profiles_data = [p.to_twitter_format() for p in profiles]
        else:
            profiles_data = [p.to_dict() for p in profiles]
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "entity_types": list(filtered.entity_types),
                "count": len(profiles_data),
                "profiles": profiles_data
            }
        })
        
    except Exception as e:
        logger.error(f"生成Profile失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 模拟运行控制接口 ==============

@simulation_bp.route('/start', methods=['POST'])
def start_simulation():
    """
    开始运行模拟

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",          // 必填，模拟ID
            "platform": "parallel",                // 可选: twitter / reddit / parallel (默认)
            "max_rounds": 100,                     // 可选: 最大模拟轮数，用于截断过长的模拟
            "enable_graph_memory_update": false,   // 可选: 是否将Agent活动动态更新到Zep图谱记忆
            "force": false                         // 可选: 强制重新开始（会停止运行中的模拟并清理日志）
        }

    关于 force 参数：
        - 启用后，如果模拟正在运行或已完成，会先停止并清理运行日志
        - 清理的内容包括：run_state.json, actions.jsonl, simulation.log 等
        - 不会清理配置文件（simulation_config.json）和 profile 文件
        - 适用于需要重新运行模拟的场景

    关于 enable_graph_memory_update：
        - 启用后，模拟中所有Agent的活动（发帖、评论、点赞等）都会实时更新到Zep图谱
        - 这可以让图谱"记住"模拟过程，用于后续分析或AI对话
        - 需要模拟关联的项目有有效的 graph_id
        - 采用批量更新机制，减少API调用次数

    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "process_pid": 12345,
                "twitter_running": true,
                "reddit_running": true,
                "started_at": "2025-12-01T10:00:00",
                "graph_memory_update_enabled": true,  // 是否启用了图谱记忆更新
                "force_restarted": true               // 是否是强制重新开始
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

        platform = data.get('platform', 'parallel')
        max_rounds = data.get('max_rounds')  # 可选：最大模拟轮数
        enable_graph_memory_update = data.get('enable_graph_memory_update', False)  # 可选：是否启用图谱记忆更新
        force = data.get('force', False)  # 可选：强制重新开始

        # 验证 max_rounds 参数
        if max_rounds is not None:
            try:
                max_rounds = int(max_rounds)
                if max_rounds <= 0:
                    return jsonify({
                        "success": False,
                        "error": "max_rounds 必须是正整数"
                    }), 400
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": "max_rounds 必须是有效的整数"
                }), 400

        if platform not in ['twitter', 'reddit', 'parallel']:
            return jsonify({
                "success": False,
                "error": f"无效的平台类型: {platform}，可选: twitter/reddit/parallel"
            }), 400

        # 检查模拟是否已准备好
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)

        if not state:
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404

        prepared_engine = getattr(state, 'simulation_engine', 'oasis-legacy')
        requested_engine = data.get('simulation_engine', prepared_engine)
        if not isinstance(requested_engine, str) or requested_engine not in {'oasis-legacy', 'world-v1'}:
            return jsonify({"success": False, "error": "Unsupported simulation_engine"}), 400
        if requested_engine != prepared_engine:
            return jsonify({
                "success": False,
                "error": f"Engine mismatch: requested {requested_engine}, prepared {prepared_engine}",
            }), 409

        if requested_engine == 'world-v1':
            if force:
                return jsonify({"success": False, "error": "World history is immutable; fork instead"}), 409
            manager.validate_prepared_simulation_config(simulation_id)
            run_state = SimulationRunner.start_simulation(
                simulation_id=simulation_id, max_rounds=max_rounds,
                enable_graph_memory_update=enable_graph_memory_update)
            return jsonify({"success": True, "data": run_state.to_dict()})

        force_restarted = False
        
        # 智能处理状态：如果准备工作已完成，允许重新启动
        if state.status != SimulationStatus.READY:
            # 检查准备工作是否已完成
            is_prepared, prepare_info = _check_simulation_prepared(simulation_id)

            if is_prepared:
                # Retirement must be durable before stopping an existing run,
                # cleaning its artifacts, or starting replacement work.
                if force:
                    _retire_report_cache_for_simulation_restart(simulation_id)
                # 准备工作已完成，检查是否有正在运行的进程
                if state.status == SimulationStatus.RUNNING:
                    # 检查模拟进程是否真的在运行
                    run_state = SimulationRunner.get_run_state(simulation_id)
                    if run_state and run_state.runner_status.value == "running":
                        # 进程确实在运行
                        if force:
                            # 强制模式：停止运行中的模拟
                            logger.info(f"强制模式：停止运行中的模拟 {simulation_id}")
                            try:
                                SimulationRunner.stop_simulation(simulation_id)
                            except Exception as e:
                                logger.warning(f"停止模拟时出现警告: {str(e)}")
                        else:
                            return jsonify({
                                "success": False,
                                "error": f"模拟正在运行中，请先调用 /stop 接口停止，或使用 force=true 强制重新开始"
                            }), 400

                # 如果是强制模式，清理运行日志
                if force:
                    logger.info(f"强制模式：清理模拟日志 {simulation_id}")
                    cleanup_result = SimulationRunner.cleanup_simulation_logs(simulation_id)
                    if not cleanup_result.get("success"):
                        logger.warning(f"清理日志时出现警告: {cleanup_result.get('errors')}")
                    force_restarted = True

                # 进程不存在或已结束，重置状态为 ready
                logger.info(f"模拟 {simulation_id} 准备工作已完成，重置状态为 ready（原状态: {state.status.value}）")
                state.status = SimulationStatus.READY
                manager._save_simulation_state(state)
            else:
                # 准备工作未完成
                return jsonify({
                    "success": False,
                    "error": f"模拟未准备好，当前状态: {state.status.value}，请先调用 /prepare 接口"
                }), 400
        
        # 获取图谱ID（用于图谱记忆更新）
        graph_id = None
        if enable_graph_memory_update:
            # 从模拟状态或项目中获取 graph_id
            graph_id = state.graph_id
            if not graph_id:
                # 尝试从项目中获取
                project = ProjectManager.get_project(state.project_id)
                if project:
                    graph_id = project.graph_id
            
            if not graph_id:
                return jsonify({
                    "success": False,
                    "error": "启用图谱记忆更新需要有效的 graph_id，请确保项目已构建图谱"
                }), 400
            
            logger.info(f"启用图谱记忆更新: simulation_id={simulation_id}, graph_id={graph_id}")
        
        # A READY simulation may also have an older completed report (for
        # example after an earlier failed restart). Invalidate before execution.
        if not force_restarted:
            _retire_report_cache_for_simulation_restart(simulation_id)

        # 启动模拟
        run_state = SimulationRunner.start_simulation(
            simulation_id=simulation_id,
            platform=platform,
            max_rounds=max_rounds,
            enable_graph_memory_update=enable_graph_memory_update,
            graph_id=graph_id
        )
        
        # 更新模拟状态
        state.status = SimulationStatus.RUNNING
        manager._save_simulation_state(state)
        
        response_data = run_state.to_dict()
        if max_rounds:
            response_data['max_rounds_applied'] = max_rounds
        # 报告「实际」开启状态而非请求标志（EXECPLAN2 F-6-12）：创建更新器若失败，
        # run_state.graph_memory_active 为 False，且带 graph_memory_error 说明原因。
        response_data['graph_memory_update_enabled'] = run_state.graph_memory_active
        response_data['graph_memory_requested'] = run_state.graph_memory_requested
        if run_state.graph_memory_error:
            response_data['graph_memory_error'] = run_state.graph_memory_error
        response_data['force_restarted'] = force_restarted
        if enable_graph_memory_update:
            response_data['graph_id'] = graph_id
        
        return jsonify({
            "success": True,
            "data": response_data
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"启动模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/stop', methods=['POST'])
def stop_simulation():
    """
    停止模拟
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx"  // 必填，模拟ID
        }
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "stopped",
                "completed_at": "2025-12-01T12:00:00"
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
        
        run_state = SimulationRunner.stop_simulation(simulation_id)
        
        # 更新模拟状态
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state and state.simulation_engine == "oasis-legacy":
            state.status = SimulationStatus.PAUSED
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"停止模拟失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 实时状态监控接口 ==============

@simulation_bp.route('/<simulation_id>/run-status', methods=['GET'])
def get_run_status(simulation_id: str):
    """
    获取模拟运行实时状态（用于前端轮询）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                "total_rounds": 144,
                "progress_percent": 3.5,
                "simulated_hours": 2,
                "total_simulation_hours": 72,
                "twitter_running": true,
                "reddit_running": true,
                "twitter_actions_count": 150,
                "reddit_actions_count": 200,
                "total_actions_count": 350,
                "started_at": "2025-12-01T10:00:00",
                "updated_at": "2025-12-01T10:30:00"
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "current_round": 0,
                    "total_rounds": 0,
                    "progress_percent": 0,
                    "twitter_actions_count": 0,
                    "reddit_actions_count": 0,
                    "total_actions_count": 0,
                }
            })
        
        return jsonify({
            "success": True,
            "data": run_state.to_dict()
        })
        
    except Exception as e:
        logger.error(f"获取运行状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/run-status/detail', methods=['GET'])
def get_run_status_detail(simulation_id: str):
    """
    获取模拟运行详细状态（包含所有动作）
    
    用于前端展示实时动态
    
    Query参数：
        platform: 过滤平台（twitter/reddit，可选）
    
    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "runner_status": "running",
                "current_round": 5,
                ...
                "all_actions": [
                    {
                        "round_num": 5,
                        "timestamp": "2025-12-01T10:30:00",
                        "platform": "twitter",
                        "agent_id": 3,
                        "agent_name": "Agent Name",
                        "action_type": "CREATE_POST",
                        "action_args": {"content": "..."},
                        "result": null,
                        "success": true
                    },
                    ...
                ],
                "twitter_actions": [...],  # Twitter 平台的所有动作
                "reddit_actions": [...]    # Reddit 平台的所有动作
            }
        }
    """
    try:
        run_state = SimulationRunner.get_run_state(simulation_id)
        platform_filter = request.args.get('platform')
        
        if not run_state:
            return jsonify({
                "success": True,
                "data": {
                    "simulation_id": simulation_id,
                    "runner_status": "idle",
                    "all_actions": [],
                    "twitter_actions": [],
                    "reddit_actions": []
                }
            })
        
        # EXECPLAN2 F-6-2: 读一次 actions.jsonl，其余切片在内存里派生，避免每次请求把两份
        # 全量 actions.jsonl 重复解析最多 4 次（输出与旧逻辑完全一致）。
        all_actions = SimulationRunner.get_all_actions(
            simulation_id=simulation_id,
            platform=platform_filter
        )

        # 分平台动作：从已读的 all_actions 内存过滤
        twitter_actions = (
            [a for a in all_actions if a.platform == "twitter"]
            if (not platform_filter or platform_filter == "twitter") else []
        )
        reddit_actions = (
            [a for a in all_actions if a.platform == "reddit"]
            if (not platform_filter or platform_filter == "reddit") else []
        )

        # 当前轮次动作（recent_actions 只展示最新一轮）—— 同样在内存里过滤
        current_round = run_state.current_round
        recent_actions = (
            [a for a in all_actions if a.round_num == current_round]
            if current_round > 0 else []
        )
        
        # 获取基础状态信息
        result = run_state.to_dict()
        result["all_actions"] = [a.to_dict() for a in all_actions]
        result["twitter_actions"] = [a.to_dict() for a in twitter_actions]
        result["reddit_actions"] = [a.to_dict() for a in reddit_actions]
        result["rounds_count"] = len(run_state.rounds)
        # recent_actions 只展示当前最新一轮两个平台的内容
        result["recent_actions"] = [a.to_dict() for a in recent_actions]
        
        return jsonify({
            "success": True,
            "data": result
        })
        
    except Exception as e:
        logger.error(f"获取详细状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/actions', methods=['GET'])
def get_simulation_actions(simulation_id: str):
    """
    获取模拟中的Agent动作历史
    
    Query参数：
        limit: 返回数量（默认100）
        offset: 偏移量（默认0）
        platform: 过滤平台（twitter/reddit）
        agent_id: 过滤Agent ID
        round_num: 过滤轮次
    
    返回：
        {
            "success": true,
            "data": {
                "count": 100,
                "actions": [...]
            }
        }
    """
    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        platform = request.args.get('platform')
        agent_id = request.args.get('agent_id', type=int)
        round_num = request.args.get('round_num', type=int)
        
        actions = SimulationRunner.get_actions(
            simulation_id=simulation_id,
            limit=limit,
            offset=offset,
            platform=platform,
            agent_id=agent_id,
            round_num=round_num
        )
        
        return jsonify({
            "success": True,
            "data": {
                "count": len(actions),
                "actions": [a.to_dict() for a in actions]
            }
        })
        
    except Exception as e:
        logger.error(f"获取动作历史失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/timeline', methods=['GET'])
def get_simulation_timeline(simulation_id: str):
    """
    获取模拟时间线（按轮次汇总）
    
    用于前端展示进度条和时间线视图
    
    Query参数：
        start_round: 起始轮次（默认0）
        end_round: 结束轮次（默认全部）
    
    返回每轮的汇总信息
    """
    try:
        start_round = request.args.get('start_round', 0, type=int)
        end_round = request.args.get('end_round', type=int)
        
        timeline = SimulationRunner.get_timeline(
            simulation_id=simulation_id,
            start_round=start_round,
            end_round=end_round
        )
        
        return jsonify({
            "success": True,
            "data": {
                "rounds_count": len(timeline),
                "timeline": timeline
            }
        })
        
    except Exception as e:
        logger.error(f"获取时间线失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 决策通道轨迹接口（Step3 实时可视化） ==============

# 响应体上界：文件大小上限（正常轨迹只有几 KB；超限拒绝解析）与返回行数上限
# （超限保留最新行并标记 truncated）。
TRAJECTORY_MAX_BYTES = 5 * 1024 * 1024
TRAJECTORY_MAX_ROWS = 720


@simulation_bp.route('/<simulation_id>/trajectory', methods=['GET'])
def get_simulation_trajectory(simulation_id: str):
    """读取模拟目录的 world_state_trajectory.json（决策通道产物）供前端实时轮询。

    Step3 的世界态堆叠面积图按详细状态轮询节奏调用本端点；模拟早期轮次文件
    尚未产出属正常态 → 404，前端静默等待。

    安全姿态与报告图表端点（report.get_report_chart）一致：realpath containment
    钉死在 OASIS_SIMULATION_DATA_DIR 下 + 拒绝 symlink；越界/缺失一律 404，不泄漏
    路径细节。响应体有界（TRAJECTORY_MAX_BYTES / TRAJECTORY_MAX_ROWS）。

    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxx",
                "rows_count": 18,
                "total_rows": 18,
                "truncated": false,
                "trajectory": [{"round": 0, "shares": {"情景A": 0.5, ...}, ...}, ...]
            }
        }
    """
    try:
        raw_id = str(simulation_id or "")
        # 字符层校验先行（NUL/控制字符会让 realpath 直接抛错，须在其前拒绝）
        if (not raw_id or raw_id in (".", "..") or "/" in raw_id or "\\" in raw_id
                or any(ord(char) < 32 or ord(char) == 127 for char in raw_id)):
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404
        sim_root = os.path.realpath(Config.OASIS_SIMULATION_DATA_DIR)
        sim_dir = os.path.realpath(os.path.join(sim_root, raw_id))
        if (os.path.commonpath([sim_dir, sim_root]) != sim_root
                or sim_dir == sim_root):
            return jsonify({
                "success": False,
                "error": f"模拟不存在: {simulation_id}"
            }), 404

        path = os.path.join(sim_dir, "world_state_trajectory.json")
        if os.path.islink(path) or not os.path.isfile(path):
            return jsonify({
                "success": False,
                "error": "世界态轨迹尚未生成（决策通道未产出或模拟尚在早期轮次）"
            }), 404
        if os.path.getsize(path) > TRAJECTORY_MAX_BYTES:
            return jsonify({
                "success": False,
                "error": "轨迹文件超出大小上限"
            }), 413

        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
        except ValueError:
            return jsonify({
                "success": False,
                "error": "轨迹文件解析失败"
            }), 500

        # 兼容 {trajectory: [...]}（schema v2/v3）与裸列表；只保留 dict 行。
        rows = payload.get("trajectory") if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            rows = []
        rows = [r for r in rows if isinstance(r, dict)]
        total_rows = len(rows)
        truncated = total_rows > TRAJECTORY_MAX_ROWS
        if truncated:
            rows = rows[-TRAJECTORY_MAX_ROWS:]  # 保留最新的行（图表关心的是最近走势）

        data = {
            "simulation_id": raw_id,
            "rows_count": len(rows),
            "total_rows": total_rows,
            "truncated": truncated,
            "trajectory": rows,
        }
        if isinstance(payload, dict):
            # 只透传有界的标量元数据，绝不透传未知的大对象。
            for key in ("schema_version", "converged", "settled_round"):
                value = payload.get(key)
                if key in payload and isinstance(value, (str, int, float, bool)):
                    data[key] = value

        return jsonify({"success": True, "data": data})

    except Exception as e:
        logger.error(f"读取世界态轨迹失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


WORLD_STATE_MAX_BYTES = 8 * 1024 * 1024
WORLD_STATE_MAX_HISTORY = 200
WORLD_STATE_MAX_EVENTS = 40
WORLD_STATE_MAX_PROBLEMS = 12      # arbiter problems kept per history row (the kernel records at most 12)
WORLD_STATE_MAX_DIGEST = 20000     # 2026-10-21: digest 不截断（保留病理上限）




def _bounded_jsonl_rows(path: str):
    """Dict rows of a per-run JSONL artifact, in file order, or [] when the file is missing.

    Same posture as the world-state file: a regular file only (symlinks refused), the
    WORLD_STATE_MAX_BYTES size cap, malformed or non-object lines skipped.
    """
    import json
    if os.path.islink(path) or not os.path.isfile(path) or os.path.getsize(path) > WORLD_STATE_MAX_BYTES:
        return []
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if isinstance(row, dict):
                    rows.append(row)
    except OSError:
        return []
    return rows


def _contained_sim_dir(simulation_id: str):
    """realpath containment under OASIS_SIMULATION_DATA_DIR (same posture as the trajectory route)."""
    raw_id = str(simulation_id or "")
    if (not raw_id or raw_id in (".", "..") or "/" in raw_id or "\\" in raw_id
            or any(ord(char) < 32 or ord(char) == 127 for char in raw_id)):
        return None
    sim_root = os.path.realpath(Config.OASIS_SIMULATION_DATA_DIR)
    sim_dir = os.path.realpath(os.path.join(sim_root, raw_id))
    if os.path.commonpath([sim_dir, sim_root]) != sim_root or sim_dir == sim_root:
        return None
    return sim_dir


_FEED_PLATFORM_RE = re.compile(r"[a-z0-9_]{1,32}")


def _feed_rows_for_round(simulation_id: str, platform: str, round_arg, kind: str, limit, offset):
    """PERIOD VIEW: the posts (or comments) of one round of a platform's feed.

    Posts of round r are those created in r plus the parents of replies written in r, so a
    thread discussed this period shows with only this period's replies; every row carries
    ``round`` and the response carries the round's ``period_label``.  Containment and bounds
    follow the world-state route (``_contained_sim_dir``); the index comes from
    ``services.feed_rounds`` (read-only, cached on the artefacts' mtime/size).
    """
    import sqlite3
    from ..services.feed_rounds import cached_feed_round_index, ids_for_round, load_platform_rows
    try:
        rnd = int(round_arg)
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "round 必须是整数"}), 400
    platform = str(platform or "reddit")
    if not _FEED_PLATFORM_RE.fullmatch(platform):
        return jsonify({"success": False, "error": "platform 非法"}), 400
    sim_dir = _contained_sim_dir(simulation_id)
    if sim_dir is None or not os.path.isdir(sim_dir):
        return jsonify({"success": False, "error": f"模拟不存在: {simulation_id}"}), 404
    try:
        limit = max(1, min(int(limit or 50), 2000))
        offset = max(0, int(offset or 0))
    except (TypeError, ValueError):
        limit, offset = 50, 0
    index = cached_feed_round_index(sim_dir, platform)
    labels = {r["round"]: r["period_label"] for r in index["rounds"]}
    db_path = os.path.join(sim_dir, f"{platform}_simulation.db")
    _posts, comments, _agents = load_platform_rows(db_path)
    post_ids, comment_ids = ids_for_round(index, rnd, comments)
    if kind == "posts":
        table, id_col, ids, rounds_map = "post", "post_id", post_ids, index["post_round"]
    else:
        table, id_col, ids, rounds_map = "comment", "comment_id", comment_ids, index["comment_round"]
    rows = []
    if ids and os.path.isfile(db_path) and not os.path.islink(db_path):
        uri = "file:" + os.path.abspath(db_path).replace("?", "%3F") + "?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.cursor()
            for start in range(0, len(ids), 500):
                chunk = ids[start:start + 500]
                marks = ",".join("?" for _ in chunk)
                try:
                    cur.execute(f"SELECT * FROM {table} WHERE {id_col} IN ({marks})", chunk)
                    rows.extend(dict(r) for r in cur.fetchall())
                except sqlite3.OperationalError:
                    break
        finally:
            conn.close()
    rows.sort(key=lambda r: (str(r.get("created_at") or ""), int(r.get(id_col) or 0)), reverse=True)
    for r in rows:
        r["round"] = rounds_map.get(int(r.get(id_col) or -1))
    page = rows[offset:offset + limit]
    return jsonify({
        "success": True,
        "data": {
            "platform": platform,
            "round": rnd,
            "period_label": labels.get(rnd, ""),
            "total": len(rows),
            "count": len(page),
            kind: page,
        }
    })


@simulation_bp.route('/<simulation_id>/feed-rounds', methods=['GET'])
def get_simulation_feed_rounds(simulation_id: str):
    """PERIOD VIEW: the rounds of a platform's feed with their period labels, headlines and
    post/reply counts (``services.feed_rounds``).  Empty ``rounds`` when the run has no
    action log yet; 404 for an unknown or uncontained simulation id."""
    try:
        from ..services.feed_rounds import cached_feed_round_index, public_index
        platform = str(request.args.get('platform', 'reddit') or "reddit")
        if not _FEED_PLATFORM_RE.fullmatch(platform):
            return jsonify({"success": False, "error": "platform 非法"}), 400
        sim_dir = _contained_sim_dir(simulation_id)
        if sim_dir is None or not os.path.isdir(sim_dir):
            return jsonify({"success": False, "error": f"模拟不存在: {simulation_id}"}), 404
        return jsonify({"success": True, "data": public_index(cached_feed_round_index(sim_dir, platform))})
    except Exception as e:  # noqa: BLE001
        logger.error(f"读取信息流轮次索引失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def _world_interactions(world: dict, limit: int = 24) -> list:
    """Offers and agreements of a ``world_state.json`` world block, open first then newest."""
    names = {}
    for a in (world.get("actors") or []):
        if isinstance(a, dict) and a.get("agent_id") is not None:
            names[a.get("agent_id")] = str(a.get("name") or f"Agent {a.get('agent_id')}")
    rows = [it for it in (world.get("interactions") or []) if isinstance(it, dict) and it.get("id")]
    rows.sort(key=lambda it: (0 if it.get("status") in ("open", "deferred") else 1,
                              -int(it.get("resolved_round") or it.get("opened_round") or 0), str(it.get("id"))))
    out = []
    for it in rows[:limit]:
        out.append({
            "id": str(it.get("id"))[:40], "kind": str(it.get("kind") or "proposal")[:16],
            "status": str(it.get("status") or "open")[:16],
            "proposer": names.get(it.get("proposer"), str(it.get("proposer"))),
            "recipient": names.get(it.get("recipient"), str(it.get("recipient"))),
            "terms": str(it.get("terms") or "")[:300], "opened_round": it.get("opened_round"),
            "expires_round": it.get("expires_round"), "resolved_round": it.get("resolved_round"),
            "response": str(it.get("response") or "")[:200], "obligations": len(it.get("obligations") or []),
        })
    return out


class _WorldStateReadError(ValueError):
    """Keep the world-state HTTP errors while exposing a Flask-free reader."""

    def __init__(self, message, status):
        super().__init__(message)
        self.status = status


def _read_simulation_world_state(simulation_id: str, rows=24) -> dict:
    """Read exactly the public /world-state projection; never create or repair files."""
    import json

    sim_dir = _contained_sim_dir(simulation_id)
    if sim_dir is None:
        raise FileNotFoundError(f"模拟不存在: {simulation_id}")
    path = os.path.join(sim_dir, "world_state.json")
    if os.path.islink(path) or not os.path.isfile(path):
        raise FileNotFoundError("世界状态尚未生成（非反身世界模式或模拟尚在早期轮次）")
    if os.path.getsize(path) > WORLD_STATE_MAX_BYTES:
        raise _WorldStateReadError("世界状态文件超出大小上限", 413)
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except ValueError:
        raise _WorldStateReadError("世界状态文件解析失败", 500) from None
    if not isinstance(payload, dict):
        raise _WorldStateReadError("世界状态文件解析失败", 500)
    world = payload.get("world") if isinstance(payload.get("world"), dict) else {}
    try:
        rows_wanted = max(1, min(WORLD_STATE_MAX_HISTORY, int(rows)))
    except (TypeError, ValueError):
        rows_wanted = 24
    # per-round digests (what the agents were shown), keyed by round; the latest one is
    # also the top-level ``digest`` below.  Only the text travels — never the shares.
    digests = {}
    for drow in _bounded_jsonl_rows(os.path.join(sim_dir, "world_digest.jsonl")):
        if drow.get("round") is not None:
            digests[drow.get("round")] = str(drow.get("digest") or "")[:WORLD_STATE_MAX_DIGEST]
    history = []
    for row in _bounded_jsonl_rows(os.path.join(sim_dir, "world_state_history.jsonl"))[-rows_wanted:]:
        problems = row.get("arbiter_problems") if isinstance(row.get("arbiter_problems"), list) else []
        entry = {
            "round": row.get("round"), "period_label": row.get("period_label"),
            "headline": str(row.get("headline") or "")[:2000],
            "narrative": str(row.get("narrative") or "")[:8000],
            "arbiter_status": row.get("arbiter_status"),
            "arbiter_problems": [str(p)[:600] for p in problems[:WORLD_STATE_MAX_PROBLEMS]],
            "decisions": row.get("decisions"),
            "diff": row.get("diff") if isinstance(row.get("diff"), dict) else {},
            "scenario_pressure": row.get("scenario_pressure") or {},
            "deterministic": row.get("deterministic") or {},
            "digest": digests.get(row.get("round"), ""),
        }
        # RED LINES crossed in the period (the kernel's apply summary), for the panel's past-period
        # view once the round's events have left the recent-event window; absent when none
        arbiter = row.get("arbiter") if isinstance(row.get("arbiter"), dict) else {}
        crossed = arbiter.get("red_lines_crossed") if isinstance(arbiter.get("red_lines_crossed"), list) else []
        crossed = [{k: str(c.get(k) or "")[:160] for k in ("actor", "by", "red_line")}
                   for c in crossed[:4] if isinstance(c, dict)]
        if crossed:
            entry["red_lines_crossed"] = crossed
        if row.get("error"):
            entry["error"] = str(row.get("error"))[:200]
        history.append(entry)
    variables = []
    for v in (world.get("variables") or [])[:64]:
        if not isinstance(v, dict):
            continue
        hist = [h for h in (v.get("history") or []) if isinstance(h, dict)][-12:]
        variables.append({"id": v.get("id"), "name": v.get("name"), "value": v.get("value"),
                          "unit": v.get("unit"), "kind": v.get("kind"), "provenance": v.get("provenance"),
                          "as_of": v.get("as_of"), "history": hist})
    actors = []
    for a in (world.get("actors") or [])[:64]:
        if not isinstance(a, dict):
            continue
        commitments = [c for c in (a.get("commitments") or []) if isinstance(c, dict)]
        actors.append({"agent_id": a.get("agent_id"), "name": a.get("name"),
                       "agency_class": a.get("agency_class"), "archetype": a.get("archetype"),
                       "capacity_per_round": a.get("capacity_per_round"),
                       "reputation": a.get("reputation"), "last_action": a.get("last_action"),
                       "track_record": a.get("track_record") if isinstance(a.get("track_record"), dict) else None,
                       "pending_commitments": [c for c in commitments if c.get("status") in ("pending", "due")][:6]})
    relationships = []
    for r in (world.get("relationships") or [])[:200]:
        if isinstance(r, dict):
            relationships.append({k: r.get(k) for k in ("source", "target", "kind", "valence", "polarity",
                                                          "strength", "last_changed_round")})
    events = [e for e in (world.get("events") or []) if isinstance(e, dict)][-WORLD_STATE_MAX_EVENTS:]
    data = {
        "simulation_id": str(simulation_id),
        "committed_round": payload.get("committed_round"),
        "headline": str(payload.get("headline") or "")[:2000],
        "brief": str(payload.get("brief") or "")[:4000],
        "digest": str(payload.get("digest") or "")[:WORLD_STATE_MAX_DIGEST],
        "summary": payload.get("summary") if isinstance(payload.get("summary"), dict) else {},
        "question": world.get("question"),
        "as_of_date": world.get("as_of_date"),
        "horizon_date": world.get("horizon_date"),
        "period": world.get("period"),
        "variables": variables,
        "actors": actors,
        "relationships": relationships,
        "pending_effects": [fx for fx in (world.get("pending_effects") or []) if isinstance(fx, dict)][:20],
        "recent_events": events,
        "history": history,
        # OFFERS: open offers first, then the latest settled ones (names resolved, bounded)
        "interactions": _world_interactions(world),
        # MODELLING GAPS the seed reported (what the research could not ground)
        "seed_gaps": [{"kind": str(g.get("kind") or "")[:40], "subject": str(g.get("subject") or "")[:120],
                       "note": str(g.get("note") or "")[:160]}
                      for g in (world.get("seed_gaps") or []) if isinstance(g, dict)][:32],
    }
    return data


@simulation_bp.route('/<simulation_id>/world-state', methods=['GET'])
def get_simulation_world_state(simulation_id: str):
    """REFLEXIVE WORLD: the latest committed world (facts, actors, relationships, events)
    plus a bounded per-round history for the live World State panel.

    404 while the world has not committed a round yet (early rounds, hours mode, legacy
    runs); path containment + symlink refusal + size bounds as for the trajectory route.
    ``?rows=N`` bounds the history (default 24, max 200).  Each history row carries the
    round's bounded ``arbiter_problems`` (and ``error`` when the update itself failed) plus
    the agent-facing ``digest`` of that round, joined from ``world_digest.jsonl`` under the
    same containment rules, so the panel can show any committed period, not only the latest.
    """
    try:
        data = _read_simulation_world_state(simulation_id, request.args.get("rows", 24))
        return jsonify({"success": True, "data": data})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except _WorldStateReadError as exc:
        return jsonify({"success": False, "error": str(exc)}), exc.status
    except Exception as e:
        logger.error(f"读取世界状态失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


def _record_publication(sim_dir: str):
    """(published, publication_status) of a simulation's after-action record.

    Served only when ``simulation_record_contract.is_published`` holds (an audit exists,
    passed, and carries no hard issue); the status names why it is withheld otherwise.
    """
    from ..services import simulation_record_contract as _rc
    record, status = _rc.load_published_record(sim_dir)
    return record is not None, status


def _record_route_preamble(simulation_id: str):
    """Shared containment for the record routes: ``(sim_dir, record, error_response)``.

    Same posture as the world-state route — realpath containment under
    OASIS_SIMULATION_DATA_DIR, the record file a regular file only (symlinks refused),
    the size cap — then the publication gate: 404 while no record exists, 409 while
    the record is unaudited or failed its gate (ADR 0003: an unaudited or failed record is
    never served).
    """
    from ..services import simulation_record_contract as _rc
    sim_dir = _contained_sim_dir(simulation_id)
    if sim_dir is None:
        return None, None, (jsonify({"success": False, "error": f"模拟不存在: {simulation_id}"}), 404)
    paths = _rc.record_paths(sim_dir)
    if os.path.islink(paths["json"]) or not os.path.isfile(paths["json"]):
        return None, None, (jsonify({"success": False, "error": "模拟事后记录尚未生成"}), 404)
    if os.path.getsize(paths["json"]) > WORLD_STATE_MAX_BYTES:
        return None, None, (jsonify({"success": False, "error": "模拟事后记录文件超出大小上限"}), 413)
    record, status = _rc.load_published_record(sim_dir)
    if record is None:
        return None, None, (jsonify({
            "success": False,
            "error": "模拟事后记录未通过审计门，不予提供（见 simulation_record_audit.json）",
            "publication_status": status,
        }), 409)
    return sim_dir, record, None


@simulation_bp.route('/<simulation_id>/record', methods=['GET'])
def get_simulation_record(simulation_id: str):
    """SIMULATION AFTER-ACTION RECORD (ADR 0003, design §3.6): the gate-passed
    ``simulation_record.json`` (schema simulation-record/v1) as JSON.

    404 when no record exists; 409 with ``publication_status`` (``not_audited`` /
    ``failed`` / ``stale_audit`` when the file no longer matches the audited bytes) when
    the deterministic gate has not passed it; containment, symlink
    refusal and size bounds as for ``/world-state``.
    """
    try:
        sim_dir, record, error = _record_route_preamble(simulation_id)
        if error is not None:
            return error
        return jsonify({"success": True, "data": record})
    except Exception as e:
        logger.error(f"读取模拟事后记录失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@simulation_bp.route('/<simulation_id>/record.md', methods=['GET'])
def get_simulation_record_markdown(simulation_id: str):
    """The record's deterministic Markdown rendering as ``text/markdown``.

    Render ``zh`` or ``en`` from the same verified JSON snapshot used by ``/record``.
    Both stored renderings must still match their audit seals. No translation call
    or unchecked cache read is made. Same 404 / 409 containment behaviour as ``/record``.
    """
    try:
        sim_dir, record, error = _record_route_preamble(simulation_id)
        if error is not None:
            return error
        want_zh = str(request.args.get("lang", "") or "").strip().lower().startswith("zh")
        from ..services.simulation_record import render_markdown
        text = render_markdown(record, "zh" if want_zh else "en")
        response = Response(text, mimetype="text/markdown; charset=utf-8")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Disposition"] = (
            f'inline; filename="simulation_record{".zh" if want_zh else ""}.md"')
        return response
    except Exception as e:
        logger.error(f"读取模拟事后记录渲染失败: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500


@simulation_bp.route('/<simulation_id>/agent-stats', methods=['GET'])
def get_agent_stats(simulation_id: str):
    """
    获取每个Agent的统计信息
    
    用于前端展示Agent活跃度排行、动作分布等
    """
    try:
        stats = SimulationRunner.get_agent_stats(simulation_id)
        
        return jsonify({
            "success": True,
            "data": {
                "agents_count": len(stats),
                "stats": stats
            }
        })
        
    except Exception as e:
        logger.error(f"获取Agent统计失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 数据库查询接口 ==============

@simulation_bp.route('/<simulation_id>/posts', methods=['GET'])
def get_simulation_posts(simulation_id: str):
    """
    获取模拟中的帖子
    
    Query参数：
        platform: 平台类型（twitter/reddit）
        limit: 返回数量（默认50）
        offset: 偏移量
    
    返回帖子列表（从SQLite数据库读取）
    """
    try:
        platform = request.args.get('platform', 'reddit')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        # PERIOD VIEW: ``round=N`` → only the posts of that round (plus the parents of its
        # replies), each row carrying its ``round``; without it the legacy path below is unchanged.
        round_arg = request.args.get('round')
        if round_arg not in (None, ''):
            return _feed_rows_for_round(simulation_id, platform, round_arg, 'posts', limit, offset)
        
        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )
        
        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)
        
        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "posts": [],
                    "message": "数据库不存在，模拟可能尚未运行"
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            cursor.execute("""
                SELECT * FROM post 
                ORDER BY created_at DESC 
                LIMIT ? OFFSET ?
            """, (limit, offset))
            
            posts = [dict(row) for row in cursor.fetchall()]
            
            cursor.execute("SELECT COUNT(*) FROM post")
            total = cursor.fetchone()[0]
            
        except sqlite3.OperationalError:
            posts = []
            total = 0
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "total": total,
                "count": len(posts),
                "posts": posts
            }
        })
        
    except Exception as e:
        logger.error(f"获取帖子失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/comments', methods=['GET'])
def get_simulation_comments(simulation_id: str):
    """
    获取模拟中的评论

    Query参数：
        platform: 平台类型（twitter/reddit，默认 reddit——与 /posts 端点保持一致）
        post_id: 过滤帖子ID（可选）
        limit: 返回数量
        offset: 偏移量
    """
    try:
        platform = request.args.get('platform', 'reddit')
        post_id = request.args.get('post_id')
        limit = request.args.get('limit', 50, type=int)
        offset = request.args.get('offset', 0, type=int)
        # PERIOD VIEW: ``round=N`` → only the replies written in that round (legacy path unchanged).
        round_arg = request.args.get('round')
        if round_arg not in (None, ''):
            return _feed_rows_for_round(simulation_id, platform, round_arg, 'comments', limit, offset)

        sim_dir = os.path.join(
            os.path.dirname(__file__),
            f'../../uploads/simulations/{simulation_id}'
        )

        # 此前硬编码只读 reddit_simulation.db（"仅Reddit"）——Twitter 平台其实同样有
        # comment 表且写满了真实评论（CREATE_COMMENT 动作两平台都会产生），只是这个
        # 端点从未读过，导致前端 Feed 只能看到帖子、看不到任何回复。与 /posts 端点
        # 保持一致，按 platform 选库。
        db_file = f"{platform}_simulation.db"
        db_path = os.path.join(sim_dir, db_file)

        if not os.path.exists(db_path):
            return jsonify({
                "success": True,
                "data": {
                    "platform": platform,
                    "count": 0,
                    "comments": []
                }
            })
        
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        try:
            if post_id:
                cursor.execute("""
                    SELECT * FROM comment 
                    WHERE post_id = ?
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (post_id, limit, offset))
            else:
                cursor.execute("""
                    SELECT * FROM comment 
                    ORDER BY created_at DESC 
                    LIMIT ? OFFSET ?
                """, (limit, offset))
            
            comments = [dict(row) for row in cursor.fetchall()]
            
        except sqlite3.OperationalError:
            comments = []
        
        conn.close()
        
        return jsonify({
            "success": True,
            "data": {
                "platform": platform,
                "count": len(comments),
                "comments": comments
            }
        })

    except Exception as e:
        logger.error(f"获取评论失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== Interview 采访接口 ==============

@simulation_bp.route('/interview', methods=['POST'])
def interview_agent():
    """
    采访单个Agent

    注意：此功能需要模拟环境处于运行状态（完成模拟循环后进入等待命令模式）

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",       // 必填，模拟ID
            "agent_id": 0,                     // 必填，Agent ID
            "prompt": "你对这件事有什么看法？",  // 必填，采访问题
            "platform": "twitter",             // 可选，指定平台（twitter/reddit）
                                               // 不指定时：双平台模拟同时采访两个平台
            "timeout": 60                      // 可选，超时时间（秒），默认60
        }

    返回（不指定platform，双平台模式）：
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "你对这件事有什么看法？",
                "result": {
                    "agent_id": 0,
                    "prompt": "...",
                    "platforms": {
                        "twitter": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit": {"agent_id": 0, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }

    返回（指定platform）：
        {
            "success": true,
            "data": {
                "agent_id": 0,
                "prompt": "你对这件事有什么看法？",
                "result": {
                    "agent_id": 0,
                    "response": "我认为...",
                    "platform": "twitter",
                    "timestamp": "2025-12-08T10:00:00"
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        agent_id = data.get('agent_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 60)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400
        
        if agent_id is None:
            return jsonify({
                "success": False,
                "error": "请提供 agent_id"
            }), 400
        
        if not prompt:
            return jsonify({
                "success": False,
                "error": "请提供 prompt（采访问题）"
            }), 400
        
        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform 参数只能是 'twitter' 或 'reddit'"
            }), 400
        
        # 检查环境状态
        SimulationRunner.require_interview_capability(simulation_id)
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "模拟环境未运行或已关闭。请确保模拟已完成并进入等待命令模式。"
            }), 400
        
        # 优化prompt，添加前缀避免Agent调用工具
        optimized_prompt = optimize_interview_prompt(prompt)
        
        result = SimulationRunner.interview_agent(
            simulation_id=simulation_id,
            agent_id=agent_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"等待Interview响应超时: {str(e)}"
        }), 504
        
    except Exception as e:
        logger.error(f"Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/batch', methods=['POST'])
def interview_agents_batch():
    """
    批量采访多个Agent

    注意：此功能需要模拟环境处于运行状态

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",       // 必填，模拟ID
            "interviews": [                    // 必填，采访列表
                {
                    "agent_id": 0,
                    "prompt": "你对A有什么看法？",
                    "platform": "twitter"      // 可选，指定该Agent的采访平台
                },
                {
                    "agent_id": 1,
                    "prompt": "你对B有什么看法？"  // 不指定platform则使用默认值
                }
            ],
            "platform": "reddit",              // 可选，默认平台（被每项的platform覆盖）
                                               // 不指定时：双平台模拟每个Agent同时采访两个平台
            "timeout": 120                     // 可选，超时时间（秒），默认120
        }

    返回：
        {
            "success": true,
            "data": {
                "interviews_count": 2,
                "result": {
                    "interviews_count": 4,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        "twitter_1": {"agent_id": 1, "response": "...", "platform": "twitter"},
                        "reddit_1": {"agent_id": 1, "response": "...", "platform": "reddit"}
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        interviews = data.get('interviews')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 120)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400

        if not interviews or not isinstance(interviews, list):
            return jsonify({
                "success": False,
                "error": "请提供 interviews（采访列表）"
            }), 400

        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform 参数只能是 'twitter' 或 'reddit'"
            }), 400

        # 验证每个采访项
        for i, interview in enumerate(interviews):
            if 'agent_id' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"采访列表第{i+1}项缺少 agent_id"
                }), 400
            if 'prompt' not in interview:
                return jsonify({
                    "success": False,
                    "error": f"采访列表第{i+1}项缺少 prompt"
                }), 400
            # 验证每项的platform（如果有）
            item_platform = interview.get('platform')
            if item_platform and item_platform not in ("twitter", "reddit"):
                return jsonify({
                    "success": False,
                    "error": f"采访列表第{i+1}项的platform只能是 'twitter' 或 'reddit'"
                }), 400

        # 检查环境状态
        SimulationRunner.require_interview_capability(simulation_id)
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "模拟环境未运行或已关闭。请确保模拟已完成并进入等待命令模式。"
            }), 400

        # 优化每个采访项的prompt，添加前缀避免Agent调用工具
        optimized_interviews = []
        for interview in interviews:
            optimized_interview = interview.copy()
            optimized_interview['prompt'] = optimize_interview_prompt(interview.get('prompt', ''))
            optimized_interviews.append(optimized_interview)

        result = SimulationRunner.interview_agents_batch(
            simulation_id=simulation_id,
            interviews=optimized_interviews,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"等待批量Interview响应超时: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"批量Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/all', methods=['POST'])
def interview_all_agents():
    """
    全局采访 - 使用相同问题采访所有Agent

    注意：此功能需要模拟环境处于运行状态

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",            // 必填，模拟ID
            "prompt": "你对这件事整体有什么看法？",  // 必填，采访问题（所有Agent使用相同问题）
            "platform": "reddit",                   // 可选，指定平台（twitter/reddit）
                                                    // 不指定时：双平台模拟每个Agent同时采访两个平台
            "timeout": 180                          // 可选，超时时间（秒），默认180
        }

    返回：
        {
            "success": true,
            "data": {
                "interviews_count": 50,
                "result": {
                    "interviews_count": 100,
                    "results": {
                        "twitter_0": {"agent_id": 0, "response": "...", "platform": "twitter"},
                        "reddit_0": {"agent_id": 0, "response": "...", "platform": "reddit"},
                        ...
                    }
                },
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}

        simulation_id = data.get('simulation_id')
        prompt = data.get('prompt')
        platform = data.get('platform')  # 可选：twitter/reddit/None
        timeout = data.get('timeout', 180)

        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400

        if not prompt:
            return jsonify({
                "success": False,
                "error": "请提供 prompt（采访问题）"
            }), 400

        # 验证platform参数
        if platform and platform not in ("twitter", "reddit"):
            return jsonify({
                "success": False,
                "error": "platform 参数只能是 'twitter' 或 'reddit'"
            }), 400

        # 检查环境状态
        SimulationRunner.require_interview_capability(simulation_id)
        if not SimulationRunner.check_env_alive(simulation_id):
            return jsonify({
                "success": False,
                "error": "模拟环境未运行或已关闭。请确保模拟已完成并进入等待命令模式。"
            }), 400

        # 优化prompt，添加前缀避免Agent调用工具
        optimized_prompt = optimize_interview_prompt(prompt)

        result = SimulationRunner.interview_all_agents(
            simulation_id=simulation_id,
            prompt=optimized_prompt,
            platform=platform,
            timeout=timeout
        )

        return jsonify({
            "success": result.get("success", False),
            "data": result
        })

    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400

    except TimeoutError as e:
        return jsonify({
            "success": False,
            "error": f"等待全局Interview响应超时: {str(e)}"
        }), 504

    except Exception as e:
        logger.error(f"全局Interview失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/interview/history', methods=['POST'])
def get_interview_history():
    """
    获取Interview历史记录

    从模拟数据库中读取所有Interview记录

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",  // 必填，模拟ID
            "platform": "reddit",          // 可选，平台类型（reddit/twitter）
                                           // 不指定则返回两个平台的所有历史
            "agent_id": 0,                 // 可选，只获取该Agent的采访历史
            "limit": 100                   // 可选，返回数量，默认100
        }

    返回：
        {
            "success": true,
            "data": {
                "count": 10,
                "history": [
                    {
                        "agent_id": 0,
                        "response": "我认为...",
                        "prompt": "你对这件事有什么看法？",
                        "timestamp": "2025-12-08T10:00:00",
                        "platform": "reddit"
                    },
                    ...
                ]
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        platform = data.get('platform')  # 不指定则返回两个平台的历史
        agent_id = data.get('agent_id')
        limit = data.get('limit', 100)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400

        history = SimulationRunner.get_interview_history(
            simulation_id=simulation_id,
            platform=platform,
            agent_id=agent_id,
            limit=limit
        )

        return jsonify({
            "success": True,
            "data": {
                "count": len(history),
                "history": history
            }
        })

    except Exception as e:
        logger.error(f"获取Interview历史失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/env-status', methods=['POST'])
def get_env_status():
    """
    获取模拟环境状态

    检查模拟环境是否存活（可以接收Interview命令）

    请求（JSON）：
        {
            "simulation_id": "sim_xxxx"  // 必填，模拟ID
        }

    返回：
        {
            "success": true,
            "data": {
                "simulation_id": "sim_xxxx",
                "env_alive": true,
                "twitter_available": true,
                "reddit_available": true,
                "message": "环境正在运行，可以接收Interview命令"
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

        env_alive = SimulationRunner.check_env_alive(simulation_id)
        
        # 获取更详细的状态信息
        env_status = SimulationRunner.get_env_status_detail(simulation_id)

        if env_alive:
            message = "环境正在运行，可以接收Interview命令"
        else:
            message = "环境未运行或已关闭"

        return jsonify({
            "success": True,
            "data": {
                "simulation_id": simulation_id,
                "env_alive": env_alive,
                "twitter_available": env_status.get("twitter_available", False),
                "reddit_available": env_status.get("reddit_available", False),
                "message": message
            }
        })

    except Exception as e:
        logger.error(f"获取环境状态失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/close-env', methods=['POST'])
def close_simulation_env():
    """
    关闭模拟环境
    
    向模拟发送关闭环境命令，使其优雅退出等待命令模式。
    
    注意：这不同于 /stop 接口，/stop 会强制终止进程，
    而此接口会让模拟优雅地关闭环境并退出。
    
    请求（JSON）：
        {
            "simulation_id": "sim_xxxx",  // 必填，模拟ID
            "timeout": 30                  // 可选，超时时间（秒），默认30
        }
    
    返回：
        {
            "success": true,
            "data": {
                "message": "环境关闭命令已发送",
                "result": {...},
                "timestamp": "2025-12-08T10:00:01"
            }
        }
    """
    try:
        data = request.get_json() or {}
        
        simulation_id = data.get('simulation_id')
        timeout = data.get('timeout', 30)
        
        if not simulation_id:
            return jsonify({
                "success": False,
                "error": "请提供 simulation_id"
            }), 400
        
        result = SimulationRunner.close_simulation_env(
            simulation_id=simulation_id,
            timeout=timeout
        )
        
        # 更新模拟状态
        manager = SimulationManager()
        state = manager.get_simulation(simulation_id)
        if state:
            state.status = SimulationStatus.COMPLETED
            manager._save_simulation_state(state)
        
        return jsonify({
            "success": result.get("success", False),
            "data": result
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 400
        
    except Exception as e:
        logger.error(f"关闭环境失败: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@simulation_bp.route('/<simulation_id>/world', methods=['GET'])
def get_world_result(simulation_id: str):
    """Read a single committed revision; cursor conflicts require caller refresh."""
    from ..services.world_simulation.contracts import WorldError
    from ..services.world_simulation.results import read_result
    from ..services.world_simulation.service import WorldSimulationService
    try:
        manager = SimulationManager()
        # Read only the admission record here; the result reader below owns
        # the sole committed revision snapshot for this response.
        state = manager._load_simulation_state(simulation_id)
        if state is None:
            return jsonify({"success": False, "error": "Simulation not found"}), 404
        if state.simulation_engine != 'world-v1':
            return jsonify({"success": False, "error": "World view requires world-v1"}), 409
        manager.validate_prepared_simulation_config(simulation_id)
        round_arg = request.args.get('round')
        result = read_result(
            WorldSimulationService.directory(simulation_id, root=manager.SIMULATION_DATA_DIR),
            view=request.args.get('view', 'public'), actor_id=request.args.get('actor_id'),
            round_index=int(round_arg) if round_arg is not None else None,
            revision=request.args.get('revision'))
        return jsonify({"success": True, "data": result})
    except WorldError as exc:
        conflict = exc.code in {'stale_revision', 'input_binding_mismatch', 'missing_artifact',
                                'result_binding_mismatch', 'world_incomplete'}
        return jsonify({"success": False, "error": str(exc), "code": exc.code}), 409 if conflict else 400
    except (ValueError, TypeError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400


def _translation_source_path(sim_dir: str, name: str):
    """Only explicitly named regular sources inside this simulation may be read."""
    path = os.path.join(sim_dir, name)
    if os.path.realpath(path) != path or os.path.islink(path):
        raise ValueError("indirect simulation translation source")
    if not os.path.exists(path):
        return None
    if not os.path.isfile(path):
        raise ValueError("invalid simulation translation source")
    return path


def _translation_source_json(sim_dir: str, name: str):
    import json

    path = _translation_source_path(sim_dir, name)
    if path is None:
        return None
    if os.path.getsize(path) > WORLD_STATE_MAX_BYTES:
        raise ValueError("simulation translation source exceeds read bound")
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _simulation_display_value(value, unit="") -> str:
    """Mirror WorldState's formatWorldValue for safe, source-derived UI snippets.

    This is an additional display string; the original typed value and unit
    always remain in the projection and its source fingerprint.
    """
    from decimal import Decimal, ROUND_HALF_UP, localcontext
    from math import isfinite

    def fixed(number, places):
        # JavaScript toFixed uses exponential number spelling at this bound.
        if abs(number) >= 1e21:
            return str(float(number)).replace(".0e", "e")
        with localcontext() as decimal_context:
            decimal_context.prec = 40
            return format(Decimal.from_float(float(number)).quantize(
                Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")

    if isinstance(value, bool):
        text = "yes" if value else "no"
    elif isinstance(value, (int, float)):
        try:
            finite = isfinite(value)
        except OverflowError:
            finite = False
        if not finite:
            raise ValueError("world display value must be finite")
        magnitude = abs(value)
        if magnitude >= 1e12:
            text = fixed(value / 1e12, 2) + " trillion"
        elif magnitude >= 1e9:
            text = fixed(value / 1e9, 2) + " billion"
        elif magnitude >= 1e6:
            text = fixed(value / 1e6, 2) + " million"
        elif magnitude >= 1e4:
            text = format(int(fixed(value, 0)), ",")
        elif float(value).is_integer():
            text = str(int(value))
        else:
            text = fixed(value, 2).rstrip("0").rstrip(".")
            if text == "-0":
                text = "0"
    elif value is None:
        text = "—"
    else:
        text = str(value).strip()[:120]
    unit = str(unit or "").strip()
    if not unit or unit.lower() in {
        "numeric", "categorical", "boolean", "text", "number", "num", "int", "integer", "float",
        "decimal", "bool", "flag", "string", "str", "category", "enum", "date", "datetime", "timestamp",
    }:
        return text
    if unit == "%":
        return text + unit
    if re.search(r"[$€£¥￥]", unit) or unit.lower() in {
        "usd", "eur", "gbp", "cny", "rmb", "jpy", "hkd", "aud", "cad", "美元", "人民币", "元",
    }:
        return unit + text
    return text + " " + unit


def _simulation_world_display(world: dict) -> list:
    """Derived strings used by worldState.js, from the public reader only."""
    snippets = []
    for headline in [world.get("headline"), *(row.get("headline") for row in world["history"])]:
        parts = str(headline or "").split(" · ")
        stop = next((i + 1 for i, part in enumerate(parts) if part.strip().startswith("arbiter=")), len(parts))
        snippets.append(" · ".join(parts[:stop]).strip())
    for variable in world["variables"]:
        snippets.append(_simulation_display_value(variable.get("value"), variable.get("unit")))
        history = variable.get("history") or []
        if len(history) >= 2:
            snippets.append(" → ".join(_simulation_display_value(row.get("value"), variable.get("unit"))
                                       for row in history[-2:]))
        # A scalar provenance is explanatory prose; structured provenance stays
        # in the original projection with its IDs and hashes unchanged.
        if isinstance(variable.get("provenance"), str):
            snippets.append(variable["provenance"])
    for row in world["history"]:
        snippets.append(str(row.get("period_label") or f"#{row.get('round')}"))
        diff = row.get("diff") or {}
        for change in diff.get("variables_changed") or []:
            if isinstance(change, dict):
                snippets.append(" → ".join(_simulation_display_value(change.get(key), change.get("unit"))
                                           for key in ("from", "to")))
        for added in diff.get("variables_added") or []:
            if isinstance(added, dict):
                snippets.append(_simulation_display_value(added.get("value"), added.get("unit")))
        for crossing in row.get("red_lines_crossed") or []:
            if all(crossing.get(key) for key in ("by", "actor", "red_line")):
                snippets.append(f"{crossing['by']} crossed {crossing['actor']}'s red line: {crossing['red_line']}")
    return [{"text": text} for text in dict.fromkeys(snippets) if text]


def _simulation_record_display(record: dict, selected_round) -> list:
    """Exact simulationRecordTranslationTexts inventory; no setup or other periods.

    Keep this explicit adapter aligned with simulationRecordTranslation.js and
    simRecord.js. A raw audited record is still too broad for text admission.
    """
    def text(value):
        return "" if value is None else str(value).strip()

    def objects(value):
        return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []

    def items(value):
        return value if isinstance(value, list) else []

    def object_value(value):
        return value if isinstance(value, dict) else {}

    def event_text(value):
        return text(value.get("description") or value.get("text") or value.get("name") or value.get("kind")) \
            if isinstance(value, dict) else text(value)

    def finish(values):
        return [{"text": value} for value in dict.fromkeys(values) if isinstance(value, str) and value]

    health = record.get("health") or {}
    limits = object_value(record.get("limits"))
    health_name, validity = text(health.get("simulation_health")) or "unknown", text(health.get("validity")) or "unknown"
    snippets = [record.get("banner"), record.get("calendar_unit"), health_name, validity,
                *(event_text(note) for note in items(limits.get("notes")))]
    if (limits.get("stub") is True or health_name in {"hollow", "errored", "truncated"}
            or validity != "valid" or record.get("rounds_committed") == 0):
        return finish(snippets)
    for period in objects(record.get("periods")):
        snippets.extend((text(period.get("label")) or f"#{period.get('round')}",
                         text(period.get("arbiter_status")) or "none"))
        if period.get("round") != selected_round:
            continue
        snippets.extend((text(period.get("narrative")), *(text(value) for value in items(period.get("arbiter_problems"))),
                         *(event_text(value) for key in ("events", "shocks_fired") for value in items(period.get(key)))))
        for crossing in items(period.get("red_lines_crossed")):
            if isinstance(crossing, dict) and crossing.get("red_line"):
                snippets.append(": ".join(filter(None, (text(crossing.get("actor")), text(crossing["red_line"])))))
            else:
                snippets.append(event_text(crossing))
        for shift in items(period.get("alliances")):
            if isinstance(shift, dict) and shift.get("kind") == "alliance_move":
                snippets.append(f"{text(shift.get('actor'))}: {text(shift.get('move'))} → {text(shift.get('target'))}")
            elif isinstance(shift, dict) and shift.get("kind") == "relationship":
                snippets.append(f"{text(shift.get('source'))} → {text(shift.get('target'))}: "
                                f"{text(shift.get('from'))} → {text(shift.get('to'))}")
            else:
                snippets.append(event_text(shift))
        for move in objects(period.get("moves")):
            option = move.get("option")
            if not isinstance(option, dict) or option.get("label"):
                snippets.append(text(option.get("label") if isinstance(option, dict) else option))
            commitment = move.get("commitment")
            snippets.extend((text(move.get("public_statement") or move.get("statement")), text(move.get("terms")),
                text(commitment.get("text") or commitment.get("description")) if isinstance(commitment, dict) else text(commitment)))
        for fact in objects(period.get("facts_changed")):
            if fact.get("variable") or fact.get("name"):
                snippets.append(text(fact.get("variable") or fact.get("name")))
            snippets.append(text(fact.get("cause")))
        for offer in objects(period.get("offers")):
            snippets.extend((text(offer.get("status")) or "unknown", text(offer.get("kind")), text(offer.get("terms"))))
    overall = object_value(record.get("overall"))
    for variable in objects(overall.get("final_variables")):
        if variable.get("name") or variable.get("variable"):
            snippets.append(text(variable.get("name") or variable.get("variable")))
    shares = object_value(overall.get("shares"))
    final, paths = shares.get("final"), object_value(shares.get("paths"))
    per_scenario = paths.get("per_scenario")
    # These map keys are the scenario names displayed by shareRows, not IDs.
    for values in (final, per_scenario):
        if isinstance(values, dict):
            snippets.extend(values)
    snippets.extend(text(row.get("why") or row.get("reason")) for row in objects(overall.get("turning_points")))
    synthesis = object_value(overall.get("synthesis"))
    snippets.extend(part.strip() for part in re.split(r"\n{2,}", text(synthesis.get("text"))) if part.strip())
    generator = text(synthesis.get("generator")) or "deterministic"
    if generator not in {"llm", "deterministic"}:
        snippets.append(generator)
    snippets.extend(event_text(gap) for gap in items(limits.get("seed_gaps")))
    snippets.append(text(limits.get("behaviour_note")))
    return finish(snippets)


def _simulation_feed_rows(db_path: str):
    """The public post/comment rows, including unchanged typed UI facts, read-only."""
    import sqlite3
    from pathlib import Path

    if not db_path:
        return [], []
    connection = sqlite3.connect(Path(db_path).as_uri() + "?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        rows = []
        for table in ("post", "comment"):
            try:
                rows.append([dict(row) for row in connection.execute(f"SELECT * FROM {table} ORDER BY {table}_id")])
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc):
                    raise ValueError("simulation feed source unavailable") from None
                rows.append([])
        return tuple(rows)
    finally:
        connection.close()


def simulation_translation_projection(sim_id: str, context) -> dict:
    """Return permitted source facts plus safe UI snippets, without any writes.

    ``context`` selects engine/platform/round/revision/generation_id/view/actor_id
    and optional ``surface``. An explicit record surface OR view (including
    simulation-record/after-action-record aliases) uses the audited record's
    rendered inventory, with an opaque seal of the entire canonical record.
    Native world views use read_result's visibility and committed-round checks.
    Legacy public projections use the same world-state projection and feed-round
    readers as the UI, plus the JSON/CSV profile format served by /profiles.

    Callers seal the ENTIRE returned JSON object, including numbers and identities,
    and check submitted texts against its string leaves. This function does not
    accept client text as source authority. Invalid scopes/source bindings raise
    ValueError; unavailable sources raise FileNotFoundError. No Flask context,
    SimulationManager construction, model client, generation or repair is needed.
    """
    import csv
    import hashlib
    import json
    from pathlib import Path

    if not isinstance(sim_id, str):
        raise ValueError("invalid simulation translation id")
    if context is None:
        context = {}
    if not isinstance(context, dict) or set(context) - {
        "engine", "platform", "round", "generation_id", "revision", "view", "actor_id", "surface",
    }:
        raise ValueError("invalid simulation translation context")
    for key, value in context.items():
        if value is not None and (isinstance(value, bool) or not isinstance(value, (str, int))
                                  or len(str(value)) > 256):
            raise ValueError("invalid simulation translation context field")
        if key != "round" and value is not None and not isinstance(value, str):
            raise ValueError("simulation translation context field must be text")
    round_index = context.get("round")
    if round_index in (None, ""):
        round_index = None
    elif isinstance(round_index, str) and re.fullmatch(r"[0-9]+", round_index):
        round_index = int(round_index)
    if round_index is not None and (type(round_index) is not int or round_index < 0):
        raise ValueError("invalid simulation translation round")
    sim_dir = _contained_sim_dir(sim_id)
    if sim_dir is None:
        raise ValueError("invalid simulation translation id")
    if os.path.islink(os.path.join(os.path.realpath(Config.OASIS_SIMULATION_DATA_DIR), sim_id)):
        raise ValueError("indirect simulation translation directory")
    if not os.path.isdir(sim_dir):
        raise FileNotFoundError("simulation translation source unavailable")
    state = _translation_source_json(sim_dir, "state.json")
    if state is not None and not isinstance(state, dict):
        raise ValueError("invalid saved simulation state")
    state = state or {}
    if state.get("simulation_id", sim_id) != sim_id:
        raise ValueError("simulation translation source identity mismatch")
    record_aliases = {"record", "simulation-record", "after-action-record"}
    surface, view = context.get("surface") or "", context.get("view") or "public"
    is_record = surface in record_aliases or view in record_aliases
    engine = state.get("simulation_engine", "oasis-legacy")
    if (not isinstance(engine, str) or engine not in {"oasis-legacy", "world-v1"}
            or (not is_record and context.get("engine") not in (None, "", engine))):
        raise ValueError("simulation translation engine mismatch")
    if not is_record and engine != "world-v1" and (os.path.lexists(os.path.join(sim_dir, "world_input_manifest.json"))
            or any(state.get(key) for key in ("world_generation_id", "world_spec_sha256", "world_input_manifest_sha256"))):
        raise ValueError("world artifacts require the saved world-v1 engine pin")
    actor_id = context.get("actor_id") or None
    platform = context.get("platform") or ""
    generation = context.get("generation_id") or None
    revision = context.get("revision") or None
    if is_record:
        if (surface not in {"", *record_aliases} or view not in {"public", *record_aliases}
                or actor_id or platform):
            raise ValueError("record translation requires an explicit public record scope")
        from ..services.simulation_record_contract import load_published_record, record_sha256
        record, status = load_published_record(sim_dir)
        if record is None:
            raise FileNotFoundError(f"published simulation record unavailable: {status}")
        if record.get("simulation_id") != sim_id:
            raise ValueError("simulation record identity mismatch")
        record_engine = "world-v1" if record.get("engine") == "world-v1" else "oasis-legacy"
        if (context.get("engine") not in (None, "", record_engine, record.get("engine"))
                or ("simulation_engine" in state and record_engine != engine)):
            raise ValueError("simulation record engine mismatch")
        engine = record_engine
        if generation and generation != state.get("world_generation_id"):
            raise ValueError("simulation record generation mismatch")
        record_revision = json.dumps([record.get(key) or "" for key in
            ("config_hash", "generator_version", "generated_at")], ensure_ascii=False, separators=(",", ":"))
        if revision and revision != record_revision:
            raise ValueError("simulation record revision changed")
        if round_index is not None and round_index not in {row.get("round") for row in record.get("periods", [])}:
            raise ValueError("simulation record round unavailable")
        metadata = {key: record.get(key) for key in (
            "schema", "record_class", "epistemic_status", "simulation_id", "pipeline_id", "config_hash",
            "engine", "language", "as_of", "horizon_date", "rounds_planned", "rounds_committed",
            "generator_version", "generated_at")}
        projection = {"simulation_id": sim_id, "engine": engine, "surface": "record", "record": metadata,
                      "record_sha256": record_sha256(record), "selected_round": round_index,
                      "display": _simulation_record_display(record, round_index)}
    elif engine == "world-v1":
        if surface not in {"", "live", "world"} or platform:
            raise ValueError("invalid native world translation surface")
        if view not in {"public", "actor", "analyst"} or (actor_id is not None and view != "actor"):
            raise ValueError("invalid native world translation view")
        from ..services.world_simulation.artifacts import load_inputs
        from ..services.world_simulation.contracts import WorldError
        from ..services.world_simulation.results import read_result
        try:
            for name in ("world_spec.json", "world_input_manifest.json", "world.sqlite3"):
                if _translation_source_path(sim_dir, name) is None:
                    raise FileNotFoundError("committed world source unavailable")
            if not all(state.get(key) for key in (
                    "world_generation_id", "world_spec_sha256", "world_input_manifest_sha256")):
                raise ValueError("prepared world state is missing generation bindings")
            spec, manifest = load_inputs(Path(sim_dir), simulation_id=sim_id,
                expected_manifest_sha256=state["world_input_manifest_sha256"])
            if (spec["generationId"] != state["world_generation_id"]
                    or manifest["specSha256"] != state["world_spec_sha256"]):
                raise ValueError("prepared world state bindings changed")
            result = read_result(Path(sim_dir), view=view, actor_id=actor_id,
                                 round_index=round_index, revision=revision)
        except WorldError as exc:
            if exc.code in {"missing_artifact", "missing_world", "world_incomplete"}:
                raise FileNotFoundError(str(exc)) from None
            raise ValueError(str(exc)) from None
        if (result.get("simulationId") != sim_id or result.get("generationId") != state["world_generation_id"]
                or (generation and result.get("generationId") != generation)):
            raise ValueError("world translation source identity mismatch")
        projection = {"simulation_id": sim_id, "engine": engine, "surface": "world", "world": result}
    else:
        if view != "public" or actor_id or generation:
            raise ValueError("OASIS translation supports only its public projection")
        if surface not in {"", "live", "world-state", "feed", "profiles", "personas"}:
            raise ValueError("invalid OASIS translation surface")
        if platform and platform not in {"reddit", "twitter"}:
            raise ValueError("invalid OASIS translation platform")
        projection = {"simulation_id": sim_id, "engine": engine, "surface": surface or "live"}
        # The World State panel uses an explicit empty platform; absent context
        # is the legacy combined public inventory. Never include a record here.
        want_world = surface == "world-state" or (not platform and surface in {"", "live"})
        if want_world or revision:
            try:
                world = _read_simulation_world_state(sim_id, WORLD_STATE_MAX_HISTORY)
            except FileNotFoundError:
                if surface == "world-state" or revision or "platform" in context:
                    raise
            else:
                if revision and revision != str(world.get("committed_round")):
                    raise ValueError("OASIS world revision changed")
                if round_index is not None and round_index not in {
                        world.get("committed_round"), *(row.get("round") for row in world["history"])}:
                    raise ValueError("OASIS world round unavailable")
                projection["world_state"] = world
                projection["display"] = _simulation_world_display(world)
        platforms = [platform] if platform else ([] if "platform" in context or surface == "world-state"
                                                else ["reddit", "twitter"])
        if surface in {"feed", "profiles", "personas"} and not platforms:
            platforms = ["reddit"]
        from ..services.feed_rounds import cached_feed_round_index, ids_for_round, public_index
        for selected_platform in platforms:
            public = {}
            if surface not in {"feed", "world-state"}:
                filename = "twitter_profiles.csv" if selected_platform == "twitter" else "reddit_profiles.json"
                path = _translation_source_path(sim_dir, filename)
                if path:
                    if os.path.getsize(path) > WORLD_STATE_MAX_BYTES:
                        raise ValueError("simulation profiles exceed read bound")
                    with open(path, encoding="utf-8") as handle:
                        profiles = list(csv.DictReader(handle)) if selected_platform == "twitter" else json.load(handle)
                    if not isinstance(profiles, list) or any(not isinstance(row, dict) for row in profiles):
                        raise ValueError("invalid simulation profiles")
                    public["profiles_sha256"] = hashlib.sha256(json.dumps(profiles, ensure_ascii=False,
                        sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
                    public["profiles"] = []
                    for row in profiles:
                        visible = {key: row[key] for key in ("id", "agent_id", "user_id") if key in row}
                        if any(value is not None and not isinstance(value, (str, int, float, bool))
                               for value in visible.values()):
                            raise ValueError("invalid simulation profile identity")
                        for field, keys in (("name", ("name", "user_name", "username")),
                                ("type", ("type", "category")),
                                ("persona", ("persona", "bio", "description", "self_description"))):
                            value = next((row[key] for key in keys if row.get(key)), "")
                            if not isinstance(value, str):
                                raise ValueError("invalid simulation profile display text")
                            visible[field] = value.strip()
                        public["profiles"].append(visible)
            if surface not in {"profiles", "personas", "world-state"}:
                db_path = _translation_source_path(sim_dir, selected_platform + "_simulation.db")
                actions_path = _translation_source_path(sim_dir, selected_platform + "/actions.jsonl")
                if db_path or actions_path:
                    index = cached_feed_round_index(sim_dir, selected_platform)
                    posts, comments = _simulation_feed_rows(db_path)
                    if round_index is not None:
                        if round_index not in {row["round"] for row in index["rounds"]}:
                            raise ValueError("OASIS feed round unavailable")
                        post_ids, comment_ids = ids_for_round(index, round_index, comments)
                        post_ids, comment_ids = set(post_ids), set(comment_ids)
                        posts = [row for row in posts if row["post_id"] in post_ids]
                        comments = [row for row in comments if row["comment_id"] in comment_ids]
                    posts = [{**row, "round": index["post_round"].get(row["post_id"])} for row in posts]
                    comments = [{**row, "round": index["comment_round"].get(row["comment_id"])} for row in comments]
                    public.update(posts=posts, comments=comments, feed_rounds=public_index(index))
                    labels = {row["round"]: str(row.get("period_label") or f"#{row['round']}") for row in index["rounds"]}
                    display = public.setdefault("display", [])
                    display.extend({"text": label} for label in labels.values())
                    display.extend({"text": f"{prefix} {labels.get(row['round'], '#' + str(row['round']))}"}
                        for row in posts if round_index is not None and row["round"] is not None and row["round"] != round_index
                        for prefix in ("发表于", "posted in"))
            if public:
                projection[selected_platform] = public
        if not any(key in projection for key in ("world_state", "reddit", "twitter")):
            raise FileNotFoundError("simulation public translation source unavailable")
    # Reject non-JSON/floating NaN sources and detach the result from reader caches.
    return json.loads(json.dumps(projection, ensure_ascii=False, allow_nan=False))


# Display-only translation requests are bound to the exact visible text inventory.
@simulation_bp.route('/<sim_id>/translations/<lang>', methods=['POST'])
def generate_simulation_translation(sim_id: str, lang: str):
    lang = (lang or '').strip().lower()
    if lang not in ('zh', 'en'):
        return jsonify({"success": False, "error": "仅支持 zh/en"}), 400
    try:
        from ..services.artifact_translation import start_translation
        body = request.get_json(silent=True)
        if body is None:
            body = {}
        if not isinstance(body, dict):
            raise ValueError("translation body must be an object")
        force = (request.args.get('force') or '').lower() in {'1', 'true', 'yes'}
        result = start_translation("simulation", sim_id, lang, force=force,
            texts=body.get("texts"), context=body.get("context"))
        return jsonify({"success": True, "data": result}), (202 if result["status"] == "generating" else 200)
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("模拟翻译失败: %s", type(exc).__name__)
        return jsonify({"success": False, "error": "translation request failed"}), 500


@simulation_bp.route('/<sim_id>/translations/<lang>', methods=['GET'])
def get_simulation_translation(sim_id: str, lang: str):
    lang = (lang or '').strip().lower()
    if lang not in ('zh', 'en'):
        return jsonify({"success": False, "error": "仅支持 zh/en"}), 400
    try:
        import json
        from ..services.artifact_translation import translation_status
        context = json.loads(request.args['context']) if 'context' in request.args else None
        result = translation_status("simulation", sim_id, lang,
            request_digest=request.args.get("request_digest"), context=context)
        return jsonify({"success": True, "data": result})
    except FileNotFoundError as exc:
        return jsonify({"success": False, "error": str(exc)}), 404
    except (TypeError, ValueError) as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        logger.error("模拟翻译读取失败: %s", type(exc).__name__)
        return jsonify({"success": False, "error": "translation status unavailable"}), 500
