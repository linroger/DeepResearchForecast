# Industry sources by jurisdiction and sector

Load this to choose S1 sources for an industry KIQ and to read them correctly. It names source classes and their caveats, not current figures. Fetch the publisher's own release page or database table rather than a news story about it. For China, search Chinese and English alike: Chinese titles find the S1 release ("国家统计局 集成电路 产量", "工信部 锂离子电池行业运行情况", "海关总署 锂离子蓄电池 出口"), English searches find filings and foreign counterparts.

Tiers: official statistics, customs, regulators and company filings (for the company's own figures) are S1. Associations are S1 or S2 for their members' reported data. Commercial research firms are S3: attribute them by name. Promotional market-size press releases (newswire "market to reach X by year Y" pages, Chinese "产业研究院" market-size pages) are S4 leads: trace to an origin or drop.

## 1. China

| Source | What it gives | Caveats |
|---|---|---|
| NBS 国家统计局 (releases and the 国家数据 database) | Industrial value added (real growth), product output (产品产量: integrated circuits, new-energy vehicles, lithium-ion batteries, solar cells, electricity), quarterly capacity utilization (产能利用率), PPI by sector, fixed-asset investment by industry, profits | Covers 规模以上 enterprises only: annual main-business revenue of at least CNY 20 million since 2011, so small firms are excluded. Growth rates are computed on a comparable-sample basis (可比口径) and can differ from growth implied by published levels. January and February are released together. Many series are year-to-date cumulative (累计): monthly values by differencing are REPORTED. Product output is in physical units that may differ from the industry's unit. Census years (经济普查) bring benchmark revisions |
| MIIT 工信部 | Operating reports for electronic-information manufacturing (电子信息制造业运行情况), lithium-ion batteries (锂离子电池行业运行情况), PV and software (软件业经济运行); telecom statistics (通信业统计公报); data-centre and computing statements; industry standard-conditions lists (规范条件) | Some figures are association-supplied; check whether "batteries" means cells or includes packs. Data-centre racks are counted in standard-rack equivalents (2.5 kW) |
| GACC 海关总署 (online statistics query platform) | Monthly imports and exports by HS code and partner, quantity and value | HS revisions (HS 2022 split PV cells into 8541.42 and 8541.43); USD vs CNY values; processing trade; re-exports through Hong Kong; mirror data differ from partner imports (CIF vs FOB, timing) |
| NEA 国家能源局 and CEC 中电联 | Installed generating capacity by source, new-type storage (新型储能) capacity in GW and GWh, power consumption by sector | Cumulative vs newly added; GW (power) vs GWh (energy); grid-connected (并网) vs commissioned (投运) |
| NDRC 发改委, MOF 财政部, SAMR 市场监管总局 | Industrial policy catalogues, subsidy and tax policy (e.g. vehicle purchase tax), pricing policy, antitrust reviews | Policy status comes from the document itself: issuing body, document number (文号), effective date and expiry |
| MOFCOM 商务部 | Export-control announcements on items and technologies, the unreliable entity list, trade remedies | Announcement date ≠ effective date ≠ licensing practice; joint MOFCOM–GACC notices give effective dates |
| CAC 网信办 | Generative-AI service filings (生成式人工智能服务备案) and algorithm filings | Counts of filed services, not usage or revenue |
| CSRC and the exchanges (SSE, SZSE, BSE; cninfo 巨潮资讯网; HKEXnews for Hong Kong) | Prospectuses (招股说明书) and annual reports (年报) with firm-level capacity (产能), output (产量), sales volume (销量), inventory (库存量), utilization, construction in progress (在建工程), top-five customers (前五大客户), government grants (政府补助) | Firm figures are S1. Industry-size statements inside them usually quote a commercial research firm and belong to that firm's estimate family |

Associations (members' data; check coverage):
- CAAM 中国汽车工业协会: vehicle production and sales; its sales are manufacturer shipments and include exports.
- CPCA 乘联会: passenger-vehicle retail (domestic sales to end buyers) and wholesale (shipments incl. exports), weekly and monthly, with new-energy splits.
- 中国汽车动力电池产业创新联盟: power-battery output, sales (incl. exports) and installations in vehicles (装车量); output, sales and installations are three different numbers.
- CNESA 中关村储能产业技术联盟 and CESA 中国化学与物理电源行业协会储能应用分会: storage project databases and newly commissioned capacity; project-counting rules differ from NEA's.
- CPIA 中国光伏行业协会: polysilicon, wafer, cell and module output and installations.
- CSIA 中国半导体行业协会: IC-industry sales split into design, manufacturing, and packaging and test. The headline total adds the three stages, so it double counts and is not comparable with device-sales totals.
- CAICT 中国信通院: digital-economy, computing-power (算力) and cloud reports. Check the numeric precision behind any EFLOPS total (FP64, FP32, FP16 and FP8 totals are not comparable); cloud market sizes are modelled (S2 or S3).

China's three-number problem: an association total (wholesale incl. exports), a customs total (declared exports or imports) and an NBS total (output of 规模以上 producers) measure different things. Reconcile definitions before comparing; never use one to "verify" another.

## 2. United States

| Source | What it gives | Catalog IDs or data_search query | Caveats |
|---|---|---|---|
| Federal Reserve G.17 | Industrial production and capacity utilization by NAICS | fred:INDPRO, fred:TCU, fred:IPG3344S, fred:CAPUTLG3344S, fred:IPG334S | Capacity is sustainable maximum output, not nameplate. Chip output is a real, quality-adjusted measure: it tracks performance-weighted volume, not units or revenue |
| Census M3 survey | Manufacturers' shipments, inventories and orders | fred:A34SVS, fred:A34SNO; data_search "inventories to shipments ratio computers electronic" | Read the M3 notes on which industries report orders before treating new orders as a leading signal |
| Census and USITC trade data (USA Trade Online, DataWeb) | Imports and exports by HTS or NAICS, duties | fred:IMPCH, fred:EXPCH, usgov:treasury/mts_customs_duties, bls:EIUIR | Customs value vs landed cost; de minimis and bonded flows; duty receipts are net of refunds; import price indexes exclude duties |
| BLS | Producer prices by industry, final demand PPI, employment | fred:PCU33443344, bls:WPUFD4, bls:CES3000000001; data_search "<industry> employment" | Quality adjustment in technology price indices |
| BEA GDP by industry | Value added by industry, quarterly at annual rates | usgov:bea/value_added_by_industry/334, usgov:bea/value_added_by_industry/51, usgov:bea/value_added_by_industry/514, usgov:bea/value_added_by_industry/22 | Value added, not revenue; needs the BEA key |
| EIA | Electricity sales by state and sector, prices, generation, generating capacity; Form 860M planned units | usgov:eia/electricity_sales/VA.COM, usgov:eia/electricity_sales/TX.COM, usgov:eia/generating_capacity/BAT, usgov:eia/generating_capacity/SOL, usgov:eia/net_generation/ALL | Commercial-sector sales are a data-centre proxy, not measured data-centre load; planned units are not built units; needs the EIA key |
| Commerce BIS | Export-control rules in the Federal Register, licence policies, the Entity List | — | Published ≠ effective ≠ enforced; licence exceptions and grace periods |
| Grant and loan programmes (CHIPS incentives, DOE loans) | Award stages: preliminary terms → final agreement → milestone disbursement | — | An award is not a disbursement; terms can be renegotiated |
| FERC, ISO/RTO queues, utility resource plans and large-load filings | Interconnection requests, load forecasts | — | Requested ≠ contracted ≠ energized load; LBNL's queue reports summarize completion rates |
| USGS Mineral Commodity Summaries | Annual production, reserves, import reliance by mineral | — | Annual; estimates for the latest year |
| SEC EDGAR | 10-K and 10-Q segment notes, major customers, purchase obligations, inventory; 20-F and 6-K for foreign issuers; 8-K events | — | Segment restatements break series; fiscal years differ |

## 3. European Union

- Eurostat: PRODCOM (sold production by product code, value and volume, annual), short-term business statistics (industrial production and producer price indices by NACE), Comext (trade by CN8 code), structural business statistics (turnover and value added by NACE). PRODCOM counts sold production of EU-based producers; confidential cells are suppressed.
- European Commission: state-aid decisions (including IPCEI), Chips Act measures, Net-Zero Industry Act, Critical Raw Materials Act, trade-defence regulations, CBAM. Status runs from proposal → adoption → publication in the Official Journal → entry into force → application date.
- ACEA vehicle registrations by fuel type (registrations ≠ production), ENTSO-E power data, national statistics offices (Destatis, INSEE), EIB lending.
- data_search reaches few EU industry series: fetch Eurostat tables directly.

## 4. Japan, Korea, Taiwan

- Japan: METI Indices of Industrial Production and Current Production Statistics (生産動態統計, physical output by product incl. semiconductors and electronic parts); MOF trade statistics by HS; JEITA electronics production; SEAJ billings of Japan-made chip equipment; JAMA vehicle production; EDINET for annual securities reports (有価証券報告書).
- Korea: Statistics Korea (KOSIS) monthly industrial activity with production, shipment and inventory indices for semiconductors (the inventory-to-shipment ratio is a memory-cycle clock); MOTIE monthly exports by major item (semiconductors, batteries, vehicles); Korea Customs Service exports for the first 10 and 20 days of each month (the earliest hard reading of the month); Bank of Korea; DART for company reports with capacity and capex.
- Taiwan: MOEA Department of Statistics export orders (外銷訂單, a leading indicator by product and destination) and industrial production; Ministry of Finance customs exports; monthly revenue that every listed company files on MOPS (公開資訊觀測站), a high-frequency S1 series for foundries, server makers and component suppliers; TSIA industry output; DGBAS national accounts.
- data_search rarely reaches these publishers: fetch the release page directly.

## 5. Global and multilateral

- Trade: UN Comtrade (by HS, with mirror data), WTO tariff profiles.
- Structure: OECD STAN and TiVA (value added in trade, input-output tables), UNIDO manufacturing value added.
- Energy and minerals: IEA (energy balances, Global EV Outlook, electricity and data-centre analysis; its scenarios are conditional projections, not forecasts), IRENA renewable capacity statistics, USGS minerals.
- Semiconductors: WSTS device sales by region and product (member-reported; SIA's monthly releases are three-month moving averages), SEMI equipment billings (its fab databases are commercial).
- Telecom and digital: ITU, GSMA; Uptime Institute data-centre surveys (S2); Epoch AI compute and model datasets and the Stanford AI Index (research bodies, S2); Hugging Face hub statistics (platform data).

## 6. Company filings: what to extract

| Need | Where |
|---|---|
| Revenue by segment, product and region | Segment note; revenue disaggregation note |
| Profit pool | Segment operating income; gross margin by product |
| Capacity, output, sales volume, inventory | Chinese annual reports and prospectuses (产能 / 产量 / 销量 / 库存量 table); Korean business reports; capacity sections of 20-F filings |
| Capex plan vs actual | Cash-flow statement vs guidance; construction in progress |
| Backlog | Remaining performance obligations; order backlog disclosures |
| Customer concentration | Major-customer note; 前五大客户 |
| Supply commitments | Purchase obligations, prepayments, contract liabilities, long-term agreements |
| Policy exposure | Risk factors; government grants note (政府补助); export-licence disclosures |
| Inventory health | Inventory note: write-downs, days of inventory |

Rules: guidance and forward-looking statements are claims (REPORTED) by an interested party; earnings-call remarks are S1 for what was said, not for whether it is true. State each company's fiscal year end. A company's own share claims need a third-party check.

## 7. Sector quick map (first sources to try)

| Sector | Official and S1 first | Associations and S2 | Commercial S3 (attribute) |
|---|---|---|---|
| Semiconductors, memory, HBM | G.17 chip output and utilization, chip PPI, customs HS 8542 and 8486, Korea and Taiwan exports, MOPS monthly revenue, filings | WSTS and SIA, SEMI, CSIA, SEAJ, JEITA, TSIA | Memory and foundry price trackers, chip market researchers |
| AI compute and data centres | EIA state commercial sales, BEA value added of data processing, utility and ISO filings, MIIT rack and computing statements, hyperscaler capex in filings | IEA, LBNL, CAICT, Uptime Institute, Epoch AI | Data-centre and server market researchers |
| Cloud | Segment disclosures of providers (definitions change; check restatements) | CAICT | Cloud market-share trackers |
| Autos and EVs | NBS output, customs HS 8703.80, registrations, fred:TOTALSA | CAAM, CPCA, ACEA, JAMA | EV sales trackers |
| Batteries and storage | NBS and MIIT output, customs HS 8507.60, NEA storage capacity, usgov:eia/generating_capacity/BAT | Battery alliance, CNESA, CESA | Battery shipment and price trackers |
| Solar and renewables | NEA, EIA, IRENA | CPIA | Module and polysilicon price trackers |
| Quantum | Government programme budgets and laws, patent offices, listed-company filings, peer-reviewed results | QED-C, national labs | Market-size studies (S3) |
| Open-source AI | Model licences and model cards, papers, CAC filings for China | Stanford AI Index, Epoch AI, Hugging Face hub statistics | Benchmark leaderboards (S3) |

Sector adapters in sectors-technology.md and sectors-economy.md give the decisive metrics and traps for each sector.
