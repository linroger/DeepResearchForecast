# Probability toolkit

Every number below is illustrative arithmetic, not a fact. Show the arithmetic in notes; the result of a calculation is REPORTED, never VERIFIED.

## 1. Hazards and deadlines

- **Constant annual hazard p:** P(by T years) = 1 − (1 − p)^T. With p = 0.10 and T = 3: 1 − 0.9³ = 27.1%.
- **From a count:** k events in N years gives the rate λ = k/N, and P(within T) = 1 − e^(−λT). Example: 12 starts in 80 years → λ = 0.15 → 1 − e^(−0.30) = 25.9% within two years.
- **Rescaling periods:**
  - monthly m → annual 1 − (1 − m)^12, so m = 1% → 11.4%;
  - annual p → monthly 1 − (1 − p)^(1/12), so p = 20% → 1.84%.
- **Discrete decision points** (FOMC meetings, court sittings, summits): P(at least one yes) = 1 − Π(1 − p_i). Four meetings at 15% each → 1 − 0.85⁴ = 47.8%. When one decision changes the next (a cut lowers the chance of another), chain the conditionals instead.
- **The shape of the hazard decides the method:**
  - Decreasing (wars, leader tenure, frozen disputes): use the rate for cases of the same age, not the class average.
  - Rising into a deadline (budgets, debt limits, session ends, expiries): probability mass piles up at the deadline. Split the window into ordinary time and the deadline window.
  - One-shot (an election, a ruling day): P is the single-event probability. There is no hazard to compound.
- **"By" vs "in":** "by YEAR" accumulates over every year up to the deadline. "In YEAR" uses only that year's chance, p. If "in YEAR" means the *first* occurrence, it is (1 − p)^(years before) · p.

## 2. Time decay as the deadline nears

- With no event so far and a constant hazard, re-price on the remaining time: P = 1 − (1 − p)^(years left). A 3-year window at p = 0.10:

| Point in the window | P(by deadline) |
|---|---|
| Start | 27.1% |
| After one quiet year | 19.0% |
| With one year left | 10.0% |
| With three months left | 2.6% |

- A quiet stretch moves the forecast only through the shrinking window. Do not also count "nothing happened" as extra evidence for the status quo.
- **Exception:** hazards that rise into a deadline must not decay this way. Hold the deadline-window share apart and decay only the ordinary-time share.

## 3. Status-quo prior

- For "will X change by date", the default is continuation: P(change) is the horizon hazard of comparable change in the class. Laws, regimes, leaders, alliances and pegs usually have high continuation rates; read the rate from the class, do not assume it.
- With a forcing event inside the horizon (an expiry, a sunset clause, a scheduled vote), the status quo is *what happens if nobody acts*. A tariff exemption that expires by default makes "lapse" the status quo.
- Scenario weights: the continuation scenario gets the largest weight unless a forcing event or the class says otherwise. Write the reason in its thesis.

## 4. Small samples

- **Laplace rule, (k+1)/(n+2):**

| Count k/n | Laplace estimate |
|---|---|
| 0/5 | 1/7 = 14% |
| 3/11 | 4/13 = 31% |
| 5/5 | 6/7 = 86% |
| 18/20 | 19/22 = 86% |

  Laplace keeps a tiny class away from 0 and 100.
- **Rule of three:** with 0 events in n, the 95% upper bound is about 3/n (0 of 30 → at most 10%).
- **Rough 95% spread near the middle:** ±1/√n. For n = 11 that is ±30 points, so a single small class cannot pin a probability to within 10 points.
- **Combining classes:**
  - Weight each class by causal similarity and by n. Report the blend and the range.
  - Example: A = 3/11 (31%) and B = 9/20 (10/22 = 45%), weighted 0.6/0.4 → 37%, with a range of 31–45.
  - The spread between classes is real uncertainty. Keep every rival scenario's weight above the floor rather than collapsing onto one class.

## 5. AND-chains and OR-routes

- **AND:** P(A∧B∧C) = P(A) · P(B|A) · P(C|A,B).
  - Example ("tariff regime still in force at end-2027"): court allows 0.5 × Congress does not override, given allowed 0.9 × administration keeps it, given both 0.8 → 36%.
  - Use conditional probabilities, not marginals. Stages usually move together (a strong position wins in court and is kept), so multiplying marginals understates the joint.
  - Long chains shrink fast: five stages at 0.8 give 33%. Every stage must be truly necessary. Leaving out a necessary stage overstates the result.
  - Parallel prerequisites with a deadline: the slowest one governs (take the maximum duration, not the sum). Negative slack against the deadline means the path is infeasible as specified.
- **OR:** P(A∨B) = P(A) + P(B) − P(A∧B).
  - Mutually exclusive routes add. Example: the war ends by agreement 0.15, by collapse 0.05 or by a frozen ceasefire 0.10 → 30%.
  - Independent routes: 1 − (1 − a)(1 − b), so 0.2 and 0.3 give 44%, not 50%.
- **Double counting.** A ceasefire that later becomes an agreement can be counted in both routes. Define each route by the first terminal state reached.

## 6. Scenario/binary consistency

- **Total probability:** P(E) = Σ P(s) · P(E|s). Weights 50/30/20 with P(E|s) = 0.9/0.4/0.05 → 0.45 + 0.12 + 0.01 = 58%.
- **Derivable binaries.** When the scenario definitions settle E (every P(E|s) is 0 or 1), P(E) is the sum of the yes-scenario weights. The forecast stage records these as yes_scenarios. Scenarios split on the anchor metric's ranges make the key binaries derivable.
- **Coherence across related questions:**
  - Monotone in the deadline: P(by 2027) ≤ P(by 2028).
  - Monotone in the threshold: P(CPI < 2.0) ≤ P(CPI < 2.5).
  - Complements: P(E) + P(not E) = 1 under the same resolution.
  - Joints and unions: P(A∧B) ≤ min(P(A), P(B)) and P(A∨B) ≥ max(P(A), P(B)).
  - Joint plausibility: a combination the actors' reaction function rules out (deep cuts while inflation runs far above target, with no recession) cannot get more weight than that function allows.
- **Integer weights.** Round with the largest-remainder method so they sum to 100. A scenario under 5 is merged unless it is a signposted tail.

## 7. Inside-view adjustment and updating without double-counting

- **Bridge:** anchor (class, k/n, rate) → adjustment 1 (direction, size, mechanism, evidence) → adjustment 2 → … → result. Each adjustment states why the class does not already contain it.
- **Odds form:** posterior odds = prior odds × LR, where LR is the likelihood ratio, P(evidence | E) ÷ P(evidence | not E).
  - Prior 30% → odds 0.43. An LR of 2 gives odds 0.86, i.e. 46%.
  - A second, independent LR of 1.5 gives odds 1.29, i.e. 56%.
- **Sizing an LR** (judgment, not measurement):

| Evidence | Likelihood ratio |
|---|---|
| Suggestive | 1.2–1.5 |
| Strong and mechanism-specific | 2–3 |
| Near-decisive act (a signed law, an official decision) | above 5 |

  An LR above 3 needs S1 evidence. Disconfirming evidence gets an LR below 1 by the same scale.
- **Independence:**
  - Five articles from one origin are one LR, and so are an official statement and its repetitions.
  - A driver already in the class adds nothing. If the class is "easing cycles that began with rising unemployment", rising unemployment is not an extra LR; with an unconditional class, it is.
- **Class changes are not updates.** Switching classes after seeing the evidence is logged as a class change, with both rates shown.
- **Base-rate neglect test.** If the final number is far from every class rate, the bridge must show the adjustments that carried it there.

## 8. Distance to threshold in volatility units

- z = (threshold − current) / (σ₁ · √h). Here σ₁ is the standard deviation of one-period changes in the stored series and h is the number of periods to the anchor. This is a random-walk approximation: mean reversion narrows the spread and a trend shifts the centre.
- **Normal tail, P(beyond z):**

| z | P(beyond z) |
|---|---|
| 0.5 | 31% |
| 1.0 | 16% |
| 1.5 | 6.7% |
| 2.0 | 2.3% |
| 2.5 | 0.6% |

- **Ever-touch vs end-state.** For a driftless random walk, P(touches before T) ≈ 2 × P(beyond at T) (the reflection principle). An end-state probability of 16% therefore means a touch probability of about 32%. Drift toward the threshold raises both; mean reversion around today's level lowers the end-state probability more than the touch probability.
- **Example:** current 3.0, threshold 2.5, σ₁ = 0.2 a month, h = 9 → σ_h = 0.6 and z = 0.83. End-state below 2.5 ≈ 20%; touching 2.5 at some point ≈ 40%.
- The forecast stage computes the empirical version of the end-state probability from stored history. Use z to sanity-check it and to explain the gap between the touch and the end-state questions.

## 9. Calibration hygiene

- **Be granular.** Write 37% when the bridge supports it; do not round to tens or default to 50% for "unsure".
- **Avoid extremes.** The forecast stage clamps binaries to 2–98%. Never write 0 or 100 for an open question. Anything below 5% or above 95% needs a decisive S1 fact or a long class with no exceptions.
- **Conviction.** Go away from 40–60% only as far as the class and the bridge carry you. Never move to look decisive.
- **Extremizing.** Pushing an average of forecasts outward (e.g. raising its odds to a power above 1) helps only when the averaged forecasters hold independent information. Never extremize a single model, a single team, or simulation agents.
- **Simulation and persona agents** share one model and one evidence base, so their agreement is not independent confirmation. Treat their outputs as scenario mechanics: who moves first, which coalition forms. They are not extra votes.
- **Blending a market with a base rate.** Average in log-odds, not in probabilities: 20% and 40% → logits −1.39 and −0.41 → mean −0.90 → 29%. When the two share their information source, do not count both at full weight.
