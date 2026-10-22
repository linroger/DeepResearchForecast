# llm-topology — LLM / provider topology and cost accounting (branch `main`)

Cross-cutting trace. It answers four questions for every stage: who calls a model, which setting picks the model, what bounds the call (retries, failover, breakers, concurrency, budgets), and where its usage and cost end up.

## 0. Anchor convention and a working-tree caveat

**The working tree changed while this trace was being written.** Another session was adding an "official data sources" layer (`datamcps/`, `deerflow_bridge/data_mcp.py`, `DATA_SOURCES_*`). It was editing `backend/app/services/pipeline_orchestrator.py` (13,492 lines at HEAD; 13,559 lines on disk when last checked) and `backend/app/config.py` (+31 lines after line 1467). None of the edits seen touch LLM code: they are bridge-module deploy lists and research-child env for data sources (`git diff` hunks at orchestrator 1356-1427 and 2429-2432). To keep anchors stable:

- `po:N` means `backend/app/services/pipeline_orchestrator.py` **as committed at HEAD `c20ec60`** (`git show HEAD:…`).
- `cfg:N` means `backend/app/config.py` **at HEAD `c20ec60`**. Lines before 1468 are the same on disk. Later lines are +31 on disk.
- Every other file was unmodified (`git diff --stat` does not list it), so disk and HEAD agree. Abbreviations:

| Abbrev | Path |
|---|---|
| `lc` | `backend/app/utils/llm_client.py` |
| `tel` | `backend/app/utils/telemetry.py` |
| `ollm` | `backend/app/utils/oasis_llm.py` |
| `ga` | `backend/app/services/graphiti_client/llm_adapter.py` |
| `grt` | `backend/app/services/graphiti_client/runtime.py` |
| `ra` | `backend/app/services/report_agent.py` |
| `fx` | `backend/app/services/forecast_extractor.py` |
| `zt` | `backend/app/services/zep_tools.py` |
| `rps` | `backend/scripts/run_parallel_simulation.py` |
| `rg` | `deerflow_bridge/research_gateway.py` |
| `lr` | `deerflow_bridge/linear_research.py` |
| `dr` | `deerflow_bridge/deerflow_research.py` |
| `rb` | `deerflow_bridge/research_budget.py` |
| `cy` | `deerflow_bridge/config.yaml` (byte-identical to the deployed `deer-flow/config.yaml`; checked with `cmp`) |

The deployed copies `deer-flow/{research_gateway,linear_research,deerflow_research,research_budget}.py` and `deer-flow/backend/packages/harness/deerflow/models/claude_provider.py` are byte-identical to their `deerflow_bridge/` sources (checked with `cmp`).

---

## 1. The three model planes

DRF has **three separate model-selection planes**. Only the first is affected by `LLM_PROVIDER`.

| Plane | Where it runs | What selects the model | Clients |
|---|---|---|---|
| **A. Backend `LLMClient` plane** | Flask/orchestrator process (ONTOLOGY, GRAPH, PREPARE, REPORT, API routes) and the OASIS sim child (decision channel, CLI bridge, fallback) | `LLM_PROVIDER` (default `claude-cli`, `cfg:750`), plus `LLM_MODEL_NAME`/`LLM_BASE_URL`/`LLM_API_KEY` (per-provider defaults, `cfg:782-799`). Tier routing (`LLM_TIERED_ROUTING` default True, `cfg:92`) swaps the model name for `Config.strong_model()`/`fast_model()` (`cfg:145-152`, `lc:356-374`). Optional fast-tier client (`LLM_FAST_PROVIDER`/`_BASE_URL`/`_API_KEY`, `cfg:101-103`, `lc:376-394`). Single-hop failover through `LLM_FALLBACK_PROVIDER`/`_MODEL`/`_BASE_URL`/`_API_KEY`, read live from `os.environ` (`lc:532-568`) | `LLMClient` (`lc:247`); `AppGraphitiLLMClient` wraps it (`ga:100-112`); OASIS CAMEL models (`ollm:557-601`) |
| **B. DeerFlow research plane** | Research child `deer-flow/deerflow_research.py` (v3 engine or legacy) | Per-run `model` from `POST /api/research/run` (validated against `SUPPORTED_DEERFLOW_MODELS`, `backend/app/api/research.py:91-98`; stored as `options.research_model`, `po:7960`), else `DEERFLOW_MODEL` (default `claude`, `cfg:1156`). Passed as `--model` (`po:2255`) and resolved as a stanza name in `deer-flow/config.yaml` (`cy:45-260`). Extra routing: `DEERFLOW_FALLBACK_MODEL` (both engines, `lr:6264-6271`, `dr:6451-6453`); legacy only: `DEERFLOW_JUDGE_MODEL` (`dr:11631`, `dr:14085`), `DEERFLOW_SYNTHESIS_MODEL` (`dr:8041`, `dr:12172`), `DEERFLOW_EXTRACTION_MODEL` (`dr:8213`, `dr:8334`) | v3: `research_gateway.ModelGateway` over `deerflow.models.create_chat_model` (`lr:6255-6273`). Legacy: `DeerFlowClient` agent turns (`dr:16914-16928`) plus bare `create_chat_model` calls (`dr:6469-6477`, `dr:14086`, `dr:14279`) |
| **C. Embeddings** | Backend process (Graphiti) | `GRAPHITI_EMBED_MODEL` (default `paraphrase-multilingual-MiniLM-L12-v2`, `cfg:1026`) | Local sentence-transformers (`backend/app/services/graphiti_client/embedder.py:241`). No hosted embedding API and no metering |

**Coupling between A and B.** `Config.apply_provider` (settings API) rewrites `LLM_PROVIDER` and **also** sets `DEERFLOW_MODEL = PROVIDER_META[provider]['deerflow_model']` (`cfg:913-971`, mapping at `cfg:858-877`). It mirrors the key into the provider-specific env var that `deer-flow/config.yaml` reads through `$VAR` (`cfg:966-971`). `openai` maps to the `claude` research stanza (`cfg:861-862`). The per-run `model` field in `POST /run` changes **only** plane B. Every non-research stage keeps using the global `LLM_PROVIDER`.

**Default deployment.** Both planes bill a subscription: `LLM_PROVIDER=claude-cli` (`cfg:750`) and `DEERFLOW_MODEL=claude`, which is the `ClaudeChatModel` stanza `claude-opus-4-8` on Code-plan OAuth (`cy:45-67`). With `claude-cli`, `LLM_MODEL_NAME` defaults to `gpt-4o-mini` (`cfg:791-798`). The CLI therefore does not pin `--model`, because pinning only happens for claude/opus/sonnet/haiku names (`lc:1022-1026`), and the meter labels these calls `claude-cli:gpt-4o-mini`.

---

## 2. Master table: stage → call site → client → model setting → budget/limit → telemetry sink

"Meter" means the backend process's `LLMMeter` (`tel:224-399`), keyed by run id and stage through contextvars (`tel:42-77`). Persistence of the meter is described in §7.

| Stage | Call site | Client | Model setting | Budget / limits | Telemetry sink |
|---|---|---|---|---|---|
| RESEARCH (v3, default engine) | `linear_research` phases call `self.gateway.invoke/json/prime/fan_out` (`lr:3990`; priming at `lr:4492,4824,5325,5633`) | `rg.ModelGateway` (`rg:1399-1999`) over `create_chat_model(args.model, thinking_enabled=False)`, plus an optional fallback model (`lr:6255-6273`) | `--model` = `options.research_model` or `DEERFLOW_MODEL` (`po:2255`); fallback `DEERFLOW_FALLBACK_MODEL` (`lr:6264`) | Semaphore = `preset.workers` (4; capped by `RESEARCH_MODEL_CONCURRENCY_GLOBAL`, `lr:615-631,748-753`; `rg:1441`). Cross-process SQLite lease (`lr:6178-6240`; `rb:902-…`). Weighted `budget_units` 1.2M/2.5M/5M with a 35% reserve (`lr:615-631`, `lr:101`). Time budget 1200/2700/5400 s, capped at 0.85 × `DEERFLOW_RESEARCH_TIMEOUT` (`lr:754-760`). Per-call output caps agent 6000 / json 16000 / write 20000 (`rg:573`) | One `[usage] tokens in= out= total= phase= cached= cache_write= reasoning=` stdout line per response (`rg:1839-1866`). `v3/usage.json` plus `meta.usage` (`lr:5882-5890`). Orchestrator parses stdout (`po:2511-2525`), then writes one synthetic meter row with stage `research` (`po:10430-10471`) |
| RESEARCH (v3 → bridge helpers) | `bridge_call("_collect_prediction_markets", …, model_name=self.model_name)` (`lr:5548-5549`): LLM query derivation (`dr:14754-14765`) and LLM relevance gate (`dr:14858-14859`) | `dr._bare_synth_invoke` → `_invoke_tool_free_model` (`dr:6602-6631`, `dr:6490-6600`). **Not** the gateway | Same `--model`; fallback `DEERFLOW_FALLBACK_MODEL` | Outside the gateway's semaphore, budget units and `usage.json`. Uses only the bridge model lease (`dr:4555-4558`). Gated by `PREDICTION_MARKETS_ENABLED` (`cfg:1423`, `dr:15484`) | `[usage]` lines from `_log_model_response_usage` (`dr:6335-6348`), so they reach the orchestrator total but not `v3/usage.json` |
| RESEARCH (legacy engine) | Agent turns `run_streamed_turn` (`dr:10190`) through `DeerFlowClient(model_name=args.model, thinking_enabled=True, subagent_enabled=…)` (`dr:16914-16928`) | DeerFlow harness (LangGraph lead agent, subagents `model: inherit`, `cy:1224`). Summarization model = configured name or the run's model (DRF overlay `deerflow_bridge/patches/apply_lead_agent_overlays.py:68-70`) | `--model` stanza in `cy` | Each harness model node leases one permit (`deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:25-32`). Subagent cap `max_concurrent: 5` (`cy:1174`), overridden by `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` from the orchestrator (`po:2366-2368`). Summarization triggers at 80K tokens and keeps 16K (`cy:1298-1329`) | One `[usage]` line per streamed turn from the `end` event's cumulative usage (`dr:10300-10302`, format `dr:10170-10187`) |
| RESEARCH (legacy tool-free) | Synthesis, outline/sections, extraction, judge, actor synthesis (`dr:8112`, `dr:8223`, `dr:8342`, `dr:11661`, `dr:14105`, `dr:14292`) | Bare `create_chat_model(name, thinking_enabled=False)` with `.bind(max_tokens=…)` (`dr:6469-6477`) | `--model`, or `DEERFLOW_SYNTHESIS/EXTRACTION/JUDGE_MODEL` overrides; fallback `DEERFLOW_FALLBACK_MODEL` with a 900 s circuit (`dr:6461-6466`) | Provider SDK `max_retries` from the stanza (for example `cy:111,144,181,214`). Multipart output envelope `SynthesisExecutionBudget` (`dr:6425-6447`). Bridge lease (`dr:4549-4558`) | `[usage]` per response (`dr:6335-6348`; `dr:14110`) |
| RESEARCH (backend side, legacy multi-lane only) | `reconcile_track_reports` → `LLMClient().chat(…, temperature=0.2, max_tokens=4000)` (`po:6240-6244`), called at `po:11747` only when ≥ 2 lanes survived and `RESEARCH_TRACK_RECONCILE` (`po:11744-11748`) | `LLMClient` (plane A) | `LLM_PROVIDER`/`LLM_MODEL_NAME` | `LLMClient` stack (§3.1) | Meter, stage `research` (set by the stage updater, `po:8953-8954`). Dormant under v3, which runs 1 outer lane |
| ONTOLOGY | `OntologyGenerator.generate` → `chat_json(temperature=0.3, max_tokens=8192)`, plus one fallback template call (`backend/app/services/ontology_generator.py:480,601-604,626-632`) | `LLMClient()` | Plane A, tier `strong` | `LLMClient` stack | Meter, stage `ontology` |
| GRAPH | Graphiti extraction: `AppGraphitiLLMClient._generate_response` → `chat_json(tier="fast" for small/medium, else "strong")` on a dedicated pool (`ga:114-176`) | `AppLLMClient()` singleton per runtime (`grt:358-364`; `ga:111`); ingest fallback client from `LLM_FALLBACK_*` (`grt:594-626`) | Plane A. The fast tier only differs when `LLM_FAST_MODEL` is set (`cfg:96`) | `GRAPH_BUILD_CONCURRENCY` 4 (`cfg:1240`) × `GRAPHITI_MAX_COROUTINES` 16 (`cfg:1244`, `grt:396-405`); I/O pool `GRAPH_LLM_EXECUTOR_WORKERS` 64 (`cfg:1247`, `ga:59-78`). Retries: temperature ladder (0.0, 0.4) (`ga:162-163`); episode re-roll `GRAPH_EPISODE_SCHEMA_RETRIES` 1 (`cfg:1324`); per-chunk attempt cap `GRAPH_CHUNK_MAX_ATTEMPTS` 2 (`cfg:1342`, `grt:143-160`) | Meter, stage `graph`. The context is copied into executor calls (`ga:165-175`), and `asyncio.run_coroutine_threadsafe` captures the caller's context (CPython `Handle.__init__` copies the calling thread's context; probed) |
| GRAPH (optional) | `build_communities` → `graphiti.build_communities` (LLM summaries) (`grt:1209-1225`) | Same Graphiti LLM client | Plane A | Off by default: `GRAPH_BUILD_COMMUNITIES=false` (`cfg:1266`, `po:12579`) | Meter, stage `graph` |
| PREPARE (personas) | `OasisProfileGenerator._generate_profile_with_llm` → `chat(response_format=json_object, temperature 0.7 − 0.1·attempt)`, 3 parse attempts (`backend/app/services/oasis_profile_generator.py:1768-1785`) | `LLMClient(provider, api_key, base_url, model)` (`backend/app/services/oasis_profile_generator.py:370-375`) | Plane A | Thread pool of `parallel_count` (`backend/app/services/oasis_profile_generator.py:2404`) = `PARALLEL_PROFILE_COUNT` 16 for HTTP providers, 3 for CLI (`cfg:474`, `po:12804-12816`) | Meter **without** run/stage context: the pool does not copy contextvars, so rows land in stage `_unstaged` of the sole active run (or `_global`) (`tel:231-246`) |
| PREPARE (sim config) | `SimulationConfigGenerator._call_llm_with_retry` → `chat(json_object, temperature 0.7 − 0.1·attempt)`, 3 attempts (`backend/app/services/simulation_config_generator.py:2079-2097`); callers `:1014,:2226,:2477,:2964` | `LLMClient(...)` (`backend/app/services/simulation_config_generator.py:448-453`) | Plane A | Sequential (no pool found). Canonical actor-intelligence/v1 casts skip the LLM agent configs (sim-config map) | Meter, stage `prepare` |
| RUN (OASIS agents, HTTP providers) | CAMEL `OpenAIModel._arequest_chat_completion` per agent action | `ModelFactory.create(OPENAI, model_type=LLM_MODEL_NAME, …)` (`ollm:490-532`), plus the kimi UA patch (`ollm:535-554`), reasoning-off `extra_body` (`ollm:591-597`) and the 422/429 → `LLMClient` fallback guard (`ollm:348-376`) | `LLM_*` env read directly (`ollm:507-515`). Reddit uses `use_boost=True` (`rps:5268`), which only matters when `LLM_BOOST_API_KEY` is set (`ollm:495-505`) | Per-platform semaphore = `OASIS_SEMAPHORE // 2`, env default **30** (`ollm:603-616`, `rps:4815,5368`) | Child accumulator → `sim_llm_telemetry.json` (`rps:2047-2225`) and `llm_health.json` (`rps:2270-2308`) → one meter row with stage `run` (`po:10473-10555`) |
| RUN (OASIS agents, CLI providers) | `CLIModel._request_chat_completion` → `LLMClient.chat` with JSON tool emulation (`ollm:379-480`) | `LLMClient(provider)` inside the sim child | Plane A (`claude`/`codex` subscription) | `OASIS_CLI_SEMAPHORE // 2`, default 8 (`ollm:28,613`); `LLM_CLI_TIMEOUT` 180 s (`lc:29`) | Same child accumulator; source `estimate` (synthetic `chatcmpl-cli-` ids, `ollm:162-212`, `rps:2099-2121`) |
| RUN (decision channel / in-band world evolution) | `decision_channel.elicit_round` → `llm.chat_json(temperature=0.2, max_tokens=2048)` (`backend/app/services/decision_channel.py:247-253`); in-band (`rps:3444-3446`), post-hoc (`rps:5989-6005`) | `_wrap_llm_client_usage(LLMClient())` | Plane A | Thread pool `concurrency` = `Config.OASIS_SEMAPHORE` (24) (`backend/app/services/decision_channel.py:578-580,529`) | Child accumulator, **double-counted** (§8 F1) |
| REPORT | `ReportAgent` (outline `ra:9958`, section native tools `ra:10576,10650`, ReACT `ra:10775,11030`, critique/revise/continue `ra:10304-10379`, language `ra:10458`, Part-2 synthesis `ra:8823`, sim-leak rewrite `ra:4736`, translation `ra:6697,5191,5262`, prose slots `ra:5971,6014`, market classifier `ra:2637`) | `self.llm = llm_client or LLMClient()` (`ra:1671`) | Plane A. Some calls pass `tier="fast"` (for example `ra:4739`, `ra:10309`) | Sections: `REPORT_SECTION_CONCURRENCY` 6 (`cfg:1535`, `ra:11298-11303`); translation pool `REPORT_TRANSLATION_CONCURRENCY` 4 (`cfg:706`, `ra:7069-7075,7269-7281`); translation per-call timeout 240 s (`cfg:713`, `ra:7431-7433`). Pre-report ping (`po:13250-13261`) | Meter, stage `report` (`ra:11163-11176`); report folder `telemetry.json` (`ra:11603-11640`). Pools copy contextvars (`ra:7074,7280,10098`) |
| REPORT (forecast library) | `fx` calls with the agent's client: `extract_structured_forecast` (`fx:1022`), `anchor_binaries_to_markets` (`fx:1802`), `enforce_market_divergence` (`fx:1909`), `extract_binary_forecasts` (`fx:2768`), `_spine_draw` (`fx:3031`), `self_critique_forecast` (`fx:3592`), `premortem_forecast` (`fx:3726`) | `ReportAgent.llm`; ensemble draws use `_build_ensemble_client(provider)` (`fx:2593-2617`) | Plane A; ensemble draws use `FORECAST_ENSEMBLE_MODELS` (default empty = off, `cfg:643`, `fx:2809`) | `LLMClient` stack | Meter, stage `report` |
| REPORT (retrieval tools) | `zt._generate_sub_queries` (`zt:1778-1784`, fast), `_select_agents_for_interview` (`zt:2317-2323`, fast), `_generate_interview_questions` (`zt:2379-2385`, fast), `_generate_interview_summary` (`zt:2437`) | Lazy `LLMClient()` (`zt:573-578`) | Plane A | `LLMClient` stack | Meter, stage `report` |
| REPORT (agent interviews) | `zep_tools.interview_agents` → `SimulationRunner` file IPC → the sim child's agents answer through their OASIS model | Sim-child CAMEL model | Plane A | Child semaphore | Counted in the child accumulator but **never reaches the meter** (§8 F2) |
| ENSEMBLE (optional) | `_maybe_run_seed_ensemble` → `_run_one_seed` (prepare + sim + `ReportAgent`) (`po:8529-8560`, `po:8762-8890`) | Plane A clients | Plane A | `N_FORECAST_SEEDS` default 1 = off (`cfg:303`) | Backend calls under stage `ensemble` (`po:8617`). Seed sim-child spend is **never recorded** (§8 F3) |
| API (dossier translation) | `POST/GET` research translate → `ReportAgent.__new__` + `LLMClient()` → `translate_research_markdown` (`backend/app/api/research.py:498-513`) | `LLMClient()` | Plane A | Translation bypasses the cache with a 240 s timeout (`ra:7741-7745`) | Meter in a Flask thread with no run context, so `_unstaged` of the sole active run or `_global` (`tel:231-246`) |
| API (report chat) | `agent.chat(...)` (`backend/app/api/report.py:1562`; `ra:11727-11829`) | `ReportAgent.llm` | Plane A | `LLMClient` stack | Same attribution as above |
| API (settings test) | `_test_openai_compat_provider` → raw `OpenAI(...).chat.completions.create(max_tokens=16)` (`backend/app/api/settings.py:77-128`); the CLI test only runs `--version` (`backend/app/api/settings.py:57-74`) | Raw OpenAI SDK | Request body | none | **Unmetered** |
| Ops scripts | `backend/scripts/preflight.py:254` (raw OpenAI probe, also `scripts/doctor.sh:349`); `backend/scripts/model_comparison.py:136`; `backend/scripts/eval_forecast_quality.py:314,330` | Raw SDK / `LLMClient` | Plane A or per-instance provider | — | Preflight is unmetered; the others use the script process's own meter |
| MCP servers (research child) | `kg_server` tools `kg_search` … `kg_graph_statistics` (`backend/app/mcp/kg_server.py:223-251`) | none (graph search uses local embeddings) | — | — | No LLM calls. `insight_forge` (which does call an LLM, `zt:1482-1542`) is not exposed |

`drf2/` has its own model routing but is not wired into the live app: `grep` finds no `import drf2`/`from drf2` in `backend/app`, `deerflow_bridge` or `frontend/src`.

---

## 3. Clients in detail

### 3.1 `LLMClient` (plane A transport), `lc`

- **Dispatch.** OpenAI-compatible providers are those in `Config.PROVIDER_META` with `openai_compat`, plus the fallback-only `antigravity` (`lc:34-41`). CLI providers are `claude-cli`/`codex-cli` (`lc:31`). An unknown provider raises at construction (`lc:267-271`). An HTTP provider without a key raises (`lc:289-290`).
- **HTTP client.** SDK timeout 600 s. `LLM_HTTP_TIMEOUT_S` is read with `getattr` but is not defined in `Config` (`lc:298-303`). With `LLM_HTTP2` (default True, `cfg:79`), an httpx client is built with keepalive `LLM_HTTP_KEEPALIVE` (128) and `max_connections = keepalive + 32`, and **SDK retries are set to 0** (`lc:310-313,330-350`). If `LLM_HTTP2=false`, the SDK default retries stay on, nested inside `chat()`'s own 3 attempts.
- **`chat()` order** (`lc:399-522`):
  1. Tier model (`lc:419`).
  2. Response-cache lookup. On a hit it meters `cached=True` with 0 tokens and returns (`lc:425-432`).
  3. Breaker pre-check, which goes straight to the fallback or raises (`lc:444-458`).
  4. 3 attempts with 2 s / 4 s backoff, honouring `Retry-After` capped at 30 s (`lc:44-46,233-244,459-493`). A deterministic 401 stops retrying (`lc:474-479`). Quota-like errors count toward the 429 breaker on every attempt (`lc:480-481`). A non-retryable 422 counts toward the 422 breaker (`lc:488-493`).
  5. `_try_fallback` (`lc:494-505`).
  6. Meter, only when not served by the fallback, using exact usage from `_last_usage` or a `len//4` estimate (`lc:507-517`).
  7. Cache put (`lc:518-519`).
  8. **Post-call** budget check (`lc:520-521`).
- **Breakers.** They are process-global and keyed only by provider name. 422: 5 consecutive → 300 s (`lc:116-123,158-165`). 429/quota: 8 consecutive → 120 s (`lc:135-142,168-176`). Only a primary success resets the counters (`lc:179-184`, called at `lc:470`).
- **Failover** (`lc:524-595`). A single hop with no recursion (`_is_fallback`, `lc:530-531,569`). An OpenAI-compatible fallback without `LLM_FALLBACK_MODEL` is refused (`lc:542-552`). Fallback clients come from a pool (`lc:572-578`). A deterministic 401/400 puts the fallback in a 900 s cooldown (`lc:230,586-593`). The fallback keeps its own model, never the tier alias (`lc:367-369`).
- **`chat_json`.** Two parse attempts at temperature −0.2 per retry, each through `self.chat` (`lc:597-627`).
- **`chat_with_tools`** (`lc:658-759`). Same 3-attempt loop and breaker accounting. It has **no fallback, no response cache and no per-call timeout override**. It meters exact usage and checks the budget (`lc:735-746`). `supports_native_tools()` is false for MiniMax (`native_tools: False`, `cfg:868-870`), for a tripped breaker, or when `REPORT_NATIVE_TOOLS` is off (`lc:632-656`, `cfg:1528`).
- **CLI providers.**
  - Claude: `claude -p --output-format json [--settings {"disableAllHooks":true}] [--model …]`, prompt on stdin, `cwd=/tmp`, `ANTHROPIC_API_KEY` stripped unless `LLM_CLI_USE_API_KEY=true` (`lc:976-1078`, `cfg:506`).
  - Codex: `codex exec --skip-git-repo-check` with no model pin (`lc:1083-1135`).
  - Temperature and max_tokens are ignored on both.
  - No exact usage is available, so the meter estimates `len//4` (`lc:509-516`).
- **Reasoning.** `extra_body` disables thinking for kimi/minimax/deepseek/glm/qwen by default (`cfg:810-847`, `lc:885-907`). Kimi's temperature is coerced to 0.6 or 1.0 (`lc:870-883`). The kimi User-Agent header comes from `LLM_USER_AGENT` (`cfg:803`).
- **Prompt caching.** There is no `cache_control` anywhere in `backend/app` or `backend/scripts` (grep finds only a comment at `po:2724`). The only cache is the in-process **response** cache `LLMCache`: on by default (`cfg:62`), FIFO with 2048 entries, keyed by provider, model, messages, temperature, max_tokens and response_format (`tel:536-594`). It is bypassed only for translation (`ra:7431,7741`).

### 3.2 Orchestrator run-level outage breaker (wraps plane A)

- `_run` sets the run context and, when `LLM_OUTAGE_HALT_CONSECUTIVE` > 0 (default 10, `cfg:69`, `po:379-396`), registers a breaker and monkeypatches **`LLMClient.chat` only** (`po:11887-11892`, `po:597-645`). Fallback clients pass through (`po:620-621`).
- Provider-level failures are classified as quota/auth/connection/circuit_breaker. `BudgetExceeded`, cancellation and 422s are excluded (`po:399-443`).
- Once tripped, every later `chat()` fails fast (`po:625-626`). The stage updater raises `ProviderOutageHalt` (`po:8965-8969`).
- Ownership resolves the same way telemetry does: contextvar, else the sole active run, else the sole registered breaker (`po:554-577`). Flask-thread calls (translation, chat) during a single in-flight run therefore feed that run's breaker.
- **Not covered:** `chat_with_tools` (not patched), the research and sim children (separate processes; research lane failures are counted only at the boundary through `_note_provider_stage_failure`, `po:580-594`).
- REPORT also sends a uuid-salted ping through `LLMClient().chat` before spending on sections (`po:13250-13261`, gated by `REPORT_LLM_PREFLIGHT`, `cfg:503`).

### 3.3 Graphiti adapter and runtime (plane A in GRAPH)

- The adapter maps graphiti `ModelSize.small/medium` → tier `fast`, everything else → `strong` (`ga:138-147`). It adds a schema-echo guard to the last message (`ga:124-136`) and runs `chat_json` on the 64-thread pool inside `contextvars.copy_context().run` (`ga:162-175`). Graphiti's own tenacity retry runs on top (comment at `ga:158-161`).
- The runtime caches **one** `AppGraphitiLLMClient()` per process on first use (`grt:358-364`). It is built from `Config` at that moment, so a later `apply_provider` does not change graph extraction until the backend restarts (inferred from the cache at `grt:359`; `lc:257-265` resolves provider and model at construction).
- **Ingest fallback.** A lazily built `LLMClient(provider=LLM_FALLBACK_PROVIDER, …)` with `_is_fallback=True`, swapped into the graph's client with ref-counting (`grt:594-660`). It is off when the fallback provider is unset or equals `LLM_PROVIDER` (`grt:605-608`). Rate-limit cooldown before the serial replay is 15 s, capped at 60 s (`grt:36-37,164-181`).
- **Embeddings** are local: `SentenceTransformer` (`embedder.py:241`) on a 4-worker pool (`cfg:1250`) with an LRU plus a sqlite disk cache (`embedder.py:121-195`). Reranker `rrf` (no-op) by default; `bge` is a local cross-encoder (`grt:366-374`, `cfg:1029`). Neither has hosted cost.

### 3.4 OASIS model factory (`ollm`, RUN child)

- **Provider resolution:** `os.environ['LLM_PROVIDER']`, then `config['llm_provider']`, then `Config.LLM_PROVIDER` (`ollm:481-487`).
- **CLI providers** go to `CLIModel`, which proxies to `LLMClient` and emulates function calling as JSON in the prompt (`ollm:379-480,566-584`).
- **HTTP providers** go to CAMEL `ModelFactory` (`ollm:490-532`) with three additions:
  - an empty-assistant sanitizer (`ollm:213-255`);
  - a reasoning-off `extra_body` (`ollm:591-597`);
  - a guard that sends 422, 429, quota or usage-limit errors to a fresh `LLMClient(provider)`, with its retries, breakers and `LLM_FALLBACK_PROVIDER` (`ollm:301-376`). The guard is controlled by `SIM_LLM_FALLBACK` (default true, `cfg:603`). Fallback events go to `llm_fallback.jsonl` in the sim dir (`ollm:272-295`).
- **Semaphore.** `get_oasis_semaphore` reads `os.environ` with **its own defaults, 8 (CLI) and 30 (HTTP)**, then divides by the number of platforms (`ollm:28-29,603-616`). `Config.OASIS_SEMAPHORE` defaults to **24** (`cfg:1091`). Its comment says "默认值与 oasis_llm.py 的 DEFAULT_*_SEMAPHORE 逐字节一致（CLI 8、OpenAI 30）" (`cfg:1084-1086`), so the Config attribute is not the effective sim cap. The decision channel, which reads `Config`, uses 24 (`backend/app/services/decision_channel.py:579-580`). The interview timeout scaler uses env with default 30 (`backend/app/services/simulation_runner.py:2729-2733`).

### 3.5 Research engine v3: `ModelGateway` (`rg`)

- **Construction.** Primary plus an optional fallback through `create_chat_model(…, thinking_enabled=False, app_config=…)` (`lr:6255-6273`). SDK retries are disabled per model (`rg:1197-1240`, applied at `rg:1329`). The provider profile is detected per slot: GLM thinking/effort ladder, Claude, OpenAI-compatible, other (`rg:711-784`).
- **Per attempt** (`rg:1614-1638`, `rg:1670-1784`), in order: semaphore, cross-process lease, deadline check, budget pre-check (`spent + estimate·w_uncached > budget`, `rg:1587-1595`), then the bound call with a timeout of `max(30, min(kind timeout, remaining))` plus a 15 s grace on a daemon thread (`rg:1250-1279`, `rg:1597-1601`).
- **Retries.** Transient errors: up to `max_attempts` (5) with backoff 8/20/45/90 s plus up to 20% jitter. Unknown errors and aborted replies: at most 2 attempts (`rg:1093-1104`, `rg:1711-1732`, `rg:1748`). GLM 400s on laddered parameters degrade sticky (`rg:1786-1810`). An empty truncated reply widens the cap once, to at most 64K (`rg:1640-1668`). An empty untruncated reply is retried once (`rg:1776-1784`).
- **Failover** (`rg:1527-1541`). `quota`/`auth` makes the fallback **sticky for the rest of the run** with the full retry budget. `transient`/`unknown` gives the fallback exactly one attempt. Other categories are not failed over.
- **Prompt caching.**
  - The message layout is `[system][shared…][task]`, and system plus shared must be byte-identical across siblings (`rg:442-458`).
  - For Claude only, an `AIMessage("OK.")` is inserted before the task so a breakpoint lands on the shared prefix (`rg:1296-1321,1336-1340`).
  - `prime()` sends a 16-token warm-up before fan-outs (`rg:1921-1965`; used at `lr:4492,4824,5325,5633`).
  - The weighted cost model prices cached input at 0.1 (Claude), about 0.246 (GLM) or 0.25 (others), relative to uncached (`rg:579-587`).
- **Usage.** `normalize_usage` reads LangChain/OpenAI/DeepSeek/Kimi/Anthropic cache shapes (`rg:844-923`). `UsageLedger` holds a total, per-phase buckets and up to 2000 call rows (`rg:967-1048`). Each response emits one `[usage]` line, flagged `estimated=1` when the provider omitted usage (`rg:1839-1866`).

### 3.6 Legacy research engine and DeerFlow patches (plane B)

- **Agent turns.** `DeerFlowClient(config_path=args.config, model_name=args.model, thinking_enabled=True, …)` (`dr:16914-16928`). The orchestrator never passes `--config` (no `"--config"` in `po`), so DeerFlow resolves `deer-flow/config.yaml`. The orchestrator only **warns** when that file drifts from `deerflow_bridge/config.yaml`; it does not copy it (`po:1718-1728`). The two files are identical today.
- **Tool-free invoker** (`dr:6490-6600`). The provider SDK retries first (`max_retries: 2` per stanza). Errors that allow failover (quota/429/content/transport markers, `dr:6398-6403`) then go to `DEERFLOW_FALLBACK_MODEL`. The circuit opens only when the fallback actually served, and lasts 900 s (`DEERFLOW_FALLBACK_COOLDOWN_SECONDS`, `dr:6461-6466`). A failed fallback clears the circuit, and a half-open probe of the primary follows (`dr:6551-6578`). `ModelProvidersUnavailable` is raised when both fail (`dr:6405-6406`).
- **No fallback here.** `judge_dossier` and actor-dossier synthesis call `_invoke_model` directly (`dr:14105`, `dr:14292`, `dr:14313`).
- **Leases.**
  - Bare bridge calls: `_invoke_model` under `research_budget.model_call_lease(1)` (`dr:4549-4558`).
  - Harness model nodes: `ModelConcurrencyMiddleware` (`deerflow_bridge/patches/middlewares/model_concurrency_middleware.py:25-44,61-75`).
  - Bridge fan-out executor bound: `RESEARCH_MODEL_CONCURRENCY_GLOBAL // weight` (`dr:4537-4546`).
- **Claude prompt caching** (`deerflow_bridge/patches/models/claude_provider.py`). `enable_prompt_caching: true` (`cy:62-67`), with the per-request env kill-switch `DEERFLOW_CLAUDE_PROMPT_CACHE` (`claude_provider.py:66-70,227-236`). At most 4 ephemeral breakpoints: one anchor on the last system block (which covers tools plus system) and incremental markers on the newest messages (`claude_provider.py:307-360`). With caching off, every marker is stripped (`claude_provider.py:258-263`). OAuth billing is injected for Code-plan tokens (`claude_provider.py:185-217,255-256`).
- **Disabled extra LLM work in the harness:** `title.enabled: false` (`cy:1286-1287`), `memory.enabled: false` (`cy:1388-1389`). Summarization stays enabled (`cy:1298-1299`).

---

## 4. Concurrency limits (all layers)

| Layer | Limit | Default | Anchor |
|---|---|---|---|
| Research, cross-process model permits | SQLite `model_leases`, capacity `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | `DEFAULT_MODEL_CONCURRENCY_GLOBAL=12` in the child (`rb:37`). The orchestrator passes `1 + RESEARCH_GLOBAL_SUBAGENT_CAP(9) = 10` for a single lane (`po:5845-5854`, `po:12020-12026`, `po:2369-2371`) | `rb:870-875`, `rb:902-1000` |
| Research lease DB | One app-wide file shared by every pipeline | `uploads/research_model_leases.sqlite3` | `cfg:1216-1219`, `po:2404-2410` |
| Research lease wait / TTL | wait 10,800 s, TTL 120 s (child). v3 caps its own wait at 300 s in 30 s steps and stops leasing after the first capacity timeout | — | `rb:38-39`, `lr:6141-6143`, `lr:6178-6240` |
| v3 gateway semaphore | `preset.workers` = min(4, `RESEARCH_MODEL_CONCURRENCY_GLOBAL`) | 4 | `lr:615-631`, `lr:748-753`, `rg:1441` |
| Legacy subagents | `max_concurrent` 5, env `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` clamped to [1, 8] | 5 | `cy:1174`, `po:2366-2368` |
| Graph episodes × intra-episode fan-out | `GRAPH_BUILD_CONCURRENCY` × `GRAPHITI_MAX_COROUTINES` | 4 × 16. `cfg:1656` pushes 16 into `os.environ` because `grt:396` reads env with fallback 16 | `cfg:1240,1244,1656` |
| Graph LLM I/O pool | `GRAPH_LLM_EXECUTOR_WORKERS` | 64 | `cfg:1247`, `ga:59-78` |
| Persona generation | `PARALLEL_PROFILE_COUNT` for HTTP, else 3 | 16 / 3 | `cfg:474`, `po:12804-12816` |
| OASIS agents | `OASIS_SEMAPHORE` / `OASIS_CLI_SEMAPHORE` from env, divided by 2 for parallel platforms | effective 30 // 2 = 15 per platform when env is unset (Config claims 24) | `ollm:603-616`, `cfg:1088-1091` |
| Decision channel | `Config.OASIS_SEMAPHORE` | 24 | `backend/app/services/decision_channel.py:578-580` |
| Report sections | `REPORT_SECTION_CONCURRENCY` | 6 | `cfg:1535`, `ra:11298-11303` |
| Report translation | `REPORT_TRANSLATION_CONCURRENCY` | 4 | `cfg:706`, `ra:7069,7269` |
| `LLMClient` HTTP pool | keepalive / max connections | 128 / 160 | `lc:330-350`, `cfg:80` |
| CLI subprocess timeout | `LLM_CLI_TIMEOUT` (read at import) | 180 s | `lc:29` |

---

## 5. Retries, failover and breakers

| Scope | Mechanism | Defaults | Anchor |
|---|---|---|---|
| `LLMClient.chat` | 3 attempts, backoff 2 s / 4 s, `Retry-After` ≤ 30 s | — | `lc:44-46,233-244,459-493` |
| `LLMClient` 422 breaker | consecutive content-filter errors | 5 → 300 s | `lc:116-123,158-165` |
| `LLMClient` 429 breaker | consecutive quota-like attempts | 8 → 120 s | `lc:135-142,168-176` |
| `LLMClient` failover | single hop to `LLM_FALLBACK_*`; 900 s cooldown on a deterministic 401/400 | off unless set (`.env.example:300` recommends `antigravity`) | `lc:524-595` |
| Run outage breaker | N consecutive provider-level failures, then fail fast plus `ProviderOutageHalt` | N = 10 | `cfg:69`, `po:379-660`, `po:8965-8969` |
| Graphiti | temperature ladder ×2 → graphiti tenacity → episode re-roll ×1 → fallback-client swap → per-chunk cap of 2 attempts → serial 429 replay after a 15 s cooldown | — | `ga:162-245`, `cfg:1324,1326,1342`, `grt:143-181,594-660` |
| OASIS HTTP path | CAMEL/SDK retries (not traced), then the guard falls back to `LLMClient` | `SIM_LLM_FALLBACK=true` | `ollm:348-376`, `cfg:603` |
| v3 gateway | transient ≤ 5 attempts (8/20/45/90 s + jitter); unknown/aborted ≤ 2; GLM parameter ladder; widened cap ≤ 64K; failover to `DEERFLOW_FALLBACK_MODEL` (quota/auth sticky, transient one attempt) | — | `rg:1093-1111`, `rg:1503-1585`, `rg:1670-1825` |
| Legacy tool-free | SDK `max_retries` (2), then `DEERFLOW_FALLBACK_MODEL` with a 900 s circuit and a half-open probe | — | `dr:6451-6600`, `cy:111,144,181,214` |
| Research child, as a whole | the runner does not retry; bounded retries live in the callers (orch-b map). Failed attempts flush their spend | — | `po:2113-2140` |

---

## 6. Token and spend budgets

| Budget | Unit | Enforcement point | Default | Anchor |
|---|---|---|---|---|
| `LLM_RUN_BUDGET_TOKENS` / `LLM_RUN_BUDGET_USD` | Metered tokens / estimated USD of the run (includes synthetic research and sim rows once recorded) | **After** each `LLMClient.chat`/`chat_with_tools` call. Cache hits skip the check | 0 / 0 (off) | `cfg:64-65`, `lc:520-521,745-746`, `tel:403-426` |
| v3 `budget_units` | Weighted tokens (uncached·w_u + cached·w_c + cache_write·w_cw + output·w_o) | Before each attempt (estimate × w_u). `can_spend` keeps a 35% reserve where the engine asks for it | 1.2M / 2.5M / 5M (quick/standard/deep) | `lr:615-631`, `lr:101`, `rg:926-937,1490-1500,1587-1595` |
| v3 time budget | seconds | `Deadline` on every call | 1200 / 2700 / 5400 s, capped at 0.85 × `DEERFLOW_RESEARCH_TIMEOUT` | `lr:615-631,754-760`, `rg:1055-1086` |
| v3 per-call output caps | tokens | bound `max_tokens` | agent 6000, json 16000, write 20000 | `rg:573` |
| Legacy multipart synthesis | Output tokens across all section calls | `SynthesisExecutionBudget.reserve` | per run | `dr:6425-6447` |
| Legacy summarization | Thread tokens | DeerFlow summarization middleware | trigger 80K, keep 16K | `cy:1298-1329` |
| Research tool budgets | Tool **calls** (search/fetch/attempts), not tokens | `research_budget` admission per epoch and lane | attempts 1800; search 900 global / 360 lane; fetch 450 / 180 | `rb:30-34` |
| Prompt sizing | chars | `token_budget.slice_budget_chars` for prior sections, persona context and world brief | window − 8192 reserved | `cfg:118-157` (llm-telemetry map) |

---

## 7. Usage and cost accounting

### 7.1 The meter (`tel`)

- **`LLMMeter.record`** (`tel:231-270`). Run id comes from the explicit argument, else the contextvar, else the **sole active run** (marked `fallback_attributed`), else `_global`. Stage comes from the argument, else the contextvar, else `"_unstaged"`. Cost is `estimate_cost(provider, …)`, and 0 for cache hits.
- **Price table** (`tel:93-110`): USD per 1K tokens, (input, output).

  | Provider | Input | Output |
  |---|---|---|
  | openai | 0.005 | 0.015 |
  | deepseek | 0.00027 | 0.0011 |
  | qwen | 0.0004 | 0.0012 |
  | glm | 0.0006 | 0.0022 |
  | minimax | 0.0003 | 0.0011 |
  | kimi | 0.0006 | 0.0022 |
  | gemini | 0.0003 | 0.0025 |
  | proxy, antigravity, claude-cli, codex-cli | 0 | 0 |

  `LLM_COST_PER_MTOK` overrides the table (`tel:128-167`). Prices are per provider, not per model, and cached-input discounts are not modelled.
- **`cost_basis`** in snapshots is `subscription`, `mixed` or `api`. `cost_estimated` flags proxy and unknown providers (`tel:117`, `tel:170-173`, `tel:273-334`).

### 7.2 What feeds the meter, per stage

| Stage | Entry into the meter | Granularity | Anchor |
|---|---|---|---|
| Backend `LLMClient` calls (ontology, graph, prepare, report, API) | Directly in `chat()`/`chat_with_tools()` | per call, `provider:model` | `lc:507-517,735-744` |
| RESEARCH (success) | One synthetic row: `provider = "claude-cli" if model in ("claude","codex") else model`, tokens = sum of parsed `[usage]` lines, latency = wall | one row per research completion | `po:10430-10471`; parse `po:2481-2525,2701-2735`; dict `po:2670-2680`; call `po:12205` |
| RESEARCH (failed/cancelled attempt) | Same mapping, flushed once from the `run()` wrapper | one row per failed attempt | `po:2035-2096`, `po:2113-2140` |
| RESEARCH (parallel lanes) | Lane telemetry summed, wall = max | one row | `po:11592-11615`, `po:11794-11808` |
| RUN (sim child) | Child writes `sim_llm_telemetry.json` (calls, errors, tokens, `by_source` provider/estimate/missing, `by_model`, `meter_run_token`). The orchestrator records it **once per `meter_run_token`** with stage `run`, provider from the file (else the same claude/codex mapping) | one row per sim process | `rps:2047-2225`; `po:10473-10555`; marker `po:10502-10506,10531-10535`; calls `po:13067,13123` |
| ENSEMBLE backend calls | stage `ensemble` | per call | `po:8617` |

### 7.3 Persisted sinks

| Artifact | Writer | Content | Anchor |
|---|---|---|---|
| `uploads/pipelines/<id>/run_telemetry.json` | `_flush_run_telemetry`: incremental (`in_flight`), every `PIPELINE_TELEMETRY_FLUSH_EVERY_CALLS` (20) new calls or on stage transitions; final in `_run`'s `finally` | `LLMMeter.snapshot` + `previous_attempt` + `cumulative_total`; final extras `report_telemetry` and `sim_llm_health` | `po:7557-7632`, `cfg:490`, `po:13402-13436` |
| `uploads/pipelines/<id>/telemetry.json` | `build_stage_telemetry` | stage × {calls, input/output tokens, est_cost_usd, wall_seconds} | `po:13443-13452`, `tel:445-488` |
| `state.options.llm_telemetry` | same | compact total, by_stage, cost flags (exposed through `/status`) | `po:13454-13461` |
| `reports/<rid>/telemetry.md` (and the `full_report.md` appendix only if `REPORT_TELEMETRY_APPENDIX`) | `render_telemetry_appendix` | Markdown table | `po:13466-13481`, `cfg:395`, `tel:491-528` |
| `reports/<rid>/telemetry.json` | ReportAgent | report-stage totals (meter delta) plus per-section rollup | `ra:11163-11176`, `ra:11603-11640` |
| Status API `live.spend_so_far` | `heartbeat_status` | live meter snapshot (in-process only) | `po:10302-10327` |
| `handoff/v3/usage.json`, `meta.json.usage` | v3 `attach_telemetry` | gateway ledger: total, phases, per-call rows (cached, cache_write, units, served_by) | `lr:5882-5890`, `rg:967-1048` |
| `handoff/research_budget.json` | `research_budget.export_telemetry` | tool-call counters, model-lease acquisitions/waits/peak, provider-circuit counts | `po:1863,2008-2009`, `rb:1463` |
| `simulations/<sid>/sim_llm_telemetry.json`, `llm_health.json`, `llm_fallback.jsonl` | sim child | as above | `rps:2179-2225,2270-2308`, `ollm:272-295` |
| `state.options.research_telemetry` (includes `tokens_cached`) | orchestrator | raw research telemetry; the cached count is kept here only | `po:10441-10444` |

The meter lives only in memory and is reset at the end of each attempt (`po:13483`). `LLMMeter.write_run_telemetry` and `status_snapshot` have no production caller (llm-telemetry map, Surprise 12).

---

## 8. Findings: accounting gaps and hazards (verified in code unless marked)

- **F1. The sim child double-counts decision-channel spend.**
  - `_wrap_llm_client_usage` wraps both `client.chat` and `client.chat_json` as instance attributes (`rps:2123-2176`).
  - `LLMClient.chat_json` calls `self.chat` (`lc:613`), which now resolves to the wrapped `chat`. Each provider call is therefore recorded once by the inner `chat` wrapper and again by the outer `chat_json` wrapper (the outer one re-reads the same `_last_usage`).
  - The decision channel only calls `chat_json` (`backend/app/services/decision_channel.py:247`). Both of its paths are wrapped (`rps:3446`, `rps:6005`).
  - **Probed:** an AST-extracted copy of the wrapper around a stub client gave `calls=2, prompt=200, completion=20` for one 100/10-token call.
  - Effect: `sim_llm_telemetry.json` and the stage-`run` meter row overstate decision-channel calls and tokens by about 2× (more when `chat_json` retries).
- **F2. Spend after the RUN boundary is never metered.**
  - The orchestrator records `sim_llm_telemetry.json` once per `meter_run_token` and skips every later read with the same token (`po:10502-10506`).
  - The child rewrites the file after the round loops (`rps:5949-5952`) and again at process exit (`rps:6141-6147`). Its comment expects the exit write to include "随后的决策通道/采访花费".
  - Report-stage agent interviews run in that same child after the RUN boundary (`zt` interview tools → `SimulationRunner` IPC). They are counted in the child accumulator but never enter the meter.
  - Inferred from the code paths. Whether the post-hoc decision channel finishes before the orchestrator's single read is not established (see open questions).
- **F3. Seed-ensemble simulations are unmetered.** `_run_one_seed` launches `SimulationRunner.start_simulation` (`po:8808`) and never calls `_record_sim_run_telemetry`. The only call sites are `po:13067,13123`. Off by default (`N_FORECAST_SEEDS=1`, `cfg:303`).
- **F4. Persona generation is unattributed.** `OasisProfileGenerator` runs `generate_single_profile` on a plain `ThreadPoolExecutor` without `copy_context` (`backend/app/services/oasis_profile_generator.py:2404-2408`). `LLMClient.chat` reads `(None, None)` from the contextvars (`lc:422-423`), so `LLMMeter.record` books those calls to the sole active run with stage `_unstaged`, or to `_global` when 0 or ≥ 2 runs are active (`tel:233-244`). The same applies to every Flask-thread call (dossier translation `backend/app/api/research.py:510-513`, report chat `backend/app/api/report.py:1562`). With exactly one pipeline in flight, a user's translation is billed to that pipeline and also feeds its outage breaker (`po:554-577`).
- **F5. Research cost is priced flat and lands late.**
  - Research enters the meter as one row at stage completion (`po:12205`). During RESEARCH, live `spend_so_far` and the incremental flushes show no research spend (`po:10302-10327`).
  - Cached prompt tokens (`tokens_cached`) are stashed but never priced: `LLMMeter.record` has no cached-token field, and research rows price every input token at the uncached rate (`po:10459-10467`, `tel:231-247`).
  - With the default `claude`, the provider maps to `claude-cli`, so cost is 0 (`po:10457`, `tel:108-109`).
  - The v3 gateway's own weighted ledger (`usage.json`) is the only cache-aware cost view.
- **F6. Research LLM calls outside the v3 gateway.** Prediction-market query derivation and relevance scoring run through the legacy bridge invoker (`lr:5548-5549` → `dr:15436`, `dr:14858`). They are not limited by the gateway semaphore or `budget_units`, are not in `usage.json`, and use the 900 s bridge circuit instead of the gateway failover. They do emit `[usage]` lines, so the orchestrator total includes them.
- **F7. An explicit model can be silently overridden.** With `LLM_TIERED_ROUTING=True` (default, `cfg:92`), a non-fallback `LLMClient` sends `Config.strong_model()`/`fast_model()`, which falls back to the global `LLM_MODEL_NAME`, instead of its own `self.model` (`lc:370-374`). Forecast ensemble clients built as `LLMClient(provider=p, model=PROVIDER_META[p]['default_model'])` (`fx:2615-2617`) therefore send the primary provider's model name to another provider's endpoint. Confirms llm-telemetry map Surprise 1.
- **F8. The budget guard is post-hoc and swallowed on failover.** `check_budget` runs after the paid call (`lc:520-521`). `BudgetExceeded` is a `RuntimeError` (`tel:86`) and is swallowed inside `_try_fallback` (`lc:586-595`). The orchestrator's classifier skips only true `BudgetExceeded` instances (`po:409-413`).
- **F9. Hot provider switching is incoherent across clients.** `apply_provider` updates `Config` and `os.environ` (`cfg:946-971`). The following keep the old values until restart:
  - `OPENAI_COMPATIBLE_PROVIDERS`, computed at import (`lc:34-41`);
  - breaker thresholds, read at import (`lc:116-142`);
  - the Graphiti runtime's cached LLM client (`grt:358-364`).

  Sim children and research children inherit the new env when they are spawned.
- **F10. `Config` does not show the effective OASIS concurrency.** The effective HTTP default is 30 (`ollm:29,615`, `backend/app/services/simulation_runner.py:2732`), while `Config.OASIS_SEMAPHORE=24` (`cfg:1091`) and its comment claims parity with 30 (`cfg:1084-1086`). Also noted by the sim-profiles and sim-runtime maps.
- **F11. Comment drift about `cached=` in `[usage]` lines.** The orchestrator comment says engine v3 "appends provider prompt-cache reads" (`po:2718-2721`). The legacy bridge appends `cached= cache_write= reasoning=` too, whenever the provider reports them (`dr:6322-6348`, `dr:10170-10187`). The parser handles both (`po:2722-2735`).
- **F12. Tokens from failed attempts are not metered in `LLMClient`.** `_last_usage` is reset per `chat()` call and overwritten on each attempt (`lc:441`, `lc:951-959`). A billed reply that raises (empty content, `lc:961-969`) is never metered. Only the final successful attempt's usage is recorded (`lc:507-517`).

---

## 9. Model and provider defaults at a glance (`cy` stanzas)

| Stanza | Class | Model | Notes | Anchor |
|---|---|---|---|---|
| `claude` (first in the list) | `deerflow.models.claude_provider:ClaudeChatModel` | `claude-opus-4-8` | Code-plan OAuth, `max_tokens` 64000, thinking off, prompt caching on | `cy:45-67` |
| `antigravity` | `PatchedChatOpenAI` | `gemini-3-flash-preview` | `$LLM_FALLBACK_API_KEY`/`$LLM_FALLBACK_BASE_URL`, effort low, `max_retries` 2, timeout 900 s | `cy:76-90` |
| `minimax` | `PatchedChatMiniMax` | `MiniMax-M3` | `max_retries` 2, timeout 900 s | `cy:98-127` |
| `deepseek` | `PatchedChatDeepSeek` | `deepseek-v4-pro` | `max_retries` 2 | `cy:137-157` |
| `qwen` | `langchain_openai:ChatOpenAI` | `qwen3.7-max` | `enable_thinking` toggle | `cy:174-191` |
| `glm` | `langchain_openai:ChatOpenAI` | `glm-5.3` (display name still "GLM-4.6") | `open.bigmodel.cn/api/coding/paas/v4` | `cy:207-225` |
| `codex` | `openai_codex_provider:CodexChatModel` | `gpt-5.5` | no key or base_url (ChatGPT plan) | `cy:235-243` |
| `kimi` | `langchain_openai:ChatOpenAI` | `kimi-k2.7` | `max_retries` 2, timeout 900 s | `cy:251-260` |

The backend plane A defaults are separate: kimi `kimi-k2.7`, minimax `MiniMax-M3`, deepseek `deepseek-chat` (not v4-pro), qwen `qwen-plus`, glm `glm-4.6`, openai `gpt-4o-mini` (`cfg:752-798`). The same provider label can therefore mean different models in research and in report or simulation.
