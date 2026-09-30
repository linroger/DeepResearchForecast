"""在 OASIS/CAMEL 模拟中使用 CLI 后端 LLM 的辅助模块。

provider=claude-cli / codex-cli 时，返回一个把请求代理到本机 CLI 的
``CLIModel``（伪造成 OpenAI ChatCompletion 喂给模拟引擎）。

provider=openai 时，回退到原有的 ``ModelFactory`` OpenAI 路径，并保留
双 LLM（boost）加速配置。
"""

import asyncio
import json
import math
import os
import time
import uuid
from typing import Any, Dict, List

from camel.models.openai_model import OpenAIModel
from openai.types.chat.chat_completion import ChatCompletion

from ..config import Config
from .llm_client import LLMClient, CLI_PROVIDERS
from .logger import get_logger
from .provider_overrides import openai_compat_request_overrides

logger = get_logger('mirofish.oasis_llm')

# CLI 提供方(claude-cli/codex-cli)的并发上限。从 3 提到 8 以显著缩短每轮墙钟时间
# （每个 CLI 调用会 spawn 子进程，8 是吞吐与系统负载的稳妥平衡）。可用 OASIS_CLI_SEMAPHORE 覆盖。
DEFAULT_CLI_SEMAPHORE = 8
DEFAULT_OPENAI_SEMAPHORE = 30


# QUALITY-OPT S2-llm: the corpus had 1236 "the message at position N with role 'assistant'
# must not be empty" BadRequestErrors — a model returns empty content, camel appends it to the
# conversation, and the NEXT request 400s on the empty assistant turn (a cascade that collapses
# whole simulations). The reliable fix is to never let an empty assistant message reach the API:
# sanitize the outgoing message list, and never emit empty completion content.
_EMPTY_ASSISTANT_PLACEHOLDER = "(no response)"


def _env_or_config_flag(name: str, default: bool) -> bool:
    """布尔开关：优先读环境变量（模拟子进程注入点），其次 Config，最后 default。

    本文件不拥有 config.py，故用 getattr 兜底；解析失败一律回退 default，绝不抛出。
    """
    raw = os.environ.get(name)
    if raw is not None:
        return str(raw).strip().lower() in ("1", "true", "yes", "on")
    try:
        val = getattr(Config, name, None)
        if val is not None:
            if isinstance(val, str):
                return val.strip().lower() in ("1", "true", "yes", "on")
            return bool(val)
    except Exception:  # noqa: BLE001 — 配置读取失败退回默认值
        pass
    return default


def _tool_emulation_enabled() -> bool:
    """XRUN-2: CLI/文本回退路径的工具调用仿真开关（默认开）。"""
    return _env_or_config_flag("SIM_CLI_TOOL_EMULATION", True)


def _sim_llm_fallback_enabled() -> bool:
    """RUN-18: 模拟 openai/minimax 直连路径的 LLMClient 故障转移开关（默认开）。"""
    return _env_or_config_flag("SIM_LLM_FALLBACK", True)


# ---------------------------------------------------------------------------
# XRUN-2: 文本协议的工具调用仿真。OASIS agent 的所有动作都以 OpenAI tool_calls 表达；
# CLI 桥接与 LLMClient 回退路径没有原生 function calling，此前直接丢弃 tool schema，
# 整场模拟只剩种子 FOLLOW（空转）。仿真协议：把工具清单以 JSON 块附到 prompt 末尾，
# 要求模型只输出一个 {"tool": ..., "arguments": {...}} 对象，再解析回 tool_calls。
# 对话里已出现 role=tool 的结果消息时不再仿真（每个 step 只允许一次动作，防止 camel
# 的 tool 循环在文本协议下无界迭代）。解析失败一律退化为纯文本回复（今日行为）。
# ---------------------------------------------------------------------------
def _tool_schema_summaries(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把 OpenAI tools schema 压缩成 {name, description, parameters} 列表（容错跳过坏项）。"""
    out = []
    for t in tools or []:
        try:
            fn = t.get("function", t) if isinstance(t, dict) else {}
            name = fn.get("name")
            if not name:
                continue
            out.append({
                "name": name,
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {}),
            })
        except Exception:  # noqa: BLE001 — 单个坏 schema 不应放弃整个清单
            continue
    return out


def _tool_names(tools: List[Dict[str, Any]]) -> set:
    return {s["name"] for s in _tool_schema_summaries(tools)}


def _render_tool_prompt(tools: List[Dict[str, Any]]) -> str:
    """渲染附加到 prompt 末尾的工具调用指令块。"""
    schemas = _tool_schema_summaries(tools)
    lines = [
        "[TOOL CALLING] You must decide your next action by calling exactly ONE of the "
        "tools below. Reply with ONLY a single JSON object, no markdown, no extra text:",
        '{"tool": "<tool_name>", "arguments": { ... }}',
        'If none of the tools is appropriate, reply exactly: {"tool": null, "reply": "<brief reason>"}',
        "Available tools (JSON schemas):",
        json.dumps(schemas, ensure_ascii=False),
    ]
    return "\n".join(lines)


def _has_tool_result(messages: Any) -> bool:
    """对话中已含工具执行结果（camel 的后续轮）→ 本轮应给纯文本收尾，不再发起新调用。"""
    if not isinstance(messages, list):
        return False
    return any(isinstance(m, dict) and m.get("role") in ("tool", "function") for m in messages)


def _parse_tool_call_text(text: str, valid_names: set) -> tuple:
    """把模型的 JSON 输出解析回 (content, tool_calls)。

    tool_calls 为 [{"name": str, "arguments": dict}]；任何解析失败/工具名不合法
    都退化为 (原文, []) —— 与旧的"忽略工具"行为逐字节一致，绝不抛出。
    """
    try:
        from .llm_client import LLMClient
        payload = LLMClient._parse_json_response(text or "")
    except Exception:  # noqa: BLE001
        payload = None
    if isinstance(payload, dict):
        name = payload.get("tool") or payload.get("tool_name") or payload.get("name")
        if isinstance(name, str) and name in valid_names:
            args = payload.get("arguments")
            if not isinstance(args, dict):
                args = payload.get("args")
            if not isinstance(args, dict):
                args = {}
            reply = payload.get("reply")
            return (reply if isinstance(reply, str) else ""), [{"name": name, "arguments": args}]
        reply = payload.get("reply") or payload.get("content")
        if isinstance(reply, str) and reply.strip():
            return reply, []
    return (text or ""), []


def _estimate_tokens_of(value: Any) -> int:
    """粗估 token 数（长度/4），供伪造的 ChatCompletion usage 使用。"""
    if value is None:
        return 0
    if isinstance(value, str):
        return max(1, math.ceil(len(value) / 4)) if value else 0
    if isinstance(value, list):
        return sum(_estimate_tokens_of(item) for item in value)
    if isinstance(value, dict):
        return _estimate_tokens_of(json.dumps(value, ensure_ascii=False, default=str))
    return _estimate_tokens_of(str(value))


def _build_chat_completion(
    model_label: str,
    messages: List[Dict[str, Any]],
    content: str,
    tool_calls: List[Dict[str, Any]] | None = None,
) -> ChatCompletion:
    """把文本（含可选的仿真 tool_calls）伪装成 OpenAI ChatCompletion 喂给 camel。"""
    # S2-llm: never emit an empty assistant turn (would 400 the next request).
    if content is None or (isinstance(content, str) and not content.strip()):
        content = _EMPTY_ASSISTANT_PLACEHOLDER
    prompt_tokens = sum(_estimate_tokens_of(m.get('content')) for m in messages if isinstance(m, dict))
    completion_tokens = _estimate_tokens_of(content)

    message: Dict[str, Any] = {'role': 'assistant', 'content': content}
    finish_reason = 'stop'
    if tool_calls:
        message['tool_calls'] = [
            {
                'id': f'call_{uuid.uuid4().hex[:16]}',
                'type': 'function',
                'function': {
                    'name': tc['name'],
                    'arguments': json.dumps(tc.get('arguments') or {}, ensure_ascii=False),
                },
            }
            for tc in tool_calls
        ]
        finish_reason = 'tool_calls'

    return ChatCompletion.model_validate(
        {
            'id': f'chatcmpl-cli-{uuid.uuid4().hex[:24]}',
            'object': 'chat.completion',
            'created': int(time.time()),
            'model': model_label,
            'choices': [
                {
                    'index': 0,
                    'message': message,
                    'finish_reason': finish_reason,
                }
            ],
            'usage': {
                'prompt_tokens': prompt_tokens,
                'completion_tokens': completion_tokens,
                'total_tokens': prompt_tokens + completion_tokens,
            },
        }
    )


def _sanitize_messages(messages: Any) -> Any:
    """Replace empty/whitespace assistant content with a minimal placeholder so the provider
    never rejects the request. Returns a new list; non-list inputs pass through untouched."""
    if not isinstance(messages, list):
        return messages
    out = []
    for m in messages:
        if isinstance(m, dict) and m.get("role") == "assistant":
            c = m.get("content")
            if c is None or (isinstance(c, str) and not c.strip()):
                m = {**m, "content": _EMPTY_ASSISTANT_PLACEHOLDER}
        out.append(m)
    return out


def _wrap_openai_empty_guard(model):
    """Monkeypatch a camel OpenAIModel instance so every chat-completion request has its
    messages sanitized first (prevents the empty-assistant 400 cascade). Signature-agnostic."""
    try:
        _orig = model._request_chat_completion

        def _guarded(*args, **kwargs):
            if args:
                args = (_sanitize_messages(args[0]),) + tuple(args[1:])
            elif "messages" in kwargs:
                kwargs["messages"] = _sanitize_messages(kwargs["messages"])
            return _orig(*args, **kwargs)
        model._request_chat_completion = _guarded

        _aorig = getattr(model, "_arequest_chat_completion", None)
        if _aorig is not None:
            async def _aguarded(*args, **kwargs):
                if args:
                    args = (_sanitize_messages(args[0]),) + tuple(args[1:])
                elif "messages" in kwargs:
                    kwargs["messages"] = _sanitize_messages(kwargs["messages"])
                return await _aorig(*args, **kwargs)
            model._arequest_chat_completion = _aguarded
    except Exception:  # noqa: BLE001 — guard is additive; never block model creation
        pass
    return model


# ---------------------------------------------------------------------------
# RUN-18: 422 熔断器与 LLM_FALLBACK_PROVIDER 故障转移只存在于 LLMClient 内部，而
# provider=minimax/kimi/openai 时 OASIS 走 camel ModelFactory 直连 API —— 内容审查
# (422 new_sensitive) / 额度耗尽 (429) 会让整场模拟每个调用都失败且无回退（sim_440 空转
# 的复现机理）。此包装器在直连路径失败时把同一请求改经 LLMClient（自带重试、熔断与
# claude-cli 故障转移）。注意：回退产出若无仿真 tool_calls 则不会生成 agent 动作，
# 该轮在 run_summary 里仍如实呈现 hollow/低有机量，而非被"拯救"；回退次数单独计数。
# ---------------------------------------------------------------------------
_LLM_FALLBACK_STATS: Dict[str, int] = {"llm_fallback_calls": 0, "llm_fallback_tool_calls": 0}


def get_llm_fallback_stats() -> Dict[str, int]:
    """返回本进程内经 LLMClient 回退接管的模拟调用计数（诊断用）。"""
    return dict(_LLM_FALLBACK_STATS)


def _record_llm_fallback(provider: str, with_tool_call: bool, exc: Exception) -> None:
    """计数 + 落盘一条回退遥测（best-effort；模拟子进程 cwd 即 sim 目录）。"""
    _LLM_FALLBACK_STATS["llm_fallback_calls"] += 1
    if with_tool_call:
        _LLM_FALLBACK_STATS["llm_fallback_tool_calls"] += 1
    n = _LLM_FALLBACK_STATS["llm_fallback_calls"]
    if n == 1 or n % 25 == 0:
        logger.warning(
            f"OASIS {provider} 直连失败（{type(exc).__name__}），已由 LLMClient 回退接管"
            f"（累计 {n} 次，其中带工具调用 {_LLM_FALLBACK_STATS['llm_fallback_tool_calls']} 次；"
            f"无工具输出的回退轮不产生动作，run_summary 将如实呈现 hollow）"
        )
    try:
        cwd = os.getcwd()
        # 仅在确认处于模拟目录时写文件，避免在后端进程 cwd 下产生游离文件。
        # 文件名与 RUN-2 的 llm_health.json（按平台聚合的调用/失败计数）区分开。
        if os.path.exists(os.path.join(cwd, "simulation_config.json")):
            with open(os.path.join(cwd, "llm_fallback.jsonl"), "a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "ts": time.time(),
                    "event": "llm_fallback",
                    "provider": provider,
                    "tool_call": bool(with_tool_call),
                    "error": type(exc).__name__,
                }, ensure_ascii=False) + "\n")
    except OSError:
        pass


def _should_fallback_exc(exc: Exception) -> bool:
    """是否为值得转投回退链路的错误（内容审查/限流/额度）。复用 llm_client 的分类器。"""
    try:
        from .llm_client import _is_content_filter
        if _is_content_filter(exc):
            return True
    except Exception:  # noqa: BLE001 — 分类器不可用时退回字符串启发
        pass
    s = str(exc).lower()
    return ("429" in s or "rate_limit" in s or "quota" in s
            or "usage limit" in s or "new_sensitive" in s or "unprocessable" in s)


def _extract_messages_tools(args: tuple, kwargs: Dict[str, Any]) -> tuple:
    messages = args[0] if args else kwargs.get("messages")
    tools = args[1] if len(args) > 1 else kwargs.get("tools")
    return messages, tools


def _fallback_completion(model, provider: str, exc: Exception, *args, **kwargs) -> ChatCompletion:
    """把失败的直连请求改经 LLMClient 重发；回退也失败时抛出原始异常（今日行为）。"""
    messages, tools = _extract_messages_tools(args, kwargs)
    messages = _sanitize_messages(messages if isinstance(messages, list) else [])
    cfg = getattr(model, "model_config_dict", None) or {}
    temperature = float(cfg.get("temperature", 0.7) or 0.7)
    max_tokens = int(cfg.get("max_tokens", 4096) or 4096)

    llm = LLMClient(provider=provider)  # 自带重试、422 熔断与 LLM_FALLBACK_PROVIDER 故障转移
    tool_calls: List[Dict[str, Any]] = []
    try:
        if tools and _tool_emulation_enabled() and not _has_tool_result(messages):
            # 回退路径同样仿真工具调用，让 agent 仍能产生动作（否则回退轮必然 hollow）。
            content = llm.chat(
                messages=list(messages) + [{"role": "user", "content": _render_tool_prompt(tools)}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content, tool_calls = _parse_tool_call_text(content, _tool_names(tools))
        else:
            content = llm.chat(messages=messages, temperature=temperature, max_tokens=max_tokens)
    except Exception as fb_exc:  # noqa: BLE001 — 回退也失败：保留主路径的原始异常语义
        logger.error(f"OASIS {provider} 回退链路也失败: {type(fb_exc).__name__}: {str(fb_exc)[:160]}")
        raise exc
    _record_llm_fallback(provider, bool(tool_calls), exc)
    return _build_chat_completion(str(getattr(model, "model_type", provider)), messages, content, tool_calls)


def _wrap_openai_fallback_guard(model, provider: str):
    """给 camel OpenAIModel 直连路径加 LLMClient 故障转移（SIM_LLM_FALLBACK=false 时按原样抛错）。"""
    try:
        _orig = model._request_chat_completion

        def _guarded(*args, **kwargs):
            try:
                return _orig(*args, **kwargs)
            except Exception as exc:  # noqa: BLE001 — 仅拦截审查/限流类错误
                if not (_sim_llm_fallback_enabled() and _should_fallback_exc(exc)):
                    raise
                return _fallback_completion(model, provider, exc, *args, **kwargs)
        model._request_chat_completion = _guarded

        _aorig = getattr(model, "_arequest_chat_completion", None)
        if _aorig is not None:
            async def _aguarded(*args, **kwargs):
                try:
                    return await _aorig(*args, **kwargs)
                except Exception as exc:  # noqa: BLE001
                    if not (_sim_llm_fallback_enabled() and _should_fallback_exc(exc)):
                        raise
                    return await asyncio.to_thread(
                        _fallback_completion, model, provider, exc, *args, **kwargs
                    )
            model._arequest_chat_completion = _aguarded
    except Exception:  # noqa: BLE001 — guard is additive; never block model creation
        pass
    return model


class CLIModel(OpenAIModel):
    """把请求代理到 Claude/Codex CLI 的 CAMEL 模型后端。"""

    def __init__(
        self,
        model_type: str,
        provider: str,
        model_config_dict: Dict[str, Any] | None = None,
        api_key: str | None = None,
        url: str | None = None,
        timeout: float | None = None,
        max_retries: int = 3,
    ) -> None:
        self.provider = (provider or '').lower()
        self._llm = LLMClient(provider=self.provider)
        super().__init__(
            model_type=model_type,
            model_config_dict=model_config_dict,
            api_key=api_key or 'cli-bridge',
            url=url,
            timeout=timeout,
            max_retries=max_retries,
        )

    def _estimate_tokens(self, value: Any) -> int:
        return _estimate_tokens_of(value)

    def _build_completion(
        self,
        messages: List[Dict[str, Any]],
        content: str,
        tool_calls: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return _build_chat_completion(self.provider, messages, content, tool_calls)

    def _request_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        temperature = float((self.model_config_dict or {}).get('temperature', 0.7) or 0.7)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)
        messages = _sanitize_messages(messages)

        # XRUN-2: 仿真 function calling —— 否则 OASIS agent 在 CLI 桥接下无法产生任何动作
        # （历史空转 sim 的直接机理）。仿真失败/解析失败退化为纯文本回复，绝不中断模拟。
        if tools and _tool_emulation_enabled() and not _has_tool_result(messages):
            content = self._llm.chat(
                messages=list(messages) + [{"role": "user", "content": _render_tool_prompt(tools)}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content, tool_calls = _parse_tool_call_text(content, _tool_names(tools))
            if not tool_calls:
                logger.info('CLIModel 工具仿真未解析出调用，退化为纯文本回复')
            return self._build_completion(messages, content, tool_calls)

        if tools:
            logger.warning('CLIModel 忽略 tool schema（SIM_CLI_TOOL_EMULATION 已关闭）；agent 本轮不会产生动作')

        content = self._llm.chat(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._build_completion(messages, content)

    async def _arequest_chat_completion(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_chat_completion, messages, tools)

    def _request_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        if tools:
            logger.warning('CLIModel 在结构化输出请求中忽略 tool schema')

        temperature = float((self.model_config_dict or {}).get('temperature', 0.3) or 0.3)
        max_tokens = int((self.model_config_dict or {}).get('max_tokens', 4096) or 4096)
        messages = _sanitize_messages(messages)
        payload = self._llm.chat_json(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return self._build_completion(messages, json.dumps(payload, ensure_ascii=False))

    async def _arequest_parse(
        self,
        messages: List[Dict[str, Any]],
        response_format,
        tools: List[Dict[str, Any]] | None = None,
    ) -> ChatCompletion:
        return await asyncio.to_thread(self._request_parse, messages, response_format, tools)


def _resolve_provider(config: Dict[str, Any]) -> str:
    return (
        os.environ.get('LLM_PROVIDER')
        or config.get('llm_provider')
        or Config.LLM_PROVIDER
        or 'claude-cli'
    ).lower()


def _create_openai_model(config: Dict[str, Any], use_boost: bool = False):
    """provider=openai 时的原有 ModelFactory 路径（保留 boost 加速配置）。"""
    from camel.models import ModelFactory
    from camel.types import ModelPlatformType

    boost_api_key = os.environ.get("LLM_BOOST_API_KEY", "")
    boost_base_url = os.environ.get("LLM_BOOST_BASE_URL", "")
    boost_model = os.environ.get("LLM_BOOST_MODEL_NAME", "")
    has_boost_config = bool(boost_api_key)

    if use_boost and has_boost_config:
        llm_api_key = boost_api_key
        llm_base_url = boost_base_url
        llm_model = boost_model or os.environ.get("LLM_MODEL_NAME", "")
        config_label = "[加速LLM]"
    else:
        # 回退到 Config（其中已按 provider 编码了 kimi/minimax 的默认 base_url/model），
        # 这样仅在 .env 里设 LLM_PROVIDER=minimax + LLM_API_KEY、不显式给 base_url/model，
        # 也能正确指向 MiniMax 端点与 MiniMax-M3 模型（修复 OASIS 直读 os.environ 的盲点）。
        llm_api_key = os.environ.get("LLM_API_KEY", "") or (Config.LLM_API_KEY or "")
        llm_base_url = os.environ.get("LLM_BASE_URL", "") or (Config.LLM_BASE_URL or "")
        llm_model = os.environ.get("LLM_MODEL_NAME", "") or (Config.LLM_MODEL_NAME or "")
        config_label = "[通用LLM]"

    if not llm_model:
        llm_model = config.get("llm_model", "gpt-4o-mini")

    # 修复（B9）：把 api_key/url 直接传给 ModelFactory.create，不再写进程全局 os.environ。
    # 此前对 OPENAI_API_KEY/OPENAI_API_BASE_URL 的全局写在 twitter+reddit 并发建模（boost 与
    # 通用 key 交替）时会相互覆盖。仍把既有 OPENAI_* 环境变量作为回退读取，仅不再写它。
    eff_api_key = llm_api_key or os.environ.get("OPENAI_API_KEY", "")
    eff_base_url = llm_base_url or os.environ.get("OPENAI_API_BASE_URL", "")
    if not eff_api_key:
        raise ValueError("缺少 API Key 配置，请在项目根目录 .env 文件中设置 LLM_API_KEY")

    logger.info(f"OASIS model: {config_label} model={llm_model}, mode=openai")
    _m = ModelFactory.create(
        model_platform=ModelPlatformType.OPENAI,
        model_type=llm_model,
        api_key=eff_api_key,
        url=eff_base_url or None,
    )
    return _wrap_openai_empty_guard(_m)  # S2-llm: prevent empty-assistant 400 cascade


def _inject_coding_agent_ua(model, provider: str = 'kimi') -> None:
    """为 CAMEL OpenAIModel 注入 ``provider`` 的默认请求头（Kimi-for-coding 的 coding-agent UA）。

    CAMEL 的 ``ModelFactory.create`` / ``OpenAIModel`` 不会把 ``default_headers``
    透传到底层 ``openai`` 客户端，因此在模型创建后直接用带头的客户端替换
    ``_client`` / ``_async_client``（同步与异步路径都要替换）。INFRA-6: 头部取自
    provider_overrides（与 LLMClient 同源）；该提供方没有默认头时不替换客户端。
    """
    headers = openai_compat_request_overrides(provider)["default_headers"]
    if not headers:
        return
    from openai import OpenAI, AsyncOpenAI

    common: Dict[str, Any] = {
        "timeout": model._timeout,
        "max_retries": model._max_retries,
        "base_url": model._url,
        "api_key": model._api_key,
        "default_headers": headers,
    }
    model._client = OpenAI(**common)
    model._async_client = AsyncOpenAI(**common)
    logger.info(f"OASIS {provider}: 已为 OpenAI 客户端注入 coding-agent UA='{headers.get('User-Agent')}'")


def create_oasis_model(config: Dict[str, Any], use_boost: bool = False):
    """创建 OASIS 模拟所用的 CAMEL 模型。

    provider=claude-cli/codex-cli -> CLIModel（CLI 桥接）
    provider=openai               -> ModelFactory OpenAI 路径（含 boost）
    provider=kimi                 -> ModelFactory OpenAI 路径 + 注入 coding-agent UA + 关闭推理
    provider=minimax              -> ModelFactory OpenAI 路径 + 关闭推理（无需 UA）
    """
    provider = _resolve_provider(config)

    if provider in CLI_PROVIDERS:
        model = config.get('llm_model') or provider
        logger.info(f"OASIS model: provider={provider}, model={model}, mode=cli-bridge")
        # XRUN-2: cli-bridge 且工具仿真被关闭 → agent 无法产生任何动作，整场模拟必然空转。
        # 在建模时就把退化喊出来，而不是 24 轮后才从 run_summary 发现 hollow。
        if not _tool_emulation_enabled():
            logger.warning(
                "SIM_CLI_TOOL_EMULATION 已关闭且 provider=cli-bridge：OASIS agent 将无法发出任何"
                "工具调用（动作），run 阶段将呈现 hollow —— 请确认这是有意为之"
            )
        return CLIModel(
            model_type=model,
            provider=provider,
            model_config_dict={},
            api_key='cli-bridge',
        )

    model = _create_openai_model(config, use_boost=use_boost)
    # INFRA-6: the overrides below (UA, extra_body, fallback guard) follow the resolved provider,
    # but _create_openai_model takes base_url/model from LLM_BASE_URL/LLM_MODEL_NAME (env, else
    # the global Config provider's endpoint). When only the simulation config names a provider
    # other than the global one, the two can belong to different providers: warn, do not guess.
    global_provider = (Config.LLM_PROVIDER or '').strip().lower()
    if not os.environ.get('LLM_PROVIDER') and global_provider and provider != global_provider:
        logger.warning(
            f"OASIS: 模拟配置 llm_provider={provider} 与全局 LLM_PROVIDER={global_provider} 不一致且未设置"
            f"环境变量 LLM_PROVIDER：UA/extra_body/故障转移按 {provider}，base_url/model 却取自 "
            f"LLM_BASE_URL/LLM_MODEL_NAME，二者可能分属不同提供方——请设置 LLM_PROVIDER 或重新准备模拟"
        )
    # 仅 Kimi-for-coding 网关按 UA 校验 coding-agent 身份；其它提供方没有默认头，不替换客户端。
    _inject_coding_agent_ua(model, provider)
    # 推理模型(kimi/minimax/deepseek/qwen/glm)默认关闭推理，避免 reasoning 吃光 token 预算
    # 导致 content 为空。非推理提供方的 extra_body 为空，不注入。
    # CAMEL 会把 model_config_dict 透传为 create() 关键字参数，故注入 extra_body。
    # INFRA-6: 按 _resolve_provider 解析出的提供方取 extra_body（此前无参调用读的是全局
    # Config.LLM_PROVIDER，模拟提供方与全局主提供方不同时发错推理开关体）。
    extra_body = openai_compat_request_overrides(provider)["extra_body"]
    if extra_body:
        try:
            model.model_config_dict["extra_body"] = extra_body
            logger.info(f"OASIS {provider}: 已关闭推理 via model_config_dict.extra_body={extra_body}")
        except Exception as e:
            logger.warning(f"OASIS {provider}: 注入 extra_body 失败（继续，但可能触发空 content）: {e}")
    # RUN-18: 直连路径接入 LLMClient 故障转移（内容审查/限流时才触发；SIM_LLM_FALLBACK=false 关闭）。
    model = _wrap_openai_fallback_guard(model, provider)
    return model


def get_oasis_semaphore(config: Dict[str, Any], use_boost: bool = False, platforms: int = 1) -> int:
    """根据提供方返回合适的 OASIS 并发上限。

    Args:
        platforms: 同进程内并发运行的平台数。双平台并行时各平台拿到 cap/2，
            使全局在飞 LLM 请求数符合 OASIS_*SEMAPHORE 的文档语义（此前
            Twitter、Reddit 各拿一整份，实际并发是配置值的 2 倍）。
    """
    provider = _resolve_provider(config)
    if provider in CLI_PROVIDERS:
        cap = int(os.environ.get('OASIS_CLI_SEMAPHORE', str(DEFAULT_CLI_SEMAPHORE)))
    else:
        cap = int(os.environ.get('OASIS_SEMAPHORE', str(DEFAULT_OPENAI_SEMAPHORE)))
    return max(1, cap // max(1, platforms))
