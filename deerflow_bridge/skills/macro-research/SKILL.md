---
name: macro-research
description: Economy-wide forecasts - policy-rate paths and central-bank decisions (Fed/FOMC, ECB, BOJ, PBoC, others), inflation thresholds (CPI, PCE, core, HICP), growth and nowcasts, recessions, unemployment and payrolls, fiscal deficits and debt, credit and financial conditions, macro FX, and China macro (GDP, CPI/PPI, LPR, RRR, TSF, property drag). Triggers - rate cut, rate hike, dot plot, FOMC, soft landing, stagflation, recession odds, inflation below X% by, GDP growth, IMF WEO forecast, 宏观, 经济增长, 增速, 通胀, CPI, PPI, 降息, 加息, 降准, 利率路径, 美联储, 欧洲央行, 日本央行, 人民银行, LPR, 社融, 衰退, 失业率, 非农, 财政赤字, 政府债务. Not for - industry size or outlooks (industry-research, industry-forecasting); bond-yield, FX-rate, equity-index or commodity-price targets (financial-markets-forecasting); whether a tariff, sanction or law happens (policy-and-trade-forecasting; tariff pass-through to prices stays here); elections (election-forecasting).
---

# Macro Research — regimes, reaction functions, settle-ready data
Forecast economy-wide outcomes from official series, central-bank reaction functions and long-history base rates. Every load-bearing finding names the series, period, unit and threshold it can settle on.

## Activation
Lead when the resolving quantity is an economy-wide aggregate or a central-bank decision: a policy rate at a date or the number of moves, a CPI/PCE/HICP threshold, unemployment, GDP growth, a recession call, a deficit or debt ratio, China growth, deflation or PBoC easing.
- Pair with `reference-class-forecasting` always; with `financial-markets-forecasting` when a yield or FX level resolves; with `policy-and-trade-forecasting` when a tariff decision drives prices (the legal path is theirs, the price pass-through is ours).
- In industry, election or conflict questions with a macro driver, contribute only the regime-dashboard KIQ.
- Adds to the deep-research core: regime diagnosis with a shift test, reaction functions built meeting by meeting, release-aware nowcasting, settle-ready catalog anchors, macro base rates counted from stored history.

## Plan
- **Pin the resolving quantity**: catalog series (`#yoy` = 12-month rate), native period, units, SA/NSA, comparator. "Below 2.5% by Dec 2027": the 2027-12 print or any earlier month? Keep both.
- **KIQs**: (1) data: regime dashboard (growth, inflation headline/core/goods/services, labour, financial conditions, fiscal); (2) data: nowcast and decomposition of the resolving series; (3) actor: central-bank reaction function, voters, constraints; Treasury/MOF/State Council; (4) general: market path vs official projection (SEP/staff, WEO, GEP) vs consensus; (5) base rate worded "historically, how often…" (历史上), data_needs = counted series (prefetch 30 years; monthly keeps 20); (6–7) drivers: fiscal impulse, energy/tariff shocks, credit, dollar, spillovers; China: NBS/PBoC data, Politburo–CEWC–NPC calendar.
- **data_needs**, anchor first. Fed: bis:WS_CBPOL/M.US, fred:PCEPILFE#yoy, fred:UNRATE. CPI: bls:CUUR0000SA0#yoy, fred:CPILFESL#yoy, bls:CUSR0000SAH1#yoy. Recession: fred:SAHMREALTIME, fred:T10Y3M, fred:A191RL1Q225SBEA. ECB/BOJ: bis:WS_CBPOL/M.XM, bis:WS_CBPOL/M.JP. China: wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN, bis:WS_LONG_CPI/M.CN.771, bis:WS_CBPOL/M.CN; else {"query": "China producer price index", "geography": "CHN"}.
- **Scenarios** = MECE regimes to the horizon, fit to the question: soft landing / reacceleration / hard landing / stagflation (China: managed slowdown / deflationary stagnation / stimulus reflation / external shock). **Weight base-rate-first**: documented regime frequency (prior to verify, NBER: a US recession began in ≈1 of 6.5 years since 1948, 1 of 11 since 1983), then stated shifts for scout pricing and hard signals (curve, Sahm); merge tails under 5 unless signposted. Name each by its anchor-series signature (end policy rate, core inflation, jobless rate).

## Investigate
**Quick (≈5 rounds)**: data_get the anchor with its exact settling transform (forecasts anchor only on series stored in this run, with its first call's window: base rates start 30 years back); the latest decision text (FOMC statement/SEP, ECB/BOJ, PBoC/NBS); a dated market path (FedWatch, OIS). **Standard**: dashboard and decomposition series; nowcasts (GDPNow, NY Fed, Cleveland Fed) and WEO/GEP vintages, REPORTED; consensus (S2). **Deep**: minutes, voter speeches, k-of-n base rate.
- **Dashboard**: fred:A191RL1Q225SBEA, fred:PAYEMS, fred:PCEPILFE#yoy, fred:MICH, fred:T10YIE, fred:UNRATE, fred:FEDFUNDS, fred:T10Y3M, fred:NFCI, fred:BAMLH0A0HYM2, fred:DTWEXBGS, usgov:treasury/mts_deficit (12-month sum). Stance = policy rate − core inflation vs r-star (SEP longer-run rate − 2).
- **Shift test**: 3m annualized vs 12m change per block; shift = ≥2 blocks turning together for ≥2 releases, not explained by one-offs (energy, base effects, shutdown gaps).
- **Settle-ready**: native monthly/quarterly series settle automatically; daily series stored as months (fred:DFEDTARU, fred:ECBDFR) and World Bank/WEO only by hand; bis:WS_CBPOL/M.US = range midpoint (upper bound − 0.125).
- **Threshold**: YoY(t) ≈ YoY(t−1) + m/m(t) − m/m(t−12). Required average m/m = ((1+X)/Π(1+m/m) of observed window months)^(1/months left) − 1, vs recent m/m on the same SA/NSA basis.
- **Reaction function**: statement, projections, chair/president > other speakers; voters > non-voters; Taylor = cross-check. Per scheduled meeting: market-implied P(cut/hold/hike) vs guidance and data due.
- **China**: NBS, PBoC, MOF, NDRC, SAFE, in Chinese and English (国家统计局, 人民银行, 政治局会议, 中央经济工作会议); official YoY over levels; Jan–Feb combined; 累计 ≠ 当月.
**Traps**
- SA YoY taken as published CPI → the BLS headline is the NSA 12-month change.
- "P(cut by December)" read as one meeting → FedWatch odds are cumulative; difference them.
- a nowcast or one month read as the quarter → partial or projection.
- two negative quarters read as recession → NBER dates it, months later.
- SEP compared with WEO → SEP is Q4/Q4, WEO annual average.
**Record**: series+transform, period, units, SA/NSA, status, next release, distance to threshold. Actors: role, vote, dated stated bias, dissents, term end, constraints, guidance kept or broken.
**Stop**: anchor, market path and official projection recorded, and two angles add nothing.

## Synthesize
Exhibits (markdown tables of cited facts only):
1. **Regime dashboard**: block | series ID | latest (period) | 3m vs 12m momentum | direction | shift flag.
2. **Policy path**, one row per decision point to the horizon: market-implied (odds, implied rate, fetch date) | official projection or guidance | evidence-based lean (no new odds) | data due before it.
3. **Decomposition** of the resolving quantity: inflation by energy, food, core goods, shelter, other services; growth by expenditure (China: consumption, investment, net exports).
4. **Release calendar**: release | publisher | reference period | date (fetched) | scenario it moves.
5. **Projections**, kept apart from observations: publisher | vintage | target period | value | type (projection, staff forecast, official target, market-implied).
6. **Decision-makers**: actor | vote | dated stated bias | constraint | next decision.
Conventions: "by YEAR" is a deadline (any print through December's, an event through 31 Dec); "at end-YEAR" or "in December" is the December observation (released next month): say which applies; a Fed level means the target-range upper bound unless stated; label YoY, 3m annualized, SA/NSA; China growth/CPI targets are 目标, not forecasts.
Per scenario: its signature on the anchor series, the policy path it implies, its falsifier. Signposts: series ID or indicator, threshold, period, each tied to the scenario it moves. No probability list, no invented numbers; nowcasts and projections stay REPORTED.

## Gaps
- Is the resolving quantity pinned to a stored, settle-ready series with transform, period, SA/NSA and comparator?
- Is there a per-meeting path with dated market-implied odds beside the official projection?
- Does the dashboard cover growth, inflation (core, goods/services), labour, stance vs neutral and financial conditions, with momentum?
- Is there a k-of-n base rate with its episode rule, window and false positives?
- For a threshold, is the required run-rate or distance computed?
- Are the decisive releases before resolution listed with lags and revision risk?
- China: are NPC targets, Politburo/CEWC signals and PBoC tools covered from NBS/PBoC sources?

## References
- [references/central-bank-reaction-functions.md](references/central-bank-reaction-functions.md) — any policy-rate question: Fed/ECB/BOJ/PBoC mandates, signal hierarchy, futures/OIS mechanics, Taylor variants, the meeting-by-meeting build, actor fields.
- [references/nowcasting-and-releases.md](references/nowcasting-and-releases.md) — threshold and nowcast questions: release lags, revisions, SA/NSA, partial periods, base-effect arithmetic, bridging high to low frequency.
- [references/macro-base-rates.md](references/macro-base-rates.md) — base-rate KIQs: k-of-n rules on catalog series within the 240-observation cap; documented priors to verify.
