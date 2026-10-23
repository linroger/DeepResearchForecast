# Copper at the Crossroads: Forecasting the LME Cash Settlement Price for 31 December 2027

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/copper-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | The LME copper Official Settlement Price (cash) is above 14,000 USD per tonne on 31 December 2027. | 30% | Resolves YES if the LME Official Cash Settlement Price for copper on 31 December 2027 (last trading day) exceeds 14,000 USD/t, per the LME Official Prices publication (source: London Metal Exchange). | supercycle-price-persistence | — |
| F2 | The LME copper Official Settlement Price (cash) is below 10,500 USD per tonne on 31 December 2027. | 30% | Resolves YES if the LME Official Cash Settlement Price for copper on 31 December 2027 is below 10,500 USD/t (source: London Metal Exchange). | mean-reversion | — |
| F3 | A Section 232 tariff of at least 15% on refined copper imports is in force at some point during 2027. | 40% | Resolves YES if a Federal Register proclamation imposes a tariff of at least 15% on refined copper (cathode) effective on or before 31 December 2027 (source: Federal Register). | us-tariff-policy | — |
| F4 | Panama and First Quantum sign a restart agreement for the Cobre Panama mine by 31 December 2027. | 50% | Resolves YES if the Government of Panama and First Quantum publicly sign an agreement to restart the Cobre Panama mine on or before 31 December 2027 (source: Reuters / Government of Panama announcements). | cobre-panama-restart | — |
| F5 | Cobre Panama produces any commercial copper output by 31 December 2027. | 15% | Resolves YES if First Quantum reports commercial copper production from Cobre Panama on or before 31 December 2027 (source: First Quantum production reports). | cobre-panama-restart | — |
| F6 | The 2027 Antofagasta-Chinese smelter annual TC/RC benchmark settles at or below 0 USD per tonne. | 75% | Resolves YES if the 2027 annual benchmark treatment charge between Antofagasta and Chinese smelters, settled in Q4 2026-Q1 2027, is at or below 0 USD/t (source: benchmark settlement reporting, e.g. Reuters/MINING.COM). | smelting-tcrc-collapse | — |
| F7 | The CSPT formalizes a primary-smelting production cut of at least 10% for 2027. | 55% | Resolves YES if the China Smelter Purchase Team announces a formal primary-smelting cut quota of at least 10% of capacity for 2027, by 30 June 2027 (source: CSPT statements). | smelting-tcrc-collapse | — |
| F8 | Kamoa-Kakula's 2027 copper production falls within Ivanhoe's guidance range of 500,000-540,000 tonnes. | 55% | Resolves YES if Ivanhoe Mines reports full-year 2027 Kamoa-Kakula production between 500,000 and 540,000 t (source: Ivanhoe Mines FY2027 results, published early 2028). | new-supply-ramp | — |
| F9 | Chilean copper mine output grows at least 5% in 2027. | 50% | Resolves YES if Cochilco-reported Chilean 2027 copper production is at least 5% above 2026 production (Cochilco forecasts 5.27 Mt in 2026, +5.2% in 2027) (source: Cochilco statistics). | new-supply-ramp | — |
| F10 | ICSG's 2027-vintage forecasts keep the 2027 global refined copper surplus at or above 200,000 tonnes. | 55% | Resolves YES if ICSG's spring or autumn 2027 forecast publications project a 2027 refined surplus of at least 200,000 t (October 2026 vintage: 368,000 t) (source: ICSG press releases). | refined-balance-surplus | — |
| F11 | LME copper warehouse stocks are below 200,000 tonnes on the last trading day of 2027. | 45% | Resolves YES if the LME's official copper stock report on the last trading day of 2027 shows total warehouse stocks below 200,000 t (source: LME stock reports). | inventory-dynamics | — |
| F12 | The COMEX-LME copper price spread exceeds 1,000 USD per tonne at any daily close during 2027. | 30% | Resolves YES if on any trading day of 2027 the CME HG settlement minus the LME cash settlement (converted to USD/t) exceeds 1,000 USD/t (spread was ~310-400 USD/t in autumn 2026) (source: CME HG settlements vs LME cash settlements). | us-tariff-policy | — |
| F13 | The IMF annual-average global copper price for 2027 is below the 2026 annual average. | 60% | Resolves YES if the IMF annual global copper price (imf:PCPS/G001.PCOPP.USD.A) for 2027 is below the 2026 annual average (2025 observed: 9946.8819 USD/t; September 2026 monthly: 14473.0559 USD/t) (source: IMF Primary Commodity Prices). | mean-reversion | — |
| F14 | The Global price of Copper (fred:PCOPPUSDM) is at least 14,000 U.S. Dollars per Metric Ton in 2027-12. | 39% | Resolves YES if fred:PCOPPUSDM >= 14000 U.S. Dollars per Metric Ton in 2027-12 (source: FRED). | supercycle-price-persistence | — |
| F15 | The Global price of Copper (fred:PCOPPUSDM) is below 10,500 U.S. Dollars per Metric Ton in 2027-12. | 28% | Resolves YES if fred:PCOPPUSDM < 10500 U.S. Dollars per Metric Ton in 2027-12 (source: FRED). | mean-reversion | — |
| F16 | Capacity Utilization: Total Index — United States (fred:TCU) is above 75 Percent in 2027-12. | 75% | Resolves YES if fred:TCU > 75 Percent in 2027-12 (source: FRED). Official resolution: fred:TCU > 75% for 2027-12. | industrial-demand | 78% (n=104, h=15) |
| F17 | EIA Retail Sales of Electricity: U.S. total, all sectors (usgov:eia/electricity_sales/US.ALL) is above 340000 Million kilowatt-hours in 2027-12. | 85% | Resolves YES if usgov:eia/electricity_sales/US.ALL > 340000 Million kilowatt-hours in 2027-12 (source: EIA). Official resolution: usgov:eia/electricity_sales/US.ALL > 340000 Million kilowatt-hours for 2027-12. | general | 83% (n=102, h=16; same-month seasonal mean plus pooled deviations, not seasonally adjusted) |

_17 forecasts; 8 high-conviction (≥70% or ≤30%); 15 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Global price of Copper | U.S. Dollars per Metric Ton | 14473.0559 | 2026-09 | +4478.2827 (+44.806%) | 7544.8095 to 14473.0559 | — | [S3] |
| EIA: Retail Sales of Electricity: U.S. total, all sectors | Million kilowatt-hours | 412568.3744 | 2026-08 | +18149.5089 (+4.602%) | 280811.1479 to 415228.5092 | — | [S9] |
| Capacity Utilization: Total Index — United States | Percent | 76.85% | 2026-09 | +0.804 pp | 75.168% to 79.042% | — | [S10] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/copper-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S9]; Million kilowatt-hours; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/TCU>) [S10]; Percent; Monthly; SA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/PCOPPUSDM>) [S3]; U.S. Dollars per Metric Ton; Monthly; NSA*

<!-- viz:charts/official_series_keakmrspafocalad.html -->
![Official Series History and Forecast Thresholds](demos/copper-2027/charts/official_series_keakmrspafocalad.png)

*Official Series History and Forecast Thresholds*

*Source: [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S9]; Million kilowatt-hours; Monthly; NSA*

<!-- viz:charts/official_series_mtclkemacbfmnese.html -->
![Official Series History and Forecast Thresholds](demos/copper-2027/charts/official_series_mtclkemacbfmnese.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/TCU>) [S10]; Percent; Monthly; SA*

## Part 2 — Framework & Synthesis

### Framework and Starting Point

The framework treats the 2027 price as the outcome of four contending forces: (1) the concentrate bottleneck and its mine-supply resolution; [S44] (2) the smelting leg — TC/RC collapse and Chinese cutback discipline; (3) demand from electrification, AI/data centres and grids versus the China property drag; and (4) US tariff policy and the distorted geography of inventories.

### The Scenario Spine and Its Logic

The concentrate deficit of roughly 530,000 t estimated by S&P Global for 2026 does not clear quickly; [S15]

It is not the central case because the retracement clock has barely started — the spike is only months old — and because the structural demand floor from grids and data centres is measurably stronger now (US retail electricity sales +4.6% y/y in August 2026 [S9]) than in prior spike episodes.

Requires a named macro catalyst — global recession or a tariff-war demand shock — coinciding with supply recovery.

### Causal Chain: Why the Plateau and Sustained-Highs Bin Dominate

The bearish absorption path is concrete.

The bullish persistence path is equally concrete. This asymmetry between the concentrate and refined balances is the analytical heart of the forecast, and it is why we weight the market's own flat curve more heavily than the surplus headline.

### Decisive Evidence

Four pieces of evidence did the most work in setting the probabilities.

Whatever the index disputes about levels (Chapter 7 of the appendix), every measure agrees on sign and direction.

The single-origin status of the 1.6 Mt figure is acknowledged;

The prior disciplines the narrative; the narrative adjusts the prior.

### Weighing the Market Anchors

Where market anchors exist, we used them as calibration, not truth. Prediction-market-style implied tariff probabilities were used directly for the tariff variable rather than our own guess.

### What Would Move Us

the refined tariff proclamation or its judicial nullification (up and down respectively); each trigger is dated and verifiable, so the forecast can be updated honestly rather than defended rhetorically.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## 1. Baseline: The Record Price of Late 2026 and the 2024–2026 Trajectory

This chapter establishes that baseline precisely — the price level, the three-year trajectory that produced it, the inventory configuration that underpins it, and the statistical context that disciplines what can plausibly happen over the following fourteen months.

### The Record of Late October 2026

The monthly series confirms the record is not a single-day artifact. The IMF global copper price — a monthly average — reached 14,473.06 USD/t in September 2026, up 4,478.28 USD/t (+44.806%) from 9,994.77 USD/t in September 2025 [S3].

### The 2023–2026 Trajectory: A Climb That Accelerated

The path to the record was a three-year grind that turned into a spike.

The spike has a physical signature, not merely a financial one.

### The Inventory Picture: Falling LME Stocks, a Swollen US Pile

Inventories tell the story of a market physically pulled in two directions.

The other side of the ledger is American.

### Statistical Discipline: What History Says Happens After Spikes

Three base rates frame everything that follows.

US electricity retail sales were up 4.602% year-on-year in August 2026, at the 99th percentile of their history [S9] — a genuine physical demand signal, not a speculative one. The historical retracement base rate was formed in episodes without this configuration.

### Why the Baseline Widens the Forecast Rather Than Resolving It

The curve itself expresses ambivalence: it does not price continuation of the spike, but it does not price collapse either.

## 2. The Concentrate Bottleneck: Mine Supply, Grades and Disruptions

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/copper-2027/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

<!-- viz:charts/regional_comparison.html -->
![Regional Comparison by Metric Family](demos/copper-2027/charts/regional_comparison.png)

*Regional Comparison by Metric Family*

<!-- viz:charts/quantitative_claims.html -->
![Comparable Forecast Benchmarks](demos/copper-2027/charts/quantitative_claims.png)

*Comparable Forecast Benchmarks*

The record copper price of late 2026 is not a financial artifact. It rests on a physical fact: the world's mines cannot currently feed its smelters.

### The arithmetic of the deficit

Smelters were, in effect, paying miners for the privilege of processing concentrate, running at deep losses on every tonne of feed purchased at spot terms.

Two things must therefore go right for the deficit to close: the mines must deliver the tonnes, and the smelters must keep running them. This chapter addresses the first condition; Chapter 4 addresses the second. The honest reading is that both are genuinely uncertain, and that the forecast dispersion between the ICSG surplus path and the physical reality of negative spot TC/RCs is the central analytical tension of this report.

### Chile: the state miner's stumble and the promised rebound

Chile produces roughly a quarter of the world's copper, so Codelco's production prints move the global balance more than any other single variable.

These are not one-off accidents but the intersection of structural grade decline — most visible at Ministro Hales — with operational restrictions at aging underground operations like El Teniente. Codelco's response is a ramp-up program funded by record prices: the company posted stronger profit on the copper rally even as disruptions dragged volumes [S5]. That profit-volumes divergence is the key tell. Codelco's incentive structure, with the Chilean state as a fiscally demanding shareholder, pushes it to monetize high prices and defend its contribution to the treasury, which supports an aggressive recovery effort — but does not guarantee the tonnes arrive on schedule.

The case for believing it: the disruptions of 2026 were partly operational and recoverable, projects are being pushed through at record margins, and Cochilco has direct statistical visibility. [S28]

### Peru: growth, but too late for 2026

Peru, the second-largest producer, tells a more encouraging but slower story.

As one analysis of the concentrate deficit put it, Peru's copper push "arrives too late" for the 2026 deficit [S15]: the tonnes unlocked by permitting flow in the 2030s, not by end-2027. The swing must come from Chile and the DRC, or not at all.

### Cobre Panama: the 350,000-tonne question

On 30 September 2026, a Panamanian government commission recommended opening formal negotiations with First Quantum on conditions to reopen the mine, with the structure designed to end pending international arbitration and finance an orderly closure at no cost to the state; [S37] President Mulino said he would study the report.

The framing deserves careful reading, because it is more ambiguous than the headline "restart recommendation" suggests. The commission's proposal is explicitly structured around financing a phased closure — Reuters reported it as a recommendation to reopen the mine "to fund a phased closure" — and no scope, timing or legal structure for a restart has been set out. Reuters separately reported the commission would propose a state tie-up with First Quantum [S37]. The critical asymmetry is that the restart is Panama's option, not First Quantum's: the government holds a legal veto, faces domestic public opposition to the mine, and is under fiscal pressure that gives it an incentive to extract maximal sovereign terms. First Quantum, holding a single-asset concentration in Panamanian politics and unresolved arbitration claims, has every reason to talk but limited leverage to set pace.

The timeline arithmetic is unforgiving. it is the single largest discrete discriminator between this report's scenarios.

### Weighing the bottleneck: steelmanning the surplus view

The strongest argument against this chapter's supply-side caution is that the bulls are extrapolating a bad year. Deeply negative spot TC/RCs, on this reading, are themselves the cure: they are already forcing the Chinese smelter cutbacks (Chapter 4) that mechanically reduce concentrate demand, and record prices are simultaneously incentivizing every restartable ounce and accelerable project in the world.

But three counterweights temper it. First, the deficit's causes are not all transient: grade decline is geological, not operational, and 2026's disruptions at the two largest producers (Codelco, Escondida) hit simultaneously with the structural absence of Cobre Panama — a combination that leaves little redundancy in the system. [S37]

The synthesis: the concentrate bottleneck probably begins to ease in 2027 — Chile's rebound, Antamina, and Kamoa-Kakula's ramp (Chapter 3) are real tonnes with named owners and published guidance — but the easing is likely partial and later than the surplus forecasts assume, and it remains hostage to two binary events outside any miner's control: the Cobre Panama negotiation and the discipline of Chinese smelters. [S38]

## 3. New Supply on the Horizon: Kamoa-Kakula, Chile's Ramp and the 2027 Project Pipeline

The evidence supports a conditional answer. The 2027 pipeline is real and large on paper, but it is dominated by ramp-ups at existing operations rather than genuine greenfield starts, its schedule assumes the smooth resolution of 2026's operational problems, and — critically — much of the projected refined surplus depends not on mines at all but on smelter behavior that Chinese producers have already signaled they intend to restrain [S44].

### The Largest Single Swing: Kamoa-Kakula's Ramp

The engineering behind the guidance matters for judging its credibility. The ramp rests on two concrete pillars rather than a vague growth promise. Both milestones are verifiable in Ivanhoe's quarterly reporting, which is what makes this guidance tradable information rather than aspiration: the market can check, quarter by quarter, whether mining rates and recoveries are on schedule [S38].

Execution risk is nonetheless non-trivial, and it is concentrated. Kamoa-Kakula is a single district in the DRC, dependent on Congolese infrastructure and power supply; the very seismic event that necessitated the recovery plan is a reminder that underground mining at this scale carries tail risk that guidance ranges only partially absorb [S38]. The direction of the price implication is asymmetric.

### Chile's Promised Rebound — and Its Track Record of Missing

Reuters separately reported, on Cochilco's January 2025 framing, that Chile plans to lift copper output about 6% over the next decade with a national peak in 2027 [S33].

Here the execution-risk question is sharper, because the forecaster's own record argues for discounting. Each of these is a reversion assumption, not a new project.

Peru, the second-largest producer, offers a useful contrast.

### Mergers and the Illusion of New Tonnes

It is not. Teck is separately seeking Chinese regulatory approval for the merger while improving its copper operations in Chile and Peru [S41]. The price-relevant channel of the merger is therefore not volume but capital allocation and geopolitics: Reuters framed the deal as a test case for navigating geopolitics [S39], and the pending Chinese antitrust decision introduces a tail risk that a Western-championed copper consolidation could become entangled in the same trade politics that distort the COMEX–LME relationship.

A similar discipline applies to the rest of the project pipeline. No verifiable 2027 startup of a brand-new large-scale mine (Cobre Panama is a restart, not a new mine, and its negotiation process had produced no scope, timing or legal structure as of the 30 September 2026 commission recommendation [S37]) appears in the evidence base.

### The Timing Mismatch: Why a 2026 Deficit and a 2027 Surplus Can Both Be True

The most important analytical point in this chapter is the structural lag between the concentrate market and the refined market. S&P Global's ~530,000 t concentrate deficit is a 2026 phenomenon [S15];

But the refined side of ICSG's 2027 surplus rests heavily on "smelter and refinery ramp-ups in Indonesia, India and the EU, better Chilean operating rates and more scrap-based output" [S6] — that is, on processing recovery, not on new mines. This creates a specific vulnerability: the surplus forecast assumes Chinese smelter behavior that Chinese smelters themselves are actively trying to change. Chapter 4 takes up that discipline question in full;

The scale check is equally sobering for the bears. A surplus that accumulates in the wrong hemisphere does not necessarily relieve the LME-shed tightness that supports cash prices.

### What This Means for the End-2027 Price

The bullish steelman — that guidance misses at Kamoa-Kakula and Chile replicate 2026's pattern, the concentrate deficit persists into a second year, and smelter cuts throttle refined output — is coherent and supported by the 2026 track record; [S45]

## 4. The Smelting Squeeze: TC/RC Collapse and Chinese Cutback Discipline

The smelting leg of the copper market is where the 2026 price spike is being either cemented or unwound. The judgment developed here is that the TC/RC collapse is genuine and mechanically supportive of prices, but that cutback discipline will only partially hold — enough to trim the surplus, not enough to eliminate it — which anchors the elevated-plateau path this report weights most heavily.

### The Anatomy of the Collapse: From Zero to Negative

The starting point is the annual benchmark. In January 2026, Antofagasta settled the year's concentrate treatment and refining charges with Chinese smelters at $0 per tonne and 0 cents per pound — the lowest annual benchmark on record. [S28] That number needs translating for what it means commercially: the treatment charge is what a miner pays a smelter to process concentrate. At zero, smelters agreed to run a year of production on the strength of by-product credits (chiefly sulfuric acid and gold/silver in the concentrate) plus whatever spot-margin opportunities arose. Any deterioration beyond that benchmark would mean smelters paying miners outright.

That deterioration arrived within months.

The index readings conflict, and the conflict matters analytically rather than being noise to be averaged away. Deeply negative spot terms are the single best-confirmed fact in the copper market's supply side as of late October 2026, and they explain a paradox that otherwise confuses the price debate: how can LME refined prices sit at records while ICSG projects a refined surplus ? [S44] The answer is that the surplus is a projection of refined capacity behavior, while negative TC/RCs are a real-time market price on the scarcity of the input. When the input is this scarce, the refined surplus is a forecast at risk, not an accomplished fact.

### CSPT's Cutback Gamble: Incentives, Mechanisms and the Discipline Problem

Negative treatment charges inflict severe losses on Chinese smelters, and China processes roughly half of the world's copper. The rational response is to cut output, and the China Smelter Group (CSPT) has coordinated exactly that. China's copper cathode output has already fallen amid maintenance and supply constraints [S43]. This is the mechanism by which the smelting squeeze transmits to price: cuts to primary smelting reduce refined supply, eroding ICSG's projected surplus; they also reduce Chinese demand for concentrate, which — perversely for the smelters — is the very thing that would pull spot TC/RCs back toward zero and restore their margins. The cutbacks are simultaneously a price-support mechanism for cathode and a terms-recovery mechanism for concentrate.

The mechanism, however, runs through a cartel-like coordination problem with a poor track record. Each member firm faces a private incentive to free-ride: keep running while rivals cut, capture the resulting cathode strength and improved terms, and let others absorb the volume loss. Chinese smelters also face local-government growth and employment mandates that complicate deep idling of capacity.

There is a steelman for the view that discipline holds better this time, and it deserves weight. Second, the sulfuric acid by-product cushion that sustained smelters through earlier TC/RC squeezes has been weakened by China's sulfuric acid export dynamics [S42], removing a key source of smelter revenue. The counter-response is that Indonesian, Indian and EU smelting ramp-ups stand outside CSPT discipline entirely, so even perfect Chinese compliance is partially offset by capacity that has every incentive to run hard into record cathode prices. The smelting squeeze, in other words, will be fought plant by plant, not bloc by bloc.

### The Pivotal Negotiation: The 2027 Benchmark as a Scenario Discriminator

The Q4 2026–January 2027 Antofagasta–Chinese smelter benchmark talks are the single most information-dense event on the copper calendar before the January tariff decision. [S30]

1. **A repeat at or below zero.**
2. the collapse since has been near-total).

The spot market provides the running scoreboard between benchmarks.

### Why This Leg Anchors the 45% Plateau Judgment

The arithmetic of this chapter says that assumption is fragile in both directions. If cuts bite at announced depth, Chinese refined output alone could shed several hundred thousand tonnes, flipping the balance back toward deficit and sustaining record prices.

The transfer of pricing power embedded in all of this should not be missed: the $0 benchmark and the shift toward index-linked concentrate pricing represent a structural migration of margin from smelting to mining, and a corresponding migration of pricing power over the copper market itself. Miners now capture what smelters once did; smelters' remedy is to shrink. Every month that spot TC/RCs stay below −$100/t, that shrinkage continues — and each tonne of Chinese cathode withdrawn from the market is a tonne ICSG's surplus quietly loses, and a dollar of support under the LME price into 2027. [S21]

## 5. Demand: Electrification versus the China Property Drag

The demand side of the copper market in late 2026 presents a rare configuration: consumption growth is accelerating into a record price, not despite it. [S45]

### The electrification engine: grids, data centres and the load record

The single most concrete demand fact in the evidence base is the US electricity data. Retail sales of electricity across all sectors reached 412,568.37 million kWh in August 2026, up 4.602% year on year, with July 2026 (415,228.51 million kWh) marking the top of the five-year range [S9]. Growth of that magnitude in a mature, services-heavy economy is abnormal: it signals electrification of transport and heating plus a data-centre buildout pulling load growth that utilities must answer with new substations, transformers and transmission — all copper-intensive.

An honest caveat: no authoritative estimate of data-centre copper tonnage exists in the record. ICSG's attribution is qualitative; the EIA load series serves as the observable proxy precisely because a hard data-centre number has not been published. That matters for calibration. If the AI capex cycle slowed, the copper impact would show up first as decelerating load growth, not in any direct data-centre tonnage series.

The IEA's Electricity 2026 report, with its Grids section, frames grid investment as the key structural copper demand lever to 2027 [S49]. The implication is that grid demand is a policy variable, not a market variable — Beijing can lift or throttle State Grid capex as a counter-cyclical tool, independently of copper prices.

### EVs: still growing, but the growth rate is compressing

Electric vehicles remain a structural demand pillar.

But the monthly frequency tells a deceleration story. For copper, the arithmetic consequence is that EV demand still adds absolute tonnes each year (an EV uses materially more copper than a combustion car), but the *incremental* year-on-year addition is shrinking at the margin. outright contraction would feed the hard-landing scenario.

The same record prices that validate electrification investment also accelerate its competitor. Two years above 12,000 USD/t would. While no firm number can be honestly cited, the direction is unambiguous, and it is one of the few mechanisms that converts high prices into permanently lost demand rather than deferred demand.

### China: 59% of consumption, property drag, and the stimulus question

Whatever happens to grids in Kansas or data centres in Virginia is second-order next to Chinese apparent usage.

The mechanism matters. Property-linked copper demand (building wire, plumbing, HVAC) is being overwhelmed by electrification-linked demand (grid capex, EV manufacturing, renewables, export-oriented manufacturing). NDRC and Beijing policymakers hold both levers: they manage the property drag through the sector's managed decline while directing State Grid and electrification spending as stimulus. The evidence characterizes property as "the largest unmeasured demand drag" — unmeasured because Chinese apparent usage conflates consumption with inventory building and financing behaviour, so the true underlying consumption rate is unknowable from the published series.

Apparent usage includes stockbuilding; Goldman Sachs's argument that record-high copper prices are not forecast to last rests partly on this: once the inventory distortions unwind, apparent demand reverts toward true consumption, which the property drag holds below headline growth [S25]. The August 2026 LME flash squeeze, reported by Reuters as copper tensions boiled over, shows how much of 2026's price is positioning and scarcity premia rather than physical demand. [S28]

The rebuttal is equally evidence-based. Smelters do not pay miners for concentrate to satisfy speculative demand.

### Scrap: the price-responsive supply that is also a demand response

Secondary copper is the hinge between the demand and supply chapters, and it cuts both ways. High prices mobilize scrap: old scrap collection rises, thrifting and premature scrappage rise, and the price-elastic secondary stream expands precisely when primary supply is constrained. Every tonne of accelerated scrap is a tonne of mine demand that does not need to happen — and, symmetrically, a tonne of refined demand that gets met without drawing on exchange inventories.

US policy complicates this channel in a way unique to this cycle. The April 2026 Section 232 action imposed export controls on high-quality scrap alongside the semi-finished tariffs [S8]. The US is a structural scrap exporter; trapping high-grade scrap onshore partially offsets the 1.6 Mt cathode stockpile as a domestic supply buffer, but it starves the ex-US scrap market — including Chinese smelters whose feed is already squeezed by the concentrate deficit. The scrap export control is thus, perversely, an ex-US bullish force even as it adds supply inside the US.

### Demand destruction: the record price as its own worst enemy

Demand destruction in copper is slow-acting — utilities commission grids on multi-year cycles, EV platforms are designed years ahead — but it compounds. they redesign it, thin the copper, extend procurement, and accelerate scrap recovery.

## 6. The US Tariff Wildcard: Section 232, the COMEX–LME Spread and the 1.6 Mt Stockpile

This chapter works through the tariff architecture, the market-implied probabilities, the stockpile mechanics, the litigation tail, and what each policy path means for the price we are forecasting.

### The Tariff Architecture: From Semi-Finished Wall to a Refined-Copper Trigger

The framework was built in three moves, each faster than the industry expected.

The third move is the one still pending.

### What the Market Is Pricing: The COMEX Premium as a Real-Time Tariff Gauge

Because refined cathode remains untariffed while the decision pends, the COMEX premium over fully delivered LME metal has become, in effect, a traded referendum on the president's next move. CNBC framed it exactly this way in August 2026: a niche copper arbitrage position functioning as a real-time gauge of the tariff decision [S18].

Every month of delay lets that inflow continue, building the domestic buffer; announcing the tariff ends the pull and hands windfall profits to those who already stockpiled.

This report treats the market-implied probability as a floor rather than a point estimate. The risk-neutral market price, meanwhile, is distorted by the same flows it is trying to measure.

### The Stranded 1.6 Mt Stockpile and the 640 kt Ex-US Deficit

The most consequential distortion is physical. The mechanics matter for the LME price: metal sitting in US warehouses cannot arbitrage back into the ex-US system while the tariff threat persists, because re-exporting it would forfeit the option value of holding it inside the wall. It is stranded not by law but by expectation.

This is why LME warehouse stocks tell a deliberately misleading story. Falling exchange inventories against record prices is consistent with metal being pulled outside LME sheds and into the US ahead of tariffs, leaving the exchange's inventories a residue of a geography-distorted system rather than a clean global balance signal.

The redistribution has a second-order demand effect that works in the opposite direction of the first. Higher domestic US prices for fabricated product therefore partly substitute *toward* imported finished goods and *away* from domestic fabrication, a subtle leakage that erodes the tariff's reshoring logic and gives the administration one more reason to hesitate before extending protection to refined cathode.

### The Spread, the Curve and the Calendar Cliff

That compression is the market unwinding the arbitrage as the tariff decision kept not arriving: if refined cathode stays untariffed, the economic premium of US-delivered metal collapses toward transport cost, and the stranded stockpile begins to look for exits.

Two tariff paths, two spread outcomes:

The forward curve currently leans mildly toward the second path.

### The Litigation Tail: The Court of International Trade Option

The final wildcard is legal. A general challenge to the April 2026 proclamation is pending before the US Court of International Trade, which has the power to invalidate tariff actions. [S52] A court decision striking down or narrowing the Section 232 copper framework would, in one stroke, release the stranded stockpile onto the world market, collapse the spread, and remove the ex-US tightness premium that currently supports the record price. [S52]

Conversely, the administration's own vulnerabilities — inflationary side effects of metal tariffs, appellate reversal risk — cut toward delay and muddle-through rather than clean escalation, which is precisely what the near-flat COMEX curve shows the market expecting.

### What This Means for the 31 December 2027 Price

Synthesising the policy paths against the price scenarios of this report:

## 7. Contested Evidence: Where the Data Conflict

Every copper forecast is only as good as the data underneath it, and in late 2026 the most load-bearing numbers in the copper market are actively disputed. This chapter does not re-litigate the supply-and-demand narrative of Chapters 2–6; instead it interrogates the evidence base itself. (2) the reference price and stock data, where the LME's official prints and the most widely used free mirror disagree on the same day; and (4) the US stockpile estimate, a single-origin figure that anchors the entire ex-US tightness argument. Each conflict is quantified below, and each one widens the forecast distribution developed in Chapter 8 rather than narrowing it.

### The Balance Forecast That Cannot Stand Still

The single most consequential dispute in copper analytics is the 2026 refined market balance. [S37] Three estimates are currently in circulation for the same calendar year:

- **Cochilco, October 2026:** a 2026 surplus of 225,000 t, alongside a raised 2026 average price forecast of US$5.95/lb [S28]

The first point to make is that these are not small disagreements. Put differently: the revision that ICSG has already made to a single year's balance within twelve months exceeds two-thirds of the surplus on which the bear case rests.

The mechanism behind the swing is instructive. ICSG's October 2025 deficit view assumed that the concentrate shortage — now estimated by S&P Global at 530,000 t for 2026 [S15] — would transmit into refined output.

Cochilco's forecast serves Chilean fiscal planning and leans on Chilean production data; ICSG aggregates globally with a lag. Neither is "wrong" — they measure overlapping but not identical constructs, with different treatment of secondary copper (where ICSG explicitly forecasts a boost [S29]) and Chinese statistical distortions.

A steelman of the ICSG number deserves acknowledgment: the 2026 surplus materialized *despite* the concentrate deficit, which suggests refined supply is less hostage to mine output than the bulls assume, and the 2027 surplus simply extends a trend already visible in the data rather than depending on a new assumption.

### Whose Price Is It Anyway: LME Official vs the Mirror

The second dispute is smaller in magnitude but troubling because it concerns the resolution source for this report's own forecast. On 22 October 2026:

This report therefore anchors all resolution criteria to the LME's own published table, with Westmetall used only for historical monthly averages and stock series where the LME's free tier does not reach [S12]. The likely causes — snapshot timing within the pricing window, and Westmetall's unofficial status unconfirmed against the LME's published table — do not indicate manipulation, but they do mean that any reader back-testing this report's forecasts must match the resolution source precisely.

The stock data carry a parallel issue with larger analytical stakes.

### Three TC/RC Indices, Three Different Markets

The spot treatment-charge picture — the single best real-time gauge of the concentrate bottleneck — is currently reported at three irreconcilable levels:

None of the three is wrong; each measures a different slice of a market that has become extremely segmented because there is very little material to assess.

All three indices being negative at once is historically unprecedented and is the strongest single piece of evidence that the concentrate deficit is real regardless of which refined-balance vintage one believes.

### The 1.6 Mt Stockpile That Anchors the Bull Case

The most important single-origin number in the market is the estimate of roughly **1.6 million tonnes of copper stockpiled in the United States** ahead of a possible refined tariff.

This report's treatment is to condition on the observable rather than the estimate: US monthly import run-rates and the COMEX curve shape are verifiable in real time, the stockpile estimate is not.

### How These Conflicts Widen the Distribution

The four disputes compound rather than offset.

## 8. Scenarios and Probabilities for 31 December 2027

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/copper-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

### The Forecast at a Glance: Four Mutually Exclusive Scenarios

The December 2027 COMEX contract printed no trade on 22 October 2026, so no instrument directly prices the horizon; the forecast must be built from fundamentals, and the distribution below is this report's estimate.

The four scenarios, mutually exclusive and exhaustive:

| Scenario | End-2027 LME cash (USD/t) | Probability | Core mechanism |
|---|---|---|---|
| Sustained supercycle | — | — | Concentrate deficit persists; no Cobre Panama restart; smelter cuts bite |
| Elevated plateau | — | — | New supply ramps meet resilient electrification demand |
| Mean reversion | — | — | ICSG surplus materializes; sell-side forecasts proved right or overshooting |
| Hard-landing collapse | — | — | Named macro catalyst (recession or tariff-war demand shock) plus supply recovery |

The statistical frame supports a wide distribution rather than a point call.

### Scenario 1 — Sustained Supercycle (>14,000 USD/t, 20%)

Its supporting evidence is real and current: S&P Global estimates a 530,000 t 2026 concentrate deficit [S15]; Cobre Panama remains shuttered, with a commission only recommending negotiations on 30 September 2026 [S37];

The mechanism runs through refined supply, not mine supply directly. Deeply negative treatment charges force smelter cuts; cuts convert a projected refined surplus into a deficit; One market analysis argues exactly this: falling LME stocks can keep copper above $14,000/t [S56].

### Scenario 2 — Elevated Plateau, the Most Likely Path (10,500–14,000 USD/t, 45%)

This scenario reconciles the two competing supply stories.

### Scenario 4 — Hard-Landing Collapse (<7,500 USD/t, 5%)

A Court of International Trade ruling striking down Section 232 could trigger exactly that release. [S52] Five percent, not more.

### The Most-Likely Trajectory, Quarter by Quarter

1. If the benchmark settles at or near zero again, the spike extends;
2. **Q2 2027 (12,500–14,000/t).**
3. **Q3 2027 (11,500–13,000/t).** continued stalemate holds the upper half.

### Why Not the Bull Case: Steelmanning the Sustained Supercycle

The strongest argument against this report's center of gravity deserves direct statement. the concentrate deficit is structural — grades at Chuquicamata and Ministro Hales, El Teniente restrictions, and a multi-year project pipeline cannot respond to price signals quickly;

The report's response is that the two forces are not symmetrical in timing. The plateau scenario does not deny the structural story; it prices its timing. That combination is plausible; it is not the most likely single path.

## 9. Ten Binary Forecasts with Thresholds, Probabilities and Resolution Criteria

The scenario architecture of Chapter 8 collapses a very wide distribution into four price bands. But scenario probabilities are only useful if they can be falsified in real time, against named documents, on dated calendars. This chapter therefore converts the scenario logic into twelve discrete binary forecasts, each with a threshold, a probability (this report's estimate, not a market quote), and a resolution source anchored to a verifiable publication. Where a market-implied probability exists in the evidence — notably Societe Generale's tariff modelling — it is quoted as such and used as an external reference point against which this report's numbers are calibrated.

### Price-Level Forecasts on the Resolution Date

The resolution instrument is the LME Official Prices page, which publishes the cash settlement (contract CA, fixed in the second Ring session and released between 12:20 and 13:25 London time); [S1]

This is one of the few forecasts where the historical base rate and the sell-side consensus agree.

The threshold is therefore a genuine coin-flip weighted slightly by the tariff-pull persistence.

### Supply-Side Forecasts: The Benchmark, the Restart and the Ramp

Bloomberg's 22 October 2026 report that Chinese smelters plan deeper output cuts ahead of the fee talks is direct evidence they intend to negotiate from scarcity, not abundance [S44].

The 30 September 2026 commission recommendation is explicitly structured to end arbitration and finance a phased closure, not a permanent restart [S37]; President Mulino has only said he will study the report, and no scope, timing or legal structure has been settled. Traders should not conflate the announcement with the tonnes. verifiable against First Quantum's investor-relations disclosures, Reuters coverage of Panama–First Quantum negotiations [S37] and BNamericas monitoring of Panamanian government announcements. A signed restart agreement without commercial output resolves NO; a Panamanian presidential decree authorizing restart without subsequent production also resolves NO.

The main downside risks are seismic-recovery execution at Kakula and single-district DRC infrastructure concentration, both of which already forced the "recovery plan" framing of the guidance itself. Resolution: Ivanhoe 2027 annual production report [S38].

Resolution: Cochilco monthly/annual production statistics.

### Policy and Market-Structure Forecasts

Resolution: Federal Register proclamation; CRS product IN12614 tracks implementation.

Note the measurement dispute: the spread's level differs by assessment date and contract leg, so resolution should fix the calculation as CME HG front-month settlement versus LME cash settlement on the same day. Resolution: CME and LME settlement data.

### How the Twelve Forecasts Hang Together

These are not twelve independent bets; they form a dependency web whose correlations matter for anyone using them as a portfolio.

The single sharpest falsification asymmetry sits in F7. That is why a monthly Cochilco print, a routine statistic, carries more scenario-discriminating power for this forecast than any analyst note in the record.

## 10. Turning Points, Watchlist and Decision Implications

Each of these will, on the evidence assembled in this report, either confirm or falsify one of the four scenarios within a few months of occurrence. This chapter converts that calendar into a practical watchlist with explicit thresholds, and closes with what each scenario implies for producers, consumers and investors.

### The 2027 decision calendar: five dated inflection points

a definitive rejection would release stranded US metal onto the world market and compress it.

**H1 2027: Panama.** continued stalemate removes the largest single source of potential supply relief and supports prices staying high. First Quantum wants the restart; the veto is President Mulino's, and the arbitration overhang constrains both sides.

### The watchlist: thresholds that upgrade or falsify each scenario

Four leading indicators, each with verifiable resolution sources, carry most of the discriminating power:

- **Spot TC/RCs (Argus).**
- **LME warehouse stocks and the cash–3M spread.**
- **COMEX curve shape and the COMEX–LME spread.**
- **US monthly import run-rates.**

### Decision implications: producers, consumers, investors

**For producers and mine developers**, the calculus is asymmetric. it also illustrates that volume shortfalls, not price, have been the state miner's real risk.

Antofagasta's shift toward spot/index-linked settlements transfers price risk onto smelters;

**For industrial consumers and procurement**, the practical exposure is twofold: the LME level and the COMEX–LME spread. if it does not, the stranded stockpile releases and US premia collapse.

**For investors**, the position is not a directional bet on copper but a bet on which scenario breaks first. with US capacity utilization at 76.85% and rising y/y [S10], none is currently visible, so it stays a tail to monitor via monthly macro prints rather than a case to position for.

A zero-or-negative benchmark, a tariff proclamation, and falling LME stocks together would force an upgrade of the supercycle path; a leaked CSPT quota, an ICSG surplus confirmation, and a Cobre Panama signature would force the opposite.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/copper-2027/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[33%] Elevated plateau (10,500-14,000 USD/t)**: FRED PCOPPUSDM monthly value for 2026-12... corrected: for 2027-12 falls within 10,500-14,000 USD/t (cross-checked against LME Official Cash Settlement on 31 December 2027 within the same band).
- **[39%] Sustained highs / status quo (>14,000 USD/t)**: FRED PCOPPUSDM monthly value for 2027-12 is at or above 14,000 USD/t, cross-checked against LME Official Cash Settlement on 31 December 2027 at or above 14,000 USD/t.
- **[22%] Mean reversion (7,500-10,500 USD/t)**: FRED PCOPPUSDM monthly value for 2027-12 is within 7,500-10,500 USD/t, cross-checked against LME Official Cash Settlement on 31 December 2027 below 10,500 USD/t.
- **[6%] Hard landing (<7,500 USD/t)**: FRED PCOPPUSDM monthly value for 2027-12 is below 7,500 USD/t, cross-checked against LME Official Cash Settlement on 31 December 2027 below 7,500 USD/t.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Global price of Copper (fred:PCOPPUSDM) | next monthly release after 2026-09 | — |
| imf:PCPS/G001.PCOPP.USD.A (imf:PCPS/G001.PCOPP.USD.A) | next annual release after 2025 | — |
| EIA: Retail Sales of Electricity: U.S. total, all sectors (usgov:eia/electricity_sales/US.ALL) | next monthly release after 2026-08 | — |
| Capacity Utilization: Total Index — United States (fred:TCU) | next monthly release after 2026-09 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Capacity Utilization: Total Index — United States (fred:TCU) | 76.85% (2026-09) | > 75% / 2027-12 | 78% (n=104, h=15) vs model 75% | [Source](<https://fred.stlouisfed.org/series/TCU>) [S10] |
| EIA: Retail Sales of Electricity: U.S. total, all sectors (usgov:eia/electricity_sales/US.ALL) | 412568.3744 Million kilowatt-hours (2026-08) | > 340000 Million kilowatt-hours / 2027-12 | 83% (n=102, h=16; same-month seasonal mean plus pooled deviations, not seasonally adjusted) vs model 85% | [Source](<https://www.eia.gov/electricity/data/browser/>) [S9] |

<!-- drf-news-market-context:7d292b255681aef7d4c872d0463ecb370e3d48223eacad517d6bf8e76211fac8:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:7d292b255681aef7d4c872d0463ecb370e3d48223eacad517d6bf8e76211fac8:end -->

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
| Scenarios (multiclass) | 4 | 0 | 4 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 11 | 0 | 11 | — |
| Unanchored binaries | 44 | 0 | 44 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S3] Global price of Copper — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/PCOPPUSDM](https://fred.stlouisfed.org/series/PCOPPUSDM)
2. [S9] EIA: Retail Sales of Electricity: U.S. total, all sectors — eia.gov — [https://www.eia.gov/electricity/data/browser/](https://www.eia.gov/electricity/data/browser/)
3. [S10] Capacity Utilization: Total Index — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/TCU](https://fred.stlouisfed.org/series/TCU)
4. [S44] Chinese Copper Smelters Plan Deeper Output Cuts as Costs Rise, Prices Fall - Bloomberg — bloomberg.com — [https://www.bloomberg.com/news/articles/2026-10-22/chinese-copper-smelters-plan-more-output-cuts-ahead-of-fee-talks](https://www.bloomberg.com/news/articles/2026-10-22/chinese-copper-smelters-plan-more-output-cuts-ahead-of-fee-talks)
5. [S15] Peru's Copper Push Arrives Too Late for a 530,000-Tonne Concentrate Deficit - Article | Crux Investor — cruxinvestor.com — [https://www.cruxinvestor.com/posts/perus-copper-push-arrives-too-late-for-a-530-000-tonne-concentrate-deficit](https://www.cruxinvestor.com/posts/perus-copper-push-arrives-too-late-for-a-530-000-tonne-concentrate-deficit)
6. [S5] Chile's Codelco posts stronger profit on copper rally as mine disruptions... — reuters.com — [https://www.reuters.com/world/americas/chiles-codelco-posts-stronger-profit-copper-rally-mine-disruptions-drag-output-2026-08-28/](https://www.reuters.com/world/americas/chiles-codelco-posts-stronger-profit-copper-rally-mine-disruptions-drag-output-2026-08-28/)
7. [S28] Chile's Cochilco Raises 2026 Copper Price Forecast — industrialinfo.com — [https://www.industrialinfo.com/news/article/chiles-cochilco-raises-2026-copper-price-forecast--361453](https://www.industrialinfo.com/news/article/chiles-cochilco-raises-2026-copper-price-forecast--361453)
8. [S37] Panama panel recommends First Quantum mine restart to fund phased closure | Reuters — reuters.com — [https://www.reuters.com/business/panama-commission-recommends-reopening-first-quantum-mine-order-gradually-close-2026-09-30/](https://www.reuters.com/business/panama-commission-recommends-reopening-first-quantum-mine-order-gradually-close-2026-09-30/)
9. [S38] Ivanhoe Mines Announces Kamoa-Kakula Copper Production Guidance for 2026 and 2027 as Recovery Plan Advances — finance.yahoo.com — [https://finance.yahoo.com/news/ivanhoe-mines-announces-kamoa-kakula-111000741.html](https://finance.yahoo.com/news/ivanhoe-mines-announces-kamoa-kakula-111000741.html)
10. [S33] Chile to lift copper output 6% in next decade, with peak in 2027 | Reuters — reuters.com — [https://www.reuters.com/markets/commodities/chile-lift-copper-output-6-next-decade-with-peak-2027-2025-01-15/](https://www.reuters.com/markets/commodities/chile-lift-copper-output-6-next-decade-with-peak-2027-2025-01-15/)
11. [S41] Teck seeks approval from China for merger with Anglo and improves... — bnamericas.com — [https://www.bnamericas.com/en/features/teck-seeks-approval-from-china-for-merger-with-anglo-and-improves-copper-in-chile-and-peru](https://www.bnamericas.com/en/features/teck-seeks-approval-from-china-for-merger-with-anglo-and-improves-copper-in-chile-and-peru)
12. [S39] Anglo-Teck merger, nickel sale are test cases for navigating... - Reuters — reuters.com — [https://www.reuters.com/world/asia-pacific/anglo-teck-merger-nickel-sale-are-test-cases-navigating-geopolitical-2026-10-07/](https://www.reuters.com/world/asia-pacific/anglo-teck-merger-nickel-sale-are-test-cases-navigating-geopolitical-2026-10-07/)
13. [S6] Global copper surplus to more than triple by 2027: ICSG - MINING.COM — mining.com — [https://www.mining.com/global-copper-surplus-to-more-than-triple-by-2027-icsg/](https://www.mining.com/global-copper-surplus-to-more-than-triple-by-2027-icsg/)
14. [S45] CSPT Smelter Cuts’ Impact on China Copper Demand in 2026 - CRU Group — crugroup.com — [https://www.crugroup.com/en/communities/thought-leadership/2025/How-CSPT-smelter-cuts-could-reshape-Chinas-copper-demand-in-2026/](https://www.crugroup.com/en/communities/thought-leadership/2025/How-CSPT-smelter-cuts-could-reshape-Chinas-copper-demand-in-2026/)
15. [S43] China Copper Cathode Output Falls Amid Maintenance and Supply... — linkedin.com — [https://www.linkedin.com/posts/amalgamated-metal-corporation_chinas-copper-cathode-production-drops-in-activity-7511331190671380481-BTsh](https://www.linkedin.com/posts/amalgamated-metal-corporation_chinas-copper-cathode-production-drops-in-activity-7511331190671380481-BTsh)
16. [S42] China's sulfuric acid export ban unlikely to suppress short-term... — mysteel.net — [https://www.mysteel.net/analysis/5125029-chinas-sulfuric-acid-export-ban-unlikely-to-suppress-short-term-copper-smelting-profit](https://www.mysteel.net/analysis/5125029-chinas-sulfuric-acid-export-ban-unlikely-to-suppress-short-term-copper-smelting-profit)
17. [S30] Chinese Smelters Pay Miners for Copper Concentrate as Mine Supply Becomes the Key Constraint - Article | Crux Investor — cruxinvestor.com — [https://www.cruxinvestor.com/posts/chinese-smelters-pay-miners-for-copper-concentrate-as-mine-supply-becomes-the-key-constraint](https://www.cruxinvestor.com/posts/chinese-smelters-pay-miners-for-copper-concentrate-as-mine-supply-becomes-the-key-constraint)
18. [S21] Copper Prices Outlook | J.P. Morgan Global Research — jpmorgan.com — [https://www.jpmorgan.com/insights/global-research/commodities/copper-outlook](https://www.jpmorgan.com/insights/global-research/commodities/copper-outlook)
19. [S49] Grids - Electricity 2026 - IEA — iea.org — [https://www.iea.org/reports/electricity-2026/grids](https://www.iea.org/reports/electricity-2026/grids)
20. [S25] Why Record-High Copper Prices Aren’t Forecast to Last | Goldman Sachs — goldmansachs.com — [https://www.goldmansachs.com/insights/articles/why-record-high-copper-prices-arent-forecast-to-last](https://www.goldmansachs.com/insights/articles/why-record-high-copper-prices-arent-forecast-to-last)
21. [S8] Section 232 National Security Tariffs on Copper Imports | Congress.gov | Library of Congress — congress.gov — [https://www.congress.gov/crs-product/IN12614](https://www.congress.gov/crs-product/IN12614)
22. [S18] This copper bet became a real-time gauge of Trump’s next tariff move — cnbc.com — [https://www.cnbc.com/2026/08/14/copper-trump-tariffs-metal-commodities-trade-war.html](https://www.cnbc.com/2026/08/14/copper-trump-tariffs-metal-commodities-trade-war.html)
23. [S52] President Trump Makes Major Changes to Section 232 Tariffs on Aluminum, Steel, and Copper | SmarTrade — thompsonhinesmartrade.com — [https://www.thompsonhinesmartrade.com/2026/04/president-trump-makes-major-changes-to-section-232-tariffs-on-aluminum-steel-and-copper/](https://www.thompsonhinesmartrade.com/2026/04/president-trump-makes-major-changes-to-section-232-tariffs-on-aluminum-steel-and-copper/)
24. [S29] ICSG forecasts secondary copper output boost - Recycling Today — recyclingtoday.com — [https://www.recyclingtoday.com/news/copper-icsg-recycling-output-refining-supply-demand-2026-2027/](https://www.recyclingtoday.com/news/copper-icsg-recycling-output-refining-supply-demand-2026-2027/)
25. [S12] westmetall. market data. prices/lme stocks. copper, tin, lead, zinc, aluminium, nickel, gold, fine silver — westmetall.com — [https://www.westmetall.com/en/markdaten.php?action=averages&field=LME_Cu_cash](https://www.westmetall.com/en/markdaten.php?action=averages&field=LME_Cu_cash)
26. [S56] Why Falling LME Stocks Can Keep Copper Above $14,000 After Expiry — cruxinvestor.com — [https://www.cruxinvestor.com/posts/why-falling-lme-stocks-can-keep-copper-above-14-000-after-expiry](https://www.cruxinvestor.com/posts/why-falling-lme-stocks-can-keep-copper-above-14-000-after-expiry)
27. [S1] LME Official Prices | London Metal Exchange — lme.com — [https://www.lme.com/market-data/reports-and-data/lme-official-prices](https://www.lme.com/market-data/reports-and-data/lme-official-prices)
