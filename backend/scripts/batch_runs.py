#!/usr/bin/env python3
"""Multi-question batch runs with shared research/graph reuse (I-9-3).

把若干**相关问题**作为一个批次一次性提交：研究 + 本体 + 图谱**只跑一次**（针对锚点
prompt，即列表里的第 0 个问题），其余问题各自从图谱完成处**分叉**（fork）出一条
prepare/run/report 子管线，复用同一张图谱——这正是 ``PipelineOrchestrator.fork()``
已经验证可行的复用机制（research/ontology/graph 标记 completed → 命中
``_run`` 的复用守卫，:1392 研究复用 / :1476 图谱复用）。

为什么值得：真实预测很少是孤立的单个问题——用户想问「对 A 会怎样、对 B 会怎样、A 与 B
的联盟会怎样」这种围绕**同一事件**的一篮子问题。逐个问题重跑 40 分钟的研究 + 建图既浪费
又不一致（不同图谱给出不可比较的答案）。共享研究/图谱让一篮子预测既便宜又内部自洽（全部
锚定在**同一份证据**上），N 个相关预测约等于 1x 研究/建图成本而非 Nx。

两种模式
--------
* **default（每问题独立模拟）**：每个分叉问题各跑一次 OASIS 模拟 + 报告，但共享图谱。
  各问题的 persona/舆情动态可以不同，最贴近"对不同主体分别预测"的语义。
* **shared_simulation（最省）**：所有问题共用锚点的那一次 OASIS 模拟结果，每个问题只跑
  各自的报告 agent（不同 simulation_requirement 查询同一个模拟+图谱）。最便宜，适合
  "同一场推演下回答多个角度"。由 ``--shared-simulation`` 或 Config.BATCH_SHARED_SIMULATION 开启。

OPTIONAL-DEGRADE 不变量
----------------------
本文件是**新增能力**，不改任何既有签名、不动单 prompt 路径。两个行为开关都经
``getattr(Config, NAME, default)`` 读取，缺省即回退到当前行为：
    * BATCH_SHARED_SIMULATION  (默认 False) —— shared_simulation 模式的默认值。
    * BATCH_MAX_FANOUT         (默认 8)     —— 一个批次最多并发分叉多少个问题，防止
                                              众多子模拟把本机 CLI LLM 吞吐打爆（风险栏所述）。

用法
----
    cd backend
    uv run python scripts/batch_runs.py run \
        --prompt "若降息，对科技股影响？" \
        --prompt "若降息，对银行股影响？" \
        --prompt "科技股与银行股的相对强弱会怎样？" \
        [--depth standard] [--max-rounds 5] [--shared-simulation] [--wait]

    uv run python scripts/batch_runs.py status <batch_id> [--json]
    uv run python scripts/batch_runs.py list [--json]

也可作为库使用：``from scripts.batch_runs import start_batch, batch_status``。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# 允许 `python scripts/batch_runs.py` 直接运行（与 test_pipeline_resume.py 同约定）。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import Config  # noqa: E402
from app.services.ensemble import aggregate_forecasts  # noqa: E402
from app.services.pipeline_orchestrator import (  # noqa: E402
    EVALUATION_RUN_OPTION,
    PIPELINE_SCHEMA_VERSION,
    STAGE_BANDS,
    STAGE_GRAPH,
    STAGE_ONTOLOGY,
    STAGE_PREPARE,
    STAGE_REPORT,
    STAGE_RESEARCH,
    STAGE_RUN,
    PipelineManager,
    PipelineOrchestrator,
    PipelineState,
    StageState,
    evaluation_pin_for_question_fork,
    fork_safety_policy_v1,
    preflight_pipeline,
)
from app.services.report_agent import ReportManager  # noqa: E402
from app.services.run_shape import ORIGIN_FORK, SHARED_GRAPH_OPTION  # noqa: E402
from app.utils.atomic import write_json_atomic  # noqa: E402
from app.utils.logger import get_logger  # noqa: E402

logger = get_logger("mirofish.batch")

# I-9-3: 批次记录与子管线同住 PIPELINE_DATA_DIR 下，独立 _batches/ 子目录隔离，避免被
# PipelineManager.list_pipelines 误当成一条管线扫描（它只读 pipe_* 形状的目录下的
# pipeline_state.json，本目录里只有 batch.json，故天然互不干扰）。
_BATCHES_SUBDIR = "_batches"
_BATCH_ID_RE_PREFIX = "batch_"

# 锚点管线等待图谱完成的轮询节奏与上限（研究+建图可达数十分钟，给足余量）。
_POLL_INTERVAL_S = 5.0
# 阻塞轮询的挂钟上限（秒）：锚点建图 / 分叉模拟若永不进入终态，避免 start_batch 永久空转。
# 默认 4 小时（足够最重的建图+模拟）；可经 BATCH_WAIT_TIMEOUT_S 覆盖。
_WAIT_TIMEOUT_S = float(os.environ.get("BATCH_WAIT_TIMEOUT_S", "14400") or "14400")
# 终态：不会再前进的状态，等待图谱时遇到即视为失败提前退出。
_TERMINAL_STATUSES = {"failed", "cancelled", "completed"}


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 批次记录持久化（file-backed，复用 PipelineManager 的目录约定）
# ---------------------------------------------------------------------------


class BatchManager:
    """读写 uploads/pipelines/_batches/<batch_id>/batch.json。

    只做文件系统读写；批次本身不持有任何在飞线程——每个子问题就是一条普通管线，
    由 PipelineOrchestrator 的既有线程注册表/孤儿回收机制管理。
    """

    @staticmethod
    def new_id() -> str:
        return f"{_BATCH_ID_RE_PREFIX}{uuid.uuid4().hex[:12]}"

    @staticmethod
    def _validate_id(batch_id: str) -> str:
        # 与 PipelineManager._validate_id 同样的路径防御：禁止 / \ .. 逃逸数据目录。
        if (
            not batch_id
            or not batch_id.startswith(_BATCH_ID_RE_PREFIX)
            or "/" in batch_id
            or "\\" in batch_id
            or ".." in batch_id
            or not all(c.isalnum() or c in "_-" for c in batch_id)
        ):
            raise ValueError(f"invalid batch_id: {batch_id!r}")
        return batch_id

    @classmethod
    def _dir(cls, batch_id: str) -> str:
        cls._validate_id(batch_id)
        return os.path.join(Config.PIPELINE_DATA_DIR, _BATCHES_SUBDIR, batch_id)

    @classmethod
    def record_path(cls, batch_id: str) -> str:
        return os.path.join(cls._dir(batch_id), "batch.json")

    @classmethod
    def save(cls, record: dict[str, Any]) -> None:
        batch_id = record["batch_id"]
        record["updated_at"] = _utcnow()
        record["schema_version"] = PIPELINE_SCHEMA_VERSION
        # 原子写：避免 status 轮询读者读到半写记录（与全仓 atomic-write-everywhere 一致）。
        write_json_atomic(cls.record_path(batch_id), record)

    @classmethod
    def load(cls, batch_id: str) -> Optional[dict[str, Any]]:
        try:
            path = cls.record_path(batch_id)
        except ValueError:
            return None
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    @classmethod
    def list_batches(cls) -> list[dict[str, Any]]:
        root = os.path.join(Config.PIPELINE_DATA_DIR, _BATCHES_SUBDIR)
        if not os.path.isdir(root):
            return []
        out: list[dict[str, Any]] = []
        for bid in os.listdir(root):
            data = cls.load(bid)
            if data:
                out.append({
                    "batch_id": data.get("batch_id", bid),
                    "status": data.get("status"),
                    "anchor_prompt": data.get("anchor_prompt"),
                    "n_questions": len(data.get("children") or []),
                    "shared_simulation": data.get("shared_simulation"),
                    "created_at": data.get("created_at"),
                })
        out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
        return out


# ---------------------------------------------------------------------------
# 等待锚点管线把研究/本体/图谱跑通（共享复用的前提）
# ---------------------------------------------------------------------------


def _wait_for_graph(pipeline_id: str, cancel: Optional[threading.Event] = None) -> dict[str, Any]:
    """阻塞轮询，直到锚点管线的 GRAPH 阶段完成（拿到可复用的 graph_id）。

    锚点是一条普通 full 管线：research → ontology → graph → prepare → run → report。
    其他问题只需要复用到 graph，故图谱一完成（state.graph_id 落盘且 graph 阶段 completed）
    即可开始分叉，不必等锚点把模拟/报告也跑完——这把分叉的等待时间压到最短。

    Returns:
        最新的锚点 pipeline_state dict（已拿到 graph_id）。
    Raises:
        RuntimeError: 锚点在拿到图谱前进入终态（failed/cancelled）或记录丢失。
    """
    _deadline = time.monotonic() + _WAIT_TIMEOUT_S if _WAIT_TIMEOUT_S > 0 else None
    while True:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("批次已被取消（等待锚点图谱阶段时）")
        if _deadline is not None and time.monotonic() > _deadline:
            raise RuntimeError(f"等待锚点图谱阶段超时（>{int(_WAIT_TIMEOUT_S)}s，疑似卡死）")
        data = PipelineManager.load(pipeline_id)
        if data is None:
            raise RuntimeError(f"锚点管线 {pipeline_id} 记录丢失")
        if PipelineManager.is_incompatible(data) is not None:
            raise RuntimeError(f"锚点管线 {pipeline_id} 状态文件 schema 不兼容（请升级后端）")
        graph_id = data.get("graph_id")
        stages = data.get("stages") or {}
        graph_done = (
            isinstance(stages.get(STAGE_GRAPH), dict)
            and stages[STAGE_GRAPH].get("status") == "completed"
        )
        if graph_id and graph_done:
            return data
        status = data.get("status")
        if status in ("failed", "cancelled") and not (graph_id and graph_done):
            err = data.get("error") or status
            raise RuntimeError(f"锚点管线在建图前进入 {status}：{err}")
        if status == "completed" and not (graph_id and graph_done):
            # 锚点跑完了却没图谱（如 research_only 误用），无法分叉。
            raise RuntimeError("锚点管线已完成但未产出可复用图谱，无法分叉问题")
        time.sleep(_POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# 分叉一个问题：复用锚点的研究/本体/图谱，重跑 prepare/run/report
# ---------------------------------------------------------------------------


def fork_question(
    base_pipeline_id: str,
    question: str,
    *,
    batch_id: Optional[str] = None,
    shared_simulation: bool = False,
    max_rounds: Optional[int] = None,
) -> PipelineState:
    """为一个相关问题分叉一条子管线，复用 base 的研究/本体/图谱（I-9-3）。

    与 ``PipelineOrchestrator.fork()`` 同构（research/ontology/graph 标记 completed →
    命中复用守卫），但额外**覆盖 state.prompt 为本问题**，使本体/persona/报告都围绕这个
    问题展开，同时仍锚定同一张图谱（同一份证据）。

    shared_simulation=True 时进一步把 PREPARE/RUN 也标记 completed 并指向 base 的
    simulation_id，于是只有 REPORT 阶段会跑——一次 OASIS 模拟、多个报告 agent 各自用
    不同的 simulation_requirement（=本问题）查询同一个模拟+图谱，是最省的模式。

    Args:
        base_pipeline_id: 锚点（或任一已完成图谱的）管线 id。
        question: 本子问题的 prompt（覆盖锚点 prompt）。
        batch_id: 归属批次（写入 options['batch_id']，供分组/聚合）。
        shared_simulation: 是否共用 base 的那次模拟（见上）。
        max_rounds: 本问题 OASIS 截断轮数（仅非共享模式有意义）。

    Returns:
        新建子管线的 PipelineState（已在后台线程启动）。
    Raises:
        FileNotFoundError: base 管线不存在。
        RuntimeError: base 未建图；shared_simulation 但 base 无模拟。
    """
    base = PipelineManager.load(base_pipeline_id)
    if base is None:
        raise FileNotFoundError("基础管线不存在")
    if PipelineManager.is_incompatible(base) is not None:
        raise RuntimeError(f"基础管线 {base_pipeline_id} 状态文件 schema 不兼容（请升级后端）")
    base_state = PipelineState.from_dict(base)
    if not base_state.graph_id:
        raise RuntimeError("基础管线尚未建图，无法分叉问题")
    if shared_simulation and not base_state.simulation_id:
        raise RuntimeError("shared_simulation 需要基础管线已产出模拟，请先让锚点跑完模拟阶段")

    new_id = f"pipe_{uuid.uuid4().hex[:12]}"
    new_state = PipelineState(
        pipeline_id=new_id,
        prompt=question,  # I-9-3: 覆盖为本问题（fork() 保留 base.prompt，这里不同）
        mode="full",
        project_id=None,  # 不复用本体项目——每个问题应生成自己的本体/persona（围绕本问题）
        graph_id=base_state.graph_id,  # 复用同一张图谱（同一份证据）
        handoff_dir=base_state.handoff_dir or PipelineManager.handoff_dir(base_pipeline_id),
    )

    # 研究 + 图谱标记完成 → 命中 _run 的复用守卫（研究经 research_report.md 复用，:1392；
    # 图谱经 graph 阶段 completed + graph_id 复用，:1476）。本体阶段保持 pending：project_id
    # 为空，_run 会用本问题做 simulation_requirement 重新生成本体/persona——这正是我们想要的
    # "同一份证据、不同问题"。如此既保证内部自洽（同图谱），又让每个问题有贴题的本体。
    for name in STAGE_BANDS.keys():
        st = StageState(name=name)
        if name in (STAGE_RESEARCH, STAGE_GRAPH):
            st.status = "completed"
            st.progress = 100
        new_state.stages[name] = st

    options: dict[str, Any] = {
        "base_pipeline_id": base_pipeline_id,
        "project_name": (base_state.options or {}).get("project_name"),
        # 透传研究语言/模型/深度，使 run.json 清单与锚点一致（纯记账，研究阶段已被跳过）。
        "depth": (base_state.options or {}).get("depth"),
        "research_language": (base_state.options or {}).get("research_language"),
        "research_model": (base_state.options or {}).get("research_model"),
    }
    if batch_id:
        options["batch_id"] = batch_id
    evaluation_pin = evaluation_pin_for_question_fork(base_pipeline_id, base_state)
    if evaluation_pin is not None:
        # EVAL-13: a question fork of an evaluation run stays in the evaluation lane without
        # the base's cell identity; carried in options, so its lane survives the loss of the
        # base's handoff marker.
        options[EVALUATION_RUN_OPTION] = evaluation_pin
    # INFRA-9：与 PipelineOrchestrator.fork() 同一规则——问题分叉沿用锚点的安全政策钉（锚点无钉则
    # 按分叉准入捕获）；FORK_INHERIT_SAFETY_POLICY 关闭 = 不写（旧行为）。
    safety_policy = fork_safety_policy_v1(base_state.options)
    if safety_policy is not None:
        options["safety_policy_v1"] = safety_policy
    if max_rounds:
        try:
            options["max_rounds"] = int(max_rounds)
        except (TypeError, ValueError):
            pass

    if shared_simulation:
        # 最省模式：PREPARE/RUN 也复用 base 的那次模拟，只跑本问题的 REPORT。
        # _run 的 PREPARE 复用守卫要求 (prepare 阶段 completed && get_simulation(sim_id) 命中)，
        # RUN 复用守卫要求 run 阶段 completed——都满足即直接进 REPORT（report_id 为空 → 新建报告，
        # simulation_requirement=本问题）。本体阶段同样保持 pending（围绕本问题生成）。
        new_state.simulation_id = base_state.simulation_id
        for name in (STAGE_PREPARE, STAGE_RUN):
            new_state.stages[name].status = "completed"
            new_state.stages[name].progress = 100
        options["shared_simulation"] = True
        options["shared_simulation_from"] = base_pipeline_id
        new_state.current_stage = STAGE_REPORT
    else:
        new_state.current_stage = STAGE_ONTOLOGY

    if bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True)):
        # INFRA-7：本体按本问题重生成、图谱刻意沿用锚点——向图谱血统守卫声明这一设计，
        # 否则本 attempt 的本体重算会被当作陈旧上游而重建共享图谱。
        options[SHARED_GRAPH_OPTION] = base_pipeline_id
    new_state.options = options
    # INFRA-7：批次问题分叉是新准入——按分叉时刻的环境钉运行形状（origin=fork），并记下锚点的钉
    # （复用的研究/图谱是在锚点的形状下建的）。
    PipelineOrchestrator._pin_run_shape(new_state, ORIGIN_FORK, base_state=base_state)

    PipelineManager.ensure_dirs(new_id)

    # 与 PipelineOrchestrator.fork() 一致：建任务、落盘 running、在 _lifecycle_lock 下注册
    # cancel_event + 启动 _run daemon 线程（复用编排器既有的线程注册表/孤儿回收/取消机制）。
    from app.models.task import TaskManager

    task_id = TaskManager().create_task(
        task_type="pipeline:full:batch_question",
        metadata={
            "pipeline_id": new_id,
            "base_pipeline_id": base_pipeline_id,
            "batch_id": batch_id,
            "shared_simulation": bool(shared_simulation),
        },
    )
    new_state.task_id = task_id
    new_state.status = "running"
    PipelineManager.save(new_state)

    with PipelineOrchestrator._lifecycle_lock:
        PipelineOrchestrator._cancel_events[new_id] = threading.Event()
        t = threading.Thread(
            target=PipelineOrchestrator._run,
            args=(new_state,),
            name=f"pipeline-batch-{new_id}",
            daemon=True,
        )
        PipelineOrchestrator._threads[new_id] = t
        t.start()
    logger.info(
        "[%s] 批次问题分叉自 %s（batch=%s, shared_sim=%s），复用图谱 %s",
        new_id, base_pipeline_id, batch_id, shared_simulation, base_state.graph_id,
    )
    return new_state


# ---------------------------------------------------------------------------
# 启动一个批次
# ---------------------------------------------------------------------------


def start_batch(
    prompts: list[str],
    *,
    mode: str = "full",
    project_name: Optional[str] = None,
    depth: Optional[str] = None,
    max_rounds: Optional[int] = None,
    language: Optional[str] = None,
    model: Optional[str] = None,
    shared_simulation: Optional[bool] = None,
    cancel: Optional[threading.Event] = None,
) -> dict[str, Any]:
    """围绕同一事件，对一篮子相关问题启动一个批次（I-9-3）。

    流程：preflight 一次 → prompts[0] 作为**锚点**跑一条普通 full 管线 → 等其图谱完成
    → prompts[1..] 各 fork_question() 复用同一图谱。返回批次记录（含子管线 id 列表）。

    本函数会**阻塞到所有子问题都被启动**（锚点图谱完成后才能分叉），但不等子管线全部跑完；
    各子管线在后台 daemon 线程继续，可用 batch_status() 轮询聚合进度/结果。

    OPTIONAL-DEGRADE：shared_simulation 缺省读 Config.BATCH_SHARED_SIMULATION（默认 False）；
    分叉并发上限读 Config.BATCH_MAX_FANOUT（默认 8），超出的问题被记入 record['skipped']
    并发警告，绝不静默丢弃。

    Args:
        prompts: 至少一个 prompt；第 0 个是锚点。
        mode: 目前仅支持 'full'（批次复用以图谱为核心，research_only 无图可分叉）。
        其余参数：透传给锚点 PipelineOrchestrator.start()。
        shared_simulation: None=用 Config 默认；True/False 显式覆盖。
        cancel: 可选取消事件（等待锚点图谱时检查）。

    Returns:
        批次记录 dict（已落盘）。
    Raises:
        ValueError: prompts 为空 / mode 非 full。
        RuntimeError: preflight 未过 / 锚点建图失败。
    """
    cleaned = [str(p).strip() for p in (prompts or []) if str(p).strip()]
    if not cleaned:
        raise ValueError("prompts 不能为空")
    if mode != "full":
        raise ValueError("批次仅支持 mode=full（复用以图谱为核心，research_only 无图可分叉）")

    if shared_simulation is None:
        shared_simulation = bool(getattr(Config, "BATCH_SHARED_SIMULATION", False))
    max_fanout = int(getattr(Config, "BATCH_MAX_FANOUT", 8) or 8)
    if max_fanout < 1:
        max_fanout = 1

    # 起飞前体检一次（与单 prompt 路径相同的廉价本地检查），避免锚点研究跑完才暴露配置错误。
    preflight_errors = preflight_pipeline(mode=mode, model=model)
    if preflight_errors:
        raise RuntimeError("启动前检查未通过：\n" + "\n".join(f"• {e}" for e in preflight_errors))

    batch_id = BatchManager.new_id()
    anchor_prompt = cleaned[0]
    extra_prompts = cleaned[1:]

    # 分叉并发上限：超出 max_fanout 的额外问题不启动，记入 skipped（绝不静默丢弃）。
    skipped: list[dict[str, Any]] = []
    if len(extra_prompts) > max_fanout:
        for p in extra_prompts[max_fanout:]:
            skipped.append({"prompt": p, "reason": f"超出 BATCH_MAX_FANOUT={max_fanout}"})
        logger.warning(
            "[%s] 批次问题数 %d 超出 BATCH_MAX_FANOUT=%d，截断 %d 个（记入 skipped）",
            batch_id, len(extra_prompts), max_fanout, len(skipped),
        )
        extra_prompts = extra_prompts[:max_fanout]

    # 1) 锚点：一条普通 full 管线（research+ontology+graph 在此一次性产出）。
    anchor_state = PipelineOrchestrator.start(
        prompt=anchor_prompt,
        mode="full",
        project_name=project_name,
        depth=depth,
        max_rounds=max_rounds,
        language=language,
        model=model,
    )
    # 锚点 options 里也打上 batch_id（供前端把锚点与子问题归到一组）。
    try:
        _ad = PipelineManager.load(anchor_state.pipeline_id)
        if _ad is not None:
            _as = PipelineState.from_dict(_ad)
            _as.options["batch_id"] = batch_id
            _as.options["batch_role"] = "anchor"
            PipelineManager.save(_as)
    except Exception:  # noqa: BLE001 — 打标失败不影响批次本体
        logger.warning("[%s] 给锚点管线打 batch_id 失败（忽略）", batch_id, exc_info=True)

    record: dict[str, Any] = {
        "batch_id": batch_id,
        "status": "preparing",  # preparing → running → completed/failed（聚合自子管线）
        "anchor_prompt": anchor_prompt,
        "anchor_pipeline_id": anchor_state.pipeline_id,
        "shared_simulation": bool(shared_simulation),
        "max_fanout": max_fanout,
        "created_at": _utcnow(),
        "options": {
            "depth": depth, "max_rounds": max_rounds,
            "language": language, "model": model, "project_name": project_name,
        },
        # children：每个元素 {prompt, pipeline_id, role}，锚点也算一个 child（role=anchor）。
        "children": [
            {"prompt": anchor_prompt, "pipeline_id": anchor_state.pipeline_id, "role": "anchor"},
        ],
        "skipped": skipped,
        "errors": [],
    }
    BatchManager.save(record)

    # 2) 等锚点图谱完成（共享复用前提）。失败则标记批次失败并把锚点错误透传出去。
    try:
        _wait_for_graph(anchor_state.pipeline_id, cancel=cancel)
    except RuntimeError as e:
        record["status"] = "failed"
        record["errors"].append(str(e))
        BatchManager.save(record)
        raise

    # shared_simulation 还需要等锚点把模拟也跑完（才有 simulation_id 可共用）。
    if shared_simulation and extra_prompts:
        try:
            _wait_for_simulation(anchor_state.pipeline_id, cancel=cancel)
        except RuntimeError as e:
            # 模拟没跑通则降级为非共享：各问题自己跑模拟（仍共享图谱），别让整批失败。
            logger.warning(
                "[%s] 锚点模拟未就绪（%s），shared_simulation 降级为每问题独立模拟",
                batch_id, e,
            )
            record["errors"].append(f"shared_simulation 降级：{e}")
            shared_simulation = False
            record["shared_simulation"] = False
            BatchManager.save(record)

    # 3) 逐个分叉其余问题（复用同一图谱）。每个分叉失败只记错，不影响其它问题。
    record["status"] = "running"
    for q in extra_prompts:
        try:
            child = fork_question(
                anchor_state.pipeline_id,
                q,
                batch_id=batch_id,
                shared_simulation=shared_simulation,
                max_rounds=max_rounds,
            )
            record["children"].append(
                {"prompt": q, "pipeline_id": child.pipeline_id, "role": "question"}
            )
        except Exception as e:  # noqa: BLE001 — 单个问题分叉失败不拖垮整批
            logger.error("[%s] 分叉问题失败（%s）: %s", batch_id, q[:60], e, exc_info=True)
            record["errors"].append(f"分叉失败「{q[:60]}」：{e}")
        BatchManager.save(record)

    logger.info(
        "[%s] 批次已启动：锚点 %s + %d 个分叉问题（shared_sim=%s）",
        batch_id, anchor_state.pipeline_id, len(extra_prompts), shared_simulation,
    )
    return record


def _wait_for_simulation(pipeline_id: str, cancel: Optional[threading.Event] = None) -> dict[str, Any]:
    """阻塞轮询，直到锚点 RUN 阶段完成（shared_simulation 复用前提）。

    Raises:
        RuntimeError: 锚点在模拟完成前进入终态或记录丢失。
    """
    _deadline = time.monotonic() + _WAIT_TIMEOUT_S if _WAIT_TIMEOUT_S > 0 else None
    while True:
        if cancel is not None and cancel.is_set():
            raise RuntimeError("批次已被取消（等待锚点模拟阶段时）")
        if _deadline is not None and time.monotonic() > _deadline:
            raise RuntimeError(f"等待锚点模拟阶段超时（>{int(_WAIT_TIMEOUT_S)}s，疑似卡死）")
        data = PipelineManager.load(pipeline_id)
        if data is None:
            raise RuntimeError(f"锚点管线 {pipeline_id} 记录丢失")
        stages = data.get("stages") or {}
        run_done = (
            isinstance(stages.get(STAGE_RUN), dict)
            and stages[STAGE_RUN].get("status") == "completed"
        )
        if run_done and data.get("simulation_id"):
            return data
        status = data.get("status")
        if status in ("failed", "cancelled") and not run_done:
            raise RuntimeError(f"锚点管线在模拟完成前进入 {status}：{data.get('error') or status}")
        if status == "completed" and not run_done:
            raise RuntimeError("锚点管线已完成但未产出可复用模拟")
        time.sleep(_POLL_INTERVAL_S)


# ---------------------------------------------------------------------------
# 批次状态聚合 + 组合视图（共享的预测篮子）
# ---------------------------------------------------------------------------


def _child_view(child: dict[str, Any]) -> dict[str, Any]:
    """读取单个子管线的当前状态 + 可选 forecast.json，组装一条 child 视图。"""
    pid = child.get("pipeline_id")
    out: dict[str, Any] = {
        "prompt": child.get("prompt"),
        "pipeline_id": pid,
        "role": child.get("role"),
        "status": None,
        "global_progress": None,
        "current_stage": None,
        "report_id": None,
        "simulation_id": None,
        "forecast": None,
    }
    if not pid:
        return out
    data = PipelineManager.load(pid)
    if not data:
        out["status"] = "missing"
        return out
    out["status"] = data.get("status")
    out["global_progress"] = data.get("global_progress")
    out["current_stage"] = data.get("current_stage")
    out["report_id"] = data.get("report_id")
    out["simulation_id"] = data.get("simulation_id")
    # I-9-3 ↔ 结构化预测：每个子问题完成后写出自己的 forecast.json（report 阶段，
    # REPORT_STRUCTURED_FORECAST 开启时）。读到即纳入组合视图，缺失则该问题不参与聚合。
    rid = data.get("report_id")
    if rid:
        fpath = os.path.join(ReportManager._get_report_folder(rid), "forecast.json")
        if os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    out["forecast"] = json.load(f)
            except (OSError, json.JSONDecodeError):
                out["forecast"] = None
    return out


def _aggregate_status(child_views: list[dict[str, Any]]) -> str:
    """从子管线状态聚合出批次状态。

    全部 completed → completed；任一 running/preparing → running；
    否则（全终态但含失败/取消）→ partial（部分问题失败，但批次本身已结束推进）。
    """
    if not child_views:
        return "empty"
    statuses = [c.get("status") for c in child_views]
    if any(s in ("running", "preparing", None) for s in statuses):
        return "running"
    if all(s == "completed" for s in statuses):
        return "completed"
    return "partial"


def batch_status(batch_id: str) -> Optional[dict[str, Any]]:
    """聚合批次下所有子管线的状态，并对已出 forecast 的问题给出组合视图。

    组合视图（``combined.ensemble``）用 ensemble.aggregate_forecasts 把各问题的结构化预测
    汇成一个跨问题的对照——因为所有问题锚定**同一份证据/图谱**，这些预测内部可比。仅当
    至少有一个子问题产出了 forecast.json 时才有 ensemble；否则为 None（仍返回逐问题进度）。

    Returns:
        批次视图 dict（含逐问题状态 + 组合视图）；批次不存在返回 None。
    """
    record = BatchManager.load(batch_id)
    if record is None:
        return None
    child_views = [_child_view(c) for c in (record.get("children") or [])]
    agg_status = _aggregate_status(child_views)

    # 把聚合出的状态回写记录（让 list 视图也能看到最新批次状态，幂等）。
    if record.get("status") not in ("failed",) and record.get("status") != agg_status:
        record["status"] = agg_status
        try:
            BatchManager.save(record)
        except Exception:  # noqa: BLE001 — 回写失败不影响读取
            pass

    forecasts = [c["forecast"] for c in child_views if isinstance(c.get("forecast"), dict)]
    ensemble = aggregate_forecasts(forecasts) if forecasts else None

    return {
        "batch_id": batch_id,
        "status": agg_status,
        "anchor_prompt": record.get("anchor_prompt"),
        "anchor_pipeline_id": record.get("anchor_pipeline_id"),
        "shared_simulation": record.get("shared_simulation"),
        "created_at": record.get("created_at"),
        "n_questions": len(child_views),
        "n_completed": sum(1 for c in child_views if c.get("status") == "completed"),
        "children": child_views,
        "skipped": record.get("skipped") or [],
        "errors": record.get("errors") or [],
        "combined": {
            "n_forecasts": len(forecasts),
            "ensemble": ensemble,
        },
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_run(args: argparse.Namespace) -> int:
    prompts = list(args.prompt or [])
    if args.prompts_file:
        try:
            with open(args.prompts_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        prompts.append(line)
        except OSError as e:
            print(f"读取 --prompts-file 失败: {e}", file=sys.stderr)
            return 2
    if not prompts:
        print("至少需要一个 --prompt（或 --prompts-file）", file=sys.stderr)
        return 2

    shared = True if args.shared_simulation else None  # None → 用 Config 默认
    try:
        record = start_batch(
            prompts,
            project_name=args.project_name,
            depth=args.depth,
            max_rounds=args.max_rounds,
            language=args.language,
            model=args.model,
            shared_simulation=shared,
        )
    except (ValueError, RuntimeError) as e:
        print(f"启动批次失败: {e}", file=sys.stderr)
        return 1

    batch_id = record["batch_id"]
    if args.json:
        print(json.dumps(record, ensure_ascii=False, indent=2))
    else:
        print(f"✓ 批次已启动: {batch_id}")
        print(f"  锚点: {record['anchor_pipeline_id']}  «{record['anchor_prompt'][:70]}»")
        for c in record["children"][1:]:
            print(f"  问题: {c['pipeline_id']}  «{c['prompt'][:70]}»")
        if record.get("skipped"):
            print(f"  ⚠️  跳过 {len(record['skipped'])} 个（超出 BATCH_MAX_FANOUT）")
        if record.get("errors"):
            print(f"  ⚠️  {len(record['errors'])} 个分叉错误")
        print(f"\n用 `status {batch_id}` 查看进度与组合预测。")

    if args.wait:
        return _wait_and_report(batch_id, as_json=args.json)
    return 0


def _wait_and_report(batch_id: str, *, as_json: bool, poll_s: float = 10.0) -> int:
    """阻塞轮询直到批次进入终态（completed/partial），打印最终聚合视图。"""
    while True:
        view = batch_status(batch_id)
        if view is None:
            print(f"批次不存在: {batch_id}", file=sys.stderr)
            return 1
        if view["status"] in ("completed", "partial"):
            break
        time.sleep(poll_s)
    if as_json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        _print_status(view)
    return 0 if view["status"] == "completed" else 1


def _cmd_status(args: argparse.Namespace) -> int:
    view = batch_status(args.batch_id)
    if view is None:
        print(f"批次不存在: {args.batch_id}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(view, ensure_ascii=False, indent=2))
    else:
        _print_status(view)
    return 0


def _print_status(view: dict[str, Any]) -> None:
    print(f"批次 {view['batch_id']}  状态={view['status']}  "
          f"完成 {view['n_completed']}/{view['n_questions']}  "
          f"shared_sim={view['shared_simulation']}")
    print(f"  锚点: «{(view.get('anchor_prompt') or '')[:70]}»")
    for c in view["children"]:
        prog = c.get("global_progress")
        prog_s = f"{prog}%" if prog is not None else "-"
        print(f"  [{c.get('status') or '?':9}] {prog_s:>4} {c.get('role') or '':8} "
              f"{c.get('pipeline_id')}  «{(c.get('prompt') or '')[:55]}»")
    combined = view.get("combined") or {}
    ens = combined.get("ensemble")
    if ens and ens.get("scenarios"):
        print(f"\n  组合预测（{combined.get('n_forecasts')} 份，agreement="
              f"{ens.get('agreement')}）:")
        for s in ens["scenarios"]:
            print(f"    - {s.get('name')}: mean={s.get('mean_probability')} "
                  f"±{s.get('stdev')} [{s.get('min')},{s.get('max')}] support={s.get('support')}")
    if view.get("skipped"):
        print(f"\n  跳过 {len(view['skipped'])} 个问题（超出并发上限）")
    if view.get("errors"):
        print("\n  错误:")
        for err in view["errors"]:
            print(f"    - {err}")


def _cmd_list(args: argparse.Namespace) -> int:
    batches = BatchManager.list_batches()
    if args.json:
        print(json.dumps(batches, ensure_ascii=False, indent=2))
    else:
        if not batches:
            print("（暂无批次）")
        for b in batches:
            print(f"{b['batch_id']}  {b.get('status') or '?':10} "
                  f"{b.get('n_questions')}问  shared_sim={b.get('shared_simulation')}  "
                  f"«{(b.get('anchor_prompt') or '')[:60]}»")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="batch_runs.py",
        description="多问题批次运行：共享研究/图谱，N 个相关预测约 1x 成本（I-9-3）。",
    )
    sub = ap.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="启动一个批次")
    p_run.add_argument("--prompt", action="append", default=[],
                       help="一个问题（可重复多次）；第一个是锚点")
    p_run.add_argument("--prompts-file", help="每行一个问题的文本文件（# 开头为注释）")
    p_run.add_argument("--project-name", help="可选项目名")
    p_run.add_argument("--depth", choices=["quick", "standard", "deep"],
                       help="研究深度（缺省用 Config 默认）")
    p_run.add_argument("--max-rounds", type=int, help="OASIS 最大轮数（截断模拟）")
    p_run.add_argument("--language", choices=["Chinese", "English", "auto"],
                       help="研究语言（缺省用 Config 默认）")
    p_run.add_argument("--model", help="研究模型覆盖（缺省用 Config 默认）")
    p_run.add_argument("--shared-simulation", action="store_true",
                       help="所有问题共用锚点的那次 OASIS 模拟（最省，只各跑报告）")
    p_run.add_argument("--wait", action="store_true",
                       help="阻塞直到批次跑完并打印组合预测")
    p_run.add_argument("--json", action="store_true", help="输出 JSON")
    p_run.set_defaults(func=_cmd_run)

    p_status = sub.add_parser("status", help="查看批次状态与组合预测")
    p_status.add_argument("batch_id")
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=_cmd_status)

    p_list = sub.add_parser("list", help="列出所有批次")
    p_list.add_argument("--json", action="store_true")
    p_list.set_defaults(func=_cmd_list)

    return ap


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    # language=auto → 空串（与 api/research.py 约定一致：不传 --target-language，模型自选）。
    if getattr(args, "language", None) == "auto":
        args.language = ""
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
