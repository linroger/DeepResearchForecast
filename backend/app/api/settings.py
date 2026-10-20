"""设置 API：运行时查询/切换/测试 LLM 模型提供方，以及官方数据源探活。

路由（挂载于 /api/settings）：
    GET  /llm        当前提供方 + 受支持提供方清单（含展示元数据）
    POST /llm        切换提供方 {provider, api_key?, base_url?, model?}；对新发起的管线生效
    POST /llm/test   测试连通性 {provider, api_key?, base_url?, model?}；不持久化任何配置
    POST /data-sources/test  官方数据 MCP 服务探活（握手 + 每家一条缓存优先的样本序列）；
                     返回 {providers: {name: {state, detail, latency_s, keys}}}，纯建议性

切换是运行时的：更新 Config 类属性 + os.environ（DeerFlow 子进程继承），并 upsert 进 .env。
已在运行中的管线不受影响（它们已读取旧配置）。
"""

import importlib
import os
import re
import shutil
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait as wait_futures
from pathlib import Path

from flask import jsonify, request

from . import settings_bp
from ..config import Config
from ..utils.logger import get_logger

logger = get_logger('mirofish.api.settings')


@settings_bp.route('/llm', methods=['GET'])
def get_llm_settings():
    return jsonify({"success": True, "data": Config.provider_info()})


@settings_bp.route('/llm', methods=['POST'])
def set_llm_settings():
    try:
        data = request.get_json(silent=True) or {}
        provider = (data.get('provider') or '').strip().lower()
        if not provider:
            return jsonify({"success": False, "error": "缺少 provider"}), 400
        info = Config.apply_provider(
            provider,
            api_key=data.get('api_key'),
            base_url=data.get('base_url'),
            model=data.get('model'),
        )
        logger.info(f"LLM 提供方已切换为: {provider}（DeerFlow 研究模型={info.get('deerflow_model')}）")
        return jsonify({"success": True, "data": info})
    except ValueError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except Exception as e:
        logger.error(f"切换提供方失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": "internal server error"}), 500


# 测试用最小请求：固定一条只要求回 "pong" 的消息，max_tokens 很小、显式关闭推理，
# 这样无论提供方/模型多贵，测试成本都可忽略（几十个 token）。
_TEST_TIMEOUT_SECONDS = 25


def _test_cli_provider(provider):
    """CLI 提供方（claude-cli / codex-cli）：检查本机 CLI 是否在 PATH 上并取版本号。"""
    cli = 'claude' if provider == 'claude-cli' else 'codex'
    path = shutil.which(cli)
    if not path:
        return {
            "ok": False,
            "error": f"'{cli}' CLI not found on PATH. Install it (or pick an API-key provider).",
        }
    version = ''
    try:
        out = subprocess.run(
            [cli, '--version'], capture_output=True, text=True, timeout=10
        )
        version = (out.stdout or out.stderr or '').strip().splitlines()[0][:120]
    except Exception:
        pass  # 版本号只是锦上添花；CLI 在 PATH 上即视为可用
    return {"ok": True, "detail": f"{path}" + (f" · {version}" if version else "")}


def _test_openai_compat_provider(provider, api_key, base_url, model):
    """OpenAI 兼容提供方：发一条最小 chat completion 验证 Key/Base URL/模型名。"""
    if not api_key:
        return {"ok": False, "error": "API key required — enter a key to test."}

    # SSRF 防护（EXECPLAN2 F-13-2）：拒绝指向云元数据/链路本地等地址的 base_url。
    from ..utils.security import validate_safe_url
    try:
        validate_safe_url(base_url, block_private=Config.APP_BLOCK_PRIVATE_URLS)
    except ValueError as e:
        return {"ok": False, "error": f"refused base_url: {e}"}

    from openai import OpenAI

    client_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "timeout": _TEST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    # Kimi-for-coding 网关按 User-Agent 校验 coding-agent 身份（详见 llm_client.py）。
    if provider == 'kimi':
        client_kwargs["default_headers"] = {"User-Agent": Config.LLM_USER_AGENT}

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": 0,
        "max_tokens": 16,
    }
    # 推理提供方：测试时一律关闭推理，避免 reasoning 吃光 max_tokens 导致空 content。
    # A model that always reasons (glm-5.x) refuses that (HTTP 400 / 1210) and gets the lowest
    # accepted effort instead; a reply cut short by reasoning still proves the key works.
    extra_body = Config.minimal_reasoning_body(provider, model)
    if extra_body:
        kwargs["extra_body"] = extra_body
    # Kimi K2.7 Code 网关硬校验温度（开推理只接受 1、关推理只接受 0.6），temperature=0 会 400。
    # 与 LLMClient._coerce_temperature 同源，否则前端「测试连接」会把 kimi 误报为失败。
    if provider == 'kimi':
        thinking_disabled = bool(extra_body and (extra_body.get("thinking") or {}).get("type") == "disabled")
        kwargs["temperature"] = 0.6 if thinking_disabled else 1.0

    started = time.monotonic()
    try:
        response = OpenAI(**client_kwargs).chat.completions.create(**kwargs)
    except Exception as e:
        status = getattr(e, 'status_code', None)
        hints = {
            401: "invalid or expired API key",
            403: "key valid but access denied (plan/permissions)",
            404: "endpoint or model not found — check Base URL / model name",
            429: "rate limited — key works, but quota is exhausted",
        }
        hint = hints.get(status) if isinstance(status, int) else None
        # 不把上游 SDK 异常原文回显给客户端（可能含内部 URL/路径，EXECPLAN2 F-8-5）。
        # 仅返回映射后的提示；原始异常记到服务端日志。
        logger.warning(f"连通性测试失败 provider={provider} status={status}: {e}")
        return {
            "ok": False,
            "status_code": status,
            "error": hint or "connection test failed — check API key / Base URL / model name",
        }
    latency_ms = int((time.monotonic() - started) * 1000)
    content = ''
    try:
        content = (response.choices[0].message.content or '').strip()
    except Exception:
        pass
    return {
        "ok": True,
        "latency_ms": latency_ms,
        "model": getattr(response, 'model', None) or model,
        "reply": content[:80],
    }


@settings_bp.route('/llm/test', methods=['POST'])
def test_llm_settings():
    """测试一个提供方配置的连通性。**不持久化**任何配置 —— 纯探活。

    请求体与 POST /llm 相同：{provider, api_key?, base_url?, model?}。
    api_key 缺省时，仅当 provider 为当前已配置的提供方才回退到已保存的 Key
    （前端「已配置，可留空沿用」语义一致）。

    返回 200 + data.ok=true/false：测试**完成**即 200，连通失败体现在 data.ok，
    400/500 仅用于非法请求/服务端异常。
    """
    try:
        data = request.get_json(silent=True) or {}
        provider = (data.get('provider') or Config.LLM_PROVIDER or '').strip().lower()
        meta = Config.PROVIDER_META.get(provider)
        if not meta:
            return jsonify({
                "success": False,
                "error": f"不支持的提供方: {provider}（需为 {', '.join(Config.SUPPORTED_LLM_PROVIDERS)} 之一）",
            }), 400

        if not meta.get('openai_compat'):
            result = _test_cli_provider(provider)
        else:
            api_key = (data.get('api_key') or '').strip()
            if not api_key and provider == Config.LLM_PROVIDER:
                api_key = Config.LLM_API_KEY or ''
            base_url, model = Config.resolve_endpoint(provider, data.get('base_url'), data.get('model'))
            result = _test_openai_compat_provider(provider, api_key, base_url, model)

        result["provider"] = provider
        logger.info(f"LLM 连通性测试: provider={provider} ok={result.get('ok')}")
        return jsonify({"success": True, "data": result})
    except Exception as e:
        logger.error(f"LLM 连通性测试失败: {e}", exc_info=True)
        return jsonify({"success": False, "error": "internal server error"}), 500


# ──────────────────────────────────────────────────────────────
# 官方数据源探活（I4）：POST /data-sources/test 与 `scripts/doctor.sh --deep` 共用
# probe_data_sources()。对每个启用的 provider：MCP initialize + list_tools（hub 启动握手），
# 再经 DataSources 取一条目录样本序列（磁盘缓存优先，TTL 内重复探活零上游调用）。BLS 只握手、
# 绝不发数据请求——免 key 日配额只有 20 次，探活不得消耗。结果纯建议性：只用于展示，绝不阻断
# 运行；只报告 key 名与状态（set / not set / invalid），绝不回显 key 值。
# 用私有 hub + 客户端、探完即关：探活要反映「此刻」各服务能否启动，且不在后端常驻六个子进程
# （合计约 800 MB）；同一时刻只允许一次探活。
# ──────────────────────────────────────────────────────────────
_DATA_TEST_DEADLINE_SECONDS = 75.0   # 构建数据层 + 握手 + 样本的总预算：IMF 冷缓存单次调用实测 34~60 s
                                     # （2026-10-12），成功一次后其样本 24 h 内走缓存
_DATA_TEST_GRACE_SECONDS = 2.0       # 预算到点后等待 worker 收尾的余量
_DATA_TEST_CLOSE_SECONDS = 5.0       # 私有 hub 等待各 MCP 会话正常结束的时限（McpHub.close 的 timeout）
# McpHub.close 在 timeout 之外的最坏余量：≤1 s SIGTERM 等待 + 2 s TERM 宽限 + 2 s 取消宽限 +
# ≤1 s 末次 SIGTERM 等待 + 2 s 事件循环线程 join。
_DATA_HUB_CLOSE_OVERHEAD_SECONDS = 8.0
# 端点自身的最坏墙钟耗时（约 90 s）：调用方须至少等这么久——前端 Settings 卡片超时 120 s，
# doctor --deep 文档写「up to ~90s」（tests/test_settings_data_sources_probe.py 校验二者）。
_DATA_TEST_MAX_SECONDS = (_DATA_TEST_DEADLINE_SECONDS + _DATA_TEST_GRACE_SECONDS
                          + _DATA_TEST_CLOSE_SECONDS + _DATA_HUB_CLOSE_OVERHEAD_SECONDS)
_DATA_PROVIDERS = ("fred", "bls", "bis", "imf", "wb", "usgov")
# 每家一条稳定、廉价的目录序列（测试断言它们都在 data_catalog 中）；BLS 刻意缺席。
_DATA_PROBE_SAMPLES = {
    "fred": "fred:UNRATE",
    "bis": "bis:WS_CBPOL/M.US",
    "imf": "imf:WEO/G001.NGDP_RPCH.A",
    "wb": "wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA",
    "usgov": "usgov:treasury/debt_to_penny",
}
# 每家相关的 key 名（usgov 的三把 key 各自解锁一个可选模块，与 data_mcp.USGOV_KEYED_MODULES 一致）。
_DATA_PROBE_KEYS = {
    "fred": ("FRED_API_KEY",),
    "bls": ("BLS_API_KEY",),
    "usgov": ("EIA_API_KEY", "BEA_API_KEY", "CENSUS_API_KEY"),
}
_DATA_SECRET_NAMES = ("FRED_API_KEY", "BLS_API_KEY", "EIA_API_KEY", "BEA_API_KEY",
                      "CENSUS_API_KEY", "DATA_GOV_API_KEY")
# 只有 FRED / BLS 的数据路由由各自的 key 决定（缺 key = 降级路由，被拒 = key 无效）；
# usgov 的样本走免 key 的 Treasury 端点，其 key 只解锁可选模块，故不据样本判定其有效性。
_DATA_PRIMARY_KEYS = {"fred": "FRED_API_KEY", "bls": "BLS_API_KEY"}
_DATA_KEYLESS_NOTES = {
    "fred": "FRED_API_KEY not set: keyless CSV route only, no FRED free-text search",
    "bls": "BLS_API_KEY not set: keyless BLS access is limited to 20 requests per day",
}
_DATA_SECRET_PARAM = re.compile(r"(?i)\b(api_key|registrationkey|userid)=[^&\s\"']+")
_DATA_DETAIL_MAX_CHARS = 400
_DATA_PROBE_LOCK = threading.Lock()


class DataProbeBusy(RuntimeError):
    """Another official-data probe is still running (each one starts every enabled server)."""


def _data_probe_env():
    """The research subprocess's data env: process env (keys) + Config's resolved DATA_SOURCES_*."""
    from ..services.pipeline_orchestrator import _data_sources_subprocess_env
    env = {str(k): str(v) for k, v in os.environ.items()}
    env.update(_data_sources_subprocess_env())
    return env


def _default_data_probe_clients(env):
    """A private (hub, DataSources) pair over the six default server specs; the caller closes both."""
    from ..services.official_data import data_api
    api = data_api()
    if api is None:
        raise RuntimeError("official-data bridge module unavailable")
    dm = importlib.import_module("deerflow_bridge.data_mcp")
    cache_dir = (env.get("DATA_SOURCES_CACHE_DIR") or "").strip()
    hub = dm.McpHub(dm.default_server_specs(env=env),
                    errlog_dir=Path(cache_dir) / "mcp-logs" if cache_dir else None)
    return hub, api.DataSources(hub, env=env)


def _redact_data_text(text, env):
    """Scrub configured key values and credential query parameters from probe text."""
    clean = _DATA_SECRET_PARAM.sub(lambda m: m.group(1) + "=[redacted]", str(text or ""))
    for name in _DATA_SECRET_NAMES:
        value = (env.get(name) or "").strip()
        if len(value) >= 4:
            clean = clean.replace(value, "[redacted]")
    clean = " ".join(clean.split())
    return clean if len(clean) <= _DATA_DETAIL_MAX_CHARS else clean[:_DATA_DETAIL_MAX_CHARS - 1] + "…"


def _data_key_status(provider, env, invalid=False):
    """Key NAMES with set / not set / invalid — never values. Only a primary key can be invalid."""
    primary = _DATA_PRIMARY_KEYS.get(provider)
    return {name: ("invalid" if invalid and name == primary else "set") if (env.get(name) or "").strip()
            else "not set" for name in _DATA_PROBE_KEYS.get(provider, ())}


def _data_probe_row(provider, state, detail, latency_s, env, *, key_invalid=False):
    return {"state": state, "detail": _redact_data_text(detail, env),
            "latency_s": round(max(0.0, float(latency_s)), 2),
            "keys": _data_key_status(provider, env, key_invalid)}


def _probe_data_provider(name, hub, client, deadline):
    """Handshake one provider and fetch its sample; returns the raw facts for the row."""
    started = time.monotonic()
    parts = []
    try:
        hub.start([name], wait=max(0.0, deadline - time.monotonic()))
        status = (hub.status() or {}).get(name) or {}
    except Exception as exc:  # noqa: BLE001 — 探活只报告，不向上抛
        status = {"state": "failed", "error": f"hub error ({type(exc).__name__})"}
    ready = status.get("state") == "ready"
    if ready:
        parts.append(f"MCP handshake ok ({len(status.get('tools') or [])} tools"
                     + (f", ready in {status['ready_s']} s)" if status.get("ready_s") is not None else ")"))
    else:
        reason = status.get("error") or ("no handshake within the probe deadline"
                                         if status.get("state") == "starting" else "no handshake")
        parts.append(f"MCP server {status.get('state') or 'unavailable'}: {reason}")
    sample = _DATA_PROBE_SAMPLES.get(name)
    sample_ok = None
    key_invalid = False
    if sample is None:
        parts.append("handshake only: no BLS data request, so the daily quota is untouched")
    elif deadline - time.monotonic() <= 0:
        sample_ok = False
        parts.append(f"sample {sample} skipped: probe deadline reached")
    else:
        try:
            result = client.get_many([sample], deadline_s=deadline - time.monotonic()).get(sample)
        except Exception as exc:  # noqa: BLE001
            result = None
            parts.append(f"sample {sample} failed ({type(exc).__name__})")
        observations = getattr(result, "observations", None)
        if isinstance(observations, list):
            values = [o for o in observations if getattr(o, "value", None) is not None]
            sample_ok = bool(values)
            route = getattr(result, "route", "") or "mcp"
            origin = "from cache" if route == "cache" else f"live via {route}"
            parts.append(f"sample {sample}: {len(values)} observations"
                         + (f" to {values[-1].date}" if values else "") + f" ({origin})")
        elif result is not None:
            sample_ok = False
            code = getattr(result, "code", "") or "provider_error"
            key_invalid = code == "key_invalid"
            parts.append(f"sample {sample}: DATA_UNAVAILABLE[{code}]: "
                         f"{getattr(result, 'message', '') or result}")
        else:
            sample_ok = False
    return {"ready": ready, "sample_ok": sample_ok, "key_invalid": key_invalid,
            "parts": parts, "latency_s": time.monotonic() - started}


def _data_probe_state(name, facts, env, flagged_invalid):
    """ok / degraded / unavailable from the handshake, the sample and the key situation."""
    primary = _DATA_PRIMARY_KEYS.get(name)
    has_key = bool(primary and (env.get(primary) or "").strip())
    # A 401/403 on a keyless route is a provider refusal, not a bad key.
    key_invalid = has_key and (facts["key_invalid"] or flagged_invalid)
    keyless = bool(primary) and not has_key
    parts = list(facts["parts"])
    if key_invalid:
        parts.append(f"{primary} rejected by the provider: fix or remove it")
    elif keyless:
        parts.append(_DATA_KEYLESS_NOTES[name])
    data_ok = facts["ready"] if facts["sample_ok"] is None else facts["sample_ok"]
    if not facts["ready"] and not facts["sample_ok"]:
        state = "unavailable"
    elif facts["ready"] and data_ok and not key_invalid and not keyless:
        state = "ok"
    else:
        state = "degraded"
    return _data_probe_row(name, state, "; ".join(parts), facts["latency_s"], env,
                           key_invalid=key_invalid)


def probe_data_sources(*, env=None, deadline_s=None, clients=None):
    """Advisory live probe of the official-data MCP servers, bounded by ``deadline_s``
    (default 75 s) plus the worker grace and the private hub's close: at most
    ``_DATA_TEST_MAX_SECONDS`` (≈ 90 s) of wall clock with the defaults.

    Returns ``{"enabled", "providers": {name: {state, detail, latency_s, keys}}, "deadline_s",
    "elapsed_s"}`` with state ∈ ok / degraded / unavailable / disabled. ``clients(env)`` returns
    a ``(hub, data_sources)`` pair (default: a private McpHub + DataSources over the default
    server specs); both are closed before returning. Raises :class:`DataProbeBusy` when a probe
    is already running; every provider failure is reported in its row, never raised.
    """
    started = time.monotonic()
    budget = _DATA_TEST_DEADLINE_SECONDS if deadline_s is None else max(0.1, float(deadline_s))
    deadline = started + budget
    env = _data_probe_env() if env is None else {str(k): str(v) for k, v in env.items()}

    def finish(enabled, rows):
        return {"enabled": enabled, "providers": rows, "deadline_s": budget,
                "elapsed_s": round(time.monotonic() - started, 2)}

    if (env.get("DATA_SOURCES_ENABLED") or "true").strip().lower() != "true":
        return finish(False, {p: _data_probe_row(p, "disabled", "DATA_SOURCES_ENABLED=false", 0.0, env)
                              for p in _DATA_PROVIDERS})
    if not _DATA_PROBE_LOCK.acquire(blocking=False):
        raise DataProbeBusy("an official-data probe is already running")
    try:
        try:
            hub, client = (clients or _default_data_probe_clients)(env)
        except Exception as exc:  # noqa: BLE001 — 数据层缺失 = 全部不可用，不是 500
            logger.warning(f"官方数据源探活无法构建数据层: {type(exc).__name__}")
            detail = f"official-data layer unavailable ({type(exc).__name__})"
            return finish(True, {p: _data_probe_row(p, "unavailable", detail, 0.0, env)
                                 for p in _DATA_PROVIDERS})
        rows = {}
        try:
            try:
                statuses = client.providers() or {}
            except Exception:  # noqa: BLE001
                statuses = {}
            active = [p for p in _DATA_PROVIDERS if statuses.get(p) != "disabled"]
            for p in _DATA_PROVIDERS:
                if p not in active:
                    rows[p] = _data_probe_row(p, "disabled", "disabled by DATA_SOURCES", 0.0, env)
            if active:
                try:
                    hub.start(active)  # 并发握手；各 worker 再按剩余预算等待自己的服务
                except Exception:  # noqa: BLE001 — 各 worker 会再试一次并报告
                    pass
                pool = ThreadPoolExecutor(max_workers=len(active), thread_name_prefix="data-probe")
                futures = {p: pool.submit(_probe_data_provider, p, hub, client, deadline) for p in active}
                wait_futures(list(futures.values()),
                             timeout=max(0.0, deadline - time.monotonic()) + _DATA_TEST_GRACE_SECONDS)
                pool.shutdown(wait=False, cancel_futures=True)
                try:
                    after = client.providers() or {}
                except Exception:  # noqa: BLE001
                    after = {}
                for p in active:
                    future = futures[p]
                    if future.done() and not future.cancelled() and future.exception() is None:
                        rows[p] = _data_probe_state(p, future.result(), env, after.get(p) == "key_invalid")
                    else:
                        reason = ("probe deadline exceeded" if not future.done()
                                  else f"probe error ({type(future.exception()).__name__})")
                        rows[p] = _data_probe_row(p, "unavailable", reason,
                                                  time.monotonic() - started, env)
        finally:
            # The hub first, with the probe's own bound: DataSources.close() closes the same
            # hub with McpHub's default timeout, and the first close is the one that waits.
            for closer in (lambda: hub.close(timeout=_DATA_TEST_CLOSE_SECONDS), lambda: client.close()):
                try:
                    closer()
                except Exception:  # noqa: BLE001 — 关闭失败只记日志
                    logger.warning("官方数据源探活关闭私有 hub 失败")
        return finish(True, {p: rows[p] for p in _DATA_PROVIDERS})
    finally:
        _DATA_PROBE_LOCK.release()


@settings_bp.route('/data-sources/test', methods=['POST'])
def test_data_sources():
    """探活官方数据 MCP 服务（I4）。**不持久化**任何配置，不阻断任何运行。

    对每个启用的 provider 做 MCP 握手（initialize + list_tools），并取一条缓存优先的目录样本；
    BLS 只握手。墙钟上限 _DATA_TEST_MAX_SECONDS（约 90 s = 75 s 预算 + 2 s 收尾 + 私有 hub 关闭
    最多 13 s），客户端超时须不少于此（前端用 120 s）。

    返回 200 + data = {enabled, providers: {name: {state, detail, latency_s, keys}},
    deadline_s, elapsed_s}；state ∈ ok / degraded / unavailable / disabled，keys 只含 key 名与
    set / not set / invalid。另一探活进行中 → 409；服务端异常 → 500。
    """
    try:
        result = probe_data_sources()
    except DataProbeBusy:
        return jsonify({"success": False,
                        "error": "a data-source test is already running; retry when it finishes"}), 409
    except Exception as e:
        logger.error(f"官方数据源探活失败: {type(e).__name__}", exc_info=True)
        return jsonify({"success": False, "error": "internal server error"}), 500
    logger.info("官方数据源探活: " + ", ".join(
        f"{name}={row['state']}" for name, row in result["providers"].items()))
    return jsonify({"success": True, "data": result})
