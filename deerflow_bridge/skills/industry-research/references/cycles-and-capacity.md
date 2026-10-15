# Cycles, capacity and stock-flow

Load this when a KIQ must place an industry in its cycle, stage a capacity pipeline, run a stock-flow check, locate the marginal producer or judge order and backlog quality. Numbers in the tables below are invented to show the arithmetic; they describe no real market.

## 1. The chain and its lags

orders → backlog → production and utilization → shipments → sell-through → inventory (producer, distributor, customer) → price → margin → capex → capacity, after a build lead time → price again.

- Upstream, high-frequency readings turn first: lead times, spot prices, book-to-bill, early-month export data (Korea, Taiwan), customs volumes.
- Inventory leads price, price leads margin, margin leads capex, and capex leads capacity by the build lead time. A glut is often built during the previous shortage.
- Record the lag you observe between two series as REPORTED, with both series and the window.

## 2. Stock-flow

Shipments_t = Consumption_t + ΔInventory_t, at every layer (producer → distributor → device maker → end user).

Inventory metrics:
- Days of inventory = inventory ÷ cost of goods sold × days in the period.
- Weeks of supply; inventory-to-shipments ratio (US Census M3; Statistics Korea inventory and shipment indices).
- Level vs change: falling inventory is a recovery signal only once the level nears normal. Rising inventory from a lean level can be healthy restocking.

Illustrative bullwhip (invented):

| Year | Consumption | ΔInventory | Shipments | Shipments y/y |
|---|---|---|---|---|
| 1 | 100 | +10 | 110 | |
| 2 | 105 | 0 | 105 | −4.5% |
| 3 | 108 | −5 | 103 | −1.9% |
| 4 | 112 | +4 | 116 | +12.6% |

End demand grew every year while shipments fell twice and then jumped. Reading shipments as demand gets the sign wrong in years 2 and 3 and the size wrong in year 4.

Partial-period traps:
- Year-to-date cumulative releases (累计, common in China): a monthly value obtained by differencing is REPORTED.
- January and February are released together by China's NBS; Lunar New Year moves activity between them.
- Never annualize a run-rate, and never treat nine months as a full-year actual.

## 3. The six cycle clocks

| Clock | Mechanism | Read it from | Misreading → discriminating observation |
|---|---|---|---|
| End-demand | Final purchases and usage by end users | End-market units (US vehicles fred:TOTALSA), retail sales, registrations, electricity use (usgov:eia/electricity_sales/US.COM), active users, sell-through | Factory builds read as end demand → registrations or retail sales |
| Inventory | Restocking and destocking across layers | Days of inventory at producers and customers, inventory-to-shipments ratios, distributor stock | Falling inventory read as recovery → level vs normal days of inventory |
| Capacity | Capex → capacity → utilization | Utilization (fred:CAPUTLG3344S, fred:TCU, China NBS 产能利用率), capex ÷ revenue, equipment orders and billings, tool lead times | Rising capex read as strong demand → capex ÷ revenue vs its history, and who pays for it |
| Financing | Cost and availability of capital | Credit spreads (fred:BAMLH0A0HYM2), project-finance terms, equity raises, state and local-government guidance funds, subsidy awards | "Low margins will stop new capacity" → check the funding source; state-backed capacity often keeps arriving |
| Technology and replacement | New nodes, chemistries and product generations; replacement of the installed base | New-generation share of shipments, installed base ÷ annual shipments (implied life), end-of-support dates | Weak units read as saturation → age of the installed base: delayed replacement is not lost replacement |
| Policy pull-forward | Subsidy cliffs, tariff or export-control effective dates, trade-in programmes, mandates | Shipment or import spikes before an effective date (customs data), payback after it | A pre-deadline surge read as a new trend → the same months after the deadline; does the surge equal the later shortfall? |

Phase vocabulary: expansion, late cycle or peak, contraction, trough or early recovery, indeterminate.

Rules:
1. Name a clock's phase only when two independent indicators agree and the strongest counter-indicator has been checked. Otherwise write "indeterminate"; that is a valid finding.
2. Clocks can be out of phase. Demand for AI servers can expand while the consumer-device inventory clock contracts. Split the segment instead of averaging the two.
3. The industry's phase is the phase of the binding clock, the one setting price now. Name it.
4. Keep structure and cycle apart: a structurally growing industry can be in a cyclical downturn, and a shrinking one can enjoy a price spike.
5. Classical cycle lengths (the inventory cycle of a few years, the fixed-investment cycle of roughly a decade) are textbook priors from economic history. Measure the industry's own cycle from long official series before relying on them, and never extrapolate a timed cycle a decade ahead.

## 4. Measuring past cycles (base-rate KIQs)

- Pull long history: data_get(series, start = 30 years back), adding the #yoy transform for indices; e.g. fred:IPG3344S#yoy, fred:CAPUTLG3344S, fred:PCU33443344#yoy, fred:INDPRO#yoy. Input prices: imf:PCPS/G001.PLITH.USD.M (lithium metal, not carbonate: compare changes), fred:PCOPPUSDM (copper), imf:PCPS/G001.PNICK.USD.M (nickel).
- Define a downturn objectively before counting, e.g. "y/y output below zero for at least two consecutive quarters" or "utilization below its long-run median". Then list episodes with start, end, duration and peak-to-trough depth. Counts and medians you compute are REPORTED and name the series and window.
- Watch for breaks: index rebasing, classification changes, and quality adjustment. US chip output and chip price indices are quality-adjusted, so output can rise while unit or revenue volumes fall, and prices can fall while average selling prices rise. Use such series to date turns, not to size revenue.
- Converting episode counts into a probability for the horizon belongs to the reference-class method; deliver the dated episode list.

## 5. Capacity staging

| Stage | Evidence that moves a project into it | What fails at this stage |
|---|---|---|
| Announced | Press release, memorandum, investment signing (签约), government target list | Never financed; figures are aspirational |
| Financed | Final investment decision, loan or bond, equity raise, signed subsidy or grant agreement, land purchase | Conditional subsidy tranches; renegotiated terms |
| Under construction | Permits, groundbreaking (开工), EPC contract, equipment purchase orders | Delays, overruns, denied equipment export licences |
| Commissioned or ramping | First output, tool move-in, trial production (试产), grid connection (并网) | Slow yield ramp |
| Qualified | Customer qualification passed (automotive qualification, accelerator-vendor memory qualification, grid-code compliance, certification) | Failed qualification leaves capacity idle or sold into lower-grade markets |
| Utilized | Actual output, utilization rate, shipments | Demand shortfall; price below cash cost |

Rules:
- Tag every capacity figure with stage and date. Never add capacity from different stages into one number.
- Nameplate is not output: effective output = nameplate × utilization × yield. Apply yield once; if capacity is already quoted in good units, do not apply it again.
- State unit conversions as REPORTED: wafer starts per month vs bits vs dies; cell GWh vs system GWh; MW of IT load vs MW of facility power (PUE); AC vs DC ratings for solar and storage; GW of power vs GWh of energy.
- Conversions cost output: moving memory lines to HBM cuts standard bit output because HBM uses more wafer area per bit. Take the trade ratio from filings, not from commentary.
- Realization: for the industry's last cycle, count how much announced capacity reached each stage, using past announcement lists or association trackers. Apply stage-conditioned realization, never 100%.
- Correlated pipelines: projects that share a funder, a policy, a grid connection point or an equipment supplier succeed or fail together. Report clusters, not one probability-weighted sum.
- Capacity bridge for a dated window: capacity_end = capacity_start + commissioned additions + debottlenecking − retirements − conversions. Source every term.

Lead times: verify each project's dated schedule; use these classes only as orientation.
- Months: debottlenecking, restarting idle lines, software capacity on existing data centres.
- Around one to a few years: module and cell lines, data-centre buildings, most process plants.
- Multi-year: leading-edge fabs, transmission lines, large grid interconnections (LBNL's interconnection-queue reports document multi-year waits in the US), new mines (IEA critical-minerals reports document lead times of more than a decade from discovery to production).

## 6. Costs and prices

Cost curve:
- Rank producers by cash cost per unit against cumulative capacity. With ample supply, price settles near the cash cost of the marginal producer needed to meet demand. When capacity is tight, price must cover the full-cycle (incentive) cost of new capacity, including depreciation and a return on capital.
- Read costs from filings (unit costs, gross margin by product), input prices (lithium, copper, polysilicon, power: usgov:eia/electricity_price/US.IND) and losses. If the price sits below most producers' cash cost, expect cuts and exits unless state support or strategic motives keep plants running.
- The marginal producer is the highest-cost producer still running and the first to cut. Subsidies, cheap land, tax breaks and local-government support move firms down the effective cost curve; record them.

Contract vs spot:
- Record the share of volume under contract, the reset frequency (monthly, quarterly, annual) and any prepayments or long-term agreements.
- Spot leads contract at turns, but spot markets are thin. Commercial price trackers are S3: use them for direction and attribute them. Realized average selling price from filings is the S1 check.
- Where futures trade (exchange-listed metals, lithium carbonate), read the curve: backwardation signals near-term tightness, contango signals surplus and inventory.
- A price-cost spread (cell price minus cathode-material cost per kWh; memory price minus cash cost per bit) is a margin clock.

Price indices: industry PPI (fred:PCU33443344), final demand PPI (bls:WPUFD4), import prices (bls:EIUIR, measured before duties, so it shows exporters' pass-through, not the tariff itself), China's NBS PPI by sector.

## 7. Orders and backlog quality

- Book-to-bill above 1 means orders exceed shipments. In shortages customers double-order from several suppliers; strip duplicates before reading demand.
- Separate cancellable orders from non-cancellable ones, and deposits or prepayments from promises. Check cancellations in the last downturn.
- Backlog is not revenue: record the conversion rate and the cancellation history. For cloud and software, remaining performance obligations differ from bookings.
- Shortage signals: lengthening lead times, allocation, spot above contract, prepayments, rising utilization.
- Glut signals: shortening lead times, rising days of inventory, spot below contract, utilization cuts, capex cuts, price cuts below cash cost.

## 8. Traps (misreading → discriminating observation)

1. Shipments up, so demand is up → sell-through, end-market units, channel days of inventory.
2. Announced capacity, so supply → financing, equipment orders, first output, qualification.
3. High utilization, so shortage → which capacity measure (the Fed's G.17 measures sustainable output, not nameplate); closures shrink the denominator without any demand gain.
4. Spot spike, so realized price → contract share, reset dates, reported average selling price.
5. Falling price, so weak demand → cost-curve shift (cheaper inputs, learning) vs inventory overhang; check margins and inventory.
6. Capex cuts, so the glut is ending → capacity still arriving from earlier capex within the lead time.
7. Inventory falling, so recovery → level vs normal; production cuts can drain inventory with no demand gain.
8. Pre-deadline surge, so a new trend → the payback after the deadline.
9. Export growth, so competitiveness → export value vs volume (falling unit prices), destination shifts and trade diversion.
10. China product output, so the whole industry → 规模以上 coverage, physical units, year-to-date differencing.
11. Peak margin, so a normal margin → the through-cycle average over at least one full cycle.
12. Falling quality-adjusted price index, so a price war → the reported average selling price.

## 9. Cycle-phase dashboard (structure)

| Clock | Indicator (series ID or disclosure) | Latest value and period | Direction over 3–6 months | Phase or indeterminate | Flip condition |
|---|---|---|---|---|---|
| Capacity | fred:CAPUTLG3344S | from the run | from the run | from the run | e.g. below its long-run median for two quarters |
| Price | fred:PCU33443344#yoy | from the run | from the run | from the run | e.g. a change of sign |

## 10. Turning this into anchors

A binary question settles only on one stored observation of an exact series: a month, quarter or year as the series is stored (an exact date for daily data), never an average or sum you compute. Write anchor candidates in this shape: series ID, observation period, comparator, threshold, unit. Examples of the shape: "fred:CAPUTLG3344S, December 2027, at least, T percent"; "usgov:eia/generating_capacity/BAT, 2027 annual value, at least, T MW"; "fred:PCU33443344#yoy, December 2027, below, 0 percent". Thresholds T come from the run's evidence, usually the long-run median or a level that separates the canonical scenarios.
