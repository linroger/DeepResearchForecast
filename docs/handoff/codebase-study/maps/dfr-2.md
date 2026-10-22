# dfr-2 — deerflow_research.py part 2: source support normalization, intelligence claims, relationships, actor artifacts, research/synthesis prompts

Slice owned: `deerflow_bridge/deerflow_research.py` lines 2925–6095 (file is 17,986 lines). Every line of the slice was read. Helpers outside the slice were read only far enough to say what they do. All anchors are `path:line` relative to the repo root. Branch: `main`, checkout on disk.

## Purpose & position in the pipeline

The research bridge (`deerflow_bridge/deerflow_research.py`) runs as a subprocess started by the backend orchestrator (`backend/app/services/pipeline_orchestrator.py:2206`, `:2100`). This slice holds four groups of code that sit at the boundaries of Stage 1, deep research:

1. **The actor-intelligence/v1 producer boundary** (`2925–4406`). It takes the model-extracted `actors.json`, admits only claims whose quotes appear in fetched, receipted source content, builds canonical relationship edges, assigns content-addressed claim/relationship/actor IDs, fills every empty dimension with an explicit evidence gap, and seals the result. The seal is cross-checked against the Track-B actor dossier audit, called "Plan A", and written as `actors.json` + `sources.json` + `actor_intelligence_lineage.json` + `meta["actor_intelligence"]`. The code calls `actors.json` "Plan B". Downstream graph and persona stages consume this output.
2. **Runtime plumbing** (`4409–4616`). It covers the `ProgressLog` event stream that the orchestrator tails on stdout, cross-process model-call leasing, subagent slot and fan-out selection, and the agentic-delegation prompt block.
3. **Citation contract (WAVE9-RQ)** (`4619–4839`). It covers the `[S<n>]` citation index, parsing a report's References section, stripping dangling markers, and the deterministic citation finalizer that runs before the report is written to disk.
4. **Research and synthesis prompts plus multipart-synthesis pure helpers** (`4842–6093`). These are the research-pass prompt builders (standard, deep opening, deep phase, coverage top-up, gap closing), the single-call synthesis prompt, and the SCALE-1 multipart planner: outline prompt, parse, default skeleton, deliverable enforcement, word and token budgeting, keyword context routing, notes digest, prose word count, cross-section shingle dedup, stitching, and per-section acceptance clauses. The orchestrating driver `synthesize_multipart` (`deerflow_research.py:6640`) is outside the slice. It calls these helpers. [verifier: the `def synthesize_multipart` line is `deerflow_bridge/deerflow_research.py:6641`; :6640 is a blank line (deerflow_research.py:6641)]

## Walkthrough (source order)

### A. Source-support binding and claim identity

**`_normalize_source_support(value, raw_refs, source_lookup)` — `deerflow_bridge/deerflow_research.py:2925`**
- Purpose: turns a claim's model-proposed support rows into verified rows. Each verified row is bound to a fetched source's `receipt_id` and `content_sha256`, plus a supporting span inside that source's stored text.
- Inputs: the claim dict `value`, `raw_refs` (flattened ref fields of the claim), and `source_lookup`. The lookup is expected to be a `_SourceLookup` (`:2664`) carrying `.records` (source_id→row) and the required receipt purpose, lane and thread (`:2931–2940`). A plain dict yields `records={}`, so every row is dropped.
- Candidates are taken from `value["source_support"]`, `"evidence_support"` or `"supporting_evidence"` (`:2941–2945`). If none exist, one synthetic candidate is built from `supporting_quote`/`exact_quote`/`source_quote` (`:2946–2957`). It gets `source_ref = raw_refs[0]` only when there is exactly one raw ref (`:2954`).
- Per candidate (`:2960–3052`):
  - It must be a dict.
  - The ref comes from `source_ref`/`source_id`/`url`/`ref`. If that is missing and there is exactly one raw ref, that ref is used (`:2963–2970`).
  - The ref is resolved via `normalize_source_refs` (`:2854`). Resolution must yield exactly one source ID (`:2971–2973`).
  - The source row must exist in `records` (`:2975–2977`).
  - Receipt scope: `_source_receipt_scope(source, purpose, lane, thread)` (`:2723`). When a purpose is required and no scope matches, the candidate is dropped (`:2984–2985`). If no purpose is required, the code falls back to any scope or a blank one (`:2986–2993`).
  - It requires a non-empty `receipt_id` and a 64-hex `content_sha256` (`_valid_content_sha256`, `:2921`) (`:2994–3003`).
  - A model-supplied `receipt_id` or `content_sha256` must match the ledger exactly, or the row is dropped (`:3004–3009`).
  - The quote comes from `supporting_quote`/`exact_quote`/`quote`/`text` (`:3010–3016`). `_supporting_span(source content or excerpt, quote)` (`:2899`) must find it, either as an exact substring (`basis: exact_excerpt`) or after NFKC + casefold + whitespace collapse (`basis: normalized_excerpt`) (`:3017–3019`). [verifier: it is content OR excerpt, not both. `_source_support_text` returns `content` whenever it is a non-blank string and falls back to `excerpt` only when content is missing or blank. A quote that appears only in `excerpt` is dropped when `content` is non-empty (deerflow_research.py:2891–2896, :3017)]
  - A supplied `supporting_span`/`span` must have integer start and end. For `exact_excerpt` it must equal the computed span. For a normalized match it is not compared (`:3020–3032`).
  - Rows are deduped on `(source_id, normalized quote)` (`:3033–3036`).
- Output: list of `{source_id, supporting_quote, supporting_span, receipt_id, content_sha256, source_publication_date (publication_date|published_at|date), thread_id, lane, purpose}` (`:3037–3052`).
- No side effects other than reading the lookup.

**`_claim_text(value)` — `:3056`**
- Returns the first non-empty field among `claim, summary, fact, detail, description, plan, action, investment, decision, preference, value` (`:3057–3063`).
- Otherwise it joins `key=value` pairs for `driver, gains_if, loses_if, status, horizon, dependencies, trigger, basis` with `"; "` (`:3064–3072`).

**`_claim_projection_payload(actor_id, dimension, claim)` — `:3075`**
- Builds the canonical identity projection. Support rows are reduced to `{source_id, sha256(normalized quote), receipt_id, content_sha256}` and sorted (`:3080–3094`).
- The projection is: actor_id, dimension, whitespace-collapsed claim text, evidence_type, claim_valid_at, horizon, status, confidence, sorted deduped dependencies and contradictions, raw `qualifiers`, and the support projection (`:3095–3114`).
- Spans, publication dates and thread/lane/purpose are not in the identity.

**`_assign_claim_identity(claim, *, actor_id, dimension, causal_attributes=None)` — `:3117`**
- Optionally adds `causal_attributes` to the projection (`:3125–3126`).
- Then it takes the SHA-256 of compact JSON with sorted keys and ensure_ascii=False (`:3127–3133`).
- It sets `claim["claim_id"] = "claim_" + digest[:20]` and `claim["claim_sha256"] = digest`, mutating the claim in place (`:3134–3136`).

**`_normalize_intelligence_claim(value, source_lookup, default_as_of, *, actor_id, dimension, causal_attributes)` — `:3139`**
- Dict input:
  - The text comes from `_claim_text` (`:3149`).
  - Refs are collected from `source_refs, sources, source_urls, source_ids, citations, evidence_refs` on the value and on its `qualifiers` (`:3154–3160`).
  - `claim_valid_at` comes only from the claim's own `claim_valid_at|valid_at|as_of_date|as_of`, either top level or in qualifiers. It is never taken from a source date or the global cutoff (comment `:3161–3163`, code `:3164–3174`).
  - `confidence` defaults to `unknown` (`:3175–3178`).
  - `evidence_type`/`epistemic_status` is lower-cased with `-`/space→`_` (`:3179–3183`).
  - Also read: `horizon`, `status`, `dependencies`, `contradictions` (`:3184–3201`).
  - Qualifiers are restricted to `_ACTOR_INTELLIGENCE_QUALIFIER_KEYS` (`:2619`) (`:3202–3208`). A boolean `actor_knows` is kept (`:3209–3213`). `visibility` is kept only if it is in `_ACTOR_KNOWLEDGE_VISIBILITY_VALUES` (`:2632`) (`:3214–3218`).
  - Support comes from `_normalize_source_support` (`:3219–3223`).
- Non-dict input (for example a legacy string): the text is `str(value)` and all metadata is unknown or empty, including `source_support=[]` (`:3224–3235`). Such a claim can never be grounded.
- An empty text returns `None` (`:3236–3237`).
- Confidence values outside {high, medium, low, unknown} and evidence types outside {verified_fact, actor_stated_claim, analyst_inference, contested, unknown} are coerced to `unknown` (`:3238–3244`).
- `default_as_of` is explicitly discarded (`del`, `:3245`).
- Output dict: `claim, evidence_type, claim_valid_at, as_of_date (alias of claim_valid_at), horizon, status, confidence, source_refs (sorted IDs derived only from verified support rows), source_support, dependencies, contradictions, qualifiers`. Identity is then assigned (`:3246–3270`).

### B. Legacy fields, relationships, evidence gaps

**`_legacy_actor_dimension_values(actor, dimension)` — `:3273`**
- A fixed mapping from pre-v1 actor fields into the 17 v1 dimensions (`ACTOR_INTELLIGENCE_DIMENSIONS`, `:2580`). Examples:
  - `identity_history ← description + history` (`:3275–3276`)
  - `values_worldview ← worldview.{values,beliefs,identity,frame} + values + beliefs` (`:3277–3286`)
  - `capabilities ← capabilities + resources + assets` (`:3291–3296`)
  - `operational_preferences ← operational_preferences + operational_aversions only`. Generic likes and dislikes are deliberately excluded (`:3299–3305`).
  - `knowledge_state ← knowledge_state + known_context + memory` (`:3329–3334`)
- Unknown dimensions return `[]` (`:3335`).
- `alliances` and `opponents_competitors` have no legacy mapping.

**`_relationship_dimension_claims(actor, relationships, dimension)` — `:3338`**
- Turns canonical relationships into claim candidates for `alliances` and `opponents_competitors`.
- Allied types: `{ALLY_OF, SUPPORTS, PARTNERS_WITH, BACKS, FUNDS, INVESTS_IN}`. Opposed types: `{OPPOSES, COMPETES_WITH, SANCTIONS, CRITICIZES, LITIGATES_AGAINST}`. Any dimension other than `alliances` selects the opposed set (`:3344–3346`).
- Matches the actor by `_cast_norm` name against either endpoint (`:3356`).
- The claim text is `"<TYPE> <other>[: basis]"` (`:3361`).
- `claim_valid_at ← claim_valid_at|as_of_date|since` (`:3362–3367`).
- **Defaults:** `horizon="current"`, `status="active"`, `evidence_type`/`confidence` `"unknown"` (`:3368–3371`).
- It carries the relation's `source_refs`/`sources`, `source_support` and `qualifiers` (`:3372–3374`).

**`_RELATIONSHIP_CAUSAL_ATTRIBUTE_KEYS` — `:3379`**
- `valence, polarity, sign, strength, grade, since, until, lag`.

**`_normalized_relationship_causal_attributes(relationship)` — `:3391`**
- For each key, takes the top-level value or falls back to `qualifiers`. Empty values are skipped (`:3400–3405`).
- Strings are NFKC-normalized and whitespace-collapsed (`:3406–3411`). Bools and finite ints/floats are kept (`:3412–3419`). A NaN or inf float raises `ValueError("…must be finite")` (`:3415–3418`). Any other type raises `ValueError("…must be a JSON scalar")` (`:3420–3423`).

**`_canonicalize_relationships(obj, actors, source_lookup)` — `:3428`**
- Builds `endpoint_lookup` from each actor's `_cast_norm` name and aliases (`:3434–3443`).
- For each `obj["relationships"][index]` (`:3448`), in order:
  - A non-dict is omitted with reason `relationship_not_object`. Its hash is `sha256(repr(raw))` (`:3449–3457`).
  - Either endpoint missing from the roster → `relationship_endpoint_not_in_simulation_roster` (`:3465–3473`).
  - The type is upper-cased and must match `[A-Z][A-Z0-9_]{1,63}`, else it becomes `OTHER` (`:3474–3476`).
  - The basis comes from `basis|claim|description` (`:3477–3482`).
  - Causal attributes are normalized. A `ValueError` → omitted with `relationship_causal_attribute_not_scalar` (`:3483–3491`).
  - A claim copy is built with `claim=basis`. Before claim normalization, `type`, `basis` and all causal keys are removed from the top level and from qualifiers (`:3492–3505`). [verifier: `type` and `basis` are popped only from the top level. Only the causal keys are filtered out of `qualifiers`. Because `type` and `basis` are whitelisted qualifier keys (`:2621`, `:2622`), a `qualifiers.type` or `qualifiers.basis` survives into the normalized claim (deerflow_research.py:3496–3505, :3202–3208). Also, when `basis` is empty, `_claim_text` falls back to other fields. A relationship that carries `status`/`horizon` therefore gets a synthetic basis such as `"status=active; horizon=current"` and can be admitted. Verified at runtime (deerflow_research.py:3064–3072, :3493)]
  - `_normalize_intelligence_claim(..., actor_id=<source actor_id>, dimension="relationship", causal_attributes=...)` (`:3506–3513`). No claim, or no `source_support` → omitted with `no_quote_bound_fetched_source_support` (`:3514–3520`).
  - `relationship_id = "relation_" + sha256({source_actor_id, target_actor_id, type, relation_label, claim_sha256, causal_attributes})[:20]` (`:3521–3537`).
  - **A duplicate relationship_id raises `ValueError`** naming both indexes (`:3538–3543`).
  - The admitted row carries canonical source/target names and actor_ids, type, relation_label, basis, all normalized claim fields, `claim_id`/`claim_sha256`, and the flattened causal attributes (`:3545–3567`).
- Side effect: it overwrites `obj["relationships"]` with the admitted rows and sets `obj["relationship_omission_audit"]`. Omitted rows are hashed only; their content is not stored (`:3568–3570`).

**`_canonical_actor_evidence_gap(value)` — `:3573`**
- A dict gap becomes `{reason (whitespace-collapsed), attempted_queries (deduped via _search_query_from_args :1621), receipt_ids, result_ids, attempt_count (int ≥0, bool→0, invalid→0), exhausted (only literal True)}` (`:3582–3614`).
- A string becomes the same shape with zero attempts and `exhausted=False` (`:3615–3625`). An empty string returns `None`.
- A dict with an empty reason is still returned.

### C. Contract normalization

**`normalize_actor_intelligence_contract(obj, *, report, dossier, sources, generated_at=None, required_receipt_purpose="track-b", required_receipt_thread_id="")` — `:3628`**
1. A non-dict input raises `TypeError` (`:3645–3646`).
2. `_canonical_source_lookup(source_rows, purpose, lane="track-b" when purpose is track-b, thread)` (`:3648–3655`, helper `:2780`). It admits only fetched rows (`_source_is_fetched`, `:2647`) carrying a matching receipt scope. **It assigns `source["source_id"]` in place**, using `stable_source_id(url)` (`:1348`).
3. `canonical_sources` = compact JSON of the source rows sorted by source_id. This is computed after the lookup mutated IDs (`:3656–3661`).
4. `actors = _normalize_actor_simulation_roster(obj)` (`:3662`, helper `:2431`). It infers or persists `simulation_tier`, raises `ValueError` on homonyms or alias overlap, keeps only Tier 1/2 in `obj["actors"]`, and moves Tier 3/4 to `context_entities`.
5. Actor IDs are producer-owned: `stable_actor_id(name)` (`:1364`). A collision raises `ValueError` (`:3669–3683`). Tier 1/2 actors are counted and their normalized names collected (`:3684–3686`).
6. `_canonicalize_relationships` is called (`:3688–3692`).
7. For each actor and each of the 17 dimensions (`:3695–3808`):
   - Candidates are, in order: `intelligence.dimensions[dim]` (or the flat `intelligence[dim]` when there is no `dimensions` dict, `:3701–3705`), then legacy fields, then relationship-derived claims for `alliances`/`opponents_competitors` (`:3717–3721`).
   - Each candidate is normalized and deduped on `claim_sha256` (`:3724–3737`).
   - **A claim with no source_support is dropped.** Only `{dimension, reason, sha256(claim text)}` goes into `omission_audit` (`:3738–3751`).
   - Explicit gaps come from `intelligence.evidence_gaps[dim]`, canonicalized and deduped (`:3755–3770`). An empty dimension with no gaps gets a default gap: "No source-grounded evidence was extracted for <dim>." (`:3771–3783`).
   - The actor's `intelligence` is rebuilt as `{schema_version, dimensions, evidence_gaps, omission_audit, coverage{covered_dimensions, grounded_dimensions, *_ratio (4dp), explicit_gap_count}}` (`:3796–3808`).
8. Aggregate fingerprints:
   - ordered actor-ID SHA (`:3810–3812`)
   - multiset actor-ID SHA (`:3813–3821`)
   - claim-projection multiset SHA (`:3822–3831`)
   - relationships SHA (`:3832–3837`)
   - coverage totals (`:3838–3847`)
   - fetched-source provenance rows `{source_id, content_sha256, receipt_id, provider, cache_hits, receipt_scopes}` hashed into `source_provenance` (`:3848–3883`)
9. Contract dict:
   - `generated_at` is `generated_at` if one is passed, otherwise `obj["as_of_date"]`. It is deterministic and never wall-clock (`:3886–3889`).
   - Also: `report_sha256`, `dossier_sha256`, `sources_sha256`, `actor_ids_sha256` (equal to the multiset SHA, a "compatibility name", `:3895–3899`), the tier-1/2 roster SHA, counts, the required receipt purpose/lane/thread, claim projection count and multiset, relationship count/SHA/omission count, `dimensions`, `coverage` (`:3884–3921`).
   - It is stored in `obj["actor_intelligence_contract"]` and returned (`:3922–3923`).
- No file I/O.

**`class ActorIntelligenceFinalizationError(RuntimeError)` — `:3926`**
- Raised when a required actor-enabled run cannot seal its contract.

### D. Lineage and finalization

**`_actor_artifact_lineage_id(payload)` — `:3930`**
- `"actor_lineage_" + sha256(payload minus {lineage_id, sealed_at})[:24]`.

**`_write_actor_artifact_lineage(out_dir, *, report, dossier, meta, contract)` — `:3943`**
- Reads the lineage from env: `_current_research_lineage()` (`:916`) returns `RESEARCH_BUDGET_RUN_ID`/`RESEARCH_BUDGET_EPOCH`/`RESEARCH_BUDGET_LANE_ID`.
- Reads `research_checkpoint.json` (`load_research_checkpoint`, `:997`) (`:3952–3957`).
- Writes `actor_intelligence_lineage.json` (`ACTOR_INTELLIGENCE_LINEAGE_FILENAME`, `:869`) atomically (`_atomic_write_text`, `:76`) (`:3995–3998`).
- Payload: `schema_version="actor-artifact-lineage/v1"`, `question_hash` (`_question_hash`, `:901`: first 16 hex chars of sha256 of the whitespace-collapsed, lower-cased question), depth, run/attempt/lane IDs, `meta.thread_id`, checkpoint_id, sha256 of the **in-memory** report and dossier strings, sha256 of the **on-disk** `sources.json` and `actors.json` bytes, the three contract SHAs, `sealed_at` (wall clock), and `lineage_id` (`:3960–3994`).

**`validate_actor_artifact_lineage(out_dir, *, question, depth)` — `:4002`**
- Fail-closed checks, each raising `ActorIntelligenceFinalizationError`, in this order:
  1. The file is unreadable (`:4010–4015`) or not an object (`:4016–4019`).
  2. Schema mismatch (`:4020–4023`).
  3. The recomputed lineage_id differs (`:4024–4027`).
  4. Question hash (`:4028–4031`).
  5. Depth (`:4032–4035`).
  6. run/attempt/lane, **checked only where the current env value is non-empty** (`:4036–4041`).
  7. The on-disk sha256 of `research_report.md`, `actor_dossier.md`, `sources.json` and `actors.json` must equal the recorded values (`:4042–4058`).
  8. If the lineage recorded a checkpoint: it must exist, its `checkpoint_id` must match, `_checkpoint_identity(checkpoint)` (`:931`) must match, and the thread must match when recorded (`:4059–4080`).
- Returns the payload.

**`_claim_is_behavior_ready(claim)` — `:4084`**
- True only for a dict that has support, an evidence_type and confidence other than `""`/`unknown`, and non-empty `claim_valid_at`, `horizon` and `status` (`:4086–4098`).

**`_normalized_actor_behavior_family_failures(obj)` — `:4101`**
- For each Tier 1/2 actor, checks each of the 5 `ACTOR_BEHAVIOR_READY_FAMILIES` (`:2605`): identity_history; incentives_motivations_values; capabilities_constraints; actions_plans_investments; decision_likely_actions_red_lines.
- A family passes when any of its dimensions holds a behavior-ready claim. Each failure is reported as `actor_<i>:<norm name>:behavior_family:<family>` (`:4115–4127`).

**`persist_final_actor_intelligence_contract(out_dir, *, report, dossier, meta, plog, required=True, require_current_extraction=False, expected_unsealed_actors_sha256="")` — `:4131`**
- This is the single sealing boundary, run after triangulation and charts (docstring `:4142–4157`).
- `_fail(msg)` writes `error` (when required) or `warn` and raises `ActorIntelligenceFinalizationError` only if `required`. Otherwise the caller returns `None` (`:4158–4161`).
- Steps:
  1. `actors.json` must exist (`:4164–4166`), parse as UTF-8 JSON (`:4167–4175`) and be an object (`:4176–4178`). `actors` must be a non-empty list of dicts with no non-dict rows (`:4179–4197`).
  2. If `require_current_extraction`: the sha256 of the unsealed bytes must equal `expected_unsealed_actors_sha256`, which must be non-empty (`:4198–4212`). This blocks a stale actors.json.
  3. Load `sources.json` if present. A list of dicts is fine. Unreadable → fail (`:4214–4226`).
  4. Normalize the roster. A `TypeError`/`ValueError` or no Tier 1/2 actors → fail (`:4228–4241`).
  5. Read `actor_dossier_coverage.json`, if readable, for the pinned `required_receipt_thread_id` and `search_result_receipts`. A corrupt file is silently ignored (`:4243–4264`).
  6. `actor_dossier_coverage_audit(dossier, sources, require_source_binding=True, required_receipt_purpose="track-b", ...)` (`:13456`). It must be `accountable`, else fail with the first 8 errors (`:4266–4281`).
  7. Plan A/Plan B equality, each mismatch failing:
     - the sorted Tier 1/2 roster set (`:4282–4293`)
     - ordered `stable_actor_id` lists (`:4294–4307`)
     - `normalize_actor_intelligence_contract(...)` with track-b and the dossier audit's thread; `TypeError`/`ValueError` → fail (`:4309–4325`)
     - the actor-ID multiset SHA (`:4326–4333`)
     - claim projection count and multiset SHA (`:4334–4344`)
  8. Behavior families must all be grounded (`:4345–4353`).
  9. Write order: `sources.json` (only if non-empty; it now carries the assigned `source_id`s) (`:4357–4361`), then `actors.json` (`:4362–4365`), then the lineage file (`:4366–4372`). `meta["actor_intelligence"]` is filled with the contract fingerprints, `dossier_coverage`, `lineage_id` and `lineage_file` (`:4373–4399`). Then `plog.write("ok", "sealed actor-intelligence/v1 (...)")` (`:4400–4405`).
- Returns the contract.

### E. Progress log and tool-arg summaries

**`_utcnow()` — `:4409`**
- `datetime.now(timezone.utc).isoformat()`.

**`class ProgressLog` — `:4418`**
- `__init__` opens `path` in **append** mode (`:4428`), with a `threading.Lock` for the concurrent fan-out workers (`:4432`).
- `_format_line(kind, message)` renders `"<iso> [kind] message"`. Multi-line text is collapsed with `" | "` (`:4436–4449`).
- `write(kind, message)`, under the lock: if not closed, writes and flushes to the file, swallowing `OSError`/`ValueError` (`:4454–4461`). It **always echoes to stdout** with `print(..., flush=True)`, swallowing `BrokenPipeError`/`ValueError`/`OSError` (`:4466–4469`).
- `close()` is idempotent. Later writes go to stdout only (`:4471–4480`). `closed` is a property (`:4482–4484`).
- The orchestrator dispatches on the `[tool]`, `[result]`, `[stage]`, `[usage]`, `[ok]`, `[done]`, `[error]` and `[init]` substrings in each stdout line (`backend/app/services/pipeline_orchestrator.py:2499–2530`).

**`_truncate(text, limit=280)` — `:4487`**
- Collapses whitespace. Truncates with `…`.

**`_summarize_tool_args(args)` — `:4492`**
- For a dict: the first non-empty of `query, url, queries, path, command` as `key=<≤160 chars>`. Otherwise truncated JSON. Non-dicts are truncated (`:4493–4499`).

### F. Prompt-side runtime knobs and model leasing

**`_market_pricing_prompt_block()` — `:4507`**
- Returns the module global `_MARKET_PRICING_BLOCK` (`:1224`, set by `_set_market_pricing_block` `:1261`) followed by a blank line, or `""`.

**`_agentic_delegation_enabled()` — `:4519`**
- `_AGENTIC_DELEGATION` (module global `:1236`, set from `--subagents` via `_set_agentic_delegation` `:1246`) AND env `RESEARCH_AGENTIC_SEARCH` (default True).

**`_configured_subagent_slots()` — `:4523`**
- Env `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS`, default 5, clamped to [1,8]. Invalid → 5.

**`_stream_model_lease_weight()` — `:4533`**
- Always 1.

**`_model_parallel_slots(weight=1)` — `:4538`**
- Env `RESEARCH_MODEL_CONCURRENCY_GLOBAL` (default 12, minimum 1; invalid → 12) floor-divided by the weight, minimum 1.

**`_model_call_lease(weight=1)` — `:4549`**
- Returns `research_budget.model_call_lease(weight)` (`deerflow_bridge/research_budget.py:902`, a SQLite-backed cross-process lease) when the module imported (`:66–73`), otherwise `nullcontext()`.

**`_invoke_model(model, messages)` — `:4555`**
- `model.invoke(messages)` inside `_model_call_lease(1)`. This is the single bare-model call wrapper.

**`_leased_client_stream(client, message, *, thread_id, recursion_limit)` — `:4561`**
- A pure `yield from client.stream(...)`. It deliberately holds no lease; the harness middleware leases each model node.

**`_bridge_fanout_enabled()` — `:4572`**
- False unless env `RESEARCH_DEEP_FANOUT` is set (bridge default False, `:4581`).
- Also False when agentic delegation is active and `RESEARCH_ALLOW_STACKED_FANOUT` is not set (`:4583–4584`).

**`_agentic_delegation_block(chinese=False)` — `:4588`**
- Returns `""` unless delegation is enabled.
- Otherwise returns an English or Chinese instruction block: use the `task` tool with `scoped-researcher` subagents for breadth only (per-actor, per-KIQ, regional/other-language pivots, disconfirmation hunts), at most `slots` parallel tasks per batch, one question per brief, graded notes plus a list of fetched URLs. It must never delegate synthesis, evidence grading or the source ledger, and must verify subagent output against the cited URLs (`:4592–4616`).

### G. WAVE9-RQ style and citation contract

**`_ban_process_narration()` — `:4632`**
- Env `RESEARCH_BAN_PROCESS_NARRATION`, default True.

**`_inline_citations_enabled()` — `:4637`**
- Env `RESEARCH_INLINE_CITATIONS`, default True.

**`_dedup_shingles_enabled()` — `:4642`**
- Env `RESEARCH_DEDUP_SHINGLES`, default True.

**`_citation_index_cap()` — `:4647`**
- Env `RESEARCH_CITATION_INDEX_MAX`, default 100. Non-positive or invalid → 100.

**`_research_charts_min()` — `:4656`**
- Env `RESEARCH_CHARTS_MIN`, default 3, floored at 0. 0 disables chart gating.

**`_dossier_style_rules_block()` — `:4669`**
- When narration is banned: a "HARD STYLE RULES" block. It bans process references (passes, working notes, tracks, coverage gates, word counts, prompts, tooling), `[citation:...](url)` syntax, and self-referential editing notes (`:4673–4685`). Otherwise `""`.

**Regexes — `:4689–4692`**
- `_CITATION_MARKER_RE = \[\s*S(\d+)\s*\]`
- `_REFERENCES_HEADING_RE` matches an H2/H3 `References|参考来源|参考文献`
- `_REFERENCE_ENTRY_RE` accepts `- [S3] …`, `[S3] …`, `3. …` and `3) …`

**`build_citation_index(fetched, cap=100)` — `:4695`**
- Iterates the fetched rows in order. It skips non-dicts, invalid URLs (`_is_valid_http_url` `:1409`), duplicates by `_norm_url` (`:1326`), `ok is False`, and denied domains (`_source_domain_denied` `:2070`) (`:4704–4710`).
- Emits `{n (1-based), title (or _title_from_url), url, excerpt[:1200]}` and stops at `max(1, cap)` (`:4711–4722`).

**`render_citation_index_block(entries)` — `:4725`**
- `""` if there are no entries. Otherwise the CITATION CONVENTION text (mandatory `[S<n>]` drawn only from the index, no invented numbers, no `[citation:]`, **do not write your own references section**) followed by `=== SOURCE INDEX ===` lines `[S<n>] title — url`.

**`parse_references_section(report)` — `:4742`**
- Returns `{n: text}` for entries after a References heading, stopping at the next H1–H3.

**`strip_dangling_citation_markers(report, valid)` — `:4765`**
- Removes each `[S<n>]` (and its leading spaces or tabs) whose n is not in `valid`. Returns `(text, kept, stripped)`.

**`render_references_section(entries, cited)` — `:4787`**
- `## References` with `- [S<n>] title — url` for each cited n present in the entries, in sorted order. `""` if none.

**`finalize_report_citations(report, plog)` — `:4802`**
- Deterministic and idempotent. No LLM call.
  - Feature off or empty report → returned unchanged (`:4811–4812`).
  - No markers → `stage` log, unchanged (`:4813–4816`).
  - The report has its own References section → strip markers that do not resolve to it; log `ok` or `warn` (`:4817–4823`). [verifier: this branch is taken only when `parse_references_section` returns at least one entry that `_REFERENCE_ENTRY_RE` can parse. A `## References` heading whose entries do not match (for example `- Title — URL`, with no `[S<n>]` or `<n>.`) falls through to the pinned-index branch, which appends a second `## References` section. Verified at runtime (deerflow_research.py:4817–4818, :4692, :4824–4830)]
  - Otherwise, if `_PINNED_CITATION_INDEX` (module global `:1243`, set by `_set_pinned_citation_index` `:1256`, reset per run `:1317`) exists: strip markers outside the index and append a deterministic References section listing only the cited entries (`:4824–4835`).
  - Otherwise strip all markers and log `warn` (`:4836–4839`).

### H. Research-pass prompts

**`build_research_prompt(question, depth, target_language, *, evidence_only=False)` — `:4842`**
- Uses preset `DEPTH_PRESETS[depth]`, defaulting to standard (`:102`, `:4845`). `lang_line` names "evidence notes" or "final report" (`:4846–4849`).
- **The evidence-only branch is checked first** (`:4850–4874`):
  - `/deep-research` evidence-lane analyst.
  - The guidance's "write the report" is replaced by "finish the evidence notes".
  - Asks for dense working notes, exact fetched URLs, and a closing `## Gaps to carry into the next pass` section.
  - No delegation block, no style rules.
- **Deep branch** (`:4875–4905`): pass 0 of a multi-pass run. TOOLING rules: web_search/web_fetch/prediction_market_search only; no ls/glob/bash; read_file only for harness paths. Then the market block, the delegation block, the preset guidance, a request for working notes plus a Gaps ledger, and "Do NOT write the final dossier yet".
- **Standard/quick branch** (`:4906–4957`):
  - Optional CITATIONS line: `[S<n>]` plus a self-numbered `## References` section in the form `<n>. <Title> — <date> — <URL>` (`:4909–4918`).
  - Report items 1–6 (actors with explicit relationships, timeline, contention, facts/quotes, sources).
  - LENGTH "at least 6,000 words … no final word or character maximum" (`:4947`).
  - Stop-and-write instruction (`:4951–4954`), then style rules and lang_line.

**`build_deep_phase_prompt(question, phase, index, total, target_language, prior_gaps=None)` — `:4960`**
- Carried gaps, up to 20, become an "UNRESOLVED GAPS" block (`:4969–4978`).
- A quantitative line is added only when the phase label contains `primary` or `evidence`. Of the five phases (`:579–623`), only `primary-evidence` qualifies (`:4982–4992`).
- The delegation block is suppressed when `RESEARCH_EVIDENCE_ONLY` is true and `RESEARCH_EVIDENCE_LANE_DELEGATION` is false (`:4993–4999`).
- Body: SEARCH DISCIPLINE (no near-duplicate queries, breadth over a "white whale") and SOURCE GROUNDING (only fetched sources, no fabricated or future-dated sources) (`:5013–5036`).
- Required headings: Evidence gathered / Actor-incentive updates / Actor relationships / Quantitative facts (unit, as-of, definition, tier) / Contradictions / Gaps (`:5037–5047`). The Gaps section must hold the complete open set with no "none" placeholder (`:5048–5052`).
- An INTERNAL SCAFFOLDING notice is added when narration is banned (`:5055–5058`).
- Ends with "Do NOT write the final report yet" (`:5059–5061`).
- Requires `phase["label"]` and `phase["focus"]`; a missing key raises `KeyError`.

**`build_coverage_topup_prompt(question, gaps, have, target, target_language)` — `:5065`**
- Up to 12 gaps. The source count is framed as "a warning, NOT a quota". Breadth-first hard rules and the same headings. **It has no production caller** (see Surprises).

**`build_gap_closing_prompt(question, gaps, target_language)` — `:5105`**
- Up to 14 gaps. The placeholder bullet is used when there are none (`:5112`). Depth-first closing of each gap. "Only genuinely still-open gaps" go under Gaps.

### I. Single-call synthesis prompt

**`build_synthesis_prompt(question, target_language, depth="standard")` — `:5138`**
- A tool-free "STOP researching" prompt.
- Word target: deep "at least 15,000 words"; otherwise "at least 6,000 words". Both say "no final word or character maximum" (`:5150–5154`). For deep, an extra content list is added (`:5155–5164`).
- Chart line: with `RESEARCH_CHARTS_MIN>0`, chart-ready data supporting ≥N visual classes and no file rendering; otherwise a softer chart-ready request (`:5169–5184`).
- Body, in order:
  - Items 1–6, where item 2 is a full 17-dimension ACTOR INTELLIGENCE section and item 6 is "A short list of the sources you used" (`:5191–5205`).
  - INSIGHT CONTRACT: thesis, base rates, 3–5 cause→effect chains, contrarian view, stress test (`:5209–5219`).
  - LENGTH and OUTPUT-LENGTH CONTRACT (`:5221–5227`).
  - Style rules, charts line, `_final_dossier_contract_block()` (`:561`), lang_line (`:5229–5232`).

**`_message_text(content)` — `:5236`**
- Flattens a LangChain message `content` given as a string or as a list of parts (dict `text` or `str`). Applies `strip_think` (`:10070`) and strips.

### J. Multipart synthesis budgeting (SCALE-1)

**`_multipart_synthesis_enabled(depth)` — `:5266`**
- If `RESEARCH_MULTIPART_SYNTHESIS` is set (non-blank), it wins for every depth (truthy = 1/true/yes/on). Unset → only `deep`.

**`_synthesis_workers()` — `:5275`**
- `min(RESEARCH_SYNTHESIS_WORKERS (default 4, min 1; invalid→4), _model_parallel_slots(1))`.

**`_synthesis_min_words(depth)` — `:5285`**
- Env `RESEARCH_SYNTHESIS_MIN_WORDS` (≥0). Default 15000 for deep, else 4500.

**`_synthesis_max_words(depth)` — `:5296`**
- Env `RESEARCH_SYNTHESIS_MAX_WORDS` (≥0). Default 22000 for deep, else 7000.

**`_synthesis_summary_word_reserve(depth)` — `:5315`**
- `min(desired, max(0, max - min))`, where desired is 1000 for deep and 700 otherwise. If max ≤ 0 it returns desired. Defaults: deep 1000, standard 700.

**`_synthesis_execution_output_token_limit(depth)` — `:5330`**
- Env `RESEARCH_SYNTHESIS_EXECUTION_MAX_OUTPUT_TOKENS` (minimum 1000). Otherwise `max(8000, round(max_words × 1.6))`. Defaults: deep 35,200, standard 11,200. This was verified by running the extracted pure function.

**`rebalance_synthesis_outline(outline, depth)` — `:5350`**
- Budget:
  - `maximum = max - summary_reserve`, at least `minimum` (`:5361–5366`).
  - `target_total = max(min, round(min × 1.15))`, capped at maximum. If min is 0, it uses the sum of the model targets (`:5367–5372`).
  - Then `≥ len(outline)` (`:5379–5382`).
- Weights: clipped to [0.75, 1.25] × the mean target (`:5383–5385`). Per-section floor `min(300, total // n)` (`:5386`). The remainder is distributed by largest remainder; ties go to the lower index (`:5388–5404`).
- Returns copies with integer `target_words` that sum exactly to `target_total`. Default deep total 17,250; standard 5,175 (verified).

**`allocate_synthesis_section_output_tokens(outline, depth)` — `:5414`**
- `aggregate = max(n × 256, round((max_words - reserve) × 1.15))`. Default deep 24,150 tokens (verified).
- Split by target_words weight, each at least 256. Overshoot is reduced from the largest allocation, and the remainder is distributed by fractional part (`:5434–5453`).

**`_forecast_trajectory_metrics(question)` — `:5456`**
- Keyword families give fixed metric lists: humanoid/robot/机器人; grid-scale/energy/battery storage/储能; data-center/AI compute/accelerator/HBM. Otherwise a generic phrase.

**`enforce_synthesis_outline_contract(outline, question="")` — `:5479`**
- Six deterministic deliverable owners, applied in this order:
  1. actor intelligence (1800)
  2. causal mechanisms (1500)
  3. scenarios with four MECE cases, annual trajectories using the metrics above, and one canonical A/B/C/D partition (1600)
  4. milestones (1500)
  5. resolution-ready binary forecasts, 10–12 (1800)
  6. actual-data visualizations (1700)
- `_find` returns the **first** row whose `title + scope + covers` (casefolded) contains any term (`:5492–5503`).
- `_assign` (`:5505–5530`):
  - no match → append a new section
  - match → append the requirement to its scope (if not already there), add the cover (keeping only the last 12 covers), and raise target_words to at least the floor.
- Returns new row dicts. It can push the outline beyond the 24-row parse cap, by up to 6.

**`build_synthesis_outline_prompt(question, target_language)` — `:5605`**
- Asks for ONLY a JSON object `{"sections":[{title, scope, target_words, covers}]}`:
  - 10–20 sections
  - 800–1,400 words each (≤1,800), "normally total 15,000–22,000"
  - a dedicated ACTOR INTELLIGENCE owner
- Ends with `=== GATHERED RESEARCH ===`. The evidence is attached by the caller.

**`default_synthesis_outline(question, target_language)` — `:5646`**
- 16 fixed sections, Chinese when the language string contains chinese/mandarin/中文/汉语/zh (`:5656–5657`), otherwise English.
- Every scope is `"<scope>. Apply specifically to this brief: <brief[:1200]>"`. target_words is 1150, or 900 for the first and last sections (`:5697–5706`).

**`_parse_json_array(text)` — `:5709`**
- A string-aware bracket matcher for the first balanced top-level `[...]`. Returns a list or `None`.

**`parse_synthesis_outline(text)` — `:5745`**
- Accepts `{"sections"}`/`{"outline"}` via `extract_json_object` (`:9040`) or a bare array (`:5753–5763`).
- Per row: a title (`title|name`) is required; scope defaults to the title; `target_words` is clamped to 700–1800 (missing or invalid → 1100); covers keep at most 12 (`:5765–5782`).
- Caps at 24 rows. **Fewer than 3 valid rows → `[]`** (`:5783–5785`).

### K. Context routing, digest, prose metrics, dedup, stitching

**`_SCOPE_TOKEN_RE`/`_SCOPE_STOPWORDS`/`_scope_terms(scope_text)` — `:5790–5812`**
- Lower-cased ASCII tokens of at least 3 characters and CJK runs of 2–6 characters, with stopwords removed. Deduped in order, at most 60.

**`score_block_for_scope(block, terms)` — `:5815`**
- `Σ over distinct hit terms of (10 + min(count, 8))`. Substring counting.

**`pack_context_for_section(blocks, scope_text, cap, *, max_blocks=None)` — `:5830`**
- With terms: positive-score blocks are ranked (score descending, index ascending). If no block scores, only block 0 is considered (`:5848–5858`).
- Without terms: all blocks in order (`:5859–5860`).
- Greedy fill under `cap` characters, counting `\n\n` seams, up to `max_blocks` (default `SYNTHESIS_SECTION_MAX_BLOCKS`=18 via `:805`) (`:5861–5872`).
- If nothing fits, the first ranked block is truncated to `cap` (`:5873–5874`).
- Output keeps the chosen blocks in **original order**.

**`route_citation_index_for_scope(entries, scope_text, *, max_entries=32, evidence_text="")` — `:5878`**
- No terms → the first `max_entries`.
- Each entry is scored on `title + url + excerpt`, with +1000 if its URL appears in the routed evidence text.
- No hits → the first `min(8, max_entries)`.
- Otherwise the top-k, returned in the original order. The global `n` numbers are preserved.

**`build_notes_digest(ai_parts, per_note_chars=240, total_cap=4000)` — `:5908`**
- One `- <first 240 whitespace-collapsed chars>` bullet per note. Stops before the total exceeds 4000.

**`count_prose_words(text)` — `:5936`**
- Removes code fences (including unterminated ones), lines starting with `|` (tables) and URLs.
- Counts ASCII/digit word tokens (internal `'`, `’`, `-` allowed), plus one per CJK character (`:5930–5943`).

**`paragraph_shingles(text, n=12)` — `:5951`**
- A set of normalized n-grams, where tokens are lowercase alnum runs or single CJK characters. Fewer than n tokens → an empty set.

**`dedup_cross_section_paragraphs(texts, n=12, threshold=0.75)` — `:5960`**
- Processes sections in order. A paragraph whose shingle overlap with **earlier sections** is ≥0.75 is removed.
- Headings (`#`), tables (`|`) and fenced paragraphs are exempt.
- Duplicates within the same section are not compared, because `seen` is updated after each section (`:5989`).
- Returns `(texts, removed)`.

**`stitch_synthesis_sections(outline, texts)` — `:5994`**
- Emits `## <title>\n\n<body>` in outline order and skips empty bodies.
- Drops the body's first line when it is a markdown heading equal to the title (case-insensitive, `*#` and spaces stripped) (`:6003–6006`).

**`select_thinnest_sections(outline, texts, k=2)` — `:6011`**
- The k non-empty indexes with the fewest prose words (ties go to the lower index).

**`_section_lead(text, max_words=200)` — `:6019`**
- The first 200 whitespace tokens.

**`_synthesis_section_contract(section)` — `:6025`**
- Keyword-triggered "SECTION-SPECIFIC ACCEPTANCE CONTRACT" clauses, matched on title + scope + covers:
  - MECHANISMS
  - ACTOR INTELLIGENCE, including a byte-exact copy of each `ACTOR_FAMILY_EVIDENCE_V1` HTML marker plus an `[S<n>]` cite (`:6043–6059`)
  - SCENARIOS
  - MILESTONES
  - BINARY FORECASTS
  - ACTUAL-DATA VISUALS
- Returns `""` if none match. It is consumed by `build_synthesis_section_prompt` (`:6149`), which is outside the slice.

## Control flow

**Full research run, actors enabled** (`main` `:16570`)
1. `ProgressLog(out_dir/research_progress.log)` (`:16622`).
2. Research stage `run_research_stage` (`:12331`):
   - standard/quick: one turn with `build_research_prompt(..., evidence_only=RESEARCH_EVIDENCE_ONLY)` (`:12356`).
   - deep: an opening turn with `build_research_prompt` (`:12480`), then phases with `build_deep_phase_prompt` (`:12645`, `:12722`, `:12781`, `:12896`, `:12956`) and gap closing with `build_gap_closing_prompt` (`:12410`, `:13034`).
   - The streams go through `run_streamed_turn` (`:10190`) → `_leased_client_stream` (`:10220`). Tool events are logged with `_summarize_tool_args` and `_truncate` (`:10238`, `:10274`).
   - Fan-out is selected by `_bridge_fanout_enabled`/`_agentic_delegation_enabled` (`:12574`, `:12580`), with width bounded by `_model_parallel_slots(_stream_model_lease_weight())` (`:10528`, `:12750`).
3. Synthesis: `synthesize_from_evidence_parts` (`:7998`).
   - If actor blocks are present and multipart is off, it raises (`:8021`).
   - If `_multipart_synthesis_enabled`, it calls `synthesize_multipart` (`:8053`, `:6640`), which runs: [verifier: the definition is at `:6641` (deerflow_research.py:6641)]
     1. `build_synthesis_outline_prompt` (`:6690`) → `parse_synthesis_outline` (`:6703`), falling back to `default_synthesis_outline` (`:6705`)
     2. `enforce_synthesis_outline_contract` (`:6716`) → `rebalance_synthesis_outline` (`:6731`)
     3. `build_notes_digest` (`:6742`), then `build_citation_index` + `_set_pinned_citation_index` (`:6748–6750`)
     4. `_synthesis_workers` (`:6764`), `allocate_synthesis_section_output_tokens` (`:6766`)
     5. Per section: `pack_context_for_section` (`:6819`, `:6828`), `route_citation_index_for_scope` + `render_citation_index_block` (`:6834–6835`), `build_synthesis_section_prompt` (→ `_synthesis_section_contract`, `:6149`)
     6. `stitch_synthesis_sections` (`:6927`) → length gate `count_prose_words`/`select_thinnest_sections` (`:6930–6933`)
     7. `dedup_cross_section_paragraphs` (`:6998`)
     8. `_section_lead` for the summary (`:7010`)
     9. Max-words gate: `OversizedSynthesisOutput` (`:7037–7045`)
   - Otherwise, single-call: `build_citation_index` + pin + `render_citation_index_block` + `build_synthesis_prompt` (`:8100–8106`), then `_message_text` (`:8129`). [verifier: deep and non-deep differ when multipart is enabled. If multipart returns empty or crashes with a non-provider error, `depth=="deep"` logs `error`, flags degradation and returns `""`; it never falls back to single-call. Only non-deep depths fall through to the single-call path. `OversizedSynthesisOutput`, `SynthesisExecutionBudgetExceeded`, `ActorCoverageBoundaryError` and provider-outage errors propagate (deerflow_research.py:8053–8091). The pinned index is sent in the evidence payload under `GLOBAL SOURCE INDEX`, not in the governing prompt (deerflow_research.py:8107–8111)]
4. Report finalize: `finalize_report_citations` (`:17445`, non-fatal on exception). Judge passes use `_finalize_and_judge_report` → `finalize_report_citations` (`:11739`).
5. The dossier is written and `actor_dossier_coverage.json` is produced (`:17548–17558`). Extraction writes `actors.json` and records `actor_extraction_sha256` (`:17578–17680`).
6. Triangulation and charts may rewrite the report.
7. Final boundary: `persist_final_actor_intelligence_contract(..., required=True, require_current_extraction=True)` (`:17936–17946`) → `normalize_actor_intelligence_contract` → `_canonicalize_relationships` / `_normalize_intelligence_claim` / `_normalize_source_support` → `_normalized_actor_behavior_family_failures` → writes → `_write_actor_artifact_lineage`.

**Extract-only salvage** (`run_extract_only` `:16063`)
1. If a dossier exists or a lineage is recorded, it runs `validate_actor_artifact_lineage` (`:16108–16124`). Failure gives meta status `failed` and exit code 2.
2. After re-extraction:
   - dossier present → `persist_final_actor_intelligence_contract` (`:16328`) and `actor_contract_mode="sealed"`
   - no dossier → `"report-only"` with a warning (`:16312–16323`)

**Shared claim normalization**
- `actor_dossier_coverage_audit` (Plan A) calls `_normalize_intelligence_claim` and `_claim_is_behavior_ready` itself (`:13631`, `:13665`). The Plan A and Plan B projections therefore come from the same code.

## Data & artifacts

| Artifact | Path pattern | Written/read here | Key fields |
|---|---|---|---|
| `actors.json` | `<out_dir>/actors.json` (`:868`) | Read and rewritten in `persist_final_actor_intelligence_contract` (`:4168`, `:4362–4365`) | `actors[]` (Tier 1/2 only, with `actor_id`, `simulation_tier`, `intelligence{schema_version, dimensions{17}, evidence_gaps, omission_audit, coverage}`), `context_entities[]` (Tier 3/4), `relationships[]` (canonical), `relationship_omission_audit[]`, `actor_intelligence_contract{…}` |
| `sources.json` | `<out_dir>/sources.json` (`:870`) | Read (`:4216–4220`); rewritten with the in-place `source_id`s (`:4357–4361`) | Rows with `url, source_id, source_origin, reachable/ok, content/excerpt, content_sha256, receipt_id, receipt_scopes[{thread_id, lane, purpose, receipt_id, content_sha256}], provider, cache_hits` |
| `actor_intelligence_lineage.json` | `<out_dir>/actor_intelligence_lineage.json` (`:869`) | Written (`:3995`); validated (`:4009–4081`) | `schema_version`, `question_hash`, `depth`, `run_id`, `attempt_id`, `lane_id`, `thread_id`, `checkpoint_id`, `report_sha256`, `dossier_sha256`, `sources_file_sha256`, `actors_file_sha256`, three contract SHAs, `sealed_at`, `lineage_id` |
| `actor_dossier_coverage.json` | `<out_dir>/actor_dossier_coverage.json` | Read only (`:4245–4264`) | `required_receipt_thread_id`, `search_result_receipts[]` |
| `research_checkpoint.json` | `<out_dir>/research_checkpoint.json` (`:896`) | Read (`:3953`, `:4059`) | `checkpoint_id`, `thread_id`, … |
| `research_report.md`, `actor_dossier.md` | `:861`, `:867` | File bytes are hashed during validation (`:4042–4058`) | — |
| `research_progress.log` | `<out_dir>/research_progress.log` (`:874`) | Appended by `ProgressLog` (`:4428`) | Lines of the form `<iso> [kind] message` |
| `meta.json` (in-memory `meta`) | — | `meta["actor_intelligence"]` filled (`:4373–4399`) | Contract fingerprints, `dossier_coverage`, `lineage_id`, `lineage_file` |

In-memory structures:
- **`_SourceLookup`** (`:2664`): a dict of normalized ref keys (source_id casefold, URL forms, the unique casefolded title, and `s<index>`/`[s<index>]` for the 1-based position in the **full** sources list, `:2806`, `:2837–2838`). It also carries `.records` and the required receipt purpose/lane/thread.
- **Claim dict**: as listed above (`:3246–3270`).
- **Citation index entries**: `{n, title, url, excerpt}` (`:4713–4719`).
- **Outline rows**: `{title, scope, target_words, covers}`.

Module globals read here: `_MARKET_PRICING_BLOCK` (`:1224`), `_AGENTIC_DELEGATION` (`:1236`), `_PINNED_CITATION_INDEX` (`:1243`).

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_BUDGET_RUN_ID` / `RESEARCH_BUDGET_EPOCH` / `RESEARCH_BUDGET_LANE_ID` | "" | Lineage identity, written and then validated (only when non-empty at validation time) | `:916–928`, `:3952`, `:4036–4041` |
| `RESEARCH_AGENTIC_SEARCH` | true | Second gate on the delegation instruction block | `:4520` |
| `DEER_FLOW_MAX_CONCURRENT_SUBAGENTS` | 5, clamped [1,8] | Slot count quoted in the delegation block; forwarded by the orchestrator (`pipeline_orchestrator.py:2366–2368`) | `:4523–4530` |
| `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | 12 | Local executor bound (÷ weight); also caps synthesis workers | `:4538–4546`, `:5282` |
| `RESEARCH_DEEP_FANOUT` | false in the bridge; the orchestrator forwards Config default true (`backend/app/config.py:1172`, `pipeline_orchestrator.py:2348`) | Enables the legacy bridge KIQ fan-out | `:4581` |
| `RESEARCH_ALLOW_STACKED_FANOUT` | false | Allows the bridge fan-out together with harness delegation | `:4583` |
| `RESEARCH_BAN_PROCESS_NARRATION` | true | Style rules and the INTERNAL notice in prompts | `:4634`, `:5055–5058` |
| `RESEARCH_INLINE_CITATIONS` | true | `[S<n>]` convention, pinned index, finalizer | `:4639`, `:4811`, `:4910` |
| `RESEARCH_DEDUP_SHINGLES` | true | Cross-section dedup in multipart | `:4644` |
| `RESEARCH_CITATION_INDEX_MAX` | 100 | Citation index cap | `:4650` |
| `RESEARCH_CHARTS_MIN` | 3 | Chart line in the synthesis prompt (0 = softer text) | `:4663`, `:5169–5184` |
| `RESEARCH_EVIDENCE_ONLY` | false (main overwrites it from `--evidence-only`, `:16602`) | Suppresses phase delegation; evidence-only research prompt | `:4994`, `:12349` |
| `RESEARCH_EVIDENCE_LANE_DELEGATION` | false | Re-enables delegation inside evidence lanes | `:4995` |
| `RESEARCH_MULTIPART_SYNTHESIS` | unset → deep only | Multipart synthesis on/off for every depth | `:5269–5272` |
| `RESEARCH_SYNTHESIS_WORKERS` | 4 | Section-writer concurrency (min with model slots) | `:5278–5282` |
| `RESEARCH_SYNTHESIS_MIN_WORDS` | 15000 deep / 4500 | Length-gate floor; rebalance target | `:5287–5293` |
| `RESEARCH_SYNTHESIS_MAX_WORDS` | 22000 deep / 7000 | Budget ceiling; a hard fail in the driver | `:5306–5312`, `:7037–7045` |
| `RESEARCH_SYNTHESIS_EXECUTION_MAX_OUTPUT_TOKENS` | max(8000, 1.6 × max_words) | Shared multipart output-token ledger (min 1000) | `:5337–5347` |
| `SYNTHESIS_SECTION_MAX_BLOCKS` | 18 | Max evidence blocks per section | `:805–810`, `:5861–5862` |
| CLI `--subagents` | off | Sets `_AGENTIC_DELEGATION` | `:1236–1248` |
| CLI `--no-actors` | off | Skips sealing entirely (callers) | `:16580`, `:17936` |

## External calls

- **LLM, bare model:** `_invoke_model` → `model.invoke(messages)` under `research_budget.model_call_lease(1)` (`:4555–4558`). The lease is a SQLite cross-process ledger (`deerflow_bridge/research_budget.py:902–931`). Callers are outside the slice (`:6524`, `:6548`, `:14105`, `:14292`, `:14313`).
- **LLM, DeerFlow agent stream:** `_leased_client_stream` → `client.stream(message, thread_id=…, recursion_limit=…)` (`:4568–4569`).
- **stdout:** `ProgressLog.write` prints every line (`:4467`). This is the subprocess protocol consumed at `backend/app/services/pipeline_orchestrator.py:2493–2530`.
- **Filesystem:** see Data & artifacts. All writes use `_atomic_write_text` (temp file + fsync + `os.replace`, `:76–96`), except the append-mode progress log.
- No HTTP, DB or subprocess calls in this slice. Prompt builders produce strings only.

## Cross-module edges

**Inbound, to this slice**
- `deerflow_research.main` (`:16570`): `ProgressLog` (`:16622`), `finalize_report_citations` (`:17445`), `persist_final_actor_intelligence_contract` (`:17937`).
- `run_extract_only` (`:16063`): `validate_actor_artifact_lineage` (`:16110`), `persist_final_actor_intelligence_contract` (`:16328`).
- `_finalize_and_judge_report` (`:11730`): `finalize_report_citations` (`:11739`).
- `run_research_stage` (`:12331`): research and phase prompt builders. `run_streamed_turn` (`:10190`): `_leased_client_stream`, `_summarize_tool_args`, `_truncate`.
- `synthesize_multipart` (`:6640`) [verifier: :6641] and `synthesize_from_evidence_parts` (`:7998`): all multipart helpers, `build_synthesis_prompt`, `_message_text`, `_multipart_synthesis_enabled`.
- `actor_dossier_coverage_audit` (`:13456`): `_normalize_intelligence_claim` (`:13631`), `_claim_is_behavior_ready` (`:13665`, `:13672`).
- `build_synthesis_section_prompt` (`:6096`, outside the slice): `_synthesis_section_contract` (`:6149`). Other prompt builders (`:6148`, `:6174`, `:6200`): `_dossier_style_rules_block`.
- The Chinese actor-track prompt (`:11548`) and other prompt builders (`:13201`, `:13319`): `_agentic_delegation_block`.
- `deerflow_bridge/linear_research.py` (v3 engine): `bridge_call("count_prose_words")` (`:5553`), `bridge_call("dedup_cross_section_paragraphs")` (`:5122`), `getattr(bridge, "_model_call_lease")` (`:6195`), and a ProgressLog facade (`:811`).
- Tests:
  - `backend/tests/test_actor_intelligence_producer.py`: normalize, persist, lineage, behavior families, `_normalize_intelligence_claim`.
  - `backend/tests/test_pipeline_actor_contract.py:210`.
  - `test_multipart_synthesis.py`, `test_wave9_research_quality.py`, `test_loop010_research_contracts.py`, `test_loop010_global_synthesis.py`.
  - `backend/scripts/test_deerflow_deep_research.py:105`, `:116`.

**Outbound, from this slice**
- `_as_items` `:2639`
- `normalize_source_refs` `:2854`
- `_source_receipt_scope` `:2723`
- `_canonical_source_lookup` `:2780`
- `_supporting_span` `:2899`
- `_normalized_support_text` `:2883`
- `_source_support_text` `:2891`
- `_cast_norm` `:2425`
- `_normalize_actor_simulation_roster` `:2431`
- `stable_actor_id` `:1364`
- `_actor_explicit_tier` `:2327`
- `_source_is_fetched` `:2647`
- `_receipt_scopes` `:2683`
- `_search_query_from_args` `:1621`
- `_current_research_lineage` `:916`
- `load_research_checkpoint` `:997`
- `_checkpoint_identity` `:931`
- `_question_hash` `:901`
- `_atomic_write_text` `:76`
- `actor_dossier_coverage_audit` `:13456`
- `_env_flag` `:2229`
- `research_budget.model_call_lease`
- `_norm_url` `:1326`
- `_is_valid_http_url` `:1409`
- `_source_domain_denied` `:2070`
- `_title_from_url` `:1389`
- `DEPTH_PRESETS` `:102`
- `_final_dossier_contract_block` `:561`
- `strip_think` `:10070`
- `extract_json_object` `:9040`
- `_synthesis_section_max_blocks` `:805`

## Invariants, gates, validation

- **Quote-bound grounding:** every claim kept in an actor dimension or relationship has at least one support row. Each row has a `receipt_id`, a 64-hex `content_sha256`, and a quote found in the fetched source's `content`/`excerpt` (`:3002–3019`, `:3738–3751`, `:3514–3520`). With purpose `track-b`, the receipt scope must have an `actor-`/`actor_` purpose, lane `track-b`, and the resolved thread (`:2713–2720`, `:2790–2808`, `:2984–2985`).
- **No temporal laundering:** `claim_valid_at` comes only from claim fields (`:3161–3174`), and `default_as_of` is discarded (`:3245`).
- **Content-addressed identities:**
  - `claim_id`/`claim_sha256` come from the projection (`:3117–3136`).
  - `relationship_id` binds the endpoints, type, label, claim hash and causal attributes (`:3521–3537`).
  - `actor_id` is `stable_actor_id(canonical name)`; model IDs are ignored (`:3671–3681`).
  - `lineage_id` is a hash of the payload without `sealed_at` (`:3930–3940`).
- **Fail-closed uniqueness:** homonyms and alias overlap raise ValueError (`:2465–2479`). An actor_id collision raises (`:3676–3679`). A duplicate relationship_id raises (`:3538–3543`).
- **Explicit gaps:** every dimension with no claims has at least one gap (`:3771–3783`).
- **Plan A ≡ Plan B:** sorted roster, ordered IDs, ID multiset, and claim-projection count and multiset must all be equal (`:4282–4344`).
- **Behavior-ready floor:** every Tier 1/2 actor needs one behavior-ready claim in each of the 5 families (`:4101–4128`, `:4345–4353`). A claim is behavior-ready only with non-unknown evidence_type and confidence and non-empty claim_valid_at, horizon and status (`:4084–4098`).
- **Write ordering:** sources → actors → lineage → meta (`:4357–4399`), so that `sources_sha256` describes the persisted ledger.
- **Lineage gate:** the four artifact file hashes, the question hash, depth, run/attempt/lane (when set) and checkpoint identity are all checked (`:4002–4081`).
- **Citation gate:** only resolvable `[S<n>]` markers survive. A References section is appended only from the pinned index (`:4802–4839`).
- **Outline gate:** fewer than 3 parsed sections → the default skeleton (`:5785`, `:6703–6705`). Rebalanced totals stay within [floor, ceiling − summary reserve] (`:5361–5382`).

## Failure modes & recovery

- **Finalization failure:** `persist_final_actor_intelligence_contract` with `required=True` raises `ActorIntelligenceFinalizationError` at the first failing gate, after logging `[error]` (`:4158–4161`). `main` lets it escape to the outer `except Exception` (`:17960`). `run_extract_only` catches it and sets meta status `failed` with return code 2 (`:16339–16352`). With `required=False`, it logs `warn` and returns `None` without writing anything.
- **Normalization errors:** `TypeError`/`ValueError` from normalization (homonyms, alias overlap, ID collision, duplicate relationship_id) are converted to `_fail` inside persist (`:4320–4325`). Direct callers of `normalize_actor_intelligence_contract` receive the raw exception.
- **Corrupt `actor_dossier_coverage.json`:** silently ignored (`:4250–4252`). The thread is then inferred from the ledger only when exactly one Track-B thread exists; otherwise all Track-B sources are rejected (`:2794–2808`), which makes the dossier audit fail.
- **Progress-log I/O:** errors are swallowed. The stdout echo stays authoritative (`:4458–4469`).
- **Citation finalizer exceptions:** callers treat them as non-fatal in `main` (`:17446–17447`). In the judge path they refuse to judge (`:11740–11745`).
- **Outline JSON:** malformed JSON → `parse_synthesis_outline` returns `[]` → the deterministic skeleton, and a degradation flag is set by the driver (`:6703–6714`).
- **Pack fallback:** `pack_context_for_section` never returns empty for non-empty blocks and a positive cap. It truncates the first ranked block (`:5873–5874`).

## Surprises

1. **Suspected bug: the default skeleton leaks deliverable clauses into every section.** `default_synthesis_outline` appends the user brief to every scope (`:5701`). `enforce_synthesis_outline_contract._find` (`:5499–5503`) and `_synthesis_section_contract` (`:6027–6035`) both match keywords against the scope.
   - Verified by running the AST-extracted pure functions on the brief "Forecast humanoid robot adoption to 2035 with scenarios, milestones and charts."
   - All 16 sections received the SCENARIOS, MILESTONES and ACTUAL-DATA VISUALS acceptance clauses.
   - The scenario and milestone requirements attached to section 0, "Executive Thesis", raising it to 1700 words, instead of the dedicated sections.
2. **Suspected bug: first-match routing misplaces requirements even with a neutral brief.** Verified with "Forecast humanoid robot adoption to 2035.":
   - The milestone requirement lands on "Technology Routes and Performance Frontier", whose scope contains "inflection points". The dedicated Milestones row is never reached.
   - The visualization requirement lands on "Scenarios…", because the scenario requirement appended earlier contains the word "visualization" (`:5563–5565` vs `:5590`).
   - In the Chinese skeleton, the scenario requirement lands on 执行摘要 (scope "基准情景") and the milestone requirement on 技术路线 (scope "技术拐点").
3. **Suspected Plan A/Plan B mismatch from relationship-derived claims.** `normalize_actor_intelligence_contract` adds claims synthesized from allied or opposed canonical relationships into the `alliances`/`opponents_competitors` dimensions (`:3719–3721`, `:3338–3376`). They carry defaulted `horizon="current"` and `status="active"` (`:3368–3369`) and count toward `claim_projection_multiset_sha256` (`:3753`). `persist_final_actor_intelligence_contract` requires that multiset to equal the dossier audit's (`:4334–4344`), and the audit only counts the dossier ledger's claims (`:13631–13656`).
   - An admitted `ALLY_OF`/`OPPOSES`/… edge would therefore likely fail sealing, unless the dossier happens to contain byte-identical claims.
   - The persist-level test uses `REGULATES` (`backend/tests/test_pipeline_actor_contract.py:167`), which is not in either set. The allied/opposed paths are tested only through `normalize_*` (`backend/tests/test_actor_intelligence_producer.py:1325–1373`). [verifier: the `"type": "REGULATES"` line is `backend/tests/test_pipeline_actor_contract.py:168`]
   - Not verified at runtime. [verifier: now verified at runtime, and the suspected bug is CONFIRMED. The module was loaded from source in an isolated scratch directory and the test's producer bundle was rebuilt. `persist_final_actor_intelligence_contract(required=True)` seals with a quote-bound `REGULATES` edge (34 projections, lineage validates). With the same edge typed `ALLY_OF` or `OPPOSES`, it raises `ActorIntelligenceFinalizationError: claim projection mismatch between dossier Plan A and actors.json Plan B` (deerflow_research.py:3719–3721, :3753, :4334–4344, :13626–13654)]
4. **Normalized span offsets are in normalized coordinates.** For `normalized_excerpt`, `_supporting_span` returns offsets into the NFKC, casefolded, whitespace-collapsed text, not the original (`:2909–2917`). Verified: `"Hello   World  Foo"` / `"hello world"` gives (0,11), while the original span is (0,13). A supplied span is not checked for this basis (`:3027–3032`).
5. **Two incompatible `S<n>` numbering schemes.** In `_canonical_source_lookup`, `s<index>` is the 1-based position in the **entire** sources list, fetched or not (`:2806`, `:2837–2838`). The synthesis `[S<n>]` index numbers fetched rows after dedup, deny-list filtering and the cap (`:4704–4720`). A claim citing the synthesis `[S7]` resolves to row 7 of sources.json. The quote check then usually drops it, so the failure is fail-safe but silent.
6. **Citation index vs `sources.json` alignment claim is approximate.** `build_citation_index` claims the same predicate and order as `merge_fetched_into_sources` (`:4697–4700`), but:
   - it dedups by `_norm_url` while merge uses `_source_identity_url`, which lowercases the host and drops fragments (`:2180`);
   - it does not drop S4-tier rows, which merge does (`:2175–2176`, `:2206–2209`);
   - merge first pulls in `_merge_shared_fetched_sources()` (`:2139`).
7. **Single-call synthesis gives contradictory instructions.** Item 6 asks for "A short list of the sources you used (titles + URLs)" (`:5205`), while the pinned SOURCE INDEX says "do NOT write your own references/sources section" (`:4734–4736`). If the model writes `## References` with its own numbering, `finalize_report_citations` trusts that section over the pinned index (`:4817–4823`). Markers can then validate against different sources, silently.
8. **Marker and heading regex gaps.**
   - Grouped markers (`[S1, S3]`, `[S1–S3]`) never match `_CITATION_MARKER_RE` (`:4689`), so they are neither validated nor stripped.
   - `# References` (H1) or `## Sources` are not recognized (`:4690`), so the pinned path appends a second references list.
9. **The evidence-only flag overrides the deep opening prompt** (`:4850` is checked before `:4875`). The deep guidance does not contain "write the report", so the `.replace` at `:4851–4852` is a no-op and the evidence-notes prompt still says "only then synthesize a long evidence-backed dossier" (`:131`). The evidence-only branch also omits the deep branch's TOOLING restrictions and delegation block.
10. **Dead code:** `build_coverage_topup_prompt` (`:5065`) has no production caller. It is referenced only in a docstring (`:5108`) and in `backend/tests/test_loop010_research_contracts.py:45`, `:107`.
11. **Docstring vs behavior on the word ceiling.** `_synthesis_max_words` is described as a "soft useful-length ceiling … not a destructive truncation rule" (`:5297–5305`), but `synthesize_multipart` raises `OversizedSynthesisOutput` when the stitched report exceeds it (`:7037–7045`). `.env.example:543` correctly calls it a hard limit.
12. **Inconsistent length targets.**
    - The standard research prompt and single-call synthesis ask for "at least 6,000 words … no final word or character maximum" (`:4947`, `:5153`).
    - The standard multipart floor is 4,500 and the ceiling 7,000 (`:5293`, `:5312`).
    - `build_synthesis_outline_prompt` hard-codes deep totals of "15,000–22,000" even when multipart is enabled for standard via env (`:5626–5627`).
13. **Redundant fields.** Because claims without support are dropped before counting, `covered_dimensions == grounded_dimensions` always, and the two ratios are always equal (`:3785–3788`). Because the roster keeps only Tier 1/2, `tier_1_2_actor_count == actor_count` always (`:3684–3686`, `:2481–2483`).
14. **Misleading omission reason.** A relationship with an empty basis is omitted as `no_quote_bound_fetched_source_support` (`:3514–3519`), because `_normalize_intelligence_claim` returns `None` for empty text. [verifier: this holds only when none of `_claim_text`'s fallback fields is present. An empty-basis edge that carries `status`, `horizon`, `trigger`, `dependencies`, `driver`, `gains_if` or `loses_if`, plus quote-bound support, is ADMITTED with a synthetic basis such as `"status=active; horizon=current"`. That text then becomes the relationship `basis` and the derived alliance claim text. Verified at runtime (deerflow_research.py:3064–3072, :3493, :3553)] Also, `_canonical_actor_evidence_gap` keeps a dict gap whose reason is empty (`:3582–3614`); only string gaps are dropped when blank.
15. **Hash basis differs between writer and validator.** The lineage hashes the **in-memory** report and dossier strings (`:3969–3974`), but validation hashes the **on-disk** bytes (`:4042–4058`). They agree only when callers pass exactly the persisted text. `main` re-reads the report from disk at `:17933–17935`.
16. **Lax validation without env.** `validate_actor_artifact_lineage` skips the run/attempt/lane checks when the current env values are empty (`:4037–4041`), so a salvage run without the orchestrator env does not bind to the original attempt.
17. **Asymmetric dossier handling.** The full-run path seals unconditionally when actors are enabled (`:17936–17946`). A dossier-less run therefore fails closed: the audit reports `ledger_count:0`, so `accountable` is false (`:13535`, `:13827`). Extract-only instead downgrades to a `"report-only"` contract (`:16312–16323`). The module docstring states "required unless --no-actors" (`:11`), so this is by design, but it is easy to miss.
18. **Dedup can delete a whole section.** `dedup_cross_section_paragraphs` can empty a section entirely, and `stitch_synthesis_sections` then silently drops its heading (`:5999–6002`). Verified with a synthetic input.
19. **Lease naming and doc drift.** `_leased_client_stream` holds no lease despite its name (`:4561–4569`). The `research_budget.model_call_lease` docstring says a harness lead stream uses weight `1 + max_concurrent_subagents` (`deerflow_bridge/research_budget.py:905–907`), but `_stream_model_lease_weight()` returns 1 (`:4533–4535`). The research_budget doc is stale.
20. **Default mismatch for `RESEARCH_DEEP_FANOUT`.** The bridge defaults it to False (`:4581`), but the orchestrator always forwards Config's default True (`backend/app/config.py:1172`, `pipeline_orchestrator.py:2348–2349`). Under delegation it is still suppressed unless stacked fan-out is allowed (`:4583`).
21. **Doc drift: architecture docs.** `DRF_ARCHITECTURE.md:554` anchors `finalize_report_citations` at `:1846` (it is at `:4802`) and states "15–25K merged" words. `ARCHITECTURE_MAP.md:165` also says "15–25K". The multipart deep ceiling is 22,000 prose words and is fatal when exceeded (`:5312`, `:7037–7045`).
22. **Doc drift, uncertain: README citation claim.** `README.md:502` says "`[S#]` markers are renumbered to be positional into `sources.json`". This slice's `finalize_report_citations` never renumbers; it only strips and appends (`:4802–4839`). The README line may describe the v3 linear engine. Not verified. [verifier: resolved. The README line describes the v3 engine, which does positional renumbering in `renumber_citations` (deerflow_bridge/linear_research.py:3274–3289). v3 is the default engine (backend/app/services/pipeline_orchestrator.py:5919–5922), so this is not drift for the default path; it is only untrue of the legacy finalizer]
23. **Duplicated logic.** `_message_text` is duplicated in `deerflow_bridge/research_gateway.py:464`. [verifier: it is not a duplicate. `research_gateway._flatten_content` (deerflow_bridge/research_gateway.py:461) only claims equivalence in its docstring (:464). It differs: it keeps only dict parts whose `type` is `text`, maps `None` to `""`, and applies neither `strip_think` nor `.strip()`. The bridge version keeps every dict part's `text` (deerflow_research.py:5236–5246)] `_normalized_support_text` and `stable_actor_id` both re-import `unicodedata` locally (`:2884`, `:1372`) although it is imported at module top (`:61`).
24. **Unused parameter.** `_normalize_intelligence_claim` keeps an unused `default_as_of` parameter only to `del` it (`:3245`). Callers still pass a value (`:3509`, `:3728`).
25. **No self-loop guard.** `_canonicalize_relationships` admits relationships whose source and target are the same actor (`:3465–3473`).

## Verification

The adversarial verifier ran on 2026-10-11 against branch `main`, using the checkout on disk. It read every load-bearing claim and surprise against `deerflow_bridge/deerflow_research.py`, and spot-checked more than 40 Walkthrough, Control-flow, Failure-mode and Data statements. Runtime checks loaded the module from source with `importlib` (`sys.dont_write_bytecode=True`, `python3 -I`, all temporary files in the session scratchpad). None of them made a network or LLM call.

**Verdict counts (15 key claims + 18 summarized surprises = 33 items):** 28 confirmed (12 claims, 16 surprises), 5 imprecise (claims 1, 10 and 12; the doc-drift and minor-items surprises), 0 refuted, 0 unverifiable. A further 4 spot-checked map statements were imprecise (item 6 below). The other spot-checked statements were confirmed.

**Non-confirmed items, with corrections:**
1. **Claim: `_normalize_source_support` quote check (`:2971–3019`). Imprecise.** The quote is matched against `content` when that is a non-blank string, and against `excerpt` only as a fallback, never against both (`deerflow_research.py:2891–2896`, `:3017`). Rows are also dropped when a supplied span dict has non-integer start/end, when a supplied span does not equal the computed one for an `exact_excerpt` match, and when the row duplicates an earlier `(source_id, normalized quote)` (`:3020–3036`).
2. **Claim: `validate_actor_artifact_lineage` (`:4009–4081`). Imprecise.** Checkpoint identity is checked only when the lineage recorded a non-empty `checkpoint_id` (`:4060–4061`). Each of the four artifact hashes must also be non-empty and the file must exist; otherwise it fails with "missing … artifact" (`:4049–4053`).
3. **Claim: `finalize_report_citations` precedence (`:4811–4839`). Imprecise.** The report's own References section wins only when it yields at least one entry that `_REFERENCE_ENTRY_RE` can parse (`:4692`, `:4817–4818`). A `## References` heading whose entries are unparseable falls through to the pinned branch, which appends a second `## References`. This was verified at runtime.
4. **Surprise: doc drift (DRF_ARCHITECTURE / ARCHITECTURE_MAP / README). Imprecise.** The `DRF_ARCHITECTURE.md:554` (`:1846`, "15–25K") and `ARCHITECTURE_MAP.md:165` drift is confirmed. The README `[S#]` renumbering claim, however, accurately describes the default v3 engine (`deerflow_bridge/linear_research.py:3274–3289`; default at `backend/app/services/pipeline_orchestrator.py:5919–5922`), so it is not drift for the default path.
5. **Surprise: minor items (empty basis, gap, `default_as_of`, `_message_text`, self-loop). Imprecise.**
   - (a) An empty relationship basis is omitted with the misleading reason only when `_claim_text` has no fallback field. With `status`/`horizon` etc. present, the edge is admitted with a synthetic basis such as `"status=active; horizon=current"` (`:3064–3072`, `:3493`). Verified at runtime.
   - (d) `research_gateway.py:464` is a docstring line inside `_flatten_content` (`deerflow_bridge/research_gateway.py:461`). That function is a near-equivalent with different semantics (text-type filter, no `strip_think`/strip), not a duplicate.
   - (b) dict gap with empty reason kept (`:3582–3614`), (c) `default_as_of` deleted (`:3245`) and (e) self-loop admitted are confirmed. A runtime `ALLY_OF Acme→Acme` edge was admitted and produced the alliance claim `"ALLY_OF Acme: …"`.
6. **Walkthrough/Control-flow anchors. Imprecise.**
   - `synthesize_multipart` is at `:6641`, not `:6640`.
   - The single-call path in Control flow step 3 applies only to non-deep depths. Deep multipart failure returns `""` and refuses the fallback (`:8082–8091`).
   - The relationship claim-copy step pops `type`/`basis` only from the top level (`:3496–3505`).
   - The test anchor is `backend/tests/test_pipeline_actor_contract.py:168`, not `:167`.

**Upgraded:** Surprise 3 (relationship-derived alliance/opponent claims break Plan A = Plan B sealing) is now **runtime-confirmed**. The same producer bundle seals with a `REGULATES` edge, and with an `ALLY_OF` or `OPPOSES` edge fails with `claim projection mismatch between dossier Plan A and actors.json Plan B` (`:3719–3721`, `:4334–4344`). Surprises 1, 2, 4 and 18 were re-run and reproduced exactly. One addition to Surprise 1: with a brief that mentions charts, the visualization requirement also lands on section 0 (which is why it reaches 1700). In the Chinese neutral run, the visualization requirement also lands on 执行摘要.

**Omissions (significant behavior the map did not state):**
- **Synthetic relationship basis.** `claim_value["claim"]=basis`, and `_claim_text` falls back to `summary/fact/detail/…/value`, then to `driver/gains_if/loses_if/status/horizon/dependencies/trigger/basis` `key=value` pairs. An edge with an empty basis can therefore be admitted with machine-generated text as its basis (`deerflow_research.py:3056–3072`, `:3492–3493`, `:3553`).
- **Content-precedence grounding.** `_source_support_text` uses `content` exclusively when it is non-blank (`deerflow_research.py:2891–2896`). A correct quote from `excerpt` alone is rejected for any row that also stores `content`.
- **Relationship qualifiers can carry `type`/`basis`.** Only causal keys are stripped from `qualifiers`. `type` and `basis` are whitelisted qualifier keys, so a nested `qualifiers.type`/`qualifiers.basis` enters the relationship claim's qualifiers and its `claim_sha256` (`deerflow_research.py:2621–2622`, `:3500–3505`, `:3202–3208`, `:3112`).
- **Omission-audit key collision.** The per-actor `omission_audit[].claim_sha256` is sha256 of the raw claim text, not the projection `claim_sha256` used everywhere else, so the same key name carries two different hash semantics (`deerflow_research.py:3744–3750` vs `:3133–3135`).
- **Duplicate References on unparseable sections.** A model-written `## References` with entries the regex cannot parse (or a `## Sources` list) makes the pinned branch append a second `## References`. Verified (`deerflow_research.py:4817–4830`).
- **Deep synthesis has no single-call fallback.** When multipart is enabled and returns empty or crashes for `depth=="deep"`, `synthesize_from_evidence_parts` returns `""` with an `error` log. Deterministic envelope errors propagate. Only non-deep depths fall through to the single-call prompt (`deerflow_research.py:8053–8091`).
