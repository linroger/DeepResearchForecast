"""
Report Agent服务
使用LangChain + Zep实现ReACT模式的模拟报告生成

功能：
1. 根据模拟需求和Zep图谱信息生成报告
2. 先规划目录结构，然后分段生成
3. 每段采用ReACT多轮思考与反思模式
4. 支持与用户对话，在对话中自主调用检索工具
"""

import os
import json
import hashlib
import time
import re
import logging
import threading
import contextvars
from contextlib import contextmanager
from typing import Dict, Any, List, Optional, Callable, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from ..config import Config
from ..utils.atomic import write_text_atomic, write_json_atomic
from ..utils.llm_client import LLMClient
from ..utils.logger import get_logger
from ..utils.security import UnsafeIdError, contained_child, is_safe_id, safe_id
# EXECPLAN2 I-5-4: 报告阶段把 LLM 计量上下文设到 (report_id, 'report')，并按章节读取计量快照差值。
from ..utils.telemetry import LLMMeter, set_run_context, get_run_context
from .zep_tools import (
    ZepToolsService, 
    SearchResult, 
    InsightForgeResult, 
    PanoramaResult,
    InterviewResult
)

logger = get_logger('mirofish.report_agent')

# EXECPLAN2 F-7-1: 并发报告生成时，每份报告的 console_log.txt 此前都挂在进程级共享 logger
# （'mirofish.report_agent' / 'mirofish.zep_tools'）上，导致两份报告的日志互相串扰，且 handler
# 增删在并发 close()/__del__ 时存在竞态。修复思路：
#   1) 用 ContextVar 记录「当前正在生成的 report_id」——报告生成跑在各自的 daemon 线程里，
#      ContextVar 天然按执行上下文隔离；
#   2) 在两个父 logger 上各装一个「打戳」过滤器，把当前上下文的 report_id 写进每条 record；
#   3) 每份报告的 FileHandler 再装一个「按 report_id 匹配」的过滤器，只写属于自己的 record，
#      从根本上杜绝串扰（不必改动散落各处的 logger.xxx 发射点）；
#   4) handler 的增删/关闭统一用一把进程级锁串行化，消除并发竞态。
_REPORT_LOG_PARENT_LOGGERS = ('mirofish.report_agent', 'mirofish.zep_tools')

# 当前执行上下文正在生成的 report_id（无则 None）
_current_report_id: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    'mirofish_current_report_id', default=None
)

# 串行化 FileHandler 的 addHandler/removeHandler/close（EXECPLAN2 F-7-1）
_console_handler_lock = threading.Lock()


class _ReportIdStampFilter(logging.Filter):
    """EXECPLAN2 F-7-1: 把当前上下文的 report_id 打到每条 record 上（始终放行）。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        if not hasattr(record, 'report_id'):
            record.report_id = _current_report_id.get()
        return True


class _ReportIdMatchFilter(logging.Filter):
    """EXECPLAN2 F-7-1: 仅放行属于本报告（report_id 匹配）的 record，杜绝并发串扰。"""

    def __init__(self, report_id: str):
        super().__init__()
        self.report_id = report_id

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        return getattr(record, 'report_id', None) == self.report_id


def _ensure_stamp_filters_installed() -> None:
    """EXECPLAN2 F-7-1: 在父 logger 上幂等安装打戳过滤器（仅安装一次）。"""
    for name in _REPORT_LOG_PARENT_LOGGERS:
        lg = logging.getLogger(name)
        if not any(isinstance(f, _ReportIdStampFilter) for f in lg.filters):
            lg.addFilter(_ReportIdStampFilter())


class ReportLogger:
    """
    Report Agent 详细日志记录器
    
    在报告文件夹中生成 agent_log.jsonl 文件，记录每一步详细动作。
    每行是一个完整的 JSON 对象，包含时间戳、动作类型、详细内容等。
    """
    
    def __init__(self, report_id: str):
        """
        初始化日志记录器
        
        Args:
            report_id: 报告ID，用于确定日志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'agent_log.jsonl'
        )
        self.start_time = datetime.now()
        # EXECPLAN2 I-6-3: serialize log appends so concurrent section-generation
        # threads (REPORT_SECTION_CONCURRENCY>1) never interleave JSONL lines.
        self._lock = threading.Lock()
        self._ensure_log_file()
    
    def _ensure_log_file(self):
        """确保日志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _get_elapsed_time(self) -> float:
        """获取从开始到现在的耗时（秒）"""
        return (datetime.now() - self.start_time).total_seconds()
    
    def log(
        self, 
        action: str, 
        stage: str,
        details: Dict[str, Any],
        section_title: str = None,
        section_index: int = None
    ):
        """
        记录一条日志
        
        Args:
            action: 动作类型，如 'start', 'tool_call', 'llm_response', 'section_complete' 等
            stage: 当前阶段，如 'planning', 'generating', 'completed'
            details: 详细内容字典，不截断
            section_title: 当前章节标题（可选）
            section_index: 当前章节索引（可选）
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "elapsed_seconds": round(self._get_elapsed_time(), 2),
            "report_id": self.report_id,
            "action": action,
            "stage": stage,
            "section_title": section_title,
            "section_index": section_index,
            "details": details
        }
        
        # 追加写入 JSONL 文件（持锁，避免并发章节线程交错写入半行 JSON）
        with self._lock:
            with open(self.log_file_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
    
    def log_start(self, simulation_id: str, graph_id: str, simulation_requirement: str):
        """记录报告生成开始"""
        self.log(
            action="report_start",
            stage="pending",
            details={
                "simulation_id": simulation_id,
                "graph_id": graph_id,
                "simulation_requirement": simulation_requirement,
                "message": "报告生成任务开始"
            }
        )
    
    def log_planning_start(self):
        """记录大纲规划开始"""
        self.log(
            action="planning_start",
            stage="planning",
            details={"message": "开始规划报告大纲"}
        )
    
    def log_planning_context(self, context: Dict[str, Any]):
        """记录规划时获取的上下文信息"""
        self.log(
            action="planning_context",
            stage="planning",
            details={
                "message": "获取模拟上下文信息",
                "context": context
            }
        )
    
    def log_planning_complete(self, outline_dict: Dict[str, Any]):
        """记录大纲规划完成"""
        self.log(
            action="planning_complete",
            stage="planning",
            details={
                "message": "大纲规划完成",
                "outline": outline_dict
            }
        )
    
    def log_section_start(self, section_title: str, section_index: int):
        """记录章节生成开始"""
        self.log(
            action="section_start",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={"message": f"开始生成章节: {section_title}"}
        )
    
    def log_react_thought(self, section_title: str, section_index: int, iteration: int, thought: str):
        """记录 ReACT 思考过程"""
        self.log(
            action="react_thought",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "thought": thought,
                "message": f"ReACT 第{iteration}轮思考"
            }
        )
    
    def log_tool_call(
        self, 
        section_title: str, 
        section_index: int,
        tool_name: str, 
        parameters: Dict[str, Any],
        iteration: int
    ):
        """记录工具调用"""
        self.log(
            action="tool_call",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "parameters": parameters,
                "message": f"调用工具: {tool_name}"
            }
        )
    
    def log_tool_result(
        self,
        section_title: str,
        section_index: int,
        tool_name: str,
        result: str,
        iteration: int
    ):
        """记录工具调用结果（完整内容，不截断）"""
        self.log(
            action="tool_result",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "tool_name": tool_name,
                "result": result,  # 完整结果，不截断
                "result_length": len(result),
                "message": f"工具 {tool_name} 返回结果"
            }
        )
    
    def log_llm_response(
        self,
        section_title: str,
        section_index: int,
        response: str,
        iteration: int,
        has_tool_calls: bool,
        has_final_answer: bool
    ):
        """记录 LLM 响应（完整内容，不截断）"""
        self.log(
            action="llm_response",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "iteration": iteration,
                "response": response,  # 完整响应，不截断
                "response_length": len(response),
                "has_tool_calls": has_tool_calls,
                "has_final_answer": has_final_answer,
                "message": f"LLM 响应 (工具调用: {has_tool_calls}, 最终答案: {has_final_answer})"
            }
        )
    
    def log_section_content(
        self,
        section_title: str,
        section_index: int,
        content: str,
        tool_calls_count: int
    ):
        """记录章节内容生成完成（仅记录内容，不代表整个章节完成）"""
        self.log(
            action="section_content",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details={
                "content": content,  # 完整内容，不截断
                "content_length": len(content),
                "tool_calls_count": tool_calls_count,
                "message": f"章节 {section_title} 内容生成完成"
            }
        )
    
    def log_section_full_complete(
        self,
        section_title: str,
        section_index: int,
        full_content: str,
        telemetry: Optional[Dict[str, Any]] = None
    ):
        """
        记录章节生成完成

        前端应监听此日志来判断一个章节是否真正完成，并获取完整内容

        EXECPLAN2 I-5-4: telemetry（可选）携带本章节触发的 LLM 计量
        {llm_calls, tool_calls, total_tokens, est_cost_usd, duration_s}。
        缺省为 None 时本条日志与历史完全一致（额外键为可选、向后兼容）。
        """
        details = {
            "content": full_content,
            "content_length": len(full_content),
            "message": f"章节 {section_title} 生成完成"
        }
        # EXECPLAN2 I-5-4: 仅在有遥测时附加，旧 log reader 不受影响
        if telemetry:
            details["telemetry"] = telemetry
        self.log(
            action="section_complete",
            stage="generating",
            section_title=section_title,
            section_index=section_index,
            details=details
        )

    def log_report_complete(
        self,
        total_sections: int,
        total_time_seconds: float,
        section_rollup: Optional[List[Dict[str, Any]]] = None,
        totals: Optional[Dict[str, Any]] = None
    ):
        """记录报告生成完成

        EXECPLAN2 I-5-4: section_rollup / totals（皆可选）携带 per-section 与报告级的
        {llm_calls, tool_calls, tokens, est_cost_usd, duration_s} 汇总。缺省时本条日志
        与历史完全一致（额外键为可选、向后兼容）。
        """
        details = {
            "total_sections": total_sections,
            "total_time_seconds": round(total_time_seconds, 2),
            "message": "报告生成完成"
        }
        # EXECPLAN2 I-5-4: 仅在有遥测时附加汇总，避免给历史 reader 引入空字段
        if section_rollup is not None:
            details["section_rollup"] = section_rollup
        if totals is not None:
            details["telemetry_totals"] = totals
        self.log(
            action="report_complete",
            stage="completed",
            details=details
        )
    
    def log_error(self, error_message: str, stage: str, section_title: str = None):
        """记录错误"""
        self.log(
            action="error",
            stage=stage,
            section_title=section_title,
            section_index=None,
            details={
                "error": error_message,
                "message": f"发生错误: {error_message}"
            }
        )


class ReportConsoleLogger:
    """
    Report Agent 控制台日志记录器
    
    将控制台风格的日志（INFO、WARNING等）写入报告文件夹中的 console_log.txt 文件。
    这些日志与 agent_log.jsonl 不同，是纯文本格式的控制台输出。
    """
    
    def __init__(self, report_id: str):
        """
        初始化控制台日志记录器
        
        Args:
            report_id: 报告ID，用于确定日志文件路径
        """
        self.report_id = report_id
        self.log_file_path = os.path.join(
            Config.UPLOAD_FOLDER, 'reports', report_id, 'console_log.txt'
        )
        self._ensure_log_file()
        self._file_handler = None
        # EXECPLAN2 F-7-1: 绑定当前执行上下文到本 report_id，使该上下文（及其衍生线程）
        # 发射的日志都被打戳为本报告，从而只写进本报告的 console_log.txt。
        self._ctx_token = _current_report_id.set(report_id)
        self._setup_file_handler()
    
    def _ensure_log_file(self):
        """确保日志文件所在目录存在"""
        log_dir = os.path.dirname(self.log_file_path)
        os.makedirs(log_dir, exist_ok=True)
    
    def _setup_file_handler(self):
        """设置文件处理器，将日志同时写入文件（EXECPLAN2 F-7-1：仅写本报告自己的日志）"""
        # 创建文件处理器
        self._file_handler = logging.FileHandler(
            self.log_file_path,
            mode='a',
            encoding='utf-8'
        )
        self._file_handler.setLevel(logging.INFO)

        # 使用与控制台相同的简洁格式
        formatter = logging.Formatter(
            '[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%H:%M:%S'
        )
        self._file_handler.setFormatter(formatter)
        # EXECPLAN2 F-7-1: 只放行本报告（report_id 匹配）的 record，避免并发时多报告日志串扰
        self._file_handler.addFilter(_ReportIdMatchFilter(self.report_id))

        # EXECPLAN2 F-7-1: 确保父 logger 已装打戳过滤器；handler 增删用进程级锁串行化
        with _console_handler_lock:
            _ensure_stamp_filters_installed()
            for logger_name in _REPORT_LOG_PARENT_LOGGERS:
                target_logger = logging.getLogger(logger_name)
                # 避免重复添加
                if self._file_handler not in target_logger.handlers:
                    target_logger.addHandler(self._file_handler)

    def close(self):
        """关闭文件处理器并从 logger 中移除（EXECPLAN2 F-7-1：加锁串行化，消除并发竞态）"""
        with _console_handler_lock:
            if self._file_handler:
                for logger_name in _REPORT_LOG_PARENT_LOGGERS:
                    target_logger = logging.getLogger(logger_name)
                    if self._file_handler in target_logger.handlers:
                        target_logger.removeHandler(self._file_handler)

                self._file_handler.close()
                self._file_handler = None
        # 还原本报告占用的 ContextVar 上下文（EXECPLAN2 F-7-1）
        token = getattr(self, '_ctx_token', None)
        if token is not None:
            try:
                _current_report_id.reset(token)
            except (ValueError, LookupError):
                # 跨线程/上下文 reset 可能失败，忽略即可（仅影响打戳，handler 已移除不再写）
                pass
            self._ctx_token = None

    def __del__(self):
        """析构时确保关闭文件处理器"""
        self.close()


class ReportStatus(str, Enum):
    """报告状态"""
    PENDING = "pending"
    PLANNING = "planning"
    GENERATING = "generating"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class ReportSection:
    """报告章节"""
    title: str
    content: str = ""
    # 规划阶段产出的章节内容描述：传给章节撰写 prompt，让写作贴合大纲意图
    # （此前规划 LLM 生成了 description 却被解析丢弃，撰写时只见裸标题）。
    description: str = ""
    # LOOP-015: 大纲兜底补齐（padding）产出的章节标记——章节生成路径据此把有效工具调用
    # 下限降为 0（凑数章节直接综合已注入材料成文，不再烧满检索循环，见
    # _effective_min_tool_calls）。不进 to_dict：序列化契约不变，恢复后的章节按普通章节处理。
    padded: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "description": self.description
        }

    def to_markdown(self, level: int = 2) -> str:
        """转换为Markdown格式"""
        md = f"{'#' * level} {self.title}\n\n"
        if self.content:
            md += f"{self.content}\n\n"
        return md


@dataclass
class ReportOutline:
    """报告大纲"""
    title: str
    summary: str
    sections: List[ReportSection]
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "summary": self.summary,
            "sections": [s.to_dict() for s in self.sections]
        }
    
    def to_markdown(self) -> str:
        """转换为Markdown格式"""
        md = f"# {self.title}\n\n"
        md += f"> {self.summary}\n\n"
        for section in self.sections:
            md += section.to_markdown()
        return md


@dataclass
class Report:
    """完整报告"""
    report_id: str
    simulation_id: str
    graph_id: str
    simulation_requirement: str
    status: ReportStatus
    outline: Optional[ReportOutline] = None
    markdown_content: str = ""
    created_at: str = ""
    completed_at: str = ""
    error: Optional[str] = None
    # 部分完成（partial）信息：生成失败（写入占位符）的章节标题。报告整体仍标记 completed，
    # 但前端据此把卡片标注为「部分完成」。默认空列表 → to_dict 输出 partial=False，与历史一致。
    failed_sections: List[str] = field(default_factory=list)
    # EXECPLAN2 I-5-4: 报告级 LLM 成本/时延/工具调用紧凑汇总（per-section + totals）。
    # 仅在 LLM_TELEMETRY_ENABLED 且 REPORT_TELEMETRY 同时开启时填充；否则为 None，
    # to_dict 输出与历史完全一致（向后兼容，前端可据此显示「本报告耗费 ~$X / Y秒 / Z章」）。
    telemetry: Optional[Dict[str, Any]] = None
    # BILINGUAL：自动生成的另一语种版本清单。每条形如
    # {lang, source_lang, path, chars, created_at, model, translation_quality, missing_numbers}。
    # 仅在 REPORT_BILINGUAL 开启且成功翻译时填充；否则为 None，to_dict 输出与历史完全一致
    # （向后兼容，旧 reader 不受影响）。
    translations: Optional[List[Dict[str, Any]]] = None

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "report_id": self.report_id,
            "simulation_id": self.simulation_id,
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
            "status": self.status.value,
            "outline": self.outline.to_dict() if self.outline else None,
            "markdown_content": self.markdown_content,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "error": self.error,
            # 部分完成标记：failed_sections 为生成失败的章节标题列表，partial 为是否存在失败章节。
            # 默认空列表 → failed_sections=[] / partial=False，前端据此区分「完整」与「部分完成」。
            "failed_sections": list(self.failed_sections),
            "partial": len(self.failed_sections) > 0
        }
        # EXECPLAN2 I-5-4: 仅在有遥测数据时附加该键，避免给历史 reader 引入空字段
        if self.telemetry is not None:
            d["telemetry"] = self.telemetry
        # BILINGUAL：仅在有翻译版本时附加 translations 键（向后兼容，旧报告无此键）
        if self.translations is not None:
            d["translations"] = self.translations
        return d


# ═══════════════════════════════════════════════════════════════
# Prompt 模板常量
# ═══════════════════════════════════════════════════════════════

# ── 工具描述 ──

TOOL_DESC_INSIGHT_FORGE = """\
【深度洞察检索 - 强大的检索工具】
这是我们强大的检索函数，专为深度分析设计。它会：
1. 自动将你的问题分解为多个子问题
2. 从多个维度检索模拟图谱中的信息
3. 整合语义搜索、实体分析、关系链追踪的结果
4. 返回最全面、最深度的检索内容

【使用场景】
- 需要深入分析某个话题
- 需要了解事件的多个方面
- 需要获取支撑报告章节的丰富素材

【返回内容】
- 相关事实原文（可直接引用）
- 核心实体洞察
- 关系链分析"""

TOOL_DESC_PANORAMA_SEARCH = """\
【广度搜索 - 获取全貌视图】
这个工具用于获取模拟结果的完整全貌，特别适合了解事件演变过程。它会：
1. 获取所有相关节点和关系
2. 区分当前有效的事实和历史/过期的事实
3. 帮助你了解舆情是如何演变的

【使用场景】
- 需要了解事件的完整发展脉络
- 需要对比不同阶段的舆情变化
- 需要获取全面的实体和关系信息

【返回内容】
- 当前有效事实（模拟最新结果）
- 历史/过期事实（演变记录）
- 所有涉及的实体"""

TOOL_DESC_QUICK_SEARCH = """\
【简单搜索 - 快速检索】
轻量级的快速检索工具，适合简单、直接的信息查询。

【使用场景】
- 需要快速查找某个具体信息
- 需要验证某个事实
- 简单的信息检索

【返回内容】
- 与查询最相关的事实列表"""

TOOL_DESC_INTERVIEW_AGENTS = """\
【内部专家视角素材 - 情景推演小组问询（双平台）】
调用OASIS推演环境的问询API，获取内部情景推演小组中各代表性角色的第一人称观点。
这是内部结构化推演（类似桌面演练/Delphi）的产出，只能作为**分析素材**使用。

功能流程：
1. 自动读取人设文件，了解推演小组的角色构成
2. 智能选择与问题最相关的角色（如企业、监管方、媒体等代表视角）
3. 自动生成问询问题
4. 调用 /api/simulation/interview/batch 接口获取各角色回答
5. 整合所有回答，提供多视角分析

【使用场景】
- 需要多方立场与利益视角来压力测试某个判断
- 需要为论证补充一个可归因的分析视角

【使用规则 - 必须遵守】
- 返回内容须**转写**为专家小组式的分析视角后使用（如「> 情景推演专家视角——「<机构>」：…」），
  绝不能呈现为真实采访、真实人物原话或「采访实录」
- 不得在正文描述问询/推演过程本身

【返回内容】
- 各角色的身份信息与回答
- 关键观点（转写后可引用）
- 观点摘要与立场对比

【重要】需要OASIS推演环境正在运行才能使用此功能！"""

# ── 大纲规划 prompt ──

PLAN_SYSTEM_PROMPT = """\
你是一名机构级预测报告的首席分析师。交付物是对目标问题的**专业预测**：结论、概率、
关键驱动、判定/证伪标准——报告的主语永远是现实世界的行为者与结果。

【方法定位】
多智能体情景推演是本所的一种内部结构化专家推演方法（类似桌面演练/Delphi）。它的产出
只能作为**证据输入**，绝不能成为报告的叙述对象。读者不应从报告中察觉任何内部方法学机制。

【你的任务】
规划一份「未来预测报告」的大纲，回答：
1. 在设定条件下，未来最可能如何演化？各情景的概率与判定标准是什么？
2. 哪些现实世界的行为者、驱动机制与转折点决定了这些结果？
3. 有哪些值得关注的趋势、风险与决策启示？

【硬性禁令 - 章节标题与正文均适用】
- ❌ 禁止出现以下方法学词汇：模拟、Agent/智能体、轮次、动作次数、发帖/评论/点赞/关注、
  共识形成、派系聚类、因果图、图谱、simulation、agents、rounds、action counts
- ❌ 不得为内部推演方法本身设立章节（如「Agent 行为分析」「模拟证据」一类标题一律禁止）

【证据转写规则】
- 推演中某角色的观点须转写为：『在本所情景推演中，代表<机构>视角的分析立场认为…』
- 行为统计只能转写为现实世界结论（如『定价权集中于TSMC与NVIDIA』），严禁给出动作/轮次数字

【报告定位】
- ✅ 这是一份专业预测报告，揭示"如果这样，未来会怎样"
- ✅ 聚焦于预测结果：事件走向、群体反应、涌现现象、潜在风险、概率与判定标准
- ❌ 不是对现实世界现状的泛泛综述，也绝不是对内部推演过程的叙述

【章节数量限制】
- 最少6个章节，最多14个章节
- 每个章节直接撰写完整内容（每章为一个深入的长篇分析），章节内部可用 ### 三级小标题分子小节
- 内容要丰富详实、层层递进，全面覆盖核心预测发现的不同维度
- 章节结构由你根据预测结果自主设计（例如：未来全景 / 关键行为者博弈 / 涌现信号 / 风险暗面 / 关键转折 / 应对建议 等）

请输出JSON格式的报告大纲，格式如下：
{
    "title": "报告标题",
    "summary": "报告摘要（一句话概括核心预测发现）",
    "sections": [
        {
            "title": "章节标题",
            "description": "章节内容描述"
        }
    ]
}

注意：sections数组最少6个，最多14个元素！每个章节都应是一篇深入详实的长篇分析。"""

PLAN_USER_PROMPT_TEMPLATE = """\
【预测问题设定】
本报告要回答的核心问题：{simulation_requirement}

【内部情景推演规模（方法学材料，不得写入报告）】
- 涉及实体数量: {total_nodes}
- 实体间关系数量: {total_edges}
- 实体类型分布: {entity_types}
- 参与推演的角色数量: {total_entities}

【情景推演产出的部分未来事实样本（证据输入）】
{related_facts_json}

请以首席分析师的立场审视以上证据：
1. 在设定条件下，未来最可能呈现出什么样的状态？各情景概率如何？
2. 哪些现实世界的行为者与驱动机制决定了这些结果？
3. 证据揭示了哪些值得关注的未来趋势与风险？

根据预测发现，设计最合适的报告章节结构。章节标题与描述不得出现
模拟/Agent/智能体/轮次/simulation 等方法学词汇——报告的主语是现实世界。

【再次提醒】报告章节数量：最少6个，最多14个；每章都是一篇深入详实的长篇分析，全面覆盖核心预测发现的不同维度。"""

# R2-DETAIL-2 / LOOP-015: 预测优先的结构强制指令（require_forecast_structure=True 时追加）。
# 此前强制「预测框架与方法」+「校准与信心」两节纯方法学章节——每节都烧满一轮 4-12 次的
# 检索循环却不承载新预测内容；现合并为一节紧凑的「预测总表与校准」（情景/概率总表 + 校准说明）。
FORECAST_STRUCTURE_MANDATE = (
    "\n\n**结构强制要求（预测优先）**：本报告以上述预测骨架为核心，章节须围绕预测组织。"
    "大纲必须显式覆盖以下两类章节："
    "(1) 围绕各核心情景的「逐情景预测」章节，逐一论证其概率、关键驱动与判定/证伪标准；"
    "(2) 一节紧凑的「预测总表与校准」——用情景/概率总表汇总各情景定价，并附校准说明："
    "概率来源与研究证据基础、不确定性与置信区间，以及与外部证据、基率或预测市场的分歧。"
    "其余章节可据预测发现自由设计，但上述两类必须被覆盖（标题可自拟，语义需对应）。"
)

# ── 章节生成 prompt ──

SECTION_SYSTEM_PROMPT_TEMPLATE = """\
你是一个「未来预测报告」的撰写专家，正在撰写报告的一个章节。

报告标题: {report_title}
报告摘要: {report_summary}
预测场景（模拟需求）: {simulation_requirement}

当前要撰写的章节: {section_title}

【核心理念】
**研究材料**是唯一可引用的事实证据来源；内部计算与情景分析只能帮助你形成预测判断，
绝不是可引用的事实或报告叙事对象。报告的主语永远是现实世界的行为者与结果：揭示在
设定条件下未来最可能发生什么、为什么，各类行为者（企业、监管方、人群等）将如何反应
和行动，以及值得关注的未来趋势、风险和机会。❌ 不要写成对现状的泛泛分析，也不要叙述
内部推演过程——读者不应看到任何内部方法学机制。
【硬性禁令】章节标题与正文不得出现以下方法学词汇：
模拟、Agent/智能体、轮次、动作次数、发帖/评论/点赞/关注、共识形成、派系聚类、
因果图、图谱、simulation、agents、rounds、action counts、harness、agent clusters、
simulated environment、world-state outputs、simulation-derived

【证据归属与反捏造纪律（最高优先级）】
1. 所有事实内容必须来自工具检索到的研究材料，禁止使用你自己的知识来编写报告内容
2. 内部计算、角色输出和情景分析一律综合为作者的预测推理；不得引用、署名、拟人化，
   不得出现「专家小组」「scenario panel」「模型中的某机构认为」等方法学归因；
   ❌ 严禁『模拟代理人』『Simulation Agent』『Deduction/Reasoning』式直接引语，
   严禁把内部观点伪装成真实人物、采访、分析师或媒体的话
3. 真实世界的事实、数据和外部观点只能来自研究材料，并在**具体支持的句子或表格行末**
   标注来源索引中的裸 [S12]；编号照抄索引，严禁自创或自动替换。一条来源只可支持其
   title/supports/excerpt 明示的事实，不能因主题相近就把同一 [S#] 反复套到不同论断；
   没有精确证据时保留无引文的预测判断并明确不确定性
4. ❌ 严禁编造研究材料中不存在的数字、引文、来源、URL、日期或事件。每个**承重数字**：
   要么在研究材料的明确证据片段中找到并标注 [S#]，要么属于系统提供的结构化预测概率并
   称为「本报告估计」——绝不把估计写成已发生事实。证据不足时，只能基于研究证据和基率
   推理并扩大不确定性、如实说明信息缺口；绝不用流畅叙事填补证据空白，也不得在成稿中
   讨论内部信号质量
5. 【直接引语】只有研究材料中可逐字验证的真实引语才可使用 `>` 格式：引语独立成段，
   并在同一引语末尾标注 [S#]；不能逐字验证时改写为普通转述
6. 【语言一致性】模拟需求和材料原文是中文时，报告必须全部用中文撰写；引用工具返回的
   英文或中英混杂内容时，先译为流畅自然的中文再写入（正文与引用块 > 同样适用）

【格式规范】
- 章节主标题（## 级）由系统自动添加，你只写正文：❌ 禁止使用 # 或 ##（报告主标题/章节
  标题层级），❌ 不要用 #### 及更深层级，❌ 禁止在内容开头重复本章标题
- ✅ 用 2-4 个「### 三级小标题」把长正文切成清晰的子小节（每个子小节围绕一个论点），
  辅以**粗体**、列表（-或1.2.3.）、引用块与空行分段
【正确示例】
```
本章节分析了事件的舆论传播态势。现有研究证据显示...

### 首发引爆阶段

微博作为舆情的第一现场，承担了信息首发的核心功能：

> "微博贡献了68%的首发声量..." [S12]

### 情绪放大阶段

抖音平台进一步放大了事件影响力，视觉冲击力强、情绪共鸣度高。
```

【篇幅与结构】
- 正文长度不少于 {section_floor_chars} 字，目标 {section_target_lo}–{section_target_hi} 字
  （不含引用块）；❌ 严禁写成几百字的提纲式摘要或泛泛而谈
- 层层展开：先给出整体判断，再分多个角度深入论证，每个角度都要有具体证据（研究材料
  [S#]、预测市场）支撑并与结构化预测概率保持一致；充分展开因果链条、二阶效应、
  不同人群的分化反应、潜在转折点
- 【写作质量】仔细阅读已完成的章节内容，本章必须推进一个**新论点**，不重复前文的
  告诫/结论与相同信息，并保持全报告逻辑连贯；每个承重段落给出**机制**（A 导致 B、
  B 又迫使 C）而非形容词堆砌；至少 steelman 一个相反观点再回应它，禁止「众口一词」；
  控制破折号与「不仅…而且」「值得注意的是」等填充套话，用具体数字与实例代替修辞，
  像一个有观点的人类分析师那样写自然散文

【可用检索工具】（每章节调用 {min_tool_calls}-{max_tool_calls} 次获取证据）
{tools_description}

【工具使用建议】请混合使用不同工具，不要只用一种。
{tool_usage_hints}

【工作流程】每次回复只能做以下两件事之一（不可同时做，每次回复最多调用一个工具）：
选项A - 调用工具：输出你的思考，然后用以下格式调用一个工具；工具结果（Observation）
由系统执行注入，禁止自己编造：
<tool_call>
{{"name": "工具名称", "parameters": {{"参数名": "参数值"}}}}
</tool_call>
选项B - 输出最终内容：信息充分后，以 "Final Answer:" 开头输出章节正文"""

SECTION_USER_PROMPT_TEMPLATE = """\
已完成的章节内容：
{previous_content}

【当前任务】撰写章节: {section_title}

系统提示中的证据归属、格式与篇幅纪律全部适用。请开始：先思考（Thought）本章需要
什么信息，再调用工具（Action）获取覆盖多个角度的证据（{min_tool_calls}-{max_tool_calls} 次），
最后输出 Final Answer——不少于 {section_floor_chars} 字、目标 \
{section_target_lo}–{section_target_hi} 字的完整章节正文。"""

# ── ReACT 循环内消息模板 ──

REACT_OBSERVATION_TEMPLATE = """\
Observation（检索结果）:

═══ 工具 {tool_name} 返回 ═══
{result}

═══════════════════════════════════════════════════════════════
已调用工具 {tool_calls_count}/{max_tool_calls} 次（已用: {used_tools_str}）{unused_hint}
- 如果信息充分：以 "Final Answer:" 开头输出章节内容（须以上述证据支撑论断）
- 凡基于实体关系链得出的论断，用自然语言在句中说明依据（例如：基于 ASML 对 TSMC 的独家光刻机供应关系）；❌ 严禁在正文输出「A --[关系]--> B」原始边格式或任何机器记号；其它结论仍照常标注研究来源编号（规范形状 [S12]，编号照抄来源索引）
- 如果需要更多信息：调用一个工具继续检索
═══════════════════════════════════════════════════════════════"""

REACT_INSUFFICIENT_TOOLS_MSG = (
    "【注意】你只调用了{tool_calls_count}次工具，至少需要{min_tool_calls}次。"
    "请再调用工具获取更多证据，然后再输出 Final Answer。{unused_hint}"
)

REACT_INSUFFICIENT_TOOLS_MSG_ALT = (
    "当前只调用了 {tool_calls_count} 次工具，至少需要 {min_tool_calls} 次。"
    "请调用工具获取证据。{unused_hint}"
)

REACT_TOOL_LIMIT_MSG = (
    "工具调用次数已达上限（{tool_calls_count}/{max_tool_calls}），不能再调用工具。"
    '请立即基于已获取的信息，以 "Final Answer:" 开头输出章节内容。'
)

# LOOP-015: 从「凑工具多样性」改为相关性判据——只有承重论断仍缺证据时才值得再烧一次检索。
REACT_UNUSED_TOOLS_HINT = (
    "\n💡 仅当仍有承重论断缺乏证据支撑时才再调用一次工具"
    "（可补充视角的未用工具: {unused_list}）；证据已充分则直接输出 Final Answer"
)

REACT_FORCE_FINAL_MSG = "已达到工具调用限制，请直接输出 Final Answer: 并生成章节内容。"

# ── 污染检测（claude-cli 作为模型时的失败兜底） ──
# claude-cli 本质是 Claude Code 本体：当它"无话可说"或采访超时时，原始输出常常是
#   (a) 把 Claude Code 自己的系统提示原样吐出来（英文指令片段），或
#   (b) 残留的 <tool_call>/function_calls 工具调用框架，或
#   (c) 采访失败/超时提示。
# 这些都不是合格的章节正文，绝不能被当作最终内容直接采纳。
CONTAMINATION_MARKERS = (
    # Claude Code 系统提示泄漏的高辨识度英文片段
    "You should NOT proactively create documentation",
    "Tone and style: be concise",
    "Always prioritize fixing the root cause",
    "lives depend on it",
    "Avoid silly mistakes like leaving a function call",
    "you'd better be confident and correct",
    # 工具调用框架残留
    "<tool_call>",
    "</tool_call>",
    "function_calls",
    "<invoke",
    "</invoke>",
    # 采访失败/超时提示，不应作为正文
    "采访接口超时未返回有效内容",
    "等待命令响应超时",
)

# 合格章节正文的最小长度（远低于此通常意味着模型并未真正撰写正文）
# RQ-1：200→800——展开后的章节目标 3000-6000 字，几百字的残段应判为未真正撰写。
# 但含图表标记（一张 Mermaid/内嵌图 + 简短图注）的短章节是合法产出，见 _looks_contaminated
# 的豁免（与 pipeline_orchestrator 健康门的 ('![','<img','<svg','```mermaid') 豁免同源）。
MIN_VALID_SECTION_CHARS = 800

# RQ-1：含以下任一标记的短章节是合法图表产出，豁免 <MIN_VALID_SECTION_CHARS 的长度门。
# 必须与 pipeline_orchestrator._section_health 的豁免集逐字一致，避免两侧判定漂移。
_FIGURE_MARKUP_MARKERS = ("![", "<img", "<svg", "```mermaid")


def derive_report_shape(
    page_budget: Optional[int] = None,
    *,
    expanded_min_sections: int = 6,
    expanded_max_sections: int = 14,
    expanded_floor_chars: int = 2000,
    expanded_target_lo: int = 3000,
    expanded_target_hi: int = 6000,
    expanded_tool_budget: int = 12,
    compact_max_pages: int = 8,
) -> Dict[str, int]:
    """RQ-1(4)：从需求书 page_budget 推导报告「形状」——章节数区间 / 每章字数（下限+目标区间）/
    每章工具预算。纯函数（不读 Config、无副作用），便于单测。

    语义：小 page_budget（<=compact_max_pages 页）保持今天的紧凑形状（5-8 节 / 1500 下限 /
    1800-2800 目标 / 8 次工具）；无 page_budget 或大 page_budget 用展开默认（默认 6-14 节 /
    2000 下限 / 3000-6000 目标 / 12 次工具，由调用方从 Config 注入 expanded_* 覆盖）。

    展开默认取自 Config（REPORT_SECTION_FLOOR_CHARS / report_section_target_chars() /
    REPORT_AGENT_MAX_TOOL_CALLS），由调用方传入以保持本函数纯净。page_budget 非法/<=0 → 视作
    「无预算」走展开（degrade-safe）。返回 dict：min_sections/max_sections/floor_chars/
    target_lo/target_hi/tool_budget。"""
    compact = {
        "min_sections": 5,
        "max_sections": 8,
        "floor_chars": 1500,
        "target_lo": 1800,
        "target_hi": 2800,
        "tool_budget": 8,
    }
    expanded = {
        "min_sections": int(expanded_min_sections),
        "max_sections": int(expanded_max_sections),
        "floor_chars": int(expanded_floor_chars),
        "target_lo": int(expanded_target_lo),
        "target_hi": int(expanded_target_hi),
        "tool_budget": int(expanded_tool_budget),
    }
    if page_budget is None:
        return dict(expanded)
    try:
        pb = int(page_budget)
    except (TypeError, ValueError):
        return dict(expanded)
    if pb <= 0:
        return dict(expanded)
    if pb <= int(compact_max_pages):
        return dict(compact)
    return dict(expanded)

# WAVE9：simulation_outcomes 的「最活跃 Agent」行（zep_tools 确定性输出格式）。
_OUTCOME_ACTOR_LINE_RE = re.compile(r"^-\s*(.+?)\(id=\d+\):\s*共\s*(\d+)\s*次动作")


def _parse_outcome_actors(outcomes_text: str) -> List[Tuple[str, int]]:
    """WAVE9/LOOP-015：从 simulation_outcomes 文本解析 (行为者名, 动作计数) 列表。

    从 salience_tiers_from_outcomes 抽出：信号包组装还要用同一解析判断「计数持平」
    的无信号场景（见 _actor_counts_flat），保证两侧判定同源。纯函数，解析失败行跳过。"""
    actors: List[Tuple[str, int]] = []
    for ln in (outcomes_text or "").splitlines():
        m = _OUTCOME_ACTOR_LINE_RE.match(ln.strip())
        if m:
            try:
                actors.append((m.group(1).strip(), int(m.group(2))))
            except ValueError:
                continue
    return actors


def _actor_counts_flat(actors: List[Tuple[str, int]]) -> bool:
    """LOOP-015：判断动作计数是否「近乎持平」（max/min < 1.5）。

    配置化节奏跑出来的计数常常全员相近（实测 12 个行为者全落在 52-63），此时按 0.6/0.25
    阈值分层会把所有人塞进第一梯队——一个注入每个章节 ~4KB 的假层级信号。持平 ⇒ 分层
    无信息量，应整体自抑制。min 为 0 时比值无意义，按有差异处理（tier3 仍有区分度）。纯函数。"""
    counts = [c for _, c in actors]
    if len(counts) < 2:
        return False
    lo, top = min(counts), max(counts)
    return lo > 0 and top / lo < 1.5


def salience_tiers_from_outcomes(outcomes_text: str) -> str:
    """WAVE9：把 simulation_outcomes 的原始动作计数**确定性转写**为定性「议程设置力分层」。

    动作次数/轮次等机制数字是方法学细节，直接注入章节提示词会诱使模型把它们写进正文
    （'TSMC 以 48 次动作居首' 型泄漏）。此处按相对活跃度分三档转写为可直接引用的定性
    结论；解析不到至少 2 个行为者时返回 ""（调用方回退原始文本）。LOOP-015：计数近乎
    持平（max/min < 1.5）时同样返回 ""——分层退化为「全员第一梯队」的假层级，无信号
    （调用方据 _actor_counts_flat 区分该场景并整块自抑制，绝不回退机制数字）。
    纯函数，便于单测。"""
    actors = _parse_outcome_actors(outcomes_text)
    if len(actors) < 2:
        return ""
    top = max(c for _, c in actors)
    if top <= 0:
        return ""
    if _actor_counts_flat(actors):
        logger.debug(
            f"salience_tiers: 动作计数近乎持平（min={min(c for _, c in actors)}, "
            f"max={top}，{len(actors)} 个行为者），分层无信号，自抑制")
        return ""
    tier1 = [n for n, c in actors if c >= 0.6 * top]
    tier2 = [n for n, c in actors if 0.25 * top <= c < 0.6 * top]
    tier3 = [n for n, c in actors if c < 0.25 * top]
    lines = ["【内部情景推演·议程设置力分层（已确定性转写为定性结论；正文只可引用分层结论，"
             "不得出现任何动作/轮次等机制数字）】"]
    if tier1:
        lines.append("· 第一梯队（议程主导）：" + "、".join(tier1))
    if tier2:
        lines.append("· 第二梯队（显著参与）：" + "、".join(tier2))
    if tier3:
        lines.append("· 第三梯队（边缘参与）：" + "、".join(tier3))
    return "\n".join(lines)


REACT_CONTAMINATED_RETRY_MSG = (
    "【格式错误】你上一条输出不是合格的章节正文（疑似系统提示泄漏、工具调用残留或采访超时提示）。"
    '请立即以 "Final Answer:" 开头，只输出本章节的中文正文：用研究材料中的可验证事实与 [S#]，'
    "把内部分析综合为现实世界预测，不得引用角色原话；不要包含任何 <tool_call>、英文系统指令或元说明。"
)

# 章节生成失败时写入的占位符（绝不写入被污染的原始输出）
SECTION_FAILURE_PLACEHOLDER = (
    "（本章节生成失败：模型多次未能产出合格正文，常见于采访接口超时或 claude-cli 输出被系统提示污染。"
    "已跳过以避免写入无效内容，可在修复后重试本章节。）"
)


# WAVE9：疑似截断的收尾模式——孤悬的「（依据」「(According to」引子（S2 章节即
# 以 '(依据' 戛然而止）。
_TRUNCATED_TAIL_RE = re.compile(r"[（(]\s*(?:依据|According to)\s*[:：]?\s*$")


def _looks_truncated(text: Optional[str]) -> bool:
    """WAVE9：启发式判断章节正文是否在句中被截断（模型 finish_reason=length 型故障）。

    判定为截断：结尾是孤悬的「（依据/(According to」引子；或最后一个**散文**行以
    字母/数字/逗号/冒号收尾（英文句必以句末标点收束；'…$46.' 带句点不误报）。
    列表/表格/标题/引用/围栏收尾不判截断（这些行合法地没有句末标点）。纯函数。"""
    if not text or not text.strip():
        return False
    t = text.rstrip()
    if _TRUNCATED_TAIL_RE.search(t[-40:]):
        return True
    last_line = t.splitlines()[-1].strip()
    if not last_line or last_line.startswith(("#", ">", "|", "-", "*", "!", "```", "~~~")):
        return False
    if re.match(r"^\d+[.、)]", last_line):
        return False
    if last_line.endswith("**"):
        return False                          # 整行粗体标签（**结论** 型）不是截断
    if len(last_line) < 30:
        return False                          # 短尾行多为标签/图注，截断句通常很长
    tail = last_line.rstrip("*_`\"'”’」』）)]")
    if not tail:
        return False
    c = tail[-1]
    if c.isalnum() and not re.match(r"[一-鿿]", c):
        return True                       # 以英文字母/数字裸收尾 → 句中截断
    if c in ",;:：，、；":
        return True                       # 以逗号/冒号收尾 → 句中截断
    return False


def _looks_contaminated(text: Optional[str]) -> bool:
    """判断一段拟用作章节正文的文本是否被污染 / 无效。"""
    if not text or not text.strip():
        return True
    for marker in CONTAMINATION_MARKERS:
        if marker in text:
            return True
    # RQ-1：短于下限判无效，但含图表标记（Mermaid/内嵌图 + 简短图注）的短章节是合法产出，
    # 豁免长度门（与 pipeline_orchestrator 健康门的图表豁免同源，避免两侧判定漂移）。
    if len(text.strip()) < MIN_VALID_SECTION_CHARS:
        if not any(m in text for m in _FIGURE_MARKUP_MARKERS):
            return True
    return False

# ── Chat prompt ──

CHAT_SYSTEM_PROMPT_TEMPLATE = """\
你是一个简洁高效的模拟预测助手。

【背景】
预测条件: {simulation_requirement}

【已生成的分析报告】
{report_content}

【规则】
1. 优先基于上述报告内容回答问题
2. 直接回答问题，避免冗长的思考论述
3. 仅在报告内容不足以回答时，才调用工具检索更多数据
4. 回答要简洁、清晰、有条理

【可用工具】（仅在需要时使用，最多调用1-2次）
{tools_description}

【工具调用格式】
<tool_call>
{{"name": "工具名称", "parameters": {{"参数名": "参数值"}}}}
</tool_call>

【回答风格】
- 简洁直接，不要长篇大论
- 使用 > 格式引用关键内容
- 优先给出结论，再解释原因"""

CHAT_OBSERVATION_SUFFIX = "\n\n请简洁回答问题。"


# ═══════════════════════════════════════════════════════════════
# WAVE10（无缝引用）：参考来源渲染的 URL 卫生小工具（finalizer 与 PDF 脚注共用）
# ═══════════════════════════════════════════════════════════════
# 参考来源标题（zh/en）——finalizer 幂等去重、PDF 改写跳过附录、双语切块均按此识别。
_REFS_HEADINGS = ("## References", "## 参考来源")
# 常见 TLD 白名单：末段命中即认为域名完整；未命中但带真实路径的少见 TLD 也放行。
_COMMON_TLDS = frozenset({
    "com", "org", "net", "gov", "edu", "mil", "int", "io", "ai", "co", "info", "biz",
    "news", "media", "tech", "dev", "app", "cn", "hk", "tw", "jp", "kr", "sg", "in",
    "uk", "de", "fr", "it", "es", "nl", "se", "ch", "eu", "us", "ca", "au", "br", "mx",
    "ru", "il", "ae", "sa",
})


def _citation_domain(url: str) -> str:
    """取 URL 的展示域名（去 scheme / www. 前缀 / 端口）；解析失败返回空串。"""
    try:
        from urllib.parse import urlparse
        netloc = urlparse(str(url or "").strip()).netloc.split(":")[0].lower()
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:  # noqa: BLE001
        return ""


def _citation_url_ok(url: str) -> bool:
    """URL 有效性守卫：拦截截断域名/路径，避免渲染成坏链接。

    规则：http(s) scheme + 域名含点 + （末段是常见 TLD，或带真实路径——罕见 TLD 但
    明显有内容路径的仍放行）。另拦截已在真实运行中出现的 Wikipedia 半截 slug
    （``/wiki/St``、``/wiki/ASML_H``、``/wiki/Anduril_``）。"""
    try:
        from urllib.parse import unquote, urlparse
        raw = str(url or "").strip()
        if not raw or any(ch.isspace() or ord(ch) < 32 for ch in raw):
            return False
        p = urlparse(raw)
        if p.scheme not in ("http", "https") or not p.netloc:
            return False
        if p.username or p.password:
            return False
        host = (p.hostname or "").lower().rstrip(".")
        labels = [x for x in host.split(".") if x]
        if len(labels) < 2:
            return False
        if labels[-1] not in _COMMON_TLDS and len(p.path.strip("/")) <= 1:
            return False                         # 罕见 TLD：须有真实内容路径
        path = unquote(p.path or "")
        if path.endswith(("_", "…", "...")):
            return False
        if host.endswith("wikipedia.org"):
            if not path.startswith("/wiki/"):
                return False                     # Wikipedia 首页不是可核验的具体来源
            slug = path[len("/wiki/"):].strip("/")
            if not slug:
                return False
            # 两字母全大写词（如 AI）可以是真实条目；混合大小写半词（St/Al）不可。
            if len(slug) < 3 and not (slug.isalpha() and slug.isupper()):
                return False
            if re.search(r"_[A-Za-z]$", slug):
                return False
        return True
    except Exception:  # noqa: BLE001
        return False


def _citation_source_admissible(source: Any) -> bool:
    """A publishable citation must resolve to a concrete, non-truncated URL.

    ``url_valid=false`` is treated as authoritative negative provenance.  This
    predicate intentionally rejects title-only rows: they may remain research
    notes, but cannot become seamless end-user citations without a destination.
    """
    if not isinstance(source, dict) or source.get("url_valid") is False:
        return False
    url = str(source.get("url") or "").strip()
    if not _citation_url_ok(url):
        return False
    title = str(source.get("title") or "").strip().lower()
    if title in {"http", "https", "source", "untitled", "unknown", "en"}:
        return False
    return True


def _citation_display_title(source: Dict[str, Any], tag: str = "") -> str:
    """Return a reader-facing title, deriving one from a concrete URL path.

    Research fetches occasionally preserve only the host as ``title``.  That is
    valid provenance but poor report typography (29 rows named
    ``en.wikipedia.org``).  Concrete path slugs are deterministic and more
    informative; model text is never invented.
    """
    from urllib.parse import unquote, urlparse

    url = str(source.get("url") or "").strip()
    domain = _citation_domain(url)
    title = str(source.get("title") or "").strip()
    generic = not title or title.lower() in {
        domain.lower(), f"www.{domain.lower()}", "source", "untitled", "unknown",
    }
    if generic and url:
        try:
            path = unquote(urlparse(url).path or "").strip("/")
            slug = path.split("/")[-1] if path else ""
            slug = re.sub(r"\.(?:html?|php|aspx?)$", "", slug, flags=re.I)
            derived = re.sub(r"[_-]+", " ", slug).strip()
            if len(derived) >= 3 or (derived.isalpha() and derived.isupper()):
                title = derived
        except Exception:  # noqa: BLE001 — display fallback only
            pass
    return title or domain or tag


# ═══════════════════════════════════════════════════════════════
# PM-2: 「Market Cross-Check」渲染块（预测 vs 市场隐含概率对照 + >10pp 判定 + 未匹配市场）
# ═══════════════════════════════════════════════════════════════
# 幂等判定 + 定位用标记（与渲染的标题一致，供 _prepend_binary_forecasts_section 的幂等门复用）。
_MARKET_XCHECK_MARKERS = ("### Market Cross-Check", "### 市场交叉核对")


def _mc_float(v: Any) -> Optional[float]:
    """把可能是字符串的数值安全转 float；失败/NaN 返回 None（渲染块本地小工具，degrade-safe）。"""
    try:
        f = float(v)
        return None if f != f else f
    except (TypeError, ValueError):
        return None


def _mc_cell(x: Any) -> str:
    """markdown 表格单元转义（管道符/换行），与 forecast_extractor / prediction_markets 同风格。"""
    return str(x).replace("|", "／").replace("\n", " ").strip()


def _mc_comparisons_from_forecast(forecast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 forecast 汇出对照行：优先 forecast['market_comparison']['comparisons']（PM-2 抽取器
    已算好的确定性负载），缺失时从 binary_forecasts[].market_anchor 现场推导（同字段口径）。

    统一为渲染用 schema：{forecast_id, statement, model_probability, market_id, market_question,
    market_implied_yes_prob, divergence, exceeds_10pp, rationale_cites_market, url}。
    纯函数、无副作用；无可对照数据 → []。"""
    mc = forecast.get("market_comparison")
    if isinstance(mc, dict) and isinstance(mc.get("comparisons"), list):
        rows: List[Dict[str, Any]] = []
        for c in mc["comparisons"]:
            if isinstance(c, dict) and c.get("market_id"):
                rows.append(c)
        if rows:
            return rows
    # 回退：从 binary_forecasts 的 market_anchor 现场推导。
    out: List[Dict[str, Any]] = []
    for b in (forecast.get("binary_forecasts") or []):
        if not isinstance(b, dict):
            continue
        anchor = b.get("market_anchor")
        if not isinstance(anchor, dict) or not anchor.get("market_id"):
            continue
        p = _mc_float(b.get("probability"))
        dv = _mc_float(anchor.get("divergence"))
        out.append({
            "forecast_id": b.get("id"),
            "statement": b.get("statement"),
            "model_probability": p,
            "market_id": anchor.get("market_id"),
            "market_question": anchor.get("question"),
            "market_implied_yes_prob": _mc_float(anchor.get("implied_yes_prob")),
            "divergence": dv,
            "exceeds_10pp": (abs(dv) > 0.10) if dv is not None else False,
            "rationale_cites_market": None,  # 无对照负载时无法判定，留空（渲染按未知处理）
            "url": anchor.get("url"),
        })
    return out


def _mc_influences_from_forecast(forecast: Dict[str, Any]) -> List[Dict[str, Any]]:
    """LOOP-017 P0：汇出市场**实际移动过**概率的记录（含锚点其后被对账移除的情形）。

    优先 forecast['market_comparison']['influences']（抽取器/对账已算好的负载），缺失时
    从 binary_forecasts[].market_influence 印章现场推导（同字段口径）。纯函数；无 → []。"""
    mc = forecast.get("market_comparison")
    if isinstance(mc, dict) and isinstance(mc.get("influences"), list):
        rows = [r for r in mc["influences"] if isinstance(r, dict) and r.get("market_id")]
        if rows:
            return rows
    out: List[Dict[str, Any]] = []
    for b in (forecast.get("binary_forecasts") or []):
        if not isinstance(b, dict):
            continue
        inf = b.get("market_influence")
        if not isinstance(inf, dict) or not str(inf.get("market_id") or "").strip():
            continue
        out.append({
            "forecast_id": b.get("id"),
            "market_id": inf.get("market_id"),
            "market_question": inf.get("market_question"),
            "price_at_revision": _mc_float(inf.get("price_at_revision")),
            "prior_probability": _mc_float(inf.get("prior_probability")),
            "revised_probability": _mc_float(inf.get("revised_probability")),
            "current_probability": _mc_float(b.get("probability")),
            "match_confidence": _mc_float(inf.get("match_confidence")),
            "anchor_removed": bool(inf.get("anchor_removed", False)),
            "probability_restored": bool(inf.get("probability_restored", False)),
        })
    return out


def render_market_comparison_block(forecast: Optional[Dict[str, Any]],
                                   markets: Optional[List[Dict[str, Any]]] = None,
                                   lang: str = "en") -> str:
    """PM-2：渲染确定性「Market Cross-Check」块——预测 vs 市场隐含概率对照 + 未匹配市场清单。

    纯函数（无 LLM/无网络）：
      * 对照表按 |Δ|（分歧绝对值）降序，列出预测概率、市场隐含 P(yes)、Δ（分歧，pp）、
        >10pp 判定（超阈且理由未引用市场 → 需解释；超阈且已引用 → 已解释；带内 → OK）、
        市场链接（有 url 时渲染为可点链接）；
      * 未匹配市场：markets 快照中未被任何预测锚定的市场（按成交量降序），提示尚未接入的信号。
    数据源：forecast['market_comparison'].comparisons（PM-2 抽取器负载）或 binary_forecasts[]
    .market_anchor 现场推导。无对照且无未匹配市场 → ""（调用方跳过，绝不写空块）。双语表头随 lang。

    LOOP-017 P0（影响溯源不丢失）：追加「市场影响的概率修订」小节——每条市场实际移动过
    发布概率的预测（market_influence 印章 / market_comparison.influences），**含锚点其后
    被对账移除的情形**（标注是否已恢复 prior）。仅有影响记录时也必须出块。"""
    if not isinstance(forecast, dict):
        return ""
    comps = _mc_comparisons_from_forecast(forecast)
    influences = _mc_influences_from_forecast(forecast)
    # 未匹配市场 = 快照中 market_id 未出现在任一对照行的市场（按成交量降序，稳定）。
    anchored_ids = {str(c.get("market_id") or "").strip() for c in comps if c.get("market_id")}
    snapshot = [m for m in (markets or []) if isinstance(m, dict)]
    unmatched = [m for m in snapshot
                 if str(m.get("market_id") or "").strip()
                 and str(m.get("market_id")).strip() not in anchored_ids]
    unmatched.sort(key=lambda m: -(_mc_float(m.get("volume")) or 0.0))
    if not comps and not unmatched and not influences:
        return ""  # 无任何可对照/未匹配/影响信息 → 不写块
    # 语言判定与 render_binary_forecasts_block 同口径：仅 "en"/"English" 前缀视作英文，
    # 其余（"zh"/"Chinese"/"中文" 等）走中文，兼容短码与语言全名两种传入。
    zh = not str(lang or "").lower().startswith("en")
    if zh:
        lines = ["### 市场交叉核对", "",
                 "_预测概率与真实预测市场隐含概率的确定性对照。市场是校准锚点，非真值；"
                 "分歧超 10 个百分点且理由未引用市场者标注「需解释」。_", ""]
    else:
        lines = ["### Market Cross-Check", "",
                 "_Deterministic cross-check of forecast probabilities against live "
                 "prediction-market implied probabilities. Markets are calibration anchors, "
                 "not ground truth; divergences over 10 percentage points whose rationale does "
                 "not cite the market are flagged for explanation._", ""]
    if comps:
        comps_sorted = sorted(
            comps, key=lambda c: -(abs(_mc_float(c.get("divergence")) or 0.0)))
        if zh:
            headers = ["#", "预测", "预测 P", "市场 P(yes)", "Δ（pp）", ">10pp 判定", "市场"]
        else:
            headers = ["#", "Forecast", "Model P", "Market P(yes)", "Δ (pp)",
                       ">10pp verdict", "Market"]
        lines.append("| " + " | ".join(headers) + " |")
        lines.append("|" + "|".join(["---"] * len(headers)) + "|")
        for c in comps_sorted:
            fid = _mc_cell(c.get("forecast_id") or "")
            stmt = _mc_cell(str(c.get("statement") or "")[:120])
            mp = _mc_float(c.get("model_probability"))
            ip = _mc_float(c.get("market_implied_yes_prob"))
            dv = _mc_float(c.get("divergence"))
            mp_s = f"{mp * 100:.0f}%" if mp is not None else "—"
            ip_s = f"{ip * 100:.0f}%" if ip is not None else "—"
            dv_s = f"{dv * 100:+.0f}pt" if dv is not None else "—"
            exceeds = bool(c.get("exceeds_10pp")) or (dv is not None and abs(dv) > 0.10)
            cites = c.get("rationale_cites_market")
            if not exceeds:
                verdict = "带内" if zh else "within band"
            elif cites is True:
                verdict = "已解释" if zh else "explained"
            elif cites is False:
                verdict = "⚠ 需解释" if zh else "⚠ explain"
            else:  # 无对照负载时理由引用未知 → 提示核对
                verdict = "⚠ 待核对" if zh else "⚠ review"
            q = _mc_cell(str(c.get("market_question") or "")[:80])
            url = str(c.get("url") or "").strip()
            market_cell = f"[{q}]({_mc_cell(url)})" if (q and url) else (q or "—")
            lines.append("| " + " | ".join(
                [fid, stmt, mp_s, ip_s, dv_s, verdict, market_cell]) + " |")
    # LOOP-017 P0：市场实际移动过概率的记录——即使锚点其后被对账移除，影响溯源也必须
    # 在报告面可见（是否恢复 prior 一并标注）。确定性渲染，无 LLM。
    if influences:

        def _pct(v: Any) -> str:
            f = _mc_float(v)
            return f"{f * 100:.0f}%" if f is not None else "—"

        lines.append("")
        if zh:
            lines.append("**市场影响的概率修订（分歧重述实际移动过的发布概率；"
                         "锚点其后被移除者仍列出）：**")
        else:
            lines.append("**Market-influenced probability revisions (accepted divergence "
                         "revisions that moved a published probability; removed anchors "
                         "remain listed):**")
        for inf in influences:
            fid = _mc_cell(inf.get("forecast_id") or "")
            q = _mc_cell(str(inf.get("market_question") or "")[:100])
            mid = _mc_cell(inf.get("market_id") or "")
            move = f"{_pct(inf.get('prior_probability'))} → {_pct(inf.get('revised_probability'))}"
            conf = _mc_float(inf.get("match_confidence"))
            conf_s = f"{conf:.2f}" if conf is not None else "—"
            if zh:
                item = (f"- {fid} — {q or '—'}（{mid}）：{move}"
                        f"（修订时市场 P(yes) {_pct(inf.get('price_at_revision'))}，"
                        f"匹配置信度 {conf_s}）")
                if inf.get("anchor_removed"):
                    if inf.get("probability_restored"):
                        item += (f"—— 锚点在对账中被移除；概率已恢复为 "
                                 f"{_pct(inf.get('current_probability'))}")
                    else:
                        item += "—— 锚点在对账中被移除（修订其后已被取代，未回滚）"
            else:
                item = (f"- {fid} — {q or '—'} ({mid}): {move} at market P(yes) "
                        f"{_pct(inf.get('price_at_revision'))}, match confidence {conf_s}")
                if inf.get("anchor_removed"):
                    if inf.get("probability_restored"):
                        item += (" — anchor removed in reconciliation; probability restored "
                                 f"to {_pct(inf.get('current_probability'))}")
                    else:
                        item += (" — anchor removed in reconciliation (revision already "
                                 "superseded; not rolled back)")
            lines.append(item)
    if unmatched:
        lines.append("")
        if zh:
            lines.append("**未匹配市场（快照中未被任何预测锚定，可补充对照）：**")
        else:
            lines.append("**Unmatched markets (in snapshot, not anchored by any "
                         "forecast — candidate cross-checks):**")
        for m in unmatched[:20]:
            ip = _mc_float(m.get("implied_yes_prob"))
            ip_s = f"{ip * 100:.0f}%" if ip is not None else "—"
            q = _mc_cell(str(m.get("question") or "")[:120])
            url = str(m.get("url") or "").strip()
            label = f"[{q}]({_mc_cell(url)})" if (q and url) else (q or _mc_cell(m.get("market_id") or ""))
            if zh:
                lines.append(f"- {label} — 隐含 P(yes) {ip_s}")
            else:
                lines.append(f"- {label} — implied P(yes) {ip_s}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# ReportAgent 主类
# ═══════════════════════════════════════════════════════════════


class ReportAgent:
    """
    Report Agent - 模拟报告生成Agent

    采用ReACT（Reasoning + Acting）模式：
    1. 规划阶段：分析模拟需求，规划报告目录结构
    2. 生成阶段：逐章节生成内容，每章节可多次调用工具获取信息
    3. 反思阶段：检查内容完整性和准确性
    """
    
    # T4.4: 工具调用上下限从 Config 读取（默认 8/4/2 = 原硬编码值，行为不变；运维可调成本/深度）
    MAX_TOOL_CALLS_PER_SECTION = Config.REPORT_AGENT_MAX_TOOL_CALLS
    MIN_TOOL_CALLS_PER_SECTION = Config.REPORT_AGENT_MIN_TOOL_CALLS

    # 最大反思轮数
    MAX_REFLECTION_ROUNDS = 3

    # 对话中的最大工具调用次数
    MAX_TOOL_CALLS_PER_CHAT = Config.REPORT_AGENT_MAX_TOOL_CALLS_CHAT

    # 大纲章节数契约（RQ-1：展开默认 6-14 节；PLAN_SYSTEM_PROMPT 同步要求 6-14 节）。此处为
    # 「无/大 page_budget」时的默认钳制边界；小 page_budget 报告经 _report_shape() 收敛回 5-8。
    # LOOP-015：min_sections 仅作为提示词的数量要求；成功解析的大纲改为「连贯性优先」——
    # >= OUTLINE_PAD_FLOOR_SECTIONS 节即接受，不再用通用兜底标题硬凑（max 仍截断，except 兜底不变）。
    OUTLINE_MIN_SECTIONS = 6
    OUTLINE_MAX_SECTIONS = 14
    # LOOP-015：padding 触发线——规划器产出 >=4 节连贯大纲即接受；仅 <4 节时补齐到 4，
    # 且补齐章节打 padded 标记（有效工具调用下限 0，见 _effective_min_tool_calls）。
    OUTLINE_PAD_FLOOR_SECTIONS = 4
    # 兜底章节标题：数量需 >= 任意形状的 min_sections（展开 6）——except 全量兜底大纲取用；
    # padding 时按需取用去重。
    _FALLBACK_SECTION_TITLES = [
        "预测场景与核心发现",
        "关键行为者与系统动力",
        "关键驱动与证据链",
        "趋势展望与情景推演",
        "风险信号与决策启示",
        "关键转折与不确定性",
        "校准与信心评估",
    ]

    @staticmethod
    def resolve_output_language(simulation_requirement: str, research_report: str = "",
                                situation_brief: str = "") -> str:
        """The report's output language (REPORT_OUTPUT_LANGUAGE override, else sniffed).

        Shared by ``__init__`` and callers that need a finished report's language
        without constructing an agent (EVAL-1's reused-report ledger repair).
        """
        forced = (os.environ.get("REPORT_OUTPUT_LANGUAGE", "") or "").strip()
        if forced:
            return forced
        try:
            from .requirement_spec import detect_output_language
            return detect_output_language(simulation_requirement, research_report, situation_brief)
        except Exception:  # noqa: BLE001 — never block construction on language sniff
            return "English"

    def __init__(
        self,
        graph_id: str,
        simulation_id: str,
        simulation_requirement: str,
        llm_client: Optional[LLMClient] = None,
        zep_tools: Optional[ZepToolsService] = None,
        situation_brief: Optional[str] = None,
        actors: Optional[Dict[str, Any]] = None,
        sources: Optional[List[Dict[str, Any]]] = None,
        research_report: Optional[str] = None,
        scenario_label: Optional[str] = None,
        base_simulation_id: Optional[str] = None,
        charts_manifest: Optional[Any] = None,
        quantitative: Optional[List[Dict[str, Any]]] = None,
        contested: Optional[List[Dict[str, Any]]] = None,
        timeline_events: Optional[List[Dict[str, Any]]] = None,
        graph_priors: Optional[Dict[str, Any]] = None,
        graph_priors_structural: Optional[Dict[str, Any]] = None,
        scenario_spine: Optional[List[Dict[str, Any]]] = None,
    ):
        """
        初始化Report Agent

        Args:
            graph_id: 图谱ID
            simulation_id: 模拟ID
            simulation_requirement: 模拟需求描述
            llm_client: LLM客户端（可选）
            zep_tools: Zep工具服务（可选）
            situation_brief: 研究档案渲染的「背景档案」文本（可选；T4.1）。提供时钉进
                规划/章节提示词，避免报告阶段对全套 cast/关系/时间线盲搜重挖。
            actors: 研究 actors.json 顶层对象（可选）。
            sources: 研究来源列表 [{title,url}]（可选）；渲染为 [S1]/[S2] 引用索引。
            research_report: 原始研究报告 markdown（可选）。
            三者全部缺省时，行为与旧 3 参构造完全一致（冷图盲搜路径）。

        W9-8（研究昂贵产物直通，全部可选、None 默认 → 行为与旧构造逐字节一致）：
            quantitative: 研究 handoff 的 quantitative.json 全量列表（339 行级富指标，
                含 tier/staleness_days/is_stale），替代 actors 内嵌 20 行副本渲染「关键指标」表。
            contested: contested.json 全量争议声明列表，渲染「承重争议声明」表注入风险章节。
            timeline_events: timeline.json 事件列表 [{date,event}]，渲染紧凑时间线注入背景章节。
            graph_priors: graph_priors.json（node_name→[0,1] 中心度，别名组已折叠）。
            graph_priors_structural: graph_priors_structural.json（{betweenness, chokepoints}），
                因果骨架的 chokepoint 支点优先取自此处（研究显著度回退）。
            scenario_spine: 主跑情景脊柱 [{name, resolution_criteria}]（W9-5 多种子集成对齐）——
                钉进骨架推导，让种子对同一组命名情景打分（概率自由，新情景可追加）。
        """
        self.graph_id = graph_id
        self.simulation_id = simulation_id
        self.simulation_requirement = simulation_requirement

        # T4.1: 钉入研究档案。背景块 + 来源索引在构造时一次性渲染，规划与每个章节复用。
        self.situation_brief = situation_brief or ""
        self.actors = actors
        self.sources = sources or []
        self.research_report = research_report or ""
        # QUALITY-OPT F0/B0: decide the report's output language from the brief + research
        # report (an English brief → English submission; a wrong-language report is an automatic
        # round-one fail). Overridable via REPORT_OUTPUT_LANGUAGE. Consumed by _lang_override()
        # (section/plan prompts) and the binary/Part-1 renderers.
        self.output_language = self.resolve_output_language(
            self.simulation_requirement, self.research_report, self.situation_brief)
        # T4.6/T4.7: 情景标签（what-if 框架）+ base 模拟 id（反事实对比）
        self.scenario_label = (scenario_label or "").strip()
        self.base_simulation_id = base_simulation_id or None
        # VIZ-2: 图表清单（charts.json：{title, caption, source_data}），由编排器随 handoff 钉入。
        # 仅存储、不在此进一步接线（报告链按需消费）；缺省 None 时行为与旧构造逐字节一致。
        self.charts_manifest = charts_manifest
        # W9-8: 研究昂贵产物直通（见类 docstring）。形状不符/空值一律归一为 None（绝不抛），
        # 全部缺省时行为与旧构造逐字节一致（degrade-safe）。须在 _build_background_block 之前
        # 赋值——背景块的「关键指标」表消费 self.quantitative。
        self.quantitative = quantitative if isinstance(quantitative, list) and quantitative else None
        self.contested = contested if isinstance(contested, list) and contested else None
        self.timeline_events = (timeline_events
                                if isinstance(timeline_events, list) and timeline_events else None)
        self.graph_priors = graph_priors if isinstance(graph_priors, dict) and graph_priors else None
        self.graph_priors_structural = (
            graph_priors_structural
            if isinstance(graph_priors_structural, dict) and graph_priors_structural else None)
        self.scenario_spine = (scenario_spine
                               if isinstance(scenario_spine, list) and scenario_spine else None)
        # VIZ-2: 研究期图表清单渲染成「可引用图表」块，钉进各章节提示词（章节据此用标准 markdown
        # 图片语法引用图形）；charts_manifest 缺省/空/解析失败时为空串 → 注入自动跳过（degrade-safe）。
        try:
            self._charts_block = self._build_charts_block()
        except Exception:  # noqa: BLE001 — 图表清单为可选增强，绝不阻断构造
            self._charts_block = ""
        self._background_block = self._build_background_block()
        # W9-8: 争议声明表（风险/不确定性章节）+ 紧凑时间线（背景/时间线章节）——章节标题命中
        # 关键词时经 _prepend_research_background(section_title=...) 追加注入；对应工件缺省 /
        # 构建失败时为空串 → 注入自动跳过（degrade-safe，行为与历史一致）。
        try:
            self._contested_table_block = self._build_contested_table_block()
        except Exception:  # noqa: BLE001 — 证据块为可选增强，绝不阻断构造
            self._contested_table_block = ""
        try:
            self._chronology_block = self._build_chronology_block()
        except Exception:  # noqa: BLE001
            self._chronology_block = ""
        # WAVE10（无缝引用）：索引文本随提示词注入；_citation_index（记号→来源）供
        # 引用最终化 / 悬空修复 / 解析度审计解析同一套编号（单一事实源）。
        self._sources_index, self._citation_index = self._build_sources_index()
        # EXECPLAN2 I-3-2: 模拟量化信号包（确定性接地下限），懒构建一次后缓存；
        # 关闭 REPORT_SIGNAL_PACK 时始终为空串，_prepend_research_background 自动跳过（行为不变）。
        self._signal_pack = ""
        # 预测市场信号包（Polymarket 公开 Gamma API，keyless）：市场隐含概率作为**校准锚点**
        # 注入章节/骨架/二元预测提示词。优先读研究 handoff 的 prediction_markets.json，
        # 缺失时经 PolymarketClient 现抓。懒构建一次后缓存；无数据/关闭
        # PREDICTION_MARKETS_ENABLED 时为空串，注入自动跳过（degrade-safe，行为不变）。
        self._market_pack = ""
        self._prediction_markets: List[Dict[str, Any]] = []
        # PM-3：市场快照是否「陈旧」（实时重报价未生效——关闭旗标/client 不可用/整体失败）。
        # True 时 _build_market_pack 在包头附一句时效性说明，读者知道价是研究期而非当下（degrade-safe）。
        self._markets_stale = False
        # NEXTSTEPS P0-1: 预测骨架（情景+概率+判定标准），在章节生成前从信号包+forecast_inputs
        # 推导一次，注入每章提示词让叙事对齐可证伪目标；缺省/未开时为空，_prepend 自动跳过。
        self._forecast_spine: Optional[Dict[str, Any]] = None
        self._forecast_spine_block = ""
        # XRUN-5/RPT-8: 报告级紧凑检索查询（懒派生一次后缓存）；None=未派生。
        self._retrieval_query: Optional[str] = None
        # RQ-1(4): 报告形状（章节数区间 / 每章字数 / 每章工具预算），从需求书 page_budget 懒派生
        # 一次后缓存；None=未派生（见 _report_shape）。小 page_budget→紧凑，无/大→展开默认。
        self._report_shape_cache: Optional[Dict[str, int]] = None
        # RPT-2(a): 大纲规划的 LLM 调用是否失败降级为默认大纲（系统性 LLM 故障的前哨信号）。
        self._outline_degraded = False
        # RPT-5: 大纲摘要（generate_report 规划完成后回填），供引用溯源审计豁免系统注入的
        # 摘要 blockquote（assemble_full_report 固定输出 "> {outline.summary}"）。
        self._outline_summary = ""
        # EVAL-1: 账本提交的溯源上下文（编排器/脚本在构造后赋值：pipeline_id、seed、run_kind、
        # record_class、as_of_date；API 路径不设 → 默认 production）与本次提交回执。
        # 测试经 __new__ 构造 agent 时二者缺失，读取一律走 getattr。
        self.ledger_context: Optional[Dict[str, Any]] = None
        self.ledger_receipt: Optional[Dict[str, Any]] = None

        self.llm = llm_client or LLMClient()
        self.zep_tools = zep_tools or ZepToolsService()
        
        # 工具定义
        self.tools = self._define_tools()
        # interview_agents 需要 OASIS 模拟环境在线（IPC）。报告阶段几乎总在模拟结束、环境关闭之后运行，
        # 此时每次采访都会失败并浪费一轮昂贵的 LLM 工具调用（实测每章被反复 nudge 去采访→失败→回退）。
        # 在 agent 初始化时探活一次：环境不在线就直接从工具集中移除 interview_agents，模型再也看不到它。
        # 环境在线（极少数边跑场景）则保留。探活失败一律按「不可用」处理（degrade-safe）。
        if "interview_agents" in self.tools and not self._interview_env_alive():
            self.tools.pop("interview_agents", None)
            logger.info("报告: OASIS 环境未在线，已从工具集移除 interview_agents（避免每章无效采访重试）")

        # 日志记录器（在 generate_report 中初始化）
        self.report_logger: Optional[ReportLogger] = None
        # 控制台日志记录器（在 generate_report 中初始化）
        self.console_logger: Optional[ReportConsoleLogger] = None
        # EXECPLAN2 F-7-3: chat() 解析到的报告做实例级记忆，避免同一 agent 多次对话重复扫描解析。
        # simulation_id 在 agent 生命周期内固定，缓存安全；用哨兵区分「未解析」与「解析为 None」。
        self._cached_report_sentinel = object()
        self._cached_report = self._cached_report_sentinel
        # EXECPLAN2 I-5-4: 当前章节的工具调用计数器（_execute_tool 单一汇聚点累加），
        # 用于 per-section 遥测；未开遥测时该计数依旧无害地维护，开销可忽略。
        self._section_tool_calls = 0

        # RQ-1(4): 依据需求书 page_budget 收敛/展开本次报告的每章工具预算——小 page_budget 报告回到
        # 紧凑 8 次，无/大预算用展开默认（Config.REPORT_AGENT_MAX_TOOL_CALLS=12）。以实例属性覆盖类
        # 默认，section-gen 仍读 self.MAX_TOOL_CALLS_PER_SECTION（测试经 __new__ 直接赋值，不受影响）。
        try:
            self.MAX_TOOL_CALLS_PER_SECTION = self._report_shape()["tool_budget"]
        except Exception:  # noqa: BLE001 — 形状派生失败保留类默认（degrade-safe）
            pass

        logger.info(f"ReportAgent 初始化完成: graph_id={graph_id}, simulation_id={simulation_id}")

    def _interview_env_alive(self) -> bool:
        """探活 OASIS 模拟 IPC 环境是否在线（interview_agents 的前置依赖）。

        报告阶段通常在模拟结束、环境关闭后运行，此时采访必失败。一次性探活，离线即返回 False，
        调用方据此从工具集移除 interview_agents。任何异常/缺失一律视为「不在线」（degrade-safe）。
        """
        try:
            if not self.simulation_id:
                return False
            import os as _os
            from .simulation_runner import SimulationRunner
            from .simulation_ipc import SimulationIPCClient
            sim_dir = _os.path.join(SimulationRunner.RUN_STATE_DIR, self.simulation_id)
            if not _os.path.isdir(sim_dir):
                return False
            return bool(SimulationIPCClient(sim_dir).check_env_alive())
        except Exception:  # noqa: BLE001 — 探活失败按不可用处理
            return False

    def _report_shape(self) -> Dict[str, int]:
        """RQ-1(4): 报告形状（章节数区间 / 每章字数下限+目标区间 / 每章工具预算）。

        从需求书 page_budget（parse_requirement_spec）懒派生一次后缓存。展开默认取自 Config
        （REPORT_SECTION_FLOOR_CHARS / report_section_target_chars() / REPORT_AGENT_MAX_TOOL_CALLS +
        OUTLINE_MIN/MAX_SECTIONS 类默认），小 page_budget 报告经纯函数 derive_report_shape 收敛回
        紧凑形状。spec 解析失败/无 page_budget → 展开默认（degrade-safe）。"""
        cached = getattr(self, "_report_shape_cache", None)
        if cached is not None:
            return cached
        page_budget: Optional[int] = None
        try:
            from .requirement_spec import parse_requirement_spec
            page_budget = parse_requirement_spec(
                getattr(self, "simulation_requirement", "") or "",
                getattr(self, "research_report", "") or "",
            ).get("page_budget")
        except Exception:  # noqa: BLE001 — spec 解析失败按「无预算」走展开默认
            page_budget = None
        target_lo, target_hi = Config.report_section_target_chars()
        shape = derive_report_shape(
            page_budget,
            expanded_min_sections=self.OUTLINE_MIN_SECTIONS,
            expanded_max_sections=self.OUTLINE_MAX_SECTIONS,
            expanded_floor_chars=int(getattr(Config, "REPORT_SECTION_FLOOR_CHARS", 2000) or 2000),
            expanded_target_lo=target_lo,
            expanded_target_hi=target_hi,
            expanded_tool_budget=int(getattr(Config, "REPORT_AGENT_MAX_TOOL_CALLS", 12) or 12),
        )
        try:
            self._report_shape_cache = shape
        except Exception:  # noqa: BLE001 — 纯缓存写入失败无害
            pass
        return shape

    def _section_prompt_kwargs(self) -> Dict[str, int]:
        """RQ-1(2)/(4)：模板进 SECTION 提示词的篇幅+工具调用范围槽位（随报告形状伸缩）。

        min/max_tool_calls 用实例的下限/上限（后者在真实报告 = 形状 tool_budget；测试经 __new__
        直接赋值时按其覆盖值），section_floor/target 取自形状。供两条 section-gen 路径复用。"""
        shape = self._report_shape()
        return {
            "min_tool_calls": self.MIN_TOOL_CALLS_PER_SECTION,
            "max_tool_calls": self.MAX_TOOL_CALLS_PER_SECTION,
            "section_floor_chars": shape["floor_chars"],
            "section_target_lo": shape["target_lo"],
            "section_target_hi": shape["target_hi"],
        }

    # ──────────────────────────────────────────────────────────────
    # VIZ-2: 研究期图表清单（charts.json：{title, caption, source_data}）
    # ──────────────────────────────────────────────────────────────
    def _available_charts(self) -> List[Dict[str, str]]:
        """VIZ-2：把 self.charts_manifest 规整成可引用图表条目 [{title, caption, path}]。

        也容忍 {"charts": [...]} 包装或缺字段。逐条规整：
          * title / caption 取字符串（缺失留空串）；
          * path 依次探测常见图形路径键（path/image/figure/file/png/svg/src），且必须是
            report-owned charts/ 下的图片或 HTML；source_data 是溯源数据，不是图；
          * 没有安全可渲染 path 的条目丢弃，避免把 actors.json/csv 当成坏图。
        纯函数、无副作用、degrade-safe：manifest 缺省/非列表/元素非字典 → []（绝不抛）。"""
        manifest = getattr(self, "charts_manifest", None)
        if isinstance(manifest, dict):  # 容忍 {"charts": [...]} 包装
            manifest = manifest.get("charts") or manifest.get("figures")
        if not isinstance(manifest, list):
            return []
        _path_keys = ("path", "image", "figure", "file", "png", "svg", "src")
        _allowed_ext = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".html"}
        out: List[Dict[str, str]] = []
        for e in manifest:
            if not isinstance(e, dict):
                continue
            title = str(e.get("title") or e.get("name") or "").strip()
            caption = str(e.get("caption") or e.get("description") or "").strip()
            path = ""
            for k in _path_keys:
                v = str(e.get(k) or "").strip().removeprefix("./")
                parts = v.split("/")
                if (v and len(parts) >= 2 and parts[0] == "charts"
                        and all(part not in ("", ".", "..") for part in parts)
                        and "\\" not in v and "%" not in v
                        and not any(ord(char) < 32 or ord(char) == 127 for char in v)
                        and os.path.splitext(parts[-1])[1].lower() in _allowed_ext):
                    path = "/".join(parts)
                    break
            if not path:
                continue
            out.append({"title": title, "caption": caption, "path": path})
        return out

    def _build_charts_block(self) -> str:
        """VIZ-2：把可引用研究期图表渲染成钉进各章节提示词的「可引用图表」块。

        列出每个图表的标题/说明/相对路径，并示范标准 markdown 图片语法，让章节在相关处以
        ![说明](路径) 引用真实图形，而非凭空描述。无可用图表 → ""（注入自动跳过，行为不变）。"""
        charts = self._available_charts()
        if not charts:
            return ""
        zh = not str(getattr(self, "output_language", "") or "English").lower().startswith("en")
        if zh:
            lines = ["【可引用研究期图表（VIZ-2；相关处用 ![说明](相对路径) 引用真实图形）】"]
        else:
            lines = ["[Available research figures (VIZ-2; reference with "
                     "![caption](relative/path) where relevant)]"]
        for i, c in enumerate(charts, 1):
            title = c.get("title") or c.get("caption") or (f"figure {i}")
            seg = f"{i}. {title}"
            if c.get("caption") and c.get("caption") != title:
                seg += f" — {c['caption']}"
            if c.get("path", "").lower().endswith(".html"):
                seg += f"  [interactive]({c['path']})"
            elif c.get("path"):
                seg += f"  ![{c.get('caption') or title}]({c['path']})"
            lines.append(seg)
        return "\n".join(lines)

    def _build_background_block(self) -> str:
        """T4.1: 把研究背景档案包装成钉入提示词的权威背景块；缺省返回空串（回退冷图路径）。

        T4.6: 若为情景（what-if）报告，前置情景框架，要求正文显式以该情景命名与展开。
        """
        scenario_head = ""
        if self.scenario_label:
            scenario_head = (
                f"【情景预测（What-If）：{self.scenario_label}】\n"
                f"本报告是在「{self.scenario_label}」假设下的反事实预测。撰写时必须显式点明这是"
                f"该情景下的推演，结论需与基线区分。\n\n"
            )
        sb = (self.situation_brief or "").strip()
        if not sb:
            return scenario_head
        aod = ""
        if isinstance(self.actors, dict):
            aod = str(self.actors.get("as_of_date", "") or "").strip()
        header = (
            f"【背景档案（深度研究·权威，as-of {aod}）】" if aod
            else "【背景档案（深度研究·权威）】"
        )
        parts = [
            f"{header}\n"
            "以下为本次预测所依据的深度研究实证档案（角色/关系/时间线/热点均为调研确认）。"
            "撰写时以此为权威背景：优先复用其中真实人名/机构/关系，再用工具补充"
            "可验证的预测驱动、结果路径与量化证据；不得描述内部推演机制。\n\n"
            f"{sb}"
        ]
        # EXECPLAN2 I-0-5/I-0-1/I-0-2: 钉入研究契约富化块（定量事实表/争议证据/预测输入）。
        # 渲染器在 actors.py，皆 degrade-safe（无对应字段返回空串）；受 RESEARCH_FORECAST_INPUTS /
        # RESEARCH_EVIDENCE_GRADING 旗标约束（默认开），关闭即回退到仅 situation_brief 的旧行为。
        try:
            from ..utils import actors as _actors
            if getattr(Config, "RESEARCH_FORECAST_INPUTS", True):
                # W9-8: 优先用研究 handoff 的全量 quantitative.json 渲染「关键指标」表
                # （tier+时效排序过滤，上限 REPORT_KEY_METRICS_MAX），替代 actors 内嵌的
                # 20 行副本；全量列表缺省/渲染为空/旗标关闭 → 回退内嵌副本（行为不变）。
                qb = ""
                if getattr(Config, "REPORT_EVIDENCE_BLOCKS", True):
                    try:
                        qb = self._build_key_metrics_block()
                    except Exception:  # noqa: BLE001 — 关键指标表为可选增强
                        qb = ""
                if not qb:
                    qb = _actors.quantitative_facts_block(self.actors)
                for blk in (qb, _actors.forecast_inputs_block(self.actors)):
                    if blk:
                        parts.append(blk)
            if getattr(Config, "RESEARCH_EVIDENCE_GRADING", True):
                cb = _actors.contested_claims_block(self.actors)
                if cb:
                    parts.append(cb)
            # CLAUDE §9.4/§10：把关键 actor 的关系名册（盟友/对手/竞争者/客户/供应商/出资方/
            # 监管方）+ 核心激励钉进背景，让叙事按真实阵营展开。受 REPORT_RELATIONAL_ROSTER
            # 约束（默认开）；仅当 actor 携带 relationships/worldview/incentives 时生效——
            # 字段全缺时 _build_relational_roster_block 返回空串，背景块与历史逐字节一致（NO-OP）。
            if getattr(Config, "REPORT_RELATIONAL_ROSTER", True):
                rb = self._build_relational_roster_block(_actors)
                if rb:
                    parts.append(rb)
        except Exception as _e:
            logger.debug(f"研究契约富化块渲染跳过: {_e}")
        return "\n\n".join(parts)

    def _build_relational_roster_block(
        self,
        _actors,
        max_actors: int = 8,
        max_per_bucket: int = 4,
        max_chars: int = 3000,
    ) -> str:
        """CLAUDE §9.4/§10：把关键 actor 的关系名册 + 核心激励渲染成紧凑的背景块。

        站在每个核心方视角，列出其盟友/伙伴/支持者/出资方/客户/供应商/竞争者/对手/监管方
        （来自 actors.relational_roster 的 10 个命名桶），并附其核心激励（driver/gains_if/
        loses_if，来自 incentives），让报告叙事能按真实阵营与得失结构展开，而非泛泛而谈。

        NO-OP 保证：当没有任何 actor 携带 relationships / worldview / incentives 等新字段时，
        本方法返回空串，背景块与历史逐字节一致（旧档案 / 现有离线测试夹具行为不变）。
        actor 池按 salience_score 降序、并经 is_agent_eligible 过滤（报道者/概念/资源不入选），
        逐项截断到 max_per_bucket，整体截断到 max_chars，与既有富化块同样有界。
        """
        rows = _actors.extract_actor_rows(self.actors)
        if not rows:
            return ""
        # 仅当确有关系名册或激励数据时才渲染（否则与历史逐字节一致）。先判断是否存在任一关系行，
        # 没有关系边时所有桶必为空，直接早退，避免无谓遍历。
        if not _actors.extract_relationship_rows(self.actors):
            has_incentive = any(
                isinstance(r.get("incentives"), list) and r.get("incentives") for r in rows
            )
            if not has_incentive:
                return ""

        # 能动 actor（tier 1/2）按显著度降序；稳定排序保留同分时的原始出现序。
        eligible = [r for r in rows if _actors.is_agent_eligible(r)]
        eligible.sort(key=lambda r: _actors.salience_score(r), reverse=True)

        # 名册桶 → 中文小标题（与 actors.roster_block 的口吻一致，按谈判语义排序）。
        bucket_labels = (
            ("allies", "盟友"),
            ("partners", "伙伴"),
            ("supporters", "支持者"),
            ("backers_investors", "出资方/投资人"),
            ("customers", "客户/下游"),
            ("suppliers", "供应商/上游"),
            ("competitors", "竞争对手"),
            ("opponents", "对手/对立方"),
            ("regulators", "监管方"),
        )

        lines: List[str] = []
        rendered = 0
        for row in eligible:
            if rendered >= max_actors:  # 精确限制渲染的核心 actor 数（有界，与既有富化块一致）
                break
            name = str(row.get("name", "") or "").strip()
            if not name:
                continue
            roster = _actors.relational_roster(name, self.actors)

            roster_segs: List[str] = []
            for bucket, label in bucket_labels:
                items = roster.get(bucket) or []
                if not items:
                    continue
                names: List[str] = []
                for it in items[:max_per_bucket]:
                    nm = str(it.get("name", "") or "").strip()
                    if nm:
                        names.append(nm)
                if names:
                    roster_segs.append(f"{label}：" + "、".join(names))

            # 核心激励（driver/gains_if/loses_if）压成一两条短句，避免与 persona DNA 块重复冗长。
            inc_segs: List[str] = []
            incentives = row.get("incentives")
            if isinstance(incentives, list):
                for inc in incentives[:2]:
                    if isinstance(inc, dict):
                        driver = str(inc.get("driver", "") or "").strip()
                        gains = str(inc.get("gains_if", "") or "").strip()
                        loses = str(inc.get("loses_if", "") or "").strip()
                        if not (driver or gains or loses):
                            continue
                        seg = driver or "动机"
                        tail: List[str] = []
                        if gains:
                            tail.append(f"得益于「{gains}」")
                        if loses:
                            tail.append(f"受损于「{loses}」")
                        if tail:
                            seg += "（" + "，".join(tail) + "）"
                        inc_segs.append(seg)
                    else:
                        s = str(inc or "").strip()
                        if s:
                            inc_segs.append(s)

            if not (roster_segs or inc_segs):
                continue
            lines.append(f"- **{name}**")
            if roster_segs:
                lines.append("  - 关系网：" + "；".join(roster_segs))
            if inc_segs:
                lines.append("  - 核心激励：" + "；".join(inc_segs))
            # W9-8: 「结构影响力（KG 中心度）」列——图谱结构先验的确定性注记（别名组内
            # MAX 去重，TSMC/2330.TW/TSM 型并列不重复计入）；无先验/关闭旗标时为空（行为不变）。
            try:
                kg_note = self._kg_structural_note(name, row)
            except Exception:  # noqa: BLE001 — 结构注记为可选增强，绝不阻断名册渲染
                kg_note = ""
            if kg_note:
                lines.append("  - 结构影响力（KG 中心度）：" + kg_note)
            rendered += 1

        if not lines:
            return ""
        block = (
            "## 关键角色的关系网与激励（深度研究实证；撰写时据此按真实阵营与得失结构展开）\n"
            + "\n".join(lines)
        )
        if len(block) > max_chars:
            block = block[:max_chars] + "\n…(关系网名册已截断)"
        return block

    _TIER_RANK = {"S1": 0, "S2": 1, "S3": 2, "": 3, None: 3, "S4": 4}

    @staticmethod
    def _md_cell(v: Any, cap: int = 80) -> str:
        """W9-8: markdown 表格单元清洗——去竖线/换行并截断，防表格结构被数据破坏。"""
        s = str(v if v is not None else "").replace("|", "\\|").replace("\n", " ").strip()
        return (s[: cap - 1] + "…") if len(s) > cap else s

    def _build_key_metrics_block(self) -> str:
        """W9-8: 用研究 handoff 的全量 quantitative.json 渲染「关键指标」表。

        排序：证据层级（S1>S2>S3>未知>S4）优先、时点新鲜度次之；上限
        REPORT_KEY_METRICS_MAX（默认 40）。陈旧行（is_stale/staleness_days>180）
        加 ⚠ 标注。无数据/形状不符返回空串（调用方回退 actors 内嵌副本）。"""
        rows = self.quantitative if isinstance(getattr(self, "quantitative", None), list) else None
        if not rows:
            return ""
        try:
            cap = int(getattr(Config, "REPORT_KEY_METRICS_MAX", 40) or 40)
        except (TypeError, ValueError):
            cap = 40
        usable = [r for r in rows if isinstance(r, dict) and (r.get("metric") or r.get("definition"))]
        if not usable:
            return ""
        usable.sort(key=lambda r: (
            self._TIER_RANK.get(str(r.get("tier") or "").upper(), 3),
            str(r.get("as_of_date") or ""),
        ))
        # 层级升序 + 同层级内时点降序：分层后各自反转时点
        usable.sort(key=lambda r: str(r.get("as_of_date") or ""), reverse=True)
        usable.sort(key=lambda r: self._TIER_RANK.get(str(r.get("tier") or "").upper(), 3))
        lines = [
            "## 关键量化指标（研究实证全量表——引用时保持数值与时点原样）",
            "| 指标 | 数值 | 单位 | 时点 | 层级 | 来源 |",
            "|---|---|---|---|---|---|",
        ]
        for r in usable[:cap]:
            stale = bool(r.get("is_stale")) or (
                isinstance(r.get("staleness_days"), (int, float)) and r["staleness_days"] > 180)
            metric = self._md_cell(r.get("metric") or r.get("definition"), 90)
            if stale:
                metric = f"⚠ {metric}"
            lines.append("| " + " | ".join([
                metric, self._md_cell(r.get("value"), 40), self._md_cell(r.get("unit"), 24),
                self._md_cell(r.get("as_of_date"), 16), self._md_cell(r.get("tier"), 8),
                self._md_cell(r.get("source"), 60),
            ]) + " |")
        return "\n".join(lines)

    def _build_contested_table_block(self, max_claims: int = 15) -> str:
        """W9-8: 争议性关键论断块（contested.json 全量，上限 15 条）。

        注入命中风险/不确定性关键词的章节提示词——报告必须正面处理证据分歧而非
        单边引用。无数据返回空串（注入自动跳过）。"""
        rows = self.contested if isinstance(getattr(self, "contested", None), list) else None
        if not rows:
            return ""
        lines = ["## 争议性关键论断（证据分歧——本章须正面呈现两侧立场与依据，不得单边引用）"]
        rendered = 0
        for r in rows:
            if not isinstance(r, dict) or not r.get("claim"):
                continue
            segs = []
            for p in (r.get("positions") or [])[:3]:
                if not isinstance(p, dict) or not p.get("stance"):
                    continue
                src = "；".join(str(s) for s in (p.get("sources") or [])[:2])
                tier = str(p.get("tier") or "").strip()
                tag = f"（{tier}{'，' if tier and src else ''}{src}）" if (tier or src) else ""
                segs.append(f"{self._md_cell(p['stance'], 160)}{tag}")
            if not segs:
                continue
            lines.append(f"- **{self._md_cell(r['claim'], 120)}** — " + " ⇄ ".join(segs))
            rendered += 1
            if rendered >= max_claims:
                break
        return "\n".join(lines) if rendered else ""

    def _build_chronology_block(self, max_events: int = 25) -> str:
        """W9-8: 紧凑时间线块（timeline.json 取最近 max_events 条、按时间升序渲染）。

        注入命中背景/时间线关键词的章节提示词；图表侧另有全量 plotly 时间线。
        无数据返回空串（注入自动跳过）。"""
        rows = (self.timeline_events
                if isinstance(getattr(self, "timeline_events", None), list) else None)
        if not rows:
            return ""
        evts = [r for r in rows if isinstance(r, dict) and r.get("date") and r.get("event")]
        if not evts:
            return ""
        evts.sort(key=lambda r: str(r.get("date") or ""))
        recent = evts[-max_events:]
        lines = ["## 关键事件时间线（研究实证，按时序——叙事因果链须与之一致）"]
        seen = set()
        for r in recent:
            key = (str(r["date"]), str(r["event"])[:60].lower())
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"- {self._md_cell(r['date'], 16)}：{self._md_cell(r['event'], 160)}")
        return "\n".join(lines) if len(lines) > 1 else ""

    def _kg_structural_note(self, name: str, row: Dict[str, Any]) -> str:
        """W9-8: 单个 actor 的「结构影响力（KG 中心度）」确定性注记。

        取 graph_priors（度中心度先验，别名组内取 MAX 去重）+ graph_priors_structural
        的 chokepoints（结构瓶颈点标记）。无先验数据返回空串（名册渲染不变）。"""
        priors = self.graph_priors if isinstance(getattr(self, "graph_priors", None), dict) else None
        gps = (self.graph_priors_structural
               if isinstance(getattr(self, "graph_priors_structural", None), dict) else None)
        if not priors and not gps:
            return ""
        names = [str(name)]
        for a in (row.get("aliases") or []) if isinstance(row, dict) else []:
            if a:
                names.append(str(a))
        lower_map = {str(k).strip().lower(): float(v) for k, v in (priors or {}).items()
                     if isinstance(v, (int, float))}
        vals = [lower_map[n.strip().lower()] for n in names if n.strip().lower() in lower_map]
        segs = []
        if vals:
            v = max(vals)
            ranked = sorted(set(lower_map.values()), reverse=True)
            try:
                rank = ranked.index(v) + 1
                segs.append(f"度中心度先验 {v:.2f}（全图第{rank}）")
            except ValueError:
                segs.append(f"度中心度先验 {v:.2f}")
        if gps:
            chokes = gps.get("chokepoints")
            names_l = {n.strip().lower() for n in names}
            if isinstance(chokes, list) and any(
                    str(c).strip().lower() in names_l for c in chokes):
                segs.append("结构瓶颈点（介数中心性识别）")
        return "；".join(segs)

    @staticmethod
    def _simleak_skip_line(s: str) -> bool:
        """W9 泄漏扫描的行分类：True=跳过（非散文）。'**' 加粗导语行按散文处理
        （旧实现把 '*' 一并跳过，导致 '**…**:' 机制段落逃过 Tier-2/3 清洗）。"""
        if s.startswith(("#", ">", "|", "!", "```", "~~~")):
            return True
        if s.startswith("*") and not s.startswith("**"):
            return True
        if s.startswith("-"):
            return True
        return False

    def _compact_retrieval_query(self) -> str:
        """XRUN-5/RPT-8: 派生一次报告级紧凑检索查询并缓存。

        整段需求书（3388 字）被直接当 query 时会被长度钳制砍到只剩开头修辞句，
        报告阶段杠杆最高的几次检索（大纲上下文 / InsightForge 全局扫描）从此全部
        锚定在引言上。这里按句界取核心问题前缀 + 追加高显著度 actor 名（让实体词
        进入 BM25/嵌入）。REPORT_COMPACT_RETRIEVAL_QUERY=False 时原样返回需求书
        （行为与历史一致）；任何失败也退回原文（degrade-safe）。
        """
        if getattr(self, "_retrieval_query", None) is not None:
            return self._retrieval_query
        req = self.simulation_requirement or ""
        if not getattr(Config, "REPORT_COMPACT_RETRIEVAL_QUERY", True):
            self._retrieval_query = req
            return req
        try:
            from .zep_tools import compact_graph_query
            q = compact_graph_query(req, 280)
            if len(q) < len(" ".join(req.split())):
                try:
                    from ..utils import actors as _actors
                    rows = _actors.extract_actor_rows(self.actors)
                    eligible = [r for r in rows if _actors.is_agent_eligible(r)]
                    eligible.sort(key=lambda r: _actors.salience_score(r), reverse=True)
                    names: List[str] = []
                    for r in eligible:
                        nm = str((r or {}).get("name", "") or "").strip()
                        if nm and nm not in names:
                            names.append(nm)
                        if len(names) >= 6:
                            break
                    if names:
                        q = (q + " " + " ".join(names))[:360]
                except Exception:  # noqa: BLE001 — actor 名为可选增强
                    pass
                logger.info(f"已派生紧凑检索查询（{len(req)}→{len(q)} 字符）: {q[:80]}...")
            self._retrieval_query = q or req
        except Exception:  # noqa: BLE001 — 派生失败退回原需求书
            self._retrieval_query = req
        return self._retrieval_query

    def _build_sources_index(self) -> Tuple[str, Dict[str, Dict[str, Any]]]:
        """T4.1/WAVE10: 把研究来源渲染成引用索引 → ``(索引文本, 记号→来源映射)``。

        WAVE10（无缝引用，单一语法）：默认走 actors.sources_index_unified——正文引用记号
        只有一种形状（裸 [S<n>]，n=来源原始位置），层级降级为标题后的展示注记；条目按
        「研究报告中被引用优先 → 层级 → 原始顺序」相关性排序后截取
        REPORT_SOURCES_INDEX_MAX（默认 60，替代旧的盲切 [:40]）。记号映射供引用最终化 /
        悬空修复 / 解析度审计解析。

        REPORT_CITATION_SINGLE_GRAMMAR=false 时回退旧行为（分层 [S1-a] 或位置 [:40]），
        映射按对应旧格式构建（degrade-safe）。缺省来源返回 ("", {})。
        """
        if not self.sources:
            return "", {}
        # Keep original list positions stable (S<n> is positional), but replace
        # malformed/non-resolvable rows with sentinels so they can never enter
        # the model-visible citation namespace.
        admissible_sources = [
            source if _citation_source_admissible(source) else None
            for source in self.sources
        ]
        try:
            max_n = int(getattr(Config, "REPORT_SOURCES_INDEX_MAX", 60) or 60)
        except (TypeError, ValueError):
            max_n = 60
        if getattr(Config, "REPORT_CITATION_SINGLE_GRAMMAR", True):
            try:
                from ..utils import actors as _actors
                text, tag_map = _actors.sources_index_unified(
                    admissible_sources, research_report=self.research_report,
                    max_sources=max_n)
                if text:
                    return text, tag_map
            except Exception as _e:  # noqa: BLE001 — 统一索引失败回退旧路径
                logger.warning(f"统一来源索引渲染失败，回退旧索引: {_e}")
        if getattr(Config, "RESEARCH_EVIDENCE_GRADING", True):
            try:
                from ..utils import actors as _actors
                tiered = _actors.sources_index_tiered(admissible_sources)
                if tiered:
                    return tiered, _actors.sources_index_tiered_map(admissible_sources)
            except Exception as _e:
                logger.debug(f"分层来源索引渲染跳过，回退位置索引: {_e}")
        lines = ["【可引用来源（正文用 [S1]/[S2] 形式标注）】"]
        tag_map: Dict[str, Dict[str, Any]] = {}
        for i, s in enumerate(admissible_sources[:40], 1):
            if not _citation_source_admissible(s):
                continue
            title = str(s.get("title", "") or "").strip()
            url = str(s.get("url", "") or "").strip()
            seg = f"[S{i}] {title}".rstrip()
            if url:
                seg += f" — {url}"
            lines.append(seg)
            tag_map[f"S{i}"] = s
        if len(lines) <= 1:
            return "", {}
        return "\n".join(lines), tag_map

    def _prepend_research_background(self, prompt: str, section_title: str = "") -> str:
        """T4.1: 把背景档案 + 来源索引钉到提示词最前；二者皆空时原样返回（回退冷图路径）。

        W9-8: section_title 命中风险/不确定性关键词时追加争议性论断表；命中背景/时间线
        关键词时追加紧凑时间线块。未传/未命中/块为空时行为与历史逐字节一致。

        EXECPLAN2 I-3-2: 同时钉入模拟量化信号包（self._signal_pack），使每个章节都获得确定性的
        量化接地下限。信号包为空（未开启或无结构化数据）时自动跳过，行为与历史一致。

        NEXTSTEPS P0-1: 还钉入预测骨架块（self._forecast_spine_block），让每章叙事对齐并捍卫
        先于叙事确定的情景概率与判定标准。骨架未推导/为空时自动跳过（行为与历史一致）。

        预测市场：还钉入市场信号包（self._market_pack，Polymarket 公开 Gamma API 的
        隐含概率表）——涉及概率的论断须与市场锚点对照。为空时自动跳过（行为与历史一致）。

        VIZ-2：还钉入可引用图表块（self._charts_block，研究期 charts.json）——章节可用标准
        markdown 图片语法引用真实图形。为空时自动跳过（行为与历史一致）。
        """
        # 市场包/图表块经 getattr 读取：部分离线测试用 __new__ 绕过 __init__ 构造 agent，
        # 缺属性时按空串处理（与注入跳过语义一致）。
        prefix_parts = [p for p in (
            self._background_block, self._sources_index,
            self._forecast_spine_block, self._signal_pack,
            getattr(self, "_market_pack", ""),
            getattr(self, "_charts_block", ""),
        ) if p]
        # W9-8: 章节定向证据块——标题命中关键词时追加争议表 / 时间线（块为空时自动跳过）。
        prefix_parts.extend(self._section_evidence_blocks(section_title))
        if not prefix_parts:
            return prompt
        return "\n\n".join(prefix_parts) + "\n\n" + prompt

    def _section_evidence_blocks(self, section_title: str) -> List[str]:
        """W9-8 / LOOP-015: 章节定向证据块——标题命中关键词时返回争议性论断表 / 紧凑时间线。

        从 _prepend_research_background 抽出为独立方法：注入路径用它拼提示词前缀，章节生成
        路径用同一判据识别「提示词已自带匹配证据」的章节并下调有效工具调用下限
        （见 _effective_min_tool_calls），两侧永不漂移。未传标题/未命中/块为空 → []
        （与历史注入跳过语义逐字节一致）。"""
        blocks: List[str] = []
        title_l = (section_title or "").lower()
        if not title_l:
            return blocks
        if any(k in title_l for k in (
                "风险", "不确定", "争议", "分歧", "risk", "uncertaint", "contested", "disagree")):
            blk = getattr(self, "_contested_table_block", "")
            if blk:
                blocks.append(blk)
        if any(k in title_l for k in (
                "时间线", "背景", "沿革", "演进", "历史", "timeline", "background",
                "chronolog", "history", "context")):
            blk = getattr(self, "_chronology_block", "")
            if blk:
                blocks.append(blk)
        return blocks

    def _effective_min_tool_calls(self, section: "ReportSection") -> int:
        """LOOP-015: 章节的**有效**工具调用下限（token 成本护栏，供两条 section-gen 路径复用）。

        - 大纲兜底补齐的 padding 章节（section.padded）→ 0：凑数章节直接综合提示词内已注入
          的背景/信号/骨架材料成文，不再烧满一轮 4-12 次的检索循环；
        - 标题命中定向证据块（争议表/时间线已钉入提示词，见 _section_evidence_blocks）→ 至多 1：
          提示词自带匹配证据，强制凑满配置下限只会产出冗余回包；
        - 其余章节维持配置下限 REPORT_AGENT_MIN_TOOL_CALLS（行为与历史一致）。"""
        if getattr(section, "padded", False):
            return 0
        if self._section_evidence_blocks(getattr(section, "title", "") or ""):
            return min(1, self.MIN_TOOL_CALLS_PER_SECTION)
        return self.MIN_TOOL_CALLS_PER_SECTION

    def _prior_section_char_budget(self, floor_chars: int = 8000, n_items: int = 1) -> int:
        """RQ-7 / I-6-4：前序章节上下文切片的预算化字符上限。

        ADAPTIVE_CONTEXT=true 时按**当前提供方的上下文窗口**放宽——大窗口模型
        （MiniMax-M3 512K / DeepSeek 1M）携带全量前文以增强跨章连贯与 grounding；
        小窗口/未知提供方（回退 32K）守住今天的 floor_chars 固定切片。share/num_items
        把前序章节这一类上下文限制在窗口的一个保守份额内、并按章节数平摊，避免 N 章 × 大切片
        撑爆窗口。ADAPTIVE_CONTEXT 关闭或任何异常 → 返回 floor_chars（degrade-safe，
        与历史逐字节一致）。返回值恒 >= floor_chars（token_budget.slice_budget_chars 的 floor 语义）。
        """
        if not getattr(Config, "ADAPTIVE_CONTEXT", False):
            return floor_chars
        try:
            from ..utils import token_budget as _tb
            provider = getattr(self.llm, "provider", None) or Config.LLM_PROVIDER
            window = Config.context_window_for(provider)
            return _tb.slice_budget_chars(
                window_tokens=window,
                reserved_tokens=getattr(Config, "RESERVED_COMPLETION_TOKENS", 8192),
                floor_chars=floor_chars,
                share=0.5,           # 前序章节须与系统提示/工具回包/补全共享窗口，取保守半额
                num_items=max(1, int(n_items)),
            )
        except Exception as _e:  # noqa: BLE001 — 预算化仅为增强，任何失败退回固定切片
            logger.debug(f"前序章节预算化切片回退固定值 {floor_chars}: {_e}")
            return floor_chars

    def _build_signal_pack(self) -> str:
        """EXECPLAN2 I-3-2: 组装一份紧凑、确定性的「模拟量化信号包」，钉进每个章节提示词。

        内容来自既有的确定性结构化工具（simulation_outcomes / coalition_map / scenario_diff），
        全部为可直接引用的硬数字（Top actor / 逐轮动作量 + 峰值 / 动作类型分布 / 派系数与规模
        / 反事实差异）。任一子块缺失时其友好降级串会被截断逻辑过滤掉，整包自我抑制。

        计算一次后缓存在 self._signal_pack；仅在 Config.REPORT_SIGNAL_PACK 为真时调用。
        篇幅有界（单块各自截断），避免给每个章节提示词注入过量 token。
        """
        # Foglamp WP1 (1D, I-11/I-16)：SIMULATION_FORECAST_EFFECT=no_update 时整包自抑制
        # （连诊断散文也不注入）。默认 diagnostic_only：允许作为「显式标注模拟来源」的
        # 诊断分析进入章节散文，但绝不进入概率生成路径（见 _derive_and_pin_forecast_spine）。
        _effect = str(getattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
                      or "diagnostic_only").strip().lower()
        if _effect == "no_update":
            return ""
        parts: List[str] = []
        # 0) NEXTSTEPS P1-1: 决策通道演化出的「结果世界态」——建模出的 P(outcome)（按情景份额），
        # 比声量份额更接近真实结果。仅开启 SIM_DECISION_CHANNEL 时存在；置于最前（最权威）。
        try:
            ws_blk = self._world_state_block()
            if ws_blk:
                parts.append(ws_blk)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"信号包 world_state 读取失败（忽略）: {e}")
        # 0b) NEXTSTEPS P3-8: 关系演化投影到预测时点（保守模型先验，显式标注=非证据）。
        # 默认关（REPORT_PROJECTED_EDGES）；标注 contingent 的纽带是情景分叉支点。
        if getattr(Config, "REPORT_PROJECTED_EDGES", False):
            try:
                from ..utils.actors import projected_edges_block as _pe_blk
                pe_blk = _pe_blk(self.actors)
                if pe_blk:
                    parts.append(pe_blk)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"信号包 projected_edges 失败（忽略）: {e}")
        # 1) 量化结果——WAVE9：默认把原始动作计数确定性转写为定性「议程设置力分层」再注入
        # （REPORT_SIGNAL_PACK_QUALITATIVE，默认开）；转写失败或旗标关闭回退原始文本（截断 ~3600 字）。
        try:
            outcomes = self.zep_tools.simulation_outcomes(self.simulation_id, top_n=8)
            if outcomes and not outcomes.strip().startswith("（"):
                if getattr(Config, "REPORT_SIGNAL_PACK_QUALITATIVE", True):
                    tiers = salience_tiers_from_outcomes(outcomes)
                    if tiers:
                        parts.append(tiers)
                    elif not _actor_counts_flat(_parse_outcome_actors(outcomes)):
                        # 转写失败（解析不出行为者）才回退原始文本（历史行为）；LOOP-015：
                        # 计数持平判空 = 无信号，整块自抑制——绝不回退原始动作计数，
                        # 那正是 WAVE9 定性转写要挡住的机制数字泄漏。
                        parts.append(outcomes[:3600])
                else:
                    parts.append(outcomes[:3600])
        except Exception as e:  # noqa: BLE001 — 信号包为可选增强，失败仅告警不影响主流程
            logger.warning(f"信号包 simulation_outcomes 计算失败（忽略）: {e}")
        # 2) 派系/联盟结构——RQ-4：截断到 ~1600 字
        try:
            coalitions = self.zep_tools.coalition_map(self.graph_id, self.simulation_id)
            if coalitions and not coalitions.strip().startswith("（"):
                parts.append(coalitions[:1600])
        except Exception as e:  # noqa: BLE001
            logger.warning(f"信号包 coalition_map 计算失败（忽略）: {e}")
        # 2b) R2-KG-7: 因果骨架——chokepoint 多跳因果邻域 + 最强 source→outcome 路径（含
        # 方向/符号/强度/时滞）。RQ-4：默认开（Config.REPORT_CAUSAL_SPINE=True），且 graph 层
        # 多跳遍历有界、任意失败降级为空串，不影响信号包其余部分。
        if getattr(Config, "REPORT_CAUSAL_SPINE", True):
            try:
                cs_blk = self._build_causal_spine_block()
                if cs_blk:
                    parts.append(cs_blk)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"信号包 causal_spine 计算失败（忽略）: {e}")
        # 3) 反事实差异（仅情景报告有基线时）——RQ-4：截断到 ~2400 字
        if self.base_simulation_id:
            try:
                diff = self.zep_tools.scenario_diff(self.base_simulation_id, self.simulation_id)
                if diff and not diff.strip().startswith("（"):
                    parts.append(diff[:2400])
            except Exception as e:  # noqa: BLE001
                logger.warning(f"信号包 scenario_diff 计算失败（忽略）: {e}")

        if not parts:
            return ""
        # Foglamp WP1 (1D)：旧版指令要求把模拟产出「转写」为现实世界判断、同时禁止提及模拟——
        # 这会把合成叙事洗成未标注的真实世界证据（social→institutional laundering）。
        # 新规则：诊断材料可以分析，但引用时必须标注模拟来源，且不得据此给出/修改概率数字。
        header = (
            "【内部情景推演·诊断材料（elicited model projection——模型引出的推演投影，"
            "非观察证据）】\n"
            "使用规则：以下产出可用于机制分析（权力集中度、联盟结构、脆弱节点、议程设置力"
            "的假设生成），但：\n"
            "✅ 正文引用其任何判断时必须显式标注来源为内部情景推演（如「内部情景推演显示…」），"
            "不得表述为观察到的现实世界事实；\n"
            "✅ 现实世界的定量声明只能来自研究材料并带 [S#] 引用；\n"
            "❌ 严禁依据本材料给出、调整或佐证任何结果概率数字——概率由预测骨架独立裁定，"
            "本材料不进入概率生成路径（forecast_effect=diagnostic_only）；\n"
            "❌ 严禁在正文引用动作次数、轮次、动作类型、发帖/点赞/评论等机制细节。"
        )
        return header + "\n\n" + "\n\n".join(parts)

    def _world_state_block(self) -> str:
        """NEXTSTEPS P1-1: 读取模拟的 world_state_trajectory.json（决策通道产物），渲染**建模出的
        结果分布 P(outcome)**。未开 SIM_DECISION_CHANNEL / 无产物 → ""（degrade-safe）。

        日历模式（轨迹 schema v3，spec §4/§6）：额外渲染 ~4 个带日期的演化航点
        （首轮/⅓/⅔/末轮），趋稳判定改为日历口径（"于 {label} 前趋稳"），且
        horizon_defaulted 时强制披露默认 12 个月期限。v2 轨迹渲染逐字节不变。
        """
        try:
            path = os.path.join(getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "",
                                self.simulation_id, "world_state_trajectory.json")
            if not os.path.exists(path):
                return ""
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            return ""
        shares = ((data or {}).get("outcome") or {}).get("shares") or {}
        if not isinstance(shares, dict) or not shares:
            return ""
        # Foglamp WP1 (1D, I-11)：WorldState 是 elicited model projection（模型引出的推演
        # 投影），不是权威/硬模拟证据；标签随块携带，且带上 1C 的有效性裁定（若有）。
        lines = ["【推演结果分布 P(outcome)（elicited model projection——模型引出的推演投影，"
                 "非观察证据；仅供机制分析，不得据此调整概率）】"]
        _validity = str((data or {}).get("validity") or "").strip().lower()
        if _validity and _validity != "valid":
            lines.append(f"⚠️ 有效性裁定：{_validity}（决策通道存在失败/沉默轮，"
                         "本分布不可用作任何依据；forecast_effect=no_update）")
        for name, sh in sorted(shares.items(), key=lambda kv: -float(kv[1] or 0)):
            try:
                lines.append(f"· {name}: {float(sh) * 100:.0f}%")
            except (TypeError, ValueError):
                continue
        ca = (data or {}).get("converged_at")
        traj = (data or {}).get("trajectory")
        rows = [r for r in (traj if isinstance(traj, list) else [])
                if isinstance(r, dict) and isinstance(r.get("shares"), dict) and r.get("shares")]
        if (data or {}).get("schema_version") == 3 and rows:
            # 日历航点：首轮/⅓/⅔/末轮（去重），每行 "截至 {period_end}: {A} 62% / {B} 38%"
            n = len(rows)
            lines.append("演化航点（按日历时段）：")
            for i in sorted({0, n // 3, (2 * n) // 3, n - 1}):
                row = rows[i]
                pe = str(row.get("period_end") or row.get("as_of") or f"第{row.get('round')}轮")
                segs = []
                for k, v in sorted(row["shares"].items(), key=lambda kv: -float(kv[1] or 0)):
                    try:
                        segs.append(f"{k} {float(v) * 100:.0f}%")
                    except (TypeError, ValueError):
                        continue
                if segs:
                    lines.append(f"截至 {pe}: {' / '.join(segs)}")
            if ca is not None:
                label = ""
                for row in rows:  # 趋稳轮所在时段（round 对不上时取其后第一个时段）
                    rr = row.get("round")
                    if isinstance(rr, (int, float)) and rr >= float(ca):
                        label = str(row.get("label") or row.get("period_end") or "")
                        break
                if not label:
                    label = str(rows[-1].get("label") or rows[-1].get("period_end") or "")
                lines.append(f"于 {label} 前趋稳")
            else:
                lines.append("截至判定日尚未趋稳，应降低信心")
            if (data or {}).get("horizon_defaulted"):
                lines.append("预测期限未在问题中明确，默认取 12 个月"
                             f"（截至 {(data or {}).get('horizon_date') or ''}）")
        else:
            lines.append("稳定性诊断：已趋稳" if ca else "稳定性诊断：尚未趋稳（应降低信心）")
        lines.append("注：这是结构化情景分析先验，不是观察事实；正文结论必须以研究来源和现实指标校验。")
        return "\n".join(lines)

    def _temporal_horizon_date(self) -> str:
        """日历模式的判定日 horizon_date（轨迹 v3 优先，其次 simulation_config 的
        temporal_config）；hours 模式/无产物 → ""（调用方回退旧行为，degrade-safe）。"""
        try:
            sim_dir = os.path.join(getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "",
                                   str(self.simulation_id or ""))
            for fname in ("world_state_trajectory.json", "simulation_config.json"):
                path = os.path.join(sim_dir, fname)
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    continue
                if fname == "simulation_config.json":
                    data = data.get("temporal_config") or {}
                if isinstance(data, dict) and data.get("mode") == "calendar" \
                        and data.get("horizon_date"):
                    return str(data["horizon_date"])
        except Exception:  # noqa: BLE001 — 期限定位失败退回 as_of_date 旧行为
            return ""
        return ""

    # ──────────────────────────────────────────────────────────────
    # 预测市场信号包（Polymarket 公开 Gamma API；市场隐含概率 = 校准锚点）
    # ──────────────────────────────────────────────────────────────
    def _load_prediction_markets(self) -> List[Dict[str, Any]]:
        """加载本次运行的预测市场快照（规整化 schema，见 utils.prediction_markets）。

        优先级：① 研究阶段落盘的 handoff/prediction_markets.json（经 PipelineManager 按
        simulation_id 定位，与 load_research_dossier_for_simulation 同模式）；② 文件缺失
        且 PolymarketClient 可用时现抓一次（检索词由需求书 + hot_topics + 头部 actor 名确定性
        派生）。任何失败返回 []（degrade-safe，绝不阻断报告生成）。
        """
        try:
            max_n = int(getattr(Config, "PREDICTION_MARKETS_MAX", 20) or 20)
        except (TypeError, ValueError):
            max_n = 20
        # ① 研究 handoff 产物（延迟导入避免与 pipeline_orchestrator 的模块级循环依赖）。
        try:
            from .pipeline_orchestrator import PipelineManager
            for entry in PipelineManager.list_pipelines():
                pid = entry.get("pipeline_id")
                if not pid:
                    continue
                data = PipelineManager.load(pid)
                if not data or data.get("simulation_id") != getattr(self, "simulation_id", None):
                    continue
                hd = data.get("handoff_dir") or PipelineManager.handoff_dir(pid)
                path = os.path.join(hd, "prediction_markets.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        payload = json.load(f)
                    markets = payload.get("markets") if isinstance(payload, dict) else payload
                    rows = [m for m in (markets or []) if isinstance(m, dict)]
                    if rows:
                        # PM-3：handoff-PLUS-refresh——研究期快照拉进来后对其做一次实时重报价，
                        # 保留 price_at_research 并算 Δ；重报价未生效时用研究期价并置 _markets_stale。
                        return self._requote_snapshot(rows[:max_n])
                break  # 找到对应管线即停（无论有无市场文件），转现抓兜底
        except Exception as e:  # noqa: BLE001 — handoff 读取失败转现抓兜底
            logger.debug(f"读取 handoff prediction_markets.json 失败（转现抓兜底）: {e}")
        # ② 现抓兜底（仅当 client + report LLM 可用）。Unlike the canonical research
        # artifact, this late path has no researcher to vet lexical matches, so it is
        # deliberately fail-closed: only rows carrying an explicit LLM relevance score
        # may enter the report.
        try:
            from ..utils.prediction_markets import (
                PolymarketClient,
                derive_market_queries_llm,
                score_market_relevance,
            )
            client = PolymarketClient()
            if not client.enabled or not getattr(self, "llm", None):
                return []
            hot_topics: List[str] = []
            actor_names: List[str] = []
            _act = getattr(self, "actors", None)
            if isinstance(_act, dict):
                hot_topics = [str(t) for t in (_act.get("hot_topics") or []) if t]
                try:
                    from ..utils import actors as _actors
                    rows = [r for r in _actors.extract_actor_rows(_act)
                            if _actors.is_agent_eligible(r)]
                    rows.sort(key=lambda r: _actors.salience_score(r), reverse=True)
                    actor_names = [str((r or {}).get("name", "") or "").strip()
                                   for r in rows]
                    actor_names = [n for n in actor_names if n]
                except Exception:  # noqa: BLE001 — actor 名为查询词的可选增强
                    pass
            question = getattr(self, "simulation_requirement", "") or ""

            def _market_llm(prompt: str) -> str:
                return str(self.llm.chat(
                    messages=[
                        {"role": "system", "content": (
                            "You are a strict prediction-market retrieval classifier. "
                            "Return only the requested JSON; never invent a market ID.")},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                ) or "")

            queries = derive_market_queries_llm(
                _market_llm, question, hot_topics=hot_topics, actors=actor_names)
            if not queries:
                return []
            try:
                min_vol = float(getattr(Config, "PREDICTION_MARKETS_MIN_VOLUME", 200) or 200)
            except (TypeError, ValueError):
                min_vol = 200.0
            try:
                max_per_event = int(getattr(Config, "PREDICTION_MARKETS_MAX_PER_EVENT", 3) or 3)
            except (TypeError, ValueError):
                max_per_event = 3
            candidates = client.snapshot_for_queries(
                queries, max_total=max_n, min_volume=min_vol,
                max_per_event=max_per_event)
            scored = score_market_relevance(_market_llm, question, candidates)
            markets = [row for row in scored if row.get("relevance_score") is not None]
            if markets:
                logger.info(f"预测市场现抓兜底：{len(markets)} 个活跃市场（queries={queries}）")
                report_id = str(getattr(self, "_active_report_id", "") or "")
                if report_id:
                    try:
                        from ..utils.atomic import write_json_atomic
                        write_json_atomic(
                            os.path.join(ReportManager._get_report_folder(report_id),
                                         "prediction_markets_recovered.json"),
                            {"as_of": datetime.now(timezone.utc).isoformat(),
                             "source": "report_fallback", "queries": queries,
                             "markets": markets,
                             "status": {"attempted": True,
                                        "candidate_count": len(candidates),
                                        "selected_count": len(markets),
                                        "empty_reason": None}},
                        )
                    except Exception as persist_error:  # noqa: BLE001 — observability only
                        logger.debug(f"写入报告期预测市场恢复工件失败（忽略）: {persist_error}")
            self._markets_stale = False  # PM-3：现抓即实时价，不陈旧
            return markets
        except Exception as e:  # noqa: BLE001 — 市场信号为可选增强
            logger.warning(f"预测市场信号抓取失败（忽略）: {e}")
            return []

    def _requote_snapshot(self, markets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """PM-3：对研究期市场快照做一次实时重报价（PREDICTION_MARKETS_REQUOTE，默认开）。

        走 PolymarketClient.requote_markets：当前 "Yes" 价覆盖 implied_yes_prob、保留研究期价
        price_at_research、算 price_delta——读者能看到「34%→41%」的移动，判断锚点是否还成立。
        整体成败写入 self._markets_stale（供 _build_market_pack 在包头标注时效性）：
          * 关闭旗标 / client 不可用 / 无行 / 异常 → 保留研究期快照并置 stale=True（degrade-safe）；
          * 每行局部失败由 requote_markets 自带 requote_failed 标记，不影响整体判定。
        返回（可能重报价后的）行列表，绝不抛异常。"""
        rows = [m for m in (markets or []) if isinstance(m, dict)]
        if not rows:
            self._markets_stale = False
            return rows
        if not getattr(Config, "PREDICTION_MARKETS_REQUOTE", True):
            self._markets_stale = True  # 关闭重报价 → 用研究期价（包头标注时效性）
            return rows
        try:
            from ..utils.prediction_markets import PolymarketClient
            client = PolymarketClient()
            if not client.enabled:
                self._markets_stale = True
                return rows
            requoted = client.requote_markets(rows)
            if not requoted:
                self._markets_stale = True
                return rows
            # 全部行都重报价失败（网络整体故障）→ 视作整体陈旧；否则至少部分拿到现价。
            self._markets_stale = all(m.get("requote_failed") for m in requoted)
            return requoted
        except Exception as e:  # noqa: BLE001 — 重报价为可选增强，失败保留研究期价并标注
            logger.warning(f"预测市场实时重报价失败（保留研究期价并标注时效性）: {e}")
            self._markets_stale = True
            return rows

    def _refresh_market_prices_for_extraction(self) -> None:
        """PM-3：二元预测抽取前对已缓存快照再重报价一次，使 market_anchor 用现价。

        就地更新 self._prediction_markets（供 extract_binary_forecasts 的 markets 回填/校验）
        与 self._market_pack（渲染的市场表，Δ 列随之刷新）。无缓存快照/未开旗标/失败 → 原样
        （degrade-safe，_requote_snapshot 内部已把整体成败写进 _markets_stale）。"""
        rows = getattr(self, "_prediction_markets", None)
        if not rows or not getattr(Config, "PREDICTION_MARKETS_ENABLED", True):
            return
        refreshed = self._requote_snapshot(rows)
        self._prediction_markets = refreshed
        try:
            self._market_pack = self._render_market_pack(refreshed)
        except Exception as e:  # noqa: BLE001 — 重渲染失败保留旧市场包
            logger.warning(f"重报价后市场包重渲染失败（保留旧市场包）: {e}")

    def _render_market_pack(self, markets: List[Dict[str, Any]]) -> str:
        """把规整化市场快照渲染为「预测市场信号包」（表 + 对照指令 + PM-3 时效性说明）。

        纯渲染（无网络/无 LLM）：PM-2 渲染行数 12→20；self._markets_stale 为真时在包头附一句
        「实时重报价未生效，价为研究期快照」的时效性说明。空/无表 → ""（注入自动跳过）。"""
        rows = [m for m in (markets or []) if isinstance(m, dict)]
        if not rows:
            return ""
        from ..utils.prediction_markets import render_markets_block
        lang = ("en" if str(getattr(self, "output_language", "") or "English")
                .lower().startswith("en") else "zh")
        table = render_markets_block(rows[:20], lang=lang)  # PM-2：渲染行数 12→20
        if not table:
            return ""
        header = (
            "【预测市场信号（Polymarket 实盘隐含概率·校准锚点，非真值）】\n"
            "以下为与本预测问题相关的真实预测市场当前定价（机器抓取）。撰写涉及概率的论断时"
            "须与之对照：与所列市场重叠的预测应引用其隐含概率，偏离超过 10 个百分点时须显式"
            "解释分歧依据（市场遗漏/错价了什么）。市场价格是聚合信念，不是事实真值。"
        )
        if getattr(self, "_markets_stale", False):
            header += (
                "\n（注：实时重报价未生效，以下为研究期快照价格，可能已随时间漂移；"
                "引用前请注意时效性。）")
        return header + "\n\n" + table

    def _build_market_pack(self) -> str:
        """组装「预测市场信号包」：市场隐含概率表 + 对照指令，钉进章节/骨架/二元预测提示词。

        计算一次后缓存市场快照于 self._prediction_markets（二元预测的 market_anchor 回填
        复用同一份快照）。PM-3：_load_prediction_markets 已对 handoff 快照做实时重报价并写
        _markets_stale。无数据/关闭旗标时返回 ""（注入自动跳过，行为与历史一致）。
        """
        if not getattr(Config, "PREDICTION_MARKETS_ENABLED", True):
            return ""
        markets = self._load_prediction_markets()
        if not markets:
            return ""
        self._prediction_markets = markets
        return self._render_market_pack(markets)

    def _build_causal_spine_block(self, max_chokepoints: int = 4, max_chars: int = 3200) -> str:
        """R2-KG-7: 确定性「因果骨架」块——以图谱中显著度最高的若干 chokepoint 为中心，渲染其
        多跳因果邻域，并追踪最强 source→outcome（前两位支点之间）传导路径，钉进信号包。

        支点取自研究 actors 的能动角色按显著度降序（与关系名册同源、确定性）。每个支点经
        zep_tools.trace_cascade(center=...) 取其因果邻域；再以前两位支点为 source/target 取
        二者间的有向因果路径——边的方向/符号/强度/时滞由 graph 层 runtime 投影 schema 渲染。

        Degrade-safe：无 actors / 无能动角色 / 遍历失败 / 无路径 → 返回 ""，信号包其余部分不受影响。
        仅在 REPORT_CAUSAL_SPINE 开启时由 _build_signal_pack 调用；多跳遍历在 graph 层有界。
        """
        try:
            from ..utils import actors as _actors
            rows = _actors.extract_actor_rows(self.actors)
        except Exception:  # noqa: BLE001
            return ""
        if not rows:
            return ""
        try:
            eligible = [r for r in rows if _actors.is_agent_eligible(r)]
            eligible.sort(key=lambda r: _actors.salience_score(r), reverse=True)
        except Exception:  # noqa: BLE001 — 排序/过滤失败时退回原始顺序
            eligible = rows
        centers: List[str] = []
        for r in eligible:
            nm = str((r or {}).get("name", "") or "").strip()
            if nm and nm not in centers:
                centers.append(nm)
            if len(centers) >= max_chokepoints:
                break
        if not centers:
            return ""
        segs: List[str] = []
        # 1) 各 chokepoint 的多跳因果邻域（"哪个节点一动就翻盘"的结构）
        for nm in centers:
            try:
                neigh = self.zep_tools.trace_cascade(self.graph_id, center=nm, causal_only=True)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"因果骨架 trace_cascade(center={nm}) 失败（忽略）: {e}")
                continue
            if neigh and not neigh.strip().startswith("（"):
                segs.append(neigh.strip())
        # 2) 最强 source→outcome 传导路径（前两位支点之间的有向因果链）
        if len(centers) >= 2:
            try:
                path = self.zep_tools.trace_cascade(
                    self.graph_id, source=centers[0], target=centers[1], causal_only=True
                )
                if path and not path.strip().startswith("（"):
                    segs.append(path.strip())
            except Exception as e:  # noqa: BLE001
                logger.warning(f"因果骨架 trace_cascade(source→target) 失败（忽略）: {e}")
        if not segs:
            return ""
        body = "\n\n".join(segs)
        if len(body) > max_chars:
            body = body[:max_chars].rstrip() + " …"
        header = (
            "【因果骨架（确定性·图谱多跳，chokepoint 为情景分叉支点）】\n"
            "以下为图谱中显著度最高节点的因果邻域与最强传导路径（边尽量标注方向/符号/强度/时滞），"
            "撰写时据此解释「哪个节点一动就翻盘」的级联机制，而非仅罗列声量数字。"
        )
        return header + "\n" + body

    # ──────────────────────────────────────────────────────────────
    # NEXTSTEPS P0-1 / P2-1 / P2-3: forecast spine + finalization + publish gate
    # ──────────────────────────────────────────────────────────────
    def _derive_and_pin_forecast_spine(self, report_id: str) -> None:
        """NEXTSTEPS P0-1: derive the structured forecast spine BEFORE section prose,
        persist forecast.json early, and pin a compact spine block into every section
        prompt so each section defends its assigned probabilities/resolution criteria.

        Degrade-safe: any failure leaves ``self._forecast_spine=None`` and the block
        empty, so sections behave exactly as the pre-spine path.
        """
        from . import forecast_extractor as _fe
        try:
            from ..utils import actors as _actors
            try:
                forecast_inputs = _actors.forecast_inputs_block(self.actors) or ""
            except Exception:  # noqa: BLE001 — forecast_inputs 为可选增强
                forecast_inputs = ""
            # Foglamp WP1 (1D, I-16/I-18)：预测骨架是概率权威。默认政策 diagnostic_only 下，
            # 模拟信号包（WorldState 份额、联盟结构、反事实差异等 elicited model projection）
            # **不得进入概率生成输入**——研究先验已经播种了 WorldState，再喂回骨架就是同一
            # 意见走两条路径被数成两份独立证据（circular corroboration）。仅
            # legacy_prompt（特征化 fixture 专用）保留旧行为，运行期显式告警。
            _sim_effect = str(getattr(Config, "SIMULATION_FORECAST_EFFECT", "diagnostic_only")
                              or "diagnostic_only").strip().lower()
            if _sim_effect == "legacy_prompt":
                logger.warning(
                    "SIMULATION_FORECAST_EFFECT=legacy_prompt：模拟信号包将直接进入概率生成"
                    "（仅限特征化 fixture；生产运行不得使用此政策）")
                signal_pack = self._signal_pack
                if not signal_pack:
                    try:
                        signal_pack = self._build_signal_pack()
                    except Exception:  # noqa: BLE001
                        signal_pack = ""
            else:
                signal_pack = ""
            # 预测市场信号包：优先复用已构建的（generate_report 已先构建），否则为骨架
            # 单独构建一次（现抓/读 handoff 皆 degrade-safe，失败为空串 → 提示词不变）。
            market_pack = getattr(self, "_market_pack", "")
            if not market_pack and getattr(Config, "PREDICTION_MARKETS_ENABLED", True):
                try:
                    market_pack = self._build_market_pack()
                except Exception:  # noqa: BLE001
                    market_pack = ""
            horizon = ""
            if isinstance(self.actors, dict):
                horizon = str(self.actors.get("as_of_date", "") or "")
            # Spine 修复（spec §4）：日历模式下预测期限应是 temporal_config/轨迹的
            # horizon_date（判定日），而非 as_of_date（那是"现在"）；hours 模式保持旧行为。
            _hz = self._temporal_horizon_date()
            if _hz:
                horizon = _hz
            spine = _fe.derive_forecast_spine(
                self.llm,
                central_question=self.simulation_requirement or "",
                horizon=horizon,
                situation_brief=self.situation_brief or None,
                forecast_inputs=forecast_inputs,
                signal_pack=signal_pack,
                market_block=market_pack,
            )
            if not spine or not spine.get("scenarios"):
                logger.info("预测骨架推导未产出情景，跳过（回退为成稿后抽取）")
                return
            # RPT-3（REPORT_CRITIQUE_BEFORE_PROSE，默认开）：红队自校准 + 事前验尸挪到
            # 叙事之前——此前批判发生在全部正文写完之后，正文（连章节标题里的百分比）
            # 捍卫的是 4 情景 39/23/19/19，而 forecast.json 交付的是批判后的 5 情景
            # 34/22/16/14/14，按构造必然矛盾（S11 只能事后打标）。前置后，钉进各章
            # 提示词的骨架与最终 forecast.json 按构造一致。critiqued 标记数据驱动，
            # _finalize 据此跳过二次批判（premortem 内部自带 REPORT_PREMORTEM 门）。
            if (getattr(Config, "REPORT_CRITIQUE_BEFORE_PROSE", True)
                    and getattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False)):
                try:
                    _critiqued = _fe.self_critique_forecast(spine, self.llm)
                    _critiqued = _fe.premortem_forecast(_critiqued, self.llm)
                    if _critiqued.get("scenarios"):
                        spine = _critiqued
                        logger.info(
                            f"预测骨架已先于叙事完成红队自校准（{len(spine['scenarios'])} 情景）"
                        )
                except Exception as _ce:  # noqa: BLE001 — 批判失败沿用未批判骨架
                    logger.warning(f"骨架前置自校准失败（忽略）: {_ce}")
            self._forecast_spine = spine
            self._forecast_spine_block = _fe.render_forecast_spine_block(spine)
            # 早落 forecast.json（骨架版）；成稿后由 _finalize_structured_forecast 补
            # citation_audit / 自校准 / 发布门后覆盖。
            try:
                fpath = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
                write_text_atomic(fpath, json.dumps(spine, ensure_ascii=False, indent=2))
            except Exception as _pe:  # noqa: BLE001 — 早落失败不影响主流程
                logger.warning(f"预测骨架早落 forecast.json 失败（忽略）: {_pe}")
            logger.info(
                f"已先于叙事推导预测骨架: {report_id} "
                f"（{len(spine.get('scenarios', []))} 情景, 信心 {spine.get('confidence')}）"
            )
        except Exception as _se:  # noqa: BLE001 — 骨架为可选增强，失败回退旧路径
            logger.warning(f"预测骨架推导失败（忽略，回退成稿后抽取）: {_se}")
            self._forecast_spine = None
            self._forecast_spine_block = ""

    def _finalize_structured_forecast(self, report_id: str, report_markdown: str,
                                      report: Optional["Report"] = None) -> None:
        """Persist the final forecast.json.

        Prefers the pre-derived spine (P0-1, already MECE & signal-seeded); else
        extracts post-hoc from prose (legacy path). Then optional red-team self-critique
        (P2-1), citation-grounding audit, and the publish gate (P2-3). Caller wraps in
        try/except → degrade-safe.

        RQ-2：审计跑完后（发布门之前），若开启 REPORT_REPAIR_PASSES 且某维度失败，按维度做
        一次定向修复（引用回填 / 引文接地 / 占位符解析），重跑受影响审计一次，把 before/after
        合并进 forecast['quality']['repair']。拿到 ``report`` 对象时把修复后的 markdown 回写
        report.markdown_content 与 full_report.md（供下游 Part-1/三部/判定章节接续）；缺省 None
        时仅记录（degrade-safe，兼容既有仅传 report_id/markdown 的调用方与测试）。
        """
        from .forecast_extractor import (
            extract_structured_forecast, audit_citation_grounding, self_critique_forecast,
        )
        if self._forecast_spine and self._forecast_spine.get("scenarios"):
            forecast = dict(self._forecast_spine)        # 骨架已由信号驱动且 MECE
        else:
            forecast = extract_structured_forecast(
                report_markdown, self.llm,
                situation_brief=getattr(self, "situation_brief", None),
            )
        # RPT-3: 骨架已在叙事前完成批判（critiqued=True，数据驱动判断）时不再二次批判——
        # 成稿后再动概率会让正文与 forecast.json 按构造矛盾。非骨架路径（成稿后抽取，
        # 如骨架推导失败的 91f5 型运行）保留原有的成稿后批判。
        if (getattr(Config, "REPORT_FORECAST_SELF_CRITIQUE", False)
                and not forecast.get("critiqued")):
            forecast = self_critique_forecast(forecast, self.llm)
        # XRUN-16(1): 骨架情景数与最终情景数漂移检测（正文按骨架 N 情景撰写、交付却是
        # M 情景 ⇒ 必然矛盾）；随 forecast.json quality 落盘供健康门消费。
        try:
            _pin_n = len((self._forecast_spine or {}).get("scenarios") or [])
            _fin_n = len(forecast.get("scenarios") or [])
            if _pin_n and _fin_n and _pin_n != _fin_n:
                forecast.setdefault("quality", {})["scenario_count_drift"] = {
                    "pinned": _pin_n, "final": _fin_n}
                logger.warning(f"情景数漂移：骨架 {_pin_n} 情景 → 最终 {_fin_n} 情景（正文与交付可能矛盾）")
        except Exception:  # noqa: BLE001
            pass
        # WAVE10（无缝引用）：传入记号→来源映射 ⇒ 审计额外报告 resolved_cited /
        # resolved_coverage（仅可解析记号计入的严格口径，独立观测指标；发布门仍读 coverage）。
        forecast["citation_audit"] = audit_citation_grounding(
            report_markdown, index_map=getattr(self, "_citation_index", None))
        # QUALITY-OPT S2: flag quotes presented as real but neither labeled simulation nor found
        # in the research material (laundered sim/graph text or fabrication). Observability →
        # forecast.quality.quote_provenance; loud warning when any are found.
        try:
            _qp = self._audit_quote_provenance(report_markdown)
            if _qp:
                forecast.setdefault("quality", {})["quote_provenance"] = _qp
                if _qp.get("ungrounded"):
                    logger.warning(
                        f"引用接地审计：{_qp['ungrounded']}/{_qp['total_quotes']} 条引用未标注为模拟"
                        f"且未在研究材料中匹配（疑似嫁接/捏造）: {_qp.get('examples', [])[:2]}")
                # RPT-5: 带 [S#] 来源但非逐字的引文单独告警（缺陷但非捏造，不入发布门）。
                if _qp.get("cited_unverbatim"):
                    logger.warning(
                        f"引用接地审计：{_qp['cited_unverbatim']}/{_qp['total_quotes']} 条引用带 [S#] "
                        f"来源但疑似非逐字引用: {_qp.get('unverbatim_examples', [])[:2]}")
        except Exception:  # noqa: BLE001
            pass
        # QUALITY-OPT S11: flag prose scenario-probabilities that disagree with forecast.json.
        try:
            _nc = self._audit_numeric_consistency(report_markdown, forecast)
            if _nc.get("mismatch_count"):
                forecast.setdefault("quality", {})["numeric_consistency"] = _nc
                logger.warning(f"概率一致性审计：{_nc['mismatch_count']} 处正文概率与 forecast.json 不符: "
                               f"{_nc.get('scenario_prob_mismatches', [])[:3]}")
        except Exception:  # noqa: BLE001
            pass
        # QUALITY-OPT S12: flag implausible headline growth stats (>100% YoY) that anchor reports.
        try:
            _sp = self._audit_stat_plausibility(report_markdown)
            if _sp.get("count"):
                forecast.setdefault("quality", {})["implausible_stats"] = _sp
                logger.warning(f"统计合理性审计：{_sp['count']} 处疑似不合理的极端增长率: "
                               f"{_sp.get('implausible_stats', [])[:3]}")
        except Exception:  # noqa: BLE001
            pass
        # QUALITY-OPT A1: emit >=N INDEPENDENT binary (yes/no) forecasts — the brief's headline
        # deliverable — ALONGSIDE the scenario spine. The research dossier usually already holds a
        # compliant F1..Fn table; we extract it (preserving its probabilities) and top up to the
        # minimum, with a conviction+objectivity scorecard. Language follows the report so the two
        # views stay consistent. Additive + degrade-safe: failure leaves the scenario forecast intact.
        if getattr(Config, "FORECAST_EMIT_BINARY", True):
            try:
                from .forecast_extractor import (
                    _binary_quality as _binary_quality_score,
                    apply_horizon_consistency as _apply_horizon_consistency,
                    extract_binary_forecasts as _ebf,
                    reconcile_forecast_contract as _reconcile_forecast_contract,
                )
                _lang = (getattr(self, "output_language", None)
                         or getattr(Config, "DEERFLOW_RESEARCH_LANGUAGE", None) or "English")
                _bsrc = self.research_report or report_markdown or ""
                # RPT-6: 主题从配置/需求书派生，不再由抽取器硬编码 Bridgewater 三元组。
                _themes = getattr(Config, "FORECAST_BINARY_THEMES", None)
                if isinstance(_themes, str):
                    _themes = [t.strip().lower() for t in _themes.split(",") if t.strip()]
                if not _themes:
                    try:
                        from .requirement_spec import parse_requirement_spec
                        _themes = parse_requirement_spec(
                            self.simulation_requirement, self.research_report
                        ).get("themes") or None
                    except Exception:  # noqa: BLE001 — 主题派生失败退回主题无关措辞
                        _themes = None
                # XRUN-1(b): 注入模拟量化信号包（缺失时为骨架单独构建一次），让 Part-1 概率
                # 对模拟敏感——两次不同模拟产出逐字节相同的概率向量即证明此前模拟被完全忽略。
                _sig = self._signal_pack
                if not _sig and getattr(Config, "FORECAST_SIM_SENSITIVITY", True):
                    try:
                        _sig = self._build_signal_pack()
                    except Exception:  # noqa: BLE001
                        _sig = ""
                # PM-3：二元预测抽取前对已缓存快照再重报价一次，使 market_anchor 用现价
                # （报告成稿到抽取之间市场会漂移）。就地刷新 _prediction_markets + _market_pack；
                # 无缓存/未开/失败 → 原样（degrade-safe，_refresh_market_prices_for_extraction 内部兜底）。
                try:
                    self._refresh_market_prices_for_extraction()
                except Exception:  # noqa: BLE001 — 重报价为增强，失败沿用旧快照
                    pass
                # 预测市场：市场表注入抽取提示词（重叠预测须引用隐含概率并解释 >10pt 分歧），
                # 规整化快照回填 market_anchor 的隐含概率。缺失时构建一次；失败为空（degrade-safe）。
                _mkt = getattr(self, "_market_pack", "")
                if not _mkt and getattr(Config, "PREDICTION_MARKETS_ENABLED", True):
                    try:
                        _mkt = self._build_market_pack()
                    except Exception:  # noqa: BLE001
                        _mkt = ""
                # CAL-TEMPORAL：把日历模式抽取出的真实判定日 horizon_date 接入二元预测抽取，
                # 让结算年份提示对齐预测期（否则提示词硬编码 2027，多年期日历运行下 Part-1
                # 二元预测会静默结算到 2027，与情景骨架/图表的日历判定日不一致）。hours 模式
                # _temporal_horizon_date() 返回 ""，传 None ⇒ 旧行为逐字节不变（degrade-safe）。
                _hz_date = self._temporal_horizon_date() or None
                # B2: 需求书解析出的 binary_min_count 参与生效——取 spec 与 Config 的较大者
                # （需求书写明「15+ binary forecasts」时不被 Config 默认静默压低）。
                _bres = _ebf(
                    _bsrc, self.llm,
                    min_count=self._binary_min_count(),
                    language=_lang,
                    situation_brief=getattr(self, "situation_brief", None),
                    themes=_themes,
                    signal_pack=_sig or None,
                    market_pack=_mkt or None,
                    markets=getattr(self, "_prediction_markets", None) or None,
                    scenarios=forecast.get("scenarios") or None,
                    horizon_date=_hz_date,
                )
                if _bres.get("binary_forecasts"):
                    forecast["binary_forecasts"] = _bres["binary_forecasts"]
                    forecast["binary_quality"] = _bres.get("binary_quality") or {}
                    _contract = _reconcile_forecast_contract(forecast)
                    _quality = _binary_quality_score(
                        forecast["binary_forecasts"],
                        min_count=self._binary_min_count(),
                        themes_expected=_themes,
                    )
                    _quality["proposition_consistency"] = _contract
                    forecast["binary_quality"] = _quality
                    # RQ-6：校验二元预测结算年份与真实判定期一致——目标年份集合（需求书 +
                    # 日历 horizon_date.year）与二元结算年份集合非空且无交集时，把
                    # quality["horizon_mismatch"] 合并进 forecast（供发布门降信心）。日历
                    # horizon 缺失（hours 模式）时 horizon_date=None，退回仅按需求书校验，
                    # 行为不变（degrade-safe，绝不覆盖既有 quality 键）。
                    try:
                        _apply_horizon_consistency(
                            forecast, getattr(self, "simulation_requirement", None),
                            horizon_date=_hz_date)
                    except Exception:  # noqa: BLE001 — 观测性校验，绝不影响产物
                        pass
                    # PM-2：确定性市场对照负载（预测 vs 市场隐含概率、|Δ|、>10pp 判定）——嵌入
                    # forecast.json 并独立落 market_comparison.json，供 Part-1 后的「Market Cross-Check」
                    # 渲染块与下游消费。无锚定预测时不写（degrade-safe）。
                    _mc = forecast.get("market_comparison")
                    if isinstance(_mc, dict) and _mc.get("comparisons"):
                        forecast["market_comparison"] = _mc
                        try:
                            _mcpath = os.path.join(
                                ReportManager._get_report_folder(report_id),
                                "market_comparison.json")
                            write_text_atomic(
                                _mcpath, json.dumps(_mc, ensure_ascii=False, indent=2))
                        except Exception as _mce:  # noqa: BLE001 — 落盘失败不影响主流程
                            logger.warning(f"落 market_comparison.json 失败（忽略）: {_mce}")
                    # XRUN-1(c): 与同图谱、不同模拟的上一份报告比对概率向量——
                    # 若逐项 |Δ|≤0.01 完全一致，则预测对模拟不敏感，记入 quality。
                    try:
                        _dup = self._check_binary_sim_sensitivity(report_id, forecast)
                        if _dup:
                            forecast.setdefault("quality", {})["sim_insensitivity"] = _dup
                            logger.warning(
                                f"二元预测对模拟不敏感：概率向量与报告 {_dup.get('other_report_id')} "
                                f"完全一致（不同 simulation_id）")
                    except Exception:  # noqa: BLE001 — 观测性检查，绝不影响产物
                        pass
            except Exception as _be:  # noqa: BLE001 — additive; never break finalization
                logger.warning(f"二元预测抽取失败（忽略，不影响情景预测）: {_be}")
        # RQ-2：质量门失败 → 按维度单次定向修复（引用回填 / 引文接地 / 占位符解析），
        # 重跑受影响审计一次并把 before/after 记进 forecast['quality']['repair']（合并，不覆盖）。
        # 置于发布门之前 ⇒ 发布门只对修复后的审计结果打分一次，避免二次降级。任何失败仅告警。
        if getattr(Config, "REPORT_REPAIR_PASSES", True):
            try:
                report_markdown = self._run_repair_passes(
                    report_id, forecast, report_markdown, report)
            except Exception as _rpe:  # noqa: BLE001 — 修复为旁路品控，失败不影响产物
                logger.warning(f"报告修复 passes 失败（忽略，不影响产物）: {_rpe}")
        # The authoritative publish gate runs only after every report mutation,
        # including citation finalization.  At this point the Markdown is still a
        # draft: binary tables, visual placement, the three-part skeleton,
        # resolution criteria, language repair, editorial lint, and References can
        # all change it below.  Applying the gate here made its citation/quality
        # fields stale by construction and could demote confidence twice.
        # P2-2: 把观察指标随 forecast.json 落盘（供解析调度器对照判别情景）。
        try:
            from ..utils import actors as _actors
            _inds = _actors.extract_forecast_inputs(self.actors).get("indicators") or []
            if _inds:
                forecast["indicators"] = _inds
        except Exception:  # noqa: BLE001
            pass
        # NEXTSTEPS P2-4: 把历史校准（已解析预测的 Brier/ECE）surfacing 进 confidence_rationale，
        # 让信心由 track record 赚得而非自评；无已解析样本时不改（degrade-safe）。
        if getattr(Config, "REPORT_FORECAST_LEDGER", True):
            try:
                from .forecast_ledger import calibration_summary as _cal
                _cs = _cal()
                if _cs.get("n_resolved"):
                    forecast["historical_calibration"] = _cs
                    _note = (f"历史校准：已解析 {_cs['n_resolved']} 个预测，平均 Brier "
                             f"{_cs.get('mean_brier')}，校准误差 {_cs.get('calibration_error')}")
                    forecast["confidence_rationale"] = (
                        (str(forecast.get("confidence_rationale") or "").strip()
                         + " ｜" + _note).strip(" ｜"))
            except Exception:  # noqa: BLE001
                pass
        fpath = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
        write_text_atomic(fpath, json.dumps(forecast, ensure_ascii=False, indent=2))
        self._forecast_spine = forecast  # 最终版（集成阶段读 forecast.json 文件，这里仅保留内存副本）
        # P2-4: 追加进校准账本（loop-closer；resolution 经 /api/v1/resolve 或 forecast_tools backtest）。
        # EVAL-1: 仅 FORECAST_LEDGER_COMMIT_MODE=legacy 在此（终审之前）追加；默认 published 模式
        # 由 generate_report 在终审封印 + 落盘之后经 _commit_forecast_ledger 提交封印字节。
        if getattr(Config, "REPORT_FORECAST_LEDGER", True):
            try:
                from .forecast_ledger import append_forecast as _append
                from .ledger_commit import commit_mode as _ledger_commit_mode
                if _ledger_commit_mode() == "legacy":
                    _append(forecast, report_id=report_id,
                            horizon=str(forecast.get("horizon") or "") or None,
                            created_at=datetime.now().isoformat())
            except Exception:  # noqa: BLE001
                pass
        logger.info(
            f"结构化预测已生成: {report_id} "
            f"({len(forecast.get('scenarios', []))} 情景, "
            f"引用覆盖 {forecast['citation_audit'].get('coverage')}, "
            f"信心 {forecast.get('confidence')})"
        )

    # RQ-2：字面占位符引用记号（研究/撰写阶段留下的未解析槽位，如 [S?-a] / 【S?】 / [S#]）。
    # 与真正的 [S1]/[S2] 引用（_CITATION_RE 只认 S\d+）不同——这些永远不是有效引用，必须解析或删除。
    _PLACEHOLDER_TOKEN_RE = re.compile(r"[\[【]\s*S(?:\?|#)(?:-[A-Za-z0-9]+)?\s*[\]】]")

    def _run_repair_passes(self, report_id: str, forecast: Dict[str, Any],
                           report_markdown: str,
                           report: Optional["Report"] = None) -> str:
        """RQ-2：质量门失败时按维度做一次定向修复，重跑受影响审计一次并记录 before/after。

        触发维度（各自独立判定，仅修失败的那些）：
          * citation_backfill —— citation_audit.coverage < 发布门阈值（且确有定量声明）；
          * quote_grounding  —— quality.quote_provenance.ungrounded > 0；
          * placeholder      —— 正文含字面占位符记号（_PLACEHOLDER_TOKEN_RE）。
        修复后若 markdown 变化：重跑 citation/quote/S11/S12 审计覆盖旧值，并把 before/after
        合并进 forecast['quality']['repair']（never overwrite 其余 quality 键）。拿到 report
        对象时回写 report.markdown_content 与 full_report.md。返回（可能被修复的）markdown。"""
        from .forecast_extractor import audit_citation_grounding as _acg
        md = report_markdown or ""
        _q0 = forecast.get("quality")
        quality = dict(_q0) if isinstance(_q0, dict) else {}
        citation_audit = forecast.get("citation_audit") or {}
        try:
            min_cov = float(getattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5) or 0.0)
        except (TypeError, ValueError):
            min_cov = 0.5
        cov = float(citation_audit.get("coverage", 1.0) or 0.0)
        has_quant = int(citation_audit.get("quantitative_claims", 0) or 0) > 0
        qp = quality.get("quote_provenance") or {}
        ungrounded0 = int(qp.get("ungrounded", 0) or 0)
        placeholder0 = len(self._PLACEHOLDER_TOKEN_RE.findall(md))
        # WAVE9：模拟机制泄漏计数（Tier-1 机器语法 + Tier-2 泄漏模式）——命中即触发泄漏修复。
        simleak0 = 0
        if getattr(Config, "REPORT_SIMLEAK_REPAIR", True):
            try:
                from . import report_lint as _rl
                simleak0 = len(_rl.leakage_hits(md))
            except Exception as _sle:  # noqa: BLE001 — 计数失败视作无泄漏（不触发）
                logger.warning(f"泄漏计数失败（跳过泄漏修复）: {_sle}")
                simleak0 = 0
        # WAVE10（无缝引用）：悬空记号计数——正文里无法在注入索引解析的 [S246] 型记号。
        # 无索引映射（旧运行/离线测试经 __new__ 构造）时回退全量位置映射兜底。
        dangling0: List[str] = []
        if getattr(Config, "REPORT_CITATION_REPAIR", True):
            try:
                from .forecast_extractor import validate_citation_markers as _vcm
                dangling0 = _vcm(md, self._citation_index_or_fallback())["dangling"]
            except Exception as _dce:  # noqa: BLE001 — 计数失败视作无悬空（不触发）
                logger.warning(f"悬空引用计数失败（跳过悬空修复）: {_dce}")
                dangling0 = []

        need_citation = has_quant and cov < min_cov
        need_quote = ungrounded0 > 0
        need_placeholder = placeholder0 > 0
        need_simleak = simleak0 > 0
        need_dangling = len(dangling0) > 0
        if not (need_citation or need_quote or need_placeholder or need_simleak
                or need_dangling):
            return md

        before = {"citation_coverage": round(cov, 3),
                  "quote_ungrounded": ungrounded0,
                  "placeholder_tokens": placeholder0,
                  "sim_leakage_hits": simleak0,
                  "dangling_citations": len(dangling0)}
        passes: List[Dict[str, Any]] = []
        new_md = md
        # 泄漏修复放最前：标签先转写为白名单规范，后续引文接地修复才不会误删合法推演引文。
        if need_simleak:
            try:
                new_md, _sl_info = self._repair_simulation_leakage(new_md)
                passes.append({"dimension": "simulation_leakage", **_sl_info})
            except Exception as _sre:  # noqa: BLE001 — 泄漏修复失败不阻断其余维度
                logger.warning(f"模拟泄漏修复失败（忽略，继续其余修复）: {_sre}")
        if need_citation:
            new_md, n = self._repair_citation_backfill(new_md)
            passes.append({"dimension": "citation_backfill", "citations_inserted": n})
        if need_quote:
            new_md, n = self._repair_quote_grounding(new_md)
            passes.append({"dimension": "quote_grounding", "quotes_removed": n})
        if need_placeholder:
            new_md, n = self._repair_placeholder_tokens(new_md)
            passes.append({"dimension": "placeholder_resolution", "tokens_resolved": n})
        if need_dangling:
            try:
                new_md, _dg_info = self._repair_dangling_citations(new_md, dangling0)
                passes.append({"dimension": "citation_dangling", **_dg_info})
            except Exception as _dre:  # noqa: BLE001 — 悬空修复失败不阻断其余维度
                logger.warning(f"悬空引用修复失败（忽略，保留原记号）: {_dre}")

        # 悬空修复可能只是把记号登记进索引（kept_verified，markdown 不变）——此时审计
        # 口径已变（resolved 指标），仍需重跑审计而非走 no-op 分支。
        _index_registered = any(
            p.get("dimension") == "citation_dangling" and p.get("kept_verified")
            for p in passes)
        if new_md == md and not _index_registered:
            # 命中维度但无处可修（如无匹配来源）——仍记录，before==after，不动 markdown。
            quality["repair"] = {"applied": False, "passes": passes,
                                 "before": before, "after": before}
            forecast["quality"] = quality
            return md

        # 重跑受影响审计一次（覆盖旧值，让发布门对修复后的状态打分）。
        new_ca = _acg(new_md, index_map=getattr(self, "_citation_index", None))
        forecast["citation_audit"] = new_ca
        try:
            _qp2 = self._audit_quote_provenance(new_md)
            quality["quote_provenance"] = _qp2 or {"total_quotes": 0, "ungrounded": 0,
                                                   "examples": []}
        except Exception:  # noqa: BLE001
            pass
        try:
            _nc2 = self._audit_numeric_consistency(new_md, forecast)
            if _nc2.get("mismatch_count"):
                quality["numeric_consistency"] = _nc2
        except Exception:  # noqa: BLE001
            pass
        try:
            _sp2 = self._audit_stat_plausibility(new_md)
            if _sp2.get("count"):
                quality["implausible_stats"] = _sp2
        except Exception:  # noqa: BLE001
            pass
        simleak_after = simleak0
        if need_simleak:
            try:
                from . import report_lint as _rl
                simleak_after = len(_rl.leakage_hits(new_md))
            except Exception:  # noqa: BLE001
                pass
            quality["sim_leakage"] = {"before": simleak0, "after": simleak_after}
        dangling_after = len(dangling0)
        if need_dangling:
            try:
                from .forecast_extractor import validate_citation_markers as _vcm2
                dangling_after = len(
                    _vcm2(new_md, self._citation_index_or_fallback())["dangling"])
            except Exception:  # noqa: BLE001
                pass
        after = {
            "citation_coverage": round(float(new_ca.get("coverage", cov) or 0.0), 3),
            "quote_ungrounded": int((quality.get("quote_provenance") or {}).get("ungrounded", 0) or 0),
            "placeholder_tokens": len(self._PLACEHOLDER_TOKEN_RE.findall(new_md)),
            "sim_leakage_hits": simleak_after,
            "dangling_citations": dangling_after,
        }
        quality["repair"] = {"applied": True, "passes": passes,
                             "before": before, "after": after}
        forecast["quality"] = quality
        # 回写修复后的 markdown（仅在拿到 report 对象时；否则仅记录，degrade-safe）。
        if report is not None:
            report.markdown_content = new_md
            try:
                folder = ReportManager._get_report_folder(report_id)
                write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
            except Exception as _we:  # noqa: BLE001
                logger.warning(f"回写修复后 full_report.md 失败（忽略）: {_we}")
        logger.info(
            f"报告修复 passes: {report_id} 引用覆盖 {before['citation_coverage']}→"
            f"{after['citation_coverage']}，未接地引用 {before['quote_ungrounded']}→"
            f"{after['quote_ungrounded']}，占位符 {before['placeholder_tokens']}→"
            f"{after['placeholder_tokens']}，悬空引用 {before['dangling_citations']}→"
            f"{after['dangling_citations']}"
        )
        return new_md

    def _source_haystacks(self) -> List[Tuple[str, str]]:
        """把 self.sources 渲染成 [(tag, 归一化底料)] 供引用回填匹配。tag 用位置式 [S{i}]
        （与 _CITATION_RE 认可的 S\\d+ 形式一致，回填后必被引用审计计入）；底料为该来源所有
        字符串字段（title/url/snippet/content/summary…）拼接后归一化。空来源返回 []。"""
        out: List[Tuple[str, str]] = []
        for i, s in enumerate(self.sources or [], 1):
            if not _citation_source_admissible(s):
                continue
            vals: List[str] = []
            for value in s.values():
                if isinstance(value, (str, int, float)):
                    vals.append(str(value))
                elif isinstance(value, (list, dict)):
                    vals.append(json.dumps(value, ensure_ascii=False))
            hay = self._norm_quote_text(" ".join(vals))
            if hay:
                out.append((f"[S{i}]", hay))
        return out

    _CITATION_MATCH_STOPWORDS = {
        "about", "above", "after", "again", "against", "among", "because", "before",
        "below", "between", "could", "during", "evidence", "forecast", "from", "have",
        "into", "line", "more", "most", "other", "over", "report", "than", "that",
        "their", "there", "these", "this", "through", "under", "using", "were", "which",
        "while", "with", "would", "year",
    }

    @classmethod
    def _best_source_tag_for_line(
            cls, line: str, haystacks: List[Tuple[str, str]]) -> str:
        """Return one uniquely supported source tag for a quantitative line.

        A candidate must match a discriminative numeric token (calendar years
        alone never qualify) and at least two non-generic lexical anchors. If
        multiple sources tie for best evidence, return empty rather than attach
        an arbitrary citation.
        """
        bare = cls._FULL_S_TAG_RE.sub(" ", str(line or ""))
        numeric: List[Tuple[str, bool]] = []
        for match in re.finditer(
            r"(?<![A-Za-z0-9_.])(\d+(?:\.\d+)?)(\s*%)?",
            bare,
        ):
            number = match.group(1)
            is_percent = bool(match.group(2))
            try:
                as_float = float(number)
            except ValueError:
                continue
            if not is_percent and as_float.is_integer() and 1900 <= as_float <= 2100:
                continue
            if not is_percent and len(number.replace(".", "")) < 2:
                continue
            numeric.append((number, is_percent))
        if not numeric:
            return ""

        lexical = {
            (token[:-1] if token.endswith("s") and len(token) > 5 else token)
            for token in re.findall(r"[a-z][a-z0-9_-]{3,}", bare.lower())
            if token not in cls._CITATION_MATCH_STOPWORDS
        }
        if len(lexical) < 2:
            return ""

        candidates: List[Tuple[int, str]] = []
        for tag, hay in haystacks:
            anchor_hits = 0
            for number, is_percent in numeric:
                suffix = r"\s*%" if is_percent else ""
                if re.search(r"(?<![\d.])" + re.escape(number) + suffix + r"(?![\d.])", hay):
                    anchor_hits += 1
            if not anchor_hits:
                continue
            lexical_hits = sum(
                1 for token in lexical
                if re.search(r"(?<![a-z0-9])" + re.escape(token) + r"(?:s)?(?![a-z0-9])", hay)
            )
            if lexical_hits < 2:
                continue
            candidates.append((anchor_hits * 4 + lexical_hits, tag))
        if not candidates:
            return ""
        candidates.sort(key=lambda item: (-item[0], item[1]))
        if len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
            return ""
        return candidates[0][1]

    def _repair_citation_backfill(self, md: str) -> Tuple[str, int]:
        """RQ-2 引用回填：仅在数字 + 至少两个词汇锚点唯一指向同一来源时追加 [S{i}]。

        Calendar years never qualify by themselves, ambiguous ties remain
        uncited, and each line receives at most one marker. This deliberately
        prefers a visible coverage gap over a seamless but false attribution.
        """
        haystacks = self._source_haystacks()
        if not haystacks:
            return md, 0
        inserted = 0
        out_lines: List[str] = []
        for ln in md.splitlines():
            stripped = ln.strip()
            # 跳过标题 / 引用块 / 已带任意 [S…] 记号。
            if (not stripped or stripped.startswith("#") or stripped.startswith(">")
                    or self._ANY_S_TAG_RE.search(ln)):
                out_lines.append(ln)
                continue
            matched_tag = self._best_source_tag_for_line(stripped, haystacks)
            if matched_tag:
                out_lines.append(ln.rstrip() + " " + matched_tag)
                inserted += 1
            else:
                out_lines.append(ln)
        if not inserted:
            return md, 0
        return "\n".join(out_lines), inserted

    def _repair_final_quantitative_grounding(
        self, md: str
    ) -> Tuple[str, Dict[str, Any]]:
        """Remove unsupported numeric claims after all report-shape rewrites.

        The publication gate measures the exact final bytes.  Part-2 synthesis,
        visualization placement, and resolution-section insertion happen after
        the earlier draft repair, so a draft can appear well cited and then ship
        mostly uncited numbers.  This bounded deterministic pass runs only at the
        final mutable stage:

        * authored Part-1 forecasts and resolution criteria are preserved and
          reported separately from *external-source* citation coverage;
        * an uncited numeric sentence gets a marker only when the persisted source
          spans pass the same semantic-support predicate as the final audit;
        * otherwise a deterministically unsupported numeric sentence/table-cell
          fragment is removed rather than receiving a guessed citation or
          surviving as false precision; unverifiable fragments remain visible
          and keep the unchanged gate failed.

        Non-numeric analysis is retained.  The following citation finalizer and
        read-only audit remain authoritative.
        """
        from .forecast_extractor import (
            BINARY_FORECAST_END_MARKER,
            BINARY_FORECAST_START_MARKER,
            _CITATION_RE as _source_citation_re,
            _NUMBER_RE as _number_re,
            audit_citation_grounding as _audit_grounding,
            authored_forecast_markers_balanced as _authored_markers_balanced,
            format_markdown_table_row as _format_table_row,
            is_authored_forecast_heading as _is_authored_heading,
            is_markdown_table_delimiter as _is_table_delimiter,
            is_markdown_table_header as _is_table_header,
            markdown_fence_transition as _fence_transition,
            markdown_table_claim_context as _table_claim_context,
            markdown_table_cells as _table_cells,
            split_markdown_claim_units as _claim_units,
        )

        text = str(md or "")
        index_map = self._citation_index_or_fallback()

        def _audit_external_claims(value: str) -> Dict[str, Any]:
            body = "\n".join(
                chunk for chunk in self._split_markdown_h2_sections(value)
                if chunk.split("\n", 1)[0].strip() not in _REFS_HEADINGS
            )
            return _audit_grounding(
                body,
                index_map=self._citation_index_or_fallback(),
                exclude_authored_forecasts=True,
            )

        before = _audit_external_claims(text)
        try:
            threshold = float(
                getattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5) or 0.0
            )
        except (TypeError, ValueError):
            threshold = 0.5
        coverage = float(before.get("resolved_coverage", 1.0) or 0.0)
        if coverage >= threshold:
            return text, {
                "applied": False,
                "before": before,
                "after": before,
                "citations_added": 0,
                "sentences_removed": 0,
                "table_rows_removed": 0,
                "table_cells_cleared": 0,
                "unverifiable_claims_preserved": 0,
                "market_claims_preserved": 0,
                "passed": True,
            }

        out_lines: List[str] = []
        in_authored_block = False
        in_authored_section = False
        in_references = False
        fence_state = None
        active_table_headers: List[str] = []
        citations_added = 0
        sentences_removed = 0
        table_rows_removed = 0
        table_cells_cleared = 0
        unverifiable_claims_preserved = 0
        market_claims_preserved = 0

        lines = text.split("\n")
        authored_markers_valid = _authored_markers_balanced(lines)

        def _repair_fragments(
            surface: str,
            *,
            semantic_context: str = "",
        ) -> Tuple[str, bool]:
            nonlocal citations_added
            nonlocal sentences_removed
            nonlocal unverifiable_claims_preserved
            nonlocal market_claims_preserved
            fragments = _claim_units(surface)
            if not fragments:
                return surface, False
            kept: List[str] = []
            removed_numeric = False
            for fragment in fragments:
                if not _number_re.search(fragment):
                    kept.append(fragment)
                    continue
                if _source_citation_re.search(fragment):
                    kept.append(fragment)
                    continue
                claim_for_support = " ".join(
                    part for part in (semantic_context.strip(), fragment) if part
                )
                tag, status = self._quantitative_semantic_decision(
                    claim_for_support
                )
                if tag:
                    kept.append(fragment.rstrip() + f" [{tag}]")
                    citations_added += 1
                elif status == "market_supported":
                    # i7：市场语境 + 快照价精确命中 ⇒ 机器抓取的真价，保留原句、
                    # 不发明 [S#]（快照不是编号来源）。历史事故：真实 Polymarket 价
                    # 在此被当 fabrication 删除。
                    kept.append(fragment)
                    market_claims_preserved += 1
                elif status == "unverifiable":
                    kept.append(fragment)
                    unverifiable_claims_preserved += 1
                else:
                    sentences_removed += 1
                    removed_numeric = True
            return " ".join(kept), removed_numeric

        for line_index, line in enumerate(lines):
            stripped = line.strip()
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = _fence_transition(line, fence_state)
            if is_fence_line:
                out_lines.append(line)
                continue
            if was_in_fence:
                out_lines.append(line)
                continue
            if stripped == BINARY_FORECAST_START_MARKER:
                in_authored_block = authored_markers_valid
                in_authored_section = False
                out_lines.append(line)
                continue
            if stripped == BINARY_FORECAST_END_MARKER:
                in_authored_block = False
                in_authored_section = False
                out_lines.append(line)
                continue
            if stripped.startswith("## "):
                if not in_authored_block:
                    in_authored_section = _is_authored_heading(stripped)
                in_references = stripped in _REFS_HEADINGS
                active_table_headers = []
                out_lines.append(line)
                continue

            table_cells = _table_cells(line)
            table_header = _is_table_header(lines, line_index)
            table_delimiter = _is_table_delimiter(line)
            if table_header:
                active_table_headers = table_cells
                out_lines.append(line)
                continue
            if table_delimiter:
                out_lines.append(line)
                continue
            if (
                in_authored_block
                or in_authored_section
                or in_references
                or not stripped
                or stripped.startswith("#")
                or not _number_re.search(stripped)
            ):
                if not stripped or (stripped and not table_cells):
                    active_table_headers = []
                out_lines.append(line)
                continue

            if table_cells:
                repaired_cells: List[str] = []
                for cell_index, cell in enumerate(table_cells):
                    context = _table_claim_context(
                        active_table_headers,
                        table_cells,
                        cell_index,
                        "",
                    )
                    repaired_cell, removed_numeric = _repair_fragments(
                        cell,
                        semantic_context=context,
                    )
                    if removed_numeric and not repaired_cell.strip():
                        repaired_cell = "—"
                        table_cells_cleared += 1
                    repaired_cells.append(repaired_cell)
                out_lines.append(_format_table_row(line, repaired_cells))
                continue

            active_table_headers = []
            prefix = ""
            body = line
            list_match = re.match(r"^(\s*(?:[-*+] |\d+[.)] ))(.*)$", line)
            if list_match:
                prefix, body = list_match.group(1), list_match.group(2)
            repaired_body, _ = _repair_fragments(body)
            if repaired_body:
                out_lines.append(prefix + repaired_body)

        repaired = "\n".join(out_lines)
        after = _audit_external_claims(repaired)
        after_coverage = float(after.get("resolved_coverage", 1.0) or 0.0)
        diagnostics = {
            "applied": repaired != text,
            "before": before,
            "after": after,
            "citations_added": citations_added,
            "sentences_removed": sentences_removed,
            "table_rows_removed": table_rows_removed,
            "table_cells_cleared": table_cells_cleared,
            "unverifiable_claims_preserved": unverifiable_claims_preserved,
            "market_claims_preserved": market_claims_preserved,
            "passed": after_coverage >= threshold,
        }
        if repaired != text:
            logger.info(
                "最终定量接地修复: coverage %.3f→%.3f, citations_added=%s, "
                "sentences_removed=%s, table_cells_cleared=%s, "
                "unverifiable_preserved=%s",
                coverage,
                after_coverage,
                citations_added,
                sentences_removed,
                table_cells_cleared,
                unverifiable_claims_preserved,
            )
        return repaired, diagnostics

    def _repair_quote_grounding(self, md: str) -> Tuple[str, int]:
        """RQ-2 引文接地修复：删除既非模拟/推演标注、又未在研究材料中逐字命中、且不带 [S#] 来源的
        blockquote 行（S2 判定为嫁接/捏造的引文）。带有效来源记号但无法逐字接地的文本保留为
        普通转述而不是伪装成直接引语。与 _audit_quote_provenance 同源判定，但按整行操作以便
        精确删除/去引号。返回 (新 markdown, 删除的引文行数)。

        WAVE9 修复两个系统性缺陷：
          (a) 推演标签常写在引文**上一行**的归因行里（'情景推演专家视角——「X」：' + 下一行
              blockquote）——此前只查 '>' 行本身，导致合法标注的引文被误删；
          (b) 整段 blockquote 被删后，紧邻其上的『X 表示：』归因行会孤悬（上一份报告残留
              ~12 处空引子）——现同步删除该引子行。"""
        v2 = bool(getattr(Config, "REPORT_QUOTE_AUDIT_V2", True))
        ground_raw = ((self.research_report or "") + "\n"
                      + (getattr(self, "_background_block", "") or "")
                      + "\n" + (getattr(self, "situation_brief", "") or ""))
        ground = self._quote_ground_material() if v2 else ground_raw.lower()
        sim_labels = self._SIM_QUOTE_LABELS
        _summary_n = self._norm_quote_text(getattr(self, "_outline_summary", "") or "")
        _table_note_n = self._norm_quote_text(self._TABLE_NOTE_TEXT)

        def _matches_ground(raw_q: str) -> bool:
            if not v2:
                probe = re.sub(r'^["“”「『\'\s]+', '', raw_q)[:40].lower().strip()
                return bool(probe and probe in ground)
            qn = self._norm_quote_text(raw_q)
            if not qn:
                return True
            if (_summary_n and qn == _summary_n) or qn == _table_note_n:
                return True
            probes = [qn[:40]]
            if len(qn) > 80:
                mid = len(qn) // 2
                probes.append(qn[mid:mid + 40])
            if len(qn) > 40:
                probes.append(qn[-40:])
            return any(p and p in ground for p in probes)

        def _is_ungrounded(raw_q: str) -> bool:
            if len(raw_q) < 12:
                return False
            ql = raw_q.lower()
            if any(t in ql for t in sim_labels):
                return False
            if _matches_ground(raw_q):
                return False
            if self._S_CITATION_RE.search(raw_q):
                return False
            return True

        lines = md.splitlines()

        def _preceding_attr_idx(i: int) -> int:
            """引文行 i 上方最近的非空行下标（-1 = 无）。"""
            j = i - 1
            while j >= 0 and not lines[j].strip():
                j -= 1
            return j

        # 第一遍：决定删除哪些引文行（归因行带推演标签的引文豁免——(a)）。
        delete: set = set()
        dequote: set = set()
        for i, ln in enumerate(lines):
            s = ln.strip()
            if not s.startswith(">"):
                continue
            raw_q = s[1:].strip()
            j = _preceding_attr_idx(i)
            if j >= 0:
                prev = lines[j].strip()
                if (prev and not prev.startswith(">") and not prev.startswith("#")
                        and any(t in prev.lower() for t in sim_labels)):
                    continue  # 上一行归因已诚实标注为推演 → 引文合法保留
            if self._S_CITATION_RE.search(raw_q) and not _matches_ground(raw_q):
                dequote.add(i)
                continue
            if _is_ungrounded(raw_q):
                delete.add(i)
        if not delete and not dequote:
            return md, 0

        # 第二遍：对「整段 blockquote 全被删」的段落，同步删除孤悬的引子归因行——(b)。
        intro_removed = 0
        i = 0
        n = len(lines)
        while i < n:
            if not lines[i].strip().startswith(">"):
                i += 1
                continue
            run_start = i
            while i < n and lines[i].strip().startswith(">"):
                i += 1
            run = range(run_start, i)
            if all(k in delete for k in run):
                j = _preceding_attr_idx(run_start)
                if j >= 0:
                    prev = lines[j].strip()
                    if (prev.endswith((":", "：")) and not prev.startswith((">", "#", "|"))
                            and j not in delete):
                        delete.add(j)
                        intro_removed += 1

        removed = sum(1 for k in delete if lines[k].strip().startswith(">"))
        out_lines: List[str] = []
        for k, ln in enumerate(lines):
            if k in delete:
                continue
            if k in dequote:
                prose = ln.strip()[1:].strip()
                prose = re.sub(r'^["“”「『\']+\s*', '', prose)
                prose = re.sub(
                    r'["”」』\'](?=\s*(?:\[S\d+\])|[.!?]?\s*$)', '', prose
                )
                out_lines.append(prose)
            else:
                out_lines.append(ln)
        if intro_removed:
            logger.info(f"引文接地修复：删除 {removed} 行未接地引文，并清理 {intro_removed} 行孤悬引子")
        if dequote:
            logger.info(f"引文接地修复：将 {len(dequote)} 行非逐字来源引文改为普通转述")
        return "\n".join(out_lines), removed

    def _repair_placeholder_tokens(self, md: str) -> Tuple[str, int]:
        """RQ-2 占位符解析：字面占位符记号（[S?-a] / 【S?】 / [S#]）——恰好只有一个来源时解析为
        [S1]，否则删除。删除后清理该行遗留的双空格与孤立标点。返回 (新 markdown, 处理数)。"""
        tokens = self._PLACEHOLDER_TOKEN_RE.findall(md)
        if not tokens:
            return md, 0
        n = len(tokens)
        single_source = len([s for s in (self.sources or []) if isinstance(s, dict)]) == 1
        if single_source:
            new_md = self._PLACEHOLDER_TOKEN_RE.sub("[S1]", md)
        else:
            new_md = self._PLACEHOLDER_TOKEN_RE.sub("", md)
            # 清理删除后遗留的 " ，" / 双空格（逐行，避免跨行误伤）
            new_md = "\n".join(
                re.sub(r"[ \t]{2,}", " ", re.sub(r"\s+([，。,.;；、])", r"\1", line)).rstrip()
                if self._PLACEHOLDER_TOKEN_RE.search(line) is None else line
                for line in new_md.splitlines()
            )
        return new_md, n

    def _citation_index_or_fallback(self) -> Dict[str, Any]:
        """WAVE10：取记号→来源映射；无 _citation_index（旧运行 / __new__ 测试构造）时
        回退为**全量**位置映射（{"S{i}": sources[i-1]}，编号与 _source_haystacks 对齐）。"""
        imap = getattr(self, "_citation_index", None)
        if isinstance(imap, dict) and imap:
            filtered = {
                str(tag): source for tag, source in imap.items()
                if _citation_source_admissible(source)
            }
            if filtered:
                return filtered
        out: Dict[str, Any] = {}
        for i, s in enumerate(getattr(self, "sources", None) or [], 1):
            if _citation_source_admissible(s):
                out[f"S{i}"] = s
        return out

    _CITATION_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
    _SEMANTIC_NUMBER_RE = re.compile(
        r"(?<![A-Za-z0-9_.])\d+(?:\.\d+)?\s*%?"
    )

    @classmethod
    def _semantic_numbers(cls, text: str) -> set[str]:
        return {
            re.sub(r"\s+", "", match.group(0))
            for match in cls._SEMANTIC_NUMBER_RE.finditer(str(text or ""))
        }

    @staticmethod
    def _citation_evidence_spans(source: Dict[str, Any]) -> List[str]:
        """Return only persisted evidence-bearing source fields."""
        spans: List[str] = []
        title = str(source.get("title") or "").strip()
        if title:
            spans.append(title)
        supports = source.get("supports")
        if isinstance(supports, list):
            spans.extend(
                str(value).strip() for value in supports if str(value).strip()
            )
        elif isinstance(supports, str) and supports.strip():
            spans.append(supports.strip())
        for key in (
            "excerpt", "snippet", "quote", "summary", "description", "content", "text"
        ):
            value = source.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            pieces = re.split(r"(?<=[.!?。！？])\s+|[\r\n]+", value.strip())
            spans.extend(
                piece.strip()[:1200] for piece in pieces[:200] if piece.strip()
            )
        return spans

    @classmethod
    def _citation_cjk_signature(cls, text: str) -> str:
        return "".join(cls._CITATION_CJK_RE.findall(str(text or "")))

    @classmethod
    def _citation_cjk_bigrams(cls, text: str) -> set[str]:
        signature = cls._citation_cjk_signature(text)
        return {
            signature[index:index + 2]
            for index in range(max(0, len(signature) - 1))
        }

    @classmethod
    def _semantic_citation_support(
        cls, line: str, source: Dict[str, Any]
    ) -> Optional[bool]:
        """Verify a cited claim against persisted, source-specific evidence spans.

        URL/domain/date/tier metadata is deliberately excluded: those fields can
        create lexical coincidences but cannot support a claim.  ``None`` means
        the pair is not deterministically auditable (for example cross-language
        prose); callers preserve but report it rather than guessing.
        """
        bare = cls._FULL_S_TAG_RE.sub(" ", str(line or ""))

        def _tokens(text: str) -> set[str]:
            out: set[str] = set()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", text.lower()):
                if token in cls._CITATION_MATCH_STOPWORDS:
                    continue
                if token.endswith("s") and len(token) > 5:
                    token = token[:-1]
                out.add(token)
            return out

        spans = cls._citation_evidence_spans(source)
        if not spans:
            return None

        title = str(source.get("title") or "").strip()
        line_tokens = _tokens(bare)
        line_numbers = cls._semantic_numbers(bare)
        discriminative_numbers = {
            number for number in line_numbers
            if not (number.isdigit() and 1900 <= int(number) <= 2100)
        }
        normalized_line = re.sub(r"\s+", " ", bare).strip().lower()
        line_cjk = cls._citation_cjk_signature(bare)
        cjk_spans = [span for span in spans if cls._citation_cjk_signature(span)]
        if line_cjk:
            if not cjk_spans:
                # Cross-language evidence cannot be rejected or accepted by a
                # monolingual lexical check. Preserve the claim and let coverage
                # remain visibly below the publication threshold.
                return None
            line_bigrams = cls._citation_cjk_bigrams(bare)
            number_compatible_span = False
            for span in cjk_spans:
                span_cjk = cls._citation_cjk_signature(span)
                span_numbers = cls._semantic_numbers(span)
                if line_numbers and not line_numbers.issubset(span_numbers):
                    continue
                number_compatible_span = True
                exact_phrase = (
                    min(len(line_cjk), len(span_cjk)) >= 6
                    and (line_cjk in span_cjk or span_cjk in line_cjk)
                )
                if exact_phrase:
                    return True
                overlap = line_bigrams & cls._citation_cjk_bigrams(span)
                if (
                    len(overlap) >= 5
                    and len(overlap) / max(1, len(line_bigrams)) >= 0.9
                ):
                    return True
            # A material number absent from every CJK span is a deterministic
            # contradiction. Similar wording with compatible numbers is merely
            # inconclusive: one changed Han character can invert sales vs.
            # production, imports vs. exports, etc., so preserve it uncited.
            return None if number_compatible_span else False

        if len(line_tokens) < 2:
            return None
        if not any(_tokens(span) for span in spans) and cjk_spans:
            return None

        all_span_tokens: set[str] = set()
        all_span_numbers: set[str] = set()
        for span in spans:
            all_span_tokens.update(_tokens(span))
            all_span_numbers.update(cls._semantic_numbers(span))
        # One source may persist a multi-part fact as several concise `supports`
        # spans (for example tariff rate and burden incidence). Aggregate only
        # those trusted spans—not URL/metadata—and require every material number
        # plus at least two source-specific lexical anchors.
        if (discriminative_numbers
                and discriminative_numbers.issubset(all_span_numbers)
                and len(line_tokens & all_span_tokens) >= 2):
            return True
        for index, span in enumerate(spans):
            span_tokens = _tokens(span)
            if not span_tokens:
                continue
            overlap = line_tokens & span_tokens
            normalized_span = re.sub(r"\s+", " ", span).strip().lower()
            exact_phrase = (
                len(normalized_span) >= 18
                and (normalized_span in normalized_line or normalized_line in normalized_span)
            )
            if exact_phrase:
                return True
            span_numbers = cls._semantic_numbers(span)
            if discriminative_numbers:
                if not discriminative_numbers.issubset(span_numbers):
                    continue
                if len(overlap) >= 2:
                    return True
                continue
            if line_numbers and not (line_numbers & span_numbers):
                continue
            # Titles identify a source but rarely prove a detailed claim; two
            # specific title anchors or three anchors in an explicit support /
            # excerpt span are the minimum deterministic standard.
            required = 2 if index == 0 and title else 3
            if len(overlap) >= required:
                return True
        return False

    @staticmethod
    def _citation_claim_clause(line: str, start: int, end: int) -> str:
        """Return the punctuation-bounded claim immediately owning a marker.

        Citation decisions must not borrow a number or entity from a neighboring
        sentence on the same Markdown line. Decimal points are not boundaries.
        Table pipes are boundaries because each cell is a distinct claim surface.
        """
        text = str(line or "")
        boundaries: List[Tuple[int, int]] = []
        for match in re.finditer(
            r"(?:\.(?=\s|$|[\[【])|[!?;。！？；]|\|)",
            text,
        ):
            boundaries.append((match.start(), match.end()))
        left = 0
        right = len(text)
        preceding = [pair for pair in boundaries if pair[1] <= start]
        if preceding:
            last_start, last_end = preceding[-1]
            if not text[last_end:start].strip():
                # Conventional Markdown puts a marker after the terminal period:
                # ``Claim. [S1]``. It belongs to Claim, not an empty next clause.
                left = preceding[-2][1] if len(preceding) > 1 else 0
                right = last_start
            else:
                left = last_end
        for boundary_start, _boundary_end in boundaries:
            if boundary_start >= end:
                if right == len(text):
                    right = boundary_start
                break
        return text[left:right].strip()

    @staticmethod
    def _citation_semantic_claim(
        line: str,
        marker_start: int,
        claim_clause: str,
        table_headers: List[str],
    ) -> str:
        """Add table row/header labels to a marker's own cell claim."""
        from .forecast_extractor import (
            markdown_table_cell_index,
            markdown_table_cells,
            markdown_table_claim_context,
        )

        cells = markdown_table_cells(line)
        if not cells:
            return claim_clause
        cell_index = markdown_table_cell_index(line, marker_start)
        if cell_index is None:
            return claim_clause
        return markdown_table_claim_context(
            table_headers,
            cells,
            cell_index,
            claim_clause,
        )

    def _best_semantic_source_tag_for_line(
        self, line: str
    ) -> str:
        candidates: List[Tuple[int, int, int, str, Dict[str, Any]]] = []
        bare = self._FULL_S_TAG_RE.sub(" ", str(line or ""))
        line_words = set(re.findall(r"[A-Za-z][A-Za-z0-9_-]{3,}", bare.lower()))
        line_numbers = self._semantic_numbers(bare)
        line_cjk = self._citation_cjk_bigrams(bare)
        for index, source in enumerate(getattr(self, "sources", None) or [], 1):
            if not _citation_source_admissible(source):
                continue
            supported = self._semantic_citation_support(line, source)
            if supported is not True:
                continue
            source_text = "\n".join(self._citation_evidence_spans(source))
            source_words = set(re.findall(
                r"[A-Za-z][A-Za-z0-9_-]{3,}", source_text.lower()))
            source_numbers = self._semantic_numbers(source_text)
            candidates.append((
                len(line_numbers & source_numbers),
                len(line_words & source_words),
                len(line_cjk & self._citation_cjk_bigrams(source_text)),
                f"S{index}",
                source,
            ))
        if not candidates:
            return ""
        candidates.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
        best = candidates[0]
        if len(candidates) > 1 and best[:3] == candidates[1][:3]:
            return ""  # tied provenance is not a safe automatic remap
        imap = getattr(self, "_citation_index", None)
        if not isinstance(imap, dict):
            imap = {}
            self._citation_index = imap
        imap.setdefault(best[3], best[4])
        return best[3]

    # i7：市场语境判据与 forecast_extractor._MARKET_MENTION_RE 同族（另加 gamma/clob）。
    _MARKET_CONTEXT_RE = re.compile(
        r"market|polymarket|gamma|clob|implied|市场|預測|预测市场", re.I)

    def _market_snapshot_price_variants(self) -> set:
        """机器抓取的市场快照价的可引用字符串形态集合（现价 + 研究期价）。

        证据源：self._prediction_markets（PM-3 缓存快照）与 _forecast_spine 里已锚定的
        market_anchor / market_comparison（同源快照价）。每个 p∈(0,1] 生成三种常见书写：
        小数原样（0.125）、百分数（12.5）、四舍五入整百分数（12）。Pure、degrade-safe。"""
        prices: set = set()

        def _collect(value: Any) -> None:
            try:
                p = float(value)
            except (TypeError, ValueError):
                return
            if not (0.0 < p <= 1.0):
                return
            prices.add(f"{p:g}")
            prices.add(f"{p * 100:g}")
            prices.add(f"{round(p * 100):d}")

        for m in (getattr(self, "_prediction_markets", None) or []):
            if isinstance(m, dict):
                _collect(m.get("implied_yes_prob"))
                _collect(m.get("price_at_research"))
        spine = getattr(self, "_forecast_spine", None)
        if isinstance(spine, dict):
            for b in (spine.get("binary_forecasts") or []):
                anchor = b.get("market_anchor") if isinstance(b, dict) else None
                if isinstance(anchor, dict):
                    _collect(anchor.get("implied_yes_prob"))
                    _collect(anchor.get("price_at_research"))
            mc = spine.get("market_comparison")
            if isinstance(mc, dict):
                for c in (mc.get("comparisons") or []):
                    if isinstance(c, dict):
                        _collect(c.get("market_implied_yes_prob"))
                        _collect(c.get("price_at_research"))
        return prices

    def _market_corroborated_claim(self, claim: str) -> bool:
        """一条数字声明是否被市场快照精确佐证。

        须同时满足：市场语境关键词命中 + 快照价（现价或研究期价）在句中按数字边界精确
        匹配（``(?<![\\d.])v(?![\\d])``，防「2012 撞 12」）。裸数字碰巧撞价不豁免。"""
        text = str(claim or "")
        if not text or not self._MARKET_CONTEXT_RE.search(text):
            return False
        for v in self._market_snapshot_price_variants():
            if re.search(rf"(?<![\d.]){re.escape(v)}(?![\d])", text):
                return True
        return False

    def _quantitative_semantic_decision(self, claim: str) -> Tuple[str, str]:
        """Return ``(supported tag, status)`` for one numeric claim unit.

        ``unverifiable`` is deliberately distinct from ``unsupported``. The
        former survives uncited so the unchanged quality gate fails honestly;
        only deterministically unsupported precision may be removed.
        ``market_supported`` (i7) marks a claim whose number exactly matches the
        machine-fetched prediction-market snapshot in a market context: kept
        as-is, never assigned an invented ``[S#]``, never removed — the
        historical failure removed true Polymarket prices as fabrication.
        """
        tag = self._best_semantic_source_tag_for_line(claim)
        if tag:
            return tag, "supported"
        if self._market_corroborated_claim(claim):
            return "", "market_supported"
        outcomes: List[bool] = []
        saw_unverifiable = False
        for source in getattr(self, "sources", None) or []:
            if not _citation_source_admissible(source):
                continue
            supported = self._semantic_citation_support(claim, source)
            if supported is None:
                saw_unverifiable = True
            else:
                outcomes.append(supported)
        if any(outcomes):
            # More than one equally plausible source is not safe provenance.
            return "", "unverifiable"
        if saw_unverifiable:
            return "", "unverifiable"
        if outcomes:
            return "", "unsupported"
        if any(
            _citation_source_admissible(source)
            for source in (getattr(self, "sources", None) or [])
        ):
            return "", "unverifiable"
        return "", "unsupported"

    def _repair_semantic_citations(
        self, md: str
    ) -> Tuple[str, Dict[str, int]]:
        """Keep supported markers and strip unsupported ones without guessing.

        A lexical candidate is not provenance.  Automatic semantic remapping is
        therefore forbidden here; a missing citation remains a visible coverage
        gap for the publication gate instead of becoming a false footnote.
        """
        from .forecast_extractor import (
            is_markdown_table_delimiter,
            is_markdown_table_header,
            markdown_fence_transition,
            markdown_table_cells,
        )

        imap = self._citation_index_or_fallback()
        current = getattr(self, "_citation_index", None)
        if not isinstance(current, dict) or not current:
            self._citation_index = dict(imap)
        marker_re = re.compile(r"[\[【]\s*(S\d+)\s*[\]】]", re.I)
        info = {"checked": 0, "kept": 0, "unverifiable": 0,
                "remapped": 0, "stripped": 0}
        out: List[str] = []
        fence_state = None
        table_headers: List[str] = []
        lines = str(md or "").split("\n")
        for line_index, line in enumerate(lines):
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = markdown_fence_transition(
                line, fence_state
            )
            if is_fence_line:
                out.append(line)
                continue
            if was_in_fence:
                out.append(line)
                continue
            cells = markdown_table_cells(line)
            if is_markdown_table_header(lines, line_index):
                table_headers = cells
                out.append(line)
                continue
            if is_markdown_table_delimiter(line):
                out.append(line)
                continue
            if not cells:
                table_headers = []

            def _replace(
                match: "re.Match",
                *,
                _line: str = line,
                _headers: Tuple[str, ...] = tuple(table_headers),
            ) -> str:
                tag = match.group(1).upper()
                source = imap.get(tag)
                if not isinstance(source, dict):
                    return match.group(0)
                info["checked"] += 1
                claim_clause = self._citation_claim_clause(
                    _line, match.start(), match.end()
                )
                semantic_claim = self._citation_semantic_claim(
                    _line,
                    match.start(),
                    claim_clause,
                    list(_headers),
                )
                supported = self._semantic_citation_support(semantic_claim, source)
                if supported is True:
                    info["kept"] += 1
                    return f"[{tag}]"
                if supported is None:
                    info["unverifiable"] += 1
                    return f"[{tag}]"
                info["stripped"] += 1
                return ""

            updated = marker_re.sub(_replace, line)
            updated = re.sub(r"(?:\[(S\d+)\])(?:\s+\[\1\])+", r"[\1]", updated)
            updated = re.sub(r"\s+([，。,.;；、])", r"\1", updated)
            updated = re.sub(r"[ \t]{2,}", " ", updated).rstrip()
            out.append(updated)
        return "\n".join(out), info

    def _audit_semantic_citations(
        self, md: str, index_map: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        from .forecast_extractor import (
            is_markdown_table_delimiter,
            is_markdown_table_header,
            markdown_fence_transition,
            markdown_table_cells,
        )

        imap = index_map or self._citation_index_or_fallback()
        marker_re = re.compile(r"[\[【]\s*(S\d+)\s*[\]】]", re.I)
        unsupported: List[Dict[str, str]] = []
        unverifiable = 0
        checked = 0
        tag_counts: Dict[str, int] = {}
        fence_state = None
        table_headers: List[str] = []
        lines = str(md or "").split("\n")
        for line_index, line in enumerate(lines):
            line_no = line_index + 1
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = markdown_fence_transition(
                line, fence_state
            )
            if is_fence_line:
                continue
            if was_in_fence:
                continue
            cells = markdown_table_cells(line)
            if is_markdown_table_header(lines, line_index):
                table_headers = cells
                continue
            if is_markdown_table_delimiter(line):
                continue
            if not cells:
                table_headers = []
            for match in marker_re.finditer(line):
                source = imap.get(match.group(1).upper())
                if not isinstance(source, dict):
                    continue
                checked += 1
                tag = match.group(1).upper()
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
                claim_clause = self._citation_claim_clause(
                    line, match.start(), match.end()
                )
                semantic_claim = self._citation_semantic_claim(
                    line,
                    match.start(),
                    claim_clause,
                    table_headers,
                )
                supported = self._semantic_citation_support(semantic_claim, source)
                if supported is None:
                    unverifiable += 1
                elif not supported:
                    unsupported.append({
                        "tag": tag,
                        "line": str(line_no),
                        "excerpt": line.strip()[:180],
                    })
        max_per_source = max(
            1, int(getattr(Config, "REPORT_MAX_CITATIONS_PER_SOURCE", 20) or 20)
        )
        overused = [
            {"tag": tag, "count": count, "limit": max_per_source}
            for tag, count in sorted(tag_counts.items())
            if count > max_per_source
        ]
        unverifiable_ratio = round(unverifiable / checked, 3) if checked else 0.0
        return {
            "checked": checked,
            "unsupported": len(unsupported),
            "unverifiable": unverifiable,
            "unverifiable_ratio": unverifiable_ratio,
            "examples": unsupported[:8],
            "max_per_source": max_per_source,
            "overused_sources": overused,
            "passed": not unsupported and not overused,
        }

    def _repair_overused_citations(
        self, md: str, index_map: Optional[Dict[str, Any]] = None
    ) -> Tuple[str, int]:
        """SESSIONB-2 引用集中度修复：把单一来源的正文引用记号裁到配置上限之内。

        终审 _final_audit_integrity_issues 把「引用来源过度集中」（单来源 >
        REPORT_MAX_CITATIONS_PER_SOURCE 次）判为硬缺陷，但修复链此前没有任何一环
        削减集中度——_stabilize_publish_markdown 可以收敛出一份「稳定」成稿、随后被
        只读终审确定性否决，整份报告在全部章节成本烧完后被丢弃。此处按与
        _audit_semantic_citations 完全同源的扫描纪律（围栏内跳过、表头/分隔行跳过、
        References 附录块跳过、仅统计能解析到来源索引的 [S#] 记号）做确定性裁剪。

        防振荡关键：_repair_final_quantitative_grounding 会给覆盖率不足时的**含数字**
        无记号论断回填最佳来源记号——若从数字行摘记号，下一轮定量修复可能原样补回，
        定点循环永不收敛。故数字行上的记号一律**钉住不动**，只从非数字行按首现顺序
        保留 (cap - 钉住数) 次、剥离其后的富余记号（论断文字原样保留，只摘记号，与
        悬空修复同样的诚实动作）。钉住数已超 cap 时无法确定性修复（与修复前一样交由
        终审否决，绝不为凑数破坏定量接地）。返回 (新 markdown, 剥离的记号数)。"""
        from .forecast_extractor import (
            _NUMBER_RE as _number_re,
            is_markdown_table_delimiter,
            is_markdown_table_header,
            markdown_fence_transition,
        )
        imap = index_map or self._citation_index_or_fallback()
        try:
            cap = max(1, int(getattr(Config, "REPORT_MAX_CITATIONS_PER_SOURCE", 20) or 20))
        except (TypeError, ValueError):
            cap = 20
        marker_re = re.compile(r"[\[【]\s*(S\d+)\s*[\]】]", re.I)
        lines = str(md or "").split("\n")
        # 第一遍：按审计同源纪律采集可计数记号出现位置 (行号, span, tag, 是否数字行)。
        occurrences: List[Tuple[int, Tuple[int, int], str, bool]] = []
        fence_state = None
        in_refs = False
        for line_index, line in enumerate(lines):
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = markdown_fence_transition(line, fence_state)
            if is_fence_line or was_in_fence:
                continue
            heading = line.strip()
            if heading.startswith("## "):
                # 与终审 body/附录切分同源：附录条目自带 [S#]，绝不能被当作正文集中度裁剪。
                in_refs = heading in _REFS_HEADINGS
            if (in_refs
                    or is_markdown_table_header(lines, line_index)
                    or is_markdown_table_delimiter(line)):
                continue
            # 记号剥掉后再判数字行：记号本身的 S<n> 编号不能把纯文字行误判成数字行。
            bare = marker_re.sub(" ", line)
            numeric_line = bool(_number_re.search(bare))
            for match in marker_re.finditer(line):
                tag = match.group(1).upper()
                if not isinstance(imap.get(tag), dict):
                    continue   # 悬空/不可解析记号归悬空修复管，此处不动
                occurrences.append((line_index, match.span(), tag, numeric_line))
        counts: Dict[str, int] = {}
        for _li, _sp, tag, _num in occurrences:
            counts[tag] = counts.get(tag, 0) + 1
        over_tags = {tag for tag, count in counts.items() if count > cap}
        if not over_tags:
            return md, 0
        # 第二遍：决定剥离集合——数字行记号全部钉住；非数字行按首现顺序保留剩余预算。
        strip_spans: Dict[int, List[Tuple[int, int]]] = {}
        stripped = 0
        for tag in over_tags:
            rows = [row for row in occurrences if row[2] == tag]
            pinned = sum(1 for row in rows if row[3])
            budget = cap - pinned
            if budget < 0:
                logger.warning(
                    f"引用集中度修复：来源 [{tag}] 在数字行上已被引用 {pinned} 次（> 上限 "
                    f"{cap}），无法在不破坏定量接地的前提下确定性裁剪，保留原样交终审判定")
                budget = 0   # 非数字行富余仍尽量剥离（best-effort 降低集中度）
            kept_plain = 0
            for line_index, span, _tag, numeric_line in rows:
                if numeric_line:
                    continue
                if kept_plain < budget:
                    kept_plain += 1
                    continue
                strip_spans.setdefault(line_index, []).append(span)
                stripped += 1
        if not stripped:
            return md, 0
        for line_index, spans in strip_spans.items():
            line = lines[line_index]
            for start, end in sorted(spans, reverse=True):
                line = line[:start] + line[end:]
            lines[line_index] = re.sub(
                r"[ \t]{2,}", " ",
                re.sub(r"\s+([，。,.;；、])", r"\1", line),
            ).rstrip()
        logger.info(
            f"引用集中度修复：剥离 {stripped} 个非数字行富余记号（上限 {cap}/来源；超限来源 "
            f"{sorted(((t, counts[t]) for t in over_tags), key=lambda kv: -kv[1])[:4]}）")
        return "\n".join(lines), stripped

    def _repair_dangling_citations(self, md: str,
                                   dangling: List[str]) -> Tuple[str, Dict[str, int]]:
        """WAVE10 悬空引用修复：正文记号在注入索引里解析不到（[S246] 型幻觉编号）时，
        按记号做三步定向处置（全部确定性，无 LLM）：

          (1) 保留验证——编号落在**全量**来源列表内（索引截取造成的假悬空），且记号所在行
              的数字锚点与至少两个词汇锚点唯一指向该来源 → 记号合法保留，并登记进 self._citation_index
              （引用最终化随后把它列入参考来源）；
          (2) 重映射——否则复用引用回填的数字 + 词汇唯一锚定在全量来源中找命中 → 记号改写为命中
              来源的 [S{i}] 并登记；
          (3) 删除——两者皆失败的记号从行内剥离（与占位符解析同样的诚实动作），
              清理遗留的双空格与孤立标点。

        围栏（```/~~~）内的记号是字面内容，不动。返回
        (新 markdown, {"kept_verified", "remapped", "stripped"})（按记号计数）。"""
        from .forecast_extractor import markdown_fence_transition

        info = {"kept_verified": 0, "remapped": 0, "stripped": 0}
        if not dangling:
            return md, info
        haystacks = self._source_haystacks()
        sources = getattr(self, "sources", None) or []
        imap = getattr(self, "_citation_index", None)
        if not isinstance(imap, dict):
            imap = {}
            self._citation_index = imap
        dangling_set = {str(tag).upper() for tag in dangling}
        marker_re = re.compile(r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]", re.I)

        out_lines: List[str] = []
        fence_state = None
        for line in md.split("\n"):
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = markdown_fence_transition(
                line, fence_state
            )
            if is_fence_line:
                out_lines.append(line)
                continue
            if was_in_fence:
                out_lines.append(line)
                continue
            changed = False

            def _replace(match: "re.Match", *, _line: str = line) -> str:
                nonlocal changed
                original = match.group(1)
                tag = original.upper()
                if tag not in dangling_set:
                    return match.group(0)
                claim_clause = self._citation_claim_clause(
                    _line, match.start(), match.end()
                )
                best = self._best_source_tag_for_line(
                    claim_clause, haystacks
                ).strip("[]").upper()
                if best:
                    try:
                        source_index = int(best[1:]) - 1
                    except (TypeError, ValueError):
                        source_index = -1
                    if (0 <= source_index < len(sources)
                            and _citation_source_admissible(sources[source_index])):
                        imap.setdefault(best, sources[source_index])
                        changed = True
                        if best == tag:
                            info["kept_verified"] += 1
                            return f"[{tag}]"
                        info["remapped"] += 1
                        return f"[{best}]"
                changed = True
                info["stripped"] += 1
                return ""

            new_line = marker_re.sub(_replace, line)
            if changed:
                new_line = re.sub(
                    r"[ \t]{2,}", " ",
                    re.sub(r"\s+([，。,.;；、])", r"\1", new_line),
                ).rstrip()
            out_lines.append(new_line)
        logger.info(
            f"悬空引用修复：保留验证 {info['kept_verified']}，重映射 {info['remapped']}，"
            f"删除 {info['stripped']}（候选 {len(dict.fromkeys(dangling))} 个记号）")
        return "\n".join(out_lines), info

    # 任意 [S…] 记号（位置式 [S1]、分层 [S1-a]、或占位符 [S?]/[S#]）——引用回填判定「本行是否已带记号」。
    _ANY_S_TAG_RE = re.compile(r"[\[【]\s*S[\d?#]", re.I)
    _FULL_S_TAG_RE = re.compile(
        r"[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】]",
        re.I,
    )

    # WAVE9：泄漏章节标题（方法学词汇进标题）——修复与大纲 lint 共用。\bagents?\b 带词界，
    # 避免误伤 agenda/agency 等词。
    _LEAK_TITLE_RE = re.compile(
        r"模拟|智能体|行为轨迹|推演轨迹|\bagents?\b|simulation|behaviou?r", re.I)
    # 泄漏标题的安全替换标题（ZH/EN 各一组，循环取用）。
    _SAFE_TITLES_ZH = ("关键行为者与权力结构", "驱动机制与证据链", "群体动态与联盟结构")
    _SAFE_TITLES_EN = ("Power Centers & Key Actors", "Drivers, Mechanisms & Evidence",
                       "Coalition Dynamics & Emerging Signals")
    # 段落中的数字 token（泄漏重写的逐字节数字校验）。
    _NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?%?")

    def _repair_simulation_leakage(self, md: str) -> Tuple[str, Dict[str, Any]]:
        """WAVE9 模拟泄漏修复：报告必须是关于现实世界的预测，推演机制绝不能成为叙述对象。

        三级流水（全部有界、degrade-safe）：
          Tier-1 确定性改写：旧模拟标签 → 专家小组转述规范；原始边转储 → 自然语言关系；
                 [simulation_outcomes] 等工具记号删除；平台行为引文（发帖/点赞）删除；
                 泄漏章节标题（模拟/Agent/Simulation…）确定性改名。
          Tier-2 每个仍命中泄漏模式的散文段落做**一次**有界 LLM 重写（至多
                 REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS 段）；重写必须保留原段全部数字 token
                 逐字节不变，否则弃用重写。
          Tier-3 重写后重扫，仍命中的句子直接删除（与引文接地修复同样的诚实动作）。

        返回 (新 markdown, 统计 dict)。无 LLM（离线/测试）时跳过 Tier-2，直接句子级删除。"""
        from . import report_lint as _rl
        lang = getattr(self, "output_language", None) or "English"
        zh = not str(lang).strip().lower().startswith("en")
        info: Dict[str, Any] = {}
        text = md or ""

        # ── Tier-1：确定性改写 ──
        text, info["labels_rewritten"] = _rl.rewrite_sim_labels(text, lang)
        text, info["edge_dumps_rewritten"], info["dangling_edge_intros"] = (
            _rl.rewrite_edge_dumps(text, lang))
        text, info["tool_tokens_stripped"] = _rl.strip_tool_tokens(text)
        text, info["platform_quotes_dropped"] = _rl.drop_platform_behavior_quotes(text)

        # 泄漏章节标题改名（保留编号前缀与章节数量契约——改名而非删除）。
        lines = text.split("\n")
        mask = _rl._fence_mask(lines)
        safe_titles = self._SAFE_TITLES_ZH if zh else self._SAFE_TITLES_EN
        renamed = 0
        for i, ln in enumerate(lines):
            if mask[i]:
                continue
            m = re.match(r"^(#{2,3})\s*(\d+[\.、]?\s*)?(.+)$", ln)
            if not m or not self._LEAK_TITLE_RE.search(m.group(3)):
                continue
            new_title = safe_titles[renamed % len(safe_titles)]
            if renamed >= len(safe_titles):
                new_title = f"{new_title}（{renamed + 1}）" if zh else f"{new_title} ({renamed + 1})"
            lines[i] = f"{m.group(1)} {m.group(2) or ''}{new_title}".rstrip()
            renamed += 1
        info["headings_renamed"] = renamed
        text = "\n".join(lines)

        # ── Tier-2/3：散文段落级扫描 ──
        llm = getattr(self, "llm", None)
        can_llm = llm is not None and hasattr(llm, "chat")
        try:
            budget = int(getattr(Config, "REPORT_SIMLEAK_MAX_LLM_PARAGRAPHS", 12) or 0)
        except (TypeError, ValueError):
            budget = 12
        lines = text.split("\n")
        mask = _rl._fence_mask(lines)
        rewritten = 0
        sentences_deleted = 0
        i = 0
        n = len(lines)
        while i < n:
            s = lines[i].strip()
            if (mask[i] or not s or self._simleak_skip_line(s)
                    or re.match(r"^\d+[.、)]", s)):
                i += 1
                continue
            # 聚合一个散文段落（连续的非空散文行）
            start = i
            while (i < n and lines[i].strip() and not mask[i]
                   and not self._simleak_skip_line(lines[i].strip())):
                i += 1
            para = "\n".join(lines[start:i])
            if not _rl.leakage_hits(para):
                continue
            new_para = None
            if can_llm and rewritten < budget:
                new_para = self._simleak_rewrite_paragraph(para, lang)
                if new_para:
                    rewritten += 1
            if new_para is None:
                new_para = para
            # Tier-3：重扫，仍命中的句子删除
            cleaned, removed = _rl.strip_leakage_sentences(new_para.replace("\n", " "))
            sentences_deleted += removed
            repl = cleaned if cleaned else ""
            lines[start:i] = [repl]
            delta = 1 - (i - start)
            i = start + 1
            n += delta
            mask = _rl._fence_mask(lines)
        info["paragraphs_rewritten"] = rewritten
        info["sentences_deleted"] = sentences_deleted
        text = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
        return text, info

    def _simleak_rewrite_paragraph(self, para: str, lang: str) -> Optional[str]:
        """对单个泄漏段落做一次有界 LLM 重写；数字 token 逐字节校验失败/输出异常 → None。"""
        nums = self._NUM_TOKEN_RE.findall(para)
        sys_prompt = (
            f"You are the chief editor of an institutional forecast written in {lang}. "
            "Rewrite the paragraph as forecast prose about the REAL WORLD. Keep every number, "
            "probability, [S#] citation tag and quotation byte-identical. Replace "
            "simulation-mechanics references (simulation, agents, rounds, action counts, "
            "posting/liking/commenting, consensus formation, factions, causal graph, "
            "模拟/智能体/轮次/动作/派系/因果图) with 'our scenario analysis indicates' or an "
            "attributed analytical viewpoint; remove action counts, round numbers and platform "
            "mechanics entirely. Output ONLY the rewritten paragraph — no preamble, no fences."
        )
        try:
            out = self.llm.chat(
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": para[:4000]}],
                temperature=0.1, max_tokens=2048, tier="fast",
            )
        except Exception as _e:  # noqa: BLE001 — 重写失败退回句子级删除
            logger.warning(f"泄漏段落重写调用失败（退回句子删除）: {_e}")
            return None
        out = (out or "").strip()
        if not out or len(out) > max(600, len(para) * 3):
            return None
        # 数字逐字节校验：原段每个数字 token 必须原样出现在重写里（防概率/数据漂移）。
        for tok in nums:
            if tok not in out:
                logger.warning(f"泄漏段落重写丢失数字 token「{tok}」，弃用重写")
                return None
        return out

    def _check_binary_sim_sensitivity(self, report_id: str,
                                      forecast: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """XRUN-1(c): 廉价的跨报告同一性门。同一图谱、不同 simulation_id 的上一份报告若
        产出了逐项 |Δ|≤0.01 的相同二元概率向量，说明 Part-1 概率是研究先验的确定性复读、
        模拟阶段贡献为零（74dc vs aa77 逐字节相同即为实锤）。命中返回 quality 记录字典，
        否则 None。只读比对、任何失败返回 None（观测性，绝不影响主流程）。
        注：在 XRUN-1(b) 的信号注入生效前，本门可能对既有报告合法命中。"""
        probs = [b.get("probability") for b in (forecast.get("binary_forecasts") or [])
                 if isinstance(b, dict)]
        if len(probs) < 5:  # 向量太短时同一性没有区分力
            return None
        try:
            reports_dir = os.path.join(Config.UPLOAD_FOLDER, "reports")
            if not os.path.isdir(reports_dir):
                return None
            candidates = []
            for name in os.listdir(reports_dir):
                if name == report_id or not name.startswith("report_"):
                    continue
                meta_path = os.path.join(reports_dir, name, "meta.json")
                fc_path = os.path.join(reports_dir, name, "forecast.json")
                if os.path.exists(meta_path) and os.path.exists(fc_path):
                    candidates.append((os.path.getmtime(fc_path), name, meta_path, fc_path))
            # 只比对最近的少量报告（有界）
            for _, other_id, meta_path, fc_path in sorted(candidates, reverse=True)[:8]:
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        meta = json.load(f)
                    if str(meta.get("graph_id") or "") != str(self.graph_id or ""):
                        continue
                    if str(meta.get("simulation_id") or "") == str(self.simulation_id or ""):
                        continue  # 同一模拟的重跑本就应相近，不算不敏感
                    with open(fc_path, "r", encoding="utf-8") as f:
                        other_fc = json.load(f)
                    other_probs = [b.get("probability")
                                   for b in (other_fc.get("binary_forecasts") or [])
                                   if isinstance(b, dict)]
                    if len(other_probs) != len(probs):
                        continue
                    if all(abs(float(a) - float(b)) <= 0.01
                           for a, b in zip(probs, other_probs, strict=True)):
                        return {
                            "issue": "binary probabilities identical to a different-simulation "
                                     "report — forecasts insensitive to simulation",
                            "other_report_id": other_id,
                            "other_simulation_id": str(meta.get("simulation_id") or ""),
                        }
                except (OSError, ValueError, TypeError):
                    continue
        except Exception:  # noqa: BLE001
            return None
        return None

    def _append_resolution_section(self, report_id: str, report: "Report") -> None:
        """NEXTSTEPS P2-2: 把确定性的「如何验证本预测」章节（判定标准 + 观察指标）追加到成稿末尾
        并重写 full_report.md。指标-情景映射已随 forecast.json 落盘。仅在已有预测骨架时调用。
        """
        from .forecast_extractor import render_resolution_block
        from ..utils import actors as _actors
        try:
            indicators = _actors.extract_forecast_inputs(self.actors).get("indicators") or []
        except Exception:  # noqa: BLE001
            indicators = []
        # WAVE9：判定章节跟随报告输出语言（此前硬编码中文标题，英文报告里出现整段中文章节）。
        block = render_resolution_block(
            self._forecast_spine, indicators,
            language=getattr(self, "output_language", None) or "Chinese")
        if not block:
            return
        new_md = (report.markdown_content or "").rstrip() + "\n\n" + block + "\n"
        report.markdown_content = new_md
        try:
            folder = ReportManager._get_report_folder(report_id)
            write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
        except Exception as _we:  # noqa: BLE001
            logger.warning(f"重写 full_report.md（追加判定标准章节）失败（忽略）: {_we}")
        logger.info(f"已追加判定标准与观察指标章节: {report_id}")

    # RPT-5: 系统确定性注入的对比表注释 blockquote（_render_comparison_table 固定输出），
    # 永远不可能命中研究材料，必须豁免。
    _TABLE_NOTE_TEXT = "上表为确定性聚合结果，正文请围绕这些权威差值展开解读，勿自行复算或反转方向。"
    _S_CITATION_RE = re.compile(r"[\[【]\s*S\d+\s*[\]】]", re.I)
    # WAVE9：诚实标注为内部推演的引文标签白名单（引文接地审计/修复共用）。旧标签
    # （模拟/代理人）与新专家小组转述规范（scenario panel / 情景推演专家视角 /
    # analytical perspective）必须同批收录——否则按新规范转写的引文会被当作未接地删除。
    _SIM_QUOTE_LABELS = (
        "模拟", "simulation", "代理人", "推演", "sim-agent", "simulated agent",
        "scenario panel", "analytical perspective", "情景推演专家视角",
    )

    @staticmethod
    def _norm_quote_text(text: str) -> str:
        """RPT-5: 归一化引文/底料——去 markdown 强调与引号字符（弯直混用）、压空白、小写，
        让逐字比对不被排版差异（**加粗**、弯引号、折行）制造假阳性。纯函数。"""
        import re as _re
        t = _re.sub(r"[*_`]+", "", str(text or ""))
        t = _re.sub(r"[\"'“”‘’„‟「」『』]", "", t)
        return _re.sub(r"\s+", " ", t).strip().lower()

    def _quote_ground_material(self) -> str:
        """Return normalized quote evidence from research and finalized sources."""
        parts = [
            self.research_report or "",
            getattr(self, "_background_block", "") or "",
            getattr(self, "situation_brief", "") or "",
        ]
        parts.extend(haystack for _tag, haystack in self._source_haystacks())
        return self._norm_quote_text("\n".join(parts))

    def _audit_quote_provenance(self, report_markdown: str) -> Dict[str, Any]:
        """QUALITY-OPT S2 + RPT-5: detect laundered quotes. A blockquote presented as a
        REAL/factual quote (not labeled as simulation) must substring-match the research
        material; otherwise it is likely sim-roleplay or a graph-edge string dressed up as
        a real source, or an outright fabrication. Returns a count + examples;
        observability only (never mutates).

        RPT-5（REPORT_QUOTE_AUDIT_V2，默认开）修掉系统性假阳性：(1) 豁免系统注入的
        大纲摘要/对比表注释 blockquote；(2) 归一化 + 头/中/尾三段探针（此前单一 40 字
        头探针对强调符/弯引号极脆）；(3) 带 [S#] 引用但非逐字的引文单列为
        cited_unverbatim（仍是缺陷，但非捏造，发布门仅对 ungrounded 降级）。"""
        import re as _re
        # WAVE9：保留行位置，使推演标签可写在引文**上一行**的归因行里（与
        # _repair_quote_grounding 同源判定，否则审计与修复对同一引文给出相反结论）。
        raw_lines = (report_markdown or "").splitlines()
        pairs: List[Tuple[str, str]] = []                # (quote, 上方最近非空行)
        for _i, _ln in enumerate(raw_lines):
            _s = _ln.strip()
            if not _s.startswith(">"):
                continue
            _j = _i - 1
            while _j >= 0 and not raw_lines[_j].strip():
                _j -= 1
            _prev = raw_lines[_j].strip() if _j >= 0 else ""
            pairs.append((_s[1:].strip(), _prev))
        pairs = [(q, p) for q, p in pairs if len(q) >= 12]
        quotes = [q for q, _ in pairs]
        if not quotes:
            return {}
        v2 = bool(getattr(Config, "REPORT_QUOTE_AUDIT_V2", True))
        ground_raw = ((self.research_report or "") + "\n"
                      + (getattr(self, "_background_block", "") or "")
                      + "\n" + (getattr(self, "situation_brief", "") or ""))
        ground = self._quote_ground_material() if v2 else ground_raw.lower()
        sim_labels = self._SIM_QUOTE_LABELS  # WAVE9：含新专家小组转述标签（scenario panel 等）
        _summary_n = self._norm_quote_text(getattr(self, "_outline_summary", "") or "")
        _table_note_n = self._norm_quote_text(self._TABLE_NOTE_TEXT)
        ungrounded: List[str] = []
        unverbatim: List[str] = []
        for q, prev in pairs:
            ql = q.lower()
            if any(t in ql for t in sim_labels):       # honestly labeled as simulation → fine
                continue
            if (prev and not prev.startswith(">") and not prev.startswith("#")
                    and any(t in prev.lower() for t in sim_labels)):
                continue                                # 归因行诚实标注为推演 → fine（WAVE9）
            if not v2:
                probe = _re.sub(r'^["“”「『\'\s]+', '', q)[:40].lower().strip()
                if probe and probe in ground:           # matches real research material → fine
                    continue
                ungrounded.append(q[:90])
                continue
            qn = self._norm_quote_text(q)
            if not qn:
                continue
            if (_summary_n and qn == _summary_n) or qn == _table_note_n:
                continue                                # 系统注入的 blockquote → 豁免
            probes = [qn[:40]]
            if len(qn) > 80:
                mid = len(qn) // 2
                probes.append(qn[mid:mid + 40])
            if len(qn) > 40:
                probes.append(qn[-40:])
            if any(p and p in ground for p in probes):  # verbatim match → fine
                continue
            if self._S_CITATION_RE.search(q):           # 有 [S#] 来源但非逐字 → 单列
                unverbatim.append(q[:90])
                continue
            ungrounded.append(q[:90])
        out = {"total_quotes": len(quotes), "ungrounded": len(ungrounded),
               "examples": ungrounded[:5]}
        if v2:
            out["cited_unverbatim"] = len(unverbatim)
            if unverbatim:
                out["unverbatim_examples"] = unverbatim[:5]
        return out

    def _audit_stat_plausibility(self, report_markdown: str) -> Dict[str, Any]:
        """QUALITY-OPT S12: flag implausible headline statistics that anchor whole reports —
        extreme year-over-year growth (>100%) like 'DRAM +303%' / '增长249.5%'. Best-effort
        prose scan; observability → forecast.quality. (Sub-market>parent & future-dated earnings
        need structured facts → handled in the research quant sanity gate.)"""
        import re as _re
        md = report_markdown or ""
        flags: List[str] = []
        cited_extremes: List[str] = []
        pat = _re.compile(
            r'(?:\+|增长|增幅|同比|环比|growth|increase|surg\w*|yoy|year[\- ]over[\- ]year)'
            r'[^0-9%]{0,10}([0-9]{3,4}(?:\.[0-9]+)?)\s*%', _re.I)
        for m in pat.finditer(md):
            try:
                v = float(m.group(1))
            except ValueError:
                continue
            if v > 100:
                ctx = md[max(0, m.start() - 24):m.start() + 14].replace("\n", " ").strip()
                item = f"{v:.0f}% growth near '…{ctx}…'"
                line_start = md.rfind("\n", 0, m.start()) + 1
                line_end = md.find("\n", m.end())
                if line_end < 0:
                    line_end = len(md)
                if self._S_CITATION_RE.search(md[line_start:line_end]):
                    cited_extremes.append(item)
                else:
                    flags.append(item)
        # dedup
        seen = set(); uniq = []
        for f in flags:
            if f not in seen:
                seen.add(f); uniq.append(f)
        _flag_vals = []
        for f in flags:
            m = _re.search(r"([0-9]+(?:\.[0-9]+)?)% growth", f)
            if m:
                _flag_vals.append(float(m.group(1)))
        return {
            "implausible_stats": uniq[:8],
            "count": len(uniq),
            "max_flagged": max(_flag_vals) if _flag_vals else 0.0,
            "cited_extreme_stats": cited_extremes[:8],
        }

    def _audit_numeric_consistency(self, report_markdown: str, forecast: Dict[str, Any]) -> Dict[str, Any]:
        """QUALITY-OPT S11: flag prose scenario-probabilities that disagree with forecast.json
        by >1pt (the 42/21/15/11/11-vs-38/17/13/12/20 failure). forecast.json is the single
        source of truth; prose must match it. Observability → forecast.quality. Best-effort."""
        import re as _re
        if not isinstance(forecast, dict):
            return {}
        md = report_markdown or ""
        issues: List[str] = []
        for s in (forecast.get("scenarios") or []):
            if not isinstance(s, dict):
                continue
            name = str(s.get("name") or "").strip()
            try:
                p = round(float(s.get("probability") or 0.0) * 100)
            except (TypeError, ValueError):
                continue
            if len(name) < 4:
                continue
            idx = md.find(name)
            if idx < 0:
                continue
            window = md[max(0, idx - 18):idx + len(name) + 55]
            pcts = []
            for m in _re.finditer(r'(\d{1,3})\s*%', window):
                try:
                    pv = int(m.group(1))
                except ValueError:
                    continue
                if 0 <= pv <= 100:
                    pcts.append(pv)
            if not pcts:
                continue
            if any(abs(pv - p) <= 1 for pv in pcts):
                continue  # a nearby percentage matches forecast.json → consistent
            near = [pv for pv in pcts if abs(pv - p) <= 60]
            if near:
                pv = min(near, key=lambda x: abs(x - p))
                issues.append(f"scenario '{name[:28]}': prose {pv}% vs forecast.json {p}%")
        return {"scenario_prob_mismatches": issues[:8], "mismatch_count": len(issues)}

    def _lang_override(self) -> str:
        """QUALITY-OPT B0: a hard output-language directive prepended to every plan/section
        system prompt. It explicitly OVERRIDES the template's legacy 'mirror the source
        language / write in Chinese' rule, so an English brief yields an English submission."""
        lang = getattr(self, "output_language", None) or "English"
        return (
            "═══ ABSOLUTE OUTPUT-LANGUAGE RULE (overrides every other language instruction below) ═══\n"
            f"Write the ENTIRE report — every heading, sentence, table cell, and quotation — in {lang}. "
            f"Translate any tool / interview / source output into {lang} before using it. Never switch "
            "languages mid-report. This rule takes precedence over any instruction to mirror the source "
            "language.\n\n"
        )

    # RQ-2 语言纯度：CJK 字符类（含中日韩统一表意 + 扩展A + 假名 + 谚文）。
    _CJK_CHAR = r"一-鿿㐀-䶿぀-ヿ가-힯"
    _CJK_RUN_RE = re.compile(
        r"[" + _CJK_CHAR + r"]" + r"[" + _CJK_CHAR + r"\s，。、；：？！…（）「」『』《》%\d\.\-]*")
    # 长英文散文片段（>=40 字符且含 >=4 空格 ⇒ 5+ 词），避开品牌/型号/代号等短拉丁 token。
    _LATIN_RUN_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,.'’\-()%/&]{39,}")
    # Protect URL destinations and inline code while still scanning the human-readable
    # Markdown around them (headings, quotes, table cells, and link labels included).
    _LANG_INLINE_PROTECTED_RE = re.compile(r"`[^`\n]*`|https?://[^\s)>\]}]+", re.I)

    def _collect_impurity_segments(self, chunk_md: str, target_is_cjk: bool,
                                   cap: int = 60) -> List[str]:
        """Collect foreign-language text from structured Markdown outside fences.

        Headings, blockquotes, table cells, and URL-bearing prose are report text and
        must be scanned. URL destinations and inline-code tokens are masked rather than
        skipping their whole line, so repair cannot corrupt links/code.
        """
        segments: List[str] = []
        seen = set()
        in_fence = False
        for line in (chunk_md or "").splitlines():
            s = line.strip()
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence or not s:
                continue
            scan_line = self._LANG_INLINE_PROTECTED_RE.sub(" ", line)
            if target_is_cjk:
                candidates = self._LATIN_RUN_RE.findall(scan_line)
                candidates = [c for c in candidates if c.count(" ") >= 4]
            else:
                candidates = self._CJK_RUN_RE.findall(scan_line)
            for c in candidates:
                seg = c.strip().strip("（）()「」\"'“”")
                if len(seg) < 2:
                    continue
                if (not target_is_cjk) and len(re.findall(r"[" + self._CJK_CHAR + r"]", seg)) < 2:
                    continue
                seg = seg[:300]
                if seg and seg not in seen:
                    seen.add(seg)
                    segments.append(seg)
                if len(segments) >= cap:
                    break
            if len(segments) >= cap:
                break
        return segments

    def _translate_impurity_segments(
        self, segments: List[str], language: str
    ) -> List[Tuple[str, str]]:
        """Translate impurity segments in bounded batches with byte-exact token safety.

        The former single 60-item / 4096-token JSON call routinely returned a
        truncated mapping, leaving the tail untranslated.  Batches are isolated:
        one malformed response loses only that batch, and successful batches still
        feed the final replacement pass.

        NUMERIC / CITATION INTEGRITY — this contamination-repair pass re-translates
        residual source-language prose, and MiniMax-class models routinely drift the
        numbers inside such prose (drop one, introduce a stray decimal, or render a
        figure as a CJK numeral / unit word).  That drift is exactly the
        "translation numeric-token multiset differs from primary" audit failure, so
        every immutable token (numbers, percentages, [S#] citations, inline code,
        URLs, comments) is placeholder-protected BEFORE the model sees the segment and
        restored byte-for-byte AFTER.  A restored candidate is accepted only when it
        preserves the source segment's number AND citation multiset exactly; any
        candidate that dropped a placeholder or introduced a bare Arabic numeral is
        discarded (the segment stays contaminated and is retried or fails closed,
        never silently corrupting the numeric multiset).
        """
        if not segments:
            return []
        try:
            batch_size = int(
                getattr(Config, "REPORT_PURITY_TRANSLATION_BATCH_SIZE", 20) or 20
            )
        except (TypeError, ValueError):
            batch_size = 20
        batch_size = max(5, min(30, batch_size))
        # Protect immutable tokens per segment; the model only ever sees ⟦…⟧ opaque /
        # self-describing placeholders in place of numbers, citations, code and URLs.
        protected: List[Tuple[str, str, List[Tuple[str, str]]]] = []
        for segment in segments:
            hidden, seg_map = self._protect_translation_tokens(segment)
            protected.append((segment, hidden, seg_map))
        mapping: List[Tuple[str, str]] = []

        def _accepted_translation(
            segment: str,
            candidate: Any,
            seg_map: List[Tuple[str, str]],
        ) -> Optional[str]:
            """Restore and validate one batch or single-fragment candidate.

            COST-1(d): number parity here folds formatting-only equivalences
            (thousands separators, full-width digits) — a translation that renders
            "1,000" as "1000" or "１０００" as "1000" preserves the value and must
            not be force-escalated; any digit-content change still mismatches and
            is rejected. The bilingual whole-report path keeps the strict
            byte-level multiset (fold_formatting defaults to False there).
            """
            if not isinstance(candidate, str) or not candidate.strip():
                return None
            restored, issues = self._restore_translation_tokens(
                candidate.strip(), seg_map, fold_formatting=True
            )
            restored = restored.strip()
            if not restored or restored == segment or issues:
                return None
            if self._folded_number_multiset(
                restored
            ) != self._folded_number_multiset(segment):
                return None
            if self._translation_marker_multiset(
                restored
            ) != self._translation_marker_multiset(segment):
                return None
            return restored

        sys_prompt = (
            f"You are a precise translator. Translate each numbered segment into {language}. "
            "Tokens shaped ⟦P…⟧, ⟦X…⟧, or ⟦F…⟧ are immutable source bytes (numbers, "
            "percentages, [S#] citations, code, URLs): copy every placeholder exactly once, "
            "verbatim, and never translate, alter, split, reorder, or drop one. Do NOT add any "
            "new Arabic numerals — all source numbers are already inside placeholders. Keep "
            "proper nouns as-is. Return ONLY a JSON object mapping each segment index (as a "
            f'string) to its {language} translation, e.g. {{"1": "...", "2": "..."}}.'
        )
        for start in range(0, len(protected), batch_size):
            batch = protected[start:start + batch_size]
            numbered = "\n".join(
                f"{index}. {hidden}" for index, (_seg, hidden, _m) in enumerate(batch, 1)
            )
            try:
                parsed = self.llm.chat_json(
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": numbered},
                    ],
                    temperature=0.0,
                    max_tokens=4096,
                    tier="fast",
                )
            except Exception as exc:  # noqa: BLE001 — one bad batch must not discard prior work
                logger.warning(
                    f"语言纯度：片段翻译批次 {start // batch_size + 1} 失败（保留该批原文）: {exc}"
                )
                continue
            if not isinstance(parsed, dict):
                continue
            for index, (segment, _hidden, seg_map) in enumerate(batch, 1):
                raw = parsed.get(str(index)) or parsed.get(index)
                accepted = _accepted_translation(segment, raw, seg_map)
                if accepted is not None:
                    mapping.append((segment, accepted))

        # Repeating the same temperature-zero JSON batch cannot recover a deterministic
        # echo/truncation. Escalate only unresolved fragments through the module's proven
        # prose-slot protocol, retaining the exact same token-integrity boundary above.
        # COST-1: escalation is one strong-tier chat call PER SEGMENT, each carrying the
        # provider's full retry ladder, and _apply_language_purity can feed up to
        # REPORT_PURITY_MAX_SEGMENTS (180) segments here — so this path is (a) skipped
        # wholesale when the provider lacks .chat, (b) hard-capped per report, and
        # (c) short-circuited after 3 consecutive call failures (provider-down signal).
        resolved_segments = {segment for segment, _translation in mapping}
        unresolved = [item for item in protected if item[0] not in resolved_segments]
        if unresolved and not hasattr(self.llm, "chat"):
            # COST-1(a): stub/degraded provider without .chat — skip escalation entirely,
            # keep originals, and say so once (not one swallowed AttributeError per segment).
            logger.info(
                "语言纯度：LLM 无 chat 接口，跳过 %d 个未解决片段的逐段升级（保留原文）",
                len(unresolved),
            )
            unresolved = []
        try:
            escalation_cap = int(
                getattr(Config, "REPORT_PURITY_ESCALATION_MAX", 12) or 12
            )
        except (TypeError, ValueError):
            escalation_cap = 12
        escalation_cap = max(0, escalation_cap)
        escalated = 0
        accepted_escalations = 0
        consecutive_call_failures = 0
        for position, (segment, hidden, seg_map) in enumerate(unresolved):
            if escalated >= escalation_cap:
                # COST-1(b): per-report escalation budget exhausted — the rest keep
                # their original text (the final read-only purity audit still gates).
                logger.info(
                    "语言纯度：逐段升级达到上限 %d，其余 %d 个片段保留原文",
                    escalation_cap, len(unresolved) - position,
                )
                break
            if consecutive_call_failures >= 3:
                # COST-1(c): 3 consecutive escalation CALL failures (exceptions, not
                # validation rejects) ⇒ provider outage — stop escalating this report.
                logger.warning(
                    "语言纯度：连续 %d 次逐段升级调用失败——判定提供方故障，"
                    "停止本报告的逐段升级（其余 %d 个片段保留原文）",
                    consecutive_call_failures, len(unresolved) - position,
                )
                break
            escalated += 1
            try:
                raw = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Translate this one Markdown prose fragment into "
                                f"{language}. Preserve its Markdown punctuation. Copy every "
                                "⟦…⟧ placeholder token exactly once, verbatim. Output ONLY "
                                "the translated fragment. Do not add Arabic numerals, URLs, "
                                "citations, code, or commentary. Keep proper nouns as-is."
                            ),
                        },
                        {"role": "user", "content": hidden},
                    ],
                    temperature=0.0,
                    max_tokens=max(512, min(4096, len(hidden) * 2 + 512)),
                    tier="strong",
                )
            except Exception as exc:  # noqa: BLE001 — final bounded fragment attempt
                consecutive_call_failures += 1
                logger.warning("语言纯度：单片段翻译调用失败（保留原文）: %s", exc)
                continue
            consecutive_call_failures = 0  # 调用成功 ⇒ 提供方存活；校验拒绝不计入短路
            candidate = str(raw or "").strip()
            if candidate.startswith("```"):
                candidate = re.sub(
                    r"^```(?:markdown|md)?\s*", "", candidate, flags=re.I
                )
                candidate = re.sub(r"\s*```$", "", candidate).strip()
            accepted = _accepted_translation(segment, candidate, seg_map)
            if accepted is not None:
                mapping.append((segment, accepted))
                accepted_escalations += 1
        if escalated:
            logger.info(
                "语言纯度：逐段升级 %d/%d 个未解决片段（采纳 %d，保留原文 %d）",
                escalated, len(unresolved), accepted_escalations,
                len(unresolved) - accepted_escalations,
            )
        # Longest first so a short phrase cannot split a longer one before it is replaced.
        mapping.sort(key=lambda item: len(item[0]), reverse=True)
        return mapping

    def _apply_language_purity(self, report_id: str, report: "Report") -> None:
        """RQ-2：成稿语言纯度扫描。目标语言为非 CJK（英文）时检测残留 CJK 片段，反之检测残留长
        英文散文片段；有界批次 chat_json 调用译成目标语言并逐行内联替换。引用型片段也只保留
        目标语言译文（否则所谓“纯度修复”会故意重新注入污染）。无片段或任何错误一律
        degrade-safe 跳过（保留原文），并改写
        full_report.md。幂等：纯净成稿命中零片段即为 no-op。

        WAVE9：按 H2 块统计污染密度——单块片段数 > REPORT_PURITY_RETRANSLATE_SEGMENTS 时
        该块**整章重译**（走 _translate_section，结构无损），不再做子串内联补丁（子串补丁在
        重污染章节上产出 'SK SK Hynix' 型混合垃圾）；轻污染块仍走历史内联路径。"""
        try:
            if not getattr(Config, "REPORT_LANGUAGE_PURITY", True):
                return
            llm = getattr(self, "llm", None)
            if llm is None or not hasattr(llm, "chat_json"):
                return
            md = report.markdown_content or ""
            if not md.strip():
                return
            lang = getattr(self, "output_language", None) or "English"
            target_is_cjk = not str(lang).strip().lower().startswith("en")

            # 1) 按 H2 块采集污染片段；重污染块记入整章重译名单（有界：至多 6 块）。
            try:
                retrans_thresh = int(getattr(Config, "REPORT_PURITY_RETRANSLATE_SEGMENTS",
                                             8) or 8)
            except (TypeError, ValueError):
                retrans_thresh = 8
            chunks = self._split_markdown_h2_sections(md)
            retranslate_idx: List[int] = []
            for ci, chunk in enumerate(chunks):
                chunk_segments = self._collect_impurity_segments(chunk, target_is_cjk)
                if retrans_thresh > 0 and len(chunk_segments) > retrans_thresh \
                        and len(retranslate_idx) < 6 and hasattr(llm, "chat"):
                    retranslate_idx.append(ci)

            # 1b) 整章重译重污染块（结构无损；失败保留原块）。
            retranslated = 0
            if retranslate_idx:
                tgt_name = ("简体中文（Simplified Chinese）" if target_is_cjk
                            else "professional analyst-grade English")
                for ci in retranslate_idx:
                    try:
                        new_chunk = self._translate_section(chunks[ci], tgt_name)
                    except Exception as _rte:  # noqa: BLE001 — 单块重译失败保留原块
                        logger.warning(f"语言纯度：重污染块整章重译失败（保留原块）: {_rte}")
                        continue
                    if new_chunk and new_chunk.strip() and new_chunk != chunks[ci]:
                        chunks[ci] = new_chunk
                        retranslated += 1
                if retranslated:
                    md = "\n".join(chunks)
                    report.markdown_content = md
                    logger.info(
                        f"语言纯度扫描: {report_id} 重污染章节整章重译 {retranslated} 块"
                        f"（阈值 >{retrans_thresh} 片段/块）")
                    # 立即落盘——后续内联路径存在多个 degrade-safe 早退点，不能指望末尾的回写。
                    try:
                        folder = ReportManager._get_report_folder(report_id)
                        write_text_atomic(os.path.join(folder, "full_report.md"), md)
                    except Exception as _we:  # noqa: BLE001
                        logger.warning(f"回写语言纯度成稿 full_report.md 失败（忽略）: {_we}")
            # 2) Re-scan the CURRENT chunks after whole-section translation.  The
            # previous implementation skipped heavy chunks forever, even when the
            # section translator left residual CJK/English lines behind.
            try:
                max_segments = int(
                    getattr(Config, "REPORT_PURITY_MAX_SEGMENTS", 180) or 180
                )
            except (TypeError, ValueError):
                max_segments = 180
            max_segments = max(1, min(600, max_segments))

            def _scan(current: str) -> List[str]:
                found: List[str] = []
                seen = set()
                for chunk in self._split_markdown_h2_sections(current):
                    remaining = max_segments - len(found)
                    if remaining <= 0:
                        break
                    for segment in self._collect_impurity_segments(
                        chunk, target_is_cjk, cap=min(60, remaining)
                    ):
                        if segment not in seen:
                            seen.add(segment)
                            found.append(segment)
                return found

            segments = _scan(md)
            if not segments:
                if md != (report.markdown_content or ""):
                    report.markdown_content = md
                return

            def _replace(current: str, replacements: List[Tuple[str, str]]) -> Tuple[str, int]:
                # Quotes are translated too; retaining the original in parentheses
                # would knowingly fail the final purity audit.
                in_fence = False
                count = 0
                out_lines: List[str] = []
                for line in current.splitlines():
                    if line.strip().startswith("```"):
                        in_fence = not in_fence
                        out_lines.append(line)
                        continue
                    if in_fence:
                        out_lines.append(line)
                        continue
                    protected: List[str] = []

                    def _mask_inline(
                        match: "re.Match[str]", *, _protected: List[str] = protected
                    ) -> str:
                        _protected.append(match.group(0))
                        return f"\x00LANGPROTECTED{len(_protected) - 1}\x00"

                    new_line = self._LANG_INLINE_PROTECTED_RE.sub(_mask_inline, line)
                    for original, translated in replacements:
                        if original not in new_line:
                            continue
                        new_line = new_line.replace(original, translated)
                        count += 1
                    for protected_index, token in enumerate(protected):
                        new_line = new_line.replace(
                            f"\x00LANGPROTECTED{protected_index}\x00", token
                        )
                    out_lines.append(new_line)
                return "\n".join(out_lines), count

            # 3) Bounded batch translation + one bounded residual repair sweep.
            # The second scan catches truncated/mixed translations without creating
            # an open-ended self-repair loop; the final read-only audit remains the
            # authoritative purity gate if anything still survives.
            new_md = md
            replaced = 0
            mapped_kinds = 0
            pending = segments
            for _repair_round in range(2):
                mapping = self._translate_impurity_segments(pending, lang)
                if not mapping:
                    break
                candidate, round_replaced = _replace(new_md, mapping)
                if not round_replaced or candidate == new_md:
                    break
                new_md = candidate
                replaced += round_replaced
                mapped_kinds += len(mapping)
                pending = _scan(new_md)
                if not pending:
                    break
            if not replaced:
                # Whole-section translations, if any, were already persisted above.
                return
            if new_md == md:
                return
            report.markdown_content = new_md
            try:
                folder = ReportManager._get_report_folder(report_id)
                write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
            except Exception as _we:  # noqa: BLE001
                logger.warning(f"回写语言纯度成稿 full_report.md 失败（忽略）: {_we}")
            logger.info(
                f"语言纯度扫描: {report_id} 目标语言 {lang}，内联翻译 {mapped_kinds} 类片段"
                f"（{replaced} 处替换）")
        except Exception as _lpe:  # noqa: BLE001 — 纯度扫描为旁路增强，失败保留原文
            logger.warning(f"语言纯度扫描失败（忽略，保留原文）: {_lpe}")

    def _apply_report_lint(self, report_id: str, report: "Report") -> None:
        """WAVE9：确定性编辑纪律 lint（report_lint.lint_report）——修复 passes 之后、
        双语翻译之前的最后一道确定性清理：引用残留 / 边转储 / 旧模拟标签 / 孤悬归因行 /
        引用记号变体 / 重复整句等。lint 报告 dict 记入 forecast.json 的 quality['lint']。

        完全 degrade-safe：任何失败仅告警，保留原成稿。"""
        from . import report_lint as _rl
        md = report.markdown_content or ""
        if not md.strip():
            return
        lang = getattr(self, "output_language", None) or "English"
        spine = self._forecast_spine if isinstance(getattr(self, "_forecast_spine", None),
                                                   dict) else None
        cleaned, lint_rep = _rl.lint_report(md, lang, mode="final", spine=spine)
        if lint_rep.get("changed") and cleaned.strip():
            report.markdown_content = cleaned
            try:
                folder = ReportManager._get_report_folder(report_id)
                write_text_atomic(os.path.join(folder, "full_report.md"), cleaned)
            except Exception as _we:  # noqa: BLE001
                logger.warning(f"回写编辑 lint 成稿 full_report.md 失败（忽略）: {_we}")
        # lint 报告并入 forecast.json 的 quality（读-改-写；文件缺失/损坏时仅记内存副本）。
        try:
            fpath = os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
            if os.path.exists(fpath):
                with open(fpath, "r", encoding="utf-8") as f:
                    fc = json.load(f)
                if isinstance(fc, dict):
                    fc.setdefault("quality", {})["lint"] = lint_rep
                    write_text_atomic(fpath, json.dumps(fc, ensure_ascii=False, indent=2))
                    if isinstance(getattr(self, "_forecast_spine", None), dict):
                        self._forecast_spine.setdefault("quality", {})["lint"] = lint_rep
        except Exception as _fe:  # noqa: BLE001 — quality 记录失败不影响成稿
            logger.warning(f"编辑 lint 报告写入 forecast.json 失败（忽略）: {_fe}")
        logger.info(
            f"编辑 lint: {report_id} changed={lint_rep.get('changed')} "
            f"引用残留 {lint_rep.get('citation_residue')}｜边转储 {lint_rep.get('edge_dumps')}"
            f"｜旧标签 {lint_rep.get('legacy_sim_labels')}｜孤悬归因 "
            f"{lint_rep.get('dangling_attributions')}｜重复句 "
            f"{lint_rep.get('duplicate_sentences_removed')}｜泄漏残留 {lint_rep.get('leakage_flags')}"
        )

    # ──────────────────────────────────────────────────────────────
    # BILINGUAL：自动生成成稿的另一语种版本（英⇄中），逐 H2 章节并发翻译
    # ──────────────────────────────────────────────────────────────
    # 译文数字完整性：提示词要求所有数字逐字节保留，因此不只校验百分比。
    # 边界避免从标识符中拆数；逗号千分位/小数/正负号/% 保持为一个 token。
    _NUMBER_INTEGRITY_RE = re.compile(
        r"(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
        r"(?:\.\d+)?(?:\s*%)?"
    )
    _TRANSLATION_FENCE_RE = re.compile(
        r"^(?P<marker>```|~~~)[^\n]*\n.*?^(?P=marker)[ \t]*$",
        re.MULTILINE | re.DOTALL,
    )
    _TRANSLATION_INLINE_PROTECTED_RE = re.compile(
        r"<!--.*?-->"
        r"|`[^`\n]+`"
        r"|(?<=\]\()[^)\s]+(?=\))"
        r"|https?://[^\s<>()]+"
        r"|[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】]"
        r"|(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
        r"(?:\.\d+)?(?:\s*%)?",
        re.IGNORECASE | re.DOTALL,
    )
    _TRANSLATION_ENCODED_PLACEHOLDER_RE = re.compile(
        r"⟦P[A-Z]+:([A-Za-z0-9_-]+)⟧"
    )
    _TRANSLATION_SELF_DESCRIBING_RE = re.compile(
        r"(?:[\[【]\s*S\d+(?:-[A-Za-z])?\s*[\]】])"
        r"|(?:(?<![A-Za-z0-9_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)"
        r"(?:\.\d+)?(?:\s*%)?)",
        re.IGNORECASE,
    )

    @staticmethod
    def _translation_placeholder_suffix(index: int) -> str:
        """Return a digit-free base-26 identifier so placeholders add no numbers."""
        value = max(0, int(index)) + 1
        out = ""
        while value:
            value, remainder = divmod(value - 1, 26)
            out = chr(65 + remainder) + out
        return out

    @classmethod
    def _protect_translation_tokens(
        cls, markdown: str
    ) -> Tuple[str, List[Tuple[str, str]]]:
        """Hide immutable bytes from the model and return their exact mapping.

        Fenced blocks, comments, code and links use compact opaque IDs because
        they can be large. Citations and numbers use short self-describing
        base64url placeholders so deterministic fakes can exercise drift repair.
        Keeping every placeholder short materially reduces copy errors and model
        timeouts on evidence-dense tables.
        """
        import base64

        mapping: List[Tuple[str, str]] = []

        def _fence(match: "re.Match") -> str:
            suffix = cls._translation_placeholder_suffix(len(mapping))
            placeholder = f"⟦F{suffix}⟧"
            mapping.append((placeholder, match.group(0)))
            return placeholder

        protected = cls._TRANSLATION_FENCE_RE.sub(_fence, markdown or "")

        def _inline(match: "re.Match") -> str:
            raw = match.group(0)
            suffix = cls._translation_placeholder_suffix(len(mapping))
            if cls._TRANSLATION_SELF_DESCRIBING_RE.fullmatch(raw):
                encoded = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii")
                encoded = encoded.rstrip("=")
                placeholder = f"⟦P{suffix}:{encoded}⟧"
            else:
                placeholder = f"⟦X{suffix}⟧"
            mapping.append((placeholder, raw))
            return placeholder

        protected = cls._TRANSLATION_INLINE_PROTECTED_RE.sub(_inline, protected)
        return protected, mapping

    @classmethod
    def _decode_translation_placeholders(cls, text: str) -> str:
        """Decode self-describing inline placeholders; opaque fences remain."""
        import base64

        def _decode(match: "re.Match") -> str:
            encoded = match.group(1)
            try:
                padded = encoded + ("=" * (-len(encoded) % 4))
                return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            except (ValueError, UnicodeDecodeError):
                return match.group(0)

        return cls._TRANSLATION_ENCODED_PLACEHOLDER_RE.sub(_decode, text or "")

    @classmethod
    def _restore_translation_tokens(
        cls, candidate: str, mapping: List[Tuple[str, str]],
        fold_formatting: bool = False,
    ) -> Tuple[str, List[str]]:
        """Restore placeholders and report unaccounted/duplicated immutable tokens.

        ``fold_formatting=True`` (language-purity segment repair only) counts a
        bare numeric rendering that differs solely in thousands separators or
        full-width digits as accounting for its placeholder (COST-1(d)); the
        default keeps the strict byte-level accounting the bilingual path pins.
        """
        from collections import Counter, defaultdict

        original = candidate or ""
        restored = original
        issues: List[str] = []
        by_raw: Dict[str, List[str]] = defaultdict(list)
        for placeholder, raw in mapping:
            by_raw[raw].append(placeholder)

        if fold_formatting:
            numeric_counts = Counter(cls._folded_number_multiset(original))
        else:
            numeric_counts = Counter(cls._translation_number_multiset(original))
        marker_counts = Counter(cls._translation_marker_multiset(original))
        for raw, placeholders in by_raw.items():
            normalized_number = (
                cls._fold_number_token(raw) if fold_formatting
                else cls._normalize_number_token(raw)
            )
            if cls._NUMBER_INTEGRITY_RE.fullmatch(raw):
                raw_count = int(numeric_counts.get(normalized_number, 0))
            else:
                marker_match = re.fullmatch(
                    r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]", raw, re.I
                )
                if marker_match:
                    raw_count = int(marker_counts.get(marker_match.group(1).upper(), 0))
                else:
                    raw_count = original.count(raw)
            represented = raw_count + sum(original.count(item) for item in placeholders)
            expected = len(placeholders)
            if represented < expected:
                issues.append(f"missing:{placeholders[0]}")
            elif represented > expected:
                issues.append(f"duplicated:{placeholders[0]}")

        for placeholder, raw in mapping:
            count = restored.count(placeholder)
            if count:
                restored = restored.replace(placeholder, raw)
        return restored, issues

    @classmethod
    def _split_translation_units(cls, markdown: str, max_chars: int = 4200) -> List[str]:
        """Split a large H2 section at paragraph boundaries without losing text.

        A single table or fenced block is never cut mid-block. This keeps model
        calls bounded while preserving enough paragraph context for fluent prose.
        Joining the returned units with two newlines reproduces the normalized
        input exactly.
        """
        text = markdown or ""
        if len(text) <= max_chars:
            return [text]
        # Protect complete fenced blocks *before* looking for paragraph breaks.
        # A fence may legally contain blank lines; splitting first turns it into
        # unmatched halves that the later token-protection pass cannot recognize.
        fences: List[Tuple[str, str]] = []

        def _hide_fence(match: "re.Match") -> str:
            token = f"\x00DRF_FENCE_{cls._translation_placeholder_suffix(len(fences))}\x00"
            fences.append((token, match.group(0)))
            return token

        protected = cls._TRANSLATION_FENCE_RE.sub(_hide_fence, text)
        paragraphs = re.split(r"\n{2,}", protected)
        units: List[str] = []
        current = ""
        for paragraph in paragraphs:
            candidate = paragraph if not current else f"{current}\n\n{paragraph}"
            if current and len(candidate) > max_chars:
                units.append(current)
                current = paragraph
            else:
                current = candidate
        if current or not units:
            units.append(current)
        return [
            cls._restore_hidden_translation_fences(unit, fences)
            for unit in units
        ]

    @staticmethod
    def _restore_hidden_translation_fences(
        text: str, fences: List[Tuple[str, str]]
    ) -> str:
        restored = text
        for token, fence in fences:
            restored = restored.replace(token, fence)
        return restored

    # Structural line grammar used by the structure-preserving translator.  Every
    # scaffold byte (heading hashes, list markers, blockquote arrows, table pipes)
    # is copied verbatim; only the natural-language core of each unit becomes a
    # translatable slot, so heading levels, table row/column counts and fenced
    # blocks are identical to the source *by construction*, never by audit luck.
    _STRUCT_HEADING_RE = re.compile(r"^(#{1,6}[ \t]+)(.*?)([ \t]*)$")
    _STRUCT_LIST_RE = re.compile(r"^([ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+)(.*)$")
    _STRUCT_QUOTE_RE = re.compile(r"^([ \t]*>+[ \t]?)(.*)$")
    _STRUCT_INDENT_RE = re.compile(r"^([ \t]*)(.*)$")
    _STRUCT_TABLE_SEP_RE = re.compile(r"^[ \t]*\|?[ \t:\-|]+\|?[ \t]*$")
    _STRUCT_SLOT_RE = re.compile("\x00SLOT([A-Z]+)\x00")

    @classmethod
    def _translation_placeholder_multiset(cls, text: str) -> Dict[str, int]:
        """Return the multiset of immutable ⟦…⟧ placeholders in a slot candidate."""
        from collections import Counter

        return dict(Counter(re.findall(r"⟦[^⟧]*⟧", text or "")))

    @classmethod
    def _build_structural_slots(
        cls, protected: str
    ) -> Tuple[str, Dict[str, str]]:
        """Split token-protected markdown into a scaffold template + prose slots.

        The returned ``template`` reproduces the source line-for-line with every
        translatable core replaced by a unique ``\\x00SLOTkey\\x00`` marker.  Only
        cores that actually contain letters become slots; pure number/citation
        placeholder cells stay literal so the model never touches them.  Restoring
        the template with translated slots preserves the exact heading/list/table
        pipe skeleton, so structural parity cannot drift.
        """
        slots: Dict[str, str] = {}

        def _mk(core: str) -> str:
            key = cls._translation_placeholder_suffix(len(slots))
            slots[key] = core
            return f"\x00SLOT{key}\x00"

        def _has_translatable_text(core: str) -> bool:
            # Ignore letters that belong to an immutable ⟦…⟧ placeholder (e.g. the
            # fence token ⟦FA⟧).  A line that is only placeholders / punctuation /
            # numbers must stay literal, or the model could append content that
            # corrupts a restored fence/URL boundary.
            stripped = re.sub(r"⟦[^⟧]*⟧", "", core)
            return any(ch.isalpha() for ch in stripped)

        def _slot_or_literal(core: str) -> str:
            # A protected fence/comment/code placeholder or a pure number cell has
            # no translatable letters — keep it literal so structure survives untouched.
            return _mk(core) if _has_translatable_text(core) else core

        out_lines: List[str] = []
        for line in protected.split("\n"):
            stripped = line.strip()
            if not stripped:
                out_lines.append(line)
                continue
            # Markdown table row (pipe-delimited) — never a heading/list.  Split on
            # unescaped pipes, translate each lettered cell in place, and rejoin with
            # the identical pipe skeleton so the column count is byte-preserved.
            if stripped.startswith("|") and stripped.count("|") >= 2:
                if cls._STRUCT_TABLE_SEP_RE.match(line):
                    out_lines.append(line)
                    continue
                cells = re.split(r"(?<!\\)\|", line)
                rebuilt: List[str] = []
                for cell in cells:
                    core = cell.strip()
                    if not core or not _has_translatable_text(core):
                        rebuilt.append(cell)
                        continue
                    lead = cell[: len(cell) - len(cell.lstrip())]
                    trail = cell[len(cell.rstrip()):]
                    rebuilt.append(lead + _mk(core) + trail)
                out_lines.append("|".join(rebuilt))
                continue
            heading = cls._STRUCT_HEADING_RE.match(line)
            if heading:
                out_lines.append(
                    heading.group(1) + _slot_or_literal(heading.group(2)) + heading.group(3)
                )
                continue
            listed = cls._STRUCT_LIST_RE.match(line)
            if listed:
                out_lines.append(listed.group(1) + _slot_or_literal(listed.group(2)))
                continue
            quoted = cls._STRUCT_QUOTE_RE.match(line)
            if quoted and quoted.group(1).strip():
                out_lines.append(quoted.group(1) + _slot_or_literal(quoted.group(2)))
                continue
            indent = cls._STRUCT_INDENT_RE.match(line)
            out_lines.append(indent.group(1) + _slot_or_literal(indent.group(2)))
        return "\n".join(out_lines), slots

    def _resolve_prose_slots(
        self, slots: Dict[str, str], target_language_name: str
    ) -> Dict[str, str]:
        """Translate keyed prose cores; keep only structurally faithful candidates.

        A candidate is accepted only when it (1) is non-empty, (2) carries the exact
        same ⟦…⟧ placeholder multiset as its source core, and (3) introduces no bare
        Arabic-number or citation token.  Because the immutable tokens are already
        placeholders, this guarantees the reassembled document keeps the source
        numeric/citation multiset.  Rejected cores fall back to the source text and
        are handled by the later contamination-repair pass, never by silent drift.
        """
        def _accept(core: str, candidate: str, *, allow_echo: bool) -> bool:
            if not isinstance(candidate, str) or not candidate.strip():
                return False
            if self._translation_placeholder_multiset(
                candidate
            ) != self._translation_placeholder_multiset(core):
                return False
            if self._translation_number_multiset(candidate):
                return False
            if self._translation_marker_multiset(candidate):
                return False
            if not allow_echo and candidate.strip() == core.strip():
                return False
            return True

        resolved: Dict[str, str] = {}
        pending = [
            key for key in slots
            if any(ch.isalpha() for ch in re.sub(r"⟦[^⟧]*⟧", "", slots[key]))
        ]
        for attempt in range(2):
            if not pending:
                break
            batch_size = 16 if attempt == 0 else 4
            next_pending: List[str] = []
            for offset in range(0, len(pending), batch_size):
                keys = pending[offset:offset + batch_size]
                request = {key: slots[key] for key in keys}
                sys_prompt = (
                    "Translate every JSON string value into "
                    f"{target_language_name}. Return ONLY one valid JSON object with the exact "
                    "same alphabetic keys. Preserve Markdown punctuation and newlines inside "
                    "each value. Copy every ⟦…⟧ placeholder token exactly once, verbatim, and "
                    "never translate, split, reorder, or remove one. Do not add Arabic numerals, "
                    "URLs, citations, code, comments, or keys inside translated values."
                )
                raw = ""
                try:
                    raw = self.llm.chat(
                        messages=[
                            {"role": "system", "content": sys_prompt},
                            {
                                "role": "user",
                                "content": json.dumps(request, ensure_ascii=False),
                            },
                        ],
                        temperature=0.0,
                        max_tokens=max(1024, min(8192, len(json.dumps(request)) + 1024)),
                        tier="strong",
                    )
                except Exception as exc:  # noqa: BLE001 — bounded fallback retries below
                    logger.warning("双语报告：结构骨架 prose-slot 翻译调用失败: %s", exc)
                text = str(raw or "").strip()
                if text.startswith("```"):
                    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
                    text = re.sub(r"\s*```$", "", text)
                parsed: Any = None
                try:
                    parsed = json.loads(text)
                except (TypeError, ValueError):
                    start, end_pos = text.find("{"), text.rfind("}")
                    if start >= 0 and end_pos > start:
                        try:
                            parsed = json.loads(text[start:end_pos + 1])
                        except (TypeError, ValueError):
                            parsed = None
                parsed = parsed if isinstance(parsed, dict) else {}
                for key in keys:
                    candidate = parsed.get(key)
                    if _accept(slots[key], candidate, allow_echo=False):
                        resolved[key] = candidate.replace("\n", " ")
                    else:
                        next_pending.append(key)
            pending = list(dict.fromkeys(next_pending))

        # A keyed JSON batch can still omit one value; retry those cores one by one.
        for key in pending:
            core = slots[key]
            raw = ""
            try:
                raw = self.llm.chat(
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "Translate this one Markdown prose fragment into "
                                f"{target_language_name}. Preserve its Markdown punctuation. "
                                "Copy every ⟦…⟧ placeholder token exactly. Output ONLY the "
                                "translated fragment. Do not add Arabic numerals, URLs, "
                                "citations, code, or commentary."
                            ),
                        },
                        {"role": "user", "content": core},
                    ],
                    temperature=0.0,
                    max_tokens=max(512, min(4096, len(core) * 2 + 512)),
                    tier="strong",
                )
            except Exception as exc:  # noqa: BLE001 — final bounded prose-only attempt
                logger.warning("双语报告：单 prose-slot 翻译调用失败: %s", exc)
            candidate = str(raw or "").strip()
            if candidate.startswith("```"):
                candidate = re.sub(r"^```(?:markdown|md)?\s*", "", candidate, flags=re.I)
                candidate = re.sub(r"\s*```$", "", candidate).strip()
            if _accept(core, candidate, allow_echo=False):
                resolved[key] = candidate.replace("\n", " ")
        return resolved

    def _translate_from_source_skeleton(
        self,
        markdown: str,
        target_language_name: str,
    ) -> str:
        """Structure-preserving translator: the primary guarantee, not a hope.

        The source markdown is parsed into a scaffold template plus natural-language
        slots.  Heading hashes/levels, table pipe skeletons and column counts, list
        markers, blockquote arrows, and every immutable token (numbers, citations,
        URLs, inline code, comments, fenced blocks) are copied byte-for-byte; only
        the prose core of each unit is translated.  Reassembly therefore reproduces
        the exact source skeleton, so heading-level sequence, table row/column
        structure and the numeric/citation multiset are identical by construction.
        Any slot the model cannot faithfully translate falls back to its source
        bytes (later resolved by the contamination-repair pass), never to drift.
        """
        if not markdown.strip():
            return markdown
        protected, mapping = self._protect_translation_tokens(markdown)
        template, slots = self._build_structural_slots(protected)
        if not slots:
            # No translatable prose (pure tables of numbers / fences) — restore
            # tokens and return the structurally-identical source unchanged.
            restored, _issues = self._restore_translation_tokens(protected, mapping)
            return restored
        resolved = self._resolve_prose_slots(slots, target_language_name)

        def _fill(match: "re.Match") -> str:
            key = match.group(1)
            return resolved.get(key, slots.get(key, ""))

        reassembled = self._STRUCT_SLOT_RE.sub(_fill, template)
        restored, _issues = self._restore_translation_tokens(reassembled, mapping)
        return restored

    @staticmethod
    def _detect_translation_target(
        md: str
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """复用 detect_output_language / CJK 比率判定成稿语言，返回
        (source_code, target_code, target_language_name)。中文→英文、英文→中文；
        其它脚本（西里尔/阿拉伯…被 CJK 比率误判为 English）→ (None, None, None) 跳过。"""
        text = md or ""
        if not text.strip():
            return None, None, None
        try:
            from .requirement_spec import detect_output_language
            lang = detect_output_language(text)  # "Chinese" | "English"
        except Exception:  # noqa: BLE001 — 判定失败即保守跳过
            return None, None, None
        if lang == "Chinese":
            return "zh", "en", "professional analyst-grade English"
        # English 分支：再确认确为拉丁脚本，排除非中英文语种被 CJK 比率误判为 English。
        letters = sum(1 for ch in text if ch.isalpha())
        if letters:
            latin = sum(1 for ch in text if "a" <= ch.lower() <= "z")
            if latin / letters < 0.5:
                return None, None, None
        return "en", "zh", "简体中文（Simplified Chinese）"

    @staticmethod
    def _split_markdown_h2_sections(md: str) -> List[str]:
        """按 H2（行首 '## '，不含 '### '）边界把成稿切成若干块；首个 H2 之前的前言
        （H1 标题 + 摘要 blockquote）为块 0。跳过围栏代码块内的 '## '（避免把代码/示例里的
        井号当章节边界）。各块以 '\\n' 拼接后 == 原文（无增删换行），保证结构无损。"""
        from .forecast_extractor import markdown_fence_transition

        lines = (md or "").split("\n")
        chunks: List[List[str]] = []
        cur: List[str] = []
        fence_state = None
        for ln in lines:
            was_in_fence = fence_state is not None
            fence_state, is_fence_line = markdown_fence_transition(
                ln, fence_state
            )
            if is_fence_line:
                cur.append(ln)
                continue
            # H2 边界：'## ' 开头但非 '### '（后者 startswith('## ') 为 False，无需额外判断）
            if (not was_in_fence) and ln.startswith("## "):
                if cur:
                    chunks.append(cur)
                cur = [ln]
            else:
                cur.append(ln)
        if cur:
            chunks.append(cur)
        return ["\n".join(c) for c in chunks]

    @staticmethod
    def _translation_heading_signature(md: str) -> List[int]:
        """Return the heading-level sequence outside fenced blocks."""
        levels: List[int] = []
        in_fence = False
        for line in (md or "").splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            match = re.match(r"^(#{1,6})\s+\S", line)
            if match:
                levels.append(len(match.group(1)))
        return levels

    @staticmethod
    def _translation_table_signature(md: str) -> List[int]:
        """Return the ordered Markdown-table row widths outside fenced blocks."""
        widths: List[int] = []
        in_fence = False
        for line in (md or "").splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence or not stripped.startswith("|") or "|" not in stripped[1:]:
                continue
            # Translators are instructed to preserve table markup byte-for-byte.
            # Count only unescaped separators so prose containing ``\|`` is safe.
            widths.append(len(re.findall(r"(?<!\\)\|", stripped)) - 1)
        return widths

    @classmethod
    def _translation_fence_signature(cls, md: str) -> List[str]:
        """Return every complete fenced block in order, byte-for-byte."""
        return [match.group(0) for match in cls._TRANSLATION_FENCE_RE.finditer(md or "")]

    @staticmethod
    def _normalize_number_token(token: str) -> str:
        """Normalize a numeric token for cross-language parity comparison.

        Whitespace is removed and a single leading ``+``/``-`` sign is dropped.  The
        sign is stripped deliberately: numbers are placeholder-protected and restored
        byte-for-byte, so their digit content never changes, but translation legitimately
        alters the *surrounding* characters (e.g. English ``end-2030`` — a letter precedes
        the hyphen so no sign is captured — becomes Chinese ``…-2030`` where a CJK char
        precedes the hyphen and the regex would otherwise capture a spurious ``-2030``).
        Comparing sign-free digit content keeps the multiset invariant to that punctuation
        drift while the exact bytes remain guaranteed by the token restore step.
        """
        cleaned = re.sub(r"\s+", "", token or "")
        if cleaned[:1] in "+-":
            cleaned = cleaned[1:]
        return cleaned

    @classmethod
    def _translation_number_multiset(cls, md: str) -> Dict[str, int]:
        """Return normalized numeric-token multiplicities for exact parity checks."""
        from collections import Counter

        return dict(Counter(
            cls._normalize_number_token(match.group(0))
            for match in cls._NUMBER_INTEGRITY_RE.finditer(md or "")
        ))

    # COST-1(d): formatting-only numeric equivalences. Full-width digits map to
    # ASCII; thousands-separator commas are stripped. Both are pure rendering
    # choices — the token regex only ever captures ',' in the \d{1,3}(,\d{3})+
    # grouping form, so a comma inside a captured token is always a separator.
    _FULLWIDTH_DIGIT_TRANS = str.maketrans("０１２３４５６７８９", "0123456789")

    @classmethod
    def _fold_number_token(cls, token: str) -> str:
        """Normalize then fold formatting equivalences of one numeric token."""
        return (
            cls._normalize_number_token(token)
            .translate(cls._FULLWIDTH_DIGIT_TRANS)
            .replace(",", "")
        )

    @classmethod
    def _folded_number_multiset(cls, md: str) -> Dict[str, int]:
        """Numeric multiset that treats value-preserving reformatting as equal.

        Used by the language-purity segment repair (`_translate_impurity_segments`)
        so a legitimate translation rendering "1,000" as "1000" (or full-width
        "１０００" as "1000") is not rejected and force-escalated to strong-tier
        calls. The bilingual whole-report path deliberately keeps the strict
        `_translation_number_multiset` (byte-level keys like "1,808,511").
        """
        from collections import Counter

        folded: "Counter[str]" = Counter()
        for token, count in cls._translation_number_multiset(md).items():
            folded[
                token.translate(cls._FULLWIDTH_DIGIT_TRANS).replace(",", "")
            ] += count
        return dict(folded)

    @classmethod
    def _translation_marker_multiset(cls, md: str) -> Dict[str, int]:
        """Return canonical citation-token multiplicities outside fenced blocks."""
        from collections import Counter
        from .forecast_extractor import _norm_citation_tag

        counter: "Counter[str]" = Counter()
        in_fence = False
        marker_re = re.compile(r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]", re.I)
        for line in (md or "").splitlines():
            stripped = line.lstrip()
            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for match in marker_re.finditer(line):
                tag = _norm_citation_tag(match.group(1))
                if tag:
                    counter[tag] += 1
        return dict(counter)

    @classmethod
    def _translation_reference_parts(cls, md: str) -> Tuple[str, str, str]:
        """Split a report into body, References block and its recognized heading."""
        chunks = cls._split_markdown_h2_sections(md or "")
        refs = [
            chunk for chunk in chunks
            if chunk.split("\n", 1)[0].strip() in _REFS_HEADINGS
        ]
        body = "\n".join(chunk for chunk in chunks if chunk not in refs).rstrip() + "\n"
        reference_text = "\n".join(refs)
        heading = refs[0].split("\n", 1)[0].strip() if refs else ""
        return body, reference_text, heading

    @staticmethod
    def _localize_translation_references(chunk_md: str, target_lang: str) -> str:
        """Localize only the canonical References heading.

        Citation titles, dates, tags, and URLs are provenance, not authored
        narrative.  Sending the appendix through the model adds cost and lets a
        harmless heading synonym make the complete namespace invisible to the
        publication audit.  Preserve every entry byte-for-byte and deterministically
        switch between the two accepted headings.
        """
        lines = (chunk_md or "").split("\n")
        if not lines or lines[0].strip() not in _REFS_HEADINGS:
            return chunk_md
        lines[0] = _REFS_HEADINGS[1] if target_lang == "zh" else _REFS_HEADINGS[0]
        return "\n".join(lines)

    def _translation_chunk_quality(
        self,
        source: str,
        candidate: str,
        target_lang: str,
    ) -> Dict[str, Any]:
        """Return bounded per-chunk integrity signals used by one repair retry."""
        hard: List[str] = []
        if self._translation_heading_signature(source) != self._translation_heading_signature(
            candidate
        ):
            hard.append("heading levels")
        if self._translation_table_signature(source) != self._translation_table_signature(
            candidate
        ):
            hard.append("table shape")
        if self._translation_number_multiset(source) != self._translation_number_multiset(
            candidate
        ):
            hard.append("numeric tokens")
        if self._translation_marker_multiset(source) != self._translation_marker_multiset(
            candidate
        ):
            hard.append("citation tokens")
        if self._translation_fence_signature(source) != self._translation_fence_signature(
            candidate
        ):
            hard.append("fenced blocks")
        residual = self._collect_impurity_segments(
            candidate,
            target_is_cjk=(target_lang == "zh"),
            cap=60,
        )
        return {"hard": hard, "residual": residual}

    def _audit_translation_variant(
        self,
        report_id: str,
        source_md: str,
        variant_md: str,
        source_lang: str,
        target_lang: str,
        primary_citations: Optional[Dict[str, Any]] = None,
        *,
        enforce_citations: bool = True,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Audit a language variant and build its isolated citation artifact.

        The audit is deterministic and read-only.  A variant is publishable only
        when heading/table/number/citation parity is exact, target-language lint is
        clean, and every body marker resolves through the primary report's finalized
        citation namespace into a visible References entry.  The returned citation
        payload is never persisted by this function.
        """
        from . import report_lint as _rl
        from .forecast_extractor import _norm_citation_tag, validate_citation_markers

        primary_citations = primary_citations if isinstance(primary_citations, dict) else {}
        marker_rows = primary_citations.get("markers")
        marker_rows = marker_rows if isinstance(marker_rows, list) else []
        primary_by_tag = {
            _norm_citation_tag(str(row.get("tag") or "")): row
            for row in marker_rows if isinstance(row, dict) and row.get("tag")
        }

        source_body, source_refs, _source_heading = self._translation_reference_parts(source_md)
        variant_body, variant_refs, variant_heading = self._translation_reference_parts(variant_md)
        source_markers = self._translation_marker_multiset(source_md)
        variant_markers = self._translation_marker_multiset(variant_md)
        source_body_markers = self._translation_marker_multiset(source_body)
        variant_body_markers = self._translation_marker_multiset(variant_body)

        heading_source = self._translation_heading_signature(source_md)
        heading_variant = self._translation_heading_signature(variant_md)
        table_source = self._translation_table_signature(source_md)
        table_variant = self._translation_table_signature(variant_md)
        number_source = self._translation_number_multiset(source_md)
        number_variant = self._translation_number_multiset(variant_md)
        fences_source = self._translation_fence_signature(source_md)
        fences_variant = self._translation_fence_signature(variant_md)

        target_name = "Chinese" if target_lang == "zh" else "English"
        _candidate, lint_audit = _rl.lint_report(
            variant_body,
            target_name,
            mode="final",
            spine=(self._forecast_spine if isinstance(
                getattr(self, "_forecast_spine", None), dict) else None),
        )

        marker_audit = validate_citation_markers(variant_body, primary_by_tag)
        expected_tags = list(marker_audit.get("order") or [])
        invalid_urls = [
            tag for tag, row in primary_by_tag.items()
            if row.get("url_valid") is not True
            or not _citation_url_ok(str(row.get("url") or ""))
        ]
        missing_reference_tags = [
            tag for tag in expected_tags if f"[{tag}]" not in variant_refs
        ]
        missing_reference_urls = [
            tag for tag in expected_tags
            if str((primary_by_tag.get(tag) or {}).get("url") or "").strip()
            and str((primary_by_tag.get(tag) or {}).get("url") or "").strip()
            not in variant_refs
        ]

        issues: List[str] = []
        if heading_source != heading_variant:
            issues.append("translation heading-level sequence differs from primary")
        if table_source != table_variant:
            issues.append("translation table row/column structure differs from primary")
        if number_source != number_variant:
            issues.append("translation numeric-token multiset differs from primary")
        if fences_source != fences_variant:
            issues.append("translation fenced blocks differ from primary bytes")
        if source_markers != variant_markers:
            issues.append("translation citation-token multiset differs from primary")
        if source_body_markers != variant_body_markers:
            issues.append("translation body citation-token placement/count differs from primary")
        if source_refs and not variant_refs:
            issues.append("translation is missing a visible References appendix")
        if variant_refs and variant_heading not in _REFS_HEADINGS:
            issues.append("translation References heading is not canonical")
        # Citation-namespace binding is enforced for the published forecast report,
        # whose curated citations.json is authoritative.  Free-standing research
        # dossiers carry their own inline References appendix (preserved byte-for-byte
        # by the structure-preserving translator) rather than that schema, so their
        # audit validates marker-multiset parity and language/structure only.
        if enforce_citations:
            if source_body_markers and not primary_by_tag:
                issues.append("primary citations.json is missing for a cited translation")
            if marker_audit.get("dangling"):
                issues.append(
                    f"translation contains {len(marker_audit['dangling'])} dangling citation tags"
                )
            if missing_reference_tags:
                issues.append(
                    f"translation References misses {len(missing_reference_tags)} cited tags"
                )
            if missing_reference_urls:
                issues.append(
                    f"translation References misses {len(missing_reference_urls)} source URLs"
                )
            if invalid_urls:
                issues.append(
                    f"translation citation map contains {len(invalid_urls)} invalid source URLs"
                )
        if lint_audit.get("changed"):
            issues.append("translation would still be rewritten by final editorial lint")
        if lint_audit.get("leakage_flags"):
            issues.append("translation contains internal process/simulation leakage")
        contamination = int(
            (lint_audit.get("language_contamination") or {}).get("lines", 0) or 0
        )
        if contamination:
            issues.append(
                f"translation contains {contamination} target-language contamination lines"
            )

        variant_rows: List[Dict[str, Any]] = []
        for display, tag in enumerate(expected_tags, 1):
            source_row = primary_by_tag.get(tag)
            if not isinstance(source_row, dict):
                continue
            row = dict(source_row)
            row["display"] = display
            row["count"] = int(variant_body_markers.get(tag, 0))
            variant_rows.append(row)
        source_sha = hashlib.sha256((source_md or "").encode("utf-8")).hexdigest()
        variant_sha = hashlib.sha256((variant_md or "").encode("utf-8")).hexdigest()
        citations_payload: Dict[str, Any] = {
            "schema_version": 2,
            "report_id": report_id,
            "grammar": "[S<n>]",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "language": target_lang,
            "source_language": source_lang,
            "source_artifact": "citations.json",
            "source_markdown_sha256": source_sha,
            "markdown_sha256": variant_sha,
            "heading": variant_heading,
            "markers": variant_rows,
            "unresolved": [
                {"tag": tag, "count": int(variant_body_markers.get(tag, 0))}
                for tag in marker_audit.get("dangling") or []
            ],
        }
        audit: Dict[str, Any] = {
            "schema_version": 2,
            "policy_version": int(getattr(
                Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3
            )),
            "report_id": report_id,
            "language": target_lang,
            "source_language": source_lang,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "markdown_chars": len(variant_md or ""),
            "markdown_sha256": variant_sha,
            "source_markdown_sha256": source_sha,
            "section_parity": {
                "passed": heading_source == heading_variant,
                "source_levels": heading_source,
                "variant_levels": heading_variant,
            },
            "table_parity": {
                "passed": table_source == table_variant,
                "source_row_widths": table_source,
                "variant_row_widths": table_variant,
            },
            "number_parity": {
                "passed": number_source == number_variant,
                "source": number_source,
                "variant": number_variant,
            },
            "fenced_block_parity": {
                "passed": fences_source == fences_variant,
                "source_sha256": [
                    hashlib.sha256(item.encode("utf-8")).hexdigest()
                    for item in fences_source
                ],
                "variant_sha256": [
                    hashlib.sha256(item.encode("utf-8")).hexdigest()
                    for item in fences_variant
                ],
            },
            "citation_parity": {
                "passed": not any((
                    source_markers != variant_markers,
                    source_body_markers != variant_body_markers,
                    marker_audit.get("dangling"),
                    missing_reference_tags,
                    missing_reference_urls,
                    invalid_urls,
                    bool(source_refs and not variant_refs),
                )),
                "source_markers": source_markers,
                "variant_markers": variant_markers,
                "source_body_markers": source_body_markers,
                "variant_body_markers": variant_body_markers,
                "dangling": list(marker_audit.get("dangling") or []),
                "missing_reference_tags": missing_reference_tags,
                "missing_reference_urls": missing_reference_urls,
                "invalid_urls": invalid_urls,
            },
            "language_lint": lint_audit,
            "issues": issues,
            "hard_passed": not issues,
        }
        return audit, citations_payload

    def _translate_section(self, section_md: str, target_language_name: str,
                           extra_rules: str = "") -> str:
        """把单个章节（H2 块）译成目标语言，严格保留 markdown 结构、围栏、表格列数、引用标记、
        数字概率。调用失败 / 空输出 → 返回原文（degrade-safe，交由数字完整性核对标记）。

        WAVE10：``extra_rules`` 追加到系统提示词末尾——引用记号对账重试用它枚举本章的
        精确记号清单（缺省空串时提示词与历史逐字节一致）。"""
        if not section_md.strip():
            return section_md
        units = self._split_translation_units(section_md)
        return "\n\n".join(
            self._translate_markdown_unit(unit, target_language_name, extra_rules)
            for unit in units
        )

    def _translate_markdown_unit(self, markdown: str, target_language_name: str,
                                 extra_rules: str = "") -> str:
        """Translate one bounded Markdown unit and restore immutable source bytes."""
        protected_md, protected_mapping = self._protect_translation_tokens(markdown)
        sys_prompt = (
            "You are a professional translator for institutional analytic / forecasting reports. "
            f"Translate the following Markdown into {target_language_name}. "
            "Obey EVERY rule strictly:\n"
            "1. Preserve ALL Markdown structure verbatim: heading levels (#/##/###), lists, "
            "blockquotes, bold/italic, and tables — tables MUST keep the EXACT same number of "
            "columns and the |---| separator row.\n"
            "2. Copy every fenced code block and mermaid block (``` or ~~~ fences, and everything "
            "inside them) UNCHANGED — never translate content inside fences.\n"
            "3. Tokens shaped ⟦P…⟧, ⟦X…⟧, or ⟦F…⟧ are immutable source bytes. "
            "Copy every placeholder exactly once and never translate, alter, split, reorder, "
            "or remove one. Do not introduce any new Arabic numerals; the source numbers, URLs, "
            "citations, link targets, inline code, comments, and fences are already protected.\n"
            "4. Keep proper nouns and source names as-is; do not invent name translations. You may "
            "add a target-language rendering in parentheses only where it aids readability.\n"
            "5. Output ONLY the translated Markdown — no preamble, no commentary, and do NOT wrap "
            "the whole answer in a code fence."
        )
        if extra_rules:
            sys_prompt += "\n" + extra_rules
        # 输出预算：中文比英文更紧凑，英译中略膨胀；给宽裕上限（有界，防单章截断）。
        est = max(2048, min(16384, len(protected_md) // 2 + 1024))
        try:
            out = self.llm.chat(
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": protected_md}],
                temperature=0.1, max_tokens=est, tier="strong",
            )
        except Exception as _te:  # noqa: BLE001 — 单章翻译失败保留原文，不牵连整篇
            logger.warning(f"双语报告：章节翻译调用失败，保留原文: {_te}")
            return markdown
        out = (out or "").strip()
        if not out:
            return markdown
        # 模型偶把整段答案包进 ``` 围栏——仅当首行是纯 fence 标记时剥掉，避免破坏结构。
        first = out.split("\n", 1)[0].strip()
        if first in ("```", "```markdown", "```md", "~~~") and out.rstrip().endswith(("```", "~~~")):
            inner = out.split("\n", 1)[1] if "\n" in out else ""
            inner = inner.rsplit("```", 1)[0].rsplit("~~~", 1)[0]
            if inner.strip():
                out = inner.rstrip()
        restored, placeholder_issues = self._restore_translation_tokens(
            out, protected_mapping
        )
        # Structure is a hard invariant, not a hope: if the whole-unit candidate
        # dropped/duplicated an immutable token, or drifted on heading levels, table
        # row/column shape, or the numeric multiset, discard it and fall back to the
        # structure-preserving translator which cannot drift by construction.
        structural_drift = (
            self._translation_heading_signature(markdown)
            != self._translation_heading_signature(restored)
            or self._translation_table_signature(markdown)
            != self._translation_table_signature(restored)
            or self._translation_number_multiset(markdown)
            != self._translation_number_multiset(restored)
            or self._translation_marker_multiset(markdown)
            != self._translation_marker_multiset(restored)
        )
        if placeholder_issues or structural_drift:
            logger.warning(
                "双语报告：整块候选结构/占位符漂移，改走结构无损骨架翻译 "
                "placeholder_issues=%s structural_drift=%s",
                placeholder_issues[:8],
                structural_drift,
            )
            return self._translate_from_source_skeleton(
                markdown,
                target_language_name,
            ).strip()
        return restored

    def _repair_variant_contamination(
        self,
        translated_md: str,
        target_is_cjk: bool,
        target_language_name: str,
    ) -> str:
        """Re-translate residual source-language lines until clean or a bounded cap.

        Structure-preserving translation guarantees the skeleton but may keep a few
        source-language cores when the model refuses one fragment.  This pass detects
        those residual segments (fence-aware, inline-code/URL masked) and re-translates
        only them in place, protecting immutable inline tokens so links/code cannot be
        corrupted.  It is strictly bounded; anything still contaminated afterwards is
        rejected by the read-only publication audit (fail-closed), never published.
        """
        try:
            rounds = int(getattr(Config, "REPORT_TRANSLATION_CONTAMINATION_RETRIES", 3) or 3)
        except (TypeError, ValueError):
            rounds = 3
        rounds = max(1, min(5, rounds))

        def _scan(current: str) -> List[str]:
            found: List[str] = []
            seen: set = set()
            for chunk in self._split_markdown_h2_sections(current):
                for segment in self._collect_impurity_segments(
                    chunk, target_is_cjk, cap=60
                ):
                    if segment not in seen:
                        seen.add(segment)
                        found.append(segment)
            return found

        def _replace(current: str, replacements: List[Tuple[str, str]]) -> Tuple[str, int]:
            in_fence = False
            count = 0
            out_lines: List[str] = []
            for line in current.splitlines():
                if line.strip().startswith("```"):
                    in_fence = not in_fence
                    out_lines.append(line)
                    continue
                if in_fence:
                    out_lines.append(line)
                    continue
                protected: List[str] = []

                def _mask(match: "re.Match[str]", *, _p: List[str] = protected) -> str:
                    _p.append(match.group(0))
                    return f"\x00LP{len(_p) - 1}\x00"

                new_line = self._LANG_INLINE_PROTECTED_RE.sub(_mask, line)
                applied = 0
                for original, translated in replacements:
                    if original in new_line:
                        new_line = new_line.replace(original, translated)
                        applied += 1
                for idx, token in enumerate(protected):
                    new_line = new_line.replace(f"\x00LP{idx}\x00", token)
                # Numeric fail-closed guard: a contamination replacement must never
                # change the line's number multiset.  The segment translations are
                # already token-protected upstream, but overlapping substring
                # substitutions could in principle disturb a shared number; if the
                # restored line's numbers drifted, revert this line verbatim so the
                # audit's byte-exact numeric multiset stays identical by construction.
                if applied and self._translation_number_multiset(
                    new_line
                ) != self._translation_number_multiset(line):
                    out_lines.append(line)
                    continue
                count += applied
                out_lines.append(new_line)
            return "\n".join(out_lines), count

        current = translated_md
        for _round in range(rounds):
            segments = _scan(current)
            if not segments:
                break
            mapping = self._translate_impurity_segments(segments, target_language_name)
            if not mapping:
                break
            candidate, replaced = _replace(current, mapping)
            if not replaced or candidate == current:
                break
            current = candidate
        return current

    def _lint_variant_to_audit_fixed_point(
        self,
        translated_md: str,
        lint_lang: str,
        spine: Optional[Dict[str, Any]],
        *,
        max_iterations: int = 4,
    ) -> str:
        """Return a variant whose audit-body view is a final-lint fixed point.

        LINT-BEFORE-AUDIT — the read-only publication audit re-runs the deterministic
        final editorial lint on ``_translation_reference_parts(variant).body`` and
        rejects the variant when that lint reports ``changed`` (the
        "translation would still be rewritten by final editorial lint" issue).  Lint is
        idempotent on a fixed document, but the reassembly of ``linted_body + refs`` is
        re-decomposed by the audit, so a single pass is not guaranteed to be the exact
        byte-view the audit lints.  We therefore lint the body, reassemble with the
        References appendix, and re-derive the audit's exact body view, iterating until
        that view is a lint fixed point (``changed == False``).  Because each lint pass
        is idempotent this converges in one or two iterations; the bounded loop makes
        "would still be rewritten" structurally impossible rather than audit-lucky.
        """
        from . import report_lint as _rl

        current = translated_md
        for _iteration in range(max(1, max_iterations)):
            body, refs, _heading = self._translation_reference_parts(current)
            linted_body, _rep = _rl.lint_report(body, lint_lang, mode="final", spine=spine)
            if not linted_body.strip():
                # Lint emptied the body (degenerate) — keep the pre-lint bytes and let
                # the audit fail closed rather than publish an empty variant.
                return current
            rebuilt = linted_body.rstrip()
            if refs.strip():
                rebuilt += "\n\n" + refs.rstrip()
            rebuilt = rebuilt.rstrip() + "\n"
            # Re-derive the exact body view the audit will lint and check its fixed point.
            audit_body, _audit_refs, _audit_heading = self._translation_reference_parts(rebuilt)
            _relinted, rep2 = _rl.lint_report(audit_body, lint_lang, mode="final", spine=spine)
            current = rebuilt
            if not rep2.get("changed"):
                break
        return current

    def _generate_bilingual_report(
        self,
        report_id: str,
        report: "Report",
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """BILINGUAL：在报告最终化/可视化/纯度处理之后，自动生成成稿的另一语种版本。

        流水：① 复用 detect_output_language 判定成稿语言（英⇄中，其它脚本跳过）；② 按 H2 边界
        切块，用小 ThreadPoolExecutor（REPORT_TRANSLATION_CONCURRENCY）并发逐章翻译；③ 逐章引用
        记号对账重译；④ 对整篇做标题/表格/数字/引用/语言五重硬审计；⑤ 仅审计通过才原子落
        full_report.{lang}.md + citations.{lang}.json + final_audit.{lang}.json；⑥ 用最终字节
        刷新 report.translations。失败译文不发布，且删除任何同语种旧成稿/PDF，防止陈旧译文
        伪装成本次运行产物。主报告永不被修改。"""
        if not getattr(Config, "REPORT_BILINGUAL", True):
            return
        llm = getattr(self, "llm", None)
        if llm is None or not hasattr(llm, "chat"):
            return
        md = report.markdown_content or ""
        if not md.strip():
            return
        src_code, tgt_code, tgt_name = self._detect_translation_target(md)
        if not tgt_code:
            logger.info(f"双语报告：成稿语言非中/英（或无法判定），跳过翻译: {report_id}")
            return

        source_sha = hashlib.sha256(md.encode("utf-8")).hexdigest()

        def _progress(percent: int, message: str) -> None:
            bounded = max(1, min(99, int(percent)))
            ReportManager._set_translation_runtime_status(
                report_id,
                str(tgt_code),
                "generating",
                source_markdown_sha256=source_sha,
                progress=bounded,
                message=message,
            )
            if progress_callback is not None:
                try:
                    progress_callback(bounded, message)
                except Exception as exc:  # noqa: BLE001 — observability cannot fail content
                    logger.warning("双语报告进度回调失败（忽略）: %s", exc)

        _progress(1, "translation initialized")

        chunks = self._split_markdown_h2_sections(md)
        if not chunks:
            return
        try:
            conc = max(1, int(getattr(Config, "REPORT_TRANSLATION_CONCURRENCY", 4) or 4))
        except (TypeError, ValueError):
            conc = 4

        translated: List[Optional[str]] = [None] * len(chunks)

        def _work(pair: Tuple[int, str]) -> Tuple[int, str]:
            i, ch = pair
            first = ch.split("\n", 1)[0].strip()
            if first in _REFS_HEADINGS:
                return i, self._localize_translation_references(ch, str(tgt_code))
            return i, self._translate_section(ch, tgt_name)

        if conc > 1 and len(chunks) > 1:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            parent_context = contextvars.copy_context()
            with ThreadPoolExecutor(max_workers=min(conc, len(chunks))) as ex:
                futures = [
                    ex.submit(parent_context.copy().run, _work, pair)
                    for pair in enumerate(chunks)
                ]
                completed = 0
                for future in as_completed(futures):
                    i, tr = future.result()
                    translated[i] = tr
                    completed += 1
                    _progress(
                        5 + int(55 * completed / len(chunks)),
                        f"translated {completed}/{len(chunks)} report sections",
                    )
        else:
            for i, ch in enumerate(chunks):
                _, translated[i] = _work((i, ch))
                _progress(
                    5 + int(55 * (i + 1) / len(chunks)),
                    f"translated {i + 1}/{len(chunks)} report sections",
                )

        # 逐 H2 块做一次有界完整性修复。结构/数字/引用漂移，或长段源语言残留，都会触发
        # 同一轮重译；只有严格改进的候选才会替换首译。References 已在上方确定性处理，不花
        # LLM 调用。最终整篇只读审计仍是发布权威。
        citation_drift: List[Dict[str, Any]] = []
        for i, ch in enumerate(chunks):
            if ch.split("\n", 1)[0].strip() in _REFS_HEADINGS:
                continue
            cur = translated[i] if translated[i] is not None else ch
            quality = self._translation_chunk_quality(ch, cur, str(tgt_code))
            citation_retry = bool(
                "citation tokens" in quality["hard"]
                and getattr(Config, "REPORT_TRANSLATION_CITATION_PARITY", True)
            )
            non_citation_hard = [
                item for item in quality["hard"] if item != "citation tokens"
            ]
            if non_citation_hard or quality["residual"] or citation_retry:
                marker_inventory = self._translation_marker_multiset(ch)
                inventory = "，".join(
                    f"[{tag}] x{count}" for tag, count in sorted(
                        marker_inventory.items(), key=lambda item: (len(item[0]), item[0])
                    )
                ) or "(none)"
                residual = " | ".join(quality["residual"][:12]) or "(none)"
                language_rule = (
                    "Translate every natural-language phrase, including prose in table cells, "
                    "blockquotes, lists, scenario statements, and forecast statements. Leave "
                    "only proper names and product/publication names in the source language."
                )
                extra = (
                    "6. INTEGRITY RETRY — the prior candidate failed: "
                    f"{', '.join(quality['hard']) or 'residual source-language prose'}. "
                    f"{language_rule} "
                    f"{('CITATION TOKEN INVENTORY: ' + inventory + '. ') if citation_retry else ''}"
                    f"Residual examples: {residual}. Preserve every numeric and citation token "
                    "byte-identical; do not add, drop, merge, or renumber any token."
                )
                try:
                    retry = self._translate_section(ch, tgt_name, extra_rules=extra)
                except Exception as exc:  # noqa: BLE001 — one bounded retry only
                    logger.warning(f"双语报告：完整性重译失败，保留首译: {exc}")
                    retry = ""
                if retry:
                    retry_quality = self._translation_chunk_quality(
                        ch, retry, str(tgt_code)
                    )
                    current_rank = (len(quality["hard"]), len(quality["residual"]))
                    retry_rank = (
                        len(retry_quality["hard"]),
                        len(retry_quality["residual"]),
                    )
                    if retry_rank < current_rank:
                        translated[i] = retry
                        cur = retry
                        quality = retry_quality

            if "citation tokens" in quality["hard"]:
                src_ms = self._translation_marker_multiset(ch)
                dst_ms = self._translation_marker_multiset(cur)
                diff = {
                    tag: {"src": src_ms.get(tag, 0), "dst": dst_ms.get(tag, 0)}
                    for tag in set(src_ms) | set(dst_ms)
                    if src_ms.get(tag, 0) != dst_ms.get(tag, 0)
                }
                citation_drift.append({"chunk": i, "diff": diff})
            if quality["hard"] or quality["residual"]:
                logger.warning(
                    "双语报告：章节完整性重试后仍有问题 report=%s chunk=%s hard=%s residual=%s",
                    report_id,
                    i,
                    quality["hard"],
                    len(quality["residual"]),
                )
            _progress(
                65 + int(25 * (i + 1) / len(chunks)),
                f"audited {i + 1}/{len(chunks)} translated sections",
            )
        if citation_drift:
            logger.warning(
                f"双语报告引用对账告警: {report_id} {len(citation_drift)} 个章节的"
                f"引用记号多重集在重译后仍漂移: "
                f"{[d['chunk'] for d in citation_drift][:8]}")

        # 逐章 strip 后以空行拼接，保证 H2 章节间有标准 markdown 空行分隔（各段已含自身标题）。
        translated_md = "\n\n".join(
            (t if t is not None else chunks[i]) for i, t in enumerate(translated)
        ).strip() + "\n"
        folder = ReportManager._get_report_folder(report_id)
        out_path = ReportManager._get_report_translation_path(report_id, tgt_code)
        pdf_path = ReportManager._get_report_pdf_path(report_id, tgt_code)
        citations_path = ReportManager._get_report_citations_path(report_id, tgt_code)
        audit_path = ReportManager._get_report_final_audit_path(report_id, tgt_code)

        def _remove_stale_variant() -> None:
            ReportManager._safe_unlink(
                out_path,
                pdf_path,
                ReportManager._get_report_pdf_manifest_path(report_id, tgt_code),
                citations_path,
            )
            remaining = [
                entry for entry in (report.translations or [])
                if not (isinstance(entry, dict) and entry.get("lang") == tgt_code)
            ]
            report.translations = remaining or None

        # no-op 守卫：译文为空、或与原文在「空白归一」意义上完全相同（如整篇翻译退化为原文）。
        def _collapse(t: str) -> str:
            return re.sub(r"\s+", " ", t or "").strip()
        if not translated_md.strip() or _collapse(translated_md) == _collapse(md):
            _remove_stale_variant()
            ReportManager._set_translation_runtime_status(
                report_id,
                str(tgt_code),
                "failed",
                source_markdown_sha256=source_sha,
                issues=["translation was empty or materially identical to the primary"],
            )
            logger.info(f"双语报告：译文为空或与原文实质相同，跳过落盘: {report_id}")
            return

        # CONTAMINATION：有界重译任何残留源语言行，随后落地为审计前的最终字节。结构无损翻译已保证
        # 骨架，此处只补足纯度；仍污染者由下方只读终审 fail-closed 拒绝。
        target_is_cjk = str(tgt_code) == "zh"
        _progress(91, "repairing residual source-language lines")
        translated_md = self._repair_variant_contamination(
            translated_md, target_is_cjk, tgt_name
        ).strip() + "\n"

        # LINT-BEFORE-AUDIT：对译文正文运行与主报告完全相同的确定性终审 lint，并迭代到审计所见
        # 正文视图的不动点（changed=False）。lint 幂等，但「lint 正文 + 拼回 References」会被审计
        # 重新拆分，单趟不必然等于审计逐字节 lint 的视图；迭代到不动点使 "would still be rewritten"
        # 结构性不可能触发；若 lint 破坏了与源文的结构一致，审计仍会 fail-closed（不发布坏译文）。
        lint_lang = "Chinese" if target_is_cjk else "English"
        lint_spine = (
            self._forecast_spine
            if isinstance(getattr(self, "_forecast_spine", None), dict)
            else None
        )
        translated_md = self._lint_variant_to_audit_fixed_point(
            translated_md, lint_lang, lint_spine
        )

        primary_citations: Dict[str, Any] = {}
        try:
            with open(ReportManager._get_report_citations_path(report_id), encoding="utf-8") as handle:
                candidate = json.load(handle)
            if isinstance(candidate, dict):
                primary_citations = candidate
        except (OSError, ValueError, TypeError):
            primary_citations = {}

        _progress(95, "running isolated translation publication audit")
        audit, citations_payload = self._audit_translation_variant(
            report_id,
            md,
            translated_md,
            str(src_code),
            str(tgt_code),
            primary_citations,
        )
        if citation_drift:
            audit.setdefault("issues", []).append(
                f"translation citation drift remained in {len(citation_drift)} sections"
            )
            audit["citation_drift"] = citation_drift[:8]
            audit["hard_passed"] = False

        if not audit.get("hard_passed"):
            _remove_stale_variant()
            write_json_atomic(audit_path, audit)
            ReportManager._set_translation_runtime_status(
                report_id,
                str(tgt_code),
                "failed",
                source_markdown_sha256=source_sha,
                progress=100,
                issues=list(audit.get("issues") or [])[:12],
            )
            logger.error(
                "双语报告硬审计未通过，译文不发布: %s %s issues=%s",
                report_id, tgt_code, (audit.get("issues") or [])[:8],
            )
            return

        # Publish barrier: citation map + audit land before Markdown.  Readers can
        # never observe a new variant without its language-specific integrity data.
        try:
            write_json_atomic(citations_path, citations_payload)
            write_json_atomic(audit_path, audit)
            write_text_atomic(out_path, translated_md)
        except Exception as exc:  # noqa: BLE001 - partial variant must not publish
            _remove_stale_variant()
            audit.setdefault("issues", []).append(
                f"translation artifact persistence failed ({type(exc).__name__})"
            )
            audit["hard_passed"] = False
            write_json_atomic(audit_path, audit)
            ReportManager._set_translation_runtime_status(
                report_id,
                str(tgt_code),
                "failed",
                source_markdown_sha256=source_sha,
                progress=100,
                issues=list(audit.get("issues") or [])[:12],
            )
            logger.error("双语报告工件落盘失败，已清理译文: %s", exc)
            return

        # 记录 translations 条目（去重同语种旧条目后追加）。所有字段取最终字节，不复用翻译前元数据。
        try:
            model_name = getattr(self.llm, "model", None) or getattr(Config, "LLM_MODEL_NAME", "")
        except Exception:  # noqa: BLE001
            model_name = getattr(Config, "LLM_MODEL_NAME", "")
        entry = {
            "report_id": report_id,
            "lang": tgt_code,
            "source_lang": src_code,
            "source_markdown_sha256": source_sha,
            "path": f"full_report.{tgt_code}.md",
            "chars": len(translated_md),
            "bytes": len(translated_md.encode("utf-8")),
            "markdown_sha256": audit["markdown_sha256"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": model_name,
            "translation_quality": "ok",
            "available": True,
            "citations_path": f"citations.{tgt_code}.json",
            "final_audit_path": f"final_audit.{tgt_code}.json",
            "missing_numbers": [],
        }
        existing = [
            e for e in (report.translations or [])
            if not (isinstance(e, dict) and e.get("lang") == tgt_code)
        ]
        existing.append(entry)
        report.translations = existing
        ReportManager._set_translation_runtime_status(
            report_id,
            str(tgt_code),
            "available",
            source_markdown_sha256=source_sha,
            markdown_sha256=audit["markdown_sha256"],
            progress=100,
            message="translation passed isolated publication audit",
        )
        logger.info(
            f"双语报告已生成: {report_id} {src_code}→{tgt_code}，{len(chunks)} 章，"
            f"{len(translated_md)} 字，variant_audit=passed")

    def translate_research_markdown(
        self,
        md: str,
        *,
        label: str = "research_report",
        primary_citations: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Structure-preserving translation of an arbitrary research-report markdown.

        Reuses the exact same fail-closed primitives as the forecast bilingual path —
        structural skeleton translation (guaranteed heading/table/number/citation
        parity), bounded contamination repair, and lint-before-audit — then runs the
        same isolated variant audit.  Performs no filesystem IO; the caller persists
        the returned bytes only when ``audit['hard_passed']`` is True.  Returns a dict
        with ``available``/``src``/``tgt``/``translated_md``/``audit``/``citations``.
        """
        from . import report_lint as _rl

        md = md or ""
        src_code, tgt_code, tgt_name = self._detect_translation_target(md)
        if not tgt_code:
            return {"available": False, "reason": "source language is not English/Chinese"}
        # The published forecast report is already a final-lint fixed point at publish
        # time, but a free-standing research dossier is not.  Normalize the source to
        # that same fixed point first so structural parity is measured against a stable
        # baseline (empty sections / internal telemetry strip identically on both sides
        # instead of only on the freshly linted translation, which would spuriously
        # differ in heading count).  The primary research_report.md is never mutated.
        source_lint_lang = "Chinese" if str(src_code) == "zh" else "English"
        baseline_md, _baseline_rep = _rl.lint_report(
            md, source_lint_lang, mode="final", spine=None
        )
        if baseline_md.strip():
            md = baseline_md
        chunks = self._split_markdown_h2_sections(md)
        if not chunks:
            return {"available": False, "reason": "empty document"}

        translated: List[str] = []
        for chunk in chunks:
            first = chunk.split("\n", 1)[0].strip()
            if first in _REFS_HEADINGS:
                translated.append(
                    self._localize_translation_references(chunk, str(tgt_code))
                )
            else:
                translated.append(self._translate_section(chunk, tgt_name))

        # One bounded, structure-preserving integrity retry per drifting/residual chunk.
        for i, chunk in enumerate(chunks):
            if chunk.split("\n", 1)[0].strip() in _REFS_HEADINGS:
                continue
            quality = self._translation_chunk_quality(chunk, translated[i], str(tgt_code))
            if quality["hard"] or quality["residual"]:
                try:
                    retry = self._translate_section(chunk, tgt_name)
                except Exception as exc:  # noqa: BLE001 — one bounded retry only
                    logger.warning("研究报告翻译：整章重译失败，保留首译: %s", exc)
                    retry = ""
                if retry:
                    retry_quality = self._translation_chunk_quality(
                        chunk, retry, str(tgt_code)
                    )
                    if (len(retry_quality["hard"]), len(retry_quality["residual"])) < (
                        len(quality["hard"]),
                        len(quality["residual"]),
                    ):
                        translated[i] = retry

        translated_md = "\n\n".join(translated).strip() + "\n"

        def _collapse(text: str) -> str:
            return re.sub(r"\s+", " ", text or "").strip()
        if not translated_md.strip() or _collapse(translated_md) == _collapse(md):
            return {
                "available": False,
                "reason": "translation was empty or materially identical to source",
                "src": src_code,
                "tgt": tgt_code,
            }

        target_is_cjk = str(tgt_code) == "zh"
        translated_md = self._repair_variant_contamination(
            translated_md, target_is_cjk, tgt_name
        ).strip() + "\n"

        # LINT-BEFORE-AUDIT (research path): iterate to the audit's body-view fixed point
        # so "would still be rewritten by final editorial lint" is structurally impossible.
        lint_lang = "Chinese" if target_is_cjk else "English"
        translated_md = self._lint_variant_to_audit_fixed_point(
            translated_md, lint_lang, None
        )

        audit, citations_payload = self._audit_translation_variant(
            label,
            md,
            translated_md,
            str(src_code),
            str(tgt_code),
            primary_citations if isinstance(primary_citations, dict) else {},
            enforce_citations=bool(primary_citations),
        )
        return {
            "available": bool(audit.get("hard_passed")),
            "src": src_code,
            "tgt": tgt_code,
            "translated_md": translated_md,
            "audit": audit,
            "citations": citations_payload,
        }

    def _finalize_citations(self, report_id: str, report: "Report") -> None:
        """WAVE10 引用最终化：把正文 [S12] 记号解析为文末「References/参考来源」附录 +
        citations.json 工件——此前 321 个内联记号全是无处可去的死端。

        语言纯度/编辑 lint 之后、双语翻译**之前**调用（附录作为一个 H2 块随章节一并翻译）。
        确定性、无 LLM：
          ① 围栏感知采集正文记号（validate_citation_markers，首现顺序）；
          ② 对照记号→来源索引（_citation_index，悬空修复可能已扩充；无索引时回退全量
             位置映射），附录**只列被引用**的来源，按首现顺序给展示序号；
          ③ 条目 = 展示序号 + 原记号 + 标题 — 域名，日期，可点击 URL；不可解析或疑似
             截断的来源在索引边界即被拒绝，其记号会被唯一重映射或诚实删除；
          ④ 记号→条目映射写 <report_dir>/citations.json（前端悬浮 / PDF 脚注消费）。
        正文内联记号**不可变**（保持 [Sxx]——改写会让审计正则、修复 passes 与译文失配）。
        幂等：重跑先按 H2 块剥离旧附录再重建。任何失败由调用方捕获（degrade-safe）。"""
        md = report.markdown_content or ""
        if not md.strip():
            return
        from .forecast_extractor import validate_citation_markers, _norm_citation_tag
        imap = self._citation_index_or_fallback()
        # 幂等：剥离既有参考来源附录（围栏感知的 H2 块级删除）。
        chunks = self._split_markdown_h2_sections(md)
        body_chunks = [c for c in chunks
                       if c.split("\n", 1)[0].strip() not in _REFS_HEADINGS]
        body = "\n".join(body_chunks).rstrip() + "\n"
        v = validate_citation_markers(body, imap)
        if v["dangling"]:
            current_index = getattr(self, "_citation_index", None)
            if not isinstance(current_index, dict) or not current_index:
                # The offline/backfill path starts with an empty explicit map
                # and obtains `imap` from the admissible positional fallback.
                # Preserve that complete namespace before repair registers any
                # remap; otherwise the first registration would make a tiny
                # explicit map authoritative and orphan every other valid tag.
                self._citation_index = dict(imap)
            body, repair_info = self._repair_dangling_citations(
                body, list(v["dangling"])
            )
            imap = self._citation_index_or_fallback()
            v = validate_citation_markers(body, imap)
            logger.info(
                "citation finalization repair: remapped=%s stripped=%s unresolved=%s",
                repair_info.get("remapped", 0),
                repair_info.get("stripped", 0),
                len(v["dangling"]),
            )
        semantic_totals = {"checked": 0, "kept": 0, "unverifiable": 0,
                           "remapped": 0, "stripped": 0}
        for _semantic_pass in range(3):
            body, semantic_info = self._repair_semantic_citations(body)
            for key in semantic_totals:
                semantic_totals[key] += int(semantic_info.get(key, 0) or 0)
            imap = self._citation_index_or_fallback()
            if self._audit_semantic_citations(body, imap)["unsupported"] == 0:
                break
        v = validate_citation_markers(body, imap)
        if semantic_totals["remapped"] or semantic_totals["stripped"]:
            logger.info(
                "semantic citation repair: checked=%s remapped=%s stripped=%s "
                "unverifiable=%s",
                semantic_totals["checked"], semantic_totals["remapped"],
                semantic_totals["stripped"], semantic_totals["unverifiable"],
            )
        norm_map = {_norm_citation_tag(k): s for k, s in imap.items()
                    if _citation_source_admissible(s)}
        cited = [t for t in v["order"] if t in norm_map]
        if v["dangling"]:
            logger.warning(
                f"引用最终化: {report_id} 有 {len(v['dangling'])} 个无法解析的悬空记号"
                f"（保留原样、不入附录）: {v['dangling'][:8]}")

        lang = str(getattr(self, "output_language", "") or "").strip().lower()
        zh = not lang.startswith("en")
        heading = _REFS_HEADINGS[1] if zh else _REFS_HEADINGS[0]
        sep = "，" if zh else ", "
        marker_entries: List[Dict[str, Any]] = []
        ref_lines: List[str] = [heading, ""]
        for disp, tag in enumerate(cited, 1):
            src = norm_map[tag]
            url = str(src.get("url") or "").strip()
            domain = _citation_domain(url)
            title = _citation_display_title(src, tag)
            date = str(src.get("date") or "").strip()
            url_ok = _citation_url_ok(url)
            seg = f"{disp}. [{tag}] {title}"
            meta = [x for x in (domain, date) if x]
            if meta:
                seg += " — " + sep.join(meta)
            if url:
                seg += f" — [{url}]({url})"
            ref_lines.append(seg)
            marker_entries.append({
                "tag": tag,
                "display": disp,
                "count": int(v["counts"].get(tag, 0)),
                "title": title,
                "url": url,
                "url_valid": url_ok,
                "domain": domain,
                "date": date,
                "tier": str(src.get("tier") or "").strip(),
            })

        payload = {
            "grammar": "[S<n>]",
            "generated_at": datetime.now().isoformat(),
            "heading": heading,
            "markers": marker_entries,
            "unresolved": [{"tag": t, "count": int(v["counts"].get(t, 0))}
                           for t in v["dangling"]],
        }
        folder = ReportManager._get_report_folder(report_id)
        try:
            write_json_atomic(os.path.join(folder, "citations.json"), payload)
        except Exception as _je:  # noqa: BLE001 — 工件落盘失败不阻断附录追加
            logger.warning(f"落 citations.json 失败（忽略）: {_je}")

        new_md = (body.rstrip() + "\n\n" + "\n".join(ref_lines) + "\n") if cited else body
        if new_md == md:
            return                                    # 无被引用来源且无旧附录 → 不动成稿
        report.markdown_content = new_md
        try:
            write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
        except Exception as _we:  # noqa: BLE001
            logger.warning(f"回写含参考来源的 full_report.md 失败（忽略）: {_we}")
        logger.info(
            f"引用最终化完成: {report_id} 被引用来源 {len(cited)}，"
            f"内联记号 {v['total_markers']}，悬空 {len(v['dangling'])}")

    def _finalize_citations_for_publish(self, report_id: str, report: "Report") -> None:
        """Finalize citations; fail hard only when body markers would otherwise be dead."""
        body = "\n".join(
            chunk for chunk in self._split_markdown_h2_sections(
                report.markdown_content or ""
            )
            if chunk.split("\n", 1)[0].strip() not in _REFS_HEADINGS
        )
        body_has_markers = bool(self._ANY_S_TAG_RE.search(body))
        try:
            self._finalize_citations(report_id, report)
        except Exception as exc:  # noqa: BLE001 — classification depends on body contract
            if body_has_markers:
                raise RuntimeError(
                    "正文含引用记号但引用最终化失败，拒绝发布：" f"{exc}"
                ) from exc
            logger.warning(f"引用最终化失败（正文无引用记号，降级继续）: {exc}")

    def _stabilize_publish_markdown(
        self,
        report_id: str,
        report: "Report",
        *,
        max_passes: int = 4,
    ) -> Dict[str, Any]:
        """Converge citation repair, quote grounding, and editorial lint.

        Citation repair can honestly remove a source marker that previously made
        a blockquote look grounded.  Removing that marker can, in turn, leave an
        unsupported quote and punctuation spacing that the earlier lint pass could
        not have seen.  Publication therefore needs a bounded fixed-point pass,
        not a single linear sequence.

        Every pass finalizes citations, removes newly exposed ungrounded quotes,
        applies deterministic lint, and finalizes citations again.  The method
        succeeds only when a dry quote repair and dry lint are both byte-stable and
        no semantically unsupported citation remains.  It persists the exact stable
        bytes so the following read-only audit can require disk/memory identity.
        """
        from . import report_lint as _rl

        try:
            limit = max(1, min(8, int(max_passes)))
        except (TypeError, ValueError):
            limit = 4
        lang = getattr(self, "output_language", None) or "English"
        spine = (
            self._forecast_spine
            if isinstance(getattr(self, "_forecast_spine", None), dict)
            else None
        )
        folder = ReportManager._get_report_folder(report_id)
        totals: Dict[str, Any] = {
            "passes": 0,
            "quotes_removed": 0,
            "lint_rewrites": 0,
            "quantitative_rewrites": 0,
            "quantitative_grounding": {},
            "semantic_unsupported": None,
            "overuse_stripped": 0,
            "stable": False,
            "lint": {},
        }

        for pass_no in range(1, limit + 1):
            totals["passes"] = pass_no
            self._finalize_citations_for_publish(report_id, report)

            # SESSIONB-2：来源集中度裁剪必须发生在收敛判定所依据的同一批字节上——
            # 终审把「引用来源过度集中」判为硬缺陷，而此前修复链没有任何一环削减集中度，
            # 稳定成稿仍可能被确定性否决（整份报告作废）。单调剥离 ⇒ 定点循环必然收敛。
            overuse_capped, overuse_stripped = self._repair_overused_citations(
                report.markdown_content or ""
            )
            if overuse_stripped:
                totals["overuse_stripped"] += int(overuse_stripped)
                report.markdown_content = overuse_capped

            quantitatively_grounded, quantitative_info = (
                self._repair_final_quantitative_grounding(
                    report.markdown_content or ""
                )
            )
            totals["quantitative_grounding"] = quantitative_info
            if quantitatively_grounded != (report.markdown_content or ""):
                totals["quantitative_rewrites"] += 1
                report.markdown_content = quantitatively_grounded

            repaired, removed = self._repair_quote_grounding(
                report.markdown_content or ""
            )
            totals["quotes_removed"] += int(removed or 0)
            cleaned, lint_info = _rl.lint_report(
                repaired,
                lang,
                mode="final",
                spine=spine,
            )
            if not cleaned.strip():
                raise RuntimeError(
                    "发布稳定化删除了全部报告正文，拒绝发布空报告"
                )
            if cleaned != (report.markdown_content or ""):
                totals["lint_rewrites"] += 1
            report.markdown_content = cleaned

            # Lint can change the claim line that a marker annotates, so rebuild
            # the citation appendix and semantic mapping from the resulting bytes.
            self._finalize_citations_for_publish(report_id, report)
            current = report.markdown_content or ""
            write_text_atomic(os.path.join(folder, "full_report.md"), current)

            body = "\n".join(
                chunk for chunk in self._split_markdown_h2_sections(current)
                if chunk.split("\n", 1)[0].strip() not in _REFS_HEADINGS
            )
            semantic = self._audit_semantic_citations(
                body, self._citation_index_or_fallback()
            )
            quantitative_probe, quantitative_probe_info = (
                self._repair_final_quantitative_grounding(current)
            )
            totals["quantitative_grounding"] = quantitative_probe_info
            quote_probe, _ = self._repair_quote_grounding(current)
            lint_probe, final_lint = _rl.lint_report(
                current,
                lang,
                mode="final",
                spine=spine,
            )
            unsupported = int(semantic.get("unsupported", 0) or 0)
            totals["semantic_unsupported"] = unsupported
            totals["lint"] = final_lint
            totals["_quote_stable"] = (quote_probe == current)
            totals["_quant_stable"] = (quantitative_probe == current)
            totals["_semantic"] = semantic
            if (
                quote_probe == current
                and quantitative_probe == current
                and quantitative_probe_info.get("passed") is True
                and lint_probe == current
                and not final_lint.get("changed")
                and unsupported == 0
                # SESSIONB-2：终审对 overused_sources 一票否决，收敛判定必须与其对齐，
                # 否则「稳定」成稿仍会在只读终审处被确定性丢弃。
                and not semantic.get("overused_sources")
            ):
                totals["stable"] = True
                logger.info(
                    "发布 Markdown 已收敛: %s passes=%s quote_removed=%s "
                    "lint_rewrites=%s quantitative_rewrites=%s",
                    report_id,
                    pass_no,
                    totals["quotes_removed"],
                    totals["lint_rewrites"],
                    totals["quantitative_rewrites"],
                )
                return totals

        # GLM-run 2026-09-18: the historical failure mode of this gate is NOT
        # content — it is a lint⇄regenerator ping-pong (e.g. a lint rule editing
        # a URL inside the References appendix that the citation finalizer then
        # rebuilds from its canonical index). If every semantic gate is green
        # (no unsupported citations, quotes and quantitative bytes stable) and
        # the ONLY moving part is lint, apply lint once more and accept its
        # output when lint is itself idempotent (a true fixed point). This can
        # never mask a content defect: the semantic/quote/quantitative probes
        # all still have to be stable, and the result is recorded honestly.
        _final_lint = totals.get("lint") or {}
        if (
            not totals["semantic_unsupported"]
            and _final_lint.get("changed")
        ):
            try:
                _current = report.markdown_content or ""
                _once, _ = _rl.lint_report(_current, lang, mode="final", spine=spine)
                _twice, _info2 = _rl.lint_report(_once, lang, mode="final", spine=spine)
                if _once == _twice and _once.strip() and not _info2.get("changed"):
                    report.markdown_content = _once
                    write_text_atomic(
                        os.path.join(folder, "full_report.md"), _once)
                    totals["stable"] = True
                    totals["lint_forced_fixed_point"] = True
                    logger.info(
                        "发布 Markdown 按 lint 不动点收敛（语义门全绿，仅 lint "
                        "在附录再生成上振荡）: %s", report_id)
                    return totals
            except Exception as _fp_exc:  # noqa: BLE001 — 保守回退到原失败路径
                logger.warning("lint 不动点收敛尝试失败，按未收敛处理: %s", _fp_exc)
        _q = totals.get("quantitative_grounding") or {}
        raise RuntimeError(
            "发布 Markdown 在限定轮次内未收敛："
            f"passes={limit}, semantic_unsupported="
            f"{totals['semantic_unsupported']}, lint_changed="
            f"{bool((totals.get('lint') or {}).get('changed'))}, "
            f"quote_stable={totals.get('_quote_stable')}, "
            f"quant_stable={totals.get('_quant_stable')}, "
            f"quant_passed={_q.get('passed')}, "
            f"quant_coverage={(_q.get('after') or {}).get('resolved_coverage')}, "
            f"overused_sources={bool((totals.get('_semantic') or {}).get('overused_sources'))}"
        )

    @staticmethod
    def _audit_final_citation_artifacts(
        folder: str,
        reference_text: str,
        body_marker_audit: Dict[str, Any],
        index_map: Dict[str, Any],
        *,
        enabled: bool,
    ) -> Dict[str, Any]:
        """Verify visible References and citations.json against body markers/index."""
        from .forecast_extractor import _norm_citation_tag

        norm_index = {
            _norm_citation_tag(tag): source
            for tag, source in (index_map or {}).items()
            if _citation_source_admissible(source)
        }
        body_order = list(body_marker_audit.get("order") or [])
        expected = [tag for tag in body_order if tag in norm_index]
        required = bool(enabled and expected)
        payload: Optional[Dict[str, Any]] = None
        citations_path = os.path.join(folder, "citations.json")
        payload_error: Optional[str] = None
        try:
            with open(citations_path, encoding="utf-8") as handle:
                candidate = json.load(handle)
            if isinstance(candidate, dict):
                payload = candidate
            else:
                payload_error = "citations.json is not an object"
        except FileNotFoundError:
            payload_error = "citations.json missing"
        except (OSError, ValueError, TypeError) as exc:
            payload_error = f"citations.json invalid ({type(exc).__name__})"

        marker_rows = (
            payload.get("markers") if isinstance(payload, dict) else None
        )
        marker_rows = marker_rows if isinstance(marker_rows, list) else []
        artifact_by_tag: Dict[str, Dict[str, Any]] = {}
        for row in marker_rows:
            if not isinstance(row, dict):
                continue
            tag = _norm_citation_tag(str(row.get("tag") or ""))
            if tag:
                artifact_by_tag[tag] = row
        artifact_tags = list(artifact_by_tag)
        missing_tags = [tag for tag in expected if tag not in artifact_by_tag]
        extra_tags = [tag for tag in artifact_tags if tag not in expected]
        mismatched_urls: List[str] = []
        invalid_artifact_urls: List[str] = []
        missing_reference_tags: List[str] = []
        missing_reference_urls: List[str] = []
        for tag in expected:
            source_url = str((norm_index.get(tag) or {}).get("url") or "").strip()
            row_url = str((artifact_by_tag.get(tag) or {}).get("url") or "").strip()
            if row_url != source_url:
                mismatched_urls.append(tag)
            if f"[{tag}]" not in reference_text:
                missing_reference_tags.append(tag)
            if source_url and source_url not in reference_text:
                missing_reference_urls.append(tag)
        for tag, row in artifact_by_tag.items():
            row_url = str(row.get("url") or "").strip()
            if row.get("url_valid") is not True or not _citation_url_ok(row_url):
                invalid_artifact_urls.append(tag)

        issues: List[str] = []
        if required and not reference_text.strip():
            issues.append("正文含引用记号但最终 Markdown 缺少可见 References/参考来源附录")
        if required and payload_error:
            issues.append(payload_error)
        if required and missing_tags:
            issues.append(f"citations.json 缺少 {len(missing_tags)} 个正文引用记号")
        if enabled and extra_tags:
            issues.append(f"citations.json 含 {len(extra_tags)} 个非正文引用记号")
        if required and mismatched_urls:
            issues.append(f"citations.json 有 {len(mismatched_urls)} 个来源 URL 与索引不一致")
        if required and missing_reference_tags:
            issues.append(f"References 缺少 {len(missing_reference_tags)} 个正文引用记号")
        if required and missing_reference_urls:
            issues.append(f"References 缺少 {len(missing_reference_urls)} 个来源 URL")
        if enabled and invalid_artifact_urls:
            issues.append(
                f"citations.json 含 {len(invalid_artifact_urls)} 个无效或截断来源 URL"
            )
        return {
            "enabled": enabled,
            "required": required,
            "references_present": bool(reference_text.strip()),
            "citations_json_present": os.path.exists(citations_path),
            "citations_json_valid": payload is not None,
            "expected_tags": expected,
            "artifact_tags": artifact_tags,
            "missing_tags": missing_tags,
            "extra_tags": extra_tags,
            "mismatched_urls": mismatched_urls,
            "invalid_artifact_urls": invalid_artifact_urls,
            "missing_reference_tags": missing_reference_tags,
            "missing_reference_urls": missing_reference_urls,
            "issues": issues,
            "passed": not issues,
        }

    @staticmethod
    def _final_audit_integrity_issues(audit: Dict[str, Any]) -> List[str]:
        """Return non-epistemic defects in the exact publishable Markdown.

        These are artifact-integrity failures, not uncertainty about the world:
        confidence demotion cannot repair them and publication must stop.
        """
        issues: List[str] = []
        failed_sections = list(audit.get("failed_sections") or [])
        if failed_sections:
            issues.append(
                f"报告仍有 {len(failed_sections)} 个生成失败章节，拒绝发布部分成稿"
            )
        structured = audit.get("structured_forecast") or {}
        if structured.get("required") and not structured.get("valid"):
            issues.append(
                "结构化预测已启用，但 forecast.json 缺失、无效或缺少情景/二元预测"
            )
        if not audit.get("disk_matches_memory", False):
            issues.append("最终 Markdown 的内存内容与磁盘工件不一致")
        marker_audit = audit.get("citation_markers") or {}
        dangling = list(marker_audit.get("dangling") or [])
        if dangling:
            issues.append(f"最终 Markdown 含 {len(dangling)} 个悬空引用记号")
        lint = audit.get("lint") or {}
        if lint.get("leakage_flags"):
            issues.append(
                f"最终 Markdown 含 {lint['leakage_flags']} 处内部流程/模拟机制泄漏"
            )
        language_lines = int(
            (lint.get("language_contamination") or {}).get("lines", 0) or 0
        )
        if language_lines:
            issues.append(f"最终 Markdown 含 {language_lines} 行目标语言污染")
        truncations = list(lint.get("table_cell_truncations") or [])
        if truncations:
            issues.append(f"最终 Markdown 含 {len(truncations)} 个疑似截断表格单元格")
        scenario_mismatches = list(lint.get("scenario_prob_mismatches") or [])
        if scenario_mismatches:
            issues.append(
                f"最终 Markdown 含 {len(scenario_mismatches)} 个情景概率/骨架不一致"
            )
        if lint.get("changed"):
            issues.append("最终 Markdown 在发布后仍会被确定性编辑 lint 改写")
        for issue in (audit.get("citation_artifacts") or {}).get("issues") or []:
            if issue not in issues:
                issues.append(str(issue))
        unsupported_citations = int(
            (audit.get("semantic_citations") or {}).get("unsupported", 0) or 0
        )
        if unsupported_citations:
            issues.append(
                f"最终 Markdown 含 {unsupported_citations} 个来源与论断不匹配的引用记号"
            )
        overused_sources = list(
            (audit.get("semantic_citations") or {}).get("overused_sources") or []
        )
        if overused_sources:
            labels = ", ".join(
                f"{row.get('tag')}×{row.get('count')}" for row in overused_sources[:4]
            )
            issues.append(f"最终 Markdown 引用来源过度集中：{labels}")
        semantic_audit = audit.get("semantic_citations") or {}
        unverifiable = int(semantic_audit.get("unverifiable", 0) or 0)
        unverifiable_ratio = float(
            semantic_audit.get("unverifiable_ratio", 0.0) or 0.0
        )
        # GLM-run 2026-09-18: "unverifiable" is the matcher's explicit
        # "cannot deterministically audit this pair" verdict (cross-language
        # prose, or sources persisted without evidence text — both true for a
        # Chinese report citing English fetches through the extract-only
        # path). If the matcher issued ZERO affirmative (kept) and ZERO
        # negative (unsupported) verdicts across the whole report, the ratio
        # measures matcher coverage, not citation quality — it must not fail
        # publication. Any real support/unsupported signal re-arms the check.
        _kept = int(semantic_audit.get("kept", 0) or 0)
        _unsupported = int(semantic_audit.get("unsupported", 0) or 0)
        if (unverifiable >= 10 and unverifiable_ratio > 0.25
                and (_kept > 0 or _unsupported > 0)):
            issues.append(
                "最终 Markdown 有过多无法按证据片段验证的引用："
                f"{unverifiable} 个（{unverifiable_ratio:.0%}）"
            )
        elif unverifiable >= 10:
            logger.warning(
                "最终审计: %s 个引用不可按证据片段验证，但语义匹配器全程未出具任何 "
                "支持/不支持判定（跨语言或来源无证据文本）——按匹配器覆盖度处理，"
                "不作为引用质量失败",
                unverifiable,
            )
        cited_unverbatim = int(
            (audit.get("quote_provenance") or {}).get("cited_unverbatim", 0) or 0
        )
        if cited_unverbatim:
            issues.append(
                f"最终 Markdown 含 {cited_unverbatim} 条有来源但无法逐字接地的直接引语"
            )
        proposition_mismatches = int(
            (audit.get("proposition_consistency") or {}).get("mismatch_count", 0) or 0
        )
        if proposition_mismatches:
            issues.append(
                f"结构化二元预测与互斥情景分区有 {proposition_mismatches} 个概率矛盾"
            )
        market_anchor_issues = int(
            (audit.get("market_anchor_integrity") or {}).get("issue_count", 0) or 0
        )
        if market_anchor_issues:
            issues.append(
                f"预测市场锚点有 {market_anchor_issues} 个来源不完整或结算命题不等价"
            )
        scenario_contract = audit.get("scenario_contract") or {}
        scenario_contract_issues = int(
            scenario_contract.get("issue_count", 0) or 0
        )
        if structured.get("required") and scenario_contract.get("valid") is not True:
            issues.append(
                "结构化情景契约缺失或未通过"
            )
        elif scenario_contract_issues:
            issues.append(
                f"结构化情景契约有 {scenario_contract_issues} 个概率、边界或结算定义问题"
            )
        return issues

    @staticmethod
    def _require_final_publish_audit(audit: Dict[str, Any]) -> None:
        """Raise when the final audit did not run cleanly enough to publish."""
        if not isinstance(audit, dict) or not audit:
            raise RuntimeError("最终只读审计未产生结果，拒绝标记报告为 completed")
        hard = list(audit.get("hard_issues") or [])
        gate = audit.get("publish_gate") or {}
        hard.extend(
            issue for issue in (gate.get("hard_issues") or []) if issue not in hard
        )
        if hard:
            raise RuntimeError("最终发布完整性门未通过：" + "；".join(hard))
        if gate.get("enabled") and gate.get("passed") is False:
            quality_issues = [str(issue) for issue in (gate.get("issues") or [])]
            raise RuntimeError(
                "最终发布质量门未通过："
                + ("；".join(quality_issues) or "未提供质量门失败原因")
            )

    def _enforce_final_publish_audit(
        self, report_id: str, report: "Report"
    ) -> Dict[str, Any]:
        """Run the authoritative audit and convert execution failure into a hard stop."""
        try:
            audit = self._audit_final_published_markdown(report_id, report)
            self._require_final_publish_audit(audit)
            return audit
        except Exception as exc:  # noqa: BLE001 — caller must enter the failed-report path
            raise RuntimeError(
                "最终只读审计/发布完整性门失败，报告不标记为 completed："
                f"{exc}"
            ) from exc

    def _audit_final_published_markdown(
        self, report_id: str, report: "Report"
    ) -> Dict[str, Any]:
        """Audit the exact, immutable main-report Markdown and persist the result.

        This is the authoritative publish gate.  It MUST run after citation
        finalization and after every other main-report rewrite.  The function is
        deliberately read-only with respect to ``report.markdown_content`` and
        ``full_report.md``: the lint pass is evaluated but its candidate rewrite is
        discarded.  Audit evidence is written to ``final_audit.json`` and, when a
        structured forecast exists, merged into ``forecast.json`` before the publish
        gate is evaluated once.

        The claim-grounding audit excludes the References appendix (reference-list
        dates and display numbers are metadata, not forecast claims), while marker
        integrity and the SHA-256 fingerprint cover the exact complete Markdown.
        """
        from . import report_lint as _rl
        from .forecast_extractor import (
            audit_market_anchor_integrity as _audit_market_anchors,
            audit_proposition_consistency as _audit_propositions,
            audit_scenario_contract as _audit_scenarios,
            audit_citation_grounding as _acg,
            validate_citation_markers as _vcm,
        )

        md = report.markdown_content or ""
        if not md.strip():
            return {}

        folder = ReportManager._get_report_folder(report_id)
        full_report_path = os.path.join(folder, "full_report.md")
        memory_sha = hashlib.sha256(md.encode("utf-8")).hexdigest()
        disk_md: Optional[str] = None
        try:
            with open(full_report_path, "r", encoding="utf-8") as handle:
                disk_md = handle.read()
        except OSError:
            disk_md = None

        # Audit forecast claims without letting the deterministic References
        # appendix inflate citation coverage.  Marker integrity still scans the
        # complete published document below.
        chunks = self._split_markdown_h2_sections(md)
        reference_chunks = [
            chunk for chunk in chunks
            if chunk.split("\n", 1)[0].strip() in _REFS_HEADINGS
        ]
        body = "\n".join(
            chunk for chunk in chunks if chunk not in reference_chunks
        ).rstrip() + "\n"
        reference_text = "\n".join(reference_chunks)
        index_map = self._citation_index_or_fallback()
        citation_audit = _acg(
            body,
            index_map=index_map,
            exclude_authored_forecasts=True,
        )
        body_marker_audit = _vcm(body, index_map)
        marker_audit = _vcm(md, index_map)
        semantic_citation_audit = self._audit_semantic_citations(body, index_map)
        citation_artifacts = self._audit_final_citation_artifacts(
            folder,
            reference_text,
            body_marker_audit,
            index_map,
            enabled=bool(getattr(Config, "REPORT_CITATION_FINALIZER", True)),
        )
        quote_audit = self._audit_quote_provenance(body)

        # Load the structured forecast before the numeric cross-check.  A report
        # can still be audited without forecast.json; in that case the standalone
        # final_audit.json remains the durable evidence artifact.
        forecast: Optional[Dict[str, Any]] = None
        forecast_path = os.path.join(folder, "forecast.json")
        try:
            with open(forecast_path, "r", encoding="utf-8") as handle:
                candidate = json.load(handle)
            if isinstance(candidate, dict):
                forecast = candidate
        except (OSError, ValueError, TypeError):
            candidate = getattr(self, "_forecast_spine", None)
            if isinstance(candidate, dict):
                forecast = dict(candidate)

        numeric_audit = self._audit_numeric_consistency(body, forecast or {})
        structured_forecast_audit = {
            "required": bool(getattr(Config, "REPORT_STRUCTURED_FORECAST", True)),
            "present": isinstance(forecast, dict),
            "scenario_count": len((forecast or {}).get("scenarios") or []),
            "binary_count": len((forecast or {}).get("binary_forecasts") or []),
        }
        structured_forecast_audit["valid"] = bool(
            (not structured_forecast_audit["required"])
            or (
                structured_forecast_audit["present"]
                and structured_forecast_audit["scenario_count"] > 0
                and structured_forecast_audit["binary_count"] > 0
            )
        )
        proposition_audit = _audit_propositions(forecast or {})
        market_anchor_audit = _audit_market_anchors(forecast or {})
        scenario_contract_audit = _audit_scenarios(forecast or {})
        stat_audit = self._audit_stat_plausibility(body)
        lang = getattr(self, "output_language", None) or "English"
        _candidate_cleaned, lint_audit = _rl.lint_report(
            md,
            lang,
            mode="final",
            spine=forecast if isinstance(forecast, dict) else None,
        )

        audit: Dict[str, Any] = {
            "schema_version": 2,
            "policy_version": int(getattr(
                Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3
            )),
            "report_id": report_id,
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "read_only": True,
            "markdown_chars": len(md),
            "markdown_sha256": memory_sha,
            "disk_sha256": (
                hashlib.sha256(disk_md.encode("utf-8")).hexdigest()
                if disk_md is not None else None
            ),
            "disk_matches_memory": disk_md == md if disk_md is not None else False,
            "failed_sections": list(
                getattr(report, "failed_sections", None) or []
            ),
            "citation_grounding": citation_audit,
            "citation_body_markers": body_marker_audit,
            "citation_markers": marker_audit,
            "citation_artifacts": citation_artifacts,
            "semantic_citations": semantic_citation_audit,
            "quote_provenance": quote_audit,
            "numeric_consistency": numeric_audit,
            "structured_forecast": structured_forecast_audit,
            "scenario_contract": scenario_contract_audit,
            "proposition_consistency": proposition_audit,
            "market_anchor_integrity": market_anchor_audit,
            "stat_plausibility": stat_audit,
            # ``changed`` means a deterministic final lint would still rewrite the
            # published bytes; the candidate rewrite is intentionally discarded.
            "lint": lint_audit,
        }
        audit["hard_issues"] = self._final_audit_integrity_issues(audit)
        audit["hard_passed"] = not audit["hard_issues"]

        if forecast is not None:
            quality0 = forecast.get("quality")
            quality = dict(quality0) if isinstance(quality0, dict) else {}
            # Replace draft-stage audit values with measurements from the exact
            # post-citation document, including zero-finding results so stale
            # pre-finalization defects cannot survive.
            forecast["citation_audit"] = citation_audit
            quality["quote_provenance"] = quote_audit
            quality["numeric_consistency"] = numeric_audit
            quality["implausible_stats"] = stat_audit
            quality["final_audit"] = audit
            forecast["quality"] = quality
            if getattr(Config, "REPORT_PUBLISH_GATE", False):
                forecast = self._apply_publish_gate(forecast)

            final_quality = forecast.get("quality") or {}
            audit["publish_gate"] = {
                "enabled": bool(getattr(Config, "REPORT_PUBLISH_GATE", False)),
                "passed": final_quality.get("passed"),
                "issues": list(final_quality.get("issues") or []),
                "hard_issues": list(final_quality.get("hard_issues") or []),
                "epistemic_issues": list(
                    final_quality.get("epistemic_issues") or []
                ),
                "hard_passed": final_quality.get("hard_passed"),
                "citation_coverage": final_quality.get("citation_coverage"),
                "citation_coverage_basis": final_quality.get("citation_coverage_basis"),
                "probability_sum": final_quality.get("probability_sum"),
                "has_residual_scenario": final_quality.get("has_residual_scenario"),
            }
            # ``audit`` is already referenced by quality.final_audit; adding the
            # compact gate result above therefore persists in both artifacts.
            forecast_serialized = json.dumps(
                forecast, ensure_ascii=False, indent=2, allow_nan=False
            )
            write_text_atomic(forecast_path, forecast_serialized)
            # This external audit fingerprint intentionally seals the exact
            # forecast bytes after all self-contained quality fields are written.
            # It is not inserted back into forecast.json (which would be
            # self-referential). Any later ensemble/config mutation therefore
            # invalidates publication until the bundle is re-audited.
            audit["forecast_sha256"] = hashlib.sha256(
                forecast_serialized.encode("utf-8")
            ).hexdigest()
            self._forecast_spine = forecast

        write_json_atomic(
            os.path.join(folder, "final_audit.json"), audit, allow_nan=False
        )
        logger.info(
            f"最终只读审计: {report_id} sha256={memory_sha[:12]} "
            f"disk_match={audit['disk_matches_memory']} "
            f"dangling={len(marker_audit.get('dangling') or [])} "
            f"lint_would_change={lint_audit.get('changed')}"
        )
        return audit

    def _prepend_binary_forecasts_section(self, report_id: str, report: "Report") -> None:
        """QUALITY-OPT B1: insert the deterministic Part-1 binary-forecast table right after
        the report's H1 title, so the brief's headline deliverable leads the document and its
        numbers are guaranteed to match forecast.json. No-op if no binaries. Rewrites full_report.md.

        PM-2：紧随二元表插入确定性「### Market Cross-Check」块（预测 vs 市场隐含概率对照 +
        >10pp 判定 + 未匹配市场清单），数据取 forecast['binary_forecasts'][].market_anchor /
        market_comparison 与研究期快照 self._prediction_markets。无锚定/无未匹配市场 → 不追加。
        与二元表同处一次插入，受同一 Part-1 标记幂等门保护（重最终化绝不二次插入，H3 标记不干扰
        三部骨架对首个 "## " 详细章节的定位）。
        """
        from .forecast_extractor import (
            render_binary_forecasts_block, upsert_binary_forecasts_block,
        )
        fc = self._forecast_spine or {}
        if not (fc.get("binary_forecasts")):
            return
        _lang = (getattr(self, "output_language", None)
                 or getattr(Config, "DEERFLOW_RESEARCH_LANGUAGE", None) or "English")
        block = render_binary_forecasts_block(fc, language=_lang)
        if not block:
            return
        # PM-2：确定性市场交叉核对块，紧随二元表。degrade-safe：渲染失败/空 → 不追加。
        try:
            xcheck = render_market_comparison_block(
                fc, markets=getattr(self, "_prediction_markets", None), lang=_lang)
        except Exception as _xe:  # noqa: BLE001 — 对照块为增强，失败不影响二元表前置
            logger.warning(f"渲染 Market Cross-Check 块失败（忽略）: {_xe}")
            xcheck = ""
        if xcheck and not any(m in block for m in _MARKET_XCHECK_MARKERS):
            block = block + "\n\n" + xcheck
        md = report.markdown_content or ""
        new_md, action = upsert_binary_forecasts_block(md, block)
        if action == "noop" or new_md == md:
            return
        report.markdown_content = new_md
        try:
            folder = ReportManager._get_report_folder(report_id)
            write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
        except Exception as _we:  # noqa: BLE001
            logger.warning(f"重写 full_report.md（前置二元预测章节）失败（忽略）: {_we}")
        logger.info(f"已{('替换' if action == 'replaced' else '前置')} Part-1 二元预测章节: "
                    f"{report_id} ({len(fc.get('binary_forecasts') or [])} 条)")

    # ──────────────────────────────────────────────────────────────
    # B2: 三部结构骨架 — Part 1（二元预测）→ Part 2（框架综合）→ Part 3（附录详析）
    # ──────────────────────────────────────────────────────────────
    # 幂等判定 + 定位用标记（与 _prepend_binary_forecasts_section / 渲染器的标题一致）。
    _PART1_MARKERS = ("Part 1 — Binary Forecasts", "第一部分 · 二元预测")
    _PART2_MARKERS = ("Part 2 — Framework & Synthesis", "第二部分 · 框架与综合")

    # VIZ-1 钩子：manifest 的 placement_hint → 章节标题匹配关键词（中英并列）。Mermaid 图按此
    # 把图就地插到最相关的详细章节标题后；无命中 → 归入文末「Visual Annex / 可视化附录」。
    _VIZ_PLACEMENT_KEYWORDS = {
        "timeline": ("timeline", "chronology", "时间线", "时间轴", "事件脉络", "沿革"),
        "actors": ("actor", "stakeholder", "coalition", "faction", "player",
                   "角色", "参与者", "行动者", "派系", "阵营", "利益相关"),
        "drivers": ("driver", "causal", "mechanism", "dynamic", "catalyst",
                    "驱动", "因果", "机制", "动力", "催化"),
        "scenarios": ("scenario", "情景", "情境", "剧本", "路径"),
        "binary_forecasts": ("forecast", "probability", "market", "prediction",
                             "预测", "概率", "市场", "赔率"),
        "simulation": ("simulation", "trajectory", "model", "outcome", "world",
                       "模拟", "推演", "轨迹", "世界态", "结果分布", "建模"),
        "comparison": ("comparison", "baseline", "counterfactual", "contrast",
                       "对比", "基线", "反事实", "对照", "情景差"),
        "calibration": ("calibration", "reliability", "校准", "可靠", "信度"),
        "quantitative": ("market", "adoption", "demand", "consumer", "regional",
                         "technology", "battery", "cost", "supply", "industry",
                         "市场", "渗透", "需求", "消费", "区域", "技术", "电池",
                         "成本", "供应", "产业"),
        "forecast_revisions": ("forecast", "outlook", "projection", "market", "policy",
                               "预测", "展望", "市场", "政策", "情景"),
    }

    def _binary_min_count(self) -> int:
        """B2: 二元预测最小数量 = max(需求书解析出的 binary_min_count, Config 默认)。

        需求书写明「15+ binary forecasts」时不能被 Config 的 10 静默压低；spec 未解析出
        数量/解析失败时沿用 Config（degrade-safe，与历史行为一致）。"""
        try:
            n = int(getattr(Config, "BINARY_FORECASTS_MIN_COUNT", 10) or 10)
        except (TypeError, ValueError):
            n = 10
        try:
            from .requirement_spec import parse_requirement_spec
            spec_n = parse_requirement_spec(
                getattr(self, "simulation_requirement", "") or "",
                getattr(self, "research_report", "") or "",
            ).get("binary_min_count")
            if spec_n:
                n = max(n, int(spec_n))
        except Exception:  # noqa: BLE001 — spec 解析失败沿用 Config
            pass
        return n

    def _section_key_points(self, report_markdown: str, max_sections: int = 8,
                            per_section_chars: int = 350, max_chars: int = 4000) -> str:
        """B2: 确定性截取各详细章节的「要点」（标题 + 开头片段）供 Part 2 综合，
        有界回灌避免整稿吃进提示词。跳过 Part 1 表格块；无章节返回 ""。"""
        lines = (report_markdown or "").split("\n")
        sections: List[tuple] = []  # (title, body_lines)
        cur_title = None
        cur_body: List[str] = []
        for ln in lines:
            s = ln.strip()
            if s.startswith("## "):
                if cur_title is not None:
                    sections.append((cur_title, cur_body))
                title = s[3:].strip()
                cur_title = None if any(m in title for m in self._PART1_MARKERS) else title
                cur_body = []
            elif cur_title is not None:
                cur_body.append(ln)
        if cur_title is not None:
            sections.append((cur_title, cur_body))
        segs: List[str] = []
        for title, body in sections[:max_sections]:
            text = " ".join(x.strip() for x in body if x.strip())
            # WAVE9：先剔除泄漏模式句（模拟机制叙述/元评论），再截 350 字——否则章节开头的
            # 泄漏元叙述会被原样喂给 Part-2 综合，催生自指句（full_report.md:66 型故障）。
            try:
                from . import report_lint as _rl
                text, _ = _rl.strip_leakage_sentences(text)
            except Exception:  # noqa: BLE001 — 剔除失败退回原文截断
                pass
            text = text[:per_section_chars]
            segs.append(f"- {title}: {text}")
        out = "\n".join(segs)
        return out[:max_chars]

    def _build_part2_synthesis(self, report_markdown: str) -> str:
        """B2: 一次 LLM 调用生成 Part 2「框架与综合」正文——从预测骨架 + 各章要点 +
        预测市场信号包做紧凑综合（RQ-1：默认 ≤~2800 词；需求书解析出 page_budget 时按
        ~150 词/页折算收紧，下限 600 词）。失败/过短返回 ""（调用方跳过，绝不写占位符）。"""
        lang = getattr(self, "output_language", None) or "English"
        cap_words = 2800
        try:
            from .requirement_spec import parse_requirement_spec
            _pb = parse_requirement_spec(
                getattr(self, "simulation_requirement", "") or "",
                getattr(self, "research_report", "") or "",
            ).get("page_budget")
            if _pb:
                cap_words = max(600, min(2800, int(_pb) * 150))
        except Exception:  # noqa: BLE001 — spec 解析失败用默认词数
            pass
        from .forecast_extractor import render_forecast_spine_block
        try:
            spine_block = (render_forecast_spine_block(self._forecast_spine)
                           if getattr(self, "_forecast_spine", None) else "")
        except Exception:  # noqa: BLE001
            spine_block = ""
        parts: List[str] = []
        if spine_block:
            parts.append("[Forecast spine]\n" + spine_block[:3000])
        mp = getattr(self, "_market_pack", "")
        if mp:
            # PM-2：Part-2 综合注入完整市场包（此前 [:2500] 截断会丢掉尾部低成交量但高相关的市场）。
            parts.append("[Prediction market signals]\n" + str(mp))
        key_points = self._section_key_points(report_markdown)
        if key_points:
            parts.append("[Section key points]\n" + key_points)
        if not parts:
            return ""  # 没有任何可综合的输入 → 跳过（绝不让模型凭空写）
        prompt = (
            "You are the lead forecaster assembling 'Part 2 — Framework & Synthesis' of a "
            "three-part forecast submission (Part 1 = the binary-forecast table, Part 3 = the "
            "detailed appendix).\n"
            f"Write a TIGHT synthesis of AT MOST {cap_words} words in {lang}: the analytical "
            "framework, the causal logic connecting the key drivers to the Part-1 probabilities, "
            "the decisive evidence, and how the prediction-market anchors (when present) were "
            "weighed. DEFEND the spine's probabilities — do not introduce numbers that contradict "
            "them. Use short paragraphs and at most '###' sub-headings; do NOT emit a '## Part 2' "
            "top-level heading (the system adds it); no placeholders or meta commentary. "
            "NEVER mention the simulation, agents, rounds, action counts, factions, causal graphs, "
            "or this report's own drafting process; attribute analytical viewpoints to our "
            "scenario analysis instead — the subject is always the real world.\n\n"
            + "\n\n".join(parts)
        )
        text = self.llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3, max_tokens=8192,  # RQ-1: 4096→8192，容纳 ~2800 词综合
        )
        text = str(text or "").strip()
        # 剥掉模型可能自带的 Part 2 大标题（系统会加），避免双标题。
        text = re.sub(r"^#{1,2}\s*(?:Part\s*2|第二部分)[^\n]*\n+", "", text, count=1).strip()
        return text if len(text) >= 200 else ""

    def _apply_three_part_skeleton(self, report_id: str, report: "Report") -> None:
        """B2: 把成稿重排为三部结构——在已前置的 Part 1 二元预测表之后插入
        「Part 2 — Framework & Synthesis」（一次 LLM 紧凑综合），随后以
        「Part 3 — Appendix: Detailed Analysis」标题包住既有详细章节（纯结构性重标签，
        不动章节内容）。仅在 Part 1 已插入时生效；幂等（已有 Part 2 标记即跳过）；
        综合失败/过短 → 一行告警并整体跳过（绝不写占位符，成稿保持原结构）。
        """
        md = report.markdown_content or ""
        if not md or not any(m in md for m in self._PART1_MARKERS):
            return  # 无 Part 1（无二元预测）→ 不套三部结构
        if any(m in md for m in self._PART2_MARKERS):
            return  # 幂等 — 重复最终化时绝不二次插入
        synthesis = self._build_part2_synthesis(md)
        if not synthesis:
            logger.warning("Part 2 综合生成失败/为空，跳过三部结构骨架（保留原结构，不写占位符）")
            return
        zh = not str(getattr(self, "output_language", "") or "English").lower().startswith("en")
        if zh:
            part2_head = "## 第二部分 · 框架与综合（Part 2 — Framework & Synthesis）"
            part3_head = "## 第三部分 · 附录：详细分析（Part 3 — Appendix: Detailed Analysis）"
            part3_note = "_以下为支撑第一、二部分的逐章详细分析。_"
        else:
            part2_head = "## Part 2 — Framework & Synthesis"
            part3_head = "## Part 3 — Appendix: Detailed Analysis"
            part3_note = "_The detailed, section-by-section analysis supporting Parts 1–2 follows._"
        lines = md.split("\n")
        # 定位第一个非 Part-1 的 "## " 标题 = 详细章节起点；Part 2 + Part 3 标题插在其前。
        insert_at = None
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("## ") and not any(m in s for m in self._PART1_MARKERS):
                insert_at = i
                break
        block = [part2_head, "", synthesis, "", part3_head, "", part3_note, ""]
        if insert_at is None:
            new_lines = lines + [""] + block  # 无详细章节（边界）：附在末尾，Part 3 空壳仍标出
        else:
            new_lines = lines[:insert_at] + block + lines[insert_at:]
        new_md = "\n".join(new_lines)
        report.markdown_content = new_md
        try:
            folder = ReportManager._get_report_folder(report_id)
            write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
        except Exception as _we:  # noqa: BLE001
            logger.warning(f"重写 full_report.md（三部结构骨架）失败（忽略）: {_we}")
        logger.info(f"已套用三部结构骨架（Part 2 综合 {len(synthesis)} 字）: {report_id}")

    # ──────────────────────────────────────────────────────────────
    # VIZ-1 钩子：确定性可视化注入（build_all → 图表落盘 → 注入成稿）
    # ──────────────────────────────────────────────────────────────
    def _inject_visualizations(self, report_id: str, report: "Report") -> None:
        """VIZ-1 钩子：调用 ReportVisualizer.build_all 由已落盘的结构化工件（forecast/comparison/
        actors/world_state_trajectory/timeline）确定性生成图表（charts/*.mmd + *.png +
        viz_manifest.json），再把图注入成稿——Mermaid 块按章节标题/关键词模糊匹配就地插入，
        未匹配的图（含全部 PNG）汇入文末「## Visual Annex / 可视化附录」（双语随报告语言）。
        PNG 用相对路径 charts/xxx.png（Web 经 /charts 端点、PDF 经绝对化重写都成立）。

        幂等：每个图带唯一 HTML 注释标记（<!-- viz:charts/xxx --> ），重最终化命中标记即跳过。
        与 _prepend_binary_forecasts_section 同族的「marker 幂等 + 原子重写」模式；任何失败降级为
        一行告警 + 不改成稿（图仍已落盘，degrade-safe）。调用点在 Part-1 前置之后、三部骨架之前。
        """
        if not getattr(Config, "REPORT_VISUALIZATIONS", True):
            return
        md = report.markdown_content or ""
        if not md:
            return
        try:
            from .report_visualizer import ReportVisualizer
        except Exception as _ie:  # noqa: BLE001 — 可视化器不可用即跳过（degrade-safe）
            logger.warning(f"可视化器不可用，跳过图表注入（忽略）: {_ie}")
            return
        folder = ReportManager._get_report_folder(report_id)
        artifacts = self._collect_viz_artifacts(report_id, folder)
        try:
            manifest = ReportVisualizer().build_all(report_id, folder, artifacts)
        except Exception as _be:  # noqa: BLE001 — 生成失败不影响主报告
            logger.warning(f"ReportVisualizer.build_all 失败（忽略，成稿不含图区）: {_be}")
            return
        if not manifest:
            return
        try:
            new_md = self._place_visualizations(md, folder, manifest)
        except Exception as _pe:  # noqa: BLE001 — 注入失败保留原文
            logger.warning(f"图表注入成稿失败（忽略，保留原文）: {_pe}")
            return
        if new_md == md:
            return  # 幂等 no-op（全部图已注入或无可注入项）
        report.markdown_content = new_md
        try:
            write_text_atomic(os.path.join(folder, "full_report.md"), new_md)
        except Exception as _we:  # noqa: BLE001
            logger.warning(f"回写注入图表后 full_report.md 失败（忽略）: {_we}")
        logger.info(f"已注入 {len(manifest)} 项报告可视化: {report_id}")

    def _collect_viz_artifacts(self, report_id: str, folder: str) -> Dict[str, Any]:
        """汇集 build_all 消费的结构化工件（全部可选，缺失即跳过对应图）。来源皆为报告代理已有
        路径：报告文件夹的 forecast.json / comparison.json / market_comparison.json、内存
        self.actors、模拟目录的 world_state_trajectory.json、研究 handoff 的 timeline.json。"""
        def _rj(path: str) -> Optional[Any]:
            try:
                if path and os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
            except Exception:  # noqa: BLE001
                return None
            return None

        arts: Dict[str, Any] = {}
        # forecast.json（scenarios / binary_forecasts / 内嵌 market_comparison）——文件优先，
        # 缺失回退内存骨架。
        forecast = _rj(os.path.join(folder, "forecast.json"))
        if not isinstance(forecast, dict):
            forecast = self._forecast_spine if isinstance(self._forecast_spine, dict) else None
        if isinstance(forecast, dict):
            # PM-2：market_comparison 优先取 forecast 内嵌；缺失时补读独立 market_comparison.json。
            if not forecast.get("market_comparison"):
                mc = _rj(os.path.join(folder, "market_comparison.json"))
                if mc:
                    forecast = dict(forecast)
                    forecast["market_comparison"] = mc
            arts["forecast"] = forecast
        comp = _rj(os.path.join(folder, "comparison.json"))
        if comp:
            arts["comparison"] = comp
        if isinstance(self.actors, dict):
            arts["actors"] = self.actors
        # GATE-W9 seam fix：build_all（schema v2）新增 plotly 构建器消费 ensemble /
        # quantitative / sources / contested / graph_priors(_structural)，此前从未接线
        # （diag-viz-audit「dead builders」）。ensemble_forecast.json 由编排器同步落到报告
        # 目录；其余直接取构造期钉入的内存工件（W9-8 直通），缺失即跳过（degrade-safe）。
        ens = _rj(os.path.join(folder, "ensemble_forecast.json"))
        if isinstance(ens, dict) and ens:
            arts["ensemble"] = ens
        if isinstance(getattr(self, "quantitative", None), list) and self.quantitative:
            arts["quantitative"] = self.quantitative
        if isinstance(getattr(self, "sources", None), list) and self.sources:
            arts["sources"] = self.sources
        if isinstance(getattr(self, "contested", None), list) and self.contested:
            arts["contested"] = self.contested
        if isinstance(getattr(self, "graph_priors", None), dict) and self.graph_priors:
            arts["graph_priors"] = self.graph_priors
        if isinstance(getattr(self, "graph_priors_structural", None), dict) and self.graph_priors_structural:
            arts["graph_priors_structural"] = self.graph_priors_structural
        # world_state_trajectory.json（决策通道产物，模拟数据目录）
        try:
            wst_path = os.path.join(
                getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "",
                str(self.simulation_id or ""), "world_state_trajectory.json")
            wst = _rj(wst_path)
            if wst:
                arts["world_state_trajectory"] = wst
        except Exception:  # noqa: BLE001
            pass
        # timeline.json（研究 handoff；best-effort，找不到即不画时间线）
        tl = self._locate_timeline()
        if not tl and isinstance(getattr(self, "timeline_events", None), list) and self.timeline_events:
            tl = self.timeline_events  # GATE-W9：handoff 定位失败时回退构造期钉入的 timeline（W9-8 直通）
        if tl:
            arts["timeline"] = tl
        # PM-6 修复：把研究 handoff 目录钉进工件，供 ReportVisualizer._load_price_history 定位
        # handoff/market_price_history.json（bridge 在研究期落盘的 {market_id:[{t,p}]}）。此前
        # _collect_viz_artifacts 从不提供 handoff_dir/market_price_history，且无人把该文件拷进
        # reports/{id}/，故 PM-6 市场价格历史折线族一直拿不到数据、整族静默跳过（永不出图）。
        # 缺失/失败即不设该键（degrade-safe，价格历史图仍自动跳过，行为不变）。
        hd = self._locate_handoff_dir()
        if hd:
            arts["handoff_dir"] = hd
        return arts

    def _locate_handoff_dir(self) -> Optional[str]:
        """best-effort 定位本报告对应管线的研究 handoff 目录（按 simulation_id 匹配，与
        _locate_timeline 同模式）。供 PM-6 市场价格历史折线定位 handoff/market_price_history.json。
        找不到/任何失败 → None（degrade-safe）。延迟导入避免与 pipeline_orchestrator 的循环依赖。"""
        try:
            from .pipeline_orchestrator import PipelineManager
            for entry in PipelineManager.list_pipelines():
                pid = entry.get("pipeline_id")
                if not pid:
                    continue
                data = PipelineManager.load(pid)
                if not data or data.get("simulation_id") != self.simulation_id:
                    continue
                hd = data.get("handoff_dir") or PipelineManager.handoff_dir(pid)
                return hd or None
        except Exception:  # noqa: BLE001
            return None
        return None

    def _locate_timeline(self) -> Optional[Any]:
        """best-effort 定位研究 handoff 的 timeline.json（经 PipelineManager 按 simulation_id
        匹配管线，与 load_research_dossier_for_simulation 同模式）。找不到/任何失败 → None
        （degrade-safe，时间线图自动跳过）。延迟导入避免与 pipeline_orchestrator 的循环依赖。"""
        try:
            from .pipeline_orchestrator import PipelineManager
            for entry in PipelineManager.list_pipelines():
                pid = entry.get("pipeline_id")
                if not pid:
                    continue
                data = PipelineManager.load(pid)
                if not data or data.get("simulation_id") != self.simulation_id:
                    continue
                hd = data.get("handoff_dir") or PipelineManager.handoff_dir(pid)
                path = os.path.join(hd or "", "timeline.json")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        return json.load(f)
                return None
        except Exception:  # noqa: BLE001
            return None
        return None

    def _place_visualizations(self, md: str, folder: str,
                              manifest: List[Dict[str, str]]) -> str:
        """把 manifest 的图注入成稿：所有可视化类型都按 placement_hint 匹配到相关章节后
        就地插入；只有未匹配项才汇入文末「Visual Annex」。逐图带唯一标记 → 幂等
        （已注入的图跳过）。无可注入项 → 原样返回 md。"""
        zh = not str(getattr(self, "output_language", "") or "English").lower().startswith("en")
        lines = md.split("\n")
        # 预扫描 "## " 详细章节标题（行号 + 小写标题），供 Mermaid 就地放置的模糊匹配。
        headings: List[Tuple[int, str]] = []
        for i, ln in enumerate(lines):
            s = ln.strip()
            if s.startswith("## "):
                headings.append((i, s[3:].strip().lower()))
        inserts: Dict[int, List[str]] = {}   # 标题行号 → [图 markdown 块, ...]
        annex: List[str] = []
        for item in manifest:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            if not path:
                continue
            marker = f"<!-- viz:{path} -->"
            if marker in md:
                continue  # 幂等：该图已注入
            vtype = str(item.get("type") or "").strip().lower()
            caption = str(item.get("caption") or "").strip()
            hint = str(item.get("placement_hint") or item.get("hint") or "").strip().lower()
            png_path = str(item.get("png_path") or "").strip()
            block = self._render_viz_block(folder, path, vtype, caption, marker, zh,
                                           png_path=png_path)
            if not block:
                continue
            target = self._match_section(headings, hint)
            if target is not None:
                inserts.setdefault(target, []).append(block)
            else:
                annex.append(block)
        if not inserts and not annex:
            return md
        # 就地插入（从后往前，避免行号漂移）。插入点=标题行之后、跳过其后紧邻的空行。
        for line_no in sorted(inserts.keys(), reverse=True):
            at = line_no + 1
            while at < len(lines) and not lines[at].strip():
                at += 1
            payload: List[str] = []
            for blk in inserts[line_no]:
                payload.extend(["", blk, ""])
            lines[at:at] = payload
        new_md = "\n".join(lines)
        if annex:
            head = "## 可视化附录（Visual Annex）" if zh else "## Visual Annex"
            note = ("_以下为支撑本报告的确定性可视化，均自结构化工件生成。_" if zh else
                    "_Deterministic visualizations supporting this report, generated from "
                    "structured artifacts._")
            body = "\n\n".join(annex)
            # 附录标题已存在（重最终化残留）→ 仅追加未注入图（每图受自身标记幂等保护）。
            if head not in new_md:
                new_md = new_md.rstrip() + "\n\n" + head + "\n\n" + note + "\n\n" + body + "\n"
            else:
                new_md = new_md.rstrip() + "\n\n" + body + "\n"
        return new_md

    @staticmethod
    def _render_viz_block(folder: str, path: str, vtype: str,
                          caption: str, marker: str, zh: bool,
                          png_path: str = "") -> str:
        """把单个 manifest 图渲染成 markdown 块：Mermaid 读 charts/*.mmd 内联其 ```mermaid 围栏；
        PNG 用相对图片语法（charts/xxx.png）；plotly HTML（schema v2）优先内嵌其 png_path 静态
        对（kaleido/matplotlib 回退产物）；Web 阅读器根据同一 manifest 在图片旁附一次交互
        链接，无 PNG 对才在 Markdown 内退化为纯链接——此前无
        'html' 分支导致 plotly 图整族孤儿在盘上（diag-viz-audit）。每块以唯一 HTML 注释标记
        打头（幂等定位）。读不到/空/未知类型 → ''。"""
        cap = caption or ("图示" if zh else "Figure")
        if vtype == "mermaid":
            try:
                with open(os.path.join(folder, path), "r", encoding="utf-8") as f:
                    code = f.read().strip()
            except Exception:  # noqa: BLE001
                return ""
            if not code:
                return ""
            return f"{marker}\n**{cap}**\n\n{code}"
        if vtype == "png":
            return f"{marker}\n![{cap}]({path})\n\n*{cap}*"
        if vtype == "html":
            link_txt = "交互版" if zh else "interactive version"
            if png_path and os.path.exists(os.path.join(folder, png_path)):
                return f"{marker}\n![{cap}]({png_path})\n\n*{cap}*"
            return f"{marker}\n**{cap}**：[{link_txt}]({path})" if zh else \
                   f"{marker}\n**{cap}**: [{link_txt}]({path})"
        return ""

    @classmethod
    def _match_section(cls, headings: List[Tuple[int, str]], hint: str) -> Optional[int]:
        """按 placement_hint 的关键词在详细章节标题里模糊匹配，返回首个命中的标题行号；
        hint 未知或无命中 → None（该图归附录）。"""
        if not headings or not hint:
            return None
        keys = cls._VIZ_PLACEMENT_KEYWORDS.get(hint)
        if not keys:
            return None
        for line_no, title in headings:
            for k in keys:
                if k and k in title:
                    return line_no
        return None

    @staticmethod
    def _apply_publish_gate(forecast: Dict[str, Any]) -> Dict[str, Any]:
        """NEXTSTEPS P2-3: coherence + grounding publish gate.

        A calibrated forecaster must refuse to silently publish incoherent or
        ungrounded probability sets. Checks citation coverage of quantitative claims,
        probability-sum coherence, presence of a residual/status-quo scenario, and
        degenerate entropy; records ``forecast['quality']``. Epistemic defects demote
        ``confidence`` at most one level; artifact/coherence defects populate
        ``hard_issues`` and must be blocked by the final audit caller. Pure; never raises.
        """
        try:
            scenarios = forecast.get("scenarios") or []
            audit = forecast.get("citation_audit") or {}
            # Post-citation audits carry ``resolved_coverage``: only markers that
            # map to the real source index count.  Prefer that strict metric when
            # available; legacy forecasts without an index retain ``coverage``.
            _coverage_basis = (
                "resolved_coverage"
                if "resolved_coverage" in audit else "coverage"
            )
            coverage = float(audit.get(_coverage_basis, 1.0) or 0.0)
            min_cov = float(getattr(Config, "REPORT_PUBLISH_GATE_MIN_COVERAGE", 0.5) or 0.0)
            probs: List[float] = []
            for s in scenarios:
                try:
                    probs.append(float(s.get("probability") or 0.0))
                except (TypeError, ValueError):
                    pass
            prob_sum = round(sum(probs), 3)
            # GLM-run 2026-09-18: keep in lockstep with forecast_extractor's
            # canonical residual-label list (_RESIDUAL_LABELS / line ~119) — the
            # extractor legitimately names the baseline "基准/基线/剩余", and an
            # audit list missing those synonyms failed a correct 4-scenario
            # MECE frame whose baseline was literally named "基准扩张".
            _residual_keys = ("维持现状", "基准", "基线", "其它", "其他", "兜底",
                              "剩余", "status", "other", "baseline", "residual")
            has_residual = any(
                any(k in str(s.get("name", "")).lower() for k in _residual_keys)
                for s in scenarios
            )
            top = max(probs) if probs else 0.0
            epistemic_issues: List[str] = []
            hard_issues: List[str] = []
            if scenarios and coverage < min_cov:
                epistemic_issues.append(
                    f"定量声明引用覆盖率 {coverage:.2f} < 阈值 {min_cov:.2f}"
                )
            if scenarios and abs(prob_sum - 1.0) > 0.05:
                hard_issues.append(f"情景概率之和 {prob_sum} 偏离 1")
            if scenarios and not has_residual:
                hard_issues.append("缺少『维持现状/兜底』情景")
            if top >= 0.9 and len(probs) <= 1:
                epistemic_issues.append("概率分布退化（单情景≥0.9 且无对照情景）")
            # QUALITY-OPT: fold the binary-forecast conviction/objectivity gate (A3/A4) +
            # the S2/S11/S12 audits into the publish gate so they actually demote confidence.
            bq = forecast.get("binary_quality") or {}
            if bq and not bq.get("passed", True):
                epistemic_issues.append(
                    "二元预测信心/客观性门未过："
                    + "；".join((bq.get("issues") or [])[:2])
                )
            _q0 = forecast.get("quality")
            _existing_q = _q0 if isinstance(_q0, dict) else {}
            if (_existing_q.get("quote_provenance") or {}).get("ungrounded"):
                hard_issues.append(
                    f"{_existing_q['quote_provenance']['ungrounded']} 条疑似嫁接/捏造引用 (S2)"
                )
            if (_existing_q.get("numeric_consistency") or {}).get("mismatch_count"):
                hard_issues.append(
                    f"{_existing_q['numeric_consistency']['mismatch_count']} 处正文概率与 forecast.json 不符 (S11)"
                )
            # GLM-run 2026-09-18: S12 is an observability-grade prose heuristic
            # by its own docstring. In AI-infrastructure domains >100% YoY growth
            # is documented reality (Vertiv +168%, Tencent Q4 capex +386%), so
            # uncited-but-plausible extremes stay observability-only (logged);
            # only misparse-grade values (>1000%: decimal/unit errors) block.
            _imp = _existing_q.get("implausible_stats") or {}
            if _imp.get("count") and float(_imp.get("max_flagged") or 0) > 1000.0:
                epistemic_issues.append(
                    f"{_imp['count']} 处疑似不合理极端增长率 (S12, max={_imp.get('max_flagged')}%)"
                )
            elif _imp.get("count"):
                logger.warning(
                    "S12 观测: %s 处 >100%% 增长表述（max=%s%%，行业可解释，不阻断）: %s",
                    _imp.get("count"), _imp.get("max_flagged"),
                    str(_imp.get("implausible_stats"))[:300],
                )
            # LOOP-010: when called by the post-citation read-only audit, gate the
            # exact published bytes rather than the earlier mutable draft.  A disk
            # mismatch, dangling marker, residual process leakage, or a deterministic
            # lint that would still rewrite the document is a publish-quality defect.
            _final_audit = _existing_q.get("final_audit") or {}
            if _final_audit:
                for issue in ReportAgent._final_audit_integrity_issues(_final_audit):
                    if issue not in hard_issues:
                        hard_issues.append(issue)
            issues = hard_issues + epistemic_issues
            # Preserve the model's pre-publish confidence/rationale exactly once.
            # Every re-audit derives from this baseline, so repeated backfills can
            # never ratchet high→medium→low.  A clean re-audit restores the baseline.
            levels = ["low", "medium", "high"]
            order = {"low": 0, "medium": 1, "high": 2}
            _baseline = str(
                _existing_q.get("pre_publish_confidence")
                or forecast.get("confidence", "medium")
            ).lower()
            if _baseline not in order:
                _baseline = "medium"
            _baseline_rationale = _existing_q.get("pre_publish_confidence_rationale")
            if _baseline_rationale is None:
                _baseline_rationale = str(
                    forecast.get("confidence_rationale", "") or ""
                ).strip()

            # MERGE into quality (do NOT overwrite the audit findings stored earlier).
            quality = dict(_existing_q)
            quality.update({
                "pre_publish_confidence": _baseline,
                "pre_publish_confidence_rationale": _baseline_rationale,
                "citation_coverage": round(coverage, 3),
                "citation_coverage_basis": _coverage_basis,
                "probability_sum": prob_sum,
                "has_residual_scenario": has_residual,
                "max_probability": round(top, 3),
                "hard_issues": hard_issues,
                "epistemic_issues": epistemic_issues,
                "hard_passed": not hard_issues,
                "issues": issues,
                "passed": not issues,
            })
            forecast["quality"] = quality
            if epistemic_issues:
                forecast["confidence"] = levels[max(0, order[_baseline] - 1)]
                forecast["confidence_rationale"] = (
                    (
                        str(_baseline_rationale)
                        + " ｜证据/校准门："
                        + "；".join(epistemic_issues)
                    ).strip(" ｜")
                )
            else:
                forecast["confidence"] = _baseline
                forecast["confidence_rationale"] = str(_baseline_rationale)
        except Exception as _qe:  # noqa: BLE001 — convert evaluator failure into a hard gate
            logger.warning(f"发布门计算失败（标记为硬失败）: {_qe}")
            _q0 = forecast.get("quality")
            quality = dict(_q0) if isinstance(_q0, dict) else {}
            failure = f"发布门计算失败：{type(_qe).__name__}"
            hard = list(quality.get("hard_issues") or [])
            if failure not in hard:
                hard.append(failure)
            epistemic = list(quality.get("epistemic_issues") or [])
            quality.update({
                "hard_issues": hard,
                "epistemic_issues": epistemic,
                "hard_passed": False,
                "issues": hard + epistemic,
                "passed": False,
            })
            forecast["quality"] = quality
        return forecast

    # ──────────────────────────────────────────────────────────────
    # EXECPLAN2 I-3-4: 结构化「基线 vs 情景」对比表（确定性，无 LLM）
    # 数据源是 decision-channel 的最终 P(outcome) 世界态。内部动作量、轮次、活跃度等
    # 运行机制永不进入报告对比表；无结果分布时宁可跳过该表，也不拿平台活动当结果代理。
    # ──────────────────────────────────────────────────────────────
    def _scenario_diff_structured(self) -> Optional[Dict[str, Any]]:
        """把基线/情景两份最终 P(outcome) 归一化为可比维度的字典。

        返回 {dimensions:[{name, baseline, scenario, delta, verdict}]}；任一侧缺少
        world_state_trajectory.json / outcome.shares 时返回 None。
        """
        if not self.base_simulation_id:
            return None
        def _shares(simulation_id: str) -> Dict[str, float]:
            path = os.path.join(
                getattr(Config, "OASIS_SIMULATION_DATA_DIR", "") or "",
                str(simulation_id or ""), "world_state_trajectory.json",
            )
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    raw = ((json.load(handle) or {}).get("outcome") or {}).get("shares") or {}
            except (OSError, ValueError, TypeError):
                return {}
            out: Dict[str, float] = {}
            for name, value in raw.items() if isinstance(raw, dict) else []:
                try:
                    number = float(value)
                except (TypeError, ValueError):
                    continue
                if number >= 0:
                    out[str(name)] = number
            total = sum(out.values())
            return ({name: value / total for name, value in out.items()} if total > 0 else {})

        base_shares = _shares(self.base_simulation_id)
        scenario_shares = _shares(self.simulation_id)
        if not base_shares or not scenario_shares:
            return None

        dims: List[Dict[str, Any]] = []
        names = sorted(set(base_shares) | set(scenario_shares), key=lambda name: (
            -max(base_shares.get(name, 0.0), scenario_shares.get(name, 0.0)), name,
        ))
        for name in names:
            baseline = base_shares.get(name, 0.0) * 100
            scenario = scenario_shares.get(name, 0.0) * 100
            delta = scenario - baseline
            dims.append({
                "name": name,
                "baseline": f"{baseline:.1f}%",
                "scenario": f"{scenario:.1f}%",
                "delta": f"{delta:+.1f} pp",
                "verdict": "更可能" if delta > 0.05 else ("更不可能" if delta < -0.05 else "基本不变"),
            })

        return {
            "base_simulation_id": self.base_simulation_id,
            "scenario_simulation_id": self.simulation_id,
            "scenario_label": self.scenario_label,
            "dimensions": dims,
        }

    @staticmethod
    def _is_comparison_section(title: str) -> bool:
        """EXECPLAN2 I-3-4: 判定某章节是否为「情景对比 / 反事实」章节。

        plan_outline 在有基线时已强制大纲含标题含「情景对比」或「反事实」的章节，
        这里据此识别需要前置对比表的章节。"""
        t = (title or "")
        return ("情景对比" in t) or ("反事实" in t)

    @staticmethod
    def _render_comparison_table(diff_dict: Dict[str, Any]) -> str:
        """EXECPLAN2 I-3-4: 把结构化对比字典渲染为 GFM Markdown 表格（数据缺失的行自动跳过）。"""
        dims = diff_dict.get("dimensions") or []
        if not dims:
            return ""

        def _esc(v: Any) -> str:
            # 表格单元转义竖线/换行，避免破坏 Markdown 表格结构
            return str(v).replace("|", "\\|").replace("\n", " ").strip()

        scen_label = (diff_dict.get("scenario_label") or "").strip()
        scen_col = f"情景（{scen_label}）" if scen_label else "情景"
        lines = [
            "**基线 vs 情景 结构化对比（确定性聚合，权威）**",
            "",
            f"| 维度 | 基线 | {_esc(scen_col)} | Δ | 判定 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for d in dims:
            lines.append(
                f"| {_esc(d.get('name'))} | {_esc(d.get('baseline'))} | "
                f"{_esc(d.get('scenario'))} | {_esc(d.get('delta'))} | {_esc(d.get('verdict'))} |"
            )
        lines.append("")
        lines.append("> 上表为确定性聚合结果，正文请围绕这些权威差值展开解读，勿自行复算或反转方向。")
        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────
    # EXECPLAN2 I-5-4: 报告级 LLM 成本/时延遥测（per-section + totals）
    # 复用中央 LLMMeter（按 run_id=report_id 聚合）。每章节前后各取一次累计快照，
    # 相减即为该章节触发的 LLM 经济学（tokens / cost / latency / calls）。
    # 全程 degrade-safe：未开 LLM_TELEMETRY_ENABLED & REPORT_TELEMETRY 时不调用本逻辑。
    # ──────────────────────────────────────────────────────────────
    def _telemetry_enabled(self) -> bool:
        """两个开关都为真才采集：底层计量已开（LLM_TELEMETRY_ENABLED），且报告级汇总已开。"""
        return bool(
            getattr(Config, "LLM_TELEMETRY_ENABLED", False)
            and getattr(Config, "REPORT_TELEMETRY", False)
        )

    def _meter_total(self, run_id: str) -> Dict[str, Any]:
        """读取本 run 的累计 LLM 计量 total（失败返回零值，绝不抛出）。

        用于 per-section 区间差值：章节循环期间 stage 恒为 'report'，故 total 的增量即本章节
        触发的 LLM 经济学（哪怕 run_id 与上游共享，区间差值仍只含本报告期间的调用）。
        """
        try:
            return dict(LLMMeter.snapshot(run_id).get("total") or {})
        except Exception:  # noqa: BLE001 — 遥测读取失败不得影响报告生成
            return {}

    def _meter_stage_total(self, run_id: str, stage: str = "report") -> Dict[str, Any]:
        """读取本 run 中指定 stage 的累计 LLM 计量（失败返回零值，绝不抛出）。

        用于报告级 totals：当 run_id 是上游编排器的共享 run（如 pipeline_id）时，total 会混入
        其它阶段（research/ontology/...）的调用；按 stage='report' 切片可只统计报告阶段花销。
        """
        try:
            by_stage = LLMMeter.snapshot(run_id).get("by_stage") or {}
            return dict(by_stage.get(stage) or {})
        except Exception:  # noqa: BLE001 — 遥测读取失败不得影响报告生成
            return {}

    @staticmethod
    def _meter_delta(before: Dict[str, Any], after: Dict[str, Any], duration_s: float,
                     tool_calls: int) -> Dict[str, Any]:
        """两次 total 快照相减，得到一段区间内的紧凑遥测条目。"""
        def _g(d: Dict[str, Any], k: str) -> float:
            try:
                return float(d.get(k, 0) or 0)
            except (TypeError, ValueError):
                return 0.0
        llm_calls = int(_g(after, "calls") - _g(before, "calls"))
        tokens = int(_g(after, "total_tokens") - _g(before, "total_tokens"))
        cost = round(_g(after, "cost_usd") - _g(before, "cost_usd"), 6)
        latency_ms = round(_g(after, "latency_ms") - _g(before, "latency_ms"), 1)
        return {
            "llm_calls": max(0, llm_calls),
            "tool_calls": max(0, int(tool_calls)),
            "tokens": max(0, tokens),
            "est_cost_usd": max(0.0, cost),
            "latency_ms": max(0.0, latency_ms),
            "duration_s": round(max(0.0, duration_s), 2),
        }


    def _define_tools(self) -> Dict[str, Dict[str, Any]]:
        """定义可用工具"""
        tools = {
            "insight_forge": {
                "name": "insight_forge",
                "description": TOOL_DESC_INSIGHT_FORGE,
                "parameters": {
                    "query": "你想深入分析的问题或话题",
                    "report_context": "当前报告章节的上下文（可选，有助于生成更精准的子问题）",
                    "as_of": "（可选）时点视图：只检索在该日期成立的事实（YYYY-MM-DD 或年份）。"
                             "用于论证立场/关系随时间的漂移——对比种子时点 vs 模拟终局，"
                             "而非只看时间压平后的快照。"
                }
            },
            "panorama_search": {
                "name": "panorama_search",
                "description": TOOL_DESC_PANORAMA_SEARCH,
                "parameters": {
                    "query": "搜索查询，用于相关性排序",
                    "include_expired": "是否包含过期/历史内容（默认True）"
                }
            },
            "quick_search": {
                "name": "quick_search",
                "description": TOOL_DESC_QUICK_SEARCH,
                "parameters": {
                    "query": "搜索查询字符串",
                    "limit": "返回结果数量（可选，默认10）"
                }
            },
            "interview_agents": {
                "name": "interview_agents",
                "description": TOOL_DESC_INTERVIEW_AGENTS,
                "parameters": {
                    "interview_topic": "采访主题或需求描述（如：'了解学生对宿舍甲醛事件的看法'）",
                    "max_agents": "最多采访的Agent数量（可选，默认5，最大6）"
                }
            },
            # T4.2: 结构化模拟结果工具（量化论断必须有据可查）
            "simulation_outcomes": {
                "name": "simulation_outcomes",
                "description": "获取模拟的量化结果：最活跃 Agent 排名、逐轮动作量、动作类型分布、峰值轮次。任何涉及『谁最活跃/参与度/动作量/级联峰值』的量化论断都应先调用它，引用具体数字。",
                "parameters": {"top_n": "返回最活跃 Agent 的数量（可选，默认15）"}
            },
            "coalition_map": {
                "name": "coalition_map",
                "description": "派系/联盟图：把对相同对象互动（点赞/转发/评论/关注）的 Agent 聚成派系（确定性，无需猜测）。分析阵营/联盟/抱团结构时使用。",
                "parameters": {}
            },
            "opinion_shift": {
                "name": "opinion_shift",
                "description": "单个 Agent/角色的逐轮行为轨迹（动作量/类型随轮次变化），用于观察其立场或参与度的演变。",
                "parameters": {"actor_name": "要追踪的 Agent/角色名"}
            },
            # NEXTSTEPS P3-6: 图谱多跳传导/级联追踪（结构推理，互补于 1-hop 检索）
            "trace_cascade": {
                "name": "trace_cascade",
                "description": "多跳传导/级联追踪：给 source+target 列出图谱中二者间的有向路径（优先因果边 "
                               "CAUSES/ENABLES/CONSTRAINS/TRIGGERS/ACCELERATES）；只给 center 列出其多跳因果邻域。"
                               "用于『追踪级联、哪个节点一动就翻盘』的结构推理（而非 1-hop 检索）。",
                "parameters": {"source": "起点实体名（与 target 配对追路径）",
                               "target": "终点实体名",
                               "center": "（可选）中心实体名：只看其多跳传导邻域时用"}
            }
        }
        # I-1-2: faction_brief 仅在启用图谱社区检索时暴露（默认关 → 工具集与现状逐字节一致）。
        # 图谱原生派系证据（社区检测 + LLM 摘要），无社区节点时内部降级到 coalition_map。
        if Config.GRAPH_COMMUNITY_RETRIEVAL:
            tools["faction_brief"] = {
                "name": "faction_brief",
                "description": "派系简报：基于图谱社区检测(Leiden)+LLM 摘要，列出各派系的成员实体与定位。分析阵营/联盟/对立结构时优先于 coalition_map（图谱原生证据，互补于行为日志聚类）。",
                "parameters": {"query": "（可选）聚焦的主题/实体关键词"}
            }
        # T4.7: 仅情景报告（有基线模拟）暴露反事实对比工具
        if self.base_simulation_id:
            tools["scenario_diff"] = {
                "name": "scenario_diff",
                "description": "反事实对比：基线模拟 vs 当前情景模拟的结构化差异（总动作量/峰值轮次/逐轮 delta/Top-actor 活跃度 delta）。撰写『情景对比』章节时必须调用，引用具体差值。",
                "parameters": {}
            }
        return tools

    def _execute_tool(self, tool_name: str, parameters: Dict[str, Any], report_context: str = "") -> str:
        """
        执行工具调用
        
        Args:
            tool_name: 工具名称
            parameters: 工具参数
            report_context: 报告上下文（用于InsightForge）
            
        Returns:
            工具执行结果（文本格式）
        """
        logger.info(f"执行工具: {tool_name}, 参数: {parameters}")
        
        try:
            if tool_name == "insight_forge":
                query = parameters.get("query", "")
                ctx = parameters.get("report_context", "") or report_context
                # NEXTSTEPS P0-2: 时点视图（可选）。底层 insight_forge 早已支持 as_of，但此前
                # 工具 schema/分发从不暴露它 → 预测者只能看到时间压平的快照。这里把它接通。
                as_of = parameters.get("as_of") or None
                result = self.zep_tools.insight_forge(
                    graph_id=self.graph_id,
                    query=query,
                    simulation_requirement=self.simulation_requirement,
                    report_context=ctx,
                    as_of=as_of,
                )
                return result.to_text()
            
            elif tool_name == "panorama_search":
                # 广度搜索 - 获取全貌
                query = parameters.get("query", "")
                include_expired = parameters.get("include_expired", True)
                if isinstance(include_expired, str):
                    include_expired = include_expired.lower() in ['true', '1', 'yes']
                result = self.zep_tools.panorama_search(
                    graph_id=self.graph_id,
                    query=query,
                    include_expired=include_expired
                )
                return result.to_text()
            
            elif tool_name == "quick_search":
                # 简单搜索 - 快速检索
                query = parameters.get("query", "")
                limit = parameters.get("limit", 10)
                if isinstance(limit, str):
                    limit = int(limit)
                result = self.zep_tools.quick_search(
                    graph_id=self.graph_id,
                    query=query,
                    limit=limit
                )
                return result.to_text()
            
            elif tool_name == "interview_agents":
                # RPT-7: 工具已因 OASIS 环境离线被移除时短路，避免未经校验的调用方
                # （原生路径等）白烧一次注定超时的 IPC 采访。
                if "interview_agents" not in self.tools:
                    return "（interview_agents 不可用：OASIS 模拟环境未在线，请改用其它检索工具）"
                # 深度采访 - 调用真实的OASIS采访API获取模拟Agent的回答（双平台）
                interview_topic = parameters.get("interview_topic", parameters.get("query", ""))
                max_agents = parameters.get("max_agents", 5)
                if isinstance(max_agents, str):
                    max_agents = int(max_agents)
                # 每位受访者都是一次双平台 claude-cli 采访（~14-40s）。把上限收紧到 6，
                # 让单次批量采访稳稳落在 600s 的 IPC 超时预算内（曾经的 8 人会触发超时）。
                max_agents = max(1, min(max_agents, 6))
                result = self.zep_tools.interview_agents(
                    simulation_id=self.simulation_id,
                    interview_requirement=interview_topic,
                    simulation_requirement=self.simulation_requirement,
                    max_agents=max_agents,
                    graph_id=self.graph_id,  # T3.14: 把采访回答持久化为 typed 图谱事实
                )
                return result.to_text()
            
            elif tool_name == "simulation_outcomes":
                top_n = parameters.get("top_n", 15)
                if isinstance(top_n, str):
                    top_n = int(top_n) if top_n.isdigit() else 15
                return self.zep_tools.simulation_outcomes(self.simulation_id, top_n=top_n)

            elif tool_name == "coalition_map":
                return self.zep_tools.coalition_map(self.graph_id, self.simulation_id)

            elif tool_name == "faction_brief":  # EXECPLAN2 I-1-2
                return self.zep_tools.faction_brief(
                    self.graph_id, parameters.get("query", ""), self.simulation_id)

            elif tool_name == "opinion_shift":
                actor_name = parameters.get("actor_name", parameters.get("query", ""))
                return self.zep_tools.opinion_shift(self.simulation_id, actor_name)

            elif tool_name == "trace_cascade":  # NEXTSTEPS P3-6: 多跳传导/级联追踪
                return self.zep_tools.trace_cascade(
                    graph_id=self.graph_id,
                    source=parameters.get("source", ""),
                    target=parameters.get("target", ""),
                    center=parameters.get("center", ""),
                )

            elif tool_name == "scenario_diff":
                # T4.7: 反事实对比 base vs 当前情景模拟
                if not self.base_simulation_id:
                    return "（本报告非情景对比报告，无基线模拟可对比）"
                return self.zep_tools.scenario_diff(self.base_simulation_id, self.simulation_id)

            # ========== 向后兼容的旧工具（内部重定向到新工具） ==========

            elif tool_name == "search_graph":
                # 重定向到 quick_search
                logger.info("search_graph 已重定向到 quick_search")
                return self._execute_tool("quick_search", parameters, report_context)
            
            elif tool_name == "get_graph_statistics":
                result = self.zep_tools.get_graph_statistics(self.graph_id)
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_entity_summary":
                entity_name = parameters.get("entity_name", "")
                result = self.zep_tools.get_entity_summary(
                    graph_id=self.graph_id,
                    entity_name=entity_name
                )
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            elif tool_name == "get_simulation_context":
                # 重定向到 insight_forge，因为它更强大
                logger.info("get_simulation_context 已重定向到 insight_forge")
                # XRUN-5: 模型未给 query 时回退紧凑查询而非整段需求书（会被钳制到只剩引言）。
                query = parameters.get("query") or self._compact_retrieval_query()
                return self._execute_tool("insight_forge", {"query": query}, report_context)
            
            elif tool_name == "get_entities_by_type":
                entity_type = parameters.get("entity_type", "")
                nodes = self.zep_tools.get_entities_by_type(
                    graph_id=self.graph_id,
                    entity_type=entity_type
                )
                result = [n.to_dict() for n in nodes]
                return json.dumps(result, ensure_ascii=False, indent=2)
            
            else:
                # RPT-7: 提示可用工具时列出 live 工具集（此前硬编码 3 个，遗漏了
                # simulation_outcomes/coalition_map/opinion_shift/trace_cascade 等）。
                return f"未知工具: {tool_name}。请使用以下工具之一: {', '.join(sorted(self.tools.keys()))}"
                
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, 错误: {str(e)}")
            return f"工具执行失败: {str(e)}"
    
    # 向后兼容的旧工具别名（_execute_tool 内部重定向到新工具，不在 self.tools 中暴露）。
    # 单独维护，避免与动态工具集（_define_tools 按 Config 条件构建）漂移。
    _LEGACY_TOOL_ALIASES = {"search_graph", "get_graph_statistics", "get_entity_summary",
                            "get_simulation_context", "get_entities_by_type"}

    # 合法的工具名称集合（遗留符号）：保留为旧工具别名集合，避免外部引用 NameError。
    # 实际校验改用 self._valid_tool_names()，从 live 工具集动态派生，杜绝与 self.tools 漂移。
    VALID_TOOL_NAMES = _LEGACY_TOOL_ALIASES

    def _valid_tool_names(self) -> set:
        """从当前实例的 live 工具集动态派生合法工具名，叠加向后兼容的旧工具别名。

        self.tools 由 _define_tools 按 Config 条件构建（如 faction_brief 仅在
        GRAPH_COMMUNITY_RETRIEVAL 时存在，scenario_diff 仅在情景报告时存在），
        因此校验必须以 live 工具集为准，而非静态名单——否则条件工具会在裸 JSON 兜底
        解析时被误丢。默认（条件工具关）时该集合与历史静态名单逐字节等价。
        """
        return set(self.tools.keys()) | self._LEGACY_TOOL_ALIASES

    def _parse_tool_calls(self, response: str) -> List[Dict[str, Any]]:
        """
        从LLM响应中解析工具调用

        支持的格式（按优先级）：
        1. <tool_call>{"name": "tool_name", "parameters": {...}}</tool_call>
        2. 裸 JSON（响应整体或单行就是一个工具调用 JSON）
        """
        tool_calls = []

        # 格式1: XML风格（标准格式）
        xml_pattern = r'<tool_call>\s*(\{.*?\})\s*</tool_call>'
        for match in re.finditer(xml_pattern, response, re.DOTALL):
            try:
                call_data = json.loads(match.group(1))
                if not isinstance(call_data, dict):
                    continue
                # RPT-7: 统一键名（tool→name / params→parameters），但不在解析层丢弃未知
                # 工具名——由 ReACT 循环给出纠正性 Observation（且不计入工具调用预算）。
                if "tool" in call_data and "name" not in call_data:
                    call_data["name"] = call_data.pop("tool")
                if "params" in call_data and "parameters" not in call_data:
                    call_data["parameters"] = call_data.pop("params")
                if not call_data.get("name"):
                    continue
                tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        if tool_calls:
            return tool_calls

        # 格式2: 兜底 - LLM 直接输出裸 JSON（没包 <tool_call> 标签）
        # 只在格式1未匹配时尝试，避免误匹配正文中的 JSON
        stripped = response.strip()
        if stripped.startswith('{') and stripped.endswith('}'):
            try:
                call_data = json.loads(stripped)
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
                    return tool_calls
            except json.JSONDecodeError:
                pass

        # 响应可能包含思考文字 + 裸 JSON，尝试提取最后一个 JSON 对象
        json_pattern = r'(\{"(?:name|tool)"\s*:.*?\})\s*$'
        match = re.search(json_pattern, stripped, re.DOTALL)
        if match:
            try:
                call_data = json.loads(match.group(1))
                if self._is_valid_tool_call(call_data):
                    tool_calls.append(call_data)
            except json.JSONDecodeError:
                pass

        return tool_calls

    def _is_valid_tool_call(self, data: dict) -> bool:
        """校验解析出的 JSON 是否是合法的工具调用"""
        # 支持 {"name": ..., "parameters": ...} 和 {"tool": ..., "params": ...} 两种键名
        tool_name = data.get("name") or data.get("tool")
        if tool_name and tool_name in self._valid_tool_names():
            # 统一键名为 name / parameters
            if "tool" in data:
                data["name"] = data.pop("tool")
            if "params" in data and "parameters" not in data:
                data["parameters"] = data.pop("params")
            return True
        return False
    
    def _get_tools_description(self) -> str:
        """生成工具描述文本"""
        desc_parts = ["可用工具："]
        for name, tool in self.tools.items():
            params_desc = ", ".join([f"{k}: {v}" for k, v in tool["parameters"].items()])
            desc_parts.append(f"- {name}: {tool['description']}")
            if params_desc:
                desc_parts.append(f"  参数: {params_desc}")
        return "\n".join(desc_parts)

    # RPT-7: 工具使用建议改为按 live 工具集动态渲染——interview_agents 被移除（OASIS 离线）
    # 后不得继续在每章提示词中宣传它（否则模型被 nudge 去调不存在的工具，白烧一轮预算）。
    # 前四条文案与历史静态块逐字一致；条件工具（faction_brief/scenario_diff 等）仅在存在时列出。
    _TOOL_HINT_SUMMARIES = {
        "insight_forge": "深度洞察分析，自动分解问题并多维度检索事实和关系",
        "panorama_search": "广角全景搜索，了解事件全貌、时间线和演变过程",
        "quick_search": "快速验证某个具体信息点",
        "interview_agents": "内部专家视角素材：情景推演小组各角色的第一人称观点（须转写为分析视角后使用，禁止呈现为真实采访）",
        "simulation_outcomes": "推演量化信号（内部方法学材料，须转写为现实世界结论后使用，正文不得引用动作/轮次数字）",
        "coalition_map": "派系/联盟结构（对相同对象互动的 Agent 聚类，确定性）",
        "opinion_shift": "单个 Agent 的逐轮行为轨迹（立场/参与度演变）",
        "trace_cascade": "图谱多跳传导/级联追踪（哪个节点一动就翻盘）",
        "faction_brief": "图谱社区检测派系简报（阵营/对立结构）",
        "scenario_diff": "基线 vs 情景反事实结构化对比",
    }

    def _tool_usage_hints(self) -> str:
        """RPT-7: 从 live self.tools 渲染工具使用建议 bullets（工具被移除即不再出现）。"""
        lines = [f"- {name}: {self._TOOL_HINT_SUMMARIES[name]}"
                 for name in self.tools if name in self._TOOL_HINT_SUMMARIES]
        return "\n".join(lines) if lines else "（按上方工具描述使用）"

    def _lint_outline_titles(self, sections: List["ReportSection"]) -> int:
        """WAVE9：把含方法学词汇的大纲章节标题**就地改名**为客户可读的安全标题。

        改名而非删除——保住 6-14 节的章节数契约；同批多个泄漏标题循环取安全标题并
        加序号去重。返回改名数。"""
        zh = not str(getattr(self, "output_language", "") or "English").lower().startswith("en")
        safe_titles = self._SAFE_TITLES_ZH if zh else self._SAFE_TITLES_EN
        existing = {s.title for s in sections}
        renamed = 0
        for s in sections:
            title = s.title or ""
            if not self._LEAK_TITLE_RE.search(title):
                continue
            new_title = safe_titles[renamed % len(safe_titles)]
            if new_title in existing:
                new_title = (f"{new_title}（{renamed + 1}）" if zh
                             else f"{new_title} ({renamed + 1})")
            logger.info(f"大纲标题改名：「{title}」→「{new_title}」")
            existing.discard(s.title)
            s.title = new_title
            existing.add(new_title)
            renamed += 1
        return renamed

    def plan_outline(
        self,
        progress_callback: Optional[Callable] = None,
        forecast_spine_block: str = "",
        require_forecast_structure: bool = False,
    ) -> ReportOutline:
        """
        规划报告大纲

        使用LLM分析模拟需求，规划报告的目录结构

        Args:
            progress_callback: 进度回调函数
            forecast_spine_block: R2-DETAIL-2 预测骨架块（先于大纲推导）。非空时钉入大纲提示词，
                让章节围绕可证伪的预测组织而非反向从叙事抽取。缺省空串 → 行为与历史一致。
            require_forecast_structure: R2-DETAIL-2/LOOP-015 为真时追加 FORECAST_STRUCTURE_MANDATE，
                强制大纲覆盖「逐情景预测」+ 一节紧凑的「预测总表与校准」（合并旧的两节纯方法学
                章节）。缺省 False → 不追加该指令，提示词与历史逐字节一致。

        Returns:
            ReportOutline: 报告大纲
        """
        logger.info("开始规划报告大纲...")
        
        if progress_callback:
            progress_callback("planning", 0, "正在分析模拟需求...")
        
        # 首先获取模拟上下文（XRUN-5: 检索用紧凑查询，需求书仍原样传给上下文回显；
        # 紧凑查询与需求书相同时不传该参数，调用形态与历史逐字节一致）
        _ctx_kwargs: Dict[str, Any] = {
            "graph_id": self.graph_id,
            "simulation_requirement": self.simulation_requirement,
        }
        _sq = self._compact_retrieval_query()
        if _sq and _sq != self.simulation_requirement:
            _ctx_kwargs["search_query"] = _sq
        context = self.zep_tools.get_simulation_context(**_ctx_kwargs)
        
        if progress_callback:
            progress_callback("planning", 30, "正在生成报告大纲...")
        
        system_prompt = self._lang_override() + PLAN_SYSTEM_PROMPT
        user_prompt = PLAN_USER_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            total_nodes=context.get('graph_statistics', {}).get('total_nodes', 0),
            total_edges=context.get('graph_statistics', {}).get('total_edges', 0),
            entity_types=list(context.get('graph_statistics', {}).get('entity_types', {}).keys()),
            total_entities=context.get('total_entities', 0),
            # T4.3: 事实切片 10→25，给规划更充足的实证依据。
            related_facts_json=json.dumps(context.get('related_facts', [])[:25], ensure_ascii=False, indent=2),
        )
        # T4.1: 钉入研究背景档案 + 来源索引，让大纲规划基于真实 cast/关系，而非纯凭模拟统计盲设。
        user_prompt = self._prepend_research_background(user_prompt)

        # T4.3: 规划前先做两次扫描——一次图谱深挖（central_question）+ 一次结构化模拟结果，
        # 让大纲随真实研究发现与模拟动态而变（如高级联的运行会催生「级联」章节），而非盲设。
        sweeps = []
        try:
            # XRUN-5: 全局扫描的 query 用紧凑查询（整段需求书会被钳制到只剩引言句）。
            forge = self.zep_tools.insight_forge(
                graph_id=self.graph_id,
                query=self._compact_retrieval_query(),
                simulation_requirement=self.simulation_requirement,
                report_context="报告大纲规划阶段的全局扫描",
            )
            forge_text = forge.to_text() if hasattr(forge, "to_text") else str(forge)
            if forge_text:
                sweeps.append("【图谱深挖摘要】\n" + forge_text[:6000])  # RQ-4: 3000→6000
        except Exception as e:
            logger.warning(f"plan_outline insight_forge 扫描失败（忽略）: {e}")
        try:
            outcomes = self.zep_tools.simulation_outcomes(self.simulation_id, top_n=10)
            if outcomes:
                # WAVE9：包成内部方法学材料——它只用于判断哪些行为者/议题值得设章深挖，
                # 绝不能催生「Agent 行为分析」型章节（940-actor 章节即此前的泄漏产物）。
                sweeps.append(
                    "【内部方法学材料——情景推演量化产出（仅供规划参考）】\n"
                    "使用规则：仅据此判断哪些现实世界行为者/议题值得设立章节深挖；"
                    "不得为推演本身单设章节，任何章节标题不得含"
                    "『模拟/Agent/智能体/行为轨迹/Simulation/Behavior』等方法学词汇。\n"
                    + outcomes[:5000])  # RQ-4: 2500→5000
        except Exception as e:
            logger.warning(f"plan_outline simulation_outcomes 扫描失败（忽略）: {e}")
        if sweeps:
            user_prompt = user_prompt + "\n\n" + "\n\n".join(sweeps)

        # T4.7: 情景对比报告 —— 强制大纲包含「情景对比 / 反事实」章节，并预取 scenario_diff 摘要
        if self.base_simulation_id:
            try:
                diff_text = self.zep_tools.scenario_diff(self.base_simulation_id, self.simulation_id)
                if diff_text:
                    user_prompt += "\n\n【基线 vs 情景 结构化对比（必须据此撰写对比章节）】\n" + diff_text[:2500]
            except Exception as e:
                logger.warning(f"plan_outline scenario_diff 扫描失败（忽略）: {e}")
            user_prompt += (
                "\n\n**强制要求**：本报告为情景（What-If）预测，大纲必须包含一节标题含"
                "「情景对比」或「反事实」的章节，对比基线与本情景的关键差异（引用上面对比数据中的具体差值）。"
            )

        # R2-DETAIL-2: 把先于大纲推导出的预测骨架钉入提示词，并（在有骨架时）强制大纲围绕预测组织。
        # forecast_spine_block 为空 / require_forecast_structure 为 False 时本段为 no-op（提示词与历史一致）。
        if forecast_spine_block:
            user_prompt += "\n\n" + forecast_spine_block
        if require_forecast_structure:
            user_prompt += FORECAST_STRUCTURE_MANDATE

        try:
            response = self.llm.chat_json(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.3
            )
            
            if progress_callback:
                progress_callback("planning", 80, "正在解析大纲结构...")
            
            # 解析大纲
            sections = []
            for section_data in response.get("sections", []):
                sections.append(ReportSection(
                    title=section_data.get("title", ""),
                    content="",
                    description=section_data.get("description", "")
                ))

            # WAVE9：大纲标题 lint——含方法学词汇（模拟/智能体/Agent/Simulation/Behavior/
            # 行为轨迹）的标题确定性改名（改名而非删除，保住 6-14 节章节数契约）。
            if getattr(Config, "REPORT_OUTLINE_TITLE_LINT", True):
                try:
                    _renamed = self._lint_outline_titles(sections)
                    if _renamed:
                        logger.warning(f"大纲标题 lint：{_renamed} 个章节标题含方法学词汇，已改名")
                except Exception as _tle:  # noqa: BLE001 — lint 失败保留原标题
                    logger.warning(f"大纲标题 lint 失败（忽略）: {_tle}")

            # RQ-1(4)/LOOP-015: 章节数钳制。上限仍取形状 max_sections（超出截断）；下限改为
            # 「连贯性优先」——规划器产出 >=4 节连贯大纲即接受，不再用通用兜底标题硬凑到形状
            # min_sections（每个凑数章节此前都要烧满一轮 4-12 次工具调用的检索循环）。仅 <4 节
            # 时补齐到 4，且补齐章节打 padded 标记——章节生成路径据此把有效工具调用下限降为 0
            # （直接综合已注入材料成文，见 _effective_min_tool_calls）。
            _shape = self._report_shape()
            _max_sections = _shape["max_sections"]
            _pad_floor = min(self.OUTLINE_PAD_FLOOR_SECTIONS, _shape["min_sections"])
            if len(sections) < _pad_floor:
                _existing = {s.title for s in sections}
                for _title in self._FALLBACK_SECTION_TITLES:
                    if len(sections) >= _pad_floor:
                        break
                    if _title in _existing:
                        continue
                    sections.append(ReportSection(title=_title, padded=True))
                    _existing.add(_title)
                logger.warning(
                    f"大纲章节数不足 {_pad_floor}，已补齐至 {len(sections)} 节"
                    "（补齐章节以零检索预算综合成文）"
                )
            elif len(sections) > _max_sections:
                logger.warning(
                    f"大纲章节数 {len(sections)} 超过上限 {_max_sections}，已截断"
                )
                sections = sections[:_max_sections]

            outline = ReportOutline(
                title=response.get("title", "未来预测报告"),
                summary=response.get("summary", ""),
                sections=sections
            )
            
            if progress_callback:
                progress_callback("planning", 100, "大纲规划完成")
            
            logger.info(f"大纲规划完成: {len(sections)} 个章节")
            return outline
            
        except Exception as e:
            logger.error(f"大纲规划失败: {str(e)}")
            # RPT-2(a): 记录「大纲 LLM 调用失败、已降级为默认大纲」——这是系统性 LLM 故障的
            # 前哨信号；generate_report 据此在前两章接连失败时快速中止，而非对着死掉的
            # 提供方烧完全部章节再假装 completed。
            self._outline_degraded = True
            # 返回默认大纲（5个章节，满足 5-8 节契约的下限，作为 fallback）
            return ReportOutline(
                title="未来预测报告",
                summary="基于研究证据、情景推理与外部校准的未来趋势与风险预测",
                sections=[
                    ReportSection(title=_title) for _title in self._FALLBACK_SECTION_TITLES
                ]
            )
    
    # ---- EXECPLAN2 I-6-3: concurrent section generation helpers ----
    _TAIL_SECTION_RE = re.compile(
        r"(总结|结论|结语|执行摘要|概要|summary|conclusion|executive)", re.I
    )

    @classmethod
    def _is_tail_section(cls, title: str) -> bool:
        """True for summary/conclusion-style sections that depend on the body and
        must be generated LAST (sequentially, with full body text). Pure."""
        return bool(cls._TAIL_SECTION_RE.search(title or ""))

    @staticmethod
    def _build_synthesis_brief(sections: List[ReportSection]) -> str:
        """Compact 'synthesis brief' (outline + per-section 1-liner) used as shared
        cross-section context when sections are generated concurrently or in brief
        context mode — replaces the O(N²) 'full text of every prior section'. Pure."""
        lines = ["【报告大纲与各章节意图（用于保持全局一致性）】"]
        for i, s in enumerate(sections, 1):
            desc = (getattr(s, "description", "") or "").strip()
            lines.append(f"{i}. {s.title}" + (f"：{desc}" if desc else ""))
        return "\n".join(lines)

    def _generate_sections_concurrent(self, outline: "ReportOutline", concurrency: int) -> Dict[int, str]:
        """Pre-generate all section contents with bounded concurrency, returning
        {section_index: content}. Body sections (independent) run in a thread pool
        with the shared synthesis brief as context; summary/conclusion sections run
        last, sequentially, with the full body text for coherence. Per-section
        failures degrade to the placeholder (never abort the report). Caller's serial
        bookkeeping loop then consumes the returned contents in order.
        """
        import concurrent.futures as _cf

        sections = outline.sections
        body = [(i, s) for i, s in enumerate(sections) if not self._is_tail_section(s.title)]
        tail = [(i, s) for i, s in enumerate(sections) if self._is_tail_section(s.title)]
        if not body:  # everything looked like a summary → treat all as body (keep parallelism)
            body, tail = tail, []
        brief = self._build_synthesis_brief(sections)
        contents: Dict[int, str] = {}

        def _noop(*_a, **_k):
            return None

        def _gen_body(idx: int, section: ReportSection):
            try:
                return idx, self._generate_section_with_retry(
                    section=section, outline=outline, previous_sections=[brief],
                    progress_callback=_noop, section_index=idx + 1)
            except Exception as e:  # noqa: BLE001 — per-section isolation
                logger.error(f"并发章节生成异常（降级占位符）: {section.title} -> {e}")
                return idx, SECTION_FAILURE_PLACEHOLDER

        if body:
            # RPT-9: ThreadPoolExecutor worker 线程不继承 ContextVar，_current_report_id
            # 在 worker 中为 None → _ReportIdMatchFilter 丢弃全部章节内日志（console_log.txt
            # 与 UI 日志流在并发模式下整段空白）。为每个任务复制当前上下文再运行。
            _parent_ctx = contextvars.copy_context()
            with _cf.ThreadPoolExecutor(max_workers=min(concurrency, len(body))) as ex:
                futures = [ex.submit(_parent_ctx.copy().run, _gen_body, i, s) for i, s in body]
                for fut in _cf.as_completed(futures):
                    idx, content = fut.result()
                    contents[idx] = content

        # tail sections: sequential, full body text as context for narrative closure
        body_text = [f"## {sections[i].title}\n\n{contents.get(i, '')}" for i, _ in body]
        for idx, section in tail:
            try:
                contents[idx] = self._generate_section_with_retry(
                    section=section, outline=outline, previous_sections=body_text,
                    progress_callback=_noop, section_index=idx + 1)
            except Exception as e:  # noqa: BLE001
                logger.error(f"尾部章节生成异常（降级占位符）: {section.title} -> {e}")
                contents[idx] = SECTION_FAILURE_PLACEHOLDER
            body_text.append(f"## {section.title}\n\n{contents[idx]}")
        return contents

    def _generate_section(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0,
    ) -> str:
        """T4.5: 章节生成调度——原生 tool calling 可用时走结构化路径，否则回退手搓 ReAct。"""
        if self.llm.supports_native_tools():
            try:
                return self._generate_section_native(
                    section, outline, previous_sections, progress_callback, section_index
                )
            except Exception as e:  # noqa: BLE001 — 原生路径异常时优雅回退 ReAct，绝不让章节失败
                logger.warning(f"原生 tool calling 章节生成失败，回退 ReAct: {e}")
        return self._generate_section_react(
            section, outline, previous_sections, progress_callback, section_index
        )

    def _generate_section_with_retry(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0,
    ) -> str:
        """RPT-2: 章节异常先退避重试，再落占位符。瞬时故障（限流/超时/单次 5xx）不应
        直接把章节钉死成占位符。REPORT_SECTION_RETRY_MAX=0 时与直接调用逐字节等价。"""
        try:
            retries = int(getattr(Config, "REPORT_SECTION_RETRY_MAX", 1) or 0)
        except (TypeError, ValueError):
            retries = 1
        try:
            backoff = float(getattr(Config, "REPORT_SECTION_RETRY_BACKOFF_S", 8.0) or 0.0)
        except (TypeError, ValueError):
            backoff = 8.0
        attempt = 0
        while True:
            try:
                content = self._generate_section(
                    section, outline, previous_sections, progress_callback, section_index
                )
                break
            except Exception as e:  # noqa: BLE001 — 重试耗尽后重抛，由调用方落占位符
                if attempt >= retries:
                    raise
                attempt += 1
                wait_s = min(backoff * attempt, 60.0)
                logger.warning(
                    f"章节 {section.title} 生成异常，{wait_s:.0f}s 后重试 "
                    f"{attempt}/{retries}: {e}"
                )
                time.sleep(wait_s)
        # WAVE9：章节语言验收（一次重写重申 _lang_override）——先于反思，让反思与
        # 后续修复都在目标语言的稿件上进行。degrade-safe：任何失败返回原草稿。
        try:
            content = self._enforce_section_language(section, content)
        except Exception as _lang_e:  # noqa: BLE001 — 语言验收为旁路增强
            logger.debug(f"章节语言验收跳过（忽略）: {_lang_e}")
        # RQ-5：草稿通过基本有效性后，做一次廉价批判 + 至多一次修订（全程 degrade-safe，
        # 失败/关闭一律返回原草稿）。留在本方法内 ⇒ 仍处于 telemetry/并发包装之内。
        return self._reflect_and_maybe_revise_section(
            section, outline, content, previous_sections, section_index
        )

    def _reflect_and_maybe_revise_section(
        self,
        section: "ReportSection",
        outline: "ReportOutline",
        content: str,
        previous_sections: List[str],
        section_index: int = 0,
    ) -> str:
        """RQ-5：对通过基本有效性的章节草稿做一次廉价批判；未通过则至多一次修订。

        评分维度：(1) 骨架情景概率一致性；(2) 硬数字接地（带 [S#] 或与信号包一致）；
        (3) 篇幅下限；(4) 不复述前序章节。批判返回 PASS 或单条修订指令；至多一次修订抽取。
        由 self.MAX_REFLECTION_ROUNDS 上限（<=0 关闭），并受 Config.REPORT_SECTION_REFLECTION
        总开关约束。全部包在 try 里——反思是旁路增强，任何异常/缺依赖都回退原草稿。"""
        try:
            if not getattr(Config, "REPORT_SECTION_REFLECTION", True):
                return content
            cap = int(getattr(self, "MAX_REFLECTION_ROUNDS", 0) or 0)
            if cap <= 0:                                  # MAX_REFLECTION_ROUNDS 上限（0=关）
                return content
            llm = getattr(self, "llm", None)
            if llm is None or not hasattr(llm, "chat"):   # 离线/桩 agent 无 LLM → 跳过
                return content
            # 仅对通过基本有效性的草稿反思——污染/过短草稿交由既有重试/占位符逻辑处理。
            if _looks_contaminated(content):
                return content
            result = content
            instruction = self._critique_section_draft(section, content, previous_sections)
            if instruction:
                revised = self._revise_section_draft(section, outline, content, instruction)
                if revised and not _looks_contaminated(revised):
                    # WAVE9：反收缩护栏——修订稿短于 max(60% 原稿, 章节字符下限) 且确实
                    # 缩水时拒绝采纳（14824→1518 的「章节销毁」型故障即此路径漏防）。
                    _min_len = max(
                        int(len(content) * self._revision_min_ratio()),
                        self._section_char_floor(),
                    )
                    if len(revised) < _min_len and len(revised) < len(content):
                        logger.warning(
                            f"章节 {section.title}: 反思修订被拒绝——修订稿 {len(revised)} 字符 "
                            f"< 下限 {_min_len}（原稿 {len(content)}），保留原稿"
                        )
                    else:
                        logger.info(
                            f"章节 {section.title}: 反思修订已采纳（{len(content)}→{len(revised)} 字符）"
                            f" ｜指令: {instruction[:80]}"
                        )
                        result = revised
            # WAVE9：截断检测——采纳稿以句中截断收尾（'(依据' / 裸字母数字 / 冒号）时
            # 做一次续写调用补全，绝不交付半句话章节。
            if (getattr(Config, "REPORT_SECTION_TRUNCATION_CONTINUE", True)
                    and _looks_truncated(result)):
                # 孤悬的「（依据/(According to」引子先剪掉（续写无法接续半个括注）。
                _base = _TRUNCATED_TAIL_RE.sub("", result.rstrip()).rstrip()
                cont = self._continue_section_draft(section, _base)
                if cont:
                    logger.info(
                        f"章节 {section.title}: 检测到句中截断，已续写补全（+{len(cont)} 字符）"
                    )
                    _joiner = " " if (_base and _base[-1].isalnum()) else "\n\n"
                    result = _base + _joiner + cont
            return result
        except Exception as _re:  # noqa: BLE001 — 反思为旁路增强，失败绝不影响章节产出
            logger.debug(f"章节反思跳过（忽略）: {_re}")
            return content

    def _reflection_spine_probs(self) -> str:
        """把预测骨架情景概率压成一行紧凑串（供反思批判对齐）；无骨架时回退骨架块文本。"""
        fc = getattr(self, "_forecast_spine", None)
        if isinstance(fc, dict) and fc.get("scenarios"):
            rows: List[str] = []
            for s in fc["scenarios"]:
                if not isinstance(s, dict):
                    continue
                try:
                    p = round(float(s.get("probability") or 0.0) * 100)
                except (TypeError, ValueError):
                    continue
                nm = str(s.get("name") or "").strip()[:40]
                if nm:
                    rows.append(f"{nm}: {p}%")
            if rows:
                return "；".join(rows[:8])
        return (getattr(self, "_forecast_spine_block", "") or "")[:800]

    def _critique_section_draft(
        self, section: "ReportSection", content: str, previous_sections: List[str]
    ) -> Optional[str]:
        """RQ-5：一次廉价批判调用。返回 None 表示 PASS，否则返回单条修订指令。"""
        spine_txt = self._reflection_spine_probs()
        signal_txt = (getattr(self, "_signal_pack", "") or "")[:1500]
        # i7 P0 尾巴：市场表此前只注入章节撰写提示、不给质检员——正文引用的真实市场价
        # 因无 [S#] 被规则 2 判为未接地，修订指令随即把真价当 fabrication 改写/删除
        # （Tesla Optimus P=0.125 事故的报告侧机制之一）。质检材料必须与撰写材料同源。
        market_txt = (getattr(self, "_market_pack", "") or "")[:1200]
        prior = "\n\n".join((s or "")[:600] for s in (previous_sections or [])[:6])[:2400]
        floor = self._section_char_floor()  # WAVE9：800 → 章节目标的 40%（随形状伸缩）
        lang = getattr(self, "output_language", None) or "English"
        sys_prompt = (
            "你是一名严格的报告章节质检员。仅依据下方给定材料，判断本章草稿是否同时满足四条标准：\n"
            "1) 概率一致性：正文若提及情景/事件概率，须与【预测骨架概率】一致，不得矛盾；\n"
            "2) 硬数字接地：关于现实世界的关键定量声明必须带来源标注 [S#]；【信号包】中的数字"
            "是内部模拟推演产物（elicited model projection），只有在正文显式标注其模拟来源时"
            "才可引用，绝不能替代 [S#] 作为现实世界声明的接地；【预测市场表】中的隐含概率/"
            "价格是机器抓取的真实市场数据（Polymarket 公开 API），正文引用且与表内数值一致时"
            "视为已接地，不要求 [S#]，绝不能当作捏造数字要求删除或改写；\n"
            f"3) 篇幅下限：正文须有不少于 {floor} 字符的实质内容；\n"
            "4) 不复述前序章节：不得大段重复【前序章节摘要】中的内容。\n"
            f"全部满足 ⇒ 只输出 PASS（不要任何多余文字）；否则 ⇒ 只输出一条最关键、可执行、"
            f"具体的修订指令（用{lang}书写，单句，不要解释）。"
        )
        usr_prompt = (
            f"【预测骨架概率】\n{spine_txt or '（无）'}\n\n"
            f"【信号包（硬数字）】\n{signal_txt or '（无）'}\n\n"
            f"【预测市场表】\n{market_txt or '（无）'}\n\n"
            f"【前序章节摘要】\n{prior or '（无）'}\n\n"
            f"【本章标题】{section.title}\n\n"
            f"【本章草稿】\n{content[:6000]}"
        )
        resp = self.llm.chat(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": usr_prompt}],
            temperature=0.0,
            max_tokens=512,
            tier="fast",
        )
        text = (resp or "").strip()
        if not text:
            return None                                   # 空响应 → 视为 PASS（不冒险改稿）
        normalized = re.sub(r"[\s`*_\"'。.，,：:！!？?-]+", "", text).upper()
        head = normalized[:8]
        if head.startswith("PASS"):
            return None
        # WAVE9：裸「FAIL」不是修订指令——把它喂给修订员会诱发整章重写/销毁
        # （console_log 实锤：'指令: FAIL' → 15031→1538 字符）。视为无指令，跳过修订。
        if normalized in ("FAIL", "FAILED", "不通过", "未通过"):
            logger.warning(f"章节 {section.title}: 质检只回了「{text[:20]}」（无具体指令），跳过修订")
            return None
        return text[:600]

    def _revise_section_draft(
        self, section: "ReportSection", outline: "ReportOutline",
        content: str, instruction: str
    ) -> str:
        """RQ-5：按修订指令改写章节草稿（至多一次抽取）。只修被指出的问题，保留其余内容。"""
        sys_prompt = self._lang_override() + (
            "你是报告章节修订员。依据给定的『修订指令』改写本章草稿：只修复被指出的问题，"
            "保留其余正确内容、数据与结构，不得引入未在材料中出现的新数字或新引用。"
            "直接输出改写后的完整 Markdown 正文，不要输出解释、前后缀或指令本身。"
        )
        usr_prompt = (
            f"【修订指令】{instruction}\n\n"
            f"【本章标题】{section.title}\n\n"
            f"【待修订草稿】\n{content}"
        )
        revised = self.llm.chat(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": usr_prompt}],
            temperature=Config.REPORT_AGENT_TEMPERATURE,
            max_tokens=Config.REPORT_AGENT_SECTION_MAX_TOKENS,
        )
        return (revised or "").strip()

    def _section_char_floor(self) -> int:
        """WAVE9：反思护栏使用的章节字符下限 = max(MIN_VALID_SECTION_CHARS, 章节目标下限 ×
        REPORT_SECTION_MIN_VALID_RATIO)。此前固定 800，远低于 3000-6000 的章节目标，
        1.5KB 的销毁性修订稿能溜过长度门。任何失败回退 MIN_VALID_SECTION_CHARS。"""
        try:
            ratio = float(getattr(Config, "REPORT_SECTION_MIN_VALID_RATIO", 0.4) or 0.4)
            shape = self._report_shape()
            return max(MIN_VALID_SECTION_CHARS, int(shape["target_lo"] * ratio))
        except Exception:  # noqa: BLE001 — 形状派生失败回退旧下限
            return MIN_VALID_SECTION_CHARS

    def _revision_min_ratio(self) -> float:
        """WAVE9：修订稿允许的最小长度比例（相对原稿）。默认 0.6。"""
        try:
            return float(getattr(Config, "REPORT_REVISION_MIN_RATIO", 0.6) or 0.6)
        except (TypeError, ValueError):
            return 0.6

    def _continue_section_draft(self, section: "ReportSection", content: str) -> str:
        """WAVE9：对句中截断的章节做**一次**续写调用，返回续写文本（失败/无效返回 ""）。

        续写只补完剩余内容（先接完被打断的句子），不复述已有正文；输出再判污染。"""
        lang = getattr(self, "output_language", None) or "English"
        sys_prompt = self._lang_override() + (
            "你是报告章节的续写员。下面的章节正文在句中被截断了。请从截断处**无缝续写**："
            "先把被打断的句子写完，再自然收束本章剩余论证（可含 1-2 段）。"
            "只输出续写部分（不要复述已有正文、不要输出任何解释或标题），"
            f"用{lang}书写，保持原文的风格与证据纪律。"
        )
        tail = (content or "")[-3000:]
        try:
            out = self.llm.chat(
                messages=[{"role": "system", "content": sys_prompt},
                          {"role": "user", "content": f"【已截断的章节结尾】\n…{tail}"}],
                temperature=Config.REPORT_AGENT_TEMPERATURE,
                max_tokens=4096,
            )
        except Exception as _ce:  # noqa: BLE001 — 续写失败保留原稿（截断但不销毁）
            logger.warning(f"章节续写调用失败（保留截断稿）: {_ce}")
            return ""
        out = (out or "").strip()
        if not out or any(m in out for m in CONTAMINATION_MARKERS):
            return ""
        return out

    # WAVE9：章节语言验收的 CJK/拉丁字符统计（跳过围栏与 URL）。
    @staticmethod
    def _lang_char_stats(text: str) -> Tuple[int, int]:
        """返回 (CJK 字符数, 拉丁字母数)；围栏代码块内不计。纯函数。"""
        cjk = 0
        latin = 0
        in_fence = False
        for ln in (text or "").splitlines():
            s = ln.strip()
            if s.startswith("```") or s.startswith("~~~"):
                in_fence = not in_fence
                continue
            if in_fence or "http://" in s or "https://" in s:
                continue
            for ch in ln:
                if "一" <= ch <= "鿿":
                    cjk += 1
                elif "a" <= ch.lower() <= "z":
                    latin += 1
        return cjk, latin

    def _enforce_section_language(self, section: "ReportSection", content: str) -> str:
        """WAVE9：章节语言验收——成稿语言与 output_language 不符时做**一次**重写重申
        _lang_override（S3/S9 整章英文报告里写中文的故障；事后 purity 补丁只会产出
        'SK SK Hynix' 型混合垃圾）。重写无效/仍不达标 → 保留原稿（degrade-safe）。"""
        try:
            if not getattr(Config, "REPORT_SECTION_LANG_ENFORCE", True):
                return content
            llm = getattr(self, "llm", None)
            if llm is None or not hasattr(llm, "chat"):
                return content
            if _looks_contaminated(content):
                return content
            lang = getattr(self, "output_language", None) or "English"
            target_is_cjk = not str(lang).strip().lower().startswith("en")

            def _foreign_ratio(text: str) -> float:
                cjk, latin = self._lang_char_stats(text)
                total = cjk + latin
                if total < 200:            # 太短没有区分力
                    return 0.0
                return (latin / total) if target_is_cjk else (cjk / total)

            try:
                thresh = float(getattr(Config, "REPORT_SECTION_LANG_MAX_FOREIGN_RATIO",
                                       0.25) or 0.25)
            except (TypeError, ValueError):
                thresh = 0.25
            if target_is_cjk:
                # 中文报告合法保留大量拉丁 token（公司名/型号/[S#]），阈值放宽。
                thresh = max(thresh, 0.6)
            ratio = _foreign_ratio(content)
            if ratio <= thresh:
                return content
            logger.warning(
                f"章节 {section.title}: 语言验收失败（外语字符占比 {ratio:.0%} > {thresh:.0%}，"
                f"目标 {lang}），触发一次整章重写"
            )
            sys_prompt = self._lang_override() + (
                f"下面的章节正文混入了大量非目标语言内容。请把全文完整改写为{lang}："
                "保留全部论点、结构（### 小标题/列表/表格/引用块）、数字、百分比与 [S#] 引用标记"
                "逐字节不变；专有名词保持原样。只输出改写后的完整 Markdown 正文，"
                "不要任何解释或前后缀。"
            )
            try:
                rewritten = self.llm.chat(
                    messages=[{"role": "system", "content": sys_prompt},
                              {"role": "user", "content": content}],
                    temperature=0.1,
                    max_tokens=Config.REPORT_AGENT_SECTION_MAX_TOKENS,
                )
            except Exception as _le:  # noqa: BLE001 — 重写失败保留原稿
                logger.warning(f"章节语言重写调用失败（保留原稿）: {_le}")
                return content
            rewritten = (rewritten or "").strip()
            if (rewritten and not _looks_contaminated(rewritten)
                    and _foreign_ratio(rewritten) <= thresh
                    and len(rewritten) >= int(len(content) * 0.5)):
                logger.info(f"章节 {section.title}: 语言重写已采纳（{len(content)}→{len(rewritten)} 字符）")
                return rewritten
            logger.warning(f"章节 {section.title}: 语言重写无效（仍不达标/过短），保留原稿")
            return content
        except Exception as _lee:  # noqa: BLE001 — 语言验收为旁路增强
            logger.debug(f"章节语言验收跳过（忽略）: {_lee}")
            return content

    def _to_openai_tool_schemas(self) -> List[Dict[str, Any]]:
        """T4.5: 把内部 tools 定义转成 OpenAI function tool schema。

        直接遍历 live 工具集 self.tools（_define_tools 按 Config 条件构建），使
        faction_brief / scenario_diff 等条件工具在被定义时即原生暴露，杜绝「prompt 中
        宣告但 tools= schema 缺失」的漂移。旧工具别名是 _execute_tool 的内部重定向，
        本就不应原生暴露，故不纳入。默认（条件工具关）时输出与历史静态名单逐字节一致。
        """
        schemas = []
        for tname in sorted(self.tools.keys()):
            spec = self.tools.get(tname)
            if not spec:
                continue
            props = {}
            for pname, pdesc in (spec.get("parameters") or {}).items():
                props[pname] = {"type": "string", "description": str(pdesc)}
            schemas.append({
                "type": "function",
                "function": {
                    "name": tname,
                    "description": spec.get("description", tname),
                    "parameters": {"type": "object", "properties": props},
                },
            })
        return schemas

    def _generate_section_native(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0,
    ) -> str:
        """T4.5: 用原生 tool calling 生成章节（无正则解析/无 conflict_retries/无污染检测）。"""
        logger.info(f"原生 tool calling 生成章节: {section.title}")
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)

        _section_heading = section.title
        if section.description:
            _section_heading = f"{section.title}\n本章内容定位（大纲规划）: {section.description}"
        # LOOP-015: 与 ReAct 路径同源的有效工具调用下限（padding=0 / 证据预注入=1 / 其余=配置值）。
        _eff_min = self._effective_min_tool_calls(section)
        _prompt_kwargs = self._section_prompt_kwargs()  # RQ-1: 篇幅+工具调用范围槽位（随形状伸缩）
        _prompt_kwargs["min_tool_calls"] = _eff_min
        system_prompt = self._lang_override() + SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=_section_heading,
            tools_description=self._get_tools_description(),
            tool_usage_hints=self._tool_usage_hints(),  # RPT-7: live 工具集
            **_prompt_kwargs,
        )
        system_prompt = self._prepend_research_background(system_prompt,
                                                          section_title=section.title)
        # 原生路径：覆盖 ReAct 的格式要求，改为「自然调用工具，最后直接输出 Markdown 正文」
        system_prompt += (
            "\n\n【输出模式】你已具备原生工具调用能力：需要数据时直接发起工具调用（可多次），"
            "信息充分后直接输出本章 Markdown 正文（不要输出 Thought/Action/Final Answer 等标记，"
            "不要输出 JSON 工具包裹）。撰写正文前至少调用 "
            f"{_eff_min} 次工具以获取实证。"
        )

        if previous_sections:
            # RQ-7: 前序章节切片从固定 [:8000] 升级为按提供方窗口预算化（大窗口携带全量前文，
            # 小窗口守住 8000 floor）。ADAPTIVE_CONTEXT 关闭时 _cap 恒为 8000（行为不变）。
            _cap = self._prior_section_char_budget(8000, len(previous_sections))
            previous_content = "\n\n---\n\n".join(
                (sec[:_cap] + "..." if len(sec) > _cap else sec) for sec in previous_sections
            )
        else:
            previous_content = "（这是第一个章节）"
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content, section_title=section.title,
            **_prompt_kwargs,  # RQ-1: 篇幅+工具调用范围槽位（min_tool_calls 已按 LOOP-015 生效值覆盖）
        )

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        schemas = self._to_openai_tool_schemas()
        max_iterations = 14  # RQ-1: 10→14，支撑更多工具轮次 + 更长章节的收尾
        max_tool_calls = self.MAX_TOOL_CALLS_PER_SECTION
        tool_calls_count = 0

        for _ in range(max_iterations):
            # REPORT-9: 工具调用未达下限时，本回合的正文会被拒绝（强制继续检索）→ 必为「工具决策回合」，
            # 用较小的 REPORT_AGENT_TOOL_TURN_MAX_TOKENS 抑制长链推理；达到下限后本回合可能直接产出正文，
            # 回到完整 SECTION_MAX_TOKENS 预算以免截断。（原生路径此前用 chat_with_tools 的 4096 默认值。）
            _turn_max_tokens = (
                Config.REPORT_AGENT_SECTION_MAX_TOKENS
                if tool_calls_count >= _eff_min
                else getattr(Config, "REPORT_AGENT_TOOL_TURN_MAX_TOKENS", 8192)
            )
            resp = self.llm.chat_with_tools(
                messages, schemas, temperature=Config.REPORT_AGENT_TEMPERATURE,
                max_tokens=_turn_max_tokens
            )
            calls = resp.get("tool_calls") or []
            content = resp.get("content") or ""

            if calls and tool_calls_count < max_tool_calls:
                # RPT-11: 整批放行会超预算（count=7、上限 8 时 4 连发会执行到 11）。先把批次
                # 裁到剩余预算再构建 assistant 消息——assistant.tool_calls 与 role=tool 回包
                # 必须一一对应，否则下一次 create() 会因缺失 tool_call_id 回包而 400。
                _dropped = calls[max_tool_calls - tool_calls_count:]
                calls = calls[:max_tool_calls - tool_calls_count]
                if _dropped:
                    logger.info(
                        f"章节 {section.title}: 工具批次超出剩余预算，裁掉 {len(_dropped)} 个调用"
                    )
                # 回填 assistant 工具调用消息
                messages.append({
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": [
                        {"id": c["id"], "type": "function",
                         "function": {"name": c["name"], "arguments": json.dumps(c["arguments"], ensure_ascii=False)}}
                        for c in calls
                    ],
                })
                for c in calls:
                    tool_calls_count += 1
                    self._section_tool_calls += 1  # EXECPLAN2 I-5-4: per-section 工具调用计数
                    try:
                        result = self._execute_tool(c["name"], c["arguments"], report_context=section.title)
                    except Exception as te:  # noqa: BLE001
                        result = f"（工具 {c['name']} 执行失败：{te}）"
                    if self.report_logger:
                        try:
                            self.report_logger.log_tool_call(
                                section.title, section_index, c["name"], c["arguments"], tool_calls_count
                            )
                        except Exception:
                            pass
                    messages.append({"role": "tool", "tool_call_id": c["id"], "content": str(result)[:8000]})
                    # RPT-11: 原生路径此前从不写 log_tool_result，agent_log.jsonl 丢失整条证据链。
                    if self.report_logger:
                        try:
                            self.report_logger.log_tool_result(
                                section.title, section_index, c["name"],
                                str(result)[:8000], tool_calls_count
                            )
                        except Exception:
                            pass
                if progress_callback:
                    progress_callback("generating", min(90, tool_calls_count * 12), f"{section.title}: 工具检索 {tool_calls_count}")
                continue

            # 无更多工具调用（或已达上限）→ 收尾出正文
            if content.strip():
                # EXECPLAN2 F-7-2 工具调用不足且仍可继续检索 → 拒绝过早出正文，强制补足实证（对齐 ReAct 路径）
                if tool_calls_count < _eff_min and tool_calls_count < max_tool_calls:
                    messages.append({"role": "assistant", "content": content})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"你只调用了 {tool_calls_count} 次工具，少于本章要求的至少 "
                            f"{_eff_min} 次。请勿现在输出正文，"
                            "继续发起工具调用以补足实证后再撰写本章。"
                        ),
                    })
                    continue
                return content
            # 达到工具上限但模型还没出正文：显式要求收尾
            messages.append({"role": "user", "content": "请基于以上工具结果直接输出本章完整 Markdown 正文。"})

        # 兜底：迭代用尽仍无正文 → 末次无工具强制出文
        final = self.llm.chat(messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt + "\n\n请直接输出本章 Markdown 正文。"},
        ], temperature=Config.REPORT_AGENT_TEMPERATURE, max_tokens=Config.REPORT_AGENT_SECTION_MAX_TOKENS)
        return final

    def _generate_section_react(
        self,
        section: ReportSection,
        outline: ReportOutline,
        previous_sections: List[str],
        progress_callback: Optional[Callable] = None,
        section_index: int = 0
    ) -> str:
        """
        使用ReACT模式生成单个章节内容
        
        ReACT循环：
        1. Thought（思考）- 分析需要什么信息
        2. Action（行动）- 调用工具获取信息
        3. Observation（观察）- 分析工具返回结果
        4. 重复直到信息足够或达到最大次数
        5. Final Answer（最终回答）- 生成章节内容
        
        Args:
            section: 要生成的章节
            outline: 完整大纲
            previous_sections: 之前章节的内容（用于保持连贯性）
            progress_callback: 进度回调
            section_index: 章节索引（用于日志记录）
            
        Returns:
            章节内容（Markdown格式）
        """
        logger.info(f"ReACT生成章节: {section.title}")
        
        # 记录章节开始日志
        if self.report_logger:
            self.report_logger.log_section_start(section.title, section_index)
        
        # 规划阶段的章节描述拼进章节标题位，让撰写贴合大纲意图（模板无独立槽位，
        # 避免对超长模板做侵入式修改）
        _section_heading = section.title
        if section.description:
            _section_heading = f"{section.title}\n本章内容定位（大纲规划）: {section.description}"
        # LOOP-015: 有效工具调用下限先于提示词计算——padding / 证据预注入章节的更低下限
        # 直接写进提示词槽位，与循环闸门保持一致（提示词不再逼模型凑满配置下限）。
        min_tool_calls = self._effective_min_tool_calls(section)
        _prompt_kwargs = self._section_prompt_kwargs()  # RQ-1: 篇幅+工具调用范围槽位（随形状伸缩）
        _prompt_kwargs["min_tool_calls"] = min_tool_calls
        system_prompt = self._lang_override() + SECTION_SYSTEM_PROMPT_TEMPLATE.format(
            report_title=outline.title,
            report_summary=outline.summary,
            simulation_requirement=self.simulation_requirement,
            section_title=_section_heading,
            tools_description=self._get_tools_description(),
            tool_usage_hints=self._tool_usage_hints(),  # RPT-7: live 工具集
            **_prompt_kwargs,
        )
        # T4.1: 钉入研究背景档案 + 来源索引，让每章撰写复用真实角色/关系/时间线并按 [S#] 引用。
        system_prompt = self._prepend_research_background(system_prompt,
                                                          section_title=section.title)

        # 构建用户prompt - 每个已完成章节各传入最大4000字
        if previous_sections:
            previous_parts = []
            # RQ-7: 每个已完成章节的上下文切片从固定 8000 升级为按提供方窗口预算化——大窗口
            # 模型携带全量前文（避免长研究报告被切碎），小窗口守住 8000 floor（避免重复、保持连贯）。
            # ADAPTIVE_CONTEXT 关闭时 _cap 恒为 8000（行为与历史逐字节一致）。
            _cap = self._prior_section_char_budget(8000, len(previous_sections))
            for sec in previous_sections:
                truncated = sec[:_cap] + "..." if len(sec) > _cap else sec
                previous_parts.append(truncated)
            previous_content = "\n\n---\n\n".join(previous_parts)
        else:
            previous_content = "（这是第一个章节）"
        
        user_prompt = SECTION_USER_PROMPT_TEMPLATE.format(
            previous_content=previous_content,
            section_title=section.title,
            **_prompt_kwargs,  # RQ-1: 篇幅+工具调用范围槽位（min_tool_calls 已按 LOOP-015 生效值覆盖）
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # ReACT循环（min_tool_calls 在提示词构建前经 _effective_min_tool_calls 计算，
        # T4.4 配置下限 + LOOP-015 padding/证据预注入下调）
        tool_calls_count = 0
        max_iterations = 14  # RQ-1: 10→14，最大迭代轮数（更高以支撑更深入的检索与更长的章节）
        conflict_retries = 0  # 工具调用与Final Answer同时出现的连续冲突次数
        contamination_retries = 0  # 输出被污染（系统提示泄漏/工具调用残留）的连续重试次数
        MAX_CONTAMINATION_RETRIES = 2  # 污染输出最多纠正重试次数
        used_tools = set()  # 记录已调用过的工具名
        # REPORT-8: interview_agents 仍可用（保留在 self.tools / 提示词中），但不再进入
        # 「未使用工具」推荐集——采访依赖 OASIS 在线、延迟高且易超时，不应被反复 nudge 去尝试。
        all_tools = {"insight_forge", "panorama_search", "quick_search",
                     "simulation_outcomes", "coalition_map", "opinion_shift"}
        if self.base_simulation_id:
            all_tools.add("scenario_diff")  # T4.7

        # 报告上下文，用于InsightForge的子问题生成
        report_context = f"章节标题: {section.title}\n模拟需求: {self.simulation_requirement}"
        
        for iteration in range(max_iterations):
            if progress_callback:
                progress_callback(
                    "generating", 
                    int((iteration / max_iterations) * 100),
                    f"深度检索与撰写中 ({tool_calls_count}/{self.MAX_TOOL_CALLS_PER_SECTION})"
                )
            
            # 调用LLM（提高 max_tokens 以容纳更长的章节正文；对 OpenAI 兼容提供方生效，
            # CLI 提供方由 prompt 篇幅下限驱动）
            # REPORT-9: 工具调用未达下限的回合必为「工具决策回合」（此时 Final Answer 会被拒绝、
            # 强制继续检索），用较小的 REPORT_AGENT_TOOL_TURN_MAX_TOKENS 抑制长链推理浪费；一旦达
            # 到下限，本回合可能直接产出最终正文，回到完整 SECTION_MAX_TOKENS 预算以免截断正文。
            # REPORT-10: 温度统一读 Config.REPORT_AGENT_TEMPERATURE（默认 0.5，行为不变、可运维调）。
            _turn_max_tokens = (
                Config.REPORT_AGENT_SECTION_MAX_TOKENS
                if tool_calls_count >= min_tool_calls
                else getattr(Config, "REPORT_AGENT_TOOL_TURN_MAX_TOKENS", 8192)
            )
            response = self.llm.chat(
                messages=messages,
                temperature=Config.REPORT_AGENT_TEMPERATURE,
                max_tokens=_turn_max_tokens
            )

            # 检查 LLM 返回是否为 None（API 异常或内容为空）
            if response is None:
                logger.warning(f"章节 {section.title} 第 {iteration + 1} 次迭代: LLM 返回 None")
                # 如果还有迭代次数，添加消息并重试
                if iteration < max_iterations - 1:
                    messages.append({"role": "assistant", "content": "（响应为空）"})
                    messages.append({"role": "user", "content": "请继续生成内容。"})
                    continue
                # 最后一次迭代也返回 None，跳出循环进入强制收尾
                break

            logger.debug(f"LLM响应: {response[:200]}...")

            # 解析一次，复用结果
            tool_calls = self._parse_tool_calls(response)
            has_tool_calls = bool(tool_calls)
            has_final_answer = "Final Answer:" in response

            # ── 冲突处理：LLM 同时输出了工具调用和 Final Answer ──
            if has_tool_calls and has_final_answer:
                conflict_retries += 1
                logger.warning(
                    f"章节 {section.title} 第 {iteration+1} 轮: "
                    f"LLM 同时输出工具调用和 Final Answer（第 {conflict_retries} 次冲突）"
                )

                if conflict_retries <= 2:
                    # 前两次：丢弃本次响应，要求 LLM 重新回复
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            "【格式错误】你在一次回复中同时包含了工具调用和 Final Answer，这是不允许的。\n"
                            "每次回复只能做以下两件事之一：\n"
                            "- 调用一个工具（输出一个 <tool_call> 块，不要写 Final Answer）\n"
                            "- 输出最终内容（以 'Final Answer:' 开头，不要包含 <tool_call>）\n"
                            "请重新回复，只做其中一件事。"
                        ),
                    })
                    continue
                else:
                    # 第三次：降级处理，截断到第一个工具调用，强制执行
                    logger.warning(
                        f"章节 {section.title}: 连续 {conflict_retries} 次冲突，"
                        "降级为截断执行第一个工具调用"
                    )
                    first_tool_end = response.find('</tool_call>')
                    if first_tool_end != -1:
                        response = response[:first_tool_end + len('</tool_call>')]
                        tool_calls = self._parse_tool_calls(response)
                        has_tool_calls = bool(tool_calls)
                    has_final_answer = False
                    conflict_retries = 0

            # 记录 LLM 响应日志
            if self.report_logger:
                self.report_logger.log_llm_response(
                    section_title=section.title,
                    section_index=section_index,
                    response=response,
                    iteration=iteration + 1,
                    has_tool_calls=has_tool_calls,
                    has_final_answer=has_final_answer
                )

            # ── 情况1：LLM 输出了 Final Answer ──
            if has_final_answer:
                # 工具调用次数不足，拒绝并要求继续调工具
                if tool_calls_count < min_tool_calls:
                    messages.append({"role": "assistant", "content": response})
                    unused_tools = all_tools - used_tools
                    unused_hint = f"（这些工具还未使用，推荐用一下他们: {', '.join(unused_tools)}）" if unused_tools else ""
                    messages.append({
                        "role": "user",
                        "content": REACT_INSUFFICIENT_TOOLS_MSG.format(
                            tool_calls_count=tool_calls_count,
                            min_tool_calls=min_tool_calls,
                            unused_hint=unused_hint,
                        ),
                    })
                    continue

                # 正常结束
                final_answer = response.split("Final Answer:")[-1].strip()

                # 即使带了 "Final Answer:"，正文仍可能被污染（claude-cli 偶尔在前缀后泄漏系统提示）。
                # 检测到污染则纠正重试，绝不直接采纳。
                if _looks_contaminated(final_answer):
                    if contamination_retries < MAX_CONTAMINATION_RETRIES:
                        contamination_retries += 1
                        logger.warning(
                            f"章节 {section.title} 的 Final Answer 疑似被污染，纠正重试 "
                            f"{contamination_retries}/{MAX_CONTAMINATION_RETRIES}"
                        )
                        messages.append({"role": "assistant", "content": response})
                        messages.append({"role": "user", "content": REACT_CONTAMINATED_RETRY_MSG})
                        continue
                    logger.error(
                        f"章节 {section.title} 的 Final Answer 多次被污染，写入失败占位符"
                    )
                    return SECTION_FAILURE_PLACEHOLDER

                logger.info(f"章节 {section.title} 生成完成（工具调用: {tool_calls_count}次）")

                if self.report_logger:
                    self.report_logger.log_section_content(
                        section_title=section.title,
                        section_index=section_index,
                        content=final_answer,
                        tool_calls_count=tool_calls_count
                    )
                return final_answer

            # ── 情况2：LLM 尝试调用工具 ──
            if has_tool_calls:
                # 工具额度已耗尽 → 明确告知，要求输出 Final Answer
                if tool_calls_count >= self.MAX_TOOL_CALLS_PER_SECTION:
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": REACT_TOOL_LIMIT_MSG.format(
                            tool_calls_count=tool_calls_count,
                            max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        ),
                    })
                    continue

                # 只执行第一个工具调用
                call = tool_calls[0]
                if len(tool_calls) > 1:
                    logger.info(f"LLM 尝试调用 {len(tool_calls)} 个工具，只执行第一个: {call['name']}")

                # RPT-7: XML 解析出的工具名在此校验——未知名（如已被移除的 interview_agents）
                # 给纠正性 Observation，且**不**计入工具调用预算（此前垃圾调用照样 +1）。
                # self.tools 为空（仅测试替身场景）时跳过校验，保持旧直通行为。
                if self.tools and call["name"] not in self._valid_tool_names():
                    logger.warning(f"章节 {section.title}: 模型调用了未知工具 '{call['name']}'，已纠正（不计预算）")
                    messages.append({"role": "assistant", "content": response})
                    messages.append({
                        "role": "user",
                        "content": (
                            f"【工具错误】'{call['name']}' 不是可用工具。请从以下工具中选择重新调用："
                            f"{', '.join(sorted(self.tools.keys()))}"
                        ),
                    })
                    continue

                if self.report_logger:
                    self.report_logger.log_tool_call(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        parameters=call.get("parameters", {}),
                        iteration=iteration + 1
                    )

                result = self._execute_tool(
                    call["name"],
                    call.get("parameters", {}),
                    report_context=report_context
                )

                if self.report_logger:
                    self.report_logger.log_tool_result(
                        section_title=section.title,
                        section_index=section_index,
                        tool_name=call["name"],
                        result=result,
                        iteration=iteration + 1
                    )

                tool_calls_count += 1
                used_tools.add(call['name'])
                self._section_tool_calls += 1  # EXECPLAN2 I-5-4: per-section 工具调用计数

                # 构建未使用工具提示
                unused_tools = all_tools - used_tools
                unused_hint = ""
                if unused_tools and tool_calls_count < self.MAX_TOOL_CALLS_PER_SECTION:
                    unused_hint = REACT_UNUSED_TOOLS_HINT.format(unused_list="、".join(unused_tools))

                messages.append({"role": "assistant", "content": response})
                messages.append({
                    "role": "user",
                    "content": REACT_OBSERVATION_TEMPLATE.format(
                        tool_name=call["name"],
                        result=result,
                        tool_calls_count=tool_calls_count,
                        max_tool_calls=self.MAX_TOOL_CALLS_PER_SECTION,
                        used_tools_str=", ".join(used_tools),
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # ── 情况3：既没有工具调用，也没有 Final Answer ──
            messages.append({"role": "assistant", "content": response})

            if tool_calls_count < min_tool_calls:
                # 工具调用次数不足，推荐未用过的工具
                unused_tools = all_tools - used_tools
                unused_hint = f"（这些工具还未使用，推荐用一下他们: {', '.join(unused_tools)}）" if unused_tools else ""

                messages.append({
                    "role": "user",
                    "content": REACT_INSUFFICIENT_TOOLS_MSG_ALT.format(
                        tool_calls_count=tool_calls_count,
                        min_tool_calls=min_tool_calls,
                        unused_hint=unused_hint,
                    ),
                })
                continue

            # 工具调用已足够，LLM 输出了内容但没带 "Final Answer:" 前缀。
            # 历史上这里直接采纳原始输出，导致 claude-cli 的系统提示泄漏/工具调用残留被写进章节。
            # 现在先做污染检测：被污染则纠正重试；多次仍失败则写占位符而非垃圾内容。
            final_answer = response.strip()
            if _looks_contaminated(final_answer):
                if contamination_retries < MAX_CONTAMINATION_RETRIES:
                    contamination_retries += 1
                    logger.warning(
                        f"章节 {section.title} 无 'Final Answer:' 且输出疑似被污染，纠正重试 "
                        f"{contamination_retries}/{MAX_CONTAMINATION_RETRIES}"
                    )
                    # 此前已在情况3入口处把 assistant response 追加进 messages，这里只补纠正提示。
                    messages.append({"role": "user", "content": REACT_CONTAMINATED_RETRY_MSG})
                    continue
                logger.error(
                    f"章节 {section.title} 多次输出被污染且无 'Final Answer:'，写入失败占位符"
                )
                return SECTION_FAILURE_PLACEHOLDER

            logger.info(f"章节 {section.title} 未检测到 'Final Answer:' 前缀，直接采纳LLM输出作为最终内容（工具调用: {tool_calls_count}次）")

            if self.report_logger:
                self.report_logger.log_section_content(
                    section_title=section.title,
                    section_index=section_index,
                    content=final_answer,
                    tool_calls_count=tool_calls_count
                )
            return final_answer
        
        # 达到最大迭代次数，强制生成内容
        logger.warning(f"章节 {section.title} 达到最大迭代次数，强制生成")
        messages.append({"role": "user", "content": REACT_FORCE_FINAL_MSG})

        # REPORT-9: 这是强制收尾的「最终答案回合」，保留完整 SECTION_MAX_TOKENS 预算以免截断正文。
        # REPORT-10: 温度读 Config.REPORT_AGENT_TEMPERATURE（默认 0.5，行为不变）。
        response = self.llm.chat(
            messages=messages,
            temperature=Config.REPORT_AGENT_TEMPERATURE,
            max_tokens=Config.REPORT_AGENT_SECTION_MAX_TOKENS
        )

        # 检查强制收尾时 LLM 返回是否为 None
        if response is None:
            logger.error(f"章节 {section.title} 强制收尾时 LLM 返回 None，使用默认错误提示")
            final_answer = "（本章节生成失败：LLM 返回空响应，请稍后重试）"
        elif "Final Answer:" in response:
            final_answer = response.split("Final Answer:")[-1].strip()
        else:
            final_answer = response

        # 强制收尾也可能吐出被污染的内容：宁可写占位符，也不把系统提示泄漏/工具残留写进报告。
        if _looks_contaminated(final_answer):
            logger.error(f"章节 {section.title} 强制收尾输出仍被污染，写入失败占位符")
            final_answer = SECTION_FAILURE_PLACEHOLDER

        # 记录章节内容生成完成日志
        if self.report_logger:
            self.report_logger.log_section_content(
                section_title=section.title,
                section_index=section_index,
                content=final_answer,
                tool_calls_count=tool_calls_count
            )
        
        return final_answer
    
    def _resurrect_failed_sections(
        self,
        report_id: str,
        outline: "ReportOutline",
        failed_titles: List[str],
        generated_sections: List[str],
    ) -> List[str]:
        """SESSIONB-1 占位符章节复活：组装成稿前对失败章节做一轮有界重试。

        终审 _final_audit_integrity_issues 对任何仍存在的失败占位符章节一票否决整份
        成稿（拒绝发布部分成稿）——单个章节在生成时段的瞬时故障（限流/配额窗口/单次
        5xx）会在全部章节、骨架与图表成本烧完后丢弃整份报告；resume 只能整报告重烧。
        章节生成与终审之间往往隔着数十分钟（其余章节 + 骨架 + 抽取），足以跨过配额
        重置/提供方恢复窗口，因此在组装前对每个占位符章节**再走一次**既有的
        _generate_section_with_retry 全链路（含语言验收与反思修订）。成功即回写
        section_NN.md 与上下文；仍失败则保留占位符、走既有部分成稿路径——终审语义
        逐字节不变，本方法只是把「直接丢弃」换成「先重试一轮」。返回仍失败的标题列表。"""
        from collections import Counter
        pending = Counter(failed_titles)
        still_failed: List[str] = []
        for idx, section in enumerate(outline.sections):
            if pending.get(section.title, 0) <= 0:
                continue
            pending[section.title] -= 1
            section_num = idx + 1
            logger.info(f"复活失败章节（重试一轮）: {section.title} ({section_num})")
            try:
                content = self._generate_section_with_retry(
                    section=section,
                    outline=outline,
                    previous_sections=generated_sections,
                    progress_callback=None,
                    section_index=section_num,
                )
            except Exception as exc:  # noqa: BLE001 — 复活失败保留占位符，绝不拖垮成稿
                logger.warning(f"章节复活重试仍失败（保留占位符）: {section.title} -> {exc}")
                still_failed.append(section.title)
                continue
            if (not content or content == SECTION_FAILURE_PLACEHOLDER
                    or content.strip().startswith("（本章节生成失败：")):
                still_failed.append(section.title)
                continue
            section.content = content
            ReportManager.save_section(report_id, section_num, section)
            if 0 <= idx < len(generated_sections):
                generated_sections[idx] = f"## {section.title}\n\n{content}"
            logger.info(f"章节复活成功，已回写: {report_id}/section_{section_num:02d}.md")
        # 计数兜底：标题未在大纲中命中（理论不可达）时如实保留为失败，不得凭空洗白。
        for title, count in pending.items():
            still_failed.extend([title] * max(0, count))
        return still_failed

    def _commit_forecast_ledger(self, report_id: str, report: "Report",
                                error: Optional[str] = None) -> Dict[str, Any]:
        """EVAL-1: run the post-publication steps (first: the forecast-ledger commit).

        Called once the report is terminal and saved (meta.json + full_report.md on
        disk), so ``publication_status`` judges the exact published bytes. Only reads
        the sealed artifacts: never mutates forecast.json / full_report.md and never
        changes the report status. Any failure yields ``{'status': 'error'}``, logged
        at WARNING because such a report is missing from the auditable ledger.
        """
        try:
            from . import ledger_commit as _ledger_commit
            _status = getattr(report, "status", None)
            receipt = _ledger_commit.run_post_publication(
                self, report_id,
                report_status=str(getattr(_status, "value", _status) or ""),
                error=error,
                publication_status_fn=ReportManager.publication_status,
                load_forecast_fn=ReportManager.load_structured_forecast,
                final_audit_path_fn=ReportManager._get_report_final_audit_path,
            )
        except Exception as _le:  # noqa: BLE001 — 账本为旁路记账，绝不影响报告终态
            receipt = {"status": "error", "reasons": [f"{type(_le).__name__}: {_le}"[:300]]}
        if not isinstance(receipt, dict):
            receipt = {"status": "error", "reasons": ["post-publication returned no receipt"]}
        receipt.setdefault("report_id", report_id)
        self.ledger_receipt = receipt
        _line = (f"[ledger] status={receipt.get('status')} "
                 f"commit_id={receipt.get('commit_id')} report={report_id}")
        if receipt.get("status") == "error":
            logger.warning(f"{_line} reasons={receipt.get('reasons')}")
        else:
            logger.info(_line)
        return receipt

    def generate_report(
        self,
        progress_callback: Optional[Callable[[str, int, str], None]] = None,
        report_id: Optional[str] = None
    ) -> Report:
        """
        生成完整报告（分章节实时输出）
        
        每个章节生成完成后立即保存到文件夹，不需要等待整个报告完成。
        文件结构：
        reports/{report_id}/
            meta.json       - 报告元信息
            outline.json    - 报告大纲
            progress.json   - 生成进度
            section_01.md   - 第1章节
            section_02.md   - 第2章节
            ...
            full_report.md  - 完整报告
        
        Args:
            progress_callback: 进度回调函数 (stage, progress, message)
            report_id: 报告ID（可选，如果不传则自动生成）
            
        Returns:
            Report: 完整报告
        """
        import uuid
        
        # 如果没有传入 report_id，则自动生成
        if not report_id:
            report_id = f"report_{uuid.uuid4().hex[:12]}"
        self._active_report_id = report_id
        start_time = datetime.now()
        
        report = Report(
            report_id=report_id,
            simulation_id=self.simulation_id,
            graph_id=self.graph_id,
            simulation_requirement=self.simulation_requirement,
            status=ReportStatus.PENDING,
            created_at=datetime.now().isoformat()
        )
        
        # 已完成的章节标题列表（用于进度追踪）
        completed_section_titles = []

        # EXECPLAN2 I-5-4: 报告级遥测 —— 设定 LLM 计量上下文的 stage='report'。
        # run_id 优先沿用编排器已设定的 run（如 pipeline_id，便于跨阶段汇总）；独立生成
        # （无上游 run）时退回 report_id，使手动报告也被计量。保存旧上下文，finally 中还原，
        # 避免污染复用线程/调用方。默认关闭时不动上下文。
        _telemetry_on = self._telemetry_enabled()
        _prev_run_ctx = None
        _telemetry_run_id = report_id  # 实际用于 LLMMeter 快照的 run 键
        _report_stage_before: Dict[str, Any] = {}  # 报告开始时 stage='report' 的基线快照
        section_rollup: List[Dict[str, Any]] = []  # I-5-4: per-section 遥测条目
        if _telemetry_on:
            try:
                _prev_run_ctx = get_run_context()
                # 沿用上游 run_id（若已设），否则用 report_id；stage 统一标记为 'report'
                _telemetry_run_id = (_prev_run_ctx[0] if _prev_run_ctx and _prev_run_ctx[0] else report_id)
                set_run_context(_telemetry_run_id, "report")
                # 基线：共享 run 上可能已有其它报告的 report 阶段花销，取差值才是本报告真实花销
                _report_stage_before = self._meter_stage_total(_telemetry_run_id, "report")
            except Exception:  # noqa: BLE001 — 遥测初始化失败不得影响报告生成
                _telemetry_on = False
                _telemetry_run_id = report_id

        try:
            # 初始化：创建报告文件夹并保存初始状态
            ReportManager._ensure_report_folder(report_id)
            
            # 初始化日志记录器（结构化日志 agent_log.jsonl）
            self.report_logger = ReportLogger(report_id)
            self.report_logger.log_start(
                simulation_id=self.simulation_id,
                graph_id=self.graph_id,
                simulation_requirement=self.simulation_requirement
            )
            
            # 初始化控制台日志记录器（console_log.txt）
            self.console_logger = ReportConsoleLogger(report_id)
            
            ReportManager.update_progress(
                report_id, "pending", 0, "初始化报告...",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            # 阶段1: 规划大纲
            report.status = ReportStatus.PLANNING
            ReportManager.update_progress(
                report_id, "planning", 5, "开始规划报告大纲...",
                completed_sections=[]
            )
            
            # 记录规划开始日志
            self.report_logger.log_planning_start()
            
            if progress_callback:
                progress_callback("planning", 0, "开始规划报告大纲...")

            # R2-DETAIL-2 / NEXTSTEPS P0-1: 先于大纲推导「预测骨架」，使章节围绕可证伪的预测组织，
            # 而非反向从成稿叙事抽取。顺序：构建确定性信号包（若开）→ 推导骨架（含早落 forecast.json）
            # → 把骨架块 + 强制结构（框架/逐情景/校准）传入 plan_outline。报告文件夹已于上文创建，
            # 骨架早落安全。任一旗标关闭或推导失败时 self._forecast_spine_block 为空串，plan_outline
            # 退回历史行为（提示词逐字节一致），章节阶段亦不受影响（degrade-safe）。
            if getattr(Config, "REPORT_SIGNAL_PACK", False) and not self._signal_pack:
                try:
                    self._signal_pack = self._build_signal_pack()
                    if self._signal_pack:
                        logger.info(f"已注入模拟量化信号包（{len(self._signal_pack)} 字）到各章节提示词")
                except Exception as _sp_err:  # noqa: BLE001 — 信号包为可选增强，失败不影响主流程
                    logger.warning(f"构建模拟量化信号包失败（忽略）: {_sp_err}")
                    self._signal_pack = ""

            # 预测市场信号包（Polymarket 公开 Gamma API）：与模拟信号包并列注入每章
            # 提示词与预测骨架（下方 _derive_and_pin_forecast_spine 复用）。无 key/无数据/
            # 关闭旗标时为空串 → 注入自动跳过（degrade-safe，提示词与历史逐字节一致）。
            if (getattr(Config, "PREDICTION_MARKETS_ENABLED", True)
                    and not getattr(self, "_market_pack", "")):
                try:
                    self._market_pack = self._build_market_pack()
                    if self._market_pack:
                        logger.info(
                            f"已注入预测市场信号包（{len(getattr(self, '_prediction_markets', []))} 个市场）"
                            "到各章节提示词")
                except Exception as _mp_err:  # noqa: BLE001 — 市场信号为可选增强
                    logger.warning(f"构建预测市场信号包失败（忽略）: {_mp_err}")
                    self._market_pack = ""

            if (getattr(Config, "REPORT_STRUCTURED_FORECAST", True)
                    and getattr(Config, "REPORT_FORECAST_SPINE_FIRST", True)):
                self._derive_and_pin_forecast_spine(report_id)

            _spine_ready = bool(self._forecast_spine and self._forecast_spine.get("scenarios"))
            outline = self.plan_outline(
                progress_callback=lambda stage, prog, msg:
                    progress_callback(stage, prog // 5, msg) if progress_callback else None,
                forecast_spine_block=self._forecast_spine_block,
                require_forecast_structure=_spine_ready,
            )
            report.outline = outline
            # RPT-5: 供引用溯源审计豁免系统注入的摘要 blockquote（"> {outline.summary}"）。
            self._outline_summary = outline.summary or ""

            # 记录规划完成日志
            self.report_logger.log_planning_complete(outline.to_dict())
            
            # 保存大纲到文件
            ReportManager.save_outline(report_id, outline)
            ReportManager.update_progress(
                report_id, "planning", 15, f"大纲规划完成，共{len(outline.sections)}个章节",
                completed_sections=[]
            )
            ReportManager.save_report(report)
            
            logger.info(f"大纲已保存到文件: {report_id}/outline.json")
            
            # 阶段2: 逐章节生成（分章节保存）
            report.status = ReportStatus.GENERATING

            # R2-DETAIL-2: 信号包与预测骨架已在大纲规划前构建/推导（见上），此处不再重复；
            # self._signal_pack / self._forecast_spine_block 已就绪并将注入每章提示词。

            total_sections = len(outline.sections)
            generated_sections = []  # 保存内容用于上下文
            failed_section_titles = []  # 记录生成失败（写入占位符）的章节，用于状态汇报
            # RPT-2(b): 连续失败计数。大纲已降级（LLM 故障前哨）+ 前两章接连落占位符 ⇒
            # 判定为系统性 LLM 中断，快速中止（走既有失败路径标记 FAILED，可重试），
            # 而非对着死掉的提供方烧完余下章节。并发路径的 _gen_body 内部吞异常返回
            # 占位符，故计数以「占位符结果」为准（两条路径统一覆盖）。
            _consecutive_failures = 0
            _abort_on_outage = bool(getattr(Config, "REPORT_ABORT_ON_LLM_OUTAGE", True))

            # EXECPLAN2 I-6-3: optionally pre-generate sections concurrently. The
            # shipped Config default is REPORT_SECTION_CONCURRENCY=6 (REPORT-1 1→3,
            # PAR-3 3→6; serial cost measured at 12 sections ≈ 24.6 min / 216 calls).
            # Setting it to 1 → _precomputed stays None → the serial loop below calls
            # _generate_section inline exactly as the legacy path (byte-identical).
            # REPORT_SECTION_CONTEXT_MODE=brief (serial path) swaps the O(N²) full
            # prior-section context for the compact synthesis brief.
            _precomputed = None
            _context_mode = (getattr(Config, "REPORT_SECTION_CONTEXT_MODE", "full") or "full").strip().lower()
            _section_brief = ""
            try:
                _concurrency = max(1, int(getattr(Config, "REPORT_SECTION_CONCURRENCY", 1) or 1))
            except (TypeError, ValueError):
                _concurrency = 1
            if _concurrency > 1 and total_sections > 1:
                logger.info(f"I-6-3: 并发生成 {total_sections} 个章节（concurrency={_concurrency}）")
                _precomputed = self._generate_sections_concurrent(outline, _concurrency)
            elif _context_mode == "brief":
                _section_brief = self._build_synthesis_brief(outline.sections)

            for i, section in enumerate(outline.sections):
                section_num = i + 1
                base_progress = 20 + int((i / total_sections) * 70)
                
                # 更新进度
                ReportManager.update_progress(
                    report_id, "generating", base_progress,
                    f"正在生成章节: {section.title} ({section_num}/{total_sections})",
                    current_section=section.title,
                    completed_sections=completed_section_titles
                )
                
                if progress_callback:
                    progress_callback(
                        "generating", 
                        base_progress, 
                        f"正在生成章节: {section.title} ({section_num}/{total_sections})"
                    )
                
                # EXECPLAN2 I-5-4: per-section 遥测——记录本章节开始时刻与累计计量快照、
                # 归零本章节工具计数；章节结束后相减得到该章节的 LLM 经济学。
                # I-6-3: 并发模式下章节生成已发生在线程池中，逐章 meter 差值与 _section_tool_calls
                # 计数器（被多线程共享递增）都不再可归因到单个章节，故跳过逐章遥测（run 级汇总仍准确）。
                _sec_telemetry_on = _telemetry_on and _precomputed is None
                _sec_started = time.monotonic()
                _sec_meter_before = self._meter_total(_telemetry_run_id) if _sec_telemetry_on else {}
                self._section_tool_calls = 0

                # 生成主章节内容。
                # 纵深防御：单个章节的 LLM 调用可能抛异常（如 MiniMax 域内容审核 422
                # new_sensitive、限流、网络错误）。绝不让单章节失败拖垮整份报告——捕获后
                # 写入失败占位符，沿用既有的 failed_section_titles 机制，其余章节照常生成，
                # 最终产出一份"部分完成"的报告而非整体失败。
                try:
                    if _precomputed is not None:
                        # I-6-3: content already produced concurrently; bookkeeping stays serial/in-order.
                        section_content = _precomputed.get(i, SECTION_FAILURE_PLACEHOLDER)
                    else:
                        # I-6-3: brief context mode swaps full prior-section text for the compact brief.
                        # RPT-2: 经退避重试包装，瞬时故障不再直接落占位符。
                        _prev_ctx = [_section_brief] if (_context_mode == "brief" and _section_brief) else generated_sections
                        section_content = self._generate_section_with_retry(
                            section=section,
                            outline=outline,
                            previous_sections=_prev_ctx,
                            progress_callback=lambda stage, prog, msg, _base=base_progress:
                                progress_callback(
                                    stage,
                                    _base + int(prog * 0.7 / total_sections),
                                    msg
                                ) if progress_callback else None,
                            section_index=section_num
                        )
                except Exception as sec_err:  # noqa: BLE001 — 章节级容错，绝不整体失败
                    logger.error(f"章节 LLM 调用异常（已降级为占位符）: {section.title} -> {sec_err}")
                    if self.report_logger:
                        try:
                            self.report_logger.log_error(str(sec_err), stage="generating", section_title=section.title)
                        except Exception:
                            pass
                    section_content = SECTION_FAILURE_PLACEHOLDER

                # EXECPLAN2 I-3-4: 若为情景对比章节且开关开启，把确定性结构化对比表
                # 前置到本章正文，使 LLM 围绕权威差值叙述（不复算/不反转方向）。
                if (
                    self.base_simulation_id
                    and getattr(Config, "REPORT_COMPARISON_TABLE", False)
                    and section_content != SECTION_FAILURE_PLACEHOLDER
                    and self._is_comparison_section(section.title)
                ):
                    try:
                        diff_dict = self._scenario_diff_structured()
                        if diff_dict:
                            table_md = self._render_comparison_table(diff_dict)
                            if table_md:
                                section_content = table_md + "\n\n" + section_content
                                # 落盘结构化对比工件，供 UI / diff 工具消费
                                cpath = os.path.join(
                                    ReportManager._get_report_folder(report_id), "comparison.json"
                                )
                                write_text_atomic(
                                    cpath, json.dumps(diff_dict, ensure_ascii=False, indent=2)
                                )
                                logger.info(f"已注入结构化对比表并写入 comparison.json: {report_id}")
                    except Exception as _ct_err:  # noqa: BLE001 — 对比表为可选增强，失败不影响主流程
                        logger.warning(f"注入结构化对比表失败（忽略）: {_ct_err}")

                section.content = section_content
                if section_content == SECTION_FAILURE_PLACEHOLDER:
                    failed_section_titles.append(section.title)
                    _consecutive_failures += 1
                    logger.error(f"章节生成失败（已写入占位符）: {section.title}")
                    # RPT-2(b): 大纲降级 + 前两章接连失败 ⇒ 系统性 LLM 中断，快速中止。
                    # 抛出 → 既有失败路径统一落盘 FAILED + update_progress('failed')（可重试），
                    # 上游 S1 健康门不必再事后猜测「假完成」。
                    if (_abort_on_outage and self._outline_degraded
                            and section_num <= 2 and _consecutive_failures >= 2):
                        raise RuntimeError(
                            "疑似 LLM 服务中断：大纲规划已降级且前两个章节接连生成失败，"
                            "提前中止本报告（修复提供方后可重试）"
                        )
                else:
                    _consecutive_failures = 0
                generated_sections.append(f"## {section.title}\n\n{section_content}")

                # 保存章节
                ReportManager.save_section(report_id, section_num, section)
                completed_section_titles.append(section.title)

                # 记录章节完成日志
                full_section_content = f"## {section.title}\n\n{section_content}"

                # EXECPLAN2 I-5-4: 计算本章节遥测条目（LLM 调用/tokens/cost/latency + 工具调用）
                # I-6-3: 并发模式跳过（_sec_telemetry_on 已含 _precomputed is None 判断）。
                _sec_telemetry = None
                if _sec_telemetry_on:
                    try:
                        _sec_after = self._meter_total(_telemetry_run_id)
                        _sec_telemetry = self._meter_delta(
                            _sec_meter_before, _sec_after,
                            duration_s=time.monotonic() - _sec_started,
                            tool_calls=self._section_tool_calls,
                        )
                        _sec_telemetry["section_title"] = section.title
                        _sec_telemetry["section_index"] = section_num
                        section_rollup.append(_sec_telemetry)
                    except Exception:  # noqa: BLE001 — 遥测计算失败不得影响报告生成
                        _sec_telemetry = None

                if self.report_logger:
                    self.report_logger.log_section_full_complete(
                        section_title=section.title,
                        section_index=section_num,
                        full_content=full_section_content.strip(),
                        telemetry=_sec_telemetry
                    )

                logger.info(f"章节已保存: {report_id}/section_{section_num:02d}.md")
                
                # 更新进度
                ReportManager.update_progress(
                    report_id, "generating", 
                    base_progress + int(70 / total_sections),
                    f"章节 {section.title} 已完成",
                    current_section=None,
                    completed_sections=completed_section_titles
                )
            
            # RPT-2(c): 全部章节均为失败占位符 ⇒ 报告没有任何可用内容，绝不能标记 completed
            # （历史上 91f5 就是 5/5 占位符仍 status=completed，靠编排器健康门事后击杀）。
            # 抛出 → 既有失败路径统一持久化 FAILED + update_progress('failed')，且先于
            # _finalize_structured_forecast（不给空报告生成 forecast.json 的机会）。
            if (_abort_on_outage and total_sections > 0
                    and len(failed_section_titles) >= total_sections):
                raise RuntimeError(
                    f"全部 {total_sections} 个章节生成失败（疑似 LLM 服务中断），"
                    "报告标记为失败（可重试），不写入全占位符的『完成』报告"
                )

            # SESSIONB-1：组装前复活占位符章节——终审对任何失败章节一票否决整份成稿，
            # 而占位符可能只是章节时段的瞬时故障（限流/配额窗口）；此刻距故障已隔多章，
            # 再走一轮既有生成链路，把「确定性丢弃整份报告」换成「先重试一轮」。仍失败
            # 则保留占位符（终审语义不变）。旗标默认开；任何异常降级为不复活。
            if (failed_section_titles
                    and getattr(Config, "REPORT_RESURRECT_FAILED_SECTIONS", True)):
                try:
                    failed_section_titles = self._resurrect_failed_sections(
                        report_id, outline, failed_section_titles, generated_sections
                    )
                except Exception as _rz_err:  # noqa: BLE001 — 复活为旁路增强
                    logger.warning(f"失败章节复活尝试异常（忽略，保留占位符）: {_rz_err}")

            # 阶段3: 组装完整报告
            if progress_callback:
                progress_callback("generating", 95, "正在组装完整报告...")
            
            ReportManager.update_progress(
                report_id, "generating", 95, "正在组装完整报告...",
                completed_sections=completed_section_titles
            )
            
            # 使用ReportManager组装完整报告
            report.markdown_content = ReportManager.assemble_full_report(report_id, outline)
            report.status = ReportStatus.COMPLETED
            report.completed_at = datetime.now().isoformat()
            # 部分完成（partial）：把失败（写入占位符）的章节标题挂到 report，经 to_dict 暴露
            # failed_sections / partial。状态仍为 completed（前端以 status==='completed' 判定终态），
            # 由 partial 标记区分「完整」与「部分完成」。无失败章节时为空列表 → 与历史一致。
            report.failed_sections = list(failed_section_titles)

            # EXECPLAN2 I-3-0/I-9-1/I-3-1 + NEXTSTEPS P0-1/P2-1/P2-3: 最终化结构化预测。
            # 优先采用先于叙事推导的骨架（P0-1），否则从成稿抽取；随后红队自校准（P2-1）+
            # 引用接地审计 + 发布门（P2-3）→ forecast.json。默认开；失败仅告警（degrade-safe）。
            if getattr(Config, "REPORT_STRUCTURED_FORECAST", True):
                try:
                    self._finalize_structured_forecast(report_id, report.markdown_content,
                                                       report=report)
                except Exception as _fe:  # noqa: BLE001
                    logger.warning(f"结构化预测最终化失败（忽略，不影响主报告）: {_fe}")
                # QUALITY-OPT B1: prepend the deterministic Part-1 binary-forecast table so the
                # brief's headline deliverable always appears and always matches forecast.json.
                if getattr(Config, "FORECAST_EMIT_BINARY", True):
                    try:
                        self._prepend_binary_forecasts_section(report_id, report)
                    except Exception as _bs_err:  # noqa: BLE001
                        logger.warning(f"前置二元预测章节失败（忽略）: {_bs_err}")
                # VIZ-1：确定性可视化注入——由已落盘工件生成图表（charts/*.mmd + *.png +
                # viz_manifest.json），Mermaid 按章节关键词就地插入、未匹配图 + PNG 归入
                # 「Visual Annex」。放在 Part-1 前置之后、三部骨架之前，使图属于详细章节区
                # （随后被 Part 3 附录标题包住）。任何失败一行告警并跳过（图仍落盘，degrade-safe）。
                if getattr(Config, "REPORT_VISUALIZATIONS", True):
                    try:
                        self._inject_visualizations(report_id, report)
                    except Exception as _viz_err:  # noqa: BLE001
                        logger.warning(f"报告可视化注入失败（忽略，成稿不含图区）: {_viz_err}")
                # B2: 三部结构骨架——Part 1（二元预测表）之后插入 Part 2「框架与综合」
                # （一次 LLM 紧凑综合），再以 Part 3「附录：详细分析」标题包住既有章节。
                # 仅当 Part 1 已插入时生效；综合失败一行告警并跳过（绝不写占位符）。
                if getattr(Config, "REPORT_THREE_PART_SKELETON", True):
                    try:
                        self._apply_three_part_skeleton(report_id, report)
                    except Exception as _tp_err:  # noqa: BLE001
                        logger.warning(f"三部结构骨架套用失败（忽略，保留原结构）: {_tp_err}")
                # NEXTSTEPS P2-2: 追加确定性「如何验证本预测」章节（判定标准 + 观察指标）。
                if (getattr(Config, "REPORT_RESOLUTION_SECTION", True)
                        and self._forecast_spine and self._forecast_spine.get("scenarios")):
                    try:
                        self._append_resolution_section(report_id, report)
                    except Exception as _rs_err:  # noqa: BLE001
                        logger.warning(f"追加判定标准章节失败（忽略）: {_rs_err}")
                # RQ-2：语言纯度扫描——放在最后，让 Part-1 / 三部 / 判定章节等系统注入内容
                # 也一并纳入纯度检查。非 CJK 目标里的 CJK 片段（或反之）批量内联翻译。
                if getattr(Config, "REPORT_LANGUAGE_PURITY", True):
                    try:
                        self._apply_language_purity(report_id, report)
                    except Exception as _lp_err:  # noqa: BLE001
                        logger.warning(f"语言纯度扫描失败（忽略，保留原文）: {_lp_err}")

            # WAVE9：确定性编辑纪律 lint——所有修复/注入/纯度处理之后、双语翻译之前跑一遍
            # report_lint.lint_report（引用残留/边转储/旧模拟标签/孤悬归因行/重复句…），
            # lint 报告记入 forecast.json quality['lint']。放在 REPORT_STRUCTURED_FORECAST
            # 块之外，无结构化预测时同样生效。失败仅告警（degrade-safe）。
            if getattr(Config, "REPORT_EDITORIAL_LINT", True):
                try:
                    self._apply_report_lint(report_id, report)
                except Exception as _el_err:  # noqa: BLE001 — lint 为旁路品控
                    logger.warning(f"编辑 lint 失败（忽略，保留原文）: {_el_err}")

            # WAVE10（无缝引用）：引用最终化——正文 [S12] 记号解析为文末「References/参考来源」
            # 附录（只列被引用来源）+ citations.json 工件。放在语言纯度/lint 之后（附录不进
            # lint 扫描——参考条目天然 URL 密集）、双语翻译之前（附录随章节一并翻译）。
            # 无正文记号时失败可降级；有正文记号时附录/映射是引用可用性的组成部分，
            # 失败必须进入 failed-report 路径，不能发布一组死 [S#]。
            if getattr(Config, "REPORT_CITATION_FINALIZER", True):
                # GLM-run 2026-09-18: glm-5.3 output needs a couple more
                # fixed-point passes for the deterministic lint to go
                # byte-stable (semantic audit already converged; only lint
                # kept changing at the default 4). Env-tunable, hard-capped at
                # the method's own 8-pass ceiling.
                self._stabilize_publish_markdown(
                    report_id, report,
                    max_passes=int(os.environ.get(
                        "REPORT_PUBLISH_STABILIZER_PASSES", "6") or "6"),
                )

            # LOOP-010: authoritative, read-only audit of the exact publishable
            # Markdown.  Nothing below mutates the main report (bilingual output is
            # written to a separate file), so this fingerprint and its citation /
            # lint / publish-gate fields cannot go stale.  The audit never repairs or
            # rewrites Markdown; it only persists final_audit.json + forecast fields.
            if getattr(Config, "REPORT_FINAL_READ_ONLY_AUDIT", True):
                self._enforce_final_publish_audit(report_id, report)

            # BILINGUAL：在所有最终化/可视化/纯度处理之后（成稿已定型），自动生成另一语种版本
            # （英⇄中）。逐 H2 章节并发翻译，落 full_report.{en|zh}.md 并把 translations 条目写入
            # report（下方 save_report 持久化进 meta.json）。放在 REPORT_STRUCTURED_FORECAST 块之外，
            # 使其无论是否开启结构化预测都能运行。完全 degrade-safe：绝不改主报告，失败仅告警。
            if getattr(Config, "REPORT_BILINGUAL", True):
                try:
                    self._generate_bilingual_report(report_id, report)
                except Exception as _bl_err:  # noqa: BLE001 — 双语为旁路增强，失败不影响主报告
                    logger.warning(f"双语报告生成失败（忽略，不影响主报告）: {_bl_err}")

            # 报告整体仍标记为 completed（确实跑完了），但若有章节写入了失败占位符，
            # 必须显著告警，避免"假完成"掩盖失败章节（历史上是静默写入污染内容）。
            if failed_section_titles:
                logger.warning(
                    f"报告 {report_id} 完成，但有 {len(failed_section_titles)}/{total_sections} "
                    f"个章节生成失败（已写入占位符）: {failed_section_titles}。"
                    f"这些章节可在修复后单独重试。"
                )
            
            # 计算总耗时
            total_time_seconds = (datetime.now() - start_time).total_seconds()

            # EXECPLAN2 I-5-4: 汇总报告级遥测（per-section rollup + totals），写入完成日志、
            # telemetry.json 工件，并挂到 Report.telemetry 以便经 /report/<id> 与 by-simulation 暴露。
            telemetry_totals = None
            if _telemetry_on:
                try:
                    # 报告级 totals 取 stage='report' 切片并相对基线求差：
                    # 即便 run_id 与上游/其它报告共享，也只计入本报告这次的报告阶段花销。
                    def _diff(after: Dict[str, Any], before: Dict[str, Any], key: str) -> float:
                        try:
                            return float(after.get(key, 0) or 0) - float(before.get(key, 0) or 0)
                        except (TypeError, ValueError):
                            return 0.0
                    snap_after = self._meter_stage_total(_telemetry_run_id, "report")
                    telemetry_totals = {
                        "report_id": report_id,
                        "run_id": _telemetry_run_id,
                        "total_sections": total_sections,
                        "failed_sections": len(failed_section_titles),
                        "duration_s": round(total_time_seconds, 2),
                        "llm_calls": max(0, int(_diff(snap_after, _report_stage_before, "calls"))),
                        "tokens": max(0, int(_diff(snap_after, _report_stage_before, "total_tokens"))),
                        "prompt_tokens": max(0, int(_diff(snap_after, _report_stage_before, "prompt_tokens"))),
                        "completion_tokens": max(0, int(_diff(snap_after, _report_stage_before, "completion_tokens"))),
                        "est_cost_usd": round(max(0.0, _diff(snap_after, _report_stage_before, "cost_usd")), 6),
                        "latency_ms": round(max(0.0, _diff(snap_after, _report_stage_before, "latency_ms")), 1),
                        "tool_calls": sum(int(s.get("tool_calls", 0) or 0) for s in section_rollup),
                    }
                    report.telemetry = {"totals": telemetry_totals, "sections": section_rollup}
                    try:
                        tpath = os.path.join(
                            ReportManager._get_report_folder(report_id), "telemetry.json"
                        )
                        write_text_atomic(
                            tpath, json.dumps(report.telemetry, ensure_ascii=False, indent=2)
                        )
                    except Exception as _twe:  # noqa: BLE001 — 工件落盘失败不影响主流程
                        logger.warning(f"telemetry.json 写入失败（忽略）: {_twe}")
                    logger.info(
                        f"报告遥测: {report_id} 共 {telemetry_totals['llm_calls']} 次 LLM 调用, "
                        f"{telemetry_totals['tokens']} tokens, "
                        f"~${telemetry_totals['est_cost_usd']:.4f}, "
                        f"{telemetry_totals['duration_s']}s, {total_sections} 章"
                    )
                except Exception as _te:  # noqa: BLE001 — 遥测汇总失败不得影响报告完成
                    logger.warning(f"报告级遥测汇总失败（忽略）: {_te}")
                    telemetry_totals = None

            # 记录报告完成日志
            if self.report_logger:
                self.report_logger.log_report_complete(
                    total_sections=total_sections,
                    total_time_seconds=total_time_seconds,
                    section_rollup=(section_rollup if _telemetry_on else None),
                    totals=telemetry_totals,
                )

            # 保存最终报告
            # XRUN-7: 终态 progress.json 如实记账——占位符章节单列 failed_sections（并从
            # completed_sections 剔除），附 forecast.json 是否产出；status 语义保持不变。
            _forecast_ok = os.path.exists(
                os.path.join(ReportManager._get_report_folder(report_id), "forecast.json")
            )
            ReportManager.save_report(report)
            ReportManager.update_progress(
                report_id, "completed", 100, "报告生成完成",
                completed_sections=completed_section_titles,
                failed_sections=failed_section_titles,
                forecast_ok=_forecast_ok
            )
            # EVAL-1: 账本提交放在收尾步骤（进度回调/日志/关闭控制台）之后、return 之前：
            # 须在 save_report/update_progress 之后（publication_status 读 meta.json）；收尾步骤
            # 抛普通异常会让失败分支把报告改记 FAILED（不可发布）→ 只留 unpublished_terminal 行，
            # 绝不让计分主行归属一份未发布报告。取消/熔断（BaseException）不经失败分支，
            # 报告仍以 completed 落盘可发布 → 照常入账后再上抛。
            try:
                if progress_callback:
                    progress_callback("completed", 100, "报告生成完成")

                logger.info(f"报告生成完成: {report_id}")

                # 关闭控制台日志记录器
                if self.console_logger:
                    self.console_logger.close()
                    self.console_logger = None
            except Exception:  # 普通异常 → 下方失败分支（报告改记 FAILED，只记 unpublished 行）
                raise
            except BaseException:  # 取消/熔断：报告已按 completed 发布 → 入账后上抛
                self._commit_forecast_ledger(report_id, report)
                raise

            self._commit_forecast_ledger(report_id, report)
            return report
            
        except Exception as e:
            logger.error(f"报告生成失败: {str(e)}")
            report.status = ReportStatus.FAILED
            report.completed_at = None
            report.error = str(e)
            
            # 记录错误日志
            if self.report_logger:
                self.report_logger.log_error(str(e), "failed")
            
            # 保存失败状态
            try:
                ReportManager.save_report(report)
                ReportManager.update_progress(
                    report_id, "failed", -1, f"报告生成失败: {str(e)}",
                    completed_sections=completed_section_titles
                )
            except Exception:
                pass  # 忽略保存失败的错误
            # EVAL-1: 失败终态同样留痕——unpublished_terminal 行（不计分）让校准分母可审计。
            self._commit_forecast_ledger(report_id, report, error=str(e))
            
            # 关闭控制台日志记录器
            if self.console_logger:
                self.console_logger.close()
                self.console_logger = None

            return report

        finally:
            # EXECPLAN2 I-5-4: 还原进入本方法前的 LLM 计量上下文，避免污染复用线程/调用方。
            if _telemetry_on and _prev_run_ctx is not None:
                try:
                    set_run_context(_prev_run_ctx[0], _prev_run_ctx[1])
                except Exception:  # noqa: BLE001 — 还原失败仅影响后续计量归属，不影响报告
                    pass

    def _resolve_report_cached(self) -> Optional[Report]:
        """EXECPLAN2 F-7-3: 解析本 simulation 的最新报告并在实例级记忆，避免重复扫描。"""
        if self._cached_report is not self._cached_report_sentinel:
            return self._cached_report
        report = ReportManager.get_report_by_simulation(self.simulation_id)
        self._cached_report = report
        return report

    def chat(
        self,
        message: str,
        chat_history: List[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        与Report Agent对话
        
        在对话中Agent可以自主调用检索工具来回答问题
        
        Args:
            message: 用户消息
            chat_history: 对话历史
            
        Returns:
            {
                "response": "Agent回复",
                "tool_calls": [调用的工具列表],
                "sources": [信息来源]
            }
        """
        logger.info(f"Report Agent对话: {message[:50]}...")
        
        chat_history = chat_history or []
        
        # 获取已生成的报告内容
        report_content = ""
        try:
            report = self._resolve_report_cached()  # EXECPLAN2 F-7-3: 实例级记忆 + 索引快路径
            if (report and report.markdown_content
                    and ReportManager.is_publishable(report.report_id)):
                # 限制报告长度，避免上下文过长（放宽到 40000 字以覆盖更长的报告）
                report_content = report.markdown_content[:40000]
                if len(report.markdown_content) > 40000:
                    report_content += "\n\n... [报告内容已截断] ..."
        except Exception as e:
            logger.warning(f"获取报告内容失败: {e}")
        
        system_prompt = CHAT_SYSTEM_PROMPT_TEMPLATE.format(
            simulation_requirement=self.simulation_requirement,
            report_content=report_content if report_content else "（暂无报告）",
            tools_description=self._get_tools_description(),
        )

        # 构建消息
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加历史对话
        for h in chat_history[-10:]:  # 限制历史长度
            messages.append(h)
        
        # 添加用户消息
        messages.append({
            "role": "user", 
            "content": message
        })
        
        # ReACT循环（简化版）
        tool_calls_made = []
        max_iterations = 2  # 减少迭代轮数
        
        for _iteration in range(max_iterations):
            response = self.llm.chat(
                messages=messages,
                temperature=0.5
            )
            
            # 解析工具调用
            tool_calls = self._parse_tool_calls(response)
            
            if not tool_calls:
                # 没有工具调用，直接返回响应
                clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', response, flags=re.DOTALL)
                clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
                
                return {
                    "response": clean_response.strip(),
                    "tool_calls": tool_calls_made,
                    "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
                }
            
            # 执行工具调用（限制数量）
            tool_results = []
            for call in tool_calls[:1]:  # 每轮最多执行1次工具调用
                if len(tool_calls_made) >= self.MAX_TOOL_CALLS_PER_CHAT:
                    break
                result = self._execute_tool(call["name"], call.get("parameters", {}))
                tool_results.append({
                    "tool": call["name"],
                    "result": result[:1500]  # 限制结果长度
                })
                tool_calls_made.append(call)
            
            # 将结果添加到消息
            messages.append({"role": "assistant", "content": response})
            observation = "\n".join([f"[{r['tool']}结果]\n{r['result']}" for r in tool_results])
            messages.append({
                "role": "user",
                "content": observation + CHAT_OBSERVATION_SUFFIX
            })
        
        # 达到最大迭代，获取最终响应
        final_response = self.llm.chat(
            messages=messages,
            temperature=0.5
        )
        
        # 清理响应
        clean_response = re.sub(r'<tool_call>.*?</tool_call>', '', final_response, flags=re.DOTALL)
        clean_response = re.sub(r'\[TOOL_CALL\].*?\)', '', clean_response)
        
        return {
            "response": clean_response.strip(),
            "tool_calls": tool_calls_made,
            "sources": [tc.get("parameters", {}).get("query", "") for tc in tool_calls_made]
        }


class ReportManager:
    """
    报告管理器
    
    负责报告的持久化存储和检索
    
    文件结构（分章节输出）：
    reports/
      {report_id}/
        meta.json          - 报告元信息和状态
        outline.json       - 报告大纲
        progress.json      - 生成进度
        section_01.md      - 第1章节
        section_02.md      - 第2章节
        ...
        full_report.md     - 完整报告
    """
    
    # 报告存储目录
    REPORTS_DIR = os.path.join(Config.UPLOAD_FOLDER, 'reports')

    # EXECPLAN2 F-7-3: simulation_id -> [report_id, ...] 轻量索引文件，
    # 让 get_report_by_simulation 免去对全部报告文件夹的 O(N) 全量扫描 + 全文反序列化。
    _SIM_INDEX_FILENAME = "_sim_index.json"
    # 串行化索引文件的读改写（同进程内）
    _sim_index_lock = threading.Lock()
    # Existing-report translation retries are user-triggerable.  A per-variant
    # lock prevents duplicate model spend and conflicting metadata updates while
    # allowing unrelated reports to translate concurrently.
    _translation_locks_guard = threading.Lock()
    _translation_locks: Dict[Tuple[str, str], threading.Lock] = {}
    # PDF builds are publication work, not a stateless view transform.  Serialize
    # each report/language bundle so concurrent requests cannot share temporary
    # sources, replace one another's output, or validate a half-written cache.
    _pdf_locks_guard = threading.Lock()
    _pdf_locks: Dict[Tuple[str, str], threading.Lock] = {}
    _PDF_MANIFEST_SCHEMA_VERSION = 1
    _PDF_RENDERER_VERSION = "report-pdf-v3-a4-font-and-glyph-gated"

    @classmethod
    def _ensure_reports_dir(cls):
        """确保报告根目录存在"""
        os.makedirs(cls.REPORTS_DIR, exist_ok=True)
    
    @classmethod
    def _get_report_folder(cls, report_id: str) -> str:
        """获取报告文件夹路径（INFRA-10：id 经 contained_child 校验，非法/逃逸 id 抛 UnsafeIdError）。

        返回值与 os.path.join(REPORTS_DIR, report_id) 逐字节相同；收容性只按 realpath 判定。
        """
        return contained_child(cls.REPORTS_DIR, report_id, "report")

    @classmethod
    def _get_legacy_report_file(cls, report_id: str, ext: str) -> str:
        """旧版扁平布局 reports/{report_id}.{ext}：先 safe_id 校验 id，再拼带后缀的文件名。"""
        return os.path.join(cls.REPORTS_DIR, f"{safe_id(report_id, 'report')}.{ext}")
    
    @classmethod
    def _ensure_report_folder(cls, report_id: str) -> str:
        """确保报告文件夹存在并返回路径"""
        folder = cls._get_report_folder(report_id)
        os.makedirs(folder, exist_ok=True)
        return folder
    
    @classmethod
    def _get_report_path(cls, report_id: str) -> str:
        """获取报告元信息文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "meta.json")
    
    @classmethod
    def _get_report_markdown_path(cls, report_id: str) -> str:
        """获取完整报告Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "full_report.md")

    @classmethod
    def load_structured_forecast(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """Load an optional forecast only when the final audit seals its bytes.

        Legacy reports may be publishable without ``forecast.json``.  Merely
        finding a parseable sidecar beside one of those reports is not proof
        that it belongs to the audited publication bundle, so callers receive
        ``None`` unless the current hard-passed audit explicitly records the
        artifact as present and valid and its SHA-256 matches the exact bytes.
        Customer-facing callers must additionally apply ``publication_status``
        to the report itself before exposing the returned object.
        """
        try:
            # INFRA-10: an unsafe id raises UnsafeIdError (a ValueError) -> "not found".
            audit_path = cls._get_report_final_audit_path(report_id)
            with open(audit_path, encoding="utf-8") as handle:
                audit = json.load(handle)
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(audit, dict):
            return None
        if audit.get("hard_passed") is not True or list(audit.get("hard_issues") or []):
            return None
        required_policy = int(getattr(
            Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3
        ))
        if audit.get("policy_version") != required_policy:
            return None
        structured = audit.get("structured_forecast")
        if not isinstance(structured, dict):
            return None
        if structured.get("present") is not True or structured.get("valid") is not True:
            return None
        expected_sha = audit.get("forecast_sha256")
        if not isinstance(expected_sha, str) or not expected_sha:
            return None

        path = os.path.join(cls._get_report_folder(report_id), "forecast.json")
        try:
            with open(path, "rb") as handle:
                raw = handle.read()
            if hashlib.sha256(raw).hexdigest() != expected_sha:
                return None
            forecast = json.loads(raw)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None
        return forecast if isinstance(forecast, dict) else None

    # BILINGUAL：合法目标语种代码（同时用于路径构造与 API 校验，单一真源）。
    _TRANSLATION_LANGS = ("en", "zh")

    @classmethod
    def _get_report_translation_path(cls, report_id: str, lang: str) -> str:
        """获取双语版本 Markdown 文件路径 reports/{id}/full_report.<lang>.md（lang ∈ {en, zh}）。"""
        return os.path.join(cls._get_report_folder(report_id), f"full_report.{lang}.md")

    @classmethod
    def _get_report_citations_path(
        cls, report_id: str, lang: Optional[str] = None
    ) -> str:
        """Return the primary or language-isolated citation artifact path."""
        filename = (
            f"citations.{lang}.json"
            if lang in cls._TRANSLATION_LANGS else "citations.json"
        )
        return os.path.join(cls._get_report_folder(report_id), filename)

    @classmethod
    def _get_report_final_audit_path(
        cls, report_id: str, lang: Optional[str] = None
    ) -> str:
        """Return the primary or language-isolated final-audit artifact path."""
        filename = (
            f"final_audit.{lang}.json"
            if lang in cls._TRANSLATION_LANGS else "final_audit.json"
        )
        return os.path.join(cls._get_report_folder(report_id), filename)

    @classmethod
    def _get_translation_runtime_status_path(cls, report_id: str, lang: str) -> str:
        return os.path.join(
            cls._get_report_folder(report_id), f"translation_status.{lang}.json"
        )

    @classmethod
    def _set_translation_runtime_status(
        cls,
        report_id: str,
        lang: str,
        status: str,
        **fields: Any,
    ) -> None:
        if lang not in cls._TRANSLATION_LANGS:
            return
        existing = cls._load_translation_runtime_status(report_id, lang) or {}
        payload = dict(existing) if isinstance(existing, dict) else {}
        updated_at = datetime.now(timezone.utc).isoformat()
        payload.update({
            "schema_version": 1,
            "report_id": report_id,
            "lang": lang,
            "status": status,
            "updated_at": updated_at,
        })
        if status in {"pending", "processing", "generating"}:
            payload["heartbeat_at"] = updated_at
            payload.pop("issues", None)
        elif status in {"failed", "available", "completed"}:
            payload["progress"] = int(fields.get("progress", 100) or 100)
        payload.update({key: value for key, value in fields.items() if value is not None})
        write_json_atomic(cls._get_translation_runtime_status_path(report_id, lang), payload)

    @classmethod
    def _load_translation_runtime_status(
        cls, report_id: str, lang: str
    ) -> Optional[Dict[str, Any]]:
        try:
            with open(
                cls._get_translation_runtime_status_path(report_id, lang),
                encoding="utf-8",
            ) as handle:
                payload = json.load(handle)
        except (OSError, ValueError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("report_id") != report_id or payload.get("lang") != lang:
            return None
        return payload

    @classmethod
    def _translation_lock_for(cls, report_id: str, lang: str) -> threading.Lock:
        key = (str(report_id), str(lang))
        with cls._translation_locks_guard:
            lock = cls._translation_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                cls._translation_locks[key] = lock
            return lock

    @classmethod
    @contextmanager
    def _translation_generation_lease(cls, report_id: str, lang: str):
        """Serialize reservation and generation across threads and processes."""
        lock = cls._translation_lock_for(report_id, lang)
        lock_path = cls._get_translation_runtime_status_path(report_id, lang) + ".lock"
        with lock, cls._advisory_file_lock(lock_path):
            yield

    @classmethod
    def _pdf_lock_for(cls, report_id: str, lang: Optional[str]) -> threading.Lock:
        key = (str(report_id), str(lang or "primary"))
        with cls._pdf_locks_guard:
            lock = cls._pdf_locks.get(key)
            if lock is None:
                lock = threading.Lock()
                cls._pdf_locks[key] = lock
            return lock

    @classmethod
    def translation_status(
        cls,
        report_id: str,
        lang: Optional[str] = None,
        report: Optional[Report] = None,
    ) -> Dict[str, Any]:
        """Describe one report's deterministic language-variant state.

        A failed audit remains visible after its rejected Markdown is removed, so
        the UI can offer an honest retry instead of silently hiding the feature.
        Availability is derived from the publication barrier, never from metadata
        or file existence alone.
        """
        report = report or cls.get_report(report_id)
        result: Dict[str, Any] = {
            "report_id": report_id,
            "source_lang": None,
            "target_lang": None,
            "requested_lang": lang,
            "status": "missing",
            "available": False,
            "can_generate": False,
            "issues": [],
        }
        if report is None:
            result["status"] = "not_found"
            result["issues"] = ["report does not exist"]
            return result

        source_lang, target_lang, _target_name = ReportAgent._detect_translation_target(
            report.markdown_content or ""
        )
        result["source_lang"] = source_lang
        result["target_lang"] = target_lang
        requested = lang or target_lang
        result["requested_lang"] = requested
        if requested not in cls._TRANSLATION_LANGS:
            result["status"] = "unsupported"
            result["issues"] = ["report language or requested target is unsupported"]
            return result
        if requested != target_lang:
            result["status"] = "source_language"
            result["available"] = requested == source_lang
            result["issues"] = ["requested language is not this report's translation target"]
            return result

        source_sha = hashlib.sha256(
            (report.markdown_content or "").encode("utf-8")
        ).hexdigest()
        result["source_markdown_sha256"] = source_sha

        primary = cls.publication_status(report_id)
        result["can_generate"] = bool(
            primary.get("publishable") and getattr(Config, "REPORT_BILINGUAL", True)
        )
        if cls.is_publishable(report_id, requested):
            result["status"] = "available"
            result["available"] = True
            result["issues"] = []
            try:
                with open(
                    cls._get_report_translation_path(report_id, requested), "rb"
                ) as handle:
                    result["markdown_sha256"] = hashlib.sha256(handle.read()).hexdigest()
            except OSError:
                pass
            result["translation"] = {
                "report_id": report_id,
                "lang": requested,
                "source_lang": source_lang,
                "path": f"full_report.{requested}.md",
                "markdown_sha256": result.get("markdown_sha256"),
                "source_markdown_sha256": source_sha,
                "final_audit_path": f"final_audit.{requested}.json",
                "final_audit_sha256": cls._sha256_file(
                    cls._get_report_final_audit_path(report_id, requested)
                ),
                "audit_verified": True,
                "available": True,
            }
            return result

        runtime = cls._load_translation_runtime_status(report_id, requested)
        if (isinstance(runtime, dict)
                and runtime.get("source_markdown_sha256") == source_sha):
            runtime_status = str(runtime.get("status") or "").lower()
            if runtime_status in {"pending", "processing", "generating"}:
                stale = False
                try:
                    updated = datetime.fromisoformat(
                        str(runtime.get("updated_at") or "").replace("Z", "+00:00")
                    )
                    if updated.tzinfo is None:
                        updated = updated.replace(tzinfo=timezone.utc)
                    stale = (datetime.now(timezone.utc) - updated).total_seconds() > 900
                except (TypeError, ValueError):
                    stale = True
                if not stale:
                    result["status"] = "generating"
                    result["can_generate"] = False
                    result["issues"] = []
                    result["message"] = str(runtime.get("message") or "")
                    result["progress"] = int(runtime.get("progress") or 0)
                    for key in ("task_id", "owner", "heartbeat_at", "updated_at"):
                        if runtime.get(key) is not None:
                            result[key] = runtime.get(key)
                    return result
                result["status"] = "interrupted"
                result["issues"] = ["previous translation attempt stopped before completion"]
                for key in ("task_id", "owner", "heartbeat_at", "updated_at"):
                    if runtime.get(key) is not None:
                        result[key] = runtime.get(key)
                return result
            if runtime_status == "failed":
                result["status"] = "failed"
                result["issues"] = [
                    str(item) for item in (runtime.get("issues") or []) if item
                ][:12]
                result["progress"] = int(runtime.get("progress") or 100)
                result["message"] = str(runtime.get("message") or "")
                for key in ("task_id", "owner", "heartbeat_at", "updated_at"):
                    if runtime.get(key) is not None:
                        result[key] = runtime.get(key)

        audit_path = cls._get_report_final_audit_path(report_id, requested)
        try:
            with open(audit_path, encoding="utf-8") as handle:
                audit = json.load(handle)
        except (OSError, ValueError, TypeError):
            audit = None
        if isinstance(audit, dict):
            audit_source_sha = audit.get("source_markdown_sha256")
            if audit_source_sha and audit_source_sha != source_sha:
                result["status"] = "stale"
                result["issues"] = ["translation audit belongs to older primary report bytes"]
            elif audit.get("hard_passed") is False:
                result["status"] = "failed"
                result["issues"] = [
                    str(item) for item in (audit.get("issues") or []) if item
                ][:12]
            else:
                result["status"] = "invalid"
                result["issues"] = list(
                    cls.publication_status(report_id, requested).get("reasons") or []
                )[:12]
        elif not primary.get("publishable"):
            result["status"] = "blocked"
            result["issues"] = list(primary.get("reasons") or [])[:12]
        elif not getattr(Config, "REPORT_BILINGUAL", True):
            result["status"] = "disabled"
            result["issues"] = ["bilingual report generation is disabled"]
        return result

    @classmethod
    def _persist_translation_metadata(
        cls, report_id: str, translations: Optional[List[Dict[str, Any]]]
    ) -> None:
        """Update only translation metadata while preserving all report fields."""
        path = cls._get_report_path(report_id)
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
        if not isinstance(payload, dict):
            raise ValueError("meta.json is not an object")
        if translations:
            payload["translations"] = translations
        else:
            payload.pop("translations", None)
        write_json_atomic(path, payload)

    @classmethod
    def generate_translation_variant(
        cls,
        report_id: str,
        lang: str,
        llm_client: Optional[LLMClient] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
    ) -> Dict[str, Any]:
        """Generate one missing language sidecar for an already published report.

        The primary report is immutable.  The same fail-closed translator and
        per-language audit used at report completion are reused, then only the
        `translations` metadata field is merged into the existing `meta.json`.
        """
        lang = str(lang or "").strip().lower()
        if lang not in cls._TRANSLATION_LANGS:
            raise ValueError("unsupported translation language")
        with cls._translation_generation_lease(report_id, lang):
            report = cls.get_report(report_id)
            if report is None:
                raise FileNotFoundError(f"report does not exist: {report_id}")
            if not cls.is_publishable(report_id):
                raise ValueError("primary report is not publishable")
            source_lang, target_lang, _target_name = ReportAgent._detect_translation_target(
                report.markdown_content or ""
            )
            if not source_lang or target_lang != lang:
                raise ValueError("requested language is not this report's translation target")
            current = cls.translation_status(report_id, lang, report=report)
            if current.get("available"):
                return current

            primary_sha = hashlib.sha256(
                (report.markdown_content or "").encode("utf-8")
            ).hexdigest()
            worker = ReportAgent.__new__(ReportAgent)
            worker.llm = llm_client or LLMClient()
            worker.output_language = "Chinese" if source_lang == "zh" else "English"
            worker.simulation_id = report.simulation_id
            worker.graph_id = report.graph_id
            worker._forecast_spine = cls.load_structured_forecast(report_id)
            worker._generate_bilingual_report(
                report_id,
                report,
                progress_callback=progress_callback,
            )

            # Refuse to bind a variant if the primary changed during the model call.
            refreshed = cls.get_report(report_id)
            refreshed_sha = hashlib.sha256(
                ((refreshed.markdown_content if refreshed else "") or "").encode("utf-8")
            ).hexdigest()
            if refreshed_sha != primary_sha:
                cls._safe_unlink(
                    cls._get_report_translation_path(report_id, lang),
                    cls._get_report_pdf_path(report_id, lang),
                    cls._get_report_pdf_manifest_path(report_id, lang),
                    cls._get_report_citations_path(report_id, lang),
                )
                raise RuntimeError("primary report changed during translation")

            cls._persist_translation_metadata(report_id, report.translations)
            return cls.translation_status(report_id, lang)

    @classmethod
    def publication_status(
        cls, report_id: str, lang: Optional[str] = None
    ) -> Dict[str, Any]:
        """Verify the exact bytes are safe for customer-facing publication.

        File existence is never sufficient.  The report must be completed with
        no failed sections, have a passing final audit, and the audit fingerprint
        must match the current Markdown bytes.  Language variants additionally
        require the primary report and their isolated citation artifact.
        """
        lang = lang if lang in cls._TRANSLATION_LANGS else None
        result: Dict[str, Any] = {
            "report_id": report_id,
            "lang": lang,
            "publishable": False,
            "reasons": [],
        }
        try:
            with open(cls._get_report_path(report_id), encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError, TypeError):
            result["reasons"].append("meta.json missing or invalid")
            return result
        if not isinstance(meta, dict) or meta.get("status") != ReportStatus.COMPLETED.value:
            result["reasons"].append("report status is not completed")
        failed_sections = list(meta.get("failed_sections") or [])
        if failed_sections or meta.get("partial"):
            result["reasons"].append("report contains failed or partial sections")

        primary: Optional[Dict[str, Any]] = None
        if lang:
            primary = cls.publication_status(report_id)
            if not primary.get("publishable"):
                result["reasons"].append("primary report is not publishable")
            md_path = cls._get_report_translation_path(report_id, lang)
        else:
            md_path = cls._get_report_markdown_path(report_id)
        try:
            with open(md_path, encoding="utf-8") as handle:
                markdown = handle.read()
        except OSError:
            result["reasons"].append("Markdown artifact missing")
            return result
        markdown_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        result["markdown_sha256"] = markdown_sha
        if not lang:
            source_lang, _target_lang, _target_name = ReportAgent._detect_translation_target(
                markdown
            )
            result["language"] = source_lang

        audit_path = cls._get_report_final_audit_path(report_id, lang)
        try:
            with open(audit_path, encoding="utf-8") as handle:
                audit = json.load(handle)
        except (OSError, ValueError, TypeError):
            result["reasons"].append("final audit missing or invalid")
            return result
        if not isinstance(audit, dict) or audit.get("hard_passed") is not True:
            result["reasons"].append("final audit did not hard-pass")
        required_policy = int(getattr(
            Config, "REPORT_FINAL_AUDIT_POLICY_VERSION", 3
        ))
        if audit.get("policy_version") != required_policy:
            result["reasons"].append(
                "final audit policy is stale; deterministic replay required"
            )
        if list(audit.get("hard_issues") or []):
            result["reasons"].append("final audit contains hard issues")
        if audit.get("markdown_sha256") != markdown_sha:
            result["reasons"].append("final audit fingerprint does not match Markdown")
        gate = audit.get("publish_gate") or {}
        if gate.get("enabled") and gate.get("passed") is not True:
            result["reasons"].append("professional publication gate did not pass")
        if not lang:
            structured = audit.get("structured_forecast") or {}
            if structured.get("required") and not structured.get("valid"):
                result["reasons"].append("structured forecast contract is invalid")
            scenario_contract = audit.get("scenario_contract") or {}
            if structured.get("required") and scenario_contract.get("valid") is not True:
                result["reasons"].append("scenario contract is missing or invalid")
            citation_artifacts = audit.get("citation_artifacts") or {}
            if citation_artifacts.get("required") and not citation_artifacts.get("passed"):
                result["reasons"].append("citation artifact contract is invalid")
            if structured.get("required") or structured.get("present"):
                forecast_path = os.path.join(
                    cls._get_report_folder(report_id), "forecast.json"
                )
                try:
                    with open(forecast_path, "rb") as handle:
                        forecast_sha = hashlib.sha256(handle.read()).hexdigest()
                except OSError:
                    forecast_sha = None
                result["forecast_sha256"] = forecast_sha
                if not forecast_sha or audit.get("forecast_sha256") != forecast_sha:
                    result["reasons"].append(
                        "final audit fingerprint does not match structured forecast"
                    )
        else:
            primary_sha = str((primary or {}).get("markdown_sha256") or "")
            source_lang = str((primary or {}).get("language") or "")
            if audit.get("report_id") != report_id:
                result["reasons"].append("language audit belongs to another report")
            if audit.get("language") != lang:
                result["reasons"].append("language audit target does not match request")
            if audit.get("source_language") != source_lang:
                result["reasons"].append("language audit source language does not match primary")
            if not primary_sha or audit.get("source_markdown_sha256") != primary_sha:
                result["reasons"].append(
                    "language audit source fingerprint does not match primary"
                )
            citations_path = cls._get_report_citations_path(report_id, lang)
            try:
                with open(citations_path, encoding="utf-8") as handle:
                    citations = json.load(handle)
                if not isinstance(citations, dict):
                    raise ValueError("citation map is not an object")
            except (OSError, ValueError, TypeError):
                result["reasons"].append("language-isolated citation map is missing or invalid")
                citations = None
            if isinstance(citations, dict):
                if citations.get("report_id") != report_id:
                    result["reasons"].append(
                        "language-isolated citation map belongs to another report"
                    )
                if citations.get("language") != lang:
                    result["reasons"].append(
                        "language-isolated citation target does not match request"
                    )
                if citations.get("source_language") != source_lang:
                    result["reasons"].append(
                        "language-isolated citation source does not match primary"
                    )
                if citations.get("source_markdown_sha256") != primary_sha:
                    result["reasons"].append(
                        "language-isolated citation source fingerprint does not match primary"
                    )
                if citations.get("markdown_sha256") != markdown_sha:
                    result["reasons"].append(
                        "language-isolated citation fingerprint does not match Markdown"
                    )
            entries = [
                entry for entry in (meta.get("translations") or [])
                if isinstance(entry, dict) and entry.get("lang") == lang
            ]
            identity_match = any(
                entry.get("report_id") == report_id
                and entry.get("source_lang") == source_lang
                and entry.get("source_markdown_sha256") == primary_sha
                and entry.get("markdown_sha256") == markdown_sha
                and entry.get("path") == f"full_report.{lang}.md"
                and entry.get("available") is True
                for entry in entries
            )
            if not identity_match:
                result["reasons"].append(
                    "translation metadata is missing the exact report/source identity"
                )
        result["publishable"] = not result["reasons"]
        return result

    @classmethod
    def is_publishable(cls, report_id: str, lang: Optional[str] = None) -> bool:
        return bool(cls.publication_status(report_id, lang).get("publishable"))

    # ── PDF-1: full_report.md → full_report.pdf（pandoc+xelatex，回退 PyMuPDF；按 mtime 缓存）──

    # 已知的 pandoc / xelatex 绝对路径（Homebrew / MacTeX）——运行时校验存在，缺失回退 PATH
    # 查找，再缺失则整条 pandoc 路径不可用（触发 PyMuPDF 回退）。单一真源，避免散落。
    _PANDOC_BIN = "/opt/homebrew/bin/pandoc"
    _XELATEX_BIN = "/Library/TeX/texbin/xelatex"

    @classmethod
    def _get_report_pdf_path(cls, report_id: str, lang: Optional[str] = None) -> str:
        """PDF 导出产物路径。lang ∈ {en, zh} → full_report.<lang>.pdf（双语版 PDF）；
        否则 → full_report.pdf（主报告，行为与历史一致）。"""
        name = f"full_report.{lang}.pdf" if lang in cls._TRANSLATION_LANGS else "full_report.pdf"
        return os.path.join(cls._get_report_folder(report_id), name)

    @classmethod
    def _get_report_pdf_manifest_path(
        cls, report_id: str, lang: Optional[str] = None
    ) -> str:
        return cls._get_report_pdf_path(report_id, lang) + ".manifest.json"

    @staticmethod
    def _is_pdf_file(path: str) -> bool:
        """校验文件确为 PDF（首字节 %PDF-）。pandoc 若因输出格式误判吐出 HTML/文本，此门拦截
        并触发回退，避免把非 PDF 当成功。读失败 → False。"""
        try:
            with open(path, "rb") as f:
                return f.read(5) == b"%PDF-"
        except OSError:
            return False

    @staticmethod
    def _sha256_file(path: str) -> Optional[str]:
        try:
            digest = hashlib.sha256()
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            return digest.hexdigest()
        except OSError:
            return None

    @staticmethod
    def _path_fingerprint(path: Optional[str]) -> Optional[Dict[str, Any]]:
        if not path:
            return None
        try:
            stat = os.stat(path)
        except OSError:
            return None
        return {
            "path": os.path.realpath(path),
            "size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
        }

    @staticmethod
    def _match_pdf_font(candidates: List[str]) -> Optional[Dict[str, Any]]:
        """Resolve the first exact installed font family and its backing file."""
        import shutil
        import subprocess

        fc_match = shutil.which("fc-match")
        for candidate in [str(item).strip() for item in candidates if str(item).strip()]:
            if fc_match:
                try:
                    raw = subprocess.check_output(
                        [fc_match, "-f", "%{family[0]}|%{file}", candidate],
                        timeout=10,
                    ).decode("utf-8", "replace")
                    family, path = (raw.split("|", 1) + [""])[:2]
                    if family.strip().casefold() == candidate.casefold() and os.path.exists(path):
                        return {"family": family.strip(), "file": os.path.realpath(path)}
                except Exception:  # noqa: BLE001 - try the next portable family
                    pass
            try:
                from matplotlib import font_manager
                path = font_manager.findfont(candidate, fallback_to_default=False)
                if path and os.path.exists(path):
                    return {"family": candidate, "file": os.path.realpath(path)}
            except Exception:  # noqa: BLE001 - fontconfig is optional
                pass
        return None

    @classmethod
    def _resolve_pdf_fonts(cls) -> Dict[str, Optional[Dict[str, Any]]]:
        configured_main = str(getattr(Config, "REPORT_PDF_MAIN_FONT", "") or "")
        configured_cjk = str(getattr(Config, "REPORT_PDF_CJK_FONT", "") or "")
        configured_mono = str(getattr(Config, "REPORT_PDF_MONO_FONT", "") or "")
        return {
            "main": cls._match_pdf_font([
                configured_main, "DejaVu Sans", "Noto Sans", "Arial Unicode MS",
            ]),
            "cjk": cls._match_pdf_font([
                configured_cjk, "Noto Sans CJK SC", "Source Han Sans SC",
                "PingFang SC", "Arial Unicode MS",
            ]),
            "mono": cls._match_pdf_font([
                configured_mono, "DejaVu Sans Mono", "Noto Sans Mono CJK SC", "Menlo",
            ]),
        }

    @classmethod
    def _pdf_renderer_fingerprint(cls) -> Dict[str, Any]:
        resolved = cls._resolve_pandoc()
        fonts = cls._resolve_pdf_fonts()
        return {
            "version": cls._PDF_RENDERER_VERSION,
            "pandoc": cls._path_fingerprint(resolved[0] if resolved else None),
            "xelatex": cls._path_fingerprint(resolved[1] if resolved else None),
            "fonts": {
                key: ({
                    "family": value.get("family"),
                    "file": cls._path_fingerprint(value.get("file")),
                } if isinstance(value, dict) else None)
                for key, value in fonts.items()
            },
            "page_size": "a4",
            "margin": "2.5cm",
            "toc": True,
            "citation_footnotes": bool(getattr(
                Config, "REPORT_PDF_CITATION_FOOTNOTES", True
            )),
        }

    @classmethod
    def _pdf_input_fingerprint(
        cls, report_id: str, lang: Optional[str], md_path: str, folder: str
    ) -> Dict[str, Any]:
        audit_path = cls._get_report_final_audit_path(report_id, lang)
        citations_path = cls._get_report_citations_path(report_id, lang)
        charts_dir = os.path.realpath(os.path.join(folder, "charts"))
        chart_rows: List[Dict[str, str]] = []
        allowed = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp", ".mmd"}
        if os.path.isdir(charts_dir) and not os.path.islink(charts_dir):
            for root, dirs, files in os.walk(charts_dir, followlinks=False):
                dirs[:] = [
                    name for name in dirs
                    if not os.path.islink(os.path.join(root, name))
                ]
                for name in sorted(files):
                    path = os.path.join(root, name)
                    if os.path.islink(path) or os.path.splitext(name)[1].lower() not in allowed:
                        continue
                    digest = cls._sha256_file(path)
                    if digest:
                        chart_rows.append({
                            "path": os.path.relpath(path, folder).replace(os.sep, "/"),
                            "sha256": digest,
                        })
        chart_rows.sort(key=lambda row: row["path"])
        return {
            "report_id": report_id,
            "lang": lang or "primary",
            "markdown_sha256": cls._sha256_file(md_path),
            "primary_markdown_sha256": cls._sha256_file(
                cls._get_report_markdown_path(report_id)
            ),
            "audit_sha256": cls._sha256_file(audit_path),
            "citations_sha256": cls._sha256_file(citations_path),
            "viz_manifest_sha256": cls._sha256_file(
                os.path.join(folder, "viz_manifest.json")
            ),
            "chart_assets": chart_rows,
            "renderer": cls._pdf_renderer_fingerprint(),
        }

    @staticmethod
    def _markdown_visible_text(markdown: str) -> str:
        """Approximate the text a Markdown renderer exposes to a PDF reader.

        Link destinations, HTML comments, and table delimiter rows are source
        syntax rather than visible prose.  Fenced/code content and link labels
        remain because readers can see them in the rendered document.
        """
        import html as _html

        text = re.sub(r"<!--.*?-->", " ", markdown or "", flags=re.DOTALL)
        text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r" \1 ", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r" \1 ", text)
        text = re.sub(r"<((?:https?://|mailto:)[^>]+)>", r" \1 ", text)
        text = re.sub(r"<[^>]+>", " ", text)
        visible_lines: List[str] = []
        for line in text.splitlines():
            if ReportManager._is_markdown_table_delimiter(line):
                continue
            stripped = line.strip()
            if stripped.startswith(("```", "~~~")):
                continue
            line = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s*", "", line)
            line = line.replace("|", " ")
            line = re.sub(r"[*_~`]", "", line)
            visible_lines.append(line)
        return _html.unescape("\n".join(visible_lines))

    @staticmethod
    def _pdf_text_key(text: str) -> str:
        import unicodedata

        normalized = unicodedata.normalize("NFKC", text or "")
        normalized = re.sub(r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", normalized)
        return "".join(
            ch.lower() for ch in normalized
            if ch.isalnum() or "\u3400" <= ch <= "\u9fff"
        )

    @staticmethod
    def _markdown_heading_anchors(markdown: str) -> List[str]:
        anchors: List[str] = []
        in_fence = False
        marker = ""
        for line in (markdown or "").splitlines():
            stripped = line.lstrip()
            fence = re.match(r"^(`{3,}|~{3,})", stripped)
            if fence:
                current = fence.group(1)
                if not in_fence:
                    in_fence, marker = True, current[0]
                elif current[0] == marker:
                    in_fence, marker = False, ""
                continue
            if in_fence:
                continue
            match = re.match(r"^\s{0,3}(#{1,2})\s+(.+?)\s*#*\s*$", line)
            if match:
                anchor = ReportManager._pdf_text_key(match.group(2))
                if anchor:
                    anchors.append(anchor)
        return anchors

    @classmethod
    def _validate_pdf_content(
        cls, pdf_path: str, source_markdown: str
    ) -> Tuple[bool, Dict[str, Any]]:
        """Parse output and fail closed on glyph, structure, and content loss."""
        details: Dict[str, Any] = {"page_count": 0, "issues": []}
        try:
            import fitz
            with fitz.open(pdf_path) as document:
                details["page_count"] = len(document)
                if len(document) <= 0:
                    details["issues"].append("PDF contains no pages")
                    return False, details
                text = "\n".join(page.get_text("text") for page in document)
        except Exception as exc:  # noqa: BLE001 - malformed PDFs must not publish
            details["issues"].append(f"PDF parse failed ({type(exc).__name__})")
            return False, details

        replacement_count = text.count("\ufffd") + text.count("\x00")
        details["replacement_glyphs"] = replacement_count
        if replacement_count:
            details["issues"].append(
                f"PDF text contains {replacement_count} replacement glyphs"
            )

        protected = "≥≤₀₁₂₃₄₅₆₇₈₉€£¥°±→←×÷"
        missing: Dict[str, Dict[str, int]] = {}
        for char in protected:
            expected = source_markdown.count(char)
            actual = text.count(char)
            if expected and actual < expected:
                missing[char] = {"expected": expected, "actual": actual}
        details["missing_protected_glyphs"] = missing
        if missing:
            details["issues"].append("PDF lost protected Unicode glyphs")

        visible_source = cls._markdown_visible_text(source_markdown)
        source_key = cls._pdf_text_key(visible_source)
        extracted_key = cls._pdf_text_key(text)

        heading_anchors = cls._markdown_heading_anchors(source_markdown)
        missing_headings = [anchor for anchor in heading_anchors if anchor not in extracted_key]
        details["heading_anchors"] = len(heading_anchors)
        details["missing_heading_sha256"] = [
            hashlib.sha256(anchor.encode("utf-8")).hexdigest()
            for anchor in missing_headings
        ]
        if missing_headings:
            details["issues"].append(
                f"PDF is missing {len(missing_headings)} rendered section headings"
            )

        source_numbers = ReportAgent._translation_number_multiset(visible_source)
        extracted_numbers = ReportAgent._translation_number_multiset(text)
        missing_numbers = {
            token: {"expected": count, "actual": int(extracted_numbers.get(token, 0))}
            for token, count in source_numbers.items()
            if int(extracted_numbers.get(token, 0)) < int(count)
        }
        details["missing_numeric_tokens"] = missing_numbers
        if missing_numbers:
            details["issues"].append("PDF lost visible numeric tokens")

        source_markers = ReportAgent._translation_marker_multiset(source_markdown)
        extracted_markers = ReportAgent._translation_marker_multiset(text)
        footnotes = bool(getattr(Config, "REPORT_PDF_CITATION_FOOTNOTES", True))
        missing_markers: Dict[str, Dict[str, int]] = {}
        for tag, count in source_markers.items():
            # Pandoc replaces the first body occurrence with a footnote marker;
            # the canonical References label remains visible.  Every additional
            # occurrence must survive byte-for-byte.
            required = max(1, int(count) - (1 if footnotes else 0))
            actual = int(extracted_markers.get(tag, 0))
            if actual < required:
                missing_markers[tag] = {"expected_min": required, "actual": actual}
        details["missing_citation_markers"] = missing_markers
        if missing_markers:
            details["issues"].append("PDF lost visible citation markers")

        # Latin token coverage catches one-page/truncated outputs while allowing
        # harmless TOC/page-number additions and line-wrap hyphenation.
        import unicodedata
        normalized_source = unicodedata.normalize("NFKC", visible_source)
        normalized_text = unicodedata.normalize("NFKC", text)
        normalized_text = re.sub(
            r"([A-Za-z])-\s*\n\s*([A-Za-z])", r"\1\2", normalized_text
        )
        source_words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", normalized_source.lower())
        extracted_words = re.findall(r"[A-Za-z][A-Za-z'-]{2,}", normalized_text.lower())
        from collections import Counter
        source_word_counts = Counter(source_words)
        extracted_word_counts = Counter(extracted_words)
        matched_words = sum(
            min(count, extracted_word_counts.get(word, 0))
            for word, count in source_word_counts.items()
        )
        word_coverage = matched_words / max(1, sum(source_word_counts.values()))
        unique_word_coverage = (
            len(set(source_words) & set(extracted_words)) / max(1, len(set(source_words)))
        )
        details["latin_word_coverage"] = round(word_coverage, 4)
        details["latin_unique_word_coverage"] = round(unique_word_coverage, 4)
        if len(source_words) >= 6 and (
            word_coverage < 0.72 or unique_word_coverage < 0.72
        ):
            details["issues"].append("PDF text extraction lost substantial Latin content")
        elif 0 < len(source_words) < 6 and len(source_key) >= 8 and source_key not in extracted_key:
            details["issues"].append("PDF text extraction lost the visible report body")

        source_han = re.findall(r"[\u3400-\u9fff]", visible_source)
        extracted_han = re.findall(r"[\u3400-\u9fff]", text)
        details["source_han_chars"] = len(source_han)
        details["extracted_han_chars"] = len(extracted_han)
        if len(source_han) >= 20:
            source_han_text = "".join(source_han)
            extracted_han_text = "".join(extracted_han)
            source_bigrams = {
                source_han_text[index:index + 2]
                for index in range(len(source_han_text) - 1)
            }
            extracted_bigrams = {
                extracted_han_text[index:index + 2]
                for index in range(len(extracted_han_text) - 1)
            }
            han_coverage = len(source_bigrams & extracted_bigrams) / max(1, len(source_bigrams))
            details["han_bigram_coverage"] = round(han_coverage, 4)
            if han_coverage < 0.72:
                details["issues"].append(
                    "PDF text extraction lost representative Han content"
                )
        elif source_han and source_key not in extracted_key:
            details["issues"].append("PDF text extraction lost the visible report body")

        # Several independent completeness signals can intentionally collapse
        # onto the same user-facing diagnosis for very short bilingual reports.
        # Keep the gate strict while returning an actionable, non-duplicated
        # issue list to the API and UI.
        details["issues"] = list(dict.fromkeys(details["issues"]))
        details["text_chars"] = len(text)
        return not details["issues"], details

    @classmethod
    def _cached_pdf_valid(
        cls, pdf_path: str, manifest_path: str, expected_input: Dict[str, Any]
    ) -> bool:
        try:
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.load(handle)
        except (OSError, ValueError, TypeError):
            return False
        if not isinstance(manifest, dict):
            return False
        if manifest.get("schema_version") != cls._PDF_MANIFEST_SCHEMA_VERSION:
            return False
        if manifest.get("input") != expected_input or not cls._is_pdf_file(pdf_path):
            return False
        return bool(
            manifest.get("pdf_sha256")
            and manifest.get("pdf_sha256") == cls._sha256_file(pdf_path)
            and int(manifest.get("page_count") or 0) > 0
        )

    @staticmethod
    def _is_markdown_table_delimiter(line: str) -> bool:
        body = (line or "").strip()
        if body.startswith("|"):
            body = body[1:]
        if body.endswith("|"):
            body = body[:-1]
        cells = [cell.strip() for cell in re.split(r"(?<!\\)\|", body)]
        return bool(
            len(cells) >= 2
            and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)
        )

    @staticmethod
    def _markdown_requires_pandoc(markdown: str) -> bool:
        lines = (markdown or "").splitlines()
        has_table_separator = any(
            ReportManager._is_markdown_table_delimiter(line) for line in lines
        )
        return bool(
            has_table_separator
            or re.search(r"^\[\^[^\]]+\]:", markdown or "", re.MULTILINE)
        )

    @staticmethod
    @contextmanager
    def _advisory_file_lock(lock_path: str):
        os.makedirs(os.path.dirname(lock_path), exist_ok=True)
        with open(lock_path, "a+b") as handle:
            try:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except (ImportError, OSError):
                fcntl = None  # type: ignore[assignment]
            try:
                yield
            finally:
                if fcntl is not None:
                    try:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    except OSError:
                        pass

    # Backward-compatible name retained for downstream callers/tests.
    _advisory_pdf_file_lock = _advisory_file_lock

    @staticmethod
    def _safe_unlink(*paths: str) -> None:
        """静默删除临时文件（不存在/权限错误一律忽略）。"""
        for p in paths:
            try:
                if p and os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass

    @staticmethod
    def _rewrite_chart_paths_for_pdf(md: str, folder: str) -> str:
        """PDF-1 预处理：只把 Markdown 图片的相对 charts/<file> 重写为绝对路径，供 PDF
        构建器定位图片。普通交互链接保持相对，绝不把工作站私有路径写进可点击文本。
        仅重写真实存在、非 symlink 且 realpath 仍位于本报告 charts/ 内的静态图片。"""
        abs_charts = os.path.realpath(os.path.join(os.path.abspath(folder), "charts"))
        allowed = {".png", ".svg", ".jpg", ".jpeg", ".gif", ".webp"}

        def _sub(m: "re.Match") -> str:
            rel = m.group("rel")                       # 形如 charts/foo.png 或 ./charts/foo.png
            raw = rel.removeprefix("./")
            if ("\\" in raw or "%" in raw
                    or any(ord(char) < 32 or ord(char) == 127 for char in raw)):
                return m.group(0)
            parts = raw.split("/")
            if (len(parts) < 2 or parts[0] != "charts"
                    or any(part in ("", ".", "..") for part in parts)
                    or os.path.splitext(parts[-1])[1].lower() not in allowed):
                return m.group(0)
            candidate = os.path.join(abs_charts, *parts[1:])
            resolved = os.path.realpath(candidate)
            try:
                contained = os.path.commonpath([resolved, abs_charts]) == abs_charts
            except ValueError:
                contained = False
            if (not contained or not os.path.isfile(resolved)
                    or any(os.path.islink(os.path.join(abs_charts, *parts[1:i]))
                           for i in range(2, len(parts) + 1))):
                return m.group(0)
            return m.group("prefix") + resolved + ")"

        # 仅匹配 ![alt](relative-chart)；普通 [link](charts/x.html) 与绝对图片不受影响。
        return re.sub(
            r"(?P<prefix>!\[[^\]\n]*\]\()(?P<rel>(?:\./)?charts/[^)\s]+)\)",
            _sub,
            md,
        )

    @staticmethod
    def _prerender_mermaid_for_pdf(md: str, folder: str) -> str:
        """PDF-1 预处理：PATH 有 mmdc 时把 ```mermaid``` 块预渲染成 PNG 并替换为绝对图片引用；
        无 mmdc 则原样保留围栏（pandoc 当作代码块排版）。degrade-safe：单块渲染失败即保留围栏。"""
        import shutil
        import subprocess
        import hashlib

        mmdc = shutil.which("mmdc")
        if not mmdc:
            return md
        charts_dir = os.path.join(os.path.abspath(folder), "charts")
        try:
            os.makedirs(charts_dir, exist_ok=True)
        except OSError:
            return md
        fence_re = re.compile(r"```mermaid[ \t]*\n(.*?)\n```", re.DOTALL)

        def _sub(m: "re.Match") -> str:
            code = m.group(1)
            h = hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]
            src = os.path.join(charts_dir, f"mermaid_{h}.mmd")
            out = os.path.join(charts_dir, f"mermaid_{h}.png")
            try:
                if not os.path.exists(out):
                    with open(src, "w", encoding="utf-8") as f:
                        f.write(code)
                    subprocess.run([mmdc, "-i", src, "-o", out],
                                   capture_output=True, timeout=60, check=True)
                if os.path.exists(out) and os.path.getsize(out) > 0:
                    return f"![]({out})"
            except Exception:  # noqa: BLE001 — 渲染失败保留原围栏
                return m.group(0)
            return m.group(0)

        return fence_re.sub(_sub, md)

    @staticmethod
    def _load_citations_map(
        folder: str, lang: Optional[str] = None
    ) -> Dict[str, Dict[str, Any]]:
        """Load the citation namespace for exactly one published artifact.

        A translation never falls back to ``citations.json``: doing so can bind a
        legacy translation's positional ``[S#]`` namespace to unrelated primary
        sources.  Missing/invalid language-specific artifacts therefore return ``{}``.
        """
        filename = f"citations.{lang}.json" if lang in ("en", "zh") else "citations.json"
        path = os.path.join(folder, filename)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            out: Dict[str, Dict[str, Any]] = {}
            for m in (data.get("markers") or []):
                if isinstance(m, dict) and m.get("tag"):
                    out[str(m["tag"])] = m
            return out
        except (OSError, json.JSONDecodeError, TypeError) as e:
            logger.warning(f"读取 {filename} 失败（PDF 不做跨语种引用回退）: {e}")
            return {}

    @classmethod
    def _translation_publish_audit_valid(
        cls, report_id: str, lang: str, markdown: str
    ) -> bool:
        """Require the complete report/source-bound variant contract before export."""
        if lang not in cls._TRANSLATION_LANGS:
            return False
        expected_sha = hashlib.sha256((markdown or "").encode("utf-8")).hexdigest()
        status = cls.publication_status(report_id, lang)
        return bool(
            status.get("publishable")
            and status.get("markdown_sha256") == expected_sha
        )

    @staticmethod
    def _rewrite_citations_for_pdf(md: str, citations: Dict[str, Dict[str, Any]]) -> str:
        """WAVE10 PDF 预处理：可解析 [S12] → pandoc 脚注（xelatex 渲染为真脚注 + 可点击链接）。

        规则（纯字符串变换，可测）：
          * 每个记号仅**首次**出现改写为 [^s12] 引用（重复引用同一脚注 id 会让 pandoc 在
            每处重复整段脚注文本——[S2] x90 会把 PDF 撑爆），后续出现保留字面记号，读者
            靠文末 References 附录对照；
          * 围栏（```/~~~）内是字面内容不动；「References/参考来源」附录章节整体跳过
            （附录里的 [S12] 是条目标签，改写会产生自引用脚注）；
          * 不可解析记号原样保留；
          * 脚注定义追加到文末：标题 — 域名，日期 + 短链接文本 [domain](url)（链接文本用
            域名而非原始长 URL——脚注里的裸长 URL 是 xelatex 边距溢出的主因）；
          * 无效 URL（citations.json url_valid=false）不渲染链接。
        citations 为空 → 原样返回。"""
        if not citations:
            return md
        marker_re = re.compile(r"[\[【]\s*(S\d+(?:-[A-Za-z])?)\s*[\]】]")
        footnoted: List[str] = []          # 保序：已改写为脚注引用的记号
        out_lines: List[str] = []
        in_fence = False
        in_refs = False
        for ln in md.split("\n"):
            s = ln.lstrip()
            if s.startswith("```") or s.startswith("~~~"):
                in_fence = not in_fence
                out_lines.append(ln)
                continue
            if not in_fence and ln.startswith("## "):
                in_refs = ln.strip() in _REFS_HEADINGS
            if in_fence or in_refs:
                out_lines.append(ln)
                continue

            def _sub(m: "re.Match") -> str:
                tag = m.group(1)
                tag = "S" + tag[1:].lower() if tag[:1] in "sS" else tag
                if tag not in citations:
                    return m.group(0)                  # 不可解析 → 原样
                if tag in footnoted:
                    return m.group(0)                  # 非首次 → 保留字面记号
                footnoted.append(tag)
                return f"[^{tag.lower()}]"

            out_lines.append(marker_re.sub(_sub, ln))
        if not footnoted:
            return md
        defs: List[str] = []
        for tag in footnoted:
            entry = citations[tag]
            title = str(entry.get("title") or "").strip() or tag
            domain = str(entry.get("domain") or "").strip()
            date = str(entry.get("date") or "").strip()
            url = str(entry.get("url") or "").strip()
            body = title
            meta = [x for x in (domain, date) if x]
            if meta:
                body += " — " + ", ".join(meta)
            if url and entry.get("url_valid"):
                body += f" [{domain or 'link'}]({url})"
            defs.append(f"[^{tag.lower()}]: {body}")
        return "\n".join(out_lines).rstrip() + "\n\n" + "\n".join(defs) + "\n"

    @classmethod
    def _resolve_pandoc(cls):
        """返回 (pandoc_path, xelatex_path|None)；pandoc 不可用 → None。"""
        import shutil
        pandoc = cls._PANDOC_BIN if os.path.exists(cls._PANDOC_BIN) else shutil.which("pandoc")
        if not pandoc:
            return None
        xelatex = cls._XELATEX_BIN if os.path.exists(cls._XELATEX_BIN) else shutil.which("xelatex")
        return pandoc, xelatex

    @classmethod
    def _export_pdf_pandoc(cls, report_id: str, md: str, folder: str, pdf_path: str) -> bool:
        """Build an A4 PDF with explicit Latin/symbol, CJK, and mono fonts.

        成功（产出非空 PDF）→ True；pandoc 不可用/返回非零/无产出/超时 → False（触发回退）。"""
        import subprocess
        import tempfile

        resolved = cls._resolve_pandoc()
        if not resolved:
            return False
        pandoc, xelatex = resolved
        fonts = cls._resolve_pdf_fonts()
        main_font = fonts.get("main")
        cjk_font = fonts.get("cjk")
        mono_font = fonts.get("mono")
        if not isinstance(main_font, dict):
            logger.warning("pandoc PDF 拒绝构建：缺少支持符号的主字体")
            return False
        if re.search(r"[\u3400-\u9fff]", md or "") and not isinstance(cjk_font, dict):
            logger.warning("pandoc PDF 拒绝构建：中文内容缺少可解析的 CJK 字体")
            return False
        source_fd, src_md = tempfile.mkstemp(
            prefix=".pdf-source-", suffix=".md", dir=folder
        )
        output_fd, tmp_pdf = tempfile.mkstemp(
            prefix=".pdf-building-", suffix=".pdf", dir=folder
        )
        os.close(source_fd)
        os.close(output_fd)
        try:
            with open(src_md, "w", encoding="utf-8") as f:
                f.write(md)
        except OSError as e:
            logger.warning(f"写 PDF 源 md 失败: {e}")
            cls._safe_unlink(src_md, tmp_pdf)
            return False
        cmd = [
            pandoc, src_md,
            f"--pdf-engine={xelatex or 'xelatex'}",
            "-V", f"mainfont={main_font['family']}",
            "-V", "geometry:margin=2.5cm",
            "-V", "papersize:a4",
            "--toc",
        ]
        if isinstance(cjk_font, dict):
            cmd += ["-V", f"CJKmainfont={cjk_font['family']}"]
        if isinstance(mono_font, dict):
            cmd += ["-V", f"monofont={mono_font['family']}"]
        # WAVE10（无缝引用）：脚注/参考来源链接着色为可见的可点击链接（colorlinks 是
        # hyperref 内建选项，无额外宏包依赖；zh 路径 PingFang SC 下同样安全）。
        if getattr(Config, "REPORT_PDF_CITATION_FOOTNOTES", True):
            cmd += ["-V", "colorlinks=true"]
        cmd += ["-o", tmp_pdf]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, cwd=folder,
                timeout=int(getattr(Config, "REPORT_PDF_TIMEOUT", 180) or 180),
            )
        except Exception as e:  # noqa: BLE001 — 超时/OS 错误 → 回退
            logger.warning(f"pandoc 执行异常，回退 PyMuPDF: {e}")
            cls._safe_unlink(src_md, tmp_pdf)
            return False
        rc = getattr(proc, "returncode", 1)
        if rc != 0 or not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0 \
                or not cls._is_pdf_file(tmp_pdf):
            _stderr = getattr(proc, "stderr", b"") or b""
            _tail = _stderr[-500:].decode("utf-8", "ignore") if isinstance(_stderr, (bytes, bytearray)) else str(_stderr)[-500:]
            logger.warning(f"pandoc 未产出有效 PDF（rc={rc}），回退 PyMuPDF：{_tail}")
            cls._safe_unlink(src_md, tmp_pdf)
            return False
        try:
            os.replace(tmp_pdf, pdf_path)
        except OSError as e:
            logger.warning(f"PDF 原子替换失败: {e}")
            cls._safe_unlink(src_md, tmp_pdf)
            return False
        cls._safe_unlink(src_md)
        logger.info(f"pandoc 导出 PDF 成功: {report_id}")
        return True

    @classmethod
    def _export_pdf_pymupdf(cls, md: str, folder: str, pdf_path: str) -> bool:
        """回退：markdown→基础 HTML→PyMuPDF Story 排版为 PDF（A4、2.5cm 边距、自动分页）。
        pymupdf 缺失/渲染失败 → False。图片经绝对路径 + folder 归档尽力解析（缺图仍出文本）。"""
        try:
            import fitz  # PyMuPDF
            import tempfile
        except Exception as e:  # noqa: BLE001
            logger.warning(f"PyMuPDF 不可用，无法回退导出 PDF: {e}")
            return False
        output_fd, tmp_pdf = tempfile.mkstemp(
            prefix=".pdf-fallback-", suffix=".pdf", dir=folder
        )
        os.close(output_fd)
        try:
            html = cls._markdown_to_basic_html(md)
            page_rect = fitz.paper_rect("a4")
            margin = 71  # ≈2.5cm（1cm≈28.35pt）
            where = fitz.Rect(page_rect.x0 + margin, page_rect.y0 + margin,
                              page_rect.x1 - margin, page_rect.y1 - margin)
            try:
                arch = fitz.Archive(os.path.abspath(folder))
                story = fitz.Story(html=html, archive=arch)
            except Exception:  # noqa: BLE001 — 归档失败仍可排版文本
                story = fitz.Story(html=html)
            writer = fitz.DocumentWriter(tmp_pdf)
            more = 1
            guard = 0
            while more and guard < 2000:  # guard：防病态 HTML 造成无限分页
                dev = writer.begin_page(page_rect)
                more, _ = story.place(where)
                story.draw(dev)
                writer.end_page()
                guard += 1
            writer.close()
            if not os.path.exists(tmp_pdf) or os.path.getsize(tmp_pdf) == 0:
                cls._safe_unlink(tmp_pdf)
                return False
            os.replace(tmp_pdf, pdf_path)
            logger.info("PyMuPDF 回退导出 PDF 成功")
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"PyMuPDF 回退导出失败: {e}")
            cls._safe_unlink(tmp_pdf)
            return False

    @staticmethod
    def _markdown_to_basic_html(md: str) -> str:
        """极简 markdown→HTML（仅回退路径用；无外部依赖）。覆盖 #~###### 标题、无序/有序列表、
        ```围栏代码块、图片 ![alt](src)、**粗体**/*斜体*/`行内码`、段落。未识别行按段落处理，
        HTML 特殊字符转义（图片 src 不转义）。目标是「文本可读 + 尽力显示图」，非像素级还原。"""
        import html as _html

        def _inline(text: str) -> str:
            # 先抽出图片，避免其 URL 被转义/干扰其它行内规则。
            imgs: List[str] = []

            def _img(m: "re.Match") -> str:
                alt = _html.escape(m.group(1))
                src = m.group(2).strip()
                imgs.append(f'<img src="{src}" alt="{alt}" style="max-width:100%;"/>')
                return f"\x00{len(imgs) - 1}\x00"

            text = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _img, text)
            text = _html.escape(text)
            text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
            text = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", text)
            text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
            # 还原图片占位符。
            text = re.sub(r"\x00(\d+)\x00", lambda m: imgs[int(m.group(1))], text)
            return text

        lines = (md or "").split("\n")
        out: List[str] = []
        in_code = False
        code_buf: List[str] = []
        list_type: Optional[str] = None  # 'ul' | 'ol' | None

        def _close_list() -> None:
            nonlocal list_type
            if list_type:
                out.append(f"</{list_type}>")
                list_type = None

        for ln in lines:
            if ln.strip().startswith("```"):
                if in_code:
                    out.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
                    code_buf = []
                    in_code = False
                else:
                    _close_list()
                    in_code = True
                continue
            if in_code:
                code_buf.append(ln)
                continue
            s = ln.strip()
            if not s:
                _close_list()
                continue
            hm = re.match(r"^(#{1,6})\s+(.*)$", s)
            if hm:
                _close_list()
                lvl = len(hm.group(1))
                out.append(f"<h{lvl}>{_inline(hm.group(2))}</h{lvl}>")
                continue
            om = re.match(r"^\d+[.)]\s+(.*)$", s)
            um = re.match(r"^[-*+]\s+(.*)$", s)
            if om:
                if list_type != "ol":
                    _close_list()
                    out.append("<ol>")
                    list_type = "ol"
                out.append(f"<li>{_inline(om.group(1))}</li>")
                continue
            if um:
                if list_type != "ul":
                    _close_list()
                    out.append("<ul>")
                    list_type = "ul"
                out.append(f"<li>{_inline(um.group(1))}</li>")
                continue
            _close_list()
            out.append(f"<p>{_inline(s)}</p>")
        if in_code:  # 未闭合围栏兜底
            out.append("<pre><code>" + _html.escape("\n".join(code_buf)) + "</code></pre>")
        _close_list()
        body = "\n".join(out)
        return ("<html><head><meta charset='utf-8'><style>"
                "body{font-family:sans-serif;font-size:11pt;line-height:1.4;}"
                "h1{font-size:20pt;}h2{font-size:16pt;}h3{font-size:13pt;}"
                "pre{background:#f4f4f4;padding:6px;font-size:9pt;white-space:pre-wrap;}"
                "code{font-family:monospace;}img{margin:6px 0;}"
                "</style></head><body>" + body + "</body></html>")

    @classmethod
    def export_pdf(cls, report_id: str, force: bool = False,
                   lang: Optional[str] = None) -> Optional[str]:
        """Export one publication-bound PDF with a content-addressed cache.

        流水：① 读成稿 → 相对图表路径绝对化 + （PATH 有 mmdc 时）预渲染 Mermaid 为 PNG；
        ② locked pandoc+xelatex with explicit symbol/CJK fonts and A4 layout;
        ③ parse, text/glyph-integrity audit, and an exact dependency/output manifest.
        The limited PyMuPDF fallback is allowed only for simple Markdown; a rich report
        fails closed instead of flattening tables or footnotes.

        BILINGUAL：lang ∈ {en, zh} 时以双语版 full_report.<lang>.md 为源、产出
        full_report.<lang>.pdf。译文须有 SHA 一致且硬通过的 final_audit.<lang>.json，
        并且只读 citations.<lang>.json；绝不回退主语种引用空间。非法/缺省 lang 仍走主报告。

        Cache reuse requires exact Markdown/audit/citation/chart/renderer fingerprints,
        an exact PDF SHA-256, and a prior successful parse/content audit. ``force=True``
        always rebuilds.  Process and advisory file locks prevent cross-request races.
        """
        if not getattr(Config, "REPORT_PDF_EXPORT", True):
            return None
        lang = lang if lang in cls._TRANSLATION_LANGS else None
        md_path = (cls._get_report_translation_path(report_id, lang)
                   if lang else cls._get_report_markdown_path(report_id))
        folder = cls._get_report_folder(report_id)
        pdf_path = cls._get_report_pdf_path(report_id, lang)
        manifest_path = cls._get_report_pdf_manifest_path(report_id, lang)
        lock = cls._pdf_lock_for(report_id, lang)
        with lock, cls._advisory_pdf_file_lock(manifest_path + ".lock"):
            if not os.path.exists(md_path):
                return None
            if not cls.is_publishable(report_id, lang):
                logger.warning(
                    "PDF 拒绝导出：报告尚未通过最终发布屏障 report_id=%s lang=%s",
                    report_id, lang or "primary",
                )
                return None
            try:
                with open(md_path, "r", encoding="utf-8") as handle:
                    md = handle.read()
            except OSError as exc:
                logger.warning(f"读取 full_report.md 失败，无法导出 PDF: {exc}")
                return None
            if lang and not cls._translation_publish_audit_valid(report_id, lang, md):
                logger.warning(
                    "译文 PDF 拒绝导出：%s 缺少报告/源字节绑定的审计、引用或元数据",
                    lang,
                )
                return None

            try:
                proc_md = cls._rewrite_chart_paths_for_pdf(md, folder)
                proc_md = cls._prerender_mermaid_for_pdf(proc_md, folder)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"PDF 预处理失败，回退用原始成稿: {exc}")
                proc_md = md
            pandoc_md = proc_md
            if getattr(Config, "REPORT_PDF_CITATION_FOOTNOTES", True):
                try:
                    citations = cls._load_citations_map(folder, lang=lang)
                    if citations:
                        pandoc_md = cls._rewrite_citations_for_pdf(proc_md, citations)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"PDF 引用脚注预处理失败（保留字面记号）: {exc}")
                    pandoc_md = proc_md

            expected_input = cls._pdf_input_fingerprint(
                report_id, lang, md_path, folder
            )
            if (not force and cls._cached_pdf_valid(
                    pdf_path, manifest_path, expected_input)):
                return pdf_path
            cls._safe_unlink(pdf_path, manifest_path)

            def _accept(renderer: str) -> bool:
                valid, content_audit = cls._validate_pdf_content(pdf_path, md)
                if not valid:
                    logger.warning(
                        "PDF 内容完整性门失败 report=%s lang=%s renderer=%s issues=%s",
                        report_id,
                        lang or "primary",
                        renderer,
                        content_audit.get("issues"),
                    )
                    cls._safe_unlink(pdf_path, manifest_path)
                    return False
                current_input = cls._pdf_input_fingerprint(
                    report_id, lang, md_path, folder
                )
                if current_input != expected_input or not cls.is_publishable(report_id, lang):
                    logger.warning(
                        "PDF 构建期间依赖或发布状态变化，拒绝提交 report=%s lang=%s",
                        report_id,
                        lang or "primary",
                    )
                    cls._safe_unlink(pdf_path, manifest_path)
                    return False
                pdf_sha = cls._sha256_file(pdf_path)
                if not pdf_sha:
                    cls._safe_unlink(pdf_path, manifest_path)
                    return False
                manifest = {
                    "schema_version": cls._PDF_MANIFEST_SCHEMA_VERSION,
                    "report_id": report_id,
                    "lang": lang or "primary",
                    "renderer": renderer,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "input": expected_input,
                    "pdf_sha256": pdf_sha,
                    "page_count": int(content_audit.get("page_count") or 0),
                    "content_audit": content_audit,
                }
                try:
                    write_json_atomic(manifest_path, manifest)
                except Exception as exc:  # noqa: BLE001 - an unbound cache is unsafe
                    logger.warning(f"PDF 清单持久化失败，拒绝发布: {exc}")
                    cls._safe_unlink(pdf_path, manifest_path)
                    return False
                return True

            if cls._export_pdf_pandoc(report_id, pandoc_md, folder, pdf_path):
                if _accept("pandoc-xelatex"):
                    return pdf_path

            if cls._markdown_requires_pandoc(md):
                logger.warning(
                    "PDF 拒绝降级：富 Markdown 需要 pandoc 保留表格/脚注 report=%s",
                    report_id,
                )
                return None
            if cls._export_pdf_pymupdf(proc_md, folder, pdf_path):
                if _accept("pymupdf-story"):
                    return pdf_path
            logger.warning(f"PDF 导出失败（所有安全渲染路径均未产出）: {report_id}")
            return None

    @classmethod
    def export_document_pdf(
        cls,
        md: str,
        folder: str,
        pdf_path: str,
        *,
        label: str = "document",
    ) -> Optional[str]:
        """Render an arbitrary Markdown document to PDF with the SHARED LaTeX template.

        This is the single rendering pipeline the forecast report uses: locked
        pandoc + XeLaTeX with the explicit symbol/CJK/mono fonts and A4 layout
        (`_export_pdf_pandoc`), the same `%PDF`/tofu/Han-coverage content gate
        (`_validate_pdf_content`), and the same "rich Markdown must not silently
        flatten" guard before the bounded PyMuPDF fallback.  Reusing it means the
        research-report Mandarin PDF is byte-for-byte the same style/template as the
        forecast-report Mandarin PDF.  Returns the PDF path on success, else None.
        """
        if not getattr(Config, "REPORT_PDF_EXPORT", True):
            return None
        if not (md or "").strip():
            return None
        try:
            proc_md = cls._rewrite_chart_paths_for_pdf(md, folder)
            proc_md = cls._prerender_mermaid_for_pdf(proc_md, folder)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"文档 PDF 预处理失败，回退用原始 markdown: {exc}")
            proc_md = md
        cls._safe_unlink(pdf_path)

        def _accept(renderer: str) -> bool:
            valid, content_audit = cls._validate_pdf_content(pdf_path, md)
            if not valid:
                logger.warning(
                    "文档 PDF 内容完整性门失败 label=%s renderer=%s issues=%s",
                    label,
                    renderer,
                    content_audit.get("issues"),
                )
                cls._safe_unlink(pdf_path)
                return False
            return True

        if cls._export_pdf_pandoc(label, proc_md, folder, pdf_path):
            if _accept("pandoc-xelatex"):
                return pdf_path
        if cls._markdown_requires_pandoc(md):
            logger.warning(
                "文档 PDF 拒绝降级：富 Markdown 需要 pandoc 保留表格/脚注 label=%s", label
            )
            return None
        if cls._export_pdf_pymupdf(proc_md, folder, pdf_path):
            if _accept("pymupdf-story"):
                return pdf_path
        logger.warning(f"文档 PDF 导出失败（所有安全渲染路径均未产出）: {label}")
        return None

    # ── EXECPLAN2 F-7-3: simulation_id 轻量索引 + 仅读 meta 头部 ──

    @classmethod
    def _get_sim_index_path(cls) -> str:
        """获取 simulation_id 索引文件路径"""
        return os.path.join(cls.REPORTS_DIR, cls._SIM_INDEX_FILENAME)

    @classmethod
    def _read_report_meta(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """仅读取并解析某报告的 meta.json（不重建 Report、不读取 full_report.md）。

        meta.json 内嵌了完整 markdown，json.load 仍会读全文；该方法主要用于在已知
        候选 report_id 时只解析一次，避免遍历全部文件夹。读取失败返回 None。
        """
        try:
            path = cls._get_report_path(report_id)
        except UnsafeIdError:
            return None
        if not os.path.exists(path):
            old_path = cls._get_legacy_report_file(report_id, "json")
            if not os.path.exists(old_path):
                return None
            path = old_path
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None

    @classmethod
    def _load_sim_index(cls) -> Dict[str, List[str]]:
        """读取 simulation_id -> [report_id, ...] 索引；缺失/损坏时返回空字典。"""
        path = cls._get_sim_index_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict):
                # 规范化为 {sim_id: [report_id,...]}
                norm: Dict[str, List[str]] = {}
                for k, v in data.items():
                    if isinstance(v, list):
                        norm[k] = [str(x) for x in v]
                    elif v:
                        norm[k] = [str(v)]
                return norm
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    @classmethod
    def _index_add(cls, simulation_id: str, report_id: str) -> None:
        """把 (simulation_id, report_id) 写入索引（原子写、加锁，幂等）。EXECPLAN2 F-7-3"""
        if not simulation_id or not report_id:
            return
        cls._ensure_reports_dir()
        with cls._sim_index_lock:
            index = cls._load_sim_index()
            ids = index.get(simulation_id, [])
            if report_id not in ids:
                ids.append(report_id)
            index[simulation_id] = ids
            try:
                write_json_atomic(cls._get_sim_index_path(), index, indent=2)
            except Exception as e:  # noqa: BLE001 — 索引仅为优化，失败不应阻断保存
                logger.warning(f"更新 simulation 索引失败（忽略，回退全量扫描）: {e}")

    @classmethod
    def _index_remove(cls, report_id: str) -> None:
        """从索引中移除某 report_id（删除报告时调用）。EXECPLAN2 F-7-3"""
        if not report_id:
            return
        with cls._sim_index_lock:
            index = cls._load_sim_index()
            changed = False
            for sim_id in list(index.keys()):
                if report_id in index[sim_id]:
                    index[sim_id] = [r for r in index[sim_id] if r != report_id]
                    changed = True
                    if not index[sim_id]:
                        del index[sim_id]
            if changed:
                try:
                    write_json_atomic(cls._get_sim_index_path(), index, indent=2)
                except Exception as e:  # noqa: BLE001 — 索引仅为优化，失败不阻断删除
                    logger.warning(f"清理 simulation 索引失败（忽略）: {e}")

    @classmethod
    def _get_outline_path(cls, report_id: str) -> str:
        """获取大纲文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "outline.json")
    
    @classmethod
    def _get_progress_path(cls, report_id: str) -> str:
        """获取进度文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "progress.json")
    
    @classmethod
    def _get_section_path(cls, report_id: str, section_index: int) -> str:
        """获取章节Markdown文件路径"""
        return os.path.join(cls._get_report_folder(report_id), f"section_{section_index:02d}.md")
    
    @classmethod
    def _get_agent_log_path(cls, report_id: str) -> str:
        """获取 Agent 日志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "agent_log.jsonl")
    
    @classmethod
    def _get_console_log_path(cls, report_id: str) -> str:
        """获取控制台日志文件路径"""
        return os.path.join(cls._get_report_folder(report_id), "console_log.txt")
    
    @classmethod
    def get_console_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        获取控制台日志内容
        
        这是报告生成过程中的控制台输出日志（INFO、WARNING等），
        与 agent_log.jsonl 的结构化日志不同。
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开始读取（用于增量获取，0 表示从头开始）
            
        Returns:
            {
                "logs": [日志行列表],
                "total_lines": 总行数,
                "from_line": 起始行号,
                "has_more": 是否还有更多日志
            }
        """
        log_path = cls._get_console_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    # 保留原始日志行，去掉末尾换行符
                    logs.append(line.rstrip('\n\r'))
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 已读取到末尾
        }
    
    @classmethod
    def get_console_log_stream(cls, report_id: str) -> List[str]:
        """
        获取完整的控制台日志（一次性获取全部）
        
        Args:
            report_id: 报告ID
            
        Returns:
            日志行列表
        """
        result = cls.get_console_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def get_agent_log(cls, report_id: str, from_line: int = 0) -> Dict[str, Any]:
        """
        获取 Agent 日志内容
        
        Args:
            report_id: 报告ID
            from_line: 从第几行开始读取（用于增量获取，0 表示从头开始）
            
        Returns:
            {
                "logs": [日志条目列表],
                "total_lines": 总行数,
                "from_line": 起始行号,
                "has_more": 是否还有更多日志
            }
        """
        log_path = cls._get_agent_log_path(report_id)
        
        if not os.path.exists(log_path):
            return {
                "logs": [],
                "total_lines": 0,
                "from_line": 0,
                "has_more": False
            }
        
        logs = []
        total_lines = 0
        
        with open(log_path, 'r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                total_lines = i + 1
                if i >= from_line:
                    try:
                        log_entry = json.loads(line.strip())
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        # 跳过解析失败的行
                        continue
        
        return {
            "logs": logs,
            "total_lines": total_lines,
            "from_line": from_line,
            "has_more": False  # 已读取到末尾
        }
    
    @classmethod
    def get_agent_log_stream(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取完整的 Agent 日志（用于一次性获取全部）
        
        Args:
            report_id: 报告ID
            
        Returns:
            日志条目列表
        """
        result = cls.get_agent_log(report_id, from_line=0)
        return result["logs"]
    
    @classmethod
    def save_outline(cls, report_id: str, outline: ReportOutline) -> None:
        """
        保存报告大纲
        
        在规划阶段完成后立即调用
        """
        cls._ensure_report_folder(report_id)
        
        # 原子写入，避免轮询端点读到半截 JSON（EXECPLAN2 F-7-6）
        write_text_atomic(cls._get_outline_path(report_id),
                          json.dumps(outline.to_dict(), ensure_ascii=False, indent=2))

        logger.info(f"大纲已保存: {report_id}")
    
    @classmethod
    def save_section(
        cls,
        report_id: str,
        section_index: int,
        section: ReportSection
    ) -> str:
        """
        保存单个章节

        在每个章节生成完成后立即调用，实现分章节输出

        Args:
            report_id: 报告ID
            section_index: 章节索引（从1开始）
            section: 章节对象

        Returns:
            保存的文件路径
        """
        cls._ensure_report_folder(report_id)

        # 构建章节Markdown内容 - 清理可能存在的重复标题
        cleaned_content = cls._clean_section_content(section.content, section.title)
        md_content = f"## {section.title}\n\n"
        if cleaned_content:
            md_content += f"{cleaned_content}\n\n"

        # 保存文件
        file_suffix = f"section_{section_index:02d}.md"
        file_path = os.path.join(cls._get_report_folder(report_id), file_suffix)
        write_text_atomic(file_path, md_content)  # 原子写入（F-7-6）

        logger.info(f"章节已保存: {report_id}/{file_suffix}")
        return file_path
    
    @classmethod
    def _clean_section_content(cls, content: str, section_title: str) -> str:
        """
        清理章节内容

        1. 移除内容开头与章节标题重复的Markdown标题行
        2. RQ-1：保留 ### 三级小标题（章节内部子小节结构），把 #/##（H1/H2 层级，与报告主标题/
           章节标题冲突）与 #### 及更深层级一律降级为粗体文本

        Args:
            content: 原始内容
            section_title: 章节标题

        Returns:
            清理后的内容
        """
        import re

        if not content:
            return content

        content = content.strip()
        lines = content.split('\n')
        cleaned_lines = []
        skip_next_empty = False

        for i, line in enumerate(lines):
            stripped = line.strip()

            # 检查是否是Markdown标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)

            if heading_match:
                level = len(heading_match.group(1))
                title_text = heading_match.group(2).strip()

                # 检查是否是与章节标题重复的标题（跳过前5行内的重复）
                if i < 5:
                    if title_text == section_title or title_text.replace(' ', '') == section_title.replace(' ', ''):
                        skip_next_empty = True
                        continue

                # RQ-1：白名单 ### 三级小标题——章节内部子小节结构，原样保留（H3 纪律）。
                if level == 3:
                    cleaned_lines.append(f"### {title_text}")
                    continue
                # 其余层级（#/##/#### 及更深）降级为粗体：H1/H2 与报告主标题/章节标题层级冲突，
                # 深层级破坏单层子小节纪律。章节主标题由系统添加，正文不应出现这些层级。
                cleaned_lines.append(f"**{title_text}**")
                cleaned_lines.append("")  # 添加空行
                continue
            
            # 如果上一行是被跳过的标题，且当前行为空，也跳过
            if skip_next_empty and stripped == '':
                skip_next_empty = False
                continue
            
            skip_next_empty = False
            cleaned_lines.append(line)
        
        # 移除开头的空行
        while cleaned_lines and cleaned_lines[0].strip() == '':
            cleaned_lines.pop(0)
        
        # 移除开头的分隔线
        while cleaned_lines and cleaned_lines[0].strip() in ['---', '***', '___']:
            cleaned_lines.pop(0)
            # 同时移除分隔线后的空行
            while cleaned_lines and cleaned_lines[0].strip() == '':
                cleaned_lines.pop(0)
        
        return '\n'.join(cleaned_lines)
    
    @classmethod
    def update_progress(
        cls,
        report_id: str,
        status: str,
        progress: int,
        message: str,
        current_section: str = None,
        completed_sections: List[str] = None,
        failed_sections: List[str] = None,
        forecast_ok: bool = None
    ) -> None:
        """
        更新报告生成进度

        前端可以通过读取progress.json获取实时进度

        XRUN-7: failed_sections/forecast_ok 为可选增量字段——占位符章节从
        completed_sections 中剔除并单列，附 placeholder_count 与 health 标记，
        让 progress.json 不再对着 5/5 占位符宣称全部章节完成。二者缺省时
        输出 schema 与历史逐字节一致（degrade-safe）。status 保持原语义不变
        （消费方以 status 判定终态，健康降级经 health 字段表达）。
        """
        cls._ensure_report_folder(report_id)

        progress_data = {
            "status": status,
            "progress": progress,
            "message": message,
            "current_section": current_section,
            "completed_sections": completed_sections or [],
            "updated_at": datetime.now().isoformat()
        }
        if failed_sections is not None:
            _failed = list(failed_sections)
            progress_data["completed_sections"] = [
                t for t in (completed_sections or []) if t not in _failed
            ]
            progress_data["failed_sections"] = _failed
            progress_data["placeholder_count"] = len(_failed)
            if _failed:
                progress_data["health"] = "degraded"
        if forecast_ok is not None:
            progress_data["forecast_ok"] = bool(forecast_ok)

        write_text_atomic(cls._get_progress_path(report_id),
                          json.dumps(progress_data, ensure_ascii=False, indent=2))  # 原子写入（F-7-6）

    @classmethod
    def get_progress(cls, report_id: str) -> Optional[Dict[str, Any]]:
        """获取报告生成进度"""
        path = cls._get_progress_path(report_id)
        
        if not os.path.exists(path):
            return None
        
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    @classmethod
    def get_generated_sections(cls, report_id: str) -> List[Dict[str, Any]]:
        """
        获取已生成的章节列表
        
        返回所有已保存的章节文件信息
        """
        folder = cls._get_report_folder(report_id)
        
        if not os.path.exists(folder):
            return []
        
        sections = []
        for filename in sorted(os.listdir(folder)):
            if filename.startswith('section_') and filename.endswith('.md'):
                file_path = os.path.join(folder, filename)
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 从文件名解析章节索引
                parts = filename.replace('.md', '').split('_')
                section_index = int(parts[1])

                sections.append({
                    "filename": filename,
                    "section_index": section_index,
                    "content": content
                })

        return sections
    
    @classmethod
    def assemble_full_report(cls, report_id: str, outline: ReportOutline) -> str:
        """
        组装完整报告
        
        从已保存的章节文件组装完整报告，并进行标题清理
        """
        folder = cls._get_report_folder(report_id)
        
        # 构建报告头部
        md_content = f"# {outline.title}\n\n"
        md_content += f"> {outline.summary}\n\n"
        md_content += "---\n\n"
        
        # 按顺序读取所有章节文件
        sections = cls.get_generated_sections(report_id)
        for section_info in sections:
            md_content += section_info["content"]
        
        # 后处理：清理整个报告的标题问题
        md_content = cls._post_process_report(md_content, outline)
        
        # 保存完整报告（原子写入，F-7-6）
        full_path = cls._get_report_markdown_path(report_id)
        write_text_atomic(full_path, md_content)

        logger.info(f"完整报告已组装: {report_id}")
        return md_content
    
    @classmethod
    def _post_process_report(cls, content: str, outline: ReportOutline) -> str:
        """
        后处理报告内容

        1. 移除重复的标题
        2. RQ-1：保留报告主标题(#)、章节标题(##) 与章节内 ### 三级小标题；把 #### 及更深层级
           降级为粗体（H1/H2/H3 三级纪律，H4+ 破坏单层子小节结构）
        3. 清理多余的空行和分隔线
        
        Args:
            content: 原始报告内容
            outline: 报告大纲
            
        Returns:
            处理后的内容
        """
        import re
        
        lines = content.split('\n')
        processed_lines = []
        prev_was_heading = False
        
        # 收集大纲中的所有章节标题
        section_titles = set()
        for section in outline.sections:
            section_titles.add(section.title)
        
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            
            # 检查是否是标题行
            heading_match = re.match(r'^(#{1,6})\s+(.+)$', stripped)
            
            if heading_match:
                level = len(heading_match.group(1))
                title = heading_match.group(2).strip()
                
                # 检查是否是重复标题（在连续5行内出现相同内容的标题）
                is_duplicate = False
                for j in range(max(0, len(processed_lines) - 5), len(processed_lines)):
                    prev_line = processed_lines[j].strip()
                    prev_match = re.match(r'^(#{1,6})\s+(.+)$', prev_line)
                    if prev_match:
                        prev_title = prev_match.group(2).strip()
                        if prev_title == title:
                            is_duplicate = True
                            break
                
                if is_duplicate:
                    # 跳过重复标题及其后的空行
                    i += 1
                    while i < len(lines) and lines[i].strip() == '':
                        i += 1
                    continue
                
                # 标题层级处理（RQ-1）：
                # - # (level=1) 只保留报告主标题
                # - ## (level=2) 保留章节标题
                # - ### (level=3) 保留章节内三级小标题（子小节结构）
                # - #### 及更深 (level>=4) 转换为粗体文本

                if level == 1:
                    if title == outline.title:
                        # 保留报告主标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    elif title in section_titles:
                        # 章节标题错误使用了#，修正为##
                        processed_lines.append(f"## {title}")
                        prev_was_heading = True
                    else:
                        # 其他一级标题转为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 2:
                    if title in section_titles or title == outline.title:
                        # 保留章节标题
                        processed_lines.append(line)
                        prev_was_heading = True
                    else:
                        # 非章节的二级标题转为粗体
                        processed_lines.append(f"**{title}**")
                        processed_lines.append("")
                        prev_was_heading = False
                elif level == 3:
                    # RQ-1：保留章节内 ### 三级小标题（子小节结构）
                    processed_lines.append(f"### {title}")
                    prev_was_heading = True
                else:
                    # #### 及更深层级的标题转换为粗体文本
                    processed_lines.append(f"**{title}**")
                    processed_lines.append("")
                    prev_was_heading = False

                i += 1
                continue
            
            elif stripped == '---' and prev_was_heading:
                # 跳过标题后紧跟的分隔线
                i += 1
                continue
            
            elif stripped == '' and prev_was_heading:
                # 标题后只保留一个空行
                if processed_lines and processed_lines[-1].strip() != '':
                    processed_lines.append(line)
                prev_was_heading = False
            
            else:
                processed_lines.append(line)
                prev_was_heading = False
            
            i += 1
        
        # 清理连续的多个空行（保留最多2个）
        result_lines = []
        empty_count = 0
        for line in processed_lines:
            if line.strip() == '':
                empty_count += 1
                if empty_count <= 2:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)
        
        return '\n'.join(result_lines)
    
    @classmethod
    def save_report(cls, report: Report) -> None:
        """保存报告元信息和完整报告"""
        cls._ensure_report_folder(report.report_id)
        
        # 保存元信息JSON（原子写入，F-7-6）
        write_text_atomic(cls._get_report_path(report.report_id),
                          json.dumps(report.to_dict(), ensure_ascii=False, indent=2))

        # 保存大纲
        if report.outline:
            cls.save_outline(report.report_id, report.outline)

        # 保存完整Markdown报告（原子写入）
        if report.markdown_content:
            write_text_atomic(cls._get_report_markdown_path(report.report_id), report.markdown_content)

        # EXECPLAN2 F-7-3: 维护 simulation_id -> report_id 轻量索引，加速 by-simulation 查询
        cls._index_add(report.simulation_id, report.report_id)

        logger.info(f"报告已保存: {report.report_id}")
    
    @classmethod
    def get_report(cls, report_id: str) -> Optional[Report]:
        """获取报告"""
        # EXECPLAN2 F-7-3: 保留文件名（索引）不是报告，直接忽略，避免误解析
        if f"{report_id}.json" == cls._SIM_INDEX_FILENAME or report_id == cls._SIM_INDEX_FILENAME[:-5]:
            return None

        try:
            path = cls._get_report_path(report_id)
        except UnsafeIdError:
            return None  # INFRA-10: 非法 id 与「不存在」同义

        if not os.path.exists(path):
            # 兼容旧格式：检查直接存储在reports目录下的文件
            old_path = cls._get_legacy_report_file(report_id, "json")
            if os.path.exists(old_path):
                path = old_path
            else:
                return None

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        # EXECPLAN2 F-7-3: 非报告结构（如索引/旧版无关 JSON）容错，返回 None 而非抛错
        if not isinstance(data, dict) or 'report_id' not in data or 'simulation_id' not in data:
            return None

        # 重建Report对象
        outline = None
        if data.get('outline'):
            outline_data = data['outline']
            sections = []
            for s in outline_data.get('sections', []):
                sections.append(ReportSection(
                    title=s['title'],
                    content=s.get('content', ''),
                    description=s.get('description', '')
                ))
            outline = ReportOutline(
                title=outline_data['title'],
                summary=outline_data['summary'],
                sections=sections
            )
        
        # 如果markdown_content为空，尝试从full_report.md读取
        markdown_content = data.get('markdown_content', '')
        if not markdown_content:
            full_report_path = cls._get_report_markdown_path(report_id)
            if os.path.exists(full_report_path):
                with open(full_report_path, 'r', encoding='utf-8') as f:
                    markdown_content = f.read()
        
        return Report(
            report_id=data['report_id'],
            simulation_id=data['simulation_id'],
            graph_id=data['graph_id'],
            simulation_requirement=data['simulation_requirement'],
            status=ReportStatus(data['status']),
            outline=outline,
            markdown_content=markdown_content,
            created_at=data.get('created_at', ''),
            completed_at=data.get('completed_at', ''),
            error=data.get('error'),
            # 部分完成信息：从 meta.json 还原失败章节标题列表（旧报告无此键 → 空列表，partial=False）
            failed_sections=data.get('failed_sections') or [],
            telemetry=data.get('telemetry'),  # EXECPLAN2 I-5-4: 从 meta.json 还原紧凑遥测，经 API 暴露
            translations=data.get('translations')  # BILINGUAL：从 meta.json 还原双语版本清单
        )
    
    @classmethod
    def get_report_by_simulation(cls, simulation_id: str) -> Optional[Report]:
        """根据模拟ID获取报告（EXECPLAN2 F-7-0 / F-7-3）。

        旧实现遍历 os.listdir 返回首个匹配项——listdir 顺序由文件系统决定，
        force_regenerate 留下多份同 simulation 报告时返回的往往是过期报告且不确定。
        新实现：
          1) 先查 simulation_id 轻量索引（F-7-3），仅解析候选 report_id 的 meta，
             避免对全部报告文件夹做 O(N) 全量扫描；
          2) 在候选中按 created_at 取最新（确定性，对齐 list_reports 的排序，F-7-0 A）；
          3) 索引缺失/未命中时回退全量扫描，同样按 created_at 取最新而非首个 listdir 命中。
        """
        cls._ensure_reports_dir()

        # ① 索引快路径：候选 report_id -> (created_at, report_id)，仅读 meta 头部
        index = cls._load_sim_index()
        candidates: List[tuple] = []  # (created_at, report_id)
        for rid in index.get(simulation_id, []):
            meta = cls._read_report_meta(rid)
            if meta and meta.get('simulation_id') == simulation_id:
                candidates.append((meta.get('created_at', ''), rid))
        if candidates:
            best_rid = max(candidates, key=lambda x: x[0])[1]
            report = cls.get_report(best_rid)
            if report and report.simulation_id == simulation_id:
                return report

        # ② 回退：全量扫描，确定性地按 created_at 取最新（F-7-0 A）
        matches: List[Report] = []
        for item in os.listdir(cls.REPORTS_DIR):
            if item == cls._SIM_INDEX_FILENAME:  # EXECPLAN2 F-7-3: 跳过索引文件，避免误当报告解析
                continue
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新格式：文件夹（INFRA-10: 名字不是合法 id 的条目——.DS_Store、_tmp 等——直接跳过）
            if os.path.isdir(item_path):
                if not is_safe_id(item):
                    continue
                report = cls.get_report(item)
                if report and report.simulation_id == simulation_id:
                    matches.append(report)
            # 兼容旧格式：JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                if not is_safe_id(report_id):
                    continue
                report = cls.get_report(report_id)
                if report and report.simulation_id == simulation_id:
                    matches.append(report)

        if not matches:
            return None
        return max(matches, key=lambda r: r.created_at)

    @classmethod
    def delete_other_reports_for_simulation(cls, simulation_id: str, keep_report_id: str) -> int:
        """EXECPLAN2 F-7-0 (B 的 in-file 部分): 删除某 simulation 除 keep_report_id 外的所有报告，
        修复 force_regenerate 留下的孤儿文件夹泄漏与过期短路。

        仅在新报告已成功落盘后调用，确保该 simulation 不会被清成零报告。
        调用方（api/report.py 等，跨文件不在本次改动范围）应在新报告 COMPLETED 后调用本方法。
        返回删除的报告数量。
        """
        deleted = 0
        for report in cls.list_reports(simulation_id=simulation_id, limit=10_000):
            if report.report_id != keep_report_id:
                try:
                    if cls.delete_report(report.report_id):
                        deleted += 1
                except Exception as e:  # noqa: BLE001 — 清理失败不应影响主流程
                    logger.warning(f"清理同 simulation 旧报告失败（忽略）: {report.report_id}: {e}")
        return deleted

    @classmethod
    def list_reports(cls, simulation_id: Optional[str] = None, limit: int = 50) -> List[Report]:
        """列出报告"""
        cls._ensure_reports_dir()
        
        reports = []
        for item in os.listdir(cls.REPORTS_DIR):
            if item == cls._SIM_INDEX_FILENAME:  # EXECPLAN2 F-7-3: 跳过索引文件，避免误当报告解析
                continue
            item_path = os.path.join(cls.REPORTS_DIR, item)
            # 新格式：文件夹（INFRA-10: 名字不是合法 id 的条目——.DS_Store、_tmp 等——直接跳过）
            if os.path.isdir(item_path):
                if not is_safe_id(item):
                    continue
                report = cls.get_report(item)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
            # 兼容旧格式：JSON文件
            elif item.endswith('.json'):
                report_id = item[:-5]
                if not is_safe_id(report_id):
                    continue
                report = cls.get_report(report_id)
                if report:
                    if simulation_id is None or report.simulation_id == simulation_id:
                        reports.append(report)
        
        # 按创建时间倒序
        reports.sort(key=lambda r: r.created_at, reverse=True)
        
        return reports[:limit]
    
    @classmethod
    def delete_report(cls, report_id: str) -> bool:
        """删除报告（整个文件夹）。

        INFRA-10: rmtree 的目标只可能来自 contained_child（REPORTS_DIR 的严格后代）；
        非法/逃逸 id 抛 UnsafeIdError，绝不删除数据根之外的任何东西。
        """
        import shutil

        folder_path = cls._get_report_folder(report_id)

        # 新格式：删除整个文件夹
        if os.path.exists(folder_path) and os.path.isdir(folder_path):
            shutil.rmtree(folder_path)
            cls._index_remove(report_id)  # EXECPLAN2 F-7-3: 同步清理索引
            logger.info(f"报告文件夹已删除: {report_id}")
            return True

        # 兼容旧格式：删除单独的文件
        deleted = False
        old_json_path = cls._get_legacy_report_file(report_id, "json")
        old_md_path = cls._get_legacy_report_file(report_id, "md")

        if os.path.exists(old_json_path):
            os.remove(old_json_path)
            deleted = True
        if os.path.exists(old_md_path):
            os.remove(old_md_path)
            deleted = True

        if deleted:
            cls._index_remove(report_id)  # EXECPLAN2 F-7-3: 同步清理索引

        return deleted
