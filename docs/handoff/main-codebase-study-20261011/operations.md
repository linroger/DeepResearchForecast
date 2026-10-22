# Main codebase study: operations

Source authority: **main, `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`**, frozen tracked tree `/tmp/drf-main-study-c20ec60-20261011/source`. Owner: `operations`. Study date: 2026-10-11. Status: complete as a static source study.

The operations surface consists of the shared LLM client, process-local usage/cache/budget utilities, the Polymarket adapter, operational CLIs, and an alternative `drf2` driver/MCP engine tree. The working application path is Flask → `PipelineOrchestrator`; `drf2` remains a separately invoked preview. This conclusion follows the actual research API call to `PipelineOrchestrator.start` (`backend/app/api/research.py:109`), the normal launcher (`scripts/start.sh:361`), the opt-in preview setup block (`setup.sh:739`), and the frozen preview status (`drf2/README.md:3`).

## Evidence boundary and coverage

All **44 assigned Python files, 14,995 source lines**, were read end to end in bounded chunks, including package initializers and the six `backend/scripts/test_*.py` programs. Each assigned file was also compared byte for byte with `git show c20ec60909fa1aa15154bb6fdb3fdb71c421e10e:<path>`; all 44 matched. The companion `operations-coverage.json` is an array of `{path, sha256, read_ranges, depth, notes}`. Ranges are inclusive, one based, and cover the actual complete reads; `depth=reviewed-full` means source understanding, not executed behavior.

The shared checkout was already dirty. Only this report and its coverage JSON were written. No feature branch, live run, credential file, application entrypoint, provider, dependency installation, or application test was used. Existing maps were not treated as evidence. Supplementary callers/configuration/launch files were inspected selectively; the test index below uses static declarations rather than full test-file review. The six assigned script tests are fully reviewed because they are owned operations source; this does **not** imply full review of `backend/tests`.

## 1. Launch, setup, dependency and CI topology

### Entrypoints and process ownership

| Surface | What exists in main | Source anchor |
|---|---|---|
| Root npm commands | `setup` installs root/frontend packages; `setup:backend` uses `uv sync --python 3.12`; `dev` uses `concurrently --kill-others`; `start`/`stop` invoke the detached launcher; `test` invokes backend pytest; `build` builds the frontend. | `package.json:5` |
| Backend entrypoint | `main()` first calls `Config.validate()`, creates Flask, invokes resolution-monitor autorun, then runs threaded Flask. Defaults: `FLASK_HOST=127.0.0.1`, `FLASK_PORT=5001`, Config debug setting. | `backend/run.py:25` |
| API authority | Flask registers graph/simulation/report/research/settings blueprints and optionally `/api/v1`; research start calls the existing preflight and `PipelineOrchestrator.start`. Built SPA assets can also be served directly by Flask. | `backend/app/__init__.py:199`; `backend/app/api/research.py:100` |
| Detached development launch | `_start_backend()` executes `backend/.venv/bin/python run.py`; `_start_frontend()` executes `npm run dev`, both through `nohup`, redirected stdin/stdout/stderr, PID files and `disown`. Logs are root `logs/backend.out.log` and `logs/frontend.out.log`. | `scripts/start.sh:361` |
| Readiness and attached observation | Backend JSON must identify `MiroFish Backend`; frontend HTML must identify DeepResearchForecast. Startup verifies process/listener ownership, rolls back newly started services on failure, and attached mode follows logs plus durable pipeline events. Ctrl-C ends followers while leaving services running. | `scripts/start.sh:309`; `scripts/start.sh:497`; `scripts/start.sh:595` |
| Durable progress watcher | `PipelineProgressWatcher.poll()` scans `*/pipeline_state.json`; initial attached polling suppresses completed history, discovers new pipelines, and emits meaningful stage status/error or 5-point progress-bucket changes. `--once` includes the current snapshot. No API/LLM dependency. | `scripts/watch_pipeline_progress.py:75`; `scripts/watch_pipeline_progress.py:126` |
| Port-80 convenience | Separate sudo script can disable bundled Apache, install a loopback pf redirect to `DRF_PORT`/5001, and install a boot LaunchDaemon. It has explicit status/uninstall modes; it is outside ordinary startup. | `scripts/setup_port80.sh:1`; `scripts/setup_port80.sh:66` |

`scripts/start.sh` has independently named startup/monitor settings: `START_BACKEND_TIMEOUT_SECONDS`, `START_FRONTEND_TIMEOUT_SECONDS`, `START_HEALTH_CURL_TIMEOUT_SECONDS`, `START_HEALTH_FAILURE_GRACE_SECONDS`, `START_MONITOR_INTERVAL_SECONDS`, and `START_FOLLOWER_RESTART_LIMIT` (`scripts/start.sh:41`). Attached mode restarts failed log/progress followers up to the configured limit and checks service health continuously (`scripts/start.sh:622`). These are launcher controls, separate from pipeline watchdogs.

### Setup and runtime layout

`setup.sh` supplies a provider picker for `claude-cli`, `codex-cli`, `openai`, `kimi`, `minimax`, `deepseek`, `qwen`, and `glm`, with corresponding research model identities. Existing `.env` provider selection is preferred as the menu default; otherwise local Claude CLI precedes Codex CLI detection (`setup.sh:153`, `setup.sh:189`). This is a description of the script, not an observation of the user's configured provider.

The dependency installation steps use root/frontend npm installs and backend `uv sync --python 3.12`. DeerFlow is assembled separately under `DEERFLOW_DIR`, default `deer-flow/`: a vendored `DEERFLOW_VENDOR_DIR`, default `deer-flow-2.0.0/`, precedes an upstream clone using `DEERFLOW_REPO` and pinned `DEERFLOW_REF=799bef6d9dbc3a2cb37ce8177eeeabe2a33d8971`. The acquisition block trims newly acquired runtime material; an existing engine is reused (`setup.sh:437`, `setup.sh:489`, `setup.sh:520`).

The overlay installs the research entrypoint and bare-import tool modules (`market_tools.py`, `search_tools.py`, `cached_fetch.py`, `research_budget.py`, `runtime_skill_sync.py`, `linear_research.py`, `research_gateway.py`). It copies provider/middleware patches, invokes the authoritative runtime-skill synchronizer, and applies subagent, lead-agent, and model-factory overlays. Required skill/subagent/lead overlay failures abort setup; several installation failures instead warn. Existing DeerFlow `config.yaml` is preserved; an absent one receives the tracked bridge template. DeerFlow has its own `backend/.venv`, built using `UV_PROJECT_ENVIRONMENT` and `uv sync --project ... --python 3.12` (`setup.sh:571`, `setup.sh:623`, `setup.sh:655`, `setup.sh:701`, `setup.sh:715`).

`SETUP_DRF2=1` adds an optional preview setup block that installs the MCP transport requirements into the existing backend environment and prints preview commands. It does not replace the Flask launch path (`setup.sh:739`). KG declares `mcp>=1.24.0`; simulation declares `mcp>=1.2` (`drf2/engines/kg/requirements.txt:5`, `drf2/engines/simulation/requirements.txt:4`).

The backend package requires Python **>=3.12** and declares Flask/CORS, OpenAI plus `h2`, `graphiti-core==0.29.2`, embedded FalkorDB, Redis `<8`, sentence-transformers, `camel-oasis==0.2.5`, `camel-ai==0.2.78`, file parsing, Plotly/Kaleido/matplotlib, dotenv and Pydantic. Its uv override fixes Neo4j at `5.23.0` to reconcile OASIS/Graphiti declarations; source comments identify FalkorDB as the used graph backend. Pytest/pytest-asyncio are development dependencies; the wheel packages `app` (`backend/pyproject.toml:1`, `backend/pyproject.toml:61`). Frontend uses Vue 3, Vue Router, Axios, D3 and Vite; its own unit command is `node --test tests/*.test.mjs` (`frontend/package.json:6`). Root Node declaration is `>=20.19.0` (`package.json:24`).

### Static dependency references and lock

The frozen `backend/requirements.txt` is a separate pip-install reference: its header states Python 3.11+, includes `zep-cloud==3.13.0`, OASIS/CAMEL, parsing, matplotlib, MCP, Plotly/Kaleido and NetworkX, and describes optional visualization behavior (`backend/requirements.txt:4`, `backend/requirements.txt:16`, `backend/requirements.txt:37`). The normal setup commands above use the uv project; these two dependency declarations are distinct source artifacts. No environment was installed or reconciled during this study.

Static TOML metadata extraction of `backend/uv.lock` found format version 1/revision 2, Python >=3.12 and 206 package records (`backend/uv.lock:1`). Selected locked resolutions are Graphiti 0.29.2 (`backend/uv.lock:726`), FalkorDBLite 0.10.0 (`backend/uv.lock:596`), Redis 7.4.1 (`backend/uv.lock:2691`), sentence-transformers 3.0.0 (`backend/uv.lock:3102`), OpenAI 1.109.1 (`backend/uv.lock:1939`), httpx 0.28.1 (`backend/uv.lock:817`), h2 4.3.0 (`backend/uv.lock:753`), Plotly 6.9.0 (`backend/uv.lock:2161`), Kaleido 1.3.0 (`backend/uv.lock:1130`), matplotlib 3.11.0 (`backend/uv.lock:1436`), MCP 1.24.0 (`backend/uv.lock:1502`), pytest 8.2.0 (`backend/uv.lock:2439`) and pytest-asyncio 0.23.6 (`backend/uv.lock:2454`). CAMEL/OASIS lock at 0.2.78/0.2.5; Neo4j at 5.23.0 (`backend/uv.lock:145`, `backend/uv.lock:168`, `backend/uv.lock:1688`).

The editable root package record lists the uv project dependencies (`backend/uv.lock:1527`). MCP is also present through CAMEL's transitive dependency record; `zep-cloud` is absent from this lock's package-name index. These are lock declarations, not installed-version observations or a solver/install result. Lock inspection was targeted metadata extraction; no claim is made of full semantic review of all wheel URLs, hashes and platform markers. The setup comment refers to `backend/.python-version`, but that file was not present in the frozen mirror; the inspected executable setup passes Python 3.12 explicitly (`setup.sh:468`).

### Preflight, doctor, smoke and CI

`environment_report(mode, model, deep=False, pull=False)` combines `preflight_pipeline()` errors with Config metadata and placeholder checks, producing `{provider, deerflow_model, graph_backend, venv_python, deerflow_dir, data_dir, embed_model, mode, ready, exit_code, checks}`. A check carries `{id, severity, ok, message, fix}`; `bad` yields exit 1, warning-only yields 2, clean yields 0 (`backend/scripts/preflight.py:73`, `backend/scripts/preflight.py:414`).

Cheap checks are distinct from opt-in deep probes. Deep mode checks configured LLM/research credentials, embedding-cache presence and free disk; `--pull` may download a missing embedding model. Despite the introductory “1-token” description, `_live_openai_compat()` constructs a completion with `max_tokens=16`, a 25-second SDK timeout and zero SDK retries. CLI probes only check executable presence. Disk checks use existing ancestor directories and classify below 2 GiB as blocking, below 5 GiB as warning. `--deep --json` emits **probe-only JSONL** `{level,message}`, while ordinary `--json` emits the structured readiness document (`backend/scripts/preflight.py:195`, `backend/scripts/preflight.py:229`, `backend/scripts/preflight.py:378`, `backend/scripts/preflight.py:486`).

`check_env_drift.py` has two independent modes. Default mode compares literal Config environment reads to documented assignments in `.env.example`; `--strict` fails on missing documentation, while documented-but-unread names are informational. `--pins` parses runtime assignments, compares them to literal defaults or example values, masks credential-name segments, and sorts critical divergences first; only `--pins --strict` with a performance-critical divergence returns 1. The parser honors `export`, quotes, inline comments and last assignment wins (`backend/scripts/check_env_drift.py:103`, `backend/scripts/check_env_drift.py:135`, `backend/scripts/check_env_drift.py:214`, `backend/scripts/check_env_drift.py:287`). No runtime `.env` was inspected during this study.

`doctor.sh` owns local tool/venv/config checks and invokes environment-documentation/pin checks; deep mode delegates to `preflight.py --deep --json`, with an embedded fallback if that helper is absent (`scripts/doctor.sh:113`, `scripts/doctor.sh:226`, `scripts/doctor.sh:268`). `smoke.sh` declares a stubbed stage-contract path, with real graph and micro-simulation legs gated by `SMOKE_GRAPH=1` and `SMOKE_FULL=1`. Its normal intent is deterministic local contract checking; these scripts were read, not run (`scripts/smoke.sh:3`, `scripts/smoke.sh:56`).

Frozen CI triggers main pushes and PRs. Jobs are: Ruff `F,E9` over `backend/app`, `backend/scripts`, `deerflow_bridge` with selected ignores; strict env-documentation drift; Python 3.12 backend `uv run pytest -q`; and compileall over those three source roots. The YAML's unit step first creates a uv environment and installs pytest/dotenv, then invokes the project command. These are declared commands, not an observed CI result or a proof of what uv resolved. There is no frontend build/unit job or explicit `drf2` Ruff/compileall target in this YAML; backend test modules do contain `drf2` characterization (`.github/workflows/ci.yml:10`, `.github/workflows/ci.yml:23`, `.github/workflows/ci.yml:40`).

## 2. Shared LLM client: routing, retries, tools, cache and usage

`LLMClient(provider=None, api_key=None, base_url=None, model=None)` resolves omitted/falsy arguments through Config, validates provider membership, and builds a synchronous OpenAI SDK client only for OpenAI-compatible identities. Compatibility comes from `Config.PROVIDER_META` plus the fallback-only `antigravity` identity; CLI identities are `claude-cli` and `codex-cli` (`backend/app/utils/llm_client.py:31`, `backend/app/utils/llm_client.py:247`). Frozen Config defaults `LLM_PROVIDER` to Claude CLI (`backend/app/config.py:750`).

Import/callsite indexing finds the shared client in ontology, persona/config generation, report synthesis, Graphiti adaptation, graph retrieval helpers and OASIS adapters. Concrete indexed callers include `OntologyGenerator` initialization (`backend/app/services/ontology_generator.py:480`), `ReportAgent` initialization (`backend/app/services/report_agent.py:1671`), `AppGraphitiLLMClient` (`backend/app/services/graphiti_client/llm_adapter.py:100`), `ZepToolsService` lazy construction (`backend/app/services/zep_tools.py:577`) and OASIS adapter construction (`backend/app/utils/oasis_llm.py:393`). These caller references were searched selectively, not fully reviewed in operations ownership.

### Ordinary `chat()` path

1. Resolve model tier; capture `(run_id, stage)` context; build a content-addressed cache key if enabled. Cache hit returns text immediately and records a zero-token cached call when telemetry is enabled (`backend/app/utils/llm_client.py:418`).
2. If the primary provider breaker is cooling down, try the configured fallback immediately. If unavailable, raise without entering the primary retry loop (`backend/app/utils/llm_client.py:444`).
3. Otherwise perform at most **three primary attempts**, retrying `RuntimeError` and imported SDK rate-limit/timeout/connection/internal-server exceptions. Deterministic authentication failures break early. Delay defaults to 2 then 4 seconds; numeric Retry-After can increase that delay, capped at 30 seconds. Other exceptions break toward fallback (`backend/app/utils/llm_client.py:233`, `backend/app/utils/llm_client.py:459`).
4. If primary attempts fail, `_try_fallback()` may serve the request. Fallback recursively calls its own `chat()` with failover disabled, so “one fallback” means one selected fallback client invocation, which still has its own internal retry policy (`backend/app/utils/llm_client.py:494`, `backend/app/utils/llm_client.py:581`).
5. Successful primary output is metered from SDK usage or estimated text lengths. A fallback-served request skips outer primary metering. The successful text is cached, then token/USD limits are checked; a budget exception can therefore occur after a response has been produced and cached (`backend/app/utils/llm_client.py:507`).

The function docstring still says SDK errors are outside its retries, but the executable catch tuple includes the named retryable SDK classes (`backend/app/utils/llm_client.py:410`, `backend/app/utils/llm_client.py:472`). If the tuned HTTP client is constructed, SDK retries are explicitly disabled; otherwise SDK defaults remain in force. HTTP/2 setup uses keepalive=`LLM_HTTP_KEEPALIVE` and max connections=keepalive+32, with construction fallback to HTTP/1.1 and then SDK default. Client timeout uses `LLM_HTTP_TIMEOUT_S` with a 600-second fallback; the tuned httpx timeout is 600 seconds with a 10-second connect timeout (`backend/app/utils/llm_client.py:285`, `backend/app/utils/llm_client.py:316`).

### Tier and fallback resolution

`_model_for_tier()` returns a fallback client's already resolved model unchanged. For ordinary clients, disabled tiering uses `self.model`; fast uses `Config.fast_model()`, strong/unknown uses `Config.strong_model()`, each falling back to the instance model. A separate fast SDK client is lazy and requires all of `LLM_FAST_PROVIDER`, `LLM_FAST_BASE_URL`, `LLM_FAST_API_KEY`; construction failure keeps the primary client (`backend/app/utils/llm_client.py:356`, `backend/app/utils/llm_client.py:376`).

The frozen Config assignments enable `LLM_TIERED_ROUTING`, `LLM_HTTP2`, `LLM_CACHE_ENABLED` and `LLM_TELEMETRY_ENABLED` by default; unset fast/strong model aliases fall back, so enabling tiering alone does not establish a different model. Some module comments describe older off defaults; the assignments are authoritative (`backend/app/config.py:56`, `backend/app/config.py:79`, `backend/app/config.py:92`). CLI dispatch does not implement distinct fast/strong transport behavior.

Fallback reads `LLM_FALLBACK_PROVIDER`, `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_BASE_URL`, `LLM_FALLBACK_API_KEY` from the environment at call time. Empty/same-provider fallback is skipped. A different OpenAI-compatible fallback without an explicit model is refused rather than inheriting the primary alias. Fallback authentication/invalid-request errors create a 900-second process cooldown keyed by provider/model/base URL. The fallback OpenAI pool cache also uses provider/model/base URL, while wrapper instances remain per invocation (`backend/app/utils/llm_client.py:524`).

Content-filter and quota circuits share `tripped_until`, under `_CB_LOCK`. Defaults: five content-filter failures/300 seconds (`LLM_CB_422_THRESHOLD`, `LLM_CB_COOLDOWN_S`), eight quota failures/120 seconds (`LLM_CB_429_THRESHOLD`, `LLM_CB_429_COOLDOWN_S`). Primary success resets both streaks. The classifiers inspect exception strings for content filtering, 422, quota and rate-limit indications (`backend/app/utils/llm_client.py:104`, `backend/app/utils/llm_client.py:132`, `backend/app/utils/llm_client.py:152`).

### HTTP payload, CLI payload and structured output

OpenAI transport sends `{model,messages,temperature,max_tokens}` plus optional response format, provider reasoning controls and contextual timeout. Kimi adds `LLM_USER_AGENT` at construction and forces temperature to 0.6 with thinking disabled or 1.0 otherwise. Fallback-only `LLM_FALLBACK_REASONING_EFFORT` accepts minimal/low/medium/high. Reasoning body selection follows the serving wrapper's provider. Missing/blank content raises a retryable RuntimeError; complete `<think>...</think>` spans are stripped (`backend/app/utils/llm_client.py:870`, `backend/app/utils/llm_client.py:885`, `backend/app/utils/llm_client.py:912`).

CLI messages are flattened with system instructions and optional JSON-only instructions. Prompt text goes through stdin; subprocess cwd is `/tmp`; timeout comes from `LLM_CLI_TIMEOUT`, default 180 seconds. Claude uses `claude -p --output-format json`, optionally disables hooks through settings and passes a Claude-compatible model alias. Codex uses `codex exec --skip-git-repo-check` and extracts its answer from CLI stdout. Nonzero exits, error envelopes, blank output, launch failures and timeouts become RuntimeErrors. By default Claude/Codex child environments remove `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`; `LLM_CLI_USE_API_KEY=true` preserves them (`backend/app/utils/llm_client.py:842`, `backend/app/utils/llm_client.py:975`, `backend/app/utils/llm_client.py:1000`, `backend/app/utils/llm_client.py:1083`).

`chat_json()` tries JSON mode, local fence/object extraction and bracket/string completion, then makes one lower-temperature resend before raising ValueError. Parsing is syntactic; it returns decoded JSON without a domain-schema validator (`backend/app/utils/llm_client.py:597`, `backend/app/utils/llm_client.py:761`).

`supports_native_tools()` requires Config enablement, a compatible SDK client, provider capability/optional `LLM_NATIVE_TOOLS_PROVIDERS` whitelist and an untripped circuit. `chat_with_tools()` sends `tools` plus `tool_choice=auto`, retries transient failures, records usage, checks budget, and returns `{content, tool_calls:[{id,name,arguments}]}`; malformed arguments become `{}`. It has no CLI failover or text-result cache. On final transport error it raises for the report-side fallback path. The contextual `_CALL_TIMEOUT_S` override is applied by `_chat_openai()`, not explicitly inserted into this tools payload (`backend/app/utils/llm_client.py:632`, `backend/app/utils/llm_client.py:658`).

## 3. Telemetry, cache and context budgeting

`set_run_context()` and `set_stage()` use ContextVars. A process registry tracks active run IDs. `LLMMeter.record()` uses explicit/current run ID; an untagged thread is attributed to the sole active run when exactly one exists, counted separately as `fallback_attributed`. With zero or multiple active runs it stays `_global`; missing stage is `_unstaged`. The global bucket emits threshold warnings at 20/100/500/2000 calls (`backend/app/utils/telemetry.py:24`, `backend/app/utils/telemetry.py:42`, `backend/app/utils/telemetry.py:230`).

Each counter contains calls, cached calls, prompt/completion/total tokens, summed latency milliseconds and estimated cost USD. Run snapshots include `total`, `by_stage`, `by_model` keyed `provider:model`, `cost_estimated`, `cost_basis`, `fallback_attributed`, and a process-lifetime `unattributed_process` summary. The latter is shared process accounting, not an amount to add independently for each run. `status_snapshot()` selects a compact subset; `reset()` removes the run and its active registration (`backend/app/utils/telemetry.py:176`, `backend/app/utils/telemetry.py:272`, `backend/app/utils/telemetry.py:337`).

`estimate_cost()` uses a built-in provider table and optional `LLM_COST_PER_MTOK` JSON overrides. Unknown providers cost zero while tokens still accrue; proxy/Antigravity/Gemini/unknown names mark cost as estimated. Subscription CLI usage has zero modeled marginal cost, exposed through subscription/mixed/API `cost_basis`. These are source-defined estimates, not verified current provider prices or bills (`backend/app/utils/telemetry.py:90`, `backend/app/utils/telemetry.py:128`, `backend/app/utils/telemetry.py:306`).

`check_budget()` reads `LLM_RUN_BUDGET_TOKENS` and `LLM_RUN_BUDGET_USD` (zero/unset unlimited), chooses the same sole-run fallback, and raises `BudgetExceeded` only when recorded usage is **greater than** the limit. It does not itself call providers, reserve tokens or enforce a wall-time budget (`backend/app/utils/telemetry.py:403`). The module introduction mentions time budgeting, but these implemented checks are token/cost checks.

`LLMCache` hashes `[provider,model,messages,temperature,max_tokens,response_format]`, stores text in memory, and evicts oldest insertion-order keys above 2048 entries. Reads do not refresh order: the actual implementation is FIFO-style bounded storage rather than access-order LRU. `bypass()` is contextual and suppresses both reads and writes. The key does not contain run ID, base URL, credentials, tools schema or reasoning-body options (`backend/app/utils/telemetry.py:531`).

`write_run_telemetry()` atomically writes a snapshot and, when a prior file has calls, retains `previous_attempt` plus additive `cumulative_total`. The active orchestrator uses a separate `_flush_run_telemetry()` that adds one fixed previous-attempt baseline to the current snapshot and marks in-flight writes; `_maybe_flush_run_telemetry()` checks a call delta, default 20. This distinction matters when reading repeated flushes (`backend/app/utils/telemetry.py:363`; `backend/app/services/pipeline_orchestrator.py:7575`).

Cross-process usage is explicitly bridged. `_record_research_telemetry()` stashes research telemetry and records a synthetic stage=`research` meter entry from input/output token totals. `_record_sim_run_telemetry()` reads simulation `sim_llm_telemetry.json`, retains the raw call/error/by-source summary in options, and deduplicates synthetic stage=`run` accounting using simulation ID plus `meter_run_token` (file hash fallback). Thus a parent meter “call” can represent an entire subprocess's aggregated usage rather than one HTTP request (`backend/app/services/pipeline_orchestrator.py:10430`, `backend/app/services/pipeline_orchestrator.py:10473`).

`build_stage_telemetry()` joins stage usage and separately supplied nonnegative wall seconds, fills missing dimensions with zero and returns stage/total summaries. `render_telemetry_appendix()` renders a deterministic Markdown table in research→ontology→graph→prepare→run→report order, then unknown names lexically, with estimate/subscription notes (`backend/app/utils/telemetry.py:445`, `backend/app/utils/telemetry.py:491`).

The independent `token_budget.py` is pure calculation: ceiling-based token estimate at approximately four characters/token; character truncation; remaining context calculation; `slice_budget_chars()` preserving a historical floor; clamps; and ordered item fitting. Invalid inputs generally fall back to floor/original strings/zero as defined by each helper. This estimator is separate from telemetry's floor-based `len(text)//4` approximation (`backend/app/utils/token_budget.py:39`, `backend/app/utils/token_budget.py:77`, `backend/app/utils/token_budget.py:140`; `backend/app/utils/telemetry.py:430`).

Selective consumer review confirms report prior-section share 0.5, persona-context share 0.4, and world-brief share 0.05 plus a 1400–`SIM_WORLD_BRIEF_MAX_CHARS` clamp. These depend on `ADAPTIVE_CONTEXT`, provider window and `RESERVED_COMPLETION_TOKENS`; disabled/error paths retain fixed floors (`backend/app/services/report_agent.py:2356`, `backend/app/services/oasis_profile_generator.py:1948`, `backend/app/services/simulation_config_generator.py:1917`).

## 4. Prediction markets and their consumers

### Transport and normalized contracts

`PolymarketClient` uses public Gamma `/public-search` and `/markets`, plus CLOB `/prices-history`, without a key. `enabled` reads `PREDICTION_MARKETS_ENABLED`. `_request()` uses browser-shaped User-Agent, Accept JSON, a default 10-second timeout, and at most two attempts for transport errors or 429/500/502/503/504, sleeping with jitter before the second attempt. Other errors return `None`; exhausted failures update `last_error={error_class,http_status,url}` and per-label `transport_errors` counts (`backend/app/utils/prediction_markets.py:35`, `backend/app/utils/prediction_markets.py:209`, `backend/app/utils/prediction_markets.py:230`).

`snapshot_for_queries()` expands matching events into markets, deduplicates by market ID with first matched query retained, rejects closed markets, unparseable Yes prices, prices outside strict `(0,1)` and insufficient volume, sorts by volume, caps each event and then total. Defaults are per-query 15, total 20, volume 200 and per-event 3. Optional batch relevance scoring runs after this truncation (`backend/app/utils/prediction_markets.py:289`).

Core row: `{market_id, exchange:"polymarket", question, implied_yes_prob, volume, liquidity, event_title, matched_query}`. Available fields add event URL, end date, price/book changes, outcome names, CLOB IDs and explicit `clob_yes_token_id`. Yes is found by outcome name, including `[No,Yes]` ordering; it is not assumed to be token index zero (`backend/app/utils/prediction_markets.py:502`).

`requote_markets()` returns copied rows, preserves existing `price_at_research` or establishes it from the old probability, fetches deduplicated IDs in configurable chunks (`PREDICTION_MARKETS_REQUOTE_CHUNK`, fallback 20), and sets new probability/delta. Missing/closed/invalid quotes retain old price with `requote_failed=True` and remove stale delta. `fetch_price_history()` returns parsed `{t,p}` rows with optional client-side day cutoff (`backend/app/utils/prediction_markets.py:339`, `backend/app/utils/prediction_markets.py:390`, `backend/app/utils/prediction_markets.py:420`).

`fetch_resolutions()` returns ID-keyed `{market_id,closed,resolved,resolved_outcome,resolved_yes_price,uma_status}`. `_parse_resolution()` requires closed plus some outcome at least 0.99 to set resolved; it selects Yes by name and carries UMA status diagnostically. Although a 0.01 constant is declared, the parser's resolved predicate does not explicitly require all other legs below it (`backend/app/utils/prediction_markets.py:146`, `backend/app/utils/prediction_markets.py:465`).

### Query and report paths

`derive_market_queries()` is deterministic clause-aware phrase extraction, stopword/generic-word filtering, CJK handling, four-digit year retention, hot-topic inclusion and reserved actor slots. `derive_market_queries_llm()` asks a supplied callable for 10–16 title-like queries, tolerates JSON wrappers and fills short lists with heuristics; failure returns heuristics. `score_market_relevance()` asks once for scores, filters below configured/default 5, annotates copied rows and sorts by relevance then volume. Completely failed scoring preserves input rows/order; individually unscored rows remain at threshold rank (`backend/app/utils/prediction_markets.py:660`, `backend/app/utils/prediction_markets.py:699`, `backend/app/utils/prediction_markets.py:749`, `backend/app/utils/prediction_markets.py:810`).

`render_markets_block()` makes a deterministic English/Chinese table, event links and a delta column only when any research/current price differs (`backend/app/utils/prediction_markets.py:580`).

Selective `ReportAgent` review shows canonical `handoff/prediction_markets.json` lookup through a matching simulation's pipeline, followed by optional requote. Missing/empty handoff can use late retrieval; this caller requires an explicit relevance score on retained rows, even though the generic scoring helper preserves unscored rows. Successful late recovery can write `prediction_markets_recovered.json`. Cached snapshot prices are refreshed again before binary extraction (`backend/app/services/report_agent.py:2573`, `backend/app/services/report_agent.py:2606`, `backend/app/services/report_agent.py:2723`). Main Config also declares the research-side horizon-retry policy; its detailed bridge implementation belongs to research ownership (`backend/app/config.py:1444`).

`drf2/config/market_tools.py` is a self-contained alternative, not an import of the backend client. Its reflected tool consumes up to six comma/newline-separated queries and returns JSON text `{queries,markets,note}`. It uses per-query 8 and timeout 15, two immediate transport attempts, a smaller row schema, and no backend Config enable gate, requote/history/resolution methods or browser-UA/backoff instrumentation. Optional LangChain wrapping produces `prediction_market_search_tool`; absent LangChain leaves that variable `None` while pure helpers remain importable (`drf2/config/market_tools.py:32`, `drf2/config/market_tools.py:76`, `drf2/config/market_tools.py:159`, `drf2/config/market_tools.py:204`, `drf2/config/market_tools.py:226`).

## 5. Operational scripts: records, transitions and side effects

### Related-question batches

`BatchManager` stores `Config.PIPELINE_DATA_DIR/_batches/<batch_id>/batch.json`, validates IDs, atomically saves, stamps update/schema fields and lists records. A batch record has anchor prompt/ID, children `{prompt,pipeline_id,role}`, options, shared-simulation flag, fanout cap, skipped entries, errors and timestamps (`backend/scripts/batch_runs.py:108`, `backend/scripts/batch_runs.py:464`).

`start_batch()` accepts only full mode and nonempty prompts, preflights once, launches prompt zero as the ordinary anchor, and waits for graph-stage completion plus graph ID. The default `BATCH_MAX_FANOUT=8` caps **extra questions**, not total including anchor. Excess questions are recorded as skipped. Waits poll every five seconds, bounded by `BATCH_WAIT_TIMEOUT_S`, fallback four hours, with cancel/missing/incompatible/terminal checks (`backend/scripts/batch_runs.py:191`, `backend/scripts/batch_runs.py:374`).

Actual `fork_question()` creates a new full PipelineState with the child question, shared graph/handoff and no project ID. Only research and graph are precompleted; ontology remains pending. Shared-simulation mode also reuses simulation ID and precompletes prepare/run, leaving ontology pending. This executable behavior is more specific than the module overview's general “research/ontology/graph reuse” wording. It creates a TaskManager task, saves running state, then registers a cancel event and daemon `_run` thread under the orchestrator lifecycle lock (`backend/scripts/batch_runs.py:279`, `backend/scripts/batch_runs.py:293`, `backend/scripts/batch_runs.py:316`, `backend/scripts/batch_runs.py:337`).

Shared simulation waits for the anchor run stage; failure degrades the batch to independent simulations while preserving shared graph. Each child-fork exception is recorded independently. `batch_status()` reads child states and report `forecast.json`, calls `aggregate_forecasts()` and returns combined ensemble plus child progress. Aggregate statuses are empty/running/completed/partial. Status reads can update stored batch status; stored failed is preserved, while returned status is the child-derived aggregate. CLI commands are run/status/list; `--wait` polls completion/partial without the graph-wait deadline (`backend/scripts/batch_runs.py:494`, `backend/scripts/batch_runs.py:570`, `backend/scripts/batch_runs.py:609`, `backend/scripts/batch_runs.py:726`).

### Scheduled rerun and forecast drift

`ScheduleStore` atomically persists `uploads/schedules/sched_<id>/schedule.json`, schema 1. It records prompt/depth/options, project/language/model, interval/max-runs/enabled, last/next time, pipeline history and drift history. Creation sets next-run time to now. CRUD includes delete of the schedule directory (`backend/scripts/scheduled_rerun.py:157`, `backend/scripts/scheduled_rerun.py:214`).

`Scheduler.maybe_start()` is gated by `SCHEDULER_ENABLED` and creates a singleton daemon; the loop reconciles orphans once then ticks. `tick()` respects enabled/due time, max runs, latest run still running and a global persisted-running cap. Forced IDs bypass enabled/due checks but retain inflight/count/concurrency guards. `_launch()` invokes `PipelineOrchestrator.start`, appends the ID and advances next time; launch failure postpones the next attempt (`backend/scripts/scheduled_rerun.py:570`, `backend/scripts/scheduled_rerun.py:627`, `backend/scripts/scheduled_rerun.py:688`).

`forecast_diff()` matches normalized scenario names, flags absolute probability shifts **>=** threshold, new/dropped scenarios, new top actors and new coalition labels. Gone actors are reported but do not independently set drift. Default threshold is 0.15. `diff_pipelines()` reads forecast plus dossier/community artifacts. `_await_and_diff()` waits for new pipeline terminal state or its deadline, writes a compact drift-history entry, and optionally POSTs a `forecast_drift` webhook using `validate_safe_url` and `APP_BLOCK_PRIVATE_URLS` policy (`backend/scripts/scheduled_rerun.py:361`, `backend/scripts/scheduled_rerun.py:474`, `backend/scripts/scheduled_rerun.py:513`, `backend/scripts/scheduled_rerun.py:735`).

Main Config sets `SCHEDULER_TICK_SECONDS=300`, overriding the script helper fallback of 60. The standalone `tick`/`run-once` commands call tick directly; only daemon startup checks the enable flag. Search found no Flask startup call to this Scheduler. It is separate from the resolution autorun below (`backend/app/config.py:439`; `backend/scripts/scheduled_rerun.py:894`).

### Resolution monitoring

`run_monitor()` reads report `forecast.json`, selects binaries with `market_anchor.market_id`, requotes anchors, fetches resolutions, computes price movers and Brier contributions, detects expired binaries needing manual resolution, and renders a monitoring summary. Resolution date is first ISO date in criteria/source/statement, then horizon-year December 31. Model binary Brier is `(model_p-y)^2`, with y taken from the resolved Yes price at the 0.5 threshold (`backend/scripts/resolution_monitor.py:183`, `backend/scripts/resolution_monitor.py:197`, `backend/scripts/resolution_monitor.py:260`, `backend/scripts/resolution_monitor.py:489`).

Writes are per-report `price_track.jsonl`, ledger market-resolution records through `append_market_resolution`, and optional atomic `monitor_report.md`. Price snapshots append each run; ledger insertion is delegated to its idempotent API. Returned `resolved_count` counts observed resolved records and `newly_recorded_count` counts newly appended ones; the Markdown receives all observed records. `dry_run=True` skips these writes but still performs market reads and ledger-summary reads. Market errors produce partial/degraded reports (`backend/scripts/resolution_monitor.py:432`, `backend/scripts/resolution_monitor.py:553`). CLI resolves report/pipeline IDs, supports recent-report selection and an offline ledger-only `summary` (`backend/scripts/resolution_monitor.py:125`, `backend/scripts/resolution_monitor.py:634`).

The **active main wiring** is `backend/run.py` → `resolution_autorun.start()`, gated by `RESOLUTION_MONITOR_AUTORUN_HOURS>0` (default zero). Its worker runs the resolution script as a child with a 15-minute hard timeout, while `trigger_once()` provides inflight deduplication for manual/API use. This is not the forecast rerun Scheduler (`backend/run.py:39`; `backend/app/services/resolution_autorun.py:38`, `backend/app/services/resolution_autorun.py:63`, `backend/app/services/resolution_autorun.py:88`).

### Export, historical visual replay and disk operations

| Program / function | Inputs → output and implemented stopping rule | Source anchors |
|---|---|---|
| `export_demo_site_data.export_run` | Hardcoded RUNS key→pipeline selection; persisted research/project/simulation/report material → `docs/demos/<key>/research_log.txt`, dossier/language files, actors/sources, ontology, graph, forum, report/language files, chart namespaces and metadata with hashes. | `backend/scripts/export_demo_site_data.py:54`; `backend/scripts/export_demo_site_data.py:915` |
| Strict export validation | Requires completed clean stages, matched pipeline/project/graph/simulation/report identity, nonhollow recognized simulation health and positive counters, final read-only audit/publication/scenario success, and current Markdown/forecast hashes. | `backend/scripts/export_demo_site_data.py:221` |
| Graph export alternatives | `--graph-api` uses running backend GET; default uses GraphBuilderService. Non-strict local facade 404 can call `rebuild_graph()` and ingest saved dossier/ontology; strict mode refuses replacement. `--skip-graph` avoids graph acquisition; strict skip verifies retained graph ID. | `backend/scripts/export_demo_site_data.py:613`; `backend/scripts/export_demo_site_data.py:641`; `backend/scripts/export_demo_site_data.py:960` |
| Export assets and variants | Restricts local Markdown targets to safe `charts/<name>`, copies all languages' referenced charts into isolated namespaces, rewrites links and removes stale variants. Missing source chart can be retained only when a supplied published hash matches. Report variants require publication status; dossier variants require current source hash, available status and hard-passed matching variant audit. | `backend/scripts/export_demo_site_data.py:414`; `backend/scripts/export_demo_site_data.py:470`; `backend/scripts/export_demo_site_data.py:695` |
| Narrow refreshes | `--research-log-only` updates provenance with complete merged root/track logs; broad legacy export may retain an old log with `complete=False` when sources are gone. `--reports-only` refreshes reports and eligible translated dossiers plus asset hashes; this branch does not call the whole-run strict validator. | `backend/scripts/export_demo_site_data.py:114`; `backend/scripts/export_demo_site_data.py:153`; `backend/scripts/export_demo_site_data.py:842`; `backend/scripts/export_demo_site_data.py:1065` |
| `backfill_one` | Validates pipeline ownership of report, defaults to a plan-only return; `--apply` backs up report families then deterministically rebuilds visuals, canonical binary/comparison blocks, language/quote/lint/publish audits and PDFs. Failure restores prior bundle and writes backup-local `replay_failure.json`. | `backend/scripts/backfill_report_visuals.py:445`; `backend/scripts/backfill_report_visuals.py:739` |
| Backfill variant handling | Repairs primary prose deterministically; variants receive visual/canonical synchronization then audits. Failed variants are marked unavailable and active Markdown/PDF/citations removed while original backup remains. Citation/audit writes precede available variant Markdown publication. | `backend/scripts/backfill_report_visuals.py:511`; `backend/scripts/backfill_report_visuals.py:596` |
| `disk_usage_report` | Reads sizes under uploads/logs/bridge cache, subtracts pipeline/report footprint from other uploads, prints largest children/free space/retention observations. It never deletes. | `backend/scripts/disk_usage_report.py:17`; `backend/scripts/disk_usage_report.py:64` |
| `reclaim_report_space` | Default dry run; `--apply` enables backup purge and/or Plotly de-inlining. Backup names must match a precise timestamp shape under report children. De-inlining requires one large signed Plotly script, retained figure payload and bundle-size compatibility; rewrites via temp + replace. Existing directory-mode charts are skipped. | `backend/scripts/reclaim_report_space.py:49`; `backend/scripts/reclaim_report_space.py:82`; `backend/scripts/reclaim_report_space.py:113`; `backend/scripts/reclaim_report_space.py:161` |
| `replay_zep_dead_letters` | Reads `_zep_dead_letter/<graph_id>.jsonl`, batches `combined_text` through the existing Zep facade `graph.add`, stops a file at first failed batch, preserves malformed/unsubmitted/newly appended lines, atomically rewrites remainder or archives fully replayed source. Dry run avoids runtime construction. | `backend/scripts/replay_zep_dead_letters.py:55`; `backend/scripts/replay_zep_dead_letters.py:99`; `backend/scripts/replay_zep_dead_letters.py:143` |
| `salvage_orphaned_pipelines` | Stdlib scan of failed (optionally cancelled) pipeline states whose report stage completed and nonempty report/forecast exist; default prints candidates. Apply marks completed/100%, records salvage/ensemble-skipped health notes and refuses a reread state that became running. It does not rerun research or simulation. | `scripts/salvage_orphaned_pipelines.py:76`; `scripts/salvage_orphaned_pipelines.py:104`; `scripts/salvage_orphaned_pipelines.py:175` |
| `architecture_baseline` | Stdlib capture/verify/compare. Capture inventories regular files, quarantines pattern-matched secrets, copies clean bytes and emits `baseline-manifest/v1` with hashes/lifecycle/size fields. Pre/post path-size-mtime inventory mismatch yields exit 3; invalid invocation 2; verify/compare differences 1. Optional timestamp only with `FOGLAMP_FAKE_NOW`. | `backend/scripts/architecture_baseline.py:89`; `backend/scripts/architecture_baseline.py:196`; `backend/scripts/architecture_baseline.py:236` |
| `process_diagnostics` | Uses `ps` to produce recursive `{pid,cmdline,children,pythonFaultStacks}`. Ordinary mode does not signal. Explicit `--signal` sends SIGUSR1 and describes cooperative faulthandler stderr output; it does not collect those stacks into JSON. | `backend/scripts/process_diagnostics.py:29`; `backend/scripts/process_diagnostics.py:64` |

These programs expose different side effects. “Export” can rebuild a graph in non-strict mode; “dry-run monitor” still reads the network; `SimulationJobService.results()` can regenerate summary files. This report treats those as source behaviors rather than assuming CLI names imply a universal read-only boundary.

### Forecast scoring and provider comparison

`forecast_tools.py` loads forecast files and delegates ensemble aggregation, or loads a list of `{forecast,outcome}` and delegates calibration/per-forecast scoring. It does not produce the underlying seed runs (`backend/scripts/forecast_tools.py:36`, `backend/scripts/forecast_tools.py:49`).

`eval_forecast_quality.py` is an opt-in rubric judge: groundedness, coverage, calibration, contradiction and citation density, clamped 0–5; default three passes and tolerance 0.5. Objective citation/forecast-shape signals accompany report text (truncated above 48,000 characters). Failed judge passes become zero-valued samples. The live CLI requires `EVAL_ENABLED` or `--live`; disabled commands return 0 without scoring. `run` skips missing report scenarios, gates present baseline dimensions, optionally writes JSON, and can update committed baseline means. Missing baseline returns `passed=None`; it is not a successful quality measurement (`backend/scripts/eval_forecast_quality.py:49`, `backend/scripts/eval_forecast_quality.py:111`, `backend/scripts/eval_forecast_quality.py:231`, `backend/scripts/eval_forecast_quality.py:266`, `backend/scripts/eval_forecast_quality.py:333`).

`golden_eval.py` is deterministic outcome scoring against a golden set: exact ID matching, probability validity checks, binary Brier/log score, resolution accuracy, ECE bins and category/difficulty breakdowns. It returns unmatched/invalid IDs; no matched forecasts yields exit 3, otherwise exit 0 without an absolute quality baseline. Optional `GOLDEN_EVAL_LEDGER` or `--to-ledger` delegates matched truth rows to `append_golden_result`, whose intended evaluation-only ledger routing is described at this boundary. `score-ledger` explicitly requests evaluation-inclusive calibration. It never launches the pipeline or establishes the input forecasts' as-of discipline itself (`backend/scripts/golden_eval.py:71`, `backend/scripts/golden_eval.py:207`, `backend/scripts/golden_eval.py:247`, `backend/scripts/golden_eval.py:356`, `backend/scripts/golden_eval.py:414`, `backend/scripts/golden_eval.py:445`).

`model_comparison.py` reuses a base pipeline's graph/simulation/dossier, builds a per-provider LLMClient and ReportAgent, generates a fresh `cmp__<base>__<provider>__<random>` report, extracts a provider forecast and optionally self-critiques. It records a separate telemetry context per provider, writes its forecast, resets context/meter afterward and executes providers sequentially. Base loading checks graph/simulation IDs and prompt, not a separately verified completed-run status. `compare_models()` itself is callable; the CLI is gated by `MODEL_COMPARISON_ENABLED` or `--force` and returns 3 when disabled. The providers command checks local executable/key presence without a live credential probe (`backend/scripts/model_comparison.py:75`, `backend/scripts/model_comparison.py:140`, `backend/scripts/model_comparison.py:187`, `backend/scripts/model_comparison.py:362`, `backend/scripts/model_comparison.py:423`). Comparison output schema 1 includes per-scenario probabilities/spread, agreement, confidence/citation/telemetry by provider, report paths and failed records (`backend/scripts/model_comparison.py:281`).

## 6. `drf2`: alternative driver, storage and engines

### Driver and persistence

`DriverState` uses stages research/ontology/graph/prepare/run/report; `StageRecord` carries status, message/error, health/issues, timestamps, attempts, reused flag and artifact paths. Legal stage transitions are pending→running, running→completed/failed, failed→running, completed→running. `StateStore` persists schema-1 `<base>/<id>/state.json` and identifies sibling `manifest.json`/artifacts directory, refuses newer schema and has an empty migration chain. Default CLI base is `.drf2/pipelines` (`drf2/driver/state.py:24`, `drf2/driver/state.py:56`, `drf2/driver/state.py:79`, `drf2/driver/state.py:188`; `drf2/driver/cli.py:28`).

`ArtifactManifest` entries are `{path,sha256,bytes,stage,recorded_at,schema_ok}`. JSON probe accepts dict/list; other files must be nonempty. `verify_stage()` checks registered size/hash/existence/current probe and includes stage-specific entries beyond default specs. No manifest entries means verification passes; unregistered outputs are skipped. This is a compatibility fallback, not proof that every required output was revalidated. The per-entry `schema_ok` is recorded metadata; verification probes current bytes directly (`drf2/driver/manifest.py:42`, `drf2/driver/manifest.py:73`, `drf2/driver/manifest.py:103`).

`PipelineDriver` owns sequencing, not the agentic tasks. The five harness stages activate `/deep-research`, `/ontology-generation`, `/kg-construction`, `/simulation-design`, `/forecast-report` with precise output filenames under `/mnt/user-data/outputs`. Required artifacts are research_report.md; ontology.json; kg_build_summary.json; simulation_config.json; run_summary.json; full_report.md + forecast.json. Research optional outputs include actor dossier, actors/sources/timeline/meta; prepare optionally includes agent_profiles (`drf2/driver/pipeline.py:36`, `drf2/driver/pipeline.py:45`, `drf2/driver/pipeline.py:72`).

`run()` creates state; `resume()` immediately returns an already-completed pipeline, otherwise re-enters the loop. Completed stages in that loop are reused on manifest verification; mismatches rebuild that stage without automatically invalidating all downstream stages. Execution exceptions mark running stages/pipeline failed and persist. Harness stages first require declared files, then gate and register them (`drf2/driver/pipeline.py:105`, `drf2/driver/pipeline.py:167`, `drf2/driver/pipeline.py:212`).

Research gate hard-fails missing/short reports and applies optional dossier/quality warnings. Report deliverable gate hard-fails missing/tiny full report, missing/empty required structured forecast or all placeholder sections; partial placeholders degrade. Binary conviction uses existing `_binary_quality` and degrades rather than hard-fails. Hollow/truncated/error simulation gate also degrades (`drf2/driver/gates.py:74`, `drf2/driver/gates.py:112`, `drf2/driver/gates.py:161`, `drf2/driver/gates.py:189`). Ontology/graph/prepare have presence checks but their `_stage_gate()` returns pass; initial registration records probe status without failing based on it (`drf2/driver/pipeline.py:147`).

### External harness and simulation transports

`RunsApiHarness` uses one persistent thread: POST `/api/threads`, POST `/api/threads/<id>/runs` with user message, `on_disconnect=continue`, `multitask_strategy=reject`, then GET the run resource until success/error/timeout/interrupted. Driver-side timeout attempts POST cancel. The client resolves output files at `<workspace>/users/<uid>/threads/<tid>/user-data/outputs/<relative>`. HTTP uses urllib JSON with optional bearer header, finite request timeout and wrapped errors; no retry loop is implemented for individual HTTP request errors (`drf2/driver/harness_client.py:56`). Embedded-client transport is mentioned as future work in source, not implemented here.

RUN calls a `SimEngine` interface, not a harness run. `HttpSimEngine` expects POST `/simulations` with `{config,seed?}`, GET `/simulations/<id>` with top-level progress/completed/error, and POST stop. `poll_simulation()` returns terminal/error status, stops on no round advance for `stall_s`, and stops on total timeout. `_sim_once()` reads base simulation config and writes returned or disk-located run summary into harness outputs before assessing hollow health (`drf2/driver/harness_client.py:187`, `drf2/driver/harness_client.py:265`; `drf2/driver/pipeline.py:234`).

The inspected simulation implementation instead exposes **stdio MCP** `sim_start(config_path|sim_id, sim_seed, ...)`, `sim_status` with nested `progress`/`health`, `sim_results`, `sim_stop`, and `sim_interview_agents`. No `/simulations` HTTP server is defined in these owned engine files. Thus the HTTP driver's expected service contract and the MCP engine surface are distinct; this study did not observe a deployed adapter connecting them (`drf2/engines/simulation/server.py:43`, `drf2/engines/simulation/server.py:60`, `drf2/engines/simulation/jobs.py:267`).

### Multi-seed and dry run

With seeds, driver starts run/report together, performs simulation then report per `seed-<n>/`, and aggregates successful forecasts to `ensemble_forecast.json`. All failed seeds fail the pipeline; partial failure degrades run/report. The seed-report path checks deliverables but does not call the normal report path's binary conviction gate. Manifest includes available seed report/run files (`drf2/driver/pipeline.py:276`).

`fan_out()` is sequential, captures each seed's success/error and pools successful dict forecasts. `aggregate_ensemble()` reuses legacy normalized-name, mean/stdev, log-odds and agreement math. Point probabilities are arithmetic or explicit-factor extremized log-odds, normalized across scenarios; output includes spread/support/drivers/criteria, pooling label and schema 1 (`drf2/driver/ensemble.py:28`, `drf2/driver/ensemble.py:103`).

CLI supports run/resume/status; config reads only optional `driver:` section. `--dry-run` injects `DryRunHarness`, fixture stage writers and `DrySimEngine`; dry mode still writes local state/artifacts and exercises sequencing/gates, while performing no provider/gateway call. It is fixture evidence, not a forecast. Main CLI requires a harness base URL for non-dry mode. The inspected shared config's final section is persistence, with no `driver:` section found in the whole-file key search (`drf2/driver/cli.py:31`, `drf2/driver/cli.py:80`, `drf2/driver/cli.py:120`, `drf2/driver/cli.py:159`; `drf2/config/config.yaml:430`).

### KG MCP engine

`build_server()` registers eight reflected tools with FastMCP; stdio transport starts only in `main()`. KG tool services load lazily into locked singleton caches on first call. Explicit graph ID wins over process default; missing required inputs return readable parameter text; operational exceptions become `KG engine error [...]` strings (`drf2/engines/kg/server.py:52`, `drf2/engines/kg/server.py:135`; `drf2/engines/kg/tools.py:27`, `drf2/engines/kg/tools.py:60`).

| Tool | Concrete delegated behavior | Anchor |
|---|---|---|
| `kg_add_episode` | Parses optional loose reference time; `GraphitiRuntime.add_episode`, then best-effort invalidates search/nodes/edges caches. | `drf2/engines/kg/tools.py:152` |
| `kg_search` | `ZepToolsService.as_of_search`, scope normalization and limit clamp; returns `.to_text()`. | `drf2/engines/kg/tools.py:191` |
| `kg_get_entities` | All nodes or entity-type filter, bounded text with UUIDs. | `drf2/engines/kg/tools.py:223` |
| `kg_get_edges` | All graph or one node's edges, optional temporal fields, bounded text. | `drf2/engines/kg/tools.py:246` |
| `kg_causal_paths` | Resolve entity names, runtime directed paths; when pure-causal search is empty, relax to general relation paths with explicit note. | `drf2/engines/kg/tools.py:276` |
| `kg_n_hop_subgraph` | Resolved center, bounded runtime neighborhood and JSON edge list. | `drf2/engines/kg/tools.py:326` |
| `kg_trace_cascade` | Direct passthrough to legacy trace-cascade reasoning view. | `drf2/engines/kg/tools.py:364` |
| `kg_centrality_priors` | `GraphBuilderService._get_graph_info().to_dict()`; no separate centrality implementation. | `drf2/engines/kg/tools.py:389` |

### Simulation MCP engine

`SimulationJobService.resolve()` reuses an already prepared simulation directory or validates and copies an external config into a fresh `drf2sim_*` directory. `start()` delegates to existing `SimulationRunner.start_simulation`; `stop()` delegates to runner termination. Main runner artifacts and checkpoints remain the persistence boundary (`drf2/engines/simulation/jobs.py:118`, `drf2/engines/simulation/jobs.py:159`, `drf2/engines/simulation/jobs.py:192`).

`status()` joins durable runner state, process identity/liveness and environment status. Health includes crashed, stale_heartbeat (default 180 seconds, `DRF2_SIM_HEARTBEAT_STALE_S` override), completed_with_errors, completed/failed/stopped. `interview_ready` requires alive environment and process. `results()` reads run/dynamics summaries, returns partial while nonterminal, and can call `write_run_summary()` when a terminal summary is absent. `interview()` rejects a nonalive environment or confirmed dead process, can mark stale environment stopped, and delegates single/batch/all-agent interview with bounded minimum timeout (`drf2/engines/simulation/jobs.py:203`, `drf2/engines/simulation/jobs.py:312`, `drf2/engines/simulation/jobs.py:364`).

The MCP server wraps blocking work in `asyncio.to_thread`, logs to stderr and catches errors into `{success:false,error:"Type: message"}` payloads (`drf2/engines/simulation/server.py:38`, `drf2/engines/simulation/server.py:55`). “No LLM call” in the job-service module means it does not directly create one; starting an OASIS process or interviewing agents can invoke LLM work through the delegated runner.

## 7. Tests: topology, actual excerpts and behavior index

### Test boundaries

Backend pytest discovers `tests/`, not `backend/scripts/test_*.py`, by project declaration (`backend/pyproject.toml:83`). Selected `conftest.py` reads show the early `DRF_TEST_PROCESS=1` marker, scripted FakeLLMClient, automatic prediction-market disabling, removal of ambient Firecrawl/research selection variables, temporary log-handler quarantine and telemetry active-run isolation (`backend/tests/conftest.py:13`, `backend/tests/conftest.py:56`, `backend/tests/conftest.py:127`, `backend/tests/conftest.py:187`). Config skips ambient dotenv under that marker (`backend/app/config.py:14`). These fixtures are isolation mechanisms, not evidence that every possible import/subprocess/network path is blocked.

The assigned script checks characterize different execution types:

- `test_deerflow_deep_research.py`: bridge/deployed byte parity, skill/loop overlay parity, marker stripping and fake multi-pass invocation sequence; requires installed runtime files for some checks (`backend/scripts/test_deerflow_deep_research.py:31`, `backend/scripts/test_deerflow_deep_research.py:121`).
- `test_pipeline_resume.py`: temp pipeline store and fake blocked `_run`; failed/cancelled states, resume reset/race, orphan cancel/delete guards, handoff floor and stale action-log rotation (`backend/scripts/test_pipeline_resume.py:69`, `backend/scripts/test_pipeline_resume.py:130`, `backend/scripts/test_pipeline_resume.py:265`).
- `test_profile_format.py`: constructs profiles without a generator initializer and writes/reads Twitter CSV and Reddit JSON; missing-field branches print diagnostics rather than assert failure (`backend/scripts/test_profile_format.py:64`, `backend/scripts/test_profile_format.py:88`).
- `test_zep_rate_limit.py`: fake sleep/fetch, Retry-After parser and graph-snapshot reuse (`backend/scripts/test_zep_rate_limit.py:21`, `backend/scripts/test_zep_rate_limit.py:57`).
- `test_graphiti_migration.py`: creates a graph, sets ontology, ingests with configured LLM/local embedding, reads/searches and asserts nonempty nodes/edges; it is an integration program with writes/provider dependency (`backend/scripts/test_graphiti_migration.py:68`).
- `test_graphiti_services.py`: exercises real graph builder/entity reader/retrieval/memory updater against the local graph and includes ingestion/insight work. “No Zep key” does not mean no LLM or no mutation (`backend/scripts/test_graphiti_services.py:51`).

### Representative backend test bodies actually reviewed

The ranges below are partial reads only. Assertions describe tests at the frozen commit; **none were executed**.

| File and exact reviewed ranges | Characterized behavior |
|---|---|
| `backend/tests/test_llm_fallback_model.py:44` (44–71), `:147` (147–176) | Missing fallback model constructs/calls nothing; tripped primary plus unavailable fallback makes no primary calls and performs no backoff sleeps. |
| `backend/tests/test_audit_fixes_infra.py:218` (218–251), `:358` (358–449) | Native-tools exact usage, no outer fallback double-metering, fallback's own model/reasoning/endpoint survives primary tier configuration. |
| `backend/tests/test_telemetry_fallback_attribution.py:59` (59–132) | Untagged thread's sole-run accounting/budget enforcement; multiple-active-run usage stays global and outside each run's budget. |
| `backend/tests/test_prediction_markets.py:120` (120–161), `:475` (475–526) | Two-attempt transient vs single-attempt nontransient transport; jitter hook; reversed outcome and CLOB Yes selection. |
| `backend/tests/test_drf2_driver.py:528` (528–579) | Resume reuses verified stages, and same-size research tamper rebuilds research while ontology remains reused. |
| `backend/tests/test_drf2_simulation.py:137` (137–162) | External config copy, runner command/cwd/process-session shape and child-only seed using fake Popen. |
| `backend/tests/test_export_demo_site_data.py:592` (592–657) | Strict graph 404 refuses reconstruction and leaves no graph/meta result. |
| `backend/tests/test_backfill_report_visuals.py:323` (323–378) | Forced publish failure restores original Markdown/meta/chart bundle and records rollback receipt. |
| `backend/tests/test_resolution_monitor.py:275` (275–337) | Synthetic monitor writes and idempotent ledger resolution; dry run writes nothing; market outage degrades while manual-resolution logic continues. |
| `backend/tests/test_golden_eval.py:196` (196–226) | Synthetic forecast/golden files produce JSON/Markdown metrics with ledger opt-in off. |
| `backend/tests/test_env_drift_pins.py:153` (153–170) | Secret-name values are masked; token-count setting remains visible. |
| `backend/tests/conftest.py:1` (1–91), `:110` (110–206) | Test marker/fakes, ambient setting suppression, log quarantine and registry cleanup. |

### Complete top-level test-module navigation index

The following index covers all **179 top-level `backend/tests/test_*.py` modules** found in the frozen tree. It was produced by static AST extraction of module docstrings and declared `test_*` function names, not a full semantic read. The number is declared test functions, not pytest collected/parameterized cases or passed tests. Descriptions are module-declared intent; cross-area names are retained as written. `backend/tests/eval/` additionally holds rubric/scenario/baseline/golden data used by the scoring scripts. The table is navigation evidence; substantive assertions above are limited to the stated excerpts.

#### Alternative drf2 driver, engines and skill configuration

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_drf2_driver.py:1` | Offline tests for the DRF-2 Pipeline Driver (drf2/driver/*). | 60 |
| `backend/tests/test_drf2_kg.py:1` | DRF-2 KG 引擎 MCP 服务器测试（离线：mock zep_tools/graphiti 层，不触真图谱/LLM/网络）。 | 20 |
| `backend/tests/test_drf2_simulation.py:1` | drf2/engines/simulation 的离线测试：job 生命周期、文件契约、健康检测、采访桥。 | 21 |
| `backend/tests/test_drf2_skills_config.py:1` | DRF-2 scaffold offline tests: skills / config / extensions / market tool. | 36 |

#### Graph, actor and ontology contracts

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_actor_cast_discipline.py:1` | ACTOR-CAST DISCIPLINE — 主角色阵容纪律（≤ ACTOR_CAST_MAX 个 main actors）。 | 36 |
| `backend/tests/test_actor_context_runtime.py:1` | Offline end-to-end checks for research-grounded actor context at OASIS. | 27 |
| `backend/tests/test_actor_dossier_compactor.py:1` | No module docstring; use declared test names. | 5 |
| `backend/tests/test_actor_dossier_judge.py:1` | NEXTSTEPS P3-1: actor-dossier AI-judge pure helpers (offline). | 6 |
| `backend/tests/test_actor_intelligence_producer.py:1` | Producer-side actor-intelligence/v1 regressions (offline and deterministic). | 42 |
| `backend/tests/test_actor_role_prompt.py:1` | Offline contract tests for DeerFlow actor roles consumed by OASIS. | 30 |
| `backend/tests/test_audit_fixes_graph.py:1` | Audit fixes（graph 组）回归测试：KG-3/KG-5/KG-7/KG-8/KG-11/ONT-7/XRUN-6。 | 19 |
| `backend/tests/test_audit_fixes_ontology.py:1` | Audit fixes — ontology group (ONT-1/3/5/6/9/11 + PREP-5). | 22 |
| `backend/tests/test_cast_reconcile.py:1` | NEXTSTEPS P3-2: cross-track cast reconciliation (pure function). | 4 |
| `backend/tests/test_dossier_coverage.py:1` | NEXTSTEPS P3-4: dossier coverage gate (pure function). | 3 |
| `backend/tests/test_faction_brief.py:1` | Offline tests for faction-aware GraphRAG (EXECPLAN2 I-1-2). | 15 |
| `backend/tests/test_forecast_extractor.py:1` | Golden tests for structured forecast extraction + citation audit (EXECPLAN2 I-3-0/I-3-1). | 62 |
| `backend/tests/test_graph_actor_v1_seed.py:1` | Strict actor-intelligence/v1 graph seed boundary regressions. | 18 |
| `backend/tests/test_graph_cost_containment.py:1` | Graph-stage cost containment regression tests (W10-COST). | 22 |
| `backend/tests/test_graph_optimizations.py:1` | Tests for the graph-bucket optimizations (wedge root-cause + KG quality). | 16 |
| `backend/tests/test_graph_research_boundary.py:1` | Graph ingestion must treat Stage-1 prose as evidence, never instructions. | 2 |
| `backend/tests/test_ontology_actors_optimizations.py:1` | Offline, deterministic tests for the ontology-actors optimization bucket. | 20 |
| `backend/tests/test_ontology_refinements.py:1` | Offline golden tests for the ONTOLOGY refinements in app.utils.actors. | 29 |
| `backend/tests/test_pipeline_actor_contract.py:1` | Parent-side actor-intelligence reception and cast-seal regressions. | 37 |
| `backend/tests/test_projected_edges.py:1` | NEXTSTEPS P3-8: relationship-trajectory projection (offline, pure). | 3 |
| `backend/tests/test_prompt_injection_boundaries.py:1` | Adversarial prompt-boundary checks for ontology and simulation preparation. | 5 |
| `backend/tests/test_wave9_kg.py:1` | Wave9-KG 单测：分页去重/终止、剪枝 keep-set 规划、GC 保留规划、UI 子图 top-K。 | 38 |
| `backend/tests/test_zep_entity_resolver.py:1` | Offline unit tests for entity resolution / canonical-alias merge (EXECPLAN2 I-1-4). | 28 |

#### Operations, infrastructure, utility and runtime boundaries

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_architecture_baseline_cli.py:1` | Offline tests for the Foglamp WP0A baseline CLI (scripts/architecture_baseline.py). | 6 |
| `backend/tests/test_architecture_characterization.py:1` | Foglamp WP0 (slice 0B) — architecture characterization suite. | 25 |
| `backend/tests/test_auth_gate_forwarded.py:1` | Auth gate vs. proxied requests (EXECPLAN2 F-13-0 hardening). | 8 |
| `backend/tests/test_config_optimization_defaults.py:1` | Regression guard for the optimization-pass config defaults. | 2 |
| `backend/tests/test_env_drift_pins.py:1` | Offline unit tests for the ENV-1 pin-divergence audit + the preserved | 18 |
| `backend/tests/test_llm_fallback_model.py:1` | TASK 2/3 (audit): fallback model-name inheritance + dual-outage fail-fast. | 6 |
| `backend/tests/test_logger.py:1` | Regression checks for application logging lifecycle behavior. | 1 |
| `backend/tests/test_runtime_lifecycle_isolation.py:1` | Regression coverage for process-lifecycle isolation. | 3 |
| `backend/tests/test_settings_endpoint_fallback.py:1` | Settings test/save keep the configured endpoint when re-used for the current provider. | 4 |
| `backend/tests/test_settings_provider_info.py:1` | /api/settings provider list carries each provider's deep-research model. | 3 |
| `backend/tests/test_spa_serving.py:1` | SPA static serving (TASK 1): the Flask backend serves the built frontend. | 7 |
| `backend/tests/test_start_script_progress.py:1` | No module docstring; use declared test names. | 9 |
| `backend/tests/test_telemetry.py:1` | Golden tests for LLM telemetry / cache / budget (EXECPLAN2 I-7-3, guards I-5-0/I-6-0/I-5-3). | 18 |
| `backend/tests/test_telemetry_fallback_attribution.py:1` | FOG-TEL-1: single-active-run fallback attribution for unattributed LLM metering. | 8 |
| `backend/tests/test_token_budget.py:1` | RQ-7 / I-6-4 — token_budget 纯函数预算工具的离线单元测试（无 LLM/网络）。 | 14 |
| `backend/tests/test_utils_atomic.py:1` | Golden tests for atomic file writes (EXECPLAN2 I-7-3, guards F-0-4/F-7-6). | 8 |
| `backend/tests/test_utils_dates.py:1` | Golden tests for lenient date parsing (EXECPLAN2 I-7-3). | 5 |
| `backend/tests/test_utils_file_parser.py:1` | Tests for file_parser.split_text_into_chunks defaults (CHUNK-1). | 5 |
| `backend/tests/test_utils_security.py:1` | Golden tests for the security helpers (EXECPLAN2 I-7-3, guards F-13-1/F-8-1/F-13-2). | 8 |

#### Outcome evaluation, ledger, rerun drift and ensemble

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_calibration_rigor.py:1` | Calibration-rigor tests for the forecast bucket (R2-CAL-* / REPORT-6 / EVAL-1). | 29 |
| `backend/tests/test_ensemble_backtest.py:1` | Golden tests for ensemble aggregation + backtest scoring (EXECPLAN2 I-9-0/I-9-2/I-3-5). | 6 |
| `backend/tests/test_eval_forecast_quality.py:1` | Offline unit tests for the forecast-quality eval harness (EXECPLAN2 I-7-7). | 15 |
| `backend/tests/test_forecast_diff.py:1` | Tech-debt fix: scheduled_rerun.forecast_diff was written offline-testable but had | 5 |
| `backend/tests/test_forecast_ledger.py:1` | NEXTSTEPS P2-4: forecast ledger (append / read / calibration / due) — offline. | 9 |
| `backend/tests/test_golden_eval.py:1` | Offline unit tests for the golden-question forecast-quality harness (EVAL-1). | 18 |
| `backend/tests/test_resolution_autorun.py:1` | i8 回归：MON-1 判定监测的进程内调度（LOOP-017「resolution monitor never ran」）。 | 6 |
| `backend/tests/test_resolution_monitor.py:1` | MON-1 解析追踪 / 持续预测监测的离线测试。 | 13 |
| `backend/tests/test_seed_ensemble.py:1` | NEXTSTEPS P0-3: seed-ensemble pure helpers (offline). | 2 |

#### Prediction-market research and influence boundaries

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_bridge_market_tools.py:1` | Offline regression tests for the DeerFlow prediction-market tool delivery lane. | 13 |
| `backend/tests/test_bridge_prediction_markets.py:1` | deerflow_bridge/deerflow_research.py 纯 helper 的离线单测（PM-1 / INT-2 / RQ-6）。 | 74 |
| `backend/tests/test_market_influence_boundary.py:1` | LOOP-017 P0：市场影响边界（market influence boundary）——离线红线测试。 | 18 |
| `backend/tests/test_prediction_markets.py:1` | 预测市场集成（Polymarket 公开 Gamma API，keyless）的离线测试。 | 48 |

#### Reporting, publication, bilingual export and visualization

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_agent_dynamics.py:1` | Offline unit tests for per-agent affective-state dynamics (EXECPLAN2 I-2-1). | 9 |
| `backend/tests/test_agent_log_publication_gate.py:1` | /api/report/<id>/agent-log must not leak drafts of reports that failed the gate. | 4 |
| `backend/tests/test_audit_fixes_infra.py:1` | ORCHESTRATOR + LLM INFRA 审计修复的针对性测试（R2 wave-2 infra group）。 | 32 |
| `backend/tests/test_audit_fixes_prepare.py:1` | Audit fixes — prepare group (PREP-1/2/4/8/9/10/11, XRUN-10/13). | 21 |
| `backend/tests/test_audit_fixes_report.py:1` | Offline tests for the report-area audit fixes (findings_report.json). | 28 |
| `backend/tests/test_backfill_report_visuals.py:1` | No module docstring; use declared test names. | 13 |
| `backend/tests/test_chart_serve_inline.py:1` | Serve-time plotly inlining for sandboxed chart HTML (utils/chart_html). | 8 |
| `backend/tests/test_dossier_edit_continue.py:1` | Dossier edits must never be silently discarded by Continue (T5.4). | 5 |
| `backend/tests/test_exec_brief.py:1` | DELIV-1 执行交付物（exec brief + digest）的离线测试。 | 20 |
| `backend/tests/test_export_demo_site_data.py:1` | No module docstring; use declared test names. | 28 |
| `backend/tests/test_final_publish_audit.py:1` | Focused regressions for the post-citation, read-only report publish audit. | 16 |
| `backend/tests/test_foglamp_containment.py:1` | Foglamp WP1 — Immediate correctness containment (EXECPLAN_FOGLAMP §9). | 19 |
| `backend/tests/test_forecast_visuals_manifest.py:1` | Focused lifecycle checks for the bundled research-chart manifest renderer. | 34 |
| `backend/tests/test_loop006_static_viz_fallbacks.py:1` | LOOP-006: static timeline/network fallbacks for report visualizations. | 10 |
| `backend/tests/test_mcp_servers.py:1` | app.mcp.{kg_server,sim_server} MCP 服务器测试（ITEM 4）。 | 32 |
| `backend/tests/test_oasis_v1_provenance.py:1` | Fail-closed OASIS persona boundary for actor-intelligence/v1. | 8 |
| `backend/tests/test_orchestrator_outage_halt.py:1` | DEFECT-1：run 级提供方中断熔断（LLM_OUTAGE_HALT_CONSECUTIVE）的离线红测。 | 13 |
| `backend/tests/test_publish_gate.py:1` | NEXTSTEPS P2-3: forecast publish-gate (coherence + grounding) tests. | 7 |
| `backend/tests/test_reclaim_report_space.py:1` | scripts/reclaim_report_space.py 的安全闸回归（owner 签核的 1.57GB 回收工具）。 | 6 |
| `backend/tests/test_report_bilingual.py:1` | Offline tests for BILINGUAL auto-translation (english⇄chinese report versions). | 38 |
| `backend/tests/test_report_chart_quality.py:1` | Chart-quality forensic-audit fixes (three gaps, red-first). | 26 |
| `backend/tests/test_report_concurrent_sections.py:1` | Offline tests for concurrent report section generation (EXECPLAN2 I-6-3). | 6 |
| `backend/tests/test_report_draft_exposure.py:1` | Draft-exposure regressions for reports that are not publishable. | 15 |
| `backend/tests/test_report_forecast_localization.py:1` | Translated report views: fresh retries, forecast language, localized dashboard. | 8 |
| `backend/tests/test_report_lint_citations.py:1` | report_lint citation safety: lint never deletes or invents [S#] markers. | 23 |
| `backend/tests/test_report_market_crosscheck.py:1` | PM-2 / PM-3 / VIZ-2 报告半侧的离线测试。 | 24 |
| `backend/tests/test_report_market_evidence.py:1` | 市场证据集回归 — 「真实市场价被当作 fabrication」事故的两条在库机制（LOOP-017 P0 尾巴）。 | 6 |
| `backend/tests/test_report_publication_barrier.py:1` | End-to-end API regressions for the report publication barrier. | 10 |
| `backend/tests/test_report_repair_and_reflection.py:1` | Offline tests for RQ-2 report repair passes + RQ-5 per-section reflection. | 44 |
| `backend/tests/test_report_section_concurrency_parity.py:1` | COST-2: report-section concurrency default + serial/concurrent parity. | 3 |
| `backend/tests/test_report_sections_partial.py:1` | ITEM-17 backend: GET /<report_id>/sections-partial 渐进式发布契约 + ITEM-16 图表 HTML 服务。 | 6 |
| `backend/tests/test_report_spine_and_turns.py:1` | Offline tests for the report bucket spine/turn-budget changes. | 18 |
| `backend/tests/test_report_visualizer.py:1` | VIZ-1: deterministic report visualizer — Mermaid renderers, matplotlib PNG family, | 51 |
| `backend/tests/test_report_visualizer_axes.py:1` | TASK 4 (audit): metric-trajectory x-axis ordering + shared plotly bundle. | 4 |
| `backend/tests/test_report_viz_and_pdf.py:1` | VIZ-1 钩子 + PDF-1 导出的离线测试（无 pandoc / 无网络依赖）。 | 26 |
| `backend/tests/test_report_viz_manifest_api.py:1` | LOOP-004: report visualization manifest producer/API contract. | 7 |
| `backend/tests/test_report_zh_presentation.py:1` | Chinese report variants: chart titles and PDF labels read in Chinese. | 5 |
| `backend/tests/test_sdk_publication_barrier.py:1` | SDK forecasts and calibration must obey the exact publication barrier. | 2 |
| `backend/tests/test_sessionb_downstream_gates.py:1` | SESSIONB 下游硬门审计回归：终审可否决缺陷必须在稳定化环节有对应的确定性修复。 | 8 |
| `backend/tests/test_sessionb_forecast_charts.py:1` | SESSION-B：预测「数据」图回归（DRF2 定量 schema 新字段驱动）—— | 16 |
| `backend/tests/test_sessionb_forecast_provenance.py:1` | SESSION-B 黄金测试：① 编造溯源修复（source 只可指向确实注入过提示词的模拟信号块）； | 10 |
| `backend/tests/test_sessionb_json_extract.py:1` | 结构化抽取 JSON 解析稳健性单测（Session B）。 | 16 |
| `backend/tests/test_sessionb_judge_normalization.py:1` | SESSION-B：judge 记分牌确定性归一（_normalize_judge_scorecard）回归测试。 | 20 |
| `backend/tests/test_sessionb_report_prompts.py:1` | SESSION-B（LOOP-015）离线测试：report_agent 提示词去重 + 条件工具下限 + 大纲收敛 + 分层护栏。 | 15 |
| `backend/tests/test_sessionb_scenario_parser.py:1` | forecast_inputs_from_report_markdown 多情景节稳健性（Session B）。 | 6 |
| `backend/tests/test_sessionb_skill_hygiene.py:1` | Session-B 技能瘦身 + 市场停查规则的卫生守卫。 | 7 |
| `backend/tests/test_sessionb_translation_reallm.py:1` | SESSION-B: REAL-LLM (MiniMax) Mandarin translation must pass the variant audit. | 5 |
| `backend/tests/test_sessionb_translation_structure.py:1` | SESSION-B: structure-preserving bilingual translation + research-report path + shared PDF. | 9 |
| `backend/tests/test_sessionb_viz_signal.py:1` | SESSION-B：报告图表信号密度回归—— | 11 |
| `backend/tests/test_smoke_realrun_residue.py:1` | SMOKE 实跑回归：report_a03be154febc 真实成稿上发现的泄漏残留类别。 | 8 |
| `backend/tests/test_status_live_block.py:1` | OBS-1/I-5-6 落地回归：/api/research/status/<id> 的计算型 ``live`` 块。 | 5 |
| `backend/tests/test_three_part_and_fetch_retry.py:1` | B2（三部结构骨架 + 需求书 binary_min_count 生效）与 R2（死抓取程序化重试）的离线测试。 | 11 |
| `backend/tests/test_translation_dates.py:1` | Dates in report translation (English ⇄ Chinese) — regression for report_d79a064bf5cc. | 14 |
| `backend/tests/test_translation_quantities.py:1` | Amounts in report translation: "$3.7 billion" must become "37亿美元", not "3.7亿美元". | 10 |
| `backend/tests/test_translation_robustness.py:1` | Translation robustness: residual tolerance, last-resort line repair, orphaned jobs. | 13 |
| `backend/tests/test_viz_manifest_provenance.py:1` | i9 回归：viz_manifest.json 的溯源块（LOOP-017「manifests lack policy/input hashes」）。 | 4 |
| `backend/tests/test_wave9_citations.py:1` | WAVE10 无缝引用（seamless citations）离线测试——单一语法 / 最终化 / 修复 / 对账 / PDF。 | 29 |
| `backend/tests/test_wave9_orchestrator.py:1` | Wave 9（编排器组）：孤儿打捞、集成语义对齐、多轨卷宗整理、遥测增量落盘、轨存活判定。 | 22 |
| `backend/tests/test_wave9_report_focus.py:1` | WAVE9 report-focus tests: 报告主语是现实世界，模拟只是内部方法。 | 42 |
| `backend/tests/test_wave9_report_integration.py:1` | W9-8 报告集成回归：昂贵研究产物直通 ReportAgent 的证据块与注入行为。 | 18 |
| `backend/tests/test_wave9_visualizer.py:1` | WAVE9：plotly-first 报告可视化重建 —— 新构建器族（二元点阵/时间线泳道/角色网络/气泡/ | 27 |

#### Research engine, evidence, budgets and runtime overlays

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_audit_fixes_research.py:1` | Audit-fix regression tests for the deerflow_bridge research stage (group: research). | 41 |
| `backend/tests/test_bridge_extensions_config.py:1` | deerflow_bridge/extensions_config.json is a template rendered at deploy time. | 11 |
| `backend/tests/test_bridge_overhaul_v3.py:1` | Deep-research engine v3 — bridge (deerflow_research.py) overhaul regressions. | 45 |
| `backend/tests/test_bridge_search_and_cache.py:1` | deerflow_bridge 的 search_tools（ITEM 6 后端调度）+ cached_fetch（ITEM 10 源缓存）离线单测。 | 21 |
| `backend/tests/test_claude_prompt_cache.py:1` | Offline unit tests for research-stage prompt caching (token lever 1). | 13 |
| `backend/tests/test_deerflow_bridge_sync_guard.py:1` | Offline unit tests for the DeerFlow bridge/deployment drift guard. | 16 |
| `backend/tests/test_live_research_progress.py:1` | Focused regression coverage for LOOP-008 live research observability. | 20 |
| `backend/tests/test_loop007_research_budget.py:1` | Offline regression tests for the LOOP-007 cross-process research budget. | 39 |
| `backend/tests/test_loop010_global_synthesis.py:1` | Offline contracts for parallel evidence lanes -> one global synthesis. | 24 |
| `backend/tests/test_loop010_research_contracts.py:1` | LOOP-010 prompt, skill, and summarization contract regressions. | 14 |
| `backend/tests/test_multipart_synthesis.py:1` | SCALE-1 multi-part synthesis — unit tests for the pure helpers. | 81 |
| `backend/tests/test_orchestrator_research_wiring.py:1` | Offline unit tests for orchestrator research-stage wiring. | 79 |
| `backend/tests/test_parallel_research_merge.py:1` | Offline unit tests for PAR-2 parallel-research-track merge helpers. | 29 |
| `backend/tests/test_research_checkpoint.py:1` | ITEM-3 研究断点续跑 + ITEM-14 --extract-only 只抽取打捞 的离线单测。 | 30 |
| `backend/tests/test_research_contract_finalization.py:1` | Regression tests for the postprocessed research contract boundary. | 11 |
| `backend/tests/test_research_dossier_translation.py:1` | Research-dossier translation: section order, funding rounds, integrity retries. | 7 |
| `backend/tests/test_research_engine_v3.py:1` | Offline tests for the deep-research engine v3 (deerflow_bridge/linear_research.py). | 38 |
| `backend/tests/test_research_engine_v3_hardening.py:1` | Robustness regressions of the deep-research engine v3 (review findings). | 11 |
| `backend/tests/test_research_engine_v3_residuals.py:1` | Residual fixes after review round 3 of the deep-research engine v3. | 20 |
| `backend/tests/test_research_engine_v3_round2.py:1` | Review round 2 regressions of the deep-research engine v3 (engine stage, E1-E11). | 33 |
| `backend/tests/test_research_engine_v3_round3_loop.py:1` | Review round 3 regressions of the deep-research engine v3: the KIQ agent loop | 26 |
| `backend/tests/test_research_engine_v3_round3_robust.py:1` | Review round 3 regressions of the deep-research engine v3: robustness, | 28 |
| `backend/tests/test_research_engine_v3_round3_synth.py:1` | Review round 3 regressions of the deep-research engine v3: synthesis, QA and | 40 |
| `backend/tests/test_research_engine_v3_text.py:1` | Text/accuracy regressions of the deep-research engine v3 (review findings). | 14 |
| `backend/tests/test_research_evidence_quality.py:1` | Offline unit tests for the deerflow-bridge evidence-quality analytics. | 21 |
| `backend/tests/test_research_fanout.py:1` | Offline unit tests for deep-research fan-out (EXECPLAN2 I-0-4). | 7 |
| `backend/tests/test_research_fork_handoff.py:1` | Fork 情景共享 handoff 目录的 API 解析回归（LOOP-017 缺陷 3）。 | 10 |
| `backend/tests/test_research_gateway.py:1` | Offline tests for deerflow_bridge/research_gateway.py (deep-research engine v3). | 156 |
| `backend/tests/test_research_round3_parent.py:1` | Round-3 parent regressions: research lint on bridge-finalized reports. | 4 |
| `backend/tests/test_research_spend_flush.py:1` | DEFECT-2：失败/超时/取消的研究 attempt 的 token 花费不再丢账。 | 13 |
| `backend/tests/test_runtime_skill_sync.py:1` | Regression tests for authoritative runtime skill bundle deployment. | 7 |
| `backend/tests/test_sessionb_firecrawl.py:1` | Firecrawl provider（web_fetch 主抓 + web_search 后端）离线单测。 | 15 |
| `backend/tests/test_sessionb_firecrawl_guardrails.py:1` | Firecrawl 花费护栏（Session B）离线单测。 | 16 |
| `backend/tests/test_sessionb_research_viz.py:1` | SESSION-B: research-report quant enrichment + trajectory rendering + diagnostic gating. | 14 |
| `backend/tests/test_stage1_model_boundaries.py:1` | Stage-1 prompt-boundary, actor-judge, and global actor-coverage regressions. | 17 |
| `backend/tests/test_wave9_research_quality.py:1` | WAVE9 research-quality — unit tests for the pure helpers in the deerflow bridge. | 26 |
| `backend/tests/test_wave9_research_speed.py:1` | WAVE9（research 提速）离线单测：缺口集收敛 / Retry-After 封顶 / 搜索缓存 / 增量补丁 / 退化环熔断。 | 30 |

#### Simulation, calendar, state and runner behavior

| Module anchor | Declared behavior / intent | Functions |
|---|---|---:|
| `backend/tests/test_audit_fixes_runloop.py:1` | Audit fixes — runloop group (RUN-1..RUN-14, XRUN-14). | 28 |
| `backend/tests/test_audit_fixes_runner.py:1` | Audit fixes — runner group (RUN-7/11/12/13/15/16/17, XRUN-2/4/9, RUN-18). | 57 |
| `backend/tests/test_calendar_event_bucketing.py:1` | Calendar event bucketing — TEMPORAL spec §7 item 3. | 10 |
| `backend/tests/test_calendar_round_loop.py:1` | CAL-TEMPORAL spec §7 item 6 — 日历轮循环的端到端离线测试（stubbed env，零 LLM）。 | 7 |
| `backend/tests/test_decision_channel.py:1` | NEXTSTEPS P1-1 integration: decision-channel orchestration (offline, fake LLM). | 10 |
| `backend/tests/test_sessionb_sim_additivity.py:1` | SESSION-B 黄金测试：让多智能体**模拟真正贡献 forecast**的端到端接线。 | 10 |
| `backend/tests/test_sim_config_incentives.py:1` | R2-SIM-3: actor incentives → AgentActivityConfig (offline, no LLM/oasis). | 5 |
| `backend/tests/test_sim_config_v1_provenance.py:1` | Fail-closed actor-intelligence/v1 boundaries in simulation configuration. | 9 |
| `backend/tests/test_sim_context_persona.py:1` | NEXTSTEPS — 模拟上下文注入（SIM_WORLD_BRIEF）+ 逐角色人格设计（SIM_PERSONA_DESIGN）。 | 27 |
| `backend/tests/test_sim_market_priors.py:1` | ITEM 11 — 市场先验注入（SIM_MARKET_PRIORS）。 | 16 |
| `backend/tests/test_sim_meter_persistence.py:1` | DEFECT-3：模拟子进程的 token 计量落盘 + 编排器恰好一次入账。 | 19 |
| `backend/tests/test_sim_reaction_phase.py:1` | SIM-REACT：每轮发帖后的回应阶段 + 模拟输出语言。 | 19 |
| `backend/tests/test_sim_realism_item20.py:1` | ITEM 20 — 模拟真实感四件套的离线测试。 | 24 |
| `backend/tests/test_sim_resume_reuse.py:1` | DEFECT-1/DEFECT-2：resume 不再重跑已完成的模拟；hollow rc=0 运行按阶段失败处理。 | 22 |
| `backend/tests/test_sim_timeline.py:1` | sim_timeline 纯函数测试（temporal_sim_spec §2 / §7-1）。 | 35 |
| `backend/tests/test_simulation_config_seal.py:1` | Tamper regressions for the PREPARE -> runner -> child config seal. | 10 |
| `backend/tests/test_simulation_runner_throttle.py:1` | SIM-13: throttle run_state.json disk writes while keeping the in-memory state fresh. | 3 |
| `backend/tests/test_simulation_trajectory_api.py:1` | GET /api/simulation/<id>/trajectory — 决策通道轨迹端点契约。 | 10 |
| `backend/tests/test_temporal_mode_contract.py:1` | CAL-TEMPORAL spec §7 item 2 — 跨模块契约测试套件（presence-keyed 分派）。 | 15 |
| `backend/tests/test_world_delta.py:1` | Tests for the qualitative world-delta digest (spec §4 / §7 item 5). | 9 |
| `backend/tests/test_worldstate.py:1` | NEXTSTEPS P1-1: pure WorldState outcome-model tests (offline, no LLM/oasis). | 14 |
| `backend/tests/test_worldstate_calendar.py:1` | 日历改造（temporal spec §4/§7-4）：WorldState 熵地板 + 决策通道日历轨迹（offline，fake LLM）。 | 10 |


## 8. Workflow packaging authority

The lead's [workflow-shortlist.md](workflow-shortlist.md) is authoritative for the repeated-workflow assessment, packaging decisions and extension of the existing codebase-research skill. This operations report covers frozen-main source behavior and reading coverage.

## 9. Verification limits and remaining uncertainties

Closeout validation on 2026-10-12 used the restored exact-commit mirror and the existing read history. The coverage array contains exactly the 44 assigned paths; all SHA-256 values match the frozen inventory, and inclusive ranges cover all 14,995 owned lines without gaps. All 495 distinct numeric source anchors in this report are within their files. The test index contains 179 module rows with no unresolved index marker. These were static artifact checks; no application import, test, provider call or pipeline launch occurred.

- **Verified source completeness:** 44/44 assigned files fully read, all hashes bound to the requested Git commit, coverage ranges checked against frozen line counts. Supplemental tests/callers are explicitly partial or index-only.
- **Active versus alternative:** Flask/orchestrator and production resolution-autorun wiring are confirmed in frozen source. Scheduler daemon and `drf2` require separate invocation/configuration. No live deployment or pipeline state was observed.
- **Behavior versus comments:** main Config enables cache/tier/HTTP2 by default despite older off-default commentary; batch forks leave ontology pending; native-tools payload and retry behavior differ from ordinary chat; preview HTTP and MCP simulation contracts differ. These are documented implementation distinctions, not requested changes.
- **Usage precision:** successful `chat()` usage is recorded; failed attempts do not automatically become separate meter records. CLI estimates, synthetic subprocess entries, provider-level price tables and ambiguous global attribution prevent treating counters as a complete request/billing ledger. Current source proves accounting paths, not historical amounts or provider invoices.
- **Test evidence:** 179 modules were indexed; representative bodies were read. No passing-suite, performance, live credential, embedding-cache, CI-resolution, PDF-render or end-to-end forecast claim is made.
- **Preview integration:** no HTTP adapter for `HttpSimEngine` was found in the owned simulation server files; shared config has no driver section in its key index. External deployment adapters/configuration are unobserved.

Continuation context: another reader can reproduce the assigned-source boundary from `study-contract.json`, this report's repo-relative anchors and `operations-coverage.json`, then consult the relevant other owner report for full orchestrator, research, graph, simulation or reporting internals. No application work remains in this operations study's authorized scope.
