# Fundamentals, polls and error

Load when a KIQ needs fundamentals, a polling average, an error prior, votes-to-seats, or a correlated probability (majority, sweep, two-chamber combination).

Priors below are documented regularities to verify: fetch the named source class before using a number as a finding. Worked examples are hypothetical.

## 1. Order of operations
1. **Lock the contract**: office or chamber, control rule, resolution source and resolution date. See [us-election-mechanics.md](us-election-mechanics.md) or [non-us-elections.md](non-us-elections.md).
2. **Prior** from the reference class (§3), adjusted for fundamentals (§2).
3. **Polls** (§4) with error priors (§5). Poll weight rises as the vote nears: fundamentals dominate a year out, polls the final weeks (Erikson & Wlezien; Jennings & Wlezien).
4. **Structure**: ratings, open seats, money and the map, as race-level evidence.
5. **Votes to seats** (§6), then **correlated aggregation** (§7).
6. **Cross-check** against markets and models (§8); explain divergence; they are not independent confirmation.

## 2. Fundamentals: what to pull and how to read it

| Driver | Catalog series (data_get) | Reading | Trap (misreading → discriminating observation) |
|---|---|---|---|
| Unemployment | fred:UNRATE or bls:LNS14000000. States: bls:LASST060000000000003 (CA), bls:LASST480000000000003 (TX), bls:LASST360000000000003 (NY); other states: data_search "unemployment rate <state>" | The 12-month change matters more than the level; fred:SAHMREALTIME flags recession onset | "Low unemployment helps the in-party" → check the trend; a rising rate from a low level is negative |
| Inflation | fred:CPIAUCSL#yoy; bls:CUSR0000SAF11 (food at home); fred:GASREGW or bls:APU000074714 (gasoline) | Voters judge price levels against wages; gasoline and groceries are the most salient prices | "Inflation fell, so the pain is over" → compare the price level with the pre-surge path and with wages |
| Real income | fred:DSPIC96#yoy. Real wage = fred:CES0500000003#yoy minus CPI year-on-year (REPORTED). Per capita: data_search "real disposable personal income per capita" | The income term in referendum models; use the election-year change | "Income is rising" → aggregates include population growth; transfers distort single months |
| Output | fred:A191RL1Q225SBEA (quarterly, annualized) | Q2–Q3 of the election year in most models | "A strong quarter" → advance estimates are revised; annualizing exaggerates |
| Sentiment | fred:UMCSENT; fred:MICH (expected inflation) | Links data to perception | "Sentiment is objective" → answers track the respondent's party; check partisan splits |
| Approval | No official series: aggregators; Gallup's archive for history | Net approval, intensity, independents | "Approval moved" → check whether the population (A vs RV) or one poll drove it |

**Release rule.** Votes move on the economy perceived by late summer; later prints are signposts. Check in BLS and BEA calendars which periods publish before Election Day, and any delays.

**Anchors.** A binary forecast on a fundamental uses a data_anchor {series, comparator, threshold, period (YYYY-MM-01 for the observation month), units}. Pick thresholds the report argues would change the environment. Record the latest value, its period and the distance to threshold.

**Non-US series.**
- Inflation: imf:CPI/GBR.CPI._T.YOY_PCH_PA_PT.M, imf:CPI/DEU.CPI._T.YOY_PCH_PA_PT.M, imf:CPI/JPN.CPI._T.YOY_PCH_PA_PT.M, imf:CPI/IND.CPI._T.YOY_PCH_PA_PT.M, imf:CPI/BRA.CPI._T.YOY_PCH_PA_PT.M; euro area bis:WS_LONG_CPI/M.XM.771.
- Unemployment: wb:IMF_WEO_LUR/GBR, wb:IMF_WEO_LUR/DEU, wb:IMF_WEO_LUR/JPN; euro area imf:WEO/G163.LUR.A.
- IMF WEO values for future years are projections: REPORTED.

## 3. Reference classes and fundamentals models

**Documented priors (verify before use):**
- **House penalty.** The president's party lost House seats in every post-war midterm except 1998 and 2002. Source class: the American Presidency Project (UCSB) midterm seat-change table; Brookings *Vital Statistics on Congress*.
- **Approval.** Losses were much larger when approval was below 50% (Gallup's midterm analyses).
- **Senate penalty.** Weaker and map-dependent: the president's party gained or held Senate seats in roughly a third of post-war midterms (same tables).
- **Incumbency.** House incumbents who reach the general election win above 90% in most cycles, less in wave years (Brookings; OpenSecrets).
- **Exposure.** A party holding many seats above its normal level has more to lose (Oppenheimer, Stimson & Waterman).
- **Mechanisms.** Referendum voting (Tufte), balancing (Alesina & Rosenthal; Bafumi, Erikson & Wlezien), turnout surge and decline (Campbell).

**Model families.** Outputs are REPORTED. Forecasts appear each cycle in the *PS: Political Science & Politics* forecasting symposia.
- Midterm referendum models: in-party vote = f(approval, real income change).
- Generic ballot plus approval plus seats held (Abramowitz; Bafumi, Erikson & Wlezien).
- Seats-in-trouble (Campbell).
- Presidential: time-for-change (Abramowitz), Bread and Peace (Hibbs), the Fair model.

**Cushion method (base-rate-first).**
- **House.** Cushion T = seats the president's party won at the last election − 218. It loses control if its net loss is at least T+1.
  - Prior P(lose) = k/n, where k counts reference midterms with an in-party net loss of at least T+1.
  - Use the full post-war class. Split by approval band (below or above 50%) only if each subclass keeps enough cases. Report k, n and the source.
  - Measure election to election, as the reference table does, not after vacancies or specials.
  - If T < 0 (in-party already in the minority), P(it takes control) = share of reference midterms with an in-party gain of at least |T|: rare.
- **Senate.** In a midterm the president's party holds the vice presidency, so 50 seats keep control. Cushion T_S = its seats − 50.
  - Exposure = the seats it defends in states the other party carried for president.
  - Count k/n from the Senate seat-change column (same rule for T_S < 0), and compare this cycle's exposure with the reference cycles'.
- **Hypothetical.** The in-party holds 222 House seats, so T = 4. If 15 of 20 reference midterms had losses of 5 or more, the prior is 75%. Then adjust for approval, the generic ballot and the map.

## 4. Polling averages: craft
- **Aggregators.** Use two or more with different methods: a simple recent average, a weighted average, or a trend model with house-effect adjustment. Record value, population, window or number of polls, as-of date and method.
- **Field dates**, not release dates; one poll per pollster per window so trackers do not dominate.
- **Population.** Adults (A), registered voters (RV), likely voters (LV). LV screens matter most in midterms.
  - The LV−RV gap's direction depends on which coalition turns out more reliably, and that shifted with the education realignment.
  - Measure the gap from pollsters that publish both; do not assume it.
- **House effects.** A pollster's average deviation from the average at the same field dates; adjust or flag it. Final-week agreement tighter than sampling allows signals herding. Pollster ratings (archived 538 data, Silver Bulletin) are S2. Campaign-released internal polls are selected to favour the sponsor: weight them down sharply.
- **Total error.** It is roughly twice the stated margin of error, which covers sampling only (Shirani-Mehr, Rothschild, Goel & Gelman, JASA 2018). The margin of error on a lead is about twice that on one share.
- **Generic ballot** is not the House popular vote, nor a seat count: uncontested seats, candidate quality and the map intervene (§6). Over the midterm year the in-party's standing has tended to slip further (Bafumi, Erikson & Wlezien): an early average is not the final margin.
- **Race polls** are sparse.
  - Start from the state's or district's last presidential margin, adjusted for incumbency, and let polls pull the estimate as their number grows.
  - Senate results now track presidential partisanship: splits with the presidential result were rare (none in 2016, one in 2020, a few in 2024; verify on certified results).
- **Approval as the outcome** ("approval above X on date D").
  - Resolve on a named aggregator and date.
  - Recent polarized presidents have had far narrower approval ranges than mid-century ones (Gallup archive).
  - Use the historical distribution of approval changes over the same horizon, not a trend line.

## 5. Poll-error priors (verify; name the source in the finding)
- **US.** Final-weeks statewide Senate and governor polls have missed the margin by about 5 points on average; House district polls by more; national averages by a few points. Source class: archived 538 pollster-ratings data; AAPOR task-force reports on 2016 and 2020.
- **Correlation.** Errors are correlated within a cycle through shared non-response, so many states miss the same way.
- **Sign.** A weak guide: Democrats were overstated in 2014, 2016, 2020 and 2024 but not in 2012 or 2022 (AAPOR reports; archived 538 data; verify). Widen σ rather than shifting the mean by last cycle's miss.
- **Cross-national.** Since the 1940s, final-week polls have missed a party's share by about two points on average, with no clear recent deterioration; misses are larger earlier in the cycle (Jennings & Wlezien, *Nature Human Behaviour* 2018).
- **Use.** Set the total error σ on a race margin from these priors and the time left, and record σ as an assumption.

## 6. Votes to seats (US House)
**Notation** (margins D−R, in points):
- M: last presidential national margin.
- m_d: district d's last presidential margin under the map in force.
- G: generic-ballot margin.
- Swing s = G − M.

**Uniform swing.** District d goes D if m_d + s > 0.

**Identity.** D wins 218+ seats if G > M − m_(218), where m_(218) is the 218th most Democratic district margin. Record the map bias b = M − m_(218): the national lead D needs (positive b = R-leaning map).

**Slope.** Seats per point of swing ≈ (districts within ±5 points of the swing line)/10, an approximation.

**Then adjust** for incumbency (a personal vote of a few points, shrinking as races nationalize), open seats, candidate quality and uncontested seats. Do not count candidate effects twice if race polls already reflect them.

**Sources.** Presidential results by district for the map in force: The Downballot / Daily Kos Elections (S2); Cook PVI (S2); state map files (S1).

The Senate works state by state: see the tipping-point method (§7).

## 7. Correlated aggregation by hand
**Model.** Race margin error = N + u: N is a national error shared by all races, u is race-specific. σ_total² = σ_N² + σ_u²; late in the cycle each is a few points (§5). Record your values.

**Normal table.**

| x | 0 | 0.25 | 0.5 | 1.0 | 1.28 | 1.5 | 1.645 | 2.0 |
|---|---|---|---|---|---|---|---|---|
| Φ(x) | 0.50 | 0.60 | 0.69 | 0.84 | 0.90 | 0.93 | 0.95 | 0.977 |

Φ(−x) = 1 − Φ(x).

**Tipping point (one chamber).**
1. Sort the contested races by the party's expected margin, best first.
2. With holdovers H (Senate seats not up), the party needs k = threshold − H wins. The k-th race is the tipping point, with margin m_tip.
3. P(control) ≈ Φ(m_tip/σ_total). If race errors are small relative to the national error, it approaches Φ(m_tip/σ_N).
4. The median seat count must point the same way.

**Three nodes (sweeps, two-chamber combinations).** Approximate N by three values: −1.732σ_N, 0 and +1.732σ_N, with weights 1/6, 2/3 and 1/6 (3-point Gauss–Hermite). At each node race i wins with p_i = Φ((m_i + N)/σ_u). Within a node races are independent: multiply within nodes, then weight across them.

**Hypothetical sweep.** Four races at m = 0, σ_N = σ_u = 3.
- Independence gives 0.5⁴ = 6%.
- Node +5.2: p = Φ(1.73) ≈ 0.96 each, so all four ≈ 0.84. Node 0: 0.0625. Node −5.2: ≈ 0.
- Sweep ≈ (1/6)(0.84) + (2/3)(0.0625) ≈ 0.18, three times the independent product, while each race stays at 50%.

**Hypothetical two chambers.** House tipping margin +2 (D), Senate −2, σ_N = 3, σ_u = 2.

| Node N | P(House D) | P(Senate D) |
|---|---|---|
| +5.2 | ≈1.00 | Φ(1.6) = 0.945 |
| 0 | 0.84 | 0.16 |
| −5.2 | 0.055 | ≈0 |

- Weighted: DD 0.25, DR 0.49, RD 0.02, RR 0.25.
- Marginals: P(House D) 0.74, P(Senate D) 0.26. Independence would give DD 0.19 and RD 0.07.
- Integer weights 25/49/2/24. A House that averages many seats has a smaller σ_u than a single Senate race; state the value you use.

**Sanity checks.**
- A sweep equal to the product of race probabilities means independence was assumed.
- Same-party control of both chambers must exceed the independent product.
- Scenario weights must reproduce the binary marginals: P(D House) = DD + DR.

## 8. Markets and published models (election-specific)
- **Record** venue (Polymarket, Kalshi, PredictIt, aggregators), contract wording, price, volume or open interest, spread, fetch time.
- **Resolution check first**:
  - "wins" versus "controls";
  - seats won versus a majority on a date;
  - how independents count and how 50–50 is treated;
  - a media call versus certification;
  - a deadline that falls before a runoff.
- **Frictions keep cross-venue gaps open.** Fees; position caps (PredictIt has historically capped positions); capital tied up for months, which pulls long-dated favourites toward 50; partisan skew in the trader base; large single traders (documented in past cycles). A gap that persists beyond fees signals friction, not information.
- **Use** a liquidity-weighted cross-venue price as one anchor. Name the reason for any gap above 10 points from your estimate: a resolution mismatch, a bias, or information the market lacks.
- **Models.** Record name, date, method (polls-only or with fundamentals) and output as REPORTED. Ratings, models and markets all ingest the same polls: one evidence family.
