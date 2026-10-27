# Forecast global AI datacenter capital expenditure and electricity demand for calendar year 2027: total hyperscaler capex with a 70% confidence interval…

## Executive Summary

For calendar-year 2027 we forecast combined capital expenditure by Amazon, Microsoft, Alphabet and Meta at roughly $800–950 billion (our forecast), with a 70% confidence interval from about $725 billion — near combined 2026 guidance of $720–745 billion [S1] — to roughly $1.05–1.1 trillion; the interval is derived from the scenario bands below against that guidance baseline. None of the four had issued formal 2027 guidance as of 20 October 2026 [S2][S3]. The binding constraint is physical, not financial: US real GDP growth is projected at 2.293% for 2027 (publisher projection) [S4], and the gap between datacenter power demand and deployable supply is clearing through price and delay. Global datacenter electricity consumption most likely grows 12–20 percent year-over-year in 2027; the IEA's central projection ("Key Questions on Energy and AI", 2026) of 485 TWh in 2025 roughly doubling to about 950 TWh by 2030, after 17% growth in 2025 [S5], implies roughly 14 percent per year. We therefore put the probability of exceeding 20 percent growth at about 45 percent, and the probability that interconnection constraints delay more than 5 GW of planned US datacenter capacity into 2028 at roughly 15 percent; smaller slippage is already embedded in the central case.

The baseline is a record of roughly $410 billion spent by the four in 2025 and about $725 billion planned for 2026, up 77 percent [S3][S6]. On the power side, over 2,060 GW of generation and storage was actively seeking US transmission interconnection at end-2025, and the median time from request to commercial operation exceeded five years for projects built in 2025 (Berkeley Lab observed dataset) [S7]. GE Vernova's gas contracts reached 116 GW against a company target of at least 125 GW by end-2026 [S8], and PJM wholesale prices rose 41 percent in 2026 [S9]. Observed load shows strain rather than surge: EIA retail sales of electricity, US total commercial sector, rose 4.306% year-over-year in 2026-07 (stored observation) [S10]; Virginia, the largest load pocket, rose 9.788% year-over-year in 2025-12 (stored observation) [S11].

Scenarios, from the fixed frame:

- Continued buildout surge — 45% — capex roughly $950 billion to $1.1 trillion and electricity growth above 20 percent as committed GPU and power capacity arrives on trend.
- Measured growth plateau — 35% — capex near $800–950 billion, growth decelerating, electricity growth roughly 12–20 percent as interconnection and turbine constraints bind.
- Power-constrained slowdown — 15% — grid delays push more than 5 GW of US capacity into 2028, capex stalls near 2026 levels, electricity growth under 15 percent.
- Overbuild correction — 5% — weak AI monetization cuts capex below 2026 levels and electricity growth drops sharply.

The most important leading indicators: the Q3 2026 earnings calls in late October–November 2026, the next decisive 2027 disclosure [S2][S3]; GE Vernova's contracted backlog against its end-2026 target of at least 125 GW [S8]; PJM wholesale prices and queue completion-versus-withdrawal rates [S7][S9]; monthly EIA commercial-sector sales, especially Virginia [S10][S11]; and revisions to the IEA's 485-to-950 TWh path [S5]. The view shifts down if any of the four signals 2027 capex at or below 2026 levels by mid-November 2026, if turbine backlogs stall short of 125 GW at end-2026, or if AI monetization disappoints; it shifts up if guidance moves above $1 trillion in early 2027 while Virginia-style load growth accelerates and queue completions rise.

## Baseline: current capex and electricity demand

### Hyperscaler capital expenditure: 2025 actuals and 2026 guidance

As of Q3 2025 earnings in late October 2025, the four hyperscalers collectively expected more than $380 billion of 2025 capital expenditure: Amazon guided to roughly $125 billion (raised from $118 billion), Alphabet to $91–93 billion (raised from $75–85 billion), and Meta narrowed its range to $70–72 billion [S12]. Microsoft's fiscal-year 2025 (ended June 2025) capex rose 45% to $64.55 billion excluding finance leases not yet commenced, and CFO Amy Hood said fiscal 2026 growth would accelerate, implying a minimum of about $94 billion [S12]. Press tallies in April 2026 put the four companies' 2025 actual at a record of roughly $410 billion, against 2026 plans of about $725 billion, up 77% [S3][S6]; the gap versus the ">$380 billion" expectation reflects definitional scope — cash capex versus finance-lease-inclusive measures — and full-year actuals [S12][S1].

The latest calendar-2026 guidance for the four adds up to $720–745 billion: Amazon about $220 billion, Alphabet $195–205 billion, Meta $130–145 billion, and Microsoft roughly $175 billion on an accounting-adjusted basis [S1]. The total mixes bases: Amazon emphasizes cash capex, Meta includes finance-lease principal payments, and Microsoft counts finance leases when they commence [S1]. Per Statista, analyst estimates run as high as about $760 billion [S13]. Deployment is back-loaded, with roughly $432 billion expected in the second half of 2026 alone [S2]. Independently, the IEA states that combined capex of the largest tech companies exceeded USD 400 billion in 2025 and is "expected to jump by another 75% in 2026" [S5].

### Datacenter electricity use: 2024–2026

On the IEA's series, global data centre electricity consumption was around 415 TWh in 2024, about 1.5% of global electricity [S14], and 485 TWh in 2025, a year in which data centre demand grew 17% — "in line with IEA projections" — while consumption at AI-focused data centres grew about 50% [S5]. The IEA's central projection reaches roughly 950 TWh by 2030 [S5], and its 2026 update warns that value-chain bottlenecks are "reducing the likelihood of more aggressive near-term scenarios" [S5].

EIA publishes no standalone datacenter series in the Short-Term Energy Outlook; commercial-sector sales, "which includes data centers," are the stated proxy [S9]. US retail electricity sales to the commercial sector were 150578.728 million kWh in July 2026 versus 144363.1467 million kWh in July 2025 [S15]; year-over-year growth was 4.306% in July 2026 and 3.448% in July 2025, within a five-year range of -2.122% to 8.715% [S10]. Virginia, the largest US datacenter load pocket, printed 9.788% year-over-year commercial growth in December 2025, up from 4.477% in December 2024 [S11]. In 3Q26, US electricity consumption rose 4% year over year, with the commercial sector up 5%, driven partly by a hot summer — weather, not only data centers [S9]. The macro demand backdrop is supportive: US real personal consumption expenditures grew 3.8% in 2026-Q2 versus 2.1% in 2025-Q2 [S16].

| Metric | Baseline value, period | Status | Marker |
|---|---|---|---|
| Four-hyperscaler capex, 2025 | >$380bn collective expectation (Oct 2025); ~$410bn actual per April 2026 tallies | expectation; reported actual | [S12]; [S3][S6] |
| Four-hyperscaler capex, 2026 | $720–745bn | latest guidance aggregation | [S1] |
| Global datacenter electricity, 2024 | ~415 TWh | IEA estimate | [S14] |
| Global datacenter electricity, 2025 | 485 TWh, +17% | IEA estimate | [S5] |
| US commercial retail sales | 150578.728 million kWh (July 2026), +4.306% YoY | EIA sample estimate | [S15][S10] |

### Figure: Real Personal Consumption Expenditures — United States

![Real Personal Consumption Expenditures — United States](demos/ai-capex-2027/research-charts/data_fred_dpcerl1q225sbea_c25f95a72f99834b.png)

*Official series from FRED; latest observation marked: up from a year earlier. [S16]*

### Figure: EIA: Retail Sales of Electricity: U.S. total, commercial sector

![EIA: Retail Sales of Electricity: U.S. total, commercial sector](demos/ai-capex-2027/research-charts/data_usgov_eia_electricity_sales_us_com_6cfeae3c8d37fb43.png)

*Official series from U.S. Energy Information Administration; latest observation marked: up from a year earlier, the highest in the charted period; bold line = derived twelve-month average of the monthly values. [S15]*

## Official Data Baseline

| Series | Latest historical value | Period | Yearly change | Status | Publisher projection | Source |
|---|---|---|---|---|---|---|
| Real Personal Consumption Expenditures — United States | 3.8% Change from Preceding Period | 2026-Q2 | +1.7 pp | stored observation | — | [S16] |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector | 150578.728 Million kilowatt-hours | 2026-07 | +6215.5814 (+4.306%) | stored observation | — | [S15] |
| Gross domestic product (GDP), Constant prices, Percent change: United States | 2.344% change | 2025 | -0.608 pp | publisher estimate | 2026: 2.328%; 2027: 2.293% | [S4] |
| EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) | 9.788% change from year ago | 2025-12 | +5.311 pp | stored observation | — | [S11] |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) | 4.306% change from year ago | 2026-07 | +0.857 pp | stored observation | — | [S10] |

### Figure: EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change)

![EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change)](demos/ai-capex-2027/research-charts/data_usgov_eia_electricity_sales_us_com_yoy_93025409efc61892.png)

*Official series from U.S. Energy Information Administration; latest observation marked: up from a year earlier. [S10]*

## Hyperscaler capex outlook to 2027

None of the four hyperscalers had issued formal 2027 capex guidance as of 20 October 2026; the 2027 picture rests on analyst consensus, bank models and guidance dynamics, with the Q3 2026 earnings calls (late October–November 2026) the next decisive disclosure [S2][S3].

### Consensus and bank models

MarketScreener's consensus (table dated August 2026, as compiled by I/O Fund) puts calendar-2027 capex at $284.8 billion for Alphabet, $256.5 billion for Amazon, $207.6 billion for Microsoft and $185.6 billion for Meta — a combined $934.5 billion [S2]. JP Morgan and Goldman Sachs each forecast AI capex of $1 trillion or more in 2027 for the big-tech group, as characterized by I/O Fund in August 2026 [S2]; after the Q1 2026 calls, Evercore and Bank of America modeled combined 2027 hyperscaler capex above $1 trillion [S3].

| Publisher, edition | Label and type | 2027 value as published | Alignment to our metric |
|---|---|---|---|
| MarketScreener consensus, Aug 2026 table | Analyst consensus | Combined $934.5bn (Alphabet $284.8bn, Amazon $256.5bn, Microsoft $207.6bn, Meta $185.6bn) [S2] | Calendar-year capex, mixed lease bases |
| JP Morgan, Aug 2026 | Bank forecast | ≥$1.0tn big-tech AI capex [S2] | Above consensus |
| Goldman Sachs, Aug 2026 | Bank forecast | ≥$1.0tn [S2] | Above consensus |
| Evercore ISI / Bank of America, post-Q1 2026 | Bank model | Combined above $1tn [S3] | Reported; above consensus |

### Revision dynamics and the upside skew

The consensus has lagged outcomes throughout the cycle: on Goldman Sachs (FactSet) data, 2025 hyperscaler capex estimates climbed from about $253 billion to nearly $394 billion across successive revisions, and 2026 forecasts from about $284 billion to more than $525 billion [S2]. Guidance moves in contagion: after Alphabet raised its 2026 outlook in July 2026, Evercore ISI's Mark Mahaney judged it more likely that Amazon and Microsoft would follow, even as the shares of Amazon, Meta and Microsoft fell amid rising capex scrutiny, per CNBC [S17]. On I/O Fund's derived arithmetic, guided 2026 capex of $732.5 billion needs only +36.5% year over year (+$267.5 billion) to reach $1 trillion in 2027, versus the roughly 79% growth guided for 2026, whose dollar increment was $332.5 billion [S2].

### Funding capacity and structure

Funding is shifting from cash to debt. Alphabet raised $25 billion in a 2026 bond sale against an AI-linked order book above $115 billion [S3]; Meta issued $30 billion of debt in September 2026 to fund the Louisiana "Hyperion" data center via SPV financing, per a Financial Times excerpt [S18]; and Oracle issued $18 billion in October 2026 for Stargate data centers [S19]. US tech companies' future datacenter lease commitments passed $850 billion by mid-2026, led by Meta and Microsoft [S20], and analysts project hundreds of billions of datacenter-linked debt issuance in 2026 against a build-out above $3 trillion, making debt markets a gating factor for 2027 capacity [S21]. US real consumption growth of 3.8% in 2026-Q2, up from 2.1% a year earlier, supports the revenue base funding this spend [S16].

Placed against the canonical frame, the $934.5 billion consensus sits at the top of Measured growth plateau — 35% ($800–950 billion) and just below the floor of Continued buildout surge — 45% ($950 billion to $1.1 trillion), which the $1-trillion-plus bank models imply. Two caveats bound the comparison: the widely cited ~$1.65 trillion "Nikkei Asia" figure covers five companies including Oracle and combines uncommenced leases, commitments, guarantees and JV exposures, so it is not a four-company capex total [S1]; and whether Meta's $185.6 billion consensus fully reflects off-balance-sheet vehicles such as the Hyperion JV is unknown, so reported capex could undershoot economic buildout [S2].

## IEA and EIA demand outlooks

### IEA: the global trajectory

The IEA's most recent outlook, "Key Questions on Energy and AI" (2026), states in its central projection that global data centre electricity consumption was 485 TWh in 2025 and roughly doubles to about 950 TWh in 2030, around 3% of global electricity demand [S5]. The same report states that demand grew 17% in 2025, "in line with IEA projections," and that consumption at AI-focused data centres grew about 50% in 2025 and triples between 2025 and 2030 [S5]. The IEA cautions that "bottlenecks across the value chain… are reducing the likelihood of more aggressive near-term scenarios" [S5], and notes rack power density rose 11x from 2020 to 2025 with a further fourfold increase set by 2027, stressing power-electronics and transformer supply chains [S5]. The prior edition, "Energy and AI" (2025, Base Case), put 2024 at around 415 TWh (~1.5% of global electricity) rising to ~945 TWh by 2030, about 15% per year [S14][S22]; the editions are internally consistent (415 TWh growing 17% matches the 485 TWh 2025 base), and the 2025 Base Case adds ~240 TWh in the US and ~175 TWh in China by 2030, together nearly 80% of global growth [S22].

The IEA publishes no 2026 or 2027 point values on the pages available. Interpolating its endpoints, (950/485)^(1/5), gives ~14.4% per year — roughly 555 TWh in 2026 and 635 TWh in 2027, i.e. ~14% year-over-year in 2027. That is a derived interpolation, not an IEA figure; the bottleneck caveat argues against near-term years running above this path [S5]. A snippet from the report PDF suggesting a 75% increase "in 2026" is unconfirmed in scope and must not be read as total datacentre growth [S23].

### EIA: the US proxy outlook

The EIA Short-Term Energy Outlook of October 6, 2026 forecasts US commercial-sector electricity demand — "which includes data centers" — to grow 2.8% year-over-year in 2027, with industrial +2.7% and residential roughly flat [S9]. EIA publishes no standalone datacentre series in the STEO; the commercial sector is a dilute proxy that also captures weather — 3Q26 consumption rose 4% year-over-year (commercial +5%, residential +6%) partly on a hot summer [S9]. EIA projects total US generation of 4,545 billion kWh in 2026 and 4,613 billion kWh in 2027, against 4,430 billion kWh in 2025 [S9], with wholesale prices averaging $52/MWh in 2026 (+11%; PJM +41%) easing to $49/MWh in 2027 [S9]. An earlier vintage (February 2026) had total US load up 1.9% in 2026 and 2.5% in 2027 [S24] (reported); Reuters frames the October STEO as record consumption in both years [S25] (reported).

Observed baseline: US commercial retail sales were 150,578.728 million kWh in July 2026 versus 144,363.1467 million kWh a year earlier (+4.306%) [S15], against Real PCE growth of 3.8% in 2026-Q2 (2.1% in 2025-Q2) [S16]. The IEA's "Electricity 2026" forecast that US electricity use adds more than 420 TWh over 2026–2030 with data centres about half of that growth [S26] implies US datacentre additions averaging >40 TWh/yr — roughly 45% of the IEA's global additions of (950−485)/5 ≈ 93 TWh/yr (derived from [S5][S26]).

### Outlook comparison

| Publisher, edition | Label / type | Value as published | Fit to the 2027 >20% question |
|---|---|---|---|
| IEA, Key Questions on Energy and AI (2026) | Central projection (external) | 485 TWh (2025) → ~950 TWh (2030); +17% in 2025 [S5] | Global, datacentres only; no 2026–27 point values; endpoints imply ~14–15%/yr |
| IEA, Energy and AI (2025) | Base Case (external) | ~415 TWh (2024) → ~945 TWh (2030), ~15%/yr [S14][S22] | Same metric; endpoint path only |
| IEA, Electricity 2026 | Forecast | US adds >420 TWh 2026–2030; datacentres ~50% of growth [S26] | US additions, not a global growth rate |
| EIA, STEO (Oct 6, 2026) | Short-term forecast | US commercial demand +2.8% YoY in 2027 [S9] | Proxy: all commercial loads, not datacentres alone |

On every consistent reading, both agencies' central paths sit below 20% growth for 2027 — the prior embedded in "Measured growth plateau — 35%" ("agency outlooks cluster below 20 percent"); "Continued buildout surge — 45%" requires the total to outrun the IEA's central path. The view changes if IEA data tables print a 2027 value well above the ~635 TWh interpolation, if EIA's 2027 commercial forecast revises materially above 2.8% in later STEO editions during 2027, or if the reported 75% 2026 increase [S23] is confirmed to cover total rather than AI-focused datacentres.

## Historical base rates of demand growth

### The stitched global record

No official continuous annual series of global datacentre electricity consumption exists; the base rate must be stitched from IEA, LBNL and Koomey estimates of different vintages and scopes [S22][S27][S28][S29]. On those estimates (reported figures from secondary renderings of the studies): global data centre energy use rose modestly from 194 TWh in 2010 to 205 TWh in 2018, about 1% of world electricity (Masanet et al., Science 2020) [S27][S30]; US datacentres held roughly steady near 70 billion kWh per year in the mid-2010s (Koomey et al., 2018) [S28]; and LBNL's 2016 report put US growth near 3%/yr over 2010–2014 [S29]. The IEA's 2025 report put 2024 at around 415 TWh, having grown about 12% per year over the preceding five years, with a Base Case of about 15% per year to 2030 [S14][S22]; its 2026 update states 2025 growth was 17% [S5]. Cross-model arithmetic — 2018→2024 at roughly 12.5%/yr and 2010→2018 at roughly 0.7%/yr (derived from [S22][S30]) — inherits definitional mismatches; the internally consistent IEA figure is the ~12%/yr.

### Base-rate counts

| Series, rule | Window | Result |
|---|---|---|
| Global documented years: calendar-year growth >20% | ~2005–2024, stitched estimates | Essentially 0 of ~15 documented years exceeded 20%; 20%+ episodes are documented only for the 2000s dot-com buildout; Laplace (0+1)/(15+2) ≈ 6% (analyst count from [S22][S27][S28][S29][S30]) |
| US commercial retail sales, monthly YoY >20% | 240 months, 2006-08 to 2026-07 | 0 of 240; window maximum 11.042% (2021-05); stored 5-year range −2.122% (2023-12) to 8.715% (2022-01) [S10] |
| Virginia commercial retail sales, monthly YoY >20% | 240 months, 2006-01 to 2025-12 | 7 of 240 (~2.9%): 2021-05 (20.472%), 2021-11 (25.246%), 2022-01 (23.575%), 2022-04 (22.919%), 2022-05 (22.136%), 2022-12 (27.176%), 2023-03 (27.222%) [S11] |

Latest official readings: US commercial sales grew 4.306% year-over-year in July 2026 (3.448% a year earlier) [S10]; Virginia commercial grew 9.788% in December 2025 (4.477% in December 2024), 5-year range −6.782% (2023-01) to 27.222% (2023-03) [S11]. Count arithmetic is derived from the stored official series.

Two caveats govern the official proxies. First, dilution: commercial-sector sales include offices and retail, so the US series understates datacentre-only growth — independent estimates such as CRS's 176 TWh of US datacentre use in 2023 [S31] and EPRI's scenario of datacentres reaching up to 9% of US generation [S32] imply sector growth far above the commercial band (both reported). Virginia is the closer but noisier proxy. Second, regime dependence: before 2021 Virginia never printed a >20% month in fifteen years (maximum ~18.408%, 2015-02); every exceedance falls in 2021–2023 and none after March 2023 [S11] — a base rate that shifts with the investment cycle, not a stationary parameter.

### What trend continuation implies

Continuing the best-documented trend — ~12%/yr over 2019–2024 [S14], 17% in 2025 [S5], the Base Case's ~15%/yr [S22] — puts 2027 in the mid-to-high teens, below the 20% threshold; the outside view answers "no" to >20% in 2027. Tracing the canonical frame: "Continued buildout surge — 45%" needs the total to exceed 20% for the first well-documented year, plausible only because the AI subset grew ~50% in 2025 [S5]; "Measured growth plateau — 35%" is trend continuation; "Power-constrained slowdown — 15%" would echo the post-2023 Virginia pattern, where >20% prints stopped as constraints tightened [S11]; "Overbuild correction — 5%" rhymes with the dot-com bust, the only prior 20%+ regime. The base-rate view would move if 2026 global growth prints at or above 20%, if Virginia monthly YoY re-enters >20% territory during 2027, or if the 485 TWh 2025 base is revised upward [S5].

### Figure: EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change)

![EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change)](demos/ai-capex-2027/research-charts/data_usgov_eia_electricity_sales_va_com_yoy_17cf5d90bbaeb7ad.png)

*Official series from U.S. Energy Information Administration; latest observation marked: up from a year earlier. [S11]*

## Grid interconnection constraints in the US

US interconnection queues are generation-side, not datacenter-specific: over 2,060 GW of generation and storage capacity was actively seeking transmission interconnection at end-2025 (Berkeley Lab "Queued Up", observed dataset) [S7], yet only 13% of capacity requesting interconnection in 2000–2020 had reached commercial operation by end-2025, with 75% withdrawn [S7]. Median time from request to commercial operation exceeded five years for projects built in 2025 [S7]; Orrick's datacenter guide cites datacenter power-interconnection delays of 5+ years, with some transmission upgrades approaching a decade [S33]. Datacenters enter as load via delivery-point requests: Dominion reported 40,000 MW of datacenter-related capacity requests as of December 2024, versus 451 Virginia datacenters consuming 3,583 MW in 2024 [S34].

### Target-year state

| Metric | Baseline | Central view | Range | Decisive driver | Signpost |
|---|---|---|---|---|---|
| US datacenter capacity scheduled for 2027 | 8.5 GW realized in 2025 [S35] | 36.3 GW scheduled (Goldman Sachs/Aterio forecast) [S35] | ~18–22 GW energized (derived: 50–60% on-time × 36.3 GW) | transformer/turbine supply; queue timing | on-time share vs ~60%, H1 2027 |
| 2027-planned GW slipping into 2028 | PJM cut its summer-2027 peak forecast ~4 GW in Jan 2026 on stricter datacenter vetting [S36] | >5 GW slipping: more likely than not (derived 15–18 GW at risk) | ~5–18 GW | interconnection timing | PJM GIA signings; FERC protocol milestones |

Goldman Sachs Research, on Aterio facility-level data, forecasts 13.6 GW of US datacenter additions scheduled for 2026 and 36.3 GW for 2027, versus realized 6.4 GW (2024) and 8.5 GW (2025); only ~60% of capacity scheduled a year out and ~50% two years out is expected online on time, with supply chain and labor the most common delay causes and typical builds of 18–24 months post-permit [S35]. Applying that 40–50% slippage to 36.3 GW implies roughly 15–18 GW of scheduled 2027 capacity arriving late — a derived figure, not a published one. Against a 5-GW threshold, this arithmetic makes a slip above 5 GW more likely than not. The canonical frame prices the severe, capex-stalling version as Power-constrained slowdown — 15%, but more than 5 GW can equally slip within Measured growth plateau — 35%, where constraints bind without halting the buildout; SemiAnalysis counters that "half cancelled" framings overstate risk by sampling the most cancellation-prone pipeline slice [S37].

### Path and milestones

| Milestone | Date | Status | Slack |
|---|---|---|---|
| FERC order on large-load interconnection protocols | 18 Jun 2026 | Issued [S38]; RTO responses reported due 16 Nov 2026 [S39] | relief after mid-2027 |
| ERCOT connection pause (Texas governor's order) | 3 Aug 2026 | BNEF: could delay 49.8 GW of the 253-GW US pipeline; only 1.2 GW of ERCOT additions forecast 2Q26–1Q27 [S40] | months expected [S40] |
| PJM Expedited Interconnection Track | opened 31 Jul 2026 | up to 10 projects/yr (≥250 MW) in 2026–27; GIAs in ~10 months [S41] | tight |
| PJM IRAS large-load rules | from 1 Jun 2027 | new ≥50 MW loads must bring new capacity, buy a backstop, or face curtailment [S41] | none for late entrants |
| PJM reformed Cycle 1 | 2026–2028 | 201.5 GW qualified of 220 GW proposed [S42]; 51 GW of signed GIAs held, many stalled [S43] | — |

### Supply-demand note

Scheduled 2027 additions of 36.3 GW [S35] far outrun demonstrated energization of 8.5 GW in 2025 [S35]; the binding constraint is grid-equipment and interconnection timing — Reuters reports generator step-up transformer lead times surpassed 160 weeks in Q1 2026, up from a 143-week average in 2024 [S38]. The gap clears through slippage into 2028, not faster energization.

### What would change the view

- ERCOT pause lifted before end-2026, removing the conditional 49.8-GW exposure [S40].
- PJM expedited-track GIAs totalling ≥2.5 GW signed by Q1 2027.
- 2027 on-time share tracking above 60% by mid-2027 [S35].
- PJM's January 2027 forecast cutting 2027/28 peaks by more than 4 GW again [S36].
- Transformer lead times back below the 143-week 2024 average during 2027 [S38].

## Power procurement bottlenecks and supply chain

The binding limits on 2027 buildout are physical lead times, not capital. Orrick's November 2025 guide puts US datacenter power interconnection delays at 5+ years, with transmission infrastructure delays extending into the decade-long range in some jurisdictions, against US datacenter demand growing 23% annually [S33]. The IEA's 2025 outlook warned that, absent grid action, around 20% of planned datacentre projects could be at risk of delay, citing transformer and cable wait times that have doubled in three years and gas turbine lead times of several years [S14].

### Turbines: slots effectively closed for 2027 delivery

GE Vernova signed 21 GW of new gas turbine agreements in Q1 2026; capacity under contract rose sequentially from 83 to 100 GW, backlog from 40 to 44 GW, and slot reservations from 43 to 56 GW [S44]. By Q2 2026 it reported gas power equipment backlog and slot reservations rising from 100 to 116 GW, with at least 125 GW under contract expected by end-2026 [S8]. CEO Scott Strazik put directional lead times on new heavy-duty orders at about three years as of Q1 2026 — an order placed in 2026 delivers after 2027 — while cautioning the turbine is often not a project's binding constraint [S44]. Utility Dive reported GE Vernova expected to end 2025 with an ~80 GW backlog stretching into 2029, with reservations sold out through 2030 by end-2026 [S45]. Pricing signals scarcity: H1 2026 orders are tracking 10–20 points higher per kilowatt than Q4 2025 orders, and Wood Mackenzie projects (external projection) gas turbine prices reaching $600/kW by end-2027, nearly triple 2019 levels [S44].

### Transformers and grid equipment

Reuters reported generator step-up transformer lead times surpassing 160 weeks by Q1 2026, up from an average 143 weeks in 2024 [S38]; vendor pages put main power transformers at 128 weeks and GSU units at 144 weeks [S46][S47], a spread reflecting equipment class and survey vintage. Utilities are buying equipment up to five years ahead, refurbishing older transformers, and asking customers to pre-pay for long-lead gear [S38]. Datacenters' share of the US electrical equipment market could rise to 40% under accelerated scenarios, from just under 2% in 2020 (Wood Mackenzie analysis cited by Reuters) [S38]. Orders confirm the squeeze: datacenter customers generated more GE Vernova electrification orders (substations, switchgear, transformers, HVDC) in Q1 2026 — $2.4 billion — than in all of 2025, with total electrification orders roughly doubling year-over-year to $7.1 billion [S44]; datacenter electrification orders exceeded $5 billion year-to-date as of July 2026, more than double the 2025 total, within a $176 billion company backlog [S8]. The IEA notes AI-server rack power density rose 11x between 2020 and 2025, with a further fourfold increase set by 2027, testing supply chains for power electronics and transformers [S5].

### Workarounds: fast gas on site; nuclear arrives after 2027

The toolkit spans nuclear and geothermal PPAs, natural gas and fuel cells, co-located generation, Clean Transition Tariffs, and behind-the-meter and virtual PPAs [S33]. GE Vernova markets aeroderivative and containerized units advertised as powering a site in "2 weeks" [S48]; Chevron and GE Vernova have teamed for 4 GW by 2027 (vendor-reported), fitting fast-deploy inventory rather than new heavy-duty slots given the three-year lead time [S48][S44]. Nuclear is strategic but late: Meta's reported January 2026 agreements for up to 6.6 GW by 2035 [S49], its 20-year, 1.1 GW Constellation PPA [S50], Microsoft's Constellation/Three Mile Island arrangement [S51], and Google's reported 1,800 MW Elementl Power deal [S52] support the 2027 capex pipeline but add little 2027 electricity.

### Supply-demand note

| Milestone for 2027 service | Latest start (implied) | Status | Slack |
|---|---|---|---|
| New heavy-duty turbine order | ~2024 (three-year lead [S44]) | Reservations sold out through 2029–2030 [S45][S8] | None |
| GSU transformer order | ~2023–24 (160+ weeks [S38]) | Utilities pre-paying, buying five years ahead [S38] | None; refurbishment only |
| Behind-the-meter fast gas | Permits and gas supply | "2 weeks" start advertised; 4 GW Chevron–GEV by 2027 [S48] | Positive, bounded by fuel and permitting |

Turbine slots and transformer lead times are the binding constraints; the gap clears through price, backlog conversion, imports, behind-the-meter generation, or demand pushed into 2028.

## Actor incentives and financial capacity

As of 20 October 2026 none of the four hyperscalers has issued formal 2027 capex guidance, so capacity and willingness must be read from 2026 guidance, funding actions and external projections. Combined 2026 guidance stands at $720–745 billion — Amazon ~$220 billion, Alphabet $195–205 billion, Meta $130–145 billion, Microsoft ~$175 billion on an accounting-adjusted basis that mixes capex definitions [S1] — up about 77% from a 2025 record of roughly $410 billion for the four, per post-Q1 aggregations [S3][S6], with cumulative capex of ~$1.1 trillion from 2023 to June 2026 per an FT tally [S3]. The IEA similarly estimates the largest tech companies' combined capex exceeded $400 billion in 2025 and expects a further 75% jump in 2026 (publisher estimate) [S5].

| Actor | 2026 posture | 2027 external view | Capacity signal |
|---|---|---|---|
| Amazon (AWS) | ~$220B plan [S1] | consensus $256.5B [S2] | Largest spender; sets the 2027 floor |
| Microsoft | ~$175B, accounting-adjusted [S1] | consensus $207.6B [S2] | Three Mile Island PPA reported, ~835 MW [S51][S53] |
| Alphabet | $195–205B [S1] | consensus $284.8B [S2] | $25B bond drawn on >$115B order book [S3] |
| Meta | $130–145B [S1] | consensus $185.6B [S2] | $30B SPV debt for Hyperion [S18]; >1.1 GW nuclear PPA reported [S50] |
| Dominion | "robust demand" from data centers [S54] | 5.4%/yr load growth expected [S55] | Q3 2025 revenue $4.53B, up from $3.94B [S54] |
| GE Vernova | argues turbines are not "gating" buildouts [S56] | reservations reported sold out through 2030 [S45] | Q2 2026 orders $24.2B (+88% organic), backlog $176B, guidance raised [S8] |
| PJM | bring-your-own-capacity (IRAS) from June 2027 [S41] | — | 2027/28 auction $16.4B, data centers $6.5B, reported [S57] |

### Escalation logic under investor scrutiny
The revision record points upward: successive analyst revisions lifted 2026 hyperscaler capex forecasts from ~$284 billion to more than $525 billion [S2], and Evercore ISI's Mark Mahaney judged Alphabet's July 2026 increase likely to pull Amazon and Microsoft up with it [S17]. The check on escalation is monetization: shares of Amazon, Meta and Microsoft fell after Alphabet's hike even as cloud revenue accelerated, signaling rising capex scrutiny [S17]. Consensus of $934.5 billion for 2027 against $720–745 billion guided for 2026 implies a further ~$190–215 billion increment [S2][S1] — fundable only if AI-linked revenue keeps beating, with OpenAI-anchored commitments and Oracle's $18 billion October 2026 Stargate issuance illustrating external demand underwriting the buildout [S19].

### Funding channels: from cash flow to structured debt
The mix is shifting: Alphabet's $25 billion bond drew an order book above $115 billion [S3]; Meta issued $30 billion in September 2026 for the Louisiana "Hyperion" campus via SPV financing [S18]; Oracle issued $18 billion in October 2026 [S19]; future data-center lease commitments passed $850 billion by mid-2026, led by Meta and Microsoft [S20]. With 2026 data-center-linked issuance projected in the hundreds of billions against a buildout framed above $3 trillion, debt markets become a new gating factor for 2027 capacity [S21]. Meta's SPV also moves spend off balance sheet, so reported capex may understate physical buildout.

### Assessment
Capital is unlikely to be the binding constraint inside 2027: demonstrated debt appetite, GE Vernova's $176 billion backlog funding its own expansion [S8], and utility rate-base incentives (PJM's auction outcome [S57]; Dominion's decade of 5.4% expected load growth [S55]) all point the same way, while gas turbines (~3-year lead times [S44], slots committed toward 2030 [S45]) and interconnection timing bind instead. Nuclear deals — Meta's reported up-to-6.6 GW by 2035 [S49] — support late-decade growth, not the 2027 increment. Current incentive alignment underpins "Continued buildout surge — 45%"; monetization disappointment is the mechanism bending the path toward "Measured growth plateau — 35%", and in the tail toward "Overbuild correction — 5%".

## Leading indicators and signposts

Four dated signal clusters will revise the 2027 capex and electricity forecasts before 31 December 2027: hyperscaler guidance and financing, grid-equipment backlogs, utility and interconnection data, and agency demand series.

### Capex guidance and financing signals

Combined 2026 guidance for the four hyperscalers stands at $720–745 billion [S1], and the MarketScreener consensus table dated August 2026 puts calendar-2027 capex at $934.5 billion for the four [S2] — a consensus that has drifted persistently upward, with 2026 estimates climbing from roughly $284 billion to more than $525 billion across successive revisions [S2]. The first test is Q3 2026 earnings season (late October–November 2026): after Alphabet's July 2026 raise, Evercore ISI's Mark Mahaney judged Amazon and Microsoft likely to follow, even as Amazon, Meta and Microsoft shares fell under capex scrutiny [S17]. Guidance contagion toward $800 billion for 2026, or first formal 2027 guidance near the >$1 trillion that Evercore and Bank of America model [S3], would support Continued buildout surge — 45%; flat or trimmed guidance would feed Overbuild correction — 5%. Financing signals: Meta's $30 billion September 2026 and Oracle's $18 billion October 2026 debt issues [S18][S19], and reportedly more than $850 billion of tech datacenter lease commitments as of July 2026 [S20].

### Grid-equipment and turbine backlogs

GE Vernova's July 22, 2026 release is the richest single indicator set: datacenter electrification orders above $5 billion year-to-date — more than double the 2025 total — total Q2 orders of $24.2 billion (+88% organically), total backlog of $176 billion, and 2026 revenue guidance raised to $45.5–46.5 billion [S8]. Gas backlog plus slot reservations grew from 100 GW to 116 GW in Q2 2026, with at least 125 GW expected under contract by end-2026 [S8]; trade press reports 2031 delivery slots already on sale [S58]. Q4 2026 and Q2 2027 earnings test this: contracts below about 125 GW, or electrification order growth reverting toward 2025's pace, would mark Measured growth plateau — 35%. Transformer lead times conflict by source — Reuters reports GSU lead times above 160 weeks in Q1 2026 versus a 143-week 2024 average [S38], while vendor pages cite 128–144 weeks [S46][S47] — so the quarterly direction matters more than the level. Utilities buying equipment five years ahead and seeking customer pre-payment [S38] signals multi-year commitment.

### Utility and interconnection data

PJM's January 14, 2026 forecast cut its summer 2027 peak by about 4 GW and 2028 by 4.4 GW, citing stricter datacenter vetting [S36]; a January 2027 vintage repeating a cut of 4 GW or more would push toward Power-constrained slowdown — 15%. Dominion Energy Virginia reportedly held about 53.8 GW of contracted datacenter capacity in July 2026, up roughly 5.3 GW from December 2025 [S59]; derived thresholds — additions of 5 GW or more per half-year sustain the surge, below about 2 GW signals constraints binding [S59][S55]. FERC's June 18, 2026 order on large-load protocols [S38] meets its first deadline in RTO show-cause responses due November 16, 2026 [S39]. The ERCOT pause ordered August 3, 2026 — which BNEF says could delay 49.8 GW [S40] — needs a declared end date; BNEF forecasts only 1.2 GW of ERCOT additions from 2Q 2026 through 1Q 2027 [S40]. Against Goldman/Aterio's 36.3 GW of US additions scheduled for 2027 and roughly 50% two-year on-time rate [S35], actual energizations are the cleanest test of the >5 GW delay question.

### Demand-series signposts

US commercial-sector retail sales grew 4.306% year over year in July 2026 [S10]; Virginia commercial grew 9.788% in December 2025 [S11]; the October 2026 STEO forecasts 2.8% commercial growth for 2027 [S9]. Monthly STEO editions and EIA-861M prints through 2027 test the path, while the IEA flags value-chain bottlenecks capping near-term upside [S5]. The IMF projects US GDP growth of 2.328% (2026) and 2.293% (2027) [S4]; a slide toward 1.5% would be a macro falsifier.

### What would change the view

- Any of the four guides 2027 capex more than 10% below its August 2026 consensus line (combined $934.5 billion) — Q4 2026/Q1 2027 earnings calls [S2].
- GE Vernova ends 2026 below 125 GW of gas capacity under contract — Q4 earnings, January 2027 [S8].
- PJM's January 2027 forecast cuts 2027–28 peaks by another 4 GW or more [S36].
- Dominion contracted-GW additions fall below about 2 GW per half-year — February 2027 call [S59][S55].
- EIA STEO revises 2027 commercial growth below about 2% — monthly releases from November 2026 [S9].

### Figure: Gross domestic product (GDP), Constant prices, Percent change: United States

![Gross domestic product (GDP), Constant prices, Percent change: United States](demos/ai-capex-2027/research-charts/data_wb_imf_weo_ngdp_rpch_usa_cc01f5d58301f87f.png)

*Official series from IMF World Economic Outlook via World Bank Data360; latest observation marked: up from a year earlier; squares = estimates; dashed shaded segment = IMF WEO projection, ending below the latest observation. [S4]*

## Forecast synthesis and scenarios

### Scenario Probability Distribution
- **Continued buildout surge (45% probability):** Hyperscaler capex reaches roughly $950 billion to $1.1 trillion in 2027 and datacenter electricity growth exceeds 20 percent as committed GPU and power capacity arrives on trend; prior: continuation of the 2024-2026 acceleration.
- **Measured growth plateau (35% probability):** Capex lands near $800-950 billion with YoY growth decelerating and datacenter electricity growth of roughly 12-20 percent as interconnection and turbine constraints bind; prior: agency outlooks cluster below 20 percent.
- **Power-constrained slowdown (15% probability):** Grid delays push more than 5 GW of US datacenter capacity into 2028 and capex growth stalls near current 2026 levels, with electricity growth under 15 percent.
- **Overbuild correction (5% probability):** Weak AI monetization triggers capex cuts to below 2026 levels and datacenter electricity growth drops sharply; prior: rare but precedented tech capex busts.

### Target-year state table (calendar 2027)

| Metric | Baseline | Central view | Scenario envelope | Decisive driver | Signpost |
|---|---|---|---|---|---|
| Four-hyperscaler capex | 2026 guidance $720–745B [S1] | $934.5B 2027 analyst consensus [S2] | $410B 2025 actual (reported) [S6] to ≥$1T (JPMorgan/Goldman Sachs, per I/O Fund) [S2] | Guidance-revision momentum | Q3/Q4 2026 earnings calls |
| Global datacenter electricity, YoY | 485 TWh in 2025, +17% [S5] | ~14% (my interpolation on 485→950 TWh, 2025–30 [S5]) | Under 15% to over 20% | Grid-equipment bottlenecks [S5] | IEA update; Virginia commercial YoY [S11] |
| US capacity delayed >5 GW into 2028 | 36.3 GW scheduled for 2027 [S35] | Delay exceeds 5 GW (40–50% slippage × 36.3 GW ≈ 15–18 GW, my derivation from [S35]) | Under 5 GW to 49.8 GW ERCOT-exposed [S40] | ERCOT pause length; PJM rules | PJM January 2027 forecast [S36] |

The frame's median falls inside Measured growth plateau: consensus capex and ~14% interpolated growth both sit in its $800–950B / 12–20% band. The binding constraint is equipment and interconnection, not capital: GE Vernova's gas contracts reached 116 GW, targeting at least 125 GW by end-2026 [S8], while PJM wholesale prices rose 41% in 2026 [S9] — the gap clears through price and delay unless monetization fails.

### Continued buildout surge

Continued buildout surge carries the frame's 45%. Consensus keeps outrunning guidance — 2026 forecasts rose from ~$284B to over $525B [S2], H2 2026 spend alone ~$432B [S2], lease commitments past $850B per trackers [S20]. Above-20% electricity growth requires committed capacity energizing on trend; Dominion's contracted pipeline of roughly 53.8 GW (per Zacks summaries) supports the path [S59]. Signposts: further guidance raises after Alphabet's reported July 2026 hike [S17]; Dominion adding ≥5 GW per half-year. Moves up if 2026 spending tops $745B [S1].

### Measured growth plateau

Measured growth plateau carries the frame's 35%. The IEA warns bottlenecks "reduce the likelihood of more aggressive near-term scenarios" [S5]; EIA's commercial proxy grows 2.8% in 2027 [S9], with July 2026 US commercial sales at 150,578.728 million kWh, +4.306% YoY [S15]. Turbine slot reservations climbed to 56 GW in Q1 2026 [S44]; GSU transformer lead times top 160 weeks per Reuters [S38]. Landing in $800–950B needs a smaller increment than 2026's guided $332.5B increase (I/O Fund arithmetic) [S2].

### Power-constrained slowdown

Power-constrained slowdown carries the frame's 15%. The ERCOT pause exposes 49.8 GW [S40]; extending it beyond BNEF's three-month delay scenario, plus PJM's IRAS curtailment regime from June 1, 2027 [S41], turns queue friction — median request-to-operation over five years [S7] and the ~4 GW cut to PJM's 2027 summer peak [S36] — into slipped capacity. The >5 GW threshold could resolve yes even outside this scenario; the full scenario additionally requires stalled capex. FERC's November 16, 2026 responses move this either way [S39].

### Overbuild correction

Overbuild correction carries the frame's 5%. Debt now funds the buildout — Meta $30B and Oracle $18B reported in late 2026 [S18][S19] — against projected 2027 US GDP growth of 2.293% [S4] and 3.8% PCE growth in 2026-Q2 [S16]; investor pressure followed Alphabet's raise [S17]. Rare in the reference class; watch cloud-revenue deceleration in Q4 2026 prints.

### Binary map and coherence

- Growth over 20% (IEA series, CY2027 vs CY2026): yes under Continued buildout surge (45%); Measured growth plateau tops at 20%; no elsewhere.
- Over 5 GW delayed into 2028: yes under Power-constrained slowdown (15%), plausible under the growth scenarios on derived slippage — an easier threshold than capex stall, so never less likely.
- Capex ≥$950B: only under Continued buildout surge; consensus sits just below at $934.5B [S2].

No market prices appear in the evidence; matching markets would resolve on combined CY2027 capex in Q4 2027 filings, IEA global data-centre TWh, and US GW with planned 2027 operation energized in 2028.

### What would change the view

1. Q3/Q4 2026 earnings: all four pushing 2026 guidance above $745B [S1] favors the surge; any cut raises correction risk.
2. ERCOT pause extending past 1Q2027 [S40].
3. PJM's January 2027 forecast trimming 2027 further beyond the ~4 GW cut [S36].
4. IEA printing 2026 at roughly 582 TWh or more (485 × 1.2, derived from [S5]).
5. GE Vernova closing 2027 delivery slots with at least 125 GW contracted [S8].

## Risks to the forecast

The scenario mass concentrates in Continued buildout surge — 45% and Measured growth plateau — 35%, so this section focuses on what shifts weight toward Power-constrained slowdown — 15% and Overbuild correction — 5%, or reinforces the surge. The decisive channels are financing and AI monetization on the downside, and self-supplied power on the upside.

### Downside: financing and monetization

Funding has shifted from cash flow toward debt: Meta issued $30 billion in September 2026 to fund its Louisiana "Hyperion" data center via SPV financing, and Oracle issued $18 billion in October 2026 for Stargate data centers [S18][S19]. Alphabet raised $25 billion in a 2026 bond sale against an AI-linked order book above $115 billion [S3], and US tech companies' future data center lease commitments passed $850 billion as of mid-2026 [S20]; against a build-out projected above $3 trillion, hundreds of billions of dollars of data-center-linked issuance in 2026 alone makes debt markets a gating factor for 2027 capacity [S21]. Monetization risk is live: shares of Amazon, Meta and Microsoft fell after Alphabet raised its 2026 capex forecast in July 2026 amid rising capex scrutiny [S17]. Analyst revisions have been one-directional — 2026 hyperscaler capex forecasts climbed from about $284 billion to more than $525 billion over successive revisions [S2] — leaving consensus exposed to the first sustained downward revision. Macro deterioration is not in the central view: IMF publisher projections put US GDP growth at 2.328% in 2026 and 2.293% in 2027 [S4], but a recession would feed Overbuild correction — 5%.

### Downside: grid and equipment

The IEA warns that without grid action, about 20% of planned data centre projects could face delays, with transformer and cable wait times having doubled in three years [S14]. Reuters reports generator step-up transformer lead times above 160 weeks in Q1 2026, up from an average of 143 weeks in 2024 [S38], and new heavy-duty gas turbine orders carry roughly three-year lead times per GE Vernova's CEO [S44]. Texas's audit-driven pause on new ERCOT data center connections could alone delay 49.8 GW of demand [S40], and PJM cut its summer 2027 peak forecast by about 4 GW on stricter data center vetting [S36]. With only about 50–60% of capacity scheduled a year ahead arriving on time [S35], these are the channels into Power-constrained slowdown — 15%.

### Upside: self-build power and regulatory fast-tracking

GE Vernova markets containerized, fast-start gas units advertised as powering a site in "2 weeks" [S48]; its marketing also claims a Chevron partnership to deliver 4 GW by 2027 [S48]. Data center customers ordered $2.4 billion of GE Vernova electrification equipment in Q1 2026 — more than in all of 2025 — and gas turbine slot reservations rose from 43 to 56 GW [S44]; Q2 2026 data-center electrification orders exceeded $5 billion year-to-date against a $176 billion total backlog [S8]. FERC's June 18, 2026 order for faster large-load connection protocols [S38], PJM's Expedited Interconnection Track with agreements expected in roughly 10 months [S41], and guidance-contagion after Alphabet's hike [S17] all push toward Continued buildout surge — 45%.

### What would change the view

| Indicator | Threshold | Date |
|---|---|---|
| Hyperscaler capex guidance at Q3/Q4 2026 earnings | Two or more cut or freeze guidance below the $720–745 billion 2026 aggregate [S1] | Nov 2026–Feb 2027 |
| Order-book coverage on major data-center bond issues | Below ~2x, versus the >4x coverage on Alphabet's $25 billion sale against a >$115 billion book [S3] | Through H1 2027 |
| ERCOT pause duration | Extended beyond BNEF's expected "months", delaying beyond the 1.2 GW additions window [S40] | Q1 2027 |
| GE Vernova slot reservations and data-center electrification orders | Reservations stalling near 56 GW or orders below 2025's full-year total [S44][S8] | Q1 2027 results |
| Dominion contracted data-center pipeline | Growth below ~2 GW per half-year from the ~53.8 GW reported for July 2026 (Zacks summary) [S59] | Each earnings call through 2027 |

## References

- [S1] Big Tech’s 2026 Capex Range Reaches $720 Billion to $745 Billion | MLQ News — https://mlq.ai/news/big-techs-2026-capex-range-reaches-720-billion-to-745-billion/ (tier 3; fetched)
- [S2] AI Capex to Hit $1 Trillion – And Estimates Are Still Too Low - I/O Fund — https://io-fund.com/ai-stocks/ai-capex-1-trillion-estimates-too-low (tier 3; fetched)
- [S3] Amazon, Microsoft, Alphabet, Meta Plan $725B AI Capex in 2026 — https://aiweekly.co/alerts/amazon-microsoft-alphabet-meta-plan-725b-ai-capex-in-2026 (tier 3; fetched)
- [S4] Gross domestic product (GDP), Constant prices, Percent change: United States — https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH?drf_series=wb%3AIMF_WEO_NGDP_RPCH%2FUSA (tier 1; fetched)
- [S5] Executive summary - Key Questions on Energy and AI - IEA — https://www.iea.org/reports/key-questions-on-energy-and-ai/executive-summary (tier 1; fetched)
- [S6] Google, Microsoft, Meta, and Amazon capex spending to ... — https://finance.yahoo.com/sectors/technology/articles/google-microsoft-meta-amazon-capex-131823436.html (tier 3; search snippet)
- [S7] Queued Up: Characteristics of Power Plants Seeking Transmission Interconnection | Energy Markets & Planning — https://emp.lbl.gov/queues (tier 1; fetched)
- [S8] GE Vernova Releases Second Quarter 2026 Financial Results | GE Vernova News — https://www.gevernova.com/news/articles/ge-vernova-releases-second-quarter-2026-financial-results (tier 3; fetched)
- [S9] Short-Term Energy Outlook - U.S. Energy Information Administration (EIA) — https://www.eia.gov/outlooks/steo/report/elec_coal_renew.php (tier 1; fetched)
- [S10] EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) — https://www.eia.gov/electricity/data/browser/?drf_series=usgov%3Aeia%2Felectricity_sales%2FUS.COM%23yoy (tier 1; fetched)
- [S11] EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) — https://www.eia.gov/electricity/data/browser/?drf_series=usgov%3Aeia%2Felectricity_sales%2FVA.COM%23yoy (tier 1; fetched)
- [S12] How much Google, Meta, Amazon and Microsoft are spending on AI — https://www.cnbc.com/2025/10/31/tech-ai-google-meta-amazon-microsoft-spend.html (tier 3; fetched)
- [S13] Big Tech's AI Spending to Reach $760 Billion in 2026 — https://www.statista.com/chart/35046/capital-expenditure-of-meta-alphabet-amazon-and-microsoft/?srsltid=AU7gw4VwImWUOgo_pmEDDQP52w-XYBYBzJ8DHkOtLx8lEXGDuyXxsUcz (tier 3; search snippet)
- [S14] Executive summary - Energy and AI - IEA — https://www.iea.org/reports/energy-and-ai/executive-summary (tier 1; fetched)
- [S15] EIA: Retail Sales of Electricity: U.S. total, commercial sector — https://www.eia.gov/electricity/data/browser/?drf_series=usgov%3Aeia%2Felectricity_sales%2FUS.COM (tier 1; fetched)
- [S16] Real Personal Consumption Expenditures — United States — https://fred.stlouisfed.org/series/DPCERL1Q225SBEA?drf_series=fred%3ADPCERL1Q225SBEA (tier 1; fetched)
- [S17] Hyperscalers face higher capex scrutiny after Alphabet ... — https://www.cnbc.com/2026/07/28/hyperscalers-face-higher-capex-scrutiny-after-alphabet-report-panned.html (tier 3; search snippet)
- [S18] From the Financial Times: "Prices of bonds issued to fund ... — https://www.facebook.com/elerianm/posts/from-the-financial-timesprices-of-bonds-issued-to-fund-prominent-data-centres-wh/1692271715594281/ (tier 3; search snippet)
- [S19] Emerging Litigation Risks in AI Data Centers — https://www.quinnemanuel.com/media/4dzkfccz/client-alert-ai-data-center-financing-and-litigation-risks.pdf (tier 3; search snippet)
- [S20] Data Center Leases Hit $850B: Meta, Microsoft Lead [2026] — https://tech-insider.org/data-center-leases-850-billion-2026/ (tier 3; search snippet)
- [S21] The $3 Trillion AI Data Center Build-Out Becomes All ... — https://energynow.com/2026/02/the-3-trillion-ai-data-center-build-out-becomes-all-consuming-for-debt-markets/ (tier 3; search snippet)
- [S22] Energy demand from AI - Energy and AI - IEA — https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai (tier 1; fetched)
- [S23] Key Questions on Energy and AI — https://iea.blob.core.windows.net/assets/3179f7f8-01f6-4dd6-bffa-c9f7b73f1dc9/KeyQuestionsonEnergyandAI.pdf (tier 3; fetched)
- [S24] Fossil generation could rise with faster-than-expected growth in data ... - EIA — https://www.eia.gov/todayinenergy/detail.php?id=67344 (tier 1; search snippet)
- [S25] US power use to beat record highs in 2026 and 2027 as AI use surges ... — https://www.reuters.com/business/energy/us-power-use-beat-record-highs-2026-2027-ai-use-surges-eia-says-2026-10-06/ (tier 2; search snippet)
- [S26] Demand - Electricity 2026 - IEA — https://www.iea.org/reports/electricity-2026/demand (tier 1; fetched)
- [S27] Untitled — https://datacenters.lbl.gov/sites/default/files/Masanet_et_al_Science_2020.full_.pdf (tier 1; fetched)
- [S28] (PDF) Data center growth in the United States: Decoupling ... — https://www.researchgate.net/publication/328620851_Data_center_growth_in_the_United_States_Decoupling_the_demand_for_services_from_electricity_use (tier 3; search snippet)
- [S29] United States Data Center Energy Usage Report - IEA 4E — https://www.iea-4e.org/wp-content/uploads/publications/2016/06/05j_-_LBNL_-_US_Data_Centres_Energy_USe.pdf (tier 3; search snippet)
- [S30] Masanet Et Al Science 2020.full | PDF | Data Center — https://www.scribd.com/document/1032208866/Masanet-Et-Al-Science-2020-Full (tier 3; search snippet)
- [S31] Data Centers and Their Energy Consumption — https://www.congress.gov/crs-product/R48646 (tier 1; search snippet)
- [S32] Clean Energy Resources to Meet Data Center Electricity ... — https://www.energy.gov/oe/clean-energy-resources-meet-data-center-electricity-demand (tier 1; search snippet)
- [S33] Powering Data Centers — https://www.orrick.com/en/Insights/2025/11/Powering-Data-Centers (tier 3; fetched)
- [S34] Dominion prepares for 70,000 MW in data center demand - Virginia Business — https://virginiabusiness.com/dominion-data-center-power-demand-virginia-scc/ (tier 3; fetched)
- [S35] US Data Center Power Demand Projected to Double by 2027 | Goldman Sachs — https://www.goldmansachs.com/insights/articles/us-data-center-power-demand-projected-to-double-by-2027 (tier 3; fetched)
- [S36] PJM trims near-term load forecast on stricter data center vetting, economic outlook — https://www.utilitydive.com/news/pjm-interconnection-load-forecast-data-centers/809717/ (tier 3; fetched)
- [S37] Stop Saying Half of 2026 US Datacenter Capacity Is ... — https://newsletter.semianalysis.com/p/stop-saying-half-of-2026-us-datacenter (tier 3; search snippet)
- [S38] US power companies scramble to secure equipment as surging data center demand strains supplies | Reuters — https://www.reuters.com/business/energy/us-power-companies-scramble-secure-equipment-surging-data-center-demand-strains-2026-07-09/ (tier 2; fetched)
- [S39] FERC Interconnection Queue Reform 2026: EPC Guide — https://www.reslink.org/blogs/ferc-interconnection-reform/ (tier 3; search snippet)
- [S40] Texas Audit Could Delay 49.8 GW of Data Center Load, Cost Projects Up to $15 Billion, BNEF Warns — https://www.powermag.com/texas-audit-could-delay-49-8-gw-of-data-center-load-cost-projects-up-to-15-billion-bnef-warns/ (tier 3; fetched)
- [S41] PJM’s New Data Center Power Equation | Data Center Frontier — https://www.datacenterfrontier.com/energy/article/55397507/pjms-new-data-center-power-equation (tier 3; fetched)
- [S42] Over 800 New Generation Projects Seek To Connect Under PJM’s Reformed Process | PJM Inside Lines — https://insidelines.pjm.com/over-800-new-generation-projects-seek-to-connect-under-pjms-reformed-process/ (tier 3; fetched)
- [S43] Over 700 New Generation Projects Accepted Into First Cycle of Reformed Interconnection Process — https://insidelines.pjm.com/over-700-new-generation-projects-accepted-into-first-cycle-of-reformed-interconnection-process/ (tier 3; fetched)
- [S44] Data centers drive record surge in GE Vernova power equipment orders as turbine slots tighten through 2030 — https://www.power-eng.com/gas/turbines/data-centers-drive-record-surge-in-ge-vernova-power-equipment-orders-as-turbine-slots-tighten-through-2030/ (tier 3; fetched)
- [S45] GE Vernova expects to end 2025 with an 80-GW gas ... — https://www.utilitydive.com/news/ge-vernova-gas-turbine-investor/807662/ (tier 3; search snippet)
- [S46] The constraints that cause lead time delays for data centers — https://www.gigaenergy.com/blog/lead-time-delays-for-data-centers (tier 3; search snippet)
- [S47] 2026 Transformer Lead Times: Pad-Mount & Main Power ... — https://www.gamechangeenergy.com/news/transformer-lead-times-in-2026-what-pad-mounted-and-substation-buyers-can-expect (tier 3; search snippet)
- [S48] Gas Power Technology for Data Centers | GE Vernova — https://www.gevernova.com/gas-power/industries/data-centers (tier 3; fetched)
- [S49] Meta Nuclear 2026, 6.6 GW Vistra and Oklo Deals - Enki AI — https://enkiai.com/data-center/meta-nuclear-firm-power/ (tier 3; search snippet)
- [S50] Meta signs 20-year PPA with Constellation for entire output ... — https://www.datacenterdynamics.com/en/news/meta-signs-20-year-ppa-with-constellation-for-entire-output-of-illinois-nuclear-power-plant/ (tier 3; search snippet)
- [S51] Microsoft Nuclear 2026, 835 MW Constellation Deal - Enki AI — https://enkiai.com/distributed-energy/nuclear-power-microsoft-demand/ (tier 3; search snippet)
- [S52] Google Nuclear 2026, 1,800 MW Elementl Power Deal - Enki AI — https://enkiai.com/sustainability-initiatives/data-center/google-nuclear-2026-1800-mw-elementl-power-deal/ (tier 3; search snippet)
- [S53] Constellation Energy, Microsoft ink nuclear power pact for ... — https://www.constellationr.com/insights/news/constellation-energy-microsoft-ink-nuclear-power-pact-ai-data-center (tier 3; search snippet)
- [S54] Dominion in contract talks for 47 gigawatts of new data centers, up 17% this year | Reuters — https://www.reuters.com/business/energy/dominion-energy-beats-estimates-strong-power-demand-virginia-south-carolina-2025-10-31/ (tier 2; fetched)
- [S55] Dominion Energy details its $65B, 5-year spending plan | Utility Dive — https://www.utilitydive.com/news/dominion-energy-details-its-65b-5-year-spending-plan/812984/ (tier 3; fetched)
- [S56] Natural Gas Turbines Aren't ‘Gating’ Data Center Buildouts, GE Vernova Says — https://naturalgasintel.com/news/natural-gas-turbines-arent-gating-data-center-buildouts-ge-vernova-says/ (tier 3; fetched)
- [S57] The 60-Day Clock: FERC Just Forced Six Grid Operators to ... — https://avanzaenergy.substack.com/p/the-60-day-clock-ferc-just-forced (tier 3; search snippet)
- [S58] The Gas Turbine Shortage Just Became AI's Biggest ... — https://oilprice.com/Energy/Energy-General/The-Gas-Turbine-Shortage-Just-Became-AIs-Biggest-Constraint.html (tier 3; search snippet)
- [S59] Can Dominion Energy Leverage Data-Center Demand for ... — https://finance.yahoo.com/energy/articles/dominion-energy-leverage-data-center-142300316.html (tier 3; search snippet)

## Visual Annex

### Event Timeline

![Event Timeline](demos/ai-capex-2027/research-charts/timeline.png)

[Interactive version](demos/ai-capex-2027/research-charts/timeline.html)

_Dated key events driving the forecast, most recent window._
