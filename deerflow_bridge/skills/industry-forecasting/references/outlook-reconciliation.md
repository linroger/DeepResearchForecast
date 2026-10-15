# Reconciling external outlooks

External outlooks are **inputs to compare against**, not the prior and not the answer. Every outlook figure is REPORTED: quote it as published, with the publisher, edition and date, scenario label and definition. Every adjustment is a separate derived figure that shows its inputs. Illustrative numbers below are invented to show the arithmetic.

## 1. Classify before comparing

| Output type | What it claims | Examples of labels | May enter the central-view comparison? |
|---|---|---|---|
| Forecast | the publisher's expected outcome | semiannual industry consensus forecasts (WSTS type), analyst-firm market forecasts (Gartner, IDC), association annual sales forecasts (CPCA, CAAM) | yes, after alignment |
| Conditional projection | the outcome **if** a stated condition holds | IEA STEPS (stated policies); EIA AEO Reference case (current laws and regulations); BNEF Economic Transition Scenario; IRENA Planned Energy Scenario | yes, with the condition stated and checked against today's policy |
| Normative scenario | what would have to happen to reach a goal | IEA NZE; IRENA 1.5°C Scenario; BNEF Net Zero Scenario; IEA APS (pledges met in full and on time) | no: separate column, never weighted |
| Target | what an actor wants | five-year-plan indicators, 规划目标, 行动计划 and 实施方案 targets, corporate targets, vendor roadmaps | no: test it against attainment history |
| Stress or sensitivity case | the outcome under one varied input | high/low cases, named sensitivity cases in agency reports | no: use for the range, not the centre |

Rules:
- **Read the publisher's own label.** The IEA states that its scenarios are not forecasts; the EIA describes the AEO as projections under current laws, not predictions. Some editions add or drop cases: check the edition's own scenario list.
- **Chinese plan indicators** come as 约束性 (binding) or 预期性 (indicative, anticipatory). A binding indicator is backed by an enforcement instrument; an indicative one is an expectation. Neither is a forecast: check attainment history by indicator type (reference-class file, §6).
- **Never average a forecast with a normative scenario**, and never average outlooks with different definitions.

## 2. Align in this order

Stop at the first mismatch and fix it, or mark the pair not comparable.

1. **Perimeter.** Product scope and value-chain stage: components vs systems vs services. Typical splits: whether PHEV and range extenders (增程) count in 新能源汽车; whether pumped hydro counts in storage (新型储能 excludes it); device sales vs foundry revenue; IaaS, PaaS, SaaS, private cloud; accelerators with or without memory and networking content.
2. **Geography.** Where it is sold, made, or headquartered. "China semiconductor market" (consumption in China) is not Chinese firms' revenue, and neither is output made in China. Mainland only or including Hong Kong and Taiwan.
3. **Metric type.** Stock or flow; capacity or output (GW vs TWh); power or energy (GW vs GWh); shipments, installations or sales; units, revenue or bits.
4. **Period.** Calendar or fiscal year (Japan's April–March; company fiscal years); edition date; data cutoff.
5. **Price basis.** Nominal or real (and the base year); currency; FX method; constant-currency vs reported growth. Flows convert at the period-average rate, stocks at the period-end rate.
6. **Gross or net.** Returns, rebates, subsidies; prices with or without VAT (含税 vs 不含税).
7. **Method.** Bottom-up shipment tracking vs top-down survey; how retirements and inventory are treated.
8. **Base-year revisions.** The base-year actual may have been revised since the edition was written; re-base (§3) before comparing.

**Disagreement decomposition.** Illustrative: three 2030 outlooks read 380, 450 and 520 (spread 140). After aligning perimeter and price basis they read 430, 450 and 470 (spread 40). About 71% of the disagreement was definitional; only the remaining 40 says anything about driver uncertainty and belongs in the scenario discussion.

## 3. Re-basing arithmetic

- **CAGR** g = (V_T ÷ V_0)^(1/n) − 1, with n = T − base year (2024 → 2030 is n = 6, not 7).
- **Check stated CAGRs against stated endpoints.** A summary says "from 100 in 2024 to 250 in 2030, a 20% CAGR". Recomputed: (250 ÷ 100)^(1/6) − 1 = **16.5%**; 20% a year from 100 would reach 298.6 by 2030. The base year, the period or one figure was mis-transcribed: go back to the publisher's document before using either number.
- **Re-basing to a revised actual.** Edition A projected 500 for 2030 from a 2023 base of 250: an implied CAGR of 10.4%. The current 2025 actual is 290.
  - Level-preserving: keep 500 for 2030, which now implies 11.5% a year from 2025.
  - Growth-preserving: keep 10.4% a year from the new base: 290 × 1.104^5 ≈ 476.
  - Say which one you use and why: level-preserving when the endpoint came from a capacity or demand build-up; growth-preserving when the old base was simply wrong.
- **Unit conversions** need the publisher's own parameter, never an assumed one:
  - GWh = GW × duration in hours (1 GW of 4-hour storage = 4 GWh);
  - TWh in a year = GW × 8.76 × utilisation or capacity factor (1 GW at 0.6 is about 5.3 TWh).
- **Currency.** Keep the published currency beside any conversion. For history use fred:DEXCHUS (daily) or bis:WS_XRU/M.CN.CNY.A (monthly average; average the year's months for an annual flow). For a future year, an FX conversion is an assumption: state it.
- **Real and nominal.** An outlook in constant base-year USD stays in that basis unless the task needs nominal; then state the deflator assumption. Never compare a real-USD outlook directly with a nominal series.

## 4. Vintages

- **Record** each edition's publisher, title, publication date, data cutoff and scenario label.
- **Build a vintage ladder:** the same publisher's figure for the same target year across 3 or more editions. Persistent one-way revisions point to model bias at that horizon.
- **Track record.** Illustrative: one publisher's projections for 2025 were 100 (2019 edition), 130 (2021) and 170 (2023), against an actual of 210. The signed errors are −52%, −38% and −19% at horizons of 6, 4 and 2 years. If the current edition projects your target year at a 5-year horizon, a similar low bias is the prior to beat; say whether the reasons for it still hold.
- **Latest is not automatically best.** A newer edition supersedes an older one, but if the publisher's record at your horizon is poor, weight it accordingly and say so.
- **Herding.** Outlooks anchor on one another and on company guidance. Three reports quoting one consultancy market-size figure are one origin. Trace each figure to its first publication before counting it.

## 5. Publisher notes (definitions to check, not current values)

- **IEA** (World Energy Outlook, Global EV Outlook, electricity and data-centre reports). Scenario-based; note which case and which edition. Data-centre electricity estimates differ in whether crypto mining and networks are included.
- **EIA** (AEO, Electric Power Monthly, Form 860M). AEO cases are conditional projections; the monthly and 860M data are observations and planned additions (pipeline stages).
- **BNEF.** Economics-led vs net-zero scenarios; annual battery pack-price survey (a volume-weighted average: check whether it is quoted in real or nominal USD, and the base year, before mixing it with cell prices or other surveys).
- **WSTS / SIA.** Semiconductor device sales by vendors, compiled from member data, with a semiannual consensus forecast covering only 1–2 years. Not comparable with sums across design, manufacturing and packaging revenue.
- **SEMI.** Equipment sales and fab capacity databases. Fab databases include announced projects: read their stage fields.
- **Gartner / IDC.** Point forecasts revised quarterly; definitions of "spending" and "revenue" differ between firms; constant-currency vs USD growth.
- **CAICT** (中国信息通信研究院). 云计算 and 算力 white papers: market-size estimates with their own perimeter. 算力 in EFLOPS: check the precision basis (FP32 vs FP16 or lower) and 通用 vs 智能算力 before comparing any two figures.
- **CNESA** (中关村储能产业技术联盟). Storage statistics and white papers, often with conservative and ideal (保守 / 理想) cases. Read these as a range of conditional projections, not percentiles.
- **CPCA / CAAM** (乘联会 / 中汽协). CPCA publishes passenger-car retail (domestic) and wholesale; CAAM reports wholesale including exports and commercial vehicles. Say which series a share uses. Their annual forecasts are 1-year forecasts.
- **China Semiconductor Industry Association** (中国半导体行业协会). 集成电路产业销售额 is the sum of design, manufacturing and packaging-and-test revenue: a different concept from WSTS-type device sales or China's chip consumption.
- **Company guidance and roadmaps** (capex plans, capacity targets, qubit roadmaps). Management claims: compare with the same company's past guidance against actuals.
- **Consultancy and sell-side market sizes.** S3: use only for a definition-aligned comparison, never as the prior.

## 6. Chinese statistical calibres (口径) to pin down

- Vehicles: 产量 (production), 批发 or 销量 (wholesale), 零售 (retail), 上险量 (insurance registrations, the closest to end sales), 出口 (exports). Penetration on wholesale is not penetration on retail.
- Power batteries: 产量, 销量 and 装车量 (installed in vehicles). The gap is exports, storage use and inventory.
- Storage: 新型储能 vs 抽水蓄能; 装机 or 投运 (installed or in operation) vs 并网 (grid-connected) vs 备案 (filed), 规划 (planned) and 中标 (tenders won). The last three are pipeline stages, not capacity. Always both GW and GWh.
- Data centres: 标准机架 is a power-normalised rack count (the plan documents define the kW per standard rack), not a physical rack count; 上架率 is utilisation. Compare with IT MW only through that definition.
- Industry output: NBS 规模以上工业 (above-designated-size firms) changes coverage each year, and NBS publishes growth on a comparable basis. Growth computed from two published levels can therefore differ from the published growth rate: quote the published rate.
- Semiconductors: NBS 集成电路产量 is counted in pieces (块 or 亿块), a unit that mixes chips of very different value. Do not read it as revenue or wafer capacity.

## 7. Putting outlooks into the report

**External-outlook table:** Publisher and edition (date) | Type and label | Metric as published | Target-year value as published [S] | Aligned? (yes / adjusted, with how / not comparable) | Note.

How to use it against the run's own view:
1. Outside view first (analogues, long official history), inside view second (drivers, feasibility), outlooks third, as a check.
2. Show which canonical scenario range each aligned outlook falls into. Never rename a scenario after an agency case, and never change a scenario's probability because an outlook sits in it.
3. If the central view lies outside the range of aligned forecasts, name the mechanism that explains the difference. If it sits in the middle, check that it was not produced by averaging the outlooks.
4. Keep normative scenarios and targets in their own rows, labelled as such: useful as what-would-it-take markers, never as probability mass.
