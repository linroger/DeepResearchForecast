---
name: reference-class-forecasting
description: Outside-view and probability craft for any dated forecast - will X happen by a date, how likely, how often has this happened before, how to weight scenarios. Route it for every forecast question beside its domain skill. Covers resolvable question contracts, reference classes counted k of n from long official series (data_get) and S1 event lists, hazard-to-deadline conversion, AND/OR decomposition, scenario-to-binary consistency, anchor-and-adjust bridges and prediction-market anchoring. Triggers - base rate, how often, historically, precedent, probability, odds, chance, likelihood, by 2027, before the deadline, will it happen; 基准率, 历史先例, 频率, 概率, 可能性, 多大可能, 是否会, 到2028年前, 赔率, 预测市场. Not for domain substance - macro-research, policy-and-trade-forecasting, geopolitical-forecasting, election-forecasting, competitive-landscape-forecasting, industry-forecasting, financial-markets-forecasting; market query craft is prediction-markets; series retrieval mechanics are data-sources.
---

# Reference-Class Forecasting
Anchor every dated forecast on an outside view: a resolvable question, comparable cases counted k of n from official history, then named, evidenced adjustments into coherent probabilities.

## Activation
- Routed for every forecast question, beside at most two domain skills. The domain skill explains what drives the outcome; this skill says how often comparable cases went each way and turns that into coherent probabilities.
- v3 injects Plan into the planner, Investigate into base-rate KIQs only, Gaps into the gap review and Synthesize into the scenario section only. Legacy lead: read this file in the opening pass; apply Investigate to base-rate passes and Synthesize to the scenario part of the dossier.
- Adds to the deep-research core: counting rules, hazard and deadline math, small-sample correction, decomposition, scenario/binary coherence, the anchor bridge and market-bias corrections. The core's source tiers, ledger and yield stop apply unchanged.
- Market query craft and the market table: prediction-markets. Series mechanics: data-sources.

## Plan
- **Make the question resolvable** first: event, threshold with unit, deadline, settling source (series ID or S1 publisher) and its edge rules (which print settles; fallback if it lapses). "By YEAR": an event on or before 31 Dec YEAR; levels, states, ranks: the domain skill's convention; "in YEAR" = that year only. Label ever-touch vs end-state: a data anchor settles one completed period.
- **Add 1-2 base-rate KIQs**, worded with "base rate", "historically", "how often" or "precedent" (基准率, 历史先例, 频率): this routes this method and stores their data_needs 30 years back. Example: {"question": "Base rate: how often did US annual inflation drop from above 4% to below 2.5% within 2 years?", "kind": "data", "data_needs": [{"series": "wb:IMF_WEO_PCPIPCH/USA"}]}. Without a series, a general KIQ asks for an S1 event list (NBER cycle dates, UCDP, Congress.gov, FOMC history, exchange IPO statistics).
- **Weight scenarios base-rate-first** (fixed now, from scout snippets). (1) Anchor on a scout base rate, else the status-quo prior (continuation, at the horizon hazard of comparable change). (2) Shift only for named scout evidence the class lacks, about 5-15 points each unless decisive (an enacted law, signed deal). (3) Integers summing to 100; merge any scenario under 5 unless a signposted tail.
- **Split on the decisive variable** (anchor-metric ranges, or the forcing decision's outcome), so key binaries derive from the weights. Make it exhaustive (open end ranges or a residual).
- **Name the anchor in each thesis** ("...; prior: 3 of 11 easing cycles"). Names stay number-free.
- Decision points in the horizon (meetings, votes, rulings, elections) need a calendar KIQ; none: lean to the status quo. Key actors: track record (deadlines, threats, roadmap dates honoured, k of n).

## Investigate
**Quick path: one class, one series, one count.**
1. Fix the counting rule before reading data: start condition like today's, event, threshold with unit, horizon, what one episode is. Match end-state vs ever-touch and "by" vs "in".
2. data_get with start 30 years back on the first call (that fixes the stored window). Only the newest 240 observations stay (20 years monthly): use annual or quarterly data for longer counts. Without a series, fetch one S1 event list: NBER cycle dates, UCDP/COW data, Congress.gov, Federal Register, FOMC decision history, SSE/SZSE/HKEX listing statistics, NBS releases. Wikipedia lists (S3) only map to S1.
3. Count "k of n episodes" of the conditional class (the forecast stage computes the unconditional h-step share), with each episode's period and stored value; tag REPORTED; if n < 20 add (k+1)/(n+2).
4. In the same finding: window, survivorship (failures, stalls, still-open cases counted?), censoring, regime change.

**Standard:** add a second class by a different causal similarity (mechanism, institution, actor); report both and the spread. **Deep:** condition on today's state (regime; distance to the threshold in σ of h-period changes); add stage-conditioned rates (bill past one chamber, ceasefire signed, plant being built) and the actor's own track record.

**Record each finding as** class | rule | k/n | window | source + series ID | settling period, unit, threshold | applicability. Example: "- US annual CPI inflation (wb:IMF_WEO_PCPIPCH/USA, observed rows) fell below 2.5 within two years of a year above 4 in k of n episodes of the stored window [S<n>] (REPORTED)".

**Traps (misreading → discriminating observation):**
- Famous-case sample → does the list hold the failures and unresolved cases?
- Overlapping windows inflate n → keep start points at least one horizon apart.
- Wrong measure → check the settling series: SA vs NSA, average vs end of period, first print vs revised.
- Projection read as history → only rows with status observed count.
- Headline analogy → did the class's cases turn on the same mechanism?
- Prediction-market odds → v3 collects them after writing: skip them here (futures/OIS stay with the domain skill); legacy runs prediction_market_search once, in the opening pass.

**Stop:** quick: one class with k/n and caveats. Standard: when a second class moves the anchor < 10 points or two angles add nothing.

## Synthesize
Scenario section only. Use counts from the findings; never invent one.
- **Base-rate table:** | Reference class | Counting rule | k/n | Window | Source | Applicability |. When classes disagree, state the range and which class fits the mechanism best.
- **Anchor → adjustment bridge,** one row per canonical scenario: | Scenario | Anchor (class, k/n) | Adjustments: direction, mechanism, evidence [S<n>] | Why not already in the class | Reads vs frame weight |. The last column says consistent, or that the evidence leans higher or lower. Write no new probability per scenario.
- **Market comparison,** only from market rows in the evidence: | Market | Its resolution vs ours | Price, volume, date | Gap to our anchor | Why |. Explain any gap over 10 points: resolution mismatch, longshot or long-dated bias, a thin or stale market, or evidence the market lacks. With no rows, state the exact resolution terms a market would have to match.
- **Binary map:** for each key binary, give its series, period, comparator, threshold and units, and the canonical scenarios in which it resolves yes or partly (its probability then follows from the frame weights), or mark it "not derivable"; write no new number.
- **Coherence:** a later deadline or an easier threshold is never less likely; label each question event, ever-touch or end-state.
- Any probability: granular, never 0 or 100, not extremized from one model; simulation and persona outputs are scenario evidence, not independent experts.

## Gaps
- Does each forecast question name the event, threshold with unit, deadline and settling series or S1 source?
- Is there a k-of-n base rate (rule, window, source) for the central outcome?
- Was a second reference class tried, with failures and unresolved cases counted?
- Does each scenario's anchor and adjustment trace to findings, with no driver counted twice?
- Is every scheduled decision point inside the horizon (meeting, vote, ruling, election) covered?
- Do the key binaries have an anchorable series, period, comparator and threshold?
- Is each key actor's track record recorded (deadlines, threats or roadmap dates honoured, k of n)?

## References
- [references/base-rate-recipes.md](references/base-rate-recipes.md): load when building a base-rate KIQ. Worked classes, counting rules and sources for macro thresholds, policy passage, conflict termination, technology adoption, leader persistence and elections.
- [references/probability-toolkit.md](references/probability-toolkit.md): load when turning counts into probabilities. Hazards, time decay, Laplace, chains and routes, scenario consistency, updating without double-counting, volatility distance.
- [references/prediction-market-anchoring.md](references/prediction-market-anchoring.md): load when a market or forecasting-platform price exists for the question. Liquidity rules, biases, resolution mismatch, the divergence rule.
