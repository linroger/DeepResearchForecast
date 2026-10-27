# Anchored at the Summit: A Probabilistic Forecast of the US 10-Year Treasury Yield at December 31, 2027

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/ust10y-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | The US 10-year Treasury constant maturity yield (fred:DGS10) monthly mean is above 5.5 percent in December 2027. | 24% | Resolves YES if fred:DGS10 > 5.5 percent in 2027-12 (source: FRED). Official resolution: fred:DGS10 > 5.5% for 2027-12. | term premium bear steepening | 29% (n=224, h=15) |
| F2 | The US 10-year Treasury constant maturity yield (fred:DGS10) monthly mean is below 4.75 percent in December 2027. | 39% | Resolves YES if fred:DGS10 < 4.75 percent in 2027-12 (source: FRED). Official resolution: fred:DGS10 < 4.75% for 2027-12. | disinflation and recession downside | 41% (n=224, h=15) |
| F3 | The US 10-year Treasury constant maturity yield (fred:DGS10) monthly mean is below 4.0 percent in December 2027. | 15% | Resolves YES if fred:DGS10 < 4.0 percent in 2027-12 (source: FRED). Official resolution: fred:DGS10 < 4% for 2027-12. | recession flight to quality | 16% (n=224, h=15) |
| F4 | The term premium on a 10-year zero-coupon bond (fred:THREEFYTP10) monthly mean is at least 1.5 percent in December 2027. | 20% | Resolves YES if fred:THREEFYTP10 >= 1.5 percent in 2027-12 (source: FRED). | term premium bear steepening | — |
| F5 | The US central bank policy rate (bis:WS_CBPOL/M.US) end-of-period value is at most 3.5 percent per year in December 2027. | 30% | Resolves YES if bis:WS_CBPOL/M.US <= 3.5 per cent per year in 2027-12 (source: BIS). Official resolution: bis:WS_CBPOL/M.US <= 3.5% for 2027-12. | fed easing path | 40% (n=104, h=15) |
| F6 | The real-time Sahm Rule recession indicator (fred:SAHMREALTIME) reaches at least 0.50 percentage points in some month of 2027. | 18% | Resolves YES if fred:SAHMREALTIME >= 0.50 percentage points in any single month from 2027-01 through 2027-12 (source: FRED). | recession risk | — |
| F7 | The 10-year minus 2-year Treasury spread (fred:T10Y2Y) monthly mean is at least 0 percent in December 2027. | 75% | Resolves YES if fred:T10Y2Y >= 0 percent in 2027-12 (source: FRED). Official resolution: fred:T10Y2Y >= 0% for 2027-12. | curve shape regime | 65% (n=105, h=15) |
| F8 | The 5-year, 5-year forward inflation expectation rate (fred:T5YIFR) monthly mean is below 2.1 percent in December 2027. | 30% | Resolves YES if fred:T5YIFR < 2.1 percent in 2027-12 (source: FRED). Official resolution: fred:T5YIFR < 2.1% for 2027-12. | long-run inflation expectations | 14% (n=105, h=15) |
| F9 | University of Michigan 1-year inflation expectations (fred:MICH) are at least 4 percent in June 2027. | 60% | Resolves YES if fred:MICH >= 4 percent in 2027-06 (source: FRED). | sticky household inflation | — |
| F10 | The 10-year breakeven inflation rate (fred:T10YIE) monthly mean is at most 2.5 percent in December 2027. | 85% | Resolves YES if fred:T10YIE <= 2.5 percent in 2027-12 (source: FRED). Official resolution: fred:T10YIE <= 2.5% for 2027-12. | anchored inflation compensation | 71% (n=105, h=15) |
| F11 | The Monthly Treasury Statement current-month deficit (usgov:treasury/mts_deficit) is at least $150 billion in April 2027. | 70% | Resolves YES if usgov:treasury/mts_deficit <= -150000000000 U.S. dollars in 2027-04 (source: Treasury Fiscal Data). | fiscal deficits | — |
| F12 | Federal Reserve total assets (fred:WALCL) are at least 6,700,000 millions of US dollars on the last Wednesday-level release of December 2027. | 80% | Resolves YES if the final fred:WALCL Wednesday observation of 2027-12 is >= 6,700,000 millions of U.S. dollars (source: FRED). | fed balance sheet regime | — |

_12 forecasts; 10 high-conviction (≥70% or ≤30%); 12 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis | Percent | 4.989% | 2026-09 | +0.869 pp | 1.37% to 4.989% | 5.202% (2026-10, partial-period value) | [S1] |
| 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States | Percent | 0.338% | 2026-09 | -0.214 pp | -0.93% to 1.19% | 0.4% (2026-10, partial-period value) | [S2] |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States | Percent | 0.896% | 2026-09 | +0.841 pp | -1.73% to 1.98% | 0.938% (2026-10, partial-period value) | [S3] |
| Central bank policy rates - United States - Monthly - End of period | Per cent per year | 3.875% | 2026-09 | -0.25 pp | 0.125% to 5.375% | — | [S8] |
| Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States | Millions of U.S. Dollars | 6753604 | 2026-10-21 | — | 6535781 to 8965487 | — | [S17] |
| 10-Year Breakeven Inflation Rate — United States | Percent | 2.351% | 2026-09 | -0.02 pp | 2.11% to 2.88% | 2.348% (2026-10, partial-period value) | [S4] |
| 5-Year, 5-Year Forward Inflation Expectation Rate — United States | Percent | 2.34% | 2026-09 | +0.022 pp | 2.05% to 2.46% | 2.318% (2026-10, partial-period value) | [S5] |
| University of Michigan: Inflation Expectation | Percent | 4.6% | 2026-09 | -0.1 pp | 2.6% to 6.6% | — | [S12] |
| Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) — United States | U.S. dollars | -26900347102.02 (≈ -26.9 billion U.S. dollars) | 2026-09 | -224849977464.18 (≈ 224.85 billion U.S. dollars; -113.589%) | -432307874621.48 (≈ -432.31 billion U.S. dollars) to 308215060526.79 (≈ 308.22 billion U.S. dollars) | — | [S18] |
| Term Premium on a 10 Year Zero Coupon Bond — United States | Percent | 0.96% | 2026-09 | +0.499 pp | -0.193% to 0.96% | 1.059% (2026-10, partial-period value) | [S6] |
| Fitted Yield on a 10 Year Zero Coupon Bond — United States | Percent | 5.003% | 2026-09 | +0.827 pp | 1.499% to 5.003% | 5.228% (2026-10, partial-period value) | [S7] |
| Real-time Sahm Rule Recession Indicator — United States | Percentage Points | 0 | 2026-09 | -0.23 | -0.07 to 0.43 | — | [S13] |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed | Percent | 2.638% | 2026-09 | — | 1.825% to 2.638% | 2.838% (2026-10, partial-period value) | [S16] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/ust10y-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DGS10>) [S1]; Percent; Monthly; NSA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8]; Per cent per year; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10Y2Y>) [S2]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10YIE>) [S4]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T5YIFR>) [S5]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10Y3M>) [S3]; Percent; Monthly; NSA · [U.S. Treasury Fiscal Data (Bureau of the Fiscal Service)](<https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/>) [S18]; U.S. dollars; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/WALCL>) [S17]; Millions of U.S. Dollars; Weekly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/MICH>) [S12]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/THREEFYTP10>) [S6]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/THREEFY10>) [S7]; Percent; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SAHMREALTIME>) [S13]; Percentage Points; Monthly; SA*

<!-- viz:charts/official_indicators_more.html -->
![Official Indicators](demos/ust10y-2027/charts/official_indicators_more.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DFII10>) [S16]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_pnblmbnsemplblel.html -->
![Official Series History and Forecast Thresholds](demos/ust10y-2027/charts/official_series_pnblmbnsemplblel.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DGS10>) [S1]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_eaeoofrpnafnqllo.html -->
![Official Series History and Forecast Thresholds](demos/ust10y-2027/charts/official_series_eaeoofrpnafnqllo.png)

*Official Series History and Forecast Thresholds*

*Source: [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8]; Per cent per year; Monthly; adjustment unknown*

<!-- viz:charts/official_series_qbsedfnnpbbecrna.html -->
![Official Series History and Forecast Thresholds](demos/ust10y-2027/charts/official_series_qbsedfnnpbbecrna.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10Y2Y>) [S2]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_korolrkrnbnmqope.html -->
![Official Series History and Forecast Thresholds](demos/ust10y-2027/charts/official_series_korolrkrnbnmqope.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T10YIE>) [S4]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_oeledsttfrqdpqkf.html -->
![Official Series History and Forecast Thresholds](demos/ust10y-2027/charts/official_series_oeledsttfrqdpqkf.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/T5YIFR>) [S5]; Percent; Monthly; NSA*

## Part 2 — Framework & Synthesis

### Analytical Framework

The framework decomposes the yield into two additive components and treats each as a separate forecasting problem with its own evidence base.

The residual — roughly 4 percentage points — is the market-implied average expected short rate over the next ten years. This split is the analytical spine of the entire forecast, because the two components are driven by different forces, move on different news, and have different volatilities.

The term premium is the swing factor. Roughly three-fifths of the year's 0.827pp rise in the fitted 10-year yield was compensation, not expected rates [S7]. The scenario probabilities therefore differ mainly on where the term premium goes, not on the expected-rate path.

the fiscal supply path; recession indicators; and observable signposts (quarterly refunding statements, monthly CPI/PCE, TIC data, NY Fed recession-probability updates) that would force probability updates before the deadline.

### Baseline: Where We Stand

DGS10 printed 5.13% on October 21, 2026, against a September monthly mean of 4.989% — both at the top of the five-year stored range of 1.37% (September 2021) to 4.989% (September 2026). The year-over-year change is +0.869pp [S1].

Two features of this baseline discipline the forecast. First, the 10-year TIPS yield of 2.638% (September 2026 monthly mean, 2.64% daily on October 22) is itself at the top of its five-year range, so the move is a real-yield and term-premium phenomenon, not an inflation-expectations one. The 10-year breakeven is 2.351% and the 5y5y forward 2.34% — both comfortably within recent ranges and near the Fed's target [S4]. Second, the Michigan one-year household measure at 4.6% sits far above market breakevens [S12]; the framework treats market-based measures as decision-relevant for the Fed and household surveys as a risk marker, not a pricing input.

### Causal Logic: From Drivers to the Part-1 Probabilities

**Fed policy and the balance sheet.** These purchases, concentrated at the short end, marginally steepen the curve without changing duration supply — a modest tailwind for the term premium at the long end.

**Term premium and inflation expectations.** The framework resolves this by using Kim-Wright as the primary series (it is the FRED-published authority) and treating the ACM gap as uncertainty about the level, not the direction. Both models agree the premium has risen materially.

**Treasury supply.** Treasury's August 5, 2026 refunding statement anticipated holding nominal coupon and FRN auction sizes unchanged "for at least the next several quarters," absorbing marginal borrowing in bills [S27]. This is the decisive asymmetry in the supply channel: the coupon freeze suppresses duration supply now, but bills at a record share are a known stress point — TBAC's own analysis flagged the long-term risk — and the freeze cannot hold indefinitely against $2.4 trillion annual deficits.

**Foreign demand.** Japan and China matter through the term premium, not through any observable holdings series in the current evidence — the TIC figures for both were not captured, and no BoJ policy series is available. What can be said is that the premium's steady climb is consistent with a marginal-buyer problem: someone must be induced to absorb the incremental paper, and the price of that induction is the premium.

**Recession risk.** Every indicator is dormant. The real-time Sahm indicator is 0.0 percentage points for September 2026, down from 0.43 at its November 2025 peak [S13].

**Historical base rates.** This is the single most important piece of evidence for the modal scenario: the unconditional base rates suggest big moves are common, but conditionally, from this starting level, they are rare — and the rare large move that did occur was a recession-driven decline.

### Decisive Evidence and the Probability Weights

It is the continuation scenario, and continuation from a near-5% start has the strongest conditional base-rate support in the entire dataset [S1].

It is capped below the plateau because it needs two things to go right (disinflation and premium compression) where the plateau needs neither.

### Weighing the Market Anchors

Where market prices did exist, they were used as one input among several rather than as an anchor. Where secondary commentary (for example, the Schwab piece quoting a 3.50-3.75% range, which predates the September hike, or J.P. Morgan Asset Management's rounded dot readings [S22]) conflicted with official Federal Reserve documents, the official documents governed [S9]. The fitted-yield and term-premium decomposition — itself a market-based measure — served as the principal quantitative anchor for the expected-rate-versus-compensation split.

### Most-Likely Trajectory

Overall confidence in the spine is medium: the decomposition is well-identified, but the term premium is at a five-year high with a live fiscal trigger, and the TIC/BoJ evidence gap means the foreign-demand channel is inferred rather than measured.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Baseline: Where the 10-Year Stands and What the Curve Is Saying

This chapter establishes that baseline precisely, reads the shape of the curve around it, decomposes the move that got us here, and explains why the configuration — a near-4% policy rate, a positively sloped curve, and contained inflation pricing — reframes the entire forecast as a question about the term premium and the policy path, not about inflation expectations. [S8]

### The Level: A 99th-Percentile Starting Point

The 10-year Treasury constant maturity yield printed 5.13% on October 21, 2026, while the September 2026 monthly mean stood at 4.989%. Both readings sit at the top of the five-year stored range of 1.37% (September 2021) to 4.989% (September 2026) [S1] — the monthly mean literally marked the ceiling of its own history.

The year-over-year change is the more important datum. What matters here is *composition*: roughly three-fifths of the 0.827pp rise in the fitted yield was compensation, not expected rates. The Kim-Wright term premium on a 10-year zero-coupon bond climbed from 0.462% in September 2025 to 0.96% in September 2026, a rise of 0.499pp, ending at its five-year high [S6].

### The Curve: Positive Slope, No Recession Signal in the Spreads

Around that summit, the curve is positively and unremarkably sloped.

Two implications follow. First, neither spread is anywhere near inversion.

The evidence does not support that reading. The curve is saying "expansion, moderately priced policy" — not "late cycle."

### The Decomposition: Compensation, Not Inflation

The most consequential fact about the baseline is what did *not* drive the rise. Market-based inflation pricing is contained and stable. The 10-year breakeven inflation rate was 2.351% in September 2026 (2.34% daily on October 23), down 0.02pp year-over-year. The 5-year, 5-year forward inflation expectation rate was 2.34% in September, up just 0.022pp year-over-year [S5]. Neither series moved meaningfully while the nominal yield rose nearly a full percentage point. The arithmetic corollary is that the real yield did the work: the 10-year TIPS yield at 2.638% for September 2026 sits at the top of its five-year range of 1.825% to 2.638% [S16].

This decomposition has a direct consequence for the forecast architecture.

That leaves the term premium, at 0.96% and a five-year high [S6], as the residual that has done all the marginal work and will do it again. The premium's climb of nearly half a percentage point in twelve months against a frozen expected-rate path is the single most important trend fact in this report.

### Why the Starting Point Defines the Forecast Problem

**First, starting at a 99th percentile raises the base-rate asymmetry.**

**Second, the composition of the level matters for which catalysts bind.**

**Third, the policy anchor is explicit and dated.** The December 2026 FOMC meeting with its new SEP, and the quarterly refunding statements beginning with the expected early-November 2026 announcement [S33], are the first dated checkpoints at which this baseline can shift.

The configuration also defines what would *falsify* the framing itself. Neither has happened as of the research cutoff; the baseline stands as a high-level, positively sloped, inflation-anchored curve whose entire forward-looking risk is concentrated in two quantities: the path of the funds rate the Fed has already published, and a term premium at a five-year high with nowhere historical to go but the levels that define the scenario bands of this report.

The next three chapters examine the drivers in turn: Federal Reserve policy and balance-sheet mechanics (Chapter 2), inflation expectations and term-premium evidence (Chapter 3), and the fiscal supply-and-demand channel spanning deficits, issuance, and foreign official holders (Chapter 4). Chapter 5 then supplies the historical base rates for moves of this magnitude, and Chapters 6 through 8 assemble the mutually exclusive scenarios, the most-likely trajectory, and the binary forecast ledger with resolution criteria.

## Driver I: The Fed's Reaction Function, the Dots, and the Balance Sheet

The single most important structural fact about the 10-year yield at the end of October 2026 is that its expected-rate component is unusually well pinned. [S30] the arithmetic residual—an expected average short rate of roughly 4 percentage points over the next decade—sits almost exactly on top of where the Federal Reserve says its policy rate will be through 2028. [S28] The chapter examines why the reaction function is currently inflation-constrained, what the dots and the futures market disagree about, and how the balance sheet quietly reshapes the supply mix that Treasury must offer—before drawing the conclusion that the expected-rate component is a stabilizer, not a swing factor.

### A Reaction Function Constrained by Inflation, Not Labor

The FOMC's September 16, 2026 decision is the clearest statement of its current reaction function.

The asymmetry inside the SEP is what makes the reaction function legible. A central bank facing a labor market at equilibrium and inflation far above target has essentially one mandate-relevant variable: inflation. If it materializes, the SEP implies at most one further 25bp step and then an extended hold;

The labor-market side of the ledger currently provides no offsetting pull toward easing. The real-time Sahm indicator printed 0.00 percentage points for September 2026, having declined for ten consecutive months from a 0.43pp peak in November 2025 [S13].

### The Unresolved Wedge: Dots versus Futures

Here lies the most underappreciated tension in the policy-path outlook. Two things are striking about that path.

That reading deserves caution, and we flag it explicitly. The market is debating the Fed's plateau altitude, not whether the plateau exists.

A steelman of the opposite view is worth stating. One could argue the expected-rate component is not pinned at all: household inflation expectations at 4.6% in the Michigan survey for September 2026, against a five-year range of 2.6% to 6.6%, represent a public that does not believe the glide path [S12]. On this view, the divergence is not noise but signal. The argument runs as follows. Market-based breakevens are priced by a narrow set of arbitrage-constrained institutions whose inflation forecasts are anchored by the Fed's own reaction function; they measure what traders believe the Fed will do, not what the price-setting public expects.

Against this steelman, three considerations keep the pinned-plateau view in command. First, market-based measures are remarkably contained: the 10-year breakeven at 2.351% and the 5y5y forward at 2.34% for September 2026 show professional money pricing long-run inflation essentially at target, and these are the measures that actually trade against the Treasury's real cost of funds. Second, the Michigan series is noisy and has historically over-predicted pass-through—its five-year range of 2.6% to 6.6% swings far more than realized core inflation ever did over the same window [S12]. Third, and decisively, the Fed has historically weighted market measures more heavily in its reaction function when the two diverge;

### The Balance Sheet: From QT Drag to Short-End Buyer

QT was a persistent, mechanical drain on duration demand—the Fed was a forced seller into a market where price-sensitive private buyers had to be enticed with higher yields. That regime is over. On December 10, 2025, the FOMC judged reserves ample and announced reserve-management purchases of shorter-term Treasury securities, sized to trend liability growth plus seasonal fluctuations. [S1] Total assets stood at $6,753,604 millions on October 21, 2026, up from a trough of $6,535,781 millions on December 3, 2025 in the stored five-year window—the balance sheet has stopped shrinking and has begun, gently, to grow again [S17].

Three consequences follow for the 10-year yield through 2027. [S30]

First, the direct duration effect is small. Reserve-management purchases are concentrated at the short end of the Treasury curve, replacing maturing bills-and-coupons runoff with short-dated securities. This is a deliberate asymmetry: the Desk's mandate is reserve adequacy and market functioning, not yield suppression.

Second, and more important, the composition shift changes what Treasury must supply to private buyers. Treasury's August 2026 refunding statement explicitly cited readiness for "the size and composition of the SOMA portfolio" alongside the fiscal outlook—official acknowledgment that Fed purchases of short-dated Treasuries absorb part of the bill supply that would otherwise hit the market, while the Fed's runoff continues to return longer-dated coupons to private hands over time [S27][S33]. The net effect is a private market that must absorb a duration-heavy mix even as official holdings stabilize. The Fed's balance-sheet policy, intended to be neutral, is marginally duration-negative for the private market.

At the current trajectory—purchases sized to trend liability growth—the balance sheet grows slowly, and crossing $7.0 trillion would require either an acceleration of reserve-management purchases or a renewed episode of market-functioning intervention. Neither is in the base case, but the threshold is a clean observable for whether the Fed's stance turned actively accommodative at the short end.

### Why the Expected-Rate Component Is the Stabilizer

The plausible ways the expected-rate component moves materially are asymmetric and tail-shaped.

The 10-year yield's fate therefore rides on the term premium—currently 0.96% and climbing—whose drivers, measurement disputes and observable thresholds are the subject of the next chapter. [S6]

## Driver II: Term Premium, Inflation Expectations, and the Compensation Puzzle

The single most consequential question for the 10-year yield between now and December 2027 is not whether the Federal Reserve hikes or cuts once or twice—it is how much extra compensation investors demand for holding long-duration Treasury paper. [S30] The gap between those two numbers—roughly a percentage point and a quarter—is where the entire forecast problem lives. This chapter decomposes that gap, examines the striking disagreement among term-premium models, and asks whether the market's remarkably calm inflation pricing is a genuine signal or a trap that leaves the Fed with less room to cut than futures pricing implies.

### The Anatomy of the Rise: Compensation, Not Inflation

The year-over-year move in the fitted 10-year zero-coupon yield was +0.827 percentage points (4.177% in September 2025 to 5.003% in September 2026) [S7]. The Kim-Wright term premium decomposition attributes the bulk of that rise to compensation: the term premium on a 10-year zero-coupon bond climbed from 0.462% in September 2025 to 0.96% in September 2026, a +0.499pp move [S6]—roughly three-fifths of the total increase in the fitted yield.

What makes this climb notable is its starting point and its trend. The term premium's five-year range runs from -0.193% (September 2021) to the current 0.96%, meaning the series has moved from the bottom to the top of its range in five years. That distinction matters for forecasting. A spike driven by one auction failure or one geopolitical shock can mean-revert quickly; a grind suggests a structural repricing of duration risk, most plausibly tied to the bill-heavy issuance mix and persistent deficits documented in the fiscal baseline, and to the marginal-buyer question examined in Chapter 4.

By contrast, the inflation-expectations components have gone nowhere. The 10-year breakeven inflation rate printed 2.351% in September 2026, down 0.02pp year-over-year, inside a five-year range of 2.11% to 2.88% [S4]. The 5-year, 5-year forward inflation expectation rate—arguably the cleanest market-based read on long-run anchoring—stands at 2.34% monthly and 2.2% on the latest daily reading (2026-10-23) [S5]. The implication is direct: the 10-year yield is not high because investors expect inflation to run hot; [S30]

This configuration disciplines the scenario probabilities adopted throughout this report. These are the discriminating thresholds, and they are observable monthly on FRED.

### The Model War: Kim-Wright at 0.96% versus ACM near 0.73%

Here the evidence base is genuinely contested, and the contest is decision-relevant. Three estimates of the current 10-year term premium coexist in the record: [S30]

- This is the five-year high of the series.

The divergence therefore changes what the market is "telling" the Fed.

### The Expectations Paradox: Market Calm versus Household Alarm

The second tension in the compensation puzzle is between two populations of inflation forecasters. Market-based measures—the 10-year breakeven at 2.351% [S4] and the 5y5y forward at 2.34% —say long-run inflation expectations are anchored within a quarter point of target. The University of Michigan 1-year inflation expectation, by contrast, stands at 4.6% (September 2026) [S12], more than double the market-implied long-run rate and far above anything consistent with the Fed's 2% objective over the policy-relevant horizon.

The steelman of the household-alarm view deserves a fair hearing: survey-based measures are the inputs central banks have historically watched for unanchoring, and the 1970s taught policymakers that market breakevens can stay deceptively calm while the wage-price process deteriorates.

The reconciliation that best fits the data is that households extrapolate salient prices (groceries, rent) while markets price the policy reaction function—and it is the reaction function that binds. That is precisely the modal higher-for-longer plateau configuration: sticky-enough inflation to prevent cuts, anchored-enough expectations to prevent a premium-driven spiral.

### Thresholds That Discriminate: Reading THREEFYTP10 Through 2027

The practical output of this chapter is a monitoring grid. Because the term premium is published monthly on FRED with only a short lag [S6], it provides the fastest verifiable signal of which scenario is materializing—faster than the quarterly SEP, faster than the annual deficit outturns.

- This is the bear-steepening confirmation zone;
- **THREEFYTP10 below 0.7%.**
- This combined state is the modal scenario's fingerprint: policy on hold, compensation high but stable.
- The five-year breakeven range tops out at 2.88%; [S4] If breakevens and the term premium rose together, the bear-steepening scenario would shift from a fiscal story to a stagflationary one—an important distinction for whether the Fed could respond with cuts.

### What the Compensation Puzzle Means for the Distribution

Weighing the evidence, three judgments follow. First, the trend in the term premium is the report's strongest single empirical regularity: +0.499pp year-over-year, five of five quarters rising within 2026, and already 0.986% on the mid-October daily print [S6]. This anchors the modal scenario in the upper-4s to low-5s rather than the low-4s.

## Driver III: Deficits, Issuance Mix, and the Marginal Buyer Problem

The fiscal channel is the least ambiguous driver in this forecast. While the Fed's reaction function and inflation expectations leave room for interpretation, the supply of Treasury paper over the next fourteen months is, in aggregate, already legislated and scored.

### The Deficit Is Already Running Ahead of the Baseline

The monthly fiscal data confirm that CBO's projection is not an abstraction. The Monthly Treasury Statement recorded a September 2026 current-month deficit of roughly $26.9 billion, a year-over-year swing of about $224.8 billion from the $197.9 billion surplus recorded in September 2025 [S18]. More striking is the July 2026 print: a $432.3 billion monthly deficit, the largest in the stored five-year series [S18].

The composition of this borrowing matters more than its headline. CBO's own baseline embeds a 10-year Treasury note rate that rises gradually through 2027 and then remains relatively stable —an assumption consistent with the plateau scenario in this report—but that assumption presumes orderly absorption. [S30] The mechanism runs as follows: a deficit of this size must be financed either in bills, which the money-market complex can absorb with limited duration risk, or in coupons, which require price-sensitive buyers to commit capital for years. Every dollar pushed into bills avoids an immediate test of the long end; every dollar that migrates to coupons is a marginal demand event that clears through the term premium.

### Treasury's Coupon Freeze: A Deliberate Deferral, Not a Solution

Treasury has been explicit about its strategy. The August 2026 quarterly refunding statement, issued by Deputy Assistant Secretary for Federal Finance Brian Smith, stated that current auction sizes leave Treasury "well positioned to address potential changes to the fiscal outlook and to the size and composition of the SOMA portfolio," and that nominal coupon and FRN auction sizes would be maintained "for at least the next several quarters" [S27][S33]. Marginal borrowing needs are being absorbed in bills.

This is a rational cost-minimizing choice in the short run, but it is a deferral with a known expiry.

The freeze has two structural pressure points. First, bills mature in weeks; the strategy works only while the money-market complex—funds, foreign official bill accounts, dealers' short books—keeps rolling. But SOMA purchases are a policy variable, not a guarantee, and Treasury itself acknowledged in August that its sizing must remain flexible to "the size and composition of the SOMA portfolio". The next quarterly refunding statement—expected in early November 2026, with subsequent statements in February, May, and August 2027 [S33]—is therefore the single highest-frequency policy trigger on the calendar for the bear-steepening scenario.

### The Marginal Buyer: Dealers, and the Missing Foreign Data

Who absorbs the coupons when the freeze eventually breaks? The intermediation capacity of primary dealers and Treasury-market hedge funds is the transmission channel from issuance to premium, and that capacity is balance-sheet-constrained. What the evidence does show is that roughly three-fifths of the 0.827pp year-over-year rise in the fitted 10-year zero-coupon yield through September 2026 was compensation, not expected rates [S7]—the market has already been paying dealers and price-sensitive buyers progressively more to take duration risk.

The foreign official channel is the largest identified evidence gap in this forecast, and it should be treated as such rather than papered over. Japan's Ministry of Finance is the largest foreign official holder of Treasuries; the People's Bank of China and SAFE are the second. But no TIC holdings data for either, and no Bank of Japan policy-rate or JGB series, were captured in the research underlying this report. What can be said with confidence is directional: Japan's MoF invests in Treasury securities as a reserve and intervention matter, BoJ policy normalization shifts relative JGB-Treasury spreads and thus the marginal incentive for Japanese buyers, and Chinese allocation decisions run through the same price channel [S10 references the futures strip; the holdings evidence itself is absent]. stable holdings would support the plateau.

### The Steelman: Why the Bear Case Might Be Overpriced

The strongest argument against the fiscal-dominance path deserves a fair hearing. Treasury has not been forced into coupon increases yet, despite deficits running at $2 trillion; the August freeze was announced with the July record deficit already known. The Fed's reserve-management purchases provide a structural bid at the short end that partially sterilizes the bill-heavy mix. Market-based inflation pricing remains fully contained—10-year breakevens at 2.351% and 5y5y forwards at 2.34% [S4]—so the supply pressure is being expressed entirely in real yields and premium, not in an inflation-unanchoring dynamic that would force the Fed's hand.

The response is that this argument conflates flow manageability with stock sustainability. Every quarter the freeze holds, the bills share drifts toward or beyond the top of the TBAC-flagged band, the maturity wall shortens, and the eventual transition to coupon issuance—when cash-balance management, refunding mechanics, or Fed portfolio composition force it —arrives at a larger scale. The past is a weak anchor in both directions here.

### What This Means for the 2027 Distribution

Weighing this driver against the scenario skeleton: the fiscal channel alone assigns no probability to the disinflation glide or recession paths—deficits are inflationary for supply, not demand for duration. It divides its weight between the plateau and the bear-steepening tail. Each step is independently verifiable, each has a date, and together they convert the marginal-buyer problem from a narrative into a falsifiable forecast. The report's medium confidence on this driver reflects the missing TIC and BoJ evidence: the domestic supply picture is well documented, but the largest holders of the stock remain, for now, unobserved.

## Driver IV: Recession Probabilities and Historical Base Rates for Large Yield Moves

The downside tail of this forecast is not primarily an interest-rate-policy question; it is a question about whether the business cycle turns. Only one scenario puts DGS10 below that floor, and it requires a recession.

### Three Recession Indicators, One Dormant Message

The first family is labor-market-based. The real-time Sahm rule recession indicator stood at 0.00 percentage points for 2026-09, at the very bottom of its five-year range of -0.07 (2026-08) to 0.43 (2025-11) [S13]. A year earlier, in 2025-09, the indicator read 0.23—closer to the trigger—so the direction of travel over the past year has been *away* from recession, not toward it; [S13] the year-over-year change was -0.23 percentage points [S13].

The second family is yield-curve-based, and here the signal reversal is the story. The NY Fed's probit model of recession from the Treasury spread put the twelve-months-ahead probability at a monthly average of just 0.28 percent for 2026. [S38] This is a genuinely unusual configuration relative to the past four years. The five-year range of 3M10Y spans -1.73% (2023-05) to +1.98% (2022-04) [S3], and the curve spent 2023-2024 deeply inverted—conditions under which the same NY Fed probit model was flashing elevated probabilities. An inverted curve predicts recession because it embodies the market's expectation of forced aggressive easing;

The third family is model-aggregate-based. This is materially higher than the NY Fed probit's near-zero reading for two reasons worth spelling out, because they explain why this report does not simply average the two. First, the Cleveland Fed approach incorporates expected GDP growth alongside the term structure, so it can register growth-fragility risk that a pure-spread probit misses. The NY Fed's own documentation shows how sharply the probit responds to spread movements;

One evidentiary caveat belongs on the record: a capture of the NY Fed recession-probability table suggests a 2027 average of 0.15, but this could not be confirmed, and only the 2026 year-average value of 0.28 percent is reliably reported [S38]. Neither gap changes the direction of the evidence; both widen the uncertainty band around it.

### Why This Report Prices Recession Risk Above the Models

The report's response rests on three grounds. First, model probabilities are point-in-time and conditional; the relevant question is not "what is recession probability today" but "what is the probability a recession begins at some point in the next fourteen months," which compounds monthly hazard rates.

### Historical Base Rates: What Moves of This Size Actually Look Like

Turn now from whether the cycle turns to how far the yield can move regardless. Three findings discipline the scenario probabilities.

**Finding one: the unconditional base rate for large moves overstates the risk from this starting point.**

**Finding three: the plateau has the strongest base-rate support of any scenario.**

A summary of the quantitative anchors:

| Indicator | Current value | Signal | Source |
|---|---|---|---|
| Real-time Sahm rule | 0.00 pp (2026-09); [S13] | Dormant, moving away from trigger | [S13] |
| Cleveland Fed 1-yr-ahead recession probability | — | Low-moderate | |
| — | 0.28% | Near-zero | [S37] |
| 3M10Y spread | — | Positive slope, probit benign | |
| 2s10s spread | — | Positive slope | |
| — | 1 of 4 | Plateau favored | |
| — | 0 of 4 | Big moves historically require regime break | |

### Transmission: How a Recession Would Actually Produce Sub-4%

A recession triggers the Sahm rule mechanically as unemployment rises [S13];

Two second-order effects qualify this path.

### What Would Change This Chapter's Mind

The falsifiable waypoints are concrete. The forecast horizon's plateau-or-break structure is not an assumption; it is what the data did the last four times yields started here.

## Scenario Forecast: Higher-for-Longer Plateau (34%) — 4.75% to 5.50%

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/ust10y-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

Each of the four pillars below rests on observable, verifiable conditions; the chapter closes with the explicit resolution criteria and falsification tests that would end this scenario's claim to being the modal outcome.

### Pillar One: A Reaction Function Locked on Inflation, Not Employment

The single most important anchor for the plateau is the FOMC's own projected path. The arithmetic is unforgiving in both directions: a Fed on hold removes the expected-rate fuel for either a sharp rally or a further sell-off.

The reason the Fed stays put is visible in the same projections. The Fed's reaction function is therefore constrained by inflation, not labor: with a dormant labor market there is no mandate pressure to cut, and with disinflation projected but slow, there is no mandate pressure to keep hiking.

Notably, market pricing is not fighting this. But the direction matters: to the extent futures price anything, they price a slightly firmer path than the SEP, not a cutting cycle.

Household expectations reinforce the stickiness. The University of Michigan one-year inflation expectation printed 4.6% in September 2026, down only 0.1pp year-over-year and far above the near-target market pricing [S12]. A Fed cutting into 4.6% household inflation expectations would risk the credibility of its just-completed tightening; [S12]

### Pillar Two: A Term Premium That Rests Near One Percent

The current configuration supports that. The Kim-Wright term premium (THREEFYTP10) printed a 0.96% monthly mean for September 2026, the top of its five-year range, with daily prints as high as 0.986% on October 16. It supplied roughly half of the 0.827-percentage-point year-over-year rise in the fitted 10-year zero-coupon yield [S7].

Why would a premium at a cycle high stop climbing rather than accelerate? The August 2026 quarterly refunding statement anticipated maintaining nominal coupon and FRN auction sizes "for at least the next several quarters," pushing marginal borrowing into bills [S27], and Treasury's stated rationale was that current auction sizes leave it "well positioned" to address changes in the fiscal outlook and to the SOMA portfolio's composition. In other words, Treasury is deliberately not testing dealer capacity with new coupon supply, which caps the marginal-buyer pressure that drives premium escalation. Meanwhile the Fed's reserve-management purchases of shorter-term Treasuries, running since December 2025 with total assets at $6,753,604 million on 2026-10-21 [S17], add a steady demand bid at the front and belly of the curve.

This divergence cuts both ways for the plateau. If ACM is right, the premium has less room to fall and the expected-rate component embedded in yields is higher — again consistent with a yield stuck near current levels. The plateau does not require resolving the model dispute;

### Pillar Three: Dormant Recession Signals Keep the Downside Tail a Tail

The plateau is also the scenario in which the recession tail never activates, and current indicators support that reading strongly. The real-time Sahm rule indicator reads 0.00 percentage points for September 2026, having declined for ten consecutive months from a 0.43pp peak in November 2025 [S13]. The New York Fed probit, keyed off the 10Y-3M spread, faces a steeply positive 0.896% monthly spread [S3] — historically an anti-recession configuration.

Absent a recession, large moves from this starting level are historically rare; the plateau is the default.

### Pillar Four: Fiscal Pressure That Is Real but Managed

Deficit pressure of this scale is the fuel for the bear-steepening tail.

The plateau's answer is that deficits translate into term premium only through the issuance channel, and that channel is currently managed. The plateau scenario is a claim that Treasury keeps deferring the coupon-size decision through the November 2026 and 2027 refundings, accepting bill-share drift rather than risk a failed long-end auction. [S33]

### Resolution Criteria and Falsification

**Resolution.**

**Falsification.** The scenario dies under any of three conditions:

1. **A sustained breach of either band boundary.**
2. A coupon increase alone, with premium contained, would not necessarily falsify the plateau.

That is demanding — hence a modal-but-minority probability, flanked by the roughly symmetric tails quantified in the companion chapters.

## Scenario Forecast: Disinflation Glide (24%) and Recession Break (15%) — The Downside Tails

### The Disinflation Glide: Convergence Without Crisis (24%)

Third, the term premium must compress: the Kim-Wright premium averaged 0.96% in September 2026, the top of its five-year range, up from 0.462% a year earlier;

The arithmetic of the scenario is straightforward.

Why only 24%? The obstacles are visible in the current data.

### The Recession Break: The Only Historically Precedented Route Below 4% (15%)

The mechanism runs through the labor market. Today those triggers are dormant. SAHMREALTIME printed 0.00 percentage points for September 2026 and has declined for ten consecutive months from its 0.43 pp peak in November 2025 [S13]. A curve this steep is the opposite of the inversion that historically precedes recessions.

Three considerations push the weight modestly above the point estimates.

One asymmetric feature of the recession branch deserves emphasis: a cycle-high term premium can mute the rally. indeed, a recession that widens the deficit could keep the premium elevated even as expected rates collapse, cushioning the decline in the headline yield.

### Signposts That Discriminate the Two Downside Paths

The two scenarios are distinguishable in real time by a small set of verifiable indicators, each published on a fixed calendar. For the recession branch: monthly SAHMREALTIME updates (a sustained rise above the November 2025 peak of 0.43 pp is the early warning; [S13] The two paths also diverge on the curve: the glide flattens the short end gently as cuts are priced;

A final calibration note on falsification. Both would then hand their probability mass back to the modal plateau, consistent with the report's overall structure: the downside tails are live, observable, and honestly weighted—but they are tails.

## Scenario Forecast: Bond Bear Steepening (24%) and Residual (3%) — The Upside Tail

Roughly three-fifths of the year's 0.827pp rise in the fitted 10-year zero-coupon yield was compensation, not expected rates [S7]. If that trend has another year of momentum in it, the scenario resolves itself.

### The Arithmetic of the Break: How 5.13% Becomes 5.50%+

The scenario works through a single decomposition.

Two observable thresholds govern resolution.

### The Causal Chain: From Deficit to Coupon Increase to Premium

The transmission runs through four links, each observable in real time.

**Link one: the deficit tracks or exceeds the CBO baseline.** If FY2027 runs at or above the roughly $2 trillion mark implied by the CBO baseline, the borrowing machine cannot be fed from bills indefinitely.

**Link two: the coupon freeze breaks.** Treasury's August 2026 quarterly refunding statement, issued by Deputy Assistant Secretary Brian Smith, committed to holding nominal coupon and FRN auction sizes unchanged "for at least the next several quarters," absorbing marginal needs in bills [S27][S33]. That language is deliberately temporary. The next statement, expected in early November 2026 (date unconfirmed), is the first test; [S33]

**Link three: dealer capacity converts supply into premium.** Once coupon sizes rise, the marginal buyer is a balance-sheet-constrained primary dealer or leveraged fund. Supplying duration on top of that base is the accelerant.

**Link four: foreign official demand softens.** Japan's Ministry of Finance and China's PBoC/SAFE are the two largest foreign official holders, and shifts in their allocation transmit through the term premium — weak official demand leaves its price signature in the compensation component of the yield. Critically, the evidence base for this link is thin: no TIC holdings figures for Japan or China and no Bank of Japan policy series were captured in this research run. That gap cuts both ways for calibration.

### Why 24%: Steelmanning the Skeptic, Then Answering

The strongest case against this scenario is the historical base rate.

it does not say they are impossible under unprecedented supply conditions, and the premium's nine-month trend is the live evidence that the regime has changed.

Note also that in this scenario the curve should *steepen*, not flatten.

### The Residual Bin: 3% for What the Named Scenarios Miss

Three percent is small because the scenario bands are wide and mutually exhaustive by construction on the DGS10 quantity itself; the bin exists for mechanism mismatch and boundary noise, not for a fifth macroeconomic story.

### Falsification and Monitoring

The monitoring calendar is fixed: the early-November 2026 refunding statement first [S33], then quarterly refundings through November 2027; monthly THREEFYTP10 and MSPD bill-share prints [S34]; monthly TIC releases on Japan and China; The first coupon-size increase, whenever it comes, is the moment this tail stops being a trend extrapolation and becomes the base case.

## Most-Likely Trajectory: Quarter-by-Quarter Path to End-2027

This chapter constructs that trajectory quarter by quarter, mapping each waypoint to the observable releases that will confirm or falsify it. The path is deliberately boring—and that is the point. A boring path is the base case unless a named trigger fires.

### Why the corridor, not a trend: the two-component arithmetic

The fitted 10-year zero-coupon yield of 5.003% (September 2026 monthly mean; [S7] The corridor forecast follows from the behavior of each component.

The expected-rate component is the more pinned of the two.

### Q4 2026: the refunding and the December SEP set the corridor's edges

The first is the quarterly refunding statement expected in early November 2026 (exact date unconfirmed in the evidence) [S33].

That wedge, described in the underlying research as a derived reading without day-count adjustment on thin back-contract liquidity, could close from either side. if futures converge down to the dots, the corridor holds with a downward bias.

### H1 2027: the hold, the glide, and the premium stall

Three observable series discriminate between scenarios during this window. Second, SAHMREALTIME: at 0.00pp for September 2026 and with a five-year range of only -0.07 to 0.43pp [S13], the indicator starts the year dormant; Third, the Monthly Treasury Statements: FY2027 deficits tracking at or above a $2.0 trillion annualized pace against CBO's $1.9 trillion FY2026 baseline would keep the marginal-buyer question alive at every refunding even under the freeze.

The balance sheet adds a quiet upward tilt to the corridor's center of gravity. With QT finished since October 2025 and reserve-management purchases of shorter-term Treasuries running since December 2025, total assets stood at $6,753,604 million on 2026-10-21 [S17]. Those purchases concentrate at the short end, which supports the front of the curve but does nothing to absorb coupon duration—meaning the Fed's balance sheet, in its current configuration, is mildly premium-supportive at the long end rather than suppressive. The modal path assumes this continues all year.

### H2 2027: the single-cut option and the year-end settling

The second half holds the path's one genuine branch point. Crucially, one cut does not break the corridor: the expected-rate component falls only a few basis points at the 10-year point, and the cut itself would likely come with a firmer growth/inflation mix that partially offsets via the premium. [S30]

The alternative branch—inflation stickiness keeping core PCE nearer 3%—produces a full-year hold. [S4]

### The signpost ledger: what each waypoint confirms or falsifies

Each waypoint in the trajectory carries a named observable and a scenario implication:

7. **Monthly TIC releases and Monthly Treasury Statements**: deficit tracking at or above $2.0 trillion annualized for FY2027 → keeps bear-steepening probability from decaying; Japan/China holding data (a stated evidence gap in the underlying research) is the wildcard on the demand side.
8. each reiterated freeze compounds the plateau's base-rate support.

The corridor is falsifiable at eight scheduled dates a year, which is precisely what makes it a forecast rather than a hope.

## Binary Forecast Ledger: Twelve Verifiable Calls with Thresholds and Dates

The twelve calls in this ledger translate the report's scenario architecture into individually falsifiable statements. Each carries a probability, a concrete numeric threshold, and a resolution source that any reader can check. Every subsidiary call is calibrated so that its probability is consistent with those scenario weights and with the historical base rates established in earlier chapters.

### The Yield-Level Calls

Why not higher?

The dormancy signals are strong: the real-time Sahm indicator reads 0.00 pp (2026-09), having declined for ten consecutive months from a 0.43 pp November 2025 peak [S13]; and the curve is positively sloped at both the 2s10s and 10Y-3M tenors.

### The Policy-Rate and Balance-Sheet Calls

Only a fast, clean disinflation with a compressed premium throughout avoids any month above 1.0%. [S6]

The August 2026 statement committed to holding sizes for "at least the next several quarters", and the next statement is expected early November 2026. [S33]

the indicator currently reads 0.00 pp with a five-year range of −0.07 to 0.43 pp [S13], meaning it would need to exceed its entire five-year historical range to resolve yes.

### The Fiscal, Inflation, and Curve-Shape Calls

Resolution: the sum of Monthly Treasury Statement deficits for October 2026 through September 2027 reaches $2.0 trillion or more, cross-checked against CBO's baseline. [S38] The recent MTS prints corroborate the run-rate: a record $432.3 billion monthly deficit in July 2026 [S18]. it does not assume any new legislation.

The breakeven stands at 2.351% (2026-09), down 0.02 pp year-over-year, with a five-year range of 2.11% (2024-08) to 2.88% (2022-04) [S4]. This is an unanchoring test: the report's entire decomposition shows the 2026 yield rise was real compensation, not inflationary — the TIPS real yield climbed from 1.825% (2026-02) to 2.638% (2026-09) while the breakeven edged down [S16]. Notably, the Michigan household survey at 4.6% [S12] sits far above the breakeven — a gap that would need to close from the market side for this call to hit.

The series stands at 4.6% (2026-09), barely changed from 4.7% a year earlier, with a five-year range of 2.6% (2024-11) to 6.6% (2025-05). This is the mirror image of Call 9: it tests whether household expectations normalize, a precondition for the Fed to cut with confidence in the disinflation-glide path.

0.338% for 2026-09), down 0.214 pp year-over-year [S2], with a five-year range of −0.93% (2023-07) to 1.19% (2021-10).

Total assets stand at $6,753,604 million (2026-10-21), with a five-year range of $6,535,781 million (2025-12-03) to $8,965,487 million (2022-04-13) [S17]. In the plateau scenario, trend-purchase sizing likely leaves the balance sheet just under $7.0 trillion; a recession with large cuts and renewed large-scale purchases, or a decision to expand purchases across maturities, would push it over.

### Coherence Checks and Known Tensions

Three cross-checks matter for reading this ledger honestly.

Second, the policy-rate call embeds the report's most genuine uncertainty: the SEP-versus-futures wedge. if the dots govern, it is too low.

Third, the term-premium model disagreement directly affects Call 5. The Kim-Wright series puts the premium at 0.96% [S6];

## Actor Map: Incentives, Constraints, and Decision Points That Move the Yield

The 10-year yield at end-2027 will not be set by an abstract "market." other/status quo, 3%). The central finding: the actors who anchor the expected-rate component (the FOMC, the Chair) are constrained and reactive, while the actors who move the swing factor — the term premium at its five-year high of 0.96% [S6] — hold the initiative. That asymmetry is why this report puts nearly half its probability weight on premium-driven outcomes (plateau and bear steepening combined).

### The FOMC: A Reaction Function Pinned Between 3.4% Core PCE and 4.1% Unemployment

In other words, the FOMC is not reacting to a labor market problem — unemployment is at its own projected steady state — it is reacting to an inflation level 1.4 points above target.

The transmission from a funds-rate decision to the long end runs through the term premium, which the Committee cannot control. A hawkish hold keeps expected rates near 4pp;

The Chair's incentive layer matters here. The Chair's incentive structure, in short, is a force for the plateau scenario.

### Treasury: The Coupon Freeze as the Single Highest-Leverage Decision

No actor has a more direct lever on the 10-year yield than the Treasury's debt managers, and no scheduled event in 2027 matters more than the quarterly refunding statements. The August 5, 2026 statement committed to maintaining nominal coupon and FRN auction sizes "for at least the next several quarters," absorbing marginal borrowing needs in bills [S27]. The next statement is expected in early November 2026 (date unconfirmed), with four more refunding decisions falling within the forecast window through November 2027. [S33]

The August 2026 refunding statement also noted that current auction sizes leave Treasury "well positioned" to address changes to the fiscal outlook and to the size and composition of the SOMA portfolio — a deliberate coordination with the Fed's reserve-management purchases. [S27]

The freeze's falsifier is equally concrete. At some point — and TBAC's own analysis flags the long-term risk — Treasury is forced to lift coupon sizes into whatever demand exists. Treasury's decision calendar and constraint (dealer absorption capacity, discussed below) make it the pivotal actor between the plateau and the upside tail — and the reason this report assigns the upside tail nearly the same weight as the disinflation glide.

### The NY Fed Desk and the Balance-Sheet Channel

The New York Fed Markets Desk executes a narrower but consequential mandate. The Desk's incentive — reserve adequacy and orderly money markets — is scenario-neutral for the 10-year in level terms, but not in mix terms: purchases concentrated at the short end mean the Desk is a marginal buyer of precisely the paper Treasury is issuing most of, reinforcing the coupon freeze's viability. [S30] The Desk also publishes the Survey of Primary Dealers, whose term-premium and policy-path expectations feed directly into the market narrative around each FOMC meeting — an informational, not just operational, role.

That last item is the one with yield relevance. A shift toward longer-maturity purchases would absorb duration supply and compress the premium — a quiet pro-plateau or even pro-glide force; conversely, a decision to hold purchases strictly at the short end while coupon supply grows would leave the duration market to private intermediaries alone.

### Primary Dealers: The Transmission Channel From Issuance to Premium

Between Treasury's supply decision and the yield stands a balance-sheet-constrained intermediary sector. Dealers' intermediation capacity determines how much issuance pressure translates into term premium — the mechanism through which the entire fiscal-supply story operates. What is established is the structural role: Treasury is a customer of the dealer community, and the dealers' willingness and capacity to warehouse newly issued duration sets the marginal price. The bill-heavy strategy works precisely because bills carry little duration risk and modest balance-sheet cost; a forced pivot to larger coupon auctions would test dealer capacity directly, and auction tails or weak bid-to-cover ratios would be the observable symptom.

### Congress and the CBO: The Fiscal Backdrop as a Slow Variable

Congress legislates the deficit; the CBO scores it. Congress's incentive — delivering spending and tax priorities — is largely indifferent to the bond market until funding costs bite; the constraint it faces is precisely a "bond-market backlash" that raises those costs.

### Japan, China, and the Unmeasured Marginal Buyer

The largest evidence gap is also one of the largest channels. Japan's Ministry of Finance is the largest foreign official holder of Treasuries, and the People's Bank of China / SAFE the second-largest — both are direct investors in Treasury paper, and both are named actors in the foreign-demand channel. Yet this evidence base contains no TIC holdings figures for either, and no BoJ policy-rate or JGB series was captured. If the premium's 0.499pp year-over-year rise partly reflects Japanese and Chinese marginal retreat, the bear-steepening risk is higher than the current benign recession signals suggest; if it reflects domestic fiscal expectations alone, the plateau holds more firmly.

### Steelman: Why the Actor Map Might Favor the Downside

A fair counterargument runs: the actor map above overweights inertia. Treasury, for its part, has every cost-minimization incentive to keep the coupon freeze, and the Fed's reserve-management purchases provide a standing buyer at the short end.

The response is that this argument assumes each actor's incentive is achievable independently. The Fed cannot cut into still-elevated core inflation if the Michigan household measure stays at 4.6% [S12] — the expectations-unanchoring risk constrains the glide. Treasury cannot maintain the freeze if deficits run at the CBO's $2.4 trillion pace and dealers balk at bill absorption. And the plateau does not require every actor to succeed — only none to fail catastrophically.

## Forecast Summary Table, Calibration, and Divergences

The preceding chapters assembled the scenario architecture, the trajectory, and the twelve-call binary ledger from the evidence. This closing chapter consolidates everything into a single reference view, then does something the earlier chapters deliberately deferred: it exposes the calibration machinery. Where did each probability come from? Which numbers rest on official published paths, which on historical base rates, and which on this report's own judgment calls? And where does this forecast diverge from the other forecasts that already exist in the public record—CBO's embedded rate assumption, the SEP dots, the futures strip, and the term-premium models that disagree with each other by a quarter of a percentage point on the same instrument? A forecast that cannot answer those questions is a narrative; this one can, and the answers are the chapter.

### The Consolidated Forecast Table

the bands are mutually exclusive and jointly exhaustive with the residual bin.

| Scenario | Probability | Resolution band (DGS10, 2027-12) | Supporting checks | Falsifying condition |
|---|---|---|---|---|
| Higher-for-longer plateau | — | — | THREEFYTP10 in [0.7, 1.3]% | Sustained breach of either band edge; |
| Disinflation glide | — | — | — | premium refusing to compress despite easing |
| Bond bear steepening | — | — | refunding showing coupon increases | — |
| Recession flight to quality | — | — | cumulative cuts ≥150bp | Sahm never triggering; |
| Residual / mixed | — | Boundary noise, data disruption, or mechanism mismatch | — | — |

### How Each Probability Was Calibrated

The bear steepening rests on trend extrapolation of the premium with no current distress signal. When the same observable is consistent with opposite futures, symmetry is the honest prior.

### The SEP-versus-Futures Wedge: The Report's Most Genuine Uncertainty

The single largest calibration tension runs through the policy path. This wedge deserves the explicit treatment it gets here for three reasons.

Second, the wedge is decision-relevant in both directions. Third, the divergence feeds the residual bin: if the realized funds path settles between the two readings, the two-component decomposition that gives each scenario its mechanism becomes contestable at the margins.

### Term-Premium Model Disagreement as a Probability Band, Not a Puzzle

under ACM, closer to 4.3%. The report's response is not to pick a winner but to treat the dispersion as an uncertainty band with two concrete consequences. The fact that FRED does not carry ACMTP10 directly, forcing reliance on mirror sites, compounds the measurement problem: the swing variable of the entire forecast is known only within a band, not to two decimals.

### Missing Evidence: TIC Holdings and the BoJ

Two evidence gaps function as uncertainty multipliers rather than neutral omissions. No TIC holdings data for Japan or China, and no Bank of Japan policy-rate or JGB series, were captured in the research underlying this report. Japan's Ministry of Finance is the largest foreign official holder of Treasuries and the PBoC/SAFE the second; The honest inference is directional only: the premium's steady climb is *consistent with* a market quietly repricing a marginal-buyer problem, but the holders themselves remain unobserved. Small-sample base rates compound the humility: the near-5% historical record is four windows, one of which caught a financial crisis [S1].

### Divergences from Other Published Forecasts

Three divergences from the public record deserve naming.

**Versus CBO's embedded rate assumption.** The scorer most aware of the fiscal arithmetic forecasts stability; the market's compensation pricing disagrees, and the report splits the difference with visible weights.

Taken literally, the SEP's own baseline delivers no easing within the forecast horizon—closer to this report's plateau than to its glide. the SEP embeds zero. The divergence is deliberate and dated.

**Versus market-implied paths.**

### What the Ledger Gets Right, Wrong, or Cannot Yet Know

The calibration honesty test: every probability in this report is anchored to one of four identifiable inputs—official published paths (SEP, refunding statements, CBO baseline) [S27]; historical base rates computed from stored data; model outputs treated as estimates with stated divergences; and this report's own judgment, always labeled as such. Each is defensible, none is certain, and all are falsifiable on the dated calendar of refundings, FOMC meetings, monthly premium prints, Sahm updates, and TIC releases that the preceding chapters fixed. The forecast does not claim to escape that distribution; it claims to know which parts of it are most likely, why, and by what evidence the claim will be settled.

## Risks, Watchlists, and Decision Implications

The upside tail is a supply-and-demand story that builds slowly through the term premium; the downside tail is a labor-market story that arrives suddenly. This chapter inventories the mechanisms that could break the base case, then converts them into a dated monitoring calendar and concrete positioning rules keyed to the scenario bands.

### The Disorderly Premium Break: How the Bear-Steepening Tail Unfolds

The single most important structural risk is that Treasury's issuance strategy reaches its limit. The mechanism of failure is mechanical: bills must be rolled continuously, money-market funds absorb them only up to their asset-allocation ceilings, and once that ceiling binds, the marginal buyer disappears not gradually but abruptly. At that point Treasury faces a choice between bill-market dysfunction and lifting coupon sizes into a dealer community whose balance-sheet capacity is already stretched—the transmission channel through which issuance becomes term premium.

The current configuration makes this risk live rather than hypothetical.

A steelman against this tail deserves weight: the premium has already risen nearly a full percentage point from its 2021 lows without a funding crisis, the Fed has been absorbing shorter-duration paper through reserve-management purchases since December 2025 with total assets at $6,753,604 million on October 21, 2026 [S17], and Treasury has demonstrated it will pay the bill-market cost to shield the coupon curve. every tool currently deployed supports the front of the curve while the risk accumulates at the long end.

### Fiscal Dominance and the Foreign-Holder Exit

One rung above a disorderly premium break sits fiscal dominance: a state in which deficit financing begins to constrain the central bank rather than the reverse. The observable early warning is the 10-year breakeven (2.351% in September, near the bottom of its five-year range [S4]) beginning to rise alongside the premium rather than staying flat—compensation for inflation risk and compensation for supply risk rising together is the signature of the dominance regime.

The foreign dimension is the evidence gap this report flags as most consequential. No TIC holdings data for Japan or China and no BoJ policy series were captured in the research underlying this forecast. Bank of Japan rate normalization raises JGB yields and reduces the carry incentive for Japanese institutions to hold duration in dollars. Because this channel cannot currently be measured, the report treats it as an uncertainty multiplier on the bear-steepening scenario rather than a separately quantified probability—a limitation that argues for monitoring the monthly TIC releases (published mid-month by Treasury) rather than assuming benign extrapolation.

### Expectation Unanchoring and the Policy-Reversal Recession

The household-versus-market inflation gap is the report's preferred unanchoring risk. Two readings are possible. The benign reading is that household surveys are noisy, backward-looking, and dominated by gasoline prices; five-year-range history supports some of this, as Michigan swung between 2.6% and 6.6% within the stored window [S12] without market pricing following.

### The Dated Watchlist

Every risk above maps to a scheduled publication. The monitoring calendar through the forecast deadline:

- **Quarterly refunding documents** (early February, May, August, November 2027, plus the November 2026 statement expected imminently): auction-size decisions and TBAC commentary [S33]. Trigger: any nominal coupon increase while THREEFYTP10 is above 1.0% [S6] confirms bear-steepening pressure.
- Two consecutive downward revisions to the growth/inflation combination shift weight toward the disinflation glide.
- **Monthly CPI/PCE and University of Michigan prints** [S12]: the expectation-gap tracker above.
- **Monthly TIC releases** (mid-month): Japan and China official holdings—the missing-variable monitor.
- **Monthly Treasury Statements**: FY2027 deficit tracking against the CBO $2.4 trillion average baseline;
- **Weekly FRED series**: DGS10 daily, THREEFYTP10, breakevens—continuous band monitoring.

### Decision Implications: Positioning by Band

the historical asymmetry favors patience over pre-positioning.

Each threshold is verifiable against FRED, Treasury, and FOMC publications, so the decision rules resolve on the same evidence as the forecast itself—which is the discipline that separates a probabilistic forecast from a narrative.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/ust10y-2027/charts/timeline_lanes.png)

*Event Timeline*

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/ust10y-2027/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[34%] Higher-for-longer plateau (4.75-5.50%)**: FRED DGS10 monthly value for 2027-12 falls in [4.75, 5.50] percent; supporting check: funds rate still in 3.5-4.5% range at Dec 2027 and THREEFYTP10 in [0.7, 1.4].
- **[24%] Disinflation glide lower (4.00-4.75%)**: FRED DGS10 monthly value for 2027-12 falls in [4.00, 4.75) percent; supporting checks: THREEFYTP10 below 0.7% and bis:WS_CBPOL/M.US end-2027 at or below 3.5%.
- **[24%] Bond bear steepening (>5.50%)**: FRED DGS10 monthly value for 2027-12 is above 5.50 percent; supporting checks: THREEFYTP10 above 1.0% and Treasury quarterly refunding statements showing nominal coupon auction size increases during 2027.
- **[15%] Recession flight to quality (<4.00%)**: FRED DGS10 monthly value for 2027-12 is below 4.00 percent; supporting checks: SAHMREALTIME at or above 0.50 during 2027 and cumulative Fed cuts of at least 150 bp between Oct 2026 and Dec 2027 (bis:WS_CBPOL/M.US).
- **[3%] Other / Status Quo**: At 2027-12-31, classify this residual bin if none of the named scenarios' complete resolution criteria are met, or if the outcome remains a mixed/status-quo path.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis (fred:DGS10) | next monthly release after 2026-09 | — |
| 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States (fred:T10Y2Y) | next monthly release after 2026-09 | — |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States (fred:T10Y3M) | next monthly release after 2026-09 | — |
| 10-Year Breakeven Inflation Rate — United States (fred:T10YIE) | next monthly release after 2026-09 | — |
| 5-Year, 5-Year Forward Inflation Expectation Rate — United States (fred:T5YIFR) | next monthly release after 2026-09 | — |
| Term Premium on a 10 Year Zero Coupon Bond — United States (fred:THREEFYTP10) | next monthly release after 2026-09 | — |
| Fitted Yield on a 10 Year Zero Coupon Bond — United States (fred:THREEFY10) | next monthly release after 2026-09 | — |
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | next monthly release after 2026-09 | — |
| University of Michigan: Inflation Expectation (fred:MICH) | next monthly release after 2026-09 | — |
| Real-time Sahm Rule Recession Indicator — United States (fred:SAHMREALTIME) | next monthly release after 2026-09 | — |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed (fred:DFII10) | next monthly release after 2026-09 | — |
| Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States (fred:WALCL) | next weekly release after 2026-10-21 | — |
| Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) — United States (usgov:treasury/mts_deficit) | next monthly release after 2026-09 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis (fred:DGS10) | 4.989% (2026-09) | > 5.5% / 2027-12 | 29% (n=224, h=15) vs model 24% | [Source](<https://fred.stlouisfed.org/series/DGS10>) [S1] |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis (fred:DGS10) | 4.989% (2026-09) | < 4.75% / 2027-12 | 41% (n=224, h=15) vs model 39% | [Source](<https://fred.stlouisfed.org/series/DGS10>) [S1] |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis (fred:DGS10) | 4.989% (2026-09) | < 4% / 2027-12 | 16% (n=224, h=15) vs model 15% | [Source](<https://fred.stlouisfed.org/series/DGS10>) [S1] |
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | 3.875% (2026-09) | <= 3.5% / 2027-12 | 40% (n=104, h=15) vs model 30% | [Source](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8] |
| 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States (fred:T10Y2Y) | 0.338% (2026-09) | >= 0% / 2027-12 | 65% (n=105, h=15) vs model 75% | [Source](<https://fred.stlouisfed.org/series/T10Y2Y>) [S2] |
| 5-Year, 5-Year Forward Inflation Expectation Rate — United States (fred:T5YIFR) | 2.34% (2026-09) | < 2.1% / 2027-12 | 14% (n=105, h=15) vs model 30% | [Source](<https://fred.stlouisfed.org/series/T5YIFR>) [S5] |
| 10-Year Breakeven Inflation Rate — United States (fred:T10YIE) | 2.351% (2026-09) | <= 2.5% / 2027-12 | 71% (n=105, h=15) vs model 85% | [Source](<https://fred.stlouisfed.org/series/T10YIE>) [S4] |

<!-- drf-news-market-context:3b2685916583d12333850aaa561f3df02e787e952025656e28075993f3e65901:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:3b2685916583d12333850aaa561f3df02e787e952025656e28075993f3e65901:end -->

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
| Scenarios (multiclass) | 6 | 0 | 6 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 15 | 0 | 15 | — |
| Unanchored binaries | 74 | 0 | 74 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S1] Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DGS10](https://fred.stlouisfed.org/series/DGS10)
2. [S2] 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T10Y2Y](https://fred.stlouisfed.org/series/T10Y2Y)
3. [S3] 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T10Y3M](https://fred.stlouisfed.org/series/T10Y3M)
4. [S8] Central bank policy rates - United States - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US)
5. [S17] Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/WALCL](https://fred.stlouisfed.org/series/WALCL)
6. [S4] 10-Year Breakeven Inflation Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T10YIE](https://fred.stlouisfed.org/series/T10YIE)
7. [S5] 5-Year, 5-Year Forward Inflation Expectation Rate — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/T5YIFR](https://fred.stlouisfed.org/series/T5YIFR)
8. [S12] University of Michigan: Inflation Expectation — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/MICH](https://fred.stlouisfed.org/series/MICH)
9. [S18] Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) — United States — fiscaldata.treasury.gov — [https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/](https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/)
10. [S6] Term Premium on a 10 Year Zero Coupon Bond — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/THREEFYTP10](https://fred.stlouisfed.org/series/THREEFYTP10)
11. [S7] Fitted Yield on a 10 Year Zero Coupon Bond — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/THREEFY10](https://fred.stlouisfed.org/series/THREEFY10)
12. [S13] Real-time Sahm Rule Recession Indicator — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/SAHMREALTIME](https://fred.stlouisfed.org/series/SAHMREALTIME)
13. [S16] Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DFII10](https://fred.stlouisfed.org/series/DFII10)
14. [S27] Quarterly Refunding Statement of Deputy Assistant Secretary for Federal Finance Brian Smith | U.S. Department of the Treasury — home.treasury.gov — [https://home.treasury.gov/news/press-releases/sb0590](https://home.treasury.gov/news/press-releases/sb0590)
15. [S22] FOMC Statement: September 2026 | J.P. Morgan Asset Management — am.jpmorgan.com — [https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/fixed-income/fixed-income-perspectives/fomc-statement-september-2026/](https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/fixed-income/fixed-income-perspectives/fomc-statement-september-2026/)
16. [S9] Federal Reserve Board - Federal Reserve issues FOMC statement — federalreserve.gov — [https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm)
17. [S33] Most Recent Quarterly Refunding Documents | U.S. Department of the Treasury — home.treasury.gov — [https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents](https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents)
18. [S30] US - ACM 10Y Treasury Term Premium Estimates | MacroMicro — en.macromicro.me — [https://en.macromicro.me/charts/45452/us-10-treasury-term-premium](https://en.macromicro.me/charts/45452/us-10-treasury-term-premium)
19. [S28] The Fed - September 16, 2026: FOMC Projections materials, accessible version — federalreserve.gov — [https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm](https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm)
20. [S38] Prob Rec.pdf — newyorkfed.org — [https://www.newyorkfed.org/medialibrary/media/research/capital_markets/Prob_Rec.pdf](https://www.newyorkfed.org/medialibrary/media/research/capital_markets/Prob_Rec.pdf)
21. [S37] Probability of US Recession Predicted by Treasury Spread — newyorkfed.org — [https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf](https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf)
22. [S34] Monthly Statement of the Public Debt (MSPD) - U.S. Treasury Fiscal Data — fiscaldata.treasury.gov — [https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/](https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/)
