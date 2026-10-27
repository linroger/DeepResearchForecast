# Gold at End-2027: A $4,300–$5,200 Central Case Between a Real-Yield Squeeze and an Official-Sector Floor

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/gold-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | The LBMA p.m. gold price on 31 December 2027 is at least $4,300 per troy ounce. | 49% | Resolves YES if the LBMA Gold Price p.m. auction in USD/ozt on 31 Dec 2027 is >= $4,300 (source: LBMA). | central-bank-demand-floor | — |
| F2 | The LBMA p.m. gold price on 31 December 2027 is above $5,500 per troy ounce. | 16% | Resolves YES if the LBMA Gold Price p.m. auction in USD/ozt on 31 Dec 2027 is > $5,500, exceeding the 29 Jan 2026 a.m. record of $5,501.70 (source: LBMA). | crisis-premium | — |
| F3 | The LBMA p.m. gold price on 31 December 2027 is at most $3,800 per troy ounce. | 21% | Resolves YES if the LBMA Gold Price p.m. auction in USD/ozt on 31 Dec 2027 is <= $3,800 (source: LBMA). | real-yield-squeeze | — |
| F4 | The 10-year TIPS yield (fred:DFII10) monthly average is below 2.2% in December 2026. | 12% | Resolves YES if fred:DFII10 < 2.2% in 2026-12 (source: FRED). | real-yield-squeeze | — |
| F5 | The US central bank policy rate (bis:WS_CBPOL/M.US) is above 3.875% at the end of December 2026. | 68% | Resolves YES if bis:WS_CBPOL/M.US > 3.875 per cent per year in 2026-12 (source: BIS). Official resolution: bis:WS_CBPOL/M.US > 3.875% for 2026-12. | fed-hawkish-pivot | 20% (n=237, h=3) |
| F6 | US CPI inflation, year-over-year (fred:CPIAUCSL#yoy), is above 3% in December 2026. | 75% | Resolves YES if fred:CPIAUCSL#yoy > 3% in 2026-12 (source: FRED). Official resolution: fred:CPIAUCSL#yoy > 3% for 2026-12. | sticky-inflation | — |
| F7 | China's central bank policy rate (bis:WS_CBPOL/M.CN) is below 3% per year at the end of December 2026. | 18% | Resolves YES if bis:WS_CBPOL/M.CN < 3 per cent per year in 2026-12 (source: BIS). Official resolution: bis:WS_CBPOL/M.CN < 3% for 2026-12. | pboc-continuity | 28% (n=116, h=3) |
| F8 | The Nominal Broad U.S. Dollar Index (fred:DTWEXBGS) monthly average is above 122 in December 2026. | 20% | Resolves YES if fred:DTWEXBGS > 122 Index Jan 2006=100 in 2026-12 (source: FRED). Official resolution: fred:DTWEXBGS > 122 Index Jan 2006=100 for 2026-12. | dollar-breakout | 15% (n=117, h=3) |
| F9 | The 10-Year Breakeven Inflation Rate (fred:T10YIE) monthly average is above 2.5% in December 2026. | 33% | Resolves YES if fred:T10YIE > 2.5% in 2026-12 (source: FRED). Official resolution: fred:T10YIE > 2.5% for 2026-12. | inflation-wedge | 21% (n=117, h=3) |
| F10 | University of Michigan one-year inflation expectations (fred:MICH) are below 3.5% in October 2026. | 22% | Resolves YES if fred:MICH < 3.5% in 2026-10 (source: FRED). | consumer-inflation-psychology | — |
| F11 | Central banks net purchase at least 500 tonnes of gold across calendar year 2027. | 55% | Resolves YES if World Gold Council Gold Demand Trends full-year 2027 official-sector net purchases are >= 500 tonnes (source: WGC). | central-bank-demand-floor | — |
| F12 | The US central bank policy rate (bis:WS_CBPOL/M.US) is lower at the end of December 2027 than at the end of December 2026. | 22% | Resolves YES if bis:WS_CBPOL/M.US in 2026-12 > bis:WS_CBPOL/M.US in 2027-12 (source: BIS). | fed-hawkish-pivot | — |

_12 forecasts; 8 high-conviction (≥70% or ≤30%); 12 with objective criteria._

### Market Cross-Check

_Deterministic cross-check of forecast probabilities against live prediction-market implied probabilities. Markets are calibration anchors, not ground truth; divergences over 10 percentage points whose rationale does not cite the market are flagged for explanation._

**Unmatched markets (in snapshot, not anchored by any forecast — candidate cross-checks):**
- [Will Gold (GC) hit (HIGH) $6,000 by end of December?](https://polymarket.com/event/what-will-gold-gc-hit-by-end-of-december) — implied P(yes) 3%
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed | Percent | 2.638% | 2026-09 | +0.889 pp | -1.06% to 2.638% | 2.859% (2026-10, partial-period value) | [S5] |
| Central bank policy rates - United States - Monthly - End of period | Per cent per year | 3.875% | 2026-09 | -0.25 pp | 0.125% to 5.375% | — | [S4] |
| Nominal Broad U.S. Dollar Index | Index Jan 2006=100 | 119.2152 | 2026-09 | -0.8138 (-0.678%) | 113.4437 to 128.837 | 121.4607 (2026-10, partial-period value) | [S29] |
| Effective exchange rates: United States - Real - Broad (64 economies) | Index, 2020 = 100 | 107.11 | 2026-09 | -0.38 (-0.354%) | 98.69 to 114.5 | — | [S30] |
| 10-Year Breakeven Inflation Rate — United States | Percent | 2.351% | 2026-09 | -0.02 pp | 2.11% to 2.88% | 2.35% (2026-10, partial-period value) | [S7] |
| University of Michigan: Inflation Expectation | Percent | 4% | 2026-08 | -0.8 pp | 2.6% to 6.6% | — | [S31] |
| Central bank policy rates - China - Monthly - End of period | Per cent per year | 3% | 2026-09 | 0 pp | 3% to 3.85% | — | [S32] |
| Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) | Percent change from year ago | 3.717% | 2026-09 | +0.695 pp | 2.391% to 4.167% | — | [S6] |
| Global price of Copper | U.S. Dollars per Metric Ton | 13542.8209 | 2026-07 | — | 12528.7095 to 13552.0409 | — | [S33] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/gold-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFII10>) [S5]; Percent; Monthly; NSA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S4]; Per cent per year; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DTWEXBGS>) [S29]; Index Jan 2006=100; Monthly; NSA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.CN>) [S32]; Per cent per year; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10YIE>) [S7]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CPIAUCSL>) [S6]; Percent change from year ago; Monthly; SA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.US>) [S30]; Index, 2020 = 100; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/MICH>) [S31]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/PCOPPUSDM>) [S33]; U.S. Dollars per Metric Ton; Monthly; NSA*

<!-- viz:charts/official_series_eaeoofrpnafnqllo.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_eaeoofrpnafnqllo.png)

*Official Series History and Forecast Thresholds*

*Source: [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S4]; Per cent per year; Monthly; adjustment unknown*

<!-- viz:charts/official_series_ksfkoqaeaspatkaf.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_ksfkoqaeaspatkaf.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DTWEXBGS>) [S29]; Index Jan 2006=100; Monthly; NSA*

<!-- viz:charts/official_series_rsoerktasoksrbkq.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_rsoerktasoksrbkq.png)

*Official Series History and Forecast Thresholds*

*Source: [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.CN>) [S32]; Per cent per year; Monthly; adjustment unknown*

<!-- viz:charts/official_series_korolrkrnbnmqope.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_korolrkrnbnmqope.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10YIE>) [S7]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_lsqcnptfsbpockkn.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_lsqcnptfsbpockkn.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CPIAUCSL>) [S6]; Percent change from year ago; Monthly; SA*

<!-- viz:charts/official_series_raknptsrnarbllsr.html -->
![Official Series History and Forecast Thresholds](demos/gold-2027/charts/official_series_raknptsrnarbllsr.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFII10>) [S5]; Percent; Monthly; NSA*

## Part 2 — Framework & Synthesis

### Framework in One Paragraph

The analytical problem is therefore not trend extrapolation but regime arbitration: two powerful, opposing forces — a hostile real-yield regime and a resilient structural demand floor — are contesting the price. Probabilities were assigned by asking, for each scenario, which axis dominates and how quickly the other can offset it.

### Baseline: An Exhausted Mania With a Firm Floor

This is a market that has already experienced both the mania and the crash phases.

### The Decisive Macro Axis: Real Yields

It stood at 2.638% in September 2026 — the top of its five-year range and up 0.889 percentage points year-over-year, with the latest daily print at 2.77% on 20 October. this is historically extreme territory for gold's most reliable inverse driver. Realized CPI at 3.717% y/y against anchored 10-year breakevens of 2.351% creates a wedge: realized inflation keeps the Fed hawkish (bearish for gold via the real-yield channel), while the market's long-run inflation expectations remain contained (removing the unhedged-inflation bid). The Fed hiked in September 2026 to 3.75–4.00%, the September SEP median holds the funds rate at 4.25% through 2028, and market pricing embeds roughly 77bp of cumulative tightening through October 2027, with a December 2026 hike priced at 73.3%. Where the SEP and market pricing diverge, we weight market pricing more heavily for the near term but note that both point away from easing in the forecast's first year.

### Why the Base Case Still Wins (34%)

Three reasons.

First, the demand floor is quantitatively large and persistent. Poland is at +98t year-to-date with its 700t target "within reach"; the RBI continues steady accumulation and has repatriated most custodial gold. Against this, Turkey (−82t YTD) and Russia (−56t YTD) are the swing sellers, but their liquidations are liquidity-driven, not conviction-driven, and Turkey turned marginal buyer again in August.

Second, the base case requires only that the extreme real-yield regime mean-reverts partway, not that it reverses.

### The Bear Case Is Live, Not a Strawman (21%)

The 21% real-yield squeeze (≤$3,800) deserves its weight because it is simply the market's own path extended: ~77bp of cumulative tightening through October 2027 against CPI sticky above 3%, with Michigan inflation expectations still at 4%.

### Range-Bound Consolidation at 28%: The Positioning-Exhaustion Outcome

the scenario asks only that it persists fourteen more months.

### Bull Case at 15%: Recession and Crisis Premium

A recession that begins while CPI is decelerating would deliver exactly the easing-and-crisis combination gold loves.

### How the Anchors Were Weighed

Three market anchors discipline the distribution. we treat bank targets as conditional-on-easing forecasts that over-weight the base-bull boundary, and shade toward the market-implied centre.

The Polymarket signal — 3% implied probability that gold touches $6,000 by end of December 2026 [polymarket] — is consistent with, and slightly reinforces, our restraint on the bull tail: the market assigns only a small chance of a near-term return to the January 2026 record region, and our 15% for >$5,200 by end-2027 reflects a fourteen-month horizon in which a recession-triggered easing cycle could plausibly rebuild that premium, not a disagreement with the market's near-term pricing.

### Defending the Milestone Probabilities in Part 1

The binary forecasts follow mechanically from this distribution. All resolutions anchor to LBMA p.m. auction prints or COMEX settlements as specified in Part 1.

### What Would Change Our Minds

The falsifiable markers, in order of importance: (1) the 10-year TIPS yield [S5] — a sustained break above 3% would migrate probability from base to bear; (3) WGC quarterly central bank data — net purchases below 400t annualized would weaken the floor; (5) Poland's 700t completion and whether China's streak breaks. The forecast's confidence is medium precisely because the two dominant forces are at historic extremes simultaneously, and history offers almost no precedent for which gives way first.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Baseline: Where Gold Stands at the Start of the Forecast Window

Gold enters the forecast window in an unusual configuration: a market that has already lived through its mania and its correction, now trading roughly a quarter below an all-time high set barely nine months ago, yet carrying record investment stock and an official sector that keeps buying.

### The Late-October 2026 Price Snapshot

The Macrotrends daily composite sat slightly higher at **$4,132** on the same date [S2] — the gap between the two reflects methodology (spot quotation versus composite averaging) rather than any genuine market dislocation, but it is worth noting because every threshold in this report will be anchored to the LBMA auction and COMEX settlements, not to composites.

### The 2024–2026 Trajectory: Boom, Blow-Off, Break

The starting point only makes sense against the three-year run that produced it.

- **January 2026: the blow-off high.** The LBMA a.m. [S3] auction printed **$5,501.70 on 29 January 2026**, the all-time record. [S3] From there the market corrected by nearly 27%, closing June 2026 at $4,026.05 and touching an intraday low near **$3,994.50 on 25 June** — a level that now functions as the single most-watched technical floor for 2027 (the binary forecasts in Chapter 12 reference it directly).

The correction's cause is as important as its size. The proximate driver was not the dollar — the nominal broad dollar index actually **fell 0.678% year-over-year** to 119.2152 in September 2026 [S29] — but real interest rates. The 10-year TIPS yield rose **+0.889 percentage points year-over-year to 2.638%** in September 2026, the top of its five-year range, with a daily print of 2.77% on 20 October 2026. That tension — a hostile macro axis versus a resilient demand floor — is the organizing question of the entire forecast.

### Positioning at the Window's Start

(A vintage discrepancy exists: an earlier WGC communication cited 4,189t/+121t;

### The Disputed End-2025 Anchor

One housekeeping dispute deserves explicit treatment because it contaminates every "calendar-year return" calculation downstream. The divergence most likely reflects a spot close versus a p.m. auction print and differing composite methodologies; the exact LBMA p.m.

Everything that follows is an attempt to weigh those forces honestly.

## Central Forecast and Scenario Probabilities for 31 December 2027

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/gold-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

### Central Forecast: Where Gold Most Plausibly Lands on 31 December 2027

The placement is a judgment, and the reasoning behind it is the substance of this chapter.

Start with why the P50 cannot simply equal the futures price. A price established by a few hundred contracts tells us what a thin handful of hedgers will pay for two-year protection, not what the marginal buyer of physical gold — a central bank adding to reserves or an ETF investor — will pay in late 2027. [S12]

Now consider why the P50 also sits below the banks. Bank targets priced for easing in a world priced for hikes are, at minimum, one dovish assumption ahead of the observable policy path.

This is not a market with a clean directional skew; it is a market with a firm demand floor beneath a heavy macro ceiling. The distribution above is the direct arithmetic expression of that structure.

### The Four Scenarios: Mutually Exclusive, Exhaustive, and Anchored to the LBMA Auction

The probability mass divides into four scenarios plus a small residual. All resolve against the LBMA Gold Price p.m. where intraday milestones matter in later chapters, COMEX settlements and WGC quarterly flow data serve as auxiliary sources.

**1. The mechanism is a slow resolution of the macro ceiling while the demand floor holds. By this report's calculation from the stored history, one-month changes in DFII10 have a median of essentially zero but a p10 of −0.19pp — meaning that when this series mean-reverts from an extreme, it does so downward more often than it climbs further.

**2.

**3. Bear — Real-yield squeeze to ≤$3,800: 21%.** Sticky CPI above 3% through H1 2027 forces the Fed to validate the 77bp of tightening markets already price; the dollar breaks its five-year DTWEXBGS high of 128.837 [S29]; and official demand cracks as Turkey (−82t YTD) and Russia (−56t YTD) accelerate sales while Poland halts at its 700t target. The scenario's probability is capped — despite the hawkish market pricing — by the demand floor: someone was buying $10bn of ETF metal into a falling September price, and that behavior is the empirical counterweight to the real-yield thesis.

**4. Morgan ~40% [S47]; We assign 15%, well above the near-zero weight the market gives extreme near-term outcomes (Polymarket prices only 3% for $6,000 by end-December *2026*), because ours is a full-2027 scenario and recession odds compound over 14 months.

**5.

### Why the Demand Floor Outweighs the Hawkish Fed in the Base Case — and the Steelman Against It

the SEP holds 4.25% through 2028 [S15]. If the tightest real-yield regime in two decades tightens further, why isn't the bear case the base case?

We reject that as the central case for three quantified reasons. First, the real-yield regime itself is the anomaly: 2.638% sits at the 98th percentile of 239 months [S5], and the historical distribution of changes from such extremes is asymmetric toward mean reversion — precisely the variable banks' easing-conditioned targets implicitly assume. Second, the demand side is not constant.

Turkey's mobilization of roughly $20bn of official gold in five weeks during the April 2026 Iran War shows how quickly an accumulator becomes a seller under fiscal stress. [S3] A multi-month ETF outflow streak from the record 4,256t stock, or two consecutive quarters of sub-100t official net buying, would remove the floor exactly when the real-yield ceiling presses hardest.

### Confidence, Calibration and What the Distribution Gets Right by Being Wide

Overall confidence in this forecast is **medium**, for three reasons stated plainly. Our P10–P90 spread of roughly $3,700–$5,600 — about ±20% around the P50 — is instead calibrated from Dec-2026 ATM implied volatility of 19.32% applied over a 14-month horizon, cross-checked against the scenario bands' outer edges.

a hike followed by a long hold drifts weight toward consolidation; The distribution above is the summary; those chapters are the audit trail.

## Scenario Deep-Dive I — Base Case: Grind Higher to $4,300–$5,200

The scenario instead describes a specific tug-of-war resolving in gold's favor by a modest margin: a real-yield regime that is historically hostile, contested by an unusually firm demand floor built from official-sector accumulation and contrarian ETF inflows.

### The Macro Turn: From Hawkish Hold to a Mid-2027 First Cut

The base case rests on one macro bet: that the current hawkish configuration is near its peak, not the start of a new multi-year tightening cycle. Three observations anchor this.

First, the real-yield regime itself is extreme. The 10-year TIPS yield averaged 2.638% in September 2026 — the top of its five-year range, up 0.889 percentage points year-over-year — and printed 2.77% on 20 October. real rates, not FX, carried the decline. That matters for the base case because it identifies the single variable whose reversal would carry the recovery: if the dollar is already flat-to-weaker, a 50bp fall in real yields translates into gold upside without needing a dollar bear call at all.

Second, the Fed's own projections embed disinflation. The inflation-hedge bid softens, but the policy-pivot bid replaces it with interest.

A necessary caveat: the near-term risk runs the other way. The scenario's year-end target absorbs this H1 weakness; it does not deny it.

### The Demand Floor: Official Buying and the Contrarian ETF Bid

The base case's second pillar is that the floor under gold does not depend on the Fed at all.

The survey evidence is unusually one-sided.

The flow data, read correctly, support a slower-but-solid pace. The most recent monthly print is consistent with trend: a net 39t in August, led by persistent buyers. At roughly 40t per month, the run-rate annualizes near 500t before any Q2-style acceleration; Goldman's expectation of ~50t per month (about 600t/year) sits comfortably inside the base case's assumed band.

The buyer list is deeper than the seller list. The People's Bank of China logged its nineteenth consecutive monthly purchase in May 2026, the longest streak since 2015. [S32] The National Bank of Poland held 648t at end-August after +98t year-to-date, its 700t target described as within reach. Uzbekistan has bought roughly 50t year-to-date;

The honest steelman against this pillar: Poland is a fading bid. Poland's taper is a headwind to the *pace*, not the *existence*, of official demand;

The private side adds a second, contrarian layer. Buying into weakness of that scale is the signature of an allocation decision, not momentum-chasing;

### The Intra-2027 Path and the Falsification Ledger

The base case implies a recognizable shape to the year.

The scenario is falsifiable on three concrete, observable conditions, any one of which kills it:

1. **Official-demand failure.** Two consecutive quarters of sub-100t net central-bank buying in the WGC quarterly data would break the floor arithmetic — a 500t annualized pace cannot survive quarterly prints below that line. A confirmed NBP halt at 700t *combined with* a PBoC streak break would be the specific trigger pattern.
2. **Private-demand reversal.** Multi-month sustained ETF outflows from the 4,256t record — not a single red month — would remove the contrarian bid; the monthly WGC ETF report is the verifying series.
3. Conversely, an *early* aggressive easing cycle driven by recession would overshoot the band into the bull case — the base case is specifically the gradual-grind path.

Two signpost dates deserve emphasis. new highs confirm the squeeze.

Because the base case requires *both* pillars to hold simultaneously — official demand at 500t+ *and* a disinflation-driven pivot — while the two principal alternatives each require only one force to dominate. The base case is the modal single outcome, but it lives in a world where the most anomalous macro variable (real yields at a generational extreme ) must normalize on a specific timetable.

## Scenario Deep-Dive II — Bear Case: Real-Yield Squeeze Below $3,800

auction. It is not a tail risk invented for symmetry; it is the market's own hawkish path taken at face value and extended one more year.

### The Real-Yield Regime Is Already Historically Extreme

The 10-year TIPS yield averaged 2.638% in September 2026 — the top of its five-year range — and the latest daily print, 2.77% on 20 October 2026, sits above even that. The yield has risen 0.889 percentage points year-over-year [S5]. A regime this hostile to gold has almost no historical precedent in the modern TIPS era, which means the baseline itself is already bearish-adjacent. That decomposition matters for the bear case: if the dollar were to stop offsetting and start reinforcing, the downside is structural, not incremental.

The transmission mechanism is straightforward opportunity cost. Non-yielding gold competes with an inflation-protected Treasury now paying nearly 2.8% risk-free in real terms. [S7] Every additional 25bp the Fed validates forces the front of the curve higher and, with Treasury issuance pressing term premia, drags the long real end with it. The bear scenario is the state of the world where that headwind compounds rather than mean-reverts.

### Trigger One: The Fed Validates the Tightening Markets Already Price

Markets are not waiting for permission.

The condition that makes this trigger fire is sticky inflation. The five-year range of the CPI series shows a January 2026 low of 2.391% [S6]. The research evidence frames the fork precisely: convergence of CPI toward the January low supports Fed easing, while persistence above 3% confirms the bear real-yield squeeze. [S5]

### Trigger Two: A Confirmed Dollar Breakout

The dollar has so far been gold's merciful offset. The nominal broad dollar index averaged 119.2152 in September 2026, down 0.678% year-over-year, with a five-year range capped at 128.837 in January 2025 [S29]; the real broad BIS index tells the same story at 107.11, down 0.354% y/y [S30]. But the daily DTWEXBGS print of 121.4048 on 16 October 2026 [S29] shows the index grinding higher into year-end, and at least one major bank has been reported revising its dollar forecast higher amid rising yields — a stronger-dollar view consistent with the bear path. The falsifiable threshold is concrete: a daily DTWEXBGS close above 128.837 would confirm a genuine dollar-breakout regime [S29]. Two mechanisms would then compound. First, the mechanical pass-through: broad-index strength raises the effective local price of gold in every non-dollar buyer market, suppressing Chinese and Indian retail bar-and-coin demand. A bear-path year would feature at least one such episode.

### Trigger Three: The Official-Sector Floor Cracks at the Edges

The bear case does not require central banks to become net sellers; it requires the marginal bid to thin by a few hundred tonnes. Three specific mechanisms, all visible in current data, could deliver that:

1. Reaching the target mechanically tapers its flow, removing the largest single year-to-date buyer from monthly WGC data. Poland and China are rival leading buyers;
2. Russia remains a sanctioned net seller at -56t year-to-date, still holding 2,271t of reserves that can be mobilized under fiscal stress. Any 2027 crisis episode — and the calendar supplies candidates in France's April–May presidential rounds and Poland's and Italy's late-2027 elections [S50] — risks replaying the Turkey mobilization pattern.

### Trigger Four: The Contrarian ETF Bid Reverses

Record ETF holdings are the strongest counter-argument to this entire chapter, so it deserves the steelman. If that bid persists, the bear scenario dies; the January 2026 to June 2026 correction already stalled at $3,994.50, an ~27% drawdown from the $5,501.70 all-time high, precisely because ETF money bought the dip. [S3]

But the same record stock is the fuel for a spiral in the other direction. September's inflows arrived into a falling price — holders gained tonnes while losing dollars, a pattern that rarely survives a second leg down. the first two consecutive months of ETF outflows crack the contrarian narrative; falling prices trigger momentum-driven redemptions from a 4,256t stock that has never been tested in a sustained outflow cycle at this scale. This quantitative bridge is our estimate, not an observed flow; it is the scenario's core uncertainty.

### The Path to $3,600–$3,800 and the Technical Break

a DTWEXBGS close above 128.837 [S29] confirms the dollar regime; and the year-end p.m. Note the levels are anchored to observable prints, not abstractions: the June low is a recorded LBMA/COMEX benchmark, and the dollar threshold is the five-year DTWEXBGS high.

### Falsification: What Kills This Scenario

- **A CPI rollover toward the January 2026 low of 2.391%** [S6] across two consecutive months would remove the Fed's mandate for further tightening, collapse the 77bp of priced hikes, and flip the real-yield impulse.
- the market-versus-SEP gap closing from below is the leading indicator.
- a half-point decline kills it.
- On the flow side, two consecutive quarters of official net buying above 250t/quarter or continued monthly ETF inflows would demonstrate the floor holds regardless of the macro.

The real-yield regime argues for a higher probability; That is a real but minority path, and it runs through the four triggers above, each with a dated, observable threshold against which readers can update in real time.

## Scenario Deep-Dive III — Bull Case: Crisis and Policy Premium Above $5,200

### The Recession-and-Easing Engine

The single most powerful bull mechanism is a US recession that forces the Federal Reserve to abandon its hawkish stance and cut aggressively. The probability inputs are strikingly asymmetric across sources. These numbers are not directly comparable — the Polymarket contract resolves cumulatively through end-2027, so it overstates any twelve-month hazard rate relative to a forecaster's point estimate — but even the more conservative JPM figure implies that a recession is close to a coin-flip-adjacent risk across a fourteen-month window. [S48]

The transmission works through real yields, gold's cleanest macro discriminator. The mechanical corollary: a reversal of the real-yield shock reverses the damage.

Gold's all-time high of $5,501.70 (LBMA a.m., 29 January 2026) was set in precisely this configuration: aggressive easing expectations, geopolitical risk premium, and momentum-driven ETF inflows all coinciding. [S3] The market has already demonstrated that it will price gold above $5,500 when the macro axis turns dovish — the bull case does not require gold to discover a new valuation regime, only to replay a regime it occupied ten months before the forecast window opened. [S12]

### Crisis Premium: The Iran War Template and Official-Sector Amplification

When the Iran War broke out in April 2026, the Central Bank of Turkey sold or lent approximately $20 billion of official gold within five weeks — evidence both that crises generate extreme safe-haven demand for gold and that official holders can become forced suppliers under stress. [S3] The bull case requires the demand side of that equation to dominate: a new or widened conflict that sends private investors into gold faster than stressed official holders liquidate.

Here the positioning backdrop is unusually favorable to a sharp rally. In a bull scenario, de-dollarization demand and crisis hedging compound rather than compete: sanctions-driven reserve flight into gold and investor flight into gold are the same trade from different balance sheets.

A third, related trigger is a US debt-financing shock — a failed-auction or term-premium spike that compresses real yields by crushing the growth outlook while elevating inflation-hedge demand. The 10-year breakeven at 2.351% is anchored, but realized CPI at 3.717% and Michigan expectations at 4% show the public's inflation experience running far above market pricing; a fiscal shock that re-anchored breakevens upward would hit gold's hedge bid directly.

### The Election Calendar as a Slow-Burn Premium Sustainer

In the bull case, political fragmentation in Europe keeps the safe-haven bid funded across the whole year rather than in a single spike.

### Why 15% — and Where We Diverge from Market Pricing

The natural objection: the market itself prices almost no near-term upside. Polymarket's contract on gold hitting $6,000 by end of December 2026 implied just 3% [Polymarket market data], and the December 2027 COMEX future settled at $4,363.70, barely above spot. Shouldn't the bull probability be closer to the market's single digits?

We think not, for three reasons. In effect, the bull scenario is the world in which the banks' central case turns out right and the futures curve is wrong.

### Falsification Criteria and the Intra-2027 Path

The bull case is falsifiable on a dated, observable basis:

- **ETF outflows and official-buying deceleration coincide.** Record ETF holdings of 4,256t are a floor only while inflows persist;

The demand floor is already observed fact; only the policy pivot is speculative. That asymmetry between an established floor and an unpriced pivot is exactly what a 15% probability, against a futures curve at $4,363.70 and a Polymarket 3% near-term spike call, is meant to capture.

## Scenario Deep-Dive IV — Range-Bound Consolidation ($3,800–$4,300) and the Residual

Unlike the base, bear and bull cases, each of which requires a specific macro regime to take hold, the consolidation scenario is defined by the *failure of both* — the uneasy equilibrium in which the real-yield squeeze never fully bites and the policy/crisis premium never fully returns. It is, in a precise sense, the market's own scenario: the one embedded in the futures curve rather than in bank research decks.

### The Market's Own Center of Gravity

The single most important piece of evidence for this scenario is the shape of the COMEX curve itself. That is a forecast of drift, not of breakout or breakdown.

The liquidity behind that print matters as much as the price. Far-dated gold futures are normally thin, but this degree of one-sidedness means the Dec-2027 quote is set by a small number of participants and should be read as a weak signal, not a strong consensus. [S18] A vacuum of conviction is precisely the precondition for a range.

The forecast landscape reinforces this reading. a $500-wide band around the current level is what unresolved disagreement looks like when it is priced. [S12]

### The Mechanism: Why Both Triggers Fail to Fire

**First, real rates stabilize rather than continue rising.** The 10-year TIPS yield entered this window at 2.638% for September 2026 — the top of its five-year range — and printed 2.77% on 20 October. The macro configuration supports this: CPI at 3.717% y/y keeps the Fed from easing, while the 10-year breakeven at 2.351% — barely changed y/y — tells the bond market inflation is not accelerating. Sticky-but-not-worsening inflation plus a Fed on hold is the textbook recipe for range-bound precious metals. if the Fed delivers one hike and then stops — validating neither the full market path nor the easing the banks expect — real yields would plateau, and the principal driver of gold's 2026 decline goes dormant without reversing. [S37]

Consolidation is what the chart looks like when the last of the momentum money exits but is not replaced by either fresh panic selling or fresh enthusiasm.

This is the critical asymmetry for the consolidation case: 500–650t of annual official buying is enough to prevent a bear-market break below $3,800, but it is not enough — on its own, against 2.6%+ real yields — to power a fresh leg above $5,200. A buyer pausing at target plus sellers liquidating at the margin, offset by the PBoC's nineteen-month streak, is exactly the demand profile of a market going nowhere fast.

Gold oscillates between a defended floor and an enforced ceiling. **Resolution criteria:** this scenario is judged to have occurred if and only if the LBMA p.m. It resolves against us — to bear — if that p.m. print is at or below $3,800; against us — to base — if it is at or above $4,300. Intraday or a.m. prints, COMEX settlements and third-party composites are context, not adjudicators; only the LBMA p.m. auction on the resolution date itself settles the band.

A steelman objection deserves an answer. But the objection proves less than it seems. The same anomaly argument cuts against resolution in either direction: a further sustained rise in real yields would require an inflation re-acceleration the breakeven market does not price (2.351% [S7]), while a sharp decline requires a recession or easing cycle that the SEP explicitly withholds until 2028. The center of the distribution — slightly up or flat — is where both base rates and the futures curve point.

### Falsification Criteria

The consolidation scenario dies if either trigger fires:

- **Partial-death marker:** the June 2026 low of $3,994.50 breaking on a weekly close without recovery within a month pushes weight toward the bear case even if year-end settles back inside the band. [S3]

### Defining the Residual: The 3% Tail

Two conditions trigger it, both adjudicated on the same observable as the four bands — the LBMA p.m. gold price auction print for 31 December 2027: [S23]

1. **Data unavailability.** If the LBMA p.m. gold price for 31 December 2027 is not published — an auction failure, benchmark discontinuation or administrative breakdown — none of the four bands can resolve. [S23] The LBMA auction remains the reference price [S55][S56], but benchmarks are institutions, and institutions occasionally fail; a small allowance is honest bookkeeping.
2. What could produce such a print? On the upside, a monetary event: a US debt-financing crisis that shatters confidence in Treasuries, or broad financial-sanctions escalation that makes gold the only settlement asset of resort — extensions of the April 2026 Iran War pattern in which Turkey mobilized ~$20bn of official gold in five weeks, scaled up to systemic size. [S3] The Polymarket contract pricing a mere 3% chance of $6,000 by end-December 2026 calibrates how cheap extreme upside is in the near term;

Crucially, the residual is *not* a fifth scenario with a narrative — it is the explicitly unlabeled uncertainty that remains after four coherent stories have been told.

### Why 28% — and Not More

The final calibration question is why the second-largest probability sits on the least dramatic story. The answer is arithmetic as much as narrative. Each is conditional on a low-probability macro event compounding. Consolidation, by contrast, requires only the absence of regime change — the default continuation of a market whose demand floor (official buying, contrarian ETF flows ) and macro ceiling (record real yields [S5]) have already spent a year proving they can hold each other in check. When two strong forces have demonstrated equilibrium for twelve months, the highest-information forecast is that the equilibrium persists unless given a reason to break.

## The Federal Reserve, Real Yields and the Dollar: The Decisive Macro Axis

The single most important question for gold between now and 31 December 2027 is not how many tonnes Poland buys or whether ETF inflows persist — it is what happens to the US real interest rate. [S23] Everything else in this forecast is, in one way or another, a modifier on that axis. This chapter establishes the mechanism, quantifies it with the official record, and identifies the specific thresholds and dates at which the macro axis will resolve toward one scenario or another.

### The Fed Has Stopped Easing — and the Market Prices It Going the Other Way

The baseline for this axis is unambiguous. The US policy rate stood at 3.875% at end-September 2026, following the September 2026 hike [S4]. The Federal Reserve has, in effect, stopped easing: the rate is 25bp *below* where it stood a year earlier (4.125% in September 2025), but the direction of travel has reversed [S4].

The structure of this gap matters more than its level. The SEP median and the futures curve disagree not just about the destination but about the sign of the next move. The SEP median at 4.25% through 2028 is *higher* than the current 3.875% setting — meaning the Committee's own projection already embeds tightening — yet markets price even more than the SEP implies through late 2027. Two interpretations are possible, and they carry opposite implications for gold:

- If markets are right and the Fed validates the priced path, the 10-year TIPS yield — already at the top of its five-year range at 2.638% for September 2026 and printing 2.77% daily on 20 October 2026 — makes new highs.
- a confirmation or downward revision would do the opposite.

The quantitative sensitivity is usable. It also means the *removal* of priced hikes is worth more to gold than any plausible incremental hike announcement, most of which is already in the price.

### Real Yields, Not the Dollar, Carried Gold's 2026 Decline

The cleanest evidence for the real-rate transmission channel is the natural experiment the past twelve months ran. If the dollar had been the driver, gold should have risen. It fell — because the opportunity cost of holding a non-yielding asset rose by nearly a full percentage point.

Consider how anomalous the current regime is. The metal is now being asked to hold a $4,000+ price in a real-rate regime it has almost never had to endure. [S3]

Yet it *is* holding. That is the second half of the mechanism. Record ETF holdings of 4,256t absorbed roughly US$10bn of inflows into a falling September price — contrarian buying into the real-yield shock — and central banks bought a Q2-record 289t even as the TIPS yield climbed. The macro axis, in other words, is currently being fought to a standstill: the real-rate shock subtracts, the official-sector and ETF stock absorbs. Which side breaks determines the scenario.

A steelman deserves an answer here. The demand floor changed the *level* around which gold oscillates; it did not repeal the slope.

### The Dollar: A Second-Order Channel with One Threshold That Matters

The dollar is best treated as an amplifier, not an independent driver, in this cycle — but it has one threshold that would change that assessment. The nominal broad dollar index printed 121.4048 daily on 16 October 2026, above its September monthly mean but still below its five-year high of 128.837 set in January 2025. A daily DTWEXBGS close above 128.837 would confirm a genuine dollar-breakout regime — a strengthening currency adding a second headwind on top of the real-rate squeeze, and in our framework the single most reliable confirmation signal that the bear scenario is compounding rather than merely grinding [S29]. The BIS real broad effective rate, at 107.11 for September 2026 against its five-year high of 114.5, tells the same story with more breadth [S30].

Two measurement caveats sharpen the signal.

### The FOMC Calendar as the Scenario Scorecard

The macro axis resolves on a knowable schedule, and each date carries a scenario assignment:

- a hold accompanied by dovish rhetoric would be the first crack in the priced-tightening path. This meeting lands in the same week as the WGC's Q3 2026 Gold Demand Trends, giving the market both the macro and flow pictures simultaneously.
- An upward PCE revision validating the hikes would mark the durable turn toward the bear squeeze.

The through-line of this chapter is deliberately simple: gold's 2027 destination is a function of whether the 10-year TIPS yield at the top of its five-year range [S5] is a peak or a plateau. The demand-side chapters that follow document the floor; this axis sets the ceiling.

## Official-Sector Demand: Buyers, Sellers and the De-Dollarization Floor

<!-- viz:charts/quantitative_claims.html -->
![Comparable Forecast Benchmarks](demos/gold-2027/charts/quantitative_claims.png)

*Comparable Forecast Benchmarks*

Official-sector demand is the structural pillar beneath every scenario in this report. While Chapter 7 showed that the Federal Reserve's real-yield path explains most of gold's 2026 decline, central-bank flows explain why that decline stopped where it did — and they will decide whether the $4,300–$5,200 base case (34%) holds or whether the market slips into consolidation ($3,800–$4,300, 28%) or worse.

### The Buyer Bloc: Concentration, Streaks and the Polish Ceiling

A handful of institutions carry the aggregate: China, Poland, Uzbekistan, the Czech Republic and India on the buy side, with Turkey and Russia as the persistent sell side.

The People's Bank of China remains the anchor buyer. The mechanism here matters more than the tonnage: a nineteen-month streak during a year in which gold corrected 27% from its January high demonstrates that the PBoC's program is price-insensitive at these levels, driven by reserve diversification against a sanctions-prone dollar system rather than by trading considerations. [S3] Even at ~10t/month, the reported pace likely understates true accumulation, since China's official figures exclude reported positions held via other vehicles — a long-standing feature of the data that makes the reported number a floor, not a point estimate.

Behind the two giants, the secondary buyers add resilience rather than scale.

### The Sell Side: Turkey as the Stress Mechanism

Against the buyer bloc stand two official sellers whose behavior under stress defines the downside tail. Russia, under sanctions, sold 56t year-to-date with 2,271t still held.

Turkey deserves particular attention because it demonstrates the mechanism by which official gold becomes market supply in a crisis. When the Iran War broke out, Ankara did not sell into a rally — it mobilized reserves for crisis liquidity, roughly $20bn in five weeks, at precisely the moment geopolitical escalation was pushing private safe-haven demand into gold. That is a crucial asymmetry for 2027: the bull case in Chapter 5 assumes geopolitical escalation lifts gold, but Turkey's 2026 episode shows that a sufficiently severe emerging-market stress event converts the official sector from a floor into incremental supply. [S3] Any 2027 crisis severe enough to trigger emerging-market balance-of-payments stress — a dollar breakout above the DTWEXBGS five-year high of 128.837, for instance — would likely put Turkey and possibly other holders back on the sell side, partially offsetting the very safe-haven bid it creates.

The WGC flow data also reveals how thin the sell side actually is. Russia's selling is sanctions-forced and therefore predictable; Turkey's is crisis-contingent. Neither is structural de-accumulation on the pattern of the 1990s European sales.

### The Pace Debate: 289t Quarters versus 600t Years

The central quantitative dispute in official-demand forecasting is the run rate.

These views are less contradictory than they appear. absent that, a single quarter above 150t should be read as the ceiling of the new regime, not its average, and three consecutive quarters below 100t would signal the transition toward the bear case's demand assumption.

One contrary view deserves a fair hearing: that official buying no longer matters for price. Steelmanning it, gold fell 27% from January to June 2026 *despite* record ETF holdings and a record Q2 of central-bank buying — proof, the argument goes, that macro (real yields) overwhelms flows. [S3] Flows don't set direction in a macro shock; they set the floor.

### The 2027 Band and Its Verification Schedule

The lower half of the band requires Poland stopping at 700t, Turkey reverting to net sales under renewed stress, and no new large entrants; A return to 1,000t+ — the level needed to supercharge the bull case — has no visible buyer pipeline and is not in our band.

Verification comes on a fixed public calendar, and each release can shift the scenario weights:

- The WGC Gold Demand Trends Q3 2026 report, due end-October 2026 in the same week as the 28 October FOMC, gives the first read on whether H2 is tracking toward our band. [S16]
- Monthly WGC central-bank commentary tracks the NBP program specifically; a Poland print of zero for two consecutive months is the cleanest single signal that the largest buyer has exited, and would move probability mass from the base case toward consolidation.
- two consecutive quarters below 100t net is an explicit falsification criterion for the base case set out in Chapter 3.

The de-dollarization floor is real;

## Private Investment Flows, Inflation Hedging and the Supply Backdrop

### The Contrarian ETF Floor: Record Holdings Buying a Falling Price

A separate WGC post printed 4,189t on +121t, an apparent vintage difference that readers should treat as a data-revision caveat rather than a contradiction. Either way, the direction is unambiguous: Western ETF investors were buying the ~27% correction from January's $5,501.70 all-time high rather than capitulating into it. [S3]

This behavior is the mechanical underpinning of the base case's demand floor. Flatness at the flagship fund combined with record aggregate holdings implies the marginal September inflow was concentrated in other funds and regions — a broader-based bid than a single-fund momentum trade would suggest.

But the same structure creates fragility. A record 4,256t stock is also a record quantity of gold that could, under the wrong macro shock, be liquidated. The bear scenario of Chapter 4 does not require ETF investors to abandon gold philosophically; Conversely, a repeat of September's pattern — inflows into a falling or flat price — would confirm the floor and, historically, has preceded recoveries.

### Futures Positioning and the Retail Channel: A Crowd That Is Leaving, Not Chasing

If ETF investors are contrarian buyers, the COMEX speculative crowd is the opposite: long, but steadily reducing exposure. This is not a crowded-long configuration of the kind that precedes violent liquidations — it is a cautious one, with speculators trimming into weakness rather than doubling down. It removes one source of downside fuel (there is less speculative length to unwind in a squeeze), but it also means the marginal price-setter on the futures side is agnostic, leaving the direction of travel to be determined by the ETF and official-sector flows and by the Fed path.

The Asian retail bar-and-coin channel — the third pillar of private demand — is harder to read at this horizon because the research record is thin. A central bank pulling metal out of foreign vaults signals a preference for unencumbered physical possession that typically accompanies elevated private accumulation in the same countries.

### The Inflation Wedge: One Number, Two Scenarios

The most important single relationship in the private-demand story is the wedge between realized inflation and anchored expectations. That is a strange configuration: consumers feel 4% inflation, the bond market prices 2.35%, and the realized print sits at 3.7%.

The wedge resolves in one of two directions, and the direction determines the scenario. If CPI stays sticky above 3% through H1 2027, it validates the roughly 77bp of cumulative Fed tightening markets price through October 2027 and the 73.3% probability of ending December 2026 at 4.00–4.25%. Higher policy rates push the 10-year TIPS yield — already at the top of its five-year range after a +0.889pp year-over-year rise [S5] — into genuinely unprecedented territory, raising gold's opportunity cost and crushing the private bid.

If instead CPI converges toward its January 2026 low of 2.391% [S6] — a path consistent with the September SEP's projection of PCE inflation falling to 2.4% in 2027 — the hawkish pricing unwinds, real yields drift down from the top of their range, and the inflation-hedge motive hands off cleanly to the monetary-easing motive. a confirmation or downward revision would favor the base.

The steelman against our base-case reading deserves stating plainly.

### Supply: The Non-Driver That Simplifies the Forecast

The supply side, by contrast, is almost boringly benign — which is analytically useful.

First, there is no supply squeeze to underwrite the bull case. Mine output at record highs means no production shortfall will do the work.

Second, recycling is the supply-side safety valve that actually strengthens the mid-range scenarios.

One asymmetry deserves emphasis. Record mine supply is bearish-lean in a demand downturn: if the bear squeeze fires and ETF holders liquidate 4,256t of stock into a market already receiving record mine output, the downside overshoot below $3,800 could be sharp. The supply non-driver is neutral for price formation but not neutral for price volatility — it amplifies whichever demand scenario wins.

### What to Watch: The Monthly Flow Scorecard

continued trimming supports consolidation.

## Forecast Cross-Checks: Banks, Futures, Options and Ratio Signals

This chapter benchmarks our central forecast (P50 near $4,500–$4,700, P10 near $3,700, P90 near $5,600) against each of these reference points, explains where and why we deliberately sit between them, and runs two independent cross-checks — options-implied volatility and metal ratio signals — before assessing how much weight the far-dated futures curve deserves at all.

### The Bank Consensus: $5,000–$5,600, Built on Easing Assumptions

That revision mechanism matters more than the number. When the Fed path moved against the model, the target moved with it — evidence that bank targets are conditional forecasts, not unconditional ones.

The steelman for the banks is straightforward: their models are right about the demand side. If official and ETF demand persist at anything like these levels, the moment real yields crack, price discovers substantially higher levels quickly. Our response is that this argument prices the *catalyst* as if it had already arrived.

### The Futures Curve and Its Limitations

Against the banks stands the COMEX curve. Our base case ($4,300–$5,200, 34%) and consolidation case ($3,800–$4,300, 28%) together dominate the distribution precisely because the market's own pricing validates the lower half of the range: a 62% combined probability that gold ends 2027 at or below $5,200 is consistent with a curve that carries only modest contango from spot of roughly $4,099.

But the futures signal must be heavily discounted, and the reason is structural rather than interpretive. it represents a thin market where a handful of positions can move the printed price by tens of dollars.

### The Options Cross-Check: Volatility-Implied Bands

The cleanest independent check on our P10–P90 width comes from the options market. Against this, our P10 of ~$3,700 and P90 of ~$5,600 are comfortably inside the options-implied one-sigma envelope; indeed, our distribution is *narrower* than the flat-volatility one-sigma band, which is appropriate because P10/P90 are quantiles of a distribution whose central mass clusters near the futures-implied center, not a mechanical standard deviation.

The options check also disciplines the bull case. Polymarket prices only a 3% probability that COMEX gold touches $6,000 by end of December 2026.

### Ratio Signals: Gold/Silver and Gold/Copper

Ratio cross-checks confirm that gold is neither at monetary-stress extremes nor in an industrial-demand divergence. It is consistent with our base case of a grind, not a break.

The gold/copper check points the same direction. Global copper at $13,542.8/t in July 2026 sits near the top of its five-year range of $12,528.7 to $13,552.0 [S33] — copper is not pricing global recession. If recession risk were being priced into industrial metals, copper nearer the bottom of that range would corroborate the bull-case gold narrative; This is a genuine tension in our own framework: either copper is complacent or gold's crisis premium is premature. Our resolution is temporal — copper leads coincident activity while gold leads policy expectations — so the combination (strong copper, resilient gold above $4,000) is most consistent with the base case in which growth slows enough to bring Fed cuts by mid-to-late 2027 without a hard landing first. [S3]

### Where We Sit and Why

Synthesizing the cross-checks:

- We do, however, let the banks' demand-side logic drive our P90 near $5,600 — if their easing assumption is right, their price is roughly right. [S12]

The pattern across all four reference points is that our forecast is a weighted blend rather than a bet on any single forecaster: roughly the futures-implied center plus a premium for official-demand persistence, capped below bank consensus by the hostile real-yield regime.

## Key Turning Points and Observable Signposts Through 2027

A forecast that cannot be updated is a forecast that cannot be used. they are prior weights that should be revised as evidence arrives. The organizing principle is that almost all of the information content in the gold price over the next fourteen months will arrive through a small number of recurring channels — FOMC decisions and SEP revisions, monthly CPI prints, the 10-year TIPS yield, the trade-weighted dollar, and the World Gold Council's flow reports — and each channel has a level at which the underlying regime changes. [S49]

### The Opening Cluster: Late October Through December 2026

The forecast window opens with an unusually dense catalyst cluster, and the first six weeks will do disproportionate work in separating the scenarios.

**28 October 2026 FOMC.** The Fed decides between holding at 3.75–4.00% and hiking to 4.00–4.25%, with market pricing at 83.9% hold / 16.1% hike per Fed Rate Monitor — a finely balanced decision in which a one-in-six hike probability is far from negligible. A hold leaves the framework intact. Scenario instruction: an October hike moves roughly 5–8 probability points from base/consolidation toward the bear real-yield squeeze.

The report will answer three questions. Third, did the National Bank of Poland — 648t held at end-August after +98t YTD — complete or approach its 700t target ? Scenario instruction: two consecutive quarters of sub-100t official net buying would kill the base case as specified in Chapter 3; a Q3 print above ~150t with NBP still active re-weights toward base.

**3 November 2026: US midterms.** The midterms test the administration's tariff-and-sanctions posture, the policy source behind the tariff-driven inflation concerns cited in 2026 gold trading.

The falsification logic is precise: the bear case requires sticky inflation to force the Fed to validate market pricing, so an upward revision to the 2027 PCE median — toward or above 3% — would favor the real-yield squeeze. That market-versus-SEP gap is itself the leading indicator. It is internally contradictory — the SEP implies the market is overpricing hikes — and its resolution direction determines the year. Repricing toward cuts (the gap closing from the dovish side) marks the turn toward the base and bull scenarios; the SEP capitulating toward the market's hawkish path validates the bear.

### The Standing Monthly and Quarterly Gauges

Between the headline events, four recurring series carry most of the updating information. Each has a threshold at which the scenario weights should move.

**1. The 10-year TIPS yield (DFII10) — the cleanest discriminator.** At 2.638% for September 2026, the monthly mean sits at the top of its five-year range, and the daily print reached 2.77% on 20 October 2026. Two thresholds matter.

**2. CPI year-over-year (CPIAUCSL) — the wedge gauge.** The current configuration is CPI at 3.717% against the January 2026 low of 2.391%. Convergence toward the January low supports Fed easing and unlocks the base case; The breakeven companion matters too: 10-year breakevens at 2.351% are anchored [S7], so the wedge can only close through realized inflation falling — a combination (falling CPI, anchored breakevens) that is bullish gold via the real-yield channel even though it looks disinflationary. Watch also the University of Michigan series (4% in August 2026, down 0.8pp y/y) for any renewed rise above 5%, which would resurrect the 2025-style hedging bid [S31].

**3. The trade-weighted dollar (DTWEXBGS) — the breakout gauge.** The nominal broad index stood at 119.2152 for September with a daily print of 121.4048 on 16 October 2026 [S29]; Below that, the dollar is a secondary driver — the past year proved that gold can fall with a soft dollar when real yields surge. use DTWEXBGS as the primary.

**4. Thresholds: two consecutive months of ETF outflows exceeding ~50t cumulatively would crack the contrarian floor built by September's $10bn inflow into a falling price; official monthly net buying below ~30t for two months running signals the flow regime is deteriorating toward the consolidation scenario's ~600t/yr pace or worse.

### The 2027 Calendar and the Asymmetric Second Half

Against this, the price floor test: gold traded down to $3,994.50 on 25 June 2026 and held; [S3]

Polymarket's own pricing is a useful calibration anchor here: the market puts only 3% on gold hitting $6,000 by end-December 2026 [Polymarket market data], consistent with our view that the bull case is a 2027-full-year scenario, not a near-term one.

Watch the pricing gap at each meeting: the moment Central Bank Watch's cumulative path through the following October flips from tightening to easing is the moment the bull scenario's probability floor is established [S16].

The April–May French rounds land precisely at the bear/bull inflection window — a euro-crisis-scale shock there would compress real yields via a flight-to-quality bid, an underappreciated channel by which a geopolitical event can be bullish gold even without Fed action.

### The Consolidated Scorecard

| Date | Signpost | Metric & threshold | Scenario impact |
|---|---|---|---|
| 28 Oct 2026 | FOMC | — | Hike: +5–8 pts to bear; hold: status quo |
| End-Oct 2026 | WGC Q3 GDT | Official net >150t; NBP still buying | Low print kills base; strong print confirms |
| Early Nov 2026 | WGC ETF report | October flows vs +67t record | Outflow >50t starts floor-crack clock |
| 3 Nov 2026 | US midterms | Tariff agenda constrained or entrenched | Entrenchment keeps CPI wedge open (bear-tilt) |
| 9 Dec 2026 | FOMC + SEP | — | Upward revision favors bear |
| Monthly | DFII10 | — | Fall → base; new highs → bear |
| Monthly | CPI y/y | Below 3% vs above 3% [S6] | above confirms bear |
| Daily | DTWEXBGS | — | Breakout regime → bear strengthening |
| 27 Jan–27 Oct 2027 | FOMC ×4–8 | Priced path flips from +77bp tightening to easing | Flip toward cuts marks the bull floor |
| — | France rounds | Sovereign spread stress | Crisis → bull via yield compression |
| — | Recession gauges | NY Fed spread model, payrolls | — |
| Q3 2027 | First Fed cut | Delivered vs Goldman's June call | Cut + DFII10 −0.5pp → upper base band |
| — | Poland/Italy votes | Fiscal premium transmission | Sustains hedging bid either scenario |

Two cross-cutting caveats keep this scorecard honest. First, the market-versus-SEP gap means several signposts point in opposite directions simultaneously by construction — markets price hikes the SEP does not endorse — so single data points should never move weights by more than mid-single digits; regime confirmation requires the threshold to hold on a sustained (monthly-average, multi-meeting) basis. The scorecard should therefore be scored primarily on LBMA p.m. auction prints, FRED monthly series, and WGC quarterly reports — the three data rails robust enough to bear the weight of a year's worth of probability updating.

## Binary Forecast Ledger: Twelve Price Milestones with Resolution Criteria

This chapter converts the report's scenario framework and macro evidence into twelve falsifiable binary forecasts, each anchored to a verifiable market print with an explicit resolution date and data source. consolidation 28% at $3,800–$4,300; bear 21% at ≤$3,800; bull 15% at >$5,200; residual 3%), or taken directly from market pricing and survey evidence in the research base, so that by 31 December 2027 any reader can score this report line by line. Two conventions apply throughout. First, "trades above X at some point" resolves on any LBMA a.m. or p.m. auction on 31 December 2027 as administered on LBMA's published prices pages, with the COMEX December 2027 contract (GCZ7) settlement as fallback. [S23]

### Path Milestones: Intra-2027 Price Excursions

**B1.
The bear scenario contributes almost nothing. Resolution: any LBMA a.m./p.m.

**B2.

**B3.
a fresh all-time high most likely requires the geopolitical or debt-crisis variant of the bull case — an Iran-War-style shock of the kind that saw Turkey mobilize roughly $20bn of official gold in five weeks in April 2026 — rather than policy easing alone. [S3] Because the record itself is an a.m. print and the research base does not document the corresponding p.m. level, we anchor strictly on the a.m.

**B4.
The complement of B2 is not the right guide here: this is the single most symmetric forecast in the ledger.

### Terminal Milestones: Where Gold Ends 2027

The next five forecasts resolve on a single day and map directly onto the scenario weights.

**B5.
Resolution: LBMA p.m. on 31 December 2027 above $4,099 [S56].

**B6.
Resolution: LBMA p.m.

**B7.
We pre-commit to resolving this on the LBMA p.m.

**B8.
Identical by construction to the bull weight, since the scenario resolves on the same print. The key inputs are the recession odds divergence (J.P. Resolution: LBMA p.m. 31 December 2027 above $5,200.00 [S56].

**B9.
Again identical to the bear weight. Resolution: LBMA p.m. 31 December 2027 at or below $3,800.00 [S56].

### Non-Price Milestones: Policy, Official Demand and Market Pricing

Three forecasts resolve on data other than the gold price itself, testing the causal chain rather than the outcome.

**B10.
This is the single most informative near-term fork for the ledger: a hike validates the bear path's first domino; a hold with dovish rhetoric would prompt us to shift several points from bear and consolidation into base.

**B11.

**B12.
The market itself prices this at roughly 3% implied Yes [Polymarket signal], and we concur with slight rounding.

### Reading the Ledger as a System

Three internal-consistency properties are worth stating explicitly.

## Forecast Summary Table, Calibration and Divergences

The preceding chapters built the forecast piece by piece: the baseline, the macro axis, the demand floors, the cross-checks, the signposts and the binary ledger. This closing chapter assembles everything into a single reference table, then does the three things a forecast document owes its readers at the end: it shows where the probabilities came from (calibration), where they disagree with every major external anchor (divergences), and what would force the authors to change their minds (revisit conditions and decision implications).

### The Consolidated Forecast Table

**Central distribution (LBMA p.m.

| # | Scenario | Probability | Resolution band (LBMA p.m., 31 Dec 2027) | Core mechanism | Primary falsifier |
|---|---|---|---|---|---|
| 1 | Base — grind higher | **34%** | $4,300–$5,200 | Real yields mean-revert from a 98th-percentile extreme [S5]; CPI converges from 3.717% toward the 2.391% January low [S6]; | Two consecutive quarters of sub-100t official net buying; |
| 2 | Range-bound consolidation | **28%** | $3,800–$4,300 | — | — |
| 3 | Bear — real-yield squeeze | **21%** | ≤ $3,800 | Fed validates ~77bp of priced tightening; ETF outflows from the record 4,256t stock | sustained ≥0.5pp fall in DFII10 |
| 4 | Bull — policy/crisis premium | **15%** | > $5,200 | Recession (JPM ~40% [S47]; election-calendar hedging | — |
| 5 | Residual | **3%** | — | Resolution failure or systemic tail | — |

above $5,000 — **40%**; below the $3,994.50 June 2026 low — **45%**; ending above $4,099 — **55%**; ending above $4,363.70 — **45%**; ending above $5,200 — **15%**; ending at or below $3,800 — **21%**;

### Calibration: Where the Probabilities Came From

The weights above were not derived from any single forecaster, and it is worth stating the arithmetic lineage explicitly, because calibration is the difference between a forecast and an opinion.

A pure real-yield model would assign more than a fifth to the squeeze.

### The Four Deliberate Divergences

This report disagrees — knowingly and for stated reasons — with every major external anchor. Readers deserve the disagreements in one place.

**Versus Polymarket's 3% on $6,000.** The prediction market prices a 3% chance of gold touching $6,000 by end-December 2026 [Polymarket market data].

**Versus J.P. SEP median at 4.25% through 2028 [S15]). Our concession to the banks is the P90 at $5,600: if their easing assumption is right, their price is roughly right. [S12]

The floor changed the level; it did not repeal the slope.

### Structural Uncertainties the Reader Should Carry

Four data defects were flagged in earlier chapters and belong in the closing record. WGC ETF data showed a vintage dispute (4,256t/+67t versus 4,189t/+121t), meaning early flow reads can revise. Far-dated COMEX liquidity is thin enough that GCZ7 prints should never move anyone's weights much. None of these defects changes the modal outcome; all of them argue for the width of the distribution and the medium — not high — confidence label.

### Decision Implications and When to Revisit

The forecast should be formally revisited on four triggers, all observable. Second, **two consecutive quarters of sub-100t official net buying** — the demand-floor crack that converts consolidation into bear. prints, FRED monthly series, and WGC quarterly flows.

The tables above are the audit trail; the signposts are the clock;

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/gold-2027/charts/timeline_lanes.png)

*Event Timeline*

<!-- viz:charts/worldstate_trajectory.html -->
![Simulated outcome-share trajectory](demos/gold-2027/charts/worldstate_trajectory.png)

*Simulated outcome-share trajectory*

<!-- viz:charts/world_variables.html -->
!

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[34%] base: grind higher ($4,300-$5,200)**: LBMA p.m. gold price on 31 Dec 2027 is >= $4,300 and <= $5,200 per troy ounce.
- **[21%] bear: real-yield squeeze (<= $3,800)**: LBMA p.m. gold price on 31 Dec 2027 is <= $3,800 per troy ounce.
- **[28%] range-bound consolidation ($3,800-$4,300)**: LBMA p.m. gold price on 31 Dec 2027 is > $3,800 and < $4,300 per troy ounce.
- **[15%] bull: policy/crisis premium (> $5,200)**: LBMA p.m. gold price on 31 Dec 2027 is > $5,200 per troy ounce.
- **[3%] other/maintain-status-quo residual (price in a band boundary dispute or data failure)**: LBMA p.m. gold price on 31 Dec 2027 is unavailable, or the price falls so far outside all four bands that none applies (outside approximately $2,000-$6,500).

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | next monthly release after 2026-09 | — |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed (fred:DFII10) | next monthly release after 2026-09 | — |
| Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) (fred:CPIAUCSL#yoy) | next monthly release after 2026-09 | — |
| 10-Year Breakeven Inflation Rate — United States (fred:T10YIE) | next monthly release after 2026-09 | — |
| Nominal Broad U.S. Dollar Index (fred:DTWEXBGS) | next monthly release after 2026-09 | — |
| Effective exchange rates: United States - Real - Broad (64 economies) (bis:WS_EER/M.R.B.US) | next monthly release after 2026-09 | — |
| University of Michigan: Inflation Expectation (fred:MICH) | next monthly release after 2026-08 | — |
| Central bank policy rates - China - Monthly - End of period (bis:WS_CBPOL/M.CN) | next monthly release after 2026-09 | — |
| Global price of Copper (fred:PCOPPUSDM) | next monthly release after 2026-07 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | 3.875% (2026-09) | > 3.875% / 2026-12 | 20% (n=237, h=3) vs model 68% | [Source](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S4] |
| Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) (fred:CPIAUCSL#yoy) | 3.717% (2026-09) | > 3% / 2026-12 | insufficient history vs model 75% | [Source](<https://fred.stlouisfed.org/series/CPIAUCSL>) [S6] |
| Central bank policy rates - China - Monthly - End of period (bis:WS_CBPOL/M.CN) | 3% (2026-09) | < 3% / 2026-12 | 28% (n=116, h=3) vs model 18% | [Source](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.CN>) [S32] |
| Nominal Broad U.S. Dollar Index (fred:DTWEXBGS) | 119.2152 Index Jan 2006=100 (2026-09) | > 122 Index Jan 2006=100 / 2026-12 | 15% (n=117, h=3) vs model 20% | [Source](<https://fred.stlouisfed.org/series/DTWEXBGS>) [S29] |
| 10-Year Breakeven Inflation Rate — United States (fred:T10YIE) | 2.351% (2026-09) | > 2.5% / 2026-12 | 21% (n=117, h=3) vs model 33% | [Source](<https://fred.stlouisfed.org/series/T10YIE>) [S7] |

<!-- drf-news-market-context:4a4dc07c74b8f50dc54383a89918aaa9717a12a4c80cc576266d448abb2b61b6:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:4a4dc07c74b8f50dc54383a89918aaa9717a12a4c80cc576266d448abb2b61b6:end -->

<!-- forecast-track-record:start -->
## Historical forecasting track record

These scores describe retained forecasts with recorded outcomes. A limited record does not establish calibration.

| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |
|---|---:|---:|---:|---:|
| Scenarios (multiclass) | 0 | 0 | 0 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 0 | 0 | 0 | — |
| Unanchored binaries | 0 | 0 | 0 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S5] Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DFII10](https://fred.stlouisfed.org/series/DFII10)
2. [S4] Central bank policy rates - United States - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US)
3. [S29] Nominal Broad U.S. Dollar Index — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DTWEXBGS](https://fred.stlouisfed.org/series/DTWEXBGS)
4. [S30] Effective exchange rates: United States - Real - Broad (64 economies) — data.bis.org — [https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.US](https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.US)
5. [S7] 10-Year Breakeven Inflation Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T10YIE](https://fred.stlouisfed.org/series/T10YIE)
6. [S31] University of Michigan: Inflation Expectation — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/MICH](https://fred.stlouisfed.org/series/MICH)
7. [S32] Central bank policy rates - China - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.CN](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.CN)
8. [S6] Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL)
9. [S33] Global price of Copper — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/PCOPPUSDM](https://fred.stlouisfed.org/series/PCOPPUSDM)
10. [S2] Gold Prices - 100 Year Historical Chart — macrotrends.net — [https://www.macrotrends.net/1333/historical-gold-prices-100-year-chart](https://www.macrotrends.net/1333/historical-gold-prices-100-year-chart)
11. [S3] LBMA Precious Metals Market Report: Q2 2026 | LBMA — lbma.org.uk — [https://www.lbma.org.uk/articles/lbma-precious-metals-market-report-q2-2026](https://www.lbma.org.uk/articles/lbma-precious-metals-market-report-q2-2026)
12. [S12] Gold Price Forecast 2027 — bullionstar.com — [https://www.bullionstar.com/blogs/gold-silver-101/gold-price-forecast-2027/](https://www.bullionstar.com/blogs/gold-silver-101/gold-price-forecast-2027/)
13. [S47] What Is the Probability of a Recession? | J.P. Morgan Research — jpmorgan.com — [https://www.jpmorgan.com/insights/global-research/economy/recession-probability](https://www.jpmorgan.com/insights/global-research/economy/recession-probability)
14. [S15] Summary of Economic Projections, September 16, 2026 — federalreserve.gov — [https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20260916.pdf](https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20260916.pdf)
15. [S50] 2027, year of elections. Which countries will go to the polls and how will the market react? - RankiaPro — rankiapro.com — [https://rankiapro.com/en/insights/2027-elections-markets-investors/](https://rankiapro.com/en/insights/2027-elections-markets-investors/)
16. [S48] US recession by end of 2027? Trading Odds & Predictions | Polymarket — polymarket.com — [https://polymarket.com/event/us-recession-by-end-of-2027-20260807185409760](https://polymarket.com/event/us-recession-by-end-of-2027-20260807185409760)
17. [S18] Gold Dec 2027 Futures Prices and News | GCZ27 — wsj.com — [https://www.wsj.com/market-data/quotes/futures/GCZ27](https://www.wsj.com/market-data/quotes/futures/GCZ27)
18. [S37] Fed Rate Odds: FOMC Meeting Probabilities (Fed Funds Rate) — rateprobability.com — [https://rateprobability.com/fed](https://rateprobability.com/fed)
19. [S23] Gold Price on 31 December 2025 — goldprice.org — [https://goldprice.org/gold-price-today/2025-12-31](https://goldprice.org/gold-price-today/2025-12-31)
20. [S55] LBMA Precious Metal Prices — lbma.org.uk — [https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices](https://www.lbma.org.uk/prices-and-data/lbma-precious-metal-prices)
21. [S56] LBMA Gold Price — lbma.org.uk — [https://www.lbma.org.uk/prices-and-data/lbma-gold-price](https://www.lbma.org.uk/prices-and-data/lbma-gold-price)
22. [S16] Fed Rate Probability | FOMC Meeting Odds & Rate Cut Forecast 2026 — centralbank.watch — [https://centralbank.watch/federal-reserve/](https://centralbank.watch/federal-reserve/)
23. [S49] [PDF] Probability of US Recession Predicted by Treasury Spread — newyorkfed.org — [https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf](https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf)
