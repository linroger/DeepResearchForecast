# Central-bank reaction functions — reading guide and path build

Load for policy-rate levels, counts of moves or the timing of the next move. Members, dates, rates and quotes come only from fetched sources; this file holds the method.

## 1. The meeting-by-meeting build (any bank)

1. **Decision points.** Fetch the official calendar (federalreserve.gov FOMC calendar, ECB monetary-policy meetings, BOJ MPM schedule). The PBoC has no scheduled rate meetings: use the LPR fixing on the 20th of each month (next business day on holidays) plus unscheduled moves. List every point from the as-of date to resolution and flag those with projections: Fed SEP and ECB/Eurosystem staff projections (March, June, September, December), BOJ Outlook Report (January, April, July, October).
2. **Data due before each point** — the signposts. Fed: one or two CPIs and jobs reports, PCE. ECB: HICP flash, negotiated wages. BOJ: Tokyo CPI, shunto tallies. PBoC: credit, CPI/PPI, activity data.
3. **Three columns per point.** *Market-implied*: outcome odds and implied post-meeting rate, with fetch date (§2). *Official*: projection or guidance (SEP year-end median, ECB "meeting-by-meeting", BOJ conditional guidance, PBoC MPC wording). *Evidence-based*: the reaction function applied to the scenario frame.
4. **Consistency checks.** Odds sum to 1 at every meeting; P(≥ n moves by meeting k) never falls as k grows; expected end rate = start + Σ expected moves; the end-rate distribution matches the scenario weights: P(end ≤ x) = Σ_s P(s)·P(end ≤ x | s).
5. **Path dependence.** Moves cluster: build one path per scenario (soft landing gradual; hard landing front-loaded, larger, possibly intermeeting; reacceleration hold or hike; stagflation hold with two-sided risk), not independent coin flips per meeting.
6. **Anchor translation** onto a settle-ready series:
   - bis:WS_CBPOL/M.US — monthly end of period; BIS records the range midpoint (upper bound − 0.125).
   - fred:FEDFUNDS — monthly average effective rate; sits inside the range and, in the month of a move, averages the old and new levels.
   - bis:WS_CBPOL/M.XM (deposit facility rate from 18 Sep 2024, MRO before), bis:WS_CBPOL/M.JP, bis:WS_CBPOL/M.CN (read which instrument the stored page names).
   - fred:DFEDTARU and fred:ECBDFR are daily series stored as months: read them; they settle only by hand.

## 2. Market-implied paths

- **Fed funds futures** (CME): price = 100 − the month's average effective rate (EFFR). For a meeting on day d of an N-day month, pre-meeting rate r0 (from a no-meeting month's contract) and F = 100 − price: post-meeting rate r1 = (N·F − d·r0)/(N − d); P(25 bp cut) ≈ (r0 − r1)/0.25 (above 1 implies part of a 50 bp move). The EFFR sits a few bp inside the range: compare changes, not levels.
- **CME FedWatch** applies this method and shows the range distribution *after* each meeting, cumulative over earlier meetings; difference consecutive meetings for per-meeting moves. Record the fetch date.
- **SOFR futures / OIS** price the path beyond about six months; they carry term and risk premia, so read them as consensus plus premium, not an expectation.
- **ECB**: €STR OIS via S2 reports. **BOJ**: TONA OIS hike odds (S2). **PBoC**: no liquid policy futures; read 1-year CGB and NCD yields and DR007/FR007 swaps (CFETS, ChinaBond: S1 market data) and sell-side calls (S2).
- **Prediction markets** (`prediction-markets` skill): match resolution wording first (upper bound vs midpoint, move size, intermeeting moves).
- **Divergence rule**: when market and official paths differ by ≥ one move by the horizon, record both and name the data that would close the gap; never average them.

## 3. Policy-rule cross-checks

Rules describe; they do not forecast. Use them to say whether the rate is high or low against the bank's own estimates and which way the gap pushes.
- **Taylor (1993)**: i = r* + π + 0.5(π − π*) + 0.5·y (y = output gap, %). **Unemployment form** (Fed Monetary Policy Report rules, Okun coefficient ≈ 2): (u* − u) replaces 0.5·y; the balanced-approach rule uses 2(u* − u). **Inertial**: i_t = 0.85·i_(t−1) + 0.15·(rule rate) — verify weights in the current MPR.
- **Inputs**: π = fred:PCEPILFE#yoy, π* = 2; r* = SEP longer-run median − 2, or NY Fed Laubach–Williams / Holston–Laubach–Williams (report a range); u = fred:UNRATE, u* = SEP longer-run median or CBO's noncyclical rate.
- **Published prescriptions** (S1): Atlanta Fed Taylor Rule Utility, Cleveland Fed simple rules, the MPR rules table — fetch rather than recompute.
- **Reading**: give the range over 2–3 input choices. Actual above the whole range and the range falling → cuts fit; inside → hold. A persistent gap describes the committee (risk management, inertia), not an error corrected on a date. ECB: an HICP + output-gap rule helps; BOJ/PBoC: direction only.

## 4. Federal Reserve

- **Mandate**: maximum employment and stable prices; 2% PCE inflation (Statement on Longer-Run Goals; read the current version).
- **Instruments**: the 25 bp target range (via IORB and ON RRP); the balance sheet (fred:WALCL; a runoff change is not a rate move); guidance.
- **Who decides**: 12 voters — 7 governors, the NY Fed president, 4 rotating presidents (rotation each January); all 19 participants submit SEP projections. Fetch the roster. Chair and governor term ends, nominations and confirmations are regime risks.
- **Signal hierarchy** (strongest first): (1) the statement — diff it against the last one, especially guidance phrases; (2) SEP — median dot by year, dispersion, how many sit at or below the median; the longer-run dot is nominal neutral; (3) the chair — press conferences, Jackson Hole, semiannual testimony with the MPR; (4) minutes, three weeks later — count quantifiers ("many", "several", "a few"); (5) vice chair, governors, NY Fed president; (6) other voters; (7) non-voters.
- **Blackout**: from the second Saturday before a meeting through the day after it. The last pre-blackout speeches are the latest signals; media reports in it (S2) are not decisions.
- **What moves it**: core PCE and its CPI/PPI inputs; payrolls, unemployment, claims; ECI and hourly earnings; expectations (fred:MICH, fred:T5YIFR, SPF); financial conditions (fred:NFCI, fred:BAMLH0A0HYM2).
- **SEP error table**: each SEP publishes historical projection-error ranges (S1); use them to set the width of 1–3-year distributions — far wider than the dot dispersion.
- **Traps**: dots read as forecast or commitment → individual "appropriate policy" views, non-voters included; a median moved by one participant read as a committee shift → count the distribution; "data-dependent" read as no information → list the data the statement and chair named; intermeeting moves ruled out → rare and crisis-driven (2001, 2008, March 2020): small tail in crisis scenarios only.

## 5. European Central Bank

- **Mandate**: price stability first — 2% HICP, symmetric, medium term (2021 review, 2025 assessment).
- **Instruments**: the deposit facility rate steers (bis:WS_CBPOL/M.XM, fred:ECBDFR), MRO and marginal lending set relative to it; APP/PEPP runoff; TPI against unwarranted spread widening.
- **Who decides**: the Governing Council (Executive Board plus euro-area governors voting in rotation). Meetings every six weeks with a same-day press conference; the account about four weeks later; a quiet week before each meeting.
- **Projections**: quarterly (Eurosystem staff June/December, ECB staff March/September), conditioned on market rates; the inflation projection two years out vs 2% is the most cited input.
- **Reaction function** (stated since 2023): inflation outlook, underlying inflation, strength of transmission. Data: HICP flash (Eurostat), core and services HICP, the negotiated-wage indicator and wage tracker, Bank Lending Survey, PMIs, the euro (bis:WS_EER/M.R.B.XM).
- **Members**: map each governor from dated speeches; never infer hawk/dove from nationality. Post-meeting "sources" stories (S2) preview the next debate. Consensus: Survey of Monetary Analysts and ECB SPF (S1 publisher, REPORTED values).
- **Traps**: BIS euro-area rate before 18 Sep 2024 read as the DFR → it is the MRO, use fred:ECBDFR; aggregates read as fixed → they change with enlargement; flash HICP read as final; a neutral point read as consensus → the staff range is wide.

## 6. Bank of Japan

- **Mandate**: price stability; 2% CPI target (2013 joint statement with the government).
- **Instruments**: the uncollateralized overnight call rate (bis:WS_CBPOL/M.JP) since the exit from negative rates and yield-curve control; the JGB purchase reduction plan; ETF holdings.
- **Who decides**: nine-member Policy Board (governor, two deputies, six members), majority vote, dissents published. Eight two-day meetings a year; Summary of Opinions about a week later; minutes after the next meeting; Outlook Report meetings carry the board's median forecasts; Tankan survey quarterly (S1).
- **Key data**: shunto (Rengo tallies from March, final in July; base pay matters); services prices; Tokyo CPI at the end of the reference month (leads national); national CPI — "core" excludes fresh food only, "core-core" excludes energy too; BOJ trimmed-mean, weighted-median and mode measures; the yen (fred:DEXJPUS) via import prices; MOF intervention amounts (S1).
- **Signals**: governor's press conference and Diet testimony; pre-meeting Nikkei/Jiji/Bloomberg reports (S2 intent, not decisions). Prior to verify: the BOJ has surprised markets more often than the Fed (2016 negative rates, 2022 yield-curve band change).
- **Traps**: Japan "core CPI" read as US core → it includes energy; energy subsidies switching on/off read as underlying change → read core-core; a weak yen read as only inflationary → it also drives political pressure and intervention.

## 7. People's Bank of China

- **Mandate**: a stable currency to promote growth (PBoC Law); in practice growth, employment, prices, the balance of payments and financial stability. Decisions follow the State Council and Party leadership (Central Financial and Economic Affairs Commission, Central Financial Commission): read the political calendar first.
- **Instruments, in hierarchy** (verify on pbc.gov.cn; the framework keeps changing): (1) the 7-day reverse repo rate, declared the main policy rate; (2) LPR 1-year/5-year, quoted on the 20th, normally moving with the 7-day rate; (3) RRR (降准), a quantity tool paired with or substituting for rate cuts; (4) MLF and outright reverse repos, government-bond trading, PSL, structural relending (再贷款), window guidance; (5) deposit-rate guidance, following LPR moves to protect margins; (6) the CNY fixing — an FX constraint on easing.
- **Communication**: quarterly MPC communiqué (货币政策委员会例会) and Monetary Policy Report (货币政策执行报告); governor's forum speeches; State Council executive meetings; joint PBoC–NFRA–CSRC press conferences; 金融时报 (Financial News, run by the PBoC) often pre-signals. Stance words: 稳健 vs 适度宽松, 加大逆周期调节, 降准降息, 择机.
- **Political calendar** (each a decision point): Politburo economic meetings (typically late April, late July; December sets next year's tone); Central Economic Work Conference (December); NPC (March) — Government Work Report targets for GDP, CPI, deficit ratio, local special bonds, ultra-long special treasury bonds; NPC Standing Committee sessions (about every two months) approve budget revisions and debt quotas; plenums and Five-Year Plans. Packages tend to follow these meetings or a data shock.
- **Data**: lags and caveats in [nowcasting-and-releases.md](nowcasting-and-releases.md). Cross-check smooth GDP prints (nowcasting §5b); the budget deficit ratio understates the augmented deficit (IMF Article IV, REPORTED).
- **Anchors**: China CPI bis:WS_LONG_CPI/M.CN.771 or imf:CPI/CHN.CPI._T.YOY_PCH_PA_PT.M; bis:WS_CBPOL/M.CN (if its stored definition is not the instrument asked about, the PBoC announcement is a manual anchor); annual growth wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN lags 1–2 years and settles by hand, quarterly NBS prints are web-only; PPI, TSF, M2, LPR via data_search ("China producer price index", "China total social financing", "China loan prime rate").
- **Traps**: an RRR cut read as a rate cut → check the 7-day rate and LPR; a Politburo wording change read as a package → wait for quotas and amounts (NPCSC approvals, MOF issuance); an unchanged LPR read as no easing → check RRR and structural tools.

## 8. Other banks (same template)

BoE (bis:WS_CBPOL/M.GB; MPC vote splits are published: a close split is a strong signal), Bank of Canada (bis:WS_CBPOL/M.CA), RBA (bis:WS_CBPOL/M.AU), Bank of Korea (bis:WS_CBPOL/M.KR), SNB (bis:WS_CBPOL/M.CH), Banxico (bis:WS_CBPOL/M.MX), RBI (bis:WS_CBPOL/M.IN), BCB (bis:WS_CBPOL/M.BR): record mandate, decision body and vote disclosure, projection rounds, market-pricing source.

## 9. Actor fields for the simulation

For each decision-maker — chair/governor, each voting member or bloc, the finance ministry/Treasury, the head of government where the bank is not independent, and the market as one actor — record: role and vote this year; term end and reappointment path; stated objective weights (inflation, employment, growth, financial stability, FX); a dated bias quote and the data they cite; dissent record and credibility (guidance followed by action); constraints (mandate, independence, political pressure, fiscal or FX dominance); red lines and the triggers that flip them; the next decision points they influence. Relationships: chair ↔ committee (agenda power), government ↔ bank (appointments, pressure), bank ↔ market (guidance credibility), cross-border (Fed moves constrain the PBoC and BOJ through FX).
