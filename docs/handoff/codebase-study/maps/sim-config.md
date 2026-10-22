# sim-config — Simulation config generator

Scope: `backend/app/services/simulation_config_generator.py`, all 4,006 lines (branch `main`, on-disk checkout as of 2026-10-11). Every line was read.
All anchors are `path:line` relative to the repo root. A bare `:N` means `backend/app/services/simulation_config_generator.py:N`.
Code outside the slice is cited only to explain what a call does or who consumes the output.

---

## Purpose & position in the pipeline

This module is the PREPARE stage's third sub-step (Stage 4), "simulation config". It runs after entity filtering, cast selection, actor-context pack sealing and OASIS persona generation in `SimulationManager.prepare_simulation` (`backend/app/services/simulation_manager.py:862`). The manager builds a fresh `SimulationConfigGenerator()` (`backend/app/services/simulation_manager.py:1155`) and calls `generate_config(...)` (`backend/app/services/simulation_manager.py:1164-1178`). It serializes the returned `SimulationParameters` with `to_json()` into `simulations/<sim_id>/simulation_config.json` through an atomic write (`backend/app/services/simulation_manager.py:1224-1226`). The file is then sealed (`backend/app/services/simulation_manager.py:1281`). The OASIS runner subprocess (`backend/scripts/run_parallel_simulation.py`) consumes it.

The generator turns four inputs into a complete, machine-readable simulation plan:
- the forecast question (`simulation_requirement`);
- the research report text (`document_text`);
- the filtered graph entities (`EntityNode` list, one per agent);
- optionally, the deep-research `actors.json` dossier (`actors`) and the sealed per-actor `actor-context/v1` packs (`actor_context_packs`).

The plan contains:
- a time model, either the legacy diurnal "hours" model or a calendar timeline (`temporal_config`);
- event seeds: hot topics, initial posts, dated scheduled events, and an initial follow graph;
- per-agent activity/stance/influence configs, optionally plus programmatic "silent majority" audience agents;
- fixed platform weights;
- a shared "world brief" text that every agent sees.

It has two authority regimes, chosen per dossier by `_dossier_uses_canonical_intelligence` (`:1395-1408`):
- **Legacy / unversioned dossiers** keep the historical behavior. They use graph summaries, the whole report, flat actor `stance`/`influence`/`memory`/`incentives`, LLM agent configs, and raw `relationships[]` and `key_events[]`.
- **Canonical `actor-intelligence/v1` dossiers** are fail-closed. Only explicitly public, source-bound rows from validated `actor-context/v1` packs may shape behavior. The agent-config LLM is skipped entirely; agent configs are deterministic neutral baselines. Graph labels and summaries never reach the prompts.

LLM usage (all through `LLMClient.chat` with `response_format={"type":"json_object"}`):
- time config: 1 call, hours mode only;
- horizon fallback: 1 call, calendar mode only, and only when deterministic extraction fails;
- event config: 1 call;
- agent configs: one call per batch of 15 entities, legacy dossiers only.

---

## Walkthrough (source order)

### Module header, imports, module constants (`:1-97`)
- **Docstring (`:1-11`).** Describes the original four-step design: time, event, batched agent, platform.
- **Imports (`:13-56`).**
  - `Config`;
  - `sim_timeline`, the pure calendar-timeline utilities;
  - 13 helpers from `utils/actors.py` (`:24-38`);
  - `parse_as_of`, `LLMClient` and `EntityNode`/`ZepEntityReader` (`ZepEntityReader` is imported but never used in the slice);
  - the actor-context contract helpers (`:43-51`);
  - the prompt-injection sanitizers from `actor_role_prompt.py` (`:52-56`).
- **Logger (`:58`).** `logger = get_logger('mirofish.simulation_config')`.
- **Gap-audit constants (`:60-66`).**
  - `ACTOR_CONFIG_EVIDENCE_GAP_AUDIT_VERSION = "actor-config-evidence-gap-audit/v1"`;
  - `..._KEY = "evidence_gap_audit_not_actor_or_llm_knowledge"`, the projection key that is kept out of behavior;
  - `..._MAX_BYTES = 65_536`.
- **`_LEGACY_REL_TYPES` (`:72-75`).** The 8 pre-valence relationship types: ALLY_OF, OPPOSES, COMPETES_WITH, REGULATES, DEPENDS_ON, PARTNERS_WITH, INFLUENCES, OTHER. Any other type, or an explicit valence/polarity field, turns on valence-aware logic (C5).
- **`CHINA_TIMEZONE_CONFIG` (`:78-97`).** Beijing diurnal buckets and multipliers. It is **referenced nowhere** (dead; see Surprises).

### Activity profiles (`:100-190`)
- **`ACTIVITY_PROFILES` (`:113-179`)** has three named profiles: `china_social` (default), `us_business` and `global_market`. Each holds:
  - `time_prompt_principles`, the Chinese-language rhythm bullets for the time-config prompt;
  - `time_system_prompt`;
  - `default_time_reasoning`;
  - `agent_prompt_rhythm`;
  - `agent_active_hours_hint`;
  - `agent_system_prompt`;
  - `peak_hours`, `off_peak_hours`, `morning_hours` and `work_hours`.
- **Profile values.**
  - `china_social`: peak 19-22, off-peak 0-5, morning 6-8, work 9-18 (`:136-139`).
  - `us_business`: peak 9-17, work 9-17 (`:156-159`).
  - `global_market`: peak 13-21 (`:174`).
- **`get_activity_profile()` (`:182-190`)** reads `getattr(Config, "SIM_ACTIVITY_PROFILE", "china_social")`, lowercases it, and falls back to `china_social` for unknown names.

### Dataclasses (`:193-407`)
- **`AgentActivityConfig` (`:193-247`)**, one per agent.
  - Identity: `agent_id`, `entity_uuid`, `entity_name`, `entity_type`.
  - Activity: `activity_level` = 0.5, `posts_per_hour` = 1.0, `comments_per_hour` = 2.0, `active_hours` = 8..22, `response_delay_min` = 5, `response_delay_max` = 60.
  - Disposition: `sentiment_bias` = 0.0, `stance` = "neutral" (vocabulary: supportive/opposing/neutral/observer), `influence_weight` = 1.0, `interested_topics` = [].
  - `gains_if` and `loses_if`: R2-SIM-3 incentive strings, default "" (`:230-231`).
  - `actor_context_digest`, `actor_context_evidence_gap_audit` and `actor_context_urgency`: audit-only (`:237-241`).
  - `cadence` = "sampled"; it becomes "principal" for top actors in calendar mode (`:247`).
- **`TimeSimulationConfig` (`:250-277`).**
  - Duration: `total_simulation_hours` = 72, `minutes_per_round` = 60.
  - Activation range: `agents_per_hour_min` = 5, `agents_per_hour_max` = 20.
  - Hour buckets with multipliers: peak 19-22 ×1.5, off-peak 0-5 ×0.05, morning 6-8 ×0.4, work 9-18 ×0.7.
- **`EventConfig` (`:280-297`).** Fields: `initial_posts`, `scheduled_events`, `hot_topics`, `narrative_direction`, and `initial_follows` (`[[follower, followee], ...]`).
- **`PlatformConfig` (`:300-322`).**
  - Fields: `platform`, `recency_weight` = 0.4, `popularity_weight` = 0.3, `relevance_weight` = 0.3, `viral_threshold` = 10, `echo_chamber_strength` = 0.5, and three recsys knobs.
  - The recsys knobs are `recsys_type` = "", `refresh_rec_post_count` = 0 and `max_rec_post_len` = 0. The comment (`:316-319`) says they take effect only when `SIM_WIRE_RECSYS=true`, and that the weight fields are display-only.
- **`SimulationParameters` (`:325-407`)**, the top-level object.
  - Base fields: `simulation_id`, `project_id`, `graph_id`, `simulation_requirement`, `time_config`, `agent_configs`, `event_config`, `twitter_config`/`reddit_config` (Optional), `llm_provider`/`llm_model`/`llm_base_url`, and `as_of_date` (Optional str).
  - Optional additions: `world_brief` (str), `temporal_config` (Optional dict) and `output_language` (str).
  - Metadata: `generated_at` = `datetime.now().isoformat()` (local time, `:370`) and `generation_reasoning`.
  - `to_dict()` (`:373-403`) always emits the base keys, in that order with `as_of_date` right after `simulation_requirement`. It adds `world_brief`, `temporal_config` and `output_language` **only when truthy** (`:395-402`), so legacy configs stay byte-identical. No API key is serialized.
  - `to_json()` (`:405-407`) is `json.dumps(ensure_ascii=False, indent=2)`.

### `SimulationConfigGenerator` class constants and `__init__` (`:410-453`)
- **Context-size constants.**
  - `MAX_CONTEXT_LENGTH = 50000` caps the shared context (`:424`).
  - `AGENTS_PER_BATCH = 15` (`:426`).
  - `TIME_CONFIG_CONTEXT_LENGTH = 10000` (`:429`).
  - `EVENT_CONFIG_CONTEXT_LENGTH = 8000` (`:430`).
  - `ENTITY_SUMMARY_LENGTH = 300` (`:431`).
  - `AGENT_SUMMARY_LENGTH = 300` (`:432`).
  - `ENTITIES_PER_TYPE_DISPLAY = 20` (`:433`).
- **`__init__` (`:435-453`).** Arguments override Config values:
  - `provider` = `(provider or Config.LLM_PROVIDER or "claude-cli").lower()`;
  - `api_key`, `base_url` and `model_name` each default to the matching Config value.
  - It builds one `LLMClient(provider, api_key, base_url, model)` (`:448-453`). The caller passes no arguments (`backend/app/services/simulation_manager.py:1155`), so the global LLM settings always apply.

### `generate_config(...)` (`:455-805`): the main entry point
- **Signature.** `simulation_id, project_id, graph_id, simulation_requirement, document_text, entities, enable_twitter=True, enable_reddit=True, progress_callback=None, actors=None, actor_context_packs=None, max_rounds=None, research_language=None`.
- **Per-run instance state.** These attributes are reset or set on every call, so a single instance is not safe for concurrent `generate_config` calls:
  - `_profile_override` (`:505`);
  - `_temporal_timeline` (`:508`, `:569`);
  - `_output_language` (`:516`);
  - `_agent_batch_stats` (`:633`);
  - `_run_hot_topics`, set later in `_parse_event_config` (`:2504`).

Steps:
1. **Profile override (PREP-4, `:509-513`).** If `research_language` starts with "en" and the `SIM_ACTIVITY_PROFILE` **environment variable** is empty, `_profile_override = "global_market"`.
2. **Output language (`:516-519`).** `_resolve_output_language(research_language, simulation_requirement)` returns "English", "Chinese" or "".
3. **Step count (`:522-531`).** `num_batches = ceil(len(entities)/15)` and `total_steps = 3 + num_batches`. `report_progress(step, msg)` forwards to `progress_callback(step, total_steps, msg)` and logs.
4. **Context (`:534-540`).** `_build_context(...)` builds one shared prompt context string.
5. **Calendar timeline (`:551-569`).** Runs only if `Config.SIM_TEMPORAL_MODE == "calendar"`; `getattr` falls back to "hours", but Config's own default is "calendar" (`backend/app/config.py:1067`). It calls `_build_temporal_timeline(...)`. **Any exception downgrades the whole run to hours mode** (`temporal_timeline=None`, warning at `:566-568`).
6. **Step 1, time config (`:572-589`).**
   - Calendar mode skips the LLM. It uses `_get_default_time_config` followed by `_parse_time_config`, then overwrites the shim fields `total_simulation_hours = n_rounds` and `minutes_per_round = 60` (`:579-582`), so legacy `hours*60/minutes_per_round` formulas compute `n_rounds`.
   - Hours mode calls `_generate_time_config` (LLM) and then `_parse_time_config`.
7. **Step 2, event config (`:592-605`).** `_generate_event_config` (LLM) followed by `_parse_event_config`.
8. **World brief (`:614-628`).**
   - `_load_prediction_markets(simulation_id)` loads the market rows.
   - `_build_world_brief(requirement, actors, event_config.hot_topics, prediction_markets, actor_context_packs)` builds the brief.
   - Exceptions produce "" and a warning.
9. **Steps 3..N, agent batches (`:633-664`).**
   - `_agent_batch_stats = {llm_batches, rule_batches, rule_agents}` (`:633`).
   - Entities are sliced into batches of 15 and passed to `_generate_agent_configs_batch` (`:645-652`).
   - A reasoning string records the LLM/rule split (`:656-659`). A warning is logged when any batch fell back to rules (`:660-664`).
10. **Initial post assignment (`:667-670`).** `_assign_initial_post_agents(event_config, all_agent_configs)`. This runs **before** audience agents are appended.
11. **Audience (`:679-692`).** `_generate_audience_agent_configs(start_idx=len(all_agent_configs), ...)` is appended. Exceptions are skipped.
12. **Cadence tiers (`:698-703`).** `_assign_cadence_tiers(all_agent_configs)`. On an exception, every agent stays "sampled".
13. **Initial follows (`:708-719`).** `_build_initial_follows(...)`. Exceptions produce `[]`.
14. **Scheduled events (`:724-735`).** `_build_scheduled_events(actors, time_config, all_agent_configs, max_rounds, timeline, packs)`. Exceptions produce `[]`. In calendar mode it also mutates `temporal_timeline.beyond_horizon_events` and `.warnings`.
15. **Echo-chamber follows (`:738-753`).** `_build_echo_chamber_follows(all_agent_configs, twitter_config_strength=None, ...)` returns a set of edges. They are unioned with `initial_follows` and re-sorted (`:746-749`). Exceptions are skipped.
16. **Platform configs (`:756-778`).** These are hard-coded, with no LLM.
    - Twitter: weights 0.4/0.3/0.3, viral 10, echo 0.5.
    - Reddit: weights 0.3/0.4/0.3, viral 15, echo 0.6.
    - The recsys knobs are left at ""/0.
17. **Assembly (`:781-801`).**
    - `as_of_date` = `str(actors["as_of_date"])` if present, else None. This is the raw, unparsed dossier value.
    - `output_language` = `_output_language`.
    - `temporal_config` = `asdict(temporal_timeline)` or None.
    - `generation_reasoning` = `" | ".join(reasoning_parts)`.

### `_activity_profile()` (`:810-815`)
Returns `ACTIVITY_PROFILES[_profile_override]` if one is set; otherwise it returns `get_activity_profile()`.

### `_build_initial_follows(agent_configs, entities, actors, packs)` (`:817-891`), T3.2
- **Name index.** `agent_id_by_name` maps `normalize_name(entity_name)` to `agent_id`, and the **first agent wins** on duplicates (PREP-10, `:832-845`). Duplicates are logged as a warning.
- **Source 1, research relationships.**
  - Canonical v1: `_canonical_context_relationship_rows` followed by `_canonical_relationship_follow_pairs` (`:851-857`).
  - Legacy: `build_initial_follow_graph(actors, agent_id_by_name)` (`:859-861`). Its directions come from `backend/app/utils/actors.py:1270`; for example, ALLY_OF makes the lower-influence actor follow the higher one, and OPPOSES/COMPETES/PARTNERS produce mutual follows.
- **Source 2, graph neighbor edges.** Used only for legacy dossiers (`:865-889`).
  - For each entity matched to an agent, it walks `e.related_edges`, up to `MAX_GRAPH_FOLLOWS_PER_AGENT = 8` per agent (`:808`, `:873`).
  - `direction == "outgoing"` adds src→dst; anything else adds dst→src.
- **Result (`:890-891`).** Edges whose endpoints are not valid agent ids are dropped, and the list is sorted.

### Cadence tiers (`:893-934`)
- **Constants.** `PRINCIPAL_CADENCE_MAX = 20`, `PRINCIPAL_CADENCE_MIN_INFLUENCE = 0.6`, `PRINCIPAL_CADENCE_FRACTION = 0.5`, `PRINCIPAL_CADENCE_GRADE_MIN = 4` (`:894-902`).
- **Selection.** `_assign_cadence_tiers` (`:904-934`) takes the non-audience agents (`entity_type != "Audience"`). Eligible agents are those with `influence_weight >= 0.6`, sorted by (-influence, agent_id). The budget is 20.
- **SIM-ADD-4 degeneracy guard (`:925-930`).** It fires when `len(non_audience) > 4` and `min(len(eligible), 20) >= len(non_audience)`, that is, when every non-audience agent would become principal. The budget then becomes `max(4, ceil(non_audience × 0.5))`.
- **Output.** The chosen agents get `cadence = "principal"`, and the function returns their count. It is deterministic.

### `_build_temporal_timeline(requirement, actors, context, max_rounds)` (`:936-990`)
- **as_of (`:954-959`).** `actors["as_of_date"]` is passed through `parse_as_of`. If it is unparseable or missing, today's date is used and the warning `as_of_defaulted` is appended (`:988-989`).
- **Horizon ladder (`:962-969`).**
  1. `sim_timeline.extract_horizon(f"{requirement}\n{central_question}", as_of)`, a deterministic 4-tier extractor: explicit date, anchored period, relative span, bare year (`backend/app/utils/sim_timeline.py:266`).
  2. `_llm_extract_horizon(context, as_of)`.
  3. `sim_timeline.default_horizon(as_of, Config.SIM_HORIZON_DEFAULT_MONTHS or 12)`.
- **Round cap (`:971-979`).** `target_max = SIM_CALENDAR_TARGET_MAX_ROUNDS (36)`, then min'ed with a positive `max_rounds` and with a positive `OASIS_DEFAULT_MAX_ROUNDS` (36 by default, `backend/app/config.py:1063`).
- **Build (`:981-987`).** `sim_timeline.build_timeline(as_of, horizon, target_max, reference_max=SIM_CALENDAR_TARGET_MAX_ROUNDS, hard_max=SIM_CALENDAR_HARD_MAX_ROUNDS (48))`. `n_rounds` always equals `len(round_dates)` (`backend/app/utils/sim_timeline.py:563`).

### `_llm_extract_horizon(context, as_of)` (`:992-1026`)
- **Prompt (`:1000-1011`).** Chinese prompt over `context[:10000]`. It asks for `{"horizon_date": "YYYY-MM-DD"}` or null; rules: prefer an explicit date, a bare year means Dec 31, never fabricate. System prompt: "你是预测问题分析专家。返回纯JSON格式。"
- **Call and validation.** It calls `_call_llm_with_retry` and returns None on exception (`:1013-1017`). The result is re-parsed with `parse_as_of`, and dates outside `(as_of, as_of+360 months]` are discarded (`:1022-1025`).
- **Return.** `HorizonResult(iso, "llm", "", False, 0.7)` (`:1026`).

### `_build_scheduled_events(actors, time_config, agent_configs, max_rounds, timeline, packs)` (`:1028-1136`), T3.8
- **Guard.** Returns `[]` if `actors` is not a dict or there are no agents (`:1054-1055`).
- **Canonical v1 (`:1057-1068`).** The event source is reduced to `{"as_of_date", "key_events": _canonical_context_event_rows(...)}`. If no safe events remain it returns `[]`.
- **Calendar branch (`:1070-1090`).**
  - Calls `events_to_calendar_rounds(event_source, timeline.round_dates, timeline.as_of_date, timeline.horizon_date)` (`backend/app/utils/actors.py:1463`). This is exact interval placement; events on or before `as_of` are dropped, and events after the horizon are returned separately.
  - Assigns `timeline.beyond_horizon_events = beyond`.
  - Counts events with unparseable dates and appends the warning `event_date_unparsed:<n>`.
- **Hours branch (`:1091-1108`).**
  - `config_rounds = max(1, int(total_hours*60/max(1, minutes_per_round)))`.
  - Budget: a positive `max_rounds`; otherwise, if `SIM_SCHEDULE_CLAMP_ROUNDS` (default true), `OASIS_DEFAULT_MAX_ROUNDS`.
  - `total_rounds = min(config_rounds, budget)` when the budget is positive (PREP-1).
  - Then calls `events_to_schedule(event_source, total_rounds, as_of)` (`backend/app/utils/actors.py:1398`). That helper places events proportionally and applies the PREP-5 reaction buffer when `SIM_EVENT_REACT_BUFFER` is set.
- **Poster selection (`:1112-1126`).**
  - Builds the index `normalize_name(entity_name) → config` with a dict comprehension, so the **last** duplicate wins.
  - The poster is the first agent, in insertion order, whose normalized name has at least 2 characters and is a substring of the normalized event text. Otherwise it is `max(agent_configs, key=influence_weight)`.
- **Output (`:1127-1135`).** Each event becomes `{"round", "content", "date", "poster_agent_id", "poster_name"}`. In calendar mode the content gets a `"[<date>] "` prefix.

### Valence (C5) helpers (`:1138-1333`)
- **`_valence_signal_active(actors, packs)` (`:1138-1177`).**
  - False if `Config.SIM_VALENCED_RELATIONS` is off (default on, `backend/app/config.py:1519`) or `actors` is not a dict.
  - Rows: canonical v1 uses `_canonical_context_relationship_rows`; legacy uses raw `actors["relationships"]` (not endpoint-filtered).
  - True if any row has a non-empty `valence`, a numeric non-bool `polarity`, or a `type` outside `_LEGACY_REL_TYPES`.
- **`_relation_sentiment_nudge(name, actors, packs)` (`:1179-1224`).**
  - It averages `relation_polarity(r)` over the rows where the actor is the source or target. Canonical rows marked `actor_local` count only for the context owner.
  - Returns `clamp(avg×0.5, -0.5, 0.5)`, or 0.0 when nothing matches.
- **`_build_echo_chamber_follows(agent_configs, twitter_config_strength=None, actors, packs)` (`:1226-1333`), T3.4.**
  - `strength` defaults to 0.5, and it returns an empty set if `strength <= 0` or there are fewer than 3 agents.
  - Clusters are keyed by `(stance.lower(), normalize_name(interested_topics[0]))`.
  - Within a cluster of 2 or more, every member follows up to `k = max(1, round(3×strength))` top-influence peers. At strength 0.5 that is `round(1.5) = 2` (`:1257-1270`).
  - Bridges: the top `max(2, n//10)` agents by influence each follow up to 2 others in that top set (`:1272-1282`).
  - When valence is active, ALLIED and ADVERSARIAL relationships both add mutual follows (`:1286-1332`). The first agent wins on duplicate names, and canonical `actor_local` rows add only edges whose follower is the context owner.

### World brief and market priors (`:1335-1937`)
- **Constants.** `WORLD_BRIEF_MAX_CHARS = 1400`, `WORLD_BRIEF_QUESTION_CHARS = 400`, `MARKET_PRIORS_TOP_N = 5` (`:1336-1339`).
- **`_market_priors_enabled()` (`:1341-1348`).** Returns `str(Config.SIM_MARKET_PRIORS)` not in {"false", "0", "no", "off"}.
- **`_load_prediction_markets(simulation_id)` (`:1350-1382`).**
  - Lazily imports `PipelineManager` (`:1364`) and iterates `list_pipelines()`. For each pipeline it calls `PipelineManager.load(pid)` until one has `data["simulation_id"] == simulation_id`.
  - It then reads `<handoff_dir>/prediction_markets.json`, taking `markets[]`, or the payload itself if that is a list, and keeps the dict rows.
  - It stops at the first matching pipeline (`:1379`). Every failure returns `[]`, logged at debug level.
- **Canonical gate.**
  - `_actor_intelligence_version` and `_is_canonical_actor` (`:1384-1393`) check whether `actor["intelligence"]["schema_version"] == "actor-intelligence/v1"`.
  - `_dossier_uses_canonical_intelligence` (`:1395-1408`) is true if the top-level `actor_intelligence_contract.schema_version` equals v1, or **any** actor row is v1.
- **`_validated_canonical_context_pack(actor, packs)` (`:1410-1464`).** This is the fail-closed pack check. It raises `ValueError` for any of these:
  - the actor is not canonical;
  - the pack for `actor_id_for(actor)` is missing;
  - `schema_version != "actor-context/v1"`;
  - the actor_id differs;
  - the normalized name differs;
  - `actor_intelligence` is missing on either side;
  - `canonical_json_sha256(pack.actor_intelligence) != sha(actor.intelligence)`;
  - the provenance source is missing, has the wrong contract version, or has the wrong intelligence sha.
- **Visibility vocabularies (`:1466-1475`).**
  - `_PUBLIC_ACTOR_CONTEXT_VISIBILITIES` = {public, public_record, publicly_known, open_source}.
  - `_ACTOR_LOCAL_CONTEXT_VISIBILITIES` is defined but **never read** in the slice.
  - `_NON_BEHAVIORAL_EVIDENCE_TYPES` = {analyst_inference, contested, unknown}.
- **`_validate_actor_context_dossier_binding(pack, actors)` (`:1477-1492`).** Requires `pack.source.actors_sha256 == canonical_json_sha256(actors)`.
- **`_canonical_context_relationship_rows(actors, packs)` (`:1494-1554`).**
  - For each canonical actor that has a pack, it takes `pack["relationships"]`.
  - Each row must be byte-identical (canonical sha) to some row in `actors["relationships"]`; otherwise it raises (`:1533-1536`).
  - Rows are sanitized with `_safe_actor_context_relationship`, kept only if they have a source and target and `is_hard_public_relationship` holds (source-bound + verified/actor-stated + public visibility; `backend/app/services/actor_context.py:415`).
  - Kept rows are tagged `_runtime_scope="public"` and deduped by (source, target, TYPE, evidence_type, visibility).
- **`_canonical_relationship_follow_pairs(rows, id_by_name)` (`:1556-1594`).**
  - Mutual follows: ALLY_OF, PARTNERS_WITH, OPPOSES, COMPETES_WITH, SANCTIONS, LITIGATES_AGAINST, CRITICIZES.
  - Source→target: DEPENDS_ON, REGULATES, CUSTOMER_OF.
  - Target→source: INFLUENCES, SUPPLIES, FUNDS, INVESTS_IN, BACKS, OWNS, SUPPORTS, ENDORSES.
  - `actor_local` rows add only edges whose follower is the context owner.
- **`_canonical_context_event_rows(actors, packs)` (`:1596-1660`).**
  - Pack events must be dossier-bound, by sha against `actors["key_events"]`; otherwise it raises.
  - An event is kept only if it has event text (≤600 characters), a date (≤40), at least one source_ref, a public visibility and a behavioral evidence type. [verifier: the evidence-type gate is a deny-list (`evidence_type not in {analyst_inference, contested, unknown}`), so an event with a missing/empty `evidence_type` passes as "behavioral" (`:1641-1647`)]
  - Kept events are deduped by (date, event.casefold()) and returned as `{date, event, source_refs, visibility}`.
- **`_canonical_public_world_rows(actors, packs)` (`:1662-1732`).**
  - Walks all `INTELLIGENCE_DIMENSIONS` claims in each validated pack.
  - Keeps claims that have claim text (≤520 characters, sanitized) and refs. Drops `analyst_inference` claims and claims without a public visibility (read from `visibility` or `qualifiers.visibility`).
  - Dedupes by claim text and returns `{actor_name, dimension, claim, evidence_type, as_of_date, source_refs}`.
- **`_build_canonical_public_world_brief(requirement, actors, packs, max_chars, english)` (`:1734-1777`).**
  - Optional question header: the sanitized requirement, capped at 400 characters.
  - "Public, source-bound shared facts" lines formatted `- {actor} / {dimension}: {claim}[ [contested|unknown; not established fact]] [sources=...; as-of=...]`.
  - It adds lines greedily while the total stays ≤ `max_chars` (lines that do not fit are skipped, not truncated). It returns "" when no fact line fits.
- **`_resolve_output_language(research_language, requirement)` (`:1779-1794`), static.**
  - "en*" → "English"; "zh*", "chinese*" or text containing "中文" → "Chinese".
  - Otherwise it counts CJK characters versus Latin letters in the requirement: `cjk*3 >= latin` → Chinese, else English, and "" if there are none of either.
- **`_english_output()` (`:1796-1798`).** True iff `_output_language == "English"`.
- **`_build_market_pricing_block(markets)` (`:1800-1841`).**
  - Sorts by (`relevance_score`, `volume`) descending; non-numeric values count as -1.
  - Emits up to 5 lines: `- "<question[:160]>": NN%` in English, or `- 「…」：NN%` in Chinese. Rows without a question or a numeric `implied_yes_prob` are skipped.
  - The header says these are "calibration priors, not ground truth". Returns "" if no line is emitted.
- **`_build_world_brief(requirement, actors, hot_topics, markets, packs)` (`:1843-1915`).**
  - Returns "" if `Config.SIM_WORLD_BRIEF` is falsy (`:1872-1874`).
  - Canonical v1: `_build_canonical_public_world_brief(...)` only. Hot topics and markets are ignored (`:1877-1884`).
  - Legacy: these parts are joined with blank lines:
    1. question `[:400]`;
    2. `situation_brief_block(actors, english=...)`, with exceptions swallowed;
    3. `## Hot topics` (up to 8, joined with "; " or "、");
    4. the market block, if enabled.
  - The result is truncated to `_world_brief_max_chars()` (`:1915`).
- **`_world_brief_max_chars()` (`:1917-1937`).**
  - Returns 1400 if `Config.ADAPTIVE_CONTEXT` is false.
  - Otherwise it calls `token_budget.slice_budget_chars(window=Config.context_window_for(provider), reserved=RESERVED_COMPLETION_TOKENS (8192), floor=1400, share=0.05, num_items=1)` and clamps the result to [1400, `SIM_WORLD_BRIEF_MAX_CHARS` (3000)].
  - Any exception returns 1400.

### `_build_context(requirement, document_text, entities, actors, packs)` (`:1939-2038`)
- **Requirement block (`:1952-1956`).** `delimit_untrusted_research_text("simulation requirement", requirement, max_chars=4000)` wraps it in `BEGIN/END UNTRUSTED RESEARCH DATA` markers (`backend/app/services/actor_role_prompt.py:259`).
- **Canonical v1 (`:1958-1972`).** Returns `"## 模拟需求\n<req>"` plus `_build_canonical_public_world_brief("", ..., 10_000)`. There is no graph summary, report or digest.
- **Legacy (`:1977-2038`).**
  1. `## 模拟需求` (requirement).
  2. `## 局势简报`: `situation_brief_block` delimited at 6,000 characters, inserted at index 1.
  3. `## 实体信息 (N个)`: `_summarize_entities` delimited at 10,000 characters.
  4. `## 深度研究档案`: `actors_digest(actors)` (default 4,000 characters, `backend/app/utils/actors.py:598`) delimited at 10,000.
  5. `## 预测输入`: `forecast_inputs_block(actors)` delimited at 8,000.
  6. `## 原始文档内容`: the report, sanitized to `remaining = 50000 - len(parts) - 500` characters, suffixed with `...(文档已截断)` when longer, and delimited (`:2020-2036`).

### `_summarize_entities(entities)` (`:2040-2077`)
Groups entities by `get_entity_type() or "Unknown"`. For each type it lists up to 20 entities as `- name: summary[:300]...`, with every value sanitized. It adds `... 还有 N 个` when a type has more than 20.

### LLM call and JSON repair (`:2079-2170`)
- **`_call_llm_with_retry(prompt, system_prompt)` (`:2079-2118`).**
  - Makes up to 3 attempts: `self.llm.chat(messages=[system, user], response_format={"type": "json_object"}, temperature=0.7 - attempt*0.1)`. `max_tokens` is not passed, so `LLMClient`'s default of 4096 applies (`backend/app/utils/llm_client.py:403`).
  - On a JSON parse failure it tries `_try_fix_config_json`; if that fails it retries immediately, without sleeping.
  - On any chat exception it sleeps `2*(attempt+1)` seconds (2, 4, 6; the 6 s happens even after the last attempt) and retries.
  - Finally it raises `last_error`.
  - Each `chat` call has its own 3-attempt exponential backoff plus an optional fallback provider (`backend/app/utils/llm_client.py:44`, `:455-505`). The worst case is therefore 9 primary-provider requests per logical call.
- **`_fix_truncated_json(content)` (`:2120-2136`).** If the last character is not one of `",}]` it appends `"`. It then appends `]` × (open `[` count) and `}` × (open `{` count). The counts are naive and include braces inside strings, and arrays are closed before objects.
- **`_try_fix_config_json(content)` (`:2138-2170`).** Runs the truncation fix, takes the regex `\{[\s\S]*\}` match, and collapses newlines and whitespace inside string literals before parsing. If that fails, it replaces control characters with spaces and retries; otherwise it returns None.

### Time config (`:2172-2307`)
- **`_generate_time_config(context, n)` (`:2172-2229`).**
  - Chinese prompt over `context[:10000]`. It includes the profile's `time_prompt_principles` and a sample JSON (72 h, 60 min, 5/50 agents, the profile's hour lists, reasoning).
  - Documented field ranges: hours 24-168, minutes per round 30-120, agents per hour 1..`max(1, int(n*0.9))`.
  - System prompt = `profile["time_system_prompt"]`.
  - On exception it returns `_get_default_time_config(n)`.
- **`_get_default_time_config(n)` (`:2231-2245`).** 72 h, 60 min, min `max(1, n//15)`, max `max(5, n//5)`, the profile's hour lists, and the profile's `default_time_reasoning`.
- **`_coerce_int(value, default)` (`:2247-2253`).** `int(float(value))`; TypeError or ValueError returns the default.
- **`_parse_time_config(result, n)` (`:2255-2307`).**
  - Clamps hours to [24, 168] and minutes per round to [30, 120], warning on each change (PREP-9).
  - Coerces the agents-per-hour values. A min above `n` becomes `max(1, n//10)`; a max above `n` becomes `max(min+1, n//2)`; if min ≥ max then min becomes `max(1, max//2)`.
  - Hour lists pass through from the LLM unvalidated, defaulting to the profile's.
  - Multipliers are **hard-coded** to 0.05/0.4/0.7/1.5, whatever the profile.

### Event config (`:2309-2638`)
- **`_generate_event_config(context, requirement, entities, actors, packs)` (`:2309-2485`).**
  - **Type examples.** Canonical v1 uses `{"Actor": [validated pack actor_names]}`; each pack is validated and dossier-bound, and failures raise (`:2325-2341`). Legacy uses up to 3 graph names per entity type (`:2343-2348`). The result is sanitized and delimited at 6,000 characters.
  - **Context.** `context[:8000]`.
  - **Digest.** Canonical: the public brief at 2,500 characters. Legacy: `actors_digest(actors, max_chars=2500)`. The digest is delimited, and a poster-name hint is added (canonical: "only public, source-bound evidence"; legacy: "prefer real dossier actors").
  - **Fault lines (legacy only, `:2400-2425`).** Up to 6 `situation_brief.fault_lines`; the prompt requires at least one initial post per fault line.
  - **Prompt (`:2432-2460`).** Asks for `{hot_topics[], narrative_direction, initial_posts[{content, poster_type, poster_name?}], reasoning}`.
  - **Language suffix (`:2463-2472`).** An English or Chinese output-language instruction is appended.
  - **System prompt (`:2474`).** "你是舆论分析专家。返回纯JSON格式。注意 poster_type 必须精确匹配可用实体类型。"
  - **Fallback.** On exception it returns an empty config with reasoning "使用默认配置" (`:2476-2485`).
- **`_parse_event_config(result, actors, packs)` (`:2487-2530`).**
  - `hot_topics` comes from the LLM. If it is empty, the dossier is legacy and `actors["hot_topics"]` is a list, the first 12 dossier topics are used instead.
  - Sets `self._run_hot_topics` to the first 8 non-empty topics (`:2504`).
  - If there are no initial posts and `SIM_SYNTH_SEED_POSTS` is on (default), it calls `_synthesize_initial_posts`; exceptions produce `[]`.
  - Returns an `EventConfig` with `scheduled_events = []`.
- **`_synthesize_initial_posts(actors, hot_topics, packs)` (`:2532-2638`).**
  - Canonical v1 (`:2547-2581`): one post per distinct actor from `_canonical_public_world_rows`, containing `"{topic}: {claim}"` (contested/unknown claims get a marker), with `poster_type="Actor"`. Capped by `SIM_SYNTH_SEED_POSTS_MAX` (10).
  - Legacy (`:2584-2638`):
    - Candidates are actors that have a name and a stance, sorted by influence (high, then medium, then low) and then `simulation_tier`.
    - The first `max_posts` get a topic in round-robin.
    - Templates: if `SIM_SEED_POST_VARIANTS` is true, posts alternate between a "position" template and a "who gains / who loses?" template. The Chinese wording is used iff the active profile **is** `china_social` (`:2612`). If the flag is false, a single English template is used.
    - Content is capped at 600 characters, and `poster_type` = actor type or "Organization".

### `_assign_initial_post_agents(event_config, agent_configs)` (`:2640-2750`)
- **Indexes.** Agents are indexed by lowercase entity_type and by normalized name (the latter is a dict comprehension, so the last duplicate wins, `:2678-2682`).
- **Match order for each post.**
  0. `poster_name`: exact normalized match, else two-way substring containment with names of at least 2 characters (`:2693-2705`).
  1. A direct type match, rotating through agents of that type via `used_indices` (`:2708-2712`).
  2. The `type_aliases` table, which covers official, university, mediaoutlet, student, professor, alumni, organization and person (`:2662-2671`, `:2715-2726`).
  3. The highest-influence agent, or `0` if there are no agents (`:2729-2736`).
- **Output.** The post is rewritten as `{content, poster_type, poster_agent_id[, poster_name]}`.

### `_generate_agent_configs_batch(context, entities, start_idx, requirement, actors, packs)` (`:2752-3139`)
- **Roster build (`:2769-2870`).** `agent_id = start_idx + i`, and `match_actor(e.name, actors)` finds the dossier actor.
  - **Canonical run.** Every row starts as `{"agent_id", "entity_name": "Unbound Actor <id>", "entity_type": "Actor"}`, and every id is added to `canonical_agent_ids` (`:2779-2790`).
  - **Legacy.** Rows are `{agent_id, entity_name, entity_type, summary[:300]}`, sanitized.
  - **Canonical matched actor.**
    - The pack is validated, which can raise.
    - `projection = _actor_context_config_projection(pack)`.
    - The dossier binding is validated.
    - The runtime name comes from the projection or the pack's `actor_name`; it raises if empty (`:2827-2838`).
    - It raises if no projection could be built (`:2839-2842`).
  - **Legacy matched actor.** Adds a `researched_profile{role, stance, influence, memory}` (sanitized; `:2843-2865`). If a pack exists for that actor id, an `actor_context` behavior projection is added too.
- **Research rule text (`:2872-2894`).**
  - Legacy: researched values must drive stance, sentiment and influence (high ≈ 2.5-3.0, medium ≈ 1.5-2.0, low ≈ 0.8-1.2).
  - Canonical: derive only from documented rows and never reread flat fields.
- **Prompt (`:2897-2953`).**
  - The rhythm line is removed in calendar mode (`:2903-2906`).
  - The requirement is delimited at 8,000 characters and the roster JSON (`indent=2`) at **24,000** characters (`:2908-2917`).
  - Stereotype guidance: officials, media, individuals and experts (`:2930-2933`).
  - Requested output: `agent_configs[{agent_id, activity_level, posts_per_hour, comments_per_hour, active_hours, response_delay_min/max, sentiment_bias, stance, influence_weight, interested_topics}]`.
  - System prompt = `profile["agent_system_prompt"]`.
- **LLM call (legacy only, `:2960-2979`).** `llm_configs[int(agent_id)] = cfg`; ids that cannot be cast are skipped (F-5-2). An exception empties both maps.
- **Stats (`:2981-2984`).** The batch counts as an `llm_batches` batch if `llm_configs` or `raw_cfgs` is non-empty, otherwise as a `rule_batches` batch.
- **Per entity (`:2989-3137`).**
  - **Config source.**
    - Canonical: `_generate_canonical_agent_config_by_rule(behavior projection)` (`:3006-3014`).
    - Legacy: look up `llm_configs[agent_id]`; on a miss, use **positional** `raw_cfgs[i]` (`:2996-3003`); otherwise `_generate_agent_config_by_rule(entity)`, overriding influence with the research weight.
  - **Object.** Builds `AgentActivityConfig`. Missing keys fall back to `cfg.get` defaults: activity 0.5, posts 0.5, comments 1.0, active hours 9..22, delays 5/60, sentiment 0, neutral, influence 1.0. `interested_topics` keeps the first 5 from `cfg`, or `_default_interested_topics(entity)` for legacy (`:3027-3052`).
  - **T3.6 (legacy).** The research influence weight (high 2.5, medium 1.5, low 1.0; `backend/app/utils/actors.py:134-142`) **always overrides** the LLM weight (`:3055-3058`). [verifier: only when `influence_weight(actor)` returns non-None; a missing or unrecognized `influence` string returns None and the LLM value stands. Matching is first-substring in dict order (high/高, medium/med/中, low/低), so e.g. "medium-high" → 2.5 (`:3056-3058`, `backend/app/utils/actors.py:495-505`)]
  - **Incentives.** `gains_if`/`loses_if` come from `_extract_actor_incentive_summary` (`:3061-3068`).
  - **Projection side effects.** If a projection exists (`:3069-3111`):
    - `actor_context_digest` = compact sorted JSON of the behavior projection;
    - the gap audit is copied;
    - `actor_context_urgency` is set;
    - projection topics are merged ahead of the existing topics (deduped case-insensitively, max 5);
    - if urgency is `active` or `near_term`: `activity_level = max(·, 0.4)` and `response_delay_max = min(·, 120)`.
  - **C5 nudge (`:3115-3120`).** When valence is active, `sentiment_bias` is shifted by the relation nudge and clamped to [-1, 1].
  - **PREP-2 (`:3125-3136`).** Applies when `SIM_RULE_FALLBACK_STANCE` is on (default), the actor is legacy and matched, and the config came from rules or is neutral. `_classify_stance(actor.stance)` then overrides the stance, and a zero sentiment is seeded to ±0.3 for supportive/opposing.

### Topic and incentive helpers (`:3141-3229`)
- **`_RULE_INTERESTED_TOPICS` (`:3143-3153`)** maps entity types to topics: university, governmentagency, ngo and official → "Public Affairs"; mediaoutlet → "General News"; professor and expert → "Academic"; student and alumni → "Education".
- **`_default_interested_topics(entity)` (`:3155-3178`).**
  - The primary topic is the type topic. If there is none, it is `hot[sum(ord(name)) % len(hot)]`; if there are no hot topics, "Public Opinion".
  - Up to 2 run hot topics are then appended.
- **`_extract_actor_incentive_summary(actor, canonical_projection)` (`:3180-3229`).**
  - Canonical actors require a projection with `schema_version == "actor-config-context/v1"`, or it raises. Their incentives are taken from `decision_incentives`.
  - Legacy actors use the first 4 `incentives[]`.
  - The unique values are joined with "；".

### Actor-context projection (`:3231-3673`)
- **Vocabularies.** `_ACTOR_CONTEXT_EVIDENCE_TYPES` (`:3231-3234`) and the qualifier allow-list `_ACTOR_CONTEXT_QUALIFIERS` (`:3235-3241`).
- **`_safe_actor_context_scalar(value, max_chars=320)` (`:3243-3258`).** Bool, None and int pass through. Finite floats pass through and non-finite floats become None. Containers become JSON strings, or a placeholder if they cannot be serialized. Everything else goes through `sanitize_untrusted_dossier_text`.
- **`_safe_actor_context_list` (`:3260-3271`).** Bounded list of sanitized scalars.
- **`_actor_context_claim_rows(pack, dimensions)` (`:3273-3349`).**
  - Raises on a non-v1 intelligence `schema_version`.
  - For v1 it requires non-empty `source_refs`. Unknown evidence types are coerced to "unknown".
  - It copies these fields, sanitized and bounded where applicable: `as_of_date`, `horizon`, `status`, `confidence`, `visibility`, `actor_knows`, `source_refs` (8), `dependencies`/`contradictions` (6), and allow-listed qualifiers.
- **`_safe_actor_context_relationship(row)` (`:3351-3373`).** Allow-listed and bounded relationship fields.
- **`_actor_context_behavior_projection(projection)` (`:3375-3392`).** Removes the gap-audit key.
- **`_actor_context_config_projection(pack, max_chars=1800)` (`:3394-3620`).**
  - **Rows.** Claims come from 8 priority dimensions: current_actions, future_plans, investments_capital_allocation, capabilities, decision_rights_process_triggers, incentives, motivations, constraints. They are split into documented, inference and contested.
  - **Skeleton.** `schema_version: "actor-config-context/v1"`, ids, and the source hashes (`:3430-3452`).
  - **Fill order, each step gated by the JSON size staying ≤ 1800.**
    1. `decision_incentives`, up to 4, from documented incentives qualifiers (`:3458-3481`).
    2. `documented` (14), `analyst_inference_not_actor_knowledge` (5), `contested_not_actor_knowledge` (5).
    3. Hard-public relationships (8).
    4. `report_section_headings`.
  - **Urgency (`:3528-3541`).** "active" if current_actions is documented. Otherwise "near_term" or "strategic" if future_plans or decision triggers are documented; near_term requires a token such as "now", "immediate", "near-term", "next 90", "本月", "近期" or "立即". Otherwise "baseline".
  - **Policy text.** `epistemic_policy` is added.
  - **Trim.** Whole items are popped (headings, then relationships, then contested, then inference, then documented) until the JSON is ≤ 1800. If it still exceeds the budget, a ValueError is raised (`:3550-3577`).
  - **Gap audit.** `normalize_evidence_gap_map(evidence_gaps, require_lossless=v1)` produces a sealed audit payload `{schema_version, actor_id, sha, evidence_gaps, canonical_bytes, max_bytes, sha256}`. A ValueError is raised if it exceeds 65,536 bytes (`:3579-3619`).
- **`_actor_context_topics(projection)` (`:3622-3648`).** Takes qualifier topics (project, program, product, asset, strategic_purpose), action/plan/investment claim prefixes (100 characters) and section headings. Returns at most 3 unique values.
- **`_generate_canonical_agent_config_by_rule(projection)` (`:3650-3673`).** Activity 0.5, posts 0.5, comments 1.0, active hours 9..22, delays 5/60, sentiment 0, neutral, influence 1.0, topics from the projection.

### `_generate_agent_config_by_rule(entity)` (`:3675-3796`)
A type table; topics come from `_default_interested_topics`.

| Entity types | Anchors | Activity | Posts/h | Influence | Stance | Active hours |
|---|---|---|---|---|---|---|
| university, governmentagency, ngo, government, country | `:3684-3697` | 0.2 | 0.1 | 3.0 | neutral | 9-17 |
| mediaoutlet | `:3698-3711` | 0.5 | — | 2.5 | observer | 7-23 |
| professor, expert, official | `:3712-3725` | 0.4 | — | 2.0 | — | — |
| student | `:3726-3739` | 0.8 | — | 0.8 | — | — |
| alumni | `:3740-3753` | 0.6 | — | 1.0 | — | — |
| organization, company | `:3754-3767` | 0.35 | — | 2.0 | — | — |
| strategicasset, policyinstrument, marketsignal, concept | `:3768-3782` | 0.15 | — | 1.2 | observer | — |
| anything else ("ordinary person") | `:3783-3796` | 0.7 | 0.5 | 1.0 | — | — |

### Audience ("silent majority") generation (`:3798-4006`)
- **Constants.** `AUDIENCE_ENTITY_TYPE = "Audience"` (`:3803`), stance buckets (`:3807`), and the zh/en `_STANCE_KEYWORDS` substring table (`:3810-3814`).
- **`_build_audience_rng()` (`:3816-3832`).** Reads the `SIM_SEED` environment variable, else `Config.SIM_SEED`. A non-zero integer seed gives `random.Random(seed ^ 0x41554449)`; otherwise an unseeded Random is used.
- **`_audience_stance_distribution(actors, main_configs)` (`:3834-3870`).** Classifies each actor's stance into buckets and normalizes the counts. Canonical actors use their already-generated main-config stance (neutral when missing). With no actors the distribution is uniform.
- **`_classify_stance(raw)` (`:3872-3881`).** First substring hit in the order supportive, opposing, observer; otherwise neutral.
- **`_sample_audience_stance` (`:3883-3891`).** Weighted `rng.choices`, uniform if all weights are zero.
- **`_generate_audience_agent_configs(start_idx, event_config, actors, main_configs, packs)` (`:3893-4006`).**
  - **Size.** `Config.SIM_AUDIENCE_AGENTS`, else the `SIM_AUDIENCE_SIZE` attribute. A size ≤ 0 returns `[]`; otherwise the size is capped at 5000.
  - **Active cap.** `SIM_AUDIENCE_ACTIVE_CAP` is read and only logged.
  - **Per agent.**
    - Stance is sampled from the distribution.
    - Uniform draws: activity in [0.2, 0.6], influence in [0.3, 0.8], posts in [0.02, 0.15], comments in [0.1, 0.5].
    - Sentiment depends on stance: [0.1, 0.6] supportive, [-0.6, -0.1] opposing, [-0.2, 0.2] otherwise, plus the C5 nudge. The nudge is effectively 0 because the name `公众_k` never appears in relationships.
    - `active_hours` is a sorted sample of 5-11 hours from {9..13, 18..23}.
    - Topics: 1-2 hot topics.
    - Delays: min in [5, 30], max in [60, 240].
    - Identity: `entity_uuid = "audience:<id>"`, `entity_name = "公众_<k>"`.

---

## Control flow

```
SimulationManager.prepare_simulation (simulation_manager.py:862)
  └─ SimulationConfigGenerator() (:435) ── LLMClient
  └─ generate_config (:455)
       ├─ _resolve_output_language (:1779)
       ├─ _build_context (:1939) ── _summarize_entities (:2040) | canonical: _build_canonical_public_world_brief (:1734)
       ├─ [calendar] _build_temporal_timeline (:936) ── sim_timeline.extract_horizon → _llm_extract_horizon (:992, LLM) → default_horizon → build_timeline
       ├─ step 1: [calendar] _get_default_time_config (:2231) → _parse_time_config (:2255) + shim
       │          [hours]    _generate_time_config (:2172, LLM) → _parse_time_config
       ├─ step 2: _generate_event_config (:2309, LLM) → _parse_event_config (:2487) → (empty posts) _synthesize_initial_posts (:2532)
       ├─ _load_prediction_markets (:1350) → _build_world_brief (:1843) → _build_market_pricing_block (:1800), _world_brief_max_chars (:1917)
       ├─ steps 3..N: _generate_agent_configs_batch (:2752) ×ceil(N/15)  [LLM only for legacy]
       │     ├─ match_actor, _validated_canonical_context_pack (:1410), _actor_context_config_projection (:3394)
       │     ├─ _call_llm_with_retry (:2079) → _try_fix_config_json (:2138) → _fix_truncated_json (:2120)
       │     ├─ _generate_agent_config_by_rule (:3675) | _generate_canonical_agent_config_by_rule (:3650)
       │     ├─ _extract_actor_incentive_summary (:3180), _actor_context_topics (:3622)
       │     └─ _valence_signal_active (:1138) → _relation_sentiment_nudge (:1179); _classify_stance (:3872)
       ├─ _assign_initial_post_agents (:2640)
       ├─ _generate_audience_agent_configs (:3893)
       ├─ _assign_cadence_tiers (:904)
       ├─ _build_initial_follows (:817)
       ├─ _build_scheduled_events (:1028)   (mutates timeline.beyond_horizon_events / warnings)
       ├─ _build_echo_chamber_follows (:1226) → merged into initial_follows (:746-749)
       └─ PlatformConfig ×2 (:760-778) → SimulationParameters (:781)
  └─ (caller) audience personas appended, write_text_atomic(simulation_config.json) (simulation_manager.py:1188-1226), seal (:1281)
```

Ordering dependencies:
- `_parse_event_config` must run before the agent batches, because it sets `_run_hot_topics`, which `_default_interested_topics` reads (`:2504`, `:3166`).
- `_temporal_timeline` must be set before the batches, so the batch prompt can drop the rhythm line (`:569`, `:2903`).
- Initial posts are assigned before the audience is appended, so audience agents never author seed posts (`:668` vs `:688`).
- Cadence, follows, scheduled events and echo-chamber edges all see the audience agents.

---

## Data & artifacts

**Files read by the slice**
- `PipelineManager.list_pipelines()` and `PipelineManager.load(pid)` read every `Config.PIPELINE_DATA_DIR/<pid>` state file (`backend/app/services/pipeline_orchestrator.py:1204-1215`, `:1136`), triggered from `:1365-1369`.
- `<handoff_dir>/prediction_markets.json`, from the first pipeline whose `simulation_id` matches (`:1372-1378`). The handoff directory comes from the stored `handoff_dir` or `uploads/pipelines/<pid>/handoff` (`backend/app/services/pipeline_orchestrator.py:884-885`). Fields used: `markets[].question`, `implied_yes_prob`, `relevance_score` and `volume`.

**Files written.** None directly. The caller writes `OASIS_SIMULATION_DATA_DIR/<sim_id>/simulation_config.json` (`backend/app/services/simulation_manager.py:1224-1226`).

**Output schema** (`SimulationParameters.to_dict`, `:373-403`):
- `simulation_id`, `project_id`, `graph_id`, `simulation_requirement`, `as_of_date` (raw dossier string or null).
- `time_config`: `total_simulation_hours`, `minutes_per_round`, `agents_per_hour_min`, `agents_per_hour_max`, `peak_hours`, `peak_activity_multiplier`, `off_peak_hours`, `off_peak_activity_multiplier`, `morning_hours`, `morning_activity_multiplier`, `work_hours`, `work_activity_multiplier`. In calendar mode, `total_simulation_hours` = `n_rounds` and `minutes_per_round` = 60.
- `agent_configs[]`: all `AgentActivityConfig` fields (`:193-247`). Named agents come first, then audience agents. `agent_id`s are contiguous from 0, matching the profile array index.
- `event_config`:
  - `initial_posts[{content, poster_type, poster_agent_id, poster_name?}]`;
  - `scheduled_events[{round, content, date, poster_agent_id, poster_name}]`;
  - `hot_topics[]`, `narrative_direction`;
  - `initial_follows[[follower, followee]]`, sorted and deduped.
- `twitter_config` / `reddit_config`: `{platform, recency_weight, popularity_weight, relevance_weight, viral_threshold, echo_chamber_strength, recsys_type, refresh_rec_post_count, max_rec_post_len}`, or null.
- `llm_provider`, `llm_model`, `llm_base_url`, `generated_at`, `generation_reasoning`.
- Optional:
  - `world_brief`;
  - `temporal_config` = `asdict(SimulationTimeline)`: `{schema_version: 1, mode: "calendar", as_of_date, horizon_date, horizon_source, horizon_text, horizon_defaulted, unit, unit_stride, n_rounds, round_dates[{round, period_start, period_end, label}], span_days, target_max_rounds, round_cap_coarsened, beyond_horizon_events, warnings}` (`backend/app/utils/sim_timeline.py:73-90`);
  - `output_language`.

**Input shape: dossier fields consumed from `actors.json`**
- `as_of_date`, `central_question`;
- `actors[]`: name, type, role, stance, influence, memory, incentives, simulation_tier, intelligence, aliases;
- `relationships[]`, `key_events[]`, `hot_topics[]`;
- `situation_brief`: current_situation, context, dynamics, fault_lines, catalysts;
- `forecast_inputs` (via `forecast_inputs_block`);
- `actor_intelligence_contract`.

**Input shape: actor-context packs.** A dict keyed by `actor_id_for(actor)`, each value an `actor-context/v1` pack with `{schema_version, actor_id, actor_name, actor_intelligence, source{actor_intelligence_contract_version, actor_intelligence_sha256, actors_sha256, ...}, relationships, events, relevant_sections}`.

**Key in-memory structures**
- The `context` string, shared by every LLM call and truncated to 10,000 / 8,000 characters per step.
- `matched_actors`, `context_projections` and `canonical_agent_ids` for each batch (`:2771-2775`).
- `reasoning_parts` (`:542`).

---

## Config / env knobs

| Knob | Default | Effect | Anchor |
|---|---|---|---|
| `LLM_PROVIDER` / `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | claude-cli / none / provider default / provider default | LLMClient construction. Provider, model and base URL are echoed into the config. | `:442-453`, `backend/app/config.py:750-798` |
| `SIM_TEMPORAL_MODE` | `calendar` (Config); `getattr` fallback "hours" | "calendar" builds `temporal_config`; anything else uses the hours path | `:552`, `backend/app/config.py:1067` |
| `SIM_CALENDAR_TARGET_MAX_ROUNDS` | 36 | Soft round budget for unit selection, and the reference for `round_cap_coarsened` | `:971`, `:985`, `backend/app/config.py:1069` |
| `SIM_CALENDAR_HARD_MAX_ROUNDS` | 48 | Ceiling for anti-alias refinement | `:986`, `backend/app/config.py:1071` |
| `SIM_HORIZON_DEFAULT_MONTHS` | 12 | Last-resort horizon | `:967-969`, `backend/app/config.py:1073` |
| `OASIS_DEFAULT_MAX_ROUNDS` | 36 | Caps calendar `target_max`; hours schedule budget when `SIM_SCHEDULE_CLAMP_ROUNDS` is on | `:977-979`, `:1101`, `backend/app/config.py:1063` |
| `SIM_SCHEDULE_CLAMP_ROUNDS` | true | Hours mode: clamps the event-schedule domain to `OASIS_DEFAULT_MAX_ROUNDS` when no `max_rounds` is given | `:1100`, `backend/app/config.py:563` |
| `SIM_EVENT_REACT_BUFFER` (indirect) | true | Hours mode: compresses event placement to leave reaction rounds | `backend/app/utils/actors.py:1436-1443`, `backend/app/config.py:562` |
| `SIM_ACTIVITY_PROFILE` | `china_social` | Rhythm prompts, default hour lists, seed-post template language. If the env var is empty and research_language is English, `global_market` is used. | `:188`, `:511`, `backend/app/config.py:1378` |
| `SIM_VALENCED_RELATIONS` | true | Enables the C5 valence echo edges and sentiment nudge (only when the dossier carries valence signals) | `:1152`, `backend/app/config.py:1519` |
| `SIM_MARKET_PRIORS` | true | Loads `prediction_markets.json` and adds the market block to the legacy world brief | `:1347`, `backend/app/config.py:1419` |
| `SIM_WORLD_BRIEF` | true | Off produces an empty `world_brief`, and the field is omitted | `:1872`, `backend/app/config.py:1409` |
| `ADAPTIVE_CONTEXT` | true | Budgets the world-brief cap between 1400 and 3000 | `:1921`, `backend/app/config.py:118` |
| `SIM_WORLD_BRIEF_MAX_CHARS` | 3000 | World-brief ceiling | `:1923`, `backend/app/config.py:128` |
| `RESERVED_COMPLETION_TOKENS` | 8192 | Subtracted from the window in the brief budget | `:1930`, `backend/app/config.py:120` |
| `DEFAULT_CONTEXT_WINDOW` / `PROVIDER_CONTEXT_WINDOWS` | 32000 / per provider | Window for the brief budget | `:1927`, `backend/app/config.py:131-157` |
| `SIM_SYNTH_SEED_POSTS` | true | Synthesizes seed posts when the LLM returns none | `:2511`, `backend/app/config.py:1405` |
| `SIM_SYNTH_SEED_POSTS_MAX` | 10 | Maximum synthesized posts | `:2556`, `:2607`, `backend/app/config.py:1406` |
| `SIM_SEED_POST_VARIANTS` | true | Alternating zh/en statement-and-question templates; false gives the single English template | `:2611`, `backend/app/config.py:565` |
| `SIM_RULE_FALLBACK_STANCE` | true | PREP-2 dossier-stance override for rule or neutral configs | `:3125`, `backend/app/config.py:564` |
| `SIM_AUDIENCE_AGENTS` (env alias `SIM_AUDIENCE_SIZE`) | 0 | Number of audience agents (capped at 5000) | `:3915`, `backend/app/config.py:1372-1374` |
| `SIM_AUDIENCE_SIZE` (Config attribute) | not defined on Config | Fallback read; effectively always 0 | `:3921` |
| `SIM_AUDIENCE_ACTIVE_CAP` | not defined on Config | Read and logged only | `:3937-3941` |
| `SIM_SEED` (env first, then Config) | 0 | A non-zero seed makes audience sampling deterministic | `:3822-3832`, `backend/app/config.py:296` |

---

## External calls

- **LLM.** `self.llm.chat(...)` in `_call_llm_with_retry` (`:2090-2097`) is the only network or subprocess call in the slice. It reaches the configured provider: claude-cli or codex-cli subprocesses, or OpenAI-compatible HTTP (`backend/app/utils/llm_client.py:461-469`). Call sites:
  - `_llm_extract_horizon` (`:1014`);
  - `_generate_time_config` (`:2226`);
  - `_generate_event_config` (`:2477`);
  - `_generate_agent_configs_batch` (`:2964`).
- **Filesystem.** `PipelineManager.list_pipelines/load` and `open(prediction_markets.json)` (`:1365-1376`).
- **No DB, graph or Zep calls.** `ZepEntityReader` is imported but unused; `EntityNode` objects arrive already loaded.
- **Sleep.** `time.sleep(2*(attempt+1))` after an LLM exception (`:2115-2116`).

---

## Cross-module edges

**Callers**
- `backend/app/services/simulation_manager.py:21` (import) and `:1155-1178` (construct and `generate_config`). It reads `SimulationConfigGenerator.AUDIENCE_ENTITY_TYPE` to pick out audience configs for persona generation (`:1193-1220`), then serializes (`:1226`) and stores `generation_reasoning` (`:1229`).
- `backend/app/services/__init__.py:11-13`, `:52-53` re-export `SimulationConfigGenerator` and `SimulationParameters`.
- Indirect callers of `prepare_simulation`:
  - the pipeline main path (`backend/app/services/pipeline_orchestrator.py:12811-12821`), which passes actors, `max_rounds` (calendar mode: only an explicit user value) and `research_language`;
  - ensemble seed runs (`backend/app/services/pipeline_orchestrator.py:8790-8799`);
  - the REST endpoint `POST /api/simulation/prepare` (`backend/app/api/simulation.py:619-627`), which passes **no** actors, `max_rounds` or `research_language`.
- Tests that exercise the slice: `backend/tests/test_audit_fixes_prepare.py`, `test_sim_context_persona.py`, `test_sim_config_incentives.py`, `test_sim_reaction_phase.py`, `test_actor_cast_discipline.py`, `test_sessionb_sim_additivity.py`, `test_actor_context_runtime.py`, `test_sim_config_v1_provenance.py`, `test_temporal_mode_contract.py`, `test_calendar_event_bucketing.py`, `test_prompt_injection_boundaries.py`, `test_sim_market_priors.py`.

**Calls out to**
- `backend/app/utils/sim_timeline.py`: `extract_horizon` (`:266`), `default_horizon` (`:338`), `build_timeline` (`:518`), `_add_months`, `HorizonResult`, `SimulationTimeline`.
- `backend/app/utils/actors.py`: `normalize_name` (`:145`), `extract_actor_rows` (`:180`), `match_actor` (`:445`), `influence_weight` (`:495`), `actors_digest` (`:598`), `extract_relationship_rows` (`:737`), `situation_brief_block` (`:763`), `relation_valence` (`:1003`), `relation_polarity` (`:1018`), `build_initial_follow_graph` (`:1270`), `events_to_schedule` (`:1398`), `events_to_calendar_rounds` (`:1463`), `forecast_inputs_block` (`:2880`).
- `backend/app/utils/dates.py`: `parse_as_of`.
- `backend/app/services/actor_context.py`: constants (`:26`, `:28`, `:98`), `canonical_json_sha256` (`:396`), `is_hard_public_relationship` (`:415`), `actor_id_for` (`:447`), `normalize_evidence_gap_map` (`:241`).
- `backend/app/services/actor_role_prompt.py`: `sanitize_untrusted_dossier_text` (`:122`), `sanitize_untrusted_research_text` (`:133`), `delimit_untrusted_research_text` (`:259`).
- `backend/app/utils/token_budget.py`: `slice_budget_chars`, `clamp_chars` (lazy import, `:1925`).
- `backend/app/services/pipeline_orchestrator.py`: `PipelineManager` (lazy import, `:1364`).

**Downstream consumers of the output.** `backend/scripts/run_parallel_simulation.py` uses:
- `temporal_config` for presence-keyed calendar dispatch (`:4723-4729`) and `n_rounds` as authority, ignoring runtime `max_rounds` (`:2591-2622`);
- `world_brief` (`:643-654`);
- `cadence`, `initial_follows`, `scheduled_events`;
- `agent_configs[].activity_level`, `active_hours`, `influence_weight` (`:1812-1851`) and `interested_topics` (`:4245`);
- `time_config` multipliers and `agents_per_hour_max` (`:1762-1828`).

`pipeline_orchestrator.apply_scenario_overlay_to_config` (`:8353`, applied at `:12863`) mutates the written config afterwards.

---

## Invariants, gates, validation

- **Agent id contiguity.**
  - Named agents get `start_idx + i` per batch (`:2777`, `:2991`), and audience agents continue from `len(main)` (`:681`, `:3952`). Ids therefore match the profile array index that the caller appends in the same order (`backend/app/services/simulation_manager.py:1193-1220`).
  - Follow edges are filtered to valid ids (`:890-891`). Echo edges skip self-loops (`:1265`, `:1277`, `:1302`).
- **Calendar authority.**
  - `temporal_config.n_rounds == len(round_dates)` (`backend/app/utils/sim_timeline.py:563`).
  - The shim makes `total_simulation_hours*60/minutes_per_round == n_rounds` (`:581-582`).
  - Calendar events are placed by interval containment. Events after the horizon are archived in `beyond_horizon_events`, not scheduled (`:1071-1077`).
- **Time clamps.** Hours are clamped to [24, 168] and minutes per round to [30, 120] (`:2263`, `:2267`). `agents_per_hour_*` must be ≤ entity count and min < max (`:2281-2292`); this is only partially enforced (see Surprises).
- **Canonical v1 fail-closed gates.** These raise `ValueError` and abort config generation:
  - pack validation (`:1424-1463`);
  - dossier fingerprint (`:1487-1492`);
  - relationship and event rows that are not dossier-bound (`:1533-1536`, `:1629-1632`);
  - missing safe runtime name or projection (`:2832-2842`);
  - projection over budget (`:3573-3577`);
  - gap audit over 64 KiB (`:3608-3613`);
  - incentive summary without a projection (`:3193-3200`).
- **Canonical exclusion rules.**
  - Graph summaries and labels never enter prompts (`:1958-1972`, `:2325-2341`, `:2779-2790`).
  - Analyst inference never enters the public brief or seed posts (`:1707-1708`).
  - Only hard-public relationships shape follows (`:1540`).
  - `actor_local` rows add only edges whose follower is the owner (`:1588-1592`, `:1323-1331`).
- **Prompt-injection boundary for LLM prompts.** Every research-derived value in a prompt is sanitized and wrapped in `BEGIN/END UNTRUSTED RESEARCH DATA` (`:1952-2036`, `:2350-2431`, `:2908-2917`). [verifier: not every value. In canonical v1 the shared context appends the public brief raw, without delimiters (`:1967-1971`); it is sanitized only row by row (`:1698`, `:1721-1729`). Per-step slices `context[:10000]`/`context[:8000]` can also drop END markers (`:999`, `:2175`, `:2367`)]
- **Degradation contract.** Every optional enrichment is wrapped so that failure yields an empty value and the config is unchanged: world brief, audience, cadence, follows, scheduled events, echo edges, seed synthesis, temporal timeline (`:566`, `:626`, `:691`, `:702`, `:718`, `:733`, `:752`, `:2522`).
- **Research influence wins (T3.6).** A matched legacy actor's influence weight always overrides the LLM value (`:3055-3058`). [verifier: only when the dossier `influence` text parses to a weight; otherwise the LLM value is kept (`:3057`, `backend/app/utils/actors.py:495-505`)]

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| LLM exception or unparsable JSON (3 attempts) | Time config falls back to defaults; event config to an empty config; an agent batch to rule configs; the horizon to `default_horizon` | `:2227-2229`, `:2478-2485`, `:2976-2979`, `:1015-1017` |
| Truncated JSON | Bracket/quote closing heuristic, then regex extraction and whitespace/control-character cleanup | `:2120-2170` |
| Empty `initial_posts` | Synthesized from the dossier (`SIM_SYNTH_SEED_POSTS`) | `:2511-2524` |
| Unparseable `as_of_date` | Today is used, with warning `as_of_defaulted` | `:956-959`, `:988-989` |
| No deadline in the question | LLM fallback, then the 12-month default (`horizon_defaulted_12_months` warning in `build_timeline`) | `:963-969`, `backend/app/utils/sim_timeline.py:538-539` |
| Any exception while building the timeline | **The whole run silently reverts to hours mode** (warning log only) | `:566-568` |
| Event dates unparseable | Excluded, with warning `event_date_unparsed:<n>` | `:1079-1085` |
| Canonical pack or binding mismatch | Raises; `prepare_simulation` fails. Exception: when it happens inside the follows, scheduled-events or echo stages, those catch it and yield empty output. [verifier: the exception rarely applies. Pack and `actors_sha256` mismatches for any canonical actor that has a pack abort first in `_build_context` (`:534` → `:1967` → `:1685-1686`). A relationship row that is not dossier-bound aborts at the batch stage, because `_valence_signal_active` runs uncaught per batch (`:2989` → `:1156-1158` → `:1533-1536`) while `SIM_VALENCED_RELATIONS` is on. Only event-row binding failures are absorbed, by the scheduled-events stage (`:1058`, `:1629-1632`, `:733`)] | `:1410-1492`, `:718`, `:733`, `:752` |
| Duplicate normalized entity names | First wins in follows and echo; last wins in scheduled-event and initial-post routing; warning logged in follows | `:832-845`, `:1112-1114`, `:2678-2682` |
| `prediction_markets.json` missing or malformed | `[]`, debug log | `:1379-1382` |

---

## Surprises

1. **Dead constant.** `CHINA_TIMEZONE_CONFIG` (`:78-97`) is never referenced. The live values are in `ACTIVITY_PROFILES` and are hard-coded again in `TimeSimulationConfig` and `_parse_time_config`.
2. **Activity multipliers ignore the profile.** `_parse_time_config` hard-codes 0.05/0.4/0.7/1.5 for every profile (`:2301-2306`). The `global_market` prompt tells the LLM the off-peak value is 0.3 and the peak 1.2 (`:164-166`), and `us_business` describes work hours as the 1.5 peak (`:146`). The prompt text and the serialized multipliers disagree. [verifier: for `us_business` the 9-17 claim actually holds. Its default `peak_hours` are 9-17 (`:156`), and the runner checks peak first, so those hours get 1.5 (`backend/scripts/run_parallel_simulation.py:1752-1769`). The real `us_business` mismatch is `:147-148`: 12-14 and 19-22 are described as 0.7 but resolve to 1.5 and 1.0. The `global_market` mismatch (0.05 vs 0.3; 1.5 vs 1.2) stands]
3. **Suspected: small `max_rounds` increases the round count in calendar mode.** `target_max = min(36, max_rounds, ...)` (`:971-979`) feeds `select_calendar_unit`. When no unit gives 8 or more rounds within the cap, that function refines toward finer units up to `hard_max` = 48 (`backend/app/utils/sim_timeline.py:375-378`).
   - Reproduced offline with the pure module: a 12-month horizon with `max_rounds` = 5 or 10 gives `half_month` × **24** rounds, with warning `round_cap_coarsened` (from month to half_month, which is actually a refinement). With the default 36 it gives month × 12.
   - The runner ignores runtime `max_rounds` in calendar mode (`backend/scripts/run_parallel_simulation.py:2591-2622`), so a 5-round smoke test runs 24 rounds. This contradicts the docstring claim that the explicit cap only coarsens the granularity (`:950-952`).
4. **Suspected: positional fallback can assign another agent's config.** On an id miss, `raw_cfgs[i]` is used without checking its own `agent_id` (`:2996-3003`). If the LLM omits one agent mid-list, the following entries shift and agents receive their neighbors' configs (influence is then partly corrected only for matched legacy actors). [verifier: overstated. The lookup is id-first (`:2996`), so when one agent is omitted, only that agent falls back to `raw_cfgs[i]` and duplicates its neighbor's config. Every later agent still gets its own config by id. A whole-batch shift happens only when the ids themselves are systematically off (e.g. 1-based ids: agent k gets agent k-1's config through the id lookup)]
5. **Suspected: the agent roster prompt may be truncated.** The roster JSON (`indent=2`) is capped at 24,000 characters by the sanitizer, which cuts it with "…" (`:2913-2917`, `backend/app/services/actor_role_prompt.py:254-256`). Legacy rows can carry `researched_profile` (role and stance up to 500 characters each, memory 300) plus an `actor_context` projection of up to 1,800 compact characters, which is larger once pretty-printed. [verifier: the 1,800 budget is measured with default `json.dumps` separators (", ", ": "), not compact ones (`:3475-3477`, `:3557-3559`). The upper-bound arithmetic still supports the suspicion: a legacy row without a projection can reach about 2.3K characters (180+160+300+500+500+160+300 plus keys and indent, `:2792-2865`), so 15 rows can reach about 35K, above 24K] A full 15-agent batch can plausibly exceed 24,000, hiding the tail of the batch from the LLM. Not measured.
6. **Suspected: LLM-supplied agent fields are not type-checked or range-clamped.** `activity_level`, `influence_weight`, `sentiment_bias`, `active_hours` and others are copied as-is (`:3037-3052`). A string `influence_weight` would raise in `_assign_initial_post_agents`'s sort (`:2733`), which is **not** wrapped and would abort generation. [verifier: conditional. That sort runs only when a post matches no `poster_name`, type or alias (`:2729-2734`), and it raises only when string and number weights are mixed (all-string values sort silently). A second uncaught path exists: a non-numeric `sentiment_bias` plus a nonzero C5 nudge raises TypeError inside the batch (`:3115-3120`)] The same value in the cadence, echo or schedule stages is caught there and silently empties their output.
7. **Suspected: non-dict JSON is not guarded.** If the LLM returns a JSON array, `_parse_time_config` and `_parse_event_config` call `.get` on a list and raise `AttributeError`, which is uncaught in `generate_config` (`:588`, `:600`). In `_llm_extract_horizon` the same failure (`:1018`) is caught by the timeline wrapper and silently forces hours mode. A post whose `poster_type` is null would hit `None.lower()` at `:2686`.
8. **Suspected: negative `agents_per_hour_max` survives.** For example, max = -5 leads to min = `max(1, -5//2)` = 1, which leaves min > max (`:2285-2292`). Also, the `_coerce_int` docstring says "0/负数 … 回默认值", but the code returns 0 and negative numbers unchanged (`:2249-2253`).
9. **Inconsistent duplicate-name tie-breaking.** Follows and echo use first-wins (PREP-10, `:830-841`, `:1291`). Scheduled events and initial posts use last-wins dict comprehensions (`:1112-1114`, `:2678-2682`).
10. **Loose name matching.** Scheduled-event and initial-post routing accept names of at least 2 characters as substrings (`:1123`, `:2700`), while `match_actor` requires at least 4 characters for fuzzy matches (`backend/app/utils/actors.py:478-481`). Short names such as "us" or "eu" can match inside unrelated words in event text and misroute the poster. Event routing also takes the first match in insertion order, not the longest.
11. **Canonical v1 cohort is behaviorally flat.** All canonical agents get influence 1.0 and neutral stance (`:3662-3673`). So:
    - cadence "principal" goes to the first `max(4, ceil(n/2))` agents by **agent_id**, because all agents are eligible and tied (`:922-930`); [verifier: that holds only for 5 ≤ n ≤ 20. For n ≤ 4 every agent is principal (guard needs n > 4), and for n > 20 the budget stays 20, the first 20 by id (`:923-931`)]
    - the audience stance distribution is 100% neutral (`:3854-3860`); [verifier: only when every dossier actor row is canonical. Non-canonical rows in a canonical-run dossier still contribute their raw `stance` (`:3861-3862`)]
    - echo clusters are split only by topic.
    The batch stats also count every canonical batch as `rule_batches` and log the "LLM 失败退化为规则生成" warning even though no LLM call was attempted by design (`:2982-2984`, `:660-664`). The agent prompt is still built (`:2918-2955`) and thrown away.
12. **Legacy world brief is not sanitized.** Unlike `_build_context`, the legacy `_build_world_brief` concatenates the raw requirement, `situation_brief_block` (unsanitized, `backend/app/utils/actors.py:779-786`), LLM hot topics and market questions (`:1888-1909`). The runner injects the result into every agent's system prompt (`backend/scripts/run_parallel_simulation.py:643-654`). [verifier: `:643-654` is `_attest_canonical_reddit_system_messages`, the canonical-Reddit seal check. The general injection is `_inject_world_brief` (`backend/scripts/run_parallel_simulation.py:749-777`), called at `:4757-4761` and `:5299-5303`] Legacy seed posts (raw `stance`, `:2616-2632`) and legacy scheduled-event text (raw `key_events[].event`, `:1118`, `:1131`) are likewise unsanitized.
13. **Output language and activity profile are decoupled.**
    - The profile override needs `research_language` starting with "en" (`:509-512`). The orchestrator passes `None` for the default language and `""` for auto (`backend/app/services/pipeline_orchestrator.py:7955-7959`), so an English question in auto mode gets `output_language="English"` (detected from the text, `:1789-1794`) but the default `china_social` profile.
    - Legacy seed-post templates choose Chinese by profile identity, not by output language (`:2612`), so such runs can produce Chinese-connector seed posts in an English simulation.
    - The override also checks the **env var** rather than the Config attribute (`:511`).
14. **Unconsumed LLM outputs.** `posts_per_hour`, `comments_per_hour`, `response_delay_min/max` and `narrative_direction` are generated or requested but have no reader anywhere under `backend/app`, `backend/scripts` or `frontend/src` (grep). `actor_context_digest`, `actor_context_urgency` and `actor_context_evidence_gap_audit` are likewise only persisted. The PlatformConfig weights are display-only (`:316-319`), and the generator never sets the recsys knobs.
15. **Reddit echo strength is never used.** `_build_echo_chamber_follows` is always called with `twitter_config_strength=None`, so it uses 0.5 (`:741`, `:1247`). Reddit's 0.6 (`:777`) is never applied to follows.
16. **Market priors fail for ensemble seed runs (suspected).** `_load_prediction_markets` matches on `pipeline_state.simulation_id` (`:1370`), which holds only the main simulation. Seed simulations created in `_run_one_seed` (`backend/app/services/pipeline_orchestrator.py:8778-8799`) never match, so their world briefs lack the market block that the main run has. Each lookup also loads every pipeline state twice: once in `list_pipelines`, once in the loop.
17. **World-brief cap is effectively always 3000.** With `ADAPTIVE_CONTEXT` on (default), even the 32K default window gives (32000-8192)×0.05×4 ≈ 4761, which clamps to 3000. The comment saying small or unknown providers stay at 1400 (`:1911-1914`) never holds for the configured windows.
18. **Truncation cuts through trust delimiters.** Per-step prompt context is a raw slice of the delimited context (`context[:10000]` at `:2175`, `:999`; `context[:8000]` at `:2367`). It routinely ends inside a `BEGIN UNTRUSTED RESEARCH DATA` block without the matching END marker. In canonical mode the event prompt also includes the public brief twice: once in the context, once as the digest (`:1967-1971`, `:2371-2377`).
19. **`as_of_date` can diverge.** Top-level `as_of_date` is the raw dossier string (`:791`). `temporal_config.as_of_date` is the parsed value, or **today** when parsing fails (`:957`).
20. **Weak stance keyword classifier.** `_classify_stance` uses plain substring matching with supportive checked first (`:3810-3814`, `:3877-3880`). "unfavorable", "unsupportive" or "反对支持…" classify as supportive, and "report" matches observer.
21. **Minor dead or redundant code.**
    - `ZepEntityReader` is imported but unused (`:42`).
    - `_ACTOR_LOCAL_CONTEXT_VISIBILITIES` is never read (`:1469-1472`).
    - `import re` is repeated inside `_try_fix_config_json` (`:2140`), as is `import time` (`:2115`); `normalize_name` is re-imported inside `_assign_initial_post_agents` (`:2677`).
    - The `SIM_AUDIENCE_SIZE` attribute fallback is dead because Config never defines that attribute; the env alias is handled in `config.py:1372-1374`. `SIM_AUDIENCE_ACTIVE_CAP` is likewise undefined and log-only (`:3919-3941`).
    - The default-value sets disagree: `AgentActivityConfig` defaults (posts 1.0, comments 2.0, hours 8-22, `:205-209`) differ from the batch `cfg.get` defaults (0.5, 1.0, 9-22, `:3038-3040`).
22. **The last retry still sleeps.** After the third LLM exception it sleeps 6 s before raising (`:2112-2118`).
23. **Doc-vs-code drift.**
    - `ARCHITECTURE_MAP.md:263` and `DRF_ARCHITECTURE.md:840` cite `generate_config` at `:398`; it is at `:455`.
    - `DRF_ARCHITECTURE.md:860-861` says echo-chamber strength derives from "community structure from `communities.json`". The generator never reads communities; platform weights are constants (`:760-778`). [verifier: the quoted text is at `DRF_ARCHITECTURE.md:855` (and the table row at `:1409`), not `:860-861`]
    - `DRF_ARCHITECTURE.md:848-850` says scheduled events come from `events_to_schedule` and follows from `build_initial_follow_graph`. [verifier: these are at `DRF_ARCHITECTURE.md:847-848`] The default calendar mode uses `events_to_calendar_rounds` (`:1071`), and v1 dossiers use `_canonical_relationship_follow_pairs` (`:851-857`).
    - `ARCHITECTURE.md:256-258` says time config is "72 simulated hours … tuned to a Chinese daily rhythm". The default calendar mode skips the time LLM and derives rounds from the calendar (`:574-585`).
    - `ARCHITECTURE_MAP.md:267` estimates "one [LLM call] for simulation config". In fact there are 2 + ceil(N/15) logical calls for legacy dossiers, plus 1 for the horizon fallback. [verifier: that mixes the two modes. Calendar mode (default) skips the time LLM, giving 1 + ceil(N/15), plus 1 only when the deterministic horizon extraction fails (`:574-585`, `:964-965`). Hours mode gives 2 + ceil(N/15) and has no horizon call. Canonical v1 dossiers make 0 agent-config calls (`:2962`)]

---

## Verification

Adversarial verification pass, 2026-10-11, branch `main` (on-disk checkout). Every cited anchor was re-opened and read. Bare `:N` means `backend/app/services/simulation_config_generator.py:N`. Surprise 1 was reproduced offline with the pure `sim_timeline` module (no network, no bytecode written). A 2026-01-01 → 2027-01-01 horizon with `target_max` = 5 or 10 gives `half_month` × 24 rounds and `round_cap_coarsened` {month → half_month}. With 36 it gives `month` × 12.

**Verdict counts (31 verdicts).**
- Reader's 15 key claims: 14 confirmed, 1 imprecise (T3.6 "always overrides").
- Reader's 16 surprises: 11 confirmed, 5 imprecise. The imprecise ones are the positional-fallback shift, the type-check abort, the runner world-brief anchor, the flat-canonical principal budget, and the doc-drift LLM-call count.
- The 10 surprises that carry the "suspected" label were checked against code. Surprise 1 was also reproduced. 0 were refuted.
- Map spot-checks: about 45 Walkthrough and Control-flow statements were checked. 6 are imprecise and are annotated inline above; the rest are confirmed. The confirmed ones include:
  - the `simulation_manager` call anchors (`backend/app/services/simulation_manager.py:1155-1178`, `:1224-1226`);
  - the `to_dict` key order and omissions (`:373-403`);
  - `total_steps = 3 + num_batches` (`:522-523`);
  - the graph-neighbor edge direction (`:885-888`; edge shape at `backend/app/services/zep_entity_reader.py:452-466`);
  - echo `k = round(1.5) = 2` (`:1257`);
  - `_fix_truncated_json` (`:2120-2136`);
  - the `LLMClient` defaults: `max_tokens` 4096 and 3 inner retries (`backend/app/utils/llm_client.py:44`, `:403`, `:455-505`);
  - the rule table (`:3684-3796`);
  - `_resolve_output_language` (`:1780-1794`);
  - `n_rounds == len(round_dates)` (`backend/app/utils/sim_timeline.py:563`);
  - REST prepare passes no actors, `max_rounds` or language (`backend/app/api/simulation.py:619-627`);
  - the main path passes `max_rounds` only when the user set one in calendar mode (`backend/app/services/pipeline_orchestrator.py:12808-12821`);
  - the world-brief cap: (32000-8192) × 0.05 × 4 = 4761, clamped to 3000 (`backend/app/utils/token_budget.py:69-120`, `backend/app/config.py:131-157`).

**Non-confirmed items, with corrections**
1. *T3.6 (claim 6; Walkthrough and Invariants).* The research influence overrides the LLM weight only when `influence_weight(actor)` returns non-None. A missing or unrecognized `influence` string leaves the LLM value in place. Matching takes the first substring in dict order, so "medium-high" gives 2.5 (`:3056-3058`, `backend/app/utils/actors.py:134-142`, `:495-505`).
2. *Positional fallback (surprise 2 / map surprise 4).* The lookup is id-first (`:2996`). If the LLM omits one agent, only that agent takes `raw_cfgs[i]` (its neighbor's config, now duplicated); later agents still get their own config by id. A whole-batch misassignment needs systematically wrong ids, e.g. 1-based ids, which make agent k take agent k-1's config through the id lookup.
3. *Type checks (surprise 3 / map surprise 6).* The `_assign_initial_post_agents` sort runs only for posts that match no name, type or alias (`:2729-2734`). It raises only when string and number weights are mixed. There is another uncaught path: a non-numeric `sentiment_bias` plus a nonzero C5 nudge raises TypeError (`:3115-3120`). The `.get`-on-list, horizon-to-hours and `None.lower()` parts are confirmed (`:588-589`, `:600`, `:1018`, which is outside the try at `:1013-1017`, and `:2686`).
4. *Legacy world brief (surprise 5 / map surprise 12).* The content claims are confirmed. The runner anchor is wrong: `run_parallel_simulation.py:643-654` is the canonical-Reddit seal attestation. The general injection is `_inject_world_brief` (`backend/scripts/run_parallel_simulation.py:749-777`), called at `:4757-4761` and `:5299-5303`.
5. *Flat canonical cohort (surprise 8 / map surprise 11).* "First half by agent_id" holds only for 5 ≤ n ≤ 20. For n ≤ 4 every agent is principal; for n > 20 the first 20 by id are (`:923-931`). The audience is 100% neutral only when every dossier actor row is canonical (`:3853-3862`). The `rule_batches` accounting and the warning are confirmed (`:2984`, `:660-664`).
6. *Activity multipliers (surprise 9 / map surprise 2).* The `global_market` mismatch is confirmed. For `us_business`, the "9-17 at 1.5" text matches runtime: default `peak_hours` = 9-17 (`:156`), and the runner checks peak first (`backend/scripts/run_parallel_simulation.py:1752-1769`). The real mismatch is at `:147-148`: 12-14 resolve to 1.5 and 19-22 to 1.0, not 0.7. This is counted under surprise 9's confirmed verdict as a sub-point.
7. *Doc drift (surprise 15 / map surprise 23).*
   - The LLM-call count mixes modes. Calendar (default): 1 + ceil(N/15), plus 1 when deterministic horizon extraction fails. Hours: 2 + ceil(N/15). Canonical v1: no agent-config calls (`:574-585`, `:964-965`, `:2962`).
   - The `DRF_ARCHITECTURE.md` anchors are off. The communities.json text is at `:855` (and `:1409`); `events_to_schedule` and `build_initial_follow_graph` are at `:847-848`.
   - The `:398` → `:455` drift and the 72-hour / Chinese-rhythm drift (`ARCHITECTURE.md:256-257`) are confirmed.
8. *Map failure-mode row "canonical pack or binding mismatch".* Pack and `actors_sha256` mismatches abort first in `_build_context` (`:534` → `:1967` → `:1685-1686`). Relationship-binding failures abort at the batch stage through the uncaught `_valence_signal_active` call (`:2989` → `:1156-1158` → `:1533-1536`). Only event-binding failures are absorbed, by the scheduled-events stage (`:1058`, `:1629-1632`, `:733`).
9. *Map invariant "every research-derived value wrapped".* The canonical shared context appends the public brief without BEGIN/END delimiters (`:1967-1971`); it is sanitized only per row (`:1698`, `:1721-1729`).
10. *Map canonical event gate.* `evidence_type` uses a deny-list, so an empty or missing value passes as "behavioral" (`:1641-1647`).
11. *Map surprise 5 wording.* The 1,800-character projection budget is measured with default (non-compact) separators (`:3475-3477`, `:3557-3559`). The truncation suspicion still holds on upper-bound arithmetic.

**Notes on confirmed items**
- Claim 10's "3000 for every configured window" assumes the default env: `DEFAULT_CONTEXT_WINDOW` = 32000 and `RESERVED_COMPLETION_TOKENS` = 8192. A window below about 15.2K tokens would fall to 1400.
- For claim 11, the top 5 counts only rows with a question and a numeric probability (`:1822-1832`).
- For surprise 10, Reddit's `echo_chamber_strength` is read by the runner but only logged (`backend/scripts/run_parallel_simulation.py:2691`, `:2738`).
- For surprise 16, tests monkeypatch `Config.SIM_AUDIENCE_SIZE` (`backend/tests/test_actor_cast_discipline.py:492`, `:511`), so that fallback is exercised in tests, though it is dead in production.

**Omissions (significant behavior the map does not cover)**
1. **Legacy synthesized seed posts can come from actors outside the cast.** `_synthesize_initial_posts` draws candidates from every dossier `actors[]` row with a name and a stance, not from the selected agents (`:2584-2605`). A post for an actor that is not an agent keeps its `poster_name`. It is then routed by substring, type, alias or top influence to an unrelated agent, which publishes "our position: <other actor's stance>" (`:2692-2736`).
2. **Downstream use of the platform configs and `as_of_date`.** When `SIM_WIRE_RECSYS=true`, Twitter's `echo_chamber_strength` drives OASIS `following_post_count = round(2 + echo*4)`. Reddit's is only logged. The raw top-level `as_of_date` becomes Platform `start_time` through `fromisoformat(str[:10])`, so a non-ISO dossier string silently yields the default (`backend/scripts/run_parallel_simulation.py:2637`, `:2690-2698`, `:2722`, `:2738`). The map's downstream-consumer list leaves these out.
3. **Per-batch and per-agent canonical re-validation.** For canonical dossiers, `_valence_signal_active` runs uncaught once per batch (`:2989`). When valence is active, `_relation_sentiment_nudge` also runs once per agent (`:3115-3116`). Each call recomputes every pack's validation and `canonical_json_sha256(actors)` over the whole dossier (`:1157`, `:1197`, `:1523-1529`). This is a hidden abort point (see correction 8) and a quadratic-ish cost for large dossiers.
4. **The hours and calendar paths treat `as_of` differently.** The hours path (`events_to_schedule`) keeps events dated exactly on `as_of` (span ≥ 0). It returns no scheduled events at all when the dossier `as_of_date` is unparseable (`backend/app/utils/actors.py:1414`, `:1428`, `:1453`). Calendar mode drops `d ≤ as_of` (`backend/app/utils/actors.py:1513`) and falls back to today for an unparseable `as_of` (`:957`).
5. **LLM `stance` strings are not normalized.** Values such as "Supportive" or "支持" are copied verbatim (`:3044`). PREP-2 fires only on the rule path or an exact "neutral" (`:3130`). Echo clustering only lowercases (`:1255`). Cadence and audience logic never re-bucket the named agents' LLM stances, so out-of-vocabulary stances split echo clusters.
6. **`_coerce_int` misses OverflowError.** It catches only TypeError and ValueError. A JSON `Infinity` (accepted by `json.loads`) in hours-mode `total_simulation_hours`, `minutes_per_round` or `agents_per_hour_*` raises OverflowError from `int(float('inf'))`. Nothing catches it in `generate_config` (`:2250-2253`, `:588`).
