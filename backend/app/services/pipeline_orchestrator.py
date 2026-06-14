"""统一管线编排器 (PipelineOrchestrator)

把 DeerFlow 深度研究 (Step 0) 接到 MiroFish 现有的五步预测管线之前，实现
"一个 prompt 进，预测报告出"：

    prompt
      → [research]  DeerFlow 子进程深度调研 → handoff/ (research_report.md, actors.json)
      → [ontology]  用研究报告做种子文本 + prompt 做预测需求 → 本体
      → [graph]     构建 Zep 知识图谱
      → [prepare]   生成 persona + 模拟配置
      → [run]       OASIS 双平台模拟
      → [report]    ReportAgent 生成预测报告

设计要点
--------
* DeerFlow 运行在它自己的 venv（依赖树与 MiroFish 隔离），通过 subprocess 调用
  仓库内 deer-flow/ 的 ``deerflow_research.py``，消费其写出的文件化 handoff 契约。
  这一模式与 ``SimulationRunner`` 驱动 OASIS 进程完全一致。
* 编排器在后台 daemon 线程中运行，进度同时写入：
    - 全局 ``TaskManager`` 任务（沿用 MiroFish 既有的轮询机制）；
    - ``uploads/pipelines/<id>/pipeline_state.json``（断点续看 + 各阶段细分进度）。
* 复用现有 service，不走 HTTP；阶段间通过 project_id → graph_id → simulation_id
  → report_id 串联。
"""

from __future__ import annotations

import atexit
import json
import os
import signal
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..config import Config
from ..models.project import ProjectManager, ProjectStatus
from ..models.task import TaskManager
from ..services.graph_builder import GraphBuilderService
from ..services.ontology_generator import OntologyGenerator
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.simulation_runner import RunnerStatus, SimulationRunner
from ..services.text_processor import TextProcessor
from ..utils.logger import get_logger

logger = get_logger('mirofish.pipeline')


# ---------------------------------------------------------------------------
# 阶段定义与全局进度权重（每个阶段在全局 0-100 中占的区间）
# ---------------------------------------------------------------------------

STAGE_RESEARCH = "research"
STAGE_ONTOLOGY = "ontology"
STAGE_GRAPH = "graph"
STAGE_PREPARE = "prepare"
STAGE_RUN = "run"
STAGE_REPORT = "report"

# (起点, 终点) 全局百分比区间
STAGE_BANDS: dict[str, tuple[int, int]] = {
    STAGE_RESEARCH: (0, 30),
    STAGE_ONTOLOGY: (30, 40),
    STAGE_GRAPH: (40, 60),
    STAGE_PREPARE: (60, 72),
    STAGE_RUN: (72, 92),
    STAGE_REPORT: (92, 100),
}

# research_only 模式下，研究阶段独占 0-100
RESEARCH_ONLY_BANDS: dict[str, tuple[int, int]] = {STAGE_RESEARCH: (0, 100)}


class PipelineCancelled(BaseException):
    """用户主动取消管线（与失败区分开：不是错误，是决定）。

    继承 BaseException 而非 Exception：管线各阶段（章节级容错、模拟准备等）布有
    大量 ``except Exception`` 的纵深防御层，取消信号必须穿透它们直达 ``_run`` 的
    取消处理器——否则取消会被降级成"占位符章节"或"阶段失败"，状态被误标。
    （与 KeyboardInterrupt 同类的控制流信号，不是可恢复错误。）
    """


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StageState:
    name: str
    status: str = "pending"          # pending / running / completed / failed / skipped
    progress: int = 0                # 0-100 (阶段内)
    message: str = ""
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StageState":
        return cls(
            name=data.get("name", ""),
            status=data.get("status", "pending"),
            progress=int(data.get("progress") or 0),
            message=data.get("message", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            error=data.get("error"),
        )


@dataclass
class PipelineState:
    pipeline_id: str
    prompt: str
    mode: str = "full"               # full / research_only
    status: str = "pending"          # pending / running / completed / failed
    global_progress: int = 0
    current_stage: str = ""
    task_id: Optional[str] = None
    # 各阶段产物 id
    project_id: Optional[str] = None
    graph_id: Optional[str] = None
    simulation_id: Optional[str] = None
    report_id: Optional[str] = None
    handoff_dir: Optional[str] = None
    # 在飞研究子进程的 PID（进程组长）。持久化后，后端崩溃重启时
    # reconcile_orphans 能找到并杀掉仍在烧额度的孤儿研究进程。
    research_pid: Optional[int] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    options: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, StageState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineState":
        stages = {
            name: StageState.from_dict(stage if isinstance(stage, dict) else {"name": name})
            for name, stage in (data.get("stages") or {}).items()
        }
        return cls(
            pipeline_id=data["pipeline_id"],
            prompt=data.get("prompt", ""),
            mode=data.get("mode", "full"),
            status=data.get("status", "pending"),
            global_progress=int(data.get("global_progress") or 0),
            current_stage=data.get("current_stage", ""),
            task_id=data.get("task_id"),
            project_id=data.get("project_id"),
            graph_id=data.get("graph_id"),
            simulation_id=data.get("simulation_id"),
            report_id=data.get("report_id"),
            handoff_dir=data.get("handoff_dir"),
            research_pid=data.get("research_pid"),
            error=data.get("error"),
            created_at=data.get("created_at") or _utcnow(),
            updated_at=data.get("updated_at") or _utcnow(),
            options=data.get("options") or {},
            stages=stages,
        )


# ---------------------------------------------------------------------------
# 管线状态持久化（file-backed，沿用 MiroFish 的目录约定）
# ---------------------------------------------------------------------------


class PipelineManager:
    """读写 uploads/pipelines/<id>/pipeline_state.json。"""

    @classmethod
    def _dir(cls, pipeline_id: str) -> str:
        return os.path.join(Config.PIPELINE_DATA_DIR, pipeline_id)

    @classmethod
    def state_path(cls, pipeline_id: str) -> str:
        return os.path.join(cls._dir(pipeline_id), "pipeline_state.json")

    @classmethod
    def handoff_dir(cls, pipeline_id: str) -> str:
        return os.path.join(cls._dir(pipeline_id), "handoff")

    @classmethod
    def ensure_dirs(cls, pipeline_id: str) -> None:
        os.makedirs(cls.handoff_dir(pipeline_id), exist_ok=True)

    @classmethod
    def save(cls, state: PipelineState) -> None:
        cls.ensure_dirs(state.pipeline_id)
        state.updated_at = _utcnow()
        tmp = cls.state_path(state.pipeline_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, ensure_ascii=False, indent=2)
        os.replace(tmp, cls.state_path(state.pipeline_id))

    @classmethod
    def mark_failed(cls, pipeline_id: str, error: str, status: str = "failed") -> bool:
        """直接在持久化 JSON 上把管线标记为终态（无需重建 dataclass）。

        用于启动时回收孤儿管线：进程崩溃/重启后，pipeline_state.json 可能永远停在
        running，前端轮询据此空转。原子写入（tmp + os.replace），同时把当前阶段标为
        同一终态。``status`` 允许 "cancelled"（用户对孤儿管线点取消时语义更准确）。
        """
        data = cls.load(pipeline_id)
        if not data:
            return False
        data["status"] = status
        data["error"] = error
        data["updated_at"] = _utcnow()
        cur = data.get("current_stage")
        stages = data.get("stages") or {}
        if cur and isinstance(stages.get(cur), dict):
            stages[cur]["status"] = status
            stages[cur]["error"] = error
        cls.ensure_dirs(pipeline_id)
        tmp = cls.state_path(pipeline_id) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, cls.state_path(pipeline_id))
        return True

    @classmethod
    def load(cls, pipeline_id: str) -> Optional[dict[str, Any]]:
        path = cls.state_path(pipeline_id)
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    @classmethod
    def delete(cls, pipeline_id: str) -> bool:
        """删除一条管线记录（整个 uploads/pipelines/<id>/ 目录，含 handoff 产物）。

        只做文件系统删除；调用方（PipelineOrchestrator.delete_pipeline）负责
        拒绝在飞管线。目录不存在返回 False。
        """
        import shutil

        # 基本路径防御：pipeline_id 来自 URL，绝不允许路径分隔符逃出数据目录
        if not pipeline_id or "/" in pipeline_id or "\\" in pipeline_id or ".." in pipeline_id:
            return False
        target = cls._dir(pipeline_id)
        if not os.path.isdir(target):
            return False
        shutil.rmtree(target, ignore_errors=True)
        return not os.path.isdir(target)

    @classmethod
    def list_pipelines(cls) -> list[dict[str, Any]]:
        root = Config.PIPELINE_DATA_DIR
        if not os.path.isdir(root):
            return []
        out = []
        for pid in os.listdir(root):
            data = cls.load(pid)
            if data:
                out.append({
                    "pipeline_id": pid,
                    "status": data.get("status"),
                    "prompt": data.get("prompt"),
                    "global_progress": data.get("global_progress"),
                    "created_at": data.get("created_at"),
                    "report_id": data.get("report_id"),
                })
        out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return out


# ---------------------------------------------------------------------------
# DeerFlow 子进程定位与启动
# ---------------------------------------------------------------------------


def _detect_deerflow_python(deerflow_dir: str) -> list[str]:
    """返回调用 DeerFlow 的命令前缀（不含脚本与参数）。

    优先级：显式 DEERFLOW_PYTHON > 探测 .venv > 退回 `uv run --project`。
    """
    if Config.DEERFLOW_PYTHON and os.path.exists(Config.DEERFLOW_PYTHON):
        return [Config.DEERFLOW_PYTHON]
    candidates = [
        os.path.join(deerflow_dir, "backend", ".venv", "bin", "python"),
        os.path.join(deerflow_dir, ".venv", "bin", "python"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return [c]
    # 退回 uv（较慢，且要求 uv 在 PATH）
    backend = os.path.join(deerflow_dir, "backend")
    return ["uv", "run", "--project", backend, "python"]


def _kill_process_group(proc: Optional[subprocess.Popen], sig: int = signal.SIGKILL) -> None:
    """终止子进程所在的整个进程组（与 SimulationRunner 一致，避免遗留孙子进程）。

    DeerFlow 子进程使用 start_new_session=True 自成进程组，因此 os.killpg 能连带
    清理它派生的任何子进程（如 stdio MCP server / sandbox shell）。失败时回退到
    仅终止直接子进程。
    """
    if proc is None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, OSError):
        try:
            proc.kill()
        except Exception:
            pass


class DeerFlowResearchRunner:
    """启动 deerflow_research.py 子进程并把进度回传给回调。"""

    # 在飞的研究子进程，供后端关闭时统一清理（避免 prompt→预测 期间被孤儿化、继续烧额度）。
    _live_procs: "set[subprocess.Popen]" = set()

    @classmethod
    def cleanup_all(cls) -> None:
        """后端退出时终止所有仍在运行的研究子进程组（SIGTERM，温和优先）。"""
        for proc in list(cls._live_procs):
            if proc.poll() is None:
                _kill_process_group(proc, signal.SIGTERM)
            cls._live_procs.discard(proc)

    @staticmethod
    def run(
        prompt: str,
        handoff_dir: str,
        *,
        on_progress: Callable[[int, str], None],
        depth: Optional[str] = None,
        model: Optional[str] = None,
        language: Optional[str] = None,
        subagents: Optional[bool] = None,
        timeout: Optional[int] = None,
        cancel_event: Optional[threading.Event] = None,
        on_spawn: Optional[Callable[[int], None]] = None,
    ) -> dict[str, Any]:
        """运行研究子进程，阻塞直到结束。返回 handoff 摘要。

        Raises:
            PipelineCancelled: cancel_event 被置位（用户取消），子进程组已被终止。
            RuntimeError: 子进程失败、超时或未产出报告。
        """
        deerflow_dir = Config.DEERFLOW_DIR
        script = os.path.join(deerflow_dir, "deerflow_research.py")
        if not os.path.isdir(deerflow_dir):
            raise RuntimeError(f"DeerFlow 目录不存在: {deerflow_dir}（设置 DEERFLOW_DIR）")
        if not os.path.exists(script):
            raise RuntimeError(f"未找到 deerflow_research.py: {script}")

        os.makedirs(handoff_dir, exist_ok=True)
        cmd = _detect_deerflow_python(deerflow_dir) + [
            script,
            "--prompt", prompt,
            "--out-dir", handoff_dir,
            "--model", model or Config.DEERFLOW_MODEL,
            "--depth", depth or Config.DEERFLOW_RESEARCH_DEPTH,
        ]
        lang = language if language is not None else Config.DEERFLOW_RESEARCH_LANGUAGE
        if lang:
            cmd += ["--target-language", lang]
        if (subagents if subagents is not None else Config.DEERFLOW_SUBAGENTS):
            cmd += ["--subagents"]

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")

        logger.info(f"启动 DeerFlow 研究子进程: {' '.join(cmd[:1])} … (cwd={deerflow_dir})")
        on_progress(2, "启动深度研究子进程…")

        proc = subprocess.Popen(
            cmd,
            cwd=deerflow_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            start_new_session=True,  # 自成进程组，便于 os.killpg 连带清理孙子进程
        )
        DeerFlowResearchRunner._live_procs.add(proc)
        if on_spawn is not None:
            try:
                on_spawn(proc.pid)
            except Exception:  # noqa: BLE001 — PID 持久化失败不影响研究本身
                logger.warning("研究子进程 PID 持久化失败", exc_info=True)

        # 看门狗预算按研究深度缩放：deep 是多轮研究协议（source map →
        # primary evidence → actors → contradictions → forecast implications →
        # synthesis），在固定 2400s 下经常被无差别 SIGKILL。显式 timeout 参数 > 用户在 .env 里
        # 显式设置的 DEERFLOW_RESEARCH_TIMEOUT > 深度档位默认值。
        _DEPTH_BUDGETS = {"quick": 900, "standard": 2400, "deep": 10800}
        effective_depth = (depth or Config.DEERFLOW_RESEARCH_DEPTH or "standard").lower()
        if timeout:
            budget = timeout
        elif os.environ.get("DEERFLOW_RESEARCH_TIMEOUT", "").strip():
            budget = Config.DEERFLOW_RESEARCH_TIMEOUT
        else:
            budget = _DEPTH_BUDGETS.get(effective_depth, Config.DEERFLOW_RESEARCH_TIMEOUT)
        deadline = time.time() + budget
        # 看门狗：即使子进程长时间无输出（模型思考），也能在超时后被杀掉。
        timed_out = {"hit": False}

        def _watchdog():
            if proc.poll() is None:
                timed_out["hit"] = True
                _kill_process_group(proc)

        watchdog = threading.Timer(budget, _watchdog)
        watchdog.daemon = True
        watchdog.start()

        # 取消监视：用户取消时立刻杀掉整个研究子进程组（不等超时）。
        # 单独线程而非读循环检查，因为读循环可能阻塞在无输出的 readline 上。
        cancelled = {"hit": False}
        if cancel_event is not None:
            def _cancel_watcher():
                while proc.poll() is None:
                    if cancel_event.wait(timeout=1.0):
                        cancelled["hit"] = True
                        _kill_process_group(proc)
                        return

            t_cancel = threading.Thread(target=_cancel_watcher, daemon=True)
            t_cancel.start()

        # 启发式进度：研究阶段难以精确，按事件类型缓慢推进 2→95。
        local = 2
        tool_events = 0
        last_line = ""
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if not line:
                    continue
                last_line = line
                # 解析进度日志的事件类型 [tool]/[result]/[stage]/[ok]/[done]/[error]
                if "[tool]" in line:
                    tool_events += 1
                    local = min(90, 10 + tool_events * 4)
                    on_progress(local, _tail(line))
                elif "[result]" in line:
                    on_progress(local, _tail(line))
                elif "[stage]" in line:
                    on_progress(min(local, 92), _tail(line))
                elif "[ok]" in line or "[done]" in line:
                    local = max(local, 95)
                    on_progress(local, _tail(line))
                elif "[error]" in line:
                    on_progress(local, _tail(line))
                elif "[init]" in line:
                    on_progress(max(local, 4), _tail(line))
                if timed_out["hit"] or time.time() > deadline:
                    break
            returncode = proc.wait(timeout=30)
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                _kill_process_group(proc)
            DeerFlowResearchRunner._live_procs.discard(proc)

        if cancelled["hit"]:
            raise PipelineCancelled("深度研究已取消")

        report_path = os.path.join(handoff_dir, "research_report.md")
        if timed_out["hit"]:
            # 超时打捞：研究主报告先于 actors/sources 提取阶段落盘——若被看门狗
            # 杀掉时报告已经写出，没必要丢弃整轮研究，降级继续（仅缺结构化档案）。
            if os.path.exists(report_path) and len(_read_text(report_path).strip()) >= 400:
                logger.warning(
                    f"DeerFlow 研究超时（>{budget}s），但 research_report.md 已写出——打捞继续"
                )
                on_progress(95, "研究超时，但报告已生成——打捞继续（无结构化档案）")
            else:
                raise RuntimeError(
                    f"DeerFlow 研究超时（>{budget}s，depth={effective_depth}）。"
                    "可降低研究深度，或在 .env 设更大的 DEERFLOW_RESEARCH_TIMEOUT"
                )
        if returncode != 0 and not os.path.exists(report_path):
            raise RuntimeError(f"DeerFlow 研究子进程失败 (exit={returncode})：{last_line}")
        if not os.path.exists(report_path):
            raise RuntimeError("DeerFlow 研究未产出 research_report.md")

        report = _read_text(report_path)
        if not report.strip():
            raise RuntimeError("research_report.md 为空")
        # 纵深防御：即便上游漏写了降级/错误消息当报告，也别让管线拿一段错误串去
        # 建图/模拟/写报告（那会把垃圾当成功）。覆盖 DeerFlow 降级文案、原始 provider
        # 报错、以及 MiniMax 域内容审核(422 new_sensitive)等多种短错误串。
        _err_markers = (
            "The configured LLM provider",  # DeerFlow LLMErrorHandlingMiddleware 降级
            "LLM request failed",            # 原始 provider 报错被当成正文
            "unprocessable_entity",          # 例如 MiniMax 422 内容审核
            "new_sensitive",                 # MiniMax 域内容过滤命中(code 1026)
            "Error code: 4", "Error code: 5",  # 4xx/5xx 错误串
        )
        if len(report.strip()) < 400 and any(m in report for m in _err_markers):
            raise RuntimeError(
                "DeerFlow 返回的是 LLM 降级/错误消息而非研究报告"
                "（提供方临时不可用/限流/额度、网络错误，或内容审核拦截），"
                "请稍后重试、降低研究深度，或更换模型"
            )

        actors = _read_json(os.path.join(handoff_dir, "actors.json"))
        sources = _read_json(os.path.join(handoff_dir, "sources.json"))
        on_progress(100, f"研究完成（报告 {len(report)} 字）")
        return {
            "report": report,
            "report_path": report_path,
            "actors": actors,
            "sources": sources,
            "exit_code": returncode,
        }


def _tail(s: str, limit: int = 160) -> str:
    s = s.strip()
    # 去掉时间戳+级别前缀，保留信息部分
    if "] " in s:
        s = s.split("] ", 1)[1] if s.count("] ") >= 1 else s
    return s if len(s) <= limit else s[:limit] + "…"


def _read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def _read_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _load_research_handoff(handoff_dir: str) -> dict[str, Any]:
    """Load a previously generated DeerFlow handoff, tolerating missing optional JSON.

    Resume uses this to continue a failed pipeline when the expensive markdown
    dossier was already written but later structured extraction or the watchdog
    failed. The same short-error guard used by DeerFlowResearchRunner still
    applies, so provider fallback text is never treated as usable research.
    """
    report_path = os.path.join(handoff_dir, "research_report.md")
    report = _read_text(report_path)
    # 与 DeerFlowResearchRunner 的短报告守卫语义一致：LLM 降级/错误文案都是短串，
    # <400 字符一律拒绝（涵盖错误串），≥400 视为真实研究报告。
    if len(report.strip()) < 400:
        raise RuntimeError("已有研究报告缺失或过短，无法从研究阶段恢复")
    return {
        "report": report,
        "report_path": report_path,
        "actors": _read_json(os.path.join(handoff_dir, "actors.json")),
        "sources": _read_json(os.path.join(handoff_dir, "sources.json")),
        "exit_code": None,
        "resumed": True,
    }


def preflight_pipeline(mode: str = "full") -> list[str]:
    """启动管线前的快速体检：把会在几十分钟后才暴露的配置错误提前到 POST /run 时。

    只做廉价的本地检查（文件存在性 / PATH / 环境变量），不发任何网络请求。
    返回人类可读的错误列表；为空表示可以起飞。

    Args:
        mode: full / research_only。research_only 在研究完成后即返回，
              全程不碰 Zep 与报告/模拟 LLM，故跳过这两项检查。
    """
    import shutil

    errors: list[str] = []
    full_mode = mode != "research_only"

    # 1) Zep：建图阶段硬依赖（仅 full 模式）。占位符等同于未配置。
    if full_mode and (not Config.ZEP_API_KEY or Config._is_placeholder(Config.ZEP_API_KEY)):
        errors.append("ZEP_API_KEY 未配置（或仍是占位符）。到 https://app.getzep.com/ 免费获取并写入 .env")

    # 2) 报告/模拟阶段的 LLM 提供方（仅 full 模式）
    if full_mode:
        meta = Config.PROVIDER_META.get(Config.LLM_PROVIDER, {})
        if meta.get('needs_key') and not Config.LLM_API_KEY:
            errors.append(f"LLM_PROVIDER={Config.LLM_PROVIDER} 需要 LLM_API_KEY（写入 .env 或在设置菜单填写）")
        if Config.LLM_PROVIDER == 'claude-cli' and shutil.which('claude') is None:
            errors.append("LLM_PROVIDER=claude-cli 但未找到 `claude` CLI。安装 Claude Code（https://claude.com/claude-code）或在设置中切换提供方")
        if Config.LLM_PROVIDER == 'codex-cli' and shutil.which('codex') is None:
            errors.append("LLM_PROVIDER=codex-cli 但未找到 `codex` CLI。安装 Codex CLI 或在设置中切换提供方")

    # 3) DeerFlow 研究引擎（stage 1 硬依赖）
    script = os.path.join(Config.DEERFLOW_DIR, 'deerflow_research.py')
    if not os.path.isdir(Config.DEERFLOW_DIR) or not os.path.exists(script):
        errors.append(
            f"DeerFlow 研究引擎未就绪（{Config.DEERFLOW_DIR}）。"
            "在项目根目录运行 ./setup.sh 自动下载并配置（或设置 DEERFLOW_DIR 指向现有 checkout）"
        )

    # 4) 研究模型的凭据
    df_model = (Config.DEERFLOW_MODEL or 'claude').lower()
    _df_key_env = {'minimax': 'MINIMAX_API_KEY', 'deepseek': 'DEEPSEEK_API_KEY',
                   'qwen': 'DASHSCOPE_API_KEY', 'glm': 'ZHIPUAI_API_KEY',
                   'kimi': 'KIMI_API_KEY'}
    if df_model in _df_key_env and not os.environ.get(_df_key_env[df_model], '').strip():
        errors.append(f"DEERFLOW_MODEL={df_model} 需要环境变量 {_df_key_env[df_model]}（写入 .env）")
    elif df_model == 'claude':
        has_oauth = (
            os.environ.get('CLAUDE_CODE_OAUTH_TOKEN', '').strip()
            or os.environ.get('ANTHROPIC_AUTH_TOKEN', '').strip()
            or os.path.exists(os.path.expanduser('~/.claude/.credentials.json'))
            or shutil.which('claude') is not None  # CLI 在则凭据多半在 Keychain
        )
        if not has_oauth:
            errors.append("DEERFLOW_MODEL=claude 需要 Claude Code 登录凭据：安装 `claude` CLI 并运行一次 `claude` 完成登录")
    elif df_model == 'codex':
        if not os.path.exists(os.path.expanduser('~/.codex/auth.json')) and shutil.which('codex') is None:
            errors.append("DEERFLOW_MODEL=codex 需要 Codex 登录凭据（~/.codex/auth.json）：安装 `codex` CLI 并登录")

    return errors


def _actors_to_context(actors: Optional[dict]) -> Optional[str]:
    """把 actors.json 压成一段给 OntologyGenerator 的 additional_context，
    引导本体偏向真实命名实体。"""
    if not isinstance(actors, dict):
        return None
    rows = actors.get("actors") or []
    if not rows:
        return None
    lines = ["根据深度研究，本事件涉及以下真实命名实体（请让本体覆盖这些类型的角色）："]
    for a in rows[:25]:
        if not isinstance(a, dict):
            continue
        name = a.get("name", "?")
        typ = a.get("type", "")
        role = a.get("role", "")
        stance = a.get("stance", "")
        lines.append(f"- {name}（{typ}）：{role} 立场：{stance}".strip())
    topics = actors.get("hot_topics") or []
    if topics:
        lines.append("热点议题：" + "、".join(str(t) for t in topics[:10]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 编排器
# ---------------------------------------------------------------------------


class PipelineOrchestrator:
    """串联 research → ontology → graph → prepare → run → report。"""

    _threads: dict[str, threading.Thread] = {}
    _cancel_events: dict[str, threading.Event] = {}
    _cleanup_registered: bool = False
    # 串行化 resume/cancel 的"读状态→判定→写状态/起线程"临界区：没有它，两个并发
    # POST /resume 都能在对方落盘 running 之前通过状态检查，对同一管线起两条 _run
    # 线程（双倍烧额度 + 状态互相覆盖）。
    _lifecycle_lock: threading.Lock = threading.Lock()

    # -- 生命周期：启动回收 + 关闭清理 ------------------------------------

    @classmethod
    def reconcile_orphans(cls) -> None:
        """后端启动时回收孤儿管线。

        硬杀 / 崩溃 / 重启会跳过 ``_run`` 的 except 块，使 pipeline_state.json 永远停在
        ``running``；前端 ``poll()`` 只在 completed/failed 时停止，于是无限空转。进程刚启动时
        ``_threads`` 必为空，故任何持久化为 running 的管线都是上一进程遗留的孤儿 → 标记 failed。
        """
        try:
            from ..models.task import TaskManager
            task_manager = TaskManager()
            for p in PipelineManager.list_pipelines():
                if p.get("status") != "running":
                    continue
                pipeline_id = p.get("pipeline_id")
                if not pipeline_id or pipeline_id in cls._threads:
                    continue
                msg = "后端在运行中被中断（进程重启），该管线已标记为失败。"
                if PipelineManager.mark_failed(pipeline_id, msg):
                    logger.warning(f"[{pipeline_id}] 启动时回收孤儿管线 → failed")
                    data = PipelineManager.load(pipeline_id) or {}
                    # 杀掉上一进程遗留、仍在烧额度的孤儿研究子进程（按持久化的 PID）。
                    cls._kill_orphan_research(pipeline_id, data.get("research_pid"))
                    tid = data.get("task_id")
                    if tid:
                        try:
                            task_manager.fail_task(tid, msg)
                        except Exception:
                            pass
        except Exception as e:  # noqa: BLE001 — 回收失败不应阻断启动
            logger.error(f"回收孤儿管线失败: {e}", exc_info=True)

    @staticmethod
    def _kill_orphan_research(pipeline_id: str, pid) -> None:
        """杀掉上一后端进程遗留的研究子进程组（按持久化 PID，谨慎校验防 PID 复用误杀）。"""
        if not pid:
            return
        try:
            pid = int(pid)
        except (TypeError, ValueError):
            return
        try:
            # PID 可能已被无关进程复用：先确认命令行确实是 deerflow_research.py
            check = subprocess.run(
                ["ps", "-p", str(pid), "-o", "command="],
                capture_output=True, text=True, timeout=5,
            )
            cmdline = (check.stdout or "").strip()
            if check.returncode != 0 or "deerflow_research.py" not in cmdline:
                return  # 进程已退出，或 PID 已被复用 → 不动
            os.killpg(os.getpgid(pid), signal.SIGTERM)
            logger.warning(f"[{pipeline_id}] 已终止孤儿研究子进程组 pid={pid}")
        except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
            pass

    @classmethod
    def register_cleanup(cls) -> None:
        """注册后端关闭清理：终止在飞的 DeerFlow 研究子进程组。

        与 ``SimulationRunner.register_cleanup`` 同构，并链式调用此前已安装的信号处理器
        （通常是 SimulationRunner 的），因此两套清理在收到 SIGINT/SIGTERM/SIGHUP 时都会执行；
        ``atexit`` 覆盖正常退出 / ``sys.exit()``。
        """
        if cls._cleanup_registered:
            return

        # Flask debug 模式下只在 reloader 子进程（真正跑应用的进程）注册（与 SimulationRunner 一致）
        is_reloader_process = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
        is_debug_mode = os.environ.get('FLASK_DEBUG') == '1' or os.environ.get('WERKZEUG_RUN_MAIN') is not None
        if is_debug_mode and not is_reloader_process:
            cls._cleanup_registered = True
            return

        cls._cleanup_registered = True
        atexit.register(DeerFlowResearchRunner.cleanup_all)

        original = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }
        has_sighup = hasattr(signal, 'SIGHUP')
        if has_sighup:
            original[signal.SIGHUP] = signal.getsignal(signal.SIGHUP)

        def cleanup_handler(signum, frame):
            DeerFlowResearchRunner.cleanup_all()
            prev = original.get(signum)
            if callable(prev):
                prev(signum, frame)            # 链式：通常是 SimulationRunner 的清理处理器
            elif prev == signal.SIG_IGN:
                return                         # 原本就忽略该信号 → 保持忽略
            else:
                # SIG_DFL 或未知（None）：恢复默认行为并自我终止
                signal.signal(signum, signal.SIG_DFL)
                os.kill(os.getpid(), signum)

        try:
            signal.signal(signal.SIGINT, cleanup_handler)
            signal.signal(signal.SIGTERM, cleanup_handler)
            if has_sighup:
                signal.signal(signal.SIGHUP, cleanup_handler)
        except ValueError:
            # 仅主线程可设置信号处理器；非主线程下 atexit 仍覆盖正常退出
            pass

    @classmethod
    def start(
        cls,
        prompt: str,
        *,
        mode: str = "full",
        project_name: Optional[str] = None,
        depth: Optional[str] = None,
        max_rounds: Optional[int] = None,
    ) -> PipelineState:
        """创建管线记录并在后台线程启动。立即返回（含 pipeline_id / task_id）。"""
        pipeline_id = f"pipe_{uuid.uuid4().hex[:12]}"
        PipelineManager.ensure_dirs(pipeline_id)

        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type=f"pipeline:{mode}",
            metadata={"pipeline_id": pipeline_id},
        )

        bands = RESEARCH_ONLY_BANDS if mode == "research_only" else STAGE_BANDS
        stages = {name: StageState(name=name) for name in bands.keys()}

        state = PipelineState(
            pipeline_id=pipeline_id,
            prompt=prompt,
            mode=mode,
            status="running",
            task_id=task_id,
            handoff_dir=PipelineManager.handoff_dir(pipeline_id),
            stages=stages,
        )
        state.options.update({
            "project_name": project_name or f"研究预测 {pipeline_id}",
            "depth": depth or Config.DEERFLOW_RESEARCH_DEPTH,
            "max_rounds": max_rounds,
        })
        PipelineManager.save(state)

        cls._cancel_events[pipeline_id] = threading.Event()
        t = threading.Thread(
            target=cls._run,
            args=(state,),
            name=f"pipeline-{pipeline_id}",
            daemon=True,
        )
        cls._threads[pipeline_id] = t
        t.start()
        return state

    @classmethod
    def cancel(cls, pipeline_id: str) -> dict[str, Any]:
        """取消一条在飞管线。

        置位取消事件后，取消在下一个取消点生效：研究子进程组被立刻杀掉；
        OASIS 运行被 stop_simulation 停止；其余阶段在下一次进度回调时退出。
        本进程没有该管线的在飞线程（如后端重启后的孤儿）时，直接在持久化
        状态上标记 cancelled。

        Returns:
            {"ok": bool, "status": str}  status ∈ cancelling / cancelled / not_found / not_running
        """
        with cls._lifecycle_lock:
            data = PipelineManager.load(pipeline_id)
            if data is None:
                return {"ok": False, "status": "not_found"}
            if data.get("status") != "running":
                return {"ok": False, "status": "not_running"}

            event = cls._cancel_events.get(pipeline_id)
            thread = cls._threads.get(pipeline_id)
            if event is not None and thread is not None and thread.is_alive():
                event.set()
                logger.info(f"[{pipeline_id}] 收到取消请求，等待管线在取消点退出")
                return {"ok": True, "status": "cancelling"}

            # 孤儿（重启后遗留 running）：直接落盘为 cancelled（是用户决定，不是错误）
            PipelineManager.mark_failed(pipeline_id, "已被用户取消", status="cancelled")
            data = PipelineManager.load(pipeline_id) or {}
            tid = data.get("task_id")
            if tid:
                try:
                    TaskManager().fail_task(tid, "已被用户取消")
                except Exception:
                    pass
            return {"ok": True, "status": "cancelled"}

    @classmethod
    def delete_pipeline(cls, pipeline_id: str) -> dict[str, Any]:
        """删除一条已结束的管线记录（含其 handoff 产物目录）。

        在飞管线必须先取消再删除——删除运行中的状态文件会让 _run 线程在下次
        落盘时凭空复活记录，且孤儿子进程无人回收。

        Returns:
            {"ok": bool, "status": str}  status ∈ deleted / not_found / still_running
        """
        with cls._lifecycle_lock:
            live = cls._threads.get(pipeline_id)
            if live is not None and live.is_alive():
                return {"ok": False, "status": "still_running"}
            data = PipelineManager.load(pipeline_id)
            if data is None:
                return {"ok": False, "status": "not_found"}
            if data.get("status") == "running":
                # 持久化为 running 但本进程无线程 → 孤儿；先按取消语义落盘再删，
                # 这样即使删除中途失败，状态也不会停在 running 误导前端。
                PipelineManager.mark_failed(pipeline_id, "已被用户删除", status="cancelled")
                cls._kill_orphan_research(pipeline_id, data.get("research_pid"))
            ok = PipelineManager.delete(pipeline_id)
            if ok:
                cls._cancel_events.pop(pipeline_id, None)
                cls._threads.pop(pipeline_id, None)
                logger.info(f"[{pipeline_id}] 管线记录已删除")
            return {"ok": ok, "status": "deleted" if ok else "not_found"}

    @classmethod
    def clean_terminal(cls, statuses: tuple[str, ...] = ("failed", "cancelled")) -> dict[str, Any]:
        """批量删除处于指定终态的管线记录（默认清理失败/已取消的运行）。

        running 与 completed 永不触碰；本进程仍有在飞线程的管线一并跳过。
        """
        deleted: list[str] = []
        skipped: list[str] = []
        for p in PipelineManager.list_pipelines():
            pid = p.get("pipeline_id")
            if not pid or p.get("status") not in statuses:
                continue
            result = cls.delete_pipeline(pid)
            (deleted if result["ok"] else skipped).append(pid)
        if deleted:
            logger.info(f"批量清理管线: 删除 {len(deleted)} 条（{', '.join(deleted[:5])}…）")
        return {"deleted": deleted, "skipped": skipped}

    @classmethod
    def resume(cls, pipeline_id: str) -> PipelineState:
        """Resume a failed/cancelled pipeline in place, reusing existing artifacts.

        The pipeline keeps the same id so browser history, artifact paths, and
        local bookmarks remain valid. A fresh task id is assigned for progress
        polling, and the background runner skips completed/recoverable stages.
        """
        with cls._lifecycle_lock:
            # 持久化状态可能滞后（崩溃时写失败），线程注册表才是本进程在飞的真相。
            live = cls._threads.get(pipeline_id)
            if live is not None and live.is_alive():
                raise RuntimeError("管线仍在运行，无法恢复")

            data = PipelineManager.load(pipeline_id)
            if data is None:
                raise FileNotFoundError("管线不存在")
            if data.get("status") == "running":
                raise RuntimeError("管线仍在运行，无法恢复")
            if data.get("status") == "completed":
                raise RuntimeError("管线已完成，无需恢复")

            state = PipelineState.from_dict(data)
            PipelineManager.ensure_dirs(pipeline_id)
            bands = RESEARCH_ONLY_BANDS if state.mode == "research_only" else STAGE_BANDS
            for name in bands.keys():
                state.stages.setdefault(name, StageState(name=name))

            failed_stage = state.current_stage
            if failed_stage and failed_stage in state.stages:
                st = state.stages[failed_stage]
                if st.status in ("failed", "cancelled"):
                    st.status = "pending"
                    st.error = None
                    st.finished_at = None

            task_manager = TaskManager()
            task_id = task_manager.create_task(
                task_type=f"pipeline:{state.mode}:resume",
                metadata={"pipeline_id": pipeline_id, "resumed_from_task_id": state.task_id},
            )
            state.task_id = task_id
            state.status = "running"
            state.error = None
            state.research_pid = None
            state.options["resumed_at"] = _utcnow()
            state.options["resume_count"] = int(state.options.get("resume_count") or 0) + 1
            PipelineManager.save(state)

            cls._cancel_events[pipeline_id] = threading.Event()
            t = threading.Thread(
                target=cls._run,
                args=(state,),
                name=f"pipeline-resume-{pipeline_id}",
                daemon=True,
            )
            cls._threads[pipeline_id] = t
            t.start()
            return state

    # -- 内部：进度辅助 ----------------------------------------------------

    @staticmethod
    def _global_from_stage(mode: str, stage: str, local_pct: int) -> int:
        bands = RESEARCH_ONLY_BANDS if mode == "research_only" else STAGE_BANDS
        lo, hi = bands.get(stage, (0, 100))
        local_pct = max(0, min(100, local_pct))
        return int(lo + (hi - lo) * local_pct / 100)

    def _make_stage_updater(self, state: PipelineState, stage: str):
        task_manager = TaskManager()

        def update(local_pct: int, message: str):
            # 取消点：各阶段内部都会频繁回调进度，在这里抬升取消请求，
            # 使取消无需等到阶段边界。
            ev = PipelineOrchestrator._cancel_events.get(state.pipeline_id)
            if ev is not None and ev.is_set():
                raise PipelineCancelled("管线已被用户取消")
            st = state.stages.get(stage)
            if st is None:
                st = StageState(name=stage)
                state.stages[stage] = st
            st.status = "running"
            st.progress = max(0, min(100, int(local_pct)))
            st.message = message
            if st.started_at is None:
                st.started_at = _utcnow()
            state.current_stage = stage
            state.global_progress = self._global_from_stage(state.mode, stage, local_pct)
            PipelineManager.save(state)
            if state.task_id:
                task_manager.update_task(
                    state.task_id,
                    progress=state.global_progress,
                    message=f"[{stage}] {message}",
                )

        return update

    def _complete_stage(self, state: PipelineState, stage: str, message: str = "完成"):
        st = state.stages.setdefault(stage, StageState(name=stage))
        st.status = "completed"
        st.progress = 100
        st.message = message
        st.finished_at = _utcnow()
        state.global_progress = self._global_from_stage(state.mode, stage, 100)
        PipelineManager.save(state)

    def _fail_stage(self, state: PipelineState, stage: str, error: str):
        st = state.stages.setdefault(stage, StageState(name=stage))
        st.status = "failed"
        st.error = error
        st.finished_at = _utcnow()
        PipelineManager.save(state)

    # -- 内部：主流程 ------------------------------------------------------

    @classmethod
    def _run(cls, state: PipelineState) -> None:
        self = cls()
        task_manager = TaskManager()
        try:
            # ---- Stage 0: RESEARCH ----
            upd = self._make_stage_updater(state, STAGE_RESEARCH)
            handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
            report_path = os.path.join(handoff_dir, "research_report.md")
            if os.path.exists(report_path) and len(_read_text(report_path).strip()) >= 400:
                upd(95, "复用已有研究报告，跳过 DeerFlow 研究阶段…")
                research = _load_research_handoff(handoff_dir)
                state.research_pid = None
                self._complete_stage(state, STAGE_RESEARCH, "研究报告已恢复")
            else:
                upd(1, "准备深度研究…")
                def _persist_research_pid(pid: int) -> None:
                    state.research_pid = pid
                    PipelineManager.save(state)

                research = DeerFlowResearchRunner.run(
                    state.prompt,
                    handoff_dir,
                    on_progress=upd,
                    depth=state.options.get("depth"),
                    cancel_event=cls._cancel_events.get(state.pipeline_id),
                    on_spawn=_persist_research_pid,
                )
                state.research_pid = None  # 子进程已结束，清掉以免 reconcile 误杀复用 PID
                self._complete_stage(state, STAGE_RESEARCH, "研究完成")
            report_md: str = research["report"]
            actors = research.get("actors")

            if state.mode == "research_only":
                state.status = "completed"
                state.global_progress = 100
                PipelineManager.save(state)
                if state.task_id:
                    task_manager.complete_task(state.task_id, result={
                        "pipeline_id": state.pipeline_id,
                        "mode": state.mode,
                        "report_path": research.get("report_path"),
                    })
                logger.info(f"[{state.pipeline_id}] research_only 完成")
                return

            # ---- Stage 1: ONTOLOGY (用研究报告做种子) ----
            upd = self._make_stage_updater(state, STAGE_ONTOLOGY)
            project_name = state.options.get("project_name") or f"研究预测 {state.pipeline_id}"
            project = ProjectManager.get_project(state.project_id) if state.project_id else None
            if project is not None and project.ontology:
                upd(100, "复用已有本体…")
                self._complete_stage(state, STAGE_ONTOLOGY, "本体已恢复")
            else:
                if project is None:
                    upd(10, "用研究报告创建项目…")
                    project = ProjectManager.create_project(name=project_name)
                    project.simulation_requirement = state.prompt
                    ProjectManager.save_extracted_text(project.project_id, report_md)
                    project.total_text_length = len(report_md)
                    file_entry: dict[str, Any] = {"filename": "research_report.md", "size": len(report_md.encode("utf-8"))}
                    project.files.append(file_entry)
                    ProjectManager.save_project(project)
                    state.project_id = project.project_id
                    PipelineManager.save(state)

                upd(40, "生成本体（LLM）…")
                generator = OntologyGenerator()
                ontology = generator.generate(
                    document_texts=[report_md],
                    simulation_requirement=state.prompt,
                    additional_context=_actors_to_context(actors),
                )
                project.ontology = {
                    "entity_types": ontology.get("entity_types", []),
                    "edge_types": ontology.get("edge_types", []),
                }
                project.analysis_summary = ontology.get("analysis_summary", "")
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                ProjectManager.save_project(project)
                self._complete_stage(state, STAGE_ONTOLOGY, "本体生成完成")

            # ---- Stage 2: GRAPH ----
            upd = self._make_stage_updater(state, STAGE_GRAPH)
            graph_stage_done = state.stages.get(STAGE_GRAPH) and state.stages[STAGE_GRAPH].status == "completed"
            graph_id = state.graph_id or getattr(project, "graph_id", None)
            if graph_stage_done and graph_id:
                upd(100, "复用已有知识图谱…")
                state.graph_id = graph_id
                self._complete_stage(state, STAGE_GRAPH, "图谱已恢复")
            else:
                upd(5, "构建知识图谱…")
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                chunks = TextProcessor.split_text(report_md, Config.DEFAULT_CHUNK_SIZE, Config.DEFAULT_CHUNK_OVERLAP)
                graph_id = builder.create_graph(name=project.name)
                builder.set_ontology(graph_id, project.ontology)

                def add_cb(msg: str, ratio: float):
                    upd(int(10 + ratio * 55), msg)

                # batch_size 10：Zep graph.add 按 episode 异步处理，批量提交吞吐近似线性；
                # 3 是早期保守值，研究报告动辄上百 chunk 时建图要多等数分钟。
                uuids = builder.add_text_batches(graph_id, chunks, batch_size=20, progress_callback=add_cb)

                def wait_cb(msg: str, ratio: float):
                    upd(int(65 + ratio * 33), msg)

                builder._wait_for_episodes(uuids, wait_cb)
                project.graph_id = graph_id
                project.status = ProjectStatus.GRAPH_COMPLETED
                ProjectManager.save_project(project)
                state.graph_id = graph_id
                self._complete_stage(state, STAGE_GRAPH, "图谱构建完成")

            # ---- Stage 3: PREPARE ----
            upd = self._make_stage_updater(state, STAGE_PREPARE)
            sim_manager = SimulationManager()
            prepare_stage_done = state.stages.get(STAGE_PREPARE) and state.stages[STAGE_PREPARE].status == "completed"
            sim_state = sim_manager.get_simulation(state.simulation_id) if state.simulation_id else None
            if prepare_stage_done and sim_state is not None:
                upd(100, "复用已有模拟环境…")
                self._complete_stage(state, STAGE_PREPARE, "环境已恢复")
            else:
                if prepare_stage_done and sim_state is None:
                    # 阶段标完成但模拟状态丢了（手动清理/磁盘损坏）：自愈重建，但要留痕。
                    logger.warning(
                        f"[{state.pipeline_id}] prepare 阶段已完成但模拟 "
                        f"{state.simulation_id} 不存在，重新创建模拟环境"
                    )
                upd(5, "创建模拟…")
                sim_state = sim_manager.create_simulation(project.project_id, graph_id, enable_twitter=True, enable_reddit=True)
                state.simulation_id = sim_state.simulation_id
                PipelineManager.save(state)

                def prepare_cb(stage: str, progress: int, message: str, **_kwargs):
                    upd(max(5, min(99, int(progress))), f"{stage}: {message}")

                # persona 生成并发：CLI 提供方受本机 CLI 吞吐限制保持 3；
                # OpenAI 兼容 HTTP 提供方可以放心放大（每个 persona 1 次 LLM + 2 次 Zep 检索）。
                _is_http_provider = bool(Config.PROVIDER_META.get(Config.LLM_PROVIDER, {}).get('openai_compat'))
                sim_manager.prepare_simulation(
                    simulation_id=sim_state.simulation_id,
                    simulation_requirement=state.prompt,
                    document_text=report_md,
                    progress_callback=prepare_cb,
                    parallel_profile_count=8 if _is_http_provider else 3,
                    actors=actors,  # 研究档案直通模拟准备：persona/配置以实证立场为准
                )
                self._complete_stage(state, STAGE_PREPARE, "环境就绪")

            # ---- Stage 4: RUN ----
            upd = self._make_stage_updater(state, STAGE_RUN)
            run_stage_done = state.stages.get(STAGE_RUN) and state.stages[STAGE_RUN].status == "completed"
            if run_stage_done:
                upd(100, "复用已有模拟结果…")
                self._complete_stage(state, STAGE_RUN, "模拟已恢复")
            else:
                upd(2, "启动 OASIS 模拟…")
                run_kwargs: dict[str, Any] = {"platform": "parallel"}
                _mr = state.options.get("max_rounds")
                if _mr:
                    run_kwargs["max_rounds"] = int(_mr)
                SimulationRunner.start_simulation(simulation_id=sim_state.simulation_id, **run_kwargs)
                # 轮询直到完成
                cancel_ev = cls._cancel_events.get(state.pipeline_id)
                _last_round_seen = (-1, -1)
                while True:
                    if cancel_ev is not None and cancel_ev.is_set():
                        # 先停掉 OASIS 子进程再退出，避免取消后模拟继续烧额度
                        try:
                            SimulationRunner.stop_simulation(sim_state.simulation_id)
                        except Exception as stop_err:  # noqa: BLE001
                            logger.warning(f"[{state.pipeline_id}] 取消时停止模拟失败: {stop_err}")
                        raise PipelineCancelled("模拟已被用户取消")
                    rs = SimulationRunner.get_run_state(sim_state.simulation_id)
                    if rs is None:
                        raise RuntimeError("模拟运行状态丢失")
                    total = getattr(rs, "total_rounds", 0) or 0
                    cur = getattr(rs, "current_round", 0) or 0
                    # 仅在轮次推进时落盘进度，省掉每 5s 一次的无效 JSON 重写 + 任务更新
                    # （取消请求由循环顶部的检查兜底，最多延迟一个 5s 周期）
                    if (cur, total) != _last_round_seen:
                        _last_round_seen = (cur, total)
                        if total > 0:
                            upd(min(98, int(cur / total * 100)), f"模拟轮次 {cur}/{total}")
                        else:
                            upd(5, "模拟进行中…")
                    if rs.runner_status == RunnerStatus.COMPLETED:
                        break
                    if rs.runner_status in (RunnerStatus.FAILED, RunnerStatus.STOPPED):
                        raise RuntimeError(f"模拟未正常结束: {rs.runner_status} {getattr(rs, 'error', '') or ''}")
                    if cancel_ev is not None:
                        cancel_ev.wait(5)
                    else:
                        time.sleep(5)
                # 同步 SimulationManager 状态
                try:
                    ss = sim_manager.get_simulation(sim_state.simulation_id)
                    if ss is not None:
                        ss.status = SimulationStatus.COMPLETED
                        sim_manager._save_simulation_state(ss)
                except Exception:
                    pass
                self._complete_stage(state, STAGE_RUN, "模拟完成")

            # ---- Stage 5: REPORT ----
            upd = self._make_stage_updater(state, STAGE_REPORT)
            upd(5, "生成预测报告…")
            report_id = f"report_{uuid.uuid4().hex[:12]}"
            agent = ReportAgent(
                graph_id=graph_id,
                simulation_id=sim_state.simulation_id,
                simulation_requirement=state.prompt,
            )

            def report_cb(stage: str, progress: int, message: str):
                upd(max(5, min(99, int(progress))), f"{stage}: {message}")

            report = agent.generate_report(progress_callback=report_cb, report_id=report_id)
            try:
                ReportManager.save_report(report)
            except Exception:
                pass
            state.report_id = getattr(report, "report_id", report_id)
            if getattr(report, "status", None) == ReportStatus.FAILED:
                raise RuntimeError(getattr(report, "error", "报告生成失败"))
            self._complete_stage(state, STAGE_REPORT, "报告完成")

            # ---- DONE ----
            state.status = "completed"
            state.global_progress = 100
            PipelineManager.save(state)
            if state.task_id:
                task_manager.complete_task(state.task_id, result={
                    "pipeline_id": state.pipeline_id,
                    "project_id": state.project_id,
                    "graph_id": state.graph_id,
                    "simulation_id": state.simulation_id,
                    "report_id": state.report_id,
                })
            logger.info(f"[{state.pipeline_id}] 全流程完成 report={state.report_id}")

        except PipelineCancelled as e:
            logger.info(f"[{state.pipeline_id}] 管线已取消: {e}")
            state.status = "cancelled"
            state.error = str(e)
            if state.current_stage:
                st = state.stages.setdefault(state.current_stage, StageState(name=state.current_stage))
                st.status = "cancelled"
                st.error = str(e)
                st.finished_at = _utcnow()
            PipelineManager.save(state)
            if state.task_id:
                try:
                    task_manager.fail_task(state.task_id, str(e))
                except Exception:
                    pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"[{state.pipeline_id}] 管线失败: {e}", exc_info=True)
            state.status = "failed"
            state.error = str(e)
            if state.current_stage:
                self._fail_stage(state, state.current_stage, str(e))
            PipelineManager.save(state)
            if state.task_id:
                try:
                    task_manager.fail_task(state.task_id, str(e))
                except Exception:
                    pass
        finally:
            # 线程结束即从注册表移除，避免 _threads 无界增长，并让 reconcile_orphans 的
            # "pid in _threads" 判定准确反映当前在飞的线程。
            cls._threads.pop(state.pipeline_id, None)
            cls._cancel_events.pop(state.pipeline_id, None)
