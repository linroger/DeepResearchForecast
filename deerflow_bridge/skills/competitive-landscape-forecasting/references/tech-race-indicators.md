# Country technology races: indicators, pitfalls and sources

Load this when the contenders are countries or blocs (US, China, EU, with the rest as the field) in AI, quantum, semiconductors or adjacent technologies. A country race is not an industry-share question: settle the metric family and the attribution rule first.

## 1. Contract for a race

- **Technology scope.** One of: frontier AI models; AI compute; chip design, manufacturing or equipment; quantum computing, communication or sensing.
- **Attribution rule.** Count by the firm's or lab's headquarters, by where the facility or compute sits, by who controls the compute (remote cloud rental crosses borders), or by researcher affiliation. Results can flip between rules, for example when a fab owned by a firm from country A operates in country B. When rules disagree, report both.
- **Leadership metric.** One of:
  - a named milestone reached first (such as a fault-tolerance demonstration);
  - a frontier gap in months of lag;
  - the market share held by national firms;
  - a self-sufficiency ratio;
  - a composite with fixed weights (§3).
- **EU.** Decide whether the EU is one contender or each member state counts separately.
- **Field.** UK, Japan, Korea, Taiwan, India, Gulf states and others, grouped.

## 2. Metric families: what to measure, where, and why counts mislead

**Frontier capability (AI)**
- **Measure:**
  - the best system per country on independent evaluations at the resolution date;
  - the lag in months for the runner-up to match the leader's score.
  The frontier is a maximum, not a sum.
- **Sources:**
  - independent evaluators: government AI institutes, academic benchmark maintainers;
  - lab model cards (S1 claims);
  - annual compilations: Stanford AI Index (S2), Epoch AI (S2);
  - China: CAC generative-AI service filings (生成式人工智能服务备案, a regulatory count, not a capability measure), CAICT evaluations (S2, state-affiliated), and Chinese-language benchmarks (S3).
- **Misleads:** counts of "notable models" reward volume; benchmarks can be contaminated or saturated; open-weight versus closed availability differs by country.

**Compute**
- **Measure:** accelerator capacity or data-centre power in operation (MW energized, not announced), and the largest single training cluster.
- **Sources:**
  - company capex and filings;
  - interconnection data from utilities and grid operators;
  - US: EIA commercial electricity sales in data-centre states as load proxies (usgov:eia/electricity_sales/VA.COM, usgov:eia/electricity_sales/TX.COM);
  - the TOP500 list for HPC, though submission is voluntary, so a missing system is not proof that it does not exist;
  - China: CAICT computing-power white papers (算力), National Data Administration (国家数据局) and NDRC computing-hub (东数西算) disclosures, and MIIT computing-infrastructure plans (targets, not outcomes).
- **Misleads:** FLOPS summed across precisions (FP64 and FP16/FP8 differ by large factors); announced MW read as energized MW; export-controlled chips counted from smuggling estimates (S3).

**Public funding**
- **Measure:** appropriated and disbursed amounts per year, not announced or authorized ones. Normalize by economy size when the prompt is about effort (wb:IMF_WEO_NGDPD/USA, wb:IMF_WEO_NGDPD/CHN). Use absolute amounts for frontier outcomes.
- **Sources:**
  - US: appropriations acts and agency budget justifications (NSF, DOE, DARPA, NIST CHIPS awards); National Quantum Initiative annual reports; USAspending award searches by programme (the catalog's federal total covers all awards, not technology);
  - China: MOF central-budget S&T lines (中央本级科学技术支出); the NBS/MOST/MOF national R&D communiqué (全国科技经费投入统计公报); government guidance funds (政府引导基金); National IC Industry Investment Fund (国家集成电路产业投资基金) registrations;
  - EU: Horizon Europe and Digital Europe work programmes; Chips Act reports; state-aid decisions (IPCEI); the Quantum Flagship; EuroHPC JU.
- **Misleads:** multi-year envelopes read as annual spend; registered fund capital read as deployed capital; local pledges double-counted with central ones; PPP read as market FX (imported tools are paid for at market FX).

**Private investment**
- **Measure:** venture and growth funding by company HQ, plus corporate capex.
- **Sources:** VC databases (S3), AI Index compilations (S2), filings of listed firms.
- **Misleads:** a few mega-rounds dominate the totals; round sizes include compute credits; firms redomicile their HQ.

**Papers**
- **Measure:** field-normalized citation impact; the share of papers in the top 1% or top 10% by citations; fractional counts in selective journals (Nature Index, S2); acceptances at top venues by affiliation.
- **Misleads:** raw counts reward volume incentives; cross-border co-authorship and diaspora authors complicate attribution; self-citation clusters; English-language databases under-index Chinese-language journals; citation measures lag by years.

**Patents**
- **Measure:** granted invention patents; international families (PCT filings via WIPO, triadic families via OECD); forward citations. Count both by applicant HQ and by inventor location.
- **Sources:** CNIPA (国家知识产权局) annual statistics, USPTO, EPO, WIPO IP Statistics, OECD.
- **Misleads:** domestic filings driven by subsidies and quotas (CNIPA has run campaigns against abnormal filings, 非正常专利申请); utility models counted as inventions; filings read as grants; the 18-month publication lag.

**Talent**
- **Measure:** where top researchers work versus where they trained; flows between countries; retention.
- **Sources:** NSF NCSES Science and Engineering Indicators; conference author-affiliation datasets; think-tank trackers (S2/S3); China MOE graduate statistics (volume only).
- **Misleads:** graduate counts read as frontier talent; stocks confused with flows; visa policy shifts change flows faster than stocks.

**Supply-chain chokepoints**
- **Map** each single point of failure and who holds it:
  - EUV lithography and EDA software;
  - advanced packaging, HBM and leading-edge accelerators;
  - specialty chemicals and photoresists;
  - cryogenics and helium-3 for superconducting quantum systems;
  - critical minerals that have been subject to export-control rounds: rare earths, gallium, germanium, graphite.
- **Measure** import dependence and self-sufficiency:
  - China customs IC imports (海关总署, HS 8542) and equipment imports (HS 8486), against NBS IC output (集成电路产量);
  - US–China goods flows: fred:IMPCH, fred:EXPCH.
- **Misleads:** "China production" includes foreign-owned fabs in China; self-sufficiency targets read as outcomes; value share confused with volume share (mature-node volume versus leading-edge value).

**Deployment and adoption**
- **Measure:** business adoption rates from official surveys: the US Census Business Trends and Outlook Survey (AI use), the Eurostat enterprise ICT survey (AI use), and China NBS/CAICT adoption statistics.
- **Misleads:** "use" is defined differently across surveys; pilots are counted as deployment.

**Quantum milestones**
- **Measure:**
  - logical qubits whose logical error rate is below the physical rate;
  - two-qubit gate fidelities;
  - below-threshold error-correction results in peer-reviewed journals;
  - programme stage gates: DARPA Quantum Benchmarking Initiative stages and national roadmaps.
- **Sources:**
  - peer-reviewed papers in Nature, Science, PRX, PRL (S1);
  - national programme reports;
  - China: CAS and USTC peer-reviewed results, 国家重点研发计划 project lists;
  - EU: the Quantum Flagship and national programmes.
- **Misleads:** physical qubit counts compared across modalities; vendor-defined composite metrics compared across vendors; "advantage" claims later matched by better classical simulation, a widely documented pattern since the 2019 supremacy claim.

## 3. Building a race composite

1. Pick 4–6 families that match the prompt's noun, with one indicator per family from an S1 or S2 source.
2. Score frontier families by ratio to the leader and volume families by rank. Never sum raw counts across families.
3. Fix integer weights at plan time, in the leadership KIQ's wording and the scenario theses. Report each family separately beside the composite.
4. Sensitivity: move 20 weight points between the top two families and report whether the leader flips.
5. Lags: inputs (funding, talent, compute) lead outputs (papers, patents, models) by years, and outputs lead deployment. A race that resolves within 2–3 years is decided mostly by inputs already committed and capacity already under construction.
6. Policy shocks are scenario drivers, not noise: export-control rounds, entity listings, subsidy programmes, and retaliation such as critical-mineral controls. Name the rule-making calendar and pair with policy-and-trade-forecasting.

## 4. Why aggregate counts mislead (traps)

- Volume read as frontier → the best single system or result decides a frontier race.
- Per-capita read as capability → per-capita figures normalize effort, not frontier position.
- Announced budget read as spend → use disbursement data, and divide multi-year envelopes by their years.
- Count read as quality → use citation-normalized, granted and internationally filed measures.
- HQ read as location (or the reverse) → state the attribution rule, and report both when they differ.
- Silence read as absence → voluntary lists and withheld statistics are incomplete by design, especially for security-sensitive programmes.
- Targets read as outcomes → compare past plan targets with measured results. That gives a track-record prior for the state actor.

## 5. State actors for the simulation

For each government or bloc, record:
- **objective and horizon:** self-sufficiency, frontier lead, or denial to the rival;
- **instruments:** subsidies, procurement mandates, export controls, standards, talent visas;
- **constraints:** fiscal room, access to tools and chips, talent, power;
- **decision process and calendar:** budget cycles, five-year plans, defence authorization acts, rule-making dockets;
- **red lines;**
- **track record:** targets met versus missed;
- **edges to firms:** FUNDS, REGULATES, SANCTIONS, DEPENDS_ON, each with its evidence.

## 6. Anchoring race findings

Most race metrics are not catalog series. In each finding, record the publisher, edition, unit and attribution rule, so a binary can settle on that publication.

Official proxies in the catalog:
- scale: wb:IMF_WEO_NGDPD/CHN, wb:IMF_WEO_NGDPD/USA;
- US–China goods trade: fred:IMPCH, fred:EXPCH;
- data-centre load proxy: usgov:eia/electricity_sales/VA.COM.

For other national series, use data_search with short English concepts:
- "research and development expenditure percent of GDP";
- "researchers in R&D per million people";
- "high-technology exports";
- "patent applications residents";
- "ICT goods imports".

## 7. China source map (search in Chinese and English)

| Topic | Official or quasi-official source | Note |
|---|---|---|
| R&D spend | 全国科技经费投入统计公报 (NBS, MOST, MOF); 中国科技统计年鉴 | Annual; reports the basic-research share |
| Industry output | NBS 集成电路产量 (monthly, above-scale firms); MIIT 电子信息制造业运行情况 | The coverage threshold changes over time |
| Trade | 海关总署: HS 8542 ICs, HS 8486 equipment | Imports by value and by volume |
| Compute | CAICT 算力 white papers; 国家数据局; NDRC 东数西算 | Mixed precisions; separate targets from outcomes |
| AI regulation | CAC 生成式人工智能服务备案 lists | Counts filings, not capability |
| Patents | CNIPA annual report and statistics | Separate filings from grants |
| Capital | 国家企业信用信息公示系统 (fund shareholdings); 科创板招股说明书; cninfo (巨潮资讯网) | Prospectuses carry capacity and customer data |
| Plans | State Council, NDRC and MIIT five-year and action plans | Targets, not outcomes |
| Associations | CSIA (中国半导体行业协会), CCID (赛迪), CAICT (中国信通院) | S2, state-affiliated |
| Science | CAS, USTC, NSFC project and result disclosures | Peer-reviewed results are S1 |

Caveats:
- release lags and revisions;
- coverage-threshold changes (规模以上);
- discontinued or withheld series;
- unit translation, for example 算力 in EFLOPS at mixed precision.

Read the definition note before comparing a Chinese figure with a US or EU one.
