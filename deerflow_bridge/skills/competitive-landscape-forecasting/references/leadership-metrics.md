# Leadership metrics: turning "who leads" into a contract that can settle

Load this when fixing the leadership metric for a market type, weighting a multi-criteria prompt, or reconciling trackers, currencies and fiscal calendars. It teaches methods only. Every threshold below is a template or a stated convention, not a current fact.

## 1. The contract (write it before the first search)

| Field | Decide | Default when the prompt is silent |
|---|---|---|
| Contenders | Named set plus "field" | Today's top 3–5 on the primary metric, plus a field for entrants, merged entities and unlisted firms |
| Primary metric | One measurable quantity | The market-type default in §2 |
| Perimeter | Product scope, geography, customer type, captive vs merchant, consolidated vs proportional | Global, merchant (external) sales, consolidated |
| Unit and currency | Units, bits, GWh, USD | Flows in USD at period-average FX; stocks at the resolution-date rate |
| Period | Calendar year, quarter or point in time | "By YEAR": the full calendar year for flows; Dec 31 for ranks and stocks; the last close of YEAR for market cap |
| Settling source | The document class that will settle it, plus one fallback | Company filings for each contender's numerator; one named tracker for the market total |
| Comparator | #1, top-k, share ≥ x, ratio to #2, or ahead of a named rival | #1 |
| Vintage | First print or latest revision | The latest print available at resolution, with its edition recorded |
| Tie rule | What counts as a tie | A gap smaller than the spread between two trackers is inside measurement error: the contenders' S1 numerators on one perimeter decide; if they are unavailable, report a tie |

Wording ladder for vague verbs:
- 领先 / lead / be number one → #1 on the primary metric.
- 主导 / dominate / 霸主 → state a convention, such as #1 with share ≥ 40% and at least 1.5× the #2. Label it the report's convention, not a standard. Use the prompt's own threshold when it gives one.
- 第一梯队 / top tier / top 3 → top-k by the metric. Set tier boundaries at metric gaps, not by prestige.
- 赶超 / overtake by YEAR → say which question it is:
  - "ever": ahead in any quarter before Dec 31 of YEAR;
  - "state": ahead for full-year YEAR.
  In volatile markets "ever" is much more likely than "state". Never merge the two questions.
- A country "leading" in AI, quantum or chips → a composite or a named milestone (tech-race-indicators.md).

## 2. Defaults by market type

Each block gives the primary metric, a cross-check, the S1/S2 source classes, and traps written as misreading → discriminating observation.

**Commodity memory (DRAM, NAND)**
- Primary metric: quarterly and annual merchant revenue share.
- Cross-checks: bit-shipment share, wafer capacity by node (wafer starts per month), inventory weeks.
- Sources:
  - earnings releases and filings, using the memory lines rather than a conglomerate's division totals;
  - trackers: TrendForce/DRAMeXchange, Omdia, Gartner;
  - WSTS for market totals;
  - Korea's monthly chip exports (MOTIE, Korea Customs Service) as a fast proxy;
  - Chinese makers are often unlisted: use prospectuses if filed, CSIA, and trade press (REPORTED).
- Traps:
  - A revenue rank read as structural → compare bit share with the price cycle. Contract-price trackers are closest; fred:PCU33443344#yoy is a coarse US proxy.
  - One quarter's flip read as a trend → use trailing four quarters.
  - Non-calendar fiscal years (Micron's, for example) read as calendar → rebuild calendar quarters.

**HBM and other qualified memory**
- Primary metric: HBM revenue or bit share, by generation.
- Cross-checks: qualification status at each accelerator customer for each generation; supply agreements booked ahead.
- Sources: supplier and customer earnings calls (S1 statements); customer product launches; trackers (REPORTED).
- Traps:
  - "Sampling" or "passed qualification" read as volume → wait for customer-confirmed shipments in a named product.
  - A generation lead read as durable → every generation re-runs qualification.
  - "Sold out" read as share → a sold-out supplier with less capacity still loses share.

**Foundry and logic**
- Primary metric: foundry revenue share. State whether it covers pure-play only or includes IDM foundry units.
- Cross-checks: leading-edge capacity (wafers per month at a node class); customer products in volume at that node.
- Sources: filings with revenue by node and platform; trackers (TrendForce, Counterpoint); teardowns (S3).
- Traps:
  - Node names read as equal technology → compare published density and performance, and customer adoption.
  - An IDM's internal transfers read as foundry revenue → check the segment note.
  - Announced fabs read as supply → stage them (see persistence-and-share-dynamics.md §5).

**Semiconductor equipment and materials**
- Primary metric: revenue share per tool segment (lithography, etch, deposition, inspection, test).
- Cross-checks: backlog; installed base; China's share of revenue, which measures export-control exposure.
- Sources: filings; SEMI equipment billings and fab-spending reports; China customs equipment imports (HS 8486).
- Trap: China pull-in orders read as lasting demand → check backlog and changes to export licences.

**Cloud infrastructure**
- Primary metric: cloud infrastructure services revenue share. Name the tracker's definition: IaaS, PaaS, hosted private.
- Cross-checks: company-disclosed cloud revenue and growth; capex; remaining performance obligations.
- Sources:
  - filings and earnings calls;
  - trackers: Synergy, Canalys, Gartner IaaS;
  - China: the IDC China public-cloud tracker and CAICT;
  - usgov:bea/value_added_by_industry/514 as a US demand proxy (needs a BEA key).
- Traps:
  - Segment names read as cloud → read the segment definition; some segments bundle SaaS, licences or servers.
  - Growth leadership read as share leadership → share moves with absolute USD gains, not percentages.
  - A global rank read as the China rank → rank China separately; a regional leader can differ from the global table.

**AI labs and frontier models** (multi-criteria by nature; see §3)
- Components:
  - capability: independent evaluation ranks;
  - commercial: revenue, paying customers;
  - compute: controlled accelerators, or MW under contract;
  - adoption: API usage, weekly active users.
- Sources:
  - model and system cards (S1 claims);
  - independent evaluators: government AI institutes, academic benchmark maintainers, public preference arenas with style control;
  - filings of listed parents.
  - Private-lab revenue and compute figures are usually REPORTED from press or investor letters.
- Traps:
  - A self-reported score read as a rank → independent runs at equal settings, on fresh or held-out tests released after the training cutoff.
  - Leaderboard #1 read as a lead → ranks inside the confidence interval are ties.
  - A point-in-time rank read as settled → ranks churn with every release. Resolve on a stated snapshot date or the final-quarter average.
  - Annualized run-rate read as annual revenue → label it.

**Open-weight and open-source AI**
- Primary metric: rank of the best open-weight model on independent evals.
- Cross-checks: derivative models; enterprise deployments; licence terms.
- Traps:
  - Downloads read as adoption → automated pulls inflate counts; look for derivatives and deployments.
  - "Open" read as one category → separate open-weight, restricted-licence and OSI-open models.

**Consumer platforms**
- Primary metric: monthly or daily active users, as each company defines them; paid subscribers.
- Cross-checks: engagement time; revenue per user; third-party panels (S3).
- Trap: different "active" definitions read as comparable → align the definitions, or rank on revenue.

**EVs**
- Primary metric: sales units with an explicit perimeter:
  - BEV only, or NEV (BEV + PHEV);
  - wholesale, retail or registrations;
  - global or one country;
  - with or without exports.
- Sources:
  - company monthly delivery releases;
  - China: CPCA (乘联会: retail, wholesale), CAAM (中汽协: production and sales including exports), MIIT, and insurance registrations (上险量, S3);
  - EU: ACEA;
  - US: company releases and registration-data vendors (S3).
- Traps:
  - A BEV vs NEV perimeter mismatch reverses rankings between global makers → state the perimeter.
  - Wholesale read as consumer demand → compare retail sales and dealer inventory.

**Batteries**
- Primary metric: EV battery installations in GWh (SNE Research for global; 中国汽车动力电池产业创新联盟 for China).
- Cross-checks: shipments including energy storage; production; capacity.
- Traps:
  - Shipments read as installations.
  - EV-only and EV-plus-storage rankings read as the same → they differ.
  - China-only rankings read as global.

**IPO league tables (A-share, Hong Kong)**
- Primary metric: gross proceeds at pricing (募资总额), counted by listing date (上市日) within the window. State the venue (main board, STAR, ChiNext, BSE, HKEX) and how over-allotment is treated.
- Sources:
  - exchange statistics and announcements: SSE, SZSE, BSE, HKEX;
  - CSRC registration decisions;
  - the prospectus (招股说明书) and listing announcement (上市公告书);
  - Wind and Choice compilations (S2/S3).
- Traps:
  - Planned raise (拟募资) read as proceeds → use the final pricing announcement.
  - An A+H listing read as one IPO → rank each venue separately unless the question says combined.
  - A registration read as a listing → stage it. A-share: 受理 → 问询 → 上市委 → 注册 → 发行 → 上市. Hong Kong: application proof filed → listing hearing → pricing → listing. Take stage odds from financial-markets-forecasting.

**Market-cap and valuation rankings**
- Primary metric: market cap = Σ over share classes (shares outstanding × that class's close) on the resolution date, in USD at that day's rate.
- Cross-checks: free float; ADR ratios.
- Traps:
  - A private round's post-money read as market cap → keep private valuations in a separate list.
  - Dual-class or ADR miscounts → check share counts in the latest filing.

## 3. Multi-criteria prompts

1. List the criteria the prompt's noun implies. "AI leader" implies capability, compute, commercial and adoption; "cloud leader" puts revenue first.
2. Keep 2–4 criteria that can be measured for every contender, each with a settling source.
3. Fix integer weights at plan time, in the leadership KIQ's wording and the scenario theses, justified by the noun. Write them once. Do not tune them after seeing results.
4. Score each criterion by rank (first place = n points, last = 1), or by ratio to the leader for frontier metrics. Avoid min–max scaling of noisy numbers.
5. Report the composite and every component. A contender missing a component is flagged, not scored zero.
6. Sensitivity: move 20 weight points between the top two criteria. If #1 flips, say so and name who leads on the primary metric alone; add no new probability.
7. Ambiguity at resolution:
   - the primary metric decides;
   - if its source is unavailable, use the named fallback;
   - if both fail, report "unresolvable on contract" rather than switching metrics.

## 4. Recording findings so they anchor

Finding line: `- <contender> <metric> = <value> <unit, currency>, <period>, perimeter <...>, settling document and edition [S<n>] (VERIFIED|REPORTED)`. A share, rank or gap to #1 that you compute is your calculation: write it as a separate REPORTED finding that names its numerator, denominator and their markers.

Binary-ready statements name one metric, one threshold, one period and the settling document class:
- "<X>'s <metric> share is at least <s>% in <period> per <source>."
- "<X> ranks #1 by <metric> for calendar <YEAR> per <source>."
- "<X>'s <metric> exceeds <Y>'s in <period> per <source>."

Rank metrics are rarely official catalog series. Anchor the official conditions separately:
- period-average FX: bis:WS_XRU/M.CN.CNY.A, bis:WS_XRU/M.JP.JPY.A, bis:WS_XRU/M.XM.EUR.A;
- US chip prices: fred:PCU33443344;
- US chip output: fred:IPG3344S;
- semiconductor equities: fred:NASDAQSOX.

## 5. Currency, calendars and revisions

- **Convert:** flows at the period-average rate; point values such as market cap at that day's rate (daily: fred:DEXCHUS, fred:DEXJPUS). For KRW and TWD, use data_search with "Korean won US dollar exchange rate" and "New Taiwan dollar exchange rate".
- **Constant currency:** report constant-currency growth beside USD growth. A currency move can flip a USD rank with no change in units.
- **Fiscal calendars:** name each contender's fiscal year-end. Rebuild calendar years from quarters before ranking.
- **Tracker revisions:**
  - record the tracker edition;
  - keep one tracker for the whole series;
  - splice two trackers only with an overlap year that shows the level difference.
- **Chinese terms:** 营收/营业收入 revenue; 出货量 shipments; 销量 sales (批发 wholesale, 零售 retail); 装机量 installations; 产能 capacity; 市占率/份额 share; 募资额 proceeds; 市值 market cap; 排名 rank.

## 6. Cross-market traps

- Installed-base share read as share of new demand → compute the share of incremental demand. Future installed share converges toward it.
- A regional rank read as global → rank each region, and combine only if the contract says global. China and ex-China markets often have different leaders.
- Captive (internal) consumption counted in a merchant market → exclude it, or state that it is included.
- An announced merger read as combined share → combine only after closing. A pending deal carries approval odds.
- Revenue counted at two value-chain stages (module and chip) → rank within one stage.
- A tracker's free summary read as its full table → cite the table actually fetched, with its edition. Summaries often round or omit the "others" share that the field needs.
