# Forecast the US 10-year Treasury yield (constant maturity, percent) as of December 31, 2027. Establish the baseline: the current yield as of late October…

## Executive Summary

This report forecasts the FRED DGS10 fixing — the Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity — at the last trading day's official close of 2027: settlement is the end-state value on 31 December 2027, not an ever-touch. The anchor is high and the curve positively sloped. DGS10 printed 5.13% on 2026-10-21, against a September 2026 monthly mean of 4.989% — the top of the series' five-year monthly range of 1.37% (2021-09) to 4.989% (2026-09) [S1] — with 2s10s at 0.338% (2026-09) [S2] and 10-year minus 3-month at 0.896% (2026-09) [S3].

The central thesis: compensation, not inflation expectations, keeps the 10-year near 5% through 2027. Market inflation pricing is near target — the 10-year breakeven is 2.351% (2026-09) [S4] and the 5y5y forward 2.34% (2026-09) [S5] — while the term premium on a 10-year zero-coupon bond is 0.96% (2026-09) [S6], at the top of its five-year range, against a fitted 10-year zero-coupon yield of 5.003% (2026-09) [S7]. With the policy rate at 3.875% per year at end-September 2026 [S8], after the 12–0 hike of September 16, 2026 [S9], and funds futures implying an average effective rate near 4.2% in February 2027 rising to about 4.56% by November 2027 (a derived, unconfirmed reading) [S10], the expected-rate component looks roughly flat; the swing factor is the term premium, pressured by CBO's baseline projection of a $1.9 trillion fiscal-year 2026 deficit (5.8 percent of GDP), averaging $2.4 trillion a year over 2027–2036 [S11], while consumer one-year inflation expectations sit at 4.6% (2026-09) [S12]. Foreign official demand is the evidence gap: this run holds no TIC holdings figures for Japan or China.

The canonical frame, most-likely path first:

- Higher-for-longer plateau — 40% — sticky inflation holds the funds rate near 4% and the term premium near 1%; DGS10 settles between 4.75% and 5.50%, centered around 5.0–5.3%.
- Disinflation glide — 25% — core inflation returns toward 2%, the Fed cuts toward its long-run dot; DGS10 settles between 4.00% and 4.75%.
- Bond bear steepening — 20% — deficit and issuance pressure push the term premium above 1.5% and DGS10 above 5.50%.
- Recession flight to quality — 15% — a 2027 recession triggers rapid cuts and drives DGS10 below 4.00%.

Combined downside weight (40%) exactly matches the plateau, so the distribution is wide; the conditional historical base rate is thin because the stored DGS10 monthly window begins 2006-11 [S1], which is why the frame leans on a roughly one-percentage-point 14-month band. The recession tail is dormant today — the real-time Sahm indicator reads 0 percentage points (2026-09) [S13] — but the one-recession-in-6.5-years prior sustains it.

Leading indicators: the ACM term premium sustained above 1.5% would confirm Bond bear steepening; a 5y5y forward sliding toward 2.0% would signal Disinflation glide; a Sahm reading of 0.50 percentage points or a rising NY Fed recession probit would trigger Recession flight to quality; FOMC dots and QT guidance, quarterly refunding coupon sizes, and Japan and China TIC holdings will discriminate the plateau from the rest.

## Baseline: current yield, curve shape and 2024-2026 range

The forecast resolves on FRED series DGS10, the Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis (percent, not seasonally adjusted, United States), published daily from the Treasury H.15 curve [S1]. Its latest stored daily value is 5.13% on 2026-10-21; the September 2026 monthly mean is 4.989%, up +0.869 pp from 4.12% in September 2025, and the partial-month October 2026 mean runs at 5.202% [S1]. The spot therefore sits above 5%, at the top of the series' five-year monthly range of 1.37% (2021-09) to 4.989% (2026-09) [S1].

The three-year range, on monthly means: 2024 traded 3.72% (September low) to 4.54% (April high), closing at 4.391% in December; 2025 ran 4.062% (October) to 4.629% (January), closing at 4.143% [S1]. In 2026 the monthly mean climbed from 4.213% (January) through 4.6% (July) to 4.989% (September) [S1]. On daily data, Macrotrends' aggregation of the series shows a 52-week range of 3.97% (2025-10-22) to 5.31% (2026-10-05), with 5.29% on 2026-09-30 [S14]; undated CNBC intraday quotes near 4.95–5.00% illustrate volatility around the mark but are not the fixing [S15]. Exact calendar-year daily minima and maxima for 2024 and 2025 are not established in the evidence.

Curve shape: the 2s10s spread (T10Y2Y) stands at 0.31% daily (2026-10-23) and 0.338% monthly (2026-09), down 0.214 pp year over year — inverted from July 2022 (−0.14%) through September 2024, first positive in October 2024 (0.123%), peaking at 0.676% in January 2026 and flattening since [S2]. The 3M10Y spread (T10Y3M) is 0.78% daily (2026-10-23) and 0.896% monthly (2026-09), up +0.841 pp year over year from 0.055% (2025-09), after a −1.73% trough (2023-05) and a first positive print in December 2024 [S3]. Derived from these fixings (5.13 − 0.31 and 5.13 − 0.78; my arithmetic), the 2-year trades near 4.82% and the 3-month near 4.35%, a front-end hump consistent with near-term easing priced before a higher back end [S1][S2][S3].

### Regime dashboard

| Block | Series | Latest (period) | 3m vs 12m momentum | Direction | Shift flag |
|---|---|---|---|---|---|
| Rates | DGS10 | 5.13% daily (2026-10-21); 4.989% monthly (2026-09) [S1] | Jul 4.6% → Sep 4.989% monthly means; +0.869 pp YoY [S1] | Rising | Yes: monthly mean at 5-year high [S1] |
| Curve | T10Y2Y | 0.31% daily (2026-10-23); 0.338% monthly (2026-09) [S2] | −0.214 pp YoY; below Jan-2026 peak 0.676% [S2] | Flattening | No: positive since Oct-2024 [S2] |
| Curve | T10Y3M | 0.78% daily (2026-10-23); 0.896% monthly (2026-09) [S3] | +0.841 pp YoY [S3] | Steepening | Yes: from −1.2% (2024-09) [S3] |
| Policy | BIS policy rate, US | 3.875% per year (2026-09, end of period) [S8] | −0.25 pp YoY; September rise from 3.625% [S8] | Tightening | Yes: 2026's first move is a hike [S8] |
| Compensation | THREEFYTP10 | 0.96% monthly (2026-09); 0.986% daily (2026-10-16) [S6] | +0.499 pp YoY [S6] | Rising | Yes: at 5-year range top (−0.193% to 0.96%) [S6] |
| Inflation comp. | T10YIE | 2.34% daily (2026-10-23); 2.351% monthly (2026-09) [S4] | −0.02 pp YoY [S4] | Flat | No [S4] |
| Real yield | DFII10 | 2.64% daily (2026-10-22); 2.638% monthly (2026-09) [S16] | At 5-year range top (1.825%–2.638%) [S16] | Rising | Yes: 5-year high [S16] |
| Balance sheet | WALCL | 6,753,604 millions USD (2026-10-21) [S17] | Vs 6,743,031 (2026-09-30): roughly flat [S17] | Flat-to-growing | No: ample-reserves regime [S17] |

The 2026 climb above 5% is a break from the 2024–2025 3.7–4.6% band, driven by real yields and term premium rather than breakevens [S4][S6][S16]; near-5% starting levels are rare in the modern sample, which thins the base-rate evidence for large moves from here [S1].

### Figure: Market Yield on U.S. Treasury Securities at Ten-Year Constant Maturity, Quoted on an Investment Basis

![Market Yield on U.S. Treasury Securities at Ten-Year Constant Maturity, Quoted on an Investment Basis](demos/ust10y-2027/research-charts/data_fred_dgs10_53b12b38e251b1e1.png)

*Official series from FRED; latest observation marked: up from a year earlier, near the top of the charted range; hollow marker = partial period. [S1]*

### Figure: Ten-Year Treasury Constant Maturity Minus Two-Year Treasury Constant Maturity — United States

![Ten-Year Treasury Constant Maturity Minus Two-Year Treasury Constant Maturity — United States](demos/ust10y-2027/research-charts/data_fred_t10y2y_6b8edf335bbec73a.png)

*Official series from FRED; latest observation marked: down from a year earlier; hollow marker = partial period. [S2]*

## Official Data Baseline

| Series | Latest historical value | Period | Yearly change | Status | Publisher projection | Source |
|---|---|---|---|---|---|---|
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis | 4.989% | 2026-09 | +0.869 pp | stored observation | — | [S1] |
| 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States | 0.338% | 2026-09 | -0.214 pp | stored observation | — | [S2] |
| 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States | 0.896% | 2026-09 | +0.841 pp | stored observation | — | [S3] |
| Central bank policy rates - United States - Monthly - End of period | 3.875% per year | 2026-09 | -0.25 pp | stored observation | — | [S8] |
| Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States | 6753604 Millions of U.S. Dollars | 2026-10-21 | — | stored observation | — | [S17] |
| 10-Year Breakeven Inflation Rate — United States | 2.351% | 2026-09 | -0.02 pp | stored observation | — | [S4] |
| 5-Year, 5-Year Forward Inflation Expectation Rate — United States | 2.34% | 2026-09 | +0.022 pp | stored observation | — | [S5] |
| University of Michigan: Inflation Expectation | 4.6% | 2026-09 | -0.1 pp | stored observation | — | [S12] |
| Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) — United States | -26900347102.02 U.S. dollars (≈ -26.9 billion U.S. dollars) | 2026-09 | -224849977464.18 (-113.589%) | stored observation | — | [S18] |
| Term Premium on a 10 Year Zero Coupon Bond — United States | 0.96% | 2026-09 | +0.499 pp | stored observation | — | [S6] |
| Fitted Yield on a 10 Year Zero Coupon Bond — United States | 5.003% | 2026-09 | +0.827 pp | stored observation | — | [S7] |
| Real-time Sahm Rule Recession Indicator — United States | 0 Percentage Points | 2026-09 | -0.23 (-100%) | stored observation | — | [S13] |
| Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed | 2.638% | 2026-09 | — | stored observation | — | [S16] |

## Settlement contract and market-implied path

### Settlement definition

| Field | Definition |
|---|---|
| Instrument | FRED DGS10: Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, investment basis, percent, NSA, United States [S1] |
| Publisher / source | Federal Reserve Bank of St. Louis, from the U.S. Treasury H.15 daily curve [S1] |
| Fixing | One level per U.S. business day, compiled from end-of-day quotes (3:30 p.m. Eastern time basis); intraday quotes are not the reference [S1][S15] |
| Statistic | The daily level on the last trading day of December 2027 (2027-12-31), published in early January 2028; "at end-2027" is this last official close, not the December monthly mean [S1] |
| Adjustment | None; a fitted constant-maturity yield, not a specific on-the-run bond [S1] |
| Fallback | If 2027-12-31 is not a Treasury business day, the last prior business day's daily level; monthly means used in base-rate history are a different statistic and must not be conflated with settlement [S1] |
| Anchor | 5.13% (2026-10-21) [S1] |

### Market-implied path versus the current level

CME 30-Day Federal Funds futures closed 23 October 2026 at 95.82 (February 2027, ZQG7), 95.53 (June 2027), 95.455 (September 2027) and 95.44 (November 2027, ZQX7) [S10]. Derived as 100 − price, without a meeting-day adjustment, these imply an average effective funds rate near 4.18% in February 2027, troughing around 4.2% in February–March and rising to about 4.56% by November 2027 — a derived, unconfirmed reading; the December 2027 contract (ZQZ7) is listed but its price was not captured [S10]. FedWatch's live board shows risk-neutral probabilities of 0.0%, 90.6% and 9.4% for an upcoming meeting whose date is not identified in the data [S19]. Schwab reports the target range at 3.50%–3.75% with futures pricing a 78.2% probability of no change through December 2026 [S20], in tension with the BIS end-September 2026 midpoint of 3.875% [S8]; the evidence does not resolve the difference. Against the market, the September 2026 SEP median funds-rate projection is 4.25% at end-2026, 4.25% at end-2027, 3.75% at end-2029 and 3.0% in the longer run [S21] (secondary readings of a 4.1% end-2027 median [S22][S23] conflict; the official document governs [S21]). As a decomposition, the fitted 10-year zero-coupon yield of 5.003% (2026-09) less the 0.96% term premium leaves roughly 4 pp as the expected-rate component (derived from the two series) [S6][S7] — so a mid-4s funds path with a ~1% term premium is arithmetically consistent with a 10-year near its current 5.13%; this is a derived illustration, not a published forecast.

### Distribution at the horizon

No exchange-settled, options-implied distribution of the end-2027 10-year yield was located; funds and SOFR futures price the short-rate path only [S19][S10]. The Cleveland Fed reports a probability of recession in one year of 11.4 percent for September 2026, down from 13.6 percent in July [S24]; the New York Fed publishes its Treasury-spread recession probability monthly, within the first two weeks of each month, with the current reading unconfirmed in fetched pages [S25].

| Method | Type | Basis | End-2027 statement |
|---|---|---|---|
| Options on 10-year futures | Market-implied | None located [S19][S10] | Not published |
| Fed funds futures | Market-implied (closes 23 Oct 2026) | CME ZQ contracts [S10] | Effective funds ≈4.56% Nov 2027 (derived, unconfirmed); Dec 2027 price not captured |
| DGS10 monthly, non-overlapping 14-month windows | Empirical: 2006-11→2026-09, h=14m, n=16; spans QE-era lows and the 2022–23 tightening | [S1] | \|Δ\|>0.5 pp in 13 of 16 (~81%); >1.0 pp in 3 of 16 (~19%) |
| Same, starts in 4.5%–5.5% band | Empirical: n=4 (2006-11, 2023-10, 2024-04, 2025-01) | [S1] | >0.5 pp: 1 of 4 (the 2006-11 start, a fall of −0.86 pp); >1.0 pp: 0 of 4 |
| CBO, February 2026 baseline | Cited forecaster (official projection) | [S11] | 10-year note rate "rises gradually through 2027," relatively stable thereafter |

The conditional empirical row fits best: settlement starts at 5.13%, inside the 4.5–5.5% conditioning band, and it says large 14-month moves from ~5% starts are the exception, with the one observed exceedance pointing down. The rows differ because the unconditional window is dominated by starts far below 5%, the futures row prices a policy rate rather than the 10-year, and CBO's is a projection, not a distribution; the counts are calculations on the stored series [S1]. Against this frame: **Higher-for-longer plateau — 40%** settles between 4.75% and 5.50%, agreeing with a mid-4s funds path plus ~1% term premium, and is falsified by a term premium sustained above ~1.5% with the funds rate near 4% [S6]. **Bond bear steepening — 20%** settles above 5.50%; term-premium daily prints up to 1.0589% (2026-10-13) show the direction but not the magnitude [S26][S6], and its falsifier is Treasury holding coupon sizes — as committed "for at least the next several quarters" in August 2026 — with deficits absorbed in bills [S27]. **Disinflation glide — 25%** settles between 4.00% and 4.75%, requiring core PCE toward the SEP's 2.5% 2027 median [S21]; it is falsified by sticky household expectations (Michigan 4.6%, September 2026 [S12]). **Recession flight to quality — 15%** settles below 4.00%; the real-time Sahm indicator at 0.00 percentage points (September 2026) currently argues against it, and its falsifier is a further labor-market improvement from an already non-triggering level [S13].

### Catalyst calendar

| Date | Event | Published implied move | Discriminates |
|---|---|---|---|
| 4 Nov 2026 (unconfirmed) | Quarterly refunding statement [S27] | None yet | Coupon-size guidance: Bond bear steepening vs Higher-for-longer plateau |
| Monthly, first two weeks | NY Fed recession-probability update [S25] | n/a | Recession flight to quality |
| Monthly | Monthly Treasury Statement [S18] | n/a | Deficit tracking vs CBO's $1.9 trillion (5.8% of GDP) FY2026 [S11]: Bond bear steepening |
| December 2026 FOMC (date not in evidence; September meeting was 15–16 Sep) | New SEP [S28] | FedWatch near-meeting odds 90.6%/9.4% for an unidentified meeting [S19] | Disinflation glide vs Higher-for-longer plateau |

### Figure: Ten-Year Treasury Constant Maturity Minus Three-Month Treasury Constant Maturity — United States

![Ten-Year Treasury Constant Maturity Minus Three-Month Treasury Constant Maturity — United States](demos/ust10y-2027/research-charts/data_fred_t10y3m_4aefaf7432bbac9a.png)

*Official series from FRED; latest observation marked: up from a year earlier; hollow marker = partial period. [S3]*

## Federal Reserve policy path and balance sheet

### Stance
On 16 September 2026 the FOMC raised the target range for the federal funds rate by ¼ percentage point to 3-3/4 to 4 percent, by a 12–0 vote; the statement said "Inflation remains elevated" and "Today's policy action will support a timelier return to the Committee's 2 percent goal" [S9]. The BIS series places the US policy rate (range midpoint, end of period) at 3.875% per year for 2026-09, versus 4.125% per year for 2025-09 — a net 25 basis points of easing year over year even after the hike — within a five-year range of 0.125% (2021-09) to 5.375% (2023-07) [S8].

### Official path and market pricing
The September 2026 SEP (18 participants; one filed no 2028–29 projections) shows federal funds rate projections of 4.25% at end-2026, end-2027 and end-2028, 3.75% at end-2029 and 3.0% in the longer run, published as year-end midpoints of the appropriate target range [S21][S28]. Snippet summaries read the end-2026 and end-2027 medians at 4.1% — one further 25bp step, then a hold (J.P. Morgan Asset Management; St. Louis Fed) [S22][S23] — most plausibly the same path quoted on a different convention; where JPM's 3.2% longer-run reading [S22] conflicts with the official print, the official 3.0% governs [S21]. Supporting medians: core PCE inflation 3.4% (2026), 2.5% (2027), 2.2% (2028), 2.0% (2029), central tendency 2.3–2.6% for 2027; unemployment 4.1% in each of 2026–29; real GDP growth 2.3%, 2.4%, 2.2%, 2.1% (Q4/Q4) [S21][S28].

| Decision point | Official projection (SEP, 16 Sep 2026) | Market-implied, risk-neutral (retrieved 23 Oct 2026) | Evidence-based lean |
| --- | --- | --- | --- |
| End-2026 | 4.25% funds-rate projection [S21] | CME FedWatch displays 90.6% and 9.4% across two buckets for an unidentified upcoming meeting, hike/hold/cut labels unreadable [S19]; an undated Schwab commentary reports futures pricing a 78.2% probability of no change through December 2026, though its quoted 3.50–3.75% range predates the September hike [S20][S9] | One further 25bp step if core PCE tracks the 3.4% 2026 median [S21] |
| End-2027 | 4.25% [S21] | CME 30-day fed funds futures imply an average effective funds rate of about 4.18% for February 2027 rising to about 4.56% for November 2027 (100 minus price; no day-count adjustment; unconfirmed) [S10] | Hold near 4%; the wedge between the strip and the SEP path is unresolved — priced hikes, an effective-rate/convexity wedge, or thin back-contract liquidity |

### Balance sheet: QT over, reserve management in place
QT ran from 1 June 2022 to 31 October 2025 and reduced securities holdings by $2.2 trillion [S29]. On 10 December 2025 the FOMC judged reserves ample and announced reserve-management purchases of shorter-term Treasury securities, sized to trend liability growth plus seasonal fluctuations [S29]. Total assets were $6.7 trillion, 21% of nominal GDP, on 25 March 2026, up $49 billion over two quarters, with securities held outright up $71 billion [S29]; the weekly series prints 6,753,604 millions of US dollars on 2026-10-21 [S17]. The balance sheet is flat-to-growing, with purchases concentrated at the short end; Treasury's August 2026 refunding statement says current auction sizes leave it "well positioned to address potential changes to the fiscal outlook and to the size and composition of the SOMA portfolio" [S27].

### Constraints and scenario signatures
The reaction function is constrained by inflation, not labour: core PCE at 3.4% for 2026 sits 1.4pp above goal while unemployment (4.1%) is just under its 4.2% longer-run median [S21]. Higher-for-longer plateau — 40% — is this path delivered: funds near 4%, premium near 1%; its falsifier is core PCE prints near 2% pulling the dots down. Disinflation glide — 25% — requires the 2.5% 2027 core median to materialise, opening cuts toward the 3.0% longer run [S21]. Recession flight to quality — 15% — implies rapid cuts from the 3.875% midpoint [S8]; the real-time Sahm indicator at 0 percentage points for 2026-09 currently blocks that trigger [S13]. Bond bear steepening — 20% — needs no funds-path change: it works through the term premium with the Fed on hold.

### Figure: Central bank policy rates - United States - Monthly - End of period

![Central bank policy rates - United States - Monthly - End of period](demos/ust10y-2027/research-charts/data_bis_ws_cbpol_m_us_eae44f753af36114.png)

*Official series from the BIS; latest observation marked: down from a year earlier. [S8]*

### Figure: Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States

![Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States](demos/ust10y-2027/research-charts/data_fred_walcl_8bc7255ad0f83329.png)

*Official series from FRED; latest observation marked: up from a year earlier, near the bottom of the charted range. [S17]*

## Inflation expectations and term premium

### Decomposition
The fitted 10-year zero-coupon yield (THREEFY10, United States) was 5.003% for 2026-09 (latest daily 5.107% on 2026-10-16), up 0.827pp from 4.177% a year earlier [S7]. The Kim-Wright term premium on the same bond (THREEFYTP10) was 0.96% for 2026-09 (latest daily 0.986% on 2026-10-16; partial October mean 1.059% per the series page), up 0.499pp from 0.462% and at the top of its five-year range of −0.193% to 0.96% [S6]. The difference of the two stored values — a derived, not published, figure — is an expected-short-rate component of about 4.0pp, so roughly 0.5pp of the year's 0.827pp rise, about three-fifths, was compensation. A second split: the 2026-09 monthly means of the 10-year TIPS yield (2.638%) [S16] and the 10-year breakeven (2.351%) [S4] sum to 4.989%, the DGS10 monthly mean [S1] — about 2.6pp real compensation over 2.35pp inflation compensation.

| Component | Series (FRED) | 2026-09 monthly mean | Latest daily | Year over year |
| --- | --- | --- | --- | --- |
| Fitted 10-year zero-coupon yield | THREEFY10 [S7] | 5.003% | 5.107% (2026-10-16) | +0.827pp |
| Term premium (Kim-Wright) | THREEFYTP10 [S6] | 0.96% | 0.986% (2026-10-16) | +0.499pp |
| Expected-rate component | derived [S6][S7] | ≈4.0pp (5.003 − 0.96) | — | ≈+0.3pp, derived |
| 10-year breakeven | T10YIE [S4] | 2.351% | 2.34% (2026-10-23) | −0.02pp |
| 5y5y forward inflation | T5YIFR [S5] | 2.34% | 2.2% (2026-10-23) | +0.022pp |
| 10-year TIPS real yield | DFII10 [S16] | 2.638% | 2.64% (2026-10-22) | not stored |
| Michigan 1-year expectation | MICH [S12] | 4.6% | — | −0.1pp |

### Expectations anchored; the rise is real compensation
Market-based long-horizon expectations sit near target: the 10-year breakeven at 2.351% (2026-09) versus 2.371% a year earlier [S4]; the 5y5y forward at 2.34% versus 2.317%, inside a five-year range of 2.05%–2.46% [S5]. Household surveys diverge — Michigan's 1-year median at 4.6% (2026-09), within a five-year range of 2.6%–6.6% [S12] — a definitional gap (1-year household median versus 10-year market compensation), not a data conflict. The 2026 rise in the nominal yield is real, not inflationary: the TIPS yield climbed from its five-year low of 1.825% (2026-02) to 2.638% (2026-09) [S16] while the breakeven edged down [S4].

### Which term premium?
The level is model-dependent. Kim-Wright prints about 1% [S6]. The NY Fed's ACM figure is unconfirmed: FRED reports the ACMTP10 series does not exist, while a mirror of the NY Fed series (MacroMicro) shows 0.72–0.73% on 2026-10-21 [S30] and a secondary site cites 0.82% [S31]. The wedge plausibly reflects different factor models, vintages and monthly-versus-daily quoting, and it is decision-relevant: at ACM's ~0.7%, a ~5% ten-year embeds ~4.3pp of expected rates, implying markets price the Fed above its dots; at Kim-Wright's ~1%, compensation is already at the top of the post-GFC distribution — the premium was negative for most of 2016–2021 (trough about −0.614% in July 2020) and last sustained above 1% around 2009–2010 [S6].

### Scenario signatures
Higher-for-longer plateau — 40% — is the current configuration: premium near 1%, breakevens near 2.3%; falsified if the term premium collapses below about 0.5%. Bond bear steepening — 20% — requires the premium above 1.5%, a further ~0.5pp repricing; falsified if the premium stalls near 1% while coupon auction sizes are unchanged [S27]. Disinflation glide — 25% — needs the expected-rate component to fall as core PCE reaches the 2.5% 2027 SEP median [S28]; falsified if the 5y5y forward rises through its 2.46% five-year high [S5]. Recession flight to quality — 15% — takes both components down; the breakeven's 2.11% five-year low (2024-08) marks the flight-to-quality floor [S4].

### Figure: Ten-Year Breakeven Inflation Rate — United States

![Ten-Year Breakeven Inflation Rate — United States](demos/ust10y-2027/research-charts/data_fred_t10yie_047417073b32645e.png)

*Official series from FRED; latest observation marked: down from a year earlier; hollow marker = partial period. [S4]*

### Figure: Five-Year, Five-Year Forward Inflation Expectation Rate — United States

![Five-Year, Five-Year Forward Inflation Expectation Rate — United States](demos/ust10y-2027/research-charts/data_fred_t5yifr_4e1ed899f76d560f.png)

*Official series from FRED; latest observation marked: up from a year earlier, near the top of the charted range; hollow marker = partial period. [S5]*

## Treasury issuance and deficit outlook

### Deficit baseline

CBO's February 2026 baseline projects a federal budget deficit of $1.9 trillion in fiscal year 2026 (5.8 percent of GDP), rising to $3.1 trillion (6.7 percent of GDP) by 2036 [S11]. Deficits average $2.4 trillion per year over 2027–2036 — 6.1 percent of GDP on average, against a 50-year average of 3.8 percent of GDP — with rising net interest costs driving much of the increase; the primary deficit is 2.6 percent of GDP in 2026 and 2.1 percent in 2036, and debt held by the public rises from 101 percent of GDP in 2026 to 120 percent in 2036 [S11]. CBO attributes the deterioration since January 2025 to the 2025 reconciliation act (raising deficits by an estimated $4.7 trillion over 2026–2035), higher tariffs (reducing them by an estimated $3.0 trillion) and immigration-related administrative actions (adding $0.5 trillion) [S11]. The FY2027-specific dollar figure is not printed in the retrieved pages; any ~$2.0 trillion (~6 percent of GDP) reading is an interpolation, not a published number. CBO's own economic assumptions embed a 10-year Treasury note rate that "rises gradually through 2027 and remains relatively stable in later years" [S11]. Observed flows are tracking near this path: the Monthly Treasury Statement shows a September 2026 current-month deficit of -26,900,347,102.02 U.S. dollars against a 197,949,630,362.16 U.S. dollar surplus in September 2025 [S18], and the stored five-year series' largest monthly deficit is -432,307,874,621.48 U.S. dollars in July 2026 [S18].

### Borrowing estimates and auction mix

Treasury announced on August 3, 2026 expected privately-held net marketable borrowing of $628 billion for October–December 2026, assuming an $850 billion end-of-December cash balance [S32]; its July–September 2026 estimate had been $739 billion, $68 billion above the May estimate, after actual April–June 2026 borrowing of $190 billion [S32]. The August 5, 2026 refunding statement "anticipates maintaining nominal coupon and FRN auction sizes for at least the next several quarters," saying current sizes leave Treasury "well positioned to address potential changes to the fiscal outlook and to the size and composition of the SOMA portfolio" [S27]. TIPS sizes are unchanged (August 30-year reopening $8 billion; September 10-year reopening $19 billion; October 5-year new issue $26 billion) [S27], and marginal needs fall on bills: benchmark sizes maintained, shorter-dated bills reduced around September tax receipts, and increases across the bill curve anticipated in October on seasonal outflows [S27]. Buybacks continue (schedule last updated September 9, 2026) but are "not expected to significantly affect privately-held net marketable borrowing" [S32][S33]. Marketable debt outstanding on September 30, 2026 comprised Bills of $7,117,937 million, Notes of $16,277,939 million and Bonds of $5,538,540 million [S34]; bills are therefore roughly 24.6 percent of bills-plus-notes-plus-bonds by derivation (excluding FRNs and TIPS), against Reuters' reported ~22 percent of outstanding marketable debt in mid-2026, with TBAC said to want a different mix [S35]. TBAC's 2024 analysis already put bills near 25 percent of total Treasury debt, above the ~23 percent historical average and the highest on record [S36]; a 22–25 percent band covers the definitional spread.

### Issuance-driven term premium pressure

The FRED term-premium series for the United States (THREEFYTP10, identified with the Kim-Wright 2005 model) stood at 0.96% (2026-09, stored observation), up +0.499 pp from 0.462% a year earlier and at the top of its five-year range of -0.193% to 0.96% [S6]; monthly means climbed from 0.601% (January 2026) through 0.792% (July) to 0.96% (September), with October 2026 partial at 1.059% [S6]. A MacroMicro mirror of the NY Fed's ACM series reports 0.72–0.73% on 2026-10-21, the wedge against the FRED series reflecting model choice [S30]. This repricing coincides with the bill-heavy mix and the deficit path, but no estimate of basis points per $100 billion of coupon supply was retrieved, so the issuance-to-term-premium elasticity is unquantified in this evidence; the linkage rests on timing and on Treasury's own spare-capacity framing [S27][S11].

### Signposts

The issuance channel mainly discriminates the fiscal-pressure branch of the outcome distribution:

| Indicator | Threshold | Period | Scenario it confirms or kills |
| --- | --- | --- | --- |
| Nominal coupon/FRN auction sizes | first announced increase | any quarterly refunding through November 2027 (next statement expected early November 2026; date unconfirmed) [S27] | supports Bond bear steepening — 20% |
| THREEFYTP10 monthly mean | above 1.5% | any month through December 2027 [S6] | confirms Bond bear steepening — 20% |
| Bills share of marketable debt | sustained above the 22–25 percent band [S36][S35] | Monthly Statement of the Public Debt through 2027 [S34] | supports Bond bear steepening — 20% |
| Coupon-size freeze maintained | no increase announced | every quarterly refunding through 2027 [S27] | consistent with Higher-for-longer plateau — 40% |

## Foreign official demand: Japan and China

### What the evidence does and does not show

The evidence base for this run contains no Treasury International Capital (TIC) holdings figures for Japan or China, no Bank of Japan policy-rate or JGB series, and no SAFE reserve-allocation data. The levels and trend of Japanese and Chinese official holdings of US Treasury securities — and any reallocation between them — are therefore unknown here, and BoJ normalization cannot be quantified from the stored policy-rate series, which is US-only (3.875% per year, end-Sep 2026) [S8]. What the evidence does capture is the domestic price signature that weak foreign official demand would leave: the compensation component of the 10-year yield.

### The transmission channel: term premium and real yields

Foreign official demand reaches the 10-year mainly through the term premium. The Kim-Wright term premium on a 10-year zero-coupon bond (THREEFYTP10, US) was 0.96% as the September 2026 monthly mean (stored observation), up +0.499 pp from 0.462% in September 2025, and sits at the top of its 5-year range of −0.193% to 0.96%; the latest daily value was 0.986% on 2026-10-16 [S6]. The rise has been steady rather than episodic — 0.601% (January), 0.792% (July), 0.96% (September), with a partial October mean of 1.059% per FRED's page listing [S26][S6] — the pattern a persistent marginal-buyer problem, as opposed to a one-off shock, would produce. A secondary mirror reports the NY Fed ACM premium at 0.72%–0.73% on 2026-10-21 [S30]; with ACMTP10 no longer retrievable from FRED in this run, the two models bracket compensation at roughly 0.7%–1.1%, so how much of the premium is foreign-demand-driven cannot be resolved.

The repricing is real-yield-heavy: the fitted 10-year zero-coupon yield (THREEFY10) rose from 4.177% (Sep 2025) to 5.003% (Sep 2026) [S7], while the 10-year TIPS yield (DFII10) printed 2.638% for September 2026 and 2.64% daily on 2026-10-22 [S16] against a 10-year breakeven of 2.34% on 2026-10-23 [S4] — compensation, not expected inflation, carried the move.

### Base-rate discipline

A foreign-demand shock would need regime scale to break the range: counting non-overlapping 14-month windows in the stored DGS10 series from 2006-11 gives |change| > 1.0 pp in only 3 of 17 episodes (~18%), and from near-5% starts specifically, 0 of 4 closed windows exceeded ±1.0 pp [S1]. With DGS10 at 5.13% on 2026-10-21 [S1], the base rate argues foreign-demand effects most plausibly operate inside a band rather than as a breakout.

### Scenario signatures and signposts

- Bond bear steepening — 20% names soft foreign demand explicitly; its signature is term premium above 1.5% with DGS10 above 5.50%. The Kim-Wright premium is already at its 5-year high [S6], so the live margin is the roughly 0.5–0.8 pp gap to 1.5%; its falsifier is a premium stalling near 1% with DGS10 below 5.50%.
- Higher-for-longer plateau — 40% matches the current configuration: premium near 1%, DGS10 near 5.1% [S1][S6].
- Disinflation glide — 25% and Recession flight to quality — 15% run through expected rates; foreign official buying would at most cushion them.

Direct signposts — TIC holdings for Japan and China, and BoJ decisions — cannot be dated or thresheld from captured evidence; no source in this run publishes a probability tied to foreign-holdings events.

## Recession probabilities and risk-shift channel

### Where the published trackers stand

The real-time Sahm rule recession indicator stood at 0 percentage points in September 2026, against 0.23 percentage points a year earlier; its five-year range runs from −0.07 (August 2026) to 0.43 (November 2025) percentage points, and after peaking at 0.43 in November 2025 it declined for ten consecutive months through September 2026 [S13]. Curve-based signals point the same way: the 10-year minus 3-month spread averaged 0.896% in September 2026 (latest daily 0.78% on 2026-10-23), a +0.841 pp year-over-year steepening [S3], and 2s10s stands at 0.31% (2026-10-23) [S2]. The New York Fed publishes a monthly probit on the 10Y–3M spread with a twelve-months-ahead window, updated within the first two weeks of each month, and cautions that the estimates are not official forecasts [S25]. The New York Fed's published year-average table put the model's probability of a US recession twelve months ahead at 0.28 percent for 2026 [S37]; a 2027 average of 0.15 that appears in one capture of the same table could not be confirmed [S38]. The Cleveland Fed's yield-curve model put the probability of a recession one year ahead at 11.4 percent for September 2026, down from 12.3 percent in August and 13.6 percent in July [S24]. The gap reflects construction: the New York Fed model keys off a single, now steeply positive spread, while the Cleveland Fed model adds other factors [S24][S25]. The Richmond Fed's weekly Sahm-style (SOS) indicator was updated on October 15, 2026, but its current value was not retrieved [S39]. Officials project no downturn: the September 2026 SEP median unemployment rate is 4.1% in each of 2026–2029 [S28].

### The risk-shift channel: funds path versus term premium

A downturn would hit a market priced for neither. On September 16, 2026 the FOMC raised the target range to 3-3/4 to 4 percent by a 12–0 vote, stating "Inflation remains elevated" [S9], and SEP medians hold the funds rate at 4.25% at end-2026, end-2027 and end-2028 before 3.75% in 2029 [S21]. Compensation is already at a cycle high: the Kim-Wright 10-year term premium averaged 0.96% in September 2026 versus 0.462% a year earlier [S6], with the 10-year breakeven at 2.351% [S4]. Recession flight to quality — 15% — a 2027 recession that triggers rapid cuts and a bull flattening driving DGS10 below 4.00% (prior: a US recession began in roughly 1 of 6.5 years since 1948) — requires the expected-rate component to fall faster than the term premium rises. History gives that asymmetry support: in the stored FRED window the only non-overlapping 14-month move beyond ±0.5 pp from a near-5% start was the 2006-11 decline of −0.86 pp into the GFC, and four overlapping 2007 starts all fell more than 0.5 pp [S1]. The offset is fiscal: CBO projects deficits averaging 6.1% of GDP over 2027–2036 [S11], which could keep the term premium sticky and mute any flight-to-quality rally. Slower growth short of recession shifts weight toward Disinflation glide — 25% rather than Higher-for-longer plateau — 40%. No exchange-published, options-derived probability distribution for the end-2027 DGS10 level was found in the evidence; funds futures imply only the short-rate path [S19][S10].

### Signposts

| Indicator | Threshold | Period | Scenario it moves |
| --- | --- | --- | --- |
| SAHMREALTIME [S13] | sustained rise above the November 2025 peak of 0.43 percentage points | monthly through 2027 | supports Recession flight to quality — 15% |
| T10Y3M [S3] | inversion below 0 from 0.78% (2026-10-23) | daily | supports Recession flight to quality — 15%; argues against Bond bear steepening — 20% |
| Cleveland Fed recession probability [S24] | rise above 11.4 percent | monthly | supports Recession flight to quality — 15% |
| Unemployment vs SEP median [S28] | Q4 2027 above the 4.1% median | quarterly | shifts weight from Higher-for-longer plateau — 40% toward easing outcomes |

## Historical base rates for 14-month yield moves

The settlement is a 14-month move from a high starting point: DGS10 printed 5.13% on 2026-10-21 (latest daily value), against a September 2026 monthly mean of 4.989% — the top of the series' five-year range of 1.37% (2021-09) to 4.989% (2026-09) [S1]. The frequencies below are computed from the stored FRED DGS10 monthly series, whose window begins 2006-11; the 1996–2006 half of the requested 1996–2026 span was not retrievable, so the late-1990s episodes with 5–7% starts go uncounted and the conditional evidence is correspondingly thin [S1].

### Empirical frequencies (non-overlapping 14-month windows)

| Reference class | n | \|Δ\| > 0.5 pp | \|Δ\| > 1.0 pp |
|---|---|---|---|
| Unconditional, 2006-11 to 2026-09 | 16 | 13 of 16 (~81%; Laplace ≈78%) [S1] | 3 of 16 (~19%; Laplace ≈22%) [S1] |
| Start in 4.5–5.5% band | 4 | 1 of 4 (Laplace ≈33%) [S1] | 0 of 4 (Laplace ≈17%) [S1] |
| Start ≥ 4.25% | 3 | 1 of 3 [S1] | 0 of 3 (Laplace 20%) [S1] |
| Post-2023-08 starts | 3 | 0 of 3 [S1] | 0 of 3 [S1] |

These are empirical rows: FRED DGS10 monthly means, h = 14 months, non-overlapping; the window spans the GFC, the QE-era lows and the post-pandemic tightening [S1]. An alternative spacing (17 episodes) gives 12 of 17 and 3 of 17 — materially the same [S1].

Only three unconditional windows breached ±1.0 pp: 2011-07→2012-09 (3.00%→1.72%, −1.28), 2018-06→2019-08 (2.91%→1.63%, −1.28) and 2021-12→2023-02 (1.47%→3.75%, +2.28); the largest 14-month moves in the window were +1.90 pp (2022-01→2023-03) and −1.53 pp (2011-02→2012-04, overlapping windows) — regime shifts, not drift [S1].

Conditioning on near-5% starts lowers the base rate sharply. Only four non-overlapping starts had monthly means in the 4.5–5.5% band (2006-11, 2023-10, 2024-04, 2025-01); one of four exceeded ±0.5 pp, none exceeded ±1.0 pp, and the single exceedance was downward — 4.60% in 2006-11 falling to 3.74% by 2008-01 as the 2007–08 recession began [S1]. Under the broader ≥4.25% cut, 2025-07's 4.392%→4.989% (+0.60 pp) is the only ±0.5 pp outcome [S1]. Overlapping GFC-era starts (2007-01, 2007-03, 2007-06, 2007-08) all fell more than 0.5 pp and two of four more than 1.0 pp (e.g. 2007-01: 4.76%→3.51%, −1.25), but are not independent observations [S1]. No near-5% start in the stored window produced an upward move beyond 1.0 pp [S1].

End-state counting understates intra-horizon volatility: the 2023-10 start ended −0.41 pp but touched −1.08 pp by 2024-09 (3.72%) before retracing, and monthly means smooth daily extremes such as the October 2023 daily peak near 5.0% [S1]. The settlement is a single end-state fixing, so the end-state counts are the decision-relevant ones; ever-touch odds are higher [S1].

Recession conditioning currently argues against the one historical near-5% exceedance path: the real-time Sahm rule indicator was 0 percentage points in September 2026 and has declined for ten consecutive months from a 0.43-percentage-point peak in November 2025, its five-year range running −0.07 to 0.43 percentage points [S13]. The Cleveland Fed's yield-curve model put the probability of recession one year ahead at 11.4 percent for September 2026, down from 12.3 percent in August [S24]. The New York Fed's table is reported to show a 2026 year-average twelve-months-ahead recession probability of 0.28 percent [S37]. No publisher examined here posts a probability for the settlement quantity itself; fed funds futures price only the short-rate path [S19][S10].

These base rates sit behind the frame: the near-5% conditional (1 of 4 beyond ±0.5 pp; 0 of 4 beyond ±1.0 pp) supports the ~1 sigma (~1pp) 14-month band prior in Higher-for-longer plateau — 40%, while the roughly one-in-five unconditional ±1.0 pp rate caps the mass outside it [S1]. The absence of any upward >1.0 pp precedent from near-5% starts tempers Bond bear steepening — 20%; a decline into the 4.00–4.75% band of Disinflation glide — 25% needs roughly a 0.4–1.1 pp move, delivered by 1 of 4 near-5% starts; and the sole near-5% exceedance ran through recession onset, consistent with the Recession flight to quality — 15% prior that a US recession began in roughly 1 of 6.5 years since 1948 [S1].

## Scenarios and probabilities

### Scenario Probability Distribution
- **Higher-for-longer plateau (40% probability):** Sticky inflation keeps the funds rate near 4% and term premium near 1%, holding DGS10 at end-2027 between 4.75% and 5.50%; prior: ~1 sigma (~1pp) 14-month band around a ~5.1% spot.
- **Bond bear steepening (20% probability):** Deficit and issuance pressure plus soft foreign demand push term premium above 1.5% and DGS10 above 5.50% even as the Fed holds or eases little.
- **Disinflation glide (25% probability):** Core inflation returns toward 2%, the Fed cuts toward its long-run dot, and DGS10 settles between 4.00% and 4.75%.
- **Recession flight to quality (15% probability):** A 2027 recession triggers rapid cuts and a bull flattening that drives DGS10 below 4.00%; prior: US recession began in roughly 1 of 6.5 years since 1948.

Settlement is the end-state DGS10 fixing on 31 December 2027, not an ever-touch. The anchor is 5.13% (daily, 2026-10-21; monthly mean 4.989% for 2026-09) [S1], a positively sloped curve (2s10s 0.31% and 3M10Y 0.78%, daily, 2026-10-23) [S2][S3], and a 3.75–4% funds target after the 12–0 hike of September 16, 2026 [S9]. The four bands — below 4.00%, 4.00–4.75%, 4.75–5.50%, above 5.50% — are mutually exclusive and exhaustive.

### Base rates

| Reference class (DGS10 monthly means [S1]) | Counting rule | k/n | Window |
|---|---|---|---|
| All non-overlapping 14-month windows | \|Δ\| > 0.5 pp | 13/16 | 2006-11 to 2026-09 |
| All non-overlapping 14-month windows | \|Δ\| > 1.0 pp | 3/16 | 2006-11 to 2026-09 |
| Starts with monthly mean 4.5–5.5% | \|Δ\| > 0.5 pp | 1/4 | 2006-11 to 2026-09 |
| Starts with monthly mean 4.5–5.5% | \|Δ\| > 1.0 pp | 0/4 | 2006-11 to 2026-09 |

The near-5% conditional class fits the mechanism best: three of four windows ended within ±0.5 pp of start, all four ended lower, and the single exceedance was the 2006-11 start falling −0.86 pp into recession [S1]. The unconditional class is inflated by QE-era low-rate windows; the stored series begins 2006-11, so 1996–2006 near-5% episodes could not be counted.

No market in the evidence prices this settlement: no options-implied end-2027 DGS10 distribution was found, and FedWatch probabilities could not be tied to a 2027 meeting [S19][S10]. Implied rates derived from quoted 2027 fed funds futures are unconfirmed arithmetic on quoted prices [S10]. A matching market would have to settle on the H.15 10-year constant-maturity fixing for 31 December 2027.

### Anchor-to-adjustment bridge

| Scenario | Anchor (near-5% class [S1]) | Adjustment: mechanism and evidence | Why not already in the class | Reads vs frame |
|---|---|---|---|---|
| Higher-for-longer plateau — 40% | 3/4 within ±0.5 pp | Sticky core (SEP median core PCE 3.4% for 2026 [S21]; Michigan 1-year 4.6%, 2026-09 [S12]) holds the 4.25% median dot through 2028 [S21]; term premium at its five-year high of 0.96% (2026-09) [S6] | The post-2023 regime mean-reverted inside ±0.5 pp [S1] | Consistent |
| Bond bear steepening — 20% | 0/4 above ±1.0 pp | CBO projects a $1.9 trillion FY2026 deficit (5.8% of GDP) and 6.1% of GDP on average 2027–2036 [S11]; bills ~22% of marketable debt, per Reuters [S35]; term premium +0.499 pp y/y [S6]; Fed reserve-management buys are short-dated only [S29] | Supply at 101% debt/GDP [S11] has no analogue in the sample | Class leans lower; fiscal momentum offsets |
| Disinflation glide — 25% | 4/4 ended lower, 3 by ≤0.41 pp | SEP medians take core PCE to 2.5% (2027) and 2.2% (2028); longer-run dot 3.0% [S21]; the hike was framed as supporting "a timelier return" to 2% [S9] | Sample declines came without a Fed median at 4.25% turning to cuts | Class leans slightly higher |
| Recession flight to quality — 15% | 1/4 exceeded ±0.5 pp, downward | Real-time Sahm 0.00 pp (2026-09) vs a 0.43 pp November 2025 peak [S13]; rapid cuts bull-flatten the 0.31% 2s10s [S2] | The one exceedance required a credit shock | Consistent with weak current signals |

### Signposts and falsifiers

| Indicator | Threshold / event | Period | Moves |
|---|---|---|---|
| Quarterly refunding statements [S27] | coupon sizes increased | statements through November 2027 | Bond bear steepening up |
| THREEFYTP10 [S6] | monthly mean above 1.5% | December 2027 | Bond bear steepening confirms |
| SEP core PCE median [S21] | at or below 2.0% for 2027 | SEPs December 2026–December 2027 | Disinflation glide up, plateau down |
| Real-time Sahm [S13] | at or above 0.50 pp | any month through 2027 | Recession flight to quality up |

Falsifiers: unchanged coupons with a sub-1% term premium kills Bond bear steepening [S27][S6]; core PCE near 2% during 2027 kills Higher-for-longer plateau [S21]; core PCE above 3% kills Disinflation glide [S21]; a falling Sahm with persistent 3M10Y steepening kills Recession flight to quality [S13][S3].

The Cleveland Fed publishes a probability of recession in one year of 11.4 percent for September 2026 [S24]. The New York Fed's yield-curve model figure is unconfirmed at monthly frequency; its reliably reported value is a 2026 year-average twelve-month-ahead recession probability of 0.28 percent, from a snippet of its table [S37].

Binary map (end-state, 31 December 2027; probabilities follow frame weights): DGS10 below 4.00% resolves yes only in Recession flight to quality; DGS10 above 5.50% only in Bond bear steepening; the funds target below 4% resolves yes in Recession flight to quality and partly in Disinflation glide; a December 2027 THREEFYTP10 mean above 1.5% resolves yes in Bond bear steepening and is not derivable elsewhere. Cumulative weights rise monotonically with the threshold — 15% below 4.00%, 40% at or below 4.75%, 80% at or below 5.50% — so no easier threshold carries less probability.

## Most-likely trajectory and leading indicators

### Most-likely path to end-2027

The modal path is Higher-for-longer plateau — 40%: a DGS10 fixing between 4.75% and 5.50% on 31 December 2027 (an end-state criterion, the last trading day's official close), centered around 5.0–5.3%. The starting point is 5.13% (2026-10-21) [S1] on a positively sloped curve — 2s10s at 0.31% and 3M10Y at 0.78% on 2026-10-23 [S2][S3]. Compensation, not inflation expectations, is doing the work: the 10-year breakeven was 2.34% and the 5y5y forward 2.2% on 2026-10-23 [S4][S5], while the term premium on a 10-year zero-coupon bond printed 0.986% on 2026-10-16, at the top of its five-year range of −0.193% to 0.96% [S6]; against a fitted 10-year zero-coupon yield of 5.107% [S7], that leaves roughly 4.1 percentage points as the expected-rate component (derived: 5.107 − 0.986).

Quarterly shape: Q4 2026 consolidation near 5% (October 2026 partial-month mean 5.202% [S1]) after the September 16, 2026 hike to 3-3/4 to 4 percent [S9]; the September SEP's median funds-rate midpoint of 4.25% at end-2026 and end-2027 [S21] sits a fraction above the 3.875% end-September midpoint [S8], implying at most one or two further quarter-point increases. H1 2027: a plateau while the core PCE median glides from 3.4% (2026) to 2.5% (2027) [S21] and the balance sheet stays in ample-reserves mode (total assets 6,753,604 millions of U.S. dollars on 2026-10-21 [S17]; reserve-management purchases since December 2025 [S29]). H2 2027: issuance and deficit pressure holds the premium near 1%, consistent with CBO's baseline assumption that the 10-year rate "rises gradually through 2027 and remains relatively stable in later years" [S11]. CME 30-day fed funds futures closed 23 October 2026 at 95.82 (February 2027) and 95.44 (November 2027) [S10], an upward-sloping implied funds path through 2027 that matches a plateau; the SEP medians first decline only in 2029, to 3.75% from 4.25% at end-2028 [S21].

The Cleveland Fed's yield-curve model put the probability of recession in the United States one year ahead at 11.4 percent for September 2026, down from 12.3 percent in August 2026 [S24].

### Catalyst calendar

| Date | Event | Published stance / data | Discriminates |
| --- | --- | --- | --- |
| 2026-11-04 (date unconfirmed) | Quarterly refunding | August 2026: nominal coupon and FRN auction sizes unchanged "for at least the next several quarters" [S27]; Q4 2026 privately-held net marketable borrowing estimated at $628 billion [S32] | any coupon-size increase moves toward Bond bear steepening — 20% |
| December 2026 FOMC (SEP round) | decision and dots | end-2026 median midpoint 4.25% [S21] | a cut would undermine Higher-for-longer plateau — 40% |
| Monthly CPI/PCE and Michigan prints | inflation | Michigan 1-year at 4.6% (2026-09) [S12]; 2027 core PCE central tendency 2.3–2.6% [S28] | Disinflation glide — 25% |
| Monthly TIC releases | foreign holdings | Japan and China shifts (no 2026 figure gathered) | bear steepening versus plateau |
| NY Fed prob_rec, updated within the first two weeks of each month [S25] | 12-months-ahead recession probability | steepened-curve input [S3] | Recession flight to quality — 15% |

### Signposts

| Indicator | Threshold | Period | Effect |
| --- | --- | --- | --- |
| Term premium [S6] | sustained above 1.5% | any 2027 month | confirms Bond bear steepening — 20%; below 0.75% kills it |
| 5y5y forward [S5] | sustained below 2.1% | by mid-2027 | supports Disinflation glide — 25% |
| Michigan 1-year [S12] | below 3% | by mid-2027 | supports glide; above 5% supports the plateau |
| Sahm indicator [S13] | rising to its recession threshold (0 pp in 2026-09) | any month | confirms Recession flight to quality — 15% |
| Nov 2027 fed funds futures [S10] | above 96, i.e. implied funds below about 4% (100 − 96) | during H1 2027 | glide or recession pricing |

Falsifiers: Higher-for-longer plateau — 40% fails if refundings lift coupon sizes and the premium clears 1.5%; Bond bear steepening — 20% fails if the November 2026 refunding again holds coupons [S27] with the premium stalled near 1% [S6]; Disinflation glide — 25% requires core PCE tracking the 2.3% lower bound of the central tendency [S28]; Recession flight to quality — 15% is falsified by a flat Sahm indicator [S13] and the Cleveland Fed probability staying near its 11.4 percent September 2026 reading [S24].

### Figure: University of Michigan: Inflation Expectation

![University of Michigan: Inflation Expectation](demos/ust10y-2027/research-charts/data_fred_mich_77dd8d691ebd9aad.png)

*Official series from FRED; latest observation marked: down from a year earlier. [S12]*

## News and market context

### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability.

| Provider / kind | Source | Published / retrieved | Status / captured contract |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport\_timeout) |

## References

- [S1] Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis — https://fred.stlouisfed.org/series/DGS10?drf_series=fred%3ADGS10 (tier 1; fetched)
- [S2] 10-Year Treasury Constant Maturity Minus 2-Year Treasury Constant Maturity — United States — https://fred.stlouisfed.org/series/T10Y2Y?drf_series=fred%3AT10Y2Y (tier 1; fetched)
- [S3] 10-Year Treasury Constant Maturity Minus 3-Month Treasury Constant Maturity — United States — https://fred.stlouisfed.org/series/T10Y3M?drf_series=fred%3AT10Y3M (tier 1; fetched)
- [S4] 10-Year Breakeven Inflation Rate — United States — https://fred.stlouisfed.org/series/T10YIE?drf_series=fred%3AT10YIE (tier 1; fetched)
- [S5] 5-Year, 5-Year Forward Inflation Expectation Rate — United States — https://fred.stlouisfed.org/series/T5YIFR?drf_series=fred%3AT5YIFR (tier 1; fetched)
- [S6] Term Premium on a 10 Year Zero Coupon Bond — United States — https://fred.stlouisfed.org/series/THREEFYTP10?drf_series=fred%3ATHREEFYTP10 (tier 1; fetched)
- [S7] Fitted Yield on a 10 Year Zero Coupon Bond — United States — https://fred.stlouisfed.org/series/THREEFY10?drf_series=fred%3ATHREEFY10 (tier 1; fetched)
- [S8] Central bank policy rates - United States - Monthly - End of period — https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US?drf_series=bis%3AWS_CBPOL%2FM.US (tier 1; fetched)
- [S9] Federal Reserve Board - Federal Reserve issues FOMC statement — https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm (tier 1; fetched)
- [S10] 30 Day Federal Funds Futures Quotes - CME Group — https://www.cmegroup.com/markets/interest-rates/stirs/30-day-federal-fund.quotes.html (tier 3; fetched)
- [S11] The Budget and Economic Outlook: 2026 to 2036 | Congressional Budget Office — https://www.cbo.gov/publication/62105 (tier 1; fetched)
- [S12] University of Michigan: Inflation Expectation — https://fred.stlouisfed.org/series/MICH?drf_series=fred%3AMICH (tier 1; fetched)
- [S13] Real-time Sahm Rule Recession Indicator — United States — https://fred.stlouisfed.org/series/SAHMREALTIME?drf_series=fred%3ASAHMREALTIME (tier 1; fetched)
- [S14] 10 Year Treasury Yield (1962-2026) — https://www.macrotrends.net/2016/10-year-treasury-bond-rate-yield-chart (tier 3; fetched)
- [S15] US10Y: U.S. 10 Year Treasury - Stock Price, Quote and News - CNBC — https://www.cnbc.com/quotes/US10Y (tier 3; search snippet)
- [S16] Market Yield on U.S. Treasury Securities at 10-Year Constant Maturity, Quoted on an Investment Basis, Inflation-Indexed — https://fred.stlouisfed.org/series/DFII10?drf_series=fred%3ADFII10 (tier 1; fetched)
- [S17] Assets: Total Assets: Total Assets (Less Eliminations from Consolidation): Wednesday Level — United States — https://fred.stlouisfed.org/series/WALCL?drf_series=fred%3AWALCL (tier 1; fetched)
- [S18] Monthly Treasury Statement: Surplus (+) or Deficit (-) (current month) — United States — https://fiscaldata.treasury.gov/datasets/monthly-treasury-statement/?drf_series=usgov%3Atreasury%2Fmts_deficit (tier 1; fetched)
- [S19] FedWatch - CME Group — https://www.cmegroup.com/markets/interest-rates/cme-fedwatch-tool.html (tier 3; search snippet)
- [S20] Why Fed Forecasting Tools Are Worth Watching - Charles Schwab — https://www.schwab.com/learn/story/why-fed-forecasting-tools-are-worth-watching (tier 3; search snippet)
- [S21] Summary of Economic Projections, September 16, 2026 — https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20260916.pdf (tier 1; fetched)
- [S22] FOMC Statement: September 2026 | J.P. Morgan Asset Management — https://am.jpmorgan.com/us/en/asset-management/adv/insights/portfolio-insights/fixed-income/fixed-income-perspectives/fomc-statement-september-2026/ (tier 3; search snippet)
- [S23] FOMC Summary of Economic Projections, September 2026 — https://fred.stlouisfed.org/blog/2026/09/fomc-summary-of-economic-projections-september-2026 (tier 3; search snippet)
- [S24] Yield Curve and Predicted GDP Growth — https://www.clevelandfed.org/indicators-and-data/yield-curve-and-predicted-gdp-growth (tier 3; search snippet)
- [S25] The Yield Curve as a Leading Indicator - FEDERAL RESERVE BANK of NEW YORK — https://www.newyorkfed.org/research/capital_markets/ycfaq (tier 3; fetched)
- [S26] Term Premium on a 10 Year Zero Coupon Bond - FRED — https://fred.stlouisfed.org/series/THREEFYTP10 (tier 3; search snippet)
- [S27] Quarterly Refunding Statement of Deputy Assistant Secretary for Federal Finance Brian Smith | U.S. Department of the Treasury — https://home.treasury.gov/news/press-releases/sb0590 (tier 1; fetched)
- [S28] The Fed - September 16, 2026: FOMC Projections materials, accessible version — https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260916.htm (tier 1; fetched)
- [S29] The Fed - May 2026 — https://www.federalreserve.gov/monetarypolicy/May-2026-Federal-Reserve-Balance-Sheet-Developments.htm (tier 1; fetched)
- [S30] US - ACM 10Y Treasury Term Premium Estimates | MacroMicro — https://en.macromicro.me/charts/45452/us-10-treasury-term-premium (tier 3; fetched)
- [S31] ACMTP10: NY Fed 10-Year Term Premium Monthly Data - Eco3min — https://eco3min.fr/en/us-term-premium-dataset/ (tier 3; search snippet)
- [S32] Treasury Announces Marketable Borrowing Estimates | U.S. Department of the Treasury — https://home.treasury.gov/news/press-releases/sb0584 (tier 1; fetched)
- [S33] Most Recent Quarterly Refunding Documents | U.S. Department of the Treasury — https://home.treasury.gov/policy-issues/financing-the-government/quarterly-refunding/most-recent-quarterly-refunding-documents (tier 1; fetched)
- [S34] Monthly Statement of the Public Debt (MSPD) - U.S. Treasury Fiscal Data — https://fiscaldata.treasury.gov/datasets/monthly-statement-public-debt/ (tier 1; search snippet)
- [S35] US Treasury bill issuance grows, heightens long-term risk - Reuters — https://www.reuters.com/legal/transactional/us-treasury-bill-issuance-grows-heightens-long-term-risk-2026-07-23/ (tier 2; search snippet)
- [S36] [PDF] Considerations for T-bill Issuance — https://home.treasury.gov/system/files/221/TBACCharge1Q32024.pdf (tier 1; search snippet)
- [S37] Probability of US Recession Predicted by Treasury Spread — https://www.newyorkfed.org/medialibrary/media/research/capital_markets/prob_rec.pdf (tier 3; search snippet)
- [S38] newyorkfed.org — https://www.newyorkfed.org/medialibrary/media/research/capital_markets/Prob_Rec.pdf (tier 3; fetched)
- [S39] Scavette-O'Trakoun-Sahm-style (SOS) Recession Indicator — https://www.richmondfed.org/research/national_economy/sos_recession_indicator (tier 3; search snippet)

## Visual Annex

### Event Timeline

![Event Timeline](demos/ust10y-2027/research-charts/timeline.png)

[Interactive version](demos/ust10y-2027/research-charts/timeline.html)

_Dated key events driving the forecast, most recent window._

### Observed and Published Forecast Trajectories

![Observed and Published Forecast Trajectories](demos/ust10y-2027/research-charts/metric_trajectories.png)

[Interactive version](demos/ust10y-2027/research-charts/metric_trajectories.html)

_Three or more sourced points on one definition; x-axis is period end, not publication date._
