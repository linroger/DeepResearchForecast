# Forecast which segments of the global semiconductor supply chain become genuine capacity or capability bottlenecks from now through December 31, 2027, and how…

## Executive Summary

Between late October 2026 and 31 December 2027, the genuine bottlenecks in the global semiconductor supply chain sit where the AI bill of materials pulls hardest: advanced packaging (CoWoS/SoIC) and HBM are binding today, and the constraint is propagating upstream into leading-edge logic and into equipment itself. TSMC's CEO said on 16 July 2026 that packaging capacity is "so tight that now it's limiting my customers' growth" [S1], and ASML stated on 14 October 2026 that its supply "as currently planned for both 2027 and 2028 will not fully meet the demand of our customers" [S2]. The rest of the chain is not broadly scarce: mature-node foundry (28nm+) is the slack pool, mainstream DRAM/NAND is starved by HBM wafer allocation rather than short of capacity, and substrate and wafer relief is announced but dated mostly beyond the horizon.

The baseline confirms tightening without broad scarcity. United States semiconductor and electronic component manufacturing capacity utilization (NAICS 3344) was 76.51% in September 2026, up from 73.723% in September 2025 after a 71.096% trough in March 2026, and still well below the 92.195% peak of February 2022 [S3]; the matching industrial production index reached 198.6335 (2017=100) against 165.667 a year earlier [S4]. Estimated CoWoS demand rose from about 370,000 wafers in 2024 to about 670,000 in 2025 and approaches about 1,000,000 in 2026 — a trade estimate, as TSMC discloses no CoWoS capacity [S1]. The decisive 2027 variable is NVIDIA's package: Rubin ships with up to 288 GB of HBM4 per GPU in 12-Hi stacks [S5], while the 2027 step is contested between a quad-die, 1 TB-class HBM4e roadmap [S6][S7] and a reported dual-die replacement carrying 192 GB [S8][S9] — a roughly fivefold gap in per-package HBM bits. Equipment demand is already at record: global equipment billings of US$40.53 billion in Q2 2026, up 23% year-over-year [S10].

Base rates argue the tightness persists rather than clears: of five documented bottleneck episodes since 2020, only the commodity memory cycles resolved within 18 months [S11][S12][S13]. The scenario frame for overall 2027 chain tightness: under AI-led broad tightness — 40% — accelerator demand outruns the CoWoS/SoIC and HBM4 ramps and spills into leading-edge logic; under Packaging-only bottleneck — 25% — capacity additions elsewhere catch up by mid-2027 but packaging and substrates remain the single binding constraint; under Balanced chain — 20% — record 2026-27 capex and sold-out 2027 memory books clear the gaps, leaving only isolated allocation episodes; under Oversupply and correction — 15% — an AI demand air pocket or export-control shock flips HBM and mainstream memory into oversupply by late 2027.

The most important leading indicators are dated and near-term. The BIS Affiliates Rule suspension runs only "until November 9, 2026" absent a Federal Register extension [S14]; China's Announcement No. 70 pause of the October 2025 rare-earth controls ends 10 November 2026 with no extension published as of 16 October 2026 [S15]; Treasury says the Busan truce was extended to 10 January 2027, but BIS has published no matching notice [S16]. A joint lapse is the dated trigger for Oversupply and correction — 15%, while mutual extensions shift weight toward Balanced chain — 20%. Beyond these clocks, watch TSMC's quarterly guidance and 2026-2028 capex, which management says will be "even more significantly higher than the past three years" [S17]; SEMI equipment billings against the Q2 2026 record [S10]; and the resolution of the Rubin Ultra package design [S8], which settles the fivefold HBM gap and, with it, the depth of the 2027 squeeze.

## Baseline: utilization, lead times and prices across the chain

The macro backdrop is tightening. United States semiconductor and electronic component manufacturing capacity utilization (NAICS 3344) was 76.51% in September 2026, up from 73.723% in September 2025 after a 71.096% trough in March 2026 [S3]; the matching industrial production index reached 198.6335 (2017=100) versus 165.667 a year earlier [S4]. Global equipment billings hit a record US$40.53 billion in Q2 2026, up 23% year-over-year [S10].

### Leading-edge logic and advanced packaging

TSMC posted Q3 2026 revenue of USD 46.7 billion, guided Q4 to $52.3–54.3 billion, and expects ~44% full-year USD growth [S17][S18]. By TSMC's earnings disclosures, N3 rose to 33% of wafer revenue in 3Q26 (28% in 4Q25) while N5 fell to 28% (35%) [S19]. Silicon Analysts — not TSMC — estimates N3 utilization near 98% with 104–156-week lead times, and N2 at 78–156 weeks, with reported bookings into 2028 unconfirmed; N7 and mature nodes run available at 4–17 weeks [S19][S1]. TSMC's CEO said on July 16, 2026 that packaging is "so tight that now it's limiting my customers' growth" [S1]. Trade reports put CoWoS-S/L lead times at 52–78 weeks, fully booked, with capacity ramping from ~75–80k toward 120–130k wafers per month by end-2026 [S1]; TrendForce reports the CoWoS supply-demand gap narrowing from ~20% to ~10% by end-2026 [S20]. Samsung's SF2 (2nm) yield is leak-reported from ~30% in Q1 2026 toward 50–60%, with no official figure [S21][S22][S23].

### HBM and mainstream memory

Counterpoint puts Q2 2026 HBM revenue share at SK Hynix 50%, Samsung 33%, Micron 18%; DRAM share at Samsung 38%, SK Hynix 25%, Micron 24%, CXMT 10% [S24]. TrendForce forecasts 4Q26 conventional DRAM contract prices +10–15% QoQ and NAND +15–20% QoQ, with the market undersupplied [S25]; 3Q26 server DRAM was forecast +13–18% QoQ, capped by LTAs [S26]. TrendForce estimates 2026 HBM prices up 70–140% YoY [S27] and has revised its 2027 blended HBM ASP forecast to +121% YoY [S25]. Samsung+SK Hynix finished-memory inventory fell below 10 days in September 2026 [S28]; Samsung runs ~150,000 DRAM wafers per month through HBM lines (~75,000 wpm HBM4) [S28], and Micron is seen reaching ~100,000 HBM wpm by December 2026 [S28].

### Materials, equipment, back-end

ABF substrate ASPs rose from ~$65 (2024) to ~$82 (2025), +26%, with 20–28-week lead times persisting [S29]; other reports cite 48–56-week lead times on large AI substrates [S30] and a 30% Ajinomoto film price rise [S31]. Ibiden (~35%), Shinko (~18%), Unimicron (~14%), AT&S (~10%) and Nan Ya (~5%) dominate [S29]. GlobalWafers projects >90% 300mm utilization from 2025 to 2027 [S32], SUMCO reports record 300mm shipments [S33], and SEMI forecasts 11.8% wafer-shipment growth in 2026 [S10]. ASML booked record Q3 2026 net sales of €11.7 billion and €5.0 billion net income [S2] and states its supply "as currently planned for both 2027 and 2028 will not fully meet the demand of our customers" [S2]; TSMC confirms "the tool supply is tight" [S17]; one High-NA system was sold in Q3 2026 [S34]. Mature nodes are repricing: SMIC 28nm pricing fell from ~$2,500 to ~$1,500 per wafer in 2024, with 5–20% increases planned for 2026 [S35][S36]; analysts assume 5–10% UMC/GlobalFoundries hikes in H2 2026 [S37]. Amkor raised its Arizona packaging/test campus to ~US$12 billion [S38]. No current utilization or lead-time data exist here for photoresist/specialty gases or EDA/IP; Shin-Etsu's last dated capacity move is a ~¥30 billion photoresist release predating the AI surge [S39].

### Figure: Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS =) —…

![Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS =) —…](demos/semichain-2027/research-charts/data_fred_caputlg3344s_e06131c33577e0cf.png)

*Official series from FRED; latest observation marked: up from a year earlier. [S3]*

## Official Data Baseline

| Series | Latest historical value | Period | Yearly change | Status | Publisher projection | Source |
|---|---|---|---|---|---|---|
| Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States | 76.51% | 2026-09 | +2.787 pp | stored observation | — | [S3] |
| Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States | 198.6335 Index 2017=100 | 2026-09 | +32.9665 (+19.899%) | stored observation | — | [S4] |
| Real Exports of Goods and Services — United States | 2814.538 Billions of Chained 2017 Dollars | 2026-Q2 | +155.218 (+5.837%) | stored observation | — | [S40] |
| Real imports of goods and services — United States | 3913.833 Billions of Chained 2017 Dollars | 2026-Q2 | +202.793 (+5.465%) | stored observation | — | [S41] |

### Figure: Real imports of goods and services — United States

![Real imports of goods and services — United States](demos/semichain-2027/research-charts/data_fred_impgsc1_554266cb0a529cbf.png)

*Official series from FRED; latest observation marked: up from a year earlier, near the top of the charted range. [S41]*

## AI demand pull: bill of materials through 2027

### HBM bits per accelerator

NVIDIA's July 2026 developer blog sets the confirmed 2026 anchor: Rubin, shipping in H2 2026, integrates up to 288 GB of HBM4 per GPU in 12-Hi stacks at 22 TB/s peak bandwidth, with 336 billion transistors on two reticle-limited compute dies unified by NV-HBI [S5]. The 2027 step-up is contested: the roadmap as commonly reported shows quad-die Rubin Ultra with 1 TB-class HBM4e in H2 2027 [S6][S7], while SemiAnalysis and mlq.ai report the quad-die design was cancelled over substrate warpage and yield issues in TSMC CoWoS-L, replaced by a dual-die package carrying 192 GB of 8-Hi HBM4 [S8][S9] — a roughly fivefold gap in per-package HBM. Commercial Times via TrendForce (October 20, 2026) reports this lever under active consideration: switching Rubin Ultra from 12-Hi to 8-Hi stacks cuts HBM capacity per GPU by about 33% and lets the same DRAM die supply support about 50% more GPUs [S42]. Bank of America sizes the 2026 HBM market at $54.6 billion, up 58% year-on-year, and Goldman Sachs projects custom-ASIC AI HBM demand growing 82% to one-third of total HBM demand [S43] — attributed external projections, not observations.

### Packaging intensity and wafer starts

CoWoS demand has roughly tripled in two years — an estimated ~370,000 wafers in 2024, ~670,000 in 2025 and approaching ~1,000,000 in 2026 — per Silicon Analysts citing trade reports; TSMC discloses no CoWoS figure [S1]. Estimated 2026 industry capacity is 120,000–140,000 wafers per month at TSMC plus 50,000–60,000 wpm from OSAT partners, approaching 200,000 wpm, against a supply–demand gap of about 20% at mid-2026 narrowing to about 10% by end-2026 [S20]. TSMC has guided a CoWoS capacity CAGR above 80% for 2022–2027 [S20], and its CEO said on July 16, 2026 that packaging is "so tight that now it's limiting my customers' growth" [S1]. NVIDIA is estimated to hold ~60% of 2026 CoWoS capacity (~595,000 wafers), with NVIDIA, Broadcom and AMD together above 85% [S1]. For logic wafer starts, TSMC reportedly targets 2nm capacity of 90,000 wpm at end-2026 rising to 110,000 wpm by mid-2027, with 3nm up more than 16% (Economic Daily News via TrendForce, September 14, 2026) [S44].

### HBM wafer allocation and the 2027 balance

SK Hynix and Samsung together process an estimated 150,000–200,000 HBM wpm, three to four times Micron's volume; Micron reaches about 100,000 HBM wpm by December 2026, and Samsung dedicates about half of ~150,000 DRAM wpm through HBM lines to HBM4 [S28]. Samsung and SK Hynix finished-memory inventory fell below 10 days of supply in September 2026 [S28], and TrendForce forecasts blended 2027 HBM ASP rising 121% year-on-year [S25].

Supply–demand note: through 2027 the binding constraint stays packaging-side, because most announced substrate relief (IBIDEN Ono ramp from Q1 2028, Unimicron full capacity mid-2028) lands after the horizon [S45]. The Rubin Ultra configuration is the decisive uncertainty separating AI-led broad tightness — 40% from Packaging-only bottleneck — 25%.

### What would change the view

- NVIDIA confirms Rubin Ultra's HBM configuration (192 GB 8-Hi versus 1 TB-class 12-Hi) at a roadmap update or GTC by March 2027.
- TrendForce quarterly estimates put the CoWoS supply–demand gap below ~5% in any H1 2027 release [S20].
- TSMC's January 2027 call guides 2027 capex flat or down, against current "even more significantly higher" 2026–2028 intentions [S17].
- SK Hynix, Samsung or Micron late-October-to-November 2026 earnings disclose 2027 HBM4 allocations materially below current sell-through reports.

## Advanced packaging and HBM: the core tightening candidates

### CoWoS: demand tripling against a record ramp

Estimated CoWoS demand rose from about 370,000 wafers in 2024 to about 670,000 in 2025 and approaches about 1,000,000 in 2026; TSMC discloses no CoWoS capacity [S1]. On its July 16, 2026 earnings call TSMC's CEO said packaging capacity is "so tight that now it's limiting my customers' growth" [S1]. Trade reports describe CoWoS-S and CoWoS-L as fully booked with 52–78-week lead times, which TSMC has not confirmed [S1]; NVIDIA is estimated to hold roughly 60% of 2026 capacity (~595,000 wafers), with NVIDIA, Broadcom and AMD above 85% combined [S1].

Supply is ramping at record pace: institutional estimates reported by TrendForce put TSMC monthly CoWoS capacity at 120,000–140,000 wafers per month in 2026 plus 50,000–60,000 wafers per month from OSAT partners, near 200,000 wpm industry-wide [S20]. The supply-demand gap is expected to narrow from about 20% in mid-2026 to about 10% by end-2026 [S20], and TSMC said in May 2026 that CoWoS capacity will compound at more than 80% annually from 2022 to 2027 [S20]. For 2027, Morgan Stanley forecasts about 200,000 wpm [S46]; a market estimate sees roughly 130,000 wpm at end-2026 doubling to about 260,000 by end-2028 [S47], with a single-sourced rumor of at least 200,000 wpm in 2027 [S48]. Next-generation CoPoS reaches pilot production only in mid-2027 [S20].

### Substrates: relief lands mostly after 2027

NVIDIA's October 2026 supply-chain agreements target 2.5x capacity over three years, but the dated components arrive late: IBIDEN's Ono ramp begins Q1 2028, and Unimicron's KF expansion adds capacity from Q2 2027, reaching full run-rate only mid-2028 [S45]. Concentration stays high — per a 2026 analysis, Ibiden ~35%, Shinko ~18%, Unimicron ~14%, AT&S ~10% — with 14-layer ABF lead times still 20–28 weeks and ASPs up from ~$65 (2024) to ~$82 (2025) [S29].

### HBM: allocation, not availability

Samsung runs about 150,000 DRAM wafers per month through HBM lines, roughly 75,000 wpm of it HBM4, as of September 2026; SK Hynix and Samsung together process an estimated 150,000–200,000 HBM wpm, three to four times Micron, which reaches about 100,000 wpm by December 2026 [S28]. Their finished-memory inventory fell below 10 days of supply on September 7, 2026 [S28]. Q2 2026 HBM revenue share: SK Hynix 50%, Samsung 33%, Micron 18% [S24]; UBS estimates SK Hynix at about 70% of Rubin-generation HBM4 supply [S43]. Rubin ships from H2 2026 with up to 288 GB of 12-Hi HBM4 per GPU [S5]; whether Rubin Ultra carries the roadmap's 1 TB-class HBM4e [S6] or a reported dual-die 192 GB 8-Hi redesign [S8][S9] is unresolved and swings per-package 2027 HBM demand roughly fivefold. TrendForce projects 4Q26 conventional DRAM contract prices up 10–15% QoQ and NAND up 15–20% QoQ [S25], and reportedly forecasts blended HBM ASP rising 121% YoY in 2027 [S25].

The binding constraints are CoWoS wafer lanes and HBM4 wafer allocation; the gap clears through the 2027 ramp toward ~200,000 wpm, substrate LTAs, or demand-side redesign to 8-Hi stacks. Under AI-led broad tightness (40%) both remain binding into 2027; under Packaging-only bottleneck (25%) memory catches up while CoWoS/substrates stay the single constraint; under Balanced chain (20%) gaps clear by mid-2027; under Oversupply and correction (15%) HBM flips to surplus by late 2027.

## Leading-edge logic foundry

### TSMC: N3 stretched, N2 ramping, tool-gated

TSMC's Q3 2026 revenue was USD 46.7 billion, above guidance, with full-year 2026 growth now expected around 44% year-over-year in US dollar terms, and Q4 2026 guidance of $52.3–54.3 billion versus $33.73 billion a year earlier [S17][S18]. Management called leading-edge demand "extremely robust" while being "prudent" on 2027 given challenged consumer and price-sensitive end markets [S17]. Q4 2026 gross margin is guided down about 40 basis points to 66% at the midpoint on 2-nanometer ramp dilution and overseas fabs [S17], and 2026–2028 capex will be "even more significantly higher than the past three years" [S17]. TSMC explicitly flagged that "the tool supply is tight" [S17], corroborated by ASML's October 14, 2026 statement that its supply "as currently planned for both 2027 and 2028 will not fully meet the demand of our customers" [S2].

On node mix, Silicon Analysts tallies N3 at 28% of TSMC wafer revenue in 4Q25 rising to 33% in 3Q26, with TSMC adding three N3 fabs — a reversal of its no-post-peak-expansion practice — while N5 fell from 35% to 28% [S19]; the same source estimates N3 utilization near 98% with 104–156-week lead times, figures TSMC does not disclose [S19]. N2 shows reported lead times of 78–156 weeks, with bookings into 2028 unconfirmed [S1]; reporting has TSMC targeting 2nm capacity of 90,000 wpm at end-2026 rising to 110,000 wpm by mid-2027, with 3nm capacity up more than 16% [S44].

### Samsung 2nm: qualification still catching up

Samsung Foundry's SF2 yield was reported at roughly 30% in Q1 2026, climbing to about 50% — with later claims of about 60% — in late 2026; Exynos 2600 for Galaxy S26 is the first mass-production product, and SF1.4 has shifted to 2029 [S21][S49][S22][S23]. All of these figures are leak-based and unconfirmed by Samsung, and no external 2nm customer qualification is verified — leaving TSMC effectively the only qualified leading-edge source through the horizon.

### Capacity backdrop and assessment

US semiconductor and electronic component manufacturing capacity utilization (NAICS 3344) was 76.51% in September 2026, up from 73.723% in September 2025 and a trough of 71.096% in March 2026 [S3] — a tightening macro signal, though it mostly reflects mature US fabs rather than leading-edge Asia capacity. Leading-edge logic is capacity-tight with pricing power intact, but it is a second-order bottleneck: the constraint propagates through tool supply rather than cleanroom space, and TSMC's 2027 prudence flags demand-side risk. Under AI-led broad tightness (40%), N2/CoWoS coupling keeps leading-edge allocation binding; under Packaging-only bottleneck (25%), wafer supply loosens as packaging stays constrained; under Balanced chain (20%), three new N3 fabs and the 2nm ramp clear gaps by late 2027; under Oversupply and correction (15%), softer AI orders would loosen N7 and mature nodes first — reported available at 4–17-week lead times [S1]. What would change the view: TSMC's January 2027 capex guidance below "significantly higher"; a Samsung-confirmed external SF2 tape-out by mid-2027; ASML 2027 shipments materially above its planned 30% capacity increase [S2].

## Materials and single-source chokepoints

The binding materials risks before end-2027 sit in substrates first and 300mm wafers second: relief is announced but dated, with most new substrate volume landing in 2028, while ABF film, glass cloth and wafer supply stay concentrated.

### ABF/BT substrates: relief dated after the horizon

A 2026 analysis puts high-end FC-BGA/ABF capacity shares at Ibiden ~35%, Shinko Electric ~18%, Unimicron ~14%, AT&S ~10% and Nan Ya PCB ~5% [S29]. Substrate ASPs rose from ~$65 (2024) to ~$82 (2025), a 26% increase, with 14-layer lead times that peaked at 28 weeks in early 2025 still at 20–28 weeks [S29]; high-tier ABF is separately reported at 48–56 weeks, up to 4.7x equilibrium — most likely a tier difference [S30]. Ajinomoto raised ABF film prices 30% [S31]. ABF area per AI GPU/ASIC shifts from ~0.5–1 sqm pre-2023 toward 2–4 sqm by 2027 [S50]. Unimicron's chairman said on 20 October 2026 that lead times for more than 80% of substrate-making equipment have lengthened — some to 30 months — and that low-CTE glass fiber cloth, CCL and ABF could face a 20% supply shortfall in 2027 [S51].

| Milestone | Status and evidence | Slack to end-2027 |
|---|---|---|
| IBIDEN Gama Cell 6 mass production | ~¥220bn first phase of ~¥500bn FY2026–28 plan; mass production from FY2027 [S52] | Qualification-dependent |
| IBIDEN Ono 3x capacity | NVIDIA multibillion-dollar reservation; ramp begins Q1 2028 [S45] | None |
| Unimicron KF, Taiwan | Adds capacity Q2 2027; full by mid-2028 [S45] | Partial |
| New ABF film supplier | Qualification takes a minimum of 18–24 months [S29] | Lock-in |

Supply-demand: a third-party model has ABF demand growing 25–35% CAGR through 2027 against committed expansions completing in 2028 [S50]; the gap clears through price, long-term agreements [S53] and substrate redesign, not new 2027 capacity. Unimicron raised 2026 capex to NT$53.7 billion, over 80% for ABF [S54]. That timing keeps Packaging-only bottleneck — 25% credible and feeds AI-led broad tightness — 40%.

### 300mm wafers: high utilization, no new volume

SUMCO's stated focus shifts to "sophistication or refinement" rather than volume [S55]; its last large greenfield commitment was a $2 billion expansion announced in 2021 [S56], and record-high 300mm shipments were projected for Q2 FY2026 [S33]. GlobalWafers projected 300mm utilization above 90% from 2025 to 2027 [S32], holds July 2024 CHIPS preliminary terms for the first US 300mm source [S57], and is reported to lift 12-inch prices in H2 2026 [S58]. SEMI forecasts 11.8% silicon wafer shipment growth in 2026 with record highs through 2029 [S10]; no new SUMCO volume commitment deliverable by end-2027 was found.

### Photoresist and specialty gases: dated expansion, unquantified propagation

Shin-Etsu's ¥30bn photoresist investments (Naoetsu, Joetsu, Douliu) date from around 2020; no dated post-2024 expansion was confirmed, leaving current EUV resist capacity unknown [S39]. China refines ~98% of the world's gallium [S59]; gallium/germanium licensing (effective 1 August 2023), the 3 December 2024 prohibition in principle on exports to the United States, and the 4 April 2025 heavy-rare-earth licences remain in force [S59], with rare-earth exports down 9.6% year on year at 43,711 tonnes in January–September 2026 [S15]. Propagation into leading-edge CMOS is not quantified in the evidence. US SME exports to China fell from $6.8 billion (2021) to $4.2 billion (2024) [S60], while real exports of goods and services — United States reached 2814.538 billions of chained 2017 dollars in 2026-Q2, up 5.837% [S40].

Two clocks converge: MOFCOM's pause of the October 2025 rare-earth controls lapses 10 November 2026, with no extension published as of 16 October 2026 [S15]; the BIS Affiliates Rule suspension ends 9 November 2026 absent a Federal Register notice, despite the announced truce extension to 10 January 2027 [S14][S16]. No source in the evidence publishes a probability for reinstatement of the suspended October 2025 rare-earth controls at that expiry [S15].

What would change the view: Unimicron and IBIDEN capex execution against plan [S54][S52]; Ajinomoto film price and lead-time prints [S31]; a new SUMCO or GlobalWafers 300mm commitment [S32]; a Federal Register extension before 9 November 2026 [S14].

### Figure: Real Exports of Goods and Services — United States

![Real Exports of Goods and Services — United States](demos/semichain-2027/research-charts/data_fred_expgsc1_ab7cc7ffefd6a55e.png)

*Official series from FRED; latest observation marked: up from a year earlier, the highest in the charted period. [S40]*

## Equipment: EUV, High-NA, etch and deposition

Equipment gating is now supplier-confirmed: ASML stated on 14 October 2026 that its supply "as currently planned for both 2027 and 2028 will not fully meet the demand of our customers" [S2].

### Lithography: a self-declared 2027–28 shortfall

Q3 2026 brought record total net sales of €11.7 billion and net income of €5.0 billion [S2]. New lithography systems sold numbered 86 in Q2 2026 and 113 in Q3 2026 per secondary summaries [S61]; around 65 Low-NA (NXE) tools ship in 2026, with one High-NA system reaching revenue in Q2 2026 [S62] and one more sold in Q3 2026 [S34].

| Publisher, edition | Type | Statement as published |
|---|---|---|
| ASML, Q3 2026 release | Company statement | 2027–28 planned supply short of demand; +30% low-NA EUV/DUV immersion capacity for 2027; FY2026 net sales €44–45 billion; Q4 guidance €14.2–15.2 billion [S2] |
| Secondary relay of ASML guidance | External projection | 2027 revenue €45–47 billion [S63] |
| ASML Q3 2026 call (transcript summary) | Transcript summary | NXE:3800F at 260 wafers per hour, small-quantity introduction early 2027 [S34] |

Install throughput, not shipment count, gates node ramps: the NXE:3800F enters small-quantity introduction in early 2027 [S34]. High-NA is a capability constraint rather than a volume bottleneck: Intel deployed the first EXE:5200B in December 2025 and reportedly expanded its order to two units at roughly $370–380 million per tool [S64][S65], against near-zero High-NA volume through the horizon [S62].

### Etch, deposition and the wider tool chain

TSMC said on 15 October 2026 that "the tool supply is tight" and that it works with tool suppliers well in advance, with 2026–2028 capex to be "even more significantly higher than the past three years" [S17]. SEMI billings corroborate: a record US$40.53 billion in Q2 2026, up 23% year on year and the second consecutive record [S10], after +21% (Q1 2025), +24% (Q2 2025), +11% (Q3 2025) and +14% (Q1 2026) [S66], with SEMI-reported full-year 2025 billings of $135 billion [S66]. No direct Applied Materials, Lam Research or Tokyo Electron shipment or lead-time figures appear in the evidence; exposure is inferred from SEMI totals, TSMC's statement, and substrate-equipment lead times of up to 30 months [S51]. TSMC reportedly targets 2nm capacity of 90,000 wafers per month at end-2026, rising to 110,000 by mid-2027 [S44] — tool-gated tranches.

### Aggregate anchor and base rate

United States semiconductor capacity utilization (NAICS 3344) was 76.51% in 2026-09, against 73.723% in 2025-09 and a February 2022 peak of 92.195% [S3], while the output index reached 198.6335 (2017=100) in 2026-09, up 19.899% year on year [S4] — record output filling newly installed capacity. On the evidence assembled, roughly 1–2 of five named 2009–2026 episodes resolved within 18 months, and capability bottlenecks such as CoWoS persisted 10+ quarters despite capacity doubling [S12][S67]. A supplier-declared tool shortfall sits in the capability class, weighting AI-led broad tightness — 40% over Balanced chain — 20%.

Supply-demand: implied demand is TSMC's 2026–28 capex step-up plus peers' ramps against a 30% ASML capacity increase that ASML itself calls insufficient [S2][S17]; the gap clears through allocation and lead times rather than price alone.

What would change the view: ASML Q4 2026 bookings and any 2027 capacity raise beyond 30% [S2]; SEMI billings growth below +15% year on year for two consecutive quarters [S10]; TSMC January 2027 capex guidance below 2026 [S17]; NXE:3800F introduction slipping past mid-2027 [S34].

### Figure: Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS =) —…

![Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS =) —…](demos/semichain-2027/research-charts/data_fred_ipg3344s_ac27e02afe5546e1.png)

*Official series from FRED; latest observation marked: up from a year earlier, the highest in the charted period. [S4]*

## Mature nodes, memory mainstream and back-end OSAT

These three segments carry different balances: 28nm+ foundry is the chain's slack pool, mainstream memory is starved by HBM wafer allocation rather than short of capacity, and OSAT relief is dated mostly for 2027–28.

### 28nm+ foundry: loose, with modest re-pricing
N7 and mature nodes are available at 4–17 weeks with little constraint [S1]. SMIC's 28nm wafer pricing fell from about $2,500 to about $1,500 during the 2024 downcycle, with 5–20% increases planned for 2026 [S35][S36], and analyst assumptions now embed 5–10% price increases at UMC and GlobalFoundries in H2 2026 and another 5–10% in 2027 [S37]. US NAICS 3344 utilization was 76.51% in September 2026, up from 73.723% a year earlier but far below the 92.195% peak of February 2022 [S3], with production at 198.6335 (Index 2017=100, September 2026, +19.899% year on year) [S4] — tightening from a loose base. China exposure grows: CXMT doubled DRAM revenue share to 10% by Q2 2026 [S24], while US SME exports to China fell from $6.8 billion (2021) to $4.2 billion (2024) and mature-node technology remains licensable [S60].

### Mainstream DRAM and NAND: allocation-driven tightness
TrendForce projects 4Q26 conventional DRAM contract prices up 10–15% QoQ and NAND up 15–20% QoQ, with capacity prioritized to server products; PC DRAM supply could decline in 2027 and mobile allocations tighten [S25]. Commercial Times, via TrendForce news, expects about 20% QoQ DRAM increases in 4Q26 [S42]; TrendForce forecast server DRAM up 13–18% QoQ in 3Q26 with LTAs capping increases [S26], and a secondary summary puts 2Q26 at +58–63% QoQ DRAM and +70–75% QoQ NAND [S68]. The mechanism is crowding-out: Samsung runs about 150,000 DRAM wafers per month through HBM lines, roughly half dedicated to HBM4 [S28], and Samsung+SK Hynix finished-memory inventory fell below 10 days of supply on September 7, 2026 [S28]. A claim that all three suppliers have sold through 2027 output is unconfirmed [S69].

### Test and OSAT: relief lands late
Amkor raised its Arizona packaging and test campus plan to roughly US$12 billion as of September 2026 [S38]; NVIDIA's October 2026 announcements add Amkor capacity growth above 300% by end-2028, KYEC US facilities backed by a $1.1 billion reservation advance, and SPIL targeting 15x optical-engine capacity by mid-2027 [S45]. ASE+Amkor CoWoS-equivalent capacity of about 110,000 wpm is an end-2028 estimate [S47].

| Metric | Baseline (Oct 2026) | Central view 2027 | Range | Driver | Signpost |
|---|---|---|---|---|---|
| Conventional DRAM contract price | 4Q26 +10–15% QoQ forecast [S25] | rises persist into 1H27, then decelerate | +20% QoQ steps [S42] to declines | HBM wafer allocation | TrendForce quarterly releases |
| NAND contract price | 4Q26 +15–20% QoQ forecast [S25] | gains fade through 2027 | sharp rises to correction | AI server pull | TrendForce releases |
| Mature-node lead time | 4–17 weeks, ample [S1] | ample; prices +5–10% [S37] | tightens only on export shock | China additions | UMC/GF/SMIC earnings |
| OSAT advanced capacity | additions dated 2027–28 [S45][S38] | test lanes loosen late 2027 | KYEC/SPIL milestones [S45] | tool lead times | company disclosures |

Supply-demand: the binding constraint in mainstream memory is allocation of DRAM wafers to HBM, cleared by price and LTA caps [S26], not new capacity. Under AI-led broad tightness — 40% this persists through 2027; under Oversupply and correction — 15% an AI air pocket or control shock flips it. Falsifiers: TrendForce 1H27 prints showing sequential declines, or a confirmed Rubin Ultra HBM cut [S8].

## Export controls and geopolitical propagation

Two synchronized clocks expire inside the horizon. The BIS Affiliates Rule suspension runs only "until November 9, 2026" absent a Federal Register extension [S14], and China's Announcement No. 70 pause of the October 2025 rare-earth controls ends 10 November 2026 with no extension published as of 16 October 2026 [S15]. Washington says the Busan truce was extended to 10 January 2027 per Treasury Secretary Bessent's 23 September 2026 statement, but BIS has published no matching notice [S16].

| Stage | Date | Rung | Record | Next decision |
|---|---|---|---|---|
| SMIC added to US Entity List | Dec 2020 | entity listing | [S70] | licence-by-licence exports |
| China Ga/Ge export licensing | 2023-07-03, effective 2023-08-01 | licensing | [S59] | in force |
| China prohibits Ga/Ge/Sb to US in principle | 2024-12-03 | directive | MOFCOM Notice 2024 No. 46 [S71][S59] | in force |
| Heavy-REE per-shipment licensing (Tb, Dy, Sm, Gd, Lu, Sc, Y) | 2025-04-04 | licensing, never paused | Announcement No. 18 of 2025 [S72][S15] | none |
| US suspends Affiliates Rule one year | published 2025-11-12; effective through 2026-11-09 | final rule | [S14] | BIS extension notice before 2026-11-10, else automatic resumption |
| China suspends Oct 2025 REE/magnet controls | 2025-11-07, until 2026-11-10 | suspension | Announcement No. 70 [S15] | MOFCOM extension notice |
| Busan truce extension | stated 2026-09-23 | political statement | [S16] | matching legal text by 2027-01-10 |

### Measured effects
US SME exports to China fell from $6.8 billion (2021) to $5.1 billion (2022), $4.4 billion (2023) and $4.2 billion (2024), excluding third-market sales [S60]. China's rare-earth exports fell 9.6% year on year to 43,711 tonnes in January–September 2026 even during the pause, while September 2026 rose 6.7% [S15]. After the August 2024 antimony limits, Chinese exports fell about 97% and antimony trioxide prices roughly doubled [S59]. US real exports of goods and services were 2814.538 Billions of Chained 2017 Dollars in 2026-Q2 versus 2659.32 in 2025-Q2 [S40].

### Propagation paths to end-2027
The suspended October 2025 measures are the direct semiconductor channel: extraterritorial licensing of foreign magnets containing ≥0.1% Chinese-origin heavy rare earths, and case-by-case licence review for rare-earth items used in sub-14nm semiconductors, next-generation memory, and semiconductor manufacturing or testing equipment [S73]; from 1 December 2025 they would largely deny military-affiliated applicants [S73]. If neither side extends by 10 November 2026, these revive simultaneously with the Affiliates Rule [S14][S15][S16]. China produces approximately 98% of refined gallium [S59], but gallium/germanium mainly affect GaAs/SiC/power-RF and epitaxy rather than leading-edge CMOS; the evidence quantifies no dependence of 300mm wafers, ABF substrates, photoresist or specialty gases on China-origin inputs. Because mature-node technology, certain equipment and materials remain licensable [S60], controls slow rather than halt China's mature-node build-out. The IEA estimates full enforcement could put $6.5 trillion a year of downstream production outside China at risk, with planned non-China magnet capacity covering only about a third of expected needs by 2035 [S15].

Balanced chain — 20% requires both extensions published; Oversupply and correction — 15% can open via simultaneous reinstatement hitting demand; AI-led broad tightness — 40% and Packaging-only bottleneck — 25% assume friction without rupture. No source in the evidence publishes a probability or window for a Taiwan or Kyushu earthquake disrupting fabs before end-2027; available coverage only describes the April 2024 magnitude-7.4 Taiwan earthquake [S74][S75].

## Base rates and historical precedents

### Resolution speeds across five episodes

Five episodes since 2017 set the prior for how fast announced capacity clears a bottleneck. A count of the stored US utilization series (NAICS 3344) shows utilization falling back below 76% within 18 months of a local peak above 80% in only one of two non-overlapping episodes: after the January 2018 peak of 84.069%, the series was below 76% by November 2018; after the February 2022 peak of 92.195%, the first print below 76% was 74.164% in January 2024, about 23 months (own count) [S3]. The series then troughed at 71.096% in March 2026 and rose to 76.51% in September 2026 against 73.723% in September 2025 — a real tightening, still short of 2021-22 extremes [S3].

| Reference class | Period and outcome | Cleared within 18 months | Source class | Prior it sets |
|---|---|---|---|---|
| Commodity memory (DRAM 2017-18) | Jan 2018 peak 84.069% to sub-76% by Nov 2028 — sub-76% by Nov 2018, own count [S3] | Yes | Official series | Fungible capacity clears fast |
| Multi-segment cycle (2021-22) | Feb 2022 peak 92.195% to 74.164% in Jan 2024, ~23 months, own count [S3] | No | Official series | ~2-year loosening tail |
| Capability/materials (ABF 2020-23) | ~3 years from onset to glut; ran through 2023 despite 2022-clearing forecasts [S13][S76] | No | Trade press | Re-tightens after a glut |
| Capability/AI (CoWoS 2023-) | 10+ quarters; capacity doubled in 2024 and 2025 yet still called insufficient in Oct 2025; ~35,000 wpm late-2024 to ~130,000 wpm projected late-2026 [S12][S67] | No | Analyst restatements of TSMC statements | Doubling capacity ≠ clearing the gap |
| AI-structural (HBM 2024-) | 10-12 quarters; 2027 output reported sold out; supplier inventory below 10 days in Sept 2026 (KB Securities estimate) [S11] | No | Cycle analysis | Allocation regimes persist |

Roughly one to two of five episodes cleared within 18 months, and both fast cases were commodity segments where new capacity was fungible; capability and AI-structural episodes ran 10-12+ quarters [S3][S11][S12][S13][S76]. CoWoS is the template: TSMC could fill only about 80% of CoWoS demand in 2023 while planning a lift from 8,000 toward 11,000 wafers per month, and the constraint outlived successive doublings [S77][S78][S67]. ABF shows re-tightening risk: after the 2023 glut, 2026 lead times are again reported at 48-56 weeks — up to 4.7 times equilibrium — with Ajinomoto raising ABF film prices 30% [S30][S31]. The October 2026 cycle analysis reads similarly: prior DRAM cycles ran about 36 and 39 months, with downturns preceded by inventory builds six to nine months ahead and inventory norms of 10-15+ weeks, versus below 10 days at Samsung and SK Hynix in September 2026 [S11].

### Indicators that led the turns

Equipment billings led every prior turn: SEMI's quarterly billings report, released about five weeks after quarter end, printed a record US$40.53 billion in Q2 2026, up 23% year over year and a second consecutive record [S10], after year-over-year growth of +21% (Q1 2025), +24% (Q2 2025), +11% (Q3 2025), +14% (Q1 2026) and +23% (Q2 2026) [S66]; SEMI also reported $135 billion for full-year 2025 [S66]. Supplier statements now carry the same signal: ASML said on 14 October 2026 that supply "as currently planned for both 2027 and 2028 will not fully meet the demand of our customers" [S2], and TSMC said on 15 October 2026 that "the tool supply is tight" while guiding 2026-2028 capex "even more significantly higher than the past three years" [S17]. Output confirms the push: NAICS 3344 industrial production reached 198.6335 Index 2017=100 in September 2026, up 19.899% from 165.667 a year earlier [S4].

This record centers the frame on AI-led broad tightness — 40% — whose prior is that HBM and CoWoS shortages persisted 6-8 quarters in 2023-25, and holds Balanced chain — 20% — to a 4-6-quarter clearing prior that matches only the commodity subset of the reference class.

No source in the evidence publishes a probability or window for fab outages, Taiwan or Kyushu earthquakes, or an export-control shock before end-2027; the rates above therefore embed no hazard adjustment.

## Scenario frame for 2027 chain tightness

### Scenario Probability Distribution
- **AI-led broad tightness (40% probability):** Accelerator demand outruns CoWoS/SoIC and HBM4 ramps, keeping advanced packaging and HBM binding into 2027 and spilling into leading-edge logic; prior: HBM and CoWoS shortages persisted 6-8 quarters in 2023-25.
- **Packaging-only bottleneck (25% probability):** Capacity additions elsewhere catch up by mid-2027 but CoWoS/SoIC and substrates remain the single binding constraint as in 2023-24, when packaging lagged wafer capacity by about a year.
- **Balanced chain (20% probability):** Record 2026-27 capex and sold-out 2027 memory books clear the gaps, leaving only isolated, short allocation episodes; prior: most announced semiconductor capacity ramps close shortages within 4-6 quarters.
- **Oversupply and correction (15% probability):** An AI demand air pocket or export-control shock flips HBM and mainstream memory into oversupply by late 2027, echoing the 2019 and 2023 memory downturns.

### Reference classes

| Reference class | Counting rule | k/n | Window | Source | Applicability |
|---|---|---|---|---|---|
| Commodity memory bottleneck clears within 18 months of supply passing demand | episode resolved within 18 months | 1/2 | DRAM 2017-18; DRAM 2021-22 | US NAICS 3344 utilization peaked at 92.195% (2022-02), first print below 76% at 74.164% (2024-01), about 23 months [S3]; cycle analysis [S11] | mainstream DRAM/NAND |
| Capability/AI-structural bottleneck persists past 18 months | still binding at 18 months | 3/3 | CoWoS 2023-; HBM 2024-; ABF 2020-23 | TSMC's CEO, 16 Jul 2026: packaging "so tight that now it's limiting my customers' growth" [S1]; HBM sold out into 2027 [S11]; the ABF episode ran about three years [S13][S76] | CoWoS/SoIC, HBM, substrates |

Blended, 1-2 of 5 documented episodes cleared within 18 months, and the 3/3 structural class fits the frame's core segments.

### Anchor → adjustment bridge

| Scenario | Anchor (class, k/n) | Adjustments: mechanism, evidence | Why not already in class | Reads vs frame weight |
|---|---|---|---|---|
| AI-led broad tightness — 40% | Structural persistence, 3/3 | ASML, 14 Oct 2026: 2027-28 planned supply "will not fully meet the demand" [S2]; TSMC: "the tool supply is tight" [S17] | Spillover into N2 logic is not given by the class | consistent |
| Packaging-only bottleneck — 25% | Split: structural 3/3 (packaging); commodity 1/2 (rest) | CoWoS gap narrows from ~20% to ~10% by end-2026 [S20]; Unimicron's chairman warns of 30-month equipment lead times and a possible 20% materials shortfall in 2027 [S51] | Assumes logic and memory clear on schedule | consistent |
| Balanced chain — 20% | Commodity resolution, 1/2 | Record billings of US$40.53 billion in Q2 2026, +23% YoY [S10]; CoWoS capacity CAGR above 80% (2022-2027) [S20] | Samsung/SK Hynix inventory below 10 days (Sept 2026) means 2027 clears by price, not availability [S28] | leans lower |
| Oversupply and correction — 15% | Commodity flip, 1/2 | Downturns followed 10-15+ weeks of inventory versus below 10 days now [S11][S28]; US utilization 76.51% (2026-09) sits far below the 92.195% (2022-02) pre-glut peak [S3] | Needs an AI air pocket or export shock, not cycle mechanics; TSMC is already "prudent" on 2027 [S17] | leans lower |

### Paths, signposts and movers

AI-led broad tightness runs through an equipment-capped ramp — ASML short [S2], TSMC's tools tight [S17] — so funded logic and packaging slip together and scarcity carries into N2. Watch ASML's next quarterly report, TSMC's January 2027 capex guidance [S17], SEMI billings roughly five weeks after quarter-end [S10], and whether Rubin Ultra keeps 12-Hi stacks [S79] or the reported 8-Hi switch lands [S42]. Packaging-only bottleneck holds where wafers and memory clear by mid-2027 but substrate relief dated Q1 2028 to mid-2028 cannot [S45]. Balanced chain requires TrendForce's reported forecast of a 121% YoY rise in 2027 HBM blended ASP to be revised down [S25]. Oversupply and correction first prints as supplier inventories rebuilding above roughly 10 weeks [S11]; its dated branch is the 9-10 November 2026 expiry of the BIS Affiliates Rule suspension and of MOFCOM Announcement No. 70's pause [S14][S15].

### Binary map

| Binary | Record and threshold | Resolves yes or partly under |
|---|---|---|
| BIS Affiliates Rule suspension lapses without a Federal Register extension (event) | Federal Register default 9 Nov 2026 [S14]; rollover to 10 Jan 2027 expected but unpublished [S16] | Oversupply and correction; odds not derivable |
| CoWoS supply-demand gap at or below 10% on 31 Dec 2027 (end-state) | TrendForce basis; ~20% mid-2026 [S20] | Balanced chain only |
| ASML reiterates a 2027 supply shortfall at Q4 2026 results (event) | Statement of 14 Oct 2026 [S2] | AI-led broad tightness; Packaging-only bottleneck |

Each question is an event or end-state inside the horizon; a later deadline or easier threshold is never less likely.

No market rows appear in the assembled evidence; a matching market would have to resolve terms such as a CoWoS gap above or below 10% on 31 Dec 2027, or TrendForce's 2027 HBM blended-ASP outcome [S25].

No source in the assembled evidence publishes a probability or window for an exogenous disruption — fab outage, Taiwan/Kyushu earthquake or geopolitical escalation — before end-2027.

## Ranked bottlenecks and binary forecasts

Under the central scenario, AI-led broad tightness — 40%, the binding constraints stay in AI bill-of-materials segments: of five named bottleneck episodes since 2020, only the commodity memory cycles resolved within 18 months [S11][S12][S13]. US semiconductor utilization of 76.51% (2026-09), against the 92.195% peak (2022-02), shows tightening without broad scarcity, even as output rose 19.899% year on year [S3][S4]. ASML states its 2027-28 supply "will not fully meet the demand of our customers"; TSMC says "the tool supply is tight" [S2][S17].

### Ranked bottlenecks (probabilities and durations are our forecasts)

| # | Segment | P demand exceeds capacity before end-2027 | Expected duration | Severity | Owners → beneficiaries | Basis |
|---|---|---|---|---|---|---|
| 1 | CoWoS/SoIC packaging | 85% | binding since mid-2023; through most of 2027 | high — 52-78-week lead times; NVIDIA ~60% of 2026 wafers | TSMC → ASE, Amkor, Intel | [S1][S20][S47] |
| 2 | HBM (HBM3E/HBM4) | 85% | through late 2027 | very high — 2027 blended ASP forecast +121% YoY | SK Hynix, Samsung, Micron | [S5][S25][S11] |
| 3 | ABF substrates | 70% | into 2028 | high — 20-28-week lead times; ASP ~$65 (2024) to ~$82 (2025); 20% 2027 materials gap warned | IBIDEN, Unimicron, Shinko, AT&S → Ajinomoto | [S29][S45][S52][S51] |
| 4 | EUV/High-NA and etch/deposition tools | 60% | through 2028 | capability gate on all leading-edge ramps | ASML → Applied Materials, Lam, TEL | [S2][S17] |
| 5 | Conventional DRAM | 55% | through at least 1H27 | high — +10-15% QoQ forecast in 4Q26 | Samsung, SK Hynix, Micron → CXMT (10% share) | [S24][S25] |
| 6 | 300mm wafers | 40% | episodic into 2029 | moderate — price, not allocation | SUMCO, GlobalWafers | [S10][S55][S32] |

Relief mostly lands after 2027 — IBIDEN's Ono ramp begins Q1 2028, Unimicron's expansion completes mid-2028, Amkor's +300% by end-2028 — so 2027 gaps clear through price, backlog and spillover to ASE/Amkor/Intel [S45][S47].

### Binary forecasts (resolution anchored to company earnings, SEMI, TrendForce, official filings)

| # | Binary | P | Resolution record |
|---|---|---|---|
| 1 | TSMC CoWoS-equivalent capacity reaches ≥200,000 wpm in 2027 | 55% | TrendForce/Economic Daily News estimates [S20][S46] |
| 2 | CoWoS-S/L lead times still ≥52 weeks at 30 Jun 2027 | 65% | trade-report trackers [S1] |
| 3 | 2027 HBM blended ASP rises ≥100% YoY | 60% | TrendForce HBM releases [S25] |
| 4 | SK Hynix HBM revenue share ≥45% in every 2027 quarter | 65% | Counterpoint quarterly tracker [S24] |
| 5 | Conventional DRAM contract prices +≥10% QoQ in 1Q27 | 55% | TrendForce [S25] |
| 6 | ASML FY2027 total net sales ≥€45 billion | 75% | ASML annual report [S2] |
| 7 | High-NA revenue recognized in ≥2 quarters of 2027 | 60% | ASML quarterly statements (1 sold Q3 2026, reported) [S34] |
| 8 | IBIDEN Ono mass production starts by 31 Dec 2027 | 30% | IBIDEN notices (announced ramp from Q1 2028) [S45][S52] |
| 9 | Unimicron KF expansion adds capacity by 30 Jun 2027 | 70% | NVIDIA/Unimicron disclosures [S45] |
| 10 | BIS publishes a Federal Register extension of the Affiliates Rule suspension before it lapses 10 Nov 2026 | 65% | Federal Register [S14][S16] |
| 11 | China does not reinstate the suspended October 2025 rare-earth notices through 31 Mar 2027 | 60% | MOFCOM announcement list [S15] |
| 12 | SEMI WWSEMS reports a record billings quarter in 2027 | 75% | SEMI quarterly release (record $40.53bn in Q2 2026) [S10][S66] |
| 13 | Rubin Ultra ships H2 2027 with 8-Hi HBM4 (~192 GB) after the reported quad-die cancellation | 55% | NVIDIA roadmap disclosure [S8][S9] |

The view shifts toward Balanced chain — 20% if TrendForce reports the CoWoS gap below 5% by mid-2027 [S20], and toward Oversupply and correction — 15% if supplier DRAM inventories rebuild above four weeks by Q2 2027 [S11]. Reviewed hazard sources discuss Taiwan earthquake exposure qualitatively (the April 2024 magnitude-7.4 event) but publish no probability or window for exogenous disruption before end-2027 [S74][S75].

## Signposts and monitoring calendar

### Dated indicators and thresholds

| Indicator (next reading) | Latest reading | Threshold and window | Moves |
|---|---|---|---|
| SEMI WWSEMS billings (Feb 2027 for Q4 2026) | US$40.53 billion in Q2 2026, +23% YoY, +11% QoQ [S10]; YoY path +14% Q1 2026 [S66] | Two consecutive prints below +10% YoY before Q4 2027 | Balanced chain — 20% |
| ASML quarterly report (Jan 2027) | Q3 2026 net sales €11.7 billion; supply for 2027–28 "will not fully meet the demand of our customers" [S2]; TSMC corroborates: "the tool supply is tight" [S17] | Shortfall sentence dropped after the planned 30% low-NA EUV/DUV immersion increase for 2027 [S2] | AI-led broad tightness — 40% |
| TSMC Q4 2026 call (Jan 2027) | Q3 2026 revenue US$46.7 billion; Q4 guide US$52.3–54.3 billion; 2026–28 capex "even more significantly higher than the past three years" [S17] | Capex cut, or packaging no longer "limiting my customers' growth" (16 Jul 2026) [S1] | AI-led broad tightness — 40% |
| Memory earnings (late Oct–Nov 2026) | Samsung/SK Hynix finished-memory inventory below 10 days of supply (estimate, 7 Sep 2026) [S28]; Micron TrendForce-reported at ~100,000 HBM wpm by Dec 2026 [S28] | Supplier inventories back above ~2 weeks during 2027 | Oversupply and correction — 15% |
| TrendForce contract prices (monthly) | 4Q26 forecast: DRAM +10–15% QoQ, NAND +15–20% QoQ [S25] | Two consecutive quarters below +5% QoQ in 2027 | Oversupply and correction — 15% |
| CoWoS capacity and gap (quarterly estimates) | Gap ~20% mid-2026 seen narrowing to ~10% by end-2026 [S20]; 2027 capacity estimated ~200,000 wpm [S46]; rumor of at least 200,000 wpm [S48] | Gap re-widening above ~15%; 52–78-week lead times persisting [S1] | Packaging-only bottleneck — 25% |
| Substrate equipment/materials | Unimicron (20 Oct 2026): over 80% of equipment lead times lengthened, some 30 months; ~20% material shortfall flagged for 2027 in low-CTE glass fiber cloth, CCL and ABF [S51] | Unimicron KF adds capacity from Q2 2027; IBIDEN Gama Cell6 mass production from FY2027 [S45][S52] | Packaging-only bottleneck — 25% |
| FRED NAICS 3344 utilization (mid-Nov 2026) | 76.51% in Sep 2026 vs 73.723% Sep 2025; 5-year range 71.096%–92.195% [S3] | Sustained break above 80% before Dec 2027 | AI-led broad tightness — 40% |
| US real exports of goods and services (quarterly) | 2814.538 billions of chained 2017 dollars in 2026-Q2, +5.837% YoY [S40] | Two consecutive falling quarters | AI-led broad tightness — 40% |

### Policy cliffs in the window

The Affiliates Rule suspension runs "until November 9, 2026" and lapses absent a Federal Register extension; none was published as of 1 October 2026 [S14]. Treasury announced a truce extension to 10 January 2027 on 23 September 2026, with an Affiliates extension "expected" but unpublished [S16]; MOFCOM's Announcement No. 70 pause lapses 10 November 2026 with no extension notice as of 16 October 2026 [S15]. Friction is measurable: China's rare-earth exports fell 9.6% year-on-year to 43,711 tonnes in January–September 2026 [S15]. A joint lapse is the dated trigger for the export-control shock inside Oversupply and correction — 15%; mutual extensions shift weight toward Balanced chain — 20%.

### Capability events

Samsung SF2 yield is reported near 30% in Q1 2026 rising to ~50% by late 2026 — leak-based and unconfirmed by Samsung [S21][S22]; SPIL targets 15x optical-engine capacity by mid-2027 under NVIDIA's reservation program [S45].

### What would change the view

- ASML's Q4 2026 release drops the 2027–28 shortfall sentence → downgrade AI-led broad tightness — 40% [S2].
- TSMC's January 2027 call describes packaging as balanced → weight to Balanced chain — 20% [S17][S1].
- TrendForce prints DRAM below +5% QoQ with supplier inventories above two weeks → Oversupply and correction — 15% [S25][S28].
- SEMI's forecast of 11.8% silicon-wafer shipment growth in 2026 with records through 2029 [S10] is cut while the CoWoS gap re-widens → Packaging-only bottleneck — 25% [S20].

No source in the evidence publishes a probability or time window for a fab outage, a Taiwan or Kyushu earthquake, or any other exogenous disruption before end-2027; available coverage is qualitative exposure description only [S80][S74][S75].

## News and market context

### News and market context
Context only; not probability anchors or resolution evidence. News snippets are not fetched full text. Publication dates do not establish historical availability.

| Provider / kind | Source | Published / retrieved | Status / captured contract |
| --- | --- | --- | --- |
| newsapi | — | — | timeout (transport\_timeout) |

## References

- [S1] Is TSMC CoWoS Sold Out in 2026? What TSMC Said — https://siliconanalysts.com/analysis/foundry-allocation-status-q1-2026 (tier 3; fetched)
- [S2] ASML reports €11.7 billion total net sales and €5.0 billion net income in Q3 2026 | Wed, 10/14/2026 - 07:00 — https://investor.asml.com/news-releases/news-release-details/asml-reports-eu11.7-billion-total-net-sales-and-eu5.0-billion-net-income-q3-2026 (tier 3; fetched)
- [S3] Capacity Utilization: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States — https://fred.stlouisfed.org/series/CAPUTLG3344S?drf_series=fred%3ACAPUTLG3344S (tier 1; fetched)
- [S4] Industrial Production: Manufacturing: Durable Goods: Semiconductor and Other Electronic Component (NAICS = 3344) — United States — https://fred.stlouisfed.org/series/IPG3344S?drf_series=fred%3AIPG3344S (tier 1; fetched)
- [S5] Inside NVIDIA Rubin GPU Architecture: Powering the Era of Agentic AI | NVIDIA Technical Blog — https://developer.nvidia.com/blog/inside-nvidia-rubin-gpu-architecture-powering-the-era-of-agentic-ai/ (tier 3; fetched)
- [S6] NVIDIA GPU Roadmap 2026-2030: Rubin, Rubin Ultra, Feynman — https://vrlatech.com/nvidia-gpu-roadmap-2026-2030/?srsltid=AYCX9vIcDsO4oy5ser6bGaI535zV9_lLnNIUb9w8m-J5WEnTbnCg-Dlb (tier 3; search snippet)
- [S7] NVIDIA GPU Roadmap 2026-2030: Rubin, Rubin Ultra, Feynman — https://vrlatech.com/nvidia-gpu-roadmap-2026-2030/?srsltid=AYCX9vLiJakDeqo-C7kMEt1ZZpX5_ypVT7caa-Luwp3jnWDfGsoGMQzw (tier 3; search snippet)
- [S8] Nvidia Scraps Quad-Die Rubin Ultra GPU Design, Cites Packaging Yield ... — https://mlq.ai/news/nvidia-scraps-quad-die-rubin-ultra-gpu-design-cites-packaging-yield-issues/ (tier 3; search snippet)
- [S9] Nvidia Rubin Ultra will ship with 192GB of HBM4 8-hi. Not only is ... - X — https://x.com/SemiAnalysis_/status/2091994110911557679?lang=en (tier 3; search snippet)
- [S10] Global Semiconductor Equipment Billings Increased 23% Year-Over-Year in Q2 2026, SEMI Reports | SEMI — https://www.semi.org/en/semi-press-release/global-semiconductor-equipment-billings-increased-23-percent-year-over-year-in-q2-2026-semi-reports (tier 3; fetched)
- [S11] DRAM Cycle October 2026: Q4 Prices, HBM & Peak Timing — https://www.useluminix.com/reports/industry-analysis/dram-cycle-position-analysis-peak-timing-indicators (tier 3; fetched)
- [S12] Report: TSMC to Double CoWoS Capacity by 2028 as AI Chip ... — https://wccftech.com/report-tsmc-to-double-cowos-capacity-by-2028-as-ai-chip-shortage-spills-over-to-rivals/ (tier 3; search snippet)
- [S13] ABF SUBSTRATE SHORTAGES: SEMICONDUCTOR SUPPLY CHAIN — https://a2globalelectronics.com/shortage-mitigation/abf-substrate-shortages/ (tier 3; search snippet)
- [S14] Federal Register — https://www.federalregister.gov/documents/2025/11/12/2025-19846/one-year-suspension-of-expansion-of-end-user-controls-for-affiliates-of-certain-listed-entities (tier 1; fetched)
- [S15] China Rare Earth Export Pause: What Ends on 10 November — https://www.technology.org/2026/10/19/china-rare-earth-export-pause-november-10/ (tier 3; fetched)
- [S16] BIS Affiliates Rule Suspension Extended but Uncertainty Remains: Miller Canfield — https://www.millercanfield.com/resources-BIS-Affiliates-Rule-Suspension-Extended.html (tier 1; fetched)
- [S17] Q3 2026 Taiwan Semiconductor Manufacturing Company Limited Earnings Call (Chinese, English) on October 15, 2026 / 6:00AM — https://investor.tsmc.com/chinese/encrypt/files/encrypt_file/reports/2026-10/eba4fac72873bf546b669bd2b5d973df5c93215d/TSMC%203Q26%20Transcript.pdf (tier 3; fetched)
- [S18] TSMC 'prudent' going into 2027 after posting sixth straight quarter of record profit | Reuters — https://www.reuters.com/world/asia-pacific/tsmc-expected-report-sixth-straight-quarter-record-profit-thanks-ai-boom-2026-10-14/ (tier 2; fetched)
- [S19] Semiconductor Allocation Dashboard — Live Foundry Capacity & Lead Time Tracker — https://siliconanalysts.com/tools/allocation (tier 3; fetched)
- [S20] [News] TSMC CoWoS Supply-Demand Gap Reportedly Seen Narrowing from 20% to 10% by End-2026 — https://www.trendforce.com/news/2026/06/15/news-tsmc-cowos-supply-demand-gap-reportedly-seen-narrowing-from-20-to-10-by-end-2026-as-capacity-expands/ (tier 3; fetched)
- [S21] Samsung's 2nm SF2 yield has climbed to roughly 60 ... - Instagram — https://www.instagram.com/p/Dd3dchWm2_j/ (tier 3; search snippet)
- [S22] Jukan on X: "Samsung Electronics Foundry Strikes Back, Begins Mass ... — https://x.com/jukan05/status/1972815934764220807 (tier 3; search snippet)
- [S23] Samsung 2nm Yield Reaches 50% - SmBom — https://www.smbom.com/news/46255?srsltid=AYCX9vKwgMc6B7bkCw2Cpil-R5ZrV-1Fis5OQ2blOv5riPrv4NfoRkr0 (tier 3; search snippet)
- [S24] Global DRAM and HBM Market Share: Quarterly — https://counterpointresearch.com/en/insights/global-dram-and-hbm-market-share (tier 3; fetched)
- [S25] AI Server Demand Sustains Memory Contract Price Increases in 4Q26, While Consumer-Side Pressure Persists, Says TrendForce — https://www.trendforce.com/presscenter/news/20260930-13258.html (tier 3; fetched)
- [S26] Long-Term Agreements Cap Price Increases; Server DRAM Contract ... — https://www.trendforce.com/presscenter/news/20260709-13140.html (tier 3; search snippet)
- [S27] Memory Prices Soar; DRAM and NAND Flash to Account for 68% of ... — https://www.trendforce.com/presscenter/news/20260825-13198.html (tier 3; search snippet)
- [S28] HBM4 Shortage: DRAM Inventory Falls Below 10 Days — https://tech-insider.org/hbm4-memory-shortage-dram-inventory-2026/ (tier 3; fetched)
- [S29] The ABF Substrate Bottleneck - by Chris Zeoli — https://www.datagravity.dev/p/the-abf-substrate-bottleneck (tier 3; fetched)
- [S30] AI Component Crunch Becomes Reality: ABF Substrate Lead Times ... — https://finance.biggo.com/news/02cf5c8f-c58d-45f8-a7a3-8fe37716bc8f (tier 3; search snippet)
- [S31] Ajinomoto Raises ABF Substrate Film Prices 30% as AI Demand Extends ... — https://www.atlaspcb.com/news/news-ajinomoto-abf-substrate-price-increase-2026/ (tier 3; search snippet)
- [S32] [PDF] GlobalWafers (6488TT) Q3 2024 Earnings Call — https://www.sas-globalwafers.com/%E6%92%AD%E5%A0%B1%E7%89%88gwc_company-profile_20241105-en/ (tier 3; search snippet)
- [S33] Sumco Corp. (SUMCF) Q2 FY2026 earnings call transcript — https://finance.yahoo.com/quote/SUMCF/earnings/SUMCF-Q2-2026-earnings_call-638313.html (tier 3; search snippet)
- [S34] ASML (ASML) Q3 2026 Earnings Call Transcript | The Motley Fool — https://www.fool.com/earnings/call-transcripts/2026/10/14/asml-asml-q3-2026-earnings-call-transcript/ (tier 3; search snippet)
- [S35] Three Companies Set to Dominate 2026 Profits in AI Chips — https://markmancapitalinsight.substack.com/p/three-companies-set-to-dominate-2026 (tier 3; search snippet)
- [S36] Trailing-edge foundry roadmaps for GlobalFoundries, UMC, and SMIC — mature node chipmakers each pursue differing strategies and IP | Tom's Hardware — https://www.tomshardware.com/tech-industry/semiconductors/the-trailing-edge-foundry-roadmap-examined (tier 3; fetched)
- [S37] GlobalFoundries climbs 8% on UMC pricing report - Yahoo Finance — https://ca.finance.yahoo.com/news/globalfoundries-climbs-8-umc-pricing-135009229.html (tier 3; search snippet)
- [S38] Dr. Change Column #16: Packaging Takes Center Stage: ASE's Next Move — https://techsoda.substack.com/p/dr-change-column-16-packaging-takes (tier 3; search snippet)
- [S39] Shin-Etsu Chemical responds to the growing demand and advances in the semiconductor photoresists market | News Release | News | Shin-Etsu Chemical Co., Ltd. — https://www.shinetsu.co.jp/en/news/news-release/shin-etsu-chemical-responds-to-the-growing-demand-and-advances-in-the-semiconductor-photoresists-market/ (tier 3; fetched)
- [S40] Real Exports of Goods and Services — United States — https://fred.stlouisfed.org/series/EXPGSC1?drf_series=fred%3AEXPGSC1 (tier 1; fetched)
- [S41] Real imports of goods and services — United States — https://fred.stlouisfed.org/series/IMPGSC1?drf_series=fred%3AIMPGSC1 (tier 1; fetched)
- [S42] [News] DRAM Prices Seen Rising 20% QoQ in 4Q26 Despite Slower Gains; AI Demand, Tight Supply Support Outlook — https://www.trendforce.com/news/2026/10/20/news-dram-prices-seen-rising-20-qoq-in-4q26-despite-slower-gains-ai-demand-tight-supply-support-outlook/ (tier 3; fetched)
- [S43] HBM4 Market Share 2026: Samsung vs SK Hynix vs Micron — https://siliconanalysts.com/analysis/hbm4-market-share-race-2026 (tier 3; fetched)
- [S44] [News] TSMC Reportedly Targets 22% 2nm, 16%+ 3nm Capacity ... — https://www.trendforce.com/news/2026/09/14/news-tsmc-reportedly-targets-22-2nm-16-3nm-capacity-boost-by-mid-2027-cowos-to-double-by-2028/ (tier 3; search snippet)
- [S45] NVIDIA and Supply Chain Partners Expand Capacity to Accelerate AI Infrastructure Buildout | NVIDIA Newsroom — https://nvidianews.nvidia.com/news/nvidia-and-supply-chain-partners-expand-capacity-to-accelerate-ai-infrastructure-buildout (tier 3; fetched)
- [S46] TSMC Earnings Q3 2026: Margins and Guidance Under Test — https://admiralmarkets.com/analytics/traders-blog/tsmc-earnings-q3-2026-preview (tier 3; search snippet)
- [S47] TSMC's CoWoS Capacity to Double to 260,000 Wafers by 2028; Intel and OSAT Providers Capture Spillover Orders — BigGo Finance — https://finance.biggo.com/news/adcec901-53b3-453f-bf00-8373ebb1bb97 (tier 3; fetched)
- [S48] Dan Nystedt on X: "Rumor: TSMC's 2027 CoWoS packaging capacity ... — https://x.com/dnystedt/status/2075374878644146511?lang=en (tier 3; search snippet)
- [S49] Samsung Shifts SF1.4 Foundry Target to 2029 as SF2 Roadmap Expands — https://mlq.ai/news/samsung-shifts-sf14-foundry-target-to-2029-as-sf2-roadmap-expands/ (tier 3; search snippet)
- [S50] Supply and Demand model for ABF | MicroEval - Artificial Analysis — https://artificialanalysis.ai/microevals/supply-and-demand-model-for-abf-1762908104429 (tier 3; search snippet)
- [S51] [News] Unimicron Warns of IC Substrate Crunch: Up to 30-Month Equipment Lead Times, 20% Material Gap in 2027 — https://www.trendforce.com/news/2026/10/20/news-unimicron-warns-of-ic-substrate-crunch-up-to-30-month-equipment-lead-times-20-material-gap-in-2027/ (tier 3; fetched)
- [S52] Notice Regarding Capital Investment Plan for High-Performance IC Package Substrates｜About IBIDEN News｜About IBIDEN｜IBIDEN CO.,LTD. — https://www.ibiden.com/company/2026/02/notice-regarding-capital-investment-plan-for-high-performance-ic-package-substrates.html (tier 3; fetched)
- [S53] Jukan on X: " Unimicron: Customers Rush to Lock In ABF Substrate LTAs — https://x.com/jukan05/status/2029745136499114216 (tier 3; search snippet)
- [S54] As Chips Get Bigger, ABF Substrates Shift from Component to Bottleneck — https://techsoda.substack.com/p/dr-change-column-15-as-chips-get (tier 3; search snippet)
- [S55] Growth Strategy Who We Are SUMCO CORPORATION — https://www.sumcosi.com/english/aboutus/growth.html (tier 3; search snippet)
- [S56] Sumco to put $2bn into new 300mm wafer capacity - Electronics Weekly — https://www.electronicsweekly.com/news/business/sumco-put-2bn-new-300mm-wafer-capacity-2021-10/ (tier 3; search snippet)
- [S57] Biden-Harris Administration Announces Preliminary Terms with ... — https://www.commerce.gov/news/press-releases/2024/07/biden-harris-administration-announces-preliminary-terms-globalwafers (tier 1; search snippet)
- [S58] GlobalWafers plans to raise prices of 12-inch silicon wafers in the 2nd ... - X — https://x.com/dnystedt/status/2051822953365713029 (tier 3; search snippet)
- [S59] China’s Export Controls: Critical Minerals and Strategic Pressure Points. — https://anderseninstitute.org/chinas-export-control-architecture-and-its-use-of-critical-minerals-as-strategic-pressure-points/ (tier 3; fetched)
- [S60] U.S. Export Controls and China: Advanced Semiconductors | Congress.gov | Library of Congress — https://www.congress.gov/crs-product/R48642 (tier 1; fetched)
- [S61] [PDF] ASML reports €11.7 billion total net sales and €5.0 billion net income in ... — https://ml-eu.globenewswire.com/Resource/Download/4beff1ba-33cc-4f21-b926-43b673c9708d (tier 3; search snippet)
- [S62] High-NA EUV: A Full Guide to ASML's 0.55 Optics and Why Most Chips ... — https://www.insidedeeptech.com/high-na-euv-lithography-full-guide/ (tier 3; search snippet)
- [S63] ASML Q3 2026 earnings show demand extending to 2030 — https://www.facebook.com/wei.liu.729/posts/asml-q3-2026-earnings-semiconductor-equipment-shortage-could-extend-beyond-2028k/10244429690061298/ (tier 3; search snippet)
- [S64] ASML ships first High-NA EUV tool; Intel takes lead as TSMC, Samsung ... — https://www.flytronics-group.com/articledetail/793.html (tier 3; search snippet)
- [S65] Tech News: Intel Reportedly Boosts ASML High-NA EUV Orders — https://www.linkedin.com/pulse/tech-news-intel-reportedly-boosts-asml-high-na-euv-orders-dwksc (tier 3; search snippet)
- [S66] Equipment Market Data | SEMI — https://www.semi.org/en/products-services/market-data/equipment (tier 3; fetched)
- [S67] Markets & Stocks - The Great Packaging Pivot: How TSMC is Doubling CoWoS Capacity to Break the AI Supply Bottleneck through 2026 — https://markets.financialcontent.com/wral/article/tokenring-2026-1-1-the-great-packaging-pivot-how-tsmc-is-doubling-cowos-capacity-to-break-the-ai-supply-bottleneck-through-2026 (tier 3; fetched)
- [S68] Memory Chip Market Forecast 2026: DRAM, NAND, HBM, and NOR Flash — https://www.ampheo.com/blog/memory-chip-market-forecast-2026-dram-nand-hbm-and-nor-flash?srsltid=AYCX9vIFxdUJMAzTi7q5PC8uM-ADPWyRzoQ3qKi8XIWgLvSmokBhvi6y (tier 3; search snippet)
- [S69] Samsung, SK Hynix, and Micron — have collectively sold through their ... — https://www.facebook.com/ign/posts/a-new-report-suggests-that-all-three-memory-manufacturers-samsung-sk-hynix-and-m/1622562369525562/ (tier 3; search snippet)
- [S70] Commerce Adds China's SMIC to the Entity List, Restricting Access to Key ... — https://2017-2021.commerce.gov/news/press-releases/2020/12/commerce-adds-chinas-smic-entity-list-restricting-access-key-enabling.html (tier 1; search snippet)
- [S71] Ministry of Commerce Notice 2024 No. 46 - CSET (Georgetown) — https://cset.georgetown.edu/publication/china-rare-earth-export-ban/ (tier 3; search snippet)
- [S72] MOFCOM Announcement No. 18 of 2025 - 商务部 — https://english.mofcom.gov.cn/Policies/AnnouncementsOrders/art/2025/art_0dd87cbee7b045bf93fabe6ab2faceee.html (tier 1; search snippet)
- [S73] China’s New Rare Earth and Magnet Restrictions Threaten U.S. Defense Supply Chains — https://www.csis.org/analysis/chinas-new-rare-earth-and-magnet-restrictions-threaten-us-defense-supply-chains (tier 2; fetched)
- [S74] TSMC controls 90% of the world's most advanced chips. A 7.4 ... — https://www.facebook.com/ChoiceHQ/videos/tsmc-controls-90-of-the-worlds-most-advanced-chips-a-74-earthquake-last-year-hal/2067402487491664/ (tier 3; search snippet)
- [S75] Semiconductor Production Threatened by Tragic Disaster in ... — https://www.ascm.org/ascm-insights/scm-now-impact/semiconductor-production-threatened-by-tragic-disaster-in-taiwan/ (tier 3; search snippet)
- [S76] ABF Substrate Shortages Impact Electronic Components Supply — https://www.fusionww.com/insights/abf-substrate-shortages-project-further-constraints-into-2021 (tier 3; search snippet)
- [S77] IFTLE 563: Is CoWoS Capacity Causing a GPU Shortage? — https://www.3dincites.com/2023/07/iftle-563-is-cowos-capacity-causing-a-gpu-shortage/ (tier 3; search snippet)
- [S78] TSMC CoWoS capacity constraints for 2024 | Sourceability — https://sourceability.com/post/tsmc-claims-ai-packaging-shortage-likely-through-2024-despite-expanding-capacity (tier 3; search snippet)
- [S79] NVIDIA Rubin GPUs Expected To Stick With 12-Hi HBM4 Despite ... — https://wccftech.com/nvidia-rubin-gpus-expected-to-stick-with-12-hi-hbm4-despite-reports-of-an-8-hi-shift-as-hbm-prices-could-surge-121-in-2027/ (tier 3; search snippet)
- [S80] Navigating Semiconductor Supply Chain Disruptions: Insights ... - Interos — https://www.interos.ai/blog/blog-navigating-semiconductor-supply-chain-disruptions-insights-from-taiwans-earthquake (tier 3; search snippet)

## Visual Annex

### Event Timeline

![Event Timeline](demos/semichain-2027/research-charts/timeline.png)

[Interactive version](demos/semichain-2027/research-charts/timeline.html)

_Dated key events driving the forecast, most recent window._

### Comparable Forecast Benchmarks

![Comparable Forecast Benchmarks](demos/semichain-2027/research-charts/quant_metrics.png)

[Interactive version](demos/semichain-2027/research-charts/quant_metrics.html)

_Strict same-denominator panels; hover retains source, as-of, and forecast status._

### Observed and Published Forecast Trajectories

![Observed and Published Forecast Trajectories](demos/semichain-2027/research-charts/metric_trajectories.png)

[Interactive version](demos/semichain-2027/research-charts/metric_trajectories.html)

_Three or more sourced points on one definition; x-axis is period end, not publication date._
