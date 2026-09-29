"""DRF 模拟引擎 MCP 服务器（stdio 传输，官方 ``mcp`` SDK / FastMCP）。

把 ``app.services.simulation_runner.SimulationRunner`` 的模拟采访/状态/结果 API 暴露给
deer-flow 2.0 harness。运行方式（须从 backend 目录启动，使 ``import app.*`` 可解析）::

    /path/to/backend/.venv/bin/python -m app.mcp.sim_server --sim-id <id>

在 extensions_config.json 里注册为 stdio MCP server（command=上面的 venv python，
args=["-m","app.mcp.sim_server"]，可选把 ``--sim-id`` 或 ``DRF_MCP_SIM_ID`` 环境变量传入）。

暴露的工具（工具名 → 底层 SimulationRunner 函数）：
- ``sim_status``           → ``get_run_state`` + ``get_env_status_detail``（进度/健康/采访就绪）
- ``sim_results``          → ``get_timeline`` + ``get_agent_stats`` + run_summary.json（结构化结果）
- ``sim_interview_agents`` → ``interview_agents_batch`` / ``interview_agent`` / ``interview_all_agents``

可用性纪律（degrade-safe）：
- 启动 / ``tools/list`` 不触碰模拟 IPC / 文件系统——服务器永远能干净启动并列出工具，
  故 bridge research 早于任何模拟存在时也不会拖垮 harness。
- 采访要求模拟进程在线（file-based IPC 契约）。sim_interview_agents 先探活
  （``SimulationIPCClient.check_env_alive``）：环境不在线立即返回结构化错误，**不**空等满
  整个 timeout。所有阻塞调用都丢进线程池并套 ``asyncio.wait_for`` 超时上限，绝不 hang 协议循环，
  也绝不把异常抛给协议层（统一 ``{"ok": False, "error": ...}``）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import Any, Dict, List, Optional

# harness 以非 backend CWD 拉起时的兜底：把 backend 目录（parents[2]）放进 sys.path。
_BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

SERVER_NAME = "drf-simulation"

INSTRUCTIONS = (
    "DRF OASIS multi-agent social simulation service. Tools read the simulation's "
    "file-based run state and interview its agents in character. sim_status polls "
    "progress/health and whether interviews are possible now; sim_results fetches the "
    "structured timeline, per-agent stats and run_summary after the run; "
    "sim_interview_agents interviews agents inside a LIVE simulation (blocking, up to "
    "timeout). Every tool accepts an optional sim_id; when omitted the server default "
    "(--sim-id or DRF_MCP_SIM_ID) is used. Interviews require the simulation process to "
    "be alive: a dead/absent environment returns {ok:false,error} immediately instead of "
    "blocking, and nothing ever hangs the protocol."
)

# 进程级默认模拟 ID（--sim-id 或 DRF_MCP_SIM_ID 环境变量），工具未显式传 sim_id 时使用。
_DEFAULT_SIM_ID: str = ""


def _default_sim_id() -> str:
    return _DEFAULT_SIM_ID or (os.environ.get("DRF_MCP_SIM_ID") or "").strip()


def _default_timeout() -> float:
    """采访的默认超时上限（秒）。DRF_MCP_SIM_TIMEOUT 覆盖，默认 120；非法值回退 120。"""
    try:
        val = float(os.environ.get("DRF_MCP_SIM_TIMEOUT", "120") or "120")
    except (TypeError, ValueError):
        val = 120.0
    return val if val > 0 else 120.0


def _resolve_sim_id(sim_id: Optional[str]) -> str:
    sid = (sim_id or "").strip() or _default_sim_id()
    if not sid:
        raise ValueError(
            "缺少 sim_id：请在调用参数里传 sim_id，或用 --sim-id / DRF_MCP_SIM_ID 配置进程默认模拟。"
        )
    # INFRA-10: sim_id 来自 LLM 工具调用，会被拼进模拟目录路径——边界上先校验（UnsafeIdError
    # 由工具包装折成 {ok: false, error}），_sim_dir 拼接处再由 contained_child 复验一次。
    from app.utils.security import safe_id
    return safe_id(sid, "simulation")


def _error_payload(exc: BaseException, sim_id: str = "") -> Dict[str, Any]:
    payload: Dict[str, Any] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if sim_id:
        payload["sim_id"] = sim_id
    return payload


def _sim_dir(sim_id: str) -> str:
    from app.services.simulation_runner import SimulationRunner
    return SimulationRunner._sim_dir(sim_id)


def _env_alive(sim_id: str) -> bool:
    """探活模拟 IPC 环境（采访前置依赖）。任何异常/缺失一律按「不在线」处理（degrade-safe）。"""
    try:
        from app.services.simulation_ipc import SimulationIPCClient
        sim_dir = _sim_dir(sim_id)
        if not os.path.isdir(sim_dir):
            return False
        return bool(SimulationIPCClient(sim_dir).check_env_alive())
    except Exception:  # noqa: BLE001
        return False


# ==================== 同步实现（在线程池里跑）====================

def _impl_status(sim_id: str) -> Dict[str, Any]:
    """读取模拟运行状态 + 环境健康 + 采访就绪标志（不阻塞、纯文件读）。"""
    from app.services.simulation_runner import SimulationRunner
    state = SimulationRunner.get_run_state(sim_id)
    found = state is not None or os.path.isdir(_sim_dir(sim_id))
    env_status = SimulationRunner.get_env_status_detail(sim_id)
    interview_ready = _env_alive(sim_id)
    return {
        "found": found,
        "run_state": state.to_dict() if state else None,
        "env_status": env_status,
        "interview_ready": interview_ready,
    }


def _impl_results(sim_id: str, top_agents: int = 20) -> Dict[str, Any]:
    """读取模拟结构化结果：run_state + 逐轮 timeline + Top agent 统计 + run_summary.json。"""
    from app.services.simulation_runner import SimulationRunner
    state = SimulationRunner.get_run_state(sim_id)
    timeline = SimulationRunner.get_timeline(sim_id) or []
    agent_stats = SimulationRunner.get_agent_stats(sim_id) or []
    # 按总动作量取 Top-N agent，避免把 80 个 agent 的完整统计塞回 LLM 上下文。
    agent_stats_sorted = sorted(
        agent_stats, key=lambda s: s.get("total_actions", 0), reverse=True
    )[: max(1, int(top_agents))]
    # run_summary.json 是模拟收尾写的诚实账本（organic vs seed、simulation_health 等）。
    run_summary: Optional[Dict[str, Any]] = None
    summary_path = os.path.join(_sim_dir(sim_id), "run_summary.json")
    if os.path.isfile(summary_path):
        try:
            with open(summary_path, "r", encoding="utf-8") as f:
                run_summary = json.load(f)
        except (json.JSONDecodeError, OSError):
            run_summary = None
    # 未终止时标记 partial，提醒下游结果可能不完整。
    runner_status = state.runner_status.value if state else "unknown"
    partial = runner_status not in ("completed", "failed", "stopped")
    return {
        "sim_id": sim_id,
        "partial": partial,
        "runner_status": runner_status,
        "timeline": timeline,
        "agent_stats": agent_stats_sorted,
        "run_summary": run_summary,
    }


def _impl_interview(sim_id: str, prompt: Optional[str], agent_id: Optional[int],
                    interviews: Optional[List[Dict[str, Any]]], platform: Optional[str],
                    timeout: float) -> Dict[str, Any]:
    """采访在线模拟中的 agent（阻塞）。三种模式：批量 / 单个 / 全体。环境不在线立即拒绝。"""
    from app.services.simulation_runner import SimulationRunner
    if not os.path.isdir(_sim_dir(sim_id)):
        return {"ok": False, "sim_id": sim_id, "error": f"ValueError: 模拟不存在: {sim_id}"}
    # 探活：环境不在线（进程已死/未起）立即返回，不空等满 timeout。
    if not _env_alive(sim_id):
        return {
            "ok": False, "sim_id": sim_id,
            "error": "EnvironmentNotAlive: 模拟 IPC 环境不在线（进程未运行或已结束），无法采访。"
                     "请先用 sim_status 确认 interview_ready=true。",
        }
    try:
        if interviews:
            payload = SimulationRunner.interview_agents_batch(
                simulation_id=sim_id, interviews=interviews, platform=platform, timeout=timeout)
        elif agent_id is not None and prompt:
            payload = SimulationRunner.interview_agent(
                simulation_id=sim_id, agent_id=agent_id, prompt=prompt,
                platform=platform, timeout=timeout)
        elif prompt:
            payload = SimulationRunner.interview_all_agents(
                simulation_id=sim_id, prompt=prompt, platform=platform, timeout=timeout)
        else:
            return {
                "ok": False, "sim_id": sim_id,
                "error": "ValueError: 采访参数不足：需 interviews=[...]，或 agent_id+prompt，或 prompt。",
            }
        return {"ok": True, "sim_id": sim_id, "result": payload}
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc, sim_id)


# ==================== 异步工具面（超时上限 + 结构化错误）====================

async def _run_guarded(fn, sim_id: str, timeout: float, *args: Any) -> Dict[str, Any]:
    """把同步实现丢进线程池并套 asyncio.wait_for 超时上限；异常/超时折成结构化错误。"""
    try:
        return await asyncio.wait_for(asyncio.to_thread(fn, sim_id, *args), timeout=timeout)
    except asyncio.TimeoutError:
        return {"ok": False, "sim_id": sim_id,
                "error": f"TimeoutError: 模拟调用超过 {timeout:.0f}s 未返回（已放弃，未 hang 协议）"}
    except Exception as exc:  # noqa: BLE001
        return _error_payload(exc, sim_id)


def build_server(default_sim_id: str = ""):
    """构建并返回注册了全部模拟工具的 FastMCP 实例（不启动传输）。

    ``mcp`` SDK 在函数内导入，使 ``import app.mcp.sim_server`` 在未装 SDK 时也能干净失败。"""
    global _DEFAULT_SIM_ID
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover
        raise ImportError(
            "官方 mcp SDK 未安装。请执行 "
            "`backend/.venv/bin/pip install -r backend/requirements.txt`（含 'mcp'）。"
        ) from exc

    if default_sim_id:
        _DEFAULT_SIM_ID = default_sim_id

    server = FastMCP(SERVER_NAME, instructions=INSTRUCTIONS)

    @server.tool(
        name="sim_status",
        description=(
            "Poll an OASIS simulation's run state and health from its file-based state: "
            "round progress, per-platform action counts, runner_status, env_status "
            "(twitter/reddit availability) and interview_ready (whether "
            "sim_interview_agents can succeed right now). Pure file reads, non-blocking. "
            "Optional sim_id overrides the server default. Returns {ok, sim_id, "
            "result:{found, run_state, env_status, interview_ready}}."
        ),
    )
    async def sim_status(sim_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            sid = _resolve_sim_id(sim_id)
        except Exception as exc:  # noqa: BLE001
            return _error_payload(exc)
        result = await _run_guarded(_impl_status, sid, _default_timeout())
        # _impl_status 成功返回裸 dict（无 ok 键）；此处补 ok/sim_id 外壳（错误路径已带 ok）。
        return result if "ok" in result else {"ok": True, "sim_id": sid, "result": result}

    @server.tool(
        name="sim_results",
        description=(
            "Fetch structured results of an OASIS simulation: run_state, the per-round "
            "timeline (action volume by round), the Top-N agents by total actions "
            "(top_agents, default 20) and run_summary.json when present (the honest "
            "accounting: organic vs seed actions, simulation_health, rounds_executed). "
            "partial=true when the run has not reached a terminal state. Optional sim_id "
            "overrides the server default. Returns {ok, sim_id, result:{...}}."
        ),
    )
    async def sim_results(sim_id: Optional[str] = None, top_agents: int = 20) -> Dict[str, Any]:
        try:
            sid = _resolve_sim_id(sim_id)
        except Exception as exc:  # noqa: BLE001
            return _error_payload(exc)
        result = await _run_guarded(_impl_results, sid, _default_timeout(), top_agents)
        return result if "ok" in result else {"ok": True, "sim_id": sid, "result": result}

    @server.tool(
        name="sim_interview_agents",
        description=(
            "Interview simulated agents inside a LIVE OASIS simulation (blocking, up to "
            "timeout seconds). Bridges the file-based interview IPC: questions are "
            "answered in character by the agents' LLMs. Requires the simulation process "
            "to be alive (check sim_status.interview_ready first); a dead/absent "
            "environment is rejected immediately instead of blocking. Three modes: "
            "interviews=[{agent_id, prompt, platform?}, ...] for a batch; agent_id+prompt "
            "for one agent; prompt alone to ask ALL agents the same question (can take "
            "minutes). platform: 'twitter' | 'reddit' | None (both in a parallel run). "
            "Optional sim_id overrides the server default. Returns {ok, sim_id, result} "
            "or {ok:false, error}."
        ),
    )
    async def sim_interview_agents(
        sim_id: Optional[str] = None,
        prompt: Optional[str] = None,
        agent_id: Optional[int] = None,
        interviews: Optional[List[Dict[str, Any]]] = None,
        platform: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        try:
            sid = _resolve_sim_id(sim_id)
        except Exception as exc:  # noqa: BLE001
            return _error_payload(exc)
        inner_timeout = timeout if (timeout and timeout > 0) else _default_timeout()
        # 外层看门狗略大于内层 IPC 超时，给探活/收尾留缓冲，同时保证协议不会永久阻塞。
        outer_timeout = inner_timeout + 30.0
        return await _run_guarded(
            _impl_interview, sid, outer_timeout,
            prompt, agent_id, interviews, platform, inner_timeout,
        )

    return server


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        prog="drf-simulation-server",
        description="DRF simulation engine MCP server (stdio) wrapping SimulationRunner interview/status/results.",
    )
    parser.add_argument(
        "--sim-id",
        default="",
        help="进程默认模拟 ID（工具未显式传 sim_id 时使用；亦可用 DRF_MCP_SIM_ID 环境变量）。",
    )
    args = parser.parse_args(argv)
    default_sid = args.sim_id or (os.environ.get("DRF_MCP_SIM_ID") or "").strip()
    server = build_server(default_sim_id=default_sid)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
