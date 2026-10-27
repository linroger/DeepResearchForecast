# Copper at the End of 2027: A Probability-Weighted Price Forecast for the LME Cash Settlement (P10/P50/P90) Amid the Concentrate Squeeze, Tariff Dislocation, and the Mine-Supply Response

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/copper-2027-r2/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging.

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme |
|---|---|---|---|---|
| F1 | The LME copper cash settlement is at least $14,000/t on the last trading day of 2027 (31 December 2027). | 40% | Resolves YES if the LME Grade A copper official cash settlement (USD/t) on the last trading day of 2027 is >= 14,000; source: LME official data via Westmetall. | concentrate squeeze |
| F2 | Any intraday LME copper print reaches at least $18,000/t on or before 31 December 2027. | 16% | Resolves YES if any LME session print for copper is >= 18,000 USD/t on or before 2027-12-31; source: LME session data via Westmetall. | supercycle breakout |
| F3 | Any intraday LME copper print falls below $11,000/t on or before 31 December 2027. | 22% | Resolves YES if any LME session print for copper is < 11,000 USD/t on or before 2027-12-31; source: LME session data via Westmetall. | demand recession |
| F4 | The calendar-2027 average of daily LME copper cash settlements is above $14,000/t. | 45% | Resolves YES if the mean of daily LME cash settlements for calendar 2027 is > 14,000 USD/t; reference: Goldman 2027 average projection $15,400/t; source: LME/Westmetall. | concentrate squeeze |
| F5 | The Q4 2026 average LME copper cash settlement is at least $14,500/t. | 45% | Resolves YES if the mean of daily LME cash settlements for Q4 2026 is >= 14,500 USD/t; reference: CRU projection $14,500; source: LME/Westmetall. | concentrate squeeze |
| F6 | The 2027 Antofagasta–Chinese smelters annual TC benchmark settles at or below $0.0/dmt. | 75% | Resolves YES if the 2027 Antofagasta–Jiangxi/Tongling benchmark treatment charge announced at or after Asia Copper Week (17-19 Nov 2026) is <= 0.0 USD/dmt; 2026 benchmark settled at $0.0; source: benchmark announcement reported by Fastmarkets/SMM. | concentrate shortage |
| F7 | The SMM imported copper concentrate weekly index prints at or below −$200/dmt at least once between January and June 2027. | 45% | Resolves YES if the SMM Imported Copper Concentrate weekly index is <= -200 USD/dmt in at least one weekly print between 2027-01-01 and 2027-06-30; index was -$231.68/dmt on 2026-09-30; source: SMM. | concentrate shortage |
| F8 | The SMM imported copper concentrate weekly index rises to at least $0/dmt in at least one print during 2027. | 15% | Resolves YES if the SMM Imported Copper Concentrate weekly index is >= 0 USD/dmt in at least one weekly print during calendar 2027; source: SMM. | supply normalization |
| F9 | LME copper stocks fall below 150,000 tonnes at some point during 2027. | 35% | Resolves YES if LME copper warehouse stocks are < 150,000 t on any day in calendar 2027 (from 229,650 t mid-October 2026); source: LME daily stock data. | ex-us tightness |
| F10 | COMEX copper warehouse stocks are below 500,000 tonnes on 31 December 2027. | 40% | Resolves YES if COMEX copper warehouse stocks are < 500,000 t on 2027-12-31 (from >714,000 t in October 2026); source: COMEX daily stock data. | tariff dislocation |
| F11 | The ICSG April 2027 forecast release keeps the 2027 refined surplus at 200,000 t or larger. | 55% | Resolves YES if ICSG's April 2027 forecast release shows a 2027 refined balance surplus >= 200,000 t (October 2026 forecast: 368,000 t); source: ICSG press release. | supply normalization |
| F12 | A First Quantum–Panama restart or framework agreement is signed by 31 December 2027. | 55% | Resolves YES if a restart/framework agreement between First Quantum and the Panamanian government is formally signed by 2027-12-31 (commission recommended negotiations on 30 Sep 2026); source: company/government announcement. | mine supply ramp |
| F13 | Cobre Panama produces saleable copper during calendar 2027. | 20% | Resolves YES if First Quantum quarterly reports show saleable copper production at Cobre Panama in any quarter of 2027; source: First Quantum quarterly reports. | mine supply ramp |
| F14 | Kamoa-Kakula produces at least 500,000 tonnes of copper in 2027. | 70% | Resolves YES if Kamoa-Kakula full-year 2027 production is >= 500,000 t, matching the low end of Ivanhoe's 500,000-540,000 t guidance (3 Dec 2025); source: Ivanhoe Mines reports. | mine supply ramp |
| F15 | Chile produces at least 5.4 million tonnes of copper in 2027. | 50% | Resolves YES if Chilean calendar-2027 mine production is >= 5.4 Mt (Cochilco forecasts 5.27 Mt in 2026 and +5.2% in 2027, implying ~5.54 Mt); source: Cochilco data. | mine supply ramp |
| F16 | The US Annex III floating copper-tariff framework is still in force on 30 December 2027. | 70% | Resolves YES if the Annex III temporary floating-tariff framework for copper remains legally in force on 2027-12-30 (framework runs through 2027-12-31); source: Federal Register / US government notices. | tariff dislocation |
| F17 | The Global price of Copper (fred:PCOPPUSDM) is at least 13000 U.S. Dollars per Metric Ton in December 2027. | 52% | Resolves YES if fred:PCOPPUSDM >= 13000 U.S. Dollars per Metric Ton in 2027-12 (source: FRED). | concentrate squeeze |
| F18 | The Global price of Copper (fred:PCOPPUSDM) is below 11000 U.S. Dollars per Metric Ton in December 2027. | 16% | Resolves YES if fred:PCOPPUSDM < 11000 U.S. Dollars per Metric Ton in 2027-12 (source: FRED). | demand recession |
| F19 | The CBOE Volatility Index (fred:VIXCLS) is at least 25 in June 2027. | 20% | Resolves YES if fred:VIXCLS >= 25 (Index) in 2027-06 (source: FRED). | macro backdrop |

_19 forecasts; 9 high-conviction (≥70% or ≤30%); 17 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Global price of Copper | U.S. Dollars per Metric Ton | 14473.0559 | 2026-09 | +4478.2827 (+44.806%) | 7544.8095 to 14473.0559 | — | [S2] |
| S&P 500 — United States | Index | 7669.4143 | 2026-09 | +1085.3962 (+16.485%) | 3726.05 to 7711.3233 | 7750.4213 (2026-10, partial-period value) | [S22] |
| CBOE Volatility Index: VIX — United States | Index | 15.7755 | 2026-09 | -0.01364 (-0.086%) | 12.67 to 31.9662 | 16.4262 (2026-10, partial-period value) | [S23] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/copper-2027-r2/charts/official_indicators.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/PCOPPUSDM>) [S2]; U.S. Dollars per Metric Ton; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/SP500>) [S22]; Index; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/VIXCLS>) [S23]; Index; Monthly; NSA*

<!-- viz:charts/official_series_qmnrkensreosbodf.html -->
![Official Series History and Forecast Thresholds](demos/copper-2027-r2/charts/official_series_qmnrkensreosbodf.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/PCOPPUSDM>) [S2]; U.S. Dollars per Metric Ton; Monthly; NSA*

## Part 2 — Framework & Synthesis

### The Baseline: A Record Regime with a Paradox

The starting point must be fixed with care because late October 2026 is not merely a high price — it is a record price coexisting with a paper surplus. [S6] The five-year range in the same series runs from 7,544.8 (July 2022) to that September 2026 record [S2] — copper has, in fifteen months, moved from the middle of its historical distribution to its very top.

The paradox sits in the balance sheet. ICSG's October 2026 forecast puts the 2026 refined market in a 104,000 t surplus, widening to 368,000 t in 2027 [S6]. Yet the physical market does not trade like a surplus market. The 2026 Antofagasta–Jiangxi/Tongling annual benchmark settled at $0/t TC and 0.0¢/lb RC, the lowest ever recorded. [S64] Smelters are paying miners for concentrate — the price of the binding input, not refined metal, is what is scarce [S21].

The inventory map explains the rest. LME stocks are 229,650–273,750 t [S4][S5]; combined exchange cover is roughly 0.4 months of world consumption, an extremely thin cushion. Metal exists, but much of it is in the wrong place, behind a tariff wall, unavailable to the ex-US market that sets the LME price.

The framework, in one sentence: in this market the concentrate market sets refined supply, the tariff sets the geography of stocks, and the LME price clears the ex-US refined balance — so the forecast is built by asking whether the concentrate squeeze persists, whether mine supply catches up, and what demand and stockpiling do at the margin.

### The Squeeze Mechanism and Why It Sets the Price

The apparent paradox resolves once treatment charges are treated as the price of the binding input. Deeply negative spot TCs mean that buying concentrate destroys smelter margin on the payable metal alone; refineries keep running on byproduct economics — sulphuric acid, gold, silver — and on market-share logic.

### Mine Supply: The 2027 Swing Factors in Named Increments

Peru's ramp arrives into a 530,000 t concentrate deficit, too late to relieve 2026 tightness [S34]. Mirador's Ecuadorian expansion adds a smaller increment pending approval [S32].

a failed negotiation removes ICSG's single biggest assumed increment.

### Demand, Stocks, and the Calendar

Demand is a tug-of-war between committed electrification build-outs and a decelerating China. EV demand is around 1.2 Mt/yr and growing despite per-unit intensity reductions;

Stockpiling cuts both ways.

extension or escalation is bullish for the ex-US price.

### Price Formation and the Reference Class

In 2026 the "deficit" is a concentrate deficit partially masked by a stranded refined surplus; [S6]

Two reference classes discipline the distribution.

CRU sees $14,500/t for Q4 2026.

### How Market Anchors Were Weighed

Where market-based anchors existed, they were used as calibration, not gospel. we shade below it because prompts embed a convenience-yield/term-structure premium in a backwardated market, and because the tariff-sunset binary is not fully priced in a single prompt quote.

### Defending the Spine

The logic, compressed:

Chinese smelter overcapacity cannot be unwound quickly; byproduct economics and market-share competition have defeated the CSPT pledge for a year;

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Baseline: The Record Regime of Late October 2026 — Price, Stocks, Balances, and Treatment Charges

The starting point for any 15-month copper forecast must be established with unusual care, because the market of late October 2026 is not merely at a high price — it is at a record price that coexists, on paper, with a surplus of refined metal. [S6] This chapter fixes the verified baseline: where the price is, where the metal physically sits, what the balance forecasts say, and what treatment charges are signaling. together they define the initial conditions from which every scenario in this report branches.

### The Price: A Record Regime, Precisely Dated

Second, the level itself: by this report's calculation from the stored FRED/IMF monthly history, the September 2026 reading of $14,473.06/t sits at the 100th percentile of 240 months of observations, up 44.8% year-on-year from $9,994.77/t in September 2025 and at the very top of the five-year range of $7,544.81–$14,473.06 [S2].

The path to this level was violent rather than gradual.

### The Inventory Map: Stranded Metal and a 0.4-Month Cover

The stock picture explains how a record price can coexist with surplus accounting.

The mechanism matters more than the number. Metal that flowed to the United States to pre-empt tariffs cannot economically flow back; the arbitrage that pulled it there has collapsed. The release of the COMEX overhang versus further LME draws, and the behavior of the cash–3M backwardation, are thus the leading indicators to watch for price direction.

### The Balance: A Surplus on Paper, Swinging Forecasts

The forecast's own history argues for skepticism. October 2026 lands at 104,000 t. The same publisher has moved the 2026 balance across zero and part-way back within twelve months, driven by revisions to usage and secondary output rather than by surprises in mine supply. The paradox resolves through the inventory geography and the smelting economics described above and in the next chapter: surplus tonnes that cannot reach the price-setting market do not suppress the price.

### Treatment Charges: The Sharpest Signal in the Dataset

No single number in this baseline is more predictive than the treatment charge.

The divergence among the assessments is itself informative and should not be averaged away. It stems from three methodological differences. First, the underlying indices sample different transaction pools: SMM's imported concentrate index draws on Chinese port-spot trades assessed weekly [S20], while Fastmarkets captures a somewhat different set of deals and impurities basket [S6], so the two can differ by tens of dollars per tonne at the same moment. Third, contract structure matters: with the 2026 benchmark at $0/t and mid-year settlements shifting toward index-linked pricing, the spot indices are increasingly the *only* price-discovery mechanism for marginal tonnes, which amplifies volatility in the assessments themselves. [S7]

The implication is structural. When TCs are deeply negative, smelting capacity is not the binding constraint on refined supply — concentrate is. Chinese refineries can add nameplate capacity without adding a tonne of output, because the feed does not exist at economic terms. This caps ex-US refined availability regardless of the surplus ICSG expects from the demand side, and it is the transmission channel through which mine-supply outcomes (Chapter 3) will determine whether the squeeze persists or breaks.

### Reconciling the Paradox: The Baseline as the Scenario Map

Each of the four baseline legs maps directly onto the scenario probabilities this report assigns. it needs only the dislocation to hold.

The chapters that follow assign probabilities to each branch; the baseline established here is the yardstick against which all of them will be scored.

## The Squeeze Mechanism: Why Negative Treatment Charges Set the Price of Refined Copper

The apparent paradox of late 2026 — record LME prices coexisting with a modest realized refined surplus — resolves once the treatment charge is treated not as a peripheral contract term but as the price of the binding input itself. [S6] This chapter sets out the mechanism the rest of the forecast rests on: deeply negative spot TCs make concentrate acquisition a cash cost for Chinese smelters, which caps refined output regardless of nameplate capacity, keeps ex-US availability structurally short, and therefore sets the floor under the LME price.

### From a $12 Gap to Paying Miners for Feed

Fastmarkets assessed the spot TC even lower, at −US$272.20/t on 9 October 2026 [S6]. Crux's framing is blunt: Chinese smelters are now paying miners for copper concentrate, because mine supply — not smelting capacity — is the key constraint [S21].

The historical context shows how anomalous this is. In a normal regime, the benchmark and the spot market track each other within a dozen dollars;

The benchmark system itself is fragmenting under the strain. This matters for the forecast because a fragmented, index-linked benchmark removes the annual reset mechanism through which past concentrate gluts transmitted quickly into looser terms and higher refined runs;

### Discipline Pledged, Discipline Deferred: The CSPT Compliance Gap

The Chinese smelting sector's response to negative TCs has been the swing variable that surprised the market in 2026. [S64]

The mechanism behind the compliance gap is byproduct economics. Sulphuric acid, gold and silver revenues cushioned smelters against the concentrate processing loss;

Policy is tightening both feed channels simultaneously. The consequence is that the smelting sector cannot escape the concentrate shortage on either margin: primary feed is scarce and repricing violently negative, while secondary feed — the usual relief valve when copper sits above $14,000/t — is administratively suppressed. [S6] The result is a policy-induced tightening that runs against the smelting provinces' employment and output interests, a tension Beijing has so far resolved in favor of discipline.

### The Blister Constraint and the Implied Refined-Output Path

Below the concentrate market sits a second, quieter bottleneck: blister and anode copper. Because scarce, negative-TC concentrate caps how much new anode can be produced, smelters wanting to hold refined volumes must buy blister and anode on a market where everyone else faces the same constraint. The result is that even refineries with idle electrolytic capacity cannot run it without feed, and the refined-output ceiling is set upstream, not by nameplate capacity.

Put differently: ICSG's refined-output projection embeds an implicit view that the blister-and-anode constraint eases in step with mine supply, because secondary refined output — the other route to cathode that bypasses concentrate — is itself being throttled by the scrap-tax crackdown [S8][S38].

Even the lower bound dwarfs the 368,000 t global surplus ICSG projects for 2027. [S6] This report's estimate, not an observed figure: the squeeze mechanism implies that the ICSG surplus is achievable only if CSPT discipline is abandoned or if mine supply overshoots.

### The Transmission Rule: From the Concentrate Index to the LME Price

The final step is the mapping the rest of the report applies. The LME cash price is the clearing price of that ex-US residual market, which is why the 2026 rally was concentrate-scarcity, tariff-dislocation and expectations driven rather than refined-deficit driven — record prices against a modest realized surplus, with the benchmark TC at zero. [S6]

In operational terms, this report reads the SMM imported concentrate index as the master indicator:

The link from this transmission rule to the skeleton weights is explicit rather than decorative. The two weights are not independent judgments;

One honest caveat completes the picture. The named increments that would rescue the concentrate market are mostly either late, unagreed, or guided downward. Until they land, the treatment charge — not the refined balance — is setting the price.

## Mine Supply: Named Increments, Disruption Rates, and the Cobre Panama Swing Factor

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/copper-2027-r2/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

The mine-supply side is where the 2027 copper price will be decided. [S62] Everything else in this forecast — the negative treatment charges, the stranded COMEX stocks, the Chinese smelter discipline — describes how the market transmits scarcity; This chapter quantifies the named supply increments in kt/yr, weighs them against disruption and grade-decline base rates, and prices the single largest swing factor: whether Cobre Panama produces a single tonne of concentrate next year.

### The Cobre Panama Swing: ~330 kt/yr of Optionality with No Timeline

On 30 September 2026, a Panamanian government commission recommended opening negotiations to reopen the mine while financing an orderly, phased closure; [S33] Reuters characterized the recommendation as a restart to fund a gradual shutdown rather than a permanent operation [S33]. Critically, no scope, no timing and no legal structure for a restart has been set — First Quantum has stated openness to negotiation but made no binding commitments, and the government's posture, while incrementally more accommodative since September, remains formally neutral [S33].

The structure of the recommendation matters for timing. The historical base rate for complex mine restarts after multi-year political closures is measured in years, not quarters.

- Even under a signed framework, restart of a mill and concentrator idled since late 2023 requires recommissioning, staffing and ramp — realistically six to nine months from signature to first concentrate, so only a Q1-2027 signature delivers meaningful 2027 tonnes. [S24]

The asymmetry is the point. A failure to restart subtracts nothing from 2026 supply — the market has already lived without these tonnes for three years — but it removes the largest single increment embedded in the 2027 surplus story. [S6]

### Delivered Increments: Kamoa-Kakula, QB2 and the Chilean Rebound

Against the Panama uncertainty, three named increments carry company guidance that can be tracked quarterly.

**Kamoa-Kakula (Ivanhoe Mines, DRC)** is the most bankable of the group. Two caveats temper, but do not overturn, the increment. Second, the constraint set is DRC power supply and ramp execution, both of which have bitten before at this operation.

**Quebrada Blanca 2 (Teck, Chile)** is a subtraction from the surplus narrative. The cut remains unconfirmed on Teck's own release, a caveat that cuts both ways: the reported numbers could be revised in either direction, but the tailings issue is physical, not commercial, and does not resolve on a price signal.

### The Base Rates: Chile's Delivery Record, Peru Disruption, and Grade Decline

**Chile / Codelco — the credibility test.** Codelco — the state miner whose recovery is the backbone of Cochilco's rebound path — spent January–July 2026 producing at a 15-year low, and the September El Teniente accident landed squarely on the flagship underground operation expected to lead the 2027 recovery. [S20] The structural headwind is ore-grade decline: Chilean grades have fallen persistently over recent years, a subtraction that offsets headline capacity additions every quarter and converts each percentage point of forecast growth into a larger required volume of new mine tonnes. The gap between Cochilco's recovery forecast and Codelco's persistent underdelivery through July 2026 is the largest single soft spot in the supply-catches-up case. [S64] it argues for discounting the Cochilco number by a third to a half.

**Peru — disruption rates versus the historical base.** Peru is a net drag inside the horizon. Peru's copper push arrives, in the words of that analysis, too late for a concentrate market that is already short [S34].

**Grade decline as the compounding base rate.** The Chilean and Peruvian evidence converges on one base rate: ore-grade decline is not a one-off disruption but a persistent annual subtraction. Where the disruption base rate is mean-reverting — El Teniente-type accidents do not compound — grade decline does compound, raising the effective hurdle that named projects must clear just to keep national production flat. This is why the probability-weighted Chilean increment above is discounted against the Cochilco headline, and why the same haircut logic is applied across the stack.

### Does ICSG's 3.1% Survive Its Own April 2027 Revision?

Summing the probability-weighted increments gives the test.

ICSG's own revision history makes the discount defensible rather than contrarian. An institution whose balance forecasts move by that magnitude in twelve months does not deserve point-estimate confidence on its mine-growth line eighteen months out. if it cuts mine growth below roughly 2% as the Chilean and Panamanian evidence above suggests, the squeeze-persists regime is confirmed even against a headline surplus number [S16].

A steelman of the other side deserves an answer before concluding. The reply is that grade decline is not bad luck but a trend: Chilean grades have fallen persistently, converting each percentage point of forecast growth into a larger required volume of new mine tonnes. And the 2026 evidence already shows the mechanism: ICSG cut its 2026 mine-growth forecast from 1.6% to 1.3% in the October round even as it raised 2027 — the same institution, one year apart, discovering that current-year delivery always trails the plan. [S6] High prices pull supply; they do not repeal geology or permitting timelines.

## Demand: Electrification Build-Outs Against the China Property Drag

The demand side of this forecast is a tug-of-war between two forces of very different character.

### The Electrification Engines: Grid, EVs, Datacentres

Grid investment is the single largest and most reliable copper-demand engine. it re-tenders with longer delivery times.

EVs are the second engine but a decelerating one. The critical dynamic is that per-unit copper intensity is falling — driven by efficiency-driven content reductions — which partly offsets the still-growing global build rate. A buyer of the supercycle thesis on EVs alone would be buying yesterday's curve.

Datacentres are the smallest but fastest-growing engine. S&P Global's electrification framing reinforces the direction: the AI build-out is, physically, a copper-and-grid problem before it is a chip problem [S43]. Their real significance is the floor they put under US and Asian wire-and-cable demand at exactly the moment Chinese property-linked fabrication is weakest, which stabilizes global demand dispersion even as aggregate growth slows.

### The China Drag: Deceleration, Not Collapse

Against those engines stands the traditional-sector slowdown. Kit Yu's summary of the demand picture — a slowdown in aggregate copper demand activity concentrated in traditional sectors even as emerging sectors accelerate — captures the structure [S44]. That subtraction is almost exactly offsetting the entire emerging-sector increment in gross terms.

A steelman of the opposing view deserves weight: Deutsche Bank's stockpiling thesis and the grid/EV literature argue demand growth is being systematically underestimated, because electrification projects are undercounted in official statistics and stockpiling (US Project Vault, possible SRB buying) shows up as apparent demand [S53]. The counter-response is that the same statistics have overestimated Chinese apparent demand in the recent past when inventory built silently in bonded and exchange warehouses — visible stocks at 0.4 months of cover argue against a large hidden surplus, but they equally argue against hidden demand strength. Net: the report stays with the ICSG-anchored central estimate and does not add a speculative stockpiling premium to demand; stockpiling is treated in Chapter 5 as a positioning variable, not a consumption variable.

### Secondary Supply and Substitution: The Broken Scrap Valve

The most consequential demand-side distortion of the current regime is what high prices normally trigger but currently cannot: a scrap surge. ICSG forecasts a secondary-output boost in 2026–2027 as recycling responds to price [S38]. In a normal $14,000/t world, price-elastic secondary supply would flood in — scrap generation is strongly price-responsive above incentive thresholds, and 2021 demonstrated how quickly secondary refined output expands when spreads widen. [S6] But the usual valve is jammed. The Chinese scrap-tax crackdown has tightened secondary feed and suppressed the collection-and-processing chain precisely when price signals scream for more scrap. Combined with the eight-month sulphuric-acid export suspension since May 2026, both primary and secondary feed streams into Chinese smelters are constrained by policy rather than economics. [S6] The result is perverse for the price: high prices that should ration demand and mobilize scrap instead do neither efficiently, so the market clears through the LME price rather than through quantity adjustment.

If the crackdown were relaxed in 2027 — a plausible policy response once Beijing's smelter-discipline objectives are met — secondary supply could add back several hundred kt/yr on its own, which would work in the same direction as ICSG's projected 368,000 t refined surplus. [S6] The April 2027 ICSG revision and any Chinese policy signal on scrap taxation are therefore joint discriminators between the modal scenario and normalization.

Aluminum substitution is the other rationing margin. The reason is redesign lead time: substitution decisions are made at product-platform refresh, not at spot price.

## Stocks, Tariffs, and Strategic Stockpiling: The Dislocated Inventory Map

This chapter maps that inventory geography, traces the tariff timeline that created it, weighs the two great discretionary stockholders (China's State Reserve Bureau and the US government's Project Vault), and shows how each stockpiling or release branch shifts the quarterly price trajectory and the probability mass among the report's scenarios.

### The Section 232 Timeline That Split One Market in Two

The dislocation has a precise legislative genealogy.

The mechanics of the split are straightforward. Two consequences follow. Second, once the arbitrage collapsed, the ex-US market lost access to that metal entirely. As Crux's analysis of LME and COMEX data put it, the tariff-arbitrage collapse "strands US copper, lifting ex-US pricing" [S4].

A surplus that cannot be delivered to ex-US consumers does not cap the LME price. SMM's own analysis concluded that although "the US copper tariff trade is fading — but it isn't over yet," the structural price premium consequences persist through the tariff's life [S13].

**The sunset as a volatility event.** Two branches matter:

- If the floating tariff lapses, the stranded COMEX stock becomes deliverable to the world market.
- **Renewal or escalation.**

But that argument assumes the sunset's outcome is known, and it is not — the framework was designed to expire on the forecast date itself, meaning the market must price a binary-ish policy event at the horizon. Option value, not level, is what is mispriced;

### The COMEX Strand and the Low-Cover Floor Under the LME Price

The inventory arithmetic deserves precision. Effective ex-US cover, counting LME stocks alone, is closer to ten days.

Meanwhile the COMEX pile grows, inflating "global" stock numbers that would otherwise signal glut. This is why the report treats the ICSG 2027 surplus forecast of 368,000 t as only weakly price-bearish while the strand persists: the surplus is real in tonnage but dislocated in geography. [S6]

The strand also interacts with the state stockpiling programs in a way that compounds the dislocation rather than resolving it. Every tonne Vault absorbs is a tonne removed from the free float without easing the LME cover; In that configuration, the ICSG surplus [S14] and the stockpiling programs are not offsetting forces but twin drains on market-clearing metal — one geographic, one institutional.

The unwind risk cuts both ways. After that, the marginal direction of COMEX stocks turns negative — either through tariff-influenced US domestic consumption or, post-sunset, through re-export. No precise post-sunset drawdown rate exists in the evidence base;

- resolution via the LME daily stock report as compiled by Westmetall [S5].
- sustained rebuilding of this magnitude most plausibly follows a confirmed Annex III sunset plus returning concentrate availability.
- Achievable through Project Vault absorption, tariff-influenced US consumption, or post-sunset re-export;

### Two Leviathans: The SRB and Project Vault

Discretionary state stockpiling is the second axis of the dislocated inventory map, and it operates on both sides of the Pacific simultaneously — an unprecedented configuration.

**China's State Reserve Bureau.** The verified record shows no confirmed SRB buying at 2026's record prices, but the February 2026 recommendation by the China Nonferrous Metals Industry Association to expand state reserves establishes a policy inclination. [S55]

**US Project Vault.** DWS's analysis similarly frames copper as poised "between shortage and stockpiling" [S47].

**Why this report discounts the supercycle stockpiling case relative to Deutsche Bank.** The bullish steelman: two governments with strategic motives, a combined war chest well above $12bn, a 0.4-month cover starting point, and demonstrated first deliveries — mechanically, only a few hundred thousand tonnes of sustained net official buying would exhaust the ex-US free float. and both programs face fiscal and political constraints that a private bank forecast does not price.

### Mapping the Branches to the Quarterly Trajectory

- locks in the Scenario I floor and fattens the Scenario III tail;
- the principal mechanism by which the P10 could be realized without a macro recession.

The through-line of this dislocated inventory map is that the end-2027 price depends less on how much copper exists — the ICSG surplus arithmetic [S14] — than on where it sits and who controls it. the two largest potential marginal buyers are states, not fabricators; and the LME stock cover that historically anchored price formation is, ex-US, effectively ten days [S5]. The inventory thresholds above are the report's commitment to being wrong in observable ways.

## Price Formation and the Reference Class: History, Cost Curve, and Bank Consensus

The central analytical problem for forecasting the LME cash price on 31 December 2027 is that copper is currently trading at record levels under a price-formation mechanism that does not match the textbook template of either 2006 or 2021. In both of those prior cycles, a refined-market deficit — visible, measurable, and confirmed by successive stock draws — transmitted directly into price.

### Why This Rally Is Not the 2006 or 2021 Template

Chinese smelters are paying miners for feed. combined exchange cover is approximately 0.4 months of world consumption. The price is therefore being set by the marginal availability of ex-US refined metal, which is capped not by smelting capacity but by the economics of buying concentrate at deeply negative treatment charges.

This distinction matters for forecasting because the transmission mechanisms revert at different speeds.

### Demand-Shock Base Rates and the Volatility Envelope

The external view from the FRED/IMF monthly copper series (PCOPPUSDM) disciplines the scenario bands.

The same volatility arithmetic caps the upside. The options market and this report roughly agree on the upper tail; the disagreement is concentrated in the middle of the distribution.

A word in favor of the higher-priced view, steelmanned: the squeeze interpretation has strong empirical support on its own terms. If strategic buying absorbs even a fraction of the projected surplus, the physical balance flips back to deficit regardless of mine-supply delivery, and Goldman's numbers become conservative rather than aggressive. This is a coherent case;

### The Cost-Curve Floor

Wood Mackenzie's global copper mine cost-curve work and derivative 90th-percentile analyses anchor the downside. The analytical point for end-2027 pricing is directional: the price required to incentivize the marginal tonne of new mine capacity has been drifting upward with ore-grade decline and disrupted Chilean output — Cochilco cut its 2026 production forecast even while raising its price forecast [S28][S29] — meaning the floor under copper in a normalization scenario is materially higher than in prior cycles. The cost curve does not set the price in a squeezed market; it sets where the price lands when the squeeze breaks.

### Bank Consensus as the Reference Class

The consensus cluster is tightly bunched and recently revised upward. CRU forecasts $14,500/t for Q4 2026 [S6]; CRU's data also show the mid-2026 shift toward index-linked concentrate pricing, an implicit admission that the annual benchmark is losing its price-discovery function. [S7]

Two features of this consensus deserve scrutiny. Second, the consensus embeds the squeeze persisting at close to full intensity through 2027 — flat to backwardated forward curves and averages above year-end levels — while ICSG's surplus projection, whatever its vintage instability, points the other way [S14]. Both cannot be right.

### Why This Report Sits Below Consensus

The reasoning is specific. The consensus overweight the squeeze's persistence at full intensity; it underweights three developments with meaningful probability by end-2027: (i) partial TC recovery as the 2027 benchmark either settles at or below zero or fragments into index-linked structures — a market that has already moved structurally — signaling that concentrate availability, not refined demand, is the price-setter and that this variable mean-reverts once mine ramps deliver even partially; [S16] and (iii) the April 2027 ICSG revision cycle, which on the vintage history has moved the balance by hundreds of kilotonnes and could confirm the surplus just as physical evidence accumulates. [S14]

## Scenario I — Squeeze Persists / Elevated Regime (40%): $13,000–$18,000/t at End-2027

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/copper-2027-r2/charts/scenario_probabilities.png)

*Scenario Probabilities*

This chapter sets out the argument, the quarterly price path, the trigger chains, the strongest counter-case, and the explicit falsification criteria.

### Why the Squeeze Outlasts the Mine-Supply Response

The single most important structural fact is the arithmetic of the concentrate market. A gap of this magnitude, persisting for a second consecutive year, means Chinese smelters are paying miners for feed — a condition that mechanically caps refined supply whatever nameplate capacity exists, because marginal tonnes are produced at a loss on treatment alone.

On 30 September 2026 a Panamanian commission recommended opening negotiations to reopen the First Quantum mine while financing an orderly closure, but no scope, timing or legal structure has been set; [S33] Even an agreement signed in H1 2027 would face a recommissioning lag: a mine shut since late 2023 needs dewatering, equipment recommissioning and workforce reassembly before concentrate flows resume, and any legal structure embedding "an orderly closure" implies a finite, possibly partial, operating envelope. [S24]

Second, the Chilean recovery has a credibility gap.

### The Smelter-Discipline Chain and the November 2026 Catalyst

The precedent is instructive.

The squeeze-persists path assumes the byproduct cushion erodes faster than the discipline cracks. the scrap-tax crackdown shrinks secondary feed; With the 2027 benchmark settling at or below $0/t TC — or fragmenting entirely into index-linked pricing, which CRU reports as the observed direction of travel after provisional mid-year settlements — the economic case for running marginal capacity disappears. [S7] Blister and anode constraints bind before cathode capacity does: you cannot solve a concentrate shortfall with refining cells.

The refined-supply consequence is that ex-China and ex-US refined availability stays capped even as headline global balances print a surplus.

### The Stranded-Stocks Floor and the Tariff Calendar

The calendar matters enormously here.

On the demand side, this scenario requires no acceleration — only that the structural build-outs hold against the China drag. EVs contribute over 1 Mt with intensity reductions offsetting build-rate growth. That is upside optionality within the band rather than a requirement.

### Quarterly Trajectory and the Honest Counter-Case

Within this scenario, the most likely quarterly path is:

- the post-benchmark squeeze premium holds.
- Prices drift lower within the band but the floor holds on low ex-US cover.

The response is that the resolution mechanism in prior cycles ran through the refined market, not the concentrate market; the acid-export suspension and scrap crackdown are precisely the policy tools removing that cushion.

### Resolution and Falsification Criteria

**Falsification — any of the following would defeat this scenario before or at the horizon:**
1. The SMM imported concentrate index recovers above −$100/dmt and holds there for a sustained period (a quarter or more), indicating the concentrate gap is closing faster than assumed [S20].

Panama negotiation milestones (framework signed, scope set); LME stock prints;

## Scenario II — Supply Catches Up / Normalization (29%): $11,000–$13,000/t at End-2027

### The Supply Ledger That Has to Arrive — and Its Named Increments

The scenario's credibility therefore rests on a small number of named tonnes.

On 30 September 2026 a Panamanian commission recommended reopening the First Quantum mine specifically to fund an orderly, phased closure — an awkward but politically saleable structure that converts restart revenue into closure financing [S33]. Nothing else about scope, timing, or legal framework has been set. The realistic version of this scenario assumes a framework agreement in H1 2027, first concentrate late in 2027, and the full tonnage arriving in 2028 — meaning Cobre Panama's direct 2027 contribution to concentrate supply is modest, but its *signaling* contribution is enormous: a signed agreement validates the ICSG supply thesis, pulls the concentrate market's expectations of scarcity forward into expectations of adequacy, and is the single event most capable of flipping the 2027 benchmark negotiation dynamics. [S16]

The third and fourth increments are Chilean. A normalization scenario does not require perfection here — it requires that Chile stops being a subtraction.

### The Transmission Chain: From Concentrate Adequacy to TC Recovery to Lower Prices

The mechanism by which these tonnes translate into lower prices runs through the concentrate market, not directly through refined availability. So the normalization scenario requires the scarcity premium to unwind, and the observable instrument for that unwind is the spot TC.

The path is steep but not unprecedented.

that would be implausible given the September spot prints. It requires the benchmark to settle at or only modestly below $0/t, or to fragment into the index-linked pricing toward which Antofagasta shifted provisionally in mid-2026 per CRU. [S7] The scenario dies if the benchmark settles deeply negative — that would signal smelters paying for contractual feed well into 2027 and would validate the squeeze-persists regime. [S24]

The demand side of the transmission works in the same direction. High prices are, in this scenario, doing their classical job: calling forth supply and destroying marginal demand simultaneously, with a lag.

### The Stock Rebuild and the Annex III Sunset as the Q4 2027 Confirmation

The final leg of normalization is inventory.

The quarterly trajectory within this scenario is deliberately patient.

### The Steelman Against This Scenario — and Why It Still Earns 29%

The strongest objection is that every prior assurance of relief has failed. That same byproduct cushion means Chinese refined output responds sluggishly even when TCs recover, limiting how fast the surplus materializes. Chile has been promising a rebound through a 15-year-low start to 2026 and an El Teniente accident that disrupted concentrate further. [S20] QB2's guidance cut is the rule, not the exception, for brownfield ramps.

The answer is that this scenario does not require trusting the number — it requires trusting the *direction* of named, funded, partially-delivered projects. Kamoa-Kakula's +120 kt is not a forecast; it is a run-rate already visible in quarterly production reports.

### The Asia Copper Week Checkpoint in Full — 17–19 November 2026

Because it is the first dated, public, falsifiable event after the as-of date, the Asia Copper Week benchmark negotiation deserves a complete treatment as this scenario's opening gate. The negotiation pits Antofagasta against the Chinese smelter group led by Jiangxi Copper and Tongling — the same counterparties who settled the 2026 benchmark at a record-low $0/t TC and 0.0¢/lb RC in January 2026. [S64] Three outcomes are possible, and each maps cleanly onto scenario probabilities.

A $0/t settle is therefore normalization-compatible even though it is nominally identical to 2026: the information content is in the direction of travel versus spot, not in the absolute number. [S7]

The second outcome is the structural one: no single number at all, but a migration to index-linked pricing, the direction Antofagasta had already shifted provisionally by mid-2026 per CRU's assessment of the mid-year settlements. [S64] Freeport's 2026 floor-cap contract structure, reported by Fastmarkets around LME Week, shows the industry already has the machinery for such hybrids [S19].

this report would treat a collapse-without-settlement as weak evidence for the squeeze regime rather than for normalization.

The scenario's explicit falsification triggers, in order of arrival: the 2027 benchmark settling materially below $0/t in November 2026; [S64]

## Scenario III — Supercycle Breakout (12%) and Scenario IV — Demand Recession (15%): The Tails

The middle of the distribution is decided by whether mine supply catches up with the concentrate shortage; the tails are decided by politics (tariff escalation, state stockpiling decisions in Washington and Beijing) and by macro demand (equity stress, Chinese construction, price-driven demand destruction). This chapter sets out the trigger chains, conditional quarterly trajectories, leading indicators and resolution criteria for both tails, and explains why the probabilities are calibrated where they are.

### Scenario III — Supercycle Breakout (12%): Above $18,000/t at End-2027

**Three independent trigger chains lead there, and any one is nearly sufficient:**

1. **Tariff re-escalation and the COMEX drain.** The mechanism is mechanical: deeper tariffs extend the strand, keep ex-US cover near the current ~0.4 months of world consumption, and force ex-US consumers to bid for a physically thinner pool.

2. **State stockpiling at scale, from both capitals.** Deutsche Bank's widely cited call for a 50% price jump within a year rests precisely on this twin-stockpiling logic [S53]. But the CNIA recommended expanding copper reserves in February 2026, and price inquiries were reported in March 2025 — Beijing has kept the option visibly alive.

3. **A major supply shock on top of an already thin concentrate market.**

**Steelman and response.** The response is that the 2026 rally was concentrate-scarcity, tariff-dislocation and expectations driven rather than refined-deficit driven — the price is set at the margin by available ex-US refined metal, and every one of the three trigger chains above tightens that marginal availability further. [S55] The scenario does not require the headline balance to flip; it requires the dislocation to deepen.

**Conditional quarterly trajectory under Scenario III:**
- Chinese refined output growth stalls under sustained negative TCs, cutting ex-US refined availability by several hundred kt annualized [S8].

### Scenario IV — Demand Recession (15%): Below $11,000/t at End-2027

**The trigger chain here is macro-first, copper-second:**

1. **A global or Chinese downturn.**

2. **High-price demand destruction and aluminum substitution.** If Beijing eases the crackdown in response to a demand slump, secondary supply floods back exactly when demand is weakest, compounding the downside. ICSG already forecasts a secondary-output boost into 2027 [S38].

3. **SRB releases rather than purchases.** If a Chinese downturn pushes prices down and Beijing prioritizes industrial consumers over strategic accumulation, releases would accelerate the slide;

this report treats that as vanishingly unlikely because the demand structure has changed.

**Steelman and response.** The recession scenario needs the demand leg to break, not just the supply forecast to be right.

**Conditional quarterly trajectory under Scenario IV:**
- Beijing eases the scrap-tax crackdown and secondary supply expands per ICSG's secondary-output forecast [S38]. Aluminum substitution orders at fabricators lock in at these prices.
- Chinese refined output discipline collapses in the other direction — overcapacity chases market share into falling prices [S8].
- That expiry mechanics cut both ways is a distinctive feature of this horizon: the same dated event amplifies whichever tail is active.

### Leading Indicators, Resolution Criteria and the Residual Bin

The two scenarios are discriminated in real time by a small set of observable series:

- **Chilean/Peruvian production prints and Codelco operational notices:** a second El Teniente-class event or a Peruvian disruption is the supply leg of Scenario III.

### Reconciling the Tails with the Central Scenarios

Because the tails are conditional on distinct variables — Washington/Beijing state action and accident risk on one side, macro and Chinese construction on the other — they can be assessed additively against the central cases without overlap. Scenario III requires an affirmative act: a tariff decision, a tender award, or an accident. History says copper's crashes come from within; its breakouts usually need a push.

## The Probability-Weighted Central Forecast: P10/P50/P90 and the Most-Likely Quarterly Path Through 2027

This chapter synthesizes those findings into the headline deliverable: a probability-weighted end-2027 price level with explicit P10/P50/P90 bands, a most-likely quarterly path, and a comparison against the forward curve and bank consensus that explains — and defends — this report's deliberate discount to the market. [S62]

### The Central Numbers: P50 ≈ $13,400/t, Weighted Mean ≈ $13,750/t, P10 ≈ $9,900/t, P90 ≈ $18,300/t

The result of the weighting is:

- this report prices the fat upper tail somewhat cheaper than the options market because that tail requires a conjunction of events (tariff escalation plus confirmed state stockpiling plus a supply shock) rather than any single one.

Two features of this distribution deserve emphasis.

### The Most-Likely Quarterly Trajectory: A Slow Deflation of the Squeeze Premium

Prices drift lower not on balance-sheet deterioration but on the market beginning to price the *possibility* of TC recovery.

if it cuts the surplus on another Chilean or Peruvian shortfall, the squeeze re-intensifies. Either way, Q3 is the quarter of maximum forecast revision.

Three branches frame it. If the tariff regime lapses or is liberalized, the stranded US metal re-enters world flow: even a partial re-direction of the stockpile into LME-eligible delivery would rebuild combined exchange cover from its current ~0.4 months of world consumption toward historical norms, a mechanically bearish flow event that would validate the low end of this report's band. If instead the tariffs are extended or restructured by Commerce/USTR before the sunset — a live possibility given the rolling Section 232 additions of 2026 [S46] — the strand persists and the ex-US squeeze premium survives into 2028, supporting prices at or above the modal path.

### Why This Report Sits ~$1,200/t Below the Forward: The Case Against the Market's Squeeze Persistence

The divergence is not a general bearishness; it rests on three specific claims, each falsifiable.

**First, the market underprices TC recovery.** The forward curve implicitly treats deeply negative spot TCs as a persistent steady state. QB2 contributes within a known, if reduced, range; and Peru's push continues even against its 530,000 t concentrate deficit [S34].

**Second, the market overweights the squeeze at full intensity.** If 2027 discipline holds even at half the pledged rate, the refined supply response to any TC recovery is *asymmetric to the downside for price*: the moment feed becomes available, idled capacity restarts quickly, converting a concentrate shortage into a refined surplus faster than the forward curve's smooth backwardation implies.

**Third, the Annex III sunset is a two-sided event the market prices one-sidedly.**

The steelman against this report's discount deserves honesty: the squeeze has already survived every predicted resolution date. The discount to consensus is a bet on mean reversion in *TCs and smelter behavior*, not in demand.

### Sensitivity and What Would Move the Number

The central forecast's most important sensitivity is the probability split between Squeeze and Normalization. The observable events that would force an update, in approximate order of information value:

3. continued stalemate keeps the squeeze branch dominant.
4. **SMM weekly TC index:** sustained recovery above −$100/dmt is the falsification trigger for the Squeeze scenario; [S20]

## Twelve-Plus Binary Forecasts with Resolution Criteria

### Why Binary Forecasts: Making the Distribution Falsifiable on a Schedule

The fourteen binary forecasts in this chapter do something different: each one is a dated, verifiable claim about a mechanism — the concentrate squeeze, the tariff strand, the stockpilers, the mine-supply response — that either occurs or does not occur at a specific moment, anchored to a specific publisher. Together they form the falsification spine of the whole report: if the physical-market binaries (treatment charges, inventories, the Cobre Panama negotiation) resolve toward normalization faster than the price binaries, the scenario weights must shift; if the price binaries resolve high while TCs stay deeply negative, the squeeze mechanism is confirmed and the P50 should migrate toward the forward curve.

The calibration draws on three documented base-rate families. Each probability below is a judgment of this report, not a quotation from any publisher, and is flagged as such.

### The Fourteen Binary Forecasts

| # | Forecast | Probability (this report's estimate) | Resolution criterion | Resolving source & date |
|---|---|---|---|---|
| 1 | — | 55% | — | Westmetall LME cash table; |
| 2 | — | 55% | — | Westmetall daily table |
| 3 | — | 40% | — | Westmetall daily table |
| 4 | — | 30% | — | Westmetall; Crux monthly averages |
| 5 | — | 60% | — | Antaike/SMM/Reuters settlement reporting; CRU's index-pricing analysis |
| 6 | — | 55% | — | SMM imported concentrate weekly index |
| 7 | — | 35% | — | SMM; Fastmarkets [S20] |
| 8 | — | 45% | A signed framework or definitive agreement between First Quantum and the Government of Panama permitting restart | First Quantum disclosure; Reuters negotiation reporting |
| 9 | — | 30% | — | First Quantum quarterly reports |
| — | — | — | — | Westmetall/LME stock data [S5] |
| — | — | — | — | LME/COMEX stock reports; ICSG statistics |
| — | — | — | — | Chinese tender notices as reported by Reuters/Mining.com |
| 13 | — | 50% | — | ICSG press release, April 2027 |
| — | — | — | — | Federal Register / White House proclamation texts [S67] |

### The Treatment-Charge Binaries: The Mechanism Test

Forecasts 5–7 are where the report stakes its central causal claim — that deeply negative TCs, not the headline ICSG balance, set ex-US refined availability and hence the LME price.

### Calibration Discipline and the Update Cadence

These fourteen forecasts are mutually informative, not independent. a positive resolution of Forecast 8 initiates the same shift with a one-to-two-quarter lag through the concentrate shipping cycle. The monitoring cadence is therefore set by the resolution dates themselves: the Asia Copper Week settlement and the CSPT's 2027 output-policy decision in November 2026, weekly SMM and Fastmarkets index prints, the ICSG April 2027 release, First Quantum's quarterly disclosures, tender notices from Beijing and Washington, and the Federal Register for tariff actions. [S16]

## Forecast Summary Table and Calibration: Evidence Base, Confidence, and Divergences

Every forecast in this report reduces to one table. The preceding chapters assembled the evidence — the record-regime baseline of late October 2026, the squeeze mechanism running through deeply negative treatment charges, the named mine-supply ledger, the demand tug-of-war, the dislocated inventory map, and the scenario tree — and this chapter consolidates all of it into a single summary structure, then subjects that structure to a calibration audit: where the probabilities came from, why overall confidence is medium rather than high, and exactly where this report diverges from Goldman Sachs, the LME forward curve, and the CRU/J.P. Morgan cluster — with the evidence that would force each divergence to close.

### The Consolidated Forecast Table

The mutually exclusive partition, the conditional price outcomes, and the derived quantiles are as follows:

| Scenario | Probability | End-2027 band (LME cash, $/t) | Conditional midpoint | Principal drivers | Falsification triggers |
|---|---|---|---|---|---|
| I. Squeeze persists / elevated regime | — | — | — | Deeply negative spot TCs (SMM −$231.68/dmt, 30 Sep 2026 ); [S7] CSPT discipline after Asia Copper Week; Cobre Panama non-restart | — |
| II. Supply catches up / normalization | — | — | — | TC recovery toward zero | 2027 benchmark deeply negative in Nov 2026; [S7] |
| III. Supercycle breakout | — | — | — | Tariff re-escalation (Annex III, ); a second supply shock | no shock |
| IV. Demand recession / hard landing | — | — | — | Annex III lapse converting strand to overhang | Electrification floor holds; SRB buys the dip; no macro break |
| V. Residual / mixed path | — | (path-dependent) | — | Round-trip paths satisfying no scenario trigger logic | — |

The internal consistency of the table is worth one explicit check. No probability in the table was set independently of the others; the partition, the quantiles, and the fourteen binary forecasts were reconciled so that each is an expression of the same underlying distribution.

### Probability Provenance: The Four Base-Rate Families

None of the five scenario weights was assigned from narrative conviction alone. Four documented base-rate families discipline them.

**First, the price-history distribution.** The report's tighter, lower distribution reflects two case-specific adjustments: the 100th-percentile starting point argues for mean reversion rather than symmetry, and the cost-curve floor from Wood Mackenzie's analysis argues against the deepest historical tails. This is a deliberate judgment, and it should be marked as such: the report pays for its below-consensus P50 by shading both tails in from the naive historical envelope.

**Second, the forecaster-revision base rate.**

**Third, the treatment-charge regime base rate.** The historical base rate is that such gaps resolve when physical tonnage arrives; the current regime is an order-of-magnitude outlier.

**Fourth, the stock-and-positioning base rate.** The inventory configuration itself supplies a distributional discipline.

### Why Confidence Is Medium: The Documented Evidence Gaps

Overall confidence in the central forecast is medium, and three specific evidentiary weaknesses — not general caution — make it so.

The first is the sign instability of the balance forecasts themselves. A market whose most authoritative balance publisher moves its projection across zero and part-way back within twelve months cannot support a high-confidence fourteen-month point estimate anchored on that balance.

The second is the single-source and unconfirmed status of several load-bearing inputs. The grid-demand path that underpins the demand floor rests on figures flagged as unconfirmed on the cited page.

The third is the known-unknowns list that no evidence base can currently resolve: the scope and timing of the Panama negotiation; and the SRB's behavior at record prices, for which the only documented precedent is countercyclical release, not purchase. Each of these is a policy variable, decided by actors whose incentives Chapter 3 and Chapter 5 traced but whose decisions cannot be probabilized beyond the assignments already made.

### The Explicit Divergences — and What Would Close Them

The divergence with **Goldman** is a disagreement about squeeze persistence at full intensity. Goldman's own article title — "Why Record-High Copper Prices Aren't Forecast to Last" — concedes the transience of the record even while carrying an average above the year-end forward, an internal tension that itself signals the consensus is chasing spot. If instead the 2027 benchmark settles at or modestly below $0/t in November 2026 and TCs begin recovering by Q2, Goldman's average becomes untenable and the divergence closes in this report's direction. [S7]

The real disagreement with that cluster is about the second derivative, not the level: CRU's own documentation of the shift toward index-linked concentrate pricing [S40] is evidence that the annual benchmark system is losing its price-discovery function — a structural change that historically precedes regime transitions in physical premiums, and one that cuts toward faster TC normalization than the consensus carries.

### The Binary Forecast Ledger

Fourteen dated, verifiable forecasts, each with a probability and resolution criteria anchored to named sources:

| # | Binary forecast | Probability | Resolution criteria |
|---|---|---|---|
| 1 | — | 55% | LME cash settlement via Westmetall/LME on that date; |
| 2 | — | 84% | Same as #1 |
| 3 | — | 25% | LME cash settlement series |
| 4 | — | 65% | Settlement announcements reported by SMM/Fastmarkets/Reuters |
| 5 | — | 55% | SMM weekly index |
| 6 | — | 35% | SMM weekly index |
| 7 | — | 50% | ICSG semi-annual forecast release |
| 8 | — | 45% | Company disclosure or government announcement |
| 9 | — | 30% | First Quantum quarterly reports |
| — | — | — | LME daily stock report via Westmetall [S5] |
| — | — | — | COMEX warehouse data |
| — | — | — | Daily spread computed from CME and LME prices |
| — | — | — | Federal Register / congressional action [S67] |
| 14 [S6] | Kamoa-Kakula meets 2027 guidance of 500,000–540,000 t [S24] | 60% [S24] | Ivanhoe Mines quarterly and annual production reports [S24][S25] |

Binaries 4, 5, 6 and 7 jointly express the TC-regime family; 8 and 9 the Panama family; and 1, 2 and 3 the price distribution itself.

### The Standing Update Discipline

The final calibration statement is procedural. weekly SMM and Fastmarkets TC prints; First Quantum and Panama government disclosures [S33]; Ivanhoe, Teck, and Codelco quarterly guidance [S24][S27]; LME and COMEX stock reports; SRB and Project Vault tender notices; and the Federal Register through the Annex III sunset [S67].

## Decision Implications: Hedging, Procurement, and Monitoring Playbook for 2027

This chapter converts that distribution into decisions.

### For Consumers and Fabricators: Layer Hedges on Dips, Engineer Substitution Above $15,000/t

The case for layered hedging rests on a simple asymmetry in the scenario tree.

The practical implication is to layer rather than time.

The substitution trigger deserves more precision than the usual "high prices cause substitution" framing.

if the market is right and the squeeze persists, the consumer has locked coverage below the prevailing price.

### For Miners: Delay Hedge Ratios, Price the First Quantum Option

For producing miners, the forecast distribution argues for patience.

First Quantum's position is the clearest case of restart-optionality value. For First Quantum, the option value of the restart compounds with the price skew: if the restart is agreed and copper is simultaneously in the squeeze regime, the revenue combination is the highest-value cell in the entire matrix.

### For Traders: Position Around Dated Catalysts, Not Narratives

A benchmark at or below $0, or a decisive move to index-linked terms, strengthens the squeeze scenario; a positive benchmark above $0 would be the first hard evidence of concentrate-market loosening and would shift probability mass toward normalization.

Two branches matter. Position sizing into that window should assume elevated slippage regardless of directional view.

### The Monitoring Dashboard: A Defined Update Cadence

The forecast should be revised on evidence, on a schedule, not on headlines. Each indicator below maps to the scenario it strengthens.

| Indicator | Cadence / Source | Strengthens | Key threshold |
|---|---|---|---|
| SMM imported concentrate index / Fastmarkets spot TC | Weekly [S20] | recovery above −$100: Normalization [S20] | — |
| LME + COMEX stocks, months of cover | Monthly, LME/Westmetall/COMEX [S5] | — | — |
| COMEX–LME spread | Continuous | — | Spread re-widening |
| — | — | Extended discipline: Squeeze | — |
| — | April 2027 [S14] | — | — |
| Cobre Panama milestones | Event-driven, Panama government/First Quantum [S33] | — | — |
| Company guidance: Ivanhoe, Teck, Codelco | Quarterly [S24][S27] | — | Guidance cuts: Squeeze |
| SRB / Project Vault tenders | Event-driven | — | Auctions/releases: Demand recession |
| US Commerce/USTR tariff actions | Event-driven | New Section 232 additions: Supercycle [S46] | — |
| — | Continuous [S22][S23] | Equity stress + contracting China demand: Demand recession | — |

The cadence discipline matters because the market's own anchors move. If by mid-2027 the dashboard's squeeze indicators (TCs, stocks, CSPT policy) are all confirming while consensus forecasts have not converged upward, the divergence itself becomes a tradable signal: the market, like the ICSG, revises in large steps rather than continuously, and positioning ahead of those steps — at Asia Copper Week, at the April ICSG release, and into the Annex III sunset — is where the forecast's edge is realized. [S16]

The final discipline is humility about the known unknowns: the unconfirmed Cobre Panama scale, the Teck guidance cut not reconciled on filings, and the single-source grid-demand figures all carry evidentiary caveats documented in earlier chapters. Decision frameworks built on this forecast should therefore prefer structures with defined maximum loss — options, collars, tranched programs — over outright positions, in proportion to how much of the probability distribution rests on data that a single quarter's company reports or government announcements could move by hundreds of thousands of tonnes.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/copper-2027-r2/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[40%] Squeeze persists / elevated regime**: LME cash settlement on 2027-12-31 (or PCOPPUSDM monthly value for 2027-12, next FRED release) is between $13,000/t and $18,000/t inclusive; ties to the inclusive/exclusive boundaries of the adjacent scenarios.
- **[29%] Supply catches up / normalization**: LME cash settlement on 2027-12-31 (or PCOPPUSDM monthly value for 2027-12) is >= $11,000/t and < $13,000/t.
- **[12%] Supercycle breakout**: LME cash settlement on 2027-12-31 (or PCOPPUSDM monthly value for 2027-12) exceeds $18,000/t.
- **[15%] Demand recession / hard landing**: LME cash settlement on 2027-12-31 (or PCOPPUSDM monthly value for 2027-12) is below $11,000/t.
- **[3%] Other / Status Quo**: At 2027-12-31, classify this residual bin if none of the named scenarios' complete resolution criteria are met, or if the outcome remains a mixed/status-quo path.

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Global price of Copper (fred:PCOPPUSDM) | next monthly release after 2026-09 | — |
| S&P 500 — United States (fred:SP500) | next monthly release after 2026-09 | — |
| CBOE Volatility Index: VIX — United States (fred:VIXCLS) | next monthly release after 2026-09 | — |

<!-- drf-news-market-context:83d221fb2b308d4016813bed377b9b371336e0d560f5e8c99870b33eeb41ec47:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:83d221fb2b308d4016813bed377b9b371336e0d560f5e8c99870b33eeb41ec47:end -->

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
| Scenarios (multiclass) | 8 | 0 | 8 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 25 | 0 | 25 | — |
| Unanchored binaries | 91 | 0 | 91 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S2] Global price of Copper — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/PCOPPUSDM](https://fred.stlouisfed.org/series/PCOPPUSDM)
2. [S22] S&P 500 — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/SP500](https://fred.stlouisfed.org/series/SP500)
3. [S23] CBOE Volatility Index: VIX — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/VIXCLS](https://fred.stlouisfed.org/series/VIXCLS)
4. [S6] Refined copper surplus forecast, but copper mines struggle to keep up - The Oregon Group — theoregongroup.com — [https://theoregongroup.com/latest-news/coppers-104000-tonne-surplus-masks-continued-mine-supply-constraint/](https://theoregongroup.com/latest-news/coppers-104000-tonne-surplus-masks-continued-mine-supply-constraint/)
5. [S64] Copper TC/RC Benchmark 2026: $0 Settlement, Negative Spot TCs — baresyndicate.com — [https://baresyndicate.com/blog/asia-copper-week-2026-tcrc-benchmark](https://baresyndicate.com/blog/asia-copper-week-2026-tcrc-benchmark)
6. [S21] Chinese Smelters Pay Miners for Copper Concentrate as Mine Supply Becomes the Key Constraint - Article | Crux Investor — cruxinvestor.com — [https://www.cruxinvestor.com/posts/chinese-smelters-pay-miners-for-copper-concentrate-as-mine-supply-becomes-the-key-constraint](https://www.cruxinvestor.com/posts/chinese-smelters-pay-miners-for-copper-concentrate-as-mine-supply-becomes-the-key-constraint)
7. [S4] Tariff Arbitrage Collapse Strands US Copper, Lifting Ex-US Pricing - Article | Crux Investor — cruxinvestor.com — [https://www.cruxinvestor.com/posts/tariff-arbitrage-collapse-strands-us-copper-lifting-ex-us-pricing](https://www.cruxinvestor.com/posts/tariff-arbitrage-collapse-strands-us-copper-lifting-ex-us-pricing)
8. [S5] westmetall. market data. prices/lme stocks. copper, tin, lead, zinc, aluminium, nickel, gold, fine silver — westmetall.com — [https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash](https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash)
9. [S34] Peru's Copper Push Arrives Too Late for a 530,000-Tonne Concentrate... — cruxinvestor.com — [https://www.cruxinvestor.com/posts/perus-copper-push-arrives-too-late-for-a-530-000-tonne-concentrate-deficit](https://www.cruxinvestor.com/posts/perus-copper-push-arrives-too-late-for-a-530-000-tonne-concentrate-deficit)
10. [S32] Ecuador to approve Mirador copper mine expansion by August — official — mining.com — [https://www.mining.com/ecuador-to-approve-mirador-copper-mine-expansion-by-august-official/](https://www.mining.com/ecuador-to-approve-mirador-copper-mine-expansion-by-august-official/)
11. [S20] Copper Concentrate TCs Break Through Negative Triple Digits: What Challenges Do Smelters Face? - Shanghai Metals Market (SMM) — news.metal.com — [https://news.metal.com/newscontent/103909269-copper-concentrate-tcs-break-through-negative-triple-digits-what-challenges-do-smelters-face](https://news.metal.com/newscontent/103909269-copper-concentrate-tcs-break-through-negative-triple-digits-what-challenges-do-smelters-face)
12. [S7] Copper TC/RC at $0: which number should a producer's book carry for 2027? | Novaex Blog — novaex.ai — [https://novaex.ai/blog/copper-tcrc-at-0-which-number-should-a-producers-book-carry-for-2027/](https://novaex.ai/blog/copper-tcrc-at-0-which-number-should-a-producers-book-carry-for-2027/)
13. [S8] China's refined copper output on track for lowest growth in decades this year, analysts say | Reuters — reuters.com — [https://www.reuters.com/world/asia-pacific/chinas-refined-copper-output-track-lowest-growth-decades-this-year-analysts-say-2026-09-28/](https://www.reuters.com/world/asia-pacific/chinas-refined-copper-output-track-lowest-growth-decades-this-year-analysts-say-2026-09-28/)
14. [S38] ICSG forecasts secondary copper output boost - Recycling Today — recyclingtoday.com — [https://www.recyclingtoday.com/news/copper-icsg-recycling-output-refining-supply-demand-2026-2027/](https://www.recyclingtoday.com/news/copper-icsg-recycling-output-refining-supply-demand-2026-2027/)
15. [S62] Copper Price Forecast 2026, 2027 and 2030 - Markets.com — markets.com — [https://www.markets.com/analysis/copper-price-forecast](https://www.markets.com/analysis/copper-price-forecast)
16. [S33] Panama panel recommends First Quantum mine restart to fund phased closure | Reuters — reuters.com — [https://www.reuters.com/business/panama-commission-recommends-reopening-first-quantum-mine-order-gradually-close-2026-09-30/](https://www.reuters.com/business/panama-commission-recommends-reopening-first-quantum-mine-order-gradually-close-2026-09-30/)
17. [S24] Ivanhoe Mines Announces Kamoa-Kakula Copper Production Guidance for 2026 and 2027 as Recovery Plan Advances – Ivanhoe Mines — ivanhoemines.com — [https://www.ivanhoemines.com/news-stories/news-release/ivanhoe-mines-announces-kamoa-kakula-copper-production-guidance-for-2026-and-2027-as-recovery-plan-advances/](https://www.ivanhoemines.com/news-stories/news-release/ivanhoe-mines-announces-kamoa-kakula-copper-production-guidance-for-2026-and-2027-as-recovery-plan-advances/)
18. [S16] Copper Market Forecast 2026/2027 | Policy Commons — policycommons.net — [https://policycommons.net/artifacts/59829045/copper-market-forecast-20262027/60727111/](https://policycommons.net/artifacts/59829045/copper-market-forecast-20262027/60727111/)
19. [S43] Copper in the Age of AI: Challenges of Electrification | S&P Global — spglobal.com — [https://www.spglobal.com/en/research-insights/special-reports/copper-in-the-age-of-ai](https://www.spglobal.com/en/research-insights/special-reports/copper-in-the-age-of-ai)
20. [S44] Copper demand slows in traditional sectors, driven by emerging sectors... — linkedin.com — [https://www.linkedin.com/posts/kit-yu-27753534_copper-demandseesa-slowdown-in-aggregate-activity-7424704971398623232-ifcR](https://www.linkedin.com/posts/kit-yu-27753534_copper-demandseesa-slowdown-in-aggregate-activity-7424704971398623232-ifcR)
21. [S53] Copper to Jump 50% in a Year on US & China Stockpiling, says Deutsche... — cruxinvestor.com — [https://www.cruxinvestor.com/posts/copper-to-jump-50-in-a-year-on-us-china-stockpiling-says-deutsche-bank](https://www.cruxinvestor.com/posts/copper-to-jump-50-in-a-year-on-us-china-stockpiling-says-deutsche-bank)
22. [S13] [SMM Analysis] The U.S. Copper Tariff Trade Is Fading — but It Isn't Over Yet — news.metal.com — [https://news.metal.com/newscontent/104139507-smm-analysis-the-us-copper-tariff-trade-is-fading-but-it-isnt-over-yet](https://news.metal.com/newscontent/104139507-smm-analysis-the-us-copper-tariff-trade-is-fading-but-it-isnt-over-yet)
23. [S14] ICSG sees global refined copper surplus widening in 2027 — miningweekly.com — [https://www.miningweekly.com/article/icsg-sees-global-refined-copper-surplus-widening-in-2027-2026-10-15](https://www.miningweekly.com/article/icsg-sees-global-refined-copper-surplus-widening-in-2027-2026-10-15)
24. [S55] What's driving metal markets prices for copper, steel and aluminum in 2026? — jpmorgan.com — [https://www.jpmorgan.com/insights/global-research/commodities/aluminum-steel-copper-prices](https://www.jpmorgan.com/insights/global-research/commodities/aluminum-steel-copper-prices)
25. [S47] Copper between shortage and stockpiling | DWS — dws.com — [https://www.dws.com/en-us/insights/cio-view/charts-of-the-week/2026/copper-between-shortage-and-stockpiling/](https://www.dws.com/en-us/insights/cio-view/charts-of-the-week/2026/copper-between-shortage-and-stockpiling/)
26. [S28] Chile's Cochilco Raises 2026 Copper Price Forecast — industrialinfo.com — [https://www.industrialinfo.com/news/article/chiles-cochilco-raises-2026-copper-price-forecast--361453](https://www.industrialinfo.com/news/article/chiles-cochilco-raises-2026-copper-price-forecast--361453)
27. [S29] Chile Cuts Copper Production Forecast for 2026 Amid Mine Woes — linkedin.com — [https://www.linkedin.com/posts/thomasschmidt1_chile-cuts-copper-production-forecast-again-activity-7493209500980625408-6WRJ](https://www.linkedin.com/posts/thomasschmidt1_chile-cuts-copper-production-forecast-again-activity-7493209500980625408-6WRJ)
28. [S19] Freeport copper concentrate contracts 2026: LME Week - Fastmarkets — fastmarkets.com — [https://www.fastmarkets.com/insights/freeport-copper-concentrate-contracts-2026-floor-cap/](https://www.fastmarkets.com/insights/freeport-copper-concentrate-contracts-2026-floor-cap/)
29. [S46] President Trump Makes Major Changes to Section 232 Tariffs on Aluminum, Steel, and Copper | SmarTrade — thompsonhinesmartrade.com — [https://www.thompsonhinesmartrade.com/2026/04/president-trump-makes-major-changes-to-section-232-tariffs-on-aluminum-steel-and-copper/](https://www.thompsonhinesmartrade.com/2026/04/president-trump-makes-major-changes-to-section-232-tariffs-on-aluminum-steel-and-copper/)
30. [S67] Adjusting Imports of Copper Into the United States - Federal Register — federalregister.gov — [https://www.federalregister.gov/documents/2025/08/05/2025-14893/adjusting-imports-of-copper-into-the-united-states](https://www.federalregister.gov/documents/2025/08/05/2025-14893/adjusting-imports-of-copper-into-the-united-states)
31. [S40] Copper concentrates index pricing shifts further - CRU Group — crugroup.com — [https://www.crugroup.com/en/communities/thought-leadership/2026/Mid-year-settlements-signal-a-further-shift-towards-copper-concentrates-index-pricing/](https://www.crugroup.com/en/communities/thought-leadership/2026/Mid-year-settlements-signal-a-further-shift-towards-copper-concentrates-index-pricing/)
32. [S25] Ivanhoe Mines Reports 76,401 Tonnes of Copper Produced by... — newsfilecorp.com — [https://www.newsfilecorp.com/release/318074/Ivanhoe-Mines-Reports-76401-Tonnes-of-Copper-Produced-by-KamoaKakula-for-Q3-2026](https://www.newsfilecorp.com/release/318074/Ivanhoe-Mines-Reports-76401-Tonnes-of-Copper-Produced-by-KamoaKakula-for-Q3-2026)
33. [S27] Teck Resources cuts copper production guidance at flagship Chilean mine QB | Reuters — reuters.com — [https://www.reuters.com/business/teck-resources-cuts-copper-production-guidance-flagship-chilean-mine-qb-2025-10-08/](https://www.reuters.com/business/teck-resources-cuts-copper-production-guidance-flagship-chilean-mine-qb-2025-10-08/)
