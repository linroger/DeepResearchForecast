"""
图谱相关API路由
采用项目上下文机制，服务端持久化状态
"""

import os
import json
import hashlib
import re
import stat
import traceback
import threading
from flask import request, jsonify
from werkzeug.exceptions import BadRequest, Conflict, NotFound

from . import graph_bp
from ..config import Config
from ..services.ontology_generator import OntologyGenerator
from ..services.graph_builder import GraphBuilderService
from ..services.text_processor import TextProcessor
from ..utils.file_parser import FileParser
from ..utils.logger import get_logger
from ..models.task import TaskManager, TaskStatus
from ..models.project import ProjectManager, ProjectStatus

# 获取日志器
logger = get_logger('mirofish.api')


def _target_id(value, prefix):
    if not isinstance(value, str) or not re.fullmatch(prefix + r'[A-Za-z0-9_-]{1,100}', value):
        raise BadRequest('Invalid target artifact identifier')
    return value


def _target_read_json(root, *parts, expected_sha256=None):
    """Read only fixed local artifacts, without following directory/file symlinks."""
    if any(not part or part in {'.', '..'} or '/' in part or '\\' in part for part in parts):
        raise BadRequest('Invalid target artifact path')
    directory = None
    try:
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        for part in parts[:-1]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = child
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, 'rb') as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 32 * 1024 * 1024:
                raise Conflict('Invalid target artifact file')
            raw = stream.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise Conflict('Target artifact exceeds read limit')
        if expected_sha256 is not None and hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise Conflict('Target artifact hash differs from its pipeline manifest')
        def invalid_constant(value):
            raise ValueError('Non-finite JSON')
        def unique_pairs(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate JSON key')
                result[key] = value
            return result
        data = json.loads(raw, parse_constant=invalid_constant, object_pairs_hook=unique_pairs)
        if not isinstance(data, dict):
            raise ValueError('Expected an object')
        json.dumps(data, allow_nan=False)  # Also catches numeric exponents that overflow to infinity.
        return data
    except FileNotFoundError:
        raise NotFound('Target artifact is not available yet') from None
    except (OSError, ValueError, UnicodeError):
        raise Conflict('Target artifact is invalid or is not a local regular file') from None
    finally:
        if directory is not None:
            os.close(directory)


def _target_artifact(pipeline_id, name, root, *parts):
    """Verify the bytes read against the owner seal without trusting its path."""
    manifest = _target_read_json(Config.PIPELINE_DATA_DIR, pipeline_id, 'handoff', 'manifest.json')
    entry = manifest.get(name)
    if entry is None:
        raise NotFound('Target artifact has not been sealed yet')
    expected_path = os.path.abspath(os.path.join(root, *parts))
    if (not isinstance(entry, dict) or entry.get('path') != expected_path or
            not isinstance(entry.get('sha256'), str) or
            not re.fullmatch(r'[a-f0-9]{64}', entry['sha256'])):
        raise Conflict('Target artifact manifest does not match its owner or known path')
    return _target_read_json(root, *parts, expected_sha256=entry['sha256'])


def _target_pipeline(pipeline_id):
    _target_id(pipeline_id, 'pipe_')
    state = _target_read_json(Config.PIPELINE_DATA_DIR, pipeline_id, 'pipeline_state.json')
    if (state.get('pipeline_id') != pipeline_id or
            not isinstance(state.get('options'), dict) or
            state['options'].get('forecast_authority') != 'target-first-v1'):
        raise Conflict('Pipeline does not own a target-first forecast')
    # Deliberately ignore persisted artifact pointers and shared fork handoffs.
    # Target reads may only use this owner's known local handoff files.
    expected = os.path.abspath(os.path.join(Config.PIPELINE_DATA_DIR, pipeline_id, 'handoff'))
    handoff_dir = state.get('handoff_dir')
    if handoff_dir is not None and (not isinstance(handoff_dir, str) or
                                    os.path.abspath(handoff_dir) != expected):
        raise Conflict('Target handoff does not belong to this pipeline')
    return state


def _target_case(pipeline_id, owner):
    from ..services.official_data import bridge_module
    fc = bridge_module('forecast_case')
    try:
        case = fc.validate_case(_target_artifact(
            pipeline_id, 'forecast_case', Config.PIPELINE_DATA_DIR,
            pipeline_id, 'handoff', 'forecast_case.json'))
        digest = fc.case_hash(case)
        prompt = owner.get('prompt')
        if not isinstance(prompt, str) or prompt.strip() != case['question'].strip():
            raise Conflict('Target case question differs from its pipeline')
        question_hash = hashlib.sha256(json.dumps(prompt, sort_keys=True, ensure_ascii=False,
                                                  separators=(',', ':')).encode()).hexdigest()
        expected_binding = {'authority': 'target-first-v1', 'caseId': case['caseId'],
                            'caseHash': digest, 'questionHash': question_hash, 'policyVersion': 1}
        if owner['options'].get('target_case_binding') != expected_binding:
            raise Conflict('Target case differs from its frozen pipeline binding')
        return case, digest
    except ValueError:
        raise Conflict('Target forecast case is invalid') from None


@graph_bp.before_request
def _serve_target_graph():
    """Keep all target graph reads on the deterministic local projection."""
    graph_id = (request.view_args or {}).get('graph_id', '')
    if not graph_id.startswith('target_graph_'):
        return None
    try:
        if request.method != 'GET':
            raise Conflict('Target graphs are read-only pipeline artifacts')
        pipeline_id = graph_id.removeprefix('target_graph_')
        state = _target_pipeline(pipeline_id)
        if state.get('graph_id') != graph_id:
            raise Conflict('Graph does not match its pipeline owner')
        case, _ = _target_case(pipeline_id, state)
        from ..services.official_data import bridge_module
        projection = _target_artifact(pipeline_id, 'target_graph', Config.PIPELINE_DATA_DIR,
                                      pipeline_id, 'handoff', 'target_graph.json')
        expected = bridge_module('forecast_case').graph_projection(case)
        # The coordinator may add the public graph ID, but cannot redirect the read.
        if {k: v for k, v in projection.items() if k != 'graph_id'} != expected:
            raise Conflict('Target graph projection does not match its forecast case')
        if projection.get('graph_id', graph_id) != graph_id:
            raise Conflict('Target graph identity mismatch')
        data = {**projection, 'graph_id': graph_id,
                'node_count': len(projection['nodes']), 'edge_count': len(projection['edges'])}
        endpoint = (request.endpoint or '').split('.')[-1]
        if endpoint == 'get_graph_data':
            return jsonify(success=True, data=data)
        if endpoint in {'get_graph_node_detail', 'get_graph_edge_detail'}:
            is_node = endpoint == 'get_graph_node_detail'
            key = 'node_uuid' if is_node else 'edge_uuid'
            row = next((item for item in data['nodes' if is_node else 'edges']
                        if item.get('uuid') == request.view_args[key]), None)
            if row is None:
                raise NotFound('Target graph item not found')
            return jsonify(success=True, data=row)
        if endpoint == 'get_graph_neighbors':
            selected = {request.view_args['node_uuid']}
            if not any(item.get('uuid') in selected for item in data['nodes']):
                raise NotFound('Target graph node not found')
            depth = max(1, min(request.args.get('depth', 1, type=int), 3))
            for _ in range(depth):
                selected |= {value for edge in data['edges']
                             if edge['source_node_uuid'] in selected or edge['target_node_uuid'] in selected
                             for value in (edge['source_node_uuid'], edge['target_node_uuid'])}
            data['nodes'] = [n for n in data['nodes'] if n['uuid'] in selected]
            data['edges'] = [e for e in data['edges'] if e['source_node_uuid'] in selected and e['target_node_uuid'] in selected]
            data['node_count'], data['edge_count'] = len(data['nodes']), len(data['edges'])
            return jsonify(success=True, data=data)
        raise Conflict('This operation is not supported for target graphs')
    except (BadRequest, Conflict, NotFound) as exc:
        return jsonify(success=False, error=exc.description), exc.code


def allowed_file(filename: str) -> bool:
    """检查文件扩展名是否允许"""
    if not filename or '.' not in filename:
        return False
    ext = os.path.splitext(filename)[1].lower().lstrip('.')
    return ext in Config.ALLOWED_EXTENSIONS


# ============== 项目管理接口 ==============

@graph_bp.route('/project/<project_id>', methods=['GET'])
def get_project(project_id: str):
    """
    获取项目详情
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": project.to_dict()
    })


@graph_bp.route('/project/list', methods=['GET'])
def list_projects():
    """
    列出所有项目
    """
    limit = request.args.get('limit', 50, type=int)
    projects = ProjectManager.list_projects(limit=limit)
    
    return jsonify({
        "success": True,
        "data": [p.to_dict() for p in projects],
        "count": len(projects)
    })


@graph_bp.route('/project/<project_id>', methods=['DELETE'])
def delete_project(project_id: str):
    """
    删除项目
    """
    success = ProjectManager.delete_project(project_id)
    
    if not success:
        return jsonify({
            "success": False,
            "error": f"项目不存在或删除失败: {project_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "message": f"项目已删除: {project_id}"
    })


@graph_bp.route('/project/<project_id>/reset', methods=['POST'])
def reset_project(project_id: str):
    """
    重置项目状态（用于重新构建图谱）
    """
    project = ProjectManager.get_project(project_id)
    
    if not project:
        return jsonify({
            "success": False,
            "error": f"项目不存在: {project_id}"
        }), 404
    
    # 重置到本体已生成状态
    if project.ontology:
        project.status = ProjectStatus.ONTOLOGY_GENERATED
    else:
        project.status = ProjectStatus.CREATED
    
    project.graph_id = None
    project.graph_build_task_id = None
    project.error = None
    ProjectManager.save_project(project)
    
    return jsonify({
        "success": True,
        "message": f"项目已重置: {project_id}",
        "data": project.to_dict()
    })


# ============== 接口1：上传文件并生成本体 ==============

@graph_bp.route('/ontology/generate', methods=['POST'])
def generate_ontology():
    """
    接口1：上传文件，分析生成本体定义
    
    请求方式：multipart/form-data
    
    参数：
        files: 上传的文件（PDF/MD/TXT），可多个
        simulation_requirement: 模拟需求描述（必填）
        project_name: 项目名称（可选）
        additional_context: 额外说明（可选）
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "ontology": {
                    "entity_types": [...],
                    "edge_types": [...],
                    "analysis_summary": "..."
                },
                "files": [...],
                "total_text_length": 12345
            }
        }
    """
    try:
        logger.info("=== 开始生成本体定义 ===")
        
        # 获取参数
        simulation_requirement = request.form.get('simulation_requirement', '')
        project_name = request.form.get('project_name', 'Unnamed Project')
        additional_context = request.form.get('additional_context', '')
        
        logger.debug(f"项目名称: {project_name}")
        logger.debug(f"模拟需求: {simulation_requirement[:100]}...")
        
        if not simulation_requirement:
            return jsonify({
                "success": False,
                "error": "请提供模拟需求描述 (simulation_requirement)"
            }), 400
        
        # 获取上传的文件
        uploaded_files = request.files.getlist('files')
        if not uploaded_files or all(not f.filename for f in uploaded_files):
            return jsonify({
                "success": False,
                "error": "请至少上传一个文档文件"
            }), 400
        
        # 创建项目
        project = ProjectManager.create_project(name=project_name)
        project.simulation_requirement = simulation_requirement
        logger.info(f"创建项目: {project.project_id}")
        
        # 保存文件并提取文本
        document_texts = []
        all_text = ""
        
        for file in uploaded_files:
            if file and file.filename and allowed_file(file.filename):
                # 保存文件到项目目录
                file_info = ProjectManager.save_file_to_project(
                    project.project_id, 
                    file, 
                    file.filename
                )
                project.files.append({
                    "filename": file_info["original_filename"],
                    "size": file_info["size"]
                })
                
                # 提取文本
                text = FileParser.extract_text(file_info["path"])
                text = TextProcessor.preprocess_text(text)
                document_texts.append(text)
                all_text += f"\n\n=== {file_info['original_filename']} ===\n{text}"
        
        if not document_texts:
            ProjectManager.delete_project(project.project_id)
            return jsonify({
                "success": False,
                "error": "没有成功处理任何文档，请检查文件格式"
            }), 400
        
        # 保存提取的文本
        project.total_text_length = len(all_text)
        ProjectManager.save_extracted_text(project.project_id, all_text)
        logger.info(f"文本提取完成，共 {len(all_text)} 字符")
        
        # 生成本体
        logger.info("调用 LLM 生成本体定义...")
        generator = OntologyGenerator()
        ontology = generator.generate(
            document_texts=document_texts,
            simulation_requirement=simulation_requirement,
            additional_context=additional_context if additional_context else None
        )
        
        # 保存本体到项目
        entity_count = len(ontology.get("entity_types", []))
        edge_count = len(ontology.get("edge_types", []))
        logger.info(f"本体生成完成: {entity_count} 个实体类型, {edge_count} 个关系类型")
        
        project.ontology = {
            "entity_types": ontology.get("entity_types", []),
            "edge_types": ontology.get("edge_types", [])
        }
        project.analysis_summary = ontology.get("analysis_summary", "")
        project.status = ProjectStatus.ONTOLOGY_GENERATED
        ProjectManager.save_project(project)
        logger.info(f"=== 本体生成完成 === 项目ID: {project.project_id}")
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project.project_id,
                "project_name": project.name,
                "ontology": project.ontology,
                "analysis_summary": project.analysis_summary,
                "files": project.files,
                "total_text_length": project.total_text_length
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 接口2：构建图谱 ==============

@graph_bp.route('/build', methods=['POST'])
def build_graph():
    """
    接口2：根据project_id构建图谱
    
    请求（JSON）：
        {
            "project_id": "proj_xxxx",  // 必填，来自接口1
            "graph_name": "图谱名称",    // 可选
            "chunk_size": 500,          // 可选，默认500
            "chunk_overlap": 50         // 可选，默认50
        }
        
    返回：
        {
            "success": true,
            "data": {
                "project_id": "proj_xxxx",
                "task_id": "task_xxxx",
                "message": "图谱构建任务已启动"
            }
        }
    """
    try:
        logger.info("=== 开始构建图谱 ===")
        
        # 检查配置
        errors = []
        if not Config.ZEP_API_KEY:
            errors.append("ZEP_API_KEY未配置")
        if errors:
            logger.error(f"配置错误: {errors}")
            return jsonify({
                "success": False,
                "error": "配置错误: " + "; ".join(errors)
            }), 500
        
        # 解析请求
        data = request.get_json() or {}
        project_id = data.get('project_id')
        logger.debug(f"请求参数: project_id={project_id}")
        
        if not project_id:
            return jsonify({
                "success": False,
                "error": "请提供 project_id"
            }), 400
        
        # 获取项目
        project = ProjectManager.get_project(project_id)
        if not project:
            return jsonify({
                "success": False,
                "error": f"项目不存在: {project_id}"
            }), 404
        
        # 检查项目状态
        force = data.get('force', False)  # 强制重新构建
        
        if project.status == ProjectStatus.CREATED:
            return jsonify({
                "success": False,
                "error": "项目尚未生成本体，请先调用 /ontology/generate"
            }), 400
        
        if project.status == ProjectStatus.GRAPH_BUILDING and not force:
            return jsonify({
                "success": False,
                "error": "图谱正在构建中，请勿重复提交。如需强制重建，请添加 force: true",
                "task_id": project.graph_build_task_id
            }), 400
        
        # 如果强制重建，重置状态
        if force and project.status in [ProjectStatus.GRAPH_BUILDING, ProjectStatus.FAILED, ProjectStatus.GRAPH_COMPLETED]:
            project.status = ProjectStatus.ONTOLOGY_GENERATED
            project.graph_id = None
            project.graph_build_task_id = None
            project.error = None
        
        # 获取配置
        graph_name = data.get('graph_name', project.name or 'MiroFish Graph')
        chunk_size = data.get('chunk_size', project.chunk_size or Config.DEFAULT_CHUNK_SIZE)
        chunk_overlap = data.get('chunk_overlap', project.chunk_overlap or Config.DEFAULT_CHUNK_OVERLAP)
        
        # 更新项目配置
        project.chunk_size = chunk_size
        project.chunk_overlap = chunk_overlap
        
        # 获取提取的文本
        text = ProjectManager.get_extracted_text(project_id)
        if not text:
            return jsonify({
                "success": False,
                "error": "未找到提取的文本内容"
            }), 400
        
        # 获取本体
        ontology = project.ontology
        if not ontology:
            return jsonify({
                "success": False,
                "error": "未找到本体定义"
            }), 400
        
        # 创建异步任务
        task_manager = TaskManager()
        task_id = task_manager.create_task(f"构建图谱: {graph_name}")
        logger.info(f"创建图谱构建任务: task_id={task_id}, project_id={project_id}")
        
        # 更新项目状态
        project.status = ProjectStatus.GRAPH_BUILDING
        project.graph_build_task_id = task_id
        ProjectManager.save_project(project)
        
        # 启动后台任务
        def build_task():
            build_logger = get_logger('mirofish.build')
            try:
                build_logger.info(f"[{task_id}] 开始构建图谱...")
                task_manager.update_task(
                    task_id, 
                    status=TaskStatus.PROCESSING,
                    message="初始化图谱构建服务..."
                )
                
                # 创建图谱构建服务
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                
                # 分块
                task_manager.update_task(
                    task_id,
                    message="文本分块中...",
                    progress=5
                )
                chunks = TextProcessor.split_text(
                    text, 
                    chunk_size=chunk_size, 
                    overlap=chunk_overlap
                )
                total_chunks = len(chunks)
                
                # 创建图谱
                task_manager.update_task(
                    task_id,
                    message="创建Zep图谱...",
                    progress=10
                )
                graph_id = builder.create_graph(name=graph_name)
                
                # 更新项目的graph_id
                project.graph_id = graph_id
                ProjectManager.save_project(project)
                
                # 设置本体
                task_manager.update_task(
                    task_id,
                    message="设置本体定义...",
                    progress=15
                )
                builder.set_ontology(graph_id, ontology)
                
                # 添加文本（progress_callback 签名是 (msg, progress_ratio)）
                def add_progress_callback(msg, progress_ratio):
                    progress = 15 + int(progress_ratio * 40)  # 15% - 55%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                task_manager.update_task(
                    task_id,
                    message=f"开始添加 {total_chunks} 个文本块...",
                    progress=15
                )
                
                episode_uuids = builder.add_text_batches(
                    graph_id, 
                    chunks,
                    batch_size=3,
                    progress_callback=add_progress_callback
                )
                
                # 等待Zep处理完成（查询每个episode的processed状态）
                task_manager.update_task(
                    task_id,
                    message="等待Zep处理数据...",
                    progress=55
                )
                
                def wait_progress_callback(msg, progress_ratio):
                    progress = 55 + int(progress_ratio * 35)  # 55% - 90%
                    task_manager.update_task(
                        task_id,
                        message=msg,
                        progress=progress
                    )
                
                builder._wait_for_episodes(episode_uuids, wait_progress_callback)
                
                # Wave9-KG（布局预计算）：建图完成即持久化 positions.json（失败只告警）。
                if getattr(Config, "GRAPH_LAYOUT_PRECOMPUTE", True):
                    builder.compute_layout(graph_id)

                # 获取图谱数据
                task_manager.update_task(
                    task_id,
                    message="获取图谱数据...",
                    progress=95
                )
                graph_data = builder.get_graph_data(graph_id)
                
                # 更新项目状态
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                
                node_count = graph_data.get("node_count", 0)
                edge_count = graph_data.get("edge_count", 0)
                build_logger.info(f"[{task_id}] 图谱构建完成: graph_id={graph_id}, 节点={node_count}, 边={edge_count}")
                
                # 完成
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.COMPLETED,
                    message="图谱构建完成",
                    progress=100,
                    result={
                        "project_id": project_id,
                        "graph_id": graph_id,
                        "node_count": node_count,
                        "edge_count": edge_count,
                        "chunk_count": total_chunks
                    }
                )
                
            except Exception as e:
                # 更新项目状态为失败
                build_logger.error(f"[{task_id}] 图谱构建失败: {str(e)}")
                build_logger.debug(traceback.format_exc())
                
                project.status = ProjectStatus.FAILED
                project.error = str(e)
                ProjectManager.save_project(project)
                
                task_manager.update_task(
                    task_id,
                    status=TaskStatus.FAILED,
                    message=f"构建失败: {str(e)}",
                    error=traceback.format_exc()
                )
        
        # 启动后台线程
        thread = threading.Thread(target=build_task, daemon=True)
        thread.start()
        
        return jsonify({
            "success": True,
            "data": {
                "project_id": project_id,
                "task_id": task_id,
                "message": "图谱构建任务已启动，请通过 /task/{task_id} 查询进度"
            }
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ============== 任务查询接口 ==============

@graph_bp.route('/task/<task_id>', methods=['GET'])
def get_task(task_id: str):
    """
    查询任务状态
    """
    task = TaskManager().get_task(task_id)
    
    if not task:
        return jsonify({
            "success": False,
            "error": f"任务不存在: {task_id}"
        }), 404
    
    return jsonify({
        "success": True,
        "data": task.to_dict()
    })


@graph_bp.route('/tasks', methods=['GET'])
def list_tasks():
    """
    列出所有任务
    """
    tasks = TaskManager().list_tasks()
    
    return jsonify({
        "success": True,
        "data": [t.to_dict() for t in tasks],
        "count": len(tasks)
    })


# ============== 图谱数据接口 ==============

def _parse_bool_arg(name: str, default: bool = False) -> bool:
    """query 参数的宽松布尔解析（1/true/yes/on）。"""
    raw = (request.args.get(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@graph_bp.route('/data/<graph_id>', methods=['GET'])
def get_graph_data(graph_id: str):
    """
    获取图谱数据（节点和边）。

    Wave9-KG 可选 query 参数（全部缺省 = 旧的全量行为，逐字节兼容）：
        top_k:      按度数排名只返回前 K 个节点及导出边；0/负值 = 用
                    Config.GRAPH_UI_MAX_NODES（默认 400）。
        min_degree: 只保留度数 ≥ 该值的节点。
        slim:       true 时剥掉 summary/fact/episodes/attributes 等重字段
                    （明细走 /data/<graph_id>/node|edge/<uuid>）。
        full:       true 时强制全量（覆盖 top_k/min_degree，调试逃生门）。
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY未配置"
            }), 500

        top_k = request.args.get('top_k', None, type=int)
        min_degree = request.args.get('min_degree', None, type=int)
        slim = _parse_bool_arg('slim')
        if _parse_bool_arg('full'):
            top_k = None
            min_degree = None

        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        graph_data = builder.get_graph_data(
            graph_id, top_k=top_k, min_degree=min_degree, slim=slim
        )

        return jsonify({
            "success": True,
            "data": graph_data
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>/neighbors/<node_uuid>', methods=['GET'])
def get_graph_neighbors(graph_id: str, node_uuid: str):
    """
    Wave9-KG（点击展开）：返回某节点 depth 跳内的邻域子图。

    query 参数：depth（默认 1，上限 3）、slim（默认 true）。
    """
    try:
        depth = request.args.get('depth', 1, type=int)
        slim = _parse_bool_arg('slim', default=True)
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        data = builder.get_node_neighborhood(graph_id, node_uuid, depth=depth, slim=slim)
        return jsonify({"success": True, "data": data})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>/node/<node_uuid>', methods=['GET'])
def get_graph_node_detail(graph_id: str, node_uuid: str):
    """Wave9-KG（详情面板）：单节点全字段（slim 列表剥掉的字段从这里取）。"""
    try:
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        node = builder.get_node_detail(graph_id, node_uuid)
        if node is None:
            return jsonify({"success": False, "error": f"节点不存在: {node_uuid}"}), 404
        return jsonify({"success": True, "data": node})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/data/<graph_id>/edge/<edge_uuid>', methods=['GET'])
def get_graph_edge_detail(graph_id: str, edge_uuid: str):
    """Wave9-KG（详情面板）：单边全字段（fact/episodes/attributes/时间戳）。"""
    try:
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        edge = builder.get_edge_detail(graph_id, edge_uuid)
        if edge is None:
            return jsonify({"success": False, "error": f"边不存在: {edge_uuid}"}), 404
        return jsonify({"success": True, "data": edge})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/gc', methods=['POST'])
def gc_stale_graphs():
    """
    Wave9-KG（陈旧图谱 GC）：回收不再被任何管线/项目引用的历史图谱。

    请求（JSON，可选）：{"retain": 5}  // 未引用图中额外保留的最新个数
    返回 GC 审计（kept/deleted/failed/skipped_reason）。
    """
    try:
        data = request.get_json(silent=True) or {}
        retain = data.get('retain')
        if retain is not None:
            retain = int(retain)
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        audit = builder.gc_stale_graphs(retain=retain)
        return jsonify({"success": True, "data": audit})
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


@graph_bp.route('/delete/<graph_id>', methods=['DELETE'])
def delete_graph(graph_id: str):
    """
    删除Zep图谱
    """
    try:
        if not Config.ZEP_API_KEY:
            return jsonify({
                "success": False,
                "error": "ZEP_API_KEY未配置"
            }), 500
        
        builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
        builder.delete_graph(graph_id)
        
        return jsonify({
            "success": True,
            "message": f"图谱已删除: {graph_id}"
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500


# ───────────────────── 2026-10-21: graph translation overlay ─────────────────────

@graph_bp.route('/<graph_id>/translations/<lang>', methods=['POST'])
def generate_graph_translation(graph_id: str, lang: str):
    """Translate the graph panel's text (node summaries / edge facts) into <lang>.

    Bounded inventory (degree-ranked top nodes + their edges), sha-keyed cache under
    uploads/graph_translations/<graph_id>/<lang>.json — incremental regeneration
    only translates new/changed entries; content-filter failures degrade per
    fragment via the compliance ladder instead of failing the overlay."""
    lang = (lang or '').strip().lower()
    if lang not in ('zh', 'en'):
        return jsonify({"success": False, "error": "仅支持 zh/en"}), 400
    try:
        from ..services.artifact_translation import start_translation
        result = start_translation("graph", graph_id, lang, force=bool(request.args.get('force')))
        return jsonify({"success": True, "data": result}), 202
    except Exception as e:  # noqa: BLE001
        logger.error(f"图谱翻译失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": str(e)}), 500


@graph_bp.route('/<graph_id>/translations/<lang>', methods=['GET'])
def get_graph_translation(graph_id: str, lang: str):
    lang = (lang or '').strip().lower()
    if lang not in ('zh', 'en'):
        return jsonify({"success": False, "error": "仅支持 zh/en"}), 400
    try:
        from ..services.artifact_translation import translation_status
        result = translation_status("graph", graph_id, lang)
        return jsonify({"success": True, "data": result})
    except Exception as e:  # noqa: BLE001
        return jsonify({"success": False, "error": str(e)}), 500
