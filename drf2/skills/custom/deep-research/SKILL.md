---
name: deep-research
description: Use this skill instead of a bare web search for ANY question requiring web research. Trigger on queries like "what is X", "explain X", "compare X and Y", "research X", "forecast X", or before content generation tasks. Provides a complete research-tradecraft methodology — question decomposition, advanced search craft, source-quality tiering (S1–S4), evidence grading, triangulation, competing-hypotheses analysis, and forecast-oriented synthesis. Prioritizes high-signal primary and reputable sources; rejects SEO farms and aggregator slop. Use proactively whenever the answer depends on online information.
allowed-tools:
  - web_search
  - web_fetch
  - read_file
  - write_file
  - ls
  - grep
  - glob
  - tool_search
  - kg_search
  - kg_get_entities
  - prediction_market_search
---

# Deep Research Skill

## 1. Mission & Operating Principles

Produce **decision-grade research** — evidence-graded, triangulated, adversarially tested — at the lowest tool cost that achieves it. You are not a search engine summarizer; you are an analyst. The difference is tradecraft:

1. **Evidence over volume.** One regulator filing outranks fifty articles paraphrasing it. Budget is spent on *verification depth*, not search breadth.
2. **Provenance over prose.** Every claim you carry forward has a knowable origin, date, and quality grade. If you cannot say where a fact comes from, you do not have a fact.
3. **Disconfirmation over confirmation.** A conclusion you have not tried to break is a guess. Allocate real budget to the case *against* your emerging picture.
4. **Calibration over confidence.** Say what is known, what is inferred, what is assumed, and what is unknown — separately, and with honest uncertainty language.
5. **Never write from general knowledge alone** — and never let writing begin before the synthesis gate (§11) passes.
6. **No thrashing, no white whales.** An elusive fact/quote/document is worth **at most two attempts** — then record it as a gap and move on. **Never reissue a near-duplicate query**: re-running the same intent with new quotes, a different `site:`/`filetype:`, reshuffled `OR` terms, or a synonym is a *duplicate* — it burns budget and surfaces nothing new. When a result is thin, change the *angle* (a different actor, driver, mechanism, document type, language, or time window), never the wording. Broad coverage of **every** actor and driver in the brief beats fifteen reworded attempts at one quotation.
7. **Sources are real or they are nothing.** Cite only documents you **actually fetched and read**, with their **true URL** and the **date shown on the page**. Never fabricate a source, URL, title, or date from memory; never list a future-dated or hypothetical document as if it were published fact. A "source" with no real fetched URL is dropped. Aim for **wide high-tier coverage** — many distinct S1/S2 origins across regions, actors, and opposing views, not a handful re-cited.

## 2. Phase 0 — Research Design (before any tool call)

Spend one explicit thinking step designing the investigation. Poor design is the #1 cause of wasted budget.

**2.1 Decompose the question** into 3–7 Key Intelligence Questions (KIQs) — the specific sub-questions whose answers compose the final answer. For each KIQ note:

- **Claim type** it needs: established fact · current statistic · causal mechanism · actor intention · estimate/projection · contested interpretation. Each type has a different evidence standard (§6).
- **Likely best source class**: which S1/S2 sources (§4) probably hold the answer — name them before searching ("TSMC capex → their quarterly report"; "US tariff schedule → Federal Register / USTR").
- **Priority**: which KIQs are load-bearing for the conclusion vs. nice-to-have color.

**2.2 Draft the opening query set** (one per KIQ, plus one landscape query). Write queries that would surface *documents*, not commentary, wherever possible.

**2.3 State your priors and what would change them.** One sentence each: what you currently expect, and what evidence would most efficiently prove you wrong. You will deliberately search for the latter in §7.

## 3. Search Craft

### 3.1 Operator toolkit

| Technique | When | Example |
|---|---|---|
| Exact phrase `"..."` | Names, titles, distinctive wording | `"advanced packaging capacity" TSMC` |
| `site:` | Go straight to the authoritative domain | `site:sec.gov 10-K NVIDIA`, `site:stats.gov.cn 半导体` |
| `filetype:pdf` | Reports, filings, academic papers | `semiconductor forecast 2030 filetype:pdf` |
| Exclusion `-term` | Cut dominant noise | `Mirai -toyota` (botnet, not the car) |
| `intitle:` | Documents *about* X, not mentioning X | `intitle:"export controls" semiconductors` |
| Date qualifiers | Pin the time window (§9) | `"price cap" oil December 2025` |
| Entity pivot | Person → org → publications → co-authors | search the *author* of a key report next |
| Citation chase | Find the origin of a repeated claim | search the exact statistic in quotes + earliest date |

### 3.2 Document-type targeting

The fastest route to S1 evidence is naming the document, not the topic: annual/quarterly reports and earnings-call transcripts; SEC/regulator filings (10-K, S-1, 8-K, prospectus); legislative texts, Federal Register notices, comment dockets; court filings and dockets; patent filings; central-bank statements and minutes; statistical releases (with the agency's name); tender/procurement notices; clinical-trial registries; standards documents. Ask: *"what document would contain this answer?"* — then search for that document.

### 3.3 Pivots when results are thin

- **Language pivot**: regional topics → search the local language and local S1/S2 outlets (Chinese: 国家统计局, Caixin/财新; Japanese: Nikkei, METI; German: Destatis, Handelsblatt). Translate the key claim back and verify the translation didn't distort it.
- **Time pivot**: for a changed/deleted page or an older claim, use the Wayback Machine (`web.archive.org/web/*/URL`).
- **Vocabulary pivot**: insiders use different words than outsiders (say "fab utilization" not "chip factory busy"). Adopt the field's jargon from your first good source and re-query with it.
- **Source pivot**: if commentary is all you find, search the names/documents the commentary cites.

## 4. Source Quality Framework

Judge every result BEFORE fetching, and every page BEFORE citing.

### 4.1 Tiers

| Tier | What | How to use |
|---|---|---|
| **S1 — Primary / authoritative** | Original data & documents from the actor or an official body: government statistics, regulator filings, peer-reviewed journals, court documents, earnings reports & transcripts, official texts, primary datasets, direct first-party statements | Preferred for every load-bearing claim. Quote numbers, dates, wording directly. Note: primary ≠ unbiased — a company's own filing is authoritative about its *reported* numbers and its *stated* intentions, not about the truth of its marketing claims. |
| **S2 — High-quality secondary** | Original reporting/analysis with editorial standards and named accountability: Reuters, AP, Bloomberg, FT, WSJ, The Economist, Nikkei, Caixin; top domain trade press; serious research houses (Gartner, TrendForce, McKinsey — commercial angle noted); established think tanks (CSIS, Brookings, Carnegie — ideological lean noted); industry associations (SEMI, SIA, IEA) | Synthesis, context, expert quotes — and as a **pointer back to the S1 origin**. |
| **S3 — Conditional** | Useful but biased, unvetted, or derivative: company blogs/marketing, vendor whitepapers, credentialed-expert blogs/Substacks, conference talks, Wikipedia (a **map to its citations**, never the citation), preprints (not yet peer-reviewed) | Cite only when corroborated by S1/S2, or explicitly attributed ("Company X claims…"). |
| **S4 — Reject** | SEO content farms ("Top 10 X in 2026"), affiliate listicles, AI-generated aggregator slop, wire-reprint sites adding nothing, undated/anonymous pages, forum threads presented as fact, pump sites, citation-less "statistics" portals | **Do not fetch. Do not cite.** Skip from the snippet without spending a tool call. Exception: forums may serve *as labeled sentiment evidence only*. |

### 4.2 Domain map — where S1 actually lives

| Domain | Go first to |
|---|---|
| Macro/economy | National statistics agencies, central banks, IMF/World Bank/BIS/OECD |
| Companies/finance | SEC EDGAR & local equivalents, earnings transcripts, exchange disclosures |
| Tech/semiconductors | Company capex & roadmap disclosures, SEMI/SIA data, TechInsights/TrendForce, export-control texts (BIS rules) |
| Policy/regulation | The bill/regulation text itself, Federal Register & comment dockets, committee testimony |
| Science/medicine | Peer-reviewed journals, clinicaltrials.gov, regulator assessments (FDA/EMA), Cochrane reviews |
| Geopolitics/conflict | Official statements from each side, UN/OSCE-type bodies, ACLED-style event data, named-analyst OSINT with shown evidence |
| Public opinion | Named pollsters with methodology (Pew, Gallup) — never vibes from social media |

### 4.3 Eight signal checks (from the snippet, pre-fetch)

1. Named author/institution with relevant standing? 2. Visible, recent-enough date? 3. Original work or rewrite? 4. Specificity — numbers, names, dates vs. vague superlatives? 5. Methodology/data sourcing disclosed? 6. **Incentive check** — who profits if you believe this? 7. Domain reputation vs. keyword-stuffed domain? 8. Headline–content match?

**≥2 red flags → treat as S4, skip without fetching.**

### 4.4 Evaluating an "expert"

Track record on *this* topic (not fame), methodology shown vs. asserted, conflicts disclosed, willingness to state uncertainty, and whether their past predictions are checkable. A credentialed person speaking outside their field is S3 at best.

## 5. The Evidence Ledger

Maintain a running mental ledger — and in long multi-pass runs, restate it at each checkpoint so it survives summarization:

```
[KIQ-2] TSMC 2026 capex guidance = $52–56B
  src: Q4'25 earnings call transcript (S1, 2026-01-16) + Reuters report (S2, independent? NO — cites the call)
  grade: B1 · status: single-origin, firm · open: split by geography?
```

For each entry track: **claim → sources (tier, date) → independence (different origins or echoes?) → grade → open questions.**

**Grading (Admiralty-style shorthand):** letter = source reliability (A reliable S1 · B usually-reliable S2 · C fair/S3 · D suspect), digit = claim credibility (1 confirmed by independent sources · 2 probable/logical+partially corroborated · 3 possible · 4 doubtful). A load-bearing claim should reach **B2 or better**; anything C3/D-grade either gets upgraded by more research, explicitly flagged, or dropped.

Claim typology matters: a **fact** can be confirmed; an **estimate** needs its methodology and range; a **projection** needs its assumptions; an **intention** ("X plans to…") needs the actor's own words and a feasibility check; a **rumor** stays a rumor however many outlets repeat it.

## 6. Verification Tradecraft

- **Lateral reading.** Don't evaluate a source by reading more *of* it; leave it and search what *others* say about that source/author/institute. Unknown site making big claims → check the site first, not the claim.
- **Triangulation rule.** Load-bearing claims need **two independent origins** (different underlying documents/reporting, not two echoes). State independence explicitly when it matters.
- **Circular-sourcing trap.** Many outlets repeating one striking number are echoing one origin — find it, cite *it*, count it as **one** source. Trace via exact-phrase search + earliest date.
- **Number sanity checks.** Units and magnitude (million vs. billion); growth rates compound — sanity-check a "40% CAGR" against the implied end value; components should sum to totals; currency/real-vs-nominal; per-capita vs. absolute; **definition drift** (two "AI chip market" sizes may define the market differently — say which definition each uses).
- **Dataset hygiene.** Note the data's *as-of* date vs. the article's publication date; check whether a "record high" uses a revised or original series; a 2019 figure in a 2026 listicle is still a 2019 figure.
- **Quote verification.** Striking quotes get checked against the primary transcript/video when load-bearing; paraphrase drift and out-of-context clipping are routine.
- **Manipulation defenses.** Watch for press-release laundering ("study shows" → vendor PR), coordinated narratives appearing simultaneously in low-tier outlets, fake/AI-generated experts, paper-mill journals, preprints touted as proven, hallucinated citations in AI-written content (verify cited sources actually exist before reusing them), and stealth-edited pages (archive-check when wording is disputed).

## 7. Adversarial Analysis

Run these cheaply but explicitly before synthesis:

- **Competing hypotheses (ACH-lite).** For any contested or causal KIQ, list the 2–4 plausible explanations/outcomes and ask of each major piece of evidence: *which hypotheses is this consistent with?* Evidence consistent with everything discriminates nothing. Prefer the hypothesis with the least contradicting evidence, not the most confirming.
- **Key assumptions check.** List the 3–5 assumptions your emerging conclusion rests on ("export controls stay in force", "no demand shock"). For each: what's the evidence, and what's the impact if wrong? Fragile load-bearing assumptions get flagged in the output.
- **Targeted disconfirmation.** Spend dedicated searches on the strongest opposing case: `"[claim] criticism"`, `"[thesis] wrong/skeptics/debunked"`, the bear case to your bull case. Finding nothing *after genuinely looking* is informative; not looking is not.
- **Premortem (for projections).** "It's two years on and this forecast failed — why?" The best answers become risks and indicators in your output.
- **Consensus check.** When every source agrees, ask whether they share one origin or one incentive before treating consensus as evidence.

## 8. Forecast-Oriented Research

When the question is predictive (this pipeline's main case), research for *forecasting inputs*, not just description:

- **Outside view first.** Find the **reference class and base rates**: how often do comparable projects ship on time, mergers clear review, conflicts de-escalate within a year? Search for historical analogues and their outcomes before tuning to case specifics.
- **Actors & incentives.** For each key actor: stated position (their words, S1), revealed behavior (what they *did*), capabilities, constraints, and what they gain/lose under each outcome. Disagreement between stated and revealed is itself evidence.
- **Actor relationship graph.** Map the *directed, typed* relationships between the named actors — who **allies with / opposes / competes with / regulates / depends on / partners with / influences** whom — each with a one-line researched basis. This relationship graph (not just the per-actor profiles) is a first-class output: it seeds the downstream knowledge graph, the personas' social networks, and the simulation's initial follow structure.
- **Drivers & indicators.** Identify the 3–6 variables that actually move the outcome, and for each a **watchable indicator** (a number, decision, or event with a date) that would signal which way things are breaking. These power downstream simulation and monitoring.
- **Trend vs. break.** Establish the trend with data, then research what could structurally break it (policy, technology, capacity limits) — extrapolation and rupture need different evidence.
- **Timeline discipline.** Build the dated sequence of events; causation claims that violate chronology die here.
- **Prediction-market signals.** In DRF-2, fetch related active prediction markets yourself with the `prediction_market_search` tool (Polymarket's public Gamma API — no key required; load the `prediction-markets` skill for query craft and filtering rules), and include a "Prediction Market Signals" section listing each market's implied P(yes). Treat market-implied probabilities as **calibration anchors, not ground truth**: they are the crowd's priced belief at fetch time, they move continuously, and thin markets are noisy. Where your forecast overlaps a listed market, downstream stages will compare the two and expect an explicit rationale for divergences larger than ~10 percentage points. If the tool is unavailable, say the lookup failed (not that no market exists); if it returns nothing, say no active liquid market matched, and continue — never fabricate market prices.

## 9. Temporal Awareness

**Check `<current_date>` (or the run's stated as-of date) before forming ANY time-sensitive query.** Match precision to intent: "today/just released" → month+day+year (`"export rules February 28 2026"`); "this week" → week range; "recently" → month+year; "this year/trends" → year. Never hardcode a remembered year. Year-only queries will not surface today's news. Recency cuts both ways: for stable facts, an authoritative older source beats a fresh low-tier rewrite.

## 10. Budget & Efficiency Discipline

Tool calls are metered per run (`web_search`/`web_fetch` limits). Allocate deliberately: roughly **¼ scoping/landscape · ½ targeted deep-dive & verification · ¼ disconfirmation + gap-filling** — and protect the verification share; it is the first thing sloppy research cuts.

- **Plan, then search.** No near-duplicate queries; a weak result means change the *angle* (entity, document type, language), not the word order.
- **Triage from snippets** with the 8 checks; never fetch S4.
- **Fetch with intent**: each fetch answers a specific named question; **1–3 fetches per KIQ**, on the sources your conclusions will actually rest on. Mine fetched pages' own citations before issuing fresh blind searches.
- **Stopping rules**: a KIQ is done when its load-bearing claims reach B2-grade or you've exhausted plausible source classes (then flag it); two consecutive searches adding nothing new on a dimension → move on; budget low → cut breadth, never verification of what you'll actually assert.
- **Checkpoint** the ledger after each phase/pass; never re-research settled items in later passes.
- **Never loop.** One retry with a changed approach, then route around and note the gap.

## 10.5 Obstacle Playbook

| Obstacle | Move |
|---|---|
| **Paywall** | Never fight it, never guess at the content behind it. In order: (1) find the **underlying S1 document** the article reports on (filing, release, transcript — usually free at the source); (2) wire coverage of the same story (Reuters/AP) or the outlet's free summary/newsletter version; (3) for papers: the **author's open copy** (arXiv, SSRN, university page, Google Scholar "all versions"); (4) an **archived version** (`web.archive.org`). If only the headline/lede is accessible and the claim is load-bearing, cite it flagged as "headline-only — full text unverified" and grade it down; never present a snippet as a read article. |
| **Dead / changed / deleted page** | Wayback Machine; or exact-phrase search the key sentence to find a mirror or the original document. |
| **Conflicting numbers** | Report the range + why (definition, window, methodology, incentive); weight the more independent, more primary source (§12.4). |
| **Thin English results on a regional topic** | Language pivot (§3.3): local-language queries + local S1/S2 outlets; verify translations of key claims. |
| **Only S3/S4 sources exist** | Drop the claim, or carry it explicitly flagged "single low-tier source — unverified". Never launder a weak source by citing it without its tier. |
| **Breaking / rumor-stage story** | Label rumor vs. confirmation; record who reported first and who confirmed *independently*; expect early numbers to be revised. |
| **Tool failure / empty page** | One retry with a changed approach, then route around and note the gap. Never loop. |

## 11. Synthesis Gate

Write only when every box ticks:

- [ ] Every KIQ answered, or its gap explicitly acknowledged?
- [ ] Every load-bearing claim at B2-or-better — or flagged as single-origin/low-grade?
- [ ] Origins traced (no circular sourcing) and key numbers sanity-checked?
- [ ] Genuine disconfirmation attempted, key assumptions listed, competing hypotheses weighed?
- [ ] Dates verified; anything old is labeled with its true date?
- [ ] For forecasts: base rates, actor incentives, and watchable indicators gathered?

Any NO → one targeted pass on that gap only. Do not restart broad searching.

## 12. Output Contract

1. **Layered claims**: distinguish *known* (graded evidence) / *inferred* (your reasoning, shown) / *assumed* (flagged) / *unknown* (stated). Never silently blend them.
2. **Calibrated uncertainty language**, used consistently: "almost certain" ≈ >90% · "likely/probable" ≈ 65–85% · "roughly even" ≈ 45–55% · "unlikely" ≈ 15–35% · "remote" ≈ <10%. Attach the driver of the uncertainty, not just the hedge.
3. **Inline attribution** for every load-bearing claim: source + date (`Reuters, 2026-02-14`; `TSMC Q4'25 call`). **Source list** with URL, date, tier for everything actually used.
4. **Conflicts shown, not averaged**: the range, why sources differ (definition/window/method/incentive), and which you weight and why.
5. **Flags preserved downstream**: single-origin claims, actor self-claims, rumor-stage items, fragile assumptions.
6. **For forecasts**: drivers, scenarios with rough likelihoods, and the dated indicators that would confirm/deny each.
7. **No S4 citations, ever.** If something is only known via S4, it is not known.
8. **Structured handoff (first-class, not just prose)**: make the report explicitly carry (a) the **actor relationship graph** — directed, typed edges between named actors with a one-line basis each (§8); (b) a **situation brief** — current situation, how it got here (context), the forces in tension (dynamics), the 3–6 fault lines actors will argue over, and the catalysts that would shift things; (c) a **source list that carries each source's tier (S1–S4) and date** so the handoff preserves provenance, not just URLs (§4–§5); (d) a **quantitative table** where every load-bearing number carries its **unit, as-of date, and definition** (§6) — a number without those three is not handoff-ready; and (e) the **contested claims** — for each genuine evidence conflict, the disputed claim, the differing positions with their sources, and **why they differ** (§6.4, §12.4), plus single-origin claims flagged as such. A downstream structured-extraction pass converts all of these into the simulation contract (`actors.json`, `sources.json` with tiers, `quantitative.json`, `contested.json`), so they must be unambiguous and grounded in the evidence above. The extraction faithfully carries through whatever you grade and tier — anything you leave ungraded is silently dropped, so grade what you can.

## 13. Failure Modes

- ❌ Searching commentary when a primary document exists (§3.2)
- ❌ Fetching the first pretty result instead of triaging by tier
- ❌ Counting echoes of one report as independent sources
- ❌ Evidence consistent with every hypothesis presented as supporting yours
- ❌ Only searching the confirming side; skipping the premortem
- ❌ "Studies show" without naming the study; quotes without checking the transcript
- ❌ A 40% CAGR cited without sanity-checking the implied end state
- ❌ Citing Wikipedia/aggregators instead of the primaries they point to
- ❌ Presenting a vendor's self-claim as independent fact
- ❌ Burning budget on duplicate queries or retry loops, then skipping verification
- ❌ **Chasing a "white whale"** — 5+ reworded queries hunting one elusive quote/document/number while most of the cast and drivers go uncovered (find it in ≤2 tries or log it as a gap and move on)
- ❌ **Reissuing a near-duplicate query** — same intent, only re-quoted / new `site:` / reshuffled `OR` terms (change the angle, not the wording)
- ❌ **Listing a source with no real fetched URL**, or inventing/guessing/future-dating a source, URL, or date from memory instead of from a page you actually read
- ❌ Narrow coverage — a few sources re-cited across the whole report instead of wide, distinct S1/S2 origins per actor/driver
- ❌ Starting to write before the synthesis gate passes
