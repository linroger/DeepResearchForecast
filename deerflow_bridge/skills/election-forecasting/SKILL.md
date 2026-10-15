---
name: election-forecasting
description: Use for forecasts decided by voters or an electing body - US midterms and general elections, control of the House, Senate or a state legislature, Senate, House and governor races, special elections and primaries, presidential approval as an electoral driver, referendums, party leadership and speaker contests, and non-US parliamentary or presidential elections with seat projection and coalition or government formation. Triggers - election, midterms, who wins, House or Senate control, majority, seats, swing states, generic ballot, approval rating, polls, runoff, recount, referendum, coalition, prime minister; 选举, 中期选举, 大选, 众议院, 参议院, 国会控制权, 多数党, 席位, 摇摆州, 民调, 支持率, 公投, 党魁选举, 组阁, 执政联盟, 联合政府. Not for - laws or policy after the vote (use policy-and-trade-forecasting); Chinese leadership succession, coups or regime stability (use geopolitical-forecasting); market reactions to an election (use financial-markets-forecasting).
---

# Election Forecasting
Forecast who wins and who controls: a resolvable control rule, a base-rate-first prior from the seat cushion, fundamentals from official series, polls with their error, race structure, markets as non-independent anchors, and path-to-majority arithmetic with correlated errors.

## Activation
- Use when voters or an electing body decide the outcome: a race, chamber control, a referendum, a leadership ballot, or who governs after a vote. Always pair with reference-class-forecasting.
- Route elsewhere: legislation after the vote → policy-and-trade-forecasting; regime stability, coups, Chinese leadership transitions (换届, 党代会) → geopolitical-forecasting; asset moves → financial-markets-forecasting.
- Adds to the research core: resolution conventions (certification, runoffs, VP tie-break, caucusing independents), the cushion-versus-history prior, fundamentals from catalog series, multi-aggregator polling with error priors, ratings and markets as anchors, path-to-majority arithmetic with a shared national error, and actor facts for the simulation.
- Pre-screened races: forecast the vetting, then the race among approved candidates (turnout and margin only if one is viable).

## Plan
KIQs (6–9):
- **data, fundamentals**: the economy voters feel; data_needs fred:UNRATE, fred:CPIAUCSL#yoy, fred:DSPIC96#yoy.
- **general, base rate**, worded "Historically, how often…": the in-party's midterm seat change versus its cushion, by approval band, with n (prior to verify: House losses in every post-war midterm but 1998 and 2002).
- **data, polls**: approval and generic-ballot averages, 2+ aggregators, LV/RV, past poll error.
- **general, structure**: ratings, open seats, retirements, maps in force, specials, FEC money.
- **general, path to majority**: thresholds, holdovers, tipping House seat and Senate race.
- **actor**: president, party leaders and committees, super PACs, tipping-race candidates, election officials, courts, voter blocs.
- **general, anchors**: market prices with rules; model outputs.

Non-US: seat projection and coalition arithmetic replace structure and path; presidential: add the tipping-point state.

Sections: Fundamentals; Polls; Races; Path to majority (scenario: true); Actors; Signposts.

Scenarios:
- **Two chambers**: the four control combinations, e.g. "D House + R Senate".
- **One race**: each viable winner, plus "unresolved at deadline" if a runoff or recount can outlast it.
- **Non-US**: single-party majority; A-led coalition; B-led coalition; minority government or repeat election.

Weights, base rate first:
1. Chamber prior = share of reference midterms where the in-party lost more than its cushion (House: seats − 218; Senate: seats − 50, given exposure in states the other party carried).
2. Shift toward liquid markets and polls near the vote.
3. One national swing drives both chambers: splits get less than independence implies.
4. No outcome below 2; keep all four chamber combinations (signposted tails, never merged).

## Investigate
**Quick path (≤5 rounds).**
1. data_get fred:UNRATE, fred:CPIAUCSL#yoy, fred:DSPIC96#yoy, start 30 years back; note values before past midterms.
2. Fetch approval and generic-ballot averages from two aggregators: value, population (A/RV/LV), window, as-of date.
3. Fetch the party division (Clerk of the House, Senate.gov) and one rater's ratings; compute cushion and seats needed.

**Standard adds:** the midterm seat-change table (American Presidency Project or Brookings) with n; a second rater; Polymarket, Kalshi, PredictIt prices with rules and volume; special-election margins versus district partisanship; maps in force; retirements.

**Deep adds:** tipping-race polls with house effects and LV/RV; FEC cash on hand, independent expenditures; early vote versus the same mode last cycle.

**Chinese prompts:** English or local S1 for foreign races; Chinese queries for Taiwan (中選會) and coverage.

**Record:**
- Margins as D−R points (or name the parties) with population, field dates, aggregator, source; model probabilities and own seat arithmetic are REPORTED.
- Fundamentals anchors: series ID, observation month (YYYY-MM-01), unit, threshold, whether the print precedes Election Day.
- Outcomes resolve on certified results: name the certifying body, control rule and date convention.
- Actors: revealed moves (spending, retirements); blocs: share, lean, turnout, trend.

**Traps (misreading → discriminating observation):**
- 50–50 Senate goes to the momentum party → the VP's party breaks ties; independents count by caucus.
- Generic-ballot lead = House win → compare the median seat's partisanship (map bias).
- Rating = probability → a category; use the rater's hit rate.
- Race probabilities multiply → a shared national error; toss-ups break together.
- Special-election swing = November → check turnout versus the last midterm.
- Money lead = votes → money follows competitiveness; reservation cuts reveal private polling.
- Early-vote lead = margin → compare the same mode last cycle.
- Market, model and rating agree → one evidence family (same polls); check market rules, volume, long-dated pull toward 50.
- Same district number = same district → check the map in force.
- Media call = result → recounts, runoffs, ranked-choice rounds, certification.

**Stop** once cushion arithmetic, two dated averages and a ratings distribution are in hand, or at yield stop.

## Synthesize
Required exhibits, as markdown tables of cited facts:
1. **Fundamentals**: indicator; series ID or source; latest value and period; 1-year change; value before past midterms; direction for the in-party.
2. **Dated polling averages**: measure (approval, generic ballot, tipping races); aggregator; value; population; window; as-of date; 30-day change.
3. **Ratings distribution**: rater and date; Solid/Likely/Lean/Toss-up counts per party; toss-ups the trailing party needs.
4. **Path to majority**: chamber; control rule; seats held or holdover; safe plus likely; still needed; tipping race, margin; market price, venue, date.
5. **Signposts**: indicator; reading and date; threshold; window; scenario moved; false-signal risk (special elections, generic-ballot shifts held 2+ weeks, retirements, rating changes, reservation cuts, economic prints).

Non-US: seat-projection and coalition tables replace 3–4.

Actors: principals' goals, levers, revealed moves; voter blocs' share, lean, turnout, trend.

Conventions:
- Control means a majority under the chamber's rule on the resolution date: House 218 of 435; Senate 51, or 50 plus the VP; independents counted by caucus.
- Results are certified, not called; flag runoffs or recounts that delay it.

Label forecasts, model outputs, ratings and prices distinctly.

Per scenario: the national environment it needs, the races that must break, falsifiers. Do not list scenario probabilities, invent poll numbers or go past the cycle asked.

## Gaps
- Is the control rule explicit: threshold, VP tie-break, caucusing independents, vacancies, called versus certified, runoff timing?
- Are approval and generic-ballot averages from 2+ aggregators dated, with population (LV/RV)?
- Is there a midterm base rate against the seat cushion, with source and n?
- Do ratings from 2+ dated raters cover every competitive seat?
- Is there a path-to-majority table naming the tipping-point race, with correlated error handled?
- Are the maps in force verified (redistricting, litigation)?
- Are market prices recorded with volume and checked against the resolution rule?
- Is actors' revealed behaviour (spending, retirements, reservations) evidenced?

## References
- [references/fundamentals-and-polls.md](references/fundamentals-and-polls.md): load for fundamentals models, poll aggregation, house effects, error priors, votes-to-seats and the correlated-error method.
- [references/us-election-mechanics.md](references/us-election-mechanics.md): load for chamber rules, calendars, certification, recounts, runoffs, redistricting, ratings, money and actor classes.
- [references/non-us-elections.md](references/non-us-elections.md): load for parliamentary and proportional systems, seat formulas, coalitions, referendums, leadership contests and polling quality by region.
