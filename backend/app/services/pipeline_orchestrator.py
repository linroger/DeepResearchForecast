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
import copy
import glob
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from ..config import Config
from ..config_audit import ConfigurationError
from ..models.project import ProjectManager, ProjectStatus
from ..models.task import TaskManager
from ..services.hindcast_policy import (
    HINDCAST_POLICY_OPTION,
    PIT_RESEARCH_ENV_PREFIX,
    as_of_enforcement_record,
    capture_hindcast_policy_v1,
    hindcast_policy,
    pit_research_env,
)
from ..services.graph_builder import (
    GraphBuilderService,
    build_actor_graph_seed_manifest,
)
from ..services.actor_role_prompt import (
    delimit_untrusted_research_text,
    sanitize_untrusted_research_text,
)
from ..services.ontology_generator import OntologyGenerator
from ..services.report_agent import ReportAgent, ReportManager, ReportStatus
from ..services.research_progress import (
    ResearchProgressEstimator,
    aggregate_parallel_progress,
)
from ..services import backbone_sensitivity, run_shape
from ..services.simulation_manager import SimulationManager, SimulationStatus
from ..services.simulation_runner import RunnerStatus, SimulationRunner
from ..services.text_processor import TextProcessor
from ..services.zep_graph_memory_updater import ZepGraphMemoryManager
from ..utils.actors import (
    REL_LABEL,
    extract_relationship_rows,
    normalize_name,
    situation_brief,
    situation_brief_block,
    valid_scenario_distribution,
)
from ..utils.canonical_json import canonical_json_sha256
from ..utils.dates import date_period, parse_as_of
from ..utils.logger import get_logger
from ..utils import model_provenance

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

# EVAL-17: LLMMeter band (not a pipeline stage) for the simulation-subprocess spend of the
# extra ensemble seeds. The seeds' prepare/persona calls meter under "ensemble"; their
# ReportAgent calls meter under "report" (ReportAgent.generate_report sets its own stage).
SIM_METER_STAGE_ENSEMBLE = "ensemble_sim"
# EVAL-17: per-simulation exactly-once sim-meter markers in state.options:
# {simulation_id: {meter_run_token, stage, recorded_at}}.
SIM_METER_MARKERS_OPTION = "sim_llm_telemetry_recorded_by_sim"
# Pre-EVAL-17 single-slot marker {simulation_id, meter_run_token, recorded_at}: honoured on
# read, migrated into the map, and still mirrored for the main run's recordings.
SIM_METER_LEGACY_MARKER_OPTION = "sim_llm_telemetry_recorded"

ACTOR_INTELLIGENCE_SCHEMA_VERSION = "actor-intelligence/v1"
ACTOR_INTELLIGENCE_POLICY_VERSION = "actor-intelligence-policy/v1"
ACTOR_INTELLIGENCE_LINEAGE_FILENAME = "actor_intelligence_lineage.json"
ACTOR_INTELLIGENCE_LINEAGE_SCHEMA_VERSION = "actor-artifact-lineage/v1"
ACTOR_GRAPH_SEED_MANIFEST_FILENAME = "actor_graph_seed_manifest.json"
ACTOR_GRAPH_SEED_MANIFEST_SCHEMA_VERSION = "actor-graph-seed-manifest/v1"
ACTOR_GRAPH_SEED_READBACK_SCHEMA_VERSION = "actor-graph-seed-readback/v1"
ACTOR_INTELLIGENCE_DIMENSIONS = (
    "identity_history",
    "values_worldview",
    "incentives",
    "motivations",
    "capabilities",
    "constraints",
    "operational_preferences",
    "alliances",
    "opponents_competitors",
    "decision_rights_process_triggers",
    "current_actions",
    "future_plans",
    "investments_capital_allocation",
    "track_record",
    "likely_actions",
    "red_lines",
    "knowledge_state",
)
_ACTOR_BEHAVIOR_READY_FAMILIES = {
    "identity_history": ("identity_history",),
    "incentives_motivations_values": (
        "values_worldview", "incentives", "motivations",
    ),
    "capabilities_constraints": ("capabilities", "constraints"),
    "actions_plans_investments": (
        "current_actions", "future_plans", "investments_capital_allocation",
    ),
    "decision_likely_actions_red_lines": (
        "decision_rights_process_triggers", "likely_actions", "red_lines",
    ),
}
_ACTOR_SEARCH_RESULT_RECEIPT_SCHEMA = "stage1-search-result-receipt/v1"
_ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT = (
    "[unsafe instruction-like evidence text omitted]"
)
_ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS = (
    re.compile(
        r"\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be|"
        r"assume\s+the\s+role|new\s+role)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:system|developer|assistant)\s+(?:message|prompt|"
        r"instructions?|role|administrator)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"<\s*/?\s*(?:system|developer|assistant|tool|user)\b|"
        r"<\|\s*(?:system|developer|assistant|tool|user)\s*\|>",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:ignore|disregard|override|forget|bypass|do\s+not\s+follow)\b"
        r"[^.?\n]{0,400}\b(?:instructions?|prompts?|brief|policy|message|"
        r"system|developer)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:follow|obey)\b[^.!?\n]{0,300}\b(?:developer|system|hidden)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:reveal|exfiltrate|disclose|leak|print|output|show)\b"
        r"[^.!?\n]{0,100}\b(?:secrets?|credentials?|passwords?|api\s*keys?|"
        r"chain[- ]of[- ]thought|hidden\s+(?:prompt|instructions?)|system\s+prompt)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:call|invoke|run|execute|use)\b[^.!?\n]{0,70}"
        r"\b(?:tools?|shell|terminal|commands?|browser)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bwhen\s+(?:generating|writing|creating|answering|responding|"
        r"simulating)\b[^.!?\n]{0,120}\b(?:write|say|respond|output|return|"
        r"claim|state|include|omit)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:^|[.!?]\s+)(?:write|say|respond|output|return|claim|state)\s+"
        r"(?:only|exactly|that)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(?:begin|end)\s+untrusted\b", re.IGNORECASE),
    re.compile(
        r"(?:^|\s)#{1,6}\s*(?:system|developer|assistant)\b",
        re.IGNORECASE,
    ),
)
_ACTOR_UNSAFE_EVIDENCE_CONTROL_FRAGMENT_PATTERN = re.compile(
    r"\b(?:ignore|disregard|override|forget|bypass|follow|obey|reveal|"
    r"exfiltrate|disclose|leak|print|output|show|call|invoke|run|execute|"
    r"system|developer|assistant|hidden)\b",
    re.IGNORECASE,
)
_ACTOR_STAGE1_BLOCK_SENTINEL_RE = re.compile(
    r"^STAGE1BLOCKBOUNDARY[0-9A-F]{12}$"
)
_ACTOR_INTELLIGENCE_QUALIFIER_KEYS = (
    "conditions", "amount", "unit", "scale", "type", "action_type",
    "strategic_purpose", "objective", "purpose", "basis", "leverage",
    "project", "program", "product", "asset", "counterparty", "geography",
    "allocation_type", "contingencies", "driver", "gains_if", "loses_if",
    "decision_kind", "trigger", "authority", "decision_maker",
    "preference_kind", "polarity", "subject", "direction", "intensity",
    "strength", "limits", "available", "revealed_by",
)
_ACTOR_RELATIONSHIP_CAUSAL_ATTRIBUTE_KEYS = (
    "valence",
    "polarity",
    "sign",
    "strength",
    "grade",
    "since",
    "until",
    "lag",
)
_ACTOR_KNOWLEDGE_VISIBILITY_VALUES = {
    "public", "actor_known", "known_to_actor", "actor_internal",
    "internal_to_actor", "private_actor_knowledge", "research_only",
    "analyst_only", "not_known_to_actor", "unknown",
}
_ACTOR_DOSSIER_LEDGER_RE = re.compile(
    r"<!--\s*ACTOR_INTELLIGENCE_LEDGER_V1\s+(\{.*?\})\s*-->",
    re.DOTALL,
)

# I-4-4: pipeline_state.json 的 schema 版本。每次形状演进 +1，并在 _MIGRATIONS 注册
# 一个把「上一版 → 本版」就地补齐的纯函数。v1 = 历史无 schema_version 字段的状态文件。
# v2 = 引入显式 schema_version + run.json manifest 指针（artifacts['run_manifest']）。
PIPELINE_SCHEMA_VERSION = 2


class PipelineCancelled(BaseException):
    """用户主动取消管线（与失败区分开：不是错误，是决定）。

    继承 BaseException 而非 Exception：管线各阶段（章节级容错、模拟准备等）布有
    大量 ``except Exception`` 的纵深防御层，取消信号必须穿透它们直达 ``_run`` 的
    取消处理器——否则取消会被降级成"占位符章节"或"阶段失败"，状态被误标。
    （与 KeyboardInterrupt 同类的控制流信号，不是可恢复错误。）
    """


class ProviderOutageHalt(BaseException):
    """DEFECT-1：LLM 提供方疑似全面中断时的运行级止损信号（run-level outage halt）。

    2026-07-08 复盘：提供方额度耗尽后，一条管线以最高 231 错误/分钟连续锤了 ~26 小时
    （10,584 行 ERROR）；07-15 又出现 8,856 次重试告警 + 4,117 次回退失败，报告阶段
    只做「单报告提前中止」然后继续下一个报告，从未有任何运行级止损。本信号由
    ``_RunOutageBreaker``（连续 N 次提供方级失败、零成功间隔）触发，在进度回调 /
    阶段边界抬升。

    与 :class:`PipelineCancelled` 同理继承 BaseException：必须穿透各阶段布设的
    ``except Exception`` 纵深防御层（否则会被降级成占位符章节/单阶段失败），直达
    ``_run`` 的专用处理器——该处理器把管线落成 status='failed' 这一**既有**可恢复
    检查点终态（`resume()` 会复用已完成阶段与研究断点原地续跑），不发明并行状态机。
    """


class IncompatiblePipelineSchema(RuntimeError):
    """I-4-4: 试图操作一个由更新版代码写出的 pipeline_state.json。

    严格模式（Config.PIPELINE_STRICT_SCHEMA，默认 True）下，对 resume/continue/fork
    等会重写状态文件的操作抛出，避免旧二进制按旧语义解析丢字段、再落盘降级覆写。
    API 层应把它映射成 409 Conflict（而非 500），并提示「升级后端或开启
    PIPELINE_STRICT_SCHEMA=false 应急旁路」。
    """

    def __init__(self, pipeline_id: str, file_version: int):
        self.pipeline_id = pipeline_id
        self.file_version = file_version
        super().__init__(
            f"管线 {pipeline_id} 的状态文件 schema 版本为 {file_version}，"
            f"高于当前后端支持的 {PIPELINE_SCHEMA_VERSION}。"
            "请升级后端，或在 .env 设 PIPELINE_STRICT_SCHEMA=false 应急旁路（可能丢失新字段）。"
        )


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# I-4-1: 进程级 boot id（每次后端进程启动唯一）。配合持久化的 owner_pid，让
# reconcile_orphans 能区分「本进程拥有的在飞管线」与「上一进程/别的 worker 遗留的孤儿」，
# 而不再仅凭 in-process _threads 判定（多 worker / 重启后 _threads 会丢失真相）。
_BOOT_ID = uuid.uuid4().hex


def _parse_iso(ts: Optional[str]) -> Optional[datetime]:
    """I-4-1/I-5-6: 解析 _utcnow() 写出的 ISO 时间戳；解析失败返回 None（best-effort）。"""
    if not ts or not isinstance(ts, str):
        return None
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None
    # 旧文件可能写的是 naive 时间戳；统一补成 UTC，使与 _utcnow() 的 aware 比较安全。
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _age_seconds(ts: Optional[str]) -> Optional[float]:
    """I-4-1/I-5-6: 自 ts 起经过的秒数（now-ts）；ts 不可解析返回 None。"""
    dt = _parse_iso(ts)
    if dt is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds())


def _pid_alive(pid: Optional[int]) -> bool:
    """I-4-1: 进程是否存活（os.kill(pid, 0) 探活，不依赖第三方 psutil）。

    pid 无效 / 已退出 → False；权限不足（EPERM）说明进程确实存在但非本用户 → 视为存活，
    保守地避免把别人的存活进程误判为死。
    """
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


# ---------------------------------------------------------------------------
# DEFECT-1：run 级提供方中断熔断器（run-level provider-outage breaker）
#
# llm_client 自 iteration 2 起在「主提供方熔断冷却 + 回退不可用」时让 chat() 立即抛出
# （不再烧 3 次退避重试 + 二次回退），编排器因此能看到一条快速、可分类的失败流。这里
# 把它聚合成运行级判定：连续 N 次提供方级失败（配额/连接/认证）且零成功间隔 → 置
# tripped；探针对该 run 的后续 LLM 调用直接快速失败（不再发起任何真实调用），编排器在
# 进度回调（_make_stage_updater.update，即各阶段的高频取消点）抬升 ProviderOutageHalt，
# 经 _run 的专用处理器落成 status='failed' 的既有可恢复检查点态。
#
# 作用域：编排器进程内驱动的阶段（ontology/graph/prepare/report + 进程内的研究合并
# 调用）。研究/模拟子进程有自己的重试环，不做进程注入——只在编排器边界按「阶段级失败」
# 计数（_note_provider_stage_failure：并行研究轨失败、仅综合恢复尝试失败）。
# ---------------------------------------------------------------------------

_PROVIDER_OUTAGE_FAST_FAIL_PREFIX = "LLM_OUTAGE_HALT"

# 连接类中断的文本指纹（openai SDK / httpx / CLI 超时的常见形态）。仅用于分类已发生的
# LLM 调用异常，宽松一点是安全的：误判的代价只是向连续计数 +1，任一成功即清零。
_PROVIDER_OUTAGE_CONNECTION_MARKERS = (
    "apiconnectionerror", "apitimeouterror", "connecterror", "connectionerror",
    "connection refused", "connection reset", "connection aborted",
    "connection error", "econnrefused", "econnreset", "getaddrinfo",
    "nodename nor servname", "name or service not known",
    "temporary failure in name resolution", "remotedisconnected",
    "server disconnected", "network is unreachable", "timed out", "sslerror",
)


def _outage_halt_threshold() -> int:
    """DEFECT-1 旋钮 LLM_OUTAGE_HALT_CONSECUTIVE（默认 10；≤0 关闭）。

    本迭代 config.py 归另一 agent 所有，故按跨 agent 约定读取：env 显式非零值优先，
    否则回退 ``Config.LLM_OUTAGE_HALT_CONSECUTIVE``，属性缺失时用内建默认 10。
    显式关闭：env 置负数，或 config 里设 0（env '0' 会按 ``int(x or 0) or fallback``
    的既定折叠语义落回 config/默认）。
    """
    try:
        env_val = int(os.environ.get("LLM_OUTAGE_HALT_CONSECUTIVE", "") or 0)
    except (TypeError, ValueError):
        env_val = 0
    if env_val:
        return env_val
    try:
        return int(getattr(Config, "LLM_OUTAGE_HALT_CONSECUTIVE", 10) or 0)
    except (TypeError, ValueError):
        return 10


def _classify_provider_outage(exc: Any) -> Optional[str]:
    """把一次 LLM 调用/研究阶段失败分类为「提供方级中断」或 None（不计数）。

    提供方级 = 配额/限流（llm_client._is_quota）、确定性认证失败
    （llm_client._is_deterministic_auth_error）、连接/传输失败、以及 llm_client 的
    双通道快失败（主提供方熔断冷却 + 回退不可用）。内容审查（422）、JSON 解析、
    预算护栏（BudgetExceeded）、取消信号等都不是「提供方中断」——既不计数也不清零。
    """
    if isinstance(exc, (PipelineCancelled, ProviderOutageHalt)):
        return None
    try:
        from ..utils.telemetry import BudgetExceeded
        if isinstance(exc, BudgetExceeded):
            return None
    except Exception:  # noqa: BLE001 — telemetry 不可导入时继续按文本分类
        pass
    text = str(exc or "")
    if not text.strip():
        return None
    if text.startswith(_PROVIDER_OUTAGE_FAST_FAIL_PREFIX):
        return None  # 本熔断器自己的快失败信号，不得自我喂养
    _is_quota = _is_auth = None
    try:
        from ..utils.llm_client import (
            _is_deterministic_auth_error as _is_auth,
            _is_quota,
        )
    except Exception:  # noqa: BLE001 — 帮手不可导入时退化为本地指纹
        pass
    if _is_auth is not None and _is_auth(exc):
        return "auth"
    # llm_client 双通道中断快失败（消息含 '422/429 熔断冷却' → _is_quota 也会命中，
    # 但显式归类更可读）。
    low = text.casefold()
    if "熔断冷却" in text or "circuit-breaker" in low or "回退提供方不可用" in text:
        return "circuit_breaker"
    if _is_quota is not None and _is_quota(exc):
        return "quota"
    if isinstance(exc, BaseException):
        tname = type(exc).__name__.casefold()
        if "connection" in tname or "timeout" in tname:
            return "connection"
    if any(marker in low for marker in _PROVIDER_OUTAGE_CONNECTION_MARKERS):
        return "connection"
    return None


class _RunOutageBreaker:
    """单条管线的「连续提供方级 LLM 失败」熔断器（线程安全）。

    计数语义：提供方级失败 +1；任一成功清零；非提供方级失败（内容审查、解析错误等）
    既不计数也不清零——它们不是「中间成功」。达到阈值置 ``tripped``（保留首次触发时的
    证据，不再累计），此后探针对该 run 的 chat() 直接快速失败。
    """

    def __init__(self, run_id: str, threshold: int) -> None:
        self.run_id = str(run_id)
        self.threshold = max(1, int(threshold))
        self.consecutive = 0
        self.tripped = False
        self.tripped_at: Optional[str] = None
        self.last_reason: Optional[str] = None
        self.last_error: Optional[str] = None
        self._lock = threading.Lock()

    def record_success(self) -> None:
        with self._lock:
            if not self.tripped:
                self.consecutive = 0

    def record_provider_failure(self, exc: Any, reason: str) -> bool:
        """记一次已分类的提供方级失败；恰在本次达到阈值时返回 True。"""
        tripped_now = False
        with self._lock:
            if self.tripped:
                return False
            self.consecutive += 1
            self.last_reason = str(reason)
            self.last_error = str(exc or "")[:300]
            if self.consecutive >= self.threshold:
                self.tripped = True
                self.tripped_at = _utcnow()
                tripped_now = True
        if tripped_now:
            logger.error(
                "[%s] 提供方中断熔断触发：连续 %d 次提供方级 LLM 失败（%s），"
                "该 run 的后续 LLM 调用将快速失败并在下一进度回调处止损",
                self.run_id, self.consecutive, self.last_reason,
            )
        return tripped_now

    def note_failure(self, exc: Any) -> bool:
        """分类 + 记录一次失败；仅提供方级失败计数。返回是否恰在本次触发。"""
        reason = _classify_provider_outage(exc)
        if reason is None:
            return False
        return self.record_provider_failure(exc, reason)

    def fail_fast_message(self) -> str:
        return (
            f"{_PROVIDER_OUTAGE_FAST_FAIL_PREFIX}: run {self.run_id} 的提供方中断"
            f"熔断已触发（连续 {self.consecutive} 次 {self.last_reason} 类失败），"
            "跳过新的 LLM 调用"
        )

    def halt_message(self) -> str:
        provider = str(getattr(Config, "LLM_PROVIDER", "") or "unknown")
        return (
            f"LLM 提供方疑似全面中断（provider outage: {self.last_reason}）："
            f"主提供方 '{provider}' 连续 {self.consecutive} 次提供方级调用失败、"
            f"零成功间隔（最后错误：{self.last_error}）。管线已止损并保存为可恢复"
            f"检查点（status=failed；已完成阶段与研究断点全部保留）。修复提供方后"
            f"执行 POST /api/research/{self.run_id}/resume 原地续跑。"
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "consecutive_failures": self.consecutive,
                "threshold": self.threshold,
                "tripped": self.tripped,
                "tripped_at": self.tripped_at,
                "reason": self.last_reason,
                "last_error": self.last_error,
            }


_RUN_OUTAGE_LOCK = threading.Lock()
_RUN_OUTAGE_BREAKERS: dict[str, _RunOutageBreaker] = {}


def _register_outage_breaker(run_id: str) -> Optional[_RunOutageBreaker]:
    """为一次管线 attempt 注册新熔断器（旧计数不跨 attempt 遗留）。关闭时返回 None。"""
    threshold = _outage_halt_threshold()
    with _RUN_OUTAGE_LOCK:
        if threshold <= 0:
            _RUN_OUTAGE_BREAKERS.pop(str(run_id), None)
            return None
        breaker = _RunOutageBreaker(str(run_id), threshold)
        _RUN_OUTAGE_BREAKERS[str(run_id)] = breaker
        return breaker


def _outage_breaker_for(run_id: Optional[str]) -> Optional[_RunOutageBreaker]:
    if not run_id:
        return None
    with _RUN_OUTAGE_LOCK:
        return _RUN_OUTAGE_BREAKERS.get(str(run_id))


def _clear_outage_breaker(run_id: str) -> None:
    with _RUN_OUTAGE_LOCK:
        _RUN_OUTAGE_BREAKERS.pop(str(run_id), None)


def _current_outage_breaker() -> Optional[_RunOutageBreaker]:
    """当前线程所属 run 的熔断器。

    归属解析与 FOG-TEL-1 同思路：先取 telemetry 的 run contextvar；工作线程
    （ThreadPoolExecutor 不继承 contextvars）退回「唯一活跃 run」；仍含糊时若注册表
    恰好只有一个熔断器则用它；0 个或 ≥2 个候选 → None（宁可不计数也不跨 run 污染）。
    """
    if not _RUN_OUTAGE_BREAKERS:
        return None
    rid: Optional[str] = None
    try:
        from ..utils.telemetry import active_run_ids, get_run_context
        rid = get_run_context()[0]
        if not rid:
            ids = active_run_ids()
            rid = ids[0] if len(ids) == 1 else None
    except Exception:  # noqa: BLE001 — telemetry 不可用时退回注册表单例判定
        rid = None
    if rid:
        return _outage_breaker_for(rid)
    with _RUN_OUTAGE_LOCK:
        if len(_RUN_OUTAGE_BREAKERS) == 1:
            return next(iter(_RUN_OUTAGE_BREAKERS.values()))
    return None


def _note_provider_stage_failure(run_id: Optional[str], exc: Any) -> None:
    """子进程阶段（研究轨/仅综合恢复）在编排器边界的失败计入运行级熔断。

    研究与模拟子进程有自己的重试环，不做进程注入；编排器观察到的一次「阶段级
    失败」若可分类为提供方级，就向同一熔断器 +1。best-effort：绝不抛。
    """
    try:
        breaker = _outage_breaker_for(run_id)
        if breaker is not None:
            breaker.note_failure(exc)
    except Exception:  # noqa: BLE001 — 计数是观测增益，失败不影响主流程
        pass


_LLM_PROBE_LOCK = threading.Lock()


def _install_llm_outage_probe() -> bool:
    """给 LLMClient.chat 装进程级探针（幂等、自愈）：按 run 计连续提供方级失败。

    探针语义：
    - 当前线程无可归属熔断器（未注册/关闭/归属含糊）或 self 是回退客户端
      （``_is_fallback``，其失败已由外层主调用统一计一次）→ 完全透传，行为不变；
    - 熔断已触发 → 立即抛 RuntimeError（前缀 LLM_OUTAGE_HALT），不发起任何真实调用；
    - 调用成功 → 清零连续计数；失败 → 分类后计数（PipelineCancelled 原样穿透）。

    幂等以函数标记 ``_drf_outage_probe`` 判定（而非进程旗标）：测试环境若有人整体
    monkeypatch 掉 LLMClient.chat，下一次安装会自愈重装。原始实现挂在探针的
    ``_drf_outage_probe_orig`` 上，_uninstall_llm_outage_probe（测试辅助）用它还原。
    """
    with _LLM_PROBE_LOCK:
        try:
            from ..utils.llm_client import LLMClient
        except Exception as exc:  # noqa: BLE001 — llm_client 不可导入时探针缺席
            logger.debug("outage probe: LLMClient 不可导入，跳过安装: %s", exc)
            return False
        if getattr(LLMClient.chat, "_drf_outage_probe", False):
            return True
        orig = LLMClient.chat

        def _outage_probed_chat(self, *args, **kwargs):
            if getattr(self, "_is_fallback", False):
                return orig(self, *args, **kwargs)
            breaker = _current_outage_breaker()
            if breaker is None:
                return orig(self, *args, **kwargs)
            if breaker.tripped:
                raise RuntimeError(breaker.fail_fast_message())
            try:
                result = orig(self, *args, **kwargs)
            except PipelineCancelled:
                raise
            except BaseException as exc:
                breaker.note_failure(exc)
                raise
            breaker.record_success()
            return result

        _outage_probed_chat.__name__ = "chat"
        _outage_probed_chat.__qualname__ = getattr(orig, "__qualname__", "LLMClient.chat")
        _outage_probed_chat.__doc__ = getattr(orig, "__doc__", None)
        _outage_probed_chat._drf_outage_probe = True
        _outage_probed_chat._drf_outage_probe_orig = orig
        LLMClient.chat = _outage_probed_chat
        return True


def _uninstall_llm_outage_probe() -> None:
    """测试辅助：还原 LLMClient.chat（仅当当前实现确为本探针时）。生产不调用。"""
    with _LLM_PROBE_LOCK:
        try:
            from ..utils.llm_client import LLMClient
        except Exception:  # noqa: BLE001
            return
        orig = getattr(LLMClient.chat, "_drf_outage_probe_orig", None)
        if orig is not None:
            LLMClient.chat = orig


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
    # I-4-4: 状态文件 schema 版本（每次落盘写当前版本；load 时按需向前迁移）。
    schema_version: int = PIPELINE_SCHEMA_VERSION
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
    # I-4-1: 拥有该在飞管线的后端进程指纹（owner_pid + owner_boot_id）与按固定壁钟节律刷新的
    # 心跳时间戳。reconcile_orphans 据此把「死管线」与「慢但活的管线」区分开（owner 进程不在/
    # boot_id 不符 且 心跳过期 才回收）。老状态文件缺失 → None，回退到旧的 _threads 判定。
    owner_pid: Optional[int] = None
    owner_boot_id: Optional[str] = None
    heartbeat_at: Optional[str] = None
    # I-5-6: 最近一次进度回调的壁钟时间戳。供状态 API 计算 stale（now-last_progress_at>阈值
    # 即「还在思考」而非「卡死」）。每次 _make_stage_updater.update() 刷新。
    last_progress_at: Optional[str] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_utcnow)
    updated_at: str = field(default_factory=_utcnow)
    options: dict[str, Any] = field(default_factory=dict)
    stages: dict[str, StageState] = field(default_factory=dict)
    # T6.3: 各阶段产物的可深链指针（stage 名 → handoff 相对文件名），随阶段完成填充。
    # 供 GET /api/research/<id>/artifact/<name> + StageTimeline 的「view →」入口。
    artifacts: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineState":  # noqa: C901
        # (Foglamp 1B) safety_policy_v1 rides inside ``options`` — no schema bump.
        stages = {
            name: StageState.from_dict(stage if isinstance(stage, dict) else {"name": name})
            for name, stage in (data.get("stages") or {}).items()
        }
        return cls(
            pipeline_id=data["pipeline_id"],
            prompt=data.get("prompt", ""),
            # I-4-4: 缺失则视为 v1（历史文件）。load() 已在更上游做过迁移，这里只是兜底。
            schema_version=int(data.get("schema_version") or 1),
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
            # I-4-1 / I-5-6: 老状态文件无这些字段 → None（回退旧 _threads 判定 / 无 stale 信息）。
            owner_pid=data.get("owner_pid"),
            owner_boot_id=data.get("owner_boot_id"),
            heartbeat_at=data.get("heartbeat_at"),
            last_progress_at=data.get("last_progress_at"),
            error=data.get("error"),
            created_at=data.get("created_at") or _utcnow(),
            updated_at=data.get("updated_at") or _utcnow(),
            options=data.get("options") or {},
            stages=stages,
            artifacts=data.get("artifacts") or {},  # T6.3: 老状态文件缺失则默认空 dict
        )


# ---------------------------------------------------------------------------
# Foglamp WP1 (slice 1B): compatibility safety-policy pin.
#
# Ambient Config flags changed their defaults in WP1 (graph feedback off,
# single seed, identity extremization, diagnostic simulation effect). A run
# admitted before a service reload must not silently change semantics, and a
# resumed legacy run must never reconstruct UNSAFE semantics (writes into the
# observed graph). The pin is captured at admission into
# ``state.options["safety_policy_v1"]`` and read back via
# ``PipelineOrchestrator._pinned_safety`` at every containment-relevant site.
# WP4 later migrates this temporary pin into the immutable RunSpec.
# ---------------------------------------------------------------------------
SAFETY_POLICY_VERSION = "safety-policy/v1"


def capture_safety_policy_v1(origin: str) -> dict[str, Any]:
    """Snapshot the containment-relevant effective flags at admission time.

    ``origin`` records how the pin came to exist: ``admission`` (new run),
    ``resume_reconstructed_safe`` (legacy run resumed after WP1 — it receives
    the SAFE containment policy, never a reconstruction of unsafe legacy
    ambient defaults; reconstruction of an unsafe policy is not approval to
    resume it) or ``fork_admission`` (INFRA-9: a fork of such an unpinned
    legacy base). The fourth origin, ``fork_inherited``, is never captured
    here: ``fork_safety_policy_v1`` stamps it on a deep copy of the base's pin.
    Every capture snapshots the ambient Config, which is the safe containment
    policy only while the operator keeps the WP1 defaults.

    ``backbone_check`` (EVAL-11) is the opt-in of the shadow cross-backbone spine
    check. Only an ``admission`` or ``fork_admission`` capture snapshots the
    ambient BACKBONE_CHECK_* knobs; any other origin (a legacy resume) records it
    disabled, so a resume never turns the check on from the current environment.
    """
    return {
        "version": SAFETY_POLICY_VERSION,
        "origin": origin,
        "pinned_at": _utcnow(),
        "sim_graph_feedback": bool(getattr(Config, "SIM_GRAPH_FEEDBACK", False)),
        "sim_typed_feedback_edges": bool(getattr(Config, "SIM_TYPED_FEEDBACK_EDGES", False)),
        "sim_interview_graph_feedback": bool(
            getattr(Config, "SIM_INTERVIEW_GRAPH_FEEDBACK", False)),
        "n_forecast_seeds": max(1, int(getattr(Config, "N_FORECAST_SEEDS", 1) or 1)),
        "report_spine_selfconsistency_k": max(
            1, int(getattr(Config, "REPORT_SPINE_SELFCONSISTENCY_K", 1) or 1)),
        "ensemble_extremize_a": float(getattr(Config, "ENSEMBLE_EXTREMIZE_A", 1.0) or 1.0),
        "simulation_forecast_effect": str(
            getattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
            or "diagnostic_only"),
        "backbone_check": (
            backbone_sensitivity.capture_policy(Config)
            if origin in ("admission", "fork_admission")
            else dict(backbone_sensitivity.DISABLED_POLICY)),
    }


def fork_safety_policy_v1(base_options: Any) -> Optional[dict[str, Any]]:
    """INFRA-9: the ``safety_policy_v1`` pin a fork of a base run receives.

    Scenario and batch-question forks reuse the base's research and graph and
    continue its forecast, so they keep the base's containment semantics: a
    deep copy of the base pin with origin ``fork_inherited`` (every other field,
    ``pinned_at`` included, is the base's; the base's own origin stays on the
    base's pin, reachable through the fork's ``base_pipeline_id``). A base
    admitted before the pin existed yields a capture at fork admission (origin
    ``fork_admission``: the current ambient policy, which is the safe policy
    under the default Config, never a reconstruction of the base's unknown
    legacy defaults). Returns None when FORK_INHERIT_SAFETY_POLICY is off; the
    fork then carries no pin and every site reads the ambient Config (legacy).

    Forks share the base's ``graph_id``, so a pin with ``sim_graph_feedback``
    on lets the fork's simulations write into the graph the base and its
    sibling forks read; callers report that with
    ``warn_if_fork_feeds_shared_graph``.
    """
    if not bool(getattr(Config, "FORK_INHERIT_SAFETY_POLICY", True)):
        return None
    base_policy = base_options.get("safety_policy_v1") if isinstance(base_options, dict) else None
    if isinstance(base_policy, dict):
        return {**copy.deepcopy(base_policy), "origin": "fork_inherited"}
    return capture_safety_policy_v1("fork_admission")


def warn_if_fork_feeds_shared_graph(policy: Optional[dict[str, Any]], *, fork_id: str,
                                    base_pipeline_id: str, graph_id: Optional[str]) -> bool:
    """INFRA-9: warn when a fork's safety pin turns on simulation → graph feedback.

    The fork reuses the base's graph, so with ``sim_graph_feedback`` pinned on
    its simulations (overlay-injected counterfactual events included) write
    into the observed graph that the base and every sibling fork read. The pin
    is kept as the spec requires; this only makes the consequence visible.
    Returns whether the warning was logged.
    """
    if not (isinstance(policy, dict) and policy.get("sim_graph_feedback") and graph_id):
        return False
    logger.warning(
        "[%s] 分叉自 %s 的安全政策钉（origin=%s）开启 sim_graph_feedback：本分叉的模拟活动"
        "（情景分叉含注入的反事实事件）将写入与 base 及其他分叉共享的图谱 %s。",
        fork_id, base_pipeline_id, policy.get("origin"), graph_id,
    )
    return True


def capture_run_shape_v1(options: Any, origin: str) -> Optional[dict[str, Any]]:
    """INFRA-7: pin the run shape (result-affecting knobs + provenance).

    The second admission snapshot next to ``safety_policy_v1``; see
    ``run_shape``.  ``origin`` is ``admission`` (start), ``fork`` (scenario and
    batch-question forks) or ``resume_unpinned`` (a run admitted before the
    pin existed, captured at its first resume).  The pin is observational, so
    a capture failure is logged and yields None instead of blocking admission.
    """
    try:
        return run_shape.pin(
            Config,
            options,
            origin=origin,
            pinned_at=_utcnow(),
            research_engine=research_engine_for_run(options),
        )
    except Exception as exc:  # noqa: BLE001 — the pin must never block a run
        logger.warning("run-shape pin skipped (origin=%s): %s", origin, exc)
        return None


def capture_actor_intelligence_policy_v1(
    origin: str,
    *,
    required: Optional[bool] = None,
) -> dict[str, Any]:
    """Pin whether this run requested the versioned Track-B actor plane.

    Absence of this policy identifies a pre-policy pipeline and intentionally
    retains its legacy/no-actor compatibility.  New admissions pin the ambient
    dual-track choice once so a later service reload cannot silently turn a
    required actor contract into an optional one (or vice versa).
    """
    return {
        "version": ACTOR_INTELLIGENCE_POLICY_VERSION,
        "origin": str(origin or "unknown"),
        "pinned_at": _utcnow(),
        "required": (
            bool(getattr(Config, "DEERFLOW_DUAL_TRACK", True))
            if required is None else bool(required)
        ),
        "schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
    }


# Disclosed on the pinned policy (and echoed by reception) when dual-track was
# requested but the selected research engine cannot produce the sealed plane.
ACTOR_PLANE_UNSUPPORTED_BY_V3 = "research_engine_v3_emits_unsealed_actor_plane"


def admission_actor_intelligence_policy_v1() -> dict[str, Any]:
    """Pin a new pipeline's actor-plane policy for the research engine it will run.

    The sealed actor-intelligence/v1 plane (Track-B dossier, coverage/lineage
    sidecars, contract manifest) is produced only by the legacy engine; the v3
    engine by design writes an unsealed, report-grounded ``actors.json``.
    Pinning ``required=True`` for a v3 run (``DEERFLOW_DUAL_TRACK`` defaults to
    true) would fail every full pipeline at reception, after the research
    spend (IF-2).  v3 admissions therefore pin ``required=False`` and record
    the engine plus the disclosed reason; legacy admissions are unchanged.
    """
    engine = resolve_research_engine()
    dual_track = bool(getattr(Config, "DEERFLOW_DUAL_TRACK", True))
    policy = capture_actor_intelligence_policy_v1(
        "admission",
        required=dual_track and engine == RESEARCH_ENGINE_LEGACY,
    )
    policy["research_engine"] = engine
    if dual_track and engine != RESEARCH_ENGINE_LEGACY:
        policy["not_required_reason"] = ACTOR_PLANE_UNSUPPORTED_BY_V3
    return policy


class RunAdmissionError(ValueError):
    """A run request refused at admission, before any pipeline dir, task or thread exists.

    TIME-7: the run API routes map only this class to 400.  A ValueError raised after
    admission (while the pipeline is being created) is an internal fault and keeps its 500.
    It subclasses ValueError so callers that catch ValueError are unaffected.
    """


def admit_hindcast_as_of(as_of: Any) -> tuple[str, dict[str, Any], str]:
    """TIME-7: the fail-closed hindcast admission rule for a run request carrying ``as_of``.

    Returns ``(as_of, actor policy, research engine)``: the canonical date, the actor-plane
    policy the admission pins and the engine the run's research stage will select from it.
    Raises RunAdmissionError, in this order, when ``Config.HINDCAST_ENABLED`` is off, when
    ``as_of`` is not a canonical YYYY-MM-DD date on or before today (UTC; ``validate_as_of``)
    and when that engine is not v3: only v3 honours a pinned as-of, while the legacy engine's
    ``_clamp_asof_reference`` would roll a past as-of forward to the run date.  Pure (nothing
    is written); ``PipelineOrchestrator.start`` and the run API routes share it.
    """
    from ..utils.point_in_time import validate_as_of
    if not bool(getattr(Config, "HINDCAST_ENABLED", False)):
        raise RunAdmissionError("as_of requires HINDCAST_ENABLED=true")
    try:
        canonical = validate_as_of(as_of)
    except ValueError as exc:
        raise RunAdmissionError(str(exc)) from exc
    actor_policy = admission_actor_intelligence_policy_v1()
    engine = research_engine_for_run({"actor_intelligence_policy_v1": actor_policy})
    if engine != RESEARCH_ENGINE_V3:
        raise RunAdmissionError("hindcast runs require the v3 research engine")
    return canonical, actor_policy, engine


# ---------------------------------------------------------------------------
# EVAL-13: evaluation-run admission pin.
#
# A run started with ``PipelineOrchestrator.start(..., evaluation={...})`` is an
# evaluation cell, never a production forecast: its reports skip the production
# calibration read, commit to the isolated evaluation ledger and are skipped by
# the resolution monitor. The context is validated before any directory or task
# exists and pinned once at admission into ``state.options['evaluation_run_v1']``
# plus the handoff marker ``evaluation_run.json`` (read back by
# ``evaluation_context_for_simulation`` for report entry points that have no
# orchestrator context). Resume and fork carry the pin; it is never re-captured.
# ---------------------------------------------------------------------------
EVALUATION_RUN_VERSION = "evaluation-run/v1"
EVALUATION_RUN_OPTION = "evaluation_run_v1"
EVALUATION_RUN_MARKER = "evaluation_run.json"
EVAL_RUN_ID_MAX_LEN = 64
EVALUATION_ID_MAX_CHARS = 128
EVALUATION_STATEMENT_MAX_CHARS = 1000
EVALUATION_CRITERIA_MAX_CHARS = 4000
_EVALUATION_KEYS = ("eval_run_id", "cell_id", "question_id", "target")
_EVALUATION_TARGET_KEYS = ("question_id", "statement", "resolution_criteria", "resolution_date")
# Control (Cc: C0, DEL, C1 incl. U+0085), format (Cf: bidi overrides, zero-width) and
# line/paragraph separators (Zl/Zp: U+2028/U+2029): anything that breaks a value across
# lines or hides/reorders text in ledger rows and log lines. Lone surrogates (Cs, e.g. a
# JSON '\ud800' escape) cannot be encoded as UTF-8, so the admission marker write would
# fail after the pipeline dir and task exist: they are refused at validation too.
_EVALUATION_REJECTED_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Zl", "Zp"})


def _evaluation_text(value: Any, name: str, max_chars: int) -> str:
    """A stripped, non-empty, single-line string of at most ``max_chars`` (ValueError otherwise).

    Errors name the field, never echo the value.
    """
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"evaluation {name} must be a non-empty string")
    if len(value) > max_chars:
        raise ValueError(f"evaluation {name} exceeds {max_chars} characters")
    if any(unicodedata.category(ch) in _EVALUATION_REJECTED_CATEGORIES for ch in value):
        raise ValueError(f"evaluation {name} contains control, format, surrogate or "
                         "line-break characters")
    return value.strip()


def _validate_evaluation_target(target: Any) -> dict[str, Any]:
    if not isinstance(target, dict):
        raise ValueError("evaluation target must be an object")
    if any(key not in _EVALUATION_TARGET_KEYS for key in target):
        raise ValueError(f"evaluation target accepts only {', '.join(_EVALUATION_TARGET_KEYS)}")
    out: dict[str, Any] = {
        "question_id": _evaluation_text(target.get("question_id"), "target.question_id",
                                        EVALUATION_ID_MAX_CHARS),
        "statement": _evaluation_text(target.get("statement"), "target.statement",
                                      EVALUATION_STATEMENT_MAX_CHARS),
        "resolution_criteria": None,
        "resolution_date": None,
    }
    if target.get("resolution_criteria") is not None:
        out["resolution_criteria"] = _evaluation_text(
            target["resolution_criteria"], "target.resolution_criteria",
            EVALUATION_CRITERIA_MAX_CHARS)
    if target.get("resolution_date") is not None:
        from datetime import date as _date
        from ..utils.point_in_time import validate_as_of
        try:
            # A resolution date normally lies ahead, so only the canonical-spelling half
            # of the point-in-time contract applies (no "not after today" bound).
            out["resolution_date"] = validate_as_of(target["resolution_date"],
                                                    today_utc=_date.max)
        except ValueError:
            raise ValueError(
                "evaluation target.resolution_date must be a canonical YYYY-MM-DD date") from None
    return out


def validate_evaluation_context(ctx: Any) -> dict[str, Any]:
    """Validate an evaluation-run context; return its normalized copy or raise ValueError.

    ``eval_run_id`` is required and must be a path-safe id of at most 64 characters
    (``security.safe_id``: ``[A-Za-z0-9][A-Za-z0-9_-]{0,63}``, so '../x', 'a/b' and a
    trailing newline are refused). ``cell_id`` / ``question_id`` are optional
    single-line strings of at most 128 characters. ``target`` is optional:
    ``{question_id, statement, resolution_criteria?, resolution_date?}`` with a
    canonical ``YYYY-MM-DD`` resolution date; build it from a golden row with
    :func:`evaluation_target_from_golden` so only outcome-free text reaches the
    run. A top-level ``question_id`` must equal the target's (it defaults to it).
    Unknown keys are refused. Missing optional fields normalize to None.
    """
    from ..utils.security import safe_id
    if not isinstance(ctx, dict):
        raise ValueError("evaluation context must be an object")
    if any(key not in _EVALUATION_KEYS for key in ctx):
        raise ValueError(f"evaluation context accepts only {', '.join(_EVALUATION_KEYS)}")
    out: dict[str, Any] = {
        "eval_run_id": safe_id(ctx.get("eval_run_id"), "eval_run", max_len=EVAL_RUN_ID_MAX_LEN),
        "cell_id": None,
        "question_id": None,
        "target": None,
    }
    for key in ("cell_id", "question_id"):
        if ctx.get(key) is not None:
            out[key] = _evaluation_text(ctx[key], key, EVALUATION_ID_MAX_CHARS)
    if ctx.get("target") is not None:
        target = _validate_evaluation_target(ctx["target"])
        if out["question_id"] is None:
            out["question_id"] = target["question_id"]
        elif out["question_id"] != target["question_id"]:
            raise ValueError("evaluation question_id differs from target.question_id")
        out["target"] = target
    return out


def build_evaluation_pin(ctx: Any, *, pinned_at: Optional[str] = None) -> dict[str, Any]:
    """The ``evaluation_run_v1`` admission pin for a validated evaluation context.

    Raises ValueError (via :func:`validate_evaluation_context`) before anything is
    written. Other admissions (TIME-7 hindcasts) reuse it to pin themselves as
    evaluation runs.
    """
    valid = validate_evaluation_context(ctx)
    return {
        "version": EVALUATION_RUN_VERSION,
        "record_class": "evaluation",
        "characterization_only": True,
        "eval_run_id": valid["eval_run_id"],
        "cell_id": valid["cell_id"],
        "question_id": valid["question_id"],
        "target": valid["target"],
        "pinned_at": pinned_at or _utcnow(),
    }


def evaluation_target_from_golden(question: dict[str, Any]) -> dict[str, Any]:
    """An evaluation ``target`` built from a golden row's forecaster view only (EVAL-9).

    ``golden_set.forecaster_view`` is the sanctioned outcome-free subset (id,
    question, resolution_criteria, as_of_date): the outcome, its note and the
    resolution date are grader-only and never reach the pin, the prompts or the
    report. The question text is the statement the binary extraction must emit.
    """
    from .golden_set import forecaster_view
    view = forecaster_view(question)
    return {
        "question_id": view.get("id"),
        "statement": view.get("question"),
        "resolution_criteria": view.get("resolution_criteria"),
    }


# ---------------------------------------------------------------------------
# 管线状态持久化（file-backed，沿用 MiroFish 的目录约定）
# ---------------------------------------------------------------------------


class PipelineManager:
    """读写 uploads/pipelines/<id>/pipeline_state.json。"""

    # 管线 id 形如 pipe_<hex>（见 create()/fork()），亦含少量历史/手工 id（如 pipe_e2egold02）。
    # 允许字母数字/下划线/连字符；不含 '.' '/' '\\' 故天然无法 ..  逃逸（EXECPLAN2 F-13-4）。
    # \A…\Z + fullmatch（INFRA-10）：旧的 ``$`` 会放过尾随换行（'pipe_x\n'）。
    # 后缀上限 123 = 总长 ≤ 128（utils.security.SAFE_ID_MAX_LEN），与 Flask id 闸门对
    # pipeline_id 的校验一致，否则 129–133 字符的 id 在此合法、到路由却被 404。
    _PIPELINE_ID_RE = re.compile(r"\Apipe_[A-Za-z0-9_-]{1,123}\Z")

    @classmethod
    def _validate_id(cls, pipeline_id: str) -> str:
        if not isinstance(pipeline_id, str) or not cls._PIPELINE_ID_RE.fullmatch(pipeline_id):
            raise ValueError(f"invalid pipeline_id: {pipeline_id!r}")
        return pipeline_id

    @classmethod
    def _dir(cls, pipeline_id: str) -> str:
        cls._validate_id(pipeline_id)
        return os.path.join(Config.PIPELINE_DATA_DIR, pipeline_id)

    @classmethod
    def state_path(cls, pipeline_id: str) -> str:
        return os.path.join(cls._dir(pipeline_id), "pipeline_state.json")

    @classmethod
    def handoff_dir(cls, pipeline_id: str) -> str:
        return os.path.join(cls._dir(pipeline_id), "handoff")

    @classmethod
    def resolve_handoff_dir(cls, pipeline_id: str) -> str:
        """按状态解析 handoff 目录：fork 情景（T4.6）共享 base 的 handoff，state.handoff_dir
        指向 base 目录；而静态 handoff_dir() 对 fork 只会算出被 ensure_dirs 建成空壳的
        fork 本地目录——API 层若用静态路径，dossier/翻译/PDF/进度/图表端点对 fork 全部
        静默拿空。解析次序：state.handoff_dir 存在且 realpath 收容于 PIPELINE_DATA_DIR
        之下 → 用它；缺失/逃逸/状态不可读 → 回落静态路径（非 fork 行为逐字节不变）。
        id 校验与 handoff_dir() 相同（非法 id 抛 ValueError）。"""
        static = cls.handoff_dir(pipeline_id)
        try:
            data = cls.load(pipeline_id)
        except Exception:  # noqa: BLE001 — 状态不可读 → 静态回落
            return static
        if not isinstance(data, dict):
            return static
        configured = str(data.get("handoff_dir") or "").strip()
        if not configured or configured == static:
            return static
        try:
            root = os.path.realpath(Config.PIPELINE_DATA_DIR)
            resolved = os.path.realpath(configured)
            if os.path.commonpath([resolved, root]) != root:
                return static
        except (OSError, ValueError):  # 不同盘符/异常路径 → 静态回落
            return static
        return configured

    @classmethod
    def manifest_path(cls, pipeline_id: str) -> str:
        """I-8-1: uploads/pipelines/<id>/run.json 的路径（可复现性清单）。"""
        return os.path.join(cls._dir(pipeline_id), "run.json")

    @classmethod
    def ensure_dirs(cls, pipeline_id: str) -> None:
        os.makedirs(cls.handoff_dir(pipeline_id), exist_ok=True)

    # I-4-4: 当 load() 读到一个 schema_version 比当前运行代码更新的状态文件时返回的哨兵。
    # 旧二进制不知道新版的语义，贸然按旧 from_dict 解析可能丢字段并在下次落盘时把新文件
    # 「降级覆写」损坏。哨兵让上层（API）把它映射成 409 Conflict 而不是 500。
    INCOMPATIBLE_KEY = "__incompatible_schema__"

    # ORCH-5: 每管线一把进程内写锁。唯一 tmp 名只消除了 FileNotFoundError 竞态；
    # touch_heartbeat/mark_failed 的「load→改→整 dict 写回」与主线程 save() 交错时仍有
    # lost-update：心跳线程读到旧 state 后原子覆写，静默回滚主线程刚落盘的阶段进度/产物，
    # 最坏把 terminal 状态翻回 running（下次重启即被孤儿回收误杀）。全部写方都在本进程
    # （管线线程/心跳线程/API 线程），进程内锁足以串行化读改写窗口，文件格式不变。
    _state_locks: "dict[str, threading.Lock]" = {}
    _state_locks_guard = threading.Lock()

    @classmethod
    def _state_lock(cls, pipeline_id: str) -> threading.Lock:
        with cls._state_locks_guard:
            lk = cls._state_locks.get(pipeline_id)
            if lk is None:
                lk = cls._state_locks[pipeline_id] = threading.Lock()
            return lk

    @classmethod
    def save(cls, state: PipelineState) -> None:
        cls.ensure_dirs(state.pipeline_id)
        state.updated_at = _utcnow()
        # I-4-4: 每次落盘都写当前 schema 版本（即便 dataclass 实例由旧文件迁移而来）。
        state.schema_version = PIPELINE_SCHEMA_VERSION
        # 走 write_json_atomic（tempfile.mkstemp 生成「每次唯一」的 tmp 名）。此前三处 state 写入
        # 共用同一个硬编码 `pipeline_state.json.tmp`，心跳线程(touch_heartbeat)与主线程 save() 并发时
        # 会竞态：一方 os.replace 把共享 tmp 改走后，另一方 os.replace 找不到 tmp → FileNotFoundError，
        # 研究阶段（双轨+心跳长跑）必现。唯一 tmp 名彻底消除该竞态。
        from ..utils.atomic import write_json_atomic
        with cls._state_lock(state.pipeline_id):  # ORCH-5: 与心跳/终态直写串行化
            write_json_atomic(cls.state_path(state.pipeline_id), state.to_dict())

    # I-4-4: 有序迁移函数，键 = 「源版本」，把 vN 的 dict 就地补齐到 v(N+1)。
    # 必须纯且幂等（在 load 时反复运行也安全）。新增一版时：PIPELINE_SCHEMA_VERSION += 1，
    # 并在此注册 {上一版: _migrate_to_next}。
    @staticmethod
    def _migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
        """v1（无 schema_version 的历史文件）→ v2。

        历史文件不会有 artifacts['run_manifest'] / run.json，缺失即按无 manifest 降级；
        这里只确保 artifacts 是 dict（极老的文件可能整体缺该键），其余字段由 from_dict 兜底。
        """
        if not isinstance(data.get("artifacts"), dict):
            data["artifacts"] = {}
        return data

    @classmethod
    def _migrations(cls) -> "dict[int, Callable[[dict[str, Any]], dict[str, Any]]]":
        """源版本 → 迁移函数。集中一处，新增版本只改这里 + PIPELINE_SCHEMA_VERSION。"""
        return {1: cls._migrate_v1_to_v2}

    @classmethod
    def _migrate(cls, data: dict[str, Any], from_version: int) -> dict[str, Any]:
        """把 data 从 from_version 依次迁移到 PIPELINE_SCHEMA_VERSION（就地 + 返回）。"""
        migrations = cls._migrations()
        ver = from_version
        while ver < PIPELINE_SCHEMA_VERSION:
            fn = migrations.get(ver)
            if fn is None:
                # 没有登记的迁移函数：保守跳过（不修改），仅推进版本号，避免死循环。
                break
            data = fn(data)
            ver += 1
        data["schema_version"] = PIPELINE_SCHEMA_VERSION
        return data

    @classmethod
    def mark_failed(cls, pipeline_id: str, error: str, status: str = "failed") -> bool:
        """直接在持久化 JSON 上把管线标记为终态（无需重建 dataclass）。

        用于启动时回收孤儿管线：进程崩溃/重启后，pipeline_state.json 可能永远停在
        running，前端轮询据此空转。原子写入（tmp + os.replace），同时把当前阶段标为
        同一终态。``status`` 允许 "cancelled"（用户对孤儿管线点取消时语义更准确）。
        """
        with cls._state_lock(pipeline_id):  # ORCH-5: 读改写全程持锁
            data = cls.load(pipeline_id)
            if not data:
                return False
            data["status"] = status
            data["error"] = error
            data["updated_at"] = _utcnow()
            cur = data.get("current_stage")
            stages = data.get("stages") or {}
            if cur and isinstance(stages.get(cur), dict):
                _st = stages[cur]
                # XRUN-15: 已跑到 100% 的阶段是「完成的工作」，不因管线级取消/失败被改写成
                # cancelled（曾出现 status='cancelled' + progress=100 + '本体生成完成' 的自相矛盾）。
                if int(_st.get("progress") or 0) >= 100 and not _st.get("error"):
                    _st["status"] = "completed"
                else:
                    _st["status"] = status
                    _st["error"] = error
            cls.ensure_dirs(pipeline_id)
            from ..utils.atomic import write_json_atomic  # 唯一 tmp 名，消除与心跳/主存档的竞态
            write_json_atomic(cls.state_path(pipeline_id), data)
            return True

    @classmethod
    def mark_salvaged_completed(cls, pipeline_id: str, note: str) -> bool:
        """W9-1: 把「报告已完整落盘」的孤儿管线直接落成 completed（pipeline_health=degraded）。

        与 mark_failed 同款的轻量直写（load → 改键 → 原子替换，全程持锁）。语义：主报告
        （full_report.md + forecast.json）已经是完整交付物，中断只发生在其后的多种子集成/
        收尾窗口——整线判 failed 会把 $10+ 的成品当废品；改为 completed + degraded 健康块 +
        「集成已跳过」留痕。同时置 options.ensemble_done=True，使后续 resume 不再重烧集成窗口。
        """
        with cls._state_lock(pipeline_id):
            data = cls.load(pipeline_id)
            if not data or cls.INCOMPATIBLE_KEY in data:
                return False
            data["status"] = "completed"
            data["error"] = None
            data["global_progress"] = 100
            data["updated_at"] = _utcnow()
            opts = data.get("options")
            if not isinstance(opts, dict):
                opts = {}
                data["options"] = opts
            ph = opts.get("pipeline_health")
            if not isinstance(ph, dict):
                ph = {"status": "degraded", "issues": []}
            elif ph.get("status") == "ok":
                ph["status"] = "degraded"
            ph.setdefault("status", "degraded")
            issues = ph.get("issues")
            if not isinstance(issues, list):
                issues = []
            if note not in issues:
                issues.append(note)
            ph["issues"] = issues
            opts["pipeline_health"] = ph
            opts["ensemble_done"] = True   # 集成窗口被中断 → 按「已跳过」处理，不再重烧
            opts["ensemble_skipped"] = note
            opts["salvaged_orphan_at"] = _utcnow()
            stages = data.get("stages") or {}
            _rs = stages.get(STAGE_REPORT)
            if isinstance(_rs, dict):
                _rs["status"] = "completed"
                _rs["progress"] = 100
                _rs["error"] = None
                if not _rs.get("finished_at"):
                    _rs["finished_at"] = _utcnow()
                # 阶段消息可能冻结在「多种子集成 …」——替换为诚实的终态描述。
                if "多种子集成" in str(_rs.get("message") or ""):
                    _rs["message"] = "报告完成（多种子集成被中断，已跳过）"
            data["current_stage"] = STAGE_REPORT
            cls.ensure_dirs(pipeline_id)
            from ..utils.atomic import write_json_atomic
            write_json_atomic(cls.state_path(pipeline_id), data)
            return True

    @classmethod
    def touch_heartbeat(cls, pipeline_id: str, pid: Optional[int] = None) -> bool:
        """I-4-1: 仅刷新 heartbeat_at（+ 可选 owner_pid/owner_boot_id），不重建 dataclass。

        独立于阶段进度的「我还活着」壁钟信号，由 _run 的看护线程按固定节律调用。沿用
        mark_failed 的轻量直写模式（load → 改两三个键 → 原子替换），避免每次心跳走 full save
        / 触发 schema 迁移副作用。状态非 running 时静默 no-op（终态管线无需心跳）。
        """
        with cls._state_lock(pipeline_id):  # ORCH-5: 读改写全程持锁，防覆写主线程刚落盘的进度
            data = cls.load(pipeline_id)
            if not data or cls.INCOMPATIBLE_KEY in data:
                return False
            if data.get("status") != "running":
                return False
            data["heartbeat_at"] = _utcnow()
            if pid is not None:
                data["owner_pid"] = int(pid)
                data["owner_boot_id"] = _BOOT_ID
            cls.ensure_dirs(pipeline_id)
            # 高频心跳：唯一 tmp 名消除与主存档竞态；fsync=False（数秒即被覆写，无需落盘耐久）。
            from ..utils.atomic import write_json_atomic
            write_json_atomic(cls.state_path(pipeline_id), data, fsync=False)
            return True

    # ----------------------------------------------------------------------
    # I-4-3: 产物清单 manifest.json（每条产物的 sha256/字节数/产出阶段/schema_ok）。
    # 与 run.json（run manifest，可复现性快照）不同：此清单服务于「复用前完整性校验」，
    # 防止半写/截断的产物冒充 completed 被复用、把垃圾喂给下游静默降级整份预测。
    # ----------------------------------------------------------------------

    @classmethod
    def artifact_manifest_path(cls, pipeline_id: str) -> str:
        """I-4-3: uploads/pipelines/<id>/handoff/manifest.json 的路径。"""
        return os.path.join(cls.handoff_dir(pipeline_id), "manifest.json")

    @classmethod
    def load_artifact_manifest(cls, pipeline_id: str) -> dict[str, Any]:
        """I-4-3: 读产物清单（缺失/损坏 → 空 dict，按「无清单」降级到旧的存在性复用）。"""
        try:
            path = cls.artifact_manifest_path(pipeline_id)
        except ValueError:
            return {}
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    @classmethod
    def write_artifact_manifest(cls, pipeline_id: str, manifest: dict[str, Any]) -> None:
        """I-4-3: 原子写产物清单（复用 utils.atomic，与其它产物写法一致）。"""
        from ..utils.atomic import write_json_atomic
        cls.ensure_dirs(pipeline_id)
        write_json_atomic(cls.artifact_manifest_path(pipeline_id), manifest)

    @classmethod
    def load(cls, pipeline_id: str) -> Optional[dict[str, Any]]:
        try:
            path = cls.state_path(pipeline_id)
        except ValueError:
            return None  # malformed id → treat as not-found, keep callers robust
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        # I-4-4: 版本检查 + 迁移，在所有 load() 消费者之前统一进行。
        v = int(data.get("schema_version") or 1)
        if v > PIPELINE_SCHEMA_VERSION:
            # 文件比当前代码更新。严格模式（默认）下拒绝，避免按旧语义解析丢字段、
            # 并在下次落盘时把新文件降级覆写。返回带 pipeline_id 的最小哨兵 dict，
            # 让 status/list 仍能读到 id 而不至于崩，由 API 层映射为 409。
            strict = bool(getattr(Config, "PIPELINE_STRICT_SCHEMA", True))
            if strict:
                return {
                    "pipeline_id": data.get("pipeline_id", pipeline_id),
                    "status": data.get("status"),
                    "schema_version": v,
                    cls.INCOMPATIBLE_KEY: v,
                }
            # 非严格（应急旁路）：尽力按旧语义读取，不迁移、不改版本号。
            return data
        if v < PIPELINE_SCHEMA_VERSION:
            try:
                data = cls._migrate(data, v)
            except Exception:
                # 迁移意外失败：返回原始数据（from_dict 的逐字段默认仍可兜底），不丢记录。
                return data
        return data

    @classmethod
    def is_incompatible(cls, data: Optional[dict[str, Any]]) -> Optional[int]:
        """若 load() 返回的是「更新版本」哨兵，返回该文件的版本号，否则 None。"""
        if isinstance(data, dict) and cls.INCOMPATIBLE_KEY in data:
            try:
                return int(data[cls.INCOMPATIBLE_KEY])
            except (TypeError, ValueError):
                return PIPELINE_SCHEMA_VERSION + 1
        return None

    @classmethod
    def delete(cls, pipeline_id: str) -> bool:
        """删除一条管线记录（整个 uploads/pipelines/<id>/ 目录，含 handoff 产物）。

        只做文件系统删除；调用方（PipelineOrchestrator.delete_pipeline）负责
        拒绝在飞管线。目录不存在返回 False。
        """
        import shutil

        # 路径防御集中在 _dir/_validate_id（pipeline_id 来自 URL，绝不允许逃出数据目录）。
        try:
            target = cls._dir(pipeline_id)
        except ValueError:
            return False
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


# ORCH-1(5): 建图切块前的内嵌图片清洗。Markdown 形式 ![alt](data:image/...;base64,...)
# 与 HTML 形式 <img src="data:..."> 各一条正则；仅捕获 data-URI 本体，外部 URL 图片不动。
_MD_DATA_URI_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*data:[^)]*\)")
_HTML_DATA_URI_IMG_RE = re.compile(
    r"<img\b[^>]*\bsrc\s*=\s*[\"']data:[^\"']*[\"'][^>]*>", re.IGNORECASE)
_HTML_ALT_ATTR_RE = re.compile(r"\balt\s*=\s*[\"']([^\"']*)[\"']", re.IGNORECASE)


def _strip_data_uri_images(text: str) -> str:
    """建图切块前剔除 base64/data-URI 内嵌图片，保留 alt 文本/图注。

    带图表的研究报告（图被渲染成 base64 PNG 内嵌）若原样切块，单张图就是成千上万
    字符的 base64 噪声 episode，会污染图谱实体抽取。此函数把 data-URI 图片本体替换
    为其 alt 文本（无 alt 则移除标签），正文与外部 URL 图片逐字节不动。
    GRAPH_STRIP_DATA_URI_IMAGES=false 可整体关闭（回到今日行为）；清洗过程任何异常
    也回退原文——degrade-safe，绝不因清洗失败阻断建图。
    （knob 就地读 env：config.py 归属其它 wave item，此处不新增 Config 属性。）
    """
    if os.environ.get("GRAPH_STRIP_DATA_URI_IMAGES", "true").strip().lower() == "false":
        return text
    try:
        stripped = _MD_DATA_URI_IMG_RE.sub(lambda m: m.group(1), text)

        def _img_alt(m: "re.Match[str]") -> str:
            alt = _HTML_ALT_ATTR_RE.search(m.group(0))
            return alt.group(1) if alt else ""

        return _HTML_DATA_URI_IMG_RE.sub(_img_alt, stripped)
    except Exception:  # noqa: BLE001 — 清洗只是降噪增强，失败回退原文
        return text


def _graph_research_chunks(text: Any, label: str) -> list[str]:
    """Prepare research evidence for the Graphiti model boundary.

    Stage-1 reports and actor dossiers are evidence, not instructions.  Graph
    ingestion ultimately invokes an extraction model, so sending the raw prose
    would recreate the same prompt-control seam already closed for ontology,
    configuration, and OASIS personas.  Sanitize the complete document first
    (so a directive split across a future chunk boundary is still detected),
    split only the safe text, and wrap *every* resulting episode in its own
    explicit non-executable data boundary.

    The cap is derived from the input length rather than a presentation budget:
    graph ingestion must retain the full safe evidence corpus.  Normal graph
    chunk size/overlap still provide the actual per-episode bound.
    """
    raw = _strip_data_uri_images(str(text or ""))
    if not raw.strip():
        return []
    safe_document = sanitize_untrusted_research_text(
        raw,
        # An unsafe one-word line expands to a stable omission marker. Reserve
        # that worst-case per-line growth so security replacement never
        # truncates neighbouring evidence before the normal chunker runs.
        max_chars=max(1, len(raw) + (raw.count("\n") + 1) * 64),
    )
    raw_chunks = TextProcessor.split_text(
        safe_document,
        Config.DEFAULT_CHUNK_SIZE,
        Config.DEFAULT_CHUNK_OVERLAP,
    )
    total = len(raw_chunks)
    prepared: list[str] = []
    for index, chunk in enumerate(raw_chunks, start=1):
        bounded = delimit_untrusted_research_text(
            f"{label} chunk {index}/{total}",
            chunk,
            max_chars=max(1, len(chunk) * 2),
        )
        if bounded:
            prepared.append(bounded)
    return prepared


class _DeerFlowSafetyOverlayError(RuntimeError):
    """A required tracked DeerFlow safety overlay could not be enforced."""


class _DeerFlowSkillSyncError(RuntimeError):
    """The required runtime skill bundle could not be deployed and verified."""


_RUNTIME_SKILL_SYNC_HELPER_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../deerflow_bridge/runtime_skill_sync.py"
))

# Bridge modules imported by BARE name from the deployed deer-flow/ directory
# (deerflow_research.py runs with sys.path[0]==deer-flow/): the config-reflected
# tools (`use: market_tools:...` / `search_tools:...` / `cached_fetch:...`), the
# LOOP-007 budget control plane they share, and the deep-research engine v3
# (linear_research.py phases + research_gateway.py LLM gateway/research tools +
# evidence_spans.py verbatim evidence-span matching), plus source_dates.py (the
# source publication-date parser cached_fetch and research_gateway import).
# setup.sh deploys the same set; test_deerflow_bridge_sync_guard pins the parity.
_DEPLOYED_BRIDGE_MODULES: tuple[str, ...] = (
    "market_tools.py", "search_tools.py", "cached_fetch.py",
    "research_budget.py", "linear_research.py", "research_gateway.py", "evidence_spans.py",
    "source_dates.py",
)


# deerflow_bridge/extensions_config.json 是模板：MCP server 的 command / PYTHONPATH 依赖本机
# 检出位置，源文件只写占位符，部署时由 _render_bridge_extensions_config 替换成真实路径。
# （此前源文件写死 /Users/<dev>/… 绝对路径，换一台机器 fork/continue/resume 的 KG MCP 就起不来。）
_EXTENSIONS_REPO_ROOT_TOKEN = "{{DRF_REPO_ROOT}}"
_EXTENSIONS_PYTHON_TOKEN = "{{DRF_BACKEND_PYTHON}}"


def _mcp_backend_python(repo_root: str) -> str:
    """MCP server 用的解释器：优先当前后端解释器（它必然装齐了 app.* 依赖），缺失时退回约定 venv。"""
    if sys.executable:
        return sys.executable
    return os.path.join(repo_root, "backend", ".venv", "bin", "python")


def _render_bridge_extensions_config(src: str, repo_root: str) -> bytes:
    """把 extensions_config.json 模板里的占位符替换为本机路径，返回待部署的字节。

    在解析后的 JSON 值上替换（而非原始文本），路径里的反斜杠/引号不会破坏 JSON。
    渲染结果若仍残留 ``{{…}}`` 占位符则抛错——宁可跳过部署，也不给 harness 一个起不来的 command。
    """
    with open(src, encoding="utf-8") as fh:
        data = json.load(fh)
    replacements = {
        _EXTENSIONS_REPO_ROOT_TOKEN: repo_root,
        _EXTENSIONS_PYTHON_TOKEN: _mcp_backend_python(repo_root),
    }

    def _sub(value: Any) -> Any:
        if isinstance(value, str):
            for token, real in replacements.items():
                value = value.replace(token, real)
            return value
        if isinstance(value, dict):
            return {key: _sub(item) for key, item in value.items()}
        if isinstance(value, list):
            return [_sub(item) for item in value]
        return value

    rendered = json.dumps(_sub(data), ensure_ascii=False, indent=2) + "\n"
    leftover = re.search(r"\{\{[^{}]*\}\}", rendered)
    if leftover:
        raise ValueError(f"unknown placeholder {leftover.group(0)} in {src}")
    return rendered.encode("utf-8")


def _deploy_rendered_extensions_config(rendered: bytes, dst: str) -> bool:
    """Atomically install rendered extensions_config.json bytes; True when written.

    Pipelines run as threads of one backend process, so concurrent first syncs
    can race here.  Each call stages into its own ``mkstemp`` file (a PID-derived
    name was shared between threads: one thread's ``os.replace`` consumed the
    other's staging file and aborted that research launch).  Identical bytes are
    left untouched.
    """
    try:
        with open(dst, "rb") as fh:
            if fh.read() == rendered:
                return False
    except FileNotFoundError:
        pass
    fd, tmp = tempfile.mkstemp(
        prefix=".extensions_config.", suffix=".tmp", dir=os.path.dirname(dst))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(rendered)
        os.chmod(tmp, 0o644)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def _sync_deerflow_bridge_if_stale(deerflow_dir: str) -> dict[str, Any]:
    """启动研究子进程前的漂移防护（2026-07-03 live-surfaced）。

    ``deerflow_bridge/``（仓库内、git 跟踪的源）与实际执行的
    ``$DEERFLOW_DIR/deerflow_research.py``（默认 ``deer-flow/``，setup.sh 从 bridge
    拷贝生成）是两份独立文件。此前所有对 deerflow_bridge 的修复（audit wave、
    actor-cast 纪律等）只有重新运行 ``./setup.sh`` 才会同步到部署副本——一次实机
    forecast run 验证时发现子进程仍在跑没有 enforce_actor_cast 的旧代码（3217 行
    vs 源 3792 行），导致 28-actor 的档案未按 ACTOR_CAST_MAX=20 截断。
    普通 bridge 模块仍沿用内容哈希同步；技能树则由共享 helper 构建确定性 manifest，
    通过跨进程锁串行化，在同一文件系统完整 staging + 验证后原子交换 ``skills/public``。
    任何必需 skill 缺失、复制失败或部署后哈希不一致都必须在启动研究子进程前失败关闭。
    若 tracked lead-agent safety overlay 存在却无法应用，也必须阻断研究启动，避免已知跨
    provider summarization stall 在未打补丁的 runtime 中重现。
    """
    skill_sync_result: dict[str, Any] | None = None
    try:
        # backend/app/services/pipeline_orchestrator.py -> repo root 是三层上级，
        # 与 config.py 里 DEERFLOW_DIR 默认值的算法一致（同样以 __file__ 为基准）。
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        bridge_dir = os.path.join(repo_root, "deerflow_bridge")
        bridge_script = os.path.join(bridge_dir, "deerflow_research.py")
        deployed_script = os.path.join(deerflow_dir, "deerflow_research.py")
        if not os.path.isfile(bridge_script) or not os.path.isfile(deployed_script):
            raise _DeerFlowSkillSyncError(
                "required DeerFlow bridge source/deployed entry point is missing"
            )

        # LOOP-014: the bridge skill source is authoritative.  Load the helper
        # from its stable tracked path (the tests patch this module's __file__ to
        # point at an isolated repository, while the mechanism itself remains the
        # exact production implementation).
        if not os.path.isfile(_RUNTIME_SKILL_SYNC_HELPER_PATH):
            raise _DeerFlowSkillSyncError(
                "required deterministic runtime skill sync helper is missing"
            )
        source_skills_dir = os.path.join(bridge_dir, "skills")
        public_skills_dir = os.path.join(deerflow_dir, "skills", "public")
        import importlib.util as _importlib_util

        try:
            _sync_spec = _importlib_util.spec_from_file_location(
                "drf_runtime_skill_sync", _RUNTIME_SKILL_SYNC_HELPER_PATH
            )
            if _sync_spec is None or _sync_spec.loader is None:
                raise RuntimeError("could not load deterministic skill sync helper")
            _sync_module = _importlib_util.module_from_spec(_sync_spec)
            _sync_spec.loader.exec_module(_sync_module)
            skill_sync_result = _sync_module.sync_runtime_skills(
                source_skills_dir,
                public_skills_dir,
                required_skills=_sync_module.DEFAULT_REQUIRED_SKILLS,
            )
        except Exception as skill_sync_err:  # noqa: BLE001 — retyped boundary
            raise _DeerFlowSkillSyncError(
                f"required runtime skill deployment failed: {skill_sync_err}"
            ) from skill_sync_err

        logger.info(
            "Runtime skill bundle %s: source_manifest=%s deployed_manifest=%s "
            "deployed_path=%s lazy_resource_hashes=%s",
            skill_sync_result.get("outcome"),
            skill_sync_result.get("source_manifest_hash"),
            skill_sync_result.get("deployed_manifest_hash"),
            skill_sync_result.get("deployed_path"),
            json.dumps({
                name: manifest.get("lazy_resource_hashes", {})
                for name, manifest in skill_sync_result.get("skills", {}).items()
            }, ensure_ascii=False, sort_keys=True),
        )

        def _digest(path: str) -> str:
            with open(path, "rb") as fh:
                return hashlib.sha256(fh.read()).hexdigest()

        pairs = [
            (bridge_script, deployed_script),
            (
                _RUNTIME_SKILL_SYNC_HELPER_PATH,
                os.path.join(deerflow_dir, "runtime_skill_sync.py"),
            ),
        ]
        # ORCH-1(2): config-reflected tool modules registered in config.yaml as BARE
        # module names (`use: market_tools:...` / `search_tools:...` / `cached_fetch:...`).
        # deerflow_research.py runs with sys.path[0]==deer-flow/, so the harness
        # reflection resolver imports these by bare name — they MUST sit next to the
        # deployed script or web_search/web_fetch/prediction_market tools fail to load.
        # setup.sh copies them, but a bridge-only edit (no ./setup.sh rerun) would
        # otherwise drift exactly like deerflow_research.py did; mirror that guard here.
        # Engine v3 is imported by bare name the same way: linear_research.py (the
        # phases), research_gateway.py (LLM gateway + research tools) and
        # evidence_spans.py (evidence-quote matching) must all sit next to the
        # deployed script or the v3 dispatch raises ImportError; source_dates.py
        # (source publication dates) sits there for cached_fetch/research_gateway.
        for _tool_mod in _DEPLOYED_BRIDGE_MODULES:
            _tool_src = os.path.join(bridge_dir, _tool_mod)
            if os.path.isfile(_tool_src):
                pairs.append((_tool_src, os.path.join(deerflow_dir, _tool_mod)))
        # LOOP-009 provider-call admission and middleware-internal model calls
        # must be reproducible from the tracked bridge overlay. ``deer-flow/``
        # is gitignored, so syncing only the root bridge script would leave a
        # clean clone without the exact-call concurrency boundary.
        _mw_src_dir = os.path.join(bridge_dir, "patches", "middlewares")
        _mw_dst_dir = os.path.join(
            deerflow_dir, "backend", "packages", "harness", "deerflow",
            "agents", "middlewares")
        if os.path.isdir(_mw_src_dir) and os.path.isdir(_mw_dst_dir):
            for _mw_name in sorted(os.listdir(_mw_src_dir)):
                if _mw_name.endswith(".py"):
                    pairs.append((
                        os.path.join(_mw_src_dir, _mw_name),
                        os.path.join(_mw_dst_dir, _mw_name),
                    ))
        # W9-9：MCP 扩展注册文件也同步到部署目录。该文件是 OPT-IN 的（harness 仅在
        # DEER_FLOW_EXTENSIONS_CONFIG_PATH 指向它时才加载），部署副本本身惰性无副作用；
        # DeerFlowResearchRunner 在「图谱已存在」的路径把该 env 指向此部署副本。
        # 源文件是模板（见 _render_bridge_extensions_config），部署的是渲染后的内容而非逐字节拷贝。
        _ext_src = os.path.join(bridge_dir, "extensions_config.json")
        _ext_dst = os.path.join(deerflow_dir, "extensions_config.json")
        synced = []
        _ext_rendered = None
        if os.path.isfile(_ext_src):
            try:
                _ext_rendered = _render_bridge_extensions_config(_ext_src, repo_root)
            except (OSError, ValueError) as ext_err:
                # 模板坏了只影响可选的 KG MCP 接线：撤掉旧部署副本（研究侧据此跳过接线），
                # 不能让它中断下面 deerflow_research.py 等必需文件的同步。
                logger.warning("extensions_config.json 模板渲染失败，本次跳过 KG MCP 接线: %s", ext_err)
                try:
                    os.remove(_ext_dst)
                except FileNotFoundError:
                    pass  # 并发管线已撤掉，或本就没有部署副本
        if _ext_rendered is not None:
            # 可选的 KG MCP 接线部署失败（磁盘/权限）不能中断下面必需模块
            # （deerflow_research.py、v3 引擎 linear_research.py / research_gateway.py…）的同步。
            try:
                if _deploy_rendered_extensions_config(_ext_rendered, _ext_dst):
                    synced.append("extensions_config.json")
            except OSError as ext_err:
                logger.warning("extensions_config.json 部署失败，本次跳过 KG MCP 接线: %s", ext_err)
        for src, dst in pairs:
            if os.path.isfile(dst) and _digest(src) == _digest(dst):
                continue
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            try:
                shutil.copyfile(src, dst)
            except Exception as copy_err:  # noqa: BLE001
                if src == _RUNTIME_SKILL_SYNC_HELPER_PATH:
                    raise _DeerFlowSkillSyncError(
                        "runtime skill verifier could not be deployed"
                    ) from copy_err
                raise
            synced.append(os.path.relpath(dst, deerflow_dir))

        # LOOP-010: unlike copied modules, the lead-agent change is a narrow
        # overlay on an upstream file. Apply the same tracked, idempotent
        # transformation used by setup.sh so an existing deployment cannot keep
        # interpreting YAML null as LangChain's implicit 4K trim default or route
        # summarization through the first configured provider instead of the
        # active per-run model.
        _lead_overlay = os.path.join(
            bridge_dir, "patches", "apply_lead_agent_overlays.py"
        )
        _lead_target = os.path.join(
            deerflow_dir, "backend", "packages", "harness", "deerflow",
            "agents", "lead_agent", "agent.py",
        )
        if os.path.isfile(_lead_target):
            if not os.path.isfile(_lead_overlay):
                raise _DeerFlowSafetyOverlayError(
                    "required tracked DeerFlow lead-agent safety overlay is missing"
                )
            import importlib.util as _importlib_util

            try:
                _spec = _importlib_util.spec_from_file_location(
                    "deerflow_lead_agent_overlay", _lead_overlay
                )
                if _spec is None or _spec.loader is None:
                    raise RuntimeError(
                        "could not load tracked DeerFlow lead-agent overlay")
                _overlay_module = _importlib_util.module_from_spec(_spec)
                _spec.loader.exec_module(_overlay_module)
                _overlay_status = _overlay_module.apply(deerflow_dir)
            except Exception as overlay_err:  # noqa: BLE001 — retyped below
                raise _DeerFlowSafetyOverlayError(
                    "required DeerFlow lead-agent safety overlay failed"
                ) from overlay_err
            if _overlay_status not in {"applied", "already_applied"}:
                raise _DeerFlowSafetyOverlayError(
                    "required DeerFlow lead-agent safety overlay is missing "
                    f"its target (status={_overlay_status!r})"
                )
            if _overlay_status == "applied":
                synced.append(
                    "backend/packages/harness/deerflow/agents/lead_agent/agent.py"
                )

        # Model config intentionally carries local context-window metadata for
        # research/synthesis budgeting. Upstream ModelConfig allows unknown
        # fields and the factory otherwise forwards that metadata into
        # OpenAI-compatible request kwargs, where providers reject it.
        _model_factory_overlay = os.path.join(
            bridge_dir, "patches", "apply_model_factory_overlays.py"
        )
        if os.path.isfile(_model_factory_overlay):
            import importlib.util as _importlib_util

            _spec = _importlib_util.spec_from_file_location(
                "deerflow_model_factory_overlay", _model_factory_overlay
            )
            if _spec is None or _spec.loader is None:
                raise RuntimeError(
                    "could not load tracked DeerFlow model-factory overlay")
            _overlay_module = _importlib_util.module_from_spec(_spec)
            _spec.loader.exec_module(_overlay_module)
            _overlay_status = _overlay_module.apply(deerflow_dir)
            if _overlay_status == "applied":
                synced.append(
                    "backend/packages/harness/deerflow/models/factory.py"
                )

        # The embedded subagent path is likewise a narrow, required
        # transformation. Never copy entire vendor modules: the seed carries
        # tracing/session callbacks that must survive. The overlay keeps the
        # lifecycle lease, passes the exact client AppConfig, inherits the
        # active model even when tracing metadata is absent, and rejects LLM
        # error-fallback messages instead of publishing them as successful
        # task evidence.
        _subagent_overlay = os.path.join(
            bridge_dir, "patches", "apply_subagent_overlays.py"
        )
        _subagent_targets = [
            os.path.join(
                deerflow_dir, "backend", "packages", "harness", "deerflow",
                "client.py",
            ),
            os.path.join(
                deerflow_dir, "backend", "packages", "harness", "deerflow",
                "tools", "builtins", "task_tool.py",
            ),
            os.path.join(
                deerflow_dir, "backend", "packages", "harness", "deerflow",
                "subagents", "executor.py",
            ),
        ]
        if all(os.path.isfile(path) for path in _subagent_targets):
            if not os.path.isfile(_subagent_overlay):
                raise _DeerFlowSafetyOverlayError(
                    "required tracked DeerFlow subagent safety overlay is missing"
                )
            import importlib.util as _importlib_util

            try:
                _spec = _importlib_util.spec_from_file_location(
                    "deerflow_subagent_overlay", _subagent_overlay
                )
                if _spec is None or _spec.loader is None:
                    raise RuntimeError(
                        "could not load tracked DeerFlow subagent overlay")
                _overlay_module = _importlib_util.module_from_spec(_spec)
                _spec.loader.exec_module(_overlay_module)
                _overlay_status = _overlay_module.apply(deerflow_dir)
            except Exception as overlay_err:  # noqa: BLE001 — retyped below
                raise _DeerFlowSafetyOverlayError(
                    "required DeerFlow subagent safety overlay failed"
                ) from overlay_err
            if _overlay_status not in {"applied", "already_applied"}:
                raise _DeerFlowSafetyOverlayError(
                    "required DeerFlow subagent safety overlay is missing "
                    f"its targets (status={_overlay_status!r})"
                )
            if _overlay_status == "applied":
                synced.extend([
                    "backend/packages/harness/deerflow/client.py",
                    "backend/packages/harness/deerflow/tools/builtins/task_tool.py",
                    "backend/packages/harness/deerflow/subagents/executor.py",
                ])

        # ORCH-1(1) config.yaml：setup.sh 明确「绝不覆盖已存在的 deer-flow/config.yaml」
        # （部署侧可能有本地 provider stanza 改动），故此处只做漂移检测 + 提示手工 diff，
        # 不自动拷贝——与 setup.sh 的 never-clobber 语义保持一致。
        bridge_cfg = os.path.join(bridge_dir, "config.yaml")
        deployed_cfg = os.path.join(deerflow_dir, "config.yaml")
        if (os.path.isfile(bridge_cfg) and os.path.isfile(deployed_cfg)
                and _digest(bridge_cfg) != _digest(deployed_cfg)):
            logger.warning(
                "deer-flow/config.yaml 与 deerflow_bridge/config.yaml 内容不一致（按 setup.sh "
                "约定不自动覆盖——部署副本可能包含本地 provider 改动）。请手工 diff 两份文件"
                "以拾取新的 provider stanza。")
        if synced:
            logger.warning(
                "DeerFlow 部署副本与 deerflow_bridge/ 源不同步，已自动重新同步（%s）——"
                "研究子进程刚才会用旧代码运行。建议提交后运行一次 ./setup.sh 使其保持最新。",
                ", ".join(synced),
            )
        return skill_sync_result
    except (_DeerFlowSafetyOverlayError, _DeerFlowSkillSyncError) as sync_err:
        logger.error("DeerFlow 必需运行时部署无法验证，拒绝启动研究子进程: %s", sync_err)
        raise
    except Exception as sync_err:  # noqa: BLE001 — 非安全 overlay 漂移继续退化为警告
        logger.warning("DeerFlow 部署副本漂移检测失败（忽略，不影响本次运行）: %s", sync_err)
        if skill_sync_result is None:
            raise _DeerFlowSkillSyncError(
                "runtime skill deployment did not produce verification telemetry"
            ) from sync_err
        return skill_sync_result


_RESEARCH_BUDGET_ENV_KEYS = (
    "RESEARCH_BUDGET_DB",
    "RESEARCH_BUDGET_TELEMETRY_PATH",
    "RESEARCH_BUDGET_LANE_ID",
    "RESEARCH_BUDGET_RUN_ID",
    "RESEARCH_BUDGET_EPOCH",
    "RESEARCH_BUDGET_ATTEMPTS_GLOBAL",
    "RESEARCH_BUDGET_SEARCH_GLOBAL",
    "RESEARCH_BUDGET_SEARCH_LANE",
    "RESEARCH_BUDGET_FETCH_GLOBAL",
    "RESEARCH_BUDGET_FETCH_LANE",
    "RESEARCH_NEGATIVE_CACHE_TTL_SECONDS",
    "RESEARCH_NEGATIVE_CACHE_RETRIES",
)


def _research_budget_exhaustion(
    telemetry_path: str,
    expected_epoch: Optional[str] = None,
) -> Optional[str]:
    """Return the saturated global cap for the expected budget epoch.

    The SQLite ledger is authoritative for admission, while this atomically
    exported snapshot is sufficient for a pre-spawn guard.  An old snapshot
    from a prior task is ignored rather than blocking a newly activated epoch.
    """
    try:
        with open(telemetry_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, TypeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    if expected_epoch and str(payload.get("epoch") or "") != expected_epoch:
        return None
    limits = payload.get("limits") or {}
    counts = payload.get("global") or {}
    checks = (
        ("attempts_global", "attempts"),
        ("search_global", "search_network"),
        ("fetch_global", "fetch_network"),
    )
    for limit_name, count_name in checks:
        try:
            limit = int(limits.get(limit_name) or 0)
            count = int(counts.get(count_name) or 0)
        except (TypeError, ValueError):
            continue
        if limit > 0 and count >= limit:
            return limit_name
    return None


def _budget_epoch_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "")).strip("-.")
    return (slug or "task")[:80]


def _research_budget_attempt_ids(state: "PipelineState") -> set[str]:
    """Return task epochs already admitted by parent pipeline authority."""
    return {
        str(row.get("epoch") or "").strip()
        for row in (state.options.get("research_budget_epochs") or [])
        if isinstance(row, dict) and str(row.get("epoch") or "").strip()
    }


def _activate_research_budget_epoch(
    state: "PipelineState",
    handoff_dir: str,
) -> tuple[str, str, str]:
    """Bind one durable tool-budget ledger to the current pipeline task.

    All outer lanes and both synthesis attempts in one task share this SQLite
    path.  Re-entry under the same task id reuses it.  A later explicit resume
    receives a new task id and therefore a fresh bounded epoch, while prior
    ledgers and final telemetry snapshots remain under ``research_budget_epochs``.
    """
    # Unit-level callers and one legacy first-run path can enter research before
    # a queue task id has been persisted.  They still need a stable epoch, but
    # must not silently share the old root ledger.  The pipeline-scoped fallback
    # is deterministic for re-entry and a later explicit resume receives its
    # real (new) task id, so it still opens a new bounded epoch.
    task_id = str(
        state.task_id or f"initial-{state.pipeline_id}"
    ).strip()
    root = os.path.join(handoff_dir, "research_budget_epochs")
    os.makedirs(root, exist_ok=True)
    history = state.options.setdefault("research_budget_epochs", [])
    if not isinstance(history, list):
        history = []
        state.options["research_budget_epochs"] = history
    for row in history:
        if isinstance(row, dict) and str(row.get("task_id") or "") == task_id:
            db_path = str(row.get("db_path") or "")
            telemetry_path = str(
                row.get("telemetry_path")
                or os.path.join(handoff_dir, "research_budget.json")
            )
            epoch = str(row.get("epoch") or task_id)
            if db_path:
                return db_path, telemetry_path, epoch

    max_epochs = max(1, int(getattr(Config, "RESEARCH_BUDGET_MAX_EPOCHS", 3) or 3))
    if len(history) >= max_epochs:
        raise RuntimeError(
            "research budget epoch limit reached; inspect preserved evidence and "
            "increase RESEARCH_BUDGET_MAX_EPOCHS only with explicit cost approval"
        )

    ordinal = len(history) + 1
    epoch = task_id
    epoch_dir = os.path.join(
        root, f"epoch-{ordinal:03d}-{_budget_epoch_slug(task_id)}")
    os.makedirs(epoch_dir, exist_ok=True)
    telemetry_path = os.path.join(handoff_dir, "research_budget.json")
    if os.path.isfile(telemetry_path):
        previous = history[-1] if history and isinstance(history[-1], dict) else None
        archive = os.path.join(
            str(previous.get("epoch_dir") if previous else epoch_dir),
            "final_research_budget.json" if previous else "legacy_research_budget.json",
        )
        try:
            shutil.copy2(telemetry_path, archive)
            if previous is not None:
                previous["telemetry_archive"] = archive
            else:
                state.options["legacy_research_budget_telemetry"] = archive
        except OSError as exc:
            raise RuntimeError(
                f"could not archive prior research budget telemetry: {exc}"
            ) from exc

    db_path = os.path.join(epoch_dir, "research_budget.sqlite3")
    row = {
        "ordinal": ordinal,
        "epoch": epoch,
        "task_id": task_id,
        "epoch_dir": epoch_dir,
        "db_path": db_path,
        "telemetry_path": telemetry_path,
        "created_at": _utcnow(),
    }
    history.append(row)
    state.options["research_budget_epoch"] = row
    legacy_db = os.path.join(handoff_dir, "research_budget.sqlite3")
    if os.path.isfile(legacy_db):
        state.options.setdefault("legacy_research_budget_db", legacy_db)

    from ..utils.atomic import write_json_atomic

    write_json_atomic(telemetry_path, {
        "schema_version": 1,
        "run_id": state.pipeline_id,
        "epoch": epoch,
        "created_at": time.time(),
        "updated_at": time.time(),
        "degraded": False,
        "tool_budget_enabled": True,
        "limits": {
            "attempts_global": int(getattr(
                Config, "RESEARCH_BUDGET_ATTEMPTS_GLOBAL", 1800)),
            "search_global": int(getattr(
                Config, "RESEARCH_BUDGET_SEARCH_GLOBAL", 900)),
            "search_lane": int(getattr(
                Config, "RESEARCH_BUDGET_SEARCH_LANE", 360)),
            "fetch_global": int(getattr(
                Config, "RESEARCH_BUDGET_FETCH_GLOBAL", 450)),
            "fetch_lane": int(getattr(
                Config, "RESEARCH_BUDGET_FETCH_LANE", 180)),
        },
        "global": {},
        "lanes": {},
    })
    PipelineManager.save(state)
    return db_path, telemetry_path, epoch


def _synthesis_recovery_budget_epoch(
    state: "PipelineState",
    handoff_dir: str,
) -> tuple[str, str, str]:
    """Reuse an unexhausted synthesis-only epoch after a code/quality failure.

    Evidence collection resumes receive a fresh bounded epoch.  Global
    synthesis, however, performs no search/fetch work.  If a prior
    synthesis-only attempt failed after generation while its tool ledger is
    still unexhausted, consuming another epoch buys no additional evidence and
    can strand an otherwise recoverable pipeline at the global epoch cap.
    """
    recovery = state.options.get("synthesis_recovery")
    current = state.options.get("research_budget_epoch")
    if (
        isinstance(recovery, dict)
        and recovery.get("attempted") is True
        and recovery.get("passed") is False
        and isinstance(current, dict)
    ):
        db_path = str(current.get("db_path") or "")
        telemetry_path = str(
            current.get("telemetry_path")
            or os.path.join(handoff_dir, "research_budget.json")
        )
        epoch = str(current.get("epoch") or "")
        if (
            db_path
            and telemetry_path
            and epoch
            and _research_budget_exhaustion(telemetry_path, epoch) is None
        ):
            state.options["synthesis_recovery_budget_reused"] = {
                "epoch": epoch,
                "ordinal": current.get("ordinal"),
                "reused_at": _utcnow(),
                "reason": "prior synthesis-only failure with unexhausted tool ledger",
            }
            PipelineManager.save(state)
            return db_path, telemetry_path, epoch
    return _activate_research_budget_epoch(state, handoff_dir)


_SYNTHESIS_PROVIDER_UNAVAILABLE_MARKERS = (
    "modelprovidersunavailable",
    "rate limit",
    "ratelimiterror",
    "token plan",
    "quota exhausted",
    "2056",
    "auth_unavailable",
    "no auth available",
)


def _synthesis_provider_unavailable(error: Any) -> bool:
    text = str(error or "").casefold()
    return any(marker in text for marker in _SYNTHESIS_PROVIDER_UNAVAILABLE_MARKERS)


# Research-child knob forwarding registry: (Config attribute, kind).  The parent
# writes each entry's Config value into the child env, so the backend's Config
# is the single source of truth and an ambient os.environ value never decides.
# RESEARCH_CHILD_KNOBS reach every engine; RESEARCH_CHILD_V3_KNOBS only a v3
# child.  A work package that forwards a Config knob adds exactly one entry,
# keeping each table alphabetical; every name must exist on Config and be
# documented in .env.example (test_orchestrator_research_wiring checks both).
RESEARCH_CHILD_KNOBS: tuple[tuple[str, str], ...] = (
    ("PREDICTION_MARKETS_END_DATE_GATE", "bool"),
    ("PREDICTION_MARKETS_END_DATE_GRACE_HOURS", "float"),
    ("RESEARCH_EVIDENCE_GRADING", "bool"),
    ("RESEARCH_FORECAST_INPUTS", "bool"),
    ("RESEARCH_SOURCE_TAXONOMY", "bool"),
)
RESEARCH_CHILD_V3_KNOBS: tuple[tuple[str, str], ...] = (
    ("RECORD_MODEL_PROVENANCE", "bool"),
    ("RESEARCH_ABSENCE_DISCIPLINE", "bool"),
    ("RESEARCH_AS_OF_PIN", "bool"),
    ("RESEARCH_EVIDENCE_QUOTES", "str"),
    ("RESEARCH_EVIDENCE_SUPPORTS", "bool"),
    ("RESEARCH_QUANT_TYPING", "bool"),
    ("RESEARCH_QUESTION_SPEC", "bool"),
    ("RESEARCH_SOURCE_DATES", "bool"),
    ("RESEARCH_SOURCE_DATE_TEXT_FALLBACK", "bool"),
    ("RESEARCH_V3_FORECAST_INPUTS", "bool"),
    ("RESEARCH_VERIFIED_FACTS", "bool"),
)
# Child-env text per registry kind: bools are 'true'/'false', never '1'/'0'.
_RESEARCH_KNOB_FORMATTERS: dict[str, Callable[[Any], str]] = {
    "bool": lambda value: "true" if value else "false",
    "int": lambda value: str(int(value)),
    "float": lambda value: str(float(value)),
    "str": str,
}


def _forward_research_knobs(env: dict[str, str],
                            table: tuple[tuple[str, str], ...]) -> None:
    """Write each registry knob's Config value into the research child ``env``.

    A name missing from Config or an unknown kind raises: the registry is code,
    and a broken entry must fail loudly rather than silently leave the child on
    its own default.
    """
    for name, kind in table:
        formatter = _RESEARCH_KNOB_FORMATTERS.get(kind)
        if formatter is None:
            raise ValueError(f"research child knob {name}: unknown kind {kind!r}")
        env[name] = formatter(getattr(Config, name))


def _configure_research_budget_env(
    env: dict[str, str],
    handoff_dir: str,
    *,
    budget_db_path: Optional[str] = None,
    budget_lane_id: Optional[str] = None,
    budget_telemetry_path: Optional[str] = None,
    budget_run_id: Optional[str] = None,
    budget_epoch: Optional[str] = None,
) -> None:
    """Inject the shared LOOP-007 ledger contract into one research process.

    All descendants inherit these values.  Disabling the feature removes any
    stale variables copied from the backend process so an operator can reliably
    turn the control plane off for a diagnostic run.
    """
    if not bool(getattr(Config, "RESEARCH_BUDGET_ENABLED", True)):
        for key in _RESEARCH_BUDGET_ENV_KEYS:
            env.pop(key, None)
        return
    env["RESEARCH_BUDGET_DB"] = str(
        budget_db_path or os.path.join(handoff_dir, "research_budget.sqlite3"))
    env["RESEARCH_BUDGET_TELEMETRY_PATH"] = str(
        budget_telemetry_path or os.path.join(handoff_dir, "research_budget.json"))
    env["RESEARCH_BUDGET_LANE_ID"] = str(budget_lane_id or "outer-track-1")
    if budget_run_id:
        env["RESEARCH_BUDGET_RUN_ID"] = str(budget_run_id)
    else:
        env.pop("RESEARCH_BUDGET_RUN_ID", None)
    if budget_epoch:
        env["RESEARCH_BUDGET_EPOCH"] = str(budget_epoch)
    else:
        env.pop("RESEARCH_BUDGET_EPOCH", None)
    env["RESEARCH_BUDGET_ATTEMPTS_GLOBAL"] = str(getattr(
        Config, "RESEARCH_BUDGET_ATTEMPTS_GLOBAL", 1800))
    env["RESEARCH_BUDGET_SEARCH_GLOBAL"] = str(getattr(
        Config, "RESEARCH_BUDGET_SEARCH_GLOBAL", 900))
    env["RESEARCH_BUDGET_SEARCH_LANE"] = str(getattr(
        Config, "RESEARCH_BUDGET_SEARCH_LANE", 360))
    env["RESEARCH_BUDGET_FETCH_GLOBAL"] = str(getattr(
        Config, "RESEARCH_BUDGET_FETCH_GLOBAL", 450))
    env["RESEARCH_BUDGET_FETCH_LANE"] = str(getattr(
        Config, "RESEARCH_BUDGET_FETCH_LANE", 180))
    env["RESEARCH_NEGATIVE_CACHE_TTL_SECONDS"] = str(getattr(
        Config, "RESEARCH_NEGATIVE_CACHE_TTL_SECONDS", 600))
    env["RESEARCH_NEGATIVE_CACHE_RETRIES"] = str(getattr(
        Config, "RESEARCH_NEGATIVE_CACHE_RETRIES", 1))


def _flush_failed_research_attempt_spend(spend: Optional[dict[str, Any]],
                                         attempt_status: str,
                                         run_id: Optional[str] = None) -> bool:
    """DEFECT-2：把一次**未成功**研究 attempt 已累计的 token 花费计入统一计量。

    审计取证（31.9M 实耗 vs 5.35M 入账）：per-attempt 的 _tok_in/_tok_out 在每次研究
    子进程启动时清零、research_telemetry 只在成功路径构建、_record_research_telemetry
    是研究花费进 LLMMeter 的唯一入口——失败/超时/SIGTERM/取消把整个 attempt 的账直接
    丢掉。本函数由 :meth:`DeerFlowResearchRunner.run` 包装层在异常出口调用，向 LLMMeter
    写一条 stage='research' 的合成记录（provider/model 映射与 _record_research_telemetry
    完全一致）。

    恰好一次 / 不与成功路径重复：``spend['flushed']`` 置位保证幂等；包装层只在异常出口
    调用（成功 return 的 attempt 仍由调用方经 _record_research_telemetry 入账，成功路径
    逐字节不变）。LLMMeter 记录 schema 无附加字段位，attempt_status 无法进计量行——以
    告警日志留痕（含 status 与 token 数）作可审计标签。

    返回是否真的写了计量记录（无 token / 计量关闭 / 已 flush → False）。
    """
    if not isinstance(spend, dict) or spend.get("flushed"):
        return False
    spend["flushed"] = True
    t_in = int(spend.get("tokens_in") or 0)
    t_out = int(spend.get("tokens_out") or 0)
    if t_in <= 0 and t_out <= 0:
        return False  # 该研究模型未报 usage → 无可计量 token
    if not bool(getattr(Config, "LLM_TELEMETRY_ENABLED", True)):
        return False
    try:
        # EVAL-17: 进审计日志，也作 prompt_cache_read_tokens 进计量；脏值退回 0，绝不影响入账本身。
        t_cached = max(0, int(spend.get("tokens_cached") or 0))
    except (TypeError, ValueError, OverflowError):
        t_cached = 0
    try:
        from ..utils.telemetry import LLMMeter
        model = str(spend.get("model") or getattr(Config, "DEERFLOW_MODEL", "claude"))
        # 与 _record_research_telemetry 相同的计价 provider 映射：CLI 订阅类（claude/
        # codex）边际成本 0，其余复用同名 provider 的定价表（缺失则成本 0，仍记 token）。
        provider = "claude-cli" if model in ("claude", "codex") else model
        try:
            wall_ms = max(0.0, time.time() - float(spend.get("t_start") or 0.0)) * 1000.0 \
                if spend.get("t_start") else 0.0
        except (TypeError, ValueError):
            wall_ms = 0.0
        LLMMeter.record(
            provider=provider,
            model=model,
            prompt_tokens=t_in,
            completion_tokens=t_out,
            latency_ms=wall_ms,
            stage=STAGE_RESEARCH,
            run_id=str(run_id) if run_id else None,  # None → contextvar/单活跃 run 回退
            prompt_cache_read_tokens=t_cached,
            aggregate=True,  # INFRA-8: the child's whole spend, no call's requested model
        )
        logger.warning(
            "研究 attempt 以 %s 终止，已消耗 tokens in=%d out=%d cached=%d（model=%s）——"
            "已计入 stage='research' 合成计量，不再随失败丢账",
            attempt_status, t_in, t_out, t_cached, model,
        )
        return True
    except Exception as exc:  # noqa: BLE001 — 计量是观测增益，绝不放大原始失败
        logger.debug("失败研究 attempt 的花费计量跳过: %s", exc)
        return False


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
    def run(prompt: str, handoff_dir: str, *,
            model: Optional[str] = None,
            budget_run_id: Optional[str] = None,
            **kwargs: Any) -> dict[str, Any]:
        """DEFECT-2 花费护栏包装层：签名/行为与 :meth:`_run_attempt` 一致（后者持有
        完整参数契约与文档），唯一差异是给 attempt 挂一个共享 tally（``_spend``），并在
        **任何异常出口**（失败/超时/收尾杀/取消）把已累计的 token 恰好一次地计入
        stage='research' 计量——成功 return 不在此计量（仍由调用方经
        _record_research_telemetry 入账），故成功路径逐字节不变、绝无双计。
        """
        spend: dict[str, Any] = {
            "tokens_in": 0, "tokens_out": 0, "tokens_total": 0, "tokens_cached": 0,
            "t_start": time.time(),
            "model": model or Config.DEERFLOW_MODEL,
            "flushed": False,
        }
        try:
            return DeerFlowResearchRunner._run_attempt(
                prompt, handoff_dir, model=model, budget_run_id=budget_run_id,
                _spend=spend, **kwargs)
        except PipelineCancelled:
            _flush_failed_research_attempt_spend(spend, "cancelled", run_id=budget_run_id)
            raise
        except BaseException as exc:
            _flush_failed_research_attempt_spend(
                spend, f"failed({type(exc).__name__})", run_id=budget_run_id)
            raise

    @staticmethod
    def _run_attempt(
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
        resume: bool = False,
        kg_graph_id: Optional[str] = None,
        budget_db_path: Optional[str] = None,
        budget_lane_id: Optional[str] = None,
        budget_telemetry_path: Optional[str] = None,
        budget_run_id: Optional[str] = None,
        budget_epoch: Optional[str] = None,
        resume_attempt_id: Optional[str] = None,
        resume_checkpoint_id: Optional[str] = None,
        max_concurrent_subagents: Optional[int] = None,
        model_concurrency_global: Optional[int] = None,
        dual_track: Optional[bool] = None,
        shared_actor_track: Optional[bool] = None,
        evidence_only: bool = False,
        synthesis_manifest_path: Optional[str] = None,
        research_engine: Optional[str] = None,
        as_of: Optional[str] = None,
        pit: Optional[dict[str, Any]] = None,
        _spend: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """运行研究子进程，阻塞直到结束。返回 handoff 摘要。

        DEFECT-2 ``_spend``：:meth:`run` 包装层注入的 attempt 级共享 tally。读循环把
        [usage] 行的 token 数同步写入该 dict，使包装层在异常出口仍能拿到已烧掉的账
        （旧实现里这些局部变量随异常蒸发——31.9M vs 5.35M 差账的机制）。None（直接
        调用 _run_attempt / 旧测试桩）时行为与历史逐字节一致。

        ITEM-3 ``resume``：True 时给子进程加 ``--resume``——bridge 若在 handoff_dir 找到
        question_hash 匹配的 research_checkpoint.json，就复用其 LangGraph thread、跳过已完成
        pass、从下一 pass 续跑（否则全量重启）。调用方仅在既存 checkpoint 时置 True（崩溃/超时
        重试路径），故正常首跑逐字节不变。

        ``resume_attempt_id`` / ``resume_checkpoint_id`` are parent-validated
        lineage, distinct from the fresh physical budget database allocated to
        a later explicit pipeline task.  They let the strict bridge reuse only
        the exact prior thread/pass checkpoint without weakening its run,
        question, lane, attempt, or checkpoint-identity checks.

        ``research_engine``: the engine the run's research stage selected
        (:func:`research_engine_for_run`); ``None`` means
        ``Config.RESEARCH_ENGINE``.  Lane-contract invocations (evidence-only,
        synthesis manifest) always run the legacy engine regardless.

        TIME-7 ``as_of``: a pinned hindcast's as-of date (``hindcast_policy_v1``).
        The child then gets ``RESEARCH_AS_OF`` (the v3 plan, brief and actors are
        dated to it), ``PREDICTION_MARKETS_ENABLED=false`` and
        ``RESEARCH_AS_OF_PIN=true``, written after every Config forward so they
        win.  Only v3 honours it: any other engine raises RuntimeError before a
        file or process exists, and a watchdog timeout that leaves no actors.json
        raises ``hindcast_salvage_refused`` instead of launching the legacy
        ``--extract-only`` salvage.  An ambient ``RESEARCH_AS_OF`` never reaches a
        child (live runs stay live).

        TIME-8 ``pit``: the pinned hindcast's ``hindcast_policy_v1['pit']`` block.  With
        ``as_of`` set and ``pit['gates']`` True the child gets ``RESEARCH_PIT_GATES`` /
        ``_SAME_DAY`` / ``_UNDATED`` / ``_PROVIDER_BOUNDS`` / ``_OVERFETCH`` from that block
        (never from the current Config, so a resume keeps the admitted gates) and
        ``RESEARCH_SOURCE_DATES=true``, written after the as-of exports; otherwise every
        ``RESEARCH_PIT_*`` key is removed, so an ambient value never half-activates gates.

        W9-9 ``kg_graph_id``：非空且 RESEARCH_MCP_KG 开启时，把 DEER_FLOW_EXTENSIONS_CONFIG_PATH
        指向部署目录的 extensions_config.json 并注入 DRF_MCP_KG_GRAPH_ID——研究子进程可经 MCP
        （kg_search/kg_trace_cascade 等）直查既有基线图谱。调用方仅在图谱已存在的路径
        （fork/continue/resume-with-graph）传入；首跑传 None，env 与今日逐字节一致。

        Raises:
            PipelineCancelled: cancel_event 被置位（用户取消），子进程组已被终止。
            RuntimeError: 子进程失败、超时或未产出报告。
        """
        # Engine v3: the parent — never ambient env inheritance — decides which
        # research engine the child runs, using the same resolver as the
        # outer-lane topology so the two cannot disagree.  Evidence lanes and
        # global synthesis are lane contracts only the legacy engine implements,
        # so those invocations always declare it explicitly.
        research_engine = (
            RESEARCH_ENGINE_LEGACY
            if (evidence_only or synthesis_manifest_path)
            else (resolve_research_engine(research_engine) if research_engine
                  else resolve_research_engine())
        )
        if as_of and research_engine != RESEARCH_ENGINE_V3:
            # TIME-7: a pinned as-of is honoured only by v3 (legacy would roll it forward
            # to the run date).  Fail before any file, process or spend exists.
            raise RuntimeError(
                f"hindcast_engine_mismatch: as_of {as_of} requires the v3 research engine, "
                f"not {research_engine}")
        deerflow_dir = Config.DEERFLOW_DIR
        script = os.path.join(deerflow_dir, "deerflow_research.py")
        if not os.path.isdir(deerflow_dir):
            raise RuntimeError(f"DeerFlow 目录不存在: {deerflow_dir}（设置 DEERFLOW_DIR）")
        if not os.path.exists(script):
            raise RuntimeError(f"未找到 deerflow_research.py: {script}")
        skill_sync_result = _sync_deerflow_bridge_if_stale(deerflow_dir)

        os.makedirs(handoff_dir, exist_ok=True)
        expected_artifact_path = os.path.join(
            handoff_dir,
            "evidence_pack.md" if evidence_only else "research_report.md",
        )

        def _artifact_fingerprint(path: str) -> Optional[tuple[int, str]]:
            try:
                size = os.path.getsize(path)
                digest = _sha256_file(path)
                return (size, digest or "") if digest is not None else None
            except OSError:
                return None

        artifact_before = _artifact_fingerprint(expected_artifact_path)

        def _fresh_expected_artifact() -> bool:
            current = _artifact_fingerprint(expected_artifact_path)
            artifact_text = _read_text(expected_artifact_path)
            return (
                current is not None
                and current != artifact_before
                and len(artifact_text.strip()) >= 400
                and not (
                    evidence_only
                    and _evidence_pack_is_control_failure_only(artifact_text)
                )
            )
        # 把（可能敏感的）研究问题写入文件，经 --prompt-file 传给子进程，避免出现在
        # ps / /proc/<pid>/cmdline 里（EXECPLAN2 F-0-7/F-13-3，与 llm_client 既有约定一致）。
        # run() 会阻塞到子进程退出，子进程启动时即读取该文件，故可在 finally 安全删除。
        fd, prompt_file = tempfile.mkstemp(prefix=".prompt-", suffix=".txt", dir=handoff_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as _pf:
            _pf.write(prompt)
        try:
            os.chmod(prompt_file, 0o600)
        except OSError:
            pass
        cmd = _detect_deerflow_python(deerflow_dir) + [
            script,
            "--prompt-file", prompt_file,
            "--out-dir", handoff_dir,
            "--model", model or Config.DEERFLOW_MODEL,
            "--depth", depth or Config.DEERFLOW_RESEARCH_DEPTH,
        ]
        lang = language if language is not None else Config.DEERFLOW_RESEARCH_LANGUAGE
        if lang:
            cmd += ["--target-language", lang]
        if (subagents if subagents is not None else Config.DEERFLOW_SUBAGENTS):
            cmd += ["--subagents"]
        # ITEM-3：崩溃/超时重试时若 handoff_dir 已有 checkpoint，续跑而非全量重启。
        if resume:
            cmd += ["--resume"]
        if evidence_only:
            cmd += ["--evidence-only"]
        if synthesis_manifest_path:
            cmd += ["--synthesis-manifest", str(synthesis_manifest_path)]

        # 看门狗预算按研究深度缩放：deep 是多轮研究协议（source map →
        # primary evidence → actors → contradictions → forecast implications →
        # synthesis），在固定 2400s 下经常被无差别 SIGKILL。优先级（T6.6）：显式 timeout 参数 >
        # 用户在 .env 里显式设置的 DEERFLOW_RESEARCH_TIMEOUT > Config.deerflow_depth_budget() 档位默认值
        # （CONF-1：档位值在双轨/子代理/扇出开启时 ×1.5，避免并行模式下更重的协议被无差别 SIGKILL）。
        # 在构造子进程 env 之前算出，使 v3 引擎能按同一预算规划各阶段（见下方 RESEARCH_ENGINE）。
        effective_depth = (depth or Config.DEERFLOW_RESEARCH_DEPTH or "standard").lower()
        if timeout:
            budget = timeout
        elif os.environ.get("DEERFLOW_RESEARCH_TIMEOUT", "").strip():
            budget = Config.DEERFLOW_RESEARCH_TIMEOUT
        else:
            budget = Config.deerflow_depth_budget(effective_depth)

        env = dict(os.environ)
        env.setdefault("PYTHONUNBUFFERED", "1")
        # Checkpoint identity is parent-owned per launch; never inherit an
        # ambient value from the backend process into a different handoff.
        env.pop("RESEARCH_CHECKPOINT_ID", None)
        # TIME-7: so is the research as-of — only a pinned hindcast sets it (below).
        env.pop("RESEARCH_AS_OF", None)
        env["RESEARCH_ENGINE"] = research_engine
        if research_engine == RESEARCH_ENGINE_V3:
            # v3 caps its own wall-clock plan at 0.85 × this value so it writes
            # research_report.md before the watchdog's SIGKILL; hand it the
            # effective watchdog budget (explicit timeout / .env / depth tier)
            # rather than only an operator-set .env value it may not match.
            env["DEERFLOW_RESEARCH_TIMEOUT"] = str(max(1, int(budget)))
        if isinstance(skill_sync_result, dict):
            # The child re-hashes the exact live directories before constructing
            # a research client.  This binds source/deployed manifest identities,
            # lazy-resource hashes, sync outcome, and deployed path into its
            # durable research_meta.json and progress log.
            env["DRF_RUNTIME_SKILL_SYNC_REQUIRED"] = "1"
            env["DRF_RUNTIME_SKILL_SYNC"] = json.dumps(
                skill_sync_result,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
        # T6.6: deep 开场 pass 的递归上限从 Config 单一真源下发给子进程（旧版在 bridge 内直接读
        # os.environ）。Config 属性本身读 env（默认 220），故此处覆盖即「Config 即真源」。
        env["DEERFLOW_DEEP_OPENING_RECURSION_LIMIT"] = str(Config.DEERFLOW_DEEP_OPENING_RECURSION_LIMIT)
        # 双轨研究开关：常规运行默认跟随 Config。Evidence-only 外轨必须显式分配
        # ownership：仅 broad baseline 以 ``dual_track=True`` 同时生产共享 Track B；
        # 其它 evidence lane 即便全局 Config 开启，也保持 actor-free。这样三轨默认架构
        # 精确运行一份共享 actor intelligence，而不是 0 份或 K 份。
        _dual_track_requested = (
            bool(dual_track)
            if dual_track is not None
            else (
                False if evidence_only
                else bool(getattr(Config, "DEERFLOW_DUAL_TRACK", True))
            )
        )
        _dual_track_enabled = _dual_track_requested
        env["DEERFLOW_DUAL_TRACK"] = (
            "true" if _dual_track_enabled else "false")
        _shared_actor_track = (
            bool(shared_actor_track)
            if shared_actor_track is not None
            else False
        )
        env["RESEARCH_SHARED_ACTOR_TRACK"] = (
            "true" if _shared_actor_track else "false")
        # CONF-1：深度扇出开关/宽度同样从 Config 单一真源下发给 bridge（bridge 侧经
        # _env_flag/os.environ 读取，自带默认值）。不下发时 Config 里的默认（true/8）对
        # 研究子进程静默失效（与 ACTOR_CAST_MAX 曾经的漂移同因）。
        env["RESEARCH_DEEP_FANOUT"] = (
            "true" if getattr(Config, "RESEARCH_DEEP_FANOUT", True) else "false")
        env["RESEARCH_FANOUT_WIDTH"] = str(getattr(Config, "RESEARCH_FANOUT_WIDTH", 8))
        # ACTOR-CAST discipline：主角色上限 + 媒体降级从 Config 单一真源下发给 bridge
        # （抽取提示词的 actor 范围、enforce_actor_cast 的截断/降级都按此执行）。
        env["ACTOR_CAST_MAX"] = str(getattr(Config, "ACTOR_CAST_MAX", 20))
        env["ACTOR_EXCLUDE_MEDIA"] = "true" if getattr(Config, "ACTOR_EXCLUDE_MEDIA", True) else "false"
        # ORCH-1(3): Polymarket 预测市场快照参数同样从 Config 单一真源下发给 bridge
        # （bridge 侧经 _env_flag/os.environ 读取）。不下发时子进程只看到自己的 env 默认值，
        # 后端 .env 里的配置对研究子进程静默失效（与 ACTOR_CAST_MAX 曾经的漂移同因）。
        env["PREDICTION_MARKETS_ENABLED"] = (
            "true" if getattr(Config, "PREDICTION_MARKETS_ENABLED", True) else "false")
        env["PREDICTION_MARKETS_MAX"] = str(getattr(Config, "PREDICTION_MARKETS_MAX", 20))
        env["PREDICTION_MARKETS_MIN_VOLUME"] = str(getattr(Config, "PREDICTION_MARKETS_MIN_VOLUME", 200.0))
        env["PREDICTION_MARKETS_MAX_PER_EVENT"] = str(getattr(Config, "PREDICTION_MARKETS_MAX_PER_EVENT", 3))
        env["PREDICTION_MARKETS_PER_QUERY"] = str(getattr(Config, "PREDICTION_MARKETS_PER_QUERY", 15))
        env["PREDICTION_MARKETS_MIN_RELEVANCE"] = str(
            getattr(Config, "PREDICTION_MARKETS_MIN_RELEVANCE", 5.0))
        # Registry-forwarded knobs (RESEARCH_CHILD_KNOBS / RESEARCH_CHILD_V3_KNOBS):
        # Config decides, never ambient env.
        _forward_research_knobs(env, RESEARCH_CHILD_KNOBS)
        if research_engine == RESEARCH_ENGINE_V3:
            _forward_research_knobs(env, RESEARCH_CHILD_V3_KNOBS)
        if as_of:
            # TIME-7 pinned hindcast (v3 only, checked above).  Written after the inline
            # PREDICTION_MARKETS_* lines and the registry forward so these values win: the
            # child dates its plan/brief/actors to as_of, never snapshots live Polymarket odds
            # (they would leak the outcome), and never adopts a model-supplied as-of.
            env["RESEARCH_AS_OF"] = as_of
            env["PREDICTION_MARKETS_ENABLED"] = "false"
            env["RESEARCH_AS_OF_PIN"] = "true"
        # TIME-8: the point-in-time gates come only from the admission pin's 'pit' block
        # (never Config, never ambient env) and only for a pinned hindcast; written after
        # the as-of exports and the registry forward, so RESEARCH_SOURCE_DATES is on.
        for _pit_key in [key for key in env if key.startswith(PIT_RESEARCH_ENV_PREFIX)]:
            env.pop(_pit_key)
        if as_of:
            env.update(pit_research_env(pit))
        # RESEARCH-1: fetch-layer shell detection and the per-call fetch bound
        # come from Config too (cached_fetch / research_gateway / linear_research
        # read them from os.environ with the same defaults).
        env["RESEARCH_FETCH_SHELL_DETECTION"] = (
            "true" if getattr(Config, "RESEARCH_FETCH_SHELL_DETECTION", True) else "false")
        env["RESEARCH_FETCH_CALL_TIMEOUT_S"] = str(
            max(0, int(getattr(Config, "RESEARCH_FETCH_CALL_TIMEOUT_S", 150))))
        if max_concurrent_subagents is not None:
            env["DEER_FLOW_MAX_CONCURRENT_SUBAGENTS"] = str(
                max(1, min(8, int(max_concurrent_subagents))))
        if model_concurrency_global is not None:
            env["RESEARCH_MODEL_CONCURRENCY_GLOBAL"] = str(
                max(1, int(model_concurrency_global)))
        env["RESEARCH_GLOBAL_SUBAGENT_CAP"] = str(
            max(1, int(getattr(Config, "RESEARCH_GLOBAL_SUBAGENT_CAP", 9))))
        # LOOP-009: prediction_market_search runs inside the DeerFlow agent and
        # previously returned useful markets only into chat history.  Give the
        # reflected tool a trusted, per-track artifact root so it can append a
        # provenance ledger that the deterministic post-pass later reconciles.
        env["DEERFLOW_RUN_ARTIFACT_DIR"] = os.path.realpath(handoff_dir)
        _configure_research_budget_env(
            env,
            handoff_dir,
            budget_db_path=budget_db_path,
            budget_lane_id=budget_lane_id,
            budget_telemetry_path=budget_telemetry_path,
            budget_run_id=budget_run_id,
            budget_epoch=budget_epoch,
        )
        if resume and str(resume_attempt_id or "").strip():
            # Checkpoint lineage and cost-ledger allocation are distinct
            # authorities on explicit resume.  The new DB remains bounded and
            # isolated, while the strict bridge receives the prior attempt ID
            # that its checkpoint was sealed against.
            env["RESEARCH_BUDGET_RUN_ID"] = str(budget_run_id or "").strip()
            env["RESEARCH_BUDGET_LANE_ID"] = str(budget_lane_id or "").strip()
            env["RESEARCH_BUDGET_EPOCH"] = str(resume_attempt_id).strip()
            if str(resume_checkpoint_id or "").strip():
                # Bind the bridge to the exact parent-validated checkpoint,
                # including its thread and completed-pass state.  A mutation
                # between parent admission and child startup must fail closed
                # instead of becoming a different, self-consistent resume.
                env["RESEARCH_CHECKPOINT_ID"] = str(
                    resume_checkpoint_id
                ).strip()
        # Model-call leases are a correctness boundary, not merely a tool-cost
        # budget. Keep their shared SQLite path even when tool-budget admission
        # is explicitly disabled, so outer processes cannot multiply provider
        # streams behind the user's concurrency cap.
        env["RESEARCH_MODEL_LEASE_DB"] = os.path.realpath(
            getattr(Config, "RESEARCH_MODEL_LEASE_DB", "")
            or os.path.join(Config.UPLOAD_FOLDER, "research_model_leases.sqlite3"))
        # W9-9：图谱已存在（fork/continue/resume-with-graph）时把 KG MCP server 暴露给研究子进程。
        # extensions_config.json 由 _sync_deerflow_bridge_if_stale 同步到部署目录；两台 server 均
        # 设计为图谱缺失时返回结构化错误、绝不 hang（见该文件 _comment），接线本身 degrade-safe。
        if kg_graph_id and bool(getattr(Config, "RESEARCH_MCP_KG", True)):
            _ext_cfg = os.path.join(deerflow_dir, "extensions_config.json")
            if os.path.isfile(_ext_cfg):
                env["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = _ext_cfg
                env["DRF_MCP_KG_GRAPH_ID"] = str(kg_graph_id)
                logger.info("研究子进程已接入 KG MCP（graph_id=%s）", kg_graph_id)
            else:
                logger.warning(
                    "RESEARCH_MCP_KG 开启且 graph_id=%s，但部署目录缺 extensions_config.json"
                    "——跳过 MCP 接线（研究照常运行）", kg_graph_id)

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

        # 看门狗截止时刻从子进程真正启动起算（budget 已在构造 env 前按深度/显式值算好）。
        deadline = time.time() + budget
        # 看门狗：即使子进程长时间无输出（模型思考），也能在超时后被杀掉。
        timed_out = {"hit": False}
        timeout_salvaged = {"hit": False}

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

        # LOOP-008: 进度由显式研究里程碑限定在各自区间；tool/result 只负责区间内的
        # 平滑移动。旧公式 ``10 + tool_calls * 4`` 在开场 20 次调用后就跳到 90%，
        # 随后的数小时合成/抽取完全没有可见进展。
        estimator = ResearchProgressEstimator()
        local = estimator.progress
        tool_events = 0
        last_line = ""
        # I-5-7: 结构化研究阶段遥测（token/工具量/壁钟）。bridge 已在 stdout 发出 [usage] 行，
        # 此前只用于推进进度启发，token 数字被丢弃；这里顺带累加，使最贵的研究阶段也进入统一计量。
        _tok_in = _tok_out = _tok_total = 0
        # Engine v3: provider prompt-cache reads (subset of tokens_in) from the
        # optional ``cached=`` usage field; stays 0 for engines that omit it.
        _tok_cached = 0
        _result_events = 0
        _t_start = time.time()
        if _spend is not None:
            _spend["t_start"] = _t_start  # 精确到读循环起点（扣除启动/同步开销）
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.rstrip("\n")
                if not line:
                    continue
                last_line = line
                local = estimator.observe(line)
                # 解析进度日志的事件类型 [tool]/[result]/[stage]/[ok]/[done]/[error]/[usage]
                if "[tool]" in line:
                    tool_events += 1
                    on_progress(local, _tail(line))
                elif "[result]" in line:
                    _result_events += 1
                    on_progress(local, _tail(line))
                elif "[stage]" in line:
                    # ResearchProgressEstimator already reserves honest bands for
                    # synthesis/extraction/finalization.  The legacy 92 cap would
                    # now regress a 95% track when triangulation emits [stage].
                    on_progress(local, _tail(line))
                elif "[usage]" in line:
                    # I-5-7: 仅累加 token，不动进度（usage 行非进度信号）。
                    parsed = _parse_usage_line(line)
                    if parsed is not None:
                        _i, _o, _t = parsed
                        _tok_in += _i
                        _tok_out += _o
                        _tok_total += (_t if _t else _i + _o)
                        _tok_cached += _parse_usage_cached_tokens(line)
                        if _spend is not None:
                            # DEFECT-2：同步进 attempt 级共享 tally，异常出口不丢账。
                            _spend["tokens_in"] = _tok_in
                            _spend["tokens_out"] = _tok_out
                            _spend["tokens_total"] = _tok_total
                            _spend["tokens_cached"] = _tok_cached
                elif "[ok]" in line or "[done]" in line:
                    on_progress(local, _tail(line))
                elif "[error]" in line:
                    on_progress(local, _tail(line))
                elif "[init]" in line:
                    on_progress(max(local, 4), _tail(line))
                if timed_out["hit"] or time.time() > deadline:
                    break
            try:
                returncode = proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                # W9-4：stdout 已经 EOF 但子进程组 30s 内没退出（bridge 的孙子进程/线程收尾慢）。
                # 旧行为让 TimeoutExpired 直接冒泡 → 整条轨被当失败丢弃——pipe_0f2bee 因此把
                # 2/3 条健康续跑轨（报告+checkpoint 都已落盘）判死、降级到只剩基率轨。
                # 改为：先杀进程组，再按盘上产物判定——research_report.md 完整且结构化产物/
                # checkpoint 表明协议已推进 → 该轨按存活处理；否则仍按失败抛出（信息更明确）。
                _kill_process_group(proc)
                try:
                    returncode = proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    returncode = -9  # 进程组已被 SIGKILL，wait 仍超时视作强杀
                _fresh = _fresh_expected_artifact()
                _evidence_survived = evidence_only and _fresh
                _report_survived = (
                    (not evidence_only) and _fresh
                    and _track_artifacts_survived(handoff_dir)
                )
                if _evidence_survived or _report_survived:
                    logger.warning(
                        "研究子进程收尾超时（stdout 已关闭但进程组未在 30s 内退出，exit=%s）"
                        "——盘上产物完整，按存活轨继续", returncode,
                    )
                    on_progress(95, "子进程收尾超时，但研究产物完整——按存活轨继续")
                    timeout_salvaged["hit"] = True
                    returncode = 0
                else:
                    raise RuntimeError(
                        "研究子进程收尾超时（30s）且产物不完整"
                        "（research_report.md 缺失/过短，或无结构化产物/checkpoint）——该轨失败"
                    ) from None
        finally:
            watchdog.cancel()
            if proc.poll() is None:
                _kill_process_group(proc)
            DeerFlowResearchRunner._live_procs.discard(proc)
            # 子进程已退出（或被杀），prompt 文件不再需要，删除以减小磁盘驻留面。
            try:
                os.unlink(prompt_file)
            except OSError:
                pass

        if cancelled["hit"]:
            raise PipelineCancelled("深度研究已取消")

        report_path = expected_artifact_path
        artifact_label = (
            "evidence_pack.md" if evidence_only else "research_report.md")
        if timed_out["hit"]:
            # 超时打捞：研究主报告先于 actors/sources 提取阶段落盘——若被看门狗
            # 杀掉时报告已经写出，没必要丢弃整轮研究，降级继续（仅缺结构化档案）。
            if _fresh_expected_artifact():
                if as_of and not os.path.exists(os.path.join(handoff_dir, "actors.json")):
                    # TIME-7: a pinned hindcast never degrades here.  The ITEM-14 salvage
                    # child runs the legacy engine (--extract-only is a legacy-only mode),
                    # which ignores RESEARCH_AS_OF, and going on without actors.json would
                    # anchor the simulation calendar at the run date.  Fail closed: v3's
                    # identity-bound work dir lets a resume finish only the finalize phase.
                    raise RuntimeError(
                        f"hindcast_salvage_refused: research timed out (>{budget}s) before v3 "
                        f"wrote actors.json; the legacy --extract-only salvage cannot honour "
                        f"RESEARCH_AS_OF {as_of}; resume so v3 finishes its finalize phase")
                logger.warning(
                    f"DeerFlow 研究超时（>{budget}s），但 {artifact_label} 已写出——打捞继续"
                )
                on_progress(
                    95,
                    "研究超时，但证据产物已生成——打捞继续"
                    if evidence_only else
                    "研究超时，但报告已生成——打捞继续（无结构化档案）",
                )
                timeout_salvaged["hit"] = True
                returncode = 0
                # ITEM-14：报告已落盘但结构化抽取还没跑（'无结构化档案'）。花一个有界的
                # --extract-only 子进程把 actors/sources/timeline/quantitative 抢救出来，
                # 让下游本体/图谱/模拟仍有真实结构可用，而非带着空档案降级。best-effort。
                actors_path = os.path.join(handoff_dir, "actors.json")
                _salvage_on = os.environ.get(
                    "RESEARCH_EXTRACT_ONLY_SALVAGE", "true").strip().lower() not in ("0", "false", "no")
                if (not evidence_only and _salvage_on
                        and not os.path.exists(actors_path)):
                    try:
                        _run_extract_only_salvage(
                            deerflow_dir, handoff_dir, prompt, model or Config.DEERFLOW_MODEL,
                            effective_depth, language, env, on_progress,
                        )
                    except Exception as _sv_err:  # noqa: BLE001 — 打捞绝不令研究失败
                        logger.warning("ITEM-14：extract-only 打捞异常（降级继续）: %s", _sv_err)
            else:
                raise RuntimeError(
                    f"DeerFlow 研究超时（>{budget}s，depth={effective_depth}）。"
                    "可降低研究深度，或在 .env 设更大的 DEERFLOW_RESEARCH_TIMEOUT"
                )
        if returncode != 0 and not timeout_salvaged["hit"]:
            raise RuntimeError(f"DeerFlow 研究子进程失败 (exit={returncode})：{last_line}")
        if not os.path.exists(report_path):
            raise RuntimeError(f"DeerFlow 研究未产出 {artifact_label}")

        report = _read_text(report_path)
        if not report.strip():
            raise RuntimeError(f"{artifact_label} 为空")
        # 纵深防御：即便上游漏写了降级/错误消息当报告，也别让管线拿一段错误串去
        # 建图/模拟/写报告（那会把垃圾当成功）。覆盖 DeerFlow 降级文案、原始 provider
        # 报错、以及 MiniMax 域内容审核(422 new_sensitive)等多种短错误串。
        # RES-1/RES-8 镜像：除「短 + 错误串」外再加一道裸长度下限（RESEARCH_MIN_REPORT_CHARS，
        # 默认 400，0 关闭）——旧版 bridge 部署仍在时，编排器侧兜住 <400 字符的报告残段。
        _min_chars = int(getattr(Config, "RESEARCH_MIN_REPORT_CHARS", 400) or 0)
        _rlen = len(report.strip())
        if (_min_chars and _rlen < _min_chars) or (
                _rlen < 400 and any(m in report for m in _LLM_ERROR_MARKERS)):
            raise RuntimeError(
                "DeerFlow 返回的是 LLM 降级/错误消息而非研究报告"
                "（提供方临时不可用/限流/额度、网络错误，或内容审核拦截），"
                "请稍后重试、降低研究深度，或更换模型"
            )
        if evidence_only and _evidence_pack_is_control_failure_only(report):
            raise RuntimeError(
                "DeerFlow evidence lane contains only terminal control failures "
                "(for example research_budget_exhausted); refusing synthesis admission"
            )

        # Exactly one evidence lane—the explicitly assigned broad baseline—owns
        # the shared Track-B dossier. Admission is metadata/checksum based so a
        # resumed track directory can never leak an earlier dossier. Other
        # evidence lanes always return empty actor context.
        if evidence_only:
            actor_dossier = (
                _load_fresh_evidence_lane_actor_dossier(
                    handoff_dir,
                    prompt=prompt,
                )
                if _dual_track_enabled else ""
            )
        else:
            actor_dossier = _read_text(
                os.path.join(handoff_dir, "actor_dossier.md"))
        if actor_dossier and (
                _is_degraded_dossier(actor_dossier)
                or _evidence_pack_is_control_failure_only(actor_dossier)):
            logger.warning("actor_dossier.md 疑似降级产物（错误串/过短），按缺失处理")
            actor_dossier = ""
        actors = _read_json(os.path.join(handoff_dir, "actors.json"))
        if as_of:
            # TIME-7: actors.json as_of_date anchors the simulation calendar and the persona
            # as-of lines.  A pinned hindcast is returned only when the child dated it to the
            # pin; anything else (no actors.json, another date) fails closed and stays resumable.
            _actors_as_of = actors.get("as_of_date") if isinstance(actors, dict) else None
            if _actors_as_of != as_of:
                raise RuntimeError(
                    f"hindcast_as_of_mismatch: actors.json as_of_date {_actors_as_of!r} is not the "
                    f"pinned as_of {as_of}; resume so v3 rewrites it")
        sources = _read_json(os.path.join(handoff_dir, "sources.json"))
        timeline = _read_json(os.path.join(handoff_dir, "timeline.json"))
        # I-5-7: 汇总研究阶段遥测。token 行可能整轮缺失（某些研究模型不报 usage）→ 全 0/None。
        research_telemetry = {
            "model": (model or Config.DEERFLOW_MODEL),
            "depth": effective_depth,
            "tokens_in": _tok_in,
            "tokens_out": _tok_out,
            "tokens_total": _tok_total or (_tok_in + _tok_out),
            "tokens_cached": _tok_cached,
            "tool_calls": tool_events,
            "results": _result_events,
            "wall_s": round(time.time() - _t_start, 1),
        }
        if bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True)):
            # INFRA-8: the resolved model id and served ids the v3 child wrote into meta.json.
            _child_meta = _read_json(os.path.join(handoff_dir, "meta.json"))
            _resolution = (_child_meta.get("model_resolution")
                           if isinstance(_child_meta, dict) else None)
            if isinstance(_resolution, dict):
                research_telemetry["model_resolution"] = _resolution
        on_progress(
            100,
            f"研究完成（{'证据包' if evidence_only else '报告'} {len(report)} 字）",
        )
        return {
            "report": report,
            "report_path": report_path,
            "evidence_pack": report if evidence_only else None,
            "actor_dossier": actor_dossier,  # 双轨 Track B：角色本体档案（缺失为 ""）
            "actors": actors,
            "sources": sources,
            "timeline": timeline,
            "exit_code": returncode,
            "research_telemetry": research_telemetry,  # I-5-7
        }


# I-5-7: 解析 DeerFlow bridge 已发出的「[usage] tokens in=.. out=.. total=..」行
# （deerflow_research.py:ProgressLog.write('usage', ...)）。容错：out/total 可能为 None
# 时 bridge 会打印字面 "None"，故各组匹配数字或 None；no-match → 该行不计入。
_USAGE_RE = re.compile(
    r"tokens in=(?P<in>\d+|None)\s+out=(?P<out>\d+|None)\s+total=(?P<total>\d+|None)"
)


def _parse_usage_line(line: str) -> Optional[tuple[int, int, int]]:
    """从一行 [usage] 日志解析 (in, out, total) token；解析不出返回 None。"""
    m = _USAGE_RE.search(line)
    if not m:
        return None

    def _num(s: str) -> int:
        return int(s) if s and s.isdigit() else 0

    return _num(m.group("in")), _num(m.group("out")), _num(m.group("total"))


# Engine v3 appends provider prompt-cache reads to every [usage] line
# (``… total=N phase=gather:K1 cached=C cache_write=W reasoning=R``).  Only a
# whitespace-delimited ``cached=<digits>`` field AFTER the ``tokens in=… total=…``
# triple counts, so ``cache_write=`` / ``prompt_cached=``-style fields never match.
_USAGE_CACHED_RE = re.compile(r"(?:^|\s)cached=(?P<cached>\d+)(?!\S)")


def _parse_usage_cached_tokens(line: str) -> int:
    """Return the prompt-cache-read token count of one [usage] line (0 if absent).

    A sibling of :func:`_parse_usage_line` rather than a fourth tuple element so
    that function's ``(in, out, total)`` contract stays unchanged for existing
    callers; lines without the optional field (legacy engine) contribute 0.
    """
    m = _USAGE_RE.search(line)
    if not m:
        return 0
    cached = _USAGE_CACHED_RE.search(line, m.end())
    return int(cached.group("cached")) if cached else 0


def _tail(s: str, limit: int = 160) -> str:
    s = s.strip()
    # 去掉时间戳+级别前缀，保留信息部分
    if "] " in s:
        s = s.split("] ", 1)[1] if s.count("] ") >= 1 else s
    return s if len(s) <= limit else s[:limit] + "…"


# RES-1/RES-8: LLM 降级/错误串标记（live 报告守卫 + 卷宗降级门共用；单一真源）。
_LLM_ERROR_MARKERS = (
    "The configured LLM provider",  # DeerFlow LLMErrorHandlingMiddleware 降级
    "LLM request failed",            # 原始 provider 报错被当成正文
    "unprocessable_entity",          # 例如 MiniMax 422 内容审核
    "new_sensitive",                 # MiniMax 域内容过滤命中(code 1026)
    "Error code: 4", "Error code: 5",  # 4xx/5xx 错误串
)


_EVIDENCE_BLOCK_RE = re.compile(
    r"^<!--\s*evidence-block:\d+\s*-->\s*$", re.MULTILINE)


def _control_failure_block(text: str) -> bool:
    block = str(text or "").strip()
    if not block:
        return True
    if block.splitlines()[0].strip().startswith("SUBAGENT_OUTCOME: BLOCKED"):
        return True
    try:
        payload = json.loads(block)
    except (TypeError, ValueError):
        payload = None
    if isinstance(payload, dict) and payload.get("error") in {
        "research_budget_exhausted",
        "llm_provider_unavailable",
    }:
        return True
    if any(marker in block for marker in _LLM_ERROR_MARKERS):
        return True
    lowered = block.lower()
    return (
        "research_budget_exhausted" in lowered
        and any(marker in lowered for marker in (
            "status: blocked",
            "status:** blocked",
            "no admissible evidence",
            "no web-document evidence",
            "cannot perform web",
            "cannot fetch",
            "unable to complete",
            "research halted",
        ))
    )


def _evidence_pack_is_control_failure_only(text: str) -> bool:
    """Mirror the bridge gate at timeout/artifact admission boundaries."""
    raw = str(text or "")
    matches = list(_EVIDENCE_BLOCK_RE.finditer(raw))
    if matches:
        blocks = []
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(raw)
            block = raw[match.end():end]
            if index + 1 < len(matches):
                block = re.sub(r"\n\s*\n---\s*\Z", "", block.rstrip())
            if block.strip():
                blocks.append(block.strip())
    elif raw.strip().startswith("# Internal Evidence Lane Pack"):
        blocks = []
    else:
        blocks = [raw.strip()] if raw.strip() else []
    return not blocks or all(_control_failure_block(block) for block in blocks)


def _is_degraded_dossier(text: str) -> bool:
    """RES-8 编排器侧镜像：actor_dossier.md 含错误串或短于 RESEARCH_MIN_REPORT_CHARS
    （默认 400，0 关闭长度门）即视为降级产物——调用方应按缺失处理，绝不喂给本体/建图。"""
    t = (text or "").strip()
    if not t:
        return False  # 空 = 缺失，由调用方原有语义处理
    _min = int(getattr(Config, "RESEARCH_MIN_REPORT_CHARS", 400) or 0)
    if _min and len(t) < _min:
        return True
    return any(m in t for m in _LLM_ERROR_MARKERS)


def _load_fresh_evidence_lane_actor_dossier(
    handoff_dir: str,
    *,
    prompt: str,
) -> str:
    """Admit only the actor dossier produced by this evidence-lane attempt.

    Evidence lanes routinely reuse ``track_1`` directories for bounded resume.
    File existence or mtime therefore cannot distinguish current output from a
    stale dossier.  The bridge rewrites ``meta.json`` at process start and only
    marks ``actor_dossier_generated`` after the current Track-B dossier,
    deterministic coverage audit, and sidecar checks have completed.  Bind all
    of those bytes here before returning the shared dossier to the orchestrator.
    """
    meta = _read_json(os.path.join(handoff_dir, "meta.json"))
    if not isinstance(meta, dict):
        raise RuntimeError(
            "baseline evidence lane did not emit current actor-dossier metadata"
        )
    if (
        meta.get("status") != "completed"
        or meta.get("workflow_mode") != "evidence_only"
        or meta.get("question") != prompt
        or meta.get("actor_dossier_generated") is not True
        or meta.get("actor_dossier_required") is not True
    ):
        raise RuntimeError(
            "baseline evidence lane actor dossier lacks current-attempt provenance"
        )

    dossier_path = os.path.join(handoff_dir, "actor_dossier.md")
    dossier = _read_text(dossier_path)
    if (
        not dossier.strip()
        or _is_degraded_dossier(dossier)
        or _evidence_pack_is_control_failure_only(dossier)
    ):
        raise RuntimeError(
            "baseline evidence lane actor dossier is missing or degraded"
        )
    dossier_sha = hashlib.sha256(dossier.encode("utf-8")).hexdigest()
    if meta.get("actor_dossier_sha256") != dossier_sha:
        raise RuntimeError(
            "baseline evidence lane actor dossier checksum mismatch"
        )

    coverage_path = os.path.join(
        handoff_dir, "actor_dossier_coverage.json")
    coverage_bytes = b""
    try:
        with open(coverage_path, "rb") as coverage_handle:
            coverage_bytes = coverage_handle.read()
        coverage = json.loads(coverage_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError(
            "baseline evidence lane actor coverage sidecar is missing or invalid"
        ) from exc
    if (
        not isinstance(coverage, dict)
        or coverage.get("accountable") is not True
        or coverage.get("schema_version") != "actor-intelligence/v1"
        or not int(coverage.get("tier_1_2_actor_count") or 0)
        or coverage != meta.get("actor_dossier_coverage")
        or hashlib.sha256(coverage_bytes).hexdigest()
        != meta.get("actor_dossier_coverage_sha256")
    ):
        raise RuntimeError(
            "baseline evidence lane actor coverage is not current and accountable"
        )

    # A current judge is optional only when transport/parsing failed.  The
    # bridge removes old sidecars before Track B, and binds any current one in
    # meta.  Thus an absent hash is a safe degraded judge, while a bound
    # explicit FAIL is always unusable.
    judge_sha = str(meta.get("actor_dossier_judge_sha256") or "").strip()
    if judge_sha:
        judge_path = os.path.join(handoff_dir, "actor_dossier_judge.json")
        try:
            with open(judge_path, "rb") as judge_handle:
                judge_bytes = judge_handle.read()
            judge = json.loads(judge_bytes.decode("utf-8"))
        except (OSError, UnicodeDecodeError, ValueError, TypeError) as exc:
            raise RuntimeError(
                "baseline evidence lane actor judge sidecar is invalid"
            ) from exc
        if hashlib.sha256(judge_bytes).hexdigest() != judge_sha:
            raise RuntimeError(
                "baseline evidence lane actor judge checksum mismatch"
            )
        if (
            isinstance(judge, dict)
            and str(judge.get("verdict") or "").strip().upper() == "FAIL"
        ):
            raise RuntimeError(
                "baseline evidence lane actor dossier has an explicit final judge FAIL"
            )
    return dossier


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


# ITEM-3：bridge 每完成一个研究 pass 就在 handoff_dir 落一个 research_checkpoint.json。崩溃/
# 超时重试时若它存在（且非空），就给重试的研究子进程加 --resume 复用 LangGraph 线程、跳过已完成
# pass，而非从 pass 0 全量重启（一整轮 deep 研究的数十个已抓来源不再被白白丢弃）。空文件/读失败
# 一律当作「无 checkpoint」→ 全量重启（degrade-safe）。
def _has_research_checkpoint(handoff_dir: str) -> bool:
    """handoff_dir 是否有一个可用于续跑的 research_checkpoint.json（存在且非空）。"""
    try:
        p = os.path.join(handoff_dir, "research_checkpoint.json")
        return os.path.exists(p) and os.path.getsize(p) > 0
    except OSError:
        return False


def _research_checkpoint_identity(checkpoint: dict[str, Any]) -> str:
    """Mirror the bridge's immutable checkpoint identity projection."""
    identity = {
        key: checkpoint.get(key)
        for key in (
            "version", "thread_id", "question_hash", "depth", "run_id",
            "attempt_id", "lane_id", "completed_passes",
            "fetched_source_count", "gaps",
        )
    }
    return "checkpoint_" + hashlib.sha256(json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:24]


def _validated_research_checkpoint_lineage(
    handoff_dir: str,
    *,
    prompt: str,
    depth: str,
    run_id: str,
    lane_id: str,
    expected_attempt_ids: Optional[set[str]] = None,
) -> dict[str, str]:
    """Return exact prior lineage only for an untampered v2 checkpoint.

    An explicit pipeline resume receives a fresh cost ledger, but the bridge's
    checkpoint identity deliberately binds the prior research attempt.  Reusing
    the new task ID as ``attempt_id`` makes the bridge reject a healthy same-run
    checkpoint and replay every completed pass.  Parent authority therefore
    validates the immutable checkpoint first and forwards its prior attempt
    identity separately from the new budget database.  Any cross-run, question,
    depth, lane, thread, or identity drift returns an empty value and forces a
    clean research start.
    """
    checkpoint = _read_json(os.path.join(
        handoff_dir, "research_checkpoint.json"
    ))
    if not isinstance(checkpoint, dict) or checkpoint.get("version") != 2:
        return {}
    thread_id = str(checkpoint.get("thread_id") or "").strip()
    attempt_id = str(checkpoint.get("attempt_id") or "").strip()
    if not thread_id or not attempt_id:
        return {}
    if checkpoint.get("question_hash") != _actor_question_hash(prompt):
        return {}
    if str(checkpoint.get("depth") or "") != str(depth or ""):
        return {}
    if str(checkpoint.get("run_id") or "") != str(run_id or ""):
        return {}
    if str(checkpoint.get("lane_id") or "") != str(lane_id or ""):
        return {}
    allowed_attempts = {
        str(value or "").strip()
        for value in (expected_attempt_ids or set())
        if str(value or "").strip()
    }
    if expected_attempt_ids is not None and attempt_id not in allowed_attempts:
        return {}
    completed_passes = checkpoint.get("completed_passes")
    if (
        not isinstance(completed_passes, list)
        or any(
            not isinstance(value, str) or not value.strip()
            for value in completed_passes
        )
        or not isinstance(checkpoint.get("gaps"), list)
        or any(not isinstance(value, str) for value in checkpoint["gaps"])
        or isinstance(checkpoint.get("fetched_source_count"), bool)
        or not isinstance(checkpoint.get("fetched_source_count"), int)
        or checkpoint["fetched_source_count"] < 0
    ):
        return {}
    expected_checkpoint_id = _research_checkpoint_identity(checkpoint)
    if checkpoint.get("checkpoint_id") != expected_checkpoint_id:
        return {}
    return {
        "attempt_id": attempt_id,
        "checkpoint_id": expected_checkpoint_id,
        "thread_id": thread_id,
    }


def _validated_research_checkpoint_attempt_id(
    handoff_dir: str,
    *,
    prompt: str,
    depth: str,
    run_id: str,
    lane_id: str,
    expected_attempt_ids: Optional[set[str]] = None,
) -> str:
    """Compatibility projection for callers that only need the attempt ID."""
    return _validated_research_checkpoint_lineage(
        handoff_dir,
        prompt=prompt,
        depth=depth,
        run_id=run_id,
        lane_id=lane_id,
        expected_attempt_ids=expected_attempt_ids,
    ).get("attempt_id", "")


def _track_artifacts_survived(handoff_dir: str) -> bool:
    """W9-4（纯，可单测）：研究子进程「收尾超时」后的产物判定——该轨是否实际已成功。

    判据：research_report.md 已落盘且非降级短串（≥400 字符，与 _load_research_handoff 同
    语义），且（actors.json 已产出 或 research_checkpoint.json 带非空 completed_passes）
    ——两者之一即证明研究协议真实推进过，报告不是半写残段。全部满足 → 该轨按存活处理。
    """
    report = _read_text(os.path.join(handoff_dir, "research_report.md")).strip()
    if len(report) < 400:
        return False
    if os.path.exists(os.path.join(handoff_dir, "actors.json")):
        return True
    ckpt = _read_json(os.path.join(handoff_dir, "research_checkpoint.json"))
    return bool(isinstance(ckpt, dict) and ckpt.get("completed_passes"))


def _preserve_research_attempt_progress(
    source_dir: str,
    handoff_dir: str,
    *,
    attempt: int,
    outcome: str,
    detail: str = "",
) -> Optional[str]:
    """Retain a failed/cancelled global-synthesis event log before cleanup.

    Synthesis runs in disposable staging directories so partial reports cannot
    leak into the research contract.  The human-readable event stream is safe
    and valuable forensic evidence, however, so copy that one file into a
    durable sidecar directory.  A unique name prevents later resumes from
    overwriting an earlier attempt.
    """
    source = os.path.join(source_dir, "research_progress.log")
    if not os.path.isfile(source) or os.path.islink(source):
        return None
    normalized_outcome = re.sub(r"[^A-Za-z0-9_-]+", "_", outcome or "unknown")
    destination_dir = os.path.join(handoff_dir, "research_attempts")
    destination = os.path.join(
        destination_dir,
        f"global_synthesis_{max(1, int(attempt))}_{normalized_outcome}_"
        f"{uuid.uuid4().hex[:12]}.log",
    )
    try:
        os.makedirs(destination_dir, exist_ok=True)
        shutil.copy2(source, destination)
        summary = " ".join(str(detail or "").split())[:1000]
        kind = "error" if normalized_outcome == "failed" else "warn"
        suffix = f": {summary}" if summary else ""
        with open(destination, "a", encoding="utf-8") as handle:
            handle.write(
                f"{_utcnow()} [{kind}] global synthesis attempt {attempt} "
                f"{normalized_outcome}{suffix}\n"
            )
        # Keep the quality-failed candidate and its exact-byte judge beside the
        # log.  These are forensic/recovery sidecars only and never enter the
        # published research contract.  Previously cleanup discarded the most
        # useful evidence for why a synthesis attempt failed.
        stem = destination[:-4] if destination.endswith(".log") else destination
        for name in (
            "research_report.md",
            "research_report_judge.json",
            "research_report_refinement_candidate.md",
            "research_report_refinement_candidate_judge.json",
            "research_report_failure_candidate.md",
            "research_report_failure_candidate_judge.json",
            "meta.json",
        ):
            artifact = os.path.join(source_dir, name)
            if os.path.isfile(artifact) and not os.path.islink(artifact):
                shutil.copy2(artifact, f"{stem}.{name}")
        return destination
    except OSError as exc:
        logger.warning(
            "无法保留全局综合尝试 %s 的研究进度日志: %s", attempt, exc,
        )
        return None


_RESEARCH_CONTRACT_FILENAME = "research_contract_manifest.json"
_RESEARCH_CONTRACT_FILES = (
    "research_report.md", "actor_dossier.md", "actor_dossier_coverage.json",
    "actor_dossier_judge.json", "actors.json", "sources.json",
    ACTOR_INTELLIGENCE_LINEAGE_FILENAME,
    "timeline.json", "quantitative.json", "contested.json",
    "prediction_markets.json", "market_price_history.json",
    "research_report_judge.json", "research_progress.log", "meta.json",
    "charts.json",
)

_RESEARCH_JUDGE_DIMS = (
    "thesis_specificity", "base_rate_usage", "mechanism_chains",
    "quantitative_density", "contrarian_coverage", "length_vs_target",
    "citation_coverage",
)
_RESEARCH_JUDGE_CRITICAL = (
    "thesis_specificity", "mechanism_chains", "contrarian_coverage",
    "citation_coverage",
)
_RESEARCH_JUDGE_FATAL_GAP_RE = re.compile(
    r"\btruncat(?:e|ed|ion|ing)\b|"
    r"\bmid[-\s]sentence\b|"
    r"\bcut(?:s)?\s+off\b|"
    r"\b(?:not|never)\s+(?:delivered|provided|included|completed)\b|"
    r"\bno\s+(?:renderable\s+)?(?:actual|source)[-\s]data\s+tables?\b|"
    r"\b(?:chart|visuali[sz]ation)\s+(?:ideas?|specifications?)\s+"
    r"(?:alone|only|without)\b|"
    r"\bincomplete\s+(?:\w+\s+){0,3}"
    r"(?:citation|marker|table|section|list|forecast|scenario|milestone|deliverable)\b|"
    r"截断|未写完|未完成|只有.{0,24}(?:规格|图表想法)|没有.{0,24}(?:真实数据表|来源数据表)",
    re.IGNORECASE,
)


def _research_judge_scores(scorecard: Any) -> Optional[tuple[float, ...]]:
    """Validate the persisted seven-dimension judge schema without importing DeerFlow."""
    if not isinstance(scorecard, dict):
        return None
    if str(scorecard.get("verdict", "")).strip().upper() not in {"PASS", "FAIL"}:
        return None
    scores = scorecard.get("scores")
    if not isinstance(scores, dict) or set(scores) != set(_RESEARCH_JUDGE_DIMS):
        return None
    values: list[float] = []
    for dimension in _RESEARCH_JUDGE_DIMS:
        raw = scores[dimension]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            return None
        value = float(raw)
        if not math.isfinite(value) or not 0.0 <= value <= 5.0:
            return None
        values.append(value)
    return tuple(values)


def _research_judge_passes(scorecard: Any) -> bool:
    values = _research_judge_scores(scorecard)
    if values is None or str(scorecard.get("verdict", "")).strip().upper() != "PASS":
        return False
    gaps = scorecard.get("gaps")
    if isinstance(gaps, list) and any(
            _RESEARCH_JUDGE_FATAL_GAP_RE.search(str(gap or ""))
            for gap in gaps):
        return False
    scores = scorecard["scores"]
    strict = str(os.environ.get("RESEARCH_REPORT_JUDGE_STRICT", "")).strip().lower()
    if strict in {"1", "true", "yes", "on"} and min(values) < 4:
        return False
    if min(values) < 3:
        return False
    if any(float(scores[name]) < 4 for name in _RESEARCH_JUDGE_CRITICAL):
        return False
    return sum(values) / len(values) >= 4.0


def _research_contract_quality_errors(
    handoff_dir: str, *, require_judge: bool = False,
) -> list[str]:
    """Return publication-quality defects independently of checksum integrity."""
    judge_path = os.path.join(handoff_dir, "research_report_judge.json")
    if not os.path.isfile(judge_path):
        return ["research_report_judge_missing"] if require_judge else []
    scorecard = _read_json(judge_path)
    if _research_judge_scores(scorecard) is None:
        return ["research_report_judge_malformed"]
    if not _research_judge_passes(scorecard):
        return ["research_report_judge_failed"]
    return []


def _research_judge_contract_errors(
    root: str,
    entries: dict[str, Any],
    report: str,
) -> list[str]:
    """Bind required deep-research judge evidence to the exact prose prefix.

    Deterministic market/chart annexes may follow the judged LLM prose.  The
    persisted ``chars`` boundary therefore identifies the exact report prefix
    the judge saw, while the outer research manifest seals the complete report.
    """
    meta = _read_json(os.path.join(root, "meta.json"))
    if not isinstance(meta, dict):
        meta = {}
    judge_required = (
        str(meta.get("depth", "")).strip().lower() == "deep"
        or "research_report_judge.json" in entries
        or isinstance(meta.get("research_report_judge"), dict)
        or isinstance(meta.get("global_synthesis_judge"), dict)
    )
    if not judge_required:
        return []
    errors: list[str] = []
    if "research_report_judge.json" not in entries or "meta.json" not in entries:
        missing = [
            name for name in ("research_report_judge.json", "meta.json")
            if name not in entries
        ]
        return ["judge_required_artifact_missing:" + ",".join(missing)]
    scorecard = _read_json(os.path.join(root, "research_report_judge.json"))
    if _research_judge_scores(scorecard) is None:
        return ["judge_scorecard_schema_invalid"]
    judged = scorecard.get("_judged_prose")
    judge_input = scorecard.get("_judge_input")
    if not isinstance(judged, dict) or not isinstance(judge_input, dict):
        return ["judge_input_identity_missing"]
    try:
        chars = int(judged.get("chars"))
    except (TypeError, ValueError):
        return ["judge_prose_chars_invalid"]
    if chars <= 0 or chars > len(report) or judged.get("scope") != "llm-prose":
        return [
            "judge_prose_boundary_invalid:"
            f"chars={chars},report_chars={len(report)},scope={judged.get('scope')!r}"
        ]
    prose = report[:chars]
    prose_sha = hashlib.sha256(prose.encode("utf-8")).hexdigest()
    if judged.get("sha256") != prose_sha:
        errors.append(
            "judge_prose_hash_mismatch:"
            f"expected={judged.get('sha256')},actual={prose_sha}"
        )
    if judge_input != {
        "report_chars": chars,
        "input_chars": chars,
        "input_sha256": prose_sha,
        "truncated": False,
    }:
        errors.append("judge_input_identity_mismatch")

    summary = meta.get("research_report_judge")
    if not isinstance(summary, dict):
        errors.append("judge_meta_summary_missing")
        return errors
    expected_pass = _research_judge_passes(scorecard)
    if (
        str(summary.get("verdict", "")).strip().upper()
        != str(scorecard.get("verdict", "")).strip().upper()
        or summary.get("scores") != scorecard.get("scores")
        or summary.get("passed") is not expected_pass
        or summary.get("judged_prose_sha256") != prose_sha
        or summary.get("judged_prose_chars") != chars
        or summary.get("judge_scope") != "llm-prose"
    ):
        errors.append("judge_meta_summary_mismatch")
    global_summary = meta.get("global_synthesis_judge")
    if global_summary is not None and global_summary != summary:
        errors.append("global_judge_summary_mismatch")
    return errors


def _validate_research_judge_contract(
    root: str,
    entries: dict[str, Any],
    report: str,
) -> bool:
    """Compatibility bool wrapper around actionable judge diagnostics."""
    return not _research_judge_contract_errors(root, entries, report)


def _research_contract_path(handoff_dir: str) -> str:
    return os.path.join(handoff_dir, _RESEARCH_CONTRACT_FILENAME)


def _research_contract_entries(root: str) -> dict[str, dict[str, Any]]:
    """Fingerprint the exact staged/root research contract, including charts."""
    entries: dict[str, dict[str, Any]] = {}
    candidates: list[tuple[str, str]] = []
    for name in _RESEARCH_CONTRACT_FILES:
        path = os.path.join(root, name)
        if os.path.isfile(path):
            candidates.append((name, path))
    charts = os.path.join(root, "charts")
    if os.path.isdir(charts):
        for dirpath, dirnames, filenames in os.walk(charts):
            dirnames[:] = sorted(d for d in dirnames if not os.path.islink(
                os.path.join(dirpath, d)))
            for filename in sorted(filenames):
                path = os.path.join(dirpath, filename)
                if os.path.isfile(path) and not os.path.islink(path):
                    candidates.append((os.path.relpath(path, root), path))
    for relative, path in candidates:
        digest = _sha256_file(path)
        if digest is None:
            raise RuntimeError(f"cannot fingerprint research artifact: {relative}")
        entries[relative] = {
            "bytes": os.path.getsize(path),
            "sha256": digest,
        }
    return entries


def _research_contract_validation_errors(handoff_dir: str) -> list[str]:
    """Return actionable manifest, artifact, and judge-binding violations."""
    manifest = _read_json(_research_contract_path(handoff_dir))
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        return ["manifest_missing_or_version_invalid"]
    entries = manifest.get("files")
    if not isinstance(entries, dict) or "research_report.md" not in entries:
        return ["manifest_files_invalid_or_report_missing"]
    root = os.path.realpath(handoff_dir)
    errors: list[str] = []
    try:
        for relative, expected in entries.items():
            if (not isinstance(relative, str) or not isinstance(expected, dict)
                    or os.path.isabs(relative)):
                errors.append(f"manifest_entry_invalid:{relative!r}")
                continue
            path = os.path.realpath(os.path.join(root, relative))
            if os.path.commonpath([root, path]) != root:
                errors.append(f"artifact_path_escape:{relative}")
                continue
            if not os.path.isfile(path):
                errors.append(f"artifact_missing:{relative}")
                continue
            if os.path.getsize(path) != expected.get("bytes"):
                errors.append(
                    f"artifact_size_mismatch:{relative}:"
                    f"expected={expected.get('bytes')},actual={os.path.getsize(path)}"
                )
                continue
            actual_sha = _sha256_file(path)
            if actual_sha != expected.get("sha256"):
                errors.append(
                    f"artifact_sha256_mismatch:{relative}:"
                    f"expected={expected.get('sha256')},actual={actual_sha}"
                )
        report = _read_text(os.path.join(root, "research_report.md"))
        if len(report.strip()) < 400:
            errors.append("report_incomplete")
        else:
            errors.extend(_research_judge_contract_errors(root, entries, report))
        # Optional contract-owned artifacts absent from the generation manifest
        # would prove that a stale file survived promotion.
        for name in _RESEARCH_CONTRACT_FILES:
            if os.path.exists(os.path.join(root, name)) and name not in entries:
                errors.append(f"unmanifested_optional_artifact:{name}")
        if os.path.isdir(os.path.join(root, "charts")):
            actual_chart_files = {
                rel for rel in _research_contract_entries(root)
                if rel.startswith("charts" + os.sep)
            }
            expected_chart_files = {
                rel for rel in entries if rel.startswith("charts" + os.sep)
            }
            if actual_chart_files != expected_chart_files:
                missing = sorted(expected_chart_files - actual_chart_files)
                extra = sorted(actual_chart_files - expected_chart_files)
                errors.append(
                    "chart_artifact_set_mismatch:"
                    f"missing={missing},extra={extra}"
                )
        return errors
    except (OSError, ValueError, TypeError) as exc:
        return [f"validation_exception:{type(exc).__name__}:{exc}"]


def _validate_research_contract(handoff_dir: str) -> bool:
    """Validate the manifest-last root contract before any research reuse."""
    return not _research_contract_validation_errors(handoff_dir)


def research_dossier_is_sealed(handoff_dir: str) -> bool:
    """Whether Stage-1 output is cryptographically bound and so not hand-editable.

    Multi-lane research is sealed by the manifest-last research contract, and
    depending on the run by the report-judge prose binding.  Independently, an
    ``actors.json`` carrying an ``actor_intelligence_contract`` (or its lineage
    file) binds the report/actors hashes that actor reception, actor-context and
    role prompts re-verify downstream.  A direct human edit breaks those seals:
    Continue/resume would either re-run synthesis over the edit or fail actor
    reception.  The dossier-edit API therefore refuses sealed research instead
    of accepting an edit that cannot survive.
    """
    if os.path.exists(_research_contract_path(handoff_dir)):
        return True
    if os.path.exists(os.path.join(handoff_dir, ACTOR_INTELLIGENCE_LINEAGE_FILENAME)):
        return True
    actors = _read_json(os.path.join(handoff_dir, "actors.json"))
    return isinstance(actors, dict) and isinstance(
        actors.get("actor_intelligence_contract"), dict)


def refresh_research_artifact_manifest(
    pipeline_id: str, handoff_dir: str, filenames: list[str],
) -> list[str]:
    """Re-record human-edited *unsealed* research artifacts in handoff/manifest.json.

    Legacy (pre-contract) research is reused on resume via ``_validate_reuse``,
    which compares each registered artifact's sha256/bytes with this manifest.
    Refreshing the edited entries makes that check accept the edit rather than
    rebuild research over it.  Returns the artifact names that were refreshed.
    """
    manifest = PipelineManager.load_artifact_manifest(pipeline_id)
    if not manifest:
        return []  # 无清单：复用走存在性检查，编辑天然保留
    probe = PipelineState(pipeline_id=pipeline_id, prompt="", handoff_dir=handoff_dir)
    wanted = {os.path.realpath(os.path.join(handoff_dir, name)) for name in filenames}
    refreshed: list[str] = []
    for name, path in PipelineOrchestrator._stage_artifact_specs(probe, STAGE_RESEARCH):
        if os.path.realpath(path) not in wanted:
            continue
        entry = _manifest_entry_for(name, path, STAGE_RESEARCH)
        if entry is not None:
            # Keep when research produced the artifact; stamp the edit separately.
            previous = manifest.get(name)
            if isinstance(previous, dict) and previous.get("produced_at"):
                entry["produced_at"] = previous["produced_at"]
            entry["human_edited_at"] = _utcnow()
            manifest[name] = entry
            refreshed.append(name)
    if refreshed:
        PipelineManager.write_artifact_manifest(pipeline_id, manifest)
    return refreshed


def _research_report_is_judge_bound(handoff_dir: str) -> bool:
    """Return whether the current manifest seals an exact report-judge binding."""
    manifest = _read_json(_research_contract_path(handoff_dir))
    if not isinstance(manifest, dict):
        # Single-lane runs (every v3 run) publish no contract manifest; this
        # used to raise AttributeError, which silently skipped research lint.
        return False
    entries = manifest.get("files")
    return bool(
        manifest.get("version") == 1
        and isinstance(entries, dict)
        and "research_report_judge.json" in entries
    )


def _promote_research_contract(
    source_dir: str,
    handoff_dir: str,
    *,
    meta_patch: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Promote one validated research generation with rollback + manifest-last.

    Files are copied completely into a private stage, then root artifacts are
    atomically replaced one by one while their predecessors live in a rollback
    directory.  Any exception restores the previous generation.  The checksum
    manifest is written last; resume never trusts an unmanifested mixed root.
    """
    source_root = os.path.realpath(source_dir)
    root = os.path.realpath(handoff_dir)
    os.makedirs(root, exist_ok=True)
    generation = uuid.uuid4().hex
    stage = tempfile.mkdtemp(prefix=f".research-stage-{generation}-", dir=root)
    rollback = tempfile.mkdtemp(prefix=f".research-rollback-{generation}-", dir=root)
    contract_path = _research_contract_path(root)
    moved_old: list[str] = []
    installed_new: list[str] = []
    charts_installed = False
    old_charts_moved = False
    old_contract_moved = False
    try:
        for name in _RESEARCH_CONTRACT_FILES:
            source = os.path.join(source_root, name)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(stage, name))
        source_charts = os.path.join(source_root, "charts")
        if os.path.isdir(source_charts):
            shutil.copytree(source_charts, os.path.join(stage, "charts"))

        if meta_patch:
            staged_meta_path = os.path.join(stage, "meta.json")
            staged_meta = _read_json(staged_meta_path)
            if not isinstance(staged_meta, dict):
                staged_meta = {}
            staged_meta.update(meta_patch)
            from ..utils.atomic import write_json_atomic
            write_json_atomic(staged_meta_path, staged_meta)

        report = _read_text(os.path.join(stage, "research_report.md")).strip()
        if len(report) < 400:
            raise RuntimeError("staged research contract has no complete report")
        entries = _research_contract_entries(stage)
        manifest = {
            "version": 1,
            "generation": generation,
            "created_at": _utcnow(),
            "files": entries,
        }

        if os.path.exists(contract_path):
            os.replace(contract_path, os.path.join(rollback, _RESEARCH_CONTRACT_FILENAME))
            old_contract_moved = True
        for name in _RESEARCH_CONTRACT_FILES:
            destination = os.path.join(root, name)
            if os.path.exists(destination):
                os.replace(destination, os.path.join(rollback, name))
                moved_old.append(name)
        root_charts = os.path.join(root, "charts")
        if os.path.lexists(root_charts):
            os.replace(root_charts, os.path.join(rollback, "charts"))
            old_charts_moved = True

        for name in _RESEARCH_CONTRACT_FILES:
            staged = os.path.join(stage, name)
            if os.path.isfile(staged):
                os.replace(staged, os.path.join(root, name))
                installed_new.append(name)
        staged_charts = os.path.join(stage, "charts")
        if os.path.isdir(staged_charts):
            os.replace(staged_charts, root_charts)
            charts_installed = True

        from ..utils.atomic import write_json_atomic
        write_json_atomic(contract_path, manifest)
        validation_errors = _research_contract_validation_errors(root)
        if validation_errors:
            raise RuntimeError(
                "promoted research contract validation failed: "
                + "; ".join(validation_errors[:8])
            )
        return manifest
    except Exception:
        try:
            if os.path.exists(contract_path):
                os.unlink(contract_path)
            for name in installed_new:
                path = os.path.join(root, name)
                if os.path.exists(path):
                    os.unlink(path)
            if charts_installed and os.path.lexists(os.path.join(root, "charts")):
                shutil.rmtree(os.path.join(root, "charts"), ignore_errors=True)
            for name in moved_old:
                prior = os.path.join(rollback, name)
                if os.path.exists(prior):
                    os.replace(prior, os.path.join(root, name))
            if old_charts_moved and os.path.lexists(os.path.join(rollback, "charts")):
                os.replace(os.path.join(rollback, "charts"), os.path.join(root, "charts"))
            if old_contract_moved:
                prior_contract = os.path.join(rollback, _RESEARCH_CONTRACT_FILENAME)
                if os.path.exists(prior_contract):
                    os.replace(prior_contract, contract_path)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
            shutil.rmtree(rollback, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(rollback, ignore_errors=True)


def _finalize_research_contract(
    handoff_dir: str,
    research: dict[str, Any],
) -> Optional[dict[str, Any]]:
    """Atomically seal sanctioned post-processing into a research contract.

    Global synthesis first promotes a clean producer generation so downstream
    code never observes a half-written handoff.  Research lint and cast
    reconciliation run afterwards, however, and historically wrote directly
    over ``research_report.md`` / ``actors.json``.  That made the already
    published checksum manifest invalid and forced every resume to reject the
    otherwise healthy generation.

    Keep the producer generation untouched and valid while building a private
    finalized copy.  The copy receives the exact in-memory report, reconciled
    actors, and effective source ledger, then goes through the same
    rollback-capable, manifest-last promotion as the producer generation.  A
    failure therefore leaves the prior valid contract reusable; it can never
    bless a mixed root.  Legacy research paths without a contract keep their
    existing behavior and return ``None``.
    """
    root = os.path.realpath(handoff_dir)
    contract_path = _research_contract_path(root)
    if not os.path.exists(contract_path):
        return None
    existing_manifest = _read_json(contract_path)
    if not _validate_research_contract(root):
        raise RuntimeError(
            "research contract changed before sanctioned finalization"
        )

    report = research.get("report")
    if not isinstance(report, str) or len(report.strip()) < 400:
        raise RuntimeError(
            "finalized research contract has no complete report"
        )
    root_report = _read_text(os.path.join(root, "research_report.md"))
    if _research_report_is_judge_bound(root) and report != root_report:
        raise RuntimeError(
            "post-judge research report mutation rejected: the sealed judge "
            "binds the exact LLM-prose bytes; run synthesis and judging again "
            "instead of finalizing modified prose"
        )
    actors = research.get("actors")
    if actors is not None and not isinstance(actors, dict):
        raise RuntimeError(
            "finalized research actors must be a JSON object"
        )
    # Persist the exact source union returned to downstream consumers,
    # including an empty list.  Previously ``or merged_sources`` could make
    # the in-memory ledger richer than the generation actually sealed.
    sources = research.get("sources")
    if sources is not None and not isinstance(sources, list):
        raise RuntimeError(
            "finalized research sources must be a JSON list"
        )
    meta = research.get("meta")
    if meta is not None and not isinstance(meta, dict):
        raise RuntimeError(
            "finalized research metadata must be a JSON object"
        )

    # A clean resume should validate, not rewrite or recopy a potentially large
    # charts tree.  Only build a private generation when a sanctioned payload
    # actually differs from the sealed root.
    if (
        _read_text(os.path.join(root, "research_report.md")) == report
        and (actors is None or _read_json(os.path.join(root, "actors.json")) == actors)
        and (sources is None or _read_json(os.path.join(root, "sources.json")) == sources)
        and (meta is None or _read_json(os.path.join(root, "meta.json")) == meta)
    ):
        return existing_manifest if isinstance(existing_manifest, dict) else None

    final_source = tempfile.mkdtemp(prefix=".research-final-", dir=root)
    try:
        for name in _RESEARCH_CONTRACT_FILES:
            source = os.path.join(root, name)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(final_source, name))
        source_charts = os.path.join(root, "charts")
        if os.path.isdir(source_charts):
            shutil.copytree(source_charts, os.path.join(final_source, "charts"))

        from ..utils.atomic import write_json_atomic, write_text_atomic
        staged_report_path = os.path.join(final_source, "research_report.md")
        if _read_text(staged_report_path) != report:
            write_text_atomic(staged_report_path, report)

        if actors is not None:
            staged_actors_path = os.path.join(final_source, "actors.json")
            if _read_json(staged_actors_path) != actors:
                write_json_atomic(staged_actors_path, actors)

        if sources is not None:
            staged_sources_path = os.path.join(final_source, "sources.json")
            if _read_json(staged_sources_path) != sources:
                write_json_atomic(staged_sources_path, sources)

        if meta is not None:
            staged_meta_path = os.path.join(final_source, "meta.json")
            if _read_json(staged_meta_path) != meta:
                write_json_atomic(staged_meta_path, meta)

        if (
            isinstance(existing_manifest, dict)
            and existing_manifest.get("files")
            == _research_contract_entries(final_source)
        ):
            return existing_manifest

        # Detect any concurrent or out-of-band mutation before replacing the
        # root.  Promotion itself retains its rollback directory until the new
        # manifest validates, so a later install error restores this generation.
        if not _validate_research_contract(root):
            raise RuntimeError(
                "research contract changed during sanctioned finalization"
            )
        return _promote_research_contract(final_source, root)
    finally:
        shutil.rmtree(final_source, ignore_errors=True)


def _run_extract_only_salvage(
    deerflow_dir: str, handoff_dir: str, prompt: str,
    model: str, depth: str, language: Optional[str], env: dict,
    on_progress: Callable[[int, str], None],
) -> bool:
    """ITEM-14：watchdog 超时打捞——用一个有界（默认 10 分钟）--extract-only 子进程，对已落盘的
    research_report.md 补跑结构化抽取 + 预测市场，恢复 actors/sources/timeline/quantitative。

    研究主 turn 被看门狗 SIGKILL 时，research_report.md 常已落盘、但 Stage 2 结构化抽取还没跑
    （'无结构化档案'）。此前只能带着空 actors/sources 降级继续；这里花一个短子进程把结构化档案
    抢救出来，让下游本体/图谱/模拟仍有真实的 actor/source 可用。

    有界（RESEARCH_EXTRACT_ONLY_TIMEOUT，默认 600s）、best-effort：任何失败/超时只记一行日志并
    返回 False，绝不让打捞本身把已成功的研究翻成失败。成功（exit 0）返回 True。
    """
    script = os.path.join(deerflow_dir, "deerflow_research.py")
    if not os.path.exists(script):
        return False
    try:
        _timeout = max(1, int(os.environ.get("RESEARCH_EXTRACT_ONLY_TIMEOUT", "600") or "600"))
    except ValueError:
        _timeout = 600

    # prompt 来源：优先复用 bridge 落在 handoff_dir 的 prediction_requirement.txt（不暴露在
    # cmdline，与 --prompt-file 既有约定一致）；缺失则写一个 0600 临时文件。
    _tmp_prompt: Optional[str] = None
    req_file = os.path.join(handoff_dir, "prediction_requirement.txt")
    if os.path.exists(req_file) and os.path.getsize(req_file) > 0:
        prompt_file = req_file
    else:
        fd, _tmp_prompt = tempfile.mkstemp(prefix=".extract-prompt-", suffix=".txt", dir=handoff_dir)
        with os.fdopen(fd, "w", encoding="utf-8") as _pf:
            _pf.write(prompt or "")
        try:
            os.chmod(_tmp_prompt, 0o600)
        except OSError:
            pass
        prompt_file = _tmp_prompt

    cmd = _detect_deerflow_python(deerflow_dir) + [
        script,
        "--extract-only",
        "--prompt-file", prompt_file,
        "--out-dir", handoff_dir,
        "--model", model or Config.DEERFLOW_MODEL,
        "--depth", depth or Config.DEERFLOW_RESEARCH_DEPTH,
    ]
    _lang = language if language is not None else Config.DEERFLOW_RESEARCH_LANGUAGE
    if _lang:
        cmd += ["--target-language", _lang]

    logger.info("ITEM-14：启动 --extract-only 打捞子进程（≤%ds）以恢复结构化档案", _timeout)
    try:
        on_progress(96, "超时打捞：补跑结构化抽取（actors/sources/timeline）…")
    except Exception:  # noqa: BLE001 — 进度回调失败不影响打捞
        pass
    try:
        r = subprocess.run(
            cmd, cwd=deerflow_dir, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, timeout=_timeout, start_new_session=True,
        )
        ok = (r.returncode == 0)
        if ok:
            logger.info("ITEM-14：--extract-only 打捞成功（结构化档案已补出）")
        else:
            logger.warning("ITEM-14：--extract-only 打捞退出码 %s（保留已有报告，降级继续）", r.returncode)
        return ok
    except subprocess.TimeoutExpired:
        logger.warning("ITEM-14：--extract-only 打捞超时（>%ds），降级继续", _timeout)
        return False
    except (OSError, subprocess.SubprocessError) as _e:
        logger.warning("ITEM-14：--extract-only 打捞失败（%s），降级继续", _e)
        return False
    finally:
        if _tmp_prompt is not None:
            try:
                os.unlink(_tmp_prompt)
            except OSError:
                pass


def _stage_walls(state: "PipelineState") -> dict[str, float]:
    """ITEM-18：从各阶段的 started_at→finished_at 时间戳算出每阶段墙钟秒数（stage → seconds）。

    供 build_stage_telemetry 把编排器的阶段级墙钟与 LLMMeter 的 token/成本合并。仅在两端时间戳
    都存在且差值非负时计入（未开始/未结束/时钟回拨 → 跳过，degrade-safe，绝不抛）。"""
    walls: dict[str, float] = {}
    for name, st in (getattr(state, "stages", None) or {}).items():
        started = _parse_iso(getattr(st, "started_at", None))
        finished = _parse_iso(getattr(st, "finished_at", None))
        if started is None or finished is None:
            continue
        dt = (finished - started).total_seconds()
        if dt >= 0:
            walls[str(name)] = dt
    # W9-2：多种子集成不占 stages（避免污染阶段带/前端渲染），墙钟从 options.ensemble_wall
    # 补入——此前 report 完成后的 +1h31m 集成窗口不归属任何阶段带（遥测里凭空消失）。
    try:
        ew = (getattr(state, "options", None) or {}).get("ensemble_wall") or {}
        e0, e1 = _parse_iso(ew.get("started_at")), _parse_iso(ew.get("finished_at"))
        if e0 is not None and e1 is not None:
            edt = (e1 - e0).total_seconds()
            if edt >= 0:
                walls["ensemble"] = edt
    except Exception:  # noqa: BLE001 — 纯观测，绝不抛
        pass
    return walls


def _reset_stage_attempt(stage: "StageState") -> None:
    """Reset one stage before real re-execution, including its timing window.

    A resumed failed stage is a new attempt. Keeping the first attempt's
    ``started_at`` while clearing only ``finished_at`` charged retry downtime and
    all prior attempts to the final attempt (the EV report appeared to take
    11,606 seconds although the successful report telemetry was 605 seconds).
    Reused completed stages do not call this helper and retain their original
    wall-clock interval.
    """
    stage.status = "pending"
    stage.progress = 0
    stage.message = ""
    stage.error = None
    stage.started_at = None
    stage.finished_at = None


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
    # RES-8 镜像（resume 路径）：错误串/过短的卷宗按缺失处理，与 live 路径一致。
    _dossier = _read_text(os.path.join(handoff_dir, "actor_dossier.md"))
    if _dossier and _is_degraded_dossier(_dossier):
        logger.warning("resume：actor_dossier.md 疑似降级产物（错误串/过短），按缺失处理")
        _dossier = ""
    return {
        "report": report,
        "report_path": report_path,
        # 双轨 Track B 产物：角色本体档案（actor_dossier.md）。缺失时 _read_text 返回 ""，
        # 下游按「空即退化」处理，与单轨/旗标关闭时逐字节一致。
        "actor_dossier": _dossier,
        "actors": _read_json(os.path.join(handoff_dir, "actors.json")),
        "sources": _read_json(os.path.join(handoff_dir, "sources.json")),
        "timeline": _read_json(os.path.join(handoff_dir, "timeline.json")),
        "exit_code": None,
        "resumed": True,
    }


# ===========================================================================
# SIM-ADD-1（决策通道点火的关键修复）：forecast_inputs 兜底注入
# ---------------------------------------------------------------------------
# 取证（pipe_bef6879b2e94 / sim_05ab2bdebbd2）：handoff/actors.json 无 'forecast_inputs'
# 键 → world_state_seed_from_actors(actors) 返回 {} → 决策通道从未点火、无
# world_state_trajectory.json → 18 轮模拟对任何 forecast 数字零贡献。研究报告本身几乎
# 总带「## Four Mutually Exclusive Scenarios」这类带概率的情景节，actors.
# forecast_inputs_from_report_markdown 早已能确定性解析回 forecast_inputs schema，只是
# 从未接线。下面两个纯/半纯 helper 负责在**研究定稿**与 **PREPARE 种子前**两处把它接上：
#   * _forecast_inputs_missing(actors)：actors 是否缺可用的 forecast_inputs.scenarios；
#   * inject_forecast_inputs_from_report(actors, report_md)：缺则从报告解析并**就地**注入，
#     返回注入用的 forecast_inputs（含非空 scenarios）——命中；否则 None（degrade-safe）。
# 对 pre-v1 研究，定稿处的注入在 _finalize_research_contract 前完成，故 forecast_inputs
# 随外层 research manifest 一并密封。actor-intelligence/v1 自己已经过 producer sealing，
# 任何缺失都必须上游重做；这个兼容 helper 对它严格 no-op。
# ===========================================================================
def _is_sealed_actor_intelligence_v1(actors: Any) -> bool:
    """Return whether ``actors`` carries the producer-owned v1 top contract."""
    if not isinstance(actors, dict):
        return False
    contract = actors.get("actor_intelligence_contract")
    return bool(
        isinstance(contract, dict)
        and contract.get("schema_version") == ACTOR_INTELLIGENCE_SCHEMA_VERSION
    )


def _reconcile_research_cast(actors: Any) -> tuple[Any, dict[str, Any]]:
    """Reconcile legacy casts while treating sealed v1 actors as immutable.

    ``reconcile_cast`` remains useful as a pure duplicate detector for a v1
    artifact, but its merge representation is a legacy compatibility shape: it
    wraps canonical dimension lists in ``{"claims": ...}`` and necessarily
    changes the actor roster.  Applying that output after the producer sealed
    ``actor_count``/``actor_ids_sha256`` would create a self-contradictory
    contract.  For v1, retain the exact original object and expose the proposed
    merge only as an audit.  Pre-v1 payloads keep the historical mutation path.
    """
    from ..utils.actors import reconcile_cast

    reconciled, raw_audit = reconcile_cast(actors)
    audit = dict(raw_audit or {})
    merged = list(audit.get("merged") or [])
    if _is_sealed_actor_intelligence_v1(actors):
        hypothetical_n_after = audit.get("n_after")
        audit.update({
            "applied": False,
            "reason": "sealed_actor_intelligence_v1_is_immutable",
            "schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
            "hypothetical_n_after": hypothetical_n_after,
            "n_after": audit.get("n_before"),
        })
        return actors, audit
    audit.update({
        "applied": bool(merged),
        "reason": "legacy_reconcile_applied" if merged else "no_duplicates",
    })
    return reconciled, audit


def _actor_explicit_simulation_tier(actor: dict[str, Any]) -> Optional[int]:
    """Mirror the producer's explicit Tier 1-4 parser for contract checks."""
    raw = actor.get("simulation_tier")
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int) and raw in (1, 2, 3, 4):
        return raw
    if isinstance(raw, str):
        value = raw.strip()
        if re.fullmatch(r"[1-4]", value):
            return int(value)
    return None


def _actor_roster_name(actor: dict[str, Any]) -> str:
    """Mirror the producer's NFKC identity namespace exactly."""
    return _actor_normalized_name(actor.get("name"))


def _valid_actor_source_url(value: Any) -> bool:
    """Mirror the producer URL admission needed by fetched-source receipts."""
    try:
        from urllib.parse import unquote, urlparse

        raw = str(value or "").strip()
        if not raw or any(char.isspace() or ord(char) < 32 for char in raw):
            return False
        parsed = urlparse(raw)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            return False
        host = (parsed.hostname or "").lower().rstrip(".")
        if len([label for label in host.split(".") if label]) < 2:
            return False
        path = unquote(parsed.path or "")
        if path.endswith(("_", "…", "...")):
            return False
        if host.endswith("wikipedia.org"):
            if not path.startswith("/wiki/"):
                return False
            slug = path[len("/wiki/"):].strip("/")
            if not slug:
                return False
            if len(slug) < 3 and not (slug.isalpha() and slug.isupper()):
                return False
            if re.search(r"_[A-Za-z]$", slug):
                return False
        return True
    except (TypeError, ValueError):
        return False


def _actor_source_is_fetched(source: dict[str, Any]) -> bool:
    if not isinstance(source, dict) or not _valid_actor_source_url(
        source.get("url")
    ):
        return False
    origin = str(source.get("source_origin") or "").strip().casefold()
    return (
        (origin == "fetched" and source.get("reachable") is True)
        or source.get("ok") is True
    )


def _actor_as_items(value: Any) -> list[Any]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _actor_stable_id(name: Any) -> str:
    """Mirror the producer's semantic actor identity exactly."""
    normalized = _actor_normalized_name(name)
    if not normalized:
        return ""
    return "actor_" + hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:16]


def _actor_normalized_name(value: Any) -> str:
    """Canonicalize every actor name/alias in the stable-ID namespace."""
    import unicodedata

    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold().split()
    )


def _actor_source_identity_url(value: Any) -> str:
    from urllib.parse import urlsplit, urlunsplit

    raw = str(value or "").strip().rstrip("/")
    if not _valid_actor_source_url(raw):
        return raw
    parsed = urlsplit(raw)
    return urlunsplit((
        parsed.scheme.lower(), parsed.netloc.lower(), parsed.path,
        parsed.query, "",
    )).rstrip("/")


def _actor_stable_source_id(value: Any) -> str:
    normalized = _actor_source_identity_url(value)
    if not _valid_actor_source_url(normalized):
        return ""
    return "src_" + hashlib.sha256(
        normalized.encode("utf-8")
    ).hexdigest()[:16]


def _actor_receipt_scopes(source: dict[str, Any]) -> list[dict[str, str]]:
    """Return the producer's normalized receipt-scope projection."""
    scopes: list[dict[str, str]] = []
    for raw in _actor_as_items(source.get("receipt_scopes")):
        if not isinstance(raw, dict):
            continue
        scope = {
            "thread_id": str(raw.get("thread_id") or "").strip(),
            "lane": str(raw.get("lane") or "").strip(),
            "purpose": str(raw.get("purpose") or "").strip(),
            "receipt_id": str(raw.get("receipt_id") or "").strip(),
            "content_sha256": str(
                raw.get("content_sha256") or ""
            ).strip().lower(),
        }
        if any(scope.values()):
            scopes.append(scope)
    direct = {
        "thread_id": str(source.get("thread_id") or "").strip(),
        "lane": str(source.get("lane") or "").strip(),
        "purpose": str(source.get("purpose") or "").strip(),
        "receipt_id": str(source.get("receipt_id") or "").strip(),
        "content_sha256": str(
            source.get("content_sha256") or ""
        ).strip().lower(),
    }
    if any(direct.values()) and direct not in scopes:
        scopes.append(direct)
    return scopes


def _actor_is_track_b_purpose(value: Any) -> bool:
    purpose = str(value or "").strip().casefold()
    return purpose.startswith("actor-") or purpose.startswith("actor_")


def _actor_valid_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(value or "").strip()))


def _actor_normalized_support_text(value: Any) -> str:
    import unicodedata

    return " ".join(
        unicodedata.normalize("NFKC", str(value or "")).casefold().split()
    )


def _actor_support_span(source_text: str, quote: str) -> Optional[dict[str, Any]]:
    if not source_text or not quote:
        return None
    exact_start = source_text.find(quote)
    if exact_start >= 0:
        return {
            "basis": "exact_excerpt",
            "start": exact_start,
            "end": exact_start + len(quote),
        }
    normalized_source = _actor_normalized_support_text(source_text)
    normalized_quote = _actor_normalized_support_text(quote)
    normalized_start = normalized_source.find(normalized_quote)
    if normalized_quote and normalized_start >= 0:
        return {
            "basis": "normalized_excerpt",
            "start": normalized_start,
            "end": normalized_start + len(normalized_quote),
        }
    return None


def _actor_source_lookup(
    source_rows: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, dict[str, Any]], list[str]]:
    """Build producer-compatible source aliases and reject identity drift."""
    lookup: dict[str, str] = {}
    records: dict[str, dict[str, Any]] = {}
    title_ids: dict[str, set[str]] = {}
    errors: list[str] = []
    track_b_thread_ids = {
        str(scope.get("thread_id") or "").strip()
        for source in source_rows
        for scope in _actor_receipt_scopes(source)
        if _actor_is_track_b_purpose(scope.get("purpose"))
        and str(scope.get("lane") or "").strip().casefold() == "track-b"
        and str(scope.get("thread_id") or "").strip()
    }
    if len(track_b_thread_ids) != 1:
        errors.append(
            "track_b_receipt_thread_unresolvable:"
            f"count={len(track_b_thread_ids)}"
        )
    for index, source in enumerate(source_rows, start=1):
        if not _actor_source_is_fetched(source):
            continue
        source_id = _actor_stable_source_id(source.get("url"))
        supplied_id = str(source.get("source_id") or "").strip()
        if not source_id or supplied_id != source_id:
            errors.append(f"source_id_not_canonical:{supplied_id or index}")
            continue
        if source_id in records:
            errors.append(f"source_id_duplicate:{source_id}")
            continue
        records[source_id] = source
        raw_url = str(source.get("url") or "").strip().rstrip("/")
        identity_url = _actor_source_identity_url(raw_url)
        for alias in (
            source_id, source_id.casefold(), raw_url, raw_url.casefold(),
            identity_url, identity_url.casefold(), f"s{index}", f"[s{index}]",
        ):
            if alias:
                lookup[alias] = source_id
        title = " ".join(str(source.get("title") or "").casefold().split())
        if title:
            title_ids.setdefault(title, set()).add(source_id)
    for title, ids in title_ids.items():
        if len(ids) == 1:
            lookup[title] = next(iter(ids))
    if len(track_b_thread_ids) != 1:
        # Mirror the producer's Track-B lookup: when the receipt ledger does
        # not identify exactly one actor-research thread, no claim may resolve
        # through a stale or mixed thread by happenstance.
        lookup.clear()
        records.clear()
    return lookup, records, errors


def _actor_search_result_receipt_id(receipt: dict[str, Any]) -> str:
    """Mirror the producer-owned identity of one Track-B search result."""
    identity = {
        key: receipt.get(key)
        for key in (
            "schema_version", "thread_id", "lane", "purpose",
            "query_sha256", "result_sha256", "result_chars",
        )
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "search_result_" + hashlib.sha256(canonical).hexdigest()[:24]


def _actor_search_query_from_args(value: Any) -> str:
    """Mirror the producer's canonical search-query text projection."""
    if isinstance(value, dict):
        raw = value.get("query") or value.get("q") or value.get("queries") or ""
        if isinstance(raw, list):
            raw = " ".join(str(item) for item in raw)
    else:
        raw = value if isinstance(value, str) else ""
    return " ".join(str(raw or "").split()).strip()


def _actor_validated_search_result_receipt(
    value: Any,
    *,
    required_thread_id: str,
) -> Optional[dict[str, Any]]:
    """Return the producer's exact canonical current-thread receipt."""
    if not isinstance(value, dict) or isinstance(value.get("result_chars"), bool):
        return None
    try:
        result_chars = int(value.get("result_chars"))
    except (TypeError, ValueError):
        return None
    query = _actor_search_query_from_args(value.get("query"))
    canonical = {
        "schema_version": str(value.get("schema_version") or "").strip(),
        "thread_id": str(value.get("thread_id") or "").strip(),
        "lane": str(value.get("lane") or "").strip().casefold(),
        "purpose": str(value.get("purpose") or "").strip(),
        "query": query,
        "query_sha256": str(value.get("query_sha256") or "").strip().lower(),
        "result_sha256": str(value.get("result_sha256") or "").strip().lower(),
        "result_chars": result_chars,
    }
    result_id = str(value.get("result_id") or "").strip()
    if (
        canonical["schema_version"] != _ACTOR_SEARCH_RESULT_RECEIPT_SCHEMA
        or canonical["thread_id"] != str(required_thread_id or "").strip()
        or canonical["lane"] != "track-b"
        or not _actor_is_track_b_purpose(canonical["purpose"])
        or not query
        or not _actor_valid_sha256(canonical["query_sha256"])
        or canonical["query_sha256"] != hashlib.sha256(
            query.encode("utf-8")
        ).hexdigest()
        or not _actor_valid_sha256(canonical["result_sha256"])
        or result_chars <= 0
        or result_id != _actor_search_result_receipt_id(canonical)
    ):
        return None
    canonical["result_id"] = result_id
    return canonical


def _actor_track_b_provenance_reception_seals(
    sources: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Recompute current Track-B source and search-receipt projections.

    The coverage sidecar is producer output, not reception authority.  Source
    admission is rebuilt from ``sources.json`` receipt scopes, while every
    search receipt is independently canonicalized and bound to that same sole
    current Track-B thread before its set hash is accepted.
    """
    errors: list[str] = []
    thread_ids = {
        str(scope.get("thread_id") or "").strip()
        for source in sources
        for scope in _actor_receipt_scopes(source)
        if _actor_is_track_b_purpose(scope.get("purpose"))
        and str(scope.get("lane") or "").strip().casefold() == "track-b"
        and str(scope.get("thread_id") or "").strip()
    }
    current_thread = next(iter(thread_ids)) if len(thread_ids) == 1 else ""
    if not current_thread:
        errors.append(
            "actor_dossier_track_b_receipt_thread_unresolvable:"
            f"count={len(thread_ids)}"
        )

    admitted_source_ids: list[str] = []
    if current_thread:
        for source in sources:
            if not _actor_source_is_fetched(source):
                continue
            source_id = _actor_stable_source_id(source.get("url"))
            if not source_id or str(source.get("source_id") or "") != source_id:
                continue
            current_scopes = [
                scope for scope in _actor_receipt_scopes(source)
                if _actor_is_track_b_purpose(scope.get("purpose"))
                and str(scope.get("lane") or "").strip().casefold() == "track-b"
                and str(scope.get("thread_id") or "").strip() == current_thread
            ]
            if not current_scopes:
                continue
            valid_scopes = [
                scope for scope in current_scopes
                if str(scope.get("receipt_id") or "").strip()
                and _actor_valid_sha256(scope.get("content_sha256"))
                and (
                    not _actor_valid_sha256(source.get("content_sha256"))
                    or str(scope.get("content_sha256") or "").strip().lower()
                    == str(source.get("content_sha256") or "").strip().lower()
                )
            ]
            if not valid_scopes:
                errors.append(
                    f"actor_dossier_track_b_receipt_scope_invalid:{source_id}"
                )
                continue
            admitted_source_ids.append(source_id)
    admitted_source_ids = sorted(set(admitted_source_ids))

    raw_receipts = coverage.get("search_result_receipts")
    if not isinstance(raw_receipts, list):
        errors.append("actor_dossier_search_result_receipt_list_invalid")
        raw_receipts = []
    canonical_receipts: list[dict[str, Any]] = []
    seen_result_ids: set[str] = set()
    for index, value in enumerate(raw_receipts):
        canonical = _actor_validated_search_result_receipt(
            value,
            required_thread_id=current_thread,
        )
        if canonical is None or canonical != value:
            errors.append(
                f"actor_dossier_search_result_receipt_invalid:{index}"
            )
            continue
        result_id = canonical["result_id"]
        if result_id in seen_result_ids:
            errors.append(
                f"actor_dossier_search_result_receipt_duplicate:{result_id}"
            )
            continue
        seen_result_ids.add(result_id)
        canonical_receipts.append(canonical)
    canonical_receipts.sort(key=lambda row: row["result_id"])
    if raw_receipts != canonical_receipts:
        errors.append("actor_dossier_search_result_receipt_order_or_set_mismatch")
    canonical_receipt_bytes = json.dumps(
        canonical_receipts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    receipt_sha256 = hashlib.sha256(canonical_receipt_bytes).hexdigest()
    if coverage.get("search_result_receipts_sha256") != receipt_sha256:
        errors.append("actor_dossier_search_result_receipt_sha256_mismatch")

    return {
        "required_receipt_lane": "track-b",
        "required_receipt_thread_id": current_thread,
        "admitted_source_ids": admitted_source_ids,
        "admitted_source_ids_sha256": hashlib.sha256(
            "\n".join(admitted_source_ids).encode("utf-8")
        ).hexdigest(),
        "search_result_receipts": canonical_receipts,
        "search_result_receipts_sha256": receipt_sha256,
    }, errors


def _actor_resolve_source_ref(value: Any, lookup: dict[str, str]) -> str:
    if isinstance(value, dict):
        value = (
            value.get("source_id") or value.get("url") or value.get("title")
            or value.get("ref")
        )
    key = str(value or "").strip()
    if not key:
        return ""
    normalized_title = " ".join(key.casefold().split())
    return str(
        lookup.get(key)
        or lookup.get(key.casefold())
        or lookup.get(_actor_source_identity_url(key))
        or lookup.get(_actor_source_identity_url(key).casefold())
        or lookup.get(normalized_title)
        or ""
    )


def _actor_normalize_source_support(
    value: dict[str, Any],
    raw_refs: list[Any],
    lookup: dict[str, str],
    records: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Revalidate exact quote/receipt/content identities for Track-B claims."""
    candidates = _actor_as_items(
        value.get("source_support")
        or value.get("evidence_support")
        or value.get("supporting_evidence")
    )
    if not candidates:
        quote = (
            value.get("supporting_quote") or value.get("exact_quote")
            or value.get("source_quote")
        )
        if quote:
            candidates = [{
                "source_ref": raw_refs[0] if len(raw_refs) == 1 else "",
                "supporting_quote": quote,
                "supporting_span": value.get("supporting_span"),
            }]
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        ref = (
            raw.get("source_ref") or raw.get("source_id") or raw.get("url")
            or raw.get("ref")
        )
        if not ref and len(raw_refs) == 1:
            ref = raw_refs[0]
        source_id = _actor_resolve_source_ref(ref, lookup)
        source = records.get(source_id)
        if not source_id or not isinstance(source, dict):
            continue
        supplied = {
            "thread_id": str(raw.get("thread_id") or "").strip(),
            "lane": str(raw.get("lane") or "").strip(),
            "purpose": str(raw.get("purpose") or "").strip(),
            "receipt_id": str(raw.get("receipt_id") or "").strip(),
            "content_sha256": str(
                raw.get("content_sha256") or ""
            ).strip().lower(),
        }
        scope = next((
            candidate for candidate in _actor_receipt_scopes(source)
            if _actor_is_track_b_purpose(candidate.get("purpose"))
            and str(candidate.get("lane") or "").strip().casefold() == "track-b"
            and all(str(candidate.get(key) or "").strip() for key in (
                "thread_id", "lane", "purpose", "receipt_id", "content_sha256"
            ))
            and _actor_valid_sha256(candidate.get("content_sha256"))
            and all(
                not supplied[key] or supplied[key] == candidate.get(key)
                for key in supplied
            )
        ), None)
        if scope is None:
            continue
        quote = str(
            raw.get("supporting_quote") or raw.get("exact_quote")
            or raw.get("quote") or raw.get("text") or ""
        ).strip()
        source_text = ""
        for key in ("content", "excerpt"):
            candidate_text = source.get(key)
            if isinstance(candidate_text, str) and candidate_text.strip():
                source_text = candidate_text
                break
        span = _actor_support_span(source_text, quote)
        if span is None:
            continue
        if isinstance(source.get("content"), str) and source.get("content"):
            if hashlib.sha256(source["content"].encode("utf-8")).hexdigest() != str(
                scope.get("content_sha256") or ""
            ).lower():
                continue
        dedupe_key = (source_id, _actor_normalized_support_text(quote))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append({
            "source_id": source_id,
            "supporting_quote": quote,
            "supporting_span": span,
            "receipt_id": scope["receipt_id"],
            "content_sha256": scope["content_sha256"],
            "source_publication_date": str(
                source.get("publication_date") or source.get("published_at")
                or source.get("date") or ""
            ).strip(),
            "thread_id": scope["thread_id"],
            "lane": scope["lane"],
            "purpose": scope["purpose"],
        })
    return normalized


def _actor_claim_text(value: dict[str, Any]) -> str:
    for key in (
        "claim", "summary", "fact", "detail", "description", "plan",
        "action", "investment", "decision", "preference", "value",
    ):
        text = str(value.get(key) or "").strip()
        if text:
            return text
    semantic: list[str] = []
    for key in (
        "driver", "gains_if", "loses_if", "status", "horizon",
        "dependencies", "trigger", "basis",
    ):
        raw = value.get(key)
        if raw not in (None, "", [], {}):
            semantic.append(f"{key}={raw}")
    return "; ".join(semantic)


def _actor_claim_projection(
    actor_id: str,
    dimension: str,
    claim: dict[str, Any],
) -> dict[str, Any]:
    support_projection = sorted(({
        "source_id": str(row.get("source_id") or ""),
        "supporting_quote_sha256": hashlib.sha256(
            _actor_normalized_support_text(
                row.get("supporting_quote")
            ).encode("utf-8")
        ).hexdigest(),
        "receipt_id": str(row.get("receipt_id") or ""),
        "content_sha256": str(row.get("content_sha256") or ""),
    } for row in (claim.get("source_support") or []) if isinstance(row, dict)),
        key=lambda row: (
            row["source_id"], row["supporting_quote_sha256"], row["receipt_id"]
        ),
    )
    return {
        "actor_id": str(actor_id or ""),
        "dimension": str(dimension or ""),
        "claim": " ".join(str(claim.get("claim") or "").split()),
        "evidence_type": str(claim.get("evidence_type") or ""),
        "claim_valid_at": str(claim.get("claim_valid_at") or ""),
        "horizon": str(claim.get("horizon") or ""),
        "status": str(claim.get("status") or ""),
        "confidence": str(claim.get("confidence") or ""),
        "dependencies": sorted({
            " ".join(str(item).split())
            for item in (claim.get("dependencies") or []) if str(item).strip()
        }),
        "contradictions": sorted({
            " ".join(str(item).split())
            for item in (claim.get("contradictions") or []) if str(item).strip()
        }),
        "qualifiers": claim.get("qualifiers") or {},
        "source_support": support_projection,
    }


def _actor_relationship_causal_attributes(
    relationship: dict[str, Any],
) -> dict[str, Any]:
    """Rebuild the producer's canonical causal identity projection.

    Persisted actor-intelligence/v1 relationships are already normalized by
    Stage 1.  Reception therefore rejects, rather than silently normalizes,
    non-canonical values.  This prevents two different received byte
    projections from sharing the same canonical relationship identity.
    """
    normalized: dict[str, Any] = {}
    for key in _ACTOR_RELATIONSHIP_CAUSAL_ATTRIBUTE_KEYS:
        if key not in relationship:
            continue
        raw = relationship[key]
        if raw in (None, "", [], {}):
            raise ValueError(f"{key} must be omitted when empty")
        if isinstance(raw, str):
            value: Any = " ".join(
                unicodedata.normalize("NFKC", raw).split()
            )
            if not value:
                raise ValueError(f"{key} must be omitted when empty")
            if value != raw:
                raise ValueError(f"{key} is not canonically normalized")
        elif isinstance(raw, bool):
            value = raw
        elif isinstance(raw, (int, float)):
            if isinstance(raw, float) and not math.isfinite(raw):
                raise ValueError(f"{key} must be finite")
            value = raw
        else:
            raise ValueError(f"{key} must be a JSON scalar")
        normalized[key] = value
    return normalized


def _actor_normalize_claim(
    value: Any,
    *,
    actor_id: str,
    dimension: str,
    lookup: dict[str, str],
    records: dict[str, dict[str, Any]],
    causal_attributes: Optional[dict[str, Any]] = None,
) -> Optional[dict[str, Any]]:
    """Rebuild the producer's canonical claim projection from received bytes."""
    if not isinstance(value, dict):
        return None
    text = _actor_claim_text(value)
    if not text:
        return None
    raw_qualifiers = (
        value.get("qualifiers")
        if isinstance(value.get("qualifiers"), dict) else {}
    )
    raw_refs: list[Any] = []
    for key in (
        "source_refs", "sources", "source_urls", "source_ids", "citations",
        "evidence_refs",
    ):
        raw_refs.extend(_actor_as_items(value.get(key)))
        raw_refs.extend(_actor_as_items(raw_qualifiers.get(key)))
    claim_valid_at = str(
        value.get("claim_valid_at") or value.get("valid_at")
        or value.get("as_of_date") or value.get("as_of")
        or raw_qualifiers.get("claim_valid_at")
        or raw_qualifiers.get("valid_at")
        or raw_qualifiers.get("as_of_date")
        or raw_qualifiers.get("as_of") or ""
    ).strip()
    confidence = str(
        value.get("confidence") or raw_qualifiers.get("confidence") or "unknown"
    ).strip().lower()
    if confidence not in {"high", "medium", "low", "unknown"}:
        confidence = "unknown"
    evidence_type = str(
        value.get("evidence_type") or value.get("epistemic_status")
        or raw_qualifiers.get("evidence_type")
        or raw_qualifiers.get("epistemic_status") or "unknown"
    ).strip().lower().replace("-", "_").replace(" ", "_")
    if evidence_type not in {
        "verified_fact", "actor_stated_claim", "analyst_inference",
        "contested", "unknown",
    }:
        evidence_type = "unknown"
    horizon = str(
        value.get("horizon") or raw_qualifiers.get("horizon") or ""
    ).strip()
    status = str(
        value.get("status") or raw_qualifiers.get("status") or ""
    ).strip()
    dependencies = [
        str(item).strip() for item in _actor_as_items(
            value.get("dependencies") or raw_qualifiers.get("dependencies")
        ) if str(item).strip()
    ]
    contradictions = [
        str(item).strip() for item in _actor_as_items(
            value.get("contradictions") or raw_qualifiers.get("contradictions")
        ) if str(item).strip()
    ]
    qualifiers: dict[str, Any] = {}
    for key in _ACTOR_INTELLIGENCE_QUALIFIER_KEYS:
        raw = value.get(key)
        if raw in (None, "", [], {}):
            raw = raw_qualifiers.get(key)
        if raw not in (None, "", [], {}):
            qualifiers[key] = raw
    actor_knows = value.get("actor_knows")
    if actor_knows in (None, ""):
        actor_knows = raw_qualifiers.get("actor_knows")
    if isinstance(actor_knows, bool):
        qualifiers["actor_knows"] = actor_knows
    visibility = str(
        value.get("visibility") or raw_qualifiers.get("visibility") or ""
    ).strip().casefold().replace("-", "_").replace(" ", "_")
    if visibility in _ACTOR_KNOWLEDGE_VISIBILITY_VALUES:
        qualifiers["visibility"] = visibility
    source_support = _actor_normalize_source_support(
        value, raw_refs, lookup, records)
    claim = {
        "claim": text,
        "evidence_type": evidence_type,
        "claim_valid_at": claim_valid_at,
        "as_of_date": claim_valid_at,
        "horizon": horizon,
        "status": status,
        "confidence": confidence,
        "source_refs": sorted({
            str(row.get("source_id") or "")
            for row in source_support if row.get("source_id")
        }),
        "source_support": source_support,
        "dependencies": dependencies,
        "contradictions": contradictions,
        "qualifiers": qualifiers,
    }
    projection = _actor_claim_projection(actor_id, dimension, claim)
    if causal_attributes is not None:
        projection["causal_attributes"] = causal_attributes
    digest = hashlib.sha256(json.dumps(
        projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    claim["claim_id"] = f"claim_{digest[:20]}"
    claim["claim_sha256"] = digest
    return claim


def _actor_multiset_sha256(values: list[str]) -> str:
    counts = {value: values.count(value) for value in sorted(set(values))}
    return hashlib.sha256(json.dumps(
        counts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _actor_lineage_id(payload: dict[str, Any]) -> str:
    body = {
        key: value for key, value in payload.items()
        if key not in {"lineage_id", "sealed_at"}
    }
    return "actor_lineage_" + hashlib.sha256(json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:24]


def _actor_sealed_visible_claim_text(value: Any) -> str:
    """Mirror Stage 1's bounded, human-visible family-claim rendition."""
    raw = unicodedata.normalize("NFKC", str(value or ""))
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]", "", raw)
    raw = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", raw)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in raw.split("\n")]
    protected = {
        index for index, line in enumerate(lines)
        if _ACTOR_STAGE1_BLOCK_SENTINEL_RE.fullmatch(line)
    }
    unsafe = {
        index for index, line in enumerate(lines)
        if index not in protected and line and any(
            pattern.search(line)
            for pattern in _ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS
        )
    }
    nonempty = [index for index, line in enumerate(lines) if line]
    for width in range(2, min(8, len(nonempty)) + 1):
        for start in range(0, len(nonempty) - width + 1):
            indexes = nonempty[start:start + width]
            if any(
                right - left > 3
                for left, right in zip(indexes, indexes[1:], strict=False)
            ):
                continue
            window = " ".join(lines[index] for index in indexes)
            matched_patterns = [
                pattern
                for pattern in _ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS
                if pattern.search(window)
            ]
            if not matched_patterns:
                continue
            attributed = [index for index in indexes if index in unsafe]
            if attributed:
                attributed_text = " ".join(lines[index] for index in attributed)
                if any(
                    not pattern.search(attributed_text)
                    for pattern in matched_patterns
                ):
                    unsafe.update(
                        index for index in indexes
                        if index not in protected
                        and _ACTOR_UNSAFE_EVIDENCE_CONTROL_FRAGMENT_PATTERN.search(
                            lines[index]
                        )
                    )
                continue
            unsafe.update(index for index in indexes if index not in protected)

    rendered: list[str] = []
    for index, line in enumerate(lines):
        if not line:
            if rendered and rendered[-1] != "":
                rendered.append("")
            continue
        if index in unsafe:
            rendered.append(_ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT)
            continue
        if index in protected:
            rendered.append(line)
            continue
        fragments = [
            fragment.strip()
            for fragment in re.split(r"(?<=[.!?。！？;；])\s+", line)
            if fragment.strip()
        ] or [line]
        safe_fragments: list[str] = []
        for fragment in fragments:
            replacement = (
                _ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT
                if any(
                    pattern.search(fragment)
                    for pattern in _ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS
                )
                else fragment
            )
            if not (
                replacement == _ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT
                and safe_fragments
                and safe_fragments[-1]
                == _ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT
            ):
                safe_fragments.append(replacement)
        rendered.append(" ".join(safe_fragments))
    while rendered and rendered[-1] == "":
        rendered.pop()
    safe = "\n".join(rendered).strip()
    if len(safe) > 900:
        safe = safe[:899].rstrip() + "…"
    safe = re.sub(r"\[\s*S\d+\s*\]", "", safe, flags=re.IGNORECASE)
    safe = " ".join(unicodedata.normalize("NFKC", safe).split())
    substantive = safe.replace(_ACTOR_UNSAFE_EVIDENCE_TEXT_REPLACEMENT, " ")
    if len(re.sub(r"[^\w]+", "", substantive, flags=re.UNICODE)) < 24:
        return ""
    return safe


def _actor_claim_is_behavior_ready(claim: Any) -> bool:
    """Mirror the producer's floor for behavior-family evidence."""
    if not isinstance(claim, dict) or not claim.get("source_support"):
        return False
    if str(claim.get("evidence_type") or "").strip() in {"", "unknown"}:
        return False
    if str(claim.get("confidence") or "").strip() in {"", "unknown"}:
        return False
    return all(
        str(claim.get(key) or "").strip()
        for key in ("claim_valid_at", "horizon", "status")
    )


def _actor_dossier_reception_seals(
    dossier: str,
    *,
    lookup: dict[str, str],
    records: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[str]]:
    """Recompute semantic actor and claim seals from the dossier ledger."""
    errors: list[str] = []
    matches = list(_ACTOR_DOSSIER_LEDGER_RE.finditer(str(dossier or "")))
    if len(matches) != 1:
        return {}, [f"dossier_ledger_count:{len(matches)}"]
    try:
        ledger = json.loads(matches[0].group(1))
    except (TypeError, ValueError):
        return {}, ["dossier_ledger_unparseable"]
    if not isinstance(ledger, dict):
        return {}, ["dossier_ledger_not_object"]
    if ledger.get("schema_version") != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
        errors.append("dossier_ledger_schema_mismatch")
    raw_rows = ledger.get("actors")
    if not isinstance(raw_rows, list) or not raw_rows:
        return {}, [*errors, "dossier_actor_rows_empty"]
    actor_ids: list[str] = []
    roster: list[str] = []
    claim_hashes: list[str] = []
    behavior_family_projection: list[dict[str, Any]] = []
    behavior_ready_family_count = 0
    for index, row in enumerate(raw_rows):
        if not isinstance(row, dict):
            errors.append(f"dossier_actor_not_object:{index}")
            continue
        name = str(row.get("name") or "").strip()
        actor_id = _actor_stable_id(name)
        if not actor_id:
            errors.append(f"dossier_actor_name_missing:{index}")
            continue
        if _actor_explicit_simulation_tier(row) not in (1, 2):
            errors.append(f"dossier_actor_tier_invalid:{actor_id}")
            continue
        actor_ids.append(actor_id)
        roster.append(_actor_roster_name(row))
        dimensions = row.get("dimensions")
        if not isinstance(dimensions, dict):
            errors.append(f"dossier_dimensions_not_object:{actor_id}")
            continue
        behavior_ready_claims: dict[str, list[dict[str, Any]]] = {}
        for dimension in ACTOR_INTELLIGENCE_DIMENSIONS:
            cell = dimensions.get(dimension)
            if not isinstance(cell, dict):
                errors.append(
                    f"dossier_dimension_missing:{actor_id}:{dimension}"
                )
                continue
            status = str(cell.get("status") or "").strip().casefold()
            if status == "gap":
                continue
            if status != "covered":
                errors.append(
                    f"dossier_dimension_status_invalid:{actor_id}:{dimension}"
                )
                continue
            raw_claims = cell.get("claims")
            if not isinstance(raw_claims, list) or not raw_claims:
                errors.append(
                    f"dossier_covered_without_claims:{actor_id}:{dimension}"
                )
                continue
            for claim_index, raw_claim in enumerate(raw_claims):
                normalized = _actor_normalize_claim(
                    raw_claim,
                    actor_id=actor_id,
                    dimension=dimension,
                    lookup=lookup,
                    records=records,
                )
                if not normalized or not normalized.get("source_support"):
                    errors.append(
                        "dossier_claim_not_quote_receipt_bound:"
                        f"{actor_id}:{dimension}:{claim_index}"
                    )
                    continue
                claim_hashes.append(normalized["claim_sha256"])
                if _actor_claim_is_behavior_ready(normalized):
                    behavior_ready_claims.setdefault(dimension, []).append(
                        normalized
                    )
        family_projection: dict[str, Any] = {
            "actor": name,
            "actor_id": actor_id,
            "families": {},
        }
        for family, family_dimensions in _ACTOR_BEHAVIOR_READY_FAMILIES.items():
            candidates = [
                (
                    family_dimensions.index(dimension),
                    dimension,
                    claim,
                    visible_claim_text,
                )
                for dimension in family_dimensions
                for claim in behavior_ready_claims.get(dimension, [])
                if (
                    visible_claim_text := _actor_sealed_visible_claim_text(
                        claim.get("claim")
                    )
                )
            ]
            if not candidates:
                errors.append(
                    f"dossier_behavior_family_missing:{actor_id}:{family}"
                )
                continue
            behavior_ready_family_count += 1
            (
                _order,
                selected_dimension,
                selected_claim,
                visible_claim_text,
            ) = min(
                candidates,
                key=lambda item: (
                    item[0], str(item[2].get("claim_sha256") or "")
                ),
            )
            family_projection["families"][family] = {
                "dimension": selected_dimension,
                "claim_id": str(selected_claim.get("claim_id") or ""),
                "claim_sha256": str(
                    selected_claim.get("claim_sha256") or ""
                ),
                "visible_claim_text": visible_claim_text,
                "source_ids": sorted({
                    str(support.get("source_id") or "")
                    for support in selected_claim.get("source_support") or []
                    if isinstance(support, dict)
                    and str(support.get("source_id") or "")
                }),
            }
        behavior_family_projection.append(family_projection)
    canonical_family_projection = json.dumps(
        behavior_family_projection,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return {
        "tier_1_2_actor_count": len(actor_ids),
        "tier_1_2_actor_roster_sha256": hashlib.sha256(
            "\n".join(sorted(roster)).encode("utf-8")
        ).hexdigest(),
        "tier_1_2_actor_ids_ordered_sha256": hashlib.sha256(
            "\n".join(actor_ids).encode("utf-8")
        ).hexdigest(),
        "tier_1_2_actor_ids_multiset_sha256": _actor_multiset_sha256(actor_ids),
        "claim_projection_count": len(claim_hashes),
        "claim_projection_multiset_sha256": _actor_multiset_sha256(claim_hashes),
        "required_behavior_ready_families": list(
            _ACTOR_BEHAVIOR_READY_FAMILIES
        ),
        "behavior_ready_family_count": behavior_ready_family_count,
        "behavior_ready_family_slots": (
            len(actor_ids) * len(_ACTOR_BEHAVIOR_READY_FAMILIES)
        ),
        "behavior_ready_family_failures": [],
        "behavior_family_projection": behavior_family_projection,
        "behavior_family_projection_sha256": hashlib.sha256(
            canonical_family_projection
        ).hexdigest(),
    }, errors


def _actor_question_hash(question: Any) -> str:
    normalized = " ".join(str(question or "").split()).strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _actor_lineage_reception_errors(
    handoff_dir: str,
    *,
    actors: dict[str, Any],
    sources: list[dict[str, Any]],
    report: str,
    dossier: str,
    contract: dict[str, Any],
    dossier_seals: dict[str, Any],
    expected_question: str,
    expected_depth: str,
    expected_run_id: str,
    expected_attempt_ids: set[str],
) -> list[str]:
    """Validate manifest, metadata, dossier, and actor-artifact lineage seals."""
    root = os.path.realpath(str(handoff_dir or ""))
    if not root or not os.path.isdir(root):
        return ["actor_reception_handoff_missing"]
    errors: list[str] = []
    manifest = _read_json(_research_contract_path(root))
    manifest_files = manifest.get("files") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest_files, dict)
        or ACTOR_INTELLIGENCE_LINEAGE_FILENAME not in manifest_files
    ):
        errors.append("actor_lineage_not_manifested")
    elif not _validate_research_contract(root):
        errors.append("research_contract_invalid_at_actor_reception")

    disk_actors = _read_json(os.path.join(root, "actors.json"))
    disk_sources = _read_json(os.path.join(root, "sources.json"))
    disk_report = _read_text(os.path.join(root, "research_report.md"))
    disk_dossier = _read_text(os.path.join(root, "actor_dossier.md"))
    if disk_actors != actors:
        errors.append("actors_memory_disk_mismatch")
    if disk_sources != sources:
        errors.append("sources_memory_disk_mismatch")
    if disk_report != report:
        errors.append("report_memory_disk_mismatch")
    if disk_dossier != dossier:
        errors.append("dossier_memory_disk_mismatch")

    lineage_path = os.path.join(root, ACTOR_INTELLIGENCE_LINEAGE_FILENAME)
    lineage = _read_json(lineage_path)
    if not isinstance(lineage, dict):
        return [*errors, "actor_lineage_missing_or_invalid"]
    if lineage.get("schema_version") != ACTOR_INTELLIGENCE_LINEAGE_SCHEMA_VERSION:
        errors.append("actor_lineage_schema_mismatch")
    if lineage.get("lineage_id") != _actor_lineage_id(lineage):
        errors.append("actor_lineage_id_mismatch")
    if expected_question and lineage.get("question_hash") != _actor_question_hash(
        expected_question
    ):
        errors.append("actor_lineage_question_mismatch")
    if expected_depth and str(lineage.get("depth") or "") != str(
        expected_depth
    ).strip():
        errors.append("actor_lineage_depth_mismatch")
    if expected_run_id and str(lineage.get("run_id") or "") != expected_run_id:
        errors.append("actor_lineage_run_mismatch")
    attempt_id = str(lineage.get("attempt_id") or "").strip()
    if not attempt_id:
        errors.append("actor_lineage_attempt_missing")
    elif expected_run_id and not expected_attempt_ids:
        errors.append("actor_lineage_attempt_authority_missing")
    elif expected_attempt_ids and attempt_id not in expected_attempt_ids:
        errors.append("actor_lineage_attempt_mismatch")
    lane_id = str(lineage.get("lane_id") or "").strip()
    if lane_id not in {
        "outer-track-1", "global-synthesis", "global-synthesis-recovery"
    }:
        errors.append("actor_lineage_lane_invalid")
    lineage_thread_id = str(lineage.get("thread_id") or "").strip()
    meta = _read_json(os.path.join(root, "meta.json"))
    meta_thread_id = (
        str(meta.get("thread_id") or "").strip()
        if isinstance(meta, dict) else ""
    )
    if not lineage_thread_id:
        errors.append("actor_lineage_thread_missing")
    elif not meta_thread_id or lineage_thread_id != meta_thread_id:
        errors.append("actor_lineage_thread_mismatch")

    lineage_checkpoint_id = str(
        lineage.get("checkpoint_id") or ""
    ).strip()
    if lineage_checkpoint_id:
        checkpoint = _read_json(os.path.join(
            root, "research_checkpoint.json"
        ))
        if not isinstance(checkpoint, dict):
            errors.append("actor_lineage_checkpoint_missing")
        else:
            if (
                checkpoint.get("checkpoint_id") != lineage_checkpoint_id
                or lineage_checkpoint_id
                != _research_checkpoint_identity(checkpoint)
            ):
                errors.append("actor_lineage_checkpoint_identity_mismatch")
            checkpoint_bindings = {
                "question_hash": lineage.get("question_hash"),
                "depth": lineage.get("depth"),
                "run_id": lineage.get("run_id"),
                "attempt_id": lineage.get("attempt_id"),
                "lane_id": lineage.get("lane_id"),
                "thread_id": lineage_thread_id,
            }
            for key, expected in checkpoint_bindings.items():
                if checkpoint.get(key) != expected:
                    errors.append(
                        f"actor_lineage_checkpoint_mismatch:{key}"
                    )

    artifact_paths = {
        "report_sha256": os.path.join(root, "research_report.md"),
        "dossier_sha256": os.path.join(root, "actor_dossier.md"),
        "sources_file_sha256": os.path.join(root, "sources.json"),
        "actors_file_sha256": os.path.join(root, "actors.json"),
    }
    for key, path in artifact_paths.items():
        actual = _sha256_file(path)
        if not actual or lineage.get(key) != actual:
            errors.append(f"actor_lineage_artifact_mismatch:{key}")
    for key in (
        "actor_ids_ordered_sha256", "actor_ids_multiset_sha256",
        "claim_projection_multiset_sha256",
    ):
        if lineage.get(key) != contract.get(key):
            errors.append(f"actor_lineage_contract_mismatch:{key}")

    coverage = _read_json(os.path.join(root, "actor_dossier_coverage.json"))
    if not isinstance(coverage, dict) or coverage.get("accountable") is not True:
        errors.append("actor_dossier_coverage_missing_or_unaccountable")
    else:
        provenance_seals, provenance_errors = (
            _actor_track_b_provenance_reception_seals(sources, coverage)
        )
        errors.extend(provenance_errors)
        expected_coverage_values = {
            "schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
            "source_binding_required": True,
            "required_receipt_purpose": "track-b",
            **dossier_seals,
            **provenance_seals,
        }
        for key, expected in expected_coverage_values.items():
            if coverage.get(key) != expected:
                errors.append(f"actor_dossier_coverage_mismatch:{key}")

    actor_meta = meta.get("actor_intelligence") if isinstance(meta, dict) else None
    if not isinstance(actor_meta, dict):
        errors.append("actor_intelligence_meta_missing")
    else:
        for key in (
            "schema_version", "actor_count", "tier_1_2_actor_count", "coverage",
            "report_sha256", "dossier_sha256", "sources_sha256",
            "actor_ids_sha256", "actor_ids_ordered_sha256",
            "actor_ids_multiset_sha256", "tier_1_2_actor_roster_sha256",
            "claim_projection_count", "claim_projection_multiset_sha256",
            "relationship_count", "relationships_sha256",
            "relationship_omission_count", "source_provenance",
        ):
            if actor_meta.get(key) != contract.get(key):
                errors.append(f"actor_intelligence_meta_mismatch:{key}")
        if actor_meta.get("lineage_id") != lineage.get("lineage_id"):
            errors.append("actor_intelligence_meta_lineage_id_mismatch")
        if actor_meta.get("lineage_file") != ACTOR_INTELLIGENCE_LINEAGE_FILENAME:
            errors.append("actor_intelligence_meta_lineage_file_mismatch")
        if isinstance(coverage, dict) and actor_meta.get("dossier_coverage") != coverage:
            errors.append("actor_intelligence_meta_dossier_coverage_mismatch")
    return errors


def _actor_intelligence_reception_errors(
    actors: Any,
    *,
    report: Any,
    dossier: Any,
    sources: Any,
    handoff_dir: str = "",
    expected_question: str = "",
    expected_depth: str = "",
    expected_run_id: str = "",
    expected_attempt_ids: Optional[set[str]] = None,
) -> list[str]:
    """Validate the exact actor-intelligence/v1 object received from Stage 1.

    This is the parent-side activation gate.  It independently recomputes every
    non-circular producer binding available at the handoff boundary and rejects
    the legacy ``{"claims": ...}`` dimension wrapper.  The outer research
    manifest still owns the complete ``actors.json`` byte fingerprint.
    """
    errors: list[str] = []
    if not isinstance(actors, dict):
        return ["actors_not_object"]
    raw_rows = actors.get("actors")
    if not isinstance(raw_rows, list):
        return ["actor_rows_not_list"]
    if not raw_rows:
        errors.append("actor_rows_empty")
    if any(not isinstance(row, dict) for row in raw_rows):
        errors.append("actor_row_not_object")
    rows = [row for row in raw_rows if isinstance(row, dict)]

    contract = actors.get("actor_intelligence_contract")
    if not isinstance(contract, dict):
        errors.append("top_contract_missing")
        return errors
    if contract.get("schema_version") != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
        errors.append("top_contract_schema_mismatch")

    expected_dimensions = list(ACTOR_INTELLIGENCE_DIMENSIONS)
    if contract.get("dimensions") != expected_dimensions:
        errors.append("top_contract_dimensions_mismatch")

    if sources is None:
        source_rows: list[dict[str, Any]] = []
    elif isinstance(sources, list):
        source_rows = [row for row in sources if isinstance(row, dict)]
        if len(source_rows) != len(sources):
            errors.append("source_row_not_object")
    else:
        source_rows = []
        errors.append("sources_not_list")
    canonical_sources = json.dumps(
        sorted(source_rows, key=lambda row: str(row.get("source_id") or "")),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    lookup, source_records, source_errors = _actor_source_lookup(source_rows)
    errors.extend(source_errors)

    actor_ids: list[str] = []
    actor_by_id: dict[str, dict[str, Any]] = {}
    namespace_owners: dict[str, set[str]] = {}
    covered_slots = 0
    grounded_slots = 0
    explicit_gaps = 0
    tier_1_2_count = 0
    tier_1_2_roster: list[str] = []
    claim_projection_hashes: list[str] = []
    for index, actor in enumerate(rows):
        actor_id = str(actor.get("actor_id") or "").strip()
        actor_name = _actor_roster_name(actor)
        if not actor_name:
            errors.append(f"actor_name_missing:{actor_id or index}")
        if not actor_id:
            errors.append(f"actor_id_missing:{index}")
        elif actor_id in actor_ids:
            errors.append(f"actor_id_duplicate:{actor_id}")
        else:
            actor_ids.append(actor_id)
        expected_actor_id = _actor_stable_id(actor.get("name"))
        if actor_id and actor_id != expected_actor_id:
            errors.append(f"actor_id_not_semantic:{actor_id}")
        tier = _actor_explicit_simulation_tier(actor)
        if (
            tier not in (1, 2)
            or isinstance(actor.get("simulation_tier"), bool)
            or not isinstance(actor.get("simulation_tier"), int)
        ):
            errors.append(f"simulation_tier_not_exact_enum:{actor_id or index}")
        else:
            tier_1_2_count += 1
            tier_1_2_roster.append(actor_name)
        if actor_id:
            actor_by_id[actor_id] = actor
        aliases = actor.get("aliases")
        if aliases is not None and not isinstance(aliases, list):
            errors.append(f"actor_aliases_not_list:{actor_id or index}")
            aliases = []
        for identity in [actor.get("name"), *(aliases or [])]:
            normalized_identity = _actor_roster_name({"name": identity})
            if normalized_identity:
                namespace_owners.setdefault(
                    normalized_identity, set()
                ).add(actor_id or str(index))

        intelligence = actor.get("intelligence")
        if not isinstance(intelligence, dict):
            errors.append(f"actor_intelligence_missing:{actor_id or index}")
            continue
        if intelligence.get("schema_version") != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
            errors.append(f"actor_intelligence_schema_mismatch:{actor_id or index}")
        dimensions = intelligence.get("dimensions")
        if not isinstance(dimensions, dict):
            errors.append(f"dimensions_not_object:{actor_id or index}")
            continue
        if list(dimensions) != expected_dimensions:
            errors.append(f"dimension_keys_or_order_mismatch:{actor_id or index}")
        gaps = intelligence.get("evidence_gaps")
        if not isinstance(gaps, dict):
            errors.append(f"evidence_gaps_not_object:{actor_id or index}")
            gaps = {}
        omission_audit = intelligence.get("omission_audit")
        if not isinstance(omission_audit, list):
            errors.append(f"omission_audit_not_list:{actor_id or index}")
        actor_covered: list[str] = []
        actor_grounded: list[str] = []
        actor_gap_count = 0
        for dimension in ACTOR_INTELLIGENCE_DIMENSIONS:
            claims = dimensions.get(dimension)
            if not isinstance(claims, list):
                errors.append(
                    f"dimension_not_canonical_list:{actor_id or index}:{dimension}"
                )
                claims = []
            elif any(not isinstance(claim, dict) for claim in claims):
                errors.append(
                    f"dimension_claim_not_object:{actor_id or index}:{dimension}"
                )
            for claim in claims:
                if not isinstance(claim, dict):
                    continue
                normalized_claim = _actor_normalize_claim(
                    claim,
                    actor_id=actor_id,
                    dimension=dimension,
                    lookup=lookup,
                    records=source_records,
                )
                if not normalized_claim or not normalized_claim.get(
                    "source_support"
                ):
                    errors.append(
                        "dimension_claim_not_quote_receipt_bound:"
                        f"{actor_id or index}:{dimension}"
                    )
                    continue
                if claim != normalized_claim:
                    errors.append(
                        f"dimension_claim_canonical_mismatch:"
                        f"{actor_id or index}:{dimension}"
                    )
                    continue
                claim_projection_hashes.append(
                    normalized_claim["claim_sha256"]
                )
            if claims:
                covered_slots += 1
                actor_covered.append(dimension)
            if any(
                isinstance(claim, dict) and bool(claim.get("source_support"))
                for claim in claims
            ):
                grounded_slots += 1
                actor_grounded.append(dimension)
            dimension_gaps = gaps.get(dimension)
            if not isinstance(dimension_gaps, list):
                errors.append(
                    f"dimension_gap_not_list:{actor_id or index}:{dimension}"
                )
            else:
                explicit_gaps += len(dimension_gaps)
                actor_gap_count += len(dimension_gaps)
        expected_actor_coverage = {
            "covered_dimensions": actor_covered,
            "grounded_dimensions": actor_grounded,
            "dimension_coverage_ratio": round(
                len(actor_covered) / len(ACTOR_INTELLIGENCE_DIMENSIONS), 4
            ),
            "grounded_coverage_ratio": round(
                len(actor_grounded) / len(ACTOR_INTELLIGENCE_DIMENSIONS), 4
            ),
            "explicit_gap_count": actor_gap_count,
        }
        if intelligence.get("coverage") != expected_actor_coverage:
            errors.append(f"actor_coverage_binding_mismatch:{actor_id or index}")

    for identity, owners in namespace_owners.items():
        if len(owners) > 1:
            errors.append(f"actor_identity_namespace_overlap:{identity}")

    actor_count = len(rows)
    if contract.get("actor_count") != actor_count:
        errors.append(
            f"actor_count_mismatch:contract={contract.get('actor_count')},actual={actor_count}"
        )
    if contract.get("tier_1_2_actor_count") != tier_1_2_count:
        errors.append("tier_1_2_actor_count_mismatch")
    if tier_1_2_count == 0:
        errors.append("tier_1_2_actor_count_zero")
    actual_actor_ids_ordered_sha = hashlib.sha256(
        "\n".join(actor_ids).encode("utf-8")
    ).hexdigest()
    actual_actor_ids_multiset_sha = _actor_multiset_sha256(actor_ids)
    if contract.get("actor_ids_sha256") != actual_actor_ids_multiset_sha:
        errors.append("actor_ids_sha256_mismatch")
    if contract.get("actor_ids_ordered_sha256") != actual_actor_ids_ordered_sha:
        errors.append("actor_ids_ordered_sha256_mismatch")
    if contract.get("actor_ids_multiset_sha256") != actual_actor_ids_multiset_sha:
        errors.append("actor_ids_multiset_sha256_mismatch")
    actual_tier_roster_sha = hashlib.sha256(
        "\n".join(sorted(tier_1_2_roster)).encode("utf-8")
    ).hexdigest()
    if contract.get("tier_1_2_actor_roster_sha256") != actual_tier_roster_sha:
        errors.append("tier_1_2_actor_roster_sha256_mismatch")

    report_text = report if isinstance(report, str) else ""
    dossier_text = dossier if isinstance(dossier, str) else ""
    if not report_text.strip():
        errors.append("report_empty")
    if contract.get("report_sha256") != hashlib.sha256(
        report_text.encode("utf-8")
    ).hexdigest():
        errors.append("report_sha256_mismatch")
    if contract.get("dossier_sha256") != hashlib.sha256(
        dossier_text.encode("utf-8")
    ).hexdigest():
        errors.append("dossier_sha256_mismatch")

    if contract.get("source_count") != len(source_rows):
        errors.append("source_count_mismatch")
    if contract.get("sources_sha256") != hashlib.sha256(
        canonical_sources
    ).hexdigest():
        errors.append("sources_sha256_mismatch")
    provenance_rows = [{
        "source_id": str(source.get("source_id") or ""),
        "content_sha256": str(source.get("content_sha256") or ""),
        "receipt_id": str(source.get("receipt_id") or ""),
        "provider": str(source.get("provider") or ""),
        "cache_hits": source.get("cache_hits", 0),
        "receipt_scopes": _actor_receipt_scopes(source),
    } for source in sorted(
        (row for row in source_rows if _actor_source_is_fetched(row)),
        key=lambda row: str(row.get("source_id") or ""),
    )]
    canonical_provenance = json.dumps(
        provenance_rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    cache_hit_total = 0
    for row in provenance_rows:
        try:
            cache_hit_total += max(0, int(row.get("cache_hits") or 0))
        except (TypeError, ValueError):
            continue
    expected_source_provenance = {
        "fetched_source_count": len(provenance_rows),
        "content_hash_count": sum(
            bool(row["content_sha256"]) for row in provenance_rows
        ),
        "receipt_count": sum(bool(row["receipt_id"]) for row in provenance_rows),
        "providers": sorted({
            row["provider"] for row in provenance_rows if row["provider"]
        }),
        "cache_hit_total": cache_hit_total,
        "sha256": hashlib.sha256(canonical_provenance).hexdigest(),
    }
    if contract.get("source_provenance") != expected_source_provenance:
        errors.append("source_provenance_binding_mismatch")

    if contract.get("claim_projection_count") != len(claim_projection_hashes):
        errors.append("claim_projection_count_mismatch")
    actual_claim_multiset_sha = _actor_multiset_sha256(
        claim_projection_hashes
    )
    if (
        contract.get("claim_projection_multiset_sha256")
        != actual_claim_multiset_sha
    ):
        errors.append("claim_projection_multiset_sha256_mismatch")

    raw_relationships = actors.get("relationships")
    if not isinstance(raw_relationships, list):
        errors.append("relationships_not_list")
        relationships: list[dict[str, Any]] = []
    else:
        relationships = [
            row for row in raw_relationships if isinstance(row, dict)
        ]
        if len(relationships) != len(raw_relationships):
            errors.append("relationship_not_object")
    relationship_id_indexes: dict[str, int] = {}
    for relation_index, relation in enumerate(relationships):
        source_actor_id = str(relation.get("source_actor_id") or "")
        target_actor_id = str(relation.get("target_actor_id") or "")
        source_actor = actor_by_id.get(source_actor_id)
        target_actor = actor_by_id.get(target_actor_id)
        if source_actor is None or target_actor is None:
            errors.append(f"relationship_endpoint_unbound:{relation_index}")
            continue
        if (
            relation.get("source_actor_id") != source_actor_id
            or relation.get("target_actor_id") != target_actor_id
            or relation.get("source") != str(source_actor.get("name") or "")
            or relation.get("target") != str(target_actor.get("name") or "")
        ):
            errors.append(f"relationship_endpoint_name_mismatch:{relation_index}")
        received_type = relation.get("type")
        canonical_type = str(received_type or "OTHER").strip().upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,63}", canonical_type):
            canonical_type = "OTHER"
        received_label = relation.get("relation_label")
        canonical_label = str(received_label or "").strip()
        if received_type != canonical_type:
            errors.append(f"relationship_type_noncanonical:{relation_index}")
        if received_label != canonical_label:
            errors.append(f"relationship_label_noncanonical:{relation_index}")
        claim_value = dict(relation)
        claim_value["claim"] = str(relation.get("basis") or "")
        claim_value.pop("type", None)
        claim_value.pop("basis", None)
        try:
            causal_attributes = _actor_relationship_causal_attributes(relation)
        except ValueError as exc:
            errors.append(
                f"relationship_causal_attributes_invalid:{relation_index}:{exc}"
            )
            continue
        for key in _ACTOR_RELATIONSHIP_CAUSAL_ATTRIBUTE_KEYS:
            claim_value.pop(key, None)
        expected_claim = _actor_normalize_claim(
            claim_value,
            actor_id=source_actor_id,
            dimension="relationship",
            lookup=lookup,
            records=source_records,
            causal_attributes=causal_attributes,
        )
        if not expected_claim or not expected_claim.get("source_support"):
            errors.append(
                f"relationship_not_quote_receipt_bound:{relation_index}"
            )
            continue
        for key in (
            "claim", "evidence_type", "claim_valid_at", "as_of_date",
            "horizon", "status", "confidence", "source_refs", "source_support",
            "qualifiers", "claim_id", "claim_sha256",
        ):
            expected = expected_claim[key]
            received = relation.get("basis") if key == "claim" else relation.get(key)
            if received != expected:
                errors.append(
                    f"relationship_claim_canonical_mismatch:{relation_index}:{key}"
                )
                break
        identity_payload = {
            "source_actor_id": source_actor_id,
            "target_actor_id": target_actor_id,
            "type": canonical_type,
            "relation_label": canonical_label,
            "claim_sha256": expected_claim["claim_sha256"],
            "causal_attributes": causal_attributes,
        }
        expected_relationship_id = "relation_" + hashlib.sha256(json.dumps(
            identity_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()[:20]
        received_relationship_id = relation.get("relationship_id")
        if received_relationship_id != expected_relationship_id:
            errors.append(f"relationship_id_mismatch:{relation_index}")
        if isinstance(received_relationship_id, str):
            prior_index = relationship_id_indexes.get(received_relationship_id)
            if prior_index is not None:
                errors.append(
                    "relationship_id_duplicate:"
                    f"{prior_index}:{relation_index}:{received_relationship_id}"
                )
            else:
                relationship_id_indexes[received_relationship_id] = relation_index
    relationship_bytes = json.dumps(
        relationships,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if contract.get("relationship_count") != len(relationships):
        errors.append("relationship_count_mismatch")
    if contract.get("relationships_sha256") != hashlib.sha256(
        relationship_bytes
    ).hexdigest():
        errors.append("relationships_sha256_mismatch")
    relationship_omissions = actors.get("relationship_omission_audit")
    if not isinstance(relationship_omissions, list):
        errors.append("relationship_omission_audit_not_list")
        relationship_omissions = []
    if contract.get("relationship_omission_count") != len(
        relationship_omissions
    ):
        errors.append("relationship_omission_count_mismatch")

    dossier_seals, dossier_errors = _actor_dossier_reception_seals(
        dossier_text,
        lookup=lookup,
        records=source_records,
    )
    errors.extend(dossier_errors)
    dossier_contract_bindings = {
        "tier_1_2_actor_count": contract.get("tier_1_2_actor_count"),
        "tier_1_2_actor_roster_sha256": contract.get(
            "tier_1_2_actor_roster_sha256"
        ),
        "tier_1_2_actor_ids_ordered_sha256": contract.get(
            "actor_ids_ordered_sha256"
        ),
        "tier_1_2_actor_ids_multiset_sha256": contract.get(
            "actor_ids_multiset_sha256"
        ),
        "claim_projection_count": contract.get("claim_projection_count"),
        "claim_projection_multiset_sha256": contract.get(
            "claim_projection_multiset_sha256"
        ),
    }
    for key, expected in dossier_contract_bindings.items():
        if dossier_seals.get(key) != expected:
            errors.append(f"dossier_contract_seal_mismatch:{key}")

    dimension_slots = actor_count * len(ACTOR_INTELLIGENCE_DIMENSIONS)
    expected_coverage = {
        "dimension_slots": dimension_slots,
        "covered_dimension_slots": covered_slots,
        "grounded_dimension_slots": grounded_slots,
        "coverage_ratio": round(
            covered_slots / dimension_slots, 4
        ) if dimension_slots else 0.0,
        "grounded_coverage_ratio": round(
            grounded_slots / dimension_slots, 4
        ) if dimension_slots else 0.0,
        "explicit_gap_count": explicit_gaps,
    }
    if contract.get("coverage") != expected_coverage:
        errors.append("coverage_binding_mismatch")
    if not str(contract.get("generated_at") or "").strip():
        errors.append("generated_at_missing")
    errors.extend(_actor_lineage_reception_errors(
        handoff_dir,
        actors=actors,
        sources=source_rows,
        report=report_text,
        dossier=dossier_text,
        contract=contract,
        dossier_seals=dossier_seals,
        expected_question=expected_question,
        expected_depth=expected_depth,
        expected_run_id=expected_run_id,
        expected_attempt_ids=set(expected_attempt_ids or set()),
    ))
    return errors


def _enforce_actor_intelligence_reception(
    state: PipelineState,
    actors: Any,
    *,
    report: Any,
    dossier: Any,
    sources: Any,
    handoff_dir: str = "",
) -> None:
    """Apply the run-pinned parent reception policy before ONTOLOGY/GRAPH."""
    policy = (state.options or {}).get("actor_intelligence_policy_v1")
    if policy is None:
        # Pre-policy runs did not request this versioned interface.  Retain the
        # historical no-actor/legacy path rather than retroactively changing a
        # persisted run's contract from ambient configuration.
        state.options["actor_intelligence_reception"] = {
            "required": False,
            "passed": True,
            "reason": "legacy_run_without_pinned_policy",
        }
        return
    if (
        not isinstance(policy, dict)
        or policy.get("version") != ACTOR_INTELLIGENCE_POLICY_VERSION
        or policy.get("schema_version") != ACTOR_INTELLIGENCE_SCHEMA_VERSION
        or not isinstance(policy.get("required"), bool)
    ):
        raise RuntimeError("actor-intelligence/v1 reception policy is malformed")
    if policy["required"] is False:
        state.options["actor_intelligence_reception"] = {
            "required": False,
            "passed": True,
            # A pinned engine limitation is disclosed verbatim; otherwise the
            # actor track was switched off by configuration at admission.
            "reason": (
                str(policy.get("not_required_reason") or "")
                or "actor_track_explicitly_disabled_at_admission"
            ),
        }
        return

    expected_attempt_ids = _research_budget_attempt_ids(state)
    errors = _actor_intelligence_reception_errors(
        actors,
        report=report,
        dossier=dossier,
        sources=sources,
        handoff_dir=handoff_dir,
        expected_question=state.prompt,
        expected_depth=str(
            state.options.get("depth")
            or getattr(Config, "DEERFLOW_RESEARCH_DEPTH", "standard")
        ),
        expected_run_id=state.pipeline_id,
        expected_attempt_ids=expected_attempt_ids,
    )
    state.options["actor_intelligence_reception"] = {
        "required": True,
        "passed": not errors,
        "schema_version": ACTOR_INTELLIGENCE_SCHEMA_VERSION,
        "actor_count": (
            len(actors.get("actors") or []) if isinstance(actors, dict) else 0
        ),
        "errors": errors,
    }
    if errors:
        raise RuntimeError(
            "actor-intelligence/v1 reception failed before ontology/graph: "
            + "; ".join(errors[:12])
        )


def _forecast_inputs_missing(actors: Any) -> bool:
    """actors 是否缺少可用的 ``forecast_inputs.scenarios``（据此决定是否从报告兜底解析）。

    仅当 actors 为 dict，且 forecast_inputs.scenarios 构成有名字、有可解析概率、总和约为
    1 的分区时返回 False（已具备种子，无需兜底）；名字壳/缺概率/坏总和均返回 True。
    actors 非 dict → False（无处可注入）。
    """
    if not isinstance(actors, dict):
        return False
    return not valid_scenario_distribution(actors.get("forecast_inputs"))


def inject_forecast_inputs_from_report(
    actors: Any, report_md: Optional[str]
) -> Optional[dict[str, Any]]:
    """actors 缺 forecast_inputs.scenarios 时，从 research_report.md 情景节确定性解析并**就地
    注入** actors['forecast_inputs']（纯离线、无 LLM）。

    返回注入用的 forecast_inputs（含非空 scenarios）——命中；否则 None：actors 已有种子、
    是不可变的 actor-intelligence/v1、非 dict、报告未解析出概率分布，或解析异常。
    degrade-safe——调用方保持 legacy 行为。命中后 pre-v1 actors 被原地修改，故同一次运行
    的下游与随后密封的外层 research generation 都能看到它。
    """
    # The versioned producer contract is immutable after sealing.  Scenario
    # extraction belongs upstream of that boundary; mutating even an unrelated
    # top-level key here would make the in-memory actor object differ from the
    # exact ``actors.json`` generation consumed by actor-context provenance.
    if _is_sealed_actor_intelligence_v1(actors):
        return None
    if not _forecast_inputs_missing(actors):
        return None
    try:
        from ..utils.actors import forecast_inputs_from_report_markdown
        parsed = forecast_inputs_from_report_markdown(report_md or "")
    except Exception:  # noqa: BLE001 — 解析纯增强，任何异常都退化为「无种子」
        return None
    if not isinstance(parsed, dict):
        return None
    scenarios = parsed.get("scenarios")
    if not (isinstance(scenarios, list) and scenarios):
        return None
    actors["forecast_inputs"] = parsed
    return parsed


# ===========================================================================
# PAR-2: 多角度并行研究轨 —— 角度特化前缀 + 确定性合并（纯函数，可单测）
# ---------------------------------------------------------------------------
# 研究阶段并行跑 K 条角度特化的研究轨（每条一个 DeerFlowResearchRunner 子进程，写入
# handoff/track_<k>/），随后把各轨产物确定性地合并回 handoff/，下游各阶段读合并后的
# handoff/ 与今日完全一致。轨 1 = 基线证据扫描（原始 brief 逐字，无前缀）；轨 2/3 = 附加
# 角度前缀。合并规则见各 merge_* 函数 docstring。
# ===========================================================================

# 角度定义：(short_key, H1 标题, prompt 前缀)。轨 1 前缀为空 → track_prompt == 原始 prompt
# 逐字节（RESEARCH_PARALLEL_TRACKS=1 时整条路径与今日一致）。上限即本列表长度。
_TRACK2_PREFIX = (
    "【研究视角：基率、参照类与历史类比】在回答下述预测问题时，请以「参照类预测"
    "（reference-class forecasting）」为主线：系统识别与本问题结构相似的历史先例与可比"
    "事件，估计相关基率（base rates）、历史发生频率与典型时间尺度，用它们为每个可能结局"
    "建立外部视角（outside view）的锚。优先搜集可量化的历史类比、长周期统计与既往类似情形"
    "的实际结局分布，而非仅当下叙事。\n\n原始预测问题：\n"
)
_TRACK3_PREFIX = (
    "【研究视角：行为者激励、反面论证与市场定价】在回答下述预测问题时，请聚焦三条线："
    "(1) 关键行为者的激励结构与约束——谁想要什么、面临何种约束、其理性策略如何影响结局；"
    "(2) 反面/证伪论证——主动搜寻能推翻主流叙事的反向证据、被忽视的风险与非共识情景"
    "（contrarian case）；(3) 市场定价信号——预测市场、期货、赔率、隐含概率等对相关结局的"
    "定价。优先搜集能挑战共识的一手证据与可交易的定价信号。\n\n原始预测问题：\n"
)

# (short_key, H1 标题, prefix)。合并后的 research_report.md 用 H1 标题作章节头。
_RESEARCH_TRACK_ANGLES: list[tuple[str, str, str]] = [
    ("base-evidence", "基线证据扫描 (Base Evidence Sweep)", ""),
    ("base-rates", "基率·参照类·历史类比 (Base Rates & Reference Classes)", _TRACK2_PREFIX),
    ("incentives-contrarian",
     "行为者激励·反面论证·市场定价 (Incentives, Contrarian Case & Market Pricing)",
     _TRACK3_PREFIX),
]


def research_subagent_cap_per_track(n_tracks: int, global_cap: int,
                                    per_track_max: int = 5) -> int:
    """Allocate one fixed harness-concurrency envelope across outer tracks."""
    try:
        tracks = max(1, int(n_tracks))
        total = max(1, int(global_cap))
        lane_max = max(1, min(8, int(per_track_max)))
    except (TypeError, ValueError):
        return 1
    return max(1, min(lane_max, total // tracks))


def research_outer_track_workers(
        n_tracks: int, global_cap: int, model_cap: int = 0) -> int:
    """Bound simultaneously active outer tracks by the shared subagent cap."""
    try:
        tracks = max(1, int(n_tracks))
        total = max(1, int(global_cap))
        models = max(0, int(model_cap))
    except (TypeError, ValueError):
        return 1
    return max(1, min(tracks, total, models if models > 0 else tracks))


def research_model_concurrency_cap(
        outer_workers: int, global_subagent_cap: int, configured: int = 0) -> int:
    """Return one provider-facing envelope for leads plus harness workers."""
    try:
        explicit = int(configured)
        workers = max(1, int(outer_workers))
        subagents = max(1, int(global_subagent_cap))
    except (TypeError, ValueError):
        return 2
    return explicit if explicit > 0 else workers + subagents


def research_lane_subagent_cap(
        outer_workers: int, global_subagent_cap: int, per_track_max: int,
        model_concurrency: int) -> int:
    """Return 0 when the all-model envelope cannot fit lead + subagent."""
    try:
        workers = max(1, int(outer_workers))
        models = max(1, int(model_concurrency))
    except (TypeError, ValueError):
        return 0
    model_room = max(0, models // workers - 1)
    if model_room <= 0:
        return 0
    return min(
        model_room,
        research_subagent_cap_per_track(
            workers, global_subagent_cap, per_track_max),
    )


def research_dual_track_for_outer_lane(
        lane_index: int, enabled: bool) -> bool:
    """Assign the shared actor/ontology dossier to the broad baseline lane."""
    try:
        return bool(enabled) and int(lane_index) == 0
    except (TypeError, ValueError):
        return False


# ---------------------------------------------------------------------------
# Deep-research engine selection (engine v3)
# ---------------------------------------------------------------------------
RESEARCH_ENGINE_V3 = "v3"
RESEARCH_ENGINE_LEGACY = "legacy"
# Accepted spellings → canonical child contract; the SAME alias sets as the
# bridge's own resolver (deerflow_research._V3_ENGINE_NAMES / _LEGACY_ENGINE_NAMES)
# so one operator value can never mean different engines in parent and child.
# ``linear`` is the historical name of the engine v3 rewrote in place (same
# deployed linear_research.py), so ``.env`` files pinning it keep selecting v3.
_RESEARCH_ENGINE_ALIASES: dict[str, str] = {
    "v3": RESEARCH_ENGINE_V3,
    "linear": RESEARCH_ENGINE_V3,
    "legacy": RESEARCH_ENGINE_LEGACY,
    "deerflow": RESEARCH_ENGINE_LEGACY,
    "agentic": RESEARCH_ENGINE_LEGACY,
}
_UNKNOWN_RESEARCH_ENGINES_WARNED: set[str] = set()
_UNKNOWN_RESEARCH_ENGINES_LOCK = threading.Lock()


def resolve_research_engine(raw: Any = None) -> str:
    """Normalize a RESEARCH_ENGINE value to ``"v3"`` or ``"legacy"``.

    The parent is the single authority for which engine a research subprocess
    runs: the runner passes this value to the child explicitly (never relying on
    ambient env inheritance) and the research stage uses the same value to pick
    the outer-lane topology, so the two can never disagree.  ``raw=None`` reads
    ``Config.RESEARCH_ENGINE``; an empty value means "unset" → the v3 default.

    An unknown value must neither fail a run at launch nor silently select the
    legacy engine (a typo would otherwise flip the whole research topology), so
    it falls back to v3 with one warning per distinct value per process.
    """
    value = getattr(Config, "RESEARCH_ENGINE", RESEARCH_ENGINE_V3) if raw is None else raw
    text = str(value or "").strip().lower()
    if not text:
        return RESEARCH_ENGINE_V3
    engine = _RESEARCH_ENGINE_ALIASES.get(text)
    if engine is not None:
        return engine
    with _UNKNOWN_RESEARCH_ENGINES_LOCK:
        first_sighting = text not in _UNKNOWN_RESEARCH_ENGINES_WARNED
        _UNKNOWN_RESEARCH_ENGINES_WARNED.add(text)
    if first_sighting:
        logger.warning(
            "RESEARCH_ENGINE=%r 未知（可选 v3 | linear | legacy | deerflow | agentic）——按默认 v3 引擎运行",
            text[:64],
        )
    return RESEARCH_ENGINE_V3


def research_engine_for_run(options: Any) -> str:
    """The research engine a pipeline runs: ``Config.RESEARCH_ENGINE`` unless
    its pinned actor-intelligence policy requires the sealed actor plane.

    Only the legacy engine produces that plane, and a policy requiring it was
    pinned by a legacy admission — including every pipeline admitted before
    the v3 engine existed (``DEERFLOW_DUAL_TRACK`` defaults to true).
    Resuming such a run under a later v3 default would fail reception only
    after the whole research spend, so the pinned contract selects the engine
    that can honour it.  Runs without a pinned policy, or whose policy does
    not require the plane, follow the configured engine.
    """
    policy = options.get("actor_intelligence_policy_v1") if isinstance(options, dict) else None
    if isinstance(policy, dict) and policy.get("required") is True:
        return RESEARCH_ENGINE_LEGACY
    return resolve_research_engine()


def research_outer_track_count(
        configured_tracks: Any, engine: str, *, pipeline_id: str = "") -> int:
    """Return how many outer research lanes the research stage launches.

    Legacy engine: exactly today's rule (``RESEARCH_PARALLEL_TRACKS``, ≥1, an
    unparsable value → 3).  v3: always 1.  The v3 engine already fans out
    internally (bounded per-KIQ agents sharing one source ledger, query dedup
    and prompt-cache prefix); outer angle lanes would multiply evidence spend
    for duplicate coverage and depend on the ``--evidence-only`` /
    ``--synthesis-manifest`` lane contracts that only the legacy engine
    implements.  The override is logged once per research stage when it
    actually disables configured lanes.
    """
    try:
        tracks = max(1, int(configured_tracks or 3))
    except (TypeError, ValueError):
        tracks = 3
    if engine != RESEARCH_ENGINE_V3:
        return tracks
    if tracks > 1:
        logger.info(
            "[%s] RESEARCH_ENGINE=v3 在引擎内部执行有界并行扇出（按 KIQ 的并行子代理共享"
            "来源台账/查询去重/提示缓存前缀）——外层研究轨已禁用"
            "（RESEARCH_PARALLEL_TRACKS=%d 按 1 执行）",
            pipeline_id or "-", tracks,
        )
    return 1


def _track_tier_rank(tier: Any) -> int:
    """来源层级 → 排序秩：S1 最高（rank 1）… S4（rank 4），缺失/非法 → 9（最低）。
    合并去重时「保最高层级」= 取 rank 最小者。"""
    if not isinstance(tier, str):
        return 9
    m = re.match(r"[sS]([1-4])", tier.strip())
    return int(m.group(1)) if m else 9


def _track_norm_url(url: Any) -> str:
    """URL 去重规范化：去空白、去尾部 '/'、整体小写。仅用于去重键，不改写落盘的原 url。"""
    if not isinstance(url, str):
        return ""
    return url.strip().rstrip("/").lower()


def merge_track_reports(labeled_reports: list[tuple[str, str]]) -> str:
    """PAR-2（纯）：把各轨报告拼接到 '# Track N: <angle>' 一级标题之下。

    labeled_reports = [(angle_title, report_text), ...]（保持轨顺序）。空文本的轨跳过。
    Track 编号按传入顺序从 1 起（跳过的轨不占号，编号连续）。
    """
    parts: list[str] = []
    n = 0
    for angle, text in labeled_reports:
        body = (text or "").strip()
        if not body:
            continue
        n += 1
        parts.append(f"# Track {n}: {angle}\n\n{body}")
    return "\n\n".join(parts)


# W9-7: 多轨卷宗的一次有界 LLM 整理 —— merge_track_reports 的纯拼接会把 3 份执行摘要、
# 互相矛盾的头条数字原封不动地交付（诊断实测：同一轨内 2030 基线 $1.45-1.55T vs $1.7-1.9T）。
# 这里补一个「合并开篇 + 跨轨分歧表 + H1 降级」的编辑整理；degrade-safe：
# 任何 LLM 失败均回退确定性去重/降级后的卷宗，而不是泄漏 K 份开篇。

_TRACK_H1_RE = re.compile(r"(?m)^# Track (\d+): (.+?)\s*$")
_REPORT_HEADING_RE = re.compile(r"(?m)^(#{1,3})[ \t]+(.+?)[ \t]*$")
_OPENING_CITATION_RE = re.compile(r"\[\s*S(\d+)\s*\]", re.I)


def _normalise_report_heading(title: str) -> str:
    """Return a comparison key for multilingual report-opening headings."""
    value = re.sub(r"[`*_~]", "", str(title or "")).strip().casefold()
    value = re.sub(r"^\s*(?:\d+(?:\.\d+)*|[ivxlcdm]+)[.)、:]?\s+", "", value)
    value = re.sub(r"[\s\-–—_:：/|'’（）()]+", " ", value)
    return value.strip(" .!?！？。")


def _report_opening_kind(title: str) -> Optional[str]:
    """Classify Executive Summary / reader-guide aliases without fuzzy matching.

    These are presentation sections generated independently by every research
    track.  Exact, bounded aliases avoid deleting substantive sections merely
    because their prose happens to contain words such as ``summary`` or
    ``guide``.
    """
    key = _normalise_report_heading(title)
    compact = re.sub(r"\s+", "", key)
    executive_aliases = {
        "executive summary", "executive overview", "management summary",
        "summary", "summary of findings", "research summary",
        "key findings summary", "key takeaways",
        "摘要", "执行摘要", "执行概要", "研究摘要", "核心摘要", "摘要与核心结论",
    }
    orientation_aliases = {
        "how to read this dossier", "how to read this report",
        "how to use this dossier", "how to use this report",
        "reader guide", "reader s guide", "reading guide", "dossier guide",
        "report guide", "orientation", "document orientation",
        "如何阅读本卷宗", "如何阅读本报告", "如何阅读这份报告", "阅读指南",
        "读者指南", "卷宗导读", "报告导读", "报告使用说明", "卷宗使用说明",
    }
    if (key in executive_aliases
            or "executive summary" in key
            or compact in {
            "摘要", "执行摘要", "执行概要", "研究摘要", "核心摘要", "摘要与核心结论"}):
        return "executive"
    if (key in orientation_aliases
            or "how to read this dossier" in key
            or "how to read this report" in key
            or compact in {
            "如何阅读本卷宗", "如何阅读本报告", "如何阅读这份报告", "阅读指南",
            "读者指南", "卷宗导读", "报告导读", "报告使用说明", "卷宗使用说明"}):
        return "orientation"
    return None


def _opening_sections(report_md: str, kind: Optional[str] = None) -> list[dict[str, Any]]:
    """Locate bounded opening sections, stopping at a peer/ancestor heading."""
    text = str(report_md or "")
    headings = list(_REPORT_HEADING_RE.finditer(text))
    found: list[dict[str, Any]] = []
    for index, heading in enumerate(headings):
        section_kind = _report_opening_kind(heading.group(2))
        if section_kind is None or (kind is not None and section_kind != kind):
            continue
        level = len(heading.group(1))
        end = len(text)
        for following in headings[index + 1:]:
            if len(following.group(1)) <= level:
                end = following.start()
                break
        found.append({
            "kind": section_kind,
            "start": heading.start(),
            "end": end,
            "body": text[heading.end():end].strip(),
        })
    return found


def _strip_opening_sections(report_md: str, kinds: set[str]) -> str:
    """Remove every recognized per-track presentation section in ``kinds``."""
    text = str(report_md or "")
    spans = [row for row in _opening_sections(text) if row["kind"] in kinds]
    for row in reversed(spans):
        text = text[:row["start"]] + text[row["end"]:]
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _first_opening_body(tracks: list[tuple[str, str]], kind: str) -> str:
    """Select the first substantive opening, with a non-empty last resort."""
    fallback = ""
    minimum = 80 if kind == "executive" else 20
    for _title, report in tracks:
        for section in _opening_sections(report, kind):
            body = str(section.get("body") or "").strip()
            if body and not fallback:
                fallback = body
            if len(re.sub(r"\s+", "", body)) >= minimum:
                return body
    return fallback


def _deterministic_track_report(tracks: list[tuple[str, str]]) -> tuple[str, str]:
    """Build one canonical opening plus clean, demoted per-track evidence parts.

    The first substantive summary/guide is retained because track order is the
    pipeline's declared priority order (the broad baseline track is first).
    Every duplicate alias is removed from the evidence parts.
    """
    summary = _first_opening_body(tracks, "executive")
    orientation = _first_opening_body(tracks, "orientation")
    opening: list[str] = []
    if summary:
        opening.append(f"## Executive Summary\n\n{summary}")
    if orientation:
        opening.append(f"## How to Read This Dossier\n\n{orientation}")
    compact_body = merge_track_reports([
        (title, _strip_opening_sections(report, {"executive", "orientation"}))
        for title, report in tracks
    ])
    body = demote_track_headings(compact_body)
    pieces = [piece.strip() for piece in (*opening, body) if piece.strip()]
    return "\n\n".join(pieces), "\n\n".join(opening)


def _opening_citation_audit(candidate: str, fallback: str,
                            merged_report: str) -> dict[str, Any]:
    """Reject synthesized openings that lose or invent source markers."""
    candidate_markers = _OPENING_CITATION_RE.findall(candidate or "")
    fallback_markers = _OPENING_CITATION_RE.findall(fallback or "")
    allowed = set(_OPENING_CITATION_RE.findall(merged_report or ""))
    dangling = sorted(set(candidate_markers) - allowed, key=lambda n: int(n))
    return {
        "candidate_markers": len(candidate_markers),
        "candidate_distinct": len(set(candidate_markers)),
        "fallback_markers": len(fallback_markers),
        "fallback_distinct": len(set(fallback_markers)),
        "dangling": dangling,
        "passed": (
            not dangling
            and set(fallback_markers).issubset(set(candidate_markers))
            and len(set(candidate_markers)) >= len(set(fallback_markers))
        ),
    }


def _track_title_en(title: str) -> str:
    """W9-7（纯）：从 '基线证据扫描 (Base Evidence Sweep)' 提取英文标题；无括号英文时原样返回。"""
    m = re.search(r"[（(]([A-Za-z][^)）]*)[)）]\s*$", str(title or ""))
    return (m.group(1).strip() if m else str(title or "").strip())


def demote_track_headings(md: str) -> str:
    """W9-7（纯）：把 '# Track N: <title>' H1 降级为 '## Part N — <english title>' H2。

    合并卷宗只应有一个文档级叙事层级；'# Track N' H1 把 3 份独立报告的骨架原样漏给读者。
    仅改写 merge_track_reports 生成的行（正则锚定行首），正文其余内容逐字节不动。
    """
    def _sub(m: "re.Match[str]") -> str:
        return f"## Part {m.group(1)} — {_track_title_en(m.group(2))}"
    return _TRACK_H1_RE.sub(_sub, md or "")


def extract_exec_summary(report_md: str, max_chars: int = 4000) -> str:
    """W9-7（纯）：提取单轨报告的执行摘要（含受控别名/译名）。

    找不到该标题时回退取开头 ``max_chars``（多数轨的头部即摘要性内容）。"""
    text = report_md or ""
    sections = _opening_sections(text, "executive")
    if sections:
        seg = str(sections[0].get("body") or "").strip()
        if seg:
            return seg[:max_chars]
    return text.strip()[:max_chars]


def reconcile_track_reports(merged_report: str,
                            labeled_reports: list[tuple[str, str]],
                            llm: Any = None, *,
                            max_prompt_chars: int = 30000) -> tuple[str, dict]:
    """W9-7：合并卷宗的一次有界 LLM 编辑整理，返回 (整理后的卷宗, 审计 dict)。

    输入只喂各轨标题 + 执行摘要（总量 cap ``max_prompt_chars``≈30K 字符，绝不喂全文），
    产出一个「合并执行摘要 + 跨轨分歧（Cross-track disagreements）」开篇；随后确定性地把
    '# Track N' H1 降级为 '## Part N — <english title>' H2 并把开篇前置。无论 LLM
    成败，确定性基线都会去掉重复的执行摘要/阅读指南、保留第一份有效开篇并降级轨级 H1。
    LLM 失败、输出可疑或 [S#] 覆盖/悬空审计退化时，回退该确定性基线。
    """
    audit: dict[str, Any] = {"applied": False, "reason": ""}
    tracks = [(t, r) for t, r in (labeled_reports or []) if (r or "").strip()]
    deterministic, deterministic_opening = _deterministic_track_report(tracks)
    fallback = deterministic or demote_track_headings(merged_report)

    def _reject(reason: str, **details: Any) -> tuple[str, dict]:
        audit.update({"reason": reason, "fallback": "deterministic", **details})
        return fallback, audit

    try:
        if len(tracks) < 2:
            audit["reason"] = "tracks<2"
            return merged_report, audit
        per = max(2000, (max_prompt_chars - 2000) // len(tracks))
        blocks = []
        for i, (title, rep) in enumerate(tracks, 1):
            blocks.append(f"### Track {i}: {title}\n{extract_exec_summary(rep, per)}")
        payload = "\n\n".join(blocks)[:max_prompt_chars]
        prompt = (
            "你是一名研究卷宗的终审编辑。下面是同一预测问题的多条并行研究轨各自的执行摘要"
            "（轨 1 = 基线证据扫描；其余轨为角度特化视角）。请产出合并卷宗的统一开篇，"
            "要求：\n"
            "1. 以 '## Executive Summary' 开头，把各轨执行摘要合并为一份连贯的摘要"
            "（去重、保留各轨独有的关键结论，不要逐轨罗列）。\n"
            "2. 紧随其后输出 '### Cross-track disagreements' 小节：用列表逐条点名各轨"
            "互相冲突的头条数字/结论（指标、各轨口径、差异），没有实质冲突就写"
            "「未发现实质性跨轨分歧」。\n"
            "3. 原样保留支撑被采用声明的 [S#] 标记；不得改号、删除基线摘要已有标记或"
            "发明输入中不存在的标记。\n"
            "4. 只输出上述 markdown，不要前言/解释；绝不提及研究 pass、working notes、"
            "轨道机制等管线内部词汇；语言与输入摘要的主要语言一致。\n\n"
            f"{payload}"
        )
        if llm is None:
            from ..utils.llm_client import LLMClient
            llm = LLMClient()
        out = llm.chat([{"role": "user", "content": prompt}],
                       temperature=0.2, max_tokens=4000)
        out = (out or "").strip()
        if len(out) < 200 or any(mk in out for mk in _LLM_ERROR_MARKERS):
            return _reject(f"llm output rejected (len={len(out)})")
        output_sections = _opening_sections(out)
        exec_count = sum(row["kind"] == "executive" for row in output_sections)
        orientation_count = sum(row["kind"] == "orientation" for row in output_sections)
        if exec_count != 1 or orientation_count > 1:
            return _reject(
                "llm opening structure rejected",
                opening_sections={
                    "executive": exec_count,
                    "orientation": orientation_count,
                },
            )
        citation_audit = _opening_citation_audit(
            out, deterministic_opening, merged_report)
        if not citation_audit["passed"]:
            return _reject("llm citation audit regressed", citation_audit=citation_audit)

        # Deterministic already contains the canonical opening followed by the
        # clean evidence body. Replace only that opening, never the source body.
        body = deterministic[len(deterministic_opening):].lstrip() \
            if deterministic_opening and deterministic.startswith(deterministic_opening) \
            else deterministic
        candidate = out.rstrip() + ("\n\n" + body if body else "")
        audit.update({
            "applied": True,
            "opening_chars": len(out),
            "tracks": len(tracks),
            "citation_audit": citation_audit,
        })
        return candidate, audit
    except Exception as e:  # noqa: BLE001 — 整理增强失败时仍执行确定性清理
        return _reject(f"{type(e).__name__}: {e}")


def merge_sources_union(track_sources: list[Any]) -> list[dict]:
    """PAR-2（纯）：跨轨合并来源，按规范化 URL 去重，冲突时保最高层级（S1>S2>…）。

    非 dict / 缺 url 的行原样保留（无法去重）。相同 URL：保留首见行，把更高层级写回、
    并用任一轨的非空字段回填缺失字段（保守合并，绝不丢信息）。保持首见顺序（确定性）。
    """
    out: list[dict] = []
    index: dict[str, int] = {}
    for sources in track_sources:
        if not isinstance(sources, list):
            continue
        for s in sources:
            if not isinstance(s, dict):
                continue
            key = _track_norm_url(s.get("url"))
            if not key:
                out.append(dict(s))
                continue
            if key not in index:
                index[key] = len(out)
                out.append(dict(s))
            else:
                existing = out[index[key]]
                if _track_tier_rank(s.get("tier")) < _track_tier_rank(existing.get("tier")):
                    existing["tier"] = s.get("tier")
                for k, v in s.items():
                    if v and not existing.get(k):
                        existing[k] = v
    return out


_TRACK_CITATION_RE = re.compile(r"\[\s*S(\d+)\s*\]", re.I)
_TRACK_REFERENCES_HEADING_RE = re.compile(
    r"^#{1,3}\s*(?:References|参考来源|参考文献)\s*$", re.I)
_TRACK_URL_RE = re.compile(r"https?://[^\s<>\])}\"']+", re.I)


def normalize_track_report_citations(
        report: str, track_sources: Any,
        merged_sources: list[dict]) -> tuple[str, dict[str, int]]:
    """Remap one track's local ``[S#]`` namespace into the merged source registry.

    Each DeerFlow track legitimately starts at S1. Concatenating those reports
    without remapping makes one marker refer to several sources. We recover each
    local marker from its References entry (falling back to the same-position
    track source), map by normalized URL into ``merged_sources``, remove the local
    References section, and strip only markers that cannot be resolved.
    """
    rows = track_sources if isinstance(track_sources, list) else []
    global_by_url = {
        _track_norm_url(row.get("url")): index
        for index, row in enumerate(merged_sources or [], 1)
        if isinstance(row, dict) and _track_norm_url(row.get("url"))
    }
    local_by_tag: dict[int, str] = {
        index: _track_norm_url(row.get("url"))
        for index, row in enumerate(rows, 1)
        if isinstance(row, dict) and _track_norm_url(row.get("url"))
    }

    lines = str(report or "").split("\n")
    body: list[str] = []
    in_refs = False
    for line in lines:
        stripped = line.strip()
        if _TRACK_REFERENCES_HEADING_RE.match(stripped):
            in_refs = True
            continue
        if in_refs and re.match(r"^#{1,3}\s+\S", stripped):
            in_refs = False
        if in_refs:
            marker = _TRACK_CITATION_RE.search(line)
            url = _TRACK_URL_RE.search(line)
            if marker and url:
                local_by_tag[int(marker.group(1))] = _track_norm_url(url.group(0))
            continue
        body.append(line)

    stats = {"markers": 0, "remapped": 0, "stripped": 0}
    out: list[str] = []
    in_fence = False
    for line in body:
        stripped = line.lstrip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            out.append(line)
            continue
        if in_fence:
            out.append(line)
            continue

        def _replace(match: "re.Match[str]") -> str:
            stats["markers"] += 1
            local_n = int(match.group(1))
            global_n = global_by_url.get(local_by_tag.get(local_n, ""))
            if not global_n:
                stats["stripped"] += 1
                return ""
            stats["remapped"] += 1
            return f"[S{global_n}]"

        rewritten = _TRACK_CITATION_RE.sub(_replace, line)
        rewritten = re.sub(r"[ \t]{2,}", " ", re.sub(r"\s+([.,;:!?，。；：！？])", r"\1", rewritten))
        out.append(rewritten.rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip(), stats


def append_merged_references(report: str, merged_sources: list[dict]) -> str:
    """Append one machine-readable References section for globally remapped markers."""
    cited = sorted({int(value) for value in _TRACK_CITATION_RE.findall(report or "")})
    if not cited:
        return report
    rows: list[str] = []
    for number in cited:
        if not (1 <= number <= len(merged_sources)):
            continue
        source = merged_sources[number - 1]
        if not isinstance(source, dict):
            continue
        title = str(source.get("title") or "source").strip()
        url = str(source.get("url") or "").strip()
        rows.append(f"- [S{number}] {title}" + (f" — {url}" if url else ""))
    if not rows:
        return report
    return report.rstrip() + "\n\n## References\n\n" + "\n".join(rows) + "\n"


def strip_exec_summary_section(report_md: str) -> str:
    """Remove all track-local Executive Summary aliases/translations."""
    return _strip_opening_sections(report_md, {"executive"})


def merge_list_dedup(track_lists: list[Any]) -> list:
    """PAR-2（纯）：跨轨拼接数组并按规范 JSON 恒等去重（quantitative/contested/timeline 用）。
    保持首见顺序；不可序列化的元素回退 repr 作键。"""
    out: list = []
    seen: set[str] = set()
    for lst in track_lists:
        if not isinstance(lst, list):
            continue
        for item in lst:
            try:
                key = json.dumps(item, sort_keys=True, ensure_ascii=False)
            except (TypeError, ValueError):
                key = repr(item)
            if key in seen:
                continue
            seen.add(key)
            out.append(item)
    return out


def merge_actors_objs(track_actor_objs: list[Any]) -> tuple[Optional[dict], dict]:
    """PAR-2：跨轨合并 actors.json 对象，再走既有 reconcile_cast 去重。

    先并集各轨的 actors[]/relationships[]/key_events[]，标量字段（central_question/
    as_of_date/situation_brief/hot_topics…）取首个非空轨；然后调用 reconcile_cast 对重复
    actor 做规范化合并并改写关系端点。返回 (merged_obj|None, audit)。全轨无 actors → (None, 空 audit)。
    """
    base: Optional[dict] = None
    all_actors: list = []
    all_rel: list = []
    all_events: list = []
    for obj in track_actor_objs:
        if not isinstance(obj, dict):
            continue
        if base is None:
            base = {k: v for k, v in obj.items()
                    if k not in ("actors", "relationships", "key_events")}
        all_actors.extend(obj.get("actors") or [])
        all_rel.extend(obj.get("relationships") or [])
        all_events.extend(obj.get("key_events") or [])
    if base is None:
        return None, {"merged": [], "n_before": 0, "n_after": 0}
    merged = dict(base)
    merged["actors"] = all_actors
    if all_rel:
        merged["relationships"] = all_rel
    if all_events:
        merged["key_events"] = all_events
    try:
        from ..utils.actors import reconcile_cast as _reconcile
        recon, audit = _reconcile(merged)
        return recon, audit
    except Exception:  # noqa: BLE001 — 去重失败回退未去重并集（union-dedup 兜底）
        return merged, {"merged": [], "n_before": len(all_actors), "n_after": len(all_actors)}


def merge_research_quality(track_metas: list[Any]) -> dict:
    """PAR-2（纯）：合并 research_quality = 各轨 score 的最小值（保守），附每轨明细。

    以 score 最小的轨的 research_quality 块为基底（其 components 内部自洽），加 per_track
    明细与 merged_from_tracks 计数。无任何轨带评分 → 仅返回 {per_track, merged_from_tracks}。
    """
    per_track: list[dict] = []
    min_rq: Optional[dict] = None
    min_score: Optional[float] = None
    for i, meta in enumerate(track_metas, start=1):
        rq = meta.get("research_quality") if isinstance(meta, dict) else None
        if not isinstance(rq, dict):
            per_track.append({"track": i, "research_quality": None})
            continue
        score = rq.get("score")
        per_track.append({"track": i, "score": score, "components": rq.get("components")})
        if isinstance(score, (int, float)):
            if min_score is None or score < min_score:
                min_score = score
                min_rq = rq
    merged = dict(min_rq) if isinstance(min_rq, dict) else {}
    merged["per_track"] = per_track
    merged["merged_from_tracks"] = len(track_metas)
    return merged


def _source_count(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def merge_source_health(track_metas: list[Any]) -> Optional[dict]:
    """RESEARCH-2（纯）：合并各轨 meta.source_health（每轨是独立研究子进程，计数互不重叠）。

    tools / search_providers 按键求和；fetch_providers 按 provider→结果类求和 count，reason
    取最后一个非空值；search_refused 取首个非空；merged_from_tracks = 带该块的轨数。
    没有任何轨带该块（RESEARCH_SOURCE_TAXONOMY 关）→ None，合并 meta 不新增键。
    """
    blocks = [meta["source_health"] for meta in track_metas
              if isinstance(meta, dict) and isinstance(meta.get("source_health"), dict)]
    if not blocks:
        return None
    tools: dict[str, int] = {}
    search_providers: dict[str, int] = {}
    fetch_providers: dict[str, dict[str, dict[str, Any]]] = {}
    refused: Any = None
    for block in blocks:
        for target, counts in ((tools, block.get("tools")), (search_providers, block.get("search_providers"))):
            for name, count in (counts.items() if isinstance(counts, dict) else ()):
                target[str(name)] = target.get(str(name), 0) + _source_count(count)
        providers = block.get("fetch_providers")
        for provider, outcomes in (providers.items() if isinstance(providers, dict) else ()):
            merged_outcomes = fetch_providers.setdefault(str(provider), {})
            for outcome, entry in (outcomes.items() if isinstance(outcomes, dict) else ()):
                if not isinstance(entry, dict):
                    continue
                merged_entry = merged_outcomes.setdefault(str(outcome), {"count": 0, "reason": ""})
                merged_entry["count"] += _source_count(entry.get("count"))
                if entry.get("reason"):
                    merged_entry["reason"] = str(entry["reason"])
        if refused is None and block.get("search_refused"):
            refused = block["search_refused"]
    return {"version": 1, "tools": tools, "search_providers": search_providers,
            "fetch_providers": fetch_providers, "search_refused": refused,
            "merged_from_tracks": len(blocks)}


def _research_health_stage(research_quality: Any) -> Optional[dict]:
    """RESEARCH-2（纯）：research_quality 已降级 → pipeline_health 的 research 阶段块
    {health: degraded, issues: 前 8 条降级说明（各 ≤200 字符）, score}；否则 None。"""
    if not isinstance(research_quality, dict) or not research_quality.get("degraded"):
        return None
    degradation = research_quality.get("degradation")
    if isinstance(degradation, str):
        degradation = [degradation]
    issues = [str(item)[:200] for item in (degradation if isinstance(degradation, list) else [])
              if str(item).strip()][:8]
    return {"health": "degraded", "issues": issues, "score": research_quality.get("score")}


def _source_tier_histogram(sources: Any) -> dict[str, int]:
    """PAR-2（纯）：从（合并后的）sources 重算 {s1_count..s4_count,s_unknown}，键名与 bridge 一致。"""
    hist = {"s1_count": 0, "s2_count": 0, "s3_count": 0, "s4_count": 0, "s_unknown": 0}
    if not isinstance(sources, list):
        return hist
    for s in sources:
        r = _track_tier_rank(s.get("tier")) if isinstance(s, dict) else 9
        hist[f"s{r}_count" if 1 <= r <= 4 else "s_unknown"] += 1
    return hist


# R2-RES-3 source-tier quality weights for the advisory confidence penalty.
# S4 (reject-tier), ``s_unknown`` and any unrecognized key keep the historical
# 0.2 fallback weight.
_SOURCE_TIER_PENALTY_WEIGHTS = {"s1": 1.0, "s2": 0.7, "s3": 0.4}
_SOURCE_TIER_PENALTY_FALLBACK_WEIGHT = 0.2
_SOURCE_TIER_KEY_RE = re.compile(r"^(s[1-4])(?:_count)?$")


def _source_tier_penalty_weight(key: Any) -> float:
    """IF-10: weight of one ``meta.source_tiers`` key, whatever its producer shape.

    Every producer (bridge ``source_tier_histogram``, :func:`_source_tier_histogram`)
    emits ``{s1_count, s2_count, s3_count, s4_count, s_unknown}``, while the
    penalty was keyed on bare ``S1``/``s1``.  Every tier then fell through to
    the fallback weight, so any run with sources paid a constant 0.08
    ``source_tier_mix`` penalty regardless of quality.  Both shapes normalize
    to ``s1``..``s4`` here.
    """
    match = _SOURCE_TIER_KEY_RE.match(str(key).strip().lower())
    tier = match.group(1) if match else ""
    return _SOURCE_TIER_PENALTY_WEIGHTS.get(tier, _SOURCE_TIER_PENALTY_FALLBACK_WEIGHT)


def pick_freshest_markets(track_markets: list[Any]) -> Optional[dict]:
    """PAR-2（纯）：跨轨取「最新」预测市场快照（按 as_of ISO 字符串字典序=时间序，取最大）。

    优先含非空 markets 的快照；全为空则回退任一 dict；全无 → None。
    """
    best: Optional[dict] = None
    best_key: str = ""
    for pm in track_markets:
        if not isinstance(pm, dict) or not pm.get("markets"):
            continue
        k = str(pm.get("as_of") or "")
        if best is None or k > best_key:
            best, best_key = pm, k
    if best is None:
        for pm in track_markets:
            if isinstance(pm, dict):
                return pm
    return best


def merge_market_snapshots(track_markets: list[Any], *, max_total: int = 20,
                           max_per_event: int = 3) -> Optional[dict]:
    """Relevance-gated union of per-track market registries.

    Older code selected one freshest snapshot, so an empty/failing track could
    erase disjoint useful markets discovered elsewhere.  Union by ``market_id``;
    the freshest snapshot wins mutable quote fields while older rows backfill
    provenance.  The bridge has already applied the semantic relevance gate.
    """
    snapshots = [pm for pm in track_markets if isinstance(pm, dict)]
    if not snapshots:
        return None
    queries: list[str] = []
    seen_queries: set[str] = set()
    by_id: dict[str, dict[str, Any]] = {}
    row_as_of: dict[str, str] = {}
    # ``markets`` contains only rows that survived each track's relevance gate.
    # Preserve the upstream raw candidate count separately: when zero selected
    # rows remain, it distinguishes "candidates existed but were irrelevant"
    # from a verified empty provider response or a total transport outage.
    candidate_count = 0
    raw_candidate_count = 0
    selected_input_count = 0
    sources: set[str] = set()
    status_totals = {
        "query_count": 0,
        "successful_query_count": 0,
        "transport_failure_count": 0,
        "inflight_timeout_count": 0,
        "tool_observation_count": 0,
    }
    empty_reason_counts: dict[str, int] = {}
    end_date_gate_seen = False
    # A track whose snapshot deadline ran out left queries unanswered (RESEARCH-3).
    deadline_exhausted = False
    for track_index, pm in enumerate(snapshots, start=1):
        snap_as_of = str(pm.get("as_of") or "")
        source_value = pm.get("registry_sources") or pm.get("source")
        if isinstance(source_value, list):
            sources.update(str(value) for value in source_value if value)
        elif source_value:
            sources.add(str(source_value))
        track_status = pm.get("status") if isinstance(pm.get("status"), dict) else {}
        # New tool payloads call this attempted_query_count; older canonical
        # snapshots call it query_count.  Count one or the other, never both.
        attempted_value = track_status.get(
            "attempted_query_count", track_status.get("query_count", 0)
        )
        try:
            status_totals["query_count"] += max(0, int(attempted_value or 0))
        except (TypeError, ValueError):
            pass
        for key in status_totals:
            if key == "query_count":
                continue
            try:
                status_totals[key] += max(0, int(track_status.get(key) or 0))
            except (TypeError, ValueError):
                continue
        empty_reason = str(track_status.get("empty_reason") or "").strip()
        if empty_reason:
            empty_reason_counts[empty_reason] = empty_reason_counts.get(empty_reason, 0) + 1
        if "end_date_passed_count" in track_status:
            end_date_gate_seen = True
        try:
            if int(track_status.get("deadline_exhausted") or 0) > 0:
                deadline_exhausted = True
        except (TypeError, ValueError, OverflowError):
            pass
        for query in pm.get("queries") or []:
            text = str(query or "").strip()
            key = text.casefold()
            if text and key not in seen_queries:
                seen_queries.add(key)
                queries.append(text)
        rows = [row for row in (pm.get("markets") or []) if isinstance(row, dict)]
        selected_input_count += len(rows)
        raw_count = track_status.get("candidate_count")
        try:
            normalized_count = max(0, int(raw_count)) if raw_count is not None else len(rows)
        except (TypeError, ValueError):
            normalized_count = len(rows)
        candidate_count += normalized_count
        provider_raw_count = track_status.get("raw_candidate_count", normalized_count)
        try:
            raw_candidate_count += max(0, int(provider_raw_count))
        except (TypeError, ValueError):
            raw_candidate_count += normalized_count
        for row in rows:
            market_id = str(row.get("market_id") or "").strip()
            if not market_id:
                continue
            existing = by_id.get(market_id)
            provenance = list((existing or {}).get("track_provenance") or [])
            provenance.append({"track": track_index, "as_of": snap_as_of})
            if existing is None or snap_as_of >= row_as_of.get(market_id, ""):
                merged = dict(existing or {})
                merged.update(row)
                by_id[market_id] = merged
                row_as_of[market_id] = snap_as_of
            by_id[market_id]["track_provenance"] = provenance

    def _numeric(value: Any) -> float:
        try:
            number = float(value)
            return number if number == number else 0.0
        except (TypeError, ValueError):
            return 0.0

    ranked = sorted(
        by_id.values(),
        key=lambda row: (
            -_numeric(row.get("relevance_score")),
            -_numeric(row.get("volume")),
            str(row.get("market_id") or ""),
        ),
    )
    selected: list[dict] = []
    per_event: dict[str, int] = {}
    selection_limit = max(0, int(max_total))
    for row in ranked:
        if len(selected) >= selection_limit:
            break
        event = str(row.get("event_title") or row.get("market_id") or "").strip()
        if max_per_event > 0 and per_event.get(event, 0) >= max_per_event:
            continue
        per_event[event] = per_event.get(event, 0) + 1
        selected.append(row)
    latest_as_of = max((str(pm.get("as_of") or "") for pm in snapshots), default="")
    all_network_attempts_failed = bool(
        status_totals["query_count"] > 0
        and status_totals["successful_query_count"] == 0
        and status_totals["transport_failure_count"] >= status_totals["query_count"]
    )
    if selected:
        evidence_state = "markets_selected"
    elif candidate_count:
        evidence_state = "all_candidates_irrelevant"
    elif all_network_attempts_failed:
        evidence_state = "transport_failure"
    elif (status_totals["inflight_timeout_count"] > 0
          and status_totals["successful_query_count"] == 0):
        evidence_state = "inflight_timeout"
    elif status_totals["transport_failure_count"] > 0 or deadline_exhausted:
        evidence_state = "partial_transport_failure"
    else:
        evidence_state = "verified_empty"
    status = {
        "attempted": True,
        "state": evidence_state,
        "snapshot_count": len(snapshots),
        "raw_candidate_count": raw_candidate_count,
        "candidate_count": candidate_count,
        "selected_input_count": selected_input_count,
        "unique_candidate_count": len(by_id),
        "selected_count": len(selected),
        "empty_reason_counts": empty_reason_counts,
        **status_totals,
        "attempted_query_count": status_totals["query_count"],
        # A failed or unanswered query with no candidate means coverage is unknown:
        # never the generic 'no_equivalent_market' (the bridge collector's rule, RESEARCH-3).
        "empty_reason": None if selected else (
            "all_candidates_irrelevant" if candidate_count else (
                "transport_failure" if all_network_attempts_failed else (
                    "partial_transport_failure"
                    if status_totals["transport_failure_count"] > 0 or deadline_exhausted
                    else "no_equivalent_market"
                )
            )
        ),
    }
    if deadline_exhausted:
        status["deadline_exhausted"] = 1
    # TIME-3: keep the endDate-gate exclusion telemetry across tracks by recounting the
    # stamped rows that survived selection. Only tracks that ran with the gate on carry the
    # key, so an all-gate-off merge keeps its bytes.
    if end_date_gate_seen:
        status["end_date_passed_count"] = sum(
            1 for row in selected if row.get("window_ended") is True)
    return {
        "as_of": latest_as_of,
        "source": "polymarket",
        "registry_sources": sorted(sources) or ["polymarket"],
        "queries": queries,
        "markets": selected,
        "no_relevant_markets": not bool(selected),
        "status": status,
    }


def merge_market_price_histories(track_histories: list[Any],
                                 selected_market_ids: set[str]) -> dict[str, list[dict]]:
    """Union price series for selected markets only, latest point per timestamp wins."""
    merged: dict[str, dict[int, dict]] = {}
    for history in track_histories:
        if not isinstance(history, dict):
            continue
        for market_id, points in history.items():
            mid = str(market_id or "").strip()
            if mid not in selected_market_ids or not isinstance(points, list):
                continue
            bucket = merged.setdefault(mid, {})
            for point in points:
                if not isinstance(point, dict):
                    continue
                try:
                    timestamp = int(float(point.get("t")))
                    probability = float(point.get("p"))
                except (TypeError, ValueError):
                    continue
                if timestamp <= 0 or not (0.0 <= probability <= 1.0):
                    continue
                bucket[timestamp] = {"t": timestamp, "p": probability}
    return {
        market_id: [points[t] for t in sorted(points)]
        for market_id, points in merged.items() if points
    }


def load_research_dossier_for_simulation(simulation_id: Optional[str]) -> dict[str, Any]:
    """T4.1: best-effort 找到含该 simulation_id 的管线 handoff，加载研究档案。

    供手动报告路径（api/report.py）复用：让手动生成/对话也能钉入背景档案。找不到对应
    管线 / handoff 时全部返回 None，ReportAgent 回退到冷图盲搜路径（与旧行为一致）。
    """
    out: dict[str, Any] = {
        "situation_brief": None, "actors": None, "sources": None, "research_report": None,
        "actor_dossier": None,  # 双轨 Track B：角色本体档案，供手动报告路径作背景上下文（缺失为 None）
    }
    if not simulation_id:
        return out
    try:
        owner = _pipeline_for_simulation(simulation_id)
        if owner is not None:
            pid, data = owner
            hd = data.get("handoff_dir") or PipelineManager.handoff_dir(pid)
            actors = _read_json(os.path.join(hd, "actors.json"))
            report = _read_text(os.path.join(hd, "research_report.md"))
            dossier = _read_text(os.path.join(hd, "actor_dossier.md"))
            out["actors"] = actors
            out["sources"] = _read_json(os.path.join(hd, "sources.json"))
            out["research_report"] = report or None
            out["actor_dossier"] = dossier or None
            out["situation_brief"] = situation_brief(actors) if actors else None
    except Exception:  # best-effort enrichment must never break manual report generation
        pass
    return out


def _pipeline_for_simulation(simulation_id: str) -> Optional[tuple[str, dict[str, Any]]]:
    """(pipeline_id, persisted state) of the newest pipeline whose simulation is ``simulation_id``."""
    for entry in PipelineManager.list_pipelines():
        pid = entry.get("pipeline_id")
        if not pid:
            continue
        data = PipelineManager.load(pid)
        if data and data.get("simulation_id") == simulation_id:
            return pid, data
    return None


def validated_as_of_from_options(options: Optional[dict[str, Any]]) -> Optional[str]:
    """EVAL-1: the graph stage's validated as-of anchor recorded in pipeline options.

    A what-if fork reuses its base's research and graph (its graph stage never
    re-runs), so it inherits the anchor of the nearest base pipeline that recorded
    one. None when no validated anchor exists (the ledger then falls back to the
    strict actors date, then the commit date). Never raises: it runs on the report
    stage's critical path.
    """
    opts = options if isinstance(options, dict) else {}
    seen: set[str] = set()
    while True:
        value = opts.get("as_of_date_validated")
        if isinstance(value, str) and value:
            return value
        base_pid = str(opts.get("base_pipeline_id") or "")
        if not base_pid or base_pid in seen:
            return None
        seen.add(base_pid)
        try:
            base = PipelineManager.load(base_pid)
        except Exception:  # noqa: BLE001 — an unreadable base simply has no anchor
            return None
        base_opts = base.get("options") if isinstance(base, dict) else None
        opts = base_opts if isinstance(base_opts, dict) else {}


def _scenario_ledger_identity(options: Optional[dict[str, Any]]) -> dict[str, Any]:
    """EVAL-1: what-if identity of a pipeline for the ledger ({} for a plain pipeline).

    ``scenario_key`` fingerprints the fork's label + overlay, so two forks of one
    base with different overlays are different conditional forecast targets.
    """
    opts = options if isinstance(options, dict) else {}
    label = str(opts.get("scenario_label") or "").strip()
    if not label:
        return {}
    overlay = opts.get("scenario_overlay")
    try:
        key = canonical_json_sha256({"label": label,
                                     "overlay": overlay if isinstance(overlay, dict) else {}})
    except (TypeError, ValueError):
        key = canonical_json_sha256({"label": label, "overlay": {}})
    return {"scenario_label": label, "scenario_key": key}


def _ledger_owner_of_simulation(
        simulation_id: str) -> Optional[tuple[str, dict[str, Any], bool, Any]]:
    """(pipeline_id, persisted state, is_member, seed) of the pipeline that ran ``simulation_id``.

    ``is_member`` is False (seed None) for the pipeline's own simulation, and True
    with the member's recorded seed for a seed-ensemble simulation
    (``options['ensemble_member_simulations']``). One scan, newest pipeline
    first, like ``_pipeline_for_simulation``.
    """
    for entry in PipelineManager.list_pipelines():
        pid = entry.get("pipeline_id")
        if not pid:
            continue
        data = PipelineManager.load(pid)
        if not data:
            continue
        if data.get("simulation_id") == simulation_id:
            return pid, data, False, None
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        members = options.get("ensemble_member_simulations")
        if isinstance(members, dict) and simulation_id in members:
            return pid, data, True, members[simulation_id]
    return None


def ledger_identity_for_simulation(simulation_id: Optional[str]) -> dict[str, Any]:
    """EVAL-1: ledger identity fields of the pipeline that owns ``simulation_id``.

    Report entry points without orchestrator context (``/api/report/generate``
    regenerations) must key the forecast ledger exactly like the pipeline's own
    report: on the graph stage's validated as-of anchor rather than the raw
    actors.json date, a what-if fork's simulation stays a conditional scenario,
    and a seed-ensemble member's simulation stays that seed's ensemble member.
    Returns ``{pipeline_id, as_of_date[, scenario_label, scenario_key]
    [, record_class='ensemble_member', seed]}``, or {} when no pipeline ran the
    simulation. Best-effort: never raises.
    """
    if not simulation_id:
        return {}
    try:
        owner = _ledger_owner_of_simulation(simulation_id)
        if owner is None:
            return {}
        pid, data, is_member, member_seed = owner
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        identity: dict[str, Any] = {
            "pipeline_id": pid,
            "as_of_date": validated_as_of_from_options(options),
        }
        identity.update(_scenario_ledger_identity(options))
        if is_member:
            # Fail closed: an unreadable seed still never makes a member a production row.
            identity["record_class"] = "ensemble_member"
            try:
                identity["seed"] = int(member_seed)
            except (TypeError, ValueError):
                pass
        return identity
    except Exception as exc:  # noqa: BLE001 — identity lookup must never break a report
        logger.warning("ledger identity lookup for simulation %s failed (ignored): %s",
                       simulation_id, exc)
        return {}


def _fail_closed_evaluation_pin(**reason: Any) -> dict[str, Any]:
    """EVAL-13: an evaluation context without run provenance or target (fail closed).

    Used when a run cannot be shown to be production but its own pin is not
    available: the report stays out of the production ledger, calibration read
    and monitor, and no cell identity is claimed. ``reason`` flags why
    (``lookup_failed`` / ``foreign_marker`` + ``marker_pipeline_id`` /
    ``marker_unreadable`` / ``pin_unreadable``); the report carries it into
    forecast['evaluation'] and its ledger row (``ledger_commit.evaluation_fail_closed``).
    """
    pin: dict[str, Any] = {"version": EVALUATION_RUN_VERSION, "record_class": "evaluation",
                           "characterization_only": True, "eval_run_id": None,
                           "cell_id": None, "question_id": None, "target": None}
    pin.update(reason)
    return pin


def _evaluation_pin_of(pipeline_id: str, data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """EVAL-13: the evaluation pin of one pipeline (None for a production run).

    ``options['evaluation_run_v1']`` is authoritative; a value that is present but
    not an object (a corrupted or hand-edited state) fails closed
    (``pin_unreadable``). A state without it still counts as an evaluation run
    when its handoff holds the admission marker. The marker's presence alone
    decides, and it yields the full pin only to the pipeline it names
    (``pipeline_id``, written at admission): handoff dirs are shared (``fork``,
    ``scripts/batch_runs.fork_question``), and a pipeline that merely sees another
    run's marker answers a different question, so it gets a fail-closed context
    without that run's cell identity or target (``foreign_marker``). An
    unreadable marker fails closed too (``marker_unreadable``).
    """
    options = data.get("options") if isinstance(data.get("options"), dict) else {}
    if EVALUATION_RUN_OPTION in options:
        pin = options[EVALUATION_RUN_OPTION]
        if isinstance(pin, dict):
            return dict(pin)
        logger.warning("[%s] unreadable options.%s: treating the run as an evaluation run",
                       pipeline_id, EVALUATION_RUN_OPTION)
        return _fail_closed_evaluation_pin(pin_unreadable=True)
    handoff_dir = data.get("handoff_dir")
    if not handoff_dir:
        try:
            handoff_dir = PipelineManager.handoff_dir(pipeline_id)
        except ValueError:
            return None  # an id PipelineManager refuses owns no pipeline dir, hence no marker
    marker_path = os.path.join(handoff_dir, EVALUATION_RUN_MARKER)
    if not os.path.exists(marker_path):
        return None
    marker = _read_json(marker_path)
    if not isinstance(marker, dict):
        logger.warning("[%s] unreadable %s: treating the run as an evaluation run",
                       pipeline_id, EVALUATION_RUN_MARKER)
        return _fail_closed_evaluation_pin(marker_unreadable=True)
    owner = marker.get("pipeline_id")
    if owner != pipeline_id:
        logger.warning("[%s] %s belongs to pipeline %s: evaluation lane without its cell identity",
                       pipeline_id, EVALUATION_RUN_MARKER, owner)
        return _fail_closed_evaluation_pin(foreign_marker=True, marker_pipeline_id=owner)
    return {key: value for key, value in marker.items() if key != "pipeline_id"}


def evaluation_pin_for_question_fork(base_pipeline_id: str,
                                     base_state: "PipelineState") -> Optional[dict[str, Any]]:
    """EVAL-13: the pin a new-question fork of ``base_state`` carries in its options.

    ``scripts/batch_runs.fork_question`` forks a base to answer another question.
    A fork of an evaluation run stays in the evaluation lane, but it is not the
    base's cell: it carries the fail-closed context that the base's shared handoff
    marker would yield it (``foreign_marker`` naming the admitted run, no cell
    identity or target), so its lane no longer depends on that marker surviving.
    None for a production base (the fork's options stay unchanged).
    """
    base_pin = PipelineOrchestrator._evaluation_pin(base_state)
    if base_pin is None:
        return None
    return _fail_closed_evaluation_pin(
        foreign_marker=True,
        marker_pipeline_id=base_pin.get("marker_pipeline_id") or base_pipeline_id)


# Bound on following ``options['shared_simulation_from']`` links (a chain of batch forks).
_SHARED_SIMULATION_MAX_HOPS = 8


def _evaluation_pin_of_simulation_owner(simulation_id: str, pipeline_id: str,
                                        data: dict[str, Any]) -> Optional[dict[str, Any]]:
    """EVAL-13: the evaluation pin that answers for ``simulation_id`` owned by ``pipeline_id``.

    ``scripts/batch_runs.fork_question(shared_simulation=True)`` points a child at
    its base's simulation (``options['shared_simulation_from']``), so the
    newest-first owner scan finds the child, whose own context claims no cell
    identity. The simulation still is the base's run (a regeneration on it uses
    the base's question), so while the owner's context has no ``eval_run_id`` the
    pipeline it borrowed the simulation from answers instead, provided that
    pipeline still names the same simulation. A production base never downgrades
    a fail-closed child context.
    """
    pin = _evaluation_pin_of(pipeline_id, data)
    seen = {pipeline_id}
    while not (pin or {}).get("eval_run_id") and len(seen) <= _SHARED_SIMULATION_MAX_HOPS:
        if data.get("simulation_id") != simulation_id:
            break  # a seed-ensemble member's simulation is its own pipeline's, never borrowed
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        origin_id = options.get("shared_simulation_from")
        if not isinstance(origin_id, str) or not origin_id or origin_id in seen:
            break
        seen.add(origin_id)
        origin = PipelineManager.load(origin_id)
        if not isinstance(origin, dict) or origin.get("simulation_id") != simulation_id:
            break
        origin_pin = _evaluation_pin_of(origin_id, origin)
        if origin_pin is not None:
            pin = origin_pin
        data = origin
    return pin


def evaluation_context_for_simulation(simulation_id: Optional[str]) -> Optional[dict[str, Any]]:
    """EVAL-13: the evaluation pin of the pipeline that ran ``simulation_id``, else None.

    Report entry points without orchestrator context (``/api/report/generate``
    regenerations, reports on a seed-ensemble member's simulation) must honour the
    evaluation run their simulation belongs to, so ``ReportAgent`` falls back to
    this lookup when no ``evaluation_context`` was assigned. Same owner scan as
    ``ledger_identity_for_simulation``; a shared-simulation batch child defers to
    the base whose simulation it borrowed. Never raises, and fails closed: a scan
    that raises is logged and yields an evaluation context without run provenance
    (``lookup_failed``), never a production answer.
    """
    if not simulation_id:
        return None
    try:
        owner = _ledger_owner_of_simulation(str(simulation_id))
        if owner is None:
            return None
        pid, data, _is_member, _seed = owner
        return _evaluation_pin_of_simulation_owner(str(simulation_id), pid, data)
    except Exception as exc:  # noqa: BLE001 — the lookup must never break a report
        logger.warning("evaluation context lookup for simulation %s failed "
                       "(treated as an evaluation run): %s", simulation_id, exc)
        return _fail_closed_evaluation_pin(lookup_failed=True)


# TIME-7: at most this many later-dated source URLs are recorded per graph build of a hindcast.
HINDCAST_VIOLATIONS_MAX = 50


def hindcast_pin_for_simulation(simulation_id: Optional[str]) -> Optional[dict[str, Any]]:
    """TIME-6: the hindcast pin of the pipeline that ran ``simulation_id``, else None.

    ``ReportAgent._hindcast_pin`` falls back to this lookup when no ``hindcast``
    kwarg was passed (``/api/report`` regenerate and chat), so those entry points
    withhold live market data from a hindcast too. Same owner scan as
    ``evaluation_context_for_simulation`` (newest pipeline first; a seed-ensemble
    member's simulation belongs to the pipeline that recorded it). A
    shared-simulation batch child without a pin of its own defers to the pipeline
    it borrowed the simulation from, provided that pipeline still names the same
    simulation. Exceptions from the scan propagate to the caller.
    """
    if not simulation_id:
        return None
    simulation_id = str(simulation_id)
    owner = _ledger_owner_of_simulation(simulation_id)
    if owner is None:
        return None
    pipeline_id, data, _is_member, _seed = owner
    pin = hindcast_policy(data.get("options"))
    seen = {pipeline_id}
    while pin is None and len(seen) <= _SHARED_SIMULATION_MAX_HOPS:
        if data.get("simulation_id") != simulation_id:
            break  # a seed-ensemble member's simulation is its own pipeline's, never borrowed
        options = data.get("options") if isinstance(data.get("options"), dict) else {}
        origin_id = options.get("shared_simulation_from")
        if not isinstance(origin_id, str) or not origin_id or origin_id in seen:
            break
        seen.add(origin_id)
        origin = PipelineManager.load(origin_id)
        if not isinstance(origin, dict) or origin.get("simulation_id") != simulation_id:
            break
        pin = hindcast_policy(origin.get("options"))
        data = origin
    return pin


def preflight_pipeline(mode: str = "full", model: Optional[str] = None) -> list[str]:
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

    # 1) 本地知识图谱后端（建图阶段硬依赖，仅 full 模式）。
    #    本地 Graphiti 无需任何 API Key；仅检查嵌入式后端是否可导入。
    if full_mode:
        import importlib.util

        backend = Config.GRAPH_BACKEND
        if backend in ('auto', 'falkordblite') and importlib.util.find_spec(
            'redislite.async_falkordb_client'
        ) is None:
            if backend == 'auto' and importlib.util.find_spec('kuzu') is not None:
                pass  # auto 会回退到 kuzu
            elif backend == 'auto' and Config.FALKORDB_HOST:
                pass  # auto 会使用外部 FalkorDB 服务
            else:
                errors.append(
                    "本地知识图谱后端未安装。运行 ./setup.sh，或手动安装 "
                    "'falkordblite'（嵌入式，推荐，Python>=3.12）或 'kuzu'。"
                )
        elif backend == 'kuzu' and importlib.util.find_spec('kuzu') is None:
            errors.append("GRAPH_BACKEND=kuzu 但未安装 kuzu。运行 ./setup.sh 或 pip install kuzu。")

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

    # 4) 研究模型的凭据（T5.5：per-run model 覆盖时校验覆盖模型的 Key，而非 Config 默认）
    df_model = (model or Config.DEERFLOW_MODEL or 'claude').lower()
    # T6.4: 单一真源 Config.DEERFLOW_KEY_ENV（与 validate()/doctor.sh 共用，避免三处漂移）
    _df_key_env = Config.DEERFLOW_KEY_ENV
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

    # 5) INFRA-14 config audit: non-canonical booleans, malformed numbers, enum / range /
    #    coupled-pair violations (empty when CONFIG_STRICT_VALIDATION is off).
    errors.extend(Config.config_errors())

    return errors


def _actors_to_context(actors: Optional[dict]) -> Optional[str]:
    """把 actors.json 压成一段给 OntologyGenerator 的 additional_context，
    引导本体偏向真实命名实体。"""
    if not isinstance(actors, dict):
        return None
    rows = actors.get("actors") or []
    if not rows:
        return None

    contract = actors.get("actor_intelligence_contract")
    if (
        isinstance(contract, dict)
        and contract.get("schema_version") == ACTOR_INTELLIGENCE_SCHEMA_VERSION
    ):
        # A received v1 cast has already passed the parent claim contract.  Do
        # not reintroduce the model-authored flat role/stance/brief/topic plane
        # into ontology generation: those fields are outside the seal and can
        # contradict the canonical source-bound dimensions.  The ontology sees
        # only structural identity/type plus a bounded canonical claim view.
        lines = [
            "Actor intelligence（actor-intelligence/v1；仅结构身份与来源绑定声明）："
        ]
        context_chars = len(lines[0])
        for actor in rows[:25]:
            if not isinstance(actor, dict):
                continue
            name = str(actor.get("name") or "?").strip()
            actor_id = str(actor.get("actor_id") or "").strip()
            actor_type = str(actor.get("type") or "").strip()
            tier = _actor_explicit_simulation_tier(actor)
            aliases = [
                " ".join(str(alias).split())
                for alias in (actor.get("aliases") or [])
                if isinstance(alias, str) and alias.strip()
            ] if isinstance(actor.get("aliases"), list) else []
            identity = f"- {name}"
            if actor_id:
                identity += f" <{actor_id}>"
            if actor_type:
                identity += f" type={actor_type}"
            if tier is not None:
                identity += f" simulation_tier={tier}"
            if aliases:
                identity += " aliases=" + "|".join(aliases[:8])

            intelligence = actor.get("intelligence")
            dimensions = (
                intelligence.get("dimensions")
                if isinstance(intelligence, dict) else None
            )
            claim_bits: list[str] = []
            if isinstance(dimensions, dict):
                for dimension in ACTOR_INTELLIGENCE_DIMENSIONS:
                    claims = dimensions.get(dimension)
                    if not isinstance(claims, list):
                        continue
                    claim = next((
                        candidate for candidate in claims
                        if isinstance(candidate, dict)
                        and re.fullmatch(
                            r"claim_[0-9a-f]{20}",
                            str(candidate.get("claim_id") or ""),
                        )
                        and _actor_valid_sha256(
                            candidate.get("claim_sha256")
                        )
                        and any(
                            isinstance(support, dict)
                            and str(support.get("source_id") or "").strip()
                            and str(support.get("receipt_id") or "").strip()
                            and _actor_valid_sha256(
                                support.get("content_sha256")
                            )
                            for support in candidate.get("source_support") or []
                        )
                    ), None)
                    if claim is None:
                        continue
                    text = " ".join(
                        str(claim.get("claim") or "").split()
                    )[:360]
                    if not text:
                        continue
                    provenance = "/".join(filter(None, (
                        str(claim.get("evidence_type") or "").strip(),
                        str(claim.get("confidence") or "").strip(),
                        str(claim.get("status") or "").strip(),
                        str(claim.get("horizon") or "").strip(),
                        str(
                            claim.get("claim_valid_at")
                            or claim.get("as_of_date") or ""
                        ).strip(),
                    )))
                    source_ids = sorted({
                        str(support.get("source_id") or "").strip()
                        for support in claim.get("source_support") or []
                        if isinstance(support, dict)
                        and str(support.get("source_id") or "").strip()
                    })
                    claim_bits.append(
                        f"{dimension}={text}"
                        + (f" [{provenance}]" if provenance else "")
                        + (f" sources={','.join(source_ids)}" if source_ids else "")
                    )
            rendered = identity
            if claim_bits:
                rendered += ": " + "; ".join(claim_bits)
            if context_chars + len(rendered) > 12000:
                break
            lines.append(rendered)
            context_chars += len(rendered)
        return "\n".join(lines)

    # Legacy/no-contract actors retain the historical permissive projection.
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

    # T2.8: 把局势简报 + 调研确认的角色关系喂给本体生成，让 edge_types 覆盖真实关系类型，
    # source_targets 连接这些角色所属的实体类型（而非凭报告行文凭空发明边类型）。
    sb = situation_brief_block(actors)
    if sb:
        lines.append("")
        lines.append(sb)
    rels = extract_relationship_rows(actors)
    if rels:
        lines.append("")
        lines.append(
            "以下角色间关系均为深度研究实证——你的 edge_types 应覆盖这些关系类型，"
            "source_targets 应连接这些角色所属的实体类型："
        )
        for r in rels[:30]:
            typ = str(r.get("type", "")).upper()
            label = REL_LABEL.get(typ, typ or "关联")
            lines.append(f"- {r.get('source')} --[{label}/{typ}]--> {r.get('target')}")
    return "\n".join(lines)


def _expected_actor_seed_count(actors: Any) -> int:
    """Return the exact triplet attempts expected from ``seed_actors``."""
    if not isinstance(actors, dict):
        return 0
    rows = [
        row for row in (actors.get("actors") or [])
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    ]
    relationships = extract_relationship_rows(actors)
    if _is_sealed_actor_intelligence_v1(actors):
        # The strict v1 writer always emits one deterministic actor-identity
        # edge per roster member before aliases and relationships.  The legacy
        # writer only needs isolated-actor edges, which is handled below.
        expected = len(rows) + len(relationships)
        for row in rows:
            name = str(row.get("name") or "")
            aliases = row.get("aliases")
            if not isinstance(aliases, list):
                continue
            expected += sum(
                1 for alias in aliases
                if isinstance(alias, str) and alias.strip()
                and normalize_name(alias) != normalize_name(name)
            )
        return expected
    seeded_names = {
        str(value or "")
        for relation in relationships
        for value in (relation.get("source"), relation.get("target"))
        if str(value or "")
    }
    expected = len(relationships) + sum(
        str(row.get("name") or "") not in seeded_names for row in rows
    )
    for row in rows:
        name = str(row.get("name") or "")
        aliases = row.get("aliases")
        if not isinstance(aliases, list):
            continue
        expected += sum(
            1 for alias in aliases
            if isinstance(alias, str) and alias.strip()
            and normalize_name(alias) != normalize_name(name)
        )
    return expected


def _actor_graph_seed_manifest_sha256(manifest: Any) -> str:
    """Independently verify the graph-owned manifest's canonical identity."""
    if not isinstance(manifest, dict):
        raise RuntimeError("actor graph seed manifest is not an object")
    body = {
        key: value for key, value in manifest.items()
        if key != "manifest_sha256"
    }
    return hashlib.sha256(json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _load_actor_graph_seed_manifest(state: Any) -> Optional[dict[str, Any]]:
    """Load the persisted strict-v1 graph seed identity for resume checks."""
    handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(
        state.pipeline_id
    )
    artifact_path = state.artifacts.get("actor_graph_seed_manifest")
    path = str(
        artifact_path
        or os.path.join(handoff_dir, ACTOR_GRAPH_SEED_MANIFEST_FILENAME)
    )
    value = _read_json(path)
    return value if isinstance(value, dict) else None


def _validate_actor_graph_seed_contract(
    builder: Any,
    graph_id: str,
    actors: Any,
    *,
    phase: str,
    expected_manifest: Optional[dict[str, Any]] = None,
    state: Any = None,
    persist: bool = False,
) -> Optional[dict[str, Any]]:
    """Prove the deterministic v1 seed exists, with exact UUIDs and attrs.

    Count-only success is insufficient: duplicate deterministic UUIDs, entity
    resolution, pruning, or stale graph reuse can all leave fewer or different
    physical records while reporting successful calls.  The graph service owns
    projection/readback details; the parent independently binds its immutable
    expected manifest to the admitted actor contract and pipeline graph.
    """
    if not _is_sealed_actor_intelligence_v1(actors):
        return None
    try:
        current_manifest = build_actor_graph_seed_manifest(graph_id, actors)
    except Exception as exc:
        raise RuntimeError(
            f"sealed actor-intelligence/v1 graph seed manifest failed:{phase}"
        ) from exc
    if (
        not isinstance(current_manifest, dict)
        or current_manifest.get("schema_version")
        != ACTOR_GRAPH_SEED_MANIFEST_SCHEMA_VERSION
        or current_manifest.get("strict") is not True
        or current_manifest.get("graph_id") != graph_id
    ):
        raise RuntimeError(
            f"sealed actor-intelligence/v1 graph seed manifest invalid:{phase}"
        )
    current_sha = _actor_graph_seed_manifest_sha256(current_manifest)
    if current_manifest.get("manifest_sha256") != current_sha:
        raise RuntimeError(
            f"sealed actor-intelligence/v1 graph seed manifest hash invalid:{phase}"
        )
    if expected_manifest is not None:
        expected_sha = _actor_graph_seed_manifest_sha256(expected_manifest)
        if (
            expected_manifest.get("manifest_sha256") != expected_sha
            or expected_sha != current_sha
        ):
            raise RuntimeError(
                "sealed actor-intelligence/v1 graph seed manifest identity "
                f"mismatch:{phase}"
            )
    validator = getattr(builder, "validate_actor_graph_seed_readback", None)
    if not callable(validator):
        raise RuntimeError(
            "sealed actor-intelligence/v1 graph seed readback unavailable:"
            f"{phase}"
        )
    try:
        audit = validator(graph_id, current_manifest)
    except Exception as exc:
        raise RuntimeError(
            f"sealed actor-intelligence/v1 graph seed readback failed:{phase}"
        ) from exc
    if (
        not isinstance(audit, dict)
        or audit.get("schema_version")
        != ACTOR_GRAPH_SEED_READBACK_SCHEMA_VERSION
        or audit.get("status") != "ok"
        or audit.get("strict") is not True
        or audit.get("graph_id") != graph_id
        or audit.get("manifest_sha256") != current_sha
        or audit.get("expected_counts")
        != current_manifest.get("expected_counts")
    ):
        raise RuntimeError(
            f"sealed actor-intelligence/v1 graph seed readback invalid:{phase}"
        )

    if state is not None:
        state.options["graph_seed_manifest_sha256"] = current_sha
        validations = state.options.setdefault("graph_seed_readback", {})
        validations[phase] = json.loads(json.dumps(
            audit,
            ensure_ascii=False,
            sort_keys=True,
        ))
    if persist:
        if state is None:
            raise RuntimeError("graph seed manifest persistence requires state")
        from ..utils.atomic import write_json_atomic

        handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(
            state.pipeline_id
        )
        os.makedirs(handoff_dir, exist_ok=True)
        path = os.path.join(
            handoff_dir,
            ACTOR_GRAPH_SEED_MANIFEST_FILENAME,
        )
        write_json_atomic(path, current_manifest)
        state.artifacts["actor_graph_seed_manifest"] = path
    return current_manifest


def _seed_research_actors(
    builder: Any,
    graph_id: str,
    actors: Any,
    *,
    valid_at: Any,
) -> Optional[int]:
    """Seed actors, failing closed for an admitted v1 cast.

    ``GraphBuilderService.seed_actors`` historically degrades per-triplet write
    failures into a short count.  That remains acceptable for legacy payloads,
    but a current v1 cast is a required, parent-admitted Stage-1 artifact: a
    disabled, raised, missing, zero, or partial seed cannot silently fall back
    to prose extraction.
    """
    if not actors:
        return None
    required = _is_sealed_actor_intelligence_v1(actors)
    if not getattr(Config, "GRAPH_SEED_FROM_ACTORS", False):
        if required:
            raise RuntimeError(
                "sealed actor-intelligence/v1 graph seeding is disabled"
            )
        return None
    expected = _expected_actor_seed_count(actors)
    if required and expected <= 0:
        raise RuntimeError(
            "sealed actor-intelligence/v1 has no graph seed projection"
        )
    try:
        seeded = builder.seed_actors(graph_id, actors, valid_at=valid_at)
    except Exception as exc:
        if required:
            raise RuntimeError(
                "sealed actor-intelligence/v1 graph seeding failed"
            ) from exc
        logger.warning("[%s] actor seeding skipped: %s", graph_id, exc)
        return None
    if required and (
        isinstance(seeded, bool)
        or not isinstance(seeded, int)
        or seeded < expected
    ):
        raise RuntimeError(
            "sealed actor-intelligence/v1 graph seeding incomplete: "
            f"expected={expected},seeded={seeded!r}"
        )
    return seeded


# ---------------------------------------------------------------------------
# I-8-1: 每次运行的可复现性清单 run.json
# ---------------------------------------------------------------------------
# 因为 LLM 提供方可在运行时经 Config.apply_provider 热切换，事后查看 .env 无法可靠还原
# 某份报告到底是「哪个模型、几个 agent、什么研究深度」生成的。run.json 把完整解析后的
# 运行配置 + 环境指纹（已脱敏）快照下来，使每份预测可审计、可复现、可 A/B 对比。
# 默认开（成本字段几乎零开销）；包版本冻结（uv pip freeze，较慢）默认关。


def _repo_git_sha() -> Optional[str]:
    """当前仓库的 git SHA（best-effort，非 git checkout / 无 git 时返回 None）。"""
    try:
        # config.py 在 backend/app/，仓库根 = 上溯三级
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
        r = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = (r.stdout or "").strip()
        return sha if r.returncode == 0 and sha else None
    except (OSError, subprocess.SubprocessError):
        return None


def _deerflow_ref() -> Optional[str]:
    """deer-flow checkout 的 commit（用于复现研究阶段）；vendored / 无 git 时降级。"""
    try:
        deerflow_dir = getattr(Config, "DEERFLOW_DIR", "") or ""
        if not deerflow_dir or not os.path.isdir(deerflow_dir):
            return None
        if not os.path.isdir(os.path.join(deerflow_dir, ".git")):
            return "vendored"  # 子目录而非独立 git checkout（如 shallow vendoring）
        r = subprocess.run(
            ["git", "-C", deerflow_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        sha = (r.stdout or "").strip()
        return sha if r.returncode == 0 and sha else "vendored"
    except (OSError, subprocess.SubprocessError):
        return None


def _capture_key_packages() -> Optional[dict[str, Any]]:
    """可选包版本冻结（MANIFEST_CAPTURE_VERSIONS=true 时）。

    优先用 importlib.metadata 取几个关键包的版本（廉价、无子进程）；不引入新依赖，
    失败静默降级到 None。
    """
    try:
        from importlib import metadata as _md
    except Exception:
        return None
    out: dict[str, Any] = {}
    for pkg in ("graphiti-core", "sentence-transformers", "openai", "flask",
                "redislite", "kuzu", "falkordb"):
        try:
            out[pkg] = _md.version(pkg)
        except Exception:
            continue
    return out or None


def _calendar_mode() -> bool:
    """CAL：配置生成语义的日历模式判定（Config.SIM_TEMPORAL_MODE=="calendar"）。

    仅用于「运行期是否注入 OASIS_DEFAULT_MAX_ROUNDS」等生成语义决策；运行器/子进程
    一律按 simulation_config.json 里 temporal_config 的有无分派，绝不读该环境开关。
    老 Config（无该属性）→ False，走 hours 旧路径，逐字节不变。
    """
    return str(getattr(Config, "SIM_TEMPORAL_MODE", "") or "").strip().lower() == "calendar"


def _build_run_manifest(state: "PipelineState") -> dict[str, Any]:
    """构造 run.json 的内容快照（secrets 已脱敏）。

    resolved 段在管线各阶段进入时由 PipelineOrchestrator._update_manifest 增量填充；
    本函数生成首版骨架 + 不随阶段变化的环境/图谱指纹。
    """
    opts = state.options or {}
    depth = (opts.get("depth") or getattr(Config, "DEERFLOW_RESEARCH_DEPTH", "standard"))
    research_model = opts.get("research_model") or getattr(Config, "DEERFLOW_MODEL", "claude")
    # CONF-1：快照记录「生效」预算（含双轨/子代理/扇出的 ×1.5 放大），与看门狗实际用值一致；
    # 老 Config（无该 classmethod）时回退原始档位 dict（degrade-safe）。
    try:
        research_timeout = Config.deerflow_depth_budget(depth)
    except (AttributeError, TypeError):  # noqa: BLE001 — 快照绝不阻塞管线启动
        depth_budgets = getattr(Config, "DEERFLOW_DEPTH_BUDGETS", {}) or {}
        research_timeout = depth_budgets.get(
            str(depth).lower(), getattr(Config, "DEERFLOW_RESEARCH_TIMEOUT", 0)
        )
    # CAL：日历模式下默认轮数上限只在配置生成期喂 target_max（粗化粒度），
    # 运行期不再注入——清单只记用户显式指定的 max_rounds。
    if _calendar_mode():
        max_rounds = opts.get("max_rounds") or None
    else:
        max_rounds = opts.get("max_rounds") or (getattr(Config, "OASIS_DEFAULT_MAX_ROUNDS", 0) or None)
    sim_graph_feedback = bool(getattr(Config, "SIM_GRAPH_FEEDBACK", True))
    if bool(getattr(Config, "RUN_SHAPE_PIN", True)):
        # INFRA-7：模拟实际遵循的是准入钉住的安全政策，而非当前环境默认值。
        _safety = opts.get("safety_policy_v1")
        _pinned_feedback = (
            _safety.get("sim_graph_feedback") if isinstance(_safety, dict) else None)
        if _pinned_feedback is not None:
            sim_graph_feedback = bool(_pinned_feedback)

    manifest: dict[str, Any] = {
        "schema_version": PIPELINE_SCHEMA_VERSION,
        "pipeline_id": state.pipeline_id,
        "mode": state.mode,
        "created_at": state.created_at,
        "updated_at": _utcnow(),
        "repo_git_sha": _repo_git_sha(),
        "deerflow_ref": _deerflow_ref(),
        "resolved": {
            "research": {
                "model": research_model,
                "depth": str(depth).lower() if depth else None,
                "timeout_s": research_timeout,
                "language": opts.get("research_language"),
                "actor_intelligence_policy": opts.get(
                    "actor_intelligence_policy_v1"
                ),
            },
            # provider 在每阶段边界由 _update_manifest 钉入实际值（可热切换）
            "ontology": {"provider": None, "model_name": None},
            "graph": {"provider": None, "model_name": None},
            "report": {"provider": None, "model_name": None},
            "simulation": {
                "max_agents": getattr(Config, "OASIS_MAX_AGENTS", None),
                "max_rounds": int(max_rounds) if max_rounds else None,
                "total_rounds": None,  # 真实总轮数运行时填
                "recsys_wired": bool(getattr(Config, "SIM_WIRE_RECSYS", False)),
                "sim_graph_feedback": sim_graph_feedback,
            },
        },
        "graph": {
            "backend": getattr(Config, "GRAPH_BACKEND", None),
            "embed_model": getattr(Config, "GRAPHITI_EMBED_MODEL", None),
            "embed_dim": getattr(Config, "GRAPHITI_EMBED_DIM", None),
            "reranker": getattr(Config, "GRAPHITI_RERANKER", None),
        },
        "env_fingerprint": {
            "python": _python_version_string(),
        },
        # 字段名刻意避开 redact_secrets 的 secret-key 正则（含 "key"/"secret"/"token" 的键名
        # 会被整值替换为 ***REDACTED***）：用 redacted_flag / package_versions 而非
        # secrets_redacted / key_packages，避免观测字段被误脱敏。
        "redacted_flag": True,
    }
    _hindcast = hindcast_policy(opts)
    if _hindcast is not None:
        # TIME-6: a pinned hindcast records how its as-of date was enforced (only then).
        manifest["resolved"]["as_of_enforcement"] = as_of_enforcement_record(_hindcast)
    if bool(getattr(Config, "MANIFEST_CAPTURE_VERSIONS", False)):
        pkgs = _capture_key_packages()
        if pkgs:
            manifest["env_fingerprint"]["package_versions"] = pkgs
    return manifest


def _python_version_string() -> str:
    import sys
    v = sys.version_info
    return f"{v.major}.{v.minor}.{v.micro}"


def _current_provider_pair() -> dict[str, Optional[str]]:
    """当前 Config 解析出的报告/模拟阶段提供方 + 模型名（随热切换变化）。"""
    return {
        "provider": getattr(Config, "LLM_PROVIDER", None),
        "model_name": getattr(Config, "LLM_MODEL_NAME", None),
    }


# ---------------------------------------------------------------------------
# I-4-3: 产物完整性（流式 sha256 + 轻量 schema 探针）
# ---------------------------------------------------------------------------


def _sha256_file(path: str, chunk_size: int = 1 << 20) -> Optional[str]:
    """流式计算文件 sha256（1MiB 分块，避免把大研究报告/图谱 dump 整入内存）。

    文件不存在 / 读失败 → None（视为「无法核验」，由调用方决定保守重建还是放行）。
    """
    import hashlib
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            while True:
                buf = f.read(chunk_size)
                if not buf:
                    break
                h.update(buf)
        return h.hexdigest()
    except (OSError, ValueError):
        return None


def _probe_artifact_schema(name: str, path: str) -> bool:
    """I-4-3: 对已知产物做廉价的「结构是否像样」探针（best-effort，绝不抛出）。

    目的不是严格校验，而是抓住「半写/截断/被错误文本覆盖」这类粗暴损坏：
      - actors.json  → dict 且含 list 形 'actors'
      - ontology.json→ dict 且含非空 'entity_types'
      - communities.json → list
      - *.md / *.csv / 其它 → 仅看非空（交由各自阶段的语义守卫，如 research 的 400 字门）
    未知产物 / 读失败 → True（不因探针缺位误杀一份本可复用的产物）。
    """
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return False
        base = os.path.basename(path)
        if base.endswith(".json"):
            data = _read_json(path)
            if data is None:
                return False
            if base == "actors.json":
                return isinstance(data, dict) and isinstance(data.get("actors"), list)
            if base == "ontology.json":
                return isinstance(data, dict) and bool(data.get("entity_types"))
            if base == "communities.json":
                return isinstance(data, list)
            # 其它 JSON：能解析即视为通过（dict/list 皆可）。
            return isinstance(data, (dict, list))
        # 非 JSON（md/csv）：非空即可（语义门交给阶段自身）。
        return os.path.getsize(path) > 0
    except Exception:  # noqa: BLE001 — 探针永不拦截一次合法的新跑
        return True


def _manifest_entry_for(name: str, path: str, stage: str) -> Optional[dict[str, Any]]:
    """I-4-3: 为单个产物构造清单条目（路径/sha256/字节/产出阶段/产出时间/schema_ok）。

    文件缺失返回 None（不登记不存在的产物）。
    """
    if not path or not os.path.exists(path):
        return None
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    if size <= 0:
        return None
    return {
        "path": path,
        "sha256": _sha256_file(path),
        "bytes": size,
        "produced_by_stage": stage,
        "produced_at": _utcnow(),
        "schema_ok": _probe_artifact_schema(name, path),
    }


def _sim_reuse_completed_enabled() -> bool:
    """SIM-REUSE (DEFECT-1) 旋钮：RUN 阶段是否允许复用磁盘上已完成的模拟。

    env 显式值优先（模拟/编排可能在不同 shell 注入），其次 Config 属性，默认开。
    任何「非 true」的显式取值（false/0/off/…）都恢复 legacy 行为（无条件重跑）。
    """
    raw = os.environ.get("SIM_RESUME_REUSE_COMPLETED")
    if raw is not None and raw.strip():
        return raw.strip().lower() in ("1", "true", "yes", "on")
    try:
        return bool(getattr(Config, "SIM_RESUME_REUSE_COMPLETED", True))
    except Exception:  # noqa: BLE001 — 配置读取失败按默认开处理
        return True


def _actions_simulation_end_present(path: str, tail_bytes: int = 262144) -> bool:
    """完成标记探针：actions.jsonl 尾部是否含 ``simulation_end`` 事件（绝不抛出）。

    每个启用平台的模拟脚本在干净收尾时向 actions.jsonl 追加一条
    ``{"event_type": "simulation_end", ...}``——这是模拟阶段的权威完成证据
    （LOOP-001/RUN-17：进程退出码不是证据）。run_state.json 由后端监控线程维护，
    后端重启/崩溃时它可能停留在 RUNNING/FAILED，而 actions.jsonl 由子进程直写、
    不会说谎。只读尾部 ``tail_bytes`` 字节：simulation_end 是收尾事件，恒在文件尾部；
    大文件整读既慢又无必要。
    """
    try:
        if not path or not os.path.exists(path):
            return False
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            if size > tail_bytes:
                f.seek(size - tail_bytes)
            data = f.read().decode("utf-8", errors="replace")
        for line in reversed(data.splitlines()):
            if '"simulation_end"' not in line:
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("event_type") == "simulation_end":
                return True
        return False
    except OSError:
        return False


def seed_scenario_pin(primary_fc: Any) -> Optional[list]:
    """W9-5：主跑情景脊柱钉给额外种子的内容——只含 ``{name, resolution_criteria}``。

    REPORT-10（信息墙）：钉的是命名与判定标准，绝不携带主跑的概率/理由——种子报告在同一组
    命名情景上独立给出概率（集成聚合才是独立抽样）。无命名情景 → None（种子自由起名）；
    坏数据（非 dict、scenarios 不可迭代等）同样回退 None（脊柱纯增强）。纯函数。
    """
    try:
        return [
            {"name": s.get("name"), "resolution_criteria": s.get("resolution_criteria")}
            for s in (primary_fc.get("scenarios") or [])
            if isinstance(s, dict) and s.get("name")
        ] or None
    except Exception:  # noqa: BLE001 — 脊柱纯增强，坏数据回退自由起名
        return None


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
    # EVAL-17: serialises _record_sim_run_telemetry. The main run and up to
    # ENSEMBLE_SEED_CONCURRENCY seed threads read-check-write one marker map in
    # state.options; class-level so instances built without __init__ have it too.
    # _note_ensemble_member_simulation takes it as well: it is the only other seed-thread
    # write to state.options, and the full save inside _record_sim_run_telemetry
    # (asdict) must never iterate a dict another seed thread is growing.
    _sim_meter_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        # I-4-6: 运行中临时产物扫描的「上次扫描壁钟」按阶段节流戳（仅本实例/本次运行有效）。
        self._partial_scan_at: dict[str, float] = {}
        # W9-3: run_telemetry.json 增量落盘状态（attempt 起点由 _init_telemetry_flush 填充）。
        self._tel_lock = threading.Lock()
        self._tel_path: Optional[str] = None
        # EVAL-17: what this attempt carries forward from the previous run_telemetry.json
        # (telemetry.previous_attempt_carry), fixed at the attempt start.
        self._tel_carry: Optional[dict] = None
        self._tel_last_flush_calls: int = 0
        # INFRA-7: stages recomputed (not reused) in this attempt, read by the
        # resume lineage guards; this attempt's stage_reuse_v1 records, passed
        # to the stage telemetry; the attempt's fresh run.json ``resolved``
        # blocks used to restamp recomputed research/simulation blocks; and the
        # simulation runtime fields this attempt's RUN wrote to run.json.
        self._recomputed_this_attempt: set[str] = set()
        self._stage_reuse_this_attempt: list[dict[str, Any]] = []
        self._fresh_resolved: Optional[dict[str, Any]] = None
        self._sim_runtime_this_attempt: dict[str, Any] = {}

    # -- W9-3: run 遥测增量落盘 --------------------------------------------
    # 两条失败跑的教训：LLMMeter 是进程内存累加器，重启即清零；run_telemetry.json 只在
    # _run 的 finally 落一次盘——被 SIGTERM 的跑整跑 $20+ 的 token/成本账直接归零。
    # 这里把落盘改成增量：attempt 起点一次性捕获上一 attempt 的账（合并基底），此后每次
    # 阶段转换 + 每 PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS 次新 LLM 调用（在心跳/进度回调上
    # 检查）都把当前快照原子落盘。与 LLMMeter.write_run_telemetry 的关键差异：合并基底
    # 固定在 attempt 起点，反复 flush 不会把本 attempt 的中间快照误当「上一 attempt」重复
    # 累进 cumulative_total。

    def _init_telemetry_flush(self, state: "PipelineState") -> None:
        """attempt 起点：定位 run_telemetry.json 并捕获上一 attempt 的账作为合并基底。"""
        self._tel_path = os.path.join(PipelineManager._dir(state.pipeline_id), "run_telemetry.json")
        self._tel_carry = None
        self._tel_last_flush_calls = 0
        try:
            # EVAL-17: the shared carry-forward rule (a zero-call attempt keeps the history;
            # per-stage base with the pre-EVAL-17 by_stage fallback and partial marker).
            from ..utils.telemetry import previous_attempt_carry
            self._tel_carry = previous_attempt_carry(_read_json(self._tel_path))
        except Exception:  # noqa: BLE001 — 基底捕获失败按首写处理
            pass

    def _flush_run_telemetry(self, state: "PipelineState", *, final: bool = False,
                             extra: Optional[dict] = None) -> None:
        """把 LLMMeter 快照原子落盘 run_telemetry.json（增量 in_flight / 终态 final）。

        degrade-safe：任何失败仅 debug 日志，绝不影响管线。未经 _init_telemetry_flush
        初始化（_tel_path 为 None）时为 no-op。
        """
        tpath = self._tel_path
        if not tpath:
            return
        from ..utils.telemetry import LLMMeter, apply_previous_attempt_carry
        from ..utils.atomic import write_json_atomic
        with self._tel_lock:
            try:
                data = LLMMeter.snapshot(state.pipeline_id)
                data.update({
                    "pipeline_id": state.pipeline_id,
                    "status": state.status,
                    "report_id": state.report_id,
                })
                if extra:
                    data.update(extra)
                if not final:
                    data["in_flight"] = True  # 运行中快照标记（终版落盘时消失）
                # EVAL-17: cumulative_total and the per-stage cumulative_by_stage both survive
                # resumes (base fixed at the attempt start).
                apply_previous_attempt_carry(data, self._tel_carry)
                write_json_atomic(tpath, data, fsync=final)
                self._tel_last_flush_calls = int((data.get("total") or {}).get("calls") or 0)
            except Exception as _fe:  # noqa: BLE001 — 遥测落盘失败不得影响管线
                logger.debug("[%s] run_telemetry 增量落盘失败（忽略）: %s", state.pipeline_id, _fe)

    def _maybe_flush_run_telemetry(self, state: "PipelineState") -> None:
        """按 LLM 调用增量节流 flush：距上次落盘新增 ≥N 次调用才写。N<=0 关闭增量 flush。"""
        if not self._tel_path:
            return
        try:
            n = int(getattr(Config, "PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS", 20) or 0)
        except (TypeError, ValueError):
            n = 20
        if n <= 0:
            return
        try:
            from ..utils.telemetry import LLMMeter
            calls = int((LLMMeter.snapshot(state.pipeline_id).get("total") or {}).get("calls") or 0)
        except Exception:  # noqa: BLE001
            return
        if calls - self._tel_last_flush_calls >= n:
            self._flush_run_telemetry(state)

    # -- 生命周期：启动回收 + 关闭清理 ------------------------------------

    @classmethod
    def reconcile_orphans(cls) -> None:
        """后端启动时回收孤儿管线。

        硬杀 / 崩溃 / 重启会跳过 ``_run`` 的 except 块，使 pipeline_state.json 永远停在
        ``running``；前端 ``poll()`` 只在 completed/failed 时停止，于是无限空转。进程刚启动时
        ``_threads`` 必为空，故任何持久化为 running 的管线都是上一进程遗留的孤儿 → 标记 failed。

        I-4-1: 旧逻辑「不在本进程 _threads 即孤儿」只在「单进程、_threads 即真相」下成立。多
        worker / gunicorn / 重启竞态下，它会误杀另一进程里真正在飞的管线，或让两个 worker 都
        以为自己拥有同一条。开启 PIPELINE_HEARTBEAT_ENABLED（默认）时改为基于证据的存活判定：
        仅当 (owner 进程已不在 / boot_id 不是本进程 / owner 未知) 且 心跳过期 才回收；owner 进程
        仍活且心跳新鲜的「慢但活」管线一律保留。关闭该开关时回退到旧的 _threads 判定。
        """
        try:
            from ..models.task import TaskManager
            # ORCH-2: reconcile 在 create_app() 里、**绑定端口之前**运行。第二个后端在第一个仍
            # 服务 :5001 时启动，会先破坏性地把活管线回收成 failed（并杀掉其研究子进程），然后才
            # 死于 'Address already in use'——一个注定失败的重复进程踩死了活进程拥有的状态。
            # 端口已被占用 = 极可能另一后端在跑 → 整体跳过孤儿回收（由那个活进程自己管理）。
            if bool(getattr(Config, "PIPELINE_RECLAIM_PORT_PROBE", True)):
                import socket
                try:
                    _port = int(os.environ.get("FLASK_PORT", "5001") or "5001")
                except ValueError:
                    _port = 5001
                try:
                    with socket.create_connection(("127.0.0.1", _port), timeout=0.2):
                        logger.warning(
                            "端口 %d 已被占用，疑似另一后端在跑——跳过孤儿管线回收", _port)
                        return
                except OSError:
                    pass  # 端口空闲 → 本进程将是唯一后端，正常回收
            task_manager = TaskManager()
            hb_enabled = bool(getattr(Config, "PIPELINE_HEARTBEAT_ENABLED", True))
            stale_s = float(getattr(Config, "PIPELINE_HEARTBEAT_STALE_S", 120) or 120)
            for p in PipelineManager.list_pipelines():
                if p.get("status") != "running":
                    continue
                pipeline_id = p.get("pipeline_id")
                if not pipeline_id or pipeline_id in cls._threads:
                    continue
                # I-4-1: 心跳模式下，先判定该 running 管线是否仍可能在别处存活。
                if hb_enabled and not cls._orphan_is_dead(pipeline_id, stale_s):
                    logger.info(
                        "[%s] 持久化为 running 但有存活证据（owner 进程活/心跳新鲜），暂不回收",
                        pipeline_id,
                    )
                    continue
                # W9-1：打捞——主报告已完整落盘（report 阶段 completed + full_report.md +
                # forecast.json 在盘）的孤儿不再整线判死。中断只发生在报告之后的多种子集成/
                # 收尾窗口（pipe_a8986bffd918 / pipe_0f2bee7bd649 两条 $10+ 的跑正是这样被
                # 误判 failed 的）→ 落成 completed(degraded)，集成按已跳过处理。
                if bool(getattr(Config, "PIPELINE_SALVAGE_COMPLETED_ORPHANS", True)):
                    _data0 = PipelineManager.load(pipeline_id) or {}
                    _arts = cls._orphan_completed_report(_data0)
                    if _arts is not None:
                        _note = ("后端在多种子集成/收尾期间被中断；主报告已完整落盘，"
                                 "管线按 completed(degraded) 打捞恢复，多种子集成已跳过。")
                        if PipelineManager.mark_salvaged_completed(pipeline_id, _note):
                            logger.warning(
                                "[%s] 启动时打捞孤儿管线 → completed(degraded)"
                                "（报告 %s 完整在盘，集成跳过）",
                                pipeline_id, _arts.get("report_id"),
                            )
                            # 孤儿研究子进程仍要清理（打捞≠允许旧进程继续烧额度）。
                            cls._kill_orphan_research(pipeline_id, _data0.get("research_pid"))
                            for _tpid in (_data0.get("options") or {}).get("research_track_pids") or []:
                                cls._kill_orphan_research(pipeline_id, _tpid)
                            _tid = _data0.get("task_id")
                            if _tid:
                                try:
                                    task_manager.complete_task(_tid, result={
                                        "pipeline_id": pipeline_id,
                                        "report_id": _arts.get("report_id"),
                                        "salvaged": True,
                                    })
                                except Exception:  # noqa: BLE001
                                    pass
                            continue
                msg = "后端在运行中被中断（进程重启），该管线已标记为失败。"
                if PipelineManager.mark_failed(pipeline_id, msg):
                    logger.warning(f"[{pipeline_id}] 启动时回收孤儿管线 → failed")
                    data = PipelineManager.load(pipeline_id) or {}
                    # 杀掉上一进程遗留、仍在烧额度的孤儿研究子进程（按持久化的 PID）。
                    cls._kill_orphan_research(pipeline_id, data.get("research_pid"))
                    # PAR-2：并行研究轨会派生多个子进程，逐一清理（_kill_orphan_research 内部
                    # 会校验命令行含本 pipeline_id + deerflow_research.py，防 PID 复用误杀）。
                    for _tpid in (data.get("options") or {}).get("research_track_pids") or []:
                        cls._kill_orphan_research(pipeline_id, _tpid)
                    tid = data.get("task_id")
                    if tid:
                        try:
                            task_manager.fail_task(tid, msg)
                        except Exception:
                            pass
            # W9-10：启动时顺带做一次图谱 GC（保留最近 GRAPH_RETAIN_COUNT 张）。
            cls._gc_stale_graphs()
        except Exception as e:  # noqa: BLE001 — 回收失败不应阻断启动
            logger.error(f"回收孤儿管线失败: {e}", exc_info=True)

    @staticmethod
    def _orphan_completed_report(data: dict, report_dir: Optional[str] = None) -> Optional[dict]:
        """W9-1（可单测）：孤儿管线是否已有「完整报告交付物」可打捞。

        判据（全部满足才打捞，宁可漏捞不可把真坏的跑洗白）：
          - state.report_id 存在；
          - report 阶段 status == 'completed'（报告链自己宣布过成功）；
          - 报告目录下 full_report.md 非空 且 forecast.json 可解析为非空 dict。
        满足 → 返回 {'report_id', 'report_dir'}；任一不满足 → None（沿用判死路径）。
        ``report_dir`` 缺省时经 ReportManager 解析（测试可显式传入临时目录）。
        """
        if not isinstance(data, dict):
            return None
        report_id = data.get("report_id")
        if not report_id:
            return None
        st = (data.get("stages") or {}).get(STAGE_REPORT)
        if not (isinstance(st, dict) and st.get("status") == "completed"):
            return None
        if report_dir is None:
            try:
                report_dir = ReportManager._get_report_folder(report_id)
            except Exception:  # noqa: BLE001 — 解析不了报告目录 → 无从验证 → 不打捞
                return None
        try:
            fr = os.path.join(report_dir, "full_report.md")
            if not (os.path.isfile(fr) and os.path.getsize(fr) > 0):
                return None
        except OSError:
            return None
        fc = _read_json(os.path.join(report_dir, "forecast.json"))
        if not (isinstance(fc, dict) and fc):
            return None
        return {"report_id": report_id, "report_dir": report_dir}

    @staticmethod
    def _gc_stale_graphs() -> None:
        """W9-10: best-effort 图谱 GC——保留最近 GRAPH_RETAIN_COUNT 张图，回收更老的存储。

        实现体在 graph_builder.gc_stale_graphs（kg-backend 工作流并行落地）；模块/函数尚未
        部署（ImportError/AttributeError）或 retain<=0 时静默跳过，任何失败绝不阻断调用方
        （启动回收 / 管线删除）。
        """
        try:
            retain = int(getattr(Config, "GRAPH_RETAIN_COUNT", 5) or 0)
        except (TypeError, ValueError):
            retain = 5
        if retain <= 0:
            return
        try:
            from . import graph_builder as _gb
            # 兼容两种落地形态：模块级函数 gc_stale_graphs(retain=)，或
            # GraphBuilderService 实例方法（kg-backend 实际落地的形态）。
            _fn = getattr(_gb, "gc_stale_graphs", None)
            if _fn is None:
                _fn = _gb.GraphBuilderService(
                    api_key=Config.ZEP_API_KEY
                ).gc_stale_graphs
            _res = _fn(retain=retain)
            if isinstance(_res, dict) and _res:
                logger.info(
                    "图谱 GC 完成（retain=%d）: total=%s kept=%d deleted=%s skipped=%s",
                    retain, _res.get("total"), len(_res.get("kept") or []),
                    _res.get("deleted"), _res.get("skipped_reason"))
            elif _res:
                logger.info("图谱 GC 完成（retain=%d）: %s", retain, _res)
        except (ImportError, AttributeError):
            logger.debug("graph_builder.gc_stale_graphs 未部署，跳过图谱 GC")
        except Exception as _gc_err:  # noqa: BLE001 — GC 纯回收，失败无声
            logger.warning("图谱 GC 失败（忽略）: %s", _gc_err)

    @classmethod
    def _orphan_is_dead(cls, pipeline_id: str, stale_s: float) -> bool:
        """I-4-1: 基于证据判定一个「持久化为 running 但不在本进程 _threads」的管线是否真的死了。

        判定（保守，宁可漏杀不可误杀活的）：
          - owner_boot_id == 本进程 _BOOT_ID 但又不在 _threads → 本进程自己的残留 → 视为死。
          - owner_pid 存在且进程仍存活（且非本进程的 boot）→ 可能是别的 worker 在跑 → 视为活
            （除非心跳已过期到 stale_s，说明那进程虽在但 hung / pid 复用 → 回收）。
          - owner_pid 不存在 / 已退出 / 字段缺失（老状态文件无 owner 信息）→ 心跳过期或缺失即视为死。
        """
        data = PipelineManager.load(pipeline_id)
        if not data or PipelineManager.INCOMPATIBLE_KEY in data:
            # 读不出 / schema 不兼容：无证据可依，沿用旧行为（视为死，交给 mark_failed）。
            return True
        owner_boot = data.get("owner_boot_id")
        owner_pid = data.get("owner_pid")
        hb_age = _age_seconds(data.get("heartbeat_at"))
        fresh = hb_age is not None and hb_age <= stale_s

        # 本进程自己写过 owner 但已不在 _threads → 线程确已结束的残留，回收。
        if owner_boot == _BOOT_ID:
            return True
        # owner 进程仍存活（属于别的后端进程/worker）：
        if _pid_alive(owner_pid):
            # 心跳仍新鲜 → 真在跑，保留；心跳过期 → 那进程 hung 或 pid 被复用 → 回收。
            return not fresh
        # owner 进程不存在 / 字段缺失：心跳新鲜（极少见，刚崩溃）也给一个宽限，否则回收。
        # ORCH-2: owner/heartbeat 双缺失（老状态文件、或手工修复过的状态）此前零宽限、立即判死。
        # 改为退回 updated_at 给同一个心跳窗口的宽限，避免刚手工编辑/刚崩溃的状态被秒杀。
        if hb_age is None:
            up_age = _age_seconds(data.get("updated_at"))
            return not (up_age is not None and up_age <= stale_s)
        return not fresh

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
            # 同时要求命令行含本管线的 handoff 路径（--out-dir .../<pipeline_id>/handoff 中已带
            # pipeline_id），避免 PID 复用时误杀同名脚本的另一条管线（EXECPLAN2 F-1-8）。
            if (check.returncode != 0
                    or "deerflow_research.py" not in cmdline
                    or pipeline_id not in cmdline):
                return  # 进程已退出，或 PID 已被复用/属于别的管线 → 不动
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
        language: Optional[str] = None,
        model: Optional[str] = None,
        evaluation: Optional[dict[str, Any]] = None,
        as_of: Optional[str] = None,
    ) -> PipelineState:
        """创建管线记录并在后台线程启动。立即返回（含 pipeline_id / task_id）。

        EVAL-13 ``evaluation``：评估运行上下文（见 validate_evaluation_context）。在创建任何
        目录/任务之前校验，非法即 ValueError；合法时钉入 options['evaluation_run_v1'] 并落
        handoff/evaluation_run.json。缺省 None → options 与 handoff 逐字节不变。

        TIME-7 ``as_of``：回测准入（规范 YYYY-MM-DD，不晚于今天 UTC）。同样在创建任何目录/任务
        之前 fail-closed 校验：Config.HINDCAST_ENABLED 未开、日期非规范/在未来、或本次运行将用
        的研究引擎不是 v3 → ValueError（绝不悄悄按实时运行）。合法时钉入 options['hindcast_policy_v1']
        （TIME-6 capture_hindcast_policy_v1），并作为评估运行准入：调用方未给 evaluation 时以
        eval_run_id ``hindcast_<YYYYMMDD>`` 走 EVAL-13 同一条钉/标记路径（评估账本、跳过生产
        校准、解析监测排除）；调用方给了 evaluation（golden 回放）则沿用其值。缺省 None → 今日路径。

        两类准入拒绝（as_of 与 evaluation）都抛 RunAdmissionError（ValueError 子类）：运行 API
        只把它映射为 400；创建目录/任务之后抛出的 ValueError 是内部故障，仍是 500。

        INFRA-14：CONFIG_STRICT_VALIDATION 开启（默认）且配置审计有错误时，在任何准入与
        目录/任务之前抛 ConfigurationError（RuntimeError 子类，errors 列出各条原因）。
        """
        config_errors = Config.config_errors()
        if config_errors:
            raise ConfigurationError(config_errors)
        admission_actor_policy: Optional[dict[str, Any]] = None
        hindcast_pin: Optional[dict[str, Any]] = None
        if as_of is not None:
            as_of, admission_actor_policy, engine = admit_hindcast_as_of(as_of)
            hindcast_pin = capture_hindcast_policy_v1(as_of, research_engine=engine)
            if evaluation is None:
                evaluation = {"eval_run_id": "hindcast_" + as_of.replace("-", "")}
        evaluation_pin: Optional[dict[str, Any]] = None
        if evaluation is not None:
            try:
                evaluation_pin = build_evaluation_pin(evaluation)
            except ValueError as exc:
                raise RunAdmissionError(str(exc)) from exc
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
            # T5.5: 每次运行的研究语言/模型覆盖。language 区分三态：None=用 Config 默认；
            # ""=auto（不传 --target-language，模型自选）；具体值=覆盖。model: None=用 Config 默认。
            "research_language": language,
            "research_model": model or None,
        })
        state.options["actor_intelligence_policy_v1"] = (
            admission_actor_policy if admission_actor_policy is not None
            else admission_actor_intelligence_policy_v1()
        )
        # Foglamp WP1 (1B)：新管线在准入时钉住安全政策快照——服务重载/环境变量漂移
        # 不得让一条已准入的运行悄悄改变图谱反馈/种子/extremize/模拟影响语义。
        state.options["safety_policy_v1"] = capture_safety_policy_v1("admission")
        if hindcast_pin is not None:
            # TIME-7：回测钉（研究子进程据此拿到 RESEARCH_AS_OF、扣下预测市场；图谱锚定钉日；
            # 报告阶段按 TIME-6 扣下市场并盖 hindcast 章）。resume 原样保留，fork 携带。
            state.options[HINDCAST_POLICY_OPTION] = hindcast_pin
        if evaluation_pin is not None:
            # EVAL-13：评估运行准入钉——报告跳过生产校准读、只入评估账本、不进解析监测。
            # handoff 标记供无编排器上下文的报告入口（API 重生成）按模拟 id 查回。标记另记
            # 准入管线 id：handoff 目录可被共享（what-if 分叉、batch_runs 子问题），只有它自己
            # 才能凭标记取回整份钉（见 _evaluation_pin_of）。
            from ..utils.atomic import write_json_atomic
            state.options[EVALUATION_RUN_OPTION] = evaluation_pin
            write_json_atomic(os.path.join(state.handoff_dir, EVALUATION_RUN_MARKER),
                              dict(evaluation_pin, pipeline_id=pipeline_id))
        # INFRA-7：第二份准入快照——影响结果的旋钮 + provider 出处（resume 时据此检测漂移）。
        cls._pin_run_shape(state, run_shape.ORIGIN_ADMISSION)
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
    def _dependent_forks(cls, pipeline_id: str) -> list[str]:
        """返回把 pipeline_id 当作 base 的 fork 管线 id 列表。

        fork（what-if 情景）与其 base **共享同一个 handoff 目录**（research/ontology/graph
        产物），删除 base 会 rmtree 掉该目录，让所有 fork 的恢复/报告复用断裂。删除前据此
        守卫。尽力而为；读不到 options 时退化为加载完整状态。
        """
        deps: list[str] = []
        try:
            for p in PipelineManager.list_pipelines():
                pid = p.get("pipeline_id")
                if not pid or pid == pipeline_id:
                    continue
                opts = p.get("options")
                if not isinstance(opts, dict):
                    full = PipelineManager.load(pid)
                    opts = (full or {}).get("options") if isinstance(full, dict) else None
                if isinstance(opts, dict) and opts.get("base_pipeline_id") == pipeline_id:
                    deps.append(pid)
        except Exception:  # noqa: BLE001 — 守卫为尽力而为，扫描失败不阻断删除决策
            pass
        return deps

    @classmethod
    def delete_pipeline(cls, pipeline_id: str, force: bool = False) -> dict[str, Any]:
        """删除一条已结束的管线记录（含其 handoff 产物目录）。

        在飞管线必须先取消再删除——删除运行中的状态文件会让 _run 线程在下次
        落盘时凭空复活记录，且孤儿子进程无人回收。

        若该管线被其它 fork 当作 base（共享 handoff 目录），默认拒绝删除（返回
        has_dependents + 依赖列表），避免静默破坏 fork；force=True 可强制删除。

        Returns:
            {"ok": bool, "status": str}  status ∈ deleted / not_found / still_running / has_dependents
        """
        with cls._lifecycle_lock:
            live = cls._threads.get(pipeline_id)
            if live is not None and live.is_alive():
                return {"ok": False, "status": "still_running"}
            data = PipelineManager.load(pipeline_id)
            if data is None:
                return {"ok": False, "status": "not_found"}
            if not force:
                deps = cls._dependent_forks(pipeline_id)
                if deps:
                    logger.warning(
                        "[%s] 拒绝删除：仍有 %d 个 fork 依赖其 handoff 目录（%s…）。"
                        "请先删除这些 fork 或 force 删除。",
                        pipeline_id, len(deps), ", ".join(deps[:5]),
                    )
                    return {"ok": False, "status": "has_dependents", "dependents": deps}
            if data.get("status") == "running":
                # 持久化为 running 但本进程无线程 → 孤儿；先按取消语义落盘再删，
                # 这样即使删除中途失败，状态也不会停在 running 误导前端。
                PipelineManager.mark_failed(pipeline_id, "已被用户删除", status="cancelled")
                cls._kill_orphan_research(pipeline_id, data.get("research_pid"))
                # PAR-2：并行研究轨的各子进程 PID 逐一清理（同上，含 pipeline_id 校验）。
                for _tpid in (data.get("options") or {}).get("research_track_pids") or []:
                    cls._kill_orphan_research(pipeline_id, _tpid)
            ok = PipelineManager.delete(pipeline_id)
            if ok:
                cls._cancel_events.pop(pipeline_id, None)
                cls._threads.pop(pipeline_id, None)
                logger.info(f"[{pipeline_id}] 管线记录已删除")
                # W9-10：管线删除后顺带回收陈旧图谱（best-effort，绝不影响删除结果）。
                cls._gc_stale_graphs()
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
    def resume(cls, pipeline_id: str, force: bool = False) -> PipelineState:
        """Resume a failed/cancelled pipeline in place, reusing existing artifacts.

        The pipeline keeps the same id so browser history, artifact paths, and
        local bookmarks remain valid. A fresh task id is assigned for progress
        polling, and the background runner skips completed/recoverable stages.

        ORCH-3 恢复态机收口（此前一天内被迫手工编辑 4 次 pipeline_state.json）：
          * status=running 但 owner 进程确证已死（_orphan_is_dead）→ 就地按取消语义回收后继续
            恢复，不再要求先重启后端触发 reconcile；
          * ``force=True`` 允许恢复一条 completed 但 pipeline_health 为 degraded/failed 的管线：
            仅把 REPORT 阶段重置为 pending（配合 ORCH-1 的损坏报告不复用守卫重生成报告）。
        """
        with cls._lifecycle_lock:
            # 持久化状态可能滞后（崩溃时写失败），线程注册表才是本进程在飞的真相。
            live = cls._threads.get(pipeline_id)
            if live is not None and live.is_alive():
                raise RuntimeError("管线仍在运行，无法恢复")

            data = PipelineManager.load(pipeline_id)
            if data is None:
                raise FileNotFoundError("管线不存在")
            _bad = PipelineManager.is_incompatible(data)  # I-4-4
            if _bad is not None:
                raise IncompatiblePipelineSchema(pipeline_id, _bad)
            if data.get("status") == "running":
                # ORCH-3(a): 无在飞线程 + owner 证据判死 → 就地回收（复用 reconcile 的判据），
                # 让「僵死的 running 孤儿」无需重启后端即可恢复。判活则维持 409。
                _stale_s = float(getattr(Config, "PIPELINE_HEARTBEAT_STALE_S", 120) or 120)
                if cls._orphan_is_dead(pipeline_id, _stale_s):
                    PipelineManager.mark_failed(
                        pipeline_id, "resume 时回收死管线（owner 进程已不存活）", status="cancelled")
                    data = PipelineManager.load(pipeline_id) or data
                    logger.warning("[%s] resume：running 孤儿 owner 已死，就地回收后继续恢复", pipeline_id)
                else:
                    raise RuntimeError("管线仍在运行，无法恢复")
            if data.get("status") == "completed":
                # ORCH-3(b): completed 但交付物健康降级/失败时，允许 force 重驱报告阶段。
                _ph = ((data.get("options") or {}).get("pipeline_health") or {})
                if not (force and _ph.get("status") in ("degraded", "failed")):
                    _degraded_stages = sorted(
                        name for name, st in (_ph.get("stages") or {}).items()
                        if isinstance(st, dict) and st.get("health") in ("degraded", "failed"))
                    if _ph.get("status") not in ("degraded", "failed"):
                        _hint = ""
                    elif _degraded_stages and "report" not in _degraded_stages:
                        # force 只重生成报告：上游阶段（如 RESEARCH-2 的研究降级）的问题它修不了。
                        _hint = ("（降级来自 " + "/".join(_degraded_stages)
                                 + " 阶段；force=true 只会重生成报告，无法修复这些阶段，请重新运行管线）")
                    else:
                        _hint = "（如需重生成降级报告，请带 force=true 重试）"
                    raise RuntimeError("管线已完成，无需恢复" + _hint)

            state = PipelineState.from_dict(data)
            PipelineManager.ensure_dirs(pipeline_id)
            bands = RESEARCH_ONLY_BANDS if state.mode == "research_only" else STAGE_BANDS
            for name in bands.keys():
                state.stages.setdefault(name, StageState(name=name))

            if force and data.get("status") == "completed":
                # 仅重置 REPORT：研究/图谱/模拟产物保持复用。ORCH-1 的复用守卫会因交付物损坏
                # 拒绝复用旧报告并铸新 report_id。
                _rst = state.stages.setdefault(STAGE_REPORT, StageState(name=STAGE_REPORT))
                _reset_stage_attempt(_rst)
                state.current_stage = STAGE_REPORT
                state.options["force_report_regen"] = _utcnow()

            failed_stage = state.current_stage
            if failed_stage and failed_stage in state.stages:
                st = state.stages[failed_stage]
                if st.status in ("failed", "cancelled"):
                    _reset_stage_attempt(st)

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
            # Foglamp WP1 (1B)：WP1 之前准入的管线没有安全政策快照。此类 resume 一律钉入
            # 当前的**安全**收容政策（graph feedback 关 / 单种子 / diagnostic_only），并显式
            # 记录 origin=resume_reconstructed_safe——绝不重建旧的不安全环境语义（把生成活动
            # 写进观察图）；重建出一个不安全政策不等于批准恢复它。已有快照的管线原样保留。
            if not isinstance(state.options.get("safety_policy_v1"), dict):
                state.options["safety_policy_v1"] = capture_safety_policy_v1(
                    "resume_reconstructed_safe")
                logger.warning(
                    "[%s] 该管线早于 Foglamp WP1 准入、无安全政策快照；resume 以安全收容政策"
                    "执行（sim_graph_feedback=%s, n_forecast_seeds=%s, "
                    "simulation_forecast_effect=%s），不重建旧默认。",
                    pipeline_id,
                    state.options["safety_policy_v1"]["sim_graph_feedback"],
                    state.options["safety_policy_v1"]["n_forecast_seeds"],
                    state.options["safety_policy_v1"]["simulation_forecast_effect"],
                )
            # INFRA-7：早于 run-shape 钉准入的管线在首次 resume 时补钉当前形状（origin 标明
            # resume_unpinned——它不是准入时的形状，只是此后漂移检测的基线）。
            if not isinstance(state.options.get("run_shape_v1"), dict):
                cls._pin_run_shape(state, run_shape.ORIGIN_RESUME_UNPINNED)
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

    @classmethod
    def continue_to_full(cls, pipeline_id: str) -> PipelineState:
        """T6.2: 把一条已完成的 research_only 管线继续跑成完整管线（复用研究产物）。

        要求 mode==research_only && status==completed && 存在 research_report.md。翻转
        mode='full'，把完整 STAGE_BANDS 的非研究阶段标记为 pending（研究保持 completed），
        复用 resume() 的启动尾。``_run`` 会经 research_report.md 复用守卫跳过研究、且不再走
        research_only 早退。对 full / running 管线 → RuntimeError（由 API 层转 409）。
        """
        with cls._lifecycle_lock:
            live = cls._threads.get(pipeline_id)
            if live is not None and live.is_alive():
                raise RuntimeError("管线仍在运行，无法继续")

            data = PipelineManager.load(pipeline_id)
            if data is None:
                raise FileNotFoundError("管线不存在")
            _bad = PipelineManager.is_incompatible(data)  # I-4-4
            if _bad is not None:
                raise IncompatiblePipelineSchema(pipeline_id, _bad)
            if data.get("mode") != "research_only":
                raise RuntimeError("仅 research_only 管线可继续为完整管线")
            if data.get("status") != "completed":
                raise RuntimeError("research_only 管线尚未完成，无法继续")

            handoff_dir = PipelineManager.handoff_dir(pipeline_id)
            report_path = os.path.join(handoff_dir, "research_report.md")
            if not (os.path.exists(report_path) and os.path.getsize(report_path) > 0):
                raise RuntimeError("缺少 research_report.md，无法继续（请重跑研究）")

            state = PipelineState.from_dict(data)
            # 翻转为完整模式；研究阶段保持 completed，其余阶段重置为 pending
            state.mode = "full"
            for name in STAGE_BANDS.keys():
                st = state.stages.setdefault(name, StageState(name=name))
                if name == STAGE_RESEARCH:
                    st.status = "completed"
                    if st.progress != 100:
                        st.progress = 100
                else:
                    _reset_stage_attempt(st)

            task_manager = TaskManager()
            task_id = task_manager.create_task(
                task_type="pipeline:full:continue",
                metadata={"pipeline_id": pipeline_id, "continued_from_task_id": state.task_id},
            )
            state.task_id = task_id
            state.status = "running"
            state.error = None
            state.current_stage = STAGE_ONTOLOGY
            state.options["continued_to_full_at"] = _utcnow()
            # INFRA-7：继续为完整管线与 resume 同理——未钉形状的旧管线补钉基线。
            if not isinstance(state.options.get("run_shape_v1"), dict):
                cls._pin_run_shape(state, run_shape.ORIGIN_RESUME_UNPINNED)
            PipelineManager.save(state)

            cls._cancel_events[pipeline_id] = threading.Event()
            t = threading.Thread(
                target=cls._run,
                args=(state,),
                name=f"pipeline-continue-{pipeline_id}",
                daemon=True,
            )
            cls._threads[pipeline_id] = t
            t.start()
            logger.info(f"[{pipeline_id}] research_only → full 继续，复用研究产物")
            return state

    @classmethod
    def fork(cls, base_pipeline_id: str, overlay: dict[str, Any]) -> PipelineState:
        """T4.6: 在 PREPARE 处分叉一个 what-if 情景管线（复用 base 的研究/本体/图谱）。

        overlay = {label, max_rounds?, influence_overrides{name:weight}, stance_overrides{name:stance},
                   injected_events[{round,poster_name,content}], as_of_shift?}。新管线复用 base 的
        project_id/graph_id/handoff（研究+本体+图谱直接命中复用守卫），仅重跑 prepare/run/report。
        要求 base 已完成图谱阶段。返回新建管线状态。
        """
        base = PipelineManager.load(base_pipeline_id)
        if base is None:
            raise FileNotFoundError("基础管线不存在")
        _bad = PipelineManager.is_incompatible(base)  # I-4-4
        if _bad is not None:
            raise IncompatiblePipelineSchema(base_pipeline_id, _bad)
        base_state = PipelineState.from_dict(base)
        if not base_state.graph_id:
            raise RuntimeError("基础管线尚未建图，无法分叉情景")

        label = str((overlay or {}).get("label") or "情景").strip()
        new_id = f"pipe_{uuid.uuid4().hex[:12]}"
        new_state = PipelineState(
            pipeline_id=new_id,
            prompt=base_state.prompt,
            mode="full",
            project_id=base_state.project_id,
            graph_id=base_state.graph_id,
            handoff_dir=base_state.handoff_dir or PipelineManager.handoff_dir(base_pipeline_id),
        )
        # 研究/本体/图谱标记完成 → 命中复用守卫；prepare/run/report 全新
        for name in STAGE_BANDS.keys():
            st = StageState(name=name)
            if name in (STAGE_RESEARCH, STAGE_ONTOLOGY, STAGE_GRAPH):
                st.status = "completed"
                st.progress = 100
            new_state.stages[name] = st
        new_state.options = {
            "scenario_overlay": overlay or {},
            "scenario_label": label,
            "base_pipeline_id": base_pipeline_id,
            "project_name": base_state.options.get("project_name"),
        }
        _actor_policy = base_state.options.get("actor_intelligence_policy_v1")
        if isinstance(_actor_policy, dict):
            # Scenario forks consume the base research generation.  Preserve
            # the base run's exact actor requirement instead of consulting
            # today's ambient dual-track flag.
            new_state.options["actor_intelligence_policy_v1"] = dict(_actor_policy)
        # INFRA-9：分叉沿用 base 的安全政策钉（base 无钉则按分叉准入捕获）；旋钮关闭 = 不写（旧行为）。
        _safety_policy = fork_safety_policy_v1(base_state.options)
        if _safety_policy is not None:
            new_state.options["safety_policy_v1"] = _safety_policy
            warn_if_fork_feeds_shared_graph(_safety_policy, fork_id=new_id,
                                            base_pipeline_id=base_pipeline_id,
                                            graph_id=base_state.graph_id)
        _evaluation_pin = cls._evaluation_pin(base_state)
        if _evaluation_pin is not None:
            # EVAL-13: a what-if fork of an evaluation run stays in the evaluation lane
            # (the admission pin is carried, never re-captured; the fork shares the base's
            # handoff dir, whose marker names the base, so the pin must travel in options).
            new_state.options[EVALUATION_RUN_OPTION] = _evaluation_pin
        _hindcast_pin = base_state.options.get(HINDCAST_POLICY_OPTION)
        if isinstance(_hindcast_pin, dict):
            # TIME-6: a what-if fork reuses the base's as-of research, so it keeps the base's
            # hindcast pin (carried, never re-captured) and its reports withhold live markets too.
            new_state.options[HINDCAST_POLICY_OPTION] = dict(_hindcast_pin)
        if (overlay or {}).get("max_rounds"):
            try:
                new_state.options["max_rounds"] = int(overlay["max_rounds"])
            except (TypeError, ValueError):
                pass
        # INFRA-7：情景分叉是新准入——按分叉时刻的环境钉形状（origin=fork），并记下 base 的钉
        # （复用的研究/本体/图谱是在 base 的形状下建的）。
        cls._pin_run_shape(new_state, run_shape.ORIGIN_FORK, base_state=base_state)

        PipelineManager.ensure_dirs(new_id)
        task_manager = TaskManager()
        task_id = task_manager.create_task(
            task_type="pipeline:full:scenario",
            metadata={"pipeline_id": new_id, "base_pipeline_id": base_pipeline_id, "label": label},
        )
        new_state.task_id = task_id
        new_state.status = "running"
        new_state.current_stage = STAGE_PREPARE
        PipelineManager.save(new_state)

        with cls._lifecycle_lock:
            cls._cancel_events[new_id] = threading.Event()
            t = threading.Thread(target=cls._run, args=(new_state,), name=f"pipeline-scenario-{new_id}", daemon=True)
            cls._threads[new_id] = t
            t.start()
        logger.info(f"[{new_id}] 情景分叉自 {base_pipeline_id}（label={label}），复用图谱 {base_state.graph_id}")
        return new_state

    @staticmethod
    def apply_scenario_overlay_to_config(config: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        """T4.6: 把情景 overlay 确定性地落到已生成的 simulation_config 上（就地修改并返回）。

        influence_overrides{name:weight} / stance_overrides{name:stance} 按 agent 名匹配覆盖
        （两路都覆盖，闭合 T3.6 旁路）；injected_events 追加为 scheduled_events（解析 poster_name
        → agent_id）；不破坏缺省字段。
        """
        from ..utils.actors import normalize_name
        agents = config.get("agent_configs") or []
        by_name = {normalize_name(a.get("entity_name", "")): a for a in agents if a.get("entity_name")}

        inf = (overlay or {}).get("influence_overrides") or {}
        for name, weight in inf.items():
            a = by_name.get(normalize_name(str(name)))
            if a is not None:
                try:
                    a["influence_weight"] = float(weight)
                except (TypeError, ValueError):
                    pass
        stc = (overlay or {}).get("stance_overrides") or {}
        for name, stance in stc.items():
            a = by_name.get(normalize_name(str(name)))
            if a is not None:
                a["stance"] = str(stance)

        injected = (overlay or {}).get("injected_events") or []
        if injected:
            ec = config.setdefault("event_config", {})
            sched = ec.setdefault("scheduled_events", [])
            # CAL：配置带 temporal_config（日历模式）时按日期精确装桶（round_for_date），
            # 与 key_events 同一套定位；无 temporal_config → 旧行为逐字节不变。
            _tc = config.get("temporal_config")
            _cal_rounds = (_tc.get("round_dates") or []) if (
                isinstance(_tc, dict) and _tc.get("mode") == "calendar") else None
            if _cal_rounds:
                from ..utils import sim_timeline
            # 影响力最高 agent 作兜底发布者
            fallback = max(agents, key=lambda x: x.get("influence_weight", 1.0), default=None)
            fb_id = fallback.get("agent_id") if fallback else 0
            fb_name = fallback.get("entity_name") if fallback else ""
            existing_injection_counts: dict[str, int] = {}
            for existing in sched:
                if not isinstance(existing, dict) or not existing.get(
                    "is_scenario_injection"
                ):
                    continue
                key = json.dumps(
                    existing,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                existing_injection_counts[key] = (
                    existing_injection_counts.get(key, 0) + 1
                )
            requested_injection_counts: dict[str, int] = {}
            for ev in injected:
                poster_name = str(ev.get("poster_name", "") or "").strip()
                a = by_name.get(normalize_name(poster_name)) if poster_name else None
                _round = int(ev.get("round", 0) or 0)
                if _cal_rounds:
                    _d = parse_as_of(ev.get("date"))
                    if _d is None:
                        _round = 0  # 无日期 → 第 0 轮起手注入
                        logger.warning("注入事件无可解析日期，落到第 0 轮: %r",
                                       str(ev.get("content") or "")[:60])
                    else:
                        _r = sim_timeline.round_for_date(_d.date(), _cal_rounds)
                        _last_end = parse_as_of(_cal_rounds[-1].get("period_end"))
                        if _r is not None:
                            _round = _r
                        elif _last_end is not None and _d.date() > _last_end.date():
                            _round = len(_cal_rounds) - 1  # 超出判定日 → 钳到最后一轮
                            logger.warning("注入事件日期 %s 超出判定日，钳到最后一轮", ev.get("date"))
                        else:
                            _round = 0  # 早于 as_of → 起手轮
                            logger.warning("注入事件日期 %s 早于 as_of，落到第 0 轮", ev.get("date"))
                event_row = {
                    "round": _round,
                    "content": str(ev.get("content", "") or ""),
                    "date": ev.get("date"),
                    "poster_agent_id": a.get("agent_id") if a else fb_id,
                    "poster_name": a.get("entity_name") if a else fb_name,
                    "is_scenario_injection": True,
                }
                event_key = json.dumps(
                    event_row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                requested_injection_counts[event_key] = (
                    requested_injection_counts.get(event_key, 0) + 1
                )
                # Reapplying PREPARE after a corrupt RUN must reconstruct the
                # same desired overlay, not append another copy. Preserve an
                # intentional duplicate within the overlay by matching counts.
                if existing_injection_counts.get(event_key, 0) >= (
                    requested_injection_counts[event_key]
                ):
                    continue
                sched.append(event_row)
                existing_injection_counts[event_key] = (
                    existing_injection_counts.get(event_key, 0) + 1
                )
        return config

    # -- NEXTSTEPS P0-3: 同问多种子集成 -----------------------------------
    @staticmethod
    def _infer_horizon_date(prompt: Any, actors: Any) -> Optional[str]:
        """NEXTSTEPS P1-2 / CAL：从问题/central_question 解析判定日 → 'YYYY-MM-DD'。

        委托 sim_timeline.extract_horizon 的四层确定性抽取（explicit_date/anchored_period/
        relative/bare_year——bare_year 层即旧实现，行为超集）。as_of 取 actors.as_of_date
        （不可解析→今天）。无合法候选 → None（不做日期映射）；任何异常回退旧的裸年份正则。
        """
        text = str(prompt or "")
        if isinstance(actors, dict):
            text += "\n" + str(actors.get("central_question") or "")
        try:
            from datetime import date as _date
            from ..utils import sim_timeline
            as_of = None
            if isinstance(actors, dict):
                parsed = parse_as_of(actors.get("as_of_date"))
                as_of = parsed.date() if parsed else None
            hr = sim_timeline.extract_horizon(text, as_of or _date.today())
            return hr.horizon_date if hr else None
        except Exception:  # noqa: BLE001 — degrade-safe：模块缺失/异常时保持旧行为
            # 数字边界（非 \b：\b 在中日韩字符旁不触发，"2027年" 取不到年份）。
            years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", text)]
            if not years:
                return None
            return f"{max(years)}-12-31"

    @staticmethod
    def _agreement_to_confidence(agreement: Any) -> str:
        """把 inter-seed 一致度 ∈[0,1] 映射为报告信心（高一致=high）。无效值→medium。"""
        try:
            a = float(agreement)
        except (TypeError, ValueError):
            return "medium"
        if a >= 0.75:
            return "high"
        if a >= 0.45:
            return "medium"
        return "low"

    @staticmethod
    def _read_report_forecast(report_id: Optional[str]) -> Optional[dict]:
        """读取某报告目录下的 forecast.json（不存在/损坏→None）。"""
        if not report_id:
            return None
        try:
            from .report_agent import ReportManager
            fpath = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:  # noqa: BLE001 — 读不到就当无集成样本
            return None
        return None

    @staticmethod
    def _pinned_safety(state: "PipelineState", key: str, default: Any) -> Any:
        """Foglamp WP1 (1B): read a containment-relevant flag from the run's pinned
        ``safety_policy_v1`` snapshot, falling back to ``default`` (the ambient —
        now safe — Config value) when the pin or the key is absent. A run must
        never silently change safety semantics on service reload."""
        try:
            pol = (state.options or {}).get("safety_policy_v1") or {}
            v = pol.get(key)
            return default if v is None else v
        except Exception:  # noqa: BLE001 — 安全政策读取绝不让管线崩溃；回退环境值
            return default

    @classmethod
    def _backbone_check_policy(cls, state: "PipelineState") -> Optional[dict[str, Any]]:
        """EVAL-11: the main report's shadow backbone-check policy from the run's pin, or None.

        Read from ``safety_policy_v1['backbone_check']`` with no ambient fallback: a run
        admitted before the key existed, a legacy resume and a fork without a pin all stay
        disabled, whatever BACKBONE_CHECK_ENABLED says now.
        """
        return backbone_sensitivity.enabled_policy(
            cls._pinned_safety(state, "backbone_check", None))

    # -- INFRA-7: run-shape pin, drift detection and resume lineage guards ----

    @staticmethod
    def _pin_run_shape(state: "PipelineState", origin: str, *,
                       base_state: Optional["PipelineState"] = None) -> None:
        """Store ``options['run_shape_v1']`` when RUN_SHAPE_PIN is on.

        A fork passes ``base_state``: its pin then records the base's pin
        under ``fork_base`` (sha256 plus the identity knobs that differ), since
        the fork reuses upstream artifacts built under the base's shape.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        shape = capture_run_shape_v1(state.options, origin)
        if shape is None:
            return
        if base_state is not None:
            base_options = base_state.options if isinstance(base_state.options, dict) else {}
            shape["fork_base"] = run_shape.fork_base_record(
                base_options.get("run_shape_v1"), shape, base_state.pipeline_id)
        state.options["run_shape_v1"] = shape

    @staticmethod
    def _run_shape_drift(state: "PipelineState") -> Optional[dict[str, Any]]:
        """Diff the run's pinned shape against the ambient config (None if unpinned)."""
        pinned = (state.options or {}).get("run_shape_v1")
        if not isinstance(pinned, dict):
            return None
        current = run_shape.capture(
            Config, state.options, research_engine=research_engine_for_run(state.options))
        return run_shape.diff(pinned, current)

    def _check_run_shape_drift(self, state: "PipelineState") -> None:
        """INFRA-7: record admission-shape drift for this attempt; refuse on policy.

        ``record`` (default) discloses the drift in ``options.run_shape_drift``
        (+ a capped history) and continues; ``refuse`` fails the attempt naming
        the changed identity knobs.  Provenance-only drift never refuses.
        ``run_shape_drift`` keeps the latest non-empty drift: a later attempt
        run under the restored admission shape does not erase it, because the
        stages completed under the drifted shape are still part of the run.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        raw_policy = getattr(Config, "RUN_SHAPE_DRIFT_POLICY", run_shape.DRIFT_POLICY_RECORD)
        policy, valid = run_shape.resolve_drift_policy(raw_policy)
        if not valid:
            logger.warning(
                "[%s] RUN_SHAPE_DRIFT_POLICY=%r 未知（可选 record | refuse）——按 record 处理",
                state.pipeline_id, str(raw_policy)[:64],
            )
        try:
            drift = self._run_shape_drift(state)
        except Exception as exc:  # noqa: BLE001 — refuse 下无法证明未漂移即拒绝
            if policy == run_shape.DRIFT_POLICY_REFUSE:
                raise RuntimeError(
                    "run-shape drift check failed under RUN_SHAPE_DRIFT_POLICY=refuse: "
                    f"{exc}") from exc
            logger.warning("[%s] run-shape 漂移检测跳过: %s", state.pipeline_id, exc)
            return
        if not run_shape.has_drift(drift):
            return
        state.options["run_shape_drift"] = drift
        state.options["run_shape_drift_history"] = run_shape.append_capped(
            state.options.get("run_shape_drift_history"),
            {"at": _utcnow(), "policy": policy, **drift},
            run_shape.DRIFT_HISTORY_CAP,
        )
        PipelineManager.save(state)
        if run_shape.refuses(policy, drift):
            raise RuntimeError(run_shape.refusal_message(drift))
        logger.warning(
            "[%s] 运行形状自准入以来已漂移（已记录，继续执行）: %s",
            state.pipeline_id, ", ".join(run_shape.drifted_knobs(drift)),
        )

    def _attempt_recomputed(self) -> set[str]:
        """Stages recomputed this attempt (lazily created for bare instances)."""
        recomputed = getattr(self, "_recomputed_this_attempt", None)
        if recomputed is None:
            recomputed = set()
            self._recomputed_this_attempt = recomputed
        return recomputed

    def _attempt_sim_runtime(self) -> dict[str, Any]:
        """Simulation runtime fields this attempt's RUN wrote to run.json (lazy)."""
        runtime = getattr(self, "_sim_runtime_this_attempt", None)
        if runtime is None:
            runtime = {}
            self._sim_runtime_this_attempt = runtime
        return runtime

    def _lineage_refuses_reuse(
        self,
        state: "PipelineState",
        stage: str,
        *,
        bound_ids: Optional[tuple[Any, Any]] = None,
        exempt: tuple[str, ...] = (),
        artifact_id: Any = None,
    ) -> Optional[str]:
        """INFRA-7 resume lineage guard: the refusal reason when ``stage`` must recompute.

        Consults this attempt's recomputes and the durable
        ``options.lineage_invalidated`` map, so a stage made stale by an earlier
        attempt whose rebuild failed is still refused.  ``artifact_id`` names
        the candidate artifact (REPORT: its report_id, passed only for a
        COMPLETED report, so an unfinished minted report is never exempt);
        when it is the one ``options.lineage_rebuilt`` records for the stage, the durable entry
        does not refuse it (a rebuild from current inputs cut off before the
        stage completed).  A refusal is recorded in the invalidated map and
        leaves a ``reuse_refused: <reason>`` note under
        ``options.stage_notes[stage]`` (a per-stage list, so it never clobbers
        the single-valued ``resumed_stage_validation`` breadcrumb that names
        the upstream cause); the caller then falls through to its rebuild
        branch.  None = reuse may proceed (always None with
        RESUME_LINEAGE_GUARDS off).
        """
        if not bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True)):
            return None
        invalidated = state.options.get(run_shape.LINEAGE_INVALIDATED_OPTION)
        invalidated = dict(invalidated) if isinstance(invalidated, dict) else {}
        reason = run_shape.lineage_refusal(
            stage, self._attempt_recomputed(), bound_ids=bound_ids, exempt=exempt,
            invalidated=invalidated, artifact_id=artifact_id,
            rebuilt=state.options.get(run_shape.LINEAGE_REBUILT_OPTION))
        if reason is None:
            return None
        invalidated.setdefault(stage, reason)
        state.options[run_shape.LINEAGE_INVALIDATED_OPTION] = invalidated
        notes = state.options.get("stage_notes")
        notes = dict(notes) if isinstance(notes, dict) else {}
        notes[stage] = run_shape.append_capped(
            notes.get(stage), f"reuse_refused: {reason}", run_shape.STAGE_NOTES_CAP)
        state.options["stage_notes"] = notes
        logger.warning(
            "[%s] %s 阶段拒绝复用（%s）：上游已变化（本 attempt 或此前未完成重建的 attempt），"
            "重算以免复用陈旧产物",
            state.pipeline_id, stage, reason,
        )
        return reason

    def _forbid_shared_fork_rebuild(
        self, state: "PipelineState", stage: str, project: Any, reason: str,
    ) -> None:
        """INFRA-7: fail closed instead of rebuilding a fork's shared artifacts in place.

        A scenario fork (``fork``) runs on its base pipeline's project record.
        When a lineage guard refuses its ontology/graph reuse, the rebuild would
        overwrite ``project.ontology`` / ``project.graph_id`` that the base (and
        sibling forks) still use.  Every fork (scenario and batch question)
        also works in the base's handoff directory, where a graph rebuild writes
        communities.json, entity_merges.json, graph_prune.json and the graph
        priors that the base's artifact manifest seals.  In either case the
        attempt fails naming the base instead.  A fork that owns its project
        still regenerates its ontology (a batch question fork does so by
        design).
        """
        base_pid = (state.options or {}).get("base_pipeline_id")
        if not base_pid:
            return
        shared: list[str] = []
        project_id = getattr(project, "project_id", None)
        if project_id:
            try:
                base = PipelineManager.load(str(base_pid))
            except Exception:  # noqa: BLE001 — an unreadable base cannot prove the project is ours
                base = None
            if isinstance(base, dict):
                project_shared = base.get("project_id") == project_id
            else:
                # Base record gone or unreadable: scenario forks share the base
                # project by construction, so treat them as shared.
                project_shared = "scenario_overlay" in (state.options or {})
            if project_shared:
                shared.append(f"project {project_id}")
        if stage == STAGE_GRAPH:
            own_handoff = PipelineManager.handoff_dir(state.pipeline_id)
            handoff = state.handoff_dir or own_handoff
            if os.path.realpath(handoff) != os.path.realpath(own_handoff):
                shared.append(f"handoff dir {handoff}")
        if not shared:
            return
        raise RuntimeError(
            f"resume lineage guard: the {stage} artifact of fork {state.pipeline_id} must be "
            f"rebuilt ({reason}), but its {' and '.join(shared)} "
            f"{'are' if len(shared) > 1 else 'is'} shared with base pipeline "
            f"{base_pid}; refusing to overwrite the base's {stage} artifacts in place. Fork "
            "again from a healthy base, or set RESUME_LINEAGE_GUARDS=false to reuse the "
            "shared artifacts knowingly."
        )

    @staticmethod
    def _store_lineage_map(state: "PipelineState", key: str, value: dict[str, str]) -> None:
        """Write a durable lineage map into ``state.options``; drop the key when empty."""
        if value:
            state.options[key] = value
        else:
            state.options.pop(key, None)

    def _record_stage_lineage(self, state: "PipelineState", stage: str, reused: bool) -> None:
        """INFRA-7: remember a recompute (or a settled rebuild) for the lineage guards.

        A recompute adds ``stage`` to this attempt's recomputed set and, with
        the guards on, updates the durable maps: the stage's own
        ``lineage_invalidated`` / ``lineage_rebuilt`` entries are cleared
        (rebuilt from current inputs), every guarded downstream stage is marked
        stale and loses its rebuilt artifact.  A reuse settles the stage's
        interrupted rebuild when the reused artifact is the rebuilt one.  The
        maps are saved with the stage's completion, so the invalidation
        survives a failed downstream rebuild.  With the guards off a recompute
        still drops the rebuilt artifacts it made stale (a map only a guards-on
        attempt wrote), so a later guards-on attempt cannot exempt an artifact
        built before this recompute; nothing else is touched.  Pure in-memory
        bookkeeping; the caller does not swallow its errors (the guard is an
        honesty check and fails closed).
        """
        guards = bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True))
        invalidated = state.options.get(run_shape.LINEAGE_INVALIDATED_OPTION)
        rebuilt = state.options.get(run_shape.LINEAGE_REBUILT_OPTION)
        if reused:
            if guards:
                invalidated, rebuilt = run_shape.settle_reused_rebuild(invalidated, rebuilt, stage)
                self._store_lineage_map(state, run_shape.LINEAGE_INVALIDATED_OPTION, invalidated)
                self._store_lineage_map(state, run_shape.LINEAGE_REBUILT_OPTION, rebuilt)
            return
        self._attempt_recomputed().add(stage)
        exemptions = run_shape.lineage_exemptions(state.options)
        if not guards:
            if run_shape.LINEAGE_REBUILT_OPTION in state.options:
                self._store_lineage_map(
                    state, run_shape.LINEAGE_REBUILT_OPTION,
                    run_shape.settle_rebuilt(rebuilt, stage, exemptions=exemptions))
            return
        self._store_lineage_map(
            state, run_shape.LINEAGE_INVALIDATED_OPTION,
            run_shape.invalidate_downstream(invalidated, stage, exemptions=exemptions))
        self._store_lineage_map(
            state, run_shape.LINEAGE_REBUILT_OPTION,
            run_shape.settle_rebuilt(rebuilt, stage, exemptions=exemptions))

    def _record_lineage_artifact_replaced(self, state: "PipelineState", stage: str) -> None:
        """INFRA-7: ``stage``'s artifact was just overwritten from current inputs.

        ONTOLOGY reuse is keyed on ``project.ontology`` being present, not on
        the stage bit, so its lineage bookkeeping cannot wait for
        ``_complete_stage``: an attempt cut off in between would keep the
        invalidation and refuse the fresh ontology on the next resume.  The
        recompute is recorded (and persisted) as soon as the artifact is
        saved; ``_complete_stage`` repeats it idempotently.  A crash before
        this save only costs a redundant rebuild.  With the guards off only an
        existing ``lineage_rebuilt`` map is settled (see ``_record_stage_lineage``).
        """
        if (not bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True))
                and run_shape.LINEAGE_REBUILT_OPTION not in state.options):
            return
        self._record_stage_lineage(state, stage, reused=False)
        PipelineManager.save(state)

    @staticmethod
    def _record_lineage_rebuild_started(state: "PipelineState", stage: str,
                                        artifact_id: str) -> None:
        """INFRA-7: an invalidated ``stage`` starts building ``artifact_id`` from current inputs.

        REPORT reuse is keyed on a persisted report, not on the stage bit: a
        report minted and published after the upstream recompute, whose
        attempt ended before ``_complete_stage`` (a cancel or outage halt
        raised from its final progress callback, a restart), must be reused on
        the next resume rather than regenerated under a new id.  The minted id
        goes into ``options.lineage_rebuilt``; any other report of the stage
        (such as the stale one the simulation-id fallback lookup would find
        when the minted report never reached disk) is still refused.  The
        caller persists the state together with the minted id.
        """
        if not bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True)):
            return
        PipelineOrchestrator._store_lineage_map(
            state, run_shape.LINEAGE_REBUILT_OPTION,
            run_shape.mark_rebuilt(
                state.options.get(run_shape.LINEAGE_INVALIDATED_OPTION),
                state.options.get(run_shape.LINEAGE_REBUILT_OPTION),
                stage, artifact_id))

    def _record_stage_decision(self, state: "PipelineState", stage: str, reused: bool) -> None:
        """INFRA-7: typed reuse fact per stage + run.json provider stamp on recompute.

        A reused REPORT whose mint is still pending (``options.report_producer_v1``,
        written when an earlier attempt minted it) is stamped with the recorded
        producer; the record is dropped once REPORT completes either way.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        record = {"stage": stage, "reused": bool(reused), "at": _utcnow()}
        state.options["stage_reuse_v1"] = run_shape.append_capped(
            state.options.get("stage_reuse_v1"), record, run_shape.STAGE_REUSE_LOG_CAP)
        attempt_records = getattr(self, "_stage_reuse_this_attempt", None)
        if attempt_records is None:
            attempt_records = []
            self._stage_reuse_this_attempt = attempt_records
        attempt_records.append(dict(record))
        if not reused:
            self._stamp_run_manifest_stage(state, stage)
        elif stage == STAGE_REPORT:
            stamp = run_shape.reused_report_stamp(
                state.options.get(run_shape.REPORT_PRODUCER_OPTION), state.report_id)
            if stamp is not None:
                self._stamp_run_manifest_stage(state, stage, provider=stamp)
        if stage == STAGE_REPORT:
            state.options.pop(run_shape.REPORT_PRODUCER_OPTION, None)

    def _record_report_mint(self, state: "PipelineState", report_id: str) -> None:
        """INFRA-7: remember who produces a newly minted report (caller saves the state).

        Stored with the minted report_id in the same state save, so a later
        attempt that reuses this report (published, but its attempt ended
        before ``_complete_stage``) can stamp run.json with its real producer.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        state.options[run_shape.REPORT_PRODUCER_OPTION] = run_shape.producer_record(
            report_id, _current_provider_pair())

    def _stamp_produced_artifact(self, state: "PipelineState", stage: str) -> None:
        """INFRA-7: restamp run.json as soon as ``stage`` starts or finishes producing
        an artifact whose reuse is keyed on the persisted artifact, not on the stage bit.

        ONTOLOGY (after ``save_project``) and REPORT (after the minted id is
        saved) can be reused by an attempt that never reached their
        ``_complete_stage`` restamp; without this, run.json would keep naming
        the replaced artifact's producer (or none on a fresh run).  REPORT
        uses the pair recorded at the mint.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        provider = None
        if stage == STAGE_REPORT:
            provider = run_shape.reused_report_stamp(
                state.options.get(run_shape.REPORT_PRODUCER_OPTION), state.report_id)
        self._stamp_run_manifest_stage(state, stage, provider=provider)

    def _reset_run_manifest_simulation(self, state: "PipelineState") -> None:
        """INFRA-7: RUN re-executes, so run.json's simulation block restarts fresh.

        The carried-forward block describes the simulation being replaced; while
        the new run is in flight (or after it fails) run.json must not present
        those values as this run's.  ``_update_manifest`` then adds the runtime
        fields this attempt's RUN writes.
        """
        if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
            return
        self._stamp_run_manifest_stage(state, STAGE_RUN)

    def _stamp_run_manifest_stage(self, state: "PipelineState", stage: str, *,
                                  provider: Optional[dict[str, Any]] = None) -> None:
        """Restamp the run.json ``resolved`` block of a stage recomputed this attempt.

        Reused stages keep the stamp carried forward from the attempt that
        produced them.  ``provider`` overrides the current provider pair for a
        provider-stamped stage (the recorded producer of a reused report).  A
        missing run.json is left missing (the attempt-start writer owns
        creating it); any failure is swallowed like every other run.json
        writer.
        """
        if not bool(getattr(Config, "RECORD_RUN_MANIFEST", True)):
            return
        if stage not in run_shape.RESOLVED_BLOCK_FOR_STAGE:
            return
        try:
            from ..utils.security import redact_secrets
            from ..utils.atomic import write_json_atomic
            path = PipelineManager.manifest_path(state.pipeline_id)
            manifest = _read_json(path)
            if not isinstance(manifest, dict):
                return
            fresh = getattr(self, "_fresh_resolved", None)
            if fresh is None:
                fresh = _build_run_manifest(state).get("resolved") or {}
            resolved = manifest.get("resolved")
            resolved = resolved if isinstance(resolved, dict) else {}
            run_shape.stamp_resolved_stage(
                resolved, stage, fresh=fresh,
                provider=provider if provider is not None else _current_provider_pair(),
                sim_runtime=self._attempt_sim_runtime())
            manifest["resolved"] = resolved
            manifest["updated_at"] = _utcnow()
            write_json_atomic(path, redact_secrets(manifest))
        except Exception as e:  # noqa: BLE001 — 清单是观测产物，写失败必须静默降级
            logger.debug("[%s] run.json 阶段戳跳过: %s", state.pipeline_id, e)

    def _stage_model_record(self, state: "PipelineState", stage: str) -> dict[str, Any]:
        """INFRA-8: the model provenance of ``stage`` as recomputed by this attempt.

        RESEARCH: the resolved model id and served ids of this attempt's research child
        (``_record_research_telemetry``; None / [] when it reported none). RUN: the
        simulation child's own record (:meth:`_sim_model_record`). Every other stage: the
        requested labels and served ids this attempt's LLMMeter recorded for the stage
        (model_provenance.stage_record: tier routing and failover included), falling back to
        the current provider pair (the pair INFRA-7 stamps) when the stage made no call.
        """
        if stage == STAGE_RESEARCH:
            record = getattr(self, "_research_model_provenance", None)
            return dict(record) if isinstance(record, dict) else model_provenance.research_stage_record(None)
        if stage == STAGE_RUN:
            return self._sim_model_record(state)
        pair = _current_provider_pair()
        from ..utils.telemetry import LLMMeter
        resolution = LLMMeter.snapshot(state.pipeline_id).get("model_resolution")
        return model_provenance.stage_record(
            model_provenance.resolution_entries(resolution, stage),
            pair.get("provider"), pair.get("model_name"))

    @staticmethod
    def _sim_model_record(state: "PipelineState") -> dict[str, Any]:
        """INFRA-8: RUN's requested labels and served ids from the simulation child.

        The child records them per call (sim_llm_telemetry.json ``model_resolution``, stashed
        in ``options.sim_llm_telemetry``): the direct camel calls with the id the provider
        reported, and every LLMClient call (CLI bridge, failover, decision channel) with its
        own requested label and served id. Without that record (a child that predates it)
        the requested label is the effective label of the simulation provider and the model
        oasis_llm sends (LLM_MODEL_NAME), with no served ids. The telemetry's ``model`` is
        never used: it is the dominant by_model key, i.e. a served id or, for the CLI bridge,
        the provider name.
        """
        from ..utils.llm_client import CLI_PROVIDERS, OPENAI_COMPATIBLE_PROVIDERS
        pair = _current_provider_pair()
        sim_tel = state.options.get("sim_llm_telemetry")
        sim_tel = sim_tel if isinstance(sim_tel, dict) else {}
        provider = sim_tel.get("provider")
        if provider not in (*CLI_PROVIDERS, *OPENAI_COMPATIBLE_PROVIDERS):
            # Missing, or the pricing key _record_sim_run_telemetry guessed from the model.
            provider = pair.get("provider")
        return model_provenance.stage_record(
            sim_tel.get("model_resolution"), provider, pair.get("model_name"))

    def _reused_stage_model_record(self, state: "PipelineState", stage: str,
                                   block: dict[str, Any]) -> Optional[dict[str, Any]]:
        """INFRA-8: the model keys to merge into a reused stage's block that lacks them.

        A block the attempt that produced the stage stamped keeps its keys (None). A reused
        ONTOLOGY / GRAPH / REPORT restamped by INFRA-7 without a recomputing completion (the
        early ONTOLOGY stamp after save_project, a pending report mint) gets the effective
        label of its stamped pair with unknown served ids; only with RUN_SHAPE_PIN on, since
        the legacy stage-entry stamp names the current provider, not the producer. A reused
        RUN gets the simulation child's own record when the stash holds one. Other stages
        stay as carried forward.
        """
        if "requested_model" in block:
            return None
        if stage in run_shape.PROVIDER_STAMPED_STAGES:
            if not bool(getattr(Config, "RUN_SHAPE_PIN", True)):
                return None
            return model_provenance.reused_stage_record(block)
        if stage == STAGE_RUN:
            sim_tel = state.options.get("sim_llm_telemetry")
            if isinstance(sim_tel, dict) and sim_tel.get("model_resolution"):
                return self._sim_model_record(state)
        return None

    def _stamp_stage_model_provenance(self, state: "PipelineState", stage: str, *,
                                      reused: bool = False) -> None:
        """INFRA-8: merge a stage's requested and served models into its run.json
        ``resolved`` block (RUN's block is ``simulation``; PREPARE gets a ``prepare`` block).

        A recomputed stage merges this attempt's record after INFRA-7's restamp, so its
        provider/model_name keys stay. A reused stage keeps the carried-forward stamp of the
        attempt that produced it, and only a block lacking the keys is filled in
        (:meth:`_reused_stage_model_record`). A missing run.json is left missing; failures
        propagate to ``_complete_stage``, which logs and continues.
        """
        if not (bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True))
                and bool(getattr(Config, "RECORD_RUN_MANIFEST", True))):
            return
        block_name = model_provenance.RESOLVED_BLOCK_FOR_STAGE.get(stage)
        if block_name is None:
            return
        from ..utils.security import redact_secrets
        from ..utils.atomic import write_json_atomic
        path = PipelineManager.manifest_path(state.pipeline_id)
        manifest = _read_json(path)
        if not isinstance(manifest, dict):
            return
        resolved = manifest.get("resolved")
        resolved = resolved if isinstance(resolved, dict) else {}
        block = resolved.get(block_name)
        block = dict(block) if isinstance(block, dict) else {}
        record = (self._reused_stage_model_record(state, stage, block) if reused
                  else self._stage_model_record(state, stage))
        if record is None:
            return
        block.update(record)
        resolved[block_name] = block
        manifest["resolved"] = resolved
        manifest["updated_at"] = _utcnow()
        write_json_atomic(path, redact_secrets(manifest))

    def _assign_run_provenance(self, agent: Any, state: "PipelineState") -> None:
        """INFRA-8: hand the report stage's ReportAgent the upstream model provenance.

        ``agent.run_provenance`` (model-provenance/v1) holds the model keys of run.json's
        research / ontology / graph / prepare / run blocks and the latest recorded run-shape
        drift (``options.run_shape_drift``, kept across attempts by INFRA-7, so it may come
        from an earlier attempt); ReportAgent adds the report stage itself and writes the
        block into forecast.json. Unset (key omitted) with RECORD_MODEL_PROVENANCE off;
        stages is empty when run.json is not recorded. Degrades to unset on any failure.
        """
        if not bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True)):
            return
        try:
            manifest = (_read_json(PipelineManager.manifest_path(state.pipeline_id))
                        if bool(getattr(Config, "RECORD_RUN_MANIFEST", True)) else None)
            resolved = manifest.get("resolved") if isinstance(manifest, dict) else None
            agent.run_provenance = model_provenance.run_provenance(
                resolved, state.options.get("run_shape_drift"))
        except Exception as exc:  # noqa: BLE001 — 出处是观测增益，绝不阻断报告
            logger.debug("[%s] run_provenance 跳过: %s", state.pipeline_id, exc)

    def _maybe_run_seed_ensemble(self, state: "PipelineState", project: Any, graph_id: Optional[str],
                                 actors: Any, research: dict, report_md: str) -> None:
        """NEXTSTEPS P0-3: 同问多种子集成。

        对**同一张图谱**用不同 SIM_SEED 多跑 (prepare→run→report)，收集每次的 forecast.json
        （含主跑），聚合为 ensemble_forecast.json，并把 inter-seed 一致度映射成报告信心回写主
        forecast.json。门控：N_FORECAST_SEEDS>1、full 模式、结构化预测已开、尚未集成。串行、
        有界、带停滞看门狗；任一额外种子失败仅告警跳过；有效样本<2 则不落集成文件（degrade-safe）。
        默认 N=1 → 该方法直接返回（与现状逐字节一致）。
        """
        try:
            # Foglamp WP1 (1B/1D)：种子数读 run 钉住的安全政策（缺失回退环境值，现默认 1）。
            n_seeds = max(1, int(self._pinned_safety(
                state, "n_forecast_seeds",
                getattr(Config, "N_FORECAST_SEEDS", 1)) or 1))
        except (TypeError, ValueError):
            n_seeds = 1
        if (n_seeds <= 1 or state.mode != "full"
                or not getattr(Config, "REPORT_STRUCTURED_FORECAST", True)
                or state.options.get("ensemble_done")):
            return
        # EVAL-17: a seed whose process died hard (SIGKILL, OOM, host reboot) before the
        # metering finally in _do_seed ran left a simulation that is neither checkpointed nor
        # recorded, and the resumed ensemble re-runs that seed under a new simulation. Meter
        # every persisted member once here; the per-simulation marker makes recorded ones
        # no-ops.
        _members = state.options.get("ensemble_member_simulations")
        if isinstance(_members, dict):
            for _member_sim in list(_members):
                self._record_sim_run_telemetry(state, _member_sim, stage=SIM_METER_STAGE_ENSEMBLE)
        if not (project and graph_id and state.report_id):
            return
        from ..utils.atomic import write_json_atomic
        primary_fc = self._read_report_forecast(state.report_id)
        if not primary_fc or not primary_fc.get("scenarios"):
            logger.info("[%s] 主报告无结构化预测，跳过多种子集成", state.pipeline_id)
            return
        forecasts: list = [primary_fc]
        extra_runs: list = []
        base_seed = int(getattr(Config, "SIM_SEED", 0) or 0)
        # CAL：日历模式运行期不注入默认轮数上限（已在配置生成期喂 target_max），
        # 只透传用户显式指定的 max_rounds（在 prepare 粗化粒度、绝不截断覆盖）。
        _mr = state.options.get("max_rounds") or (
            None if _calendar_mode() else (Config.OASIS_DEFAULT_MAX_ROUNDS or None))
        max_rounds = int(_mr) if _mr else None
        handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
        # 派生互异种子（base=0 时也确定性互异）；每个种子跑一次独立 (prepare→run→report)。
        seed_jobs = [(k, (base_seed or 0) + k * 7919) for k in range(2, n_seeds + 1)]
        cancel_ev0 = type(self)._cancel_events.get(state.pipeline_id)
        if cancel_ev0 is not None and cancel_ev0.is_set():
            raise PipelineCancelled("多种子集成期间被取消")

        # W9-5：主跑的情景脊柱（名 + 判定标准）钉给每个额外种子——种子间共享同一组命名情景
        # （概率自由），集成聚合才有稳定的对齐坐标（此前 3 种子自由起名 → 11 桶全 support=1）。
        _spine = seed_scenario_pin(primary_fc)

        # W9-2：集成 checkpoint + 遥测阶段带 + 心跳。此前集成运行在「report 完成之后」的
        # 无保护窗口：无 checkpoint、心跳陈旧、墙钟不归属任何阶段——两条失败跑都死在这里。
        from ..utils.telemetry import set_run_context as _set_run_ctx, set_stage as _set_stage
        _ckpt_path = os.path.join(handoff_dir, "ensemble_checkpoint.json")
        _done_seeds: dict[int, dict] = {}
        _prev_ckpt = _read_json(_ckpt_path)
        if isinstance(_prev_ckpt, dict):
            for _row in (_prev_ckpt.get("completed") or []):
                if not isinstance(_row, dict):
                    continue
                try:
                    _done_seeds[int(_row.get("seed"))] = _row
                except (TypeError, ValueError):
                    continue
        _ckpt_lock = threading.Lock()

        def _persist_ckpt() -> None:
            """把已完成种子清单原子落盘（调用方持 _ckpt_lock）。失败仅告警，不拦集成。"""
            try:
                write_json_atomic(_ckpt_path, {
                    "schema_version": 1,
                    "pipeline_id": state.pipeline_id,
                    "primary_report_id": state.report_id,
                    "n_seeds_requested": n_seeds,
                    "completed": list(_done_seeds.values()),
                    "updated_at": _utcnow(),
                })
            except Exception as _ce:  # noqa: BLE001
                logger.warning("[%s] ensemble_checkpoint.json 落盘失败（忽略）: %s",
                               state.pipeline_id, _ce)

        state.options.setdefault("ensemble_wall", {})["started_at"] = _utcnow()
        try:
            _set_stage("ensemble")
        except Exception:  # noqa: BLE001
            pass

        # PAR-3：额外种子并行跑。_run_one_seed 线程安全（各种子独立 simulation_id → 独立
        # 目录/DB/文件式 IPC/仅注入子进程 env；SimulationRunner 类级映射均按 sim_id 独立键；
        # 共享的 graph_id 由 Zep 服务端处理并发写，串行版本本就共享同一张图）。并发度
        # ENSEMBLE_SEED_CONCURRENCY（默认 2、上限 3）；=1 或仅 1 个额外种子时走串行（逐字节
        # 复现旧行为）。共享 cancel_event + 每种子内建停滞看门狗均保留（在 _run_one_seed 内）。
        try:
            seed_conc = max(1, min(3, int(getattr(Config, "ENSEMBLE_SEED_CONCURRENCY", 2) or 2)))
        except (TypeError, ValueError):
            seed_conc = 2

        def _do_seed(k: int, seed: int) -> None:
            """跑一个额外种子并把结果并入 forecasts/extra_runs（GIL 下 list.append 线程安全）。

            W9-2 幂等：checkpoint 里已完成、且其报告仍能读出结构化预测的种子直接复用结果，
            重启后 resume 不再重烧已完成的种子。ThreadPoolExecutor 不继承 contextvars，
            这里显式重设 run/stage 上下文，种子的 LLM 调用才会归入 ensemble 阶段带
            （此前落 '_global' 桶，per-run 成本失真）。
            """
            try:
                _set_run_ctx(state.pipeline_id, "ensemble")
            except Exception:  # noqa: BLE001
                pass
            _prev = _done_seeds.get(seed)
            if _prev and _prev.get("simulation_id"):
                # EVAL-17: a checkpointed seed's simulation spend is real whether its report is
                # reused below or the seed re-runs under a new simulation. A seed completed
                # before seed metering existed was never recorded; the per-simulation marker
                # makes this a no-op for one recorded when it ran.
                self._record_sim_run_telemetry(
                    state, _prev.get("simulation_id"), stage=SIM_METER_STAGE_ENSEMBLE)
            if _prev and _prev.get("report_id"):
                _fc_prev = self._read_report_forecast(_prev.get("report_id"))
                if _fc_prev and _fc_prev.get("scenarios"):
                    logger.info("[%s] 集成种子 %s 已在 checkpoint 中完成，复用其报告 %s",
                                state.pipeline_id, seed, _prev.get("report_id"))
                    self._note_ensemble_member_simulation(state, _prev.get("simulation_id"), seed)
                    extra_runs.append({"seed": seed,
                                       "simulation_id": _prev.get("simulation_id"),
                                       "report_id": _prev.get("report_id"),
                                       "resumed_from_checkpoint": True})
                    forecasts.append(_fc_prev)
                    return
            # EVAL-17: meter the seed simulation's subprocess spend exactly once under
            # 'ensemble_sim' on every exit (success, failure, cancel) once it exists.
            _sink: list = []
            try:
                sim_id, rid, fc = self._run_one_seed(
                    state, project, graph_id, actors, research, report_md,
                    seed=seed, max_rounds=max_rounds, scenario_spine=_spine,
                    sim_id_sink=_sink,
                )
            finally:
                if _sink:
                    self._record_sim_run_telemetry(
                        state, _sink[0], stage=SIM_METER_STAGE_ENSEMBLE)
            with _ckpt_lock:
                _done_seeds[seed] = {
                    "k": k, "seed": seed, "simulation_id": sim_id, "report_id": rid,
                    "has_forecast": bool(fc and fc.get("scenarios")),
                    "completed_at": _utcnow(),
                }
                _persist_ckpt()
            try:  # W9-2：每完成一个种子即刷新心跳（集成窗口内心跳不再冻结）
                PipelineManager.touch_heartbeat(state.pipeline_id, pid=os.getpid())
            except Exception:  # noqa: BLE001
                pass
            extra_runs.append({"seed": seed, "simulation_id": sim_id, "report_id": rid})
            if fc and fc.get("scenarios"):
                forecasts.append(fc)

        try:
            if seed_conc <= 1 or len(seed_jobs) <= 1:
                # 串行路径（与今日逐字节一致）
                for k, seed in seed_jobs:
                    cancel_ev = type(self)._cancel_events.get(state.pipeline_id)
                    if cancel_ev is not None and cancel_ev.is_set():
                        raise PipelineCancelled("多种子集成期间被取消")
                    st = state.stages.setdefault(STAGE_REPORT, StageState(name=STAGE_REPORT))
                    st.message = f"多种子集成 {k}/{n_seeds}（种子 {seed}）…"
                    if state.owner_boot_id is not None:  # W9-2：save 不得用陈旧心跳覆写看护线程
                        state.heartbeat_at = _utcnow()
                    PipelineManager.save(state)
                    try:
                        _do_seed(k, seed)
                    except PipelineCancelled:
                        raise
                    except Exception as _se:  # noqa: BLE001 — 单个种子失败不拖垮集成
                        logger.warning("[%s] 集成种子 %s 失败（跳过）: %s", state.pipeline_id, k, _se)
            else:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                st = state.stages.setdefault(STAGE_REPORT, StageState(name=STAGE_REPORT))
                st.message = f"多种子集成：并行 {len(seed_jobs)} 个额外种子（并发 {seed_conc}）…"
                if state.owner_boot_id is not None:  # W9-2
                    state.heartbeat_at = _utcnow()
                PipelineManager.save(state)
                cancelled: Optional[PipelineCancelled] = None
                with ThreadPoolExecutor(max_workers=seed_conc, thread_name_prefix="ens-seed") as ex:
                    futs = {ex.submit(_do_seed, k, seed): (k, seed) for k, seed in seed_jobs}
                    for fut in as_completed(futs):
                        k, seed = futs[fut]
                        try:
                            fut.result()
                        except PipelineCancelled as pc:
                            cancelled = pc  # 取消须穿透（其余种子按同一 cancel_event 各自停机）
                        except Exception as _se:  # noqa: BLE001 — 单个种子失败不拖垮集成
                            logger.warning("[%s] 集成种子 %s 失败（跳过）: %s", state.pipeline_id, k, _se)
                if cancelled is not None:
                    raise cancelled
            # REPORT-1：概率待复核（needs_review）的 run 会被 aggregate_forecasts 剔除，不算有效
            # 样本——否则 1 个可读 run 会被写成集成，一致度 1.0 被映射成「high」信心。
            if sum(1 for f in forecasts if f.get("probability_status") != "needs_review") < 2:
                logger.info("[%s] 有效集成样本<2，不写 ensemble_forecast.json", state.pipeline_id)
                state.options["ensemble_done"] = True
                PipelineManager.save(state)
                return
            from .ensemble import aggregate_forecasts
            agg = aggregate_forecasts(forecasts)
            agg["n_seeds_requested"] = n_seeds
            agg["extra_runs"] = extra_runs
            agreement = agg.get("agreement")
            agg["confidence"] = self._agreement_to_confidence(agreement)
            # 落 ensemble_forecast.json（handoff + 主报告目录）。主报告的
            # forecast.json/full_report.md 已作为一个精确审计束封存；在报告之后只改
            # confidence/ensemble 会让结构化预测、 prose、图表和 final_audit 分叉。
            # 因此集成保持为独立、可追溯的敏感性 sidecar，直到它能在下一版流程中
            # 前移到最终报告渲染/审计之前。
            try:
                write_json_atomic(os.path.join(handoff_dir, "ensemble_forecast.json"), agg)
                state.artifacts["ensemble_forecast"] = os.path.join(handoff_dir, "ensemble_forecast.json")
            except Exception:  # noqa: BLE001
                pass
            try:
                from .report_agent import ReportManager
                rfolder = ReportManager._get_report_folder(state.report_id)
                write_json_atomic(os.path.join(rfolder, "ensemble_forecast.json"), agg)
            except Exception as _we:  # noqa: BLE001
                logger.warning("[%s] 写集成结果失败: %s", state.pipeline_id, _we)
            state.options["ensemble_done"] = True
            state.options["ensemble"] = {
                "n_runs": agg.get("n_runs"), "agreement": agreement, "confidence": agg["confidence"],
            }
            PipelineManager.save(state)
            logger.info("[%s] 多种子集成完成: n=%s, 一致度=%s, 信心=%s",
                        state.pipeline_id, agg.get("n_runs"), agreement, agg["confidence"])
        finally:
            # W9-2：无论正常/取消/异常，把集成墙钟收口进 options（遥测的 'ensemble' 阶段带）
            # 并恢复 LLM 计量阶段上下文；save 前刷新内存心跳，避免用陈旧值覆写看护线程。
            state.options.setdefault("ensemble_wall", {})["finished_at"] = _utcnow()
            if state.owner_boot_id is not None:
                state.heartbeat_at = _utcnow()
            try:
                PipelineManager.save(state)
            except Exception:  # noqa: BLE001
                pass
            try:
                _set_stage(STAGE_REPORT)
            except Exception:  # noqa: BLE001
                pass
            self._flush_run_telemetry(state)  # W9-3：集成窗口结束即落一版遥测

    @staticmethod
    def _report_ledger_context(state: "PipelineState", simulation_id: Optional[str], *,
                               run_kind: str, seed: int,
                               record_class: Optional[str] = None) -> dict[str, Any]:
        """EVAL-1: ledger provenance for one ReportAgent (``agent.ledger_context``).

        ``as_of_date`` is the graph stage's validated anchor, inherited from the base
        pipeline by a what-if fork (None when it was not validated → the ledger falls
        back to strict actors / commit date). A fork also carries its scenario identity
        (``scenario_label`` / ``scenario_key``). Without an explicit ``record_class`` the
        ledger derives production / conditional_scenario. An evaluation run's pin
        (EVAL-13) re-classes the context as ``evaluation`` with its run provenance, so
        a reused report's repair commit lands in the evaluation ledger too.
        """
        context: dict[str, Any] = {
            "pipeline_id": state.pipeline_id,
            "simulation_id": simulation_id,
            "seed": seed,
            "run_kind": run_kind,
            "as_of_date": validated_as_of_from_options(state.options),
        }
        context.update(_scenario_ledger_identity(state.options))
        if record_class:
            context["record_class"] = record_class
        evaluation = PipelineOrchestrator._evaluation_pin(state)
        if evaluation is not None:
            from .ledger_commit import apply_evaluation_context
            context = apply_evaluation_context(context, evaluation)
        return context

    @staticmethod
    def _evaluation_pin(state: "PipelineState") -> Optional[dict[str, Any]]:
        """EVAL-13: this run's evaluation pin (None for a production run).

        The same resolution as the report-side lookup (``_evaluation_pin_of``): the
        options pin, else this pipeline's own handoff marker, else the fail-closed
        context of a shared handoff whose marker names another run. Orchestrator
        paths and ``evaluation_context_for_simulation`` therefore always agree.
        """
        return _evaluation_pin_of(state.pipeline_id, {"options": state.options or {},
                                                      "handoff_dir": state.handoff_dir})

    @staticmethod
    def _hindcast_agent_kwargs(state: "PipelineState") -> dict[str, Any]:
        """TIME-6: ``{'hindcast': pin}`` for a pinned hindcast run's ReportAgent, else {}."""
        pin = hindcast_policy(state.options)
        return {"hindcast": pin} if pin is not None else {}

    @classmethod
    def _assign_evaluation_context(cls, agent: Any, state: "PipelineState") -> None:
        """EVAL-13: give a report agent this run's evaluation context.

        An evaluation run's agent gets its pin as ``evaluation_context``. A production
        run's agent is marked as already resolved (production), so its report skips
        the pipeline-state scan of ``ReportAgent._resolve_evaluation_context``: this
        run's options and handoff decide, exactly as that scan would.
        """
        pin = cls._evaluation_pin(state)
        if pin is not None:
            agent.evaluation_context = pin
            return
        agent._evaluation_context_lookup = None
        agent._evaluation_context_looked_up = True

    @staticmethod
    def _record_validated_as_of(state: "PipelineState", as_of: Optional[datetime],
                                validated: bool) -> None:
        """EVAL-1: record the graph stage's as-of anchor as the ledger pre-registration date.

        Only an anchor the validator actually produced counts (``validated``); the
        raw-parse fallback date is unvalidated and never recorded. Every graph build
        re-decides, so a stale anchor from an earlier attempt is dropped first.
        """
        state.options.pop("as_of_date_validated", None)
        if not validated or as_of is None:
            return
        from ..utils.point_in_time import validate_as_of
        try:
            state.options["as_of_date_validated"] = validate_as_of(as_of.date().isoformat())
        except ValueError:
            pass

    def _generate_stage_report(self, state: "PipelineState", agent: Any,
                               simulation_id: Optional[str], *, report_id: str,
                               progress_callback: Callable[[str, int, str], None]) -> Any:
        """EVAL-1: generate the report stage's report with its ledger wiring.

        The agent gets its ledger context before generation (production, or the
        conditional_scenario a what-if's scenario label derives), and its ledger
        receipt is copied into ``state.options['forecast_ledger']`` whatever the
        outcome: completed, FAILED, or a cancellation raised after the completed
        report was committed. An evaluation run's agent also gets its admission pin
        as ``evaluation_context`` (EVAL-13, :meth:`_assign_evaluation_context`), and every
        agent the upstream model provenance as ``run_provenance`` (INFRA-8,
        :meth:`_assign_run_provenance`).
        """
        agent.ledger_context = self._report_ledger_context(
            state, simulation_id, run_kind="pipeline", seed=int(Config.SIM_SEED or 0))
        self._assign_run_provenance(agent, state)  # INFRA-8
        self._assign_evaluation_context(agent, state)
        try:
            return agent.generate_report(progress_callback=progress_callback, report_id=report_id)
        finally:
            receipt = getattr(agent, "ledger_receipt", None)
            if isinstance(receipt, dict):
                state.options["forecast_ledger"] = dict(receipt)

    def _repair_reused_report_ledger(self, state: "PipelineState", report: Any,
                                     simulation_id: Optional[str], actors: Any,
                                     research_report: Optional[str]) -> None:
        """EVAL-1: commit a reused report whose ledger commit never landed (best-effort).

        A resume reuses the finished report, so a commit that failed (ledger I/O) or
        was cut off by a crash would otherwise never happen. The report gets the
        context the report stage gives it; ``ledger_commit.recommit_reused_report``
        writes only for a completed report with no ledger row at all. A stored
        receipt proving the report already has its row skips the ledger read.
        """
        report_id = getattr(report, "report_id", None) or state.report_id
        if not report_id:
            return
        prior = state.options.get("forecast_ledger")
        if (isinstance(prior, dict) and prior.get("report_id") == report_id
                and (prior.get("status") in ("committed", "revision", "duplicate")
                     or prior.get("unpublished_row") in ("recorded", "duplicate"))):
            return
        try:
            from . import ledger_commit
            status = getattr(report, "status", None)
            receipt = ledger_commit.recommit_reused_report(
                report_id,
                report_status=getattr(status, "value", status),
                question=state.prompt,
                language=ReportAgent.resolve_output_language(
                    state.prompt, research_report or "", situation_brief(actors) or ""),
                actors=actors,
                scenario_label=str(state.options.get("scenario_label") or ""),
                ledger_context=self._report_ledger_context(
                    state, simulation_id, run_kind="pipeline", seed=int(Config.SIM_SEED or 0)),
                publication_status_fn=ReportManager.publication_status,
                load_forecast_fn=ReportManager.load_structured_forecast,
            )
        except Exception as exc:  # noqa: BLE001 — 账本补提交为旁路记账，绝不阻断复用
            logger.warning("[%s] [ledger] reused report %s: repair failed (ignored): %s",
                           state.pipeline_id, report_id, exc)
            return
        if receipt is None:
            return
        state.options["forecast_ledger"] = receipt
        log = logger.warning if receipt.get("status") == "error" else logger.info
        log("[%s] [ledger] status=%s commit_id=%s report=%s (reused report repaired)",
            state.pipeline_id, receipt.get("status"), receipt.get("commit_id"), report_id)

    @staticmethod
    def _note_ensemble_member_simulation(state: "PipelineState", simulation_id: Optional[str],
                                         seed: int) -> None:
        """EVAL-1: remember which ensemble seed a member simulation ran.

        No pipeline owns a member's simulation as its ``simulation_id``, so without
        this map a later /api/report/generate on it would key a second PRODUCTION
        primary; ``ledger_identity_for_simulation`` reads it to keep it an
        ensemble member. Persisted by the ensemble's own state saves. Seed threads call it
        concurrently with the full state save in _record_sim_run_telemetry, so the write
        takes the same lock (EVAL-17).
        """
        if simulation_id:
            with PipelineOrchestrator._sim_meter_lock:
                state.options.setdefault(
                    "ensemble_member_simulations", {})[str(simulation_id)] = int(seed)

    def _run_one_seed(self, state: "PipelineState", project: Any, graph_id: str,
                      actors: Any, research: dict, report_md: str, *,
                      seed: int, max_rounds: Optional[int],
                      scenario_spine: Optional[list] = None,
                      sim_id_sink: Optional[list] = None) -> tuple:
        """对同一图谱跑一次额外 (prepare→run→report)，返回 (sim_id, report_id, forecast|None)。

        自包含、串行、运行在管线线程内；不触碰主 sim/report 的 id 与状态。带停滞看门狗。
        W9-5 ``scenario_spine``：主跑的情景脊柱（名+判定标准），钉给种子的 ReportAgent 使
        种子对同一组命名情景打分（概率自由）；报告链尚未支持该参数时回退旧签名。
        EVAL-17 ``sim_id_sink``: receives the seed's simulation_id as soon as it exists, so
        the caller can meter the seed simulation's spend even when this method raises.
        """
        sim_manager = SimulationManager()
        _is_http = bool(Config.PROVIDER_META.get(Config.LLM_PROVIDER, {}).get('openai_compat'))
        sim_state = sim_manager.create_simulation(
            project.project_id, graph_id, enable_twitter=True, enable_reddit=True)
        sim_id = sim_state.simulation_id
        if sim_id_sink is not None:
            sim_id_sink.append(sim_id)
        self._note_ensemble_member_simulation(state, sim_id, seed)
        # SIM-11 (pairs with SIM-7): HTTP/openai-compat providers tolerate higher
        # persona fan-out; raise the default 8→16 (configurable via PARALLEL_PROFILE_COUNT).
        # CLI providers stay capped at 3 (local CLI throughput bound).
        _pp = int(getattr(Config, "PARALLEL_PROFILE_COUNT", 16) or 16)
        # W9-5：与主路径（PREPARE 阶段）对齐——把 GRAPH 阶段持久化的中心度先验也喂给种子跑的
        # salience 排序（此前种子跑漏传 graph_priors，agent 选池与主跑系统性不一致）。
        _graph_priors = None
        try:
            _graph_priors = _read_json(os.path.join(
                state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id),
                "graph_priors.json"))
        except Exception:  # noqa: BLE001
            _graph_priors = None
        sim_manager.prepare_simulation(
            simulation_id=sim_id,
            simulation_requirement=state.prompt,
            document_text=report_md,
            parallel_profile_count=_pp if _is_http else 3,
            actors=actors,
            graph_priors=_graph_priors,  # W9-5: 与主路径一致（P3-7 中心度先验）
            max_rounds=max_rounds,  # PREP-1: 集成种子跑同样按真实执行窗排期
            research_language=state.options.get("research_language"),  # PREP-4
        )
        run_kwargs: dict[str, Any] = {"platform": "parallel", "sim_seed": int(seed)}
        if max_rounds:
            run_kwargs["max_rounds"] = int(max_rounds)
        # Foglamp WP1 (1A/1B)：读 run 钉住的安全政策（默认已为 false——观察图不得吃反馈）。
        if self._pinned_safety(state, "sim_graph_feedback",
                               Config.SIM_GRAPH_FEEDBACK) and graph_id:
            run_kwargs["enable_graph_memory_update"] = True
            run_kwargs["graph_id"] = graph_id
        SimulationRunner.start_simulation(simulation_id=sim_id, **run_kwargs)
        cancel_ev = type(self)._cancel_events.get(state.pipeline_id)
        last_progress_at = time.monotonic()
        last_round = -1
        try:
            stall_s = float(getattr(Config, "PIPELINE_RUN_STALL_S", 1800) or 1800)
        except (TypeError, ValueError):
            stall_s = 1800.0
        # W9-2：种子轮询内的心跳刷新节律（与看护线程同参）。
        try:
            _hb_interval = float(getattr(Config, "PIPELINE_HEARTBEAT_INTERVAL_S", 30) or 30)
        except (TypeError, ValueError):
            _hb_interval = 30.0
        _last_hb = time.monotonic()
        while True:
            if cancel_ev is not None and cancel_ev.is_set():
                try:
                    SimulationRunner.stop_simulation(sim_id)
                except Exception:  # noqa: BLE001
                    pass
                raise PipelineCancelled("多种子集成期间被取消")
            rs = SimulationRunner.get_run_state(sim_id)
            if rs is None:
                raise RuntimeError("集成种子模拟运行状态丢失")
            cur = getattr(rs, "current_round", 0) or 0
            if cur != last_round:
                last_round = cur
                last_progress_at = time.monotonic()
            if rs.runner_status == RunnerStatus.COMPLETED:
                break
            if rs.runner_status in (RunnerStatus.FAILED, RunnerStatus.STOPPED):
                raise RuntimeError(f"集成种子模拟未正常结束: {rs.runner_status}")
            if stall_s > 0 and (time.monotonic() - last_progress_at) > stall_s:
                try:
                    SimulationRunner.stop_simulation(sim_id)
                except Exception:  # noqa: BLE001
                    pass
                raise RuntimeError(f"集成种子模拟约 {int(stall_s)}s 无进展，看门狗终止")
            # W9-2：种子轮询期间按心跳节律刷新 heartbeat_at——集成窗口内心跳不再冻结，
            # 别的进程的 reconcile_orphans 能看到「这条管线还活着」。
            if (time.monotonic() - _last_hb) >= _hb_interval:
                _last_hb = time.monotonic()
                try:
                    PipelineManager.touch_heartbeat(state.pipeline_id, pid=os.getpid())
                except Exception:  # noqa: BLE001
                    pass
            time.sleep(5)
        # 反馈写入器排空（与主跑一致），保证报告读到完整图谱（Foglamp 1B：读钉住政策）
        if self._pinned_safety(state, "sim_graph_feedback",
                               Config.SIM_GRAPH_FEEDBACK) and graph_id:
            SimulationRunner.join_monitor_thread(sim_id, timeout=30)
            try:
                ZepGraphMemoryManager.stop_updater(sim_id)
            except Exception:  # noqa: BLE001
                pass
        try:
            SimulationRunner.write_run_summary(sim_id)
        except Exception:  # noqa: BLE001
            pass
        rid = f"report_{uuid.uuid4().hex[:12]}"
        _agent_kwargs: dict[str, Any] = {
            "graph_id": graph_id,
            "simulation_id": sim_id,
            "simulation_requirement": state.prompt,
            "situation_brief": situation_brief(actors),
            "actors": actors,
            "sources": research.get("sources"),
            "research_report": report_md,
        }
        # TIME-6：回测运行的种子报告同样扣下市场——钉随构造参数直接交给报告，不依赖报告侧
        # 按模拟 id 的所属管线查找（种子模拟不是任何管线自己的 simulation_id）。
        _agent_kwargs.update(self._hindcast_agent_kwargs(state))
        # W9-5：把主跑情景脊柱钉给种子报告（scenario_spine 参数由报告链工作流并行落地；
        # 尚未支持时 TypeError → 回退旧签名，落地顺序无关）。
        try:
            if scenario_spine:
                agent = ReportAgent(scenario_spine=scenario_spine, **_agent_kwargs)
            else:
                agent = ReportAgent(**_agent_kwargs)
        except TypeError:
            logger.info("[%s] ReportAgent 尚未支持 scenario_spine，种子 %s 回退自由情景命名",
                        state.pipeline_id, seed)
            agent = ReportAgent(**_agent_kwargs)
        # EVAL-1: 集成种子报告是相关抽样而非独立预测——以 ensemble_member 入账（不进生产校准）。
        agent.ledger_context = self._report_ledger_context(
            state, sim_id, run_kind="seed_ensemble", seed=int(seed),
            record_class="ensemble_member")
        # EVAL-13: 评估运行的种子报告同样只进评估通道（跳过生产校准读、入评估账本）。
        self._assign_evaluation_context(agent, state)
        agent.generate_report(report_id=rid)
        return sim_id, rid, self._read_report_forecast(rid)

    # -- 内部：进度辅助 ----------------------------------------------------

    @staticmethod
    def _global_from_stage(mode: str, stage: str, local_pct: int, dynamic_bands: Optional[dict] = None) -> int:
        base = RESEARCH_ONLY_BANDS if mode == "research_only" else STAGE_BANDS
        # T6.7: 已知真实成本信号时用动态权重（仅 full 模式）；否则回退静态档位。
        bands = dynamic_bands if (dynamic_bands and mode != "research_only") else base
        band = bands.get(stage) or base.get(stage, (0, 100))
        lo, hi = band[0], band[1]
        local_pct = max(0, min(100, local_pct))
        return int(lo + (hi - lo) * local_pct / 100)

    @staticmethod
    def _recompute_dynamic_bands(
        state: "PipelineState",
        chunk_count: Optional[int] = None,
        total_rounds: Optional[int] = None,
        section_count: Optional[int] = None,
        temporal: Optional[dict] = None,
    ) -> None:
        """T6.7: 用已知成本信号（chunk 数 / 轮数 / 章节数）按比例重排 graph/run/report 的全局区间。

        research/ontology/prepare 区间保持静态；把这三段之后到 100 的剩余区间按成本权重重新切分，
        让深跑（多 chunk/多轮）时图谱/模拟阶段占更大份额，进度条与 ETA 更诚实。结果写入
        state.options['dynamic_bands']，被 _global_from_stage 读取。信号不全则按当前已知部分估计。"""
        # research/ontology 静态；动态区间覆盖 graph(40)→report(100)
        dyn_start = STAGE_BANDS[STAGE_GRAPH][0]      # 40
        dyn_total = 100 - dyn_start                  # 60
        # 成本权重（带兜底，避免 0）
        prev = state.options.get("cost_signals", {}) if isinstance(state.options.get("cost_signals"), dict) else {}
        cc = chunk_count if chunk_count is not None else prev.get("chunk_count")
        tr = total_rounds if total_rounds is not None else prev.get("total_rounds")
        sc = section_count if section_count is not None else prev.get("section_count")
        _sig: dict[str, Any] = {"chunk_count": cc, "total_rounds": tr, "section_count": sc}
        # CAL：日历模式把 temporal_config 的日历指纹一并记入成本信号（跨调用保留）。
        for _k in ("calendar_unit", "n_rounds", "horizon_date"):
            _v = (temporal or {}).get(_k, prev.get(_k))
            if _v is not None:
                _sig[_k] = _v
        state.options["cost_signals"] = _sig
        w_graph = float(cc or 20)        # 每 chunk ~1 次 LLM 抽取
        w_prepare = 8.0                  # prepare 较轻且较稳定
        w_run = float((tr or 24) * 1.5)  # 每轮多次 agent LLM 调用
        w_report = float((sc or 6) * 6)  # 每章多次工具调用
        weights = [("graph", w_graph), ("prepare", w_prepare), ("run", w_run), ("report", w_report)]
        tot = sum(w for _, w in weights) or 1.0
        bands: dict[str, list] = {
            STAGE_RESEARCH: list(STAGE_BANDS[STAGE_RESEARCH]),
            STAGE_ONTOLOGY: list(STAGE_BANDS[STAGE_ONTOLOGY]),
        }
        cursor = float(dyn_start)
        for name, w in weights:
            seg = dyn_total * (w / tot)
            bands[name] = [int(round(cursor)), int(round(cursor + seg))]
            cursor += seg
        bands["report"][1] = 100  # 收尾对齐 100，避免取整漂移
        state.options["dynamic_bands"] = bands

    def _make_stage_updater(self, state: PipelineState, stage: str):
        task_manager = TaskManager()
        # 把后续该阶段的 LLM 调用归属到此 stage（I-5-2 per-stage rollup）。
        try:
            from ..utils.telemetry import set_stage
            set_stage(stage)
        except Exception:
            pass

        def update(local_pct: int, message: str):
            # 取消点：各阶段内部都会频繁回调进度，在这里抬升取消请求，
            # 使取消无需等到阶段边界。
            ev = PipelineOrchestrator._cancel_events.get(state.pipeline_id)
            if ev is not None and ev.is_set():
                raise PipelineCancelled("管线已被用户取消")
            # DEFECT-1：与取消同款的高频止损点。运行级提供方中断熔断触发后，在下一次
            # 进度回调处抬升 ProviderOutageHalt（BaseException 穿透语义），使止损无需
            # 等阶段边界——报告阶段不会再「中止本报告后继续下一个报告」。
            _breaker = _outage_breaker_for(state.pipeline_id)
            if _breaker is not None and _breaker.tripped:
                raise ProviderOutageHalt(_breaker.halt_message())
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
            # I-5-6: 记录最近一次进度信号的壁钟时间戳，供状态 API 计算 elapsed/stale，
            # 让 UI 把「长时间无进度」诚实地呈现为「仍在思考」而非「卡死的进度条」。
            # I-4-1: 进度回调本身即确凿的存活信号，顺手把 heartbeat_at 也刷新，避免随后的
            # save(state) 用陈旧的内存值覆盖看护线程刚原子写入的新心跳（两者就此保持一致）。
            _hb_now = _utcnow()
            state.last_progress_at = _hb_now
            if state.owner_boot_id is not None:
                state.heartbeat_at = _hb_now
            state.global_progress = self._global_from_stage(
                state.mode, stage, local_pct, state.options.get("dynamic_bands")
            )
            # I-4-6: 在长阶段运行中机会性地登记已落盘的「临时产物」深链（best-effort，
            # 不覆盖完成时登记的正式产物），让用户在阶段完成前就能查看增量证据。
            self._register_partial_artifacts(state, stage)
            PipelineManager.save(state)
            # W9-3：进度回调即机会性遥测 flush 检查点（每新增 N 次 LLM 调用落一版账）。
            try:
                self._maybe_flush_run_telemetry(state)
            except Exception:  # noqa: BLE001
                pass
            if state.task_id:
                task_manager.update_task(
                    state.task_id,
                    progress=state.global_progress,
                    message=f"[{stage}] {message}",
                )

        return update

    def _complete_stage(
        self,
        state: PipelineState,
        stage: str,
        message: str = "完成",
        *,
        reused: bool = False,
    ):
        """Seal a stage without charging resume downtime to its wall clock.

        Reuse paths briefly mark an already-completed stage as ``running`` so
        progress and artifact checks remain visible.  Those bookkeeping calls
        must preserve the original attempt timestamps; otherwise a resume made
        hours later reports the idle gap as model/runtime cost.  Legacy reused
        states missing one endpoint degrade to a zero-duration bookkeeping
        interval rather than an invented multi-hour duration.
        """
        st = state.stages.setdefault(stage, StageState(name=stage))
        st.status = "completed"
        st.progress = 100
        st.message = message
        now = _utcnow()
        if reused:
            if st.started_at is None and st.finished_at is None:
                st.started_at = st.finished_at = now
            elif st.started_at is None:
                st.started_at = st.finished_at
            elif st.finished_at is None:
                st.finished_at = st.started_at
        else:
            st.finished_at = now
        state.global_progress = self._global_from_stage(
            state.mode, stage, 100, state.options.get("dynamic_bands")
        )
        try:
            self._record_stage_artifacts(state, stage)  # T6.3
        except Exception:
            pass
        # INFRA-7：血统记账是诚实性检查（fail closed，不吞异常），随本次 save 与阶段完成一起落盘。
        self._record_stage_lineage(state, stage, reused)
        try:
            self._record_stage_decision(state, stage, reused)  # INFRA-7
        except Exception as _sd_err:  # noqa: BLE001 — 复用记账是观测增益，绝不阻断阶段完成
            logger.debug("[%s] stage_reuse_v1 记账跳过: %s", state.pipeline_id, _sd_err)
        try:
            self._stamp_stage_model_provenance(state, stage, reused=reused)  # INFRA-8
        except Exception as _mp_err:  # noqa: BLE001 — 出处记录是观测增益，绝不阻断阶段完成
            logger.debug("[%s] run.json 模型出处跳过: %s", state.pipeline_id, _mp_err)
        PipelineManager.save(state)
        # W9-3：阶段转换必落一版遥测账（重启只丢「上一次阶段边界之后」的增量）。
        self._flush_run_telemetry(state)

    @staticmethod
    def _reconcile_completed_simulation_state(
        sim_state: Any,
        run_state: Any = None,
        run_summary: Any = None,
    ) -> None:
        """Copy authoritative terminal RUN fields into the durable simulation state.

        ``SimulationState`` is the API-facing record while ``SimulationRunState``
        is the runtime authority.  Updating only the former's top-level status
        produced impossible records (completed with round 0 and both platforms
        not_started).  This helper makes the terminal projection explicit and
        testable without coupling it to pipeline I/O.
        """
        sim_state.status = SimulationStatus.COMPLETED
        round_candidates = [getattr(run_state, "current_round", None)]
        if isinstance(run_summary, dict):
            round_candidates.append(run_summary.get("rounds_executed"))
        parsed_rounds = []
        for candidate in round_candidates:
            try:
                parsed_rounds.append(max(0, int(candidate or 0)))
            except (TypeError, ValueError):
                continue
        sim_state.current_round = max(parsed_rounds, default=0)
        for platform in ("twitter", "reddit"):
            enabled_raw = getattr(run_state, f"{platform}_enabled", None)
            enabled = bool(
                getattr(sim_state, f"enable_{platform}", False)
                if enabled_raw is None else enabled_raw
            )
            completed_raw = getattr(run_state, f"{platform}_completed", None)
            if not enabled:
                platform_status = "disabled"
            elif completed_raw is not None:
                platform_status = "completed" if bool(completed_raw) else "incomplete"
            else:
                # Aggregate rounds prove that *some* simulation work completed,
                # not that every enabled lane reached its terminal checkpoint.
                # Preserve an existing explicit terminal projection when one is
                # available; otherwise expose the missing evidence honestly.
                existing = str(
                    getattr(sim_state, f"{platform}_status", "") or ""
                ).strip()
                platform_status = (
                    existing if existing not in {"", "not_started"} else "unknown"
                )
            setattr(sim_state, f"{platform}_status", platform_status)
        sim_state.error = getattr(run_state, "error", None) or None

    # ---------------------------------------------------------------- S1 health gate
    # The corpus review found 8/13 runs reported status=completed/100%/error=null while
    # the deliverable was actually broken (all-placeholder reports, no forecast.json, hollow
    # sims). The pipeline marked success on stage *return* without validating artifacts, so
    # every other defect was invisible. These methods assess the real deliverable and either
    # HARD-FAIL the run (so it shows as failed, not falsely completed) or record a degraded
    # health block consumed by the status API + the report's simulation-caveat logic.
    @staticmethod
    def _sim_dir(sim_id: str) -> str:
        return os.path.normpath(os.path.join(
            os.path.dirname(__file__), "..", "..", "uploads", "simulations", sim_id))

    def _spawn_run_stall_watchdog(self, pipeline_id: str, sim_id: str, stall_s: float) -> dict:
        """QUALITY-OPT C1/C2 (live-surfaced): an INDEPENDENT daemon watchdog for the RUN stage.

        The inline poll-loop watchdog cannot fire when the poll itself blocks on a wedged sim's
        IPC (observed: both LLM providers exhausted → sim deadlocked at a round for 4.5h while the
        pipeline still showed 'running'). This thread reads run_state.json FROM DISK (never blocks
        on the sim), and if the round hasn't advanced within stall_s it force-stops the sim
        subprocess — which makes the poll loop's next get_run_state return STOPPED and fail the run
        honestly instead of hanging forever. Returns a control dict; caller sets ctl['stop']=True.
        """
        import threading
        ctl = {"stop": False}
        if stall_s <= 0:
            return ctl
        rsp = os.path.join(self._sim_dir(sim_id), "run_state.json")

        def _wd() -> None:
            last_round = None
            last_prog = time.monotonic()
            while not ctl["stop"]:
                time.sleep(30)
                if ctl["stop"]:
                    return
                try:
                    cur = None
                    if os.path.exists(rsp):
                        with open(rsp, encoding="utf-8") as f:
                            rs = json.load(f)
                        cur = rs.get("current_round")
                        if rs.get("completed") or rs.get("error"):
                            return  # sim reached a terminal state; poll loop handles it
                    if cur != last_round:
                        last_round = cur
                        last_prog = time.monotonic()
                    elif (time.monotonic() - last_prog) > stall_s:
                        logger.error("[%s] 独立看门狗：模拟 %ds 无轮次推进（卡在 round %s，疑似双 provider 耗尽），"
                                     "强制停止子进程", pipeline_id, int(stall_s), cur)
                        try:
                            SimulationRunner.stop_simulation(sim_id)
                        except Exception as _e:  # noqa: BLE001
                            logger.warning("[%s] 看门狗停止模拟失败: %s", pipeline_id, _e)
                        return
                except Exception:  # noqa: BLE001 — watchdog must never crash
                    pass

        threading.Thread(target=_wd, name=f"run-stall-wd-{sim_id[:8]}", daemon=True).start()
        return ctl

    def _assess_report_health(self, report_id: Optional[str]) -> "tuple[str, list[str], dict]":
        """Assess the exact deliverable, including its authoritative final audit.

        Empty/placeholder output, missing forecast/audit, or hard publish-integrity
        defects fail. Partial sections and epistemic/calibration findings degrade.
        """
        import glob
        issues: list[str] = []
        if not report_id:
            return "failed", ["no report_id was produced"], {}
        try:
            folder = ReportManager._get_report_folder(report_id)
        except Exception:  # noqa: BLE001
            return "failed", ["report folder unresolved"], {}
        secs = sorted(glob.glob(os.path.join(folder, "section_*.md")))
        total = len(secs)
        placeholder = 0
        for s in secs:
            try:
                body = open(s, encoding="utf-8", errors="ignore").read()
            except OSError:
                continue
            # ORCH-1(2): 占位符判定收紧为 report_agent 实际写入的失败模板——
            # SECTION_FAILURE_PLACEHOLDER 与「LLM 返回空响应」变体均以「（本章节生成失败：」
            # 开头。旧的 '生成失败' / '本章节'+'失败' 松散子串会把正文里合法讨论
            # 「××失败」的章节误判为占位符。另外，含图表标记的短章节（一张 Mermaid/内嵌图
            # + 简短图注是合法产出）豁免 <200 字符规则，不再按占位符计。
            _is_placeholder = "（本章节生成失败：" in body
            if not _is_placeholder and len(body.strip()) < 200:
                _is_placeholder = not any(
                    m in body for m in ("![", "<img", "<svg", "```mermaid"))
            if _is_placeholder:
                placeholder += 1
        fc_ok = False
        fcp = os.path.join(folder, "forecast.json")
        q_issues: list[str] = []
        hard_q_issues: list[str] = []

        def _add_unique(target: list[str], value: Any) -> None:
            text = str(value or "").strip()
            if text and text not in target:
                target.append(text)

        if os.path.exists(fcp):
            try:
                fc = json.load(open(fcp, encoding="utf-8"))
                fc_ok = bool(fc.get("scenarios") or fc.get("binary_forecasts"))
                # surface the report-side audit findings (S2/S11/S12) as degraded signals
                _q0 = fc.get("quality")
                q = _q0 if isinstance(_q0, dict) else {}
                if (q.get("quote_provenance") or {}).get("ungrounded"):
                    q_issues.append(f"{q['quote_provenance']['ungrounded']} ungrounded/laundered quote(s) (S2)")
                if (q.get("numeric_consistency") or {}).get("mismatch_count"):
                    q_issues.append(f"{q['numeric_consistency']['mismatch_count']} prose-vs-forecast probability mismatch(es) (S11)")
                if (q.get("implausible_stats") or {}).get("count"):
                    q_issues.append(f"{q['implausible_stats']['count']} implausible headline stat(s) (S12)")
                lint_q = q.get("lint") or {}
                if lint_q.get("leakage_flags"):
                    q_issues.append(
                        f"{lint_q['leakage_flags']} residual simulation-mechanics phrase(s) "
                        "remain in the published report"
                    )
                bq = fc.get("binary_quality") or {}
                if bq and not bq.get("passed", True):
                    q_issues.append("binary-forecast conviction/objectivity gate failed (A3/A4): " + "；".join(bq.get("issues", [])[:2]))
                elif bq.get("needs_review_count"):
                    # REPORT-1：部分二元概率不可读被扣下、其余仍过门时，扣下说明只在
                    # binary_quality 里——作为降级信号浮到健康面（不阻断发布；门未过时
                    # 上一分支的 issues 已以该说明行打头）。
                    from .forecast_extractor import _binary_withheld_issue
                    q_issues.append(_binary_withheld_issue(bq["needs_review_count"]))
                # XRUN-1(c): 二元预测对模拟不敏感（与另一份报告输出同一概率向量）→ 降级信号。
                if (q.get("sim_insensitivity") or {}).get("issue"):
                    q_issues.append(
                        "binary forecasts insensitive to simulation (identical vector to "
                        f"{(q.get('sim_insensitivity') or {}).get('other_report_id')})")
                # XRUN-16(1): 钉定骨架与最终 forecast 之间情景数漂移。
                _scd = q.get("scenario_count_drift") or {}
                if _scd:
                    q_issues.append(
                        f"scenario count drifted {_scd.get('pinned')}→{_scd.get('final')} "
                        "between pinned spine and final forecast")
                # LOOP-010: surface the complete final publish-gate result, not
                # only its citation-coverage prefix. Hard issues block completion;
                # epistemic issues keep the report visible as degraded.
                for _qi in (q.get("issues") or []):
                    if isinstance(_qi, str):
                        _add_unique(q_issues, _qi)
                for _qi in (q.get("hard_issues") or []):
                    if isinstance(_qi, str):
                        _add_unique(hard_q_issues, _qi)
            except (OSError, ValueError, TypeError, AttributeError):
                fc_ok = False
        final_audit_meta: dict[str, Any] = {}
        fr = os.path.join(folder, "full_report.md")
        if getattr(Config, "REPORT_FINAL_READ_ONLY_AUDIT", True):
            final_audit_path = os.path.join(folder, "final_audit.json")
            if not os.path.exists(final_audit_path):
                _add_unique(hard_q_issues, "final_audit.json missing (report was not audited)")
            else:
                try:
                    with open(final_audit_path, encoding="utf-8") as _faf:
                        final_audit = json.load(_faf)
                    if not isinstance(final_audit, dict) or not final_audit:
                        raise ValueError("empty final audit")
                    final_hard = list(final_audit.get("hard_issues") or [])
                    _gate0 = final_audit.get("publish_gate")
                    gate = _gate0 if isinstance(_gate0, dict) else {}
                    required_policy = int(getattr(
                        Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3
                    ))
                    if final_audit.get("policy_version") != required_policy:
                        final_hard.append(
                            "final audit policy is stale; deterministic replay required"
                        )
                    if final_audit.get("hard_passed") is not True:
                        final_hard.append("final audit did not hard-pass")
                    if final_audit.get("disk_matches_memory") is not True:
                        final_hard.append(
                            "final audit did not confirm disk/memory byte identity"
                        )
                    if gate.get("enabled") and gate.get("passed") is not True:
                        final_hard.append("professional publication gate did not pass")
                    structured = final_audit.get("structured_forecast") or {}
                    scenario_contract = final_audit.get("scenario_contract") or {}
                    if structured.get("required") and structured.get("valid") is not True:
                        final_hard.append("structured forecast contract is invalid")
                    if (structured.get("required")
                            and scenario_contract.get("valid") is not True):
                        final_hard.append("scenario contract is missing or invalid")
                    if os.path.exists(fr):
                        with open(fr, "rb") as _report_handle:
                            current_sha = hashlib.sha256(
                                _report_handle.read()
                            ).hexdigest()
                        if final_audit.get("markdown_sha256") != current_sha:
                            final_hard.append(
                                "final audit fingerprint does not match full_report.md"
                            )
                    if os.path.exists(fcp):
                        with open(fcp, "rb") as _forecast_handle:
                            current_forecast_sha = hashlib.sha256(
                                _forecast_handle.read()
                            ).hexdigest()
                        if final_audit.get("forecast_sha256") != current_forecast_sha:
                            final_hard.append(
                                "final audit fingerprint does not match forecast.json"
                            )
                    final_hard.extend(
                        issue for issue in (gate.get("hard_issues") or [])
                        if issue not in final_hard
                    )
                    for _qi in final_hard:
                        _add_unique(hard_q_issues, _qi)
                        _add_unique(q_issues, _qi)
                    for _qi in (gate.get("epistemic_issues") or []):
                        _add_unique(q_issues, _qi)
                    final_audit_meta = {
                        "read_only": final_audit.get("read_only"),
                        "markdown_sha256": final_audit.get("markdown_sha256"),
                        "forecast_sha256": final_audit.get("forecast_sha256"),
                        "disk_matches_memory": final_audit.get("disk_matches_memory"),
                        "hard_passed": not final_hard,
                    }
                except (OSError, ValueError, TypeError, AttributeError) as _fae:
                    _add_unique(
                        hard_q_issues,
                        f"final_audit.json unreadable/invalid ({type(_fae).__name__})",
                    )
        fr_len = os.path.getsize(fr) if os.path.exists(fr) else 0
        meta = {"sections": total, "placeholder_sections": placeholder,
                "forecast_ok": fc_ok, "full_report_bytes": fr_len,
                "final_audit": final_audit_meta}
        hard = False
        if total and placeholder >= total:
            hard = True
            issues.append(f"all {total} report sections are failure placeholders")
        elif placeholder:
            issues.append(f"{placeholder}/{total} report sections are failure placeholders")
        if not fc_ok and getattr(Config, "REPORT_STRUCTURED_FORECAST", True):
            hard = True
            issues.append("forecast.json missing or empty (no scenarios/binary_forecasts)")
        if fr_len and fr_len < 2000:
            hard = True
            issues.append(f"full_report.md is only {fr_len} bytes (effectively empty)")
        if hard_q_issues:
            hard = True
            for _qi in hard_q_issues:
                _add_unique(issues, _qi)
        for _qi in q_issues:  # all final publish issues are visible in health
            _add_unique(issues, _qi)
        meta["quality_issues"] = q_issues
        meta["hard_quality_issues"] = hard_q_issues
        health = "failed" if hard else ("degraded" if issues else "ok")
        return health, issues, meta

    def _assess_run_health(self, sim_id: Optional[str],
                           graph_id: Optional[str] = None) -> "tuple[str, list[str], dict]":
        """Degraded (not hard-fail) if the simulation is hollow (0 organic posts/comments),
        errored, or truncated — the report must then NOT narrativize it as evidence."""
        import sqlite3
        issues: list[str] = []
        if not sim_id:
            return "ok", issues, {}
        base = self._sim_dir(sim_id)
        db_rows = 0
        db_found = False
        for dbn in ("reddit_simulation.db", "twitter_simulation.db"):
            p = os.path.join(base, dbn)
            if not os.path.exists(p):
                continue
            db_found = True
            try:
                c = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
                cur = c.cursor()
                for t in ("post", "comment"):
                    try:
                        db_rows += cur.execute(f"select count(*) from {t}").fetchone()[0]
                    except sqlite3.Error:
                        pass
                c.close()
            except sqlite3.Error:
                pass
        # XRUN-11: run_summary.json 已做诚实的种子/有机拆分（CREATE_POST/COMMENT − seeds），
        # 与 sqlite 裸行数（含种子+转发行）是两套口径、曾对同一 sim 给出 20 vs 40 的双重真相。
        # 存在时以 run_summary 为准；sqlite 计数保留为回退并改名 db_post_comment_rows。
        organic = db_rows
        organic_source = "db_rows"
        summary_health = None
        try:
            _sum_path = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id, "run_summary.json")
            if os.path.exists(_sum_path):
                with open(_sum_path, encoding="utf-8") as _sf:
                    _summary = json.load(_sf)
                if isinstance(_summary, dict):
                    _oc = _summary.get("organic_action_count")
                    if isinstance(_oc, int):
                        organic = _oc
                        organic_source = "run_summary"
                    _sh = _summary.get("simulation_health")
                    if isinstance(_sh, str) and _sh:
                        summary_health = _sh
        except Exception:  # noqa: BLE001 — 老 run 无 summary → 沿用 db 口径
            pass
        err = None
        truncated = False
        rsp = os.path.join(base, "run_state.json")
        if os.path.exists(rsp):
            try:
                rs = json.load(open(rsp, encoding="utf-8"))
                err = rs.get("error")
                cr = rs.get("current_round")
                tr = rs.get("total_rounds") or rs.get("total_simulation_rounds")
                if isinstance(cr, int) and isinstance(tr, int) and tr > 0 and cr < tr:
                    truncated = True
            except (OSError, ValueError):
                pass
        # XRUN-6: 图谱反馈死信队列非空 = 报告将读到一张 episode 饥饿的图谱。计数暴露 + 降级，
        # 运维用 backend/scripts/replay_zep_dead_letters.py <graph_id> 重放（成功后归档、计数归零）。
        dead_letters = 0
        if graph_id:
            try:
                _dl_path = os.path.join(
                    Config.OASIS_SIMULATION_DATA_DIR, "_zep_dead_letter", f"{graph_id}.jsonl")
                if os.path.exists(_dl_path):
                    with open(_dl_path, encoding="utf-8") as _df:
                        dead_letters = sum(1 for _ln in _df if _ln.strip())
            except Exception:  # noqa: BLE001
                dead_letters = 0
        meta = {"organic_actions": organic, "organic_source": organic_source,
                "db_post_comment_rows": db_rows,
                "error": (str(err)[:160] if err else None),
                "truncated": truncated, "dead_letter_count": dead_letters}
        if summary_health:
            meta["simulation_health"] = summary_health
            if summary_health in ("hollow", "errored", "llm_degraded", "truncated"):
                issues.append(f"run_summary simulation_health={summary_health}")
        if err:
            issues.append(f"simulation error: {str(err)[:120]}")
        if truncated:
            issues.append("simulation was truncated before completion")
        if db_found and organic == 0:
            issues.append("simulation produced 0 organic posts/comments (hollow) — report must not cite it as evidence")
        if dead_letters:
            issues.append(
                f"{dead_letters} graph-feedback episode(s) in the dead-letter queue — "
                "report may read an episode-starved graph (replay via replay_zep_dead_letters.py)")
        health = "degraded" if issues else "ok"
        return health, issues, meta

    def _enforce_pipeline_health(self, state: PipelineState) -> None:
        """Aggregate stage health into state.options['pipeline_health']; HARD-FAIL (raise →
        status=failed) when the report deliverable is empty. Flag-gated + degrade-safe."""
        if not getattr(Config, "PIPELINE_HEALTH_GATE", True):
            return
        health: dict[str, Any] = {"status": "ok", "stages": {}}
        hard_issues: list[str] = []
        try:
            rh, ri, rm = self._assess_report_health(state.report_id)
            health["stages"]["report"] = {"health": rh, "issues": ri, **rm}
            if rh == "failed":
                hard_issues = ri
            if state.simulation_id:
                sh, si, sm = self._assess_run_health(state.simulation_id, graph_id=state.graph_id)
                health["stages"]["run"] = {"health": sh, "issues": si, **sm}
                if sh != "ok" and "run" in state.stages and not state.stages["run"].error:
                    state.stages["run"].error = "；".join(si) or None
            # KG-5/LOOP-003: 建图跳块或 destructive prune 未通过物理后置条件 → graph 降级。
            graph_issues: list[str] = []
            graph_meta: dict = {}
            _gskip = state.options.get("graph_ingest_degraded_ratio")
            if _gskip is not None:
                graph_issues.append(
                    f"graph build skipped {float(_gskip) * 100:.0f}% of chunks "
                    f"({state.options.get('graph_skipped_chunks')}/"
                    f"{state.options.get('graph_total_chunks')})"
                )
                graph_meta["skipped_ratio"] = _gskip
            _gprune = state.options.get("graph_prune") or {}
            if isinstance(_gprune, dict) and _gprune.get("degraded"):
                graph_issues.append(
                    str(_gprune.get("error") or _gprune.get("skipped_reason")
                        or "graph pruning hard-cap postcondition was not satisfied")
                )
                graph_meta["prune"] = _gprune
            if graph_issues:
                health["stages"]["graph"] = {
                    "health": "degraded",
                    "issues": graph_issues,
                    **graph_meta,
                }
            # RESEARCH-2: a degraded research_quality is a degraded research stage
            # (degrade-only: it never adds a hard issue).
            if getattr(Config, "PIPELINE_HEALTH_RESEARCH_STAGE", False):
                research_stage = _research_health_stage(state.options.get("research_quality"))
                if research_stage is not None:
                    health["stages"]["research"] = research_stage
            degraded = any(s.get("health") in ("degraded", "failed")
                           for s in health["stages"].values())
            health["status"] = "failed" if hard_issues else ("degraded" if degraded else "ok")
            state.options["pipeline_health"] = health
        except Exception as _he:  # noqa: BLE001 — assessment must never itself crash the run
            logger.warning("[%s] 健康评估异常（忽略）: %s", state.pipeline_id, _he)
            return
        if hard_issues:
            raise RuntimeError("交付物健康检查失败（deliverable is broken）: " + "；".join(hard_issues))
        if health["status"] == "degraded":
            logger.warning("[%s] 管线健康降级: %s", state.pipeline_id,
                           json.dumps(health["stages"], ensure_ascii=False)[:400])

    @staticmethod
    def _reset_stage_scorecard_sidecar(state: PipelineState) -> None:
        """EVAL-15: attempt 起点移除上一 attempt 的记分卡侧车与 options 摘要。

        侧车/摘要只描述「到达 finally 块的最近一次 attempt」。本 attempt 若崩溃后被
        reconcile_orphans 收尾（不走 finally），旧结果不得冒充本次，也不得让 CLI 回填把它
        当作管线亲写的证据而跳过。旋钮关闭 = 不动（逐字节不变）。位于 _run 的 try 之前，
        故自身兜住一切异常、绝不抛出。
        """
        if not getattr(Config, "STAGE_SCORECARD_ENABLED", True):
            return
        try:
            from .stage_scorecard import sidecar_path
            _stale = sidecar_path(state.pipeline_id)
            if os.path.exists(_stale):
                os.remove(_stale)
            if state.options.pop("stage_scorecard_summary", None) is not None:
                PipelineManager.save(state)
        except Exception as _rse:  # noqa: BLE001 — 记分卡为观测增益，失败不影响管线
            logger.warning("[%s] 清理上一 attempt 的记分卡失败（忽略）: %s",
                           state.pipeline_id, _rse)

    @staticmethod
    def _write_stage_scorecard_sidecar(state: PipelineState) -> None:
        """EVAL-15: 确定性分阶段记分卡侧车 <pipeline_dir>/stage_scorecard.json。

        纯投影、绝不是门：不改 status/pipeline_health，不写报告目录；由 _run 的 finally 块在
        每个终态调用（位于任何 try 之外），故自身兜住一切异常、绝不抛出。成功时把
        {stage: passed} 折入 state.options['stage_scorecard_summary']；失败时移除上一 attempt
        的摘要与侧车文件（宁缺毋错——旧结果不得冒充本次结果）。旋钮关闭 = 不写文件、不动
        options（逐字节不变）。
        """
        if not getattr(Config, "STAGE_SCORECARD_ENABLED", True):
            return
        summary = None
        try:
            from .stage_scorecard import summarize_checks, write_stage_scorecard
            summary = summarize_checks(
                write_stage_scorecard(state.pipeline_id, state=state.to_dict()))
        except Exception as _sce:  # noqa: BLE001 — 记分卡为观测增益，失败不影响管线终态
            logger.warning("[%s] 分阶段记分卡写入失败（忽略）: %s", state.pipeline_id, _sce)
            try:
                from .stage_scorecard import sidecar_path
                _stale = sidecar_path(state.pipeline_id)
                if os.path.exists(_stale):
                    os.remove(_stale)
            except Exception as _rme:  # noqa: BLE001
                logger.warning("[%s] 移除上一 attempt 的记分卡失败（忽略）: %s",
                               state.pipeline_id, _rme)
        try:
            if summary is not None:
                state.options["stage_scorecard_summary"] = summary
            else:
                state.options.pop("stage_scorecard_summary", None)
            PipelineManager.save(state)
        except Exception as _sse:  # noqa: BLE001
            logger.warning("[%s] 保存记分卡摘要失败（忽略）: %s", state.pipeline_id, _sse)

    @staticmethod
    def _stage_artifact_specs(state: PipelineState, stage: str) -> list[tuple[str, str]]:
        """T6.3/I-4-3/I-4-6: 单一真源——某阶段「可深链产物」的 (name, 绝对路径) 候选列表。

        完成时登记（_record_stage_artifacts）、复用前完整性校验（_validate_reuse）、
        运行中临时产物发现（_discover_partial_artifacts）三处共用，避免三套各写一份文件名清单
        造成漂移。仅返回候选路径，不检查存在性（调用方按需过滤）。
        """
        hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
        specs: list[tuple[str, str]] = []
        if stage == STAGE_RESEARCH:
            specs.append(("report", os.path.join(hd, "research_report.md")))
            specs.append(("actor_dossier", os.path.join(hd, "actor_dossier.md")))
            specs.append(("dossier", os.path.join(hd, "actors.json")))
            specs.append(("timeline", os.path.join(hd, "timeline.json")))
            specs.append(("sources", os.path.join(hd, "sources.json")))
            specs.append(("quantitative", os.path.join(hd, "quantitative.json")))
            specs.append(("contested", os.path.join(hd, "contested.json")))
            # REPORT-7 (RESEARCH_VERIFIED_FACTS): v3's claim/figure-to-page-span projection;
            # optional (absent with the knob off, on legacy runs and older handoffs).
            specs.append(("verified_facts", os.path.join(hd, "verified_facts.json")))
            # RESEARCH-11 (RESEARCH_QUESTION_SPEC): v3's operational definition of the
            # question (drf.question_spec/v1), written at plan time; optional (absent
            # with the knob off, on legacy runs and older handoffs).
            specs.append(("question_spec", os.path.join(hd, "question_spec.json")))
            specs.append(("prediction_markets", os.path.join(hd, "prediction_markets.json")))
            specs.append(("market_price_history", os.path.join(hd, "market_price_history.json")))
            specs.append(("prediction_market_candidates",
                          os.path.join(hd, "prediction_market_candidates.jsonl")))
            specs.append(("research_budget", os.path.join(hd, "research_budget.json")))
            specs.extend(PipelineOrchestrator._viz_artifact_specs(hd))
        elif stage == STAGE_ONTOLOGY:
            specs.append(("ontology", os.path.join(hd, "ontology.json")))
        elif stage == STAGE_GRAPH:
            specs.append(("communities", os.path.join(hd, "communities.json")))
            specs.append((
                "actor_graph_seed_manifest",
                os.path.join(hd, ACTOR_GRAPH_SEED_MANIFEST_FILENAME),
            ))
        elif stage == STAGE_PREPARE:
            sim_id = state.simulation_id
            if sim_id:
                sim_dir = os.path.join(Config.OASIS_SIMULATION_DATA_DIR, sim_id)
                specs.append(("initial_posts", os.path.join(sim_dir, "simulation_config.json")))
                specs.append((
                    "simulation_config_manifest",
                    os.path.join(sim_dir, "simulation_config_manifest.json"),
                ))
                for fname in ("twitter_profiles.csv", "reddit_profiles.json"):
                    specs.append(("personas", os.path.join(sim_dir, fname)))
                specs.append(("actor_cast", os.path.join(
                    sim_dir, "actor_cast_manifest.json"
                )))
                specs.append(("twitter_actor_roles", os.path.join(
                    sim_dir, "twitter_profiles_roles.json"
                )))
                specs.append(("reddit_actor_roles", os.path.join(
                    sim_dir, "reddit_profiles_roles.json"
                )))
        elif stage == STAGE_RUN:
            sim_id = state.simulation_id
            if sim_id:
                specs.append(("run_summary",
                              os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id, "run_summary.json")))
        elif stage == STAGE_REPORT:
            # 报告章节逐节落盘（section_NN.md）；运行中可作临时产物深链（见 _discover_partial_artifacts）。
            if state.report_id and bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True)):
                report_dir = ReportManager._get_report_folder(state.report_id)
                specs.append(("report_viz_manifest",
                              os.path.join(report_dir, "viz_manifest.json")))
        return specs

    @staticmethod
    def _charts_manifest_path(hd: str) -> str:
        """Return the producer-aligned charts manifest, with legacy fallback.

        The deterministic research renderer writes ``handoff/charts.json`` and
        keeps rendered assets under ``handoff/charts/``. Older experimental
        producers wrote ``handoff/charts/charts.json``; accept that layout only
        when the canonical file is absent.
        """
        canonical = os.path.join(hd, "charts.json")
        legacy = os.path.join(hd, "charts", "charts.json")
        if os.path.exists(canonical) or not os.path.exists(legacy):
            return canonical
        return legacy

    @staticmethod
    def _viz_artifact_specs(hd: str) -> list[tuple[str, str]]:
        """VIZ-2: 可视化产物通道的「索引文件」候选 (name, 绝对路径)——供 RESEARCH/REPORT 两阶段共用。

        单文件锚点（与 charts/data 目录内动态命名的 png|svg|csv 一一对应地登记不现实，故以索引清单
        为完整性/深链锚）：
          - charts    → handoff/charts.json（图表清单；兼容旧 handoff/charts/charts.json）
          - datasets  → handoff/data/datasets.json（数据集清单，与 charts.json 平行）
        二者均为可选、且在旧跑上不存在：调用方（登记/复用校验/临时产物发现）一律按「文件缺失即跳过」
        自然降级，绝不误伤健康/完整性校验。原始 *.png|svg / *.csv 作为增量证据另经
        _discover_partial_artifacts 目录扫描透出（见该方法）。关闭 PIPELINE_VIZ_ARTIFACTS 时整段返回空。
        """
        if not bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True)):
            return []
        return [
            ("charts", PipelineOrchestrator._charts_manifest_path(hd)),
            ("datasets", os.path.join(hd, "data", "datasets.json")),
        ]

    @staticmethod
    def _viz_dynamic_artifact_specs(hd: str) -> list[tuple[str, str]]:
        """Enumerate bounded chart assets under one artifact root for deep links.

        These files appear only after the final deterministic research-chart
        step, so completion-time registration must not depend on an earlier
        progress-poll scan. Symlinks and unsupported files are excluded.
        """
        charts_dir = os.path.join(hd, "charts")
        if not os.path.isdir(charts_dir):
            return []
        allowed = {".png", ".svg", ".jpg", ".jpeg", ".webp", ".html"}
        out: list[tuple[str, str]] = []
        try:
            for filename in sorted(os.listdir(charts_dir)):
                path = os.path.join(charts_dir, filename)
                if (os.path.splitext(filename)[1].lower() not in allowed
                        or os.path.islink(path) or not os.path.isfile(path)):
                    continue
                out.append((f"chart_{filename}", path))
        except OSError:
            return []
        return out

    @staticmethod
    def _report_viz_dynamic_artifact_specs(report_dir: str) -> list[tuple[str, str]]:
        """Report-owned chart assets, namespaced away from research chart keys."""
        return [
            (f"report_{name}", path)
            for name, path in PipelineOrchestrator._viz_dynamic_artifact_specs(report_dir)
        ]

    @staticmethod
    def _validate_report_viz_references(report_dir: str) -> bool:
        """Validate every file referenced by an existing report viz manifest.

        The integrity manifest hashes ``viz_manifest.json`` itself, but a report
        cannot be safely reused when one of its declared chart assets was deleted,
        truncated, or replaced by a symlink. Visuals remain optional: an absent
        manifest is valid; an existing malformed/dangling manifest is not.
        """
        manifest_path = os.path.join(report_dir, "viz_manifest.json")
        if not os.path.exists(manifest_path):
            return True
        if os.path.islink(manifest_path):
            return False
        try:
            payload = _read_json(manifest_path)
            if isinstance(payload, list):
                items = payload
            elif isinstance(payload, dict) and isinstance(payload.get("items"), list):
                items = payload["items"]
            else:
                return False
            charts_root = os.path.realpath(os.path.join(report_dir, "charts"))
            allowed = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".html", ".mmd"}
            for item in items:
                if not isinstance(item, dict):
                    return False
                for field in ("path", "png_path"):
                    value = item.get(field)
                    if value in (None, ""):
                        continue
                    if (not isinstance(value, str) or "\\" in value or "%" in value
                            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                        return False
                    raw = value.strip().removeprefix("./")
                    parts = raw.split("/")
                    if (len(parts) < 2 or parts[0] != "charts"
                            or any(part in ("", ".", "..") for part in parts)
                            or os.path.splitext(parts[-1])[1].lower() not in allowed):
                        return False
                    candidate = os.path.join(report_dir, *parts)
                    resolved = os.path.realpath(candidate)
                    if (os.path.commonpath([resolved, charts_root]) != charts_root
                            or not os.path.isfile(resolved) or os.path.getsize(resolved) <= 0
                            or any(os.path.islink(os.path.join(charts_root, *parts[1:i]))
                                   for i in range(2, len(parts) + 1))):
                        return False
            return True
        except (OSError, ValueError, TypeError):
            return False

    @staticmethod
    def _clear_report_attempt_artifacts(state: PipelineState) -> None:
        """Remove old REPORT-owned pointers and integrity rows at a new attempt boundary."""
        # EVAL-1: the previous attempt's ledger receipt must not pass for the verdict of
        # the new report (a cancelled/halted attempt never replaces it).
        state.options.pop("forecast_ledger", None)
        stale_names = {
            name for name in list(state.artifacts)
            if name.endswith("_partial") or name == "report_viz_manifest"
            or name.startswith("report_chart_")
        }
        for name in stale_names:
            state.artifacts.pop(name, None)
        try:
            manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
            changed = False
            for name in list(manifest):
                if name == "report_viz_manifest" or name.startswith("report_chart_"):
                    manifest.pop(name, None)
                    changed = True
            if changed:
                PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
        except Exception:  # noqa: BLE001 — cleanup is best-effort; new keys overwrite safely
            pass

    def _record_stage_artifacts(self, state: PipelineState, stage: str) -> None:
        """T6.3: 阶段完成时登记其产物的可深链路径（存在且非空才登记）。

        I-4-3: 同时把每条登记的产物写入 handoff/manifest.json（sha256/字节/产出阶段/schema_ok），
        供后续 resume 复用前做完整性校验（_validate_reuse）。清单写失败仅退化为「无清单」，
        不影响 T6.3 的深链登记。
        """
        recorded: list[tuple[str, str]] = []

        def add_if(name: str, path: Optional[str]) -> bool:
            if path and os.path.exists(path) and os.path.getsize(path) > 0:
                state.artifacts[name] = path
                state.artifacts.pop(f"{name}_partial", None)
                recorded.append((name, path))
                return True
            return False

        if stage == STAGE_PREPARE:
            # personas 取首个存在者（twitter_profiles.csv | reddit_profiles.json）。
            for name, path in self._stage_artifact_specs(state, stage):
                if name == "personas":
                    if add_if("personas", path):
                        break
                else:
                    add_if(name, path)
        else:
            for name, path in self._stage_artifact_specs(state, stage):
                add_if(name, path)

        # Research charts are created at the very end of the subprocess. Register
        # them again at the completion boundary so deep links never depend on a
        # lucky progress-poll scan occurring after rendering.
        if stage == STAGE_RESEARCH and bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True)):
            hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
            for name, path in self._viz_dynamic_artifact_specs(hd):
                add_if(name, path)
        elif (stage == STAGE_REPORT and state.report_id
              and bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True))):
            report_dir = ReportManager._get_report_folder(state.report_id)
            for name, path in self._report_viz_dynamic_artifact_specs(report_dir):
                add_if(name, path)

        # REPORT-7: a research completion describes the whole research artifact set.
        # A research spec file absent at this boundary (the v3 child removes
        # verified_facts.json when RESEARCH_VERIFIED_FACTS is off or its step fails)
        # loses the pointer and manifest row an earlier attempt left; a row whose
        # file is gone fails _validate_reuse, which would re-run research on every
        # later resume.
        stale: list[str] = []
        if stage == STAGE_RESEARCH:
            present = {name for name, _ in recorded}
            stale = [name for name, _ in self._stage_artifact_specs(state, stage) if name not in present]
            for name in stale:
                state.artifacts.pop(name, None)
                state.artifacts.pop(f"{name}_partial", None)

        # I-4-3: 把本阶段实际登记到的产物写入完整性清单。
        if (recorded or stale) and bool(getattr(Config, "PIPELINE_VALIDATE_ARTIFACTS", True)):
            try:
                manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
                removed = [name for name in stale if manifest.pop(name, None) is not None]
                for name, path in recorded:
                    entry = _manifest_entry_for(name, path, stage)
                    if entry is not None:
                        manifest[name] = entry
                if recorded or removed:
                    PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
            except Exception as e:  # noqa: BLE001 — 清单是复用保障，写失败仅退化为无校验
                logger.debug("[%s] 产物清单写出跳过: %s", state.pipeline_id, e)

    def _fail_stage(self, state: PipelineState, stage: str, error: str):
        st = state.stages.setdefault(stage, StageState(name=stage))
        st.status = "failed"
        st.error = error
        st.finished_at = _utcnow()
        PipelineManager.save(state)
        # W9-3：失败也是阶段转换——立即落一版遥测账（失败跑的花费不再消失）。
        self._flush_run_telemetry(state)

    def _halt_for_provider_outage(self, state: PipelineState, task_manager: Any,
                                  error: BaseException) -> None:
        """DEFECT-1：把 ProviderOutageHalt 落成既有的可恢复检查点终态。

        status='failed' + 当前阶段 failed + 明确点名提供方中断与 resume 路径的错误消息；
        熔断器证据快照留在 options['provider_outage_halt']。resume()（POST
        /api/research/<id>/resume）会重置失败阶段的 attempt 并复用其余已完成产物与研究
        断点——与任何其他失败的恢复语义完全一致，不发明并行状态机。
        """
        msg = str(error)
        logger.error(f"[{state.pipeline_id}] 管线因提供方中断止损（可恢复）: {msg}")
        state.status = "failed"
        state.error = msg
        breaker = _outage_breaker_for(state.pipeline_id)
        state.options["provider_outage_halt"] = {
            **(breaker.snapshot() if breaker is not None else {}),
            "provider": str(getattr(Config, "LLM_PROVIDER", "") or "unknown"),
            "halted_at": _utcnow(),
            "halted_stage": state.current_stage,
            "resume": f"POST /api/research/{state.pipeline_id}/resume",
        }
        if state.current_stage:
            self._fail_stage(state, state.current_stage, msg)
        PipelineManager.save(state)
        if state.task_id:
            try:
                task_manager.fail_task(state.task_id, msg)
            except Exception:  # noqa: BLE001 — 任务簿失败不影响状态落盘
                pass

    # -- 内部：产物完整性校验（复用前守卫） (I-4-3) ------------------------

    def _validate_reuse(self, state: PipelineState, stage: str) -> bool:
        """I-4-3: 复用一个标记 completed 的阶段前，按产物清单核验其产物未被半写/截断/篡改。

        对该阶段在清单里登记过的每条产物：重算 sha256 + 字节数与清单比对，并跑轻量 schema 探针。
        任一不符 → 返回 False（调用方应回落到重建并留痕），全部通过 → True。

        语义边界（保守、绝不误杀一次本可复用的产物）：
          - 清单整体缺失（老管线 / 关闭过校验）→ True（按旧的「存在性复用」行为放行）；
          - 某产物在清单里没有条目（阶段产出可选，如无 communities.json）→ 不校验该产物；
          - 清单里有条目但磁盘文件已不存在 → False（产物丢了，必须重建）；
          - sha256 当时未能计算（None）→ 仅比字节数 + schema（无哈希可比时不因此误判）。
        仅在 Config.PIPELINE_VALIDATE_ARTIFACTS 开启时被调用（见各复用分支）。
        """
        manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
        if not manifest:
            if stage == STAGE_REPORT and state.report_id:
                return self._validate_report_viz_references(
                    ReportManager._get_report_folder(state.report_id))
            return True  # 无清单 → 退化到旧的存在性复用，保持向后兼容
        ok = True
        # ``personas`` deliberately has two alternative candidate paths. Group by
        # logical artifact name so a recorded reddit profile does not also require
        # twitter_profiles.csv. More importantly, the manifest path must belong to
        # the *current* stage identity. Previously an old sim's perfectly valid
        # run_summary could satisfy a new PREPARE attempt because only the stored
        # path's bytes/hash were checked.
        candidates_by_name: dict[str, list[str]] = {}
        for name, path in self._stage_artifact_specs(state, stage):
            candidates_by_name.setdefault(name, []).append(path)

        for name, candidates in candidates_by_name.items():
            entry = manifest.get(name)
            if not isinstance(entry, dict):
                continue  # 该产物未登记（可选 / 老清单）→ 不校验

            declared_path = entry.get("path")
            if isinstance(declared_path, str) and declared_path:
                expected_paths = {
                    os.path.realpath(os.path.abspath(candidate))
                    for candidate in candidates
                }
                declared_real = os.path.realpath(os.path.abspath(declared_path))
                if declared_real not in expected_paths:
                    logger.warning(
                        "[%s] 复用校验：产物 %s 属于另一 attempt（manifest=%s, current=%s）",
                        state.pipeline_id, name, declared_path, candidates,
                    )
                    ok = False
                    break
                paths_to_check = [declared_path]
            else:
                # Very old manifests may not carry a path. Try each logical
                # alternative and accept the one whose bytes/hash/schema match.
                paths_to_check = candidates

            matched = False
            for man_path in paths_to_check:
                if not os.path.exists(man_path):
                    continue
                try:
                    size = os.path.getsize(man_path)
                except OSError:
                    continue
                exp_bytes = entry.get("bytes")
                if isinstance(exp_bytes, int) and exp_bytes != size:
                    continue
                exp_sha = entry.get("sha256")
                if isinstance(exp_sha, str) and exp_sha:
                    cur_sha = _sha256_file(man_path)
                    if cur_sha is not None and cur_sha != exp_sha:
                        continue
                if not _probe_artifact_schema(name, man_path):
                    continue
                matched = True
                break
            if not matched:
                logger.warning(
                    "[%s] 复用校验：产物 %s 缺失、内容变更或结构探针未通过（%s）",
                    state.pipeline_id, name, paths_to_check,
                )
                ok = False
                break
        if ok and stage == STAGE_REPORT and state.report_id:
            ok = self._validate_report_viz_references(
                ReportManager._get_report_folder(state.report_id))
            if not ok:
                logger.warning("[%s] 复用校验：报告可视化清单含缺失/越界产物", state.pipeline_id)
        return ok

    def _reuse_ok(self, state: PipelineState, stage: str) -> bool:
        """I-4-3: 复用守卫的薄封装——校验关闭时恒 True，开启时调 _validate_reuse。

        各阶段（GRAPH/PREPARE/RUN）的复用分支统一经此判定，校验失败时由调用方
        把对应阶段降级重建，并写 resumed_stage_validation 面包屑（与既有图谱重建路径同构）。
        校验器本身异常时必须 fail closed：缺失清单的兼容路径已经由
        ``_validate_reuse`` 显式放行，异常意味着身份/完整性未被证明。
        """
        if not bool(getattr(Config, "PIPELINE_VALIDATE_ARTIFACTS", True)):
            return True
        try:
            return self._validate_reuse(state, stage)
        except Exception as e:  # noqa: BLE001 — 未证明完整性时拒绝复用
            state.options["artifact_validation_error"] = {
                "stage": stage,
                "error": str(e)[:300],
                "at": _utcnow(),
            }
            logger.warning("[%s] %s 复用校验异常（拒绝复用）: %s",
                           state.pipeline_id, stage, e)
            return False

    @staticmethod
    def _run_reuse_ready(state: PipelineState, sim_state: Any) -> bool:
        """Return whether a completed RUN can belong to the current simulation.

        The stage bit alone is not provenance. A rebuilt PREPARE attempt creates a
        fresh READY simulation while the persisted RUN bit can still say completed.
        Reuse is therefore allowed only for the same simulation identity in a
        terminal COMPLETED state. A missing summary remains recoverable for legacy
        runs and is generated once by ``_publish_run_summary``.
        """
        sim_id = state.simulation_id
        if not sim_id or sim_state is None:
            return False
        if str(getattr(sim_state, "simulation_id", "")) != str(sim_id):
            return False
        status = getattr(sim_state, "status", None)
        status_value = getattr(status, "value", status)
        if status_value != SimulationStatus.COMPLETED.value:
            return False

        summary_path = os.path.join(
            SimulationRunner.RUN_STATE_DIR, sim_id, "run_summary.json")
        if not os.path.exists(summary_path):
            return True  # Legacy completed run; regenerate from preserved raw data.
        summary = _read_json(summary_path)
        if not isinstance(summary, dict):
            return False
        summary_sim_id = summary.get("simulation_id")
        if summary_sim_id not in (None, "", sim_id):
            return False
        return _probe_artifact_schema("run_summary", summary_path)

    @staticmethod
    def _sim_platform_completion_missing(sim_id: str, run_state: Any = None) -> list[str]:
        """返回缺少权威完成证据的启用平台清单（空清单 = 完成证据齐全）。

        逐平台的证据 = run_state 持久化的 ``*_completed`` 位 **或** 该平台
        actions.jsonl 尾部的 ``simulation_end`` 事件。位优先（旧的已清理运行可能只剩
        run_state），文件兜底（后端重启窗口里 run_state 可能停在 RUNNING/FAILED，而
        detached 子进程早已干净收尾——actions.jsonl 由子进程直写，不会说谎）。
        启用集合取 run_state 的 ``*_enabled``；两者皆缺（legacy）时回退「actions.jsonl
        存在即启用」（与 SimulationRunner._check_all_platforms_completed 同构）。
        任何证据都不存在时返回 ``["<no-platform-evidence>"]``（fail closed）。
        """
        sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, str(sim_id or ""))
        tw_enabled = bool(getattr(run_state, "twitter_enabled", False) or False)
        rd_enabled = bool(getattr(run_state, "reddit_enabled", False) or False)
        if not tw_enabled and not rd_enabled:
            tw_enabled = os.path.exists(os.path.join(sim_dir, "twitter", "actions.jsonl"))
            rd_enabled = os.path.exists(os.path.join(sim_dir, "reddit", "actions.jsonl"))
        if not tw_enabled and not rd_enabled:
            return ["<no-platform-evidence>"]
        missing: list[str] = []
        for platform, enabled in (("twitter", tw_enabled), ("reddit", rd_enabled)):
            if not enabled:
                continue
            if run_state is not None and bool(
                getattr(run_state, f"{platform}_completed", False)
            ):
                continue
            if _actions_simulation_end_present(
                os.path.join(sim_dir, platform, "actions.jsonl")
            ):
                continue
            missing.append(platform)
        return missing

    def _completed_sim_reusable(
        self, state: PipelineState, sim_state: Any
    ) -> tuple[bool, str]:
        """DEFECT-1 探测器：磁盘上是否已有可复用的「同一密封配置的已完成模拟」。

        stage 位不是证据（崩溃/重启会把它抹掉）；复用资格由三层磁盘证据构成：
          1. **完成标记**：每个启用平台的 ``simulation_end``（位或 actions.jsonl 尾部，
             与 DEFECT-2 完成证据门共用探针——rc=0 的 hollow 运行在此即被拒绝复用）；
          2. **run_summary**：存在则必须结构有效且属于本模拟（半写/异构 → 不可复用；
             缺失可由复用路径按完整动作日志回填，随后仍受完成证据门硬校验）；
          3. **身份**：与 runner 启动边界（LOOP-011）同一把最严校验——
             ``validate_simulation_config_seal`` 按 prepared state 指纹核验
             simulation_config_manifest ↔ 配置字节 ↔ cast/context/role 闭包；另有
             运行期见证（reddit_runtime_system_messages.json 携带子进程启动时验证过的
             seal SHA）时必须与当前 seal 一致，把「这场已完成的运行」和「当前密封配置」
             直接绑死。无任何 seal 身份可核验（pre-seal 遗留）→ fail closed 照旧重跑。
        返回 ``(可复用, 不可复用原因)``；探测自身异常一律 fail closed。
        """
        try:
            if not _sim_reuse_completed_enabled():
                return False, "sim_resume_reuse_completed_disabled"
            sim_id = state.simulation_id
            if not sim_id or sim_state is None:
                return False, "no_simulation_identity"
            if str(getattr(sim_state, "simulation_id", "")) != str(sim_id):
                return False, "simulation_identity_mismatch"
            sim_dir = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id)
            if not os.path.isdir(sim_dir):
                return False, "simulation_dir_missing"
            rs = SimulationRunner.get_run_state(sim_id)
            # 仍有存活进程在跑回合（尚未完成）→ 绝不把半成品文件当完成结果复用。
            if rs is not None and rs.runner_status in (
                RunnerStatus.STARTING, RunnerStatus.RUNNING,
            ):
                try:
                    if SimulationRunner._is_simulation_alive(rs):
                        return False, "simulation_process_still_running"
                except Exception:  # noqa: BLE001 — 存活性未知时保守拒绝复用
                    return False, "simulation_liveness_unknown"
            missing = self._sim_platform_completion_missing(sim_id, rs)
            if missing:
                return False, "missing_simulation_end:" + ",".join(missing)
            summary_path = os.path.join(sim_dir, "run_summary.json")
            if os.path.exists(summary_path):
                summary = _read_json(summary_path)
                if not isinstance(summary, dict):
                    return False, "run_summary_invalid"
                if summary.get("simulation_id") not in (None, "", sim_id):
                    return False, "run_summary_identity_mismatch"
                if not _probe_artifact_schema("run_summary", summary_path):
                    return False, "run_summary_schema_invalid"
            expected_manifest = str(getattr(
                sim_state, "simulation_config_manifest_sha256", "") or "")
            expected_config = str(getattr(
                sim_state, "simulation_config_sha256", "") or "")
            manifest_path = os.path.join(sim_dir, "simulation_config_manifest.json")
            if not (expected_manifest or expected_config) and not os.path.exists(
                manifest_path
            ):
                return False, "no_config_seal_identity"
            from .simulation_manager import validate_simulation_config_seal
            try:
                seal = validate_simulation_config_seal(
                    sim_dir,
                    expected_manifest_sha256=expected_manifest or None,
                    expected_config_sha256=expected_config or None,
                    expected_simulation_id=sim_id,
                    require=True,
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as seal_err:
                return False, f"config_seal_mismatch:{str(seal_err)[:160]}"
            sealed_manifest_sha = str((seal or {}).get("manifest_sha256") or "")
            attest = _read_json(os.path.join(
                sim_dir, "reddit_runtime_system_messages.json"))
            if isinstance(attest, dict):
                attest_sha = str(
                    attest.get("simulation_config_manifest_sha256") or "")
                if attest_sha and sealed_manifest_sha and attest_sha != sealed_manifest_sha:
                    return False, "runtime_attestation_seal_mismatch"
            return True, ""
        except Exception as e:  # noqa: BLE001 — 未证明身份/完整性时拒绝复用
            return False, f"reuse_check_error:{str(e)[:160]}"

    def _require_run_completion_evidence(
        self,
        state: PipelineState,
        sim_id: str,
        run_state: Any,
        summary_published: bool,
    ) -> None:
        """DEFECT-2 hollow-run 完成证据门（RUN 完成边界，新跑与复用共用）。

        进程退出码 / stage 位 / 状态投影都不是完成证据（bug-sweep：子进程可以 rc=0
        退出却从未产出 simulation_end，下游把它当成功消费）。权威证据 =「每个启用平台
        的 simulation_end 完成标记」+「有效 run_summary.json」。缺任一 → 以清晰讯息抛
        RuntimeError（RUN 阶段判失败、可 resume；与 DEFECT-1 组合：该结果同样不可复用）。
        """
        missing = self._sim_platform_completion_missing(sim_id, run_state)
        if missing:
            raise RuntimeError(
                "模拟未产出完成证据：启用平台缺少 simulation_end 完成标记"
                f"（{', '.join(missing)}）。进程退出码不是完成证据——该运行按 RUN 阶段"
                "失败处理，产物不可复用；修复后可 resume 重跑模拟"
            )
        if not summary_published:
            raise RuntimeError(
                "模拟完成证据不完整：run_summary.json 缺失或结构无效。该运行按 RUN "
                "阶段失败处理，产物不可复用；修复后可 resume 重跑模拟"
            )

    def _publish_run_summary(
        self,
        state: PipelineState,
        simulation_id: str,
        *,
        communities: Any = None,
        regenerate: bool,
    ) -> bool:
        """Generate a new summary when needed, otherwise preserve the reused bytes.

        Re-running the aggregator unconditionally used to overwrite a valid reused
        summary. If PREPARE had changed identity, that produced a plausible-looking
        but hollow ``0 agents / 0 rounds`` file under the new simulation id. This
        method makes reuse read-only and only backfills a missing legacy summary.
        """
        summary_path = os.path.join(
            SimulationRunner.RUN_STATE_DIR, simulation_id, "run_summary.json")
        summary_exists = (
            os.path.exists(summary_path) and os.path.getsize(summary_path) > 0
            and _probe_artifact_schema("run_summary", summary_path)
        )
        if regenerate or not summary_exists:
            SimulationRunner.write_run_summary(simulation_id, communities=communities)

        if not (os.path.exists(summary_path) and os.path.getsize(summary_path) > 0
                and _probe_artifact_schema("run_summary", summary_path)):
            return False

        state.artifacts["run_summary"] = summary_path
        PipelineManager.save(state)
        if bool(getattr(Config, "PIPELINE_VALIDATE_ARTIFACTS", True)):
            manifest = PipelineManager.load_artifact_manifest(state.pipeline_id)
            entry = _manifest_entry_for("run_summary", summary_path, STAGE_RUN)
            if entry is not None:
                manifest["run_summary"] = entry
                PipelineManager.write_artifact_manifest(state.pipeline_id, manifest)
        return True

    # -- 内部：运行中临时产物深链 (I-4-6) ----------------------------------

    @staticmethod
    def _discover_partial_artifacts(state: PipelineState, stage: str) -> list[dict[str, Any]]:
        """I-4-6: best-effort 发现某阶段「此刻已落盘」的临时产物（含字节/mtime，标记 provisional）。

        长且大多无声的阶段（深度研究、多轮模拟、多章节报告）正是用户最需要增量证据来
        判断是否取消的地方。本方法只读目录元信息（cheap），不解析内容；返回的每条都带
        provisional 标记，供 UI/API 永不把临时产物当成最终产物。
        REPORT 额外扫描 section_NN.md（逐节落盘），RUN 额外扫描尚未聚合的 actions/run-state。
        """
        out: list[dict[str, Any]] = []
        seen: set[str] = set()

        def _stat(name: str, path: str) -> None:
            if not path or path in seen or not os.path.exists(path):
                return
            try:
                size = os.path.getsize(path)
                mtime = os.path.getmtime(path)
            except OSError:
                return
            if size <= 0:
                return
            seen.add(path)
            out.append({
                "name": name,
                "path": path,
                "bytes": size,
                "mtime": datetime.fromtimestamp(mtime, timezone.utc).isoformat(),
                "provisional": True,
            })

        # 1) 阶段已知产物（与完成时登记同源，但此处不要求阶段已完成）。
        for name, path in PipelineOrchestrator._stage_artifact_specs(state, stage):
            _stat(name, path)

        # 2) 阶段特有的「过程中产物」（完成时清单未涵盖的逐步落盘文件）。
        try:
            if stage == STAGE_RESEARCH:
                hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                _stat("research_report", os.path.join(hd, "research_report.md"))
                _stat("research_progress", os.path.join(hd, "research_progress.log"))
            elif stage == STAGE_RUN:
                sim_id = state.simulation_id
                if sim_id:
                    rsd = os.path.join(SimulationRunner.RUN_STATE_DIR, sim_id)
                    _stat("run_state", os.path.join(rsd, "run_state.json"))
                    # actions.jsonl 按平台分目录（twitter/ reddit/）逐行 append，运行中即可观测。
                    for _plat in ("twitter", "reddit"):
                        _stat(f"actions_{_plat}", os.path.join(rsd, _plat, "actions.jsonl"))
            elif stage == STAGE_REPORT:
                # 报告章节逐节写入 ReportManager 的报告目录；扫描 section_*.md 排序后透出。
                rid = state.report_id
                if rid:
                    try:
                        rep_dir = ReportManager._get_report_folder(rid)
                    except Exception:  # noqa: BLE001
                        rep_dir = None
                    if rep_dir and os.path.isdir(rep_dir):
                        for fn in sorted(os.listdir(rep_dir)):
                            if fn.startswith("section_") and fn.endswith(".md"):
                                _stat(fn[:-3], os.path.join(rep_dir, fn))
            # VIZ-2: each stage scans its own visual root. Research assets live in
            # handoff/charts; final-report assets live in reports/<id>/charts.
            if stage == STAGE_RESEARCH and bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True)):
                hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                for _name, _path in PipelineOrchestrator._viz_dynamic_artifact_specs(hd):
                    _stat(_name, _path)
                _ddir = os.path.join(hd, "data")
                if os.path.isdir(_ddir):
                    for fn in sorted(os.listdir(_ddir)):
                        if fn.endswith(".csv"):
                            _stat(f"dataset_{fn}", os.path.join(_ddir, fn))
            elif (stage == STAGE_REPORT and state.report_id
                  and bool(getattr(Config, "PIPELINE_VIZ_ARTIFACTS", True))):
                _report_dir = ReportManager._get_report_folder(state.report_id)
                for _name, _path in PipelineOrchestrator._report_viz_dynamic_artifact_specs(
                        _report_dir):
                    _stat(_name, _path)
        except Exception:  # noqa: BLE001 — 发现是观测增益，永不抛出
            pass
        return out

    def _register_partial_artifacts(self, state: PipelineState, stage: str) -> None:
        """I-4-6: 运行中把新出现的临时产物以 provisional 键登记进 state.artifacts（节流、不覆盖正式产物）。

        节流：同一阶段每隔 PIPELINE_PARTIAL_SCAN_EVERY_S 秒最多扫一次磁盘（默认 10s），
        避免在每次进度回调（可能秒级多次）都做目录 stat。登记键形如 'report_partial'，与完成时
        登记的正式键（'run_summary' 等）分离，确保完成产物永不被临时产物覆盖。
        关闭 PIPELINE_LIVE_ARTIFACTS 时整段 no-op（行为回到只在完成时登记）。
        """
        if not bool(getattr(Config, "PIPELINE_LIVE_ARTIFACTS", True)):
            return
        now = time.time()
        every = float(getattr(Config, "PIPELINE_PARTIAL_SCAN_EVERY_S", 10) or 10)
        # 节流戳存在 orchestrator 实例（每次 _run 新建一个实例，更新器闭包持有它），
        # 仅在本次运行内跨调用有效——刻意不落到 state.options，避免污染持久化状态文件。
        throttle = self._partial_scan_at
        last = throttle.get(stage)
        if isinstance(last, (int, float)) and (now - last) < every:
            return
        throttle[stage] = now
        try:
            partials = self._discover_partial_artifacts(state, stage)
        except Exception:  # noqa: BLE001
            return
        for p in partials:
            name = p.get("name")
            path = p.get("path")
            if not name or not path:
                continue
            key = f"{name}_partial"
            # 正式产物（同名非 _partial 键）已登记则不再重复打临时键，避免冗余。
            if name in state.artifacts:
                continue
            state.artifacts[key] = path

    # -- 内部：ETA / spend 心跳估计 (I-5-6) --------------------------------

    def estimate_eta(self, state: PipelineState) -> dict[str, Any]:
        """I-5-6: 从已有数据廉价推导 elapsed / 近似 ETA / staleness（不发任何请求）。

        ETA 用「当前 global_progress 占比 vs 自 created_at 起的已耗时」线性外推剩余时间——刻意标注
        approximate（管线各阶段速率差异大，仅作量级参考）。stale 判定：自 last_progress_at（无则
        updated_at）起超过 PIPELINE_STALE_S 秒未更新 → True（UI 显示「仍在思考」而非「卡死」）。
        终态（completed/failed/cancelled）下 eta=0、不再 stale。供状态 API 增量拼进响应（纯附加字段）。
        """
        out: dict[str, Any] = {
            "elapsed_s": None,
            "eta_s": None,
            "eta_approximate": True,
            "stale": False,
            "last_progress_age_s": None,
        }
        # ORCH-7: 恢复过的管线以 resumed_at 为耗时锚——created_at 可能是数天前，用它线性外推
        # 会立刻顶到 PIPELINE_ETA_CAP_S（resume_count=5 的管线每个会话 ETA 全是噪声）。
        status = state.status
        terminal = status in ("completed", "failed", "cancelled")
        _anchor = state.options.get("resumed_at") if isinstance(state.options, dict) else None
        anchor_age = _age_seconds(_anchor) if _anchor else None
        if anchor_age is None:
            anchor_age = _age_seconds(state.created_at)
        if terminal:
            # i8（F2 取证）：终态 elapsed 此前是「距现在的年龄」——一条 33 天前完成的
            # 管线报 elapsed_s≈2,855,077。终态耗时应冻结在 anchor→updated_at 的真实
            # 运行时长；时间戳缺失/倒挂 → 省略而非给误导数字。
            end_age = _age_seconds(state.updated_at)
            elapsed = (
                anchor_age - end_age
                if (anchor_age is not None and end_age is not None
                    and anchor_age >= end_age)
                else None
            )
        else:
            elapsed = anchor_age
        if elapsed is not None:
            out["elapsed_s"] = int(elapsed)
        # staleness：仅对在飞管线有意义。
        ref = state.last_progress_at or state.updated_at
        age = _age_seconds(ref)
        if age is not None:
            out["last_progress_age_s"] = int(age)
        if not terminal and age is not None:
            stale_s = float(getattr(Config, "PIPELINE_STALE_S", 300) or 300)
            out["stale"] = age > stale_s
        # ETA：线性外推（progress→剩余时间）。需要正进度与正耗时。
        if terminal:
            out["eta_s"] = 0
        else:
            prog = max(0, min(100, int(state.global_progress or 0)))
            if elapsed is not None and elapsed > 0 and 0 < prog < 100:
                remaining = elapsed * (100 - prog) / prog
                # 夹取到合理上限，避免极早期（prog=1）外推出离谱数字误导用户。
                cap = float(getattr(Config, "PIPELINE_ETA_CAP_S", 7200) or 7200)
                out["eta_s"] = int(min(remaining, cap))
        return out

    def heartbeat_status(self, state: PipelineState) -> dict[str, Any]:
        """I-4-1/I-5-6: 汇总 ETA/staleness 心跳 + （计量开启时）当前累计花费，供状态 API 透出。

        spend_so_far 来自 LLMMeter.snapshot（进程内累计，仅对本进程在飞的管线有数据；
        重启后或别的 worker 的管线读不到 → 省略该字段，不臆造）。整体 best-effort。
        """
        info = self.estimate_eta(state)
        # owner/心跳液体性（reconcile 也用同一判据，这里只读不改）。
        info["owner_pid"] = state.owner_pid
        info["owner_alive"] = _pid_alive(state.owner_pid) if state.owner_pid else None
        hb_age = _age_seconds(state.heartbeat_at)
        info["heartbeat_age_s"] = int(hb_age) if hb_age is not None else None
        if bool(getattr(Config, "LLM_TELEMETRY_ENABLED", True)):
            try:
                from ..utils.telemetry import LLMMeter
                snap = LLMMeter.snapshot(state.pipeline_id)
                tot = snap.get("total") or {}
                # 仅在确有计量数据时透出（全 0 视为「本进程无数据」省略）。
                if tot.get("total_tokens") or tot.get("cost_usd"):
                    info["spend_so_far"] = {
                        "tokens": tot.get("total_tokens"),
                        "cost_usd": tot.get("cost_usd"),
                    }
            except Exception:  # noqa: BLE001
                pass
        return info

    # -- 内部：心跳看护线程 (I-4-1) ----------------------------------------

    def _start_heartbeat(self, state: PipelineState) -> Optional[threading.Event]:
        """I-4-1: 钉入 owner 指纹并启动壁钟心跳看护线程。返回用于在 finally 停止它的 Event。

        看护线程独立于阶段进度，每 PIPELINE_HEARTBEAT_INTERVAL_S 秒原子刷新一次 heartbeat_at
        （走 touch_heartbeat 轻量直写，不触发 full save）。即便研究子进程/persona 生成长时间无
        进度回调，心跳仍在跳，让别的进程的 reconcile_orphans 看到「这条管线还活着」。
        关闭 PIPELINE_HEARTBEAT_ENABLED 时不启动线程、不写 owner（回退旧的 _threads 判定），返回 None。
        """
        if not bool(getattr(Config, "PIPELINE_HEARTBEAT_ENABLED", True)):
            return None
        # 钉入 owner 指纹 + 首拍心跳（即便随后看护线程才起，状态文件也已带 owner/心跳）。
        try:
            state.owner_pid = os.getpid()
            state.owner_boot_id = _BOOT_ID
            state.heartbeat_at = _utcnow()
        except Exception:  # noqa: BLE001
            pass
        interval = float(getattr(Config, "PIPELINE_HEARTBEAT_INTERVAL_S", 30) or 30)
        stop = threading.Event()
        pid = os.getpid()

        def _beat() -> None:
            # 立即落一拍，再按节律续跳，直到 _run 在 finally 置位 stop。
            while not stop.wait(interval):
                try:
                    if not PipelineManager.touch_heartbeat(state.pipeline_id, pid=pid):
                        # 状态已非 running（终态）→ 无需再跳，提前退出看护线程。
                        return
                except Exception as e:  # noqa: BLE001 — 心跳失败不得拖垮管线
                    logger.debug("[%s] 心跳刷新跳过: %s", state.pipeline_id, e)
                # W9-3：心跳节律上的遥测 flush 检查点——覆盖长时间无进度回调的窗口
                # （集成种子/深研究静默期），LLM 调用每新增 N 次都会被落盘。
                try:
                    self._maybe_flush_run_telemetry(state)
                except Exception:  # noqa: BLE001
                    pass

        t = threading.Thread(target=_beat, name=f"pipeline-hb-{state.pipeline_id}", daemon=True)
        t.start()
        return stop

    # -- 内部：可复现性清单 run.json (I-8-1) -------------------------------

    def _write_run_manifest(self, state: PipelineState) -> None:
        """I-8-1: 在管线启动时写出首版 run.json（best-effort，绝不阻断运行）。

        与 _persist_env 一样整体包 try/except：清单写失败只是少了审计产物，
        不能让它拖垮一次真正的预测运行。RECORD_RUN_MANIFEST=false 时整段跳过。
        """
        if not bool(getattr(Config, "RECORD_RUN_MANIFEST", True)):
            return
        try:
            from ..utils.security import redact_secrets
            from ..utils.atomic import write_json_atomic
            manifest = _build_run_manifest(state)
            if bool(getattr(Config, "RUN_SHAPE_PIN", True)):
                manifest = self._fold_prior_run_manifest(state, manifest)
            manifest = redact_secrets(manifest)
            write_json_atomic(PipelineManager.manifest_path(state.pipeline_id), manifest)
            # 登记可深链指针，供 StageTimeline / GET /manifest 复用。
            if isinstance(state.artifacts, dict):
                state.artifacts["run_manifest"] = PipelineManager.manifest_path(state.pipeline_id)
        except Exception as e:  # noqa: BLE001 — 清单是观测产物，写失败必须静默降级
            logger.debug("[%s] run.json 写出跳过: %s", state.pipeline_id, e)

    def _fold_prior_run_manifest(self, state: PipelineState,
                                 manifest: dict[str, Any]) -> dict[str, Any]:
        """INFRA-7: keep run.json history across attempts instead of rewriting it.

        The previous run.json's ``resolved`` blocks are carried forward (a
        reused stage keeps the stamp of the attempt that produced it; stages
        recomputed this attempt are restamped in ``_complete_stage``), one
        ``attempts`` entry is appended (capped), and the pinned run shape plus
        this attempt's drift are published under ``run_shape``.
        """
        # carry_forward_resolved deep-copies, so this attempt's fresh blocks stay
        # untouched for restamping recomputed research/simulation blocks.
        self._fresh_resolved = manifest.get("resolved") or {}
        prior = _read_json(PipelineManager.manifest_path(state.pipeline_id))
        prior = prior if isinstance(prior, dict) else {}
        manifest["resolved"] = run_shape.carry_forward_resolved(
            prior.get("resolved"), manifest.get("resolved"))
        if bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True)):
            # INFRA-8: PREPARE's model-provenance block is not a run-shape block.
            model_provenance.carry_forward_extra_blocks(prior.get("resolved"), manifest["resolved"])
        pinned = (state.options or {}).get("run_shape_v1")
        pinned = pinned if isinstance(pinned, dict) else None
        try:
            drift = self._run_shape_drift(state)
        except Exception as exc:  # noqa: BLE001 — 漂移判定由 _check_run_shape_drift 负责
            logger.debug("[%s] run.json 漂移摘要跳过: %s", state.pipeline_id, exc)
            drift = None
        manifest["attempts"] = run_shape.append_capped(
            prior.get("attempts"),
            run_shape.attempt_record(_utcnow(), pinned, drift),
            run_shape.ATTEMPTS_CAP,
        )
        manifest["run_shape"] = {"pin": pinned, "drift": drift}
        return manifest

    def _update_manifest(self, state: PipelineState, stage: str,
                         total_rounds: Optional[int] = None,
                         temporal: Optional[dict] = None) -> None:
        """I-8-1: 阶段进入时把当前解析出的 provider/model（可热切换）钉入 run.json。

        读出现有清单，更新对应 stage 的 resolved.provider/model_name（ontology/graph/report）
        与 simulation.total_rounds，原子写回。任何异常静默吞掉。
        CAL：temporal 给出时把 calendar_unit/n_rounds/horizon_date 一并钉入 resolved.simulation。
        """
        if not bool(getattr(Config, "RECORD_RUN_MANIFEST", True)):
            return
        try:
            if stage == STAGE_RUN:
                # INFRA-7：记下本 attempt 的 RUN 实际写入的运行期字段——RUN 重算的阶段戳只保留这些，
                # 不沿用被替换模拟的旧值。
                _runtime = self._attempt_sim_runtime()
                if total_rounds is not None:
                    _runtime["total_rounds"] = int(total_rounds)
                for _k in ("calendar_unit", "n_rounds", "horizon_date"):
                    if temporal and temporal.get(_k) is not None:
                        _runtime[_k] = temporal[_k]
            from ..utils.security import redact_secrets
            from ..utils.atomic import write_json_atomic
            path = PipelineManager.manifest_path(state.pipeline_id)
            manifest = _read_json(path)
            if not isinstance(manifest, dict):
                # 清单缺失（如老管线 resume）：重建首版骨架。
                manifest = redact_secrets(_build_run_manifest(state))
            resolved = manifest.setdefault("resolved", {})
            # INFRA-7：RUN_SHAPE_PIN 开启时 provider 戳改在 _complete_stage 按「是否重算」落下——
            # 阶段进入时尚不知是否复用，此处重戳会把复用阶段的出处改写成当前 provider。
            if (stage in (STAGE_ONTOLOGY, STAGE_GRAPH, STAGE_REPORT)
                    and not bool(getattr(Config, "RUN_SHAPE_PIN", True))):
                resolved[stage] = _current_provider_pair()
            if total_rounds is not None:
                sim = resolved.setdefault("simulation", {})
                sim["total_rounds"] = int(total_rounds)
            if temporal:
                sim = resolved.setdefault("simulation", {})
                for _k in ("calendar_unit", "n_rounds", "horizon_date"):
                    if temporal.get(_k) is not None:
                        sim[_k] = temporal[_k]
            manifest["updated_at"] = _utcnow()
            write_json_atomic(path, redact_secrets(manifest))
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] run.json 更新跳过: %s", state.pipeline_id, e)

    # -- 内部：研究阶段遥测 (I-5-7) ----------------------------------------

    def _record_research_telemetry(self, state: PipelineState,
                                   telemetry: Optional[dict[str, Any]]) -> None:
        """I-5-7: 把 DeerFlowResearchRunner 返回的研究遥测纳入统一计量。

        (1) 始终 stash 到 state.options['research_telemetry']（即使计量关闭，也是免费观测）；
        (2) 计量开启且确有 token 时，向 LLMMeter 写一条 stage='research' 的合成记录，
            让 run_telemetry.json 的整轮 token/成本 rollup 把最贵的研究阶段也算进去。
        resume 路径无遥测（telemetry=None）→ 直接跳过，保持旧行为。
        """
        if not isinstance(telemetry, dict):
            return
        try:
            state.options["research_telemetry"] = telemetry
            PipelineManager.save(state)
        except Exception:  # noqa: BLE001 — stash 失败不影响主流程
            pass
        if bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True)):
            # INFRA-8: resolved.research.model_id / served_models of this attempt's research;
            # _complete_stage merges them into run.json after INFRA-7 restamps the block.
            self._research_model_provenance = model_provenance.research_stage_record(
                telemetry.get("model_resolution"))
        if not bool(getattr(Config, "LLM_TELEMETRY_ENABLED", True)):
            return
        t_in = int(telemetry.get("tokens_in") or 0)
        t_out = int(telemetry.get("tokens_out") or 0)
        if t_in <= 0 and t_out <= 0:
            return  # 该研究模型未报 usage → 无可计量 token，跳过合成记录
        try:
            # EVAL-17: the runner's summed [usage] cached= reads (no new parsing here); a
            # malformed value degrades to 0 instead of dropping the whole record.
            t_cached = max(0, int(telemetry.get("tokens_cached") or 0))
        except (TypeError, ValueError, OverflowError):
            t_cached = 0
        try:
            from ..utils.telemetry import LLMMeter
            model = str(telemetry.get("model") or getattr(Config, "DEERFLOW_MODEL", "claude"))
            # 研究模型名映射到一个计价 provider 键：CLI 订阅类（claude/codex）边际成本为 0，
            # 其余复用同名 provider 的定价表（缺失则成本 0，仍记 token/延迟）。
            provider = "claude-cli" if model in ("claude", "codex") else model
            wall_ms = float(telemetry.get("wall_s") or 0.0) * 1000.0
            LLMMeter.record(
                provider=provider,
                model=model,
                prompt_tokens=t_in,
                completion_tokens=t_out,
                latency_ms=wall_ms,
                stage=STAGE_RESEARCH,
                run_id=state.pipeline_id,
                prompt_cache_read_tokens=t_cached,
                aggregate=True,  # INFRA-8: the child's whole spend, no call's requested model
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] 研究阶段合成计量跳过: %s", state.pipeline_id, e)

    # -- 内部：模拟阶段遥测 (DEFECT-3) -------------------------------------

    @staticmethod
    def _sim_meter_markers(state: PipelineState) -> tuple[dict[str, Any], bool]:
        """EVAL-17: a copy of the per-simulation sim-meter markers, plus whether the
        pre-EVAL-17 single slot had to be migrated into it.

        The legacy slot only ever held the main run's marker (seeds were never recorded),
        so it migrates as a stage='run' entry; a map entry already present for that
        simulation wins. The caller stores the copy back when it writes.
        """
        stored = state.options.get(SIM_METER_MARKERS_OPTION)
        markers: dict[str, Any] = dict(stored) if isinstance(stored, dict) else {}
        legacy = state.options.get(SIM_METER_LEGACY_MARKER_OPTION)
        legacy_sid = str(legacy.get("simulation_id") or "") if isinstance(legacy, dict) else ""
        if legacy_sid and legacy_sid not in markers:
            markers[legacy_sid] = {
                "meter_run_token": str(legacy.get("meter_run_token") or ""),
                "stage": STAGE_RUN,
                "recorded_at": legacy.get("recorded_at"),
            }
            return markers, True
        return markers, False

    def _record_sim_run_telemetry(
        self, state: PipelineState, simulation_id: Optional[str], *,
        stage: str = STAGE_RUN,
    ) -> None:
        """DEFECT-3: 把模拟子进程落盘的 sim_llm_telemetry.json 纳入统一计量（恰好一次）。

        RUN 的 LLM 调用发生在 detached 子进程——contextvars 与 LLMMeter 都不跨进程，
        这是 run_telemetry.json 拿到模拟花费的唯一入口。镜像 _record_research_telemetry：
        (1) 主模拟（stage='run'）始终 stash 摘要到 state.options['sim_llm_telemetry']
            （计量关闭也是免费观测；INFRA-8 开启时连同子进程逐调用的 model_resolution）；
        (2) 计量开启且确有 token 时，向 LLMMeter 写一条 ``stage`` 的合成记录
            （provider/model 取快照自报值；缺失时按研究路径同款映射兜底——CLI 订阅类
            claude/codex → 'claude-cli' 边际成本 0，其余复用同名 provider 定价表）。

        EVAL-17: ``stage`` is 'run' for the main simulation and SIM_METER_STAGE_ENSEMBLE
        ('ensemble_sim') for an extra ensemble seed's simulation; a seed never touches the
        'sim_llm_telemetry' stash.

        恰好一次（跨 attempt 持久）：state.options[SIM_METER_MARKERS_OPTION][simulation_id]
        记住快照的 ``meter_run_token``（每次子进程启动铸新、同进程重写不变）及 stage/
        recorded_at。同一场运行的后续边界调用（成功收尾、后续 resume 的复用路径）全部跳过；
        重跑产生新 token → 新一笔真实花费照记。标记先持久化、计量后写：中间窗口崩溃宁可
        少记（诚实下限），绝不双计。EVAL-17: markers are kept per simulation, so recording a
        seed can no longer evict the main run's marker. The pre-EVAL-17 single slot
        'sim_llm_telemetry_recorded' is honoured on read and migrated into the map (a resumed
        legacy run never double counts), and is still written for stage='run' so a rollback
        to older code cannot double count the main simulation either. When the marker save
        fails, the marker is rolled back and nothing is metered, so a later boundary or
        resume retries instead of trusting a marker that exists only in memory. The whole
        check-and-mark runs under self._sim_meter_lock because seed threads record
        concurrently. 成功、复用与失败边界各调用一次；全程 degrade-safe，绝不抛出。
        """
        try:
            if not simulation_id:
                return
            sid = str(simulation_id)
            with self._sim_meter_lock:
                tel_path = os.path.join(
                    SimulationRunner.RUN_STATE_DIR, sid, "sim_llm_telemetry.json")
                tel = _read_json(tel_path)
                if not isinstance(tel, dict):
                    return
                token = str(tel.get("meter_run_token") or "") or (
                    _sha256_file(tel_path) or "")
                markers, migrated = self._sim_meter_markers(state)
                prior = markers.get(sid)
                legacy = state.options.get(SIM_METER_LEGACY_MARKER_OPTION)
                if ((isinstance(prior, dict)
                        and str(prior.get("meter_run_token") or "") == token)
                        or (isinstance(legacy, dict)
                            and str(legacy.get("simulation_id") or "") == sid
                            and str(legacy.get("meter_run_token") or "") == token)):
                    if migrated:
                        state.options[SIM_METER_MARKERS_OPTION] = markers
                        if state.owner_boot_id is not None:  # W9-2: see the marker save below
                            state.heartbeat_at = _utcnow()
                        try:
                            PipelineManager.save(state)
                        except Exception:  # noqa: BLE001 — 迁移落盘失败：旧槽仍被读取兜底
                            pass
                    return  # 恰好一次：这场子进程运行已入账
                # 先解析全部字段（解析失败 → 不入账也不落标记，下个边界重试）。
                t_in = int(tel.get("prompt_tokens") or 0)
                t_out = int(tel.get("completion_tokens") or 0)
                calls = int(tel.get("calls") or 0)
                model = str(tel.get("model") or "unknown")
                provider = str(tel.get("provider") or "")
                if not provider or provider == "unknown":
                    provider = "claude-cli" if model in ("claude", "codex") else model
                try:
                    wall_ms = float(tel.get("wall_s") or 0.0) * 1000.0
                except (TypeError, ValueError):
                    wall_ms = 0.0
                recorded_at = _utcnow()
                # The marker slots as they were, for the rollback when the save below fails.
                prior_slots = {key: state.options[key]
                               for key in (SIM_METER_MARKERS_OPTION,
                                           SIM_METER_LEGACY_MARKER_OPTION)
                               if key in state.options}
                if stage == STAGE_RUN:
                    state.options["sim_llm_telemetry"] = {
                        "provider": provider,
                        "model": model,
                        "calls": calls,
                        "errors": int(tel.get("errors") or 0),
                        "prompt_tokens": t_in,
                        "completion_tokens": t_out,
                        "total_tokens": int(tel.get("total_tokens") or (t_in + t_out)),
                        "by_source": (tel.get("by_source")
                                      if isinstance(tel.get("by_source"), dict) else {}),
                        "wall_s": tel.get("wall_s"),
                    }
                    if bool(getattr(Config, "RECORD_MODEL_PROVENANCE", True)):
                        # INFRA-8: the child's own per-call requested label -> served ids
                        # (absent from a child that predates it or recorded no call).
                        _sim_resolution: dict[str, Any] = {}
                        model_provenance.merge_resolution_entries(
                            _sim_resolution, tel.get("model_resolution"))
                        if _sim_resolution:
                            state.options["sim_llm_telemetry"]["model_resolution"] = _sim_resolution
                    state.options[SIM_METER_LEGACY_MARKER_OPTION] = {
                        "simulation_id": sid,
                        "meter_run_token": token,
                        "recorded_at": recorded_at,
                    }
                markers[sid] = {
                    "meter_run_token": token,
                    "stage": stage,
                    "recorded_at": recorded_at,
                }
                state.options[SIM_METER_MARKERS_OPTION] = markers
                # W9-2: a full save must not overwrite the fresh on-disk heartbeat with a stale
                # in-memory one. Seed threads call this too, and nothing refreshes their in-memory
                # heartbeat_at (the watchdog and the seed poll loop only touch the disk copy).
                if state.owner_boot_id is not None:
                    state.heartbeat_at = _utcnow()
                try:
                    PipelineManager.save(state)
                except Exception as save_err:  # noqa: BLE001 — 落盘失败不影响主流程
                    # EVAL-17: exactly-once needs the marker on disk before the spend is
                    # metered. A marker living only in memory would be lost by a crash before
                    # the next successful save, and the resume would record this run again.
                    # Roll the marker back and meter nothing: a later boundary or resume
                    # retries, and until then the spend is under-counted, never doubled.
                    for key in (SIM_METER_MARKERS_OPTION, SIM_METER_LEGACY_MARKER_OPTION):
                        if key in prior_slots:
                            state.options[key] = prior_slots[key]
                        else:
                            state.options.pop(key, None)
                    logger.warning(
                        "[%s] 模拟计量标记落盘失败：本边界不入账，留待后续边界或 resume 重试"
                        "（stage='%s' simulation=%s）: %s",
                        state.pipeline_id, stage, sid, save_err,
                    )
                    return
                if not bool(getattr(Config, "LLM_TELEMETRY_ENABLED", True)):
                    return
                if t_in <= 0 and t_out <= 0:
                    return  # 无可计量 token（空场/0 调用）→ 不写空记录
                from ..utils.telemetry import LLMMeter
                LLMMeter.record(
                    provider=provider,
                    model=model,
                    prompt_tokens=t_in,
                    completion_tokens=t_out,
                    latency_ms=wall_ms,
                    stage=stage,
                    run_id=state.pipeline_id,
                    # INFRA-8: the child's whole spend under its dominant by_model key (a
                    # served id or the CLI bridge's provider name), no call's requested model.
                    aggregate=True,
                )
                logger.info(
                    "[%s] 模拟子进程花费已入账 stage='%s'（simulation=%s provider=%s model=%s "
                    "calls=%d tokens in=%d out=%d）",
                    state.pipeline_id, stage, sid, provider, model, calls, t_in, t_out,
                )
        except Exception as e:  # noqa: BLE001 — 计量是观测增益，绝不放大失败
            logger.debug("[%s] 模拟阶段合成计量跳过: %s", state.pipeline_id, e)

    # -- 内部：研究覆盖度/质量记分牌 (I-0-3) -------------------------------

    def _surface_research_quality(
        self, state: PipelineState, handoff_dir: str
    ) -> Optional[dict[str, Any]]:
        """I-0-3: 把研究阶段写出的 research_quality 记分牌（来自 handoff/meta.json）
        透传到 state.options，供 StageTimeline / API 展示。

        记分牌由 DeerFlow bridge 的 compute_research_quality() 写入 meta.json（跨文件部分）。
        本方法只负责「读出并上抛」：若 bridge 尚未写该字段（旧 bridge / 未启用），静默 no-op，
        保持现有行为不变（纯观测、零成本、永不硬失败）。

        若 RESEARCH_QUALITY_GATE 开启且记分牌的 score 低于 RESEARCH_QUALITY_FLOOR，
        在 options 里打一个软告警标记（real gap-pass 由 bridge 在研究阶段内自校正）。
        """
        try:
            meta = _read_json(os.path.join(handoff_dir, "meta.json"))
        except Exception:  # noqa: BLE001
            meta = None
        meta = meta if isinstance(meta, dict) else {}
        rq = dict(meta.get("research_quality") or {})
        budget = _read_json(os.path.join(handoff_dir, "research_budget.json"))
        if isinstance(budget, dict):
            global_counts = budget.get("global") if isinstance(budget.get("global"), dict) else {}
            denials = sum(
                int(value or 0) for key, value in global_counts.items()
                if str(key).startswith("denied_") and isinstance(value, (int, float))
            )
            budget_summary = {
                "degraded": bool(budget.get("degraded")),
                "denials": denials,
                "attempts": int(global_counts.get("attempts") or 0),
                "search_network": int(global_counts.get("search_network") or 0),
                "fetch_network": int(global_counts.get("fetch_network") or 0),
                "limits": budget.get("limits") if isinstance(budget.get("limits"), dict) else {},
            }
            state.options["research_budget"] = budget_summary
            meta["research_budget"] = budget_summary
            if budget_summary["degraded"] or denials:
                rq["degraded"] = True
                degradation = list(rq.get("degradation") or [])
                reason = (
                    "research budget ledger degraded"
                    if budget_summary["degraded"]
                    else f"research tool budget denied {denials} call(s); synthesis used collected evidence"
                )
                if reason not in degradation:
                    degradation.append(reason)
                rq["degradation"] = degradation
                meta["research_quality"] = rq
                # Manifest-owned metadata is written into the private finalized
                # generation with report/cast/sources.  Mutating it here would
                # invalidate the producer contract before that generation is
                # ready to promote.
                if not os.path.exists(_research_contract_path(handoff_dir)):
                    try:
                        from ..utils.atomic import write_json_atomic
                        write_json_atomic(os.path.join(handoff_dir, "meta.json"), meta)
                    except Exception:  # noqa: BLE001 — state still carries the signal
                        pass
        if not rq and not isinstance(budget, dict):
            return meta or None
        try:
            state.options["research_quality"] = rq
            # 软告警：记分牌偏低时留痕（不阻断管线——GIGO 是软信号，宁可继续也不误杀小盘口事件）。
            gate_on = bool(getattr(Config, "RESEARCH_QUALITY_GATE", False))
            floor = float(getattr(Config, "RESEARCH_QUALITY_FLOOR", 0.0) or 0.0)
            score = rq.get("score")
            if gate_on and isinstance(score, (int, float)) and floor > 0 and score < floor:
                state.options["research_quality_warning"] = (
                    f"research quality score {round(float(score), 3)} < floor {floor}"
                )
                logger.warning(
                    "[%s] 研究质量记分牌偏低: score=%.3f < floor=%.3f（继续，不硬失败）",
                    state.pipeline_id, float(score), floor,
                )
            PipelineManager.save(state)
        except Exception as e:  # noqa: BLE001
            logger.debug("[%s] research_quality 透传跳过: %s", state.pipeline_id, e)
        return meta or None

    # -- 内部：预测信心罚分 (R2-RES-3) -------------------------------------

    @staticmethod
    def _compute_forecast_confidence_penalty(
        meta: Optional[dict], dossier_coverage: Optional[dict]
    ) -> tuple[float, dict]:
        """R2-RES-3 (pure): derive an advisory forecast-confidence penalty in [0, 0.3]
        from research evidence quality.

        Four additive sources, each capped so the total is a soft demotion signal and
        never large enough to be load-bearing on its own:
          * research_quality.score below RESEARCH_QUALITY_FLOOR (proportional, ≤0.15);
          * exhausted/degraded shared research budget (0.05);
          * source-tier mix skewed to low-tier sources (≤~0.08);
          * weak dossier-coverage signals (0.05 each, ≤0.10).
        Returns ``(penalty, components)``; never raises (caller wraps too)."""
        meta = meta if isinstance(meta, dict) else {}
        components: dict[str, float] = {}
        penalty = 0.0

        rq = meta.get("research_quality")
        if isinstance(rq, dict):
            score = rq.get("score")
            try:
                floor = float(getattr(Config, "RESEARCH_QUALITY_FLOOR", 0.0) or 0.0)
            except (TypeError, ValueError):
                floor = 0.0
            if isinstance(score, (int, float)) and floor > 0 and score < floor:
                c = round(min(0.15, float(floor) - float(score)), 3)
                if c > 0:
                    components["research_quality"] = c
                    penalty += c

        research_budget = meta.get("research_budget")
        if isinstance(research_budget, dict) and (
                research_budget.get("degraded") or research_budget.get("denials")):
            components["research_budget"] = 0.05
            penalty += 0.05

        tiers = meta.get("source_tiers")
        if isinstance(tiers, dict) and tiers:
            tot = 0
            wsum = 0.0
            for t, n in tiers.items():
                try:
                    cnt = int(n)
                except (TypeError, ValueError):
                    continue
                if cnt <= 0:
                    continue
                wsum += _source_tier_penalty_weight(t) * cnt
                tot += cnt
            if tot > 0:
                c = round(max(0.0, 1.0 - (wsum / tot)) * 0.1, 3)
                if c > 0:
                    components["source_tier_mix"] = c
                    penalty += c

        if isinstance(dossier_coverage, dict):
            weak = 0
            if dossier_coverage.get("n_actors", 0) and dossier_coverage.get("pct_actors_with_incentives", 0) < 0.34:
                weak += 1
            if dossier_coverage.get("n_relationships", 0) == 0:
                weak += 1
            elif dossier_coverage.get("n_relationships", 0) and dossier_coverage.get("pct_edges_valenced", 0) < 0.2:
                weak += 1
            if weak:
                c = round(min(0.10, 0.05 * weak), 3)
                components["dossier_coverage"] = c
                penalty += c

        return round(min(0.3, penalty), 3), components

    def _surface_forecast_confidence_penalty(self, state: PipelineState, handoff_dir: str) -> None:
        """R2-RES-3: stash an advisory ``forecast_confidence_penalty`` (+ component
        breakdown) into ``state.options`` for the publish gate to consume later.

        Pure observation: only *writes* the number — the publish gate that reads it
        (gate refine) is deliberately deferred to a later change, so nothing here can
        block or wedge a run. Best-effort; never raises."""
        try:
            meta = _read_json(os.path.join(handoff_dir, "meta.json"))
            penalty, components = self._compute_forecast_confidence_penalty(
                meta if isinstance(meta, dict) else None,
                state.options.get("dossier_coverage"),
            )
            state.options["forecast_confidence_penalty"] = penalty
            state.options["forecast_confidence_penalty_components"] = components
            if penalty > 0:
                logger.info("[%s] forecast_confidence_penalty=%.3f（来源: %s）",
                            state.pipeline_id, penalty, components)
            PipelineManager.save(state)
        except Exception as e:  # noqa: BLE001 — 罚分纯观测，失败不影响主流程
            logger.debug("[%s] forecast_confidence_penalty 计算跳过: %s", state.pipeline_id, e)

    def _log_decision_channel_outcome(self, state: PipelineState, simulation_id: Optional[str]) -> None:
        """SIM-ADD-2：RUN 结束后落一条决策通道端到端摘要（日志 + state.options）。

        读注入 simulation_config.json 的 ``world_state_seed.scenarios`` 与模拟目录下的
        ``world_state_trajectory.json``（决策通道产物），把「种子情景数 / 是否产出轨迹 /
        终局结果份额 / 是否趋稳」汇成一条可审计记录——这正是取证时需要翻磁盘才能回答的
        「这次模拟到底有没有贡献 forecast」。纯观测：只读盘、只写 options，绝不阻断主流程。
        """
        sim_dir = os.path.join(
            getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "", str(simulation_id or ""))
        seed = {}
        try:
            cfg = _read_json(os.path.join(sim_dir, "simulation_config.json"))
            if isinstance(cfg, dict) and isinstance(cfg.get("world_state_seed"), dict):
                seed = cfg["world_state_seed"]
        except Exception:  # noqa: BLE001
            seed = {}
        scenarios = [s for s in (seed.get("scenarios") or []) if str(s).strip()]
        traj = _read_json(os.path.join(sim_dir, "world_state_trajectory.json"))
        produced = isinstance(traj, dict) and bool(traj.get("trajectory"))
        outcome = (traj.get("outcome") if isinstance(traj, dict) else None) or {}
        shares = outcome.get("shares") if isinstance(outcome, dict) else None
        converged_at = traj.get("converged_at") if isinstance(traj, dict) else None
        # SIM-1：两路决策通道产物共用的有效性裁定（顶层；旧轨迹缺席 → None）。只观测：
        # 通道本就 diagnostic_only，非 valid 裁定只告警，不进 _assess_run_health。
        validity = traj.get("validity") if isinstance(traj, dict) else None
        # SIM-2：名册校验的 run 级汇总（DECISION_CHANNEL_VALIDATION 关或旧轨迹 → None）。
        validation = traj.get("decision_validation") if isinstance(traj, dict) else None
        validation = validation if isinstance(validation, dict) else {}
        summary = {
            "scenarios_seeded": len(scenarios),
            "trajectory_produced": bool(produced),
            "leader": (outcome.get("leader") if isinstance(outcome, dict) else None),
            "leader_share": (outcome.get("leader_share") if isinstance(outcome, dict) else None),
            "converged_at": converged_at,
            "validity": validity,
            "validity_reasons": (traj.get("validity_reasons") if isinstance(traj, dict) else None),
            "forecast_effect": (traj.get("forecast_effect") if isinstance(traj, dict) else None),
            "fallback_share": validation.get("fallback_share"),
            "decision_validation_measured_rounds": validation.get("measured_rounds"),
        }
        state.options["decision_channel_summary"] = summary
        try:
            PipelineManager.save(state)
        except Exception:  # noqa: BLE001
            pass
        if produced:
            _share_str = ""
            if isinstance(shares, dict) and shares:
                _top = sorted(shares.items(), key=lambda kv: -float(kv[1] or 0))[:4]
                _share_str = "，".join(f"{k}={float(v):.0%}" for k, v in _top)
            logger.info(
                "[%s] 决策通道端到端：种子 %d 情景 → 已产出 world_state_trajectory.json"
                "（终局 %s；converged_at=%s）",
                state.pipeline_id, len(scenarios), _share_str or "?", converged_at)
        elif scenarios:
            logger.warning(
                "[%s] 决策通道未产出 world_state_trajectory.json——已种子 %d 情景但轨迹缺失"
                "（检查子进程 SIM_DECISION_CHANNEL(_INBAND) 与 LLM 可用性）",
                state.pipeline_id, len(scenarios))
        else:
            logger.warning(
                "[%s] 决策通道未点火：world_state_seed 无情景（研究阶段未产出概率分布）",
                state.pipeline_id)
        validity_norm = str(validity or "").strip().lower()
        if validity_norm and validity_norm != "valid":
            logger.warning(
                "[%s] 决策通道有效性裁定=%s（原因 %s；forecast_effect=%s）——推演结果分布不可用作"
                "任何依据（REPORT_WORLDSTATE_HIDE_INVALID 开时报告隐藏份额/图表/对比表）",
                state.pipeline_id, validity_norm, summary["validity_reasons"],
                summary["forecast_effect"])

    # -- 内部：研究 as_of 锚校验 (R2-RES-7) -------------------------------

    @staticmethod
    def _validate_as_of_date(actors: Any, sources: Any) -> tuple[Optional[datetime], Optional[str]]:
        """R2-RES-7: validate ``actors.as_of_date`` — the bi-temporal anchor used as the
        seed ``valid_at`` and as every research chunk's ``reference_time``.

        A trustworthy anchor must (a) parse, (b) be no later than the run date (no
        future anchor), and (c) be no earlier than the newest source publication date
        (the anchor cannot predate the evidence it summarizes). On any violation we fall
        back to max(source dates) clamped to the run date, else the run date, and return
        a human-readable note for telemetry.

        Returns ``(as_of_dt | None, note | None)``. When ``as_of_date`` is simply absent
        AND there are no source dates, returns ``(None, None)`` to preserve today's
        "no anchor" behavior byte-for-byte. Never raises."""
        run_dt = datetime.now(timezone.utc)
        max_src: Optional[datetime] = None
        if isinstance(sources, list):
            for s in sources:
                if not isinstance(s, dict):
                    continue
                d = parse_as_of(s.get("date"))
                # TIME-2 (defensive): a source dated after the run is a misdated
                # page, never evidence newer than today, so it cannot push a
                # valid as_of_date off (the research tools already reject it).
                if d is not None and d <= run_dt and (max_src is None or d > max_src):
                    max_src = d
        raw = actors.get("as_of_date") if isinstance(actors, dict) else None
        parsed = parse_as_of(raw)
        note: Optional[str] = None
        if parsed is not None:
            if parsed > run_dt:
                note = f"as_of_date {parsed.date()} 晚于运行日 {run_dt.date()}，回退"
                parsed = None
            elif max_src is not None and parsed < max_src:
                note = f"as_of_date {parsed.date()} 早于最新来源日 {max_src.date()}，回退"
                parsed = None
        elif raw not in (None, ""):
            note = f"as_of_date 无法解析（{raw!r}），回退"
        if parsed is not None:
            return parsed, None
        if max_src is not None:
            return (max_src if max_src <= run_dt else run_dt), note
        if raw in (None, ""):
            # 既无 as_of_date 也无来源日 → 维持今日「无锚」行为（degrade-safe）。
            return None, None
        # as_of_date 存在但无效且无来源日可回退 → 运行日兜底（优于带脏日期入图）。
        return run_dt, note

    @classmethod
    def _pin_hindcast_graph_anchor(cls, state: "PipelineState", pin: dict[str, Any],
                                   sources: Any) -> datetime:
        """TIME-7: the bi-temporal graph anchor of a pinned hindcast (midnight UTC of its as-of).

        ``_validate_as_of_date`` is not consulted: it moves an anchor forward to the newest
        source date, and in a hindcast a source dated after the as-of is a leak, never newer
        evidence.  Such sources are recorded, never adopted: up to
        ``HINDCAST_VIOLATIONS_MAX`` of their URLs go to ``state.options['hindcast_violations']``
        (only when there is one; every graph build re-decides).  A source date is read at
        its precision (``utils.dates.date_period``: a day, a month or a year, the coarser of
        the row's ``date_precision`` and its text): it is after the as-of only when its whole
        period is, and a month or year that starts on or before the as-of but ends after it
        is ambiguous, neither cleared nor recorded as a violation.  The check can only see
        dated sources (v3 dates them only with RESEARCH_SOURCE_DATES), so its coverage is
        always recorded in ``state.options['hindcast_source_dates']`` = ``{'dated',
        'undated', 'after_as_of', 'ambiguous'}`` (source rows; ``after_as_of`` and
        ``ambiguous`` count dated rows and are not capped): no violations with every source
        undated or ambiguous means "not checked", never "no leak".  The pinned date is also
        the ledger pre-registration anchor (EVAL-1 ``as_of_date_validated``).  A pin whose
        as-of is not a canonical, non-future date raises ValueError: the graph stage fails
        closed rather than anchor a hindcast anywhere else.
        """
        from ..utils.point_in_time import validate_as_of
        anchor = datetime.strptime(validate_as_of(pin.get("as_of")), "%Y-%m-%d").replace(
            tzinfo=timezone.utc)
        pin_day = anchor.date()
        violations: list[str] = []
        coverage = {"dated": 0, "undated": 0, "after_as_of": 0, "ambiguous": 0}
        for source in sources if isinstance(sources, list) else []:
            if not isinstance(source, dict):
                continue
            period = date_period(source.get("date"), source.get("date_precision"))
            if period is None:
                coverage["undated"] += 1
                continue
            coverage["dated"] += 1
            first_day, last_day = period
            if last_day <= pin_day:
                continue
            if first_day <= pin_day:
                coverage["ambiguous"] += 1
                continue
            coverage["after_as_of"] += 1
            url = source.get("url")
            if (isinstance(url, str) and url and url not in violations
                    and len(violations) < HINDCAST_VIOLATIONS_MAX):
                violations.append(url)
        state.options.pop("hindcast_violations", None)
        state.options["hindcast_source_dates"] = coverage
        if violations:
            state.options["hindcast_violations"] = violations
            logger.warning("[%s] hindcast: %d source(s) dated after the pinned as-of %s recorded "
                           "in hindcast_violations, never adopted as the graph anchor",
                           state.pipeline_id, len(violations), anchor.date())
        if coverage["undated"]:
            logger.info("[%s] hindcast: %d of %d source(s) carry no publication date; the "
                        "later-dated check covers only dated sources (RESEARCH_SOURCE_DATES)",
                        state.pipeline_id, coverage["undated"],
                        coverage["undated"] + coverage["dated"])
        if coverage["ambiguous"]:
            logger.info("[%s] hindcast: %d source(s) dated only to a month or year that spans "
                        "the pinned as-of %s; the later-dated check can neither clear nor flag "
                        "them", state.pipeline_id, coverage["ambiguous"], pin_day)
        cls._record_validated_as_of(state, anchor, True)
        return anchor

    # -- 内部：仅综合恢复（复用 immutable evidence lanes）-----------------

    def _run_research_synthesis_recovery(
        self, state: "PipelineState", handoff_dir: str,
        upd: "Callable[[int, str], None]", manifest_path: str,
    ) -> dict[str, Any]:
        """Retry only global synthesis from sealed lane packs.

        A checksum or report-quality failure occurs after evidence gathering.
        Re-running three multi-hour lanes is both wasteful and unsafe.  The
        evidence manifest already fingerprints every lane pack/source ledger;
        the bridge validates it before writing and now exits nonzero on judge
        FAIL.  This path therefore performs at most two clean synthesis attempts,
        promotes only an integrity-valid PASS, and retains failed candidates.
        """
        from ..utils.atomic import write_text_atomic

        _sync_deerflow_bridge_if_stale(Config.DEERFLOW_DIR)
        manifest = _read_json(manifest_path)
        lanes = manifest.get("lanes") if isinstance(manifest, dict) else None
        actor_descriptor = (
            manifest.get("actor_dossier")
            if isinstance(manifest, dict) else None
        )
        if (
            not isinstance(manifest, dict)
            or int(manifest.get("version") or 0) < 3
            or not isinstance(lanes, list)
            or not lanes
            or not isinstance(actor_descriptor, dict)
        ):
            raise RuntimeError(
                "synthesis-only recovery requires a version-3 evidence manifest "
                "with a checksum-bound shared actor dossier"
            )
        budget_db_path, budget_telemetry_path, budget_epoch = (
            _synthesis_recovery_budget_epoch(state, handoff_dir)
        )
        exhausted = _research_budget_exhaustion(
            budget_telemetry_path, budget_epoch)
        if exhausted:
            raise RuntimeError(
                "research_budget_exhausted before synthesis-only recovery "
                f"(epoch={budget_epoch}, budget={exhausted})"
            )
        global_cap = getattr(Config, "RESEARCH_GLOBAL_SUBAGENT_CAP", 9)
        model_concurrency = research_model_concurrency_cap(
            1,
            global_cap,
            getattr(Config, "RESEARCH_GLOBAL_MODEL_CONCURRENCY", 0),
        )

        market_lines: list[str] = []
        seen_market_lines: set[str] = set()
        candidate_paths = [
            os.path.join(handoff_dir, "prediction_market_candidates.jsonl")
        ]
        candidate_paths.extend(sorted(glob.glob(os.path.join(
            handoff_dir, "track_*", "prediction_market_candidates.jsonl"))))
        for candidate_path in candidate_paths:
            if not os.path.isfile(candidate_path):
                continue
            for line in _read_text(candidate_path).splitlines():
                normalized = line.strip()
                if normalized and normalized not in seen_market_lines:
                    seen_market_lines.add(normalized)
                    market_lines.append(normalized)

        def _spawn(pid: int) -> None:
            state.research_pid = int(pid)
            PipelineManager.save(state)

        def _progress(percent: int, message: str) -> None:
            upd(
                min(99, max(1, int(percent))),
                f"[仅综合恢复] {message}",
            )

        final_res: Optional[dict[str, Any]] = None
        source_dir = ""
        errors: list[str] = []
        attempts = 0
        provider_blocked = False
        for attempt in range(1, 3):
            attempts = attempt
            synthesis_dir = tempfile.mkdtemp(
                prefix=f".synthesis-recovery-{attempt}-", dir=handoff_dir)
            if market_lines:
                write_text_atomic(
                    os.path.join(
                        synthesis_dir, "prediction_market_candidates.jsonl"),
                    "\n".join(market_lines) + "\n",
                )
            upd(
                2,
                f"复用 {len(lanes)} 条已校验证据轨，仅重跑全局综合（{attempt}/2）…",
            )
            try:
                candidate = DeerFlowResearchRunner.run(
                    state.prompt,
                    synthesis_dir,
                    on_progress=_progress,
                    depth=state.options.get("depth"),
                    language=state.options.get("research_language"),
                    model=state.options.get("research_model"),
                    cancel_event=type(self)._cancel_events.get(state.pipeline_id),
                    on_spawn=_spawn,
                    kg_graph_id=state.graph_id,
                    budget_db_path=budget_db_path,
                    budget_lane_id="global-synthesis-recovery",
                    budget_telemetry_path=budget_telemetry_path,
                    budget_run_id=state.pipeline_id,
                    budget_epoch=budget_epoch,
                    subagents=False,
                    max_concurrent_subagents=1,
                    model_concurrency_global=model_concurrency,
                    dual_track=False,
                    shared_actor_track=False,
                    synthesis_manifest_path=manifest_path,
                )
                if int(candidate.get("exit_code") or 0) != 0:
                    raise RuntimeError(
                        "synthesis-only recovery returned non-zero exit "
                        f"{candidate.get('exit_code')}"
                    )
                final_res = candidate
                source_dir = synthesis_dir
                break
            except PipelineCancelled:
                _preserve_research_attempt_progress(
                    synthesis_dir,
                    handoff_dir,
                    attempt=attempt,
                    outcome="cancelled",
                    detail="synthesis-only recovery cancelled",
                )
                shutil.rmtree(synthesis_dir, ignore_errors=True)
                raise
            except Exception as exc:  # noqa: BLE001 - bounded retry
                detail = f"{type(exc).__name__}: {exc}"
                errors.append(detail)
                provider_blocked = _synthesis_provider_unavailable(detail)
                # DEFECT-1：仅综合恢复的失败在编排器边界按阶段级失败计入运行级熔断。
                _note_provider_stage_failure(state.pipeline_id, exc)
                _preserve_research_attempt_progress(
                    synthesis_dir,
                    handoff_dir,
                    attempt=attempt,
                    outcome="failed",
                    detail=detail,
                )
                shutil.rmtree(synthesis_dir, ignore_errors=True)
                logger.warning(
                    "[%s] 仅综合恢复尝试 %d/2 失败: %s",
                    state.pipeline_id, attempt, exc,
                )
                if provider_blocked:
                    logger.warning(
                        "[%s] 主模型与回退模型均不可用；停止重复综合尝试，等待提供方恢复后安全续跑",
                        state.pipeline_id,
                    )
                    break

        state.research_pid = None
        if final_res is None or not source_dir:
            state.options["synthesis_recovery"] = {
                "attempted": True,
                "passed": False,
                "evidence_manifest": manifest_path,
                "attempts": attempts,
                "errors": errors,
                "blocked_by_provider": provider_blocked,
            }
            PipelineManager.save(state)
            if provider_blocked:
                raise RuntimeError(
                    "全局综合暂时被模型提供方阻塞；MiniMax 有界重试及配置的 "
                    "Antigravity/Quotio 回退均不可用。证据包保持封存，提供方恢复后可安全续跑，"
                    "未重跑证据研究"
                )
            raise RuntimeError(
                "全局综合恢复连续两次未通过质量门；已保留证据包、失败报告和 judge，"
                "未重跑证据研究"
            )

        recovery_meta = {
            "attempted": True,
            "passed": True,
            "evidence_manifest": manifest_path,
            "evidence_lanes_consumed": len(lanes),
            "attempts": attempts,
        }
        parallel_meta = dict(state.options.get("parallel_research") or {})
        parallel_meta.update({
            "architecture": "parallel_evidence_single_global_synthesis",
            "evidence_manifest": manifest_path,
            "evidence_lanes_consumed": len(lanes),
            "global_synthesis_failed": False,
            "global_synthesis_attempts": attempts,
            "synthesis_only_recovery": True,
        })
        _promote_research_contract(
            source_dir,
            handoff_dir,
            meta_patch={
                "parallel_research": parallel_meta,
                "synthesis_recovery": recovery_meta,
            },
        )
        shutil.rmtree(source_dir, ignore_errors=True)
        state.options["parallel_research"] = parallel_meta
        state.options["synthesis_recovery"] = recovery_meta
        PipelineManager.save(state)
        loaded = _load_research_handoff(handoff_dir)
        loaded["exit_code"] = 0
        loaded["research_telemetry"] = (
            final_res.get("research_telemetry") or {})
        return loaded

    # -- 内部：PAR-2 多角度并行研究轨 ------------------------------------

    def _run_parallel_research_tracks(
        self, state: "PipelineState", handoff_dir: str,
        upd: "Callable[[int, str], None]", n_tracks: int,
    ) -> dict[str, Any]:
        """PAR-2：并行跑 K 条角度特化研究轨，确定性合并回 handoff_dir，返回 research 摘要。

        每轨 = 一个 DeerFlowResearchRunner 子进程（角度前缀 + 原始 prompt），写入
        handoff/track_<k>/。各轨用既有 per-run 看门狗预算 → wall-clock ≈ 1 轨。某轨失败仅
        跳过（存活 ≥1 即继续并打降级标）；全失败 → RuntimeError（阶段失败，与今日一致）。
        取消（cancel_event）穿透所有轨并向上重抛。返回 dict 的键与 DeerFlowResearchRunner.run
        一致（report/report_path/actor_dossier/actors/sources/timeline/exit_code/research_telemetry），
        供下游各阶段无差别消费。
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from ..utils.atomic import write_json_atomic, write_text_atomic

        cls = type(self)
        angles = _RESEARCH_TRACK_ANGLES[:max(1, n_tracks)]
        n = len(angles)
        # Full-research lanes (no global synthesis) run the run's own engine.
        research_engine = research_engine_for_run(state.options)
        global_synthesis = bool(
            n > 1 and getattr(Config, "RESEARCH_GLOBAL_SYNTHESIS", True))
        global_subagent_cap = getattr(Config, "RESEARCH_GLOBAL_SUBAGENT_CAP", 9)
        configured_model_cap = getattr(Config, "RESEARCH_GLOBAL_MODEL_CONCURRENCY", 0)
        outer_workers = research_outer_track_workers(
            n, global_subagent_cap, configured_model_cap)
        model_concurrency = research_model_concurrency_cap(
            outer_workers,
            global_subagent_cap,
            configured_model_cap,
        )
        subagent_cap = research_lane_subagent_cap(
            outer_workers,
            global_subagent_cap,
            getattr(Config, "RESEARCH_SUBAGENTS_PER_TRACK_MAX", 5),
            model_concurrency,
        )
        harness_subagents = bool(
            getattr(Config, "DEERFLOW_SUBAGENTS", True) and subagent_cap > 0)
        os.makedirs(handoff_dir, exist_ok=True)
        budget_db_path, budget_telemetry_path, budget_epoch = (
            _activate_research_budget_epoch(state, handoff_dir)
        )
        exhausted = _research_budget_exhaustion(
            budget_telemetry_path, budget_epoch)
        if exhausted:
            raise RuntimeError(
                "research_budget_exhausted before track launch "
                f"(epoch={budget_epoch}, budget={exhausted}); "
                "explicit pipeline resume is required for a new bounded epoch"
            )
        # LOOP-014: synchronize once before admitting any lane.  Every runner
        # verifies again under the same cross-process lock, but those calls are
        # normally manifest-only no-ops.  A required bundle failure propagates
        # here so no lane can start against stale or partially copied skills.
        _sync_deerflow_bridge_if_stale(Config.DEERFLOW_DIR)
        upd(
            2,
            f"并行研究：排队 {n} 条多角度研究轨（同时 {outer_workers} 条；"
            f"每轨最多 {subagent_cap if harness_subagents else 0} 个 harness 子代理；"
            f"全局模型流 {model_concurrency}）…",
        )

        # LOOP-008：等权聚合每条真实研究轨，并为最终跨轨合并保留 95→100。
        # 旧实现取 min 且允许子轨先报 100，随后 ``upd(96, 合并…)`` 会倒退；并发回调还
        # 可能以旧值晚写覆盖新值。这里把每轨限定在 95、聚合单调化，并串行发布状态。
        # 高频 tool/result 仍由 progress endpoint 直接读各轨日志；状态文件只在百分比变化
        # 或 15 秒存活刷新时写，避免日志洪峰阻塞 stdout reader。
        prog_lock = threading.Lock()
        publish_lock = threading.Lock()
        track_local = [2] * n
        failed_tracks: set[int] = set()
        last_published = 2
        last_publish_at = 0.0
        pids_lock = threading.Lock()

        def _make_cb(idx: int) -> "Callable[[int, str], None]":
            def _cb(local: int, msg: str) -> None:
                nonlocal last_published, last_publish_at
                ev = cls._cancel_events.get(state.pipeline_id)
                if ev is not None and ev.is_set():
                    raise PipelineCancelled("并行研究期间被取消")
                with prog_lock:
                    track_local[idx] = max(track_local[idx], min(95, int(local)))
                with publish_lock:
                    with prog_lock:
                        agg = aggregate_parallel_progress(
                            track_local,
                            previous=last_published,
                            ceiling=95,
                            excluded_indices=failed_tracks,
                        )
                    now = time.monotonic()
                    detail = str(msg or "")
                    if agg <= last_published and now - last_publish_at < 15.0:
                        return
                    last_published = agg
                    last_publish_at = now
                    upd(agg, f"[轨{idx + 1}] {_tail(detail)}")
            return _cb

        def _make_spawn(idx: int) -> "Callable[[int], None]":
            def _spawn(pid: int) -> None:
                # 持久化各轨 PID，供后端重启时 reconcile_orphans 逐一清理孤儿研究子进程。
                # 单一 state.research_pid 字段保留首个 PID（back-compat）；完整清单入 options。
                with pids_lock:
                    lst = state.options.setdefault("research_track_pids", [])
                    if int(pid) not in lst:
                        lst.append(int(pid))
                    if state.research_pid is None:
                        state.research_pid = int(pid)
                PipelineManager.save(state)
            return _spawn

        def _run_track(idx: int, angle_title: str, prefix: str) -> tuple:
            track_dir = os.path.join(handoff_dir, f"track_{idx + 1}")
            os.makedirs(track_dir, exist_ok=True)
            track_prompt = (prefix + state.prompt) if prefix else state.prompt
            track_lane_id = f"outer-track-{idx + 1}"
            # ITEM-3：每轨各写自己的 track_<k>/research_checkpoint.json；重试时逐轨判定续跑
            # （某轨已完成的 pass 不重跑，只补未完成的）。首跑无 checkpoint → 全量跑该轨。
            _resume_lineage = _validated_research_checkpoint_lineage(
                track_dir,
                prompt=track_prompt,
                depth=str(
                    state.options.get("depth")
                    or getattr(Config, "DEERFLOW_RESEARCH_DEPTH", "standard")
                ),
                run_id=state.pipeline_id,
                lane_id=track_lane_id,
                expected_attempt_ids=_research_budget_attempt_ids(state),
            )
            _resume_attempt_id = _resume_lineage.get("attempt_id", "")
            _resume_track = bool(_resume_attempt_id)
            res = DeerFlowResearchRunner.run(
                track_prompt,
                track_dir,
                on_progress=_make_cb(idx),
                depth=state.options.get("depth"),
                language=state.options.get("research_language"),
                model=state.options.get("research_model"),
                cancel_event=cls._cancel_events.get(state.pipeline_id),
                on_spawn=_make_spawn(idx),
                resume=_resume_track,
                kg_graph_id=state.graph_id,  # W9-9：图谱已存在时接入 KG MCP（首跑为 None → no-op）
                budget_db_path=budget_db_path,
                budget_lane_id=track_lane_id,
                budget_telemetry_path=budget_telemetry_path,
                budget_run_id=state.pipeline_id,
                budget_epoch=budget_epoch,
                resume_attempt_id=_resume_attempt_id,
                resume_checkpoint_id=_resume_lineage.get(
                    "checkpoint_id", ""
                ),
                subagents=harness_subagents,
                max_concurrent_subagents=max(1, subagent_cap),
                model_concurrency_global=model_concurrency,
                # Actor/ontology research is a shared cast-building plane, not
                # an angle-specific evidence lane. Running it inside every
                # outer track tripled its synthesis/judge cost and expanded the
                # graph with duplicate peripheral actors. The broad baseline
                # lane owns the single global dossier; the other lanes remain
                # focused on orthogonal Track-A evidence.
                dual_track=research_dual_track_for_outer_lane(
                    idx, bool(getattr(Config, "DEERFLOW_DUAL_TRACK", True))),
                # Track B is a separate downstream artifact and is not injected
                # into Track-A threads. Keep Track A's actor/incentive phase so
                # the visible research report remains complete even if the one
                # baseline Track-B lane fails.
                shared_actor_track=False,
                evidence_only=global_synthesis,
                research_engine=research_engine,
            )
            if int(res.get("exit_code") or 0) != 0:
                raise RuntimeError(
                    f"research lane {idx + 1} returned non-zero exit "
                    f"{res.get('exit_code')}"
                )
            return idx, angle_title, track_dir, res

        results: dict[int, tuple] = {}
        cancelled: Optional[PipelineCancelled] = None
        with ThreadPoolExecutor(
                max_workers=outer_workers, thread_name_prefix="research-track") as ex:
            futs = {ex.submit(_run_track, i, angles[i][1], angles[i][2]): i for i in range(n)}
            for fut in as_completed(futs):
                i = futs[fut]
                try:
                    idx, angle_title, track_dir, res = fut.result()
                    results[idx] = (angle_title, track_dir, res)
                except PipelineCancelled as pc:
                    cancelled = pc  # 取消须穿透，不当作「可跳过的轨失败」
                except Exception as te:  # noqa: BLE001 — 单轨失败用存活轨继续
                    logger.warning("[%s] 研究轨 %d 失败（跳过，用存活轨继续）: %s",
                                   state.pipeline_id, i + 1, te)
                    # DEFECT-1：研究子进程有自己的重试环，不做进程注入——在编排器边界把
                    # 「可分类为提供方级」的轨失败计入运行级熔断（best-effort）。
                    _note_provider_stage_failure(state.pipeline_id, te)
                    with prog_lock:
                        failed_tracks.add(i)
                    try:
                        _make_cb(i)(95, f"研究轨失败，已从活动进度聚合移除：{te}")
                    except Exception:  # noqa: BLE001 — 可观测性更新不得掩盖原始轨失败
                        pass
        if cancelled is not None:
            raise cancelled
        if not results:
            raise RuntimeError("所有并行研究轨均失败，研究阶段失败")

        survived = len(results)
        degraded = survived < n
        upd(96, f"合并 {survived}/{n} 条研究轨…")

        # 按轨序确定性合并
        ordered = [results[i] for i in sorted(results)]
        track_sources = [res.get("sources") for (_title, _td, res) in ordered]
        merged_sources = merge_sources_union(track_sources)

        if global_synthesis:
            # The broad baseline (index 0) is the sole owner of shared actor
            # intelligence.  Evidence from other angles is useful without that
            # lane, but the final report/simulation contract is not: fail closed
            # instead of publishing an actor-free synthesis or picking the
            # "longest" dossier from an unintended lane.
            if 0 not in results:
                raise RuntimeError(
                    "broad baseline evidence lane failed; required shared actor "
                    "intelligence is unavailable"
                )
            baseline_title, baseline_dir, baseline_result = results[0]
            shared_dossier = str(
                baseline_result.get("actor_dossier") or "").strip()
            if not shared_dossier:
                raise RuntimeError(
                    "broad baseline evidence lane returned no fresh shared actor dossier"
                )
            leaked_actor_lanes = [
                index + 1
                for index, (_title, _track_dir, result) in results.items()
                if index != 0 and str(result.get("actor_dossier") or "").strip()
            ]
            if leaked_actor_lanes:
                raise RuntimeError(
                    "non-baseline evidence lanes produced actor dossiers: "
                    + ", ".join(str(index) for index in leaked_actor_lanes)
                )

            manifest_path = os.path.join(
                handoff_dir, "evidence_synthesis_manifest.json")
            lane_manifest_rows: list[dict[str, Any]] = []
            for title, track_dir, _res in ordered:
                evidence_path = os.path.join(track_dir, "evidence_pack.md")
                sources_path = os.path.join(track_dir, "sources.json")
                for artifact_name, artifact_path in (
                    ("evidence pack", evidence_path),
                    ("source ledger", sources_path),
                ):
                    if not os.path.isfile(artifact_path) or os.path.getsize(artifact_path) <= 0:
                        raise RuntimeError(
                            f"surviving research lane has empty/missing {artifact_name}: "
                            f"{os.path.relpath(artifact_path, handoff_dir)}"
                        )
                with open(evidence_path, "rb") as evidence_handle:
                    evidence_bytes = evidence_handle.read()
                with open(sources_path, "rb") as source_handle:
                    source_bytes = source_handle.read()
                try:
                    lane_sources = json.loads(source_bytes.decode("utf-8"))
                except (UnicodeDecodeError, ValueError, TypeError) as exc:
                    raise RuntimeError(
                        "surviving research lane has an invalid source ledger: "
                        f"{os.path.relpath(sources_path, handoff_dir)}"
                    ) from exc
                verified_lane_sources = [
                    row for row in lane_sources
                    if isinstance(row, dict)
                    and str(row.get("url") or "").startswith(("http://", "https://"))
                    and row.get("reachable") is not False
                ] if isinstance(lane_sources, list) else []
                if not verified_lane_sources:
                    raise RuntimeError(
                        "surviving research lane has no verified fetched sources: "
                        f"{os.path.relpath(sources_path, handoff_dir)}"
                    )
                lane_manifest_rows.append({
                    "title": title,
                    "path": os.path.relpath(evidence_path, handoff_dir),
                    "bytes": len(evidence_bytes),
                    "sha256": hashlib.sha256(evidence_bytes).hexdigest(),
                    "sources_path": os.path.relpath(sources_path, handoff_dir),
                    "sources_bytes": len(source_bytes),
                    "sources_sha256": hashlib.sha256(source_bytes).hexdigest(),
                })

            def _sealed_actor_artifact(
                    path: str, *, label: str) -> tuple[bytes, str]:
                if not os.path.isfile(path) or os.path.islink(path):
                    raise RuntimeError(
                        f"baseline actor dossier has missing {label}: "
                        f"{os.path.relpath(path, handoff_dir)}"
                    )
                with open(path, "rb") as artifact_handle:
                    raw = artifact_handle.read()
                if not raw:
                    raise RuntimeError(
                        f"baseline actor dossier has empty {label}: "
                        f"{os.path.relpath(path, handoff_dir)}"
                    )
                return raw, os.path.relpath(path, handoff_dir)

            dossier_path = os.path.join(
                baseline_dir, "actor_dossier.md")
            coverage_path = os.path.join(
                baseline_dir, "actor_dossier_coverage.json")
            baseline_sources_path = os.path.join(
                baseline_dir, "sources.json")
            dossier_bytes, dossier_relative = _sealed_actor_artifact(
                dossier_path, label="dossier")
            coverage_bytes, coverage_relative = _sealed_actor_artifact(
                coverage_path, label="coverage audit")
            baseline_source_bytes, baseline_source_relative = (
                _sealed_actor_artifact(
                    baseline_sources_path, label="source ledger")
            )
            if dossier_bytes.decode("utf-8").strip() != shared_dossier:
                raise RuntimeError(
                    "baseline runner dossier differs from sealed actor_dossier.md"
                )
            actor_descriptor: dict[str, Any] = {
                "lane_index": 1,
                "lane_title": baseline_title,
                "path": dossier_relative,
                "bytes": len(dossier_bytes),
                "sha256": hashlib.sha256(dossier_bytes).hexdigest(),
                "coverage_path": coverage_relative,
                "coverage_bytes": len(coverage_bytes),
                "coverage_sha256": hashlib.sha256(
                    coverage_bytes).hexdigest(),
                # load_manifest_actor_dossier reuses the same strict positional
                # ledger reader as evidence lanes to remap local [S<n>] markers.
                "sources_path": baseline_source_relative,
                "sources_bytes": len(baseline_source_bytes),
                "sources_sha256": hashlib.sha256(
                    baseline_source_bytes).hexdigest(),
            }
            baseline_meta = _read_json(os.path.join(
                baseline_dir, "meta.json"))
            current_judge_sha = str(
                (baseline_meta or {}).get("actor_dossier_judge_sha256") or ""
            ).strip() if isinstance(baseline_meta, dict) else ""
            if current_judge_sha:
                judge_path = os.path.join(
                    baseline_dir, "actor_dossier_judge.json")
                judge_bytes, judge_relative = _sealed_actor_artifact(
                    judge_path, label="judge scorecard")
                if hashlib.sha256(judge_bytes).hexdigest() != current_judge_sha:
                    raise RuntimeError(
                        "baseline actor judge does not match current-attempt metadata"
                    )
                actor_descriptor.update({
                    "judge_path": judge_relative,
                    "judge_bytes": len(judge_bytes),
                    "judge_sha256": current_judge_sha,
                })
            canonical_sources = json.dumps(
                merged_sources,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            manifest = {
                "version": 3,
                "pipeline_id": state.pipeline_id,
                "lanes": lane_manifest_rows,
                "sources": merged_sources,
                "sources_count": len(merged_sources),
                "sources_sha256": hashlib.sha256(canonical_sources).hexdigest(),
                "actor_dossier": actor_descriptor,
            }
            write_json_atomic(manifest_path, manifest)
            # Agent-vetted market observations are evidence too.  The previous
            # manifest boundary copied only source ledgers, so global synthesis
            # lost a real Optimus market and then spent ~17 minutes repeating
            # keyless catalog calls during a transport outage.  Carry the
            # immutable JSONL envelopes into the private synthesis generation;
            # bridge relevance gating still decides which rows are canonical.
            market_candidate_lines: list[str] = []
            seen_market_candidate_lines: set[str] = set()
            for _title, track_dir, _res in ordered:
                candidate_path = os.path.join(
                    track_dir, "prediction_market_candidates.jsonl")
                if not os.path.isfile(candidate_path):
                    continue
                try:
                    for line in _read_text(candidate_path).splitlines():
                        normalized = line.strip()
                        if normalized and normalized not in seen_market_candidate_lines:
                            seen_market_candidate_lines.add(normalized)
                            market_candidate_lines.append(normalized)
                except OSError:
                    continue
            def _global_progress(percent: int, message: str) -> None:
                mapped = min(99, 96 + max(0, int(percent)) * 3 // 100)
                upd(mapped, f"[全局综合] {message}")

            final_res: Optional[dict[str, Any]] = None
            synthesis_source_dir = ""
            synthesis_attempts = 0
            synthesis_errors: list[str] = []
            # A synthesis outage must never trigger another full evidence run.
            # Retry the immutable manifest once in a clean directory; if both
            # attempts fail, preserve every lane pack and fail closed.
            for attempt in range(1, 3):
                synthesis_attempts = attempt
                synthesis_dir = tempfile.mkdtemp(
                    prefix=f".global-synthesis-{attempt}-", dir=handoff_dir)
                if market_candidate_lines:
                    write_text_atomic(
                        os.path.join(
                            synthesis_dir,
                            "prediction_market_candidates.jsonl",
                        ),
                        "\n".join(market_candidate_lines) + "\n",
                    )
                upd(
                    96,
                    f"全局综合 {survived} 条证据轨（单一 outline / citation / judge，"
                    f"尝试 {attempt}/2）…",
                )
                try:
                    candidate = DeerFlowResearchRunner.run(
                        state.prompt,
                        synthesis_dir,
                        on_progress=_global_progress,
                        depth=state.options.get("depth"),
                        language=state.options.get("research_language"),
                        model=state.options.get("research_model"),
                        cancel_event=cls._cancel_events.get(state.pipeline_id),
                        on_spawn=_make_spawn(0),
                        kg_graph_id=state.graph_id,
                        budget_db_path=budget_db_path,
                        budget_lane_id="global-synthesis",
                        budget_telemetry_path=budget_telemetry_path,
                        budget_run_id=state.pipeline_id,
                        budget_epoch=budget_epoch,
                        subagents=False,
                        max_concurrent_subagents=1,
                        model_concurrency_global=model_concurrency,
                        dual_track=False,
                        shared_actor_track=False,
                        synthesis_manifest_path=manifest_path,
                    )
                    if int(candidate.get("exit_code") or 0) != 0:
                        raise RuntimeError(
                            "global synthesis returned non-zero exit "
                            f"{candidate.get('exit_code')}"
                        )
                    final_res = candidate
                    synthesis_source_dir = synthesis_dir
                    break
                except PipelineCancelled as cancelled:
                    _preserve_research_attempt_progress(
                        synthesis_dir,
                        handoff_dir,
                        attempt=attempt,
                        outcome="cancelled",
                        detail=str(cancelled),
                    )
                    shutil.rmtree(synthesis_dir, ignore_errors=True)
                    raise
                except Exception as synthesis_error:  # noqa: BLE001 — bounded retry
                    _preserve_research_attempt_progress(
                        synthesis_dir,
                        handoff_dir,
                        attempt=attempt,
                        outcome="failed",
                        detail=f"{type(synthesis_error).__name__}: {synthesis_error}",
                    )
                    synthesis_errors.append(
                        f"{type(synthesis_error).__name__}: {synthesis_error}"
                    )
                    shutil.rmtree(synthesis_dir, ignore_errors=True)
                    logger.warning(
                        "[%s] 全局证据综合尝试 %d/2 失败（%s）",
                        state.pipeline_id, attempt, synthesis_error,
                    )
                    # DEFECT-1：全局综合的失败在编排器边界按阶段级失败计入运行级熔断。
                    _note_provider_stage_failure(state.pipeline_id, synthesis_error)

            if final_res is None or not synthesis_source_dir:
                failure_meta = {
                    "requested": n,
                    "survived": survived,
                    "architecture": "parallel_evidence_single_global_synthesis",
                    "evidence_manifest": manifest_path,
                    "evidence_lanes_consumed": survived,
                    "global_synthesis_failed": True,
                    "global_synthesis_attempts": synthesis_attempts,
                    "errors": synthesis_errors,
                    "degraded": True,
                }
                state.options["parallel_research"] = failure_meta
                state.options["global_synthesis_failure"] = failure_meta
                PipelineManager.save(state)
                raise RuntimeError(
                    "全局证据综合连续两次失败；已保留全部 evidence packs，"
                    "拒绝回退到全量研究重跑或发布未综合证据"
                )

            parallel_meta = {
                "requested": n,
                "survived": survived,
                "angles": [angles[i][0] for i in sorted(results)],
                "architecture": "parallel_evidence_single_global_synthesis",
                "evidence_manifest": manifest_path,
                "evidence_lanes_consumed": survived,
                "global_synthesis_failed": False,
                "global_synthesis_attempts": synthesis_attempts,
                "degraded": degraded,
            }
            _promote_research_contract(
                synthesis_source_dir,
                handoff_dir,
                meta_patch={"parallel_research": parallel_meta},
            )
            shutil.rmtree(synthesis_source_dir, ignore_errors=True)
            state.options["parallel_research"] = parallel_meta
            state.options.pop("global_synthesis_failure", None)
            state.options.pop("global_synthesis_fallback", None)
            PipelineManager.save(state)

            lane_tels = [
                res.get("research_telemetry") or {}
                for _title, _track_dir, res in ordered
            ]
            final_tel = final_res.get("research_telemetry") or {}
            all_tels = lane_tels + [final_tel]

            def _sum_tel(key: str) -> int:
                return sum(int(tel.get(key) or 0) for tel in all_tels)

            merged_tel = {
                "model": final_tel.get("model") or Config.DEERFLOW_MODEL,
                "depth": final_tel.get("depth"),
                "tokens_in": _sum_tel("tokens_in"),
                "tokens_out": _sum_tel("tokens_out"),
                "tokens_total": _sum_tel("tokens_total") or (
                    _sum_tel("tokens_in") + _sum_tel("tokens_out")),
                "tokens_cached": _sum_tel("tokens_cached"),
                "tool_calls": _sum_tel("tool_calls"),
                "results": _sum_tel("results"),
                # Research lanes overlap; the one global synthesis follows them.
                "wall_s": round(
                    max((float(t.get("wall_s") or 0.0) for t in lane_tels),
                        default=0.0)
                    + float(final_tel.get("wall_s") or 0.0),
                    1,
                ),
                "parallel_tracks": survived,
                "global_synthesis_runs": synthesis_attempts,
            }
            # INFRA-8: every lane's and the synthesis child's resolved model and served ids.
            _resolution = model_provenance.merge_research_model_resolutions(
                tel.get("model_resolution") for tel in all_tels)
            if _resolution is not None:
                merged_tel["model_resolution"] = _resolution
            report_path = os.path.join(handoff_dir, "research_report.md")
            return {
                "report": _read_text(report_path),
                "report_path": report_path,
                "actor_dossier": _read_text(os.path.join(
                    handoff_dir, "actor_dossier.md")),
                "actors": _read_json(os.path.join(handoff_dir, "actors.json")),
                "sources": _read_json(os.path.join(handoff_dir, "sources.json"))
                or merged_sources,
                "timeline": _read_json(os.path.join(handoff_dir, "timeline.json")),
                "exit_code": 0,
                "research_telemetry": merged_tel,
            }

        labeled_reports: list[tuple[str, str]] = []
        citation_audits: list[dict[str, int]] = []
        for (title, _td, res), sources in zip(
                ordered, track_sources, strict=True):
            normalized_report, citation_audit = normalize_track_report_citations(
                res["report"], sources, merged_sources)
            labeled_reports.append((title, normalized_report))
            citation_audits.append(citation_audit)
        labeled_dossiers = [(title, res.get("actor_dossier") or "") for (title, _td, res) in ordered]
        track_dirs = [td for (_t, td, _r) in ordered]

        merged_report = merge_track_reports(labeled_reports)
        raw_merged_dossier = merge_track_reports(labeled_dossiers)
        merged_dossier = raw_merged_dossier
        merged_actors, _cast_audit = merge_actors_objs([res.get("actors") for (_t, _td, res) in ordered])
        dossier_audit: dict[str, Any] = {
            "enabled": bool(getattr(Config, "RESEARCH_COMPACT_MERGED_DOSSIER", True)),
            "raw_chars": len(raw_merged_dossier),
        }
        if dossier_audit["enabled"]:
            try:
                _dossier_cap = max(1000, int(getattr(
                    Config, "ACTOR_DOSSIER_MAX_CHARS", 80000) or 80000))
            except (TypeError, ValueError):
                _dossier_cap = 80000
            compact = ""
            compact_meta: dict[str, Any] = {}
            if isinstance(merged_actors, dict):
                try:
                    from .actor_dossier_compactor import render_compact_actor_dossier
                    compact, compact_meta = render_compact_actor_dossier(
                        merged_actors,
                        max_chars=_dossier_cap,
                        max_actors=int(getattr(Config, "ACTOR_CAST_MAX", 20) or 20),
                    )
                except Exception as _compact_err:  # noqa: BLE001
                    compact_meta = {"fallback_reason": f"{type(_compact_err).__name__}"}
            if len(compact.strip()) >= 800:
                merged_dossier = compact
            else:
                # Honest fallback: one best surviving dossier, never K-way
                # concatenation, and still bounded before graph chunking.
                candidates = [str(body or "").strip() for _title, body in labeled_dossiers
                              if str(body or "").strip()]
                best = max(candidates, key=len, default="")
                merged_dossier = best[:_dossier_cap].rsplit("\n", 1)[0].rstrip() + "\n" \
                    if len(best) > _dossier_cap else best
                compact_meta["fallback_reason"] = (
                    compact_meta.get("fallback_reason") or "compact_output_too_short")
            dossier_audit.update(compact_meta)
            dossier_audit["compact_chars"] = len(merged_dossier)
            dossier_audit["reduction_ratio"] = round(
                1.0 - (len(merged_dossier) / max(1, len(raw_merged_dossier))), 4)
        merged_timeline = merge_list_dedup([res.get("timeline") for (_t, _td, res) in ordered])
        merged_quant = merge_list_dedup([_read_json(os.path.join(td, "quantitative.json")) for td in track_dirs])
        merged_contested = merge_list_dedup([_read_json(os.path.join(td, "contested.json")) for td in track_dirs])
        track_metas = [(_read_json(os.path.join(td, "meta.json")) or {}) for td in track_dirs]
        merged_rq = merge_research_quality(track_metas)
        merged_pm = merge_market_snapshots(
            [_read_json(os.path.join(td, "prediction_markets.json")) for td in track_dirs],
            max_total=int(getattr(Config, "PREDICTION_MARKETS_MAX", 20) or 20),
            max_per_event=int(getattr(Config, "PREDICTION_MARKETS_MAX_PER_EVENT", 3) or 3),
        )
        selected_market_ids = {
            str(row.get("market_id") or "").strip()
            for row in ((merged_pm or {}).get("markets") or [])
            if isinstance(row, dict) and str(row.get("market_id") or "").strip()
        }
        merged_market_history = merge_market_price_histories(
            [_read_json(os.path.join(td, "market_price_history.json")) for td in track_dirs],
            selected_market_ids,
        )

        if degraded:
            merged_rq["degraded"] = True
            merged_rq.setdefault("degradation", [])
            merged_rq["degradation"].append(f"parallel-tracks {survived}/{n} survived")

        # 合并 meta：以首个非空轨 meta 为基底（其它观测字段自洽），覆写 research_quality
        # 为「取最小值」的合并块，并按合并后的 sources 重算 source_tiers/计数（诚实）。
        base_meta: dict = next((m for m in track_metas if m), {})
        merged_meta = dict(base_meta)
        merged_meta["research_quality"] = merged_rq
        merged_source_health = merge_source_health(track_metas)
        if merged_source_health is not None:
            merged_meta["source_health"] = merged_source_health
        merged_meta["source_tiers"] = _source_tier_histogram(merged_sources)
        merged_meta["sources_count"] = len(merged_sources)
        if isinstance(merged_actors, dict):
            merged_meta["actors_count"] = len(merged_actors.get("actors") or [])
            merged_meta["relationships_count"] = len(merged_actors.get("relationships") or [])
        merged_meta["parallel_research"] = {
            "requested": n, "survived": survived,
            "angles": [angles[i][0] for i in sorted(results)],
            "citation_remap": {
                "markers": sum(item.get("markers", 0) for item in citation_audits),
                "remapped": sum(item.get("remapped", 0) for item in citation_audits),
                "stripped": sum(item.get("stripped", 0) for item in citation_audits),
            },
        }
        merged_meta["actor_dossier_compaction"] = dossier_audit
        if isinstance(merged_pm, dict):
            merged_meta["prediction_markets_count"] = len(merged_pm.get("markets") or [])
            merged_meta["prediction_markets_as_of"] = merged_pm.get("as_of")
            merged_meta["prediction_market_status"] = merged_pm.get("status")
        if merged_market_history:
            merged_meta["prediction_market_price_history_count"] = len(merged_market_history)

        # W9-7：合并卷宗的一次有界 LLM 整理——合并 K 份执行摘要为统一开篇、点名跨轨冲突的
        # 头条数字、'# Track N' H1 降级为 Part H2。只喂各轨执行摘要（cap ~30K 字符）；
        # 失败回退纯拼接（与今日逐字节一致）。存活 <2 轨时无需整理。
        if survived >= 2:
            if bool(getattr(Config, "RESEARCH_TRACK_RECONCILE", True)):
                upd(97, "整理多轨卷宗（合并执行摘要 + 跨轨分歧）…")
                merged_report, _rec_audit = reconcile_track_reports(
                    merged_report, labeled_reports)
            else:
                # Disabling the optional LLM editor must not re-enable the
                # known duplicate-summary/H1-scaffolding defect.
                merged_report, _unused_opening = _deterministic_track_report(
                    labeled_reports)
                _rec_audit = {
                    "applied": False,
                    "reason": "llm reconciliation disabled",
                    "fallback": "deterministic",
                }
            state.options["research_track_reconcile"] = _rec_audit
            if not _rec_audit.get("applied"):
                logger.info(
                    "[%s] LLM 卷宗整理未应用（%s），已使用确定性去重卷宗",
                    state.pipeline_id, _rec_audit.get("reason"))

        # Each track starts its citation namespace at S1. At this point every
        # marker has been remapped to merged_sources, so publish exactly one
        # global References section rather than K colliding local ledgers.
        merged_report = append_merged_references(merged_report, merged_sources)

        # 落盘合并产物到 handoff_dir（下游/resume 读的正是这些文件）
        report_path = os.path.join(handoff_dir, "research_report.md")
        write_text_atomic(report_path, merged_report)
        if merged_dossier.strip():
            write_text_atomic(os.path.join(handoff_dir, "actor_dossier.md"), merged_dossier)
        if isinstance(merged_actors, dict):
            write_json_atomic(os.path.join(handoff_dir, "actors.json"), merged_actors)
        if merged_sources:
            write_json_atomic(os.path.join(handoff_dir, "sources.json"), merged_sources)
        if merged_timeline:
            write_json_atomic(os.path.join(handoff_dir, "timeline.json"), merged_timeline)
        if merged_quant:
            write_json_atomic(os.path.join(handoff_dir, "quantitative.json"), merged_quant)
        if merged_contested:
            write_json_atomic(os.path.join(handoff_dir, "contested.json"), merged_contested)
        if isinstance(merged_pm, dict):
            write_json_atomic(os.path.join(handoff_dir, "prediction_markets.json"), merged_pm)
        if merged_market_history:
            write_json_atomic(
                os.path.join(handoff_dir, "market_price_history.json"),
                merged_market_history,
            )
        write_json_atomic(os.path.join(handoff_dir, "meta.json"), merged_meta)

        # 合并遥测：token/工具量求和；wall_s 取最大（并行）；model/depth 取首轨。
        tels = [res.get("research_telemetry") or {} for (_t, _td, res) in ordered]

        def _sum(key: str) -> int:
            return sum(int(t.get(key) or 0) for t in tels)

        merged_tel = {
            "model": (tels[0].get("model") if tels else None) or Config.DEERFLOW_MODEL,
            "depth": tels[0].get("depth") if tels else None,
            "tokens_in": _sum("tokens_in"),
            "tokens_out": _sum("tokens_out"),
            "tokens_total": _sum("tokens_total") or (_sum("tokens_in") + _sum("tokens_out")),
            "tokens_cached": _sum("tokens_cached"),
            "tool_calls": _sum("tool_calls"),
            "results": _sum("results"),
            "wall_s": max((float(t.get("wall_s") or 0.0) for t in tels), default=0.0),
            "parallel_tracks": survived,
        }
        # INFRA-8: every lane's resolved model and served ids.
        _resolution = model_provenance.merge_research_model_resolutions(
            t.get("model_resolution") for t in tels)
        if _resolution is not None:
            merged_tel["model_resolution"] = _resolution

        state.options["parallel_research"] = merged_meta["parallel_research"]
        state.options["actor_dossier_compaction"] = dossier_audit
        if degraded:
            logger.warning("[%s] 并行研究降级：%d/%d 轨存活", state.pipeline_id, survived, n)
        PipelineManager.save(state)

        return {
            "report": merged_report,
            "report_path": report_path,
            "actor_dossier": merged_dossier if merged_dossier.strip() else "",
            "actors": merged_actors,
            "sources": merged_sources,
            "timeline": merged_timeline,
            "exit_code": 0,
            "research_telemetry": merged_tel,
        }

    # -- 内部：嵌入预热 (R2-EXEC-7) ---------------------------------------

    def _maybe_warm_embedder(self, state: PipelineState, actors: Any) -> None:
        """R2-EXEC-7: best-effort warm the local embedder during research/ontology.

        Loads the SentenceTransformer model and pre-embeds actor names/aliases on a
        daemon thread so the graph stage meets a warm model + a populated disk cache
        (EMBED_DISK_CACHE_PATH) instead of paying first-encode latency mid-build.
        Default-OFF (EMBED_WARM_AT_RESEARCH); fully best-effort — failures are swallowed
        and the daemon thread can never block or wedge the pipeline."""
        if not getattr(Config, "EMBED_WARM_AT_RESEARCH", False):
            return
        try:
            from ..utils.actors import extract_actor_rows
            rows = extract_actor_rows(actors)
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            return
        texts: list[str] = []
        seen: set[str] = set()
        for r in rows:
            aliases = r.get("aliases") if isinstance(r.get("aliases"), list) else []
            for cand in [r.get("name"), *aliases]:
                s = str(cand or "").strip()
                if s and s not in seen:
                    seen.add(s)
                    texts.append(s)
            if len(texts) >= 600:
                break
        if not texts:
            return
        pid = state.pipeline_id

        def _warm() -> None:
            try:
                from .graphiti_client.embedder import LocalSentenceTransformerEmbedder
                emb = LocalSentenceTransformerEmbedder()
                # 分批编码，写穿到共享磁盘缓存（按 model+text 寻址，graph 阶段命中即近零成本）。
                for i in range(0, len(texts), 128):
                    emb._encode(texts[i:i + 128])
                logger.info("[%s] 嵌入预热完成：%d 个 actor 名/别名", pid, len(texts))
            except Exception as _we:  # noqa: BLE001 — 预热纯增益，失败无声
                logger.debug("[%s] 嵌入预热跳过: %s", pid, _we)

        try:
            threading.Thread(target=_warm, name=f"embed-warm-{pid[:8]}", daemon=True).start()
        except Exception:  # noqa: BLE001
            pass

    # -- 内部：主流程 ------------------------------------------------------

    @classmethod
    def _run(cls, state: PipelineState) -> None:
        self = cls()
        task_manager = TaskManager()
        # EXECPLAN2 I-5-0/I-5-2: 把本次管线所有 LLM 调用归属到该 pipeline_id（contextvars）。
        from ..utils.telemetry import set_run_context, LLMMeter
        set_run_context(state.pipeline_id)
        # DEFECT-1：注册本 attempt 的运行级中断熔断器（旋钮关闭时返回 None、零行为差异），
        # 并确保 LLMClient.chat 的进程级探针在位（幂等、自愈；无熔断器时完全透传）。
        if _register_outage_breaker(state.pipeline_id) is not None:
            _install_llm_outage_probe()
        # W9-3: attempt 起点初始化遥测增量落盘（捕获上一 attempt 的账作合并基底）。
        self._init_telemetry_flush(state)
        # I-8-1: 管线起飞即写首版 run.json（解析后的研究深度/模型/图谱/环境指纹），
        # 后续每阶段进入时把热切换出的报告/模拟 provider 钉入。
        self._write_run_manifest(state)
        # EVAL-15: 清掉上一 attempt 的记分卡侧车与摘要（本 attempt 的 finally 块会重写）。
        self._reset_stage_scorecard_sidecar(state)
        # I-4-1: 钉入本进程的 owner 指纹 + 启动一个独立于阶段进度的壁钟心跳看护线程。
        # 心跳让 reconcile_orphans 把「死管线」与「慢但活（深研究/persona 静默数分钟）」区分开。
        hb_stop = self._start_heartbeat(state)
        try:
            # INFRA-7：对比准入钉住的运行形状与当前环境；漂移默认记录后继续，refuse 策略下失败。
            self._check_run_shape_drift(state)
            # ---- Stage 0: RESEARCH ----
            upd = self._make_stage_updater(state, STAGE_RESEARCH)
            handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
            report_path = os.path.join(handoff_dir, "research_report.md")
            _report_candidate = (
                os.path.exists(report_path)
                and len(_read_text(report_path).strip()) >= 400
            )
            _contract_present = os.path.exists(
                _research_contract_path(handoff_dir))
            _research_stage = state.stages.get(STAGE_RESEARCH)
            _stage_was_complete = bool(
                _research_stage and _research_stage.status == "completed")
            _reuse_research = False
            _evidence_manifest_path = os.path.join(
                handoff_dir, "evidence_synthesis_manifest.json")
            _synthesis_recovery_manifest: Optional[str] = None
            if _report_candidate:
                if _contract_present:
                    _integrity_valid = _validate_research_contract(handoff_dir)
                    if not _integrity_valid:
                        logger.warning(
                            "[%s] 研究 contract manifest 校验失败，拒绝复用混合/篡改产物",
                            state.pipeline_id,
                        )
                        if os.path.isfile(_evidence_manifest_path):
                            _synthesis_recovery_manifest = _evidence_manifest_path
                    else:
                        _quality_errors = _research_contract_quality_errors(
                            handoff_dir,
                            require_judge=os.path.isfile(
                                _evidence_manifest_path),
                        )
                        if _quality_errors:
                            logger.warning(
                                "[%s] 研究 contract 完整但未通过发布质量门（%s）；"
                                "拒绝复用并仅重跑全局综合",
                                state.pipeline_id,
                                ", ".join(_quality_errors),
                            )
                            if os.path.isfile(_evidence_manifest_path):
                                _synthesis_recovery_manifest = (
                                    _evidence_manifest_path)
                        else:
                            _reuse_research = True
                elif _stage_was_complete:
                    _reuse_research = self._validate_reuse(
                        state, STAGE_RESEARCH)
                else:
                    logger.warning(
                        "[%s] 发现未带完成阶段/contract manifest 的研究报告，拒绝长度式复用",
                        state.pipeline_id,
                    )
            elif os.path.isfile(_evidence_manifest_path):
                # A prior synthesis may have failed before publishing any root
                # report.  Lane packs are still independently checksummed by
                # this manifest, so recover synthesis without replaying research.
                _synthesis_recovery_manifest = _evidence_manifest_path
            if _reuse_research:
                upd(95, "复用已有研究报告，跳过 DeerFlow 研究阶段…")
                research = _load_research_handoff(handoff_dir)
                state.research_pid = None
            else:
                upd(1, "准备深度研究…")
                def _persist_research_pid(pid: int) -> None:
                    state.research_pid = pid
                    PipelineManager.save(state)

                # TIME-7: a pinned hindcast reaches research only through the v3 single-lane
                # launch below, the one path that dates the child to its as-of.  The global
                # synthesis recovery re-runs the legacy synthesis child without it, and its
                # manifest is written only by legacy parallel lanes, which a hindcast never
                # runs: fail closed before any spend.
                _hindcast_pin = hindcast_policy(state.options)
                if _hindcast_pin is not None and _synthesis_recovery_manifest:
                    raise RuntimeError(
                        "hindcast_synthesis_refused: pinned hindcast (as_of "
                        f"{_hindcast_pin.get('as_of')}) cannot recover a legacy global synthesis, "
                        "which runs without the as-of; remove evidence_synthesis_manifest.json "
                        "from its handoff dir and resume to re-run v3 research")
                if _synthesis_recovery_manifest:
                    research = self._run_research_synthesis_recovery(
                        state,
                        handoff_dir,
                        upd,
                        _synthesis_recovery_manifest,
                    )
                # PAR-2：多角度并行研究轨。>1 时并行跑 K 个研究子进程（每轨角度特化）后
                # 确定性合并回 handoff/；=1 时走今日单轨路径（下方 else 逐字节不变）。
                else:
                    # Engine v3 fans out internally → exactly one outer lane; the
                    # legacy engine keeps today's RESEARCH_PARALLEL_TRACKS rule.
                    # The run's pinned actor policy may require the legacy engine.
                    _research_engine = research_engine_for_run(state.options)
                    # TIME-7: a pinned hindcast is re-checked at launch (config drift or a
                    # resume could select legacy, which would roll the as-of forward): fail
                    # closed before any spend; the stage stays resumable once v3 is back.
                    if _hindcast_pin is not None and _research_engine != RESEARCH_ENGINE_V3:
                        raise RuntimeError(
                            "hindcast_engine_mismatch: pinned hindcast (as_of "
                            f"{_hindcast_pin.get('as_of')}) requires the v3 research engine, "
                            f"but this run resolves {_research_engine}; set RESEARCH_ENGINE=v3 "
                            "and resume")
                    _n_tracks = research_outer_track_count(
                        getattr(Config, "RESEARCH_PARALLEL_TRACKS", 3),
                        _research_engine,
                        pipeline_id=state.pipeline_id,
                    )
                    if _n_tracks > 1:
                        research = self._run_parallel_research_tracks(
                            state, handoff_dir, upd, _n_tracks)
                    else:
                        # ITEM-3：本次研究阶段是 resume/orphan-reclaim 重试且 handoff_dir 已有
                        # checkpoint（上一轮崩溃/超时前写下）→ 续跑而非全量重启。首跑无 checkpoint → False。
                        _resume_lineage = (
                            _validated_research_checkpoint_lineage(
                                handoff_dir,
                                prompt=state.prompt,
                                depth=str(
                                    state.options.get("depth")
                                    or getattr(
                                        Config,
                                        "DEERFLOW_RESEARCH_DEPTH",
                                        "standard",
                                    )
                                ),
                                run_id=state.pipeline_id,
                                lane_id="outer-track-1",
                                expected_attempt_ids=(
                                    _research_budget_attempt_ids(state)
                                ),
                            )
                        )
                        _resume_attempt_id = _resume_lineage.get(
                            "attempt_id", ""
                        )
                        _resume_research = bool(_resume_attempt_id)
                        if _resume_research:
                            upd(1, "检测到研究断点，续跑（复用已完成 pass）…")
                        _single_global_subagents = getattr(
                            Config, "RESEARCH_GLOBAL_SUBAGENT_CAP", 9)
                        _single_model_concurrency = research_model_concurrency_cap(
                            1,
                            _single_global_subagents,
                            getattr(Config, "RESEARCH_GLOBAL_MODEL_CONCURRENCY", 0),
                        )
                        _single_subagent_cap = research_lane_subagent_cap(
                            1,
                            _single_global_subagents,
                            getattr(Config, "RESEARCH_SUBAGENTS_PER_TRACK_MAX", 5),
                            _single_model_concurrency,
                        )
                        (
                            _single_budget_db,
                            _single_budget_telemetry,
                            _single_budget_epoch,
                        ) = _activate_research_budget_epoch(state, handoff_dir)
                        _single_exhausted = _research_budget_exhaustion(
                            _single_budget_telemetry, _single_budget_epoch)
                        if _single_exhausted:
                            raise RuntimeError(
                                "research_budget_exhausted before track launch "
                                f"(epoch={_single_budget_epoch}, "
                                f"budget={_single_exhausted}); explicit pipeline "
                                "resume is required for a new bounded epoch"
                            )
                        research = DeerFlowResearchRunner.run(
                            state.prompt,
                            handoff_dir,
                            on_progress=upd,
                            depth=state.options.get("depth"),
                            language=state.options.get("research_language"),  # T5.5
                            model=state.options.get("research_model"),        # T5.5
                            cancel_event=cls._cancel_events.get(state.pipeline_id),
                            on_spawn=_persist_research_pid,
                            resume=_resume_research,
                            # W9-9：图谱已存在（resume-with-graph/fork/continue 血统）时接入 KG MCP；
                            # 首跑 graph_id 为 None → env 与今日逐字节一致。
                            kg_graph_id=state.graph_id,
                            budget_db_path=_single_budget_db,
                            budget_lane_id="outer-track-1",
                            budget_telemetry_path=_single_budget_telemetry,
                            budget_run_id=state.pipeline_id,
                            budget_epoch=_single_budget_epoch,
                            resume_attempt_id=_resume_attempt_id,
                            resume_checkpoint_id=_resume_lineage.get(
                                "checkpoint_id", ""
                            ),
                            subagents=bool(
                                getattr(Config, "DEERFLOW_SUBAGENTS", True)
                                and _single_subagent_cap > 0),
                            max_concurrent_subagents=max(1, _single_subagent_cap),
                            model_concurrency_global=_single_model_concurrency,
                            research_engine=_research_engine,
                            as_of=_hindcast_pin["as_of"] if _hindcast_pin else None,
                            # TIME-8: the admission pin's gates (None: no pin, or a pin
                            # admitted before TIME-8 -> no gates).
                            pit=(_hindcast_pin or {}).get("pit"),
                        )
                state.research_pid = None  # 子进程已结束，清掉以免 reconcile 误杀复用 PID
                # PAR-2：并行轨 PID 清单也一并清空（研究阶段已结束，避免 reconcile 误杀复用 PID）。
                state.options.pop("research_track_pids", None)
            report_md: str = research["report"]
            # W9-11: 研究卷宗定稿后跑确定性编辑 lint（report_lint 由报告链工作流并行落地；
            # 模块缺失 → ImportError → 静默跳过）。清理 [citation:...] 残渣、pass/working-notes
            # 叙述泄漏等机器语法；只有 manifest-owned（多轨）卷宗采纳清洗结果，由下方
            # _finalize_research_contract 在私有 generation 中封存；其余一律 audit-only。
            if bool(getattr(Config, "REPORT_LINT", True)):
                try:
                    from .report_lint import lint_report
                    _judge_bound_report = _research_report_is_judge_bound(
                        handoff_dir
                    )
                    # Single-lane reports (every v3 run, legacy with one lane)
                    # publish no contract manifest: the bridge already
                    # finalized their citations, References and positional
                    # sources.json (v3 also QA'd those exact bytes), and lint
                    # rewrites would delete cited claims or mint citations
                    # after that validation.  Lint is an audit there, exactly
                    # like the judge-bound case.
                    _lint_audit_only = _judge_bound_report or not os.path.exists(
                        _research_contract_path(handoff_dir)
                    )
                    _lint_lang = (state.options.get("research_language")
                                  or getattr(Config, "DEERFLOW_RESEARCH_LANGUAGE", None))
                    if not _lint_lang:
                        # 无显式语言时按正文 CJK 占比推断（lint 用它决定改写文案的语言；
                        # report_lint._is_zh 会把空串当中文，英文卷宗须显式给 'English'）。
                        _sample = report_md[:20000]
                        _cjk_n = len(re.findall(r"[一-鿿]", _sample))
                        _lint_lang = "Chinese" if _cjk_n > max(1, len(_sample)) * 0.05 else "English"
                    _cleaned, _lint_rep = lint_report(report_md, _lint_lang, mode="research")
                    if isinstance(_cleaned, str) and _cleaned.strip() and _cleaned != report_md:
                        if _judge_bound_report:
                            # The bridge finalizes citations before its real
                            # report judge.  Any parent-side prose edit would
                            # invalidate that exact evidence binding.  Keep lint
                            # as an audit only; a desired prose mutation belongs
                            # upstream of judging, never in post-processing.
                            logger.info(
                                "[%s] 研究卷宗 lint 提议了 judge-bound 字节变更；"
                                "已保留受审原文（audit-only）",
                                state.pipeline_id,
                            )
                            if isinstance(_lint_rep, dict):
                                _lint_rep = dict(_lint_rep)
                                _lint_rep["post_judge_mutation_suppressed"] = True
                        elif _lint_audit_only:
                            logger.info(
                                "[%s] 研究卷宗 lint 提议了单轨卷宗字节变更；"
                                "已保留 bridge 定稿原文（audit-only）",
                                state.pipeline_id,
                            )
                        else:
                            # A manifest-owned report is finalized in a private
                            # generation below; writing it here would invalidate
                            # the still-published producer contract before an
                            # atomic replacement is ready.
                            report_md = _cleaned
                            research["report"] = _cleaned
                    if isinstance(_lint_rep, dict):
                        _lint_record = {
                            k: v for k, v in _lint_rep.items()
                            if isinstance(v, (int, float, str, bool))
                        }
                        _lint_record["audit_only"] = _lint_audit_only
                        state.options["research_lint"] = _lint_record
                except ImportError:
                    logger.debug("report_lint 未部署，跳过研究卷宗 lint")
                except Exception as _lint_err:  # noqa: BLE001 — lint 是增强，失败保留原文
                    logger.warning("[%s] 研究卷宗 lint 跳过: %s", state.pipeline_id, _lint_err)
            # 双轨 Track B：角色本体档案（actor_dossier.md）。它是本体/角色抽取的主种子，
            # 研究报告（Track A）作为补充上下文。旗标关闭或 Track B 缺失时为 None/""，
            # 下游 document_texts/chunks 退化为单轨，与今日逐字节一致。
            dossier_md = research.get("actor_dossier")
            actors = research.get("actors")
            # NEXTSTEPS P3-2: 抽取后跨轨去重，把同一实体的重复行合并为规范行（默认开；只会收紧
            # cast，无重复时 no-op）。actor-intelligence/v1 已在 producer 边界封存 roster/hash，
            # 因此只能做只读重复审计；legacy/pre-v1 才保留实际合并。
            if getattr(Config, "CAST_RECONCILE", True) and actors:
                try:
                    _recon, _audit = _reconcile_research_cast(actors)
                    if _audit.get("merged"):
                        if _audit.get("applied"):
                            actors = _recon
                            # Legacy cast: keep downstream and outer checksum
                            # generation aligned with the reconciled object.
                            research["actors"] = _recon
                        _hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                        try:
                            from ..utils.atomic import write_json_atomic
                            if (
                                _audit.get("applied")
                                and not os.path.exists(_research_contract_path(_hd))
                            ):
                                write_json_atomic(
                                    os.path.join(_hd, "actors.json"), _recon)
                            write_json_atomic(os.path.join(_hd, "cast_reconciliation.json"), _audit)
                            state.artifacts["cast_reconciliation"] = os.path.join(_hd, "cast_reconciliation.json")
                        except Exception:  # noqa: BLE001
                            pass
                        state.options["cast_reconciliation"] = {
                            "n_before": _audit.get("n_before"), "n_after": _audit.get("n_after"),
                            "merges": len(_audit.get("merged") or []),
                            "applied": bool(_audit.get("applied")),
                            "reason": _audit.get("reason"),
                            "hypothetical_n_after": _audit.get("hypothetical_n_after"),
                        }
                        if _audit.get("applied"):
                            logger.info("[%s] cast 去重：%s→%s（合并 %s 组）", state.pipeline_id,
                                        _audit.get("n_before"), _audit.get("n_after"),
                                        len(_audit.get("merged") or []))
                        else:
                            logger.warning(
                                "[%s] sealed actor-intelligence/v1 检出 %s 组潜在重复；"
                                "保留 producer roster 原样（hypothetical %s→%s）",
                                state.pipeline_id,
                                len(_audit.get("merged") or []),
                                _audit.get("n_before"),
                                _audit.get("hypothetical_n_after"),
                            )
                except Exception as _rc_err:  # noqa: BLE001 — 去重为增强，失败回退原 cast
                    if _is_sealed_actor_intelligence_v1(actors):
                        raise RuntimeError(
                            "sealed actor-intelligence/v1 duplicate audit failed"
                        ) from _rc_err
                    logger.warning("[%s] cast 去重跳过: %s", state.pipeline_id, _rc_err)
            # I-5-7: 把研究阶段遥测并入统一计量（stash 到 options + 喂给 meter）。
            self._record_research_telemetry(state, research.get("research_telemetry"))
            # R2-EXEC-7: 趁本体/建图阶段尚未到来，后台预热嵌入器并预嵌 actor 名/别名
            # （默认关，EMBED_WARM_AT_RESEARCH；纯增益、daemon 线程、失败无声）。
            self._maybe_warm_embedder(state, actors)
            # I-0-3: 透传研究覆盖度/质量记分牌（meta.json → options，纯观测，永不硬失败）。
            _final_research_meta = self._surface_research_quality(
                state, handoff_dir)
            if isinstance(_final_research_meta, dict):
                research["meta"] = _final_research_meta

            # NEXTSTEPS P3-4: 计算并透传 dossier 载荷字段覆盖率（纯观测；让"空壳种子"可见）。
            try:
                from ..utils.actors import dossier_coverage as _dcov
                cov = _dcov(actors)
                state.options["dossier_coverage"] = cov
                _weak = []
                if cov.get("n_actors", 0) and cov.get("pct_actors_with_incentives", 0) < 0.34:
                    _weak.append("多数 actor 缺激励结构")
                if cov.get("n_tier12", 0) and cov.get("pct_tier12_with_worldview", 0) < 0.34:
                    _weak.append("核心 actor 多缺世界观")
                if cov.get("n_relationships", 0) and cov.get("pct_edges_valenced", 0) < 0.2:
                    _weak.append("关系网几乎无显式 valence")
                if cov.get("n_relationships", 0) == 0:
                    _weak.append("无关系边")
                if _weak:
                    state.options["dossier_coverage_warning"] = "；".join(_weak)
                    logger.warning("[%s] dossier 覆盖偏低：%s", state.pipeline_id, "；".join(_weak))
            except Exception as _cov_err:  # noqa: BLE001 — 覆盖度纯观测，失败不影响主流程
                logger.debug("[%s] dossier_coverage 计算跳过: %s", state.pipeline_id, _cov_err)

            # SIM-ADD-1：pre-v1 研究定稿前可继续从报告补 forecast_inputs。v1 producer
            # contract 不可变；若漏产该字段，只能显式告警并在上游重做，不能在 reception 后
            # 改写 actors.json 或内存副本。
            try:
                _fi_seed = inject_forecast_inputs_from_report(actors, report_md)
                if _fi_seed is not None:
                    research["actors"] = actors  # 让契约密封与下游都用注入后的 cast
                    logger.info(
                        "[%s] forecast_inputs 兜底解析：从研究报告注入 %d 情景"
                        "（决策通道世界态种子就绪）",
                        state.pipeline_id, len(_fi_seed.get("scenarios") or []))
                elif _forecast_inputs_missing(actors):
                    # 显式的「响亮信号」（对齐先前审计的诉求）：种子仍为空，模拟不会点火。
                    if _is_sealed_actor_intelligence_v1(actors):
                        logger.warning(
                            "[%s] sealed actor-intelligence/v1 缺 forecast_inputs；"
                            "拒绝 post-seal 注入，world_state 种子将为空",
                            state.pipeline_id,
                        )
                    else:
                        logger.warning(
                            "[%s] forecast_inputs 缺失且研究报告未解析出情景概率分布——"
                            "world_state 种子将为空、决策通道不会点火、模拟对 forecast 无贡献",
                            state.pipeline_id)
            except Exception as _fi_err:  # noqa: BLE001 — 兜底注入纯增强，绝不阻断研究定稿
                logger.warning("[%s] forecast_inputs 兜底注入跳过: %s",
                               state.pipeline_id, _fi_err)

            # A research stage is complete only after every sanctioned
            # postprocessor and the effective source ledger are sealed into a
            # single manifest-last generation.  The producer generation stays
            # valid throughout this operation and is restored on install error.
            _finalize_research_contract(handoff_dir, research)
            # R2-RES-3: 由 dossier 覆盖度 + 来源层级 + 研究质量记分牌派生一个咨询性
            # forecast_confidence_penalty 写入 options，供发布门后续消费（gate refine 推迟；
            # 此处纯写值，不读不阻断，永不 wedge）。
            # Read the now-finalized metadata so a budget degradation staged
            # above is reflected in the advisory confidence penalty.
            self._surface_forecast_confidence_penalty(state, handoff_dir)
            if state.mode != "research_only":
                # A current full run that requested Track B MUST receive the
                # producer's nonempty, hash-bound v1 actor plane.  Validate
                # before declaring RESEARCH complete so a missing actor plane
                # is a Stage-1 contract failure, never an ontology fallback.
                _enforce_actor_intelligence_reception(
                    state,
                    actors,
                    report=report_md,
                    dossier=dossier_md,
                    sources=research.get("sources"),
                    handoff_dir=handoff_dir,
                )
            self._complete_stage(
                state,
                STAGE_RESEARCH,
                "研究报告已恢复" if _reuse_research else "研究完成",
                reused=_reuse_research,
            )

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
            self._update_manifest(state, STAGE_ONTOLOGY)  # I-8-1: 钉入本阶段实际 provider
            project_name = state.options.get("project_name") or f"研究预测 {state.pipeline_id}"
            project = ProjectManager.get_project(state.project_id) if state.project_id else None
            _reuse_ontology = bool(project is not None and project.ontology)
            # INFRA-7：研究已重算（本 attempt，或此前重建未完成的 attempt）→ 旧本体派生自旧研究，
            # 拒绝复用并在本管线自有项目上重生成；与 base 共用项目的情景分叉 fail closed。
            _onto_refusal = (
                self._lineage_refuses_reuse(state, STAGE_ONTOLOGY) if _reuse_ontology else None)
            if _onto_refusal:
                self._forbid_shared_fork_rebuild(state, STAGE_ONTOLOGY, project, _onto_refusal)
                _reuse_ontology = False
            if _reuse_ontology:
                upd(100, "复用已有本体…")
                self._complete_stage(state, STAGE_ONTOLOGY, "本体已恢复", reused=True)
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
                # I-1-3 领域自适应本体：把研究的 central_question + actors 直方图喂给生成器，
                # 让实体/关系类型贴合预测领域，而不是永远走通用 social_opinion 模板。
                # 模板由 Config.ONTOLOGY_TEMPLATE 控制（general_forecast 有内置兜底回退到
                # social_opinion，故传入即安全）；缺字段时静默降级到旧行为。
                # NEXTSTEPS P3-3: ONTOLOGY_FROM_DOSSIER 开启时，把已实现 actor 阵容投影成本体种子
                # 约束拼到 additional_context 末尾（单一真源，避免从散文重新派生导致 schema/instance
                # 漂移）。默认关 → 行为与今日一致。
                _addl_ctx = _actors_to_context(actors)
                if getattr(Config, "ONTOLOGY_FROM_DOSSIER", False):
                    try:
                        from ..utils.actors import ontology_seed_block as _onto_seed
                        _seed_blk = _onto_seed(actors)
                        if _seed_blk:
                            _addl_ctx = ((_addl_ctx + "\n\n") if _addl_ctx else "") + _seed_blk
                    except Exception:  # noqa: BLE001 — 本体种子为可选增强，失败回退
                        pass
                ontology = generator.generate(
                    # 双轨喂料：角色档案在前作为本体/角色种子，研究报告在后作补充。
                    # dossier_md 为空（旗标关闭/Track B 失败）时退化为 [report_md]，与今日逐字节一致。
                    document_texts=([dossier_md] if dossier_md and dossier_md.strip() else []) + [report_md],
                    simulation_requirement=state.prompt,
                    additional_context=_addl_ctx,
                    # ONT-2: 传 None 才让 ONTOLOGY_AUTO_SELECT（默认开）真正生效——此前恒传
                    # Config.ONTOLOGY_TEMPLATE（非 None），自动选模板在主管线路径是死代码，
                    # 未手工改 ONTOLOGY_TEMPLATE 的部署会把市场/地缘预测硬塞进社媒 schema。
                    # 关闭 AUTO_SELECT 时 _resolve_template(None) 仍回落 Config.ONTOLOGY_TEMPLATE，
                    # 显式配置照旧生效。（关键词误路由已由 ONT-11 的双词组合收紧。）
                    template=None,
                    central_question=(actors.get("central_question") if isinstance(actors, dict) else None),
                    actors=actors,
                )
                # CLAUDE §12.1 / CODEX Step 1：保留完整本体对象。set_ontology 与现有读者只读
                # entity_types/edge_types（见 graph_builder.set_ontology），故除这两键外，生成器
                # 还可能返回的 archetype 分类的类型、边族/valence、analysis_summary、schema_version、
                # domain 等键在被消费前都是惰性的——保留它们零风险，且为下游 valenced/archetype
                # 消费打底。旗标关闭、或生成器只返回两键时，行为与旧逻辑逐字节一致。
                if getattr(Config, "ONTOLOGY_RICH_SCHEMA", True) and isinstance(ontology, dict):
                    project.ontology = dict(ontology)
                    project.ontology["entity_types"] = ontology.get("entity_types", [])
                    project.ontology["edge_types"] = ontology.get("edge_types", [])
                else:
                    project.ontology = {
                        "entity_types": ontology.get("entity_types", []),
                        "edge_types": ontology.get("edge_types", []),
                    }
                project.analysis_summary = ontology.get("analysis_summary", "")
                project.status = ProjectStatus.ONTOLOGY_GENERATED
                ProjectManager.save_project(project)
                # INFRA-7：本体复用以 project.ontology 存在为准（非阶段位）——新本体一落盘即结清其血统
                # 失效项并改戳 run.json，否则在 _complete_stage 前被打断的 attempt 会让下次 resume
                # 拒绝这份新本体，或复用它却沿用被替换本体的 provider 戳。
                self._record_lineage_artifact_replaced(state, STAGE_ONTOLOGY)
                self._stamp_produced_artifact(state, STAGE_ONTOLOGY)
                # T6.3: 把本体落到 handoff/ontology.json，供 artifact 深链。
                # ONT-10: 原子写（对齐 actors.json 的 write_json_atomic 约定）——半写的
                # ontology.json 会让 resume 校验静默强制重建；失败留 warning 而非无声吞掉。
                try:
                    from ..utils.atomic import write_json_atomic
                    _hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                    write_json_atomic(os.path.join(_hd, "ontology.json"), project.ontology)
                except Exception as _oe:  # noqa: BLE001 — 落盘失败非致命，但必须可见
                    logger.warning("[%s] ontology.json 落盘失败: %s", state.pipeline_id, _oe)
                self._complete_stage(state, STAGE_ONTOLOGY, "本体生成完成")

            # ---- Stage 2: GRAPH ----
            upd = self._make_stage_updater(state, STAGE_GRAPH)
            self._update_manifest(state, STAGE_GRAPH)  # I-8-1
            graph_stage_done = state.stages.get(STAGE_GRAPH) and state.stages[STAGE_GRAPH].status == "completed"
            graph_id = state.graph_id or getattr(project, "graph_id", None)
            _reuse_graph = bool(graph_stage_done and graph_id)
            # INFRA-7：研究/本体已重算（本 attempt 或此前未完成重建的 attempt）→ 旧图谱派生自旧种子，
            # 拒绝复用、重建；与 base 共用项目的情景分叉 fail closed。批次问题分叉声明了「共用锚点
            # 图谱、按问题重生成本体」，其本体重算不视为陈旧上游。
            _graph_refusal = self._lineage_refuses_reuse(
                state, STAGE_GRAPH,
                exempt=run_shape.graph_lineage_exempt(state.options)) if _reuse_graph else None
            if _graph_refusal:
                self._forbid_shared_fork_rebuild(state, STAGE_GRAPH, project, _graph_refusal)
                _reuse_graph = False
            _reuse_builder: Optional[GraphBuilderService] = None
            # I-4-3: 复用前先按产物清单校验 GRAPH 阶段的文件产物（communities.json 等）未被半写/篡改；
            # 不符则回落重建并留痕（与下方既有的实体数健康检查并列，两道防线各管一半）。
            if _reuse_graph and not self._reuse_ok(state, STAGE_GRAPH):
                _reuse_graph = False
                state.options["resumed_stage_validation"] = "graph_rebuilt_manifest_mismatch"
                logger.info("[%s] 图谱产物清单校验未通过，回落到重建", state.pipeline_id)
            if _reuse_graph and _is_sealed_actor_intelligence_v1(actors):
                try:
                    persisted_seed_manifest = _load_actor_graph_seed_manifest(state)
                    if persisted_seed_manifest is None:
                        raise RuntimeError("persisted actor graph seed manifest missing")
                    _reuse_builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                    _validate_actor_graph_seed_contract(
                        _reuse_builder,
                        graph_id,
                        actors,
                        phase="reuse",
                        expected_manifest=persisted_seed_manifest,
                        state=state,
                    )
                except Exception as exc:  # noqa: BLE001 — invalid reuse must rebuild
                    _reuse_graph = False
                    state.options["resumed_stage_validation"] = (
                        "graph_rebuilt_actor_seed_readback_mismatch"
                    )
                    logger.warning(
                        "[%s] v1 actor graph seed reuse validation failed; "
                        "rebuilding graph: %s",
                        state.pipeline_id,
                        exc,
                    )
            if _reuse_graph:
                # T6.1/T2.7: 复用前做廉价健康检查——0 实体的图谱被复用会在 PREPARE 阶段崩溃，
                # 故实体数为 0（或查询失败）时回落到重建，并留痕。
                try:
                    from .zep_entity_reader import ZepEntityReader
                    _cnt = len(ZepEntityReader().filter_defined_entities(graph_id, enrich_with_edges=False).entities)
                    state.options["graph_entity_count"] = _cnt
                    if _cnt == 0:
                        _reuse_graph = False
                        state.options["resumed_stage_validation"] = "graph_rebuilt_0_entities"
                        logger.info("[%s] 复用图谱实体数为 0，回落到重建", state.pipeline_id)
                except Exception as e:
                    _reuse_graph = False
                    state.options["resumed_stage_validation"] = "graph_rebuilt_healthcheck_error"
                    logger.warning("[%s] 图谱健康检查失败，回落到重建: %s", state.pipeline_id, e)
            if _reuse_graph:
                upd(100, "复用已有知识图谱…")
                state.graph_id = graph_id
                # KG-6: 本体注册是进程内存字典——后端重启后的复用路径若不重注册，每次
                # SIM_GRAPH_FEEDBACK 写回都以 entity_types=None 抽取、落成裸 'Entity' 标签，
                # 随后被 typed-entity 过滤器整体丢弃。幂等、纯内存写，绝不失败该阶段。
                try:
                    if project is not None and project.ontology:
                        (_reuse_builder or GraphBuilderService(
                            api_key=Config.ZEP_API_KEY
                        )).set_ontology(graph_id, project.ontology)
                except Exception as _ro_err:  # noqa: BLE001
                    logger.warning("reuse-path set_ontology skipped: %s", _ro_err)
                self._complete_stage(state, STAGE_GRAPH, "图谱已恢复", reused=True)
            else:
                upd(5, "构建知识图谱…")
                builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)
                # ORCH-1(5): 切块前剔除 base64/data-URI 内嵌图片（保留 alt/图注）——
                # 图表型报告的单张内嵌图就是数万字符的 base64 噪声，切块后会整段
                # 灌进图谱 episode。仅影响建图输入；本体/报告落盘仍用原文。
                report_chunks = _graph_research_chunks(
                    report_md,
                    "Stage 1 research report",
                )
                dossier_chunks = (
                    _graph_research_chunks(
                        dossier_md,
                        "Stage 1 actor dossier",
                    )
                    if dossier_md else []
                )
                chunks = report_chunks
                # 双轨：角色本体档案非空时也切块并前置注入（角色中心内容先种入图谱，
                # 再由广覆盖研究报告补充）。dynamic-band 用 len(chunks) 重算仍成立。旗标关闭/
                # Track B 缺失时 dossier_md 为 None/""，chunks 与今日逐字节一致。
                #
                # RESEARCH-2 / ONTO-7: 建图输入源可配置，默认 'both' 与今日逐字节一致。
                #   'dossier_only' (RESEARCH-2): dossier 非空时只用 dossier 建图；研究报告仅
                #       继续喂本体 + 报告上下文，不再切块入图。
                #   'report_only'  (ONTO-7): 跳过 dossier 重切块——GRAPH_SEED_FROM_ACTORS 已把
                #       cast 作为 typed 边种入，dossier 散文在此冗余。
                # 未知值或 dossier 缺失/为空一律回退 'both'/当前行为（degrade-safe）。
                _chunk_src = str(getattr(Config, "GRAPH_CHUNK_SOURCE", "both") or "both").strip().lower()
                _have_dossier = bool(dossier_md and dossier_md.strip())
                if _have_dossier and _chunk_src == "dossier_only":
                    chunks = dossier_chunks
                    state.options["graph_chunk_source"] = "dossier_only"
                elif _chunk_src == "report_only":
                    # 报告 chunk 已在 `chunks` 中；dossier 有意不再切块。
                    state.options["graph_chunk_source"] = "report_only"
                elif _have_dossier:
                    chunks = dossier_chunks + chunks
                    state.options["graph_chunk_source"] = "both"
                self._recompute_dynamic_bands(state, chunk_count=len(chunks))  # T6.7: 已知 chunk 数→重排区间
                graph_id = builder.create_graph(name=project.name)
                # EXECPLAN2 F-3-1（跨文件兜底）：set_ontology 已对无名条目逐项跳过；这里再包一层
                # try/except，确保即便整段本体异常也不至于中断 GRAPH 阶段（无本体则按纯文本抽取建图）。
                try:
                    builder.set_ontology(graph_id, project.ontology)
                except Exception as _e:
                    logger.warning(f"set_ontology 失败，回退为无本体建图: {_e}")

                # T2.2/T2.3: 在文本抽取前，把研究确认的 actors + relationships 作为 typed 边
                # 种入图谱；valid_at 锚定研究 as_of（不是建图时刻），后续文本抽取按名+embedding
                # dedup「富化」这些种子节点而非重复创建。as_of 同时作为所有研究 chunk 的
                # reference_time，给 panorama_search 的 active/historical 切分一个真实双时态轴。
                # R2-RES-7: validate the research as_of_date before using it as the
                # bi-temporal anchor; fall back to newest source date / run date on a
                # future, pre-evidence, or unparseable value. Gated default-on; any
                # error or a disabled flag reverts to the plain parse (today's behavior).
                _as_of_validated = False
                # TIME-7: a pinned hindcast anchors at its as-of date; the validator below would
                # roll the anchor forward to a later-dated source (a leak, never newer evidence).
                _hindcast_anchor_pin = hindcast_policy(state.options)
                if _hindcast_anchor_pin is not None:
                    as_of = self._pin_hindcast_graph_anchor(
                        state, _hindcast_anchor_pin, research.get("sources"))
                elif getattr(Config, "VALIDATE_AS_OF_DATE", True):
                    try:
                        as_of, _as_of_note = self._validate_as_of_date(actors, research.get("sources"))
                        if _as_of_note:
                            state.options["as_of_date_correction"] = _as_of_note
                            logger.warning("[%s] %s → %s", state.pipeline_id, _as_of_note,
                                           as_of.date() if as_of else None)
                        _as_of_validated = True
                    except Exception as _ae:  # noqa: BLE001 — 校验失败回退原始解析
                        logger.debug("[%s] as_of 校验跳过: %s", state.pipeline_id, _ae)
                        as_of = parse_as_of((actors or {}).get("as_of_date")) if isinstance(actors, dict) else None
                else:
                    as_of = parse_as_of((actors or {}).get("as_of_date")) if isinstance(actors, dict) else None
                # EVAL-1: 只有校验器实际给出的锚点才成为账本预注册键的 as_of（本次建图重新判定，
                # 旧值先清掉）；回退到原始解析的日期未经校验，不写入。回测钉的锚点已由
                # _pin_hindcast_graph_anchor 记为钉日。
                if _hindcast_anchor_pin is None:
                    self._record_validated_as_of(state, as_of, _as_of_validated)
                seeded = _seed_research_actors(
                    builder, graph_id, actors, valid_at=as_of
                )
                actor_seed_manifest = _validate_actor_graph_seed_contract(
                    builder,
                    graph_id,
                    actors,
                    phase="post_seed",
                    state=state,
                    persist=True,
                )
                if seeded is not None:
                    upd(8, f"已注入 {seeded} 条调研关系/角色种子…")
                    state.options["graph_seeded_edges"] = seeded

                def add_cb(msg: str, ratio: float):
                    upd(int(10 + ratio * 55), msg)

                # batch_size 10：Zep graph.add 按 episode 异步处理，批量提交吞吐近似线性；
                # 3 是早期保守值，研究报告动辄上百 chunk 时建图要多等数分钟。
                uuids = builder.add_text_batches(
                    graph_id, chunks, batch_size=10, progress_callback=add_cb, reference_time=as_of
                )

                # KG-5: 量化 ingest 丢失。builder 对失败 chunk 是跳过续跑（正确的韧性），但跳块
                # 比例超过 GRAPH_MAX_SKIPPED_RATIO 时图谱是「安静残缺」的——留痕到 options，
                # 由 _enforce_pipeline_health 折入 pipeline_health 的 graph 阶段降级。
                try:
                    _ing = getattr(builder, "last_ingest_stats", None)
                    if isinstance(_ing, dict) and int(_ing.get("total") or 0) > 0:
                        _ing_total = int(_ing.get("total") or 0)
                        _ing_failed = int(_ing.get("failed") or 0)
                        state.options["graph_skipped_chunks"] = _ing_failed
                        state.options["graph_total_chunks"] = _ing_total
                        _skip_ratio = _ing_failed / float(_ing_total)
                        _max_skip = float(getattr(Config, "GRAPH_MAX_SKIPPED_RATIO", 0.3) or 0.3)
                        if _skip_ratio > _max_skip:
                            state.options["graph_ingest_degraded_ratio"] = round(_skip_ratio, 3)
                            logger.warning(
                                "[%s] 建图跳块比例 %.0f%%（%d/%d）超过阈值 %.0f%% —— 图谱残缺，"
                                "GRAPH 阶段将标记 degraded", state.pipeline_id,
                                _skip_ratio * 100, _ing_failed, _ing_total, _max_skip * 100)
                except Exception:  # noqa: BLE001 — ingest 统计纯观测
                    pass

                def wait_cb(msg: str, ratio: float):
                    upd(int(65 + ratio * 33), msg)

                builder._wait_for_episodes(uuids, wait_cb)

                # T2.4: best-effort 社区发现（派系/联盟），失败不影响建图。持久化到 handoff/communities.json
                # 供 sim-config 回声室种子（T3.4）与报告派系图（T4.2）复用。
                if Config.GRAPH_BUILD_COMMUNITIES:
                    try:
                        upd(99, "检测派系/社区结构…")
                        communities = builder.build_communities(graph_id)
                        if communities:
                            handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                            os.makedirs(handoff_dir, exist_ok=True)
                            with open(os.path.join(handoff_dir, "communities.json"), "w", encoding="utf-8") as cf:
                                json.dump(communities, cf, ensure_ascii=False, indent=2)
                        state.options["graph_communities"] = len(communities)
                        logger.info("[%s] 社区发现: %d 个", state.pipeline_id, len(communities))
                    except Exception as e:
                        logger.warning("[%s] community detection skipped: %s", state.pipeline_id, e)

                # I-1-4: best-effort entity resolution / canonical-alias merge (no LLM).
                # Runs AFTER communities so merges land before retrieval reads the graph;
                # KG-10b: default-ON (GRAPH_RESOLVE_ENTITIES, config.py 默认 true——并行建图
                # 的 dedup 安全网)。Never blocks the build; audited to handoff/entity_merges.json.
                if Config.GRAPH_RESOLVE_ENTITIES:
                    try:
                        upd(99, "实体消解/规范别名合并…")
                        from .zep_entity_resolver import resolve_entities
                        audit = resolve_entities(graph_id, actors)
                        if audit.get("merges"):
                            handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                            os.makedirs(handoff_dir, exist_ok=True)
                            with open(os.path.join(handoff_dir, "entity_merges.json"), "w", encoding="utf-8") as mf:
                                json.dump(audit, mf, ensure_ascii=False, indent=2)
                        state.options["entity_merges"] = audit.get("merged_nodes", 0)
                        logger.info("[%s] 实体消解: 扫描 %d 合并 %d 节点",
                                    state.pipeline_id, audit.get("nodes_scanned", 0),
                                    audit.get("merged_nodes", 0))
                    except Exception as e:
                        logger.warning("[%s] entity resolution skipped: %s", state.pipeline_id, e)

                # W9-10: 图谱裁剪——把 KG 收敛到研究确认的关键 actor 周边（用户明确要求）。
                # 在实体消解之后、中心度先验计算之前执行，使 graph_priors 反映裁剪后的图。
                # graph_pruner 由 kg-backend 工作流并行落地（模块缺失 → ImportError → 静默跳过）。
                if bool(getattr(Config, "GRAPH_PRUNE_ENABLED", False)):
                    try:
                        from .graph_pruner import prune_graph
                        upd(99, "裁剪外围图谱节点（收敛到关键 actor）…")
                        _actor_rows = (actors.get("actors") if isinstance(actors, dict) else None) or []
                        _prune_audit = prune_graph(graph_id=graph_id, actors=_actor_rows)
                        if isinstance(_prune_audit, dict) and _prune_audit:
                            state.options["graph_prune"] = {
                                k: v for k, v in _prune_audit.items()
                                if isinstance(v, (int, float, str, bool))
                            }
                            try:
                                from ..utils.atomic import write_json_atomic
                                _hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                                write_json_atomic(os.path.join(_hd, "graph_prune.json"), _prune_audit)
                                state.artifacts["graph_prune"] = os.path.join(_hd, "graph_prune.json")
                            except Exception:  # noqa: BLE001 — 审计落盘失败不影响裁剪本身
                                pass
                            logger.info("[%s] 图谱裁剪完成: %s", state.pipeline_id,
                                        state.options.get("graph_prune"))
                    except ImportError:
                        logger.debug("graph_pruner 未部署，跳过图谱裁剪")
                    except Exception as _pr_err:  # noqa: BLE001 — 裁剪失败绝不拖垮建图
                        logger.warning("[%s] 图谱裁剪跳过: %s", state.pipeline_id, _pr_err)

                # A current-v1 seed is an immutable Stage-3 contract, not a
                # best-effort hint.  Re-read every deterministic UUID and
                # required attribute after prose extraction, entity resolution,
                # and optional pruning so those mutators cannot silently erase
                # or override the admitted identity/provenance projection.
                _validate_actor_graph_seed_contract(
                    builder,
                    graph_id,
                    actors,
                    phase="post_mutation",
                    expected_manifest=actor_seed_manifest,
                    state=state,
                )

                # J1: 并发抽取（GRAPH_BUILD_CONCURRENCY>1）的重名实体守卫。
                # add_episodes_concurrent 的 read-before-commit dedup 在并发下可能让两个 episode
                # 都漏掉对方在飞的同名新节点，各自建出重名重复节点（runtime 文档 F-2-5；DB 无名唯一约束）。
                # 实体消解（GRAPH_RESOLVE_ENTITIES，默认关）是缓解手段，但与并发解耦。这里在并发>1 时
                # 做一遍重名 DETECTION：按 NFKC 规范名分组、统计含 >1 节点的组数，记入 graph_integrity 指标，
                # 并在未开消解却检出重复时打 WARNING。全程 best-effort，失败不影响建图；并发==1 时不触发，
                # 默认路径逐字节不变。
                _effective_concurrency = int(getattr(Config, "GRAPH_BUILD_CONCURRENCY", 1) or 1)
                if _effective_concurrency > 1:
                    try:
                        from ..utils.actors import normalize_name as _normalize_name
                        from .graphiti_client.runtime import get_runtime
                        _nodes = get_runtime().all_entity_nodes(graph_id) or []
                        _groups: dict[str, int] = {}
                        for _nd in _nodes:
                            _norm = _normalize_name(_nd.get("name", ""))
                            if not _norm:
                                continue
                            _groups[_norm] = _groups.get(_norm, 0) + 1
                        _dup_groups = sum(1 for _c in _groups.values() if _c > 1)
                        state.options["graph_duplicate_name_groups"] = _dup_groups
                        if _dup_groups and not Config.GRAPH_RESOLVE_ENTITIES:
                            logger.warning(
                                "[%s] 并发建图(GRAPH_BUILD_CONCURRENCY=%d)检出 %d 组重名实体节点，"
                                "而实体消解(GRAPH_RESOLVE_ENTITIES)未开启——重复节点会分裂检索召回/低估中心性。"
                                "建议设 GRAPH_RESOLVE_ENTITIES=true 合并，或回退 GRAPH_BUILD_CONCURRENCY=1",
                                state.pipeline_id, _effective_concurrency, _dup_groups,
                            )
                        elif _dup_groups:
                            logger.info("[%s] 并发建图检出 %d 组重名实体（已开启实体消解）",
                                        state.pipeline_id, _dup_groups)
                    except Exception as e:
                        logger.warning("[%s] duplicate-name detection skipped: %s", state.pipeline_id, e)

                # KG cookbook 第4步：建图后跑结构完整性检查（节点/边/弱连通分量/枢纽），
                # 把分量数等指标记入 state.options 并 emit 日志/欠合并告警（实现在 _get_graph_info）。
                try:
                    gi = builder._get_graph_info(graph_id)
                    state.options["graph_node_count"] = gi.node_count
                    state.options["graph_edge_count"] = gi.edge_count
                    state.options["graph_components"] = gi.components
                    # NEXTSTEPS P3-7: 持久化中心度先验（node_name→[0,1]）供 PREPARE 的 salience
                    # 排序融合 + 报告/UI 引用；此前 _get_graph_info 算完即丢弃。
                    # KG-7: 按 actors.json 策展别名组折叠（组内 MAX、ADD-only、旗标内部门控）——
                    # 同一现实 actor 的表面形不再把影响力信号打碎成小分片；无 actors/关旗标时原样返回。
                    if getattr(gi, "centrality", None):
                        try:
                            from ..utils.atomic import write_json_atomic
                            from .graph_builder import fold_priors_with_aliases
                            _hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                            _folded = fold_priors_with_aliases(gi.centrality, actors)
                            write_json_atomic(os.path.join(_hd, "graph_priors.json"), _folded)
                            state.artifacts["graph_priors"] = os.path.join(_hd, "graph_priors.json")
                            state.options["graph_centrality_nodes"] = len(_folded)
                        except Exception:  # noqa: BLE001
                            pass
                    # KG-3: 结构咽喉先验（介数中心度 + 关节点，GRAPH_CHOKEPOINT_PRIORS 开启且
                    # 非空时才有值）。落独立文件，扁平的 graph_priors.json（name→centrality）
                    # 保持不变以兼容旧读者。
                    if getattr(gi, "betweenness", None) or getattr(gi, "chokepoints", None):
                        try:
                            from ..utils.atomic import write_json_atomic
                            _hd = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                            _sp = os.path.join(_hd, "graph_priors_structural.json")
                            write_json_atomic(_sp, {
                                "betweenness": gi.betweenness or {},
                                "chokepoints": gi.chokepoints or [],
                            })
                            state.artifacts["graph_priors_structural"] = _sp
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as e:
                    logger.warning("[%s] graph integrity check skipped: %s", state.pipeline_id, e)

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
            # I-4-3: 复用前校验 PREPARE 产物（simulation_config.json / personas）未被半写/篡改；
            # 不符则当作未完成、走重建分支并留痕（半写的 sim_config 会让模拟/报告静默降级）。
            _prepare_reuse = bool(prepare_stage_done and sim_state is not None)
            # INFRA-7：模拟必须绑定当前图谱，且图谱本 attempt 未重建；否则重建模拟环境。
            if _prepare_reuse and self._lineage_refuses_reuse(
                    state, STAGE_PREPARE,
                    bound_ids=(getattr(sim_state, "graph_id", None), state.graph_id)):
                _prepare_reuse = False
            if _prepare_reuse and not self._reuse_ok(state, STAGE_PREPARE):
                _prepare_reuse = False
                state.options["resumed_stage_validation"] = "prepare_rebuilt_manifest_mismatch"
                logger.info("[%s] 模拟环境产物清单校验未通过，回落到重建", state.pipeline_id)
            if _prepare_reuse:
                try:
                    sim_manager.validate_prepared_simulation_config(
                        sim_state.simulation_id
                    )
                except Exception as exc:  # noqa: BLE001 — seal proof is mandatory
                    _prepare_reuse = False
                    state.options["resumed_stage_validation"] = (
                        "prepare_rebuilt_config_seal_mismatch"
                    )
                    state.options["artifact_validation_error"] = {
                        "stage": STAGE_PREPARE,
                        "artifact": "simulation_config_manifest",
                        "error": str(exc)[:300],
                    }
                    logger.warning(
                        "[%s] 已完成 PREPARE 的配置封印校验失败，回落到重建: %s",
                        state.pipeline_id,
                        exc,
                    )
            if _prepare_reuse:
                upd(100, "复用已有模拟环境…")
                _prepare_completion_message = "环境已恢复"
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
                # XRUN-15: 新模拟 attempt 取代旧 attempt，清掉指向旧 sim/report 目录的
                # *_partial 临时产物指针（扫描器会为新 attempt 重新登记）。
                for _pk in [k for k in list(state.artifacts) if k.endswith("_partial")]:
                    state.artifacts.pop(_pk, None)
                PipelineManager.save(state)

                def prepare_cb(stage: str, progress: int, message: str, **_kwargs):
                    upd(max(5, min(99, int(progress))), f"{stage}: {message}")

                # persona 生成并发：CLI 提供方受本机 CLI 吞吐限制保持 3；
                # OpenAI 兼容 HTTP 提供方可以放心放大（每个 persona 1 次 LLM + 2 次 Zep 检索）。
                _is_http_provider = bool(Config.PROVIDER_META.get(Config.LLM_PROVIDER, {}).get('openai_compat'))
                # P3-7: 读取 GRAPH 阶段持久化的中心度先验，融入 agent-cap 的 salience 排序
                # （从 handoff 读，resume 也能拿到）。缺失则为 None → 排序行为不变。
                _graph_priors = None
                try:
                    _gp_path = os.path.join(
                        state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id),
                        "graph_priors.json")
                    if os.path.exists(_gp_path):
                        with open(_gp_path, "r", encoding="utf-8") as _gf:
                            _graph_priors = json.load(_gf)
                except Exception:  # noqa: BLE001
                    _graph_priors = None
                # SIM-11 (pairs with SIM-7): raise HTTP persona fan-out default 8→16
                # (configurable via PARALLEL_PROFILE_COUNT); CLI providers stay at 3.
                _pp = int(getattr(Config, "PARALLEL_PROFILE_COUNT", 16) or 16)
                # PREP-1: 把本次运行的真实轮数预算透传到事件排期（否则生成器只能按
                # OASIS_DEFAULT_MAX_ROUNDS 钳制，options.max_rounds < 默认时欠覆盖）。
                # CAL：日历模式只透传用户显式 max_rounds（生成器把它当 target_max 粗化
                # 粒度、绝不截断）；默认上限已由生成器自身读取，不在此注入。
                _prep_mr = state.options.get("max_rounds") or (
                    None if _calendar_mode() else (Config.OASIS_DEFAULT_MAX_ROUNDS or None))
                sim_manager.prepare_simulation(
                    simulation_id=sim_state.simulation_id,
                    simulation_requirement=state.prompt,
                    document_text=report_md,
                    progress_callback=prepare_cb,
                    parallel_profile_count=_pp if _is_http_provider else 3,
                    actors=actors,  # 研究档案直通模拟准备：persona/配置以实证立场为准
                    graph_priors=_graph_priors,  # P3-7: 中心度先验（融入 salience 排序）
                    max_rounds=int(_prep_mr) if _prep_mr else None,
                    research_language=state.options.get("research_language"),  # PREP-4
                )
                _prepare_completion_message = "环境就绪"

            # T4.6: 情景 overlay — 把影响力/立场覆盖 + 注入事件确定性落到 simulation_config.json
            _overlay = state.options.get("scenario_overlay")
            # DEFECT-1 (SIM_RESUME_REUSE_COMPLETED): RUN stage 位丢失（崩溃/重启窗口、
            # resume 重置）但磁盘上已有「绑定同一密封配置的已完成模拟」时复用产物，不再
            # 重启子进程重烧配额（2026-07-15 取证：18 轮模拟被 resume 重跑 4 次、损失
            # 3h34m）。必须在下方 PREPARE 的配置注入块之前判定：复用路径要保持配置字节
            # 与该场运行密封时完全一致（重注入/重密封会破坏 seal↔运行的身份绑定）。
            _sim_disk_reuse = False
            if (_prepare_reuse
                    and not (state.stages.get(STAGE_RUN)
                             and state.stages[STAGE_RUN].status == "completed")):
                _sim_ok, _sim_why = self._completed_sim_reusable(state, sim_state)
                if _sim_ok and self._reuse_ok(state, STAGE_RUN):
                    _sim_disk_reuse = True
                    logger.info(
                        "[%s] RUN stage 位缺失，但发现同一密封配置的已完成模拟 %s"
                        "（simulation_end 完成标记 + seal 身份已核验）——复用产物，跳过重跑",
                        state.pipeline_id, sim_state.simulation_id,
                    )
                elif _sim_why and _sim_why != "sim_resume_reuse_completed_disabled":
                    logger.debug(
                        "[%s] 已完成模拟复用不成立（%s）→ 照旧重跑",
                        state.pipeline_id, _sim_why,
                    )
            _run_already_done = _sim_disk_reuse or bool(
                _prepare_reuse and state.stages.get(STAGE_RUN)
                and state.stages[STAGE_RUN].status == "completed"
                and self._run_reuse_ready(state, sim_state)
                and self._reuse_ok(state, STAGE_RUN)
            )
            _config_mutated_after_prepare = False
            if _overlay and not _run_already_done:
                try:
                    _cfg_path = os.path.join(
                        Config.OASIS_SIMULATION_DATA_DIR, sim_state.simulation_id, "simulation_config.json"
                    )
                    if os.path.exists(_cfg_path):
                        with open(_cfg_path, "r", encoding="utf-8") as _cf:
                            _cfg = json.load(_cf)
                        self.apply_scenario_overlay_to_config(_cfg, _overlay)
                        _tmp = _cfg_path + ".tmp"
                        with open(_tmp, "w", encoding="utf-8") as _cf:
                            json.dump(_cfg, _cf, ensure_ascii=False, indent=2)
                        os.replace(_tmp, _cfg_path)
                        _config_mutated_after_prepare = True
                        logger.info("[%s] 情景 overlay 已应用到 simulation_config", state.pipeline_id)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[%s] 情景 overlay 应用跳过: %s", state.pipeline_id, e)

            # NEXTSTEPS P1-1/P1-2: 决策通道开启时，把 WorldState 种子（情景+基率）+ 时点跨度
            # （as_of→horizon，供子进程逐轮日期映射）注入 simulation_config.json，供 post-sim
            # 演化"结果世界态"。默认关 → 不注入，行为与今日逐字节一致。
            # CAL：日历模式无条件注入（去掉 SIM_DECISION_CHANNEL 门控；空情景 → 演化静默关），
            # 并从已生成的 temporal_config 补 horizon_date/horizon_source/horizon_defaulted。
            _cal_gen = _calendar_mode()
            if (_cal_gen or getattr(Config, "SIM_DECISION_CHANNEL", False)) and not _run_already_done:
                try:
                    from ..utils.actors import world_state_seed_from_actors as _ws_seed
                    # SIM-ADD-1（belt-and-suspenders）：pre-v1 种子前再兜底一次。sealed
                    # actor-intelligence/v1 严格 no-op，保持 actor context 的 exact-object
                    # provenance；新契约缺 seed 时只能告警并由 producer 重做。
                    _fi_prep = inject_forecast_inputs_from_report(actors, report_md)
                    if _fi_prep is not None:
                        logger.info("[%s] PREPARE 兜底注入 forecast_inputs：%d 情景",
                                    state.pipeline_id, len(_fi_prep.get("scenarios") or []))
                    _seed = _ws_seed(actors)
                    if not _seed.get("scenarios"):
                        # 响亮信号：即便兜底解析后仍无情景分布，决策通道不会点火。
                        logger.warning(
                            "[%s] world_state 种子为空——研究阶段未产出可用情景概率分布，"
                            "决策通道不会点火、模拟对 forecast 无贡献", state.pipeline_id)
                    if _cal_gen or _seed.get("scenarios"):
                        _seed["as_of_date"] = (actors.get("as_of_date") if isinstance(actors, dict) else None)
                        _seed["horizon_date"] = self._infer_horizon_date(state.prompt, actors)
                        _wcfg_path = os.path.join(
                            Config.OASIS_SIMULATION_DATA_DIR, sim_state.simulation_id, "simulation_config.json")
                        if os.path.exists(_wcfg_path):
                            from ..utils.atomic import write_json_atomic
                            with open(_wcfg_path, "r", encoding="utf-8") as _wf:
                                _wcfg = json.load(_wf)
                            _tc = _wcfg.get("temporal_config")
                            if isinstance(_tc, dict) and _tc.get("mode") == "calendar":
                                # 判定日以 temporal_config 为准（含 LLM/default 兜底结果）
                                _seed["horizon_date"] = _tc.get("horizon_date") or _seed.get("horizon_date")
                                _seed["horizon_source"] = _tc.get("horizon_source")
                                _seed["horizon_defaulted"] = bool(_tc.get("horizon_defaulted"))
                            _wcfg["world_state_seed"] = _seed
                            write_json_atomic(_wcfg_path, _wcfg)
                            _config_mutated_after_prepare = True
                            logger.info("[%s] WorldState 种子已注入 simulation_config（%d 情景, horizon=%s）",
                                        state.pipeline_id, len(_seed.get("scenarios") or []),
                                        _seed.get("horizon_date"))
                except Exception as _ws_err:  # noqa: BLE001
                    logger.warning("[%s] WorldState 种子注入跳过: %s", state.pipeline_id, _ws_err)

            # The manager sealed the initially generated config before the two
            # PREPARE-owned mutation blocks above.  Rebind the exact final bytes
            # and all cast/context/role authorities before RUN can observe the
            # file.  A reseal failure is an admission failure, not a degradable
            # enrichment error.  A completed read-only reuse never reaches it.
            if _config_mutated_after_prepare:
                sim_state = sim_manager.reseal_simulation_config(
                    sim_state.simulation_id
                )

            # PREPARE's integrity fingerprint must cover the final config consumed
            # by RUN. Scenario/world-state injection above mutates
            # simulation_config.json; completing earlier recorded a permanently
            # stale hash and forced every resume to create a new simulation.
            self._complete_stage(
                state,
                STAGE_PREPARE,
                _prepare_completion_message,
                reused=_prepare_reuse,
            )

            # ---- Stage 4: RUN ----
            upd = self._make_stage_updater(state, STAGE_RUN)
            previous_run_done = bool(
                state.stages.get(STAGE_RUN)
                and state.stages[STAGE_RUN].status == "completed"
            )
            # A rebuilt PREPARE attempt invalidates every downstream RUN result,
            # even if the persisted stage bit still says completed.
            run_stage_done = bool(_prepare_reuse and previous_run_done)
            if previous_run_done and not _prepare_reuse:
                state.options["resumed_stage_validation"] = "run_rebuilt_prepare_identity_changed"
                logger.info("[%s] PREPARE attempt 已变化，旧 RUN 结果不可复用", state.pipeline_id)
            if run_stage_done and not self._run_reuse_ready(state, sim_state):
                run_stage_done = False
                state.options["resumed_stage_validation"] = "run_rebuilt_simulation_state_mismatch"
                logger.info("[%s] RUN 状态与当前 simulation identity 不一致，回落到重跑", state.pipeline_id)
            # I-4-3: 复用前校验 RUN 产物（run_summary.json）未被半写/篡改；不符则重跑模拟并留痕。
            if run_stage_done and not self._reuse_ok(state, STAGE_RUN):
                run_stage_done = False
                state.options["resumed_stage_validation"] = "run_rebuilt_manifest_mismatch"
                logger.info("[%s] 模拟结果产物清单校验未通过，回落到重跑", state.pipeline_id)
            # DEFECT-1: stage 位丢失但磁盘证据（完成标记 + seal 身份 + 产物清单）已在
            # PREPARE 边界核验通过 → 走复用分支，不再重启模拟子进程。
            if not run_stage_done and _sim_disk_reuse:
                run_stage_done = True
                state.options["resumed_stage_validation"] = "run_reused_completed_simulation"
                logger.info(
                    "[%s] 复用磁盘上已完成的模拟 %s（SIM_RESUME_REUSE_COMPLETED）",
                    state.pipeline_id, sim_state.simulation_id,
                )
            if run_stage_done:
                upd(100, "复用已有模拟结果…")
                _run_completion_message = "模拟已恢复"
            else:
                upd(2, "启动 OASIS 模拟…")
                # INFRA-7：重跑期间/失败后 run.json 不得把被替换模拟的轮数/日历字段当作本次的。
                self._reset_run_manifest_simulation(state)
                run_kwargs: dict[str, Any] = {"platform": "parallel"}
                # T3.7: 每次运行的 max_rounds 优先，否则用 Config.OASIS_DEFAULT_MAX_ROUNDS（0→None=跑满）。
                # CAL：日历模式运行期不注入默认上限——轮数由 temporal_config.n_rounds 定，
                # 用户显式 max_rounds 也已在配置生成期粗化粒度（运行器会忽略并告警）。
                _mr = state.options.get("max_rounds") or (
                    None if _calendar_mode() else (Config.OASIS_DEFAULT_MAX_ROUNDS or None))
                if _mr:
                    run_kwargs["max_rounds"] = int(_mr)
                # T3.10 → Foglamp WP1 (1A/1B)：模拟 → 观察图反馈默认【关】（I-11/I-12），
                # 且按 run 钉住的安全政策决定，服务重载不改变已准入运行的语义。
                if cls._pinned_safety(state, "sim_graph_feedback",
                                      Config.SIM_GRAPH_FEEDBACK) and graph_id:
                    run_kwargs["enable_graph_memory_update"] = True
                    run_kwargs["graph_id"] = graph_id
                SimulationRunner.start_simulation(simulation_id=sim_state.simulation_id, **run_kwargs)
                # 轮询直到完成
                cancel_ev = cls._cancel_events.get(state.pipeline_id)
                _last_round_seen = (-1, -1)
                # B12: 停滞看门狗——记录上次「轮次推进」的时刻；长时间毫无进展视为卡死。
                _last_progress_at = time.monotonic()
                try:
                    _stall_s = float(getattr(Config, "PIPELINE_RUN_STALL_S", 1800) or 1800)
                except (TypeError, ValueError):
                    _stall_s = 1800.0
                # C1/C2: independent disk-based watchdog that force-stops a wedged sim even if
                # this poll loop blocks on the sim's IPC (the inline check below can't fire then).
                _wd_ctl = self._spawn_run_stall_watchdog(state.pipeline_id, sim_state.simulation_id, _stall_s)
                # ORCH-6: 看门狗退休放 finally——此前只在 COMPLETED 快乐路径置位 stop，取消/
                # FAILED/STOPPED/轮询异常路径会让 daemon 线程继续每 30s 轮询 run_state.json，
                # 并在 stall_s 后对已结束的模拟再次 stop_simulation、伴随整个报告阶段游荡。
                try:
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
                            if total > 0 and (_last_round_seen[1] or 0) <= 0:
                                # CAL：读一次 temporal_config，把日历指纹随成本信号/清单落盘。
                                _tc_sig = None
                                try:
                                    _tc_path = os.path.join(
                                        Config.OASIS_SIMULATION_DATA_DIR,
                                        sim_state.simulation_id, "simulation_config.json")
                                    with open(_tc_path, "r", encoding="utf-8") as _tf:
                                        _tc_cfg = (json.load(_tf) or {}).get("temporal_config")
                                    if isinstance(_tc_cfg, dict) and _tc_cfg.get("mode") == "calendar":
                                        _tc_sig = {
                                            "calendar_unit": _tc_cfg.get("unit"),
                                            "n_rounds": _tc_cfg.get("n_rounds"),
                                            "horizon_date": _tc_cfg.get("horizon_date"),
                                        }
                                except Exception:  # noqa: BLE001 — 观测指纹缺失不阻塞运行
                                    _tc_sig = None
                                self._recompute_dynamic_bands(
                                    state, total_rounds=total, temporal=_tc_sig)  # T6.7
                                self._update_manifest(
                                    state, STAGE_RUN, total_rounds=total, temporal=_tc_sig)  # I-8-1
                            _last_round_seen = (cur, total)
                            _last_progress_at = time.monotonic()  # B12: 有进展即续命看门狗
                            if total > 0:
                                upd(min(98, int(cur / total * 100)), f"模拟轮次 {cur}/{total}")
                            else:
                                upd(5, "模拟进行中…")
                        if rs.runner_status == RunnerStatus.COMPLETED:
                            break
                        if rs.runner_status in (RunnerStatus.FAILED, RunnerStatus.STOPPED):
                            raise RuntimeError(f"模拟未正常结束: {rs.runner_status} {getattr(rs, 'error', '') or ''}")
                        # B12: 停滞看门狗——长时间无轮次推进（区别于「慢但在推进」）判定为卡死，
                        # 停模拟并失败，避免管线线程永久空转。取消仍由循环顶部兜底；默认 30min。
                        if _stall_s > 0 and (time.monotonic() - _last_progress_at) > _stall_s:
                            try:
                                SimulationRunner.stop_simulation(sim_state.simulation_id)
                            except Exception as _wd_err:  # noqa: BLE001
                                logger.warning(f"[{state.pipeline_id}] 看门狗停止模拟失败: {_wd_err}")
                            raise RuntimeError(f"模拟约 {int(_stall_s)}s 无进展（疑似卡死），看门狗已终止")
                        time.sleep(5)
                except BaseException:
                    # DEFECT-3: 失败/取消/停滞的模拟同样烧了真金白银——在阶段失败前把
                    # 子进程已落盘的 sim_llm_telemetry.json 恰好一次入账（_run 的 finally
                    # 会把 LLMMeter 快照终版落盘 run_telemetry.json）。方法自身绝不抛出，
                    # 原始异常原样上抛。
                    self._record_sim_run_telemetry(state, sim_state.simulation_id)
                    raise
                finally:
                    _wd_ctl["stop"] = True  # C1/C2/ORCH-6: 任何退出路径都退休独立看门狗
                # EXECPLAN2 F-12-1: 模拟结束后、读 actions.jsonl 写 run_summary 与跑报告之前，
                # 加一道"汇流栅栏"。runner_status 会在 simulation_end 事件被解析的瞬间就置为
                # COMPLETED（此时 OASIS 进程仍存活、监控线程仍在收尾，「模拟 → 图谱」反馈写入器
                # 也可能还在排空队列向同一张 FalkorDB 图谱写 typed 边/episode）。若直接前进，报告
                # 可能读到只摄入了一半反馈的图谱、run_summary 也可能基于仍在增长的 actions.jsonl，
                # 导致同一模拟的报告 run-to-run 漂移、漏掉末轮反馈动态。故：
                #   (1) join 监控线程 → 保证 OASIS 进程已退出且 _monitor_simulation 的 finally 跑完；
                #   (2) 显式 stop_updater → 其 stop() 会 _flush_remaining 再 join worker（幂等，
                #       即便监控线程已停过也安全）。
                # 仅在本次运行启用了反馈回路时才需要（与 RUN 启动条件一致）；任何卡顿降级为告警，
                # 不让栅栏本身拖垮管线。
                if cls._pinned_safety(state, "sim_graph_feedback",
                                      Config.SIM_GRAPH_FEEDBACK) and graph_id:
                    # F-12-1 汇流栅栏：经公共访问点等待监控线程退出（不再直接读私有注册表）。
                    if not SimulationRunner.join_monitor_thread(sim_state.simulation_id, timeout=30):
                        logger.warning(
                            "[%s] 等待模拟监控线程退出超时（降级继续）", state.pipeline_id,
                        )
                    try:
                        ZepGraphMemoryManager.stop_updater(sim_state.simulation_id)
                    except Exception as _flush_err:  # noqa: BLE001
                        logger.warning(
                            "[%s] 排空图谱反馈写入器失败（降级继续）: %s",
                            state.pipeline_id, _flush_err,
                        )

                _run_completion_message = "模拟完成"

            # T3.14: 模拟结束后聚合 run_summary.json（per-agent engagement + 每轮动作量 + top_posts +
            # 可选派系）。报告阶段的 simulation_outcomes 工具与前端均可直接读，免再 fuzzy 检索。
            _run_summary_published = False
            try:
                _comm = None
                _comm_path = os.path.join(handoff_dir, "communities.json")
                if os.path.exists(_comm_path):
                    with open(_comm_path, "r", encoding="utf-8") as cf:
                        _comm = json.load(cf)
                _run_summary_published = self._publish_run_summary(
                    state,
                    sim_state.simulation_id,
                    communities=_comm,
                    regenerate=not run_stage_done,
                )
                if not _run_summary_published:
                    logger.warning("[%s] run_summary 未生成或结构无效", state.pipeline_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("[%s] run_summary 写出跳过: %s", state.pipeline_id, e)

            # DEFECT-3: RUN 完成边界（新跑与复用共用）恰好一次入账模拟子进程的 token
            # 花费。刻意放在下方完成证据门**之前**：token 已经真实烧掉，门若判失败也不
            # 该丢账（meter_run_token 幂等守卫保证复用/重入/失败钩子的任何组合都不双计；
            # _complete_stage / _fail_stage 都会随后 flush LLMMeter 快照进 run_telemetry）。
            self._record_sim_run_telemetry(state, sim_state.simulation_id)

            # DEFECT-2: hollow-run 完成证据门——rc=0/stage 返回/状态投影都不是完成证据
            # （bug-sweep：子进程可以 rc=0 退出却从未产出 simulation_end，下游把它当成功
            # 消费）。每个启用平台必须有 simulation_end 完成标记，且 run_summary.json 必须
            # 有效；缺任一 → RUN 阶段以清晰讯息判失败（可 resume）。新跑与复用共用此门：
            # legacy 完成位伪装的 hollow 结果同样在此被拦下（与 DEFECT-1 组合：不可复用）。
            _gate_rs = (
                SimulationRunner.get_run_state(sim_state.simulation_id)
                if run_stage_done else rs
            )
            self._require_run_completion_evidence(
                state, sim_state.simulation_id, _gate_rs, _run_summary_published,
            )

            # Reconcile both freshly executed and reused RUNs. The successful EV
            # resume proved that a valid reused summary can coexist with a stale
            # API-facing state.json at round 0; reuse must repair that projection
            # just as a fresh run does.
            try:
                _terminal_rs = (
                    SimulationRunner.get_run_state(sim_state.simulation_id)
                    if run_stage_done else rs
                )
                _summary_path = os.path.join(
                    SimulationRunner.RUN_STATE_DIR,
                    sim_state.simulation_id,
                    "run_summary.json",
                )
                _terminal_summary = (
                    _read_json(_summary_path) if _run_summary_published else None
                )
                ss = sim_manager.get_simulation(sim_state.simulation_id)
                if ss is not None:
                    self._reconcile_completed_simulation_state(
                        ss, _terminal_rs, _terminal_summary,
                    )
                    sim_manager._save_simulation_state(ss)
            except Exception as _state_sync_err:  # noqa: BLE001
                logger.warning(
                    "[%s] 同步终态 simulation state 失败: %s",
                    state.pipeline_id,
                    _state_sync_err,
                )

            # Completion now follows the final summary publication, so the stage
            # manifest and status describe the same durable boundary.
            self._complete_stage(
                state,
                STAGE_RUN,
                _run_completion_message,
                reused=run_stage_done,
            )

            # SIM-ADD-2：决策通道端到端可观测性——一条 per-run 摘要，把「种子了几个情景 /
            # 是否产出 world_state_trajectory.json / 终局结果份额」钉在日志与 options 里，
            # 让「模拟是否真的贡献了 forecast」可事后审计（取证发现此前全靠翻磁盘才知道熄火）。
            try:
                self._log_decision_channel_outcome(state, sim_state.simulation_id)
            except Exception as _dc_obs_err:  # noqa: BLE001 — 观测性，绝不影响主流程
                logger.debug("[%s] 决策通道摘要跳过: %s", state.pipeline_id, _dc_obs_err)

            # ---- Stage 5: REPORT ----
            upd = self._make_stage_updater(state, STAGE_REPORT)
            self._update_manifest(state, STAGE_REPORT)  # I-8-1
            # EXECPLAN2 F-1-0: REPORT 复用守卫——以"已落盘的报告本身"为复用信号，而非
            # stage 状态。REPORT 总是末阶段：当报告已生成、却在收尾 DONE 记账处崩溃/失败时，
            # _fail_stage / mark_failed 会把 REPORT（current_stage）状态翻成 failed，resume()
            # 又把它重置为 pending——因此 state.stages[REPORT].status 在恢复时永远不是 completed，
            # 无法像其它阶段那样用阶段状态做复用判定。改为：若 state.report_id 能解析到一份非
            # FAILED 的已存报告，则直接复用（保留原 report_id，不再凭空铸新 id 孤立前端/书签链接），
            # 避免重复跑最贵的多工具 LLM 报告生成。
            existing_report = None
            if state.report_id:
                try:
                    existing_report = ReportManager.get_report(state.report_id)
                except Exception:
                    existing_report = None
            # 兜底：report_id 丢失但该模拟已有报告时，按 simulation_id 找回（同样保留原 id）。
            if existing_report is None and sim_state is not None:
                try:
                    existing_report = ReportManager.get_report_by_simulation(sim_state.simulation_id)
                except Exception:
                    existing_report = None
            # INFRA-7：报告必须绑定当前模拟，且 RUN 未在其后重跑（本 attempt，或尚未结清的此前
            # attempt——该 attempt 为重建铸出且已完成（COMPLETED）的报告除外；未写完的铸出报告不豁免）；
            # 否则铸新报告。
            if (existing_report is not None
                    and getattr(existing_report, "status", None) != ReportStatus.FAILED
                    and self._lineage_refuses_reuse(
                        state, STAGE_REPORT,
                        bound_ids=(getattr(existing_report, "simulation_id", None),
                                   state.simulation_id),
                        artifact_id=(
                            getattr(existing_report, "report_id", None)
                            if getattr(existing_report, "status", None) == ReportStatus.COMPLETED
                            else None))):
                existing_report = None
            # ORCH-1: 复用前评估交付物本身。meta 说 COMPLETED 但全章占位/无 forecast.json 的
            # 报告若被复用，S1 健康门必再抛错 → resume 陷入「复用坏报告→健康门失败」死循环
            # （report_id=None 手工修复也不够：get_report_by_simulation 兜底会把它找回来）。
            # 交付物判 failed → 弃用复用、落到重建分支铸新 report_id。PIPELINE_HEALTH_GATE 关闭时不改行为。
            if (existing_report is not None
                    and getattr(Config, "PIPELINE_HEALTH_GATE", True)):
                _cand_rid = getattr(existing_report, "report_id", None) or state.report_id
                try:
                    _erh, _eri, _ = self._assess_report_health(_cand_rid)
                except Exception:  # noqa: BLE001 — 评估异常不拦一次合法复用
                    _erh, _eri = "ok", []
                if _erh == "failed":
                    logger.warning("[%s] 现有报告 %s 交付物损坏（%s），弃用复用、重建报告",
                                   state.pipeline_id, _cand_rid, "；".join(_eri)[:200])
                    state.options["report_rebuilt_broken_deliverable"] = _cand_rid
                    existing_report = None
            # ORCH-3(b): force resume 显式要求重生成报告 → 跳过复用（一次性标记，用后即清）。
            if existing_report is not None and state.options.pop("force_report_regen", None):
                logger.info("[%s] force resume：跳过报告复用，重生成", state.pipeline_id)
                existing_report = None
            if existing_report is not None:
                _candidate_report_id = (
                    getattr(existing_report, "report_id", None) or state.report_id
                )
                _previous_report_id = state.report_id
                state.report_id = _candidate_report_id
                if not self._reuse_ok(state, STAGE_REPORT):
                    logger.warning(
                        "[%s] 现有报告 %s 完整性校验失败，跳过复用并重生成",
                        state.pipeline_id, _candidate_report_id,
                    )
                    state.options["report_rebuilt_artifact_validation"] = _candidate_report_id
                    existing_report = None
                    state.report_id = _previous_report_id
            if existing_report is not None and getattr(existing_report, "status", None) != ReportStatus.FAILED:
                upd(100, "复用已有报告")
                state.report_id = getattr(existing_report, "report_id", state.report_id)
                # EVAL-1: 上一 attempt 若没把这份报告记进账本（账本 I/O 失败 / 提交前崩溃），补提交。
                self._repair_reused_report_ledger(
                    state, existing_report,
                    getattr(sim_state, "simulation_id", None) or state.simulation_id,
                    actors, report_md)
                self._complete_stage(state, STAGE_REPORT, "报告完成（复用）", reused=True)
            else:
                # ORCH-8: 报告是最贵的 LLM 阶段，而健康门在全部章节成本烧完后才触发。双 provider
                # 同时不可用（MiniMax 审查/配额 + claude-cli 耗尽）时，先花 ~10 token 探测一次
                # （chat() 自带重试+回退链）；失败即在 <60s 内以可恢复的 REPORT 阶段失败收场，
                # 而不是磨完 N 个占位章节。带 uuid 防命中 LLM_CACHE 的陈旧 'ping' 结果。
                if bool(getattr(Config, "REPORT_LLM_PREFLIGHT", True)):
                    try:
                        from ..utils.llm_client import LLMClient as _PreflightLLM
                        _PreflightLLM().chat(
                            [{"role": "user", "content": f"ping {uuid.uuid4().hex[:8]} — reply: pong"}],
                            temperature=0.0, max_tokens=64,
                        )
                    except Exception as _pf_err:  # noqa: BLE001
                        raise RuntimeError(
                            "报告前置探测失败：主/回退 LLM 提供方均不可用 —— 中止报告阶段以免"
                            f"烧掉全部章节成本（稍后 resume 可从 REPORT 续跑）: {str(_pf_err)[:200]}"
                        ) from _pf_err
                if bool(getattr(Config, "RESUME_LINEAGE_GUARDS", True)):
                    # INFRA-7：一次性 force 标记所要求的重生成此刻开始——血统守卫（或其它复用否决）
                    # 先于上方的 pop 拒绝了复用时标记会残留，下次普通 resume 会丢弃这份新报告再重生成。
                    state.options.pop("force_report_regen", None)
                # XRUN-15/LOOP-005: 铸新报告 = 新 attempt。清掉上一 attempt 的临时及正式
                # REPORT-owned 指针/完整性行，随后在生成开始前持久化新 report_id。这样每次
                # progress callback 都扫描当前 attempt 的 sections/charts，而非旧目录或空目录。
                self._clear_report_attempt_artifacts(state)
                report_id = f"report_{uuid.uuid4().hex[:12]}"
                state.report_id = report_id
                # INFRA-7：报告复用以已落盘报告为准（非阶段位）——记下本次铸出的报告是从当前上游重建的，
                # 使发布后、阶段完成前被取消/熔断/重启打断的 attempt 下次复用它，而非再生成一份。
                self._record_lineage_rebuild_started(state, STAGE_REPORT, report_id)
                # INFRA-7：同一次落盘记下这份报告的生产者；run.json 随即改戳为它（被替换报告的旧戳作废），
                # 发布后、阶段完成前被打断的 attempt 下次复用它时仍按此戳。
                self._record_report_mint(state, report_id)
                PipelineManager.save(state)
                self._stamp_produced_artifact(state, STAGE_REPORT)
                upd(5, "生成预测报告…")
                # T4.6/T4.7: 情景报告 → 传情景标签 + base 模拟 id（反事实对比 scenario_diff）
                _scenario_label = state.options.get("scenario_label")
                _base_sim_id = None
                _base_pid = state.options.get("base_pipeline_id")
                if _base_pid:
                    try:
                        _bd = PipelineManager.load(_base_pid) or {}
                        _base_sim_id = _bd.get("simulation_id")
                    except Exception:
                        _base_sim_id = None
                # Visual ownership boundary: research charts remain relative to the
                # dossier handoff. The final report consumes the shared structured
                # artifacts below and ReportVisualizer generates its own richer,
                # report-owned Plotly set. Passing research paths into every section
                # prompt would duplicate timeline/actor/quantitative figures.
                _ra_kwargs: dict[str, Any] = {
                    "graph_id": graph_id,
                    "simulation_id": sim_state.simulation_id,
                    "simulation_requirement": state.prompt,
                    # T4.1: 钉入研究档案，报告不再从冷图盲搜重挖 cast/关系/时间线
                    "situation_brief": situation_brief(actors),
                    "actors": actors,
                    "sources": research.get("sources"),
                    "research_report": report_md,
                    "scenario_label": _scenario_label,
                    "base_simulation_id": _base_sim_id,
                }
                # TIME-6：回测运行把钉交给报告（不读/不重报价/不现抓预测市场，盖 hindcast 章）；
                # 实时运行不加该参数，构造调用逐字节不变。
                _ra_kwargs.update(self._hindcast_agent_kwargs(state))
                # W9-8: 研究昂贵产物直通报告链——quantitative(339 行)/contested(29 条)/
                # timeline(101 事件)/graph_priors(_structural) 此前落盘后零下游读者。
                # 构造参数由报告链工作流并行落地（None 默认）；尚未支持时 TypeError →
                # 回退旧签名（落地顺序无关）。缺文件时 _read_json 返回 None（同 None 默认）。
                _hd_ra = state.handoff_dir or PipelineManager.handoff_dir(state.pipeline_id)
                _ra_artifacts: dict[str, Any] = {
                    "quantitative": _read_json(os.path.join(_hd_ra, "quantitative.json")),
                    "contested": _read_json(os.path.join(_hd_ra, "contested.json")),
                    "timeline_events": _read_json(os.path.join(_hd_ra, "timeline.json")),
                    "graph_priors": _read_json(os.path.join(_hd_ra, "graph_priors.json")),
                    "graph_priors_structural": _read_json(
                        os.path.join(_hd_ra, "graph_priors_structural.json")),
                }
                try:
                    agent = ReportAgent(**_ra_kwargs, **_ra_artifacts)
                except TypeError:
                    logger.info("[%s] ReportAgent 尚未支持研究工件直通参数，回退旧签名",
                                state.pipeline_id)
                    agent = ReportAgent(**_ra_kwargs)

                # EVAL-11：只有主报告按准入钉决定是否跑骨架跨底座影子检查（None = 不跑）；种子报告 /
                # model_comparison / API 重生成从不设置。
                agent.backbone_check_policy = self._backbone_check_policy(state)

                def report_cb(stage: str, progress: int, message: str):
                    upd(max(5, min(99, int(progress))), f"{stage}: {message}")

                # EVAL-1: 主报告以 production（what-if 由 scenario_label 派生 conditional_scenario）
                # 入账；报告的封印发布即提交权威——其后的集成/健康门失败不撤回账本行。
                report = self._generate_stage_report(
                    state, agent, sim_state.simulation_id, report_id=report_id,
                    progress_callback=report_cb)
                try:
                    ReportManager.save_report(report)
                except Exception:
                    pass
                state.report_id = getattr(report, "report_id", report_id)
                if getattr(report, "status", None) == ReportStatus.FAILED:
                    raise RuntimeError(getattr(report, "error", "报告生成失败"))
                self._complete_stage(state, STAGE_REPORT, "报告完成")

            # ORCH-4: NEXTSTEPS P0-3 多种子集成——此前实现完整却从未被调用（N_FORECAST_SEEDS>1
            # 静默 no-op）。在主报告完成后、健康门之前接线，使集成的信心改写落进被健康门校验的
            # forecast.json。方法自身在 N_FORECAST_SEEDS<=1（默认）时直接返回，默认行为逐字节不变。
            if state.mode == "full":
                try:
                    self._maybe_run_seed_ensemble(state, project, graph_id, actors, research, report_md)
                except PipelineCancelled:
                    raise
                except Exception as _ens_err:  # noqa: BLE001 — 集成失败不拖垮已成功的主跑
                    logger.warning("[%s] 多种子集成失败（主报告不受影响）: %s",
                                   state.pipeline_id, _ens_err)

            # ---- DONE ---- S1: validate the real deliverable before declaring success.
            # Hard-fails (raises → status=failed) on an empty/placeholder report or missing
            # forecast.json; records a degraded health block otherwise. Makes broken runs visible.
            self._enforce_pipeline_health(state)
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
                # XRUN-15: 已完成（progress=100）的阶段是完成的工作，取消只作用于未完成阶段，
                # 避免出现 status='cancelled' + progress=100 + '…完成' 的自相矛盾标签。
                if not (st.status == "completed" or (st.progress or 0) >= 100):
                    st.status = "cancelled"
                    st.error = str(e)
                st.finished_at = st.finished_at or _utcnow()
            PipelineManager.save(state)
            if state.task_id:
                try:
                    task_manager.fail_task(state.task_id, str(e))
                except Exception:
                    pass
        except ProviderOutageHalt as e:
            # DEFECT-1：提供方全面中断 → 复用既有的 status='failed' 可恢复检查点终态
            # （resume() 接受 failed/cancelled 并复用已完成阶段与研究断点），不发明新状态。
            self._halt_for_provider_outage(state, task_manager, e)
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
            # I-4-1: 停掉心跳看护线程（管线已到终态，不应再刷新 heartbeat_at）。
            if hb_stop is not None:
                hb_stop.set()
            # EXECPLAN2 I-5-1: 落盘本次管线的 LLM 计量（token/成本/延迟，按阶段/模型），便于复盘。
            try:
                tpath = os.path.join(PipelineManager._dir(state.pipeline_id), "run_telemetry.json")
                _tel_extra: dict[str, Any] = {
                    "pipeline_id": state.pipeline_id,
                    "status": state.status,
                    "report_id": state.report_id,
                }
                # XRUN-8: 折入报告自身的 telemetry.json rollup——复用报告时 by_stage.report 只有
                # 1 次 cached/0 token 的缓存命中，报告的真实成本在它自己的目录里。
                try:
                    if state.report_id:
                        _rt = _read_json(os.path.join(
                            ReportManager._get_report_folder(state.report_id), "telemetry.json"))
                        if isinstance(_rt, dict):
                            _tel_extra["report_telemetry"] = _rt
                except Exception:  # noqa: BLE001
                    pass
                # XRUN-8(2): RUN 阶段的 LLM 调用发生在 sim 子进程（contextvars 不跨进程），
                # 折入其自报的 llm_health.json 平台级计数，避免 run 阶段在 rollup 里显示为 0。
                try:
                    if state.simulation_id:
                        _lh = _read_json(os.path.join(
                            Config.OASIS_SIMULATION_DATA_DIR, state.simulation_id, "llm_health.json"))
                        if isinstance(_lh, dict):
                            _tel_extra["sim_llm_health"] = _lh
                except Exception:  # noqa: BLE001
                    pass
                # W9-3: 终版落盘走增量 flush 的同一路径——合并基底在 attempt 起点捕获
                # （_init_telemetry_flush），与运行中的多次 flush 不会重复累计 cumulative_total。
                # （旧的 LLMMeter.write_run_telemetry 每次调用都把盘上文件当「上一 attempt」
                # 合并，与增量 flush 组合会把本 attempt 的中间快照重复累进账里。）
                self._tel_path = self._tel_path or tpath
                self._flush_run_telemetry(state, final=True, extra=_tel_extra)
                state.artifacts = getattr(state, "artifacts", None) or {}
                if isinstance(state.artifacts, dict):
                    state.artifacts["run_telemetry"] = tpath
                    PipelineManager.save(state)
                # ITEM-18: 阶段级遥测（stage × 调用/tokens/成本/墙钟）。把 LLMMeter 的 per-stage 快照
                # 与编排器记录的每阶段墙钟合并，落 telemetry.json（区别于 run_telemetry.json 的原始计量
                # 转储），把紧凑摘要折入 state.options.llm_telemetry（经 GET /status 返回 options 暴露给
                # 前端），并在成功完成时把确定性「Run Telemetry」附录追加到最终报告。必须在 reset 前算——
                # 用独立 try/except 兜底，任何失败都不得跳过下方的 LLMMeter.reset。
                try:
                    from ..utils.atomic import write_json_atomic, write_text_atomic
                    from ..utils.telemetry import build_stage_telemetry, render_telemetry_appendix
                    # INFRA-7：RUN_SHAPE_PIN 开启时附上本 attempt 的 stage_reuse_v1 记录（每阶段 reused 标志）。
                    _stage_tel = build_stage_telemetry(
                        state.pipeline_id, _stage_walls(state),
                        stage_decisions=(
                            self._stage_reuse_this_attempt
                            if bool(getattr(Config, "RUN_SHAPE_PIN", True)) else None))
                    try:
                        _stpath = os.path.join(
                            PipelineManager._dir(state.pipeline_id), "telemetry.json")
                        write_json_atomic(_stpath, _stage_tel)
                        if isinstance(state.artifacts, dict):
                            state.artifacts["telemetry"] = _stpath
                    except Exception as _swe:  # noqa: BLE001 — 工件落盘失败不影响摘要/附录
                        logger.debug(f"[{state.pipeline_id}] 写入 telemetry.json 失败（忽略）: {_swe}")
                    # 只把紧凑摘要折入 options（避免状态文件因 per-model 明细膨胀）
                    state.options["llm_telemetry"] = {
                        "total": _stage_tel.get("total"),
                        "by_stage": _stage_tel.get("by_stage"),
                        "cost_estimated": _stage_tel.get("cost_estimated"),
                        "cost_basis": _stage_tel.get("cost_basis"),
                    }
                    PipelineManager.save(state)
                    # W9-6: 遥测默认不再进入客户交付物——「Run Telemetry」表写到报告目录的
                    # 独立 telemetry.md（$26.28 的内部成本表曾随 full_report.md 一并交付）。
                    # REPORT_TELEMETRY_APPENDIX=true 时额外保留旧的 full_report.md 附录行为
                    # （幂等：已含则跳过，resume/re-report 安全）。
                    if state.status == "completed" and state.report_id:
                        _appendix = render_telemetry_appendix(_stage_tel)
                        if _appendix:
                            _rdir = ReportManager._get_report_folder(state.report_id)
                            try:
                                write_text_atomic(
                                    os.path.join(_rdir, "telemetry.md"),
                                    _appendix.rstrip() + "\n")
                            except Exception as _tme:  # noqa: BLE001 — telemetry.md 纯观测
                                logger.debug(
                                    f"[{state.pipeline_id}] 写入 telemetry.md 失败（忽略）: {_tme}")
                            if getattr(Config, "REPORT_TELEMETRY_APPENDIX", False):
                                _rpath = os.path.join(_rdir, "full_report.md")
                                _existing = _read_text(_rpath)
                                if _existing and "## Run Telemetry" not in _existing:
                                    write_text_atomic(
                                        _rpath, _existing.rstrip() + "\n\n" + _appendix.rstrip() + "\n")
                except Exception as _ste:  # noqa: BLE001 — 阶段遥测为观测增益，失败不影响管线终态
                    logger.debug(f"[{state.pipeline_id}] 阶段级遥测处理失败（忽略）: {_ste}")
            except Exception as _te:
                logger.debug(f"[{state.pipeline_id}] 写入 run_telemetry 失败（忽略）: {_te}")
            # INFRA-9：reset 是本 run 在 LLMMeter 与活跃 run 注册表里的权威终局，放在遥测 try 之外
            # （仍在其后：上面的落盘/阶段遥测要先读计量）。此前它在 try 内，终版落盘任一步抛错就被
            # 跳过——该 run 的计量与活跃登记滞留到进程结束，此后每条单独运行的管线都面对 2 个「活跃」
            # run，单活跃 run 回退归属失效。
            LLMMeter.reset(state.pipeline_id)
            # EVAL-15: 分阶段记分卡侧车。放在遥测 try 之外（与之平级）——遥测块任何一步抛错都
            # 不得让终态管线缺记分卡、或让上一 attempt 的摘要冒充本次结果。记分卡不读 LLMMeter，
            # 位于 reset 之后无影响；方法自身兜住一切异常。
            self._write_stage_scorecard_sidecar(state)
            # DEFECT-1：本 attempt 的中断熔断器随线程终结注销（下一 attempt 重新注册，
            # 计数不跨 attempt 遗留；注册表清空后探针对全进程完全透传）。
            _clear_outage_breaker(state.pipeline_id)
            # 线程结束即从注册表移除，避免 _threads 无界增长，并让 reconcile_orphans 的
            # "pid in _threads" 判定准确反映当前在飞的线程。
            cls._threads.pop(state.pipeline_id, None)
            cls._cancel_events.pop(state.pipeline_id, None)
