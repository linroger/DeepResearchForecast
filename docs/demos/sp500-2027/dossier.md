# Forecast the S&P 500 index level (close) as of December 31, 2027, and separately the probability that the index experiences a drawdown of 20% or more from any…

## Executive Summary

All index levels settle on S&P Dow Jones Indices official closing values on a price basis; because no official S&P DJI print for the as-of week is in evidence, the anchor is the 7,662.54 vendor close of 2026-10-22 [S1], alongside the official monthly observation of 7669.4143 Index (2026-09) [S2]. For the drawdown question, "by 31 December 2027" means any official close through the last trading day of 2027; for the level, it is that day's close.

Central thesis: this run's most-likely trajectory is an earnings-carried advance to end-2027 near 8,700, ≈14% above the WSJ close [S3][S1], but the advance carries a fat left tail. The frame implies roughly a 30% probability of a 20%-or-greater fall from any 2026–2027 peak, since only the two loss scenarios breach that threshold while the correction scenario caps out at 10–19%. The vulnerability is valuation, not earnings: the trailing as-reported P/E was 26.15 on 2026-10-22 and has exceeded 22 continuously since January 2024 [S4][S5], while FactSet's CY2026 consensus EPS growth was 32.8% on 16 October 2026 [S6][S7] on a blended Q3 2026 net margin of 14.9%, the second-highest in more than 15 years [S8]. The tension is breadth and concentration: excluding Micron and NVIDIA alone, Q3 2026 blended earnings growth falls from 29.0% to 20.0% [S8], and the top-10 weight hit a record 40.7% in 2025 against roughly 32% of index earnings [S9]. The index enters the horizon up 16.485% year over year (2026-09) [S10].

The canonical scenarios, mutually exclusive with fixed probabilities:

- AI-driven reacceleration — 35% — roughly 10–15% annual earnings growth and stable multiples, no 20% drawdown.
- Melt-up then correction — 30% — earnings deliver, multiples overshoot, then a mid-horizon 10–19% correction resets them; 2027 still ends modestly higher.
- Bear market and drawdown — 20% — an AI-capex disappointment or mild recession triggers a 20%+ drawdown and a negative two-year return.
- Hard landing recession — 10% — a policy or credit shock drives a 25–35% drawdown and a 2027 close well below 2026.
- Stagnant sideways grind — 5% — flat revisions and multiple compression leave 2027 within a few percent of today.

The scenarios sum to a 65% chance the index ends 2027 higher than the anchor close.

The modal path is up because policy is tight but recession signals are quiet: the federal funds target-range upper limit is 4% (September 2026, and the daily value on 2026-10-23) [S11] after a unanimous 25 bp September hike per J.P. Morgan's summary [S12], yet the smoothed US recession probability is 0.62% (2026-08) [S13] and the NY Fed's Treasury-spread model averages 0.15 for 2027 — the publisher's model estimate, not an observation [S14]. The empirical base rate from trailing-P/E-above-22 calendar starts since 2003 shows two-year price returns with a median near +20% and no episode worse than about −1% [S4][S15], though only 4–7 windows — too few to price the tail [S4][S15].

Leading indicators to watch: the FOMC meetings of October 27–28 and December 8–9, the latter with a Summary of Economic Projections [S16]; FactSet Earnings Insight revisions to CY2026's 32.8% [S6] and to CY2027; hyperscaler capex guidance from NVIDIA, Microsoft, Alphabet, Amazon and Meta; the real-time Sahm rule, currently 0 Percentage Points (2026-09) [S17]; and the 10-year minus 3-month Treasury curve at 0.896% (2026-09) [S18]. Sustained negative CY2027 revisions would kill AI-driven reacceleration; a rising Sahm rule would confirm Bear market and drawdown.

## Baseline: index level, valuation and returns

### Settlement definition

| Contract | Definition |
|---|---|
| Index level | Official S&P 500 closing level on 31 December 2027 (last trading day), as fixed by S&P Dow Jones Indices |
| Drawdown leg | Any daily official close at least 20% below any prior closing peak set between 1 January 2026 and 31 December 2027 |
| Anchor | S&P 500 — United States: 7669.4143 Index (2026-09; stored monthly observation, a 4 p.m. ET closing-value series) [S2]; verified vendor close 7,662.54 on 2026-10-22 [S1] |

No official S&P DJI closing print for the as-of week is in evidence, so the baseline below rests on vendor closes plus the official monthly series; horizon settlement should use the publisher's official close.

### Level and valuation

The index closed at 7,662.54 on 22 October 2026, the basis of the StreetStats valuation snapshot [S1]. For the as-of date, WSJ reports a close of 7,623.68 on 23 October 2026 [S3], while Investing.com shows 7,639.06 [S19]; the gap likely reflects snapshot timing or settlement differences and is unresolved. A daily reading of 7757.17 on 2026-10-21 in the official series is unconfirmed and inconsistent with those vendor closes [S2]. On that official series, the September 2026 observation is 7669.4143 Index versus 6584.0181 a year earlier, a 16.485% year-over-year rise [S2][S10].

Against that level, the trailing P/E is 22.28 on trailing 12-month actual earnings of $343.87 per share, and the forward P/E is 18.87 on estimated forward 12-month earnings of $406.12 per share [S1]. FactSet's forward 12-month P/E is 19.0 as of 16 October 2026, below its 5-year (19.8) and 10-year (19.1) averages [S7]. Higher multiples appear under other definitions — GuruFocus shows 25.943 on GAAP as-reported earnings as of 22 October 2026 [S20], and WorldPE 23.80 [S21] — a definitional gap (depressed GAAP earnings), not a data dispute; this report keeps to the consistent StreetStats/FactSet bases.

### Returns

Total returns were 25.02% in 2024 and 17.88% in 2025 [S22]; Macrotrends' price-only figures are 23.31% and 16.39% [S23]. The 2026 year-to-date total return is 12.38% through the 23 October 2026 close [S22]. Yahoo Finance puts the 52-week intraday range at 6,316.91–7,844.52 [S24].

### Earnings run-rate

Blended Q3 2026 earnings growth is 29.0% as of 16 October (29.2% at 30 September) [S7][S8]. Of the 9% of companies reported, 84% beat EPS estimates versus a 78% five-year average, but the aggregate surprise of +2.6% trails the +7.5% five-year average [S7][S8]. The calendar-2026 consensus is +32.8% [S7]; StreetStats' 18.10% one-year earnings-growth figure is a model input, not a consensus statistic [S1].

### Figure: S&P — United States

![S&P — United States](demos/sp500-2027/research-charts/data_fred_sp500_27cd291ad955bc97.png)

*Official series from FRED; latest observation marked: up from a year earlier, near the top of the charted range; hollow marker = partial period. [S2]*

### Figure: S&P (year-over-year % change) — United States

![S&P (year-over-year % change) — United States](demos/sp500-2027/research-charts/data_fred_sp500_yoy_449476441e338eb4.png)

*Official series from FRED; latest observation marked: down from a year earlier; hollow marker = partial period; breaks mark missing periods. [S10]*

## Official Data Baseline

| Series | Latest historical value | Period | Yearly change | Status | Publisher projection | Source |
|---|---|---|---|---|---|---|
| S&P 500 — United States | 7669.4143 Index | 2026-09 | +1085.3962 (+16.485%) | stored observation | — | [S2] |
| S&P 500 (year-over-year % change) — United States | 16.485% change from year ago | 2026-09 | -0.642 pp | stored observation | — | [S10] |
| Central bank policy rates - United States - Monthly - End of period | 3.875% per year | 2026-09 | -0.25 pp | stored observation | — | [S25] |
| Smoothed U.S. Recession Probabilities | 0.62% | 2026-08 | -0.24 pp | stored observation | — | [S13] |
| Real-time Sahm Rule Recession Indicator — United States | 0 Percentage Points | 2026-09 | -0.23 (-100%) | stored observation | — | [S17] |
| Average Hourly Earnings of All Employees, Total Private — United States | 37.81 Dollars per Hour | 2026-09 | +1.11 (+3.025%) | stored observation | — | [S26] |
| Monthly Treasury Statement: Customs Duties (current month) — United States | 5910402249.78 U.S. dollars (≈ 5.91 billion U.S. dollars) | 2026-09 | -23764551072.46 (-80.083%) | stored observation | — | [S27] |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States | 0.896% | 2026-09 | +0.841 pp | stored observation | — | [S18] |
| Federal Funds Effective Rate — United States | 3.75% | 2026-09 | — | stored observation | — | [S28] |
| Federal Funds Target Range - Upper Limit — United States | 4% | 2026-09 | — | stored observation | — | [S11] |
| Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States | 3.025% change from year ago | 2026-09 | -0.824 pp | stored observation | — | [S29] |
| Federal Funds Effective Rate — United States | 3.747% | 2026-09 | — | stored observation | — | [S30] |

## Earnings growth path and AI-capex breadth

### Projections (kept separate from observations)

| Publisher | Vintage | Period | Projection | Type |
|---|---|---|---|---|
| FactSet Earnings Insight | 16 Oct 2026 | Q4 2026 | +28.6% YoY earnings growth | Bottom-up consensus [S7] |
| FactSet Earnings Insight | 16 Oct 2026 | CY 2026 | +32.8% YoY earnings growth | Bottom-up consensus [S7] |
| FactSet Earnings Insight | 9 Oct 2026 | CY 2027 | +15.8% YoY earnings growth | Bottom-up consensus [S6] |
| Goldman Sachs Research | 23 Sep 2026 | CY 2027 / CY 2028 | EPS $415 / $460 (~11% per year) | Sell-side forecast [S31] |
| Goldman Sachs Research | 23 Sep 2026 | Next 12 months | Index target 8,700, from 7,764 on 21 Sep 2026 | Sell-side target [S31] |
| Oak Harvest, citing FactSet | 21 Aug 2026 | CY 2026 / CY 2027 | EPS $358.66 / $405.17 | Secondary citation [S32] |

FactSet's CY2026 headline slipped from about 33% (9 October) to 32.8% (16 October), with Health Care downward revisions the largest drag [S6][S7]. FactSet's own dollar CY2027 EPS was not directly retrievable; the $405.17 figure is a secondary August-vintage citation [S32], close to StreetStats' $406.12 forward aggregation [S1].

### Momentum

Blended Q3 2026 growth of 29.0% marks a third consecutive quarter above 25% [S7]. Goldman Sachs Research notes EPS grew 51% year over year in Q2 2026 and 26% over the trailing four quarters, versus a 30-year average of 7% [S31]. Prices have tracked earnings: the index was up 16.485% year over year in September 2026 [S10].

### AI-capex share

Goldman Sachs Research attributes "almost half" of 2026 index EPS growth to AI investment and estimates the largest US hyperscalers will spend $800 billion on capex in 2026, +94% over 2025, with that contribution fading into AI-productivity gains in 2027-2028 [S31]. NVIDIA chief executive Jensen Huang has claimed $600 billion in annual hyperscaler capex, a figure The Cube Research says the leading hyperscalers do not validate [S33] — a caution on the narrative underpinning top-10 earnings.

### Breadth beyond mega-caps

Breadth has widened at the mega-cap boundary: estimated Q3 2026 growth is 33.2% for the "Magnificent 7" versus 27.7% for the other 493 companies, an unusually narrow gap [S34]; for Q4 2026 analysts predict 23.6% versus 30.6%, which would be the first Mag 7 underperformance since Q4 2022 [S34]. Concentration at the very top remains decisive: excluding Micron and NVIDIA alone drops blended Q3 2026 growth from 29.0% to 20.0% [S34]. The largest year-over-year index EPS contributors were Micron (33.42 vs 3.03), Meta (6.58 vs 1.05), NVIDIA (2.47 vs 1.30), EchoStar (0.17 vs −44.37) and Boeing (−0.24 vs −7.47) [S8].

### 2027 quality caveats

Goldman Sachs Research estimates large technology companies recorded roughly $150 billion of unrealized private-company investment gains in Q2 2026 — 12% of index EPS — expected to shrink materially in 2027 [S31]. Energy is projected to swing from +86.7% growth in Q1 2027 to −21.3% in Q2 2027 and −19.5% in Q3 2027 [S6]. FactSet's blended Q3 2026 net margin of 14.9%, after Q2 2026's 15.7%, is reported as the second-highest in more than 15 years [S8][S35].

## Fed policy and recession risk

### Policy stance and path to end-2027

The Federal Funds Effective Rate — United States averaged 3.75% in September 2026 [S28], with a daily effective rate of 3.88% on 2026-10-22 [S30], and the Federal Funds Target Range - Upper Limit was 4% on 2026-10-23 [S11]; CME FedWatch lists the current target range as 375–400 bps [S36]. BIS records the US policy rate (end of period) at 3.875% per year in 2026-09, versus 4.125% in 2025-09 [S25], after 3.625% from February through August 2026 [S25]; J.P. Morgan's summary of the September 2026 FOMC statement records a unanimous 25 bp hike [S12]. For the 28 October 2026 meeting, FedWatch (21 Oct 2026) prices an 83.9% probability of no change and 16.1% of a hike [S36].

Market-implied and official paths to end-2027 diverge. StreetStats' futures-implied path (close of 20 Oct 2026) rises to about 4.1% by January 2027 and roughly 4.7% by October 2027, holding near 4.6% into 2031 [S37]; the October 2027 fed funds future trades at 95.44, implying about 4.56% [S38]. J.P. Morgan's read of the September 2026 Summary of Economic Projections reports a median fed funds rate of 4.1% at end-2026, unchanged through 2027, with a 2027 participant range of 3.125% to 4.375% [S12]; the SEP's own medians show PCE inflation of 2.3% (2026) and 2.4% (2027) and unemployment of 4.1% [S39]. The futures premium over the SEP partly reflects term premia and SOFR blending in far-dated contracts, per StreetStats' methodology note, rather than pure policy expectations [S37].

| Decision point | Market-implied | Official projection | Discriminates |
| --- | --- | --- | --- |
| 27–28 Oct 2026 FOMC [S16] | 83.9% hold / 16.1% hike (21 Oct 2026) [S36] | — | A hike tightens the multiple constraint on AI-driven reacceleration (35%) |
| 8–9 Dec 2026 FOMC with SEP [S16] | — | Median 4.1% end-2026, per J.P. Morgan [S12] | Hawkish revision feeds Melt-up then correction (30%) |
| 2027 meetings (dates unpublished) [S16] | ~4.56%–4.7% implied by late 2027 [S38][S37] | Median 4.1% through 2027 [S12] | Rates held above 4.5% pressure the multiples at risk in Bear market and drawdown (20%) |

### Recession probability indicators

Labor-market models sit near zero: Smoothed U.S. Recession Probabilities were 0.62% in 2026-08, versus 0.86% in 2025-08 and a five-year high of 2.32% (2024-01) [S13], and the Real-time Sahm Rule Recession Indicator — United States was 0 Percentage Points in 2026-09 against its 0.50pp trigger [S17]. The curve is steep, not inverted: 10-year minus 3-month Treasuries averaged 0.896% in 2026-09 and 0.78% on 2026-10-23 [S18].

The New York Fed's yield-curve model puts the average probability of a US recession 12 months ahead at 0.28 for 2026 and 0.15 for 2027 — estimates the Bank states are not official forecasts [S14][S40]. The Cleveland Fed's yield-curve model put the probability of a US recession within one year at 11.4% for September 2026 [S41]. Polymarket's "US recession by end of 2026?" contract was quoted at an 8% chance [S42]. No named source in the evidence publishes a probability for a credit event or a policy shock before end-2027, and the WSJ survey's numeric consensus probability was not retrievable [S43].

### Signposts

- SAHMREALTIME at or above 0.50pp would confirm the labor signature of Hard landing recession (10%) [S17].
- RECPROUSM156N sustained above its five-year high of 2.32% would signal recession onset consistent with Bear market and drawdown (20%) [S13].
- A negative T10Y3M would lift the NY Fed model's 12-month-ahead probability and challenge the discount-rate assumption in AI-driven reacceleration (35%) [S18][S14].

### Figure: Central bank policy rates - United States - Monthly - End of period

![Central bank policy rates - United States - Monthly - End of period](demos/sp500-2027/research-charts/data_bis_ws_cbpol_m_us_eae44f753af36114.png)

*Official series from the BIS; latest observation marked: down from a year earlier. [S25]*

### Figure: Smoothed U.S. Recession Probabilities

![Smoothed U.S. Recession Probabilities](demos/sp500-2027/research-charts/data_fred_recprousm156n_f364c815868fac8b.png)

*Official series from FRED; latest observation marked: down from a year earlier, near the bottom of the charted range. [S13]*

## Concentration risk in mega-cap tech

### Weight versus earnings share

RBC Wealth Management's "Great Narrowing" analysis puts the S&P 500 top-10 weight at a record 40.7% in 2025, versus roughly 19% at end-2015 and an 18%–23% band from 1990 to 2015 [S9]. In 2025 the top 10 were about 41% of index weight but were expected to generate only about 32% of index earnings — a gap that has widened since 2015, when weight and earnings were aligned near 19% each [S9]. No official current figure exists: S&P DJI's Top 10 factsheet tables did not render [S44], while a Slickcharts SPY-holdings snapshot of 2026-10-23 implies a top-10 weight of roughly 38%–39%, a derived sum whose holdings figures could not be verified [S45]. The question is live because the index carries momentum: the S&P 500 year-over-year price change was 16.485% in September 2026 [S10]. Guinness Global Investors (as of 31 December 2025) reports the ten largest stocks grew market value 29% over the trailing period versus roughly 19% for the index and 13% for the rest, while arguing mega-cap earnings dominance is "now fading" [S46] — an offset to RBC's risk framing [S9].

### AI-capex dependence inside the top 10

Earnings growth is concentrated in AI names: excluding only Micron and NVIDIA, FactSet's blended Q3 2026 S&P 500 earnings growth falls from 29.0% to 20.0%, and the top five contributors are Micron, NVIDIA, Meta Platforms, EchoStar and Boeing [S34]. Index-level Q3 2026 EPS contributions versus Q3 2025: Micron $33.42 vs $3.03, Meta $6.58 vs $1.05, NVIDIA $2.47 vs $1.30, EchoStar $0.17 vs −$44.37, Boeing −$0.24 vs −$7.47 [S8]. Goldman Sachs Research estimates AI investment is driving almost half of 2026 S&P 500 EPS growth and that the largest hyperscalers are on track to spend $800 billion of capex in 2026, +94% over 2025 [S31]; Nvidia CEO Jensen Huang's claim of $600 billion in annual hyperscaler capex is flagged by The Cube Research as unvalidated by the leading hyperscalers [S33]. For severity, Morgan Stanley's 1985–2024 study of more than 6,500 single stocks found a median maximum drawdown of −85.4% [S47] — the idiosyncratic bound on the de-rating channel behind Bear market and drawdown (20%). Only 23.2% of the top 500 US stocks beat the S&P 500 over the latest ten-year window through end-August 2026, per Ben Carlson [S48].

### Transmission channels and signposts

RBC documents the transmission: concentration means S&P 500 diversification "increasingly functions as a concentrated allocation in a single thematic outcome," so a top-10 de-rating passes one-for-one through index weight, amplified by passive flows, and hits the cap-weighted index far harder than the average stock — the equal-weight divergence channel [S9]. Alphabet's dual share classes illustrate single-company exposure: a combined weight of about 5.63%, derived from the same unverified Slickcharts snapshot, would rank third behind Nvidia and Apple [S45]. Signposts: FactSet's Magnificent 7 versus other-493 growth gap — 33.2% vs 27.7% in Q3 2026, with Q4 2026 predicted at 23.6% vs 30.6%, the first Mag 7 underperformance since Q4 2022 if realised [S34] — measures the broadening that AI-driven reacceleration (35%) requires, whereas renewed Micron/NVIDIA dependence would mark the fragility central to Melt-up then correction (30%) [S34].

## Margin sensitivity: wages and tariffs

Index profitability is near cyclical highs, but the cushion is narrow. FactSet reports a blended S&P 500 net profit margin of 14.9% for Q3 2026, the second-highest in more than 15 years after 15.7% in Q2 2026, and has cited 13.9% for calendar 2026 [S8][S35][S49]. Excluding Micron and NVIDIA alone, Q3 2026 blended earnings growth falls from 29.0% to 20.0%, so margin resilience is concentrated rather than broad-based [S8].

### Wage-cost channel
Average Hourly Earnings of All Employees, Total Private were 37.81 Dollars per Hour in the United States (2026-09) against 36.7 a year earlier [S26]; year-over-year growth of 3.025% is down 0.824 pp from 3.848% (2025-09) and sits at the bottom of a five-year range topped by 4.214% (2025-03) [S29]. The Atlanta Fed Wage Growth Tracker eased to 3.9% in September 2026 from 4.1% in August, with job-stayers at 3.4% and job-switchers at 4.7% in the 8 October 2026 update [S50].

| Series | Latest (period) | Comparison | Direction |
| --- | --- | --- | --- |
| AHE YoY, total private, US [S29] | 3.025% (2026-09) | 3.848% (2025-09) | Decelerating |
| AHE level, US [S26] | 37.81 Dollars per Hour (2026-09) | 36.7 (2025-09) | Rising, slower |
| Net customs duties, US [S27] | 5910402249.78 U.S. dollars (2026-09) | 29674953322.24 (2025-09) | Refund-distorted fall |
| Effective tariff rate [S51] | 7.1% (Aug 2026) | 6.7% (Jul 2026); 10.1% pre-substitution | Partial rebound |
| Wage Growth Tracker [S50] | 3.9% (Sep 2026) | 4.1% (Aug 2026) | Decelerating |

### Tariff-cost channel
The average US effective tariff rate was 7.1% in August 2026, up from 6.7% in July but below January, after the Supreme Court's 20 February 2026 ruling that IEEPA tariffs were unconstitutional; it was 2.3% in January 2025 [S51]. Section 122 tariffs expired 24 July 2026, replaced by Section 301 tariffs of 10 or 12.5% on imports from 60 economies, with a pre-substitution rate of 10.1% [S51]. Burdens remain uneven — China 24.3%, steel and aluminium 39.8%, automotive 13.8%; 81.4% of Canada/Mexico imports claim USMCA exemptions [S51]. Yale Budget Lab's April 2026 vintage put the January rate at 10.6% and estimated $214.7 billion of revenue above the 2022–2024 average, with roughly $165 billion possibly refunded; PWBM counts $314.8 billion gross through August 2026 — differences of vintage and baseline, not substance [S52][S51]. Net customs duties swung within five years from 31353501081.11 U.S. dollars (2025-10) to -25555668440.83 U.S. dollars (2026-06), a refund-distorted range [S27], and BLS reported import prices up 8.1% year over year in September 2026 (nonfuel +6.0%, fuel +34.5%) [S53][S54].

### What this implies for 2027
Yale's incidence framework — tariffs land on foreign producers, importer margins or consumers — is descriptive, and no published elasticity of S&P 500 margins to the effective tariff rate was found [S52]. With wages cooling and effective tariffs below their January peak, measured incremental cost pressure into 2027 looks modest, conditional on no escalation; the larger risk is profitability concentrated in AI-levered names [S8][S50][S51].

| Signpost | Threshold | Discriminates |
| --- | --- | --- |
| AHE YoY [S29] | Back above 4.214% (five-year high) | Cost pressure challenging AI-driven reacceleration — 35% |
| Effective tariff rate [S51] | Back above the 10.1% pre-substitution mark | Revives the cost-shock channel behind Bear market and drawdown — 20% |
| FactSet blended net margin [S49] | CY2027 below the 13.9% CY2026 projection | Erodes earnings support in Melt-up then correction — 30% |

### Figure: Average Hourly Earnings of All Employees, Total Private — United States

![Average Hourly Earnings of All Employees, Total Private — United States](demos/sp500-2027/research-charts/data_fred_ces0500000003_063a14ec551b71b4.png)

*Official series from FRED; latest observation marked: up from a year earlier, the highest in the charted period. [S26]*

### Figure: Monthly Treasury Statement: Customs Duties (current month) — United States

![Monthly Treasury Statement: Customs Duties (current month) — United States](demos/sp500-2027/research-charts/data_usgov_treasury_mts_customs_duties_237244547d210738.png)

*Official series from U.S. Treasury Fiscal Data; latest observation marked: down from a year earlier. [S27]*

## Valuation mean-reversion and return base rates

### Starting-valuation class and measure
The S&P 500 trailing as-reported P/E was 26.15 on 22 October 2026 (Multpl, Shiller-derived data) and has exceeded 22 every month since January 2024 [S4][S5]. Definition matters: StreetStats puts the trailing P/E at 22.28 on blended trailing-actual EPS of $343.87, and FactSet's forward 12-month P/E is 19.0, below its 5-year (19.8) and 10-year (19.1) averages [S1][S7]. The stored FRED series anchors the level: 7669.4143 (2026-09 monthly mean), five-year range 3726.05 (2022-10) to 7711.3233 (2026-08) [S2]. Settlement basis: official daily closes, with drawdowns measured peak-to-trough on closing levels, the convention of the bear-market table used here [S55].

### Two-year outcomes from P/E>22 starts
Returns are computed from fred:SP500 monthly means; drawdowns per closing-basis sources.

| Start | Trailing P/E [S4] | 2-year price return | Largest intra-window drawdown | 20% breach? |
| --- | --- | --- | --- | --- |
| Jan 2004 | 22.73 | ≈+10% | — | No |
| Jan 2017 | 23.59 | +14.3% [S2] | Q4 2018 ≈−19.8% (daily close) | No (near miss) |
| Jan 2021 | 35.96 | +0.2% [S2] | −25.4%, Jan–Oct 2022 [S55] | Yes |
| Jan 2024 | 25.01 | +28.7% [S2] | Spring 2025 ≈−10.7% (monthly means) [S2] | No |

A wider Multpl-based set (2003–2021 calendar starts) shows two-year price returns of ≈+34%, +20%, +12%, +21%, +37% and −1% — median ≈+20%, no episode worse than about −1% [S4][S15]. Elevated starting multiples produced flat-to-strong two-year returns far more often than losses.

### Drawdown frequency and context
The two constructions in the evidence give 1 of 4 post-2003 starts and 2 of 7 on the wider set (adding the 2018 start that caught COVID's −33.79% fall in 23 trading days); Laplace-adjusted, both round to about 33% [S2][S56][S4]. Adding the dot-com start — P/E above 22 in the late 1990s, then the March 2000–October 2002 bear of −49.1% over 31 months — yields 2 of 5, about 40% [S55][S4]. These are computed reference-class counts on small, partly overlapping samples, not published probabilities. Unconditionally, 13 closing-basis bears since 1929 (roughly one every 7 years) show a median −33.9% decline and 17 months to trough; July 1990's −19.18% over 62 trading days shows how near high-multiple regimes came without breaching [S55][S56].

### Fit to the scenario frame
The frame gives 30% combined weight to breach scenarios — Bear market and drawdown — 20% and Hard landing recession — 10% — at the low end of the computed 33–40% band, while the near-miss cluster (Q4 2018 ≈−19.8%; the 2011 ≈−19% correction) is the historical signature of Melt-up then correction — 30% [S56]. Goldman Sachs Research's 12-month target of 8,700 (from 7,764 on 21 September 2026), implying a forward P/E near 19x, is the cited forecaster view most consistent with no near-term mean reversion [S31]. Falsifiers: AI-driven reacceleration — 35% dies on a 20% closing-basis drawdown; Stagnant sideways grind — 5% needs the trailing multiple compressing toward 22 with prices roughly flat [S4].

| Signpost | Threshold | Discriminates |
| --- | --- | --- |
| Multpl trailing as-reported P/E [S4] | Below 22 without a 20% closing drawdown | Compression via earnings; supports AI-driven reacceleration — 35% |
| fred:SP500 daily close [S2] | 20% below any 2026–2027 closing peak | Settles the breach question; Bear market and drawdown — 20% / Hard landing recession — 10% |
| FactSet CY2027 EPS growth estimate [S6] | Revised below ~10% (Oct 2026: 15.8%) | Kills AI-driven reacceleration — 35% |

## Macro backdrop: GDP and leading indicators

The observable backdrop combines a positively sloped yield curve, a cooling labour market and a Fed that has resumed tightening. The federal funds target-range upper limit for the United States is 4% (September 2026, and the daily value on 2026-10-23) [S11]; the effective rate averaged 3.75% in September 2026, up from 3.63% in June 2026 [S28], printed 3.88% on 2026-10-22 [S30], and the BIS end-of-September policy rate is 3.875% per year [S25]. J.P. Morgan's summary of the September 2026 FOMC statement reports a unanimous 25 bp hike [S12].

### Regime dashboard

| Block | Series | Latest (period) | Momentum | Shift flag |
|---|---|---|---|---|
| Policy | Fed funds target-range upper limit [S11] | 4% (2026-09; daily 2026-10-23) | +25 bp hike, September 2026 FOMC, per J.P. Morgan's summary [S12] | Hawkish; 16.1% hike odds for 28 Oct (21 Oct 2026) [S36] |
| Money market | Effective fed funds [S28][S30] | 3.75% (2026-09); 3.88% daily (2026-10-22) | Rising from 3.63% (2026-06) | Drifting to range top |
| Yield curve | 10Y–3M Treasury spread [S18] | 0.896% (2026-09) | 0.055% a year earlier | Positive; no inversion signal |
| Labour | Real-time Sahm rule [S17] | 0 pp (2026-09) | ≤0.27 pp since February 2026 | None |
| Labour cost | AHE, total private, YoY [S29] | 3.025% (2026-09) | 3.848% (2025-09) | Cooling |
| Cycle | Smoothed recession probability [S13] | 0.62% (2026-08) | 0.24% in July; 0.86% in Aug 2025 | None |

### Growth path versus official projections

The growth path to 2027 rests on projections; no official GDP print was retrieved for this section. The September 2026 FOMC projections show median PCE inflation of 2.3% (2026) and 2.4% (2027) and median unemployment of 4.1% in both years [S39], with median real GDP of 2.0% (2026) and 2.1% (2027) reported from the same materials [S39]. SIFMA's economist panel posts median US GDP growth of 2.2% for Q4 2026 and 2.0% for Q4 2027 over Q4 2026, core CPI declining to 2.4% by Q4 2027, and a majority seeing one further Fed cut [S57]. Goldman Sachs Research ties its 2027 earnings path to solid GDP growth [S31]; Oxford Economics forecasts global GDP growth back into a 2.8%–3.0% range [S58].

### Policy path: official projection versus market

Per J.P. Morgan's summary, the September SEP median is 4.1% at end-2026 and holds at 4.1% through 2027 — 16 of 18 participants expect one more 2026 hike — with 2027 dispersion from 3.125% to 4.375% [S12]. StreetStats' futures-implied path (20 October 2026 close) rises to about 4.1% by January 2027 and roughly 4.7% by October 2027, near 4.6% through 2031, a blend of SOFR futures and term premia rather than pure policy expectations [S37]. CME FedWatch (21 October 2026) prices 83.9% no change and 16.1% a hike for 28 October, after hike odds of 57.6% a month earlier [S36]. A much lower SEP median (3.4% end-2026, 2.5% end-2027) circulates but was not confirmed on the fetched projections page and is treated as unconfirmed [S39]. The dealer panel's single further cut [S57] sits closer to the SEP than to futures.

### Decision calendar and scenario fit

The remaining 2026 FOMC meetings are 27–28 October and 8–9 December, the latter with an SEP; 2027 dates were not yet published [S16]. The New York Fed updates its recession model within the first two weeks of each month and disclaims the estimates as official forecasts [S40]. A positive curve (0.896%, September 2026 [S18]) with a zero Sahm reading [S17] fits the no-recession scenarios — AI-driven reacceleration — 35%, Melt-up then correction — 30% and Stagnant sideways grind — 5% — and would have to break, or be overridden by non-curve shocks, for Hard landing recession — 10%.

### Figure: Real-time Sahm Rule Recession Indicator — United States

![Real-time Sahm Rule Recession Indicator — United States](demos/sp500-2027/research-charts/data_fred_sahmrealtime_bbf917e8a5cc3c29.png)

*Official series from FRED; latest observation marked: down from a year earlier, near the bottom of the charted range; breaks mark missing periods. [S17]*

### Figure: Ten-Year Treasury Constant Maturity Minus Three-Month Treasury Constant Maturity — United States

![Ten-Year Treasury Constant Maturity Minus Three-Month Treasury Constant Maturity — United States](demos/sp500-2027/research-charts/data_fred_t10y3m_4aefaf7432bbac9a.png)

*Official series from FRED; latest observation marked: up from a year earlier; hollow marker = partial period. [S18]*

## Exogenous risks and documented hazards

### Published recession probabilities

The smoothed US recession-probability model reads 0.62% for August 2026, versus 0.86% in August 2025 [S13]. The New York Fed's Treasury-spread model puts the average probability of a US recession twelve months ahead at 0.28 for 2026 and 0.15 for 2027, down from 0.60 in both 2024 and 2025 [S14]. The Cleveland Fed's model puts the probability of a US recession within one year at 11.4% for September 2026, down from 12.3% in August and 13.6% in July, on a 3-month bill at 4.20% and a +88 bp slope [S41]. YCharts' US recession probability series shows 13.88% for August 2027, against 15.19% a month earlier and 28.85% a year earlier [S59]. Polymarket's "US recession by end of 2026?" contract was quoted at an 8% chance [S42]. The last clearly dated vintage of J.P. Morgan Research's series put a 2025 US/global recession at 40%, cut from 60%; no 2026–2027 figure was retrieved [S60].

These are not interchangeable: the smoothed series is a contemporaneous state probability, the Fed-bank models are twelve-month-ahead term-spread predictions the New York Fed explicitly disclaims as forecasts [S40], and prediction markets price event risk. The WSJ survey archive's headlines point to falling economist recession expectations, but its numeric probability was unreadable [S43].

### Credit and policy shocks

For credit events, no named source publishes a probability or window before end-2027; the only proxy retrieved is the high-yield corporate spread at about 3.33% in October 2026 (3.27–3.33%), around the 78th percentile per MacroRadar [S61]. No market-based or institutional probability was found for a policy shock such as a government shutdown or fresh tariff escalation. CME FedWatch prices a 16.1% probability of a hike at the 28 October 2026 meeting (as of 21 October 2026) [S36]. Documented policy hazards are events rather than odds: the Supreme Court ruled IEEPA tariffs unconstitutional on 20 February 2026, Section 122 tariffs expired 24 July 2026 and were replaced by Section 301 tariffs of 10 or 12.5% on imports from 60 economies, leaving an effective tariff rate of 7.1% in August 2026 versus 2.3% in January 2025 [S51]; Yale Budget Lab estimates roughly $165 billion may be returned via IEEPA refunds [S52], and customs duties net of refunds swung from -25555668440.83 US dollars (June 2026) to 5910402249.78 US dollars (September 2026) [S27].

### Named hazard windows for 2027

Oxford Economics' 2027 outlook names "oil market stress or a disorderly end to the AI boom" as the principal risks, with global GDP growth forecast back into a 2.8%–3.0% range; any US-specific probability in it is unconfirmed [S58]. Goldman Sachs Research documents an endogenous AI hazard: AI investment drives almost half of 2026 EPS growth and its contribution "will fade going forward," while roughly $150 billion of unrealized private-company gains — 12% of Q2 2026 EPS — should shrink materially in 2027 [S31]. Curve models cannot see these: the 10Y–3M spread's 0.896% September 2026 average [S18] is what holds their probabilities down, so low readings are a scope limitation, not reassurance.

| Date | Event | Published implied move | Discriminates |
|---|---|---|---|
| 27–28 Oct 2026 | FOMC meeting [S16] | 83.9% no change / 16.1% hike (FedWatch, 21 Oct 2026) [S36] | AI-driven reacceleration — 35% vs Melt-up then correction — 30% |
| 8–9 Dec 2026 | FOMC with SEP [S16] | None published in evidence | Hard landing recession — 10% |
| First two weeks, monthly | NY Fed recession-model update [S40] | Not applicable | Hard landing recession — 10% |
| Q4 2026–Q1 2027 | Hyperscaler 2027 capex guidance (NVIDIA, Microsoft, Alphabet, Amazon, Meta) | None published in evidence | Bear market and drawdown — 20% vs AI-driven reacceleration — 35% |

Falsifiers: a smoothed recession probability rising toward its January 2024 high of 2.32% [S13] would be the first labour-model support for Hard landing recession — 10%; two or more hyperscalers cutting 2027 capex guidance would undercut AI-driven reacceleration — 35% and feed Bear market and drawdown — 20%.

## Actor incentives and decision calendar

The FOMC's remaining 2026 meetings are October 27–28 and December 8–9, the latter with a Summary of Economic Projections; 2027 dates are not yet published on the Federal Reserve's calendar [S16]. The target-range upper limit is 4% (latest daily observation, 2026-10-23) [S11], the effective federal funds rate averaged 3.75% in September 2026 [S28], and BIS records the end-September policy-rate midpoint at 3.875% [S25]. Per J.P. Morgan's summary, September's 25 bp hike was unanimous, the SEP median holds 4.1% from end-2026 through 2027 (16 of 18 participants see one more 2026 hike), 2027 dots span 3.125% to 4.375%, and Chair Warsh submitted no dot for a second consecutive SEP, with projections revised toward stronger growth, higher inflation and lower unemployment [S12]. A smoothed recession probability of 0.62% (August 2026) [S13] and a Sahm indicator of 0 percentage points (September 2026) [S17] leave the Committee room to hold or hike.

### Policy path to end-2027

| Decision point | Market-implied (risk-neutral) | Official projection | Discriminates |
|---|---|---|---|
| FOMC, Oct 27–28, 2026 [S16] | 83.9% no change / 16.1% hike (CME FedWatch, 21 Oct 2026) [S36] | SEP median 4.1% at end-2026 [S12] | AI-driven reacceleration — 35% needs a benign rate path |
| FOMC, Dec 8–9, 2026, with SEP [S16] | none published in the evidence | fresh dots; 2027 span 3.125%–4.375% [S12] | Bear market and drawdown — 20% on a hawkish surprise |
| End-2027 policy rate | about 4.7% by Oct 2027 (StreetStats futures path, 20 Oct 2026) [S37] | SEP median 4.1% through 2027 [S12] | Melt-up then correction — 30% if the futures path prevails |

The SEP–futures divergence is the calendar's central tension, and the December SEP is its resolution point [S12][S37].

### Earnings catalysts and strategist anchors

No dated Q4 2026 or 2027 earnings-release calendar for the mega-caps appears in the evidence; anchors are reporting-season aggregates. FactSet puts Q4 2026 growth at 28.6% and CY2026 at 32.8% [S7], with CY2027 growth of 15.8% projected in its October 9, 2026 report [S6]. Goldman Sachs (September 23, 2026) forecasts 2027 EPS of $415 and 2028 EPS of $460, with a 12-month index target of 8,700 from 7,764 on September 21, 2026 [S31]. For Q4 2026 analysts expect the Magnificent 7 to grow earnings 23.6% versus 30.6% for the other 493 — the first Mag 7 underperformance since Q4 2022 if realised [S34]; excluding Micron and NVIDIA, Q3 2026 blended growth falls from 29.0% to 20.0% [S34]. Hyperscalers are on track to spend $800 billion of capex in 2026, +94% over 2025 [S31], while NVIDIA's CEO's $600 billion hyperscaler-capex claim is unvalidated per The Cube Research [S33].

### Signposts

| Indicator | Threshold | Date | Moves |
|---|---|---|---|
| Mag 7 vs other-493 EPS growth [S34] | other 493 outgrow the Mag 7 | Q4 2026 reports | confirms the breadth behind AI-driven reacceleration — 35% |
| Top-10 index weight | above the record 40.7% [S9]; roughly 38–39% now per a Slickcharts snapshot [S45] | end-2027 | concentration leg of Melt-up then correction — 30% |
| Unrealized private-company gains (~$150 billion, 12% of Q2 2026 EPS) [S31] | shrink materially through 2027 | 2027 reports | Stagnant sideways grind — 5% if index EPS flattens |

## Scenarios and probabilities

### Scenario Probability Distribution
- **AI-driven reacceleration (35% probability):** Broadening earnings growth of roughly 10-15% annually and stable multiples carry the index to new highs, with no 20% drawdown; prior: bull-market continuation after double-digit EPS growth.
- **Melt-up then correction (30% probability):** Earnings deliver but valuations overshoot, then a mid-horizon 10-19% correction resets multiples while the index still ends 2027 modestly higher; prior: high-multiple regimes often see double-digit corrections without a 20% breach.
- **Bear market and drawdown (20% probability):** An AI-capex disappointment or mild recession triggers a 20%+ drawdown and a negative two-year return; prior: roughly 1 in 5 two-year windows from elevated multiples ended in a bear market.
- **Hard landing recession (10% probability):** Policy or credit shock causes a recession, a 25-35% drawdown and a 2027 close well below 2026 levels; prior: US recession began in roughly 1 of 6.5 years since 1948.
- **Stagnant sideways grind (5% probability):** Flat earnings revisions and multiple compression leave the 2027 close within a few percent of today with shallow drawdowns; residual case for range-bound markets.

The starting point sits squarely in the high-multiple class: trailing as-reported P/E was 26.15 on October 22, 2026, above 22 continuously since January 2024 [S4][S5]; the index rose 16.485% year over year as of September 2026 [S10]; the fed funds target-range upper limit is 4% as of the 2026-10-23 daily value [S11]. Each scenario below is scored against base rates computed from exactly that class.

### Base rates

| Reference class | Counting rule | k/n | Window | Source | Applicability |
| --- | --- | --- | --- | --- | --- |
| Trailing as-reported P/E > 22, non-overlapping January starts | −20% or worse closing-basis drawdown within 24 months | 1/4 | 2004, 2017, 2021, 2024 | [S4][S55][S2] | Best fit; current 26.15 is in-class |
| Same class, dot-com era added | as above | 2/5 | adds the 2000 start (−49.1% bear) | [S55][S4] | Captures a technology-capex unwind |
| Overlapping P/E > 22 starts | as above | 2/7 | 2003–2021 | [S56][S4] | Overlapping windows inflate n |
| All bear markets | closing-basis −20%+ | 13 since 1929, about one per 7 years | 1929–2022 | [S55] | Regime-free floor |

Conditional classes span roughly 33% (Laplace-adjusted 1/4) to 40% (2/5); the non-overlapping post-2003 class fits best, though n is small. Two-year price outcomes from those starts ranged from about +0.2% to +28.7%, with one intra-window bear [S2].

### Anchor-to-scenario bridge

| Scenario | Anchor (class, k/n) | Adjustments: direction, mechanism, evidence | Why not already in the class | Reads vs frame weight |
| --- | --- | --- | --- | --- |
| AI-driven reacceleration — 35% | Class 2-yr returns +0.2% to +28.7% [S2] | Up: FactSet CY2027 growth 15.8% [S6]; Goldman Sachs EPS $415 in 2027 [S31]. Down: ~$150bn unrealized gains (12% of Q2-2026 EPS) fade in 2027 [S31] | Class predates AI breadth (Mag 7 33.2% vs 493 at 27.7% in Q3 2026) [S34] | Consistent |
| Melt-up then correction — 30% | Near-misses from >22 starts: ~−19.8% (Q4 2018), ~−19% (2011) [S56][S4] | Up: Goldman Sachs 12-month target of 8,700 implies overshoot room [S31] | Class records breaches only, not 10–19% corrections | Consistent |
| Bear market and drawdown — 20% | 1/4 to 2/5 conditional [S4][S55] | Down: smoothed recession probability 0.62% (Aug 2026) [S13]; Sahm 0 pp (Sep 2026) [S17]. Up: top-10 weight 40.7% vs ~32% of earnings [S9]; ex-Micron/NVIDIA growth 20.0% vs 29.0% [S34] | Labor-market models and the +0.896% 10Y–3M spread (Sep 2026) [S18] are not in the class | Consistent |
| Hard landing recession — 10% | Unconditional ~1 bear per 7 years [S55] | Up: futures imply roughly 4.56% by Oct 2027 [S38] vs an SEP median of 4.1% through 2027 per J.P. Morgan's summary [S12] | No re-tightening episode in the class | Consistent |
| Stagnant sideways grind — 5% | 2021-start window ≈ +0.2% [S2] | Requires consensus to stall near 15.8% [S6] while multiples compress | Class contains no AI-capex stall | Consistent, as residual |

The two drawdown scenarios combine to 30%, just under the 33–40% conditional range — a discount resting on near-zero labor-market signals [S13][S17].

### Market comparison and published hazard probabilities

No index-level market on the settlement quantity exists in the evidence; the only market rows condition it. CME FedWatch put 83.9% on no change and 16.1% on a hike for the October 28, 2026 meeting (data as of October 21, 2026) [S36].

The New York Fed's Treasury-spread model publishes an average probability of US recession 12 months ahead of 0.28 for 2026 and 0.15 for 2027 [S14][S40]. The Cleveland Fed's yield-curve model put the probability of a US recession within one year at 11.4% for September 2026 [S41]. Polymarket's "US recession by end of 2026?" contract was quoted at an 8% chance [S42]. The evidence records no published probability for a credit event before end-2027; a high-yield spread around 3.33% (October 2026) is the only market proxy [S61].

### Signposts and falsifiers

- AI-driven reacceleration — 35%: confirmed if Q4 2026 realizes the estimated first Mag-7 underperformance since Q4 2022 (23.6% vs 30.6%) [S34] with 2026 hyperscaler capex near $800bn (+94% over 2025) [S31]; falsified by 2027 capex cuts.
- Melt-up then correction — 30%: a forward P/E of 19.0 vs its 5-year average of 19.8 [S7] leaves overshoot room toward 8,700 [S31]; falsified by multiple stability without a double-digit decline.
- Bear market and drawdown — 20%: ex-Micron/NVIDIA growth sliding from 20.0% toward zero [S34] with hike odds repricing beyond 16.1% [S36]; falsified by CY2027 consensus holding 15.8% [S6] with Sahm at 0 pp [S17].
- Hard landing recession — 10%: smoothed recession probability rising from 0.62% toward its 2.32% January 2024 high [S13] and curve inversion from +0.896% (Sep 2026) [S18].
- Stagnant sideways grind — 5%: FactSet CY2027 revisions stalling [S6] while the multiple compresses.

### Key binary and coherence

The drawdown question is an ever-touch event — an official close at or below 80% of any 2026–2027 peak close by December 31, 2027 — and resolves yes only under Bear market and drawdown (20%) and Hard landing recession (10%); its end-state version (the 2027-12-31 close below threshold) is strictly less likely. Recession by end-2027 must be no less likely than recession by end-2026, quoted at 8% on Polymarket [S42].

## Most-likely trajectory

### Basis and settlement
Quoted in official closing levels; end-2027 is the last trading day's close. fred:SP500 stores 7669.4143 Index for 2026-09 (latest daily value 7757.17 on 2026-10-21) and a year-over-year change of 16.485% [S2][S10]; WSJ historical prices report a 7,623.68 close on 2026-10-23 [S3], leaving a working anchor of roughly 7,624–7,757 pending one settlement source. The forward 12-month P/E is 18.87 on forward EPS of $406.12 [S1]; FactSet's forward multiple is 19.0 versus its 5-year average of 19.8 and 10-year average of 19.1 [S7]; trailing P/E is 22.28 on trailing EPS of $343.87 [S1], and 26.15 on Multpl's as-reported basis [S4].

### Modal path
The modal scenario is AI-driven reacceleration — 35%: CY 2026 earnings growth of 32.8% and Q4 2026 growth of 28.6% [S7] roll into 15.8% projected for CY 2027 [S6]. Oak Harvest's August 2026 citation of FactSet bottom-up charts puts dollar EPS at $358.66 for CY 2026 and $405.17 for CY 2027 [S32]; Goldman Sachs Research forecasts $415 for 2027 and $460 for 2028, with hyperscalers on track to spend $800 billion on capex in 2026, +94% over 2025 [S31]. The path holds the multiple near 19x [S7] and lets EPS carry the index.

| Checkpoint | EPS basis | Multiple | Derived close |
|---|---|---|---|
| End-2026 | CY2027 $405.17 [S32] to $415 [S31] | ~19x forward [S7] | ≈7,700–7,900 |
| Mid-2027 | 2027/2028 blend ≈$415–440 [S31] | ~19x [S7] | ≈7,900–8,400 |
| End-2027 | CY2028 $460 [S31] | ~19x [S7] | ≈8,700 (19×460), in line with Goldman Sachs Research's 12-month target of 8,700 [S31] |

End-2027 near 8,700 is ≈14% above the WSJ close [S3]. The only horizon distribution in the evidence is empirical — trailing-P/E>22 calendar starts since 2003, h=24 months, n=4–7 windows — with two-year price outcomes of roughly flat to +29% and a median near +20% [S4][S15][S2]; the modal path lands inside, and below the median of, that distribution. No market-implied horizon distribution appears in the evidence.

### Rates and hazards
The path absorbs rather than uses discount rates: the effective federal funds rate was 3.75% in 2026-09 [S28] and the target-range upper limit 4% [S11]; CME FedWatch prices 83.9% no change and a 16.1% hike probability for the 28 October 2026 meeting [S36]; the October 2027 fed funds contract at 95.44 implies roughly 4.56% [S38], and StreetStats' futures-based path runs from about 4.1% in January 2027 to about 4.7% by October 2027 [S37]. J.P. Morgan's summary of the September 2026 SEP holds its median at 4.1% through 2027 [S12], the dovish alternative.

The New York Fed's yield-curve model puts the average probability of a US recession 12 months ahead at 0.15 for 2027 [S14]. The Cleveland Fed's model put the probability of a US recession within one year at 11.4% for September 2026 [S41].

### Falsifier and signposts
From trailing-P/E>22 starts, one of four non-overlapping post-2003 windows — two of five adding the dot-com start — breached −20% within 24 months, a Laplace-adjusted 33–40% [S4][S55][S2]; any such breach from a 2026–2027 peak moves resolution to Bear market and drawdown — 20% or Hard landing recession — 10%.

| Signpost | Level now | Threshold | Discriminates |
|---|---|---|---|
| FactSet CY2027 growth estimate | 15.8% [S6] | sustained below ~10% | kills AI-driven reacceleration — 35% |
| Real-time Sahm indicator | 0 Percentage Points, 2026-09 [S17] | 0.50pp trigger | Hard landing recession — 10% |
| Multpl trailing P/E | 26.15, 2026-10-22 [S4] | sustained above ~30 | Melt-up then correction — 30% |
| FOMC, 27–28 Oct and 8–9 Dec 2026 (Dec with SEP) | 16.1% hike odds [S36] | hike delivered [S16] | steepens the discount-rate leg of every path |

## Binary forecasts and signposts

All index-level forecasts resolve on S&P Dow Jones Indices official closing values (price basis, no dividend adjustment); the anchor close is 7,662.54 on 2026-10-22 [S1]. EPS binaries resolve on FactSet Earnings Insight bottom-up actuals; policy binaries on the FRED target-range upper limit, 4% as of 2026-10-23 [S11]; recession triggers on FRED SAHMREALTIME (0 percentage points, September 2026) [S17].

### Binary forecasts

| # | Event: threshold and window | P | Resolution source |
|---|---|---|---|
| B1 | ≥20% peak-to-trough decline from any 2026–2027 peak, official closes, before 2028-01-01 | 30% | S&P DJI daily closes; equals "Bear market and drawdown" (20%) + "Hard landing recession" (10%) |
| B2 | Close on 2027-12-31 above 7,662.54 [S1] | 65% | S&P DJI official close |
| B3 | Any close ≥8,700 before 2028-01-01 (Goldman 12-month target) [S31] | 40% | S&P DJI daily closes |
| B4 | A 10–19% correction with no 20% breach ("Melt-up then correction" signature) | 30% | S&P DJI daily closes |
| B5 | CY2026 EPS growth ≥30% (consensus 32.8%) [S7] | 75% | FactSet Earnings Insight actuals, Feb 2027 |
| B6 | CY2027 EPS growth ≥10% (FactSet 15.8% [S6]; Goldman ~11% to $415 [S31]) | 60% | FactSet actuals, Feb 2028 |
| B7 | Q3 2026 blended growth ≥25% (29.0% on Oct 16) [S7] | 75% | FactSet, Dec 2026 |
| B8 | Mag 7 Q4 2026 growth below other-493 (consensus 23.6% vs 30.6%) [S34] | 55% | FactSet Earnings Insight, Feb 2027 |
| B9 | FOMC hikes at the 2026-10-27/28 meeting (futures: 16.1% hike) [S36] | 15% | Target-range upper limit [S11] |
| B10 | Upper limit ≥4.25% at end-2027 (a derived CME reading puts October 2027 near 4.56% [S38]; SEP median 4.1% through 2027 [S12]) | 50% | [S11], 2027-12-31 |
| B11 | Sahm rule trigger (≥0.50pp) before 2028-01-01 [S17] | 15% | FRED SAHMREALTIME monthly |
| B12 | Top-10 index weight ≥38% at end-2027 (record 40.7% in 2025) [S9] | 50% | S&P DJI constituent data [S44] |

The reported drawdown base rate from trailing-P/E>22 starts is roughly 33–40% (2–3 qualifying windows breaching) [S4][S56][S55], bracketing B1.

### Catalyst calendar

| Date | Event | Published odds | Discriminates |
|---|---|---|---|
| 2026-10-27/28 | FOMC | 16.1% hike, 83.9% hold (CME, 2026-10-21) [S36] | "AI-driven reacceleration" vs rate-pressure paths |
| 2026-12-08/09 | FOMC with SEP [S16] | none published | Tests the 4.1% 2027 median [S12] |
| Feb 2027 | Mag 7 vs 493 EPS [S34] | none published | Breadth of the earnings leg |

### Signposts

| Indicator | Threshold | By when | Effect |
|---|---|---|---|
| FactSet CY2027 growth estimate [S6] | <10% | mid-2027 | kills "AI-driven reacceleration" (35%) |
| Ex-Micron/NVIDIA growth gap [S34] | <5pp | Q4 2026 print | confirms breadth |
| Sahm indicator [S17] | ≥0.30pp | 2027 | confirms "Hard landing recession" (10%) |
| Hyperscaler capex vs $800bn 2026 track [S31] | guidance cut | H1 2027 | feeds "Bear market and drawdown" (20%) |

The Cleveland Fed yield-curve model put the probability of a US recession within one year at 11.4% for September 2026 [S41]. The New York Fed Treasury-spread model averages 0.28 for 2026 and 0.15 for 2027 twelve months ahead, published as model estimates rather than official forecasts [S14][S40]. Polymarket quoted an 8% chance for US recession by end of 2026 [S42]. No source in the evidence publishes a probability for a credit event or policy shock before end-2027.

## News and market context

### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability.

| Provider / kind | Source | Published / retrieved | Status / captured contract |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport\_timeout) |

## References

- [S1] Stock Market Valuation - S&P 500 | StreetStats — https://streetstats.finance/valuation/market (tier 3; fetched)
- [S2] S&P 500 — United States — https://fred.stlouisfed.org/series/SP500?drf_series=fred%3ASP500 (tier 1; fetched)
- [S3] S&P 500 Index Price & News - WSJ | SPX — https://www.wsj.com/market-data/quotes/index/SPX/historical-prices (tier 2; search snippet)
- [S4] S&P 500 PE Ratio by Year - Multpl — https://www.multpl.com/s-p-500-pe-ratio/table/by-year (tier 3; fetched)
- [S5] S&P 500 PE Ratio by Month - Multpl — https://www.multpl.com/s-p-500-pe-ratio/table/by-month (tier 3; fetched)
- [S6] FactSet Earnings Insight — https://advantage.factset.com/hubfs/Website/Resources%20Section/Research%20Desk/Earnings%20Insight/EarningsInsight_100926.pdf (tier 3; fetched)
- [S7] S&P 500 Earnings Season Update: October 16, 2026 — https://insight.factset.com/sp-500-earnings-season-update-october-16-2026 (tier 3; fetched)
- [S8] FactSet Earnings Insight — https://www.factset.com/earningsinsight (tier 3; fetched)
- [S9] The 'Great Narrowing': S&P 500 concentration — https://www.rbcwealthmanagement.com/en-us/insights/the-great-narrowing-sp-500-concentration (tier 3; fetched)
- [S10] S&P 500 (year-over-year % change) — United States — https://fred.stlouisfed.org/series/SP500?drf_series=fred%3ASP500%23yoy (tier 1; fetched)
- [S11] Federal Funds Target Range - Upper Limit — United States — https://fred.stlouisfed.org/series/DFEDTARU?drf_series=fred%3ADFEDTARU (tier 1; fetched)
- [S12] FOMC Statement: September 2026 — https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/fixed-income/fixed-income-perspectives/fomc-statement-september-2026/ (tier 3; fetched)
- [S13] Smoothed U.S. Recession Probabilities — https://fred.stlouisfed.org/series/RECPROUSM156N?drf_series=fred%3ARECPROUSM156N (tier 1; fetched)
- [S14] [PDF] Probability of US Recession Predicted by Treasury Spread — https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf (tier 3; fetched)
- [S15] S&P 500 Historical Prices by Year - Multpl — https://www.multpl.com/s-p-500-historical-prices/table/by-year (tier 3; search snippet)
- [S16] The Fed - Meeting calendars and information - Federal Reserve — https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm (tier 1; search snippet)
- [S17] Real-time Sahm Rule Recession Indicator — United States — https://fred.stlouisfed.org/series/SAHMREALTIME?drf_series=fred%3ASAHMREALTIME (tier 1; fetched)
- [S18] 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States — https://fred.stlouisfed.org/series/T10Y3M?drf_series=fred%3AT10Y3M (tier 1; fetched)
- [S19] S&P 500 Historical Data (SPX) - Investing.com — https://www.investing.com/indices/us-spx-500-historical-data (tier 3; search snippet)
- [S20] S&P 500 PE Ratio : 25.943 (As of 2026-10-22) NEW - GuruFocus — https://www.gurufocus.com/economic_indicators/57/sp-500-pe-ratio (tier 3; search snippet)
- [S21] S&P 500 Index: current P/E Ratio - World PE Ratio — https://worldperatio.com/index/sp-500/ (tier 3; search snippet)
- [S22] S&P 500 Total Returns by Year Since 1926 — https://www.slickcharts.com/sp500/returns (tier 3; fetched)
- [S23] S&P 500 Historical Annual Returns (1927-2026) — https://www.macrotrends.net/2526/sp-500-historical-annual-returns (tier 3; search snippet)
- [S24] S&P 500 (^GSPC) Charts, Data & News - Yahoo Finance — https://finance.yahoo.com/quote/%5EGSPC/ (tier 3; search snippet)
- [S25] Central bank policy rates - United States - Monthly - End of period — https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US?drf_series=bis%3AWS_CBPOL%2FM.US (tier 1; fetched)
- [S26] Average Hourly Earnings of All Employees, Total Private — United States — https://fred.stlouisfed.org/series/CES0500000003?drf_series=fred%3ACES0500000003 (tier 1; fetched)
- [S27] Monthly Treasury Statement: Customs Duties (current month) — United States — https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/?drf_series=usgov%3Atreasury%2Fmts_customs_duties (tier 1; fetched)
- [S28] Federal Funds Effective Rate — United States — https://fred.stlouisfed.org/series/FEDFUNDS?drf_series=fred%3AFEDFUNDS (tier 1; fetched)
- [S29] Average Hourly Earnings of All Employees, Total Private (year-over-year % change) — United States — https://fred.stlouisfed.org/series/CES0500000003?drf_series=fred%3ACES0500000003%23yoy (tier 1; fetched)
- [S30] Federal Funds Effective Rate — United States — https://fred.stlouisfed.org/series/DFF?drf_series=fred%3ADFF (tier 1; fetched)
- [S31] Can AI Investment Drive S&P 500 Earnings Even Higher? | Goldman Sachs — https://www.goldmansachs.com/insights/articles/can-ai-investment-drive-s-and-p-500-earnings-even-higher (tier 3; fetched)
- [S32] Earnings Up, Rates Up: Who Wins the Tug-of-War? Stock Talk Update Aug ... — https://oakharvestfg.com/stock-talk/earnings-up-rates-up-who-wins-the-tug-of-war-stock-talk-update-aug-21-2026/ (tier 3; search snippet)
- [S33] Jensen Claims $600B in Annual CAPEX Spend - Wait, What? — https://thecuberesearch.com/jensen-claims-600b-in-annual-capex-spend-wait-what/ (tier 3; search snippet)
- [S34] Are “Magnificent 7” Companies Still Top Contributors to S&P 500 Earnings Growth for Q3? — https://insight.factset.com/are-magnificent-7-companies-still-top-contributors-to-sp-500-earnings-growth-for-q3 (tier 3; fetched)
- [S35] S&P 500 Reporting Highest Net Profit Margin in More Than 15 Years — https://insight.factset.com/sp-500-reporting-highest-net-profit-margin-in-more-than-15-years-2 (tier 3; search snippet)
- [S36] FedWatch - CME Group — https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html (tier 3; fetched)
- [S37] Fed Funds Rate Forecast 2026-2031 | StreetStats — https://streetstats.finance/rates/fedfunds (tier 3; fetched)
- [S38] 30 Day Federal Funds Futures Quotes - CME Group — https://www.cmegroup.com/markets/interest-rates/stirs/30-day-federal-fund.quotes.html (tier 3; fetched)
- [S39] The Fed - September 16, 2026: FOMC Projections materials, accessible version — https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm (tier 1; fetched)
- [S40] The Yield Curve as a Leading Indicator - FEDERAL RESERVE BANK of NEW YORK — https://www.newyorkfed.org/research/capital_markets/ycfaq (tier 3; fetched)
- [S41] Yield Curve and Predicted GDP Growth — https://www.clevelandfed.org/indicators-and-data/yield-curve-and-predicted-gdp-growth (tier 3; search snippet)
- [S42] US recession by end of 2026? Trading Odds & Predictions | Polymarket — https://polymarket.com/event/us-recession-by-end-of-2026 (tier 3; search snippet)
- [S43] About The Wall Street Journal Economic Forecasting Survey - WSJ — https://www.wsj.com/economy/economic-forecasting-survey-archive-11617814998 (tier 2; search snippet)
- [S44] S&P 500 Top 10 Index | S&P Dow Jones Indices — https://www.spglobal.com/spdji/en/indices/equity/sp-500-top-10-index/ (tier 3; fetched)
- [S45] S&P 500 Companies by Weight — https://www.slickcharts.com/sp500 (tier 3; fetched)
- [S46] Rising S&P 500 concentration was rational - but mega-cap… — https://www.guinnessgi.com/insights/articles/rising-sp-500-concentration-was-rational-mega-cap-earnings-dominance-now-fading (tier 3; search snippet)
- [S47] Counterpoint Global Insights — https://www.morganstanley.com/im/publication/insights/articles/article_drawdownsandrecoveries.pdf (tier 3; fetched)
- [S48] S&P 500 Top 10 Stocks Account for 40% of Index - LinkedIn — https://www.linkedin.com/posts/ben-carlson-cfa-97661244_the-top-10-stocks-in-the-sp-500-now-make-activity-7503859931717046272-TJDC (tier 3; search snippet)
- [S49] S&P 500 Earnings Growth Expected 15% in 2026 - LinkedIn — https://www.linkedin.com/posts/factset_sp-500-cy-2026-earnings-preview-analysts-activity-7407875146713034752-QfUK (tier 3; search snippet)
- [S50] Wage Growth Tracker - Federal Reserve Bank of Atlanta — https://www.atlantafed.org/research-and-data/data/wage-growth-tracker (tier 3; fetched)
- [S51] Effective Tariff Rates and Revenues (Updated October 14, 2026) | Penn Wharton Budget Model — https://budgetmodel.wharton.upenn.edu/p/2026-10-14-effective-tariff-rates-and-revenues-updated-october-14-2026/ (tier 1; fetched)
- [S52] Tracking the Economic Effects of Tariffs | The Budget Lab — https://budgetlab.yale.edu/research/tracking-economic-effects-tariffs (tier 1; fetched)
- [S53] U.S. Import and Export Price Indexes summary - Bureau of Labor Statistics — https://www.bls.gov/news.release/ximpim.nr0.htm (tier 1; search snippet)
- [S54] Import/Export Price Indexes - Bureau of Labor Statistics — https://www.bls.gov/mxp/ (tier 1; search snippet)
- [S55] S&P 500 Bear Markets — https://winthropwealth.com/wp-content/uploads/2023/01/SP-500-Bear-Markets-CQ.pdf (tier 3; fetched)
- [S56] [PDF] S&P 500 Total Return Index History Drawdowns of Greater Than 5 ... — https://www.washoecounty.gov/humanresources/board_committees/deferred_compensation/2020/08-12-2020%20Item%209%20S%20and%20P%20500%20Index%20Drawdown%20Chart.pdf (tier 1; fetched)
- [S57] US Economic Survey - SIFMA — https://www.sifma.org/research/economics/us-economic-survey (tier 3; search snippet)
- [S58] 2027 economic outlook: Resilience to continue, but the risks are building — https://www.oxfordeconomics.com/resource/2027-economic-outlook-resilience-to-continue-but-the-risks-are-building/ (tier 3; search snippet)
- [S59] US Recession Probability (Monthly, I:USRPEM) - United States - YCharts — https://ycharts.com/indicators/us_recession_probability (tier 3; search snippet)
- [S60] What Is the Probability of a Recession? | J.P. Morgan Research — https://www.jpmorgan.com/insights/global-research/economy/recession-probability (tier 3; search snippet)
- [S61] High Yield Corporate Bond Spread Today: 3.33% (Oct 2026) — https://www.macroradar.io/high-yield-spread (tier 3; search snippet)

## Visual Annex

### Event Timeline

![Event Timeline](demos/sp500-2027/research-charts/timeline.png)

[Interactive version](demos/sp500-2027/research-charts/timeline.html)

_Dated key events driving the forecast, most recent window._

### Observed and Published Forecast Trajectories

![Observed and Published Forecast Trajectories](demos/sp500-2027/research-charts/metric_trajectories.png)

[Interactive version](demos/sp500-2027/research-charts/metric_trajectories.html)

_Three or more sourced points on one definition; x-axis is period end, not publication date._
