# Value chain, sizing and profit pools

Load this when a KIQ must fix an industry perimeter, size a market, reconcile conflicting size estimates, decompose demand or growth, or estimate profit pools and concentration. Every number you write still follows the finding format: number, unit, period, geography, source marker, VERIFIED or REPORTED. Your own arithmetic is REPORTED and shows its inputs.

## 1. The perimeter contract (write it before any number)

A size figure is meaningless until these fields are fixed. Write them as the first finding of a sizing KIQ.

| Field | State | Typical mismatch it prevents |
|---|---|---|
| Object | The unit actually sold or measured: chips, wafers, bits, cell kWh, system kWh, MW of IT load, vehicles, subscriptions | Wafers vs dies vs bits; cells vs packs vs systems |
| Stage | Whose revenue: materials, equipment, components, devices, systems, services, operators | Device sales mixed with foundry or equipment revenue |
| Merchant vs captive | Sold to third parties, or made in-house for own use | In-house accelerators or in-house cells missing from merchant tallies |
| Geography | By production site, by customer location, or by company headquarters | "China output" that includes foreign-owned plants and exports |
| Period | Calendar or fiscal year (name the fiscal year end), quarter, year-to-date | A March-end fiscal year compared with a calendar year |
| Price basis | Ex-factory, distributor, end-user, installed/turnkey; VAT in or out | Cell price vs system price vs EPC price |
| Gross vs net | Before or after rebates, returns, intra-group sales, subsidies | Group revenue that includes sales between subsidiaries |
| Stock vs flow | Annual additions vs cumulative installed base | New installs reported as the installed base, or the reverse |
| Currency and basis | Currency, nominal or real, FX average vs year-end | Local-currency growth read as USD growth |
| Status | Actual, estimate, publisher projection, government target | A target quoted as an actual |

Template: "<object> sold by <stage> producers to <customers>, <geography basis>, CY<year>, <price basis>, <currency> nominal, <status>."

## 2. Segment where behaviour differs, not where labels differ

Split a segment when at least one of these differs: price trend per unit, cycle sensitivity, customer set, technology path, qualification barrier, regulation. Report by segment whenever segments move in opposite directions; one blended growth rate then hides both.

Examples of splits that change conclusions:
- Memory: standard DRAM (spot-sensitive) vs HBM (qualification-bound, contract-priced) vs NAND.
- Logic: leading-edge vs mature nodes (different capacity owners, customers and policy exposure).
- Storage: cells vs integrated systems; utility front-of-meter vs commercial and industrial vs residential.
- EVs: BEV vs PHEV/EREV; domestic sales vs exports.
- Data centres: self-built hyperscale vs colocation vs enterprise; IT load vs facility power.
- Cloud: infrastructure and platform services vs software subscriptions.

## 3. Map the value chain; never add stages

1. List the stages from inputs to end user, each with its unit and revenue concept.
2. For each stage record producer revenue, leading firms and the scarce asset that sets its margin: bottleneck capacity, IP, qualification, licence, standard, customer access.
3. Only value added is additive: value added of a stage = its revenue − inputs bought from upstream stages. Summing stage revenues counts every input again at each later stage; the end-market value already contains the upstream stages.

Double counts seen in real research:
- Chip device sales (WSTS-type totals) plus foundry revenue: foundry revenue is a cost inside fabless device sales.
- Cell plus pack plus system revenue for batteries.
- Accelerator vendor revenue plus server maker revenue plus cloud revenue presented as one "AI market".
- National industry totals built by adding design, manufacturing and packaging/test revenue (for example China's CSIA headline IC-industry sales). Treat such a total as gross output of a chain, not as a chip market, and never compare it with device-sales totals without restating.

Check: a stage's revenue for one perimeter cannot exceed the downstream revenue that contains it, unless exports or inventory explain the gap. If it does, the perimeters differ.

## 4. Demand decomposition

Revenue_t = Σ over end markets m of Units(m,t) × Content per unit(m,t) × Price per content unit(m,t)

- End markets: servers, phones, PCs, vehicles, industrial; or utility, commercial, residential.
- Content per unit: GB of DRAM per server, kWh per vehicle, MW per campus, wafers per accelerator.
- Content growth can offset unit decline; record units and content separately so the forecast can move them separately.

Installed base vs flow:
- Base_t = Base_(t−1) + Shipments_t − Retirements_t.
- Without retirement data, approximate retirements as base ÷ average life and label it an assumption.
- Replacement demand (retirements) and expansion demand (net base growth) respond to different drivers.
- Penetration of sales (flow share) is not penetration of the fleet (stock share). The stock lags the flow by roughly one asset life.

Demand-side check: end-market units × content should match producer shipments to within the change in channel inventory (see the stock-flow identity in cycles-and-capacity.md).

## 5. Triangulate three ways

| Route | Build | Weakness |
|---|---|---|
| Top-down | Official output, shipments, trade or value added (S1) | Coverage thresholds, physical units, value added rather than revenue |
| Bottom-up | Sum of company segment revenues from filings, divided by their combined share | Circular if the share comes from the same research firm as the total |
| Demand-side | Units × content × price (section 4) | Content and price assumptions |

When the routes disagree beyond their stated uncertainty, the cause is usually a perimeter difference (section 1), not an error. Find it before choosing.

## 6. Reconciling conflicting estimates

Work in this order and stop when the gap is explained:
1. Perimeter: object, stage, merchant vs captive.
2. Geography: production vs consumption vs headquarters; exports and re-exports.
3. Period: calendar vs fiscal year, year-to-date vs full year, vintage and revisions.
4. Price basis: producer vs end-user vs installed; VAT.
5. Gross vs net: rebates, intra-group sales, subsidies.
6. Stock vs flow: installed base vs additions; shipped vs installed vs grid-connected.
7. Currency: local vs USD; average vs year-end rate.
8. Real vs nominal.
Then check coverage (association membership, statistical thresholds), method (survey, census, model) and revisions.

Output a reconciled range with each family's basis. Never average estimates built on different concepts. Put the unexplained residual in Conflicts.

Estimate families and independence:

| Family | Tier | Notes |
|---|---|---|
| Statistical office, customs | S1 | Published definitions; coverage limits |
| Regulator or ministry operating statistics | S1 | Check whether an association supplied the figure |
| Company filings, for the company's own figures | S1 | Industry-size claims quoted inside filings or prospectuses belong to the quoted firm's family |
| Industry association | S1 or S2 | Covers its members only |
| Commercial research firm | S3 | Modelled, revised, widely repeated; attribute by name |
| Press-release "market will reach X by year Y at Z% CAGR" | S4 lead | Trace to an origin or drop |

One originator, one year, one number is one family, however many outlets repeat it.

## 7. Growth decomposition and CAGR hygiene

- (1 + g_revenue) = (1 + g_volume) × (1 + g_price), so g_revenue = g_volume + g_price + g_volume × g_price. Report the three contributions separately.
- Split price into like-for-like price change and mix. A higher average price caused by a richer mix is not a price increase.
- Deflate an industry with its own producer price index, not with CPI, and name the index. Quality-adjusted technology indices (US chips: fred:PCU33443344) fall over time even when average selling prices rise, so revenue deflated by them measures quality-adjusted volume, not units.
- CAGR = (V_end / V_start)^(1/n) − 1, with n = years between the endpoints (2025 to 2030 is n = 5).
- Endpoint check: a CAGR that starts at a cyclical trough or ends at a peak overstates the trend. Quote the endpoints with the CAGR.

## 8. Profit pools

Three levels, each telling a different story:
1. Revenue pool: sales by stage.
2. Operating-profit pool: operating income by stage.
3. Economic profit: after-tax operating profit minus a charge on invested capital. Capital-heavy stages can show large operating profit and little economic profit.

Estimating a stage's pool from filings: sum the segment operating income of the firms you can observe, divide by their combined share of that stage's revenue, and state the coverage. For cyclical stages use averages over at least one full cycle and say so. Segment definitions differ between firms and change over time; a restated segment breaks a series.

Where value accrues: name the scarce asset of each stage and ask what could make it abundant (new capacity, standardization, open-source substitution, subsidised entry, an export control that removes a buyer or a supplier). The answer is a forecast driver; record it in Findings with its evidence.

Moat claims must be testable: mechanism → observable behaviour (price premium held through a downturn, share held while rivals cut price) → durability → erosion trigger.

## 9. Concentration, shares, entry and exit

- Every share states its metric (revenue, units, capacity, shipments), perimeter, period and source. Revenue and unit rankings differ when prices differ.
- CRk = sum of the top k shares. HHI = Σ share², with shares in percent (range 0 to 10,000). The 2023 US Merger Guidelines treat an HHI above 1,800 as highly concentrated; use that only as a descriptive marker.
- Share tables from different publishers use different perimeters and rarely sum to 100. Never mix rows from different sources in one ranking.
- Compare at least two dated periods. Share moves during a downturn reveal cost position: low-cost producers usually gain.
- Entry and exit: count entrants, exits, mergers and closures over the last cycle. State-funded entrants may ignore price signals; record the funder.

## 10. Worked mini-example (ILLUSTRATIVE NUMBERS, invented for the arithmetic only)

Fictional question: the stationary-storage industry of "Country A" in CY2025. None of these figures describes any real market.

Three figures are found:
- F1, an industry association: "storage cell shipments 100 GWh". Cells shipped by Country A producers, exports included.
- F2, a research firm (S3): "storage market USD 15 billion". Projects installed in Country A, turnkey end-user value including EPC.
- F3, an official series: "new grid-connected storage 55 GWh". Installed and connected in Country A.

Reconciliation onto one perimeter, "systems installed in Country A, CY2025":

| Step | Finding | Effect |
|---|---|---|
| Perimeter | F1 counts cells; F2 and F3 count installed systems | Restate F1 before comparing |
| Geography | 35 GWh of F1 cells were exported | 65 GWh of cells stayed in Country A |
| Stock-flow and timing | 65 GWh shipped domestically vs 55 GWh connected | 10 GWh sits in integrator inventory or awaits connection; check inventory and connection-queue evidence |
| Price basis | F2 ÷ F3 = USD 15 billion ÷ 55 GWh | Implied turnkey price about USD 273 per kWh (REPORTED); compare with tender prices |

Reconciled statement: 55 GWh connected in CY2025 (official), 10 GWh shipped but not connected, turnkey value about USD 15 billion (research firm, S3). Wrong statement: "a 100 GWh market worth USD 15 billion".

Value chain and profit pool on the 55 GWh installed:

| Stage | Price basis (USD per kWh) | Revenue (USD bn) | Value added (USD bn) | Operating margin | Operating profit (USD bn) |
|---|---|---|---|---|---|
| Cells, including their materials | 50 | 2.75 | 2.75 | 4% | 0.11 |
| Systems (cells plus converters, controls, enclosure, integration) | 150 | 8.25 | 5.50 | 8% | 0.66 |
| EPC and turnkey delivery | 273 | 15.00 | 6.75 | 5% | 0.75 |

- The revenue column sums to USD 26 billion, which is meaningless: it counts cells three times and systems twice. The end-user market is USD 15 billion, and the value-added column sums to exactly that.
- The operating-profit pool is USD 1.52 billion. Cells hold 18% of value added (2.75 ÷ 15) but only 7% of the profit pool (0.11 ÷ 1.52).

Growth decomposition for the next year (also invented): installations rise 40% to 77 GWh and the turnkey price falls 25% to about USD 205 per kWh. Revenue = 15 × 1.40 × 0.75 = USD 15.75 billion, up 5%. Contributions: volume +40 points, price −25 points, interaction −10 points (0.40 × −0.25). "Installations up 40%" and "market up 5%" are both true; a writer must say which one is meant.

Concentration (invented): system-integrator shares by GWh of 40, 25, 15, 10 and 10 give CR3 = 80 and HHI = 1,600 + 625 + 225 + 100 + 100 = 2,650. Revenue shares can rank differently if the leader sells cheaper systems.

From finding to anchor: the reconciliation tells the forecast stage which series can settle a binary question. Here the official grid-connected series would anchor "new grid-connected storage in Country A in CY2026 is at least T GWh", with series, period (CY2026, full year), unit (GWh, newly connected, not cumulative) and threshold T taken from the run's evidence. F1 and F2 cannot anchor it: one measures cells shipped, the other a modelled value.
