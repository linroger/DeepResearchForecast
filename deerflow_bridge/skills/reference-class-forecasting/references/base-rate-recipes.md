# Base-rate recipes

Each recipe: shapes → classes (two or more, chosen by mechanism) → counting rule → data → priors to verify → traps → anchor. Your counts are REPORTED. A prior here is a documented pattern to verify against the named source, never a number to copy.

## 0. Rules for every recipe

- **The unit is the episode** (a cycle, a war, a bill, a ranking window), not the month. Space start points at least one horizon apart.
- **Conditional vs unconditional.** The conditional class starts only from states like today's (level band plus direction) and is the usual anchor; the share of all periods meeting the condition is a sanity check.
- **Report the n you hold.** The base-rate prefetch keeps 30 years of an annual or quarterly series but only the newest 240 monthly observations (20 years). Older cycles need an S1 event list.
- **Censoring and survivorship.** Write "k of n resolved, m open". List from sources that record failures too: all bills, the conflict dataset, the IPO pipeline, rankings as published at each window's start.
- **Small n.** Give k/n and (k+1)/(n+2). With n < 5 the class is a pointer, not an anchor.
- **The forecast stage** already computes each data anchor's unconditional share of historical h-step changes crossing the threshold (30+ samples). Add what it cannot: conditional and event-list classes, regime caveats.

## 1. Macro thresholds and policy-rate paths

**Shapes:** "US CPI below 2.5% by Dec 2027"; "fed funds upper bound at most X at end-2026"; "US recession by 2027"; "PBoC cuts the LPR".

**Classes:**
- A. State frequency.
- B. Transition from today's band and direction to the threshold, within h (ever-touch) or at h (end-state).
- C. Policy cycle: cumulative moves within 12 months of a first cut, insurance vs recession cycles.
- D. Forecaster error: year-ahead misses of SEP medians and WEO vintages give the spread around a published path.

**Data:**
- Inflation: bls:CUUR0000SA0#yoy (headline as published, NSA: the usual settling series); fred:CPIAUCSL#yoy (SA; can differ near a threshold); fred:PCEPILFE#yoy (core PCE, the Fed's target); wb:IMF_WEO_PCPIPCH/USA (annual, for long counts; rows after the latest completed year are projections). China: wb:WB_WDI_FP_CPI_TOTL_ZG/CHN, imf:CPI/CHN.CPI._T.YOY_PCH_PA_PT.M, NBS releases.
- Policy rate: fred:DFEDTARU (target upper limit, steps only at decisions); fred:FEDFUNDS (monthly average effective, not the target); bis:WS_CBPOL/M.US (midpoint); fred:ECBDFR; bis:WS_CBPOL/M.CN with PBoC LPR/RRR notices. Older cycles: the Fed's target-change table and statement archive (S1); class D: the SEP archive.
- Recession: the NBER peak/trough table (S1) or data_search("NBER recession indicator"); fred:SAHMREALTIME (signals at 0.50), fred:T10Y3M, fred:UNRATE; fred:A191RL1Q225SBEA (q/q annualized; two negative quarters is not the NBER rule); wb:WB_WDI_NY_GDP_MKTP_KD_ZG/USA and wb:WB_WDI_NY_GDP_MKTP_KD_ZG/CHN (long annual growth).

**Priors to verify:**
- About a dozen NBER peaks since 1945: an unconditional recession-start hazard near 15% a year. Count it; expansions vary widely.
- 12-month cumulative cuts differ several-fold between insurance and recession cycles; classify each by whether a recession followed.
- Year-ahead SEP and WEO misses are as large as the moves forecast; read the archived vintages.

**Counting rule (illustrative):** starts are years above 4 in wb:IMF_WEO_PCPIPCH/USA (observed rows), at least two years apart. The event is a year below 2.5 within two years. Report k of n, the episode years and any open episode.

**Traps:**
- Average read as target → a target question settles automatically on bis:WS_CBPOL/M.US (range midpoint, end of month: upper bound − 0.125); fred:DFEDTARU keeps end-of-month targets but settles by hand; fred:FEDFUNDS is the average effective rate.
- First print read as final → GDP advance estimates are revised twice; a near-threshold call needs the typical revision size (BEA release history).
- Missing period (e.g. a shutdown gap) → it cannot settle; name the fallback period.
- One class across regimes → split pre/post inflation targeting and the zero-lower-bound years.

**Anchor:** {"series": "bls:CUUR0000SA0#yoy", "period": "2027-12", "comparator": "<", "threshold": 2.5}, units as stored. An ever-touch question needs one anchor per period, or a restatement.

## 2. Policy passage, rules, courts and tariffs

**Shapes:** "Congress passes X by 2028"; "IEEPA tariffs still collected at end-2027"; "the Court rules against Y"; "the NPCSC adopts law Z this year".

**Classes.** Always condition on the stage the item has already reached.
- A. Introduced → enacted: a low single-digit share per Congress (GovTrack and Congress.gov statistics; verify). A floor, rarely the right class.
- B. Stage-conditioned: passed one chamber; leadership or presidential priority; reconciliation. Must-pass vehicles (NDAA, appropriations, the debt limit) pass almost every year, often late through stopgaps.
- C. Executive and trade actions: announced → effective on the stated date → still in force after N months. Count from the Federal Register, USTR, Commerce/BIS and CBP CSMS notices. Pauses, exemptions and extensions are separate outcomes.
- D. Courts: appeals affirmance from the US Courts judicial-business tables. The Supreme Court reverses most cases it hears, often cited near two-thirds or more (Supreme Court Database, SCOTUSblog statistics; verify).
- E. China: NPCSC work-plan items adopted within the year (npc.gov.cn); Five-Year Plan quantitative targets met at plan end, k of n (plan text vs NBS outcomes); MOFCOM and Customs Tariff Commission (国务院关税税则委员会) measures, announced → effective.
- F. EU: proposal-to-adoption durations for comparable files (EUR-Lex procedure files, the Legislative Observatory), split first-reading vs trilogue.

**Counting rule:** items at the same stage and calendar point (session year, months before an election): share enacted or effective by the deadline, open items apart. Hazards cluster before recesses, session ends and fiscal deadlines; pending bills die with the Congress.

**Tariff data:** usgov:treasury/mts_customs_duties (monthly cash, net of refunds, seasonal); fred:B235RC1Q027SBEA (quarterly accrual, long history); fred:IMPCH; bls:EIUIR (import prices, pass-through). Effective rate = duties ÷ goods imports (data_search("US imports of goods customs basis")).

**Prior to verify:** most introduced bills never reach a floor vote, so "no action by the deadline" is the modal outcome (Congress.gov).

**Traps:**
- Announced read as effective or collected → check the notice's effective date and the MTS duty line.
- Paused or narrowed read as repealed → read the product scope of the latest notice.
- Court loss read as the end → stays, remands and other authorities (Sections 232, 301, 122) remain; list fallbacks before scoring "tariffs end".
- China plan targets → expected (预期性) and binding (约束性) targets differ in attainment; classify first.

**Anchor:** events settle on S1 documents: the Public Law number, a Federal Register citation, the opinion, an NPC notice. Quantitative proxies anchor on customs duties.

## 3. Conflict termination, ceasefires and escalation

**Shapes:** "the Russia–Ukraine war ends by end-2026"; "a ceasefire holds 90 days"; "US–Iran direct strikes in 2026".

**Define "end" first:** a signed agreement; a ceasefire holding N days; fighting below a UCDP-style threshold (fewer than 25 battle deaths a year); or capitulation or regime change. Each has its own class and settling source.

**Classes:**
- A. Interstate wars by age (COW Inter-State War data; UCDP/PRIO Armed Conflict Dataset): the annual end rate for wars already this old. Verify the documented falling hazard: wars past their first year end more slowly.
- B. Termination type (UCDP Conflict Termination dataset): agreement, ceasefire, victory, low activity. Many episodes end in low activity without settlement; verify the shares.
- C. Ceasefire durability (ETH/PRIO Civil Conflict Ceasefire dataset; the PA-X agreements database). Fortna's documented finding: stronger terms last longer (buffer zones, monitors, guarantees).
- D. Escalation (COW Militarized Interstate Disputes): few disputes become wars; verify, conditioning on the highest action level and nuclear status.
- E. Negotiation tracks: talks → signed → implemented, over prior rounds of the same pair.

**Data:** UCDP (ucdp.uu.se), COW (correlatesofwar.org), ACLED and ISW/CSIS (S2), government and UN Security Council records (S1). Consequence anchors: fred:DCOILBRENTEU or imf:PCPS/G001.POILBRE.USD.M (Brent), imf:PCPS/G001.PWHEAMT.USD.M (wheat), imf:PCPS/G001.PNGASEU.USD.M (EU gas).

**Counting rule:** interstate wars since 1946 that reached this war's age: the share ending within the next 12 months, by end type, with open cases listed.

**Traps:**
- Tiny n (about a hundred interstate wars since 1816 in COW, far fewer comparable) → combine A with B and C, and widen the range.
- Announcement read as termination → count a ceasefire only when its settling test is met.
- Conflict-years read as episodes → the unit is the war.
- Frozen conflict read as peace → keep "low activity, no settlement" as its own scenario.

**Actor facts for the simulation:** dated terms and red lines; prior ceasefires or deadlines honoured (k of n); domestic constraints (elections, mobilisation, economy); patrons' leverage.

## 4. Technology adoption and capacity build-out

**Shapes:** "EV share of new sales by 2035"; "US battery storage by 2030"; "fault-tolerant quantum by 2030".

**Classes:**
- A. Diffusion analogues: the time from x% to y% of the right denominator, for technologies with similar cost, complements and asset life. Sources: the Comin–Hobijn CHAT dataset, household-adoption histories, IEA Global EV Outlook country series. Our World in Data only maps to them.
- B. Lead-lag geography: the leading market's path, shifted in time (IEA, CPCA/CAAM, ACEA). Check policy and price gaps first.
- C. Stage-conditioned pipeline: announced → financed or permitted → building → commissioned → qualified, with the completion share by stage. Sources: LBNL interconnection-queue studies (a minority of queued capacity reaches operation; verify), NEA approvals vs grid connections, SEMI fab announcements vs production, CNESA tracking.
- D. Roadmap reliability: the share of the same actor's past dated milestones delivered on time, from its own earlier roadmaps (S1 first-party). For quantum, chips, AI labs.

**Counting rule:** fix the denominator (new sales vs fleet, nameplate vs qualified, MW vs MWh); count per country-technology pair (years from 5% to 25% of new sales), keeping stalled, pilot-only and reversed cases.

**Data:** usgov:eia/generating_capacity/BAT, usgov:eia/generating_capacity/SOL, usgov:eia/electricity_sales/VA.COM (data-centre proxy), fred:TOTALSA (vehicle denominator), fred:IPG3344S, imf:PCPS/G001.PLITH.USD.M; China: CPCA/CAAM, NEA, CNESA/CESA, MIIT, CAICT; IEA.

**Priors to verify:**
- Later technologies took off faster (CHAT-based studies); early data cannot fix both an S-curve's ceiling and midpoint.
- Announced capacity overstates built capacity at every stage (LBNL, SEMI): score projects at the stage reached.

**Traps:**
- Sales share read as fleet share → check the denominator.
- Subsidy pull-forward read as trend → find the cliff date and read the month after it.
- Fast adopters only → put stalled technologies in the class.
- Vendor outlook read as base rate → it is a REPORTED projection.

**Anchor:** EIA year-end capacity (period YYYY), or an S1 industry-body figure with its definition.

## 5. Leader persistence and rank changes

**Shapes:** "which US AI lab leads by 2030"; "AI-race ranking in 2028"; "largest A-share IPOs by end-2026".

**Classes:**
- A. Persistence: in a stable-method ranking, the share of non-overlapping h-year windows in which the #1 stayed #1; also the top-k turnover.
- B. Gap closure: the change per year a challenger needs, divided by the largest annual change on record.
- C. Annual maximum: k of n years in which the year's largest item exceeded the threshold (exchange statistics).
- D. IPO stages: accepted → inquiry → listing-committee approval → CSRC registration → listing (SSE/SZSE review-status pages, S1). Regulatory pace shifts are regimes: split there.

**Data:** filings (S1: revenue, capex, shipments); exchange annual IPO tables (SSE, SZSE, HKEX, NYSE, Nasdaq) and CSRC notices; TOP500, WSTS; vendor shares (Synergy, Gartner, IDC, TrendForce: S2/S3, attribute); AI: Epoch AI and the Stanford AI Index (S2), LMArena (S3; short history, method changes).

**Prior to verify:** revenue and installed-base ranks should be stickier than market-value or benchmark ranks. Compute class A on both metrics over one window.

**Traps:**
- Method change → count within one methodology.
- Today's giants only → use the ranking as published at each window's start.
- Two or three windows → use Laplace and widen; do not extrapolate a run.
- Overlapping windows → they inflate n.

**Anchor:** the leadership metric that the competitive-landscape skill fixes, settled on a named S1 table and date.

## 6. Elections and scheduled votes: the class decides the answer

Commonly cited tallies to verify (House Clerk party divisions; Brookings Vital Statistics on Congress):
- The president's party lost House seats in every post-war midterm but 1998 and 2002: about 18 of 20 from 1946 to 2022 (Laplace ≈ 86%).
- It lost House control in midterms where it held the House: about 7 of 12 over the same years (Laplace ≈ 57%).

The classes differ by about 30 points; conditioning on majority size or approval narrows the class and lowers n.

Senate: count by seat class and state partisanship. Certified state returns (S1) settle; a media call does not.

Where a vote is near-certain (e.g. the NPC on government bills), the uncertainty is whether and when the item is tabled.
