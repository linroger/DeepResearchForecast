"""
LLM客户端封装

支持三种提供方（由 Config.LLM_PROVIDER 决定，默认 claude-cli）：
  - claude-cli: 通过本机 `claude` CLI 调用（Claude Code 订阅，无需 API Key）
  - codex-cli:  通过本机 `codex` CLI 调用（Codex 订阅，无需 API Key）
  - openai:     OpenAI 兼容 API（需要 LLM_API_KEY），保留作为回退

对外接口统一为 chat() / chat_json()，调用方无需关心底层提供方。
"""

import json
import os
import re
import subprocess
import time
from typing import Optional, Dict, Any, List

from ..config import Config
from .logger import get_logger

logger = get_logger('mirofish.llm_client')

# 单次 CLI 调用超时（秒）。从 300 降到 180 以便在模拟中卡住的 agent 调用更快释放并发槽；
# 仍足够长，可容纳报告章节这类长文生成。可用 LLM_CLI_TIMEOUT 覆盖（模拟密集场景可设 120）。
CLI_TIMEOUT = int(os.environ.get('LLM_CLI_TIMEOUT', '180'))

CLI_PROVIDERS = ('claude-cli', 'codex-cli')
# OpenAI 兼容的 HTTP 提供方（直接从 PROVIDER_META 的 openai_compat 标记派生，
# 新增提供方只需在 config.py 改一处：openai / kimi / minimax / deepseek / qwen / glm）
OPENAI_COMPATIBLE_PROVIDERS = tuple(
    pid for pid, meta in Config.PROVIDER_META.items() if meta.get('openai_compat')
)

# CLI 调用的瞬时失败重试配置
MAX_RETRIES = 3
RETRY_BASE_DELAY = 2.0  # 秒


class LLMClient:
    """LLM客户端 — 支持 claude-cli / codex-cli / openai"""

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None
    ):
        self.provider = (provider or Config.LLM_PROVIDER or "claude-cli").lower()

        # openai 提供方所需的连接参数（CLI 模式下不使用）
        self.api_key = api_key or Config.LLM_API_KEY
        self.base_url = base_url or Config.LLM_BASE_URL
        self.model = model or Config.LLM_MODEL_NAME

        if self.provider not in CLI_PROVIDERS and self.provider not in OPENAI_COMPATIBLE_PROVIDERS:
            _supported = " / ".join(repr(p) for p in (*CLI_PROVIDERS, *OPENAI_COMPATIBLE_PROVIDERS))
            raise ValueError(
                f"不支持的 LLM 提供方: {self.provider!r}。可选: {_supported}。"
            )

        # 仅在使用 OpenAI 兼容提供方（openai/kimi）时才创建 OpenAI 客户端（CLI 模式无需 API Key）
        self._openai_client = None
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            from openai import OpenAI
            if not self.api_key:
                raise ValueError(f"LLM_PROVIDER={self.provider} 时必须配置 LLM_API_KEY")
            client_kwargs: Dict[str, Any] = {"api_key": self.api_key, "base_url": self.base_url}
            # Kimi-for-coding 网关按 User-Agent 校验 coding-agent 身份；
            # 不带可识别的 UA 会被拒绝（access_terminated_error）。
            if self.provider == "kimi":
                client_kwargs["default_headers"] = {"User-Agent": Config.LLM_USER_AGENT}
            self._openai_client = OpenAI(**client_kwargs)

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------
    def chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: int = 4096,
        response_format: Optional[Dict] = None
    ) -> str:
        """
        发送聊天请求，返回模型响应文本。

        所有提供方在瞬时失败（RuntimeError，含 CLI 错误、超时、推理模型空 content）
        时自动指数退避重试（3 次）。OpenAI SDK 自身的 APIError 子类不在此重试范围，
        会按原样抛出（SDK 内部已有自己的重试与限流处理）。
        """
        last_error: Optional[Exception] = None
        for attempt in range(MAX_RETRIES):
            try:
                if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
                    return self._chat_openai(messages, temperature, max_tokens, response_format)
                if self.provider == "codex-cli":
                    return self._chat_codex_cli(messages, temperature, max_tokens, response_format)
                return self._chat_claude_cli(messages, temperature, max_tokens, response_format)
            except RuntimeError as exc:
                last_error = exc
                if attempt < MAX_RETRIES - 1:
                    delay = min(RETRY_BASE_DELAY * (2 ** attempt), 30)
                    logger.warning(
                        f"LLM 调用失败 (第 {attempt + 1}/{MAX_RETRIES} 次)，{delay}s 后重试: {exc}"
                    )
                    time.sleep(delay)
        raise last_error if last_error is not None else RuntimeError("LLM 调用失败")

    def chat_json(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.3,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """发送聊天请求并返回解析后的 JSON。

        解析失败时先做本地修复（提取 JSON 块、补全被 max_tokens 截断的括号），
        仍失败则降温重发一次。单次格式抖动不再让上层（如报告大纲）直接退化。
        """
        last_response = ""
        for attempt in range(2):
            response = self.chat(
                messages=messages,
                temperature=max(0.0, temperature - attempt * 0.2),
                max_tokens=max_tokens,
                response_format={"type": "json_object"}
            )
            last_response = response
            parsed = self._parse_json_response(response)
            if parsed is not None:
                return parsed
            if attempt == 0:
                logger.warning("chat_json 解析失败，降温重发一次")
        raise ValueError(f"LLM返回的JSON格式无效: {last_response[:500]}")

    @staticmethod
    def _parse_json_response(response: str) -> Optional[Dict[str, Any]]:
        """尽力把模型输出解析成 JSON 对象；失败返回 None（不抛异常）。"""
        cleaned = response.strip()
        # 清理 markdown 代码块标记
        cleaned = re.sub(r'^```(?:json)?\s*\n?', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        cleaned = cleaned.strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # 提取首个 JSON 对象（应对模型在 JSON 前后加说明文字）
        match = re.search(r'\{[\s\S]*\}', cleaned)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                cleaned = match.group()
        else:
            # 没有闭合的 '}'：截断式输出，从首个 '{' 起修复
            brace = cleaned.find('{')
            if brace < 0:
                return None
            cleaned = cleaned[brace:]

        # 补全被 max_tokens 截断的字符串/括号：扫描跟踪字符串态与括号栈，
        # 按嵌套逆序闭合（简单计数会按错误顺序拼接 ]} ）。
        stack: List[str] = []
        in_string = False
        escaped = False
        for ch in cleaned:
            if escaped:
                escaped = False
                continue
            if ch == '\\':
                escaped = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in '{[':
                stack.append(ch)
            elif ch == '}' and stack and stack[-1] == '{':
                stack.pop()
            elif ch == ']' and stack and stack[-1] == '[':
                stack.pop()

        repaired = cleaned
        if in_string:
            repaired += '"'
        # 去掉悬空的尾逗号（如 '{"a": 1,' 截断）
        repaired = re.sub(r',\s*$', '', repaired)
        for opener in reversed(stack):
            repaired += '}' if opener == '{' else ']'
        try:
            return json.loads(repaired)
        except json.JSONDecodeError:
            return None

    # ------------------------------------------------------------------
    # 共享辅助
    # ------------------------------------------------------------------
    def _split_system_message(self, messages: List[Dict[str, str]]):
        """从对话消息中拆分出 system 指令。"""
        system_text = None
        conversation = []
        for msg in messages:
            if msg.get("role") == "system":
                if system_text is None:
                    system_text = msg["content"]
                else:
                    system_text += "\n\n" + msg["content"]
            else:
                conversation.append(msg)
        return system_text, conversation

    def _flatten_prompt(
        self,
        messages: List[Dict[str, str]],
        response_format: Optional[Dict] = None
    ) -> str:
        """将多轮消息扁平化为单条 prompt（CLI 提供方使用）。"""
        system_text, conversation = self._split_system_message(messages)

        prompt_parts: List[str] = []
        if system_text:
            prompt_parts.append(f"SYSTEM INSTRUCTIONS:\n{system_text}\n")

        if response_format and response_format.get("type") == "json_object":
            prompt_parts.append(
                "IMPORTANT: Respond with valid JSON only. "
                "No markdown, no explanation, just pure JSON.\n"
            )

        for msg in conversation:
            role = msg.get("role", "user").upper()
            prompt_parts.append(f"{role}: {msg['content']}")

        return "\n\n".join(prompt_parts)

    def _clean_content(self, content: str) -> str:
        """移除推理模型的 <think> 标签。"""
        return re.sub(r'<think>[\s\S]*?</think>', '', content).strip()

    # ------------------------------------------------------------------
    # openai 提供方
    # ------------------------------------------------------------------
    def _chat_openai(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None
    ) -> str:
        kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if response_format:
            kwargs["response_format"] = response_format

        # 推理模型(kimi/minimax/deepseek/qwen/glm)：默认关闭推理，避免 reasoning 吃光
        # max_tokens 导致 content 为空。reasoning_extra_body() 对非推理提供方返回 None。
        extra_body = Config.reasoning_extra_body()
        if extra_body:
            kwargs["extra_body"] = extra_body

        response = self._openai_client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        content = choice.message.content
        # 推理模型在 content 被推理耗尽时会返回空串/None（finish_reason=length）。
        # 明确报错而不是把空串交给下游 JSON 解析，便于定位与重试。
        if content is None or not content.strip():
            finish = getattr(choice, "finish_reason", None)
            raise RuntimeError(
                f"OpenAI 兼容提供方({self.provider})返回空 content（finish_reason={finish}）。"
                f"若为 kimi/minimax 推理模型，请确认已关闭推理(LLM_{self.provider.upper()}_DISABLE_THINKING)或增大 max_tokens。"
            )
        return self._clean_content(content)

    # ------------------------------------------------------------------
    # claude-cli 提供方
    # ------------------------------------------------------------------
    @staticmethod
    def _claude_cli_env() -> Dict[str, str]:
        """claude-cli 子进程环境：默认剥离 ANTHROPIC_API_KEY。

        历史事故：环境里游离的 ANTHROPIC_API_KEY 会让 `claude` CLI 弃用订阅 OAuth
        改走 API 计费，且 Key 失效时表现为难排查的 401。订阅是本提供方的设计前提，
        故默认剥离；确需 API Key 计费时设 LLM_CLI_USE_API_KEY=true 保留。
        """
        env = dict(os.environ)
        if os.environ.get('LLM_CLI_USE_API_KEY', '').strip().lower() != 'true':
            env.pop('ANTHROPIC_API_KEY', None)
        return env

    def _chat_claude_cli(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None
    ) -> str:
        """通过 Claude Code CLI 调用。

        prompt 经 stdin 传入而非 argv：报告后期的长 prompt 会超 Linux 的 ARG_MAX
        （E2BIG），且 argv 会把 prompt 暴露在进程列表里。
        """
        prompt = self._flatten_prompt(messages, response_format)

        try:
            result = subprocess.run(
                ["claude", "-p", "--output-format", "json"],
                input=prompt,
                capture_output=True, text=True, timeout=CLI_TIMEOUT,
                cwd="/tmp", env=self._claude_cli_env()
            )

            if result.returncode != 0:
                logger.error(f"Claude CLI error: {result.stderr[:200]}")
                raise RuntimeError(f"Claude CLI failed: {result.stderr[:200]}")

            try:
                output = json.loads(result.stdout)
                # Detect error envelopes (e.g. is_error / non-success subtype) so the
                # caller's exponential-backoff retry kicks in instead of silently
                # propagating an empty/invalid result (often rate-limit induced).
                if isinstance(output, dict) and (
                    output.get("is_error") or output.get("subtype") not in (None, "success")
                ):
                    raise RuntimeError(
                        f"Claude CLI error envelope: subtype={output.get('subtype')!r} "
                        f"is_error={output.get('is_error')!r}"
                    )
                content = output.get("result", result.stdout) if isinstance(output, dict) else result.stdout
            except json.JSONDecodeError:
                content = result.stdout.strip()

            content = self._clean_content(content)
            if not content:
                raise RuntimeError("Claude CLI returned empty result")
            return content

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Claude CLI timed out after {CLI_TIMEOUT}s")
        except FileNotFoundError:
            raise RuntimeError(
                "未找到 `claude` 可执行文件，请确认已安装 Claude Code CLI 并加入 PATH"
            )
        except OSError as exc:
            raise RuntimeError(f"Claude CLI 进程启动失败: {exc}")

    # ------------------------------------------------------------------
    # codex-cli 提供方
    # ------------------------------------------------------------------
    def _chat_codex_cli(
        self,
        messages: List[Dict[str, str]],
        temperature: float,
        max_tokens: int,
        response_format: Optional[Dict] = None
    ) -> str:
        """通过 Codex CLI 调用。"""
        prompt = self._flatten_prompt(messages, response_format)

        try:
            result = subprocess.run(
                ["codex", "exec", "--skip-git-repo-check"],
                input=prompt,
                capture_output=True, text=True, timeout=CLI_TIMEOUT,
                cwd="/tmp"
            )

            if result.returncode != 0:
                logger.error(f"Codex CLI error: {result.stderr[:200]}")
                raise RuntimeError(f"Codex CLI failed: {result.stderr[:200]}")

            raw = result.stdout.strip()
            parts = raw.split("\ncodex\n")
            if len(parts) > 1:
                content = parts[-1].strip()
                lines = content.split("\n")
                clean_lines = []
                for line in lines:
                    if line.strip() == "tokens used":
                        break
                    clean_lines.append(line)
                content = "\n".join(clean_lines).strip()
            else:
                content = raw
            return self._clean_content(content)

        except subprocess.TimeoutExpired:
            raise RuntimeError(f"Codex CLI timed out after {CLI_TIMEOUT}s")
        except FileNotFoundError:
            raise RuntimeError(
                "未找到 `codex` 可执行文件，请确认已安装 Codex CLI 并加入 PATH"
            )
