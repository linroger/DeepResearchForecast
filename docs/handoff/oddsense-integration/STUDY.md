# Oddsense: source study and integration decisions

**Date:** 2026-10-18, Asia/Singapore. **Status:** source study; implementation not started.

## Authority and reading scope

The supplied [Oddsense repository](https://github.com/jayeshvpatil/oddsense) is pinned to `a625a81ff84091c12148b9fb5c84893466aea282` (package version `0.2.1`). Its 36 tracked files include 29 Rust files totaling 4,051 lines. All 29 Rust files, including inline test definitions, were read. The [inventory](upstream-inventory.json) records hashes, line ranges, supporting-document coverage and exclusions. `Cargo.lock` was hashed, not substantively reviewed; only lines 1–70 of the 868-line vendor `CLAUDE.md` count as inspected. There are no separate tracked test directories. No vendor code, build, tests, imports or dependency installation was executed.

The destination authority is the current working tree on `claude-reflexive-world-state-model`, initially `dcff7684f255be358232fdcf989af30cbc032c43`, including pre-existing modifications. Historical main-branch studies supplied navigation only. [Research paths](research-paths.md) and [downstream paths](downstream-paths.md) record current-source anchors and reading limits. The [checkout baseline](checkout-baseline.json) identifies work outside this task's ownership.

## Workflow placement

The active application uses `PipelineOrchestrator`, durable `pipeline_state.json` and research handoff artifacts. Current `pipeline_orchestrator.py:6361–6425` resolves fresh runs to v3, accepts `linear` as its alias and selects legacy when a pinned actor-intelligence policy requires the sealed actor plane. The parent's research subprocess configuration at `:2417–2447` supplies prediction-market controls and a per-track artifact directory. New tools must reach both supported research engines and their deployed bare-import copies.

Oddsense belongs at the research evidence boundary. Its outputs should enter the same citation, cutoff, persistence and report paths as other evidence. Creating an unrelated CLI output file would not fulfill the requested integration. Likewise, automatic probability revision, simulation world facts and outcome resolution require stronger evidence than topic sentiment or a similar market title.

## Upstream mechanisms and limitations

All upstream anchors below resolve to the pinned revision's repository-relative source paths.

| Mechanism | Source evidence | Integration decision |
|---|---|---|
| News discovery and enrichment | `src/sentiment/news.rs:33–112`; stores title, publisher, publication time, URL and English lexicon score | Add NewsAPI discovery through a DRF-owned bounded client. Preserve article-level evidence and distinguish snippets from fetched article bodies. |
| Reddit topic signals | `src/sentiment/reddit.rs:32–108`; public JSON search, newest posts in one-week window | Add an optional social-context source with explicit provider status and item identity. Access is not proven by source inspection. Social opinion is not independent factual confirmation. |
| Cross-platform discovery | `src/cli/search.rs:25–163`; `src/adapters/kalshi.rs:108–160` | Extend the existing market search owner with source-aware records; keep Polymarket's existing native implementation. Kalshi's one-page 200-event filter is limited recall, not exhaustive search. |
| Community forecasts | `src/adapters/metaculus.rs:56–108` | Keep community forecasts distinct from traded prices. Missing prediction becomes `0.0` upstream; forecaster count is stored as `volume_total`; 403 becomes empty success. These semantics must not be copied. |
| Sentiment summary | `src/sentiment/scorer.rs:1–85`; `src/sentiment/mod.rs:103–163` | English keyword tone is useful only as a labeled heuristic. Empty/unavailable sources must not become neutral evidence. Count-based "confidence" is coverage, not calibrated accuracy. No Chinese sentiment claim follows from Chinese article discovery. |
| Market/sentiment divergence | `src/analysis/divergence.rs:29–83` | Reject its use as a forecast probability or mispricing measure: `(score + 1) / 2` has no demonstrated event calibration or event-direction mapping. Present underlying news and market evidence for review instead. |
| Cross-platform comparison | `src/analysis/arbitrage.rs:58–178` | Adapt candidate discovery and a comparison view. Title similarity alone cannot establish matching event, horizon, threshold, resolution source or outcome polarity. A price spread is not executable arbitrage. |
| Query expansion/category rules | `src/search/mod.rs:8–222`; `src/search/categories.rs:50–155` | Reuse the mechanism only where existing DRF query generation leaves a concrete gap. Keep language/context-aware expansion bounded; do not transplant a competing broad research router. |
| Smart LLM mode | `src/llm/provider.rs:23–179`; `src/cli/search.rs:61–133,175–242` | Use existing DRF LLM routing, accounting and budgets if needed. Upstream supports Anthropic only; `provider_name` is ignored and expanded queries are computed but are not used for additional adapter searches. No second provider credential or paid model path is necessary. |
| CLI transport/configuration | `src/main.rs:15–112`; `src/config.rs:51–72`; `src/adapters/polymarket.rs:27–57,183–190` | Do not make the raw CLI the canonical evidence boundary. It requires a second Polymarket binary; subprocess and HTTP operations lack explicit task deadlines/output caps in inspected code. The JSON contract lacks the provenance and availability distinctions DRF needs. |

Additional fidelity problems constrain reuse. Polymarket takes the first outcome price as Yes and falls back to zero (`src/adapters/polymarket.rs:100–112`), while numeric IDs become an empty string (`:66–70`). Most normalized rows discard provider payloads (`source_data: null`). The schema lacks capture timestamps and settlement rules (`src/adapters/schema.rs:9–25`). Divergence deduplication can discard distinct candidates and thresholds by shared event URL or title template (`src/cli/divergence.rs:108–218`). `signals --timeframe` ignores its timeframe (`src/cli/signals.rs:8–32`). Source exceptions often disappear into an empty result or stderr, including in quiet JSON mode. These are static findings, not executed bug reproductions.

## Current provider documentation checks

NewsAPI supports `X-Api-Key`, which avoids embedding credentials in request URLs. Its Everything endpoint supports explicit `from`/`to` timestamps, language, bounded pages, publisher identity, article URLs and publication timestamps. Its `content` field is truncated to 200 characters; discovery snippets cannot be treated as a fetched full article. The published Developer plan has a 24-hour delay, a one-month search window and 100 requests per day. The supplied key's actual plan and validity were not checked. Sources: [authentication](https://newsapi.org/docs/authentication), [Everything](https://newsapi.org/docs/endpoints/everything), [pricing and plan limits](https://newsapi.org/pricing), checked 2026-10-18.

Current [Kalshi Get Market documentation](https://docs.kalshi.com/api-reference/market/get-market) shows a singular `market` response object, `yes_bid_dollars`/`yes_ask_dollars`/`last_price_dollars` and fixed-point contract-volume fields. Oddsense expects a `markets` list for that endpoint and legacy cent-valued fields (`src/adapters/kalshi.rs:30–50,63–68,205–232`). A direct transplant risks failed decoding or fabricated zero prices. Provider compatibility must be verified against current documented responses; no live provider success is claimed here. The Metaculus documentation page was reachable but exposed no readable text, so current endpoint/authentication compatibility remains unresolved.

## License and reuse

Oddsense's `Cargo.toml` declares MIT and its license names Copyright (c) 2026 Jayesh Patil. Independently authored Python adaptation is the preferred fit for DRF's existing owners and contracts. Preserve the upstream revision and attribution in an integration notice; retain the MIT notice with any substantial copied source or expressive assets. The repository license does not establish provider-data or article-content rights. Vendor agent files were studied as data and were not installed as instructions.

## Per-file source notes

Each Rust file below has full text coverage and a hash in the inventory. These notes describe source roles and material boundaries; they do not claim runtime verification.

| File | Role and material behavior |
|---|---|
| `src/adapters/mod.rs` | Async search/list/get interface plus an availability probe; it has no status/provenance carrier. |
| `src/adapters/schema.rs` | Unified market and response schema; parses expiration relative to the current clock and lacks capture/rules metadata. |
| `src/adapters/polymarket.rs` | CLI composition, normalization and inline tests; assumes first price is Yes, loses numeric IDs and substitutes zero. |
| `src/adapters/kalshi.rs` | Direct event search/list and detail calls with inline normalization tests; limited recall and current schema mismatch described above. |
| `src/adapters/metaculus.rs` | Old question API client and inline tests; conflates forecaster count with volume and missing prediction with zero. |
| `src/analysis/mod.rs` | Exposes arbitrage and divergence modules. |
| `src/analysis/arbitrage.rs` | Greedy fuzzy-title groups and price spread sorting, with inline tests; lacks settlement-equivalence and executable-price checks. |
| `src/analysis/divergence.rs` | Tone-to-probability transformation and confidence-weighted absolute difference, with inline tests; no empirical calibration. |
| `src/cli/mod.rs` | Command/flag definitions; output defaults to table, market sources to all, and limits lack an application-wide resource contract. |
| `src/cli/search.rs` | Concurrent provider discovery, category filtering and optional reranking; provider failures can become success with empty markets. |
| `src/cli/enrich.rs` | Loads a NewsAPI key from config and calls aggregate sentiment. |
| `src/cli/divergence.rs` | Polymarket-only sentiment comparison with URL/template/fuzzy deduplication that can collapse distinct outcomes. |
| `src/cli/signals.rs` | Polymarket volume ranking; accepted timeframe is unused. |
| `src/cli/compare.rs` | Parallel discovery and fuzzy/query filtering into side-by-side rows; errors are dropped and the final limit is global. |
| `src/cli/arbitrage.rs` | Parallel source discovery feeding title groups; failures are stderr-only and no transaction is executed. |
| `src/config.rs` | TOML config with optional provider keys/defaults/model fields; NewsAPI has no direct env lookup here. |
| `src/lib.rs` | Library module exports; LLM and CLI modules are not exported. |
| `src/main.rs` | Clap dispatch, async command calls and top-level error exit; no workflow persistence or monitor. |
| `src/llm/mod.rs` | Expansion and reranking structs. |
| `src/llm/provider.rs` | Anthropic expansion/reranking with config/environment key lookup; other declared provider names do not change routing. |
| `src/output/mod.rs` | JSON/table dispatch; quiet table mode produces no output. |
| `src/output/json.rs` | Serializes selected response to stdout without adding provenance metadata. |
| `src/output/table.rs` | Human table formatting; turns forecaster-count proxy into dollar-looking volume through the shared formatter. |
| `src/search/mod.rs` | English domain synonym expansion and overlap/fuzzy relevance with inline false-positive controls. |
| `src/search/categories.rs` | Ordered keyword classification with inline category tests; inferred categories are heuristic. |
| `src/sentiment/mod.rs` | Signal/result schemas, market-keyword reweighting, news/Reddit aggregation; empty sources collapse to score zero. |
| `src/sentiment/news.rs` | English NewsAPI snippets, URL query authentication and item scoring; no explicit historical window or task timeout. |
| `src/sentiment/reddit.rs` | Recent public JSON posts with title/selftext scoring and permalink construction; no proven API availability. |
| `src/sentiment/scorer.rs` | English positive/negative lexicon with a two-token negation window and title weighting; inline unit definitions test the heuristic only. |

## Stopping condition

The study supports the proposed integration slices in [PLANS.md](PLANS.md). It does not establish live source access, useful forecast improvement, CLI runtime compatibility, completed wiring, publication or deployment. Those require the plan's separate implementation and acceptance evidence.
