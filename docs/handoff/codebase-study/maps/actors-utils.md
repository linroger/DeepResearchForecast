# actors-utils — utils/actors.py

Slice: `backend/app/utils/actors.py` (3006 lines, read in full). All anchors are `path:line` relative to the repo root; unqualified `:N` means `backend/app/utils/actors.py:N`.

How this was checked: I read every line. I also loaded the module in isolation under a fake parent package, so `from ..config import Config` raised and the module's own fallbacks ran. No `.env` or app config was loaded. I then called the pure helpers on small fixtures. Results from those calls are marked **(probe)**. Because the fallbacks ran, the probes saw every Config flag at its default.

---

## Purpose & position in the pipeline

`actors.py` is the shared, pure-Python reader, renderer and normalizer for `actors.json`. That file is the structured output of the deep-research stage (contract documented in the module docstring at `:1-96`). Every stage after research uses it:

- **Research → prepare:** `pipeline_orchestrator` uses it to:
  - dedupe the cast (`reconcile_cast`);
  - measure dossier coverage (`dossier_coverage`);
  - recover scenario probabilities from the research report when `forecast_inputs` is missing (`forecast_inputs_from_report_markdown`, `valid_scenario_distribution`);
  - seed the WorldState / decision channel (`world_state_seed_from_actors`);
  - seed ontology generation (`ontology_seed_block`, `situation_brief_block`, `REL_LABEL`).
- **Graph build:** `graph_builder` writes actor/relationship triplets with `REL_EDGE_NAME`, valence and polarity, and the tier/salience attributes. `zep_entity_resolver` and `graph_pruner` use `normalize_name` to merge and prune nodes.
- **Simulation prepare:**
  - Agent-pool gating: `zep_entity_reader` and `simulation_manager` use `match_actor`, `is_agent_eligible`, `entity_simulation_tier`, `salience_score`, `is_media_entity`.
  - Persona prompts: `oasis_profile_generator` uses `actor_briefing`, `relationship_briefing`, `roster_block`, `behavioral_dna_block`, `influence_weight`.
  - Config and event schedule: `simulation_config_generator` uses `actors_digest`, `situation_brief_block`, `build_initial_follow_graph`, `events_to_schedule`, `events_to_calendar_rounds`, `relation_polarity`, `forecast_inputs_block`.
- **Report:** `report_agent` uses:
  - source indexes: `sources_index_unified`, `sources_index_tiered` / `sources_index_tiered_map`;
  - evidence blocks: `quantitative_facts_block`, `contested_claims_block`, `forecast_inputs_block`, `projected_edges_block`;
  - the roster: `relational_roster`.

  The orchestrator also renders `situation_brief(actors)` and passes it into the report agent.

Design rule stated in the module (`:120-122`): `actors.json` is always an *optional enhancement*. Missing or mistyped fields quietly fall back to None, `""`, `[]` or `{}`, and nothing in this module should block the plain-LLM path. Almost every function begins with an `isinstance(..., dict)` guard. Apart from the explicit-v2 fail-closed rule (`:203-233`), there are no raises. [verifier: the module has zero `raise` statements (AST count 0), and the fail-closed rule does not raise either; it returns `{}`/`True` for any explicit non-v1 version, not only v2 (`:212-213`, `:230-232`). Implicit exceptions are still possible: see the note under Invariants (`:2248`, `:2393`)] The module does no file I/O, makes no network or LLM calls, and starts no subprocesses. Its only side channel is three lazy reads of `Config` flags (`:898-904`, `:1436-1441`, `:2498-2504`).

The docstring also claims (`:122`) that *all* consumers read `actors.json` only through this module. That is not true (see Surprises).

---

## Walkthrough (source order)

### Module header
- **Docstring / contract** `:1-123`. Documents the full `actors.json` shape:
  - top-level: `central_question`, `as_of_date`, `situation_brief`{current_situation, context, dynamics, fault_lines, catalysts};
  - `actors[]` rows: name, type, role, stance, influence, description, aliases, goals, constraints, assets, vulnerabilities, stated_vs_revealed, memory, archetype, simulation_tier, role_class, salience, worldview, incentives, resources, risk_tolerance, `intelligence`{schema_version `actor-intelligence/v1`, dimensions, evidence_gaps, coverage};
  - `relationships[]`: source, target, type, relation_label, valence, polarity, sign, strength, since/until, basis;
  - `key_events[]`, `hot_topics[]`, `sources[]` (tier S1-S4, date, supports, independent), `quantitative_facts[]`, `contested_claims[]`, `forecast_inputs`{base_rates, drivers, indicators, scenarios}.

  A function index follows at `:98-118`. It is incomplete; see Surprises.
- **Imports** `:125-131`: `copy, json, re, unicodedata, typing`. That is the whole stdlib footprint. Intra-package imports are lazy: `.dates.parse_as_of` (`:1409`, `:1489`, `:2972`), `.sim_timeline.round_for_date` (`:1490`), and `..config.Config` (`:901`, `:1438`, `:2500`).
- **`INFLUENCE_WEIGHTS`** `:134-142`: free-text influence → weight. `high`/`高` → 2.5, `medium`/`med`/`中` → 1.5, `low`/`低` → 1.0. Its insertion order matters (see `influence_weight`).

### Identity / normalization
- **`normalize_name(name)`** `:145-156`.
  1. Falsy input → `""`.
  2. Apply NFKC, then `.lower()`.
  3. Delete runs of whitespace and these punctuation marks (regex `:155`): `. , : ; - _ ( ) [ ] 【 】 （ ） ' " ·`.

  Everything else is kept, including `/`, `&` and `+` (probe: `"Ｏｐｅｎ-AI/Corp&Co"` → `"openai/corp&co"`). Company suffixes such as `公司` or `Inc` are *not* stripped (probe: `"OpenAI 公司 (Inc.)"` → `"openai公司inc"`); suffix variants are matched only through containment. Pure function.
- **`_actor_norm_aliases(row)`** `:159-177`. If `row["aliases"]` is a list, returns `normalize_name` of each string element, dropping empties. Otherwise returns `[]`.
- **`extract_actor_rows(actors)`** `:180-187`. Returns `actors["actors"]` filtered to dict rows with a truthy `name`. Anything not a dict, or with a non-list `actors`, gives `[]`. This is the gate behind nearly every other helper.

### actor-intelligence/v1 accessors
- **`ACTOR_INTELLIGENCE_SCHEMA_VERSION = "actor-intelligence/v1"`** `:190`.
- **`actor_intelligence_schema_version(actor)`** `:193-200`. Returns `str(actor["intelligence"]["schema_version"]).strip()`, or `""`.
- **`has_unsupported_actor_intelligence_schema(actor)`** `:203-213`. True only when a version is declared *and* it is not v1. Unversioned rows count as legacy and are supported.
- **`actor_intelligence_payload(actor)`** `:216-233`. Returns the `intelligence` dict when it is unversioned or v1. Returns `{}` when it is missing, not a dict, or carries a different explicit version. This is the fail-closed rule for unknown versions (`:231-232`).
- **`actor_intelligence_dimension(actor, canonical, *flat_aliases)`** `:236-254`. Lookup order:
  1. `payload.dimensions[canonical]`. If that is a dict with non-empty `claims`, `items` or `entries`, return that list (`:245-248`). Otherwise return the value itself if it is not `None`/`""`/`[]` (`:249-250`).
  2. Otherwise the first non-empty `payload[flat_alias]`. Note these aliases are keys on the **intelligence payload**, not top-level actor keys (`:251-253`).
  3. Otherwise `None`.
- **`_intelligence_has_source_refs(value, depth)`** `:257-269`. Recursive search, depth-capped at 12, for any truthy `source_refs`, `source_ids`, `evidence_refs` or `citations` key.
- **`actor_intelligence_claims(actor, canonical, *aliases, limit=3, max_chars=260)`** `:272-347`. Renders up to `limit` bounded strings.
  - A dimension value that is a dict, scalar or list is treated as a list of rows (`:281-288`).
  - For a dict row, the claim text is the first of `claim`/`finding`/`description`/`text`.
  - Qualifiers are rendered as `label=value` for: as of, confidence, evidence type, status, horizon, conditions, amount, unit, action type, purpose (`:302-313`). Each is read from the row first, then from `row.qualifiers` (`:314-321`). List values are joined with `; ` (max 4).
  - Up to 4 refs are appended as `sources=a,b` (`:328-333`).
  - Qualifiers are rendered only when a claim exists (`:334-337`).
  - Whitespace is collapsed. Text longer than `max_chars` is cut to `max_chars-1` and given a `…` suffix (`:340-342`).
- **`actor_intelligence_dimension_presence(actor)`** `:350-442`. Returns a dict of booleans: identity_history, track_record, history, values_worldview, incentives, motivations, capabilities, constraints, preferences, alliances, opponents_competitors, current_actions, future_plans, investments, decision_model, likely_actions, red_lines, knowledge_state, report_context, source_refs, provenance, evidence_gaps, producer_coverage.
  - `preferences` is true when a `likes`/`dislikes` dict is non-empty, or when the dimension or `intel.aversions` is truthy (`:361-367`).
  - `report_context` is true for `intel.relevant_report_context`, or for `intel.context_pack.actor_relevant_report_sections` (`:372-376`).

  The docstring says this is a structural presence check, not a confidence measure (`:353-358`).

### Matching
- **`match_actor(entity_name, actors)`** `:445-492`. Resolves a graph/Zep entity name to an actor row.
  1. **Exact pass** `:461-469`. Every row whose normalized name equals the normalized target, or whose normalized aliases contain it, goes into a dict keyed by the row's **normalized canonical name**. Exactly 1 key → return that row. More than 1 → `None` (ambiguous). Because the dict is keyed by canonical name, two rows with the *same* normalized name collapse to one key and the **last row wins**, not ambiguity (probe: `"X Corp"` + `"xcorp"` → returns the second).
  2. **Fuzzy pass** `:474-492`. Runs only if there was no exact hit. For each row's surfaces (name and aliases), it records a candidate when `min(len(surface), len(target)) >= 4` and either string contains the other (`:478-479`). It keeps the candidates with the longest surface. If they map to exactly one distinct canonical, that row is returned; ties → `None`, which is fail-closed (`:490-492`). [verifier: a tie returns None only when the longest-surface candidates span more than one distinct canonical. A tie between surfaces of the same canonical (e.g. name and alias of one row) returns that row (`:485-492`; probe: `"Alpha Beta Inc"` against `{name:"Alpha Beta", aliases:["Alpha-Beta"]}` returns the row)]

  Probes: `"OpenAI Inc"` → OpenAI; `"MSFT"` → Microsoft via alias; `"U.S."` → US (exact after punctuation strip); `"USA"` → None; `"Metaculus Inc"` → **Meta** (a fuzzy false positive).
- **`influence_weight(actor)`** `:495-505`. Takes `str(influence).strip().lower()` and returns the weight of the **first** `INFLUENCE_WEIGHTS` key that is a *substring*, in dict order (high, 高, medium, med, 中, low, 低). Returns None if nothing matches or the field is empty. Probes: `"medium-high"` → 2.5, `"highly uncertain"` → 2.5, `"low-medium"` → 1.5.

### Prompt blocks (persona / config)
- **`actor_briefing(actor, max_memory_chars=600, max_intelligence_chars=2200)`** `:508-595`. Persona-injection block.
  - Lines for role/stance/influence (`:521-524`).
  - List fields goals/constraints/assets/vulnerabilities: first 6, joined with `；` (`:527-531`).
  - `stated_vs_revealed` (`:532-534`).
  - `memory`, truncated to `max_memory_chars` plus `…` (`:535-539`).
  - Then 11 intelligence dimensions, up to 2 claims each (`:541-556`): identity_history, track_record, motivations, capabilities, operational_preferences, current_actions, future_plans, investments_capital_allocation, decision_rights_process_triggers, knowledge_state, red_lines.
  - Then `evidence_gaps`. For a dict, keys are walked in sorted order, at most 3 gaps, each cut to 220 chars. For a list, at most 3, each cut to 260 chars (`:557-582`).
  - Intelligence lines are added greedily until `max_intelligence_chars` would be exceeded (`:583-589`).
  - Output header: `## 深度研究实证档案（来自真实网络调研，生成时必须以此为准）` (`:592-595`). Empty → `""`.
- **`actors_digest(actors, max_actors=30, max_chars=4000)`** `:598-660`. Config-generation digest. Contents:
  - one line per actor (first 30): name (type), role, stance, influence, first goal, and 1 claim each, capped at 140 chars, for current_actions, future_plans and investments (`:613-640`);
  - `key_events[:15]` (`:642-650`);
  - `hot_topics[:12]` (`:652-655`).

  Hard truncation to `max_chars`, with suffix `\n…(研究档案已截断)` (`:657-659`).

### Relationship vocab & renderers
- **`REL_EDGE_NAME`** `:668-702`. Maps relationship type → KG edge name. It is the identity mapping for the 8 legacy, 13 ONTOLOGY and 5 causal (`CAUSES`, `ENABLES`, `CONSTRAINS`, `TRIGGERS`, `ACCELERATES`) types. `OTHER` → `RELATES_TO`. [verifier: only 7 of the 8 legacy types are identity-mapped; the 8th legacy type is `OTHER` itself, which maps to `RELATES_TO`. That gives 25 identity entries plus `OTHER` (`:669-675`, `:701`)]
- **`REL_LABEL`** `:705-734`. Chinese label per type; `OTHER` → `关联`.
- **`extract_relationship_rows(actors)`** `:737-760`. Keeps dict relationship rows whose `source` and `target` both normalize into the set of actor names **plus aliases** (`:749-752`). Drops everything else.
- **`situation_brief_block(actors, english=False)`** `:763-789`. Renders `situation_brief` prose fields (current_situation/context/dynamics) and list fields (fault_lines/catalysts, first 6 each) as `###` subsections. Titles are Chinese by default and English when `english=True` (`:769-777`). Missing or empty → `""`.
- **`relationship_briefing(actor_name, actors, max_edges=6)`** `:792-817`. For edges where `normalize_name(actor_name)` equals the source, emits `"{label}（{strength}）: {target}"`. Where it equals the target, emits `"被{label}: {source}"`.
  - For `OTHER`, a non-empty `relation_label` replaces the label (`:803-806`).
  - Endpoint comparison uses `normalize_name` only, not aliases (`:807-812`).
  - Header: `## 你的社会关系网（调研实证，互动时据此 @ 相关方）`.

### Ontology layer: archetype, tier, media, salience, valence
- **`ENTITY_ARCHETYPES`** `:826-830` (11 values). **`_AGENT_ARCHETYPES = {actor, collective}`** `:832`.
- **`_VALENCE_POLARITY`** `:835-841`: allied +0.4, adversarial −0.4, transactional +0.15, directional 0, neutral 0.
- **`_REL_TYPE_VALENCE`** `:843-859`. Type → valence: alliance types → allied; OPPOSES/COMPETES/SANCTIONS/CRITICIZES/LITIGATES → adversarial; economic types → transactional; governance/influence/reporting/causal types → directional. Anything else (including `OTHER`) is absent here and becomes neutral.
- **`entity_archetype(actor)`** `:862-867`. Returns the lower-cased `archetype` if it is in `ENTITY_ARCHETYPES`, else `"actor"`. Missing and invalid values both become `"actor"`.
- **`_MEDIA_TYPE_VALUES`** `:874` and **`_MEDIA_ROLE_KEYWORDS`** `:875-881` (EN and ZH keywords such as journalist, newspaper, pollster, think tank, 记者, 智库…).
- **`_explicit_simulation_tier(actor)`** `:884-895`. Accepts an int in {1,2,3,4} (bools excluded) or a string, from which it takes the **first digit 1-4 found anywhere** (`re.search(r"[1-4]")`). Probes: `"tier 3"` → 3, `"12"` → 1. Otherwise None.
- **`_media_exclusion_enabled()`** `:898-904`. Reads `Config.ACTOR_EXCLUDE_MEDIA` lazily. Returns True if Config cannot be imported.
- **`is_media_entity(actor)`** `:907-925`.
  - An explicit tier of 1 or 2 → False (`:915-916`).
  - `type` in the media set → True.
  - Raw `archetype == "source"` → True.
  - Otherwise True when any `_MEDIA_ROLE_KEYWORDS` entry is a **substring** of `role + role_class + description`, lower-cased (`:922-925`).
- **`entity_simulation_tier(actor)`** `:928-958`.
  - Not a dict → 1.
  - Explicit tier wins.
  - Archetype `source` → 3; any other non-agent archetype → 4.
  - If media exclusion is on and the row is a media entity → 3 (`:952-953`).
  - Influence weight ≥2.5 → 1; any other parseable weight → 2; **unparseable or missing influence → 1** (`:955-958`).
- **`is_agent_eligible(actor)`** `:961-967`. True when the tier is 1 or 2.
- **`salience_score(actor)`** `:970-1000`.
  1. Numeric `salience.score` (non-bool), clamped to [0,1].
  2. Else `salience.tier` text: high 0.85, medium 0.55, low 0.3.
  3. Else from influence weight: ≥2.5 → 0.85, ≥1.5 → 0.55, otherwise 0.3. No signal → 0.3.
- **`relation_valence(rel)`** `:1003-1015`. An explicit valence in the polarity table wins. Otherwise `_REL_TYPE_VALENCE[TYPE.upper()]`, defaulting to `"neutral"`.
- **`relation_polarity(rel)`** `:1018-1042`. A numeric `polarity` (non-bool) is clamped to [−1,1]. Otherwise the valence base value is scaled by strength: high/高 ×1.0, medium/med/中 ×0.7, low/低 ×0.45, unknown ×1.0. Probe: ALLY_OF+low → 0.18; SUPPLIES+medium → 0.105.

### Relational roster
- **`_ROSTER_RULES`** `:1051-1069`. Ten buckets, each a list of `(type, direction)`:
  - `out`: I am the source, so the target goes in the bucket.
  - `in`: I am the target, so the source goes in.
  - `both`: either end.

  Buckets: allies, opponents, competitors, customers, suppliers, backers_investors, supporters, regulators, dependents, partners. Example: `SUPPLIES` feeds customers(out), suppliers(in) and dependents(out).
- **`_rel_strength_text`** `:1072-1074`.
- **`relational_roster(actor_name, actors)`** `:1077-1133`. Returns the 10 buckets of `[{name, basis, strength}]`. Each bucket is de-duplicated by normalized name in order of appearance and never includes the actor itself (`:1098-1110`). It uses `extract_relationship_rows`, and identifies "me" by `normalize_name` equality only, so alias endpoints are invisible here (`:1115-1117`).
- **`_ROSTER_BUCKET_LABEL`** `:1137-1148`. Display order and Chinese labels.
- **`roster_block(actor_name, actors, max_per_bucket=5)`** `:1151-1174`. Renders `## 关系网角色（调研实证：互动时据此 @ 正确阵营）`, one line per bucket, as `name（strength）` joined with `、`.

### Behavioural DNA
- **`_dna_str_list(value, limit)`** `:1177-1188`. Non-empty stripped strings from a list.
- **`behavioral_dna_block(actor)`** `:1191-1267`. Renders:
  - worldview identity/frame/values(6)/beliefs(6) (`:1201-1214`);
  - incentives (first 6). Dict rows render `driver：得益于「gains_if」，受损于「loses_if」（强度 intensity）`; string rows are passed through (`:1216-1244`);
  - resources(8), falling back to assets(8) (`:1247-1249`);
  - risk_tolerance (`:1251-1253`);
  - up to 3 claims each from 4 intelligence dimensions: values_worldview, incentives, motivations, operational_preferences (`:1255-1263`).

  Header `## 行为 DNA（…）`. Empty → `""`.

### Simulation wiring
- **`build_initial_follow_graph(actors, agent_id_by_name)`** `:1270-1320`. Returns a de-duplicated list of `[follower_id, followee_id]`.
  - Endpoints are resolved with `agent_id_by_name.get(normalize_name(n))`. The caller's map must already be normalized. Unresolved endpoints and self-loops are skipped (`:1286-1289`).
  - Each endpoint's influence comes from `influence_weight(match_actor(...))`, defaulting to 1.0 (`:1290-1291`).
  - Direction rules:
    - ALLY_OF: the lower-influence side follows the higher; on a tie, source follows target (`:1292-1294`).
    - PARTNERS_WITH, OPPOSES, COMPETES_WITH: both directions.
    - DEPENDS_ON: source follows target.
    - INFLUENCES: target follows source.
    - REGULATES: source follows target.
    - SUPPLIES: customer (target) follows supplier. CUSTOMER_OF: source follows target.
    - FUNDS, INVESTS_IN, BACKS, OWNS, SUPPORTS, ENDORSES: target follows source.
    - SANCTIONS, LITIGATES_AGAINST, CRITICIZES: both directions.
    - REPORTS_ON, CONSUMES, OTHER and the causal types: no edge (`:1319`).
  - Output comes from iterating a set, so it is unsorted.
- **`situation_brief(actors, max_actors=25, max_chars=6000)`** `:1323-1395`. The report's "background dossier". Contains:
  - `**核心问题**` and `**研究截止日 (as-of)**`;
  - `situation_brief_block` output;
  - an actor table (first 25);
  - `rels[:40]` as `src --[label]--> tgt（strength）: basis`. For `OTHER` this uses `REL_LABEL`, i.e. `关联`, and **ignores relation_label** (`:1366-1367`);
  - `key_events[:20]` and `hot_topics[:15]`.

  Truncated with suffix `\n…(背景档案已截断)` (`:1392-1394`).
- **`events_to_schedule(actors, total_rounds, as_of_date, horizon_days=None)`** `:1398-1460`. Hour-mode event schedule.
  1. Returns `[]` if `total_rounds<=0`, if as_of does not parse, or if `key_events` is not a list.
  2. Parses each event date with `parse_as_of` and computes `span = (d - base).days`. **Events with span ≥ 0 are kept, including same-day events** (`:1427-1429`, `:1452-1454`).
  3. `hz = horizon_days or max(spans) or 1` (`:1430`).
  4. **PREP-5 react buffer** (`Config.SIM_EVENT_REACT_BUFFER`, default True; also True if Config fails to import): `effective_rounds = max(1, total_rounds - max(2, total_rounds//5))` (`:1436-1443`).
  5. `round = min(total_rounds-1, round(span/hz*effective_rounds))` (`:1456`).

  Returns `[{round, event, date}]`. Probe: 10 rounds, a one-year event → round 8 (2 rounds of buffer).
- **`events_to_calendar_rounds(actors, round_dates, as_of_date, horizon_date)`** `:1463-1526`. Calendar-mode schedule.
  - Bad input → `([], [])`.
  - Unparseable dates → skipped (the caller counts these).
  - **`d <= as_of` → dropped** (`:1513-1514`).
  - `d > horizon` → a shallow copy goes into the second return value, `beyond` (`:1515-1517`).
  - Otherwise the round is `sim_timeline.round_for_date(d, round_dates)`. That is a `bisect_left` on `period_end`, which returns None before the first `period_start` or after the last end (`backend/app/utils/sim_timeline.py:491-510`). None → skipped silently (`:1518-1520`).

  Returns `(scheduled[{round,event,date}], beyond[raw dicts])`.

### Source tiers & citation indexes
- **`SOURCE_TIERS`** `:1534`. **`_TIER_DESC`** `:1536-1541`.
- **`_norm_tier(value)`** `:1544-1553`. Upper-cases, then `re.search(r"S?\s*([1-4])")` **anywhere** → `S<n>`, else `""`. Probes: `"tier 2"` → S2; `"10"` → S1; `"B2"` → S2; `"2026-05-01"` → S2; `"S5"` → `""`.
- **`extract_source_rows(sources)`** `:1556-1567`. Accepts a list, or `{"sources": [...]}`. Keeps dict rows with a title or url.
- **`source_tier_histogram(sources)`** `:1570-1582`. Returns `{s1_count..s4_count, untiered_count}`. It has no callers (see Surprises).
- **`sources_index_tiered(sources, max_sources=40)`** `:1585-1633`. Legacy tiered index. Takes the first 40 valid rows in **input order**, buckets them by tier (untiered → `S?`), and tags each as `[S1-a]`, `[S2-b]`, … with letters a-z, then the raw index number past 26 (`:1617`). Each row may carry date, `非独立` (when `independent is False`) and the URL.
- **`sources_index_tiered_map(sources, max_sources=40)`** `:1636-1661`. Rebuilds the same bucketing and tagging and returns `{"S1-a": row}`.
- **`_raw_source_rows`** `:1664-1673`. Position-preserving raw list, including junk rows.
- **`_source_cited_in_research(row, research_norm)`** `:1676-1689`. True when the URL with scheme and trailing slash stripped (≥12 chars), or the title (≥8 chars), is a substring of the lower-cased, whitespace-collapsed report.
- **`_source_evidence_preview(row, max_chars=280)`** `:1692-1710`. Joins `supports[:3]`, `excerpt` and `snippet`, de-duplicated, with `|` escaped. Bounded to `max(40, max_chars)`.
- **`sources_index_unified(sources, research_report=None, max_sources=60)`** `:1713-1770`. WAVE10 single-grammar index.
  - The tag is `S<pos>`, where pos is the **1-based position in the raw list**. Junk rows still consume a number (`:1733-1748`).
  - Ranking is (cited in report first, tier rank S1..S4, then untiered=5, then position). The top `max(1, max_sources)` are taken and re-sorted by position (`:1741-1742`).
  - Each line: `[S12] title（S2·可靠二手，date，非独立） — url ｜supports: …`.
  - Returns `(text, {"S12": row})`, or `("", {})`.

  Probe: with `max_sources=2`, the cited Reuters row (S1) and the tier-S1 row (S3) are kept, the S4 blog is dropped, and the junk row at position 2 still consumes "S2".
- **`actor_grade(actor)`** `:1773-1779`. An Admiralty grade upper-cased and full-matching `[A-F][1-6]`, else `""`. It has no callers.

### Evidence blocks
- **`extract_quantitative_rows`** `:1787-1799`. Keeps rows with a non-empty metric and value.
- **`quantitative_facts_block(actors, max_facts=20)`** `:1802-1837`. Markdown table `| 指标 | 数值 | 单位 | as-of | 定义 | 来源 |`. Cells escape `|` and flatten newlines. The source cell gets `（S<n>）` appended.
- **`CONTESTED_STATUS`** `:1845`, **`_STATUS_LABEL`** `:1846-1851`.
- **`extract_contested_rows`** `:1854-1877`. Requires a claim, plus either ≥2 dict positions or `status == single-origin`.
- **`contested_claims_block(actors, max_claims=8)`** `:1880-1921`. Renders the claim with its status label, each position's stance with its tier and up to 3 sources, and `why_they_differ`.
- **`SCENARIO_NAMES`** `:1929` (unused), **`_SCENARIO_LABEL`** `:1930`.
- **`extract_forecast_inputs(actors)`** `:1933-1948`. Always returns the 4 keys, each a list of dicts.

### Dossier coverage (observability)
- **`dossier_coverage(actors)`** `:1951-2091`. Pure metrics. Zero actors returns a zero skeleton of 32 keys (`:1962-1992`). [verifier: the skeleton and the full result both have 34 keys (probe `len(dossier_coverage(...)) == 34`). The list below also omits `pct_actors_with_actor_intelligence` = explicit-v1 rows / n (`:1967`, `:2064`)] Otherwise:
  - `n_actors`, `n_relationships`, `n_tier12`;
  - `pct_actors_with_incentives`: top-level `incentives` or the intel incentives dimension (`:2002-2006`);
  - `pct_tier12_with_worldview` (`:2007-2012`);
  - `pct_edges_valenced`: edges carrying an explicit `valence`, or a `polarity` that is not None (`:2050-2053`);
  - `edges_per_actor`, `salience_basis_present`;
  - `n_actor_intelligence_v1`: rows whose payload has an **explicit** v1 marker (`:2015-2019`);
  - `pct_tier12_with_complete_actor_intelligence`: all 18 `critical_dimensions` present (`:2023-2038`);
  - 23 `pct_intelligence_with_*` rates, computed over v1 rows only (`:2040-2044`).

  Values are rounded to 3 places; `edges_per_actor` to 2.

### Cast reconciliation (dedupe / merge)
- **`_row_norm_tokens`** `:2094-2103`. Normalized name plus normalized aliases.
- **`_rows_same_entity(a, b)`** `:2106-2119`. True if the token sets intersect, **or** one primary name contains the other and the shorter is ≥4 chars. Probe: `"Meta"` vs `"Metaculus"` → same entity.
- **`_INTELLIGENCE_DIMENSION_ALIASES`** `:2122-2142`. The 17 canonical dimensions and their flat aliases, used for merging.
- **`_claim_merge_key(value)`** `:2145-2160`.
  - For a dict, takes the first of claim/finding/description/text/event/action/plan/investment/capability/subject and returns `"claim:" + casefolded, whitespace-collapsed` text.
  - For a string, the same `claim:` form.
  - Otherwise canonical JSON (`json:`), with a `repr:` fallback.
- **`_dimension_claim_rows(value, dimension)`** `:2163-2198`. Turns a dimension value into a list of claim dicts, deep-copied.
  - `{"claims": [...]}` is unpacked.
  - For operational_preferences, `likes`/`dislikes` get `preference_kind`.
  - For decision_rights_process_triggers, decision_rights/decision_process/triggers/red_lines get `decision_kind`.
  - Scalars and lists are wrapped.
- **`_merge_actor_intelligence(members)`** `:2201-2330`. Unions the supported intelligence payloads from duplicate rows.
  - Payloads are de-duplicated by fingerprint (`:2212-2218`).
  - Per dimension, claims are unioned by merge key. On a collision, source-ref lists are unioned; missing fields are filled; differing non-empty fields are logged to `conflicts` and the first value is kept (`:2228-2263`).
  - Writes `dimensions[dim] = {"claims": [...]}`.
  - Records `variant_audit` when there is more than one claim in current_actions, future_plans, investments_capital_allocation, decision_rights_process_triggers or red_lines (`:2267-2276`).
  - Unions evidence_gaps (`:2278-2295`) and top-level source_refs (`:2296-2305`).
  - `merge_provenance` keeps every coverage and provenance snapshot (`:2309-2323`). A single snapshot is promoted to `coverage`/`provenance` (`:2326-2329`).
  - Returns `(merged|None, conflicts)`.
- **`reconcile_cast(actors)`** `:2333-2448`.
  - Fewer than 2 rows, or no duplicates → returns the **same input object** with an audit of `{"merged": [], n_before, n_after}` (`:2348-2349`, `:2372-2373`).
  - Clusters rows with an O(n²) union-find (path halving) over `_rows_same_entity` (`:2352-2369`).
  - Per cluster, the survivor is the max of (richness = count of truthy `_RICH_KEYS`, alias count, name length) (`:2375-2394`).
  - Victims:
    - their names and aliases become survivor aliases;
    - fields falsy on the survivor are back-filled from victims;
    - conflicting strings in role/stance/type/influence are logged as `{field, kept, dropped, from}` (`:2399-2415`).
  - Intelligence is rebuilt with `_merge_actor_intelligence` (`:2416-2419`).
  - Aliases are sorted with the canonical name removed (`:2420-2422`).
  - Relationship endpoints equal to a victim's normalized name are rewritten to the canonical name (`:2433-2446`).
  - Returns `(new_obj, {"merged": [{canonical, merged, conflicts}], n_before, n_after})`.

### Ontology seed
- **`ontology_from_actors(actors)`** `:2451-2482`.
  - Distinct actor `type` values become `entity_types`.
  - Distinct edge names from relationships become `edge_types`. For `OTHER` with a `relation_label`, the label is sanitized to `[A-Z0-9_]`. Each edge type is `{name, valence}`, with valence from `_REL_TYPE_VALENCE[type]`; `OTHER` therefore always becomes neutral.
  - Both empty → `{}`.
- **`ontology_seed_block(actors)`** `:2485-2512`. Renders the seed as a Chinese constraint block. The number of extra types the LLM may add is `allow_new = max(2, 8 - len(entity_types))` when `Config.ONTOLOGY_SEED_ADAPTIVE_BUDGET` is on (default, and also the fallback when Config fails to import), else 2 (`:2498-2504`).

### Probabilities, scenarios, WorldState seed
- **`_parse_probability_value(value)`** `:2515-2552`.
  - None and bools → None.
  - Numbers: kept only if in (0,1].
  - Text: extract all numbers. If the text contains `%` or **any** number exceeds 1, divide all of them by 100. Take the mean. Reject results outside (0,1]. Round to 6 places.

  Probes: `"30-40%"` → 0.35; `"0.3-0.5"` → 0.4; `45` → None; `"1 in 4"` → 0.025; `"1.5"` → 0.015; `"2030: 40%"` → None.
- **`valid_scenario_distribution(forecast_inputs)`** `:2555-2591`. Requires 1-6 dict rows with unique non-empty normalized names. Each needs a parseable value from the first key, in order probability/likelihood/base_rate/prob/probability_band, that yields a value. The sum must satisfy `|sum − 1| ≤ 0.02`. A single scenario passes only with P=1.
- **`_match_reference_class_to_scenario(rc, names)`** `:2594-2610`. Normalized bidirectional containment, with the key at least 3 chars; the longest name wins.
- **`world_state_seed_from_actors(actors)`** `:2613-2678`. Returns `{scenarios:[names], base_rates:{name: p}, uniform_prior: bool}`, or `{}` when there are no named scenarios.
  - Rate priority:
    1. The bare keys probability/likelihood/base_rate/prob via plain **`float(v)`** (`:2641-2650`).
    2. `_parse_probability_value(probability_band)` (`:2652-2655`).
    3. `base_rates[].outcome_frequency`, mapped by reference_class, only for scenarios that still lack a rate (`:2661-2672`).
  - `uniform_prior = not any(v > 0)` (`:2675-2677`).
  - It does **not** check the partition invariant.
- **Report-markdown scenario parser** `:2681-2831`.
  - Regexes: `_SCENARIO_SECTION_CUE_RE` (`:2686`, scenario/情景/情境/场景), `_SCENARIO_AGGREGATE_TOTAL_RE` (`:2687-2691`), `_MD_HEADING_RE` (`##`–`######`, `:2692`), `_MD_BOLD_LIST_ITEM_RE` (`:2693`), `_PROB_RANGE_RE` (`:2696-2697`), `_PROB_DECIMAL_RE` (`:2701-2702`, a complete decimal after 概率/probability, guarding the old "概率 15%" → 1.0 bug), `_PROB_PERCENT_RE` (`:2703`).
  - `_extract_probability_text` (`:2706-2712`) tries range, then decimal, then percent.
  - `_is_scenario_section_heading` (`:2715-2736`) requires a scenario cue and either no probability, or a probability of 1.0 together with aggregate wording ("summing to 100%").
  - `_strip_probability_annotation` (`:2739-2743`) and `_append_scenario_row` (`:2746-2762`) build rows. A range keeps the raw `probability_band`; a point becomes a `probability` float. Names are de-duplicated by normalized form.
  - **`forecast_inputs_from_report_markdown(report_md)`** `:2765-2831`.
    1. Each candidate section heading opens a section that ends at the next heading of the same or shallower level.
    2. Rows come from deeper headings that carry a probability, or from bold list items. For bold items the probability is in the bold text, or within the first 60 chars of the remainder before the first colon (`:2808-2819`).
    3. The section needs 2-6 rows and a midpoint sum in **[0.9, 1.1]** (`:2820-2829`). Otherwise the parser moves on to the next candidate section.

    Returns `{"scenarios": rows, "base_rates": []}` or `{}`.

### Relationship projection & forecast scaffold
- **`_VALENCE_TRAJECTORY`** `:2836-2841`: allied → likely_persists, adversarial → persists_or_escalates, transactional → contingent, neutral → uncertain. Directional valence is not in the map and falls to `("uncertain","轨迹不定")` (`:2856`).
- **`project_relationships(actors)`** `:2844-2862`. Returns `[{source, target, type, valence, projected, rationale}]` for each `extract_relationship_rows` row. These are model priors, not evidence.
- **`projected_edges_block(actors, max_rows=14)`** `:2865-2877`. Sorts contingent, then persists_or_escalates, then likely_persists, then uncertain. Renders with a header marked `⚠模型推断·非证据`.
- **`forecast_inputs_block(actors, max_per_section=6)`** `:2880-2958`. Up to 6 each of:
  - base rates: reference_class, freq, basis;
  - drivers: variable, direction, why;
  - indicators: name, date/trigger, signals;
  - scenarios: the label is `_SCENARIO_LABEL` for base/upside/downside, otherwise the **lower-cased raw name**. Only `probability_band` is shown, plus narrative and `key_assumptions[:4]` (`:2941-2957`).
- **`indicators_to_schedule(actors, total_rounds, as_of_date, horizon_days=None)`** `:2961-3006`. Like `events_to_schedule` but over `forecast_inputs.indicators[].date_or_trigger`, and **without the react buffer** (`:3002`). It has no callers.

---

## Control flow

This module is a library: nothing in it runs on import. Internal call chains:

- `extract_actor_rows` (`:180`) is used by `match_actor` (`:451`), `actors_digest` (`:611`), `extract_relationship_rows` (`:748`), `situation_brief` (`:1344`), `dossier_coverage` (`:1993`), `reconcile_cast` (`:2346`) and `ontology_from_actors` (`:2460`).
- `extract_relationship_rows` (`:737`) feeds `relationship_briefing` (`:796`), `relational_roster` (`:1089`), `build_initial_follow_graph` (`:1279`), `situation_brief` (`:1362`), `dossier_coverage` (`:2046`), `ontology_from_actors` (`:2461`) and `project_relationships` (`:2852`).
- Tier chain: `is_agent_eligible` (`:967`) → `entity_simulation_tier` (`:928`) → `_explicit_simulation_tier` (`:884`), `entity_archetype` (`:862`), `_media_exclusion_enabled` (`:898`) → Config, then `is_media_entity` (`:907`) and `influence_weight` (`:495`).
- Intelligence chain: `actor_intelligence_claims` → `actor_intelligence_dimension` → `actor_intelligence_payload`. Used by `actor_briefing` (`:554`, `:557`), `actors_digest` (`:635`), `behavioral_dna_block` (`:1261`) and `_merge_actor_intelligence` (`:2233`).
- `reconcile_cast` → `_rows_same_entity` → `_row_norm_tokens`, then `_merge_actor_intelligence` → `_dimension_claim_rows` / `_claim_merge_key`.
- `ontology_seed_block` → `ontology_from_actors`. `projected_edges_block` → `project_relationships` → `relation_valence`. `roster_block` → `relational_roster`.
- `world_state_seed_from_actors` → `extract_forecast_inputs` → `_parse_probability_value` → `_match_reference_class_to_scenario`.
- `forecast_inputs_from_report_markdown` → `_is_scenario_section_heading` → `_extract_probability_text` / `_parse_probability_value`, then `_append_scenario_row`.

Pipeline order of use (caller anchors):
1. **Research finalize (orchestrator).**
   - `merge_actors_objs` → `reconcile_cast` for PAR-2 multi-track merges (`backend/app/services/pipeline_orchestrator.py:6433-6466`, called at `:11650`).
   - Then `_reconcile_research_cast` → `reconcile_cast` (`pipeline_orchestrator.py:3917-3946`, called at `:12158`). This wrapper does **not** apply the merge to sealed v1 actors.
   - `dossier_coverage` (`pipeline_orchestrator.py:12217-12233`).
   - `inject_forecast_inputs_from_report` → `valid_scenario_distribution` / `forecast_inputs_from_report_markdown` (`pipeline_orchestrator.py:5740-5782`, called at `:12239`).
2. **Ontology.** `_actors_to_context` uses `situation_brief_block`, `extract_relationship_rows` and `REL_LABEL` (`pipeline_orchestrator.py:6985-6999`). `ontology_seed_block` is appended when `ONTOLOGY_FROM_DOSSIER` is set (`pipeline_orchestrator.py:12337-12345`).
3. **Graph build.** `graph_builder.seed_actors` uses `extract_actor_rows`, `extract_relationship_rows`, `REL_EDGE_NAME`, `relation_valence`/`relation_polarity`, `actor_briefing(max_memory_chars=300)`, `entity_archetype`, `entity_simulation_tier` and `salience_score` (`backend/app/services/graph_builder.py:1375-1472`).
4. **Entity read / agent pool.**
   - `zep_entity_reader._explicit_classification` → `match_actor`, `is_media_entity`; then `is_agent_eligible` (`backend/app/services/zep_entity_reader.py:79-88`, `:423`).
   - `simulation_manager.ensure_dossier_actor_entities` (`backend/app/services/simulation_manager.py:224-266`).
   - `select_agent_pool` (`simulation_manager.py:351-470`).
5. **Persona generation.** `oasis_profile_generator`: `actor_briefing`, `relationship_briefing`, `behavioral_dna_block`, `roster_block` (`backend/app/services/oasis_profile_generator.py:1679-1692`). Rule-path overlay with `influence_weight` → follower/karma scaling (`oasis_profile_generator.py:2145-2156`).
6. **Simulation config.** `simulation_config_generator`:
   - `build_initial_follow_graph` (`backend/app/services/simulation_config_generator.py:859`);
   - `events_to_calendar_rounds` / `events_to_schedule` (`:1071`, `:1108`);
   - `relation_polarity` stance nudge (`:1219`);
   - `situation_brief_block` (`:1894`, `:1987`);
   - `actors_digest` (`:1996`, `:2376`);
   - `forecast_inputs_block` (`:2008`);
   - `match_actor` (`:2778`).
7. **WorldState seed (prepare).** `world_state_seed_from_actors`, preceded by another `inject_forecast_inputs_from_report` (`pipeline_orchestrator.py:12881-12900`).
8. **Report.**
   - `situation_brief(actors)` is passed in as a kwarg (`pipeline_orchestrator.py:6772`, `:8872`, `:13290`).
   - `report_agent` evidence blocks (`backend/app/services/report_agent.py:1874-1898`) and roster (`report_agent.py:1924-1961`).
   - Source index (`report_agent.py:2242-2257`).
   - Projected edges (`report_agent.py:2401-2404`).
   - Indicators via `extract_forecast_inputs` (`report_agent.py:3174`, `:4814`).

---

## Data & artifacts

- **Files:** none. The module never opens a file. Callers load `handoff/actors.json` and `sources.json` and pass the parsed dicts in (e.g. `pipeline_orchestrator.py:6766-6772`).
- **Main in-memory input:** the `actors.json` dict (contract at `:3-96`). Key fields read per function are listed in the walkthrough.
- **Main outputs:**
  - Prompt strings: Chinese markdown blocks, plus the English variant of `situation_brief_block`.
  - Edge lists: `List[List[int]]` (`:1320`).
  - Schedules: `[{round, event, date}]` (`:1455-1459`, `:1521-1525`).
  - Citation tag maps: `{"S12": row}` (`:1746-1749`) and `{"S1-a": row}` (`:1660`).
  - Coverage metrics dict (`:2054-2091`).
  - Reconcile output and audit `{merged:[{canonical, merged, conflicts}], n_before, n_after}` (`:2429`, `:2448`).
  - Ontology seed `{entity_types:[{name}], edge_types:[{name, valence}]}` (`:2479-2482`).
  - WorldState seed `{scenarios, base_rates, uniform_prior}` (`:2678`).
  - Parsed forecast_inputs `{scenarios:[{name, probability|probability_band}], base_rates: []}` (`:2830`).
- **Shape note:** the merged intelligence produced by `reconcile_cast` is a *legacy compatibility shape* (`dimensions[dim] = {"claims": [...]}` plus `merge_provenance`) (`:2222-2225`, `:2266`, `:2317-2323`). The orchestrator therefore refuses to apply it to sealed v1 actors (`pipeline_orchestrator.py:3920-3940`).

---

## Config / env knobs

All three are read lazily through `from ..config import Config`, with a hard-coded fallback if the import fails.

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `ACTOR_EXCLUDE_MEDIA` | `true` (env, `backend/app/config.py:1368`); fallback True | Media/observer rows with no explicit tier 1/2 are inferred as tier 3, which makes them not agent-eligible | `:898-904`, `:952-953` |
| `SIM_EVENT_REACT_BUFFER` | `true` (`backend/app/config.py:562`); fallback True | Compresses the hour-mode event mapping into `total_rounds - max(2, total_rounds//5)` rounds, so the farthest event leaves time for a reaction | `:1436-1443` |
| `ONTOLOGY_SEED_ADAPTIVE_BUDGET` | `true` (`backend/app/config.py:561`); fallback True | Extra entity types the LLM may add = `max(2, 8 - n_seed_types)`; otherwise fixed at 2 | `:2498-2504` |

Function parameters act as soft knobs. Defaults:

| Function | Parameter defaults | Anchor |
|---|---|---|
| `actor_briefing` | `max_memory_chars=600`, `max_intelligence_chars=2200` | `:510-511` |
| `actors_digest` | `max_actors=30`, `max_chars=4000` | `:600-601` |
| `situation_brief` | `max_actors=25`, `max_chars=6000` | `:1323` |
| `relationship_briefing` | `max_edges=6` | `:792` |
| `roster_block` | `max_per_bucket=5` | `:1151` |
| `sources_index_tiered` | `max_sources=40` | `:1585` |
| `sources_index_unified` | `max_sources=60` | `:1716` |
| `quantitative_facts_block` | `max_facts=20` | `:1802` |
| `contested_claims_block` | `max_claims=8` | `:1880` |
| `forecast_inputs_block` | `max_per_section=6` | `:2880` |
| `projected_edges_block` | `max_rows=14` | `:2865` |

Caller-side flags that decide whether these helpers are reached at all (not read in this slice):

| Flag | Default | Anchor |
|---|---|---|
| `ONTOLOGY_FROM_DOSSIER` | True | `backend/app/config.py:379` |
| `PERSONA_BEHAVIORAL_DNA` | True | `config.py:383` |
| `REPORT_RELATIONAL_ROSTER` | True | `config.py:409` |
| `REPORT_CITATION_SINGLE_GRAMMAR` | true | `config.py:251` |
| `REPORT_PROJECTED_EDGES` | False | `config.py:294` |
| `CAST_RECONCILE` | True | `config.py:372` |
| `SIM_DECISION_CHANNEL` | true | `config.py:1483` |
| `ONTOLOGY_RICH_SCHEMA` | True | `config.py:368` |

---

## External calls

- **None.** No LLM, HTTP, DB, subprocess or filesystem access anywhere in the slice. The only cross-module calls are:
  - `backend/app/utils/dates.parse_as_of` (`:1409`, `:1489`, `:2972`). Lenient date parser returning a UTC datetime or None; never raises (`backend/app/utils/dates.py:38-69`).
  - `backend/app/utils/sim_timeline.round_for_date` (`:1490`; definition `backend/app/utils/sim_timeline.py:491-510`).
  - `backend/app/config.Config` attribute reads (`:901`, `:1438`, `:2500`).

---

## Cross-module edges

**Inbound (production callers):**

| Caller | Helpers used | Anchor |
|---|---|---|
| `backend/app/services/pipeline_orchestrator.py` | `REL_LABEL`, `extract_relationship_rows`, `normalize_name`, `situation_brief`, `situation_brief_block`, `valid_scenario_distribution` (import `:69-76`); `reconcile_cast` (`:3928`, `:6462`); `forecast_inputs_from_report_markdown` (`:5772`); `normalize_name` (`:8360`, `:12663`); `extract_actor_rows` (`:11843`); `dossier_coverage` (`:12217`); `ontology_seed_block` (`:12340`); `world_state_seed_from_actors` (`:12881`) | see col. 2 |
| `backend/app/services/graph_builder.py` | `ACTOR_INTELLIGENCE_SCHEMA_VERSION`, `extract_actor_rows`, `extract_relationship_rows`, `actor_briefing`, `normalize_name`, `REL_EDGE_NAME`, `entity_archetype`, `entity_simulation_tier`, `salience_score`, `relation_valence`, `relation_polarity` | import `:25-37`; uses `:463`, `:719-727`, `:1375-1472`, `:2066` |
| `backend/app/services/zep_entity_reader.py` | `entity_archetype`, `entity_simulation_tier`, `is_agent_eligible`, `is_media_entity`, `match_actor` | import `:15-21`; uses `:79-88`, `:423-430` |
| `backend/app/services/simulation_manager.py` | `extract_actor_rows`, `is_agent_eligible`, `match_actor`, `normalize_name` (`:236-266`); `extract_actor_rows` (`:341`); `match_actor`, `influence_weight`, `salience_score`, `is_agent_eligible`, `entity_simulation_tier`, `normalize_name` in `select_agent_pool` (`:390-470`); `match_actor` (`:943`) | see col. 2 |
| `backend/app/services/oasis_profile_generator.py` | `ACTOR_INTELLIGENCE_SCHEMA_VERSION`, `actor_briefing`, `behavioral_dna_block`, `extract_actor_rows`, `influence_weight`, `match_actor`, `normalize_name`, `relationship_briefing`, `roster_block` | import `:24-34`; uses `:1621`, `:1679-1692`, `:2145-2153`, `:2302`, `:2359`, `:2445`, `:2468` |
| `backend/app/services/simulation_config_generator.py` | `actors_digest`, `build_initial_follow_graph`, `events_to_calendar_rounds`, `events_to_schedule`, `extract_actor_rows`, `extract_relationship_rows`, `forecast_inputs_block`, `influence_weight`, `match_actor`, `normalize_name`, `relation_polarity`, `relation_valence`, `situation_brief_block` | import `:24-38`; uses `:859`, `:1071`, `:1108`, `:1200`, `:1219`, `:1304`, `:1894`, `:1987`, `:1996`, `:2008`, `:2376`, `:2677`, `:2778` |
| `backend/app/services/report_agent.py` (lazy `from ..utils import actors as _actors`) | `quantitative_facts_block`, `forecast_inputs_block`, `contested_claims_block` (`:1886-1891`, `:2859`); `extract_actor_rows`, `extract_relationship_rows`, `is_agent_eligible`, `salience_score`, `relational_roster` (`:1924-1961`, `:2197-2199`, `:2626-2628`, `:2793-2800`); `sources_index_unified` (`:2245`); `sources_index_tiered` / `_map` (`:2255-2257`); `projected_edges_block` (`:2403`); `extract_forecast_inputs` (`:3174`, `:4814`) | see col. 2 |
| `backend/app/services/actor_dossier_compactor.py` | `actor_intelligence_claims`, `actor_intelligence_payload`, `entity_simulation_tier`, `normalize_name`, `salience_score` | import `:12-18`; uses `:66-70`, `:241-251` |
| `backend/app/services/actor_role_prompt.py` | `ACTOR_INTELLIGENCE_SCHEMA_VERSION`, `actor_intelligence_payload`, `has_unsupported_actor_intelligence_schema` | import `:18-22`; uses `:953`, `:968` |
| `backend/app/services/zep_entity_resolver.py` | `extract_actor_rows`, `normalize_name` | `:32`, `:61-92` |
| `backend/app/services/graph_pruner.py` | `normalize_name` | `:30`, `:67-129` |
| `backend/app/services/zep_tools.py` | `normalize_name`, `relation_polarity` | `:2604`, `:2633`, `:2678`, `:2777` |
| `backend/scripts/run_parallel_simulation.py` | `ACTOR_INTELLIGENCE_SCHEMA_VERSION` | `:589` |

- **Tests (17 files)** import the module, among them `backend/tests/test_cast_reconcile.py`, `test_dossier_coverage.py`, `test_ontology_refinements.py`, `test_projected_edges.py`, `test_sessionb_scenario_parser.py`, `test_worldstate.py`, `test_actor_cast_discipline.py`, `test_calendar_event_bucketing.py` and `test_wave9_citations.py` (`grep -rln "utils.actors" backend/tests`).
- **Mirror outside the backend:** `deerflow_bridge/linear_research.py:563-566` `_name_key` is a hand copy of `normalize_name`, using the same regex.

**Outbound:** `.dates.parse_as_of`, `.sim_timeline.round_for_date` and `..config.Config` only (see External calls).

**Public symbols with zero production callers:** `indicators_to_schedule` (`:2961`), `actor_grade` (`:1773`), `source_tier_histogram` (`:1570`), `SCENARIO_NAMES` (`:1929`), `CONTESTED_STATUS` (`:1845`), `SOURCE_TIERS` (used only internally), `ENTITY_ARCHETYPES` (internal only; mentioned in a comment at `backend/app/services/ontology_generator.py:306`). Also internal-only: `extract_source_rows`, `extract_quantitative_rows`, `extract_contested_rows`, `actor_intelligence_dimension`, `actor_intelligence_schema_version`. In addition, `ontology_from_actors` (`:2451`), `project_relationships` (`:2844`) and `actor_intelligence_dimension_presence` (`:350`) are reached in production only through other actors.py helpers; their only direct callers are tests.

---

## Invariants, gates, validation

- **Degrade-safe contract:** malformed input never raises and yields an empty value of the expected type. [verifier: refuted for `reconcile_cast`. An int `aliases` raises `TypeError` at the survivor key `len(r.get("aliases") or [])` (`:2393`). Dict-valued `source_refs` entries raise `TypeError: unhashable type` in `dict.fromkeys` (`:2248`). A string `aliases` is iterated per character, giving single-letter aliases (`:2396`, `:2406`; probe `"NVDA"` → `A, D, N, V`). Both callers catch the exceptions (`backend/app/services/pipeline_orchestrator.py:6461-6466`, `:12157`)] Examples: `extract_actor_rows` (`:182-187`), `extract_forecast_inputs` (`:1938-1948`), `events_to_calendar_rounds` (`:1492-1497`), `sources_index_unified` (`:1727-1740`).
- **Schema gate (fail closed):** an explicit non-v1 `intelligence.schema_version` makes the payload invisible (`:231-232`), and `actor_role_prompt` returns no role for that actor (`backend/app/services/actor_role_prompt.py:953-957`). Unversioned payloads are accepted as legacy (`:220-222`).
- **Agent-admission gate:** `is_agent_eligible` ⇔ tier ∈ {1,2} (`:967`). Tier priority:
  1. an explicit tier;
  2. archetype `source` → 3, other non-agent archetypes → 4;
  3. media → 3 when the flag is on;
  4. influence.

  Explicit tier 1/2 exempts a row from media demotion (`:915-916`). An explicit `archetype: "actor"` does **not** (probe: `{"type":"Media","archetype":"actor"}` → tier 3).
- **Identity safety in `match_actor`:**
  - exact/alias matches beat fuzzy matches (`:458-469`);
  - fuzzy containment requires both strings to be ≥4 chars (`:478`);
  - ambiguity returns None (`:468-469`, `:492`).
- **Merge safety in `reconcile_cast`:** containment needs a ≥4-char shorter name (`:2117`), and identical-token overlap always merges (`:2113`). A no-duplicate run returns the same object (`:2372-2373`).
- **Scenario partition invariants:**
  - `valid_scenario_distribution`: 1-6 unique names, all parseable, `|Σ−1| ≤ 0.02` (`:2567`, `:2576`, `:2588`, `:2591`).
  - `forecast_inputs_from_report_markdown`: 2-6 rows, `Σ ∈ [0.9, 1.1]` (`:2820-2829`).
  - `world_state_seed_from_actors` enforces neither.
- **Citation numbering invariant:** in `sources_index_unified`, `S<n>` is the raw 1-based position and stays stable even when rows are filtered (`:1664-1673`, `:1733`, `:1748`).
- **Bounded output:** every renderer caps item counts, and character counts where documented: `actors_digest` 4000 (`:658`), `situation_brief` 6000 (`:1393`), `actor_briefing` intelligence 2200 (`:586`), claims 260 (`:341`), evidence preview 280 (`:1709`).

---

## Failure modes & recovery

- **Config import failure** (standalone scripts, circular-import timing): each of the three flags falls back to True through a bare `except Exception` (`:903-904`, `:1440-1441`, `:2503-2504`). Behaviour stays at the defaults with no log.
- **Unparseable `as_of`:** `events_to_schedule` and `indicators_to_schedule` return `[]` (`:1413-1415`, `:2976-2978`). `events_to_calendar_rounds` returns `([], [])` (`:1496-1497`). The caller is responsible for warnings (`backend/app/services/simulation_config_generator.py:1078-1085`).
- **Unresolvable or ambiguous actor names:** `match_actor` → None. Downstream:
  - `build_initial_follow_graph` treats influence as 1.0 (`:1290-1291`);
  - `select_agent_pool` treats the entity as unmatched;
  - zep_entity_reader leaves the node unclassified (kept).
- **Duplicate-merge failure:** `reconcile_cast` does not catch internally. `merge_actors_objs` catches any exception and falls back to the un-deduplicated union (`backend/app/services/pipeline_orchestrator.py:6461-6466`).
- **Report fallback parser:** a messy candidate section does not stop the search; later sections are tried (`:2824-2829`). If none qualify the result is `{}`, and the orchestrator logs a loud "world_state 种子为空" warning (`pipeline_orchestrator.py:12891-12895`). [verifier: the warning fires only when `world_state_seed_from_actors(actors)` then has no scenario names (`pipeline_orchestrator.py:12890-12894`). A name-only or invalid scenario list that the gate rejected still seeds names, with `uniform_prior=True` or with unnormalized rates, so no warning is logged (`:2628-2678`)]
- **Empty everything:** `world_state_seed_from_actors` returns `uniform_prior=True` instead of silently assuming 50/50 (`:2675-2678`).

---

## Surprises

Items marked **(suspected)** are possible bugs. I have not fixed any of them.

1. **(suspected) Alias-written relationship endpoints are kept but invisible to per-actor helpers.** `extract_relationship_rows` accepts endpoints that match an alias (`:750-752`). However, `relationship_briefing` (`:807-812`), `relational_roster` (`:1115-1117`) and `build_initial_follow_graph` (`:1282-1286`, with name-keyed maps) compare only against `normalize_name(actor_name)`. Probe: with `NVIDIA Corp (aliases: NVDA)`, an edge `NVDA OPPOSES AMD` passes the filter, but NVIDIA's roster and briefing are empty and no follow edge is created. `reconcile_cast` rewrites only *victim names*, not aliases, so it does not fix this (`:2425-2428`, `:2441-2444`).
2. **(suspected) The `supporters` roster bucket is direction-inverted.** The comment says supporters are the *source* of SUPPORTS/ENDORSES (`:1062`), but the rule uses `"out"` (`:1063`), which adds the *target*. Probe: `Fan SUPPORTS Star` puts **Star** in Fan's `supporters` (rendered as `支持者：Star`), while Star only sees Fan under `allies`.
3. **(suspected) Rate-parsing inconsistency between the gate and the seed.**
   - `valid_scenario_distribution` parses `{"probability": "45%"}` with `_parse_probability_value` and accepts it (`:2580-2587`). The orchestrator then skips the report fallback.
   - `world_state_seed_from_actors` parses bare keys with `float(v)` (`:2645-2650`), which fails on `"45%"`. Without a `probability_band` the rate is missing, and with all rates missing the result is `uniform_prior: True`.
   - Conversely, `{"probability": 45}` is rejected by the gate but seeded as `45.0` without normalization (probe `ws2`).
   - The tolerances also differ: the report parser accepts Σ ∈ [0.9, 1.1], the gate needs ±0.02 (`:2824` vs `:2591`). A report-derived seed with Σ=0.95 is injected but still counts as "missing" when re-checked.
4. **(suspected) `_parse_probability_value` misreads odds, ratios and years.** `"1 in 4"` → 0.025, `"3 of 10 years"` → 0.065, `"1.5"` → 0.015, and `"2030: 40%"` → None. The cause: the mean is taken over *all* numbers, and the percent mode fires whenever any number exceeds 1 (`:2539-2551`).
5. **(suspected) Intelligence shapes that presence counts but renderers drop.**
   - `operational_preferences` as `{likes, dislikes}` and `decision_rights_process_triggers` as `{decision_rights, triggers, …}` are not `{claims/items/entries}`. `actor_intelligence_dimension` returns the dict (`:249-250`) and `actor_intelligence_claims` finds no `claim` key, so nothing renders. Meanwhile `actor_intelligence_dimension_presence` reports both as present (`:361-371`).
   - A dimension of `{"claims": []}` also counts as present (`:245-250`, then `bool(dict)`), which inflates `dossier_coverage`. [verifier: true for every presence key except `preferences`. For `operational_preferences`, a dict value is tested only for `likes`/`dislikes`, so `{"claims": []}` gives False (`:364-365`; probe). Related gap: the renderer reads only `claim`/`finding`/`description`/`text` (`:292-298`), while `_claim_merge_key` also accepts `event`/`action`/`plan`/`investment`/`capability`/`subject` (`:2147-2151`). A row such as `{"action": ...}` therefore counts as present but renders nothing]
   - The merge path does understand these shapes (`:2166-2188`), so renderers and merging disagree.
6. **(suspected) `reconcile_cast` drops intelligence data and invalid rows.**
   - `_merge_actor_intelligence` rebuilds only the 17 `_INTELLIGENCE_DIMENSION_ALIASES` dimensions plus gaps, refs, coverage and provenance. It drops `context_pack`, `relevant_report_context` and custom dimensions (probe: `report_context` presence True → False). It also adds an empty `evidence_gaps: {}` (`:2278-2295`).
   - When any merge happens, `out["actors"] = new_rows` silently drops non-dict and nameless rows that the no-merge path would have kept (`:2346`, `:2432`).
   - Case-only differences in claim text are logged as `claim` conflicts (probe).
7. **(suspected) Containment false merges and matches.** `_rows_same_entity` merges `Meta` into `Metaculus` (`:2117`; probe), and `match_actor("Metaculus Inc")` → `Meta` (`:478-479`). [verifier: the `match_actor` false positive needs a roster without a `Metaculus` row. With both rows present the longest surface wins and `Metaculus` is returned (`:484-492`; probe). A merge of two rows that share an edge also turns that edge into a self-loop (probe: `Meta ALLY_OF Metaculus` → `Metaculus ALLY_OF Metaculus`, `:2441-2444`)] The ≥4-char guard does not prevent prefix collisions between different entities. Union-find makes this transitive (`:2360-2365`). The orchestrator applies the merge for legacy casts (`pipeline_orchestrator.py:12158-12165`), and PAR-2's `merge_actors_objs` always applies it (`pipeline_orchestrator.py:6462-6463`). `merge_actors_objs` calls `reconcile_cast` directly, without the sealed-v1 guard in `_reconcile_research_cast`.
8. **(suspected) `match_actor` exact-match ambiguity check misses same-normalized duplicates.** The exact pass keys by canonical normalized name, so two distinct rows that both normalize to `xcorp` return the *last* row instead of None (`:461-467`; probe).
9. **(suspected) Media keyword demotion is substring-based over `description` too.** A Government regulator described as "often criticized by journalists", and a politician whose role is "newspaper owner and politician" with `influence: high`, are both inferred as tier 3 and excluded from the agent pool (`:922-925`; probes). Only an explicit `simulation_tier` of 1 or 2 overrides this.
10. **Tier inference quirk.** Unparseable or missing `influence` gives tier **1**, while `"medium"`/`"low"` give tier 2 (`:955-958`). A row with *no* signal therefore outranks a row with a known medium influence. `influence_weight` uses first-key substring matching in dict order, so `"medium-high"` → high, `"highly uncertain"` → high, `"low-medium"` → medium (`:502-504`). `_explicit_simulation_tier("12")` → 1 (`:891-894`).
11. **(suspected) `_norm_tier` accepts any digit 1-4 anywhere.** `"10"` → S1, `"B2"` (an Admiralty grade placed in `tier`) → S2, `"2026-05-01"` → S2 (`:1550`). Bridge and orchestrator tier histograms use strict matching instead (`deerflow_bridge/deerflow_research.py:9197-9204`, `backend/app/services/pipeline_orchestrator.py:6495-6503`). [verifier: the bridge uses exact membership in `("S1".."S4")` (`deerflow_bridge/deerflow_research.py:879`, `:9201`). The orchestrator's `_track_tier_rank` uses a prefix-anchored `re.match(r"[sS]([1-4])")`, so `"S12"` → rank 1. It is stricter than `_norm_tier` but not a full match (`backend/app/services/pipeline_orchestrator.py:5984-5991`)]
12. **Same-day events differ between modes.** `events_to_schedule` keeps events dated on `as_of` (span ≥ 0, `:1428`, `:1453`). `events_to_calendar_rounds` drops `d <= as_of` (`:1513`), yet its docstring says this "follows events_to_schedule's existing policy" (`:1480`). Also, `indicators_to_schedule` lacks the PREP-5 react buffer (`:3002` vs `:1456`).
13. **Rendering inconsistencies.**
    - `relationship_briefing` prints empty parentheses `盟友（）` when `strength` is missing (`:810`; probe).
    - `situation_brief` ignores `relation_label` for `OTHER` edges, while `relationship_briefing` uses it (`:1367` vs `:803-806`).
    - `ontology_from_actors` gives a label-derived edge such as `FUNDS` (from OTHER) the valence `neutral` rather than `transactional` (`:2476`).
    - `forecast_inputs_block` shows only `probability_band`, so point `probability` values, including every point estimate written by `forecast_inputs_from_report_markdown` (`:2761`), are omitted. It also lower-cases non-standard scenario names (`:2944-2945`; probe: `"NVIDIA Holds"` → `nvidia holds`).
    - `report_agent` re-implements the roster bucket labels (omitting `dependents`; `backend/app/services/report_agent.py:1941-1951`) instead of reusing `_ROSTER_BUCKET_LABEL` (`:1137-1148`).
14. **Dead / unused code.**
    - `indicators_to_schedule` (`:2961`), `actor_grade` (`:1773`) and `source_tier_histogram` (`:1570`) have no callers at all, including tests. `source_tier_histogram` also emits `untiered_count` where the bridge and orchestrator use `s_unknown` (`deerflow_bridge/deerflow_research.py:9194`, `backend/app/services/pipeline_orchestrator.py:6497`).
    - `SCENARIO_NAMES` (`:1929`) and `CONTESTED_STATUS` (`:1845`) are never read.
15. **Duplicated logic.**
    - `deerflow_bridge/linear_research.py:563-566` hand-copies `normalize_name`.
    - `zep_entity_resolver._name_match` claims to mirror `match_actor` but uses a ≥2-char containment guard, not ≥4 (`backend/app/services/zep_entity_resolver.py:110-120`).
    - `zep_entity_resolver.actor_alias_map` re-implements `_actor_norm_aliases` (`zep_entity_resolver.py:65-95`).
    - `pipeline_orchestrator._actor_explicit_simulation_tier` mirrors `_explicit_simulation_tier` but uses `re.fullmatch(r"[1-4]")`, which is stricter (`pipeline_orchestrator.py:3950-3961` vs `:891-894`).
16. **Doc-vs-code drift.**
    - **Function index:** the module docstring index (`:98-118`) omits about 20 public helpers, including `influence_weight`, `situation_brief`, `sources_index_unified`, `sources_index_tiered_map`, `dossier_coverage`, `reconcile_cast`, `ontology_seed_block`, `valid_scenario_distribution`, `world_state_seed_from_actors`, `forecast_inputs_from_report_markdown`, `projected_edges_block` and all `actor_intelligence_*`. [verifier: the exact count is 24 of 51 public functions missing (AST scan of the docstring at `:98-118` against every top-level `def`). The index also omits `normalize_name`, `extract_actor_rows`, `extract_source_rows`, `actor_grade`, `ontology_from_actors`, `project_relationships` and `indicators_to_schedule`]
    - **Relationship types:** the contract docstring lists 21 types (`:50-52`) but omits the 5 causal types present in `REL_EDGE_NAME` (`:694-698`).
    - **`match_actor` docstring:** it says "exact → containment → alias" (`:447-449`), but the code checks aliases in the *first* (exact) pass and also in the fuzzy pass (`:464`, `:476`).
    - **"Single reader" claim:** the claim that all consumers read only through this module (`:122`) is false. Examples: `backend/app/services/simulation_manager.py:341-345` reads `row["intelligence"]` directly; `backend/app/services/oasis_profile_generator.py:1709` reads `actors.get("situation_brief")`; `backend/app/services/graph_pruner.py:65` reads `actors["actors"]` directly.
    - **Media-demotion comment in config:** `backend/app/config.py:1363-1367` says "explicit simulation_tier/archetype annotation still takes priority", but an explicit `archetype: "actor"` does not prevent media demotion (`:945-953`). [verifier: the comment is half right. Explicit non-agent archetypes do take priority over the media branch, returning 3 for `source` and 4 for others before media is checked (probe: `{type: Media, archetype: institution_rule}` → tier 4). Only `actor`/`collective` cannot shield a row (`:945-953`)]
    - **`ONTOLOGY_FROM_DOSSIER` default:** the orchestrator comment calls it "默认关" (default off) (`backend/app/services/pipeline_orchestrator.py:12336`), but config defaults it to `True` (`backend/app/config.py:379`).
    - **Stale line anchors:** `DRF_ARCHITECTURE.md:792-796` cites `entity_archetype :515`, `entity_simulation_tier :581`, `is_agent_eligible :614`, `salience_score :623`, `is_media_entity :560` and `match_actor :172`. The actual lines are 862, 928, 961, 970, 907 and 445. `DRF_ARCHITECTURE.md:1018` cites `world_state_seed_from_actors` at `:1842`; it is at `:2613`.
17. **Cross-module (outside slice, related):**
    - `inject_forecast_inputs_from_report` replaces the *whole* `actors["forecast_inputs"]` with the parsed `{scenarios, base_rates: []}`. Any research drivers, indicators or base_rates that existed alongside invalid scenarios are lost (`backend/app/services/pipeline_orchestrator.py:5781`).
    - `report_agent` gates on `RESEARCH_FORECAST_INPUTS` and `RESEARCH_EVIDENCE_GRADING` via `getattr(Config, ..., True)` (`backend/app/services/report_agent.py:1875`, `:1890`). Neither attribute is defined on `Config`, which has no `__getattr__`, so the env vars documented in `.env.example:324-325` cannot switch those report blocks off.

---

## Verification

An adversarial verifier re-checked this map against the code on `main` on 2026-10-11. Method:
- Read all 3006 lines of `backend/app/utils/actors.py`.
- Grepped every cross-module anchor the map cites.
- Re-ran the pure helpers on small fixtures. The module was loaded in isolation under a fake parent package, so the `..config` import failed and every flag took its fallback value. Bytecode writing was off, and no app config or `.env` was loaded.

Inline `[verifier: …]` notes above mark the statements that were corrected.

**Verdict counts** (38 verdicts in total):

| Group | Checked | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims | 15 | 13 | 2 | 0 |
| Surprises | 17 | 13 | 4 | 0 |
| Walkthrough / control-flow spot checks | 6 entries (1 roll-up of confirmed checks + 5 corrections) | 1 roll-up | 3 | 2 |

### Non-confirmed key claims and surprises

1. **`match_actor` fuzzy tie (imprecise).** The fuzzy pass returns None only when the longest-surface candidates map to more than one distinct canonical. A tie between surfaces of the *same* canonical returns that row (`:484-492`).
2. **`reconcile_cast` survivor (imprecise).** The survivor is `max` over `(richness, len(aliases), len(name))`. When all three tie, the first of the tied rows in cluster order wins (`:2391-2394`). "Most truthy `_RICH_KEYS`" is only the first key of that tuple.
3. **`{'claims': []}` counted as present (imprecise).** This is true for every presence key except `preferences`, which tests a dict value only for `likes`/`dislikes` (`:364-365`).
4. **Meta / Metaculus (imprecise).** `match_actor("Metaculus Inc")` returns Meta only when the roster has no Metaculus row. With both rows present the longest surface wins (`:484-492`). The `merge_actors_objs` bypass of the sealed-v1 guard is confirmed (`backend/app/services/pipeline_orchestrator.py:6461-6463` vs `:3917-3946`).
5. **Doc drift: function index (imprecise).** The index omits 24 of 51 public functions, not "about 20". The other drift items are confirmed: the single-reader claim at `:122`, the missing causal edge types at `:50-52`, the `match_actor` docstring at `:447-449`, and the stale `DRF_ARCHITECTURE.md:792-796,1018` anchors.
6. **Config/comment drift (imprecise, two parts overstated).**
   - The `config.py:1365-1366` comment is half right. Explicit non-agent archetypes *do* take priority over media demotion (`:945-949`); only `actor`/`collective` cannot shield a row.
   - The `.env.example` switches `RESEARCH_FORECAST_INPUTS` / `RESEARCH_EVIDENCE_GRADING` are not inert. The bridge reads them through `_env_flag` (`deerflow_bridge/deerflow_research.py:8474-8476`). They only fail to gate the report_agent blocks, because `Config` never defines them (`backend/app/services/report_agent.py:1875`, `:1890`, `:2252`).
   - The `ONTOLOGY_FROM_DOSSIER` "默认关" drift is confirmed (`backend/app/services/pipeline_orchestrator.py:12336` vs `backend/app/config.py:379`).

### Corrected walkthrough / control-flow statements

1. **"there are no raises" (imprecise).** There are zero `raise` statements, and the fail-closed rule returns `{}`; it does not raise (`:230-232`).
2. **`REL_EDGE_NAME` "8 legacy" identity entries (imprecise).** Seven legacy types are identity-mapped; `OTHER` → `RELATES_TO` (`:669-675`, `:701`).
3. **`dossier_coverage` "32 keys" (refuted).** It has 34 keys, and the walkthrough omits `pct_actors_with_actor_intelligence` (`:1962-1992`, `:2064`).
4. **"malformed input never raises" (refuted).** `reconcile_cast` raises `TypeError` on an int `aliases` (`:2393`) and on dict-valued `source_refs` entries (`:2248`). It also explodes a string `aliases` into single characters (`:2396`, `:2406`).
5. **Loud warning on parser failure (imprecise).** The warning fires only when the final seed has no scenario names (`backend/app/services/pipeline_orchestrator.py:12890-12894`).

The roll-up of confirmed spot checks:
- `normalize_name` probes; `actor_briefing`'s 11 dimensions and the 220/260 gap caps.
- `relation_polarity` probes; `events_to_schedule` round 8 for a one-year event; `_norm_tier` probes.
- The 18 critical dimensions and the 17 merge-alias dimensions; `evidence_gaps: {}` added on merge.
- The citation-match thresholds (12/8 chars); `S?` tags past 26.
- The `round_for_date` semantics; the report_agent roster labels omitting `dependents`.
- The 17 importing test files; the orchestrator anchors `:6433`, `:11650`, `:12158`, `:12217`, `:12239`, `:12881`.

### Omissions (significant behaviour the map did not cover)

1. **(suspected) A merge stamps legacy intelligence as v1.** `_merge_actor_intelligence` always writes `schema_version: actor-intelligence/v1` into the merged payload, even when every source payload was unversioned legacy (`:2222-2225`).
   - After a legacy merge, the row-level v1 detectors treat the whole dossier as canonical v1: `backend/app/services/simulation_config_generator.py:1392-1408` and `backend/app/services/simulation_manager.py:321-347`.
   - `dossier_coverage` also starts counting the merged row as explicit v1 (`:2015-2019`).
2. **`reconcile_cast` can create self-loop relationships.** If two merged rows had an edge between them, both endpoints are rewritten to the canonical name and the loop is kept (`:2441-2444`; probe: `Meta ALLY_OF Metaculus` → `Metaculus ALLY_OF Metaculus`).
   - `build_initial_follow_graph` skips self-loops (`:1288`).
   - `situation_brief` (`:1365-1375`) and `relationship_briefing` (`:809-810`) still render them.
3. **`reconcile_cast` alias handling is not type-guarded** (`:2393`, `:2396`, `:2406`).
   - A string `aliases` is split into single-character aliases, and those then enter `extract_relationship_rows` and `match_actor`'s exact pass.
   - A non-iterable `aliases` raises. Unhashable ref entries raise at `:2248`.
4. **`world_state_seed_from_actors` bare-key path accepts invalid values.** `float(v)` accepts bools (`True` → 1.0), negatives and values above 1 (`:2645-2646`). Names are de-duplicated by raw string, not normalized form (`:2636`), unlike `valid_scenario_distribution` (`:2575-2577`).
5. **`events_to_schedule` clamps rather than drops beyond-horizon events.** With an explicit `horizon_days`, events past the horizon land on the last round (`:1456`; probe: 365-day event, horizon 30 → round 9). This is latent today: the production caller passes no `horizon_days` (`backend/app/services/simulation_config_generator.py:1108`).
6. **Renderer and merge-key disagree on claim fields.** `actor_intelligence_claims` renders only `claim`/`finding`/`description`/`text` (`:292-298`). `_claim_merge_key` also accepts `event`/`action`/`plan`/`investment`/`capability`/`subject` (`:2147-2151`). Rows keyed only by those fields count toward presence but render nothing.
