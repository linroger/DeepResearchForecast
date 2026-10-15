# Forecasting methods — worked mini-examples

Every number in this file is **illustrative**, chosen to make the arithmetic visible; none is a fact about any industry. When an agent does this arithmetic on real inputs it shows the inputs, cites each input's marker, and tags the result REPORTED (it is the agent's calculation, not an observation).

## 1. Lock the contract before any model

One question wording can hide three different metrics. Settle which one the forecast is about, and name the publisher whose release will resolve it.

| Question as asked | Resolvable metric | Type | What a careless reading gets wrong |
|---|---|---|---|
| 中国新能源汽车渗透率到2030年 | NEV share of domestic passenger-car retail sales, calendar 2030 (a CPCA-type retail series) | annual flow ratio | CAAM-type wholesale includes exports and commercial vehicles: different numerator and denominator |
| Global data-centre power by 2030 | electricity consumed in calendar 2030, TWh | annual flow | installed IT GW at 31 Dec 2030 is a stock; grid-connection requests are a pipeline |
| China new-type storage by 2035 | cumulative installed GW **and** GWh at 31 Dec 2035, pumped hydro excluded | year-end stock | annual additions are a flow; GW without duration says nothing about GWh |
| Chip market reaches USD 1 trillion by 2030 | calendar-2030 nominal device sales on one vendor-sales definition | annual flow, nominal | adding foundry revenue to fabless revenue counts the same wafers twice |
| Quantum advantage by 2035 | a qualifying demonstration, judged by a named arbiter, occurring by 31 Dec 2035 | event | a vendor press release is not the arbiter |

**Ever crossed, still true, sustained.** Take a monthly share path that first reaches 50% in November 2029, dips to 48% in December 2030 and averages 47% over 2030. "Ever reaches 50% by 2030": yes. "At or above 50% at the end of 2030": no. "2030 annual share of at least 50%": no. Write which of the three the question means into the metric definition; a binary forecast anchored on the wrong one resolves the wrong way.

**Basis.** State nominal or real (and the base year), currency, and the FX rule: flows convert at the period-average rate, stocks at the period-end rate. Convert only when the task needs it, and keep the published figure beside the converted one.

## 2. The benchmark the forecast must beat

Before any driver model, run the simple benchmarks to the target year and keep them in the notes:
- **no change** (last full-year value);
- **drift** (average absolute change of the last 5–10 years);
- **constant share** (the metric's share of a parent aggregate held fixed);
- **constant CAGR**, only while the metric is far from any ceiling.

A central view that departs from the benchmark needs a named mechanism with evidence. Report both, so a reader can see how much the view depends on the inside story.

## 3. Nowcast the current year

Year-to-date January–August = 7.2 units. Over the last five years, January–August made up 0.62, 0.64, 0.61, 0.63 and 0.65 of the full year (mean 0.63).
- Full-year nowcast = 7.2 ÷ 0.63 = **11.4**; range 7.2 ÷ 0.65 = 11.1 to 7.2 ÷ 0.61 = 11.8.
- The run-rate shortcut 7.2 × 12/8 = 10.8 understates a year whose second half is seasonally heavy (year-end delivery and installation rushes are common in autos and solar).
- Check for a break in seasonality: a subsidy or tax change at year-end pulls demand forward into the current year and out of the next. Model it as a level shift around the cliff, not as trend.

## 4. Demand = installed base × usage intensity

**Data-centre electricity.** Energy = IT capacity × average utilisation × PUE × 8,760 h.
- 10 GW × 0.6 × 1.3 × 8,760 h = 68.3 TWh.
- Utilisation 0.5 to 0.7 gives 56.9 to 79.7 TWh: utilisation is a decisive driver, not a detail.
- Units trap: an announced campus "GW" is usually a grid request; IT MW, facility MW and energised MW are three different numbers. PUE multiplies IT load, never the grid request.

**Memory revenue.** Revenue = bits shipped × price per bit, so (1 + revenue growth) = (1 + bit growth)(1 + price-per-bit growth).
- Bits +20%, price per bit −15%: 1.20 × 0.85 = 1.02, revenue **+2%**.
- In a glut, price per bit −40%: 1.20 × 0.60 = 0.72, revenue **−28%** on rising volume. The profit pool falls faster still, because fab costs are largely fixed.

**Battery demand.** GWh = vehicles sold × average pack kWh + stationary storage + other uses; 20 million × 55 kWh = 1,100 GWh for the vehicle part. Pack size moves with the BEV/PHEV mix, so forecast the mix, not one average.

**Usage-priced services** (cloud, AI inference): revenue = workload units × price per unit. Price per unit tends to fall fast, so volume must outrun price deflation for revenue to grow; forecast both legs.

## 5. The adoption chain multiplies

Gates in order: technical readiness → economic competitiveness → qualification or regulatory acceptance → distribution and complements → paid usage → retention.

P(at scale by the target year) = P(technical) × P(economic | technical) × P(qualification | economic) × … Illustrative: 0.9 × 0.75 × 0.8 × 0.9 × 0.85 × 0.9 = **0.37**. Six individually likely gates compound to well under one half.
- Spend the research budget on the gate with the lowest conditional probability: that gate binds.
- Each gate also has a duration; sequential gates add up, and the sum is the input to the backcast in §9.
- Evidence per gate: a demonstration on the stated metric (not a roadmap); cost per useful output against the incumbent; a granted certification or rule; deployed paying customers (not pilots or downloads); renewal or churn data.

## 6. S-curves: ceiling first, speed second

Logistic share s(t) = K / (1 + e^(−r(t − t0))), with ceiling K, speed r and midpoint t0.
- Time to go from 10% to 90% of K = ln 81 ÷ r ≈ 4.39 ÷ r. With r = 0.45 per year that is 9.8 years; with r = 0.9, 4.9 years.

**Early data cannot pin the ceiling.** Observed shares of 2%, 4% and 8% in three consecutive years fit both of these curves (both with r = ln 2):

| Year | 0 | 1 | 2 | 6 |
|---|---|---|---|---|
| K = 40% | 2.0% | 3.8% | 7.0% | 30.8% |
| K = 90% | 2.0% | 3.9% | 7.5% | 53.3% |

Both stay within about one point of the observed history, yet they are 22 points apart four years later.

Rules:
- Set K from an explicit denominator: the segments where the technology is technically and economically eligible, each named, with its size.
- Take r from the analogue range (see the reference-class file) rather than fitting it on three points.
- Treat the ceiling as a scenario dimension, not as a confidence interval.
- Build the aggregate from segments (passenger cars vs heavy trucks; consumer vs enterprise), each with its own K, r and t0. The sum is not a logistic.
- A mandate or subsidy shifts r and K directly; a subsidy cliff gives a pull-forward then a dip.

**Bass form.** The adoption hazard is p + q·F(t), where F is the adopted share of the ceiling: p is external influence, q imitation. Meta-analyses of consumer durables in the marketing-science literature report average p near 0.03 and q near 0.4. That is a prior to verify; infrastructure-dependent and business-to-business technologies usually run slower.

## 7. Learning curves on cumulative output

Cost C(x) = C0 × (x / x0)^(−b), where x is cumulative output; learning rate LR = 1 − 2^(−b).
- LR 18% gives b = −log2(0.82) = 0.286; three doublings of cumulative output give 0.82³ = 0.551 of the starting cost.

**Put in a floor.** Write C = F + (C0 − F) × (x / x0)^(−b), with F the part that does not learn (raw materials, regulated fees).
- Start at C0 = 100, of which materials F = 40. After three doublings: 40 + 60 × 0.551 = **73.1**, not the no-floor 55.1.
- If materials then rise 50% (F = 60): 60 + 33.1 = **93.1**. Cost can rise while cumulative output doubles; pack-price surveys recorded exactly this kind of reversal during the 2021–22 lithium spike (verify the survey before citing it).

**Learning speed follows growth.** In steady exponential growth at rate g, cumulative output doubles every ln 2 ÷ ln(1 + g) years, so the annual cost decline is 1 − (1 − LR)^(1/T).
- g = 25%: doubling every 3.1 years, cost falls about **6.2% a year**.
- g = 10%: doubling every 7.3 years, cost falls about **2.7% a year**.
A slowdown in volume growth slows the cost decline, and through it adoption: the loop runs both ways.

Rules:
- **No double counting.** Applying the learning rate to cumulative output and then an extra "−x% per year" time trend counts the same progress twice. Pick cumulative output as the driver; add a time term only for a residual that has its own evidence.
- **Price is not cost.** Price tracks cost only under competition. In shortage (advanced packaging, transformers, leading-edge memory) price decouples from cost; learning acts on cost, scarcity acts on margin.

## 8. Stock-flow and cohorts

Installed base(t) = base(t − 1) + sales(t) − retirements(t), and sales = replacement + net fleet growth.

**Sales share is not fleet share.** Fleet 300 million vehicles, 25 million sold a year, 20 million retired a year (all retirements assumed old combustion cars), 20 million EVs on the road at the start. EV sales share rises 40%, 50%, 60%, 70%, 80% over five years, so EV sales are 10, 12.5, 15, 17.5 and 20 million (75 million in total).
- After five years the EV fleet is 20 + 75 = 95 million out of 325 million: **29%** of the fleet, while EVs are 80% of sales.
- Energy, charging and fuel demand follow the fleet; factory and supplier demand follow sales. Forecast the one the question asks about.

**Lives and retirements.** In a steady state, annual retirements ≈ installed base ÷ mean life. Take lives from filings and engineering sources (server and accelerator depreciation lives, battery warranty and degradation terms, vehicle scrappage), never from one anecdote. Storage fleets also lose capacity each year and need augmentation; a GWh stock is not a constant.

**Channel inventory.** Shipments = consumption + change in inventory.
- Consumption grows 100 → 105 (+5%). Channel inventory was built up by 12 last year and is drawn down by 6 this year.
- Shipments go from 112 to 99: **−11.6%** while end demand grows. A shipment-based forecast reads destocking as a demand collapse; sell-through and inventory weeks discriminate.

**Unmet demand.** Say whether demand the supply cannot serve is lost, delayed into backlog, or served by imports or substitutes. Each choice moves a different year's number.

## 9. Feasibility: staged pipelines and backcasting

**Stage-conditioned capacity.** Expected capacity = Σ (MW at each stage × P(completed by the deadline | stage)). Illustrative stage probabilities: announced 0.3, permitted or financed 0.6, under construction 0.85, commissioned 0.97 (build real ones from the reference-class file).

**Correlation breaks the interval.** Ten 1 GW projects, each with P = 0.6:
- If independent: expected 6 GW, standard deviation √(10 × 0.6 × 0.4) ≈ 1.5 GW.
- If all ten hinge on the same subsidy or transformer supply: still 6 GW expected, but the outcome is near 0 or near 10. A probability-weighted sum then describes no world that can happen; split on the shared factor as a scenario instead.

**Backcast to a latest start.** Target: a campus energised by 31 Dec 2030. Interconnection study and agreement 36 months; transformer procurement 30 months; building shell 18 months; these three run in parallel, then energisation and commissioning take 6 months.
- Critical chain = max(36, 30, 18) + 6 = 42 months, so the latest start is **30 June 2027**. Parallel prerequisites take the maximum, never the sum (the sum, 90 months, would wrongly rule the target out).
- If the interconnection request is not yet filed and the regional queue typically takes longer than 42 months, slack is negative: the target-year state is a contradiction unless another route exists.
- **AND routes** multiply: P(A and B) = P(A) × P(B | A).
- **OR routes** combine: P(grid by the deadline) = 0.5 and P(on-site generation by the deadline | no grid) = 0.4 give P(energised) = 1 − 0.5 × 0.6 = **0.7**.

**Funding.** Required capex = capacity added × unit capex. Compare it with the builders' cash flow, balance sheets and the buyers' capex guidance. A build-out nobody has funded is a conditional case, never the central view.

## 10. Quantiles, envelopes and mixtures

**Non-exceedance convention.** P10 is the value with a 10% chance that the outcome is at or below it; P10–P90 is a central 80% interval. Petroleum and some energy reporting use exceedance (a "P90 reserve" has a 90% chance of being met or beaten); flip such figures before comparing.

**Never sum marginal P90s.** Two independent regions, each with mean 100 and standard deviation 20:
- each P90 = 100 + 1.2816 × 20 = 125.6, so the sum of the P90s = 251.3;
- the P90 of the total = 200 + 1.2816 × √800 = **236.2**.
The two agree only under perfect correlation.

**Mix scenario distributions; do not average their quantiles.** Scenario A (weight 0.7) spreads evenly over 80–120; scenario B (weight 0.3) over 40–60.
- Overall median: solve 0.3 + 0.7 × (x − 80) ÷ 40 = 0.5, giving x = **91.4**.
- The weighted mean is 0.7 × 100 + 0.3 × 50 = 85: a mean, not a median.
- Overall P10: solve 0.3 × (x − 40) ÷ 20 = 0.1, giving x = **46.7**, inside the downside scenario.

**Label every range.** Lowest-to-highest across scenarios is a **scenario envelope**, not an 80% interval. A P10–P90 needs a distribution, stated or derived. A sensitivity (one input varied, others fixed) is neither.
