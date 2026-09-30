# Forecast-quality judge rubric (EXECPLAN2 I-7-7)

A rubric LLM-judge scores each forecast report on the five dimensions below, each
on an integer **0–5** scale (0 = absent/broken, 5 = excellent). The judge must
return strict JSON: `{"groundedness": int, "coverage": int, "calibration": int,
"contradiction": int, "citation_density": int, "notes": "..."}`.

Score at **temperature 0** and average over **k=3** passes to damp variance.
Assertions are made on coarse per-dimension thresholds (± tolerance) vs a
committed baseline — never on exact scores — because LLM-judge scores are noisy.

---

## 1. groundedness
Are the report's claims traceable to concrete evidence — graph facts, named
actors, or cited sources — rather than free-floating assertion? Attribution
phrasing without a resolvable [S#] marker or market snapshot is not grounding.
- **0** Pure assertion; no anchoring to entities, data, or sources.
- **2** Some named actors/numbers, but most claims are unsupported.
- **4** Most material claims anchored to a specific actor, datum, or source.
- **5** Nearly every substantive claim is traceable to a concrete, checkable anchor.

## 2. coverage
Does the forecast cover the scenario space — multiple mutually-exclusive
scenarios with drivers, plus the key uncertainties — rather than a single
narrative?
- **0** One narrative; no alternative scenarios or drivers.
- **2** 2 scenarios but thin drivers / missing a status-quo or tail case.
- **4** 3+ mutually-exclusive scenarios with drivers and key uncertainties.
- **5** Exhaustive, well-separated scenarios incl. tail risk + explicit driver map.

## 3. calibration
Is uncertainty expressed responsibly — explicit probabilities/ranges that are
internally consistent (sum ≈ 1 across mutually-exclusive scenarios), with
base-rate awareness, and confidence matched to evidence strength?
- **0** False precision or no uncertainty language at all.
- **2** Probabilities present but inconsistent (don't sum) or overconfident.
- **4** Consistent probabilities/ranges with some base-rate / confidence rationale.
- **5** Well-calibrated: consistent probabilities, base rates, evidence-matched confidence.

## 4. contradiction
Is the report internally consistent — scenarios mutually exclusive, no claim
contradicting another, probabilities not double-counting?
- **0** Self-contradictory; overlapping/incoherent scenarios.
- **2** Minor inconsistencies or overlapping scenario boundaries.
- **4** Logically consistent; scenarios cleanly separated.
- **5** Airtight: explicitly reconciles tensions and contested claims.

## 5. citation_density
How densely are quantitative/quoted claims tied to citation markers
(`[S1]`, `【S3】`)? Anchor to the objective citation-coverage
signal supplied with the report, then adjust for quote attribution quality.
- **0** No citation markers anywhere; numbers appear unsourced.
- **2** Sparse markers; <30% of quantitative claims carry one.
- **4** Majority of quantitative claims carry a citation/quote attribution.
- **5** Near-complete: quantitative claims and key quotes are consistently sourced.
