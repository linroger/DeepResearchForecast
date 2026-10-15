# Escalation and negotiation analysis

Load for escalation, red-line, bargaining, mediation and sanctions-coercion KIQs, and for scenario and binary design. Methods and indicator types only: fetch current positions yourself.

## 1. Escalation: dimensions and a generic ladder

Classify each escalation by:
- **direction**: vertical (intensity, weapon class, target class), horizontal (new territory, new state belligerents) or temporal (duration);
- **intent**: deliberate; inadvertent (a strike on an asset the other side reads as strategic, such as early warning or command and control); accidental (an air or sea incident).

Generic ladder; every rung is observable:

| Rung | Observable markers | Typical S1/S2 evidence |
|---|---|---|
| R0 diplomatic | ambassador recalled, embassy "ordered departure", travel advisories, flights suspended | MFA notices, State Department advisories |
| R1 coercive signal | named exercises, deployments, alert or doctrine statements, sanction threats | MoD releases, NOTAM and NAVAREA warnings, imagery |
| R2 gray zone | cyber attacks, sabotage, proxy attacks, maritime harassment, airspace incursions | attributions by governments, ACLED, ship tracking |
| R3 limited direct force | one-off, often pre-signalled, retaliatory strikes | both sides' statements, imagery, FIRMS fire detections |
| R4 sustained campaign | daily strikes or ground operations in the theatre | ACLED or UCDP weekly counts, map series |
| R5 strategic targets | strikes on homeland energy, ports, leadership; blockade or closure declared | operator notices, IMF PortWatch transits, prices |
| R6 widening | a new state belligerent; attacks on a patron's forces or territory | official acknowledgement, alliance consultations |
| R7 nuclear | readiness changes (dispersal, warheads leaving storage), then use | government statements, imagery; rhetoric alone is R1 |

Mark de-escalation rungs just as concretely: a hotline used, envoys received, prisoner exchanges, withdrawal from forward positions, an exercise ended early or a closure zone lifted, sanction waivers, flights or shipping resumed, war-risk premiums falling.

## 2. Theatre indicator sets (types, not current facts)

- **Russia-Ukraine and NATO:** patron permissions on weapon range and target class; long-range strikes on refineries, ports and the grid; mobilization decrees and recruitment-bonus changes; third-country troops on either side; drones or missiles entering NATO airspace and NATO consultations; nuclear signalling (doctrine revisions, exercises with non-strategic weapons, deployments to an ally).
  - Energy channel: imf:PCPS/G001.PNGASEU.USD.M and imf:PCPS/G001.POILBRE.USD.M. Grain: imf:PCPS/G001.PWHEAMT.USD.M.
- **US or Israel and Iran:**
  - proxy attacks on forces and shipping → direct exchanges → strikes on nuclear sites → attacks on Gulf energy infrastructure, or harassment or closure of Hormuz → regime-targeting aims.
  - Nuclear thresholds come from IAEA Board and Director General reports: enrichment level, stockpile, whether inspectors keep continuity of knowledge, and any NPT withdrawal notice (Article X requires three months' notice).
  - Channels: Hormuz transits (IMF PortWatch), tanker war-risk premiums, daily Brent quotes for event windows (stored fred:DCOILBRENTEU is monthly), imf:PCPS/G001.PNGASJP.USD.M for the Gulf LNG link, and fred:GASREGW for the US domestic pump-price constraint.
- **Taiwan Strait:** gray-zone counts (Taiwan 國防部 daily aircraft and vessel reports, median-line crossings) → named large exercises announced by 东部战区 → coast-guard "law-enforcement" inspections, i.e. a quarantine → declared closure zones or a blockade → strikes → an amphibious assault.
  - What separates signalling from preparation: how long and how large closure areas are; requisition of civilian RO-RO ferries; blood and medical stockpiling; reservist call-ups; fuel stockpiles; cancelled leave; financial sanctions-proofing. Watch US and Japanese responses (transits, Japan Joint Staff releases).
- **Korean peninsula:** ICBM or nuclear tests are signals; the long record of tests without war is the persistence prior.
- **Coups and regime stability:** elite defections, unpaid security forces, officer purges; leader health and an unclear succession; protest scale against repression capacity, and whether security forces refuse orders; a currency collapse or inflation spike (`data_search` "consumer price inflation" or "exchange rate" with the country). Scheduled succession (congress, plenum): resolve on the official communiqué; watch personnel moves, age norms.

## 3. Thresholds that resolve

Write every signpost as: indicator, source, current reading and date, threshold, window, direction (escalation or de-escalation), the scenario it moves, false-signal risk.

A threshold must be observable: a count above its trailing 90-day maximum; a published legal act (decree, gazette notice, UNSC resolution); a named deployment confirmed by two origins; a price level on a stored series in a stated month; a percentage fall in chokepoint transits against a 30-day baseline; an IAEA-reported quantity.

Never write "tensions rise" or "talks progress".

## 4. Red lines and credibility

Keep a red-line ledger. For each declared line record who declared it, the verbatim wording in the original language, the date, whether it is explicit or ambiguous, whether and when it was crossed, the response within 30 and 90 days, and whether that response was proportionate.

Rate each line **enforced**, **partly enforced** or **not enforced**. Rules:
- Ambiguity is often deliberate (strategic ambiguity). Do not convert an ambiguous red line into a precise threshold.
- Credibility comes from costly acts: mobilization, sunk deployments, legislated commitments, public commitments that create audience costs (Fearon, 1994). Words alone are cheap talk.
- Rate each rung separately. A record of lower-rung lines crossed without response does not discount the top rungs (regime survival, nuclear use).
- Record salami tactics (many crossings each below the threshold) as a pattern.
- Schelling's "threat that leaves something to chance": crises raise accident risk, so keep an inadvertent path in the widened-war scenario.

## 5. Bargaining-model cues: why wars go on and how they end

Use Fearon's (1995) rationalist causes of war as a checklist, each with cues that it is being resolved.

1. **Private information with incentives to bluff.** Fighting continues until the battlefield reveals the balance. Cues that expectations are converging (Slantchev; Reiter, How Wars End): both sides publicly shrink their war aims; offensives culminate without breakthrough; victory claims fade from official rhetoric; the front barely moves for months.
2. **Commitment problems.** Each side fears the other will use a pause to rearm, or will be stronger later. This is the main obstacle in territorial wars. Cues that it is being solved: concrete guarantee designs (who guarantees, with what forces, under what trigger, for how long); demilitarized-zone and monitoring proposals; an agreed sequence of withdrawal against sanctions relief. Without these, keep the ceasefire weight low even when talks exist.
3. **Indivisible issues** (sovereignty, regime survival, sacred sites). Cues that the issue is being reframed: language separating de facto control from de jure recognition; clauses deferring final status; referendum formulas.

Other drivers:
- **Ripeness** (Zartman): a mutually hurting stalemate plus a perceived way out. Measure the hurt (loss trends from one consistent source, energy revenue, inflation, aid fatigue), the stalemate (rate of map change) and the way out (a formula both sides have publicly engaged with).
- **Time preference.** Which side believes time is on its side? Look at economic runway, manpower pool, production trend, patron elections and budget cycles, and the sanctions trajectory. The side that expects to gain will delay.
- **Domestic constraints** (Putnam's two-level game). The win-set is set by ratification rules (legislature, referendum, constitutional bars on ceding territory), hardliners and coalition partners, polls on concessions, and the leader's personal risk after leaving office.
- **Spoilers** (Stedman): limited, greedy or total spoilers, inside or outside the process, including proxies with their own agendas. A total spoiler with the capacity to act puts a tripwire on any settlement scenario.

## 6. The actor matrix for negotiation and for the simulation

For each principal, patron, mediator and domestic veto player record:

| Field | Content | Evidence rule |
|---|---|---|
| goal | minimum acceptable vs maximal aim, with horizon | dated official texts; revealed behaviour beats words |
| red line | verbatim, with its credibility rating from the ledger | see section 4 |
| leverage | what it can give or withhold: territory, guarantees, arms, money, energy, sanctions relief, UN vote or veto | S1 acts, flows |
| constraint | military capacity, economy, ratification, patron dependence, legal limits | data series, polls, constitutional text |
| BATNA | expected value of no deal: battlefield trend, external support, economic runway | sustainability KIQ |
| decision rights | who can sign, who must ratify, who can veto | constitutional or organizational rules |
| time preference | gains or loses from delay | see section 5 |

ZOPA test: a deal exists only if reservation points overlap; if not, the frame stays on continuation or a frozen line until a BATNA moves. Name what would move each BATNA (an aid cut-off, an offensive breakthrough, an oil-price collapse, sanctions relief) and turn each into a signpost.

Make anyone who can block a deal (a P5 member with a UNSC veto, a parliament, an armed spoiler) a separate actor with explicit incentives for the simulation.

## 7. Negotiation stages: evidence and misreadings

| Stage | Evidence it is reached | Common misreading |
|---|---|---|
| 1 back channel | credible reports of envoy contacts (REPORTED) | "talks" in a headline read as negotiations |
| 2 talks about talks | format, venue, participants and agenda announced by both sides | a mediator's announcement alone |
| 3 partial deals | prisoner exchanges carried out; corridors, grain or energy moratoria in force | a partial deal read as a ceasefire |
| 4 framework | text published, or confirmed by both principals | leaked drafts; a one-sided "points" plan |
| 5 ceasefire agreement | signed text with line, timing and monitoring; monitors deployed | "agreed in principle"; a unilateral pause |
| 6 settlement text | signed by authorized signatories | initialled read as signed |
| 7 ratification | gazette or vote record; referendum held | signature read as final |
| 8 implementation | withdrawals, exchanges, sanctions relief, demobilization verified by monitors or imagery | announcements |
| 9 durability window | event counts below threshold for w days | the first quiet week |

Movement rules: one stage advanced moves weight modestly; stages are rarely skipped, so "deal close" without stage 2 to 4 evidence moves nothing; regression (talks suspended, a delegation recalled) is common and must be recorded.

## 8. Mediators

Classify the mediator's role: **facilitator** (venue, messages), **formulator** (drafts texts) or **manipulator** (brings leverage: aid, sanctions, guarantees, forces). Then track its own interest, whether both parties accept it, rival mediators competing for the role (forum shopping), and whether it can guarantee implementation.

Mediator optimism is an interested claim (REPORTED). A patron-mediator can deliver its client, but the other side may reject it as guarantor.

## 9. Sanctions used as coercion

- **Name the aim** and forecast each separately: signal, constrain capability (deny revenue or technology), or compel a change of policy.
- **Follow the chain**, with evidence at each link rather than the announcement: designation → enforcement (secondary sanctions, vessel designations) → physical flows (volumes, buyers, discounts) → fiscal and currency effects → elite and policy response.
- **Check for evasion**: shadow fleets and ship-to-ship transfers; transshipment through third countries, visible in partners' mirror statistics; gaps in price-cap attestation.
- **Relief as a bargaining chip** buys concessions only if credible: executive sanctions lift quickly, statutory ones are hard to lift (weaker offers); snapback clauses and step order decide whether the target trusts relief.
- **Chokepoints:** distinguish harassment from closure; evidence is transits (IMF PortWatch), rerouting, cancelled insurance cover, canal-authority statements. A price jump with no fall in volumes is a risk premium, not a supply loss.

## 10. Scenario and binary design

- **Scenarios** take one axis, the state on the horizon date; classify each world by the first that applies: decisive outcome > widened war > settlement in force > ceasefire or frozen line > continued fighting. Define each by an observable state, never by intent.
- **Binary templates** (numbers from fetched evidence):
  - A front-wide ceasefire is in effect on D and has held N days, with ACLED battle events below K per week.
  - Both governments sign a written agreement by D, published by a party or the UN.
  - X strikes Y's territory between D1 and D2, acknowledged by X or confirmed by two independent origins.
  - Brent monthly average (imf:PCPS/G001.POILBRE.USD.M) is at least T USD/bbl in month M (data-anchored: the series must be stored).
  - EU natural gas monthly price (imf:PCPS/G001.PNGASEU.USD.M) is at most T USD/MMBtu in month M.
- **Mapping:** P(E) = Σ over scenarios s of P(s) · P(E | s). A binary is derivable from the scenarios only when the partition fully decides it; then list its YES scenarios.
- **Consistency checks:** implemented ≤ signed ≤ framework; an earlier deadline is never likelier; a partial deal never resolves a full-ceasefire question.
