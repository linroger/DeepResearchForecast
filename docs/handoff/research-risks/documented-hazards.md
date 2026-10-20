# Documented hazards — research that gives `forecast_inputs.risks` something to keep (design note, 2026-10-21)

Status: implemented offline on `claude/fervent-spence-6d11bb` (built on `claude/nice-diffie-73cb9a`); not pushed; no live run yet (a live run is paid and needs the owner's approval).
Related: [handoff.md](handoff.md) (the documented-risk extraction this feeds), `docs/handoff/research-skills/design.md` §5.2 item 7.

## 1. Problem

The reflexive world model fires exogenous shocks only from documented risks: an event, a probability, the window it refers to, and a source (`forecast_inputs.risks`). The owner's rule is to never invent a probability. The v3 frame extraction (`_T_FRAME`) keeps a risk only when one line of the report states that probability for that event (`normalize_frame_risks`).

A read-only scan of the 9 latest live v3 reports found probabilities almost only as scenario weights, outcome odds or market quotes (handoff F1). Nobody asked the research to look for published event hazards, so live runs end with `risks: []` and fire no shocks.

## 2. Design

In runs with method skills only (`RESEARCH_SKILLS=auto` and a plan with skills), which is the same condition under which the frame is extracted:

1. **Planner (skill text).** The `reference-class-forecasting` Plan gains this rule:
   > Word the risks KIQ "Documented hazards (外生风险概率): which sources publish a probability and window for <2-3 exogenous events: disaster, disruption, ruling, default>?", never the outcome or a scenario.

   The risks KIQ already exists, because `_T_PLAN` asks for "constraints and risks". So this rule rewords a KIQ; it adds none.

2. **KIQ note (engine).** A KIQ whose question matches `_HAZARD_KIQ_RE` gets `_HAZARD_KIQ_NOTE` at the end of its task. The regex matches "documented/published hazard(s)", 外生风险 and 风险概率. Gap follow-ups worded the same way get it too. The note says:
   - find a probability that a source itself publishes (risk outlook, risk register, return period, default study);
   - record the event, the probability and the window exactly as printed, with the publisher's `[S<n>]`;
   - never estimate, count, convert or derive one;
   - never take a scenario weight or a forecast of the question's outcome for one;
   - when none is published, say so under Open questions.

3. **Writer rule (engine).** Every section writer gets `_HAZARD_SECTION_RULE` as one more line of its Rules:
   - state each published probability in a sentence of its own that names no scenario and is not bold or a heading;
   - give the event, the probability and the window exactly as the evidence gives them, with the marker;
   - never give a risk event a probability the evidence does not publish;
   - say when none was found.

4. **Extraction guard (engine).** `normalize_frame_risks` now drops a probability *range* ("5-25%", "between 1% and 5%", "5%至25%") and counts it as `meta.forecast_risks.probability_range`. Risk registers publish likelihood bands. Copied faithfully, the report states a band, but the seed's parser would read one end of it as the shock's rate (`"5-25%"` → 0.25, `"between 1% and 5%"` → 0.01).

The frame prompt, the line checks and the seed are otherwise unchanged.

Flow: plan → hazards KIQ + note → verified finding "… at 10% per year [S7] (VERIFIED)" → digest → writer sentence on one line → frame row → `normalize_frame_risks` → `actors.json` `forecast_inputs.risks` → `world_model_seed.shocks_from_research`.

### Why the KIQ note and the writer rule are engine text, not skill text

The research-skills design asks for method text in SKILL.md. These two texts are the evidence contract of the engine's own extraction instead, kept next to `_T_FRAME` and `normalize_frame_risks`, like `KIQ_HEADER`'s VERIFIED rule:

- **Routing.** `reference-class-forecasting`'s Investigate reaches only base-rate KIQs (`_BASE_RATE_RE`). Wording the hazards KIQ as a base-rate KIQ would also trigger the engine's base-rate data machinery: the 30-year prefetch, the catalog fallback seed and the "count comparable episodes … (for example 3 of 11 years)" note. That contradicts "never count or convert". The chosen wording matches `_HAZARD_KIQ_RE` and not `_BASE_RATE_RE`, so the hazards KIQ keeps its domain method (domain sources and traps) and gets only the note.
- **Reach.** The skill's Synthesize goes only to the scenario-section writer. The hazards KIQ usually feeds a risks section, and any writer may state a hazard.
- **Mechanics.** The form of the sentence follows engine mechanics, not domain method:
  - `normalize_frame_risks` checks one line;
  - `fix_scenario_weights` rewrites "Stalled expansion (10%) …" to the scenario's weight, so the hazard is lost;
  - `parse_report_scenarios` reads a bold "**X (10% per year):**" row in the scenario section as a fourth scenario.

  `test_why_the_rule_names_no_scenario_and_no_bold_item` pins all three.
- **Caps.** Investigate is at 2,396/2,400 and Synthesize at 1,488/1,500, and both are shared by every base-rate KIQ and every scenario writer. A hazard rule there would mean cutting about 450 characters of reviewed base-rate method that every run uses.

The Plan rule stays in the skill, because how to decompose a forecast question is method. Its 7 net characters were paid for by removing text that only repeats engine prompts the planner already gets:
- "(fixed now, from scout snippets)" repeats `PLAN_HEADER`'s "The weights are fixed for the whole run";
- "Names stay number-free" repeats `_T_PLAN`'s "without numbers or percent signs";
- the JSON wrapper of the base-rate example repeats the OFFICIAL DATA block's data_needs example.

Every rule of the Plan is kept: resolvability, base-rate wording and routing, the weighting steps, the decisive split, the anchor in each thesis, calendar KIQs and track records. Plan is now 1,798/1,800 characters, and the whole SKILL.md 9,267/11,000.

## 3. Alternatives considered

| Alternative | Why not |
|---|---|
| Hazard rule in the skill's Investigate/Synthesize, with the hazards KIQ worded as a base-rate KIQ | Triggers the base-rate data machinery that tells the agent to count episodes. Needs about 450 characters cut from method text that every base-rate KIQ and scenario writer reads. The rule reaches only the scenario writer. |
| An extra, engine-forced hazards KIQ | About +1 agent run per plan: 5–9 LLM calls with 2–5 searches and 2–5 fetches, roughly 100–200k (mostly cached) input tokens and 5–10k output tokens. The plan already has a risks KIQ to reword. |
| A gap-review check ("is there a published hazard for each main risk?") | When no source publishes one, which F1 suggests is common, the check stays open and pays for a futile follow-up agent. |
| Let the frame read the evidence digest instead of the report | Breaks the extraction fan-out's shared cached report prefix (+10–25k uncached tokens per run) and the report-line verification (D1). |
| Ask the model for its own hazard when none is published | Violates the owner's rule. |

## 4. Cost per run

- **Calls: +0.** The KIQ count is unchanged (the risks KIQ is reworded), and the hazards KIQ spends its existing search and fetch budget. There are no new extraction calls.
- **Input tokens** (cl100k counts):
  - Planner: +7 characters.
  - Hazards KIQ: the note, 726 characters ≈ 151 tokens. It is uncached once, then a cached prefix on each further step: about +150 uncached and about +1k cached tokens over 5–9 steps.
  - Writers: the rule, 441 characters ≈ 89 tokens on each writer call. That is 8 calls in the scripted standard run (`cost_probe.txt` in the evidence directory, [handoff.md](handoff.md) §8), so about +0.7k uncached tokens. Repairs and critique rewrites add one rule each.
- **Output tokens:** the hazard findings (one line each) plus up to 6 risk rows in the frame reply (about 80 tokens each).
- **Total:** under 2k tokens per run, against a standard run's budget of 2.5M units. Off mode is byte-identical, with no cost.

## 5. Why it never invents

- **Prompts.** No text asks for a probability of the model's own:
  - the Plan asks "which sources publish";
  - the note says "Never estimate, count, convert or derive a probability yourself" and "say so" when none is published;
  - the rule says "Never give a risk event a probability the evidence does not publish";
  - the frame (unchanged) says "never one you estimate, convert or derive".

  `_never_asks_for_an_estimate` in the tests requires every estimate/count/convert/derive/compute/assess word in the Plan rule, the note and the rule to stand in a "never" clause. The note has no example figure to copy.
- **Deterministic checks** (unchanged except the range guard):
  - a VERIFIED finding's numbers must appear on the fetched page, or it becomes UNVERIFIED, and writers must not state an UNVERIFIED figure as fact;
  - a finding without a known marker never reaches the digest;
  - `normalize_frame_risks` keeps a risk only when a report line states that probability for that event (not inside a longer number, not one end of a range, not a range, not a scenario's weight), and keeps its window and marker only on such a line;
  - the seed models only documented windows.
- **Tests.** A run where no source publishes a probability ends with `risks: []` even when the extraction model offers 10% and 5% (`probability_not_stated: 2`), and the seed records `no_documented_shocks`.

## 6. Limits and what the live check must show

- The planner may merge the hazards KIQ away when the KIQ limit binds (quick depth has 4 KIQs), or word it so `_HAZARD_KIQ_RE` misses. The KIQ question still asks for published probabilities, but without the note.
- Sources often publish hazards with windows that the seed cannot parse ("2014–2043"). Those become `shock_without_window` gaps, not shocks.
- What to read on the first owner-approved run, beside handoff §9:
  1. `plan.json` has a "Documented hazards" KIQ.
  2. Its agent task ends with the note.
  3. Its notes hold published probabilities with windows and markers, or "no published probability".
  4. `research_report.md` states them on one line each, outside bold items, headings and scenario sentences.
  5. In `meta.forecast_risks`, `probability_not_stated` and `probability_range` stay low.
  6. The sealed seed has `world_model.shocks`.

  A question whose sources publish event hazards is the best first check: hurricane-season or ENSO outlooks, rating-agency default rates, a national risk register.
