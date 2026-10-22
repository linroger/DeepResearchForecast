# llm-telemetry — LLM client, token budget, telemetry, file parser

Slice (branch `main`, read in full from disk on 2026-10-11):

| File | Lines | Role |
|---|---|---|
| `backend/app/utils/llm_client.py` | 1135 | `LLMClient`, the one synchronous LLM interface for pipeline generation (ontology, profiles, sim config, report, graph extraction, translation). It covers provider dispatch (claude-cli / codex-cli subprocess, or OpenAI-compatible HTTP), retries, 422/429 circuit breakers, single-hop provider failover, JSON repair, native tool calling, and metering hooks. |
| `backend/app/utils/telemetry.py` | 594 | Process-wide LLM meter (`LLMMeter`), run/stage correlation through contextvars, single-active-run fallback attribution, the cost model, the per-run budget guard, the stage-telemetry builder and Markdown appendix renderer, and the content-addressed response cache (`LLMCache`). |
| `backend/app/utils/token_budget.py` | 174 | Pure, never-raising helpers. They turn fixed character slices into budgets sized to the provider's context window (RQ-7 / `ADAPTIVE_CONTEXT`). |
| `backend/app/utils/file_parser.py` | 192 | Extracts text from uploaded PDF/MD/TXT files (with encoding detection) and splits it into overlapping, sentence-aware chunks. |

**Anchor convention.** `llm_client.py:N`, `telemetry.py:N`, `token_budget.py:N` and `file_parser.py:N` mean `backend/app/utils/<file>:N`. Every other anchor is a full path relative to the repo root.

**What is *not* here.** There is no Anthropic prompt caching (`cache_control`) anywhere in `LLMClient`. Research-stage prompt caching lives in the DeerFlow bridge patches (`backend/tests/test_claude_prompt_cache.py:1-9`). The only "cache" in this slice is `LLMCache`, an in-process **response** cache (`telemetry.py:536-594`). Model selection "per role" works through a `tier` argument (`'fast'` / `'strong'`) that callers pass (`llm_client.py:356-374`). This slice has no role-to-model table.

---

## Purpose & position in the pipeline

- **`LLMClient` is the transport for every non-research, non-OASIS-native LLM call in the backend process.** The ontology generator (`backend/app/services/ontology_generator.py:480`), the OASIS profile generator (`backend/app/services/oasis_profile_generator.py:370-375`), the simulation config generator (`backend/app/services/simulation_config_generator.py:448-453`), the report agent (`backend/app/services/report_agent.py:1671`), the Zep tools (`backend/app/services/zep_tools.py:577`) and the forecast extractor's ensemble draws (`backend/app/services/forecast_extractor.py:2606-2617`) all build one. Graphiti graph extraction wraps one in `AppGraphitiLLMClient` (`backend/app/services/graphiti_client/llm_adapter.py:33,111,169-173`). The OASIS bridge uses it for CLI providers and as a failover path (`backend/app/utils/oasis_llm.py:22,328,393`). The simulation subprocess uses it for decision/evolution channels (`backend/scripts/run_parallel_simulation.py:3444-3446,5989-6005`). The research stage does **not** use it: DeerFlow has its own model factory.
- **Telemetry is the spend ledger.** Every `LLMClient.chat()` / `chat_with_tools()` call records into `LLMMeter`, keyed by the run id and stage held in contextvars (`llm_client.py:422-423,507-517,735-744`). `PipelineOrchestrator._run` sets the run id (`backend/app/services/pipeline_orchestrator.py:11887-11888`). Each stage updater sets the stage (`backend/app/services/pipeline_orchestrator.py:8950-8956`). The orchestrator also records research-stage and sim-subprocess usage into the meter itself, because that spend happens out of process (`backend/app/services/pipeline_orchestrator.py:2069-2085,10453-10465,10544-10553`). The orchestrator persists the meter as `run_telemetry.json` (incremental and final) and `telemetry.json` (stage × calls/tokens/cost/wall), and resets it when the run ends (`backend/app/services/pipeline_orchestrator.py:7559,7575-7614,13399-13483`).
- **`token_budget`** sizes three prompt slices in production: prior report sections (`backend/app/services/report_agent.py:2346-2369`), persona context (`backend/app/services/oasis_profile_generator.py:1948-1963`) and the simulation world brief (`backend/app/services/simulation_config_generator.py:1918-1937`).
- **`file_parser`** is the first step of the legacy upload flow. `POST /api/graph/ontology/generate` saves the uploads and calls `FileParser.extract_text` per file (`backend/app/api/graph.py:121-122,184-200`). `split_text_into_chunks` is the chunker behind `TextProcessor.split_text` (`backend/app/services/text_processor.py:23-49`). That method is used by graph build (`backend/app/services/graph_builder.py:1161`), the orchestrator's dossier chunking (`backend/app/services/pipeline_orchestrator.py:1323`) and `/api/graph/build` (`backend/app/api/graph.py:393`).

---

## Walkthrough (source order)

### 1. `backend/app/utils/llm_client.py`

**Module header and constants**

- **Module docstring** (`llm_client.py:1-10`): lists only three providers (claude-cli default, codex-cli, openai). This is stale: see Surprises.
- **Imports** (`llm_client.py:12-25`): `subprocess`, `threading`, `contextvars`, `Config`, and the logger `mirofish.llm_client`.
- **`CLI_TIMEOUT`** (`llm_client.py:29`): `int(os.environ.get('LLM_CLI_TIMEOUT','180'))`. It is read **once at import** and bounds each `claude`/`codex` subprocess.
- **`CLI_PROVIDERS = ('claude-cli','codex-cli')`** (`llm_client.py:31`).
- **`OPENAI_COMPATIBLE_PROVIDERS`** (`llm_client.py:34-41`): every `Config.PROVIDER_META` key with `openai_compat=True` (`openai, kimi, minimax, deepseek, qwen, glm`, `backend/app/config.py:858-877`) plus the fallback-only identity `'antigravity'`, which is deliberately absent from `PROVIDER_META`. The tuple is computed at import, so it is static even though `Config.apply_provider` can switch providers at runtime.
- **Retry constants** (`llm_client.py:44-46`): `MAX_RETRIES=3`, `RETRY_BASE_DELAY=2.0`s, `RETRY_AFTER_CAP=30.0`s.
- **`_RETRYABLE_API_ERRORS`** (`llm_client.py:53-62`): `(openai.RateLimitError, APITimeoutError, APIConnectionError, InternalServerError)`. It is an empty tuple if `openai` cannot be imported. 400/401/404/422 SDK errors are deliberately **not** included.

**Per-context request timeout**

- **`_CALL_TIMEOUT_S`** ContextVar (`llm_client.py:68-70`) and the **`llm_call_timeout(seconds)`** context manager (`llm_client.py:73-88`). Inside the block, `_chat_openai` passes `timeout=<seconds>` to `chat.completions.create` (`llm_client.py:946-948`). `None`/0/non-numeric/negative values mean "client default". The override applies only to the OpenAI-compatible `chat()` path: not to CLI providers and not to `chat_with_tools`. Its one production user is the report translation path, `with LLMCache.bypass(), llm_call_timeout(REPORT_TRANSLATION_CALL_TIMEOUT_S=240)` (`backend/app/services/report_agent.py:7431-7433,7741`).

**Error classification helpers**

- **`_err_brief(exc)`** (`llm_client.py:91-101`): a one-line label for logs. It returns `content-filter(422)` if the text has `new_sensitive` or both `content` and `filter`; `quota/rate-limit(429)` if it has `429`/`rate_limit`/`quota`/`usage limit`; otherwise the exception type name. The label is followed by the first 160 characters of the message.
- **`_is_content_filter(exc)`** (`llm_client.py:126-129`): a case-insensitive substring test for `new_sensitive`, `unprocessable`, `content`+`filter`, `" 422"` or `"code: 422"`.
- **`_is_quota(exc)`** (`llm_client.py:145-149`): a substring test for `429`, `rate_limit`, `rate limit`, `quota` or `usage limit`. The orchestrator's outage classifier imports it (`backend/app/services/pipeline_orchestrator.py:420-436`).
- **`_is_deterministic_auth_error(exc)`** (`llm_client.py:198-208`): matches `authenticationerror`, `invalid authentication credentials`, `failed to authenticate`, `api_error_status":401` / `': 401`, or the regex `(error|status|code).{0,24}\b401\b`. The orchestrator also imports it (`backend/app/services/pipeline_orchestrator.py:422-428`).
- **`_is_deterministic_invalid_request_error(exc)`** (`llm_client.py:211-226`): matches `exc.status_code == 400`, `badrequesterror`, `unknown provider for model`, `model_not_found`, `invalid_request_error`, or the regex `(error|status|code).{0,24}\b400\b`. It is used only to put a failed fallback into cooldown.
- **`_retry_delay(exc, attempt)`** (`llm_client.py:233-244`): the default is `2.0 * 2**attempt` (2 s, then 4 s). If `exc.response.headers` has `retry-after`, it returns `min(max(base, retry_after), 30.0)`.

**Circuit breakers (process-global, keyed by provider name)**

- **State** (`llm_client.py:109-123`): `_CB_STATE: {provider: {"consec", "consec429", "tripped_until"}}`, guarded by `_CB_LOCK` (a `threading.Lock`; the comment at `:110-114` records a lost-update bug that the lock fixed). `_CB_THRESHOLD = max(1, LLM_CB_422_THRESHOLD or 5)`. `_CB_COOLDOWN_S = LLM_CB_COOLDOWN_S or 300`. Bad values fall back to the defaults.
- **429 breaker** (`llm_client.py:135-142`): `_CB_429_THRESHOLD = max(1, LLM_CB_429_THRESHOLD or 8)`, `_CB_429_COOLDOWN_S = LLM_CB_429_COOLDOWN_S or 120`. All four knobs are read **at import**.
- **`_cb_tripped(provider)`** (`llm_client.py:152-155`): `tripped_until > time.monotonic()`.
- **`_cb_record_422(provider)`** (`llm_client.py:158-165`): `consec += 1`. When `consec >= threshold` and the breaker is not already tripped, it sets `tripped_until = now + 300` and logs a warning.
- **`_cb_record_429(provider)`** (`llm_client.py:168-176`): the same, on `consec429` with threshold 8 and a 120 s cooldown. Both kinds share the one `tripped_until`.
- **`_cb_reset(provider)`** (`llm_client.py:179-184`): zeroes both counters. It is called only when a primary call **succeeds** (`llm_client.py:470,715`). It does not touch `tripped_until`.
- **Failover caches** (`llm_client.py:190-195,230`):
  - `_FB_OPENAI_CLIENTS[(provider, model, base_url)]`: reuses fallback OpenAI SDK clients.
  - `_FB_AUTH_UNAVAILABLE_UNTIL[(provider, model or "", base_url or "")]`: deterministic-failure cooldown, `_FB_AUTH_COOLDOWN_S = 900.0`.
  - `_FB_MISCONFIG_WARNED`: a set used to warn once per process.

**`class LLMClient`** (`llm_client.py:247`)

- **`__init__(provider=None, api_key=None, base_url=None, model=None)`** (`llm_client.py:250-283`):
  - `provider = (provider or Config.LLM_PROVIDER or "claude-cli").lower()`.
  - `api_key`, `base_url` and `model` each fall back to `Config.LLM_API_KEY`, `Config.LLM_BASE_URL` and `Config.LLM_MODEL_NAME` (`:263-265`).
  - It raises `ValueError` for a provider in neither family (`:267-271`).
  - Only for OpenAI-compatible providers does it build `self._openai_client` (`:274-276`). That build raises `ValueError` if no API key resolves (`:289-290`).
  - It initialises `_last_usage=None`, `_fast_openai_client=None` and `_is_fallback=False` (`:260,281,283`).
- **`_build_openai_client(provider, api_key, base_url)`** (static, `llm_client.py:285-314`):
  - Builds `openai.OpenAI(api_key, base_url, timeout=600)`. The timeout comes from `getattr(Config, "LLM_HTTP_TIMEOUT_S", 600.0)`, and that attribute does not exist in `Config`.
  - When `provider == "kimi"`, it adds `default_headers={"User-Agent": Config.LLM_USER_AGENT}` (default `claude-cli/1.0.0`, `backend/app/config.py:803`).
  - If `_build_http_client()` returns a client, it injects it as `http_client` and sets `max_retries=0`, so the SDK's own retries are off and `chat()` owns backoff (`:310-313`).
- **`_build_http_client()`** (static, `llm_client.py:316-351`):
  - Returns `None` unless `Config.LLM_HTTP2` (default **True**, `backend/app/config.py:79`).
  - Otherwise returns `httpx.Client(http2=True, limits=Limits(max_keepalive_connections=K, max_connections=K+32), timeout=Timeout(600, connect=10))`, with `K = LLM_HTTP_KEEPALIVE` (default 128).
  - If that fails, it retries with `http2=False`. If that fails too, it returns `None` (the SDK default client).
- **`_model_for_tier(tier)`** (`llm_client.py:356-374`):
  - A fallback client always returns `self.model` (`:368-369`).
  - If `Config.LLM_TIERED_ROUTING` is false, it returns `self.model`.
  - Otherwise `'fast'` returns `Config.fast_model() or self.model`, and anything else returns `Config.strong_model() or self.model`. `fast_model()` is `LLM_FAST_MODEL or LLM_MODEL_NAME`; `strong_model()` is `LLM_STRONG_MODEL or LLM_MODEL_NAME` (`backend/app/config.py:145-152`).
  - `LLM_TIERED_ROUTING` defaults to **True** (`backend/app/config.py:92`). As a result, a non-fallback client normally sends the **global** `Config` model name, not its own `self.model`. See Surprises.
- **`_fast_provider_client()`** (`llm_client.py:376-394`): needs `LLM_FAST_PROVIDER`, `LLM_FAST_BASE_URL` and `LLM_FAST_API_KEY` all set, with the provider OpenAI-compatible. It then lazily builds and caches a second SDK client on the instance. Any build error is logged and returns `None`, which falls back to the primary client.

**`chat(messages, temperature=0.7, max_tokens=4096, response_format=None, tier="strong") -> str`** (`llm_client.py:399-522`). This is the central path, in order:

1. `model = self._model_for_tier(tier)` (`:419`). It lazy-imports `LLMMeter, LLMCache, get_run_context, check_budget, estimate_tokens` from telemetry and reads `(run_id, stage)` (`:422-423`).
2. **Cache.** If `Config.LLM_CACHE_ENABLED` (default **True**, `backend/app/config.py:62`), it computes `LLMCache.key(provider, model, messages, temperature, max_tokens, response_format)`. On a hit it records a `cached=True` meter row with 0 tokens (only if telemetry is on) and returns at once (`:425-432`). No budget check and no outage-breaker accounting happen on that path.
3. Resets `served_by_fallback=False`, `started=monotonic()` and `self._last_usage=None` (`:439-441`).
4. **Breaker pre-check** (`:444-458`). If the primary is tripped and this is not a fallback client, it calls `_try_fallback(...)` with a synthetic `RuntimeError("circuit-breaker: … in 422/429 cooldown")`. On success it uses that result. If the fallback returns `None`, it **raises** `RuntimeError("LLM 调用失败：主提供方 … 处于 422/429 熔断冷却，且回退提供方不可用")`. The primary is never attempted during the cooldown.
5. **Retry loop**, `for attempt in range(3)` (`:459-493`). It dispatches to `_chat_openai` (OpenAI-compatible, with `tier`), `_chat_codex_cli` or `_chat_claude_cli`. On success it calls `_cb_reset` and breaks.
   - `except (RuntimeError, *_RETRYABLE_API_ERRORS)` (`:472-487`):
     - A deterministic auth error logs a warning and breaks with no further retries.
     - If `_is_quota`, it calls `_cb_record_429`. This counts **every attempt**.
     - Otherwise, when attempt < 2, it sleeps `_retry_delay`. The final attempt does not sleep.
   - `except Exception` (`:488-493`), meaning not retryable (for example `openai.UnprocessableEntityError` 422, `AuthenticationError` 401 or `BadRequestError` 400): if `_is_content_filter`, it calls `_cb_record_422`. It logs and breaks.
6. **Failover** (`:494-505`). If there is still no result, it calls `_try_fallback(..., last_error)`. On success `served_by_fallback=True`. Otherwise it raises `last_error`, or `RuntimeError("LLM 调用失败")` if that is `None`.
7. **Metering** (`:507-517`). This runs only if `LLM_TELEMETRY_ENABLED` (default True, `backend/app/config.py:58`) **and not** served by fallback; the fallback client's own `chat()` already metered under its own provider. `prompt_tokens`/`completion_tokens` come from `self._last_usage` when the OpenAI path filled it. Otherwise (CLI) they are estimated as `len(text)//4` per message and for the result. It records `LLMMeter.record(provider, model, pt, ct, latency_ms, cached=False, stage, run_id)`.
8. **Cache write** (`:518-519`): `LLMCache.put(cache_key, result)`, including fallback-served results under the primary's key.
9. **Budget** (`:520-521`): if `LLM_RUN_BUDGET_TOKENS` or `LLM_RUN_BUDGET_USD` is non-zero, it calls `check_budget(run_id)`, which may raise `BudgetExceeded` **after** the call has already been paid for.
10. Returns `result` (`:522`).

**`_try_fallback(messages, temperature, max_tokens, response_format, primary_error) -> Optional[str]`** (`llm_client.py:524-595`)

- Returns `None` when `self._is_fallback` (no recursion, `:530-531`), when `LLM_FALLBACK_PROVIDER` is empty, or when it equals `self.provider` (`:532-534`). The env vars are read **live** from `os.environ` on every call.
- **Misconfiguration guard** (`:542-552`): if `LLM_FALLBACK_MODEL` is unset and the fallback is OpenAI-compatible, it refuses (warning once per provider) and returns `None`. Inheriting the primary's model name produced a guaranteed 400 in production. A CLI fallback is allowed with no model.
- **Deterministic cooldown check** (`:553-561`): if `_FB_AUTH_UNAVAILABLE_UNTIL[key] > now`, it skips with a warning and returns `None`.
- Builds `LLMClient(provider=fb, model=LLM_FALLBACK_MODEL, api_key=LLM_FALLBACK_API_KEY or None, base_url=LLM_FALLBACK_BASE_URL or None)` and sets `fb._is_fallback=True` (`:563-569`). An unset key or base_url silently inherits the **primary's** `Config.LLM_API_KEY` / `LLM_BASE_URL` through `__init__` (`:263-264`).
- **Pool reuse** (`:572-578`): stores or swaps `fb._openai_client` from `_FB_OPENAI_CLIENTS`.
- Calls `fb.chat(messages, temperature, max_tokens, response_format)` without `tier`. On success it clears the cooldown key and returns the text (`:581-585`).
- `except Exception` (`:586-595`): on a deterministic auth or invalid-request error, it sets a 900 s cooldown for that `(provider, model, base_url)`. It logs an error and returns `None`. **Every** exception is swallowed here, including `BudgetExceeded` raised inside `fb.chat` (see Surprises).

**`chat_json(messages, temperature=0.3, max_tokens=4096, tier="strong") -> Dict`** (`llm_client.py:597-627`)

- Makes 2 attempts. Each one calls `self.chat(..., temperature=max(0, temperature - 0.2*attempt), response_format={"type":"json_object"}, tier)` and then `_parse_json_response`. It returns the first non-`None` parse (`:613-624`). Otherwise it raises `ValueError("LLM返回的JSON格式无效: <first 500 chars>")` (`:627`).
- Since each `chat()` retries 3 times and may fail over, one `chat_json` can issue up to 2 × (3 primary + 3 fallback) = 12 provider calls.
- The return type is not enforced. A top-level JSON array or scalar is returned as is.

**Native tools**

- **`supports_native_tools()`** (`llm_client.py:632-656`) is True only when all of these hold:
  - `Config.REPORT_NATIVE_TOOLS` is on (default true, `backend/app/config.py:1528`);
  - the provider is OpenAI-compatible and the SDK client exists;
  - the provider is in the comma-separated `LLM_NATIVE_TOOLS_PROVIDERS` override if that is set, or else `PROVIDER_META[provider].get('native_tools', True)` (MiniMax sets False, `backend/app/config.py:868-870`);
  - the breaker is **not** tripped.
- **`chat_with_tools(messages, tools_schema, temperature=0.4, max_tokens=4096, tier="strong")`** (`llm_client.py:658-759`):
  - Raises `RuntimeError` if there is no SDK client (`:677-678`) or the breaker is tripped (`:681-682`).
  - Resolves the model and client the same way as `_chat_openai` (`:684-691`). Builds `tools`, `tool_choice="auto"`, reasoning `extra_body` and the Kimi temperature coercion (`:692-702`).
  - Runs the same 3-attempt loop with 429/422 breaker accounting (`:712-732`), but has **no** deterministic-auth short-circuit, **no** fallback, **no** cache and **no** `llm_call_timeout`.
  - Meters exact usage and runs `check_budget` (`:735-746`).
  - Returns `{"content": _clean_content(msg.content or ""), "tool_calls": [{"id","name","arguments"(dict)}]}`. Unparsable argument JSON becomes `{}` (`:747-759`).

**JSON repair: `_parse_json_response(response)`** (static, `llm_client.py:761-823`)

1. Strips the leading and trailing code fences (`` ```json `` / `` ``` ``) (`:764-768`).
2. Tries `json.loads` (`:770-773`).
3. Greedily extracts `\{[\s\S]*\}` (first `{` to last `}`) and tries again. If there is no closing brace it truncates from the first `{`, and returns `None` if there is no `{` at all (`:776-787`).
4. Scans the text, tracking string, escape and bracket-stack state (`:791-811`). It closes an open string, drops a trailing comma, appends closers in reverse nesting order, and tries again. Failure returns `None`; the function never raises (`:813-823`).

**Shared helpers**

- **`_split_system_message`** (`llm_client.py:828-840`): joins every `system` message with blank lines and returns `(system_text, other_messages)`.
- **`_flatten_prompt(messages, response_format)`** (`llm_client.py:842-864`): builds the CLI prompt. The parts are `SYSTEM INSTRUCTIONS:\n…`, then, for `json_object`, the line `IMPORTANT: Respond with valid JSON only…`, then `ROLE: content` per turn, all joined by `\n\n`.
- **`_clean_content`** (`llm_client.py:866-868`): strips `<think>…</think>` blocks and whitespace.
- **`_coerce_temperature(temperature, extra_body)`** (`llm_client.py:870-883`): for `provider=='kimi'` it forces `0.6` when thinking is disabled and `1.0` otherwise. Other providers pass through unchanged.
- **`_apply_reasoning_options(kwargs)`** (`llm_client.py:885-907`): `extra_body = Config.reasoning_extra_body(self.provider)`. That is `{"thinking":{"type":"disabled"}}` for kimi/minimax/deepseek/glm and `{"enable_thinking": False}` for qwen when their disable flags are on (default on), and `None` for openai/antigravity (`backend/app/config.py:810-843`). For a fallback client, it also sets `reasoning_effort` from `LLM_FALLBACK_REASONING_EFFORT`, which must be one of minimal/low/medium/high or it raises `ValueError` (`:896-906`).

**`_chat_openai(messages, temperature, max_tokens, response_format, tier)`** (`llm_client.py:912-970`)

- Resolves the model and client: a non-fallback client with tiered routing and `tier=='fast'` uses the fast-provider client when one exists (`:922-929`).
- Builds kwargs (`model, messages, temperature, max_tokens`, plus `response_format` if set, `extra_body`, coerced temperature, and `timeout` from the contextvar) (`:930-948`). It calls `client.chat.completions.create` (`:949`).
- Stores `self._last_usage = {prompt_tokens, completion_tokens}` when `response.usage` exists (`:951-959`).
- A `None` or whitespace-only `content` raises `RuntimeError` naming `finish_reason` and the `LLM_<PROVIDER>_DISABLE_THINKING` hint. That error is retryable (`:964-969`).
- Returns `_clean_content(content)`.

**CLI providers**

- **`_claude_cli_env()`** (`llm_client.py:975-986`) and **`_codex_cli_env()`** (`llm_client.py:988-998`): copy `os.environ` and drop `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` respectively, unless `LLM_CLI_USE_API_KEY=true`. This keeps the CLI on its subscription OAuth.
- **`_chat_claude_cli`** (`llm_client.py:1000-1078`):
  - Runs `["claude","-p","--output-format","json"]`. It adds `["--settings",'{"disableAllHooks": true}']` when `Config.LLM_CLI_ISOLATE_HOOKS` (default true, `backend/app/config.py:506`). It adds `["--model", self.model]` only if the model starts with `claude` or is `opus`/`sonnet`/`haiku` (`:1017-1026`).
  - The prompt goes through **stdin** (`input=prompt`), with `cwd="/tmp"` and `timeout=CLI_TIMEOUT` (`:1029-1034`). `temperature` and `max_tokens` are ignored.
  - A non-zero return code raises `RuntimeError("Claude CLI failed (rc=N): <stderr|stdout[:300]>")` (`:1036-1045`).
  - A JSON dict with `is_error`, or a `subtype` other than `None`/`"success"`, raises `RuntimeError("Claude CLI error envelope: … detail=<result|error[:200]>")` (`:1052-1061`).
  - Otherwise content is `output["result"]` (`:1062`). Non-JSON stdout is used raw (`:1063-1064`). Empty content after cleaning raises `RuntimeError` (`:1066-1068`).
  - `TimeoutExpired`, `FileNotFoundError` and `OSError` are all re-raised as `RuntimeError`, so they are retryable (`:1071-1078`).
- **`_chat_codex_cli`** (`llm_client.py:1083-1135`):
  - Runs `["codex","exec","--skip-git-repo-check"]` with the prompt on stdin, in `/tmp`, under the same timeout (`:1094-1099`). It does **not** pass a model, temperature or max_tokens.
  - A non-zero return code raises `RuntimeError("Codex CLI failed: <stderr[:200]>")`.
  - Output parsing (`:1105-1117`): takes the text after the last `"\ncodex\n"` marker and cuts it at a line equal to `tokens used`. With no marker, it uses the whole stdout.
  - An empty result raises `RuntimeError` (`:1118-1123`). The exception mapping matches the Claude path (`:1125-1135`).

### 2. `backend/app/utils/telemetry.py`

- **Docstring** (`telemetry.py:1-8`): says "the cache and budget guard are off unless explicitly configured". The cache now defaults to **on** (see Surprises).
- **Run context** (`telemetry.py:24-27`): ContextVars `llm_run_id` and `llm_stage`, both defaulting to `None`. `_DEFAULT_BUCKET = "_global"`.
- **Active-run registry** (FOG-TEL-1, `telemetry.py:29-39`): `_active_runs: {run_id: registered_at}`, under `_ACTIVE_LOCK`. Its purpose is to attribute calls from `ThreadPoolExecutor` / `run_in_executor` workers, which do not inherit contextvars, to the single in-flight run.
  - **`set_run_context(run_id, stage=None)`** (`telemetry.py:42-55`): a truthy `run_id` registers it. `None` unregisters the thread's *previous* run (`_current_run.get()`). Both contextvars are then set, so `stage` is reset to the argument, which defaults to `None`.
  - **`set_stage(stage)`** (`telemetry.py:58-59`); **`get_run_context()`** returns `(run_id, stage)` (`telemetry.py:62-63`); **`active_run_ids()`** (`telemetry.py:66-69`); **`_sole_active_run()`** returns the id only when exactly one run is registered (`telemetry.py:72-77`); **`_clear_active_runs()`** is a test helper (`telemetry.py:80-83`).
- **`BudgetExceeded(RuntimeError)`** (`telemetry.py:86-87`).
- **Cost model**:
  - `_COST_PER_1K` holds USD per 1K tokens as (input, output) (`telemetry.py:93-110`): openai (0.005, 0.015); deepseek (0.00027, 0.0011); qwen (0.0004, 0.0012); glm (0.0006, 0.0022); minimax (0.0003, 0.0011); kimi (0.0006, 0.0022); gemini (0.0003, 0.0025); proxy, antigravity, claude-cli and codex-cli are all (0, 0).
  - `_ESTIMATED_COST_PROVIDERS = {gemini, proxy, antigravity}` (`telemetry.py:117`).
  - **`_cost_overrides()`** (`telemetry.py:128-155`) parses `Config.LLM_COST_PER_MTOK`, a JSON object of `{provider: [in $/Mtok, out $/Mtok]}`, into lowercase per-1K pairs. It caches by the raw string and degrades to `{}` on any parse error.
  - **`estimate_cost(provider, pt, ct)`** (`telemetry.py:158-167`): checks the override (exact name, then lowercase), then the built-in table, then (0, 0).
  - **`cost_is_estimated(provider)`** (`telemetry.py:170-173`): True if the provider is in the estimated set or absent from `_COST_PER_1K`.
- **`_Counter`** (`telemetry.py:177-205`): `calls, cached, prompt_tokens, completion_tokens, latency_ms, cost_usd`. `add()` increments `calls` even for cached hits. `as_dict()` adds `total_tokens` and rounds latency to 0.1 and cost to 6 decimal places.
- **`_RunMeter`** (`telemetry.py:208-215`): `total`, `by_stage{stage: _Counter}`, `by_model{"provider:model": _Counter}`, and `fallback` (the subset attributed through the sole-active-run fallback).
- **`_GLOBAL_BUCKET_WARN_AT = (20, 100, 500, 2000)`** (`telemetry.py:221`).
- **`LLMMeter`** (`telemetry.py:224-399`): class-level `_lock` and `_runs: {run_id: _RunMeter}`, process-wide and in memory only.
  - **`record(provider, model, pt, ct, latency_ms, *, cached=False, stage=None, run_id=None)`** (`telemetry.py:230-270`):
    - Run id: explicit `run_id`, else the contextvar, else `_sole_active_run()` (marked as fallback), else `_global` (`:234-243`).
    - Stage: `stage`, else the contextvar, else `"_unstaged"` (`:244`).
    - Cost is 0 when `cached`, else `estimate_cost` (`:245`).
    - Under the lock it adds to total, by_stage, by_model and (when attributed through the fallback) fallback (`:248-258`).
    - It logs once at INFO on a run's first fallback-attributed call, and at WARNING when the `_global` bucket reaches 20/100/500/2000 calls (`:259-270`).
  - **`snapshot(run_id=None)`** (`telemetry.py:272-334`). The run id resolves to arg, then contextvar, then `_global`. It returns `{run_id, total, by_stage, by_model, cost_estimated, cost_basis, fallback_attributed}`, plus `unattributed_process` (the `_global` totals) for any run other than `_global`.
    - `cost_estimated` is True if any provider with tokens > 0 is estimated or unknown (`:306-309`).
    - `cost_basis` is computed over providers with tokens > 0 (`:312-322`): `"subscription"` when all are claude-cli/codex-cli, `"mixed"` when some are, and `"api"` otherwise or when there are none.
    - An unknown run returns a zero skeleton (`:291-299`).
  - **`status_snapshot(run_id)`** (`telemetry.py:336-350`): a compact `{run_id, total, by_stage, cost_estimated}`. It has no production caller (see Surprises).
  - **`reset(run_id=None)`** (`telemetry.py:352-360`): resolves the run id the same way, pops it from `_active_runs`, and pops its meter.
  - **`write_run_telemetry(path, run_id=None, extra=None)`** (`telemetry.py:362-399`): snapshot plus extra. If a file already exists at `path` with `total.calls > 0`, it adds `previous_attempt {total, report_id, status}` and a `cumulative_total` (the previous file's `cumulative_total`, or its `total`, plus the current total). It writes with `write_json_atomic` (`backend/app/utils/atomic.py:53-61`). It has no production caller: the orchestrator re-implements this merge (`backend/app/services/pipeline_orchestrator.py:7548-7614`).
- **`check_budget(run_id=None)`** (`telemetry.py:403-426`):
  - Limits are `Config.LLM_RUN_BUDGET_TOKENS` and `LLM_RUN_BUDGET_USD`. If both are ≤ 0 it returns at once.
  - Run id: arg, then contextvar, then the sole active run, then `_global`.
  - Raises `BudgetExceeded("run exceeded token budget: X > Y")` when `total_tokens > max_tokens`, or the cost variant when `cost_usd > max_cost`. The comparison is strictly greater-than.
- **`estimate_tokens(text)`** (`telemetry.py:430-434`): `max(1, len(text)//4)`, and 0 for empty text.
- **`_PIPELINE_STAGE_ORDER`** (`telemetry.py:442`): research, ontology, graph, prepare, run, report. These match the orchestrator's `STAGE_*` constants (`backend/app/services/pipeline_orchestrator.py:87-92`).
- **`build_stage_telemetry(run_id, stage_walls=None)`** (`telemetry.py:445-488`):
  - Keeps the non-negative numeric walls.
  - Takes the union of the snapshot's `by_stage` keys and the wall keys. It may include `_unstaged` and `ensemble` (the latter from `backend/app/services/pipeline_orchestrator.py:3825-3833`).
  - Per stage it emits `{calls, input_tokens, output_tokens, est_cost_usd, wall_seconds}`, plus a summed `total`, `run_id`, `cost_estimated`, `cost_basis`, and `unattributed_process` when present. It never raises on missing data.
- **`render_telemetry_appendix(stage_telemetry, title="Run Telemetry")`** (`telemetry.py:491-528`):
  - Returns `""` for a non-dict input or an empty `by_stage`.
  - Otherwise it renders `## Run Telemetry` and a table with the columns `Stage | Calls | Input tok | Output tok | Est. cost (USD) | Wall (s)`. Known stages come in pipeline order, unknown ones sorted after them, and a final `**TOTAL**` row.
  - It ends with an italic footnote: either "rough estimate…" or "derived from…". When `cost_basis != "api"` the footnote also gets ` Cost basis: <basis>.`.
- **`LLMCache`** (`telemetry.py:531-594`):
  - `_LLM_CACHE_BYPASS` ContextVar.
  - Class-level `_store: {sha256: str}` and `_order: list` (insertion order), with `_max_entries = 2048`.
  - **`bypass()`**: a context manager that sets the bypass flag (`:554-562`).
  - **`key(...)`**: `sha256(json.dumps([provider, model, messages, temperature, max_tokens, response_format], sort_keys=True, ensure_ascii=False, default=str))` (`:568-575`).
  - **`get`**: returns `None` when bypassed, and does not refresh recency (`:577-582`).
  - **`put`**: a no-op when bypassed. A new key is appended, and the oldest is evicted (`_order.pop(0)`) beyond 2048. The value is then stored or overwritten (`:584-594`). Eviction is therefore **FIFO**, not LRU.

### 3. `backend/app/utils/token_budget.py`

The contract is in the docstring (`token_budget.py:1-19`): pure functions with no Config access and no I/O, and they **never raise**. `slice_budget_chars` never returns less than `floor_chars`.

- **`CHARS_PER_TOKEN = 4.0`** (`token_budget.py:27`).
- **`_coerce_chars_per_token(x)`** (`token_budget.py:30-36`): `float(x)` if it is > 0, else 4.0.
- **`estimate_tokens(text, cpt=4.0)`** (`token_budget.py:39-47`): `ceil(len(str(text))/cpt)`. Empty text or any exception gives 0.
- **`truncate_to_tokens(text, max_tokens, cpt=4.0)`** (`token_budget.py:50-66`):
  - `None` becomes `""`. `max_tokens <= 0` gives `""`.
  - Otherwise it returns `s[:int(max_tokens*cpt)]`, or the original if it already fits. On an exception it returns the original string.
- **`context_budget(window, reserved, used=0)`** (`token_budget.py:69-74`): `max(0, window - reserved - used)`. An exception gives 0.
- **`slice_budget_chars(*, window_tokens, reserved_tokens, floor_chars, share=1.0, num_items=1, chars_per_token=4.0, cap_tokens=None)`** (`token_budget.py:77-120`):
  - A non-integer `floor_chars` returns 0.
  - `avail = context_budget(...)`; if `avail <= 0` it returns `floor`. An optional `cap_tokens` caps `avail`.
  - It returns `max(floor, int(avail*share*cpt/max(1, num_items)))`. Any other exception returns `floor`.
  - No production caller passes `cap_tokens`.
  - Worked example with `RESERVED_COMPLETION_TOKENS=8192` and `share=0.5, n=1`:
    - minimax (512K window) gives 1,007,616 chars;
    - claude-cli (200K) gives 383,616;
    - an unknown provider (the 32K default) gives 47,616.
    - All of these exceed the report's 8000-char floor.
- **`clamp_chars(value, floor, ceiling)`** (`token_budget.py:123-137`): clamps `value` into [floor, ceiling]. If `ceiling < floor` it uses `ceiling = floor`. On an exception it returns `int(floor)`, or 0.
- **`fit_to_budget(items, budget_tokens, item_max_tokens=None, cpt=4.0)`** (`token_budget.py:140-174`):
  - Walks the items in order and skips empty ones. It truncates each to `min(remaining, item_max_tokens)` and subtracts the estimated tokens of the piece, stopping when the budget is ≤ 0.
  - A non-integer budget returns every item stringified. No production caller uses it.

### 4. `backend/app/utils/file_parser.py`

- **`_read_text_with_fallback(path)`** (`file_parser.py:11-58`):
  - Reads the bytes and tries UTF-8.
  - Next it tries `charset_normalizer.from_bytes(data).best().encoding`, then `chardet.detect(data)['encoding']`. Exceptions from either detector are swallowed.
  - The final fallback is `'utf-8'`. It returns `data.decode(encoding, errors='replace')`.
- **`FileParser.SUPPORTED_EXTENSIONS = {'.pdf','.md','.markdown','.txt'}`** (`file_parser.py:64`). This matches `Config.ALLOWED_EXTENSIONS = {'pdf','md','txt','markdown'}` (`backend/app/config.py:1049`).
- **`extract_text(path)`** (`file_parser.py:66-94`): raises `FileNotFoundError` for a missing path and `ValueError("不支持的文件格式")` for other suffixes (compared lowercase). It dispatches `.pdf`, `.md`/`.markdown` and `.txt` to their extractors. The final `raise` (`:94`) is unreachable.
- **`_extract_from_pdf`** (`file_parser.py:96-111`): `import fitz` (PyMuPDF), raising `ImportError("需要安装PyMuPDF…")` if it is missing. Opens the document, takes each page's `get_text()` and keeps only pages with non-blank text, joined by `\n\n`. There is no OCR, so a scanned PDF yields `""`.
- **`_extract_from_md` / `_extract_from_txt`** (`file_parser.py:113-121`): both call `_read_text_with_fallback`. Markdown is **not** stripped or rendered.
- **`extract_from_multiple(paths)`** (`file_parser.py:123-144`): for each file it emits `=== 文档 {i}: {filename} ===\n{text}`. A failed file becomes `=== 文档 {i}: {path} (提取失败: {err}) ===`, so one bad file never fails the batch. Parts are joined by `\n\n`.
- **`split_text_into_chunks(text, chunk_size=2500, overlap=250)`** (`file_parser.py:147-191`):
  - Text with `len <= chunk_size` returns `[text]` unstripped, or `[]` if it is blank (`:166-167`).
  - Otherwise, starting from `start=0`: `end = start + chunk_size`. When that is not the end of the text, it searches `text[start:end]` for the **last** occurrence of the first separator in this priority list that lies past 30% of `chunk_size`: `。 ！ ？ .\n !\n ?\n \n\n ". " "! " "? "`. It sets `end` just after that separator (`:176-182`).
  - It appends the stripped, non-empty chunk (`:184-186`). The next `start` is `end - overlap`, or `len(text)` once the end has been reached (`:189`).
  - There is no validation of `overlap` against `chunk_size` (see Surprises).

---

## Control flow

**A. One `chat()` call in a pipeline run**

1. A caller (for example `ReportAgent`) calls `llm.chat(...)` or `llm.chat_json(...)`. `chat_json` loops over two `self.chat` calls (`llm_client.py:613-620`).
2. Because `LLMClient.chat` may have been replaced by the orchestrator's **outage probe**, it may actually run `_outage_probed_chat` (`backend/app/services/pipeline_orchestrator.py:597-645`). The probe is installed at the start of `_run` when the run-level outage breaker is enabled (`backend/app/services/pipeline_orchestrator.py:11891-11892`). It passes calls through for `_is_fallback` clients and when no breaker is attributable. It fails fast if that breaker is tripped. Otherwise it counts success or failure around the original `chat`.
3. Inside `chat()`, the sequence is (`llm_client.py:419-522`):
   - resolve the model;
   - cache lookup;
   - breaker pre-check, which can route to `_try_fallback` or raise;
   - up to 3 primary attempts through `_chat_openai`, `_chat_claude_cli` or `_chat_codex_cli`, with breaker accounting and sleeps;
   - `_try_fallback`, which builds a fallback `LLMClient` and calls its own full `chat()` with recursion disabled;
   - meter, then cache put, then `check_budget`.
4. `LLMMeter.record` attributes the call to the run id and stage from contextvars, or falls back as described in Walkthrough §2 (`telemetry.py:234-244`).

**B. Run lifecycle (orchestrator, outside this slice)**

1. `_run` calls `set_run_context(pipeline_id)` (`backend/app/services/pipeline_orchestrator.py:11887-11888`) and `_init_telemetry_flush` (`:11894`). The latter captures the previous attempt's totals from `run_telemetry.json` (`:7557-7573`).
2. Each stage's `_make_stage_updater` calls `set_stage(stage)` (`:8950-8956`).
3. Incremental flushes happen on stage transitions and every `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` (default 20) new calls (`:7616-7632`). They write `LLMMeter.snapshot(...)` plus metadata atomically (`:7575-7614`).
4. In `finally`, the orchestrator:
   - does a final flush with `report_telemetry` and `sim_llm_health` extras (`:13399-13430`);
   - writes `build_stage_telemetry(...)` to `telemetry.json` and folds it into `state.options.llm_telemetry`;
   - writes `render_telemetry_appendix` to `<report>/telemetry.md`, and appends it to `full_report.md` only if `REPORT_TELEMETRY_APPENDIX` (`:13436-13481`);
   - calls `LLMMeter.reset(pipeline_id)` (`:13483`).
5. Standalone report generation sets `set_run_context(upstream_run or report_id, "report")` and restores the previous context in `finally` (`backend/app/services/report_agent.py:11163-11176,11711-11716`).

**C. Upload, then chunks**

`POST /api/graph/ontology/generate` follows these steps (`backend/app/api/graph.py:121-200`):

1. `allowed_file` (`:25-30`).
2. `ProjectManager.save_file_to_project`, which saves the upload as `<uuid8><ext>` (`backend/app/models/project.py:257-266`).
3. `FileParser.extract_text`.
4. `TextProcessor.preprocess_text`.
5. Later, `/api/graph/build` calls `TextProcessor.split_text`, which calls `split_text_into_chunks` (`backend/app/api/graph.py:393`, `backend/app/services/text_processor.py:43-49`).

---

## Data & artifacts

| Artifact | Writer | Format / key fields |
|---|---|---|
| None from `llm_client.py` | — | The CLI subprocesses run in `cwd="/tmp"` (`llm_client.py:1033,1098`). The prompt goes through stdin, never argv. |
| `<path>` passed to `write_run_telemetry` | `telemetry.py:362-399` (unused in production) | The snapshot JSON plus `previous_attempt` and `cumulative_total`. |
| `<pipeline dir>/run_telemetry.json` | orchestrator, from `LLMMeter.snapshot` (`backend/app/services/pipeline_orchestrator.py:7559,7589-7609`) | `run_id`, `total{calls,cached,prompt_tokens,completion_tokens,total_tokens,latency_ms,cost_usd}`, `by_stage{…}`, `by_model{"provider:model":{…}}`, `cost_estimated`, `cost_basis` (`api`/`subscription`/`mixed`), `fallback_attributed{…}`, `unattributed_process{…}`, `pipeline_id`, `status`, `report_id`, `in_flight` (non-final flushes only), `previous_attempt`, `cumulative_total`, and final extras `report_telemetry` and `sim_llm_health`. |
| `<pipeline dir>/telemetry.json` | orchestrator, from `build_stage_telemetry` (`backend/app/services/pipeline_orchestrator.py:13443-13447`) | `run_id`, `by_stage{stage:{calls,input_tokens,output_tokens,est_cost_usd,wall_seconds}}`, `total{same keys}`, `cost_estimated`, `cost_basis`, `unattributed_process`. |
| `<report folder>/telemetry.md` | orchestrator, from `render_telemetry_appendix` (`backend/app/services/pipeline_orchestrator.py:13464-13471`) | A Markdown table (see Walkthrough §2). |
| Uploaded files (read) | `ProjectManager.save_file_to_project` (`backend/app/models/project.py:257-266`) | Read by `FileParser.extract_text`. Size is capped by Flask `MAX_CONTENT_LENGTH = 50MB` (`backend/app/config.py:1047`). |

**Process-global in-memory structures.** None of these persist across restarts.

- `_CB_STATE` (`llm_client.py:109`)
- `_FB_OPENAI_CLIENTS`, `_FB_AUTH_UNAVAILABLE_UNTIL`, `_FB_MISCONFIG_WARNED` (`llm_client.py:190,194,230`)
- `LLMMeter._runs` (`telemetry.py:228`)
- `_active_runs` (`telemetry.py:39`)
- `LLMCache._store` / `_order` (`telemetry.py:550-551`)
- `_COST_OVERRIDE_CACHE` (`telemetry.py:125`)

**Per-instance:** `LLMClient._last_usage` (`llm_client.py:260`), which other modules read (for example `backend/scripts/run_parallel_simulation.py:2151`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `LLM_PROVIDER` | `claude-cli` | Primary provider used when the constructor gets none | `backend/app/config.py:750`; `llm_client.py:257` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | none / provider default / provider default (`gpt-4o-mini` for openai **and for the CLI providers**) | Constructor fallbacks | `backend/app/config.py:782-798`; `llm_client.py:263-265` |
| `LLM_USER_AGENT` | `claude-cli/1.0.0` | Kimi-only `User-Agent` header | `backend/app/config.py:803`; `llm_client.py:304-305` |
| `LLM_KIMI_DISABLE_THINKING`, `LLM_MINIMAX_DISABLE_THINKING`, `LLM_DISABLE_THINKING` | true | Send `extra_body` that disables thinking. Kimi's temperature becomes 0.6 (or 1.0 with thinking on) | `backend/app/config.py:810-843`; `llm_client.py:880-883,893-895` |
| `LLM_CLI_TIMEOUT` | 180 s | Subprocess timeout. Read at import | `llm_client.py:29` |
| `LLM_CLI_ISOLATE_HOOKS` | true | Adds `--settings {"disableAllHooks": true}` to `claude` | `backend/app/config.py:506`; `llm_client.py:1022-1023` |
| `LLM_CLI_USE_API_KEY` | unset (false) | When `true`, keeps `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` in the CLI environment. Read per call; not in `.env.example` | `llm_client.py:984,996` |
| `LLM_CB_422_THRESHOLD` / `LLM_CB_COOLDOWN_S` | 5 / 300 s | 422 breaker. Read at import | `llm_client.py:116-123` |
| `LLM_CB_429_THRESHOLD` / `LLM_CB_429_COOLDOWN_S` | 8 / 120 s | 429 breaker. Read at import | `llm_client.py:135-142` |
| `LLM_FALLBACK_PROVIDER` | unset (failover off) | Single-hop failover target. Read from `os.environ` on each failover | `llm_client.py:532`; `.env.example:300` |
| `LLM_FALLBACK_MODEL` / `_BASE_URL` / `_API_KEY` | unset | Fallback client parameters. A missing model blocks an OpenAI-compatible fallback. A missing URL or key inherits the primary's | `llm_client.py:535-568` |
| `LLM_FALLBACK_REASONING_EFFORT` | unset | `reasoning_effort` on fallback requests. Must be minimal/low/medium/high | `llm_client.py:896-906` |
| `LLM_HTTP_TIMEOUT_S` | **not defined in Config**, so effectively 600 s | SDK client timeout | `llm_client.py:298` |
| `LLM_HTTP2` / `LLM_HTTP_KEEPALIVE` | True / 128 | Tuned httpx client and SDK `max_retries=0` | `backend/app/config.py:79-80`; `llm_client.py:310-313,330-344` |
| `LLM_TIERED_ROUTING` | True | `tier` selects the global fast or strong model | `backend/app/config.py:92`; `llm_client.py:370-374` |
| `LLM_FAST_MODEL` / `LLM_STRONG_MODEL` | unset, so `LLM_MODEL_NAME` | Tier model names | `backend/app/config.py:96-97,145-152` |
| `LLM_FAST_PROVIDER` / `_BASE_URL` / `_API_KEY` | unset | Separate fast-tier SDK client (all three required) | `backend/app/config.py:101-103`; `llm_client.py:383-394` |
| `REPORT_NATIVE_TOOLS` | true | Gates `supports_native_tools` | `backend/app/config.py:1528`; `llm_client.py:645` |
| `LLM_NATIVE_TOOLS_PROVIDERS` | unset | Comma-separated allow-list overriding `PROVIDER_META.native_tools` | `llm_client.py:649-653` |
| `LLM_TELEMETRY_ENABLED` | True | Meter recording in `chat` / `chat_with_tools` | `backend/app/config.py:58`; `llm_client.py:430,507,735` |
| `LLM_CACHE_ENABLED` | **True** | Response cache in `chat()` | `backend/app/config.py:62`; `llm_client.py:425,518` |
| `LLM_RUN_BUDGET_TOKENS` / `LLM_RUN_BUDGET_USD` | 0 / 0 (unlimited) | Post-call budget guard | `backend/app/config.py:64-65`; `telemetry.py:410-413` |
| `LLM_COST_PER_MTOK` | `''` | JSON `$/Mtok` override table | `backend/app/config.py:73`; `telemetry.py:128-155` |
| `REPORT_TRANSLATION_CALL_TIMEOUT_S` | 240 | Value passed to `llm_call_timeout` for translation | `backend/app/services/report_agent.py:7431-7433` |
| `ADAPTIVE_CONTEXT`, `RESERVED_COMPLETION_TOKENS`, `PROVIDER_CONTEXT_WINDOWS`, `DEFAULT_CONTEXT_WINDOW` | True, 8192, per-provider table, 32000 | Inputs that callers pass to `slice_budget_chars` | `backend/app/config.py:118-157` |
| `CONTEXT_ITEM_MAX_TOKENS` | 4096 | Defined but **never read** (intended for `fit_to_budget`) | `backend/app/config.py:122` |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | 2500 / 250 | Chunking used by `TextProcessor.split_text` and callers. Not validated | `backend/app/config.py:1055-1057`; `backend/app/services/text_processor.py:44-48` |
| `ALLOWED_EXTENSIONS`, `MAX_CONTENT_LENGTH` | `{pdf,md,txt,markdown}`, 50 MB | Upload gate | `backend/app/config.py:1047-1049` |

---

## External calls

| Target | Anchor | Notes |
|---|---|---|
| `claude -p --output-format json [--settings …] [--model M]` subprocess | `llm_client.py:1017-1034` | Prompt on stdin, cwd `/tmp`, timeout `CLI_TIMEOUT`, environment without `ANTHROPIC_API_KEY`. |
| `codex exec --skip-git-repo-check` subprocess | `llm_client.py:1094-1099` | Prompt on stdin, cwd `/tmp`, environment without `OPENAI_API_KEY`. |
| OpenAI SDK `chat.completions.create` (HTTP to `base_url`) | `llm_client.py:949` (chat), `llm_client.py:714` (tools) | This reaches openai/kimi/minimax/deepseek/qwen/glm/antigravity endpoints. The default base URLs are at `backend/app/config.py:753-779`. |
| `httpx.Client(http2=…)` construction | `llm_client.py:344,348` | Connection pool only. |
| PyMuPDF `fitz.open` | `file_parser.py:100-107` | Local file. |
| `charset_normalizer`, `chardet` | `file_parser.py:38-52` | Local encoding detection. |
| `write_json_atomic` (filesystem) | `telemetry.py:373,399` | Only in the unused `write_run_telemetry`. |

`telemetry.py` and `token_budget.py` make no network calls.

---

## Cross-module edges

**Into `llm_client`:**

- **Pipeline generators:** `backend/app/services/ontology_generator.py:9,480`; `backend/app/services/oasis_profile_generator.py:36,370`; `backend/app/services/simulation_config_generator.py:40,448`; `backend/app/services/zep_tools.py:26,577`; `backend/app/services/report_agent.py:28,1671,12394` (which also imports `llm_call_timeout`).
- **Forecast ensemble draws:** a per-provider `LLMClient(provider, api_key, base_url, model=default_model)` (`backend/app/services/forecast_extractor.py:2606-2617`).
- **Graphiti extraction:** one shared `AppLLMClient` per adapter, called through `loop.run_in_executor` (`backend/app/services/graphiti_client/llm_adapter.py:33,111,169-173`). The graph-ingest fallback builds its own `LLMClient(... LLM_FALLBACK_*)` with `_is_fallback=True` (`backend/app/services/graphiti_client/runtime.py:605-618`).
- **OASIS bridge:**
  - `LLMClient`, `CLI_PROVIDERS` (`backend/app/utils/oasis_llm.py:22,567,612`);
  - `_parse_json_response` for emulated tool calls (`backend/app/utils/oasis_llm.py:129-130`);
  - `_is_content_filter` (`backend/app/utils/oasis_llm.py:304`);
  - the failover path `LLMClient(provider=…)` (`backend/app/utils/oasis_llm.py:328`).
- **Orchestrator:**
  - the outage classifier imports `_is_deterministic_auth_error` and `_is_quota` (`backend/app/services/pipeline_orchestrator.py:422-436`);
  - the outage probe monkeypatches `LLMClient.chat` (`backend/app/services/pipeline_orchestrator.py:597-657`);
  - it also constructs `LLMClient` at `:612,651,6241,13252`.
- **API:** the research report translation endpoint (`backend/app/api/research.py:500,511`).
- **Scripts:** the sim subprocess (`backend/scripts/run_parallel_simulation.py:3444-3446,5989-6005`, wrapped by `_wrap_llm_client_usage`, `:2123-2153`), `backend/scripts/model_comparison.py:64,136`, `backend/scripts/eval_forecast_quality.py:311-330`.
- **Package export:** `backend/app/utils/__init__.py:6`.

**Into `telemetry`:**

- `llm_client.py:422,707`.
- The orchestrator uses `set_run_context`, `set_stage`, `LLMMeter.record/snapshot/reset`, `build_stage_telemetry`, `render_telemetry_appendix`, `BudgetExceeded`, `active_run_ids` and `get_run_context` (`backend/app/services/pipeline_orchestrator.py:410,565,2069,7585,7627,8586,8953,10316,10453,10544,11887,13442,13483`).
- The report agent uses `LLMCache.bypass`, `LLMMeter.snapshot` and `set_run_context` / `get_run_context` (`backend/app/services/report_agent.py:31,7431,7741,9432,9443,11173,11715`).
- Script: `backend/scripts/model_comparison.py:66,221,258,270-271`.

**Into `token_budget`:** `backend/app/services/report_agent.py:2359-2367`, `backend/app/services/oasis_profile_generator.py:1952-1960`, `backend/app/services/simulation_config_generator.py:1925-1935`. Only `slice_budget_chars` and `clamp_chars` are used.

**Into `file_parser`:** `backend/app/api/graph.py:16,197`; `backend/app/services/text_processor.py:6,21,49`; `backend/app/utils/__init__.py:5`.

**Out of the slice:**

- `Config` (`backend/app/config.py`), `get_logger`, and `openai` / `httpx` (`llm_client.py:22-23,54,288,333`).
- `telemetry` imports `Config` lazily (`telemetry.py:131,409`) and `atomic.write_json_atomic` (`telemetry.py:373`).
- `token_budget` and `file_parser` import nothing from the app.

---

## Invariants, gates, validation

- **No recursive failover.** A fallback client has `_is_fallback=True`. `_try_fallback` returns `None` on such a client, and the breaker pre-check is skipped for it (`llm_client.py:444,530-531,569`). The fallback's model is never replaced by the tier alias (`llm_client.py:368-369`). The outage probe also passes fallback clients through untouched (`backend/app/services/pipeline_orchestrator.py:620-621`).
- **No double metering.** A fallback-served call is metered once, by the fallback client's own `chat()` under the fallback provider (`llm_client.py:436-439,507`).
- **Provider whitelist** at construction (`llm_client.py:267-271`). An OpenAI-compatible provider needs a key (`llm_client.py:289-290`).
- **Empty output is an error.** OpenAI-compatible empty `content` (`llm_client.py:964-969`), an empty Claude result (`:1067-1068`) and an empty Codex result (`:1120-1122`) each raise `RuntimeError`, which `chat()` retries.
- **Breaker state is updated under `_CB_LOCK`** (`llm_client.py:153,159,170,180`). The fallback cooldown map is also accessed under `_CB_LOCK` (`llm_client.py:554,582,590`).
- **Meter mutations happen under `LLMMeter._lock`.** The active-run registry uses `_ACTIVE_LOCK` (`telemetry.py:248,357-360,44,52`).
- **Attribution rule.** An explicit run id wins, then the contextvar, then the sole active run, then `_global`. An ambiguous call (zero or 2+ active runs) is never assigned to a specific run (`telemetry.py:234-243,414-419`).
- **`slice_budget_chars` is never below `floor_chars`.** It and every other `token_budget` function swallow all exceptions (`token_budget.py:102-120`).
- **Cache key covers the model.** The key includes the resolved model, so fast and strong results do not mix (`llm_client.py:426-427`). `LLMCache.bypass()` turns off both reads and writes in the scoped context (`telemetry.py:577-594`).
- **Upload gates.** The extension is checked twice, by the route (`backend/app/api/graph.py:25-30`) and by `FileParser.extract_text` (`file_parser.py:84-85`). The file must exist (`file_parser.py:79-80`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Transient HTTP error (429/timeout/connection/5xx) or any `RuntimeError` (CLI failure, empty content) | 3 attempts with 2 s and 4 s backoff (or `Retry-After` up to 30 s), then failover, then the last error is raised | `llm_client.py:459-505` |
| 422 content filter (SDK `UnprocessableEntityError` or a matching message) | No retry. Counts toward the 422 breaker, then failover | `llm_client.py:488-493` |
| Deterministic 401 inside a `RuntimeError` (CLI auth) | Retries stop at once, then failover | `llm_client.py:474-479` |
| 5 consecutive 422s, or 8 consecutive quota-like failures (counted per attempt) | The provider trips for 300 s or 120 s. During that window every `chat()` goes straight to the fallback, or **raises at once** when there is no fallback. `supports_native_tools()` returns False and `chat_with_tools` raises | `llm_client.py:158-176,444-458,656,681-682` |
| Breaker cooldown expires | The counters are still at or above the threshold, so the first new 422/429 re-trips at once (half-open). Only a primary success resets them | `llm_client.py:162,173,179-184` |
| Fallback fails with 401/400-class error | A 900 s per-`(provider, model, base_url)` cooldown starts. The primary error is raised | `llm_client.py:586-595,553-561` |
| Fallback misconfigured (OpenAI-compatible without `LLM_FALLBACK_MODEL`) | Fallback disabled, one warning | `llm_client.py:542-552` |
| `chat_json` cannot parse | Local repair, then one retry at a temperature 0.2 lower, then `ValueError` | `llm_client.py:613-627` |
| Native tool call fails | Retries with no fallback, then raises. The report agent drops down to ReAct (comment at `llm_client.py:703-706`) | `llm_client.py:712-734` |
| Run over budget | `BudgetExceeded` is raised after the call that crossed the limit has already completed and been metered | `llm_client.py:520-521`; `telemetry.py:421-426` |
| Missing run context in worker threads | Calls go to the sole active run (counted in `fallback_attributed`) or to `_global`, with WARN at 20/100/500/2000 | `telemetry.py:236-270` |
| Process restart | `LLMMeter`, the cache and the breakers are all lost. The orchestrator's incremental `run_telemetry.json` flushes keep the spend (`backend/app/services/pipeline_orchestrator.py:7548-7555`) | `telemetry.py:227-228` |
| PDF parser missing / unsupported file / undecodable text | `ImportError` / `ValueError` / replacement characters. The upload route returns 500 with a traceback (`backend/app/api/graph.py:249-254`). `extract_from_multiple` turns per-file errors into marker lines instead | `file_parser.py:84-85,101-102,57-58,141-142` |

---

## Surprises

1. **Suspected bug: an explicit `model=` is ignored for non-fallback clients while tiered routing is on (the default).**
   - `_model_for_tier` returns `Config.strong_model() or self.model`, and `strong_model()` returns `LLM_STRONG_MODEL or LLM_MODEL_NAME`. That value is almost always non-empty, so `self.model` is never used (`llm_client.py:370-374`; `backend/app/config.py:92,150-152`).
   - Forecast ensemble draws build `LLMClient(provider='deepseek', model='deepseek-chat', …)` (`backend/app/services/forecast_extractor.py:2615-2617`), but the request carries the *primary's* model name, for example `MiniMax-M3`.
   - The same applies to `backend/scripts/model_comparison.py:130-136`.
   - The cache key and the `by_model` meter label also use the global model (`llm_client.py:419,427,517`).
2. **Suspected bug: `BudgetExceeded` is hidden during failover.**
   - `BudgetExceeded` subclasses `RuntimeError` (`telemetry.py:86`). When the fallback's own `chat()` raises it (`llm_client.py:520-521` on the fallback instance), `_try_fallback` swallows it with `except Exception` and returns `None` (`llm_client.py:586-595`).
   - The caller then gets the *primary's* provider error (`llm_client.py:505`), or the "熔断冷却…回退提供方不可用" error on the breaker path (`llm_client.py:455-458`).
   - The orchestrator's outage classifier exempts only real `BudgetExceeded` instances (`backend/app/services/pipeline_orchestrator.py:410-411`), so a budget overrun can be counted as a provider outage.
3. **The budget guard runs after the call.** `check_budget` runs after the response has been paid for and metered, and the call that crossed the limit loses its result. Every later call also completes before raising (`llm_client.py:507-522`). Cache hits return before the check (`llm_client.py:428-432`).
4. **Response-cache behavior drifts from its docs.**
   - The cache is **on by default** (`backend/app/config.py:62`), but `telemetry.py:6-7,540` and `llm_client.py:421` say it is off.
   - It caches every `chat()` call regardless of temperature, so any identical retry is replayed. An example is the "retry once" for an empty spine, made with the same prompt at temperature 0.2 (`backend/app/services/forecast_extractor.py:3256-3260,3031-3035`).
   - The config comment says "LRU" and "only deterministic attempt-0 calls hit" (`backend/app/config.py:59-61`, repeated at `ARCHITECTURE_MAP.md:878`). The code is FIFO with no recency refresh, and it is unconditional (`telemetry.py:577-594`). Only translation uses `bypass()` (`backend/app/services/report_agent.py:7431,7741`).
5. **`chat_json` can return a non-dict.** A top-level array or scalar is returned as is (`llm_client.py:622-624,770-771`). I confirmed this by running the extracted `_parse_json_response`: `'[1,2]'` gives `[1, 2]` and `'42'` gives `42`. Some callers guard against it (`backend/app/services/forecast_extractor.py:3036-3037`).
6. **`_last_usage` is per instance and not thread-safe.** One `LLMClient` is shared across Graphiti executor threads (`backend/app/services/graphiti_client/llm_adapter.py:111,169-173`). Thread A can read thread B's usage between `:954` and `:509`. On a cache hit `chat()` returns before the reset at `:441`, so `_last_usage` still holds the previous call's usage, and wrappers that read it (`backend/scripts/run_parallel_simulation.py:2151`) may double-count.
7. **Breaker state is keyed only by provider name** (`llm_client.py:109`). Failures from a fast-tier client on a *different* provider are recorded against the primary provider (`llm_client.py:464,481,491` with `:922-929`). Every instance with the same provider name shares one breaker. With no fallback configured, a tripped breaker makes every `chat()` fail at once for the whole cooldown (`llm_client.py:450-458`). Because the 429 counter increments on every retry attempt, about 3 fully failing `chat()` calls are enough to trip it (`llm_client.py:480-481`).
8. **Fallback inherits primary connection data.**
   - If `LLM_FALLBACK_API_KEY` or `LLM_FALLBACK_BASE_URL` is unset, the fallback silently uses the primary's `Config.LLM_API_KEY` / `LLM_BASE_URL` (`llm_client.py:263-264,563-568`). The misconfiguration guard only checks the model (`llm_client.py:542-552`).
   - The inner condition `(fb_provider != self.provider or …)` is always true, because `:533` already returned in the equal case.
   - Fallback construction errors that are not deterministic get no cooldown, so they are rebuilt and fail on every failover. Examples are an unsupported provider, a missing key, or an invalid `LLM_FALLBACK_REASONING_EFFORT` (`llm_client.py:289-290,901-905,586-595`).
9. **Fallback "pool reuse" still builds a new client every failover.** `LLMClient.__init__` constructs a new OpenAI/httpx client on each failover (`llm_client.py:274-276`, through `:563`). It is then discarded in favor of the cached one without being closed (`llm_client.py:572-578`).
10. **`LLM_HTTP_TIMEOUT_S` is not a real knob.** No `Config` attribute exists, so the SDK timeout is always 600 s (`llm_client.py:298`; grep finds no other definition).
11. **Stale docstrings and comments.**
    - The module docstring lists only 3 providers (`llm_client.py:4-9`).
    - The `chat` docstring says SDK `APIError`s are not retried (`llm_client.py:410-412`), which `_RETRYABLE_API_ERRORS` contradicts (`:53-60`).
    - The comments at `llm_client.py:306-309` and `:359` say HTTP/2 and tiered routing are off by default, but both default to True (`backend/app/config.py:79,92`).
12. **Dead or unused code.**
    - `LLMMeter.write_run_telemetry` has no production caller; the orchestrator re-implements the merge (`backend/app/services/pipeline_orchestrator.py:7548-7555,13425-13430`).
    - `LLMMeter.status_snapshot` has no caller, although `backend/app/api/research.py:310-313` implies it was wired up; `heartbeat_status` reads `LLMMeter.snapshot` directly (`backend/app/services/pipeline_orchestrator.py:10314-10325`).
    - Only `slice_budget_chars` and `clamp_chars` are used in production, even though `backend/app/config.py:106-110` claims all six `token_budget` helpers are wired. `CONTEXT_ITEM_MAX_TOKENS` is never read (`backend/app/config.py:122`).
    - `FileParser.extract_from_multiple` is reachable only through `TextProcessor.extract_from_files`, which has no callers (`backend/app/services/text_processor.py:19-21`).
    - `file_parser.py:94` is unreachable.
13. **Duplicated token estimator.** `telemetry.estimate_tokens` uses `max(1, len//4)` (`telemetry.py:430-434`), while `token_budget.estimate_tokens` uses `ceil(len/cpt)` and returns 0 for empty text (`token_budget.py:39-47`).
14. **Suspected bug: `split_text_into_chunks` can loop forever.**
    - It never terminates when `overlap >= chunk_size`. It also loops when `overlap` exceeds about 30% of `chunk_size` and a separator lands just past the 30% mark, because `start` then moves backward (`file_parser.py:178-189`).
    - I confirmed both cases with a pure-function probe: 100/100, and 100/80 with a sentence every 35 characters, each failed to finish within 2 s. The default 2500/250 terminates.
    - `DEFAULT_CHUNK_OVERLAP` is env-settable with no validation (`backend/app/config.py:1057`).
    - Also, the short-text path returns unstripped text (`file_parser.py:166-167`) while long-text chunks are stripped (`:184`).
15. **No OCR for PDFs.** A scanned or image-only PDF yields `""` (`file_parser.py:104-111`). The upload route still counts it as a processed document, so a project can proceed with empty text (`backend/app/api/graph.py:197-205`).
16. **CLI-provider quirks.**
    - `temperature` and `max_tokens` are ignored, and only JSON mode adds a prompt line (`llm_client.py:854-858,1017-1034`).
    - Codex never pins a model (`llm_client.py:1095`). Its output parse depends on the `"\ncodex\n"` and `tokens used` markers, which is fragile if the CLI's output changes (suspected, `llm_client.py:1105-1117`).
    - Claude pins a model only for claude/opus/sonnet/haiku names. The default `LLM_MODEL_NAME` with `claude-cli` is `gpt-4o-mini` (`backend/app/config.py:791-798`), so it is not pinned, but the meter still labels the calls `claude-cli:gpt-4o-mini`.
    - Suspected: if `claude --output-format json` ever emits a JSON array, the raw stdout is returned as the content (`llm_client.py:1062`).
17. **Suspected false positives in `_is_quota`.** It matches the substring `"429"` anywhere, for example "4290 tokens" (`llm_client.py:148`). `_is_content_filter` matches `" 422"` anywhere (`llm_client.py:129`).
18. **Telemetry nuances.**
    - The comment says `reset` never clears `_global` (`telemetry.py:218`). But `reset()` called with no argument and no run context resolves to `_global` and pops it (`telemetry.py:354,360`).
    - `cost_is_estimated` ignores `LLM_COST_PER_MTOK` overrides (`telemetry.py:173`).
    - `set_run_context(run_id)` resets the stage to `None` unless one is passed (`telemetry.py:55`).
19. **Doc drift.**
    - `ARCHITECTURE_MAP.md:875` says the Claude CLI gets the prompt as an argv element, but the code uses stdin (`llm_client.py:1009-1011,1029-1031`).
    - `ARCHITECTURE_MAP.md:879-880` mentions only the 422 breaker, but a 429 breaker also exists (`llm_client.py:132-176`).
    - `DRF_ARCHITECTURE.md:1512-1525` and `:291-298` cite stale line numbers. For example, `_model_for_tier :273` is actually `:356`, `_try_fallback :420` is `:524`, and `check_budget :309-326` is `telemetry.py:403-426`.
