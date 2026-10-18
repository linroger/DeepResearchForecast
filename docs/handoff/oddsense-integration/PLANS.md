# Oddsense capabilities in the DeepResearchForecast workflow

**Date:** 2026-10-18, Asia/Singapore.
**Status:** Proposed. Application coding awaits the user's plan approval.
**Evidence:** [source study](STUDY.md), [research seams](research-paths.md), [downstream seams](downstream-paths.md), [upstream hashes/coverage](upstream-inventory.json).

## Objective and recommended approach

Make the useful capabilities studied in Oddsense available to research agents and visible in their resulting research/forecast reports: NewsAPI article discovery, optional Reddit discussion context, and comparisons with additional prediction/forecast platforms. Integrate them into existing DRF evidence owners, rather than operating a separate forecasting CLI beside the pipeline.

Independently adapt the useful mechanisms into Python using the existing HTTP, tool, source-ledger, deployment, budget and report infrastructure. Keep the working Polymarket path. Record Oddsense's MIT attribution and pinned revision. The Rust CLI is not a required runtime dependency: its current normalization loses evidence that DRF needs, and an external wrapper cannot reconstruct missing prices, literal Yes mapping, settlement rules or discarded capture metadata. No provider-specific LLM or second model budget is needed.

## Task brief and invariants

Inputs are the existing forecast question, research cutoff, language, run/track identity, bounded derived queries and configured provider credentials. Outputs are agent-accessible evidence, a versioned run-local snapshot, cited research text and bounded report context with explicit availability. Finish when controlled scenarios show that those exact stored records reach the final consumer and offline compatibility checks pass. Record separate results for live source compatibility; do not infer them from fixtures.

The following invariants bind implementation:

1. Provider failure, missing credentials, access denial, verified emptiness and deadline exhaustion remain distinct. No missing value becomes zero or neutral evidence.
2. Every record retains provider/native identity, evidence type, URL, publication/quote time where known, retrieval time, query/window, method/version and eligibility. Article snippets, fetched bodies, community forecasts, market quotes and social opinions remain distinguishable.
3. News and social tone never become event probabilities, automatic forecast updates, resolved outcomes or simulation facts. Model synthesis may discuss the evidence with citations. English heuristic tone carries its method/language and no calibrated-confidence claim.
4. Cross-platform topic similarity produces a candidate comparison only. Event, entity, horizon, threshold, resolution rules and outcome polarity must match before an equivalence claim. The first delivery keeps newly added providers contextual and excludes them from automatic anchoring/reconciliation/resolution paths.
5. Existing Polymarket fields, literal Yes mapping, refresh/history and safety policies retain their existing owner. Never send a Kalshi/Metaculus ID into Gamma/CLOB or the Polymarket resolver.
6. Credentials stay out of argv, request URLs, serialized state, cache keys, model prompts, tool responses, fixtures and error messages. Use `X-Api-Key` for NewsAPI. The supplied chat credential is not written to a file by this study; runtime configuration uses `NEWSAPI_API_KEY` through the existing secret/environment path.
7. A resumed/continued/forked consumer reads its bound evidence generation; it does not silently adopt fresh data. An explicit new retrieval produces a new capture, with research versus report-time context labeled separately. Historical mode cannot claim point-in-time availability from a publication timestamp alone.
8. New modules do no work at import time. Off switches prevent their calls/writes and preserve existing tool behavior. Source text remains untrusted input to prompts and renderers.

## Ordered implementation slices

### OS-1 — News and social evidence through both research engines

**Before:** Agents use existing web tools and Polymarket search; the supplied NewsAPI source and Oddsense's article/discussion enrichment are unavailable as dedicated evidence tools.

**Change:** Add a small DRF-owned `deerflow_bridge/news_signals.py` provider/normalization/persistence module and `news_tools.py` wrappers. Expose `news_search` for NewsAPI and an independently controlled `social_search` for Reddit discussion context. Register the tools in both v3 and legacy through their existing tool owners; add one bounded topic-level NewsAPI prefetch when configured so a normal run uses the new source, while repeated/parallel identical requests share cached results. The plan specifies independent Python adaptation, not installation/execution of vendor scripts.

NewsAPI defaults: enabled when configured, at most two distinct requests per run/track generation, at most 20 items per request, one page, a 10-second aggregate stage deadline and a shorter per-request timeout. Reuse the existing budget and cancellation mechanisms; do not add a second process-wide budget service. Multi-track orchestration must allocate that request allowance once across lanes. No automatic retry for 401/403/429. Bound response bytes and sanitize errors before any logging.

Reddit is separately configurable and initially disabled unless selected; one bounded query per topic, one recent-result page, explicit forbidden/rate-limited/unavailable status. Preserve native post IDs, canonical links, subreddit and publication time. Access limitations do not fail unrelated research. Do not promise public API access without a compatibility probe.

News queries respect explicit language and publication windows. Preserve publisher identity, deduplicate article URLs and obvious repeated items, disclose provider delay/coverage, and fetch the selected publisher page with existing `web_fetch` before making full-text factual/numeric claims. A snippet result alone does not become a fetched article in the source ledger. If English tone is implemented, keep it a deterministic optional annotation; skip unsupported languages rather than claiming neutral sentiment.

The current v3 gateway accepts only a fixed web/data schema and rejects other names. Implement the new schemas and dispatch explicitly in `research_gateway.py` and `linear_research.py`; construct one stable tool set per run. For legacy, update `config.yaml`, scoped worker allowlists and trusted runtime registration together. Existing installations preserve user YAML, so setup/sync needs a supported registration/migration path rather than assuming a new source YAML stanza is deployed. Extend `SourceLedger` serialization and final `sources.json` projection to retain publication/retrieval/provider metadata; current web projections drop it. All new acquisition, source registration and machine-owned cited sections must finish before QA, citation ordering and evidence sealing. Do not bolt cited news onto the post-QA market finalizer.

**Positive scenario:** A controlled forecast question causes the tool/prefetch to return two dated articles; selected article fetches acquire normal citations; the investigator and final dossier cite those exact sources and retain a snapshot of their query/availability metadata.

**Negative scenarios:** Missing/invalid key, 429, malformed/oversized response, future/unknown publication time, duplicate URL, post-cutoff retrieval, empty result, denied Reddit access, simultaneous identical queries, deadline and disabled mode. A 429 is not "no news"; a failed social source is not neutral opinion.

**Evidence:** Red/green integration checks through actual tool registration and source-ledger paths; immutable snapshot bytes/hashes; v3 and legacy controlled question-to-dossier scenarios. No paid model run is necessary for deterministic acceptance.

**OS-1 release prerequisite:** Implement the core snapshot generation, `_RESEARCH_CONTRACT_FILES`, promotion/fingerprint and stage-reuse registration in this slice, before enabling acquisition in ordinary runs. OS-1 acceptance includes restart/tamper/changed-cutoff cases with zero silent refetch. OS-2 extends that same sealed schema/owner; OS-3 adds final report/UI consumers and their consumed-generation binding. This ordering resolves the independent review's sequencing finding and prevents an interim unprotected evidence artifact.

### OS-2 — Source-aware cross-platform market context

**Prerequisite:** OS-1's shared evidence/status conventions frozen and reviewed.

**Change:** Extend the existing market-tool owner with a narrow `market_compare` discovery path backed by a new small `deerflow_bridge/market_intelligence.py` module. Reuse the existing Polymarket provider and query derivation; add Kalshi discovery/detail normalization against current documented fields. Preserve the existing `prediction_market_search(queries: str)` behavior and canonical `prediction_markets.json` for current Polymarket consumers.

Keep external market/community rows in the new source-aware evidence snapshot until eligible provider-specific downstream contracts are explicitly supported. Kalshi uses its own native ticker, price field/basis, bid/ask, contract-volume units, quote timestamps and settlement rules; never apply the Polymarket USD volume floor to a count of contracts. Missing/nonfinite/out-of-range prices stay unknown. Bound candidate paging, detail calls, bytes, concurrency and elapsed time and report incomplete recall. Resolve current host/field compatibility from official documentation and a separate read-only provider probe.

Metaculus support is part of the compatibility investigation: implement a community-forecast adapter only when current documented schema and configured access are established. Otherwise the same tool reports an explicit unsupported/unavailable provider reason. Forecaster count stays a count, and a continuous forecast or missing median is not interpreted as a binary zero-probability outcome. Do not copy Oddsense's obsolete assumptions to claim working support.

Comparison output groups candidates for the same research topic while retaining each distinct entity, threshold and horizon. Matching prose is insufficient for equivalence. It can show a labeled indicative price difference only when comparable records and bases are established, and cannot call it executable arbitrage. No trading, wallet, order, smart-mode LLM or new monitor is introduced.

**Positive scenario:** Scripted Polymarket and current-schema Kalshi responses appear in one comparison with provider/native identity, price basis, retrieval time and source links. The stored external rows remain context-only throughout report generation.

**Negative scenarios:** Identical titles with different years/thresholds/entities/rules, reversed outcome order, literal No first, same native ID on different platforms, missing price, numeric/string/fixed-point prices, singular market response, partial pages, provider access failures and historical cutoff. Assert no new-provider call reaches Polymarket requote, automatic anchoring or resolution.

**Evidence:** Native-shaped fixtures and tool-to-snapshot integration, explicit compatibility-probe results when available, regression coverage for existing Polymarket behavior.

### OS-3 — Persisted context in reports, UI and operating documentation

**Prerequisites:** OS-1 and OS-2 accepted individually; the source-aware carrier is frozen before downstream edits.

**Change:** Promote and bind the new snapshot through research handoff finalization, multi-track merge, resume/fork paths and report context. Add a bounded `news_market_context` carrier to ordinary pipeline, direct/manual and ensemble/seed report paths using stored captures, not report-time unlabelled refetches. Render a compact evidence/comparison table with source links, times, evidence types and limitations in research and forecast reports; verify it survives normal report API/UI/export and language variants. Use existing table/rendering surfaces and one narrow expandable source-context view only if needed to expose durable structured metadata.

The proposed single snapshot is `news_market_context.json` (schema version 1) under the run handoff. It carries run/track identity, immutable generation ID, cutoff/retrieval window, query identities, per-provider statuses, bounded news/social/external-market rows, source references and hashes of stored evidence. Cache identity includes provider, normalized query, language, publication window/cutoff and method/schema version. Credentials are never an identity input. Stored metadata and source text are bounded and validated before prompt/UI entry. Unknown/provider-unavailable rows cannot masquerade as successful evidence. Keep official quantitative datasets and `official_data` under their current contract.

Extend and verify the core generation registration delivered in OS-1 across final report/UI consumers. Merge by provider-qualified identity plus capture identity, then remap references against the final citation order. Bind report loading to the consumed research generation rather than a mutable handoff directory found only by graph or simulation ID. Existing quote refreshes are not a substitute for that binding. Existing Polymarket research-price/timestamp/status inconsistencies are tracked as separate source-level findings; they are not silently repaired or recharacterized as part of this contextual-source feature.

Update the existing prediction-markets project skill and add only the narrow news/social evidence guidance necessary for the new tools. Include them in all setup/sync/deployment allowlists; do not install the vendor skill or duplicate personal/global skills. Document defaults, availability, NewsAPI plan-dependent delay/history and degradation in both READMEs and `.env.example`. The actual user key's plan is unknown; do not label it real-time or production-capable by assumption.

**Positive scenario:** A fixture question traverses v3/legacy tool → saved source evidence → merged handoff → normal/manual/seed/ensemble report context → publication checks → API/export with the same source identity, capture times and context-only labels. A Chinese query preserves article language and receives bilingual presentation without fabricated Chinese tone scoring.

**Negative scenarios:** Replaced/tampered snapshot, stale generation, altered cutoff/query, duplicated multi-track captures, legacy handoff without the new file, disabled feature and source outage. Old runs keep old semantics and cannot silently acquire new evidence. Validate that no article/social row is seeded as a numeric world fact or resolution anchor.

**Evidence:** Existing guarded offline runner and relevant research/market/report/API/deployment suites; focused UI behavior checks and visual inspection only if UI changes; independent producer-to-consumer review tied to final source hashes. No publication bypass, saved-run mutation or paid-model experiment is part of deterministic acceptance.

## Rollout, ownership and final gates

Before coding, choose an isolated owned branch/worktree after reconciling the current dirty baseline; do not copy unrelated modifications or silently switch the running checkout. Freeze current source seams and carrier fields, then assign disjoint bridge provider/tool and backend report/test ownership. Deliver OS-1, then OS-2, then OS-3 as individually verified changes. Keep this handoff current.

Approval of this plan authorizes implementing these source integrations and bounded read-only compatibility probes using already configured credentials. It does not authorize retaining a chat-exposed key, installing a second model provider, launching paid full pipelines, restarting services, changing existing runs, enabling schedules, trading or deploying. These are scope boundaries, not extra approval requests for ordinary implementation work.

Finish with explicit evidence for tool availability in both engines, actual use in a controlled research scenario, persisted provenance, final report consumers, disabled/failure compatibility, correct provider identity and separation from automatic probability/resolution paths. Run applicable checks only after code changes. Stage only owned files, commit coherent slices and attempt an ordinary non-forced push only with appropriate configured Git authentication; preserve unrelated dirt and record any external publication blocker.
