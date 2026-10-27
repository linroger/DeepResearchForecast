# The Earnings-Carried Ascent and Its Fragility: An Institutional Forecast for the S&P 500 through December 31, 2027

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/sp500-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | The S&P 500 experiences a closing-basis drawdown of at least 20% from any closing peak between 1 October 2026 and 31 December 2027. | 30% | Resolves YES if any official S&P DJI daily close on or before 2027-12-31 is at least 20% below a prior closing peak set between 2026-10-01 and 2027-12-31 (source: S&P Dow Jones Indices daily closes). | ai | — |
| F2 | The S&P 500 — United States (fred:SP500) is at least 8,700 Index in December 2027. | 24% | Resolves YES if fred:SP500 >= 8700 Index in 2027-12 (source: FRED). Official resolution: fred:SP500 >= 8700 Index for 2027-12. | ai | 33% (n=104, h=15) |
| F3 | The S&P 500 official close on 31 December 2027 is above 7,662.54. | 65% | Resolves YES if the official S&P DJI closing level on 2027-12-31 (last trading day) is > 7,662.54 (the 2026-10-22 vendor close anchor; source: S&P Dow Jones Indices). | ai | — |
| F4 | The S&P 500 posts any official daily close at or above 8,700 at some point before 1 January 2028. | 40% | Resolves YES if any official S&P DJI daily close from 2026-10-23 through 2027-12-31 is >= 8,700 (source: S&P Dow Jones Indices daily closes). | ai | — |
| F5 | The Federal Funds Target Range - Upper Limit — United States (fred:DFEDTARU) is at least 4.25% in December 2027. | 50% | Resolves YES if fred:DFEDTARU >= 4.25 Percent in 2027-12 (source: FRED). Official resolution: fred:DFEDTARU >= 4.25% for 2027-12. | ai | — |
| F6 | The Real-time Sahm Rule Recession Indicator — United States (fred:SAHMREALTIME) reaches at least 0.50 percentage points at least once before 1 January 2028. | 15% | Resolves YES if any published monthly value of fred:SAHMREALTIME from 2026-10 through 2027-12 is >= 0.50 Percentage Points (source: FRED). | ai | — |
| F7 | S&P 500 calendar-2026 EPS growth comes in at least 30% when FactSet publishes full-year actuals in February 2027. | 75% | Resolves YES if FactSet Earnings Insight bottom-up actual CY2026 S&P 500 EPS growth >= 30% as reported in the February 2027 Earnings Insight (consensus was 32.8% on 2026-10-16; source: FactSet). | ai | — |
| F8 | S&P 500 calendar-2027 EPS growth comes in at least 10% when FactSet publishes full-year actuals in February 2028. | 60% | Resolves YES if FactSet Earnings Insight bottom-up actual CY2027 S&P 500 EPS growth >= 10% as reported in the February 2028 Earnings Insight (Oct 2026 consensus 15.8%; source: FactSet). | ai | — |
| F9 | Magnificent 7 Q4 2026 earnings growth comes in below the other 493 companies' growth when FactSet reports the quarter in February 2027 — the first Mag 7 underperformance since Q4 2022. | 55% | Resolves YES if FactSet Earnings Insight reports Q4 2026 blended YoY earnings growth for the Magnificent 7 < growth for the other 493 S&P 500 companies (consensus 23.6% vs 30.6%; source: FactSet Earnings Insight, February 2027). | ai | — |
| F10 | The FOMC raises the federal funds target range at its 27-28 October 2026 meeting. | 15% | Resolves YES if the Federal Funds Target Range - Upper Limit — United States (fred:DFEDTARU) is raised above 4% in 2026-10 (source: FRED; CME FedWatch priced 16.1% hike / 83.9% hold on 2026-10-21). | ai | — |
| F11 | The 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States (fred:T10Y3M) is below 0% in June 2027. | 12% | Resolves YES if fred:T10Y3M < 0 Percent in 2027-06 (source: FRED). Official resolution: fred:T10Y3M < 0% for 2027-06. | ai | 15% (n=111, h=9) |
| F12 | Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States (fred:CES0500000003#yoy) is at least 4.214% in June 2027, back above its five-year high. | 15% | Resolves YES if fred:CES0500000003#yoy >= 4.214 Percent change from year ago in 2027-06 (source: FRED). | ai | — |
| F13 | The top-10 share of S&P 500 index weight is at least 38% at end-2027, staying near its 2025 record of 40.7% despite the earnings-breadth broadening. | 50% | Resolves YES if the combined weight of the 10 largest constituents is >= 38% of the S&P 500 as of 2027-12-31 (source: S&P Dow Jones Indices constituent data / Top 10 factsheet). | ai | — |
| F14 | The largest US hyperscalers' capital expenditure for 2027 falls short of the $800 billion they are on track to spend in 2026 — an outright AI-capex contraction rather than further growth. | 25% | Resolves YES if aggregate reported FY2027 capex of the largest US hyperscalers (NVIDIA, Microsoft, Alphabet, Amazon, Meta as scoped by Goldman Sachs Research) is < $800 billion (the 2026 estimated run-rate, +94% over 2025; source: company filings aggregated in Goldman Sachs Research / FactSet). | ai | — |
| F15 | The S&P 500 (year-over-year % change) — United States (fred:SP500#yoy) falls below 0% in December 2027, i.e., the index posts a negative year-over-year price change at the horizon. | 20% | Resolves YES if fred:SP500#yoy < 0 Percent change from year ago in 2027-12 (source: FRED). | ai | — |

_15 forecasts; 9 high-conviction (≥70% or ≤30%); 15 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| S&P 500 — United States | Index | 7669.4143 | 2026-09 | +1085.3962 (+16.485%) | 3726.05 to 7711.3233 | 7750.4213 (2026-10, partial-period value) | [S2] |
| S&P 500 (year-over-year % change) — United States | Percent change from year ago | 16.485% | 2026-09 | -0.642 pp | -16.47% to 35.671% | 15.065% (2026-10, partial-period value) | [S10] |
| Central bank policy rates - United States - Monthly - End of period | Per cent per year | 3.875% | 2026-09 | -0.25 pp | 0.125% to 5.375% | — | [S25] |
| Smoothed U.S. Recession Probabilities | Percent | 0.62% | 2026-08 | -0.24 pp | 0.02% to 2.32% | — | [S13] |
| Real-time Sahm Rule Recession Indicator — United States | Percentage Points | 0 | 2026-09 | -0.23 | -0.37 to 0.57 | — | [S17] |
| Average Hourly Earnings of All Employees, Total Private — United States | Dollars per Hour | 37.81 | 2026-09 | +1.11 (+3.025%) | 30.98 to 37.81 | — | [S26] |
| Monthly Treasury Statement: Customs Duties (current month) — United States | U.S. dollars | 5910402249.78 (≈ 5.91 billion U.S. dollars) | 2026-09 | -23764551072.46 (≈ 23.76 billion U.S. dollars; -80.083%) | -25555668440.83 (≈ -25.56 billion U.S. dollars) to 31353501081.11 (≈ 31.35 billion U.S. dollars) | — | [S27] |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States | Percent | 0.896% | 2026-09 | +0.841 pp | -1.73% to 1.98% | 0.938% (2026-10, partial-period value) | [S18] |
| Federal Funds Effective Rate — United States | Percent | 3.75% | 2026-09 | — | 3.63% to 3.75% | — | [S28] |
| Federal Funds Target Range - Upper Limit — United States | Percent | 4% | 2026-09 | — | 3.75% to 4% | 4% (2026-10, partial-period value) | [S11] |
| Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States | Percent change from year ago | 3.025% | 2026-09 | -0.824 pp | 3.025% to 4.214% | — | [S29] |
| Federal Funds Effective Rate — United States | Percent | 3.747% | 2026-09 | — | 3.63% to 3.747% | 3.88% (2026-10, partial-period value) | [S30] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/sp500-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SP500>) [S2]; Index; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10Y3M>) [S18]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFEDTARU>) [S11]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SP500>) [S10]; Percent change from year ago; Monthly; NSA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S25]; Per cent per year; Monthly; adjustment unknown · [U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)](<https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/>) [S27]; U.S. dollars; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/RECPROUSM156N>) [S13]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SAHMREALTIME>) [S17]; Percentage Points; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CES0500000003>) [S26]; Dollars per Hour; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/FEDFUNDS>) [S28]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CES0500000003>) [S29]; Percent change from year ago; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFF>) [S30]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_mrcdmtladtppbctr.html -->
![Official Series History and Forecast Thresholds](demos/sp500-2027/charts/official_series_mrcdmtladtppbctr.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SP500>) [S2]; Index; Monthly; NSA*

<!-- viz:charts/official_series_oaefafronmbbacta.html -->
![Official Series History and Forecast Thresholds](demos/sp500-2027/charts/official_series_oaefafronmbbacta.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10Y3M>) [S18]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_lfbrtnalcapaqdpa.html -->
![Official Series History and Forecast Thresholds](demos/sp500-2027/charts/official_series_lfbrtnalcapaqdpa.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFEDTARU>) [S11]; Percent; Monthly; NSA*

## Part 2 — Framework & Synthesis

### Framework and Synthesis

This synthesis defends those numbers.

### The Analytical Logic: Earnings Carry, Valuation Con strains

Three forces dominate. This is why the modal outcome is a higher index, not a lower one.

Second, the valuation constraint: a trailing P/E above 22 for nearly three years means multiple expansion is largely exhausted as a return source. [S9] The reference class is genuinely small, which is why base rates are treated as a starting scaffold rather than a verdict.

That divergence is the tug of war: earnings up, rates up. It compresses the room for multiple expansion in every scenario and is the main mechanism converting macro news into drawdown risk.

### Why 30% for a 20%+ Drawdown

Unconditionally, the S&P 500 has experienced 13 closing-basis bear markets since 1929 — roughly one every seven years [S55].

Labor income growth is decelerating, not collapsing: average hourly earnings rose 3.025% year over year in September 2026, down 0.824 points [S29].

### Defending the Scenario Probabilities

Breadth improving is bullish; dependence on two names is not.

This is the most historically typical expression of a 26x trailing multiple working off excess while earnings keep growing.

These five scenarios are mutually exclusive and exhaustive, and their weights are the arithmetic backbone of every binary forecast in Part 1.

### The Fragility Ledger

Four frictions shape propagation speed rather than direction. a mega-cap de-rating passes one-for-one through index weight.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Baseline: Where the Market Stands and What Is Already Priced In

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/sp500-2027/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

### The As-Of Level: A Small Disagreement That Matters for Resolution Mechanics

Any forecast anchored to a specific closing level must first confront an uncomfortable fact: the vendors do not agree on where the index closed on the very day of the research snapshot.

These discrepancies are not trivial bookkeeping. Every scenario-resolution criterion in this report therefore names its source of record in advance: closing levels resolve against the official S&P Dow Jones Indices close as reported by the primary data vendors (WSJ/FRED), and monthly reference values resolve against the FRED monthly-mean series.

The realized return record reinforces how extended the starting point is. Total returns were +25.02% in 2024 and +17.88% in 2025, with 2026 running +12.38% year-to-date at the time of the snapshot [S22].

### Valuation: Which P/E You Quote Determines How Scared You Should Be

The trailing as-reported P/E stood at 26.15 per the Multpl series [S4], and it has been above 22 continuously since January 2024 [S4] — a nearly three-year residence in what historical standards treat as expensive territory. But the definitional dispersion across vendors is wide and directionally important:

- Multpl: 26.15 on GAAP as-reported earnings [S4]

it is a definitional difference between blended trailing-actual and GAAP as-reported earnings bases. The forward P/E tells a calmer story: near 19, reflecting the market's expectation of steep near-term EPS growth. [S6] If the FactSet consensus path disappoints, the forward multiple is no cushion; it simply converges upward toward the trailing multiple as estimates fall.

That survival record is exactly what makes the current setup fragile; the reference class says most high-multiple episodes end fine, but not all of them do, and the market has now been in the risky class for a record stretch.

### The Earnings Consensus: What Is Priced In and Who Provides It

FactSet Earnings Insight anchors the consensus: blended Q3 2026 earnings growth of 29.0% — a third consecutive quarter above 25% — with CY2026 calendar-year growth consensus at 32.8% and CY2027 at 15.8% [S6].

Two structural facts about this earnings picture deserve emphasis at the baseline stage, because every later driver builds on them.

The dollar-EPS estimates carry their own definitional fog, worth fixing now because Chapter Twelve resolves binary forecasts against them. This report treats the FactSet Earnings Insight publications as the source of record for consensus-growth resolution [S6][S8], with the caveat that vintage and definition shifts of 2-3% in dollar EPS are routine.

### The Official-Indicator Dashboard: A Quiet Macro Beneath a Loud Market

While equities price an AI-driven earnings boom, the official macro series stored in this report's snapshot describe an economy close to textbook-neutral — and that quietness is doing a great deal of work in the scenario probabilities assigned later.

- **Labor market:** The real-time Sahm Rule recession indicator reads 0 percentage points for September 2026, at the 47th percentile of its trailing window, having fallen 0.23 points over the year [S17]. The smoothed recession probability is 0.62% for August 2026, versus a 2.32% window high in January 2024 [S13].
- **Yield curve:** The 10-year minus 3-month Treasury spread is +0.896% for September 2026, steeply positive, with a latest daily reading of 0.78% on 2026-10-23 — nowhere near the inversion that historically precedes recessions.
- **Policy rate:** The federal funds target-range upper limit is 4.0%, after the FOMC's unanimous 25bp September 2026 hike [S11]; the BIS end-of-month policy rate series reads 3.875% [S25].

These are projections and market prices, not observed values, and this report's judgments depart from each where reasoned — but they mark the boundaries of the defensible range.

### What Is Priced In: Framing the Forecast's Core Tension

The chapters that follow decompose this tension: Driver One tests whether the earnings engine broadens or narrows; Driver Two quantifies what elevated starting multiples have historically delivered; Drivers Three and Four map the Fed's path and the concentration-margin-tariff fragility ledger.

## Key Official Indicators: What the Stored Series Imply for the Forecast

The stored official series form the skeleton of this forecast: they fix where the index, policy rates, labor market, yield curve, wages and tariffs actually stood as of late October 2026, and they define the verifiable thresholds at which the scenario probabilities in later chapters would have to move.

### The Index and Its Momentum Base

The year-over-year change on the same series is +16.485% [S10]. Two structural facts matter beyond the level itself. Second, the five-year stored range runs from 3,726.05 (October 2022) to 7,711.3233 (August 2026) [S2], meaning the index has more than doubled off its window low in four years without a single 20% closing-basis breach in that span — a reminder that long uninterrupted advances are exactly the conditions under which concentration and valuation risks accumulate silently.

conditioning on valuation shifts the distribution downward, as Chapter 4 quantifies.

### Policy Rates: The Tightening Bias in the Stored Numbers

Three observations follow.

First, the five-year range of the upper limit is only 3.75% to 4% [S11]: policy has been moving in quarter-point steps at the bottom of a newly constructed range. A central bank that has just hiked unanimously, with near-zero recession signals, retains room to hike again — this is why the report treats the rates channel as the primary conversion mechanism from the melt-up scenario into the bear-market scenario.

Second, the market-policymaker divergence is wide and measurable.

Third, the immediate binary is defined on the stored series itself: any policy forecast in this report resolves on the FRED target-range upper limit [S11].

### Recession Signals: Three Models Measuring Three Different Objects

The recession-indicator complex is the most misunderstood part of the dashboard because its components measure different things. The smoothed U.S. recession probability — a contemporaneous state estimate — reads 0.62% for August 2026, down 0.24 pp year over year, against a five-year window high of just 2.32% set in January 2024 [S13]. The real-time Sahm rule indicator reads 0 percentage points for September 2026, down from 0.23 a year earlier, with a five-year high of 0.57 (August 2024) [S17]. Both are labor-market state measures, and both are as quiet as they have been at any point in the stored window.

The yield curve itself is the swing input. The 10Y-3M spread averaged +0.896% in September 2026, up 0.841 pp year over year, with the latest daily value at 0.78% on 2026-10-23. A steeply positive curve is why both Fed-bank models read low.

a smoothed recession probability sustained above its 2.32% window high [S13] would mark recession onset consistent with the bear scenario; Each resolves on the named FRED series with monthly frequency and roughly one-month publication lags.

### Wages and Tariffs: The Margin-Squeeze Channels in the Data

Cooling wage growth is currently a margin tailwind, not a headwind.

The tariff channel is more distorted, and the stored series shows why. This is not a collapse in actual tariff policy; Forecast consumers should treat the customs-duties line as noise through the refund window and anchor on the effective-rate estimates instead.

### What the Dashboard Implies for the Two Forecast Questions

The dashboard also defines the falsification sequence. 0.50 pp confirms); Each threshold is a pre-registered trigger, each resolves on a named official series, and each maps to a specific scenario transition quantified in the chapters that follow.

One caveat belongs on the record. All scenario resolutions in this report therefore settle on S&P Dow Jones Indices official closing values, with the FRED monthly series used for distributional analysis; Chapter 1 addresses these discrepancies in full.

## Driver One: The Earnings Path and the Breadth Question in AI Capex

At those multiples, the market is not being carried by valuation expansion; it is being carried by earnings.

### The headline: three quarters above 25%, and what holds it up

FactSet's blended Q3 2026 earnings growth stands at 29.0% as of 16 October 2026 (29.2% at the 30 September start of the quarter), a third consecutive quarter above 25%. [S8] By any historical standard this is an exceptional run: the index has just posted three quarters of growth at rates that in most cycles would mark a peak.

The decisive fact, however, is what happens when two companies are removed. Nine percentage points of index-level earnings growth — nearly a third of the entire print — comes from two semiconductor firms. This is not a criticism of either company; it is an accounting statement about where index earnings growth is being minted. The mechanism matters for the forecast: memory cycles are among the most violent in technology, and a boom that multiplies EPS eleven-fold in a year is, by the nature of the industry, priced by investors with a short half-life.

The margin picture carries the same signature of concentration.

### The breadth question: the Mag 7 handoff to the other 493

The most constructive data point in the entire earnings file is at the Mag 7 boundary.

This is precisely the observable that separates the report's scenario families.

There is a genuine debate here, and it deserves steelmanning. Both can be true simultaneously — earnings growth can broaden (Guinness) while the index's price exposure to a mega-cap de-rating remains one-for-one (RBC). The forecasting consequence is asymmetric: broadening earnings growth caps the downside scenarios but does not reduce the drawdown probability much, because a top-10 multiple compression passes through index weight directly and is amplified by passive flows [S9]. Chapter 6 develops the concentration ledger in full; the point for this chapter is that earnings breadth is necessary but not sufficient for the bull path.

### The capex engine: $800 billion, plus or minus $200 billion of dispute

Underneath the earnings numbers sits the largest capital-expenditure cycle in corporate history, and its size is itself disputed at the source. NVIDIA's chief executive, Jensen Huang, has separately claimed $600 billion in annual hyperscaler capex — a figure The Cube Research explicitly flags as unvalidated by the leading hyperscalers [S33]. it defines the perimeter of the AI-dependence problem. If Goldman's broader perimeter is right, "almost half" of index EPS growth rides on a spending base that must keep compounding; Either reading leaves the transmission chain intact: hyperscaler capex buys AI silicon from NVIDIA (Microsoft, Alphabet, Amazon and Meta are all NVIDIA customers) and memory from Micron, whose revenues and margins then flow back into index EPS with a multiplier, since both companies carry enormous operating leverage.

The consensus, in other words, has not fully priced the deceleration that the capex arithmetic makes nearly unavoidable.

That makes the decisive mid-2027 observable hyperscaler 2027 capex guidance, issued by Microsoft, Alphabet, Amazon and Meta in their Q4 2026–Q1 2027 earnings reports, with NVIDIA's own guidance as the aggregator of demand.

### The accounting tail: $150 billion of unrealized private-company gains

These gains — mark-ups on venture and private holdings sitting on balance sheets, disproportionately at mega-caps with large investment portfolios — are not operating earnings.

The magnitude is scenario-defining. Twelve percent of a quarter's EPS is roughly three percentage points of annual growth if it merely flattens, more if it reverses. the private-gains fade is the most concrete mechanism that could repeat it.

When the most constructive forecaster in the file is also the source of the fade math, the market has little excuse for being surprised by it.

### The decisive observables and their thresholds

This chapter therefore fixes four falsifiable checkpoints, each anchored to a named publisher and each capable of moving the scenario distribution materially:

1. **Ex-Micron/NVIDIA blended growth** — FactSet publishes this decomposition quarterly. Threshold: any FactSet Earnings Insight publication in 2027 showing ex-Micron/NVIDIA blended growth below 10% would shift probability mass from the melt-up scenario to the bear scenario.

### Synthesis: what the capex evidence does to the skeleton probabilities

The evidence assembled here is what assigns the skeleton's probability weights. History, as Chapter 4 quantifies, says the downshift combination produces a double-digit correction far more often than a bear market;

## Driver Two: Valuation Mean-Reversion Base Rates from Elevated Multiples

— is not primarily a question about this cycle's idiosyncratic features. It is, first, a question about what has historically happened to equity markets that entered multi-year windows from trailing P/E multiples above 22. [S9] The reconciliation runs through the labor market, not through optimism.

### The Reference Class: What P/E >22 Starts Have Actually Produced

This is not a borderline case: the market has spent nearly three years in a valuation regime that, historically, has been rare and dangerous.

Two reasonable adjustments to that base rate cut in opposite directions. The honest summary is that from this starting valuation, roughly one-third to two-fifths of historical windows saw a 20%+ closing-basis drawdown within two years — with the small samples a genuine limitation, since four to seven observations is thin support for any point estimate. [S55]

The unconditional base rate is lower but not negligible: since 1929 the S&P 500 has experienced 13 closing-basis bear markets (declines of 20% or more without a subsequent 20% advance), roughly one every seven years [S55].

### The Asymmetry: Two-Year Returns Are Usually Positive Anyway

Here is the strongest argument against the bear case, and it deserves to be stated at full strength. The same elevated-multiple reference class that produces a 1-in-4 to 2-in-5 drawdown frequency also produces strikingly benign two-year *returns*. In other words, the historical record from expensive starting points contains almost no instance of a materially negative two-year return — because the one 20%+ drawdown in the modern sample, the 2022 bear, began from the January 2022 peak and largely recovered by the time the two-year window closed. [S55]

The mechanism behind this asymmetry is well documented in drawdown-recovery research: deep drawdowns without a recession trigger are historically rare, while double-digit corrections are routine features of even the strongest bull markets. High-multiple regimes compress the *distribution of multiples* — they make de-rating possible — but a de-rating of the magnitude needed for a -20% index decline has almost always required a earnings recession, a policy shock, or both, to supply the fundamental deterioration. [S55]

That is the precedent this report takes most seriously for 2026-2027: a path in which the multiple de-rates meaningfully, the index goes essentially nowhere for two years on a price basis, and the 20% threshold is approached or briefly breached without a recession ever arriving. [S55]

### Why 30% and Not 33-40%: The Labor-Market Discount

The discount rests on the current state of the recession-precursor indicators, because the historical record says elevated multiples rarely convert into 20% declines without a fundamental trigger, and every stored trigger series currently reads benign: [S55]

- The real-time Sahm Rule recession indicator stands at 0 percentage points for September 2026, against a five-year window high of 0.57 [S17].
- The smoothed US recession probability is 0.62% for August 2026, down 0.24 points year over year, against a window high of 2.32% [S13].
- The 10-year minus 3-month Treasury spread is +0.896% (September 2026 monthly; [S18]

### What the Base Rates Imply for the Return Distribution

Three specific implications follow for the scenario architecture that later chapters build.

Third, and most important for calibration: the base rates say double-digit corrections are the *norm* from this starting valuation, not the exception. The valuation regime guarantees turbulence; only the fundamental indicators determine whether turbulence becomes a bear market. That division of labor between valuation base rates and real-time signals is the analytical core this report carries into the Fed-path chapter that follows.

## Driver Three: The Fed's Path, Recession Odds, and the Rates-Multiples Tug of War

### A Tightening Fed at 4%, With Three Incompatible Paths Priced

The baseline policy setting is a Federal Reserve that has just moved, not paused, in a hawkish direction. Stored official data confirm the setting: DFEDTARU stands at 4% as of 2026-09 and 2026-10-23, with a five-year window range of 3.75% (2026-06) to 4% (2026-09) [S11]; the effective rate averaged 3.747% in September and printed 3.88% daily on 2026-10-22 [S30]; BIS end-of-month data show 3.875% for September 2026, down 0.25pp year over year [S25].

What makes this cycle distinctive is the three-way divergence in what happens next:

1. Note that the SEP median sits *above* the current target, implying the committee's center of gravity still leans toward one more move.
3. **The dealer community**: the SIFMA economic survey shows a majority of its dealer panel expecting the *next Fed move to be a cut* [S57]—positioned on the opposite side of both the SEP and the curve.

This triangulation matters because each path implies a different equity regime.

### Recession Models Disagree—Because They Measure Different Things

- **The contemporaneous state**: smoothed US recession probability reads 0.62% for August 2026, down 0.24pp year over year, against a five-year window high of just 2.32% (January 2024) [S13]. The real-time Sahm rule indicator is at 0.0 percentage points for September 2026, down from 0.23 a year earlier and against a window high of 0.57 [S17].
- **Forward-looking term-spread models**: the New York Fed's Treasury-spread model puts 12-month-ahead recession probability at 0.28 for 2026 and 0.15 for 2027—explicitly disclaimed by the New York Fed as not official forecasts [S14].

Average hourly earnings growth has *decelerated* to 3.025% year over year, the bottom of its five-year range and far below the 4.214% high of March 2025 —the opposite of the wage-price dynamic that would force a more aggressive Fed.

Because the reference class is valuation, not recession.

### The Steelman: Why the Doves Could Be Right

The strongest counterargument to this chapter's hawkish-conversion thesis deserves full weight. Wage growth at 3.025% and falling [S29] removes the classic rationale for further tightening. if genuine, it would represent a dovish minority view inside the committee.

Central banks do not typically reverse unanimous tightening decisions within two quarters absent a growth shock—and a growth shock sufficient to force that reversal is itself the hard-landing trigger. The dovish path and the recession path share a doorway. That structural coupling is a core reason the scenario probabilities are assigned as they are.

### The December 2026 Meeting as the Pivot

Three outcomes partition the scenario space:

3. Chapter 6 develops the concentration multiplier; here the point is sequencing: a hawkish December SEP would likely hit *before* any earnings disappointment is observable, meaning the drawdown would begin from a position of earnings strength—the most confusing and violent configuration for trend-following capital.

### Monitoring Thresholds and Scenario Consequences

The observable thresholds that would reweight this chapter's conclusions, each anchored to a stored official series:

- report probability 25%.
- **T10Y3M inverting below zero** [S18] from +0.896%: the classic 12-month leading signal, currently far from trigger.

In sum, the rates question does not determine whether earnings deliver—Chapter 3's evidence suggests they will, at least through 2026. [S47] It determines what the market will *pay* for delivered earnings. Confidence in this chapter's rate-path judgments is low, consistent with the report's overall calibration: the futures-SEP gap may partly reflect term premia, the unconfirmed lower SEP median remains unresolved, and the as-of data landscape carries the vendor discrepancies documented in Chapter 1. The probabilities above are this report's estimates, not observed facts, and they are constructed to be revised at each dated checkpoint the calendar supplies.

## Driver Four: Concentration, Margins, Wages, and Tariffs — The Fragility Ledger

The first three drivers of this forecast — earnings, valuation base rates, and the Fed — describe forces that could push the S&P 500 either way. [S6] This chapter assembles the ledger of structural frictions that work mostly in one direction: they do not by themselves cause a bear market, but they determine how fast and how far any shock propagates. Four entries dominate the ledger: record index concentration, margins at a cyclical high with visible pressure points, a wage-growth channel that is currently benign but asymmetric, and a tariff regime whose fiscal signals are actively distorted by refunds.

### The 40.7% Problem: Concentration as a Shock Multiplier

RBC Wealth Management's "Great Narrowing" analysis documents the decade-long divergence: an index once viewed as a balanced cross-section of the US economy has become a leveraged bet on a handful of mega-cap technology balance sheets [S9].

The index's two largest earnings contributors sit inside or adjacent to the same AI-capex complex that drives the top-10 weight. [S9] A disappointment in AI silicon therefore hits the index twice — once through NVIDIA's own earnings, once through the hyperscaler customers (Microsoft, Alphabet, Amazon, Meta) whose capex plans anchor their guidance. Concentration of weight, concentration of growth, and concentration of earnings quality all point at the same ten names.

There is a serious counterargument, and it deserves a fair hearing. Guinness Global Investors argues that rising concentration "was rational" because mega-cap earnings dominance justified mega-cap weight — and that this dominance is "now fading" as earnings growth converges between the largest stocks and the rest [S46].

This report treats the Guinness view as the bull-case mechanism rather than a refutation of the risk.

### Margins at the Top of the Cycle

Q2 2026 delivered 15.7%;

The margin ledger has two live cost lines. The first is labor: average hourly earnings rose 3.025% year over year in September 2026, down 0.824 percentage points from a year earlier and at the bottom of the five-year stored range of 3.025% to 4.214% [S29]. Wage growth is falling — a tailwind for margins and a signal of a cooling, not overheating, labor market. A single indicator would then be squeezing margins and multiples at once.

The second cost line is tariffs. These are input costs that flow into COGS with a lag; the sectors most exposed — retail and consumer-facing businesses, with Amazon the index-relevant example — face the wage channel and the tariff channel simultaneously.

### The Distorted Tariff Fiscal Signal

The tariff line of the ledger carries a second-order problem: the data themselves are unreliable.

For the forecast, this matters in two ways. First, fiscal-policy signals are noisy: Treasury receipt data cannot be read cleanly for the real state of trade, which raises the odds of a policy error in either direction — Congress and the President adjusting tariff schedules based on distorted revenue prints. Second, the refund overhang is a latent margin event: if refunds of roughly $165bn are ultimately paid out, the effective tariff burden on corporates falls and margins get a one-time relief; The uncertainty itself — a $100bn+ spread between gross and net estimates on a single policy line — is a reason to widen rather than tighten the probability bands on the downside scenarios.

### How the Frictions Compound in the Downside Scenarios

Individually, none of these ledger entries is fatal.

**The bear-market sequence runs through concentration.** passive outflows amplify the move; The frictions do not cause the drawdown — the de-rating of ten names does — but each one removes a cushion that would otherwise arrest it.

**The hard-landing sequence adds the labor-market and policy channels.** At that funds rate, the multiple compression documented in Chapter 4 combines with a genuine earnings recession; margins take the wage and tariff cost lines simultaneously; and refund-distorted fiscal signals — September customs duties down 80% to $5.91bn on mechanics rather than trade [S27] — complicate any fiscal or tariff-policy response, making the decline steeper and the recovery slower than the historical average of roughly one bear market per seven years would suggest.

The ledger does not predict that the frictions fire; it states that if any one of them does, the other three are loaded.

## Scenario Forecast I: AI-Driven Reacceleration — 24% Probability

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/sp500-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

### The Earnings Engine: Why the Consensus Path, If Realized, Gets the Index There on Its Own

The arithmetic of this scenario begins with the earnings consensus. FactSet Earnings Insight's bottom-up consensus as of mid-October 2026 projects +32.8% earnings growth for calendar 2026, +28.6% for Q4 2026, and +15.8% for calendar 2027 [S6].

This is why the scenario's definition permits stable-to-slightly-higher multiples: it does not require multiple expansion as an act of faith, only that the trailing multiple compresses through earnings growth rather than price decline.

The breadth evidence is the scenario's most distinctive and most recent supporting fact. For this scenario, that crossover is not a curiosity; it is the load-bearing wall.

The recession dashboard, quiet as it is, provides the macro permission slip. The real-time Sahm rule stands at 0 percentage points for September 2026, at the bottom of its five-year range [S17]; smoothed US recession probabilities were 0.62% in August 2026, near the bottom of the stored window and down 0.24 points year over year [S13]; the 10-year minus 3-month Treasury spread is +0.896% for September 2026, steeply positive and up 0.841 points from a year earlier [S18]; and the NY Fed's Treasury-spread model averages just 0.15 recession probability for 2027 (an estimate the NY Fed itself disclaims as a forecast) [S14].

### Why the Probability Is Capped at 24%: The Three Structural Hands on the Ceiling

the labor market shows zero recession signal across every official indicator [S17]; consensus expects double-digit growth two years forward; The answer lies in three structural constraints that earlier chapters established and that this scenario cannot assume away.

First, the valuation starting point.

Second, the earnings-quality and AI-dependence problem sits inside the consensus itself. NVIDIA's CEO claims $600 billion in annual hyperscaler capex, a figure flagged as unvalidated by the leading hyperscalers [S33] — a reminder that the bull case's capex leg rests partly on projections the buyers have not confirmed.

Third, the policy path is not this scenario's friend. Every additional hike tightens the multiple constraint: this scenario needs stable-to-higher multiples precisely while the market prices a rising terminal rate. A hike in late October, or a hawkish December SEP revision, converts probability mass from this branch toward the melt-up-then-correction and bear-market branches.

the modal version of "earnings deliver" belongs to the melt-up-then-correction branch, not this one.

### Resolution Criteria and the Falsification Ledger

and (3) the smoothed recession probability series does not indicate a recession over the horizon (which would reassign the outcome to the hard-landing branch). It resolves as FALSE if any one of those conditions fails, with the specific failing condition determining which sibling scenario inherits the probability mass.

Four observable falsification triggers would kill this scenario before the horizon, each anchored to a verifiable source of record:

- A sustained revision below roughly +10% at any 2027 publication — resolving on FactSet Earnings Insight [S6][S8] — falsifies the earnings-carried mechanism, since at 19x forward the index cannot reach 8,700 on single-digit EPS growth without a multiple this scenario does not permit.
- **Mag 7 re-domination of earnings growth.**
- A fred:SP500 daily close 20% below any 2026–2027 closing peak mechanically terminates this scenario regardless of the endpoint, transferring the resolution to the bear-market or hard-landing branch depending on the behavior of RECPROUSM156N. [S55]

The monitoring sequence follows directly. and the monthly Sahm and smoothed-recession-probability releases police the macro boundary.

## Scenario Forecast II: Melt-Up Then Mid-Horizon Correction — 28% Probability (Most Likely)

The modal path this report assigns the highest single probability to is not a clean bull run and not a bear market.

### Why the overshoot happens first

The mechanical case for the overshoot leg rests on the gap between where the index stands and where the most prominent sell-side forecast already points. This is the analytical tension that seeds the melt-up: the trailing multiple is historically expensive while the forward multiple looks average, and the reconciliation is entirely dependent on the earnings in the denominator actually arriving.

The earnings have, so far, been arriving at extraordinary rates. The first three quarters of 2026 mark the third consecutive quarter above 25% growth. When a market is carried by earnings of this magnitude and the forward multiple screens as average, the path of least resistance for capital allocation — particularly through the passive channels RBC Wealth Management documents as amplifying flows into the largest weights [S9] — is toward the index high end of analysts' targets. momentum regimes historically overshoot such targets before the fundamentals that justify them are tested.

The concentration structure pushes in the same direction. A melt-up built on this footing is, by construction, a melt-up with a sell-by date.

### Why the correction follows — and why it stops short of 20%

The mid-horizon correction in this scenario has three converging causes, each independently documented in the research base.

**First, the earnings-quality fade.** Oxford Economics' 2027 outlook independently names a disorderly end to the AI boom as a principal risk [S58]. Markets price the second derivative;

**Second, the discount-rate squeeze.**

**Third, the base rate itself.** Since 1929 the S&P 500 has experienced 13 closing-basis bear markets, roughly one every seven years [S55] — an unconditional frequency far below one per two-year window. Morgan Stanley's drawdown-and-recovery base-rate research reinforces the shape: double-digit drawdowns are the routine tax on equity ownership, while full bear markets are the exception that generally requires a recession or systemic shock.

The benign labor data is what keeps the correction in this scenario capped below the bear threshold. The real-time Sahm rule stands at 0 percentage points for September 2026 [S17]; the smoothed recession probability is 0.62% for August 2026, near the bottom of its five-year range [S13]; and the 10Y–3M spread is +0.896% for September 2026, positive and un-inverted [S18].

### Steelmanning the alternative readings

Two objections deserve direct engagement.

### Resolution and falsification

**Resolution criteria.** The scenario resolves YES if and only if: (a) the official S&P 500 closing level on the last trading day of 2027 (S&P Dow Jones Indices;

**Falsification conditions.** Any of the following falsifies the scenario: a closing drawdown of ≥20% at any point in the window (resolves the bear or hard-landing branches instead); [S55]

**Confirming observables, in sequence.** a hike begins compressing the overshoot immediately. outright cuts from two or more names flip the path to the bear branch.

The melt-up-then-correction path is the most likely single branch not because it is the most dramatic but because it demands the least of the world: earnings need only decelerate on schedule, the Fed need only stay divided with the market, and the labor market need only stay quiet — while every one of those conditions, if it breaks cleanly in either direction, hands the outcome to one of the four adjacent scenarios.

## Scenario Forecast III: Bear Market and 20%+ Drawdown Without Recession — 22% Probability

This is the AI-disappointment path, the valuation-shock path, and the concentration-amplifier path rolled into one branch.

### The Anatomy of a Recessionless Bear Market

The defining condition of this scenario is that the drawdown is driven by a repricing of earnings expectations and equity multiples, not by an economic contraction. The historical record supports the plausibility of this configuration. There have been 13 closing-basis bear markets since 1929, roughly one every seven years [S55].

Each of these is a standalone risk. Their interaction is the scenario.

### Trigger One: The Capex Guidance Cliff

The arithmetic of dependence is stark.

The credibility problem sits at the centre of the trigger. NVIDIA's chief executive has publicly claimed $600 billion in annual hyperscaler capex [S33] — a figure flagged as unvalidated by the leading hyperscalers themselves [S33]. A capex miss combined with an elevated multiple is what converts a correction into a bear market.

The timing window matters. Two simultaneous earnings-quality hits — capex deceleration and private-gains fade — arriving in the same quarter is the configuration this branch requires.

### Trigger Two: The Hawkish December Surprise

The second channel is monetary. One of these two paths is wrong. each 50 basis points of discount-rate repricing, holding earnings fixed, mechanically removes several percent of fair value. [S47]

The mechanism runs: a hawkish December SEP pushes the 10-year yield higher, compressing multiples on the mega-caps, whose weights are at record concentration [S9]; passive-index flows, which cannot discriminate, sell the whole index in proportion; the drawdown deepens without any change in real economic activity.

### The Concentration Multiplier and the Steelman Against This Scenario

The honest counter-argument deserves full weight. Guinness Global Investors argues that mega-cap earnings dominance is "now fading" precisely because the rest of the index is catching up.

Three counterweights nonetheless keep the probability high. The Guinness convergence thesis and the RBC concentration thesis are, in fact, the same fact read in opposite directions — and the RBC reading is the one that matters for drawdown probability.

### Distinguishing This Branch from Hard Landing and Melt-Up Correction

The boundaries are operational, not rhetorical:

- Employment, wage growth (currently 3.025% and decelerating [S29]), and consumption stay intact; the damage is confined to financial conditions and the equity risk premium.

### The Observable Confirmation Sequence to Mid-2027

5. drawdown-recovery research documents that market bottoms and bounces cluster at extreme volatility.

### Why 22%, Precisely

The probability is a base rate adjusted for case specifics. The remaining 22 points belong here: enough to demand hedging attention at current concentration, and not so much as to dismiss the earnings momentum that still carries the modal path. [S37] everything else in the sequence is downstream of it.

## Scenario Forecast IV: Hard-Landing Recession — 8% Probability; and V: Stagnant Sideways Grind — 18%

The two scenarios in this chapter occupy the lower and middle reaches of the probability distribution, but they are not the same kind of object. One is a crash; the other is an erosion.

### Scenario IV: The Hard-Landing Recession — 8% Probability

**Resolution criteria.** This scenario resolves as true if, and only if, either of two verifiable conditions is met: (1) the National Bureau of Economic Research declares a US recession with a business-cycle peak falling between October 2026 and December 2027; [S52] The second condition exists because NBER declarations arrive with long, variable lags;

**Why 8% and not more.** The case for a higher number rests on respectable evidence. Polymarket's "US recession by end of 2026?" [S42]

The real-time Sahm rule indicator stands at 0 percentage points for September 2026, having fallen 0.23 points year over year from an already-benign reading [S17]. The smoothed recession probability of 0.62% sits near the bottom of its charted range, down 0.24 points from a year earlier [S13]. The 10-year minus 3-month Treasury spread averaged +0.896% in September 2026, up 0.841 points from +0.055% a year earlier — the curve has spent the last year re-steepening, not inverting. The NY Fed's term-spread model, which the bank itself disclaims as a forecast, averages just 0.15 recession probability for 2027 [S14]. For the hard landing to materialize, all of these benign readings would have to break within roughly fourteen months, or be overridden entirely by a shock that bypasses the labor-market channel the Sahm rule monitors.

Because the indicators disagree about what they measure, and only one of them is close to the right object. the smoothed 0.62% measures the contemporaneous state; [S13] and Polymarket prices a market-clearing event contract with its own liquidity and attention biases. None of these is a fourteen-month-forward recession probability conditioned on a tightening Fed and a concentrated AI-capex cycle. What keeps it below the Cleveland Fed number is the absence in the evidence base of any credit-stress, bank-failure, or commercial-real-estate event large enough to serve as the exogenous trigger; zero Sahm, a positively sloped curve, and decelerating wage growth at 3.025% year over year against a 4.214% window high [S29] is the configuration in which post-war recessions did not begin without one.

**The transmission channels that could still do it.** The scenario is not unthinkable, and its most plausible route runs through policy rather than through the gradual deterioration the recession models watch. That divergence matters: if the market-implied path prevails, the economy absorbs a full percentage point of additional tightening beyond the Committee's own projection.

The second channel is an AI-cycle shock with credit amplification. Oxford Economics' 2027 outlook names a disorderly end to the AI boom as a principal risk [S58].

**Market anatomy of the hard landing.** If it comes, the drawdown is amplified by structure.

### Scenario V: The Stagnant Sideways Grind — 18% Probability

**Resolution criteria.** and (3) the calendar-year 2027 price return is near zero. [S55] It is mutually exclusive with all four other scenarios by construction — it is defined as everything that is neither a new-high breakout (Scenario I), nor a melt-up-with-correction that ends higher (Scenario II), nor any 20% breach whether or not a recession follows (Scenarios III and IV). [S55]

**The economics of going nowhere.** The grind is the multiple-compression-without-crisis equilibrium.

**Why 18%.** But the residual is not arbitrary; it has independent economic content.

**What would falsify each scenario.**

## Most-Likely Trajectory and the Decision Calendar of Turning Points

The core argument is that the forecast is not a smooth glide toward a number; it is a sequence of a small number of identifiable gates, each of which can shift probability mass between scenarios in discrete jumps rather than continuously.

### The Most-Probable Quarterly Path to December 2027

The modal outcome — a hold — removes the nearest hawkish risk without changing the trajectory.

If that prediction materializes, it confirms the broadening that the reacceleration scenario requires; This is the quarter in which the melt-up scenario's overshoot phase completes.

Three mechanical forces converge here.

### The Decision Calendar: Dated Gates and Probability-Shifting Thresholds

The trajectory above is best used not as a point forecast but as a schedule of gates. Each gate has a date, a resolving source, and a pre-specified threshold at which scenario probabilities should be revised. The report's scenario weights are conditional on passing these gates; a gate failure does not merely change the destination, it changes the probability distribution itself.

resolution on the target-range upper limit (fred:DFEDTARU, currently 4% [S11]). A hold leaves the modal path unchanged.

The decisive observable for the AI question. Note the definitional dispute: NVIDIA's CEO has claimed $600 billion in annual hyperscaler capex, a figure flagged as unvalidated by the leading hyperscalers themselves [S33] — guidance from Microsoft, Alphabet, Amazon and Meta is the authoritative signal, not supplier-side claims.

this meeting is the highest-density policy gate of the horizon because it resolves, or deepens, the futures-versus-SEP divergence that currently straddles the entire scenario distribution.

the 10Y-3M spread at +0.896% and its inversion [S18]; and average hourly earnings at +3.025% YoY against a retest of the 4.214% window high [S29].

**Gate 6 — FactSet CY2027 consensus revision trajectory, each publication.**

### What Would Invalidate the Modal Path

Two steelman objections deserve direct answers. First, that the mid-2027 air pocket is invented — that earnings momentum of three consecutive 25%+ quarters simply continues. The counter is the state of the labor market and curve: with Sahm at zero, smoothed recession probability at 0.62% and the curve positively sloped [S13], the historical pattern is that high-multiple starts rarely produce negative two-year returns without a recession trigger, and no such trigger is currently observable.

The decision calendar above is the operational form of the forecast — the dates on which this report's probabilities should be re-examined against evidence, and the thresholds at which they should move.

## Ten-Plus Binary Forecasts with Probabilities and Resolution Criteria

Each carries a probability, a precise resolution mechanic, and a named source of record. Where a probability is derived from a market price (FedWatch), a publisher consensus (FactSet), or an official model (NY Fed, Cleveland Fed), the anchor is cited; where it is this report's own judgment, it is labeled as such.

This is the AI-driven reacceleration scenario of Chapter 7.

The modal outcome, corresponding to the melt-up-then-correction scenario of Chapter 8.

sub-branch attribution per and NBER dating.

**Drawdown Forecasts: The Statistical Core**

This is the report's headline drawdown answer. resolves YES if any trough is >= 20% below its preceding peak. [S55]

**Policy Binaries: The Fed Path as a Dated, Checkable Sequence**

this report endorses the market price rather than overriding it, given no private information edge on a two-week horizon. Resolution: fred:DFEDTARU (4% as of 2026-10-23 [S11]) moves above 4% following the meeting.

A YES resolution is the primary channel converting the melt-up scenario into the bear-market scenario, as argued in Chapter 5.

**Earnings and Breadth Binaries: Testing the Engine**

Resolution: any FactSet Earnings Insight publication dated between 2027-01-01 and 2027-12-31 reporting CY2027 bottom-up EPS growth below +10% [S6][S8]. This is the single most scenario-relevant binary in the set: a YES resolution would mechanically shift probability from Binary 1 toward Binaries 3 and 4.

Resolution: FactSet Earnings Insight Q4 2026 final comparison, published around February 2027.

this binary tests whether it persists across the forecast horizon. Resolution: at least one FactSet Earnings Insight quarterly Mag 7 versus other-493 earnings-growth comparison for a calendar-2027 quarter (Q1 through Q4 2027), published through roughly June 2028, showing Mag 7 growth below other-493 growth [S8]. A YES resolution supports Binaries 2 and 3 by confirming that index earnings are broadening but mega-cap leadership premium is eroding — a two-sided signal for multiples.

NVIDIA's CEO has claimed $600bn per year in annual hyperscaler spend, a figure flagged as unvalidated by leading hyperscalers [S33] — a scope dispute that matters for resolution mechanics. A YES resolution is the leading trigger for Binary 5's bear branch.

**Macro-Regime Binaries: Recession Signals on Official Series**

The real-time Sahm indicator stands at 0 percentage points, down from 0.23 a year earlier, with a five-year window high of 0.57 in August 2024.

Resolution: an NBER Business Cycle Dating Committee announcement identifying a monthly peak within the window;

**Valuation Binary: Mean Reversion, Measured**

**Coherence, Steelman, and Calibration Notes**

Three consistency properties hold across the set.

Concentration cuts both tails' independence, and the binary set prices that.

Every probability above is this report's estimate except Binary 7, which adopts the FedWatch market price as the best available anchor on a two-week horizon. All resolutions are designed to be checkable against named public sources — FRED series, FactSet publications, Multpl, NBER announcements, and company filings — so that by early 2028 each of the fifteen claims can be scored without interpretive dispute, with the sole caveat that P/E-basis and capex-scope definitional disputes (documented in Chapters 1 and 3) may require the pre-specified primary sources to arbitrate. [S45]

## Forecast Summary Table and Calibration Note

The chapters that precede this one built the forecast piece by piece: the baseline, the indicator dashboard, four drivers, five scenarios, a modal trajectory, fifteen binary forecasts, and a risk map. This closing chapter consolidates everything into a single reference table and then does the one thing a forecast owes its readers at the end: an honest account of how much confidence each number deserves, where this report deliberately departs from external anchors, and which specific observations would force the probability distribution to move.

### The Forecast Summary Table

| Scenario | Probability | Index band (Dec 2027 close) | 20% drawdown? | Defining condition | Primary falsification trigger |
|---|---|---|---|---|---|
| I. AI-driven reacceleration | — | — | No | — | — |
| II. Melt-up then mid-horizon correction (modal) | — | — | — | — | — |
| III. Bear market, no recession | — | — | Yes | — | — |
| IV. Hard-landing recession | — | — | — | Sahm rule triggered en route [S17] | smoothed probability rising toward its 2.32% window high [S13] (confirms) |
| V. Stagnant sideways grind | — | — | No | — | — |

### How Each Probability Was Calibrated — and Why Confidence Is Low

The scenario weights are not point estimates dressed up as probabilities; each is a reference-class base rate adjusted for case-specific evidence, and the adjustments are documented so a reader can disagree with them one at a time.

**But the calibration carries an explicit low-confidence rating**, and the reasons are concrete rather than ritual. Four data disputes documented throughout this report remain unresolved as of the research cutoff. if genuine, the entire rate-path chapter would need reweighting toward the dovish branch. Each dispute individually shifts scenario boundaries by a few points;

The small-sample problem deserves its own confession. The cleanest reference class contains four observations; the loosened version, seven. That three anchors from different methodologies land on a coherent picture — upside median, fat left tail, drawdown probability around a third — is the strongest calibration argument available, and it is still weak by the standards of a proper out-of-sample test.

### Where This Report Diverges from External Anchors — and Why

Three external anchors frame the forecast, and this report departs from each in a documented direction.

and that no credit-stress, bank-failure, or comparable exogenous trigger is visible in the evidence base — the configuration in which post-war recessions historically did not begin. That is the honest sensitivity: the framework's ordering of scenarios is robust to this choice; the exact weights are not.

### Scenario-Probability Sensitivity: What Would Move the Distribution Most

Not all observables are equal.

1. The single most powerful revision.

2. **The December 8–9, 2026 SEP** [S16][S39]. This is the highest-density *policy* gate; the capex gate remains the higher-density *earnings* gate.

4. **The CY2027 consensus revision path.**

5. **Monthly labor releases.** a smoothed recession probability sustained above the 2.32% window high [S13] marks regime change. These alone would not rewrite the distribution quickly, but they are the triggers that convert the other channels' damage from correction into bear market.

### The Closing Statement of the Forecast

The forecast's users should treat the numbers as a structured ordering of uncertainty, monitor the five sensitivity observables on their documented schedules, and expect to rewrite at least one scenario's probability when the December 2026 SEP and the February 2027 breadth checkpoint arrive — the two observations most capable, on current evidence, of determining whether 2027 rewards or finally punishes the fourth consecutive year of a trailing multiple above 22. [S9]

## Risk Map and Decision Implications for Investors and Policymakers

The preceding chapters established a market carried by exceptional earnings growth against a valuation regime with historically elevated drawdown base rates.

### Tail Risks: The Four Channels That Could Break the Modal Path

NVIDIA sits at the centre of this web as the largest AI-capex proxy whose guidance drives index earnings expectations, with Microsoft, Alphabet, Amazon and Meta as its downstream customers.

A December SEP revision toward the futures path — or beyond it — would validate the rates end of the tug-of-war at exactly the moment the earnings-quality fade begins.

The third tail risk is tariff escalation.

Average hourly earnings at +3.025% are at the bottom of their five-year range; the 4.214% window high from March 2025 marks the level at which unit-labour-cost pressure would force the Fed's hand on the inflation side [S29]. The September 2026 unanimous 25bp hike to a 4% upper limit [S11] shows the committee's willingness to tighten against wage-driven inflation.

### Underpriced Risks: What the Market's Attention Has Not Yet Priced

Three risks in the research record receive less market attention than their mechanism warrants.

First, the earnings-quality fade. This is not a tail risk — it is a scheduled headwind inside the consensus numbers. The underpricing lies in its second-order effect: when those gains fade, reported growth will decelerate mechanically even if operating earnings hold, and the deceleration will be concentrated in exactly the mega-caps that dominate the index. A market conditioned on three consecutive quarters above 25% blended growth may read the mechanical slowdown as a fundamental deterioration, amplifying the multiple response beyond what the operating fundamentals justify. [S8]

Second, refund-driven fiscal distortions. The risk to investors is indirect but real: a fiscal-revenue surprise in either direction changes the Treasury issuance calendar and the term premium, feeding back into the multiples question.

Third, concentration-amplified passive-flow feedback. But this is a debate about the direction of earnings dominance, not about the structural exposure. The passive-flow amplifier works symmetrically on the way down, and no earnings-breadth improvement reduces that mechanical exposure.

Against these, one underpriced upside deserves equal billing: the breadth broadening already visible at the Mag 7 boundary.

### Decision Implications for Investors

the cost-efficiency argument favours hedges targeted at the mega-cap complex itself, or at the capex cycle through the NVIDIA-Micron axis where the 9-percentage-point gap between headline and ex-Micron/NVIDIA growth identifies the single point of failure.

Timing follows the decision calendar. Adding cyclical exposure before that checkpoint is a bet that the current quarter's 29.0% blended growth persists; [S8] adding after confirmation of breadth is a bet on the two-engine market.

The melt-up scenario carries its own decision implication.

### Decision Implications for Corporates and Policymakers

For corporate planners, the margin mathematics are the operative constraint. those without it compound the margin squeeze.

the December SEP is the second.

That combination, tight-for-longer against benign labour signals, is precisely the environment in which corrections are common but bear markets need an exogenous trigger.

### The Pre-Registered Monitoring Dashboard

The report's overall confidence is low, and that confession is itself a decision input.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/sp500-2027/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[24%] AI-driven reacceleration (bull continuation)**: S&P 500 closing level on 2027-12-31 (fred:SP500, last trading day of 2027, or Dec 2027 monthly mean) >= 8,700 AND no closing-basis decline of >= 20% from any closing peak between 2026-10-01 and 2027-12-31 (measured on daily closes; if only monthly means are used, measured on monthly means).
- **[28%] Melt-up then mid-horizon correction**: S&P 500 closing level on 2027-12-31 between 7,700 and 8,699.99 AND at least one closing-basis drawdown of 10-19.9% from a closing peak between 2026-10-01 and 2027-12-31 AND no closing drawdown >= 20% over the same window.
- **[22%] Bear market / 20%+ drawdown, mild landing**: A closing-basis decline of >= 20% from any closing peak between 2026-10-01 and 2027-12-31, occurring on or before 2027-12-31 AND fred:RECPROUSM156N < 30% for every published month through 2027-12 AND no NBER-declared recession peak in 2026-10 through 2027-12 AND Dec 2027 index level between 6,100 and 7,699.99. If the level criterion fails but the drawdown and no-recession criteria hold, the scenario counts as unresolvable and falls to judgment.
- **[8%] Hard landing recession**: NBER declares a US recession with peak between 2026-10 and 2027-12, OR fred:RECPROUSM156N >= 30% for any month published through 2027-12, AND S&P 500 Dec 2027 level < 6,100 AND a >= 25% closing drawdown from a closing peak in the window. NBER declaration lagging past 2027-12 does not void the scenario if the RECPROUSM156N criterion is met.
- **[18%] Stagnant sideways grind (residual / status quo)**: S&P 500 Dec 2027 monthly-mean level between 7,300 and 7,699.99 AND no closing drawdown >= 20% from a closing peak between 2026-10-01 and 2027-12-31 AND calendar-2027 price return (Dec 2027 vs Dec 2026) between -5% and +2%. Note: this bucket also absorbs residual paths not cleanly classified by the other four scenarios.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| S&P 500 — United States (fred:SP500) | next monthly release after 2026-09 | — |
| S&P 500 (year-over-year % change) — United States (fred:SP500#yoy) | next monthly release after 2026-09 | — |
| Federal Funds Target Range - Upper Limit — United States (fred:DFEDTARU) | next monthly release after 2026-09 | — |
| Smoothed U.S. Recession Probabilities (fred:RECPROUSM156N) | next monthly release after 2026-08 | — |
| Real-time Sahm Rule Recession Indicator — United States (fred:SAHMREALTIME) | next monthly release after 2026-09 | — |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States (fred:T10Y3M) | next monthly release after 2026-09 | — |
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | next monthly release after 2026-09 | — |
| Average Hourly Earnings of All Employees, Total Private — United States (fred:CES0500000003) | next monthly release after 2026-09 | — |
| Monthly Treasury Statement: Customs Duties (current month) — United States (usgov:treasury/mts_customs_duties) | next monthly release after 2026-09 | — |
| Federal Funds Effective Rate — United States (fred:FEDFUNDS) | next monthly release after 2026-09 | — |
| Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States (fred:CES0500000003#yoy) | next monthly release after 2026-09 | — |
| Federal Funds Effective Rate — United States (fred:DFF) | next monthly release after 2026-09 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| S&P 500 — United States (fred:SP500) | 7669.4143 Index (2026-09) | >= 8700 Index / 2027-12 | 33% (n=104, h=15) vs model 24% | [Source](<https://fred.stlouisfed.org/series/SP500>) [S2] |
| Federal Funds Target Range - Upper Limit — United States (fred:DFEDTARU) | 4% (2026-09) | >= 4.25% / 2027-12 | insufficient history vs model 50% | [Source](<https://fred.stlouisfed.org/series/DFEDTARU>) [S11] |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States (fred:T10Y3M) | 0.896% (2026-09) | < 0% / 2027-06 | 15% (n=111, h=9) vs model 12% | [Source](<https://fred.stlouisfed.org/series/T10Y3M>) [S18] |

<!-- drf-news-market-context:6b3a76d814f847c940eb08fadec87c42e17214a7bcac6981ac300f2ff27f2fbe:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:6b3a76d814f847c940eb08fadec87c42e17214a7bcac6981ac300f2ff27f2fbe:end -->

<!-- sim-bridge:start -->
## Scenario simulation: what the exercise explored

Simulated under declared assumptions. Not observed facts, not a calibrated probability, and not an input to any probability in this report.

- Engine: oasis-reflexive
- Periods committed: 14 of 14 planned
- Health: unavailable (validity: invalid)

After-action record not available for this run.
<!-- sim-bridge:end -->

<!-- forecast-track-record:start -->
## Historical forecasting track record

These scores describe retained forecasts with recorded outcomes. A limited record does not establish calibration.

| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |
|---|---:|---:|---:|---:|
| Scenarios (multiclass) | 7 | 0 | 7 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 22 | 0 | 22 | — |
| Unanchored binaries | 79 | 0 | 79 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S2] S&P 500 — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/SP500](https://fred.stlouisfed.org/series/SP500)
2. [S10] S&P 500 (year-over-year % change) — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/SP500](https://fred.stlouisfed.org/series/SP500)
3. [S25] Central bank policy rates - United States - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US)
4. [S13] Smoothed U.S. Recession Probabilities — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/RECPROUSM156N](https://fred.stlouisfed.org/series/RECPROUSM156N)
5. [S17] Real-time Sahm Rule Recession Indicator — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/SAHMREALTIME](https://fred.stlouisfed.org/series/SAHMREALTIME)
6. [S26] Average Hourly Earnings of All Employees, Total Private — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CES0500000003](https://fred.stlouisfed.org/series/CES0500000003)
7. [S27] Monthly Treasury Statement: Customs Duties (current month) — United States — fiscaldata.treasury.gov — [https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/](https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/)
8. [S18] 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T10Y3M](https://fred.stlouisfed.org/series/T10Y3M)
9. [S28] Federal Funds Effective Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/FEDFUNDS](https://fred.stlouisfed.org/series/FEDFUNDS)
10. [S11] Federal Funds Target Range - Upper Limit — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DFEDTARU](https://fred.stlouisfed.org/series/DFEDTARU)
11. [S29] Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CES0500000003](https://fred.stlouisfed.org/series/CES0500000003)
12. [S30] Federal Funds Effective Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DFF](https://fred.stlouisfed.org/series/DFF)
13. [S9] The 'Great Narrowing': S&P 500 concentration — rbcwealthmanagement.com — [https://www.rbcwealthmanagement.com/en-us/insights/the-great-narrowing-sp-500-concentration](https://www.rbcwealthmanagement.com/en-us/insights/the-great-narrowing-sp-500-concentration)
14. [S55] S&P 500 Bear Markets — winthropwealth.com — [https://winthropwealth.com/wp-content/uploads/2023/01/SP-500-Bear-Markets-CQ.pdf](https://winthropwealth.com/wp-content/uploads/2023/01/SP-500-Bear-Markets-CQ.pdf)
15. [S22] S&P 500 Total Returns by Year Since 1926 — slickcharts.com — [https://www.slickcharts.com/sp500/returns](https://www.slickcharts.com/sp500/returns)
16. [S4] S&P 500 PE Ratio by Year - Multpl — multpl.com — [https://www.multpl.com/s-p-500-pe-ratio/table/by-year](https://www.multpl.com/s-p-500-pe-ratio/table/by-year)
17. [S6] FactSet Earnings Insight — advantage.factset.com — [https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_100926.pdf](https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_100926.pdf)
18. [S8] FactSet Earnings Insight — factset.com — [https://www.factset.com/earningsinsight](https://www.factset.com/earningsinsight)
19. [S33] Jensen Claims $600B in Annual CAPEX Spend - Wait, What? — thecuberesearch.com — [https://thecuberesearch.com/jensen-claims-600b-in-annual-capex-spend-wait-what/](https://thecuberesearch.com/jensen-claims-600b-in-annual-capex-spend-wait-what/)
20. [S57] US Economic Survey - SIFMA — sifma.org — [https://www.sifma.org/research/economics/us-economic-survey](https://www.sifma.org/research/economics/us-economic-survey)
21. [S14] [PDF] Probability of US Recession Predicted by Treasury Spread — newyorkfed.org — [https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf](https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf)
22. [S47] Counterpoint Global Insights — morganstanley.com — [https://www.morganstanley.com/im/publication/insights/articles/article_drawdownsandrecoveries.pdf](https://www.morganstanley.com/im/publication/insights/articles/article_drawdownsandrecoveries.pdf)
23. [S46] Rising S&P 500 concentration was rational - but mega-cap… — guinnessgi.com — [https://www.guinnessgi.com/insights/articles/rising-sp-500-concentration-was-rational-mega-cap-earnings-dominance-now-fading](https://www.guinnessgi.com/insights/articles/rising-sp-500-concentration-was-rational-mega-cap-earnings-dominance-now-fading)
24. [S58] 2027 economic outlook: Resilience to continue, but the risks are building — oxfordeconomics.com — [https://www.oxfordeconomics.com/resource/2027-economic-outlook-resilience-to-continue-but-the-risks-are-building/](https://www.oxfordeconomics.com/resource/2027-economic-outlook-resilience-to-continue-but-the-risks-are-building/)
25. [S37] Fed Funds Rate Forecast 2026-2031 | StreetStats — streetstats.finance — [https://streetstats.finance/rates/fedfunds](https://streetstats.finance/rates/fedfunds)
26. [S52] Tracking the Economic Effects of Tariffs | The Budget Lab — budgetlab.yale.edu — [https://budgetlab.yale.edu/research/tracking-economic-effects-tariffs](https://budgetlab.yale.edu/research/tracking-economic-effects-tariffs)
27. [S42] US recession by end of 2026? Trading Odds & Predictions | Polymarket — polymarket.com — [https://polymarket.com/event/us-recession-by-end-of-2026](https://polymarket.com/event/us-recession-by-end-of-2026)
28. [S45] S&P 500 Companies by Weight — slickcharts.com — [https://www.slickcharts.com/sp500](https://www.slickcharts.com/sp500)
29. [S16] The Fed - Meeting calendars and information - Federal Reserve — federalreserve.gov — [https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
30. [S39] The Fed - September 16, 2026: FOMC Projections materials, accessible version — federalreserve.gov — [https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm](https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm)
