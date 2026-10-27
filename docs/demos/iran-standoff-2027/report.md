# Iran Conflict and Nuclear Standoff Through End-2027: Scenario Probabilities, Priced Market Paths, and Macro Consequences

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/iran-standoff-2027/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging. The official-data base rate is the share of past moves over the same number of periods, applied to the latest complete observation, that meet the threshold (an outside view, not a forecast).

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme | Official-data base rate |
|---|---|---|---|---|---|
| F1 | US or Israeli forces carry out large-scale direct strikes on Iranian nuclear, military, or regime targets on or after 2026-11-04 and before 2027-12-31. | 27% | Resolves YES if Reuters or AP report US or Israeli strikes on Iranian territory (nuclear, military, or leadership targets) occurring on or after 2026-11-04 and before 2027-12-31. | post-midterm-strike-window | — |
| F2 | A signed US-Iran negotiated nuclear framework including IAEA access restoration and partial sanctions relief is in force on 2027-12-31. | 9% | Resolves YES if a signed US-Iran agreement text including IAEA access restoration to declared enrichment sites (IAEA inspections resumed, per IAEA statement) and partial sanctions relief is in force on 2027-12-31. | nuclear-diplomacy | — |
| F3 | A signed US-Iran ceasefire agreement with the blockade lifted but no IAEA access restoration is in force on 2027-12-31. | 22% | Resolves YES if a signed US-Iran ceasefire agreement (text published or jointly announced by both governments) is in force on 2027-12-31, with blockade lifted (Iranian crude loadings >1.0 mb/d per tanker-tracking reporting) AND no IAEA access restoration to declared sites. | blockade-attrition-settlement | — |
| F4 | A regime crisis involving forced removal, death, or substantive power transfer of Iran's sitting Supreme Leader or president, open IRGC factional conflict, or a materially disruptive Hormuz closure attempt occurs by 2027-12-31. | 8% | Resolves YES if by 2027-12-31 credible reporting (Reuters/AP/major outlets) documents forced removal, death, or substantive power transfer of the sitting Supreme Leader or president, OR open IRGC factional conflict with contested control of Tehran, OR a Hormuz closure attempt materially disrupting traffic. | succession-tail-risk | — |
| F5 | Managed low-intensity attrition with no US or Israeli strikes on Iranian territory continues from 2026-11-01 through 2027-12-31 with no signed US-Iran agreement in force at end-2027. | 35% | Resolves YES if no US or Israeli strikes on Iranian territory are reported by Reuters/AP between 2026-11-01 and 2027-12-31 AND no signed US-Iran agreement is in force on 2027-12-31 AND Brent (imf:PCPS/G001.POILBRE.USD.M) 2027-12 observation is between 70 and 110 USD/bbl. | managed-attrition-status-quo | — |
| F6 | Brent Crude, US dollars per barrel, Unit prices — World (imf:PCPS/G001.POILBRE.USD.M) is at least 110 U.S. dollars per barrel in December 2027. | 35% | Resolves YES if imf:PCPS/G001.POILBRE.USD.M >= 110 U.S. dollars per barrel in 2027-12 (source: IMF). | war-premium-oil | — |
| F7 | The US CPI year-over-year rate (fred:CPIAUCSL#yoy) is below 3% in December 2027. | 30% | Resolves YES if fred:CPIAUCSL#yoy < 3 Percent in 2027-12 (source: FRED). | inflation-pass-through | — |
| F8 | Central bank policy rates - Euro area - Monthly - End of period (bis:WS_CBPOL/M.XM) are at least 2.5% per cent per year in December 2027. | 65% | Resolves YES if bis:WS_CBPOL/M.XM >= 2.5 per cent per year in 2027-12 (source: BIS). Official resolution: bis:WS_CBPOL/M.XM >= 2.5% for 2027-12. | ecb-energy-shock-response | 79% (n=104, h=15) |
| F9 | The ICE BofA US High Yield Index Option-Adjusted Spread (fred:BAMLH0A0HYM2) is above 4.035 percent in December 2027. | 25% | Resolves YES if fred:BAMLH0A0HYM2 > 4.035 percent in 2027-12 (source: FRED). Official resolution: fred:BAMLH0A0HYM2 > 4.035% for 2027-12. | credit-stress | — |
| F10 | Gold, US dollars per troy ounce of gold, Unit prices — World (imf:PCPS/G001.PGOLD.USD.M) is below 4000 U.S. dollars per troy ounce in December 2027. | 30% | Resolves YES if imf:PCPS/G001.PGOLD.USD.M < 4000 U.S. dollars per troy ounce in 2027-12 (source: IMF). | safe-haven-deflation | — |
| F11 | The Global price of Natural gas, EU — Euro area (fred:PNGASEUUSDM) is below 17.67 U.S. Dollars per Million Metric British Thermal Unit in December 2027. | 35% | Resolves YES if fred:PNGASEUUSDM < 17.67 U.S. Dollars per Million Metric British Thermal Unit in 2027-12 (source: FRED). | gas-war-premium | — |
| F12 | Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) is at least 3.875% per cent per year in December 2027. | 60% | Resolves YES if bis:WS_CBPOL/M.US >= 3.875 per cent per year in 2027-12 (source: BIS). Official resolution: bis:WS_CBPOL/M.US >= 3.875% for 2027-12. | fed-restrictive-stance | 57% (n=104, h=15) |
| F13 | Real Exports of Goods and Services — United States (fred:EXPGSC1) is below 2600 Billions of Chained 2017 Dollars in 2027-Q4. | 15% | Resolves YES if fred:EXPGSC1 < 2600 Billions of Chained 2017 Dollars in 2027-Q4 (source: FRED). Official resolution: fred:EXPGSC1 < 2600 Billions of Chained 2017 Dollars for 2027-Q4. | trade-contraction-tail | 9% (n=32, h=6) |
| F14 | IAEA access to Iran's declared enrichment sites is restored by 2027-12-31. | 9% | Resolves YES if the IAEA publicly confirms resumed inspections at declared enrichment sites on or before 2027-12-31. | verification-blackout | — |
| F15 | Iranian crude loadings exceed 1.0 mb/d per tanker-tracking reporting on 2027-12-31. | 30% | Resolves YES if Vortexa/Kpler tanker-tracking reporting shows Iranian crude loadings above 1.0 million barrels per day in December 2027. | blockade-erosion | — |

_15 forecasts; 10 high-conviction (≥70% or ≤30%); 13 with objective criteria._
<!-- binary-forecast-block:end -->

---

## Key official indicators

_Stored official observations behind this report, exactly as published (never re-fetched)._

| Indicator | Units | Latest observed | Period | Year-over-year change | Five-year range | Publisher value (status) | Source |
|---|---|---|---|---|---|---|---|
| Brent Crude, US dollars per barrel, Unit prices — World | U.S. dollars per barrel | 102.0181 | 2026-09 | +34.409 (+50.894%) | 61.8109 to 117.6927 | — | [S5] |
| Central bank policy rates - United States - Monthly - End of period | Per cent per year | 3.875% | 2026-09 | -0.25 pp | 0.125% to 5.375% | — | [S8] |
| Central bank policy rates - Euro area - Monthly - End of period | Per cent per year | 2.5% | 2026-09 | +0.5 pp | 0% to 4.5% | — | [S28] |
| All index, Commodity price index, Index, 2016=100 — World | Index 2016=100 | 222.4285 | 2026-09 | +54.9641 (+32.821%) | 154.056 to 241.935 | — | [S29] |
| Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma — World | Dollars per Barrel | 97.3081 | 2026-09 | +33.349 (+52.141%) | 57.9723 to 114.84 | 99.97 (2026-10, partial-period value) | [S18] |
| Real Exports of Goods and Services — United States | Billions of Chained 2017 Dollars | 2814.538 | 2026-Q2 | +155.218 (+5.837%) | 2269.97 to 2814.538 | — | [S30] |
| Effective exchange rates: Euro area - Real - Broad (64 economies) | Index, 2020 = 100 | 103.27 | 2026-09 | -1.32 (-1.262%) | 95.33 to 104.59 | — | [S31] |
| Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) | Percent change from year ago | 3.717% | 2026-09 | +0.695 pp | 2.325% to 8.979% | — | [S6] |
| ICE BofA US High Yield Index Option-Adjusted Spread | Percent | 2.755% | 2026-09 | -0.033 pp | 2.696% to 4.035% | 3.186% (2026-10, partial-period value) | [S32] |
| Gold, US dollars per troy ounce of gold, Unit prices — World | U.S. dollars per troy ounce | 4334.7467 | 2026-09 | — | 4075.0968 to 5014.645 | — | [S10] |
| Consumer prices: Euro area - Year-on-year changes, in per cent | Per cent, year-on-year change | 3.249% | 2026-08 | — | 1.676% to 3.249% | — | [S33] |
| Real imports of goods and services — United States | Billions of Chained 2017 Dollars | 3913.833 | 2026-Q2 | +202.793 (+5.465%) | 3164.889 to 4025.786 | — | [S34] |
| Harmonized Index of Consumer Prices: Total for Euro Area (19 Countries) (year-over-year % change) | Percent change from year ago | 3.75% | 2026-09 | +1.534 pp | 1.636% to 10.621% | — | [S35] |
| Global price of Natural gas, EU — Euro area | U.S. Dollars per Million Metric British Thermal Unit | 25.494 | 2026-09 | +14.491 (+131.7%) | 8.0982 to 69.9772 | — | [S9] |
| Crude Oil Prices: Brent - Europe — World | Dollars per Barrel | 114.1591 | 2026-09 | — | 91.076 to 114.1591 | 124.9636 (2026-10, partial-period value) | [S36] |

<!-- viz:charts/official_indicators.html -->
![Official Indicators](demos/iran-standoff-2027/charts/official_indicators.png)

*Official Indicators*

*Source: [International Monetary Fund (IMF)](<https://data.imf.org/en/datasets/IMF.RES:PCPS>) [S5]; U.S. dollars per barrel; Monthly; adjustment unknown · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8]; Per cent per year; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/EXPGSC1>) [S30]; Billions of Chained 2017 Dollars; Quarterly; SAAR · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.XM>) [S28]; Per cent per year; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/BAMLH0A0HYM2>) [S32]; Percent; Monthly; NSA · [International Monetary Fund (IMF)](<https://data.imf.org/en/datasets/IMF.RES:PCPS>) [S29]; Index 2016=100; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DCOILWTICO>) [S18]; Dollars per Barrel; Monthly; NSA · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.XM>) [S31]; Index, 2020 = 100; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CPIAUCSL>) [S6]; Percent change from year ago; Monthly; SA · [International Monetary Fund (IMF)](<https://data.imf.org/en/datasets/IMF.RES:PCPS>) [S10]; U.S. dollars per troy ounce; Monthly; adjustment unknown · [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CPI/BIS,WS_LONG_CPI,1.0/M.XM.771>) [S33]; Per cent, year-on-year change; Monthly; adjustment unknown · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/IMPGSC1>) [S34]; Billions of Chained 2017 Dollars; Quarterly; SAAR*

<!-- viz:charts/official_indicators_more.html -->
![Official Indicators](demos/iran-standoff-2027/charts/official_indicators_more.png)

*Official Indicators*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/CP0000EZ19M086NEST>) [S35]; Percent change from year ago; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/PNGASEUUSDM>) [S9]; U.S. Dollars per Million Metric British Thermal Unit; Monthly; NSA · [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/DCOILBRENTEU>) [S36]; Dollars per Barrel; Monthly; NSA*

<!-- viz:charts/official_series_eaeoofrpnafnqllo.html -->
![Official Series History and Forecast Thresholds](demos/iran-standoff-2027/charts/official_series_eaeoofrpnafnqllo.png)

*Official Series History and Forecast Thresholds*

*Source: [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8]; Per cent per year; Monthly; adjustment unknown*

<!-- viz:charts/official_series_abrccrffefdqappe.html -->
![Official Series History and Forecast Thresholds](demos/iran-standoff-2027/charts/official_series_abrccrffefdqappe.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/EXPGSC1>) [S30]; Billions of Chained 2017 Dollars; Quarterly; SAAR*

<!-- viz:charts/official_series_fntloftlrpoffkpr.html -->
![Official Series History and Forecast Thresholds](demos/iran-standoff-2027/charts/official_series_fntloftlrpoffkpr.png)

*Official Series History and Forecast Thresholds*

*Source: [Bank for International Settlements (BIS)](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.XM>) [S28]; Per cent per year; Monthly; adjustment unknown*

<!-- viz:charts/official_series_dpbtaoetcpkqalon.html -->
![Official Series History and Forecast Thresholds](demos/iran-standoff-2027/charts/official_series_dpbtaoetcpkqalon.png)

*Official Series History and Forecast Thresholds*

*Source: [FRED (Federal Reserve Bank of St. Louis)](<https://fred.stlouisfed.org/series/BAMLH0A0HYM2>) [S32]; Percent; Monthly; NSA*

<!-- viz:charts/official_series_oeabckponlrdocmq.html -->
![Official Series History and Forecast Thresholds](demos/iran-standoff-2027/charts/official_series_oeabckponlrdocmq.png)

*Official Series History and Forecast Thresholds*

*Source: [International Monetary Fund (IMF)](<https://data.imf.org/en/datasets/IMF.RES:PCPS>) [S5]; U.S. dollars per barrel; Monthly; adjustment unknown*

## Part 2 — Framework & Synthesis

### Framework: One Question, Five Answers

The probability map is the verdict; the market calls are its arithmetic. This chapter defends those weights and traces the causal logic that connects them to the Part-1 binary probabilities and the central market calls.

The framework is deliberately structured as an outside-view-first exercise. Base rates for renewed state-on-state fighting after Middle East ceasefires, strike-recurrence patterns in the Israel–Iran shadow war, and the historical relationship between war premiums and realized supply loss anchor the prior; the extraordinary specifics of late 2026 — collapsed IAEA verification, a naval blockade that has driven Iranian exports to zero, and drafted post-midterm strike plans — shift the weights from there. [S19] The direction of adjustment is explicit throughout.

### The Baseline: A War of Attrition in Numbers

The starting line is peculiar.

The nuclear baseline is opaque by design. The IAEA has had no access to declared enrichment sites since January 2026. [S89] All are estimates, not measurements. Breakout-time visibility is effectively gone in both directions: neither the Agency nor outside analysts can confirm whether Iran is rebuilding cascades, and Tehran cannot prove it is not.

The market baseline embeds the war. September Brent averaged 102.02 $/b on the IMF series [S5]; EU natural gas stands at 25.49 $/MMBtu, up 131.7% year-on-year [S9];

### The Causal Spine

The forecast rests on four causal propositions.

**First, verification collapse is the dominant escalation driver.** With no IAEA access, Israeli and US red lines cannot be monitored, and ambiguity cuts toward action.

**Second, the blockade substitutes for bombing.**

**Third, oil-market structure is historically fragile.** In five Middle East shock episodes since 2006, only those with sustained realized supply loss kept Brent more than $10/b above pre-shock levels for six months. [S47] The market is already pricing the loss of ~4.8 million b/d of Iranian supply;

**Fourth, the principals' incentives diverge.** Netanyahu's doctrine is regime change; Trump's is cheap suppression without an oil shock; Mojtaba Khamenei's IRGC-aligned coalition needs blockade relief without visible nuclear concession; the reformist presidency needs a channel.

### Defending the Weights

The modal path. Attrition is working for the US at acceptable cost: Gulf exports exceeded pre-war levels for part of September [S47], and Trump has repeatedly cancelled major-combat plans. Historical base rates for ceasefire-without-settlement persisting at this intensity support continuation as the single most likely state.

The fat right tail. The New York Times reports specific US-Israeli plans for a "short but intensive operation" after the November 3 midterms; whether Trump blocked a mid-October Israeli strike is disputed, which is itself evidence of live planning.

Economic exhaustion is real: floating storage will exhaust, the contraction compounds, and Iran's reported offer — Hormuz reopening within seven days for blockade relief — shows a price exists at which Tehran trades. A signed ceasefire with blockade lift but no IAEA restoration is the most reachable text because it requires neither side to concede the nuclear question.

Requires a signed text including restored IAEA access and partial sanctions relief. Deadlocked talks, an IRGC-heavy Tehran, and Netanyahu's rejection of deals that legitimize Iran's program make this a modest weight, despite Chinese interest in mediation.

A World Bank-grade contraction can break a regime as easily as bend it, and Bessent's "economic collapse in months" warning is contested by Tehran precisely because it matters. But no visible challenger coalition exists inside Iran, and decapitation has already been tested — the February 28 killing of Khamenei produced succession within a week, not upheaval. [S69] Eight percent is a tail, not a scenario; note it splits into sub-paths with opposite market signs, which is why its pricing contributes less variance than its label suggests.

### Pricing the States

Gold stays bid in the 4,000s on continued central-bank accumulation and inflation hedging. US CPI grinds toward the mid-3s; TTF stays near current elevated levels given Red Sea risk and continued Gulf infrastructure vulnerability; tanker rates normalize gradually from record highs [S54]. defense spending keeps rising across the Gulf and Europe.

Headline CPI adds 0.5–1.5 pp; the Fed faces a stagflationary hold-or-hike dilemma; High-yield OAS widens toward 4%+; [S32] GCC equities and credit sell off on Hormuz tail fear despite intact export capacity.

Gold gives back war premium toward the high-3,000s, cushioned by structural central-bank demand. HY OAS tightens; GCC and Israeli markets rally.

The largest single-day downside moves of any state.

A negotiated-successor path prices like the framework; a violent succession or decapitation strike with IRGC retaliation prices like strikes-plus-Hormuz. Net market expectation contribution is small but the variance is the largest in the map.

### Market Anchors

Prediction-market pricing on renewed strikes and ceasefire timing was treated as one calibrated forecaster among many, not an authority: it carries real information about near-term political events but systematically underweights structural oil-market tightness and multi-quarter nuclear-reconstruction dynamics.

### Confidence and Honest Limits

Overall confidence is **low**, for three reasons. The November 3 midterms are a genuine regime-change point for US policy within the forecast window. And the market structure that makes any state's pricing extreme (zero spare capacity, drawn inventories) also makes the distribution fat: small probability shifts produce large price differences. The Part-1 binaries are the resolution of that uncertainty into verifiable claims; the probabilities above are the defended spine.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Executive Forecast: The End-2027 Probability Map and Central Market Calls

<!-- viz:charts/quantitative_claims.html -->
![Comparable Forecast Benchmarks](demos/iran-standoff-2027/charts/quantitative_claims.png)

*Comparable Forecast Benchmarks*

The probability map is the verdict, and the market calls are its arithmetic. This chapter states both up front, then defends the weighting, traces the most-likely trajectory from the October 2026 baseline through the November 3 midterms into 2027, and explains why overall confidence is deliberately low — because the two variables that dominate the distribution, nuclear-breakout progress inside a verification blackout and US political decisions inside an election cycle, are precisely the two no observer can currently measure. [S25]

### The Verdict: The Five-State Probability Map

| State | Probability | One-line resolution logic |
|---|---|---|
| Managed low-intensity attrition | — | Blockade, sabotage, cyber and proxy attacks continue; no new US/Israeli campaign of direct strikes on Iranian territory; no signed agreement in force |
| Renewed large-scale strikes | — | — |
| Durable ceasefire, no nuclear diplomacy | — | — |
| Negotiated nuclear framework | — | Signed agreement including resumed IAEA inspections at declared enrichment sites (per an IAEA statement) and partial sanctions relief |
| Regime crisis / other | — | — |

First, the machinery exists: The New York Times reported on October 21, 2026 that the US and Israeli militaries hold specific plans for a "short but intensive operation" after the November 3 midterms, with the un-attacked Pickaxe Mountain complex among candidate targets and Trump steering target selection away from oil infrastructure. [S80] Second, the trigger is invisible: since January 2026 the IAEA has had no access to any declared Iranian enrichment facility and can verify neither stockpiles nor centrifuge status, making red-line breaches undetectable in advance. [S13] Netanyahu's stated doctrine that "there's only one way to remove this threat once and for all — overthrow the regime in Iran" adds a demand-side bias toward execution that no prior shadow-war episode carried.

and Trump's October 12 temporary lifting of sanctions on Russian diesel — while Washington weighed letting "legal oil" move on previously sanctioned shadow-fleet vessels — shows an administration actively working to cap the oil market's war premium rather than feed it. [S40]

Every 2025–2026 attempt through that door has failed — the April 2026 Pakistan-mediated window lapsed, the June 2026 Versailles MOU collapsed and formally expired in August — and the Qatar channel remains deadlocked over sequencing, with Iran offering to reopen Hormuz within seven days under its own control for a blockade lift and released assets, while Washington demands concessions first. no visible challenger coalition exists in the evidence.

### The Most-Likely Trajectory: From the Midterms to December 2027

The modal path runs through four dated gates.

The midterms are the explicit calendar for the drafted strike operation, and Iranian officials are reported to be prolonging the talk stalemate deliberately to influence the outcome. A result read as a repudiation of the war suppresses execution and locks in attrition; a hawk-favorable result reopens the strike question within weeks. This is the highest-leverage single day in the forecast horizon.

A third cancellation does not kill the tail;

Exhaustion of that buffer intensifies Tehran's squeeze toward either a signed ceasefire or — the darker branch — internal rupture. Watch Kpler/Vortexa loadings: a rebound above 0.5–1 mb/d signals blockade erosion inside the attrition state; sustained zero signals the economic trigger maturing.

**Gate four: IAEA Board meetings throughout.** Because verification is dark, the Board calendar is a sequence of binary windows. A Board finding of verified cascade reinstallation at Isfahan hands Netanyahu the justification Washington has so far withheld, migrating probability mass toward strikes; an implemented — not merely urged — resolution pointing toward access restoration would be the earliest institutional signpost of the framework state.

### The Central Market Calls: Probability-Weighted, With Intervals

The central forecasts are composites across the five states, each state carrying its own priced path (developed in Chapters 4–7 and assembled in the master table):

- The arithmetic: 0.35×95 + 0.27×125 + 0.22×82 + 0.09×74 + 0.08×100.
- Every state except the negotiated framework leaves gold above pre-war trend because the central-bank diversification floor is state-independent.

Third, 4.8 mb/d of conflict shut-ins remain shut in, and their return requires either Iranian capitulation or US political reversal, neither in evidence. The EIA's path is not wrong;

The disagreement with the official forecasts is a probability disagreement about politics, not an elasticity disagreement about barrels.

### Why Confidence Is Low — and What Would Change the Map

Overall confidence in this distribution is low, for three reasons that are properties of the situation rather than of the analysis.

First, the nuclear clock is unobservable.

Second, US political volatility is extreme within the forecast window itself. A distribution that depends on one man's sequencing of electoral incentives across fourteen months deserves wide intervals regardless of how legible the incentives are.

Every threshold in this report is therefore anchored to a named series rather than to "Brent" or "Hormuz" generically, and every central call should be read as the middle of a distribution whose width is itself the forecast.

The map updates on dated, verifiable signposts rather than on narrative: a Reuters/AP strike report after November 4 (strikes state confirmed); a third Trump cancellation (attrition reinforced); a jointly announced text via Qatar (ceasefire weight up sharply); an IAEA statement on resumed inspections (framework weight up); an open rupture in the Assembly of Experts (regime-crisis tail lifted); Kpler-counted Iranian arrivals sustained above 1 mb/d (blockade erosion);

Sources: [S3][S5][S8][S9][S10][S11][S13][S14][S15][S16][S17][S22][S23][S24][S28][S36][S39][S40][S45][S47][S50][S57][S59][S99][S100]

These are middles of wide distributions;

strike plans have been drafted, cancelled, and redrafted within a single month [S24]. Markets price the fast variable.

Sources: [S5][S10][S22][S23][S24][S36][S47][S57][S99][S100]

## Baseline as of Late October 2026: The War of Attrition in Numbers

This chapter fixes that baseline in numbers—conflict, nuclear, sanctions, and market—because every scenario priced later in this report is a deviation from it, and because several of the baseline's own numbers are contested in ways that matter for calibration.

### The Conflict Baseline: Two Strike Campaigns, One Dead Supreme Leader, One Blockade

The war's current phase is the product of a compressed and violent sequence. On February 28, 2026, US strikes designated "Operation Epic Fury" killed Supreme Leader Ali Khamenei and dozens of senior leaders, hitting IRGC, Basij and regime-security targets. [S69] Within about a week, the Assembly of Experts installed his son Mojtaba Khamenei as Supreme Leader, a figure with deep IRGC ties [S17]. A negotiated off-ramp followed and then failed: the June 2026 Memorandum of Understanding—signed at Versailles with Macron present, endorsed by the new Supreme Leader as the basis for direct talks—collapsed within weeks and formally expired in August. [S84]

The blockade has accomplished what a decade of sanctions could not. Treasury Secretary Bessent has warned Iran "could face economic collapse in months" [S3].

The nuclear file has effectively gone dark.

The proxy layer is degraded but active. Hezbollah, meanwhile, is rebuilding its arsenal and deterrent capability while nominally inside the Lebanon ceasefire framework; The direction of that contest—Hezbollah reconstitution versus sustained LAF seizures—is one of the levers that determines whether low-intensity conflict stays low.

Two political clocks frame the near-term trajectory. Second, the post-midterm strike window: the New York Times reports specific drafted US-Israeli plans for a "short but intensive" operation after the elections, with the Pickaxe Mountain complex identified as a candidate target [S24]. Iran's negotiating posture is explicitly calibrated to the first clock—Reuters reports Iranian officials are prolonging the deadlocked Qatar-mediated talks past the midterms [S23]. Tehran's standing offer via Qatar is to reopen the Strait of Hormuz within seven days under Iranian control in exchange for a blockade lift, eased export limits, released frozen assets, and an end to hostilities; Washington insists on concessions first. The sequencing deadlock is the single most important diplomatic fact in the baseline.

### The Market Baseline: An Oil Price Carrying a War Premium With No Supply Cut Behind It

The market numbers must be quoted with their definitional caveats attached, because the two headline Brent figures diverge sharply. The IMF monthly-average series puts September 2026 Brent at 102.0181 $/b, 50.9% above a year earlier [S5]; the EIA/FRED monthly observation for the same month is 114.1591 $/b, with the latest daily print at 115.22 on October 20 [S36]. This report carries both explicitly rather than averaging them: the gap reflects source-and-definition differences, and any threshold set on "Brent" for resolution purposes must specify the series. WTI's September observation is 97.3081 $/b with a daily 107.89 on October 20 [S18].

What is remarkable is what the price does *not* contain. Gulf exports exceeded pre-war levels for part of September, even as tanker attacks increased [S47]. The price, in other words, is carrying a war-and-uncertainty premium on top of a *realized* 4.8 mb/d loss, with the market paying for the possibility that the next escalation closes Hormuz rather than for any current closure.

The structural buffer beneath that premium is historically thin. VLCC rates on the Gulf of Oman–China route hit a record WS776 in mid-October before easing [S54]. This combination—zero effective spare, a depleted inventory floor, and record tanker rates—is why subsequent chapters price small new shocks with large price responses.

The rest of the market complex confirms a broad energy-and-risk repricing. The IMF all-commodity index is at 222.4, up 32.8% year-on-year and at the 98th percentile of its five-year stored history [S29].

The macro policy picture is one of central banks moving in opposite directions into the same shock. US CPI is running at 3.717% year-on-year [S6]; Credit, notably, has barely flinched: US high-yield OAS is 2.755% for September, essentially unchanged from a year earlier, though the latest daily print of 3.27% on October 21 shows the spread beginning to reprice the post-midterm strike window [S32].

### Contested Numbers and Why They Matter

Three baseline disputes deserve explicit treatment because they change downstream probabilities.

**Iranian exports are not unambiguously zero.** Zero October loadings [S39] is a loading-side observation. The measurement points differ—loadings, blockade crossings, Chinese arrivals—and Treasury's claim to have "neutralized" the shadow fleet [S45] is an enforcement assertion, not an observation, when trackers show flows persisting. Chinese teapot refiners have meanwhile bought at least 12 million barrels of substitute Iraqi crude [S40].

**The remaining HEU stock is unverifiable.** All imagery-based estimates are made without IAEA access, and no verification mechanism exists to catch cascade reinstallation at Isfahan before it is operational.

**The economy-collapse claim is belligerent propaganda on at least one side.** The truth is probably worse than Tehran admits and less deterministic than Washington implies: rationing, exchange-rate repression, and IRGC control of scarce hard currency can stretch a collapse timeline considerably. The unresolved question is whether blockade attrition produces capitulation (supporting the durable-ceasefire scenario) or internal rupture (the regime-crisis tail)—the same pressure powers both.

That normalization requires both a conflict resolution *and* the supply build—conditions only the de-escalation states deliver, as Chapter 3 and 9 develop. This report's judgment, carried into all subsequent chapters, is that the baseline's structural tightness makes the EIA path contingent rather than central.

Everything that follows is a branch from this line.

## What the Official Indicators Say: Oil, Gold, Gas and Policy Rates Relative to History

The starting point for any disciplined forecast is what the official series actually show, measured against their own five-year distributions rather than against narrative.

### Oil and the Commodity Complex: Near the Top of the Range, But Not at It

The single most important nuance in the oil data is that Brent is high but not at its five-year peak — and the gap between the two is informative. The IMF monthly series shows Brent averaging 102.0181 $/b in September 2026, up 34.409 $/b (+50.894%) from 67.6091 $/b a year earlier. The EIA/FRED monthly observation for the same month is materially higher at 114.1591 $/b, with the latest daily print at 115.22 on October 20 [S36]. This report carries both explicitly rather than averaging: the IMF average reflects the full month while the EIA observation and the October daily prints capture the post-blockade-hardening repricing. The divergence itself is a signal — prices rose through September, meaning the market was re-pricing escalation risk in real time rather than settling.

Against the five-year window, the stored IMF series ranges from 61.8109 (December 2025) to 117.6927 (June 2022) [S5]. That unconditioned distribution is the correct outside-view anchor — but it is drawn from a history in which most months carried no active US blockade of a major producer.

The broad commodity index confirms this is a complex-wide repricing, not an oil idiosyncrasy. When a broad index is at its 98th percentile while oil is at its 77th, the war's transmission into food, fertilizers, metals and freight is running ahead of the oil price alone — an important input for the inflation pass-through chapter that follows.

### Gas and Gold: The Series Already in Extreme Territory

If oil is elevated, gas and gold are at extremes. EU natural gas at 25.494 $/MMBtu in September is 131.7% above the 11.003 $/MMBtu level of September 2025 — more than double year-on-year, a move proportionally larger than oil's. The five-year range runs from 8.0982 (February 2024) to 69.9772 (August 2022) [S9], so the current level sits in the upper part of the band but far below the 2022 crisis peak. Gas at double its year-ago level with HICP already above target is the specific channel through which a strikes scenario forces an ECB reaction rather than a Fed-only one.

Gold presents the sharpest historical break. Two features of this series shape the gold forecasts in later chapters. it has already been touched once.

### Inflation and Policy Rates: Hiking into a Shock

Both inflation measures are above target and rising, and — critically for the macro chapters — the two central banks are responding in opposite directions. US CPI at 3.717% year-on-year for September is up 0.695 percentage points from a year earlier and stands at the 75th percentile of its 118-month window [S6];

The policy divergence is the structural fact of the baseline.

The credit market, in other words, is where the least war is currently discounted, making it the series with the most room to move in the strikes scenario.

### Against the Official Projections: Why $74 Brent Is a Conditional, Not a Baseline

The most consequential analytical choice in this report is how to treat the official normalization projections.

The steelman for the official view deserves to be stated fairly: the market has already demonstrated remarkable supply resilience. Middle East exports exceeded pre-war levels for part of September [S47]; the Saudi-led 2.1 mb/d ramp has replaced most conflict-barrel losses; Historical base rates also favor normalization: by this report's calculation from the stored history, of five distinct Middle-East shock episodes since 2006, only the two with sustained realized supply loss kept Brent more than $10/b above pre-shock levels for six months or longer. If the blockade ends and Iranian barrels return, the same retracement logic applies with force.

This report's counterargument rests on three stored facts the official projections must overcome. there is no second Saudi ramp available for any new outage. Third, 4.8 mb/d of conflict shut-ins remain shut in, and the mechanism for their return requires either Iranian capitulation or US political reversal, neither of which is in evidence.

### Observable Thresholds: What Confirms or Falsifies Each Scenario

The official series define the tripwires. Each is verifiable against a named source and dated:

- market sign depends on the successor faction, which is why this state has bimodal price implications.

Two cross-cutting indicators warrant standing watch. if the October IMF average prints near or above the EIA monthly observation, it confirms the escalation repricing consolidated rather than reversed.

## Scenario Deep-Dive I: Managed Low-Intensity Attrition Persists (35%)

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/iran-standoff-2027/charts/scenario_probabilities.png)

*Scenario Probabilities*

**Scenario definition and resolution.** This chapter prices the modal path: through December 31, 2027, the United States and Israel conduct no new campaign of direct strikes on Iranian territory, no signed US-Iran agreement enters into force, and the conflict continues as what the Congressional Research Service already calls a "war of attrition" — blockade enforcement, sabotage, cyber operations, proxy attacks, and the limited strike exchanges both sides have been trading since the June 2026 memorandum collapsed. [S67] Any verified strike after November 4 falsifies the scenario; a collapse of the blockade that restores Iranian loadings above roughly 1 million b/d without a signed text moves the outcome into the durable-ceasefire state.

### Why attrition is the modal path: three mutually reinforcing locks

The status quo persists not because anyone prefers it but because each major actor is trapped by a different constraint, and the traps point in the same direction — neither escalation nor settlement.

**The American lock is electoral and monetary.** Trump's own incentive structure reinforces restraint: his price-stability preoccupation is visible in policy, not just rhetoric — on October 12, 2026 he temporarily lifted sanctions on Russian diesel while Washington weighed letting "legal oil" move on previously sanctioned shadow-fleet vessels, an active attempt to cap the oil market's war premium. He has, on the research record, repeatedly canceled plans for a return to major combat. The post-midterm "short but intensive operation" drafted with Israel [S24] is real, but drafted-and-canceled is the established pattern, and Trump has steered the planners away from oil infrastructure targets precisely because he understands the price consequence of hitting them.

**The Iranian lock is sequencing.** Tehran's October offer via Qatari mediators — reopen the Strait of Hormuz within seven days under Iranian control in exchange for a blockade lift, eased export limits and released assets — is not a bridge to settlement; it is a relief-first demand the United States will not accept, and Iranian officials are reported to be prolonging the deadlock deliberately to influence the November 3 midterms. That stalling tactic reveals a strategy: wait out American politics rather than concede nuclear verification. Critically, the IRGC-heavy ruling coalition around Mojtaba Khamenei retains coercion as its only real instrument, and the surviving diplomatic faction carries the US channel without the authority to close a deal. A regime that cannot concede and cannot escalate at scale defaults to endurance.

**The structural lock is the oil market itself.** This cuts both ways, and the direction matters for pricing: it makes any new outage explosively bullish (Chapter 5's fat tail), but it also gives every actor with exposure to oil revenue — Saudi Arabia, the Gulf states, the United States consumer, China's importers — a shared stake in preventing one. Under attrition, these hands stay on the market's tiller.

### The priced path: Brent's slow bleed from $115 to the high-$80s

Under this scenario the war premium decays without ever fully clearing, because the supply that would clear it — Iranian barrels — stays off the water.

The mechanics of the drift downward are threefold. Second, IMF price history shows oil spikes decaying by at least half within three to six months absent sustained supply loss — the June 2025 premium unwound within roughly ten trading days of the June 24 ceasefire — and attrition, by definition, produces no new sustained loss; [S16]

But the floor is equally structural. every dip toward $80 attracts Chinese strategic and teapot buying — teapots have already substituted at least 12 million barrels of Iraqi crude for October-November delivery as Iranian flows fell [S40], a demand pool that returns to any discount.

Tankers normalize unevenly. VLCC Gulf-China rates peaked at a record WS776 and were already falling from record highs by October 16; [S7]

### Gold, gas and the macro hand-off

**Gold keeps a floor, not a bid.**

**Gas eases but stays historically expensive.** EU gas at $25.494/MMBtu is up 131.7% year-on-year [S9].

**The Fed and ECB both get to stop.** The inflation arithmetic is the scenario's most benign feature: a flat-to-falling oil path with gas easing means the CPI pass-through that drove the September 16 hike fades mechanically through 2027. [S7]

### Steelman and the falsification ledger

The strongest objection to this chapter is that it confuses delay with stability. The post-midterm strike plans are specific, jointly drafted, and gated on an election that may remove Trump's restraint incentive entirely [S24]; Netanyahu has stated that "there's only one way to remove this threat once and for all — overthrow the regime in Iran"; and since January 2026 the IAEA has had no access to any declared enrichment facility, so centrifuge reinstallation at Isfahan proceeds invisibly until an intelligence leak or a Netanyahu red-line declaration converts undetectable progress into an ultimatum. [S13] The rebuttal is not that the objection is wrong — it is that the countdown has no observable clock. Without IAEA verification, neither Washington nor Jerusalem can establish a breach date, and Trump has demonstrated that unverifiable urgency loses every time to verifiable gasoline prices.

Iranian loadings staying at or near zero [S39]; the EIA's easing oil-price path remaining broadly intact as the confirming market tell; and the Fed's projected hold-then-cut path materializing. Each of those belongs to the fatter tails priced in the chapters that follow.

## Scenario Deep-Dive II: Renewed Large-Scale Strikes (27%) — The Fat Right Tail

The previous chapter argued that managed attrition persists as the modal path. Resolution is definitional: Reuters or Associated Press reporting of such strikes on Iranian territory within that window settles the scenario, with CENTCOM releases and Congressional Research Service reporting serving as corroborating settling sources for tripwire events.

### Why the Strike Probability Is Elevated Above Every Base Rate

The core reason is that the machinery for a third campaign is already built and dated. On October 21, 2026, The New York Times reported that the US and Israeli militaries hold specific plans for a "short but intensive operation" of renewed strikes against Iran after the November 3 midterms, with Trump steering target selection away from oil infrastructure and the un-attacked Pickaxe Mountain nuclear complex south of Natanz — where ISIS imagery shows continuing tunnel construction — among the candidate targets. [S80] This is not generic escalation risk; it is drafted operational planning with an explicit electoral gate. Netanyahu's doctrine supplies the demand side: in his October 2026 campaign speech he named Iran's new supreme leader developing "the bombs of death" as the threat and argued the only way to remove it is to overthrow the regime in Iran — a regime-change objective that cannot be satisfied by blockade attrition and structurally biases Israeli planning toward strike options.

Two structural conditions make the red-line trigger far more hair-trigger than in any previous US-Iran episode. Iran formally replied in February 2026 that normal safeguards implementation was "legally untenable and materially impracticable" and refuses design-information verification at Isfahan. This means breakout progress — the very thing that would justify a strike in Jerusalem's or Washington's decision calculus — is invisible in advance, and both capitals must plan against worst-case imagery estimates rather than inspector findings. Second, warning time has been compressed on the Iranian side too: Iran's September 2026 preemption doctrine and reporting from late February 2026 indicating missile launch authority was pre-delegated to lower-ranking officers mean an Israeli or US strike could trigger a full-spectrum Iranian response faster than any political circuit can interrupt it, including "kill box" attacks on shipping in the Strait of Hormuz. [S41]

Reconstruction at Isfahan and Pickaxe Mountain proceeds under no inspection; any verified cascade reinstallation becomes, in effect, a self-announcing red-line breach.

Trump has repeatedly canceled drafted plans for a return to major combat, including a reported block of a mid-October 2026 Israeli strike that Netanyahu denies. [S26] Trump's price-stability incentive cuts the same way: October 2026 policy actions (temporarily lifting sanctions on Russian diesel on October 12 while weighing letting "legal oil" move on previously sanctioned shadow-fleet vessels) show an administration actively working to cap the oil market's war premium. The scenario weight therefore assumes the electoral gate opens, the target set is nuclear rather than economic, and at least one of the two principals executes — a conjunction that base rates discount but drafted plans and a verification blackout elevate.

### The Priced Path: Oil at $115–135, or $140–180 if Hormuz Breaks

The pricing asymmetry in this scenario is extreme because the market enters it with no buffer. Historical war-premium episodes calibrate the moves. the premium unwound within roughly ten trading days of the ceasefire, and IMF price history shows oil spikes decaying by at least half within three to six months absent sustained supply loss [S110].

This report's estimate for the two sub-cases is therefore as follows.

Gas and shipping transmit the shock asymmetrically. A Houthi attack sinking a tanker is itself a named escalation trigger toward this scenario, meaning the Red Sea front can be both cause and amplifier. Tanker rates, having touched record VLCC Gulf–China levels around WS776 before easing [S54], would re-test and exceed records as ton-miles balloon under simultaneous Hormuz risk premium and Red Sea rerouting.

### Gold, Credit and the Policy Trap

Gold is the cleanest expression of this scenario's tail. At $4,334.75/oz in September 2026 gold already sits near its 2026 extremes, having peaked at $5,014.65 in February during the war's most intense phase [S10]; Critically, the floor beneath gold in this scenario is structural: official-sector buying accelerates because sanctions immobilization risk is precisely what gold insures against, and October 2026's "oil up, dollar up, gold down" dynamic would invert once oil-driven inflation hedging compounds geopolitical demand. [S53] The dollar and Swiss franc rally alongside; euro-area real effective exchange rate weakness (already -1.3% y/y at 103.27) deepens as TTF-led energy costs hit European industry [S31].

The policy response is genuinely trapped, and this is where the scenario does its deepest macro damage. a hike into European stagnation becomes probable in the Hormuz sub-case.

Sources: [S1][S6][S9][S10][S11][S12][S13][S14][S15][S16][S24][S28][S31][S32][S35][S36][S40][S49][S50][S54][S57][S59][S60][S100][S104][S105][S108][S110][S113][S121]

Duration, not initial magnitude, is the discriminating variable across the five stored shock episodes: only conflicts with sustained realized supply loss kept Brent more than $10/b above pre-shock levels for six months or longer, and a blockade-plus-campaign configuration guarantees realized loss by construction — Iranian loadings are already at zero. [S47]

Two final calibration notes.

Sources: [S1][S24][S39][S47][S57][S99][S100]

## Scenario Deep-Dive III: Durable Ceasefire Without Nuclear Diplomacy (22%) and Negotiated Framework (9%)

The central argument is that both states run through the same narrow door: a signed text. The durable-ceasefire state needs a signed halt to hostilities without nuclear diplomacy; the framework state adds IAEA access restoration and partial sanctions relief.

### The Mechanism: How Blockade Attrition Manufactures a Ceasefire

Khamenei's stated negotiating goals — a blockade lift, eased export limits, and released frozen assets — are precisely the currency of a ceasefire, not of a nuclear framework.

Iran has already tabled the concrete shape of such a deal: via Qatari mediators, Tehran offered on September–October 2026 to reopen the Strait of Hormuz within seven days under Iranian control in exchange for a blockade lift, eased export limits, released frozen assets, and an end to hostilities. [S41] Note what is absent from this offer: any mention of IAEA access, enrichment caps, or stockpile disposition. That absence is the analytical basis for assigning the durable ceasefire more than twice the weight of the framework. Iran's bid is a pure de-escalation trade — shipping security for economic relief — which is exactly the durable-ceasefire state.

The sequencing dispute is the principal obstacle, and it is a real one: the US channel insists on concessions first, Tehran on relief first, and both sides are currently using the November 3 midterm calendar — Iranian officials are reported to be prolonging the stalemate deliberately to influence the US vote. But the structure of incentives tilts toward eventual Iranian movement, not US movement. Khamenei's economic problem is compounding. A durable ceasefire, on the precedent of the June 2025 Israel-Iran ceasefire that cut oil prices 6% on announcement [S110], is more likely to arrive as a mutual exhaustion artifact in mid-to-late 2027 than as a diplomatic breakthrough — the second Versailles-style text, minus the nuclear clock that killed the first one.

and no accompanying IAEA access restoration, which would reclassify the state as a framework. Falsification is straightforward — any US or Israeli strike on Iranian territory reported by Reuters/AP between November 4, 2026 and end-2027 moves the state to renewed large-scale strikes, and this is not a negligible risk given the reported post-midterm "short but intensive" planning. [S118]

### Pricing the Durable Ceasefire: Brent Toward the $80s, and the Supply Rebuild Problem

The oil path under a durable ceasefire is a race between premium decay and supply return, and the historical record on which force wins is unambiguous. IMF monthly Brent history shows oil spikes decaying by at least half within three to six months absent sustained supply loss;

The second leg is the supply return, and here the arithmetic is demanding.

it merely stops the bleeding. Chinese teapot refiners that substituted at least 12 million barrels of Iraqi crude for October–November delivery [S40] would rotate back to discounted Iranian barrels, displacing demand for other grades — a mild additional bearish force.

Tanker rates compress sharply: the record WS776 Gulf of Oman–China supertanker rates and the record highs preceding them [S54] embed both war-risk insurance and blockade-enforcement rerouting premia, both of which a signed ceasefire deflates. Hormuz product flows recovering above roughly 2 million bpd, against roughly 3.6 million pre-war, is the normalizing marker for LPG cracks per Vortexa data.

a ceasefire removes most of the first component and much of the second, while the third persists under continuing sanctions.

Macro transmission under this state is the disinflation case. GCC credit tightens modestly (the Saudi 5Y CDS anchor near 67.75 bps is already the tight end of historical regional risk), GCC equities face mixed oil-revenue math — lower prices, higher volumes through unblocked Hormuz — and Israeli assets extend the post-de-escalation rally pattern observed after the March 2026 strikes. [S58]

### The Negotiated Framework (9%): Why a Signed Nuclear Text Is an Order Harder

The framework state requires strictly more than the ceasefire: a signed US-Iran agreement text including IAEA access restoration to declared enrichment sites — verified by resumed inspections per an IAEA statement — plus partial sanctions relief.

First, the verification deadlock is not a technicality but the core of the dispute. The IAEA has had no access to declared enrichment sites since January 2026; [S89] Iran formally replied in February 2026 that normal safeguards implementation was "legally untenable and materially impracticable" and refuses design-information and inventory verification at Isfahan, citing "illegal military attacks." [S16] A framework requires Tehran to trade that chip; a ceasefire does not.

Second, the mediation supply is thin. Qatar carries the channel but is deadlocked on sequencing. Russia likewise benefits from the US tied down. No great-power sponsor currently profits from a signed framework, which historically has been a near-necessary condition for one.

Third, the Israeli veto. Netanyahu's stated doctrine — "there's only one way to remove this threat once and for all — overthrow the regime in Iran" — makes any text that legitimizes enrichment an existential political threat to him, and the US-Israeli planning record [S24] shows strike options being drafted, not settlement annexes.

Priced as full normalization, the framework state is the most disinflationary of the five. Iranian barrels return through a partially rebuilt logistics chain plus sanctioned-vessel reflagging (Washington was already weighing letting "legal oil" move on previously sanctioned shadow-fleet vessels in mid-October — evidence that the supply-side relief playbook exists).

### Steelman: The Case That Both Weights Are Too Low

The strongest objection to this chapter's probabilities comes from the exhaustion arithmetic. The 2026 precedent cuts both ways: Iran did sign the June MOU and reopened the Hormuz calculus once before, showing the regime will sign under pressure. [S21]

The rebuttal rests on three legs. First, every previous 2025–2026 de-escalation collapsed — the April window lapsed, the June MOU expired — demonstrating that both Washington and Tehran currently prefer the attrition equilibrium to each available deal, and revealed preference dominates projection. [S21] Second, the IRGC's cohesion: the Guard survived decapitation, replaced killed officials, and its coercive apparatus remains intact, with its leverage (Hormuz "kill box" attacks, pre-delegated missile authority) worth more intact than traded away. Third, the framework state specifically requires verification concessions that the Isfahan stockpile ambiguity makes maximally painful.

The signposts that would move these numbers are dated and verifiable: a jointly announced text via Qatar (ceasefire weight up sharply); an IAEA statement on resumed inspections at declared sites (framework weight up); a third Trump cancellation of strike plans after November 3 (ceasefire weight up modestly); conversely, any CENTCOM/IDF strike on Pickaxe Mountain or the Isfahan tunnels moves the probability mass to the fat right tail and prices this chapter's central paths off the table.

## Scenario Deep-Dive IV: Regime Crisis and Tail Events (8%)

It is the only state whose internal composition splits into two sub-paths with *opposite* market signs—one resembling a negotiated framework in its price implications, the other exceeding even the renewed-strikes scenario in violence.

### The Institutional Channel: How a Succession Crisis Would Actually Happen

The mechanics of the regime-crisis path run through a body that has already exercised its succession function once this cycle. The Assembly of Experts installed Mojtaba Khamenei as supreme leader within days of his father's killing in the February 28, 2026 opening strikes. [S69] It did not fracture.

The vulnerability is different now. The legitimacy deficit does not produce crisis by itself; it means any second shock lands on a leader with thinner institutional roots than his father built over three decades. Congressional Research Service reporting on the conflict identifies the succession machinery's cohesion as a live variable for this tail —an open rupture in the Assembly of Experts is the specific observable that would lift it.

The economic pressure behind the scenario is quantified on both sides. October crude loadings have fallen to zero under the blockade [S39]. The question for this scenario is whether that pressure produces *concession* (feeding the durable-ceasefire state) or *rupture* (feeding this one). Notably, the same World Bank contraction projection is cited elsewhere in this report as raising the probability of the durable-ceasefire scenario—the economic-collapse channel points toward settlement more strongly than toward upheaval. CRS sees no imminent collapse of the Iranian regime while keeping the possibility open, which is precisely the calibration that supports a high-single-digit rather than double-digit weight.

Leadership illness rumors, protest waves, or cabinet purges do not resolve this state.

### Why 8%: Discounting the Transition-Contest Distribution

Assessments published at the vacuum moment typically scored three branches: IRGC consolidation around collective leadership with a clerical figurehead as the modal outcome, a protracted elite power contest next, and a popular uprising seizing the vacuum as the minority branch. Read naively, two of those three branches look like this scenario, implying a substantial probability of post-succession upheaval.

This report rejects that reading, on three evidence-grounded grounds. First, the modal branch—IRGC consolidation with a figurehead—is arguably what *actually happened*: a leader with deep IRGC ties and thin clerical credentials was installed atop an IRGC-centred coalition. The consolidation branch resolved; the contest branch did not. Second, the IRGC coercive apparatus has proven *cohesive* after the decapitation strikes—it replaced killed officials and survived rather than fragmenting, which explicitly lowers the assessed probability of this scenario. Third, the diplomatic faction survived and still carries the US channel through Qatari mediators; the intra-elite contest is being waged inside institutions, not against them.

The first is a successful decapitation strike: Netanyahu's declared doctrine of regime change in Iran is a matter of record, and reported post-midterm planning includes a "short but intensive operation" against regime and nuclear targets [S24]. The second is an economic-collapse-driven rupture, if the "months" timeline US officials warn of proves right and Iranian denial wrong. The third is a bottom-up challenge exceeding regime coercive capacity—an uprising branch that did not materialize at the vacuum moment, when coercive cohesion was at its lowest. Each alone is low-single-digit; What remains here is the portion of upheaval risk not embedded in an announced campaign.

### Sub-Path One: Orderly Soft-Liner Succession (roughly 3 points of the 8%)

The bearish branch. Crisis produces a leadership change *toward* the negotiating faction—either because the Assembly displaces Mojtaba in favor of a consensus cleric backed by the surviving presidency, or because a post-Mojtaba collective leadership concludes the war is unwinnable and seeks terms. Iran's standing negotiating position is already on the table: via Qatari mediators it offered to reopen Hormuz within seven days under its control in exchange for a blockade lift, eased export limits, released frozen assets, and an end to hostilities. A leadership change that empowers the faction carrying that channel converts the offer from bargaining posture into settlement.

Gold unwinds from the September 2026 IMF monthly average of $4,334.75/oz [S10], but war-premium dissolution meets structural central-bank buying: the asset-freeze demonstration against the IRGC reinforced official-sector gold diversification, making a collapse below the July 2026 trough of $4,075.10/oz [S10] unlikely even here. EU gas normalizes from the September 2026 average of $25.494/MMBtu [S9] toward pre-war ranges as Hormuz product flows rebuild.

### Sub-Path Two: Chaotic IRGC Takeover with Hormuz Escalation (roughly 4 points of the 8%)

The fat tail inside the fat tail. Crisis means the IRGC seizes full power during upheaval and executes the escalation doctrine already in place. A crisis that decapitates normal command-and-control makes *involuntary* escalation more likely precisely because launch authority no longer requires Tehran's consent.

The market structure makes this branch uniquely dangerous. Conflict shut-ins already reached 4.8 million b/d this cycle. These interventions cap premiums in an attrition regime; against a sustained Hormuz closure they are days of cover, not months.

The hardest element to price is duration. gold spikes above the February 2026 record of $5,014.65/oz [S10] before settling; the high-yield spread blows through its five-year ceiling of 4.035% [S32];

Because every actor's incentive cuts against it. Trump has steered planners away from oil infrastructure targets and repeatedly cancelled major-combat plans [S24]; And the IRGC itself presumably understands that a Hormuz campaign invites the regime-ending war it has so far survived. The tail exists because pre-delegated launch authority and command fragmentation make *accidental or local* execution possible, not because any principal rationally chooses it.

### Regional, Haven, and Falsification Implications

Regional market implications are the most asymmetric of any scenario. Sub-path two hits GCC credit hardest—Gulf export infrastructure is the target set—and pipeline workarounds now routing a substantially larger share of Gulf crude around the Strait than before the war provide only partial protection;

The watch-list that would force this chapter's probabilities upward is short and dated. An open rupture in the Assembly of Experts—factional statements, competing announcements, cancelled sessions—is the leading indicator. Verified post-November 4 strikes on leadership targets would shift probability in from the renewed-strikes state.

## Key Actors and Decision Nodes: Who Determines Which Scenario Materializes

It is the product of a small number of identifiable actors whose incentives are documented, whose options are known, and whose decision calendar is dated. This chapter maps who actually holds the levers, what each lever does to the scenario distribution, and when the decision points fall. The core argument: the single most powerful individual is Donald Trump, but the single most powerful *structural* force is the exhaustion of the oil market's buffers, which converts every actor's modest move into a large price event.

### Trump: The Blockade Ladder, the Price Ceiling, and the Strike Cancellation Pattern

Trump sits at the center of the distribution because he controls all three escalation instruments simultaneously: the naval blockade, the strike plans, and the sanctions-relief valve.

Trump's revealed behavior pattern is cancellation. The New York Times reporting on post-midterm strike planning notes the drafted "short but intensive operation" [S24], and separate reporting indicates Trump blocked a mid-October Israeli strike — a block Netanyahu denies [S24]. Trump has now cancelled major-combat plans repeatedly while keeping the blockade tight. This pattern is why this report weights attrition above strikes even though specific strike plans exist on paper: the plans are real, but so is the demonstrated reluctance to execute them.

The binding constraint on Trump is the oil price. His core incentive is containment without an oil-price shock — Reuters reported the administration weighing easing sanctions on the *global* shadow fleet specifically to stabilize prices [S50]. Every $10 of additional war premium works against the strike option; [S118] every month of blockade attrition works against Iran's ability to refuse a deal. The post-midterm "strike window" [S24] is real but conditional: it opens only if Trump concludes the blockade has stopped yielding returns.

### Netanyahu and the IDF: The Regime-Change Doctrine Against the American Leash

The IDF's operational logic rewards striking before Iran reconstitutes: every month of reconstruction at Isfahan shrinks the military advantage window.

But the IDF cannot execute a campaign-scale operation without American enablers — refueling, ISR, and the blockade screen that CENTCOM provides [S2]. The mid-October episode — an Israeli strike reportedly blocked by Washington and denied by Netanyahu — captures the dynamic exactly: Netanyahu probes the leash, Trump jerks it, and the market cannot verify which account is true.

Iranian retaliation doctrine compresses this timeline from the other side. Iran's September 2026 preemption doctrine, with launch authority pre-delegated to lower-ranking officers, means an Israeli strike may trigger a missile response Tehran's leadership cannot fully throttle — which is itself an argument Netanyahu's critics inside Israel's security establishment use against striking, and an argument Trump uses to block it. [S16]

### Tehran: Mojtaba Khamenei, the IRGC, and the Foreign Ministry Channel

The IRGC-heavy coalition benefits from blockade erosion and costly US overreach; the surviving reformist presidency carries the American channel through the Qatar mediation. Reuters reporting that Iran is deliberately prolonging the talk stalemate to influence the midterms [S23] shows the diplomatic faction's operating style: wait, probe, and assume American politics will deliver a better deal.

The sequencing deadlock is the specific mechanism blocking both de-escalation states. Iran offers relief-first (blockade lift, eased export caps, released assets, in exchange for Hormuz reopening under its own control within seven days); the US demands concessions-first. Neither side can accept the other's sequence without validating the other's narrative of victory. The Iranian government denies collapse is near, and the denial should be taken seriously: authoritarian regimes under sanctions routinely endure far longer than external models predict. The honest statement is that the internal IRGC-versus-diplomats balance is unobservable from outside, which is a principal reason this report's overall confidence is low.

A decapitation strike, an IRGC seizure of the diplomatic channel, or an economic-collapse-driven rupture in the coalition — any of these would flip Iran from a unitary (if factional) negotiator into an unstable succession contest, with the two sub-paths priced oppositely in Chapter 7. No visible challenger coalition exists today, which is why the weight is single-digit.

### The Enablers and Gatekeepers: CENTCOM, OPEC+, China, Russia, the IAEA

CENTCOM is the actor that makes attrition *work*. Its enforcement releases [S2] document the interdiction machinery that took exports to zero [S39]. Blockades fail politically before they fail militarily; the military failure mode — a Hormuz mining campaign or mass fast-boat attack — would be an Iranian escalation choice, not a US one.

OPEC+ has lost its role as shock absorber. Saudi Arabia's incentive — disruption premiums with volumes protected — aligns it with continued Gulf export throughput, making it a quiet de-escalation advocate with Qatar in the mediation chair.

China is the swing economic actor. The USCC timeline documents China's enabling role during and after the strikes [S98] — but China has not offered mediation. Its revealed preference is opportunism: buy discounted barrels when possible, substitute when not, and let the US bleed strategically. its absence to date justifies keeping that state's weight modest.

Russia's role is military-technical and sanctions-evasion enablement — limited transfers, supportive rhetoric, and strategic benefit from the US being tied down. Russia raises the cost of escalation to Washington without materially changing Iran's survival arithmetic.

The IAEA is the least powerful actor in absolute terms but the most important *gatekeeper*. This cuts both ways: Israel cannot prove Iran is rebuilding toward a weapon, and the US cannot verify Iran is not — meaning the strike decision must be made on imagery inference alone [S14], and any negotiated framework must *begin* with access restoration, which is why the IAEA-access criterion anchors the framework state's resolution definition. The IAEA Board meeting calendar is therefore a genuine decision node: a Board finding on Isfahan design information or verified cascade reinstallation could hand Netanyahu the justification Washington has so far withheld.

### The Dated Decision Calendar Through End-2027

The scenario distribution resolves through a sequence of dated nodes:

- **November 3, 2026 — US midterms.** [S25] The stated gate for the post-midterm strike window. An adverse result for hawks raises attrition probability; a favorable one reopens the strike question within weeks.
- Exhaustion, alongside zero loadings, is the ceasefire scenario's economic trigger; watch Iranian loadings rebounding above 0.5–1 mb/d as the falsification signal the other way.
- A verified reconstruction finding is the most probable non-political trigger of the strike state.

The actors' incentives are legible; their timing is not — which is the report's low-confidence caveat in institutional form.

## Oil-Market Structure: Why Small Shocks Now Price Like Large Ones

Together they mean the oil market has lost both of its shock absorbers simultaneously. In a normal market, a supply outage meets two defenses — spare capacity that can be ramped within weeks, and inventories that can be drawn for months. In this market, neither defense exists.

This chapter sets out the structural arithmetic behind those price calls.

### The Supply Hole and the Missing Shock Absorbers

Start with the size of the hole.

The critical word is "effective." The distinction matters for forecasting because markets price responses, not press releases. the only remaining buffers are demand destruction, strategic releases, and price.

That recovery is genuinely impressive — and it is precisely why no further ramp is available. The September surge was the release of the last stored production capability, not evidence of durable slack.

The inventory position is the second, and less appreciated, half of the structure. The market is being balanced by high prices destroying demand rather than by supply catching up.

Two policy actions in October 2026 confirm how tight policymakers themselves judge the market to be. [S57] On October 12, President Trump temporarily lifted sanctions on Russian diesel while Washington weighed letting "legal oil" move on previously sanctioned shadow-fleet vessels. [S104] These are not the actions of governments comfortable with supply conditions; they are ad hoc, product-focused interventions that cap the war premium at the margin without rebuilding any structural buffer. The IEA diesel release, in particular, is a signal: when the agency goes to strategic stocks for diesel rather than crude, the binding constraint has moved to refined product, where capacity cannot be surged the way crude can.

### How History Prices Shocks — And Why History Underprices Them Here

The historical record gives a reasonably clean taxonomy of how oil prices respond to Middle East supply shocks, and it divides sharply by whether the shock produced sustained realized supply loss or only risk. Within the stored IMF monthly Brent window (2006–2026), five distinct Middle East shock episodes can be identified, and only the two that involved sustained realized supply loss kept Brent more than $10/b above pre-shock levels for six months or longer. [S47] The general pattern in IMF Brent history is that oil spikes decay by at least half within three to six months absent sustained supply loss;

That record is exactly why the current structure is different. The decay half-life observed in 2006–2026 episodes assumed either spare capacity or inventories would eventually arbitrage the premium away. [S101] The "sustained realized supply loss" condition is already satisfied — 4.8 million b/d of conflict shut-ins are not a risk premium, they are a physical fact — so the historical episodes that argue for fast decay do not apply to the baseline state. What the historical record prices instead is the *marginal* shock on top of the baseline:

- These are the "risk on/risk off" bounds of a strike-and-ceasefire round with no realized supply loss, and they bracket the price action of the 2026 rounds' diplomatic phases as well. [S100]
- **Large-but-recoverable outages: the September 2019 Abqaiq attack.** [S104] The EIA's own retrospective analysis of the episode emphasizes that prices quickly retraced as Saudi recovery timelines firmed and inventories proved ample. That episode is the cleanest modern calibration of a large-but-recoverable outage, and it occurred in a market with ample spare capacity and healthy inventories, both of which are absent now.
- Crucially, even that episode eventually decayed once supply was physically restored;
- They are the only precedent in the window that combines an initial risk-premium move with a lasting physical deficit, which is why this report treats the post-strike 2026 price level (Brent monthly average $102.0181 in September 2026 [S5]; latest daily print $115.22 on October 20 [S36]) as predominantly structural rather than premium.

### Why the EIA's $74 Is a Scenario, Not a Baseline

Both projections share a common, explicit condition: Iranian and regional flows must substantially normalize.

That condition decomposes into two requirements that must both hold. First, the conflict must resolve sufficiently for Iranian barrels (and full Gulf logistics) to return — either through a durable ceasefire lifting the blockade or a negotiated framework with sanctions relief.

A steelman of the EIA view deserves attention: the agency could be right that markets are tighter than fundamentals because of an oversized fear premium, and that any credible de-escalation trigger produces an outsized unwind. The June 2025 precedent supports this — a 6% drop on a ceasefire announcement within a day [S110], and a full premium unwind in ten trading days. Today's elevated price is not a premium on top of a balanced market; it is the balanced price of a market that has already lost 4.8 million b/d and half a billion barrels of stocks. De-escalation announcements can remove the *marginal* risk premium quickly, but only physically returned barrels can remove the structural deficit — and barrels return on tanker schedules and blockade-lifting timelines measured in quarters, not days.

### Hormuz: Definitional Fog Around the Chokepoint

Any forecast of Hormuz disruption risk must first survive a measurement problem.

These are not contradictory so much as measuring different things — crude-only versus crude-plus-products, different averaging windows, different pre-war baselines — but the spread matters enormously for threshold-based monitoring. A "Hormuz below 10 million b/d" alarm trips immediately on the IEA definition and never trips on the JP Morgan one. [S41]

Two structural facts partially insulate the market from Hormuz tail risk, and honest pricing requires stating them. The chokepoint risk that would actually break the market in 2027 is thus narrower than the headline "Hormuz closure" framing suggests: it requires either a crude-transit collapse below the Kpler threshold, or a strike round that re-damages Gulf export infrastructure of the kind hit in March 2026, when Qatari LNG, a Saudi refinery and Israeli oil and gas fields went down. [S56] Trump's reported steering of post-midterm strike planning away from oil-infrastructure targets lowers, but does not eliminate, that channel — the IRGC's pre-delegated missile authority and "kill box" doctrine mean Iranian retaliation need not follow US target discipline.

### The Demand Side of the Deficit: China, Substitution and the Shadow Fleet

The demand side of the structural deficit has its own fragile plumbing.

The shadow fleet is the other piece of plumbing under active attack. What is not contested is the direction: each wave of designations raises the per-barrel logistics cost of moving Iranian crude, compressing the discount at which Iran can sell, and deepening the fiscal squeeze the blockade is designed to impose [S4][S39].

The freight market reflects all of this. Freight is now a transmission channel that amplifies any physical shock: with tonne-miles already stretched by rerouting, an outage that forces further rerouting hits an already-tight tanker market, adding several dollars per barrel of delivered cost on top of the crude price move itself.

### The Structural Verdict

Concretely:

it is a different weighting of the political conditions under which that supply arrives. In a market where small shocks price like large ones, the distribution of outcomes is dictated less by barrels than by the decisions of the actors mapped in Chapter 8 — and the structural arithmetic above is why those decisions carry the price leverage they do.

## Gas, Shipping, and the Broader Commodity Complex

But gas, shipping and the petrochemical chain are not simple oil derivatives here. Each has its own chokepoint: European gas is hostage to Qatari LNG infrastructure that has already been struck once; tanker rates are hostage to a Red Sea that has become a semi-closed corridor; and LPG and naphtha economics are hostage to Hormuz *product* flows, which have collapsed far more completely than crude flows.

### European Gas: The Qatari LNG Tail Is the Whole Story

The baseline is stark. EU gas stood at $25.494/MMBtu in September 2026, up 131.7% year-on-year [S9], against a five-year range whose upper bound ($69.98, August 2022) is a reminder that the demand-destruction threshold sits far above current levels but is reachable in a tail. The critical precedent is March 2, 2026, when strikes simultaneously hit Qatari LNG facilities, a Saudi refinery (Ras Tanura) and Israeli oil and gas fields; [S80] The lesson the market has internalized is that Gulf energy infrastructure is a strike target, and Qatar—the world's largest LNG exporter, shipping through Hormuz—is the single point of failure for European winter supply.

That makes the scenario dispersion wide and asymmetric:

- This is a slow normalization, not a collapse;
- Gas, not oil, is where a re-strike does the most unbuffered physical damage to Europe.

only the strikes-state tail approaches it.

### Shipping: Tanker Rates as the Conflict's Real-Time Barometer

Freight is the most information-dense market in this conflict because it reprices within hours of physical events. Two structural forces are pulling rates in opposite directions.

The first is ton-mile inflation from rerouting. twelve attacks on commercial vessels since resumption, including ballistic-missile strikes on the Saudi tankers Amzan, Encelia and Layl [S47].

the falsifier is a Houthi attack *sinking* a tanker in the southern Red Sea, which would move both insurance and the conflict state toward the strikes scenario.

The Iraqi datapoint deserves attention: Iraq arranged passage for its own tankers through the Hormuz region in August 2026 despite blockade conditions, and Chinese teapots substituted at least 12 million barrels of Iraqi crude for October–November delivery [S40]. This is the sanctions-era pattern reincarnated at state scale—officially documented workarounds that erode the blockade's marginal bite over time and, in the attrition state, gradually normalize freight without normalizing politics.

### LPG, Naphtha and Petrochemicals: The Product-Flow Collapse No One Hedged

The quiet casualty of this war is Hormuz *product* flow.

LPG is the sharpest expression. Iran was a major LPG exporter to Asian petrochemical feedstock buyers; per Vortexa-flow logic, a recovery of Hormuz product flows above 2 million b/d would normalize LPG cracks. Until then: under **attrition**, LPG and naphtha cracks stay wide, favoring US-sourced and Atlantic-basin LPG (which does not transit Hormuz) at a persistent premium and squeezing Asian mixed-feed crackers that relied on Iranian and Gulf product; Chinese PDH plants running on Middle Eastern LPG face the tightest margins.

The Chinese substitution chain is the demand-side ballast. Kpler tracks precisely this buffer, and its exhaustion would complete China's structural re-sourcing away from Iranian barrels regardless of how the conflict resolves. That re-sourcing is bullish freight ton-miles (longer hauls from the Atlantic) even in de-escalation states, which is why freight normalizes more slowly than prices in every scenario.

### The All-Commodity Index and the Inflation Transmission Gauge

The exceptions are energy-linked: EU gas at +131.7% [S9] and the commodity-freight complex. Under **de-escalation**, the index retraces toward the 170s, consistent with the IMF series' historical pattern of conflict premia decaying by at least half within three to six months absent sustained supply loss.

If the Iraqi-passage and teapot-substitution workarounds scale, gas and product markets could normalize *within* the attrition state, making TTF's path closer to the ceasefire band and LPG cracks self-correcting.

Hormuz product flows recovering above 2 mb/d, which would normalize LPG cracks; a Houthi attack sinking a commercial vessel in the southern Red Sea (escalation trigger); and a second consecutive monthly euro-area energy contribution above +1.71pp, which would mark second-round inflation effects and force ECB action into the gas tail.

## Macro Transmission: Inflation Pass-Through, the Fed, the ECB, and Global Growth

The macro transmission of the Iran conflict runs through a single dominant channel: the oil-and-gas price level set by the conflict state, which feeds headline inflation in the US and euro area with a lag of roughly one to three months, and which in turn constrains—or in the de-escalation states, frees—the Federal Reserve and the European Central Bank.

### The Pass-Through Arithmetic from Brent to CPI

The starting point matters less than the arithmetic of marginal moves.

This is the tripwire that would force the ECB from hold into hike despite weak growth.

Applying the arithmetic to the priced oil paths from Chapters 4–7:

- Research evidence is unambiguous on the policy consequence: the inflation pass-through from renewed large-scale strikes would keep the Fed and ECB restrictive.
- the orderly-succession sub-path is disinflationary, the chaotic IRGC-consolidation sub-path is the worst inflation print of all five states.

### The Fed: Hiking into the Shock, Then What?

Under renewed strikes, the Fed faces the 1970s trap: a supply-driven inflation surge against growth damage. Research evidence indicates the FOMC extends hikes in this state;

Under the de-escalation states the pivot is fast. the negotiated framework implies a similar or slightly deeper path. The regime-crisis state is bimodal: soft-liner succession is a cut environment; a Hormuz kill-box consolidation forces the strikes-state response in extreme form.

### The ECB: The Gas-Exposed Twin

The ECB's constraint set is different in kind.

The asymmetry deserves emphasis: the ECB's hiking response to the strikes state would come with the euro area closer to stagnation than the US, making any hike contingent on the TTF channel specifically rather than on oil alone. An oil-only spike with gas contained (strikes steered away from energy infrastructure, per the reported US planning) would more likely produce an ECB hold-and-suffer outcome than a hike.

### Global Growth, Trade and Credit

That demand destruction is the market's own recession signal—prices this high are already rationing.

GCC and Israeli markets take the direct hit, as research evidence notes—the inflation pass-through drags growth and hits GCC and Israeli markets. a strikes state pushes it toward and beyond the 4.035% five-year high, at which point the financial-conditions tightening does the Fed's work for it—the strongest argument for why the Fed might ultimately stop short of the full hikes implied. [S32]

The negotiated framework adds the investment and trade normalization on top.

## Regional Markets and Safe Havens: GCC Credit, Israeli Assets, Gold and the Dollar

The core of this chapter's argument is a divergence: Gulf credit is being carried by an export windfall that rests on volumes physically protected by the US blockade, while gold is being carried by a structural bid that persists even in scenarios where the war premium unwinds. The dollar sits between the two, caught in an "oil up, dollar up, gold down" dynamic that October 2026 commentary describes as linking oil and gold markets.

### The Windfall-Tail Tension in GCC Credit and Equities

The Gulf's starting position is deceptively strong. Around that same window, S&P Global Ratings is reported to have upgraded Saudi Arabia to 'A+', though the date was not confirmed on the fetched page. Two provisional data points, both unconfirmed at primary level, but both pointing the same direction: the market is not pricing acute Gulf sovereign risk despite an active war on Iran's side of the Gulf.

The mechanism is volume, not price. Middle East oil exports topped pre-war levels for part of September even as tanker attacks increased [S47], and Hormuz flows recovered toward pre-war figures in early October. Qatar's mediation role in the deadlocked US-Iran talks further embeds Doha in the de-escalation coalition rather than the crossfire.

A US-Israeli "short but intensive operation" is planned for the post-November 3 midterm window, and Iran's September 2026 preemption doctrine pre-delegates missile launch authority to lower-ranking officers, compressing warning times around the Strait. [S25] The inflation pass-through from renewed large-scale strikes would, as the scenario literature within this report's evidence base notes, drag growth and hit GCC and Israeli markets. The pricing implication under the five states:

- CDS likely stays tight (peace is good for risk), but equity leadership rotates away from pure oil exporters toward regional banks and diversification plays; Qatar benefits as mediator and LNG normalizer.
- An orderly soft-liner succession opening sanctions relief compresses spreads; a chaotic IRGC consolidation with sustained Hormuz attacks is the scenario in which Gulf credit ceases to trade like carry and starts trading like event risk.

### Israeli Assets: Pricing Deterrence, Not War

The counterintuitive precedent here is March 2, 2026: Israel's stocks and the shekel jumped after Israel and the US struck Iran. [S77] This is the pattern to extrapolate. Israeli markets in this conflict trade on perceived deterrence success and the degradation of the Iranian threat, not on the mere absence of war. Under managed attrition, with Hezbollah nominally inside the Lebanon ceasefire framework while reconstituting its deterrent, Israeli equities and the shekel hold a war-discount that has already been partially repaid; under renewed strikes that degrade Iran's reconstruction at Isfahan, the March 2026 rally template repeats — a sharp initial risk-on move in Tel Aviv as the market prices threat reduction, capped by retaliation risk against Israeli cities and the Ras Tanura-style infrastructure precedent. Under de-escalation states, Israeli assets perform on the peace dividend but underperform the euphoria case, because a nuclear framework that leaves any enrichment infrastructure intact cuts against Netanyahu's stated doctrine of overthrowing the regime and thus against the maximalist outcome Israeli equities have been pricing. The military fiscal channel matters throughout: sustained elevated defense expenditure is a real-economy drag the equity market discounts only slowly, and it is the channel through which European and Gulf defense procurement becomes a structural earnings story for the defense sector independent of the scenario mix.

### Gold: The Floor Beneath Every Scenario

Gold averaged $4,334.75 per ounce on the IMF monthly measure in September 2026 [S10], against a February 2026 peak of $5,014.645 [S10] and a July trough of $4,075.0968 [S10]. The war premium is best decomposed into three components, and their behavior under the five states differs critically:

1. **Geopolitical risk premium.** This is the scenario-sensitive component. Under renewed strikes it reprices toward and possibly through the February 2026 peak of $5,014.645 [S10];
2. **Oil-driven inflation hedging.**
3. **Structural central-bank buying.** The asset-freeze dimension of the conflict itself (Iran's frozen-asset demands in the Qatar-mediated talks [S23]) reinforces the diversification logic for any reserve manager watching a great power freeze an adversary's reserves.

The asymmetry is the key forecast: because components 2 and 3 decay slowly or not at all, the de-escalation states produce a plateau, not a collapse. The July 2026 trough of $4,075 [S10] is the best available marker for where gold settles when the acute war premium is gone but the structural bid remains.

### The Dollar and the Swiss Franc: An Unstable Haven Trade

This coupling is unstable. Under managed attrition it holds, and the dollar stays firm on rate differentials. Under de-escalation states the franc gives back gains as European energy relief restores euro sentiment, while the dollar softens with Fed cuts — leaving gold's structural bid as the only haven exposure that performs across all five states.

## Risks, Trend Signals, and Decision Implications Through 2027

The preceding chapters priced five end-states and their market consequences. The through-line is that this is a watch-list environment, not a forecast environment: the largest price moves of the next fourteen months will be triggered by discrete, verifiable signposts, not by trend extrapolation.

### The 2027 Watch-List: Signals That Move Probability Mass

The first family of signals is nuclear-detection. Any verified cascade reinstallation at Isfahan — observable through the same commercial-imagery methodology ISIS uses — would compress Israeli and US decision timelines, because with pre-delegated Iranian missile authority and a declared preemption doctrine, both sides operate with shortened warning. IAEA Board documents remain the official channel: a Board resolution that is *implemented* rather than merely urged would be the earliest institutional signpost of the negotiated-framework state, whereas a Board finding of undeclared activity would do the opposite.

The second family is the post-midterm strike window itself. A third cancellation would not kill the risk; The contested report that Trump blocked a mid-October Israeli strike, which Netanyahu denies, illustrates the deniability problem: markets will likely get the signal from strike execution, not from pre-strike diplomacy.

The third family is the blockade's physical ledger. The signposts cut both ways: loadings rebounding above 0.5–1 mb/d would signal blockade erosion and move mass toward the durable-ceasefire state;

The fourth family is the proxy ledger. Sustained LAF seizures pull toward durable ceasefire; verified Hezbollah reconstitution or a strike north of the Litani pulls toward escalation. Houthi operations against southern Red Sea shipping, which surged war-risk insurance costs in July [S49], define the freight channel: renewed attacks re-price the Red Sea rerouting premium independently of the Hormuz question.

The fifth family is China. No such mediation has occurred; its absence is priced in.

### Decision Implications

**For policymakers**, the binding constraint is that traditional buffers are spent. The implication is uncomfortable: with the strategic buffer partially drawn and producer spare exhausted, reserve posture is a one-shot tool. Governments should sequence its use against the highest-probability trigger windows (the post-midterm strike decision, IAEA Board findings) rather than against price levels, and prepare product-specific releases — the diesel action targeted Hormuz product tightness directly. Trump's October 12 temporary lifting of sanctions on Russian diesel as complementary supply-side relief shows the sanctions regime itself is now being used counter-cyclically against the oil price; [S104] policymakers should expect further selective sanctions relief as a price-management instrument before any Iran-related relief.

**For corporates**, the message is hedging the tails rather than the central path. Buying convexity (out-of-the-money crude calls, TTF calls given Qatari LNG outage precedent ) is cheap insurance relative to the historical war-premium magnitudes, and shipping exposure argues for war-risk cover ahead of any post-midterm window rather than after it, when the October precedent of VLCC rates at WS776 shows how fast freight reprices.

**For investors**, the highest-information trade is positioning ahead of the November 3, 2026 midterms and the strike decision that follows. [S25] Long gold and long crude-option convexity into the post-midterm window, with an explicit exit on a third Trump cancellation, is the expression of the probability map.

### Why Confidence Is Low — and the Counterargument

This report's overall confidence in the probability map is deliberately low, for three reasons.

The official forecasts are best read as the de-escalation-state price path, not the probability-weighted one — which is precisely why the watch-list above, not any single price target, is this report's most durable deliverable.

## Master Forecast Table and Calibration

The preceding chapters priced each conflict state separately; this chapter assembles them into a single calibrated forecast table, derives the probability-weighted central calls, and states eleven verifiable binary forecasts with resolution criteria.

### The Master Forecast Table

The table below is the report's core deliverable. All market figures are this report's estimates, not observations;

| End-2027 state (probability) | Resolution criteria | End-2027 Brent ($/b) | 2027 avg Brent ($/b) | End-2027 gold ($/oz) | End-2027 TTF ($/MMBtu) | Fed funds | ECB |
|---|---|---|---|---|---|---|---|
| — | — | 95 | 98 | 4,450 | 19 | 3.50% | 2.00% |
| — | — | 140-180 with) | 112 | 5,100 | 28 | 4.00% | 2.50% |
| — | — | 82 | 88 | 3,950 | 14 | 3.25% | 1.75% |
| — | Signed agreement with resumed IAEA access to declared sites (per IAEA statement) and partial sanctions relief | — | — | — | — | — | — |
| — | Credible Reuters/AP reporting of forced removal, death or substantive power transfer of the Supreme Leader or president | — | — | — | — | — | — |

The probability-weighted central forecasts follow directly:

- The weights: 0.35×95 + 0.27×125 + 0.22×82 + 0.09×74 + 0.08×100 ≈ 99.
- **ECB 2.1%** (range 1.75-2.50%).

### Why the Central Calls Diverge from the EIA and IEA

it is the correct conditional forecast for a state with roughly a one-in-three probability.

The divergence is therefore a probability disagreement, not an analytical one.

### Eleven Binary Forecasts with Resolution Criteria

Each forecast below carries a probability (this report's estimate) and a resolution criterion anchored to a named, verifiable source.

1. Resolution: Reuters or AP reports strikes on Iranian nuclear, military or leadership targets. Rationale: reported specific plans for a post-November 3 "short but intensive operation" front-load risk into the post-midterm window;
2. Same resolution basis as (1), matching the skeleton's scenario weight by construction.
3. Resolution: front-month Brent settlement per the EIA/FRED daily series (DCOILBRENTEU), which printed 115.22 on 2026-10-20. [S36] Requires the attrition or escalation states to hold with limited premium decay.
4. Same source. Requires either a Hormuz-disrupting strike round or the chaotic sub-path of regime crisis;
6. Resolution: jointly announced or published agreement text per Reuters/AP, with blockade lifted (Iranian loadings recovering per Vortexa/Kpler tracking ).
7. Resolution: an IAEA statement confirming inspections resumed at Natanz, Fordow and Isfahan;
8. Resolution: signed US-Iran text including IAEA access restoration and sanctions relief. Modest because the Qatar-mediated channel is deadlocked on sequencing (relief-first vs concessions-first) and China has not entered as mediator.
9. Resolution: IMF monthly gold series (September 2026: 4,334.75; [S10] five-year window 4,075-5,015) [S10].
10. Requires the escalation states (and part of attrition, given sticky oil-driven CPI) to force the Fed to hold or hike;

### Calibration: Where the Probabilities Come From and Why They Are Shaded

third, published reporting of specific post-midterm strike plans [S24] converts generic escalation risk into dated intent.

the sub-paths are bimodal and deliberately shown as such in the table.

Two honesty notes on the calibration.

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/iran-standoff-2027/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[35%] Managed low-intensity attrition continues (status quo)**: No US or Israeli strikes on Iranian territory reported by Reuters/AP between 2026-11-01 and 2027-12-31 AND no signed US-Iran agreement in force on 2027-12-31 AND Brent (imf:PCPS/G001.POILBRE.USD.M) 2027-12 observation between 70 and 110 USD/bbl.
- **[27%] Renewed large-scale strikes**: Reuters/AP report US or Israeli strikes on Iranian territory (nuclear, military, or leadership targets) occurring on or after 2026-11-04 and before 2027-12-31. (Retaliation is expected but not required for resolution, to avoid an over-conjunctive criterion.)
- **[22%] Durable ceasefire (no nuclear diplomacy)**: A signed US-Iran ceasefire agreement (text published or jointly announced by both governments) in force on 2027-12-31, with blockade lifted (Iranian crude loadings >1.0 mb/d per tanker-tracking reporting) AND no IAEA access restoration to declared sites (else scenario 4).
- **[9%] Negotiated nuclear framework**: Signed US-Iran agreement text including IAEA access restoration to declared enrichment sites (IAEA inspections resumed, per IAEA statement) and partial sanctions relief in force on 2027-12-31.
- **[8%] Regime crisis / other (succession upheaval, Hormuz tail)**: By 2027-12-31, credible reporting (Reuters/AP/major outlets) of forced removal, death, or substantive power transfer of the sitting Supreme Leader or president, OR open IRGC factional conflict with contested control of Tehran, OR a Hormuz closure attempt materially disrupting traffic, OR an outcome not meeting any prior scenario's criteria (residual).

### Indicators to Watch (check at expiry/trigger)
| Indicator | Due / trigger | Discriminates scenario |
|---|---|---|
| Brent Crude, US dollars per barrel, Unit prices — World (imf:PCPS/G001.POILBRE.USD.M) | next monthly release after 2026-09 | — |
| Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) (fred:CPIAUCSL#yoy) | next monthly release after 2026-09 | — |
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | next monthly release after 2026-09 | — |
| Global price of Natural gas, EU — Euro area (fred:PNGASEUUSDM) | next monthly release after 2026-09 | — |
| Gold, US dollars per troy ounce of gold, Unit prices — World (imf:PCPS/G001.PGOLD.USD.M) | next monthly release after 2026-09 | — |
| Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma — World (fred:DCOILWTICO) | next monthly release after 2026-09 | — |
| Central bank policy rates - Euro area - Monthly - End of period (bis:WS_CBPOL/M.XM) | next monthly release after 2026-09 | — |
| All index, Commodity price index, Index, 2016=100 — World (imf:PCPS/G001.PALLFNF.INDEX.M) | next monthly release after 2026-09 | — |
| Real Exports of Goods and Services — United States (fred:EXPGSC1) | next quarterly release after 2026-Q2 | — |
| Effective exchange rates: Euro area - Real - Broad (64 economies) (bis:WS_EER/M.R.B.XM) | next monthly release after 2026-09 | — |
| ICE BofA US High Yield Index Option-Adjusted Spread (fred:BAMLH0A0HYM2) | next monthly release after 2026-09 | — |
| Consumer prices: Euro area - Year-on-year changes, in per cent (bis:WS_LONG_CPI/M.XM.771) | next monthly release after 2026-08 | — |
| Real imports of goods and services — United States (fred:IMPGSC1) | next quarterly release after 2026-Q2 | — |
| Harmonized Index of Consumer Prices: Total for Euro Area (19 Countries) (year-over-year % change) (fred:CP0000EZ19M086NEST#yoy) | next monthly release after 2026-09 | — |
| Crude Oil Prices: Brent - Europe — World (fred:DCOILBRENTEU) | next monthly release after 2026-09 | — |

### Official series to watch
| Series | Latest complete historical observation | Model threshold / period | Empirical base rate vs model P | Source |
|---|---|---|---|---|
| Central bank policy rates - Euro area - Monthly - End of period (bis:WS_CBPOL/M.XM) | 2.5% (2026-09) | >= 2.5% / 2027-12 | 79% (n=104, h=15) vs model 65% | [Source](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.XM>) [S28] |
| ICE BofA US High Yield Index Option-Adjusted Spread (fred:BAMLH0A0HYM2) | 2.755% (2026-09) | > 4.035% / 2027-12 | insufficient history vs model 25% | [Source](<https://fred.stlouisfed.org/series/BAMLH0A0HYM2>) [S32] |
| Central bank policy rates - United States - Monthly - End of period (bis:WS_CBPOL/M.US) | 3.875% (2026-09) | >= 3.875% / 2027-12 | 57% (n=104, h=15) vs model 60% | [Source](<https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US>) [S8] |
| Real Exports of Goods and Services — United States (fred:EXPGSC1) | 2814.538 Billions of Chained 2017 Dollars (2026-Q2) | < 2600 Billions of Chained 2017 Dollars / 2027-Q4 | 9% (n=32, h=6) vs model 15% | [Source](<https://fred.stlouisfed.org/series/EXPGSC1>) [S30] |

<!-- drf-news-market-context:4aa23d1f5ef6a25062e43eca87654ff20ae8e08ab8d1ee20cd3eb56b83467a10:start -->
### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability. Links identify original sources directly; stored citation identifiers belong to the original research ledger.

| Provider / kind / identity | Source | Published / retrieved | Status / source quote |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport_timeout) |
<!-- drf-news-market-context:4aa23d1f5ef6a25062e43eca87654ff20ae8e08ab8d1ee20cd3eb56b83467a10:end -->

<!-- sim-bridge:start -->
## Scenario simulation: what the exercise explored

Simulated under declared assumptions. Not observed facts, not a calibrated probability, and not an input to any probability in this report.

- Engine: oasis-reflexive
- Horizon: 2026-10-23 → 2027-12-31 (month)
- Periods committed: 14 of 14 planned
- Health: ok (validity: valid)
- Arbiter-failed rounds: 5
- Modelling gaps: 9

### Decisive moves

| Period | Actor | Move | Target | Public statement |
|---|---|---|---|---|
| 2026-12 | IRGC | Counter US Central Command's move (CENTCOM raises force protection and accelerates shadow-fleet interdictions afte…) | US Central Command | The Islamic Revolutionary Guard Corps holds CENTCOM responsible for the pirate seizure and disabling of two tankers in international waters. These acts of state… |
| 2027-11 | IRGC | Advance your documented plan: Raise costs of any re-strike via preemption doctrine | Israel, US Central Command | The Guard confirms its retaliation for the 31 August aggression has been executed in full; the enemy's interceptors changed only the price, not the ledger. We r… |
| 2027-03 | IAEA | Open or join negotiations with another actor | Iranian diplomatic faction (Foreign Ministry), Government of China, Donald Trump | IAEA statement: The Agency notes the Islamic Republic's stated readiness to receive inspector redeployment at declared sites and welcomes China's simultaneous-r… |
| 2026-12 | IAEA | Advance your documented plan: Restore safeguards at Fordow, Natanz, Isfahan | Supreme Leader Mojtaba Khamenei | IAEA Director General statement: Eleven months have passed since inspectors last accessed Fordow, Natanz and Isfahan — the Agency can no longer verify the locat… |
| 2027-08 | Israel | Counter Hezbollah's move (Advance your documented plan: Rebuild deterrent against Israel → Israel) | Hezbollah | IDF Spokesperson's Unit: Recent rocket fire from southern Lebanon is a direct violation of the ceasefire framework and UN Resolution 1701. In response, the IDF … |
| 2026-12 | Israel | Deliver commitment [c3_1_1]: Be ready to execute a short but intensive strike package against Iranian nuclear and IRGC targets within 2 periods of the post-midterm political decision window. |  | IDF Spokesperson's Unit: In accordance with the post-election decision timeline, the IDF has finalized and maintains full operational readiness for a short but … |
| 2027-06 | IRGC | Advance your documented plan: Raise costs of any re-strike via preemption doctrine | US Central Command, Donald Trump | IRGC Navy commences announced joint missile-and-UAV live-fire exercises across the Strait of Hormuz 'kill-box' corridors from June 10–18, 2027, under pre-delega… |
| 2027-06 | Israel | Deliver commitment [c3_7_3]: If IAEA inspectors have not physically entered the Isfahan tunnels by 30 days from this statement, Israel will execute follow-on strikes on tunnel entrances and Pickaxe Mountain, coordinating with US Central Command to… |  | IDF Spokesperson's Unit: The 30-day deadline has expired. IAEA inspectors have not physically entered a single Isfahan tunnel. In fulfillment of our stated comm… |

### Red lines crossed and commitments broken

- Benjamin Netanyahu: commitments kept 5, lapsed 1, broken 0
- Donald Trump: commitments kept 1, lapsed 4, broken 3
- Government of China: commitments kept 1, lapsed 1, broken 0
- Hezbollah: commitments kept 1, lapsed 3, broken 0
- IAEA: commitments kept 1, lapsed 3, broken 2
- IRGC: commitments kept 1, lapsed 3, broken 0
- Iranian diplomatic faction (Foreign Ministry): commitments kept 1, lapsed 3, broken 0
- Saudi Arabia: commitments kept 1, lapsed 1, broken 0
- Supreme Leader Mojtaba Khamenei: commitments kept 5, lapsed 2, broken 0
- US Central Command: commitments kept 0, lapsed 1, broken 0
- US Federal Reserve: commitments kept 5, lapsed 1, broken 0

### Simulated shares beside this report's probabilities

| Scenario | Final simulated share | Report probability |
|---|---|---|
| Managed low-intensity attrition continues (status quo) | — | 35% |
| Renewed large-scale strikes | 26.0% | 27% |
| Durable ceasefire (no nuclear diplomacy) | — | 22% |
| Negotiated nuclear framework | — | 9% |
| Regime crisis / other (succession upheaval, Hormuz tail) | — | 8% |
| Negotiated framework | 59.4% | — |
| Low-intensity conflict | 13.2% | — |
| Durable ceasefire | 1.1% | — |
| Regime crisis | 0.4% | — |

The probabilities in this report were not changed by the exercise (policy: diagnostic_only).

<!-- viz:charts/worldstate_trajectory.html -->
![Simulated outcome-share trajectory](demos/iran-standoff-2027/charts/worldstate_trajectory.png)

*Simulated outcome-share trajectory*

<!-- viz:charts/world_variables.html -->
![Simulated state variables (indexed, seed = 100)](demos/iran-standoff-2027/charts/world_variables.png)

*Simulated state variables (indexed, seed = 100)*

Full record: `simulation_record.md` (canonical JSON SHA-256 de2cf89831bfc7426b4c0b0d9968d036ecc9512d0d8b35b7748f2fb7e2f901ff)
<!-- sim-bridge:end -->

<!-- forecast-track-record:start -->
## Historical forecasting track record

These scores describe retained forecasts with recorded outcomes. A limited record does not establish calibration.

| Forecast type | Forecasts | Resolved | Outstanding | Mean Brier |
|---|---:|---:|---:|---:|
| Scenarios (multiclass) | 3 | 0 | 3 | — |
| Market binaries | 0 | 0 | 0 | — |
| Official-data binaries | 7 | 0 | 7 | — |
| Unanchored binaries | 33 | 0 | 33 | — |

Scenario and binary scores have separate denominators. This report is excluded from its own history.
<!-- forecast-track-record:end -->

## References

1. [S5] Brent Crude, US dollars per barrel, Unit prices — World — data.imf.org — [https://data.imf.org/en/datasets/IMF.RES:PCPS](https://data.imf.org/en/datasets/IMF.RES:PCPS)
2. [S8] Central bank policy rates - United States - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.US)
3. [S28] Central bank policy rates - Euro area - Monthly - End of period — data.bis.org — [https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.XM](https://data.bis.org/topics/CBPOL/BIS,WS_CBPOL,1.0/M.XM)
4. [S29] All index, Commodity price index, Index, 2016=100 — World — data.imf.org — [https://data.imf.org/en/datasets/IMF.RES:PCPS](https://data.imf.org/en/datasets/IMF.RES:PCPS)
5. [S18] Crude Oil Prices: West Texas Intermediate (WTI) - Cushing, Oklahoma — World — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DCOILWTICO](https://fred.stlouisfed.org/series/DCOILWTICO)
6. [S30] Real Exports of Goods and Services — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/EXPGSC1](https://fred.stlouisfed.org/series/EXPGSC1)
7. [S31] Effective exchange rates: Euro area - Real - Broad (64 economies) — data.bis.org — [https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.XM](https://data.bis.org/topics/EER/BIS,WS_EER,1.0/M.R.B.XM)
8. [S6] Consumer Price Index for All Urban Consumers: All Items in U.S. City Average (year-over-year % change) — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CPIAUCSL](https://fred.stlouisfed.org/series/CPIAUCSL)
9. [S32] ICE BofA US High Yield Index Option-Adjusted Spread — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/BAMLH0A0HYM2](https://fred.stlouisfed.org/series/BAMLH0A0HYM2)
10. [S10] Gold, US dollars per troy ounce of gold, Unit prices — World — data.imf.org — [https://data.imf.org/en/datasets/IMF.RES:PCPS](https://data.imf.org/en/datasets/IMF.RES:PCPS)
11. [S33] Consumer prices: Euro area - Year-on-year changes, in per cent — data.bis.org — [https://data.bis.org/topics/CPI/BIS,WS_LONG_CPI,1.0/M.XM.771](https://data.bis.org/topics/CPI/BIS,WS_LONG_CPI,1.0/M.XM.771)
12. [S34] Real imports of goods and services — United States — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/IMPGSC1](https://fred.stlouisfed.org/series/IMPGSC1)
13. [S35] Harmonized Index of Consumer Prices: Total for Euro Area (19 Countries) (year-over-year % change) — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/CP0000EZ19M086NEST](https://fred.stlouisfed.org/series/CP0000EZ19M086NEST)
14. [S9] Global price of Natural gas, EU — Euro area — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/PNGASEUUSDM](https://fred.stlouisfed.org/series/PNGASEUUSDM)
15. [S36] Crude Oil Prices: Brent - Europe — World — fred.stlouisfed.org — [https://fred.stlouisfed.org/series/DCOILBRENTEU](https://fred.stlouisfed.org/series/DCOILBRENTEU)
16. [S19] Analysis of IAEA Iran Verification and Monitoring and NPT Safeguards Reports — June 2026 | ISIS Reports | Institute For Science And International Security — isis-online.org — [https://isis-online.org/isis-reports/analysis-of-iaea-iran-verification-and-monitoring-and-npt-safeguards-reports-june-2026](https://isis-online.org/isis-reports/analysis-of-iaea-iran-verification-and-monitoring-and-npt-safeguards-reports-june-2026)
17. [S89] Khamenei Is Dead: The 2026 Iran War Could Become a Giant Power Vacuum Crisis | American Enterprise Institute - AEI — aei.org — [https://www.aei.org/commentary/khamenei-is-dead-the-2026-iran-war-could-become-a-giant-power-vacuum-crisis/](https://www.aei.org/commentary/khamenei-is-dead-the-2026-iran-war-could-become-a-giant-power-vacuum-crisis/)
18. [S47] Middle East oil exports top pre-war levels for part of September but tanker attacks increase | Reuters — reuters.com — [https://www.reuters.com/business/energy/middle-east-crude-oil-exports-exceed-pre-war-levels-tanker-attacks-increase-2026-10-05/](https://www.reuters.com/business/energy/middle-east-crude-oil-exports-exceed-pre-war-levels-tanker-attacks-increase-2026-10-05/)
19. [S69] Iran Succession Crisis After Supreme Leader Khamenei Death — forbes.com — [https://www.forbes.com/sites/guneyyildiz/2026/02/28/khamenei-is-dead---irans-missiles-keep-flying-without-him/](https://www.forbes.com/sites/guneyyildiz/2026/02/28/khamenei-is-dead---irans-missiles-keep-flying-without-him/)
20. [S54] Supertanker rates fall from record highs - Reuters — reuters.com — [https://www.reuters.com/business/energy/supertanker-rates-fall-record-highs-2026-10-16/](https://www.reuters.com/business/energy/supertanker-rates-fall-record-highs-2026-10-16/)
21. [S25] US, Israel said to draft plans for resumed strikes on Iran after midterm elections | The Times of Israel — timesofisrael.com — [https://www.timesofisrael.com/us-israel-said-to-draft-plans-for-resumed-strikes-on-iran-after-midterm-elections/](https://www.timesofisrael.com/us-israel-said-to-draft-plans-for-resumed-strikes-on-iran-after-midterm-elections/)
22. [S80] Saudi-led intervention in the Yemeni civil war - Wikipedia — en.wikipedia.org — [https://en.wikipedia.org/wiki/Saudi-led_intervention_in_the_Yemeni_civil_war](https://en.wikipedia.org/wiki/Saudi-led_intervention_in_the_Yemeni_civil_war)
23. [S13] The status of Iran's uranium enrichment programme | Reuters — reuters.com — [https://www.reuters.com/world/middle-east/status-irans-uranium-enrichment-programme-2026-10-07/](https://www.reuters.com/world/middle-east/status-irans-uranium-enrichment-programme-2026-10-07/)
24. [S40] Chinese independent refiners boost Iraqi oil purchases as Iranian flows fall, traders say | Reuters — reuters.com — [https://www.reuters.com/business/energy/chinese-independent-refiners-boost-iraqi-oil-purchases-iranian-flows-fall-2026-10-06/](https://www.reuters.com/business/energy/chinese-independent-refiners-boost-iraqi-oil-purchases-iranian-flows-fall-2026-10-06/)
25. [S3] Looming US sanctions on Iran put China oil buying in spotlight | Reuters — reuters.com — [https://www.reuters.com/business/energy/looming-us-sanctions-iran-put-china-oil-buying-spotlight-2026-08-24/](https://www.reuters.com/business/energy/looming-us-sanctions-iran-put-china-oil-buying-spotlight-2026-08-24/)
26. [S11] Federal Reserve Board - Federal Reserve issues FOMC statement — federalreserve.gov — [https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm](https://www.federalreserve.gov/newsevents/pressreleases/monetary20260916a.htm)
27. [S14] Comprehensive Imagery Report on Nuclear Enrichment Related Sites, Post-April Ceasefire | ISIS Reports | Institute For Science And International Security — isis-online.org — [https://isis-online.org/isis-reports/comprehensive-imagery-report-on-nuclear-enrichment-related-sites-post-april-ceasefire](https://isis-online.org/isis-reports/comprehensive-imagery-report-on-nuclear-enrichment-related-sites-post-april-ceasefire)
28. [S15] [PDF] Board of Governors Implementation of the NPT Safeguards Agreement... — iaea.org — [https://www.iaea.org/sites/default/files/gov2026-8.pdf](https://www.iaea.org/sites/default/files/gov2026-8.pdf)
29. [S16] gov2026 50.pdf — iaea.org — [https://www.iaea.org/sites/default/files/gov2026-50.pdf](https://www.iaea.org/sites/default/files/gov2026-50.pdf)
30. [S17] Iran names Mojtaba Khamenei as new supreme leader after father’s killing | US-Israel war on Iran News | Al Jazeera — aljazeera.com — [https://www.aljazeera.com/news/2026/3/8/iran-names-khameneis-son-as-new-supreme-leader-after-fathers-killing-2](https://www.aljazeera.com/news/2026/3/8/iran-names-khameneis-son-as-new-supreme-leader-after-fathers-killing-2)
31. [S22] U.S. lifts blockade of Iran and Iranian supreme leader endorses direct talks with American officials | PBS News — pbs.org — [https://www.pbs.org/newshour/world/u-s-lifts-blockade-of-iran-and-iranian-supreme-leader-endorses-direct-talks-with-american-officials](https://www.pbs.org/newshour/world/u-s-lifts-blockade-of-iran-and-iranian-supreme-leader-endorses-direct-talks-with-american-officials)
32. [S23] Iran prolongs talks in stalemate to influence US midterms, officials say | Reuters — reuters.com — [https://www.reuters.com/world/us/iran-prolongs-talks-stalemate-influence-us-midterms-officials-say-2026-10-20/](https://www.reuters.com/world/us/iran-prolongs-talks-stalemate-influence-us-midterms-officials-say-2026-10-20/)
33. [S24] U.S. and Israel Draw Up Plans for Renewed Strikes on Iran After Elections - The New York Times — nytimes.com — [https://www.nytimes.com/2026/10/21/us/politics/us-israel-renewed-iran-strikes.html](https://www.nytimes.com/2026/10/21/us/politics/us-israel-renewed-iran-strikes.html)
34. [S39] US blockade keeps Iranian crude exports at zero in October, report says — reuters.com — [https://www.reuters.com/business/energy/us-blockade-keeps-iranian-crude-exports-zero-october-report-says-2026-10-13/](https://www.reuters.com/business/energy/us-blockade-keeps-iranian-crude-exports-zero-october-report-says-2026-10-13/)
35. [S45] Operation Economic Outcast Neutralizes Iranian Regime’s Remaining Shadow Fleet Network | U.S. Department of the Treasury — home.treasury.gov — [https://home.treasury.gov/news/press-releases/sb0653](https://home.treasury.gov/news/press-releases/sb0653)
36. [S50] Brent steady as US weighs easing sanctions on global 'shadow fleet' | Reuters — reuters.com — [https://www.reuters.com/business/energy/oil-prices-fall-investors-weigh-supply-outlook-middle-east-tensions-2026-10-15/](https://www.reuters.com/business/energy/oil-prices-fall-investors-weigh-supply-outlook-middle-east-tensions-2026-10-15/)
37. [S57] Oil Market Report - October 2026 - IEA — iea.org — [https://www.iea.org/reports/oil-market-report-october-2026](https://www.iea.org/reports/oil-market-report-october-2026)
38. [S59] Qatar LNG, Saudi refinery, Israeli oil, gas fields down due to Mideast strikes — reuters.com — [https://www.reuters.com/business/energy/saudi-aramco-shuts-ras-tanura-refinery-after-drone-strike-source-says-2026-03-02/](https://www.reuters.com/business/energy/saudi-aramco-shuts-ras-tanura-refinery-after-drone-strike-source-says-2026-03-02/)
39. [S99] Short-Term Energy Outlook - U.S. Energy Information Administration (EIA) — eia.gov — [https://www.eia.gov/outlooks/steo/report/global_oil.php](https://www.eia.gov/outlooks/steo/report/global_oil.php)
40. [S100] Oil Market Report - July 2026 - IEA — iea.org — [https://www.iea.org/reports/oil-market-report-july-2026](https://www.iea.org/reports/oil-market-report-july-2026)
41. [S84] 2026 Iranian supreme leader election - Wikipedia — en.wikipedia.org — [https://en.wikipedia.org/wiki/2026_Iranian_supreme_leader_election](https://en.wikipedia.org/wiki/2026_Iranian_supreme_leader_election)
42. [S67] Hezbollah Rebuilds Military Capabilities in Beirut, Prepares for Renewed Fighting Against Israel | Algemeiner.com — algemeiner.com — [https://www.algemeiner.com/2026/10/21/hezbollah-rebuilds-military-capabilities-beirut-prepares-renewed-fighting-israel/](https://www.algemeiner.com/2026/10/21/hezbollah-rebuilds-military-capabilities-beirut-prepares-renewed-fighting-israel/)
43. [S7] Annual inflation up to 3.8% in the euro area - Euro indicators - Eurostat — ec.europa.eu — [https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-16102026-ap](https://ec.europa.eu/eurostat/web/products-euro-indicators/w/2-16102026-ap)
44. [S41] Iran's secret oil supply bound for China has dried up — nypost.com — [https://nypost.com/2026/10/22/world-news/irans-secret-oil-supply-bound-for-china-has-dried-up/](https://nypost.com/2026/10/22/world-news/irans-secret-oil-supply-bound-for-china-has-dried-up/)
45. [S26] What we know about war plans that Trump and Netanyahu are drawing up: NPR — npr.org — [https://www.npr.org/2026/10/22/nx-s1-6012306/what-we-know-about-war-plans-that-trump-and-netanyahu-are-drawing-up](https://www.npr.org/2026/10/22/nx-s1-6012306/what-we-know-about-war-plans-that-trump-and-netanyahu-are-drawing-up)
46. [S110] Oil prices drop 6% as Israel-Iran ceasefire reduces Middle East... — reuters.com — [https://www.reuters.com/business/energy/us-crude-oil-futures-fall-over-3-trump-announces-israel-iran-ceasefire-2025-06-23/](https://www.reuters.com/business/energy/us-crude-oil-futures-fall-over-3-trump-announces-israel-iran-ceasefire-2025-06-23/)
47. [S53] Gold Price Today: October 22, 2026 – Forbes Advisor — forbes.com — [https://www.forbes.com/advisor/investing/gold-price/](https://www.forbes.com/advisor/investing/gold-price/)
48. [S1] U.S. Conflict with Iran | Congress.gov | Library of Congress — congress.gov — [https://www.congress.gov/crs-product/R48887](https://www.congress.gov/crs-product/R48887)
49. [S12] Fed rate hike call seen tight as inflation heats up - Reuters — reuters.com — [https://www.reuters.com/markets/us/fed-rate-hike-seen-more-likely-after-inflation-data-2026-10-14/](https://www.reuters.com/markets/us/fed-rate-hike-seen-more-likely-after-inflation-data-2026-10-14/)
50. [S49] War risk insurance costs surge for southern Red Sea voyages after... — reuters.com — [https://www.reuters.com/world/middle-east/war-risk-insurance-costs-surge-southern-red-sea-voyages-after-houthi-attacks-2026-07-23/](https://www.reuters.com/world/middle-east/war-risk-insurance-costs-surge-southern-red-sea-voyages-after-houthi-attacks-2026-07-23/)
51. [S60] Strait of Hormuz - About - IEA — iea.org — [https://www.iea.org/about/oil-security-and-emergency-response/strait-of-hormuz](https://www.iea.org/about/oil-security-and-emergency-response/strait-of-hormuz)
52. [S104] Attacks on Saudi Oil Facilities: Effects and Responses — congress.gov — [https://www.congress.gov/crs_external_products/IN/PDF/IN11173/IN11173.3.pdf](https://www.congress.gov/crs_external_products/IN/PDF/IN11173/IN11173.3.pdf)
53. [S105] Risk of oil supply disruptions can have an immediate effect on oil prices - — eia.gov — [https://www.eia.gov/todayinenergy/detail.php?id=42675](https://www.eia.gov/todayinenergy/detail.php?id=42675)
54. [S108] Oil settles up 7% as Israel, Iran trade air strikes | Reuters — reuters.com — [https://www.reuters.com/world/china/oil-prices-jump-more-than-4-after-israel-strikes-iran-2025-06-13/](https://www.reuters.com/world/china/oil-prices-jump-more-than-4-after-israel-strikes-iran-2025-06-13/)
55. [S113] Gold advances as Israel-Iran escalation fuels safe-haven bids — reuters.com — [https://www.reuters.com/world/china/gold-tops-1-month-high-middle-east-tensions-spur-safe-haven-demand-2025-06-13/](https://www.reuters.com/world/china/gold-tops-1-month-high-middle-east-tensions-spur-safe-haven-demand-2025-06-13/)
56. [S121] Israel's stocks and shekel jump after Israel and US strike Iran | Reuters — reuters.com — [https://www.reuters.com/world/middle-east/israels-stocks-shekel-jump-after-israel-us-strike-iran-2026-03-02/](https://www.reuters.com/world/middle-east/israels-stocks-shekel-jump-after-israel-us-strike-iran-2026-03-02/)
57. [S118] TA-35 Index About | TASE Site — market.tase.co.il — [https://market.tase.co.il/en/market_data/index/142/about](https://market.tase.co.il/en/market_data/index/142/about)
58. [S58] Saudi Arabia CDS 5 Year USD Bond Historical Data - Investing.com — investing.com — [https://www.investing.com/rates-bonds/saudi-arabia-cds-5-year-usd-historical-data](https://www.investing.com/rates-bonds/saudi-arabia-cds-5-year-usd-historical-data)
59. [S21] 2026 Iran war ceasefire - Wikipedia — en.wikipedia.org — [https://en.wikipedia.org/wiki/2026_Iran_war_ceasefire](https://en.wikipedia.org/wiki/2026_Iran_war_ceasefire)
60. [S2] CENTCOM Maintains Strict Enforcement of U.S. Blockade Against Iran > U.S. Central Command > U.S. Central Command (CENTCOM) Official Public Releases — centcom.mil — [https://www.centcom.mil/MEDIA/PUBLIC-RELEASES/Article/4619553/centcom-maintains-strict-enforcement-of-us-blockade-against-iran/](https://www.centcom.mil/MEDIA/PUBLIC-RELEASES/Article/4619553/centcom-maintains-strict-enforcement-of-us-blockade-against-iran/)
61. [S98] Enabling Iran: A Timeline of China’s Role During and After Operation Epic Fury | U.S.- CHINA | ECONOMIC and SECURITY REVIEW COMMISSION — uscc.gov — [https://www.uscc.gov/research/enabling-iran-timeline-chinas-role-during-and-after-operation-epic-fury](https://www.uscc.gov/research/enabling-iran-timeline-chinas-role-during-and-after-operation-epic-fury)
62. [S101] OPEC Spare Capacity 2026: What the EIA Numbers Really Show — kingdomexploration.com — [https://www.kingdomexploration.com/?page=news&article=eia-opec-capacity-redefinition-january-2026-supply-crisis](https://www.kingdomexploration.com/?page=news&article=eia-opec-capacity-redefinition-january-2026-supply-crisis)
63. [S56] Hormuz oil shipments at prewar levels but fuel shipments constrained — cnbc.com — [https://www.cnbc.com/2026/09/30/iran-war-strait-hormuz-gulf-oil-fuel.html](https://www.cnbc.com/2026/09/30/iran-war-strait-hormuz-gulf-oil-fuel.html)
64. [S4] Iran’s export floor disappears as crude falls to 210kbd | Vortexa — vortexa.com — [https://www.vortexa.com/insights/irans-export-floor-disappears](https://www.vortexa.com/insights/irans-export-floor-disappears)
65. [S77] Three years since 7 October: How has violence changed in Gaza and Lebanon? | ACLED — acleddata.com — [https://acleddata.com/expert-comment/three-years-7-october-how-has-violence-changed-gaza-and-lebanon](https://acleddata.com/expert-comment/three-years-7-october-how-has-violence-changed-gaza-and-lebanon)
