---
name: deep-research
description: Use for web research, comparisons, explanations that depend on external evidence, and every forecast investigation. Provides the always-on core for KIQ decomposition, source grading, evidence-yield stopping, disconfirmation, forecast inputs, provenance, and phase-aware handoffs. Tradecraft and the final-dossier contract are lazy references.
---

# Deep Research — Core Contract

Produce decision-grade research: real fetched evidence, graded provenance, explicit uncertainty, and forecast-useful structure.

## Activation discipline

When this body is injected, do **not** reread `SKILL.md`. Load only a named lazy reference when the phase needs it.

## Phase type comes first

Identify the current phase from its prompt. The phase contract overrides any final-output rule:

- **Working phases** — opening/source-map notes, scoped worker notes, KIQ top-ups, verification notes, actor passes, correction messages, and fan-out absorption. Return concise evidence-ledger notes and gaps. **They are explicitly exempt from every final word-count, section-count, and polished-dossier floor.** Do not pad or synthesize the final report.
- **Final dossier synthesis only** — the prompt explicitly says to write/synthesize/finalize the complete research dossier. Only this phase uses the long-form output contract in `references/final-dossier-contract.md`.
- **Structured extraction/judging** — follow the requested JSON/scorecard schema, not the prose length contract.

This distinction is mandatory: a dossier floor on every pass multiplies latency and tokens.

## Core loop

1. Decompose the brief into 3–7 Key Intelligence Questions (KIQs). Mark load-bearing KIQs, likely S1/S2 source classes, priors, and what would falsify them.
2. Search for documents, not commentary. Use `web_search`, then `web_fetch` the strongest pages in full. For official statistics use `data_search` → `data_get` if available. For forecast calibration use `prediction_market_search`; if unavailable, use read-only `web_fetch` against the public Gamma API. Run the full market sweep **once, in the opening pass**; if it surfaces zero topically relevant markets, record `no_market_coverage` and skip market search in later phases (one refresh at synthesis only). A transport-failing market tool must not be retried within the same phase.
3. Maintain an evidence ledger: `KIQ → claim → source/title/real URL/date/tier → independence → grade → open gap`.
4. Prefer primary origins, verify numbers/units/as-of dates, trace repeated claims back to their origin, and seek the strongest opposing case.
5. Check convergence after every evidence-bearing call. Continue only for a named unresolved KIQ with a credible next upgrade.
6. Before final synthesis, verify the synthesis gate and load the final-dossier reference.

## News and cross-platform context

When exposed, use `news_search` to discover dated publisher articles and then `web_fetch` selected original URLs before factual or numeric claims. A NewsAPI snippet is discovery, not a fetched page. Keep publisher, URL, language, publication time and retrieval time; repeated outlets may share one origin. The opening prefetch is already captured: reuse its evidence before spending another query.

`social_search`, when enabled, returns attributed discussion and opinion. `market_compare` returns source-aware topic candidates from additional venues. Preserve provider/native identity, quote basis, units, rules and horizon; similar titles do not establish equivalent contracts or executable arbitrage. These records are context only: never convert tone to event probability or participation counts to trading volume, and never treat them as automatic forecast anchors or settlement evidence.

Read availability status before interpreting an empty list: unavailable, forbidden, rate-limited, partial, disabled and verified empty differ. Do not retry a failed provider repeatedly. Once the research generation is sealed, use stored captures and citations; do not acquire replacement evidence on resume. If these tools are absent, continue with the existing web/data tools.

## Evidence discipline

- **S1**: original/authoritative material — official statistics, filings, laws, court records, peer-reviewed papers, transcripts, primary datasets, direct first-party statements. Preferred for load-bearing facts.
- **S2**: accountable high-quality reporting/analysis — major wires/outlets, serious trade press, established research bodies. Context and a pointer to S1.
- **S3**: conditional/biased/derivative — vendor research, expert blogs, preprints, Wikipedia as a map. Corroborate or attribute explicitly.
- **S4**: reject — SEO/affiliate slop, anonymous/undated aggregators, unsupported statistics, synthetic rewrites. Do not fetch or cite.

Only cite sources actually fetched and read. Preserve their true URL and on-page date. Never invent a title, URL, market, quote, or future-dated document. Two outlets repeating one underlying report are one origin, not triangulation.

For each quantitative fact record the metric, value/range, unit, as-of date, definition, geography/population, and source URL. Sanity-check magnitude, currency, nominal/real basis, denominators, totals, and compounding. Quote stored official series exactly with period and `[S<n>]`; projections are not history.

For query operators, document targeting, source maps, grading, number checks, adversarial analysis, and obstacle routing, load:

`references/source-tradecraft.md`

## KIQ and evidence-yield stopping

Tool counts and source counts are safety telemetry, never quotas or quality proxies.

- **KIQ done**: each load-bearing claim is B2-or-better and its strongest plausible opposing case was checked; or accessible S1/S2 paths are exhausted and the remaining gap is explicit.
- **Evidence delta**: a new independent origin, stronger tier, verified number, resolved contradiction, reference-class base rate, watchable indicator, or genuine disconfirmation.
- **Yield stop**: two genuinely different angles produce no evidence delta. Stop that line and record the gap.
- **Continue**: at least one priority KIQ remains unresolved and the next call has a named expected upgrade.
- Never issue a near-duplicate query. Change actor, mechanism, document type, jurisdiction/language, or time window—not punctuation.
- Checkpoint the ledger after every pass; later phases must not re-research settled items.

## Forecast-specific requirements

Research forecasting inputs, not only present-state description:

- outside-view reference classes and base rates (long official history via `data_get` where a series exists);
- named actors, stated versus revealed behavior, incentives, capabilities, constraints, and what each gains/loses;
- directed typed relationships among key actors, each with an evidence basis;
- causal drivers, countervailing forces, catalysts, and second-order effects;
- dated timeline and forecast horizon;
- explicit competing scenarios/hypotheses and disconfirming evidence;
- watchable indicators with thresholds/dates;
- chart-ready tables/series with definitions and provenance;
- prediction-market question, market ID, P(yes), volume/liquidity, end date, URL, and fetch time for relevant liquid markets.

Market prices are calibration anchors, not ground truth; self-filter lexical false positives and explain material divergence rather than copying the price.

## Synthesis gate

Final synthesis may begin only when:

- every priority KIQ is resolved or explicitly flagged;
- load-bearing claims are B2-or-better or visibly labeled weak/single-origin;
- key numbers, dates, quotes, and citation origins were checked;
- circular sourcing was removed;
- disconfirmation, key assumptions, and competing hypotheses were tested;
- forecasts have base rates, actor incentives, chart-ready evidence, and indicators.

If one item fails, run one targeted gap pass. Do not restart broad research.

## Final synthesis routing

When—and only when—the prompt requests the complete final research dossier, load and follow:

`references/final-dossier-contract.md`

It holds the long-form floor, handoff fields, citations, scenarios, market section, tables, conflicts, and failure checklist; working phases must not load or inherit its length floor.
