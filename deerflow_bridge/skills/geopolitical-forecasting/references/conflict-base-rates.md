# Conflict base rates and reference classes

Load this for base-rate KIQs and when weighting a conflict scenario frame. Every prior here is a **prior to verify**. Fetch the dataset page, its codebook or a peer-reviewed summary before you state it as a finding. Shares you compute yourself are REPORTED. No number in this file is a current fact.

## 1. Datasets: what each one can settle

| Dataset (source class) | Unit and threshold | Use it for | Caution |
|---|---|---|---|
| Correlates of War (COW) Inter-State War | wars between states with at least 1,000 battle deaths in 12 months; from 1816 | duration and outcome of interstate wars | coverage ends in the 2000s; outcome codes (win, compromise, stalemate, transformed) are coarse |
| COW Intra-State and Extra-State War | civil and colonial wars, same death threshold | civil-war duration contrasts | different eras dominate |
| UCDP/PRIO Armed Conflict Dataset | state-based conflict with at least 25 battle deaths per calendar year; "war" means at least 1,000 | active or inactive status, intensity, type (interstate, intrastate, internationalized intrastate) | "inactive" only means below 25 deaths that year, not peace |
| UCDP Conflict Termination | episodes ended by peace agreement, ceasefire agreement, victory, low activity, or actor ceasing to exist | termination-type priors | coded per episode; a later restart is a new episode |
| UCDP Peace Agreement; PA-X (University of Edinburgh) | signed agreements, including partial and process texts | what agreements contain and how processes are staged | most texts are partial or procedural |
| ETH/PRIO Civil Conflict Ceasefire | ceasefires with their declared type and purpose (for example unilateral vs agreed, partial vs general) | ceasefire durability in civil wars | civil conflicts only; read the codebook categories |
| Fortna's interstate ceasefire data (Peace Time) | ceasefires after interstate wars since 1946 | durability against agreement strength | small, older sample |
| UCDP GED; ACLED | georeferenced events; ACLED (updated weekly) codes battles, remote violence and protests | front activity; monthly counts that can settle a "violence below K" outcome | coverage widened over time; fatalities are reported estimates; read the codebook |
| COW Militarized Interstate Disputes (MID) | threats, displays and uses of force short of war | how often disputes escalate to war | the severity coding hides near-misses |
| International Crisis Behavior (ICB) | crises: triggers, great-power involvement, outcomes | how often crises become wars, and crises between nuclear powers | crisis onset is a judgment call |
| Archigos | leaders: manner of exit (regular, irregular, foreign) and fate after exit | leader-exit and regime priors | update lag |
| Powell and Thyne coups; Cline Center Coup d'Etat Project | coup attempts and successes | coup priors | definitions differ (attempt vs plot vs auto-coup) |
| HSE (Hufbauer, Schott, Elliott, Oegg); TIES; Global Sanctions Data Base | sanction episodes, threats, outcomes | sanctions-success priors | what counts as "success" is contested |
| ICM (Bercovitch); Civil Wars Mediation | mediation attempts and outcomes | mediation priors | mediation is selected into hard cases |
| SIPRI Military Expenditure and Arms Transfers; IISS Military Balance; Kiel Institute Ukraine Support Tracker | spending, transfers, force structure, aid commitments | capacity and aid baselines | SIPRI definitions differ from national budgets; aid commitments are not deliveries |

Official-data complements: `data_search` "military expenditure percent of GDP" (geography of each belligerent), "armed forces personnel", and "GDP growth" or "consumer price inflation" for an economy under strain. Use `data_get(..., start="<30 years back>")` to compare price shocks across past crises, for example on imf:PCPS/G001.POILBRE.USD.M or imf:PCPS/G001.PNGASEU.USD.M.

## 2. Build the reference class (ordered checks)

1. **Conflict type.** Interstate, intrastate, internationalized intrastate (foreign troops fight on one side) or proxy. A war between two states, each backed by patrons, is still interstate. Militias fighting with a state sponsor make an internationalized civil war.
2. **Great-power role.** Is a great power a direct belligerent, a patron supplying arms and money, or absent? Direct belligerency by a great power or a nuclear-armed state shrinks the sample to a handful. Say so, then add a broader second class.
3. **Incompatibility.** Territory or government. Territorial wars more often end along lines of control, with ceasefires or partition. Wars over government more often end in victory or power-sharing. Verify this on the termination data.
4. **Balance and geography.** The capability ratio, defensive advantage of terrain, and access to resupply.
5. **Duration so far (the most important conditioning).** Use only wars that had already lasted at least as long as this one. A prior built on all wars is dominated by short ones. Whether the hazard of ending rises, falls or stays flat with elapsed time depends on the dataset: measure it on the conditioned class rather than assuming it.
6. **Era.** Post-1945 (the norm against conquest, UN mechanisms) and post-1990 (more negotiated endings, fewer outright victories).
7. **Diplomatic state.** Are talks active? How many ceasefires have already failed? Does a mediator have leverage over both sides?

Rule: report two or three classes (one narrow and causal, one broad), the spread between them, and n. If n is below about 10, call the prior weak and widen it.

## 3. Priors to verify, with their source class

**Duration and termination**
- Interstate wars are typically much shorter than civil wars. The duration distribution is right-skewed: many end within months, and a minority run for years. Verify on COW Inter-State War, and on the Bennett and Stam duration studies.
- Civil wars last far longer on average than interstate wars. Verify on UCDP and in Fearon's work on civil-war duration.
- Termination types: in the UCDP termination data, low activity (fighting fades without any agreement) is the most common ending. Peace agreements and ceasefire agreements are minorities, and decisive victories have become rarer since the Cold War. Verify the shares on the UCDP Conflict Termination Dataset (Kreutz).
- Since 1945, conquest of a whole state is rare (Zacher on the territorial-integrity norm; Fazal on "state death"). Decisive outcomes therefore usually mean the collapse of one side's army or government, not annexation of the whole state.

**Ceasefire durability**
- Failure risk is front-loaded: the first months after a ceasefire carry the highest hazard of relapse. Verify on Fortna's interstate analysis and the ETH/PRIO ceasefire data.
- Stronger agreements last longer. The strength mechanisms are:
  - demilitarized zones;
  - peacekeepers or monitors;
  - third-party guarantees;
  - joint commissions;
  - specific lines, timetables and procedures;
  - dispute-resolution channels.
  Source: Fortna, Scraps of Paper? and Peace Time. Use this list as the checklist for any ceasefire scenario: each mechanism absent lowers durability.
- Many civil-war ceasefires are preliminary, partial or unilateral and short-lived. Count only the ceasefires that match the question's resolution term.

**Recurrence**
- A large minority of terminated conflicts recur. Estimates of the share returning within a decade vary with the dataset and definitions, and are often cited as about a third or more. Verify on the UCDP termination and recurrence data, and in Walter's and Collier's work on the conflict trap. That literature is mostly about civil conflicts: verify interstate recurrence separately (COW; Fortna). Every "frozen" or "ceasefire" scenario therefore needs a relapse tripwire.

**Mediation**
- Mediated conflicts reach formal agreements more often. But agreements extracted under heavy leverage are less durable once the pressure lifts: Beardsley calls this the mediation dilemma.
- A mediator biased toward one side can deliver that side's concessions (Kydd; Svensson).
- Raw success rates understate mediation's effect, because mediators take on the hard cases. Verify on ICM and Civil Wars Mediation.

**Escalation**
- Most militarized interstate disputes never reach war; only a small fraction escalate. Verify on MID, conditioning on fatalities and mobilization.
- Crises between nuclear-armed states have mostly ended without full-scale war between them (ICB).
- No nuclear weapon has been used in war since 1945. That record makes use a tail outcome, not a zero. Weight it from readiness signposts, never from rhetoric.

**Coups and regime stability**
- Roughly half of coup attempts have historically succeeded. Verify on Powell and Thyne.
- Attempts cluster in countries with a recent coup (the coup trap) and spread within regions (contagion).
- Most non-constitutional exits of autocrats come from regime insiders (coups, palace removals), not mass uprisings or foreign imposition. Verify in Svolik and on Archigos.
- Leaders who expect punishment after losing office (exile, prison or death, typical where removal is irregular) tend to prolong losing wars (Goemans, War and Punishment; Chiozza and Goemans), "gambling for resurrection" in Downs and Rocke's term. Use this to lower the termination hazard for such leaders.

**Sanctions**
- HSE coded roughly a third of episodes as at least partly successful; Pape argued that far fewer were. The dispute itself is the lesson: "success" depends on the coding.
- Success is likelier when:
  - goals are modest;
  - the target is an ally or a democracy;
  - sanctions are multilateral (evidence mixed: HSE found little gain from cooperation; Drezner finds institution-backed coalitions help);
  - a threat alone suffices (TIES: many episodes resolve at the threat stage).
- Regime change and reversal of territorial conquest are the least likely sanction outcomes. Verify on HSE, TIES and the Global Sanctions Data Base.

## 4. Hazard arithmetic (by hand)

- **Constant annual hazard h:** P(event within T years) = 1 − (1 − h)^T. Monthly hazard: h_m = 1 − (1 − h)^(1/12).
- **Piecewise hazard:** P = 1 − Π(1 − h_k) over sub-periods k. Use a higher hazard inside a live negotiation window and the base hazard elsewhere.
- **Illustration (arithmetic only, not a base rate).** Suppose the class implies 20% per year. Then P(end within 18 months) = 1 − 0.8^1.5 ≈ 0.28. Now suppose a framework text is judged to double the hazard for the first 6 months: survival = 0.6^0.5 × 0.8 ≈ 0.62, so P(end) ≈ 0.38. Write the judgment ("doubles") as REPORTED reasoning, not as data.
- **Ceasefire holding at D:** P(in effect on D and held w days) = P(reached by D − w) × P(survives w days | reached). Because failure risk is front-loaded, do not assume survival over a short window w is close to 1. The product is an upper bound: a ceasefire reached earlier must survive longer than w.
- **Ordering constraints:**
  - P(implemented) ≤ P(signed) ≤ P(framework);
  - P(comprehensive settlement by D) ≤ P(any ceasefire by D);
  - P(event by D1) ≤ P(event by D2) when D1 is earlier than D2.

## 5. From base rate to plan-time weights

The planner fixes the weights from scout snippets alone, so:
1. Pick the class, take its termination hazard and compute p_T, the probability of termination by the horizon.
2. Set continued fighting at about 1 − p_T before any adjustment.
3. Split p_T using the termination-type priors:
   - low activity and ceasefire → frozen line or ceasefire;
   - agreement → settlement;
   - victory → decisive outcome.
4. Adjust only for observed stage evidence (a format agreed by both sides, a framework text, a signature) and for escalation thresholds already crossed. Each stage moves weight from continuation toward ceasefire or settlement; a headline does not.
5. Give tails (decisive outcome, widened war) an explicit small weight; never 0.
6. Record the class, n, h, horizon and result in the base-rate KIQ, so the scenario writer can show the outside view.

Adaptations:
- **US-Iran or another crisis without a war:** use crisis and dispute escalation priors (ICB, MID) for "strikes or war". Use negotiation-stage evidence for "deal".
- **Coups:** start from the country's own attempt history plus the regional cluster. Never use the global average alone.
- **Taiwan Strait:** there is no meaningful invasion sample. Anchor on the status quo, with the long record of coercive exercises that did not become blockades as the persistence prior. Move weight only on preparation signposts (see escalation-and-negotiation.md).

## 6. Recording a base-rate finding

`- Prior to verify: <statement>; class: <definition>, n=<count>; window: <years>; source class: <dataset> [S<n>] (REPORTED)`

A fetched codebook definition (for example, UCDP's 25-death threshold) is VERIFIED for the definition only. A share or hazard you computed is REPORTED.

## 7. Traps (misreading → discriminating observation)

- **"Most wars end quickly" applied to a war already years old** → condition the class on elapsed duration.
- **"Ceasefires usually fail"** (built mostly from partial or unilateral truces) → match the ceasefire type and the strength mechanisms present.
- **"UCDP inactive" read as peace** → inactive only means fewer than 25 deaths that year; check for an agreement and for relapse.
- **"ACLED shows violence rising"** → coverage expansion; compare like-for-like regions and periods, and check the codebook date.
- **A great-power-war sample of 1 to 3 cases read as a precise prior** → widen it, state n, and add a broader class.
- **Sanctions success rate applied to a regime-change aim** → condition on the goal type; regime change is the hardest goal.
