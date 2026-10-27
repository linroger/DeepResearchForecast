# AI Infrastructure at the Physical Frontier: 2027 Hyperscaler Capex, Datacenter Electricity Demand, and the Grid Interconnection Bottleneck

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/ai-capex-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | Global datacenter electricity consumption grows more than 20% year-over-year in calendar 2027. | 20% | Resolves YES if the IEA (or LBNL) published 2027 global datacenter electricity estimate shows 2027 vs 2026 growth >20%, resolved by 2028-12-31. | ai | — |
| F2 | More than 5 GW of planned US datacenter capacity scheduled for 2027 is confirmed delayed into 2028. | 55% | Resolves YES if utility/regulatory filings or credible industry trackers (e.g., Goldman Sachs/Aterio facility data) document >5 GW of US datacenter capacity with planned 2027 operation slipping into 2028, resolved by 2028-12-31. | ai | — |
| F3 | Combined calendar-2027 capex of Amazon, Microsoft, Alphabet and Meta exceeds $950 billion per company filings. | 20% | Resolves YES if the sum of Amazon+Microsoft+Alphabet+Meta reported CY2027 capex from 10-Ks/filings exceeds $950 billion, resolved by 2028-12-31. | ai | — |
| F4 | Combined calendar-2027 capex of the four hyperscalers falls below $720 billion, under the floor of 2026 guidance. | 6% | Resolves YES if the sum of Amazon+Microsoft+Alphabet+Meta reported CY2027 capex from company filings is below $720 billion, resolved by 2028-12-31. | ai | — |
| F5 | GE Vernova reports at least 125 GW of gas power capacity under contract by end-2026. | 70% | Resolves YES if GE Vernova's Q4 2026 earnings release (published by 2027-02-28) states gas power equipment capacity under contract of at least 125 GW as of end-2026. | ai | — |
| F6 | The IEA's 2026 global datacenter electricity estimate prints at least 582 TWh, i.e. 20% growth over the 485 TWh 2025 base. | 28% | Resolves YES if the IEA's published 2026 global datacenter electricity consumption estimate is ≥582 TWh (485 × 1.2), when published by 2027-12-31. | ai | — |
| F7 | EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/US.COM#yoy) is at least 8% in December 2027. | 12% | Resolves YES if usgov:eia/electricity_sales/US.COM#yoy >= 8 (Percent change from year ago) in 2027-12 (source: EIA). | ai | — |
| F8 | EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/VA.COM#yoy) is at least 15% in December 2027. | 35% | Resolves YES if usgov:eia/electricity_sales/VA.COM#yoy >= 15 (Percent change from year ago) in 2027-12 (source: EIA). | ai | — |
| F9 | EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/US.COM#yoy) is at most 3% in December 2027. | 62% | Resolves YES if usgov:eia/electricity_sales/US.COM#yoy <= 3 (Percent change from year ago) in 2027-12 (source: EIA). | ai | — |
| F10 | Combined calendar-2027 capital expenditure of Amazon, Microsoft, Alphabet and Meta exceeds $950 billion per their company filings. | 20% | Resolves YES if the sum of Amazon, Microsoft, Alphabet and Meta reported calendar-2027 capital expenditure in 10-K/Q4 filings exceeds $950 billion by 2028-12-31 (source: company SEC filings). | ai | — |
| F11 | EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/VA.COM#yoy) is at least 12% in December 2026. | 30% | Resolves YES if usgov:eia/electricity_sales/VA.COM#yoy >= 12 Percent change from year ago in 2026-12 (source: EIA electricity data browser). Official resolution: usgov:eia/electricity_sales/VA.COM#yoy >= 12% for 2026-12. | ai | 43% (n=228, h=12) |
| F12 | EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/US.COM#yoy) is at least 5% in December 2026. | 45% | Resolves YES if usgov:eia/electricity_sales/US.COM#yoy >= 5 Percent change from year ago in 2026-12 (source: EIA electricity data browser). Official resolution: usgov:eia/electricity_sales/US.COM#yoy >= 5% for 2026-12. | ai | 41% (n=235, h=5) |
| F13 | Combined calendar-2026 capital expenditure of Amazon, Microsoft, Alphabet and Meta exceeds $745 billion, above the top of current guidance, per company filings. | 55% | Resolves YES if the sum of the four hyperscalers' reported calendar-2026 capital expenditure in Q4 2026 filings exceeds $745 billion by 2027-03-31 (source: company SEC filings). | ai | — |
| F14 | Global datacenter electricity consumption grows by less than 15% year-over-year in calendar 2027, below the IEA central path, per the IEA's published estimate. | 18% | Resolves YES if the IEA's published 2027 global datacenter electricity estimate shows 2027 vs 2026 growth below 15% by 2028-12-31 (source: IEA Energy and AI / Key Questions on Energy and AI publications). | ai | — |

_14 forecasts; 9 high-conviction (≥70% or ≤30%); 14 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Real Personal Consumption Expenditures — United States | Percent Change from Preceding Period | 3.8% | 2026-Q2 | +1.7 pp | 0.4% to 14.8% | — | [S16] |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector | Million kilowatt-hours | 150578.728 | 2026-07 | +6215.5814 (+4.306%) | 103062.6212 to 150578.728 | — | [S15] |
| Gross domestic product (GDP), Constant prices, Percent change: United States | Percent change | 2.952% | 2024 | +0.033 pp | -2.081% to 6.268% | 2.293% (2027, publisher projection) | [S4] |
| EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) | Percent change from year ago | 9.788% | 2025-12 | +5.311 pp | -6.782% to 27.222% | — | [S11] |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) | Percent change from year ago | 4.306% | 2026-07 | +0.857 pp | -2.122% to 8.715% | — | [S10] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/ai-capex-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S11]; Percent change from year ago; Monthly; NSA · [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S10]; Percent change from year ago; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DPCERL1Q225SBEA>) [S16]; Percent Change from Preceding Period; Quarterly; SAAR · [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S15]; Million kilowatt-hours; Monthly; NSA · [World Bank Data360](<https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH>) [S4]; Percent change; Annual; adjustment unknown*

<!-- viz:charts/official_series_lrcfpdtkbbaebrad.html -->
![Official Series History and Forecast Thresholds](demos/ai-capex-2027/charts/official_series_lrcfpdtkbbaebrad.png)

*Official Series History and Forecast Thresholds*

*Source: [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S11]; Percent change from year ago; Monthly; NSA*

<!-- viz:charts/official_series_tnkmpoktefcqlstm.html -->
![Official Series History and Forecast Thresholds](demos/ai-capex-2027/charts/official_series_tnkmpoktefcqlstm.png)

*Official Series History and Forecast Thresholds*

*Source: [U.S. Energy Information Administration (EIA)](<https://www.eia.gov/electricity/data/browser/>) [S10]; Percent change from year ago; Monthly; NSA*

## Part 2 — Framework & Synthesis

### Framework and Synthesis

This chapter consolidates the forecast's analytical machinery: the causal spine connecting hyperscaler capital expenditure, datacenter electricity growth, and interconnection delays; the evidence that discriminates among scenarios; and the treatment of prediction-market anchors. The central analytical claim is that these three quantities are not independent questions. They are one physical-financial system observed at three points, and the Part-1 probabilities follow from modeling that system rather than polling its components separately.

### The Single System: Money, Megawatts, and Queues

The causal chain runs in one direction with feedback. Hyperscaler capex (Amazon, Microsoft, Alphabet, Meta) converts into orders for shells, servers, and power equipment; that equipment converts into datacenter floor space; Money is abundant; transformers, gas turbines, and interconnection queue positions are not.

This is why the three headline predictions cohere. A plateau in energized capacity is fully compatible with record capital expenditure, because the money arrives faster than the megawatts. The scenario analysis treats "capex is high" and "power growth is throttled" not as a contradiction but as the expected signature of a power-constrained buildout.

### Why the Consensus Path Carries 45%

First, the financial engine is intact but decelerating in growth-rate terms. Hyperscaler operating cash flow continues to cover the majority of capex, but the shift toward financing structures — SPVs, vendor financing, and debt issued at the subsidiary and JV level — signals that companies are stretching balance sheets to sustain guidance rather than expanding it without limit. This is the behavior of firms managing toward a consensus number, not overshooting it.

Second, the physical evidence supports electricity growth just under the surge threshold. The stored official data shows US commercial-sector electricity retail sales at 150,578.728 million kWh for 2026-07, up 4.306% year over year [S15] — a solid but not explosive pace for the sector as a whole, of which datacenters are the fastest-growing component. Virginia, the densest datacenter market, shows commercial electricity sales up 9.788% year over year as of 2025-12 [S11], having decelerated from the 27.222% peak in the stored five-year window (2023-03). That deceleration in the leading market is precisely what a queue-constrained system looks like: the front of the queue is energized; the back waits.

Third, demand-side macro conditions are stable. A stable consumer economy sustains cloud and AI monetization narratives, keeping capex near consensus rather than forcing either a cut or an accelerando.

### Why the Surge Gets Only 20%

The conjunctive structure of the resolution criterion is the analytical reason for the moderate probability.

Each condition alone is plausible.

### Why the Slowdown Also Gets 20%

It requires the constraint to bind hard enough to pull capex below consensus, not merely to slow energization.

Historically, hyperscalers facing infrastructure bottlenecks re-time spending rather than cancel it — they shift between sites, pre-buy equipment, and reclassify projects — because the competitive logic of the AI race punishes unilateral restraint. A genuine sub-$850B outcome therefore requires an additional financial trigger on top of physical constraint: a debt-market repricing of datacenter financing vehicles, a visible AI-monetization disappointment, or a credit event in the SPV/JV complex. Each is credible;

### The Residual Bin and Why It Is Not Noise

The named scenarios have conjunctive resolution criteria, and conjunctions fail more often than intuition suggests. such mixed outcomes are common in systems with multiple bottlenecks operating at different lags. Our scenario analysis explicitly declines to force every outcome into a clean bin.

### Decisive Evidence and Discriminating Observations

Four evidence streams do most of the probability-discriminating work.

*Company filings and guidance revisions.* 10-K capex disclosure is the resolution instrument for the capex questions, and the trajectory of quarterly guidance through 2026–2027 is the leading indicator. [S1] Continued upward revisions favor the surge; guidance plateaus favor the consensus band; any mention of deferral language paired with financing-structure strain favors the slowdown.

*Financing conditions.* The composition of capex funding — the ratio of operating cash flow to debt-financed and off-balance-sheet spending — is the earliest warning of the slowdown scenario. As long as the debt market prices datacenter paper without punitive spreads, the plateau holds; a widening of spreads on datacenter SPVs is the trigger to upgrade the slowdown's probability.

They do not discriminate among the three named scenarios but they suppress the probability of demand-driven collapse below what pure supply-side analysis would suggest.

### Treatment of Prediction-Market Anchors

Where prediction-market prices exist for adjacent questions — hyperscaler capex thresholds, AI-capex levels, utility load growth — our scenario analysis used them as calibration anchors, not as forecasts to be copied. Three rules governed their use.

First, markets were downweighted where resolution criteria diverge from ours. blind adoption would import definitional error larger than the informational value.

Second, markets were used to check tail calibration rather than central tendency. Where markets implied a materially higher probability of extreme outcomes than our scenarios, we examined whether our named bins were underweighted;

Third, absence of a market anchor was treated as neutral. No adjustment was made to any scenario probability purely because a market was silent on it. Where anchors were present and credible, they modestly reinforced the plateau weighting and did not conflict with the 20/20 split between surge and slowdown — the market-anchored picture is symmetric around a consensus center, which matches the structural symmetry of our causal logic: both deviations from consensus require an additional trigger beyond the base mechanism.

### Confidence and Falsifiability

Overall confidence in this forecast is low, stated deliberately. The system being forecast contains a commodity — grid equipment — with multi-year lead times being ordered at unprecedented scale by counterparties whose incentives change quarterly; historical base rates for trillion-dollar capex programs and for global electricity-growth inflections of this size are thin. The scenario probabilities are defended as the best-structured allocation of that uncertainty, not as precise measurements.

The forecast is falsifiable on a dated schedule. The spine's probabilities stand until that evidence — not narrative momentum — moves them.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Executive Forecast: The 2027 Triad of Capex, Electricity, and Interconnection Delay

The predictions:

Every 2027 capex figure in circulation—including the consensus this forecast anchors to—is an analyst construct that will be reset, in contagion, on the Q3 2026 earnings calls in late October and November 2026. [S3] The physical-side predictions carry firmer footing, because they are gated by equipment orders already placed and queues already joined, not by decisions still unmade. The rest of this chapter defends each number and then shows why they move together.

### Prediction 1: The Capex Band and Why It Brackets Consensus Upward

The anchor points are fixed and well documented.

That asymmetry is deliberate, and it rests on the most robust empirical pattern in this domain: consensus has persistently lagged outcomes. Guidance moves in contagion: after Alphabet's July 2026 raise, Evercore ISI's Mark Mahaney judged it more likely than not that Amazon and Microsoft would follow. [S3] Each raise resets the baseline for the others, because no hyperscaler can afford to be visibly behind in capacity while AI demand signals remain strong. When the mechanism has run one direction for two consecutive years, the burden of proof falls on the reversal case.

The lower edge of the interval is not arbitrary.

The forecast refers to **cash capital expenditures including finance-lease principal repayments as reported in each company's 10-K**, excluding uncommenced commitments, guarantees and joint-venture exposures. [S12]

### Prediction 2: Why 15–20% Electricity Growth Is the Central Call

The electricity prediction is the forecast's most contrarian element relative to its own capex headline, and the tension between the two is the report's core analytical claim.

The historical base rate is starker still.

The mechanism is the physical conversion chain, and it runs through one gatekeeper above all. Capex becomes consumed electricity only through turbines, transformers, and interconnection agreements that operate on multi-year clocks.

Money compounds annually; steel and copper do not.

### Prediction 3: The ~75% Call on More Than 5 GW of Delay

The slippage prediction is the most confident of the three, and its arithmetic is the simplest.

Because the strongest counterargument deserves real weight. SemiAnalysis contends that "half cancelled" framings overstate risk by sampling the most cancellation-prone, speculative slice of the pipeline rather than aggregate on-time rates. But the critique cannot carry the threshold itself, because delay does not require speculative projects. Selection bias cannot explain away an administrative pause. Each element is individually plausible; jointly they require the system to outperform its own documented base rates in a single year against a fourfold step-up in the schedule.

The scenario structure distributes the risk as follows, and the triad is consistent with all four central tendencies.

### Why the Three Quantities Are Jointly Determined

The deepest claim of this forecast, and the reason this chapter presents a triad rather than three forecasts, is that capex, electricity, and slippage are one quantity measured at three points in a chain. Capex measures intent; electricity measures energization; slippage measures the gap between them. All three are governed by the same asymmetry in adjustment speeds.

Two second-order mechanisms reinforce the decoupling.

Even within the surge scenario, the binding constraints documented at the equipment and grid layers dampen how much committed spend converts into consumed terawatt-hours within the calendar year.

### The Verification Calendar and the Confidence Rating

The Q3 2026 earnings calls in late October and November 2026 deliver the first formal 2027 guidance signals—if Amazon and Microsoft follow Alphabet's raise as Evercore expected, the central band shifts upward; [S3] if they do not, the contagion mechanism weakens and the slowdown scenarios gain.

The forecast's low overall confidence rating is not an excuse; it is the honest price of predicting a year whose capex intentions have not yet been spoken and whose megawatts were, in large part, decided three years ago. The chapters that follow unpack each leg in turn: the four scenario forecasts with explicit resolution and falsification criteria; the capex engine of guidance contagion and debt-market gating; the physical ceiling of turbines and transformers; the grid friction map of PJM, ERCOT and FERC; the official EIA and IEA indicator series and their tripwires; the correlated risk architecture; and dated decision guidance for every stakeholder.

## Scenario Forecast I — Measured Growth Plateau: The Power-Constrained Consensus Path (45%)

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/ai-capex-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

<!-- viz:charts/worldstate_trajectory.html -->
![Forecast Outcome-Share Trajectory](demos/ai-capex-2027/charts/worldstate_trajectory.png)

*Forecast Outcome-Share Trajectory*

<!-- viz:charts/world_variables.html -->

It is a world in which money keeps flowing at roughly a trillion-dollar annual pace while physical infrastructure—turbines, transformers, and interconnection queues—converts that money into energized megawatts at a lag. The core mechanism is a scissors movement: guidance rises in contagion at the speed of earnings calls, while energization rises at the speed of a three-year turbine lead time.

### The Capex Band: Why $850–950 Billion Is the Modal Landing Zone

Bank models run higher: JP Morgan and Goldman Sachs each forecast AI capex of $1 trillion or more in 2027, with Evercore and Bank of America above that line as well [S2].

First, consensus has historically drifted upward toward outcomes rather than away from them.

Second, the financing mix is shifting in ways that make reported capex an increasingly imperfect proxy for economic buildout. US tech companies' future datacenter lease commitments passed $850 billion by mid-2026, led by Meta and Microsoft [S20].

Third, deployment is back-loaded.

### The Electricity Band: Why 12–20% Is More Likely Than Crossing the Threshold

The IEA's 2026 update explicitly warns that value-chain bottlenecks are "reducing the likelihood of more aggressive near-term scenarios," citing transformer and cable wait times that have doubled in three years and gas turbine lead times of several years. [S47]

This is the quantitative heart of the plateau scenario.

- heavy-duty turbine orders carry roughly three-year lead times per CEO Scott Strazik, meaning an order placed in 2026 delivers after 2027. [S47]

The official US series corroborate a below-threshold picture. Virginia, the densest datacenter load pocket, grew 9.788% YoY in December 2025 [S11].

The external base rate reinforces the point. The plateau scenario says growth runs at the top of the plausible historical range but does not break through it, because the binding constraints sit upstream of the datacenter itself.

### The Slippage Band: 5–15 GW Into 2028, and Why the Threshold Is Not the Scenario

The resolution is that the >5 GW threshold can be crossed without any of the other stall conditions holding. Slippage in the plateau world is ordinary friction: projects slip for site-specific reasons—transformer delivery dates, local transmission upgrades, gas lateral completion—while the aggregate buildout proceeds and capex keeps climbing. The distinction matters because SemiAnalysis has argued that "half cancelled" framings overstate risk by sampling the most cancellation-prone slice of the pipeline rather than aggregate on-time rates.

Two institutional dynamics set the boundaries of the band from above and below.

The same reform that delays speculative load accelerates genuine generation. That is the plateau dynamic in miniature: slower vetting, faster real projects, net slippage in the middle of the range.

### Resolution Criteria and Falsification

A steelman deserves an answer before closing. But the surge case requires the physical layer to bend, and the physical layer's own gatekeeper—GE Vernova, with slot reservations sold out toward 2029–2030 [S44]—is the one actor in this system whose incentives would favor announcing open 2027 capacity if it existed. Money can compound annually; steel and copper cannot. That asymmetry is why the plateau, not the surge, is the modal path.

## Scenario Forecast II — Continued Buildout Surge (20%)

This report assigns it 20%. The joint probability lands at roughly one in five.

### The Capex Leg: Why $1 Trillion Is Closer Than Consensus Suggests

The arithmetic case for the upside begins with how small the remaining gap is.

The bank models sit above consensus for a reason. JP Morgan and Goldman Sachs each forecast AI capex of $1 trillion or more in 2027 [S2]; Evercore ISI and Bank of America both modeled combined 2027 hyperscaler capex above $1 trillion after the Q1 2026 earnings calls [S2].

The contagion mechanism is already observable. Alphabet's July 2026 raise of its capex outlook pulled expectations for its peers upward: Evercore ISI's Mark Mahaney judged both Amazon and Microsoft likely to follow with similar raises. [S3] This is the latest documented instance of the pattern in this cycle. Each raise shifts the anchor for the others, because no hyperscaler can afford to be visibly behind in capacity while AI demand signals remain strong — the competitive structure among Amazon, Microsoft, Alphabet and Meta, in which guidance moves in contagion [S1][S3]. The late-October and November 2026 Q3 earnings calls are the first formal window in which 2027 signals will appear; [S3]

A second, quieter mechanism pushes reported capex upward: off-balance-sheet structures. The mirror-image risk for resolution matters too: if the Street's models embed JV exposure that never appears in cash capex lines, the filed numbers could disappoint even as physical construction surges. This is a definitional trap the resolution rules must respect, and it cuts both ways.

### The Demand Underwriters: OpenAI, Oracle, and Pre-Committed Compute

What distinguishes this buildout from a speculative bubble in the pure sense is that much of the demand is contractually pre-committed before the concrete is poured. Microsoft's AI capacity commitments are tied to OpenAI-anchored demand. These are not projections of hoped-for revenue;

The $3 trillion buildout is consuming debt markets, but so far the market is absorbing the supply.

### The Electricity Leg: The Base Rate Problem and the Energization Catch-Up Case

Every official proxy points below the threshold.

The steelman for the upside runs through synchronized energization, and it has four visible mechanisms:

**1. Notably, FERC's acceleration and Alphabet's guidance hike are not independent bullish signals: Alphabet's buildout pressure itself accelerates PJM's institutional response, a reinforcing loop in which more money demands faster interconnection and, at the margin, gets it.

**2. This matters because it partially bypasses the interconnection queue entirely — the single most binding constraint in the base case. Four gigawatts is not enough to carry the scenario alone, but it demonstrates a template: hyperscalers self-supplying power outside grid queues.

**3.

**4. capacity additions lead consumption with a lag, which is precisely why the scenario needs "committed power arriving on trend," not merely on schedule.

The counterargument deserves full weight: the IEA explicitly warns that value-chain bottlenecks — transformer and cable wait times that have doubled in three years, and gas turbine lead times of several years — cap aggressive near-term scenarios. The physical ceiling documented in Scenario I does not dissolve because capex rises; it binds harder, because more dollars chase the same constrained pool of turbines, transformers, and interconnection engineers. This is the structural reason the surge scenario cannot be assigned a probability proportional to the bullishness of bank models: the money leg and the megawatt leg are only loosely coupled within a single year.

### Resolution and Falsification

The scenario resolves against hard documents, not sentiment. By 31 December 2028:

- Microsoft's figures require the accounting-adjusted basis (finance leases counted at commencement), and Meta's require a judgment on whether SPV-funded Hyperion spending appears in reported capex; the resolution default is filed cash capex plus commenced finance leases.
- Early falsification signals arrive on the Q3 2026 earnings calls (late October–November 2026): if Amazon and Microsoft do *not* follow Alphabet's July raise, the contagion mechanism weakens and the surge scenario's capex leg loses its primary engine. [S3]

The surge scenario is not a bet on ambition or on analyst models — both are already maximal. It is a bet on synchronization: that in one particular calendar year, the physical delivery system performs above every documented base rate at the same moment the financial system keeps funding it, with FERC's accelerated protocols, PJM's expedited track and behind-the-meter fast gas patching just enough of the delivery gap. That conjunction is possible, partially pre-arranged by pre-committed demand, and roughly one-in-five likely.

## Scenario Forecast III — Power-Constrained Slowdown (20%)

The first two scenario chapters traced the modal consensus path and the upside surge. The chapter's central analytical task is to explain why that number is simultaneously plausible and not higher: every ingredient of the slowdown is already observable in the record, yet each has a countervailing force that has, so far, kept the buildout accelerating.

A definitional point must come first, because it does most of the work in calibrating the probability. The slowdown scenario requires something stronger: that grid friction and financing strain not merely delay megawatts but actually stall dollar commitments at or barely above 2026's $720–745 billion guidance level. [S1]

### The grid triggers: ERCOT's pause and PJM's new cost regime

Two regulatory clocks, both running during the forecast window, could convert queue friction into a genuine spending stall. The first is Texas. On 3 August 2026 the Texas governor ordered a pause on new ERCOT datacenter connections; [S40] BNEF expects the pause to last "months"; If the latter, a large slice of the national pipeline loses its fastest-growing host grid, and projects that had counted on Texas speed—ERCOT's historically light-touch process was itself part of the site-selection logic—get pushed into queues with five-year median request-to-operation times.

The second clock is PJM. The mechanism by which this stalls capex rather than merely delaying it is cost transmission: bring-your-own-capacity rules convert a datacenter from a $/MW tenant into a generation procurer, raising the all-in cost of Virginia capacity precisely when PJM has already trimmed its summer-2027 peak forecast by roughly 4 GW on stricter datacenter vetting [S36].

### The debt-market gate: from Alphabet's order book to Meta's SPV

The second trigger is financial, and it is the channel most likely to be underestimated by physical-constraint analysts. and US tech companies' future datacenter lease commitments passed $850 billion by mid-2026, led by Meta and Microsoft [S20]. All of this sits inside a buildout variously priced above $3 trillion, which has made datacenter-linked issuance, in the words of one energy-trade analysis, "all-consuming" for debt markets.

The mechanism here is a classic leverage cycle in reverse. In the surge scenario, debt appetite is an accelerant—Oracle's Stargate issuance and OpenAI-anchored compute commitments let spending run ahead of hyperscaler cash flow. In the slowdown scenario, the same structure becomes a transmission channel: one or two visible repricings of datacenter bonds—which the Financial Times has already reported pressure on [S18]—raise funding costs across the SPV complex, and the most leveraged builder retrenches first. it requires only that 2027 guidance comes in at or modestly above 2026 levels ($720–745 billion), with off-balance-sheet vehicles quietly shrinking because spreads widened. [S1]

Notably, investor tolerance is already visibly thin. After Alphabet's July 2026 guidance raise, shares of Amazon, Meta and Microsoft fell amid rising capex scrutiny. A year of that pressure, compounded by a bond-market wobble, is the kind of environment in which boards choose deceleration.

### Why 20% and not more: the steelman against the slowdown

The honest case against this scenario is strong, and it deserves explicit statement.

Second, the supplier-side constraint story is contested by the supplier itself. SemiAnalysis further argues that "half cancelled" framings overstate risk by sampling the most cancellation-prone pipeline slice.

The report's response to this steelman is the asymmetry argument developed in Chapter 7: guidance can move upward in contagion faster than physical supply can respond, which means capex dollars can keep rising even as energization stalls—producing the plateau scenario, not the slowdown. The slowdown requires the causality to reverse, with physical and financing constraints pulling dollars down.

### Observable path markers and resolution

and, on the financing side, a datacenter-linked bond repricing that visibly stalls an SPV issuance.

The power-constrained slowdown is a coherent, evidence-grounded downside—but it demands that three partially independent systems (Texas regulation, PJM cost structure, and credit markets) all break the buildout's way, simultaneously. That conjunction is what holds it at one chance in five.

## Scenario Forecast IV — Overbuild Correction and the Residual Bin (15%)

Treating these together is not analytical laziness. It is an honest accounting of where this forecast is structurally uncertain, and it forces explicit falsification rules so that the residual bin cannot silently absorb every awkward outcome at resolution time.

### The Overbuild Tail: What a Monetization-Driven Capex Bust Would Actually Require

The overbuild correction scenario posits that weak AI monetization triggers capex cuts that push the four-company 2027 total below 2026's $720–745 billion guidance baseline [S1] — that is, an absolute year-over-year decline, not merely slower growth. The research record shows the warning lights are already flashing, even if the fire has not started.

The clearest signal came in July 2026, when Alphabet's capex raise — the very event that catalyzed guidance contagion toward the $1 trillion consensus — was punished rather than rewarded. Shares of Amazon, Meta and Microsoft fell after Alphabet's report, as investors confronted escalating spending against unproven monetization. This is the mechanism that matters: capex escalation and investor scrutiny are rising together, and the report's controversy map identifies "capex escalation vs rising investor scrutiny and AI monetization risk" as the first fault line in the entire forecast.

Three amplifiers make this tail more dangerous than a conventional capex pause would be.

Hundreds of billions of 2026 datacenter-linked issuance sit against a buildout whose total cost is estimated above $3 trillion. [S1] A debt-funded buildout has a failure mode that a cash-flow-funded one does not: the bond market can gate capacity independently of whether the hyperscalers themselves still want to build. The Financial Times has already reported price pressure on bonds issued to fund prominent data centers [S18], and Quinn Emanuel has published a client alert on emerging litigation risks in AI datacenter financing structures [S19]. Debt indigestion and litigation exposure convert a monetization disappointment from an earnings problem into a financing freeze.

**Second, the demand side of the buildout is concentrated in a small number of AI anchors.** Microsoft's AI capacity commitments are tied to OpenAI-anchored demand, and Oracle's Stargate expansion is similarly underwritten by OpenAI's long-term compute commitments. If the anchor tenant's economics fail, two of the largest capacity ramps lose their revenue justification simultaneously — a correlated failure, not an independent one.

a repricing of datacenter paper would hit Meta's buildout first and hardest, given the leverage layered through the Hyperion SPV.

Against these amplifiers, however, the steelman for keeping this tail small is strong, and this report credits it fully. Every forward indicator currently points up, not down: JP Morgan and Goldman Sachs each forecast AI capex of at least $1 trillion for 2027, with Evercore and Bank of America modeling the four-company combined figure above $1 trillion [S2]. Even the physical constraint problem cuts against a 2027 bust: turbine slots sold out toward 2029–2030 and ~3-year equipment lead times mean much of the 2027 spend is already contractually committed, with cancellation costs that make abrupt cuts expensive [S44]. A tech-capex bust of the precedented kind typically requires visible revenue failure *before* the capex peak, not after it. On the current evidence — cloud revenue still growing, AI demand underwritten by multi-year commitments — the overbuild correction remains a tail, not a base case.

### Why the Residual Bin Is Set at 15%: Definitional Ambiguity as a First-Class Uncertainty

The residual bin exists because the very quantity being forecast — "combined four-hyperscaler capex" — does not have a single agreed definition, and the resolution evidence itself is contested. The research record documents this dispute explicitly.

Three distinct sources of classification failure are in play:

- **Data revisions**: company filings are restated;

The mixed-outcome path deserves emphasis because it is genuinely plausible. It belongs here, in the residual.

### Resolution, Falsification, and Reclassification Rules

Because this bin mixes a real tail scenario with classification uncertainty, its resolution rules must be stricter than the named scenarios', or it becomes a garbage collector. This report commits to the following:

Anything short of an absolute decline reclassifies to Scenario III (power-constrained slowdown), because a physical-constraint-driven plateau and a demand-driven bust produce different signatures: the former shows unchanged or rising guidance with delayed energization; the latter shows guidance cuts with intact supply chains.

**Resolution of the residual bin.** An outcome is classified as residual only if, by 31 December 2028, the observable evidence — four 10-K capex figures under a single stated definition, published IEA or LBNL 2027 electricity data, and documented GW slippage — fails to satisfy any named scenario's complete criteria. [S54] This report pre-commits to a primary definition for resolution: **cash capital expenditures including finance-lease principal repayments, as reported in each company's 10-K**, excluding uncommenced commitments, guarantees and JV exposures. [S12] Stating this now forecloses the temptation to pick whichever definition lands the outcome in the most convenient scenario.

Each one moves probability mass either out of this bin or into its overbuild half.

### What the Bin Reveals About the Whole Forecast

Three of the four scenarios are stories about a buildout that continues; the disagreement among them is about magnitude and physical timing. The overbuild correction is the only scenario in which the buildout itself stops, and it is also the only one whose probability cannot be read off any physical indicator — turbines, transformers and queues say nothing about whether AI revenue materializes. That is why its weight is set by financial and behavioral evidence (the post-Alphabet share declines, debt-market stress signals, litigation risk ) rather than by engineering base rates, and why it must remain small while every forward-looking financial indicator — bank models at or above $1 trillion [S2], upward-drifting consensus, committed OpenAI and Oracle demand — points the other way.

The residual mass, by contrast, is not a statement about the world at all.

## Forecast Summary Table and Calibration Notes

This chapter consolidates the report's forecasts into a single master table and then subjects the underlying probabilities to explicit calibration discipline: where each number came from, which base rates constrain it, where credible sources disagree with it, and which dated observations will confirm or falsify it. The purpose is not summary for its own sake. Every probability below is stated with its evidence anchor, its deviation from the reference class, and the named observation that would force it to move.

### The Master Table: Scenarios, Bands, and Resolution Criteria

| Scenario | Probability | 2027 capex (four hyperscalers, filed basis) | Global datacenter electricity growth (YoY) | US capacity slipping from 2027 into 2028 | Resolution criteria (by 31 Dec 2028) |
|---|---|---|---|---|---|
| I. Measured growth plateau | — | — | — | — | — |
| II. Continued buildout surge | — | >$950B | — | Typically <8 GW | The ~$1.65T Nikkei figure is inadmissible—five companies, combining leases, commitments, guarantees and JV exposures. Default definition: cash capex plus commenced finance leases |
| III. Power-constrained slowdown | — | — | — | — | Filed capex below consensus; |
| IV. Overbuild correction / residual | — | — | any | any | — |

The derived headline quantities follow from this table rather than being asserted independently. The consistency check matters: a forecast whose headline quantities could not be reconstructed from its scenario weights would be narratively coherent but probabilistically incoherent, and this one can be reconstructed.

### Calibration: How Each Probability Derives from Evidence and Base Rates

one who thinks it too high must explain why this cycle breaks a base rate that held through the cloud, mobile and crypto buildouts.

And PJM itself trimmed its summer-2027 peak forecast by roughly 4 GW in January 2026 on stricter datacenter vetting [S36]—the grid operator closest to the load pocket, in effect, pre-announcing roughly one threshold's worth of slippage on its own. SemiAnalysis contends that "half cancelled" framings overstate risk by sampling the most cancellation-prone pipeline slice. Selection bias cannot explain an administrative pause. Each is plausible;

The contagion mechanism is observable: after Alphabet's July 2026 raise, Evercore ISI's Mark Mahaney judged both Amazon and Microsoft likely to follow. [S3]

### Why Overall Confidence Is Rated Low

The low rating is structural, and it rests on three identifiable gaps rather than on general caution. First, **no formal 2027 guidance existed as of 20 October 2026**: every 2027 capex figure in circulation, including the consensus this forecast anchors to, is an analyst construct that will be reset on the Q3 2026 earnings calls in late October and November 2026. [S44] The report is forecasting a quantity its subjects have not yet spoken. Second, **the target quantity lacks an agreed definition**. Microsoft's accounting-adjusted basis counts finance leases at commencement, shifting spending across periods. The pre-committed resolution definition—cash capital expenditures including finance-lease principal repayments as reported in each company's 10-K, excluding uncommenced commitments, guarantees and JV exposures—is the report's guard against definition-shopping at resolution time, stated now precisely so it cannot be chosen conveniently later. [S12]

### Explicit Divergences from Credible Sources

Calibration honesty requires naming where this forecast disagrees with authorities it otherwise relies on—and why the disagreement survives.

**Sell-side banks sit above the central range.** JP Morgan and Goldman Sachs each forecast big-tech AI capex of $1 trillion or more for 2027, with Evercore ISI and Bank of America modeling the four-company combined total above $1 trillion after the Q1 2026 calls [S2]. Our point band of $850B–$1.05T contains these numbers but does not center on them. the implication disagreement is large.

That is what a well-placed threshold looks like: crossed in nearly every version of the disagreement.

the difference is attributable to the weight this report places on the debt-market channel—datacenter bonds already repricing, litigation risk in SPV structures flagged by Quinn Emanuel, and a buildout consuming debt markets against a >$3 trillion program. That is a judgment call, and it is flagged as one.

**GE Vernova disputes that turbines gate the buildout.** Its CEO, Scott Strazik, argues the turbine is often not a project's binding constraint, against trade-press reading of slot reservations sold out toward 2029–2030 with roughly three-year lead times on new heavy-duty orders [S44]. The forecast is agnostic on the dispute's premise and firm on its conclusion.

### The Verification Calendar

The dashboard, in descending order of information value, with the probability mass each observation moves:

1. Because GE Vernova supplies generation equipment to hyperscalers directly and to PJM's queue, its order book simultaneously conditions the Virginia load pocket, ERCOT's options, and Dominion's conversion rate. an order-book decline would be the earliest hard signal of the overbuild tail.
2. Amazon and Microsoft following Alphabet's raise, as Evercore expected [S17], shifts the capex band up and compresses the residual bin; absence weakens the contagion mechanism underlying both the plateau and surge scenarios.
4. An extension is the single largest identifiable trigger for migration from the plateau into the slowdown; a grandfathering resolution removes the largest discrete overhang from the slippage arithmetic.
5. **PJM's January 2027 peak-forecast vintage:** whether the ~4 GW trim deepens or reverses [S36]—the first clean read of how much load the new vetting regime strands.

A closing word on what calibration means here. The scenario weights, bands, and probabilities above are this report's own estimates, anchored to the research record but not dictated by it. The banks say ≥$1 trillion; the report centers below them, and identifies the conversion friction responsible. Every deviation from a reference class is identified in advance, sized, and reversible on a dated calendar.

## The Capex Engine: Hyperscaler Guidance Dynamics, Financing Structures, and the Debt-Market Gate

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/ai-capex-2027/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

The four hyperscalers are the engine of this forecast, but the engine's fuel mix has changed. This chapter examines each company's guidance dynamics, the shift in financing structure, the external actors underwriting demand, and the persistent lag of consensus, before closing on the central asymmetry of the forecast: guidance can move upward in contagion within weeks, while physical supply cannot respond for years.

### Four Companies, Four Guidance Postures

**Microsoft** is the definitional wild card. Calendar-2026 guidance is roughly $175 billion on an accounting-adjusted basis that counts finance leases when they commence—a treatment that shifts spending across periods and makes reported capex noisier than peers' [S3]. Critically, Microsoft's ramp is contractually tied to OpenAI-anchored compute commitments: the company's capacity obligations run through its OpenAI partnership, and its reported ~835 MW Three Mile Island nuclear arrangement with Constellation shows it procuring power decades forward to serve that demand. [S51] Microsoft's capex is thus less a discretionary budget line than the fulfillment of pre-sold capacity contracts.

**Alphabet** is the contagion-setter.

**Meta** is the leverage outlier. Of the four, Meta has the least diversified cash-flow cover for a capital program whose intensity now resembles a utility's more than a social platform's—and it is therefore the company most exposed to any debt-market repricing.

### The Shift from Cash Flow to Debt, and the New Gate

The $3 trillion AI datacenter buildout has become, in the words of one energy-trade analysis, "all-consuming for debt markets" [S21]. Oracle—outside the four-company metric but inside the same debt pool—issued $18 billion in October 2026 to fund Stargate data centers, and Quinn Emanuel's client alert on emerging litigation risks in AI data centers explicitly covers financing structures of the kind Meta uses [S19].

Second, it creates a new fragility. Bond prices for prominent datacenter issuers have already come under pressure; a sustained repricing would hit the SPV-funded margin of the buildout first, which in the four-company cluster means Meta.

### Who Underwrites the Demand: OpenAI, NVIDIA, Oracle

The hyperscalers are not spending blind. Three external actors convert speculative AI demand into contracted revenue that justifies the capex. OpenAI anchors the demand side: its compute commitments—most visibly the Stargate partnership with Oracle—underwrite external demand for the buildout, giving Microsoft and Oracle long-dated revenue contracts against which capacity can be financed. NVIDIA sits at the end of the chain as the supply-side shaper: GPU availability governs how quickly capex converts into computing capacity, and its delivery schedule effectively sets the pace at which hyperscaler spending can land as usable capacity rather than sit as inventory. The tail risk is correlated, not idiosyncratic, which is precisely what distinguishes a capex bust from a normal spending pause.

### Why Consensus Keeps Lagging—and What That Implies for 2027

The single most robust empirical pattern in this domain is that analyst consensus has persistently undershot outcomes.

This is not random error; it has a mechanism. Guidance moves in contagion: when Alphabet raises, competitive logic—and Evercore's explicit expectation of follow-through —makes matching raises by Amazon and Microsoft more likely, and each raise resets the consensus baseline for the others. Because each company prefers to guide low and beat, the cluster ratchets upward in discrete steps timed to earnings calls rather than continuously.

JP Morgan and Goldman Sachs each forecast big-tech AI capex of at least $1 trillion for 2027, with Evercore and Bank of America modeling the four-company combined total above $1 trillion after the Q1 2026 calls [S2].

A steelman of the bearish counter deserves explicit treatment. Against the contagion thesis, one could argue that July 2026 marked the turn: CNBC reported that Alphabet's report was panned and that shares of Amazon, Meta and Microsoft all fell amid rising capex scrutiny—the first synchronized investor pushback of the cycle. This report assigns that path real weight: the overbuild-correction tail and the below-consensus band of the power-constrained slowdown together carry roughly a third of the probability mass. But the underwriting structure described above is why it is not the modal path.

### The Core Asymmetry: Dollars Outpace Megawatts

The chapter's central claim, and the hinge of the whole forecast, is an asymmetry in adjustment speed. Financial guidance operates on an earnings-call clock: Alphabet's July 2026 raise altered the expected 2027 total within days. [S1] Physical supply operates on an equipment clock: GE Vernova's CEO Scott Strazik puts directional lead times on new heavy-duty turbine orders at roughly three years—an order placed in 2026 delivers after 2027—while arguing the turbine is often not a project's binding constraint. [S44] Every incremental guidance dollar therefore widens the gap between committed capex and energizable capacity, because dollars can be raised and spent on land, shells and GPUs long before the megawatts exist to run them at full load.

Even in the continued-buildout-surge scenario, the binding constraints documented in Chapters 8 and 9—turbines, transformers, queues—dampen how much committed spend converts into consumed electricity within the calendar year.

Capex measures intent; electricity measures energization; The late-October and November 2026 earnings calls will supply the first hard observations of whether the contagion mechanism carries into formal 2027 guidance. [S3] By the logic above, the surprise risk on the capex number is skewed upward, while the surprise risk on electricity growth remains capped by physics—and the gap between the two is precisely where this forecast lives.

## The Physical Ceiling: Turbines, Transformers, and the Equipment Supply Chokepoints

The previous chapter argued that hyperscaler guidance moves upward in contagion faster than physical supply can respond. This chapter maps the physical side of that gap in detail: the turbines, transformers, and grid equipment that stand between a committed dollar and an energized megawatt. The core claim is that the equipment supply chain functions as a ceiling, not a throttle—it does not slow demand growth smoothly;

### GE Vernova as Gatekeeper: The 116 GW Book and the Closed 2027 Slots

No single company sits closer to the capex-to-capacity conversion point than GE Vernova. Trade reporting on the same results cycle describes record power-equipment orders driven by data centers, with turbine slots tightening through 2030 [S44].

CEO Scott Strazik has put directional lead times on new heavy-duty turbine orders at roughly three years—meaning an order placed in 2026 delivers after 2027. [S47] Combined with slots reported sold out toward 2029–2030 [S44], the implication is stark: the 2027 energization envelope was substantially determined by orders placed in 2023–2024.

The company's electrification segment tells a parallel story. Because GE Vernova supplies gas turbines and grid equipment to hyperscalers including Meta and Amazon, and to utilities like Dominion serving the Virginia load pocket, this order book functions as a leading indicator of energization two to three years forward. When the backlog converts, capacity arrives; when it is sold out, no amount of hyperscaler capex pulls delivery forward.

### Transformers: The Contested Numbers, the Uncontested Direction

On transformers, the research record contains a genuine numerical dispute that must be presented as such. The discrepancy is partly equipment class and partly survey vintage: trade-press reporting on recent utility procurement captures the leading edge of the deterioration, while vendor pages reflect broader averages across product lines.

Which number is right matters less than what both agree on: lead times are above two and a half years, lengthening, and now comparable to or exceeding heavy-duty turbine lead times. The equipment queue and the interconnection queue have converged on similarly punishing durations, and they compound rather than substitute for each other.

The second-order effect is financial. Utilities buying five years ahead and demanding customer pre-payment transfers supply-chain risk onto hyperscalers and datacenter developers.

### Scarcity Economics: $600/kW and the Price of Certainty

Whatever the exact landing point, the direction is unambiguous: the marginal cost of on-site or dedicated generation capacity is rising sharply precisely when hyperscalers need it most.

Scarcity pricing changes behavior in observable ways. GE Vernova markets aeroderivative and containerized fast-start units advertised as powering a datacenter site in roughly two weeks, and its partnership with Chevron targets 4 GW of fast-deploy capacity by 2027. [S7] Meta's reported nuclear procurement pipeline targets the mid-2030s.

### The Dispute: Are Turbines Actually "Gating"?

GE Vernova's own position, argued publicly through CEO commentary, is that natural gas turbines are not "gating" datacenter buildouts—the turbine is often not a project's binding constraint [S56]. Trade press reads the same data oppositely: 2027 delivery slots are effectively closed, reservations sold out through 2029–2030, and three-year lead times on new orders constitute a hard gate [S44]. This disagreement deserves a fair hearing rather than dismissal, because both sides are partly right.

The steelman of GE Vernova's position runs as follows. A datacenter project's critical path runs through land, permits, financing, generation, grid equipment, and interconnection approval in parallel. The vendor also has a credibility interest in not appearing to choke its own customers' growth.

The counter-reading is equally grounded. Internal scenario deliberation across supplier, grid-operator, and buyer perspectives surfaced the same fault line: the grid-operator view tends to hold that interconnection delay is procedurally compressible while equipment lead times are not, whereas project developers closest to financing tend to hold the reverse—that equipment can be pre-bought with money, but queue time cannot. This divergence is structural, not evidentiary: each actor sees the constraint it cannot control as the binding one.

The resolution this report adopts is that the dispute is a framing error at the aggregate level. For any single project, the binding constraint varies—turbine for one, transformer for another, GIA signing for a third. That is why SemiAnalysis's selection-bias critique of slippage framing —while correct that aggregate on-time rates overstate cancellation risk in the most speculative pipeline slice—does not overturn the direction of the conclusion; it narrows the plausible slippage band without moving it below the 5 GW threshold assessed in Chapter 9.

### Why the Ceiling Is Load-Bearing for the Forecast

The physical ceiling has three direct implications for this report's headline numbers.

The highest-information single observation in the forecast window follows directly: GE Vernova's Q4 2026 results. [S8]

## The Grid Friction Map: PJM, ERCOT, FERC, and the >5 GW Slippage Probability

and the two largest interconnection jurisdictions—PJM and ERCOT—have both moved to slow, vet, or pause new large-load connections precisely when the pipeline peaks. This chapter maps the friction layer by layer, then confronts the strongest counterargument before concluding that even the most skeptical reading leaves the >5 GW threshold more likely than not.

### The Arithmetic Core: 36.3 GW Scheduled Against a 40–50% Slippage Base Rate

The threshold this forecast must clear is 5 GW—under a third of even the most conservative slippage estimate.

Two complementary base rates reinforce the point. Legal-practice reporting corroborates the delay frame from the developer side: Orrick's November 2025 guide puts US datacenter power-interconnection delays at five-plus years, against datacenter demand growing 23% annually [S33]. The generation-side completion history matters because datacenter load cannot energize ahead of the power behind it—every queued megawatt of supply is a potential bottleneck megawatt of load.

### PJM: Tighter Vetting, a Queue Under Reform, and a June 2027 Rule Change

PJM governs the jurisdiction containing the Virginia load pocket, the largest concentration of datacenter demand in the country, where Virginia commercial retail electricity sales were already running at +9.788% year-over-year in December 2025 [S11].

That single adjustment sits adjacent to the 5 GW threshold by itself: it represents load PJM itself no longer expects to materialize on schedule. it is one of its two clearing mechanisms.

The mechanism deserves emphasis because it converts queue friction from a cost into a hard gating decision.

At the same time, PJM is genuinely accelerating some traffic. The expedited track is real relief for a handful of projects, not a release valve for the aggregate pipeline. It is also worth noting the tension inside PJM's own position: the same institution is trimming its load forecast by 4 GW while advertising a ten-project fast lane—the combination of a system acknowledging oversubscription and rationing its exceptions.

### ERCOT and FERC: A 49.8 GW Overhang and a November Deadline

Texas contributes the single largest discrete risk to the slippage forecast. The Texas governor's order of 3 August 2026 paused new ERCOT datacenter connections; [S40] BNEF expects the pause to last "months";

Equipment constraints compound the Texas problem from a different direction—GE Vernova's heavy-duty turbine orders carry roughly three-year lead times per its CEO, so a Texas project that loses its slot in 2026 cannot simply reorder equipment for 2027 delivery. [S44]

Above both RTOs sits FERC.

### The Steelman: Why SemiAnalysis Thinks the Slippage Framing Is Overblown

The strongest counterargument comes from SemiAnalysis, which argues that "half cancelled" framings overstate risk by sampling the most cancellation-prone slice of the pipeline—early-stage, pre-financing, speculative projects that were never going to be built in the reference year anyway. On this reading, aggregate on-time rates computed across the full pipeline understate the delivery reliability of the projects that matter: those with hyperscaler balance sheets, executed power agreements, and equipment reservations already secured.

But three considerations limit how far the skeptical reading can be pushed.

First, the objection cuts mainly against *cancellation* framing, not *delay* framing. Delay does not require speculative projects; it requires only median equipment and queue friction—friction measured in years, not months, across every authoritative source.

They are jurisdiction-wide. PJM's 4 GW forecast trim applies to all Virginia-pending load regardless of sponsor quality; the ERCOT pause applies indiscriminately across Texas under a governor's order; Selection bias cannot explain away an administrative pause.

Third, even the SemiAnalysis-style concession implies *some* slippage. The >5 GW call is deliberately constructed to be robust to the disagreement: it is crossed in nearly every version of the skeptics' world, which is precisely what a well-placed forecast threshold should be.

### Why ~75% and Not Higher: The Paths to Under 5 GW

For slippage to stay under 5 GW, several things must go right together: the ERCOT pause resolves within BNEF's "months" expectation and in-process Texas projects are grandfathered through; and equipment lead times ease from their Q1 2026 peaks. [S47] Each element is individually plausible.

The watchpoints that would force a revision downward are concrete and dated. An ERCOT resolution that grandfatheres substantially all in-process Texas load would remove the largest single overhang. Dominion earnings calls through 2027 will show whether contracted-pipeline growth continues at 5 GW or more per half-year; [S55]

Absent those signals, the grid friction map points one way. The deeper structural point is that this slippage is not a malfunction of the buildout; it is the physical frontier asserting itself.

## Key Official Indicators: What EIA and IEA Series Signal for the 2027 Electricity Question

Official statistics are usually the last place a boom shows up and the last place it gets revised away. The answer, developed across four sub-sections below, is that every official proxy currently points below that threshold. The chapter closes with the specific tripwires that would force this judgment to be revised.

### The US Commercial Series: Real Acceleration, But a Factor of Five Short of the Threshold

The most direct domestic proxy for datacenter load is the EIA's retail sales of electricity to the US commercial sector, because large datacenters are classified as commercial customers. Critically, the EIA's Short-Term Energy Outlook publishes no standalone datacenter series; US commercial-sector retail electricity sales—“which includes data centers” and also captures weather effects—serve as the stated proxy. That dilution matters for how the series should be read: it is an encompassing measure, not a datacenter-only measure, which cuts both ways in inference, as discussed below.

The stored history runs 240 months through July 2026, and its latest reading is a record: 150,578.728 million kWh in July 2026, versus 144,363.1467 million kWh in July 2025, a gain of roughly 6.22 billion kWh or +4.306% year over year [S15]. The acceleration is real—July 2025's year-over-year change was +3.448%, so the series gained +0.857 percentage points in twelve months. The five-year range of the YoY series runs from -2.122% (December 2023) to +8.715% (January 2022) [S10], which places the current reading around the 85th percentile of its own recent history.

The EIA's own forward view currently agrees with the below-threshold reading. Reuters frames the same STEO as forecasting record US electricity consumption in both 2026 and 2027 as AI use surges [S25]. Note the tension worth flagging honestly: a headline of “record” generation is arithmetically compatible with modest percentage growth, because the base is enormous. Watching those revisions is cheaper than waiting for annual data.

### Virginia: The Load Pocket Where the Threshold Question Will Be Decided

If the aggregate US series is too diluted an instrument for detecting datacenter-driven step changes, the Virginia commercial series is the sharpest one available. Northern Virginia is the largest datacenter load pocket in the country, and its commercial retail sales grew +9.788% YoY in December 2025, accelerating sharply from +4.477% a year earlier—a +5.311 percentage-point jump in a single year. That acceleration, more than any national figure, is the cleanest official-statistics signature of the AI buildout anywhere in the stored data, and it is monitored monthly as a key leading indicator.

Virginia's history also shows what a genuine step change looks like when a jurisdiction's commercial base becomes datacenter-dominated. The five-year range of its YoY series includes a 27.222% spike in March 2023 [S11]—an episode that dwarfs anything in the national series.

The critical point is one of aggregation, not rhetoric. Global datacenter consumption is a sum of many jurisdictions and facility vintages.

### The IEA Central Path: ~14% per Year, With the Bottleneck Caveat Written In

Two features of the IEA framework matter directly for the threshold question. That is the arithmetic of a fast-growing subsegment compounding off a small share of the total—which is precisely why the AI slice can keep growing at multiples while the global figure the threshold refers to grows in the mid-teens. Conflating the two is the most common error in bullish readings of the official data.

A steelman of the bullish case deserves an honest hearing, because the official series have been behind this cycle before. If official and sell-side forecasters lagged capex by a factor of two, why trust their electricity numbers? The answer is that electricity, unlike guidance, is gated by physical delivery. Capex can be announced in an afternoon; Capex converts to consumption only through energized megawatts, and the official electricity series measure the energized stock, not the announced flow.

One disputed reading must be flagged and set aside. Treating it as total-consumption growth would be a definitional error masquerading as a forecast.

### Thresholds, Revisions, and the Verification Calendar

- the burden of proof lies on the surge, not on the plateau.

Nothing in the stored vintages as of 20 October 2026 suggests they are about to: the data show strain—record sales, accelerating pockets, sharply higher PJM prices—but strain clearing through price and delay, not a volume explosion. [S44]

## Risks, Wildcards, and Cascade Mechanisms

The through-line is GE Vernova: its equipment backlog sits upstream of the Virginia load pocket, the ERCOT pipeline, and Dominion's contracted pipeline simultaneously, which is why we treat its Q4 2026 results as the single highest-information observation of the entire forecast window.

### Risk 1: The monetization cascade into synchronized capex cuts

The overbuild tail begins with an AI revenue miss, not a power problem. The mechanism runs: weak AI monetization → investor scrutiny of capex intensity → simultaneous guidance discipline across all four hyperscalers → 2027 capex landing below 2026 levels. [S1] The precondition for synchronization is already visible. After Alphabet's July 2026 capex raise, shares of Amazon, Meta and Microsoft fell amid what CNBC characterized as rising capex scrutiny —a market explicitly pricing the possibility that aggressive spending outruns revenue. [S3] Guidance moves in contagion on the way up; nothing in the structure prevents contagion on the way down.

A monetization disappointment at the anchor propagates to at least two large builders at once. they are refinancing decisions, and refinancing decisions are pro-cyclical. Third, US tech companies' datacenter lease commitments passed $850 billion by mid-2026, led by Meta and Microsoft—fixed obligations that convert a revenue miss directly into balance-sheet stress rather than a mere earnings miss. [S20]

That correlation is the point: a debt repricing makes a monetization miss more costly, and a monetization miss makes debt repricing more likely.

### Risk 2: Debt-market repricing and Meta as the most exposed node

Datacenter-linked bonds are already showing strain. The Financial Times has reported on falling prices of bonds issued to fund prominent data centres, including Meta's debt financing [S18], and Quinn Emanuel has flagged emerging litigation risk in AI datacenter financing structures, specifically covering vehicles of the kind Meta uses [S19]. Against a buildout that one analysis sizes at more than $3 trillion and that has become, in that outlet's framing, "all-consuming" for debt markets [S21], the marginal buyer of the next tranche matters as much as the marginal GPU.

Meta is structurally the most exposed of the four. If datacenter bond spreads widen materially in late 2026 or 2027, the transmission is asymmetric across the four companies: Amazon and Alphabet fund largely from operating cash flow; [S3] Microsoft from cash flow plus a pristine credit; Meta partially from a levered special-purpose vehicle.

### Risk 3: Reliability events in PJM and retroactive curtailment

The Virginia load pocket is the forecast's densest concentration of correlated risk. Virginia commercial electricity sales grew 9.788% year-over-year in December 2025, up from 4.477% a year earlier, against a five-year monthly range that includes a 27.222% spike—evidence of how violently this one series can move when campuses energize in clusters.

The institutional response is already legislated and dated. PJM has already cut its summer-2027 peak forecast by roughly 4 GW on stricter datacenter vetting [S36].

### Risk 4: An ERCOT resolution that strands the Texas pipeline

BNEF expects the pause to last "months";

The critical asymmetry: a favorable resolution returns Texas capacity to the queue but cannot return lost time.

### Risk 5: The upside wildcard—NVIDIA supply and interconnection fast-tracks

The upside deserves equal rigor because the report's central range ($850B–$1.05T) has a fat right shoulder toward $1.15T. First, GPU supply: capex converts to electricity demand only through installed compute, and if NVIDIA's shipments surge beyond plan, the binding constraint shifts from chips to power—neutral for capex but positive for electricity growth, since already-energized shells fill faster. GE Vernova's Chevron partnership to deliver 4 GW of fast-deploy containerized gas capacity by 2027—units the vendor advertises as powering a site in "2 weeks" —shows a parallel fast path bypassing grid queues entirely. [S7]

Fast tracks lift the tails of the distribution without moving its center above the threshold.

### The cascade architecture: why GE Vernova's Q4 2026 print carries so much information

Nearly every path above runs through the same node. Its equipment supplies Amazon, Microsoft and Meta directly, feeds PJM's queue, and simultaneously constrains the Virginia load pocket, ERCOT's options, and Dominion's pipeline conversion. This is the structural core of the report's central asymmetry: guidance can move in contagion within weeks; turbines cannot.

That is why GE Vernova's Q4 2026 results are the forecast's highest-information single observation. [S8] And if its order book turns down outright, that is the earliest hard signal of the monetization cascade—suppliers see capex cuts before income statements do. One earnings release thus discriminates between three of the four scenarios, a property no hyperscaler guidance date can match, since each company's capex number is contaminated by SPV structures, lease accounting, and the definitional disputes documented earlier in this report.

The final synthesis: the forecast's risks are not five independent coins but one network with five failure and two acceleration modes, all sharing GE Vernova, PJM, and the debt channel as common nodes. The monitoring dashboard in the closing chapter follows directly from this architecture.

## Decision Implications: Guidance for Investors, Utilities, Suppliers, and Policymakers

They imply opposite bet structures depending on where an actor sits in the capex-to-capacity conversion chain.

### Investors: A Two-Sided Capex Bet Attached to a One-Sided Electricity Bet

The central structural insight for investors is that the two headline quantities have opposite surprise geometries. Capex is genuinely two-sided. So a beat above consensus is entirely plausible; Positioning for a single direction in hyperscaler equities is a poor expression of this forecast. The asymmetry lives elsewhere.

The genuinely asymmetric bet is the electricity threshold. US commercial retail sales were running at +4.306% YoY in July 2026 [S10]. The IEA explicitly warns that value-chain bottlenecks reduce the likelihood of aggressive near-term scenarios. Strategies that pay off only on a demand blowout are betting a low-probability tail;

Timing matters more than direction. Two watch items stand out. First, whether Amazon and Microsoft follow Alphabet's raise, as Evercore expected. Investors relying on reported cash capex alone will systematically mismeasure Meta's exposure. portfolio arithmetic built on it will mis-allocate.

The answer is that the binding variable has changed. Earlier, the constraint was willingness to spend;

### Utilities: Dominion's Pipeline Is a Conversion Problem, Not a Demand Problem

For Dominion and its peers, the forecast reframes what to worry about. The growth case does not depend on datacenter demand materializing — it manifestly exists. the same five-year-plus queue medians; and equipment lead times that have utilities buying transformers five years ahead and seeking customer pre-payment.

The second-order risk is defection. Every gigawatt that self-supplies is a gigawatt of rate base that never materializes, so the same grid friction that justifies utility capex programs also erodes their captive-load foundation.

### Suppliers: Scarcity Pricing Persists Under Almost Every Scenario

only the Other/Status Quo branch genuinely threatens the order book, and multi-year contracted backlog cushions the first years of any downturn.

The honest counterpoint: GE Vernova itself argues turbines are not "gating" buildouts, noting the turbine is often not a project's binding constraint [S56]. Investors should not dismiss this as vendor spin — it correctly identifies that the binding constraint varies by project, and fast-deploy aeroderivative options relax timing for some sites. But for 2027 heavy-duty delivery the aggregate arithmetic is decisive: with roughly three-year lead times, an order placed in 2026 delivers after 2027. [S47]

### Policymakers: Two Dates Decide Whether Slippage Stays Orderly

Two dates carry most of the weight.

Policymakers face a genuine trade-off rather than a free lunch. PJM's stricter vetting reflects legitimate reliability management [S36], and IRAS bring-your-own-capacity rules correctly price the externality large loads impose on the queue. SemiAnalysis's objection — that "half cancelled" framings overstate risk by sampling the most cancellation-prone pipeline slice — deserves steelmanning because it implies orderliness is achievable: if the marginal, speculative projects are the ones that slip, then >5 GW of slippage coexists with a healthy core buildout, which is precisely our modal scenario. The policy objective should therefore be *sorting* the pipeline efficiently — through co-location rules, firm-commitment requirements, and the expedited track — rather than maximizing gross throughput. whether constituent bills follow the PJM path or the national average will determine the durability of any protocol regime.

### The Monitoring Dashboard

Each stakeholder's thesis resolves against dated, observable checkpoints:

1. **Q3 2026 earnings calls (late Oct–Nov 2026):** first formal 2027 capex signals from all four companies. [S3] Four guides summing above $950B shifts weight toward the surge;
4. This is the highest-information single observation in the window because turbine supply simultaneously conditions the Virginia load pocket, ERCOT options, and Dominion's conversion rate.
6. below ~2 GW per half-year signals conversion failure.

The final calibration note ties the dashboard to the forecast's low overall confidence: none of the four hyperscalers had issued formal 2027 guidance as of 20 October 2026, and the definitional disputes — cash capex versus finance-lease-inclusive measures, the five-company Nikkei figure conflating leases and guarantees — mean even resolved outcomes will admit some reinterpretation. [S42] Decision-makers should hold positions and policies conditionally, keyed to the dates above, rather than committing now to any single scenario.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/ai-capex-2027/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[45%] Measured growth plateau (power-constrained consensus path)**: By 2028-12-31: (a) sum of Amazon+Microsoft+Alphabet+Meta reported 2027 capex (company 10-Ks/filings) is $850B–$950B; (b) IEA/LBNL published 2027 global datacenter electricity estimate shows 2027 vs 2026 growth <20%; (c) >5 GW of US datacenter capacity publicly confirmed delayed into 2028 (utility/regulatory filings or credible tracker).
- **[20%] Continued buildout surge**: By 2028-12-31: (a) four-hyperscaler 2027 capex >$950B per company filings; (b) published 2027 global datacenter electricity (IEA or LBNL) shows ≥20% YoY growth; (c) US commercial retail sales YoY (usgov:eia/electricity_sales/US.COM#yoy) sustained above ~8% in H2-2027 months.
- **[20%] Power-constrained slowdown**: By 2028-12-31: (a) four-hyperscaler 2027 capex $720B–$850B (below consensus) per filings; (b) published 2027 global datacenter electricity growth <15%; (c) ≥15 GW of planned 2027 US datacenter capacity documented as delayed into 2028+ in regulatory/utility filings or credible industry trackers.
- **[15%] Other / Status Quo**: At 2027 calendar year, resolved by 2028-12-31, classify this residual bin if none of the named scenarios' complete resolution criteria are met, or if the outcome remains a mixed/status-quo path.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Gross domestic product (GDP), Constant prices, Percent change: United States (wb:IMF_WEO_NGDP_RPCH/USA) | next annual release after 2025 | — |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/US.COM#yoy) | next monthly release after 2026-07 | — |
| EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/VA.COM#yoy) | next monthly release after 2025-12 | — |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector (usgov:eia/electricity_sales/US.COM) | next monthly release after 2026-07 | — |
| Real Personal Consumption Expenditures — United States (fred:DPCERL1Q225SBEA) | next quarterly release after 2026-Q2 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/VA.COM#yoy) | 9.788% (2025-12) | >= 12% / 2026-12 | 43% (n=228, h=12) vs model 30% | [Source](<https://www.eia.gov/electricity/data/browser/>) [S11] |
| EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) (usgov:eia/electricity_sales/US.COM#yoy) | 4.306% (2026-07) | >= 5% / 2026-12 | 41% (n=235, h=5) vs model 45% | [Source](<https://www.eia.gov/electricity/data/browser/>) [S10] |

## References

1. [S16] Real Personal Consumption Expenditures — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DPCERL1Q225SBEA](https://fred.stlouisfed.org/series/DPCERL1Q225SBEA)
2. [S15] EIA: Retail Sales of Electricity: U.S. total, commercial sector — eia.gov — [https://www.eia.gov/electricity/data/browser/](https://www.eia.gov/electricity/data/browser/)
3. [S4] Gross domestic product (GDP), Constant prices, Percent change: United States — data360.worldbank.org — [https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH](https://data360.worldbank.org/en/indicator/IMF_WEO_NGDP_RPCH)
4. [S11] EIA: Retail Sales of Electricity: Virginia, commercial sector (year-over-year % change) — eia.gov — [https://www.eia.gov/electricity/data/browser/](https://www.eia.gov/electricity/data/browser/)
5. [S10] EIA: Retail Sales of Electricity: U.S. total, commercial sector (year-over-year % change) — eia.gov — [https://www.eia.gov/electricity/data/browser/](https://www.eia.gov/electricity/data/browser/)
6. [S1] Big Tech’s 2026 Capex Range Reaches $720 Billion to $745 Billion | MLQ News — mlq.ai — [https://mlq.ai/news/big-techs-2026-capex-range-reaches-720-billion-to-745-billion/](https://mlq.ai/news/big-techs-2026-capex-range-reaches-720-billion-to-745-billion/)
7. [S3] Amazon, Microsoft, Alphabet, Meta Plan $725B AI Capex in 2026 — aiweekly.co — [https://aiweekly.co/alerts/amazon-microsoft-alphabet-meta-plan-725b-ai-capex-in-2026](https://aiweekly.co/alerts/amazon-microsoft-alphabet-meta-plan-725b-ai-capex-in-2026)
8. [S12] How much Google, Meta, Amazon and Microsoft are spending on AI — cnbc.com — [https://www.cnbc.com/2025/10/31/tech-ai-google-meta-amazon-microsoft-spend.html](https://www.cnbc.com/2025/10/31/tech-ai-google-meta-amazon-microsoft-spend.html)
9. [S2] AI Capex to Hit $1 Trillion – And Estimates Are Still Too Low - I/O Fund — io-fund.com — [https://io-fund.com/ai-stocks/ai-capex-1-trillion-estimates-too-low](https://io-fund.com/ai-stocks/ai-capex-1-trillion-estimates-too-low)
10. [S20] Data Center Leases Hit $850B: Meta, Microsoft Lead [2026] — tech-insider.org — [https://tech-insider.org/data-center-leases-850-billion-2026/](https://tech-insider.org/data-center-leases-850-billion-2026/)
11. [S47] 2026 Transformer Lead Times: Pad-Mount & Main Power... — gamechangeenergy.com — [https://www.gamechangeenergy.com/news/transformer-lead-times-in-2026-what-pad-mounted-and-substation-buyers-can-expect](https://www.gamechangeenergy.com/news/transformer-lead-times-in-2026-what-pad-mounted-and-substation-buyers-can-expect)
12. [S44] Data centers drive record surge in GE Vernova power equipment orders as turbine slots tighten through 2030 — power-eng.com — [https://www.power-eng.com/gas/turbines/data-centers-drive-record-surge-in-ge-vernova-power-equipment-orders-as-turbine-slots-tighten-through-2030/](https://www.power-eng.com/gas/turbines/data-centers-drive-record-surge-in-ge-vernova-power-equipment-orders-as-turbine-slots-tighten-through-2030/)
13. [S40] Texas Audit Could Delay 49.8 GW of Data Center Load, Cost Projects Up to $15 Billion, BNEF Warns — powermag.com — [https://www.powermag.com/texas-audit-could-delay-49-8-gw-of-data-center-load-cost-projects-up-to-15-billion-bnef-warns/](https://www.powermag.com/texas-audit-could-delay-49-8-gw-of-data-center-load-cost-projects-up-to-15-billion-bnef-warns/)
14. [S36] PJM trims near-term load forecast on stricter data center vetting, economic outlook — utilitydive.com — [https://www.utilitydive.com/news/pjm-interconnection-load-forecast-data-centers/809717/](https://www.utilitydive.com/news/pjm-interconnection-load-forecast-data-centers/809717/)
15. [S18] From the Financial Times: "Prices of bonds issued to fund... — facebook.com — [https://www.facebook.com/elerianm/posts/from-the-financial-timesprices-of-bonds-issued-to-fund-prominent-data-centres-wh/1692271715594281/](https://www.facebook.com/elerianm/posts/from-the-financial-timesprices-of-bonds-issued-to-fund-prominent-data-centres-wh/1692271715594281/)
16. [S19] Emerging Litigation Risks in AI Data Centers — quinnemanuel.com — [https://www.quinnemanuel.com/media/4dzkfccz/client-alert-ai-data-center-financing-and-litigation-risks.pdf](https://www.quinnemanuel.com/media/4dzkfccz/client-alert-ai-data-center-financing-and-litigation-risks.pdf)
17. [S54] Dominion in contract talks for 47 gigawatts of new data centers, up 17% this year | Reuters — reuters.com — [https://www.reuters.com/business/energy/dominion-energy-beats-estimates-strong-power-demand-virginia-south-carolina-2025-10-31/](https://www.reuters.com/business/energy/dominion-energy-beats-estimates-strong-power-demand-virginia-south-carolina-2025-10-31/)
18. [S17] Hyperscalers face higher capex scrutiny after Alphabet... — cnbc.com — [https://www.cnbc.com/2026/07/28/hyperscalers-face-higher-capex-scrutiny-after-alphabet-report-panned.html](https://www.cnbc.com/2026/07/28/hyperscalers-face-higher-capex-scrutiny-after-alphabet-report-panned.html)
19. [S51] Microsoft Nuclear 2026, 835 MW Constellation Deal - Enki AI — enkiai.com — [https://enkiai.com/distributed-energy/nuclear-power-microsoft-demand/](https://enkiai.com/distributed-energy/nuclear-power-microsoft-demand/)
20. [S21] The $3 Trillion AI Data Center Build-Out Becomes All... — energynow.com — [https://energynow.com/2026/02/the-3-trillion-ai-data-center-build-out-becomes-all-consuming-for-debt-markets/](https://energynow.com/2026/02/the-3-trillion-ai-data-center-build-out-becomes-all-consuming-for-debt-markets/)
21. [S7] Queued Up: Characteristics of Power Plants Seeking Transmission Interconnection | Energy Markets & Planning — emp.lbl.gov — [https://emp.lbl.gov/queues](https://emp.lbl.gov/queues)
22. [S56] Natural Gas Turbines Aren't ‘Gating’ Data Center Buildouts, GE Vernova Says — naturalgasintel.com — [https://naturalgasintel.com/news/natural-gas-turbines-arent-gating-data-center-buildouts-ge-vernova-says/](https://naturalgasintel.com/news/natural-gas-turbines-arent-gating-data-center-buildouts-ge-vernova-says/)
23. [S8] GE Vernova Releases Second Quarter 2026 Financial Results | GE Vernova News — gevernova.com — [https://www.gevernova.com/news/articles/ge-vernova-releases-second-quarter-2026-financial-results](https://www.gevernova.com/news/articles/ge-vernova-releases-second-quarter-2026-financial-results)
24. [S33] Powering Data Centers — orrick.com — [https://www.orrick.com/en/Insights/2025/11/Powering-Data-Centers](https://www.orrick.com/en/Insights/2025/11/Powering-Data-Centers)
25. [S55] Dominion Energy details its $65B, 5-year spending plan | Utility Dive — utilitydive.com — [https://www.utilitydive.com/news/dominion-energy-details-its-65b-5-year-spending-plan/812984/](https://www.utilitydive.com/news/dominion-energy-details-its-65b-5-year-spending-plan/812984/)
26. [S25] US power use to beat record highs in 2026 and 2027 as AI use surges... — reuters.com — [https://www.reuters.com/business/energy/us-power-use-beat-record-highs-2026-2027-ai-use-surges-eia-says-2026-10-06/](https://www.reuters.com/business/energy/us-power-use-beat-record-highs-2026-2027-ai-use-surges-eia-says-2026-10-06/)
27. [S42] Over 800 New Generation Projects Seek To Connect Under PJM’s Reformed Process | PJM Inside Lines — insidelines.pjm.com — [https://insidelines.pjm.com/over-800-new-generation-projects-seek-to-connect-under-pjms-reformed-process/](https://insidelines.pjm.com/over-800-new-generation-projects-seek-to-connect-under-pjms-reformed-process/)
