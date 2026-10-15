---
name: industry-forecasting
description: Target-year industry outlooks - an industry's state by a given year - market size and mix, adoption and penetration, installed base, capacity pipelines and lead times, cost and learning curves, transition milestones, target-year profit pools, alternative futures. Use for semiconductors, memory and HBM, AI compute and data centres, cloud, EVs, batteries and energy storage, quantum, open-source AI to 2030-2040. Triggers - industry outlook, market forecast, by 2030, target year, penetration, adoption curve, S-curve, learning curve, capacity pipeline, installed base, 行业展望, 行业预测, 到2030年, 2035年, 市场规模, 渗透率, 装机, 产能, 出货量, 技术路线, 成本曲线. Pair with industry-research and reference-class-forecasting. Not for - who will lead, rank or hold share (competitive-landscape-forecasting); prices, market caps, IPO size (financial-markets-forecasting); GDP, inflation, policy rates (macro-research); whether a law, tariff, subsidy or export control happens (policy-and-trade-forecasting).
---

# Industry Forecasting — Target-Year Outlooks

Forecast an industry's state in the target year, the path that gets it there and the evidence that will settle it: outside view first, every number labelled by type.

## Activation
- **Lead** when the question asks for an industry's state by a year: size and mix, adoption, installed base, capacity, cost curves, milestones, target-year profit pools.
- **Pair** with `industry-research` for the present baseline and its sector adapters (sector metrics, units and traps live there, not here) and with `reference-class-forecasting` for base-rate and probability craft.
- **Route away**: who leads or ranks → `competitive-landscape-forecasting`; prices, market caps, IPOs → `financial-markets-forecasting`; GDP, inflation, rates → `macro-research`; whether a law, tariff, subsidy or export control happens → `policy-and-trade-forecasting`.
- **Adds to the core**: the forecast contract, the horizon ladder, outside view before inside view, driver identities, feasibility and backcasting, output-type labels, and signposts a binary forecast can settle on.

## Plan
- **Contract first.** Pick 5–8 resolvable metrics; KIQs state each one's unit, CY flow or 31-Dec stock, nominal/real, currency, geography, settling publisher.
- **KIQs** (merge to fit):
  - data: baseline and current-year nowcast per headline metric;
  - data, worded "historical base rate of … by <target year>" (pulls 30 years): analogues or long history;
  - drivers per horizon rung: 0–2 yr committed supply, orders, inventory; 2–5 construction, cohorts, rivals; 5+ diffusion gate, cost curves, institutions; no timed cycle 10 years out;
  - general: external outlooks (IEA, BNEF, SEMI, WSTS, IDC/Gartner, CAICT, CNESA) on one definition;
  - actor: 2–3 capacity owners, anchor buyers or regulators setting the path.
- **data_needs**: a catalog ID only if it measures the metric; else a concept query + geography (EV sales, CHN).
- **Sections** (exhibit homes): baseline; drivers; supply path; target-year state; scenarios; signposts.
- **Scenarios.** 2–6 MECE cases split on 1–2 decisive uncertainties (adoption speed × policy or supply regime; cyclicals: demand × capacity response), one a stall or overbuild; each thesis states a non-overlapping headline-metric range; names in words.
- **Weights, base-rate-first.** Plurality to the range holding the simple benchmark (trend or constant share), never to a target or the boldest outlook. Skew by the analogue record (prior to verify): granular mass-made tech has tended to beat agency outlooks; lumpy first-of-a-kind builds (nuclear, fusion, new-country fabs, quantum) to slip. Shift only for enacted policy, funded capacity under construction.
- **Main ask who leads, ranks or overtakes**: "skills": ["industry-forecasting", "competitive-landscape-forecasting"]; the landscape leader frame replaces this split; size ranges go into its theses.

## Investigate
Sector specifics: any injected sector adapter.

**Quick path:**
1. Restate the contract: unit, flow or stock, nominal/real, geography, settling publisher; ever crossed, still true or sustained.
2. Official series first: data_get the catalog ID (base rate: start 30 years back; 240 points kept: 20 years monthly). None fits: data_search the concept, then S1 bodies in Chinese and English (NBS, MIIT, NEA, CPCA/CAAM, CNESA, CAICT; EIA, IEA, SEMI, WSTS; filings).
3. Nowcast the current year: year-to-date ÷ its usual share of the full year, never a run rate.
4. One external outlook: publisher, edition, scenario label, definition; REPORTED.

**Standard adds:** an analogue plus one that stalled; the capacity pipeline by stage with lead times; the binding adoption gate (technical → economic → qualification → distribution → paid use → retention; multiply). **Deep adds:** backcast (latest start = deadline − critical chain; parallel steps: max; negative slack = contradiction); past outlook editions vs actuals; funding (unfunded = conditional case).

**Horizon rung → evidence:** 0–2 yr orders, inventory, committed capacity; 2–5 construction, cohorts, rivals' moves; 5+ diffusion, cost curves, institutions.

**Identities** (show inputs; REPORTED): demand = installed base × usage; base(t) = base(t−1) + sales − retirements (sales share ≠ fleet share); cost = floor + (C0 − floor) × (cumulative ratio)^−b, never plus a time trend; S-curve only with a stated ceiling and denominator.

**Traps** (misreading → check):
- Target read as forecast → funded instrument; past attainment of that indicator type.
- Announced capacity counted as target-year supply → construction start; lead time vs deadline.
- IEA STEPS/APS/NZE read as forecasts → the publisher's own label.
- Recent CAGR run through saturation → share of the addressable base reached.
- Roadmap date read as milestone → the issuer's past roadmap record.

**Record** metric, value, unit, period, geography, basis, type (actual, nowcast, projection + edition, target), series ID or publisher table. **Signpost**: series, one stored period (never an average), comparator, threshold, units. **Actor**: lever, stated plan + date, behaviour in the last downturn, binding constraint, stake in fast vs slow adoption.
**Stop** when each metric this KIQ covers has an S1 baseline, an outside-view anchor and a feasibility bound, or a named gap.

## Synthesize
- **Conventions**: "by YEAR" = a metric's YEAR value (flows calendar-year, stocks at 31 Dec) or an event on or before 31 Dec; say whether a threshold is ever crossed, still true or sustained. Label every number: forecast, conditional projection, policy target, external projection (publisher, edition, scenario) or stress test. A target such as 中国2030目标 is never the central view.
- **Place each exhibit once**, in the section whose focus matches; others refer to it.
- **Target-year state table**: Metric | Baseline value, year + marker | Central view (if theses give ranges: inside the one holding the frame's median) | Range (scenario envelope) | Decisive driver | Signpost (series, period, comparator, threshold).
- **Path and milestones table**: milestone | needed-by or latest start | status + evidence | slack.
- **Supply-demand note**: implied demand vs deployable, funded supply; the binding constraint; how a gap clears (price, backlog, imports, lost demand).
- **Outlook table**: publisher + edition | label and type | value as published + marker | aligned to our metric or why not.
- **Scenarios**: trace each canonical scenario through the decisive uncertainties; keep volume and producer profit apart (fast adoption with price deflation can shrink margins).
- **Quantities**: derived figures show their inputs; never sum marginal P90s; where evidence cannot carry a number, give a bounded judgment.
- **What would change the view**: 3–5 falsifiers, each indicator + threshold + date.

## Gaps
- Does every headline metric have a definition, an S1 baseline and a current-year nowcast?
- Is there an outside-view anchor: an analogue transition or 20+ years of official history?
- Is target-year supply counted only from capacity whose stage, lead time and funding reach the deadline?
- Is implied demand reconciled with deployable supply?
- Are external outlooks aligned (definition, vintage, scenario label) and tagged as projections?
- Does each scenario rest on a decisive uncertainty with a dated signpost?
- Does a signpost name a series or publisher table, period and threshold?
- Are the actors who set capex or rules covered with their constraints?

## References
- [references/forecasting-methods.md](references/forecasting-methods.md) — load when doing adoption, S-curve, learning-curve, stock-flow, nowcast, backcast or quantile arithmetic; worked mini-examples with illustrative numbers.
- [references/reference-classes-and-lead-times.md](references/reference-classes-and-lead-times.md) — load for the outside view: choosing analogues, diffusion-speed and lead-time priors to verify, base rates from catalog history.
- [references/outlook-reconciliation.md](references/outlook-reconciliation.md) — load when external forecasts disagree: definition alignment, vintages, scenario labels, Chinese statistical calibres (口径).
