"""INFRA-13 (N04): the egress import-fence policy that test_import_fences.py enforces.

Data only. Every model and network call must go through a transport that meters it (LLMClient's
usage ledger and run budget, the research gateway ledger, cached_fetch's source cache and spend
ceilings, the sim's usage accumulator). An import that reaches one of the CAPABILITIES below is
legitimate only where an ALLOW row names its file and capability and states why the module needs
direct access (``reason``) and what meters or bounds the calls it makes (``ledger``).

Adding a row is the review gate for a new egress site: name the narrowest ``scopes`` (the def or
class qualname the import sits in; a pinned def also covers the closures nested in it, and
MODULE_SCOPE is the top level) and ``symbols`` (dotted names the import may bring in) that fit.
Rows without a pin admit the capability anywhere in the file, which is reserved for the transports
themselves. test_no_stale_allow_rows fails on a row that no longer matches an import.
"""

MODULE_SCOPE = "<module>"

# Repo-relative directories walked for .py files. Directories named in EXCLUDED_DIR_NAMES, or
# starting with an EXCLUDED_DIR_PREFIXES entry (dot-dirs such as deerflow_bridge/.cache, and the
# gitignored deer-flow checkout), are skipped at any depth.
SCAN_ROOTS = ("backend/app", "backend/scripts", "deerflow_bridge", "drf2")
EXCLUDED_DIR_NAMES = frozenset({"tests", "__pycache__", "node_modules"})
EXCLUDED_DIR_PREFIXES = (".", "deer-flow")

# Capability -> dotted module prefixes. ``openai`` covers ``openai.types.chat``; ``from a import b``
# is checked as ``a.b``, so ``from deerflow import models`` and ``from deerflow.models import
# create_chat_model`` both reach llm_factory. data_vendor fences the whole ``deerflow.community``
# package (jina_ai, and the serper/tavily/ddg_search tools search_tools loads dynamically).
CAPABILITIES = {
    "llm_sdk": (
        "openai",
        "anthropic",
        "langchain_openai",
        "langchain_anthropic",
        "camel.models",
        "graphiti_core.llm_client",
        "graphiti_core.embedder",
        "graphiti_core.cross_encoder",
    ),
    "llm_factory": ("deerflow.client", "deerflow.models"),
    "http_client": ("httpx", "requests", "urllib.request", "aiohttp"),
    "data_vendor": ("exa_py", "deerflow.community", "firecrawl"),
}

# Imported names that carry a capability whichever module they are imported from (a re-export or
# a relative import of DeerFlow's model factory).
FENCED_SYMBOLS = {"create_chat_model": "llm_factory"}

# Names of module tables whose string values are importlib targets resolved at runtime; each value
# is scanned like a literal ``importlib.import_module`` argument.
DYNAMIC_IMPORT_TABLES = frozenset({"_PROVIDER_MODULES"})

# Subscription-billed provider CLIs: a list/tuple literal holding one of these adjacent string
# pairs spawns a model call that only LLMClient meters.
CLI_ARGV_RULE = {
    "pairs": (("claude", "-p"), ("codex", "exec")),
    "allowed_files": ("backend/app/utils/llm_client.py",),
}

_LLMCLIENT_LEDGER = "none of its own: the calls run through app.utils.llm_client.LLMClient"
_V3_LEDGER = ("research_gateway.ModelGateway: per-call usage ledger, run budget units and the "
              "research bridge lease")
_TOOL_FREE_LEDGER = ("_invoke_tool_free_model + _log_model_response_usage write each call's token "
                     "usage to the research progress log, which feeds the research telemetry")
_SEARCH_LEDGER = ("research_budget admission (admit_attempt) before every search, the short-TTL "
                  "search cache and the per-process provider event counters")

ALLOW = (
    # --- the LLMClient transport and its sim adapter -------------------------------------------
    {
        "file": "backend/app/utils/llm_client.py",
        "capability": "llm_sdk",
        "reason": "LLMClient is the OpenAI-compatible transport itself (client construction and "
                  "the retryable openai error classes).",
        "ledger": "LLMMeter.record per call, LLMCache, check_budget (BudgetExceeded)",
    },
    {
        "file": "backend/app/utils/llm_client.py",
        "capability": "http_client",
        "reason": "LLMClient builds the tuned HTTP/2 httpx client the openai SDK sends through "
                  "(LLM_HTTP2).",
        "ledger": "LLMMeter.record per call, check_budget (BudgetExceeded)",
    },
    {
        "file": "backend/app/utils/oasis_llm.py",
        "capability": "llm_sdk",
        "reason": "The OASIS/camel model adapter: builds camel OpenAIModel backends (openai "
                  "provider path, Kimi user-agent client swap) and fakes ChatCompletion objects "
                  "for the CLI bridge.",
        "ledger": "run_parallel_simulation's _SIM_LLM_USAGE accumulator (persisted in the sim "
                  "telemetry snapshot); the single-platform twitter/reddit runners are "
                  "unmetered; the CLI bridge and the direct-path fallback go through LLMClient",
    },
    # --- graphiti client adapters (local models or LLMClient-backed) ---------------------------
    {
        "file": "backend/app/services/graphiti_client/llm_adapter.py",
        "capability": "llm_sdk",
        "reason": "Graphiti's LLMClient base class, config and error types, plus the openai "
                  "transient error classes normalised to Graphiti's RateLimitError; the adapter "
                  "itself calls the app LLMClient.",
        "ledger": _LLMCLIENT_LEDGER,
        "symbols": (
            "graphiti_core.llm_client.client",
            "graphiti_core.llm_client.config",
            "graphiti_core.llm_client.errors",
            "openai.APIConnectionError",
            "openai.APITimeoutError",
            "openai.InternalServerError",
            "openai.RateLimitError",
        ),
    },
    {
        "file": "backend/app/services/graphiti_client/embedder.py",
        "capability": "llm_sdk",
        "reason": "Base class for the local sentence-transformers embedder that replaces "
                  "Graphiti's default OpenAI embedder.",
        "ledger": "no remote call: embeddings are computed locally",
        "symbols": ("graphiti_core.embedder.client.EmbedderClient",),
    },
    {
        "file": "backend/app/services/graphiti_client/cross_encoder.py",
        "capability": "llm_sdk",
        "reason": "Base class for the no-op reranker that replaces Graphiti's default OpenAI "
                  "reranker.",
        "ledger": "no remote call: passthrough scores",
        "symbols": ("graphiti_core.cross_encoder.client.CrossEncoderClient",),
    },
    {
        "file": "backend/app/services/graphiti_client/runtime.py",
        "capability": "llm_sdk",
        "reason": "GRAPHITI_RERANKER=bge selects Graphiti's local BGE cross-encoder.",
        "ledger": "no remote call: the BGE model runs locally",
        "scopes": ("GraphitiRuntime._get_clients",),
        "symbols": ("graphiti_core.cross_encoder.bge_reranker_client.BGERerankerClient",),
    },
    # --- connectivity probes -------------------------------------------------------------------
    {
        "file": "backend/app/api/settings.py",
        "capability": "llm_sdk",
        "reason": "The settings 'test connection' probe: one chat completion capped at 16 output "
                  "tokens against the key and base URL the user is about to save (SSRF-guarded).",
        "ledger": "unmetered by design: user-initiated, outside any run, max_tokens=16",
        "scopes": ("_test_openai_compat_provider",),
        "symbols": ("openai.OpenAI",),
    },
    {
        "file": "backend/scripts/preflight.py",
        "capability": "llm_sdk",
        "reason": "Operator preflight live probe of an OpenAI-compatible provider (SSRF-guarded "
                  "base URL).",
        "ledger": "unmetered by design: operator CLI run outside any pipeline run",
        "scopes": ("_live_openai_compat",),
        "symbols": ("openai.OpenAI",),
    },
    # --- keyless market data and notifications ---------------------------------------------------
    {
        "file": "backend/app/utils/prediction_markets.py",
        "capability": "http_client",
        "reason": "PolymarketClient: keyless Gamma/CLOB reads for the market calibration anchor.",
        "ledger": "keyless (no billing); PREDICTION_MARKETS_ENABLED gate, bounded timeouts and "
                  "retries, degrade-safe empty results",
    },
    {
        "file": "deerflow_bridge/market_tools.py",
        "capability": "http_client",
        "reason": "The research agents' prediction_market_search tool: keyless Polymarket GET.",
        "ledger": "keyless (no billing); query cache and the prediction-market ledger file; one "
                  "retry, never raises",
        "scopes": ("_http_get",),
    },
    {
        "file": "drf2/config/market_tools.py",
        "capability": "http_client",
        "reason": "The drf2 harness copy of the prediction_market_search tool: keyless "
                  "Polymarket GET.",
        "ledger": "keyless (no billing); one retry, never raises",
        "scopes": ("_http_get",),
    },
    {
        "file": "deerflow_bridge/deerflow_research.py",
        "capability": "http_client",
        "reason": "Keyless stdlib Polymarket Gamma/CLOB GET for the research child's market "
                  "stage.",
        "ledger": "keyless (no billing); PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS bound and at "
                  "most five attempts",
        "scopes": ("_polymarket_get",),
    },
    {
        "file": "backend/scripts/scheduled_rerun.py",
        "capability": "http_client",
        "reason": "Optional drift-alert webhook POST (URL checked by validate_safe_url).",
        "ledger": "no model or vendor spend: one POST per drift alert, failures only warn",
    },
    {
        "file": "backend/scripts/export_demo_site_data.py",
        "capability": "http_client",
        "reason": "Demo-site exporter: with --graph-api it reads a graph from a running local "
                  "backend's /api/graph/data endpoint instead of opening the embedded graph "
                  "store that process owns.",
        "ledger": "no model or vendor spend: one read-only request per exported graph",
        "scopes": ("export_graph",),
    },
    {
        "file": "drf2/driver/harness_client.py",
        "capability": "http_client",
        "reason": "The drf2 driver's Runs API client for the local DeerFlow harness gateway "
                  "(run submission and status polling).",
        "ledger": "no model spend of its own: the harness meters the model calls of each run",
    },
    # --- official-data vendors -----------------------------------------------------------------
    {
        "file": "deerflow_bridge/data_tools.py",
        "capability": "http_client",
        "reason": "TIME-10/TIME-11 official-data vendor tools: the default transport's GET of the "
                  "FRED/ALFRED API (vintage-pinned macro series) and of SEC EDGAR (the ticker map and "
                  "XBRL companyfacts, statements as filed).",
        "ledger": "not metered: official-data vendor HTTP bounded by DATA_TOOL_TIMEOUT_S and "
                  "per-process throttles (FRED 0.5 s, SEC 0.2 s); ok fetches cached "
                  "(DATA_TOOLS_CACHE_DIR); no LLM egress",
        "scopes": ("_httpx_transport",),
        "symbols": ("httpx",),
    },
    # --- research fetch and search transports ----------------------------------------------------
    {
        "file": "deerflow_bridge/cached_fetch.py",
        "capability": "http_client",
        "reason": "Direct keyless fetch fallback and the Firecrawl /scrape transport behind "
                  "web_fetch.",
        "ledger": "source cache (RESEARCH_SOURCE_CACHE_DIR), research_budget fetch admission and "
                  "provider circuits, and the Firecrawl per-process /scrape call ceiling",
        "scopes": ("_direct_http_fetch", "_firecrawl_fetch"),
    },
    {
        "file": "deerflow_bridge/cached_fetch.py",
        "capability": "data_vendor",
        "reason": "Exa and DeerFlow's Jina web_fetch as fetch providers behind web_fetch.",
        "ledger": "source cache (RESEARCH_SOURCE_CACHE_DIR), research_budget fetch admission and "
                  "provider circuits",
        "scopes": ("_exa_fetch", "_jina_delegate_fetch"),
    },
    {
        "file": "deerflow_bridge/search_tools.py",
        "capability": "http_client",
        "reason": "Firecrawl /search transport (and its availability probe) behind web_search.",
        "ledger": "the Firecrawl per-process /search call ceiling plus " + _SEARCH_LEDGER,
        "scopes": ("_firecrawl_search", "_firecrawl_search_available"),
    },
    {
        "file": "deerflow_bridge/search_tools.py",
        "capability": "data_vendor",
        "reason": "_PROVIDER_MODULES: the DeerFlow community search tools web_search dispatches "
                  "to (serper, tavily, ddg).",
        "ledger": _SEARCH_LEDGER,
        "scopes": (MODULE_SCOPE,),
        "symbols": (
            "deerflow.community.serper",
            "deerflow.community.tavily",
            "deerflow.community.ddg_search",
        ),
    },
    # --- DeerFlow model factory ----------------------------------------------------------------
    {
        "file": "deerflow_bridge/linear_research.py",
        "capability": "llm_factory",
        "reason": "The v3 engine's single model choke point: every v3 model call goes through "
                  "the gateway this factory builds.",
        "ledger": _V3_LEDGER,
        "scopes": ("_default_gateway_factory",),
        "symbols": ("deerflow.models.create_chat_model",),
    },
    {
        "file": "deerflow_bridge/deerflow_research.py",
        "capability": "llm_factory",
        "reason": "Legacy engine tool-free model calls: the outline/section/judge model builder, "
                  "the dossier judge and the actor-ontology synthesis.",
        "ledger": _TOOL_FREE_LEDGER,
        "scopes": ("_build_tool_free_model", "judge_dossier", "run_actor_ontology_stage"),
        "symbols": ("deerflow.models.create_chat_model",),
    },
    {
        "file": "deerflow_bridge/deerflow_research.py",
        "capability": "llm_factory",
        "reason": "Legacy engine entry point: the Claude/Codex credential preflight and the "
                  "DeerFlowClient research agent.",
        "ledger": "credential loaders make no model call; DeerFlowClient runs are metered by the "
                  "client usage overlay and the stream-end usage line in the progress log",
        "scopes": ("main",),
        "symbols": ("deerflow.models.credential_loader", "deerflow.client.DeerFlowClient"),
    },
    # --- overlays copied into the DeerFlow harness (they are part of its model factory) ---------
    {
        "file": "deerflow_bridge/patches/models/claude_provider.py",
        "capability": "llm_sdk",
        "reason": "Overlay of DeerFlow's Claude chat model (OAuth bearer auth, prompt caching): "
                  "it is the provider adapter.",
        "ledger": "the DeerFlow run that invokes the model (research gateway ledger for v3, "
                  "progress-log usage lines for the legacy engine)",
    },
    {
        "file": "deerflow_bridge/patches/models/claude_provider.py",
        "capability": "llm_factory",
        "reason": "The Claude overlay loads its OAuth credential through DeerFlow's credential "
                  "loader.",
        "ledger": "no model call: credential loading only",
        "scopes": ("ClaudeChatModel.model_post_init",),
        "symbols": ("deerflow.models.credential_loader",),
    },
    {
        "file": "deerflow_bridge/patches/models/patched_minimax.py",
        "capability": "llm_sdk",
        "reason": "Overlay of DeerFlow's MiniMax ChatOpenAI adapter (reasoning_details mapping): "
                  "it is the provider adapter.",
        "ledger": "the DeerFlow run that invokes the model (research gateway ledger for v3, "
                  "progress-log usage lines for the legacy engine)",
    },
    {
        "file": "deerflow_bridge/patches/middlewares/title_middleware.py",
        "capability": "llm_factory",
        "reason": "Overlay of DeerFlow's thread-title middleware, which builds its own title "
                  "model; title generation is disabled in deerflow_bridge/config.yaml "
                  "(title.enabled: false).",
        "ledger": "the DeerFlow run's usage accounting; disabled in DRF's config",
        "symbols": ("deerflow.models.create_chat_model",),
    },
)

# Report-stage modules must import no capability directly: their model calls go through LLMClient.
# This is a direct-import fence only. Transitive egress through an allowlisted transport is out of
# scope: report_agent reaches Polymarket through utils.prediction_markets.PolymarketClient (the
# live fetch fallback when the research handoff has no prediction_markets.json, and the PM-3
# re-quote). A missing file fails the test (a rename must update this).
REPORT_STAGE_MODULES = (
    "backend/app/services/report_agent.py",
    "backend/app/services/forecast_extractor.py",
    "backend/app/services/report_lint.py",
    "backend/app/services/exec_brief.py",
    "backend/app/services/ensemble.py",
    "backend/app/services/forecast_ledger.py",
    "backend/app/services/backtest.py",
)

# Eval and diagnostic modules held to the same rule as they land (EVAL-11 alongside this fence;
# EVAL-12, EVAL-20 and REPORT-13 later); a file that does not exist yet is skipped.
NO_EGRESS_MODULES = (
    "backend/app/services/backbone_sensitivity.py",
    "backend/scripts/golden_probe.py",
    "backend/scripts/value_add_eval.py",
    "backend/app/services/forecast_counter_case.py",
)

# Landing baseline (INFRA-13): .py files scanned and capability hits (one per imported name and
# capability). A broken scanner finds fewer; lower a floor only in the commit that removes the
# files or imports that made it drop.
SCANNER_FLOOR = {"files": 158, "hits": 53}
