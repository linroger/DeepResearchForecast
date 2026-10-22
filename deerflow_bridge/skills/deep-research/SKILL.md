---
name: deep-research
description: Use for external-evidence research and forecasting. Core rules cover KIQs, provenance, convergence, disconfirmation and phase handoffs; details are lazy references.
---

# Deep Research — Core Contract

Produce forecast-useful research with fetched evidence, graded provenance and explicit uncertainty.

## Activation discipline

When this body is injected, do **not** reread `SKILL.md`. Load only a named lazy reference when the phase needs it.

## Phase type comes first

The prompt's phase overrides final-output rules:

- **Working phases**: opening/source maps, scoped workers, KIQ top-ups, verification, actor/correction passes and fan-out absorption return concise evidence notes and gaps. They are exempt from final word-count, section-count and prose floors. Do not pad or synthesize the final report.
- **Final dossier synthesis only**: only an explicit complete-dossier request uses the long-form and handoff contract in `references/final-dossier-contract.md`.
- **Structured extraction/judging** — follow the requested JSON/scorecard schema, not the prose length contract.

## Core loop

1. Decompose the brief into 3–7 Key Intelligence Questions (KIQs). Mark load-bearing KIQs, likely S1/S2 source classes, priors, and what would falsify them.
2. Search for documents, not commentary. Use `web_search`, then `web_fetch` the strongest pages in full. For official statistics use `data_search` → `data_get` if available. Before using an exposed `news_search`, `social_search` or `market_compare`, load `references/news-market-context.md`; their rows are leads or context, never anchors. For forecast calibration use `prediction_market_search`; if unavailable, use read-only `web_fetch` against the public Gamma API. Run the full market sweep **once, in the opening pass**; if it surfaces zero topically relevant markets, record `no_market_coverage` and skip market search in later phases (one refresh at synthesis only). A transport-failing market tool must not be retried within the same phase.
3. Maintain an evidence ledger: `KIQ → claim → source/title/real URL/date/tier → independence → grade → open gap`.
4. Prefer primary origins, verify numbers/units/as-of dates, trace repeated claims back to their origin, and seek the strongest opposing case.
5. Check convergence after every evidence-bearing call. Continue only for a named unresolved KIQ with a credible next upgrade.
6. Before final synthesis, verify the synthesis gate and load the final-dossier reference.

## News and market context

`news_search` discovers publisher URLs; `web_fetch` originals before factual/numeric claims. Reuse prefetch. Optional `social_search` is opinion; `market_compare` is context, never automatic anchors or settlement evidence. Keep provider/native IDs, dates, units, quote bases, rules and horizons; similar titles do not establish equivalence/arbitrage. Distinguish outages, denials, partial and verified-empty results; replay sealed evidence. Full rules: `references/news-market-context.md`.

## Evidence discipline

- **S1**: original/authoritative material — official statistics, filings, laws, court records, peer-reviewed papers, transcripts, primary datasets, direct first-party statements. Preferred for load-bearing facts.
- **S2**: accountable high-quality reporting/analysis — major wires/outlets, serious trade press, established research bodies. Context and a pointer to S1.
- **S3**: conditional/biased/derivative — vendor research, expert blogs, preprints, Wikipedia as a map. Corroborate or attribute explicitly.
- **S4**: reject — SEO/affiliate slop, anonymous/undated aggregators, unsupported statistics, synthetic rewrites. Do not fetch or cite.

Only cite sources actually fetched and read. Preserve their true URL and on-page date. Never invent a title, URL, market, quote, or future-dated document. Two outlets repeating one underlying report are one origin, not triangulation.

For each quantitative fact record the metric, value/range, unit, as-of date, definition, geography/population, and source URL. Sanity-check magnitude, currency, nominal/real basis, denominators, totals, and compounding. Quote stored official series exactly with period and `[S<n>]`; projections are not history.

Load `references/source-tradecraft.md` for targeting, source grading, numeric checks, adversarial analysis and obstacle routing.

## KIQ and evidence-yield stopping

Tool counts and source counts are safety telemetry, never quotas or quality proxies.

- **KIQ done**: each load-bearing claim is B2-or-better and its strongest plausible opposing case was checked; or accessible S1/S2 paths are exhausted and the remaining gap is explicit.
- **Evidence delta**: a new independent origin, stronger tier, verified number, resolved contradiction, reference-class base rate, watchable indicator, or genuine disconfirmation.
- **Yield stop**: two genuinely different angles produce no evidence delta. Stop that line and record the gap.
- **Continue**: at least one priority KIQ remains unresolved and the next call has a named expected upgrade.
- Never issue a near-duplicate query. Change actor, mechanism, document type, jurisdiction/language, or time window—not punctuation.
- Checkpoint the ledger after every pass; later phases must not re-research settled items.

## Forecast-specific requirements

Collect forecast inputs:

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

Final dossier synthesis follows `references/final-dossier-contract.md`: prose floors, handoff fields, citations, scenarios, markets, tables, conflicts and failure checks.
