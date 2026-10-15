# US process stages, clocks and base rates

Load to stage a US bill, executive action, agency rule or court case, to test whether it can finish before a deadline, and to set a stage-conditioned prior. Every rate below is a **prior to verify** against the named source class; cite what you fetched, never this file. Trade-specific authorities, China and EU pathways are in [trade-instruments.md](trade-instruments.md).

## 1. Five-step method

1. **Instrument → pathway.** Name the act and the pathway it must travel (sections 2–5). A question about "tariffs by 2028" usually spans several instruments; stage each one.
2. **Current stage from the primary record:** Congress.gov "All Actions"; the Federal Register document or public-inspection copy; reginfo.gov (Unified Agenda, OIRA review); the regulations.gov docket; the court docket or opinion.
3. **Forward pass (feasibility).** Earliest completion = date of the latest record + minimum duration of each remaining stage. Sequential stages add; parallel prerequisites take the maximum. If the earliest completion falls after the deadline, that path is near zero unless an expedited route exists: name it and stage it separately. Latest start = deadline − the remaining minimum durations; a negative slack is a contradiction to report.
4. **Prior.** A stage-conditioned base rate from a reference class matched on instrument type, stage reached, salience and the control configuration (unified or divided government). For a constant per-period rate r, P(by T periods) = 1 − (1 − r)^T. Prefer the calendar to a flat hazard when floor time, comment deadlines or court terms concentrate decisions.
5. **Adjust** for veto players (how many must consent, how far apart, their revealed record), then for news. Never adjust twice for the same driver.

## 2. Congress (statute)

| Stage | Record to fetch | Gate (veto point) | Clock |
|---|---|---|---|
| Introduced, referred | bill page, cosponsors, committee referral | committee chair's agenda | none |
| Hearing, markup, reported | markup vote, committee report (H. Rept. / S. Rept. number) | chair and committee majority | chamber layover rules |
| House floor | Rules Committee special rule, roll call | Speaker, Rules Committee, majority whip count | suspension of the rules needs two-thirds |
| Senate floor | motion to proceed, cloture motion, roll calls | majority leader; 41 senators can sustain a filibuster; holds | cloture needs three-fifths of senators sworn, ripens after an intervening day, up to 30 hours post-cloture |
| Resolve differences | conference report or amendment exchange | both chambers' leaders | none |
| Presentment | enrolled bill | President | 10 days, Sundays excepted; pocket veto when adjournment prevents return |
| Override | roll calls | two-thirds of each chamber | none |
| Law | **Public Law number** (the resolving record) | | |

**Routes that remove a veto point** (check whether the instrument qualifies before assuming a 60-vote Senate):
- **Budget reconciliation:** needs a budget resolution with reconciliation instructions; Senate debate is capped at 20 hours and passage takes a simple majority. The Byrd rule strikes provisions that are extraneous (no budgetary effect, or one merely incidental to a policy change), outside the instructed committee's jurisdiction, or that raise deficits beyond the budget window; waivers need 60 votes and the parliamentarian's advice is the gate. Prior: about one reconciliation law per Congress since 1980 (CRS lists).
- **Congressional Review Act** disapproval of a rule: Senate expedited procedure (no filibuster) during a window of 60 session days after the rule is received; the President can veto; a disapproved rule cannot be reissued in substantially the same form without new statutory authority. Rules received in roughly the last 60 session or legislative days before a session ends get a fresh window in the next session (the lookback).
- **Trade agreements under Trade Promotion Authority:** implementing bills get an up-or-down vote with no amendments on fixed deadlines. TPA lapsed in 2021: check whether it has been renewed before assuming fast track.
- **National Emergencies Act** termination resolutions are privileged (committee report and floor-vote deadlines), but the President can veto them, so surviving a veto takes two-thirds.
- **Must-pass vehicles:** regular appropriations (the fiscal year starts 1 October), continuing resolutions, the NDAA, debt-limit measures, expiring authorizations and tax provisions. Policy riders (tariff, export-control, sanctions language) travel on them; track the vehicle's own clock.

**Priors to verify**

| Reference class | Prior | Source class |
|---|---|---|
| Bills and joint resolutions introduced → enacted, per Congress | low single-digit percent, and many enactments are ceremonial | GovTrack statistics; Congress.gov search |
| Passed one chamber → enacted in the same Congress | far higher; compute for the last three Congresses under the current control configuration | Congress.gov advanced search filters |
| All regular appropriations enacted by 1 October | only a handful of fiscal years since the 1974 Budget Act; continuing resolutions are the default | CRS appropriations status reports |
| Funding gaps | about twenty since FY1977, most short | CRS shutdown reports |
| NDAA enacted | every year for over six decades | CRS; Armed Services committees |
| Regular vetoes overridden | under one in ten | Senate Historical Office veto tables |
| Discharge petitions reaching 218 signatures | rare | House Clerk discharge petition records |
| Successful CRA disapprovals | clustered in the first months of a new administration whose party holds both chambers after a party switch; near zero otherwise because the President vetoes | GAO CRA database; CRS |

**Calendar effects.** A Congress lasts two years and convenes in early January of odd years; bills pending at the final adjournment of its second session die and must be reintroduced, so the stage resets to zero. In election years floor time collapses from the August recess to November; the lame-duck session clears must-pass items and leftovers. Senate floor time is the binding resource: count the cloture votes a measure needs against the weeks in session. A change in chamber control at a midterm changes the veto-player set; take control probabilities from election-forecasting and condition on them.

## 3. Executive actions

- **Instruments:** executive orders (numbered, published under Presidential Documents), proclamations (Section 232, 201 and 122 tariffs are proclaimed), memoranda, national emergency declarations, determinations and notices.
- **Stages:** signed → Federal Register publication (document number and FR citation) → agency implementation (FR notices, interim final rules, guidance, CBP messages) → effective and enforced → amended, suspended or revoked by a later order → litigated.
- **Durability:** a successor can revoke an order the day it takes office; Congress overrides only by statute, which the President can veto. Prior: broad revocation of a predecessor's orders in a new administration's first weeks is the norm (FR revocation lists).
- **National emergencies (NEA):** a declaration lapses on its anniversary unless a continuation notice is published within the 90 days before it. Prior: most emergencies are continued for years, and Congress has not terminated one over a veto (Brennan Center emergency list; FR continuation notices; CRS).
- **Litigation:** suits challenge the implementing agency action under the APA or claim the President acted beyond statutory authority; standing and ripeness gate early. Since Trump v. CASA (2025) universal injunctions are curtailed, so relief runs through class actions, APA vacatur, state plaintiffs or party-specific orders: read whom a ruling covers before calling a policy blocked.

## 4. Agency rulemaking

| Stage | Record | Gate | Clock and prior |
|---|---|---|---|
| Unified Agenda entry | RIN on reginfo.gov | agency priorities | projected dates slip often; check this agency's past slippage |
| ANPRM (optional) | FR document | none | none |
| OIRA review of the proposal | reginfo.gov EO 12866 review list | OIRA | nominally 90 days, extendable |
| NPRM | FR document; regulations.gov docket | none | comment period usually 30–60 days; at least 60 days is recommended for significant rules |
| Comment analysis | docket comment count and substance | litigation exposure | months |
| OIRA review of the final rule | reginfo.gov | OIRA | nominally 90 days |
| Final rule | FR document (the resolving record for "finalized") | none | none |
| Effective | rule text | none | at least 30 days after publication unless good cause; a major rule at least 60 days after the later of publication and receipt by Congress |
| CRA window and litigation | GAO CRA database; petitions for review | Congress; courts | statute-specific petition windows (often 60 days); otherwise the six-year APA limit, running from the plaintiff's injury (Corner Post, 2024) |

- **Shortcuts and their costs:** interim final and direct final rules skip prior comment on a good-cause finding but invite procedural challenges; guidance and enforcement discretion are fast but easily reversed; delaying a final rule's effective date usually needs notice and comment itself, and courts have vacated summary delays.
- **Duration priors:** significant rules commonly take one to two years from NPRM to final rule, with a long right tail, and a material share of proposals are withdrawn or never finalized. Compute this agency's own NPRM-to-final and OIRA review durations from its Federal Register and reginfo.gov history rather than using a cross-agency average.
- **Doctrine raises litigation-loss priors** for rules resting on old, general statutory language: Loper Bright (2024) ended Chevron deference, and the major questions doctrine (West Virginia v. EPA, 2022; Biden v. Nebraska, 2023) targets novel claims of vast economic authority.

## 5. Courts

| Stage | Record | Clock and prior |
|---|---|---|
| Complaint, TRO | docket (PACER, CourtListener) | a TRO lasts about 14 days unless extended |
| Preliminary injunction | order and opinion | weeks to months; likelihood of success, irreparable harm, equities, public interest |
| Stay pending appeal | district court, then circuit, then a Supreme Court application | days to weeks; the first stay factor is a strong showing of likely success |
| Notice of appeal | docket | 60 days when the United States is a party, 30 otherwise |
| Panel decision | opinion | months to over a year; use US Courts median times for that circuit |
| Rehearing en banc | order | rare |
| Certiorari | supremecourt.gov docket | petition due 90 days after judgment (up to 60 more on extension); four votes to grant |
| Merits | argument calendar, opinion | cases granted by about January are usually argued that term and decided by the end of June or early July |

The Court can grant certiorari before judgment and expedite briefing; emergency applications are decided in days to weeks. Read the order text, not commentary about it.

**Priors to verify**

| Reference class | Prior | Source class |
|---|---|---|
| Certiorari petitions granted | about 1% overall; far higher for petitions filed by the Solicitor General | Supreme Court journal; SCOTUSblog statistics |
| Cases where the Court calls for the views of the Solicitor General | grant odds an order of magnitude or more above the base | SCOTUSblog and academic counts |
| Supreme Court merits outcome | reverses or vacates about seven in ten of the cases it decides | SCOTUSblog statistics |
| Courts of appeals reversing district courts | a small minority, around one in ten or fewer | US Courts caseload table B-5 |
| A lower court holds a federal statute unlawful and the government seeks review | review is near-routine (usual, not automatic, for a major federal policy) | Supreme Court docket history |
| Oral argument | the side asked more questions tends to lose | political-science studies of argument transcripts |

**Read the remedy:** injunction, declaratory judgment or vacatur; party-specific or class-wide; stayed or in effect; mootness when the policy changes; refund or compliance duties. **Forums:** the Court of International Trade has exclusive jurisdiction over most tariff and customs cases (three-judge panels for major or constitutional questions), with appeal to the Federal Circuit; many agency rules go to the D.C. Circuit; money claims go to the Court of Federal Claims.

## 6. Feasibility template

Question: "Will rule R be in effect by D?" Record: the NPRM published on day 0 with comments closing on day 60. Remaining minimums: comment analysis and drafting (no statutory minimum; take this agency's fastest comparable case), OIRA final review (this agency's fastest review), then 30 days to effect (60 if major). Earliest effective date = day 60 + fastest drafting + fastest review + 30 or 60. If D falls earlier, the only path is an interim final rule: stage it and its litigation risk. Otherwise P(in effect by D) ≈ P(final by D − effective lag | NPRM, agency history) × P(not stayed or vacated by D). Write each factor with its source and tag the product REPORTED.

Same pattern for a bill: count the remaining floor stages, the session weeks left, recesses and the cloture votes needed; for a case: the briefing schedule, the next argument sitting and the term's end.
