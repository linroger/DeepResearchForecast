"""
OASIS 双平台并行模拟预设脚本
同时运行Twitter和Reddit模拟，读取相同的配置文件

功能特性:
- 双平台（Twitter + Reddit）并行模拟
- 完成模拟后不立即关闭环境，进入等待命令模式
- 支持通过IPC接收Interview命令
- 支持单个Agent采访和批量采访
- 支持远程关闭环境命令

使用方式:
    python run_parallel_simulation.py --config simulation_config.json
    python run_parallel_simulation.py --config simulation_config.json --no-wait  # 完成后立即关闭
    python run_parallel_simulation.py --config simulation_config.json --twitter-only
    python run_parallel_simulation.py --config simulation_config.json --reddit-only

日志结构:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter 平台动作日志
    ├── reddit/
    │   └── actions.jsonl    # Reddit 平台动作日志
    ├── simulation.log       # 主模拟进程日志
    └── run_state.json       # 运行状态（API 查询用）
"""

# ============================================================
# 解决 Windows 编码问题：在所有 import 之前设置 UTF-8 编码
# 这是为了修复 OASIS 第三方库读取文件时未指定编码的问题
# ============================================================
import sys
import os

if sys.platform == 'win32':
    # 设置 Python 默认 I/O 编码为 UTF-8
    # 这会影响所有未指定编码的 open() 调用
    os.environ.setdefault('PYTHONUTF8', '1')
    os.environ.setdefault('PYTHONIOENCODING', 'utf-8')
    
    # 重新配置标准输出流为 UTF-8（解决控制台中文乱码）
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    
    # 强制设置默认编码（影响 open() 函数的默认编码）
    # 注意：这需要在 Python 启动时就设置，运行时设置可能不生效
    # 所以我们还需要 monkey-patch 内置的 open 函数
    import builtins
    _original_open = builtins.open
    
    def _utf8_open(file, mode='r', buffering=-1, encoding=None, errors=None, 
                   newline=None, closefd=True, opener=None):
        """
        包装 open() 函数，对于文本模式默认使用 UTF-8 编码
        这可以修复第三方库（如 OASIS）读取文件时未指定编码的问题
        """
        # 只对文本模式（非二进制）且未指定编码的情况设置默认编码
        if encoding is None and 'b' not in mode:
            encoding = 'utf-8'
        return _original_open(file, mode, buffering, encoding, errors, 
                              newline, closefd, opener)
    
    builtins.open = _utf8_open

# XRUN-14: transformers tokenizers 在 fork 后会逐条刷 "The current process just got forked"
# 警告（曾把 simulation.log 的整个可见尾部淹没，掩盖真实错误）。必须在任何 huggingface
# 相关 import 之前显式禁用 tokenizers 并行才能静音。
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

import argparse
import asyncio
import hashlib
import inspect
import json
import logging
import multiprocessing
import random
import re
import shutil
import signal
import sqlite3
import threading
import time
import uuid
import warnings
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple


# 全局变量：用于信号处理
_shutdown_event = None
_cleanup_done = False
_VALIDATED_CONFIG_MANIFEST_SHA256 = ""


# EXECPLAN2 I-7-2: 确定性随机数种子（默认 None = 维持当前非确定性行为）。
# 设置环境变量 SIM_SEED=<int> 后，调度采样（加权水库 / 概率发帖）变为可复现，
# 使 prepare/run 阶段的快照/黄金测试与 A/B 评估成为可能。未设置时 random.Random()
# 从系统熵播种，与历史上的 random.random() 行为逐次一致（零行为变化）。
def _build_sampling_rng() -> "random.Random":
    """根据 SIM_SEED 构造本进程的采样 RNG（缺省即非确定性，与旧行为一致）。"""
    raw = os.environ.get("SIM_SEED")
    if raw is None or str(raw).strip() == "":
        return random.Random()
    try:
        return random.Random(int(str(raw).strip()))
    except (TypeError, ValueError):
        # 容错：非整数种子退回非确定性，避免因配置错误中断模拟。
        return random.Random()


_RNG = _build_sampling_rng()

# 添加 backend 目录到路径
# 脚本固定位于 backend/scripts/ 目录
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
_backend_dir = os.path.abspath(os.path.join(_scripts_dir, '..'))
_project_root = os.path.abspath(os.path.join(_backend_dir, '..'))
sys.path.insert(0, _scripts_dir)
sys.path.insert(0, _backend_dir)

# 加载项目根目录的 .env 文件（包含 LLM_API_KEY 等配置）。INFRA-12：经 load_project_dotenv
# 加载——行为同 load_dotenv(override=False)，但测试进程（DRF_TEST_PROCESS=1）在收集阶段
# 导入本脚本时不再把开发者 .env 注入 pytest 进程。
from app.utils.env_loading import load_project_dotenv
_env_file = os.path.join(_project_root, '.env')
if os.path.exists(_env_file):
    if load_project_dotenv(_env_file):
        print(f"已加载环境配置: {_env_file}")
else:
    # 尝试加载 backend/.env
    _backend_env = os.path.join(_backend_dir, '.env')
    if load_project_dotenv(_backend_env):
        print(f"已加载环境配置: {_backend_env}")


class MaxTokensWarningFilter(logging.Filter):
    """过滤掉 camel-ai 关于 max_tokens 的警告（我们故意不设置 max_tokens，让模型自行决定）"""
    
    def filter(self, record):
        # 过滤掉包含 max_tokens 警告的日志
        if "max_tokens" in record.getMessage() and "Invalid or missing" in record.getMessage():
            return False
        return True


# 在模块加载时立即添加过滤器，确保在 camel 代码执行前生效
logging.getLogger().addFilter(MaxTokensWarningFilter())


def disable_oasis_logging():
    """
    禁用 OASIS 库的详细日志输出
    OASIS 的日志太冗余（记录每个 agent 的观察和动作），我们使用自己的 action_logger
    """
    # 禁用 OASIS 的所有日志器
    oasis_loggers = [
        "social.agent",
        "social.twitter", 
        "social.rec",
        "oasis.env",
        "table",
    ]
    
    for logger_name in oasis_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.CRITICAL)  # 只记录严重错误
        logger.handlers.clear()
        logger.propagate = False


def init_logging_for_simulation(simulation_dir: str):
    """
    初始化模拟的日志配置
    
    Args:
        simulation_dir: 模拟目录路径
    """
    # 禁用 OASIS 的详细日志
    disable_oasis_logging()
    
    # 清理旧的 log 目录（如果存在）
    old_log_dir = os.path.join(simulation_dir, "log")
    if os.path.exists(old_log_dir):
        import shutil
        shutil.rmtree(old_log_dir, ignore_errors=True)


from action_logger import SimulationLogManager, PlatformActionLogger
from app.utils.oasis_llm import create_oasis_model, get_oasis_semaphore

try:
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType
    import oasis
    from oasis import (
        ActionType,
        LLMAction,
        ManualAction,
        generate_twitter_agent_graph,
        generate_reddit_agent_graph
    )
except ImportError as e:
    print(f"错误: 缺少依赖 {e}")
    print("请先安装: pip install oasis-ai camel-ai")
    sys.exit(1)


# Twitter可用动作（不包含INTERVIEW，INTERVIEW只能通过ManualAction手动触发）
# T3.11: 加入 CREATE_COMMENT（最大结构性收益——让推文形成回复线程，而非只有转发/引用），
# 以及 SEARCH_POSTS / TREND。三者在 camel-oasis 0.2.5 platform.py 均有平台无关的处理器
# （create_comment@1079 / search_posts@773 / trend@1030），对 Twitter 同样可用。
TWITTER_ACTIONS = [
    ActionType.CREATE_POST,
    ActionType.LIKE_POST,
    ActionType.REPOST,
    ActionType.FOLLOW,
    ActionType.DO_NOTHING,
    ActionType.QUOTE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.SEARCH_POSTS,
    ActionType.TREND,
]

# Reddit可用动作（不包含INTERVIEW，INTERVIEW只能通过ManualAction手动触发）
REDDIT_ACTIONS = [
    ActionType.LIKE_POST,
    ActionType.DISLIKE_POST,
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_COMMENT,
    ActionType.DISLIKE_COMMENT,
    ActionType.SEARCH_POSTS,
    ActionType.SEARCH_USER,
    ActionType.TREND,
    ActionType.REFRESH,
    ActionType.DO_NOTHING,
    ActionType.FOLLOW,
    ActionType.MUTE,
]


# ============================================================
# EXECPLAN2 I-2-3: 按角色定制的「动作可供性」（per-role action affordances）
# ------------------------------------------------------------
# 现状：同一平台的所有 Agent 共用一份全局动作清单（TWITTER_ACTIONS / REDDIT_ACTIONS），
# 政府账号、官媒、学生、匿名水军拥有完全相同的可选动作（都能 REPOST/QUOTE/FOLLOW/MUTE…）。
# 现实中可供性与行为习惯是角色相关的：官方账号很少给个人点赞/转发/拉黑，媒体大量引用/造势，
# 活动家激进转发/关注，潜水受众多为点赞/沉默。人设文本会暗示这点，但没有任何东西约束动作空间，
# 于是 LLM 频繁选出「跳戏」的动作，稀释保真度。
#
# 方案：以 entity_type（角色）为键，为每个 Agent 量身裁剪 available_actions。camel-oasis 在
# 构图时已把动作转成 ChatAgent 的工具（SocialAgent.__init__ 把 available_actions 过滤成
# action_tools 并注入 ChatAgent.tools）；ChatAgent 暴露了公开的 remove_tools(name) API，
# 工具名恰为 ActionType.value。因此「构图后按角色裁剪」是库原生支持的——在 generate_*_agent_graph
# 之后、env.reset() 之前，逐个 Agent 移除不属于其角色策略的社交动作工具即可（仅移除社交动作，
# 不动 INTERVIEW 等其它工具）。同时把一句简短的「行为习惯」约束注入 system prompt，让 LLM 自我设限。
#
# 可降级不变式：默认 SIM_ROLE_ACTION_PROFILES!=true → 完全跳过，沿用单一全局清单（逐字节旧行为）。
# 任意环节失败（缺 entity_type、库 API 变动、工具名不匹配）一律 best-effort 跳过该 Agent，绝不中断模拟。
#
# 策略表的「白名单」会与平台 union 清单求交，确保永远不会授予平台不存在/未启用的动作；
# 任何角色都至少保留 CREATE_POST / CREATE_COMMENT / DO_NOTHING，避免把某类角色变成完全惰性。
# ============================================================

# 每个角色策略只在 union 动作集合内做「白名单」过滤；未列出的 entity_type 走 _ROLE_ACTION_DEFAULT。
# 注：键为 entity_type.lower()，与 oasis_profile_generator 的 INDIVIDUAL/GROUP_ENTITY_TYPES 命名一致。
ROLE_ACTION_POLICY = {
    # —— 机构 / 群体 ——
    # 政府机构：几乎只发布官方声明、检索舆情；不给个人点赞/转发/拉黑。
    "governmentagency": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "official": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    # 媒体：大量发帖/引用/转发/造势/评论，构成信息放大主力。
    "mediaoutlet": [
        ActionType.CREATE_POST,
        ActionType.QUOTE_POST,
        ActionType.REPOST,
        ActionType.CREATE_COMMENT,
        ActionType.TREND,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "journalist": [
        ActionType.CREATE_POST,
        ActionType.QUOTE_POST,
        ActionType.REPOST,
        ActionType.CREATE_COMMENT,
        ActionType.SEARCH_POSTS,
        ActionType.SEARCH_USER,
        ActionType.DO_NOTHING,
    ],
    # 高校 / NGO / 公司 / 机构：偏官方口径，少量互动。
    "university": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "ngo": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.QUOTE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "company": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "organization": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "institution": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "group": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.LIKE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    "community": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.LIKE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    # —— 个人 ——
    # 专家 / 教授：发表观点、评论、引用佐证，少量转发。
    "professor": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.QUOTE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.LIKE_POST,
        ActionType.DO_NOTHING,
    ],
    "expert": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.QUOTE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.LIKE_POST,
        ActionType.DO_NOTHING,
    ],
    "faculty": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.QUOTE_POST,
        ActionType.SEARCH_POSTS,
        ActionType.LIKE_POST,
        ActionType.DO_NOTHING,
    ],
    "publicfigure": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.QUOTE_POST,
        ActionType.REPOST,
        ActionType.LIKE_POST,
        ActionType.FOLLOW,
        ActionType.DO_NOTHING,
    ],
    # 活动家：激进——大量转发/关注/评论/造势以扩散立场。
    "activist": [
        ActionType.CREATE_POST,
        ActionType.CREATE_COMMENT,
        ActionType.REPOST,
        ActionType.QUOTE_POST,
        ActionType.LIKE_POST,
        ActionType.FOLLOW,
        ActionType.TREND,
        ActionType.SEARCH_POSTS,
        ActionType.DO_NOTHING,
    ],
    # 学生 / 普通个人：完整社交动作集（最自由）——见 _ROLE_FULL_ACCESS，直接放行平台全部 union。
    # —— 程序化「沉默的大多数」受众（simulation_config_generator.AUDIENCE_ENTITY_TYPE="Audience"）——
    # 以点赞 / 偶尔评论 / 转发 / 大量沉默为主，几乎不发起原创帖、不关注、不拉黑。
    "audience": [
        ActionType.LIKE_POST,
        ActionType.DISLIKE_POST,
        ActionType.LIKE_COMMENT,
        ActionType.REPOST,
        ActionType.CREATE_COMMENT,
        ActionType.DO_NOTHING,
        ActionType.REFRESH,
    ],
}

# 完整动作集角色：最自由的个人账号，直接放行平台全部 union（不做任何裁剪）。
# 等价于设计草图里 'student': TWITTER_ACTIONS 的「完整社交动作集」语义，但与平台无关——
# Reddit 上同样拿到 REDDIT_ACTIONS 全集，而非被 Twitter 清单截断。
_ROLE_FULL_ACCESS = {"student", "alumni", "person"}

# 未匹配到具体角色时的兜底策略：保守地保留发帖/评论/检索/沉默/点赞，避免越权放大类动作。
_ROLE_ACTION_DEFAULT = [
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.LIKE_POST,
    ActionType.SEARCH_POSTS,
    ActionType.DO_NOTHING,
]

# 不变式：任何角色都至少保留这几样基本动作，防止过度限制把某类 Agent 变成完全惰性。
_ROLE_ACTION_FLOOR = {
    ActionType.CREATE_POST,
    ActionType.CREATE_COMMENT,
    ActionType.DO_NOTHING,
}

# 角色 → 注入 system prompt 的「行为习惯」一句话约束（让 LLM 在工具裁剪之外再自我设限）。
# 仅覆盖最容易跳戏的机构/媒体/活动家/受众；未列出的角色不注入额外约束（保持原 persona）。
_ROLE_BEHAVIOR_HINT = {
    "governmentagency": "【行为习惯】你是官方机构账号：通常只发布正式声明或检索舆情，几乎从不给个人点赞、转发或拉黑。",
    "official": "【行为习惯】你是官方机构账号：通常只发布正式声明或检索舆情，几乎从不给个人点赞、转发或拉黑。",
    "mediaoutlet": "【行为习惯】你是媒体账号：以发布报道、引用与转发关键信息、推动话题热度为主，很少给普通用户点赞。",
    "journalist": "【行为习惯】你是记者：以发布报道、引用与求证、关注信源为主，较少随手点赞。",
    "activist": "【行为习惯】你是活动家：积极转发、关注同立场账号、评论与造势以扩散你的主张。",
    "audience": "【行为习惯】你是普通围观受众（沉默的大多数）：多数时候只是点赞或沉默，偶尔评论或转发，几乎不发起原创长帖。",
}


def _build_role_type_map(config: Dict[str, Any]) -> Dict[int, str]:
    """EXECPLAN2 I-2-3: 从 simulation_config 构建 agent_id -> entity_type（小写）映射。

    与 get_agent_names_from_config 同源（config["agent_configs"]，每项含 agent_id/entity_type），
    缺字段则跳过该项。供按角色裁剪动作可供性使用。
    """
    role_map: Dict[int, str] = {}
    for agent_config in config.get("agent_configs", []) or []:
        agent_id = agent_config.get("agent_id")
        entity_type = agent_config.get("entity_type")
        if agent_id is not None and entity_type:
            role_map[agent_id] = str(entity_type).strip().lower()
    return role_map


def _allowed_actions_for_role(entity_type: str, platform_union: List["ActionType"]) -> List["ActionType"]:
    """EXECPLAN2 I-2-3: 计算某角色在给定平台上的「允许动作」白名单。

    策略表白名单 ∩ 平台 union（绝不授予平台不存在/未启用的动作），再并入基本动作下限
    （_ROLE_ACTION_FLOOR，同样需在 union 内）。返回顺序去重、稳定。
    完整动作集角色（_ROLE_FULL_ACCESS）直接返回平台 union 全集，不做裁剪。
    """
    role = (entity_type or "").lower()
    if role in _ROLE_FULL_ACCESS:
        return list(platform_union)
    policy = ROLE_ACTION_POLICY.get(role, _ROLE_ACTION_DEFAULT)
    union_set = set(platform_union)
    allowed_set = (set(policy) & union_set) | (_ROLE_ACTION_FLOOR & union_set)
    # 以平台 union 的顺序产出，便于阅读 / 日志稳定。
    return [a for a in platform_union if a in allowed_set]


def _apply_role_action_profiles(
    agent_graph,
    config: Dict[str, Any],
    platform_union: List["ActionType"],
    log_info,
) -> None:
    """EXECPLAN2 I-2-3: 在构图后、env.reset() 前，按角色裁剪每个 Agent 的社交动作工具。

    机制：camel ChatAgent 把每个动作注册为名为 ActionType.value 的工具。对每个 Agent，
    移除「属于平台 union 但不在该角色白名单」的社交动作工具（仅社交动作，绝不动 INTERVIEW 等
    其它工具）。同时把一句「行为习惯」约束追加进 system prompt，让 LLM 自我设限。

    可降级：任意 Agent 处理失败仅跳过该 Agent（best-effort），不抛出、不中断模拟。
    仅当 SIM_ROLE_ACTION_PROFILES=true 时由调用方触发；默认完全不进入本函数。
    """
    if agent_graph is None:
        return
    role_map = _build_role_type_map(config)
    # 平台所有社交动作的工具名集合——只在这个集合内做增删，避免误删非社交工具。
    union_tool_names = {a.value for a in platform_union}

    restricted = 0
    hinted = 0
    try:
        agents = agent_graph.get_agents()
    except Exception as e:  # noqa: BLE001
        log_info(f"角色动作裁剪跳过（无法枚举 Agent）: {e}")
        return

    for agent_id, agent in agents:
        try:
            entity_type = role_map.get(agent_id, "")
            allowed = _allowed_actions_for_role(entity_type, platform_union)
            allowed_names = {a.value for a in allowed}
            # 待移除 = 平台社交动作 - 允许动作；只在 agent 实际拥有的工具里删。
            to_remove = [
                name for name in union_tool_names
                if name not in allowed_names and name in getattr(agent, "_internal_tools", {})
            ]
            if to_remove:
                agent.remove_tools(to_remove)
                restricted += 1

            # 软约束：把「行为习惯」一句话注入 system prompt（best-effort，失败不影响硬裁剪）。
            hint = _ROLE_BEHAVIOR_HINT.get((entity_type or "").lower())
            if hint and _inject_behavior_hint(agent, hint):
                hinted += 1
        except Exception as e:  # noqa: BLE001
            log_info(f"角色动作裁剪跳过 Agent {agent_id}（已隔离）: {e}")
            continue

    log_info(f"角色动作可供性已应用: 裁剪 {restricted} 个 Agent，注入行为约束 {hinted} 个")


def _inject_behavior_hint(agent, hint: str) -> bool:
    """EXECPLAN2 I-2-3: 把一句行为约束追加进 Agent 的 system prompt（best-effort）。

    走 camel ChatAgent 受支持的路径：基于 _original_system_message 重建系统消息并
    init_messages() 把它重新写入记忆。任何版本差异/缺属性即返回 False（降级，不影响硬裁剪）。
    在 env.reset() 之前调用——reset()→generate_custom_agents 不会重置记忆，注入得以保留。
    """
    try:
        original = getattr(agent, "_original_system_message", None)
        if original is None or not hasattr(original, "content"):
            return False
        if hint in (original.content or ""):
            return True  # 已注入过，幂等
        new_msg = original.create_new_instance((original.content or "") + "\n\n" + hint)
        agent._original_system_message = new_msg
        # 触发系统消息按输出语言重算并重新写入记忆（与 camel 内部行为一致）。
        agent._system_message = agent._generate_system_message_for_output_language()
        agent.init_messages()
        return True
    except Exception:
        return False


def _replace_agent_system_message(agent, content: str) -> None:
    """Replace, rather than append to, the exact effective system message."""
    original = getattr(agent, "_original_system_message", None)
    if original is None or not hasattr(original, "content"):
        raise ValueError("OASIS agent exposes no replaceable system message")
    new_msg = original.create_new_instance(str(content))
    agent._original_system_message = new_msg
    agent._system_message = agent._generate_system_message_for_output_language()
    agent.init_messages()
    actual = getattr(agent, "_original_system_message", None)
    if actual is None or str(getattr(actual, "content", "")) != str(content):
        raise ValueError("OASIS agent did not retain the sealed system message")
    effective = getattr(agent, "_system_message", None)
    if effective is None or str(getattr(effective, "content", "")) != str(content):
        raise ValueError("OASIS appended unsealed effective system-message text")


def _enforce_canonical_reddit_system_messages(
    agent_graph,
    profile_path: str,
) -> List[Dict[str, Any]]:
    """Replace OASIS' demographic template for every current canonical role."""
    role_manifest_path = os.path.splitext(profile_path)[0] + "_roles.json"
    if not os.path.exists(role_manifest_path):
        return []
    from app.services.oasis_profile_generator import (
        CANONICAL_REDDIT_SYSTEM_MESSAGE_VERSION,
        OasisProfileGenerator,
        canonical_reddit_system_message,
    )
    from app.utils.actors import ACTOR_INTELLIGENCE_SCHEMA_VERSION

    manifest = OasisProfileGenerator.validate_role_prompt_manifest(profile_path)
    with open(profile_path, encoding="utf-8") as handle:
        profiles = json.load(handle)
    agents = {int(agent_id): agent for agent_id, agent in agent_graph.get_agents()}
    runtime_rows: List[Dict[str, Any]] = []
    for role in manifest.get("roles") or []:
        if not isinstance(role, dict):
            continue
        contract = role.get("contract")
        if not isinstance(contract, dict) or contract.get(
            "actor_intelligence_schema_version"
        ) != ACTOR_INTELLIGENCE_SCHEMA_VERSION:
            continue
        if role.get("reddit_system_message_version") != (
            CANONICAL_REDDIT_SYSTEM_MESSAGE_VERSION
        ):
            raise ValueError("canonical Reddit system-message schema is missing")
        index = role.get("profile_index")
        if type(index) is not int or not 0 <= index < len(profiles):
            raise ValueError("canonical Reddit role profile index is invalid")
        agent = agents.get(index)
        if agent is None:
            raise ValueError(f"canonical Reddit agent {index} is missing")
        profile = profiles[index]
        base_message = canonical_reddit_system_message(
            profile.get("username"), profile.get("persona")
        )
        base_sha = hashlib.sha256(base_message.encode("utf-8")).hexdigest()
        if role.get("reddit_base_system_message_sha256") != base_sha:
            raise ValueError("canonical Reddit base system-message seal mismatch")
        _replace_agent_system_message(agent, base_message)
        runtime_rows.append({
            "profile_index": index,
            "actor_id": role.get("actor_id"),
            "base_system_message": base_message,
        })
    return runtime_rows


def _attest_canonical_reddit_system_messages(
    agent_graph,
    profile_path: str,
    config: Dict[str, Any],
    runtime_rows: List[Dict[str, Any]],
    config_manifest_sha256: str,
) -> None:
    """Verify and seal final bytes after every allowed system-message injection."""
    if not runtime_rows:
        return
    if not config_manifest_sha256:
        raise ValueError("canonical Reddit runtime lacks a validated config seal")
    agents = {int(agent_id): agent for agent_id, agent in agent_graph.get_agents()}
    brief = str(config.get("world_brief") or "").strip()
    temporal = config.get("temporal_config")
    temporal = temporal if isinstance(temporal, dict) else {}
    calendar = str(temporal.get("mode") or "").strip().lower() == "calendar"
    calendar_unit = str(temporal.get("unit") or "").strip()
    attestations: List[Dict[str, Any]] = []
    for row in runtime_rows:
        expected = str(row["base_system_message"])
        composition = ["canonical_role_only_base"]
        if _world_brief_enabled() and brief:
            expected += "\n\n" + _world_brief_header(config) + "\n" + brief
            composition.append("sealed_world_brief")
        if calendar and calendar_unit:
            expected += "\n\n" + _CALENDAR_ACTION_VOCAB_TEMPLATE.format(
                unit=calendar_unit
            )
            composition.append("sealed_calendar_vocabulary")
        agent = agents.get(int(row["profile_index"]))
        effective = getattr(agent, "_system_message", None)
        actual = str(getattr(effective, "content", ""))
        if actual != expected:
            raise ValueError(
                "canonical Reddit final system message differs from sealed composition"
            )
        if "years old, with an MBTI personality type" in actual:
            raise ValueError("canonical Reddit system message contains demographics")
        attestations.append({
            "profile_index": int(row["profile_index"]),
            "actor_id": row.get("actor_id"),
            "composition": composition,
            "system_message_sha256": hashlib.sha256(
                actual.encode("utf-8")
            ).hexdigest(),
            "system_message_chars": len(actual),
        })
    role_manifest_path = os.path.splitext(profile_path)[0] + "_roles.json"
    with open(role_manifest_path, "rb") as handle:
        role_manifest_sha = hashlib.sha256(handle.read()).hexdigest()
    from app.utils.atomic import write_json_atomic
    write_json_atomic(
        os.path.join(
            os.path.dirname(profile_path),
            "reddit_runtime_system_messages.json",
        ),
        {
            "schema_version": "reddit-runtime-system-messages/v1",
            "simulation_config_manifest_sha256": config_manifest_sha256,
            "actor_role_manifest_sha256": role_manifest_sha,
            "actor_count": len(attestations),
            "messages": attestations,
        },
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    )


# CAL-TEMPORAL: 日历模式一次性动作词汇表（spec §5 verbatim）——一轮=一个日历时段，
# 社交平台动作被重新语义化为"时段级战略动作"，开局注入一次即可（幂等）。
_CALENDAR_ACTION_VOCAB_TEMPLATE = (
    "In this simulation each round is one calendar {unit}. Action meanings:\n"
    "CREATE_POST = your period communiqué (decision/announcement/strategic move);\n"
    "QUOTE_POST / CREATE_COMMENT = strategic response or counter-move;\n"
    "FOLLOW = alliance or coalition formation; LIKE / REPOST = public endorsement;\n"
    "DO_NOTHING = strategic patience."
)


def _inject_calendar_vocabulary(agent_graph, temporal_config, log_info) -> None:
    """CAL-TEMPORAL: 日历模式把动作词汇表一次性追加进每个 Agent 的 system prompt。

    机制与 _inject_world_brief 完全一致（复用 _inject_behavior_hint 的幂等注入路径），
    必须在 oasis.make()/env.reset() 之前调用。可降级：unit 缺失 / agent_graph 不可枚举 /
    单个 Agent 失败均静默跳过，绝不中断模拟。hours 模式（无 temporal_config）从不调用。
    """
    unit = str((temporal_config or {}).get("unit", "") or "").strip()
    if agent_graph is None or not unit:
        return
    hint = _CALENDAR_ACTION_VOCAB_TEMPLATE.format(unit=unit)
    try:
        agents = agent_graph.get_agents()
    except Exception as e:  # noqa: BLE001
        log_info(f"日历动作词汇注入跳过（无法枚举 Agent）: {e}")
        return
    injected = 0
    total = 0
    for _agent_id, agent in agents:
        total += 1
        try:
            if _inject_behavior_hint(agent, hint):
                injected += 1
        except Exception:  # noqa: BLE001 — 单个 Agent 失败不影响其余（best-effort）
            continue
    log_info(f"日历动作词汇已注入 {injected}/{total} 个 Agent（unit={unit}）")


_WORLD_BRIEF_HEADER = "# WORLD BRIEF（共同世界背景）"
_WORLD_BRIEF_HEADER_EN = "# WORLD BRIEF (shared world background)"


def _world_brief_header(config: Dict[str, Any]) -> str:
    """世界简报块标题：英文模拟用英文标题，其余保持历史中文标题（逐字节不变）。
    注入（_inject_world_brief）与 Reddit 封印复核（_attest_...）必须用同一函数取标题。"""
    return _WORLD_BRIEF_HEADER_EN if _sim_output_language(config) == "English" else _WORLD_BRIEF_HEADER


def _inject_world_brief(agent_graph, world_brief, log_info,
                        header: str = _WORLD_BRIEF_HEADER) -> None:
    """NEXTSTEPS SIM_WORLD_BRIEF: 把 config.world_brief（核心预测问题 + 局势简报 + 热点话题）
    作为共同世界背景追加进每个 Agent 的 system prompt。

    机制与 _inject_behavior_hint 完全一致（基于 _original_system_message 重建系统消息并
    init_messages() 重新写入记忆，幂等），必须在 oasis.make()/env.reset() 之前调用。
    可降级：world_brief 为空 / agent_graph 不可枚举 / 单个 Agent 失败均静默跳过，绝不中断模拟。
    """
    brief = str(world_brief or "").strip()
    if agent_graph is None or not brief:
        return
    block = header + "\n" + brief
    try:
        agents = agent_graph.get_agents()
    except Exception as e:  # noqa: BLE001
        log_info(f"世界简报注入跳过（无法枚举 Agent）: {e}")
        return
    injected = 0
    total = 0
    for _agent_id, agent in agents:
        total += 1
        try:
            if _inject_behavior_hint(agent, block):
                injected += 1
        except Exception:  # noqa: BLE001 — 单个 Agent 失败不影响其余（best-effort）
            continue
    log_info(f"世界简报已注入 {injected}/{total} 个 Agent（简报 {len(brief)} 字）")


def _world_brief_enabled() -> bool:
    """NEXTSTEPS SIM_WORLD_BRIEF: 世界简报注入开关（默认开）。

    与其它 SIM_* 开关同风格：env 优先（子进程独立可控），其次 app.config.Config，
    最后默认 true。置 false → 完全跳过注入（system prompt 与旧行为逐字节一致）。
    """
    return _flag_true("SIM_WORLD_BRIEF", "true")


def _role_action_profiles_enabled() -> bool:
    """EXECPLAN2 I-2-3: 特性开关（与 SIM_WIRE_RECSYS / SIM_EMERGENT_METRICS 同风格的环境变量）。

    默认关闭 → 维持单一全局动作清单的旧行为（可降级不变式）。
    """
    return os.environ.get("SIM_ROLE_ACTION_PROFILES", "false").strip().lower() == "true"


def _cfg_flag(name: str, default: str) -> str:
    """读取运行开关：环境变量优先（子进程独立可控），其次 app.config.Config（由 infra
    统一定义），最后落安全默认。Config 不可导入时绝不阻断模拟。"""
    raw = os.environ.get(name)
    if raw is not None and str(raw).strip() != "":
        return str(raw).strip()
    try:
        from app.config import Config
        val = getattr(Config, name, default)
        return default if val is None else str(val)
    except Exception:
        return default


def _flag_true(name: str, default: str) -> bool:
    return _cfg_flag(name, default).strip().lower() in ("true", "1", "yes", "on")


def _event_provenance_enabled() -> bool:
    """SIM-5 SIM_EVENT_PROVENANCE（默认开）：定时事件帖带来源前缀，回应阶段/立场轨迹/
    决策名册不再把注入内容记作发帖行为者的行为。false → 旧行为逐字节一致。"""
    return _flag_true("SIM_EVENT_PROVENANCE", "true")


def _event_post_contents_for_run(event_config: Any) -> set:
    """SIM-5：回应阶段识别事件帖用的帖文集合（与 fire_scheduled_events 同一标注助手生成）。
    开关关 / 无定时事件 → 空集（回应阶段逐字节走旧路径）。"""
    if not _event_provenance_enabled() or not isinstance(event_config, dict):
        return set()
    try:
        from app.services.sim_event_provenance import event_post_contents
        return event_post_contents(event_config.get("scheduled_events") or [], labelled=True)
    except Exception:  # noqa: BLE001 — 附加层，失败只退回旧渲染，绝不中断模拟
        return set()


# IPC相关常量
IPC_COMMANDS_DIR = "ipc_commands"
IPC_RESPONSES_DIR = "ipc_responses"
ENV_STATUS_FILE = "env_status.json"
# RUN-10: 与 simulation_ipc.SimulationIPCClient 的 F-12-7 取消协议对齐——客户端超时后
# 会写 <command_id>.cancel；服务端必须在执行前/写响应前感知，否则被放弃的采访照跑不误。
IPC_CANCEL_SUFFIX = ".cancel"


def _ipc_write_json(path: str, payload: Dict[str, Any]) -> None:
    """RUN-10: 状态/响应文件被客户端与 runner 轮询读取，必须原子写避免读到半截 JSON。
    原子写助手不可用时降级为旧的直接写（保持旧行为而非崩溃）。"""
    try:
        from app.utils.atomic import write_json_atomic
        write_json_atomic(path, payload)
    except Exception:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

class CommandType:
    """命令类型常量"""
    INTERVIEW = "interview"
    BATCH_INTERVIEW = "batch_interview"
    CLOSE_ENV = "close_env"


class ParallelIPCHandler:
    """
    双平台IPC命令处理器
    
    管理两个平台的环境，处理Interview命令
    """
    
    def __init__(
        self,
        simulation_dir: str,
        twitter_env=None,
        twitter_agent_graph=None,
        reddit_env=None,
        reddit_agent_graph=None
    ):
        self.simulation_dir = simulation_dir
        self.twitter_env = twitter_env
        self.twitter_agent_graph = twitter_agent_graph
        self.reddit_env = reddit_env
        self.reddit_agent_graph = reddit_agent_graph
        
        self.commands_dir = os.path.join(simulation_dir, IPC_COMMANDS_DIR)
        self.responses_dir = os.path.join(simulation_dir, IPC_RESPONSES_DIR)
        self.status_file = os.path.join(simulation_dir, ENV_STATUS_FILE)
        
        # 确保目录存在
        os.makedirs(self.commands_dir, exist_ok=True)
        os.makedirs(self.responses_dir, exist_ok=True)

        # XRUN-14: 空闲计时基准——每处理一条命令即刷新，供 main 的等待循环做空闲自动关闭。
        self.last_command_at = time.monotonic()

    def update_status(self, status: str):
        """更新环境状态（RUN-10: 原子写，runner 会轮询此文件）"""
        _ipc_write_json(self.status_file, {
            "status": status,
            "twitter_available": self.twitter_env is not None,
            "reddit_available": self.reddit_env is not None,
            "timestamp": datetime.now().isoformat()
        })

    def poll_command(self) -> Optional[Dict[str, Any]]:
        """轮询获取待处理命令

        RUN-10: 客户端超时/放弃的命令带 .cancel 标记——执行前跳过并清理，
        不再为无人等待的采访烧 LLM 配额，也不让 .cancel 文件无限累积。
        """
        if not os.path.exists(self.commands_dir):
            return None

        # 获取命令文件（按时间排序）
        command_files = []
        for filename in os.listdir(self.commands_dir):
            if filename.endswith('.json'):
                filepath = os.path.join(self.commands_dir, filename)
                try:
                    command_files.append((filepath, os.path.getmtime(filepath)))
                except OSError:
                    continue

        command_files.sort(key=lambda x: x[1])

        for filepath, _ in command_files:
            command_id = os.path.basename(filepath)[:-len('.json')]
            cancel_file = os.path.join(
                self.commands_dir, f"{command_id}{IPC_CANCEL_SUFFIX}")
            if os.path.exists(cancel_file):
                for path in (filepath, cancel_file):
                    try:
                        os.remove(path)
                    except OSError:
                        pass
                continue
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                continue

        return None

    def send_response(self, command_id: str, status: str, result: Dict = None, error: str = None):
        """发送响应

        RUN-10 (F-6-6): 客户端超时后会删除命令文件并写 .cancel——此时跳过写出，
        避免 ipc_responses/ 里堆积无人消费的孤儿响应；响应本身原子写，
        防止客户端轮询读到半截 JSON。
        """
        command_file = os.path.join(self.commands_dir, f"{command_id}.json")
        cancel_file = os.path.join(
            self.commands_dir, f"{command_id}{IPC_CANCEL_SUFFIX}")

        if os.path.exists(cancel_file) or not os.path.exists(command_file):
            for path in (command_file, cancel_file):
                try:
                    os.remove(path)
                except OSError:
                    pass
            print(f"  客户端已放弃命令，跳过写出响应: command_id={command_id}")
            return

        response = {
            "command_id": command_id,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": datetime.now().isoformat()
        }

        response_file = os.path.join(self.responses_dir, f"{command_id}.json")
        _ipc_write_json(response_file, response)

        # 删除命令文件及取消标记（尽力而为）
        for path in (command_file, cancel_file):
            try:
                os.remove(path)
            except OSError:
                pass
    
    def _get_env_and_graph(self, platform: str):
        """
        获取指定平台的环境和agent_graph
        
        Args:
            platform: 平台名称 ("twitter" 或 "reddit")
            
        Returns:
            (env, agent_graph, platform_name) 或 (None, None, None)
        """
        if platform == "twitter" and self.twitter_env:
            return self.twitter_env, self.twitter_agent_graph, "twitter"
        elif platform == "reddit" and self.reddit_env:
            return self.reddit_env, self.reddit_agent_graph, "reddit"
        else:
            return None, None, None
    
    async def _interview_single_platform(self, agent_id: int, prompt: str, platform: str) -> Dict[str, Any]:
        """
        在单个平台上执行Interview
        
        Returns:
            包含结果的字典，或包含error的字典
        """
        env, agent_graph, actual_platform = self._get_env_and_graph(platform)
        
        if not env or not agent_graph:
            return {"platform": platform, "error": f"{platform}平台不可用"}
        
        try:
            agent = agent_graph.get_agent(agent_id)
            interview_action = ManualAction(
                action_type=ActionType.INTERVIEW,
                action_args={"prompt": prompt}
            )
            actions = {agent: interview_action}
            await env.step(actions)
            
            result = self._get_interview_result(agent_id, actual_platform)
            result["platform"] = actual_platform
            return result
            
        except Exception as e:
            return {"platform": platform, "error": str(e)}
    
    async def handle_interview(self, command_id: str, agent_id: int, prompt: str, platform: str = None) -> bool:
        """
        处理单个Agent采访命令
        
        Args:
            command_id: 命令ID
            agent_id: Agent ID
            prompt: 采访问题
            platform: 指定平台（可选）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None/不指定: 同时采访两个平台，返回整合结果
            
        Returns:
            True 表示成功，False 表示失败
        """
        # 如果指定了平台，只采访该平台
        if platform in ("twitter", "reddit"):
            result = await self._interview_single_platform(agent_id, prompt, platform)
            
            if "error" in result:
                self.send_response(command_id, "failed", error=result["error"])
                print(f"  Interview失败: agent_id={agent_id}, platform={platform}, error={result['error']}")
                return False
            else:
                self.send_response(command_id, "completed", result=result)
                print(f"  Interview完成: agent_id={agent_id}, platform={platform}")
                return True
        
        # 未指定平台：同时采访两个平台
        if not self.twitter_env and not self.reddit_env:
            self.send_response(command_id, "failed", error="没有可用的模拟环境")
            return False
        
        results = {
            "agent_id": agent_id,
            "prompt": prompt,
            "platforms": {}
        }
        success_count = 0
        
        # 并行采访两个平台
        tasks = []
        platforms_to_interview = []
        
        if self.twitter_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "twitter"))
            platforms_to_interview.append("twitter")
        
        if self.reddit_env:
            tasks.append(self._interview_single_platform(agent_id, prompt, "reddit"))
            platforms_to_interview.append("reddit")
        
        # 并行执行
        platform_results = await asyncio.gather(*tasks)
        
        for platform_name, platform_result in zip(platforms_to_interview, platform_results):
            results["platforms"][platform_name] = platform_result
            if "error" not in platform_result:
                success_count += 1
        
        if success_count > 0:
            self.send_response(command_id, "completed", result=results)
            print(f"  Interview完成: agent_id={agent_id}, 成功平台数={success_count}/{len(platforms_to_interview)}")
            return True
        else:
            errors = [f"{p}: {r.get('error', '未知错误')}" for p, r in results["platforms"].items()]
            self.send_response(command_id, "failed", error="; ".join(errors))
            print(f"  Interview失败: agent_id={agent_id}, 所有平台都失败")
            return False
    
    async def handle_batch_interview(self, command_id: str, interviews: List[Dict], platform: str = None) -> bool:
        """
        处理批量采访命令
        
        Args:
            command_id: 命令ID
            interviews: [{"agent_id": int, "prompt": str, "platform": str(optional)}, ...]
            platform: 默认平台（可被每个interview项覆盖）
                - "twitter": 只采访Twitter平台
                - "reddit": 只采访Reddit平台
                - None/不指定: 每个Agent同时采访两个平台
        """
        # 按平台分组
        twitter_interviews = []
        reddit_interviews = []
        both_platforms_interviews = []  # 需要同时采访两个平台的
        
        for interview in interviews:
            item_platform = interview.get("platform", platform)
            if item_platform == "twitter":
                twitter_interviews.append(interview)
            elif item_platform == "reddit":
                reddit_interviews.append(interview)
            else:
                # 未指定平台：两个平台都采访
                both_platforms_interviews.append(interview)
        
        # 把 both_platforms_interviews 拆分到两个平台
        if both_platforms_interviews:
            if self.twitter_env:
                twitter_interviews.extend(both_platforms_interviews)
            if self.reddit_env:
                reddit_interviews.extend(both_platforms_interviews)
        
        results = {}
        
        # 处理Twitter平台的采访
        if twitter_interviews and self.twitter_env:
            try:
                twitter_actions = {}
                for interview in twitter_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.twitter_agent_graph.get_agent(agent_id)
                        twitter_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  警告: 无法获取Twitter Agent {agent_id}: {e}")
                
                if twitter_actions:
                    await self.twitter_env.step(twitter_actions)
                    
                    for interview in twitter_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "twitter")
                        result["platform"] = "twitter"
                        results[f"twitter_{agent_id}"] = result
            except Exception as e:
                print(f"  Twitter批量Interview失败: {e}")
        
        # 处理Reddit平台的采访
        if reddit_interviews and self.reddit_env:
            try:
                reddit_actions = {}
                for interview in reddit_interviews:
                    agent_id = interview.get("agent_id")
                    prompt = interview.get("prompt", "")
                    try:
                        agent = self.reddit_agent_graph.get_agent(agent_id)
                        reddit_actions[agent] = ManualAction(
                            action_type=ActionType.INTERVIEW,
                            action_args={"prompt": prompt}
                        )
                    except Exception as e:
                        print(f"  警告: 无法获取Reddit Agent {agent_id}: {e}")
                
                if reddit_actions:
                    await self.reddit_env.step(reddit_actions)
                    
                    for interview in reddit_interviews:
                        agent_id = interview.get("agent_id")
                        result = self._get_interview_result(agent_id, "reddit")
                        result["platform"] = "reddit"
                        results[f"reddit_{agent_id}"] = result
            except Exception as e:
                print(f"  Reddit批量Interview失败: {e}")
        
        if results:
            self.send_response(command_id, "completed", result={
                "interviews_count": len(results),
                "results": results
            })
            print(f"  批量Interview完成: {len(results)} 个Agent")
            return True
        else:
            self.send_response(command_id, "failed", error="没有成功的采访")
            return False
    
    def _get_interview_result(self, agent_id: int, platform: str) -> Dict[str, Any]:
        """从数据库获取最新的Interview结果"""
        db_path = os.path.join(self.simulation_dir, f"{platform}_simulation.db")
        
        result = {
            "agent_id": agent_id,
            "response": None,
            "timestamp": None
        }
        
        if not os.path.exists(db_path):
            return result
        
        try:
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            
            # 查询最新的Interview记录
            cursor.execute("""
                SELECT user_id, info, created_at
                FROM trace
                WHERE action = ? AND user_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (ActionType.INTERVIEW.value, agent_id))
            
            row = cursor.fetchone()
            if row:
                user_id, info_json, created_at = row
                try:
                    info = json.loads(info_json) if info_json else {}
                    result["response"] = info.get("response", info)
                    result["timestamp"] = created_at
                except json.JSONDecodeError:
                    result["response"] = info_json
            
            conn.close()
            
        except Exception as e:
            print(f"  读取Interview结果失败: {e}")
        
        return result
    
    async def process_commands(self) -> bool:
        """
        处理所有待处理命令
        
        Returns:
            True 表示继续运行，False 表示应该退出
        """
        command = self.poll_command()
        if not command:
            return True

        # XRUN-14: 有命令到达即刷新空闲计时（采访期间不会被空闲超时误关）。
        self.last_command_at = time.monotonic()

        command_id = command.get("command_id")
        command_type = command.get("command_type")
        args = command.get("args", {})
        
        print(f"\n收到IPC命令: {command_type}, id={command_id}")
        
        if command_type == CommandType.INTERVIEW:
            await self.handle_interview(
                command_id,
                args.get("agent_id", 0),
                args.get("prompt", ""),
                args.get("platform")
            )
            # XRUN-14: 长采访结束后再刷新一次，避免执行耗时被计入空闲时间
            self.last_command_at = time.monotonic()
            return True

        elif command_type == CommandType.BATCH_INTERVIEW:
            await self.handle_batch_interview(
                command_id,
                args.get("interviews", []),
                args.get("platform")
            )
            # XRUN-14: 长采访结束后再刷新一次，避免执行耗时被计入空闲时间
            self.last_command_at = time.monotonic()
            return True
            
        elif command_type == CommandType.CLOSE_ENV:
            print("收到关闭环境命令")
            self.send_response(command_id, "completed", result={"message": "环境即将关闭"})
            return False
        
        else:
            self.send_response(command_id, "failed", error=f"未知命令类型: {command_type}")
            return True


def load_config(
    config_path: str,
    expected_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Load the exact child-executed bytes and optionally enforce their seal."""
    with open(config_path, "rb") as handle:
        config_bytes = handle.read()
    if expected_sha256 and hashlib.sha256(config_bytes).hexdigest() != expected_sha256:
        raise ValueError("simulation config changed after seal validation")
    config = json.loads(config_bytes.decode("utf-8"))
    if not isinstance(config, dict):
        raise ValueError("simulation config must be an object")
    return config


def validate_direct_child_config_seal(
    config_path: str,
    expected_manifest_sha256: Optional[str] = None,
) -> Dict[str, Any]:
    """Revalidate the READY artifact closure at the direct child boundary."""
    simulation_dir = os.path.dirname(os.path.abspath(config_path))
    state_path = os.path.join(simulation_dir, "state.json")
    state: Dict[str, Any] = {}
    if os.path.exists(state_path):
        with open(state_path, encoding="utf-8") as handle:
            loaded = json.load(handle)
        if isinstance(loaded, dict):
            state = loaded
    state_manifest_sha = str(
        state.get("simulation_config_manifest_sha256") or ""
    )
    state_config_sha = str(state.get("simulation_config_sha256") or "")
    if (
        expected_manifest_sha256
        and state_manifest_sha
        and expected_manifest_sha256 != state_manifest_sha
    ):
        raise ValueError("runner and prepared state disagree on config seal")

    current_role_evidence = False
    for filename in (
        "reddit_profiles_roles.json",
        "twitter_profiles_roles.json",
    ):
        path = os.path.join(simulation_dir, filename)
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8") as handle:
            role_manifest = json.load(handle)
        if isinstance(role_manifest, dict) and (
            role_manifest.get("role_contract_version") != "actor-role/v1"
            or role_manifest.get("actor_context_required")
        ):
            current_role_evidence = True
    require = bool(
        expected_manifest_sha256
        or state_manifest_sha
        or current_role_evidence
        or state.get("actor_context_count")
    )
    if current_role_evidence and not (state_manifest_sha and state_config_sha):
        raise ValueError(
            "current actor roles require state-bound simulation config fingerprints"
        )
    if require and os.path.basename(config_path) != "simulation_config.json":
        raise ValueError("sealed child config must be simulation_config.json")
    from app.services.simulation_manager import validate_simulation_config_seal
    return validate_simulation_config_seal(
        simulation_dir,
        expected_manifest_sha256=(
            expected_manifest_sha256 or state_manifest_sha or None
        ),
        expected_config_sha256=(state_config_sha or None),
        expected_simulation_id=(str(state.get("simulation_id") or "") or None),
        require=require,
    )


# 需要过滤掉的非核心动作类型（这些动作对分析价值较低）
FILTERED_ACTIONS = {'refresh', 'sign_up'}

# 动作类型映射表（数据库中的名称 -> 标准名称）
ACTION_TYPE_MAP = {
    'create_post': 'CREATE_POST',
    'like_post': 'LIKE_POST',
    'dislike_post': 'DISLIKE_POST',
    'repost': 'REPOST',
    'quote_post': 'QUOTE_POST',
    'follow': 'FOLLOW',
    'mute': 'MUTE',
    'create_comment': 'CREATE_COMMENT',
    'like_comment': 'LIKE_COMMENT',
    'dislike_comment': 'DISLIKE_COMMENT',
    'search_posts': 'SEARCH_POSTS',
    'search_user': 'SEARCH_USER',
    'trend': 'TREND',
    'do_nothing': 'DO_NOTHING',
    'interview': 'INTERVIEW',
}


def get_agent_names_from_config(config: Dict[str, Any]) -> Dict[int, str]:
    """
    从 simulation_config 中获取 agent_id -> entity_name 的映射
    
    这样可以在 actions.jsonl 中显示真实的实体名称，而不是 "Agent_0" 这样的代号
    
    Args:
        config: simulation_config.json 的内容
        
    Returns:
        agent_id -> entity_name 的映射字典
    """
    agent_names = {}
    agent_configs = config.get("agent_configs", [])
    
    for agent_config in agent_configs:
        agent_id = agent_config.get("agent_id")
        entity_name = agent_config.get("entity_name", f"Agent_{agent_id}")
        if agent_id is not None:
            agent_names[agent_id] = entity_name
    
    return agent_names


def fetch_new_actions_from_db(
    db_path: str,
    last_rowid: int,
    agent_names: Dict[int, str]
) -> Tuple[List[Dict[str, Any]], int]:
    """
    从数据库中获取新的动作记录，并补充完整的上下文信息
    
    Args:
        db_path: 数据库文件路径
        last_rowid: 上次读取的最大 rowid 值（使用 rowid 而不是 created_at，因为不同平台的 created_at 格式不同）
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        (actions_list, new_last_rowid)
        - actions_list: 动作列表，每个元素包含 agent_id, agent_name, action_type, action_args（含上下文信息）
        - new_last_rowid: 新的最大 rowid 值
    """
    actions = []
    new_last_rowid = last_rowid
    
    if not os.path.exists(db_path):
        return actions, new_last_rowid
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # 使用 rowid 来追踪已处理的记录（rowid 是 SQLite 的内置自增字段）
        # 这样可以避免 created_at 格式差异问题（Twitter 用整数，Reddit 用日期时间字符串）
        cursor.execute("""
            SELECT rowid, user_id, action, info
            FROM trace
            WHERE rowid > ?
            ORDER BY rowid ASC
        """, (last_rowid,))
        
        for rowid, user_id, action, info_json in cursor.fetchall():
            # 更新最大 rowid
            new_last_rowid = rowid
            
            # 过滤非核心动作
            if action in FILTERED_ACTIONS:
                continue
            
            # 解析动作参数
            try:
                action_args = json.loads(info_json) if info_json else {}
            except json.JSONDecodeError:
                action_args = {}
            
            # 精简 action_args，只保留关键字段（保留完整内容，不截断）
            simplified_args = {}
            if 'content' in action_args:
                simplified_args['content'] = action_args['content']
            if 'post_id' in action_args:
                simplified_args['post_id'] = action_args['post_id']
            if 'comment_id' in action_args:
                simplified_args['comment_id'] = action_args['comment_id']
            if 'quoted_id' in action_args:
                simplified_args['quoted_id'] = action_args['quoted_id']
            if 'new_post_id' in action_args:
                simplified_args['new_post_id'] = action_args['new_post_id']
            if 'follow_id' in action_args:
                simplified_args['follow_id'] = action_args['follow_id']
            if 'query' in action_args:
                simplified_args['query'] = action_args['query']
            if 'like_id' in action_args:
                simplified_args['like_id'] = action_args['like_id']
            if 'dislike_id' in action_args:
                simplified_args['dislike_id'] = action_args['dislike_id']
            
            # 转换动作类型名称
            action_type = ACTION_TYPE_MAP.get(action, action.upper())
            
            # 补充上下文信息（帖子内容、用户名等）
            _enrich_action_context(cursor, action_type, simplified_args, agent_names)
            
            actions.append({
                'agent_id': user_id,
                'agent_name': agent_names.get(user_id, f'Agent_{user_id}'),
                'action_type': action_type,
                'action_args': simplified_args,
            })
        
        conn.close()
    except Exception as e:
        print(f"读取数据库动作失败: {e}")
    
    return actions, new_last_rowid


def _enrich_action_context(
    cursor,
    action_type: str,
    action_args: Dict[str, Any],
    agent_names: Dict[int, str]
) -> None:
    """
    为动作补充上下文信息（帖子内容、用户名等）
    
    Args:
        cursor: 数据库游标
        action_type: 动作类型
        action_args: 动作参数（会被修改）
        agent_names: agent_id -> agent_name 映射
    """
    try:
        # 点赞/踩帖子：补充帖子内容和作者
        if action_type in ('LIKE_POST', 'DISLIKE_POST'):
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
        
        # 转发帖子：补充原帖内容和作者
        elif action_type == 'REPOST':
            new_post_id = action_args.get('new_post_id')
            if new_post_id:
                # 转发帖子的 original_post_id 指向原帖
                cursor.execute("""
                    SELECT original_post_id FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    original_post_id = row[0]
                    original_info = _get_post_info(cursor, original_post_id, agent_names)
                    if original_info:
                        action_args['original_content'] = original_info.get('content', '')
                        action_args['original_author_name'] = original_info.get('author_name', '')
        
        # 引用帖子：补充原帖内容、作者和引用评论
        elif action_type == 'QUOTE_POST':
            quoted_id = action_args.get('quoted_id')
            new_post_id = action_args.get('new_post_id')
            
            if quoted_id:
                original_info = _get_post_info(cursor, quoted_id, agent_names)
                if original_info:
                    action_args['original_content'] = original_info.get('content', '')
                    action_args['original_author_name'] = original_info.get('author_name', '')
            
            # 获取引用帖子的评论内容（quote_content）
            if new_post_id:
                cursor.execute("""
                    SELECT quote_content FROM post WHERE post_id = ?
                """, (new_post_id,))
                row = cursor.fetchone()
                if row and row[0]:
                    action_args['quote_content'] = row[0]
        
        # 关注用户：补充被关注用户的名称
        elif action_type == 'FOLLOW':
            follow_id = action_args.get('follow_id')
            if follow_id:
                # 从 follow 表获取 followee_id
                cursor.execute("""
                    SELECT followee_id FROM follow WHERE follow_id = ?
                """, (follow_id,))
                row = cursor.fetchone()
                if row:
                    followee_id = row[0]
                    target_name = _get_user_name(cursor, followee_id, agent_names)
                    if target_name:
                        action_args['target_user_name'] = target_name
        
        # 屏蔽用户：补充被屏蔽用户的名称
        elif action_type == 'MUTE':
            # 从 action_args 中获取 user_id 或 target_id
            target_id = action_args.get('user_id') or action_args.get('target_id')
            if target_id:
                target_name = _get_user_name(cursor, target_id, agent_names)
                if target_name:
                    action_args['target_user_name'] = target_name
        
        # 点赞/踩评论：补充评论内容和作者
        elif action_type in ('LIKE_COMMENT', 'DISLIKE_COMMENT'):
            comment_id = action_args.get('comment_id')
            if comment_id:
                comment_info = _get_comment_info(cursor, comment_id, agent_names)
                if comment_info:
                    action_args['comment_content'] = comment_info.get('content', '')
                    action_args['comment_author_name'] = comment_info.get('author_name', '')
        
        # 发表评论：补充所评论的帖子信息
        elif action_type == 'CREATE_COMMENT':
            post_id = action_args.get('post_id')
            if post_id:
                post_info = _get_post_info(cursor, post_id, agent_names)
                if post_info:
                    action_args['post_content'] = post_info.get('content', '')
                    action_args['post_author_name'] = post_info.get('author_name', '')
    
    except Exception as e:
        # 补充上下文失败不影响主流程
        print(f"补充动作上下文失败: {e}")


def _get_post_info(
    cursor,
    post_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    获取帖子信息
    
    Args:
        cursor: 数据库游标
        post_id: 帖子ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        包含 content 和 author_name 的字典，或 None
    """
    try:
        cursor.execute("""
            SELECT p.content, p.user_id, u.agent_id
            FROM post p
            LEFT JOIN user u ON p.user_id = u.user_id
            WHERE p.post_id = ?
        """, (post_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # 优先使用 agent_names 中的名称
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # 从 user 表获取名称
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def _get_user_name(
    cursor,
    user_id: int,
    agent_names: Dict[int, str]
) -> Optional[str]:
    """
    获取用户名称
    
    Args:
        cursor: 数据库游标
        user_id: 用户ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        用户名称，或 None
    """
    try:
        cursor.execute("""
            SELECT agent_id, name, user_name FROM user WHERE user_id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row:
            agent_id = row[0]
            name = row[1]
            user_name = row[2]
            
            # 优先使用 agent_names 中的名称
            if agent_id is not None and agent_id in agent_names:
                return agent_names[agent_id]
            return name or user_name or ''
    except Exception:
        pass
    return None


def _get_comment_info(
    cursor,
    comment_id: int,
    agent_names: Dict[int, str]
) -> Optional[Dict[str, str]]:
    """
    获取评论信息
    
    Args:
        cursor: 数据库游标
        comment_id: 评论ID
        agent_names: agent_id -> agent_name 映射
        
    Returns:
        包含 content 和 author_name 的字典，或 None
    """
    try:
        cursor.execute("""
            SELECT c.content, c.user_id, u.agent_id
            FROM comment c
            LEFT JOIN user u ON c.user_id = u.user_id
            WHERE c.comment_id = ?
        """, (comment_id,))
        row = cursor.fetchone()
        if row:
            content = row[0] or ''
            user_id = row[1]
            agent_id = row[2]
            
            # 优先使用 agent_names 中的名称
            author_name = ''
            if agent_id is not None and agent_id in agent_names:
                author_name = agent_names[agent_id]
            elif user_id:
                # 从 user 表获取名称
                cursor.execute("SELECT name, user_name FROM user WHERE user_id = ?", (user_id,))
                user_row = cursor.fetchone()
                if user_row:
                    author_name = user_row[0] or user_row[1] or ''
            
            return {'content': content, 'author_name': author_name}
    except Exception:
        pass
    return None


def create_model(config: Dict[str, Any], use_boost: bool = False):
    """创建LLM模型。

    委托给 app.utils.oasis_llm.create_oasis_model，按 LLM_PROVIDER 选择后端：
    - claude-cli / codex-cli: CLI 桥接（默认）
    - openai: ModelFactory OpenAI 路径，并保留双 LLM（boost）加速配置
      （通用配置 LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME，
       加速配置 LLM_BOOST_API_KEY/LLM_BOOST_BASE_URL/LLM_BOOST_MODEL_NAME）

    Args:
        config: 模拟配置字典
        use_boost: openai 提供方时是否使用加速 LLM 配置（如果可用）
    """
    return create_oasis_model(config=config, use_boost=use_boost)


def _weighted_sample_without_replacement(items: List, k: int) -> List:
    """按权重不放回采样 k 个（Efraimidis-Spirakis A-Res）。items: [(id, weight), ...]。"""
    if not items or k <= 0:
        return []
    if k >= len(items):
        return [i for i, _ in items]
    keyed = []
    for item_id, w in items:
        w = max(1e-6, float(w))
        keyed.append((_RNG.random() ** (1.0 / w), item_id))  # EXECPLAN2 I-7-2: 可复现采样
    keyed.sort(reverse=True)
    return [item_id for _, item_id in keyed[:k]]


def _resolve_hour_multiplier(time_config: Dict[str, Any], current_hour: int) -> float:
    """RUN-5: 完整消费配置生成器给出的时段乘子阶梯。此前只认 peak/off_peak，
    morning_hours/work_hours（生成器一直在产出）被静默忽略——白天非高峰全按 1.0 跑，
    配置承诺的昼夜活跃曲线并未实现。缺失的键行为与旧逻辑逐字节一致（回退 1.0）。"""
    peak_hours = time_config.get("peak_hours", [9, 10, 11, 14, 15, 20, 21, 22])
    off_peak_hours = time_config.get("off_peak_hours", [0, 1, 2, 3, 4, 5])
    morning_hours = time_config.get("morning_hours", [])
    work_hours = time_config.get("work_hours", [])

    if current_hour in peak_hours:
        return time_config.get("peak_activity_multiplier", 1.5)
    if current_hour in off_peak_hours:
        return time_config.get("off_peak_activity_multiplier", 0.3)
    if current_hour in morning_hours:
        return time_config.get("morning_activity_multiplier", 0.4)
    if current_hour in work_hours:
        return time_config.get("work_activity_multiplier", 0.7)
    return 1.0


def _resolve_start_hour(time_config: Dict[str, Any]) -> int:
    """RUN-4: 模拟起始小时。此前恒从 0 点（午夜）起跑，而生成的 agent active_hours
    普遍从 9 点开始——前 9 轮结构性零激活，24 轮预算里近半是死轮。
    优先级: time_config.start_hour > SIM_START_HOUR（env/Config）> 0（与旧行为逐字节一致）。"""
    raw = time_config.get("start_hour")
    if raw is None:
        raw = _cfg_flag("SIM_START_HOUR", "0")
    try:
        return int(float(raw)) % 24
    except (TypeError, ValueError):
        return 0


def _supported_log_kwargs(logger, method_name: str, fields: Dict[str, Any]) -> Dict[str, Any]:
    """CAL-TEMPORAL: 把日历时段字段过滤到 logger 方法真实支持的关键字参数子集。

    hours 模式 fields 恒为空 → 恒返回 {}（旧调用逐字节等价）；日历模式下若 action_logger
    尚未升级出新参数，则静默降级为不附字段（绝不因 TypeError 打断轮循环）；logger 带
    **kwargs 时全量透传。任何反射失败一律返回 {}（degrade-safe）。"""
    if not fields or logger is None:
        return {}
    try:
        params = inspect.signature(getattr(logger, method_name)).parameters
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
            return {k: v for k, v in fields.items() if v is not None}
        return {k: v for k, v in fields.items() if k in params and v is not None}
    except Exception:  # noqa: BLE001
        return {}


def get_active_agents_for_round(
    env,
    config: Dict[str, Any],
    current_hour: int,
    round_num: int,
    last_active_ids: Optional[set] = None,
    calendar: bool = False,
) -> List:
    """根据时间、影响力与上一轮活跃情况决定本轮激活哪些 Agent（T3.5）。

    - 激活概率 p = activity_level × (0.5 + 0.5 × 归一化影响力) × 时段乘子；
    - 上一轮活跃/被提及的 agent 获 ×1.5 近因加成（形成级联）；
    - 目标人数随 cast 规模放大（max(base_max, ceil(0.2N))，封顶 3×base_max），避免大规模 cast 被饿死；
    - 候选按影响力加权不放回采样。缺 influence_weight 时退化为 1.0（与旧行为接近）。

    CAL-TEMPORAL（calendar=True，仅日历模式）：一轮=一个日历时段，昼夜节律无意义——
    跳过 active_hours 过滤、时段乘子恒 1.0，激活概率退化为 activity_level × (0.5 + 0.5 × 归一化影响力)
    （近因加成保留）；cadence=="principal" 的主角每轮无条件激活，绕过采样与
    3×agents_per_hour_max 上限（一个季度里主要行动体毫无动作是建模错误），sampled agent
    照旧填满上限。calendar=False（缺省）→ hours 路径逐字节不变。
    """
    time_config = config.get("time_config", {})
    agent_configs = config.get("agent_configs", [])
    num_agents = len(agent_configs)
    last_active_ids = last_active_ids or set()

    base_max = time_config.get("agents_per_hour_max", 20)

    multiplier = 1.0 if calendar else _resolve_hour_multiplier(time_config, current_hour)

    # 影响力归一化（用于激活概率与采样权重）
    influences = [float(c.get("influence_weight", 1.0) or 1.0) for c in agent_configs]
    max_infl = max(influences) if influences else 1.0
    if max_infl <= 0:
        max_infl = 1.0

    principal_ids: List = []  # CAL-TEMPORAL: cadence=="principal" 的主角（每轮必激活）
    candidates = []  # (agent_id, influence_weight)
    for cfg in agent_configs:
        agent_id = cfg.get("agent_id", 0)
        if calendar and str(cfg.get("cadence", "sampled") or "sampled") == "principal":
            principal_ids.append(agent_id)
            continue
        if not calendar:
            active_hours = cfg.get("active_hours", list(range(8, 23)))
            if current_hour not in active_hours:
                continue
        activity_level = float(cfg.get("activity_level", 0.5) or 0.5)
        infl = float(cfg.get("influence_weight", 1.0) or 1.0)
        p = activity_level * (0.5 + 0.5 * (infl / max_infl)) * multiplier
        if agent_id in last_active_ids:
            p *= 1.5  # 近因加成：上一轮活跃/被提及 → 形成级联
        if _RNG.random() < min(1.0, p):  # EXECPLAN2 I-7-2: 可复现激活概率
            candidates.append((agent_id, infl))

    # 目标人数：随 cast 规模放大，封顶 3×base_max
    base_target = max(base_max, (num_agents + 4) // 5)  # ceil(0.2 * num_agents)
    target_count = max(1, int(min(base_max * 3, base_target) * multiplier))

    selected_ids = _weighted_sample_without_replacement(candidates, target_count)
    if principal_ids:
        # CAL-TEMPORAL: 主角无条件置前，不占 sampled 配额（上限外追加；主角在上面已
        # continue 跳过采样候选池，故不会重复）
        selected_ids = principal_ids + selected_ids

    active_agents = []
    for agent_id in selected_ids:
        try:
            agent = env.agent_graph.get_agent(agent_id)
            active_agents.append((agent_id, agent))
        except Exception:
            pass

    return active_agents


# ============================================================================
# EXECPLAN2 I-2-1: per-agent affective-state dynamics (mood/energy/opinion/fatigue)
# threaded into each round's prompt. All gated behind Config.SIM_AGENT_DYNAMICS;
# when off these helpers are never called → static-persona behavior is byte-identical.
# The pure update math lives in app.services.agent_dynamics (offline-tested); here
# we (a) extract received-interaction signals from the round's actions, (b) inject
# the rendered state line into each active agent's system message before env.step.
# ============================================================================
def _build_dynamics_tracker(config, log_info):
    """Build an AgentDynamicsTracker if SIM_AGENT_DYNAMICS is on; else None (no-op)."""
    try:
        from app.config import Config
        if not getattr(Config, "SIM_AGENT_DYNAMICS", False):
            return None
        from app.services.agent_dynamics import AgentDynamicsTracker
        tracker = AgentDynamicsTracker.from_config(config.get("agent_configs", []), config_obj=Config)
        log_info("已启用逐智能体动态情感状态 (SIM_AGENT_DYNAMICS)")
        return tracker
    except Exception as e:  # never let an init bug break the run
        log_info(f"动态情感状态初始化失败，按静态人设运行: {e}")
        return None


# SIM-5: {plat}_dynamics_summary.json 的 prompt_delivery——_inject_agent_dynamics 写的是
# SYSTEM 记录，camel ScoreBasedContextCreator 只保留首条系统消息，状态行因此从未送达模型。
# 改为 USER 投递（及把硬编码中文状态行本地化）是另一项所有者决策，这里只如实记录。
_DYNAMICS_PROMPT_DELIVERY = "system_record_dropped_by_context_creator"


def _inject_agent_dynamics(active_agents, tracker, log_info):
    """Append each active agent's current-state line as a fresh SYSTEM memory record
    for this round. astep() reads memory.get_context(), so the note becomes the
    most-recent system message before the action prompt (maximal salience) WITHOUT
    clearing the agent's accumulated conversation memory. Best-effort per agent.

    (EXECPLAN2 I-2-1. Memory-preserving via update_memory rather than the earlier
    init_messages() re-seed, which the adversarial review flagged as silently wiping
    cross-round agent memory once an agent developed non-baseline state.)"""
    if tracker is None:
        return
    try:
        from camel.messages import BaseMessage
        from camel.types import OpenAIBackendRole
    except Exception:
        return
    for aid, agent in active_agents:
        try:
            line = tracker.state_line(aid)
            if not line:
                continue
            note = BaseMessage.make_user_message(role_name="StateUpdater", content=line)
            agent.update_memory(note, OpenAIBackendRole.SYSTEM)
        except Exception as e:
            log_info(f"动态状态注入失败 (agent {aid}): {e}")


def _observe_agent_dynamics(tracker, actual_actions, name_to_id):
    """Feed this round's signals into the tracker (best-effort, never raises)."""
    if tracker is None:
        return
    try:
        from app.services.agent_dynamics import extract_round_signals
        received, activity = extract_round_signals(actual_actions, name_to_id)
        tracker.observe_round(received, activity)
    except Exception:
        pass


def _inject_period_context(env, active_ids, round_num, period, timeline,
                           fired_events, world_delta, response_step: bool = False,
                           language: str = "") -> None:
    """CAL-TEMPORAL: env.step 前给每个活跃 agent 追加一条本轮「世界时钟」记忆。

    以 USER 角色写入（关键）：camel-ai 0.2.78 的 ScoreBasedContextCreator 只保留
    records[0] 作系统消息、丢弃其后所有 SYSTEM 记录，故用 OpenAIBackendRole.SYSTEM
    写入的动态世界时钟根本到不了模型（实测 get_context() 丢弃）；改用 USER 角色则随
    环境消息一同送达（与 OASIS 把「你的环境：[帖子…]」作 USER 消息投喂同源），且
    update_memory 不清空跨轮记忆。头部含日历时段/轮次进度/预测判定日（spec §5 verbatim）；
    CONFIRMED EVENTS 列出本轮已到期的日程事件；WHAT CHANGED LAST PERIOD 段由
    SIM_WORLD_DELTA 开关控制（默认开），摘要为空（首轮 / in-band 演化未产出）时显示
    "(first period)"。仅日历模式调用；全程 best-effort——无法构造/单个 agent 失败均静默
    跳过，绝不中断轮循环。
    """
    if not isinstance(period, dict) or not period:
        return
    try:
        from camel.messages import BaseMessage
        from camel.types import OpenAIBackendRole
    except Exception:
        return
    timeline = timeline if isinstance(timeline, dict) else {}
    label = str(period.get("label", "") or "")
    period_start = str(period.get("period_start", "") or "")
    period_end = str(period.get("period_end", "") or "")
    unit = str(timeline.get("unit", "") or "")
    horizon_date = str(timeline.get("horizon_date", "") or "")
    try:
        n_rounds = int(timeline.get("n_rounds") or 0)
    except (TypeError, ValueError):
        n_rounds = 0
    periods_remaining = max(0, n_rounds - (round_num + 1))

    event_lines = []
    for ev in fired_events or []:
        if not isinstance(ev, dict):
            continue
        content = str(ev.get("content", "") or "").strip()
        if not content:
            continue
        date = str(ev.get("date", "") or "").strip()
        # 配置生成器在日历模式已给 content 加 "[{date}] " 前缀；未加前缀时这里补上
        if date and not content.startswith("["):
            content = f"[{date}] {content}"
        event_lines.append(content)
    events_block = "\n".join(event_lines) if event_lines else "(none)"

    lines = [
        f"# WORLD CLOCK — {label} ({period_start} → {period_end}) | "
        f"round {round_num + 1}/{n_rounds} | one {unit} per round | "
        f"forecast horizon {horizon_date} ({periods_remaining} periods remain)",
        f"You are acting as your real-world actor OVER THIS ENTIRE {unit}. Your post is the most",
        "consequential public action you take this period — a decision, announcement, launch, deal,",
        "alliance, investment, or policy move — not minute-by-minute chatter. Reacting to another",
        "actor's move is a strategic response. Doing nothing is a legitimate strategic choice.",
    ]
    # SIM-REACT: 回应阶段开启时告知本次动作是「自己的一步」，回应他人另有专门一步。
    if response_step:
        lines.append("After every actor has moved, you get a separate response step to answer other "
                     "actors' posts, so use this action for your own move.")
    if language:
        lines.append(f"Write all of your posts and replies in {language}.")
    lines += [
        "## CONFIRMED EVENTS THIS PERIOD",
        events_block,
    ]
    if _flag_true("SIM_WORLD_DELTA", "true"):
        lines.append("## WHAT CHANGED LAST PERIOD")
        lines.append(str(world_delta or "").strip() or "(first period)")
    text = "\n".join(lines)

    for aid in active_ids or []:
        try:
            agent = env.agent_graph.get_agent(aid)
            note = BaseMessage.make_user_message(role_name="WorldClock", content=text)
            # USER 角色（非 SYSTEM）：见 docstring——SYSTEM 记录会被 camel 的上下文构造器
            # 丢弃，只有 USER 记录能随环境送达模型。这是本特性真正落地的关键行。
            agent.update_memory(note, OpenAIBackendRole.USER)
        except Exception:
            continue


# ============================================================================
# RUN-2: 逐调用 LLM 健康计数。OASIS 在 agent.astep 内部吞掉每个 agent 的模型异常
# （只留一行 'Error processing with model'），env.step 正常返回——历史上出现过
# 416/416 全部失败仍报 simulation_health='ok' 的整场空跑。模型请求层是唯一可靠的
# 观测点：在这里计数调用/异常，循环结束落 llm_health.json 供健康门消费。
# ============================================================================
# ============================================================================
# DEFECT-3: sim 子进程 token 计量落盘（最后一个记账盲区）。审计取证：648 次已确认的
# LLM 调用在 run_telemetry.json 里记为 0 token——oasis_llm 为每次调用构造 usage
# （CLI 桥接/回退路径按文本长度估算，直连路径为提供方真实值），但该 usage 喂给 camel
# 后即被丢弃，子进程退出时整场模拟的 token 账随进程蒸发。这里在模型请求边界
# （_wrap_model_llm_counter）逐调用累计 usage，按来源分桶：
#   * source='provider'：提供方返回的真实 usage 字段；
#   * source='estimate'：oasis_llm._build_chat_completion 伪造的长度估算——其
#     completion id 恒以 'chatcmpl-cli-' 开头（CLI 桥接与 LLMClient 回退路径）；
#   * source='missing'：响应不带 usage（只计调用数，token 记 0）。
# 决策通道 / in-band 世界演化走 LLMClient 直连（不经 camel 模型边界）→ 由
# _wrap_llm_client_usage 以同一累计器入账（精确 usage 优先，缺失时长度估算）。
# 快照以 sim_llm_telemetry.json 原子落盘：模拟回路结束后写一版（命令等待模式可能
# 驻留很久甚至被 SIGKILL），进程退出路径（__main__ 的 finally，含失败/信号优雅退出）
# 再写终版。编排器在 RUN 阶段边界读取该文件并恰好一次地计入 stage='run' 的 LLMMeter
# 记录（pipeline_orchestrator._record_sim_run_telemetry；meter_run_token 是幂等去重键，
# 每次子进程启动铸新、同进程重写不变）。纯附加遥测：任何失败都被吞掉，绝不影响模拟。
# ============================================================================
SIM_LLM_TELEMETRY_FILE = "sim_llm_telemetry.json"
SIM_LLM_TELEMETRY_SCHEMA = "sim-llm-telemetry/v1"
_SIM_LLM_METER_RUN_TOKEN = uuid.uuid4().hex
_SIM_LLM_METER_STARTED = time.time()
_SIM_LLM_USAGE_LOCK = threading.Lock()
_SIM_LLM_USAGE: Dict[str, Any] = {
    "calls": 0,
    "errors": 0,
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "by_source": {},
    "by_model": {},
}
# main() 钉定、__main__ 的 finally 消费：任何退出路径都能写终版快照。
_SIM_LLM_TELEMETRY_SINK: Dict[str, Any] = {"dir": None, "config": None}


def _record_sim_llm_usage(source: str, model: str,
                          prompt_tokens: Any, completion_tokens: Any) -> None:
    """向进程级累计器记一笔调用（线程安全、绝不抛出）。"""
    try:
        pt = max(0, int(prompt_tokens or 0))
        ct = max(0, int(completion_tokens or 0))
        key = str(model or "unknown")
        with _SIM_LLM_USAGE_LOCK:
            u = _SIM_LLM_USAGE
            u["calls"] += 1
            u["prompt_tokens"] += pt
            u["completion_tokens"] += ct
            for bucket_map, bucket_key in ((u["by_source"], str(source)),
                                           (u["by_model"], key)):
                b = bucket_map.setdefault(
                    bucket_key,
                    {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0})
                b["calls"] += 1
                b["prompt_tokens"] += pt
                b["completion_tokens"] += ct
    except Exception:  # noqa: BLE001 — 计量绝不影响调用路径
        pass


def _record_sim_llm_error() -> None:
    """记一次模型边界调用失败（token 无从谈起，只计失败数）。"""
    try:
        with _SIM_LLM_USAGE_LOCK:
            _SIM_LLM_USAGE["errors"] += 1
    except Exception:  # noqa: BLE001
        pass


def _accumulate_sim_llm_response(response: Any) -> None:
    """从一次 chat-completion 响应提取 usage 并入账（degrade-safe）。

    oasis_llm._build_chat_completion 伪造的估算响应 id 恒以 'chatcmpl-cli-' 开头
    （CLI 桥接与 LLMClient 回退路径）→ source='estimate'；其余带 usage 的响应视为
    提供方真实值 → source='provider'；无 usage → source='missing'（token 记 0）。"""
    try:
        model = str(getattr(response, "model", "") or "unknown")
        usage = getattr(response, "usage", None)
        if usage is None:
            _record_sim_llm_usage("missing", model, 0, 0)
            return
        source = (
            "estimate"
            if str(getattr(response, "id", "") or "").startswith("chatcmpl-cli-")
            else "provider"
        )
        _record_sim_llm_usage(
            source, model,
            getattr(usage, "prompt_tokens", 0),
            getattr(usage, "completion_tokens", 0),
        )
    except Exception:  # noqa: BLE001
        pass


def _last_provider_usage(client: Any) -> Any:
    """本线程上 client 最近一次调用的提供方真实 usage；无则 None。

    INFRA-2：优先读 INFRA-1 的逐调用元数据 last_call_meta()（线程本地，按客户端归属；仅
    usage_source='provider' 算精确值）；不提供该接口或返回 None 的客户端回退旧的 _last_usage。"""
    meta_of = getattr(client, "last_call_meta", None)
    try:
        meta = meta_of() if callable(meta_of) else None
    except Exception:  # noqa: BLE001 — 元数据读取失败 → 回退 _last_usage
        meta = None
    if isinstance(meta, dict):
        return meta.get("usage") if meta.get("usage_source") == "provider" else None
    return getattr(client, "_last_usage", None)


def _wrap_llm_client_usage(client: Any) -> Any:
    """DEFECT-3: 包装决策通道 / in-band 演化所用 LLMClient 的 chat/chat_json。

    这两条路径不经 camel 模型边界，其 LLMMeter 记录只活在子进程内存里。精确 usage
    （_last_provider_usage：逐调用元数据，OpenAI 兼容直连路径填充）→ source='provider'；
    CLI 提供方无精确 usage → 按文本长度估算 → source='estimate'。包装失败原样返回 client。

    INFRA-2：真实 LLMClient 的 chat_json 经 self.chat 发出每次请求（含修复轮），而实例上的
    chat 已被包装、逐次入账——再包 chat_json 会把同一调用记两遍，故对 LLMClient 实例只包 chat。"""
    if client is None:
        return client
    try:
        from app.utils.llm_client import LLMClient
        from app.utils.oasis_llm import _estimate_tokens_of

        def _wrap_method(name: str) -> None:
            orig = getattr(client, name, None)
            if not callable(orig):
                return

            def _wrapped(messages, *args, **kwargs):
                try:
                    result = orig(messages, *args, **kwargs)
                except Exception:
                    _record_sim_llm_error()
                    raise
                try:
                    model = str(
                        getattr(client, "model", "")
                        or getattr(client, "provider", "")
                        or "unknown"
                    )
                    usage = _last_provider_usage(client)
                    if isinstance(usage, dict) and (
                        usage.get("prompt_tokens") or usage.get("completion_tokens")
                    ):
                        _record_sim_llm_usage(
                            "provider", model,
                            usage.get("prompt_tokens", 0),
                            usage.get("completion_tokens", 0),
                        )
                    else:
                        _record_sim_llm_usage(
                            "estimate", model,
                            _estimate_tokens_of(messages),
                            _estimate_tokens_of(result),
                        )
                except Exception:  # noqa: BLE001 — 计量绝不影响调用结果
                    pass
                return result

            setattr(client, name, _wrapped)

        _wrap_method("chat")
        if not isinstance(client, LLMClient):
            _wrap_method("chat_json")
    except Exception:  # noqa: BLE001 — 包装失败 → 该路径放弃计量，不阻断
        pass
    return client


def _write_sim_llm_telemetry(simulation_dir: str,
                             config: Optional[Dict[str, Any]] = None,
                             log_info=None) -> None:
    """把当前 usage 快照原子落盘 <sim_dir>/sim_llm_telemetry.json（幂等、绝不抛出）。"""
    try:
        from app.utils.atomic import write_json_atomic
        with _SIM_LLM_USAGE_LOCK:
            usage = json.loads(json.dumps(_SIM_LLM_USAGE))
        cfg = config if isinstance(config, dict) else {}
        try:
            from app.utils.oasis_llm import _resolve_provider
            provider = _resolve_provider(cfg)
        except Exception:  # noqa: BLE001
            provider = "unknown"
        # 主导模型标签：按调用数取最大者；无调用时回退配置模型名/provider。
        by_model = usage.get("by_model") or {}
        model = ""
        if by_model:
            model = max(by_model.items(), key=lambda kv: kv[1].get("calls", 0))[0]
        if not model or model == "unknown":
            model = str(cfg.get("llm_model") or provider or "unknown")
        payload = {
            "schema_version": SIM_LLM_TELEMETRY_SCHEMA,
            "simulation_id": str(
                cfg.get("simulation_id")
                or os.path.basename(os.path.abspath(simulation_dir))
            ),
            "meter_run_token": _SIM_LLM_METER_RUN_TOKEN,
            "provider": str(provider or "unknown"),
            "model": model,
            "calls": int(usage.get("calls") or 0),
            "errors": int(usage.get("errors") or 0),
            "prompt_tokens": int(usage.get("prompt_tokens") or 0),
            "completion_tokens": int(usage.get("completion_tokens") or 0),
            "total_tokens": (int(usage.get("prompt_tokens") or 0)
                             + int(usage.get("completion_tokens") or 0)),
            "by_source": usage.get("by_source") or {},
            "by_model": by_model,
            "wall_s": round(max(0.0, time.time() - _SIM_LLM_METER_STARTED), 3),
            "written_at": datetime.now().isoformat(),
        }
        write_json_atomic(
            os.path.join(simulation_dir, SIM_LLM_TELEMETRY_FILE), payload)
        if log_info:
            log_info(
                f"sim_llm_telemetry.json 已落盘（calls={payload['calls']}, "
                f"tokens={payload['total_tokens']}, provider={payload['provider']}）"
            )
    except Exception:  # noqa: BLE001 — 遥测落盘失败绝不影响模拟结果
        pass


def _wrap_model_llm_counter(model) -> Dict[str, int]:
    """包装模型的 chat-completion 请求方法以计数调用与异常。只包异步路径
    （OASIS astep 全走 _arequest_chat_completion；CLIModel 的异步实现委托同步方法，
    双包会重复计数），无异步方法时才包同步路径。包装失败不影响建模（计数保持 0）。"""
    counter = {"calls": 0, "errors": 0}
    try:
        _aorig = getattr(model, "_arequest_chat_completion", None)
        if _aorig is not None:
            async def _acounted(*args, **kwargs):
                counter["calls"] += 1
                try:
                    result = await _aorig(*args, **kwargs)
                except Exception:
                    counter["errors"] += 1
                    _record_sim_llm_error()
                    raise
                # DEFECT-3: 逐调用累计 usage（真实/估算按来源分桶）；纯附加，绝不抛出。
                _accumulate_sim_llm_response(result)
                return result
            model._arequest_chat_completion = _acounted
        else:
            _orig = model._request_chat_completion

            def _counted(*args, **kwargs):
                counter["calls"] += 1
                try:
                    result = _orig(*args, **kwargs)
                except Exception:
                    counter["errors"] += 1
                    _record_sim_llm_error()
                    raise
                _accumulate_sim_llm_response(result)  # DEFECT-3（同上）
                return result
            model._request_chat_completion = _counted
    except Exception:  # noqa: BLE001 — 遥测是附加物，绝不阻断模型创建
        pass
    return counter


def _write_llm_health(simulation_dir: str, platform: str, counter: Dict[str, int], log_info) -> None:
    """RUN-2: 把本平台 LLM 调用/失败计数合并写入 llm_health.json（原子）。
    error_rate 超过 SIM_LLM_ERROR_RATE_THRESHOLD（默认 0.5）标记 degraded=True，
    供 write_run_summary 把 simulation_health 降级。纯附加遥测，失败不影响模拟。"""
    try:
        calls = int(counter.get("calls", 0) or 0)
        errors = int(counter.get("errors", 0) or 0)
        rate = (errors / calls) if calls > 0 else 0.0
        try:
            threshold = float(_cfg_flag("SIM_LLM_ERROR_RATE_THRESHOLD", "0.5"))
        except (TypeError, ValueError):
            threshold = 0.5
        path = os.path.join(simulation_dir, "llm_health.json")
        data: Dict[str, Any] = {"platforms": {}}
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    existing = json.load(f)
                if isinstance(existing, dict) and isinstance(existing.get("platforms"), dict):
                    data = existing
            except (json.JSONDecodeError, OSError):
                pass
        degraded = bool(calls > 0 and rate > threshold)
        data["platforms"][platform] = {
            "llm_calls": calls,
            "llm_errors": errors,
            "error_rate": round(rate, 4),
            "degraded": degraded,
        }
        data["threshold"] = threshold
        data["updated_at"] = datetime.now().isoformat()
        from app.utils.atomic import write_json_atomic
        write_json_atomic(path, data)
        if degraded:
            log_info(f"⚠ LLM 调用失败率 {rate:.0%} ({errors}/{calls}) 超阈值 {threshold:.0%}——本平台产出不可信")
        else:
            log_info(f"LLM 调用健康: {errors}/{calls} 失败")
    except Exception as e:  # noqa: BLE001
        log_info(f"llm_health.json 写出失败（不影响模拟）: {e}")


# ============================================================================
# XRUN-14: 工具参数规整。模型（尤其 MiniMax-M3）会幻觉工具参数名（实测
# like_comment(post_id=...)，签名是 comment_id），camel 把异常吞成 warning 后
# 该类动作被整体丢弃。这里在 FunctionTool.func 外套一层：可安全改名的按别名映射，
# 其余未知关键字丢弃并记录降级；规整后仍非法则照旧抛错（与今日行为一致）。
# SIM_TOOL_ARG_NORMALIZE=false 可整体关闭（恢复原生行为）。
# ============================================================================
_TOOL_ARG_ALIASES = {
    "like_comment": {"post_id": "comment_id"},
    "dislike_comment": {"post_id": "comment_id"},
}


def _normalize_tool_kwargs(kwargs: Dict[str, Any], params, tool_name: str) -> Dict[str, Any]:
    """纯函数：按目标签名过滤/改名 LLM 给出的工具关键字参数。"""
    aliases = _TOOL_ARG_ALIASES.get(tool_name, {})
    out: Dict[str, Any] = {}
    for k, v in kwargs.items():
        if k in params:
            out[k] = v
            continue
        target = aliases.get(k)
        if target and target in params and target not in kwargs:
            print(f"[tool-args] {tool_name}: 幻觉参数 {k} 已改名为 {target}（动作保留执行）")
            out[target] = v
        else:
            print(f"[tool-args] {tool_name}: 丢弃未知参数 {k}（模型幻觉，尽力保留动作）")
    return out


def _wrap_agent_tool_arg_normalizer(agent_graph, log_info) -> None:
    """给 agent_graph 中每个 agent 的已注册工具套上参数规整层（幂等，best-effort）。"""
    if not _flag_true("SIM_TOOL_ARG_NORMALIZE", "true"):
        return
    import functools
    import inspect
    wrapped = 0
    try:
        agents = list(agent_graph.get_agents())
    except Exception:
        return
    for _aid, agent in agents:
        tools = getattr(agent, "_internal_tools", None)
        if not isinstance(tools, dict):
            continue
        for name, tool in tools.items():
            func = getattr(tool, "func", None)
            if func is None or getattr(func, "_sim_arg_normalized", False):
                continue
            try:
                sig = inspect.signature(func)
            except (TypeError, ValueError):
                continue
            if any(p.kind is inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                continue  # **kwargs 函数本就接受任意关键字，无需规整
            params = frozenset(sig.parameters)
            if inspect.iscoroutinefunction(func):
                def _make_async(f, ps, nm):
                    @functools.wraps(f)
                    async def _w(*args, **kwargs):
                        return await f(*args, **_normalize_tool_kwargs(kwargs, ps, nm))
                    return _w
                new_func = _make_async(func, params, name)
            else:
                def _make_sync(f, ps, nm):
                    @functools.wraps(f)
                    def _w(*args, **kwargs):
                        return f(*args, **_normalize_tool_kwargs(kwargs, ps, nm))
                    return _w
                new_func = _make_sync(func, params, name)
            new_func._sim_arg_normalized = True
            tool.func = new_func
            wrapped += 1
    if wrapped:
        log_info(f"已启用工具参数规整（{wrapped} 个工具；SIM_TOOL_ARG_NORMALIZE=false 关闭）")


# 自我背书守卫：点赞 = 公开背书，给自己的帖子/评论点赞不是有效互动。实测（quantum-2040）
# 提示里写明「never like your own post」后仍有约 2% 的点赞落在自己的帖子上（回应自己帖子
# 下的回复时顺手点赞），发帖步骤里 OASIS 自带的点赞同样会点自己的帖子——必须在工具层拦截。
_SELF_ENDORSE_QUERIES = {
    "like_post": ("post_id",
                  "SELECT u.agent_id FROM post p JOIN user u ON p.user_id = u.user_id "
                  "WHERE p.post_id = ?"),
    "like_comment": ("comment_id",
                     "SELECT u.agent_id FROM comment c JOIN user u ON c.user_id = u.user_id "
                     "WHERE c.comment_id = ?"),
}


def _target_author_agent_id(db_path: str, query: str, target_id: Any) -> Optional[int]:
    """被点赞对象的作者 agent_id；库/表/行缺失或参数非法 → None（不拦截）。"""
    try:
        target = int(target_id)
    except (TypeError, ValueError):
        return None
    if not os.path.exists(db_path):
        return None
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute(query, (target,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    return int(row[0]) if row and row[0] is not None else None


def _wrap_agent_self_like_guard(agent_graph, db_path: str, log_info) -> None:
    """给每个 agent 的 like_post / like_comment 套上自我背书守卫（幂等，best-effort）：
    目标由本 agent 所写 → 不执行，返回失败结果（模型看到原因），其余照常执行。"""
    import functools
    import inspect
    guarded = 0
    try:
        agents = list(agent_graph.get_agents())
    except Exception:
        return
    for aid, agent in agents:
        tools = getattr(agent, "_internal_tools", None)
        if not isinstance(tools, dict):
            continue
        for name, (arg, query) in _SELF_ENDORSE_QUERIES.items():
            tool = tools.get(name)
            func = getattr(tool, "func", None)
            if func is None or getattr(func, "_sim_self_like_guard", False):
                continue
            if not inspect.iscoroutinefunction(func):
                continue  # OASIS 的社交动作均为 async；非预期形态不包

            def _make(f, owner, arg_name, sql):
                @functools.wraps(f)
                async def _w(*args, **kwargs):
                    target = kwargs.get(arg_name, args[0] if args else None)
                    if _target_author_agent_id(db_path, sql, target) == owner:
                        return {"success": False,
                                "error": "You cannot like your own post or comment."}
                    return await f(*args, **kwargs)
                return _w

            new_func = _make(func, int(aid), arg, query)
            new_func._sim_self_like_guard = True
            tool.func = new_func
            guarded += 1
    if guarded:
        log_info(f"已启用自我背书守卫（{guarded} 个点赞工具：不能给自己的帖子/评论点赞）")


async def inject_initial_follows(env, event_config, log_info, agent_names=None, action_logger=None):
    """T3.3: 把 event_config.initial_follows 作为 round-0 关注边注入。

    对每条 [follower, followee]：
      1. ``agent_graph.add_edge`` 直接建图——立刻改变推荐器看到的社交结构；
      2. 下一个 ``FOLLOW`` ManualAction——写入 ``follow`` 表（platform.follow 自带去重）。
    两者互不冲突（add_edge 改内存图，follow 写 DB 表）。一个 agent 每个 step 只能一个动作，
    故按 follower 分组多趟 step 清空。空/缺失 → 直接返回 0（与旧行为一致）。
    """
    follows = event_config.get("initial_follows", []) or []
    if not follows:
        return 0

    from collections import defaultdict
    by_follower = defaultdict(list)
    for pair in follows:
        try:
            follower, followee = int(pair[0]), int(pair[1])
        except (TypeError, ValueError, IndexError):
            continue
        if follower == followee:
            continue
        # 1. 直接建图（best-effort）
        try:
            env.agent_graph.add_edge(follower, followee)
        except Exception:
            pass
        by_follower[follower].append(followee)

    # ITEM 20 (SIM_MAX_FOLLOWS_PER_AGENT_ROUND): 种子 FOLLOW 风暴节流。上面的 add_edge 已对
    # 全量边建图（推荐器看到的社交拓扑完整），此处仅截断写 trace/follow 表的 FOLLOW **动作**
    # 数量——630 条种子关注一次性灌入会把早期动作日志淹没（其余动作看不见）。cap<=0 = 不限（旧行为）。
    _follow_cap = _max_follows_per_agent_round()
    if _follow_cap and _follow_cap > 0:
        try:
            from app.services.agent_dynamics import throttle_seed_follows
            _capped, _dropped = throttle_seed_follows(dict(by_follower), _follow_cap)
            by_follower = _capped
            if _dropped:
                log_info(f"种子 FOLLOW 节流：每 follower ≤{_follow_cap} 条 FOLLOW 动作，"
                         f"丢弃 {_dropped} 条（社交图 add_edge 已建全量边，不受影响）")
        except Exception as _thr_err:  # noqa: BLE001 — 节流失败退回旧的全量注入（不中断模拟）
            log_info(f"种子 FOLLOW 节流失败，退回全量注入（不中断模拟）: {_thr_err}")

    # 2. FOLLOW 动作多趟注入（每趟每个 follower 处理一个 followee）
    applied = 0
    max_passes = max((len(v) for v in by_follower.values()), default=0)
    for p in range(max_passes):
        actions = {}
        for follower, followees in by_follower.items():
            if p >= len(followees):
                continue
            try:
                agent = env.agent_graph.get_agent(follower)
                actions[agent] = ManualAction(
                    action_type=ActionType.FOLLOW,
                    action_args={"followee_id": followees[p]},
                )
            except Exception:
                continue
        if not actions:
            continue
        try:
            await env.step(actions)
            applied += len(actions)
        except Exception as e:
            log_info(f"初始关注注入第 {p + 1} 趟部分失败（继续）: {e}")
    log_info(f"已建立 {applied} 条初始关注边")
    return applied


async def fire_scheduled_events(env, event_config, loop_round, agent_names, action_logger, log_info):
    """T3.8: 在 loop_round（0 基）触发 scheduled_events 中 round==loop_round 的事件为 CREATE_POST。

    复用 initial_posts 的注入路径（matched poster → ManualAction(CREATE_POST)）。无匹配事件 → 0。
    返回成功触发的事件数。

    SIM-5：同一发帖者同轮多个事件按列表累积（此前按 agent 覆盖，只发出最后一条却全部计数）；
    缺发帖者/内容或发帖者不可用的事件逐条记日志（此前静默丢弃）——两者不受开关影响。
    SIM_EVENT_PROVENANCE 开（默认）→ 发帖与落账内容带来源前缀，落账 action_args 附 event_provenance。
    """
    events = event_config.get("scheduled_events", []) or []
    due = [e for e in events if int(e.get("round", -1)) == loop_round]
    if not due:
        return 0
    provenance_on = _event_provenance_enabled()
    if provenance_on:
        from app.services.sim_event_provenance import classify_event, label_event_post
    actions: Dict[Any, List[Any]] = {}
    fired = 0
    for ev in due:
        agent_id = ev.get("poster_agent_id")
        content = str(ev.get("content", "") or "")
        if agent_id is None or not content:
            log_info(
                f"第 {loop_round + 1} 轮定时事件缺{'发帖者' if agent_id is None else '内容'}，"
                f"跳过: {_truncate_text(content or ev.get('date') or '', 80)!r}"
            )
            continue
        logged_args: Dict[str, Any] = {"content": content, "is_scheduled_event": True}
        if provenance_on:
            provenance = classify_event(ev)
            content = label_event_post(content, provenance)
            logged_args = {"content": content, "is_scheduled_event": True,
                           "event_provenance": provenance}
        try:
            agent = env.agent_graph.get_agent(agent_id)
            actions.setdefault(agent, []).append(ManualAction(
                action_type=ActionType.CREATE_POST,
                action_args={"content": content},
            ))
            if action_logger:
                action_logger.log_action(
                    round_num=loop_round + 1,
                    agent_id=agent_id,
                    agent_name=(agent_names or {}).get(agent_id, f"Agent_{agent_id}"),
                    action_type="CREATE_POST",
                    action_args=logged_args,
                )
            fired += 1
        except Exception as e:  # noqa: BLE001 — 如发帖者不在 agent 图中（裁剪/重编号）
            log_info(f"第 {loop_round + 1} 轮定时事件（发帖者 {agent_id}）注入失败，跳过: "
                     f"{type(e).__name__}: {e}")
            continue
    if actions:
        try:
            await env.step(actions)
            log_info(f"第 {loop_round + 1} 轮触发 {fired} 个定时事件（时间线回放）")
        except Exception as e:
            log_info(f"定时事件触发失败，跳过（不中断模拟）: {e}")
            return 0
    return fired


def _scheduled_events_due(event_config, loop_round) -> List[Dict[str, Any]]:
    """CAL-TEMPORAL: 取 loop_round（0 基）到期的日程事件原始条目（供世界时钟头的
    CONFIRMED EVENTS 段展示）。与 fire_scheduled_events 同一 round 匹配语义；
    round 字段非法的条目静默跳过（fire 路径对其同样无能为力）。失败 → []。"""
    out: List[Dict[str, Any]] = []
    for ev in (event_config or {}).get("scheduled_events", []) or []:
        if not isinstance(ev, dict):
            continue
        try:
            if int(ev.get("round", -1)) == loop_round:
                out.append(ev)
        except (TypeError, ValueError):
            continue
    return out


def _resolve_total_rounds(config: Dict[str, Any], temporal_config: Dict[str, Any],
                          calendar: bool, max_rounds: Optional[int], log_info) -> int:
    """总轮数的唯一权威计算（在 log_simulation_start 之前调用一次，使其记录真实轮数）。

    hours 模式：total_simulation_hours*60 // minutes_per_round，可被 max_rounds 截断
    （旧行为逐字节不变）。
    CAL-TEMPORAL 日历模式：temporal_config.n_rounds 为唯一权威（timeline 生成期已内建
    ≤48 硬上限），且不做运行期 max_rounds 截断——轮数上限已在配置生成期通过粗化时间
    粒度消化（spec：cap 粗化粒度、绝不截断预测期尾部）。
    """
    time_config = config.get("time_config", {})
    total_hours = time_config.get("total_simulation_hours", 72)
    minutes_per_round = time_config.get("minutes_per_round", 60)
    total_rounds = (total_hours * 60) // minutes_per_round

    if calendar:
        try:
            cal_rounds = int(temporal_config.get("n_rounds") or 0)
        except (TypeError, ValueError):
            cal_rounds = 0
        if cal_rounds <= 0:  # 降级：n_rounds 缺失/非法 → round_dates 长度 → legacy 公式
            cal_rounds = len(temporal_config.get("round_dates") or []) or total_rounds
        total_rounds = cal_rounds
        if max_rounds is not None and max_rounds > 0 and max_rounds < total_rounds:
            log_info(f"日历模式：忽略运行期 max_rounds={max_rounds}"
                     f"（总轮数 {total_rounds} 覆盖完整预测期，截断只会砍掉判定日前的尾部）")
    # 如果指定了最大轮数，则截断（hours 模式旧行为，逐字节不变）
    elif max_rounds is not None and max_rounds > 0:
        original_rounds = total_rounds
        total_rounds = min(total_rounds, max_rounds)
        if total_rounds < original_rounds:
            log_info(f"轮数已截断: {original_rounds} -> {total_rounds} (max_rounds={max_rounds})")
    return total_rounds


def build_oasis_platform(kind: str, db_path: str, config: Dict[str, Any], log_info):
    """T3.12: 用 config 的 *_config recsys 旋钮构建自定义 oasis Platform（含 T3.9 时钟锚定）。

    OASIS 的 make() 只接受 agent_graph/platform/db/semaphore；recsys_type / refresh_rec_post_count /
    max_rec_post_len / following_post_count / start_time 等仅在 Platform 上。仅当 SIM_WIRE_RECSYS=true
    时启用；否则返回 None，调用方退回 DefaultPlatformType（与旧行为逐字节一致）。构建失败同样回退。

    映射：recsys_type / refresh_rec_post_count / max_rec_post_len 直传；echo_chamber_strength →
    following_post_count（越强→关注流曝光越多→同温层更强）。recency/popularity/relevance/
    viral_threshold 是展示性权重，OASIS 不消费，此处不再谎称生效。
    """
    if os.environ.get("SIM_WIRE_RECSYS", "false").strip().lower() != "true":
        # RUN-6 (S8): DefaultPlatformType.TWITTER 用 twhin-bert recsys——运行期要从
        # HuggingFace 下载 transformer，语料里该下载成百次 ConnectTimeout → 空 feed →
        # 500 帖 0 评论 0 赞的纯广播模拟。S8 的模型无关 recsys 修复此前只在
        # SIM_WIRE_RECSYS=true 时可达，而默认 false → 默认跑的仍是坏 feed。这里把
        # Twitter 的 recsys_type 缺省提升到 'reddit'（工程无关、纯启发式排序），
        # 其余参数与 DefaultPlatformType.TWITTER 逐项一致；SIM_TWITTER_RECSYS 可显式
        # 覆盖（模型已缓存时设回 twhin-bert）。SIM_TWITTER_MODEL_FREE_FEED=false 或
        # 构建失败 → 回退默认平台（今日行为）。
        if kind == "twitter" and _flag_true("SIM_TWITTER_MODEL_FREE_FEED", "true"):
            try:
                from oasis.social_platform.platform import Platform
                from oasis.social_platform.channel import Channel
                _mf_recsys = os.environ.get("SIM_TWITTER_RECSYS", "").strip() or "reddit"
                # 2026-07-03 live-surfaced: max_rec_post_len=2 predates the S8 model-free
                # feed fix — harmless back when Twitter used twhin-bert (its HuggingFace
                # download routinely failed → empty feed regardless of this value), but
                # became a severe winner-take-all bug once S8 switched Twitter to the
                # WORKING reddit-style hot-score recsys. rec_sys_reddit() gives every
                # single agent the IDENTICAL top-N-by-hot-score list every round (no
                # personalization); with N=2, whichever post gets an early like-lead
                # permanently occupies both slots (more visibility → more likes → higher
                # score → stays in the top 2), starving every other post of exposure for
                # the entire run. Observed live: a 24-round/54-post run put 32 of 33 total
                # comments on ONE seed post while 52 posts got zero. Reddit's own recsys_type
                # already defaults max_rec_post_len to 100 (see the else-branch below) — with
                # our small ≤20-actor casts (~50-60 total posts/run), 100 lets rec_sys_reddit's
                # `len(post_ids) <= max_rec_post_len` branch fire, handing every agent the
                # FULL post list with zero algorithmic bias — the dense mutual-awareness a
                # small principals-only cast needs. Mirrors that default here for consistency.
                platform = Platform(
                    db_path=db_path,
                    channel=Channel(),
                    recsys_type=_mf_recsys,
                    refresh_rec_post_count=5,
                    max_rec_post_len=100,
                    following_post_count=3,
                )
                log_info(
                    f"已启用模型无关 Twitter feed: recsys_type={_mf_recsys}"
                    "（SIM_TWITTER_MODEL_FREE_FEED=false 恢复 twhin-bert 默认平台）"
                )
                return platform
            except Exception as e:  # noqa: BLE001
                log_info(f"模型无关 feed 构建失败，回退默认平台: {e}")
        return None
    try:
        from oasis.social_platform.platform import Platform
        from oasis.social_platform.channel import Channel
    except Exception as e:  # noqa: BLE001
        log_info(f"recsys 旋钮接入不可用，回退默认平台: {e}")
        return None

    pcfg = (config.get("twitter_config") if kind == "twitter" else config.get("reddit_config")) or {}
    echo = float(pcfg.get("echo_chamber_strength", 0.5) or 0.5)
    start_time = None
    as_of = config.get("as_of_date")
    if as_of:
        try:
            start_time = datetime.fromisoformat(str(as_of)[:10])
        except Exception:
            start_time = None
    try:
        channel = Channel()
        if kind == "twitter":
            # QUALITY-OPT S8: default Twitter to the MODEL-FREE "reddit" recsys (engagement +
            # recency ranking) instead of "twhin-bert"/"twitter", which load a HuggingFace
            # transformer (twhin-bert-base) at runtime. In the corpus that download failed
            # (hundreds of huggingface.co ConnectTimeouts) → empty feed → 500 posts but 0
            # comments/0 likes (broadcast-only). A heuristic feed that WORKS beats an
            # embedding feed that doesn't. Override with SIM_TWITTER_RECSYS=twhin-bert once the
            # model is cached (HF_HUB_OFFLINE=1). pcfg.recsys_type still wins if explicitly set.
            _tw_recsys = (pcfg.get("recsys_type")
                          or os.environ.get("SIM_TWITTER_RECSYS", "").strip()
                          or "reddit")
            platform = Platform(
                db_path=db_path,
                channel=channel,
                recsys_type=_tw_recsys,
                # 2026-07-03: matches the model-free fallback path's fix above (and
                # Reddit's own defaults below) — a tiny max_rec_post_len under the
                # working reddit-style hot-score recsys creates a winner-take-all
                # feed monopoly instead of the intended per-config tunable depth.
                refresh_rec_post_count=int(pcfg.get("refresh_rec_post_count") or 5),
                max_rec_post_len=int(pcfg.get("max_rec_post_len") or 100),
                following_post_count=int(round(2 + echo * 4)),
                start_time=start_time,
            )
        else:
            platform = Platform(
                db_path=db_path,
                channel=channel,
                recsys_type=(pcfg.get("recsys_type") or "reddit"),
                allow_self_rating=True,
                show_score=True,
                refresh_rec_post_count=int(pcfg.get("refresh_rec_post_count") or 5),
                max_rec_post_len=int(pcfg.get("max_rec_post_len") or 100),
                start_time=start_time,
            )
        log_info(
            f"已接入 recsys 旋钮[{kind}]: type={getattr(platform, 'recsys_type', '?')}, "
            f"echo={echo}, start_time={start_time.date() if start_time else '默认'}"
        )
        return platform
    except Exception as e:  # noqa: BLE001
        log_info(f"自定义平台构建失败，回退默认平台: {e}")
        return None


# ============================================================
# EXECPLAN2 I-2-0: 涌现结构 / 观点动力学度量层
# ------------------------------------------------------------
# 模拟结束后（只读地）在 {platform}_simulation.db + actions.jsonl 上计算：
#   1) 观点/立场轨迹 —— 每轮按 stance 桶（supportive/opposing/neutral/observer）
#      统计发声量（CREATE_POST/CREATE_COMMENT/QUOTE_POST），并对内容做轻量情感打分；
#   2) 极化指数 —— 每 agent 净情感分布的方差/双峰性 + 跨立场 vs 同立场互动比；
#   3) 关注图社区检测 —— 在真实 follow 表上跑 networkx（贪婪模块度/标签传播），
#      给出每个社区的主导立场与桥接 agent；
#   4) 级联/传播 —— top 帖的回复+转发+引用深度与广度。
# 全部行为默认关闭（SIM_EMERGENT_METRICS!=true 时不计算），networkx 缺失时社区检测
# 自动跳过，情感使用离线 CN/EN 极性词典（无 LLM 成本）。任何异常都不影响已完成的模拟，
# 仅在调用方以 try/except 包裹，结果写入 {platform}_emergent_metrics.json 与 emergent_metrics.json。
# ============================================================

# 影响立场表达的发声动作（用于立场轨迹加权与跨立场互动判定）
_SPEECH_ACTIONS = {"CREATE_POST", "CREATE_COMMENT", "QUOTE_POST", "REPOST"}
# 直接产生“agent→agent”互动的动作（用于跨立场 vs 同立场互动比）
_INTERACTION_ACTIONS = {
    "REPOST", "QUOTE_POST", "CREATE_COMMENT", "LIKE_POST", "DISLIKE_POST",
    "LIKE_COMMENT", "DISLIKE_COMMENT", "FOLLOW", "MUTE",
}
_STANCE_BUCKETS = ("supportive", "opposing", "neutral", "observer")

# 离线情感词典（CN + EN 极性词），用于 LLM 成本过高时的回退打分。
# 仅作粗粒度净情感方向估计；命中即 ±1，无命中记 0（中性）。
_POS_LEXICON = {
    # EN
    "good", "great", "excellent", "positive", "support", "growth", "win", "gain",
    "strong", "bullish", "optimistic", "agree", "love", "best", "advantage",
    "lead", "leading", "dominate", "success", "breakthrough", "soar", "surge",
    # CN
    "好", "强", "优势", "增长", "领先", "成功", "突破", "看好", "利好", "支持",
    "同意", "赞", "上涨", "飙升", "主导", "碾压", "双赢", "乐观",
}
_NEG_LEXICON = {
    # EN
    "bad", "poor", "negative", "oppose", "decline", "lose", "loss", "weak",
    "bearish", "pessimistic", "disagree", "hate", "worst", "risk", "fail",
    "failure", "crash", "plunge", "drop", "threat", "concern", "doubt",
    # CN
    "差", "弱", "下跌", "崩", "失败", "风险", "反对", "不同意", "看空", "利空",
    "暴跌", "担忧", "质疑", "威胁", "落后", "亏损", "悲观", "泡沫",
}


def _load_stance_by_agent(config: Dict[str, Any]) -> Dict[int, str]:
    """agent_id -> 归一化 stance 桶映射（缺省 neutral）。"""
    stance_map: Dict[int, str] = {}
    for cfg in config.get("agent_configs", []) or []:
        aid = cfg.get("agent_id")
        if aid is None:
            continue
        raw = str(cfg.get("stance", "neutral") or "neutral").strip().lower()
        stance_map[int(aid)] = raw if raw in _STANCE_BUCKETS else "neutral"
    return stance_map


def _lexicon_sentiment(text: str) -> float:
    """离线极性打分：返回 [-1, 1] 的净情感方向（无命中 → 0）。"""
    if not text:
        return 0.0
    low = text.lower()
    pos = sum(1 for w in _POS_LEXICON if w in low)
    neg = sum(1 for w in _NEG_LEXICON if w in low)
    if pos == 0 and neg == 0:
        return 0.0
    return (pos - neg) / float(pos + neg)


def _iter_action_lines(actions_jsonl_path: str):
    """逐行产出 actions.jsonl 中的“真实动作”记录（跳过 event_type 控制行）。"""
    if not os.path.exists(actions_jsonl_path):
        return
    try:
        with open(actions_jsonl_path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                # 控制行（simulation_start/round_start/round_end/simulation_end）无 action_type
                if rec.get("event_type") or not rec.get("action_type"):
                    continue
                yield rec
    except OSError:
        return


def _score_stance_trajectory(
    actions_jsonl_path: str,
    stance_by_agent: Dict[int, str],
) -> Tuple[List[Dict[str, Any]], float, Dict[int, float]]:
    """计算每轮立场轨迹 + 全局极化指数（按 agent 净情感分布方差）。

    Returns:
        (trajectory, polarization_index, net_sentiment_by_agent)
        - trajectory: [{round, by_stance:{...发声量...}, net_sentiment}]
        - polarization_index: agent 级净情感分布的方差（[0,1] 量级，越大越极化）
        - net_sentiment_by_agent: agent_id -> 平均净情感（供互动比/社区主导立场使用）

    SIM-5：SIM_EVENT_PROVENANCE 开（默认）→ 跳过注入行（round≤0 种子、定时事件回放、种子
    动作、采样点赞），立场轨迹只反映行为者自发的发声。
    """
    from collections import defaultdict

    skip_injected = _event_provenance_enabled()
    if skip_injected:
        from app.services.sim_event_provenance import is_injected_row

    per_round: Dict[int, Dict[str, Any]] = {}
    sent_sum_by_agent: Dict[int, float] = defaultdict(float)
    sent_cnt_by_agent: Dict[int, int] = defaultdict(int)

    for rec in _iter_action_lines(actions_jsonl_path):
        action_type = str(rec.get("action_type", ""))
        if action_type not in _SPEECH_ACTIONS:
            continue
        agent_id = rec.get("agent_id")
        round_num = rec.get("round")
        if agent_id is None or round_num is None:
            continue
        if skip_injected and is_injected_row(rec.get("action_args"), round_num):
            continue
        agent_id = int(agent_id)
        round_num = int(round_num)
        stance = stance_by_agent.get(agent_id, "neutral")

        bucket = per_round.setdefault(
            round_num,
            {"round": round_num, "by_stance": {s: 0 for s in _STANCE_BUCKETS}, "_sent": 0.0, "_n": 0},
        )
        bucket["by_stance"][stance] = bucket["by_stance"].get(stance, 0) + 1

        # 情感仅对带内容的动作打分
        content = ""
        args = rec.get("action_args") or {}
        if isinstance(args, dict):
            content = str(args.get("content") or args.get("quote_content") or "")
        if content:
            s = _lexicon_sentiment(content)
            bucket["_sent"] += s
            bucket["_n"] += 1
            sent_sum_by_agent[agent_id] += s
            sent_cnt_by_agent[agent_id] += 1

    trajectory: List[Dict[str, Any]] = []
    for round_num in sorted(per_round.keys()):
        b = per_round[round_num]
        net = (b["_sent"] / b["_n"]) if b["_n"] else 0.0
        trajectory.append({
            "round": round_num,
            "by_stance": b["by_stance"],
            "net_sentiment": round(net, 4),
        })

    net_by_agent: Dict[int, float] = {}
    for aid, total in sent_sum_by_agent.items():
        cnt = sent_cnt_by_agent.get(aid, 0)
        if cnt:
            net_by_agent[aid] = total / cnt

    # 极化指数：发声 agent 净情感分布的方差（0=完全一致，越大越极化）
    polarization = 0.0
    vals = list(net_by_agent.values())
    if len(vals) >= 2:
        mean = sum(vals) / len(vals)
        polarization = sum((v - mean) ** 2 for v in vals) / len(vals)

    return trajectory, round(polarization, 4), net_by_agent


def _compute_interaction_ratio(
    conn: "sqlite3.Connection",
    stance_by_agent: Dict[int, str],
    event_contents: Any = frozenset(),
) -> Dict[str, Any]:
    """跨立场 vs 同立场互动比。

    通过 follow（关注边）、post.original_post_id（转发/引用）、comment（回复）三类
    “agent→agent”边，按双方 stance 是否相同计数。比值 = 跨立场 / (同立场 + 跨立场)。

    SIM-5：event_contents（_event_post_contents_for_run，开关关/无事件 → 空集）非空时，
    目标帖是定时事件帖本身（原帖且正文 ∈ event_contents，与回应阶段同一判定）的转发/引用/
    评论边不计——对新闻的反应不是与发帖账号的互动。对他人引用事件的帖子的评论照计（目标是
    引用者）。空集 → 计数逐字节不变。
    """
    def _is_event_post(original_post_id, content) -> bool:
        return (bool(event_contents) and original_post_id is None
                and str(content or "").strip() in event_contents)

    cursor = conn.cursor()

    # user_id -> agent_id -> stance
    uid_to_stance: Dict[int, str] = {}
    try:
        cursor.execute("SELECT user_id, agent_id FROM user")
        for user_id, agent_id in cursor.fetchall():
            if agent_id is None:
                continue
            uid_to_stance[user_id] = stance_by_agent.get(int(agent_id), "neutral")
    except sqlite3.Error:
        return {"cross_stance_interaction_ratio": 0.0, "cross_stance": 0, "within_stance": 0}

    cross = 0
    within = 0

    def _tally(src_uid, dst_uid):
        nonlocal cross, within
        if src_uid is None or dst_uid is None or src_uid == dst_uid:
            return
        s_src = uid_to_stance.get(src_uid)
        s_dst = uid_to_stance.get(dst_uid)
        if s_src is None or s_dst is None:
            return
        if s_src == s_dst:
            within += 1
        else:
            cross += 1

    # 关注边
    try:
        cursor.execute("SELECT follower_id, followee_id FROM follow")
        for follower, followee in cursor.fetchall():
            _tally(follower, followee)
    except sqlite3.Error:
        pass

    # 转发/引用边：reposter -> 原帖作者
    try:
        cursor.execute(
            "SELECT p.user_id, orig.user_id, orig.original_post_id, orig.content "
            "FROM post p JOIN post orig ON p.original_post_id = orig.post_id "
            "WHERE p.original_post_id IS NOT NULL"
        )
        for reposter, author, orig_parent, orig_content in cursor.fetchall():
            if _is_event_post(orig_parent, orig_content):
                continue
            _tally(reposter, author)
    except sqlite3.Error:
        pass

    # 评论边：评论者 -> 被评论帖作者
    try:
        cursor.execute(
            "SELECT c.user_id, p.user_id, p.original_post_id, p.content "
            "FROM comment c JOIN post p ON c.post_id = p.post_id"
        )
        for commenter, author, post_parent, post_content in cursor.fetchall():
            if _is_event_post(post_parent, post_content):
                continue
            _tally(commenter, author)
    except sqlite3.Error:
        pass

    total = cross + within
    ratio = (cross / total) if total else 0.0
    return {
        "cross_stance_interaction_ratio": round(ratio, 4),
        "cross_stance": cross,
        "within_stance": within,
    }


def _detect_follow_communities(
    conn: "sqlite3.Connection",
    stance_by_agent: Dict[int, str],
    log_info,
) -> List[Dict[str, Any]]:
    """在真实 follow 表上做社区检测（networkx 缺失 → 返回 [] 并跳过）。"""
    try:
        import networkx as nx  # 可选依赖，缺失即优雅跳过
        from networkx.algorithms import community as nx_community
    except Exception as e:  # noqa: BLE001
        log_info(f"涌现度量：networkx 不可用，跳过社区检测: {e}")
        return []

    cursor = conn.cursor()
    # user_id -> agent_id
    uid_to_agent: Dict[int, Optional[int]] = {}
    try:
        cursor.execute("SELECT user_id, agent_id FROM user")
        for user_id, agent_id in cursor.fetchall():
            uid_to_agent[user_id] = int(agent_id) if agent_id is not None else None
    except sqlite3.Error:
        return []

    g = nx.DiGraph()
    try:
        cursor.execute("SELECT follower_id, followee_id FROM follow")
        for follower, followee in cursor.fetchall():
            if follower is None or followee is None or follower == followee:
                continue
            g.add_edge(follower, followee)
    except sqlite3.Error:
        return []

    if g.number_of_nodes() == 0:
        return []

    # 贪婪模块度在无向图上运行；用无向投影
    ug = g.to_undirected()
    try:
        comms = list(nx_community.greedy_modularity_communities(ug))
    except Exception:
        try:
            comms = list(nx_community.label_propagation_communities(ug))
        except Exception as e:  # noqa: BLE001
            log_info(f"涌现度量：社区检测失败，跳过: {e}")
            return []

    # 桥接节点：跨社区出/入度高者（按 betweenness 近似——用跨社区边计数）
    node_to_comm: Dict[int, int] = {}
    for idx, members in enumerate(comms):
        for node in members:
            node_to_comm[node] = idx

    cross_links: Dict[int, int] = {}
    for u, v in ug.edges():
        if node_to_comm.get(u) != node_to_comm.get(v):
            cross_links[u] = cross_links.get(u, 0) + 1
            cross_links[v] = cross_links.get(v, 0) + 1

    result: List[Dict[str, Any]] = []
    for idx, members in enumerate(comms):
        member_agents = [uid_to_agent.get(uid) for uid in members]
        member_agents = [a for a in member_agents if a is not None]
        # 主导立场
        from collections import Counter
        stance_counts = Counter(stance_by_agent.get(a, "neutral") for a in member_agents)
        dominant = stance_counts.most_common(1)[0][0] if stance_counts else "neutral"
        # 桥接 agent（跨社区连接数最高的前 3 个）
        bridges = sorted(
            (uid for uid in members if cross_links.get(uid, 0) > 0),
            key=lambda uid: cross_links.get(uid, 0),
            reverse=True,
        )[:3]
        bridge_agents = [uid_to_agent.get(uid) for uid in bridges]
        bridge_agents = [a for a in bridge_agents if a is not None]
        result.append({
            "size": len(members),
            "members": sorted(member_agents),
            "dominant_stance": dominant,
            "stance_breakdown": dict(stance_counts),
            "bridge_agents": bridge_agents,
        })
    # 大社区在前
    result.sort(key=lambda c: c["size"], reverse=True)
    return result


def _compute_cascades(
    conn: "sqlite3.Connection",
    top_n: int = 10,
) -> List[Dict[str, Any]]:
    """每个原帖的级联/传播统计：回复数(breadth) + 转发/引用数 + 综合互动深度。"""
    cursor = conn.cursor()

    # 转发/引用：original_post_id -> 计数
    repost_counts: Dict[int, int] = {}
    try:
        cursor.execute(
            "SELECT original_post_id, COUNT(*) FROM post "
            "WHERE original_post_id IS NOT NULL GROUP BY original_post_id"
        )
        for orig_id, cnt in cursor.fetchall():
            if orig_id is not None:
                repost_counts[orig_id] = cnt
    except sqlite3.Error:
        repost_counts = {}

    # 评论数
    comment_counts: Dict[int, int] = {}
    try:
        cursor.execute("SELECT post_id, COUNT(*) FROM comment GROUP BY post_id")
        for post_id, cnt in cursor.fetchall():
            if post_id is not None:
                comment_counts[post_id] = cnt
    except sqlite3.Error:
        comment_counts = {}

    # 原帖（original_post_id 为空）的基础信息
    cascades: List[Dict[str, Any]] = []
    try:
        cursor.execute(
            "SELECT post_id, num_likes, num_shares FROM post "
            "WHERE original_post_id IS NULL"
        )
        rows = cursor.fetchall()
    except sqlite3.Error:
        return []

    for post_id, num_likes, num_shares in rows:
        reposts = repost_counts.get(post_id, 0)
        replies = comment_counts.get(post_id, 0)
        likes = num_likes or 0
        breadth = reposts + replies
        # 综合级联“深度”：直接互动总量（回复 + 转发 + 点赞）
        depth = breadth + likes
        if breadth == 0 and likes == 0:
            continue
        cascades.append({
            "post_id": post_id,
            "replies": replies,
            "reposts": reposts,
            "likes": likes,
            "breadth": breadth,
            "depth": depth,
        })

    cascades.sort(key=lambda c: c["depth"], reverse=True)
    return cascades[:top_n]


def compute_emergent_metrics(
    simulation_dir: str,
    config: Dict[str, Any],
    platform: str,
    log_info,
) -> Optional[Dict[str, Any]]:
    """EXECPLAN2 I-2-0: 为单个平台计算涌现度量并返回字典（失败 → None）。

    只读 {platform}_simulation.db + {platform}/actions.jsonl，绝不修改模拟产物。
    """
    db_path = os.path.join(simulation_dir, f"{platform}_simulation.db")
    actions_path = os.path.join(simulation_dir, platform, "actions.jsonl")
    if not os.path.exists(db_path):
        log_info(f"涌现度量[{platform}]：数据库不存在，跳过")
        return None

    stance_by_agent = _load_stance_by_agent(config)

    trajectory, polarization, net_by_agent = _score_stance_trajectory(actions_path, stance_by_agent)

    conn = None
    try:
        conn = sqlite3.connect(db_path)
        interaction = _compute_interaction_ratio(
            conn, stance_by_agent, _event_post_contents_for_run(config.get("event_config"))
        )
        communities = _detect_follow_communities(conn, stance_by_agent, log_info)
        cascades = _compute_cascades(conn)
    except Exception as e:  # noqa: BLE001
        log_info(f"涌现度量[{platform}]：数据库读取失败，部分跳过: {e}")
        interaction = {"cross_stance_interaction_ratio": 0.0, "cross_stance": 0, "within_stance": 0}
        communities = []
        cascades = []
    finally:
        if conn is not None:
            try:
                conn.close()
            except sqlite3.Error:
                pass

    # 末轮立场占比（供报告 agent 直接引用“支持率从 X% 跌至 Y%”）
    final_stance_share: Dict[str, float] = {}
    if trajectory:
        last = trajectory[-1]["by_stance"]
        total = sum(last.values()) or 1
        final_stance_share = {s: round(v / total, 4) for s, v in last.items()}

    metrics = {
        "platform": platform,
        "polarization_index": polarization,
        "cross_stance_interaction_ratio": interaction.get("cross_stance_interaction_ratio", 0.0),
        "interaction_counts": {
            "cross_stance": interaction.get("cross_stance", 0),
            "within_stance": interaction.get("within_stance", 0),
        },
        "final_stance_share": final_stance_share,
        "stance_trajectory": trajectory,
        "follow_communities": communities,
        "cascades": cascades,
        "num_speaking_agents": len(net_by_agent),
        "sentiment_method": "lexicon",
    }
    return metrics


def write_emergent_metrics(
    simulation_dir: str,
    config: Dict[str, Any],
    platforms: List[str],
    log_info,
) -> None:
    """EXECPLAN2 I-2-0: 计算并原子写出涌现度量产物（仅 SIM_EMERGENT_METRICS=true 时调用）。

    产出：
      - {platform}_emergent_metrics.json（每平台）
      - emergent_metrics.json（聚合，供报告 agent 读取）
    全程 try/except 隔离，任何失败都不影响已完成的模拟。
    """
    from app.utils.atomic import write_json_atomic  # 复用原子写助手

    aggregate: Dict[str, Any] = {
        "simulation_id": config.get("simulation_id"),
        "generated_at": datetime.now().isoformat(),
        "platforms": {},
    }
    for platform in platforms:
        try:
            metrics = compute_emergent_metrics(simulation_dir, config, platform, log_info)
        except Exception as e:  # noqa: BLE001
            log_info(f"涌现度量[{platform}]：计算异常，跳过该平台: {e}")
            metrics = None
        if metrics is None:
            continue
        aggregate["platforms"][platform] = metrics
        try:
            write_json_atomic(
                os.path.join(simulation_dir, f"{platform}_emergent_metrics.json"),
                metrics,
            )
            log_info(
                f"涌现度量[{platform}]：极化={metrics['polarization_index']}, "
                f"跨立场互动比={metrics['cross_stance_interaction_ratio']}, "
                f"社区数={len(metrics['follow_communities'])}"
            )
        except Exception as e:  # noqa: BLE001
            log_info(f"涌现度量[{platform}]：写出失败: {e}")

    if aggregate["platforms"]:
        try:
            write_json_atomic(
                os.path.join(simulation_dir, "emergent_metrics.json"),
                aggregate,
            )
        except Exception as e:  # noqa: BLE001
            log_info(f"涌现度量：聚合产物写出失败: {e}")


class PlatformSimulation:
    """平台模拟结果容器"""
    def __init__(self):
        self.env = None
        self.agent_graph = None
        self.total_actions = 0


# ============== NEXTSTEPS P1-1/P1-2/P1-4: post-sim decision channel helpers ==============
def _read_actions_for_decision_channel(simulation_dir: str) -> List[Dict[str, Any]]:
    """读取两平台 actions.jsonl 的动作记录（跳过 round_start/end/sim_end 事件），
    汇成 [{round, agent_id, agent_name}] 供决策通道按轮回放。失败/缺失 → []。

    SIM-5：SIM_EVENT_PROVENANCE 开（默认）→ 跳过定时事件回放与采样点赞行（发帖账号/采样者
    并未作出该动作），与 in-band 名册只见有机+回应动作一致。"""
    skip_injected = _event_provenance_enabled()
    out: List[Dict[str, Any]] = []
    for plat in ("twitter", "reddit"):
        path = os.path.join(simulation_dir, plat, "actions.jsonl")
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    if rec.get("event_type") or rec.get("agent_id") is None:
                        continue
                    if skip_injected:
                        _args = rec.get("action_args")
                        if isinstance(_args, dict) and (_args.get("is_scheduled_event")
                                                        or _args.get("is_engagement_sample")):
                            continue
                    out.append({"round": rec.get("round", 0),
                                "agent_id": rec.get("agent_id"),
                                "agent_name": rec.get("agent_name", "")})
        except OSError:
            continue
    return out


def _build_round_to_date(seed: Dict[str, Any], config: Dict[str, Any]):
    """NEXTSTEPS P1-2: round(1-based) → ISO 日期。

    CAL-TEMPORAL: config 顶层 temporal_config.round_dates 存在时改用精确查表
    {round+1: period_end}（日历模式每轮对应真实日历时段，不再线性内插；round<1 回
    as_of_date，越界钳制到末时段）；否则回退 as_of_date→horizon_date 线性映射
    （hours 模式旧行为逐字节不变）。无法确定（缺日期/非法/horizon≤as_of）→ None。"""
    from datetime import datetime as _dt, timedelta as _td
    _tc_cal = (config.get("temporal_config") or {}) if isinstance(config, dict) else {}
    _round_dates = _tc_cal.get("round_dates") if isinstance(_tc_cal, dict) else None
    if _round_dates:
        _mapping: Dict[int, str] = {}
        for _rp_i, _rp in enumerate(_round_dates):
            if not isinstance(_rp, dict):
                continue
            _pe = str(_rp.get("period_end", "") or "")[:10]
            if not _pe:
                continue
            try:
                _mapping[int(_rp.get("round", _rp_i)) + 1] = _pe
            except (TypeError, ValueError):
                _mapping[_rp_i + 1] = _pe
        if _mapping:
            _keys = sorted(_mapping)
            _cal_as_of = (str((seed or {}).get("as_of_date", "") or "")[:10]
                          or str(_tc_cal.get("as_of_date", "") or "")[:10])

            def _r2d_exact(rnd: int) -> str:
                if rnd in _mapping:
                    return _mapping[rnd]
                if rnd < _keys[0]:  # round 0 基线（决策通道首行等）→ as_of
                    return _cal_as_of or _mapping[_keys[0]]
                return _mapping[_keys[-1]]

            return _r2d_exact
    as_of, horizon = seed.get("as_of_date"), seed.get("horizon_date")
    if not as_of or not horizon:
        return None
    try:
        d0 = _dt.fromisoformat(str(as_of)[:10])
        d1 = _dt.fromisoformat(str(horizon)[:10])
    except (ValueError, TypeError):
        return None
    if d1 <= d0:
        return None
    tc = config.get("time_config", {}) if isinstance(config, dict) else {}
    try:
        total_hours = float(tc.get("total_simulation_hours", 72) or 72)
        mpr = float(tc.get("minutes_per_round", 60) or 60)
    except (TypeError, ValueError):
        total_hours, mpr = 72.0, 60.0
    total_rounds = max(1, int(total_hours * 60 / mpr))
    span_days = (d1 - d0).days

    def _r2d(rnd: int) -> str:
        frac = min(1.0, max(0.0, float(rnd) / total_rounds))
        return (d0 + _td(days=int(span_days * frac))).date().isoformat()

    return _r2d


# ============================================================================
# CAL-TEMPORAL in-band 世界演化（spec §4，SIM_DECISION_CHANNEL_INBAND，默认开，仅日历模式）。
# 每轮有机动作 + 参与度注入落账后：本轮动作 → 名册（decision_channel._build_active_roster）
# → 承诺 elicit（decision_channel.elicit_round，时段框架）→ WorldState.step（真实时段 gap
# 惯性 + WORLDSTATE_ENTROPY_MIX 熵地板）→ 定性摘要（world_delta.build_world_delta）喂下一轮
# WORLD CLOCK 头 + 定量份额落 world_digest.jsonl（审计产物——份额只活在这里和轨迹里，
# 绝不进 agent 可见文本，herding guard）。收尾写 world_state_trajectory.json（schema v3）。
# ============================================================================
_INBAND_EVOLUTIONS: Dict[str, "_InbandWorldEvolution"] = {}
# 收尾兜底判据：本进程内该 sim 目录是否已由 in-band 写出轨迹（post-hoc 回退据此跳过）。
_INBAND_TRAJ_WRITTEN: Dict[str, bool] = {}


class _InbandWorldEvolution:
    """日历模式的轮内世界演化——双平台共享的单一 WorldState（spec §4/§6）。

    双平台并行时共用一个实例（按 sim 目录注册，expected=semaphore_platforms）：每轮
    各平台交付（deliver）本轮有机动作与到期事件，凑齐全部平台的轮次水位后按轮序步进
    一次（合并名册，一轮只 elicit/step 一次——与 post-hoc 回放的"单一共享 WorldState"
    口径一致）；死轮/失败轮只推水位（heartbeat），防止双平台按轮配对停摆。

    全程 degrade-safe：任何一步异常 → 告警日志 + 下一轮空摘要，模拟照常推进；LLM 不可用
    → 承诺恒空（轨迹退化为先验 + 熵地板）；断点续跑重启进程后 WorldState 从种子重建，
    轨迹只覆盖续跑轮次（诚实降级）。无收敛早停：轮循环永远跑满判定日，converged_at
    仅作为稳定性信号记录（spec §6）。
    """

    def __init__(self, config: Dict[str, Any], simulation_dir: str,
                 expected_platforms: int, log_info) -> None:
        from app.services import decision_channel as _dc_mod
        from app.services import decision_validation as _dv_mod
        from app.services.worldstate import WorldState
        self._dc = _dc_mod
        self._dv = _dv_mod
        self._log = log_info
        self._dir = simulation_dir
        self._expected = max(1, int(expected_platforms or 1))
        tc = config.get("temporal_config") or {}
        self._tc = tc if isinstance(tc, dict) else {}
        seed = config.get("world_state_seed") or {}
        self._seed = seed if isinstance(seed, dict) else {}
        self._scenarios = [str(s) for s in (self._seed.get("scenarios") or []) if str(s).strip()]
        # 与 post-hoc 决策通道同一组旋钮（SIM_DECISION_INERTIA / SIM_CONVERGENCE_EPS）
        try:
            self._inertia = float(os.environ.get("SIM_DECISION_INERTIA", "0.7") or "0.7")
        except ValueError:
            self._inertia = 0.7
        try:
            self._conv_eps = float(os.environ.get("SIM_CONVERGENCE_EPS", "0.02") or "0.02")
        except ValueError:
            self._conv_eps = 0.02
        self._ws = WorldState(self._scenarios, self._seed.get("base_rates"), inertia=self._inertia)
        self._base_shares = dict(self._ws.shares)  # 不变的种子先验（喂 elicit，绝不喂演化份额）
        agent_configs = config.get("agent_configs")
        self._activation = self._dc._activation_weight_map(agent_configs)
        self._power = self._dc._outcome_power_map(agent_configs)
        self._meta = self._dc._agent_meta_map(agent_configs)
        self._cap = int(self._dc._cfg("DECISION_CHANNEL_MAX_ACTIVE", 60) or 60)
        self._conv_window = max(1, int(self._dc._cfg("SIM_CONVERGENCE_WINDOW", 3) or 3))
        self._entropy_on = _flag_true("WORLDSTATE_ENTROPY_MIX", "true")  # spec §1: 熵地板开关
        unit = str(self._tc.get("unit") or "").strip() or None
        if not unit:
            unit = self._dc._infer_calendar_unit(self._tc.get("round_dates"))
        self._unit = unit
        # 日历模式 avg_gap = 单位名义天数（spec §4）；snap 后首/尾残段 gap 偏离名义值时
        # _inertia_for_gap 据此放行更少/更多变化。
        self._avg_gap = dict(self._dc._UNIT_NOMINAL_DAYS).get(unit or "", 0.0)
        try:
            self._n_rounds = int(self._tc.get("n_rounds") or 0) or None
        except (TypeError, ValueError):
            self._n_rounds = None
        self._horizon_date = self._tc.get("horizon_date") or self._seed.get("horizon_date")
        self._horizon_source = self._tc.get("horizon_source") or self._seed.get("horizon_source")
        self._horizon_defaulted = self._tc.get("horizon_defaulted")
        if self._horizon_defaulted is None:
            self._horizon_defaulted = self._seed.get("horizon_defaulted")
        self._as_of_date = str(self._tc.get("as_of_date") or self._seed.get("as_of_date") or "") or None
        row0: Dict[str, Any] = {"round": 0, **self._ws.outcome()}
        if self._as_of_date:
            row0["as_of"] = self._as_of_date  # spec §6: 第 0 行 as_of=as_of_date
        self._trajectory: List[Dict[str, Any]] = [row0]
        self._decisions: List[Dict[str, Any]] = []
        # SIM-2：逐轮名册校验记录（elicit_round 写入 ctx["decision_validation"]；旧签名的
        # elicit 替身不写 → 无记录、无新键、裁定不变）。只收已步进轮，收尾汇总成 fallback_share。
        self._validation_records: List[Dict[str, Any]] = []
        self._watermark: Dict[str, int] = {}   # 平台 → 已交付/心跳的最高轮次（0 基）
        self._done: set = set()                # 已结束回路的平台
        self._pending: Dict[int, Dict[str, Any]] = {}  # 轮次 → 合并缓冲（等齐平台水位）
        self._delta_text = ""                  # 最近一次步进产出的定性摘要（喂下一轮头部）
        self._prev_date = self._as_of_date
        self._stepped = 0
        self._max_round = 0
        # SIM-1：本进程见过的最高轮次（1 基，deliver/heartbeat 均计）。与 WorldState 实际
        # 入账轮数之差 = 未入账轮（有损续跑前的轮次、全平台死轮），裁定时按 missing 计入分母。
        self._max_seen_round = 0
        self._converged_at: Optional[int] = None
        self._stable_streak = 0
        self._finalized = False
        try:
            from app.utils.llm_client import LLMClient
            # DEFECT-3: in-band 演化的 LLM 调用同样进 sim token 计量（不经 camel 边界）。
            self._llm = _wrap_llm_client_usage(LLMClient())
        except Exception as _llm_err:  # noqa: BLE001 — LLM 缺席时演化退化为先验+熵地板
            self._llm = None
            log_info(f"in-band 世界演化 LLM 初始化失败（承诺恒空，轨迹退化为先验+熵地板）: {_llm_err}")

    # ------------------------------------------------------------------ 轮内接口
    def deliver(self, platform: str, round_num: int, period: Optional[Dict[str, Any]],
                round_actions: List[Dict[str, Any]],
                fired_events: List[Dict[str, Any]]) -> None:
        """交付某平台本轮（0 基）的有机动作与到期事件；凑齐全部平台水位后按轮序步进。
        内部全隔离：任何异常 → 告警 + 下一轮空摘要，绝不中断轮循环（spec §4）。"""
        try:
            self._max_seen_round = max(self._max_seen_round, int(round_num) + 1)
            p = str(platform)
            buf = self._pending.get(round_num)
            if buf is None:
                buf = {"period": None, "actions": [], "events": [], "event_keys": set()}
                self._pending[round_num] = buf
            if isinstance(period, dict) and period:
                buf["period"] = period
            for a in round_actions or []:
                if isinstance(a, dict):
                    buf["actions"].append(a)
            # 同一份日程事件配置在两平台各触发一次 → 按 (date, content) 去重
            for ev in fired_events or []:
                if not isinstance(ev, dict):
                    continue
                key = (str(ev.get("date", "") or ""), str(ev.get("content", "") or ""))
                if key in buf["event_keys"]:
                    continue
                buf["event_keys"].add(key)
                buf["events"].append(ev)
            self._watermark[p] = max(self._watermark.get(p, -1), round_num)
            self._advance()
        except Exception as _e:  # noqa: BLE001
            self._delta_text = ""
            self._log(f"第 {round_num + 1} 轮 in-band 世界演化交付失败（已隔离，下一轮空摘要）: {_e}")

    def heartbeat(self, platform: str, round_num: int) -> None:
        """死轮/env.step 失败轮的水位推进（本平台本轮无动作可交付），
        防止双平台按轮配对停摆。绝不抛异常。"""
        try:
            self._max_seen_round = max(self._max_seen_round, int(round_num) + 1)
            p = str(platform)
            self._watermark[p] = max(self._watermark.get(p, -1), round_num)
            self._advance()
        except Exception:  # noqa: BLE001
            pass

    def latest_delta(self) -> str:
        """最近一次步进产出的定性摘要（喂下一轮 WORLD CLOCK 头；未步进/失败 → ""）。"""
        return self._delta_text

    def platform_done(self, platform: str) -> None:
        """本平台回路结束；全部平台完成时冲刷剩余轮并落轨迹（幂等）。"""
        try:
            self._done.add(str(platform))
            self._advance()
            if len(self._done) >= self._expected:
                self.force_finalize()
                _INBAND_EVOLUTIONS.pop(os.path.abspath(self._dir), None)
        except Exception as _e:  # noqa: BLE001
            self._log(f"in-band 世界演化收尾失败（已隔离）: {_e}")

    def force_finalize(self) -> None:
        """冲刷所有滞留轮次并写 world_state_trajectory.json（schema v3）+ decisions.jsonl。
        幂等；平台回路异常中断时由 main() 的兜底调用触发。无任何演化轮 → 不写轨迹
        （post-hoc 决策通道可按旧门控回退）。"""
        if self._finalized:
            return
        try:
            self._advance(flush_all=True)
        except Exception as _e:  # noqa: BLE001
            self._log(f"in-band 世界演化冲刷失败（已隔离）: {_e}")
        self._finalized = True
        if self._stepped <= 0:
            return
        try:
            from app.utils.atomic import write_json_atomic
            self._ws.converged_at = self._converged_at
            out = self._ws.outcome()
            result: Dict[str, Any] = {
                "outcome": out,
                "trajectory": self._trajectory,
                "decisions": self._decisions,
                "converged_at": self._converged_at,  # 稳定性信号——日历模式从不据此早停
                "n_rounds": self._max_round,
                "scenarios": self._scenarios,
                "schema_version": 3,
                "mode": "calendar",
            }
            if self._unit:
                result["calendar_unit"] = self._unit
            for fk, fv in (("horizon_date", self._horizon_date),
                           ("horizon_source", self._horizon_source),
                           ("horizon_defaulted", self._horizon_defaulted)):
                if fv is not None:
                    result[fk] = fv
            # SIM-1：与 post-hoc 决策通道同一套有效性裁定规则（诚实对齐，无开关）。未入账轮
            # （本进程见过但 WorldState 未步进）按 missing 计入分母——有损续跑只覆盖部分
            # 轮次时不再被判 valid（post-hoc 只入账动作日志中出现的轮次，见
            # decision_channel_verdict）。嵌套 outcome.round_accounting 保留 WorldState 原始口径。
            # 同理 converged_at / outcome.converged / outcome.convergence_state 只反映本进程实际
            # 步进的轮次，未入账轮不改它们：有损续跑时 validity=inconclusive 可与"已趋稳"并存，
            # 下游须以 validity 为准（报告侧 REPORT_WORLDSTATE_HIDE_INVALID 默认连趋稳行一并隐藏）。
            # 裁定失败只丢裁定键，绝不丢轨迹。
            # SIM-2：有校验记录时汇总 run 级 fallback_share 并折入裁定（超阈 → inconclusive）；
            # 无记录的已步进轮计作 unmeasured。汇总与裁定同进退：失败只丢裁定键。
            try:
                accounted = len(self._ws.round_statuses)
                validation_summary = None
                if self._validation_records:
                    validation_summary = self._dv.summarize_validation(
                        self._validation_records,
                        unmeasured_rounds=max(0, accounted - len(self._validation_records)))
                verdict = self._dc.decision_channel_verdict(
                    self._ws.round_accounting(),
                    unaccounted_rounds=max(0, self._max_seen_round - accounted),
                    fallback_share=(validation_summary or {}).get("fallback_share"))
                result["round_accounting"] = verdict["round_accounting"]
                result["validity"] = verdict["validity"]
                result["validity_reasons"] = verdict["validity_reasons"]
                result["forecast_effect"] = verdict["forecast_effect"]
                result["epistemic_status"] = "elicited_model_projection"
                if validation_summary is not None:
                    result["decision_validation"] = validation_summary
            except Exception as _v_err:  # noqa: BLE001
                self._log(f"in-band 有效性裁定失败（已隔离，轨迹照写、无裁定键）: {_v_err}")
            write_json_atomic(os.path.join(self._dir, "world_state_trajectory.json"), result)
            with open(os.path.join(self._dir, "decisions.jsonl"), "w", encoding="utf-8") as _df:
                for _d in self._decisions:
                    _df.write(json.dumps(_d, ensure_ascii=False) + "\n")
            _INBAND_TRAJ_WRITTEN[os.path.abspath(self._dir)] = True
            self._log(f"in-band 世界演化完成: leader={out.get('leader')} "
                      f"share={out.get('leader_share')} converged_at={self._converged_at}"
                      f"（稳定性信号，从不早停） validity={result.get('validity')}")
        except Exception as _e:  # noqa: BLE001
            self._log(f"in-band 轨迹写出失败（已隔离）: {_e}")

    # ------------------------------------------------------------------ 内部机制
    def _advance(self, flush_all: bool = False) -> None:
        """按轮序步进所有"已凑齐平台水位"的滞留轮。gate = 未完成平台的最低水位；
        所有已知平台都完成 / flush_all → 全部放行。有平台尚未进场（双平台并行开局的
        建图错峰）→ 不放行，摘要暂为 ""（诚实降级，绝不乱序步进）。"""
        if not self._pending:
            return
        if flush_all:
            gate: Optional[int] = None
        else:
            known = set(self._watermark) | self._done
            if len(known) < self._expected:
                return
            live = [self._watermark.get(p, -1) for p in known if p not in self._done]
            gate = min(live) if live else None
        for r in sorted(self._pending):
            if gate is not None and r > gate:
                break
            buf = self._pending.pop(r)
            self._step_round(r, buf)

    def _step_round(self, round_num: int, buf: Dict[str, Any]) -> None:
        """步进一轮：名册 → elicit → WorldState.step → 摘要 + world_digest.jsonl 行。
        任何异常 → 告警 + 空摘要（下一轮头部回落 "(first period)" 语义），模拟继续。"""
        try:
            period = buf.get("period") if isinstance(buf.get("period"), dict) else None
            rnd = round_num + 1  # 轨迹/digest/decisions 与 actions.jsonl 同为 1 基轮号
            period_end = (str(period.get("period_end")) if period and period.get("period_end")
                          else None)
            # 名册：本轮（两平台合并）去重行动者，附 meta + 本轮首条帖文（与 post-hoc 同口径）
            entries: Dict[Any, Dict[str, Any]] = {}
            for a in buf.get("actions") or []:
                aid = a.get("agent_id")
                if aid is None:
                    continue
                e = entries.get(aid)
                if e is None:
                    base = self._meta.get(aid, {"agent_id": aid,
                                                "name": a.get("agent_name", ""),
                                                "stance": "", "influence": ""})
                    e = dict(base)
                    entries[aid] = e
                if "post" not in e:
                    content = (a.get("action_args") or {}).get("content")
                    if content:
                        e["post"] = str(content)
            roster = self._dc._build_active_roster(
                list(entries.values()), self._activation, self._power, self._cap)
            ctx: Dict[str, Any] = {
                "llm": self._llm, "scenarios": self._scenarios,
                "base_shares": self._base_shares, "abstain_allowed": True,
                "round_num": rnd, "as_of": period_end,
            }
            if period:
                ctx.update({"period": period, "n_rounds": self._n_rounds,
                            "horizon_date": self._horizon_date, "unit": self._unit})
            commitments = self._dc.elicit_round(roster, ctx) if roster else []
            # SIM-2：本轮名册校验记录（DECISION_CHANNEL_VALIDATION 开时由 elicit_round 写入）
            validation = ctx.get("decision_validation")
            validation = validation if isinstance(validation, dict) else None
            # Foglamp WP1 (1C/I-16): elicit_round 把类型化轮结果写入 ctx["round_status"]
            # （committed/abstained/silent/failed/missing）；roster 为空即 missing。
            # 旧签名的 elicit 替身（测试/降级路径）不写状态 → 传 None，由
            # WorldState.step 按承诺内容保守推断（有有效承诺=committed，空=silent）。
            # 失败/沉默轮冻结 WorldState 且不衰减收敛 EWMA——死通道不再伪装成均衡。
            round_status = ctx.get("round_status") if roster else "missing"
            # 真实时段 gap 的惯性 + 熵地板（spec §4）；snap 后首/尾残段 gap 天然偏离名义值
            eff_inertia = self._dc._inertia_for_gap(
                self._inertia, self._prev_date, period_end, self._avg_gap)
            entropy_days = (self._dc._period_days(period)
                            if (self._entropy_on and period) else None)
            prev_shares = dict(self._ws.shares)
            self._ws.step(commitments, inertia=eff_inertia, entropy_mix_days=entropy_days,
                          round_status=round_status)
            if validation is not None:  # 与 WorldState 入账轮一一对应（步进成功后才收）
                self._validation_records.append(validation)
            out = self._ws.outcome()
            leader = out.get("leader")
            # leader_move：只取方向（up/down/flat），份额数值绝不进 agent 可见文本
            leader_move = None
            if leader:
                diff = (float(self._ws.shares.get(leader, 0.0))
                        - float(prev_shares.get(leader, 0.0)))
                direction = "up" if diff > 1e-9 else ("down" if diff < -1e-9 else "flat")
                leader_move = {"leader": leader, "direction": direction}
            # 定性摘要（喂下一轮 WORLD CLOCK 头）——纯函数，出错自身返回 ""
            from app.services.world_delta import build_world_delta
            digest_actions = []
            for a in buf.get("actions") or []:
                content = (a.get("action_args") or {}).get("content")
                if not content:
                    continue
                digest_actions.append({
                    "content": str(content),
                    "agent_name": a.get("agent_name", ""),
                    "influence_weight": self._activation.get(a.get("agent_id"), 0.0),
                })
            delta_text = build_world_delta(digest_actions, buf.get("events") or [], leader_move)
            # decisions 审计行：与 post-hoc 同口径（剥离 step 用的 weight）
            for c in commitments:
                self._decisions.append({k: v for k, v in c.items() if k != "weight"})
            # 轨迹行（spec §6：日期化 + 时段字段；as_of = period_end）
            snap: Dict[str, Any] = {"round": rnd, **out}
            snap["round_status"] = round_status  # Foglamp 1C/I-16：逐轮有效性入账
            if period_end:
                snap["as_of"] = period_end
            if period:
                for fk in ("period_start", "period_end", "label"):
                    if period.get(fk):
                        snap[fk] = str(period[fk])
            if validation is not None:
                snap["decision_validation"] = validation
            self._trajectory.append(snap)
            # world_digest.jsonl（审计产物）：定量份额只活在这里和轨迹里（spec §4）
            digest_row = {
                "round": rnd,
                "period_start": (str(period.get("period_start"))
                                 if period and period.get("period_start") else None),
                "period_end": period_end,
                "digest": delta_text,
                "shares": dict(self._ws.shares),
                "leader": leader,
                "delta": {k: round(float(self._ws.shares.get(k, 0.0))
                                   - float(prev_shares.get(k, 0.0)), 6)
                          for k in self._ws.shares},
            }
            if validation is not None and validation.get("measured") is True:
                # SIM-2：名册覆盖（失败轮的 {"measured": False} 没有计数可报）
                digest_row["actor_coverage"] = {
                    k: validation.get(k) for k in ("roster_size", "accepted", "abstained",
                                                   "rejected", "missing_from_reply")}
            with open(os.path.join(self._dir, "world_digest.jsonl"), "a", encoding="utf-8") as _f:
                _f.write(json.dumps(digest_row, ensure_ascii=False) + "\n")
            # 收敛只记信号（SIM-1 同窗口口径），绝不早停
            if self._ws.converged(self._conv_eps):
                self._stable_streak += 1
                if (self._converged_at is None and self._stable_streak >= self._conv_window
                        and rnd >= 2):
                    self._converged_at = rnd
            else:
                self._stable_streak = 0
            self._stepped += 1
            self._max_round = max(self._max_round, rnd)
            if period_end:
                self._prev_date = period_end
            self._delta_text = delta_text
        except Exception as _e:  # noqa: BLE001 — spec §4: 失败 → 告警 + 下一轮空摘要
            self._delta_text = ""
            self._log(f"第 {round_num + 1} 轮 in-band 世界演化失败（已隔离，下一轮空摘要）: {_e}")


def _get_inband_evolution(config: Dict[str, Any], simulation_dir: str,
                          expected_platforms: int, log_info) -> Optional[_InbandWorldEvolution]:
    """取/建本 sim 目录共享的 in-band 演化器（仅日历模式调用方进入）。
    SIM_DECISION_CHANNEL_INBAND 关闭 / world_state_seed.scenarios 为空 → None（静默关闭，
    spec §4）；构建失败同样 None（degrade-safe，模拟照跑，只是没有世界演化）。"""
    try:
        if not _flag_true("SIM_DECISION_CHANNEL_INBAND", "true"):
            return None
        seed = config.get("world_state_seed") if isinstance(config, dict) else None
        if not (isinstance(seed, dict) and seed.get("scenarios")):
            # CAL-TEMPORAL 可观测性：种子无情景 ⇒ 世界演化关闭、轨迹退化为先验（无 delta、
            # 无 world_state_trajectory.json）。此前静默返回 None——现明确告警，便于运维区分
            # 「按配置关闭」与「研究阶段未产出 forecast 情景」这一真实降级。
            log_info("in-band 世界演化关闭：world_state_seed 无 scenarios"
                     "（研究阶段未产出 forecast 情景 → 轨迹将退化为先验，无逐轮演化）")
            return None
        key = os.path.abspath(simulation_dir)
        evo = _INBAND_EVOLUTIONS.get(key)
        if evo is None:
            _INBAND_TRAJ_WRITTEN.pop(key, None)  # 新一场演化 → 清掉同进程旧运行的落盘标记
            evo = _InbandWorldEvolution(config, simulation_dir,
                                        int(expected_platforms or 1), log_info)
            _INBAND_EVOLUTIONS[key] = evo
            log_info(f"in-band 世界演化已启用（SIM_DECISION_CHANNEL_INBAND，"
                     f"platforms={evo._expected}，scenarios={len(evo._scenarios)}）")
        return evo
    except Exception as _e:  # noqa: BLE001
        log_info(f"in-band 世界演化初始化失败（已隔离，世界演化关闭）: {_e}")
        return None


def _finalize_inband_world_evolution(simulation_dir: str, log_info) -> bool:
    """CAL-TEMPORAL 收尾兜底（main() 在两平台 gather 之后调用）：平台回路异常中断导致
    platform_done 未走到时，强制冲刷滞留轮并落轨迹。返回本次运行 in-band 是否已写出
    world_state_trajectory.json（post-hoc 决策通道据此跳过/回退，spec §4）。"""
    key = os.path.abspath(simulation_dir)
    evo = _INBAND_EVOLUTIONS.pop(key, None)
    if evo is not None:
        try:
            evo.force_finalize()
        except Exception as _e:  # noqa: BLE001
            log_info(f"in-band 世界演化兜底收尾失败（已隔离）: {_e}")
    return bool(_INBAND_TRAJ_WRITTEN.get(key))


# ============================================================================
# RUN-7: 轮级检查点与断点续跑（默认关，SIM_RESUME=true 开启）。
# 每轮 ~32 次 LLM 调用，崩溃/被杀/后端重启曾意味着 100% 花费作废并从第 0 轮重烧。
# 检查点只记「已完成轮次 + trace 游标 + 累计动作数」；续跑保留模拟 DB——OASIS 的
# sign_up 用 user_id=agent_id 显式主键插入，重登录冲突被静默容忍且旧行不受影响，
# 故 DB 复用安全。已知取舍（诚实降级，不假装无损）：agent 的进程内会话记忆与
# Twitter sandbox 时钟在续跑后重置；崩溃时进行到一半的轮次被整轮丢弃。
# XRUN-4: 磁盘预检 + 连续同类 env.step 失败熔断（磁盘耗尽曾导致 10+ 轮静默跳过、
# LLM 额度对着死 SQLite 连烧 5 小时）。
# ============================================================================
def _resume_checkpointing_enabled() -> bool:
    """SIM_RESUME=true 时每轮落检查点（历史契约：开启续跑者必然需要写检查点）。"""
    return _flag_true("SIM_RESUME", "false")


def _checkpoint_enabled() -> bool:
    """ITEM 3: 轮级检查点写入开关。SIM_CHECKPOINT（默认 true）主控——每轮原子落盘 checkpoint.json，
    使任意崩溃/被杀/后端重启后的运行都可被续跑（续跑本身另由 SIM_RESUME/--resume 触发，见
    start_simulation）。置 SIM_CHECKPOINT=false → 完全不产出 checkpoint.json（回到 RUN-7 早期
    degrade-safe 行为）。SIM_RESUME=true 视为隐式开启写检查点（向后兼容），故任一为真即写。"""
    return _flag_true("SIM_CHECKPOINT", "true") or _resume_checkpointing_enabled()


def _checkpoint_file(simulation_dir: str, platform: str) -> str:
    return os.path.join(simulation_dir, platform, "checkpoint.json")


def _config_hash(config: Dict[str, Any]) -> str:
    """ITEM 3: 稳定 config 指纹（整份 config 规范化 JSON 的 sha256）。用于续跑前校验——
    配置若变更（agent/事件/时长/recsys 任一改动），旧 DB/世界与新意图不一致，必须放弃续跑、
    从头重跑（诚实降级）。任何异常返回 ""（视为无指纹 → 向后兼容旧检查点，不阻断续跑）。"""
    try:
        import hashlib
        blob = json.dumps(config, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
    except Exception:  # noqa: BLE001 — 指纹计算失败退化为无指纹，绝不中断模拟
        return ""


def _capture_rng_state() -> Optional[Dict[str, Any]]:
    """ITEM 3: 捕获采样 RNG（_RNG，即 python random）当前状态，供续跑时精确恢复采样流。
    仅在 SIM_SEED 设定（确定性采样）时有实际意义；未设定时恢复也无害。numpy 未被本脚本使用
    （"numpy if used" —— 此处未用），故不捕获。任何异常返回 None（降级：不恢复，等价旧行为）。"""
    try:
        st = _RNG.getstate()
        # getstate() -> (version:int, internalstate:tuple[int], gauss_next:float|None)；tuple→list 以可 JSON 序列化
        return {"py_random": [st[0], list(st[1]), st[2]]}
    except Exception:  # noqa: BLE001
        return None


def _restore_rng_state(rng_state: Optional[Dict[str, Any]]) -> bool:
    """ITEM 3: 从检查点恢复 _RNG 状态（与 _capture_rng_state 对称）。成功 True，否则 False（降级）。"""
    if not isinstance(rng_state, dict):
        return False
    py = rng_state.get("py_random")
    if not py:
        return False
    try:
        _RNG.setstate((int(py[0]), tuple(int(x) for x in py[1]), py[2]))
        return True
    except Exception:  # noqa: BLE001 — 状态非法则不恢复（续跑采样流回退为非复现，但不崩溃）
        return False


def _write_round_checkpoint(
    simulation_dir: str,
    platform: str,
    completed_round: int,
    last_rowid: int,
    total_rounds: int,
    total_actions: int,
    config_hash: str = "",
    rng_state: Optional[Dict[str, Any]] = None,
) -> None:
    """每轮结束后原子落盘微型检查点（best-effort；开关关闭时 no-op）。

    ITEM 3: 追加两个可选、向后兼容字段——config_hash（续跑前校验配置未变）与 rng_state
    （python random 采样流，SIM_SEED 设定时可跨崩溃边界复现）。缺省二者时，产物与 RUN-7 逐字节一致。
    """
    if not _checkpoint_enabled():
        return
    try:
        from app.utils.atomic import write_json_atomic
        payload = {
            "platform": platform,
            "completed_round": int(completed_round),
            "last_rowid": int(last_rowid),
            "total_rounds": int(total_rounds),
            "total_actions": int(total_actions),
            "updated_at": datetime.now().isoformat(),
        }
        if config_hash:
            payload["config_hash"] = str(config_hash)
        if rng_state is not None:
            payload["rng_state"] = rng_state
        write_json_atomic(_checkpoint_file(simulation_dir, platform), payload)
    except Exception:  # noqa: BLE001 — 检查点是旁路持久化，绝不影响模拟主循环
        pass


def _load_round_checkpoint(simulation_dir: str, platform: str) -> Optional[Dict[str, Any]]:
    """读取并校验平台检查点；缺失/损坏/未完成任何轮次 → None（全新运行）。"""
    path = _checkpoint_file(simulation_dir, platform)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and int(data.get("completed_round", 0)) >= 1:
            return data
    except (OSError, ValueError, TypeError):
        pass
    return None


def _max_trace_rowid(db_path: str) -> int:
    """trace 表当前最大 rowid；任何失败返回 0（退化为从头重放的旧行为）。"""
    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(rowid), 0) FROM trace")
        row = cur.fetchone()
        conn.close()
        return int(row[0] or 0)
    except Exception:  # noqa: BLE001
        return 0


def _free_disk_error(simulation_dir: str) -> Optional[str]:
    """XRUN-4: 可用磁盘低于 SIM_MIN_FREE_DISK_GB（默认 2；<=0 关闭）时返回错误描述。"""
    try:
        min_gb = float(_cfg_flag("SIM_MIN_FREE_DISK_GB", "2"))
    except (TypeError, ValueError):
        min_gb = 2.0
    if min_gb <= 0:
        return None
    try:
        free = shutil.disk_usage(simulation_dir).free
    except OSError:
        return None  # 查询失败不阻断（degrade-safe）
    if free < min_gb * (1024 ** 3):
        return (f"可用磁盘 {free / 1024 ** 3:.2f} GB 低于阈值 {min_gb} GB"
                f"（SIM_MIN_FREE_DISK_GB）——SQLite/日志随时会写失败")
    return None


def _step_failure_limit() -> int:
    """XRUN-4: 连续同类 env.step 失败的熔断阈值（默认 3；0=不熔断，维持旧的无限跳轮）。"""
    try:
        return max(0, int(_cfg_flag("SIM_STEP_FAILURE_LIMIT", "3")))
    except (TypeError, ValueError):
        return 3


# ============================================================================
# ITEM 20 — 参与度采样（LIKE_POST）运行时接入。纯采样算法在 app.services.agent_dynamics
# .sample_engagement_likes（确定性、可离线单测）；这里只做 DB 取本轮新帖 + 构造 ManualAction
# 注入 env + 记录动作三件副作用。全部 env 门控、默认开、降级安全（任何异常 → 0，不中断模拟）。
# ============================================================================
def _engagement_sampler_enabled() -> bool:
    """SIM_ENGAGEMENT_SAMPLER：每轮有机动作后补一层被动点赞。

    默认 auto：回应阶段（SIM_REACTION_PHASE）开启时关闭——采样赞是随机的「背书」，会让
    出口管制机构给被管制方点赞这类与角色矛盾的互动混进数据；回应阶段里点赞由 agent 自己
    按身份决定。回应阶段关闭时照旧开启。显式 true/false 永远优先。
    """
    raw = _cfg_flag("SIM_ENGAGEMENT_SAMPLER", "auto").strip().lower()
    if raw in ("", "auto"):
        return not _reaction_phase_enabled()
    return raw in ("true", "1", "yes", "on")


def _engagement_rate() -> float:
    """SIM_ENGAGEMENT_RATE：每个活跃 agent 本轮产生一次点赞的概率（clamp 到 [0,1]，默认 0.3）。"""
    try:
        r = float(_cfg_flag("SIM_ENGAGEMENT_RATE", "0.3"))
    except (TypeError, ValueError):
        return 0.3
    return min(1.0, max(0.0, r))


def _max_follows_per_agent_round() -> int:
    """SIM_MAX_FOLLOWS_PER_AGENT_ROUND：每个 follower 的种子 FOLLOW 动作上限（默认 3；<=0=不限）。"""
    try:
        return int(_cfg_flag("SIM_MAX_FOLLOWS_PER_AGENT_ROUND", "3"))
    except (TypeError, ValueError):
        return 3


def _max_post_id(db_path: str) -> int:
    """取当前 post 表最大 post_id（作为参与度采样的初始水位，跳过 round-0 种子帖）。缺表/异常 → 0。"""
    if not os.path.exists(db_path):
        return 0
    try:
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT MAX(post_id) FROM post").fetchone()
        finally:
            conn.close()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception:  # noqa: BLE001 — 采样是附加真实感层，取水位失败退回 0（首轮会含种子帖，仍安全）
        return 0


def _fetch_round_posts(
    db_path: str, last_post_id: int, agent_names: Dict[int, str]
) -> Tuple[Dict[int, int], int]:
    """取 post_id > last_post_id 的本轮新帖及其作者 agent_id（join user 表）。
    返回 ({post_id: author_agent_id}, 新水位)。缺表/异常 → ({}, last_post_id)。"""
    posts: Dict[int, int] = {}
    hw = int(last_post_id or 0)
    if not os.path.exists(db_path):
        return posts, hw
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT p.post_id, u.agent_id
                FROM post p LEFT JOIN user u ON p.user_id = u.user_id
                WHERE p.post_id > ?
                """,
                (int(last_post_id or 0),),
            )
            for post_id, agent_id in cur.fetchall():
                if post_id is None:
                    continue
                pid = int(post_id)
                posts[pid] = int(agent_id) if agent_id is not None else -1
                if pid > hw:
                    hw = pid
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 取帖失败即本轮不采样（degrade-safe）
        return {}, int(last_post_id or 0)
    return posts, hw


async def inject_engagement_likes(
    env,
    db_path: str,
    engagement_state: Dict[str, int],
    active_agents: List[Tuple[int, Any]],
    actual_actions: List[Dict[str, Any]],
    round_num: int,
    agent_names: Dict[int, str],
    action_logger,
    rng,
    rate: float,
    last_rowid: int,
    log_info,
) -> Tuple[int, int]:
    """ITEM 20 (SIM_ENGAGEMENT_SAMPLER): 每轮有机动作后，确定性采样 LIKE_POST 从本轮活跃 agent
    落到本轮新帖上（权重 = 1 + 该帖本轮已获评论/点赞），补足 OASIS 默认 feed「满屏帖 0 赞」的
    纯广播失真。注入的赞标记 is_engagement_sample=True——run_summary 的有机比例侦测器据此排除
    （诚实：采样赞不得掩盖 agent 自身零点赞的塌缩）。

    返回 (注入的点赞数, 新 last_rowid)。任何异常 → (0, 原 last_rowid)（degrade-safe）。
    """
    try:
        from app.services.agent_dynamics import sample_engagement_likes

        # 1. 本轮新帖（post_id > 上轮水位）及作者
        prev_hw = int(engagement_state.get("last_post_id", 0) or 0)
        new_posts, hw = _fetch_round_posts(db_path, prev_hw, agent_names)
        if hw > prev_hw:
            engagement_state["last_post_id"] = hw
        if not new_posts:
            return 0, last_rowid

        # 2. 权重 = 1 + 本轮该帖收到的评论/点赞（winner-take-all 真实感）
        from collections import defaultdict as _dd
        engaged = _dd(int)
        for a in actual_actions:
            at = a.get("action_type")
            pid = (a.get("action_args") or {}).get("post_id")
            if pid is not None and at in ("CREATE_COMMENT", "LIKE_POST", "DISLIKE_POST"):
                try:
                    engaged[int(pid)] += 1
                except (TypeError, ValueError):
                    continue
        post_weights = {pid: 1.0 + engaged.get(pid, 0) for pid in new_posts}
        post_authors = dict(new_posts)

        # 3. 采样（纯函数，rng 确定性）
        id_to_agent = {int(aid): ag for aid, ag in active_agents}
        pairs = sample_engagement_likes(
            post_weights, post_authors, list(id_to_agent.keys()), rate, rng
        )
        if not pairs:
            return 0, last_rowid

        # 4. 构造 LIKE_POST ManualAction 注入 env（每个 liker 至多一次，满足单 step 单动作约束）
        step_actions = {}
        for liker, pid in pairs:
            ag = id_to_agent.get(int(liker))
            if ag is None:
                continue
            step_actions[ag] = ManualAction(
                action_type=ActionType.LIKE_POST,
                action_args={"post_id": int(pid)},
            )
        if not step_actions:
            return 0, last_rowid
        await env.step(step_actions)

        # 5. 推进 last_rowid 丢弃这些赞的 trace 行（避免下一轮 fetch 重复记账），改为
        #    手动按本轮记录（带 is_engagement_sample 标记——比例侦测器据此排除）。
        _, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        injected = 0
        if action_logger:
            for liker, pid in pairs:
                if int(liker) not in id_to_agent:
                    continue
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=int(liker),
                    agent_name=agent_names.get(int(liker), f"Agent_{int(liker)}"),
                    action_type="LIKE_POST",
                    action_args={"post_id": int(pid), "is_engagement_sample": True},
                )
                injected += 1
        else:
            injected = len(step_actions)
        return injected, last_rowid
    except Exception as e:  # noqa: BLE001 — 采样是附加真实感层，失败绝不中断模拟
        log_info(f"参与度采样注入失败，跳过（不中断模拟）: {e}")
        return 0, last_rowid


# ============================================================================
# SIM-REACT: 每轮「回应阶段」——让 agent 真正回应彼此的帖子。
# ----------------------------------------------------------------------------
# 取证（pipe_6c4190b31f0b / sim_0170a91d15a3，GLM-5.3，日历模式半年/轮）：OASIS 给每个
# SocialAgent 设 max_iteration=1，即每个活跃 agent 每轮只有一次模型调用；世界时钟又把这次
# 调用定性为「本时段最重要的公开动作」。前 19 轮 Twitter 有机动作 200 帖 : 9 评论，Reddit
# 190 帖 : 37 评论——agent 各发各的通告，几乎从不回应彼此。
#
# 方案：有机发帖 step 落账后，本轮活跃 agent 各做一次「回应」调用：
#   * 候选帖 = 本轮 + 上轮的他人帖子（及别人刚回复了你的自己的帖子），按与该 agent 的
#     相关性排序取 ≤3 条（点名提到你 / 别人回复了你 / 你关注作者 / 话题与你的利益重合 /
#     较新），并对同一帖的回应者数量做分散惩罚，避免全员挤在一条帖子下；
#   * 提示要求：针对主帖的具体主张/决定/数字作答，补充主帖没说的信息，以该角色公开发声的
#     方式、按与作者的关系（盟友/竞争者/监管者）表态，并写成本次模拟的输出语言；
#   * 调用在一个无状态的辅助 ChatAgent 里进行：沿用该 agent 的 system prompt、模型与已绑定
#     其身份的动作工具，但只给回复与背书工具（create_comment / like_post / like_comment；
#     没有 create_post，也没有 quote_post——实测 GLM 在 Twitter 上 11/13 选了引用转发，
#     引用会变成新的顶层帖子而非帖子下的回复，正是要修的「只发帖不回复」）。不把回应提示写进 agent 的长期记忆——camel 对本模型
#     的上下文上限按 999,999,999 token 计，每轮追加的候选帖会让之后每次调用的输入线性膨胀；
#     只回写一条简短的「你本期的回应」记录，保证后续轮次的连续性。
# 可降级：任何异常只跳过该 agent / 本阶段，绝不中断轮循环。SIM_REACTION_PHASE=false 关闭。
# ============================================================================
_REACTION_TOOL_NAMES = ("create_comment", "like_post", "like_comment")
_REACTION_REPLY_TOOLS = ("create_comment",)
_REACTION_MAX_CANDIDATES = 3
_REACTION_WINDOW_POSTS = 60
_REACTION_POST_CHARS = 700
_REACTION_QUOTED_CHARS = 240
_REACTION_REPLY_CHARS = 240
_REACTION_THREAD_REPLIES = 3
_REACTION_MAX_WORDS = 90
_REACTION_STEP_TIMEOUT_S = 240.0
_REACTION_NOTE_CHARS = 320

_CJK_RUN_RE = re.compile(r"[㐀-䶿一-鿿]+")
_LATIN_LETTER_RE = re.compile(r"[A-Za-z]")
_TOPIC_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9\-]{3,}")
_ACRONYM_RE = re.compile(r"\b[A-Z][A-Z0-9&]{1,9}\b")
_TOPIC_STOPWORDS = frozenset({
    "about", "after", "against", "also", "because", "been", "before", "being", "between",
    "both", "could", "does", "each", "from", "have", "into", "just", "like", "many", "more",
    "most", "much", "must", "only", "other", "over", "period", "post", "posts", "should",
    "some", "such", "than", "that", "their", "them", "then", "there", "these", "they",
    "this", "those", "through", "under", "until", "very", "what", "when", "where",
    "which", "while", "will", "with", "within", "without", "would", "year", "years", "your",
})
# 多词机构名的首词若是这些泛称，不能单独作为「点名」别名（"Chinese" ≠ 点名中国政府）。
_ALIAS_GENERIC_WORDS = frozenset({
    "academy", "agency", "american", "board", "bureau", "central", "chinese", "commission",
    "council", "department", "european", "federal", "global", "government", "institute",
    "international", "ministry", "national", "office", "people", "state", "states",
    "united", "white",
})


def _reaction_phase_enabled() -> bool:
    """SIM_REACTION_PHASE：每轮发帖后的回应阶段（默认开）。"""
    return _flag_true("SIM_REACTION_PHASE", "true")


def _reaction_share() -> float:
    """SIM_REACTION_SHARE：本轮活跃 agent 中参与回应的比例（clamp 到 [0,1]，默认 1.0）。"""
    try:
        share = float(_cfg_flag("SIM_REACTION_SHARE", "1.0"))
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(0.0, share))


def _normalize_output_language(raw: Any) -> str:
    """把配置/环境里的语言值归一成 English / Chinese（auto/空 → ""）。"""
    text = str(raw or "").strip()
    low = text.lower()
    if not low or low == "auto":
        return ""
    if low.startswith("en"):
        return "English"
    if low.startswith(("zh", "chinese", "cn")) or "中文" in text or "汉语" in text:
        return "Chinese"
    return text[:40]


def _sim_output_language(config: Dict[str, Any]) -> str:
    """本次模拟的输出语言：SIM_OUTPUT_LANGUAGE 覆盖 → config.output_language → 按预测问题
    的文字判定（一个汉字约抵三个拉丁字母）。都判不出 → ""（提示里不加语言要求）。"""
    cfg = config if isinstance(config, dict) else {}
    for raw in (_cfg_flag("SIM_OUTPUT_LANGUAGE", ""), cfg.get("output_language")):
        lang = _normalize_output_language(raw)
        if lang:
            return lang
    text = str(cfg.get("simulation_requirement") or "")
    cjk = sum(len(run) for run in _CJK_RUN_RE.findall(text))
    latin = len(_LATIN_LETTER_RE.findall(text))
    if not cjk and not latin:
        return ""
    return "Chinese" if cjk * 3 >= latin else "English"


def _reaction_topic_tokens(text: Any) -> set:
    """相关性打分用的词集合：拉丁词（≥4 字符、去停用词、小写）+ 汉字串内的二元组。"""
    s = str(text or "")
    tokens = {w.lower() for w in _TOPIC_WORD_RE.findall(s)} - _TOPIC_STOPWORDS
    for run in _CJK_RUN_RE.findall(s):
        tokens.update(run[i:i + 2] for i in range(len(run) - 1))
    return tokens


def _reaction_name_aliases(name: Any) -> List[Tuple[str, bool]]:
    """机构名 → 用于识别「点名」的别名 [(alias, case_sensitive)]。

    "US Department of Commerce / BIS" → 全名、各分段、缩写 BIS（大小写敏感，避免 "most"
    命中 MOST）；"Google Quantum AI" → 全名 + 首词 Google；泛称首词（Chinese/White…）不单列。
    """
    full = str(name or "").strip()
    if not full:
        return []
    out: List[Tuple[str, bool]] = []

    def add(alias: str, case_sensitive: bool) -> None:
        alias = alias.strip()
        if alias and (alias, case_sensitive) not in out:
            out.append((alias, case_sensitive))

    segments = [full] + [s.strip() for s in re.split(r"[/()（）,，]", full) if s.strip()]
    for seg in segments:
        if _CJK_RUN_RE.search(seg):
            if len(seg) >= 2:
                add(seg, True)
            continue
        if re.fullmatch(r"[A-Z][A-Z0-9&]{1,9}", seg):
            add(seg, True)
            continue
        if len(seg) >= 4:
            add(seg, False)
        for acronym in _ACRONYM_RE.findall(seg):
            if len(acronym) >= 3:
                add(acronym, True)
        words = seg.split()
        if len(words) > 1:
            first = words[0]
            if len(first) >= 4 and first[0].isupper() and first.lower() not in _ALIAS_GENERIC_WORDS:
                add(first, False)
    return out


def _text_mentions(text: str, aliases: List[Tuple[str, bool]]) -> bool:
    """text 是否点名了某个别名（拉丁别名按词边界匹配；汉字别名按子串匹配）。"""
    if not text:
        return False
    for alias, case_sensitive in aliases:
        if _CJK_RUN_RE.search(alias):
            if alias in text:
                return True
            continue
        pattern = r"(?<![A-Za-z0-9])" + re.escape(alias) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text, 0 if case_sensitive else re.IGNORECASE):
            return True
    return False


def _truncate_text(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: max(0, limit - 1)].rstrip() + "…"


def _build_reaction_profiles(config: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    """agent_configs → {agent_id: {name, stance, aliases, tokens}}（相关性打分的角色画像）。"""
    profiles: Dict[int, Dict[str, Any]] = {}
    for row in (config or {}).get("agent_configs", []) or []:
        if not isinstance(row, dict) or row.get("agent_id") is None:
            continue
        try:
            aid = int(row["agent_id"])
        except (TypeError, ValueError):
            continue
        name = str(row.get("entity_name") or "").strip()
        topics = row.get("interested_topics") or []
        if not isinstance(topics, list):
            topics = [topics]
        interest_text = " ".join(
            [str(t) for t in topics] + [str(row.get("gains_if") or ""), str(row.get("loses_if") or "")]
        )
        profiles[aid] = {
            "name": name,
            "stance": str(row.get("stance") or "").strip().lower(),
            "aliases": _reaction_name_aliases(name),
            "tokens": _reaction_topic_tokens(interest_text),
        }
    return profiles


def _fetch_reaction_threads(
    db_path: str, since_post_id: int, recent_after_post_id: int,
    limit: int = _REACTION_WINDOW_POSTS,
) -> Dict[int, Dict[str, Any]]:
    """取 post_id > since_post_id 的帖子（最新的 limit 条）及其全部评论。

    原帖取 content；引用帖取 quote_content（被引原文进 quoted）；纯转发（有 original_post_id
    且无 quote_content）不是可回应的新发言，跳过。recent=post_id > recent_after_post_id（本轮新帖）。
    缺表/缺列/任何 sqlite 异常 → {}（本轮不回应，degrade-safe）。
    """
    threads: Dict[int, Dict[str, Any]] = {}
    if not os.path.exists(db_path):
        return threads
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT p.post_id, u.agent_id, p.content, p.quote_content,
                       p.original_post_id, ou.agent_id
                FROM post p
                LEFT JOIN user u ON p.user_id = u.user_id
                LEFT JOIN post op ON p.original_post_id = op.post_id
                LEFT JOIN user ou ON op.user_id = ou.user_id
                WHERE p.post_id > ?
                ORDER BY p.post_id DESC
                LIMIT ?
                """,
                (int(since_post_id or 0), int(limit)),
            )
            for post_id, agent_id, content, quote_content, original_post_id, orig_agent in cur.fetchall():
                if post_id is None or agent_id is None:
                    continue
                quote_text = str(quote_content or "").strip()
                if original_post_id is not None and not quote_text:
                    continue  # 纯转发
                text = quote_text if quote_text else str(content or "").strip()
                if not text:
                    continue
                threads[int(post_id)] = {
                    "post_id": int(post_id),
                    "author_id": int(agent_id),
                    "content": text,
                    "quoted": str(content or "").strip() if quote_text else "",
                    "quoted_author_id": int(orig_agent) if (quote_text and orig_agent is not None) else None,
                    "recent": int(post_id) > int(recent_after_post_id or 0),
                    "comments": [],
                }
            if threads:
                ids = sorted(threads)
                placeholders = ",".join("?" for _ in ids)
                cur.execute(
                    f"""
                    SELECT c.comment_id, c.post_id, u.agent_id, c.content
                    FROM comment c LEFT JOIN user u ON c.user_id = u.user_id
                    WHERE c.post_id IN ({placeholders})
                    ORDER BY c.comment_id
                    """,
                    ids,
                )
                for comment_id, post_id, agent_id, content in cur.fetchall():
                    thread = threads.get(int(post_id)) if post_id is not None else None
                    if thread is None:
                        continue
                    thread["comments"].append({
                        "comment_id": int(comment_id),
                        "author_id": int(agent_id) if agent_id is not None else -1,
                        "content": str(content or "").strip(),
                    })
        finally:
            conn.close()
    except Exception:  # noqa: BLE001 — 取帖失败即本轮不回应（degrade-safe）
        return {}
    return threads


def _fetch_follow_edges(db_path: str) -> set:
    """follow 表 → {(follower_agent_id, followee_agent_id)}；缺表/异常 → 空集。"""
    edges: set = set()
    if not os.path.exists(db_path):
        return edges
    try:
        conn = sqlite3.connect(db_path)
        try:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT uf.agent_id, ut.agent_id
                FROM follow f
                JOIN user uf ON f.follower_id = uf.user_id
                JOIN user ut ON f.followee_id = ut.user_id
                """
            )
            for follower, followee in cur.fetchall():
                if follower is not None and followee is not None:
                    edges.add((int(follower), int(followee)))
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return set()
    return edges


def select_reaction_candidates(
    reactor_id: int,
    threads: Dict[int, Dict[str, Any]],
    profiles: Dict[int, Dict[str, Any]],
    follows: set,
    assigned: Dict[int, int],
    max_candidates: int = _REACTION_MAX_CANDIDATES,
    rng: Optional["random.Random"] = None,
) -> List[Dict[str, Any]]:
    """为一个回应者挑选 ≤max_candidates 条最值得它回应的帖子（纯函数，rng 只用于打破平局）。

    规则：
      * 自己的帖子只有在别人回复了且自己尚未再回应时才入选（回应对方）；
      * 自己已回应过、之后无人再接话的帖子不入选（不重复自己）；
      * 加分：点名提到自己 +3、别人回复了自己的帖子 +3、自己参与的讨论有新回复 +2、
        话题与自己利益重合（每个重合词 +0.5，上限 +2）、关注作者 +1 / 被作者关注 +0.5、
        立场不同 +0.5 / 相同 +0.25、本轮新帖 +1（上轮 +0.3）；
      * 分散：本轮已分配给其他回应者的次数 −0.75/次，已有评论 −0.2/条（封顶 10 条）。
      * SIM-5：定时事件帖（thread["is_scheduled_event"]）的发帖账号不是说话者——对任何回应者
        都不算「自己的帖子」，不给关注/立场加分；点名加分改用原因「a scheduled world event
        that concerns you」，话题与新帖加分不变。
    返回候选 dict（帖子字段 + score + reasons），按分数降序；同分新帖优先。
    """
    me = profiles.get(int(reactor_id)) or {}
    aliases = me.get("aliases") or []
    my_tokens = me.get("tokens") or set()
    my_stance = me.get("stance") or ""
    scored: List[Tuple[float, int, List[str]]] = []
    for pid in sorted(threads):
        thread = threads[pid]
        author = thread.get("author_id")
        comments = thread.get("comments") or []
        my_last = -1
        for idx, comment in enumerate(comments):
            if comment.get("author_id") == reactor_id:
                my_last = idx
        newer_from_others = [
            c for c in comments[my_last + 1:]
            if c.get("author_id") not in (reactor_id, -1, None)
        ]
        reasons: List[str] = []
        score = 0.0
        is_event = bool(thread.get("is_scheduled_event"))
        if author == reactor_id and not is_event:
            if not newer_from_others:
                continue
            score += 3.0
            reasons.append("other actors replied to your post")
        else:
            if my_last >= 0:
                if not newer_from_others:
                    continue
                score += 2.0
                reasons.append("new replies in a discussion you joined")
            # 只看别人的话：自己早先的评论里出现自己的名字不算「被点名」。
            discussion = " ".join(
                [str(thread.get("content") or ""), str(thread.get("quoted") or "")]
                + [str(c.get("content") or "") for c in comments
                   if c.get("author_id") != reactor_id]
            )
            if _text_mentions(discussion, aliases):
                score += 3.0
                reasons.append("a scheduled world event that concerns you" if is_event
                               else "it mentions you")
            overlap = my_tokens & _reaction_topic_tokens(
                str(thread.get("content") or "") + " " + str(thread.get("quoted") or "")
            )
            if overlap:
                score += min(2.0, 0.5 * len(overlap))
                reasons.append("it touches your priorities (" + ", ".join(sorted(overlap)[:4]) + ")")
            if not is_event:
                if (reactor_id, author) in follows:
                    score += 1.0
                    reasons.append("you follow the author")
                if (author, reactor_id) in follows:
                    score += 0.5
                author_stance = (profiles.get(author) or {}).get("stance") or ""
                if my_stance and author_stance:
                    score += 0.5 if author_stance != my_stance else 0.25
        score += 1.0 if thread.get("recent") else 0.3
        score -= 0.75 * float(assigned.get(pid, 0))
        score -= 0.2 * min(len(comments), 10)
        if rng is not None:
            score += rng.random() * 0.05
        scored.append((score, pid, reasons))
    scored.sort(key=lambda item: (-item[0], -item[1]))
    out: List[Dict[str, Any]] = []
    for score, pid, reasons in scored[:max(0, int(max_candidates))]:
        out.append({**threads[pid], "score": round(score, 3), "reasons": reasons})
    return out


def build_reaction_prompt(
    reactor_id: int,
    reactor_name: str,
    candidates: List[Dict[str, Any]],
    agent_names: Dict[int, str],
    platform: str,
    period_label: str = "",
    language: str = "",
) -> str:
    """回应阶段的用户提示：候选帖（含已有回复与相关原因）+ 作答要求。

    SIM-5：定时事件帖（is_scheduled_event / quoted_is_event）的作者位渲染为来源标注
    （SCHEDULED WORLD EVENT …），绝不渲染成发帖行为者「X wrote:」；作者位已说明来源，正文去掉
    feed 前缀再截断（不挤占事件正文）；无事件候选 → 逐字节不变。"""
    def who(aid: Any) -> str:
        try:
            return agent_names.get(int(aid), f"Agent_{int(aid)}")
        except (TypeError, ValueError):
            return "Unknown"

    has_event = any(c.get("is_scheduled_event") or c.get("quoted_is_event") for c in candidates)
    if has_event:
        from app.services.sim_event_provenance import event_author_label, strip_event_label
    # 发帖账号本身：事件帖在库里记在它名下，自我背书守卫会拒绝 like_post——提前说明
    own_event = any(c.get("is_scheduled_event") and c.get("author_id") == reactor_id
                    for c in candidates)

    reddit = platform == "reddit"
    lines = [
        f"# RESPONSE ROUND — {period_label}" if period_label else "# RESPONSE ROUND",
        "The other actors have made their moves for this period. Respond now as "
        f"{reactor_name}: choose the ONE post below where {reactor_name} has the most at stake "
        "or the most to add, and answer it directly.",
        "",
    ]
    for idx, cand in enumerate(candidates, start=1):
        content = cand.get("content")
        if cand.get("is_scheduled_event"):
            lines.append(f"[{idx}] post_id={cand['post_id']} — {event_author_label(content)}:")
            content = strip_event_label(content)
        else:
            own = cand.get("author_id") == reactor_id
            author = "you" if own else who(cand.get("author_id"))
            lines.append(f"[{idx}] post_id={cand['post_id']} — {author} wrote:")
        lines.append('"' + _truncate_text(content, _REACTION_POST_CHARS) + '"')
        if cand.get("quoted"):
            quoted_by = cand.get("quoted_author_id")
            quoted = cand["quoted"]
            if cand.get("quoted_is_event"):
                source = event_author_label(quoted)
                quoted = strip_event_label(quoted)
            else:
                source = who(quoted_by) if quoted_by is not None else "another post"
            lines.append(
                f'  (quoting {source}: "' + _truncate_text(quoted, _REACTION_QUOTED_CHARS) + '")'
            )
        comments = cand.get("comments") or []
        if comments:
            lines.append(f"  Replies so far ({len(comments)}):")
            for comment in comments[-_REACTION_THREAD_REPLIES:]:
                ref = f"[comment_id={comment['comment_id']}] " if reddit else ""
                lines.append(
                    f"  - {ref}{who(comment.get('author_id'))}: \""
                    + _truncate_text(comment.get("content"), _REACTION_REPLY_CHARS) + '"'
                )
        if cand.get("reasons"):
            lines.append("  Why it may concern you: " + "; ".join(cand["reasons"]))
        lines.append("")
    endorse = "like_post on a listed post"
    if reddit:
        endorse += " or like_comment on a listed reply"
    language_clause = f", written in {language}" if language else ""
    lines += [
        "How to respond:",
        "1. Reply with create_comment(post_id, content), using the post_id of the post you answer.",
        "2. Answer that post's specific claim, decision or number: agree, dispute or qualify it, "
        "or state the concrete counter-move you are making in response. If others have already "
        "replied, engage with their points instead of repeating them.",
        "3. Add something the post does not already say: a fact, figure, date, program, capability, "
        f"constraint or consequence that {reactor_name} knows from its own position. Do not restate "
        "the post and do not recycle your own announcement from this period.",
        f"4. Speak exactly as {reactor_name} would speak in public, consistent with its mandate, "
        "interests and relationship to the author: allies build on each other, competitors and "
        "rivals challenge with evidence, regulators and funders set conditions.",
        f"5. Keep it to 1-3 sentences (at most {_REACTION_MAX_WORDS} words){language_clause}.",
        f"6. In the same turn, also call {endorse} only if {reactor_name} would publicly endorse "
        "it; never like your own post.",
    ]
    if has_event:
        lines.append(
            "7. A post marked SCHEDULED was placed on the feed by the simulation's event timeline; "
            "no actor said it. Respond to the event itself, not to the account it appears under."
            + (" Event posts filed under your own account cannot be liked; reply to them instead."
               if own_event else "")
        )
    lines.append("You cannot publish a new standalone post in this step.")
    return "\n".join(lines).strip()


def _make_reaction_agent(agent, tools: List[Any]):
    """无状态回应调用的辅助 ChatAgent：同一 system prompt / 模型 / 已绑定身份的动作工具，
    独立记忆，max_iteration=1（一次模型调用，执行其返回的全部工具调用）。"""
    from camel.agents import ChatAgent

    system_message = getattr(agent, "system_message", None) or getattr(agent, "_system_message", None)
    return ChatAgent(
        system_message=system_message,
        model=agent.model_backend,
        tools=tools,
        max_iteration=1,
        step_timeout=_REACTION_STEP_TIMEOUT_S,
    )


def _scheduled_event_post_ids(db_path: str, post_ids: Any, event_contents: Any) -> set:
    """SIM-5：post_ids 中哪些是定时事件帖本身——原帖（original_post_id 为空）且正文属于
    event_contents。

    按帖子身份判断，不能只比 post_content：OASIS quote_post 把被引根帖正文复制进引用帖的
    post.content，对「某行为者引用事件」的评论/点赞也带着事件正文，回应的却是引用者的评论。
    无事件/无目标/缺表/任何 sqlite 异常 → 空集（ResponseLog 退回旧措辞，degrade-safe）。"""
    ids = set()
    for pid in post_ids or ():
        try:
            ids.add(int(pid))
        except (TypeError, ValueError):
            continue
    if not ids or not event_contents or not os.path.exists(db_path):
        return set()
    try:
        conn = sqlite3.connect(db_path)
        try:
            ordered = sorted(ids)
            placeholders = ",".join("?" for _ in ordered)
            rows = conn.execute(
                "SELECT post_id, content FROM post WHERE original_post_id IS NULL "
                f"AND post_id IN ({placeholders})",
                ordered,
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return set()
    return {int(pid) for pid, content in rows if str(content or "").strip() in event_contents}


def _comment_post_ids(db_path: str, comment_ids: Any) -> Dict[int, int]:
    """SIM-5：comment_id → 该评论所回应帖子的 post_id。

    OASIS create_comment 的 trace 只记 {content, comment_id}，不含 post_id（platform.py
    create_comment），fetch_new_actions_from_db 读出的评论行因此没有目标帖——须经 comment
    表回查。OASIS 已把对纯转发的评论改挂到根帖，comment.post_id 即回应对象。
    无目标/缺表/任何 sqlite 异常 → 空映射（ResponseLog 退回旧措辞，degrade-safe）。"""
    ids = set()
    for cid in comment_ids or ():
        try:
            ids.add(int(cid))
        except (TypeError, ValueError):
            continue
    if not ids or not os.path.exists(db_path):
        return {}
    try:
        conn = sqlite3.connect(db_path)
        try:
            ordered = sorted(ids)
            placeholders = ",".join("?" for _ in ordered)
            rows = conn.execute(
                f"SELECT comment_id, post_id FROM comment WHERE comment_id IN ({placeholders})",
                ordered,
            ).fetchall()
        finally:
            conn.close()
    except Exception:  # noqa: BLE001
        return {}
    return {int(cid): int(pid) for cid, pid in rows if pid is not None}


def _reaction_target_post_id(action: Dict[str, Any], comment_post_ids: Dict[int, int]) -> Optional[int]:
    """SIM-5：回应动作所针对的帖子 id——优先取动作参数里的 post_id（点赞帖子的 trace 带它），
    评论行没有时按 comment_post_ids（_comment_post_ids 回查结果）补齐；都没有 → None。"""
    args = action.get("action_args") or {}
    pid = args.get("post_id")
    if pid is None and action.get("action_type") == "CREATE_COMMENT":
        try:
            pid = comment_post_ids.get(int(args.get("comment_id")))
        except (TypeError, ValueError):
            pid = None
    try:
        return int(pid)
    except (TypeError, ValueError):
        return None


def _reaction_memory_note(
    agent_id: int, actions: List[Dict[str, Any]], agent_names: Dict[int, str],
    event_post_ids: Any = frozenset(), comment_post_ids: Optional[Dict[int, int]] = None,
) -> str:
    """把某 agent 本阶段的回应动作压成一条简短记忆（供后续轮次保持连续性）。

    SIM-5：回应对象是定时事件帖本身（目标帖 ∈ event_post_ids，见 _scheduled_event_post_ids）
    时不写「You replied to X's post」——事件不是发帖行为者说的话；对他人引用事件的帖子的回应
    照旧记为回应引用者。评论的目标帖经 comment_post_ids 回查（OASIS 评论 trace 不带 post_id）。
    event_post_ids 为空 → 逐字节不变。"""
    parts: List[str] = []
    for action in actions:
        if action.get("agent_id") != agent_id:
            continue
        kind = action.get("action_type")
        args = action.get("action_args") or {}
        target = args.get("post_author_name") or args.get("comment_author_name") or "another actor"
        on_event = False
        if event_post_ids and kind in ("CREATE_COMMENT", "LIKE_POST"):
            on_event = _reaction_target_post_id(action, comment_post_ids or {}) in event_post_ids
        if kind == "CREATE_COMMENT":
            text = _truncate_text(args.get("content"), _REACTION_NOTE_CHARS)
            if on_event:
                parts.append(f"You responded to the scheduled world event: \"{text}\"")
            else:
                parts.append(f"You replied to {target}'s post: \"{text}\"")
        elif kind == "LIKE_POST":
            if on_event:
                parts.append("You endorsed the scheduled world event.")
            else:
                parts.append(f"You endorsed (liked) {target}'s post.")
        elif kind == "LIKE_COMMENT":
            parts.append(f"You endorsed (liked) {target}'s reply.")
    if not parts:
        return ""
    return "# YOUR RESPONSES THIS PERIOD\n" + "\n".join(parts)


async def run_reaction_phase(
    env,
    db_path: str,
    active_agents: List[Tuple[int, Any]],
    config: Dict[str, Any],
    round_num: int,
    period_label: str,
    platform: str,
    agent_names: Dict[int, str],
    reaction_state: Dict[str, Any],
    last_rowid: int,
    action_logger,
    rng,
    log_info,
) -> Tuple[List[Dict[str, Any]], int]:
    """SIM-REACT：本轮活跃 agent 回应他人帖子。返回 (本阶段落账的动作, 新 last_rowid)。

    reaction_state 由调用方每个平台持有一份：{"window_start": 上轮起点水位, "round_start":
    本轮起点水位, "profiles": 角色画像缓存}；水位由 _advance_reaction_window 在有机 step 前推进。
    任何异常 → ([], 原 last_rowid)，绝不中断轮循环。
    """
    try:
        if not active_agents:
            return [], last_rowid
        threads = _fetch_reaction_threads(
            db_path,
            int(reaction_state.get("window_start", 0) or 0),
            int(reaction_state.get("round_start", 0) or 0),
        )
        if not threads:
            return [], last_rowid
        # SIM-5：event_contents 由调用方按 SIM_EVENT_PROVENANCE 预置（关/无事件 → 空集 → 线程
        # 不带任何新键，候选与提示逐字节不变）；帖文与日志用同一 label_event_post，精确匹配。
        event_contents = reaction_state.get("event_contents") or frozenset()
        if event_contents:
            for thread in threads.values():
                thread["is_scheduled_event"] = thread["content"].strip() in event_contents
                thread["quoted_is_event"] = thread["quoted"].strip() in event_contents
        profiles = reaction_state.get("profiles")
        if profiles is None:
            profiles = _build_reaction_profiles(config)
            reaction_state["profiles"] = profiles
        follows = _fetch_follow_edges(db_path)
        language = reaction_state.get("language")
        if language is None:
            language = _sim_output_language(config)
            reaction_state["language"] = language

        reactors = sorted(active_agents, key=lambda item: int(item[0]))
        share = _reaction_share()
        if share < 1.0:
            keep = int(round(len(reactors) * share))
            reactors = sorted(rng.sample(reactors, keep), key=lambda item: int(item[0])) if keep else []
        rng.shuffle(reactors)  # 分散惩罚按分配顺序累积——打乱顺序避免永远偏向低 id

        assigned: Dict[int, int] = {}
        plans: List[Tuple[int, Any, str]] = []
        for aid, agent in reactors:
            candidates = select_reaction_candidates(
                int(aid), threads, profiles, follows, assigned, rng=rng
            )
            if not candidates:
                continue
            assigned[candidates[0]["post_id"]] = assigned.get(candidates[0]["post_id"], 0) + 1
            name = agent_names.get(int(aid)) or (profiles.get(int(aid)) or {}).get("name") or f"Agent_{aid}"
            prompt = build_reaction_prompt(
                int(aid), name, candidates, agent_names, platform, period_label, language
            )
            plans.append((int(aid), agent, prompt))
        if not plans:
            return [], last_rowid

        semaphore = getattr(env, "llm_semaphore", None)
        if semaphore is None:
            semaphore = asyncio.Semaphore(4)
        from camel.messages import BaseMessage

        async def _respond(aid: int, agent, prompt: str) -> bool:
            internal = getattr(agent, "_internal_tools", None)
            if not isinstance(internal, dict) or getattr(agent, "model_backend", None) is None:
                return False
            tools = [internal[name] for name in _REACTION_TOOL_NAMES if name in internal]
            if not any(name in internal for name in _REACTION_REPLY_TOOLS):
                return False
            helper = _make_reaction_agent(agent, tools)
            message = BaseMessage.make_user_message(role_name="User", content=prompt)
            try:
                async with semaphore:
                    await helper.astep(message)
                return True
            except Exception as exc:  # noqa: BLE001 — 单个 agent 失败不影响其余
                log_info(f"回应阶段 agent {aid} 调用失败（已跳过）: {type(exc).__name__}: {exc}")
                return False

        results = await asyncio.gather(*(_respond(aid, agent, prompt) for aid, agent, prompt in plans))
        responded = sum(1 for ok in results if ok)

        actions, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        if action_logger:
            for action in actions:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action["agent_id"],
                    agent_name=action["agent_name"],
                    action_type=action["action_type"],
                    action_args=action["action_args"],
                )

        # 连续性：把各自的回应压成一条 USER 记忆（SYSTEM 记录会被 camel 上下文构造器丢弃）。
        try:
            from camel.types import OpenAIBackendRole
            # SIM-5：评论行没有 post_id（OASIS trace 只记 comment_id）——仅在有事件帖时回查目标帖，
            # 无事件 → 不读库、event_post_ids 为空，记忆逐字节不变。
            comment_post_ids: Dict[int, int] = {}
            if event_contents:
                comment_post_ids = _comment_post_ids(
                    db_path,
                    [(a.get("action_args") or {}).get("comment_id") for a in actions
                     if a.get("action_type") == "CREATE_COMMENT"],
                )
            event_post_ids = _scheduled_event_post_ids(
                db_path, [_reaction_target_post_id(a, comment_post_ids) for a in actions],
                event_contents,
            )
            for aid, agent, _prompt in plans:
                note = _reaction_memory_note(
                    aid, actions, agent_names, event_post_ids, comment_post_ids
                )
                if note and hasattr(agent, "update_memory"):
                    agent.update_memory(
                        BaseMessage.make_user_message(role_name="ResponseLog", content=note),
                        OpenAIBackendRole.USER,
                    )
        except Exception as exc:  # noqa: BLE001
            log_info(f"回应记忆回写失败（不影响模拟）: {exc}")

        counts: Dict[str, int] = {}
        for action in actions:
            counts[action["action_type"]] = counts.get(action["action_type"], 0) + 1
        log_info(
            f"第 {round_num + 1} 轮回应阶段: {responded}/{len(plans)} 个 agent 完成回应，动作 {counts or '{}'}"
        )
        return actions, last_rowid
    except Exception as exc:  # noqa: BLE001 — 回应阶段是附加层，失败绝不中断模拟
        log_info(f"回应阶段失败，跳过本轮（不中断模拟）: {type(exc).__name__}: {exc}")
        return [], last_rowid


def _advance_reaction_window(reaction_state: Dict[str, Any], db_path: str) -> None:
    """有机 step 前推进候选窗口：上轮起点 ← 本轮起点，本轮起点 ← 当前最大 post_id。
    候选 = post_id > 上轮起点（上轮 + 本轮的帖子；首轮含种子帖）。"""
    reaction_state["window_start"] = int(reaction_state.get("round_start", 0) or 0)
    reaction_state["round_start"] = _max_post_id(db_path)


async def run_twitter_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None,
    semaphore_platforms: int = 1,
    resume: bool = False
) -> PlatformSimulation:
    """运行Twitter模拟

    Args:
        config: 模拟配置
        simulation_dir: 模拟目录
        action_logger: 动作日志记录器
        main_logger: 主日志管理器
        max_rounds: 最大模拟轮数（可选，用于截断过长的模拟）
        resume: RUN-7 断点续跑——存在有效检查点时保留 DB、跳过种子注入并从检查点轮次继续

    Returns:
        PlatformSimulation: 包含env和agent_graph的结果对象
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Twitter] {msg}")
        print(f"[Twitter] {msg}")
    
    log_info("初始化...")

    # CAL-TEMPORAL: presence-keyed 日历模式检测——只认 config 顶层 temporal_config.mode=="calendar"
    # （spec §1：运行器不读 SIM_TEMPORAL_MODE 环境变量）。缺该块的旧配置/检查点/在途运行
    # 全部走 hours 路径，行为逐字节不变。
    temporal_config = config.get("temporal_config") or {}
    if not isinstance(temporal_config, dict):
        temporal_config = {}
    calendar = str(temporal_config.get("mode") or "").strip().lower() == "calendar"
    
    # Twitter 使用通用 LLM 配置
    model = create_model(config, use_boost=False)
    # RUN-2: OASIS 吞掉逐 agent 模型异常，模型请求层是唯一可靠的失败观测点
    llm_counter = _wrap_model_llm_counter(model)

    # OASIS Twitter使用CSV格式
    profile_path = os.path.join(simulation_dir, "twitter_profiles.csv")
    if not os.path.exists(profile_path):
        log_info(f"错误: Profile文件不存在: {profile_path}")
        return result
    
    result.agent_graph = await generate_twitter_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=TWITTER_ACTIONS,
    )

    # EXECPLAN2 I-2-3: 按角色裁剪每个 Agent 的动作可供性（默认关闭；开关 SIM_ROLE_ACTION_PROFILES）。
    # 必须在 oasis.make()/env.reset() 之前，对 generate_*_agent_graph 产出的同一批 Agent 直接生效。
    if _role_action_profiles_enabled():
        try:
            _apply_role_action_profiles(result.agent_graph, config, TWITTER_ACTIONS, log_info)
        except Exception as _rap_err:  # noqa: BLE001
            log_info(f"角色动作可供性应用失败（已隔离，回退全局动作清单）: {_rap_err}")

    # NEXTSTEPS SIM_WORLD_BRIEF: 全体 Agent 共享世界底稿（默认开）。与角色动作裁剪一样必须在
    # env.reset() 之前注入；config 无 world_brief 字段（旧配置）→ no-op。
    if _world_brief_enabled():
        try:
            _inject_world_brief(result.agent_graph, config.get("world_brief"), log_info,
                                header=_world_brief_header(config))
        except Exception as _wb_err:  # noqa: BLE001
            log_info(f"世界简报注入失败（已隔离，系统提示保持原样）: {_wb_err}")

    # CAL-TEMPORAL: 日历模式开局一次性注入动作词汇表（与世界简报同一幂等注入机制，
    # 必须在 env.reset() 之前）。hours 模式不进此分支，system prompt 逐字节不变。
    if calendar:
        try:
            _inject_calendar_vocabulary(result.agent_graph, temporal_config, log_info)
        except Exception as _cv_err:  # noqa: BLE001
            log_info(f"日历动作词汇注入失败（已隔离，系统提示保持原样）: {_cv_err}")

    # XRUN-14: 幻觉工具参数（如 like_comment(post_id=...)）降级为改名/丢参而非整个动作被吞
    try:
        _wrap_agent_tool_arg_normalizer(result.agent_graph, log_info)
    except Exception as _tan_err:  # noqa: BLE001
        log_info(f"工具参数规整启用失败（已隔离，保持原生工具行为）: {_tan_err}")
    # 自我背书守卫：点赞工具拒绝自己写的帖子/评论（发帖与回应两个步骤共用同一工具对象）
    try:
        _wrap_agent_self_like_guard(
            result.agent_graph, os.path.join(simulation_dir, "twitter_simulation.db"), log_info)
    except Exception as _slg_err:  # noqa: BLE001
        log_info(f"自我背书守卫启用失败（已隔离，保持原生工具行为）: {_slg_err}")

    # 从配置文件获取 Agent 真实名称映射（使用 entity_name 而非默认的 Agent_X）
    agent_names = get_agent_names_from_config(config)
    # 如果配置中没有某个 agent，则使用 OASIS 的默认名称
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')

    db_path = os.path.join(simulation_dir, "twitter_simulation.db")
    # RUN-7: 续跑时保留模拟 DB（世界状态所在）；检查点或 DB 缺失 → 退化为全新运行。
    resume_ckpt = _load_round_checkpoint(simulation_dir, "twitter") if resume else None
    if resume_ckpt is not None and not os.path.exists(db_path):
        log_info("检查点存在但模拟 DB 缺失，无法续跑 → 从头重跑")
        resume_ckpt = None
    # ITEM 3: 续跑前校验 config_hash——配置自上次运行以来若已变更，旧 DB/世界与新意图不一致，
    # 必须放弃续跑、从头重跑（诚实降级）。旧检查点无 config_hash 字段时不阻断（向后兼容）。
    if resume_ckpt is not None:
        _saved_hash = str(resume_ckpt.get("config_hash", "") or "")
        _cur_hash = _config_hash(config)
        if _saved_hash and _cur_hash and _saved_hash != _cur_hash:
            log_info("检查点 config_hash 与当前配置不匹配（配置已变更）→ 放弃续跑，从头重跑")
            resume_ckpt = None
    if os.path.exists(db_path) and resume_ckpt is None:
        os.remove(db_path)
    
    # T3.12: 优先用 config 的 recsys 旋钮构建自定义平台；未启用/失败则回退默认平台类型
    _custom_platform = build_oasis_platform("twitter", db_path, config, log_info)
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=_custom_platform if _custom_platform is not None else oasis.DefaultPlatformType.TWITTER,
        database_path=db_path,
        semaphore=get_oasis_semaphore(config, use_boost=False, platforms=semaphore_platforms),  # 按提供方限制并发 LLM 请求数（双平台并行时各拿一半）
    )
    
    await result.env.reset()
    log_info("环境已启动")
    
    if action_logger:
        # simulation_start 的 total_rounds 显式传入（修复旧的 hours*2 陈旧硬编码）：
        # 日历模式以 temporal_config.n_rounds 为准；hours 模式按时长公式 + max_rounds 截断。
        _tcfg_log = config.get("temporal_config") or {}
        if _tcfg_log.get("mode") == "calendar":
            _tr_log = int(_tcfg_log.get("n_rounds", 0) or 0)
        else:
            _ttc_log = config.get("time_config", {}) or {}
            _tr_log = int((_ttc_log.get("total_simulation_hours", 72) * 60)
                          // (_ttc_log.get("minutes_per_round", 60) or 60))
            if max_rounds is not None and max_rounds > 0:
                _tr_log = min(_tr_log, max_rounds)
        action_logger.log_simulation_start(config, _tr_log)
    
    total_actions = 0
    last_rowid = 0  # 跟踪数据库中最后处理的行号（使用 rowid 避免 created_at 格式差异）

    # RUN-7: 续跑——动作累计从检查点接续；trace 游标推进到 DB 末尾（崩溃时进行到一半
    # 的轮次宁可整轮丢弃也不错记到新轮次；重登录产生的失败 sign_up 不写 trace）。
    if resume_ckpt is not None:
        total_actions = int(resume_ckpt.get("total_actions", 0) or 0)
        last_rowid = max(int(resume_ckpt.get("last_rowid", 0) or 0), _max_trace_rowid(db_path))
        # ITEM 3: 恢复采样 RNG 状态，使 SIM_SEED 确定性运行跨崩溃边界仍可复现采样流。
        if _restore_rng_state(resume_ckpt.get("rng_state")):
            log_info("已从检查点恢复采样 RNG 状态（续跑采样流可复现）")

    # 执行初始事件
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    if resume_ckpt is not None:
        initial_posts = []  # RUN-7: 种子帖在原始运行的 round-0 已注入，续跑不得重复

    # RUN-4: 模拟起始小时（默认 0 与旧行为逐字节一致）。对齐 agent active_hours
    # （生成器普遍从 9 点起）可消除开局的结构性死轮。
    start_hour = _resolve_start_hour(config.get("time_config", {}) or {})

    # 记录 round 0 开始（初始事件阶段）；RUN-7: 续跑时 round 0 已在原始运行记录过
    if action_logger and resume_ckpt is None:
        action_logger.log_round_start(0, start_hour)  # round 0（RUN-4: 起始小时，默认 0）

    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                # 修复：同一 agent 的多条初始帖此前会相互覆盖（dict 单键单值），第一条被静默丢弃。
                # 与 Reddit 路径一致地把同 agent 的多条合并成 list（env.step 接受 list 值）。
                if agent in initial_actions:
                    if not isinstance(initial_actions[agent], list):
                        initial_actions[agent] = [initial_actions[agent]]
                    initial_actions[agent].append(ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    ))
                else:
                    initial_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )

                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass

        if initial_actions:
            try:
                await result.env.step(initial_actions)
                log_info(f"已发布 {len(initial_actions)} 条初始帖子")
            except Exception as init_err:
                log_info(f"初始帖子发布失败，跳过（继续进入主循环）: {init_err}")
    
    # T3.3: 注入研究/图谱驱动的初始关注边（建图 add_edge + FOLLOW 动作），让社交图不再从空起步
    # RUN-7: 续跑时关注边已在 DB 的 follow 表里（世界状态被保留），不得重复注入。
    if resume_ckpt is None:
        try:
            await inject_initial_follows(result.env, event_config, log_info, agent_names, action_logger)
        except Exception as follow_err:
            log_info(f"初始关注注入失败，跳过（继续进入主循环）: {follow_err}")

    # RUN-1: 立即消化 round-0 注入（初始帖 + 初始关注）在 trace 表里产生的积压——
    # 否则 last_rowid 停在 0，首个活跃轮的 fetch 会把整个 backlog（种子帖的第二份
    # 逐字节拷贝 + 全部种子 FOLLOW）记成该轮动作并被计为"有机"，击穿 hollow-sim
    # 健康门（sim_440: 全 LLM 失败仍报 health='ok'）。种子 FOLLOW 按 round 0 +
    # is_seed_action 记录；CREATE_POST 已手动记录过，直接丢弃避免重复。
    try:
        _seed_rows, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        for _sr in _seed_rows:
            if _sr['action_type'] == 'CREATE_POST':
                continue
            if action_logger:
                action_logger.log_action(
                    round_num=0,
                    agent_id=_sr['agent_id'],
                    agent_name=_sr['agent_name'],
                    action_type=_sr['action_type'],
                    action_args={**_sr['action_args'], 'is_seed_action': True},
                )
                total_actions += 1
                initial_action_count += 1
    except Exception as _seed_err:  # noqa: BLE001 — 消化失败退回旧行为（首轮统计重复），不中断模拟
        log_info(f"round-0 注入积压消化失败（退回旧行为）: {_seed_err}")

    # 记录 round 0 结束（RUN-7: 续跑时 round 0 不重复记账）
    if action_logger and resume_ckpt is None:
        action_logger.log_round_end(0, initial_action_count, simulated_hours=0.0)
    
    # 主模拟循环
    time_config = config.get("time_config", {})
    minutes_per_round = time_config.get("minutes_per_round", 60)
    # CAL-TEMPORAL: 总轮数唯一权威计算（_resolve_total_rounds）——日历模式取
    # temporal_config.n_rounds 且不做运行期 max_rounds 截断（cap 已在配置生成期粗化消化）；
    # hours 模式为时长公式 + max_rounds 截断（旧行为与日志逐字节不变）。
    total_rounds = _resolve_total_rounds(config, temporal_config, calendar, max_rounds, log_info)

    # CAL-TEMPORAL: 轮次(0基)→日历时段查表 + 上一时段世界演化摘要占位。
    # world_delta_text 由后续 in-band 演化切片在每轮末填充；本切片恒为 ""（首轮语义）。
    _round_periods: Dict[int, Dict[str, Any]] = {}
    if calendar:
        for _rp_i, _rp in enumerate(temporal_config.get("round_dates") or []):
            if not isinstance(_rp, dict):
                continue
            try:
                _round_periods[int(_rp.get("round", _rp_i))] = _rp
            except (TypeError, ValueError):
                _round_periods[_rp_i] = _rp
    world_delta_text = ""

    start_time = datetime.now()

    last_active_ids: set = set()  # T3.5: 近因加成——上一轮活跃的 agent 下一轮更易被激活
    # RUN-4: 默认 false = 死轮清空近因集（旧行为）；true 时跨死轮保留，级联不被时段空档打断
    _recency_carry = _flag_true("SIM_RECENCY_CARRY", "false")
    # I-2-1: 逐智能体动态情感状态（默认开；SIM_AGENT_DYNAMICS=false 关闭）
    dynamics_tracker = _build_dynamics_tracker(config, log_info)
    dyn_name_to_id = {name: aid for aid, name in agent_names.items()}

    # ITEM 20: 参与度采样状态——初始水位取当前最大 post_id，使采样只落到主循环各轮的新帖上，
    # 不去点赞 round-0 种子帖。门控与 rate 只读一次（子进程内不变），关闭则整段 no-op。
    _engagement_on = _engagement_sampler_enabled()
    _engagement_rate_val = _engagement_rate()
    _engagement_state = {"last_post_id": _max_post_id(db_path) if _engagement_on else 0}

    # SIM-REACT: 每轮发帖后的回应阶段（默认开）；候选窗口水位在每轮有机 step 前推进。
    _reaction_on = _reaction_phase_enabled()
    _reaction_state: Dict[str, Any] = {}
    # SIM-5: 全部定时事件的帖文（带来源前缀）一次性预置——回应阶段据此把事件帖渲染为世界事件
    # 而非发帖行为者的发言；按全量事件而非已触发事件计算，断点续跑安全。开关关 → 空集。
    _reaction_state["event_contents"] = _event_post_contents_for_run(event_config)
    _sim_language = _sim_output_language(config)
    if _reaction_on:
        log_info(f"回应阶段已启用（每轮发帖后回应他人帖子；输出语言={_sim_language or '未指定'}）")

    # RUN-7: 每轮结束后落轮级检查点（SIM_CHECKPOINT 默认开）；续跑则跳过已完成的轮次。
    _ckpt_platform = "reddit" if os.path.basename(db_path).startswith("reddit") else "twitter"
    _cfg_hash = _config_hash(config)  # ITEM 3: 每轮检查点写入配置指纹，供续跑前校验（只算一次）

    # CAL-TEMPORAL: in-band 世界演化器（SIM_DECISION_CHANNEL_INBAND，默认开，仅日历模式；
    # world_state_seed.scenarios 为空 → None，静默关闭）。双平台共享同一实例（按 sim 目录
    # 注册，expected=semaphore_platforms），凑齐两平台本轮水位后才按轮序步进一次。
    _inband_evo = (_get_inband_evolution(config, simulation_dir, semaphore_platforms, log_info)
                   if calendar else None)

    def _write_ckpt(completed_round: int) -> None:
        # 闭包按调用时读取 last_rowid / total_actions 的当前值；ITEM 3: 附带 config_hash 与实时 RNG 状态
        _write_round_checkpoint(simulation_dir, _ckpt_platform, completed_round,
                                last_rowid, total_rounds, total_actions,
                                config_hash=_cfg_hash, rng_state=_capture_rng_state())

    start_round = 0
    if resume_ckpt is not None:
        start_round = min(int(resume_ckpt.get("completed_round", 0) or 0), total_rounds)
        log_info(f"断点续跑：跳过已完成的 {start_round}/{total_rounds} 轮，从第 {start_round + 1} 轮继续")

    # XRUN-4: 连续同类 env.step 失败熔断（默认 3；0=关闭）——磁盘耗尽等系统性死亡
    # 曾被逐轮"跳过本轮"吞成静默僵死，LLM 额度对着死 SQLite 连烧数小时。
    step_failure_limit = _step_failure_limit()
    consec_step_failures = 0
    last_step_err_cls = None
    for round_num in range(start_round, total_rounds):
        # 检查是否收到退出信号
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"收到退出信号，在第 {round_num + 1} 轮停止模拟")
            break

        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (start_hour + simulated_minutes // 60) % 24  # RUN-4: 从起始小时推进
        simulated_day = simulated_minutes // (60 * 24) + 1

        # CAL-TEMPORAL: 本轮日历时段与 round_start/round_end 事件附加字段（hours 模式恒空 →
        # 下方所有 log_round_* 调用经 _supported_log_kwargs 过滤后与旧行为逐字节等价）
        _period = _round_periods.get(round_num) if calendar else None
        _cal_extra: Dict[str, Any] = {}
        if calendar and isinstance(_period, dict):
            _cal_extra = {
                "period_start": _period.get("period_start"),
                "period_end": _period.get("period_end"),
                "period_label": _period.get("label"),
                "calendar_unit": temporal_config.get("unit"),
            }

        # XRUN-4: 每轮磁盘预检——磁盘耗尽后 SQLite 已死，继续跑只会烧 LLM 额度；
        # 硬失败让平台异常被隔离上抛，run_state/管线健康门看见真实原因而非静默僵死。
        _disk_err = _free_disk_error(simulation_dir)
        if _disk_err:
            raise RuntimeError(f"第 {round_num + 1} 轮前磁盘预检失败: {_disk_err}")

        # T3.8: 在活跃 agent 选择前回放本轮到期的研究时间线事件（CREATE_POST），使其对本轮可见
        try:
            fired = await fire_scheduled_events(
                result.env, event_config, round_num, agent_names, action_logger, log_info
            )
            total_actions += fired
            if fired:
                # RUN-14: 定时事件已在 fire_scheduled_events 内手动记录（is_scheduled_event），
                # 立即推进 last_rowid 丢弃其 trace 行，否则本轮 fetch 会再记一次并伪装成有机动作
                _, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        except Exception as _ev_err:
            log_info(f"定时事件触发异常，跳过（不中断模拟）: {_ev_err}")

        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num, last_active_ids,
            calendar=calendar,
        )
        # T3.5/RUN-4: 供下一轮近因加成；SIM_RECENCY_CARRY=true 时死轮不清空（级联跨空档保留）
        if active_agents or not _recency_carry:
            last_active_ids = {aid for aid, _ in active_agents}

        # 无论是否有活跃agent，都记录round开始（CAL-TEMPORAL: 日历模式附带时段字段）
        if action_logger:
            action_logger.log_round_start(
                round_num + 1, simulated_hour,
                **_supported_log_kwargs(action_logger, "log_round_start", _cal_extra))

        if not active_agents:
            # 没有活跃agent时也记录round结束（actions_count=0）
            if action_logger:
                action_logger.log_round_end(
                    round_num + 1, 0,
                    simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                    **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
            if _inband_evo is not None:
                # CAL-TEMPORAL: 死轮只推演化水位（无动作交付），防止双平台按轮配对停摆
                _inband_evo.heartbeat(_ckpt_platform, round_num)
                world_delta_text = _inband_evo.latest_delta()
            _write_ckpt(round_num + 1)  # RUN-7: 死轮也推进检查点
            continue

        # I-2-1: 注入本轮动态情感状态（默认开）。以 SYSTEM 记录写入，camel 上下文构造器只保留
        # 首条系统消息、丢弃其后 SYSTEM 记录 → 该行实际送不到模型（dynamics_summary 如实记录）。
        _inject_agent_dynamics(active_agents, dynamics_tracker, log_info)

        # CAL-TEMPORAL: 日历模式注入本轮世界时钟头（时段/进度/本轮已确认事件/上一时段演化摘要）。
        # world_delta_text 由 in-band 演化在上一轮末填充；首轮/演化失败 → "" → "(first period)"。
        if calendar:
            try:
                _inject_period_context(
                    result.env, [aid for aid, _ in active_agents], round_num,
                    _period, temporal_config,
                    _scheduled_events_due(event_config, round_num),
                    world_delta_text,
                    response_step=_reaction_on,
                    language=_sim_language,
                )
            except Exception as _pc_err:  # noqa: BLE001
                log_info(f"世界时钟注入失败，跳过（不中断模拟）: {_pc_err}")

        if _reaction_on:
            _advance_reaction_window(_reaction_state, db_path)
        actions = {agent: LLMAction() for _, agent in active_agents}
        # 健壮性：单次 env.step 内的某个 agent LLM 调用失败（超时/降级/异常）不应中断整场模拟。
        # 记录并跳过本轮，让模拟继续，保住此前所有轮次的进度。
        try:
            await result.env.step(actions)
            consec_step_failures = 0  # XRUN-4: 成功轮清零连续失败计数
            last_step_err_cls = None
        except Exception as step_err:
            # XRUN-4: 同类异常连续 N 轮（如 disk full → unable to open database file）
            # 是系统性死亡而非单轮抖动——达到阈值即硬失败，停止对死环境烧额度。
            _err_cls = type(step_err).__name__
            consec_step_failures = (consec_step_failures + 1
                                    if _err_cls == last_step_err_cls else 1)
            last_step_err_cls = _err_cls
            log_info(f"第 {round_num + 1} 轮 env.step 失败，跳过本轮（不中断整场模拟）: {step_err}")
            if action_logger:
                action_logger.log_round_end(
                    round_num + 1, 0,
                    simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                    **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
            if _inband_evo is not None:
                # CAL-TEMPORAL: 失败轮同样只推演化水位（该轮已按 0 动作记账）
                _inband_evo.heartbeat(_ckpt_platform, round_num)
                world_delta_text = _inband_evo.latest_delta()
            _write_ckpt(round_num + 1)  # RUN-7: 失败轮同样推进检查点（该轮已按 0 动作记账）
            if step_failure_limit > 0 and consec_step_failures >= step_failure_limit:
                raise RuntimeError(
                    f"env.step 连续 {consec_step_failures} 轮以同类异常（{_err_cls}）失败，"
                    f"硬失败以避免继续烧额度: {step_err}"
                )
            continue

        # 从数据库获取实际执行的动作并记录
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )

        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1

        # SIM-REACT: 回应阶段——本轮活跃 agent 回应他人帖子（评论/引用/背书）。其动作并入
        # actual_actions，供下方情感动态、参与度权重与 in-band 世界演化一并消费。
        if _reaction_on:
            _reaction_actions, last_rowid = await run_reaction_phase(
                result.env, db_path, active_agents, config, round_num,
                str((_period or {}).get("label") or ""), "twitter", agent_names,
                _reaction_state, last_rowid, action_logger, _RNG, log_info,
            )
            if _reaction_actions:
                actual_actions = list(actual_actions) + list(_reaction_actions)
                if action_logger:
                    total_actions += len(_reaction_actions)
                    round_action_count += len(_reaction_actions)

        # I-2-1: 用本轮实际动作更新动态情感状态（默认开；状态行注入见上，被 camel 丢弃）
        _observe_agent_dynamics(dynamics_tracker, actual_actions, dyn_name_to_id)

        # ITEM 20 (SIM_ENGAGEMENT_SAMPLER): 有机动作落账后补一层被动点赞（本轮活跃者→本轮新帖）。
        # 关闭 → no-op；异常内部吞掉并返回 0（degrade-safe），round_action_count/total_actions 据实增量。
        if _engagement_on:
            _liked, last_rowid = await inject_engagement_likes(
                result.env, db_path, _engagement_state, active_agents, actual_actions,
                round_num, agent_names, action_logger, _RNG, _engagement_rate_val,
                last_rowid, log_info,
            )
            total_actions += _liked
            round_action_count += _liked

        # CAL-TEMPORAL in-band 世界演化（spec §4）：有机动作 + 参与度注入落账后，交付本轮
        # 动作/到期事件给共享 WorldState；产出的定性摘要喂下一轮 WORLD CLOCK 头。deliver
        # 内部全隔离——任何失败 → 告警 + 下一轮空摘要，绝不中断轮循环。
        if _inband_evo is not None:
            _inband_evo.deliver(_ckpt_platform, round_num, _period, actual_actions,
                                _scheduled_events_due(event_config, round_num))
            world_delta_text = _inband_evo.latest_delta()

        if action_logger:
            action_logger.log_round_end(
                round_num + 1, round_action_count,
                simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
        _write_ckpt(round_num + 1)  # RUN-7: 本轮已完整记账，落轮级检查点

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")

    # 注意：不关闭环境，保留给Interview使用

    # CAL-TEMPORAL: 本平台回路结束 → 通知 in-band 演化；全部平台完成时冲刷剩余轮并落
    # world_state_trajectory.json（schema v3）+ decisions.jsonl（main() 另有兜底收尾）。
    if _inband_evo is not None:
        _inband_evo.platform_done(_ckpt_platform)

    # RUN-2/RUN-9: 循环结束落 LLM 健康计数与情感动态摘要（附加遥测，供 write_run_summary
    # 健康门与报告 caveat 消费；platform 名由本函数的 db 文件名推导，两平台共用此代码块）。
    _plat = "reddit" if os.path.basename(db_path).startswith("reddit") else "twitter"
    _write_llm_health(simulation_dir, _plat, llm_counter, log_info)
    if dynamics_tracker is not None:
        # RUN-9 (QUALITY-OPT C6): dynamics_summary 若不落盘，"情感演化是否真的发生"
        # 死在模拟进程内，报告阶段无法对 hollow sim 施加"不得叙述情绪演化"的 caveat。
        try:
            from app.utils.atomic import write_json_atomic
            # SIM-5: prompt_delivery 如实记录状态行的投递结果——SYSTEM 记录被 camel 丢弃，
            # 情感状态从未进入模型提示（见 tests/test_camel_context_delivery.py）。
            write_json_atomic(
                os.path.join(simulation_dir, f"{_plat}_dynamics_summary.json"),
                {**dynamics_tracker.dynamics_summary(),
                 "prompt_delivery": _DYNAMICS_PROMPT_DELIVERY},
            )
        except Exception as _dyn_err:  # noqa: BLE001
            log_info(f"dynamics_summary 写出失败（不影响模拟）: {_dyn_err}")

    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)

    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"模拟循环完成! 耗时: {elapsed:.1f}秒, 总动作: {total_actions}")

    return result


async def run_reddit_simulation(
    config: Dict[str, Any],
    simulation_dir: str,
    action_logger: Optional[PlatformActionLogger] = None,
    main_logger: Optional[SimulationLogManager] = None,
    max_rounds: Optional[int] = None,
    semaphore_platforms: int = 1,
    resume: bool = False
) -> PlatformSimulation:
    """运行Reddit模拟

    Args:
        config: 模拟配置
        simulation_dir: 模拟目录
        action_logger: 动作日志记录器
        main_logger: 主日志管理器
        max_rounds: 最大模拟轮数（可选，用于截断过长的模拟）
        resume: RUN-7 断点续跑——存在有效检查点时保留 DB、跳过种子注入并从检查点轮次继续

    Returns:
        PlatformSimulation: 包含env和agent_graph的结果对象
    """
    result = PlatformSimulation()
    
    def log_info(msg):
        if main_logger:
            main_logger.info(f"[Reddit] {msg}")
        print(f"[Reddit] {msg}")
    
    log_info("初始化...")

    # CAL-TEMPORAL: presence-keyed 日历模式检测——只认 config 顶层 temporal_config.mode=="calendar"
    # （spec §1：运行器不读 SIM_TEMPORAL_MODE 环境变量）。缺该块的旧配置/检查点/在途运行
    # 全部走 hours 路径，行为逐字节不变。
    temporal_config = config.get("temporal_config") or {}
    if not isinstance(temporal_config, dict):
        temporal_config = {}
    calendar = str(temporal_config.get("mode") or "").strip().lower() == "calendar"
    
    # Reddit 使用加速 LLM 配置（如果有的话，否则回退到通用配置）
    model = create_model(config, use_boost=True)
    # RUN-2: OASIS 吞掉逐 agent 模型异常，模型请求层是唯一可靠的失败观测点
    llm_counter = _wrap_model_llm_counter(model)

    profile_path = os.path.join(simulation_dir, "reddit_profiles.json")
    if not os.path.exists(profile_path):
        log_info(f"错误: Profile文件不存在: {profile_path}")
        return result
    
    result.agent_graph = await generate_reddit_agent_graph(
        profile_path=profile_path,
        model=model,
        available_actions=REDDIT_ACTIONS,
    )

    # EXECPLAN2 I-2-3: 按角色裁剪每个 Agent 的动作可供性（默认关闭；开关 SIM_ROLE_ACTION_PROFILES）。
    # Reddit 平台以 REDDIT_ACTIONS 为 union，白名单与之求交，绝不授予平台不存在的动作。
    if _role_action_profiles_enabled():
        try:
            _apply_role_action_profiles(result.agent_graph, config, REDDIT_ACTIONS, log_info)
        except Exception as _rap_err:  # noqa: BLE001
            log_info(f"角色动作可供性应用失败（已隔离，回退全局动作清单）: {_rap_err}")

    # Current canonical Reddit actors have one behavioral authority: the
    # sealed actor-role prompt. Replace OASIS' demographic template *after*
    # optional role-action hints so no unsealed behavioral suffix survives.
    canonical_runtime_rows = _enforce_canonical_reddit_system_messages(
        result.agent_graph, profile_path
    )

    # NEXTSTEPS SIM_WORLD_BRIEF: 全体 Agent 共享世界底稿（默认开）。与角色动作裁剪一样必须在
    # env.reset() 之前注入；config 无 world_brief 字段（旧配置）→ no-op。
    if _world_brief_enabled():
        try:
            _inject_world_brief(result.agent_graph, config.get("world_brief"), log_info,
                                header=_world_brief_header(config))
        except Exception as _wb_err:  # noqa: BLE001
            log_info(f"世界简报注入失败（已隔离，系统提示保持原样）: {_wb_err}")

    # CAL-TEMPORAL: 日历模式开局一次性注入动作词汇表（与世界简报同一幂等注入机制，
    # 必须在 env.reset() 之前）。hours 模式不进此分支，system prompt 逐字节不变。
    if calendar:
        try:
            _inject_calendar_vocabulary(result.agent_graph, temporal_config, log_info)
        except Exception as _cv_err:  # noqa: BLE001
            log_info(f"日历动作词汇注入失败（已隔离，系统提示保持原样）: {_cv_err}")

    # Fail closed before env.reset/model execution unless every final effective
    # system-message byte is exactly the deterministic composition of the
    # sealed role plus the sealed config's optional world/calendar blocks.
    _attest_canonical_reddit_system_messages(
        result.agent_graph,
        profile_path,
        config,
        canonical_runtime_rows,
        _VALIDATED_CONFIG_MANIFEST_SHA256,
    )

    # XRUN-14: 幻觉工具参数（如 like_comment(post_id=...)）降级为改名/丢参而非整个动作被吞
    try:
        _wrap_agent_tool_arg_normalizer(result.agent_graph, log_info)
    except Exception as _tan_err:  # noqa: BLE001
        log_info(f"工具参数规整启用失败（已隔离，保持原生工具行为）: {_tan_err}")
    # 自我背书守卫：点赞工具拒绝自己写的帖子/评论（发帖与回应两个步骤共用同一工具对象）
    try:
        _wrap_agent_self_like_guard(
            result.agent_graph, os.path.join(simulation_dir, "reddit_simulation.db"), log_info)
    except Exception as _slg_err:  # noqa: BLE001
        log_info(f"自我背书守卫启用失败（已隔离，保持原生工具行为）: {_slg_err}")

    # 从配置文件获取 Agent 真实名称映射（使用 entity_name 而非默认的 Agent_X）
    agent_names = get_agent_names_from_config(config)
    # 如果配置中没有某个 agent，则使用 OASIS 的默认名称
    for agent_id, agent in result.agent_graph.get_agents():
        if agent_id not in agent_names:
            agent_names[agent_id] = getattr(agent, 'name', f'Agent_{agent_id}')

    db_path = os.path.join(simulation_dir, "reddit_simulation.db")
    # RUN-7: 续跑时保留模拟 DB（世界状态所在）；检查点或 DB 缺失 → 退化为全新运行。
    resume_ckpt = _load_round_checkpoint(simulation_dir, "reddit") if resume else None
    if resume_ckpt is not None and not os.path.exists(db_path):
        log_info("检查点存在但模拟 DB 缺失，无法续跑 → 从头重跑")
        resume_ckpt = None
    # ITEM 3: 续跑前校验 config_hash——配置自上次运行以来若已变更，旧 DB/世界与新意图不一致，
    # 必须放弃续跑、从头重跑（诚实降级）。旧检查点无 config_hash 字段时不阻断（向后兼容）。
    if resume_ckpt is not None:
        _saved_hash = str(resume_ckpt.get("config_hash", "") or "")
        _cur_hash = _config_hash(config)
        if _saved_hash and _cur_hash and _saved_hash != _cur_hash:
            log_info("检查点 config_hash 与当前配置不匹配（配置已变更）→ 放弃续跑，从头重跑")
            resume_ckpt = None
    if os.path.exists(db_path) and resume_ckpt is None:
        os.remove(db_path)
    
    # T3.12: 优先用 config 的 recsys 旋钮构建自定义平台；未启用/失败则回退默认平台类型
    _custom_platform = build_oasis_platform("reddit", db_path, config, log_info)
    result.env = oasis.make(
        agent_graph=result.agent_graph,
        platform=_custom_platform if _custom_platform is not None else oasis.DefaultPlatformType.REDDIT,
        database_path=db_path,
        semaphore=get_oasis_semaphore(config, use_boost=True, platforms=semaphore_platforms),  # 按提供方限制并发 LLM 请求数（双平台并行时各拿一半）
    )
    
    await result.env.reset()
    log_info("环境已启动")
    
    if action_logger:
        # simulation_start 的 total_rounds 显式传入（修复旧的 hours*2 陈旧硬编码）：
        # 日历模式以 temporal_config.n_rounds 为准；hours 模式按时长公式 + max_rounds 截断。
        _tcfg_log = config.get("temporal_config") or {}
        if _tcfg_log.get("mode") == "calendar":
            _tr_log = int(_tcfg_log.get("n_rounds", 0) or 0)
        else:
            _ttc_log = config.get("time_config", {}) or {}
            _tr_log = int((_ttc_log.get("total_simulation_hours", 72) * 60)
                          // (_ttc_log.get("minutes_per_round", 60) or 60))
            if max_rounds is not None and max_rounds > 0:
                _tr_log = min(_tr_log, max_rounds)
        action_logger.log_simulation_start(config, _tr_log)
    
    total_actions = 0
    last_rowid = 0  # 跟踪数据库中最后处理的行号（使用 rowid 避免 created_at 格式差异）

    # RUN-7: 续跑——动作累计从检查点接续；trace 游标推进到 DB 末尾（崩溃时进行到一半
    # 的轮次宁可整轮丢弃也不错记到新轮次；重登录产生的失败 sign_up 不写 trace）。
    if resume_ckpt is not None:
        total_actions = int(resume_ckpt.get("total_actions", 0) or 0)
        last_rowid = max(int(resume_ckpt.get("last_rowid", 0) or 0), _max_trace_rowid(db_path))
        # ITEM 3: 恢复采样 RNG 状态，使 SIM_SEED 确定性运行跨崩溃边界仍可复现采样流。
        if _restore_rng_state(resume_ckpt.get("rng_state")):
            log_info("已从检查点恢复采样 RNG 状态（续跑采样流可复现）")

    # 执行初始事件
    event_config = config.get("event_config", {})
    initial_posts = event_config.get("initial_posts", [])
    if resume_ckpt is not None:
        initial_posts = []  # RUN-7: 种子帖在原始运行的 round-0 已注入，续跑不得重复

    # RUN-4: 模拟起始小时（默认 0 与旧行为逐字节一致）。对齐 agent active_hours
    # （生成器普遍从 9 点起）可消除开局的结构性死轮。
    start_hour = _resolve_start_hour(config.get("time_config", {}) or {})

    # 记录 round 0 开始（初始事件阶段）；RUN-7: 续跑时 round 0 已在原始运行记录过
    if action_logger and resume_ckpt is None:
        action_logger.log_round_start(0, start_hour)  # round 0（RUN-4: 起始小时，默认 0）

    initial_action_count = 0
    if initial_posts:
        initial_actions = {}
        for post in initial_posts:
            agent_id = post.get("poster_agent_id", 0)
            content = post.get("content", "")
            try:
                agent = result.env.agent_graph.get_agent(agent_id)
                if agent in initial_actions:
                    if not isinstance(initial_actions[agent], list):
                        initial_actions[agent] = [initial_actions[agent]]
                    initial_actions[agent].append(ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    ))
                else:
                    initial_actions[agent] = ManualAction(
                        action_type=ActionType.CREATE_POST,
                        action_args={"content": content}
                    )
                
                if action_logger:
                    action_logger.log_action(
                        round_num=0,
                        agent_id=agent_id,
                        agent_name=agent_names.get(agent_id, f"Agent_{agent_id}"),
                        action_type="CREATE_POST",
                        action_args={"content": content}
                    )
                    total_actions += 1
                    initial_action_count += 1
            except Exception:
                pass
        
        if initial_actions:
            try:
                await result.env.step(initial_actions)
                log_info(f"已发布 {len(initial_actions)} 条初始帖子")
            except Exception as init_err:
                log_info(f"初始帖子发布失败，跳过（继续进入主循环）: {init_err}")
    
    # T3.3: 注入研究/图谱驱动的初始关注边（建图 add_edge + FOLLOW 动作），让社交图不再从空起步
    # RUN-7: 续跑时关注边已在 DB 的 follow 表里（世界状态被保留），不得重复注入。
    if resume_ckpt is None:
        try:
            await inject_initial_follows(result.env, event_config, log_info, agent_names, action_logger)
        except Exception as follow_err:
            log_info(f"初始关注注入失败，跳过（继续进入主循环）: {follow_err}")

    # RUN-1: 立即消化 round-0 注入（初始帖 + 初始关注）在 trace 表里产生的积压——
    # 否则 last_rowid 停在 0，首个活跃轮的 fetch 会把整个 backlog（种子帖的第二份
    # 逐字节拷贝 + 全部种子 FOLLOW）记成该轮动作并被计为"有机"，击穿 hollow-sim
    # 健康门（sim_440: 全 LLM 失败仍报 health='ok'）。种子 FOLLOW 按 round 0 +
    # is_seed_action 记录；CREATE_POST 已手动记录过，直接丢弃避免重复。
    try:
        _seed_rows, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        for _sr in _seed_rows:
            if _sr['action_type'] == 'CREATE_POST':
                continue
            if action_logger:
                action_logger.log_action(
                    round_num=0,
                    agent_id=_sr['agent_id'],
                    agent_name=_sr['agent_name'],
                    action_type=_sr['action_type'],
                    action_args={**_sr['action_args'], 'is_seed_action': True},
                )
                total_actions += 1
                initial_action_count += 1
    except Exception as _seed_err:  # noqa: BLE001 — 消化失败退回旧行为（首轮统计重复），不中断模拟
        log_info(f"round-0 注入积压消化失败（退回旧行为）: {_seed_err}")

    # 记录 round 0 结束（RUN-7: 续跑时 round 0 不重复记账）
    if action_logger and resume_ckpt is None:
        action_logger.log_round_end(0, initial_action_count, simulated_hours=0.0)
    
    # 主模拟循环
    time_config = config.get("time_config", {})
    minutes_per_round = time_config.get("minutes_per_round", 60)
    # CAL-TEMPORAL: 总轮数唯一权威计算（_resolve_total_rounds）——日历模式取
    # temporal_config.n_rounds 且不做运行期 max_rounds 截断（cap 已在配置生成期粗化消化）；
    # hours 模式为时长公式 + max_rounds 截断（旧行为与日志逐字节不变）。
    total_rounds = _resolve_total_rounds(config, temporal_config, calendar, max_rounds, log_info)

    # CAL-TEMPORAL: 轮次(0基)→日历时段查表 + 上一时段世界演化摘要占位。
    # world_delta_text 由后续 in-band 演化切片在每轮末填充；本切片恒为 ""（首轮语义）。
    _round_periods: Dict[int, Dict[str, Any]] = {}
    if calendar:
        for _rp_i, _rp in enumerate(temporal_config.get("round_dates") or []):
            if not isinstance(_rp, dict):
                continue
            try:
                _round_periods[int(_rp.get("round", _rp_i))] = _rp
            except (TypeError, ValueError):
                _round_periods[_rp_i] = _rp
    world_delta_text = ""

    start_time = datetime.now()

    last_active_ids: set = set()  # T3.5: 近因加成——上一轮活跃的 agent 下一轮更易被激活
    # RUN-4: 默认 false = 死轮清空近因集（旧行为）；true 时跨死轮保留，级联不被时段空档打断
    _recency_carry = _flag_true("SIM_RECENCY_CARRY", "false")
    # I-2-1: 逐智能体动态情感状态（默认开；SIM_AGENT_DYNAMICS=false 关闭）
    dynamics_tracker = _build_dynamics_tracker(config, log_info)
    dyn_name_to_id = {name: aid for aid, name in agent_names.items()}

    # ITEM 20: 参与度采样状态——初始水位取当前最大 post_id，使采样只落到主循环各轮的新帖上，
    # 不去点赞 round-0 种子帖。门控与 rate 只读一次（子进程内不变），关闭则整段 no-op。
    _engagement_on = _engagement_sampler_enabled()
    _engagement_rate_val = _engagement_rate()
    _engagement_state = {"last_post_id": _max_post_id(db_path) if _engagement_on else 0}

    # SIM-REACT: 每轮发帖后的回应阶段（默认开）；候选窗口水位在每轮有机 step 前推进。
    _reaction_on = _reaction_phase_enabled()
    _reaction_state: Dict[str, Any] = {}
    # SIM-5: 全部定时事件的帖文（带来源前缀）一次性预置——回应阶段据此把事件帖渲染为世界事件
    # 而非发帖行为者的发言；按全量事件而非已触发事件计算，断点续跑安全。开关关 → 空集。
    _reaction_state["event_contents"] = _event_post_contents_for_run(event_config)
    _sim_language = _sim_output_language(config)
    if _reaction_on:
        log_info(f"回应阶段已启用（每轮发帖后回应他人帖子；输出语言={_sim_language or '未指定'}）")

    # RUN-7: 每轮结束后落轮级检查点（SIM_CHECKPOINT 默认开）；续跑则跳过已完成的轮次。
    _ckpt_platform = "reddit" if os.path.basename(db_path).startswith("reddit") else "twitter"
    _cfg_hash = _config_hash(config)  # ITEM 3: 每轮检查点写入配置指纹，供续跑前校验（只算一次）

    # CAL-TEMPORAL: in-band 世界演化器（SIM_DECISION_CHANNEL_INBAND，默认开，仅日历模式；
    # world_state_seed.scenarios 为空 → None，静默关闭）。双平台共享同一实例（按 sim 目录
    # 注册，expected=semaphore_platforms），凑齐两平台本轮水位后才按轮序步进一次。
    _inband_evo = (_get_inband_evolution(config, simulation_dir, semaphore_platforms, log_info)
                   if calendar else None)

    def _write_ckpt(completed_round: int) -> None:
        # 闭包按调用时读取 last_rowid / total_actions 的当前值；ITEM 3: 附带 config_hash 与实时 RNG 状态
        _write_round_checkpoint(simulation_dir, _ckpt_platform, completed_round,
                                last_rowid, total_rounds, total_actions,
                                config_hash=_cfg_hash, rng_state=_capture_rng_state())

    start_round = 0
    if resume_ckpt is not None:
        start_round = min(int(resume_ckpt.get("completed_round", 0) or 0), total_rounds)
        log_info(f"断点续跑：跳过已完成的 {start_round}/{total_rounds} 轮，从第 {start_round + 1} 轮继续")

    # XRUN-4: 连续同类 env.step 失败熔断（默认 3；0=关闭）——磁盘耗尽等系统性死亡
    # 曾被逐轮"跳过本轮"吞成静默僵死，LLM 额度对着死 SQLite 连烧数小时。
    step_failure_limit = _step_failure_limit()
    consec_step_failures = 0
    last_step_err_cls = None
    for round_num in range(start_round, total_rounds):
        # 检查是否收到退出信号
        if _shutdown_event and _shutdown_event.is_set():
            if main_logger:
                main_logger.info(f"收到退出信号，在第 {round_num + 1} 轮停止模拟")
            break
        
        simulated_minutes = round_num * minutes_per_round
        simulated_hour = (start_hour + simulated_minutes // 60) % 24  # RUN-4: 从起始小时推进
        simulated_day = simulated_minutes // (60 * 24) + 1

        # CAL-TEMPORAL: 本轮日历时段与 round_start/round_end 事件附加字段（hours 模式恒空 →
        # 下方所有 log_round_* 调用经 _supported_log_kwargs 过滤后与旧行为逐字节等价）
        _period = _round_periods.get(round_num) if calendar else None
        _cal_extra: Dict[str, Any] = {}
        if calendar and isinstance(_period, dict):
            _cal_extra = {
                "period_start": _period.get("period_start"),
                "period_end": _period.get("period_end"),
                "period_label": _period.get("label"),
                "calendar_unit": temporal_config.get("unit"),
            }

        # XRUN-4: 每轮磁盘预检——磁盘耗尽后 SQLite 已死，继续跑只会烧 LLM 额度；
        # 硬失败让平台异常被隔离上抛，run_state/管线健康门看见真实原因而非静默僵死。
        _disk_err = _free_disk_error(simulation_dir)
        if _disk_err:
            raise RuntimeError(f"第 {round_num + 1} 轮前磁盘预检失败: {_disk_err}")

        # T3.8: 在活跃 agent 选择前回放本轮到期的研究时间线事件（CREATE_POST），使其对本轮可见
        try:
            fired = await fire_scheduled_events(
                result.env, event_config, round_num, agent_names, action_logger, log_info
            )
            total_actions += fired
            if fired:
                # RUN-14: 定时事件已在 fire_scheduled_events 内手动记录（is_scheduled_event），
                # 立即推进 last_rowid 丢弃其 trace 行，否则本轮 fetch 会再记一次并伪装成有机动作
                _, last_rowid = fetch_new_actions_from_db(db_path, last_rowid, agent_names)
        except Exception as _ev_err:
            log_info(f"定时事件触发异常，跳过（不中断模拟）: {_ev_err}")

        active_agents = get_active_agents_for_round(
            result.env, config, simulated_hour, round_num, last_active_ids,
            calendar=calendar,
        )
        # T3.5/RUN-4: 供下一轮近因加成；SIM_RECENCY_CARRY=true 时死轮不清空（级联跨空档保留）
        if active_agents or not _recency_carry:
            last_active_ids = {aid for aid, _ in active_agents}
        
        # 无论是否有活跃agent，都记录round开始（CAL-TEMPORAL: 日历模式附带时段字段）
        if action_logger:
            action_logger.log_round_start(
                round_num + 1, simulated_hour,
                **_supported_log_kwargs(action_logger, "log_round_start", _cal_extra))
        
        if not active_agents:
            # 没有活跃agent时也记录round结束（actions_count=0）
            if action_logger:
                action_logger.log_round_end(
                    round_num + 1, 0,
                    simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                    **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
            if _inband_evo is not None:
                # CAL-TEMPORAL: 死轮只推演化水位（无动作交付），防止双平台按轮配对停摆
                _inband_evo.heartbeat(_ckpt_platform, round_num)
                world_delta_text = _inband_evo.latest_delta()
            _write_ckpt(round_num + 1)  # RUN-7: 死轮也推进检查点
            continue

        # I-2-1: 注入本轮动态情感状态（默认开）。以 SYSTEM 记录写入，camel 上下文构造器只保留
        # 首条系统消息、丢弃其后 SYSTEM 记录 → 该行实际送不到模型（dynamics_summary 如实记录）。
        _inject_agent_dynamics(active_agents, dynamics_tracker, log_info)

        # CAL-TEMPORAL: 日历模式注入本轮世界时钟头（时段/进度/本轮已确认事件/上一时段演化摘要）。
        # world_delta_text 由 in-band 演化在上一轮末填充；首轮/演化失败 → "" → "(first period)"。
        if calendar:
            try:
                _inject_period_context(
                    result.env, [aid for aid, _ in active_agents], round_num,
                    _period, temporal_config,
                    _scheduled_events_due(event_config, round_num),
                    world_delta_text,
                    response_step=_reaction_on,
                    language=_sim_language,
                )
            except Exception as _pc_err:  # noqa: BLE001
                log_info(f"世界时钟注入失败，跳过（不中断模拟）: {_pc_err}")

        if _reaction_on:
            _advance_reaction_window(_reaction_state, db_path)
        actions = {agent: LLMAction() for _, agent in active_agents}
        # 健壮性：单次 env.step 内的某个 agent LLM 调用失败（超时/降级/异常）不应中断整场模拟。
        # 记录并跳过本轮，让模拟继续，保住此前所有轮次的进度。
        try:
            await result.env.step(actions)
            consec_step_failures = 0  # XRUN-4: 成功轮清零连续失败计数
            last_step_err_cls = None
        except Exception as step_err:
            # XRUN-4: 同类异常连续 N 轮（如 disk full → unable to open database file）
            # 是系统性死亡而非单轮抖动——达到阈值即硬失败，停止对死环境烧额度。
            _err_cls = type(step_err).__name__
            consec_step_failures = (consec_step_failures + 1
                                    if _err_cls == last_step_err_cls else 1)
            last_step_err_cls = _err_cls
            log_info(f"第 {round_num + 1} 轮 env.step 失败，跳过本轮（不中断整场模拟）: {step_err}")
            if action_logger:
                action_logger.log_round_end(
                    round_num + 1, 0,
                    simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                    **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
            if _inband_evo is not None:
                # CAL-TEMPORAL: 失败轮同样只推演化水位（该轮已按 0 动作记账）
                _inband_evo.heartbeat(_ckpt_platform, round_num)
                world_delta_text = _inband_evo.latest_delta()
            _write_ckpt(round_num + 1)  # RUN-7: 失败轮同样推进检查点（该轮已按 0 动作记账）
            if step_failure_limit > 0 and consec_step_failures >= step_failure_limit:
                raise RuntimeError(
                    f"env.step 连续 {consec_step_failures} 轮以同类异常（{_err_cls}）失败，"
                    f"硬失败以避免继续烧额度: {step_err}"
                )
            continue

        # 从数据库获取实际执行的动作并记录
        actual_actions, last_rowid = fetch_new_actions_from_db(
            db_path, last_rowid, agent_names
        )
        
        round_action_count = 0
        for action_data in actual_actions:
            if action_logger:
                action_logger.log_action(
                    round_num=round_num + 1,
                    agent_id=action_data['agent_id'],
                    agent_name=action_data['agent_name'],
                    action_type=action_data['action_type'],
                    action_args=action_data['action_args']
                )
                total_actions += 1
                round_action_count += 1
        
        # SIM-REACT: 回应阶段——本轮活跃 agent 回应他人帖子（评论/引用/背书）。其动作并入
        # actual_actions，供下方情感动态、参与度权重与 in-band 世界演化一并消费。
        if _reaction_on:
            _reaction_actions, last_rowid = await run_reaction_phase(
                result.env, db_path, active_agents, config, round_num,
                str((_period or {}).get("label") or ""), "reddit", agent_names,
                _reaction_state, last_rowid, action_logger, _RNG, log_info,
            )
            if _reaction_actions:
                actual_actions = list(actual_actions) + list(_reaction_actions)
                if action_logger:
                    total_actions += len(_reaction_actions)
                    round_action_count += len(_reaction_actions)

        # I-2-1: 用本轮实际动作更新动态情感状态（默认开；状态行注入见上，被 camel 丢弃）
        _observe_agent_dynamics(dynamics_tracker, actual_actions, dyn_name_to_id)

        # ITEM 20 (SIM_ENGAGEMENT_SAMPLER): 有机动作落账后补一层被动点赞（本轮活跃者→本轮新帖）。
        # 关闭 → no-op；异常内部吞掉并返回 0（degrade-safe），round_action_count/total_actions 据实增量。
        if _engagement_on:
            _liked, last_rowid = await inject_engagement_likes(
                result.env, db_path, _engagement_state, active_agents, actual_actions,
                round_num, agent_names, action_logger, _RNG, _engagement_rate_val,
                last_rowid, log_info,
            )
            total_actions += _liked
            round_action_count += _liked

        # CAL-TEMPORAL in-band 世界演化（spec §4）：有机动作 + 参与度注入落账后，交付本轮
        # 动作/到期事件给共享 WorldState；产出的定性摘要喂下一轮 WORLD CLOCK 头。deliver
        # 内部全隔离——任何失败 → 告警 + 下一轮空摘要，绝不中断轮循环。
        if _inband_evo is not None:
            _inband_evo.deliver(_ckpt_platform, round_num, _period, actual_actions,
                                _scheduled_events_due(event_config, round_num))
            world_delta_text = _inband_evo.latest_delta()

        if action_logger:
            action_logger.log_round_end(
                round_num + 1, round_action_count,
                simulated_hours=round((round_num + 1) * minutes_per_round / 60, 2),
                **_supported_log_kwargs(action_logger, "log_round_end", _cal_extra))
        _write_ckpt(round_num + 1)  # RUN-7: 本轮已完整记账，落轮级检查点

        if (round_num + 1) % 20 == 0:
            progress = (round_num + 1) / total_rounds * 100
            log_info(f"Day {simulated_day}, {simulated_hour:02d}:00 - Round {round_num + 1}/{total_rounds} ({progress:.1f}%)")

    # 注意：不关闭环境，保留给Interview使用

    # CAL-TEMPORAL: 本平台回路结束 → 通知 in-band 演化；全部平台完成时冲刷剩余轮并落
    # world_state_trajectory.json（schema v3）+ decisions.jsonl（main() 另有兜底收尾）。
    if _inband_evo is not None:
        _inband_evo.platform_done(_ckpt_platform)

    # RUN-2/RUN-9: 循环结束落 LLM 健康计数与情感动态摘要（附加遥测，供 write_run_summary
    # 健康门与报告 caveat 消费；platform 名由本函数的 db 文件名推导，两平台共用此代码块）。
    _plat = "reddit" if os.path.basename(db_path).startswith("reddit") else "twitter"
    _write_llm_health(simulation_dir, _plat, llm_counter, log_info)
    if dynamics_tracker is not None:
        # RUN-9 (QUALITY-OPT C6): dynamics_summary 若不落盘，"情感演化是否真的发生"
        # 死在模拟进程内，报告阶段无法对 hollow sim 施加"不得叙述情绪演化"的 caveat。
        try:
            from app.utils.atomic import write_json_atomic
            # SIM-5: prompt_delivery 如实记录状态行的投递结果——SYSTEM 记录被 camel 丢弃，
            # 情感状态从未进入模型提示（见 tests/test_camel_context_delivery.py）。
            write_json_atomic(
                os.path.join(simulation_dir, f"{_plat}_dynamics_summary.json"),
                {**dynamics_tracker.dynamics_summary(),
                 "prompt_delivery": _DYNAMICS_PROMPT_DELIVERY},
            )
        except Exception as _dyn_err:  # noqa: BLE001
            log_info(f"dynamics_summary 写出失败（不影响模拟）: {_dyn_err}")

    if action_logger:
        action_logger.log_simulation_end(total_rounds, total_actions)
    
    result.total_actions = total_actions
    elapsed = (datetime.now() - start_time).total_seconds()
    log_info(f"模拟循环完成! 耗时: {elapsed:.1f}秒, 总动作: {total_actions}")
    
    return result


async def main():
    parser = argparse.ArgumentParser(description='OASIS双平台并行模拟')
    parser.add_argument(
        '--config', 
        type=str, 
        required=True,
        help='配置文件路径 (simulation_config.json)'
    )
    parser.add_argument(
        '--config-seal',
        type=str,
        default=None,
        help='prepare/runner 已验证的 simulation_config_manifest.json SHA-256',
    )
    parser.add_argument(
        '--twitter-only',
        action='store_true',
        help='只运行Twitter模拟'
    )
    parser.add_argument(
        '--reddit-only',
        action='store_true',
        help='只运行Reddit模拟'
    )
    parser.add_argument(
        '--max-rounds',
        type=int,
        default=None,
        # RUN-3: 默认 None=不截断（T3.7 契约"max_rounds=None → 跑满配置时长"）。
        # 此前默认 40 会让未显式传参的调用被静默截断，而 run_state.total_rounds
        # 仍按不限制计算 → 进度永远卡在中途。0/负数同样视为不限制。
        help='最大模拟轮数（默认不限制=跑满配置时长；传 0/负数亦视为不限制）'
    )
    parser.add_argument(
        '--no-wait',
        action='store_true',
        default=False,
        help='模拟完成后立即关闭环境，不进入等待命令模式'
    )
    parser.add_argument(
        '--resume',
        action='store_true',
        default=False,
        # RUN-7: 由 SimulationRunner 在发现有效轮级检查点时传入；保留模拟 DB、
        # 跳过种子注入并从 checkpoint.completed_round 之后继续（无检查点则退化为全新运行）。
        help='断点续跑：从上次轮级检查点继续（需 SIM_RESUME=true 生成的 checkpoint.json）'
    )

    args = parser.parse_args()
    
    # 在 main 函数开始时创建 shutdown 事件，确保整个程序都能响应退出信号
    global _shutdown_event, _VALIDATED_CONFIG_MANIFEST_SHA256
    _shutdown_event = asyncio.Event()
    
    if not os.path.exists(args.config):
        print(f"错误: 配置文件不存在: {args.config}")
        sys.exit(1)
    
    simulation_dir = os.path.dirname(args.config) or "."
    # DEFECT-3: 尽早钉定遥测落盘目标——__main__ 的 finally 在任何退出路径（正常/异常/
    # sys.exit/信号触发的优雅退出）都会据此写终版 sim_llm_telemetry.json。
    _SIM_LLM_TELEMETRY_SINK["dir"] = simulation_dir
    validated_config_manifest = validate_direct_child_config_seal(
        args.config, args.config_seal
    )
    _VALIDATED_CONFIG_MANIFEST_SHA256 = str(
        validated_config_manifest.get("manifest_sha256") or ""
    )
    config = load_config(
        args.config,
        str(validated_config_manifest.get("simulation_config_sha256") or "") or None,
    )
    _SIM_LLM_TELEMETRY_SINK["config"] = config  # DEFECT-3: 落盘时解析 provider/model
    wait_for_commands = not args.no_wait
    
    # 初始化日志配置（禁用 OASIS 日志，清理旧文件）
    init_logging_for_simulation(simulation_dir)
    
    # 创建日志管理器
    log_manager = SimulationLogManager(simulation_dir)
    twitter_logger = log_manager.get_twitter_logger()
    reddit_logger = log_manager.get_reddit_logger()
    
    log_manager.info("=" * 60)
    log_manager.info("OASIS 双平台并行模拟")
    log_manager.info(f"配置文件: {args.config}")
    log_manager.info(f"模拟ID: {config.get('simulation_id', 'unknown')}")
    log_manager.info(f"等待命令模式: {'启用' if wait_for_commands else '禁用'}")
    if args.resume:
        log_manager.info("断点续跑模式: 启用（存在有效检查点的平台将跳过已完成轮次）")
    log_manager.info("=" * 60)

    # XRUN-4: 启动前磁盘预检——磁盘耗尽时 SQLite/动作日志全都会写失败，与其静默僵死
    # 数小时不如立刻以明确原因退出（exit 1 → runner 标记 FAILED 并带出日志尾部）。
    _disk_err = _free_disk_error(simulation_dir)
    if _disk_err:
        log_manager.error(f"磁盘预检失败，拒绝启动模拟: {_disk_err}")
        sys.exit(1)
    
    time_config = config.get("time_config", {})
    total_hours = time_config.get('total_simulation_hours', 72)
    minutes_per_round = time_config.get('minutes_per_round', 60)
    config_total_rounds = (total_hours * 60) // minutes_per_round
    
    log_manager.info(f"模拟参数:")
    log_manager.info(f"  - 总模拟时长: {total_hours}小时")
    log_manager.info(f"  - 每轮时间: {minutes_per_round}分钟")
    log_manager.info(f"  - 配置总轮数: {config_total_rounds}")
    if args.max_rounds:
        log_manager.info(f"  - 最大轮数限制: {args.max_rounds}")
        if args.max_rounds < config_total_rounds:
            log_manager.info(f"  - 实际执行轮数: {args.max_rounds} (已截断)")
    log_manager.info(f"  - Agent数量: {len(config.get('agent_configs', []))}")

    # 加固：OASIS 按 profile 数组下标分配 agent_id，全链路（poster_agent_id / initial_follows /
    # agent_configs 查找）都假设 agent_configs[i].agent_id == i。此前无任何运行时校验——生成器
    # 一旦错位会表现为"语义错误但不崩溃"的模拟。这里在启动时做一次软校验，错位则显著告警（不中断）。
    _acfgs = config.get("agent_configs", []) or []
    _misaligned = [
        i for i, _c in enumerate(_acfgs)
        if isinstance(_c, dict) and str(_c.get("agent_id", i)) != str(i)
    ]
    if _misaligned:
        log_manager.warning(
            f"  - ⚠ agent_configs 下标与 agent_id 错位 {len(_misaligned)} 处"
            f"（首例 index={_misaligned[0]} agent_id={_acfgs[_misaligned[0]].get('agent_id')}）；"
            f"poster/follows/查找可能指向错误 persona——疑似生成器 bug，请检查。"
        )

    log_manager.info("日志结构:")
    log_manager.info(f"  - 主日志: simulation.log")
    log_manager.info(f"  - Twitter动作: twitter/actions.jsonl")
    log_manager.info(f"  - Reddit动作: reddit/actions.jsonl")
    log_manager.info("=" * 60)
    
    start_time = datetime.now()
    
    # 存储两个平台的模拟结果
    twitter_result: Optional[PlatformSimulation] = None
    reddit_result: Optional[PlatformSimulation] = None
    
    if args.twitter_only:
        twitter_result = await run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds,
                                                      resume=args.resume)
    elif args.reddit_only:
        reddit_result = await run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds,
                                                    resume=args.resume)
    else:
        # 并行运行（每个平台使用独立的日志记录器）
        # return_exceptions=True：一个平台抛异常不会取消另一个平台、也不会让 main() 崩溃；
        # 异常作为结果返回，下面单独降级为 None 并记录，保证平台之间相互隔离。
        results = await asyncio.gather(
            run_twitter_simulation(config, simulation_dir, twitter_logger, log_manager, args.max_rounds,
                                   semaphore_platforms=2, resume=args.resume),
            run_reddit_simulation(config, simulation_dir, reddit_logger, log_manager, args.max_rounds,
                                  semaphore_platforms=2, resume=args.resume),
            return_exceptions=True,
        )
        twitter_result, reddit_result = results
        if isinstance(twitter_result, BaseException):
            log_manager.error(f"Twitter 平台模拟异常（已隔离，不影响 Reddit）: {twitter_result}")
            twitter_result = None
        if isinstance(reddit_result, BaseException):
            log_manager.error(f"Reddit 平台模拟异常（已隔离，不影响 Twitter）: {reddit_result}")
            reddit_result = None
    
    total_elapsed = (datetime.now() - start_time).total_seconds()
    log_manager.info("=" * 60)
    log_manager.info(f"模拟循环完成! 总耗时: {total_elapsed:.1f}秒")

    # DEFECT-3: 模拟回路刚结束就落一版 token 快照——命令等待模式可能驻留很久甚至被
    # SIGKILL，先把回路花费钉在盘上；进程退出路径（__main__ 的 finally）会再写终版
    # （原子覆盖，含随后的决策通道/采访花费）。
    _write_sim_llm_telemetry(simulation_dir, config, log_manager.info)

    # EXECPLAN2 I-2-0: 模拟结束后（只读）计算涌现结构 / 观点动力学度量。
    # 默认关闭（SIM_EMERGENT_METRICS!=true 时完全跳过，run 产物逐字节不变）；
    # 全程 try/except 隔离，失败不影响已完成的模拟与后续 interview/关闭流程。
    if os.environ.get("SIM_EMERGENT_METRICS", "false").strip().lower() == "true":
        emergent_platforms: List[str] = []
        if twitter_result is not None and twitter_result.env is not None:
            emergent_platforms.append("twitter")
        if reddit_result is not None and reddit_result.env is not None:
            emergent_platforms.append("reddit")
        if emergent_platforms:
            try:
                write_emergent_metrics(
                    simulation_dir, config, emergent_platforms, log_manager.info
                )
                log_manager.info("已生成涌现度量: emergent_metrics.json")
            except Exception as _em_err:  # noqa: BLE001
                log_manager.error(f"涌现度量计算失败（已隔离，不影响模拟结果）: {_em_err}")

    # CAL-TEMPORAL: in-band 世界演化收尾兜底——平台回路异常中断导致 platform_done 未走到时，
    # 强制冲刷滞留轮并落 world_state_trajectory.json（schema v3）。返回值 = 本次运行 in-band
    # 是否已写出轨迹（True 时下方 post-hoc 决策通道跳过，避免覆盖轮内演化结果；spec §4）。
    _inband_traj_written = _finalize_inband_world_evolution(simulation_dir, log_manager.info)

    # NEXTSTEPS P1-1/P1-2/P1-4: 模拟结束后演化"结果世界态"——按轮 elicit 各活跃 agent 的承诺
    # （朝哪个 forecast 情景），资源加权步进 WorldState，落 world_state_trajectory.json +
    # decisions.jsonl + 终局 outcome（report/集成读它而非声量份额 final_stance_share）。
    # 默认关（SIM_DECISION_CHANNEL!=true 完全跳过，与现状一致）；全程 try/except 隔离。
    # CAL-TEMPORAL: 保留为 hours 模式主路径 + 日历模式 in-band 未产出轨迹时的回退
    # （回退时传 round_dates → 输出同为带日期的 schema v3）。
    _ws_seed = config.get("world_state_seed") if isinstance(config, dict) else None
    if (os.environ.get("SIM_DECISION_CHANNEL", "false").strip().lower() == "true"
            and isinstance(_ws_seed, dict) and _ws_seed.get("scenarios")
            and not _inband_traj_written):
        try:
            from app.services.decision_channel import run_decision_channel
            from app.utils.llm_client import LLMClient
            from app.utils.atomic import write_json_atomic
            _acts = _read_actions_for_decision_channel(simulation_dir)
            try:
                _inertia = float(os.environ.get("SIM_DECISION_INERTIA", "0.7") or "0.7")
            except ValueError:
                _inertia = 0.7
            try:
                _eps = float(os.environ.get("SIM_CONVERGENCE_EPS", "0.02") or "0.02")
            except ValueError:
                _eps = 0.02
            _tc_posthoc = config.get("temporal_config") if isinstance(config, dict) else None
            _tc_posthoc = _tc_posthoc if isinstance(_tc_posthoc, dict) else {}
            _res = run_decision_channel(
                # DEFECT-3: 决策通道批调用同样进 sim token 计量（不经 camel 边界）。
                _acts, config.get("agent_configs"), _ws_seed,
                _wrap_llm_client_usage(LLMClient()),
                inertia=_inertia, conv_eps=_eps,
                round_to_date=_build_round_to_date(_ws_seed, config),
                # 日历模式回退：精确 round→时段映射（hours 模式无 temporal_config → None，
                # 旧路径逐字节不变）
                round_dates=(_tc_posthoc.get("round_dates")
                             if str(_tc_posthoc.get("mode") or "").lower() == "calendar"
                             else None),
            )
            if _res:
                write_json_atomic(
                    os.path.join(simulation_dir, "world_state_trajectory.json"), _res)
                with open(os.path.join(simulation_dir, "decisions.jsonl"), "w",
                          encoding="utf-8") as _df:
                    for _d in _res.get("decisions", []):
                        _df.write(json.dumps(_d, ensure_ascii=False) + "\n")
                _oc = _res.get("outcome", {})
                log_manager.info(
                    f"决策通道·结果世界态: leader={_oc.get('leader')} "
                    f"share={_oc.get('leader_share')} converged_at={_res.get('converged_at')}")
        except Exception as _dc_err:  # noqa: BLE001
            log_manager.error(f"决策通道演化失败（已隔离，不影响模拟结果）: {_dc_err}")

    # 是否进入等待命令模式
    if wait_for_commands:
        log_manager.info("")
        log_manager.info("=" * 60)
        log_manager.info("进入等待命令模式 - 环境保持运行")
        log_manager.info("支持的命令: interview, batch_interview, close_env")
        log_manager.info("=" * 60)
        
        # 创建IPC处理器
        ipc_handler = ParallelIPCHandler(
            simulation_dir=simulation_dir,
            twitter_env=twitter_result.env if twitter_result else None,
            twitter_agent_graph=twitter_result.agent_graph if twitter_result else None,
            reddit_env=reddit_result.env if reddit_result else None,
            reddit_agent_graph=reddit_result.agent_graph if reddit_result else None
        )
        ipc_handler.update_status("alive")

        # XRUN-14: 空闲超时自动关环境——语料里出现过 loop 完成后 15+ 小时无命令仍占着
        # DB/进程等 close_env（孤儿回收只在 backend 重启时跑）。任何 IPC 命令都会重置
        # 计时（采访期间不会误关）；SIM_IDLE_CLOSE_MIN<=0 恢复无限等待旧行为。
        try:
            _idle_close_min = float(_cfg_flag("SIM_IDLE_CLOSE_MIN", "60"))
        except (TypeError, ValueError):
            _idle_close_min = 60.0

        # 等待命令循环（使用全局 _shutdown_event）
        try:
            while not _shutdown_event.is_set():
                should_continue = await ipc_handler.process_commands()
                if not should_continue:
                    break
                if (_idle_close_min > 0
                        and time.monotonic() - ipc_handler.last_command_at > _idle_close_min * 60):
                    log_manager.info(
                        f"等待命令空闲超过 {_idle_close_min:.0f} 分钟，自动关闭环境"
                        "（SIM_IDLE_CLOSE_MIN，<=0 恢复无限等待）"
                    )
                    break
                # 使用 wait_for 替代 sleep，这样可以响应 shutdown_event
                try:
                    await asyncio.wait_for(_shutdown_event.wait(), timeout=0.5)
                    break  # 收到退出信号
                except asyncio.TimeoutError:
                    pass  # 超时继续循环
        except KeyboardInterrupt:
            print("\n收到中断信号")
        except asyncio.CancelledError:
            print("\n任务被取消")
        except Exception as e:
            print(f"\n命令处理出错: {e}")
        
        log_manager.info("\n关闭环境...")
        ipc_handler.update_status("stopped")
    
    # 关闭环境
    if twitter_result and twitter_result.env:
        await twitter_result.env.close()
        log_manager.info("[Twitter] 环境已关闭")
    
    if reddit_result and reddit_result.env:
        await reddit_result.env.close()
        log_manager.info("[Reddit] 环境已关闭")
    
    log_manager.info("=" * 60)
    log_manager.info(f"全部完成!")
    log_manager.info(f"日志文件:")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'simulation.log')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'twitter', 'actions.jsonl')}")
    log_manager.info(f"  - {os.path.join(simulation_dir, 'reddit', 'actions.jsonl')}")
    log_manager.info("=" * 60)


def setup_signal_handlers(loop=None):
    """
    设置信号处理器，确保收到 SIGTERM/SIGINT 时能够正确退出
    
    持久化模拟场景：模拟完成后不退出，等待 interview 命令
    当收到终止信号时，需要：
    1. 通知 asyncio 循环退出等待
    2. 让程序有机会正常清理资源（关闭数据库、环境等）
    3. 然后才退出
    """
    def signal_handler(signum, frame):
        global _cleanup_done
        sig_name = "SIGTERM" if signum == signal.SIGTERM else "SIGINT"
        print(f"\n收到 {sig_name} 信号，正在退出...")
        
        if not _cleanup_done:
            _cleanup_done = True
            # 设置事件通知 asyncio 循环退出（让循环有机会清理资源）
            if _shutdown_event:
                _shutdown_event.set()
        
        # 不要直接 sys.exit()，让 asyncio 循环正常退出并清理资源
        # 如果是重复收到信号，才强制退出
        else:
            print("强制退出...")
            sys.exit(1)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


if __name__ == "__main__":
    setup_signal_handlers()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n程序被中断")
    except SystemExit:
        pass
    finally:
        # DEFECT-3: 终版 token 快照——失败/中断/信号退出路径也不丢账（目录未钉定 =
        # 从未进入 main 主体 = 无任何调用可记）。写入原子且绝不抛出。
        if _SIM_LLM_TELEMETRY_SINK.get("dir"):
            _write_sim_llm_telemetry(
                _SIM_LLM_TELEMETRY_SINK["dir"],
                _SIM_LLM_TELEMETRY_SINK.get("config"),
            )
        # 清理 multiprocessing 资源跟踪器（防止退出时的警告）
        try:
            from multiprocessing import resource_tracker
            resource_tracker._resource_tracker._stop()
        except Exception:
            pass
        print("模拟进程已退出")
