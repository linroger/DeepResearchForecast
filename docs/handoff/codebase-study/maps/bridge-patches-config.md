# bridge-patches-config — DeerFlow patches, bridge config and runtime skill sync

Slice owner files (all read line-by-line):

| File | Lines | Kind |
|---|---|---|
| `deerflow_bridge/patches/apply_lead_agent_overlays.py` | 138 | in-place string-transform overlay |
| `deerflow_bridge/patches/apply_model_factory_overlays.py` | 65 | in-place string-transform overlay |
| `deerflow_bridge/patches/apply_subagent_overlays.py` | 410 | in-place string-transform overlay (3 target files) |
| `deerflow_bridge/patches/middlewares/loop_detection_middleware.py` | 635 | full-file replacement |
| `deerflow_bridge/patches/middlewares/tool_error_handling_middleware.py` | 257 | full-file replacement |
| `deerflow_bridge/patches/middlewares/model_concurrency_middleware.py` | 76 | new file (no upstream counterpart) |
| `deerflow_bridge/patches/middlewares/summarization_middleware.py` | 513 | full-file replacement |
| `deerflow_bridge/patches/middlewares/title_middleware.py` | 194 | full-file replacement |
| `deerflow_bridge/patches/models/claude_provider.py` | 514 | full-file replacement |
| `deerflow_bridge/patches/models/credential_loader.py` | 278 | full-file replacement |
| `deerflow_bridge/patches/models/patched_minimax.py` | 239 | full-file replacement (byte-identical to vendor seed) |
| `deerflow_bridge/patches/tests/*.py` (6 files) | 852 | pytest regressions run inside DeerFlow's venv |
| `deerflow_bridge/runtime_skill_sync.py` | 615 | skill-bundle deployer + verifier (lib + CLI) |
| `deerflow_bridge/config.yaml` | 1669 | DeerFlow `AppConfig` YAML (models/tools/sandbox/subagents/...) |
| `deerflow_bridge/extensions_config.json` | 41 | MCP server template |
| `deerflow_bridge/README.md` | 101 | docs |

(`deerflow_bridge/patches/.DS_Store` and `__pycache__/*.pyc` are noise; not mapped.)

Two DeerFlow trees exist on disk, both gitignored (`.gitignore:84` `deer-flow/`, `.gitignore:93` `deer-flow-2.0.0/`):
- `deer-flow/` — the **active runtime** the research subprocess executes (`pipeline_orchestrator.py:2430` `cwd=deerflow_dir`).
- `deer-flow-2.0.0/` — the **vendor seed** `setup.sh` copies from when `deer-flow/` is absent (`setup.sh:501`, `setup.sh:519-523`).
They are **different upstream snapshots** (e.g. `config/subagents_config.py` default timeout 900 in runtime vs 1800 in seed; `community/brave`, `searxng` exist only in seed) — verified with `diff -rq`.

---

## Purpose & position in the pipeline

Stage 1 (deep research) runs `deer-flow/deerflow_research.py` as a subprocess inside DeerFlow's own Python 3.12 venv (`deerflow_bridge/README.md:10-13`). DeerFlow lives in the gitignored `deer-flow/` tree, so anything DRF changes inside DeerFlow must be re-applied from tracked sources. This slice is that tracked layer:

1. **Patches** (`deerflow_bridge/patches/`) change DeerFlow's behavior in two styles: (a) full-file replacements copied over DeerFlow modules (`models/*.py`, `middlewares/*.py`), and (b) narrow, idempotent string-anchor overlays (`apply_*_overlays.py`) that edit specific blocks of upstream files and refuse to edit if the anchor drifted.
2. **`config.yaml`** is the DeerFlow `AppConfig` used by research runs: 8 model stanzas, the tool set (bridge-owned `web_search`/`web_fetch`/`prediction_market_search` plus sandbox tools), host bash, summarization/loop-detection tuning, and the `scoped-researcher` custom subagent.
3. **`extensions_config.json`** is a template registering two DRF MCP servers (KG + simulation) that the orchestrator renders into `deer-flow/extensions_config.json`.
4. **`runtime_skill_sync.py`** deterministically deploys the four DRF-owned skill bundles from `deerflow_bridge/skills/` into `deer-flow/skills/public/` with manifest hashing, a cross-process lock, staging, an atomic directory swap and post-verification; the research child re-verifies the hashes before it does any work.

Application points: `setup.sh` (install-time, `setup.sh:572-713`) and `_sync_deerflow_bridge_if_stale` (launch-time drift guard before every research subprocess, `backend/app/services/pipeline_orchestrator.py:1441-1745`).

---

## Walkthrough (source order)

### A. `deerflow_bridge/patches/apply_lead_agent_overlays.py`

- **Module docstring** (`:1-14`): declares two contracts: YAML `trim_tokens_to_summarize: null` must mean "summarize the whole discarded segment" (not LangChain's 4K default), and `summarization.model_name: null` must inherit the run's model instead of the first configured provider.
- **`LEAD_AGENT_PATH`** (`:23-25`) = `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (relative to the DeerFlow root). **Target verified present** in `deer-flow/` (558 lines) and `deer-flow-2.0.0/` (545 lines).
- **Four (old, new, label) transforms** (`:27-89`, tuple at `:84-89`):
  1. `_OLD_TRIM_BLOCK` → `_NEW_TRIM_BLOCK` (`:27-46`) "explicit null trim forwarding": upstream only sets `kwargs["trim_tokens_to_summarize"]` when the config value is not None; the patched block always puts `"trim_tokens_to_summarize": config.trim_tokens_to_summarize` into the kwargs dict, so `None` reaches LangChain. LangChain's default when the kwarg is omitted is `_DEFAULT_TRIM_TOKEN_LIMIT = 4000` (`deer-flow/backend/.venv/lib/python3.12/site-packages/langchain/agents/middleware/summarization.py:77,169`).
  2. `_OLD_SUMMARY_SIGNATURE` → `_NEW_SUMMARY_SIGNATURE` (`:48-56`) "runtime model factory parameter": adds keyword `model_name: str | None = None` to `_create_summarization_middleware`.
  3. `_OLD_SUMMARY_MODEL_BLOCK` → `_NEW_SUMMARY_MODEL_BLOCK` (`:58-73`) "runtime model inheritance": `summary_model_name = config.model_name or model_name`; if set, `create_chat_model(name=summary_model_name, thinking_enabled=False, ...)`, else the default (first) model.
  4. `_OLD_SUMMARY_FACTORY_CALL` → `_NEW_SUMMARY_FACTORY_CALL` (`:75-82`) "call-site forwarding": `build_middlewares` passes `model_name=model_name` into the factory.
- **`apply(deerflow_root) -> str`** (`:92-129`):
  - Input: DeerFlow root path. Returns `"missing"` if the target file is absent (`:100-102`).
  - For each transform: skip if `new` already present (`:107-108`); raise `RuntimeError("lead-agent overlay context drifted while applying <label>; refusing an unsafe edit")` if `old` absent (`:109-113`); else replace the **first** occurrence (`:114`). Note: unlike the other overlays it does not require `old` to occur exactly once.
  - All four edits accumulate in memory; nothing is written if any raises. Returns `"already_applied"` if nothing changed (`:117-118`).
  - Side effect: writes `<target>.py.tmp`, `os.replace` onto the target, then best-effort unlinks the tmp (`:120-128`). Returns `"applied"`.
- **CLI** (`:132-138`): `python apply_lead_agent_overlays.py <deer-flow-root>`; prints status; exit 2 on `"missing"`; usage error → `SystemExit` message.
- **Deployed state** (read-only dry check): all four `new` blocks present in `deer-flow/.../agent.py` (e.g. `agent.py:115-117`, `:127-130`, `:328-330`); all four `old` anchors present exactly once in the vendor seed, so a fresh seed would apply cleanly.

### B. `deerflow_bridge/patches/apply_model_factory_overlays.py`

- Docstring (`:1-7`): `context_window_tokens` is DRF budgeting metadata (read by `deerflow_research.py:681-728`); DeerFlow's permissive `ModelConfig` would forward it to the provider constructor and LangChain would send it as an OpenAI request kwarg, which providers reject.
- **`MODEL_FACTORY_PATH`** (`:16-17`) = `backend/packages/harness/deerflow/models/factory.py`. Target verified present in both trees.
- **Transform** (`:19-29`): appends `"context_window_tokens",` (plus a comment) after `"supports_vision",` inside the `exclude={...}` set of `model_dump`. Deployed: `deer-flow/.../models/factory.py:113-125`.
- **`apply()`** (`:32-55`): `"missing"` if the target is absent; `"already_applied"` if the patched tail is present; raises `RuntimeError("model-factory overlay context drifted ...")` unless the original tail occurs **exactly once** (`:40-43`); otherwise the same tmp + `os.replace` write (`:46-54`) → `"applied"`.
- **CLI** (`:58-65`): exit 2 on `"missing"`.

### C. `deerflow_bridge/patches/apply_subagent_overlays.py`

- Docstring (`:1-16`): never copy whole client/task-tool/executor modules across versions (that would erase tracing, session, callback and token-accounting code); change only these contracts: the embedded client passes its exact `AppConfig`; `model: inherit` reads the active model from `configurable` when metadata is empty; provider fallbacks and all-denied evidence tasks end as FAILED; the application-wide subagent lifecycle lease wraps execution.
- **Targets** (`:25-31`): `backend/packages/harness/deerflow/client.py`, `.../tools/builtins/task_tool.py`, `.../subagents/executor.py`. All verified present in both trees.
- **Client context transform** (`:33-38`): `context = {"thread_id": thread_id}` → `context = {"thread_id": thread_id, "app_config": self._app_config}`. Marker: `"task subagents must receive the exact per-client config"` (`:308`). Deployed at `deer-flow/.../client.py:628-630`.
- **Client usage-accounting transform** (LOOP-017 F1, `:40-121`): replaces `counted_usage_ids: set[str]` first-seen-wins dedup with `counted_usage_by_id: dict[str, dict[str,int]]`:
  - First snapshot for an id: record it and add the full amounts to `cumulative_usage` (`:108-120`).
  - Later snapshot for the same id: compute `max(0, new - prev)` per field (`:92-94`); if all three deltas are 0 → return `None` (identical re-arrival counts zero, `:95-96`); otherwise raise `prev` to the per-field max, add the deltas, and return the delta dict (`:97-107`). Shrinking values are never subtracted.
  - Snapshots with no `msg_id`: counted in full each time (unchanged upstream behavior, `:113-120`).
  - Marker `_CLIENT_USAGE_MARKER` (`:49`). Deployed at `client.py:638-683`.
- **Task-tool transform** (`:123-133`): `parent_model = metadata.get("model_name")` → `parent_model = metadata.get("model_name") or configurable.get("model_name") or configurable.get("model")`, with `configurable = runtime.config.get("configurable", {})`. Marker `"embedded clients carry the active model under"` (`:337`). Deployed at `task_tool.py:267-274`.
- **Executor lifecycle-lease wrapper** (`:135-153`): renames `_aexecute(self, task, result_holder=None)` to `_aexecute_under_lease` and inserts a new `_aexecute` that does `async with async_subagent_lifecycle_lease(): return await self._aexecute_under_lease(...)` (lease from patched `model_concurrency_middleware`). Applied only if `"async def _aexecute_under_lease("` is absent (`:365`). Deployed at `executor.py:533-550`.
- **Executor provider-fallback guard** (`:155-194`): inserted immediately **before** the log line `Subagent ... completed async execution`. Scans `final_state["messages"]` in reverse for an `AIMessage` whose `additional_kwargs["deerflow_error_fallback"]` is truthy (the flag set by `LLMErrorHandlingMiddleware`, `deer-flow/.../llm_error_handling_middleware.py:236-243`). If found: `result.try_set_terminal(SubagentStatus.FAILED, error="LLM provider fallback inside subagent (reason=<error_reason|provider>)", ai_messages=..., token_usage_records=collector.snapshot_records())`, logs an error, returns. Deployed at `executor.py:652-682`.
- **Executor `import json`** (`:196-197`) and **control-failure helper** `_drf_subagent_control_failure(messages, final_result)` (`:199-244`), inserted after `logger = logging.getLogger(__name__)` (deployed `executor.py:43-84`). Returns an error string or `None`:
  - If the **first line** of `final_result` starts with `SUBAGENT_OUTCOME: BLOCKED`, return `"Subagent reported blocked outcome (code=<code>)"` where `code` is taken from the first `code=` token (default `unspecified`) (`:205-214`).
  - Otherwise iterate tool messages named `web_search`/`web_fetch` (`:216-240`): `attempts += 1`; JSON payload with `error == "research_budget_exhausted"` → `denials += 1`; JSON `web_search` with a non-empty `results` list → success; JSON `web_fetch` without `error` → success; non-JSON content that is non-empty and does not start with `Error:` → success.
  - Returns `"Subagent evidence tools exhausted before any usable result"` only if `attempts and denials and successes == 0` (`:241-242`). Errors other than budget denials alone never trigger this.
- **Executor terminal guard** (`:246-267`): inserted before `result.try_set_terminal(SubagentStatus.COMPLETED, result=final_result, ...)`; if the helper returns a string → `FAILED` with that error, `token_usage_records=token_usage_records`. Deployed at `executor.py:761-774`.
- **`_updated_source`** (`:270-278`): marker check → unchanged; else requires the anchor exactly once, else `RuntimeError("subagent overlay context drifted ...")`.
- **`_atomic_write`** (`:281-290`): tmp + `os.replace`.
- **`apply()`** (`:293-404`): `"missing"` unless **all three** targets exist (`:301-302`). Builds `updates: dict[Path,str]` for the client (context, then declaration+body usage transform — each must occur exactly once, `:318-329`), the task tool (`:333-340`), and the executor (control helper + import `:344-364`, lease wrapper `:365-374`, fallback guard `:375-386`, terminal guard `:387-398`). Writes every changed file atomically at the end (`:402-403`); returns `"applied"` if any file changed, else `"already_applied"`. Any drift raises before any write.
- **CLI** (`:407-410`): prints the status; **does not exit non-zero on `"missing"`** (unlike the other two overlays).
- **Deployed state**: all markers present in `deer-flow/`; all anchors present exactly once in the vendor seed.

### D. `deerflow_bridge/patches/middlewares/loop_detection_middleware.py` (full-file replacement)

Target: `deer-flow/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` (deployed copy byte-identical). **Diff vs vendor seed** is purely additive: the method `_reset_run_scoped_loop_state` (`:524-543`) and its calls from `before_agent` (`:547`) and `abefore_agent` (`:553`).

- **Constants** (`:64-70`): warn 3, hard 5 (identical tool-call sets), window 20, LRU 100 threads, per-tool frequency warn 30 / hard 50, `_MAX_PENDING_WARNINGS_PER_RUN = 4`.
- **`_normalize_tool_call_args`** (`:73-96`): dict → as-is; JSON string → parsed dict or `({}, fallback_key)`; None → `({}, None)`; other → `({}, json.dumps(...))`.
- **`_stable_tool_key`** (`:99-139`): `read_file` keys by `path:startBucket-endBucket` with 200-line buckets (`:101-121`); `write_file`/`str_replace` hash the full args (`:126-129`); otherwise only the salient fields `path,url,query,command,pattern,glob,cmd` (`:131-134`), else fallback, else full args.
- **`_hash_tool_calls`** (`:142-160`): sorts `name:key` strings (order-independent), MD5, first 12 hex chars.
- **Messages** (`:163-171`): `[LOOP DETECTED] ...` warnings and `[FORCED STOP] ...` hard-stop texts.
- **`LoopDetectionMiddleware.__init__`** (`:205-233`): state = `_history` (OrderedDict thread→hash list), `_warned`, `_tool_freq`, `_tool_freq_warned`, `_pending_warnings` keyed by `(thread_id, run_id)`, touch-order map, cap `max(1, max_tracked_threads*2)` pending keys; one `threading.Lock`.
- **`from_config`** (`:235-246`): maps `LoopDetectionConfig` incl. `tool_freq_overrides` → `(warn, hard_limit)` tuples (schema: `deer-flow/.../config/loop_detection_config.py:6-20`).
- **Thread/run ids** (`:248-264`): from `runtime.context`; missing → `"default"` (all such runs share one bucket).
- **LRU eviction** (`:266-279`) and pending-warning pruning (`:281-320`).
- **`_track_and_check`** (`:322-438`): only acts if the last message is an AI message with tool calls. Appends the hash to the per-thread window (trimmed to `window_size`, `:358-360`).
  - Layer 1 (`:371-397`): `count >= hard_limit` → `(_HARD_STOP_MSG, True)`; `count >= warn_threshold` and hash not yet warned → `(_WARNING_MSG, False)`.
  - Layer 2 (`:399-436`): increments `freq[name]` per tool call (only reached if layer 1 did not return); per-tool override or global thresholds; hard → `(_TOOL_FREQ_HARD_STOP_MSG, True)`; warn once per tool name.
- **`_append_text`** (`:440-455`): appends to str/list/None content safely (list → new text block).
- **`_build_hard_stop_update`** (`:457-475`): `tool_calls=[]`, removes `tool_calls`/`function_call` from `additional_kwargs`, rewrites `finish_reason` `"tool_calls"` → `"stop"`.
- **`_apply`** (`:477-502`): hard stop → returns `{"messages": [stripped copy of last AIMessage]}`; warning → queued for the next model call (not inserted now, so tool-call/tool-result pairing is not broken for OpenAI/Moonshot validators).
- **`_reset_run_scoped_loop_state`** (`:524-543`, DRF patch): on every agent run start, drops the thread's hash history, warned sets and frequency counters → limits are per run, not per thread. Rationale in docstring: multi-pass deep research reuses one thread, and cumulative counts would force-stop `web_search` from pass 2 onward.
- **Hooks**: `before_agent`/`abefore_agent` (`:545-555`) reset + clear other runs' pending warnings; `after_model`/`aafter_model` (`:557-563`) run `_apply`; `after_agent`/`aafter_agent` (`:565-573`) drop the current run's pending warnings.
- **`_augment_request`** + `wrap_model_call`/`awrap_model_call` (`:583-616`): drain pending warnings and append one `HumanMessage(content=<deduped warnings>, name="loop_warning")` after all existing messages.
- **`reset`** (`:618-635`): manual clear for one thread or all.

### E. `deerflow_bridge/patches/middlewares/tool_error_handling_middleware.py` (full-file replacement)

Target: `.../agents/middlewares/tool_error_handling_middleware.py` (deployed byte-identical). Diff vs vendor: imports `ModelConcurrencyMiddleware` (`:138`), moves `LLMErrorHandlingMiddleware` from after Dangling (vendor seed `tool_error_handling_middleware.py:158`) to **index 0** (`:147-152`), and appends `ModelConcurrencyMiddleware()` after guardrails (`:189`).

- **`_stamp_task_subagent_status`** (`:29-56`): for tool `task` only, parses the status from string content via `deerflow.subagents.status_contract.extract_subagent_status` and merges `make_subagent_additional_kwargs(status, error=...)` into `additional_kwargs`.
- **`ToolErrorHandlingMiddleware`** (`:59-126`): `wrap_tool_call`/`awrap_tool_call` re-raise `GraphBubbleUp`, convert any other exception into `ToolMessage(status="error", content="Error: Tool '<name>' failed with <Exc>: <detail≤500 chars>. Continue with available context, or choose an alternative tool.")` (`:62-82`), and stamp successful `task` results (`:84-94`). `Command` results pass through.
- **`_build_runtime_middlewares`** (`:129-195`): final order = `[LLMErrorHandling, ToolOutputBudget, (Uploads if include_uploads → insert at index 2), ThreadData, Sandbox, (DanglingToolCall), (Guardrail if configured), ModelConcurrency, SandboxAudit, ToolErrorHandling]`. Comment `:143-146`: the first wrapper is outermost, so retries (LLMErrorHandling) sit outside the permit and each retry acquires a fresh permit; backoff sleeps hold no permit.
- **`build_lead_runtime_middlewares`** (`:198-205`): uploads + dangling.
- **`build_subagent_runtime_middlewares`** (`:208-257`): no uploads; if `model_name is None` uses `app_config.models[0].name` for the vision check (`:228-229`); optional `ViewImageMiddleware`, `DeferredToolFilterMiddleware`, `SafetyFinishReasonMiddleware`.

### F. `deerflow_bridge/patches/middlewares/model_concurrency_middleware.py` (new file)

No vendor counterpart (`deer-flow-2.0.0` lacks it); deployed byte-identical.

- **Import** (`:19-22`): `import research_budget`; on `ImportError` → `_research_budget = None` (normal DeerFlow deployments). `research_budget.py` is importable only because it is copied next to `deerflow_research.py` (`setup.sh:597`, `pipeline_orchestrator.py:1359-1362`).
- **`provider_model_lease()`** (`:25-32`): sync context manager → `research_budget.model_call_lease(1)` or no-op.
- **`async_provider_model_lease()`** (`:35-43`): → `research_budget.async_model_call_lease(1)` or no-op.
- **`async_subagent_lifecycle_lease()`** (`:46-54`): → `research_budget.async_subagent_call_lease()` or no-op (used by the executor overlay).
- **`ModelConcurrencyMiddleware`** (`:57-76`): holds one lease only while the provider handler runs. [verifier: it is the last model wrapper only within the shared runtime list; `build_middlewares` appends lead-only middlewares after that list (`deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py:311-392`), and LangChain composes the first-listed wrapper outermost (`deer-flow/backend/.venv/lib/python3.12/site-packages/langchain/agents/factory.py:219-231`). So the `wrap_model_call` hooks of SkillActivation, TodoList, DeferredToolFilter and LoopDetection run inside the lease. In subagents, DeferredToolFilter is appended after it as well (`tool_error_handling_middleware.py:242-245`)]
- Even with the module importable, leases are no-ops unless `RESEARCH_MODEL_LEASE_DB` or `RESEARCH_BUDGET_DB` is set (`deerflow_bridge/research_budget.py:78-106`, `:916`, `:1105`); the orchestrator always sets `RESEARCH_MODEL_LEASE_DB` (`pipeline_orchestrator.py:2408-2410`).

### G. `deerflow_bridge/patches/middlewares/summarization_middleware.py` (full-file replacement)

Target: `.../agents/middlewares/summarization_middleware.py` (deployed byte-identical). Diff vs vendor is additive: the env knob (`:24-67`, `:159-172`) and provider leases around the summary LLM call (`:215-223`, `:236-244`).

- **`TRIM_TOKENS_ENV = "RESEARCH_TRIM_TOKENS_TO_SUMMARIZE"`** (`:32`), sentinels `none|null|full` (`:33`).
- **`_resolve_trim_tokens_override()`** (`:36-67`): unset/blank → `(False, None)`; sentinel → `(True, None)`; positive int → `(True, n)`; non-int or `<1` → warning + `(False, None)`.
- **`SummarizationEvent`** dataclass (`:70-78`), **`BeforeSummarizationHook`** protocol (`:81-85`), thread/agent-name resolvers from `runtime.context` then `get_config()["configurable"]` (`:88-109`), `_tool_call_path` (`:112-121`), `_clone_ai_message` (`:124-131`), `_SkillBundle` (`:134-142`).
- **`DeerFlowSummarizationMiddleware.__init__`** (`:148-191`): applies the env override into `kwargs["trim_tokens_to_summarize"]` before `super().__init__` (logs `configured -> override`); defaults: skills root `/mnt/skills`, read-tool names `{read_file, read, view, cat}`, preserve 5 skills / 25K tokens / 5K per skill (config passes 3/15K/5K); builds `self._summary_model = self.model.with_config(tags=[...existing, TAG_NOSTREAM])` so the summary call is not streamed to the UI.
- **`_summarize_with` / `_asummarize_with`** (`:201-247`): empty input → `"No previous conversation history."`; prompt `None` → `"Previous conversation was too long to summarize."`; otherwise invoke the nostream model inside `provider_model_lease()` / `async_provider_model_lease()` with metadata `lc_source=summarization`. **Any exception** (including lease errors) → returns the string `"Error generating summary: <e>"`.
- **`_build_summary_prompt`** (`:249-257`): trims via the parent `_trim_messages_for_summary`, `get_buffer_string`, formats `summary_prompt`.
- **`before_model`/`abefore_model` → `_maybe_summarize`/`_amaybe_summarize`** (`:259-315`): token count → `_should_summarize` → cutoff → `_partition_with_skill_rescue` → `_preserve_dynamic_context_reminders` → hooks → summary → returns `[RemoveMessage(REMOVE_ALL_MESSAGES), HumanMessage(name="summary", "Here is a summary of the conversation to date:\n\n..."), *preserved]` (`:317-322`).
- **Skill rescue** (`:342-489`): finds AIMessage + paired ToolMessage bundles that read files under the skills root, keeps the newest bundles within the count/token budgets (dedup by skill path key), splits AIMessages so only the skill tool calls are rescued.
- **`_fire_hooks`** (`:491-513`): hook exceptions are logged and swallowed.

### H. `deerflow_bridge/patches/middlewares/title_middleware.py` (full-file replacement)

Target: `.../agents/middlewares/title_middleware.py` (deployed byte-identical). The only diff vs vendor: the async title LLM call is wrapped in `async_provider_model_lease()` (`:174-180`).

- `_should_generate_title` (`:69-89`): needs `title.enabled`, no existing title, exactly one real user message and at least one AI message.
- Sync path `_generate_title_result` (`:146-152`) never calls an LLM: it returns a local fallback title (first ≤50 chars of the user message + `...`, or `"New Conversation"`, `:124-129`).
- Async path `_agenerate_title_result` (`:154-186`) calls `create_chat_model(name=config.model_name or default, thinking_enabled=False, attach_tracing=False)` and strips `<think>` tags (`:112-122`); any exception → fallback title.
- **Effectively dormant for research runs**: `config.yaml:1286-1287` sets `title.enabled: false`.

### I. `deerflow_bridge/patches/models/patched_minimax.py` (full-file replacement, no-op on vendor seed)

Target: `.../deerflow/models/patched_minimax.py`; **byte-identical to both the deployed and vendor copies** (`cmp`). Used by `config.yaml:106`.

- Helpers (`:28-95`): `_extract_reasoning_text` joins `reasoning_details[*].text`; `_strip_inline_think_tags` moves `<think>…</think>` into a reasoning string; `_merge_reasoning` dedups; `_with_reasoning_content` writes `additional_kwargs["reasoning_content"]` (appending raw text for streaming chunks).
- **`PatchedChatMiniMax(ChatOpenAI)._get_request_payload`** (`:101-118`): forces `extra_body.reasoning_split = True` and calls `_strip_user_message_names` (`:120-136`), which removes `name` from every `role == "user"` message. This avoids MiniMax error 2013 "user name must be consistent", triggered by DeerFlow's named user messages (`summary`, `loop_warning`, ...).
- `_convert_chunk_to_generation_chunk` (`:138-200`): streaming; ignores `content.delta` events; maps `delta.reasoning_details` to `reasoning_content`; sets `response_metadata.model_provider="openai"`.
- `_create_chat_result` (`:202-239`): non-streaming; strips inline `<think>` from content and merges it with `message.reasoning_details`.

### J. `deerflow_bridge/patches/models/credential_loader.py` (full-file replacement)

Target: `.../deerflow/models/credential_loader.py` (deployed identical). Diff vs vendor: adds `subprocess`/`sys` imports and the macOS Keychain fallback (`:130-177`, `:247-252`).

- `OAUTH_ANTHROPIC_BETAS = "oauth-2025-04-20,claude-code-20250219,interleaved-thinking-2025-05-14"` (`:28`); `is_oauth_token` = contains `"sk-ant-oat"` (`:31-33`).
- `ClaudeCodeCredential.is_expired` (`:45-49`): `expires_at <= 0` → never expired; otherwise expired 60 s before `expires_at` (ms).
- `_read_secret_from_file_descriptor` (`:90-107`): `os.read(fd, 1 MiB)`.
- **`load_claude_code_credential()`** (`:201-254`), lookup order:
  1. `$CLAUDE_CODE_OAUTH_TOKEN` or `$ANTHROPIC_AUTH_TOKEN` (`:221-226`). If set, the result is returned **without trying later sources**, even if it strips to empty (then `None`).
  2. `$CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` (`:228-233`).
  3. `$CLAUDE_CODE_CREDENTIALS_PATH`, then `~/.claude/.credentials.json` (`:235-245`, `:117-127`), reading `claudeAiOauth.accessToken`; an expired token → `None` + warning (`:194-196`).
  4. macOS only: `subprocess.run(["security","find-generic-password","-s","Claude Code-credentials","-w"], timeout=10)` (`:149-158`). Any failure/timeout/bad JSON → `None`.
  Direct-env and FD tokens carry no expiry, so they are never treated as expired.
- **`load_codex_cli_credential()`** (`:257-278`): `$CODEX_AUTH_PATH` or `~/.codex/auth.json`; accepts top-level `access_token`/`token` or nested `tokens.access_token`; `account_id` likewise.

### K. `deerflow_bridge/patches/models/claude_provider.py` (full-file replacement)

Target: `.../deerflow/models/claude_provider.py` (deployed identical). Diff vs vendor: the thinking ratio changes from 0.8 to 0.5, OAuth-preference, prompt caching is no longer force-disabled for OAuth and is rewritten (anchor + incremental breakpoints), the `_create`/`_acreate` strip overrides are removed, and the Retry-After cap is new.

- **Constants** (`:44-81`): `MAX_RETRIES=3`; `DEFAULT_RETRY_AFTER_CAP_S=120.0`; `THINKING_BUDGET_RATIO=0.5`; `_DEFAULT_BILLING_HEADER = "x-anthropic-billing-header: cc_version=2.1.85.351; cc_entrypoint=cli; cch=6c6d5;"` overridable via `ANTHROPIC_BILLING_HEADER` (read at import, `:62-63`); `PROMPT_CACHE_ENV="DEERFLOW_CLAUDE_PROMPT_CACHE"`; `MAX_CACHE_BREAKPOINTS=4`; `CACHEABLE_BLOCK_TYPES={text,image,tool_use,tool_result,document}`.
- `_env_prompt_cache_override` (`:84-91`): `0/false/no/off` → False; `1/true/yes/on` → True; else None.
- `RetryAfterCapExceededError(RuntimeError)` (`:94-99`); `_retry_after_cap_ms` (`:102-109`): env `CLAUDE_RETRY_AFTER_CAP_S`, invalid → 120, negative clamps to 0 (= uncapped).
- **`ClaudeChatModel(ChatAnthropic)`** (`:112`): fields `enable_prompt_caching=True`, `prompt_cache_size=3`, `auto_thinking_budget=True`, `retry_max_attempts=3`; private `_is_oauth`, `_oauth_access_token` (`:128-133`).
- **`model_post_init`** (`:141-219`): validates `retry_max_attempts >= 1`; reads the current key from `anthropic_api_key`; **if it is not already an OAuth token, calls `load_claude_code_credential()` and, when found, replaces the key with the OAuth token** (even if a real non-placeholder API key was configured; logs "Preferring Claude Code OAuth credential", `:170-182`). If the final key is OAuth: `_is_oauth=True`, adds header `anthropic-beta: <OAUTH_ANTHROPIC_BETAS>` (`:191-194`), and after `super().model_post_init` swaps `api_key=None, auth_token=<token>` on both SDK clients (`:217-225`).
- **`_get_request_payload`** (`:238-268`), the single choke point for all request paths: OAuth → `_apply_oauth_billing`; cache enabled → `_apply_prompt_caching`, else `_strip_cache_control`; `auto_thinking_budget` → `_apply_thinking_budget`.
- **`_apply_oauth_billing`** (`:270-305`): puts exactly one billing text block at `system[0]` (dedups existing ones); sets `metadata.user_id` = JSON `{device_id: sha256("deerflow-<hostname>"), account_uuid: "deerflow", session_id: <new uuid4 per request>}` if absent.
- **`_apply_prompt_caching`** (`:307-383`): strips all existing markers, then marks (1) the last system text block (or the last tool if there is no system) and (2) up to the remaining budget, the last cacheable block of each of the newest `prompt_cache_size` messages, newest first; string content is converted to a single text block. Total ≤4 `{"cache_control":{"type":"ephemeral"}}` markers.
- **`_apply_thinking_budget`** (`:385-396`): only when `thinking.type == "enabled"` and no `budget_tokens`: `budget_tokens = int(max_tokens * 0.5)` (default max_tokens 8192).
- **`_strip_cache_control`** (`:398-425`): removes markers from system/messages (and their content blocks) and tools.
- **`_generate` / `_agenerate`** (`:433-483`): re-patch OAuth on the client; loop `attempt in 1..retry_max_attempts`; retries only on `anthropic.RateLimitError` / `anthropic.InternalServerError`, sleeping `_calc_backoff_ms`; re-raises on the last attempt.
- **`_calc_backoff_ms`** (`:485-514`): `2000 * 2^(attempt-1)` + 20% (attempt 1 → 2400 ms, 2 → 4800 ms); an integer `Retry-After` header replaces it if ≤ cap, else raises `RetryAfterCapExceededError` (raised from inside the `except` block, so it chains the original 429). Non-integer Retry-After (e.g. `"1.5"` or an HTTP date) → ignored, exponential backoff.

### L. `deerflow_bridge/patches/tests/` (pytest; run in DeerFlow's venv)

- **`conftest.py`** (`:10-23`): inserts `<repo>/deer-flow/backend/packages/harness` and `<repo>/deer-flow/backend` at the front of `sys.path` (so tests import the **deployed** copies), and installs a `MagicMock` for `deerflow.subagents.executor` to break DeerFlow's import cycle.
- **`test_client_usage_overlay.py`** (`:1-137`): loads the overlay module by path; builds a synthetic `deer-flow` tree whose `client.py` embeds the original usage blocks (other targets carry markers so their transforms are skipped). Tests: the red baseline undercounts 10→110 as 10 (`:78-85`); apply is idempotent (`:88-94`); patched accounting gives delta 90/10/100, zero on identical re-arrival, no subtraction on shrink, full count for id-less snapshots (`:97-120`); drift → `RuntimeError` (`:123-127`); the deployed client carries `counted_usage_by_id` (skips if absent, `:130-137`).
- **`test_subagent_runtime_contract.py`** (`:1-369`): `real_executor_module` fixture temporarily mocks heavy deps and imports the real executor (`:36-72`). Tests: task tool inherits `parent_model="minimax"` from `configurable` with empty metadata and passes `app_config` through to `get_available_tools` (`:79-157`); a fallback AIMessage → FAILED `"LLM provider fallback inside subagent (reason=auth)"` (`:160-202`); search+fetch both budget-denied → FAILED `"Subagent evidence tools exhausted before any usable result"` (`:205-266`); one successful search plus a later denial → COMPLETED (`:269-326`); `SUBAGENT_OUTCOME: BLOCKED code=no_usable_evidence` → FAILED (`:329-369`).
- **`test_lead_agent_trim_none.py`** (`:1-191`): factory forwards `trim_tokens_to_summarize=None` (`:57-82`); null summary model inherits `active-model` (`:85-116`); an explicit `summary-model` wins (`:119-150`); `build_middlewares` forwards `model_name` (`:153-191`).
- **`test_model_factory_metadata.py`** (`:1-42`): `create_chat_model` must not pass `context_window_tokens` to the provider class.
- **`test_summarization_trim_env.py`** (`:1-90`): the env override matrix (unset preserves None/int/LangChain default; int overrides; sentinels force None; `abc,-5,0,1.5` ignored; blank = unset).

### M. `deerflow_bridge/runtime_skill_sync.py`

- **Constants** (`:40-64`): `SCHEMA_VERSION=1`; state file `.drf-runtime-skill-manifest.json`; lock file `.drf-runtime-skill-sync.lock`; stage prefix `.drf-public-stage-`; `DEFAULT_REQUIRED_SKILLS = (actor-ontology-research, deep-research, forecast-visuals, prediction-markets)`; empty `RUNTIME_GENERATED_ALLOWLIST` and `PUBLIC_ROOT_FILE_ALLOWLIST`; safe name regex `^[A-Za-z0-9][A-Za-z0-9._-]*$`; source noise = `.DS_Store`, `*.pyc`, `*.pyo`, any `__pycache__` path part.
- **`SkillSyncError(RuntimeError)`** (`:67-68`).
- **Hash helpers** (`:71-89`): canonical JSON (`sort_keys`, compact separators, UTF-8); sha256 of bytes and of files (1 MiB chunks).
- **`_build_skill_manifest(skill_root, name, source)`** (`:106-170`): rejects a missing or symlinked root; `os.walk(followlinks=False)` with sorted dirs/files; noise filtering **only when `source=True`**; symlinked subdirs or non-regular files → error; requires exactly one top-level `SKILL.md`. Output: `{schema_version, skill, directories, files:[{path,sha256,size}], manifest_hash = sha256(canonical(core)), skill_md_sha256, lazy_resource_hashes: {path: sha for non-SKILL.md}}`.
- **`_discover_source_manifests`** (`:173-186`): every non-symlink child dir **that has a `SKILL.md`** becomes a managed skill (so dropping a new skill dir into `deerflow_bridge/skills/` auto-manages it).
- **`_bundle_manifest_hash`** (`:189-197`): sha256 of `{schema_version, skills: {name: manifest_hash}}`.
- **`_state_payload`** (`:200-212`): the persisted state `{schema_version, managed_by:"DeepResearchForecast", managed_skills, bundle_manifest_hash, allowlists, skills:{full manifests}}`.
- **`_load_state`** (`:215-235`): validates schema version, owner, managed_skills names; unsafe/unreadable → `SkillSyncError`.
- **`_exclusive_lock(path, timeout)`** (`:245-271`): `fcntl.flock(LOCK_EX|LOCK_NB)` polled every ≤50 ms until the deadline; timeout → `SkillSyncError("timed out waiting ...")`.
- **`_copy_source_bundle`** (`:274-288`): recreates only manifest-listed dirs/files with `shutil.copy2` (noise is never copied).
- **`_copy_unmanaged_public_skills`** (`:291-314`): copies every **non-managed** top-level entry of the live `skills/public` into the stage (dirs via `copytree(symlinks=True)`, top-level symlinks preserved as links; top-level files only if allowlisted, i.e. none → root `.DS_Store` etc. are pruned).
- **`_atomic_exchange(left, right)`** (`:317-353`): `ctypes` call into libc: macOS `renamex_np(..., RENAME_SWAP=0x2)`, Linux `renameat2(AT_FDCWD=-100, ..., RENAME_EXCHANGE=0x2)`; other platforms or a missing symbol → `SkillSyncError`.
- **`_fsync_directory`** (`:356-364`).
- **`_deployed_manifests`** (`:367-378`) → `_build_skill_manifest(..., source=False)` (no noise filter, so stray `__pycache__` in the live tree counts as drift).
- **`_result_payload`** (`:381-402`): `{schema_version, outcome, source_manifest_hash, deployed_manifest_hash, deployed_path, managed_skills, pruned_skills, runtime_generated_allowlist, skills}`.
- **`sync_runtime_skills(source_root, deployed_public_root, *, required_skills=DEFAULT_REQUIRED_SKILLS, lock_timeout_seconds=60.0)`** (`:405-530`):
  1. The parent of `deployed_public_root` must be an existing non-symlink dir (`:416-418`). Lock at `<parent>/.drf-runtime-skill-sync.lock` (`:421-422`).
  2. Discover the source; any required name missing → `SkillSyncError("required runtime skill source bundle(s) missing: ...")` (`:423-428`).
  3. `previous_managed` = the state's `managed_skills`, or the current source names if there is no state; `pruned_skills = previous - current` (`:430-437`).
  4. **Fast path "verified"** (`:439-461`): state equals expected AND nothing to prune AND the live hash of the managed bundles equals expected AND per-skill hashes match → return without writing.
  5. **Update path** (`:463-523`): `tempfile.mkdtemp(prefix=".drf-public-stage-", dir=<parent>)`; copy unmanaged entries, then every source bundle; re-hash the staged bundles and compare to source (`:478-486`); write the state file into the stage (`:487`); if the live dir exists → atomic swap (`live_swapped=True`), else `os.replace(stage, live)`; fsync the parent; re-read state + re-hash live; mismatch → swap back (if swapped) and raise (`:496-506`); success → `rmtree` the old tree (now at the stage path; failure recorded as `cleanup_warning`) → outcome `"updated"`.
  6. Any non-`SkillSyncError` exception is wrapped as `SkillSyncError("runtime skill staging/deployment failed: ...")` (`:526-527`); `finally` removes the stage if it was not swapped (`:528-530`).
- **`verify_runtime_sync_payload(payload, deployed_public_root)`** (`:533-572`): run by the research child. Requires schema 1, `deployed_path` resolving to the same dir, `managed_skills` == keys of `skills`; re-hashes the live bundles; each must equal the payload's manifest; the bundle hash must equal both `source_manifest_hash` and `deployed_manifest_hash`; the persisted state's `bundle_manifest_hash` must match. Returns the payload with `runtime_verified=True`.
- **CLI** (`:575-615`): `--source-root`, `--deployed-public-root`, repeatable `--required-skill`, `--lock-timeout` (default 60). Success → JSON result on stdout, exit 0; any exception → `{"schema_version":1,"outcome":"failed","error":...}` on **stderr**, exit 2.

### N. `deerflow_bridge/config.yaml` (DeerFlow `AppConfig`; deployed `deer-flow/config.yaml` is byte-identical today)

- `config_version: 11` (`:18`); `log_level: info` (`:24`); `token_usage.enabled: true` (`:32-33`).
- **Models** (`:40-291`), 8 active stanzas (all keys `$VAR`):

| name | `use` | model | key / endpoint | output / context | thinking | notes |
|---|---|---|---|---|---|---|
| `claude` (`:45-67`) | `deerflow.models.claude_provider:ClaudeChatModel` | `claude-opus-4-8` | OAuth (no api_key) | max_tokens 64000 / ctx 200000 | `supports_thinking: false` (comment `:52-57`: double-nested thinking payload broke every call) | vision; `enable_prompt_caching: true` |
| `antigravity` (`:76-90`) | `deerflow.models.patched_openai:PatchedChatOpenAI` | `gemini-3-flash-preview` | `$LLM_FALLBACK_API_KEY` / `$LLM_FALLBACK_BASE_URL` | 65536 / 1048576 | `reasoning_effort: low` | timeout 900, retries 2 |
| `minimax` (`:98-127`) | `deerflow.models.patched_minimax:PatchedChatMiniMax` | `MiniMax-M3` | `$MINIMAX_API_KEY`, `https://api.minimaxi.com/v1` | 512000 / 1000000 | `extra_body.thinking.type` adaptive / disabled | vision; timeout 900 |
| `deepseek` (`:137-158`) | `deerflow.models.patched_deepseek:PatchedChatDeepSeek` | `deepseek-v4-pro` | `$DEEPSEEK_API_KEY`, `api_base` | 64000 / 1000000 | enabled (+ `reasoning_effort: high`) / disabled | uses `api_base` + `timeout` |
| `qwen` (`:174-191`) | `langchain_openai:ChatOpenAI` | `qwen3.7-max` | `$DASHSCOPE_API_KEY`, dashscope-intl | 32768 / 1000000 | `extra_body.enable_thinking` true/false | |
| `glm` (`:207-226`) | `langchain_openai:ChatOpenAI` | `glm-5.3` | `$ZHIPUAI_API_KEY`, `https://open.bigmodel.cn/api/coding/paas/v4` | 65536 / 200000 | `thinking.type` enabled/disabled | display name says GLM-4.6 |
| `codex` (`:235-243`) | `deerflow.models.openai_codex_provider:CodexChatModel` | `gpt-5.5` | `~/.codex/auth.json` | — | `reasoning_effort: high` | `retry_max_attempts: 3` |
| `kimi` (`:251-291`) | `langchain_openai:ChatOpenAI` | `kimi-k2.7` | `$KIMI_API_KEY`, `https://api.kimi.com/coding/v1`, `User-Agent: claude-cli/1.0.0` | 32768 / 200000 | temperature 1.0 + thinking enabled / 0.6 + disabled | gateway hard-validates temperature |

  Order matters: `claude` is `models[0]`, the default for anything that falls back to "first model" (title model, subagent vision check, unpatched summarization).
  `:293-699` are commented examples (Doubao, OpenAI, Ollama, Anthropic, Gemini, MiMo, DeepSeek, Kimi, Novita, MiniMax intl/CN, OpenRouter, vLLM, MindIE).
- **Tool groups** (`:706-710`): `web`, `file:read`, `file:write`, `bash`.
- **Tools** (`:717-881`):
  - `web_search` → `search_tools:web_search_tool` (bare module, `max_results: 10`; dispatcher picks Serper → Tavily → DDG by available key; disk cache knobs `RESEARCH_SEARCH_CACHE_*`) (`:730-735`).
  - `web_fetch` → `cached_fetch:web_fetch_tool` (disk-cached Jina reader; `timeout: 30`; knobs `RESEARCH_SOURCE_CACHE_*`) (`:799-802`).
  - `prediction_market_search` → `market_tools:prediction_market_search_tool` (Polymarket Gamma, keyless) (`:826-828`).
  - `image_search` → `deerflow.community.image_search.tools:image_search_tool` (`:832-835`).
  - Sandbox tools `ls`, `read_file`, `glob` (200), `grep` (100), `write_file`, `str_replace`, `bash` (`:847-881`). Bare module names resolve because the child runs with `sys.path[0] == deer-flow/` (comment `:822-825`).
- `tool_search.enabled: false` (`:892-893`) → MCP tools, when loaded, are bound directly rather than deferred.
- **`tool_output`** (`:907-923`): externalize >12000 chars to `.tool-results` (2000-char head / 1000-char tail preview); fallback truncation 30000 (8000/3000); `read_file`/`read_file_tool` exempt; `web_fetch` threshold 12000 (LOOP-009).
- **`loop_detection`** (`:931-954`): 3/5/20/100/30/50; overrides `web_search` and `web_fetch` warn 100 / hard 150 (per run thanks to the bridge reset).
- `safety_finish_reason.enabled: true` with built-in detectors (`:970-971`).
- `uploads` (`:998-1016`): 10 files, 50 MiB / 100 MiB, `auto_convert_documents: false`, `pdf_converter: auto`.
- **`sandbox`** (`:1018-1050`): `deerflow.sandbox.local:LocalSandboxProvider`, **`allow_host_bash: true`** (`:1036`; justified as a trusted single-user deployment; enables script skills like forecast-visuals); output caps bash 20000 / read_file 50000 / ls 20000.
- **`subagents`** (`:1168-1226`): `timeout_seconds: 1800`, `max_turns: 160`, `max_concurrent: 5` (clamped [1,8]; env `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` overrides, per `deer-flow/.../config/subagents_config.py:165-190`). Custom agent **`scoped-researcher`**: long system prompt (S1–S4 tiering, ≥2 independent origins, real fetched URLs only, ≤2 attempts per fact, disconfirmation, fixed Markdown return format) (`:1182-1214`); tools `web_search, web_fetch, prediction_market_search, read_file, write_file` (`:1215-1220`, no `bash`/`task`); skills `deep-research, prediction-markets` (`:1221-1223`); `model: inherit`; `max_turns: 120`; `timeout_seconds: 1800`. Delegation itself is only unlocked when the bridge runs with `--subagents` (comment `:1155-1160`).
- `skills.container_path: /mnt/skills` (`:1261-1271`; host path defaults to `<project root>/skills`).
- **`title.enabled: false`** (`:1286-1290`).
- **`summarization`** (`:1298-1377`): enabled; `model_name: null` (→ inherits the run model via the lead overlay); trigger tokens 80000 (`:1314-1315`); keep tokens 16000 (`:1328-1329`); **`trim_tokens_to_summarize: null`** (`:1347`); forecast "EVIDENCE LEDGER" `summary_prompt` (`:1351-1364`); skill rescue 3 / 15000 / 5000; skill read tools `read_file, read, view, cat` (`:1370-1377`).
- **`memory.enabled: false`**, `injection_enabled: false` (`:1388-1396`) to avoid cross-run contamination.
- `agents_api.enabled: false` (`:1403-1404`); `skill_evolution.enabled: false` (`:1410-1412`).
- `database: sqlite, .deer-flow/data` (`:1482-1484`); `run_events: memory` with token tracking (`:1499-1502`).
- Channels, guardrails and circuit breaker are commented out (`:1510-1669`) → no guardrail middleware, no circuit breaker.

### O. `deerflow_bridge/extensions_config.json`

- `_comment` (`:2`): states the file is opt-in (loaded only via `DEER_FLOW_EXTENSIONS_CONFIG_PATH`), both servers are degrade-safe (startup/`tools/list` never touch FalkorDB/Graphiti/sim IPC; missing graph → `{ok:false,error}`), and `{{DRF_BACKEND_PYTHON}}` / `{{DRF_REPO_ROOT}}` are rendered at deploy time.
- **`drf-kg`** (`:4-22`): stdio, `command {{DRF_BACKEND_PYTHON}}`, `args ["-m","app.mcp.kg_server"]`, env `PYTHONPATH={{DRF_REPO_ROOT}}/backend:{{DRF_REPO_ROOT}}`, `DRF_MCP_KG_GRAPH_ID`, `DRF_MCP_KG_TIMEOUT`, `FALKORDB_HOST`, `FALKORDB_PORT`, `GRAPHITI_DATA_DIR`, `MINIMAX_API_KEY` (as `$VAR`). Tools per description: `kg_search`, `kg_trace_cascade`, `kg_entity_summary`, `kg_get_entities`, `kg_centrality_priors`, `kg_graph_statistics`.
- **`drf-simulation`** (`:23-38`): `-m app.mcp.sim_server`; env `DRF_MCP_SIM_ID`, `DRF_MCP_SIM_TIMEOUT`, `MINIMAX_API_KEY`. Tools: `sim_status`, `sim_results`, `sim_interview_agents`.
- `"skills": {}` (`:40`) → DeerFlow treats every `public`/`custom` skill as enabled by default (`deer-flow/.../config/extensions_config.py:221-224`).
- Server modules exist: `backend/app/mcp/kg_server.py`, `backend/app/mcp/sim_server.py`.
- DeerFlow resolves `$VAR` values at load; unset → `""` (`deer-flow/.../config/extensions_config.py:183-190`).

### P. `deerflow_bridge/README.md`

Documents the bridge contract (handoff files, `:10-16`), a file → destination table (`:24-36`), automated install via `./setup.sh` and env overrides (`:38-60`), manual install steps (`:62-87`), and bridge hardening in `deerflow_research.py` (`:93-101`). Several statements have drifted from the code; see Surprises.

---

## Control flow

### Install time — `setup.sh` (overlay steps, in order)

1. Acquire `deer-flow/` if absent: copy `$DEERFLOW_VENDOR_DIR` (default `deer-flow-2.0.0`, `setup.sh:501`), else a shallow clone pinned to `DEERFLOW_REF=799bef6d…` (`setup.sh:503`, `:525-544`) [verifier: the clone branch is `setup.sh:530-550`; `:524-529` is the vendor-seed copy]; trim non-runtime files including `config.example.yaml` and `extensions_config.example.json` (`setup.sh:557-565`).
2. (a) copy `deerflow_research.py` (`:578-581`); (a2) copy bare modules `market_tools.py search_tools.py cached_fetch.py research_budget.py runtime_skill_sync.py linear_research.py research_gateway.py` (`:597-608`).
3. (b) `cp patches/models/*.py → deer-flow/.../deerflow/models/` (`:617-621`).
4. (b2) `python3 runtime_skill_sync.py --source-root deerflow_bridge/skills --deployed-public-root deer-flow/skills/public`; failure → `exit 1` (`:626-641`).
5. (b3) `cp patches/middlewares/*.py → .../agents/middlewares/` (`:649-653`).
6. (b4) `python3 apply_subagent_overlays.py deer-flow` — **required**, `exit 1` on non-zero (`:659-670`).
7. (b5) `python3 apply_lead_agent_overlays.py deer-flow` — **required**, `exit 1` on non-zero (`:677-688`).
8. (b6) `python3 apply_model_factory_overlays.py deer-flow` — **optional**, warning only (`:692-699`).
9. (c) copy `config.yaml` **only if `deer-flow/config.yaml` is absent** (`:704-712`).
10. Build DeerFlow's venv (`:715+`).
`extensions_config.json` is **not** deployed by setup.sh (only by the orchestrator).

### Launch time — `_sync_deerflow_bridge_if_stale(deerflow_dir)` (`pipeline_orchestrator.py:1441-1745`)

Called from `DeerFlowResearchRunner.run_research` before every research subprocess (`:2211`), once before admitting parallel lanes (`:11116`), and before synthesis-manifest runs (`:10856`).

1. Require `deerflow_bridge/deerflow_research.py` and the deployed copy, else `_DeerFlowSkillSyncError` (`:1460-1467`).
2. Load `runtime_skill_sync.py` by path and call `sync_runtime_skills(deerflow_bridge/skills, deer-flow/skills/public, required_skills=DEFAULT_REQUIRED_SKILLS)`; any error → `_DeerFlowSkillSyncError` (`:1473-1497`). Log outcome/hashes (`:1499-1510`).
3. Build sha256 pairs: `deerflow_research.py`, `runtime_skill_sync.py`, the 6 `_DEPLOYED_BRIDGE_MODULES`, and every `patches/middlewares/*.py` (`:1516-1551`).
4. Render `extensions_config.json` → `deer-flow/extensions_config.json` (atomic mkstemp + replace; unchanged bytes skipped; a render failure deletes the deployed copy) (`:1556-1578`, `:1379-1438`).
5. Copy every pair whose digest differs (`:1579-1591`); a failed copy of `runtime_skill_sync.py` → `_DeerFlowSkillSyncError`.
6. Lead overlay: if `agent.py` exists, load and `apply`; exceptions or a status other than applied/already_applied → `_DeerFlowSafetyOverlayError` (`:1599-1635`).
7. Model-factory overlay: load and `apply` without a retyped error boundary (`:1641-1659`).
8. Subagent overlay: if all three targets exist → `apply`, fail closed like the lead overlay (`:1668-1716`).
9. `config.yaml` drift → warning only, never copied (`:1721-1728`). Synced files → warning listing them (`:1729-1734`).
10. Return the skill sync result. `_DeerFlowSafetyOverlayError`/`_DeerFlowSkillSyncError` propagate (`:1736-1738`); any other exception → warning and return the skill result if one exists, else `_DeerFlowSkillSyncError` (`:1739-1745`).

Then `run_research` sets env `DRF_RUNTIME_SKILL_SYNC_REQUIRED=1` and `DRF_RUNTIME_SKILL_SYNC=<compact JSON result>` (`:2308-2319`), `RESEARCH_MODEL_LEASE_DB=<realpath>` (`:2408-2410`), and, only if `kg_graph_id` is set and `Config.RESEARCH_MCP_KG` (default true, `backend/app/config.py:521`) is on, `DEER_FLOW_EXTENSIONS_CONFIG_PATH=deer-flow/extensions_config.json` + `DRF_MCP_KG_GRAPH_ID` (`:2414-2423`); then `Popen(cmd, cwd=deerflow_dir)` (`:2428-2430`).

### Child start — `deerflow_research.py`

`runtime_skill_sync_telemetry()` (`deerflow_research.py:480-514`): no payload + required → `RuntimeError`; no payload + not required → `{"outcome":"standalone-unverified","runtime_verified":False}`; else `import runtime_skill_sync` (the deployed copy) → `verify_runtime_sync_payload(payload, <deer-flow>/skills/public)`. In `main`, a failure writes a failed `meta.json`, logs `runtime skill deployment rejected`, and **returns exit code 3** (`:16622-16647`); success logs manifest hashes and per-skill lazy-resource hashes (`:16648-16670`).

### Runtime call order inside DeerFlow (lead agent)

Lead middlewares come from `build_lead_runtime_middlewares` (section E) plus lead-only middlewares in `agent.py:281-395` (summarization `:327-332`, Title `:346`, LoopDetection `:373-376`, ...). Model call wrapping: `LLMErrorHandling` (outermost; retries) → ... → `LoopDetection.wrap_model_call` (injects warnings) → ... → `ModelConcurrency` (lease) → provider (`ClaudeChatModel`/`PatchedChatMiniMax`/...). [verifier: the order is wrong. The `wrap_model_call` order is LLMErrorHandling → ToolOutputBudget → DanglingToolCall → ModelConcurrency (lease) → SkillActivation → TodoList (plan mode) → DeferredToolFilter → LoopDetection → provider. The runtime list containing ModelConcurrency comes first (`agent.py:311`), LoopDetection is appended later (`agent.py:373-376`), and the first-listed wrapper is outermost (`langchain/agents/factory.py:224`). So loop warnings are injected inside the lease] Summarization (`before_model`) and title (`aafter_model`) take their own leases around their internal LLM calls. Subagent `task` → `SubagentExecutor._aexecute` (lifecycle lease) → `_aexecute_under_lease` → fallback/control guards.

---

## Data & artifacts

| Path | Writer | Reader | Format / key fields |
|---|---|---|---|
| `deer-flow/backend/packages/harness/deerflow/agents/lead_agent/agent.py` | `apply_lead_agent_overlays.apply` (tmp `agent.py.tmp` → `os.replace`) | DeerFlow | Python source |
| `deer-flow/.../models/factory.py` | `apply_model_factory_overlays.apply` | DeerFlow | Python source |
| `deer-flow/.../client.py`, `tools/builtins/task_tool.py`, `subagents/executor.py` | `apply_subagent_overlays.apply` | DeerFlow | Python source |
| `deer-flow/.../agents/middlewares/{loop_detection,tool_error_handling,model_concurrency,summarization,title}_middleware.py` | `setup.sh:651`; orchestrator copy on digest mismatch (`:1541-1551`) | DeerFlow | full-file copies |
| `deer-flow/.../models/{claude_provider,credential_loader,patched_minimax}.py` | `setup.sh:619` only | DeerFlow | full-file copies |
| `deer-flow/skills/public/<skill>/**` | `sync_runtime_skills` (stage + swap) | DeerFlow skill loader, sandbox `/mnt/skills` | skill bundles |
| `deer-flow/skills/public/.drf-runtime-skill-manifest.json` | `sync_runtime_skills` (`:487`) | `_load_state`, `verify_runtime_sync_payload` | JSON: `schema_version, managed_by, managed_skills, bundle_manifest_hash, runtime_generated_allowlist, public_root_file_allowlist, skills{name:{directories, files[{path,sha256,size}], manifest_hash, skill_md_sha256, lazy_resource_hashes}}` (sorted, indent 2) |
| `deer-flow/skills/.drf-runtime-skill-sync.lock` | `_exclusive_lock` | same | empty flock file, mode 0600 |
| `deer-flow/skills/.drf-public-stage-XXXX/` | `tempfile.mkdtemp` | transient | becomes the new `public/` (mode 0700) or holds the old tree until rmtree |
| `deer-flow/config.yaml` | `setup.sh:706` (only if absent) | DeerFlow `AppConfig` | YAML |
| `deer-flow/extensions_config.json` | orchestrator `_deploy_rendered_extensions_config` | DeerFlow `ExtensionsConfig` | JSON, placeholders rendered to absolute paths |
| env `DRF_RUNTIME_SKILL_SYNC` | orchestrator (`:2314`) | child `runtime_skill_sync_telemetry` | compact JSON of the `_result_payload` |
| `research_meta.json` / progress log (child) | `deerflow_research.py` | downstream | carries `runtime_skill_sync` verification result (`:16790`) [verifier: the child writes `meta.json` (`META_FILENAME = "meta.json"`, `deerflow_research.py:875`) and `research_progress.log` (`:874`). Only the orchestrator comment calls it `research_meta.json` (`pipeline_orchestrator.py:2312`)] |

In-memory structures: the loop detector's per-thread hash windows, frequency counters and `(thread, run)` pending-warning queues (section D); the client's `counted_usage_by_id` (section C); `ClaudeChatModel._is_oauth`/`_oauth_access_token`.

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_TRIM_TOKENS_TO_SUMMARIZE` | unset (config value used) | int ≥1 caps summarizer input; `none/null/full` forces full segment; invalid ignored | `summarization_middleware.py:32-67`, `:163-172` |
| `DEERFLOW_CLAUDE_PROMPT_CACHE` | unset (config `enable_prompt_caching`, default true) | `0/false/no/off` strip all markers; `1/true/yes/on` force on; read per request | `claude_provider.py:70-91`, `:227-236` |
| `CLAUDE_RETRY_AFTER_CAP_S` | 120 | max Retry-After honored; larger → `RetryAfterCapExceededError`; `0` disables cap | `claude_provider.py:51`, `:102-109`, `:504-511` |
| `ANTHROPIC_BILLING_HEADER` | `x-anthropic-billing-header: cc_version=2.1.85.351; ...` | OAuth billing block text (read at import) | `claude_provider.py:62-63` |
| `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN` | unset | direct OAuth token (highest priority) | `credential_loader.py:221-226` |
| `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` | unset | read token from an fd | `credential_loader.py:228-233` |
| `CLAUDE_CODE_CREDENTIALS_PATH` | `~/.claude/.credentials.json` | credentials JSON path | `credential_loader.py:117-127` |
| `CODEX_AUTH_PATH` | `~/.codex/auth.json` | Codex credential | `credential_loader.py:257-260` |
| `HOME` | — | home dir for credential defaults | `credential_loader.py:68-72` |
| `RESEARCH_MODEL_LEASE_DB` (fallback `RESEARCH_BUDGET_DB`) | set by orchestrator | enables model/subagent leases | `research_budget.py:78-106`; `pipeline_orchestrator.py:2408-2410` |
| `DEER_FLOW_EXTENSIONS_CONFIG_PATH` | set only with `kg_graph_id` + `RESEARCH_MCP_KG` | points DeerFlow at the rendered MCP config | `pipeline_orchestrator.py:2414-2418`; `extensions_config.py:118-122` |
| `DRF_MCP_KG_GRAPH_ID` | set with the above | default graph id for `drf-kg` | `extensions_config.json:14`; `pipeline_orchestrator.py:2418` |
| `DRF_MCP_KG_TIMEOUT`, `FALKORDB_HOST`, `FALKORDB_PORT`, `GRAPHITI_DATA_DIR`, `DRF_MCP_SIM_ID`, `DRF_MCP_SIM_TIMEOUT`, `MINIMAX_API_KEY` | inherited env; unset → `""` | MCP server env | `extensions_config.json:12-20`, `:32-36` |
| `RESEARCH_MCP_KG` | `true` | gate for the explicit MCP wiring | `backend/app/config.py:521` |
| `DRF_RUNTIME_SKILL_SYNC_REQUIRED` / `DRF_RUNTIME_SKILL_SYNC` | set by orchestrator | child must verify skill bytes | `pipeline_orchestrator.py:2313-2319`; `deerflow_research.py:489-514` |
| `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` | unset | overrides `subagents.max_concurrent` (clamp 1–8) | `config.yaml:1166`, `:1174` |
| `DEER_FLOW_PROJECT_ROOT` | unset → cwd | DeerFlow project root (config/extensions discovery) | `deer-flow/.../config/runtime_paths.py:7-16` |
| `LLM_FALLBACK_API_KEY`, `LLM_FALLBACK_BASE_URL`, `MINIMAX_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `ZHIPUAI_API_KEY`, `KIMI_API_KEY` | from `.env` | model credentials | `config.yaml:80-81,108,141,178,211,255` |
| `RESEARCH_SEARCH_CACHE_TTL_H/_DIR/_MAX_MB`, `RESEARCH_SOURCE_CACHE_DIR/_TTL_H/_MAX_MB` | 6h/200MB; 72h/500MB | search/fetch disk caches (documented in config comments) | `config.yaml:725-729`, `:792-796` |
| setup: `DEERFLOW_DIR`, `DEERFLOW_VENDOR_DIR`, `DEERFLOW_REPO`, `DEERFLOW_REF` | `./deer-flow`, `./deer-flow-2.0.0`, upstream, `799bef6d…` | runtime location / seed | `setup.sh:500-503` |
| `runtime_skill_sync` CLI `--lock-timeout` | 60 s | lock wait | `runtime_skill_sync.py:585` |
| `ClaudeChatModel` fields `enable_prompt_caching`, `prompt_cache_size`, `auto_thinking_budget`, `retry_max_attempts` | True, 3, True, 3 | caching / thinking / retries | `claude_provider.py:128-131` |
| config `loop_detection.*`, `summarization.*`, `subagents.*`, `sandbox.allow_host_bash`, `title.enabled`, `memory.enabled` | see section N | runtime behavior | `config.yaml:931-954`, `:1298-1377`, `:1168-1226`, `:1036`, `:1287`, `:1389` |

---

## External calls

| Call | Where | Notes |
|---|---|---|
| Anthropic Messages API (via `langchain_anthropic` / `anthropic` SDK) | `claude_provider.py:441`, `:468` (`super()._generate/_agenerate`) | OAuth Bearer + `anthropic-beta`, or x-api-key; retry on 429/5xx [verifier: the bridge loop catches only `RateLimitError`/`InternalServerError` (`claude_provider.py:442,449`). In the vendored anthropic 0.97.0, 529 maps to `OverloadedError`, which is not an `InternalServerError` subclass (`deer-flow/backend/.venv/lib/python3.12/site-packages/anthropic/_client.py:285-289`, `_exceptions.py:131-140`). So 529 overload gets only the SDK's own `max_retries=2`, and streaming calls skip the bridge loop entirely (Surprise 5)] |
| MiniMax OpenAI-compatible API (`api.minimaxi.com/v1`) | `patched_minimax.py:108` (payload) | `extra_body.reasoning_split=true` |
| Other providers per `config.yaml` (Quotio/Antigravity proxy, DeepSeek, DashScope, BigModel, chatgpt.com Codex, Kimi) | `config.yaml:76-291` | instantiated by DeerFlow's model factory |
| `security find-generic-password -s "Claude Code-credentials" -w` subprocess (macOS) | `credential_loader.py:153-158` | 10 s timeout; runs whenever no env/fd/file credential exists, at every `ClaudeChatModel` construction |
| libc `renamex_np` / `renameat2` via ctypes | `runtime_skill_sync.py:320-343` | atomic dir swap |
| `fcntl.flock` | `runtime_skill_sync.py:258` | cross-process lock |
| SQLite lease ledger (`research_budget`) | `model_concurrency_middleware.py:31,42,53` | via `RESEARCH_MODEL_LEASE_DB` |
| MCP stdio subprocesses `python -m app.mcp.kg_server` / `app.mcp.sim_server` | `extensions_config.json:4-38` | launched by DeerFlow's MCP client when the config is loaded |
| Summary / title LLM calls | `summarization_middleware.py:219-223`, `:240-244`; `title_middleware.py:171-180` | inside provider leases |
| Python subprocesses from setup (`python3 apply_*.py`, `python3 runtime_skill_sync.py`) | `setup.sh:632-634`, `:664`, `:682`, `:694` | |

---

## Cross-module edges

**Callers into this slice**
- `setup.sh:597-712` copies modules, runs `runtime_skill_sync.py` and the three overlays.
- `backend/app/services/pipeline_orchestrator.py:1349-1351` (helper path), `:1441-1745` (`_sync_deerflow_bridge_if_stale`: loads `runtime_skill_sync`, copies `patches/middlewares/*.py`, loads + applies all three overlays, renders `extensions_config.json`, compares `config.yaml`); call sites `:2211`, `:10856`, `:11116`.
- `deerflow_bridge/deerflow_research.py:480-514`, `:16622-16670`: `import runtime_skill_sync` (deployed copy) → `verify_runtime_sync_payload`.
- `deerflow_bridge/deerflow_research.py:681-728`: reads `context_window_tokens` from model configs (the reason for the factory overlay).
- DeerFlow itself: `agents/lead_agent/agent.py:32,37,80-153,327-332,346,373-376` (summarization/title/loop-detection), `tool_error_handling_middleware.build_*_runtime_middlewares`, `models/factory.py` (resolves `use:` classes), `subagents/executor.py` (lifecycle lease), `config/extensions_config.py` (MCP config).
- Tests: `backend/tests/test_deerflow_bridge_sync_guard.py` (sync guard + overlays, e.g. `:238`, `:264`, `:322`, `:379`, `:425`, `:556`, `:615`, `:647`, `:666`), `backend/tests/test_runtime_skill_sync.py:69-292`, `backend/tests/test_drf2_skills_config.py:634-700` (setup uses the helper; deployed skills byte-identical to tracked/clean sources), `backend/tests/test_wave9_research_speed.py:84-171` and `backend/tests/test_claude_prompt_cache.py:29-41` (load `patches/models/claude_provider.py` by path), `backend/scripts/test_deerflow_deep_research.py:73-85` (loop-detection overlay deployed byte-identical), and `deerflow_bridge/patches/tests/*`.

**This slice calls out to**
- `deerflow_bridge/research_budget.py` (`model_call_lease`, `async_model_call_lease`, `async_subagent_call_lease`, `research_budget.py:902`, `:1051`, `:1238`).
- DeerFlow internals: `deerflow.subagents.status_contract`, `deerflow.agents.middlewares.{llm_error_handling, thread_data, tool_output_budget, uploads, dangling_tool_call, sandbox_audit, view_image, deferred_tool_filter, safety_finish_reason, dynamic_context, tool_call_metadata}`, `deerflow.sandbox.middleware`, `deerflow.guardrails`, `deerflow.config.*`, `deerflow.models.create_chat_model` (all verified present in both trees).
- Bridge tool modules referenced by `config.yaml`: `search_tools.web_search_tool` (`search_tools.py:746` fallback None), `cached_fetch.web_fetch_tool` (`cached_fetch.py:840`), `market_tools.prediction_market_search_tool` (`market_tools.py:628`).
- Backend MCP servers `backend/app/mcp/kg_server.py`, `backend/app/mcp/sim_server.py` (via `extensions_config.json`).
- Skill sources `deerflow_bridge/skills/{actor-ontology-research,deep-research,forecast-visuals,prediction-markets}`.

---

## Invariants, gates, validation

- **Overlay idempotence + fail-closed drift**: every overlay checks a marker/new block first, requires the original anchor (exactly once for the factory and subagent overlays, `apply_model_factory_overlays.py:40`, `apply_subagent_overlays.py:274,309,323,346,354,366,376,388`; at least once for the lead overlay, `apply_lead_agent_overlays.py:109`), and raises rather than editing a drifted file. Writes go through tmp + `os.replace`.
- **Launch gate**: lead and subagent overlays and the skill sync are hard gates (orchestrator raises before spawning, `pipeline_orchestrator.py:1736-1738`); setup.sh `exit 1` for skill sync, subagent and lead overlays (`setup.sh:630,639,662,668,680,686`).
- **Skill-bundle provenance chain**: source manifest → staged manifest must equal source (`runtime_skill_sync.py:478-486`) → installed state and hash must equal staged (`:496-506`) → child re-hash must equal the payload and the persisted state (`:556-568`). Symlinks and non-regular files are rejected anywhere inside managed bundles (`:115-116`, `:129-130`, `:140-141`). Skill names must match `_SAFE_SKILL_NAME` (`:92-95`).
- **Lock**: one writer at a time per `deer-flow/skills` dir (`runtime_skill_sync.py:421-422`).
- **Prompt cache**: never more than 4 `cache_control` markers; never on thinking blocks (`claude_provider.py:76-81`, `:336-383`).
- **Loop detection**: thresholds validated by `LoopDetectionConfig` (`hard_limit >= warn`, `deer-flow/.../config/loop_detection_config.py:14-20,69-72`); limits are per agent run (`loop_detection_middleware.py:545-555`).
- **Subagent terminal semantics**: a fallback AIMessage, a typed `SUBAGENT_OUTCOME: BLOCKED`, or all-denied evidence tools ⇒ FAILED, never `Task Succeeded` (`apply_subagent_overlays.py:155-267`).
- **Model config hygiene**: `context_window_tokens` is excluded from provider kwargs (`factory.py:113-125` deployed).
- **Child integrity**: orchestrated children refuse to run without a valid skill-sync payload (`deerflow_research.py:489-495`, exit 3 at `:16647`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Upstream anchor drift in lead/subagent target | `RuntimeError` → orchestrator `_DeerFlowSafetyOverlayError`, research not spawned; setup `exit 1` | `apply_lead_agent_overlays.py:109-113`; `pipeline_orchestrator.py:1623-1626`, `:1702-1705` |
| Factory anchor drift | `RuntimeError` is not retyped → generic `except` → warning; **remaining steps (subagent overlay, config check) are skipped for that call**; setup only warns | `pipeline_orchestrator.py:1655`, `:1739-1745`; `setup.sh:694-698` |
| Overlay target file missing | lead/factory return `"missing"` (CLI exit 2); orchestrator skips lead if `agent.py` is absent (`:1606`) and subagent unless all 3 exist (`:1685`); subagent CLI prints `missing` with exit 0 | `apply_subagent_overlays.py:407-410` |
| Required skill bundle missing / staging copy failure / verification mismatch | `SkillSyncError`; the live tree is untouched before the swap; after the swap a hash mismatch triggers a swap back | `runtime_skill_sync.py:424-428`, `:478-486`, `:499-506`, `:528-530` |
| Lock contention > 60 s | `SkillSyncError("timed out waiting ...")` | `runtime_skill_sync.py:262-265` |
| Unsupported platform for atomic exchange (e.g. Windows) | `SkillSyncError` on any update (fast "verified" path still works) | `runtime_skill_sync.py:344-347` |
| Live skill tree edited after sync (e.g. `__pycache__` written) | child `verify_runtime_sync_payload` → `RuntimeError` → exit 3; the next orchestrator sync re-deploys | `runtime_skill_sync.py:557-559`; `deerflow_research.py:16624-16647` |
| Summary LLM failure (incl. lease error) | Returns `"Error generating summary: ..."` which **replaces** the removed history (all pre-cutoff messages are dropped) | `summarization_middleware.py:225-226`, `:283-289` |
| Title LLM failure | local fallback title | `title_middleware.py:184-186` |
| Anthropic 429 with huge Retry-After | `RetryAfterCapExceededError` instead of sleeping | `claude_provider.py:504-511` |
| Anthropic 429/5xx otherwise | up to 3 attempts with 2.4 s / 4.8 s waits [verifier: this excludes 529 `OverloadedError` (not an `InternalServerError` subclass in anthropic 0.97.0, `anthropic/_client.py:285-289`) and all `_stream`/`_astream` calls. Each bridge attempt also wraps the SDK's own `max_retries=2` (`langchain_anthropic/chat_models.py:771`)] | `claude_provider.py:439-456` |
| No Claude credential | warning; requests then fail auth | `claude_provider.py:181-182` |
| Keychain prompt blocks | 10 s timeout → no credential | `credential_loader.py:153-161` |
| Tool exception | converted to error `ToolMessage`; run continues | `tool_error_handling_middleware.py:96-126` |
| Repeated tool calls | warning at 3 identical / 30 per tool (100 for search/fetch); forced stop at 5 / 50 (150) | `loop_detection_middleware.py:371-436`; `config.yaml:931-954` |
| `research_budget` not importable | all leases are silent no-ops | `model_concurrency_middleware.py:19-22` |
| Extensions template render failure | deployed copy deleted, MCP wiring skipped; research continues | `pipeline_orchestrator.py:1563-1570` |

---

## Surprises

1. **Stray local artifacts would be deployed as skill resources (confirmed with a read-only manifest computation).** `_is_source_noise` only filters `__pycache__`, `.DS_Store`, `.pyc/.pyo` (`runtime_skill_sync.py:63-64`, `:98-103`). On disk, `deerflow_bridge/skills/forecast-visuals/scripts/` contains gitignored Claude-Code hook/session files (`scripts/.claude/data/sessions/<uuid>.json`, `scripts/logs/<uuid>/{pre,post}_tool_use.json`, `scripts/logs/user_prompt_submit.json`; `git status --ignored` shows them as `!!`). The current source manifest includes these 4 files, so the source bundle hash (`05e06e02…`) differs from the deployed state (`f14068b3…`). The next orchestrator launch will deploy them into `deer-flow/skills/public/forecast-visuals/scripts/`, where agents can read them via `/mnt/skills`. The test filter in `backend/tests/test_drf2_skills_config.py:676-679` skips dot-paths, so it is stricter than the deployer and won't catch this.
2. **Suspected: MCP servers are not actually opt-in.** The `_comment` (`extensions_config.json:2`) and the orchestrator (`pipeline_orchestrator.py:1552-1555`, `backend/app/config.py:517-520`) say the file loads only when `DEER_FLOW_EXTENSIONS_CONFIG_PATH` is set. But DeerFlow's resolver falls back to `existing_project_file(("extensions_config.json", ...))` under `project_root()` (`deer-flow/.../config/extensions_config.py:123-124`), and `project_root()` is the cwd when `DEER_FLOW_PROJECT_ROOT` is unset (`runtime_paths.py:7-16`). The research child runs with `cwd=deer-flow` (`pipeline_orchestrator.py:2430`), where the rendered file lives, and `get_available_tools(include_mcp=True)` is the only mode used (`deer-flow/.../tools/tools.py:46,119-125`; no caller passes False). So `drf-kg`/`drf-simulation` (both `"enabled": true`) may be spawned on first runs too, with an empty graph id. Not verified at runtime. [verifier: the mechanism holds, with two corrections. (1) There is a second, cwd-independent fallback. `ExtensionsConfig.resolve_config_path` also probes `Path(__file__).parents[4].parent / "extensions_config.json"`, which is `deer-flow/extensions_config.json` (`deer-flow/backend/packages/harness/deerflow/config/extensions_config.py:128-135`). (2) Scope: only legacy-engine children construct `DeerFlowClient` and so reach `get_available_tools` (`deerflow_research.py:16902-16929`). The default v3 engine returns before that and only calls `create_chat_model` (`linear_research.py:6257-6262`). Evidence lanes and synthesis are always legacy (`pipeline_orchestrator.py:2295-2300`)]
3. **Suspected: a model-factory overlay failure silently skips the subagent safety overlay.** The factory overlay is invoked without the retyped `try` used for the other overlays (`pipeline_orchestrator.py:1641-1659`). A drift `RuntimeError` reaches the generic `except Exception` (`:1739-1745`), which only warns, so the subagent overlay block (`:1668-1716`) and the config drift check never run. Research then launches. If the subagent overlay was not already applied (e.g. a re-seeded runtime), this bypasses a "required" gate.
4. **Provider patches are not drift-guarded at launch.** The orchestrator syncs `patches/middlewares/*.py` (`:1541-1551`) but never `patches/models/*.py`; those deploy only via `setup.sh:617-621`. An edit to `claude_provider.py`/`credential_loader.py` does not reach `deer-flow/` until setup re-runs (today the deployed copies are byte-identical).
5. **Suspected: the Claude retry/Retry-After cap covers only non-streaming calls.** `ClaudeChatModel` overrides `_generate`/`_agenerate` (`claude_provider.py:433-483`) but not `_stream`/`_astream`. LangChain routes `invoke` to `_stream` whenever a `_StreamingCallbackHandler` is attached (`deer-flow/backend/.venv/.../langchain_core/language_models/chat_models.py:567-569`), as with LangGraph message streaming. Those calls get only SDK retries (`ChatAnthropic.max_retries = 2`, `langchain_anthropic/chat_models.py:771`) and LLMErrorHandlingMiddleware retries. Conversely, non-streaming calls stack bridge retries (3) over SDK retries (2+1).
6. **Middleware reorder side effect.** Moving `LLMErrorHandlingMiddleware` to index 0 (`tool_error_handling_middleware.py:147-152`) shifts the `insert(2, UploadsMiddleware())` slot (`:157`): uploads now run **before** `ThreadDataMiddleware` (vendor order was ThreadData → Uploads → Sandbox; vendor seed `tool_error_handling_middleware.py:142-150`). UploadsMiddleware reads `thread_id` from the runtime context, not thread-data state (`deer-flow/.../uploads_middleware.py:190-227`), so this is probably benign; headless research has no uploads.
7. **`apply_subagent_overlays.py` CLI exits 0 on `"missing"`** (`:407-410`), unlike the other two overlays (exit 2). `setup.sh:664` checks only the exit status, so a tree without the three targets would print "Applied subagent provider inheritance + failure boundary".
8. **The deployed executor's lease wrapper doesn't match what this overlay emits.** Deployed `executor.py:533-550` has multi-line signatures for `_aexecute`/`_aexecute_under_lease`, while `_WRAPPER` (`apply_subagent_overlays.py:143-153`) writes single-line ones. The marker-only check (`:365`) accepts either, so the deployed state came from an earlier overlay version or a reformat. Harmless, but it shows "applied" does not mean "byte-produced by this file".
9. **The full-file replacements are version-coupled to a runtime that differs from the vendor seed.** `deer-flow/` and `deer-flow-2.0.0/` differ in many unpatched files (e.g. `config/subagents_config.py` default timeout 900 vs 1800). The middleware/model copies are verified additive-only relative to the **seed** (diffs in sections D–K), but if the runtime is re-seeded or upgraded, the copies will silently overwrite any newer upstream versions of those files. Only the string overlays detect drift.
10. **Credential edge cases (suspected, minor).** A set but whitespace-only `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_AUTH_TOKEN` returns `None` without trying the file or Keychain (`credential_loader.py:221-226`). A non-OAuth `ANTHROPIC_AUTH_TOKEN` replaces a configured API key, because `model_post_init` adopts any loaded credential (`claude_provider.py:170-180`) and then sends it as x-api-key. The Keychain subprocess can run at every `ClaudeChatModel` construction (summarizer, subagents) when no env/file credential exists.
11. **Summarizer failure destroys context.** On any summary exception, the "summary" is the literal error text, and `REMOVE_ALL_MESSAGES` still drops the pre-cutoff history (`summarization_middleware.py:225-226`, `:283-289`). This mirrors upstream behavior, but now a lease failure also counts as a summary failure (`:219`).
12. **OAuth billing metadata uses a fresh `session_id = uuid4()` per request** (`claude_provider.py:298`). It doesn't affect prompt-cache keys (content-based), but every request looks like a new session.
13. **Loop detection: a returned layer-1 warning skips layer-2 counting** for that response (`loop_detection_middleware.py:384-397` returns before `:400-405`), so per-tool frequency slightly undercounts. Runs without `thread_id` share the `"default"` bucket (`:248-253`).
14. **Live `skills/public` becomes mode 0700.** `tempfile.mkdtemp` creates the stage with mode 0700 and it is swapped in as the live dir (`runtime_skill_sync.py:463`, `:489-493`). Observed: `deer-flow/skills/public` is `drwx------`. This matters only for container sandboxes or other users.
15. **Post-promotion error path can leak the old tree.** If `_load_state`/`_deployed_manifests` raises *after* a successful swap (`runtime_skill_sync.py:496-497`), the `SkillSyncError` re-raises without swapping back (the rollback only covers the explicit mismatch branch `:499-503`), and `finally` keeps the stage because `live_swapped` is True (`:529`). The old tree is left in `.drf-public-stage-*` and the new tree stays live. Edge case (suspected).
16. **The upstream `deep-research` skill is replaced.** The vendor seed ships its own `skills/public/deep-research`; because DRF manages a bundle with the same name, the sync replaces it wholesale and prunes destination-only files (`runtime_skill_sync.py:304-305`, `:471-476`). This is intentional per the README "overhauled skill", but there's no namespace separation.
17. **Doc-vs-code drift (README and config comments)**:
    - `README.md:19-21`, `:46-48`, `:53`, `:67` say the vendor seed is `deer-flow-2.0-m1-rc3/`; `setup.sh:501` defaults to `deer-flow-2.0.0`, which is the only seed dir on disk.
    - `README.md:3` calls the project "DeepAgentForecast".
    - `README.md:91` references `DEERFLOW_INTEGRATION.md`, which does not exist at the repo root.
    - `README.md:31` and the manual steps (`:72-80`) cover only the `deep-research` skill and omit `apply_subagent_overlays.py`, `runtime_skill_sync.py` and `extensions_config.json`; the runtime manages 4 skills (`runtime_skill_sync.py:47-52`). [verifier: the README file table does list `apply_subagent_overlays.py` (`deerflow_bridge/README.md:34`); only the manual steps (`:64-87`) omit it. The table itself omits `runtime_skill_sync.py`, `extensions_config.json` and the six bare bridge modules (`setup.sh:597`)]
    - `README.md:36` lists 7 provider stanzas and `setup.sh:707` prints "7 provider stanzas"; `config.yaml` has 8 (`antigravity` is omitted).
    - `config.yaml:1301` says summarization `model_name: null` = "use default model", but the lead overlay makes null inherit the **run's** model.
    - `config.yaml:193-212`: the `glm` stanza's display name/comments say GLM-4.6 and an "International endpoint shown", but `model: glm-5.3` and `base_url` is the CN BigModel coding endpoint.
    - `config.yaml:4` "Copy this file to `config.yaml`" is upstream boilerplate.
    - `config.yaml:18` `config_version: 11` lags the vendor seed's `config.example.yaml` (`config_version: 14`, `deer-flow-2.0.0/config.example.yaml:18`). The DeerFlow version warning never fires only because setup trims `config.example.yaml` from `deer-flow/` (`setup.sh:561`; check in `deer-flow/.../config/app_config.py:284-308`).
    - `setup.sh:494-499` claims claude_provider/credential_loader/loop_detection are "byte-identical between this pin and the vendored RC outside the patched regions"; this can't be checked against the current seed, and the runtime differs from the seed elsewhere.
18. **`title_middleware` patch is effectively dead for research**, since `title.enabled: false` (`config.yaml:1287`) and the sync path never calls an LLM (`title_middleware.py:146-152`).
19. **`claude` stanza thinking budget logic is unused**: `supports_thinking: false` (`config.yaml:60`), so `_apply_thinking_budget` (`claude_provider.py:385-396`) never fires for the configured Claude model.

---

## Verification

An adversarial verifier re-read every cited anchor on `main` (2026-10-11), working read-only. It recomputed the skill manifests in memory with the module's own pure functions, ran `diff`/`cmp` against `deer-flow/` and `deer-flow-2.0.0/`, and wrote nothing outside this file.

**Verdict counts.** There were 14 key claims: 13 confirmed and 1 imprecise. There were 17 surprises: 16 confirmed and 1 imprecise. Separate spot checks of the Walkthrough, Control-flow and table sections covered more than 25 statements. Five were wrong or imprecise: 1 refuted and 4 imprecise. Each of those five has an inline `[verifier: …]` note.

**Re-observed evidence**
- Source bundle hash `05e06e028acf…` vs persisted/live `f14068b3574a…`. The only difference is 4 extra source files under `forecast-visuals/scripts/{.claude,logs}`, and the live tree still matches its state file.
- `deer-flow/skills/public` is `drwx------`.
- Every overlay anchor occurs exactly once in `deer-flow-2.0.0`, and every new block or marker is present in `deer-flow/`.
- All five middleware patches and all three model patches are byte-identical to the deployed copies. `patched_minimax.py` is also byte-identical to the seed.
- `deerflow_bridge/config.yaml` is byte-identical to `deer-flow/config.yaml`.

**Non-confirmed items and corrections**
1. *Key claim 8 (imprecise):* "ModelConcurrencyMiddleware last among model wrappers" holds only within `_build_runtime_middlewares` (`tool_error_handling_middleware.py:147-195`). In the lead chain, `build_middlewares` appends SkillActivation, TodoList, DeferredToolFilter and LoopDetection after it (`agent.py:311-392`). LangChain makes the first-listed wrapper outermost (`langchain/agents/factory.py:219-231`), so those hooks run inside the lease. The lease-gating half of the claim is confirmed (`model_concurrency_middleware.py:19-54`, `research_budget.py:78-106,916,1105`, `pipeline_orchestrator.py:2408-2410`).
2. *Surprise 2, MCP not opt-in (imprecise):* the mechanism is real, and stronger than stated. `extensions_config.py:128-135` also falls back to the module-relative `deer-flow/extensions_config.json`, whatever the cwd. It is narrower in scope, though: only legacy-engine children build `DeerFlowClient` and so reach `get_available_tools` (`deerflow_research.py:16902-16929`). The default v3 engine only calls `create_chat_model` (`linear_research.py:6257-6262`).
3. *Control flow, "Runtime call order" (refuted):* LoopDetection's `wrap_model_call` sits inside ModelConcurrency, not outside it. See the inline note.
4. *Failure modes / External calls, "429/5xx retried 3×" (imprecise):* 529 `OverloadedError` is a separate class in anthropic 0.97.0 (`anthropic/_client.py:285-289`, `_exceptions.py:131-140`) and the bridge loop does not retry it. Streaming calls bypass the loop as well.
5. *Data table, `research_meta.json` (imprecise):* the child writes `meta.json` (`deerflow_research.py:875`).
6. *Surprise 17 README bullet (imprecise):* the README file table does list `apply_subagent_overlays.py` (`README.md:34`); only the manual steps omit it.
7. *Setup step 1 anchor (imprecise):* the clone branch is `setup.sh:530-550`, not `:525-544`.

**Clarifications on confirmed items (not errors)**
- Key claim 4: the "verified" fast path still opens/creates the lock file (`runtime_skill_sync.py:252`). On a first deploy (no live dir) the update path uses `os.replace`, not an exchange (`:489-493`).
- Key claim 7: identical-set counts are taken within the sliding 20-entry window (`loop_detection_middleware.py:358-368`).
- Key claim 2: lead/subagent targets are pre-checked for existence (`pipeline_orchestrator.py:1606,1685`), so a `"missing"` status never reaches the fail-closed branch. Missing targets are skipped silently instead.
- Surprise 5: the streaming bypass is confirmed at the code level. `DeerFlowClient` streams with `stream_mode=["values","messages","custom"]` (`deer-flow/backend/packages/harness/deerflow/client.py:712`), and `StreamMessagesHandler` is a `_StreamingCallbackHandler` (`langgraph/pregel/_messages.py:42`). `_generate_with_cache` then routes to the v2/v1 stream branches (`langchain_core/language_models/chat_models.py:1817-1848`). This applies only to the legacy `DeerFlowClient` path.
- Dead/dormant surprise: the thinking budget never fires because the `claude` stanza has no `when_thinking_enabled`/`thinking` settings (`factory.py:130-137`; `config.yaml:45-67`), as well as `supports_thinking: false`.

**Omissions (significant behavior the map does not state)**
1. **Patch scope depends on the research engine.** The default v3 engine (`pipeline_orchestrator.py:2295-2300`, `deerflow_research.py:16902-16903`) never constructs `DeerFlowClient`. It calls `create_chat_model` directly (`linear_research.py:6257-6267`) under its own bridge lease (`linear_research.py:6182-6195`). So the middleware patches, the lead/subagent overlays, loop detection, summarization and MCP loading take effect only for legacy-engine children (evidence lanes, global synthesis, explicit legacy). The provider patches (`claude_provider`, `credential_loader`) and the factory overlay affect both engines.
2. **Any non-retyped drift-guard exception skips both required overlays, not just a factory drift.** A failed `shutil.copyfile` for any pair other than `runtime_skill_sync.py` re-raises (`pipeline_orchestrator.py:1583-1590`), and so does a `_digest` read error (`:1512-1514`). Both reach the generic `except` (`:1739-1745`) before the lead overlay (`:1599`) and the subagent overlay (`:1668`). The guard only warns, and research launches.
3. **Suspected race: the drift guard's write half is not serialized.** Only `sync_runtime_skills` holds the flock (`runtime_skill_sync.py:421-422`). The overlays write through a fixed `<target>.tmp` name (`apply_lead_agent_overlays.py:120-128`, `apply_subagent_overlays.py:281-290`, `apply_model_factory_overlays.py:46-54`), and the module copies use non-atomic `shutil.copyfile` (`pipeline_orchestrator.py:1584`). The orchestrator itself documents that concurrent first syncs from pipeline threads race, and it fixed this for `extensions_config.json` with `mkstemp` (`:1413-1431`). For the overlays, a losing thread's `os.replace` can raise `FileNotFoundError`. For the lead/subagent overlays that becomes `_DeerFlowSafetyOverlayError` and the launch is refused. For the factory overlay it becomes a warning and the subagent overlay is skipped. Not observed at runtime.
4. **A corrupt or foreign skill state file blocks every launch, with no self-heal.** `_load_state` raises `SkillSyncError` on unreadable JSON, a wrong schema or a wrong owner (`runtime_skill_sync.py:215-235`). It is called before any repair path (`:432`), and the orchestrator retypes the error to `_DeerFlowSkillSyncError` (`pipeline_orchestrator.py:1494-1497`). So research stays refused until `deer-flow/skills/public/.drf-runtime-skill-manifest.json` is removed by hand.
5. **529 overload is not covered by the bridge retry.** See correction 4 (`claude_provider.py:442-455`; `anthropic/_client.py:285-286`).
