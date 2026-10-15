---
name: geopolitical-forecasting
description: Use for forecasts of wars and their end-state or timing, ceasefires, armistices and peace deals, escalation and military operations, invasions and blockades, interstate crises (Russia-Ukraine, US-Iran or Israel-Iran, Taiwan Strait, Korean peninsula), chokepoints (Hormuz, Red Sea, Black Sea), coups and regime stability, and sanctions used as coercion. Triggers - war end, ceasefire, peace talks, frozen conflict, escalation, red line, nuclear threat, mobilization, offensive, territorial control, blockade, coup, regime collapse, succession, sanctions pressure; 战争, 停火, 停战, 和谈, 和平协议, 战争结束, 冲突升级, 入侵, 封锁, 台海, 俄乌, 美伊, 伊朗核问题, 霍尔木兹, 政变, 政权更迭, 换届, 接班, 制裁施压. Not for - elections or approval (election-forecasting); how a tariff, export control or sanction is legally made, litigated or measured in trade data (policy-and-trade-forecasting); oil or gold price targets alone (financial-markets-forecasting); macro outcomes (macro-research). Pair with reference-class-forecasting for base rates.
---

# Geopolitical Forecasting
Turn conflict and crisis questions into resolvable outcomes, base-rate-first scenario frames, graded state-of-play evidence and actor facts the simulation can play. Belligerent words are claims; signed texts, physical flows and independently verified events are evidence.

## Activation
- Use when the outcome is a security event or state: war termination or timing, a ceasefire, armistice or settlement, escalation or widening, a military operation, a blockade or chokepoint closure, a coup, regime collapse or non-electoral succession (换届, 接班: resolve on the official appointment record), or sanctions meant to coerce a state.
- Route elsewhere: elections → election-forecasting; the legal making, litigation or trade measurement of sanctions, tariffs and export controls → policy-and-trade-forecasting; a price path alone → financial-markets-forecasting. Always pair with reference-class-forecasting.
- Adds to the research core: resolution definitions for conflict outcomes, conflict reference classes, escalation ladders and red-line credibility, negotiation-stage tracking, evidence grading under information war, and the actor matrix the simulation needs.

## Plan
1. **Resolve** a dated state or event ("ceasefire in effect on D, held 30+ days"): **ceasefire** (fire halted; may be partial, unilateral), **armistice** (signed military accord: line, monitoring), **peace agreement** (signed settlement), **frozen conflict** (no deal; fighting below a set threshold); say partial or full, signed or in force.
2. **KIQs:** general: state of play (control, front, talks); data: sustainability (manpower, munitions, aid, budgets, energy revenue, sanctions bite); general, worded "Historically, how often…": duration, termination type, ceasefire durability; actor: each principal, patron, mediator; general: talks, escalation thresholds, red-line record.
3. **actors:** leaders, security organs that may diverge, patrons, mediators, veto players.
4. **data_needs** (≤3 per KIQ): energy imf:PCPS/G001.POILBRE.USD.M, imf:PCPS/G001.PNGASEU.USD.M; grain imf:PCPS/G001.PWHEAMT.USD.M; war economy query "military expenditure percent of GDP" per belligerent. Only stored series anchor binaries.
5. **Sections:** state of play; actors and red lines; sustainability; talks; scenarios (scenario: true); signposts.
6. **Scenarios: one axis, the state at the horizon,** first match wins: decisive outcome > widened war > settlement in force > ceasefire or frozen line > continued fighting. US-Iran: sustained war > limited strikes > deal > managed standoff; Taiwan: combat > blockade or quarantine > gray zone. "When": split the end-state by window (by D1, by D2, later) by class hazard given elapsed time.
7. **Weights base-rate-first:** status quo = 1 − class hazard of change by the horizon; shift to agreement only on scout stage evidence (signed text > framework > talks); decisive and great-power or nuclear escalation stay single digits unless a threshold is crossed.
## Investigate
**Quick path (≈5 rounds):**
1. Note the resolution term and what observation meets it.
2. Fetch the act itself (S1): agreement text, decree, UNSC or IAEA document, sanctions notice, transcript; then the other side's position.
3. Corroborate independently: ACLED/UCDP events, one map series throughout (ISW/CTP), imagery or geolocated OSINT, ship tracking, IMF PortWatch.
4. data_get planned series; record latest value and 12-month range.

**Standard:** capacity ledgers (Kiel Ukraine Support Tracker, SIPRI, IISS, finance-ministry oil revenue) and the mediator. **Deep:** prior rounds and red lines; domestic polls (KIIS, NCCU, Pew/Gallup; Levada with repression caveat); 30-year data_get history for past shocks.

**S1 classes:** belligerent presidencies, MFAs, MoDs, gazettes (proof of what they say and sign, not of results); UNSC records, OHCHR verified counts, IAEA reports; OFAC, EU Official Journal; congressional votes. China: 外交部, 国防部, 国台办, 商务部, 东部战区; Taiwan 國防部 daily PLA reports, 陸委會; Japan Joint Staff. Search Chinese, English and belligerents' languages.

**Record:** side (A, B, neutral, OSINT); event vs report date; stage (announced, signed, in force, implemented); independence group. VERIFIED needs two independent origins or the S1 text of the act; casualty, loss, interception and capture claims are REPORTED. **Anchors:** series ID + period + unit + candidate threshold; for events, the settling source (UN document, gazette, ACLED monthly count).

**Actor KIQs:** goal (minimum vs maximal), verbatim red line + enforcement record, leverage, constraints (economy, patron, ratification), time preference, stated vs revealed.

**Traps (misreading → discriminating observation):**
- talks announced → deal near: principals present, written text, preconditions dropped
- ceasefire declared → holding: reciprocal acceptance, monitors, 2-4 weeks of event counts
- village captured → control changed: geolocation or rival admission, same map series
- aid announced → delivered: appropriated → obligated → delivered
- sanctions round → pressure: export volumes, discounts, budget revenue
- red line stated → enforced: past crossings and responses
- exercise → attack: reservists, fuel and blood stocks, sealift, closure duration

**Stop** once the resolution state has two origins (or is flagged single-origin), the other side is fetched and an anchor is recorded.

## Synthesize
- Open with the definitions used: term, operational test, durability window, settling source. "By D" means it happened on or before D; "on D" means the state holds on D.
- Required tables, cited facts only:
  - **State of play**: dimension | latest reading | as-of | source side | tag.
  - **Actor matrix**: actor | goal (minimum vs maximal) | red line | leverage | constraint | evidence.
  - **Negotiation track**: stage reached | date | parties present | text status.
  - **Signposts** (mobilization, deployments, aid packages and votes, sanctions rounds, energy flows and prices, envoy visits, rhetoric shifts): indicator | direction | threshold | current reading | window | scenario it moves.
  - **Base rates** (merge with any reference-class table): reference class | n | prior | source class.
- Attribute every belligerent number to its side. Never present casualty or loss totals as fact; give ranges with each method.
- Per canonical scenario: causal path, the bargaining condition it needs (converging expectations, credible guarantees, a divisible issue), stage evidence, tripwires.
- Label a forecast, a belligerent's stated aim and a mediator's plan differently.
- Phrase checkable outcomes as actor + act + threshold + date + settling source; price channels on the stored series with period and unit.
- Close with "what would change the view": 3-5 observable events and their direction.

## Gaps
- Is the resolution term defined with durability window and settling source?
- Is there a base rate with named reference class (interstate/civil, great-power role, time elapsed) and n?
- Does each principal, patron and mediator have dated goal, red line, leverage, constraint?
- Is territorial control from one map series or event dataset, claims tagged REPORTED?
- Is the negotiation stage evidenced (talks about talks, framework, signed, implemented)?
- Is sustainability evidenced (production, recruitment, aid, budget or energy revenue)?
- Do signposts carry thresholds and dates; was the red-line record checked?
- If an energy or grain channel exists, is its price series stored?

## References
- [references/conflict-base-rates.md](references/conflict-base-rates.md): base-rate KIQs and scenario weighting (datasets, reference-class choice, duration, termination and ceasefire-durability priors, hazard arithmetic).
- [references/escalation-and-negotiation.md](references/escalation-and-negotiation.md): escalation, red-line, bargaining, mediation and sanctions-coercion KIQs; scenario and binary design.
- [references/evidence-under-information-war.md](references/evidence-under-information-war.md): grading belligerent, OSINT, casualty, territory, strike and shipping evidence.
