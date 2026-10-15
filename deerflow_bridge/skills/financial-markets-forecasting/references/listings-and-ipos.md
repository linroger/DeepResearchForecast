# Listings and IPOs: staged pipelines, timelines, ranking conventions

Load this for IPO timing, size or ranking questions on A-share, Hong Kong or US venues. A listing is a staged pipeline. Stage every candidate from the venue's own dated status page (S1), then convert stages into odds. **Every rule and duration below is a prior to verify against the current rulebook.** Listing rules change often, so record the rule's source and date.

## 1. The probability frame

- **Stage arithmetic.** P(lists by D) = P(clears every remaining stage | current stage) x P(the remaining time fits before D).
- **Stage-conditional rates from the venue's own cohort.** Take applications that reached stage s in a past window. Record the share that listed, the share terminated or lapsed, and the median days from s to listing. If the page cannot be counted within budget, use S2 year-end tallies (accepted, approved, registered, listed, terminated) labelled REPORTED.
- **Correlated gating.** A regulator's pace-setting (window guidance) moves the whole pipeline together. Never multiply candidates' odds as if independent. Make the pace regime a scenario driver.
- **Market gating.** IPO issuance is procyclical: windows close in drawdowns and high-volatility spells (widely documented). Condition on the index level and the volatility regime of the venue.
- **Size.** Final proceeds = offer price x shares offered, plus the over-allotment if exercised. The planned raise in the prospectus is a target, not the result. A-share actual raises can exceed it (超募) or fall short.

## 2. Mainland China: registration-based system (注册制)

**Venues.**
- **SSE STAR Market (科创板):** registration since 2019.
- **SZSE ChiNext (创业板):** registration since 2020.
- **Beijing Stock Exchange (北交所):** opened in late 2021.
- **SSE and SZSE main boards:** full registration from February 2023.

**Stage ladder.** Status labels are those of the SSE, SZSE and BSE review pages; verify the exact wording.
1. **Tutoring filing (辅导备案)** with the local CSRC bureau, then tutoring acceptance (辅导验收). The minimum tutoring period is typically about three months.
2. **Accepted (已受理)** by the exchange.
3. **Inquiry (已问询):** written rounds and responses.
4. **Listing committee meeting (上市委会议):** passed (通过), not passed (未通过) or deferred (暂缓审议). Exchanges announce meetings shortly ahead.
5. **Submitted for registration (提交注册).**
6. **Registration effective (注册生效).** The CSRC decides within 20 working days, excluding time the issuer takes to supplement.
7. **Issuance:** the registration decision is valid for 12 months. Then preliminary price inquiry with institutions (初步询价), pricing, online and offline subscription, allotment.
8. **Listing (上市):** usually weeks after registration; measure from recent cohorts.

**Side statuses.**
- **Suspended (中止):** for example the filing's financial statements went stale (they expire after about six months, extendable by about three), or an intermediary is under investigation.
- **Terminated (终止):** withdrawn (撤回), not passed, or not registered (不予注册).

**Clocks versus elapsed time.** The statutory review and registration limits (a total of about three months; verify in the exchange's 发行上市审核规则) exclude the issuer's response time and suspensions. Elapsed time from acceptance to listing is therefore usually far longer: take it from cohorts, not from the rule.

**Pace regime (precedents to verify).**
- The CSRC has slowed or suspended IPOs in weak markets several times since the 1990s; long pauses include 2012-2014 and mid-2015.
- It announced a phased tightening of IPO pace in August 2023.
- The April 2024 State Council capital-market opinions (新国九条) raised listing standards and tightened on-site inspections.
- Read the current stance from CSRC press conferences and the monthly counts of acceptances and registrations. A pace shift is an actor decision, so model the CSRC as an actor with a reaction function to index levels and fundraising pressure.

**Lock-ups**, which create dated 解禁 catalysts:
- controlling shareholder and actual controller: 36 months;
- other pre-IPO holders: 12 months;
- strategic placees: at least 12 months;
- STAR and ChiNext sponsor co-investment (跟投): 24 months;
- part of each offline allotment: 6 months.

Exchanges and cninfo publish restricted-share release notices (限售股上市流通公告).

**Price limits** (they shape listing-day market cap):
- STAR, ChiNext and the main boards (since the 2023 reform): no daily limit for the first five trading days; then ±20% on STAR and ChiNext, ±10% on the main boards.
- BSE: no limit on day one, then ±30%.

**Sources.**
- S1: CSRC registration approvals (注册批复) and press conferences; SSE and SZSE project review pages (项目动态); BSE review updates; cninfo (巨潮资讯网) for 招股说明书, 发行公告 and 上市公告书; exchange monthly statistics.
- S2: Securities Times, Caixin and vendor-based year-end IPO reviews (REPORTED).

## 3. Hong Kong (HKEX)

**Stages.**
1. **A1 filing.** The listing application is filed and an Application Proof is published on HKEXnews. It lapses after six months unless refiled, so refilings are common.
2. **Review.** Listing Division review and comment rounds.
3. **Hearing.** The Listing Committee hearing (聆讯) gives approval in principle.
4. **PHIP.** The Post-Hearing Information Pack is published, usually days to weeks before launch.
5. **Offer.** Prospectus and price range; the Hong Kong public offer plus the international placing; cornerstone investors, typically locked for six months.
6. **Pricing and listing,** usually within about two weeks of the prospectus; allotment results are published on HKEXnews.
7. **Over-allotment option:** up to 15% of the offer, exercisable within 30 days.

**Mainland issuers** (H shares, red chips, A+H listings) face extra gates:
- **CSRC filing** under the overseas listing trial measures (effective 31 March 2023). The CSRC publishes its filing notices (境外发行上市备案通知书), and a missing notice blocks listing.
- **CAC cybersecurity review** where required. The one-million-user trigger applies to listings abroad; Hong Kong listings fall under the national-security test (verify the current measures).
- Record both gates as dated stages.

**Specialist routes:** Chapter 18A (pre-revenue biotech) and Chapter 18C (specialist technology, from 2023). Check for any current fast-track arrangements for large A-share companies.

**Lock-ups.** Controlling shareholders may not sell for six months, then may not lose control for a further six.

**Sources (S1):** HKEXnews (披露易: Application Proofs, PHIPs, prospectuses, allotment results); HKEX monthly market statistics; CSRC filing notices.

## 4. United States (SEC; Nasdaq, NYSE)

**Stages.**
1. **Confidential draft registration statement (DRS).** It must become public at least 15 days before the roadshow.
2. **SEC review.** The first comment letter typically arrives about four weeks after filing (widely cited), followed by further rounds.
3. **Public S-1 (F-1 for foreign private issuers)** and S-1/A amendments. An amendment that sets a price range starts the roadshow, typically one to two weeks long.
4. **Effectiveness.** The SEC declares the statement effective on an acceleration request (EDGAR shows an EFFECT notice). Pricing follows that evening, trading the next morning, and the final prospectus is filed as 424B4.
5. **Over-allotment** up to 15% within 30 days. Lock-ups are contractual, typically 180 days, with early releases often tied to earnings.

**Withdrawals and stalls.** A registration withdrawal request (RW) ends the attempt. A public S-1 with no amendment for months is stalled, not pending.

**Shutdown precedent.** SEC reviews pause during a federal government shutdown. Some issuers have used automatic effectiveness 20 days after filing without a delaying amendment (Securities Act section 8(a); 2019 precedent, verify).

**PRC issuers in the US** need the CSRC filing, any triggered CAC review and PCAOB audit-inspection compliance (HFCAA). Record each.

**Not IPOs?** Direct listings, SPAC mergers and uplistings: the settlement contract must say whether they count.

**Sources.** S1: SEC EDGAR full-text search (S-1, F-1, S-1/A, EFFECT, 424B4, RW); exchange listing notices. S2: Nasdaq and NYSE IPO calendars. S3: IPO-research aggregators.

## 5. Size, valuation and ranking conventions

Fix each choice in the settlement contract before ranking. League tables (Dealogic, LSEG, Wind and others) differ on them, so the same "largest IPO" can differ by source.

| Choice | Options | Typical trap |
|---|---|---|
| Size metric | Gross proceeds at the base deal; with greenshoe exercised; net of fees; planned (拟募资) vs actual (募集资金总额) | Planned raise reported as proceeds |
| Share type | Primary (new) vs secondary (selling holders) | Secondary-heavy deals counted as company fundraising |
| Currency | Local currency vs USD at the pricing-date rate | Converting at today's rate |
| Venue counting | A+H or dual listings per venue or combined; listing by introduction (no new shares) | A combined figure ranked against single-venue deals |
| Year assignment | Listing date vs pricing date vs registration date | December pricings that list in January |
| Listing-day market cap | All shares outstanding, every class and restricted shares, times the first-day close; vs offer-price valuation; vs free-float cap (流通市值) | Offer-price valuation reported as market cap; one share class only; ADR ratio ignored |

**Ranking odds** (for example "largest A-share IPOs by end of 2026"):
1. List the candidates: registered issues, committee-passed applications and large accepted applications.
2. Give each P(lists by D) from its stage, and a size distribution anchored on the planned raise. Adjust by the cohort's actual-to-planned ratio in the current regime (REPORTED, computed).
3. Rank with the consistency rules of competitive-landscape-forecasting.

Within a one-year horizon the late-stage pipeline dominates: an application accepted only months before the deadline rarely lists in time. Measure this from the cohort rather than assuming it.

## 6. Catalysts and signposts

- **China:** exchange listing-committee meeting notices; CSRC registration batches; CSRC press-conference statements on IPO pace; monthly acceptance and registration counts.
- **Hong Kong:** hearing passed and PHIP published; prospectus launch; CSRC filing notice for mainland issuers.
- **US:** EDGAR public filing, price-range amendment, EFFECT notice; shutdown risk for SEC staff.
- **All venues:**
  - lock-up expiries (解禁 calendars; US 180-day dates);
  - index seasoning and fast-entry rules for large new listings (check each provider's methodology);
  - the venue's index drawdown and volatility, which gates every window.

## 7. Traps (misreading → discriminating observation)

- **Accepted read as likely to list** → the cohort's termination share and median elapsed time from acceptance.
- **Statutory clock read as elapsed time** → response time and suspensions are excluded; compare the cohort's actual durations.
- **Committee passed read as listed** → registration and issuance can still stall, and a registration decision lapses after its validity window. Look for the issuance announcement.
- **Planned raise read as proceeds** → the final pricing announcement and allotment results; greenshoe exercise notice.
- **Offer-price valuation read as listing-day market cap** → first-day close times all shares; no price limits in the first five A-share sessions.
- **HK A1 filing read as commitment** → lapse after six months, refiling history, hearing status.
- **Public S-1 read as imminent** → price-range amendment and EFFECT notice, not the initial filing.
- **Mainland issuer abroad assumed cleared** → the CSRC filing notice and any CAC review outcome.
- **Many headlines read as many deals** → one issuer's repeated coverage is one candidate; dedupe by issuer and venue.
