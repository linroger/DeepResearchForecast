# Persistence base rates and share dynamics

Load this to compute how often leaders hold, to model how share moves on the way to the target year, and to build rank probabilities that are coherent and agree with the scenario frame. Every rate here is something the agent computes from fetched tables, tags REPORTED, and cites to its table.

## 1. Classify the market first

The class picks the reference class and the plan-time prior.

- **Concentration** (from the baseline):
  - CR1 and CR3;
  - HHI = Σ (share in %)² on a 0–10,000 scale;
  - relative share = #1 ÷ #2.
  US merger-guideline bands are useful vocabulary: the 2023 DOJ/FTC guidelines call HHI above 1,800 highly concentrated (verify the current version).
- **Clock speed**: product-generation length, and share volatility = the mean absolute yearly change in each top-3 contender's share, in pp.
- **Transition exposure**: is a platform, architecture or generation change due before the target year? Examples: a new memory generation, a node class, a compute paradigm, a regulatory regime.
- **Maturity**: a field is nascent when no leader has held #1 for 3+ years or the metric itself is new. Nascent fields use milestone-based classes.

Plan-time priors by class are procedural defaults for the fixed scenario weights. The rate computed in §2 is reported beside those weights and tests them; it never rewrites them within the run.

| Class | Incumbent-holds weight | Field |
|---|---|---|
| Concentrated, scale-economy, slow clock, no transition in the window | Majority | Small |
| Concentrated, but a transition falls in the window or relative share < 1.2 | Near even with the challengers | Small |
| Fragmented or fast clock | Minority | Material |
| Nascent | No premium beyond the evidence | ≥ 10 |

## 2. Computing a persistence base rate

1. **Get one long table.** Rank or share, annual, on a consistent perimeter, ideally 10+ years. Sources:
   - tracker or analyst annual top-10 lists (Gartner, IDC, TrendForce, Omdia, Synergy, SNE Research, CPCA/CAAM);
   - company histories that cite them;
   - industry-association yearbooks (CSIA, CAAM, SIA/WSTS for totals);
   - academic studies of share stability.
2. **Score each window.** For each start year t with t + h inside the table (h = years to the target), record:
   - held: the #1 at t is still #1 at t + h;
   - the rank at t of the eventual #1;
   - whether the eventual #1 was outside the top k at t.
3. **Rate.** P_hold(h) = held windows ÷ all windows. Overlapping windows are not independent, so report the number of distinct leadership changes and use the count of non-overlapping windows as the effective n.
4. **Small n.** Report the raw value and a shrunk value from the non-overlapping windows only: (x_m + 1) ÷ (m + 2), where x_m of the m windows held. Pool 3–5 causally similar markets: same concentration band, clock speed and capital intensity. Similarity means the same causes, not the same industry label.
5. **Condition when n allows:**
   - by starting relative share (#1 ÷ #2 below vs above about 1.5);
   - by whether a transition fell inside the window.
   Leadership changes cluster in transition windows. For revenue metrics they also cluster at price-cycle extremes.
6. **Hazard form.** When only the number of changes over Y years is known: annual hazard λ ≈ changes ÷ Y, so P_hold(h) ≈ (1 − λ)^h. This assumes a constant hazard. Raise λ for windows that contain a known transition.
7. **Field rate** = the share of windows where the eventual #1 was outside the top k at t. It sets the floor for the field probability.
8. **Write it up** as: "Computed from <table, edition, years>; windows n, #1 held in x, P_hold(h) = x/n; non-overlapping m, held x_m, shrunk (x_m+1)/(m+2); REPORTED."

**Survivorship.** Include leaders that exited, categories that disappeared and firms that were acquired. A table that starts from today's leaders overstates persistence.

## 3. Seed histories for reference classes (verify before use)

These are widely documented leadership histories. Use them to seed a class or sanity-check a computed rate. Verify each against the named table class first; none is a claim about today.

| History | Source class | Pattern |
|---|---|---|
| **DRAM revenue.** One firm (Samsung) held #1 for long stretches from the early 1990s. The field consolidated through downturn shake-outs: Qimonda's 2009 insolvency; Elpida's 2012 bankruptcy and later acquisition by Micron. | Company and tracker histories | Concentrated, capital-intensive, cyclical. Persistence is high and exits cluster at troughs. |
| **Total semiconductor revenue.** The #1 flipped between Intel and Samsung more than once with the memory price cycle. | Gartner and IC Insights annual rankings | A price-driven flip: reversible, not structural. |
| **Pure-play foundry.** TSMC has led since the segment formed. | Company and tracker histories | Scale and process lead compound. |
| **Mobile phones.** The unit #1 passed from Nokia to Samsung in the early 2010s, during the smartphone platform shift. | IDC, Gartner, Strategy Analytics | A platform transition overturns a dominant leader within a few years. |
| **Web browsers.** Usage #1 passed from Internet Explorer to Chrome in the early 2010s. | StatCounter | Distribution plus a product shift beats a bundled incumbent. |
| **PCs.** The unit #1 changed several times from the 1980s on. | IDC, Gartner | Modular hardware with low switching costs shows low persistence. |
| **Web search.** One leader (Google) since the early 2000s. | StatCounter | Data scale and default placement sustain a lead. Remedies that target defaults are the structural test. |

Use these as anchors for how a class behaves, not as the class itself. The computed table for the question's own market comes first.

## 4. Share-shift mechanisms and what to observe

Each mechanism has an observable that leads the share change.

- **Capacity and capex share** (commodity hardware). Output share follows qualified capacity, which follows cash capex after the build lead time.
  - Observe cash capex from cash-flow statements (not guidance), tool orders and fab milestones.
  - Rule: a contender whose capex share runs above its output share for several years is gaining capacity share. Take the lead time from the company's own fab timeline.
- **Technology transitions.** Each generation re-runs qualification and resets share.
  - Observe sampling → qualification → volume at the largest buyer. The first to qualified volume wins incremental share.
  - Rule: count the transitions between now and the target year. Each is a draw for the challenger.
- **Cost position.** The lowest-cost producer gains share in downturns.
  - Observe the gross-margin spread at the trough, and who cuts output first.
- **Switching costs and lock-in.** Sources include egress fees and data gravity (cloud), software ecosystems (accelerators), multi-year commitments (remaining performance obligations) and certification (automotive, aerospace).
  - Observe net revenue retention, porting announcements, and multi-sourcing by large buyers.
  - Installed-base share moves slowly; share of new workloads moves fast.
- **Network effects**: direct (users), indirect (developers, complements) or data.
  - Test whether users multi-home and whether liquidity is local or global. A large dataset alone is not proof.
- **Distribution and bundling**: defaults, preinstallation, enterprise bundles.
  - Observe default-placement deals and bundling remedies.
- **Regulation and geopolitics.**
  - Export controls cut access to tools, chips or markets; entity listings cut customers; subsidies lower an entrant's cost of capital; localization mandates split the market.
  - Observe rule texts (Federal Register, MOFCOM announcements), licence decisions and procurement lists.
  - A global ranking can hide two regional rankings.
- **Capital-cycle shake-outs.** Downturns remove the weakest balance sheets by exit or merger.
  - Observe net debt to EBITDA and cash runway. For cash-burning labs, compare funding rounds with compute commitments.
  - Market gauges: credit spreads (fred:BAMLH0A0HYM2) and long rates (fred:DGS10).
- **M&A and consolidation.** Combined share jumps at closing.
  - Approval chokepoints: SAMR (deals over China revenue thresholds), EC, UK CMA, US FTC/DOJ, CFIUS for inbound investment, KFTC, JFTC.
  - Treat a pending deal as a staged event with approval odds (policy-and-trade-forecasting), and model both outcomes.
- **New entrants:**
  - state-backed capacity, which is not return-constrained but is tool- and talent-constrained;
  - customer insourcing, as when hyperscalers' custom chips shift share away from merchant vendors;
  - open-weight models, which compress closed-model pricing.
  - Observe subsidy disclosures, insourced-volume statements and price cuts.

**Incremental-share identity:**

s_T = (S_0·s_0 + ΔS·s_Δ) ÷ (S_0 + ΔS)

- S_0 is the base-year market and s_0 the contender's base-year share.
- ΔS is market growth to T, taken from industry-forecasting.
- s_Δ is the contender's share of that growth.

The identity assumes the base-year business is retained; subtract churn separately. Share moves toward s_Δ only as fast as ΔS ÷ S_0 grows: in a market that doubles (ΔS = S_0), the end share sits halfway between s_0 and s_Δ. In slow-growth markets, share is decided by taking customers, not by winning new demand.

## 5. Catch-up arithmetic

- **Share gap.** G = s_lead − s_ch, in pp. If the challenger gains a pp a year and the leader loses b, years to cross = G ÷ (a + b).
  - Compare a + b with the largest sustained three-year swing in the reference class.
  - If the required rate exceeds the observed maximum, the probability is low unless a transition or shock lies on the path.
- **Revenue crossing.** T = ln(R_lead ÷ R_ch) ÷ ln((1 + g_ch) ÷ (1 + g_lead)).
  - Halve the growth differential and recompute; T roughly doubles.
  - If T at half the differential exceeds the horizon, call the crossing fragile.
- **Market-cap crossing** (driftless approximation; pair with financial-markets-forecasting).
  - Let x = ln(M_lead ÷ M_ch) and σ_r = √(σ_l² + σ_c² − 2ρσ_lσ_c), from annualized volatilities and their correlation.
  - P(challenger ahead at T) ≈ Φ(−x ÷ (σ_r√T)).
  - P(ahead at any time before T) ≈ 2 × that, capped at 1 (the reflection principle).
  - Point-in-time and "ever" are different questions.
- **Capacity crossing.** Compare staged capacity pipelines (announced → under construction → tool move-in → qualified → volume) with slippage specific to each stage. Only qualified capacity counts toward share.

## 6. Coherent rank probabilities

**Build the weights at plan time.** The frame is fixed from scout snippets, so steps 1–3 use the §1 class prior and hard scout facts; the rate computed later (§2) tests the weights in the report but never changes them.
1. Start P(incumbent #1) at the class's P_hold(h), conditioned on relative share and the number of transitions.
2. Give the field at least the class field rate.
3. Split the rest among the named challengers by evidence: catch-up feasibility (§5), the capability cells and qualification status. Never split equally by default. Prominence is not evidence.
4. Name each scenario's #1 (or "field") in its thesis, so the ranking derives from the frame:
   - P(X #1) = the sum of the weights of the scenarios whose thesis names X; with leader-defined scenarios it equals the weights;
   - split a grouped scenario (the field) only on cited evidence; a frame that names no leaders (dominant / duopoly / fragmented) gets evidence tiers, not P(#1);
   - P(X in top k), only when the question asks: the sum of the weights of the scenarios whose thesis places X in the top k;
   - writers quote the derived values and never re-estimate the weights.

**Coherence checks:**
- Σ_X P(X #1) = 100, field included.
- For every X, P(X in top k) ≥ P(X #1); and Σ_X P(X in top k) = k × 100.
- P(X above Y) + P(Y above X) = 100.
- P(X #1) ≤ P(X is still independent and reporting at T).
- No 0 and no 100. Longer horizons sit closer to the base rate.

**Tiers** are reporting bands chosen by convention:

| Tier | P(#1) |
|---|---|
| Favourite | ≥ 50 |
| Contender | 15–49 |
| Long shot | 3–14 |
| Field | below 3 each, grouped |

**Mini-example** (the numbers are illustrative only). The scenario weights are 55 (incumbent holds), 30 (challenger A takes #1) and 15 (field or break). The ranking quotes P(#1): incumbent 55, A 30, field 15. Cited evidence on challenger B's qualification splits the field: B 8, all others 7. Top-3 probabilities would need theses that name each scenario's top three; without them, report tiers only.

## 7. Kill criteria, signposts and credibility

- **Challenger paths.** For each, name the observable that must appear by a date for the path to stay alive:
  - qualification at the largest buyer by a named quarter;
  - share of incremental demand at or above the required rate for two consecutive quarters;
  - guided capex turned into cash capex;
  - an export licence granted.
- **Incumbent break signals:**
  - qualification lost at a pivotal buyer;
  - a generation slip of two quarters or more;
  - a forced remedy or divestiture.
- **Each criterion** carries a metric, threshold, date and source, and says which scenario weight it would move, and in which direction, at the next update.
- **Stated vs revealed.** For each contender, compare guidance with cash outcomes over the last 3–5 years: capex guided vs spent; launch dates promised vs shipped; capacity announced vs qualified. The hit rate is that actor's credibility prior in the simulation.
- **Reaction functions.** Record how each contender responded to past downturns, price cuts or rival breakthroughs:
  - cut output or held it;
  - matched prices or ceded share;
  - raised capex or paused.
  Past moves in comparable cycles are the behavioural base rate for the simulated actor.
