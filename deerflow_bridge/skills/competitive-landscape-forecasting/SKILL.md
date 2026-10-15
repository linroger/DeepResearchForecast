---
name: competitive-landscape-forecasting
description: Use for questions about who will lead, rank, dominate, overtake or hold share by a date - firms, AI labs, cloud providers, chip and memory makers, EV and battery makers, platforms, the largest IPOs or most valuable companies, and countries in a technology race (AI, quantum, chips). Triggers - who will lead, which company will be number one, ranking, top 3, market leader, overtake, catch up, dominate, tech race, market share by 2030; 谁将领先, 哪家, 排名, 排行, 格局, 竞争格局, 龙头, 头部, 第一梯队, 领跑, 主导, 赶超, 市占率, 份额, 最大IPO, 市值排名, 中美科技竞争, 到2030年. Adds the leadership contract, dated share baselines, leader-persistence base rates, cited capability evidence, share-shift mechanics and rank probabilities that sum to 100. Not for - market size or adoption by a year (industry-forecasting); present-day industry primers (industry-research); price, valuation or IPO-timing paths alone (financial-markets-forecasting); whether an export control or law happens (policy-and-trade-forecasting).
---

# Competitive Landscape Forecasting

Forecast who leads, ranks or holds share by a date: fix one measurable leadership metric, start from leader-persistence base rates, and depart from them only on cited share-shift evidence.

## Activation

Lead when the question asks who will lead, win, rank, dominate or overtake by a date: firms, labs, platforms, IPO or market-cap league tables, country technology races. Pairings:
- industry-forecasting sizes the market; this skill splits it among contenders and sets the scenario frame;
- financial-markets-forecasting supplies volatility and listing-stage odds for market-cap and IPO rankings;
- policy-and-trade-forecasting decides whether an export control, subsidy or merger approval happens.

The deep-research core already sets source tiers, the evidence ledger and the yield stop. This skill adds the leadership contract, persistence base rates by market type, the contender × dimension evidence table, share-shift arithmetic, rank probabilities derived from the scenario frame, and contender actor facts for the simulation.

## Plan

1. **Leadership contract**, written into KIQ 1 and the theses: metric, perimeter, settling source, period, comparator. "By YEAR" = the YEAR value (flows: calendar year; market cap: last close); "ever overtakes" differs. Multi-criteria (领先, "AI race"): integer weights now; the primary metric breaks ties.
2. **KIQs**, each worded with ranking, leadership or dominance (排名, 领跑) to route this method: data — baseline ranking, 3–5 years of share per contender, one perimeter; data — historical base rate of leadership changes in horizon-length windows, here and in peers; actor — leadership strategy of the top 2–4 contenders and entrants (stated vs revealed); general — share-shift mechanisms behind the ranking (switching costs, capacity, transitions, M&A); actor — arbiters of the ranking (BIS, MOFCOM, SAMR, EC, state funds).
3. **data_needs**: period-average FX (bis:WS_XRU/M.CN.CNY.A, bis:WS_XRU/M.JP.JPY.A; query "Korean won US dollar").
4. **Scenarios**: main ask who leads → this frame leads; size or price ranges go into theses. #1: split on the leader at resolution (incumbent; ≤3 challengers; field/break). Ranking or race: on what reorders it (dominant / duopoly / fragmented; IPOs: which mega-deals list in time). Each thesis names its #1 or "field". Base-rate-first: incumbent-holds starts at its class prior (high: concentrated, scale economies, slow clock; low: platform shift; field ≥10 if nascent or >5 years out), moved only by hard scout facts (overtaking print, export ban, closed merger), not today's order.
5. **Sections**: contract and baseline; contender evidence; dynamics; scenarios + ranking; signposts. **Actors**: contenders, arbiters, pivotal buyers, suppliers. IPO or market-cap tables: "skills": ["competitive-landscape-forecasting", "financial-markets-forecasting"].

## Investigate

**Quick path (≈5 rounds; only the steps this KIQ asks for):**
1. S1 numerator per top contender: the filing's segment line (10-K/20-F; cninfo, SSE/SZSE/BSE, HKEX; DART, MOPS, EDINET), in Chinese and English; convert at period-average FX via data_get. Private labs: model cards, independent evals; revenue and compute REPORTED. IPOs: 招股说明书 stage (受理 → 问询 → 上市委 → 注册 → 发行 → 上市), 拟募资 vs priced proceeds.
2. One denominator: a tracker table (TrendForce, Omdia, Gartner, IDC, Synergy, SNE Research; CAICT, CSIA, CPCA, CAAM, 动力电池产业创新联盟) or exchange statistics. Share = numerator ÷ named total (REPORTED).
3. One search for the strongest challenger case.

**Standard adds:** 3–5 years of share on one perimeter; a persistence count (horizon-length windows where #1 held, with n); capability cells. **Deep adds:** pooled reference class; required catch-up rate; stated-vs-revealed audit; pending M&A and rules.

**Record anchor-ready:** `- <contender> <metric> = <value> <unit, currency>, <period>, perimeter <...>, settling document (filing line, tracker table, exchange list, eval board) [S<n>] (VERIFIED|REPORTED)`; a share, rank or gap you compute: a separate REPORTED finding.

**Capability cells** (capital, compute/capacity, talent, technology, customers, cost, lock-in, regulatory): a dated fact comparable across ≥2 contenders; no scores; empty without evidence.

**Country races:** frontier = best system, not counts; papers/patents: citation-weighted, granted, PCT; budgets: disbursed; compute: energized MW, one precision; state the attribution (HQ vs location).

**Actor facts:** objective (share, margin, state mandate); guided vs cash capex; downturn behaviour; hard constraints (balance sheet, entity list, tools, power); alliances, red lines.

**Traps** (misreading → discriminating observation):
- Revenue-share gain read as a win → unit or bit share and fred:PCU33443344#yoy; price-led gains reverse.
- Benchmark #1 read as leader → independent held-out evals at equal settings; paid usage.
- Announced capacity read as supply → tool move-in, qualification, volume.
- One tracker or segment label read as the market → reconcile perimeters, never average.
- Private round, ARR or fiscal year read as market cap, revenue or calendar year → convert first.

**Stop** when this KIQ's contenders have ≥2 comparable periods, the gap to #1 and the challenger case, as asked; else log the gap.

## Synthesize

Required exhibits (markdown tables of cited facts), each placed once, in the section whose focus matches:
1. **Leadership contract**: metric, perimeter, settling source, period, comparator, weights, tie rule.
2. **Baseline**: contender × last 3–5 years of share or rank, each cell cited, perimeter breaks flagged.
3. **Contender × dimension table**: dated, cited facts read ahead / parity / behind; empty without evidence; no scores.
4. **Tiered ranking**, a table in the scenario section:
   - P(#1) per contender = sum of the canonical weights of scenarios whose thesis names it #1 (field: the rest), summing to 100; list the scenarios summed; split a grouped scenario only on cited evidence;
   - tiers by P(#1): favourite ≥50, contender 15–49, long shot 3–14, field grouped; theses naming no leader: evidence tiers, no P(#1);
   - P(top-k) only when asked: summed weights of scenarios whose thesis puts it in the top k;
   - the persistence base rate (reference class, n) as the start, not today's order; cite every departure.
5. **Challenger paths and kill criteria**: required yearly share gain, or the crossing year T = ln(R_lead/R_ch) / ln((1+g_ch)/(1+g_lead)), vs the fastest swing in the class; kill criteria = metric + threshold + date.
6. **Signposts**: share prints, customer qualifications, guided vs cash capex, rule changes; each with threshold and date.

Label ranks as forecast, consensus or company target. Write no second scenario probability list and change no probability.

## Gaps

- Is the leadership metric fixed with perimeter, settling source, period and tie rule?
- Does every top contender have 3+ years of share or rank on one consistent perimeter?
- Is a persistence base rate computed from a named reference class, with n?
- Does each top contender have stated vs revealed evidence (capex, capacity, pricing, roadmap)?
- Is the strongest challenger's required catch-up rate compared with historical share swings?
- Are export-control, antitrust and subsidy exposures evidenced per contender?
- Is the field (entrant, merger, breakup) covered, not only today's top names?

## References

- [references/leadership-metrics.md](references/leadership-metrics.md): load when choosing or weighting the leadership metric for a market type, or when reconciling trackers, currencies and fiscal years.
- [references/persistence-and-share-dynamics.md](references/persistence-and-share-dynamics.md): load to compute a persistence base rate, model share shifts, consolidation and M&A, or build coherent rank probabilities and kill criteria.
- [references/tech-race-indicators.md](references/tech-race-indicators.md): load for US/China/EU country races in AI, quantum or chips: metrics, pitfalls and Chinese official sources.
