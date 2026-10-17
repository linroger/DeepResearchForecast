"""
动作日志记录器
用于记录OASIS模拟中每个Agent的动作，供后端监控使用

日志结构:
    sim_xxx/
    ├── twitter/
    │   └── actions.jsonl    # Twitter 平台动作日志
    ├── reddit/
    │   └── actions.jsonl    # Reddit 平台动作日志
    ├── simulation.log       # 主模拟进程日志
    └── run_state.json       # 运行状态（API 查询用）
"""

import json
import os
import logging
import sys
from datetime import datetime
from typing import Dict, Any, Optional


def _stdio_points_at(path: str) -> bool:
    """True when this process's stdout or stderr already is the file at ``path``: the launching
    backend (app/services/simulation_runner.py) captures the runner's console into simulation.log."""
    try:
        target = os.stat(path)
    except OSError:
        return False
    for stream in (sys.stdout, sys.stderr):
        try:
            if os.path.samestat(os.fstat(stream.fileno()), target):
                return True
        except (AttributeError, OSError, ValueError):
            continue
    return False


class PlatformActionLogger:
    """单平台动作日志记录器"""
    
    def __init__(self, platform: str, base_dir: str):
        """
        初始化日志记录器
        
        Args:
            platform: 平台名称 (twitter/reddit)
            base_dir: 模拟目录的基础路径
        """
        self.platform = platform
        self.base_dir = base_dir
        self.log_dir = os.path.join(base_dir, platform)
        self.log_path = os.path.join(self.log_dir, "actions.jsonl")
        self._ensure_dir()
    
    def _ensure_dir(self):
        """确保目录存在"""
        os.makedirs(self.log_dir, exist_ok=True)
    
    def log_action(
        self,
        round_num: int,
        agent_id: int,
        agent_name: str,
        action_type: str,
        action_args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True
    ):
        """记录一个动作"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_args": action_args or {},
            "result": result,
            "success": success,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_start(self, round_num: int, simulated_hour: int,
                        period_label: Optional[str] = None):
        """记录轮次开始。period_label=日历模式的时段标签（如 "2027-Q3"），
        hours 模式不传 → 输出逐字节不变。"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_start",
            "simulated_hour": simulated_hour,
        }
        if period_label is not None:
            entry["period_label"] = period_label

        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def log_round_end(self, round_num: int, actions_count: int,
                      simulated_hours: Optional[float] = None,
                      period_end: Optional[str] = None):
        """记录轮次结束。simulated_hours=累计已模拟小时数——runner 的 round_end 对账
        （simulation_runner state.simulated_hours）以此为唯一数据源，缺省则对账值恒为 0。
        period_end=日历模式本轮覆盖时段的结束日（ISO），runner 据此推进 current_period_end；
        hours 模式不传 → 输出逐字节不变。"""
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "round_end",
            "actions_count": actions_count,
        }
        if simulated_hours is not None:
            entry["simulated_hours"] = simulated_hours
        if period_end is not None:
            entry["period_end"] = period_end

        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def log_world_update(self, round_num: int, headline: str, **fields: Any):
        """REFLEXIVE WORLD: one row per committed world update (round is 1-based).

        The backend monitor projects ``headline``/``period_label``/``arbiter_status``
        into run_state.options["world_model"]; hours mode never emits this event."""
        entry: Dict[str, Any] = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "event_type": "world_update",
            "headline": str(headline or ""),
        }
        for key, value in fields.items():
            if value is not None:
                entry[key] = value

        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def log_simulation_start(self, config: Dict[str, Any], total_rounds: int):
        """记录模拟开始。total_rounds 由调用方显式给出——旧实现按
        total_simulation_hours*2 硬编码推算，早已与真实轮数公式
        （total_hours*60/minutes_per_round + 截断/日历 n_rounds）脱节（陈旧 bug）。"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_start",
            "platform": self.platform,
            "total_rounds": total_rounds,
            "agents_count": len(config.get("agent_configs", [])),
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_end(self, total_rounds: int, total_actions: int):
        """记录模拟结束"""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "event_type": "simulation_end",
            "platform": self.platform,
            "total_rounds": total_rounds,
            "total_actions": total_actions,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


class SimulationLogManager:
    """
    模拟日志管理器
    统一管理所有日志文件，按平台分离
    """
    
    def __init__(self, simulation_dir: str):
        """
        初始化日志管理器
        
        Args:
            simulation_dir: 模拟目录路径
        """
        self.simulation_dir = simulation_dir
        self.twitter_logger: Optional[PlatformActionLogger] = None
        self.reddit_logger: Optional[PlatformActionLogger] = None
        self._main_logger: Optional[logging.Logger] = None
        
        # 设置主日志
        self._setup_main_logger()
    
    def _setup_main_logger(self):
        """设置主模拟日志。

        The launching backend streams this process's stdout/stderr into the same ``simulation.log``
        through its own append-only handle (SimulationRunner._open_main_log), so the file handler
        appends as well — a second non-appending writer overwrites the other's bytes at its private
        offset and the world-model round lines came out torn or missing.  The file is truncated only
        when no standard stream already points at it (a standalone run starts a fresh log; a
        backend capture is never discarded), and the console handler is skipped when stderr IS the
        log file, where it would only repeat every record."""
        log_path = os.path.join(self.simulation_dir, "simulation.log")
        shared = _stdio_points_at(log_path)
        if not shared:
            with open(log_path, 'w', encoding='utf-8'):
                pass
        
        # 创建 logger
        self._main_logger = logging.getLogger(f"simulation.{os.path.basename(self.simulation_dir)}")
        self._main_logger.setLevel(logging.INFO)
        self._main_logger.handlers.clear()
        
        # 文件处理器（追加写：与后端捕获的 stdout/stderr 共用同一文件）
        file_handler = logging.FileHandler(log_path, encoding='utf-8', mode='a')
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        ))
        self._main_logger.addHandler(file_handler)
        
        # 控制台处理器（stderr 已经就是日志文件时省略，避免每条记录写两遍）
        if not shared:
            console_handler = logging.StreamHandler()
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(logging.Formatter(
                '[%(asctime)s] %(message)s',
                datefmt='%H:%M:%S'
            ))
            self._main_logger.addHandler(console_handler)
        
        self._main_logger.propagate = False
    
    def get_twitter_logger(self) -> PlatformActionLogger:
        """获取 Twitter 平台日志记录器"""
        if self.twitter_logger is None:
            self.twitter_logger = PlatformActionLogger("twitter", self.simulation_dir)
        return self.twitter_logger
    
    def get_reddit_logger(self) -> PlatformActionLogger:
        """获取 Reddit 平台日志记录器"""
        if self.reddit_logger is None:
            self.reddit_logger = PlatformActionLogger("reddit", self.simulation_dir)
        return self.reddit_logger
    
    def log(self, message: str, level: str = "info"):
        """记录主日志"""
        if self._main_logger:
            getattr(self._main_logger, level.lower(), self._main_logger.info)(message)
    
    def info(self, message: str):
        self.log(message, "info")
    
    def warning(self, message: str):
        self.log(message, "warning")
    
    def error(self, message: str):
        self.log(message, "error")
    
    def debug(self, message: str):
        self.log(message, "debug")


# ============ 兼容旧接口 ============

class ActionLogger:
    """
    动作日志记录器（兼容旧接口）
    建议使用 SimulationLogManager 代替
    """
    
    def __init__(self, log_path: str):
        self.log_path = log_path
        self._ensure_dir()
    
    def _ensure_dir(self):
        log_dir = os.path.dirname(self.log_path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
    
    def log_action(
        self,
        round_num: int,
        platform: str,
        agent_id: int,
        agent_name: str,
        action_type: str,
        action_args: Optional[Dict[str, Any]] = None,
        result: Optional[str] = None,
        success: bool = True
    ):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "agent_id": agent_id,
            "agent_name": agent_name,
            "action_type": action_type,
            "action_args": action_args or {},
            "result": result,
            "success": success,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_start(self, round_num: int, simulated_hour: int, platform: str):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "round_start",
            "simulated_hour": simulated_hour,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_round_end(self, round_num: int, actions_count: int, platform: str,
                      simulated_hours: Optional[float] = None):
        entry = {
            "round": round_num,
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "round_end",
            "actions_count": actions_count,
        }
        if simulated_hours is not None:
            entry["simulated_hours"] = simulated_hours

        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_start(self, platform: str, config: Dict[str, Any]):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "simulation_start",
            "total_rounds": config.get("time_config", {}).get("total_simulation_hours", 72) * 2,
            "agents_count": len(config.get("agent_configs", [])),
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    
    def log_simulation_end(self, platform: str, total_rounds: int, total_actions: int):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "platform": platform,
            "event_type": "simulation_end",
            "total_rounds": total_rounds,
            "total_actions": total_actions,
        }
        
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')


# 全局日志实例（兼容旧接口）
_global_logger: Optional[ActionLogger] = None


def get_logger(log_path: Optional[str] = None) -> ActionLogger:
    """获取全局日志实例（兼容旧接口）"""
    global _global_logger
    
    if log_path:
        _global_logger = ActionLogger(log_path)
    
    if _global_logger is None:
        _global_logger = ActionLogger("actions.jsonl")
    
    return _global_logger
