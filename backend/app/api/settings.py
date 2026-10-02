"""设置 API：运行时查询/切换/测试 LLM 模型提供方。

路由（挂载于 /api/settings）：
    GET  /llm        当前提供方 + 受支持提供方清单（含展示元数据）
    POST /llm        切换提供方 {provider, api_key?, base_url?, model?}；对新发起的管线生效；
                     data.env_persisted / data.env_persist_error 报告 .env 是否落盘
    POST /llm/test   测试连通性 {provider, api_key?, base_url?, model?}；不持久化任何配置

切换是运行时的：更新 Config 类属性 + os.environ（DeerFlow 子进程继承），并 upsert 进 .env。
已在运行中的管线不受影响（它们已读取旧配置）。
"""

import shutil
import subprocess
import time

from flask import jsonify, request

from . import settings_bp
from ..config import Config
from ..utils.logger import get_logger
from ..utils.provider_overrides import openai_compat_request_overrides

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
        # data.env_persisted / data.env_persist_error tell the client whether the switch
        # survives a restart: the runtime switch applies either way, .env may not have.
        if not info.get('env_persisted', True):
            logger.warning(
                f"LLM 提供方已在运行时切换，但写入 .env 失败（{info.get('env_persist_error')}）：重启后将恢复旧配置"
            )
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

    # INFRA-6: 请求头 / 推理开关体 / 温度规则与生产调用同源（provider_overrides）。
    # 推理提供方：测试时一律关闭推理（force_disable_thinking），避免 reasoning 吃光 max_tokens
    # 导致空 content；温度用 0，Kimi K2.7 Code 网关只接受关推理时的 0.6（0 会 400，前端
    # 「测试连接」会把 kimi 误报为失败），由同一规则修正。
    overrides = openai_compat_request_overrides(provider, 0, force_disable_thinking=True)
    client_kwargs = {
        "api_key": api_key,
        "base_url": base_url,
        "timeout": _TEST_TIMEOUT_SECONDS,
        "max_retries": 0,
    }
    # Kimi-for-coding 网关按 User-Agent 校验 coding-agent 身份（详见 llm_client.py）。
    if overrides["default_headers"]:
        client_kwargs["default_headers"] = overrides["default_headers"]

    kwargs = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
        "temperature": overrides["temperature"],
        "max_tokens": 16,
    }
    if overrides["extra_body"]:
        kwargs["extra_body"] = overrides["extra_body"]

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
