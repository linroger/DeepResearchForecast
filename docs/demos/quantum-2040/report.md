# Quantum Computing 2026–2040: Fault-Tolerance Timelines, Tri-Polar Competition, and the Economic Reckoning

<!-- binary-forecast-block:start -->
## Part 1 — Binary Forecasts

<!-- viz:charts/binary_forecast_dotplot.html -->
![Binary Forecasts — P(yes)](demos/quantum-2040/charts/binary_forecast_dotplot.png)

*Binary Forecasts — P(yes)*

Independent binary (yes/no) forecasts, each with a probability and an objective resolution test (metric · threshold · date · source). Probabilities express genuine conviction, not hedging.

| # | Forecast (one sentence) | Prob. | Resolution criteria | Theme |
|---|---|---|---|---|
| F1 | By December 31, 2033, at least one vendor has an independently verified (DARPA QBI or peer-reviewed) machine running at least 100 logical qubits with logical error rate at or below 1e-6. | 45% | Metric: independently verified logical qubit count and logical error rate; threshold ≥100 logical qubits at ≤1e-6; window: on or before 2033-12-31; resolved by DARPA QBI Stage C verdicts or Nature/Science/PRL peer-reviewed publications. | ai |
| F2 | By December 31, 2030, a third-party-verified quantum computer with at least 200 logical qubits completes a commercially relevant task in hours that no classical supercomputer can finish in reasonable time. | 15% | Metric: verified machine with ≥200 logical qubits completing a non-contrived commercial task infeasible classically; threshold as stated; window: on or before 2030-12-31; resolved by DARPA QBI verification or Nature/Science-level peer review. | ai |
| F3 | By December 31, 2033, at least two of the three quantum-winter conditions hold (no independently verified ≥50-logical-qubit machine at ≤1e-6, QED-C revenue under $2 billion with private investment down ≥50% from the 2025 peak, and at least two of IonQ/Rigetti/D-Wave delisted or cheaply acquired). | 30% | Metric: count of the three winter conditions satisfied; threshold ≥2; window: on or before 2033-12-31; resolved by DARPA QBI verdicts, QED-C State of the Global Quantum Industry reports, and public market data on IonQ, Rigetti, D-Wave. | ai |
| F4 | A cryptographically relevant quantum computer capable of breaking RSA-2048 in practical time is publicly demonstrated by December 31, 2035. | 12% | Metric: public demonstration of RSA-2048 factorization or equivalent attack on a real machine; threshold: demonstrated by a credible lab; window: on or before 2035-12-31; resolved by peer-reviewed publication or government announcement. | ai |
| F5 | NIST's transition guidance is finalized so that RSA and elliptic-curve cryptography are formally disallowed for US federal use after 2035, as drafted in IR 8547. | 80% | Metric: status of NIST IR 8547 final version; threshold: RSA/ECC disallowed after 2035 as in the draft; window: final publication checked by 2035-12-31; resolved by NIST Computer Security Resource Center. | ai |
| F6 | IBM's claim that users will demonstrate quantum advantage over classical computing by the end of 2026 is borne out by an acknowledged user demonstration on a Nighthawk-class system by December 31, 2026. | 30% | Metric: user-demonstrated quantum advantage claim on IBM hardware; threshold: publicly acknowledged demonstration; window: on or before 2026-12-31; resolved by IBM announcements and independent expert commentary. | ai |
| F7 | Global quantum computing industry revenue reaches at least $3 billion in 2028, matching the QED-C projection. | 42% | Metric: annual global quantum computing revenue (QED-C definition); threshold ≥$3 billion; window: fiscal year 2028; resolved by QED-C State of the Global Quantum Industry report (2029 edition). | ai |
| F8 | China's domestic dilution-refrigerator and helium-3 alternative supply reaches at least 30% of its quantum cryogenics demand by December 31, 2035, insulating it from the European-controlled choke point. | 70% | Metric: share of Chinese quantum program cryogenic demand met by domestic dilution refrigerators or helium-3 substitutes; threshold ≥30%; window: on or before 2035-12-31; resolved by RUSI/analyst supply-chain assessments and Chinese vendor disclosures (QuantumCTek, Origin, Liangyi). | ai |
| F9 | The US National Quantum Initiative reauthorization (S.3597 or successor) is enacted into law by December 31, 2027. | 62% | Metric: enactment status of NQI reauthorization legislation; threshold: signed into law; window: on or before 2027-12-31; resolved by Congress.gov bill status. | ai |
| F10 | Quantum-related items on US/EU export control lists grow by at least 20% between 2026 and December 31, 2035 relative to the 2026 baseline. | 75% | Metric: count of quantum-related controlled items in the US Commerce Control List and EU dual-use list; threshold ≥20% increase; window: 2026 baseline to 2035-12-31; resolved by Federal Register Entity List/CCL rulemakings and EU dual-use list updates. | ai |

_10 forecasts; 7 high-conviction (≥70% or ≤30%); 10 with objective criteria._
<!-- binary-forecast-block:end -->

Through 2040, the US most likely delivers the first early fault-tolerant machines around 2030–2033 and dominates commercialization, but large-scale economic value arrives only after 2035, post-quantum cryptography migration costs land before quantum commercial value, and export-control-driven supply chain splits push the global landscape toward multipolarity rather than hegemony. [S114]

---

## Part 2 — Framework & Synthesis

### Analytical Framework

Every long-range forecast about quantum computing must reconcile two facts pulling in opposite directions. The field has never been in better technical shape: below-threshold error correction has been demonstrated on two continents, logical qubits are no longer theoretical objects, and verifiable quantum advantage claims have begun to accumulate. The technology is accelerating; the economics are lagging. Our framework is built around that gap and around the dates by which it must close or fail to close.

We therefore reject the popular question "when will quantum computers arrive? " in favor of four sharper questions: When does independently verified fault tolerance at meaningful logical scale occur, if at all? When does revenue begin to reflect delivered value rather than subsidized experimentation? And does leadership concentrate in one region or fragment across several?

- leadership indicators disperse across regions; fault tolerance arrives late in the decade.

Two structural commitments define our analysis and recur throughout: first, the post-quantum cryptography migration will impose real costs *before* quantum computing generates comparable commercial value — the cryptographic clock does not wait for the machine. Second, geopolitical supply-chain fragmentation pushes the world toward a multipolar quantum order even if one country holds a technical lead; hardware leadership does not translate into unipolar hegemony.

Overall confidence is **low**, and we say so deliberately. Any probability distribution over machine capabilities fourteen years out, conditioned on a technology whose error-correction inflection occurred only within the last two years, deserves epistemic humility. The distribution is wide because the evidence supports genuinely divergent readings, not because we failed to choose.

### The Central Causal Logic

The probabilities above rest on three causal chains.

**Chain one: error correction is now the pacing variable, and it has become bankable but not yet schedulable.** For two decades the field's bottleneck was physical qubit quality; the demonstration of below-threshold error correction — on superconducting platforms in the United States and neutral-atom or trapped-ion systems elsewhere — moved the bottleneck to *logical scaling*: growing the number of logical qubits while holding logical error rates near 10⁻⁶ and keeping overheads tractable. Every major modality has now crossed one decisive threshold: superconducting leads on gate speed and fabrication ecosystems, trapped ions on fidelity and all-to-all connectivity, neutral atoms on qubit count and reconfigurability, photonics and spin qubits on integration paths. None has crossed all of them. When every contender has proven its core physics but none has proven its scaling economics, the honest prior is bimodal.

**Chain two: the verification inflection compresses hype cycles and hardens the falsifiability of claims.** The single most important institutional development of the 2020s is DARPA's Quantum Benchmarking Initiative and the broader shift toward independent, adversarial testing of vendor claims. Before this shift, roadmaps were marketing instruments; after it, claims must survive third-party replication or peer review at Nature/Science rigor. This matters causally in both directions. It raises the probability of Steady Climb, because genuine progress can no longer be obscured by skepticism and capital flows to verified leaders. Verification is a volatility amplifier, which is why we cannot in good conscience push either dominant scenario above one-third.

**Chain three: value arrives later than capability, and PQC costs arrive before both.** Because of harvest-now-decrypt-later attacks, the cryptographic threat window is already open; data encrypted today with RSA/ECC and retained for a decade is already at risk. This forces governments and large enterprises to begin post-quantum migration on a schedule set by *risk tolerance and regulation*, not by the actual arrival of a cryptographically relevant quantum computer. NIST-standardized PQC algorithms and mandates in the vein of US federal deadlines are creating compliance-driven spending now. we assign that event to Quantum Leap or Other.

### Why 30% Steady Climb — and Not Higher

and no CRQC before 2035.

Below-threshold operation means the error-correction theory works; what remains is fabrication yield, control electronics scaling, and real-time decoding — hard but conventional-hard, not discovery-hard. Multiple credible vendor roadmaps converge on ~100 logical qubits in the 2029–2033 window, and for the first time those roadmaps are being independently benchmarked rather than merely asserted. The US leads on the weighted combination of capital depth, cloud distribution, talent inflows, and the deepest stack from chips to software.

The verification regime could validate the leaders and still reveal that no one is as close as claimed. Thirty percent makes Steady Climb the modal single outcome while acknowledging that the majority of probability mass lies in slower or messier worlds.

### Why 30% Long Winter — and Not Dismissed

Skeptics treat winter as unthinkable given current funding. We treat it as fully co-equal with the baseline, for four reasons.

Second, the public-market channel is narrow. A small number of listed pure-plays carry outsized signaling weight; two failures would reprice the entire private stack, matching our winter criteria mechanically.

Third, history: the field has already survived at least two funding winters, and each followed a period in which promises outran delivery by roughly this ratio.

A mild slowdown is not winter; it is our fourth scenario.

### Why 10% Quantum Leap — and Not Zero

This is a demanding conjunctive standard: logical scale, verification, and genuine commercial relevance simultaneously.

Neutral-atom platforms in particular have shown qubit-count growth rates that, if translated to logical qubits, compress timelines. Note that Quantum Leap embeds an urgent PQC crisis — which is precisely why harvest-now-decrypt-later makes the cryptographic clock urgent *today* regardless of this scenario's probability.

### Why 25% Fragmented Multipolarity — the Realistic Continuation

Our fourth scenario is the "messy middle" and we weight it heavily because it is the path of least resistance for a world in which no falsifiable extreme triggers.

The geopolitical logic is the strongest part of this case. The United States, China, and the European Union are not running the same race at different speeds; they are three different machines. The US optimizes for venture-paced commercialization and defense-coupled innovation; China for state-directed scale, application deployment, and indigenous supply chains; the EU for scientific depth, public infrastructure, and regulatory shaping. These strategies produce leadership on *different metrics*, which mechanically disperses the indicators our fragmentation criterion tracks.

Supply chains reinforce this. Export controls on qubit-relevant components, cryogenics, lasers, and advanced fabrication create a chokepoint paradox: restrictions designed to preserve US advantage also accelerate Chinese indigenous substitution and EU strategic-autonomy investment, hardening the very fragmentation they aim to prevent. Fragmentation, not unipolarity, is the attractor.

### How Prediction-Market Anchors Were Weighed

Where liquid prediction markets or calibrated forecast aggregators existed for adjacent questions — CRQC-by-date, verified fault-tolerance milestones, vendor-specific roadmaps — we treated them as one input among several, never as an override. Three rules governed their use.

First, we used markets for *short-horizon* milestones, where crowd updating is fast and information-rich, and discounted them for long-horizon questions where liquidity is thin and prices mostly restate priors. Second, we checked for the known failure mode of markets on technologies with enthusiast-skewed trader pools — a systematic optimism bias on capability timelines — and shaded capability-arrival probabilities accordingly.

### Decisive Evidence and the Next Falsification Points

The evidence that would most move this distribution is already identifiable. On the geopolitical axis, watch export-control license-denial patterns and Chinese indigenous-substitution rates — the co-evolution of those two curves largely determines whether fragmentation hardens into durable multipolarity.

the PQC migration bill arrives before the quantum dividend; and the global order that emerges is multipolar, with American technical leadership contested at the edges by state-directed Chinese scale and European infrastructural depth.

## Part 3 — Appendix: Detailed Analysis

_The detailed, section-by-section analysis supporting Parts 1–2 follows._

## Executive Forecast: The State of Quantum Computing in 2040

Every long-range forecast about quantum computing has to reconcile two facts that pull in opposite directions. The first is that the field has never been in better technical shape: below-threshold error correction has been demonstrated on two continents, logical qubits are no longer theoretical objects, and the first claims of verifiable quantum advantage have been framed for independent checking rather than for keynote audiences [S2][S46]. This chapter, the executive forecast for the whole report, states the central projection up front and then defends it: through 2040, the United States is most likely to deliver the first early fault-tolerant machines around 2030–2033 and dominate their commercialization, but large-scale economic value arrives only after 2035; [S111] China stays roughly one generation behind in error correction while leading photonic advantage demonstrations and quantum communication networks; the European Union converts its choke points—dilution refrigerators, cryogenics, helium-3—plus coordinated deployment through EuroHPC into a niche but indispensable role; and the costs of post-quantum cryptography migration land years before any quantum computer earns a dollar.

### The Three Regional Trajectories to 2040

Google's Willow demonstrated below-threshold surface-code error correction in December 2024 and claimed the first verifiable quantum advantage in October 2025 [S1][S2]; DARPA's Quantum Benchmarking Initiative will independently test whether any approach reaches utility-scale operation by 2033 [S11]. No other country combines capital intensity, hardware pluralism across modalities, and external verification.

The US weakness is public funding continuity and political patience. The National Quantum Initiative's reauthorization limbo illustrates the fragility: H.R. The projection, therefore, is not unconditional American leadership but leadership that survives only if either the venture cycle keeps financing the gap or Congress closes the authorization gap before a funding winter.

**China: a generation behind in error correction, a generation ahead in communication.** The Chinese position is the mirror image of the American one: state patience where the US has capital markets, publication-verified milestones where the US has institutional benchmarking. Add the world's only operational quantum communication infrastructure under Pan Jianwei's CAS/USTC complex, backed by the 14th Five-Year Plan's designation of quantum information as the second-ranked cutting-edge technology field, and the Chinese profile through 2040 becomes clear: second in universal fault-tolerant computing, first in quantum networking, and the pace-setter in photonic advantage claims. [S122]

The projection is that export controls accelerate rather than retard this bifurcated trajectory. US controls and the March 2025 Entity List additions targeting Chinese cryogenics firms pushed QuantumCTek and Origin Quantum to expand domestic refrigerator and interconnect production—the localization that the controls were meant to prevent. [S73] China's kiloqubit-class target around 2030, served by Origin Quantum's Wukong line, will be judged through peer-reviewed publication rather than DARPA-style verification, meaning the world will read Chinese progress through a weaker evidentiary lens—but also that Chinese milestones, when they do appear in Physical Review Letters or Nature, will be more credible than skeptics assume. [S50]

**The European Union: the indispensable niche.** Europe's quantum strategy looks modest only if measured in qubit counts. EuroHPC's coordinated deployment—national procurements co-funded across Germany, Luxembourg, and other member states—builds a distributed quantum-computing fabric rather than a champion vendor [S78][S81].

### The Four Scenarios and Why the Probability Mass Splits

| Scenario | Probability | Defining condition |
|---|---|---|
| Steady Climb | — | Incremental roadmap delivery brings early fault-tolerant machines 2030–2033, US-led; [S50] |
| Long Winter | — | Scaling stalls across modalities; |
| Fragmented Multipolarity + Delayed Fulfillment | — | leadership indicators split across ≥2 regions; export controls cement the divide |
| Quantum Leap | — | — |
| Other / unanticipated | 5% | — |

The mechanism is financial, not physical. If that cluster slips en masse, there are no intermediate proof points to justify refinancing, and the correction propagates through the public listings first. Against this stands the strongest bull argument, which deserves steelmanning: three independent modalities—superconducting, trapped-ion, and neutral-atom—are all posting credible logical-qubit results simultaneously, so a single-modality engineering failure no longer sinks the timeline. The report takes this seriously; But the modalities share bottlenecks their marketing obscures—real-time decoding, cryogenic I/O density, control-electronics scaling—and DARPA's benchmarking exists because verified results have lagged claimed ones. Redundancy at the qubit layer does not guarantee redundancy at the systems layer.

### The Central Asymmetry: Costs Before Benefits

The single most decision-relevant structural fact in this forecast is temporal. On its face this looks like spending billions against a coin flip. It is not, for two reasons.

This inverts the usual innovation sequence. In prior technology waves, commercial value preceded the security reckoning. Here the security bill—$7.1 billion federally, multiples of that across the private sector—arrives during the 2026–2035 window when quantum-computing revenue is still measured in single-digit billions. [S114]

### What to Watch, 2026–2035

The forecast's falsification points are dated and public. China's kiloqubit demonstration arrives around 2030 with or without peer-reviewed Λ ≥ 2 suppression [S22]; NIST finalizes IR 8547's deadlines; [S104] Each event moves the scenario pricing by more than any amount of vendor communication. The honest posture for 2040 is this: the US most likely leads, China most likely follows closely in computing and leads in networking, Europe most likely controls the taps, and the trillion-dollar question—when quantum computation itself starts earning—most likely answers "after 2035, in a world already divided."

## Hardware Modalities Head-to-Head: Who Reaches Fault Tolerance First

Ask six quantum hardware executives who reaches fault tolerance first and you will get six confident answers, each of which happens to favor the speaker's modality. Strip away the positioning, and the race as of late 2026 reduces to a surprisingly clean structure: every modality has now crossed one decisive threshold or another—below-threshold error correction, high-fidelity logical operations, or fault-tolerant memory in Nature—but no modality has crossed all of them, and the specific cliff each one faces differs. [S23] This chapter compares the six routes on the metrics that matter—physical qubit count, two-qubit gate fidelity, demonstrated logical qubits, and error-correction overhead—then asks which route most plausibly delivers a utility-scale machine in the 2030–2033 window this report prices as the base case, and which engineering cliffs separate the roadmaps from reality. [S50]

Photonic and topological routes are structurally attractive but evidentially behind; spin/silicon is the dark horse whose failure modes are industrial rather than scientific.** Crucially, the differences between modalities are narrowing at the qubit layer while hardening at the systems layer, and it is the systems layer—real-time decoding, cryogenic I/O, logical clock speed—where the race will actually be decided.

### The Scoreboard: Six Routes, Four Honest Metrics

Any cross-modality comparison must begin with a discipline the vendors' marketing undermines: fidelity numbers are not comparable across conventions. it is a bookkeeping disagreement, and the difference matters enormously at fault-tolerance thresholds, where each additional "nine" of fidelity cuts the error-correction overhead geometrically.

**Superconducting** leads on qubit-count parity, error-correction verification, and roadmap specificity.

**Trapped ion** leads on fidelity and encoding efficiency. the surface code at practical error rates typically demands far more physical qubits per logical.

**Neutral atom** leads on scaling dynamics and logical-qubit architecture depth. Neutral atoms uniquely combine large qubit counts with reconfigurable connectivity—atoms can be physically moved mid-circuit, and arrays can be reconfigured between algorithm phases—giving them a route around the routing overhead that plagues fixed-lattice superconducting chips. The cost of that flexibility is throughput: atom rearrangement, cooling, and imaging cycles slow the logical clock, and 99.5% physical fidelity forces higher code distances than trapped ions require. [S31]

**Photonic** leads on manufacturing ambition and lags on logical evidence. PsiQuantum's Omega chipset (announced February 2025, published in Nature) contains all components for million-qubit-scale fusion-based machines fabricated in a high-volume semiconductor fab, with compute centers under construction in Brisbane and Chicago—but **no logical-qubit count has been publicly demonstrated** [S35]. The photonic route's wager is that if fault tolerance works at all, fab-based manufacturing wins the scale-out phase; the risk is that the error-correction physics of fusion-based schemes remains largely undemonstrated in hardware. Against that, photons need no cryogenics and inherit the semiconductor industry's yield discipline—an advantage no other modality can claim at the million-component scale.

Demonstrated logical-qubit results from this community remain at laboratory scale, far behind the superconducting and neutral-atom leaders. The spin/silicon bet is therefore not a 2030–2033 bet at all: it is a bet that when quantum computing reaches the manufacturing phase, the modality already compatible with CMOS lines wins the cost curve—provided uniformity, cross-talk, and connectivity problems yield to process engineering rather than fundamental physics. [S50]

**Topological** remains the highest-variance bet. DARPA nonetheless selected Microsoft for the final US2QC/QBI phase, betting that if topological qubits work, their intrinsically lower error rates collapse the overhead problem that dominates every other route. That is a coherent bet on a physics result that does not yet exist. Topological qubits also require no error-correction demonstration to invalidate rivals' arithmetic: a single verified topological qubit at intrinsic error rates far below threshold would reset every overhead estimate in this chapter, which is precisely why the modality is priced as option value rather than a race entry.

### The Overhead Race: Why 2:1 Changes Everything

Error-correction overhead is the single most decision-relevant metric in the modality race, because it determines how many physical qubits a useful machine requires. The arithmetic is unforgiving. Google's roadmap culminates in controlling one million physical qubits, with the next milestone—a long-lived logical qubit—requiring a control system of millions of components [S19]. at 2:1, it needs hundreds.

This is why Helios's Iceberg-code result at ~2:1 encoding is the most strategically important single number on the scoreboard. The counter-bet, which deserves steelmanning, is that it cannot: trapped-ion machines pay for fidelity with **logical clock speed**. Helios demonstrates beautiful logical qubits; whether it demonstrates fast ones at scale is exactly the open question. A superconducting machine with heavier overhead but microsecond gates could deliver commercial answers years before an ion machine with elegant 2:1 overhead but millisecond ones.

The code-design race compounds this. The surface code's dominance has always rested on its decodability and layout tolerance, not its efficiency; if higher-rate codes with implementable decoders mature by the late 2020s, the physical-qubit requirements for Starling-class machines shrink by an order of magnitude, and the superconducting route's principal liability—needing millions of physical qubits—weakens correspondingly. This is why every serious lab now runs parallel code and platform programs: the modality race and the code race are converging into a single systems-engineering race.

### Who Reaches Utility Scale First: Pricing the Routes

**Most probable first: superconducting.** The route holds three structural advantages no rival matches simultaneously: below-threshold error correction verified in Nature on two continents [S46][S22]; and a scaling pipeline in which the hard problems—real-time decoding, cryogenic I/O density, modular chip-to-chip interconnect—are engineering problems with known industrial analogues rather than open physics questions. IBM's 2026 milestones (Nighthawk running 7,500-gate circuits across up to three 120-qubit modules; [S18] Kookaburra prototyping a real-time error-correction decoder) are precisely the systems-layer stepping stones the route needs.

The route's liability is fidelity: 99.5% physical gate fidelity sits well below trapped-ion levels, forcing higher code distances and eroding the atom-count advantage. [S31] The neutral-atom endgame is a wager that atom shuttling and mid-circuit measurement improve faster than ion transport does.

**Conditional third: trapped ion.** If Apollo lands near 2030 with hundreds of logical qubits at near-2:1 overhead, Quantinuum—not IBM—delivers the first economically useful machine, because low overhead means low systems cost. [S122]

**Unpriced for 2030–2033 delivery but live for the 2030s: photonic and topological.** PsiQuantum's fab-manufacturing thesis and its expanded $125 million DARPA Stage C agreement make the photonic route the first to face government-run utility-scale verification, and if Omega-fabricated systems run utility-scale circuits, the Quantum Leap scenario's probability rises materially. [S60] Spin/silicon remains unpriced for the window entirely: its gate to relevance opens only if CMOS-compatible fabrication converts into demonstrated logical qubits before the superconducting leaders lock in the verification race.

### The Engineering Cliffs That Separate Roadmaps from Reality

The modality comparison above compares physics.

**Real-time decoding.** Error correction only works if the decoder keeps up with the error rate. Surface-code decoding at scale requires processing enormous syndrome-bit streams per logical qubit, with latency low enough that corrections apply before errors accumulate. Every modality faces this cliff; the codes with elegant overhead (qLDPC, tile codes) have harder decoding problems than the surface code's, creating a direct trade between qubit count and decoder complexity that roadmap slides never show.

**Cryogenic I/O density.** A million-qubit superconducting machine needs a million control lines or cryo-CMOS multiplexing at temperatures where commercial electronics barely function. Each physical qubit added increases refrigerator heat load, wiring, and cost; Trapped-ion and photonic routes partially escape this cliff—ions need room-temperature lasers, photons need no cryogenics—which is a rarely priced advantage of those modalities at the million-component scale. Spin/silicon sits on the far side of it: the modality most dependent on helium-3 is also the one whose entire cost thesis rests on dense cryogenic integration.

**Logical clock speed and transport.** As argued above, the trapped-ion fidelity advantage is denominated in a currency—gate time—that commercial value does not accept at face value. The first commercially useful machine will likely be the one that first completes a million-gate logical circuit on a real problem, and gate rate × fidelity × qubit count is the composite metric on which superconducting currently leads despite inferior per-gate quality. IonQ's response—scaling through acquisitions such as Lightsynq's photonic interconnects and the Oxford Ionics chip—implicitly concedes that no single trapped-ion architecture carries the whole roadmap. Neutral atoms face the same cliff one layer down: rearrangement speed is to atom shuttling what transport time is to ions, and QuEra's Libra specifications will be judged on wall-clock throughput, not logical-qubit count alone.

The synthesis this chapter offers is that the race is not six independent bets but one correlated bet on systems engineering, with six entry points. Below-threshold physics has been settled in superconducting; logical-qubit architecture has been settled in neutral-atom and trapped-ion; fab-scale manufacturing is being settled in photonic; nothing has been settled in topological. Which route crosses the commercial-relevance line first is the question the next chapter's verification timeline will police; the hardware answer most likely sits in Poughkeepsie, but the honest confidence interval still includes Cambridge, Harvard Square, and—outside chance—a fab in Brisbane.

## The Verification Inflection: DARPA QBI and the Credibility Filter

The 2020s will be remembered less for any single quantum processor than for a quieter institutional shift: the moment the industry stopped asking audiences to take its word for it. Between now and 2033, the decisive question in quantum computing is not "who has the best roadmap" but "whose claims survive independent testing." DARPA's Quantum Benchmarking Initiative (QBI) has quietly positioned itself as the arbiter of that question, and the sequence of dated, checkable milestones between 2026 and 2033 will do more to determine which of this report's four scenarios materializes than any amount of vendor communication. [S63] This chapter lays out that verification sequence, explains why Google's decision to submit itself to QBI scrutiny marks a structural change in how quantum progress is priced by markets and governments, and derives concrete decision rules for readers tracking the 2028–2030 fault-tolerance cluster. [S63]

### From Rhetorical Advantage to Testable Claims

The NISQ era's central pathology was that "advantage" was a marketing category. Vendors claimed it, rebutted each other's definitions, and moved on. Whatever one thinks of random circuit sampling's commercial relevance, the claim was framed for verification rather than spectacle, and the underlying error-correction result had been published in Nature.

DARPA's QBI institutionalizes that shift. The initiative proceeds in three stages—Stage A for concept evaluation, Stage B for R&D plans and prototype development, and Stage C for government-run verification—with the explicit goal of determining whether any quantum computing approach can reach utility-scale operation by 2033 [S11]. Nearly twenty companies entered Stage A, and DARPA selected eleven for Stage B on 6 November 2025 [S12]. The signal to the market is unambiguous: the US government will pay serious money not for promises but for the right to test them.

The structural importance of QBI lies in what it does to the industry's information asymmetry. A Stage C test specification forces a single convention. It converts the fidelity-fraud dimension of quantum marketing, where conventions differ and definitions are load-bearing, into a pass/fail measurement. For investors and governments, that is the difference between pricing a story and pricing an asset.

### Why Google's Stage A Submission Matters More Than It Looks

On its face this is a small administrative event; Google has federal contracts and publishes prolifically. But Google's roadmap posture has been distinctive: it publishes milestones, not dates, explicitly declining the dated-machine commitments that IBM (Starling 2029, Blue Jay 2033+), QuEra (Libra 2028), and Quantinuum (Apollo 2030) have made. [S50] By entering QBI, Google accepted external specification of what counts as progress toward its own stated next milestone—a long-lived logical qubit whose control system requires scaling to millions of components, an engineering jump of several orders of magnitude beyond anything demonstrated [S19].

This matters for three reasons. First, it converts the industry's most credible scientific actor into a participant in a common yardstick. If Google's milestone framework is being evaluated inside QBI's stages alongside IBM's, QuEra's, and IonQ's, then by Stage B and Stage C the public will be able to compare approaches on DARPA's terms rather than each vendor's. Second, it raises the reputational cost of missing for everyone else. Third, it aligns the frontier lab's incentives with the government's timeline: QBI's 2033 verdict horizon now brackets Google's own implied schedule, and Hartmut Neven's February 2025 statement to Reuters that commercial quantum applications would arrive within roughly five years becomes a testable claim rather than a keynote flourish. [S122]

A counterargument deserves steelmanning: one could hold that QBI is unnecessary because peer review already filters claims—Google's below-threshold result appeared in Nature, and Zuchongzhi 3.2's December 2025 below-threshold milestone (distance-7 surface code, suppression factor Λ = 1.40(6), published as a Physical Review Letters Editors' Suggestion) shows the academic system working across geopolitical blocs [S22]. But peer review verifies experiments as performed, not roadmaps as promised; IBM's claim that its users will demonstrate quantum advantage by the end of 2026—Nighthawk running 7,500-gate circuits across up to three 120-qubit modules, with Kookaburra prototyping a real-time error-correction decoder in the same year—is not a scientific claim at all until someone checks it [S18].

### The Observable Milestone Sequence, 2026–2030

The verification inflection plays out through a sequence of dated claims, each of which will either compound credibility or erode it.

**End-2026: IBM's advantage claim on Nighthawk.** IBM has committed that its users—not IBM itself, which is a subtle but important hedge—will demonstrate quantum advantage over classical computing by the end of 2026 on Nighthawk hardware. [S18] The claim is the first dated, falsifiable commercial-relevance test of the cluster. IBM's is framed around user workloads. If both stand, they describe different things, and QBI-style standardization becomes more valuable, not less.

Quantinuum targets Apollo, a fully fault-tolerant universal machine, in 2030, though a later company blog pulls universal fault tolerance forward to "by 2029". [S50]

It will be the natural first candidate for Stage C verification at scale. China's milestones will be verified—if at all—through peer-reviewed publication rather than a DARPA-style process, which means the world will read Chinese progress through a different, and weaker, evidentiary lens.

### Decision Rules: What Should Downgrade the 2028–2030 Cluster

The value of a verification framework is that it converts disappointment into information.

2. Claims at the bottom of that hierarchy should not move scenario assessments at all.

3. At least one verified survivor keeps Steady Climb or Quantum Leap alive; PsiQuantum's $125 million Stage C agreement makes the photonic route the first to face this test at scale. [S60]

4. Chinese announcements without PRL- or Nature-level publication should be treated as unverifiable for forecasting purposes.

5. **Let failed roadmaps redistribute probability, not destroy it.** If IonQ's 2027–2028 chain breaks, the probability mass does not vanish; [S48] it moves toward the modality leaders with demonstrated verification pedigrees—superconducting (IBM, Google) and neutral-atom (QuEra)—consistent with this report's hardware assessment in Chapter 2.

The deeper point is that the verification inflection is already priced into the geometry of the industry. Nearly every serious actor—IBM with dated machines, Google with QBI submission, Quantinuum with fidelity records, DARPA with staged funding—has converged on testability as the currency of progress. Readers should watch the stages, not the slides.

## Tri-Polar Strategies: National Programs, Funding Asymmetries, and Talent

Every regional comparison of quantum computing eventually collapses into a league table of qubits and dollars, and the league table is the wrong instrument. The United States, China, and the European Union are not three competitors running the same race at different speeds; they are three different machines, each engineered around a distinct theory of how technological races are won. The American machine runs on private capital and institutional verification, with the state supplying roughly a billion dollars a year and, critically, the credibility infrastructure nobody else possesses. The Chinese machine runs on state patience whose budget nobody outside the Chinese government can audit, converting five-year planning horizons into publication-verified milestones. The European machine runs on coordinated deployment and control of the physical inputs—dilution refrigerators, cryogenics, helium-3—that every other region's program must purchase. Each architecture carries a characteristic failure mode: funding volatility for the United States, evidentiary opacity for China, and scale ceilings for Europe.

### The American Model: Capital Depth, Legislative Fragility

The defining American asymmetry is that private money dwarfs public money by a widening margin.

The structural weakness sits in Congress, not in the market. The National Quantum Initiative's reauthorization saga shows how a flagship program can operate in indefinite limbo.

> "At the moment, this bill does not have any funds authorized."

A program extended in time but not in money is a program whose real budget is the annual appropriations process. That matters because federal dollars fund the layer venture capital does not reach: university laboratories, the DOE national-lab ecosystem, and the Isotope Program that sources all domestic helium-3 from tritium processing at Savannah River and deems federal supply "mitigated" [S14]—the pipeline inputs whose absence shows up only after a decade-long lag.

The steelman against worrying about any of this deserves a direct answer: the anchoring institutions of American quantum are not SPAC-era startups. Quantinuum is majority-held by Honeywell. On this reading, the American model is more resilient than the NQI limbo suggests, because frontier bets are insulated from congressional dysfunction. The counter is that anchors protect the frontier, not the base. Graduate students, cryogenics technicians, and national-lab instrument builders are financed by precisely the appropriations the reauthorization stalemate leaves unsecured.

### The Chinese Model: Opaque Patience, Legible Through Publication

China's quantum funding is the single largest unverifiable number in this entire forecast. What is verifiable is structure, not scale. The 14th Five-Year Plan (2021–2025) designated quantum information the second-ranked cutting-edge technology field, and funding flows through the CAS/USTC complex under Pan Jianwei's leadership into a national laboratory established in 2017. [S122] The photonic line leads outright: the Jiuzhang demonstrations culminated in a programmable 3,050-photon Gaussian boson-sampling result in August 2025. [S38]

The capital structure confirms this is a state model with markets bolted on, not the reverse. Export controls compress the model from both directions: the September 2024 US rule and Entity List additions—including CAS's National Time Service Center among 32 entities listed in September 2025—constrain hardware and component access [S71], while per RUSI's assessment they accelerated the very domestic substitution they sought to prevent: QuantumCTek's ez-Q Fridge entered mass production in February 2024 rated just under the control threshold, and Origin's SL1000 refrigerator line has operated in Hefei since mid-2024. The mechanism to internalize is leverage decay: chokepoint pressure is real in the near term and self-liquidating in the long term, on a clock set in Hefei and Shanghai.

For forecasting purposes, the Chinese model's distinctive instrument is the flagship milestone as state narrative, verified through peer review rather than institutional benchmarking. This has an underappreciated consequence: Chinese progress is legible to the outside world only through PRL- and Nature-level publication—a weaker evidentiary lens than DARPA's staged testing, but a more honest one than skeptics assume, because Λ values and photon counts in peer-reviewed papers cannot be inflated the way vendor specifications can. announcements without publication should be treated as unverifiable. The model's core bet is temporal: state patience outlasts Western funding cycles. If the US venture boom corrects while Chinese appropriations continue on Five-Year-Plan timescales, the capability gap closes without any Chinese breakthrough—which is precisely the catch-up path this report's Long Winter scenario prices.

### The European Model: Deployment Density and the Indispensable Niche

Europe's architecture inverts America's: coordinated public deployment where the United States has market selection. National programs in Germany, France, and the Netherlands layer onto this fabric.

The European wager is that chokepoints outlast qubit records. refrigerators can cost more than the quantum processors they host and take months to procure. Bluefors has even hedged its own helium-3 supply with lunar deliveries of up to 10,000 liters per year from Interlune for 2028–2037—a striking indicator of how binding the constraint is. [S39] The model's failure mode is the mirror image of America's—not funding volatility but the absence of any European actor capable of a Starling-class bet. If it arrives late, Europe's relative position strengthens, because the value of being the supplier everyone must buy from rises as the race lengthens. Europe, uniquely among the three, is long volatility in the fault-tolerance timeline.

### Talent and the 2027–2030 Stress Test

The pipelines differ structurally. America's runs through the university–national-lab complex that federal appropriations finance; China's pipeline is the most rapidly expanding, anchored at USTC under a single leadership structure that has trained successive generations of experimentalists; the historical pattern of Chinese researchers training in the United States before returning is exactly what export controls and visa friction now suppress, making talent decoupling—more than hardware denial—the controls' most durable effect [S41]. Europe's pipeline benefits from physics tradition and mobility but leaks at the top: its strongest hardware entrepreneurs face thinner growth capital at home, though EuroHPC's procurement fabric increasingly offers domestic demand anchors that retain companies even when it cannot grow champions.

The synthesis for this report's scenario pricing is that the tri-polar structure itself is robust across all four scenarios—no plausible 2026–2040 path produces either American hegemony or Chinese leapfrog in universal quantum computing—but its internal balance is not. In that window, each model's characteristic weakness is maximally exposed: American legislative drift meets a refinancing cliff; Chinese opacity meets a Western propensity to over-control in response to unverifiable milestones; European scale ceilings meet a moment when only balance-sheet-scale actors can deliver. The most probable evolution is the fragmented-multipolar world of duplicated, costlier parallel stacks—reached not by anyone's design but by the simultaneous partial failure of all three models' weaknesses and all three models' strengths.

As controls harden and talent flows decouple, the three regions' verification regimes themselves diverge: DARPA's institutional benchmarking in the West, peer-reviewed publication in China, EuroHPC's procurement-linked standardization calls in Europe [S80]. By the mid-2030s, even the metric of "leadership" becomes regionally contested—not three regions racing on one yardstick, but three yardsticks, each measuring the race in the dimension its own system is built to win. A forecast that asks only "who leads in quantum computing by 2040" will misprice this. [S111] The better question is who leads at what—and the answer developed across this report is: the United States at verified fault tolerance, China at state-paced catch-up and photonic advantage, Europe at the inputs and deployment fabric everyone else requires. That division of leadership is not a transitional state. It is the destination.

## Supply Chain Chokepoints and the Export Control Paradox

<!-- viz:charts/metric_trajectories.html -->
![Key Metric Trajectories (research-extracted)](demos/quantum-2040/charts/metric_trajectories.png)

*Key Metric Trajectories (research-extracted)*

Supply chains are where quantum computing's geopolitical abstractions turn into purchase orders, lead times, and denied license applications. The previous chapters treated export controls mostly as a background condition shaping funding and talent; this chapter argues that the controls and the chokepoints they target form a system with its own internal clock—a clock that determines not who wins the quantum race but how expensive and how duplicated the race becomes. The central claim can be stated plainly: **Western export controls are genuinely disruptive to China's near-term hardware access and durably disruptive to its talent flows, but they are self-liquidating against China's component base on a five-to-ten-year localization clock that was already running in Hefei before the controls took effect. it is that they succeed, and succeed too slowly—buying years of leverage at the price of permanently forfeiting the option of interdependence.

### The Map of Chokepoints: What Actually Binds, and for Whom

The quantum supply chain has one genuinely concentrated chokepoint, one state-monopolized input, and a long tail of dispersed-but-critical components. Getting the hierarchy right matters, because policy leverage and vulnerability both live at the top of it.

This concentration binds directly by modality. It partially binds trapped-ion programs, whose trap systems require cryogenic operation though far less extreme than millikelvin superconducting platforms. It does not bind photonics at all: PsiQuantum's architecture needs no dilution refrigerator, a rarely priced structural advantage of the photonic route—though even photonic systems face slow, expensive cryogenic supply for their detector infrastructure, with helium-3 near $2,500 per liter feeding that demand. [S94] Neutral atoms sit in between: the modality escapes millikelvin cooling but depends on precision laser and optics supply chains, so its chokepoint is optical rather than cryogenic.

**Helium-3 is the chokepoint behind the chokepoint, and it is American.** The US DOE Isotope Program, the dominant Western supplier, sources all of its helium-3 from tritium processing at the Savannah River Site in South Carolina, making "thousands of liters" available each year [S14][S39]. DOE deems the historical shortage "mitigated"—but that assessment covers federal allocations only, leaving commercial buyers in a tighter market. The economics are stark. When the world's dominant refrigerator maker contracts for *lunar* isotope supply a decade out, that is the market's own verdict on how binding terrestrial supply is. The structural implication for the 2030s: as fault-tolerant superconducting machines scale from tens of refrigerators toward hundreds, helium-3 demand grows roughly linearly with installed cryogenic capacity, and the US government—through the Isotope Program—becomes an inadvertent gatekeeper of the Western superconducting scale-out, including for allied programs.

**Control electronics and cryogenic components form the third tier.** The EU's 8 September 2025 Delegated Regulation added quantum computers, cryogenic electronic components, parametric signal amplifiers, cryogenic cooling systems, and wafer probes to the dual-use control list, aligning with US, UK, and Japanese controls. The inclusion of parametric signal amplifiers is diagnostic: those devices are the readout chain of every superconducting machine on earth, and controlling them means controlling the ability to *read* superconducting qubits at scale, not merely to cool them.

The honest summary of the hierarchy: **cryogenics binds superconducting, topological, and spin modalities; photon sources and detectors bind photonics; tweezer lasers and precision optics bind neutral atoms; control electronics binds everything.** No region holds all of these. IISS's assessment is that no single country dominates the quantum supply chain, and that the effectiveness of the US-and-allies control regime rests on a small number of geographically dispersed critical-node firms. That dispersion is precisely why the regime works at all—and why it cannot be tightened into a blockade without the node firms' home governments forcing the issue.

### The Control Architecture and Its Escalation Logic

The Western control regime did not arrive at once; it accreted, and its accretion pattern reveals its theory of the case. The US interim final rule effective 6 September 2024 added quantum-related Commerce Control List entries with deemed-export licensing, imposing a presumption of denial for dilution refrigerator exports to Chinese research groups and for cryogenic circuits to Chinese quantum suppliers. Entity List additions followed a supply-chain logic rather than a systems-integrator logic: in March 2025 BIS added seven Chinese supply-chain entities including the cryogenics companies Scikro and Physike, and in September 2025 it listed CAS's National Time Service Center among 32 entities [S71]. The pattern is unmistakable—the regime targets the *inputs* to Chinese quantum hardware (cryostats, cryo-electronics, timing infrastructure) rather than Chinese machines themselves, on the theory that denying components denies scaling.

The EU aligned on 8 September 2025, completing what IISS describes as allied coverage of "almost the entire quantum 'stack' — complete quantum computers, enabling components, equipment and advanced materials". [S100] Rare earths matter to quantum hardware less directly than to defense electronics, but the retaliation's *function* is symmetrical: it demonstrates that China holds chokepoints of its own, and that the West's decision to weaponize supply concentration invites reciprocal weaponization. The escalation logic is now locked in on both sides.

### The Paradox in Operation: How Controls Build What They Seek to Prevent

Here is the chapter's core mechanism, and it deserves to be stated as a causal chain rather than a slogan. Step one: US controls deny Chinese actors dilution refrigerators and cryogenic circuits. Step two: denial converts a purchasable input into a national mandate—Chinese state funding, flowing through the 14th Five-Year Plan's second-ranked priority for quantum information, redirects toward domestic production of exactly the denied items. Step five: by the time the denied component is indigenized, the *denial* has cost the controlling side its export revenue and its intelligence visibility into Chinese programs, while the Chinese side has acquired a permanent, uncontrollable production base.

Per RUSI's assessment, this is not a hypothetical: US export controls accelerated China's domestic refrigerator and interconnect industry [S41]. The controls worked—and in working, they destroyed their own foundation.

The counterargument deserves a genuine steelman before being answered. One can hold that the paradox is overstated on three grounds. First, *quality gap*: a Chinese dilution refrigerator rated just under a control threshold is not a Bluefors XLD1000sl; indigenous cryogenics typically trail the frontier in vibration, base-temperature stability, and uptime, and frontier superconducting research is exquisitely sensitive to all three. Second, *talent denial is the durable effect*: the historical pipeline of Chinese researchers training in American and European laboratories before returning home is exactly what visa restrictions and deemed-export licensing suppress, and talent, unlike hardware, cannot be reverse-engineered from a shipment. Third, *time still matters*: even if localization succeeds by the early 2030s, the years of denied access between 2024 and then are years subtracted from China's error-correction catch-up—and catching up in quantum computing is a race against a moving frontier, where a year lost in 2026 is not recovered in 2031. [S50]

This report's answer is that all three grounds are correct—and the conclusion still follows. The talent effect is the controls' most durable achievement, which is precisely why this report treats talent decoupling, not hardware denial, as the controls' lasting legacy. And the time bought is real but was demonstrably insufficient to widen the capability gap: China's below-threshold error correction arrived in December 2025 with Zuchongzhi 3.2's distance-7 code and suppression factor Λ = 1.40(6), roughly a year behind Google [S22]. A one-year gap sustained *under full denial pressure* is a poor return on a policy whose premise was that denial would widen the gap. The paradox's arithmetic is that controls converted a converging-capability problem into a converging-capability-plus-self-sufficiency problem: China catches up *and* exits dependency.

### The Localization Clock and the Leverage Half-Life

The forecasting question is therefore not whether chokepoint leverage exists—it does, concentrated and real—but how fast it decays. The evidence supports a rough half-life structure by component class.

Refrigerator engineering, while demanding, is mature physics with an adjacent industrial base in China's helium and LNG cryogenics sector.

**Helium-3: leverage decays slowest, and may not decay at all.** Helium-3 cannot be reverse-engineered; it is an isotope whose Western supply flows through a single government program at Savannah River [S14]. Meanwhile the supply side is *expanding* outside China: Interlune's domestic separation from natural helium, demonstrated at 99% purity in early 2025, plus lunar sourcing for 2028–2037, means the Western bloc is lengthening its isotope lead even as its cryostat lead erodes. [S93] China gains machine autonomy while remaining isotope-constrained. Each side retains one hand on the other's tap.

the open question is whether indigenous stacks scale to the million-channel regime fault tolerance demands before the Western superconducting leaders get there. Precision lasers for neutral atoms and trapped ions are a diversified market with no single point of control, which is why the control regimes have largely not targeted them: the EU list's parametric amplifiers and cryogenic components [S84] map onto superconducting needs, reflecting superconducting modalities' dominance in Western programs rather than a modality-neutral strategy. This leaves a gap in the control architecture itself—if the neutral-atom or photonic route wins the fault-tolerance race, today's control lists will have regulated the losers' supply chain.

### The 2035 Bifurcation and What It Costs

On the Western side, dilution refrigeration remains European, helium-3 remains American, and the integrated transatlantic stack functions—albeit at higher cost, because export-control compliance, entity screening, and duplicated licensing add friction to what was previously routine commerce, and because China's rare-earth and battery-material retaliation feeds back into Western optics, electronics, and magnet supply chains. On the Chinese side, a domestic stack—refrigerators (QuantumCTek, Origin), control systems (Tianji), processors (the Wukong and Zuchongzhi lines)—serves the state-directed program, with quality converging from behind and scale guaranteed by funding no market test disciplines; Between the two stacks, commerce in quantum components falls close to zero, and IISS's critical-node firms become, in effect, allied strategic assets.

The costs of bifurcation are asymmetric and mostly hidden. For China, the cost is efficiency: duplicated development at non-frontier quality subtracts perhaps a year or two from an already trailing program—absorbed easily by state patience. For the West, the cost is subtle and compounding: the control regime *raises Western costs too*. Every European cryostat firm must now run licensing compliance; every US–Chinese scientific collaboration requiring component transfer is dead; and crucially, the market for critical-node firms shrinks by the excluded Chinese demand, weakening the very firms the regime depends on. A Bluefors that cannot sell to Chinese research groups under presumption-of-denial licensing has fewer scale economies for the Western scale-out of the 2030s. The regime, in other words, taxes its own enforcement base.

Which scenario does this chapter's mechanism favor? The one scenario bifurcation actively *undermines* is Quantum Leap at global scale: a pre-2030 breakthrough would land inside one bloc and take years to propagate, because the diffusion channels—component trade, talent circulation, joint ventures—are precisely what the controls closed. [S107] The second-order implication deserves emphasis: **export controls do not merely divide supply chains; they divide verification and diffusion paths, so even a breakthrough arrives regionally, slower, and more contentiously than it would in an open system.**

### Watchpoints: Pricing the Leverage Decay

Four dated, observable signals will calibrate this chapter's projections. First, watch for Chinese peer-reviewed results (Physical Review Letters or Nature level) reporting experiments demonstrably run on domestic refrigeration at millikelvin scale—the appearance of frontier error-correction physics on indigenous cryostats would confirm the localization clock is running ahead of schedule [S22]. Second, watch the BIS Entity List cadence: if additions shift from Chinese component makers toward Chinese isotope and helium channels, it signals Washington has recognized where the durable leverage lies [S71]. Third, watch Interlune's deliveries against the 2028–2037 lunar contract [S39]: on-schedule isotope volume would materially soften the Western helium-3 constraint exactly as superconducting scale-out peaks. Fourth, watch whether the EU's standardization calls evolve into allied verification standards—if Europe converts chokepoint control into standards-setting, the bifurcated world acquires not just two supply chains but two certification regimes, institutionalizing multipolarity one layer deeper.

The final judgment on the paradox, stated as this report's estimate: the controls will be remembered less for slowing China—which they did, modestly and temporarily—than for ending the possibility that quantum computing would ever be a single, global industry. The leverage was real; it was also perishable;

## The Cryptographic Clock: PQC Migration Before Quantum Value

Every previous chapter of this report has treated the quantum computer as the protagonist—the machine that will or will not arrive on schedule, earn or fail to earn its trillion-dollar billing. This chapter is about a clock that does not wait for any machine. Because of harvest-now-decrypt-later, the cryptographic threat window is not a future event to be dated; it is an ongoing condition—the Cloud Security Alliance calls it "not a forecast — it is an ongoing operation," aimed in particular at the long-lived training data and model weights of AI infrastructure. That single fact inverts the economics of the entire quantum transition: the security bill arrives years, probably a decade, before the first quantum computer earns a commercially meaningful dollar. the European Union migrates through regulatory alignment; China pursues a state-directed hybrid posture that is partly opaque to the Western standards process.

### The Threat Window Is Already Open

"—asks the wrong question for anyone responsible for long-lived secrets. The Global Risk Institute and evolutionQ's Quantum Threat Timeline Report 2025, surveying 26 experts and published in March 2026, puts a CRQC at 28–49% probability within ten years, 51–70% within fifteen, and only about 15% within five. [S122]

But the survey numbers measure the probability of the machine existing, not the probability of exposure. Exposure is a function of data lifetime, and for intelligence archives, health records, state secrets, and long-lived cryptographic credentials, the relevant lifetime already spans the entire plausible CRQC distribution.

This is why the migration clock started in the mid-2020s regardless of hardware timelines. one that waits until a CRQC looks imminent has, by definition, waited too long. The window's arithmetic is unforgiving in both directions: the probability mass is not negligible, and the cost of being wrong compounds across the entire stock of long-lived encrypted data.

There is a respectable counterargument, and it deserves steelmanning before this chapter commits to its position. The skeptical case runs: expert surveys systematically overweight novel threats; Migration money spent now, on this view, is misallocated—better spent on quantum research itself.

The reply is that even if the skeptics are right about the machine, they are wrong about the money. NIST's draft IR 8547 would deprecate RSA and elliptic-curve cryptography after 2030 and disallow them entirely after 2035 [S10]—converting migration into a compliance requirement with a regulatory deadline, independent of whether any quantum computer exists. The deadline structure is not NIST acting alone: National Security Memorandum 10 set 2035 as the target for completing federal migration, and the Quantum Computing Cybersecurity Preparedness Act of December 2022 reinforced it. [S7] she faces a federal standard that prohibits the algorithms her systems run. The skeptics are arguing about physics; the compliance clock runs on regulatory fiat. That is the decisive asymmetry.

### IR 8547, the $7.1 Billion Bill, and a Market That Grows Without Physics

The institutional machinery of migration is already in motion. NIST published its first three final post-quantum standards in 2024; [S118] draft IR 8547, issued as an initial public draft in November 2024, sets the transition schedule—RSA, ECDSA, ECDH, and finite-field Diffie-Hellman deprecated after 2030, disallowed after 2035 [S10]. The 2035 cutoff deliberately encodes NIST's own expectation of a viable quantum breaking capability by then, meaning the standard itself prices the mid-2030s threat. [S114] NIST is now finalizing the document, and its finalization is one of this report's leading indicators: a final version holding the dates firm makes the compliance clock irreversible; a softened disallowance date would be the first genuine institutional signal of de-escalation.

The cost side is quantified for the US federal estate, and only there. In a July 2024 report to Congress, OMB together with ONCD, CISA, and NIST estimated approximately $7.1 billion (2024 dollars) to migrate prioritized federal civilian systems to post-quantum cryptography over 2025–2035—explicitly excluding national security systems [S114]. Two properties of that figure deserve emphasis. First, it is a floor: the private-sector analog across banking, healthcare, critical infrastructure, and technology vendors is a large multiple, though nobody has audited it with authority. Second, its phasing matches the deadline structure—spending concentrated in the years approaching 2030–2035, which means the outlay peaks precisely in the window when, on this report's central scenario, quantum-computing revenue is still measured in single-digit or low-tens-of-billions of dollars. [S7]

The market consequence is structural rather than cyclical. That inversion is the cleanest quantitative expression of this report's thesis: the defensive economy currently exceeds the productive one. And unlike every other segment of the quantum economy, PQC demand does not depend on any hardware milestone. PQC demand is driven by a dated regulatory prohibition. It is a compliance trade, not a physics trade—and that distinction is the single most useful classification an investor or budget officer can apply to the quantum sector in this decade. Migration cost has three further properties worth naming. It is pervasive but invisible, because cryptographic dependencies are buried in firmware, TLS stacks, payment networks, and industrial control systems their own operators cannot fully enumerate—which is why cryptographic discovery and inventory, the least glamorous phase, is itself a multi-year expenditure. And it is front-loaded relative to benefits: the organizations paying it receive, in return, only the non-occurrence of a catastrophic event whose probability no one can measure.

### Where This Report Stands on the CRQC Timeline

Synthesizing the calibrated evidence, this report's position on when a cryptographically relevant quantum computer exists is: **mid-to-late 2030s as the median, with the compression trend a more important fact than the level.**

Three evidence streams anchor the median.

Each such reduction moves the CRQC date earlier without any hardware advance at all. The mechanism matters: algorithmic improvements arrive on publication timescales—months—while hardware improvements arrive on engineering timescales—years. When the target moves toward the attacker faster than the hardware improves, expert medians drift earlier, which is exactly the pattern across successive GRI editions. Forecasters who anchor on today's probability level rather than its trend will systematically understate the threat;

One further caveat from the expert community itself deserves weight: covert state programs could be two or more years ahead of the open record, which means the honest forecast interval includes a machine that already exists behind classification, undetectable until it is used.

### Three Regions, Three Asymmetric Bills

**The United States: the largest attack surface, the most advanced migration machinery.** The American exposure is structural—the world's deepest digital economy, its reserve currency, its intelligence apparatus, and its cloud infrastructure all run on RSA/ECC at planetary scale. But the US also controls the standards process: NIST's post-quantum project [S103] is the de facto global standard, and federal procurement leverage forces migration through the entire vendor stack selling to Washington. The $7.1 billion federal estimate [S114] is the leading edge; OMB-driven deadlines pull every federal contractor through the transition by the early 2030s, giving US industry something rare—a forced rehearsal of quantum-era security on a fixed schedule.

**The European Union: migration by regulatory alignment.** Europe's path runs through the same NIST standards, adopted into European norms and reinforced by the EU's coordinated technology-security posture—visible in the September 2025 Delegated Regulation aligning the EU dual-use list with US, UK, and Japanese quantum controls [S84] and in EuroHPC's standardization calls extending Europe's deployment fabric into conformity infrastructure. The European position is distinctive in one respect: its regulatory instinct converts PQC from a security project into a single-market harmonization project, which historically means a slower start but more complete penetration. Europe's large public sector and long-lived industrial and governmental data face the same harvest-now-decrypt-later arithmetic, but once engaged, the EU's compliance machinery enforces broadly rather than at the frontier—and EuroHPC's procurement fabric gives member-state agencies a domestic institutional anchor for the transition that neither the US (procurement-driven) nor China (state-directed) replicates in quite the same form.

**China: the hybrid strategy, externally opaque.** China's posture is the outlier among the three. The CAS/USTC complex under Pan Jianwei operates the world's only national-scale quantum communication infrastructure, built on the same institutional base that delivered the Zuchongzhi superconducting line and the Jiuzhang photonic demonstrations [S21][S22][S36]. The strategic logic is defensive asymmetry: Beijing's threat model includes Western signals intelligence with harvest-now capabilities, and quantum key distribution offers key exchange whose security rests on physics rather than computational assumptions—insulated from any CRQC wherever the network reaches. The limitation is equally physical: QKD covers point-to-point links, not the installed base of public-key cryptography in ordinary commerce, payments, and infrastructure, so China must also run a PQC migration for everything the fiber and satellite networks cannot reach—including, plausibly, migration away from Western-designed lattice standards in sensitive domains toward domestically controlled algorithms. The forecasting consequence deserves emphasis: **China's cryptographic posture will be the least legible to outside observers.** Where the US and EU will demonstrate migration progress through procurement records, standards compliance, and vendor announcements, Chinese migration will be visible mainly through network deployments and standard-setting behavior. Western analysts should expect to read China's cryptographic timeline the way they read its quantum funding—structurally, not numerically, given that even the ~$15 billion funding figure originates from a non-public planning document no one has independently verified. [S4]

The regional asymmetry feeds back into this report's scenario structure in a way previous chapters established and this one deepens. A CRQC arriving in the late 2030s would arrive into a world already split by export controls and duplicated supply chains—meaning the cryptanalytic advantage, like the hardware, would be regional and slow to propagate. The cryptographic clock thus reinforces the report's central geopolitical finding: not one race with one winner, but parallel clocks running at different visibilities.

### The Compression Watchlist

Four dated, observable signals will calibrate the threat window faster than any expert survey. softening it would be the first institutional evidence of de-escalation. a cascade of Stage B failures pushes the threat mass rightward and would, perversely, do nothing to relax the regulatory deadlines already locked in.

The closing judgment is this report's position stated plainly. The quantum computer is a probability distribution; the migration deadline is a number on a calendar. Organizations and governments that treat the first as the trigger for acting on the second will spend the 2030s decrypting their own regret. The most likely single decade ahead, 2026–2035, is one in which quantum computing is overwhelmingly a cost center—$7.1 billion federally [S114], large multiples privately, on PQC alone —while the machines that justified the spending remain, at the median, just over the horizon. That is not an irony of the quantum transition. It is its defining economic structure, and every actor in this report's forecast—vendor, legislator, intelligence service, enterprise CIO—will spend the next decade navigating it.

## Economic Impact 2030–2040: Revenue, Value, and Jobs by Sector

Nine dollars in for every dollar out, by the wider measure, is not a mature industry's ratio; it is a wager.

### Why the Forecasts Diverge: Scope, Vintages, and Wishful Definitions

It is a disagreement about what is being counted.

The first fault line separates **revenue from value creation**. McKinsey's $1.3–2.7 trillion figure measures something entirely different—value for companies using quantum technology, including productivity and enablement effects across industries. A drug discovered faster with quantum simulation creates value for a pharmaceutical company regardless of what the quantum vendor charges for the compute; conversely, a vendor can book a billion dollars of cloud revenue that creates almost no end-user value if the machines run benchmark circuits for papers.

The second fault line is **scope within the revenue estimates themselves**.

The third fault line is **vintage restatement**, which the funding data expose most vividly.

The reconciliation follows. McKinsey's range represents cloud-integrated services with faster enterprise uptake; the trillion-dollar figures represent economy-wide value creation conditional on fault tolerance arriving and diffusing on schedule.

### The Pre-2035 Economy: Cloud, Services, and the PQC Anomaly

Before sector-level computational value materializes, three adjacent revenue pools carry the industry—and one of them has nothing to do with quantum computers at all.

This is the standard pattern of a platform technology's first commercial decade, but it means the "quantum economy" of 2026–2032 is substantially a research-equipment and exploration-services economy, and its revenue is a lagging indicator of scientific progress rather than a leading indicator of transformation.

Every major consultancy has built a quantum practice; every large bank and pharma runs an internal exploration team; none of this spending appears in quantum-vendor revenue. the 3.4× spread between the two estimates is another scope artifact, though the direction is unambiguous—quantum employment grows substantially in every scenario short of Long Winter, and the workers most in demand are not algorithm designers but the cryogenics technicians, control-systems engineers, and cryptography specialists that Chapters 4 and 5 identified as the binding constraints.

The defensive economy already exceeds the productive one. A reader asking when quantum starts producing economic value gets the wrong answer unless the ledger also shows quantum already consuming economic value, at scale, on a regulatory schedule.

### Sector Sequencing After Fault Tolerance: Who Earns What, and When

**Finance is the contested giant.** McKinsey's $400–600 billion finance figure for 2035 is the largest single sectoral claim in the literature—and it has drawn a published critique arguing the number does not survive decomposition. [S113] The critique's logic is sound: finance's quantum use cases (portfolio optimization, risk simulation, derivatives pricing) are the least proven to offer quantum advantage, and the sector's classical alternative keeps improving on the same schedule. The steelman for the large number is that finance has the shortest path from algorithm to dollar—no regulatory approval, no physical product, milliseconds from computation to trade—and the deepest pockets for early cloud access. This report's position: finance is the largest spender on early quantum access and the earliest PQC migrator, but its quantum-computational value capture by 2035 is more plausibly in the tens of billions than the hundreds. [S113]

**Materials, batteries, and energy scale later but with cleaner physics.** Materials simulation shares chemistry's favorable problem structure without pharma's regulatory lag: a better battery electrolyte or catalyst formulation enters products within years, not decades. If quantum materials simulation matures in the mid-2030s, it is the one major sector where benefits plausibly accrue substantially outside the United States, because the machines may be American but the manufacturing that monetizes the discoveries is not.

AI/ML applications are the most hype-adjacent claims in the sector, and nothing in the demonstrated hardware record supports quantum-accelerated training or inference within this window. These sectors belong in the post-2040 tail, and forecasts that front-load them into 2035 totals deserve the same discount Chapter 3 applied to IonQ's roadmap arithmetic. [S40]

### The Distributional Verdict: Value Follows the Cloud Layer

Who captures this value regionally has a structural answer that holds across the scenario table. Quantum economic value in the 2030s accrues at three layers: hardware, the cloud/access layer, and the application layer. The hardware layer most likely sits in the United States under baseline conditions—IBM's Starling in Poughkeepsie, Google's undated but peer-leading error-correction program, Quantinuum's Apollo —and the cloud layer is even more concentrated: American cloud platforms already distribute most global quantum access, meaning much European pharmaceutical quantum spending and Asian research spend flows through US-hosted infrastructure. and the PQC migration bill flows disproportionately to US-standards-following vendors and consultancies because NIST's process effectively defines the global product specification.

The result is a distributional asymmetry sharper than any qubit count. China captures state-directed capability and the materials-manufacturing downstream; Europe captures the indispensable supplier niche.

## China's Catch-Up Trajectory: Parity, Perpetual Second, or Leapfrog

This chapter argues that the answer does not hinge on the budget at all. the Chinese model, running on Five-Year-Plan timescales through the CAS/USTC complex, is not. Perpetual second is the central estimate; leapfrog is a real but minority path that runs precisely through the scenario Western investors fear most.

### The Evidence Base: One Year Behind, Verified in Print

Start with what China has demonstrably done, because the record is stronger than the casual dismissal of Chinese claims deserves. In December 2025, Zuchongzhi 3.2 achieved below-threshold surface-code error correction with a distance-7 code and suppression factor Λ = 1.40(6), published as a Physical Review Letters Editors' Suggestion [S22]—the first such milestone outside the United States, arriving roughly a year after Google's Willow demonstrated the same physics.

Two features of this record matter for forecasting. Second, and cutting the other way, Chinese flagship milestones arrive through peer review, not press release. Λ values and photon counts in Physical Review Letters cannot be inflated the way vendor specifications can, which means Chinese progress is more credible than skeptics assume and simultaneously less legible than American progress verified through DARPA's staged benchmarking. China has no institutional analogue to the Quantum Benchmarking Initiative;

Against this stand the structural weaknesses, and they are not cosmetic. And the talent channel that historically fed Chinese experimentalism, researchers trained in American and European laboratories before returning, is precisely what export controls and visa friction have suppressed, making talent decoupling the controls' most durable effect [S41].

### The Funding Asymmetry That Decides the Race

The decisive variable is not any of these technical gaps, which are real but closing on a state-funded clock. It is the asymmetry in how the two systems fail. Consider the capital structures. Cumulative US private quantum funding dwarfs China's by more than an order of magnitude, and Origin Quantum, the leading Chinese commercial firm, has raised only a small fraction of its American counterparts' capital, entirely from domestic investors. The Chinese frontier runs on appropriations that no market test disciplines and no election cycle interrupts. China backs both poles of its domestic ecosystem directly—state support sustains Origin Quantum's production lines and QuantumCTek's refrigerator and interconnect expansion alike—meaning the commercial and laboratory wings advance on the same state rails rather than on separate clocks.

Now run the two failure modes. State funding does not retrench when a roadmap slips; Five-Year Plans do not have quarters. A Western funding winter lasting from the late 2020s into the mid-2030s would hand China its catch-up window without requiring a single Chinese breakthrough: the frontier stops moving, and a program advancing even slowly closes a gap that is, on current evidence, only about a year wide in error correction.

This is the mechanism the chapter's title turns on, and it deserves statement as a causal chain rather than an innuendo. American leadership is capitalized by a market that prices milestones on a two-to-three-year horizon; Chinese leadership ambitions are capitalized by a state that prices them on a fifteen-year horizon; therefore any world in which the milestones are late is a world in which the relative value of patience rises. Export controls sharpen rather than blunt this dynamic: per RUSI's assessment, US controls accelerated the very domestic substitution they sought to prevent [S41], removing the one dependency—components—that would have constrained China during a Western winter, while leaving intact the one dependency—talent flows—that constrains it in every scenario. The result is that China enters the 2030s more autonomous in hardware and more isolated in people than at any point in the field's history: stronger in a slow race, weaker in a fast one.

A steelman of the leapfrog case—one that takes Chinese parity seriously rather than dismissing it—runs as follows. Qubit count is the axis on which state-directed programs scale best, and the kiloqubit target is an engineering problem of replication, not a physics problem. If qLDPC-class codes and related overhead reductions mature in the early 2030s—the same 10× qubit-requirement cuts that would shrink IBM's Starling-class machines—physical-qubit requirements for useful machines drop by an order of magnitude, and the country with guaranteed fabrication scale and unconstrained capital captures the benefit fastest. [S122]

### The Communication and Photonics Pole: Leadership That Is Already Real

Chinese leadership claims in quantum are usually argued prospectively, which obscures the fact that in two domains they are already settled. The CAS/USTC complex under Pan Jianwei operates the world's only national-scale quantum communication infrastructure, and the Fourteenth Five-Year Plan's designation of quantum information as the second-ranked cutting-edge technology field sustains the whole ecosystem—flagship processors and network alike—as a state priority. China's network lead is therefore inversely correlated with Western cryptographic comfort: the more credible the quantum threat becomes, the more the one country with deployed quantum communication infrastructure benefits.

The photonic pole is more nuanced. Jiuzhang 4.0's 3,050 photons is a fixed-purpose sampling demonstration, not a step toward universal fault tolerance—the honest read is that China leads photonics in the scale of demonstrated advantage while the West leads in the architecture most plausibly connected to useful computation: PsiQuantum's fab-manufactured Omega chipset, published in Nature with compute centers under construction in Brisbane and Chicago, though no logical-qubit count has been publicly demonstrated. [S38] If fault tolerance arrives via photonics, the US-Australia corridor most likely delivers it; if the photonic route stalls, China's boson-sampling records become museum pieces while remaining politically valuable proof of non-dependence. Either way, photonics consolidates rather than resolves the bifurcated Chinese profile: first at advantage theater, second at advantage economics.

### Observable Signals: What Confirms or Refutes Parity by 2033

Because Chinese progress is legible only through publication, the falsification points are unusually clean. Five dated signals will resolve the parity question faster than any budget estimate.

A Physical Review Letters or Nature paper showing Λ ≥ 2 on a thousand-qubit-class machine would mark genuine parity in error correction, closing the coefficient gap that currently defines second place [S22]. An announcement without publication should be treated as unverifiable. Second, the appearance of frontier error-correction physics demonstrably run on domestic refrigeration—results of Zuchongzhi-3.2 quality on QuantumCTek or Origin cryostats would confirm that the localization clock has outrun the quality gap, removing the last hardware dependency. Third, the first peer-reviewed logical-qubit paper from a Chinese commercial firm rather than USTC, which would signal that the state-directed ecosystem has developed a second pole of verified capability rather than a single flagship laboratory—particularly notable given that Origin Quantum, nominally the commercial champion, has published no error-correction work while the academic complex holds all the milestones. Fourth, any Chinese publication of logical qubits in the Helios regime—tens of logical qubits at low overhead, the current Western frontier —before IBM's Starling window closes. Fifth, and negatively: continued silence. If by 2033 no Chinese group has published a suppression factor above 2, the perpetual-second estimate hardens regardless of what the funding totals were. [S22]

The bottom line, stated as this report's estimate: through 2040 China is most likely a durable but converging second in universal quantum computing, an outright first in quantum communication, and a conditional first in photonic demonstration scale. [S111] The West's most consequential error would be to read China's opacity as stagnation; China's most consequential error would be to mistake publication parity for systems parity, since the distance from a Λ value in Physical Review Letters to a million-gate machine with real-time decoding—the gap IBM's 2026 Kookaburra decoder prototypes and Nighthawk's 7,500-gate circuits exist to cross —is the same distance every Western leader must also still traverse. [S18]

## Scenario Deep-Dive I: Steady Climb and Fragmented Multipolarity (55% combined)

<!-- viz:charts/scenario_probabilities.html -->
![Scenario Probabilities](demos/quantum-2040/charts/scenario_probabilities.png)

*Scenario Probabilities*

<!-- viz:charts/worldstate_trajectory.html -->
![Forecast Outcome-Share Trajectory](demos/quantum-2040/charts/worldstate_trajectory.png)

*Forecast Outcome-Share Trajectory*

The two scenarios this chapter examines carry the majority of this report's probability mass and, not coincidentally, describe the same world at different tempos. What separates the two scenarios is not whether fault tolerance arrives but who is standing when it does, and how divided the world is that receives it.

### Steady Climb: The Roadmap Machine That Actually Ships

The Steady Climb scenario is best understood as a specific sequence of deliveries, each with a named owner, a dated commitment, and a verification pathway. This is what distinguishes it from both the Long Winter (the sequence breaks) and the Quantum Leap (the sequence is overtaken by a single breakthrough): it is the scenario in which the industry's existing institutional machinery—dated roadmaps, staged government verification, peer-reviewed publication—converts claims into facts on roughly the advertised schedule.

The sequence runs as follows. End-2026: IBM's users—not IBM itself, a subtle but load-bearing hedge—demonstrate quantum advantage on Nighthawk hardware, running 7,500-gate circuits across up to three 120-qubit modules, while the Kookaburra prototype validates real-time error-correction decoding in the same year. [S18] it requires only that the modality leaders deliver, and an IonQ failure, if it comes, redistributes credibility toward those leaders rather than away from the field. By 2033: DARPA's Quantum Benchmarking Initiative delivers Stage C verdicts certifying at least one approach at utility scale [S11].

Three structural conditions must hold for this sequence to complete, and each has a plausible failure mode that would push the world toward a sibling scenario.

**Condition one: the systems layer scales multiplicatively.** Every machine in the 2028–2030 cluster requires solving three shared engineering problems simultaneously: real-time decoding of syndrome streams at logical clock speed, cryogenic I/O density sufficient for the physical-qubit count, and control electronics scaling from today's hundreds of channels toward millions. [S50] In Steady Climb these problems yield on industrial timescales, each solved once and then replicated, because they are engineering problems with classical-computing and semiconductor-test analogues rather than open physics questions. The below-threshold physics has already been settled twice, on two continents: Google's Willow halved logical error rates at each code-distance step from 3×3 to 7×7 grids, published in Nature, and USTC's Zuchongzhi 3.2 replicated the milestone with a distance-7 code and suppression factor Λ = 1.40(6), published as a Physical Review Letters Editors' Suggestion in December 2025—the first such result outside the United States, about a year after Google [S22]. What remains in Steady Climb is repetition at scale, which is precisely what industrial organizations are built to do.

Steady Climb therefore does not require flawless delivery; it requires that any single slip be absorbed by the anchored players. Here the ecosystem's structure matters: IBM's commitments ride a corporate balance sheet, Google's program sits inside Alphabet, and Quantinuum is majority-held by Honeywell. These anchors can finance a one-year slip without returning to market. The venture-financed fringe may correct—indeed, some correction is consistent with Steady Climb provided the revenue and verification criteria still clear—but the frontier advances because its funding does not depend on quarterly results.

Google's submission matters disproportionately: when the field's most credible scientific actor accepts external specification of progress, abstention by others becomes informative, and the industry's claims converge on a common yardstick. In Steady Climb, at least one approach—most probably superconducting, with neutral-atom close behind, consistent with Chapter 2's hardware assessment—survives Stage C verification.

The economic signature of Steady Climb follows from the delivery sequence with a three-to-five-year revenue-recognition lag.

At least two of the three must hold.

### Fragmented Multipolarity: Same Physics, Slower Clock, Divided World

The mechanism is the systems-layer analysis of Chapter 2 operating at half speed. Real-time decoding, cryogenic I/O, and logical clock speed are solved, but serially rather than in parallel: each machine generation surfaces a new bottleneck, adding twelve to eighteen months per generation rather than the collapse the Long Winter requires. The historical base rate supports this middle path.

The second clause—the regional split—is where this scenario does its distinctive analytical work, and it rests on a structural claim developed across Chapters 4 through 6: **no region's quantum stack is complete by construction, and export controls have converted incompleteness from a vulnerability into policy.** Consider the geography of the three leadership indicators. That is the multipolar outcome—not three racers on one track, but three yardsticks, each measuring the dimension its own system is built to win.

Europe deserves particular attention in this scenario because its position improves as the timeline lengthens. Europe is, uniquely among the three regions, long volatility in the fault-tolerance timeline.

The export-control dimension is the scenario's cement, and in this scenario controls are not background but structure. The bifurcation mechanism established in Chapter 5 runs: denial converts purchasable inputs into national mandates; and by the time localization completes, the denial has cost the controlling side its revenue and visibility while permanently insulating the target. Per RUSI's assessment, the controls accelerated the domestication they sought to prevent [S41]. IISS's assessment that regime effectiveness depends on a small number of geographically dispersed critical-node firms is, in this scenario, a description of permanent structural dependency rather than a policy observation.

A steelman against this scenario deserves an honest hearing, because it comes from both directions simultaneously. The reply to both is the same observation about how engineering programs of this scale actually behave: million-gate fault-tolerant machines are built in generations, and generations slip individually rather than jointly. A world in which IBM delivers late, QuEra delivers on time, China's kiloqubit arrives with publication but weak suppression data, and the verification regimes themselves diverge—DARPA benchmarking in the West, Physical Review Letters in China, EuroHPC standardization calls in Europe [S80]—is not a contrived midpoint. It is the default outcome of three differently-organized systems each succeeding partially on their own clocks.

### The Actors Who Decide Each Branch, and the Year-by-Year Signposts

Because both scenarios are roadmap-driven, the branch points are unusually well-attributed to named actors, and readers can track them on a calendar.

The end-2026 user-advantage claim on Nighthawk is the first checkable date in the chain, and Chapter 3's decision rule applies: a miss should discount all 2028–2029 logical-qubit claims by at least a year. [S40]

**Quantinuum and QuEra between them determine the overhead frontier.** If Apollo lands near 2030 with hundreds of logical qubits at near-2:1 encoding—and a later company blog even pulls universal fault tolerance forward to "by 2029" —the physical-qubit requirements for every application collapse and the commercial value timeline pulls forward within Steady Climb. [S122]

**USTC and Origin Quantum determine whether the multipolar split is real or nominal.** The kiloqubit demonstration around 2030, judged strictly by whether it arrives with peer-reviewed suppression data at Λ ≥ 2, is the decisive Chinese signal [S22]. Publication with strong suppression marks genuine capability parity in error correction and locks in the regional split; announcement without publication—or publication with weak suppression, Wukong-180's self-reported fidelities never having been independently benchmarked—leaves China legibly second and shifts mass toward the American-led reading of both scenarios. [S44]

PsiQuantum's $125 million Stage C agreement makes photonics the first route to face government-run verification at scale —a live test of whether fab-based manufacturing can leapfrog the cryogenic modalities' iteration cycles. [S60]

The consolidated signpost calendar, with the scenario each signal favors:

- Delivered → Steady Climb strengthens; missed → shift a year of discount across the cluster, Fragmented Multipolarity strengthens.
- Exists at specification → bullish but not scenario-defining; fails → credibility discount spreads through listed quantum equities, funding stress begins, but the modality leaders can absorb it.
- Delivered at ~10⁻⁶ logical error → the strongest single confirmation of Steady Climb available before Starling;
- Either delivered near specification → Steady Climb's technical criterion effectively met;
- **~2030**: China's kiloqubit demonstration, judged strictly by peer-reviewed suppression data. Λ ≥ 2 at kiloqubit scale → the multipolar split is substantiated; weak or unpublished → Chinese second place hardens regardless of qubit count.
- At least one utility-scale survivor → Steady Climb confirmed if the revenue criterion also holds; no survivor but substantial Stage B progress → Fragmented Multipolarity confirmed; cascading failure → Long Winter.
- revenue below that band with regional indicator splits completes Fragmented Multipolarity's.

One interaction between the scenarios and the cryptographic clock deserves final emphasis, because it is identical in both. Both scenarios are therefore worlds in which the quantum line item remains a cost center through the mid-2030s while the machines mature. The difference—and it is the entire difference between them—is whether, by the time the migration invoices are paid, one region holds a certified fault-tolerant machine and the commercial layer above it, or whether three regions hold three pieces of an arriving capability, separated by controls that no longer can be and no longer need to be reversed. Steady Climb is the world where quantum computing grows up on schedule in one place. Fragmented Multipolarity is the world where it grows up everywhere, late, and apart.

## Scenario Deep-Dive II: Long Winter and Quantum Leap (40% combined)

The two scenarios this chapter examines are the tails of the distribution, but they are not symmetric tails. The through-line connecting them is that both are triggered not by exotic events but by ordinary ones—a financing cycle turning, or a single engineering program compounding faster than expected—and both, in different ways, would make the regional asymmetries documented throughout this report decisive rather than merely important.

### Long Winter (30%): A Financial Scenario Wearing a Physics Costume

The first thing to understand about the Long Winter is that it is not primarily a prediction about quantum physics failing. It is a prediction about capital structure. two or more of the major listed quantum companies (IonQ, Rigetti, D-Wave) delisted or distress-acquired—describes a financial event with a technical trigger, not a technical dead end.

The financial precondition is already in place, and it deserves restating with precision because it is the single most load-bearing fact in the scenario's pricing. That is roughly nine dollars invested for every dollar earned by the wider measure. The pattern is a classic deep-tech cycle: capital arrives on narrative, exits on milestone performance, and the bridge between the two is built from proof points. What makes 2025's surge more dangerous than 2021's is scale relative to any plausible near-term revenue—even QED-C's own measured projection sees only roughly $3 billion of industry revenue by 2028. [S63]

**The mechanism of the winter, step by step.** The scenario's causal chain runs through five links, each observable in advance. This is the load-bearing assumption, and it is more plausible than any single-vendor analysis suggests, for the reason Chapter 2 developed: the modalities share systems-layer bottlenecks—real-time decoding, cryogenic I/O density, control-electronics scaling—that their marketing obscures. A decoder problem at IBM is a decoder problem at Google; a cryogenic wiring constraint binds every superconducting program simultaneously. Redundancy at the qubit layer does not guarantee redundancy at the systems layer, so correlated slippage is a live outcome even with three modalities progressing credibly.

Third, the correction propagates through public listings first, because the SPAC-era names carry retail valuations most sensitive to roadmap credibility.

Fifth, and most consequentially for the 2040 horizon, DARPA's Quantum Benchmarking Initiative delivers its Stage C verdicts by 2033 into this environment [S11]. A cascade of Stage B failures with no Stage C candidate would certify—formally, institutionally—that utility-scale operation was not reached on schedule, converting a market correction into a government-validated verdict. That is the moment the Long Winter stops being a funding story and becomes the official record.

**The steelman against the winter, answered honestly.** The strongest objection runs: three independent modalities are posting credible logical-qubit results simultaneously, and the anchored frontier players—IBM on a corporate balance sheet, Google inside Alphabet, Quantinuum majority-held by Honeywell—can finance multi-year slips without returning to market. The winter, on this view, prunes the fringe while the frontier keeps advancing: Steady Climb with casualties, not Long Winter. The reply has two parts. Second, the anchored players do not anchor the ecosystem's inputs: the cryogenics technicians, graduate students, and component suppliers are financed by precisely the appropriations and venture flows the winter freezes, and the National Quantum Initiative's authorization limbo—S.3597 extended to December 2034 with no stated dollar authorization, Ranking Member Zoe Lofgren confirming in April 2026 that the bill "does not have any funds authorized" [S53]—means the American public cushion does not exist when the private one deflates.

**Who wins the winter: China's patient clock.** The Long Winter is the one scenario in which the regional funding asymmetries of Chapters 4 and 6 become decisive. The American model prices milestones on a two-to-three-year venture horizon; the Chinese model, funded through Five-Year-Plan appropriations that no market test disciplines, prices them on fifteen-year horizons. A stopped frontier plus a moving follower equals closure of the gap without a single Chinese breakthrough. Export controls compound this: per RUSI's assessment, the controls accelerated China's domestic refrigerator and interconnect industry [S41], meaning China enters the winter more hardware-autonomous than at any point in the field's history. The winter is bad for quantum companies everywhere and structurally good for the two regions whose positions do not depend on venture exits.

### Quantum Leap (10%): One Breakthrough, Three Shocks

Verification must be independent—DARPA's QBI or Nature/Science-level peer review—which distinguishes the scenario definitionally from vendor claims.

The first is overhead compression in code design. Algorithms improve on publication timescales; hardware improves on engineering timescales; when the target moves toward the attacker faster than the machine scales, leap probabilities rise.

The case against pricing higher is calibration discipline, stated bluntly. Google, the actor with the strongest error-correction record in the field, publishes milestones but declines to date its next one—a long-lived logical qubit requiring a control system of millions of components, an engineering jump of orders of magnitude beyond anything demonstrated [S19].

The superconducting path—Google's Willow line compounding below-threshold physics with qLDPC-class overhead cuts, or IBM pulling Starling's specification forward on the strength of its 2026 Kookaburra decoder prototype and Nighthawk's 7,500-gate circuits —carries the largest single share, because it is the only route where verified below-threshold error correction and an explicit dated roadmap already coexist. [S18] The photonic dark horse deserves separate mention: PsiQuantum's Omega chipset, published in Nature and fabricated in a high-volume fab with compute centers under construction in Brisbane and Chicago, means that if fusion-based error correction works at all, the manufacturing scale-out could be faster than any cryogenic modality's—and its expanded $125 million Stage C agreement makes photonics the first route to face government-run verification of exactly this claim. [S60] Behind all of them sits Microsoft's topological wildcard: two fault-tolerantly demonstrated logical topological qubits would rewrite every overhead calculation simultaneously [S42], which is why the modality is priced as option value and why its failure would say nothing about the other routes.

**The consequences if it happens.** The leap's destabilization runs through three shocks in sequence. The first is a cryptographic crisis that arrives suddenly rather than gradually. The expert community already flags that covert state programs could be two or more years ahead of the open record; a leap would retroactively validate every aggressive estimate in the distribution, and harvest-now-decrypt-later operations would be recognized as having produced decryptable data all along.

The second shock is a sudden redistribution of geopolitical leverage concentrated in one bloc. The leap thus produces not global quantum advantage but regional quantum advantage, sharpened: the United States, or an allied program on US-anchored infrastructure, would hold a verified capability no rival could purchase, license, or replicate on any timeline.

The third shock is economic, and it inverts Chapter 7's sequencing. The one sector whose demand does not change—because it never depended on hardware timelines—is post-quantum cryptography; it simply becomes urgent rather than merely certain.

### The 5% Residual and the Boundary Discipline

The residual exists because a fourteen-year forecast horizon deserves epistemic humility stated numerically. a cryptographic surprise arriving from the mathematics rather than the hardware; a geopolitical rupture that reorganizes supply chains faster than any technical milestone; or Chinese capability revelations that turn out to have been years ahead of the open record, as the surveyed experts explicitly warn is possible. The residual is deliberately small because the four named scenarios were constructed to be exhaustive over their observable resolution criteria—but the honest statement is that the scenarios resolve on what can be measured, and the most consequential events in technological history are not always measurable in advance.

The boundary between this chapter's scenarios and their neighbors deserves final restatement, because misclassification is the main analytical risk. Long Winter is not any funding correction: a 2027–2028 pullback that leaves revenue growing toward $5 billion and the anchored frontier intact is Steady Climb with casualties. [S122] the task must be commercially relevant, non-contrived, and independently verified. it is the statement that the two futures in which quantum computing either fails its financiers or stuns its skeptics are, together, nearly as likely as the futures in which it merely arrives on time—and that the preparations each demands are almost entirely disjoint.

## Forecast Ledger: Twelve Resolution-Ready Binary Predictions

A forecast earns its keep only when it can be graded. Everything preceding this chapter—the scenario weights, the modality rankings, the regional trajectories, the cryptographic clock—resolves into claims about the world that either come true or do not by specific dates. This chapter converts the report's analytical structure into twelve binary predictions, each with a deadline, an explicit probability, a named resolution source, and a statement of which scenarios it discriminates between. The discipline is borrowed from prediction-market practice: every probability below is a price this report is willing to be judged on, calibrated against external anchors—the Global Risk Institute's expert distribution [S5], QED-C's measured revenue baselines, DARPA's verification calendar, and the vendor roadmap cluster —rather than against the report's own narrative momentum. One entry deliberately breaks with the twelve: where an ungraded claim would have been tempting, the ledger's own convention excluded it, and the exclusion is itself informative.

### How to Read the Ledger

Three conventions govern every entry. First, resolution requires an identified source: a named publication, a government action, a corporate disclosure, or a specified measurement convention. Second, each prediction states which of the four scenarios it separates, because the value of a binary forecast lies not in being right but in distinguishing between futures that require different preparations. any entry implying a different weighting would silently reprice the report, and where tension exists it is flagged rather than hidden.

The table gives the twelve predictions in dated order; the prose that follows justifies each probability, steelmans the strongest opposing price where the entry is genuinely contested, and identifies second-order consequences if it resolves yes.

### The Twelve Predictions

| # | Prediction (binary) | Deadline | Prob. | Resolution source | Discriminates |
|---|---|---|---|---|---|
| 1 | IBM publicly demonstrates user-driven quantum advantage on Nighthawk-class hardware in peer-reviewable form | 2027-06-30 | 40% | arXiv/Nature publication or IBM technical disclosure | Steady Climb vs. Long Winter |
| 2 | US NQI reauthorization enacted with ≥$1.8 billion stated authorization | 2027-12-31 | 55% | Enacted bill text (Congress.gov) | Funding resilience |
| 3 | — | 2028-06-30 | 20% | Peer-reviewed publication or QBI-verified result | Listed-quantum credibility |
| 4 | — | 2029-12-31 | 35% | Amazon Braket availability plus independent benchmark | Steady Climb vs. Fragmented |
| 5 | — | 2030-12-31 | 35% | QBI Stage C or peer-review verification | Steady Climb vs. all others |
| 6 | QED-C-measured industry revenue exceeds $5 billion in a calendar year | 2032-12-31 | 40% | QED-C annual report | Steady Climb vs. Long Winter |
| 7 | — | 2033-12-31 | 45% | Physical Review Letters / Nature paper | Multipolar split vs. second place |
| 8 | DARPA QBI certifies at least one approach at utility scale | 2033-12-31 | 40% | DARPA announcement | Steady Climb/Leap vs. Winter |
| 9 | At least one of IonQ/Rigetti/D-Wave delisted or distress-acquired | 2029-12-31 | 45% | Exchange filings, acquisition disclosures | Long Winter onset |
| — | NIST IR 8547 finalized with the 2035 disallowance date intact | — | — | NIST CSRC publication | Compliance clock |
| — | China achieves practical dilution-refrigerator import independence | — | — | Peer-reviewed results on domestic cryostats; supply-chain reporting | Chokepoint leverage decay |
| — | — | — | — | ArXiv-to-journal publication | CRQC compression trend |

### Hardware Delivery: The Four Claims That Anchor Everything

The probability prices three factors. Favoring delivery: the claim is scoped to capability that already exists in the fleet rather than to a future machine, and IBM's cloud business gives it incentive continuity. The six-month grace period beyond IBM's own deadline prices slippage without total failure. This is the earliest date in the ledger; its resolution should move the reader's pricing of every subsequent hardware entry in the same direction.

Oxford Ionics' 99.99% two-qubit gate fidelity claim of October 2025, on the selected-pair convention, is the best ion number on record [S27]; IonQ consolidated capability through acquisitions including Lightsynq and the roughly $1.1 billion Oxford Ionics transaction; and trapped-ion overhead near the 2:1 encoding Helios demonstrated means large logical capability does not require millions of physical qubits. A no resolution sends the credibility discount through all SPAC-era listings and materially strengthens Prediction 9.

against that, state funding operates on Five-Year-Plan timescales that do not retrench, and peer-reviewed Chinese milestones have historically arrived when skeptics discounted them. A yes makes the multipolar split substantive; a no hardens perpetual second place regardless of qubit counts.

### Verification, Revenue, and the Market Test

PsiQuantum holds an expanded $125 million Stage C agreement it calls its most valuable US government deal, making photonics the first route to face this test at scale, and Google joined Stage A in September 2025, converting the field's most credible scientific actor into a participant in a common standard. [S60] First, "utility scale" under government-run testing is a stricter bar than a vendor demonstrating 100 logical qubits—a machine can satisfy Steady Climb's technical criterion via peer review while failing QBI's utility threshold. [S45] A yes here plus a yes on Prediction 6 would complete Steady Climb's resolution contract; a no across the portfolio is the formal, institutional trigger for the Long Winter criteria.

Doubling from $3 billion to $5 billion in four years requires early fault-tolerant machines delivering commercial access, which is why the price aligns with Steady Climb plus the front edge of Quantum Leap. The steelman for a higher number: government procurement fabrics—EuroHPC's six deployed systems and four new quantum calls issued in June 2026 alongside roughly €119 million in 2026 quantum-technology funding —plus PQC-adjacent spending could push measured revenue up independently of hardware timelines. [S79] the increment to $5 billion needs production workloads.

Critically, one distress event is consistent with all four scenarios; it does not require the winter, only ordinary capital-cycle pruning of the weakest position in a sector priced for perfection. What would distinguish Long Winter is the scenario-table criterion—two or more of the named companies failing—so this entry should be read as the early-warning gauge for that scenario rather than a downshift of the central case.

### Policy, Supply Chains, and the Cryptographic Compression

The lapsed H.R. The slightly-better-than-even price reflects genuine two-sided risk: bipartisan momentum and the geopolitical framing favor enactment, while the demonstrated congressional capacity to let the authorization lapse entirely—plus the precedent of a no-dollar bill advancing out of committee—argues the enacted figure, if any, lands below $1.8 billion.

NIST's transition schedule—deprecating RSA, ECDSA, ECDH, and finite-field Diffie-Hellman after 2030 and disallowing them entirely after 2035—has already survived its initial public draft of November 2024, the first three final post-quantum standards were published in 2024, and National Security Memorandum 10 independently fixed 2035 as the federal migration target, reinforced by the Quantum Computing Cybersecurity Preparedness Act of December 2022. [S7] Readers should treat a softening here as one of the few events that would justify repricing the entire cryptographic thesis downward.

What keeps this from resolving trivially is the quality gap—indigenous cryostats trailing Bluefors-class stability at the frontier—and the definitional question of what counts as independence. The resolution standard: peer-reviewed frontier error-correction results demonstrably run on domestic refrigeration, or credible supply-chain reporting that Chinese superconducting programs operate predominantly on domestic units. A yes accelerates the leverage-decay mechanism of the supply-chain chapter and strengthens Fragmented Multipolarity's bifurcation; a no preserves Western leverage into precisely the Starling-scale-out window, when refrigerator demand peaks.

A peer-reviewed estimate below one million physical qubits would pull every CRQC median earlier without any machine existing. This is the one entry whose resolution yes is bad news for nearly every actor in the report—and the one whose value lies entirely in watching it, since the publication, if it comes, will be public, dated, and impossible to un-read.

### The Ledger's Aggregate Discipline

Read as a portfolio, the twelve predictions enforce the report's structural conclusions on anyone tempted to round them off. The market cluster (6, 9) brackets the funding question between moderate growth and visible distress without committing to the winter. Two coherence checks deserve explicit statement. First, Predictions 4 and 5 cannot both resolve no and leave Steady Climb alive; a reader tracking the ledger should treat a joint miss as the moment to shift mass toward Long Winter regardless of intermediate news. Every probability is falsifiable, every source is named, and every date is on the calendar. The reader who returns to this table in 2028 with five or six resolutions in hand will know more about quantum computing's future than any roadmap slide deck can show—and will be able to grade this report with the same severity it applied to the vendors. [S48]

## Calibration, Divergence, and Decision Implications

Every forecast in this report rests on a foundation that is, frankly, thinner than the confident vendor slideware and trillion-dollar consultancy decks would suggest. This closing chapter does three things the rest of the report deferred: it aggregates the scenario pricing into a single master table, explains candidly why overall confidence is rated low and where this report deliberately diverges from external anchors, and converts the forecast into concrete decisions for four audiences. The through-line is a single asymmetry established in Chapter 1: the costs of the quantum transition (post-quantum cryptography migration, supply-chain bifurcation) arrive with near-certainty years before the benefits (fault-tolerant computation at commercial scale), which means most readers must act on this forecast under genuine uncertainty about the upside but very little uncertainty about the downside obligations.

### The Forecast Master Table and Its Calibration Logic

| Scenario | Probability | Defining condition (by 2033 unless noted) |
|---|---|---|
| Steady Climb | — | — |
| Long Winter | — | — |
| Fragmented Multipolarity + Delayed Fulfillment | — | leadership indicators split across ≥2 regions with controls cementing the divide |
| Quantum Leap | — | — |
| Other / unanticipated | 5% | — |

That is not pessimism for its own sake; it is a direct read of the funding-to-revenue ratio. The probability mass splits almost evenly between incremental delivery and retrenchment precisely because the discriminating evidence—DARPA's Quantum Benchmarking Initiative verdicts, due by 2033 [S11]—will not arrive until the venture cycle has already had to refinance twice.

Confidence in this pricing is low for three structural reasons, and honesty about them is more useful than false precision.

First, the physics of error-correction scaling remains irreducibly uncertain. Whether suppression factors, logical clock speeds, real-time decoders, and cryogenic I/O scale multiplicatively without new failure modes is exactly the question DARPA's staged verification exists to answer, and no amount of market analysis substitutes for it.

Second, the China data are unverifiable at the load-bearing points. A forecast of Chinese catch-up versus perpetual second place swings materially on numbers nobody outside the Chinese state can audit.

Third, the market baselines themselves are unstable. Any calibration built on these series inherits their volatility, which is why this report's revenue-based falsification criteria specify the QED-C measurement convention explicitly.

### Where This Report Diverges from External Anchors—and Why

Divergence from vendor roadmaps. This report prices meaningful probability on timelines the vendors do not acknowledge. IBM is more disciplined but still asserts it is the only organization that will run hundreds of logical qubits by decade's end.

Divergence from McKinsey's value framing. This report's Chapter 7 reconciliation concludes most pre-2035 realized value comes from enabling services, cloud access, and PQC rather than quantum computation itself; [S18] Readers should treat the trillion-dollar figures as an upper bound conditional on Steady Climb or Quantum Leap, not a central estimate.

Divergence on CRQC urgency, in both directions. The trend of expert revision is upward, and forecasters who anchor on the level rather than the trend will understate the threat. NIST's draft IR 8547—deprecating RSA/ECC after 2030 and disallowing them after 2035—effectively institutionalizes mid-2030s as the planning deadline [S10], which this report treats as the right default.

On the Quantum Leap weighting specifically, a note on internal dissent. This report's structured expert elicitation exercises—used diagnostically, not as observation—repeatedly pushed weight toward the leap scenario, reflecting the logic that Willow's below-threshold result plus qLDPC-style overhead reductions could compound quickly in one modality. Internal scenarioDeduction material informing this report showed exactly this kind of drift toward the salient breakthrough narrative, which is why the published number is anchored to the external expert distribution instead.

A steelman of the bull case deserves an answer before moving on. correlated success across redundant paths is more likely than in any previous quantum decade. But the modalities share deeper bottlenecks than their marketing suggests: real-time decoding, cryogenic wiring density, and control-electronics scaling are common infrastructure problems, and DARPA's independent benchmarking exists precisely because the field's claims have outpaced its verified results.

### Decision Implications

**For US policymakers: close the authorization gap and fund PQC as a certainty.** The National Quantum Initiative's authorization lapsed into limbo: H.R. The window for fixing this is the current Congress; every year of gap widens the relative advantage of state-patient funding models precisely when the venture cycle may retrench. Funding it as a certainty, on schedule, is cheaper than every plausible alternative.

The pragmatic sequence is unglamorous—inventory, prioritize long-lived secrets, pilot hybrid classical/PQC protocols—precisely because it does not require believing any particular fault-tolerance timeline.

If those slip while DARPA's staged verdicts fail to validate utility-scale claims, the correction will be concentrated and fast, and the Long Winter indicators (delistings, distressed consolidation among IonQ, Rigetti, D-Wave) become live. The former is a compliance trade; the latter is a physics trade, and only the second one can go to zero.

**For allied governments: coordinate controls around genuine chokepoints before localization erodes them.** The US September 2024 rule and the EU's September 2025 dual-list alignment already cover nearly the entire quantum stack, but their leverage decays on a clock set in Hefei and Shanghai: Chinese domestic refrigerator and interconnect production expanded directly in response to the controls, and Origin Quantum's SL1000 refrigerator line has been operational since mid-2024. [S100] Chokepoint leverage is real but perishable—concentrated today in European cryogenics and US-controlled helium-3 supply, contested tomorrow by state-directed substitution. The policy implication is sequencing: extract coordination value (intelligence sharing, talent-flow management, joint verification standards like QBI-style benchmarking) in the near term rather than maximizing friction, because controls that accelerate self-sufficiency while their targets are still a generation behind convert a temporary lever into a permanent bifurcation.

The final calibration note is the most important one. Nothing in this report's probability table should be read with more precision than roughly ±10 percentage points per scenario. [S117]

## Visual Annex

_Deterministic visualizations supporting this report, generated from structured artifacts._

<!-- viz:charts/timeline_lanes.html -->
![Event Timeline](demos/quantum-2040/charts/timeline_lanes.png)

*Event Timeline*

## How to Verify This Forecast (Resolution Criteria & Indicators)
This section lists **falsifiable, trackable** resolution criteria for each scenario, plus dated/triggered indicators for future scoring and calibration.

### Per-Scenario Resolution Criteria
- **[30%] Steady Climb (Baseline: early-fault-tolerance in 2030–2033, US in the lead)**: Falsifiable criteria: (1) By 2033-12-31, at least one vendor has independently verified (via DARPA QBI or peer review) a machine running ≥100 logical qubits with a logical error rate ≤1e-6; (2) Quantum computing industry annual revenue (QED-C basis) reaches 50–200 hundred million USD before 2035; (3) No CRQC capable of breaking RSA-2048 appears before 2035. If ≥2 of these three conditions are met and the "Long Winter" conditions do not apply, this scenario is judged to hold.
- **[10%] Quantum Leap (utility-scale breakthrough before 2030, PQC crisis becomes urgent)**: Falsifiable criteria: By 2030-12-31, a machine independently verified by a third party (DARPA QBI or Nature/Science-level peer review) completes, within hours, a commercially relevant task (not an artificially constructed problem) that a classical supercomputer cannot complete in a reasonable time, with ≥200 logical qubits. If this condition is met, this scenario is judged to hold.
- **[30%] Long Winter (scaling stagnates, funding retreats, value confined to niches)**: Falsifiable criteria: (1) By 2033-12-31, no vendor has achieved an independently verified machine with ≥50 logical qubits and logical error rate ≤1e-6; (2) Industry annual revenue (QED-C basis) falls below 20 hundred million USD and private investment declines ≥50% from the 2025 peak; (3) ≥2 of the major listed companies (e.g., IonQ, Rigetti, D-Wave) are delisted or acquired cheaply. If ≥2 conditions are met, this scenario is judged to hold.
- **[25%] Fragmented Multipolarity + Gradualist Hybrid (default / most likely continuation of the status quo: delayed delivery under a multipolar order)**: Falsifiable criteria (conjunctive): (A) Technical side: By 2033-12-31 no vendor achieves ≥100 independently verified logical qubits, but before 2038 at least one reaches ≥50 logical qubits with logical error rate ≤1e-6 (i.e., delayed but not stalled, while excluding both the Winter and Baseline scenarios); (B) Geopolitical side: By 2035-12-31, the three leading indicators — logical qubit count, fidelity, and commercial revenue — are dispersed across ≥2 regions, and quantum-related items on export control lists increase ≥20% over 2026, or China's domestic share in dilution refrigerators / helium--3 substitutes reaches ≥30%. If both A and B hold, this scenario is judged to hold.
- **[5%] Other / Unanticipated Paths**: Falsifiable criteria: By 2040-12-31, if the actual evolution path satisfies the resolution criteria of none of the preceding four scenarios, it falls into this scenario.

## References

1. [S114] White House PQC Cost Estimate: $7.1B to Migrate Federal Civilian System — postquantum.com — [https://postquantum.com/security-pqc/white-house-pqc-estimate/](https://postquantum.com/security-pqc/white-house-pqc-estimate/)
2. [S2] Google hardware is powering quantum breakthroughs — blog.google — [https://blog.google/innovation-and-ai/technology/research/quantum-hardware-verifiable-advantage/](https://blog.google/innovation-and-ai/technology/research/quantum-hardware-verifiable-advantage/)
3. [S46] Quantum error correction below the surface code threshold - Nature — nature.com — [https://www.nature.com/articles/s41586-024-08449-y](https://www.nature.com/articles/s41586-024-08449-y)
4. [S111] Quantum computing to create over $450 billion of economic value by 2040 — marks-clerk.com — [https://www.marks-clerk.com/insights/latest-insights/102jf66-quantum-computing-to-create-over-450-billion-of-economic-value-by-2040/](https://www.marks-clerk.com/insights/latest-insights/102jf66-quantum-computing-to-create-over-450-billion-of-economic-value-by-2040/)
5. [S1] Meet Willow, our state-of-the-art quantum chip — blog.google — [https://blog.google/innovation-and-ai/technology/research/google-willow-quantum-chip/](https://blog.google/innovation-and-ai/technology/research/google-willow-quantum-chip/)
6. [S11] QBI | DARPA — darpa.mil — [https://www.darpa.mil/research/programs/quantum-benchmarking-initiative](https://www.darpa.mil/research/programs/quantum-benchmarking-initiative)
7. [S122] Quantum Threat Timeline Report 2025 — globalriskinstitute.org — [https://globalriskinstitute.org/mp-files/pdf-quantum-threat-timeline-report-2025.pdf/](https://globalriskinstitute.org/mp-files/pdf-quantum-threat-timeline-report-2025.pdf/)
8. [S73] Export Controls Accelerate China’s Quantum Supply Chain | Royal United Services Institute — rusi.org — [https://www.rusi.org/explore-our-research/publications/commentary/export-controls-accelerate-chinas-quantum-supply-chain](https://www.rusi.org/explore-our-research/publications/commentary/export-controls-accelerate-chinas-quantum-supply-chain)
9. [S50] Quantinuum Unveils Accelerated Roadmap to Achieve Universal, Fully Fault-Tolerant Quantum Computing by 2030 — quantinuum.com — [https://www.quantinuum.com/press-releases/quantinuum-unveils-accelerated-roadmap-to-achieve-universal-fault-tolerant-quantum-computing-by-2030](https://www.quantinuum.com/press-releases/quantinuum-unveils-accelerated-roadmap-to-achieve-universal-fault-tolerant-quantum-computing-by-2030)
10. [S78] EuroHPC JU Launches Procurement for a Quantum Computer in... — eurohpc-ju.europa.eu — [https://www.eurohpc-ju.europa.eu/eurohpc-ju-launches-procurement-quantum-computer-luxembourg-2026-07-23_en](https://www.eurohpc-ju.europa.eu/eurohpc-ju-launches-procurement-quantum-computer-luxembourg-2026-07-23_en)
11. [S81] EuroHPC JU launches procurement for a new quantum computer in... — eurohpc-ju.europa.eu — [https://www.eurohpc-ju.europa.eu/eurohpc-ju-launches-procurement-new-quantum-computer-germany-2023-11-24_en](https://www.eurohpc-ju.europa.eu/eurohpc-ju-launches-procurement-new-quantum-computer-germany-2023-11-24_en)
12. [S22] USTC’s Zuchongzhi 3.2 Achieves Below-Threshold QEC Milestone - Quantum Computing Report — quantumcomputingreport.com — [https://quantumcomputingreport.com/ustcs-zuchongzhi-3-2-achieves-below-threshold-qec-milestone/](https://quantumcomputingreport.com/ustcs-zuchongzhi-3-2-achieves-below-threshold-qec-milestone/)
13. [S104] NIST IR 8547 Explained: 2030 and 2035 PQC Deadlines — encryptionconsulting.com — [https://www.encryptionconsulting.com/nist-ir-8547-2030-2035-action-plan/](https://www.encryptionconsulting.com/nist-ir-8547-2030-2035-action-plan/)
14. [S23] IQM achieves milestone in quantum error correction, enabling fault-tolerant computing in the near-term - IQM Quantum Computers — iqm.tech — [https://iqm.tech/press-releases/iqm-achieves-milestone-in-quantum-error-correction-enabling-fault-tolerant-computing-in-the-near-term/](https://iqm.tech/press-releases/iqm-achieves-milestone-in-quantum-error-correction-enabling-fault-tolerant-computing-in-the-near-term/)
15. [S31] Harvard, MIT & QuEra — quera.com — [https://www.quera.com/press-releases/harvard-university-mit-and-quera-demonstrate-historic-99-5-two-qubit-gate-fidelity-on-60-neutral-atom-qubits](https://www.quera.com/press-releases/harvard-university-mit-and-quera-demonstrate-historic-99-5-two-qubit-gate-fidelity-on-60-neutral-atom-qubits)
16. [S35] PsiQuantum Announces Omega, a Manufacturable Chipset for Photonic Quantum Computing — PsiQuantum — psiquantum.com — [https://www.psiquantum.com/news-import/omega](https://www.psiquantum.com/news-import/omega)
17. [S19] Roadmap | Google Quantum AI — quantumai.google — [https://quantumai.google/roadmap](https://quantumai.google/roadmap)
18. [S18] Quantum Roadmap — IBM Technology Atlas — ibm.com — [https://www.ibm.com/roadmaps/quantum/](https://www.ibm.com/roadmaps/quantum/)
19. [S60] PsiQuantum Signs $125 Million Agreement with DARPA — psiquantum.com — [https://www.psiquantum.com/news-import/psiquantum-signs-125-million-agreement-with-darpa](https://www.psiquantum.com/news-import/psiquantum-signs-125-million-agreement-with-darpa)
20. [S63] QED-C | Global Quantum Computing Market to Double by 2028, Reaching $3 Billion in Revenue, QED-C® State of the Global Quantum Industry 2026 Report Finds | QED-C — quantumconsortium.org — [https://quantumconsortium.org/global-quantum-computing-market-to-double/](https://quantumconsortium.org/global-quantum-computing-market-to-double/)
21. [S12] Stage B selection | DARPA — darpa.mil — [https://www.darpa.mil/research/programs/quantum-benchmarking-initiative/stage-b-selection](https://www.darpa.mil/research/programs/quantum-benchmarking-initiative/stage-b-selection)
22. [S48] IonQ’s 2025 Roadmap: Toward a Cryptographically Relevant Quantum Computer by 2028 — postquantum.com — [https://postquantum.com/industry-news/ionqroadmap-crqc/](https://postquantum.com/industry-news/ionqroadmap-crqc/)
23. [S14] Supply and Demand of Helium-3 (He-3) — isotopes.gov — [https://www.isotopes.gov/Supply-and-Demand-of-Helium-3](https://www.isotopes.gov/Supply-and-Demand-of-Helium-3)
24. [S38] Jiuzhang 4.0: 3,050 Photons, 25.6 Microseconds, and a Direct Answer... — postquantum.com — [https://postquantum.com/industry-news/jiuzhang-4-0/](https://postquantum.com/industry-news/jiuzhang-4-0/)
25. [S71] Additions and Revisions to the Entity List — federalregister.gov — [https://www.federalregister.gov/documents/2025/09/16/2025-17893/additions-and-revisions-to-the-entity-list](https://www.federalregister.gov/documents/2025/09/16/2025-17893/additions-and-revisions-to-the-entity-list)
26. [S39] Helium-3 in Quantum Computing: Hype vs. Reality — postquantum.com — [https://postquantum.com/quantum-systems-integration/helium-3-quantum-computing/](https://postquantum.com/quantum-systems-integration/helium-3-quantum-computing/)
27. [S41] China's Quantum Supply Chain: How Export Controls Are Building What They Sought to Prevent — postquantum.com — [https://postquantum.com/china-quantum-ambition/china-supply-chain-self-sufficiency/](https://postquantum.com/china-quantum-ambition/china-supply-chain-self-sufficiency/)
28. [S80] Four New EuroHPC JU Calls to Boost Quantum Innovation and... — eurohpc-ju.europa.eu — [https://www.eurohpc-ju.europa.eu/four-new-eurohpc-ju-calls-boost-quantum-innovation-and-standardisation-europe-2026-06-02_en](https://www.eurohpc-ju.europa.eu/four-new-eurohpc-ju-calls-boost-quantum-innovation-and-standardisation-europe-2026-06-02_en)
29. [S94] Quantum Cryogenic Infrastructure and Helium-3 Guide — postquantum.com — [https://postquantum.com/building-quantum-computers/quantum-cryogenic-infrastructure-helium3/](https://postquantum.com/building-quantum-computers/quantum-cryogenic-infrastructure-helium3/)
30. [S100] Guidance re: New Export Controls on Quantum Technology and Associated Deemed Exports | UChicago University Research Administration | The University of Chicago — ura.uchicago.edu — [https://ura.uchicago.edu/policy-library/guidance-re-new-export-controls-quantum-technology-and-associated-deemed-exports](https://ura.uchicago.edu/policy-library/guidance-re-new-export-controls-quantum-technology-and-associated-deemed-exports)
31. [S93] Interlune Develops Cryogenic Technology to Expand Helium-3 Supply for Quantum Computing — thequantuminsider.com — [https://thequantuminsider.com/2026/07/20/interlune-produces-pure-helium-3-from-domestic-helium-using-novel-cryogenic-technology/](https://thequantuminsider.com/2026/07/20/interlune-produces-pure-helium-3-from-domestic-helium-using-novel-cryogenic-technology/)
32. [S84] 2025 Update of the EU Control List of Dual-Use Items — policy.trade.ec.europa.eu — [https://policy.trade.ec.europa.eu/news/2025-update-eu-control-list-dual-use-items-2025-09-08_en](https://policy.trade.ec.europa.eu/news/2025-update-eu-control-list-dual-use-items-2025-09-08_en)
33. [S107] Global Quantum Computing Market to Grow 34.6% Annually Through 2030 — bccresearch.com — [https://www.bccresearch.com/pressroom/ift/global-quantum-computing-market-to-grow-346?srsltid=AU7gw4XWlFkNffwIRtpDHvXk4wxhORLsIAcKI5Pk5ZMqOl8tx2VptjcG](https://www.bccresearch.com/pressroom/ift/global-quantum-computing-market-to-grow-346?srsltid=AU7gw4XWlFkNffwIRtpDHvXk4wxhORLsIAcKI5Pk5ZMqOl8tx2VptjcG)
34. [S10] IR 8547, Transition to Post-Quantum Cryptography Standards | CSRC — csrc.nist.gov — [https://csrc.nist.gov/pubs/ir/8547/ipd](https://csrc.nist.gov/pubs/ir/8547/ipd)
35. [S7] H.R. 6213, National Quantum Initiative Reauthorization Act | Congressional Budget Office — cbo.gov — [https://www.cbo.gov/publication/60891](https://www.cbo.gov/publication/60891)
36. [S118] The Quantum Threat Timeline: Why Organizations Must Act Now - evolutionQ — evolutionq.com — [https://www.evolutionq.com/post/the-quantum-threat-timeline-why-organizations-must-act-now](https://www.evolutionq.com/post/the-quantum-threat-timeline-why-organizations-must-act-now)
37. [S103] Post-Quantum Cryptography | CSRC — csrc.nist.gov — [https://csrc.nist.gov/projects/post-quantum-cryptography](https://csrc.nist.gov/projects/post-quantum-cryptography)
38. [S21] Establishing a New Benchmark in Quantum Computational Advantage with 105-qubit Zuchongzhi 3.0 Processor | Phys. Rev. Lett. — link.aps.org — [https://link.aps.org/doi/10.1103/PhysRevLett.134.090601](https://link.aps.org/doi/10.1103/PhysRevLett.134.090601)
39. [S36] Quantum computational advantage with a programmable photonic processor | Nature — nature.com — [https://www.nature.com/articles/s41586-022-04725-x](https://www.nature.com/articles/s41586-022-04725-x)
40. [S4] When will fault-tolerant quantum computers be available? — quera.com — [https://www.quera.com/questions/when-will-fault-tolerant-quantum-computers-be-available](https://www.quera.com/questions/when-will-fault-tolerant-quantum-computers-be-available)
41. [S113] McKinsey's $600B Quantum Finance Number Doesn't Add Up — postquantum.com — [https://postquantum.com/quantum-computing/mckinsey-quantum-finance-600b/](https://postquantum.com/quantum-computing/mckinsey-quantum-finance-600b/)
42. [S40] The Tweezer Array's Hidden Supply Chain: Who Really Wins If Neutral-Atom Quantum Computing Wins — postquantum.com — [https://postquantum.com/quantum-ecosystem/neutral-atom-quantum-ecosystem/](https://postquantum.com/quantum-ecosystem/neutral-atom-quantum-ecosystem/)
43. [S44] Origin Quantum Unveils Origin Wukong-180 Fourth-Generation Quantum Computer — quantumcomputingreport.com — [https://quantumcomputingreport.com/origin-quantum-unveils-origin-wukong-180-fourth-generation-quantum-computer/](https://quantumcomputingreport.com/origin-quantum-unveils-origin-wukong-180-fourth-generation-quantum-computer/)
44. [S53] S.3597 - 119th Congress (2025-2026): National Quantum Initiative Reauthorization Act of 2026 | Congress.gov | Library of Congress — congress.gov — [https://www.congress.gov/bill/119th-congress/senate-bill/3597](https://www.congress.gov/bill/119th-congress/senate-bill/3597)
45. [S42] Microsoft unveils Majorana 1, the world’s first quantum processor powered by topological qubits - Microsoft Azure Quantum Blog — azure.microsoft.com — [https://azure.microsoft.com/en-us/blog/quantum/2025/02/19/microsoft-unveils-majorana-1-the-worlds-first-quantum-processor-powered-by-topological-qubits/](https://azure.microsoft.com/en-us/blog/quantum/2025/02/19/microsoft-unveils-majorana-1-the-worlds-first-quantum-processor-powered-by-topological-qubits/)
46. [S5] Quantum Threat Timeline Report 2025 - Global Risk Institute — globalriskinstitute.org — [https://globalriskinstitute.org/publication/quantum-threat-timeline-report-2025b/](https://globalriskinstitute.org/publication/quantum-threat-timeline-report-2025b/)
47. [S27] Unlocking 99.99% Two-Qubit Gate Fidelities - IonQ — ionq.com — [https://www.ionq.com/blog/accelerating-towards-fault-tolerance-unlocking-99-99-two-qubit-gate](https://www.ionq.com/blog/accelerating-towards-fault-tolerance-unlocking-99-99-two-qubit-gate)
48. [S45] Quantinuum Launches Industry-First, Trapped-Ion 56-Qubit Quantum Computer, Breaking Key Benchmark Record — quantinuum.com — [https://www.quantinuum.com/press-releases/quantinuum-launches-industry-first-trapped-ion-56-qubit-quantum-computer-that-challenges-the-worlds-best-supercomputers](https://www.quantinuum.com/press-releases/quantinuum-launches-industry-first-trapped-ion-56-qubit-quantum-computer-that-challenges-the-worlds-best-supercomputers)
49. [S79] EuroHPC Opens €119M in Funding Calls for Quantum Technologies — thequantuminsider.com — [https://thequantuminsider.com/2026/08/24/eurohpc-119m-funding-calls-quantum-technologies/](https://thequantuminsider.com/2026/08/24/eurohpc-119m-funding-calls-quantum-technologies/)
50. [S117] Quantum Threat Timeline Report 2025: Record Predictions, But Can the Survey Keep Up? — postquantum.com — [https://postquantum.com/security-pqc/quantum-threat-timeline-report-2025/](https://postquantum.com/security-pqc/quantum-threat-timeline-report-2025/)
