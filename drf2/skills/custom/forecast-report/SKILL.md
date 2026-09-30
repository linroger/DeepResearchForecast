---
name: forecast-report
description: Use this skill in the DRF-2 pipeline to assemble the final deliverable — a three-part Bridgewater-style forecast brief. It encodes the calibration rubric (at least 10 independent binary forecasts with objective metric+threshold+date resolution criteria, contrarian framing mix, conviction spread with stdev above 0.12), the scenario spine, prediction-market anchoring with explained divergences, and the provenance discipline that separates research evidence from simulation roleplay.
allowed-tools:
  - tool_search
  - read_file
  - write_file
  - ls
  - grep
  - glob
  - web_search
  - web_fetch
  - kg_search
  - kg_causal_paths
  - kg_trace_cascade
  - kg_get_entities
  - sim_results
  - sim_interview_agents
  - prediction_market_search
---

# Forecast Report Skill

## 1. Mission & deliverable shape

Produce a **decision-grade forecast brief** whose headline is a table of independent, falsifiable, calibrated binary forecasts — the contract a Bridgewater-style reader grades you on. The report has exactly three parts, in this order:

- **Part 1 — Binary Forecasts**: the headline table of ≥10 independent yes/no forecasts (§2). First thing after the title.
- **Part 2 — Framework & Synthesis**: the analytical spine — how the drivers interact, the causal framework, the coalition map, why the probabilities are what they are (§4). Short paragraphs, `###` sub-headings at most.
- **Part 3 — Appendix: Detailed Analysis**: the full per-driver / per-actor chapters, evidence, and methodology (§5).

Inputs: the research report + actor dossier (evidence), the knowledge graph (`kg_*` — causal chains and edges to cite beside claims), the simulation outputs (`sim_results`, `sim_interview_agents` — signals, not evidence; see §6), and prediction-market snapshots (`prediction_market_search`, per the `prediction-markets` skill).

## 2. Part 1 — the binary forecast contract

At least **10 DISTINCT independent binary forecasts**. First **extract** every binary the research already stated (preserve its probability and resolution criteria verbatim where given); then **derive** additional ones from the drivers, indicators, and quantitative facts until the minimum is met. Never invent facts the evidence does not support.

Each forecast carries:

| Field | Rule |
|---|---|
| `id` | F1, F2, … |
| `statement` | ONE declarative sentence that resolves strictly yes/no, with the number and the date INSIDE the sentence. Model: "The US effective tariff rate on imports averages over 10% from 2026-2028." |
| `probability` | 0.02–0.98. **Independent per forecast — these do NOT sum to 1.** |
| `resolution_criteria` | The objective settle test: a named **METRIC + a NUMERIC threshold + a DATE/window + the SOURCE** that resolves it. All four, always. A criterion missing any of metric/number/date is not sharp and will be bounced. |
| `resolution_source` | The dataset/agency/publication that will settle it. |
| `theme` | A short lowercase tag naming the driving force this forecast belongs to (derive themes from the brief; they are not a fixed triple). |
| `horizon_year` | Resolution year, within 1–5 years of now. |
| `base_rate_anchor` | The reference-class base rate / outside view. |
| `adjustment_rationale` | Why this case differs from the base rate (anchor-and-adjust). Cite the market anchor here when one exists (§3). |
| `source` | Provenance of the probability: name the **simulation signal** that moved it (e.g. "world-state outcome shares", "coalition map") or `research-prior` when only research evidence informs it. Every probability is accountable to a named signal. |

### 2.1 Conviction & spread (size each probability by the evidence)

Each probability is **sized by the evidence**, one forecast at a time:

- Weigh the evidence, then move toward the side it supports, **as far as it decisively wins** — conflicting sources alone are not a reason to sit at 0.5 or at the base rate.
- Stay near 0.5 or the base rate **only** when the evidence is still balanced after weighing, or too thin to move you. When that happens, prefer a statement the evidence can discriminate (a sharper threshold, date or metric) over publishing a coin-flip.
- **Never manufacture extremity** to look decisive, and never shade a number toward a target range: if the evidence does not support the probability a statement needs, drop or rewrite the statement instead.

A table built this way usually looks healthy on its own: few calls clustered in 0.40–0.60, a spread with stdev ≥ 0.12, and at least 3 high-conviction calls (p ≥ 0.70 or p ≤ 0.30). These numbers describe a well-researched table; they are not targets to aim the probabilities at.

### 2.2 Contrarian framing (how to achieve spread honestly)

Frame roughly **40–50% of the statements so the evidence-supported probability is BELOW 0.5** — assert the counter-consensus outcome directly (e.g. "X exceeds Y by Z date" priced at 0.25). **Never** achieve this by negating another statement in the set (that manufactures fake spread and fake independence). One-directional framing is the classic failure: all probabilities land above 0.5 and the spread gate can never pass.

## 3. Prediction-market anchoring

Fetch related active markets (`prediction_market_search`; craft per the `prediction-markets` skill). Where a forecast overlaps a listed market:

- **Cite** the market's implied probability in `adjustment_rationale`.
- Add `market_anchor: {market_id, implied_yes_prob}`; omit the field entirely when no listed market applies. (The pipeline re-verifies the implied probability against its own snapshot and computes divergence deterministically — do not transcribe prices sloppily.)
- When your probability diverges from the market by **more than 10 percentage points, explain the divergence explicitly** — what the market is missing or mispricing (information edge, simulation signal, definitional mismatch).
- Markets are **calibration anchors, not ground truth**: never copy a price as your probability without your own reasoning; thin markets are noise.

## 4. Part 2 — Framework & Synthesis

One compact synthesis written from the binary-forecast skeleton plus the key points of the detailed chapters: the causal framework (cite `kg_causal_paths` chains), how the 3–6 drivers interact, the coalition/opposition map from the simulation, the scenario spine (§4.1), and what would change your mind (the dated indicators). It reads as the analytical bridge between the table (Part 1) and the evidence (Part 3) — no new facts appear here that Part 3 does not support.

### 4.1 The scenario spine

Alongside the independent binaries, maintain **2–5 mutually exclusive, collectively near-exhaustive scenarios** with numeric probabilities **summing to ~1.0**, each with its own falsifiable `resolution_criteria` (how an auditor decides, at horizon, whether this scenario occurred). Binaries and scenarios are different objects — never let the scenario probabilities masquerade as binary forecasts or vice versa.

## 5. Part 3 — Appendix: Detailed Analysis

The existing per-driver / per-actor / per-fault-line chapters, with full evidence: inline attribution (source + date) for every load-bearing claim, the quantitative table (unit + as-of + definition), contested claims shown with why sources differ, and the tiered source list. Follow the `deep-research` §12 output contract throughout.

## 6. Provenance discipline (research vs. simulation)

The report draws on two epistemically different inputs. **Never launder one as the other:**

- **Research evidence** (S1/S2 sources, the dossier, the KG's evidenced edges) supports factual claims and quotes. Any blockquote presented as a real/factual quote **must be verbatim from the research material** — a deterministic audit substring-matches every unlabeled blockquote against the research corpus and flags failures as fabrications.
- **Simulation output** (agent posts, interviews, world-state shares, coalition dynamics) is a **model-generated signal about plausible dynamics** — cite it as such, explicitly labeled ("in the simulation…", "sim-agent X argued…", 模拟/推演), and name it in a forecast's `source` field when it moved a probability. **Never** quote a sim agent as if a real person said it, never dress a graph-edge string up as a source, and never cite simulation roleplay as research evidence.
- Every probability is accountable: either a named simulation signal or `research-prior`. "Vibes" is not a provenance.

## 7. Language & style

- Report language follows the run's requested language; Part 1 field text follows the report language.
- Bridgewater register: direct, numerate, falsifiable; short paragraphs; no hedging filler ("only time will tell") — uncertainty is expressed in the numbers and the named drivers, not in mush.
- Idempotent structure: exactly one Part 1/2/3 skeleton; the binary table appears once, immediately after the title (plus an optional one-blockquote executive summary).
- **Stage artifacts**: when run as a pipeline stage, write BOTH `full_report.md` (the three-part brief) AND `forecast.json` — the structured mirror of Part 1 and §4.1 (`{"binary_forecasts": [...], "scenarios": [...]}` with the exact fields from §2). The driver's conviction/deliverable gates read `forecast.json` deterministically; a report without it fails the stage.

## 8. Quality gate (the deterministic checks your output must survive)

- [ ] ≥10 distinct binaries; every statement one sentence, yes/no-resolvable, number and date inside it?
- [ ] Every resolution_criteria carries metric + numeric threshold + date/window + resolving source?
- [ ] Every probability sized by how decisively its evidence wins — near 0.5 only when the evidence stays balanced or thin, no extremity manufactured to look decisive, no number shaded toward a range? Does the resulting table show healthy spread (stdev ≥ 0.12, ≥3 calls at ≥0.70 or ≤0.30, little 0.40–0.60 clustering) with 40–50% of statements framed below 0.5 without negation tricks?
- [ ] Every probability's `source` names a simulation signal or research-prior?
- [ ] Market overlaps cited; divergences > 10pp explained; `market_anchor` present only where a listed market applies?
- [ ] Scenarios (2–5) mutually exclusive, probabilities sum ~1.0, each with falsifiable criteria?
- [ ] Zero unlabeled non-verbatim blockquotes (the quote-provenance audit will catch them)?
- [ ] Three-part skeleton in order; Part 2 supported entirely by Part 3 evidence?

## 9. Failure modes

- ❌ Scenario probabilities that sum to 1 presented as the binary table (or binaries forced to sum to 1).
- ❌ All probabilities above 0.5 — one-directional framing that can never pass the spread gate.
- ❌ Manufacturing spread by negating existing statements.
- ❌ Shading a probability toward a target band, or manufacturing extremity to look decisive, when the evidence does not carry it.
- ❌ "Resolves by 2027" with no metric or threshold — an unsharp criterion an auditor cannot settle.
- ❌ Quoting a simulation agent as a real-world source; graph-edge strings dressed up as citations.
- ❌ Copying market prices as probabilities, or diverging > 10pp from a cited market silently.
- ❌ Probabilities with no provenance — neither a named sim signal nor research-prior.
- ❌ New facts appearing in Part 2 that Part 3's evidence does not carry.
