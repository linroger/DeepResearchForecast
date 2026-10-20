# Reflexive world-state model for the multi-agent simulation

**Branch:** `claude-reflexive-world-state-model` (off `main` 8852ce1)
**Status:** design frozen 2026-10-16; implementation in this branch
**Owner record:** [handoff.md](handoff.md)

The words MUST, SHOULD and MAY are used as in RFC 2119.

## 1. Problem

The simulation stage runs OASIS (Twitter + Reddit) in calendar mode: one round is one
calendar period, every active agent writes one "period communiqué" post, a reaction step
lets agents reply, and a shared `WorldState` evolves. That `WorldState` is only a
probability distribution over the forecast scenarios, moved by a batched elicitation
("which scenario does each actor push toward?"). Agents never see a concrete world: there
are no facts that change, no consequences of an announced investment or sanction, no
pending commitments, no alliances that shift because of what somebody did. The feedback
loop between rounds is a 900-character qualitative digest of posts. The simulation
therefore measures discourse, not an evolving world.

The user asked for a reflexive simulation: an explicit world state every round, actors
acting on it with realistic, motivated option sets (goals, values, beliefs, incentives,
alliances, competition, constraints), the world changing in response to those actions, and
actors responding to the changed world.

## 2. Architecture

### 2.1 Round protocol (calendar mode, `SIM_WORLD_MODEL=true`)

```
round r (one calendar period)
  1. begin_round        barrier: wait until world update r-1 is committed
                        -> public WORLD STATE brief for r (facts, moves, consequences,
                           alliances, pending items; never scenario probabilities)
  2. decision step      ONE structured LLM call per deciding actor (principals + active
                        named actors, capped): option menu grounded in the actor's role
                        contract and the current world -> {option, targets, magnitude,
                        public statement, commitment, alliance moves, scenario pushed}
  3. publish            each platform posts the public statement (ManualAction CREATE_POST,
                        tagged is_world_decision) and writes a private USER memory note;
                        non-deciding active agents keep the OASIS LLMAction post
  4. discourse          reaction step (replies / endorsements) unchanged
  5. deliver            platform hands its round actions + fired events to the coordinator
  6. world update       when every live platform delivered r (or heartbeat for a dead
                        round): deterministic kernel update (capacity, commitments,
                        relationship nudges, due effects, scheduled events) + ONE arbiter
                        LLM call that resolves contested actions, moves state variables,
                        emits emergent events and delayed effects (validated and bounded);
                        scenario-share WorldState stepped from the actors' scenario
                        commitments (unchanged consumer contract); artifacts persisted;
                        next brief rendered; barrier r released
```

Hours mode (no `temporal_config`) and `SIM_WORLD_MODEL=false` MUST stay byte-identical to
the current behaviour. The feature is presence-keyed: the runner enters world mode only
when `simulation_config.json` carries a `world_model` block AND the flag is on.

### 2.2 Modules

| Module | Role | Purity |
|---|---|---|
| `backend/app/services/world_model.py` | Kernel: `WorldModel` (state variables, actor states, relationships, pending effects, events), apply/advance/snapshot/diff, public and private brief renderers | pure, seeded RNG injected |
| `backend/app/services/agent_decision.py` | Agency classes, action catalog, option menu, decision prompt, decision parsing/validation, memory note | pure except the injected `llm.chat_json` |
| `backend/app/services/world_update.py` | Deterministic round update, arbiter prompt, arbiter output validation, round digest | pure except the injected `llm.chat_json` |
| `backend/app/services/world_model_seed.py` | PREPARE-time `world_model` block from research artifacts (quantitative facts, official data, actor intelligence, relationships, scheduled events) | pure |
| `backend/app/services/agent_decision.py` (`infer_agency_class`) | agency-class inference shared by ontology normalisation, the seed and the decision step (kept in services so utils never imports services) | pure |
| `backend/app/services/ontology_generator.py` | rich-schema `agency_class` / `levers` metadata and normalisation | prompt + pure |
| `backend/app/services/simulation_config_generator.py` | emits `world_model` block (before sealing) and per-agent `agency_class` / `archetype` | existing |
| `backend/scripts/run_parallel_simulation.py` | `_ReflexiveWorldCoordinator`: shared per-sim-dir round barrier, decision step, world update, artifacts | runtime |
| `backend/app/services/simulation_runner.py` | run-state projection of world rounds, run_summary `world_model` block, stale-artifact rotation | existing |
| `backend/app/api/simulation.py` | `GET /api/simulation/<id>/world-state` | existing |
| `frontend/src/components/research/WorldStatePanel.vue`, `frontend/src/utils/worldState.js` | live world-state panel inside the simulation tab | new |
| `backend/app/services/report_agent.py`, `report_visualizer.py` | world-evolution block in the diagnostic signal pack; world-variable chart | existing |

### 2.3 World model (kernel)

`WorldModel` holds:

- `variables`: `{id: StateVariable}` with `name`, `value`, `unit`, `kind`
  (numeric / categorical / boolean / text), `as_of`, `provenance`
  (research / official / seed / arbiter / effect), bounded `history`.
- `actors`: `{agent_id: ActorState}` with `name`, `agency_class`, `archetype`,
  `capacity_per_round`, `capacity_used`, `outcome_power` (declared only), `posture`,
  `documented_plans`, `red_lines`, `commitments` (pending, with `due_round`), `last_action`.
- `relationships`: `{(a, b): Relationship}` with `kind`, `valence`, `polarity`,
  `strength`, `last_changed_round`, `basis`.
- `pending_effects`: delayed consequences `{due_round, description, variable_id,
  op, value, probability, source}` resolved with the seeded RNG when due.
- `events`: per-round `WorldEvent` rows (scheduled / action / consequence / emergent /
  resolution) with the actors involved.
- `round`, `period`, `scenario_shares` (mirror of the scenario `WorldState`, for the
  record only; never rendered into agent-facing text).

Pure operations: `register_decisions`, `apply_arbiter_update`, `advance`, `snapshot`,
`diff`, `render_public_brief`, `render_private_brief`, `to_dict` / `from_dict`.

Invariants:

- I-1 Agent-facing text never contains scenario shares or percentages derived from them
  (herding guard, inherited from `world_delta`). Variables with a `%` unit are world
  facts and are allowed.
- I-2 Every change to a variable carries a cause (`round`, `source`, `rationale`) in its
  history; numeric changes from the arbiter are clamped to
  `SIM_WORLD_MAX_CHANGE_RATIO` of the current magnitude per round.
- I-3 Unknown outcome power stays unknown. Capacity per round comes from the agency class,
  never from visibility (`influence_weight`).
- I-4 The kernel never calls an LLM, never does I/O and never reads `Config`.

### 2.4 Decision step

- Deciding roster per round: all `cadence == "principal"` agents plus the active sampled
  named (non-audience) agents, capped at `SIM_WORLD_DECISION_MAX_ACTORS` (default 24),
  principals first, then by influence weight.
- Option menu (deterministic): response options (to actions / events that targeted the
  actor last period), documented options (the actor's researched plans and likely
  actions), agency-class options from the catalog filtered by remaining capacity and
  reversibility, and `hold_position`. At most 10 options.
- Prompt: system message = the actor's existing sealed role brief (read from the live
  OASIS agent, never modified); user message = WORLD CLOCK line, public world brief,
  private brief (own commitments, consequences aimed at it, capacity), the option menu,
  the candidate scenarios (names only) and the JSON contract.
- Output validated: option id must be in the menu (or `custom` with a catalogued kind),
  targets resolved to cast names, magnitude clamped, statement bounded, scenario name
  validated or `abstain`. Any failure degrades to `hold_position` with a typed status
  (`failed` / `invalid`) so a dead decision step can never masquerade as "everybody
  waited".
- One decision per actor per round shared across platforms. Both platforms publish the
  same statement; each writes a `# YOUR MOVE THIS PERIOD` USER memory note so the
  reaction step and later rounds stay consistent.

### 2.5 World update

Deterministic (always): consume capacity, register commitments (due_round = r + lag),
nudge relationships (coalition moves closer / antagonistic moves farther, bounded),
fire due pending effects (probability roll with the seeded RNG), record scheduled events,
advance the round counter.

Arbiter (one LLM call, `SIM_WORLD_ARBITER=true`): receives the world snapshot brief, the
round's decisions (option, targets, magnitude, statement), fired events and the
deterministic effects, and returns `variable_changes`, `new_variables` (bounded count),
`events`, `relationship_changes`, `pending_effects`, `action_resolutions`, a short
`narrative`, and `scenario_pressure` (direction words only). The update is validated
against the variable registry and the cast before being applied. On failure the round is
committed with the deterministic update only and `arbiter_status=failed`.

Scenario shares: commitments are the deciding actors' `scenario_commitment`s weighted by
declared outcome power (`commitments_from_decisions`), stepped through the existing
`WorldState` with the calendar inertia and entropy floor; `round_status` follows the
Foglamp typed statuses. `world_state_trajectory.json` (schema v3), `world_digest.jsonl`
and `decisions.jsonl` keep their contract; the trajectory gains an additive
`world_model` summary.

### 2.6 Artifacts (simulation directory)

| File | Content |
|---|---|
| `world_state.json` | latest committed `WorldModel.to_dict()` plus `committed_round`, `brief` |
| `world_state_history.jsonl` | one row per committed round: period, statuses, diff, arbiter narrative, decisions summary |
| `world_actions.jsonl` | one row per structured decision (round, actor, option, targets, magnitude, statement, status) |
| `world_state_trajectory.json`, `world_digest.jsonl`, `decisions.jsonl` | unchanged scenario-share contract |
| `twitter|reddit/actions.jsonl` | principals' statements are `CREATE_POST` rows tagged `is_world_decision`, `option_id`, `action_kind`; a `world_update` event row per committed round carries a one-line headline |

### 2.7 PREPARE-time seed (`world_model` block)

Built by `world_model_seed.build_world_model_seed` inside `generate_config` (calendar
mode) before the config is sealed:

- `state_variables`: numeric/categorical facts parsed from `quantitative_facts` and the
  bound official-data snapshot (bounded by `SIM_WORLD_MAX_VARIABLES`), each with unit,
  as-of date and provenance.
- `actors`: per cast member `agent_id`, `name`, `agency_class` (dossier value, ontology
  value, or inferred from type/role text), `archetype`, `capacity_per_round` (class
  default), `outcome_power` (declared only), `documented_plans`, `red_lines`,
  `allies`, `rivals`.
- `relationships`: valenced edges from `relationships[]` restricted to the cast.
- `settings`: arbiter on/off, max change ratio, barrier timeout.

Canonical actor-intelligence/v1 dossiers: plans and red lines come from the validated
context pack rows (documented evidence only); the public brief only ever shows facts the
world has produced or public research facts; analyst inference never becomes world fact.

### 2.8 Ontology

The rich-schema addendum asks for `agency_class` and `levers` on actor / collective
entity types; normalisation fills a missing `agency_class` from the type name. The
general-forecast prompt tells the designer that entity types must support an evolving
actor world (levers, constraints, decision rights). This is additive metadata, like
`archetype`.

### 2.9 Downstream

- Run state: `world_model_round`, `world_headline` projected from the `world_update`
  event rows; `run_summary.json` gains a `world_model` block (rounds committed, variables,
  events, arbiter failures, decision coverage).
- API: `GET /api/simulation/<id>/world-state` returns the latest state and a bounded
  history, with the same containment/symlink/size posture as the trajectory endpoint.
- UI: a World State panel in the simulation tab (period headline, key facts with deltas,
  latest moves, consequences, alliance shifts), polled with the existing refresh.
- Report: `_world_evolution_block` adds variable trajectories, decisive moves and
  alliance shifts to the diagnostic signal pack under the elicited-model-projection
  label (`forecast_effect` unchanged); a "World State Variables" chart is registered in
  the report visualizer.
- Pipeline: `_log_decision_channel_outcome` records the world-model summary.

## 3. Acceptance scenarios

| Id | Scenario | Evidence |
|---|---|---|
| A1 | A principal's round-1 decision (e.g. tariff increase) appears as a consequence in the round-2 public brief handed to every active agent (reflexivity) | `test_world_model_loop.py::test_world_model_round_loop_is_reflexive` |
| A2 | Each deciding actor is prompted at most once per round even with two platforms; the second platform reuses the shared decision | `test_world_model_loop.py::test_two_platforms_share_decisions_and_respect_barrier` |
| A3 | A platform never starts round r+1 before the world update for r is committed | same test, ordering assertions |
| A4 | Arbiter failure: the round still commits with the deterministic update and `arbiter_status=failed`; the loop never crashes | `test_world_model_loop.py::test_arbiter_failure_round_commits_deterministically` |
| A5 | Invalid decision JSON degrades to `hold_position` with status `invalid`; unknown option ids are rejected | `test_agent_decision.py` |
| A6 | Public brief contains no scenario share percentages; private brief lists the actor's own commitments | `test_world_model.py` |
| A7 | Hours mode and `SIM_WORLD_MODEL=false` produce no world-model artifacts and unchanged events | `test_world_model_loop.py::test_world_model_off_falls_back_to_legacy_inband`, `::test_hours_mode_ignores_world_model_block`, existing `test_calendar_round_loop.py` |
| A8 | `world_model` block is generated from a dossier with quantitative facts and relationships and survives sealing | `test_world_model_seed.py` |
| A9 | API endpoint containment / 404 / happy path; run_summary, run-state projection, report block, chart, orchestrator summary | `test_world_model_downstream.py` |
| A10 | Full backend suite stays green; resume never re-decides a committed round | pytest run recorded in handoff; `test_world_model_loop.py::test_resume_skips_committed_world_rounds` |

## 4. Out of scope (recorded, not hidden)

- The standalone `run_twitter_simulation.py` / `run_reddit_simulation.py` scripts never
  supported calendar mode; the world model targets `run_parallel_simulation.py` (both
  platforms, or `--twitter-only` / `--reddit-only`).
- Promotion of world-model outputs into published probabilities stays behind the Foglamp
  `SIMULATION_FORECAST_EFFECT` policy (`diagnostic_only`).
- The Codex engine on `codex/reflexive-world-simulation` (`world-v1`, a separate opt-in
  engine that replaces the social simulation) is not merged wholesale: its own delivery keeps
  it opt-in after its live behaviour gate. Section 2.10 lists what was ported from it.

## 2.10 Ported from the Codex `world-v1` engine (2026-10-17)

Studied: `docs/handoff/reflexive-world-simulation/{ARCHITECTURE,DELIVERY,contracts,plan-review,
runtime-input,policy-implementation,store-implementation}.md` and the package
`backend/app/services/world_simulation/`. Kept the integrated model as the base (it runs inside
the social simulation, is live-validated and feeds the report and the dashboard). Ported:

- **Consent rule (offers → answers → obligations → breach).** `world_model.Interaction`: a move
  of a proposing option (`open_talks`, `form_alliance`, `signal_concession`, `sign_agreement`,
  `partnership_deal`, `bargain`, `convene`, `program_decision`) aimed at another actor opens an
  offer with exact `terms` (new decision field); the recipient's menu starts with
  `accept:/counter:/reject:/defer:<id>`; acceptance binds both parties with commitments
  (`source=agreement:<id>`, `counterparty`), pulls the relationship closer; rejection pushes it
  apart; a counter opens a counter-offer back; a deferral moves the deadline one period (twice at
  most); unanswered offers lapse after `INTERACTION_TTL_PERIODS`; a lapsed obligation or an
  explicit `break_alliance` is a breach (reputation −0.15, relationship −0.3, obligations
  breached/released). Offers appear in both briefs, the digest, the arbiter prompt (which must
  never assume consent), the round record (`offers_opened/answered/lapsed`, `breaches`), the
  run summary (`offers` counts), the `/world-state` API (`interactions`), the panel card and the
  report block. Tests: `tests/test_world_interactions.py`. Live validation (2026-10-17,
  `sim_1838cf014c0b`, 8 offers) added two rules: any non-hold move — an answer included — honours
  an obligation that fell due in that period, and an actor that owes an answer to an open offer or
  whose agreement obligation falls due decides in that round even when the activity sampler did
  not activate it (`_ReflexiveWorldCoordinator.owed_decision_ids`); without them every breach of
  that run was an artefact of the mechanics, not of the actors.
  *Mirror-image rule (2026-10-17, after the live run `sim_1838cf014c0b`, where the OPEC
  Secretariat chose `accept:` with terms that only acknowledged conformity data and was bound to
  Iraq's baseline anchor):* an `accept:` answer adopts the offer's terms verbatim; acceptor `terms`
  that are empty, a fragment of the offer, a bare acknowledgement (fewer than
  `ACCEPT_TERMS_MIN_TOKENS` = 3 content tokens) or that share at least `ACCEPT_TERMS_OVERLAP_MIN`
  = 0.6 of their content tokens with the offer without introducing a figure the offer lacks bind
  as an acceptance; anything else is recorded as a counter-offer back to the proposer carrying the
  acceptor's terms (`status=countered`, round record "recorded as a counter-offer, not an
  acceptance"), never as an agreement (`world_model.terms_restate_offer`; CJK text is compared as
  character bigrams; the menu label and the decision contract tell the actor so).
- **Modelling gaps instead of invention.** `world_model_seed.seed_gaps` lists what the research
  could not ground (numeric facts without units or as-of dates, actors without goals / plans /
  an agency class, a cast without relationships, a world without facts); the sealed block, the
  kernel (`seed_gaps`), the run summary, the API and the panel badge carry them.
- **Behaviour diagnostics.** `world_update.behaviour_metrics`: per round, the share of moves
  that answered an offer or whose statement / rationale names a fact that changed or an actor
  that moved last period (a textual diagnostic, not a realism verdict); aggregated in the run
  summary (`behaviour`), shown as a panel badge and a report line.

Not ported, with reasons: the SQLite fenced store and exact-decimal replay (the JSON artifacts
plus resume guards already give replay without re-deciding), the strict budgeted HTTP policy
(the pipeline's telemetry/budget and the decision concurrency caps cover it), the compiler's
typed mechanism catalogue (it only admits eight pre-declared action kinds and fails the whole
world on any gap; the integrated model keeps the agency-class catalogue plus a bounded arbiter),
the preregistered evaluation harness (tied to Codex's evidence workflow and frozen fixtures).

## 2.11 Reflexivity and realism iteration (2026-10-20)

Record: [`docs/handoff/world-state-realism/handoff.md`](../world-state-realism/handoff.md). Each item lists the
gap it closes; all are deterministic kernel rules or bounded arbiter fields validated before use.

- **Announced settings land; everything else stays bounded.** `world_model.ANNOUNCING_KINDS`,
  `WorldModel._announced_by`: an arbiter change attributed (`caused_by`) to an actor whose move this period
  was a policy, economic, legal, coalition or operational move that stated the new value or the size of the
  change (an acceptance states the figures of the offer it adopts) applies in full and never crosses zero;
  other changes keep the `max_change_ratio` clamp, which now also bounds delayed effects (`fire_due_effects`
  applied them unbounded before). `last_action` keeps the bounded statement and terms the check reads.
- **Track records (reputation made visible).** `ActorState.track_record`: commitments kept / lapsed / broken,
  `released` ones (the other side's breach), open ones, and how the arbiter resolved the actor's moves
  (`ActorState.outcomes`). The public brief lists them (breakers first), each actor sees its own, the arbiter
  reads each mover's record and is told that counterparts discount the word of actors who broke theirs; the
  `/world-state` API returns it. A `break_alliance` no longer honours the obligation it breaks in the period
  it falls due (the mechanical "any move honours a due commitment" rule used to give the breaker a clean
  record).
- **Expectations (the perception side of reflexivity).** The `expected_reactions` of each decision are stored
  on the actor (`ActorState.expectations`, newest 8); one period later `WorldModel.expectation_checks` puts
  each next to what that actor actually did, in the expecting actor's private brief. The arbiter lists the
  expectations in play and is told that markets and counterparties react to announcements and expectations
  before measures take effect, weighted by credibility, and that shared expectations can be self-fulfilling
  or self-defeating. `behaviour_metrics` and the run summary count `expectations_checked` /
  `expectations_reacted`.
- **Red lines.** The arbiter sees the red lines at stake (actors targeted this period first) and may report
  `red_line_crossings`; `WorldModel.cross_red_line` accepts one only when the crossing actor moved this period
  and the text matches one of the aggrieved actor's own red lines (`match_red_line`: equal, containing, a
  fragment covering 60%, or half its content tokens). It becomes a `red_line` event aimed at that actor, pushes
  the relationship apart (`RED_LINE_NUDGE`), shows in the briefs and digest, and puts the actor's response
  options first ("X crossed your red line last period"), replacing a plain response to the same move.
- **Trends.** `StateVariable.trend` / `values_by_round`: the arbiter sees each fact's recent path; the public
  brief marks a fact that moved the same way for `TREND_MIN_PERIODS` (2) periods or more.
- **World channel into the outcome.** `worldstate.pressure_commitments`: when the arbiter applied, its
  `scenario_pressure` enters `WorldState.step` as the current shares tilted ±`WORLD_PRESSURE_TILT` (0.25),
  weighted at `SIM_WORLD_PRESSURE_WEIGHT` (default 0.35; `settings.pressure_weight` overrides; 0 disables) of
  the actors' committed weight, or alone when every actor abstained. Round statuses stay the actors'; frozen
  rounds and failed arbiter rounds add nothing; trajectory rows record `channels`. The herding guard holds:
  agents never see shares, and the arbiter never sees them either.
- **Models that always reason.** Not a world-model rule but a precondition for running it on GLM: since
  2026-10-18 glm-5.3 refuses `thinking: disabled` (400 / 1210). `Config.reasoning_extra_body` gives models
  matching `LLM_ALWAYS_THINKING_MODELS` (default `glm-5`) reasoning on at `LLM_THINKING_REQUIRED_EFFORT`
  (default `low`) plus `LLM_THINKING_HEADROOM_TOKENS`; `LLMClient` and the OASIS agents' model resend once and
  remember any other model that refuses.

Acceptance: `tests/test_world_announced_settings.py`, `test_world_track_records.py`, `test_world_red_lines.py`,
`test_world_pressure_channel.py`, `test_world_reflexivity.py` (the chain end to end) and
`test_llm_thinking_refusal.py`.

- **Readers (same day, later).** The World State panel lists each actor's `track_record` on the latest view
  (counts, never the reputation score; breakers first: broken + lapsed, then broken, resolved, name), labels
  `red_line` consequences "red line crossed" / 「越过红线」 at the head of their period, and shows
  `expectations_reacted / expectations_checked` from the run summary beside the responsive-moves badge. The
  `/world-state` history rows carry `red_lines_crossed` (at most 4, only when present) so a past period keeps
  its crossings after its events leave the 40-event window. The report's world-evolution block adds the newest
  4 red-line crossings and up to 6 actors with broken or lapsed commitments, inside the block that stays
  labelled an elicited model projection; without such events or records it is byte-identical. Acceptance:
  `tests/test_world_reader_signals.py` (it also pins `frontend/tests/fixtures/world/world_state.reflexive.json`,
  the panel tests' payload, to the API's output for the reflexivity scenario) and the frontend
  `worldState` / `worldStatePanel` tests.
