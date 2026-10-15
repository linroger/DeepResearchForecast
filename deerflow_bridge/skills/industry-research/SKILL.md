---
name: industry-research
description: Present-state diagnosis of an industry or value chain; the baseline of every industry outlook. Use for perimeter and segments, market size, demand and end markets, supply and capacity, costs and prices, profit pools, concentration and market shares, cycle phase (upcycle, inventory correction, overcapacity, downturn) and policy and geographic architecture (subsidies, local content, export controls; China vs US vs EU). Triggers: industry, sector, value chain, market size, capacity, utilization, shipments, inventory, pricing, oversupply, profit pool, market share; 行业, 产业, 产业链, 上中下游, 市场规模, 产能, 产能利用率, 出货量, 库存, 价格, 供需, 景气, 周期, 产能过剩, 市场份额, 集中度, 现状. Pair with industry-forecasting for a target-year state (到2030年, 2035年, 前景). Not for: who will lead or rank (competitive-landscape-forecasting); economy-wide growth, inflation or rates (macro-research); whether a tariff or export control happens (policy-and-trade-forecasting); asset prices or valuations (financial-markets-forecasting).
---

# Industry Research — present-state diagnosis

Present-state diagnosis of an industry or value chain: perimeter, size, demand, capacity, prices, profit pools, shares, cycle phase and policy, as the baseline of every industry outlook. It finds what binds the industry now, so the forecast, its binary anchors and the actor simulation start from measured facts.

## Activation

- Lead for present-state industry or value-chain questions. Route it with `industry-forecasting` on every target-year industry outlook (semiconductors, memory/HBM, batteries and storage, EVs, data centres, cloud, quantum, open-source AI); it also supplies the share table behind `competitive-landscape-forecasting`.
- Route elsewhere: target-year size or adoption → industry-forecasting; who leads or ranks → competitive-landscape-forecasting; economy-wide aggregates → macro-research; whether a tariff or export control happens → policy-and-trade-forecasting; asset prices → financial-markets-forecasting.
- Adds to the research core: a perimeter contract, four identities (demand decomposition, stock-flow, capacity bridge, volume × price), estimate-family reconciliation, cycle clocks, profit pools and five required exhibits. Sector specifics come from the injected sector adapters.

## Plan

Baseline KIQs, each worded with "industry" (行业/产业), the sector, geography and latest full year to route this method (merge to fit; quick: 1, 3, 4, 5):
1. data — size by segment: two independent estimate families, one official series.
2. data — demand: end markets × units × content × price; installed base vs flow.
3. data — capacity by stage, utilization, lead times; contract vs spot; marginal producer's cost.
4. general — profit pool by value-chain stage; dated top-5 shares; entry, exit.
5. data — cycle position (orders, inventory, utilization, prices, margins); "historically, how deep and frequent were downturns".
6. general — subsidies, local content, export controls: China, US, EU (Japan, Korea, Taiwan for chips).
7. actor — capacity moves and incentives of top capacity holders, marginal producer, fastest entrant, key customers, regulators, state funders (all as actors).
data_needs, catalog IDs first: chips fred:CAPUTLG3344S, fred:PCU33443344; data centres usgov:eia/electricity_sales/VA.COM; storage usgov:eia/generating_capacity/BAT; lithium imf:PCPS/G001.PLITH.USD.M; else {"query": "<industry> producer prices", "geography": "USA"}.
Sections: size; demand; supply, price; value chain, competition; cycle and policy; scenarios.
Scenarios: target year → industry-forecasting's frame (starts from this phase and constraint); main ask who leads → competitive-landscape-forecasting's; else next 12–24 months, split on the binding constraint (demand, capacity response, cost/price, policy), each defined by one horizon observable (price, utilization, volume). Weight base-rate-first: a horizon of half the documented cycle makes a phase change the base case, not a tail; announced capacity counts at stage-conditioned realization; promotional CAGR snippets never raise a boom weight.

## Investigate

Quick path (≈5 rounds; only items this KIQ asks for):
1. Perimeter — unit sold, stage(s), merchant vs captive, geography (produced vs consumed), CY/FY, price basis, currency.
2. Size — latest full year by segment: two independent estimate families (research firms S3; one figure repeated = one family) plus one official series (output, PPI, shipments, EIA, BEA value added: catalog ID, else data_search "<industry> shipments <country>").
3. Capacity — stage-tag each number: announced → financed → under construction → commissioned/ramping → qualified → utilized; + utilization, lead time.
4. Shares — top 3–5 with metric (revenue, units, capacity), period, source.
Standard: demand decomposition, contract vs spot, marginal cost, cycle clocks, policy status. Deep: profit pools, actor capacity moves, entry/exit, data_get(start = 30 years back).
Identities (show inputs; results REPORTED): revenue = Σ(end-market units × content × price); installed base = prior + shipments − retirements; shipments = consumption + Δinventory, per layer; 1+g_revenue = (1+g_volume)(1+g_price); capacity_end = start + commissioned − retired − converted; output = capacity × utilization × yield (yield once).
Reconcile sizes in order: perimeter, geography, period, price basis, gross/net, stock/flow, currency, real/nominal; residual → Conflicts. Never average concepts or sum stage revenues.
Cycle clocks (end-demand, inventory, capacity, financing, replacement, policy pull-forward): call a phase only when two of orders, shipments, inventory, utilization, prices, margins agree, else "indeterminate".
**Traps** (misreading → check):
- shipments up = demand up → sell-through, channel inventory;
- announced = supply → financing, orders, first output, qualification;
- spot = realized → contract price, reported ASP;
- association = customs = NBS → definition (output, wholesale incl. exports, installed), coverage (规模以上 omits small firms).
**Anchors**: official series as ID, one stored period (never an average), unit, SA/NSA, latest value, status, long-run range, a scenario-separating threshold (e.g., 10-year median).
Actors: name, aliases (Chinese, ticker), role, capacity by stage and site, capex plan vs actual, cost position, constraints (export controls, subsidies).
China: Chinese S1 (NBS, MIIT, customs, associations) + English filings.
Stop when each item this KIQ asks for has a finding or a named gap.

## Synthesize

Required exhibits (markdown tables of cited facts; blank means unknown, never zero), each placed once, in the section whose focus matches:
1. Size reconciliation: family | perimeter | geography | period | value + unit | basis | source; then the reconciled range and why rows differ.
2. Value chain and profit pool: stage | revenue pool | operating margin | leading players | scarce asset; no summed total; revenue share is not profit share.
3. Capacity by stage: owner/site | capacity + unit | stage | date | source.
4. Dated share table: rank | firm | share | metric | period | source; trend over ≥ 2 periods.
5. Cycle-phase dashboard: clock | indicator (series ID) | latest reading + period | direction | phase or indeterminate | what flips it.
Conventions: state the perimeter first; label actual, estimate, publisher projection, government target; split growth into volume and price; say FY or CY and the currency; tag each policy by jurisdiction and status. Keep structure (growing or not) separate from cycle (up or down): one does not imply the other.
Scenarios: analyse each canonical scenario through the binding constraint and the clock that would move first; write no second probability list and change no probability.
Signposts: series or disclosure, period, threshold, direction, scenario favoured (e.g., utilization below its 10-year median for two quarters); binary-ready ones name one stored period. Falsifiers: the observation that would overturn the baseline diagnosis.

## Gaps

- Is the perimeter stated (unit, stage, geography, period, currency)?
- Are two independent size estimates reconciled, plus an official series with ID, period, unit?
- Is capacity staged announced → financed → under construction → ramping → qualified → utilized, with lead times?
- Is there a dated top-share table naming its metric?
- Are contract and spot prices split and the marginal producer's cost located?
- Is each cycle clock read from two indicators or flagged indeterminate?
- Are policies tagged by jurisdiction and status (proposed, enacted, implemented, litigated, expired)?
- Do principal actors have evidenced capacity decisions, cost position and incentives?

## References

- [references/value-chain-and-sizing.md](references/value-chain-and-sizing.md) — load to set a perimeter, reconcile market sizes, decompose demand or growth, or estimate profit pools and concentration; includes an illustrative worked example.
- [references/cycles-and-capacity.md](references/cycles-and-capacity.md) — load to read cycle clocks, stage a capacity pipeline, run stock-flow checks or place the marginal producer on the cost curve.
- [references/industry-sources.md](references/industry-sources.md) — load to find S1 sources by jurisdiction and sector and their data caveats (China, US, EU, Japan, Korea, Taiwan, company filings).
- [references/sectors-technology.md](references/sectors-technology.md) — technology sector adapters (semiconductors, AI compute and data centres, cloud, autos/EV, batteries and storage, frontier tech); the engine injects the matching block.
- [references/sectors-economy.md](references/sectors-economy.md) — economy sector adapters (power, renewables, oil and gas, mining, agriculture, health, finance, real estate, consumer, industrials, transport); injected the same way.
