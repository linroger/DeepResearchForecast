# sim-profiles — OASIS profile generator and OASIS LLM util

Slice files (read in full, main branch checkout on disk):

- `backend/app/services/oasis_profile_generator.py` (3,264 lines)
- `backend/app/utils/oasis_llm.py` (616 lines)

All anchors are `path:line` relative to the repo root. In the walkthrough, `opg` stands for `backend/app/services/oasis_profile_generator.py` and `ollm` stands for `backend/app/utils/oasis_llm.py`.

---

## Purpose & position in the pipeline

The two files sit in Stage 4 (PREPARE) and Stage 5 (RUN) of the pipeline.

- **`oasis_profile_generator.py` (PREPARE).** This file turns graph entities (`EntityNode`s from `ZepEntityReader`, `backend/app/services/zep_entity_reader.py:127`) into OASIS agent profiles. It writes them to the two OASIS on-disk formats: `reddit_profiles.json` (a JSON array) and `twitter_profiles.csv` (columns `user_id,name,username,user_char,description`). Next to each profile file it writes a sealed `*_roles.json` manifest. The manifest binds every researched actor's deterministic role prompt (`actor-role/v2`, from `actor_role_prompt.py`) to the exact bytes OASIS will load.
  - **Legacy (pre-v1) actors and non-actor entities.** These get an LLM-written or rule-written base persona. The compiled role prompt is appended to it.
  - **Canonical actors (`actor-intelligence/v1`).** These skip the LLM and the graph retrieval entirely. Their whole persona is the role prompt.
  - **Callers.** `SimulationManager.prepare_simulation` calls it (`backend/app/services/simulation_manager.py:1046-1131`). The prepare-ready check (`backend/app/api/simulation.py:314-329`), the runner launch gate (`backend/app/services/simulation_runner.py:689-757`) and the OASIS child process (`backend/scripts/run_parallel_simulation.py:576-627`) call it again to validate the files.
- **`oasis_llm.py` (RUN).** This file builds the CAMEL model object that OASIS agents use inside the simulation subprocesses (`backend/scripts/run_parallel_simulation.py:1722-1735`, `run_twitter_simulation.py:740`, `run_reddit_simulation.py:748`).
  - **CLI providers** (`claude-cli`/`codex-cli`) are wrapped in `CLIModel`. `CLIModel` proxies each request through `LLMClient` and emulates OpenAI function calling with a JSON-in-prompt protocol.
  - **HTTP providers** go through CAMEL `ModelFactory` (OpenAI platform). Guards are monkey-patched on, plus kimi UA injection and an `extra_body` that disables reasoning.
  - **Concurrency.** It also supplies the per-platform OASIS semaphore.

---

## Walkthrough (source order)

### A. `backend/app/services/oasis_profile_generator.py`

#### Module header and imports (`opg:1-56`)
- The docstring at `opg:1-9` says the module enriches nodes via Zep retrieval, uses detailed persona prompts, and separates individual from group entities.
- `Zep` is imported from the local Graphiti facade at `opg:21` (not zep_cloud).
- Actor helpers come from `utils/actors.py` (`opg:24-34`). Atomic writers come from `utils/atomic.py` (`opg:35`) and `LLMClient` from `opg:36`.
- The role-contract compiler and sanitizers are imported from `actor_role_prompt.py` (`opg:38-46`). Actor-context helpers come from `actor_context.py` (`opg:47-53`).
- `EntityNode, ZepEntityReader` are imported at `opg:54`. **`ZepEntityReader` is never used.** It appears only in a docstring at `opg:1122`.
- The logger is named `mirofish.oasis_profile` (`opg:56`).

#### `CANONICAL_REDDIT_SYSTEM_MESSAGE_VERSION` and `canonical_reddit_system_message(username, role_prompt)` (`opg:59-86`)
- The version string is `"canonical-reddit-system-message/v1"` (`opg:59`).
- The function returns a fixed f-string system message for canonical v1 actors: OBJECTIVE / SELF-DESCRIPTION / RESPONSE METHOD. It contains `Your name is {name}.` and `Your have profile: {role}.` (`opg:75-86`).
- It raises `ValueError` if either the username or the role is blank after `str().strip()` (`opg:71-74`).
- Purpose (docstring `opg:63-69`): OASIS' bundled Reddit template appends age, gender, MBTI and country. For canonical actors, the child process replaces the template with this message and attests the bytes (`backend/scripts/run_parallel_simulation.py:615-620`).
- No side effects.

#### `@dataclass OasisAgentProfile` (`opg:89-272`)
- **Fields**
  - Common fields: `user_id, user_name, name, bio, persona` (`opg:93-97`).
  - Reddit field: `karma=1000` (`opg:100`).
  - Twitter fields: `friend_count=100`, `follower_count=150`, `statuses_count=500` (`opg:103-105`).
  - Optional demographics: `age, gender, mbti, country, profession, interested_topics` (`opg:108-113`).
  - Source fields: `source_entity_uuid/type` (`opg:116-117`).
  - `created_at` is today as `%Y-%m-%d` (`opg:119`).
  - `generation_path` defaults to `"llm"`. Values are `"llm"`, `"rule"`, `"rule_fallback"`, `"error_stub"` or `"canonical_role"` (`opg:123`, `opg:728`).
  - `persona_design` (`opg:128`).
  - Role fields: `role_contract`, `role_prompt`, `role_prompt_sha256`, `role_prompt_max_chars` (`opg:134-137`).
  - Actor-context binding fields: `actor_context_file/_sha256/_manifest_sha256/_report_sha256` (`opg:141-144`).
- **`_canonical_role_only_persona()`** (`opg:146-174`)
  - Returns `None` unless `role_contract.schema_version == ROLE_CONTRACT_VERSION` (`"actor-role/v2"`, `backend/app/services/actor_role_prompt.py:30`) and `actor_intelligence_schema_version == "actor-intelligence/v1"` (`backend/app/utils/actors.py:190`) (`opg:157-163`).
  - Otherwise it returns `role_prompt`. It raises if the prompt is empty (`opg:165-168`) or if `sha256(prompt)` differs from `role_prompt_sha256` (`opg:169-173`).
  - This is the final serialization guard: a mutated `profile.persona` is ignored for canonical actors.
- **`to_reddit_format()`** (`opg:176-203`) and **`to_twitter_format()`** (`opg:205-234`)
  - Both return dicts with `username` (not `user_name`). The persona is the canonical role or `self.persona`.
  - Reddit adds `karma`. Twitter adds `friend_count/follower_count/statuses_count`.
  - Both add demographics/profession/topics only when truthy.
  - Only the `/generate-profiles` API route uses them (`backend/app/api/simulation.py:1459-1464`). The on-disk writers are `_save_reddit_json` and `_save_twitter_csv`.
- **`to_dict()`** (`opg:236-272`) returns the full dict. It adds `other_info.persona_design` and `other_info.actor_role{contract,prompt_sha256,prompt_chars}` when present (`opg:261-271`).

#### `class OasisProfileGenerator` constants (`opg:275-343`)
- `MBTI_TYPES`: all 16 types (`opg:288-293`).
- `COUNTRIES`: 11 countries (`opg:296-299`).
- `INDIVIDUAL_ENTITY_TYPES`: student, alumni, professor, person, publicfigure, expert, faculty, official, journalist, activist (`opg:302-305`).
- `GROUP_ENTITY_TYPES` (`opg:308-311`). Only the unused `_is_group_entity` reads it.
- `MARKET_AWARE_ENTITY_TYPES`: analyst, expert, journalist, columnist, commentator, pundit, researcher, economist, strategist, mediaoutlet, media (`opg:317-321`).
- `RELATIONSHIP_EDGE_TYPES`: ALLY_OF, OPPOSES, COMPETES_WITH, REGULATES, DEPENDS_ON, PARTNERS_WITH, INFLUENCES (`opg:326-329`).
- `PERSONA_DESIGN_KEYS`: identity, views_beliefs, incentives, objectives, relations, constraints_red_lines, decision_style, rhetoric (`opg:334-343`).

#### `__init__(api_key, base_url, model_name, zep_api_key, graph_id, provider, persona_language)` (`opg:345-386`)
- **Persona language.** If `persona_language is None` and **`os.environ["SIM_ACTIVITY_PROFILE"]`** (read directly, not via Config) is `us_business` or `global_market`, it sets `persona_language="en"` (`opg:358-362`).
- **Provider settings.** Provider is `provider or Config.LLM_PROVIDER or "claude-cli"`, lower-cased (`opg:364`). Key, URL and model fall back to `Config.LLM_API_KEY/LLM_BASE_URL/LLM_MODEL_NAME` (`opg:365-367`).
- **LLM client.** It builds `self.llm = LLMClient(...)` eagerly (`opg:370-375`). For an HTTP provider without an API key, `LLMClient.__init__` raises (`backend/app/utils/llm_client.py:276`, `286-290`). In that case even a `use_llm=False` generator cannot be constructed.
- **Graph client.** It builds `self.zep_client = Zep(api_key=...)` when a key exists. `Config.ZEP_API_KEY` defaults to `'local-graphiti'` (`backend/app/config.py:1038`), so a client is effectively always attempted. A construction failure is only a warning (`opg:378-386`).
- **Instance attributes set by the caller after construction** (`backend/app/services/simulation_manager.py:1050-1058`), not in `__init__`: `role_dossier_sha256`, `role_cast_manifest_sha256`, `actor_context_bindings`, `actor_context_manifest_sha256`, `actor_context_report_sha256`. All are read with `getattr(..., default)`.

#### `_bind_actor_context_provenance(role_contract, actor, context_pack)` (`opg:388-432`)
- If `context_pack` is not a dict, it returns `{}` (`opg:395-396`).
- It raises `ValueError` in these cases:
  - the role contract or actor is missing (`opg:397-398`);
  - `context_pack.actor_id != actor_id_for(actor)` (`opg:399-401`);
  - the binding `file/sha256`, the manifest sha or the report sha is empty (`opg:402-411`);
  - `context_pack.source.report_sha256 != self.actor_context_report_sha256` (`opg:412-414`).
- **Side effect:** it mutates `role_contract["provenance"]`, adding `context_pack_sha256` (`canonical_json_sha256`), `context_pack_file_sha256`, `manifest_sha256`, `actors_sha256`, `report_sha256`, `actor_intelligence_sha256`, `dossier_sha256`, `source_catalog_sha256` and `actor_ids_sha256` (`opg:415-431`).
- It returns the binding dict (`file`, `sha256`, …).

#### Canonical-v1 detection helpers (`opg:434-472`)
- `_explicit_actor_intelligence_schema(actor)` returns `actor.intelligence.schema_version` stripped, or `""` (`opg:434-441`).
- `_uses_canonical_actor_intelligence(actor)` returns true when that value equals `actor-intelligence/v1` (`opg:443-452`).
- `_dossier_uses_canonical_actor_intelligence(actors)` returns true if `actors.actor_intelligence_contract.schema_version == v1` **or any** row in `extract_actor_rows(actors)` is v1 (`opg:454-472`). One v1 row switches the **whole run** to canonical mode.

#### `_validated_canonical_batch_context(*, entity, actor, actors, actor_context_packs)` (`opg:474-595`)
This is a pre-flight check for each selected entity in a canonical run. It runs before the thread pool. It raises `ValueError` when:
- the actor is not a dict (the entity has no matched actor) (`opg:490-494`);
- the actor is not v1 (`opg:495-499`);
- the dossier is missing (`opg:500-501`);
- the pack for `actor_id_for(actor)` is missing (`opg:503-512`), or its schema is not `actor-context/v1` (`opg:513-516`);
- the pack's actor_id or normalized name differs from the actor (`opg:517-522`);
- `canonical_json_sha256(actor.intelligence) != canonical_json_sha256(pack.actor_intelligence)` (`opg:524-536`);
- the pack provenance is missing, or `source.actor_intelligence_contract_version`, `actor_intelligence_sha256` or `actors_sha256` (= sha of the whole `actors` dict) mismatch (`opg:538-557`);
- `source.report_sha256` differs from the generator's report sha (`opg:558-561`);
- the persisted binding is missing fields or its identity mismatches (`opg:563-579`);
- the re-serialized pack hash differs from `binding.sha256` (`opg:580-590`). The hash is `json.dumps(indent=2, ensure_ascii=False, default=str, allow_nan=False)`, which matches the writer at `backend/app/services/actor_context.py:1451-1454`;
- the manifest sha is empty (`opg:591-594`).

It returns the pack.

#### `_reject_unsupported_actor_intelligence(actor)` (`opg:597-607`)
Raises `ValueError("unsupported actor intelligence schema …; refusing legacy persona downgrade")` when an explicit schema version is present and is not v1. It is called first by every persona path (`opg:714`, `opg:874`, `opg:1572`, `opg:1665`, `opg:2128`).

#### `_canonical_actor_role_profile(*, entity, user_id, actor, actors, context_pack, generation_path)` (`opg:609-686`)
- It calls `build_actor_role_contract(actor, actors, context_pack)` and requires `actor-role/v2` plus a v1 intelligence version, otherwise it raises (`opg:629-637`).
- It binds provenance (`opg:638-640`).
- It reads `max_chars = resolve_actor_role_prompt_max_chars()`: env `SIM_ACTOR_ROLE_PROMPT_MAX_CHARS`, default 6000, clamped to [1800, 12000] (`backend/app/services/actor_role_prompt.py:2017-2027`). Then it compiles the prompt and raises if the result is empty (`opg:641-648`).
- **Profile contents**
  - `name` is the sanitized `role_contract.actor_name` or the entity name (240 chars).
  - `bio` is the structural `"{type}: {name}"` (500 chars).
  - `persona` is the role prompt. `profession` and `source_entity_type` are the sanitized entity type.
  - There are **no demographics, no topics, and default counts** (`opg:650-686`).
- **No LLM call and no graph retrieval.**

#### `generate_profile_from_entity(entity, user_id, use_llm=True, actor=None, actors=None, context_pack=None)` (`opg:688-863`)
1. Rejects an unsupported schema (`opg:714`). Entity type is `entity.get_entity_type() or "Entity"`, i.e. the first label that is not Entity/Node (`backend/app/services/zep_entity_reader.py:150-155`) (`opg:715`).
2. **Canonical branch** (`opg:721-729`): returns `_canonical_actor_role_profile(..., generation_path="canonical_role")` before any context build.
3. **Legacy path**
   - `user_name` comes from `_generate_username(name)` (`opg:733`). Context comes from `_build_entity_context(entity)`, which may do network graph searches (`opg:736`).
   - If an actor matched, all prompt inputs are sanitized: `sanitize_untrusted_dossier` on actor and actors; the name is limited to 240 chars, type to 160, summary to 4000, context to 12000; the username is regenerated from the sanitized name (`opg:743-758`).
4. When `use_llm` is set, it calls `_generate_profile_with_llm(...)` and pops `_generation_path` (default `"llm"`) (`opg:760-774`). Otherwise it calls `_generate_profile_rule_based(...)` with `generation_path="rule"` (`opg:775-785`).
5. Demographics (`age/gender/mbti`) are kept **only if** `_is_individual_entity(entity_type)`. `country` is kept for all (`opg:793-796`).
6. `persona_design` is popped from the profile data. A non-dict or empty value becomes `None` (`opg:800-802`).
7. **Role compilation after generation** (`opg:808-829`): `build_actor_role_contract` → `_bind_actor_context_provenance` → `compile_actor_role_prompt`.
   - If a role prompt exists, the base persona is sanitized (default 12000 chars) and the bio limited to 500. The persona becomes `"{base}\n\n{role_prompt}"`.
8. **Return value** (`opg:831-863`): `OasisAgentProfile`.
   - `karma/friend_count/follower_count/statuses_count` come from `profile_data` or **`random.randint`**: 500-5000, 50-500, 100-1000 and 100-2000 respectively (`opg:837-840`).
   - `name` and `source_entity_type` use the sanitized values only when a role prompt exists (`opg:834`, `opg:848`).

#### `_error_stub_profile(entity, user_id, actor, actors, context_pack)` (`opg:865-926`)
- **Canonical actors** go through `_canonical_actor_role_profile(..., "error_stub")` (`opg:875-883`).
- **Legacy actors**
  - The persona is `entity.summary or "A participant in social discussions."`. The bio is `"{type}: {name}"`.
  - The role is still compiled and appended. When a role exists, the text is sanitized.
  - Fields not set fall back to the dataclass defaults: karma 1000, friend_count 100, follower_count 150, statuses_count 500. Demographics are left as `None`.
  - `generation_path="error_stub"` (`opg:884-926`).

#### `_generate_username(name)` (`opg:928-936`)
- It lower-cases the name, replaces spaces with `_`, and keeps only `isalnum()` characters (CJK characters count as alnum) and `_`.
- It appends `_{random.randint(100,999)}`. The result is **non-deterministic**, and nothing checks for collisions.

#### `_search_zep_for_entity(entity)` (`opg:938-1089`)
- **Early exits.** Returns empty `{facts:[], node_summaries:[], context:""}` when there is no `zep_client` (`opg:953-954`) or no `graph_id` (`opg:965-967`).
- **Query** is the Chinese template `关于{name}的所有信息、活动、事件、关系和背景` (`opg:969`).
- **Retries.** `max_retries = Config.PROFILE_ZEP_SEARCH_MAX_RETRIES` (fallback 3), `base_delay = …_RETRY_DELAY_SECONDS` (fallback 2.0) (`opg:974-975`). **Neither attribute exists in `config.py`**, so the effective values are 3 tries with 2s then 4s delays.
- **Two searches** run in parallel through `ThreadPoolExecutor(max_workers=2)`, each with `future.result(timeout=30)` (`opg:1027-1033`):
  - `search_edges`: `graph.search(query, graph_id, limit=30, scope="edges", reranker="rrf")` with exponential backoff (`opg:977-999`);
  - `search_nodes`: `limit=20, scope="nodes"` (`opg:1001-1023`).
- **Result handling**
  - Facts are deduplicated as a set (`opg:1036-1041`).
  - Node summaries are collected, plus `"相关实体: {name}"` for other node names (`opg:1044-1051`).
  - The context is `事实信息:` (first 20) plus `相关实体:` (first 10) (`opg:1054-1059`).
- **Optional community block.** When `Config.GRAPH_COMMUNITY_RETRIEVAL` is set, it appends `群体身份: 属于派系「…」` plus a 300-character summary and sets `results["community"]` (`opg:1063-1071`).
- **Logging.** An INFO log is written when anything was found. A WARNING is written when retrieval comes back empty, i.e. the actor lacks KG grounding (`opg:1076-1082`). A timeout or other exception only warns, and partial results are returned (`opg:1084-1087`). [verifier: on a timeout nothing partial is returned. Both futures are awaited inside the `with` block (`opg:1027-1033`) and `results` is only filled after that block (`opg:1036-1059`), so a timeout returns the empty initial dict (`opg:958-962`). A partial dict is possible only if an exception fires during post-processing. The two `result(timeout=30)` waits also run one after the other (`opg:1032-1033`).]

#### `_community_for_entity(entity_name)` (`opg:1091-1117`)
- On first use it caches `get_runtime().list_communities(graph_id)` on the instance; on failure it caches `[]` (`opg:1099-1105`).
- It returns the first community whose member names match the entity after `normalize_name`, either exactly or by containment in either direction when the target is at least 2 characters (`opg:1110-1116`).

#### `_resolve_entity_uuid(entity)` (`opg:1119-1157`)
- It returns `entity.uuid` if set; that is the usual case (`opg:1127-1128`).
- Otherwise it searches nodes by name (`limit=5, rrf`). It prefers an exact name match and falls back to the top hit (`opg:1133-1157`).

#### `_retrieve_ego_network(entity, center_uuid)` (`opg:1159-1234`)
- Only used when `PERSONA_EGO_RETRIEVAL` is set.
- It runs the edge search with `limit=max_neighbors`, where `Config.PERSONA_EGO_MAX_NEIGHBORS` falls back to 10 and **is not defined in config.py**. The search uses `reranker="node_distance"`, `center_node_uuid=center_uuid` and `search_filter={"edge_types": RELATIONSHIP_EDGE_TYPES}`. Retries and backoff are the same as above (`opg:1174-1206`).
- It returns up to `max_neighbors` unique lines. Each line is the edge fact, or `"{center} --[{edge_name}]--> (关系网邻居)"` (`opg:1213-1234`).

#### `_build_entity_context(entity)` (`opg:1236-1349`)
The function builds the persona context in five steps:
1. Lists non-empty entity attributes as `### 实体属性` (`opg:1248-1254`).
2. Builds `### 相关事实和关系` from `entity.related_edges`, with **no count limit** (`opg:1264`). Each edge is rendered as its fact text when present. Otherwise neighbor names are resolved through `related_nodes` and rendered with an arrow that follows the edge direction (`opg:1257-1285`).
3. Builds `### 关联实体信息` from `related_nodes` (name, custom labels, summary), with **no limit** (`opg:1288-1305`).
4. Runs the graph search unless `Config.PROFILE_ZEP_SKIP_WHEN_CONTEXT`, which defaults to True (`backend/app/config.py:387`), applies and the entity already has edges or nodes (`opg:1311-1318`). New facts not already listed are added, first 15 (`opg:1320-1324`), followed by node summaries, first 10 (`opg:1326-1327`).
5. Adds the ego-network block `## 你在关系网中的实际位置` when `Config.PERSONA_EGO_RETRIEVAL` is set (default False, `backend/app/config.py:380`). Any exception only logs at debug level (`opg:1333-1347`).

The function returns the parts joined by blank lines.

#### Small predicates (`opg:1351-1398`)
- `_english_persona()` returns true when `persona_language` starts with `en` (`opg:1351-1357`).
- `_is_individual_entity(type)` is an exact lowercase membership test against `INDIVIDUAL_ENTITY_TYPES` (`opg:1359-1361`).
- `_is_group_entity` is dead code (`opg:1363-1365`).
- `_persona_design_enabled()` reads `Config.SIM_PERSONA_DESIGN`, default true; the strings false/0/no/off disable it (`opg:1367-1374`).
- `_MARKET_TERM_STOPWORDS` is defined at `opg:1378-1385`.
- `_market_priors_enabled()` reads `Config.SIM_MARKET_PRIORS`, default true (`opg:1387-1394`).
- `_is_market_aware_role` is defined at `opg:1396-1398`.

#### Market-prior hint (`opg:1400-1506`)
- **`_prediction_markets()`** (`opg:1400-1434`)
  - It lazily imports `PipelineManager` and walks **every** pipeline through `list_pipelines()` and `load(pid)` until one has `graph_id == self.graph_id`.
  - It then reads `<handoff_dir>/prediction_markets.json` and accepts either `{"markets":[…]}` or a bare list.
  - The result is cached on the instance in `_market_priors_cache`, including an empty list after a failure.
- **`_topic_terms(text)`** splits on `[^0-9a-zA-Z一-鿿]+`, lower-cases, drops stopwords, and keeps tokens of at least 4 characters (`opg:1436-1447`).
- **`_market_awareness_hint(name, type, summary, actor)`** (`opg:1449-1506`)
  - It applies only to market-aware types.
  - It picks the market whose question has the most term overlap with name + summary + actor role/stance, and requires a numeric `implied_yes_prob` that is not a bool.
  - It emits a `## Market awareness` block (English) or a `## 市场先验感知` block. The question is limited to 160 characters and the percentage has no decimals.

#### Persona design (`opg:1508-1645`)
- **`_build_persona_design_block()`** returns a fixed Chinese instruction block that asks for a `persona_design` object with the 8 keys, each 1-3 sentences, extracted strictly from the dossier (`opg:1508-1530`).
- **`_normalize_persona_design(raw, actor, name, actors)`** (`opg:1532-1556`)
  - It keeps only whitelisted keys. List values are joined with `；`. Empty values are dropped.
  - If nothing is left, it falls back to `_design_from_actor`.
- **`_design_from_actor(actor, name, actors)`** (`opg:1558-1645`)
  - It returns `None` for canonical v1 actors (`opg:1573-1577`) and for an empty actor.
  - Otherwise it maps dossier fields deterministically:
    - identity ← role / worldview.identity
    - views_beliefs ← stance / beliefs / frame
    - incentives ← up to 4 incentives, as driver/gains_if/loses_if
    - objectives ← goals
    - relations ← `roster_block` with the header line stripped
    - constraints_red_lines ← constraints / vulnerabilities, 3 each
    - decision_style ← `风险偏好：{risk_tolerance}`
    - rhetoric ← `stated_vs_revealed`

#### `_generate_profile_with_llm(...)` (`opg:1647-1837`) — the main LLM call
- **Guard.** It raises for canonical v1 actors (`opg:1665-1670`).
- **Prompt blocks**
  - `actor_briefing`, `relationship_briefing`, and, when `Config.PERSONA_BEHAVIORAL_DNA` is set (default True, `backend/app/config.py:383`), `behavioral_dna_block` and `roster_block` (`opg:1679-1692`).
  - The role evidence contract (`opg:1696`).
- **Base prompt.** Individual entities get `_build_individual_persona_prompt`. Everything else, including unknown types, gets `_build_group_persona_prompt` (`opg:1698-1705`).
- **Additions**
  - A prefixed situation-brief line `【共同背景·局势简报（调研实证）】`, made of `current_situation + dynamics` and limited to 600 characters (`opg:1708-1715`).
  - Appended in order: DNA, roster, relationships, then the actor briefing with a "dossier wins on conflict" rule (`opg:1720-1732`).
  - The role contract as sorted compact JSON between `BEGIN/END UNTRUSTED ACTOR EVIDENCE — JSON DATA ONLY` markers (`opg:1733-1749`).
  - The market hint (`opg:1754-1758`).
  - The persona-design block, added when design is enabled and an actor exists (`opg:1764-1768`).
- **Call loop** (`opg:1771-1828`)
  - Up to `max_attempts=3`. Each attempt is `self.llm.chat(messages=[system, user], response_format={"type":"json_object"}, temperature=0.7 - 0.1*attempt)`. The system prompt comes from `_get_system_prompt`.
  - On success, `json.loads`. An empty `bio` is backfilled from summary[:200] or `"{type}: {name}"`. An empty `persona` is backfilled from the summary or `"{name}是一个{type}。"`. `persona_design` is normalized when requested and stripped otherwise (`opg:1786-1804`).
  - On `JSONDecodeError`, it calls `_try_fix_json`. If the result is marked `_fixed`, that result is returned after the same design normalization (`opg:1806-1822`). Otherwise the loop retries without sleeping.
  - On any other exception, it logs and sleeps `1*(attempt+1)` seconds. **The sleep is linear even though the comment says exponential, and it also happens after the last attempt** (`opg:1824-1828`).
- **Fallback.** After 3 failures it returns `_generate_profile_rule_based(...)` tagged `_generation_path="rule_fallback"` (`opg:1830-1837`).

#### JSON repair (`opg:1839-1926`)
- **`_fix_truncated_json`** (`opg:1839-1860`)
  - It appends `"` if the last character is not one of `",}]`.
  - It then appends the missing `]` characters followed by the missing `}` characters. The counts are raw character counts that include braces inside strings, and the closing order ignores nesting.
- **`_try_fix_json`** (`opg:1862-1926`) tries these steps in order:
  1. Run the truncation fix.
  2. Take the outermost `{…}` match with a regex.
  3. Collapse newlines inside string literals.
  4. Parse.
  5. Strip control characters and parse again.
  6. Regex-salvage `"bio"` and `"persona"` into `{bio, persona, _fixed:True}`.
  7. Return `{bio, persona}` without `_fixed`, which makes the caller retry.

#### Prompt builders (`opg:1928-2112`)
- **`_get_system_prompt(is_individual)`** returns a Chinese system prompt that demands valid JSON with no raw newlines. The English variant adds "write bio/persona in English" (`opg:1928-1939`). **The `is_individual` argument is ignored.**
- **`_persona_context_cap()`** (`opg:1941-1963`)
  - The floor is `Config.PERSONA_CONTEXT_FLOOR_CHARS` (default 3000).
  - When `ADAPTIVE_CONTEXT` is set (default True, `backend/app/config.py:118`), the cap is `slice_budget_chars(window=Config.context_window_for(provider), reserved=RESERVED_COMPLETION_TOKENS(8192), floor, share=0.4)` with no `cap_tokens`.
  - For `claude-cli` (200K window, `backend/app/config.py:139`) that is about 306,892 characters, so in practice the context is not truncated.
  - Any exception falls back to the floor.
- **`_build_individual_persona_prompt`** (`opg:1965-2043`) asks for JSON with these fields:
  - `bio` (200 characters) and `persona` (2000 characters, covering 7 sub-areas including 个人记忆);
  - `age`, `gender`, `mbti`, `country`, `profession`, `interested_topics`;
  - optional `values`, `beliefs`, `incentives`.
  - When `PERSONA_FIELD_EXTRACTION` is set (default true, `backend/app/config.py:566`), the demographic fields say "omit if not inferable, don't invent". When it is false, the old wording is used, including the `"中国"` example (`opg:1983-1998`).
  - The language rule switches between English and Chinese (`opg:2001-2005`).
- **`_build_group_persona_prompt`** (`opg:2045-2112`) is the institution version.
  - It forces `age=30` and `gender="other"`, and still asks for MBTI as an "account style".
  - The country is the HQ or jurisdiction when field extraction is on (`opg:2062-2066`).

#### Rule path (`opg:2114-2249`)
- **`_generate_profile_rule_based(...)`** (`opg:2114-2176`)
  - It raises for canonical v1 actors (`opg:2129-2133`) and starts from `_rule_based_base`.
  - With an actor it adds overlays:
    - `bio = "{role}；立场：{stance}"` limited to 200 characters (`opg:2139-2142`);
    - the persona plus `actor_briefing` plus `relationship_briefing` (`opg:2145-2150`);
    - **influence scaling**: `follower=int(300*w)`, `friend=int(120*w)`, `karma=int(1500*w)`, where `w` is 2.5, 1.5 or 1.0 from `INFLUENCE_WEIGHTS` (`backend/app/utils/actors.py:134-142`) (`opg:2153-2157`);
    - a persona design plus a `【人格设计·实证提炼】` summary line (`opg:2162-2174`).
- **`_rule_based_base(...)`** (`opg:2178-2249`) uses English templates per type bucket:
  - student/alumni: random age 18-30, random gender, MBTI and country;
  - publicfigure/expert/faculty: random age 35-60, MBTI from the NT types;
  - mediaoutlet/socialmediaplatform: age 30, gender other, MBTI ISTJ, country `"中国"` (hard-coded);
  - university/governmentagency/ngo/organization: same as media, with `"中国"`;
  - default: bio from summary[:150], random demographics.

#### `set_graph_id` (`opg:2251-2253`) — trivial setter.

#### `generate_profiles_from_entities(entities, use_llm=True, progress_callback=None, graph_id=None, parallel_count=5, realtime_output_path=None, output_platform="reddit", actors=None, actor_context_packs=None)` (`opg:2255-2518`)
1. Sets `self.graph_id` when it is given (`opg:2288-2289`).
2. **Canonical pre-flight** (`opg:2296-2309`): when the dossier is canonical, each entity runs `match_actor` then `_validated_canonical_batch_context`. **Any failure raises before any worker starts.**
3. `profiles` is pre-allocated as `[None]*total`, and a `Lock` is created (`opg:2311-2314`).
4. **`save_profiles_realtime()`** (`opg:2317-2351`)
   - It writes only the **contiguous completed prefix**, stopping at the first `None`. This keeps the array index equal to the entity index (OASIS assigns agent_id by array position).
   - It reuses `_save_reddit_json` / `_save_twitter_csv`, so each realtime save **also rewrites the `*_roles.json` manifest**. Exceptions are only logged.
5. **Worker `generate_single_profile(idx, entity)`** (`opg:2353-2396`)
   - In canonical runs it uses the preflight inputs. Otherwise it calls `match_actor(entity.name, actors)` and looks up `context_pack` by `actor_id_for(actor)`.
   - It calls `generate_profile_from_entity(user_id=idx, …)` and then `_print_generated_profile` (stdout).
   - On exception: canonical runs **re-raise**. Legacy runs return `(idx, _error_stub_profile(...), str(e))`.
6. **Pool** (`opg:2404-2457`)
   - `ThreadPoolExecutor(max_workers=parallel_count)` with one submit per entity. Results are collected with `as_completed`.
   - Each completion triggers the progress callback `"已完成 {current}/{total}: {name}（{type}）"` and a realtime save.
   - When `future.result()` raises, canonical runs re-raise. Legacy runs build an error stub again, outside the worker.
7. **Post-checks** (`opg:2463-2491`)
   - Every entity that matches an actor must have a non-empty `role_prompt`, otherwise `RuntimeError("researched actors missing runtime role prompts: …")` (first 8 names).
   - In canonical runs, `done == researched == role_prompts == total` is required, otherwise `RuntimeError`.
8. **Stats** (`opg:2492-2512`)
   - `self.last_generation_stats = {total, ok, rule_fallback, error_stub, researched_actors, role_prompts}`.
   - A WARNING is logged when `use_llm` is set and the degraded share is above 25%.
   - A final `progress_callback(total, total, summary)` is called, with errors suppressed.
9. Returns `profiles` in entity order (`opg:2518`).

#### `_print_generated_profile` (`opg:2520-2549`)
Prints the full, untruncated profile (bio, persona, demographics) to stdout for every entity.

#### `generate_audience_profiles(audience_configs, start_user_id)` (`opg:2551-2617`)
- Builds rule-only "silent majority" profiles with zero LLM and zero graph calls. Configs are duck-typed (dict or attributes).
- **Fields**
  - name from `entity_name`, or `公众_{i}`;
  - stance (supportive, opposing, neutral or observer) mapped to an English sentence;
  - English bio and persona;
  - random karma 50-800, friends 20-200, followers 5-120, statuses 10-400;
  - random age 18-65, gender and MBTI;
  - `country` is `""` in English mode and `"中国"` otherwise;
  - `profession="General public"`, `generation_path="rule"`;
  - `user_id = start_user_id + i`.
- **Caller:** `backend/app/services/simulation_manager.py:1188-1221`. It runs after config generation, and the extended list is re-saved.

#### `save_profiles(profiles, file_path, platform="reddit")` (`opg:2619-2640`)
`twitter` → `_save_twitter_csv`. Anything else → `_save_reddit_json`.

#### `_role_manifest_path(profile_path)` (`opg:2642-2645`)
Returns `"{stem}_roles.json"`, for example `reddit_profiles_roles.json` and `twitter_profiles_roles.json`.

#### `_save_role_prompt_manifest(profiles, profile_path)` (`opg:2647-2791`)
- **Per-row checks.** For every profile with a `role_contract` (`opg:2655-2657`), it verifies `sha256(role_prompt) == role_prompt_sha256` (`opg:2658-2661`).
- **Runtime field.** It determines what OASIS will load (`opg:2662-2682`):
  - canonical actors: the role itself;
  - legacy CSV: `bio + " " + persona` with newlines replaced by spaces;
  - legacy JSON: the persona.
- It raises if the role fragment is not a substring of that runtime field (`opg:2683-2686`).
- **Row contents** (`opg:2687-2710`): `profile_index`, `user_id`, `name`, `source_entity_uuid`, `actor_id`, `contract`, `prompt_sha256`, `runtime_prompt_sha256`, `runtime_field` (`user_char`|`persona`), `runtime_profile_sha256`, `runtime_transform` (`newlines_to_spaces`|`none`), `prompt_chars`, `compiler_max_chars` and the actor-context bindings. Canonical JSON rows also get `reddit_system_message_version/_sha256/_chars` (`opg:2711-2723`). [verifier: the real keys are `reddit_system_message_version`, `reddit_base_system_message_sha256` and `reddit_base_system_message_chars`, with a "base" infix (`opg:2716-2722`, read back at `opg:3016-3037`).]
- **Profile hash.** It re-reads the profile file it just wrote to compute `profile_file_sha256` (`opg:2725-2726`).
- **Context-binding consistency.** Either all role rows are context-bound or none are. All bound rows must share one manifest sha and one report sha (`opg:2727-2747`).
- **Top-level manifest** (`opg:2748-2784`): `schema_version "actor-role-manifest/v2"`, `role_contract_version`, `profile_file` (basename), `profile_file_sha256`, `profile_count`, `actor_role_count`, `dossier_sha256`, `actor_cast_manifest_sha256`, `actor_context_required`, `actor_context_manifest_sha256`, `actor_context_report_sha256`, `actor_roster_sha256` (sha of the sorted compact JSON of `[{actor_id, input_sha256}]`) and `roles`.
- **Write.** The manifest is written atomically (`opg:2785-2791`). It is **always** written, even with 0 roles.

#### `validate_role_prompt_manifest(profile_path, *, expected_role_count=None, expected_cast_manifest_sha256=None)` classmethod (`opg:2793-3060`)
This is a read-only fail-closed validator. Every failure raises `ValueError`.
- **Manifest header** (`opg:2809-2837`)
  - the manifest is an object with schema `actor-role-manifest/v2`;
  - the role version is `actor-role/v1` or `/v2`, and a v1 manifest cannot require context;
  - the basename matches and the profile file sha matches;
  - `roles` is a list and the count matches;
  - the optional expected count and cast sha match.
- **Context artifacts.** When context is required, it checks the expected context and report shas, then runs `validate_actor_context_artifacts(dirname(profile_path), …)` and builds the bindings (`opg:2842-2857`).
- **Profile rows.** It parses CSV through `csv.DictReader(decoded.splitlines())`, with runtime field `user_char`, or JSON with `persona`. The row count must equal `profile_count` (`opg:2859-2870`).
- **Per role** (`opg:2874-3050`)
  - the index is a valid int;
  - the actor_id is unique and non-empty;
  - the runtime field name and the full runtime-field sha match;
  - the contract's actor_id and schema match;
  - context file/sha/manifest/report bindings and the 9 provenance keys match (`opg:2896-2952`);
  - `compiler_max_chars` is an int;
  - **v1 legacy roles:** a fragment-seal check that slides a window over each `"ROLE BRIEF"` occurrence (`opg:2956-2993`);
  - **v2 roles:** the contract is recompiled with `compile_actor_role_prompt(contract, max_chars=compiler_max)` and the prompt sha, length, runtime-fragment sha and substring must all match (`opg:2995-3010`);
  - **canonical v1 Reddit rows** additionally verify the canonical system-message version, sha and length, and that `age/gender/mbti/country` are all `None`/`""` (`opg:3011-3044`).
- **Roster.** It checks the roster fingerprint (`opg:3051-3059`) and returns the manifest dict.

#### `_save_twitter_csv(profiles, file_path)` (`opg:3062-3123`)
- If the path does not end in `.csv`, it replaces `.json` with `.csv` (`opg:3081-3082`).
- **Columns:** `user_id,name,username,user_char,description` (`opg:3089`).
  - `user_id` is the **array index `idx`**, not `profile.user_id` (`opg:3112`).
  - `user_char` is the canonical role, or `bio + " " + persona` (bio alone when the two are equal), with `\n`/`\r` replaced by spaces (`opg:3097-3106`).
  - `description` is the full bio with newlines replaced (`opg:3109`).
- It is built in a `StringIO` and written with `write_text_atomic`, then the role manifest is written (`opg:3120-3121`).
- There are **no demographic columns.**

#### `_normalize_gender(gender)` (`opg:3125-3148`)
Maps 男→male, 女→female, 机构/其他→other, and passes male/female/other through. Anything else, including empty, becomes `"other"`.

#### `_save_reddit_json(profiles, file_path)` (`opg:3150-3253`)
- **Canonical rows:** `age/gender/mbti/country` are all `""` (`opg:3175-3185`).
- **Legacy rows** get backfills (`opg:3186-3192`):
  - `age` defaults to `30`;
  - `gender` goes through `_normalize_gender`;
  - `mbti` defaults to `"ISTJ"`;
  - `country` defaults to `"中国"` in Chinese mode and `""` in English mode (`opg:3170`).
- **Item fields** (`opg:3196-3214`):
  - `user_id` is `profile.user_id`, or `idx` when that is `None`;
  - `username`;
  - `name`;
  - `bio` limited to **300** characters (`opg:3200`);
  - `persona`;
  - `karma`, defaulting to 1000 if falsy;
  - `created_at`;
  - the four demographic keys.
- **Optional keys:** `profession`, `interested_topics`, and `other_info{persona_design, actor_role}` (`opg:3221-3239`).
- It logs how many backfilled defaults were used (`opg:3243-3247`), writes atomically, then writes the role manifest (`opg:3250-3251`).

#### `save_profiles_to_json` (`opg:3256-3264`)
Deprecated alias that logs a warning and calls `save_profiles`. It has no production callers.

### B. `backend/app/utils/oasis_llm.py`

#### Header, constants and flags (`ollm:1-67`)
- The logger is `mirofish.oasis_llm` (`ollm:25`).
- `DEFAULT_CLI_SEMAPHORE = 8` and `DEFAULT_OPENAI_SEMAPHORE = 30` (`ollm:29-30`).
- `_EMPTY_ASSISTANT_PLACEHOLDER = "(no response)"` (`ollm:38`).
- **`_env_or_config_flag(name, default)`** (`ollm:41-57`)
  - The environment variable wins when it is set. The values 1/true/yes/on count as true; any other value is false.
  - Otherwise `Config.<name>` is used: strings are parsed the same way, other values with `bool()`.
  - Otherwise the default. It never raises.
- **`_tool_emulation_enabled()`** reads `SIM_CLI_TOOL_EMULATION`, default True (`ollm:60-62`; `backend/app/config.py:602`).
- **`_sim_llm_fallback_enabled()`** reads `SIM_LLM_FALLBACK`, default True (`ollm:65-67`; `backend/app/config.py:603`).

#### Tool-call emulation protocol (`ollm:78-146`)
- **`_tool_schema_summaries(tools)`** turns OpenAI tool schemas into `[{name, description, parameters}]` and skips malformed entries (`ollm:78-94`).
- **`_tool_names(tools)`** returns the set of names (`ollm:97-98`).
- **`_render_tool_prompt(tools)`** produces a `[TOOL CALLING]` instruction (`ollm:101-112`):
  - reply with only `{"tool": "<tool_name>", "arguments": {...}}`;
  - or `{"tool": null, "reply": "<brief reason>"}`;
  - followed by the JSON schema list.
- **`_has_tool_result(messages)`** returns true when any message has role `tool` or `function`. Emulation is then skipped, which allows one action per step (`ollm:115-119`).
- **`_parse_tool_call_text(text, valid_names)`** (`ollm:122-146`)
  - It parses with `LLMClient._parse_json_response`.
  - The tool name is read from `tool`, `tool_name` or `name`, and must be in `valid_names`.
  - Arguments are read from `arguments`, then `args`, then `{}`. The result is `(reply or "", [{"name", "arguments"}])`.
  - If no valid tool is found, it returns `(reply/content, [])`. If nothing parses, it returns `(text, [])`. It never raises.

#### `_estimate_tokens_of(value)` (`ollm:149-159`)
Estimates tokens as `ceil(len/4)` for strings, sums over lists, and serializes dicts as JSON first. Used for the fake `usage` block.

#### `_build_chat_completion(model_label, messages, content, tool_calls=None)` (`ollm:162-210`)
- **Empty content** becomes `"(no response)"` (`ollm:170-171`).
- **Usage** is estimated: prompt tokens are the sum over message contents (`ollm:172-173`).
- **Tool calls.** When present, each call is given `id=call_{16 hex}`, `type=function` and arguments as a JSON string, and `finish_reason` is `tool_calls` (`ollm:177-189`).
- **Return value.** It returns `ChatCompletion.model_validate` with `id='chatcmpl-cli-{24 hex}'` (`ollm:193`). Run telemetry relies on that prefix to recognise estimated usage (`backend/scripts/run_parallel_simulation.py:2100`).

#### Empty-assistant guard (`ollm:213-253`)
- **`_sanitize_messages(messages)`** replaces assistant messages whose content is None or blank with the placeholder, in a new list (`ollm:213-225`).
- **`_wrap_openai_empty_guard(model)`** monkey-patches the instance's `_request_chat_completion` and `_arequest_chat_completion` so messages (`args[0]` or `kwargs["messages"]`) are sanitized first. Any error during patching is swallowed (`ollm:228-253`).

#### LLMClient fallback for the HTTP path (`ollm:264-376`)
- **`_LLM_FALLBACK_STATS`** is a module global `{llm_fallback_calls, llm_fallback_tool_calls}` (`ollm:264`). `get_llm_fallback_stats()` returns a copy (`ollm:267-269`). **Only tests call it.**
- **`_record_llm_fallback(provider, with_tool_call, exc)`** (`ollm:272-298`)
  - It increments the counters and logs a WARNING on the 1st call and every 25th.
  - If `cwd/simulation_config.json` exists, it appends a line `{ts, event:"llm_fallback", provider, tool_call, error}` to `cwd/llm_fallback.jsonl`. `OSError` is ignored.
- **`_should_fallback_exc(exc)`** (`ollm:301-311`) is true when:
  - `llm_client._is_content_filter(exc)` matches (new_sensitive / unprocessable / content+filter / 422; see `backend/app/utils/llm_client.py:126-129`); or
  - the message contains 429 / rate_limit / quota / usage limit / new_sensitive / unprocessable.
- **`_extract_messages_tools(args, kwargs)`** reads messages from `args[0]` or the kwarg, and tools from `args[1]` or the kwarg (`ollm:314-317`).
- **`_fallback_completion(model, provider, exc, *args, **kwargs)`** (`ollm:320-345`)
  - It sanitizes the messages and reads `temperature` (default 0.7) and `max_tokens` (default 4096) from `model.model_config_dict`.
  - It creates a **new `LLMClient(provider=provider)` per call**.
  - It emulates tools when tools are present, emulation is on, and there is no tool result yet. Otherwise it makes a plain chat call.
  - If the fallback itself fails, it logs an ERROR and **re-raises the original `exc`** (`ollm:341-343`). [verifier: this holds only for failures inside `llm.chat` and parsing. `LLMClient(provider=provider)` is built at `ollm:328`, before the `try` at `ollm:330`. If construction fails (unsupported provider, or no `Config.LLM_API_KEY` for an OpenAI-compatible provider: `backend/app/utils/llm_client.py:266-270`, `289-290`), that `ValueError` propagates in place of the original exception.]
  - It records stats and returns a synthesized completion labelled with `model.model_type`.
- **`_wrap_openai_fallback_guard(model, provider)`** (`ollm:348-376`) wraps the sync and async request methods. When the fallback flag is on and `_should_fallback_exc` matches, it routes to `_fallback_completion`; the async path does so through `asyncio.to_thread`. Otherwise it re-raises.

#### `class CLIModel(OpenAIModel)` (`ollm:379-478`)
- **`__init__`** (`ollm:382-401`)
  - It stores the lower-cased `provider` and creates `self._llm = LLMClient(provider=...)`, which uses `Config.LLM_MODEL_NAME`; `model_type` is only a label.
  - It calls `OpenAIModel.__init__` with `api_key='cli-bridge'`.
- **`_request_chat_completion(messages, tools)`** (`ollm:414-444`)
  - `temperature` and `max_tokens` default to 0.7 and 4096. The `or` fallback means an explicit `0` becomes the default (`ollm:419-420`).
  - It sanitizes the messages (`ollm:421`).
  - When tools are present, emulation is on, and there is no tool result, it appends a user message containing the tool prompt, calls `self._llm.chat`, parses the reply, and logs INFO if no call was parsed (`ollm:425-434`).
  - When tools are present but emulation is off, it logs a WARNING that the agent will not act (`ollm:436-437`).
  - It returns a synthesized completion labelled with the **provider** (`ollm:412`).
- **`_arequest_chat_completion`** wraps the sync method in `asyncio.to_thread` (`ollm:446-451`).
- **`_request_parse(messages, response_format, tools)`** ignores tools with a warning, uses temperature default 0.3, calls `self._llm.chat_json`, and wraps `json.dumps(payload)` (`ollm:453-470`). **`response_format` is ignored.**
- **`_arequest_parse`** wraps `_request_parse` in `asyncio.to_thread` (`ollm:472-478`).

#### `_resolve_provider(config)` (`ollm:481-487`)
Resolution order: `os.environ['LLM_PROVIDER']`, then `config['llm_provider']` (from `simulation_config.json`, `backend/app/services/simulation_config_generator.py:387`), then `Config.LLM_PROVIDER`, then `'claude-cli'`. The result is lower-cased.

#### `_create_openai_model(config, use_boost=False)` (`ollm:490-532`)
- **Boost path.** Used when `use_boost` is set and `LLM_BOOST_API_KEY` is non-empty. It takes key, URL and model from `LLM_BOOST_*`, with the model falling back to `os.environ LLM_MODEL_NAME` (`ollm:500-504`).
- **Normal path.** Each value comes from the environment variable, else `Config` (`ollm:509-512`).
- **Model default.** If there is still no model, it uses `config["llm_model"]`, else `"gpt-4o-mini"` (`ollm:514-515`). [verifier: the code is `config.get("llm_model", "gpt-4o-mini")`, so the default applies only when the key is absent. `simulation_config.json` always writes `llm_model` (`backend/app/services/simulation_config_generator.py:388`), so an empty value gives model `""`, not `gpt-4o-mini`.]
- **Key and URL fallback.** If the key or URL is empty, it reads `OPENAI_API_KEY` / `OPENAI_API_BASE_URL` from the environment (read only, never written) (`ollm:520-521`).
- It raises `ValueError` if no key is found (`ollm:522-523`).
- It calls `ModelFactory.create(model_platform=OPENAI, model_type, api_key, url)` and wraps the result with the empty guard (`ollm:526-532`).

#### `_inject_coding_agent_ua(model)` (`ollm:535-554`)
Replaces `model._client` and `_async_client` with plain `OpenAI` / `AsyncOpenAI` clients that use `default_headers={"User-Agent": Config.LLM_USER_AGENT}` (default `'claude-cli/1.0.0'`, `backend/app/config.py:803`). It reuses the private CAMEL attributes `_timeout/_max_retries/_url/_api_key`, which exist in camel-ai 0.2.78 (`backend/.venv/.../camel/models/openai_model.py:121-144`).

#### `create_oasis_model(config, use_boost=False)` (`ollm:557-600`)
- **CLI providers** (`CLI_PROVIDERS = ('claude-cli','codex-cli')`, `backend/app/utils/llm_client.py:31`)
  - The label is `config['llm_model'] or provider`.
  - A WARNING is logged if tool emulation is off.
  - It returns `CLIModel(model_type, provider, model_config_dict={}, api_key='cli-bridge')` (`ollm:567-582`).
- **Other providers**
  - It calls `_create_openai_model`.
  - For `kimi` only it injects the UA (`ollm:585-587`).
  - It sets `model.model_config_dict["extra_body"] = Config.reasoning_extra_body()` when that is not None. **No provider argument is passed**, so `Config.LLM_PROVIDER` decides, not the resolved provider. A failure to set it only warns (`ollm:591-597`).
  - It wraps the fallback guard (`ollm:599`).

#### `get_oasis_semaphore(config, use_boost=False, platforms=1)` (`ollm:603-616`)
- CLI providers: `int(os.environ OASIS_CLI_SEMAPHORE or 8)`.
- Other providers: `int(os.environ OASIS_SEMAPHORE or 30)`.
- It returns `max(1, cap // max(1, platforms))`.
- It reads **os.environ only**, not `Config`. A non-integer value raises `ValueError` (it is not caught here). `use_boost` is unused.

---

## Control flow

### PREPARE (profile generation)
1. `SimulationManager.prepare_simulation(..., use_llm_for_profiles=True, parallel_profile_count=3, actors, ...)` (`backend/app/services/simulation_manager.py:862-876`).
   - Orchestrator callers pass `Config.PARALLEL_PROFILE_COUNT` (default 16) for HTTP providers and 3 for CLI (`backend/app/services/pipeline_orchestrator.py:12789-12816`, `8773-8794`).
   - The `/prepare` API defaults to 5 (`backend/app/api/simulation.py:509`).
2. The generator is constructed with `graph_id` and `persona_language="en"` for English research. The cast/context hashes are injected as attributes (`backend/app/services/simulation_manager.py:1046-1058`).
3. The realtime path is `reddit_profiles.json` when Reddit is enabled, else `twitter_profiles.csv` (`backend/app/services/simulation_manager.py:1072-1079`).
4. `generate_profiles_from_entities` runs (`opg:2255`):
   - canonical pre-flight (`opg:2296-2309`);
   - thread-pool workers call `generate_profile_from_entity` (`opg:2368`);
   - which either branches to `_canonical_actor_role_profile` (`opg:721-729`);
   - or calls `_build_entity_context` (`opg:736`), possibly `_search_zep_for_entity` (`opg:1318`) and the ego network (`opg:1333-1347`);
   - then `_generate_profile_with_llm` (`opg:762`), which uses `LLMClient.chat` ×≤3 and falls back to the rule path;
   - then role compilation and append (`opg:808-829`);
   - after each completion, a realtime prefix save that also writes `*_roles.json` (`opg:2425`);
   - finally post-checks and stats (`opg:2463-2512`).
5. The manager checks that `last_generation_stats.role_prompts == actor_cast_manifest.selected_actor_count`, else `RuntimeError` (`backend/app/services/simulation_manager.py:1093-1102`).
6. `save_profiles` is called for each enabled platform (`backend/app/services/simulation_manager.py:1123-1137`). Each call writes the profile file and the `*_roles.json` manifest.
7. After `SimulationConfigGenerator.generate_config`, `generate_audience_profiles` appends audience profiles and the files are re-saved (`backend/app/services/simulation_manager.py:1188-1221`).
8. `validate_role_prompt_manifest` runs for each platform when there are roles, and the sha of each `*_roles.json` is stored in `state.actor_role_manifest_sha256` (`backend/app/services/simulation_manager.py:1242-1276`).

### Re-validation consumers
- Prepare-ready check: `backend/app/api/simulation.py:300-334`.
- Runner launch gate: `backend/app/services/simulation_runner.py:684-757`.
- OASIS child, canonical Reddit: `_enforce_canonical_reddit_system_messages`, which calls `validate_role_prompt_manifest` and `canonical_reddit_system_message` (`backend/scripts/run_parallel_simulation.py:576-627`), then attestation (`backend/scripts/run_parallel_simulation.py:630-680`).

### RUN (simulation model)
- Twitter uses `create_model(config, use_boost=False)` and Reddit uses `create_model(config, use_boost=True)` (`backend/scripts/run_parallel_simulation.py:4732`, `5268`). Both call `create_oasis_model` (`ollm:557`).
- `oasis.make(..., semaphore=get_oasis_semaphore(config, use_boost, platforms=semaphore_platforms))` (`backend/scripts/run_parallel_simulation.py:4815`, `5368`).
- **Per agent step**
  - CAMEL `OpenAIModel._run`/`_arun` calls `_request_chat_completion(messages, tools)`, or `_request_parse` when a `response_format` is set (`backend/.venv/lib/python3.12/site-packages/camel/models/openai_model.py:298-317`).
  - For CLI providers this is `CLIModel._request_chat_completion`, which calls `LLMClient.chat`, possibly with tool emulation (`ollm:414-444`).
  - For HTTP providers it goes through the fallback guard, then the empty guard, then the original CAMEL request. On a 422/429-class error it calls `_fallback_completion`, which calls `LLMClient.chat` (`ollm:348-376`, `228-253`, `320-345`).

---

## Data & artifacts

| Artifact | Path pattern | Writer | Format / key fields |
|---|---|---|---|
| Reddit profiles | `<sim_dir>/reddit_profiles.json` (`backend/app/services/simulation_manager.py:1074`, `1125`) | `_save_reddit_json` (`opg:3150-3253`) | JSON array. Keys `user_id, username, name, bio(≤300), persona, karma, created_at, age, gender, mbti, country`, plus optional `profession, interested_topics, other_info{persona_design, actor_role{contract,prompt_sha256,prompt_chars}}`. Array index is the OASIS agent_id. |
| Twitter profiles | `<sim_dir>/twitter_profiles.csv` | `_save_twitter_csv` (`opg:3062-3123`) | CSV header `user_id,name,username,user_char,description`. `user_id` is the array index. `user_char` has newlines flattened. |
| Role manifests | `<sim_dir>/reddit_profiles_roles.json`, `<sim_dir>/twitter_profiles_roles.json` (`opg:2642-2645`) | `_save_role_prompt_manifest` (`opg:2647-2791`) | `actor-role-manifest/v2` (fields listed in the walkthrough). |
| Actor context packs (read) | `<sim_dir>/actor_context/<file>` (via `validate_actor_context_artifacts`, `opg:2851-2856`) | `actor_context.py` (not this slice) | `actor-context/v1`. Hashed and checked here (`opg:580-590`). |
| Prediction markets (read) | `<handoff_dir>/prediction_markets.json` (`opg:1423-1430`) | elsewhere | `{"markets":[{question, implied_yes_prob}]}` or a bare list. |
| LLM fallback telemetry | `<cwd>/llm_fallback.jsonl`, only if `<cwd>/simulation_config.json` exists (`ollm:284-296`) | `_record_llm_fallback` | JSONL `{ts, event, provider, tool_call, error}`. |
| stdout | — | `_print_generated_profile` (`opg:2549`), banners (`opg:2399-2401`, `2514-2516`) | full persona dumps |

**In-memory structures**
- `OasisAgentProfile` (`opg:89`).
- `profiles: List[Optional[OasisAgentProfile]]`, pre-allocated in entity order (`opg:2312`).
- `canonical_inputs: Dict[int, (actor, pack)]` (`opg:2297-2309`).
- `last_generation_stats` (`opg:2496-2501`).
- Per-instance caches `_communities_cache` (`opg:1099-1105`) and `_market_priors_cache` (`opg:1433`).
- Module-global `_LLM_FALLBACK_STATS` (`ollm:264`).

---

## Config / env knobs

| Name | Default (effective) | Effect | Anchor |
|---|---|---|---|
| `LLM_PROVIDER` | `claude-cli` | Persona LLM provider. In the sim, the env var takes priority over `config['llm_provider']`. | `opg:364`; `ollm:481-487`; `backend/app/config.py:750` |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | Config-derived | Persona LLMClient; HTTP sim model (env first, then Config) | `opg:365-367`; `ollm:509-511` |
| `LLM_BOOST_API_KEY` / `_BASE_URL` / `_MODEL_NAME` | empty | Reddit (`use_boost=True`) HTTP model override | `ollm:495-504` |
| `OPENAI_API_KEY` / `OPENAI_API_BASE_URL` | — | Last-resort read fallback for the HTTP sim model | `ollm:520-521` |
| `LLM_USER_AGENT` | `claude-cli/1.0.0` | UA injected for kimi | `ollm:544`; `backend/app/config.py:803` |
| `ZEP_API_KEY` | `local-graphiti` | Enables the graph client used for persona enrichment | `opg:378-386`; `backend/app/config.py:1038` |
| `SIM_ACTIVITY_PROFILE` (raw env) | unset → `None` | `us_business`/`global_market` switch personas to English | `opg:358-362` |
| `PROFILE_ZEP_SKIP_WHEN_CONTEXT` | True | Skip the graph search when the entity already has edges or nodes | `opg:1311-1313`; `backend/app/config.py:387` |
| `PROFILE_ZEP_SEARCH_MAX_RETRIES` | **3** (not defined in Config) | Graph search attempts | `opg:974`, `1175` |
| `PROFILE_ZEP_SEARCH_RETRY_DELAY_SECONDS` | **2.0** (not defined in Config) | Base backoff, doubled after each failure | `opg:975`, `1176` |
| `GRAPH_COMMUNITY_RETRIEVAL` | derived (see config) | Append the 群体身份 community block | `opg:1063`; `backend/app/config.py:1273-1275` |
| `PERSONA_EGO_RETRIEVAL` | False | Ego-network context block | `opg:1333`; `backend/app/config.py:380` |
| `PERSONA_EGO_MAX_NEIGHBORS` | **10** (not defined in Config) | Ego edge limit | `opg:1178` |
| `PERSONA_BEHAVIORAL_DNA` | True | DNA and roster blocks in the LLM prompt | `opg:1690`; `backend/app/config.py:383` |
| `SIM_PERSONA_DESIGN` | true | Request and normalize `persona_design`; rule-path design summary | `opg:1367-1374`; `backend/app/config.py:1413` |
| `SIM_MARKET_PRIORS` | true | Market-awareness hint for analyst/media types | `opg:1387-1394`; `backend/app/config.py:1419` |
| `PERSONA_FIELD_EXTRACTION` | true | "Don't invent demographics" wording versus the legacy wording | `opg:1983`, `2062`; `backend/app/config.py:566` |
| `ADAPTIVE_CONTEXT` | True | Budgeted persona-context cap instead of the floor | `opg:1949`; `backend/app/config.py:118` |
| `PERSONA_CONTEXT_FLOOR_CHARS` | 3000 | Floor of the context slice | `opg:1948`; `backend/app/config.py:125` |
| `RESERVED_COMPLETION_TOKENS` | 8192 | Reserved tokens in the context budget | `opg:1957`; `backend/app/config.py:120` |
| `SIM_ACTOR_ROLE_PROMPT_MAX_CHARS` | 6000, clamped to [1800, 12000] | Role prompt compile limit | `opg:641`, `812`; `backend/app/services/actor_role_prompt.py:2017-2027` |
| `PARALLEL_PROFILE_COUNT` | 16 (HTTP providers only; CLI 3) | `parallel_count` → thread-pool size | `backend/app/services/pipeline_orchestrator.py:12804-12816`; `opg:2404` |
| `SIM_CLI_TOOL_EMULATION` | true (env first, then Config) | JSON tool-call emulation on the CLI and fallback paths | `ollm:60-62`; `backend/app/config.py:602` |
| `SIM_LLM_FALLBACK` | true | LLMClient fallback on 422/429-class HTTP failures | `ollm:65-67`; `backend/app/config.py:603` |
| `OASIS_CLI_SEMAPHORE` | 8 | CLI in-flight cap (÷ platforms) | `ollm:613` |
| `OASIS_SEMAPHORE` | **30 in `oasis_llm`** (Config says 24) | HTTP in-flight cap (÷ platforms) | `ollm:615`; `backend/app/config.py:1091` |
| `LLM_*_DISABLE_THINKING` (via `Config.reasoning_extra_body`) | provider-specific | `extra_body` that disables reasoning on the HTTP sim model | `ollm:591-597`; `backend/app/config.py:826-843` |

---

## External calls

| Call | Where | Notes |
|---|---|---|
| `LLMClient.chat(messages, response_format={"type":"json_object"}, temperature=0.7/0.6/0.5)` | `opg:1776-1783` | Persona generation. Default `max_tokens=4096` (`backend/app/utils/llm_client.py:399-405`). CLI providers spawn subprocesses inside LLMClient. |
| Graph `zep_client.graph.search` (edges limit 30, nodes limit 20, rrf) | `opg:984-990`, `1008-1014` | Local Graphiti/FalkorDB facade (`backend/app/services/graphiti_client/client.py:316-345`) |
| Graph search, ego (node_distance, center uuid, edge_types filter) | `opg:1187-1195` | Facade supports these arguments (`backend/app/services/graphiti_client/runtime.py:1604-1699`) |
| Graph search, uuid resolution (nodes limit 5) | `opg:1134-1140` | Only when `entity.uuid` is missing |
| `get_runtime().list_communities(graph_id)` | `opg:1101-1102` | When `GRAPH_COMMUNITY_RETRIEVAL` is set |
| `PipelineManager.list_pipelines()` / `load()` and a file read | `opg:1415-1430` | Disk scan of every pipeline record |
| `CLIModel` → `LLMClient.chat` / `chat_json` | `ollm:426-443`, `465-469` | Every OASIS agent action on CLI providers |
| CAMEL `ModelFactory.create(OPENAI, …)` | `ollm:526-531` | HTTP sim model; network traffic happens at agent step time |
| `OpenAI` / `AsyncOpenAI` clients (kimi UA) | `ollm:552-553` | Client construction only |
| Fallback `LLMClient(provider).chat` | `ollm:328-340` | On 422/429-class HTTP failures |

---

## Cross-module edges

**Callers into `oasis_profile_generator.py`**
- `backend/app/services/simulation_manager.py:20`, `1046-1088` (generate), `1123-1137` (save), `1188-1221` (audience), `1262-1271` (validate and manifest path).
- `backend/app/api/simulation.py:13`; `314-329` (ready check); `1453-1464` (`/generate-profiles` standalone route). That route passes no actors and no graph_id, so there is no graph retrieval and no roles, and nothing is persisted.
- `backend/app/services/simulation_runner.py:689-757` (launch gate validation).
- `backend/scripts/run_parallel_simulation.py:584-617` (canonical Reddit system message enforcement).
- `backend/app/services/__init__.py:9`, `47-48` (re-export).
- `backend/scripts/test_profile_format.py:17-64` (manual script).
- Tests: `backend/tests/test_audit_fixes_prepare.py`, `test_sim_context_persona.py`, `test_faction_brief.py`, `test_actor_role_prompt.py`, `test_actor_cast_discipline.py`, `test_actor_context_runtime.py`, `test_oasis_v1_provenance.py`, `test_sim_market_priors.py`.

**Callers into `oasis_llm.py`**
- `backend/scripts/run_parallel_simulation.py:191`, `1735`, `4815`, `5368`. It also imports the private helpers `_estimate_tokens_of` (`:2132`) and `_resolve_provider` (`:2189`).
- `backend/scripts/run_twitter_simulation.py:118`, `740`, `876`.
- `backend/scripts/run_reddit_simulation.py:118`, `748`, `862`.
- Tests: `backend/tests/test_sim_meter_persistence.py`, `test_audit_fixes_runner.py`.

**Outbound from this slice**
- `utils/actors.py`: `match_actor`, `actor_briefing`, `relationship_briefing`, `behavioral_dna_block`, `roster_block`, `influence_weight`, `normalize_name`, `extract_actor_rows`, `ACTOR_INTELLIGENCE_SCHEMA_VERSION`.
- `services/actor_role_prompt.py`: `build_actor_role_contract` (`:937`), `compile_actor_role_prompt` (`:1653`), `role_prompt_sha256` (`:2013`), `resolve_actor_role_prompt_max_chars` (`:2017`), the sanitizers (`:122`, `:286`).
- `services/actor_context.py`: `actor_id_for`, `canonical_json_sha256`, `context_binding_by_actor_id` (`:1593`), `validate_actor_context_artifacts` (`:1501`).
- `services/graphiti_client`: `Zep` and the runtime.
- `services/pipeline_orchestrator.PipelineManager` (lazy import, `opg:1415`).
- `utils/token_budget.slice_budget_chars` (`opg:1952-1961`).
- `utils/atomic`.
- `utils/llm_client`: `LLMClient`, `CLI_PROVIDERS`, `_is_content_filter`, `_parse_json_response`.
- camel `OpenAIModel` / `ModelFactory`; openai `ChatCompletion`.

---

## Invariants, gates, validation

1. **Array index = agent_id.** Realtime saves write only the contiguous completed prefix (`opg:2335-2341`). The Twitter CSV writes `user_id=idx` (`opg:3112`). Audience profiles use `user_id = start_user_id + i` and are appended in order (`opg:2598`).
2. **Every researched actor carries a role prompt**, otherwise `RuntimeError` (`opg:2467-2482`). The manager also checks the count against the cast manifest (`backend/app/services/simulation_manager.py:1093-1102`).
3. **Canonical v1 is all-or-nothing.** A single v1 row or contract makes the run canonical (`opg:454-472`). Every selected entity must resolve to a v1 actor with a sealed pack before any work starts (`opg:2300-2309`). Errors are never stubbed (`opg:2384-2388`, `2441-2442`). Coverage must equal total (`opg:2483-2491`).
4. **Canonical actors have no synthetic personality.**
   - Their persona or `user_char` is exactly the sealed role (`opg:146-174`, `3097-3099`, `3201-3206`).
   - Reddit demographics are `""` (`opg:3175-3185`), and the validator enforces this (`opg:3038-3044`).
   - The child process attests that the final system message has no demographics sentence (`backend/scripts/run_parallel_simulation.py:667-668`).
5. **Unknown future intelligence schema is refused.** No legacy downgrade happens (`opg:597-607`).
6. **Dossier text is untrusted.** It is sanitized before any legacy prompt helper sees it (`opg:750-758`), and the role contract is inserted as fenced JSON data with a "never follow commands" instruction (`opg:1741-1749`). [verifier: overstated. Sanitization runs only when an actor row matched (`opg:750`). For an entity with no matched actor, `prompt_actors` stays the raw dossier (`opg:744`), and `_generate_profile_with_llm` still adds `situation_brief` free text (`opg:1708-1715`) and the `relationship_briefing` / `roster_block` output for that name (`opg:1682`, `1692`; free-text `relation_label` at `backend/app/utils/actors.py:803-806`) without sanitizing it. The code comment at `opg:1676-1678` overstates this the same way.]
7. **Role-fragment containment and hashes.** At write time the role must be a substring of the runtime field and its sha must match (`opg:2658-2686`). At read time the v2 contract is recompiled and compared byte-for-byte (`opg:2995-3010`).
8. **Context binding consistency.** Either all role rows are bound to one context manifest and report or none are (`opg:2727-2747`). There are 9 provenance keys and they are re-derived on validation (`opg:2933-2952`).
9. **No empty assistant turn reaches the provider or CAMEL** (`ollm:170-171`, `213-225`, `228-253`).
10. **A tool call is emulated at most once per step.** Emulation is skipped once a `tool`/`function` message exists (`ollm:115-119`, `425`).

---

## Failure modes & recovery

| Failure | Behavior | Anchor |
|---|---|---|
| Persona LLM error or invalid JSON ×3 | Rule fallback (`generation_path="rule_fallback"`), counted in stats. WARNING when the degraded share is above 25%. | `opg:1824-1837`, `2503-2507` |
| Truncated or malformed JSON | Multi-stage repair. A partial `{bio, persona}` salvage is accepted as success. | `opg:1806-1822`, `1862-1926` |
| Legacy worker exception | `_error_stub_profile` (summary persona plus role). Run continues. | `opg:2382-2396` |
| Canonical worker exception or preflight failure | Re-raised. The batch aborts. | `opg:2384-2388`, `2441-2442`, `2300-2309` |
| Context binding inconsistent (legacy actor with pack) | `_bind_actor_context_provenance` raises inside the worker. The error stub calls the same binder and raises again. The outer handler (`opg:2439-2455`) raises a third time, uncaught. The batch aborts after the `with` block waits for in-flight workers. [verifier: the first raise is at `opg:809-811`, after the LLM persona call at `opg:760-771`, so the LLM work is wasted. `ThreadPoolExecutor.__exit__` calls `shutdown(wait=True)` without `cancel_futures`. Every queued future therefore runs to completion, not only in-flight ones, so all remaining entities' LLM personas are still generated before the error surfaces (`opg:2404-2457`).] | `opg:886-888`, `2389-2395`, `2449-2455` |
| Graph search failure or timeout | Each search retries 3× (2s then 4s backoff), then returns empty context and logs a WARNING. Persona generation continues. | `opg:977-1023`, `1084-1087` |
| Ego / community / market lookups fail | Silently skipped, debug log only. Empty block. | `opg:1070-1071`, `1345-1347`, `1431-1432` |
| HTTP provider without key | `LLMClient` constructor raises → generator construction fails. `_create_openai_model` raises `ValueError` at sim start. | `opg:370-375`; `ollm:522-523` |
| HTTP sim 422/429/quota | Re-routed through `LLMClient` (its own retries, circuit breaker, `LLM_FALLBACK_PROVIDER`). If the fallback also fails, the **original** exception is raised. [verifier: this is not true when the fallback `LLMClient` cannot be constructed. That happens at `ollm:328`, outside the `try` at `ollm:330`, so the constructor's `ValueError` propagates instead.] | `ollm:348-376`, `320-345` |
| HTTP sim other errors (5xx, timeouts) | Not intercepted. Propagate into OASIS/CAMEL. | `ollm:357-358` |
| CLI tool reply unparseable | Plain-text reply with no tool_calls, so the agent takes no action that step (INFO log). | `ollm:431-434` |
| Tool emulation disabled | WARNING at model creation and per call. The run will be "hollow". | `ollm:572-576`, `436-437` |
| Realtime save failure | WARNING only. The final `save_profiles` is authoritative. | `opg:2350-2351` |
| Manifest/profile tampering or staleness | `validate_role_prompt_manifest` raises `ValueError`. Callers translate it into a not-ready state or a launch refusal. | `opg:2793-3060`; `backend/app/api/simulation.py:330-334`; `backend/app/services/simulation_runner.py:758-759` |

---

## Surprises

1. **Doc-vs-code drift (persona assembly).**
   - `ARCHITECTURE_MAP.md:257` and `DRF_ARCHITECTURE.md:823-829` place `generate_profile_from_entity` at `:305` and `OasisAgentProfile` at `:47`. Both are stale: the actual lines are `opg:688` and `opg:89`. [verifier: only `DRF_ARCHITECTURE.md:829` gives `OasisAgentProfile` (`:47`). `ARCHITECTURE_MAP.md` gives `:305` (line 257) but no line for `OasisAgentProfile` (line 260). The "JSON keyed by `user_id`" wording is also in `ARCHITECTURE.md:251`.]
   - They say the base persona is built "from the entity's Zep ego-network context". **Ego retrieval is off by default** (`backend/app/config.py:380`; `opg:1333`), and canonical v1 actors get no LLM base persona at all (`opg:721-729`).
   - They say `to_twitter_format` → CSV and `to_reddit_format` → "JSON keyed by user_id". The writers are actually `_save_twitter_csv` / `_save_reddit_json`. The Reddit file is a **JSON array** (`opg:3173`, `3250`), and `to_*_format` serves only the `/generate-profiles` API (`backend/app/api/simulation.py:1459-1464`).
2. **Doc-vs-code drift (oasis_llm).**
   - `ARCHITECTURE.md:407-412` says `CLIModel` "ignores `tools=`" and that the CLI semaphore is 3. The code emulates tool calls (`ollm:425-434`) and the default CLI cap is 8 (`ollm:29`).
   - `ARCHITECTURE_MAP.md:759`, `884` also say "3 CLI".
3. **Semaphore default disagreement (suspected drift).**
   - `Config.OASIS_SEMAPHORE` defaults to **24** (`backend/app/config.py:1091`), and its own comment claims byte-parity with `oasis_llm`'s **30** (`backend/app/config.py:1085-1086`).
   - `get_oasis_semaphore` ignores `Config` and reads only the environment, defaulting to 30 (`ollm:615`). `simulation_runner` also assumes 30 (`backend/app/services/simulation_runner.py:2732`).
   - So when the env var is unset, the real HTTP cap is 30, not the documented 24.
4. **Phantom Config knobs.**
   - `PROFILE_ZEP_SEARCH_MAX_RETRIES`, `PROFILE_ZEP_SEARCH_RETRY_DELAY_SECONDS` and `PERSONA_EGO_MAX_NEIGHBORS` are not defined in `config.py`. The `getattr` fallbacks (3, 2.0s, 10) always apply.
   - The comment at `opg:971-973` claims the defaults were "tightened to 2 tries / 0.5s". That is false in this checkout.
5. **Stale ego docstring.** `_retrieve_ego_network`'s docstring says the facade ignores `center_node_uuid` / `search_filter` until "proposal 1" lands (`opg:1167-1169`). The facade already forwards them (`backend/app/services/graphiti_client/client.py:324-345`; `runtime.py:1694-1699`).
6. **Search timeout does not bound wall time (suspected).** `future.result(timeout=30)` raises inside a `with ThreadPoolExecutor` block. `__exit__` then calls `shutdown(wait=True)`, so the caller still waits for the retrying searches to finish (`opg:1027-1033`, `1084-1085`).
7. **Demographic stripping undone on disk.**
   - C5 drops age/gender/MBTI for non-individual legacy entities (`opg:793-796`).
   - `_save_reddit_json` then backfills `age=30`, `gender="other"`, `mbti="ISTJ"` and, in Chinese mode, `country="中国"` (`opg:3187-3192`).
   - OASIS' Reddit template then prints those values to the agent.
   - The rule base also hard-codes `country="中国"` for media and institutions regardless of the actual nationality (`opg:2221`, `2233`). The audience generator does the same in Chinese mode (`opg:2610`).
8. **Individual/group classification is narrow.** It is an exact lowercase match against 10 types (`opg:302-305`, `1359-1361`). Types such as Analyst, Politician or Executive therefore get the **institution** prompt with forced `age=30` and `gender="other"` (`opg:1698-1705`, `2095-2096`). This holds even for market-aware analysts (`opg:317-321`).
9. **Requested fields are discarded.** Both LLM prompts ask for optional `values`, `beliefs` and `incentives` (`opg:2032-2035`, `2102-2105`). `generate_profile_from_entity` never reads them (`opg:831-850`).
10. **Influence weighting is applied only on the rule path.** `influence_weight` scaling of follower/friend/karma exists only in `_generate_profile_rule_based` (`opg:2153-2157`). Successful LLM personas always get **random** counts (`opg:837-840`). This is the opposite of what one would want for high-influence actors. [verifier: "always" is overstated. `profile_data.get("karma", random…)` (`opg:837-840`) uses any `karma`/`friend_count`/`follower_count`/`statuses_count` the LLM JSON happens to include, unvalidated. The prompts never ask for these keys (`opg:2017-2036`, `2084-2105`), so in practice the counts are random.]
11. **Non-determinism.** `random` is never seeded in this module. Usernames (`opg:935`), social counts (`opg:837-840`), rule demographics (`opg:2194-2246`) and audience fields (`opg:2603-2609`) therefore differ run-to-run. Username uniqueness is not checked.
12. **Mislabeled backoff.** The persona LLM retry sleeps linearly (1s, 2s, 3s), sleeps even after the final attempt, and is commented as exponential (`opg:1828`).
13. **Stats claim vs consumers.** The comment says `last_generation_stats` feeds `config_reasoning` (`opg:2459-2462`). The only consumer reads `role_prompts` (`backend/app/services/simulation_manager.py:1093-1097`), and no code outside this file reads `rule_fallback` or `error_stub` (grep).
14. **Dead or unused code.**
    - The `ZepEntityReader` import (`opg:54`).
    - `_is_group_entity` (`opg:1363-1365`), together with `GROUP_ENTITY_TYPES`.
    - The `is_individual` parameter of `_get_system_prompt` (`opg:1928-1939`).
    - The `save_profiles_to_json` alias (`opg:3256-3264`).
    - `get_llm_fallback_stats` is used only by tests (`ollm:267-269`).
    - `use_boost` is unused in `get_oasis_semaphore` (`ollm:603`).
    - Redundant local `import re` / `import time` (`opg:1440`, `1841`, `1864`, `1827`).
15. **Context cap is effectively unbounded.** With `ADAPTIVE_CONTEXT=True` (the default) and no `cap_tokens`, the persona context cap is about 307K characters for claude-cli (`opg:1955-1961`; `backend/app/utils/token_budget.py:106-118`). Meanwhile `_build_entity_context` lists all related edges and nodes with no limit (`opg:1264`, `1290`). Prompts for hub entities can therefore be very large. [verifier: this applies only to entities with no matched actor row. For a matched legacy actor, `prompt_context = sanitize_untrusted_dossier_text(context, 12000)` (`opg:758`) truncates the context to 12,000 chars (`backend/app/services/actor_role_prompt.py:254-257`) before the ~306,892-char cap applies. Also, (200000-8192)×0.4×4 = 306,892 is claude-cli-specific. HTTP providers with larger windows get bigger caps, e.g. about 806K for minimax (`backend/app/config.py:131-141`).]
16. **`reasoning_extra_body` uses the global provider (suspected).** `create_oasis_model` calls `Config.reasoning_extra_body()` without the resolved provider (`ollm:591`). `Config`'s own comment warns that omitting the provider makes a different client inherit the primary's `thinking.type=disabled` payload (`backend/app/config.py:832-835`). If `simulation_config.json`'s `llm_provider` differs from `Config.LLM_PROVIDER`, the wrong body may be sent. [verifier: the trigger is narrower than stated. `_resolve_provider` prefers env `LLM_PROVIDER` (`ollm:483`), and `Config.LLM_PROVIDER` is read from the same env var (`backend/app/config.py:750`) after `load_dotenv(override=True)` (`backend/app/config.py:21`). The runtime provider switch also writes `os.environ` and `.env` (`backend/app/config.py:973-975`). The mismatch therefore needs env/.env `LLM_PROVIDER` to be unset while `config['llm_provider']` carries a non-default value. A config mismatch alone does not trigger it.]
17. **Boost key without base URL (suspected).** Setting `LLM_BOOST_API_KEY` without `LLM_BOOST_BASE_URL` sends Reddit traffic to `OPENAI_API_BASE_URL` or the OpenAI default endpoint, not the configured provider's URL (`ollm:500-503`, `521`, `530`).
18. **Guards cover only chat completions.** The empty-assistant and fallback guards wrap `_request_chat_completion` / `_arequest_chat_completion` only. CAMEL's `_request_parse` path, used when a `response_format` is set, is unguarded on HTTP providers (`ollm:228-253`, `348-376`; `camel/models/openai_model.py:306-315`).
19. **CSV validation and Unicode line separators (suspected edge bug).** `validate_role_prompt_manifest` parses the CSV with `str.splitlines()` (`opg:2862`). That also splits on `\x0b`, `\x0c`, `\x1c-\x1e`, `\x85`, ` ` and ` `, but the writer only flattens `\n` and `\r` (`opg:3106`). A legacy persona containing one of those characters would fail validation even though the CSV is valid. Whether the sanitizers remove them on role-bearing rows was not verified. [verifier: resolved. `sanitize_untrusted_research_text` removes `\x0b`, `\x0c` and `\x1c-\x1f` (`backend/app/services/actor_role_prompt.py:158`) but not `\x85`, U+2028 or U+2029; NFKC (`:155`) leaves them unchanged. The one exception is right after sentence punctuation, where the `\s+` split at `:233` turns them into a space. A stdlib reproduction confirmed both failure modes. A quoted field loses the character, which breaks the `runtime_profile_sha256` check (`opg:2887`). An unquoted field splits into an extra row, which breaks the `profile_count` check (`opg:2869`).]
20. **No type validation of LLM fields.** `age` may come back as a string and `interested_topics` as a string. Both are written to disk unchanged (`opg:841-846`, `3210`, `3224`). A string topic would also be joined character-by-character in `_print_generated_profile` (`opg:2525`).
21. **Manifest rewrites per completion.** Every realtime prefix save rewrites the profile file **and** re-hashes and rewrites `*_roles.json` (`opg:2347-2349`, `3250-3251`). Profile and manifest are two separate atomic writes, so a concurrent reader can briefly see a mismatched pair.
22. **`temperature 0` is coerced.** In `CLIModel` and `_fallback_completion`, `float(cfg.get('temperature', 0.7) or 0.7)` turns an explicit 0 into 0.7 (`ollm:325`, `419`, `462`). [verifier: at `ollm:462` (`CLIModel._request_parse`) the fallback is 0.3, so an explicit 0 becomes 0.3 there, not 0.7. In all three places `max_tokens=0` is likewise coerced to 4096 (`ollm:326`, `420`, `463`).]

---

## Verification

An adversarial verifier checked this map against the main-branch checkout on disk on 2026-10-11. Every key claim and surprise was re-read at its cited lines. In addition, 17 walkthrough, control-flow and invariant statements were spot-checked. Statements found wrong or imprecise carry an inline `[verifier: …]` note above.

### Verdict counts

| Group | Checked | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims | 14 | 13 | 1 | 0 |
| Surprises | 17 | 12 | 5 | 0 |
| Extra spot-checks | 17 | 12 | 5 | 0 |
| **Total** | **48** | **37** | **11** | **0** |

Nothing was refuted. The load-bearing behaviour all checks out:
- the canonical v1 run-level switch and synchronous preflight;
- no LLM call and no graph retrieval for canonical actors;
- the 3-attempt persona loop with linear 1s/2s/3s sleeps;
- legacy error stubs versus canonical re-raise;
- the role-prompt coverage gates;
- contiguous-prefix realtime saves;
- the Reddit/Twitter writers;
- the `actor-role-manifest/v2` writer and validator;
- the phantom `PROFILE_ZEP_*` / `PERSONA_EGO_MAX_NEIGHBORS` knobs;
- the `oasis_llm` CLI tool emulation, fallback guard, semaphore and synthetic completions.

### Non-confirmed statements, with corrections

1. **Key claim, fallback guard ("re-raises the original exception if the fallback also fails").** *Imprecise.*
   - `LLMClient(provider=provider)` is constructed at `ollm:328`, outside the `try` at `ollm:330`.
   - A construction failure (unsupported provider `backend/app/utils/llm_client.py:266-270`, or a missing API key `:289-290`) therefore propagates its own `ValueError`, not the original exception.
   - Also annotated at the failure-mode table row.
2. **Surprise 1, doc drift.** *Imprecise attribution.*
   - Only `DRF_ARCHITECTURE.md:829` puts `OasisAgentProfile` at `:47`. `ARCHITECTURE_MAP.md:260` gives no line for it.
   - The `:305` drift is in both docs (`ARCHITECTURE_MAP.md:257`, `DRF_ARCHITECTURE.md:823`).
   - "JSON keyed by user_id" also appears in `ARCHITECTURE.md:251`.
3. **Surprise 10, "LLM personas always get random counts".** *Overstated.*
   - Any `karma`/`friend_count`/`follower_count`/`statuses_count` in the LLM JSON is used unvalidated (`opg:837-840`).
   - The prompts never request these keys, so in practice the counts are random.
4. **Surprise 15, context cap "effectively unbounded".** *Imprecise.*
   - For actor-matched legacy entities the context is first truncated to 12,000 chars (`opg:758`; `backend/app/services/actor_role_prompt.py:254-256`).
   - The ~306,892-char cap matters only for entities with no actor match. It is claude-cli-specific; minimax gets about 806K (`backend/app/config.py:131-141`).
5. **Surprise 16, `reasoning_extra_body` without provider.** *The code fact is confirmed, but the trigger is narrower than stated.*
   - `_resolve_provider` prefers env `LLM_PROVIDER` (`ollm:483`), and `Config.LLM_PROVIDER` reads that same env var (`backend/app/config.py:750`) after `load_dotenv(override=True)` (`:21`).
   - The runtime provider switch also writes `os.environ` and `.env` (`:973-975`).
   - A mismatch therefore needs env/.env `LLM_PROVIDER` to be unset while `simulation_config.json` carries another provider.
   - The boost-key/base-URL half of the surprise is confirmed (`ollm:500-503`, `521`, `530`).
6. **Context-binding triple raise (failure table row and key surprise).** *Imprecise.*
   - The first raise is at `opg:809-811`, after the LLM call (`opg:760-771`).
   - `ThreadPoolExecutor.__exit__` → `shutdown(wait=True)` runs all queued futures, not only in-flight ones. Every remaining entity's LLM persona is generated before the abort surfaces (`opg:2404-2457`).
7. **Walkthrough `_search_zep_for_entity`, "partial results are returned" on timeout.** *Imprecise.* `results` is filled only after both futures resolve (`opg:1027-1059`), so a timeout returns the empty initial dict (`opg:958-962`).
8. **Walkthrough `_save_role_prompt_manifest`, "`reddit_system_message_version/_sha256/_chars`".** *Imprecise key names.* The real keys are `reddit_base_system_message_sha256` / `_chars` (`opg:2716-2722`).
9. **Walkthrough `_create_openai_model`, "else gpt-4o-mini".** *Imprecise.* `config.get("llm_model", "gpt-4o-mini")` returns `""` when the key exists but is empty. `simulation_config.json` always writes it (`backend/app/services/simulation_config_generator.py:388`).
10. **Invariant 6, "sanitized before any legacy prompt helper sees it".** *Overstated.*
    - Sanitization runs only when an actor matched (`opg:750`).
    - Unmatched entities get the raw dossier's `situation_brief` (`opg:1708-1715`), `relationship_briefing` and `roster_block` (`opg:1682`, `1692`).
    - The code comment at `opg:1676-1678` overstates this the same way.
11. **Surprise 22, temperature-0 coercion.** *Imprecise.* At `ollm:462` an explicit 0 becomes 0.3, not 0.7. `max_tokens=0` is likewise coerced to 4096 (`ollm:326`, `420`, `463`).

**Surprise 19 resolved (confirmed).**
- The sanitizer strips `\x0b`, `\x0c` and `\x1c-\x1f` (`backend/app/services/actor_role_prompt.py:158`) but not `\x85`, U+2028 or U+2029.
- A stdlib `csv` reproduction showed a quoted field losing the character, which breaks the sha check at `opg:2887`. An unquoted field splits into an extra row, which breaks the count check at `opg:2869`.

**Anchor nit (confirmed claim).** The `chatcmpl-cli-` prefix test itself is at `backend/scripts/run_parallel_simulation.py:2111`; `:2100` is its docstring.

### Omissions (behaviour the map does not cover)

1. **A progress callback failure counts as a generation failure.**
   - The `as_completed` `try` (`opg:2416-2438`) also wraps `save_profiles_realtime()` and `progress_callback(...)`.
   - If the callback raises, a legacy run overwrites the already-stored good profile with an error stub and increments `completed_count` twice (`opg:2418-2421`, `2443-2455`).
   - A canonical run aborts (`opg:2441-2442`).
2. **Aborts do not cancel queued work.** The `with ThreadPoolExecutor` exit (`opg:2404`) waits for every submitted future. A canonical re-raise (`opg:2442`) or a legacy third raise (`opg:2449-2455`) still lets all remaining entities generate, including LLM calls on the legacy path, before the exception reaches the caller.
3. **Legacy context binding runs after the LLM call.** `_bind_actor_context_provenance` (`opg:808-811`) runs only after `_generate_profile_with_llm` (`opg:760-771`). A binding defect therefore burns up to 3 LLM attempts per entity before failing.
4. **The community (群体身份) block is reachable only for cold entities.** It lives inside `_search_zep_for_entity` (`opg:1063-1071`), which `PROFILE_ZEP_SKIP_WHEN_CONTEXT=True` skips for any entity with related edges or nodes (`opg:1311-1318`). `GRAPH_COMMUNITY_RETRIEVAL` defaults to off through `GRAPH_BUILD_COMMUNITIES=false` (`backend/app/config.py:1266`, `1273-1277`).
5. **More non-determinism.** Graph-search facts and node summaries pass through `set()` before the `[:20]` / `[:10]` / `[:15]` slices (`opg:1036-1058`, `1324-1327`). Which items survive therefore depends on per-process string-hash order, on top of the unseeded `random` already noted.
6. **Audience step failures are non-fatal (caller side).** The audience-profile append and re-save in `SimulationManager` sits inside a `try/except` that only logs a warning (`backend/app/services/simulation_manager.py:1193-1221`). A failure leaves profile files without the audience agents the config expects. This qualifies control-flow step 7.
7. **A non-string LLM `gender` crashes the save.** `_normalize_gender` calls `gender.lower()` (`opg:3134`), so a numeric or list `gender` from the LLM, which is kept for individual entities (`opg:795`), raises `AttributeError`. The final `save_profiles` then fails; the realtime save only warns. This extends surprise 20.
