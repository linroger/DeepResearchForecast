# Where the Chip Chain Binds: A Segment-by-Segment Bottleneck Forecast Through End-2027

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/semichain-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | TSMC or its CEO publicly states in H2 2027 that CoWoS/SoIC packaging allocation still limits customer output or growth. | 68% | Resolves YES if between 2027-07-01 and 2027-12-31 TSMC management (earnings call, press release, or quoted statement) says CoWoS/SoIC capacity or allocation limits customers' output/growth (source: TSMC investor relations transcripts, Reuters). | ai | — |
| F2 | US semiconductor and electronic component manufacturing capacity utilization (fred:CAPUTLG3344S) is at least 80% in December 2027. | 35% | Resolves YES if fred:CAPUTLG3344S >= 80 Percent in 2027-12 (source: FRED). | ai | — |
| F3 | US industrial production for semiconductors and electronic components (fred:IPG3344S) is at least 220.0 Index 2017=100 in December 2027. | 52% | Resolves YES if fred:IPG3344S >= 220.0 Index 2017=100 in 2027-12 (source: FRED). | ai | — |
| F4 | US industrial production for semiconductors and electronic components (fred:IPG3344S) falls below its September 2026 level of 198.6335 by December 2027. | 7% | Resolves YES if fred:IPG3344S < 198.6335 Index 2017=100 in 2027-12 (source: FRED). | ai | — |
| F5 | US semiconductor and electronic component manufacturing capacity utilization (fred:CAPUTLG3344S) drops below the five-year low of 71.096% in December 2027. | 10% | Resolves YES if fred:CAPUTLG3344S < 71.096 Percent in 2027-12 (source: FRED). | ai | — |
| F6 | US real imports of goods and services (fred:IMPGSC1) come in below their 2026-Q2 level of 3913.833 billions of chained 2017 dollars in the fourth quarter of 2027. | 18% | Resolves YES if fred:IMPGSC1 < 3913.833 Billions of Chained 2017 Dollars in 2027-Q4 (source: FRED). | ai | — |
| F7 | US real exports of goods and services (fred:EXPGSC1) reach at least 2950 billions of chained 2017 dollars in the fourth quarter of 2027. | 42% | Resolves YES if fred:EXPGSC1 >= 2950 Billions of Chained 2017 Dollars in 2027-Q4 (source: FRED). Official resolution: fred:EXPGSC1 >= 2950 Billions of Chained 2017 Dollars for 2027-Q4. | ai | 28% (n=32, h=6) |
| F8 | The CoWoS supply-demand gap narrows below 5% in a TrendForce H1 2027 release. | 20% | Resolves YES if any TrendForce estimate published between 2027-01-01 and 2027-06-30 puts the TSMC CoWoS supply-demand gap below 5% (source: TrendForce news/press releases). | ai | — |
| F9 | NVIDIA confirms by 31 March 2027 that Rubin Ultra ships with at most 192 GB of HBM4/HBM4e in 8-Hi stacks rather than the 1 TB-class quad-die configuration. | 55% | Resolves YES if NVIDIA (developer blog, GTC keynote, or official roadmap update) states on or before 2027-03-31 that Rubin Ultra carries 192 GB or less HBM in 8-Hi stacks (source: NVIDIA Newsroom/developer blog). | ai | — |
| F10 | ASML's Q4 2026 results release drops its statement that planned 2027-28 supply will not fully meet customer demand. | 18% | Resolves YES if ASML's Q4 2026 earnings release or call (expected late January 2027) no longer contains the 2027-28 supply-shortfall statement and/or raises 2027 capacity plans above the +30% already guided (source: ASML investor relations). | ai | — |
| F11 | Samsung confirms an external customer 2nm (SF2) tape-out or qualification by 30 June 2027. | 22% | Resolves YES if Samsung Foundry officially announces (press release or earnings call) an external SF2/2nm customer tape-out or qualification on or before 2027-06-30 (source: Samsung Electronics newsroom / earnings calls). | ai | — |
| F12 | US industrial production for semiconductors and electronic components (fred:IPG3344S) is at least 190.0 Index 2017=100 in December 2027. | 92% | Resolves YES if fred:IPG3344S >= 190.0 Index 2017=100 in 2027-12 (source: FRED). | ai | — |
| F13 | US real exports of goods and services (fred:EXPGSC1) come in below 2700 billions of chained 2017 dollars in the fourth quarter of 2027. | 8% | Resolves YES if fred:EXPGSC1 < 2700 Billions of Chained 2017 Dollars in 2027-Q4 (source: FRED). Official resolution: fred:EXPGSC1 < 2700 Billions of Chained 2017 Dollars for 2027-Q4. | ai | 19% (n=32, h=6) |
| F14 | US semiconductor and electronic component manufacturing capacity utilization (fred:CAPUTLG3344S) drops below 73% in December 2027. | 24% | Resolves YES if fred:CAPUTLG3344S < 73 Percent in 2027-12 (source: FRED). | ai | — |
| F15 | Industry-wide CoWoS advanced-packaging capacity reaches at least 200,000 wafers per month during 2027, per a named industry tracker or TSMC-linked report. | 60% | Resolves YES if any TrendForce, Morgan Stanley, or equivalent named institutional report published by 2027-12-31 estimates industry-wide CoWoS capacity (TSMC plus OSAT partners) at >= 200,000 wafers per month for 2027. | ai | — |
| F16 | Global semiconductor equipment billings grow by less than 15% year-on-year in the fourth quarter of 2027, per SEMI. | 32% | Resolves YES if SEMI's quarterly equipment billings release for Q4 2027 shows year-on-year growth below +15% (metric: SEMI worldwide semiconductor equipment billings, YoY % change, Q4 2027). | ai | — |

_16 forecasts; 9 high-conviction (≥70% or ≤30%); 15 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States | Percent | 76.51% | 2026-09 | +2.787 pp | 71.096% to 92.195% | — | [S3] |
| Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States | Index 2017=100 | 198.6335 | 2026-09 | +32.9665 (+19.899%) | 118.1095 to 198.6335 | — | [S4] |
| Real Exports of Goods and Services — United States | Billions of Chained 2017 Dollars | 2814.538 | 2026-Q2 | +155.218 (+5.837%) | 2269.97 to 2814.538 | — | [S40] |
| Real imports of goods and services — United States | Billions of Chained 2017 Dollars | 3913.833 | 2026-Q2 | +202.793 (+5.465%) | 3164.889 to 4025.786 | — | [S41] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/semichain-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CAPUTLG3344S>) [S3]; Percent; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/EXPGSC1>) [S40]; Billions of Chained 2017 Dollars; Quarterly; SAAR · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/IPG3344S>) [S4]; Index 2017=100; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/IMPGSC1>) [S41]; Billions of Chained 2017 Dollars; Quarterly; SAAR*

<!-- viz:charts/official_series_abrccrffefdqappe.html -->
![Official Series History and Forecast Thresholds](demos/semichain-2027/charts/official_series_abrccrffefdqappe.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/EXPGSC1>) [S40]; Billions of Chained 2017 Dollars; Quarterly; SAAR*

<!-- viz:charts/official_series_ekqlnlcnnprrekcf.html -->
![Official Series History and Forecast Thresholds](demos/semichain-2027/charts/official_series_ekqlnlcnnprrekcf.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CAPUTLG3344S>) [S3]; Percent; Monthly; SA*

## Part 2 — Framework & Synthesis

### Analytical Framework

This forecast rests on three questions asked of every segment of the chain. First, is demand above available capacity today, and is the gap structural or cyclical? Second, when does credible, funded supply relief actually land — not when it is announced, but when it produces output? Third, is the segment concentrated enough that a single supplier, fab, or qualification event can convert tightness into a hard bottleneck?

The framework distinguishes capability bottlenecks (CoWoS/SoIC, HBM4, ABF substrates) from commodity bottlenecks (conventional DRAM, NAND, mature nodes). Persistence is the base case for AI-exposed choke points; mean reversion is the base case elsewhere.

### Baseline: A Two-Speed Chain

The broad manufacturing base is far from scarcity: US capacity utilization for semiconductors and electronic components (NAICS 3344) stood at 76.51% in September 2026, up 2.787 points year over year but well below the 92.195% peak of February 2022.

Against that slack baseline, the AI-exposed front end is already rationed. TSMC's CEO said on 16 July 2026 that packaging capacity is "so tight that now it's limiting my customers' growth" [S1].

### Causal Logic: Why Packaging and HBM Stay Binding

The causal spine runs from one driver: the accelerator bill of materials.

The decisive evidence for persistence is timing. Money is not the constraint; time is. Substrate relief is dated beyond the horizon: IBIDEN's Ono ramp begins Q1 2028, Unimicron's expansion reaches full run-rate only mid-2028, and Amkor's +300% lands by end-2028 [S45]. Unimicron's chairman warns publicly of a 20% supply shortfall in glass fiber cloth, CCL and ABF in 2027, with substrate equipment lead times up to 30 months [S51]. Above all, ASML stated on 14 October 2026 that its planned supply "for both 2027 and 2028 will not fully meet the demand of our customers" [S2] — a supplier-declared shortfall that gates every leading-edge logic and packaging ramp simultaneously. When the tool that makes capacity is itself the constraint, announced capacity cannot arrive early.

This is why HBM bottleneck probabilities are high but not extreme: an 8-Hi switch cuts per-GPU bits by about a third and could partially relieve HBM4 while making packaging-limited output the binding fact.

### Concentration and the Wildcards

Concentration makes tightness brittle. ASML is single-source for EUV and High-NA.

China MOFCOM's pause of its October 2025 rare-earth controls ends 10 November 2026 with no extension published [S15]. A lapse of both would raise compliance friction across tool and materials flows; escalation hurts China's own export industries, which is why gradualism is more likely than shock [S60]. These wildcards raise tail variance but do not change the modal path;

### Defending the Scenario Probabilities

It requires no new shock, only persistence consistent with the 3-of-3 base rate for capability bottlenecks.

Confidence in the spine is low-to-moderate: the Rubin Ultra configuration and the November 2026 regulatory cliffs are genuinely unresolved observable forks, not analysis gaps.

### How the Probabilities Map to Segments

The Part-1 binary forecasts operationalize this logic.

### Weighing Market and Third-Party Anchors

Where prediction-market prices existed, they were treated as one calibrated voice among sources, not an anchor: they were weighted most heavily on near-dated, well-covered events (TSMC capex guidance, ASML Q4 language) and discounted on long-dated capacity outcomes where liquidity is thin. Third-party estimates were weighted by disclosure quality. Named trackers (TrendForce, Counterpoint, Silicon Analysts) carry intermediate weight, with the caveat that TSMC discloses neither lead times nor CoWoS capacity, so all such figures are estimates [S19]. Official statistics (FRED utilization, Federal Register texts) anchor the baseline without forecasting it [S14].

### Bottom Line

The chain through 2027 binds where capability meets concentration: CoWoS/SoIC and HBM4 first, substrates and leading-edge logic tools close behind, mainstream memory tight by allocation rather than scarcity, and mature nodes, wafers, OSAT and materials tight but not binding absent a policy shock. [S51]

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Baseline Map: Utilization, Lead Times and Pricing Across the Chain, Late October 2026

The broad manufacturing base remains well below scarcity thresholds — US capacity utilization for semiconductors and other electronic components (NAICS 3344) stood at 76.51% in September 2026, up 2.787 percentage points from 73.723% a year earlier but far under the 92.195% peak of February 2022. This chapter maps that asymmetry segment by segment, because the entire forecast question — which bottlenecks persist and which dissolve — depends on where the chain is already binding in late October 2026 and where spare capacity remains. [S45]

### The aggregate picture: expansion without broad scarcity

The official US series anchors the outside view. The production side confirms hard expansion: the industrial production index for the same category reached 198.6335 (2017=100) in September 2026, +19.899% year over year and the highest value in the five-year window. Supply is growing at a near-record pace and still being outpaced in specific AI-exposed segments — the defining feature of the baseline.

### The tight side: packaging, HBM, substrates, EUV tools

**Advanced packaging (CoWoS/CoWoS-L/SoIC)** is the most unambiguously binding segment in the chain. On its 16 July 2026 call, TSMC's CEO said packaging capacity is: [S1]

> "so tight that now it's limiting my customers' growth" [S1]

TrendForce estimates the supply-demand gap narrowing from about 20% mid-2026 to about 10% by end-2026 [S20] — improved, but still a deficit requiring allocation. The disputed numbers matter less than the mechanism: packaging, not wafer starts, is the gate on AI hardware output, and TSMC's own words confirm it [S1].

**HBM (HBM3E/HBM4)** is the second binding segment. Revenue share in Q2 2026 was SK Hynix 50%, Samsung 33%, Micron 18%. [S43]

**Mainstream memory is tight by crowding-out, not by demand.** DRAM and NAND together are projected to account for 68% of memory industry growth [S27].

**ABF substrates and upstream materials** form the third tight cluster. Relief is dated beyond the forecast horizon: IBIDEN's Ono ramp begins Q1 2028 and Unimicron reaches full run-rate only mid-2028, with Amkor's +300% expansion by end-2028 [S45].

**Equipment — above all EUV** — is the newest member of the tight list, and the most consequential for everything upstream. On 14 October 2026 ASML stated that its planned supply: [S2]

This is a supplier-declared shortfall from the sole EUV/High-NA vendor, and it converts what was a demand-side story into a supply-side gate on every leading-edge and packaging ramp.

### The loose side: mature nodes, wafers, OSAT, consumer silicon

The rest of the chain is tightening gently, not scarce. SMIC operates under Entity List constraints that cap its equipment access [S70], limiting how much China-side capacity can relieve global mature-node demand regardless of price. Conventional OSAT lines and mainstream consumer silicon sit closest to the aggregate 76.51% utilization picture [S3]: the tightness that exists is at the advanced-packaging front end of the back-end, where ASE captures TSMC overflow, not on conventional wire-bond lines.

### Disputed data and what the disputes mean

Three disputes in the baseline deserve explicit treatment, because each shapes downstream probabilities. First, CoWoS lead times and capacity: every number is a third-party estimate against TSMC's non-disclosure policy [S19]; forecasts that cite one number as if it described the whole substrate market misstate the constraint.

Every subsequent chapter of this forecast is an argument about which of these four binding segments stays bound, and whether the ASML gate spreads the tightness upstream into leading-edge logic itself.

## The Demand Engine: How the Accelerator Bill of Materials Pulls the Chain

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/semichain-2027/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

<!-- viz:charts/regional_comparison.html -->
![Regional Comparison by Metric Family](demos/semichain-2027/charts/regional_comparison.png)

*Regional Comparison by Metric Family*

<!-- viz:charts/quantitative_claims.html -->
![Comparable Forecast Benchmarks](demos/semichain-2027/charts/quantitative_claims.png)

*Comparable Forecast Benchmarks*

The AI accelerator boom is not a uniform demand shock across the semiconductor chain. It is a bill-of-materials multiplier concentrated on a handful of segments — advanced packaging, HBM, leading-edge logic wafers, and large ABF substrates — with per-unit intensity that grows faster than unit shipments themselves. That structural asymmetry, more than any single forecast error, is why the chain binds at packaging and memory first while broad utilization measures stay moderate.

### The Multiplier Structure: Why Accelerators Pull Some Segments Far Harder

A single flagship GPU now consumes a slice of every scarce segment at once. Each Rubin package also requires a large CoWoS interposer and a high-layer-count ABF substrate, meaning every GPU shipped pulls packaging capacity, substrate capacity, and DRAM wafer allocation simultaneously.

The aggregate effect shows in the packaging numbers.

The mechanism propagates upstream in a specific order. Packaging binds first because its capacity is the smallest and most concentrated: TSMC owns most CoWoS/SoIC capacity, and its CEO said on 16 July 2026 that packaging capacity is 'so tight that now it's limiting my customers' growth' [S1].

### Containment Actions That Amplify Scarcity

NVIDIA's response has been to buy out the chain ahead of rivals. It has signed multibillion-dollar capacity reservations and new capacity agreements with IBIDEN, Unimicron and Amkor [S45] — pre-committing to substrate and packaging capacity before it is built. These reservations have a double effect: they de-risk NVIDIA's roadmap, and they remove incremental capacity from the merchant market, tightening availability for everyone else. Critically, IBIDEN's new Ono plant ramps from Q1 2028 and Amkor targets a capacity expansion of roughly +300% by end-2028 [S45], so the reserved volume lands almost entirely after this forecast's horizon. The 2027 supply of substrates and outsourced packaging is therefore effectively fixed by capacity already installed or under construction in 2026 — demand-side decisions in 2027 can reshuffle allocation, but they cannot add wafers.

The same logic shows up in substrates, where customers are rushing to lock in ABF long-term agreements and Ajinomoto has raised ABF film prices by 30% [S31].

### The Decisive Contested Variable: Rubin Ultra's 2027 HBM Configuration

NVIDIA's published roadmap points to a quad-die Rubin Ultra in the second half of 2027 with 1 TB-class HBM4e in 12-Hi stacks. [S43] NVIDIA has confirmed neither path.

The stakes are asymmetric across scenarios.

Two second-order effects deserve emphasis. Second, either configuration still requires large-format CoWoS-L-class packaging for a dual-die or quad-die package, so packaging tightness is partly insulated from the HBM outcome: Rubin Ultra binds packaging in both worlds, but binds memory in only one. This asymmetry is a core reason packaging carries a higher bottleneck probability than HBM in this report's ranked list, despite both being sold out today.

There is a further subtlety in who bears the risk.

### A Counterargument: Demand Echo Rather Than Structural Shortage

On this reading, tripled demand is already being answered by tripled capacity, and 2027 will clear the packaging market the way most announced capacity ramps have historically closed shortages within four to six quarters. [S48]

The rebuttion is timing asymmetry. Unimicron's chairman has warned publicly of equipment lead times up to 30 months and a 20% shortfall in glass fiber cloth, CCL and ABF supply in 2027 [S51]. A gap narrowing measured against 2026 demand does not survive a 2027 demand step that is itself the contested Rubin Ultra variable.

There is also a fragility argument running the other way. Because roughly 60% of CoWoS capacity is committed to one customer, the packaging market is more exposed to a single buyer's demand revision than a diversified one. [S1]

### The Observation Calendar

The demand engine's direction becomes legible on a short calendar. TSMC's January 2027 Q4 call will disclose 2027 capex guidance and updated packaging commentary. [S48] TrendForce's quarterly CoWoS gap and HBM ASP prints [S25] provide continuous telemetry on whether demand is outrunning the installed base.

In short, the demand engine does not pull the chain evenly.

## The Supply Response: Capacity Announcements vs Realistic Ramp Timing

That is the central finding of this chapter: money is not the constraint; time is. But when each announced addition is dated against realistic equipment lead times, construction schedules and qualification gates, the arithmetic shows relief concentrating in 2028, with only partial and uneven slack arriving during 2027. [S51]

### Packaging: the 80% CAGR that still arrives late

A SEMI-sourced report similarly frames TSMC's CoWoS doubling as a 2028 event [S12].

Why the skepticism about the optimistic end of that range?

- **Tool gating.** Because the leading-edge logic constraint propagates through tool supply rather than cleanroom space, funded logic and packaging capacity tend to slip together — scarcity carries from N3 into N2 rather than clearing on schedule.
- **Demand compounding in parallel.**
- **Next-generation timing.** TSMC's CoPoS packaging — the technology needed for the largest 2027-class packages — reaches pilot production only in mid-2027, so it contributes essentially no volume inside the window. [S48]

The steelman for faster relief deserves an answer: a doubling of CoWoS capacity in roughly two years has in fact happened before, and the TrendForce gap-narrowing sequence is a genuine, observed improvement, not a promise. If that 10% end-2026 gap continued narrowing linearly, packaging would clear by mid-2027 and the balanced-chain scenario (10%) would gain weight. [S20] But the gap series measures TSMC's line-item capacity against demand booked on TSMC;

### HBM and memory: reallocation is the supply response, and it creates a second bottleneck

This is why the binding constraint in mainstream memory is allocation of DRAM wafers to HBM rather than any physical shortage of memory capacity: conventional DRAM contract prices are forecast up 10-15% QoQ and NAND up 15-20% QoQ in 4Q26 precisely because HBM absorbs the wafer starts, and the tightness is cleared by price and long-term-agreement caps rather than new capacity [S25]. Samsung and SK Hynix finished-memory inventory below 10 days of supply in September 2026 [S28] confirms there is no inventory buffer to bridge 2027.

The timing trap here mirrors packaging.

### Substrates: the relief that lands after the horizon

Nowhere is the announcement-versus-delivery gap starker than in ABF substrates. Map the dated commitments:

- **IBIDEN**: the Ono plant holds a 3x capacity expansion reserved by NVIDIA on a multibillion-dollar commitment, ramping from Q1 2028 — zero slack before end-2027. [S43]
- its KF plant in Taiwan adds capacity from Q2 2027 but reaches full run-rate only by mid-2028. [S47]

And the upstream is warning loudly.

### Equipment and materials: the gate above every ramp

The supply response itself needs a supply response, and that is where ASML's 14 October statement bites. [S2] they do not confirm delivery.

Upstream materials reinforce rather than relieve.

### What the calendar implies for the scenario split

Assemble the dated relief into a single timeline and the report's probability structure follows almost mechanically. The supply response is therefore back-loaded by construction. If demand growth decelerates while CoWoS still ramps, the chain bifurcates into a relieved HBM segment and a still-bound packaging/substrate segment — the 30% packaging-only case. [S31] The announcements are real; the calendar is not on the buyers' side.

## Single Points of Failure: Concentration Risk at ASML, Shin-Etsu and IBIDEN

Concentration is the reason this cycle's bottlenecks behave differently from ordinary semiconductor cycles. When a single point of that kind fails to expand fast enough, the shortfall does not stay local: it propagates down a causal chain — tool shortfall → slower cleanroom ramp → fewer packaging lanes → longer allocation for everyone downstream.

### ASML: The Supplier-Declared Shortfall That Gates Every Ramp

The most consequential statement in this entire chain came not from a chipmaker but from a toolmaker. On 14 October 2026, ASML reported €11.7 billion in Q3 sales and €5.0 billion in net income, and stated that its planned supply for 2027 and 2028 "will not fully meet the demand of our customers" [S2]. This is a supplier voluntarily declaring a multi-year shortage — the commercial equivalent of a weather warning. ASML is the sole producer of EUV and High-NA lithography systems; every leading-edge logic node (TSMC N3, N2, A16; Samsung SF2; Intel 14A) and, crucially, much of the advanced-packaging expansion that depends on new cleanroom equipment, sits behind ASML's allocation decisions.

The mechanism matters more than the headline. Equipment lead times run well ahead of fab construction: Unimicron's chairman has warned of equipment lead times of up to 30 months for substrate production machinery [S51]. If a substrate maker orders tools in late 2026 and waits up to two and a half years for delivery, the capacity that could relieve a 2027 bottleneck physically cannot arrive before mid-2028 — matching IBIDEN's Ono ramp start in Q1 2028 and Unimicron's full run-rate only in mid-2028 [S45]. ASML's declared shortfall therefore does not merely slow TSMC's N2 ramp; it retroactively caps every downstream expansion whose equipment order book sits in the queue.

A single-source monopolist with a multi-year order book has neither the incentive nor the physical ability to over-deliver rapidly. This report assigns roughly 60% probability that EUV/High-NA equipment remains a binding constraint into 2028, and flags ASML's January 2027 Q4 results as the decisive checkpoint: if the shortfall language is reiterated, the scenario-one probability hardens; [S1]

### TSMC as the Sole Qualified Leading-Edge Source

The second concentration layer is geographic and corporate at once.

This converts every downstream shortage into TSMC pricing power and every customer roadmap into TSMC queue position. The single-source structure also explains why packaging tightness persists: no competitor can arbitrage TSMC's CoWoS queues, and the overflow beneficiaries (ASE, Amkor with its +300% expansion by end-2028, Intel as a packaging alternative) all ramp on timelines dated after or late within the horizon [S45].

Concentration risk at the leading edge therefore most likely persists through the horizon, making TSMC the choke point's landlord in either leading scenario.

### Shin-Etsu, SUMCO and the Quiet Materials Concentrations

The least visible single points of failure sit in materials. An EUV resist allocation problem would be invisible in any utilization statistic until it suddenly stopped a scanner-fed fab; there is no second source of equivalent scale to absorb a shortfall. The report treats photoresist as a low-probability, high-impact node: unlikely to bind in the base scenarios, but a genuine tail risk that would instantaneously convert scenario three into scenario one.

Silicon wafers present the mirror-image concentration. Two suppliers near full utilization with one of them deliberately volume-constraining is the precondition for a wafer allocation episode should leading-edge wafer starts accelerate under scenario one.

### IBIDEN, Unimicron and the ABF Single-Source Web

Substrates illustrate concentration at its most physically stubborn. Above them sits Ajinomoto — literally the inventor and sole volume supplier of the ABF film itself — which raised film prices by 30% in 2026 [S31]. Three companies, one film chemistry, and a customer (NVIDIA) that has already locked all three plus Amkor into multibillion-dollar capacity reservations [S45].

What makes this concentration durable rather than cyclical is the relief calendar: IBIDEN's Ono plant ramps from Q1 2028 and Unimicron reaches full run-rate only mid-2028, while Unimicron's chairman publicly warns of a 20% shortfall in glass fiber cloth, CCL and ABF supply in 2027 and equipment lead times up to 30 months [S51]. In other words, the industry's own second-largest supplier is on record saying 2027 supply will fall 20% short of demand before the new capacity even lands.

The propagation path is textbook: Ajinomoto film scarcity → substrate makers cannot debottleneck without new machinery → the machinery itself waits in ASML-class equipment queues → new fabs (IBIDEN Ono, Unimicron KF) start a year late → packaging capacity at TSMC is capped by substrate input scarcity, not by TSMC's own capital. The counter-case — that NVIDIA's reservations themselves guarantee supply for the marginal AI package, leaving only non-AI buyers squeezed — is plausible;

### Why Concentration Explains the Persistence Asymmetry

The deepest lesson of the evidence base is the asymmetry between commodity and capability bottlenecks. Concentration is the mechanism behind the asymmetry: commodity capacity has many owners who all expand at once into high prices, overshooting collectively; capability capacity has one or two owners whose expansion is gated by their own single-source suppliers, so supply responses arrive late, sequentially, and perpetually behind demand.

Every node examined in this chapter — ASML tools, TSMC packaging, IBIDEN substrates, Ajinomoto film, Shin-Etsu resist, the SUMCO/GlobalWafers duopoly — sits in the capability category. The concentrated nodes cannot collectively overshoot because they cannot collectively expand fast enough to overshoot; their customers' record capex queues behind equipment lead times of up to 30 months [S51].

### Synthesis: Four Nodes, One Verdict

Read together, the four concentration nodes form a single causal loop rather than four independent risks. TSMC's sole-source status converts that cap into allocation rather than price competition; IBIDEN's and Unimicron's post-2027 relief calendar [S51] keeps the substrate input to packaging scarce through the entire horizon; and Shin-Etsu's undated resist expansion plus the SUMCO/GlobalWafers volume discipline means even the inputs' inputs cannot surge. Each node individually raises the odds of persistence;

## The Wildcards: Export Controls, Rare Earths and the November 2026 Cliffs

The gap between what officials say and what the Federal Register contains is itself the risk: two governments have each signaled forbearance while leaving the legal instruments to expire by default.

This chapter argues that these cliffs matter, but asymmetrically and mostly through one channel. Either way, the November dates compress an extraordinary amount of scenario-shaping information into a two-day window.

### The Two Clocks and What Each Actually Controls

The BIS Affiliates Rule suspension was published in the Federal Register on 12 November 2025 as a one-year suspension of the expansion of end-user controls to affiliates of certain listed entities [S14]. If it lapses on 9 November 2026 without extension, the default expansion of Entity List reach to majority-owned subsidiaries and affiliates snaps back into force. [S18] A snap-back of affiliate controls would broaden the perimeter of that restriction to entities currently transacting in the gray zone — traders, distributors, and indirectly-owned subsidiaries — tightening de facto enforcement on tool, component and material flows into China's mature-node complex.

The critical question is how much margin is left to tighten. On this reading, an Affiliates snap-back mostly accelerates a bifurcation that is already happening — China sourcing domestically, non-China buyers sourcing from UMC, GlobalFoundries and TSMC's mature lines — rather than creating a new physical shortage.

The counter-argument, and the reason the lapse is not pure noise, is second-order: enforcement ambiguity freezes transactions. The most damaging feature of the Affiliates Rule was never its formal scope but the compliance chill around it — banks, shippers and distributors de-risking ahead of clarity. The mature-node segment would move from "tight but not scarce" toward episodic allocation, raising the probability of a seventh de facto bottleneck without changing the ranked top six.

### Rare Earths, Gallium and Germanium: The Materials Propagation Path

The propagation into the semiconductor chain runs through three distinct routes.

First, the direct materials route: gallium and germanium feed compound semiconductors (GaAs, GaN, Ge-based optics) and, less directly, some specialty-gas and precursor chemistries. CSIS analysis of the rare-earth and magnet restrictions emphasizes the threat to US defense supply chains [S73], and the defense exposure matters for semiconductors because compound-semiconductor and RF capacity sits disproportionately in defense-adjacent lines with thin inventory buffers. This is a real but narrow channel for the AI bottleneck question — it does not touch CoWoS, HBM or leading-edge logic directly.

Second, the magnet route into equipment and facilities: rare-earth permanent magnets are embedded in the motors, vacuum pumps, robotics and precision motion stages that etch, deposition and lithography tools depend on, and in the cleanroom material-handling systems every new fab requires.

The lesson buyers have internalized is that Chinese export volume is policy-contingent regardless of formal suspension status. That is why the pause's mere existence — not just its lapse — has already induced inventory building and dual-sourcing across the materials chain, visible in substrate customers "rushing to lock in ABF substrate LTAs" and in the price telemetry: Ajinomoto's 30% ABF film price increase [S31] partly reflects buyers paying scarcity premiums for insurance rather than current-period shortage.

### Shock Versus Noise: Assigning the Probabilities

The joint structure matters more than either cliff alone. The probability that China extends the rare-earth pause is similar or slightly higher, because a unilateral reinstatement while the US side holds the truce would forfeit Beijing's leverage — the two control regimes are explicitly adversarial instruments, with MOFCOM and BIS each opposing the other and both constraining the same downstream segments. Mutual extension is therefore the modal branch, and in that branch the November cliffs resolve as noise: headline risk for a week, no capacity impact.

The dangerous branches are two. Notably, a rare-earth reinstatement does not create oversupply anywhere — it constrains supply — so the escalation branch raises the probability of severe tightness, not correction.

One further asymmetry deserves emphasis: the cliffs bind hardest on the loose segments, not the tight ones. CoWoS, HBM and leading-edge logic are capacity-constrained regardless of trade policy; their bottlenecks are made in Hsinchu, Icheon and Veldhoven, not Washington or Beijing. Mature nodes, mainstream consumer silicon, OSAT conventional lines and commodity materials are where export-control friction can convert slack into scarcity.

### The Observation Calendar After November

Four dated events will reveal which branch the world took. First, the Federal Register itself in November 2026: publication of an Affiliates Rule extension before 9 November, and a MOFCOM notice extending Announcement No. 70 before 10 November [S14][S15][S16]. Fourth, NVIDIA's GTC in March 2027, where the Rubin Ultra HBM configuration resolves — an event nominally about demand, but one whose interaction with the geopolitical branch matters: in the escalation branch, an 8-Hi switch becomes more likely because packaging-yield and materials constraints bite harder, compounding the memory makers' allocation calculus. [S9]

The honest bottom line: through end-2027 the geopolitical wildcards are most likely a sideshow to the capacity story — the binding constraints are CoWoS/SoIC, HBM4 and substrates, and they will remain binding because relief is dated 2028.

## Scenario One — AI-Led Broad Tightness (38%): Packaging, HBM, Logic and Equipment All Binding

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/semichain-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

Scenario One is the modal path because it is the one the supply chain's own actors are already describing in the present tense. This is not a forecast requiring a new shock or a new demand inflection; it is the continuation of the current allocation regime, plus one supplier-declared equipment shortfall that propagates the tightness upstream from packaging into logic.

### Why the modal scenario is a continuation, not a break

The single most important piece of evidence for this scenario is that the constraint is already binding at the top of the chain and is described as such by the company that owns the capacity. On 16 July 2026, TSMC's CEO said on the record that packaging capacity is: [S1]

> "so tight that now it's limiting my customers' growth"

This is not a trade-press estimate or a leaked figure — it is the constrained supplier itself confirming that demand exceeds available CoWoS/SoIC capacity and that the shortfall is capping output for its customers.

The second anchor is that the second-most-constrained segment shows the same pattern of sold-out allocation rather than price clearing. When inventory sits below ten days and books are full a year forward, the market is not approaching equilibrium; it is rationing.

The base rates support persistence.

### The coupling mechanism: how packaging tightness becomes broad tightness

The distinctive claim of this scenario is not that two segments stay tight — that would be Scenario Two — but that tightness propagates into leading-edge logic and equipment through two identifiable channels.

**Channel one: ASML's supplier-declared shortfall gates every ramp.** On 14 October 2026, ASML stated that its planned supply: [S2]

The critical feature of this statement is its position in the chain: ASML is the sole EUV supplier, and TSMC is its customer — the tool shortfall lands directly on the foundry whose capex is funding the packaging relief. The leading-edge constraint therefore propagates through tool supply rather than cleanroom space: TSMC has the money and the shells (three new N3 fabs, reversing its post-peak practice), but the equipment to fit them arrives slower than the demand.

**Channel two: HBM wafer allocation starves conventional memory.** Every one of those wafers is a conventional DRAM wafer that is not being built. The tightness clears through price and allocation rather than new capacity — new greenfield DRAM capacity cannot land inside the horizon. CXMT, having doubled its DRAM revenue share to roughly 10% by Q2 2026 [S24], absorbs spillover demand at the fringe of the constrained market, particularly in China where entity-list and export-control walls already segment it from the global allocation system — a structural, not cyclical, share gain that marginally loosens global conventional-DRAM tightness but nowhere near enough to close a 10%-plus undersupply.

Put together, the mechanism is a closed loop: accelerator demand pulls packaging → packaging relief requires new tool install → ASML says it cannot ship enough tools on time → the relief ramps slip while demand compounds → scarcity carries into N2 logic and conventional DRAM in parallel.

### Who does what: the actors' behavior under this scenario

Each major actor's rational strategy in this scenario reinforces the tightness rather than relieving it:

- **NVIDIA** locks multi-year reservations rather than buying spot.
- **TSMC** allocates rather than prices to clear, and spends record capex into a tool wall.
- **ASML** allocates tools, extending its backlog;
- **ASE, Amkor and Intel** capture CoWoS overflow demand as constrained TSMC capacity pushes orders outward through 2027. [S1]

### Judgment and falsification criteria

1. TSMC or a major customer publicly states that CoWoS/SoIC allocation still limits output (the 16 July 2026 statement's counterpart on a 2027 earnings call or equivalent), **AND** [S1]

It falsifies if either condition fails: packaging tightness publicly eases, or HBM4 supply catches up (lead times under ~20 weeks with inventories rebuilding above 10 days). The observation calendar is concrete: TSMC's January 2027 Q4 call for 2027 capex guidance and packaging commentary; [S48] and TrendForce quarterly CoWoS gap and HBM ASP prints.

Two additional telemetry series discriminate this scenario from Scenario Two. that is precisely the accelerator BOM's growth rate.

### The strongest counterargument, answered

The best case against this scenario deserves a fair hearing: the CoWoS supply–demand gap is already narrowing from ~20% at mid-2026 to ~10% by end-2026 [S20]; Unimicron's KF expansion adds substrate capacity from Q2 2027; [S51] and TSMC's Q4 2026 guidance implies enormous wafer supply growth.

The response is threefold. Third, the flagship new substrate volume — IBIDEN Ono at 3x capacity under NVIDIA's reservation — ramps from Q1 2028, and Unimicron reaches full run-rate only mid-2028; [S43]

One genuine wildcard cuts the other way: the reported Rubin Ultra redesign.

a clean truce extension is the neutral-to-supportive outcome for broad tightness.

### Defending 38%

The 8-point gap between them is a judgment about tool supply: ASML's own words make propagation the base case, but one supplier's capacity plan, revised quarterly, is a thinner foundation than a decade of base rates.

## Scenario Two — Packaging-Only Bottleneck (30%): CoWoS/SoIC and Substrates as the Single Binding Constraint

This chapter argues that scenario, specifies how it would be recognized, and names who wins if it materializes.

### The Asymmetry That Defines This Scenario: Relief Arrives Unevenly

The single most important structural fact separating Scenario Two from Scenario One is the calendar of new capacity. Across the chain, announced additions cluster either inside the window or just outside it — and packaging sits almost entirely on the wrong side of that line.

Consider HBM first. Three suppliers, three separate capex programs, and a documented share race in which SK Hynix's HBM revenue lead narrowed from 58% in Q1 2026 to 50% in Q2 while Samsung announced HBM4 mass production [S43]. That is what a segment approaching balance looks like: rivals gaining share on the leader, which is only possible when the leader cannot absorb all demand. If Samsung's and Micron's HBM4 ramps execute on their current trajectories through 2027, HBM4 lead times could plausibly compress below the 20-week threshold that defines relief in this scenario's judgment criteria. [S51]

Now compare packaging and substrates. And the substrate layer beneath packaging is worse: IBIDEN's Ono plant ramps from Q1 2028, Unimicron reaches full run-rate only in mid-2028, and Amkor's expanded capacity arrives at +300% by end-2028 [S45]. Unimicron's chairman has publicly warned of equipment lead times up to 30 months and a 20% shortfall in glass fiber cloth, CCL and ABF supply in 2027 [S51]. The mechanism is straightforward: packaging cannot expand faster than its substrate input, and substrate capacity additions ordered in 2026 with 30-month equipment lead times physically cannot produce wafers before late 2028. [S51] Packaging is therefore capacity-frozen through 2027 regardless of how much money TSMC commits. [S48]

Scenario Two is essentially that pattern repeating with the lag shifted onto substrates.

### Why Packaging Stays Binding Even as Memory Loosens

The strongest objection to this scenario comes from the demand side: if HBM4 is relieved, doesn't that signal accelerator demand softening, which would relieve packaging too? This is the steelman of Scenario One and it deserves a direct answer.

The answer is that HBM and packaging respond to different supply dynamics even under identical demand. HBM tightness in 2026 is substantially an allocation phenomenon — memory makers choosing to run DRAM wafers through HBM lines, crowding out conventional DRAM and pushing 4Q26 contract price forecasts to +10-15% QoQ for DRAM and +15-20% for NAND [S25]. That tightness can ease through supply-side substitution: Samsung and Micron converting more capacity, or NVIDIA accepting a lower-HBM configuration. Fewer HBM stacks per package does not reduce the number of packages needed; it may even increase packaging demand per unit of compute by lowering per-package yield risk. That is the decoupling mechanism at the heart of Scenario Two: NVIDIA can cut HBM intensity to fit memory supply, but it cannot cut packaging intensity, because CoWoS is the package.

The second reason packaging persists is concentration. Packaging lines need lithography, deposition and etch tools like any fab;

Third, the substrate layer acts as a hard floor on packaging supply.

### Judgment Criteria and How This Scenario Resolves

1. **CoWoS/SoIC remains binding**: lead times exceed 40 weeks per a named industry tracker (Silicon Analysts or TrendForce), or TSMC confirms on an earnings call that packaging still limits customer growth — a direct echo of the July 2026 statement. [S47]

Observable signposts on the path: TrendForce's quarterly CoWoS gap prints (a gap stuck near 10% through 2027 rather than closing [S20]); the January 2027 TSMC Q4 call's packaging commentary and 2027 capex guidance; [S48] If Rubin Ultra ships 8-Hi, Scenario Two's probability conditional on that fact rises sharply;

### Who Benefits: The Overflow Economy

If packaging is the last binding constraint, the winners are the companies that own alternative packaging capacity or locked-in substrate allocation — an "overflow economy" forms around the choke point.

**ASE Technology and Amkor** are the primary beneficiaries. Amkor, party to NVIDIA's multibillion-dollar capacity agreements alongside IBIDEN and Unimicron [S45], converts overflow demand into pricing power and LTA-secured utilization.

Unimicron reports customers rushing to lock in ABF substrate long-term agreements — in a packaging-only world, those LTAs function as allocation insurance, and the 20% 2027 materials shortfall Unimicron itself warns of [S51] becomes revenue per unit rather than lost volume.

**TSMC itself** is the paradoxical winner: it owns the constraint, so it captures the allocation premium and can price packaging into foundry deals. **Intel** is the wildcard beneficiary — as a CoWoS alternative with its own packaging ambitions [S47], a persistent packaging-only bottleneck is the strongest possible commercial argument for its advanced packaging services.

The losers are accelerator buyers without reservations — anyone not NVIDIA, in practice — and second-tier AI chip designers who find wafer capacity available but no packaging lane to put it in.

## Scenario Three — Balanced Chain (10%) and Scenario Four — AI Air Pocket Correction (12%), Plus Mixed Outcomes (10%)

They are residual not because they are unimportant — the air pocket in particular is the scenario that would strand billions of dollars of capacity being reserved right now — but because each requires something the current evidence does not yet show: a capacity surge arriving ahead of schedule, a demand break that has no precedent this early in an AI-driven allocation regime, or a partial resolution that fails every clean test. This chapter states what each scenario requires, who is exposed, how it would be observed, and why the probabilities are what they are.

### Scenario Three — Balanced Chain (10%): Record Capex Actually Clears the Gaps

The balanced-chain world is one in which the supply response arrives on time or early, and demand, while strong, is met rather than rationed. All three conditions must hold jointly;

The steelman for the balanced chain is real and worth taking seriously.

The case against the balanced chain is structural, and it runs through two dated facts. First, ASML said on 14 October 2026 that its planned supply for 2027 and 2028 "will not fully meet the demand of our customers" [S2]; because ASML is the sole EUV supplier and TSMC's leading-edge constraint propagates through tool supply rather than cleanroom space, every downstream ramp — N2, CoWoS, HBM-adjacent logic — inherits this gate. Second, the substrate relief is dated after the horizon: IBIDEN's Ono ramp begins Q1 2028, Unimicron's KF expansion reaches full run-rate only mid-2028, and Amkor's 300% growth lands end-2028 [S45]. Unimicron's chairman warned on 20 October 2026 that substrate-making equipment now carries lead times of up to 30 months and that glass fiber cloth, CCL and ABF could see a 20% supply shortfall in 2027 [S51]. A chain cannot balance while its packaging inputs are still short 20%. [S20]

There is one narrow path in, and it runs through HBM rather than packaging. But even in that world, CoWoS and substrates remain constrained, so the full balanced-chain conjunction still fails.

Who benefits if it happens: TSMC's customers broadly — the second-tier accelerator vendors currently locked out of CoWoS allocation, consumer-electronics makers squeezed by DRAM allocation, and CXMT, whose reported ~10% DRAM share gain in 2026 [S24] came amid tightness and would face renewed price pressure. ASML would see backlog stretch out; IBIDEN, Unimicron and Amkor would carry capacity reserved against NVIDIA commitments into a softer market.

### Scenario Four — AI Air Pocket Correction (12%): The 2019/2023 Echo Arrives Early

Resolution requires TrendForce (or equivalent) printing DRAM and/or HBM contract prices down more than 15% YoY in Q4 2027, or at least two major memory makers announcing capex cuts. [S25] Probability: 12%.

The base-rate case for a correction deserves more respect than the consensus gives it. A capex pause at a handful of hyperscalers, a monetization disappointment at the large AI labs, or a financing squeeze in the neocloud segment propagates into a bill of materials with almost no diversification. The exposure is compounded downstream: NVIDIA has made multibillion-dollar reservations at IBIDEN's Ono plant, at KYEC, and across Amkor, SPIL and Unimicron [S45] — capacity commitments that would strand if demand broke, converting a demand shock into a supplier solvency question.

The case against a correction inside this window is the inventory and price telemetry, which points the other way with unusual force. nothing in the current data shows even the beginning of a build. And demand-side visibility is unusually long: HBM is reported sold out into 2027 (a claim that, while single-sourced and uncorroborated, is at least directionally consistent with the sub-10-day inventories), and TSMC described leading-edge demand as "extremely robust" even while being "prudent" on 2027 [S18].

A joint lapse would reinstate the rare-earth controls alongside the gallium/germanium prohibition regime, raising costs and disrupting logistics across equipment, substrates and mature-node supply. Note, though, that this route is more likely to produce a mixed outcome — supply-side disruption plus intact AI demand — than a clean oversupply flip; a pure correction still requires the demand leg to break.

TSMC would see CoWoS utilization fall from full, though its N2/N3 logic franchise is more diversified. The beneficiaries would be buyers: server OEMs, consumer electronics makers, and the second tier of accelerator vendors who today cannot get allocation at any price.

### Mixed Outcomes (10%) and Why the Split Is 38/30/10/12/10

The mixed bucket exists because the scenario criteria are conjunctions, and conjunctions fail in more ways than they succeed. Neither scenario resolves cleanly.

The Rubin Ultra fivefold ambiguity cuts across all of this: a 12-Hi confirmation pushes mass toward Scenario One; [S43] the 8-Hi redesign pushes mass from One toward Two and slightly toward Four (a demand signal that NVIDIA itself is hitting packaging walls is a leading indicator of a broader air pocket).

## The Ranked Bottleneck List: Six Segments, Probabilities, Severity and Who Benefits

The ranking is cumulative over the forecast window: a segment ranks above another if it is both more likely to bind and more severe when it does.

### The Master Table

| Rank | Segment | P(binding before end-2027) | Expected duration | Severity (price / lead time / allocation) | Capacity owners | Beneficiaries |
|---|---|---|---|---|---|---|
| 1 | Advanced packaging (CoWoS/CoWoS-L/SoIC) | ~85% | Binding since mid-2023; [S1] through end-2027 | Extreme / Extreme / Allocation-only | TSMC | ASE, Amkor, Intel, Broadcom-adjacent fabless with reserved lanes |
| 2 | HBM (HBM3E/HBM4) | ~85% | Sold out into 2027; binding through 2027 | — | SK Hynix (50% revenue share), Samsung (33%), Micron (18%) [S43] | All three HBM makers; NVIDIA via secured allocation |
| 3 | ABF substrates and upstream materials | ~75% | Tight now; | — | — | IBIDEN, Unimicron, Kinsus via LTA lock-ins |
| 4 | EUV/High-NA equipment | ~60% | — | High (price) / High / Rationed allocation | ASML (sole source) | ASML margin; incumbent tool holders |
| 5 | Conventional DRAM (crowding-out) | ~55% | Through at least 1H27 | — | Samsung, SK Hynix, Micron | Memory trio; hurts consumer/auto buyers |
| 6 | Leading-edge logic foundry (N3/N2, effective single-source) | ~50% (conditional) | 2H27 if tool supply gates the ramp | — | TSMC; Samsung SF2 unqualified | TSMC pricing; |

### #1 Advanced Packaging: CoWoS/CoWoS-L and SoIC

Packaging is the chain's most reliably binding constraint, and uniquely it is binding by the supplier's own admission rather than by third-party estimate. On 16 July 2026 TSMC's CEO said packaging capacity is "so tight that now it's limiting my customers' growth" [S1] — the clearest possible statement that demand already exceeds capacity. The report assigns ~85% probability that demand exceeds capacity at some point before end-2027 and expects the constraint to persist the entire window; [S1]

Severity is extreme on all three axes. Mechanically, allocation-only access means accelerator output is decided by packaging lanes, not wafer starts: a customer with N2 wafers and no CoWoS lane ships nothing. That is why NVIDIA has locked multibillion-dollar reservations and a claimed 2.5x capacity agreement across IBIDEN, Unimicron and Amkor [S45]. ASE and Amkor capture overflow, with Amkor planning +300% capacity by end-2028 including expanded US operations under the NVIDIA supply-chain agreement [S45];

### #2 HBM / HBM4

Revenue shares in Q2 2026 were SK Hynix 50%, Samsung 33%, Micron 18% [S43]. the constraint only clears in the air-pocket tail.

Beneficiaries are the three suppliers themselves, with SK Hynix holding the largest HBM4 allocation premium; NVIDIA benefits relative to rivals precisely because it has secured allocation ahead of them. Losers are conventional-DRAM buyers, which brings us to #5.

### #3 ABF Substrates and Upstream Materials

Substrates are the most durable constraint on this list because the relief is dated after the horizon. Unimicron's chairman has publicly warned of up to 30-month equipment lead times and a 20% shortfall in glass fiber cloth, CCL and ABF supply in 2027 [S51] — a rare supplier-declared shortfall, echoing ASML's. The report assigns ~75% probability of binding before end-2027; the discount to packaging/HBM reflects genuine substitution at the margin (larger substrates can be redesigned, BT can absorb some sockets) and the air-pocket scenario in which capacity built on NVIDIA reservations is stranded [S45]. Beneficiaries: IBIDEN, Unimicron and Ajinomoto via LTA lock-ins as customers rush to secure volume [S53].

### #4 EUV/High-NA Equipment

The equipment segment differs from the three above: it is a supplier-declared, forward-looking constraint rather than a current one. On 14 October 2026 ASML stated that its planned supply "will not fully meet the demand of our customers" for both 2027 and 2028 [S2]. This matters because it is the gating variable for every downstream ramp: leading-edge logic capacity growth, packaging tooling and memory expansion all route through ASML as sole EUV/High-NA source. The report assigns ~60% probability that tool supply becomes a binding constraint on specific customer ramps before end-2027 — lower than the segments above because "binding at the margin" (some customers' ramps slip) is a weaker condition than market-wide scarcity, and ASML can still grow shipments substantially while declaring a shortfall. [S1] Severity is high on price (ASML holds pricing power) and on allocation, but the pain lands as delayed ramps rather than absent chips — one fab quarter of slippage, not a missing product. Beneficiaries: ASML's backlog and margin; incumbent tool holders whose existing installed base appreciates in a rationed environment. The single observation that would change this view is ASML's Q4 2026 results in January 2027 — reiteration confirms, dropping the statement downgrades the call. [S34]

### #5 Conventional DRAM: The Crowding-Out Bottleneck

Mainstream DRAM is tight for a second-order reason: HBM wafer allocation is crowding out conventional supply. If HBM4 additions from Samsung and Micron [S43] outpace accelerator demand, conventional DRAM supply rebounds quickly. But the mechanism cuts the other way too: as long as HBM4 remains sold out, every additional HBM wafer is a conventional wafer withdrawn, and sub-10-day inventories leave no buffer. [S43] Beneficiaries: Samsung, SK Hynix and Micron, who enjoy both HBM premiums and conventional price inflation simultaneously. Losers: PC, smartphone, auto and industrial buyers, for whom the AI boom arrives as a price shock.

### #6 Leading-Edge Logic Foundry: Conditional Single-Source

Leading-edge logic ranks last not because it is loose but because its binding status is derivative — conditional on packaging coupling and tool supply. The constraint propagates through tool supply rather than cleanroom space: TSMC targets 22% 2nm and 16%+ 3nm capacity boosts by mid-2027 [S44], and three new N3 fabs could clear gaps by late 2027 in the balanced-chain scenario — unless ASML's declared shortfall gates the tooling. Beneficiaries: TSMC's pricing power in allocation; Samsung Foundry if it qualifies an external 2nm customer by mid-2027, which would be the single most competitive-changing event in this segment. [S1]

### Who Is Left Off the List, and Why

Three exclusions deserve explicit defense. Mature-node foundry (SMIC, UMC, GlobalFoundries) is repricing upward from the 2024 trough but US NAICS 3344 utilization at 76.51% (September 2026) — up 2.787pp YoY but far below the 92.195% February 2022 peak — shows no chain-wide scarcity; OSAT conventional capacity benefits from CoWoS overflow rather than binding independently — ASE and Amkor are on the right side of this list, not on it [S47].

## Binary Forecast Ledger: Twelve-Plus Verifiable Calls with Resolution Criteria

This chapter converts the report's scenario architecture into thirteen discrete, falsifiable binary calls. Each is stated as a concrete threshold with a named resolution source and a resolution window; A call resolves YES only when the named source prints the threshold; a source staying silent resolves nothing and the call is graded against the best available named alternative.

### Packaging and Logic Capacity Calls

This report estimates **70% YES**. The mechanism: even if capacity reaches the optimistic 2027 prints (Call 2), demand from Rubin-class and custom ASIC accelerators has grown faster than capacity for eleven consecutive quarters, and substrate relief is dated after the horizon — IBIDEN Ono ramps Q1 2028 and Unimicron reaches full run-rate only mid-2028 — so packaging remains the last constraint to clear. [S1]

TSMC discloses no CoWoS capacity figure, so resolution must come from third-party consensus or a rare company disclosure. sources: TrendForce quarterly CoWoS estimates, with TSMC's January 2027 Q4 call commentary as corroborating color. [S48] This report estimates **55% YES**.

This report estimates **45% YES**. Until it happens, TSMC remains the sole qualified leading-edge source, which converts any leading-edge tightness directly into allocation rather than price competition — the mechanism behind Chapter 9's conditional sixth-ranked bottleneck.

### Memory, HBM and the Rubin Ultra Hinge

a NO is the largest single release valve for the memory chain.

This report estimates **60% YES**.

**Call 6 — Conventional DRAM contract prices remain positive year over year in 4Q27.** This report estimates **55% YES**. The crowding-out mechanism — Samsung and SK Hynix allocating DRAM wafers to HBM lines starves conventional supply — supports persistence, and memory-maker inventories below 10 days against downturn norms of 10-15+ weeks mean any oversupply flip needs a long inventory rebuild first.

### Equipment, Materials and Policy Calls

The baseline statement, made 14 October 2026 with Q3 results, is that planned 2027 and 2028 supply "will not fully meet the demand of our customers". [S2] Resolution: ASML's Q4 2026 earnings release and call, January 2027 [S34]. This report estimates **75% YES**. The mechanism: ASML's constraint is its own upstream supply chain and output capacity, which cannot materially change within one quarter; dropping the statement would signal either demand deterioration (bearish for the whole chain) or a supply breakthrough with no announced source.

**Call 10 — China extends the rare-earth export-control pause beyond 10 November 2026.** A NO here compounds a NO on Call 9 into the escalation branch of the wildcard set, propagating into specialty gases, magnets and wafer logistics.

### Macro and Substrate Telemetry

This report estimates **30% YES**. The mechanism: the series is dominated by broad-based (largely non-AI) US semiconductor manufacturing, so it registers chain-wide scarcity only with a lag and only if tightness spreads well beyond packaging and HBM — which is precisely what distinguishes Scenario One from Scenario Two. the more likely path is continued grinding gains from the low-70s trough as new US capacity ramps.

IBIDEN, Unimicron and Ajinomoto hold the constrained capacity and the pricing power; NVIDIA has pre-committed to it via reservations.

Resolution: TSMC's January 2027 Q4 2026 earnings call, where 2027 capex guidance is given [S17]. The mechanism: TSMC is capacity-bound, not demand-bound, in packaging and leading edge; a capex guide-down would require either demand deterioration or an explicit tool-availability ceiling (ASML's declared shortfall ), and even the tool-constrained case implies spending the same capital over a longer window rather than less. This call is a demand-health proxy: it resolves NO only in the early innings of an air pocket.

### How the Ledger Maps to the Scenarios

Read as a panel, the thirteen calls form a decision tree with identifiable signatures.

The ledger's honest weakness is its dependence on third-party estimates that the primary companies refuse to confirm: TSMC discloses neither CoWoS capacity nor lead times, Samsung confirms no 2nm yield figure [S21], and NVIDIA has not resolved the Rubin Ultra configuration. Where a call can only be graded against unconfirmed trade estimates, that is flagged in the resolution criteria;

## Key Official Indicators and What They Signal for the Bottleneck Question

The official statistical series stored for this report — Federal Reserve industrial production and capacity utilization for NAICS 3344, and the BEA real trade series — are the only chain-wide, methodology-consistent measurements available at monthly and quarterly frequency. Used correctly, however, they serve three purposes in this forecast. they confirm that supply is expanding at a record pace and still being outpaced in AI-exposed segments;

### The Utilization Number That Rules Out a Broad Shortage

Capacity utilization for Semiconductors and Other Electronic Components (NAICS 3344) stood at **76.51% in September 2026**, up 2.787 percentage points from 73.723% a year earlier. The stored five-year window runs from a trough of 71.096% (March 2026) to a peak of 92.195% (February 2022) [S3].

Nothing in the current aggregate resembles that. TSMC's CEO saying on 16 July 2026 that packaging capacity is "so tight that now it's limiting my customers' growth" [S1];

The threshold question follows directly.

### Production at a Record High While Segments Still Starve

The analytical significance is the divergence between the two series. Output at an all-time high plus utilization at only the 34th percentile of its range means capacity is being added at least as fast as production is rising — the denominator is growing too. That combination — record supply growth and persistent specific scarcity — is the statistical signature of a demand curve outrunning even aggressive capacity expansion in particular lanes, rather than a supply-side failure.

For the forecast horizon, the production series supplies two discriminating thresholds.

### The Trade Series and the Control-Risk Channel

These are economy-wide series and cannot isolate semiconductors; their value here is as a stress gauge for the geopolitical transmission channel analyzed in the wildcard chapters.

An escalation severe enough to move semiconductor-linked trade materially would likely push the aggregate import growth toward or below its p10 within two quarters of the cliff — a detectable signature.

### Reading the Dashboard: What Each Print Settles

- **NAICS 3344 utilization (monthly, FRED)**: settles whether scarcity is broad or narrow. [S3]
- **NAICS 3344 industrial production (monthly, FRED)**: settles whether record supply growth continues. [S4]
- **Real exports/imports (quarterly, FRED)**: settles whether the November 2026 geopolitical cliffs propagated. a p10-below import print within two quarters of a lapse would mark the escalation path that converts the wildcard chapter's tail risks into the dominant driver.

Two honest caveats close the analysis. First, the aggregates lag and dilute: TSMC's CoWoS lanes are in Taiwan and never enter the US NAICS series directly, so packaging tightness will be visible in these numbers only via knock-on effects through US assembly, test and component production. The decisive segment-level telemetry remains the company and tracker sources — TrendForce's quarterly CoWoS gap and HBM ASP prints [S20], TSMC's January 2027 call [S17], ASML's Q4 2026 results, and NVIDIA's GTC confirmation of the Rubin Ultra configuration in March 2027 [S6]. The official series confirm the frame; they do not time the turns. Second, the stored history's p10-p90 bands were computed on a window dominated by one pandemic cycle and one AI cycle; treat them as calibration scaffolding for thresholds, not as precise probabilities. What the official data do establish firmly, as of this report's as-of date, is the central paradox that organizes the whole forecast: a chain producing at an all-time high, at barely one-third-of-range utilization on average, in which the fastest-growing segment's customers are told by the world's largest foundry that its packaging capacity is limiting their growth [S1].

## Risks, Second-Order Effects and Decision Implications for Buyers, Suppliers and Policymakers

The chapters above rank the bottlenecks and assign them probabilities. This chapter turns to the darker half of the ledger: the second-order consequences that follow once packaging and HBM are genuinely scarce, the fragilities that concentration creates, and what each class of actor should actually do before the calendar closes the windows that remain open.

### Memory Crowding-Out: The Inflation the Rest of the Economy Inherits

The most underpriced risk in the chain is that the fight for HBM wafer allocation quietly reprices every product containing a memory chip. Each of those wafers is a wafer not making conventional DDR5 or LPDDR for servers, PCs and phones. The pass-through is not capped by demand weakness — it is capped only by long-term agreements, which limit how fast contract prices can move for the largest buyers and therefore concentrate the sharpest increases on smaller ones [S26].

The buffer that normally absorbs such moves does not exist. A buyer of PC memory has no inventory to draw down and no alternative supplier to switch to; DRAM is an oligopoly with Samsung at 38% revenue share, SK Hynix 25% and Micron 24% [S24]. The second-order effect is therefore a redistribution of margin from downstream assemblers — PC OEMs, handset makers, automotive tier-1s, none of which bid for HBM allocation — to three memory makers. PC and phone makers will either accept bill-of-materials inflation or cut configurations; carmakers will thin local storage and delay memory-rich feature sets. TrendForce's August 2026 analysis puts DRAM and NAND at roughly 68% of the memory market's value, underlining how broad the price exposure runs [S27].

The conventional-DRAM tightness also produces a geopolitical beneficiary. CXMT, which Counterpoint put at 10% of DRAM revenue by Q2 2026, grows fastest precisely because the incumbents' wafers are pulled into HBM — a structural consequence of the crowding-out mechanism. [S24]

A steelman of the benign view deserves an answer. One could argue the crowding-out is self-limiting: as 4Q26 price momentum reaches roughly 20% QoQ DRAM increases [S42], conventional buyers cut demand, and the market clears by price rather than shortage.

### One Decision, Fivefold Swing: The Rubin Ultra Wildcard

No single event inside the forecast window moves as much value as NVIDIA's Rubin Ultra configuration.

This is a systemic risk because the entire memory complex has already priced the high case. If the dual-die redesign is real, HBM4 demand lands materially below the wafer allocations at SK Hynix, Samsung and Micron [S24]. The excess does not vanish — it cascades: marginal HBM4 capacity additions get cancelled, conventional DRAM supply recovers sooner than buyers expected, and the 4Q26 price momentum breaks. Conversely, if NVIDIA confirms 12-Hi at GTC in March 2027, every HBM4 wafer committed for 2027 stays committed, conventional DRAM stays starved, and the crowding-out inflation above extends deeper into 2027.

Note the direction of causality the evidence supports: the reported redesign was driven by packaging yield constraints — CoWoS-L yield and substrate warpage — not by demand weakness [S8]. The packaging bottleneck is therefore not merely a symptom of the cycle; it is shaping the product architecture of the cycle's largest demand driver, which then feeds back into memory allocation. A packaging constraint at one company is determining memory prices for every company. That loop is the single most important second-order effect in this report.

### Single Points of Failure With No Redundancy Inside the Window

- **TSMC packaging and leading-edge logic.** Samsung's SF2 2nm process remains unqualified for external customers; A single Taiwan disruption — seismic, geopolitical or epidemiological — is thus simultaneously a packaging, leading-edge logic and substrate event, because no second qualified leading-edge foundry exists to absorb it.
- **ASML tools.** Because ASML is the sole EUV supplier and TSMC depends on it for the N2 ramp, every announced expansion downstream — TSMC's CoWoS doubling, memory HBM lines — assumes tool throughput that the sole supplier has already flagged as insufficient. TSMC itself said "the tool supply is tight" on its October call [S17]. The constraint propagates: fewer tools, slower ramp, longer packaging scarcity, higher substrate LTAs. And because High-NA capacity is even narrower — Intel is the first adopter — the 2nm-and-beyond roadmap carries a second, tighter single point nested inside the first.
- **IBIDEN and upstream substrate materials.** Ajinomoto has already raised ABF film prices 30% [S31].

The interaction among the three is the real risk. An ASML tool shortfall slows the CoWoS ramp; the slower ramp extends packaging scarcity; Buyers should read the concentration list not as three separate risks but as one coupled system with three single hosts — and, at the materials layer, a fourth.

### Geopolitical Cliffs and the Cycle Risk

Two dated cliffs bracket the near term. Treasury has said a truce extension to 10 January 2027 is expected, but no matching BIS notice had been published. [S2] The asymmetry matters: these cliffs do not create new AI-segment scarcity — packaging and HBM are already sold out — but they propagate into the loose half of the chain. Rare-earth and gallium/germanium restrictions feed specialty materials and logistics; an Affiliates Rule reinstatement tightens the SMIC-linked mature-node supply that is currently the chain's slack pool. Escalation therefore lands mostly on consumer and industrial buyers, compounding the memory-driven inflation described above rather than offsetting it.

### What Each Actor Should Do

**Accelerator buyers (AMD, Broadcom, hyperscalers).** The window to secure 2027 CoWoS/SoIC lanes and HBM4 allocation closes around TSMC's January 2027 Q4 call, when 2027 capex guidance and allocation commentary reset everyone's price expectations. [S48] The only structural hedge inside the window is overflow: ASE and Amkor capture spillover as TSMC's capacity doubles toward 2028 [S45][S47], and dual-sourcing packaging there is cheaper than paying spot HBM premiums later. System OEMs outside the AI complex — PC, handset, automotive — should treat the crowding-out arithmetic as a 2027 sourcing problem now: lock LTAs before the 4Q26 momentum annualizes, and design for memory-lean configurations as a hedge against allocation rather than price. [S19]

**Memory makers.** The HBM-versus-conventional allocation decision is now the industry's central trade-off. SK Hynix's 50% HBM revenue share is the prize [S43]; the Rubin Ultra downside is the risk. if not, it remains a memory-price taker with the same wafer trade-off as everyone else.

**Equipment and substrate suppliers (ASML, Lam, Applied Materials, TEL, IBIDEN, Unimicron, Amkor).** For substrate makers specifically, the Unimicron chairman's warning of a 20% materials gap in 2027 [S51] implies that the binding constraint on their own expansion is upstream — glass fiber cloth, CCL and equipment — not demand, so vertical supply security is worth more than additional capacity announcements.

**Policymakers.** The chain's 2027 problem is not aggregate capacity — utilization at 76.51% proves that [S3] — it is that the throughput decisions of roughly four companies determine the price of computation for everyone else, and no policy instrument in current use changes that before 2028.

## Forecast Summary Table and Calibration Notes

This closing chapter consolidates the report's forecast architecture into two master tables — the five-scenario split and the ranked six-segment bottleneck list — and then explains, in one place, where every probability comes from and where the honest uncertainty lies.

### The Scenario Table: Five Worlds for the 2027 Chain

| Scenario | Probability | Core claim | Resolution criteria (by 31 Dec 2027) | Key beneficiaries / casualties |
|---|---|---|---|---|
| One — AI-led broad tightness | — | CoWoS/SoIC, HBM4, leading-edge logic and equipment all bind; tightness propagates upstream through ASML's declared tool shortfall | (a) TSMC or a major customer publicly states packaging still limits output; | TSMC, SK Hynix, ASML, reservation holders; losers: non-NVIDIA accelerator buyers, conventional DRAM buyers |
| Two — Packaging-only bottleneck | — | — | — | TSMC, ASE, Amkor, Intel, IBIDEN, Unimicron, Ajinomoto via LTA lock-ins |
| Three — Balanced chain | — | Record capex clears gaps on schedule; only isolated, short allocation episodes | AND (c) no major public allocation complaint | Second-tier accelerator vendors, consumer OEMs, buyers broadly; ASML backlog stretches |
| Four — AI air pocket / correction | — | — | OR (b) at least two major memory makers announce capex cuts | Buyers; casualties: memory trio, reservation-financed substrate/OSAT buildouts |
| Five — Mixed / other | — | Partial relief and mixed signals; conjunctions of Scenarios 1–4 each partially but not fully met | None of the four conjunctions resolves cleanly (e.g., packaging tight AND HBM relieved AND memory prices soft) | Fragmented; |

The split is mutually exclusive and exhaustive by construction.

### The Ranked Bottleneck Table: Six Segments, Probabilities and Severity

| Rank | Segment | P(binding before end-2027) | Expected duration | Severity (price / lead time / allocation) | Capacity owners | Who benefits |
|---|---|---|---|---|---|---|
| 1 | Advanced packaging (CoWoS/CoWoS-L/SoIC) | ~85% | Binding since mid-2023; [S1] entire window | — | TSMC | ASE, Amkor, Intel, reservation holders [S47] |
| 2 | HBM (HBM3E/HBM4) | ~85% | Sold out into 2027; through 2027 | — | SK Hynix (50%), Samsung (33%), Micron (18%) [S43] | All three suppliers; NVIDIA via secured allocation |
| 3 | ABF substrates and upstream materials | ~75% | Tight now; | — | — | Substrate trio via LTA lock-ins |
| 4 | EUV/High-NA equipment | ~60% | — | High / High / Rationed allocation | ASML (sole source) | ASML margin; incumbent tool holders |
| 5 | Conventional DRAM (crowding-out) | ~55% | Through at least 1H27 | — | Samsung, SK Hynix, Micron | Memory trio; hurts consumer/auto buyers |
| 6 | Leading-edge logic foundry (N3/N2) | ~50% (conditional) | 2H27 if tool supply gates the ramp | — | TSMC; Samsung SF2 unqualified | TSMC pricing; |

### Where the Probabilities Come From: The Calibration Ladder

Three layers of evidence stack to produce every number above, and their order matters.

**Layer one: base rates from documented episodes.**

**Layer two: primary-source statements from the constrained parties themselves.** Where a company that owns the capacity volunteers that it is short, third-party estimate disputes lose force. Three such statements anchor the table: TSMC's CEO on 16 July 2026 [S1]; ASML on 14 October 2026 [S2]; and Unimicron's chairman on 20 October 2026 warning of up to 30-month equipment lead times and a 20% shortfall in glass fiber cloth, CCL and ABF in 2027 [S51]. These convert what would otherwise be trade-press speculation into supplier-admitted constraints, and they justify the high probabilities on rows 1-4 even where precise capacity figures are contested.

**Layer three: price and inventory telemetry.**

### Honest Divergences: Where This Report Departs From Published Numbers

Calibration requires stating where this forecast disagrees with the sources it cites, and why.

The discount is mechanical: every packaging ramp routes through tool supply that ASML has already declared insufficient and substrate equipment carrying lead times of up to 30 months [S51]. When the sole EUV supplier and the second-largest substrate maker both volunteer shortfall warnings, institutional capacity forecasts built on announced capex deserve a haircut.

The report treats it as directionally consistent with the verified sub-10-day inventories but does not rest any probability on the sell-through claim itself. [S43] Readers should distinguish the two: the inventory data are supplier-reported and checkable; the sell-through claim is not.

TSMC's own CEO statement corroborates the direction (customer-limiting tightness ) but not the numbers. Every threshold in the binary ledger anchored to third-party trackers inherits that caveat, which is why primary-source checkpoints — TSMC's January 2027 call, ASML's Q4 2026 results, GTC March 2027 — are treated as authoritative wherever they exist. [S34]

### The Confidence Statement and the Four Early Checkpoints

Overall confidence in this forecast is **low-to-moderate**, and the sources of the discount are specific, not general:

- **The Rubin Ultra hinge.** A large share of the probability mass separating Scenario One from Scenario Two, and Scenario Two from Scenario Four, sits on this single unconfirmed specification.
- **Leak-based Samsung yields** with no external qualification on record [S21][S23], leaving the leading edge effectively single-source and any diversification estimate speculative.

TSMC's January 2027 Q4 call for 2027 capex and packaging commentary; [S48] Until then, the summary judgment stands as calibrated: a chain producing at an all-time high at barely one-third-of-range aggregate utilization, in which the binding constraints are concentrated, allocation-managed, and relieved — by every supplier's own published schedule — only after this forecast's horizon [S45].

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/semichain-2027/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[38%] AI-led broad tightness (packaging + HBM + leading-edge logic + equipment)**: By 2027-12-31: (a) TSMC or a major customer publicly states CoWoS/SoIC allocation still limits output; AND (b) HBM4 lead times >26 weeks or supplier inventory <10 days per named supplier disclosure or TrendForce; AND (c) at least one major customer publicly attributes an N2/2nm or EUV-tool ramp delay to allocation; AND (d) DRAM contract prices rising YoY in Q4 2027 per TrendForce.
- **[30%] Packaging-only bottleneck persists (CoWoS/SoIC + substrates the single binding constraint)**: By 2027-12-31: (a) CoWoS/SoIC lead times >40 weeks per industry tracker, or TSMC confirms packaging still customer-limiting; AND (b) HBM4 lead times <20 weeks and supplier inventory >10 days; AND (c) no broad N2/tool allocation crisis publicly reported by TSMC/Samsung customers.
- **[10%] Balanced chain (record capex clears gaps; only isolated allocation episodes)**: By 2027-12-31: (a) CoWoS lead times <26 weeks per named industry tracker; AND (b) HBM4 lead times <20 weeks with supplier inventory >10 days; AND (c) no major public statements of packaging/HBM limiting customer growth in H2 2027; AND (d) Q4 2027 memory contract prices flat-to-down YoY per TrendForce.
- **[12%] AI air pocket / correction: memory and packaging flip to oversupply**: By 2027-12-31: (a) DRAM and/or HBM contract prices down >15% YoY in Q4 2027 per TrendForce or equivalent; OR (b) at least two major memory makers announce capex cuts; AND (c) CAPUTLG3344S (2027-12) observed below 71.096% (five-year low, 2026-03) [S3]; AND (d) CoWoS lead times <20 weeks.
- **[10%] Other / mixed-status-quo (partial relief, mixed signals, or none of the above cleanly resolves)**: By 2027-12-31: the conjunctions of criteria in Scenarios 1-4 are each partially but not fully met (e.g., packaging tight but HBM relieved AND memory prices down, or criteria split across two scenarios), such that no single scenario's full criteria set resolves true.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States (fred:CAPUTLG3344S) | next monthly release after 2026-09 | — |
| Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States (fred:IPG3344S) | next monthly release after 2026-09 | — |
| Real Exports of Goods and Services — United States (fred:EXPGSC1) | next quarterly release after 2026-Q2 | — |
| Real imports of goods and services — United States (fred:IMPGSC1) | next quarterly release after 2026-Q2 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Real Exports of Goods and Services — United States (fred:EXPGSC1) | 2814.538 Billions of Chained 2017 Dollars (2026-Q2) | >= 2950 Billions of Chained 2017 Dollars / 2027-Q4 | 28% (n=32, h=6) vs model 42% | [Source](<https://fred.stlouisfed.org/series/EXPGSC1>) [S40] |
| Real Exports of Goods and Services — United States (fred:EXPGSC1) | 2814.538 Billions of Chained 2017 Dollars (2026-Q2) | < 2700 Billions of Chained 2017 Dollars / 2027-Q4 | 19% (n=32, h=6) vs model 8% | [Source](<https://fred.stlouisfed.org/series/EXPGSC1>) [S40] |

<!-- drf-news-market-context:117084d6192f3a9657f400a49d32931af36847d772310c1255a94d62d0b46ef6:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:117084d6192f3a9657f400a49d32931af36847d772310c1255a94d62d0b46ef6:end -->

<!-- sim-bridge:start -->
## Scenario simulation: what the exercise explored

Simulated under declared assumptions. Not observed facts, not a calibrated probability, and not an input to any probability in this report.

- Engine: oasis-reflexive
- Horizon: 2026-10-24 → 2027-12-31 (month)
- Periods committed: 14 of 14 planned
- Health: ok (validity: valid)
- Arbiter-failed rounds: 1
- Modelling gaps: 5

### Decisive moves

| Period | Actor | Move | Target | Public statement |
|---|---|---|---|---|
| 2027-05 | IBIDEN | Advance your documented plan: NVIDIA multibillion-dollar Ono reservation announced October 2026 |  | IBIDEN confirms steady execution of its Gama Cell 6 and Ono plant expansion programs under the FY2026-28 investment plan (~JPY 500bn). Gama Cell 6 first-phase c… |
| 2027-08 | ASML | Advance your documented plan: Raise capacity ~30% for 2027 |  | ASML Q3 2027 delivery update: cumulative qualified installed Low-NA EUV and DUV immersion output at customer sites now stands approximately 27% above the 2026 c… |
| 2027-08 | TSMC | Deliver commitment [c0_1_1]: Advance CoWoS industry-equivalent capacity toward ~200,000 wpm by end-2027 and bring 2nm to 90,000 wpm by end-2026 |  | TSMC continues to execute its committed capacity roadmap: 2nm reached 90,000 wafers per month at end-2026 and has advanced to ~110,000 wpm as of mid-2027, with … |
| 2027-02 | Samsung Electronics | Deliver commitment [c3_1_1]: Maintain and expand HBM4 capacity toward closing share gap with SK Hynix through 2027 |  | Samsung Electronics continues delivery on its HBM4 capacity commitment: dedicated HBM4 wafer input rises to ~90,000 wpm this quarter within our ~150,000 DRAM wp… |
| 2027-10 | Broadcom | Seek talks with TSMC over its move | TSMC | Broadcom welcomes the ASE integration into the CoWoS planning framework and confirms we will bring our full 2028 volume forecast tranche and co-investment signa… |
| 2027-12 | IBIDEN | Issue a public statement or warning |  | IBIDEN year-end IR update (December 2027): Gama Cell 6 first-phase equipment installation and process qualification are complete, and mass production has begun … |
| 2027-12 | Unimicron | Publish an investigation or editorial |  | Unimicron year-end 2027 review: KF initial lines have produced at committed volumes since Q2 and progressive ramp continues toward full utilization by mid-2028,… |
| 2027-07 | SK Hynix | Counter Samsung Electronics's move (Accommodate or publicly answer SK Hynix's move → SK Hynix) | Samsung Electronics | We welcome all capacity additions that convert to qualified, delivered 12-Hi HBM4 stacks on customer timelines. For our part, SK hynix remains the principal sup… |

### Red lines crossed and commitments broken

- ASML: commitments kept 2, lapsed 2, broken 0
- China MOFCOM: commitments kept 2, lapsed 1, broken 0
- NVIDIA: commitments kept 6, lapsed 1, broken 0
- Samsung Electronics: commitments kept 4, lapsed 1, broken 0
- US Department of Commerce/BIS: commitments kept 3, lapsed 4, broken 0

### Simulated shares beside this report's probabilities

| Scenario | Final simulated share | Report probability |
|---|---|---|
| AI-led broad tightness (packaging + HBM + leading-edge logic + equipment) | — | 38% |
| Packaging-only bottleneck persists (CoWoS/SoIC + substrates the single binding constraint) | — | 30% |
| Balanced chain (record capex clears gaps; only isolated allocation episodes) | — | 10% |
| AI air pocket / correction: memory and packaging flip to oversupply | — | 12% |
| Other / mixed-status-quo (partial relief, mixed signals, or none of the above cleanly resolves) | — | 10% |
| Packaging-only bottleneck | 47.0% | — |
| AI-led broad tightness | 43.9% | — |
| Balanced chain | 7.8% | — |
| Oversupply and correction | 1.2% | — |

The probabilities in this report were not changed by the exercise (policy: diagnostic_only).

<!-- viz:charts/worldstate_trajectory.html -->
![Simulated outcome-share trajectory](demos/semichain-2027/charts/worldstate_trajectory.png)

*Simulated outcome-share trajectory*

<!-- viz:charts/world_variables.html -->
![Simulated state variables (indexed, seed = 100)](demos/semichain-2027/charts/world_variables.png)

*Simulated state variables (indexed, seed = 100)*

Full record: `simulation_record.md` (canonical JSON SHA-256 a7db02926ab7504ce502b38454a4aa0389e9e9695bacdf82b74988e1a5ec2c23)
<!-- sim-bridge:end -->

<!-- forecast-track-record:start -->
## Historical forecasting track record

These scores describe retained forecasts with recorded outcomes. A limited record does not establish calibration.

| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |
|---|---:|---:|---:|---:|
| Scenarios (multiclass) | 9 | 0 | 9 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 25 | 0 | 25 | — |
| Unanchored binaries | 110 | 0 | 110 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S3] Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CAPUTLG3344S](https://fred.stlouisfed.org/series/CAPUTLG3344S)
2. [S4] Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/IPG3344S](https://fred.stlouisfed.org/series/IPG3344S)
3. [S40] Real Exports of Goods and Services — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/EXPGSC1](https://fred.stlouisfed.org/series/EXPGSC1)
4. [S41] Real imports of goods and services — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/IMPGSC1](https://fred.stlouisfed.org/series/IMPGSC1)
5. [S1] Is TSMC CoWoS Sold Out in 2026? What TSMC Said — siliconanalysts.com — [https://siliconanalysts.com/analysis/foundry-allocation-status-q1-2026](https://siliconanalysts.com/analysis/foundry-allocation-status-q1-2026)
6. [S45] NVIDIA and Supply Chain Partners Expand Capacity to Accelerate AI Infrastructure Buildout | NVIDIA Newsroom — nvidianews.nvidia.com — [https://nvidianews.nvidia.com/news/nvidia-and-supply-chain-partners-expand-capacity-to-accelerate-ai-infrastructure-buildout](https://nvidianews.nvidia.com/news/nvidia-and-supply-chain-partners-expand-capacity-to-accelerate-ai-infrastructure-buildout)
7. [S51] [News] Unimicron Warns of IC Substrate Crunch: Up to 30-Month Equipment Lead Times, 20% Material Gap in 2027 — trendforce.com — [https://www.trendforce.com/news/2026/10/20/news-unimicron-warns-of-ic-substrate-crunch-up-to-30-month-equipment-lead-times-20-material-gap-in-2027/](https://www.trendforce.com/news/2026/10/20/news-unimicron-warns-of-ic-substrate-crunch-up-to-30-month-equipment-lead-times-20-material-gap-in-2027/)
8. [S2] ASML reports €11.7 billion total net sales and €5.0 billion net income in Q3 2026 | Wed, 10/14/2026 - 07:00 — investor.asml.com — [https://investor.asml.com/news-releases/news-release-details/asml-reports-eu11.7-billion-total-net-sales-and-eu5.0-billion-net-income-q3-2026](https://investor.asml.com/news-releases/news-release-details/asml-reports-eu11.7-billion-total-net-sales-and-eu5.0-billion-net-income-q3-2026)
9. [S15] China Rare Earth Export Pause: What Ends on 10 November — technology.org — [https://www.technology.org/2026/10/19/china-rare-earth-export-pause-november-10/](https://www.technology.org/2026/10/19/china-rare-earth-export-pause-november-10/)
10. [S60] U.S. Export Controls and China: Advanced Semiconductors | Congress.gov | Library of Congress — congress.gov — [https://www.congress.gov/crs-product/R48642](https://www.congress.gov/crs-product/R48642)
11. [S19] Semiconductor Allocation Dashboard — Live Foundry Capacity & Lead Time Tracker — siliconanalysts.com — [https://siliconanalysts.com/tools/allocation](https://siliconanalysts.com/tools/allocation)
12. [S14] Federal Register — federalregister.gov — [https://www.federalregister.gov/documents/2025/11/12/2025-19846/one-year-suspension-of-expansion-of-end-user-controls-for-affiliates-of-certain-listed-entities](https://www.federalregister.gov/documents/2025/11/12/2025-19846/one-year-suspension-of-expansion-of-end-user-controls-for-affiliates-of-certain-listed-entities)
13. [S20] [News] TSMC CoWoS Supply-Demand Gap Reportedly Seen Narrowing from 20% to 10% by End-2026 — trendforce.com — [https://www.trendforce.com/news/2026/06/15/news-tsmc-cowos-supply-demand-gap-reportedly-seen-narrowing-from-20-to-10-by-end-2026-as-capacity-expands/](https://www.trendforce.com/news/2026/06/15/news-tsmc-cowos-supply-demand-gap-reportedly-seen-narrowing-from-20-to-10-by-end-2026-as-capacity-expands/)
14. [S43] HBM4 Market Share 2026: Samsung vs SK Hynix vs Micron — siliconanalysts.com — [https://siliconanalysts.com/analysis/hbm4-market-share-race-2026](https://siliconanalysts.com/analysis/hbm4-market-share-race-2026)
15. [S27] Memory Prices Soar; DRAM and NAND Flash to Account for 68% of... — trendforce.com — [https://www.trendforce.com/presscenter/news/20260825-13198.html](https://www.trendforce.com/presscenter/news/20260825-13198.html)
16. [S70] Commerce Adds China's SMIC to the Entity List, Restricting Access to Key... — 2017-2021.commerce.gov — [https://2017-2021.commerce.gov/news/press-releases/2020/12/commerce-adds-chinas-smic-entity-list-restricting-access-key-enabling.html](https://2017-2021.commerce.gov/news/press-releases/2020/12/commerce-adds-chinas-smic-entity-list-restricting-access-key-enabling.html)
17. [S31] Ajinomoto Raises ABF Substrate Film Prices 30% as AI Demand Extends... — atlaspcb.com — [https://www.atlaspcb.com/news/news-ajinomoto-abf-substrate-price-increase-2026/](https://www.atlaspcb.com/news/news-ajinomoto-abf-substrate-price-increase-2026/)
18. [S48] Dan Nystedt on X: "Rumor: TSMC's 2027 CoWoS packaging capacity... — x.com — [https://x.com/dnystedt/status/2075374878644146511?lang=en](https://x.com/dnystedt/status/2075374878644146511?lang=en)
19. [S25] AI Server Demand Sustains Memory Contract Price Increases in 4Q26, While Consumer-Side Pressure Persists, Says TrendForce — trendforce.com — [https://www.trendforce.com/presscenter/news/20260930-13258.html](https://www.trendforce.com/presscenter/news/20260930-13258.html)
20. [S12] Report: TSMC to Double CoWoS Capacity by 2028 as AI Chip... — wccftech.com — [https://wccftech.com/report-tsmc-to-double-cowos-capacity-by-2028-as-ai-chip-shortage-spills-over-to-rivals/](https://wccftech.com/report-tsmc-to-double-cowos-capacity-by-2028-as-ai-chip-shortage-spills-over-to-rivals/)
21. [S28] HBM4 Shortage: DRAM Inventory Falls Below 10 Days — tech-insider.org — [https://tech-insider.org/hbm4-memory-shortage-dram-inventory-2026/](https://tech-insider.org/hbm4-memory-shortage-dram-inventory-2026/)
22. [S47] TSMC's CoWoS Capacity to Double to 260,000 Wafers by 2028; Intel and OSAT Providers Capture Spillover Orders — BigGo Finance — finance.biggo.com — [https://finance.biggo.com/news/adcec901-53b3-453f-bf00-8373ebb1bb97](https://finance.biggo.com/news/adcec901-53b3-453f-bf00-8373ebb1bb97)
23. [S18] TSMC 'prudent' going into 2027 after posting sixth straight quarter of record profit | Reuters — reuters.com — [https://www.reuters.com/world/asia-pacific/tsmc-expected-report-sixth-straight-quarter-record-profit-thanks-ai-boom-2026-10-14/](https://www.reuters.com/world/asia-pacific/tsmc-expected-report-sixth-straight-quarter-record-profit-thanks-ai-boom-2026-10-14/)
24. [S73] China’s New Rare Earth and Magnet Restrictions Threaten U.S. Defense Supply Chains — csis.org — [https://www.csis.org/analysis/chinas-new-rare-earth-and-magnet-restrictions-threaten-us-defense-supply-chains](https://www.csis.org/analysis/chinas-new-rare-earth-and-magnet-restrictions-threaten-us-defense-supply-chains)
25. [S16] BIS Affiliates Rule Suspension Extended but Uncertainty Remains: Miller Canfield — millercanfield.com — [https://www.millercanfield.com/resources-BIS-Affiliates-Rule-Suspension-Extended.html](https://www.millercanfield.com/resources-BIS-Affiliates-Rule-Suspension-Extended.html)
26. [S9] Nvidia Rubin Ultra will ship with 192GB of HBM4 8-hi. Not only is... - X — x.com — [https://x.com/SemiAnalysis_/status/2091994110911557679?lang=en](https://x.com/SemiAnalysis_/status/2091994110911557679?lang=en)
27. [S24] Global DRAM and HBM Market Share: Quarterly — counterpointresearch.com — [https://counterpointresearch.com/en/insights/global-dram-and-hbm-market-share](https://counterpointresearch.com/en/insights/global-dram-and-hbm-market-share)
28. [S53] Jukan on X: " Unimicron: Customers Rush to Lock In ABF Substrate LTAs — x.com — [https://x.com/jukan05/status/2029745136499114216](https://x.com/jukan05/status/2029745136499114216)
29. [S34] ASML (ASML) Q3 2026 Earnings Call Transcript | The Motley Fool — fool.com — [https://www.fool.com/earnings/call-transcripts/2026/10/14/asml-asml-q3-2026-earnings-call-transcript/](https://www.fool.com/earnings/call-transcripts/2026/10/14/asml-asml-q3-2026-earnings-call-transcript/)
30. [S44] [News] TSMC Reportedly Targets 22% 2nm, 16%+ 3nm Capacity... — trendforce.com — [https://www.trendforce.com/news/2026/09/14/news-tsmc-reportedly-targets-22-2nm-16-3nm-capacity-boost-by-mid-2027-cowos-to-double-by-2028/](https://www.trendforce.com/news/2026/09/14/news-tsmc-reportedly-targets-22-2nm-16-3nm-capacity-boost-by-mid-2027-cowos-to-double-by-2028/)
31. [S17] Q3 2026 Taiwan Semiconductor Manufacturing Company Limited Earnings Call (Chinese, English) on October 15, 2026 / 6:00AM — investor.tsmc.com — [https://investor.tsmc.com/chinese/encrypt/files/encrypt_file/reports/2026-10/eba4fac72873bf546b669bd2b5d973df5c93215d/TSMC%203Q26%20Transcript.pdf](https://investor.tsmc.com/chinese/encrypt/files/encrypt_file/reports/2026-10/eba4fac72873bf546b669bd2b5d973df5c93215d/TSMC%203Q26%20Transcript.pdf)
32. [S21] Samsung's 2nm SF2 yield has climbed to roughly 60... - Instagram — instagram.com — [https://www.instagram.com/p/Dd3dchWm2_j/](https://www.instagram.com/p/Dd3dchWm2_j/)
33. [S6] NVIDIA GPU Roadmap 2026-2030: Rubin, Rubin Ultra, Feynman — vrlatech.com — [https://vrlatech.com/nvidia-gpu-roadmap-2026-2030/?srsltid=AYCX9vIcDsO4oy5ser6bGaI535zV9_lLnNIUb9w8m-J5WEnTbnCg-Dlb](https://vrlatech.com/nvidia-gpu-roadmap-2026-2030/?srsltid=AYCX9vIcDsO4oy5ser6bGaI535zV9_lLnNIUb9w8m-J5WEnTbnCg-Dlb)
34. [S26] Long-Term Agreements Cap Price Increases; Server DRAM Contract... — trendforce.com — [https://www.trendforce.com/presscenter/news/20260709-13140.html](https://www.trendforce.com/presscenter/news/20260709-13140.html)
35. [S42] [News] DRAM Prices Seen Rising 20% QoQ in 4Q26 Despite Slower Gains; AI Demand, Tight Supply Support Outlook — trendforce.com — [https://www.trendforce.com/news/2026/10/20/news-dram-prices-seen-rising-20-qoq-in-4q26-despite-slower-gains-ai-demand-tight-supply-support-outlook/](https://www.trendforce.com/news/2026/10/20/news-dram-prices-seen-rising-20-qoq-in-4q26-despite-slower-gains-ai-demand-tight-supply-support-outlook/)
36. [S8] Nvidia Scraps Quad-Die Rubin Ultra GPU Design, Cites Packaging Yield... — mlq.ai — [https://mlq.ai/news/nvidia-scraps-quad-die-rubin-ultra-gpu-design-cites-packaging-yield-issues/](https://mlq.ai/news/nvidia-scraps-quad-die-rubin-ultra-gpu-design-cites-packaging-yield-issues/)
37. [S23] Samsung 2nm Yield Reaches 50% - SmBom — smbom.com — [https://www.smbom.com/news/46255?srsltid=AYCX9vKwgMc6B7bkCw2Cpil-R5ZrV-1Fis5OQ2blOv5riPrv4NfoRkr0](https://www.smbom.com/news/46255?srsltid=AYCX9vKwgMc6B7bkCw2Cpil-R5ZrV-1Fis5OQ2blOv5riPrv4NfoRkr0)
