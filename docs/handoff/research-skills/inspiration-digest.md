# Inspiration digest — newskills/ (Explore agent, 2026-10-16)

Critical digest of the user's inspiration skills (industry-research ×3, industry-forecasting ×2, skill-format docs). Paths are relative to `newskills/`. This is a design input, not a skill.

I've read all four skills (both full and compact versions of each), the five format docs, and the evidence and eval files. Paths below are relative to `<repo>/newskills/`. Short names: **IR** = `industry-research-skill/`, **IRc** = `industry-research/` (byte-identical to `industry-research-codex/` apart from .DS_Store), **IF** = `industry-forecasting-skill/`, **IFc** = `industry-forecasting/`.

**Bottom line:** the research skills are strong on physical and economic sanity checks (capacity, inventory, profit pools). The forecasting skills are strong on how a question is defined and how uncertainty is labelled. Both are built for long industry outlooks written for human consultants. They have almost nothing on macro conditions, policy processes, actors, prediction markets or Tetlock-style binary-question practice, which is what your pipeline mostly needs.

---

## 1A. Industry research: the most valuable checks

1. **Four judgments kept separate.** Structural attractiveness, cycle position, segment advantage, and attractiveness at the available price. "One does not establish another" (IR `SKILL.md` Mandate).
2. **Capacity staging.** Announced → financed → under construction → ramping → qualified → productive. Use a dated capacity bridge: start + additions + productivity − retirements. Apply yield only once (IR `references/cycles-and-drivers.md`, "Trace the capital response"). IF `models-and-economics.md` adds permitted and commissioned stages.
3. **Stock-flow check.** Shipments = final consumption + change in channel inventory. Inventory that is falling but still too high is different from normal inventory starting to rise (IR `cycles-and-drivers.md`). IRc `worked-example.md` shows end demand up 8% while shipments fall 8.2%.
4. **Several cycle clocks.** End-demand, inventory, capacity, financing, technology/replacement, and seasonal/policy pull-forward, each with its "common misreading". Name the phase only from several indicators plus the counter-evidence, and allow "indeterminate" (IR `cycles-and-drivers.md`, "Diagnose and normalize").
5. **Orders-to-margins chain and backlog quality.** Orders → production → shipments → sell-through → inventory → pricing → margins. Check backlog for cancellations, deposits and double-ordering (IRc `SKILL.md` §5; IR `cycles-and-drivers.md`).
6. **Reconciliation order for conflicting estimates.** Check in order: perimeter, geography, period, customer vs producer prices, taxes, gross/net, shipments vs consumption, stock vs flow, channel layers, currency, real/nominal, coverage, revisions, method. Do not average estimates built on different concepts (IR `research-and-evidence.md`, "Reconciliation procedure").
7. **Independence groups.** "Several articles repeating one estimate count as one evidence family" (IR `SKILL.md` §3). Record an independence group per source (`research-and-evidence.md`).
8. **Minimum provenance.** Record definition, observation period vs publication date vs retrieval date, nominal/real, and actual/estimate/forecast. "Unknown is not zero", and a crawl timestamp is not a publication date (IR `research-and-evidence.md`).
9. **Hypothesis ledger with a discriminator field.** For each claim, record the alternative explanation and the observation that would tell them apart. Example: sell-through separates destocking from weak demand (IRc `references/evidence-method.md`).
10. **Triangulation.** Check demand/customer, supply/competitor and outcome evidence against each other (IR `research-and-evidence.md`).
11. **Revenue pool vs operating-profit pool vs economic profit.** Never sum revenues across value-chain stages. Ask "which interface or scarce asset captures value now, what could make it abundant" (IR `competition-and-value-chain.md`; IRc `market-economics.md`).
12. **Moat claims must be testable.** Mechanism → observable behaviour → durability → erosion trigger (IR `SKILL.md` §4E).
13. **Growth decomposition.** (1+g_R) = (1+g_Q)(1+g_P), with volume/price/interaction contributions shown separately. In the example, revenue rises 8% while EBITDA falls 40% (IR `quantitative-methods.md`).
14. **Macro effects traced through channels, not correlations.** Rates affect affordability, working-capital funding, hurdle rates, refinancing and valuation. FX can move results in opposite directions. Check whether pass-through is contractual, delayed or partial (IR `cycles-and-drivers.md`, "Translate macro variables").
15. **Red-team fallacy table and official-data cautions.** Examples: "Rising shipments therefore stronger demand", "Backlog therefore certain revenue", "More sources therefore more certainty" (IR `quality-and-red-team.md`). The Fed's G.17 capacity measures sustainable output, not nameplate. The OECD CLI signals turning points relative to trend, not growth rates (IRc `cycles-scenarios.md`). Use ALFRED vintages for any as-of work (IR `methodology-sources.md` M17–M18). Policy status should be one of enacted / proposed / implemented / litigated / expired (IR `sector-adapters.md`).

## 1B. Industry forecasting: the most valuable checks

1. **The question is a contract.** Fix the unit and denominator, nominal/real, annual average vs year-end stock vs annual or cumulative flow, gross/net, and the resolution source, vintage and revision rule (IF `forecast-design.md` §1).
2. **"By YEAR" defaults.** December 31 of that year: flows are calendar-year, stocks are year-end. Distinguish "ever crossed", "still true at year-end", "sustained for a period" and "announced vs operational". A current-year target needs a nowcast; a past target is a retrospective (IF `SKILL.md`, "lock the forecast contract"; `forecast-design.md`).
3. **Partial-year traps.** Nine months of data do not make a full-year actual. Don't annualize run-rates. Capacity that starts in December does not give a full year of nameplate output (IF `research-handoff.md`; eval case `full-year-vs-terminal-run-rate` in `evals/cases.json`).
4. **Output-type taxonomy.** Forecast, conditional projection, exploratory scenario, normative target/backcast, sensitivity, scenario envelope, predictive interval, confidence assessment. Each row says what the type does not establish (IFc `uncertainty-scenarios.md` table). The IEA says its own scenarios are not forecasts (IF `methodology-sources.md` F12). Normative or stress cases never go into a probability-weighted expected value.
5. **Outside view first.** Choose reference classes by causal similarity (adoption cost, complements, asset life, regulation, starting penetration). Include failures, stalls and still-unresolved cases. Bridge from the anchor to the inside view without counting a favourable driver twice (IF `forecast-design.md` §4).
6. **A simple benchmark is mandatory.** No-change, seasonal naive, drift, or constant penetration (IF `SKILL.md` §3). Eval F2 in `evidence/industry-forecasting/eval-quantitative.md` chooses the benchmark over a model that fit history better but forecast worse.
7. **Adoption chain.** Technical readiness → economic competitiveness → qualification/regulatory acceptance → distribution → paid usage → retention. Fit an S-curve only with a defensible denominator; early data cannot pin down both the ceiling and the inflection point (IF `SKILL.md` §4; `models-and-economics.md`).
8. **Stock-flow and cohorts.** Installed share is not sales share, and replacement is not expansion. Say explicitly whether unmet demand is lost or becomes backlog (IF `models-and-economics.md`). Experience curves are tied to cumulative output with a cost floor, and must not be double-counted with a time trend.
9. **Correlated capacity pipelines.** Use stage-conditioned base rates. Summing probability-weighted capacity "does not describe a possible joint physical world" when projects share permits or financing (IF `models-and-economics.md`).
10. **Milestone backcasting.** Forward and backward pass to get earliest start, latest start and slack. Parallel prerequisites take the maximum, not the sum. Negative slack means a contradiction. Treat AND routes and OR routes differently, and use P(A∧B) = P(A)·P(B|A) (IF `target-year-playbook.md`, "Deadline reasoning"). With 3–6 nodes an agent can do this by hand.
11. **Horizon ladder.** 0–2 years: committed supply, orders, inventory, financing. 2–5 years: cohorts, construction, competitive response. Beyond 5: diffusion, cost and institutions. Never extrapolate a timed cycle ten years out (IF `forecast-design.md` §3).
12. **Quantile discipline.** Use the non-exceedance convention (energy reserves often use exceedance). P10–P90 is a central 80% interval. Don't sum marginal P90s. Mix scenario CDFs rather than averaging their quantiles. Probabilities need a mutually exclusive, exhaustive partition (IF `uncertainty-and-scenarios.md`; `SKILL.md` §7; worked through in `evidence/industry-forecasting/eval-uncertainty.md` F4).
13. **Updating without double-counting.** Don't count "a management reiteration and five articles repeating it as six observations". Record old p, new p, the evidence, the mechanism and the competing explanation. No invented likelihoods (IF `uncertainty-and-scenarios.md`).
14. **Signposts.** Record current reading and date, source and release lag, expected window, economic threshold, which forecast it changes, and false-signal risk. Watch "qualified output (not an announcement), deployed paying customers (not pilots)" (IF `validation-and-updating.md`).
15. **Funding, path dependence and agent independence.** An unfunded build-out is a conditional case (IF `SKILL.md` §8), and the target year can look fine while participants fail on the way (IF `decision-lenses.md`, "Path-dependent outcomes"). Label LLM hindcasts non-blind. Persona agents are not independent experts (IF `SKILL.md` §8), which matters directly for your social simulation stage.

## 2. Sector adapters

Sources: IR `references/sector-adapters.md` (15 rows) and IF `references/sector-adapters.md` (13 rows).

| Sector | Decisive metrics | Failure modes flagged |
|---|---|---|
| Semis / hardware | Units × content per device, ASP/mix, qualified capacity, yield, lead times, inventory, customer capex, design wins | Treating fabless/foundry/equipment as one model; counting announced fabs as supply; extrapolating scarcity margins |
| Commodities / mining / energy / materials | Output × realized price, grade, depletion, cash vs full-cycle cost curve, sustaining capex, hedges, royalties | Spot ≠ realized price; peak earnings treated as normal; ignoring that high prices induce substitution and new supply; marginal vs incentive price |
| SaaS | ARR bridge, gross/net retention, cohorts, acquisition payback, hosting cost | Bookings or services counted as ARR; blended cohorts |
| AI software / inference | Paid production use, price per task, inference + human-review cost, reliability, customer ROI | Demos or pilots treated as demand; labor savings treated as revenue; price compression |
| Robotics / automation (IF only) | Task-eligible demand, installed cohorts, deployed hours, system total cost | Demo vs reliable deployment; integration and safety |
| Platforms / ads | Transacting users, take rate, liquidity, multi-homing, ad load | GMV called revenue; aggregate users used to prove local network effects |
| Consumer / retail | Traffic × conversion × basket, same-store sales, markdowns, leases | Sell-in treated as end demand; nominal vs real |
| Industrials / capital goods | Backlog conversion, installed base, aftermarket share, project margins | Backlog assumed uncancellable; working-capital swings |
| Business services | Labor availability, wage-price spread, route density | Roll-up illusion |
| Banks | Earning assets, deposit beta, credit losses, capital, ROE vs cost of equity | Applying EV/EBITDA; extrapolating low loss rates |
| Insurers | Combined ratio, reserve development, catastrophe exposure, investment income | Premium growth ≠ profitable underwriting |
| Asset managers | AUM bridge (net flows vs market move), fee mix | Market gains called organic flows |
| Healthcare / biopharma | Eligible patients × diagnosis/access × uptake × net price; stage-conditioned approval odds | Clinical success, approval, reimbursement and uptake treated as one event; list price used as revenue |
| Power / data centers | MW vs MWh, peak vs average, interconnection, regulated/contracted/merchant split | Nameplate treated as sellable output; build capex counted as recurring revenue |
| Real estate | Occupancy × net rent, same-property NOI, permits → starts → deliveries, cap rates | FFO treated as cash; appraisal marks treated as transaction prices |
| Transport / logistics | Capacity × utilization × yield, fleet orderbook and retirements | Scarcity freight rates treated as permanent |
| Telecom / defense / government procurement | Churn, spectrum, appropriations → contracts → delivery | Budget authorization or contract ceiling counted as booked revenue |

**Not covered at all:** autos/EV, batteries (used only as a framing example in IR `research-and-evidence.md`), chemicals, agriculture/food, media, aerospace, crypto. You will need to write these adapters yourself. As a starting point (my suggestion, not from the source): for EV, track regulatory credits, subsidy cliffs and battery $/kWh vs pack price. For batteries, track cell capacity utilization and chemistry share (LFP vs NMC).

## 3. Overhead to drop or compress

- **CSV registers** (IR `assets/*.csv`; IF `assumption-register.csv`, `signpost-register.csv`). Drop them. Fold only 3–4 fields into your existing [S#] + VERIFIED/REPORTED/UNVERIFIED tags: claim kind (fact / management claim / estimate / assumption / inference / forecast), observation period, publication date, independence group.
- **Python helpers** (`research_math.py`, `forecast_math.py`, `milestone_path.py`, `prepare_handoff.py`, `validate_forecast.py`) plus their tests. Drop them; turn the identities into inline arithmetic checks (CAGR intervals, price-volume bridge, stock reconciliation, latest-start).
- **Forecast-book JSON schema, SHA-256 hashes, namespaced claim IDs, `MANIFEST.sha256`, release checks.** Your stage handoffs already carry this structure.
- **IB/VC/PE/consulting/public-equity/credit lenses** (both `decision-lenses.md` files). Drop them. Keep only two rules: industry growth is not asset returns, and interim survival matters.
- **Client templates** (`report-template.md`, `forecast-report.md`, briefs). Compress into writer instructions. The one piece worth keeping is the "baseline vs target-year state" table in IF `target-year-dashboard.md`.
- **Depth modes** (quick scan / diligence / update; screen / deep / hindcast). Map them onto your quick/standard/deep presets.
- **Primary-research and interview plans.** Drop; your agents can't interview anyone.
- **Rolling-origin backtests, CRPS/interval/pinball scores, Monte Carlo seed records.** These belong in an offline evaluation harness, not in agent prompts. The 0–3 rubric (IF `evals/rubric.md`) suits an LLM judge in QA.
- **Repeated disclaimers** ("a watchlist does not schedule an automation", "no interviews occurred", "sources aren't current evidence"). Collapse into one boundary line. Never load the `methodology-sources.md` files into agents.

## 4. Gaps your pipeline needs filled

Confirmed by grep: zero hits for prediction markets, Metaculus/Polymarket/Kalshi, Tetlock/superforecasting, central bank/reaction function, chokepoint, stakeholder, Fermi, extremizing, yield curve/credit spreads/financial conditions, and technology readiness levels.

- **Macro regime.** Only channel-tracing (#14 above) exists. Add a growth × inflation × policy-stance × financial-conditions diagnosis using credit spreads, curve slope and FCI, plus a test for whether the regime is shifting.
- **Central-bank reaction functions.** Absent. Needed: mandate, forward guidance, SEP/dot plot, market-implied path (futures/OIS), a Taylor-rule benchmark, the meeting calendar, and the data that moves the decision.
- **Policy and regulatory process.** Only the enacted/proposed taxonomy and "authorization ≠ revenue" exist. Needed: stage base rates (introduced → committee → floor → signed), rulemaking stages (NPRM → comment → final → effective → litigation), statutory deadlines, and election and court calendars.
- **Geopolitics, sanctions, chokepoints.** Only a passing "geopolitical constraints". Needed: single-source inputs, export controls, straits, substitution lead times, and trade-flow evidence.
- **Technology readiness and S-curves.** The adoption chain is good but there are no TRL/MRL scales, no empirical diffusion-speed priors, and no Bass p/q ranges.
- **Commodity balances.** The inventory identity exists, but there is no supply/demand/stocks-to-use table, days of cover, cost-curve percentile, spare capacity, or futures curve shape (contango/backwardation as a tightness signal).
- **Base-rate and Tetlock discipline.** Mellers et al. is cited but no procedure is given. Needed: status-quo and "nothing happens" priors, Fermi decomposition, converting annual hazard rates to "by deadline" probabilities, time decay as the deadline nears, granular probabilities, and extremizing aggregated estimates.
- **Question decomposition.** Missing: how each data/actor/general KIQ maps to the binary forecast it informs; scenario-to-binary mapping, P(E) = Σ P(s)·P(E|s); keeping related questions mutually consistent; and resolution edge cases (series discontinued, revised after resolution).
- **Prediction markets as an anchor.** Absent. Needed: liquidity and volume thresholds, favourite-longshot bias, distortions in long-dated markets, mismatches between market and question resolution criteria, and a policy for justifying divergence from the market.
- **Actor and incentive mapping.** Absent apart from "who is adding capacity and why" (IR `cycles-and-drivers.md`). For the social simulation you need objectives, constraints, decision rights, red lines, credibility of past signals, and behavioural base rates.
- **Nowcasting with official data.** Only "nowcast remaining periods" plus ALFRED. Needed: release calendars and lags, typical revision sizes, SA vs NSA, bridging high-frequency to low-frequency series, consensus expectations, and the exact anchor for each question (series ID, units, vintage at resolution). Also distance-to-threshold measured in historical volatility units.

## 5. Format lessons

- **Frontmatter (`specification.md`).** `name` is 1–64 characters, lowercase letters, digits and hyphens, no leading, trailing or double hyphens, and must match the directory name. The examples break this: IR, IRc and IF all declare a name that doesn't match their folder. `description` is 1–1024 characters, non-empty, and should say what the skill does and when to use it. `compatibility` (≤500 characters) only if truly needed. `metadata` is a string-to-string map. `allowed-tools` is experimental.
- **Portability.** API and claude.ai uploads accept only the six spec fields; anything else is a hard error (`claudeskillsdoc.md` "Using skill frontmatter outside Claude Code").
- **Description writing.** Put the main use case first: Claude Code truncates `description` + `when_to_use` at 1,536 characters. Include concrete trigger phrases and explicit non-triggers. IR's "Do not use for a standalone stock quote…" is a good model.
- **Progressive disclosure.** Metadata is about 100 tokens, the body should be under 5,000 tokens and 500 lines, and references should sit one level deep and load on demand. IR's "Need → Resource" routing table and IF's "Always read X and Y; load others only when needed" are good patterns.
- **Size in practice.** IF `SKILL.md` is 20 KB, roughly at or over the 5,000-token guidance. The compact IRc/IFc versions (78–105 lines) are the better model.
- **Context lifecycle.** In Claude Code the skill body stays in context, and after compaction only its first 5,000 tokens are re-attached, so put the critical rules at the top. "State what to do rather than narrating how or why." Skills preloaded into subagents inject their full content at startup, which argues for very tight bodies in per-KIQ agents.
- **Don't hard-code sibling skills.** IF `research-handoff.md` describes a companion with a "186-line core" and files (`evidence-protocol.md`, `evidence-ledger.schema.json`, …) that don't exist anywhere in this folder.
- **OpenAI hosts** (`openaiskillsdocs.md`). Skill instructions get user-prompt priority, not system priority. Exactly one `SKILL.md` per bundle.
- **Reuse the eval design.** IF `evals/cases.json` mixes trigger and non-trigger prompts with adversarial probes, e.g. "Treat low/base/high 2035 cases as P10/P50/P90", "Three news stories repeat one capacity announcement; triple the posterior impact", "Sum regional P90", and an injected-instruction source. That format would make a good regression suite for your pipeline.
