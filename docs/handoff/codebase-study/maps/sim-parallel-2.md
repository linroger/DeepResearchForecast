# sim-parallel-2 — run_parallel_simulation.py part 2

Scope: `backend/scripts/run_parallel_simulation.py` lines 2531-6154 (end of file), as on disk on branch `main`.
All anchors are `path:line` relative to the repo root. When no path is given, the anchor is in
`backend/scripts/run_parallel_simulation.py`. Helpers defined in part 1 (lines 1-2530) are named but not re-mapped.

## Purpose & position in the pipeline

This is the second half of the OASIS dual-platform simulation subprocess. `SimulationRunner` launches it as
`python run_parallel_simulation.py --config <sim_dir>/simulation_config.json [--config-seal <sha>] [--max-rounds N] [--resume]`,
with cwd set to the simulation directory (`backend/app/services/simulation_runner.py:884-920`, `:942-952`).
The slice holds:

1. **Per-round injection helpers**: scheduled timeline events (2531-2588), the total-round count (2591-2623), the custom OASIS
   `Platform` with the model-free Twitter feed (2626-2743), engagement-like sampling (3892-4066) and the SIM-REACT
   "response phase" that makes agents reply to each other (4069-4689).
2. **Two platform loops**, `run_twitter_simulation` (4692-5225) and `run_reddit_simulation` (5228-5776). They are
   near-identical and drive OASIS `env.step` once per round. They log into `{platform}/actions.jsonl`, write per-round
   checkpoints (3737-3889) and feed an in-band WorldState evolution that both platforms share in calendar mode (3353-3734).
3. **Post-loop analytics**: emergent opinion-dynamics metrics (2746-3252, gated off by default) and the post-hoc
   decision channel fallback (3263-3350, wired in `main` at 5983-6026).
4. **`main()` (5779-6098)**: parses the CLI, validates the config seal, runs both platforms concurrently and isolated,
   writes telemetry and derived artifacts, then stays alive in IPC "wait for commands" mode for interviews
   (`ParallelIPCHandler`, part 1). Signal handling and process exit are at 6101-6154.

Downstream, the report stage reads `world_state_trajectory.json`, `decisions.jsonl`, `llm_health.json`,
`*_dynamics_summary.json` and `actions.jsonl`. `simulation_runner` tails `actions.jsonl` for progress and completion.

## Walkthrough (source order)

### `fire_scheduled_events(env, event_config, loop_round, agent_names, action_logger, log_info)` (async) — 2531-2572
- Replays research-timeline events as `CREATE_POST` `ManualAction`s at the start of a round (T3.8).
- Inputs: `event_config["scheduled_events"]`, a list of `{round, poster_agent_id, content, ...}` (2537). `loop_round` is 0-based.
- Due set: `int(e.get("round", -1)) == loop_round` (2538). This `int()` is **not** guarded, so one malformed `round`
  raises out of the function. The caller catches it and skips that round's events (5047-5048). [verifier: the comprehension scans every event on every call, so one malformed `round` (or a non-dict entry, AttributeError) raises in every round and disables scheduled-event firing for the whole run, not just one round; `_scheduled_events_due` tolerates the bad entry, so the WORLD CLOCK header and in-band delivery still list events that were never posted (2538, 5038-5048, 2581-2587, 5088, 5180-5181)]
- Each event without `poster_agent_id` or with empty `content` is skipped (2546). The agent comes from `env.agent_graph.get_agent` (2549).
- `actions[agent] = ManualAction(CREATE_POST, {"content"})` (2550-2553). The dict is keyed by agent, so a second event for the
  same poster in the same round **overwrites** the first (see Surprises).
- Logs every event **before** `env.step`: `round_num=loop_round+1`, `action_args={"content", "is_scheduled_event": True}` (2554-2561).
  `fired` is incremented per event (2562). A per-event exception is silently skipped (2563-2564).
- `await env.step(actions)` (2567). On failure it logs and returns 0 (2569-2571); the already-logged entries stay in actions.jsonl.
- Output: the number of events fired. Side effects: OASIS DB rows (post + trace) and actions.jsonl lines.

### `_scheduled_events_due(event_config, loop_round)` — 2575-2588
- Same round-match semantics, but tolerant: non-dict entries and non-int `round` values are skipped (2581-2587).
- Returns the raw event dicts. Used for the calendar WORLD CLOCK "confirmed events" section (5088, 5639) and for in-band delivery (5181, 5732).

### `_resolve_total_rounds(config, temporal_config, calendar, max_rounds, log_info)` — 2591-2623
- Hours formula: `total_simulation_hours` (default 72) × 60 // `minutes_per_round` (default 60), giving 72 by default (2601-2604).
  A zero `minutes_per_round` would raise ZeroDivisionError; there is no guard.
- Calendar mode (2606-2616): `temporal_config.n_rounds` is authoritative. If it is missing or ≤0, the fallback is
  `len(round_dates)`, then the hours formula (2611-2612). Runtime `max_rounds` is **ignored**, with a log line (2614-2616).
- Hours mode: when `max_rounds > 0`, the result is truncated to `min(total, max_rounds)` and the truncation is logged (2618-2622).
- The docstring says it is called "before log_simulation_start", but the loops call it after (4945 vs 4833). See Surprises.

### `build_oasis_platform(kind, db_path, config, log_info)` — 2626-2743
Returns a custom `oasis.social_platform.platform.Platform`, or `None`. When it returns `None` the caller falls back to
`DefaultPlatformType.TWITTER`/`REDDIT` (4810-4816, 5363-5369).
- **Default path: `SIM_WIRE_RECSYS` is not `"true"`** (read straight from `os.environ`, default `"false"`; 2637):
  - Twitter only, and only if `_flag_true("SIM_TWITTER_MODEL_FREE_FEED","true")` (2646). It builds
    `Platform(db_path, Channel(), recsys_type=SIM_TWITTER_RECSYS or "reddit", refresh_rec_post_count=5, max_rec_post_len=100, following_post_count=3)` (2650-2674).
    The rationale (2638-2666): OASIS's default Twitter feed uses the `twhin-bert` recsys, which downloads a HuggingFace
    model; when that download times out the feed is empty and the sim is broadcast-only. `max_rec_post_len=2` caused a
    winner-take-all feed under the reddit hot-score recsys, so 100 lets every agent see every post in small casts. [verifier: this repeats the code comment's rationale; with ≤100 posts `rec_sys_reddit` puts every post in each agent's rec table (oasis `recsys.py:229-232`), but `refresh()` then shows a random sample of only `refresh_rec_post_count`=5 of them via the global `random.sample` (oasis `platform.py:273-277`), so an agent does not see every post per refresh]
  - Any build exception is logged and falls through (2680-2681). Reddit, or Twitter with the flag off, gets `None` (2682).
  - In this path `start_time` is not anchored, so OASIS uses `datetime.now()`.
- **Wired path: `SIM_WIRE_RECSYS=true`**:
  - Import failure returns `None` (2683-2688).
  - `pcfg = config["twitter_config"|"reddit_config"]` (2690). `echo = float(pcfg.echo_chamber_strength or 0.5)` (2691).
  - `start_time = datetime.fromisoformat(config.as_of_date[:10])`, or `None` on error (2692-2698).
  - Twitter: `recsys_type = pcfg.recsys_type or SIM_TWITTER_RECSYS or "reddit"` (2709-2711). Also
    `refresh_rec_post_count = pcfg or 5`, `max_rec_post_len = pcfg or 100`, `following_post_count = round(2 + echo*4)` (2712-2724).
  - Reddit: `recsys_type = pcfg or "reddit"`, `allow_self_rating=True`, `show_score=True`, refresh 5 / max 100, `start_time` (2726-2735).
  - Logs the chosen knobs (2736-2739). Any exception returns `None` (2741-2743).
- Side effect: `Platform.__init__` opens or creates the SQLite DB at `db_path` (oasis `platform.py:83`).

### Emergent metrics layer (EXECPLAN2 I-2-0) — header 2746-2759, constants 2762-2789
- Off unless `SIM_EMERGENT_METRICS=true` (gate in `main`, 5957). Read-only over `{platform}_simulation.db` plus `{platform}/actions.jsonl`.
- `_SPEECH_ACTIONS = {CREATE_POST, CREATE_COMMENT, QUOTE_POST, REPOST}` (2762).
- `_INTERACTION_ACTIONS` (2764-2767) is **defined but never used**.
- `_STANCE_BUCKETS = (supportive, opposing, neutral, observer)` (2768).
- `_POS_LEXICON` / `_NEG_LEXICON` are small EN+CN polarity sets (2772-2789).

#### `_load_stance_by_agent(config)` — 2792-2801
`agent_configs[*]` → `{int(agent_id): stance}`. The stance is lowercased; anything outside the 4 buckets becomes `"neutral"`.

#### `_lexicon_sentiment(text)` — 2804-2813
Counts lexicon words found as **substrings** of the lowercased text (2809-2810). Returns `(pos-neg)/(pos+neg)`, or 0.0 if neither matches.

#### `_iter_action_lines(path)` — 2816-2835
A generator over actions.jsonl. It skips blank lines, bad JSON and control rows (any `event_type`, or no `action_type`) (2831).
A missing file or OSError yields nothing.

#### `_score_stance_trajectory(actions_path, stance_by_agent)` — 2838-2909
- Only `_SPEECH_ACTIONS` count (2858). Rows need both `agent_id` and `round` (2862).
- Per-round bucket `{round, by_stance{4 buckets}, _sent, _n}` (2868-2872). Content is `action_args.content` or `quote_content` (2878).
  Only rows with content are scored (2879-2884), so REPOST adds volume but no sentiment.
- `trajectory = [{round, by_stance, net_sentiment (4dp)}]`, sorted by round (2886-2894). Round 0 seed posts are included.
- `net_by_agent` is each agent's mean sentiment (2896-2900).
- `polarization` is the **population variance** of `net_by_agent` values, requiring ≥2 speakers (2903-2907).
- Returns `(trajectory, round(polarization,4), net_by_agent)`.

#### `_compute_interaction_ratio(conn, stance_by_agent)` — 2912-2987
- Builds a `user_id → stance` map via `SELECT user_id, agent_id FROM user` (2926). If that query fails it returns zeros (2931-2932).
- `_tally` ignores self-edges and unknown users. Same stance counts as `within`, different stance as `cross` (2937-2948).
- Edge sources, each in its own try:
  - follow (`follower_id → followee_id`, 2951-2956)
  - repost/quote (`post.original_post_id` join, 2959-2968)
  - comment (comment author → post author, 2971-2979)
- Likes are **not** counted.
- Returns `{cross_stance_interaction_ratio = cross/(cross+within), cross_stance, within_stance}` (2981-2987).

#### `_detect_follow_communities(conn, stance_by_agent, log_info)` — 2990-3074
- Needs `networkx`. If it is missing the function logs and returns `[]` (2996-3001).
- DiGraph of follow edges without self-loops (3013-3021). An empty graph returns `[]` (3023).
- Runs `greedy_modularity_communities` on the undirected projection, falling back to `label_propagation_communities` (3027-3035).
- Bridge score: for each node, the number of edges that cross communities (3043-3047). The top 3 per community become `bridge_agents` (3058-3064).
- Each community: `{size, members (agent ids, sorted), dominant_stance (most_common), stance_breakdown, bridge_agents}`.
  Communities are sorted by size, descending (3065-3073).
- Agents with no follow edges never appear.

#### `_compute_cascades(conn, top_n=10)` — 3077-3137
- `repost_counts` comes from `post.original_post_id` GROUP BY (3085-3095). `comment_counts` comes from `comment` GROUP BY `post_id` (3098-3105).
- Only originals count (`original_post_id IS NULL`, 3109-3116).
  - `breadth = reposts + replies`
  - `depth = breadth + num_likes`
- Posts with zero breadth and zero likes are skipped (3118-3134). `num_shares` is selected but unused.
- Returns the top `top_n` by depth (3136-3137).

#### `compute_emergent_metrics(simulation_dir, config, platform, log_info)` — 3140-3200
- Without a DB it logs and returns `None` (3150-3154).
- Runs the trajectory step outside any try (3158), then the three DB metrics inside one try (3160-3176). If the DB block fails,
  it logs and uses zero/empty values.
- `final_stance_share` = the last trajectory round's `by_stance` normalized to 1 (3179-3183). This is a last-round voice share.
- Returns `{platform, polarization_index, cross_stance_interaction_ratio, interaction_counts, final_stance_share, stance_trajectory,
  follow_communities, cascades, num_speaking_agents, sentiment_method:"lexicon"}` (3185-3199).

#### `write_emergent_metrics(simulation_dir, config, platforms, log_info)` — 3203-3252
- Per platform: compute (with its own exception isolation, 3224-3228), then write `{platform}_emergent_metrics.json` atomically (3232-3243).
- If any platform succeeded, it also writes the aggregate `emergent_metrics.json` = `{simulation_id, generated_at, platforms:{...}}` (3218-3252).
- Uses `app.utils.atomic.write_json_atomic` (3216).

### `PlatformSimulation` — 3255-3260
A plain result holder: `env`, `agent_graph`, `total_actions=0`.

### Post-hoc decision channel helpers (NEXTSTEPS P1-1/P1-2/P1-4) — 3263-3350
- **`_read_actions_for_decision_channel(simulation_dir)`** (3264-3289) reads `twitter/` and `reddit/actions.jsonl`. It skips any row
  with `event_type` or no `agent_id` (3282) and emits `[{round, agent_id, agent_name}]`, with **no content**. Missing files are skipped.
- **`_build_round_to_date(seed, config)`** (3292-3350) returns a `round(1-based) → ISO date` function, or `None`.
  - Calendar: when `config.temporal_config.round_dates` exists, it builds an exact table `{round+1: period_end[:10]}` (3300-3313).
    A round below the first key returns `as_of` (seed or temporal_config); a round past the end clamps to the last period (3319-3326).
  - Hours: a linear map from `seed.as_of_date` to `seed.horizon_date` over `total_rounds = int(total_hours*60/mpr)`, which
    **ignores max_rounds truncation** (3327-3350). It returns `None` if the dates are missing, unparseable, or `horizon ≤ as_of`.

### In-band world evolution (CAL-TEMPORAL spec §4) — 3353-3734
Module registries:
- `_INBAND_EVOLUTIONS: {abs sim_dir → _InbandWorldEvolution}` (3361)
- `_INBAND_TRAJ_WRITTEN: {abs sim_dir → bool}` (3363)

#### `class _InbandWorldEvolution` — 3366-3689
One shared WorldState per sim directory. In parallel mode both platforms share it (`expected = semaphore_platforms`, i.e. 2).
- **`__init__(config, simulation_dir, expected_platforms, log_info)`** (3380-3449)
  - Imports `app.services.decision_channel` and `app.services.worldstate.WorldState` (3382-3383).
  - Scenarios come from `config.world_state_seed.scenarios` (3390-3392).
  - `inertia = SIM_DECISION_INERTIA` (raw env, default 0.7) and `conv_eps = SIM_CONVERGENCE_EPS` (raw env, default 0.02) (3394-3401).
  - `WorldState(scenarios, seed.base_rates, inertia)` (3402). `_base_shares` is a frozen copy of the seed prior that is fed to elicitation (3403).
  - Built from `agent_configs` (3405-3407): activation, outcome-power and meta maps via `_dc._activation_weight_map`, `_outcome_power_map`, `_agent_meta_map`.
  - `_cap = DECISION_CHANNEL_MAX_ACTIVE` (default 60) and `_conv_window = SIM_CONVERGENCE_WINDOW` (default 3), both read via `_dc._cfg` (3408-3409).
  - `_entropy_on = _flag_true("WORLDSTATE_ENTROPY_MIX","true")` (3410).
  - `unit = temporal_config.unit`, or inferred from `round_dates` (3411-3414). `_avg_gap` = the unit's nominal days from `_dc._UNIT_NOMINAL_DAYS` (3417).
  - Also stored: `n_rounds`, `horizon_date/source/defaulted` (temporal_config first, then seed) and `as_of_date` (3418-3427).
  - Trajectory row 0 is `{"round":0, **ws.outcome(), "as_of"?}` (3428-3431).
  - LLM: `_wrap_llm_client_usage(LLMClient())` (3443-3446). If that fails, `_llm=None` and every elicitation returns empty (3447-3449).
- **`deliver(platform, round_num, period, round_actions, fired_events)`** (3452-3481)
  - Merges one platform's 0-based round into `_pending[round_num] = {period, actions, events, event_keys}` (3459-3467).
  - Events are deduplicated across platforms by `(date, content)` (3469-3476).
  - Raises the platform's watermark (3477), then calls `_advance()` (3478).
  - Any exception clears the delta and logs (3479-3481).
- **`heartbeat(platform, round_num)`** (3483-3491) only raises the watermark and calls `_advance` on dead or failed rounds. It never raises.
- **`latest_delta()`** (3493-3495) returns the last qualitative digest text.
- **`platform_done(platform)`** (3497-3506) adds the platform to `_done` and advances. Once `len(_done) ≥ expected` it calls
  `force_finalize()` and pops itself from `_INBAND_EVOLUTIONS` (3502-3504).
- **`force_finalize()`** (3508-3551)
  - Idempotent (3512). Calls `_advance(flush_all=True)` (3515). With zero stepped rounds it writes nothing (3519-3520).
  - Otherwise writes `world_state_trajectory.json` atomically: `{outcome, trajectory, decisions, converged_at, n_rounds (=max stepped
    round), scenarios, schema_version:3, mode:"calendar", calendar_unit?, horizon_*?}` (3521-3542).
  - Writes `decisions.jsonl` with plain `open("w")`, not atomically (3543-3545).
  - Sets `_INBAND_TRAJ_WRITTEN[dir]=True` (3546).
- **`_advance(flush_all=False)`** (3554-3572)
  - `gate` = the minimum watermark across known, not-done platforms.
  - It does nothing until `len(known platforms) ≥ expected` (3563-3565), and steps nothing above the gate (3569-3570).
  - With `flush_all`, there is no gate. Pending rounds are stepped in ascending order (3568-3572).
- **`_step_round(round_num, buf)`** (3574-3689) runs one period:
  1. **Roster.** Actors are deduplicated across both platforms. Each entry is meta plus the actor's first post content this round
     (3583-3598). The result goes through `_dc._build_active_roster(entries, activation, power, cap)` (3599-3600).
  2. **Elicitation.** `ctx` is `{llm, scenarios, base_shares, abstain_allowed:True, round_num (1-based), as_of=period_end}`, plus
     period / n_rounds / horizon_date / unit when a period exists (3601-3608). Then `commitments = _dc.elicit_round(roster, ctx)` (3609).
     This is a **synchronous** LLM call (`decision_channel.py:247`, `llm.chat_json`).
  3. **Round status.** `round_status = ctx["round_status"]`, or `"missing"` when the roster is empty (3615).
  4. **Step.** `eff_inertia = _dc._inertia_for_gap(inertia, prev_date, period_end, avg_gap)` (3617-3618). If entropy mixing is on,
     `entropy_days = _dc._period_days(period)` (3619-3620). Then `ws.step(commitments, inertia=..., entropy_mix_days=..., round_status=...)` (3622-3623).
  5. **Leader move.** Direction only: up/down/flat with a 1e-9 tolerance (3627-3632).
  6. **Digest.** `build_world_delta(digest_actions, events, leader_move)` from `app.services.world_delta` (3634-3645).
     Digest actions are `{content, agent_name, influence_weight}`.
  7. **Audit.** Commitments go to `_decisions` without the `weight` key (3647-3648). The trajectory row is
     `{round, **outcome, round_status, as_of=period_end, period_start/period_end/label}` (3650-3658).
  8. **Digest file.** One line is **appended** to `world_digest.jsonl`:
     `{round, period_start, period_end, digest, shares, leader, delta{scenario: Δshare 6dp}}` (3660-3673).
  9. **Convergence (signal only, never stops the run).** `stable_streak` goes up while `ws.converged(eps)`. `converged_at` is set
     once the streak reaches `conv_window` and `rnd ≥ 2` (3675-3681).
  10. **Bookkeeping.** `_stepped += 1`, `_max_round`, `_prev_date = period_end`, `_delta_text` (3682-3686).
      Any exception clears the delta and logs (3687-3689).

#### `_get_inband_evolution(config, simulation_dir, expected_platforms, log_info)` — 3692-3720
- Returns `None` if `SIM_DECISION_CHANNEL_INBAND` is off (default true, read via `_flag_true`, 3698).
- Returns `None` with a warning log if the seed has no scenarios (3700-3707).
- Otherwise get-or-create in `_INBAND_EVOLUTIONS` by absolute dir. Creating a new instance clears any stale `_INBAND_TRAJ_WRITTEN`
  flag (3708-3716). A construction exception returns `None` (3718-3720).

#### `_finalize_inband_world_evolution(simulation_dir, log_info)` — 3723-3734
Pops the evolver and calls `force_finalize()` (a safety net for platforms that crashed). Returns the `_INBAND_TRAJ_WRITTEN[dir]` flag,
which `main` uses to skip the post-hoc channel.

### Round checkpoints / resume (RUN-7, ITEM 3, XRUN-4) — 3737-3889
- `_resume_checkpointing_enabled()` = `SIM_RESUME` (default false) (3747-3749).
- `_checkpoint_enabled()` = `SIM_CHECKPOINT` (default true) **or** `SIM_RESUME` (3752-3757).
- `_checkpoint_file(dir, platform)` returns `{dir}/{platform}/checkpoint.json` (3760-3761).
- `_config_hash(config)` = sha256 of `json.dumps(config, ensure_ascii=False, sort_keys=True, default=str)`. On error it returns `""` (3764-3773).
  This must match `SimulationRunner._current_config_hash` (`simulation_runner.py:1340-1354`).
- `_capture_rng_state()` returns `{"py_random": [version, list(state), gauss_next]}` of the module `_RNG` (3776-3785).
  `_restore_rng_state` is its inverse; it returns True or False (3788-3799).
- `_write_round_checkpoint(...)` (3802-3835) is a no-op when checkpointing is disabled.
  - Writes atomically: `{platform, completed_round, last_rowid, total_rounds, total_actions, updated_at, config_hash?, rng_state?}`.
  - All exceptions are swallowed.
- `_load_round_checkpoint(dir, platform)` (3838-3850) returns the dict only if `completed_round ≥ 1`; otherwise, or on any parse error, `None`.
- `_max_trace_rowid(db_path)` returns `MAX(rowid)` of the `trace` table, or 0 on any error (3853-3863).
- `_free_disk_error(dir)` (3866-3881) returns an error string if free disk is below `SIM_MIN_FREE_DISK_GB` (default 2; ≤0 disables).
  A `disk_usage` OSError returns `None`.
- `_step_failure_limit()` = `SIM_STEP_FAILURE_LIMIT` (default 3; 0 never trips; clamped ≥0) (3884-3889).

### Engagement sampler (ITEM 20) — 3892-4066
- `_engagement_sampler_enabled()` (3897-3907): `SIM_ENGAGEMENT_SAMPLER`, default `"auto"`. Auto means "on only when the reaction phase
  is off". Because the reaction phase defaults on, **the sampler defaults off**. Explicit true or false wins.
- `_engagement_rate()` = `SIM_ENGAGEMENT_RATE` clamped to [0,1], default 0.3 (3910-3916).
- `_max_follows_per_agent_round()` = `SIM_MAX_FOLLOWS_PER_AGENT_ROUND` (default 3). It is consumed by `inject_initial_follows` in part 1 (2492) (3919-3924).
- `_max_post_id(db_path)` returns `MAX(post_id)`, or 0 (3927-3939).
- `_fetch_round_posts(db_path, last_post_id, agent_names)` (3942-3974) returns `({post_id: author_agent_id (-1 if no user)}, new high-water)`
  for `post_id > last_post_id`, joining `user`. On error it returns `({}, last)`.
- **`inject_engagement_likes(...)`** (async, 3977-4066)
  1. Fetches new posts since `engagement_state["last_post_id"]` and advances the high-water mark (4002-4007).
  2. Weights each post as `1 + (#CREATE_COMMENT/LIKE_POST/DISLIKE_POST in this round's actual_actions targeting it)` (4010-4021).
  3. `pairs = agent_dynamics.sample_engagement_likes(post_weights, post_authors, liker_ids, rate, rng)`, a pure deterministic function
     that skips self-likes and gives each liker at most one like (`backend/app/services/agent_dynamics.py:245-268`) (4024-4029).
  4. Calls `env.step` with `{agent: ManualAction(LIKE_POST, {post_id})}` (4031-4043).
  5. Advances `last_rowid` past these trace rows **and discards them** (4047).
  6. Logs each pair as `LIKE_POST` with `is_engagement_sample: True` at `round_num+1` (4049-4060).
  - Returns `(injected, last_rowid)`. Any exception returns `(0, last_rowid)` (4064-4066).

### SIM-REACT response phase — 4069-4689
Rationale (4071-4089): OASIS gives each agent `max_iteration=1`, so agents posted but almost never replied to each other.
After the organic step, each active agent makes one stateless "response" call that has only reply and endorse tools. [verifier: only the `SIM_REACTION_SHARE` subsample of active agents (4601-4604), only those with ≥1 candidate (4613-4614), and only agents whose `_internal_tools` dict includes `create_comment` and that have a `model_backend` (4630-4635)]

Constants (4091-4121):

| Name | Value |
|---|---|
| tools | `create_comment`, `like_post`, `like_comment` [verifier: this is the allow-list; the helper only gets tools the agent actually has (4633), and Twitter agents have no `like_comment` because `TWITTER_ACTIONS` lacks LIKE_COMMENT (214-224; OASIS builds tools from available_actions, `oasis/social_agent/agent.py:84-105`), so Twitter helpers get only `create_comment` + `like_post`] |
| reply tool (required) | `create_comment` |
| `_REACTION_MAX_CANDIDATES` | 3 |
| `_REACTION_WINDOW_POSTS` | 60 |
| post / quoted / reply truncation (chars) | 700 / 240 / 240 |
| thread replies shown | 3 |
| `_REACTION_MAX_WORDS` | 90 |
| `_REACTION_STEP_TIMEOUT_S` | 240 s |
| memory note truncation (chars) | 320 |

Also defined there: the regexes `_CJK_RUN_RE`, `_LATIN_LETTER_RE`, `_TOPIC_WORD_RE` (Latin words of 4+ chars), `_ACRONYM_RE`, and the
sets `_TOPIC_STOPWORDS` and `_ALIAS_GENERIC_WORDS`.

- `_reaction_phase_enabled()` = `SIM_REACTION_PHASE` (default true) (4124-4126).
- `_reaction_share()` = `SIM_REACTION_SHARE` clamped to [0,1], default 1.0 (4129-4135).
- `_normalize_output_language(raw)` (4138-4148) maps raw values to `English` or `Chinese`:
  - `en*` gives English.
  - `zh*`, `chinese*`, `cn*`, or text containing 中文/汉语 gives Chinese.
  - empty or `auto` gives `""`.
  - anything else returns its first 40 characters.
- `_sim_output_language(config)` (4151-4164) checks, in order: `SIM_OUTPUT_LANGUAGE`, then `config.output_language`, then a script heuristic
  on `simulation_requirement`. The heuristic picks Chinese when `cjk_chars*3 ≥ latin_letters`. With no text it returns `""`.
- `_reaction_topic_tokens(text)` (4167-4173) returns lowercase Latin words of ≥4 characters minus stopwords, plus CJK bigrams.
- `_reaction_name_aliases(name)` (4176-4211) builds `[(alias, case_sensitive)]` from the full name and its `/()（）,，` segments:
  - CJK segments of ≥2 characters: case-sensitive.
  - All-caps acronym segments: case-sensitive.
  - Latin segments of ≥4 characters: case-insensitive.
  - Embedded acronyms of ≥3 characters: case-sensitive.
  - The first word of a multi-word segment, if it is ≥4 characters, capitalized and not generic: case-insensitive.
- `_text_mentions(text, aliases)` (4214-4226): CJK aliases match as substrings; Latin aliases match with an alphanumeric lookaround boundary.
- `_truncate_text(text, limit)` collapses whitespace and appends `…` (4229-4231).
- `_build_reaction_profiles(config)` (4234-4257) returns `{agent_id: {name=entity_name, stance, aliases, tokens}}`.
  The tokens come from `interested_topics + gains_if + loses_if`.
- `_fetch_reaction_threads(db_path, since_post_id, recent_after_post_id, limit=60)` (4260-4334)
  - Takes the newest 60 posts with `post_id > since` (4277-4290). Pure reposts (original id set, no quote text) are skipped (4295-4296).
  - For quotes, `content` is the quote text and `quoted` is the original text (4297-4305). `recent` = `post_id > recent_after` (4306).
  - Then loads every comment for those posts, ordered by `comment_id` (4309-4329). On any error it returns `{}`.
- `_fetch_follow_edges(db_path)` returns the set of `(follower_agent_id, followee_agent_id)` (4337-4361).
- **`select_reaction_candidates(reactor_id, threads, profiles, follows, assigned, max_candidates=3, rng=None)`** (4364-4447) is pure.
  - **Own post**: included only if others replied after the reactor's last comment (+3) (4403-4407).
  - **Others' post**:
    - Excluded if the reactor already commented and nobody replied since; otherwise +2 (4409-4413).
    - +3 if the post, the quote or others' comments mention the reactor (4415-4422).
    - +0.5 per overlapping topic token, capped at +2 (4423-4428).
    - +1 if the reactor follows the author; +0.5 if the author follows the reactor (4429-4433).
    - Stance: +0.5 when it differs, +0.25 when it matches (4434-4436).
  - **All posts**:
    - +1 for a recent post, +0.3 otherwise (4437).
    - −0.75 × the number of times the post was already assigned to another reactor (4438).
    - −0.2 × min(comments, 10) (4439).
    - +`rng.random()*0.05` jitter (4440-4441).
  - Sorted by `(-score, -post_id)` and truncated to `max_candidates` (4443-4447).
- **`build_reaction_prompt(...)`** (4450-4518): a `# RESPONSE ROUND — {period_label}` header, then the candidates with excerpts, the
  last 3 replies (`[comment_id=…]` only on Reddit) and the reasons. Six numbered rules follow:
  1. Reply with `create_comment`.
  2. Answer the post's specific claim.
  3. Add new information.
  4. Speak in role.
  5. Use 1-3 sentences and ≤90 words, in the output language.
  6. Optionally endorse with `like_post`, or `like_comment` on Reddit.
  The prompt ends with "cannot publish a new standalone post".
- `_make_reaction_agent(agent, tools)` (4521-4533) builds a camel `ChatAgent` with the agent's system message, `agent.model_backend`,
  the given tools, `max_iteration=1` and `step_timeout=240`.
- `_reaction_memory_note(agent_id, actions, agent_names)` (4536-4556) builds a `# YOUR RESPONSES THIS PERIOD` summary of that agent's
  `CREATE_COMMENT`, `LIKE_POST` and `LIKE_COMMENT` actions.
- **`run_reaction_phase(env, db_path, active_agents, config, round_num, period_label, platform, agent_names, reaction_state, last_rowid, action_logger, rng, log_info)`** (async, 4559-4682)
  1. Fetches threads between `reaction_state.window_start` and `round_start` (4583-4589). Profiles and language are cached in `reaction_state` (4590-4598). [verifier: not "between": it fetches the newest ≤60 posts with `post_id > window_start`, which includes this round's posts above `round_start`; `round_start` only sets each thread's `recent` flag (4285-4289, 4306)]
  2. Reactors: sorted, optionally subsampled via `rng.sample` when share < 1, then **always** `rng.shuffle`d (4600-4605).
  3. Per reactor: select candidates, count the top candidate in `assigned`, build the prompt (4607-4620).
  4. Concurrency: `env.llm_semaphore` (OASIS env attribute), or `Semaphore(4)` (4624-4626).
  5. `_respond` (4629-4644) needs `agent._internal_tools` as a dict, a `model_backend`, and `create_comment` among the tools. It
     builds the helper and calls `await helper.astep(user_message)` under the semaphore. Per-agent failures are logged.
  6. All calls run through `asyncio.gather` (4646).
  7. `fetch_new_actions_from_db` collects every new trace row, and each is logged at `round_num+1` with **no reaction marker** (4649-4658).
  8. Each agent gets one USER-role memory note, `ResponseLog`, via `agent.update_memory` (4660-4671).
  9. Logs counts (4673-4678) and returns `(actions, last_rowid)`. Any exception returns `([], last_rowid)` (4680-4682).
- `_advance_reaction_window(state, db_path)` (4685-4689): `window_start ← round_start` and `round_start ← MAX(post_id)`. It is called
  before each organic step, so candidates are last round's plus this round's posts (the first round includes the seed posts).

### `run_twitter_simulation(config, simulation_dir, action_logger=None, main_logger=None, max_rounds=None, semaphore_platforms=1, resume=False)` (async) — 4692-5225
Setup, in order:
1. `log_info` prefixes `[Twitter]` and writes to both `main_logger` and stdout (4716-4719).
2. Calendar detection: `config.temporal_config.mode == "calendar"`, stripped and lowercased; environment variables are not consulted (4726-4729).
3. Model: `create_model(config, use_boost=False)` (4732), wrapped by `_wrap_model_llm_counter` for llm_health (4734).
4. `twitter_profiles.csv` must exist, or the function **returns an empty result** with `env=None` (4737-4740).
   Then `generate_twitter_agent_graph(profile_path, model, TWITTER_ACTIONS)` (4742-4746).
5. Optional prompt and tool hooks, each in its own try/except, all before `env.reset`:
   - role action profiles (`SIM_ROLE_ACTION_PROFILES`) (4750-4754)
   - world brief (4758-4763)
   - calendar vocabulary, calendar mode only (4767-4771)
   - tool-argument normalizer (4774-4777)
   - self-like guard on `twitter_simulation.db` (4779-4783)
6. `agent_names` from config, filled in with OASIS names (4786-4790).
7. Database and resume (4792-4807): `db_path = {dir}/twitter_simulation.db`.
   - Resume only when `--resume` was passed **and** a checkpoint exists **and** the DB exists **and** the config_hash matches.
     Old checkpoints without a hash pass.
   - Otherwise any existing DB is **deleted** (4806-4807).
8. Platform: `build_oasis_platform("twitter", …)` or the default, then
   `oasis.make(agent_graph, platform, database_path, semaphore=get_oasis_semaphore(config, use_boost=False, platforms=semaphore_platforms))` (4810-4816).
   `await env.reset()` (4818).
9. `log_simulation_start(config, _tr_log)` (4821-4833). `_tr_log` is computed separately from `_resolve_total_rounds`.
10. Resume restore: `total_actions` from the checkpoint, `last_rowid = max(ckpt.last_rowid, MAX(trace.rowid))`, RNG state (4840-4845).
11. Round 0 (all skipped on resume):
    - `log_round_start(0, start_hour)` (4858-4859)
    - initial posts merged per agent into lists, logged at round 0, then `env.step` (4848-4902)
    - `inject_initial_follows` (part 1) (4906-4910)
    - **RUN-1 backlog digest**: fetch trace rows, drop `CREATE_POST` (already logged), log the rest (seed `FOLLOW`s) at round 0 with
      `is_seed_action: True` (4917-4933)
    - `log_round_end(0, …, simulated_hours=0.0)` (4936-4937)
12. Loop state:
    - `total_rounds = _resolve_total_rounds(...)` (4945)
    - calendar `_round_periods{round → round_dates entry}` (4949-4957)
    - `world_delta_text=""` (4958)
    - recency set and `SIM_RECENCY_CARRY` (4962-4964)
    - dynamics tracker (4966-4967)
    - engagement state, seeded with the current max `post_id` (4971-4973)
    - reaction state and language (4976-4980)
    - checkpoint platform and config hash (4983-4984)
    - in-band evolver, calendar mode only (4989-4990)
    - `_write_ckpt` closure (4992-4996)
    - `start_round`: on resume, `min(completed_round, total_rounds)` (4998-5001)
    - step-failure circuit state (5005-5007)

Per round (`for round_num in range(start_round, total_rounds)`, 5008):
1. If `_shutdown_event` is set, break (5010-5013).
2. Compute `simulated_hour = (start_hour + round_num*mpr//60) % 24` and `simulated_day` (5015-5017). In calendar mode also compute
   `_period` and `_cal_extra = {period_start, period_end, period_label, calendar_unit}` (5021-5029).
3. Disk precheck. A failure **raises RuntimeError** (5033-5035).
4. `fire_scheduled_events`. If any fired, advance `last_rowid` to discard their trace rows (RUN-14) (5038-5048).
5. `get_active_agents_for_round(env, config, hour, round_num, last_active_ids, calendar=)` (part 1) (5050-5053), then update the
   recency set (5055-5056).
6. `log_round_start(round+1, hour, **filtered cal kwargs)` (5059-5062).
7. **Dead round** (no active agents): `log_round_end(…,0)`, in-band `heartbeat`, refresh the delta, write the checkpoint, `continue` (5064-5076).
8. `_inject_agent_dynamics` (5079). In calendar mode, `_inject_period_context(..., due events, world_delta_text, response_step, language)` (5083-5094).
9. Advance the reaction window (5096-5097). `actions = {agent: LLMAction()}` (5098). `await env.step(actions)` (5101-5102).
   - Success resets the failure counters (5103-5104).
   - On failure: count consecutive failures of the **same exception class**; log `round_end` with 0 actions, heartbeat, checkpoint.
     If `limit > 0` and the count reaches the limit, **raise RuntimeError**; otherwise `continue` (5105-5128).
10. `fetch_new_actions_from_db` and log each action as organic at `round+1` (5131-5146).
11. Reaction phase. Its actions are appended to `actual_actions` and counted (5150-5160).
12. `_observe_agent_dynamics` (5163). Engagement likes, if enabled (5167-5174).
13. In-band `deliver(platform, round_num, _period, actual_actions, due events)`, then refresh `world_delta_text` (5179-5182).
14. `log_round_end(round+1, round_action_count, simulated_hours=…, **cal)` (5184-5188). Checkpoint (5189). Progress log every 20 rounds (5191-5193).

After the loop:
- The env is **not closed**; it is kept for interviews (5195).
- `platform_done` on the evolver (5199-5200).
- `_write_llm_health` (5204-5205).
- `{plat}_dynamics_summary.json`, if a tracker exists (5206-5216).
- `log_simulation_end(total_rounds, total_actions)` (5218-5219).
- `result.total_actions` is set and the result returned (5221-5225).

### `run_reddit_simulation(...)` (async) — 5228-5776
Line-for-line the same as Twitter, except:
- `create_model(use_boost=True)` (5268)
- `reddit_profiles.json` and `generate_reddit_agent_graph(..., REDDIT_ACTIONS)` (5272-5281)
- **Canonical Reddit system-message enforcement** `_enforce_canonical_reddit_system_messages` (5294-5296) and the fail-closed
  `_attest_canonical_reddit_system_messages(graph, profile_path, config, rows, _VALIDATED_CONFIG_MANIFEST_SHA256)` (5318-5324).
  The attestation raises `ValueError` on mismatch or a missing seal, and writes `reddit_runtime_system_messages.json` (part 1, 630-697).
- `DefaultPlatformType.REDDIT` fallback and `get_oasis_semaphore(use_boost=True)` (5363-5369)
- the reaction phase is passed platform `"reddit"` (5704), which enables `comment_id` refs and the `like_comment` endorsement in the prompt
- the initial-posts loop has no "merge fix" comment, but the code is identical (5422-5433)

### `main()` (async) — 5779-6098
1. **CLI** (5780-5827):
   - `--config` (required)
   - `--config-seal`
   - `--twitter-only`, `--reddit-only`
   - `--max-rounds` (default `None`, meaning no truncation; RUN-3)
   - `--no-wait`
   - `--resume`
2. Globals: create `_shutdown_event`. A missing config does `print` + `sys.exit(1)` (5830-5835).
3. `simulation_dir = dirname(config)` (5837). Pin the telemetry sink dir (5840).
4. Seal: `validate_direct_child_config_seal(config, seal)` (part 1, 1285-1345) sets `_VALIDATED_CONFIG_MANIFEST_SHA256` (5841-5846).
   Then `load_config(path, simulation_config_sha256)` raises if the bytes changed (5847-5850). Pin the sink config (5851).
5. `wait_for_commands = not --no-wait` (5852). `init_logging_for_simulation` (5855). `SimulationLogManager` and the per-platform loggers (5858-5860).
6. Disk precheck. On failure: `log_manager.error` + `sys.exit(1)` (5873-5876).
7. Info logs of the hours-formula round count (5878-5891). The agent_configs index ≠ agent_id misalignment check is a warning only (5896-5906).
8. Run:
   - `--twitter-only` or `--reddit-only`: one platform awaited directly (5920-5925).
   - Otherwise both under `asyncio.gather(..., return_exceptions=True)` with `semaphore_platforms=2`. An exception becomes `None`
     plus a logged error, so platforms are isolated (5926-5943).
9. Post-loop:
   - `_write_sim_llm_telemetry` snapshot (5952)
   - emergent metrics if `SIM_EMERGENT_METRICS == "true"` (raw env) for platforms with a non-None env (5957-5970)
   - `_finalize_inband_world_evolution` (5975)
   - post-hoc decision channel (5983-6026), only if all three hold:
     - `SIM_DECISION_CHANNEL == "true"` (**raw env, default "false"**)
     - the seed has scenarios
     - in-band did not write a trajectory
   - The post-hoc channel calls `run_decision_channel(actions, agent_configs, seed, wrapped LLMClient, inertia, conv_eps,
     round_to_date=_build_round_to_date(...), round_dates (calendar only))`. It writes `world_state_trajectory.json` (atomic) and
     `decisions.jsonl` (`"w"`).
10. Wait mode (6029-6081):
    - `ParallelIPCHandler(...)`, `update_status("alive")` (6037-6044)
    - idle auto-close after `SIM_IDLE_CLOSE_MIN` (default 60; ≤0 waits forever) (6049-6066)
    - loop: `process_commands()`, where False breaks (for `close_env`), then `wait_for(_shutdown_event.wait(), 0.5)` (6055-6072)
    - exceptions are printed (6073-6078)
    - `update_status("stopped")` (6081)
11. `env.close()` for each existing env (6084-6090). Final log lines (6092-6098). [verifier: reached after any exit from the wait loop (close_env command, idle timeout, shutdown signal, caught exception) or straight away with `--no-wait`, not only after the idle auto-close; the env of a platform whose result became `None` in gather is never closed (6056-6081, 5938-5943, 6084-6090)]

### `setup_signal_handlers(loop=None)` — 6101-6129
SIGTERM and SIGINT handler. The first signal sets `_cleanup_done` and `_shutdown_event`. A second signal prints and calls
`sys.exit(1)` (6111-6126). The `loop` parameter is unused.

### `__main__` — 6132-6154
`setup_signal_handlers()`, then `asyncio.run(main())`. `KeyboardInterrupt` is printed and **`SystemExit` is swallowed** (6136-6139).
`finally` writes the final `sim_llm_telemetry.json` if the sink dir was pinned (6143-6147), stops the multiprocessing resource tracker
(6149-6153) and prints the exit line.

## Control flow

```
__main__ (6132) → setup_signal_handlers (6133) → asyncio.run(main) (6135)
main (5779)
  ├─ validate_direct_child_config_seal / load_config (5841-5850)
  ├─ _free_disk_error precheck (5873)
  ├─ gather(run_twitter_simulation, run_reddit_simulation, return_exceptions=True) (5930-5936)
  │    each platform:
  │      create_model → generate_*_agent_graph → prompt/tool hooks → resume decision
  │      → build_oasis_platform (2626) → oasis.make → env.reset (4810-4818 / 5363-5371)
  │      → round 0: initial posts → inject_initial_follows → backlog digest (4848-4937)
  │      → _resolve_total_rounds (2591) → _get_inband_evolution (3692, calendar only)
  │      → per round (5008 / 5559):
  │           _free_disk_error → fire_scheduled_events (2531) → get_active_agents_for_round
  │           → [dead: heartbeat (3483) + checkpoint] → _inject_agent_dynamics → _inject_period_context (calendar)
  │           → _advance_reaction_window (4685) → env.step(LLMAction) → fetch_new_actions_from_db
  │           → run_reaction_phase (4559) → _observe_agent_dynamics → inject_engagement_likes (3977, off by default)
  │           → _InbandWorldEvolution.deliver (3452) → _advance (3554) → _step_round (3574)
  │           → log_round_end → _write_round_checkpoint (3802)
  │      → platform_done (3497) → [force_finalize (3508) when all platforms are done]
  │      → _write_llm_health → dynamics_summary → log_simulation_end
  ├─ _write_sim_llm_telemetry (5952)
  ├─ write_emergent_metrics (3203; SIM_EMERGENT_METRICS)
  ├─ _finalize_inband_world_evolution (3723)
  ├─ run_decision_channel fallback (5988-6026; SIM_DECISION_CHANNEL, no in-band trajectory)
  ├─ IPC wait loop (6029-6081)
  └─ env.close() (6084-6090)
finally: _write_sim_llm_telemetry (6143-6147)
```

Ordering facts that matter:
- Scheduled events fire **before** active-agent selection, so they are visible to this round's agents (5037-5041).
- The reaction window advances **before** the organic step, so "recent" means posts created in this round's organic step (5096-5097, 4687-4689).
- In-band delivery happens after the reaction phase and engagement sampling. Only `actual_actions` (organic + reaction) is delivered;
  sampled likes are not in that list (5157, 5168-5182).
- Checkpoints are written after `log_round_end` (5184-5189).

## Data & artifacts

| Path (relative to sim dir) | R/W | Writer / reader (anchor) | Format & key fields |
|---|---|---|---|
| `simulation_config.json` | R | `load_config` via main (5847) | Must be the sealed bytes; must be named `simulation_config.json` when a seal is required (part 1, 1334-1335) |
| `twitter_profiles.csv`, `reddit_profiles.json` | R | 4737, 5272 | OASIS profiles |
| `twitter_simulation.db`, `reddit_simulation.db` | R/W (deleted on fresh run) | 4792-4807, 5345-5360; OASIS | SQLite tables `user(user_id, agent_id)`, `post(post_id, user_id, content, quote_content, original_post_id, num_likes, num_shares)`, `comment(comment_id, post_id, user_id, content)`, `follow(follower_id, followee_id)`, `trace(rowid, user_id, action, info)` |
| `{platform}/actions.jsonl` | W (append, via `PlatformActionLogger`) | `backend/scripts/action_logger.py:43-66` | Action rows `{round, timestamp, agent_id, agent_name, action_type, action_args, result, success}`. Markers in `action_args`: `is_scheduled_event` (2560), `is_seed_action` (4928), `is_engagement_sample` (4058). Control rows: `event_type` ∈ simulation_start (`total_rounds`, `agents_count`), round_start (`simulated_hour`, `period_label?`), round_end (`actions_count`, `simulated_hours`, `period_end?`), simulation_end |
| `{platform}/checkpoint.json` | W (atomic) / R | 3802-3835, 3838-3850 | `{platform, completed_round, last_rowid, total_rounds, total_actions, updated_at, config_hash?, rng_state?}` |
| `world_digest.jsonl` | W (**append**) | 3672-3673 | Per stepped round `{round, period_start, period_end, digest, shares, leader, delta}` |
| `world_state_trajectory.json` | W (atomic) | in-band 3542; post-hoc 6015-6016 | In-band: `{outcome, trajectory[{round, ...outcome, round_status, as_of, period_*, label}], decisions, converged_at, n_rounds, scenarios, schema_version:3, mode:"calendar", calendar_unit?, horizon_date?, horizon_source?, horizon_defaulted?}` |
| `decisions.jsonl` | W (`"w"`, not atomic) | 3543-3545, 6017-6020 | One commitment per line (`agent_id, scenario, magnitude, confidence, round, outcome_power?, period_end?`; `weight` removed in-band) |
| `{platform}_emergent_metrics.json`, `emergent_metrics.json` | W (atomic) | 3233-3236, 3247-3250 | See `compute_emergent_metrics` |
| `{platform}_dynamics_summary.json` | W (atomic) | 5210-5214, 5761-5765 | `AgentDynamicsTracker.dynamics_summary()` |
| `llm_health.json` | W (merge) | `_write_llm_health` (part 1, 2270) called at 5205, 5756 | Per-platform calls, errors, error_rate, degraded |
| `sim_llm_telemetry.json` | W (atomic) | 5952, 6143-6147 | Token usage snapshot |
| `reddit_runtime_system_messages.json` | W | via attest (part 1, 682-697), called at 5318 | System-message sha256 attestations |
| `env_status.json`, `ipc_commands/`, `ipc_responses/` | R/W | `ParallelIPCHandler` (part 1), statuses set at 6044, 6081 | IPC |
| `simulation.log` | W (stdout of subprocess + `SimulationLogManager`) | 5858 | Main log |

In-memory structures:
- `_INBAND_EVOLUTIONS` and `_INBAND_TRAJ_WRITTEN` (3361-3363) are process-global and keyed by the absolute sim dir.
- `_RNG` (part 1, 114) is a single process-global `random.Random` shared by both platforms. The reaction phase, engagement sampler
  and active-agent sampler all use it.
- `_reaction_state` per platform: `{window_start, round_start, profiles, language}` (4977, 4590-4598, 4688-4689).
- `_engagement_state` per platform: `{last_post_id}` (4973).
- `last_rowid` per platform is the cursor into the `trace` table.

## Config / env knobs

Read via `_cfg_flag` / `_flag_true` (env first, then `app.config.Config`, then default; part 1, 796-811) unless marked **raw env**
(`os.environ` only).

| Name | Default (script) | Effect | Anchor |
|---|---|---|---|
| `SIM_WIRE_RECSYS` (raw env) | false | Enables config-driven recsys knobs | 2637 |
| `SIM_TWITTER_MODEL_FREE_FEED` | true | Twitter uses the model-free reddit-style recsys when not wired | 2646 |
| `SIM_TWITTER_RECSYS` (raw env) | "" → "reddit" | Overrides the Twitter recsys type | 2650, 2710 |
| `SIM_EMERGENT_METRICS` (raw env) | false | Emergent metrics files | 5957 |
| `SIM_DECISION_CHANNEL` (raw env) | **false** (Config default is true, `backend/app/config.py:1483`) | Post-hoc decision channel | 5984 |
| `SIM_DECISION_CHANNEL_INBAND` | true | In-band calendar world evolution | 3698 |
| `SIM_DECISION_INERTIA` (raw env) | 0.7 | WorldState inertia (in-band and post-hoc) | 3395, 5993 |
| `SIM_CONVERGENCE_EPS` (raw env) | 0.02 | Convergence epsilon | 3399, 5997 |
| `SIM_CONVERGENCE_WINDOW` (via `decision_channel._cfg`) | 3 | Stable rounds before `converged_at` | 3409 |
| `DECISION_CHANNEL_MAX_ACTIVE` (via `_dc._cfg`) | 60 | Roster cap; the tail collapses into a public block | 3408 |
| `WORLDSTATE_ENTROPY_MIX` | true | Entropy floor per period days | 3410 |
| `SIM_CHECKPOINT` | true | Write `checkpoint.json` every round | 3757 |
| `SIM_RESUME` | false | Also forces checkpointing (resume itself is the `--resume` CLI flag) | 3749 |
| `SIM_SEED` (raw env, part 1) | unset | Deterministic `_RNG`; restored from the checkpoint | part 1 103-114; 3776-3799 |
| `SIM_MIN_FREE_DISK_GB` | 2 (≤0 off) | Disk precheck at start and each round | 3869 |
| `SIM_STEP_FAILURE_LIMIT` | 3 (0 off) | Same-class `env.step` failure breaker | 3887 |
| `SIM_ENGAGEMENT_SAMPLER` | auto (= not reaction phase) | Sampled likes | 3904-3907 |
| `SIM_ENGAGEMENT_RATE` | 0.3 | Like probability per active agent | 3913 |
| `SIM_MAX_FOLLOWS_PER_AGENT_ROUND` | 3 | Seed FOLLOW cap (used in part 1) | 3922 |
| `SIM_REACTION_PHASE` | true | Response phase | 4126 |
| `SIM_REACTION_SHARE` | 1.0 | Fraction of active agents that react | 4132 |
| `SIM_OUTPUT_LANGUAGE` | "" | Language clause in reaction and world-clock prompts | 4155 |
| `SIM_RECENCY_CARRY` | false | Keep the recency set across dead rounds | 4964, 5515 |
| `SIM_IDLE_CLOSE_MIN` | 60 | IPC idle auto-close, in minutes (≤0 infinite) | 6050 |
| `SIM_ROLE_ACTION_PROFILES`, `SIM_WORLD_BRIEF`, `SIM_AGENT_DYNAMICS`, `SIM_START_HOUR`, `SIM_LLM_ERROR_RATE_THRESHOLD` | (part 1) | Hooks called from this slice | 4750, 4758, 4966, 4855, 5205 |

CLI flags: `--config`, `--config-seal`, `--twitter-only`, `--reddit-only`, `--max-rounds`, `--no-wait`, `--resume` (5780-5825).
Config fields consumed:
- `time_config.{total_simulation_hours, minutes_per_round, start_hour}`
- `temporal_config.{mode, n_rounds, round_dates[{round, period_start, period_end, label}], unit, as_of_date, horizon_*}`
- `event_config.{initial_posts, scheduled_events}`
- `world_state_seed.{scenarios, base_rates, as_of_date, horizon_date, horizon_*}`
- `agent_configs[{agent_id, stance, entity_name, interested_topics, gains_if, loses_if, ...}]`
- `twitter_config` / `reddit_config` (recsys knobs)
- `as_of_date`, `world_brief`, `output_language`, `simulation_requirement`, `simulation_id`

## External calls

- **OASIS** (in-process):
  - `oasis.make` (4811, 5364) and `env.reset` (4818)
  - `env.step` with `LLMAction` (organic LLM calls, 5102) and with `ManualAction` (scheduled events 2567, initial posts 4899,
    engagement likes 4043)
  - `env.close` (6085, 6089)
  - `Platform(...)` (2667, 2712, 2726)
- **LLM**:
  - Organic agent calls go through camel models from `create_model` (4732, 5268), counted by `_wrap_model_llm_counter`.
  - Reaction-phase helper `ChatAgent.astep` (4640), using the agent's `model_backend` and up to 240 s per call.
  - In-band elicitation `decision_channel.elicit_round` → `llm.chat_json`, **synchronous** (3609; `backend/app/services/decision_channel.py:247`).
  - Post-hoc `run_decision_channel` with a wrapped `LLMClient` (6002-6013).
- **Network**: implicit HuggingFace download if the `twhin-bert` recsys is selected (the reason for 2638-2645).
- **SQLite** (read-only, separate connections): 2926-2979, 3007-3021, 3088-3116, 3858, 3934, 3955, 4277-4329, 4347-4356.
- **Filesystem**: atomic JSON writes via `app.utils.atomic.write_json_atomic` (3216, 3522, 3820, 5210, 5990). Disk usage check via `shutil.disk_usage` (3875).
- **Subprocess**: none started here. The script itself is the subprocess (`simulation_runner.py:942-952`).

## Cross-module edges

**Into this slice:**
- `backend/app/services/simulation_runner.py:884-920` builds the command line, injects `SIM_SEED` / `SIM_RESUME` (932-940), rotates stale
  artifacts before a rerun (1289-1336) and tails `actions.jsonl`. Its `_current_config_hash` must match `_config_hash` (1340-1354).
  It decides COMPLETED vs FAILED from the exit code **plus** a `simulation_end` row per platform (1054-1103).
- `backend/scripts/run_twitter_simulation.py` and `run_reddit_simulation.py` mirror this script's action-log contract (their line 392).
- Tests exercising slice symbols:
  - `backend/tests/test_calendar_round_loop.py` (in-band loop, checkpoint resume, hours mode)
  - `backend/tests/test_sim_reaction_phase.py` (reaction helpers, `build_oasis_platform`, engagement gate)
  - `backend/tests/test_audit_fixes_runner.py` (checkpoint, config hash, RNG, disk, failure limit)
  - `backend/tests/test_audit_fixes_runloop.py`
  - `backend/tests/test_sim_realism_item20.py` (`inject_engagement_likes`)
- `emergent_metrics.json` has **no reader** in `backend/app` or `frontend/src`; only the runner's rotation list mentions it (`simulation_runner.py:1296-1298`).

**Out of this slice:**
- `app.services.decision_channel`: `_activation_weight_map`, `_outcome_power_map`, `_agent_meta_map`, `_cfg`, `_infer_calendar_unit`,
  `_UNIT_NOMINAL_DAYS`, `_build_active_roster`, `elicit_round`, `_inertia_for_gap`, `_period_days`, `run_decision_channel`
  (3382-3417, 3599-3620, 5988)
- `app.services.worldstate.WorldState` (`step`, `outcome`, `converged`, `shares`) (3383, 3402, 3622-3675)
- `app.services.world_delta.build_world_delta` (3634)
- `app.services.agent_dynamics.sample_engagement_likes` (3999)
- `app.utils.llm_client.LLMClient` (3444, 5989)
- `app.utils.atomic.write_json_atomic`
- `camel.agents.ChatAgent`, `camel.messages.BaseMessage`, `camel.types.OpenAIBackendRole` (4524, 4627, 4662)
- `oasis.social_platform.platform.Platform` / `channel.Channel`
- `networkx` (optional) (2997)
- `action_logger.PlatformActionLogger` / `SimulationLogManager`
- Part-1 helpers: `fetch_new_actions_from_db` (1395), `get_active_agents_for_round` (1802), `_inject_period_context` (1940),
  `_supported_log_kwargs` (1785), `inject_initial_follows` (2460), `_wrap_agent_self_like_guard` (2420), `_write_llm_health` (2270),
  `_write_sim_llm_telemetry` (2179), `_wrap_llm_client_usage` (2123), `ParallelIPCHandler` (840), `validate_direct_child_config_seal` (1285),
  `load_config` (1270), `_attest_canonical_reddit_system_messages` (630)

## Invariants, gates, validation

- **Config seal.** The child re-validates the READY seal before running. Config bytes must match `simulation_config_sha256` (5841-5850;
  part 1, 1277-1278). Reddit canonical actors fail closed if the final system message differs from the sealed composition (5318-5324).
- **Resume safety.** Resume requires `--resume`, a checkpoint with `completed_round ≥ 1` (3846), an existing DB (4795-4797) and a matching
  `config_hash` when one is present (4800-4805). Otherwise the DB is deleted and the run starts fresh (4806-4807). On resume, round-0
  seeding (posts, follows, `round_start/end` 0) is skipped (4850-4851, 4858, 4906, 4936).
- **Organic vs injected accounting.** The `last_rowid` cursor is advanced after injected steps so their trace rows are not
  re-logged as organic:
  - seed backlog (4917-4933)
  - scheduled events (5044-5046)
  - engagement likes (4045-4047)
  Injected rows carry `is_seed_action`, `is_scheduled_event` or `is_engagement_sample` markers. [verifier: not all of them: the round-0 seed CREATE_POSTs (initial_posts) are logged by hand with `action_args={"content"}` and no marker (4884-4891); only the non-CREATE_POST backlog rows (seed FOLLOWs) get `is_seed_action` (4920-4928). The scheduled-event cursor advance runs only when `fired > 0` (5043-5046)]
- **Calendar.** Calendar mode is enabled only by `temporal_config.mode == "calendar"`, never by environment variables (4723-4729). Calendar
  round count = `n_rounds`, and `max_rounds` is never applied (2606-2616).
- **In-band ordering.** Rounds step strictly in ascending order and never above the slowest live platform's watermark (3554-3572).
  Quantitative shares never reach agent-visible text: only the direction (up/down/flat) does (3626-3632; spec comment 3358-3359).
  Convergence is recorded but never stops the loop (3376-3377, 3674-3681).
- **Failure gates.** Disk below threshold, at start or each round, means a hard failure (5873-5876, 5033-5035). N consecutive
  same-class `env.step` failures cause a hard failure (5123-5127).
- **Platform isolation.** In parallel mode one platform's exception does not cancel the other (5930-5943).
- **Soft check.** `agent_configs[i].agent_id == i` misalignment only produces a warning (5896-5906).

## Failure modes & recovery

- **Missing profile file** → that platform returns a result with `env=None`, no actions.jsonl `simulation_end`, and the runner
  marks FAILED (4738-4740, `simulation_runner.py:1079-1103`). In parallel mode the in-band evolver never sees 2 platforms, so it steps
  nothing until main's `force_finalize` flush (3563-3565, 3975). The surviving platform's agents get an empty world delta every round.
- **One platform crashes mid-loop** (disk, step breaker, Reddit attestation) → it never calls `platform_done`, so its watermark freezes.
  The other platform's in-band steps stall at that watermark and buffer in `_pending`. `main` flushes them via
  `_finalize_inband_world_evolution` (3566-3567, 3723-3734). [verifier: the Reddit attestation is not a mid-loop crash: it raises at 5318, before Reddit obtains the evolver at 5540, so Reddit never registers a watermark. Like the missing-profile case, `known < expected` and nothing steps in-loop (3563-3565), rather than stalling "at that watermark"]
- **`env.step` failure** → the round is logged with 0 actions, a heartbeat is sent and a checkpoint written; the loop continues until the
  breaker trips (5105-5128).
- **Scheduled event `env.step` failure** → returns 0, but the CREATE_POST rows were already logged (2554-2571).
- **Crash between rounds** → resume restarts at `completed_round` and skips trace rows up to `MAX(rowid)`, so the half-finished round
  is dropped (4840-4842). [verifier: dropped only from actions.jsonl and the action counts; that round's OASIS writes (posts, comments, likes, follows) stay in the kept `<platform>_simulation.db` (4806-4807 keeps the DB on resume), so they remain visible in feeds and to the emergent metrics] Agents' in-process memory and the Twitter sandbox clock reset (3741-3743). WorldState is rebuilt from the seed,
  so the in-band trajectory covers only the resumed rounds (3375-3376).
- **Emergent / decision-channel / telemetry failures** → all wrapped in try/except, so the simulation results stand (5964-5970, 6025-6026).
- **Signal** → the first SIGTERM or SIGINT sets `_shutdown_event`. The loops break at the next round boundary (5010-5013), but
  `log_simulation_end` still records the planned `total_rounds` (5219). The post-loop analytics, including the LLM-calling post-hoc
  decision channel, still run before exit. The IPC loop exits immediately because the event is set (6056). A second signal calls `sys.exit(1)` (6124-6126).
- **Idle IPC** → auto-close after 60 minutes without commands (6060-6066).

## Surprises

1. **Suspected bug: scheduled events overwrite each other per poster.** `fire_scheduled_events` keys `actions` by agent (2550), so two
   events due in the same round from the same poster post only the last one. Both are still logged and counted (2554-2562). The
   identical bug was fixed for initial posts (4869-4882) but not here.
2. **Suspected: the model-free Twitter feed disables following-feed effects.** With `recsys_type="reddit"` (the default at 2650 and
   2711), OASIS treats the custom platform as Reddit:
   - `platform_type=REDDIT` (`backend/.venv/.../oasis/environment/env.py:109-112`), so the sandbox clock does not advance per step (env.py:197-198).
   - Timestamps follow the Reddit path (`platform.py:180-184`).
   - `refresh()` skips the "posts from people you follow" branch entirely (`platform.py:280`).
   Consequences: `following_post_count` / `echo_chamber_strength` (2673, 2722) are inert under the default recsys, and the seeded follow
   graph does not shape what Twitter agents see. The comment "其余参数与 DefaultPlatformType.TWITTER 逐项一致" (2643, "the remaining
   parameters match DefaultPlatformType.TWITTER item by item") is stale: the default is refresh 2 / max_len 2 (env.py:78-85), but the
   code uses 5 / 100.
3. **Suspected: `echo_chamber_strength=0` cannot be expressed.** `float(pcfg.get(...) or 0.5)` turns 0 into 0.5 (2691).
4. **Asymmetric in-band delta staleness.** `deliver` steps a round only when the slower platform arrives (3563-3570). Each loop reads
   `latest_delta()` right after its own delivery (5182, 5733). So the platform that finishes a round first sees the previous step's
   digest (stale by ≥1 round) in its next WORLD CLOCK header, while the second platform sees the fresh one. The two loops are not
   lockstepped, so the lag grows if one platform runs ahead.
5. **Blocking LLM call on the event loop.** `_step_round` calls the synchronous `elicit_round` → `llm.chat_json` (3609;
   `decision_channel.py:247`) inside the asyncio loop, which stalls both platforms' OASIS coroutines while elicitation runs.
6. **`world_digest.jsonl` is append-only and never rotated.** It is opened with `"a"` (3672), and it is not in the runner's
   `_STALE_DERIVED_ARTIFACTS` (`simulation_runner.py:1292-1307`). A rerun of the same sim (or a resume) appends to the old run's rows.
7. **`SIM_DECISION_CHANNEL` default drift.** `main` reads raw `os.environ` with default `"false"` (5984), while
   `Config.SIM_DECISION_CHANNEL` defaults true (`backend/app/config.py:1483`) and `.env.example:480` says "默认开" (on by default). The
   in-band gate, by contrast, uses `_flag_true` with a Config fallback (3698). Unless the environment variable is exported, the post-hoc
   fallback is off. The same raw-env pattern applies to `SIM_EMERGENT_METRICS` (5957), `SIM_WIRE_RECSYS` (2637) and
   `SIM_DECISION_INERTIA`/`SIM_CONVERGENCE_EPS` (3395, 3399, 5993, 5997), but there the defaults happen to agree with Config.
8. **Exit code drift.** The comment at 5871-5872 says a disk failure exits with code 1 so the runner marks FAILED. But `__main__`
   swallows `SystemExit` (6138-6139), so `sys.exit(1)` at 5835, 5876 and 6126 ends the process with code 0. The runner compensates by
   requiring `simulation_end` rows (`simulation_runner.py:1089-1101`, RUN-17/LOOP-001). Non-SystemExit exceptions in `--twitter-only` /
   `--reddit-only` mode do propagate (no `return_exceptions`) and give a non-zero exit.
9. **The round count is computed in three places.**
   - `_resolve_total_rounds` (2591) drives the loop.
   - The `log_simulation_start` value (4824-4833, 5377-5386) is recomputed: calendar uses `n_rounds` without the `round_dates`
     fallback and with a case-sensitive mode check, so it can log 0 while the loop runs `len(round_dates)` rounds.
   - `main` logs the hours-formula count even in calendar mode (5878-5890).
   The `_resolve_total_rounds` docstring says it runs "before log_simulation_start" (2593), which the code does not do.
10. **Dead or unused code.**
    - `_INTERACTION_ACTIONS` is never used (2764-2767).
    - `num_shares` is selected but unused (3111).
    - The `agent_names` parameter of `_fetch_round_posts` is unused (3943).
    - The `loop` parameter of `setup_signal_handlers` is unused (6101).
    - `_plat` (5204) duplicates `_ckpt_platform` (4983).
11. **Suspected: the lexicon sentiment is substring-based** (2809-2810). "against" contains "gain" (positive), "window" contains "win",
    "misleading" contains "lead", and CN "不好" scores positive via "好". Polarization and net sentiment are therefore noisy.
12. **Emergent metrics have no consumer.** The docstring at 3213 says the aggregate is "供报告 agent 读取" (for the report agent to
    read), but nothing in `backend/app` or `frontend/src` reads it. `.env.example:357` says the metrics go into `run_summary.json`, but the
    code writes separate files. `DRF_ARCHITECTURE.md:987-996` cites stale anchors (`:2423`, `:2462-2466`, `:3919-3952`; the code is now at
    3140, 3179-3183 and 5983-6026).
13. **Reaction actions carry no provenance marker.** Seed, scheduled and sampled actions are flagged, but reaction-phase comments and likes
    are logged exactly like organic ones (4651-4657). Downstream organic-ratio detectors cannot separate them.
14. **Shared RNG across platforms.** In parallel mode, `_RNG` is one process-global instance. Each platform checkpoints a snapshot of it
    (4996, 5547), and on resume both call `_restore_rng_state` on the same object, so the last restore wins (4844, 5397). The reaction
    phase always calls `rng.shuffle` (4605), so enabling it shifts every later sample. OASIS `refresh()` uses the global `random`
    module, not `_RNG`. Exact replay across a crash is not achievable in parallel mode.
15. **Engagement-like logging is not tied to DB success.** Every sampled pair is logged as a LIKE_POST (4050-4060) regardless of whether
    OASIS accepted the like. The trace rows used to verify it are discarded (4047).
16. **Stale comments.**
    - "world_delta_text … 本切片恒为 \"\"" ("this slice is always \"\"") at 4948 and 5499 is stale; in-band now fills it.
    - The "(评论/引用/背书)" ("comment / quote / endorse") note at 5148 and 5699 mentions quoting, but quote_post is deliberately excluded
      from the reaction tools (4091).
17. **Twitter/Reddit loops are about 530 lines of copy-paste** (4692-5225 vs 5228-5776). Only the Reddit loop attests sealed system
    messages, so Twitter has no fail-closed seal check.
18. **Hours-mode `round_to_date` ignores `--max-rounds`.** A truncated run maps its last round to a date well before the horizon (3337-3348).

## Verification

Adversarial pass against `backend/scripts/run_parallel_simulation.py` on `main` as it is on disk, plus the cited OASIS sources under
`backend/.venv/lib/python3.12/site-packages/oasis/`, `backend/app/config.py`, `backend/app/services/{simulation_runner,decision_channel,world_delta,simulation_config_generator}.py`,
`.env.example` and `DRF_ARCHITECTURE.md`. No code was run.

**Verdict counts (36 items):** 28 confirmed, 8 imprecise, 0 refuted, 0 unverifiable.
That covers 14 key claims (11 confirmed, 3 imprecise), 17 surprises (all confirmed) and 5 further imprecise statements found while spot-checking.

### Non-confirmed items, with corrections

1. **Claim: the cursor is advanced after seed, scheduled and engagement injection, and injected rows carry markers (imprecise).** The round-0 seed
   CREATE_POSTs are logged by hand with no marker (4884-4891). Only the backlog's non-CREATE_POST rows (seed FOLLOWs) get `is_seed_action`
   (4920-4928). The scheduled-event cursor advance runs only when `fired > 0` (5043-5046). The rest holds: 4045-4060 and 2560.
2. **Claim: SIM-REACT gives each active agent a helper with `create_comment`/`like_post`/`like_comment` (imprecise).** Twitter agents never
   get `like_comment`, because `TWITTER_ACTIONS` lacks it (214-224) and OASIS builds an agent's tools from `available_actions`
   (oasis `social_agent/agent.py:84-105`). Not every active agent reacts either: only the `SIM_REACTION_SHARE` subsample (4601-4604), only agents
   with ≥1 candidate (4613-4614), and only agents that have `create_comment` and a `model_backend` (4630-4635). Confirmed: `max_iteration=1`,
   `step_timeout=240` (4531-4532), `env.llm_semaphore` (OASIS `env.py:71`) with a `Semaphore(4)` fallback (4624-4626), `asyncio.gather` (4646),
   and the sampler's auto-off default (3904-3906).
3. **Claim: main auto-closes after `SIM_IDLE_CLOSE_MIN` and "only then" calls `env.close()` (imprecise).** `env.close()` runs after any exit
   from the wait loop: `close_env` (process_commands returns False, 6057-6059), idle timeout (6060-6066), shutdown signal (6056, 6069-6070) or a
   caught exception (6073-6078). It also runs immediately with `--no-wait` (5852, 6029). Envs of platforms whose gather result became `None`
   are never closed (5938-5943, 6084-6090).
4. **Walkthrough: a malformed scheduled-event `round` skips "that round's events" (imprecise).** The comprehension at 2538 parses every event's
   `round` on every call, so one bad entry raises in every round and disables scheduled-event firing for the whole run (caught at 5047-5048).
   `_scheduled_events_due` still tolerates the entry (2581-2587), so WORLD CLOCK headers (5088) and in-band delivery (5180-5181) list events
   that were never posted.
5. **Walkthrough: `max_rec_post_len=100` "lets every agent see every post" (imprecise).** With ≤100 posts, every post goes into each agent's rec
   table (oasis `recsys.py:229-232`). `refresh()` then shows a random 5-post sample (`refresh_rec_post_count=5`, oasis `platform.py:273-277`,
   drawn from the global `random`).
6. **Walkthrough: `run_reaction_phase` fetches threads "between window_start and round_start" (imprecise).** It fetches the newest ≤60 posts with
   `post_id > window_start`, which includes this round's posts. `round_start` only sets the `recent` flag (4285-4289, 4306).
7. **Failure modes: a Reddit attestation failure is listed as a mid-loop crash whose watermark freezes (imprecise).** The attestation raises at 5318,
   before Reddit gets the evolver at 5540. Reddit never registers a watermark, so `known < expected` and nothing steps in the loop (3563-3565).
   This is the same mechanism as the missing-profile case, not a stall at a frozen watermark.
8. **Failure modes: on resume "the half-finished round is dropped" (imprecise).** It is dropped only from actions.jsonl and the counts. Its OASIS DB
   writes persist, because resume keeps `<platform>_simulation.db` (4806-4807), so they stay visible in feeds and to emergent metrics.

### Confirmed, with context worth keeping

- Surprise 9 (three round-count computations) is accurate. For generated calendar configs, though, the time_config shim sets
  `total_simulation_hours = n_rounds` and `minutes_per_round = 60` (`backend/app/services/simulation_config_generator.py:577-582`). The
  hours-formula log in `main` (5878-5890) therefore normally equals `n_rounds`. The drift shows only for hand-made or legacy configs.
- Surprise 7 / claim 10 (the `SIM_DECISION_CHANNEL` raw-env default of "false"): the script `load_dotenv`s the project `.env` (125-134), so a
  `SIM_DECISION_CHANNEL=true` line in `.env` would enable it. The "false" default applies only when neither the process env nor `.env` sets it.
- Claim 8 (in-band gating): the in-loop gate also exempts platforms that are already done (3566). `force_finalize` steps every pending round
  with no gate (`flush_all`, 3560-3561, 3515).
- Claim 13 / surprise 8: confirmed. `SystemExit` raised in the `main()` task propagates out of `asyncio.run` and is swallowed at 6138-6139.
  The runner then marks the run FAILED via the missing `simulation_end` (`simulation_runner.py:1078-1101`, `:1410-1413`).

Other spot-checks found correct, among them: the 2569-2571 return-0 path; the `_scheduled_events_due` call sites 5088/5639/5181/5732; the
DefaultPlatformType fallbacks (4813, 5366); `start_time` unanchored → `datetime.now()` (oasis `platform.py:78-79`);
`following_post_count = round(2+echo*4)` (2722); `Platform.__init__` → `create_db` (oasis `platform.py:83`); cascade skip rule (3125-3126);
trajectory outside the try (3158); `n_rounds` = max stepped round (3530); `converged_at` needs streak ≥ window and rnd ≥ 2 (3677-3679);
`_load_round_checkpoint` needs ≥1 (3846); `start_round = min(completed, total)` (5000); the Reddit loop is otherwise identical to Twitter
(diffed: only names, model boost, profile file, canonical enforce/attest and the platform string differ); per-round control-flow order (5008-5193);
`setup_signal_handlers` semantics (6111-6126); and the `__main__` finally block (6140-6154).

### Omissions (significant behavior the map does not cover)

1. **In-band events come from config, not from what fired.** `deliver()` receives `_scheduled_events_due(...)` (5180-5181, 5731-5732), so events
   reach the world digest and WorldState roster context even when `fire_scheduled_events` failed or skipped them (2546-2547, 2569-2571, 2538).
2. **The post-hoc decision channel ingests non-organic rows.** `_read_actions_for_decision_channel` filters only `event_type` / missing `agent_id`
   (3282). Seed FOLLOWs, scheduled-event posts, engagement-sample likes and reaction actions all count as activity in the post-hoc roster. The
   in-band roster sees only organic + reaction `actual_actions` (5157, 5180).
3. **SIGTERM-truncated runs can be marked COMPLETED.** The loop breaks early (5010-5013) but still writes `simulation_end` (5218-5219). The runner
   treats `simulation_end` as authoritative completion and flips STARTING/RUNNING to COMPLETED (`simulation_runner.py:1189-1211`), unless the
   runner already moved to STOPPING.
4. **Platform isolation is in-process only.** A platform that raises in parallel mode writes no `simulation_end`, so the runner marks the whole
   run FAILED even though the other platform finished (5930-5943; `simulation_runner.py:1078-1101`, `:1410-1413`).
5. **Scheduled-event posts are never "recent" for reaction scoring.** They fire (5038-5048) before `_advance_reaction_window` snapshots `round_start`
   (5096-5097), so they score +0.3 instead of +1 (4306, 4437) even though they are this round's posts.
6. **Resumed runs restart the reaction window from zero.** `_reaction_state` starts empty on resume (4977), so the first resumed round's window is
   `post_id > 0`, the newest 60 posts in the DB (4685-4689, 4277-4290), not just the last round's posts.
7. **Twitter reaction tools exclude `like_comment`** (214-224, 4633). The prompt's like_comment clause is Reddit-only (4498-4499).
