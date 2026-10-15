# Nowcasting and releases — lags, revisions, adjustment, bridges

Load for threshold questions (a CPI, unemployment or GDP reading for a period) and any nowcast. Exact release dates come from the publishers' calendars (fetch them; shutdowns and holidays move them). This file gives the standing patterns and the arithmetic.

## 1. Release patterns (verify each date on the publisher's calendar)

| Economy | Release (publisher) | Usual lag | Revision profile | Catalog ID or route |
|---|---|---|---|---|
| US | CPI (BLS) | ~10–15 days after month end | NSA index final when published; SA factors re-estimated each year with January data, 5 years back | bls:CUUR0000SA0, fred:CPIAUCSL, fred:CPILFESL |
| US | PPI (BLS) | around the CPI | revised 4 months later | bls:WPSFD4 |
| US | Employment Situation (BLS) | usually first Friday | payrolls revised in the next two releases; annual benchmark with January data (preliminary estimate in late summer); household-survey factors and population controls change each January | fred:PAYEMS, fred:UNRATE |
| US | Jobless claims (DOL) | Thursdays, week ending prior Saturday | prior week revised | fred:ICSA, fred:CCSA |
| US | JOLTS (BLS) | ~5 weeks | next month and annually | fred:JTSJOL |
| US | Personal income and outlays, PCE prices (BEA) | ~4 weeks | monthly, plus the annual update (usually September) | fred:PCEPI, fred:PCEPILFE |
| US | GDP (BEA) | advance ~4 weeks after quarter; second and third monthly after | annual and comprehensive updates revise years | fred:A191RL1Q225SBEA, fred:GDPC1, fred:GDP (nominal) |
| US | ECI (BLS) | ~4 weeks after quarter | small | bls:CIU1010000000000A |
| US | Retail sales (Census) | mid-month | two months and annually | fred:RSAFS |
| US | Michigan survey | preliminary mid-month, final month end | preliminary → final | fred:MICH |
| US | ISM PMIs | first business days | rare | web |
| US | Monthly Treasury Statement | ~8th business day | small | usgov:treasury/mts_deficit |
| Euro area | HICP flash (Eurostat) | end of month or first days after; final mid-month | flash → final | bis:WS_LONG_CPI/M.XM.771 |
| Euro area | GDP preliminary flash | ~30 days after quarter | later estimates revise | data_search "euro area GDP growth" |
| Japan | Tokyo CPI / national CPI (MIC) | end of reference month / ~3 weeks after | rare | bis:WS_LONG_CPI/M.JP.771 |
| Japan | GDP preliminary (Cabinet Office) | ~6 weeks; second estimate ~1 month later | often large | web |
| China | Official PMI (NBS/CFLP) | last day of reference month | none | web |
| China | CPI/PPI (NBS) | ~9th–10th | rare | bis:WS_LONG_CPI/M.CN.771 |
| China | IP, retail, FAI, property (NBS) | ~mid-month; Jan–Feb combined in March | base levels revised; official YoY stands | web |
| China | GDP (NBS) | ~mid-month after quarter, with activity data | after census and annual verification | web; wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN (annual, lagged) |
| China | Loans, TSF, M2 (PBoC) | ~10th–15th, no fixed date | definitional breaks | web |
| China | Trade (GACC); FX reserves (SAFE) | ~7th–10th; 7th | — | web |
| China | LPR (PBoC, published by NIFC) | 20th | — | web |

## 2. Revisions

- **Which vintage resolves?** The resolution monitor settles from a stored retrieval. For revisable series (payrolls, GDP, PCE) the question's wording decides (first print vs as currently published): record which. ALFRED (St. Louis Fed, web) holds past vintages for checking revision history.
- **Revision-to-distance rule**: if |threshold − nowcast| is smaller than the series' typical revision, call the outcome revision-sensitive and widen the distribution.
- **Payrolls**: benchmark revisions can be large relative to monthly gains; read the latest BLS preliminary benchmark before leaning on the level.
- **GDP**: compare with GDI (from the second estimate); a wide GDP–GDI gap signals revision risk.
- **CPI**: the NSA index is not revised, which makes it the cleanest anchor for headline thresholds.

## 3. Seasonal adjustment

- BLS computes headline 12-month CPI changes from NSA indexes and m/m changes from SA ones. SA-based YoY can differ slightly; near a threshold, use the publisher's basis (bls:CUUR0000SA0#yoy). If BLS is unavailable (keyless quota), use fred:CPIAUCSL#yoy or bis:WS_LONG_CPI/M.US.771 and note the basis.
- Weekly series have no `yoy` transform in data_get: use levels or a published rate.
- **Residual seasonality**: check the same month in earlier years (January price resets in CPI, weak first-quarter GDP); the stored history makes this a quick check.
- China and the euro area: the headline is NSA YoY. China's SA m/m CPI and q/q GDP exist but are short and revised: questions resolve on YoY.

## 4. Partial periods and calendar conventions

- **Partial is not observed**: an open month of a daily series is `partial`; a quarter with one or two months of data is a nowcast; China's YTD (累计) is not the full year.
- **Year conventions differ**: annual-average growth (IMF WEO, World Bank, NBS annual GDP) ≠ Q4/Q4 (Fed SEP GDP and PCE inflation) ≠ December/December. SEP unemployment is the Q4 average; the SEP fed funds rate is the year-end midpoint. "Inflation in 2027" is ambiguous: state the basis.
- **Fiscal years**: the US federal FY runs October–September. MTS months sum to FY totals; use 12-month rolling sums or same-period-last-year comparisons rather than annualizing a partial year (April tax receipts are seasonal). Deficit ratio ≈ 12-month sum of usgov:treasury/mts_deficit (US dollars) ÷ nominal GDP (fred:GDP, billions at an annual rate: convert units); fred:FYFSGDA188S gives the official FY ratio. China's fiscal year is the calendar year.
- **Missing months** (e.g. a shutdown-cancelled release) break the 12-month base a year later. Check the stored page for gaps before computing YoY.

## 5. Threshold arithmetic (by hand)

- **YoY identity**: (1 + YoY_t) = (1 + YoY_(t−1))·(1 + m_t)/(1 + m_(t−12)), with m the NSA m/m change; approximately YoY_t ≈ YoY_(t−1) + m_t − m_(t−12). The months dropping out are known, so list them: base effects are fully predictable.
- **Required run-rate**: for target month T with k months of its 12-month window already observed, r = ((1 + X)/Π_observed(1 + m))^(1/(12 − k)) − 1 per month, or (1 + r)^12 − 1 annualized.
- **Illustration (hypothetical numbers)**: X = 2.5%; six window months observed with a cumulative +1.6% → r = (1.025/1.016)^(1/6) − 1 ≈ 0.147%/month ≈ 1.8% annualized. The question becomes "will the next six months run below ≈1.8% annualized?", to set against the recent 3m and 6m annualized rates and the same months' seasonal pattern (NSA) — or work in SA m/m and accept a small basis gap.
- **Momentum**: 3m annualized = (I_t/I_(t−3))^4 − 1; 6m annualized = (I_t/I_(t−6))^2 − 1.
- **Distance**: (threshold − latest)/σ_h, where σ_h is the standard deviation of historical h-period changes in the stored window. The forecast stage computes the same outside view, so state the window you used.

## 5a. Threshold workflow (ordered, fits a quick KIQ)

1. data_get the anchor with the exact transform (e.g. bls:CUUR0000SA0#yoy, fred:PCEPILFE#yoy, fred:UNRATE) and an early `start`. The stored window is the forecast's outside view.
2. Record the latest observed period, its status and the next release date. List the base months that will drop out of the 12-month window before the target month.
3. Compute the required run-rate (§5) and compare it with the 3m and 6m annualized rates and the latest nowcast (REPORTED).
4. List each release due before resolution, with its revision profile (§1–2). Flag the outcome as revision-sensitive when the distance is within a typical revision.
5. Record one finding per number in the §8 shape. The forecast stage can then anchor `<series> <comparator> <threshold> in <period>` directly.

## 5b. China data caveats

- Use the **official YoY**. Growth computed from published levels differs because bases are revised (FAI, industrial profits, property investment).
- **Calendar conventions**: January–February is released combined; 累计 (YTD) and 当月 (single month) are different series; Lunar New Year timing distorts January–March YoY.
- **Reported GDP is smooth** relative to targets. Cross-check it with nominal GDP and the deflator, electricity output, freight, tax revenue and PMI employment. A gap between real and nominal growth (a negative deflator) is the deflation signal.
- **Definitional breaks**: M1 scope changes, TSF components (government bonds included, other items added over time), and youth unemployment (publication paused, then a new method excluding students). Read the release notes before comparing across years.
- **PMIs**: the NBS PMI samples larger and state-linked firms; the S&P Global China PMI (S2) skews to private and export firms. Read both and do not average them.
- **Property**: 70-city new versus second-hand prices; sales floor area versus value; starts versus completions; developer funding sources. Each tells a different part of the cycle (bis:WS_SPP/Q.CN.R.628 for the long real-price index).
- **Suspensions and delays** are information, not zeros: record the gap explicitly.

## 6. Bridges from high frequency to the target series

| Target | Bridge (tier) | Use |
|---|---|---|
| Payrolls, unemployment | claims (fred:ICSA, fred:CCSA) in the survey week containing the 12th; JOLTS; ADP (S2) | direction, not level |
| CPI energy | weekly retail gasoline (fred:GASREGW) → CPI gasoline (bls:CUUR0000SETB01, NSA) | near-mechanical for the current month |
| CPI shelter | new-lease market rents (Zillow, Apartment List, CoStar: S2/S3; BLS new-tenant rent research index: S1) → bls:CUSR0000SEHA, bls:CUSR0000SAH1 | lead of roughly a year: a prior to verify with BLS/Fed research |
| CPI used cars | wholesale auction prices (Manheim: S2) → bls:CUSR0000SETA02 | lead of about 1–2 months: a prior to verify |
| Core PCE | after CPI and PPI, forecasters map components (S2); PPI supplies airfares, medical services, portfolio management | core PCE ≠ core CPI: shelter weight is far smaller in PCE |
| Tariff pass-through | import prices (bls:EIUIR); duties (usgov:treasury/mts_customs_duties, fred:B235RC1Q027SBEA) ÷ goods imports (data_search "US imports of goods") = effective tariff rate | timing and size of goods-price pressure |
| GDP | GDPNow, NY Fed Staff Nowcast (S1 models, REPORTED); fred:PCEC96, fred:INDPRO, fred:BOPGSTB | a nowcast, not an observation |
| CPI/PCE near term | Cleveland Fed inflation nowcasting (S1 model, REPORTED) for the current and next month | a strong near-term prior |
| China growth | NBS and S&P Global PMIs, electricity output, freight, port throughput, 30-city property sales (S2 vendors) | cross-checks on the official print |

## 7. Consensus and surprises

- Pre-release consensus (Bloomberg, Reuters, WSJ polls: S2) is an expectation, not a forecast of record; surprise = actual − consensus, and surprise indices (S2) summarize the run of data.
- Quarterly surveys: Philadelphia Fed SPF (S1 publisher, REPORTED values), Blue Chip (S2), ECB SPF and SMA, Japan's ESP Forecast (JCER), China Reuters/Wind polls (S2).
- Forecasters share data and models: agreement across surveys is not independent evidence.

## 8. Recording a nowcast finding

`- <series+transform> for <period>: latest observed <value> <units> (<period>, <SA/NSA>, released <date>; next release <date>) [S<n>] (VERIFIED); nowcast <value> (<model>, as of <date>) [S<n>] (REPORTED); required run-rate <r>/month vs recent <r3m>; distance <d>σ over <window> (REPORTED).`
