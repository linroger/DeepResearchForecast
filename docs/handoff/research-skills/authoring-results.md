# Authoring round (workflow wf_db04393d-5ea, 2026-10-16)

Ten author agents, one skill folder each, with one writing the sector adapters. Below are their reports verbatim: files, checker output and design notes.

## industry-research

Files: deerflow_bridge/skills/industry-research/SKILL.md, deerflow_bridge/skills/industry-research/references/value-chain-and-sizing.md, deerflow_bridge/skills/industry-research/references/cycles-and-capacity.md, deerflow_bridge/skills/industry-research/references/industry-sources.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python .../docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/industry-research
OK

Sizes in characters (what the checker counts), measured against the caps:
- SKILL.md: 9,725 of 11,000 (9,939 bytes)
  - description: 986 of 1,000
  - Activation: 886 of 900
  - Plan: 1,788 of 1,800
  - Investigate: 2,391 of 2,400
  - Synthesize: 1,385 of 1,500
  - Gaps: 675 of 700
  - References: 1,116 (no cap)
- references/value-chain-and-sizing.md: 13,710 of 14,000 (13,748 bytes)
- references/cycles-and-capacity.md: 13,598 of 14,000 (13,727 bytes)
- references/industry-sources.md: 13,780 of 14,000 (14,478 bytes; the Chinese terms take several bytes each, and the cap is in characters)

The sector-adapter files belong to the other author. I link both from my References, and both exist now, so all five links resolve.
```

The industry-research skill is written: SKILL.md plus three reference files. The checker prints OK, and every section is under its size cap.

**Files**
- `SKILL.md` (9,725 characters). Its References section links my three files and the other author's two sector files, which now exist.
- `references/value-chain-and-sizing.md` (13,710): perimeter, sizing, reconciling estimates, profit pools and concentration, with a worked example.
- `references/cycles-and-capacity.md` (13,598): the six cycle clocks, stock-flow, capacity staging, cost curves, order quality, 12 traps.
- `references/industry-sources.md` (13,780): a source map by jurisdiction and sector, with data caveats.

**How it is built**
- **Plan:** seven baseline KIQs that can be merged, with a quick-depth subset. Each KIQ names the industry, geography and latest full year, because that wording is what routes the KIQ to this skill. KIQ 5 says "historically", so the engine's base-rate rule also gives it the reference-class skill.
  - The actor KIQ names the actors the simulation needs: top capacity holders, the high-cost marginal producer, the fastest entrant, key customers, regulators and state funders.
  - `data_needs` uses only catalog IDs, plus one concept query that the providers can actually answer.
- **Scenario weights, base-rate-first:**
  - Split on whichever constraint binds now (demand, capacity, cost or policy).
  - If the horizon spans half the industry's documented cycle, a phase change is the base case, not a tail.
  - Announced capacity counts at its stage-conditioned realization, not face value.
  - Promotional growth-rate claims in scout snippets never raise a boom weight.
  - For a target-year question, industry-forecasting sets the frame and starts from this skill's cycle phase and binding constraint, so the two Plan texts don't conflict.
- **Investigate:** starts with the four required quick steps (perimeter; size by segment from two independent estimate families plus one official series; stage-tagged capacity; a dated share table), then what standard and deep depth add. It also gives:
  - six identities (demand, installed base, stock-flow, volume × price, capacity bridge, effective output);
  - the reconciliation order you specified;
  - the six cycle clocks, with "indeterminate" as a valid reading;
  - four traps written as misreading → check;
  - an anchor format (series ID, period, unit, seasonal adjustment, latest value, status, long-run range, a threshold that separates scenarios);
  - the actor facts the simulation needs;
  - Chinese plus English search, and a stop rule.
- **Synthesize:** the five required tables. It never asks writers to add a probability list or change a probability. I first wrote "never restate probabilities", but that would have clashed with the executive summary, which must restate them exactly.
- **References:** the worked example is a fictional "Country A" storage industry with clearly invented numbers, and I checked all its arithmetic. It shows three conflicting size figures reconciled step by step, why summing revenues across stages is meaningless, and how cells can hold 18% of value added but 7% of the profit pool. It also shows installations up 40% while the market grows only 5%, and which series could settle a binary forecast.
- **Sources:** the source file records the caveats that cause real errors:
  - China's official statistics cover only firms above a revenue threshold (规模以上), and published growth rates are computed on a comparable basis.
  - Year-to-date reporting is common, and January–February are released together.
  - Association, customs and official-statistics totals measure different things.
  - The Chinese chip association's headline total adds three value-chain stages, so it double counts.
  - The US semiconductor output and price indices are quality-adjusted.
  - Korea's early-month export data and Taiwan's monthly company revenue filings are the fastest hard readings.

**Checks I ran**
- The engine's own parser (`research_skills.py`, read only) reads all four injected sections without cutting anything.
- Real Chinese and English questions route this skill as the baseline companion of industry-forecasting, and planner-style KIQs get its method text plus the right sector adapters.
- No `$` signs and no `[S<digits>]` markers anywhere in my files.
- No overlap with the `newskills/` text at the 8-word level. At 6 words the only match is the capacity-stage sequence your brief itself prescribes.

**Left out on purpose**
- No current figures, shares, prices or future dates.
- No numeric lead-time or cycle-length statistics. Only documented priors appear, named by source class: the US interconnection-queue reports, the energy agency's mine lead times, and textbook cycle lengths.
- No consultant material: data registers, scripts, investor-lens deliverables, interview plans or generic strategy checklists.
- No sector-specific detail, which the injected sector adapters carry, and no rules the deep-research skill already covers.

**Two router issues to pass to the lead** (I did not edit engine code):
- "Which US AI labs will lead by 2030?" does not route to competitive-landscape-forecasting, because the pattern only matches when "labs" directly follows "which".
- Any Chinese year written like "2025年" counts as future-looking, so present-state Chinese KIQs also get industry-forecasting's method text. That costs prompt space but does no harm.

Nothing was staged or committed.

## sector-adapters

Files: deerflow_bridge/skills/industry-research/references/sectors-technology.md, deerflow_bridge/skills/industry-research/references/sectors-economy.md

Checker:
```
$ backend/.venv/bin/python .../docs/handoff/research-skills/check_skill.py --sectors deerflow_bridge/skills/industry-research/references/sectors-technology.md
OK
$ backend/.venv/bin/python .../docs/handoff/research-skills/check_skill.py --sectors deerflow_bridge/skills/industry-research/references/sectors-economy.md
OK
```

I wrote both sector-adapter files (21 blocks), and the checker prints OK for each.

| File | Characters (checker cap) | Bytes | Blocks | Block sizes (cap 1,200) |
|---|---|---|---|---|
| `sectors-technology.md` | 11,385 (14,000) | 11,924 | 9 | 1,173–1,199 |
| `sectors-economy.md` | 13,923 (14,000) | 14,703 | 12 | 1,052–1,136 |

The byte count is higher because of the Chinese terms; the checker counts characters. Keys are in the exact order from design §4, and each block has the 7 bold labels in template order.

**Other checks I ran:**
- Every series ID was confirmed with `data_catalog.lookup()`, and the checker found none missing.
- No `$`, no `deep-research §`, no trailing spaces.
- Every block has 2–3 traps and a "Scenario axis".
- An 8-word overlap test against all of `newskills/**/*.md` found 0 matches.
- I staged nothing and changed no other file. `newskills/` was already untracked before this work.

**How the blocks are built:**
- **Each block works on its own.** The engine injects only the block, never the file header, so each block names its own anchors. Catalog IDs carry unit and frequency (e.g. `fred:CAPUTLG3344S (%, M)`, `usgov:eia/electricity_sales/VA.COM (million kWh, M)`).
- **No Chinese data through data_search.** Its providers are only fred, bls, bis, imf, wb and usgov, so it cannot serve NBS, MIIT, NEA, NFRA or MARA statistics. Those are marked "via web" with the release name in Chinese (e.g. 集成电路产量, 新型储能, 社会消费品零售总额) so the agent can search for the actual release.
- **data_search queries are in English and worded like FRED or World Bank series titles.** Examples: "e-commerce retail sales as a percent of total sales", "charge-off rate on all loans, all commercial banks", "nondefense capital goods excluding aircraft new orders".
- **Every trap is "misreading → the observation that tells them apart".** Examples:
  - CAAM vs CPCA NEV share: wholesale including exports and commercial vehicles, vs domestic retail.
  - 社零 treated as household spending, when it includes purchases by institutions and leaves out most services.
  - A PMI above 50 read as high output, when it measures how widespread the change is.
  - Queued grid capacity read as supply (LBNL prior).
  - Chinese 5G user definitions.
  - Physical qubit counts read as capability, instead of logical qubits.
  - Quota cuts read as barrels removed, instead of secondary-source output.
  - Low NPLs read as soundness, instead of 关注类 loans.
- **Each block has the identities it needs.** Examples: memory revenue = bits × ASP/bit; PUE; storage duration = GWh ÷ GW; China apparent oil demand; deposit beta; bank growth limit (RWA growth ≈ ROE × retention); take rate; deliverable MW = the minimum of parallel bottlenecks.
- **Each block ends Forecast drivers with a "Scenario axis".** It gives the planner a base-rate-first split, e.g. AI capex persistence × China self-sufficiency; power-limited vs demand-limited vs capex pullback; for quantum, fusion and robotics, on time / slip / stall weighted by each actor's past roadmap hit rate.
- **Staged pipelines are written out**, e.g. announced → tool move-in → qualified for fabs, and queue → agreement → COD for power.
- **Sources name S1/S2/S3 classes** across the US, China, the EU, Japan, Korea and Taiwan. That includes CSIA, CAICT, CPCA/CAAM, CNESA/CESA, NEA/CEC, NFRA, NHSA and MARA.
- **frontier-tech uses milestone ladders and TRL, with no TAM extrapolation.** banking-insurance values on ROE vs cost of equity and P/B, never EV/EBITDA.

**Accuracy corrections from my review pass:**
- I rewrote lines that stated current conditions as fact (e.g. "cell capacity far above output", "China's solar chain exceeds world demand") as checks to run.
- Every lead time now carries a named source, e.g. "(IEA priors)", "(LBNL/DOE prior)", "(Clarksons prior)". The battery learning rate is flagged as a prior to verify with BNEF/IEA.
- I corrected an inaccurate 510(k) lead time to "510(k) months vs PMA years".
- I removed a "3–5 yr platform cycle" that is wrong for Chinese carmakers.
- The NEA solar AC/DC basis is now a "check" rather than an assertion.
- The IMF lithium and cobalt units are ambiguous in the catalog, so the lithium ID carries "check unit".
- In aerospace I swapped `usgov:spending/total` (all federal awards, not defence-specific) for a data_search on national defence expenditures.

**What I left out, and why:**
- **No current facts.** No current prices, shares or rates, and no dates of future events. Policies are named so the agent checks their current status (136号文, 强制配储, US vehicle credits "check current law", MOFCOM export-control scope).
- **Little on actors for the simulation.** The 1,200-char cap leaves no room for actor lists per block. Actor-relevant regulators and bodies appear only in Sources and drivers. Actor facts for the simulation, and how findings are recorded, belong in the industry-research SKILL.md Plan and Investigate sections, which another author owns.
- **No consultant overhead.** No PESTLE-style checklists, valuation lenses or market-size (TAM) projections.

**For whoever writes the router and the industry-research SKILL.md:**
- **Economy file is near its cap.** It is 77 characters under 14,000, so any additions there need matching cuts.
- **Where some use cases fall.** Open-source AI is covered under cloud-software (open-weight vs closed models, USD per token). Quantum is under frontier-tech. The router's sector detection should send those topics to those keys.

## industry-forecasting

Files: deerflow_bridge/skills/industry-forecasting/SKILL.md, deerflow_bridge/skills/industry-forecasting/references/forecasting-methods.md, deerflow_bridge/skills/industry-forecasting/references/reference-classes-and-lead-times.md, deerflow_bridge/skills/industry-forecasting/references/outlook-reconciliation.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/industry-forecasting
OK
```

The industry-forecasting skill is written and the checker prints OK. I also ran the repo's own tests (read-only):
- All 8 `test_research_skills.py` tests that check this skill pass (`-k industry-forecasting`), and the `test_sessionb_skill_hygiene.py` suite passes.
- The engine's own `parse_skill` reads all four injected sections without truncating them.
- `route()` sends every listed use case to this skill, in both English and Chinese, with the right sector adapter. CPI and Russia–Ukraine questions route elsewhere.
- I wrote nothing outside the skill folder and made no git operations.

**Files** (characters; bytes differ because of the Chinese text):
| File | Size | Cap |
|---|---|---|
| `SKILL.md` | 9,184 | 11,000 |
| `references/forecasting-methods.md` | 13,555 | 14,000 |
| `references/reference-classes-and-lead-times.md` | 13,852 | 14,000 |
| `references/outlook-reconciliation.md` | 11,152 | 14,000 |

Section sizes: Activation 870/900, Plan 1,790/1,800, Investigate 2,389/2,400, Synthesize 1,478/1,500, Gaps 661/700. The description is 973/1,000 characters with no `": "`, so the YAML parses.

**Design choices**
- **Written for the engine's actual behaviour**:
  - Base-rate KIQs are worded "historical base rate of …" so the engine pulls 30 years of data.
  - The data layer keeps only the newest 240 observations, so a monthly series gives about 20 years; the skill says so.
  - Signposts are recorded as series, period, comparator, threshold and units, the shape a binary forecast's data anchor settles on.
  - Every section writer receives the Synthesize text, so it says to place each exhibit once.
  - Plan names "exhibit homes" sections so each table has one place to go.
- **The scenario weights are base-rate-first**, because they are fixed at plan time from scout snippets. Most weight goes to the range that holds the simple benchmark (trend or constant share). It is then skewed by a documented prior, to be verified: modular, mass-made technologies have tended to beat agency outlooks, while big first-of-a-kind builds tend to slip. Only enacted policy and funded capacity under construction move it further. Targets and normative scenarios never set weights.
- **No repetition of the sibling skills.** `industry-research` is injected alongside this skill, so I left its capacity-staging chain, identities and present-state traps to it. I also dropped my small-tail rule so it cannot conflict with `reference-class-forecasting`. Investigate still stands alone for forecasting KIQs, with traps of its own (targets read as forecasts, roadmap dates read as milestones, growth rates run past saturation).
- **Plan routing hint.** It tells the planner to add `competitive-landscape-forecasting` for "who leads" questions, because the router misses some of them (see below).
- **References.** All illustrative numbers were computed in a script, so every example is exact. Every base rate and lead time is phrased as a prior to verify, with its source class named. Chinese statistical definitions (口径) are covered, for example 上险量 vs wholesale and 装车量, and the 预期性 vs 约束性 split for plan indicators.

**Left out on purpose**
- Current figures and dates of future events.
- Sector specifics (they live in the sector adapters).
- k-of-n counting and hazard maths (owned by `reference-class-forecasting`).
- Consulting overhead (CSV registers, scripts, client templates, deal lenses).
- Any copied prose or layout from `newskills/`.

**Two things for you, in files I don't own:**
- **One router test fails**, unrelated to this skill: `test_real_questions_route_to_their_method_skills` for the Chinese question "预测到2030年，哪家美国人工智能实验室或企业将成为美国AI领域竞争的主导者". It expects `industry-forecasting` alongside `competitive-landscape-forecasting`, but `route()` returns only the latter. Routing comes from regexes in `research_skills.py` and doesn't read skill files.
- **Some "who leads" questions never reach `competitive-landscape-forecasting`.** "Cloud computing market leaders by 2030", "Which cloud provider will lead by 2030?" and "2030年云计算市场的领导者是谁？" all miss it: its trigger scores 1.0, below the 2.0 minimum, and 领导者 isn't matched at all.

## competitive-landscape-forecasting

Files: deerflow_bridge/skills/competitive-landscape-forecasting/SKILL.md, deerflow_bridge/skills/competitive-landscape-forecasting/references/leadership-metrics.md, deerflow_bridge/skills/competitive-landscape-forecasting/references/persistence-and-share-dynamics.md, deerflow_bridge/skills/competitive-landscape-forecasting/references/tech-race-indicators.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/competitive-landscape-forecasting
OK
```

I wrote the competitive-landscape-forecasting skill: SKILL.md plus three reference files. The checker prints OK, and every section fits its cap, so the engine injects each one whole.

**Files (characters / bytes)**

| File | Chars | Bytes |
|---|---|---|
| SKILL.md (cap 11,000) | 8,979 | 9,178 |
| references/leadership-metrics.md | 13,547 | 13,860 |
| references/persistence-and-share-dynamics.md | 13,379 | 13,475 |
| references/tech-race-indicators.md | 12,140 | 12,572 |

The reference files are capped at 14,000 characters each.

| SKILL.md section | Chars | Cap |
|---|---|---|
| Activation | 807 | 900 |
| Plan | 1,786 | 1,800 |
| Investigate | 2,387 | 2,400 |
| Synthesize | 1,431 | 1,500 |
| Gaps | 597 | 700 |
| Description | 968 | 1,000 |

**Other checks run**
- The engine's own parser reads the skill, and none of the four injected blocks is cut short.
- The planner menu line is under the parser's 200-character cut.
- The legacy deer-flow validator says "Skill is valid!", and the frontmatter parses as YAML.
- In `test_research_skills.py`, the three format, catalog and reference tests for this skill pass. The hygiene tests pass.
- Every catalog ID in the four files exists in the data catalog.

**Design choices**
- **Written around the engine's actual behaviour.**
  - A KIQ only gets this method if its own wording contains a ranking word, so the Plan tells the planner to put one in every landscape KIQ ("leadership", "rank", "dominate", 排名, 领跑). I checked that actor KIQs phrased this way do get the method.
  - KIQ agents and writers cannot open files, so the injected sections never point to the references. Anything they need, such as the tier bands, the "by YEAR" rule and the country-race checks, is written inline.
  - Binary forecasts only settle on catalog series, and rank metrics are rarely in the catalog. So each finding names the document that would settle it (filing line, tracker table, exchange list, eval board) in a fixed one-line format. Catalog IDs are used only for official proxies: exchange rates, the US chip price index, credit spreads and similar.
- **Leadership contract.** Before any search, the brief fixes:
  - one primary metric, its perimeter, the settling source, the period and the comparison;
  - for multi-criteria prompts, weights set once plus a tie rule;
  - the meaning of "by YEAR" (calendar-year value, or the Dec 31 state);
  - the difference between "ever overtakes" and "ahead for the full year".
  The first reference gives the default metric and its traps for 12 market types: memory, HBM, foundry, equipment, cloud, AI labs, open-weight AI, platforms, EVs, batteries, IPO league tables and market-cap rankings.
- **Base rate first.**
  - Scenarios split on who leads at resolution: incumbent holds, a named challenger takes #1, or the field / a structural break. For full rankings and races they split on what reorders the table.
  - Incumbent weight starts from a class prior, and today's order is never the default.
  - The persistence reference gives the full counting method: window counting with an effective n, a shrunk estimate from non-overlapping windows, a constant-hazard conversion and a field-rate floor.
  - It also lists seven widely documented leadership histories as anchors to verify, never as current claims: DRAM, total semiconductor revenue, foundry, phones, browsers, PCs and search.
- **Rank probabilities tie to the scenarios.** P(#1) for each contender is derived from the fixed scenario weights and quoted, never re-estimated. The ranking is a table, not a second probability list. Coherence checks:
  - P(#1) across contenders, field included, sums to 100;
  - each contender's chance of making the top k is at least its P(#1), and those chances sum to k × 100.
  I checked that this does not trip the engine's scenario-weight rewriting.
- **Capability evidence without scores.** Each of the eight dimensions holds a dated, cited fact comparable across at least two contenders, or stays empty. Benchmark gaming, capacity staging and "stated vs revealed" behaviour each come with a test that tells the readings apart. Actor facts for the simulation include the objective, guided vs cash capex, behaviour in downturns, hard constraints, credibility track record and how each contender reacted to past moves.
- **Catch-up arithmetic.** Formulas for when a challenger closes a share gap, overtakes on revenue or overtakes on market cap. Each is compared with the fastest swing seen in the reference class, and challenger paths carry kill criteria with a threshold and a date.
- **Country races.** The third reference covers ten metric families, each with what to measure, sources, and why raw counts mislead. It also gives a fixed-weight composite method, the facts needed for state actors, and a source map for China in both Chinese and English.

**Left out on purpose**
- Generic strategy checklists and 1–10 persona scores.
- Any current shares, prices, ranks or dates of future events, and any statistic I could not trace.
- Data that only applies to one company.
- Market-size forecasting, which belongs to industry-forecasting.
- Price paths and IPO-stage odds, which belong to financial-markets-forecasting.
- Whether a policy passes, which belongs to policy-and-trade-forecasting.
- I also removed some wording that read like a claim about today (for example, "local providers lead there").

The default weights by market class, the "dominate" threshold (share of at least 40% and at least 1.5× the #2) and the tier bands are labelled as conventions in the text, not data.

**For the lead (outside my files, not edited)**
1. In the existing tests, the routing case for "预测到2030年，哪家美国人工智能实验室或企业将成为美国AI领域竞争的主导者。" fails: industry-forecasting is expected alongside this skill, but only this skill and reference-class come back. The router only reads question text, so this failure does not come from my files.
2. Some real prompts don't reach this skill:
   - "Which US AI lab will lead by 2030?" sends only the industry skills: the "which lab" pattern doesn't allow words in between.
   - "US China EU quantum computing race 2026-2040: who leads?" routes nowhere: "who leads" isn't matched, only "who will".
   - "Cloud computing leaders by 2030 market share" sends only the industry skills.
3. The new folder still has to be synced into the deployed copy (`deer-flow/skills/public`).

I did not stage, commit, or touch engine code, tests, other skills or newskills/.

## macro-research

Files: deerflow_bridge/skills/macro-research/SKILL.md, deerflow_bridge/skills/macro-research/references/central-bank-reaction-functions.md, deerflow_bridge/skills/macro-research/references/nowcasting-and-releases.md, deerflow_bridge/skills/macro-research/references/macro-base-rates.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/macro-research
OK
```

The macro-research skill is written and the checker prints OK.

**Files and sizes** (all under deerflow_bridge/skills/macro-research/):

| File | Characters | Bytes | Notes |
|---|---|---|---|
| SKILL.md | 9,098 | 9,323 | description 911; Activation 853, Plan 1,793, Investigate 2,393, Synthesize 1,430, Gaps 667 |
| references/central-bank-reaction-functions.md | 13,667 | 13,898 | under 14,000 by either measure |
| references/nowcasting-and-releases.md | 11,505 | 11,617 | |
| references/macro-base-rates.md | 10,477 | 10,578 | |

**Checks beyond the checker:**
- Every series ID in the four files resolves in data_catalog: 24 in SKILL.md and 27–39 per reference.
- No `$` anywhere.
- The frontmatter parses as strict YAML.
- The engine's own parser reads the skill correctly.
- `route()` sends real English and Chinese Fed, CPI, recession, ECB/BOJ and China questions to macro-research, with reference-class-forecasting alongside.

**Design choices**, based on what the pipeline code actually does:
- **Settle-ready anchors.** In `data_sources.py`, any daily series stored as monthly values (fred:DFEDTARU, fred:ECBDFR, yields) and every World Bank or WEO series is marked not resolution-safe, so it only settles by hand. The skill therefore anchors Fed questions on bis:WS_CBPOL/M.US, which is the target-range midpoint (upper bound − 0.125). Headline CPI is anchored on bls:CUUR0000SA0#yoy, because the published 12-month rate uses the unadjusted index.
- **Stored history.** The forecast stage computes its own outside view from the stored window, which keeps only the newest 240 observations (about 20 years of monthly data), and the first call fixes that window. So Plan words the base-rate KIQ to trigger the engine's 30-year prefetch (English and Chinese wording), and Investigate tells agents to fetch the anchor with its exact transform.
- **Method content:**
  - a regime shift test: 3-month vs 12-month momentum, at least two blocks moving for at least two releases;
  - the year-on-year identity and the required monthly run-rate for threshold questions;
  - real policy rate against r-star;
  - the order in which central-bank signals count;
  - a table per decision point comparing market-implied odds, the official projection and an evidence-based view, with consistency checks;
  - the CME futures formula and the warning that FedWatch odds are cumulative;
  - Taylor rules used only as a cross-check;
  - for China: the instrument hierarchy, the Politburo–CEWC–NPC calendar and data caveats.
- **Scenarios** are regimes fitted to the question (a China set is included). They are weighted base-rate-first from NBER frequencies, written as priors to verify, then shifted in stated steps for market pricing and hard signals, with every tail at least 5.
- **Base rates** follow a fixed counting rule (trigger, window, outcome, independence, false alarms, shrink small samples), with worked rules for recessions, Sahm and the yield curve, cutting cycles, disinflation, soft landings, surprises against market pricing, projection errors and China's growth targets.
- **Actor fields** for the simulation cover role, vote, dated stance, dissents, term end, constraints, credibility and red lines, plus a decision-makers table for writers.

**Deliberately left out:** current rates, levels, members and meeting dates (agents fetch them); generic consulting checklists; how to convert a hazard to a deadline probability and keep scenarios and binaries consistent (reference-class-forecasting covers that); yield, FX and spread price targets (financial-markets-forecasting); tariff legal paths (policy-and-trade-forecasting). Every historical figure is phrased as a prior to verify, with its source class.

**Conflict for you to resolve:** references/base-rate-recipes.md in reference-class-forecasting says target questions settle on fred:DFEDTARU. The code and the test at test_data_sources_normalization.py:320 show that monthly series built from daily data are marked not resolution-safe, so DFEDTARU anchors settle only by hand. I did not edit that skill.

I did not create a handoff.md: the assignment restricted writes to this folder. Nothing was staged or committed, and newskills/ was not touched.

## policy-and-trade-forecasting

Files: deerflow_bridge/skills/policy-and-trade-forecasting/SKILL.md, deerflow_bridge/skills/policy-and-trade-forecasting/references/us-process-and-base-rates.md, deerflow_bridge/skills/policy-and-trade-forecasting/references/trade-instruments.md, deerflow_bridge/skills/policy-and-trade-forecasting/references/signals-and-credibility.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python .../docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/policy-and-trade-forecasting
OK
```

The policy-and-trade-forecasting skill is written and the checker prints OK. All 12 of the lead's tests that touch this skill pass (`-k "policy or hygiene"`), as does the hygiene test file. The full `test_research_skills.py` run has one failure, in a router test the lead owns: a Chinese "which US AI lab will dominate by 2030" question gets `industry-forecasting` as an extra skill. It is not about this skill. I wrote nothing outside my folder and made no git operations.

**Files (characters, then bytes; caps are in characters)**
| File | Chars | Bytes | Cap |
|---|---|---|---|
| SKILL.md | 9,215 | 9,417 | 11,000 |
| references/us-process-and-base-rates.md | 13,485 | 13,516 | 14,000 |
| references/trade-instruments.md | 13,966 | 14,272 | 14,000 |
| references/signals-and-credibility.md | 10,847 | 10,924 | 14,000 |

Section sizes against caps: Activation 893/900, Plan 1,797/1,800, Investigate 2,388/2,400, Synthesize 1,481/1,500, Gaps 610/700. The description is 957 characters and parses with `yaml.safe_load`, which the deer-flow loader uses. The engine's own `parse_skill` loads it and no section is truncated. Questions about IEEPA and the trade system route to this skill in English and Chinese.

**Design choices**
- **Must-have content sits in the injected sections.** In v3 the planner and research agents never see the reference files. So Plan carries the scenario frame and a few concrete priors, and Investigate carries the key procedural clocks: bill passage, the 60-vote Senate rule unless reconciliation, rulemaking stages, court and cert deadlines, Sections 232, 301 and 122, and the EU process.
- **Everything is organised per instrument.** Each instrument is placed on a status ladder: threatened → announced → signed → published → effective → implemented → collected → durable or reversed. The question's wording decides which step counts as resolution.
- **Scenarios are legal path × political will**, collapsed to 3–5 mutually exclusive states of what is in force on the resolution date. Weighting starts from base rates: a change path gets near zero if the minimum statutory clocks cannot finish in time, otherwise its stage prior shrunk for each extra veto player. The status quo keeps the remainder, and elections are conditioned on, not forecast. When one tariff authority falls or expires, the substitutes are listed with their own clocks and ceilings: 122, 232, 301, 338, statute or deals.
- **Anchors match how the forecast stage settles them.** I read `validate_data_anchor`: an anchor settles on one stored month, quarter or year, optionally `#yoy` or `#pct`. So the skill bans sums and computed ratios as anchors, even though the effective tariff rate is computed for analysis. Annual tariff revenue is anchored on `fred:B235RC1Q027SBEA` for a named quarter.
- **Measurement:** effective tariff rate = customs duties ÷ customs-value imports for consumption over the same months. The traps covered are refunds (Treasury receipts are net of refunds and can go negative), payment lagging entries by about a month, front-loading, and import prices that exclude duties. Trade diversion is separated from transshipment and relocation by what each would show in the data, and the US–China mirror gap (each side's reported bilateral trade disagreeing) is tracked by its change.
- **Credibility ledger:** an actor's past threats are counted as k of n kept, with a small-sample correction, and rate conditioned on each status step. It feeds the actor fields the simulation needs.
- **China and EU:** MOFCOM numbered announcements, the unreliable entity list, the State Council Tariff Commission, anti-dumping (12+6 months), NPC Standing Committee readings, the EU legislative process, EU trade defence clocks and the anti-coercion instrument. Chinese search terms and primary-source classes are named.
- Every catalog ID used exists in `data_catalog.py`.

**Deliberately left out**
- Current facts: no IEEPA ruling outcome, current rates, deal terms or future dates. The skill tells agents to fetch the latest opinion and refund guidance first.
- Specific recent tariff actions and executive order numbers, and the refund figure in the catalog note.
- Precise statistics I could not vouch for. Base rates are phrased as priors to verify, with their source class named.
- Generic consulting checklists, prose or structure copied from `newskills/`, and election and war mechanics, which go to the sibling skills.

**For the lead (router, not edited by me)**
- "Will Congress pass a crypto market structure bill by 2026?" does not route here: `bill` and `congress` share one 1.0-weight pattern, scoring 1.25 against the 2.0 threshold.
- "Will the EU impose countervailing duties on Chinese EVs?" does not route here: `countervailing` is missing from the 2.0-weight trade triggers.

## geopolitical-forecasting

Files: deerflow_bridge/skills/geopolitical-forecasting/SKILL.md, deerflow_bridge/skills/geopolitical-forecasting/references/conflict-base-rates.md, deerflow_bridge/skills/geopolitical-forecasting/references/escalation-and-negotiation.md, deerflow_bridge/skills/geopolitical-forecasting/references/evidence-under-information-war.md

Checker:
```
cd <repo> && backend/.venv/bin/python .../docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/geopolitical-forecasting
OK
(exit 0)
```

I wrote the geopolitical-forecasting skill: SKILL.md plus three reference files. The checker prints OK. I only wrote inside the assigned folder: no engine, test, sibling-skill or newskills/ edits, and no git operations.

**Files (characters as the checker counts them):**

| File | Size | Cap |
|---|---|---|
| SKILL.md | 9,040 | 11,000 |
| references/conflict-base-rates.md | 13,432 | 14,000 |
| references/escalation-and-negotiation.md | 13,854 | 14,000 |
| references/evidence-under-information-war.md | 11,423 | 14,000 |

SKILL.md sections against their caps: description 967/1,000; Activation 844/900; Plan 1,782/1,800; Investigate 2,378/2,400; Synthesize 1,361/1,500; Gaps 685/700; References 585. Plan and Investigate are within about 20 characters of their caps. If the lead's test counts characters slightly differently from the checker, those two sections are the ones to recheck.

The six catalog IDs used all resolve through `data_catalog.lookup()`: fred:DCOILBRENTEU, fred:GASREGW, imf:PCPS/G001.POILBRE.USD.M, imf:PCPS/G001.PNGASEU.USD.M, imf:PCPS/G001.PNGASJP.USD.M, imf:PCPS/G001.PWHEAMT.USD.M. Military spending has no catalog series, so it gets a data_search concept query. The frontmatter parses as YAML with only name and description. The injected sections contain no dollar signs and no [S<n>] markers. Routing matches the siblings: policy-and-trade sends wars, ceasefires and coercive sanctions here, and election-forecasting sends coups and regime stability here.

**Design choices**
- **Outcome definitions:** the four terms are ceasefire, armistice, peace agreement and frozen conflict. Each outcome also states whether it is partial or comprehensive, signed or in force, and how long it must hold. "By D" means it happened on or before D; "on D" means the state holds on D.
- **Scenario frame:** scenarios sit on one axis, the state at the horizon. They are made mutually exclusive by a "first match wins" order, most severe first: decisive outcome, widened war, settlement in force, ceasefire or frozen line, continued fighting. US–Iran and Taiwan get adapted lists in the same severe-first order.
- **Weighting at plan time:** start from the status quo, using one minus the reference class's hazard of change over the horizon. Shift weight toward agreement only on evidence of the stage reached (signed text, then framework, then talks), never on headlines. Decisive outcomes and great-power or nuclear escalation stay in single digits unless a threshold has already been crossed.
- **Binary anchors:** only series stored during research can settle a binary, so the Plan asks for the Brent, EU gas and wheat series where there is an energy or grain channel. Event outcomes must name the source that settles them: a UN document, an official gazette, or an ACLED monthly count.
- **Evidence grading:** an act (signed text, decree, sanctions notice) proves only that it exists. Everything a belligerent claims is REPORTED. VERIFIED needs two independent origins or the official text of the act itself. Casualty, loss, interception and capture claims are always REPORTED, and territorial change is measured within one map series.
- **Actor facts for the simulation:** actor KIQs record each actor's minimum and maximal goals, red line in its own words with its enforcement record, leverage, constraints, whether time favours it, and stated versus revealed behaviour. The planner's actor list includes security organs that may act apart from their leaders, and domestic veto players. The report carries an actor matrix: goal, red line, leverage, constraint, evidence.
- **Report tables:** state of play, actor matrix, negotiation track, signposts and base rates. Signposts cover mobilization, deployments, aid packages and votes, sanctions rounds, energy flows and prices, envoy visits and rhetoric shifts, each with a threshold. The report closes with what would change the view.
- **Sources, global and Chinese:** UN Security Council records, OHCHR, IAEA, OFAC, the EU Official Journal and congressional votes. On the Chinese side: 外交部, 国防部, 国台办, 商务部 and 东部战区, plus Taiwan's 國防部 and 陸委會, and Japan's Joint Staff for corroboration. Agents search in Chinese, English and the belligerents' languages.
- **conflict-base-rates.md:** a table of the conflict datasets (COW, UCDP termination and ceasefire data, PA-X, ACLED, crisis, coup, leader, sanctions and mediation datasets, SIPRI, IISS, Kiel) and seven ordered checks for choosing a reference class. The deciding check is conditioning on how long the war has already lasted. Priors are qualitative and marked "to verify" with their source class. It also covers converting a hazard rate into a deadline probability (with a worked illustration) and a recipe for turning base rates into plan-time weights.
- **escalation-and-negotiation.md:** an eight-rung escalation ladder (R0–R7) with observable markers and indicator sets for Russia–Ukraine, Iran, Taiwan and coups. It also has a red-line credibility ledger, bargaining-theory cues for why wars continue or end (Fearon, Zartman, Putnam, Stedman), and a nine-stage negotiation table with the usual misreading at each stage. It covers mediator types, the chain from sanction announcement to policy effect, and binary templates.
- **evidence-under-information-war.md:** a table of what each source class can and cannot prove, an ordered grading procedure, and propaganda patterns written as traps. It also covers casualty and territory rules, polls under repression, handling of Chinese official texts, and finding templates.

**Deliberately left out**
- No current facts: no front lines, troop numbers, prices, current positions, live peace plans or dates of future events. Numeric priors appear only where they are widely documented (about half of coup attempts succeed; Hufbauer, Schott and Elliott code about a third of sanctions as at least partly successful), and every prior is phrased "to verify".
- The research core is not repeated: no source tiers, evidence ledger or yield stop.
- No consulting checklists, registers or interview plans, and no reproduction of Kahn's escalation ladder. newskills/ has nothing on geopolitics, so nothing was taken from it.
- To fit the caps, two things moved from the injected sections into the references: daily Brent and Asian LNG in the data requests, and the "price spike means supply loss" trap.

## election-forecasting

Files: deerflow_bridge/skills/election-forecasting/SKILL.md, deerflow_bridge/skills/election-forecasting/references/fundamentals-and-polls.md, deerflow_bridge/skills/election-forecasting/references/us-election-mechanics.md, deerflow_bridge/skills/election-forecasting/references/non-us-elections.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/election-forecasting
OK
```

The election-forecasting skill is written and the checker prints OK. Its four engine-contract tests in backend/tests/test_research_skills.py also pass: format, catalog IDs, references, and routing of the real midterm question. Nothing was committed; the folder is untracked.

**Files (characters / bytes)**

| File | Chars | Bytes |
|---|---|---|
| SKILL.md | 9,200 (cap 11,000) | 9,354 |
| references/fundamentals-and-polls.md | 13,792 (cap 14,000) | 13,897 |
| references/non-us-elections.md | 12,514 | 12,636 |
| references/us-election-mechanics.md | 10,671 | 10,690 |

| SKILL.md section | Size / cap |
|---|---|
| Activation | 879 / 900 |
| Plan | 1,790 / 1,800 |
| Investigate | 2,385 / 2,400 |
| Synthesize | 1,486 / 1,500 |
| Gaps | 689 / 700 |
| Description | about 930 / 1,000 |

Every series ID I cite exists in the catalog: fred:UNRATE, fred:CPIAUCSL#yoy, fred:DSPIC96#yoy and the state series, plus IMF and BIS series for the UK, Germany, Japan, India, Brazil and the euro area.

**Design choices**
- **Built against real failures.** The earlier us-midterms-2026 dossier gave a 50–50 Senate to the party that did not hold the vice presidency. Its scenarios were not mutually exclusive and left out "R House + D Senate". It multiplied independent toss-up odds to price a sweep, and it drifted to 2028. Each of these is now a named trap or a rule.
- **Base-rate-first weights.** The v3 planner sees only the Plan section and fixes weights at plan time. So Plan itself carries the documented prior (the president's party lost House seats in every post-war midterm except 1998 and 2002, marked "verify").
  - It also carries an exact "cushion" test: House cushion = seats − 218, Senate cushion = seats − 50 (the president's party holds the vice presidency in a midterm). The prior is k/n, the share of past midterms where the loss exceeded the cushion.
  - Then it shifts toward markets and polls as the vote nears, and gives split outcomes less weight than independence implies.
- **Correlated errors by hand.** Agents cannot run code, so the reference gives two hand methods: a tipping-point estimate, Φ(margin / σ), and a three-node Gauss–Hermite method for sweeps and House+Senate combinations. Both have checked worked examples: a correlated four-race sweep is about 18% versus 6% under independence, and a two-chamber example gives weights 25/49/2/24 that reproduce the single-chamber probabilities.
- **Votes to seats.** A uniform-swing identity: Democrats win 218 seats only if the generic-ballot margin beats the national presidential margin minus the 218th district's margin. The difference is recorded as map bias.
- **Investigate.** A 3-step quick path comes first, then standard and deep additions, then 10 traps written "misreading → discriminating observation". Findings must record:
  - margins as D−R points with population (LV/RV), field dates and aggregator;
  - for economic anchors: series ID, observation month as YYYY-MM-01, unit and threshold;
  - for outcomes: the certifying body, the control rule and the date convention.
- **Writer exhibits.** Fundamentals, dated polling averages, ratings distribution, path to majority and signposts, plus an actors line (voter blocs as share, lean, turnout and trend; principals' revealed moves). For non-US races, seat-projection and coalition tables replace the ratings and path tables.
- **Actors and sources.** Actor classes map onto the engine's extraction roles (principal, arbiter, stakeholder, intermediary, amplifier). Each US and non-US jurisdiction gets named official sources. For Chinese prompts, agents search English or local-language official sources and use Chinese for Taiwan's election commission (中选会). China's own leadership questions route to geopolitical-forecasting.

**Left out on purpose**
- No current facts: no seat counts, who holds the presidency or vice presidency, the election date, the current maps, or live litigation. Fragile rules (Louisiana's primaries, Alaska's ranked-choice voting, ballot-receipt deadlines) are marked "verify".
- No unsourced statistics. Each historical prior names its source class; worked examples are labelled hypothetical.
- No generic market-query craft, hazard maths or source tiers, which the prediction-markets, reference-class-forecasting and deep-research skills already cover. No consultant templates, and no FiveThirtyEight-style poll-weighting code.

**For the lead (outside my folder)**
- The router sends nothing to election-forecasting for an approval-only question ("Will Trump's approval rating be above 45%…") and nothing at all for "中共二十一大后的领导层换届". Consider adding approval rating / 支持率 to the election patterns, and 换届 / 党代会 to geopolitical.
- One unrelated router test fails: the Chinese US-AI-labs question no longer co-routes industry-forecasting. A separate run with `-x` also stopped earlier on macro-research, whose SKILL.md links a missing references/macro-base-rates.md. Both belong to other folders.

## financial-markets-forecasting

Files: deerflow_bridge/skills/financial-markets-forecasting/SKILL.md, deerflow_bridge/skills/financial-markets-forecasting/references/implied-distributions.md, deerflow_bridge/skills/financial-markets-forecasting/references/empirical-and-volatility-base-rates.md, deerflow_bridge/skills/financial-markets-forecasting/references/listings-and-ipos.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/financial-markets-forecasting
OK
```

I wrote the financial-markets-forecasting skill: SKILL.md plus three reference files. The checker prints OK.

## Files (characters, as the checker counts them; bytes in brackets)

| File | Size | Cap |
|---|---|---|
| SKILL.md | 8,801 [8,964] | 11,000 |
| references/implied-distributions.md | 12,967 [12,971] | 14,000 |
| references/empirical-and-volatility-base-rates.md | 10,856 [10,856] | 14,000 |
| references/listings-and-ipos.md | 11,881 [12,202] | 14,000 |

SKILL.md sections: Activation 777/900, Plan 1,790/1,800, Investigate 2,385/2,400, Synthesize 1,228/1,500, Gaps 605/700 (eight checks). The description is 985 characters and parses as plain YAML. The engine's own parser (`research_skills.parse_skill`) reads every section in full. There is no `$` or `§` anywhere, no `[S<n>]` marker in the injected sections, and every catalog ID resolves.

## What I found in the pipeline code, and built the skill around
- **The first fetch fixes the history.** The first `data_get` of a series sets its window for the whole run, and a stored series keeps only its newest 240 observations (20 years of monthly data). So a series must be fetched with `start` 30 years back on its first call, or named in a base-rate KIQ's `data_needs` (a KIQ is a planner research question).
- **Daily market series are stored as monthly means.** This applies to `DGS10`, the spreads, FX, oil and `SP500`. The forecast stage marks them unsafe for automatic resolution. Its own rule is "a monthly mean of daily data cannot settle a single-day question". Hence the skill's anchor rule: these series anchor only monthly averages, never a single-day close or a touch.
- **Monthly-native series do settle automatically.** For example `imf:PCPS/G001.POILBRE.USD.M`, `fred:PCOPPUSDM`, `bis:WS_XRU/M.CN.CNY.A` and `bis:WS_CBPOL/M.US`. The references say to prefer them when a question allows an average.
- **How the forecast stage computes base rates.** It uses absolute h-step changes from the latest complete month and needs at least 30 samples. The references correct three distortions: price-level scale, overlapping samples (240 months at h = 36 gives fewer than 7 independent outcomes), and a starting value up to about six weeks old.
- **Scenario weights are fixed at plan time from scout snippets only.** So Plan gives a rule to centre on the forward or no change and start near 16/68/16 when the bins sit at about plus or minus one vol-scaled sigma. It also gives long-run volatility ranges, labelled as priors to verify, for when the scout shows none.

## Design choices
- **Plan:** the settlement contract comes first (publisher, fixing time and zone, level on a date vs touch vs average vs rank, price vs total return). Then KIQs for the base rate, the market-implied distribution, the fundamental anchor, a catalyst calendar, and actors (price-setters and gatekeepers).
- **Investigate:** a quick path first, then standard and deep additions. A fixed finding format with an `anchor:` or `not anchorable:` line and a market-implied, empirical or judgmental label. S1 source classes, global and Chinese (CFETS, ChinaBond, SSE/SZSE/BSE, the Chinese futures exchanges including GFEX, HKEXnews, EDGAR). A line requiring Chinese and English searches, because the engine has no bilingual rule of its own. Seven traps, each written as misreading → discriminating observation.
- **Synthesize:** a settlement-definition table, a labelled P10/P50/P90 non-exceedance table with a reconciled row, a catalyst calendar and signposts. It never asks writers for a probability list.
- **References:**
  - **implied-distributions:** turning futures curves, fed funds and SOFR futures, OIS, foreign-exchange forwards, options (lognormal and normal-model formulas, skew, event moves, touch questions), CDS and prediction-market brackets into probabilities, each with the risk premium to remove.
  - **empirical-and-volatility-base-rates:** formulas for period averages, A-overtakes-B odds and touch questions; regime precedents to verify.
  - **listings-and-ipos:** A-share, Hong Kong and US listing stages, clocks, lock-ups and price limits, all as priors to verify, plus ranking conventions.
- **Routing:** this skill pairs with macro-research for policy rates and with competitive-landscape-forecasting for IPO and market-cap rankings. Both of those sibling skills already say the same in their own text.

## Left out on purpose
- Current prices, rates, shares and dates of future events.
- IPO termination or approval rates. None is widely documented, so the skill shows how to count them from the exchange's own status lists.
- Consultant overhead, code helpers, and a repeat of the general research-core or prediction-market rules (the references point to the prediction-markets skill instead).
- A futures-roll trap, folded into the "roll rule" item in step 1, and a few lower-value IDs, to stay inside the caps.
- Nothing from `newskills/` was copied or changed. Nothing was committed.

## reference-class-forecasting

Files: deerflow_bridge/skills/reference-class-forecasting/SKILL.md, deerflow_bridge/skills/reference-class-forecasting/references/base-rate-recipes.md, deerflow_bridge/skills/reference-class-forecasting/references/probability-toolkit.md, deerflow_bridge/skills/reference-class-forecasting/references/prediction-market-anchoring.md

Checker:
```
$ cd <repo> && backend/.venv/bin/python docs/handoff/research-skills/check_skill.py deerflow_bridge/skills/reference-class-forecasting
OK
```

The reference-class-forecasting skill is written and passes the checker (prints OK). The repo's skill tests also pass for it: 10 passed, covering the format contract, catalog IDs and reference links.

Files written (characters, the unit the caps are measured in):

| File | Size | Cap |
|---|---|---|
| SKILL.md | 9,224 | 11,000 |
| references/base-rate-recipes.md | 13,825 | 14,000 |
| references/probability-toolkit.md | 9,640 | 14,000 |
| references/prediction-market-anchoring.md | 7,470 | 14,000 |

SKILL.md sections against their caps: description 984/1000, Activation 857/900, Plan 1790/1800, Investigate 2388/2400, Synthesize 1461/1500, Gaps 644/700.

**Checks I ran beyond the checker**
- The engine's own loader (`load_library`) parses the skill with no section truncated, and the frontmatter parses as YAML.
- The planner menu cut the mandate's first sentence mid-phrase at its 200-character limit, so I shortened it to fit whole.
- Routing sends seven real use-case questions (EN and ZH) to their domain skill plus this one. A base-rate KIQ is assigned this skill's Investigate text.
- All 38 catalog IDs resolve, and every worked number in the references was recomputed.
- Running the full skill test files without filtering shows failures, all outside this folder: three other authors' in-progress skills (one is missing a reference file) and one router test the lead owns.

**Design choices**
- **Tied to how the engine actually behaves.** I read the code and wrote the skill around what it does:
  - The planner is told to word base-rate questions with "base rate / historically / how often / precedent / 基准率 / 历史先例 / 频率". That wording is what makes the engine route this skill to the question and fetch 30 years of history.
  - A stored series keeps only its newest 240 observations (20 years of monthly data), and its window is fixed on first retrieval. So the skill pushes annual or quarterly series, or an S1 event list, for long counts.
  - A forecast's data anchor settles exactly one completed period. So ever-touch questions are flagged separately from end-state ones, with a rough conversion: touching a level is about twice as likely as ending beyond it.
  - The forecast stage already computes the simple unconditional base rate from stored history. The skill has agents add only what it cannot: counts conditioned on today's situation, and counts from event lists.
  - In v3, markets are collected only after the report is written, so research agents are told not to spend steps on them. Legacy runs the market search once, at the start.
- **Planner.** Scenario weights start from a base rate (or "nothing changes" if none is visible in the scout results). Each adjustment is named and sized at about 5–15 points. Scenarios are split on the decisive variable so the key yes/no forecasts can be read straight off the weights. Each scenario's one-line thesis names its anchor, e.g. "prior: 3 of 11".
- **Research agents.** A quick path first: one comparison class, one long series, one "k of n" count with caveats. Standard and deep depth add a second class and stage-specific rates. Each finding records the series ID, period, unit and threshold. Traps are written as "misreading → what tells them apart".
- **Report writers.** The scenario section gets three tables: base rates; anchor-to-adjustment per scenario; market comparison. The anchor table's last column says only whether the evidence fits the fixed weight or leans higher or lower. That is deliberate: the engine forbids writers from restating their own probability list and rewrites restated weights. The section also maps each key yes/no forecast to the scenarios that imply it.
- **Simulation.** The skill asks for each key actor's track record: how many past deadlines, threats or roadmap dates they honoured, k of n.
- **References.**
  - Base-rate recipes for macro thresholds, policy passage, conflict termination, technology adoption, leader persistence and elections, with US, Chinese and EU primary sources.
  - A probability toolkit with small worked examples.
  - A market-anchoring guide: liquidity tiers, the bias toward overpriced longshots, capital-cost distortion in long-dated markets, overpriced outcome ladders, mapping a market that resolves differently, and the 10-point divergence rule.

**Deliberately left out**
- No current facts, prices or future dates. Historical rates appear only as widely documented priors to verify, with the source named. The most specific: about a dozen US recessions since 1945; the Supreme Court reverses roughly two-thirds of cases it hears; the president's party lost House seats in 18 of 20 post-war midterms but lost control in only 7 of the 12 it went in holding.
- Nothing from the prediction-markets skill (query craft, the market table) or the data-sources skill (retrieval mechanics), and nothing from the deep-research core.
- No series IDs outside the catalog. The NBER recession indicator, for example, is a `data_search` query instead.
- No consultant overhead and no prose copied from newskills/.
- The market liquidity tiers are labelled as house rules of thumb, not measured facts.

I made no git operations and wrote nothing outside the assigned folder.
