# Non-US elections

Load this for parliamentary, proportional and two-round systems, seat formulas, coalition and government formation, referendums, leadership contests and polling quality by region.

Electoral rules change. Verify thresholds, seat totals and formulas with the election authority for the election in question. Economic series for other countries are listed in [fundamentals-and-polls.md](fundamentals-and-polls.md) §2.

## 1. First checks, in order
1. **What resolves the question**: votes, seats, the head of government, or a formed government? An election result is not a government. Write the date convention: results declared, parliament constituted, or PM appointed or invested.
2. **How the executive is chosen**: directly (presidential, often two-round); by parliament, with or without an investiture vote; or semi-presidential.
3. **Seat formula**: thresholds and district magnitude decide the projection method (§2).
4. **Party system**: fragmentation, pre-electoral alliances and declared red lines (cordons sanitaires).
5. **Polling**: quality, blackout rules, and who publishes seat projections (§6).
6. **The official results body** (§8).

## 2. Systems and seat projection

| System | Examples (verify current rules) | Projection method | Trap (misreading → discriminating observation) |
|---|---|---|---|
| First-past-the-post | UK, Canada, India's Lok Sabha | Uniform or regional swing applied seat by seat to the last result; MRP projections (S2); adjust for tactical voting | "A national lead is a majority" → vote efficiency decides: concentrated regional parties win seats on small shares. Count the seats within ±5 points of the swing line |
| Two-round | France (legislative and presidential); many presidential systems | First-round projection plus a transfer matrix from second-preference questions. In French legislative races, round two takes the top two plus anyone with 12.5% of registered voters (verify); presidential runoffs are the top two. Candidates withdraw before round two | "The first-round leader wins" → model the transfers and the abstention between rounds |
| Preferential (alternative vote) | Australia's House | Two-party-preferred (2PP) from primary votes, using the last election's preference flows | "A primary-vote lead wins" → 2PP decides, and preference flows shift |
| Single transferable vote | Ireland, Malta, Australia's Senate | Droop quota = floor(valid votes / (seats + 1)) + 1, then transfers | "First preferences are seats" → transfers decide in multi-member districts |
| List PR | Netherlands, Israel, Spain, Sweden, Turkey | Apply thresholds, then allocate by the stated divisor (D'Hondt or Sainte-Laguë) district by district | "1 point is 1% of seats" → threshold cliffs and small districts (Spain's provinces) create jumps |
| Mixed-member proportional | Germany, New Zealand | The list vote sets each party's proportional seats; constituency wins fill them. Watch overhang (New Zealand), threshold exceptions and Germany's 2023 reform, under which a constituency win may go unseated (verify) | "Constituency wins are seats" → the list vote decides; check the exceptions |
| Parallel or mixed | Japan, South Korea, Taiwan, Mexico, Italy | Project the district and list tiers separately, then add. Watch dual candidacy and satellite lists | "The list tier compensates" → in parallel systems it does not (South Korea's is partly compensatory: verify) |

**Hypothetical divisor example.** 5 seats; votes A 46k, B 30k, C 24k.
- **D'Hondt** (divisors 1, 2, 3, …): quotients A 46, 23, 15.3; B 30, 15; C 24, 12. The five largest are A 46, B 30, C 24, A 23, A 15.3, so A 3, B 1, C 1.
- **Sainte-Laguë** (divisors 1, 3, 5, …): A 46, 15.3, 9.2; B 30, 10; C 24, 8. The five largest give A 2, B 2, C 1.
- Same votes, one seat moves. Record the formula (including modified first divisors), the district magnitude and the threshold.

**Majorities.**
- Majority = floor(N/2) + 1 of the statutory size N.
- The effective majority is lower when members do not vote. In the UK, the Speaker and deputies do not vote, and Sinn Féin MPs do not take their seats.

## 3. Government and coalition formation

**Arithmetic.**
1. **List** every coalition that reaches the investiture rule. Rules differ: an absolute majority; a simple majority; or merely not being opposed by a majority (negative parliamentarism, as in Sweden).
2. **Keep** minimal winning coalitions, in which every member is pivotal. Prefer connected ones (adjacent on the main left–right dimension, after Axelrod) and those with fewer parties.
3. **Drop** coalitions that break a declared red line or a pre-election pledge. Record the evidence for each red line and how credible it is, given past behaviour.
4. **Find the pivotal (median) party**: it bargains hardest. Among partners, portfolio shares track seat shares (Gamson's law, a documented regularity).
5. **Minority governments** with confidence-and-supply deals are common in Scandinavia and in hung FPTP parliaments (Canada).

**Base rates** (verify with ParlGov or ERDDA; use the country's own history, not a cross-country average):
- Single-party majorities are rare under PR.
- The largest party usually leads the government, but not always.
- Formation time ranges from days to well over a year: Belgium's 2010–11 formation took more than 500 days.
- Repeat elections follow failed formations: Spain in 2015–16 and 2019; Israel held five elections in 2019–2022.

**Process signals.** The head of state appoints an informateur or formateur → exploratory talks → formal negotiations → signed coalition agreement → party approvals (member ballots in some German parties) → investiture vote → swearing-in.
- A signed agreement is not a government; a caretaker government stays in office meanwhile.

**Confidence rules.**
- A constructive vote of no confidence needs a named successor (Germany, Spain).
- The power to call a snap election sits with the PM or the head of state, depending on the constitution.

## 4. Leadership contests and transitions without a general election

**Rules.** Fetch the party's current rules: who votes (MPs, members, affiliated organizations), nomination thresholds, ballot rounds and timetable. Examples:
- UK Conservatives: MP ballots reduce the field to a shortlist, then members vote.
- UK Labour: MP nominations, then one member, one vote.
- Japan's LDP: Diet members plus party members; the runoff is weighted toward Diet members and prefectural chapters.
- Canadian parties: points per riding, ranked ballots.

**Trap.** General-public polls of "preferred leader" do not measure the selectorate. Use member polls (sparse, S2) and count public MP endorsements against the nomination threshold.

**Without a general election.**
- In Westminster systems, a new leader of the governing party becomes PM.
- For removal (no-confidence motions, leadership challenges, presidential impeachment), count the votes needed at each stage, including supermajorities and any court or senate stage.

## 5. Referendums

**Rules first.**
- Simple majority or double majority: Swiss constitutional votes (amendments, popular initiatives) need the people and the cantons, optional referendums on laws the people only; Australia needs a national majority plus a majority of states.
- Turnout quorums: Italy's abrogative referendums need a majority of the electorate to vote, so boycotting is a strategy.
- Binding or advisory, and any supermajority.

**Priors (verify):**
- Support for change tends to erode as the campaign runs, and undecided voters break toward the status quo (LeDuc's research on referendum campaigns).
- Only 8 of 45 Australian federal proposals carried to 2023 (AEC).
- About one Swiss popular initiative in ten is accepted (Federal Chancellery).

**Polling traps.**
- The survey question's wording differs from the ballot's.
- Survey modes diverge: online and phone polls disagreed before the 2016 Brexit vote.
- Referendum polls err more than party polls.

## 6. Polling quality, blackouts and fundamentals by region (priors to verify)

**Baseline.** Jennings & Wlezien's cross-national database: final-week polls miss a party's share by about two points on average.

**UK.** British Polling Council members publish their tables. Big misses came in 1992 and 2015; the 2016 BPC/MRS inquiry blamed unrepresentative samples. MRP seat projections are S2.

**Western and Northern Europe.** Polls are generally accurate; check each country's record on new and populist parties. Aggregators: Europe Elects, POLITICO Poll of Polls, national sites such as Wahlrecht.de (S2/S3).

**Latin America.** Misses are wider: Argentina's 2019 primaries; Brazil's 2022 first round, which understated the incumbent. Official quick counts and preliminary results arrive fast and are reliable: Mexico's INE quick count and PREP, Brazil's TSE electronic tally.

**India.** Opinion and exit polls have a mixed record: they overstated the incumbent alliance in 2004 and 2024. Exit polls are embargoed until the last phase closes, and the ECI counts all phases on one day.

**Japan.** Media polls (NHK, Kyodo, Asahi, Yomiuri, Nikkei) track cabinet approval and party support. Newspapers' pre-election situation surveys (情勢調査) project seats.

**South Korea.** New polls may not be published in the final six days (NEC). Phone-interview and automated (ARS) polls differ systematically, so compare like with like (Gallup Korea, Realmeter).

**Taiwan.** Polls may not be published in the final ten days (CEC). Pollsters include TVBS, 美麗島電子報 (My-Formosa), 台灣民意基金會 (TPOF) and NCCU's Election Study Center (TEDS). Chinese-language sources are S1/S2 here.

**Blackouts elsewhere.**
- France: the eve and the day of voting.
- Italy: 15 days.
- Others: verify with the ACE Electoral Knowledge Network.
- Foreign media and markets may keep publishing during a blackout.

**Economic voting.**
- It is weaker where responsibility is diffuse: coalitions, federal systems, minority governments (Powell & Whitten, "clarity of responsibility").
- Broad anti-incumbent swings followed the post-2021 inflation wave in many democracies (S2 analyses; verify).

**Non-competitive elections.** Where candidates are pre-screened, forecast the vetting first; if more than one viable candidate remains, forecast the race as usual. Where the opposition is barred or the result is not in doubt:
- forecast turnout and margin only;
- route regime stability, protests and succession to geopolitical-forecasting.

**China** has no competitive national elections. Questions about NPC or party-congress leadership go to geopolitical-forecasting or policy-and-trade-forecasting.

## 7. Scenarios and actors outside the US

**Scenarios** (MECE, integer weights):
- **Parliamentary**: single-party majority; A-led coalition; B-led coalition; single-party minority government or repeat election (if the deadline allows). Each must be exclusive on the resolution date.
- **Presidential with a runoff**: each viable winner. For a deadline before the runoff, split "decided in round one" from "goes to a runoff".
- **Referendum**: passes; fails; void for turnout (where a quorum exists).

**Weights, base rate first:**
1. The country's own history: incumbent re-election rate, how often single-party majorities occur, how often the poll leader at the same horizon won.
2. The seat projection from polls, with the error prior.
3. Liquid markets, if any.

**Actors.**
- Principal: party leaders and factions; pivotal small parties (kingmakers).
- Arbiter: the head of state (appoints the formateur); the election commission; the constitutional court.
- Stakeholder: regional, linguistic, age and education blocs; unions; business federations.
- Amplifier: media and pollsters.

**For each party, record:**
- seats now and projected;
- red lines and their credibility;
- past coalition behaviour;
- internal approval steps (member ballots);
- how secure the leader is.

## 8. Official result bodies and comparative data
**National bodies (S1):**
- UK Electoral Commission (House of Commons Library briefings are S2);
- Elections Canada;
- Australian Electoral Commission;
- Germany's Federal Returning Officer (Bundeswahlleiter);
- France's Ministère de l'Intérieur results and the Conseil constitutionnel;
- the European Parliament results site;
- Japan's Ministry of Internal Affairs and Communications (総務省);
- South Korea's National Election Commission (중앙선거관리위원회);
- Taiwan's Central Election Commission (中央選舉委員會);
- the Election Commission of India;
- Brazil's TSE;
- Mexico's INE;
- the Netherlands' Kiesraad;
- Israel's Central Elections Committee;
- Italy's Ministero dell'Interno (Eligendo).

**Comparative (S2):**
- International IDEA (turnout, electoral systems);
- IFES ElectionGuide;
- ParlGov and ERDDA (cabinets and formation);
- CLEA (constituency results);
- ACE Electoral Knowledge Network (rules, blackouts).
