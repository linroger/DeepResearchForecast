# Reference classes, diffusion speeds and lead times

Every number here is a **prior to verify**: before it enters a finding, confirm it in a fetched source of the class named beside it, then cite that source. A prior that cannot be confirmed stays out of the notes. Projects, companies and plans named below are analogue cases to look up, not current facts.

## 1. Build the class by mechanism, not by label

Score each candidate analogue on the dimensions that set diffusion speed, and keep those that match on the decisive ones:

| Dimension | Faster when… | Slower when… |
|---|---|---|
| Unit size (granularity) | small, mass-produced, many units | lumpy, bespoke, few units |
| Cost gap at the start | already cheaper over the life cycle | needs subsidy to break even |
| Complements | works with existing infrastructure | needs new grids, chargers, fabs, software ecosystems |
| Stock being replaced | short asset life (phones, servers) | long asset life (power plants, buildings, vehicle fleets) |
| Qualification | self-certified | safety, automotive, medical or utility approval cycles |
| Payer | private buyer with a payback | utility or state budget cycle |
| Standards and networks | one standard settled | competing standards, two-sided markets |

Rules:
- **Include failures, stalls and unresolved cases.** A class built only from technologies that made it inflates speed and success rates (survivorship).
- **Same technology, different segments.** One technology can win one segment and stall in another (open-source operating systems won servers and phones but not desktops). Build the class per segment.
- **State the class size.** "3 of 7 analogues reached 50% within 10 years of 5%" is usable; "historically fast" is not.

**Analogue groups to look up** (verify each case's dates and shares in the named class):
- Granular, fast: solar modules, lithium-ion cells, LED lighting, smartphones, China's NEV retail share, Norway's policy-driven EV share (national registration statistics, industry associations such as CPCA, Norway's OFV and Statistics Norway).
- Lumpy, slow: large nuclear new-build in the US and Europe with long documented overruns (IAEA PRIS dates, regulator and audit reports); offshore wind in new markets; carbon capture; leading-edge fabs in new countries (company filings).
- Stalled or failed: fuel-cell passenger cars against national targets in Japan, Korea and California (government target documents vs registration data); 3D television; WiMAX; battery start-ups that failed to ramp yields (insolvency filings).
- Frontier, unresolved: quantum computing, fusion, humanoid robots. No completed commercial diffusion exists, so the class is **roadmap slippage**: announced milestone dates against achieved dates in the same vendors' or programmes' own records.

## 2. Diffusion-speed priors

- **Logistic identity.** 10% to 90% of the ceiling takes ln 81 ÷ r ≈ 4.39 ÷ r years.
- **Estimate r from two observations** with the log-odds slope r = [ln(s2/(K − s2)) − ln(s1/(K − s1))] ÷ (t2 − t1). Illustrative: a share going from 2% to 6% in 4 years gives r ≈ 0.29–0.30 per year whether K is 100% or 50%, so 10%→90% of K would take about 15 years. Early speed says little about the ceiling (see the methods file, §6).
- **Cross-country lags.** Long-run cross-country studies of technology adoption (e.g. Comin and Hobijn's adoption dataset) find that later technologies reached new countries faster than older ones. Prior; verify in the academic source.
- **US household adoption.** Compilations of US household adoption curves (academic datasets, Our World in Data) show later consumer technologies reaching majority adoption in one to two decades, and early networked ones (electricity, the landline telephone) taking several decades. Prior.
- **Bass parameters.** Marketing-science meta-analyses of consumer durables report average p near 0.03 and q near 0.4. Prior for consumer goods only.
- **Granularity.** Studies of energy technologies (e.g. Wilson and co-authors on "granular" technologies) find that small-unit technologies diffuse faster and learn faster than large-unit ones. Prior.
- **Energy transitions.** Historical studies of primary-energy transitions (Grübler, Smil) find decades-long shifts at the aggregate level, even when single end-uses switch fast. Do not read a fast end-use S-curve as a fast system transition.
- **Policy-driven curves.** Mandates and subsidies raise r and can raise K, but leave cliffs: look for the pull-forward before a subsidy ends and the dip after it, in monthly data.

## 3. Learning-rate priors

| Technology | Prior to verify | Source class |
|---|---|---|
| Solar PV modules | about 20% per doubling of cumulative capacity over decades | IRENA cost reports, experience-curve literature |
| Lithium-ion packs and cells | high teens to 20%+ per doubling | pack-price surveys (BNEF), peer-reviewed cost studies |
| Onshore wind | lower than solar in most studies | IRENA, LBNL wind market reports |
| Large nuclear | flat or negative learning in several national programmes | peer-reviewed cost-history studies (e.g. of the French programme) |
| Leading-edge logic | cost per transistor improving more slowly at recent nodes than in earlier decades | foundry and equipment-maker disclosures, IEEE literature |

Use the rate on **cumulative output**, with a floor (methods file, §7). A rate fitted in a period of falling input prices overstates pure learning; check whether materials prices fell over the fit window (imf:PCPS/G001.PLITH.USD.M, imf:PCPS/G001.PNICK.USD.M, imf:PCPS/G001.PCOPP.USD.M).

## 4. Lead-time priors by asset type

Durations are typical ranges to verify for the specific project and jurisdiction; the binding step is where projects usually slip.

| Asset | Typical span (prior) | Binding step | Verify in |
|---|---|---|---|
| Leading-edge logic fab, existing site | about 2–3 years from shell to volume, then a yield ramp | tool install and yield | company filings, SEMI fab databases, permit records |
| Greenfield fab in a new country | 3–5 years, often with announced slips | workforce, permits, subsidies | filings, government grant records (US CHIPS, EU Chips Act, Japanese and Korean programmes) |
| Memory capacity | 2–3 years for a new cleanroom; months for node migration in place | cleanroom shell vs tool move-in | filings, earnings calls |
| Advanced packaging line | about 1–2 years | substrate and tool supply | filings, earnings calls |
| Leading-edge lithography tools | order to shipment of a year or more | supplier backlog | equipment-maker filings |
| Battery cell plant | about 1–2 years from groundbreaking to first output in China; longer in the US and Europe; then 1–2 years of yield ramp | yield ramp | filings, local government records, 中国汽车动力电池产业创新联盟 data |
| Utility-scale solar / onshore wind | about 1 year / 1–2 years of construction | permits and grid connection | EIA-860M planned-additions file, NEA, CEC |
| Offshore wind | 5–10 years including permitting | permits, vessels, ports | national energy agencies, developer filings |
| Grid battery storage | months to about 1.5 years once connected | interconnection | EIA, CNESA, NEA |
| US interconnection queue | several years from request to operation; historically only a minority (about one-fifth or less) of requested capacity reached operation | studies and network upgrades | LBNL "Queued Up" (latest edition), RTO queue data |
| Transmission | often 7–10+ years for US interregional lines; China UHV lines much faster | permitting and siting | FERC, DOE, NEA and State Grid announcements |
| Large power transformers, HV switchgear | multi-year lead times during demand surges | factory slots | utility and OEM filings, DOE/NREL supply-chain studies |
| Large gas turbines | multi-year order backlogs during demand surges | OEM slots | OEM order books and filings |
| Hyperscale data-centre building | about 1–2 years from shell to energisation once power is secured | power, not the building | developer and utility filings, utility resource plans, grid operators' load forecasts |
| Large nuclear reactor | often 10+ years from construction start in the US and Europe; shorter in China | first-of-a-kind engineering, supply chain | IAEA PRIS construction-start and grid-connection dates |
| New mine | well over a decade from discovery to production on average | permits, financing | IEA critical-minerals reports, company technical reports |
| Lithium chemical conversion plant | about 2–4 years | commissioning and qualification | filings |
| New EV model programme | about 3–5 years at legacy OEMs; under about 2.5 years at leading Chinese OEMs | platform and supplier tooling | filings, S2 trade press |
| Automotive chip qualification | about 1–2 years | AEC-Q and PPAP cycles | supplier disclosures |

Rules:
- **Stage-condition the pipeline.** Measure P(completed by the deadline | stage) in the class: announced, permitted or financed, under construction, commissioned. Announcements carry the least weight; a public completion rate for the region (such as an interconnection queue study) beats a guess.
- **Run the latest-start test** (methods file, §9): deadline − critical chain. Parallel steps take the maximum.
- **Shared bottlenecks** (one subsidy, one transformer supplier, one grid operator) correlate the projects: split on that factor in scenarios instead of summing probabilities.

## 5. Base rates from catalog history

The engine fetches 30 years of history for a KIQ worded as a historical base rate; any agent can also call `data_get(series, start="<as-of year − 30>")`. Two mechanics matter:
- The data layer keeps the newest 240 observations: about 20 years of a monthly series, all 30 years of a quarterly or annual one. Say which window the count covers.
- A series keeps the window it was first stored with, so ask for the long start on the first call.

Counting rules (k of n, small-sample correction, hazard-to-deadline conversion) belong to `reference-class-forecasting`; this section covers the industry series and statistics. Procedure:

1. **Pick a series that measures the concept**, never a proxy for another concept or place. Industry-relevant catalog IDs:
   - semiconductors and electronics: fred:IPG3344S (real output index), fred:CAPUTLG3344S (utilisation), fred:PCU33443344 (producer prices), fred:A34SNO and fred:A34SVS (nominal orders and shipments), fred:IPG334S;
   - power and data centres: usgov:eia/electricity_sales/VA.COM, usgov:eia/electricity_sales/TX.COM, usgov:eia/net_generation/SUN, usgov:eia/net_generation/ALL, usgov:eia/generating_capacity/SOL, usgov:eia/generating_capacity/BAT, usgov:bea/value_added_by_industry/514;
   - vehicles and materials: fred:TOTALSA, imf:PCPS/G001.PLITH.USD.M, imf:PCPS/G001.PCOPP.USD.M;
   - macro denominators: fred:INDPRO, wb:WB_WDI_EG_USE_ELEC_KH_PC/CHN.
   EIA and BEA series hold shorter histories than the FRED production indexes, and some need a provider key; record the window you actually got.
2. **Put it on the forecast's basis.** Annual average or December-on-December for monthly series; `yoy` for growth rates of indexes and levels. Real (output indexes) and nominal (orders, shipments, sales) series are not interchangeable; deflate only with a price index of the same scope.
3. **Compute and show the inputs** (REPORTED):
   - the annual growth distribution: median, P10, P90;
   - the share of years with a decline, and the deepest peak-to-trough fall;
   - the h-year growth distribution, with h the years to the target. Overlapping windows are not independent: effective N ≈ years of history ÷ h;
   - cycle statistics for the 0–2 year rung: the number of downturns, their durations and depths (utilisation and production indexes). Beyond about 5 years use diffusion and cost priors instead; never extend a timed cycle a decade out.
4. **Write the finding with the rule and the count.** Example form: "In fred:IPG3344S (Index 2017=100, monthly, seasonally adjusted), the calendar-year average fell in N of M years between YYYY and YYYY; the deepest annual fall was X%." Add the marker; tag the count REPORTED.
5. **Shares from two series.** usgov:eia/net_generation/SUN ÷ usgov:eia/net_generation/ALL gives utility-scale solar's share of US generation by period; take the log-odds slope (§2) for an observed diffusion speed.
6. **Distance to a threshold.** (threshold − latest value) ÷ the standard deviation of h-step changes says how unusual the required move is. The forecast stage computes this for any binary anchored on a catalog series, so naming the exact series ID, period and units in the findings is what makes that outside view possible.

## 6. Past forecasts as a reference class

A publisher's own record at a comparable horizon is often the best prior for how far to trust its current number.
- Fetch 2–4 earlier editions of the same outlook (agency outlooks, WSTS-type consensus forecasts, CPCA or CAAM annual forecasts, vendor roadmaps). Compare each edition's value for a year that is now observed with the actual.
- Record the signed error and its horizon. Consistent sign means bias, which the current edition probably shares.
- Known patterns to test, not assume: agency outlooks have repeatedly under-projected solar additions (documented by independent analysts comparing successive IEA editions with outturns); hype-phase forecasts have over-projected hydrogen vehicles and many frontier-technology markets; Chinese manufacturing and deployment targets have often been reached early (NEA reported wind-plus-solar capacity passing its 2030 target years early; verify in NEA releases), while targets for nascent technologies are missed more often.
- Build target attainment for Chinese plan indicators from past plan evaluations (十二五, 十三五, 十四五 mid-term and final reviews): per indicator type, the share met, met early, or missed.
