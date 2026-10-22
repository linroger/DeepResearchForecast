# temporal-dynamics — Agent dynamics, decision channel, world state, sim timeline, dates

Slice files (all read in full on branch `main`):

| File | Lines | Purity |
|---|---|---|
| `backend/app/utils/dates.py` | 69 | pure, stdlib only |
| `backend/app/utils/sim_timeline.py` | 570 | pure, stdlib + `dates` |
| `backend/app/services/world_delta.py` | 80 | pure, no imports beyond typing |
| `backend/app/services/worldstate.py` | 304 | pure, no imports beyond typing |
| `backend/app/services/agent_dynamics.py` | 405 | pure; lazily imports `app.config.Config` only in `from_config` (`agent_dynamics.py:127-128`) |
| `backend/app/services/decision_channel.py` | 775 | pure except for the injected `llm.chat_json` call and a lazy `Config` read (`decision_channel.py:74-80`) |

Verification method: besides reading, the pure functions were exercised on *copies* of these six files placed in the session scratchpad (no repo writes, no network, no LLM — the decision channel was driven with a fake `chat_json`). Results quoted below as "(verified)" come from that run.

---

## Purpose & position in the pipeline

This slice owns the **time axis** and the **modeled-outcome state** of the OASIS simulation stage.

1. **Dates / horizon / rounds (config-generation time).** `dates.parse_as_of` is the single lenient date parser (`dates.py:38-69`). `sim_timeline` turns the forecast question into a horizon date (`extract_horizon`, `sim_timeline.py:266-335`) and slices `(as_of, horizon]` into natural-calendar rounds (`build_timeline`, `sim_timeline.py:518-570`). `SimulationConfigGenerator._build_temporal_timeline` calls it when `Config.SIM_TEMPORAL_MODE == "calendar"` (`simulation_config_generator.py:552-570`, `:937-990`) and serializes the result as the top-level `temporal_config` block of `simulation_config.json` (`simulation_config_generator.py:796`).
2. **Seed (PREPARE).** `pipeline_orchestrator` injects `world_state_seed` (`{scenarios, base_rates, uniform_prior, as_of_date, horizon_date, horizon_source?, horizon_defaulted?}`) into `simulation_config.json` (`pipeline_orchestrator.py:12878-12912`).
3. **In-loop dynamics (OASIS subprocess `backend/scripts/run_parallel_simulation.py`).** Each round:
   - `AgentDynamicsTracker` updates per-agent mood/energy/opinion/fatigue and injects a one-line state note (`run_parallel_simulation.py:1886-1937`).
   - In calendar mode, a "WORLD CLOCK" header is injected (`run_parallel_simulation.py:1940-2021`). It carries the qualitative `build_world_delta` digest of the previous period.
   - The **in-band** decision channel (`_InbandWorldEvolution`, `run_parallel_simulation.py:3366-3689`) runs `decision_channel.elicit_round` and then `WorldState.step`.
4. **Post-sim fallback.** When in-band did not write a trajectory and the env flag is set, `decision_channel.run_decision_channel` replays the frozen action log (`run_parallel_simulation.py:5975-6047`).
5. **Downstream.** Several consumers read `world_state_trajectory.json`:
   - the report's world-state block (`report_agent.py:2472-2541`)
   - charts (`report_visualizer.py:2149`, `:3106`, `:5235`)
   - the orchestrator summary (`pipeline_orchestrator.py:10738-10790`)
   - the trajectory API (`api/simulation.py:2006-2060`)
   - the scenario diff (`report_agent.py:9318-9350`)

   In addition, `agent_dynamics` helpers feed `run_summary.json` (`simulation_runner.py:2151-2210`).

Under Foglamp WP1 the WorldState output is labeled `elicited_model_projection` and by default never moves a published probability (`decision_channel.py:724-749`, `config.py:1484-1497`).

---

## Walkthrough (source order)

### `backend/app/utils/dates.py`

- **Module contract** (`dates.py:1-10`): it parses LLM-extracted dates of any shape into **UTC tz-aware** `datetime` and **never raises**. Unparseable input returns `None`. Stated consumers are Graphiti `valid_at` and `actors.events_to_schedule`.
- **Regex constants** (`dates.py:19-24`):
  - `_CJK_YMD` (`YYYY年M月D日`, with the trailing 日 optional)
  - `_CJK_YM`
  - `_NUM_YMD` (`YYYY[-/.]M[-/.]D`)
  - `_NUM_YM`
  - `_YEAR`: `\b(\d{4})\b`. It relies on word boundaries, unlike sim_timeline.
- **`_make(y, m, d)`** (`dates.py:27-35`) builds a UTC datetime. If the day overflows (e.g. Feb 30) it falls back to **the 1st of that month**, not month-end. An invalid month returns `None`.
- **`parse_as_of(value)`** (`dates.py:38-69`):
  - `None` and empty strings return `None`.
  - A `datetime` passes through; a naive one gets UTC attached (`:46-47`). A `date` becomes midnight UTC (`:48-49`).
  - Strings are searched in this order, taking the first match: CJK YMD → numeric YMD → CJK YM (day 1) → numeric YM (day 1) → bare year (Jan 1) (`:54-69`).
  - It uses `.search`, so the first date found anywhere in the text wins.
  - Edge cases (verified): `"2027-02-30"`→2027-02-01; `"12/31/2027"`→2027-01-01 (US format degrades to Jan 1 of the year, silently); `"Q3 2027"`→2027-01-01; `"FY2025"`→`None` (no `\b` between `Y` and `2`); `"2027.13.01"`→`None` (YMD matched but invalid, so there is no fall-through to the year).

### `backend/app/utils/sim_timeline.py`

- **Module contract** (`sim_timeline.py:1-14`): pure, with no LLM, I/O or OASIS. `parse_as_of` is the only string date parser. The regexes are CJK-safe and use explicit look-arounds rather than `\b`. `extract_horizon` never raises.
- **Constants** (`:33-48`):
  - `NOMINAL` = day 1, week 7, half_month 15.22, month 30.44, quarter 91.31, half_year 182.62 nominal days (`:33-40`)
  - `NOMINAL_DAYS` (`:41`) and `UNIT_ORDER` (fine→coarse, `:42`)
  - `TARGET_MIN=8` (`:44`), `TARGET_IDEAL=16` (`:45`)
  - `_HORIZON_MAX_MONTHS=360`, i.e. 30 years (`:48`)
- **Dataclasses**:
  - `HorizonResult` (frozen; `horizon_date` ISO, `source` ∈ explicit_date|anchored_period|relative|bare_year|llm|default, `matched_text`, `defaulted`, `confidence`) (`:56-62`)
  - `RoundPeriod` (frozen; 0-based `round`, inclusive `period_start`/`period_end`, `label`) (`:65-70`)
  - `SimulationTimeline` (`schema_version`, `mode`, `as_of_date`, `horizon_*`, `unit`, `unit_stride`, `n_rounds`, `round_dates`, `span_days`, `target_max_rounds`, `round_cap_coarsened`, `beyond_horizon_events`, `warnings`) (`:73-90`)
- **Date helpers**:
  - `_to_date` (`:98-105`): datetime→date, date passthrough, otherwise `parse_as_of`.
  - `_add_months` (`:108-114`): true calendar addition; the day is clamped to the target month's end.
  - `_month_end` (`:117-120`), `_QUARTER_END` (`:123`), `_quarter_end` (`:126-130`).
- **CJK numerals**:
  - `_CN_NUM` (一..九, with 两=2), `_CN_QUARTER`, `_MONTH_BY_ABBR` (`:138-142`).
  - `_cn_to_int` (`:145-161`) handles digits, 十-compounds (十二, 二十, 二十三) and single numerals. It does not handle 百.
- **Tier tables**:
  - Tier 1 `_TIER1` (`:165-168`): `20YY-M-D` and `20YY年M月D日`.
  - Tier 2 handlers (`:173-215`) and the `_TIER2` table of 11 patterns (`:218-234`): "by end of / end of / late YYYY" and `YYYY年底` → Dec 31; "mid-YYYY" and `YYYY年中` → Jun 30; `Q3 2027`, `2027Q3` and `2028年第三季度` → quarter end; `H1/H2` and `上半年/下半年` → Jun 30 / Dec 31; English month + year → month end; `YYYY年MM月` (with `(?!\d)` to exclude a following day number) → month end.
  - Tier 3 `_TIER3` (`:237-242`): `in|within|next|over the next|未来|今后|接下来` + N + unit (days..years, 天/日/周/星期/个月/月/季度/年).
  - Tier 4 `_TIER4` (`:245`): `(?<!\d)(20\d{2})(?!\d)`.
- **`_relative_target`** (`:248-263`): `as_of + N units` using timedelta for days/weeks and `_add_months` for months/quarters/years. `n<=0` returns None. Verified: `in 2 years` from 2024-02-29 → 2026-02-28.
- **`extract_horizon(text, as_of)`** (`:266-335`):
  - Inputs: `text` is by convention `prompt + "\n" + central_question` (`:269-271`). `as_of` may be a date or any parseable value.
  - Validity window: a candidate must satisfy `as_of < d <= as_of + 360 months` (`:283-286`).
  - Tier 1 (`:289-296`): collects all matches sorted by (position, pattern index). Each match is re-parsed via `parse_as_of`, and the first valid one returns `source="explicit_date"`.
  - Tier 2 (`:299-308`): same ordering, handler per pattern, returns `anchored_period`.
  - Tier 3 (`:311-320`): first valid match in text order, returns `relative`.
  - Tier 4 (`:323-332`): collects **all** years in `[as_of.year, as_of.year+30]`, maps each to Dec 31, and returns the **maximum** valid one as `bare_year`.
  - If nothing matches it returns `None`. Any exception also returns `None` (`:334-335`). Confidence is always 1.0 for deterministic tiers.
  - Verified examples (as_of 2026-10-11): "by end of 2027"→2027-12-31 anchored; "within 18 months"→2028-04-11 relative; "未来两年"→2028-10-11; "2026-10-01" (≤ as_of, skipped in tier 1)→**2026-12-31 via bare_year**; "Will the 2028 Olympics host be decided by 2026?"→**2028-12-31** (the max year wins; "by YYYY" alone is not a tier-2 pattern).
- **`default_horizon(as_of, months=12)`** (`:338-344`): returns `as_of + months` with `source="default"`, `defaulted=True`, confidence 0.3. It **raises `ValueError`** when `as_of` is unparseable, which is the one raising API in the module.
- **`select_calendar_unit(span_days, target_max, hard_max=48)`** (`:352-381`):
  1. `rounds[u] = ceil(span/nominal[u])`, and `fits` = the units with `rounds ≤ target_max`.
  2. Among fits with `rounds ≥ 8`, it picks the one closest to 16 rounds. Ties go to the finer unit, because replacement happens only when strictly better (`:364-373`).
  3. If no fit reaches 8 rounds, it takes the finest fitting unit and keeps refining to finer units while their `rounds ≤ hard_max` (the "anti-aliasing" step, `:374-378`). **This step can exceed `target_max`.**
  4. If even half_year does not fit, it uses half_year with stride `k = ceil(rounds_half_year / target_max)` (`:380-381`).

  Verified with target 36: span 5→day; 40→day (40 rounds > 36); 60→week; 365→month; 1826→quarter; 3653→half_year; 7300→half_year stride 2. Also verified: span 446 with target 3, 5, 8 or 12 → **half_month (29 rounds)**, while targets 20 and 36 → month (15 rounds).
- **Grid helpers**:
  - `_next_grid` (`:389-406`): the next natural boundary strictly after `d`. Weeks use ISO Mondays; half-months the 1st and 16th; months the 1st; quarters Jan/Apr/Jul/Oct 1; half-years Jan/Jul 1. Unknown units raise `ValueError`.
  - `_slot_label` (`:409-424`): ISO date, `YYYY-Www`, `YYYY-MM-H1/H2`, `YYYY-MM`, `YYYY-Qn` or `YYYY-H1/H2`.
  - `_period_label` (`:427-432`): when stride>1 the label is `start~end` if the two slots differ.
- **`build_round_periods(as_of, horizon, unit, stride=1)`** (`:435-479`):
  - The first period starts at `as_of+1d` (`:448`). If the horizon is before that start, it returns `[]`.
  - It collects grid boundaries ≤ horizon (`:453-457`); stride keeps every k-th boundary (`:458-459`).
  - Periods are closed `[start, next_boundary-1]`, and the last one ends exactly at the horizon (`:461-463`).
  - Stub merges use `eff_days = nominal×stride` (`:466-474`). A first period shorter than `eff/3` is merged into the second; a last period shorter than `eff/4` is merged into the previous one.
  - Labels come from the **start date's slot** (`:476-479`). Verified: a merged first period 2026-10-26→2026-11-30 is labeled `2026-10`.
- **`_field`** (`:487-488`) reads from either a dict or an attribute. **`round_for_date(d, round_dates)`** (`:491-510`) works on `RoundPeriod` rows or JSON dicts. It bisects on `period_end`. It returns `None` when the date is before the first `period_start` or after the last `period_end`, and also on any corrupt row (`:504-505`). The `as_of` day itself therefore maps to `None` (verified).
- **`build_timeline(as_of, horizon, target_max, reference_max=36, hard_max=48)`** (`:518-570`):
  - `as_of` unparseable raises `ValueError` (`:529-530`).
  - If the horizon is unparseable or not after `as_of`, it substitutes a 12-month default and adds the warning `horizon_invalid_defaulted` (`:533-537`). An already-defaulted horizon adds `horizon_defaulted_12_months` (`:538-539`).
  - Unit selection happens at `:542`. If `target_max < reference_max`, selection is re-run at `reference_max`; a different unit sets `round_cap_coarsened={from_unit,to_unit,cap}` and adds a warning (`:544-548`). Stride>1 adds `horizon_capped_stride` (`:549-550`).
  - `n_rounds = len(round_dates)` (`:563`). `mode="calendar"`, `schema_version=1`.
  - Verified: as_of 2026-10-11 with "by end of 2027" gives month×15 rounds; the 12-month default gives month×13; a 2060 horizon gives half_year stride 2 × 34 rounds. The 30-year limit is not enforced here, only in `extract_horizon`.

### `backend/app/services/world_delta.py`

- **Module contract** (`world_delta.py:1-12`): pure and deterministic. It is the "WHAT CHANGED LAST PERIOD" digest. Herding guard: **no numeric shares/percentages** ever go into agent-facing text.
- `_DIRECTION_WORD = {up: strengthened, down: weakened, flat: held}` (`:18`).
- **`build_world_delta(round_actions, fired_events, leader_move=None, top_k=5, char_cap=900)`** (`:21-80`):
  1. Fired events (`:38-48`): each non-empty dict becomes `"[{date}] {content}"`, unless the content already starts with `"[{date}]"` (the calendar config-gen prefix, `simulation_config_generator.py:1131`).
  2. Organic posts (`:51-67`): only dicts with non-empty `content`. The weight is `float(influence_weight)` (bad values → 0). The name comes from `actor_name`, then `agent_name`, then `name`, then `"unknown"`. Posts are sorted by (−weight, input index) and the top `top_k` are rendered as `"{name}: {content[:140]}"`.
  3. Momentum (`:70-74`): only when `leader_move` is a dict with a non-empty `leader` and a known direction. It renders `"Momentum: {leader} {word} this period."`. Extra keys such as `share` are ignored (verified).
  - Lines are joined with `\n` and truncated to `char_cap` characters (`:78`). Empty input returns `""` (`:76-77`). Any exception returns `""` (`:79-80`).

### `backend/app/services/worldstate.py`

- **Module docstring** (`worldstate.py:1-15`): the forecast outcome is an aggregate of resource-weighted **decisions**, not voice-share. It states that the wiring "is gated behind `SIM_DECISION_CHANNEL` (default OFF)", which is stale; see Surprises.
- **Round statuses** (`:22-54`): `committed`, `abstained`, `silent`, `failed`, `missing` and `infeasible` (reserved, never emitted). `VALID_ROUND_STATUSES = {committed, abstained}` (`:50`). `KNOWN_ROUND_STATUSES` holds all six (`:51-54`).
- **`CONVERGENCE_POLICY_V1`** (`:59-67`): `min_valid_transitions=3`, `min_valid_coverage=0.5`, `max_failed_rounds=0`, version string `foglamp-convergence-policy/v1`.
- **`_norm_shares`** (`:70-78`): clamps negatives to 0 and renormalizes to sum 1. An all-zero map becomes uniform; values are rounded to 6 decimals.
- **`commitments_from_decisions(decisions, weight_by_agent=None)`** (`:81-119`):
  - Decisions with an empty `scenario` are skipped, which is how abstention is expressed.
  - `magnitude = max(0, float(magnitude or 0))` and `confidence ∈ [0,1]` clamped. Unparseable decisions are dropped.
  - `power` resolves as the decision's `outcome_power`, then `weight_by_agent[agent_id]`, then 1.0. Output rows are `{scenario, magnitude, weight = power×confidence}`.
  - Magnitude has **no upper clamp**.
- **`WorldState.__init__(scenarios, base_rates=None, inertia=0.7)`** (`:130-157`):
  - Scenarios are stringified and blanks dropped. `inertia` is clamped to [0,1].
  - The seed is taken from `base_rates` (bad values → 0). If the sum is ≤0, `uniform_prior=True` and the seed becomes all-ones (`:143-145`). Shares are the normalized seed.
  - `_seed_shares` keeps the prior for the entropy floor (`:150`). `history` starts with the seed.
  - `_last_delta = _ewma_delta = 1.0` (`:152-153`). `converged_at=None` (`:155`). `round_statuses=[]` (`:157`).
- **`WorldState.step(commitments, inertia=None, entropy_mix_days=None, round_status=None)`** (`:159-232`):
  - No scenarios returns `{}` (`:183-184`).
  - Status inference (`:185-194`): with `round_status=None`, a commitment naming a known scenario means `committed`, otherwise `silent`. An unknown string is coerced to `silent` (verified).
  - **Invalid statuses** (not committed/abstained): the status is appended, shares are copied into history, the shares are returned **unchanged, and the EWMA is not touched**. No entropy floor is applied either (`:195-200`).
  - Valid rounds (`:201-232`):
    - Effective inertia is the per-call override or the instance default (`:202`).
    - Votes are `Σ max(0,mag)×max(0,weight)` per known scenario (`:203-214`). If any votes exist, `target=_norm_shares(votes)` and `blended = inertia×prior + (1−inertia)×target`, renormalized (`:215-219`); otherwise the shares are unchanged.
    - Entropy floor (`:222-226`): `lam = clamp(0.0005×days, 0, 0.05)`, mixing toward `_seed_shares` (the prior, not uniform). Verified: a 1/0 prior stays 1/0.
    - `delta` = L1 change (`:227`). `_ewma_delta = round(0.5×prev + 0.5×delta, 6)` (`:229`).
- **`round_accounting()`** (`:234-253`): `{policy_version, counts, rounds_accounted, valid_transitions, valid_coverage, failed_rounds, missing_rounds}`.
- **`convergence_state(eps=0.02)`** (`:255-273`):
  - `active` when the EWMA is ≥ eps.
  - `inconclusive` when the EWMA has settled but a policy guard fails.
  - `converged` otherwise.
  - Because the EWMA starts at 1.0 and halves per zero-delta round, settling needs ≥6 valid rounds (0.5⁶ ≈ 0.0156).
- **`converged(eps)`** (`:275-281`) is `convergence_state(eps) == "converged"`.
- **`outcome()`** (`:283-304`): `{shares, leader, leader_share (4dp), rounds = len(history)-1, ewma_delta, converged, convergence_state, converged_at, uniform_prior, round_accounting, epistemic_status:"elicited_model_projection"}`.
  - Note: `rounds` counts frozen rounds too.

### `backend/app/services/agent_dynamics.py`

- **Module contract** (`agent_dynamics.py:1-18`): a per-agent affective vector updated from interactions received plus the agent's own activity, rendered as a one-line prompt note. Wiring lives in `run_parallel_simulation.py`.
- **Action valence sets** (`:28-30`): POS = LIKE_POST, LIKE_COMMENT, REPOST, FOLLOW, QUOTE_POST. NEG = DISLIKE_POST, DISLIKE_COMMENT, MUTE. ENGAGE = CREATE_COMMENT, REPLY.
- **`TARGET_NAME_KEYS`** (`:34-36`) lists the 7 `action_args` keys that may hold the target's name. `target_user_name` was added for FOLLOW/MUTE (RUN-8 comment, `:31-33`).
- **`extract_round_signals(actual_actions, name_to_id)`** (`:39-73`):
  - `activity[aid]` counts the actions the agent took.
  - For each action, the first non-empty target-name key resolves via `name_to_id` to a target id. The target's `received[tid]` gets `pos`, `neg` or `engage` incremented according to the action type. Unresolvable targets are ignored.
  - Self-targeted actions count as received.
- **`_clamp`** (`:76-77`); **`_squash(x)=x/(1+|x|)`** (`:80-83`).
- **`AgentDynamicsTracker.__init__(agent_ids, *, initial, mood_lr=.25, opinion_lr=.15, fatigue_rate=.20, fatigue_decay=.10)`** (`:94-120`):
  - `mood` = clamp(`sentiment_bias`, −1, 1), default 0.
  - `opinion_strength` = clamp(`influence` or else `influence_weight`, 0, 1), **default 0.3 only when both keys are absent** (`:109-113`).
  - `energy=1`, `fatigue=0`. The counters `_rounds_observed` and `_rounds_with_received` start at 0 (`:119-120`).
- **`from_config(agent_configs, *, config_obj=None)`** (`:122-148`): ids come from `agent_id`. Initial values are `{sentiment_bias, influence (or influence_weight)}`, and the learning rates come from `Config.SIM_DYNAMICS_*` via getattr with defaults.
- **`observe_round(received, activity)`** (`:150-178`):
  - `_rounds_observed` is incremented every call. `_rounds_with_received` is incremented if any agent received a non-zero signal.
  - Per agent: `mood += mood_lr×squash(pos−neg)`. If total interactions > 0, `opinion += opinion_lr×squash(total)`. Then `fatigue = fatigue×(1−decay) + rate×acted`, where `acted ∈ {0,1}`, and `energy = 1 − fatigue`.
  - All values are clamped.
  - Verified: 4 rounds of 1 received like plus own activity → mood 0.5, opinion 0.8 (from 0.5), fatigue 0.688.
- **`dynamics_summary()`** (`:180-188`): `{rounds_observed, rounds_with_received_signal, active = rounds_with_received > 0}`.
- **`get_state(aid)`** (`:190-191`) returns a copy of the state.
- **`state_line(aid)`** (`:193-211`):
  - Fragments: mood ≥0.4 → 情绪亢奋/激动; mood ≤−0.4 → 情绪低落/愤懑; opinion ≥0.7 → 立场已明显强化; fatigue ≥0.6 → 有些疲惫，参与意愿下降.
  - With no fragments it returns `""`. Otherwise it returns `【你当前状态】…。让你的发帖语气…体现这一状态。`.
- **ITEM 20 realism helpers** (`:214-405`):
  - Organic buckets (`:223-228`).
  - `classify_organic_action` (`:231-242`): CREATE_POST, QUOTE_POST and REPOST → `posts`; CREATE_COMMENT → `comments`; likes and dislikes → `likes`; anything else → None.
  - `sample_engagement_likes(post_weights, post_authors, liker_ids, rate, rng)` (`:245-307`):
    - Deterministic, given a seeded rng.
    - Each sorted liker consumes one `rng.random()` for the rate gate and at most one like. It never likes its own post. The pick is weighted by post weight.
    - Returns sorted `(liker, post_id)` tuples. `rate ≤ 0`, no positive-weight posts or no likers → `[]`.
  - `throttle_seed_follows(by_follower, cap)` (`:310-332`) truncates each follower's FOLLOW list to `cap` and returns `(capped, dropped)`. `cap ≤ 0` means unlimited.
  - `detect_organic_ratio_collapse(platform_round_counts, min_consecutive)` (`:335-387`):
    - Per platform, it flags runs of ≥K rounds where `posts>0` and `comments+likes==0`.
    - Rounds absent from the map are neither breakers nor extenders. Verified: rounds 1, 2, 4 count as a 3-round run "1–4".
    - The detail strings are Chinese.
  - `simulated_hours_from_rounds(r, mpr)` (`:390-405`): `round(r×mpr/60, 2)`; bad or non-positive input → 0.0.

### `backend/app/services/decision_channel.py`

- **Module docstring** (`decision_channel.py:1-35`):
  - It describes a post-simulation replay. Elicitation is a pure function of the frozen log plus the immutable base distribution, which makes it safe to run in parallel and to cache by roster.
  - In calendar mode (`round_dates` given), the prompt switches to a "时段" (period) frame, the cache key becomes (signature, label), rows carry `period_end`, and the output schema is v3.
  - It says the channel is "default OFF" (`:13`), which is stale.
- **Constants** (`:60-71`):
  - `PUBLIC_BLOCK_ID="__public__"` (`:60`)
  - `ABSTAIN_TOKEN="弃权"` (`:63`)
  - `_UNIT_ZH` (unit→Chinese, `:66-67`)
  - `_UNIT_NOMINAL_DAYS`, which duplicates `sim_timeline.NOMINAL` (`:70-71`)
- **`_cfg(name, default)`** (`:74-80`): `getattr(Config, name, default)`. Any import error returns the default. It **does not read `os.environ` directly**, so only real `Config` attributes are tunable.
- **Prompt rendering**:
  - `_render_incentives` (`:83-92`): `利好于：gains_if；受损于：loses_if`.
  - `_render_roster_line` (`:95-114`): `- id={id} {name}（立场：{stance}，影响力：{influence}）`, optionally followed by `｜` + incentives, `当前状态：affect` and `本轮发声：post[:120]`.
- **Period helpers**:
  - `_period_days` (`:117-126`): inclusive day count, or None.
  - `_unit_for_days` (`:129-131`): nearest nominal unit. Verified: 11 days → week.
  - `_infer_calendar_unit` (`:134-141`): unit of the median period length.
  - `_render_period_block` (`:144-170`): `时段：第 {n}/{N} 轮，覆盖 {start} 至 {end}（一个{unit_zh}）。` plus `距离判定日 {horizon} 还有 {days} 天。` (only when both dates parse) and an instruction line. Missing period fields return `""`.
- **`_build_round_decision_prompt(...)`** (`:173-213`), a single Chinese user prompt:
  - mutually exclusive scenario list
  - the **seed base distribution shown as rounded percentages** (`:191-198`), sorted descending, and only the base shares, never the evolving ones
  - the period block, or else `第 N 轮（对应时点约 as_of）的`
  - commitment semantics
  - the optional abstain line (`:199-201`)
  - a strict JSON schema `{"decisions":[{agent_id, scenario, magnitude, confidence}]}`
  - the roster
- **`_elicit_round_decisions(llm, scenarios, active, round_num, ...)`** (`:216-286`), which returns `(decisions, round_status)`:
  - empty roster or scenarios → `([], missing)` (`:244-245`)
  - `llm.chat_json(messages=[user prompt], temperature=0.2, max_tokens=2048)` (`:247-255`). Prompt building is inside the `try`.
  - any exception → warning log and `failed` (`:256-261`)
  - a payload whose `decisions` is not a list → `failed` (`:262-265`)
  - per item: `scenario == "弃权"` counts as an abstention; non-candidate scenarios are dropped; otherwise `{agent_id, scenario, magnitude (default 1.0), confidence (default 0.7)}` (`:268-283`)
  - result: any valid item → `committed`; else `abstained` if any abstentions; else `silent` (`:284-286`)
- **`elicit_round(roster, period_ctx)`** (`:289-340`), the shared single-round core used by both in-band and post-hoc:
  - No `llm`, scenarios or roster → `period_ctx["round_status"]="missing"` and `[]` (`:311-314`).
  - It calls `_elicit_round_decisions` and **writes `period_ctx["round_status"]`** (`:320-326`).
  - Each decision gets `round`, plus `outcome_power` taken from the roster entry and `period_end`. `weight` is computed via `commitments_from_decisions([c])` (`:327-339`).
  - `c.get("agent_id") in pmap` (`:333`) **raises `TypeError` if the LLM returns an unhashable agent_id** such as a list (verified). No try wraps it.
- **Weights and roster**:
  - `_to_weight` (`:343-347`).
  - `_activation_weight_map` (`:350-357`): `{agent_id: influence_weight (default 1.0)}`.
  - `_outcome_power_map` (`:360-380`): only explicit `outcome_power` values, with no fallback to visibility (I-15).
  - `_agent_meta_map` (`:383-396`): `{agent_id, name (entity_name|name), stance, influence (influence|influence_weight), gains_if, loses_if}`.
  - `_build_active_roster(entries, activation, power, cap)` (`:399-439`):
    - Entries are sorted by activation, descending.
    - The top `cap` stay individual. Agents with unknown power get 1.0 and `outcome_power_known=False`.
    - The tail collapses into one `__public__` entry with `outcome_power = influence = Σ tail power` and `stance="mixed"`.
  - `_roster_signature` (`:442-451`): a sorted tuple of `(id, stance, gains_if, loses_if, post)`. Round and affect are not part of it.
- **Date and inertia helpers**:
  - `_safe_round_to_date` (`:454-461`).
  - `_parse_date` (`:464-470`): ISO date from the first 10 characters only.
  - `_inertia_for_gap(base, prev, cur, avg_gap)` (`:473-490`): `base ** (gap/avg_gap)` clamped to [0.3, 0.95]. It returns None (meaning: use base) if base ∉ (0,1), avg_gap ≤ 0, a date is missing, or the gap is negative. Verified with base 0.7 and avg 30.44: a 20-day gap → 0.791; 30 days → 0.704; 365 days → 0.3.
  - `_avg_gap_days(seed, as_of_by_round)` (`:493-503`): hours-path average days per round.
- **`_fan_out_elicit(tasks, concurrency)`** (`:506-532`): one `elicit_round` per unique key. It runs serially when there is 1 worker, otherwise in a `ThreadPoolExecutor(thread_name_prefix="decision-elicit")` via `ex.map`. There is no per-task try/except, so an exception propagates.
- **`run_decision_channel(actions, agent_configs, seed, llm, *, inertia=.7, conv_eps=.02, round_to_date=None, round_dates=None, max_active_per_round=60, concurrency=None, abstain_allowed=True, posts_by_round=None, affect_by_agent=None)`** (`:535-775`):
  1. No scenarios in the seed → `{}` (`:566-568`).
  2. A `WorldState` is built from the seed, with `base_shares` frozen (`:570-571`).
  3. The activation, power and meta maps are built (`:572-574`). `cap` comes from `_cfg("DECISION_CHANNEL_MAX_ACTIVE", max_active_per_round)` (`:578`). `concurrency` defaults to `Config.OASIS_SEMAPHORE` (24) (`:579-580`).
  4. Per-round rosters are built from `actions` (`:584-605`). It reads `round`, falling back to `round_num`; rounds < 1 and actions without `agent_id` are skipped. Each actor appears once and is enriched with `post` (`posts_by_round`, else `a.post`, else `a.text`) and `affect`. Rosters are then capped (`:607-611`).
  5. Calendar mapping (`:615-629`): `period_by_round[p.round+1]` (0-based → 1-based). `calendar_unit` is inferred, `n_rounds_total = len(period_by_round)`, and `as_of_by_round[r] = period_end`, falling back to `round_to_date(r)`.
  6. Phase 1 (`:634-653`): key = `(roster_signature, label or as_of)`; one ctx per unique key, which also carries `period/n_rounds/horizon_date/unit` in calendar mode. Then the fan-out runs.
  7. Phase 2 serial replay (`:658-719`):
     - `avg_gap` is the unit's nominal days in calendar mode, else `_avg_gap_days` (`:658-661`).
     - The entropy floor is on only in calendar mode with `WORLDSTATE_ENTROPY_MIX` (`:662`). `conv_window = SIM_CONVERGENCE_WINDOW` (`:663`).
     - Trajectory row 0 is `{"round":0, **outcome}`, plus `as_of` in calendar mode (`:664-666`).
     - Per round: audit decisions are rewritten with the true round, `outcome_power` and `period_end`, with `weight` stripped (`:677-689`). `eff_inertia` comes from `_inertia_for_gap` (`:691`) and `entropy_days` from `_period_days` (`:692`). `round_status` is read from the shared task ctx, defaulting to `missing` (`:695-696`).
     - It calls `ws.step(commitments_from_decisions(decisions), inertia, entropy_mix_days, round_status)` (`:697-698`) and appends a snapshot row with `round_status`, `as_of`, `period_start/period_end/label` (`:699-707`).
     - Windowed convergence (`:712-717`): `converged_at` is the first round where `ws.converged` has held for `conv_window` consecutive rounds and `rnd ≥ 2`.
  8. Verdict (`:733-749`):
     - `validity` is `invalid` if there are 0 valid transitions; `inconclusive` if any round failed or coverage < 0.5; otherwise `valid`.
     - `forecast_effect` is `no_update` unless the run is valid. A valid run is `diagnostic_only`, unless `SIMULATION_FORECAST_EFFECT=="no_update"`; `validated_update` and `legacy_prompt` both collapse to `diagnostic_only`.
  9. Result (`:750-774`): `{outcome, trajectory, decisions, converged_at, n_rounds = max round, scenarios, schema_version 2, round_accounting, validity, forecast_effect, epistemic_status}`. In calendar mode it adds `schema_version 3`, `mode "calendar"`, `calendar_unit` and `horizon_*` from the seed.

  Verified: 5 identical-roster rounds with no dates make **1 LLM call**. All-failed → `invalid/no_update`. 14 all-abstain rounds → `converged_at=8`, `converged`, `valid`.

---

## Control flow

**A. Config generation (PREPARE, backend process)**
1. `SimulationConfigGenerator.generate_config` resets `_temporal_timeline` (`simulation_config_generator.py:508`). If `Config.SIM_TEMPORAL_MODE == "calendar"` it calls `_build_temporal_timeline` (`:552-570`), and on any exception it falls back to hours mode.
2. `_build_temporal_timeline` (`:937-990`):
   - `parse_as_of(actors.as_of_date)`, falling back to today with the warning `as_of_defaulted`.
   - `sim_timeline.extract_horizon(requirement + "\n" + central_question)`, then `_llm_extract_horizon` (one JSON LLM call, re-validated against the 30-year window, confidence 0.7, `:992-1026`), then `default_horizon(as_of, SIM_HORIZON_DEFAULT_MONTHS)`.
   - `target_max = min(SIM_CALENDAR_TARGET_MAX_ROUNDS, max_rounds, OASIS_DEFAULT_MAX_ROUNDS)`, then `build_timeline(..., reference_max=SIM_CALENDAR_TARGET_MAX_ROUNDS, hard_max=SIM_CALENDAR_HARD_MAX_ROUNDS)`.
3. Calendar-mode time_config compat shim: `total_simulation_hours = n_rounds`, `minutes_per_round = 60` (`simulation_config_generator.py:581-582`).
4. `_build_scheduled_events` calendar branch (`:1069-1090`): it calls `actors.events_to_calendar_rounds`, which uses `round_for_date` (`actors.py:1462-1522`). Events after the horizon are stored in `timeline.beyond_horizon_events`, and unparsed dates add the warning `event_date_unparsed:<n>`. Content is prefixed `"[{date}] "` (`:1131`).
5. `asdict(timeline)` is serialized as `temporal_config` (`:796`).

**B. PREPARE seed injection (orchestrator)**
- When `_calendar_mode() or Config.SIM_DECISION_CHANNEL` (`pipeline_orchestrator.py:12878-12879`), it injects `world_state_seed_from_actors(actors)` (`actors.py:2613-2679`).
- It then adds `as_of_date` (raw `actors.as_of_date`, not normalized) and `horizon_date` (via `_infer_horizon_date` → `extract_horizon`, `pipeline_orchestrator.py:8461-8484`). In calendar mode, the `temporal_config` values for `horizon_date`, `horizon_source` and `horizon_defaulted` override (`:12905-12909`).
- Scenario-overlay injected events are bucketed with `round_for_date`. An undated event goes to round 0, and one beyond the last period is clamped to the last round (`pipeline_orchestrator.py:8384-8427`).

**C. Subprocess round loop (`run_parallel_simulation.py`, per platform coroutine; twitter `:4726-5216`, reddit `:5262-5767`)**
- `calendar = temporal_config.mode == "calendar"` (`:4729`, `:5265`). This is the runtime dispatch; `SIM_TEMPORAL_MODE` is never read here.
- `total_rounds` in calendar mode is `temporal_config.n_rounds`, and **runtime `max_rounds` is ignored** (`_resolve_total_rounds`, `:2591-2625`, specifically `:2606-2619`).
- Before the loop:
  - `_round_periods` maps each 0-based round to its period (`:4948-4958`).
  - `dynamics_tracker = _build_dynamics_tracker` (`:4966`, gated on `Config.SIM_AGENT_DYNAMICS`).
  - `_inband_evo = _get_inband_evolution(...)` in calendar mode (`:4989-4990`). It is shared by both platforms, keyed by the absolute sim dir (`:3692-3720`).
- Per round `round_num` (0-based):
  1. `fire_scheduled_events` (`:2531-2572`).
  2. Agent activation (`get_active_agents_for_round`, `:1802-1876`). In calendar mode: no diurnal gating, and `cadence=="principal"` agents are always active.
  3. If no agents are active: `_inband_evo.heartbeat` (`:5071-5074`).
  4. `_inject_agent_dynamics` (`:5079`, which writes the SYSTEM role at `:1923`).
  5. `_inject_period_context(... _scheduled_events_due(...), world_delta_text ...)` (`:5083-5094`), which writes the USER role at `:2018`.
  6. `env.step`. On failure: heartbeat (`:5118-5121`).
  7. Fetch actions, then the reaction phase.
  8. `_observe_agent_dynamics(tracker, actual_actions, name_to_id)` (`:5163`).
  9. Engagement sampler.
  10. `_inband_evo.deliver(platform, round_num, period, actual_actions, due_events)` and `world_delta_text = latest_delta()` (`:5179-5182`).
- After the loop: `platform_done` (`:5199-5200`), then `{platform}_dynamics_summary.json` is written (`:5206-5216`).
- `_InbandWorldEvolution.deliver` (`:3452-3481`):
  - It buffers actions and events per round, de-duplicating events by `(date, content)` across the two platforms, and bumps the platform watermark.
  - `_advance` (`:3554-3572`) then steps every buffered round ≤ min(watermark of live platforms), but only once every expected platform has reported.
  - `_step_round` (`:3574-3689`):
    - It builds the merged roster (first post per actor) and calls `_dc._build_active_roster` and then `_dc.elicit_round`. `round_status` is taken from ctx, or `"missing"` when the roster is empty (`:3615`).
    - It computes `_dc._inertia_for_gap` (prev_date → period_end, `avg_gap` = unit nominal days) and the entropy days, then calls `WorldState.step`.
    - `leader_move` is the up/down/flat direction of the leader versus the previous shares. `build_world_delta` is called on the actions with content plus the events.
    - It appends the trajectory row and appends a line to `world_digest.jsonl`.
    - Convergence is tracked as a signal only.
- `platform_done` (`:3497-3506`): once all platforms are done it calls `force_finalize` (`:3508-3551`). That flushes the buffers and, if ≥1 round was stepped, writes `world_state_trajectory.json` (v3) and `decisions.jsonl`, then sets `_INBAND_TRAJ_WRITTEN`.

**D. Post-sim (main, after gather)**
- `_finalize_inband_world_evolution` (`:3723-3734`, called at `:5975`).
- If `os.environ["SIM_DECISION_CHANNEL"]=="true"` (default `"false"`), the seed has scenarios, and in-band did **not** write (`:5983-5986`):
  - `run_decision_channel(_read_actions_for_decision_channel(dir), agent_configs, seed, LLMClient, inertia=SIM_DECISION_INERTIA, conv_eps=SIM_CONVERGENCE_EPS, round_to_date=_build_round_to_date(seed, config), round_dates=temporal round_dates if calendar)` (`:5987-6014`).
  - It writes the trajectory and `decisions.jsonl` (`:6015-6022`).

**E. Downstream reads** — see Cross-module edges.

---

## Data & artifacts

**`simulation_config.json` → `temporal_config`** (from `asdict(SimulationTimeline)`, `simulation_config_generator.py:796`): `schema_version=1`, `mode="calendar"`, `as_of_date`, `horizon_date`, `horizon_source`, `horizon_text`, `horizon_defaulted`, `unit`, `unit_stride`, `n_rounds`, `round_dates: [{round (0-based), period_start, period_end, label}]`, `span_days`, `target_max_rounds`, `round_cap_coarsened`, `beyond_horizon_events`, `warnings` (`sim_timeline.py:73-90`). It is absent in hours mode.

**`simulation_config.json` → `world_state_seed`**: `{scenarios:[str], base_rates:{name:prob}, uniform_prior:bool, as_of_date, horizon_date, horizon_source?, horizon_defaulted?}` (`actors.py:2679`, `pipeline_orchestrator.py:12895-12909`).

**`simulation_config.json` → `agent_configs[]`** keys consumed by this slice:
- `agent_id`
- `sentiment_bias`, `influence` / `influence_weight` (dynamics seed)
- `influence_weight` (activation)
- `outcome_power` (power; **no producer exists**, see Surprises)
- `entity_name` / `name`, `stance`, `gains_if`, `loses_if` (prompt)

**`<sim_dir>/world_state_trajectory.json`** has two writers:
- **Post-hoc writer** (`decision_channel.py:750-774`, written at `run_parallel_simulation.py:6016-6017`): schema 2 (hours) or 3 (calendar).
  - Top-level keys: `outcome`, `trajectory[]`, `decisions[]`, `converged_at`, `n_rounds`, `scenarios`, `schema_version`, `round_accounting`, `validity`, `forecast_effect`, `epistemic_status`. In v3 also `mode`, `calendar_unit`, `horizon_date`, `horizon_source`, `horizon_defaulted`.
- **In-band writer** (`run_parallel_simulation.py:3523-3542`): always schema 3, with `outcome`, `trajectory`, `decisions`, `converged_at`, `n_rounds`, `scenarios`, `mode`, `calendar_unit`, `horizon_*`. It has **no top-level `validity`, `forecast_effect`, `round_accounting` or `epistemic_status`**; those last two exist only nested inside `outcome`.
- Trajectory rows are `{round, shares, leader, leader_share, rounds, ewma_delta, converged, convergence_state, converged_at, uniform_prior, round_accounting, epistemic_status, round_status, as_of?, period_start?, period_end?, label?}`. Row 0 has no `round_status`.

**`<sim_dir>/decisions.jsonl`**: one JSON row per commitment, `{agent_id, scenario, magnitude, confidence, round (1-based), outcome_power?, period_end?}`, with `weight` stripped. Written at `run_parallel_simulation.py:3543-3545` (in-band) and `:6018-6020` (post-hoc).

**`<sim_dir>/world_digest.jsonl`** (in-band only, **append mode**, `run_parallel_simulation.py:3660-3673`): `{round, period_start, period_end, digest, shares, leader, delta:{scenario: Δshare}}`. There is no reader in `backend/app` or `backend/scripts`, and it is not in `_STALE_DERIVED_ARTIFACTS` (`simulation_runner.py:1292-1306`).

**`<sim_dir>/{twitter,reddit}_dynamics_summary.json`**: `dynamics_summary()` output (`run_parallel_simulation.py:5210-5214`). It is read into `run_summary.agent_dynamics` (`simulation_runner.py:2151-2160`, `:2268-2269`).

**`run_summary.json` fields derived from this slice**:
- `simulated_hours` (via `simulated_hours_from_rounds`, `simulation_runner.py:2184-2186`)
- `organic_ratio_warnings` (via `classify_organic_action` / `detect_organic_ratio_collapse`, `:2193-2210`)
- calendar keys `temporal_mode`, `calendar_unit`, `total_periods`, `simulated_span_days`, `horizon_*`, `coverage_end` (`:2234-2263`)

**In-memory structures**:
- `WorldState`: `scenarios`, `inertia`, `shares`, `_seed_shares`, `history`, `_last_delta`, `_ewma_delta`, `converged_at`, `round_statuses`, `uniform_prior` (`worldstate.py:130-157`).
- `AgentDynamicsTracker._state[aid] = {mood, energy, opinion_strength, fatigue}` (`agent_dynamics.py:114-115`).
- `_InbandWorldEvolution`: `_pending[round] = {period, actions, events, event_keys}`, `_watermark[platform]`, `_done`, `_delta_text`, `_trajectory`, `_decisions`, `_stable_streak` (`run_parallel_simulation.py:3424-3439`, `:3457-3462`).
- Module globals: `_INBAND_EVOLUTIONS` and `_INBAND_TRAJ_WRITTEN` (`:3361-3363`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `SIM_TEMPORAL_MODE` | `calendar` | Config generation only: calendar builds `temporal_config`; `hours` builds none. The runtime dispatches on the `temporal_config` block. | `config.py:1067`; `simulation_config_generator.py:552`; `pipeline_orchestrator.py:7296-7303` |
| `SIM_CALENDAR_TARGET_MAX_ROUNDS` | 36 | Soft round budget for unit selection; also the `reference_max` used for the coarsening audit | `config.py:1069`; `simulation_config_generator.py:971`, `:985` |
| `SIM_CALENDAR_HARD_MAX_ROUNDS` | 48 | Ceiling for anti-aliasing refinement (can exceed the soft target) | `config.py:1071`; `sim_timeline.py:376` |
| `SIM_HORIZON_DEFAULT_MONTHS` | 12 | Default horizon when deterministic and LLM extraction both fail | `config.py:1073`; `simulation_config_generator.py:967-969` |
| `OASIS_DEFAULT_MAX_ROUNDS` | 36 | Also caps calendar `target_max` at generation time | `config.py:1063`; `simulation_config_generator.py:978-980` |
| `SIM_WORLD_DELTA` | true | Includes the "WHAT CHANGED LAST PERIOD" section in the WORLD CLOCK header | `config.py:1075`; `run_parallel_simulation.py:2007-2009` |
| `SIM_DECISION_CHANNEL_INBAND` | true | Enables in-band evolution (calendar mode only); **independent of `SIM_DECISION_CHANNEL`** | `config.py:1077`; `run_parallel_simulation.py:3698` |
| `WORLDSTATE_ENTROPY_MIX` | true | Calendar-only entropy floor toward the seed prior | `config.py:1079`; `decision_channel.py:662`; `run_parallel_simulation.py:3410` |
| `SIM_DECISION_CHANNEL` | Config `true`, but the subprocess post-hoc gate reads `os.environ` with default `"false"` | Backend: gates seed injection in hours mode. Subprocess: gates the post-hoc replay. | `config.py:1483`; `pipeline_orchestrator.py:12879`; `run_parallel_simulation.py:5984` |
| `SIM_DECISION_INERTIA` | 0.7 | WorldState inertia (prior persistence) | `config.py:1498`; `run_parallel_simulation.py:3394-3397`, `:5992-5995` |
| `SIM_CONVERGENCE_EPS` | 0.02 | EWMA settle threshold | `config.py:1503`; `run_parallel_simulation.py:3398-3401`, `:5996-5999` |
| `SIM_CONVERGENCE_WINDOW` | 3 | Consecutive converged rounds required before `converged_at` is set | `config.py:1504`; `decision_channel.py:663`; `run_parallel_simulation.py:3409` |
| `SIM_CONVERGENCE_STOP` | true | **Defined but never read** (no early stop anywhere) | `config.py:1502` |
| `SIMULATION_FORECAST_EFFECT` | `diagnostic_only` | Valid runs → `diagnostic_only` unless `no_update`; also suppresses the report signal pack when `no_update` | `config.py:1492-1497`; `decision_channel.py:745-749`; `report_agent.py:2386-2389` |
| `DECISION_CHANNEL_MAX_ACTIVE` | 60 (effective) | Roster cap. **Not a Config attribute**, so `_cfg` always falls back to the default and it is not env-tunable. | `decision_channel.py:578`; `run_parallel_simulation.py:3408` |
| `OASIS_SEMAPHORE` | 24 | Post-hoc elicitation thread-pool size | `config.py:1091`; `decision_channel.py:579-580` |
| `SIM_AGENT_DYNAMICS` | true | Builds the `AgentDynamicsTracker` in the subprocess | `config.py:1399`; `run_parallel_simulation.py:1890` |
| `SIM_DYNAMICS_MOOD_LR` / `_OPINION_LR` / `_FATIGUE_RATE` / `_FATIGUE_DECAY` | .25 / .15 / .20 / .10 | Tracker learning rates | `config.py:1473-1476`; `agent_dynamics.py:142-148` |
| `SIM_ENGAGEMENT_SAMPLER`, `SIM_ENGAGEMENT_RATE` | `auto`, 0.3 | Runtime use of `sample_engagement_likes` | `config.py:612-613`; `run_parallel_simulation.py:3999` |
| `SIM_MAX_FOLLOWS_PER_AGENT_ROUND` | 3 | `throttle_seed_follows` cap | `config.py:623`; `run_parallel_simulation.py:2495` |
| `SIM_ORGANIC_RATIO_DETECTOR`, `SIM_ORGANIC_RATIO_MIN_CONSECUTIVE` | true, 3 | Enables collapse detection in `run_summary` | `config.py:626-627`; `simulation_runner.py:2195-2208` |

---

## External calls

- **LLM, decision elicitation**: `llm.chat_json(messages=[{"role":"user",...}], temperature=0.2, max_tokens=2048)` (`decision_channel.py:247-255`). The client is injected:
  - in-band: `_wrap_llm_client_usage(LLMClient())` (`run_parallel_simulation.py:3442-3449`)
  - post-hoc: `_wrap_llm_client_usage(LLMClient())` (`run_parallel_simulation.py:6005`)

  There is one call per unique roster key: per round in-band, and per unique (signature, label/date) key post-hoc. Post-hoc calls run in parallel threads (`decision_channel.py:529-531`). In-band calls are made **synchronously inside the asyncio round loop** (`run_parallel_simulation.py:3609`), and `LLMClient.chat_json` is a plain `def` (`llm_client.py:597`). The call therefore blocks both platform coroutines while it runs.
- **LLM, horizon fallback** (caller side, not in the slice): `SimulationConfigGenerator._llm_extract_horizon` → `_call_llm_with_retry` (`simulation_config_generator.py:992-1026`).
- **No HTTP, subprocess or DB calls inside the slice.** All file I/O happens in callers (`run_parallel_simulation.py`, `simulation_runner.py`, `report_agent.py`, `pipeline_orchestrator.py`, `api/simulation.py`).
- **Config import**: `decision_channel._cfg` (`:74-80`) and `AgentDynamicsTracker.from_config` (`:127-128`) lazily import `app.config.Config`. That import runs `load_dotenv(override=True)` (`config.py:15-24`).

---

## Cross-module edges

**Callers into the slice**

| Slice API | Caller(s) |
|---|---|
| `dates.parse_as_of` | `zep_tools.py:31` (and `:939`, `:1516`, `:1837`, `:1863-1864`; bi-temporal edge filtering); `actors.py:1409`, `:1489`, `:2972` (events and indicator scheduling); `pipeline_orchestrator.py:77` (as_of validation, overlay bucketing, horizon); `simulation_config_generator.py:39`, `:955`, `:1018`, `:1081`; `forecast_extractor.py:2709`, `:2958` |
| `sim_timeline.extract_horizon` | `simulation_config_generator.py:963`; `pipeline_orchestrator.py:8479` (`_infer_horizon_date`); `forecast_ledger.py:206` (`_year_end`, which also reads private `_TIER4`, `:204`); `forecast_extractor.py:2963` |
| `sim_timeline.default_horizon` / `build_timeline` / `_add_months` / `HorizonResult` | `simulation_config_generator.py:967`, `:981`, `:1022`, `:1026` |
| `sim_timeline.round_for_date` | `actors.events_to_calendar_rounds` (`actors.py:1490`, `:1515`); `pipeline_orchestrator.py:8420` (overlay events) |
| `agent_dynamics.AgentDynamicsTracker` / `extract_round_signals` | `run_parallel_simulation.py:1892-1893`, `:1933-1935` |
| `agent_dynamics.throttle_seed_follows` / `sample_engagement_likes` | `run_parallel_simulation.py:2495`, `:3999` |
| `agent_dynamics.simulated_hours_from_rounds` / `classify_organic_action` / `detect_organic_ratio_collapse` | `simulation_runner.py:2184`, `:2196-2208` |
| `world_delta.build_world_delta` | `run_parallel_simulation.py:3634-3645` (in-band only) |
| `worldstate.WorldState` | `decision_channel.py:570`; `run_parallel_simulation.py:3383`, `:3403` |
| `decision_channel.elicit_round`, `_build_active_roster`, `_activation_weight_map`, `_outcome_power_map`, `_agent_meta_map`, `_cfg`, `_infer_calendar_unit`, `_UNIT_NOMINAL_DAYS`, `_inertia_for_gap`, `_period_days` (private helpers used cross-module) | `run_parallel_simulation.py:3382-3415`, `:3601-3622` |
| `decision_channel.run_decision_channel` | `run_parallel_simulation.py:5988-6014` |

**Readers of slice outputs**

- `world_state_trajectory.json` is read by:
  - `report_agent._world_state_block` (`report_agent.py:2472-2541`, shows the validity warning only from top-level `validity`, `:2496-2499`)
  - `report_agent._temporal_horizon_date` (`:2544+`)
  - the chart artifacts loader (`:8975-8982`)
  - `_scenario_diff_structured` (`:9318-9350`, uses `outcome.shares` regardless of validity)
  - `report_visualizer.build_worldstate_area` / `_html` (`:2149`, `:3106`, `:4487-4491`, `:4602-4605`; dates via `_trajectory_row_date` `:5235-5252`)
  - `pipeline_orchestrator._log_decision_channel_outcome` (`:10738-10790`)
  - `api/simulation.get_simulation_trajectory` (`api/simulation.py:2006-2060`)
  - `scripts/backfill_report_visuals.py:360-363`
- The world-state block text is re-parsed by `forecast_extractor` (`_SIM_SIGNAL_TAXONOMY` `:1142-1145`, `_WS_OUTCOME_HEADER_RE` `:1223`). The header string has drifted; see Surprises.

**Slice calls out to**: `app.config.Config` (lazy) and `llm.chat_json` (injected). `sim_timeline` → `dates`. `decision_channel` → `worldstate`.

---

## Invariants, gates, validation

- `parse_as_of` and `extract_horizon` never raise (`dates.py:9`, `sim_timeline.py:334-335`). `default_horizon` and `build_timeline` **do** raise `ValueError` on an unparseable `as_of` (`sim_timeline.py:341-342`, `:529-530`).
- Horizon candidates must satisfy `as_of < d ≤ as_of + 30y` (`sim_timeline.py:283-286`). The LLM fallback re-applies the same window (`simulation_config_generator.py:1022-1025`).
- Round periods partition `(as_of, horizon]` without gaps or overlap; the first starts at `as_of+1` and the last ends at the horizon (`sim_timeline.py:440-442`, `:461-463`). `n_rounds == len(round_dates)` (`:563`).
- Agent-facing text never contains numeric WorldState shares: `build_world_delta` emits a direction word only (`world_delta.py:8-11`, `:70-74`), and the WORLD CLOCK uses only the delta (`run_parallel_simulation.py:2007-2009`). The elicitation prompt (seen by the LLM elicitor, not by OASIS agents) **does** show seed base shares as percentages (`decision_channel.py:191-198`), but never the evolving shares.
- WorldState shares always sum to 1 (to 6 dp), and the entropy floor keeps λ ≤ 0.05 (`worldstate.py:70-78`, `:224`).
- I-16: failed, silent and missing rounds freeze the state and do not update the EWMA (`worldstate.py:195-200`). Convergence requires the policy guards (`:255-273`).
- I-15: visibility (`influence_weight`) is never used as outcome power (`decision_channel.py:360-380`, `:416-422`).
- I-11: outputs carry `epistemic_status="elicited_model_projection"` (`worldstate.py:303`, `decision_channel.py:763`). Only valid runs can be `diagnostic_only`, and nothing ever yields an updating effect (`decision_channel.py:742-749`).
- Elicitation only ever sees the immutable base distribution, which is what makes the parallel fan-out and caching sound (`decision_channel.py:17-21`, `:571`).
- In-band rounds are stepped strictly in round order, only after all expected platforms report (`run_parallel_simulation.py:3554-3572`).

---

## Failure modes & recovery

- **Horizon not extractable**: the order is deterministic tiers → LLM → `default_horizon(12m)`. The warnings `horizon_defaulted_12_months` or `horizon_invalid_defaulted` are recorded (`sim_timeline.py:533-539`), and `report_agent` discloses the defaulted horizon (`report_agent.py:2536-2538`).
- **Timeline build exception**: hours-mode fallback (`simulation_config_generator.py:567-569`).
- **LLM elicitation failure**: the round becomes `failed` (`decision_channel.py:256-261`). WorldState freezes, and the run verdict becomes `inconclusive` or `invalid` (post-hoc only).
- **LLM client cannot be built in-band**: `_llm=None`, so every round is `missing` and the trajectory is flat at the prior. The in-band docstring still claims "prior + entropy floor" (`run_parallel_simulation.py:3374-3375`).
- **In-band exception in a round**: the delta becomes `""`, so the next header shows `(first period)`. The round produces **no trajectory row and no status** (`run_parallel_simulation.py:3687-3689`).
- **Platform crash**: `_finalize_inband_world_evolution` force-flushes (`run_parallel_simulation.py:3723-3734`). If nothing was stepped, nothing is written and the post-hoc fallback may run (env-gated).
- **Resume**: the in-band WorldState is rebuilt from the seed, so the trajectory covers only the resumed rounds (documented at `run_parallel_simulation.py:3375-3376`). `world_digest.jsonl` keeps appending.
- **Re-run**: the trajectory, `decisions.jsonl` and the dynamics summaries are rotated (`simulation_runner.py:1292-1306`); `world_digest.jsonl` is not.
- **`world_delta` / `agent_dynamics` errors**: swallowed (`world_delta.py:79-80`; `run_parallel_simulation.py:1895-1898`, `:1936-1937`).

---

## Surprises

1. **Agent-dynamics state line is probably never seen by the model (suspected bug).** `_inject_agent_dynamics` writes it as `OpenAIBackendRole.SYSTEM` (`run_parallel_simulation.py:1922-1923`). The same file's `_inject_period_context` documents that camel 0.2.78's `ScoreBasedContextCreator` keeps only `records[0]` as the system message and drops later SYSTEM records (`run_parallel_simulation.py:1945-1953`). The installed `backend/.venv/.../camel/memories/context_creators/score_based.py:115-120`, `:372-376` confirms it: SYSTEM records after index 0 are skipped. The tracker still runs and `dynamics_summary.active` can be `True`, even though the prompt effect never reaches the model.
2. **Opinion strength saturates at round 1 (suspected bug).** `opinion_strength` is seeded from `influence` or `influence_weight` clamped to [0,1] (`agent_dynamics.py:109-113`). `AgentActivityConfig` has no `influence` field (`simulation_config_generator.py:200-250`) and `influence_weight` defaults to 1.0, typically 0.8–3.0 (`:222`, `:2876`). Every agent with weight ≥0.7 therefore starts at 1.0 and gets "立场已明显强化" from round 1. Verified, and contrary to the docstring at `agent_dynamics.py:194-195`. It also can never harden further.
3. **`outcome_power` has no producer.** Only `decision_channel` and `run_parallel_simulation.py:3406` mention it. So `_outcome_power_map` is always `{}`, every actor gets 1.0 with `outcome_power_known=False`, and commitments are effectively **equal-weight × confidence**. The `__public__` block's power equals the number of collapsed tail agents (`decision_channel.py:430-438`).
4. **The in-band trajectory lacks the Foglamp run verdict.** `force_finalize` omits the top-level `validity`, `forecast_effect`, `round_accounting` and `epistemic_status` (`run_parallel_simulation.py:3523-3537`), which `run_decision_channel` adds (`decision_channel.py:733-764`). `report_agent._world_state_block` reads only the top-level `validity` (`report_agent.py:2496-2499`). On the default calendar path, a dead or failed channel therefore never triggers the "⚠️ 有效性裁定" warning (suspected).
5. **A small explicit round cap can *increase* rounds (suspected bug).** When no unit within `target_max` gives ≥8 rounds, the anti-aliasing refinement walks to finer units up to `hard_max` (`sim_timeline.py:374-378`). Verified: a 446-day span with `target_max` 3–12 gives half_month × 29 rounds, while 36 gives month × 15. The audit records this as `round_cap_coarsened` (`from=month,to=half_month`), although it is a refinement (`sim_timeline.py:544-548`). The runtime ignores `max_rounds` in calendar mode (`run_parallel_simulation.py:2614-2619`), so a smoke test with `max_rounds=3` would run 29 rounds. DRF_ARCHITECTURE.md:1052-1053 claims max_rounds "coarsens the unit".
6. **The post-hoc gate's default disagrees with Config.** The subprocess checks `os.environ.get("SIM_DECISION_CHANNEL","false")` (`run_parallel_simulation.py:5984`), while `Config.SIM_DECISION_CHANNEL` defaults to true (`config.py:1483`). The subprocess env is a plain copy (`simulation_runner.py:929`) and Config defaults never reach `os.environ`. Unless `.env` or the shell sets the key (not inspected; `.env.example:480` has it commented out), hours-mode runs inject a seed (`pipeline_orchestrator.py:12879`) but never run the channel. The orchestrator then logs "已种子 N 情景但轨迹缺失" (`:10783-10786`).
7. **`SIM_DECISION_CHANNEL=false` does not disable in-band evolution in calendar mode.** `_get_inband_evolution` checks only `SIM_DECISION_CHANNEL_INBAND` and the seed scenarios (`run_parallel_simulation.py:3697-3707`), and seed injection is unconditional in calendar mode (`pipeline_orchestrator.py:12876-12879`).
8. **`SIM_CONVERGENCE_STOP` is dead.** It is defined at `config.py:1502` and has no reader. Its comment promises a "72→~20 rounds" saving. Calendar mode explicitly never early-stops (`run_parallel_simulation.py:3376-3377`), and the hours post-hoc path only records `converged_at`.
9. **`DECISION_CHANNEL_MAX_ACTIVE` is not tunable.** `_cfg` reads only `Config` attributes (`decision_channel.py:74-80`), and Config has no such attribute. The cap is always the call-site default of 60 (`decision_channel.py:578`, `run_parallel_simulation.py:3408`), despite DRF_ARCHITECTURE.md:999.
10. **The WORLD CLOCK delta can be stale for the faster platform.** `_advance` steps only up to the slowest live platform's watermark (`run_parallel_simulation.py:3561-3569`). The faster platform's next header therefore shows an older period's delta under "WHAT CHANGED LAST PERIOD" (`:5181-5182`, `:2007-2008`). In addition, the synchronous `chat_json` in `_step_round` blocks the shared event loop (`:3609`; `llm_client.py:597`).
11. **`world_digest.jsonl` is written but never read or rotated.** It is opened in append mode (`run_parallel_simulation.py:3672`), is absent from `_STALE_DERIVED_ARTIFACTS` (`simulation_runner.py:1292-1306`), and has no reader anywhere in `backend/app` or `backend/scripts`. It accumulates across re-runs and resumes.
12. **Dead rounds leave gaps.** Rounds where no platform delivered actions are neither stepped nor accounted. Post-hoc rosters skip them (`decision_channel.py:584-605`); in-band only heartbeats (`run_parallel_simulation.py:3483-3492`). They are absent from `round_accounting` (not counted as `missing`) and from the trajectory, and the next round's inertia sees a longer gap.
13. **The world-state header string has drifted.** `report_agent` renders `【推演结果分布 P(outcome)…` (`report_agent.py:2494`), but `forecast_extractor` still matches `【预测结果分布\s*P\(outcome\)` (`forecast_extractor.py:1144`, `:1223`). As a result `world_state_outcome_from_signal_pack` (SIM-ADD-3) and the provenance taxonomy marker can no longer match a live block. The tests use both strings (`tests/test_sessionb_sim_additivity.py:60` old, `tests/test_foglamp_containment.py:323` new). This may be partly intentional under Foglamp containment; it is a suspected stale parser.
14. **Unhashable `agent_id` from the LLM raises.** It happens at `elicit_round` `c.get("agent_id") in pmap` (`decision_channel.py:333`). Verified as `TypeError`. Post-hoc, it aborts the whole channel (caught at `run_parallel_simulation.py:6025-6026`). In-band, the round silently disappears (`:3687-3689`). The `_fan_out_elicit` docstring says a failing task degrades to `[]` "for that key only" (`decision_channel.py:512-513`), but there is no per-task guard.
15. **The roster cache is inert in calendar post-hoc mode.** The key includes the period `label` (`decision_channel.py:639-640`) and labels are unique per round. Conversely, on the hours path with `round_to_date=None`, every identical roster across all rounds shares one elicitation and one status (verified: 5 rounds → 1 call).
16. **All-abstain runs report "converged / valid".** Abstention is valid evidence, so the EWMA decays 1.0→<0.02 in 6 rounds. Verified with 14 rounds: `converged_at=8`, `validity=valid`.
17. **Calendar labels and horizon heuristics have quirks.**
    - A merged first stub period takes the stub's slot label, e.g. `2026-10` for 10-26→11-30 (`sim_timeline.py:476-479`).
    - The bare-year tier picks the **maximum** year, so a question mentioning "the 2028 Olympics … by 2026" gets horizon 2028-12-31 (`sim_timeline.py:323-332`).
    - An explicit date ≤ as_of falls through to the bare year of that date (`"2026-10-01"` → 2026-12-31 when as_of is 2026-10-11).
    - `parse_as_of` silently maps US `MM/DD/YYYY` to Jan 1 of the year (`dates.py:66-68`).
18. **Event prefix detection differs between two places.** `world_delta` checks `content.startswith(f"[{date}]")` (`world_delta.py:45`), while `_inject_period_context` checks `content.startswith("[")` (`run_parallel_simulation.py:1983`). Content such as "[Breaking] …" is therefore prefixed by one and not the other. Scenario-overlay events carry no date prefix (`pipeline_orchestrator.py:8429-8437`), unlike key_events (`simulation_config_generator.py:1131`).
19. **Frozen rounds still say "held".** When a round is failed or missing, `leader_move` is computed as `flat`, so the next header says "Momentum: X held this period." even though nothing was measured (`run_parallel_simulation.py:3627-3632`, `world_delta.py:18`).
20. **The nominal-days table is duplicated.** `decision_channel._UNIT_NOMINAL_DAYS` duplicates `sim_timeline.NOMINAL` (`decision_channel.py:70-71` vs `sim_timeline.py:33-40`), and only a comment ties them together.
21. **Doc-vs-code drift.**
    - `worldstate.py:13-14` and `decision_channel.py:13` say `SIM_DECISION_CHANNEL` is "default OFF"; Config says true (`config.py:1483`).
    - DRF_ARCHITECTURE.md:995-996 says the channel runs "post-simulation … wired at `run_parallel_simulation.py:3919-3952`". The default is in-band now, and the post-hoc block is at `:5975-6047`.
    - DRF_ARCHITECTURE.md:1683 lists `SIM_DECISION_CHANNEL (off)`.
    - DRF_ARCHITECTURE.md:1054-1055 calls the WORLD CLOCK a "system record"; it is written with the USER role (`run_parallel_simulation.py:2018`).
    - The `api/simulation.py:2008-2011` docstring says the frontend Step3 polls `/trajectory` during the run. No file under `frontend/src` references it, and the trajectory is written only at the end (`run_parallel_simulation.py:3508-3542`, `:6015-6017`).
    - `agent_dynamics.py:11` says it is used only "when Config.SIM_AGENT_DYNAMICS is on". That is now the default (`config.py:1399`), while the comment at `run_parallel_simulation.py:4965` still says "默认关" (default off).
22. **`magnitude` has no upper clamp**, either in `commitments_from_decisions` (`worldstate.py:105`) or in `WorldState.step` (`:211`). A magnitude of 5 from the LLM outweighs five actors at magnitude 1.
