---
name: prediction-markets
description: Use this skill whenever a research question is a forecast — anything asking about probability, outcomes, elections, policy decisions, macro events, or "will X happen". It teaches the prediction_market_search tool (Polymarket's public Gamma API — no API key, no wallet) — how to derive short high-recall queries that match how markets are actually titled, which markets to trust (open, priced, liquid), how to self-filter for relevance, and how to write the surviving anchors into a "Prediction Market Signals" table. Market-implied probabilities are calibration anchors, never ground truth.
---

# Prediction Markets Skill

When this body is eagerly loaded for a scoped researcher, it is already complete
in the conversation. Do **not** read `SKILL.md` from the filesystem again; use
the permitted tools directly and record the resulting market rows.

## 1. Why markets, and what they are not

Prediction-market prices are the **aggregated, money-weighted belief of people with skin in the game** — an excellent *calibration anchor* for a forecast. They are NOT ground truth: prices move continuously, thin markets are noisy, and market questions rarely match your research question's resolution criteria word-for-word. The workflow is: fetch → filter → compare → explain divergence — never copy.

The `prediction_market_search` tool queries **Polymarket's public Gamma API** (`https://gamma-api.polymarket.com` `/public-search` — no key, no wallet) for active markets and returns, per market: `market_id`, `exchange` (`"polymarket"`), `question`, `implied_yes_prob` (the "Yes" price), `volume`, `liquidity`, `event_title`, `url`, and `end_date`. It is degrade-safe: network failure / nothing found → empty result. **An empty result is an answer** — note "no liquid markets overlap this question" and move on; never fabricate a market or a price.

In this forecast workflow, every successful tool response is also captured in an append-only run ledger (`prediction_market_candidates.jsonl`). The deterministic finalizer relevance-gates and refreshes that ledger into the canonical `prediction_markets.json`. This is a first-class delivery contract: a useful market you found mid-research must survive even if a later query is phrased differently. Do not repeatedly issue an identical query payload—the tool caches normalized payloads for the life of the research process, and repetition adds no evidence.

**Fallback if the tool is unavailable**: query the Gamma API directly via the available `web_fetch` tool — it is the same keyless endpoint:

```
https://gamma-api.polymarket.com/public-search?q=<short query>&limit_per_type=8&events_status=active
```

Each returned event carries a `markets` list; per market read `question`, `outcomes`/`outcomePrices` (the "Yes" index is the implied probability), `volume`, `closed`, `endDate`, `slug`. Apply the same filters as §3.

These are the only two permitted access paths in this research agent: the narrow
`prediction_market_search` tool first, then read-only `web_fetch` to the public Gamma
endpoint. Do not invoke a shell, CLI, wallet, CLOB order endpoint, or any state-changing
market operation. If both permitted paths have a real transport/protocol failure, record
that degraded status and continue without a market anchor. A valid empty or
relevance-filtered result is not a transport failure.

**The stop rule.** The full market sweep (the derived queries of §2) runs **once, in the
opening pass**. If it surfaces no liquid, topically relevant market, record
`no_market_coverage` and **stop querying markets** — coverage does not appear because a
later phase rephrases the question; one refresh at final synthesis is the only follow-up.
Likewise never loop retries on a `transport_failure`: after a real transport/protocol
failure, record the degraded status once and do not re-call the failing path within the
same phase.

## 2. Query craft (match how markets are titled)

Market search is full-text over market/event **titles**, and Polymarket titles are concrete and outcome-shaped: markets are titled like **"Ohio Senate winner"**, **"House control 2026"**, **"Fed rate cut in September"** — never like **"midterm elections analysis"** or "impact of tariffs on semiconductors". Query the way a market would be titled, not the way a research brief is worded.

- **Short phrases (≤5 words) work best** — `tariff`, `semiconductor export`, `Fed rate cut`, `House control 2026`, `Ohio Senate`.
- Derive up to ~6 queries deterministically from the run's materials:
  1. The 2–3 most **salient noun phrases** of the central question (strip stopwords and generic forecast-speak like "forecast", "impact", "scenario", "analysis"; keep short all-caps acronyms — AI, EU, GDP).
  2. The run's **hot topics** (up to 4).
  3. The **top 2–3 actor names** by salience (candidates, agencies, companies).
- Deduplicate case-insensitively; trim each query to ≤5 words.
- Do not reissue near-duplicate queries; a thin result means change the phrase's *angle* (another actor, another driver, a concrete race or decision), not its word order.
- Reuse the exact returned `market_id` and `url`; never reconstruct a URL from memory. Record `end_date`, volume, liquidity, and the fetch timestamp so downstream freshness checks and charts remain auditable.

## 3. Filtering (relevance is YOUR job)

The tool already drops closed, unpriced, resolved (price exactly 0/1), and low-volume (volume < ~200) markets, dedupes by `market_id`, ranks by volume, and caps each event to ~3 markets so one multi-outcome ladder (e.g. "How many Fed rate cuts in 2026?") cannot flood the snapshot.

What the tool CANNOT judge is **relevance — self-filter every hit before using it**:

- Full-text search returns lexical matches, not topical ones: a query like `China` will surface sports, crypto, and celebrity markets. Discard any market whose question does not bear on your research question.
- Check **question match honestly**: does the market's question, horizon (`end_date`), and resolution rule actually correspond to the statement you are forecasting? A near-miss market (different threshold, different date) can still be cited — with the mismatch named — but must not be presented as equivalent.
- Prefer higher `volume`/`liquidity` when several surviving markets say the same thing.
- Keep only anchors you would defend; an unfiltered market table is worse than none.

## 4. Using the anchors — the "Prediction Market Signals" table

Write the surviving anchors into the research report as a **"Prediction Market Signals"** section: a markdown table with one row per market —

| Market question | Implied P(yes) | Volume (USD) | Ends | URL |
|---|---|---|---|---|
| House control 2026 — GOP | 0.62 | 1,240,000 | 2026-11-03 | https://polymarket.com/event/… |

populated from the tool's `question`, `implied_yes_prob`, `volume`, `end_date`, and `url` fields, plus the standing caveat that this is a **machine-fetched snapshot of moving prices** (note the fetch time).

- **Cite, don't copy.** Where your forecast overlaps a listed market, cite the market's implied probability in your reasoning. Your probability remains YOUR probability, produced by your own base-rate + evidence reasoning.
- **The divergence rule**: when your probability differs from a cited market by **more than 10 percentage points**, explain the divergence explicitly — what the market is missing or mispricing (private research signal, definitional mismatch, stale pricing around a catalyst). Silent large divergence is a defect; so is silent convergence achieved by copying.
- **Freshness**: a snapshot ages fast around catalysts; re-fetch rather than reason from a stale table when synthesis runs long after research.

## 5. Failure modes

- ❌ Long natural-language queries ("what is the probability that the US will raise tariffs in 2026") — full-text search returns junk; use `tariff`, `US tariffs`.
- ❌ Research-speak queries ("midterm elections analysis") — markets are titled like "Ohio Senate winner", "House control 2026"; query in that register.
- ❌ Keeping lexical-match hits that are topically irrelevant (self-filter every market).
- ❌ Anchoring on a closed, unpriced, or resolved (price 0/1) market.
- ❌ Copying the market price as your forecast probability (that is abdication, not calibration).
- ❌ Diverging >10pp from a cited market without an explicit explanation.
- ❌ Treating a market with mismatched threshold/date as equivalent to your statement.
- ❌ Fabricating market IDs, prices, or URLs when the tool returns nothing.
- ❌ Presenting the snapshot as live truth without the freshness caveat.
- ❌ Re-running market search phase after phase once `no_market_coverage` is recorded (§1 stop rule; one synthesis refresh only).
- ❌ Retrying a transport-failing market path within the same phase instead of recording the degraded status and moving on.

## 6. Source-aware contextual comparisons

When `market_compare` is exposed, it supplements this Polymarket anchor workflow with source-aware research context. Retain provider and native IDs, literal outcome labels, bid/ask/last basis, contract-volume units, timestamps, resolution rules and horizon. Kalshi and community-forecast rows stay outside the Polymarket anchor registry; never pass their IDs to Gamma/CLOB or automatic settlement. Topic overlap is a discovery lead, not event equivalence or executable arbitrage.

Use `news_search` for article discovery and fetch selected publisher pages through `web_fetch` before factual claims. Optional `social_search` supplies attributed opinion, not factual confirmation. Do not turn headline tone into a probability, call missing evidence neutral, or label a source outage as absence of a relevant market. Preserve explicit provider statuses and reuse the sealed contextual snapshot. These tools are available only when enabled; their absence does not change the existing permitted Polymarket paths above.
