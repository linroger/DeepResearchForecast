# Sector adapters: technology
Each `### <key>` block is injected alone into industry KIQ tasks. Fetch its Decisive metrics first (data_get the catalog ID, else data_search, else the named S1 release via web); record value, unit, period, basis and source so a binary can anchor on it; clear each Trap before stating a level or trend; carry the Scenario axis into drivers and dated signposts.

### semiconductors
**Unit and segments** — Revenue = units × ASP; memory = bits × ASP/bit. Foundry/logic, DRAM/NAND/HBM, analog, WFE, packaging cycle apart.
**Decisive metrics** — bits vs ASP; utilization fred:CAPUTLG3344S (%, M); fred:IPG3344S (US, quality-adjusted); fred:PCU33443344; inventory days; capex/revenue; China 集成电路产量 (NBS, units), IC trade (customs) via web.
**Supply and capacity** — announced → shell → tool move-in → qualified → volume (greenfield 2–4 yr, filings prior); HBM needs more wafer per bit; advanced packaging can bind (check).
**Cycle and price signals** — contract prices, customer inventory, Korea/Taiwan chip exports, SEMI/SEAJ billings; HBM can boom while DRAM slumps.
**Forecast drivers** — AI capex × HBM content, devices × content, memory capex discipline, export controls vs 国产替代/大基金, subsidies. Scenario axis: AI capex persistence × China self-sufficiency.
**Sources** — S1: filings, US BIS rules, Korea MOTIE, Taiwan MOF, Japan METI, China NBS/customs/MIIT, CSIA; S2: WSTS, SEMI (forecasts REPORTED); S3: TrendForce.
**Traps** — revenue up = demand → split bits × ASP; announced fab = supply → tool move-in, qualification; China IC units up = leading edge → node mix, value/unit.

### ai-compute-datacenters
**Unit and segments** — IT MW vs facility MW vs MWh vs GPUs vs capex USD; hyperscale, colocation, GPU clouds; training vs inference; China 智算 vs 通用.
**Decisive metrics** — energized vs under-construction IT MW; PUE = facility ÷ IT energy; capex (10-Q); usgov:eia/electricity_sales/VA.COM, usgov:eia/electricity_sales/TX.COM (commercial proxy, million kWh, M); China 算力规模 (MIIT) via web.
**Supply and capacity** — site → power agreement → interconnection → substation/transformers → energized; chips, cooling, turbines in parallel: deliverable MW = minimum.
**Cycle and price signals** — capex guidance, pre-leasing, GPU-hour prices, large-load queues; cheap GPU-hours may mean supply, not weak demand.
**Forecast drivers** — capex funding (cash vs debt), inference × efficiency, grid and on-site power, chip controls vs China accelerators, 东数西算. Scenario axis: power- vs demand-limited vs capex pullback.
**Sources** — S1: 10-K/10-Q, utility IRPs, ISO load forecasts, FERC, EIA, MIIT/NDRC, Ireland CSO; S2: CAICT 信通院, IEA, LBNL.
**Traps** — announced GW campus = capacity → signed power agreement, interconnection stage; MW × 8760 = MWh → load factor, PUE; GPUs shipped = live compute → power-on MW.

### cloud-software
**Unit and segments** — Recognized revenue: IaaS/PaaS, SaaS, model APIs (tokens), open-weight vs closed; China public vs operator clouds, 信创.
**Decisive metrics** — segment growth on each filing's perimeter; RPO (12-month part); net retention; capex/revenue; USD per token; open-weight gap to the closed frontier on one independent eval, usage share; usgov:bea/value_added_by_industry/514; 软件业务收入 (MIIT) via web.
**Supply and capacity** — regions, MW, GPU fleet; capex leads revenue; "capacity-constrained" in calls = demand exceeds supply.
**Cycle and price signals** — consumption vs optimization phases, RPO vs revenue growth, price cuts, AI revenue quoted as run-rate.
**Forecast drivers** — on-prem migration ceiling, inference volume × falling unit price, open-weight models compressing API prices, localization (EU Data Act, 数据出境). Scenario axis: AI monetization vs price compression.
**Sources** — S1: 10-K/10-Q segment notes, HKEX/SSE filings, MIIT, EC and UK CMA cases; S2: CAICT 云计算白皮书; S3: IDC, Gartner, Synergy, Canalys.
**Traps** — "cloud" lines comparable → each filing's perimeter; tracker gap = share change → same tracker and perimeter; run-rate = revenue → recognized revenue.

### telecom-networks
**Unit and segments** — Connections, ARPU, traffic (GB), sites; mobile, fibre, enterprise/IoT, towers, vendors (RAN, optical), satellite cycle apart.
**Decisive metrics** — service revenue, ARPU, churn, capex/revenue; 5G base stations and users (MIIT, M) via web; fibre passed vs connected; DOU (GB/user); data_search "producer price index wireless telecommunications carriers".
**Supply and capacity** — spectrum auction → licence → sites → coverage → densification; generations gated by 3GPP releases.
**Cycle and price signals** — capex peaks mid-rollout then falls; vendor orders, 4→3 consolidation lifts ARPU; flat-rate plans decouple traffic and revenue.
**Forecast drivers** — 5G-Advanced/6G timing, fixed-wireless and LEO substitution, high-risk-vendor bans (EU 5G toolbox, FCC Covered List), China operator capex. Scenario axis: capex trough length × new revenue.
**Sources** — S1: FCC, NTIA, ITU, Ofcom, BEREC, Korea MSIT, Japan MIC, MIIT 通信业统计公报, operator reports, 3GPP; S2: GSMA Intelligence; S3: Dell'Oro, Ookla.
**Traps** — China "5G users" = network users → package vs network-user definitions; subscriptions = people → multi-SIM, IoT; vendor upturn durable → operator capex guidance.

### internet-platforms-media
**Unit and segments** — Users × engagement × monetization: ads (impressions × price), commerce (GMV × take rate), subscriptions, games, AI assistants.
**Decisive metrics** — DAU/MAU per filing definition; time spent; ad revenue net of TAC; take rate = revenue ÷ GMV; data_search "e-commerce retail sales as a percent of total sales"; 实物商品网上零售额 (NBS), 版号 (NPPA) via web.
**Supply and capacity** — ad load, creator payouts, AI compute capex, logistics; attention and regulation bind more than capacity.
**Cycle and price signals** — ads track nominal GDP and SME budgets; split CPM vs impressions; subsidies (百亿补贴); falling take rate as GMV rises = price war.
**Forecast drivers** — attention shifts (short video, AI answers vs search clicks), antitrust remedies (EU DMA, US DOJ/FTC, SAMR), privacy and minors rules, de minimis/tariffs. Scenario axis: AI disruption of the ad funnel.
**Sources** — S1: 10-K/20-F/HKEX filings, court dockets, EU DMA/DSA decisions, SAMR, CAC, NPPA, Census, NBS, CNNIC; S3: Sensor Tower, QuestMobile.
**Traps** — GMV = revenue → take rate; MAU up = engagement up → DAU/MAU, time spent, definition changes; 网上零售额 = goods → includes services; use 实物商品 subset.

### autos-ev
**Unit and segments** — Production vs wholesale vs retail vs registrations vs exports; China NEV = BEV + PHEV (incl. EREV) + FCEV, not HEV; sales ≠ fleet share.
**Decisive metrics** — NEV share: CPCA retail vs CAAM wholesale (incl. exports, CVs); exports (customs); dealer inventory coefficient (CADA); 装车量 (GWh); fred:TOTALSA (millions SAAR); bls:CUSR0000SETA02 (used cars).
**Supply and capacity** — model cycles (China faster than legacy); utilization (overcapacity → price war, exports); overseas plants to clear tariffs.
**Cycle and price signals** — price cuts, weekly 上险量, pull-forward before subsidy/tax deadlines; one month's peak share ≠ annual share.
**Forecast drivers** — pack USD/kWh → price parity; charging; China purchase-tax schedule, 以旧换新, 双积分; US credits, CAFE/GHG (check current law); EU CO2 targets, CVDs. Scenario axis: parity × policy × trade barriers.
**Sources** — S1: MIIT, MPS 保有量, NBS, customs, India VAHAN, EEA, EPA; S2: CPCA, CAAM, ACEA, KAMA, JAMA; S3: Cox/KBB US EV estimates.
**Traps** — CAAM share = CPCA share → wholesale incl. exports/CVs vs domestic retail; NEV growth = BEV adoption → BEV vs PHEV/EREV split; post-deadline dip = collapse → prior pull-forward.

### energy-storage-batteries
**Unit and segments** — GWh vs GW (duration = GWh ÷ GW); produced vs shipped vs installed vs grid-connected; EV vs stationary; LFP/NMC/sodium; cell vs system.
**Decisive metrics** — 新型储能 GW/GWh (NEA; excl. pumped hydro); 装车量 (GWh); bid price 中标价 (RMB/Wh) vs cell USD/kWh; imf:PCPS/G001.PLITH.USD.M (Li metal, not LCE); usgov:eia/generating_capacity/BAT (MW, A); utilization hours (CEC).
**Supply and capacity** — cell nameplate (产能) vs output = utilization; cell plant 1–2 yr from groundbreaking (China), projects months (filings priors).
**Cycle and price signals** — lithium carbonate, cell and bid prices, maker inventory; prices falling as volumes rise = overcapacity, not weak demand.
**Forecast drivers** — learning rate per doubling of cumulative GWh (prior: BNEF/IEA); curtailment; market revenue (spot, 容量电价) replacing 强制配储 (verify 136号文); US credits/FEOC/tariffs. Scenario axis: merchant returns vs mandate loss.
**Sources** — S1: NEA, NDRC, MIIT, customs, CEC, EIA 860M; S2: CNESA/CESA, 动力电池产业创新联盟, IEA; S3: BNEF, SNE, GGII, InfoLink.
**Traps** — shipments = installs → exports, inventory, lag; cell price = system price → add PCS, BOS, EPC; storage installed = used → utilization hours.

### frontier-tech
**Unit and segments** — Milestones before revenue: quantum (superconducting, ion, neutral-atom, photonic), fusion, humanoids, space; no TAM extrapolation.
**Decisive metrics** — quantum: logical qubits, two-qubit fidelity, logical error rate vs threshold; fusion: Q_sci vs Q_eng; robots: units in paid work, BOM USD; space: launches/yr, USD/kg to LEO; TRL 1–9; programme budgets.
**Supply and capacity** — demo → peer-reviewed → replicated → prototype → pilot → paid use; bottlenecks: cryogenics, tritium, HTS tape, actuators.
**Cycle and price signals** — funding rounds, IPO windows, programme reauthorizations; funding ≠ progress.
**Forecast drivers** — error-correction scaling, launch cost, public programmes (US NQI, DOE fusion, EU Quantum Flagship, China 五年规划), export controls. Scenario axis: on time / slip / stall, weighted by actor hit rate.
**Sources** — S1: peer-reviewed papers, DOE/NSF/NASA/DARPA budgets, FAA licences, MOST/MIIT/CAS, NBS 工业机器人产量; S2: IFR, IAEA; S3: arXiv, roadmaps.
**Traps** — physical qubits = capability → logical qubits, error rates; roadmap date = milestone → past slippage; humanoid framework orders = deployment → units in paid work.

### aerospace-defense
**Unit and segments** — Deliveries, firm orders/backlog, engines, aftermarket; defence budget authority vs obligations vs outlays; procurement vs R&D.
**Decisive metrics** — deliveries, rate/month; net orders (gross − cancellations); backlog ÷ deliveries; defence % GDP (SIPRI, NATO); data_search "nondefense aircraft and parts new orders", "national defense consumption expenditures".
**Supply and capacity** — rate ramps gated by engines, castings/forgings, labour, certification; munitions lines take years; budget → contract → delivery lags.
**Cycle and price signals** — deliveries vs guidance, supplier delays, lease rates; supplementals, continuing resolutions.
**Forecast drivers** — traffic vs GDP, retirements, duopoly capacity, COMAC ramp; threats, NATO/EU targets, Japan/Korea/Taiwan budgets, China budget (NPC), ITAR. Scenario axis: supply recovery × budget path.
**Sources** — S1: OEM order/delivery reports, FAA, CAAC, DoD Comptroller P-1/R-1, Congress.gov, NATO, Japan MOD, China MOF budget; S2: SIPRI, IISS, IATA.
**Traps** — MoU = firm order → firm net orders; budget request = spending → enacted, obligated, outlaid; China official budget = total → SIPRI perimeter.
