# Sector adapters: economy
Each `### <key>` block is injected alone into industry KIQ tasks. Fetch its Decisive metrics first (data_get the catalog ID, else data_search, else the named S1 release via web); record value, unit, period, basis and source so a binary can anchor on it; clear each Trap before stating a level or trend; carry the Scenario axis into drivers and dated signposts.

### power-utilities
**Unit and segments** — MWh vs MW vs peak MW; generation, grid (T&D), retail; regulated (rate base × allowed ROE) vs merchant.
**Decisive metrics** — load usgov:eia/electricity_sales/US.ALL (million kWh, M); price usgov:eia/electricity_price/US.RES (cents/kWh, M); China 全社会用电量 (NEA), 利用小时 (CEC) via web; reserve margin.
**Supply and capacity** — queue → study → agreement → build → COD; transmission 5–10+ yr (LBNL/DOE prior); transformer/turbine backlogs; net of retirements.
**Cycle and price signals** — weather-normalized load (HDD/CDD), capacity-auction and forward prices, rate cases; one hot summer ≠ structural growth.
**Forecast drivers** — data centres, electrification, reshoring vs efficiency; firm-capacity adds; permitting; China 电力市场 and 容量电价 reform. Scenario axis: load growth × firm build.
**Sources** — S1: EIA, FERC, NERC LTRA, ISO/RTO reports, state PUC dockets, NEA, CEC 中电联, NDRC, ENTSO-E; S2: LBNL Queued Up, IEA.
**Traps** — queue GW = supply → most queued projects withdraw (LBNL prior): signed agreements; retail sales = demand → behind-the-meter; MW × 8760 = MWh → capacity factor.

### renewables
**Unit and segments** — GW (solar DC vs AC), TWh; utility vs distributed (分布式) solar, onshore vs offshore wind; hydrogen: electrolyser GW, Mt H2.
**Decisive metrics** — China 新增装机 (NEA; check AC/DC) via web; usgov:eia/generating_capacity/SOL, usgov:eia/generating_capacity/WND (MW, A); curtailment 弃风弃光率; module USD/W; auction prices.
**Supply and capacity** — China chain nameplate (polysilicon → module) vs world demand; permit → grid connection → COD; hydrogen: announced → FID → operating.
**Cycle and price signals** — module price vs cash cost, chain utilization, inventory, rush before policy deadlines.
**Forecast drivers** — LCOE vs firmed cost, curtailment and grid build, China market tariffs (136号文), US credits/FEOC/AD-CVD; hydrogen offtake. Scenario axis: grid integration pace.
**Sources** — S1: NEA, NDRC, CEC, 新能源消纳监测预警中心, EIA, IRENA; S2: IEA, Ember, CPIA, CWEA; S3: InfoLink, BNEF.
**Traps** — solar GW comparable → DC vs AC, installed vs connected; hydrogen pipeline = supply → FID only; record adds = trend → deadline rush, payback.

### oil-gas
**Unit and segments** — mb/d crude vs products; bcm or Mt LNG; upstream, refining, LNG; OPEC+ vs non-OPEC; spot vs term.
**Decisive metrics** — imf:PCPS/G001.POILBRE.USD.M (USD/bbl, M; daily fred:DCOILBRENTEU keeps ~1 yr), fred:DHHNGSP (USD/MMBtu, D), imf:PCPS/G001.PNGASJP.USD.M; usgov:eia/crude_production (kb/d, M); OECD stocks, days of cover; OPEC+ spare capacity; curve shape.
**Supply and capacity** — shale: rigs → completions → output in months; offshore FID → first oil 3–7 yr; LNG FID → start 4–5 yr (IEA priors).
**Cycle and price signals** — stocks vs 5-yr average, backwardation = tight, cracks, floating storage, OPEC+ compliance.
**Forecast drivers** — EV and LNG-truck substitution, petchem; OPEC+ strategy, shale breakeven, sanctions (Russia, Iran, Venezuela), Hormuz/Red Sea risk. Scenario axis: OPEC+ × sanctions × demand.
**Sources** — S1: EIA WPSR/STEO, JODI, OPEC MOMR, NBS 原油加工量, customs, NDRC, EU AGSI+; S2: IEA OMR, Baker Hughes.
**Traps** — quota cut = barrels removed → secondary-source output; China imports = use → output + net imports − stock change; rigs down = output down → per-rig productivity.

### mining-metals
**Unit and segments** — contained metal t; ore → concentrate → refined; lithium LCE vs hydroxide; nickel class 1 vs NPI; mine vs refining geography.
**Decisive metrics** — fred:PCOPPUSDM (USD/t, M), imf:PCPS/G001.PNICK.USD.M, imf:PCPS/G001.PLITH.USD.M (Li metal, not LCE); exchange + bonded stocks; cost-curve percentile; TC/RCs; 十种有色金属产量 (NBS) via web.
**Supply and capacity** — discovery → permit → finance → build → ramp; often >10 yr (IEA prior); grade decline; brownfield faster.
**Cycle and price signals** — stocks in weeks of use, falling TC/RCs = concentrate tight, Yangshan premium, scrap; spike ≠ structural deficit.
**Forecast drivers** — intensity per EV/grid/data centre, substitution (Al for Cu, LFP), recycling, Indonesia/DRC export policy, MOFCOM controls (Ga, Ge, graphite, rare earths: check scope). Scenario axis: supply response speed.
**Sources** — S1: USGS MCS, reserve reports, MOFCOM, customs, NBS; S2: ICSG/INSG, IEA Critical Minerals, LME; S3: SMM, Fastmarkets.
**Traps** — LME stocks fall = deficit → SHFE/bonded/off-warrant stocks; spike = durable → incentive price, substitution; LCE vs hydroxide mixed → convert.

### agriculture-food
**Unit and segments** — t or bushels = area × yield; marketing year (MY) vs calendar; grains/oilseeds, pork, dairy, fertilizer; China reserves opaque.
**Decisive metrics** — stocks-to-use (and ex-China); imf:PCPS/G001.PSOYB.USD.M, imf:PCPS/G001.PMAIZMT.USD.M (USD/t, M); bls:CUSR0000SAF11 (food at home, M); 能繁母猪存栏 (MARA), soybean imports (customs) via web.
**Supply and capacity** — planting follows last season's price; sow herd leads hog supply ~10 months (MARA rule); weather (ENSO) drives yield.
**Cycle and price signals** — WASDE revisions, crop conditions, planting intentions, export sales; weather spikes mean-revert.
**Forecast drivers** — diet shifts, biofuel mandates (RFS, SAF), trade retaliation shifting origin (US vs Brazil soy), yield trend, input costs, disease (ASF, avian flu → eggs bls:APU0000708111). Scenario axis: weather × trade.
**Sources** — S1: USDA WASDE/PSD/NASS, FAO, AMIS, MARA CASDE 农产品供需形势, NBS 粮食产量, customs, CONAB, NOAA CPC.
**Traps** — MY vs calendar mixed → align periods; global stocks ample → ex-China stocks-to-use; USDA projection = outcome → REPORTED until NASS final.

### biopharma
**Unit and segments** — net sales (after rebates) = patients × uptake × net price × duration; small molecule, biologics, biosimilars, cell/gene, vaccines.
**Decisive metrics** — phase-transition and approval odds by indication (BIO/Citeline priors); novel approvals/yr (FDA, EMA, NMPA); PDUFA dates; gross-to-net; exclusivity expiry (Orange/Purple Book); NRDL/集采 price cuts.
**Supply and capacity** — phase I → II → III → filing → approval; standard vs priority review; biologics/CDMO capacity, BIOSECURE-type limits.
**Cycle and price signals** — biotech funding/IPOs, licensing upfronts, CRLs, Medicare negotiation lists; adcom vote ≠ decision.
**Forecast drivers** — patent cliffs, pricing reform (IRA, MFN, EU package), NRDL/VBP, China out-licensing, biosimilars. Scenario axis: trial → approval → coverage → uptake, chained (multiply).
**Sources** — S1: FDA, EMA, NMPA/CDE, NHSA 国家医保局, CMS, ClinicalTrials.gov, SEC/HKEX filings, PMDA; S3: IQVIA.
**Traps** — deal value = cash → upfront vs milestones; topline "met endpoint" = approvable → primary endpoint, safety, full data; approval = revenue → coverage, net price.

### healthcare-services-medtech
**Unit and segments** — volumes (admissions, procedures) × net reimbursement; hospitals, payers, physicians, CRO/CDMO, devices, diagnostics; payer mix.
**Decisive metrics** — utilization; MLR = claims ÷ premiums; CMS payment updates; 510(k) vs PMA; bls:CUSR0000SAM (medical CPI, M); China 诊疗人次 (NHC), 医保基金收支 (NHSA), device 集采 cuts via web.
**Supply and capacity** — beds, nurses, procedure slots, device QMS capacity; 510(k) months vs PMA years; coverage codes lag approval.
**Cycle and price signals** — MLR spikes, utilization surprises, wage inflation, prior-auth rules, DRG/DIP rollout.
**Forecast drivers** — ageing (data_search "population ages 65 and above percent of total"), Medicare/Medicaid policy, site-of-care shift, China DRG/DIP and device VBP, Japan fee revisions. Scenario axis: payer squeeze vs volume growth.
**Sources** — S1: CMS (NHE projections REPORTED), FDA CDRH, CDC, filings, NHC 统计公报, NHSA, NMPA, OECD Health, MHLW, EU MDR; S2: KFF.
**Traps** — chargemaster = revenue → net revenue/case; MLR spike = utilization → risk-adjustment/coding change; 510(k) cleared = approved and paid → coverage decision.

### banking-insurance
**Unit and segments** — NII (earning assets × NIM) + fees − credit costs; value on ROE vs cost of equity, P/B, never EV/EBITDA; banks, P&C, life.
**Decisive metrics** — deposit beta = Δdeposit cost ÷ Δpolicy rate (fred:FEDFUNDS); NIM; NCO, NPL; CET1; data_search "charge-off rate on all loans, all commercial banks"; NFRA 净息差/不良贷款率 (Q) via web.
**Supply and capacity** — capital is capacity: RWA growth ≈ ROE × retention at constant CET1; deposits/LCR; Basel III, C-ROSS, Solvency II.
**Cycle and price signals** — curve fred:T10Y2Y, shift to time deposits, 30–89-day delinquencies, 关注类 loans, CRE refinancing, cat losses.
**Forecast drivers** — policy-rate path, credit gap bis:WS_CREDIT_GAP/Q.CN.P.A.C, China property/LGFV workout, life guaranteed-rate spread. Scenario axis: soft landing vs credit cycle.
**Sources** — S1: Fed H.8, FDIC QBP, FR Y-9C, NAIC, NFRA, PBoC 金融统计, ECB/EBA, BoJ; S2: rating agencies.
**Traps** — low NPL = sound → 关注类, 90+ overdue, restructured; NIM gain permanent → deposit beta lag; premium growth = profit → combined ratio, reserve development.

### real-estate-construction
**Unit and segments** — units or m², sales value, starts vs completions; new vs existing homes, rental, commercial; China presale model.
**Decisive metrics** — fred:HOUST, fred:PERMIT (thousands SAAR, M), fred:CSUSHPISA; bis:WS_SPP/Q.CN.R.628 (real, 2010=100); 商品房销售面积, 新开工面积, 70城 index (NBS) via web; months of inventory.
**Supply and capacity** — land sales (土地出让) → starts → completions (China presale lag years); permits lead US starts; 到位资金.
**Cycle and price signals** — affordability (fred:MORTGAGE30US), inventory months, failed land auctions, developer defaults, cement output.
**Forecast drivers** — demographics, household leverage bis:WS_TC/Q.CN.H.A.M.770.A, mortgage rules, 收储 destocking, 保交楼; US rate lock-in, zoning. Scenario axis: China price-floor timing.
**Sources** — S1: Census/HUD, FHFA, NBS, MOHURD, PBoC, MOF land revenue, city 网签 data; S2: NAR; S3: CRIC 克而瑞.
**Traps** — 70-city new-home index = market price → second-hand index, listings; sales recovery = building recovery → starts, land buys; appraisals = prices → transactions.

### consumer-retail
**Unit and segments** — nominal sales vs real volume; traffic × conversion × basket; same-store vs total; goods vs services; sell-in vs sell-through.
**Decisive metrics** — fred:RSAFS (USD mn, M), fred:RRSFS, fred:PCEC96, fred:DSPIC96, fred:PSAVERT; China 社会消费品零售总额 (M), 居民人均消费支出 (Q), 服务零售额 (NBS) via web; deflate by CPI components.
**Supply and capacity** — store space, inventory-to-sales, fulfilment; capacity rarely binds: inventory is the cycle.
**Cycle and price signals** — data_search "retail inventories to sales ratio", markdowns, card spending, delinquencies, subsidy timing.
**Forecast drivers** — real income, jobs, wealth effects, saving rate, tariffs (bls:EIUIR import prices, ex-duty), China 以旧换新 and consumption policy, channel shift. Scenario axis: real income × policy support.
**Sources** — S1: Census, BEA, BLS, filings, NBS, MOFCOM, Eurostat, Japan METI; S2: NRF, Circana; S3: card data.
**Traps** — nominal up = demand up → deflate; 社零 = household spending → includes institutional buyers, excludes most services; subsidy boom = trend → payback after expiry.

### industrials-machinery
**Unit and segments** — orders, shipments, backlog; construction machinery, machine tools, robots, grid equipment (transformers), HVAC, rail, trucks; OE vs aftermarket.
**Decisive metrics** — book-to-bill; backlog months; fred:INDPRO (index, M), fred:TCU (%, M); data_search "nondefense capital goods excluding aircraft new orders"; 产能利用率 (Q), 工业机器人产量 (NBS), excavator sales (CCMA) via web.
**Supply and capacity** — plant adds 1–3 yr (filings prior); bottlenecks: bearings, castings, electrical steel, labour; lead times signal tightness.
**Cycle and price signals** — PMI new orders (NBS, ISM), Japan machine-tool orders (JMTBA), dealer inventory, lead times, data_search "machinery manufacturing PPI".
**Forecast drivers** — capex cycle, reshoring subsidies, grid and data-centre equipment demand, China property drag vs 设备更新, tariffs, automation (IFR density). Scenario axis: capex cycle × trade.
**Sources** — S1: Census M3, Fed G.17, NBS, MIIT, filings, METI, Destatis; S2: IFR, ISM, VDMA, JMTBA.
**Traps** — PMI above 50 = high output → it measures breadth of change: check levels; backlog = revenue → cancellations; excavator sales up = home recovery → split exports.

### transport-logistics
**Unit and segments** — capacity × utilization × yield; container TEU, dry bulk, tanker t-mile, air RTK/RPK, trucking, rail, parcels; spot vs contract.
**Decisive metrics** — fleet vs t-mile demand; orderbook ÷ fleet; SCFI, Baltic Dry; transits (IMF PortWatch); 港口集装箱吞吐量 (MOT), 快递业务量 (国家邮政局) via web; data_search "freight transportation services index".
**Supply and capacity** — newbuild order → delivery 2–4 yr (Clarksons prior); yard slots; scrapping; rerouting absorbs effective capacity.
**Cycle and price signals** — spot vs contract spread, idle fleet, blank sailings, tariff front-loading; spikes fade as capacity returns.
**Forecast drivers** — trade volume (imf:WEO/G001.TRADEPCH.A, REPORTED), tariffs (US imports from China fred:IMPCH), nearshoring, chokepoints (Red Sea, Panama, Hormuz), IMO rules. Scenario axis: chokepoints × trade volume.
**Sources** — S1: MOT, 国家邮政局, CAAC, BTS, canal authorities, IMF PortWatch, IMO; S2: IATA, UNCTAD, Clarksons; S3: Drewry, Xeneta.
**Traps** — spot = carrier revenue → contract share; rate spike = demand → rerouting absorbing ships; volume surge = trend → front-loading, payback.
