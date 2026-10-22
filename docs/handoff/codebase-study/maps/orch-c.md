# orch-c — Orchestrator part C: research handoff loading and actor-intelligence reception

Slice: `backend/app/services/pipeline_orchestrator.py` lines 3857-5820 (branch `main`, checkout on disk, studied 2026-10-11).
All anchors are `path:line` relative to the repo root. "PO" below means `backend/app/services/pipeline_orchestrator.py`.

## Purpose & position in the pipeline

This slice sits at the boundary between Stage 0 (RESEARCH, the DeerFlow bridge subprocess) and Stage 1 (ONTOLOGY/GRAPH). It contains five groups of code:

1. **Handoff loader.** `_load_research_handoff` (PO:3857) rebuilds the `research` dict from an existing `handoff/` directory. Resume/reuse and synthesis-only recovery use it instead of rerunning DeerFlow (callers PO:11962, PO:11052).
2. **Cast reconciliation wrapper.** `_reconcile_research_cast` (PO:3917) runs `utils.actors.reconcile_cast`. For legacy (pre-v1) casts it applies the merge. For a sealed `actor-intelligence/v1` cast it only returns a read-only audit (PO:3933-3942).
3. **Parent-side reception of the actor plane.** PO:3950-5737 is a set of pure helpers that mirror the producer code in `deerflow_bridge/deerflow_research.py`. From the bytes received, they recompute every identity and hash: actor IDs, source IDs, receipt scopes, quote spans, claim projections, relationship IDs, dossier-ledger seals, Track-B provenance seals and the artifact lineage. `_actor_intelligence_reception_errors` (PO:5194) collects the error codes. `_enforce_actor_intelligence_reception` (PO:5668) is the gate: when the run's pinned policy requires the v1 actor plane, any error raises `RuntimeError`. That failure happens before RESEARCH is marked complete, so ONTOLOGY/GRAPH never start (call site PO:12274-12286).
4. **Forecast-input fallback (SIM-ADD-1).** `_forecast_inputs_missing` (PO:5740) and `inject_forecast_inputs_from_report` (PO:5752) parse the report's scenario section into `actors["forecast_inputs"]` with no LLM. They do this only for pre-v1 casts and run twice: at research finalization (PO:12239) and before the PREPARE world-state seed (PO:12885).
5. **PAR-2 angle constants.** `_TRACK2_PREFIX`, `_TRACK3_PREFIX` and `_RESEARCH_TRACK_ANGLES` (PO:5796-5818) define the outer research lanes that `_run_parallel_research_tracks` uses (PO:11077, PO:11178, PO:11245).

Nothing in the slice calls an LLM, the network or a subprocess. The slice reads files from `handoff/` and computes SHA-256 hashes. Its only mutations are to `state.options` (PO:5683, PO:5697, PO:5724) and, in place, to a pre-v1 `actors` dict (PO:5781).

## Walkthrough (source order)

### 1. `_load_research_handoff(handoff_dir)` — PO:3857-3887
- **Input:** a `handoff_dir` path.
- **Reads:**
  - `research_report.md` through `_read_text` (PO:2925). `_read_text` swallows every exception and returns `""`.
  - `actor_dossier.md`, `actors.json`, `sources.json` and `timeline.json` through `_read_json` (PO:2933), which returns `None` when the file is missing or unparsable. [verifier: `actor_dossier.md` is read with `_read_text`, not `_read_json` (PO:3872), so a missing dossier is `""`, not `None`; only `actors.json`, `sources.json` and `timeline.json` go through `_read_json` (PO:3882-3884)]
- **Short-report guard:** if `len(report.strip()) < 400` it raises `RuntimeError("已有研究报告缺失或过短，无法从研究阶段恢复")` (PO:3869-3870). The 400 is hard-coded. It does not read `Config.RESEARCH_MIN_REPORT_CHARS`.
- **Degraded-dossier guard (RES-8 mirror):** if the dossier is non-empty and `_is_degraded_dossier` (PO:2814) flags it, the dossier becomes `""` and a warning is logged (PO:3872-3875). `_is_degraded_dossier` flags text shorter than `Config.RESEARCH_MIN_REPORT_CHARS` (default 400, config.py:511) or text containing any `_LLM_ERROR_MARKERS` string (PO:2748-2754: "The configured LLM provider", "LLM request failed", "unprocessable_entity", "new_sensitive", "Error code: 4", "Error code: 5").
- **Returns** `{report, report_path, actor_dossier, actors, sources, timeline, exit_code: None, resumed: True}` (PO:3876-3887). It does not return `meta` or `research_telemetry`. The synthesis-recovery caller adds `exit_code=0` and `research_telemetry` afterwards (PO:11052-11055).
- **Side effects:** file reads and a log warning only.

### 2. SIM-ADD-1 banner comment — PO:3890-3905
This comment records the motivation: `actors.json` lacked `forecast_inputs`, so `world_state_seed_from_actors` returned `{}` and the decision channel never fired. It describes the two hook points (research finalization and pre-PREPARE). It also says v1 producer-sealed casts must be strictly no-op.

### 3. `_is_sealed_actor_intelligence_v1(actors)` — PO:3906-3914
Returns True only when `actors` is a dict, `actors["actor_intelligence_contract"]` is a dict, and its `schema_version == "actor-intelligence/v1"` (constant PO:107). Several places use this test to choose between "immutable" and "legacy mutable" behavior: PO:3933, PO:5767, PO:7012, PO:7098, PO:7201, PO:12199, PO:12248, PO:12402.

### 4. `_reconcile_research_cast(actors)` — PO:3917-3947
- Lazily imports `reconcile_cast` (backend/app/utils/actors.py:2333) and always runs it (PO:3930). `reconcile_cast` is a union-find duplicate detector. It returns `(actors, {"merged": [], "n_before", "n_after"})` when there are no duplicates (utils/actors.py:2343-2373) and otherwise a new object plus a merge audit (utils/actors.py:2448).
- **Sealed v1** (PO:3933-3942): returns the **original** object unchanged. The audit is patched with `applied=False`, `reason="sealed_actor_intelligence_v1_is_immutable"`, `schema_version`, `hypothetical_n_after=<proposed n_after>` and `n_after=n_before`.
- **Pre-v1** (PO:3943-3947): returns the reconciled object. The audit gets `applied=bool(merged)` and `reason` equal to `"legacy_reconcile_applied"` or `"no_duplicates"`.
- Has no side effects of its own. The caller writes `cast_reconciliation.json` and possibly `actors.json` (see Control flow).

### 5. Identity, URL and receipt primitives — PO:3950-4134
Each of these mirrors producer logic in `deerflow_bridge/deerflow_research.py`.
- `_actor_explicit_simulation_tier(actor)` (PO:3950-3961) reads `simulation_tier`. A `bool` gives None. The int 1-4 gives that int. A string `"1"`-`"4"` (exact single digit after strip) gives the int. Anything else gives None.
- `_actor_roster_name(actor)` (PO:3964-3966) returns `_actor_normalized_name(actor["name"])`.
- `_valid_actor_source_url(value)` (PO:3969-4003) is the URL admission rule. A URL is rejected when:
  - it is empty, contains whitespace, or has a control char (<32);
  - the scheme is not http/https, or there is no netloc;
  - it carries userinfo;
  - the host has fewer than 2 labels;
  - the unquoted path ends with `_`, `…` or `...` (truncation markers).
  For `*.wikipedia.org` [verifier: the test is `host.endswith("wikipedia.org")` (PO:3991), so it also matches bare `wikipedia.org` and any host merely ending in that string, such as `notwikipedia.org`] it also requires the path to start with `/wiki/` and the slug to be non-empty. A slug shorter than 3 chars passes only if it is all-uppercase alpha. A slug ending in `_<single letter>` is rejected. `TypeError`/`ValueError` give False.
- `_actor_source_is_fetched(source)` (PO:4006-4015) requires a valid URL and either (`source_origin` casefold `== "fetched"` and `reachable is True`) or `ok is True`.
- `_actor_as_items` (PO:4018-4023): `None`/`""` give `[]`, a list/tuple/set gives a list, and a scalar gives `[scalar]`.
- `_actor_stable_id(name)` (PO:4026-4033) returns `"actor_" + sha256(normalized_name)[:16]`, or `""` when the normalized name is empty.
- `_actor_normalized_name(value)` (PO:4036-4042) applies NFKC, then casefold, then whitespace collapse.
- `_actor_source_identity_url(value)` (PO:4045-4055) strips the URL and removes the trailing `/`. If the result is invalid it is returned unchanged. Otherwise the scheme and netloc are lowercased, the path and query are kept, the fragment is dropped, and the trailing `/` is stripped again.
- `_actor_stable_source_id(value)` (PO:4058-4064) returns `"src_" + sha256(identity_url)[:16]`, or `""` if the URL is invalid.
- `_actor_receipt_scopes(source)` (PO:4067-4095) projects each `receipt_scopes[]` dict to `{thread_id, lane, purpose, receipt_id, content_sha256(lower)}`, keeping only projections with at least one non-empty value. It then appends the "direct" top-level projection of the same five fields if that projection is non-empty and not already present.
- `_actor_is_track_b_purpose` (PO:4098-4100): the purpose casefold starts with `actor-` or `actor_`.
- `_actor_valid_sha256` (PO:4103-4104): exactly 64 hex chars (either case).
- `_actor_normalized_support_text` (PO:4107-4112): NFKC, casefold, whitespace collapse.
- `_actor_support_span(source_text, quote)` (PO:4115-4134) first tries an exact `find`, giving `{"basis": "exact_excerpt", start, end}`. If that fails it searches inside the normalized text, giving `{"basis": "normalized_excerpt", ...}`. In the second case the offsets are into the **normalized** text. If neither search matches, it returns None.

### 6. `_actor_source_lookup(source_rows)` — PO:4137-4190
- Collects the set of Track-B thread IDs: scopes with an actor-purpose, `lane` casefold `== "track-b"` and a non-empty `thread_id` (PO:4145-4152). If the set size is not 1, it appends `track_b_receipt_thread_unresolvable:count=N` (PO:4153-4157).
- For every **fetched** source:
  - The canonical `src_` ID must equal the supplied `source_id`. Otherwise it appends `source_id_not_canonical:<id|index>` and skips the source (PO:4161-4165).
  - A repeated ID appends `source_id_duplicate:` (PO:4166-4168).
  - Each admitted source is registered under these aliases: the source_id and its casefold; the raw URL and its casefold; the identity URL and its casefold; `s{index}` and `[s{index}]` (PO:4172-4177). `index` is the 1-based position in **all** source rows, fetched or not (PO:4158).
- A casefolded, whitespace-collapsed title becomes an alias only if it maps to exactly one ID (PO:4178-4183).
- If the Track-B thread is not unique, `lookup` and `records` are **cleared** (PO:4184-4189). After that no claim can resolve, so every claim fails as not quote/receipt-bound.
- Returns `(lookup, records, errors)`.

### 7. Search-result receipts — PO:4193-4262
- `_actor_search_result_receipt_id(receipt)` (PO:4193-4208) returns `"search_result_" + sha256(canonical JSON of {schema_version, thread_id, lane, purpose, query_sha256, result_sha256, result_chars})[:24]`. "Canonical JSON" here and below means `ensure_ascii=False, sort_keys=True, separators=(",", ":")`.
- `_actor_search_query_from_args(value)` (PO:4211-4219) handles two shapes. A dict yields `query`, `q` or `queries`, with a list joined by spaces. A string is used as-is. The result is whitespace-collapsed.
- `_actor_validated_search_result_receipt(value, required_thread_id)` (PO:4222-4262) rejects:
  - a non-dict, or a bool `result_chars`;
  - a `result_chars` that is not int-coercible.
  It then builds the canonical receipt and requires all of these:
  - `schema_version == "stage1-search-result-receipt/v1"` (PO:146);
  - the thread equals `required_thread_id`;
  - the lane casefold is `"track-b"`;
  - the purpose is an actor purpose;
  - the query is non-empty;
  - `query_sha256` is valid and equals sha256(query);
  - `result_sha256` is valid;
  - `result_chars > 0`;
  - `result_id` matches the recomputed ID.
  It returns the canonical dict including `result_id`, or None.

### 8. `_actor_track_b_provenance_reception_seals(sources, coverage)` — PO:4265-4372
The docstring says the coverage sidecar is producer output, not reception authority (PO:4271-4274). The function proceeds as follows:
- **Current thread.** It resolves the single current Track-B thread. If there is none, it appends `actor_dossier_track_b_receipt_thread_unresolvable:count=N` (PO:4277-4290).
- **Admitted sources** (PO:4292-4324). A source is admitted when it is fetched, has a canonical ID, and has at least one current-thread Track-B scope. The scope must have a `receipt_id`, a valid `content_sha256`, and, when the source itself has a valid `content_sha256`, a matching value. A source that has current-thread scopes but no valid one appends `actor_dossier_track_b_receipt_scope_invalid:<id>`. The admitted IDs are sorted and de-duplicated.
- **Receipts** (PO:4326-4352). `coverage["search_result_receipts"]` must be a list; otherwise it appends `actor_dossier_search_result_receipt_list_invalid`. Each entry must validate **and** equal its canonical form exactly, so extra keys or non-canonical casing fail; a failure appends `..._receipt_invalid:<i>`. Duplicate result IDs append `..._duplicate:<id>`. The raw list must equal the canonical list sorted by `result_id`; otherwise it appends `..._order_or_set_mismatch`.
- **Hash check.** `search_result_receipts_sha256` must equal sha256 of the canonical JSON of the sorted receipts (PO:4353-4361).
- **Returns** `{required_receipt_lane: "track-b", required_receipt_thread_id, admitted_source_ids, admitted_source_ids_sha256 (sha256 of "\n".join), search_result_receipts, search_result_receipts_sha256}` plus the errors (PO:4363-4372).

### 9. Claim normalization — PO:4375-4705
- `_actor_resolve_source_ref(value, lookup)` (PO:4375-4392): a dict ref uses `source_id`, `url`, `title` or `ref`. It tries, in order: the key, its casefold, the identity URL, the identity-URL casefold, and the normalized title. It returns `""` when nothing matches.
- `_actor_normalize_source_support(value, raw_refs, lookup, records)` (PO:4395-4493):
  - **Candidates.** It takes candidates from `source_support`, `evidence_support` or `supporting_evidence`. If there are none, it synthesizes one from a top-level `supporting_quote`, `exact_quote` or `source_quote`, using the only raw ref when exactly one exists (PO:4402-4417).
  - **Per candidate:**
    - Resolve the ref, defaulting to the only raw ref. The resolved ID must be in `records`.
    - Choose the **first** source scope that has a Track-B purpose, lane `track-b`, all five fields non-empty and a valid sha, and that agrees with every non-empty field the candidate supplied (PO:4442-4454).
    - Take the quote from `supporting_quote`, `exact_quote`, `quote` or `text`. Take the source text from `content`, falling back to `excerpt` (PO:4457-4466).
    - Require a span (PO:4467-4469).
    - If `content` exists, require `sha256(content) == scope.content_sha256` (PO:4470-4474).
    - Deduplicate on `(source_id, normalized quote)` (PO:4475-4478).
  - **Output rows** are `{source_id, supporting_quote, supporting_span (recomputed, not taken from input), receipt_id, content_sha256, source_publication_date (publication_date|published_at|date), thread_id, lane, purpose}` (PO:4479-4492).
- `_actor_claim_text(value)` (PO:4496-4512): returns the first non-empty value among `claim, summary, fact, detail, description, plan, action, investment, decision, preference, value`. If all are empty it returns `"; ".join("k=v")` over `driver, gains_if, loses_if, status, horizon, dependencies, trigger, basis`.
- `_actor_claim_projection(actor_id, dimension, claim)` (PO:4515-4553) builds the hash identity: `actor_id`, `dimension`, the whitespace-collapsed claim, `evidence_type`, `claim_valid_at`, `horizon`, `status`, `confidence`, sorted unique `dependencies`/`contradictions`, `qualifiers`, and a sorted support projection `{source_id, supporting_quote_sha256 (normalized quote), receipt_id, content_sha256}`. Spans, publication dates and thread/lane/purpose are **excluded**.
- `_actor_relationship_causal_attributes(relationship)` (PO:4556-4590) checks the keys `valence, polarity, sign, strength, grade, since, until, lag` (PO:222-231). An empty value raises `ValueError("... must be omitted when empty")`. A string must already be NFKC and whitespace-collapsed, or it raises `"not canonically normalized"`. A bool is allowed. An int/float must be finite. Any other type raises `"must be a JSON scalar"`. The function **rejects** non-canonical input rather than normalizing it.
- `_actor_normalize_claim(value, actor_id, dimension, lookup, records, causal_attributes=None)` (PO:4593-4705):
  - Non-dict input or empty claim text returns None.
  - It gathers raw refs from `source_refs, sources, source_urls, source_ids, citations, evidence_refs` on the claim and on its `qualifiers`.
  - `claim_valid_at` falls back through `claim_valid_at → valid_at → as_of_date → as_of`, on the claim first and then on the qualifiers.
  - `confidence` is one of {high, medium, low, unknown}; anything else becomes `unknown`.
  - `evidence_type` is lowercased with `-` and space mapped to `_`, then must be one of {verified_fact, actor_stated_claim, analyst_inference, contested, unknown}; anything else becomes `unknown`.
  - `qualifiers` keeps only the 35 keys in `_ACTOR_INTELLIGENCE_QUALIFIER_KEYS` (PO:213-221), plus `actor_knows` when it is a bool and `visibility` when it is in the 10-value set at PO:232-236.
  - `source_refs` is **rebuilt** as the sorted set of `source_id`s from the normalized support. Supplied refs only steer resolution.
  - `claim_sha256` is sha256 of the canonical JSON of the projection, with `causal_attributes` added when given. `claim_id` is `"claim_" + sha[:20]` (PO:4694-4704).
  - The returned claim has exactly these keys: `claim, evidence_type, claim_valid_at, as_of_date, horizon, status, confidence, source_refs, source_support, dependencies, contradictions, qualifiers, claim_id, claim_sha256`.

### 10. Hash helpers — PO:4708-4728
- `_actor_multiset_sha256(values)` (PO:4708-4715): sha256 of the canonical JSON of `{value: count}` with sorted keys.
- `_actor_lineage_id(payload)` (PO:4718-4728): `"actor_lineage_" + sha256(canonical JSON of payload minus {lineage_id, sealed_at})[:24]`. It mirrors the producer's `_actor_artifact_lineage_id` (deerflow_bridge/deerflow_research.py:3930).

### 11. `_actor_sealed_visible_claim_text(value)` — PO:4731-4828
This mirrors the Stage-1 "visible family claim" sanitizer (producer: deerflow_research.py:7559).
- **Normalize:** NFKC, newline normalization, then strip zero-width and bidi chars (`​-‏‪-‮⁠-⁯﻿`) and C0 control chars (PO:4733-4737).
- **Protected lines:** lines that fully match `^STAGE1BLOCKBOUNDARY[0-9A-F]{12}$` (PO:210-212, PO:4738-4741).
- **Unsafe lines:** lines matching any of the 11 prompt-injection regexes in `_ACTOR_UNSAFE_EVIDENCE_CONTROL_PATTERNS` (PO:150-203), for example "ignore … instructions", "you are now", "system prompt", "call … tool", "begin untrusted" (PO:4742-4748).
- **Sliding window** of 2-8 consecutive non-empty lines, where adjacent indexes differ by at most 3. If the joined window matches a pattern and no line in it is already unsafe, every non-protected line in the window becomes unsafe. If some lines are already unsafe but they do not explain all matched patterns, the window's lines that match the fragment pattern (PO:204-209) also become unsafe (PO:4750-4781).
- **Render:**
  - Unsafe lines become `"[unsafe instruction-like evidence text omitted]"` (PO:147-149).
  - Other lines are split into sentence fragments. Each fragment that matches a pattern is replaced, and consecutive replacements are deduplicated (PO:4783-4817).
  - Text is truncated to 900 chars (899 plus `…`). Then `[S\d+]` citation markers are removed, and NFKC plus whitespace collapse produce one line (PO:4820-4824).
- **Floor:** returns `""` if fewer than 24 `\w` chars remain once the replacement markers are removed (PO:4825-4828).

### 12. `_actor_claim_is_behavior_ready(claim)` — PO:4831-4842
A claim is behavior-ready when it is a dict with non-empty `source_support`, an `evidence_type` and `confidence` outside {"", "unknown"}, and non-empty `claim_valid_at`, `horizon` and `status`.

### 13. `_actor_dossier_reception_seals(dossier, lookup, records)` — PO:4845-5013
- **Ledger.** The dossier must contain exactly one `<!-- ACTOR_INTELLIGENCE_LEDGER_V1 {json} -->` (regex PO:237-240). Otherwise it returns `({}, ["dossier_ledger_count:N"])`. A JSON failure returns `dossier_ledger_unparseable`, and a non-dict returns `dossier_ledger_not_object` (PO:4853-4861).
- **Header checks.** A wrong `schema_version` appends `dossier_ledger_schema_mismatch` and continues. Empty `actors` returns early with `dossier_actor_rows_empty` (PO:4862-4866).
- **Per row:**
  - Compute `actor_id` from `name`; a missing name appends `dossier_actor_name_missing:i`.
  - The tier must be 1 or 2 and may be a string, through `_actor_explicit_simulation_tier`; otherwise it appends `dossier_actor_tier_invalid:id` and skips the row.
  - Append the ID and roster name.
  - `dimensions` must be a dict.
  - For each of the 17 `ACTOR_INTELLIGENCE_DIMENSIONS` (PO:114-132), the cell must be a dict. `status == "gap"` skips the dimension. `status == "covered"` requires a non-empty `claims` list. Any other status is an error (PO:4872-4911).
  - Each claim is normalized with that actor and dimension. A claim with no source support appends `dossier_claim_not_quote_receipt_bound:id:dim:i`. Valid claim hashes are collected, and behavior-ready claims are bucketed by dimension (PO:4912-4930).
- **Behavior families** (PO:4931-4983). There are 5 families, defined in `_ACTOR_BEHAVIOR_READY_FAMILIES` (PO:133-145):
  - `identity_history`;
  - `incentives_motivations_values`;
  - `capabilities_constraints`;
  - `actions_plans_investments`;
  - `decision_likely_actions_red_lines`.
  Each family's candidates are behavior-ready claims with non-empty sanitized visible text. If a family has none, it appends `dossier_behavior_family_missing:id:family`. Otherwise it selects the minimum by (dimension order within the family, `claim_sha256`) and records `{dimension, claim_id, claim_sha256, visible_claim_text, source_ids}`.
- **Returns** these seals (PO:4990-5013):
  - `tier_1_2_actor_count`;
  - `tier_1_2_actor_roster_sha256`: sha256 of the sorted roster joined with `\n`;
  - `tier_1_2_actor_ids_ordered_sha256`;
  - `tier_1_2_actor_ids_multiset_sha256`;
  - `claim_projection_count`;
  - `claim_projection_multiset_sha256`;
  - `required_behavior_ready_families`;
  - `behavior_ready_family_count`;
  - `behavior_ready_family_slots`: actors × 5;
  - `behavior_ready_family_failures`: always `[]`;
  - `behavior_family_projection`;
  - `behavior_family_projection_sha256`.

### 14. `_actor_question_hash(question)` — PO:5016-5018
Collapses whitespace, strips, lowercases, and returns `sha256(...)[:16]`. This is the same algorithm as the producer's `_question_hash` (deerflow_research.py:901).

### 15. `_actor_lineage_reception_errors(handoff_dir, ...)` — PO:5021-5191
- **Root.** `root = realpath(handoff_dir)`. If `root` is falsy or not a directory, it returns `["actor_reception_handoff_missing"]` (PO:5036-5038). See Surprises #1 for the empty-string case.
- **Manifest** (PO:5040-5048). `research_contract_manifest.json` (PO:3140) must have a `files` dict that contains `actor_intelligence_lineage.json`; otherwise it appends `actor_lineage_not_manifested`. If the entry is present, `_validate_research_contract(root)` (PO:3418) must pass; otherwise it appends `research_contract_invalid_at_actor_reception`.
- **Memory vs disk** (PO:5050-5061). It re-reads `actors.json`, `sources.json`, `research_report.md` and `actor_dossier.md` and requires equality with the in-memory objects. Mismatches append `*_memory_disk_mismatch`. [verifier: clarification — `actors.json`/`sources.json` are compared as parsed JSON values (`_read_json`, PO:5050-5057), not as bytes, and the in-memory `sources` here is the dict-filtered `source_rows` (PO:5655). Byte binding comes only from the lineage sha256 checks (PO:5134-5143)]
- **Lineage file** `actor_intelligence_lineage.json` (PO:109). A missing or non-dict file returns early with `actor_lineage_missing_or_invalid` (PO:5063-5066). Otherwise it checks:
  - `schema_version == "actor-artifact-lineage/v1"` (PO:110);
  - `lineage_id` recomputes correctly;
  - `question_hash` matches `state.prompt`, when `expected_question` is set;
  - `depth` matches;
  - `run_id` matches `pipeline_id`;
  - `attempt_id` is present. If `expected_run_id` is set but no attempt IDs are known, it appends `actor_lineage_attempt_authority_missing`. If attempt IDs are known and this one is not among them, it appends `actor_lineage_attempt_mismatch` (PO:5067-5087);
  - `lane_id ∈ {outer-track-1, global-synthesis, global-synthesis-recovery}` (PO:5088-5092);
  - the lineage `thread_id` equals `meta.json["thread_id"]` (PO:5093-5102).
- **Checkpoint.** Only when the lineage has `checkpoint_id`: `research_checkpoint.json` must exist, its `checkpoint_id` must equal the lineage's and `_research_checkpoint_identity` (PO:2956), and the checkpoint's `question_hash, depth, run_id, attempt_id, lane_id, thread_id` must equal the lineage values (PO:5104-5132).
- **Artifact hashes.** It streams sha256 (`_sha256_file`, PO:7401) for the report, dossier, sources and actors files and compares each to the lineage's `report_sha256`, `dossier_sha256`, `sources_file_sha256` and `actors_file_sha256` (PO:5134-5143). It also checks the lineage's `actor_ids_ordered_sha256`, `actor_ids_multiset_sha256` and `claim_projection_multiset_sha256` against the contract (PO:5144-5149).
- **Coverage sidecar** `actor_dossier_coverage.json`. It must be a dict with `accountable is True`; otherwise it appends `actor_dossier_coverage_missing_or_unaccountable`. When it passes, the provenance seals are recomputed (§8) and the sidecar must equal `{schema_version, source_binding_required: True, required_receipt_purpose: "track-b", **dossier_seals, **provenance_seals}` key by key (PO:5151-5168).
- **`meta.json["actor_intelligence"]`.** It must exist, and its keys `schema_version, actor_count, tier_1_2_actor_count, coverage, report_sha256, dossier_sha256, sources_sha256, actor_ids_sha256, actor_ids_ordered_sha256, actor_ids_multiset_sha256, tier_1_2_actor_roster_sha256, claim_projection_count, claim_projection_multiset_sha256, relationship_count, relationships_sha256, relationship_omission_count, source_provenance` must equal the contract. Its `lineage_id` and `lineage_file` must equal the lineage values, and `dossier_coverage` must equal the sidecar (PO:5170-5190). [verifier: only `lineage_id` is compared to the lineage file (PO:5185). `lineage_file` must equal the constant `ACTOR_INTELLIGENCE_LINEAGE_FILENAME` (PO:5187, PO:109). `dossier_coverage` is compared only when the sidecar parsed as a dict (PO:5189)]

### 16. `_actor_intelligence_reception_errors(actors, *, report, dossier, sources, handoff_dir, expected_question, expected_depth, expected_run_id, expected_attempt_ids)` — PO:5194-5665
This is the main validator. It returns a list of error codes, and an empty list means the plane passed. In order:
1. **Shape** (PO:5214-5223). A non-dict `actors` returns `["actors_not_object"]` immediately. A non-list `actors["actors"]` returns `["actor_rows_not_list"]` immediately. An empty list appends `actor_rows_empty`, and non-dict rows append `actor_row_not_object`.
2. **Top contract** (PO:5225-5234). A missing `actor_intelligence_contract` appends `top_contract_missing` and returns. Otherwise it checks `schema_version` and that `dimensions` equals the 17-item list.
3. **Sources** (PO:5236-5252). `None` becomes `[]` with **no error**. A list keeps only its dict rows, with an error if any were dropped. Any other type appends `sources_not_list`. The canonical sources hash is taken over the rows sorted by `source_id`. `_actor_source_lookup` (§6) then builds `lookup` and `records`.
4. **Per actor** (PO:5263-5389):
   - The name must be present.
   - `actor_id` must be present, unique, and equal `_actor_stable_id(name)`; otherwise it appends `actor_id_not_semantic`. [verifier: each failure has its own code. A missing ID gives `actor_id_missing:<index>` (PO:5268-5269) and a repeat gives `actor_id_duplicate` (PO:5270-5271). Only a present but wrong ID gives `actor_id_not_semantic` (PO:5275-5276). The ID is compared after `.strip()` (PO:5264), so surrounding whitespace is tolerated]
   - `simulation_tier` must be a real `int` in {1, 2}; otherwise it appends `simulation_tier_not_exact_enum` (PO:5277-5286).
   - `aliases` must be a list or None.
   - The name and aliases feed a namespace-owner map.
   - `intelligence` must be a dict with the v1 `schema_version`. `dimensions` must be a dict whose keys are exactly the 17 dimensions **in order** (PO:5310-5311). `evidence_gaps` must be a dict and `omission_audit` a list.
   - For each dimension, the value must be a list of dicts. Each claim must normalize with source support, otherwise `dimension_claim_not_quote_receipt_bound`. Each claim must also be **exactly equal** (dict equality) to its normalized form, otherwise `dimension_claim_canonical_mismatch` (PO:5336-5356). The `claim_sha256` values are collected.
   - Slot counts: a non-empty list is a covered slot, and a list with any truthy `source_support` is a grounded slot. Gaps must be lists and their lengths are summed.
   - The per-actor `intelligence.coverage` must equal `{covered_dimensions, grounded_dimensions, dimension_coverage_ratio, grounded_coverage_ratio (round 4), explicit_gap_count}`; otherwise it appends `actor_coverage_binding_mismatch` (PO:5377-5389).
5. **Namespace overlap** (PO:5391-5393). Any normalized name or alias owned by more than one actor appends `actor_identity_namespace_overlap:<identity>`.
6. **Roster seals** (PO:5395-5418): `actor_count`, `tier_1_2_actor_count` (zero appends `tier_1_2_actor_count_zero`), `actor_ids_sha256` (the multiset hash), `actor_ids_ordered_sha256` (sha256 of the IDs joined with `\n`), `actor_ids_multiset_sha256`, and `tier_1_2_actor_roster_sha256` (sorted normalized names).
7. **Report and dossier** (PO:5420-5431). An empty report appends `report_empty`. `report_sha256` and `dossier_sha256` must match sha256 of the exact UTF-8 strings. A non-string dossier is treated as `""`.
8. **Source seals** (PO:5433-5475). `source_count` and `sources_sha256` must match. `source_provenance` must equal `{fetched_source_count, content_hash_count, receipt_count, providers (sorted unique), cache_hit_total (sum of max(0, int)), sha256 of canonical [{source_id, content_sha256, receipt_id, provider, cache_hits, receipt_scopes}] over fetched rows sorted by id}`.
9. **Claim seals** (PO:5477-5486): `claim_projection_count` and `claim_projection_multiset_sha256`. These cover dimension claims only; relationship claims are excluded.
10. **Relationships** (PO:5488-5607). `relationships` must be a list of dicts. For each relation:
    - Both endpoint IDs must resolve to actors, and the `source`/`target` names must equal those actors' `name`.
    - `type` must already be canonical: upper case and matching `[A-Z][A-Z0-9_]{1,63}`, otherwise it would be `OTHER`. `relation_label` must already be stripped.
    - The claim is rebuilt: copy the relation, set `claim = basis`, pop `type`, `basis` and the causal keys, then run `_actor_normalize_claim` with `dimension="relationship"` and `causal_attributes`. It must have source support.
    - Twelve fields must equal the received relation: `claim` (compared to `basis`), `evidence_type`, `claim_valid_at`, `as_of_date`, `horizon`, `status`, `confidence`, `source_refs`, `source_support`, `qualifiers`, `claim_id`, `claim_sha256`. The first mismatch appends an error and stops the comparison.
    - `relationship_id` must be `"relation_" + sha256(canonical {source_actor_id, target_actor_id, type, relation_label, claim_sha256, causal_attributes})[:20]`. Duplicate IDs are reported with both indexes.
    - `relationship_count` and `relationships_sha256` (canonical JSON of the received list, order-sensitive) must match. `relationship_omission_audit` must be a list whose length equals `relationship_omission_count`.
11. **Dossier seals** (PO:5609-5633). It runs §13 and requires these bindings:
    - dossier `tier_1_2_actor_count` = contract `tier_1_2_actor_count`;
    - dossier `tier_1_2_actor_roster_sha256` = contract `tier_1_2_actor_roster_sha256`;
    - dossier `tier_1_2_actor_ids_ordered_sha256` = contract `actor_ids_ordered_sha256`;
    - dossier `tier_1_2_actor_ids_multiset_sha256` = contract `actor_ids_multiset_sha256`;
    - dossier `claim_projection_count` = contract `claim_projection_count`;
    - dossier `claim_projection_multiset_sha256` = contract `claim_projection_multiset_sha256`.
    As a result the dossier ledger must list exactly the same actors in the same order, with the same claim multiset, as `actors.json`.
12. **Global coverage** (PO:5635-5649). `contract.coverage` must equal `{dimension_slots = actors × 17, covered_dimension_slots, grounded_dimension_slots, coverage_ratio, grounded_coverage_ratio (round 4, 0.0 when there are no slots), explicit_gap_count}`.
13. **Timestamp.** `generated_at` must be non-empty (PO:5650-5651).
14. **Lineage.** It appends `_actor_lineage_reception_errors(...)` (§15) and passes the **filtered** `source_rows` and the string-coerced report and dossier (PO:5652-5664).

### 17. `_enforce_actor_intelligence_reception(state, actors, *, report, dossier, sources, handoff_dir="")` — PO:5668-5737
This is the gate. It reads `state.options["actor_intelligence_policy_v1"]`, which is pinned at admission by `admission_actor_intelligence_policy_v1` (PO:832-852, called at PO:7962-7963) and inherited by forks/continues (PO:8321-8326). [verifier: PO:8321-8326 lies in `fork` (PO:8280) and copies the policy explicitly. `continue_to_full` (PO:8214) flips `mode` on the same state, so the policy persists without a copy]
- **Policy `None`** (pre-policy run): records `{"required": False, "passed": True, "reason": "legacy_run_without_pinned_policy"}` and returns (PO:5679-5688).
- **Malformed policy** (not a dict, wrong `version` `"actor-intelligence-policy/v1"` (PO:108), wrong `schema_version`, or non-bool `required`): raises `RuntimeError("actor-intelligence/v1 reception policy is malformed")` (PO:5689-5695).
- **`required is False`:** records `passed: True` with `reason` = `policy.not_required_reason` (for example `"research_engine_v3_emits_unsealed_actor_plane"`, PO:829) or `"actor_track_explicitly_disabled_at_admission"`, and returns (PO:5696-5707).
- **`required is True`:**
  - `expected_attempt_ids = _research_budget_attempt_ids(state)`, which is the set of `state.options["research_budget_epochs"][].epoch` (PO:1806-1812).
  - It runs the validator with `expected_question=state.prompt`, `expected_depth=state.options["depth"] or Config.DEERFLOW_RESEARCH_DEPTH` (fallback `"standard"` if the attribute is absent), and `expected_run_id=state.pipeline_id` (PO:5709-5723).
  - It records `{required: True, passed, schema_version, actor_count, errors}` in `state.options["actor_intelligence_reception"]` (PO:5724-5732).
  - If there are errors it raises `RuntimeError("actor-intelligence/v1 reception failed before ontology/graph: " + "; ".join(errors[:12]))` (PO:5733-5737).
- Persistence: the function does not call `PipelineManager.save` itself. The `_run` failure handler saves the state (PO:13381-13387), and the success path persists it through `_complete_stage`.

### 18. `_forecast_inputs_missing(actors)` — PO:5740-5749
A non-dict gives False (there is nowhere to inject). Otherwise it returns `not valid_scenario_distribution(actors.get("forecast_inputs"))`. The validator (utils/actors.py:2555-2591) requires 1-6 uniquely named scenario rows, each with a parseable `probability|likelihood|base_rate|prob|probability_band`, whose midpoints sum to 1 ± 0.02.

### 19. `inject_forecast_inputs_from_report(actors, report_md)` — PO:5752-5782
- Sealed v1 gives None (no-op, PO:5767-5768).
- A cast that is not missing gives None (PO:5769-5770).
- Otherwise it lazily imports and calls `forecast_inputs_from_report_markdown(report_md or "")` (utils/actors.py:2765). That function is pure and makes no LLM call. It scans scenario-ish headings, accepts the first section with 2-6 probability-bearing rows whose midpoints sum to [0.9, 1.1], and returns `{"scenarios": rows, "base_rates": []}` or `{}` (utils/actors.py:2787-2831).
- Any exception gives None (PO:5771-5775).
- A parsed result without a non-empty `scenarios` list gives None.
- On success it **replaces** `actors["forecast_inputs"]` in place with the parsed dict and returns it (PO:5781-5782).

### 20. PAR-2 outer-lane angles — PO:5785-5818
- `_TRACK2_PREFIX` (PO:5796-5802) is a Chinese-language prompt preamble for base rates, reference classes and historical analogues.
- `_TRACK3_PREFIX` (PO:5803-5809) is a preamble for actor incentives, the contrarian case and market pricing.
- `_RESEARCH_TRACK_ANGLES` (PO:5812-5818) is `[(short_key, H1 title, prefix)]`: `("base-evidence", …, "")`, `("base-rates", …, _TRACK2_PREFIX)`, `("incentives-contrarian", …, _TRACK3_PREFIX)`.
- Track 1 has an empty prefix, so `track_prompt == state.prompt` byte for byte (PO:11178).
- The list length (3) caps the lanes: `angles = _RESEARCH_TRACK_ANGLES[:max(1, n_tracks)]` (PO:11077).
- `angles[i][0]` is recorded in the parallel meta (PO:11573, PO:11726).

## Control flow

**Research stage inside `PipelineOrchestrator._run`** (PO:11883, `try` at PO:11901):
1. **Reuse.** When `_reuse_research` is true, `research = _load_research_handoff(handoff_dir)` (PO:11962). Synthesis-only recovery ends with `loaded = _load_research_handoff(handoff_dir)` (PO:11052). Otherwise `research` comes from `DeerFlowResearchRunner.run` (single lane, PO:12047) or `_run_parallel_research_tracks` (PO:11990, which uses `_RESEARCH_TRACK_ANGLES`).
2. `report_md = research["report"]` (PO:12079). Research lint may replace `report_md` and `research["report"]`, but only for a manifest-owned report that is not judge-bound (PO:12097-12136).
3. `dossier_md = research.get("actor_dossier")` and `actors = research.get("actors")` (PO:12151-12152).
4. **Cast reconcile.** This step runs only if `Config.CAST_RECONCILE` (config.py:372, default True) and `actors` is truthy. The caller runs `_reconcile_research_cast(actors)` (PO:12158). When the audit has merges:
   - if `applied`, it swaps `actors`/`research["actors"]`, and writes `actors.json` directly **only when no research contract manifest exists** (PO:12168-12173);
   - it always writes `cast_reconciliation.json`, swallowing write errors (PO:12174-12177); [verifier: the write is attempted in the same `try` as the `actors.json` write (PO:12166-12177). If that write raises, `cast_reconciliation.json` is silently skipped]
   - it sets `state.options["cast_reconciliation"]` (PO:12178).
   An exception is fatal for sealed v1 (`RuntimeError("sealed actor-intelligence/v1 duplicate audit failed")`, PO:12198-12202). For legacy casts it only logs a warning.
5. Research telemetry, embedder warm-up, quality surfacing and dossier coverage run next. They are outside this slice.
6. **SIM-ADD-1 at research finalization** (PO:12238-12261). The caller runs `inject_forecast_inputs_from_report(actors, report_md)`. On a hit it sets `research["actors"] = actors`. On a miss it logs a "loud" warning, with a v1-specific message when sealed. Any exception is logged and ignored.
7. **Finalize.** `_finalize_research_contract(handoff_dir, research)` (PO:12267). This seals post-processing into a new manifest-last generation **only if a manifest exists** (PO:3629-3631).
8. **Gate.** If `state.mode != "research_only"`, the caller runs `_enforce_actor_intelligence_reception(state, actors, report=report_md, dossier=dossier_md, sources=research.get("sources"), handoff_dir=handoff_dir)` (PO:12274-12286). This happens for both reused and fresh research.
9. `_complete_stage(STAGE_RESEARCH)` runs only after the gate passes (PO:12287). A `RuntimeError` from the gate reaches the generic handler, which sets `state.status = "failed"`, fails the current stage, saves the state and fails the task (PO:13381-13392).

**Later stages that reuse slice helpers:**
- GRAPH reuse checks `_is_sealed_actor_intelligence_v1(actors)` before validating the persisted actor graph-seed manifest (PO:12402).
- PREPARE runs a second injection pass, `_fi_prep = inject_forecast_inputs_from_report(actors, report_md)` (PO:12885). It runs only when calendar mode or `Config.SIM_DECISION_CHANNEL` is on and the run has not already completed (PO:12879). Afterwards `world_state_seed_from_actors(actors)` is called.

**Internal call tree of the gate:**
```
_enforce_actor_intelligence_reception (5668)
 ├─ _research_budget_attempt_ids (1806)
 └─ _actor_intelligence_reception_errors (5194)
     ├─ _actor_source_lookup (4137) → _actor_receipt_scopes, _actor_source_is_fetched → _valid_actor_source_url, _actor_stable_source_id
     ├─ per-actor: _actor_stable_id, _actor_explicit_simulation_tier, _actor_roster_name
     │   └─ _actor_normalize_claim (4593) → _actor_claim_text, _actor_normalize_source_support (4395)
     │        → _actor_resolve_source_ref, _actor_support_span, _actor_claim_projection
     ├─ relationships: _actor_relationship_causal_attributes (4556) → _actor_normalize_claim
     ├─ _actor_dossier_reception_seals (4845) → _actor_normalize_claim, _actor_claim_is_behavior_ready, _actor_sealed_visible_claim_text
     └─ _actor_lineage_reception_errors (5021)
          ├─ _research_contract_path (3321), _validate_research_contract (3418), _read_json/_read_text
          ├─ _actor_lineage_id, _actor_question_hash, _research_checkpoint_identity (2956), _sha256_file (7401)
          └─ _actor_track_b_provenance_reception_seals (4265) → _actor_validated_search_result_receipt → _actor_search_result_receipt_id
```

## Data & artifacts

All paths are under `handoff/` (`state.handoff_dir`, or `PipelineManager.handoff_dir(pipeline_id)`). **The slice writes no files.**

| File | Read by | Format / key fields used |
|---|---|---|
| `research_report.md` | `_load_research_handoff` PO:3865; lineage PO:5052, PO:5135 | UTF-8 markdown; at least 400 stripped chars; sha256 bound to `contract.report_sha256` and `lineage.report_sha256` |
| `actor_dossier.md` | PO:3872, PO:5053, PO:5136 | markdown with exactly one `<!-- ACTOR_INTELLIGENCE_LEDGER_V1 {json} -->`. Ledger keys: `schema_version`, `actors[]{name, simulation_tier, dimensions{<dim>{status: covered/gap, claims[]}}}` |
| `actors.json` | PO:3882, PO:5050, PO:5138 | v1 shape below |
| `sources.json` | PO:3883, PO:5051, PO:5137 | list of `{url, source_id ("src_"+16hex), source_origin, reachable, ok, title, content, excerpt, content_sha256, receipt_id, thread_id, lane, purpose, receipt_scopes[], provider, cache_hits, publication_date/published_at/date}` |
| `timeline.json` | PO:3884 | passed through, not validated |
| `research_contract_manifest.json` | PO:5040 | must list `actor_intelligence_lineage.json` under `files` and pass `_validate_research_contract` |
| `actor_intelligence_lineage.json` | PO:5063-5064 | `{schema_version "actor-artifact-lineage/v1", question_hash, depth, run_id, attempt_id, lane_id, thread_id, checkpoint_id, report_sha256, dossier_sha256, sources_file_sha256, actors_file_sha256, actor_ids_ordered_sha256, actor_ids_multiset_sha256, claim_projection_multiset_sha256, sealed_at, lineage_id}` (producer writer deerflow_bridge/deerflow_research.py:3960-3994) |
| `meta.json` | PO:5094, PO:5170 | `thread_id`; `actor_intelligence{…17 contract mirrors…, lineage_id, lineage_file, dossier_coverage}` |
| `research_checkpoint.json` | PO:5108 (only if `lineage.checkpoint_id`) | `checkpoint_id` and identity keys (PO:2958-2964) |
| `actor_dossier_coverage.json` | PO:5151 | `accountable: true`, `schema_version`, `source_binding_required`, `required_receipt_purpose`, all dossier seals (§13), all provenance seals (§8), `search_result_receipts[]` and its sha256 |
| `cast_reconciliation.json` | written by the caller (PO:12174), not by the slice | reconcile audit |

**`actors.json` actor-intelligence/v1 shape**, as implied by the checks:
- `actor_intelligence_contract`: `{schema_version, dimensions[17], actor_count, tier_1_2_actor_count, actor_ids_sha256, actor_ids_ordered_sha256, actor_ids_multiset_sha256, tier_1_2_actor_roster_sha256, report_sha256, dossier_sha256, source_count, sources_sha256, source_provenance{fetched_source_count, content_hash_count, receipt_count, providers, cache_hit_total, sha256}, claim_projection_count, claim_projection_multiset_sha256, relationship_count, relationships_sha256, relationship_omission_count, coverage{dimension_slots, covered_dimension_slots, grounded_dimension_slots, coverage_ratio, grounded_coverage_ratio, explicit_gap_count}, generated_at}`.
- `actors[]`: `{actor_id ("actor_"+16hex of the normalized name), name, aliases[], simulation_tier (int 1|2), intelligence{schema_version, dimensions{17 ordered lists of canonical claims}, evidence_gaps{dim: list}, omission_audit[], coverage{covered_dimensions, grounded_dimensions, dimension_coverage_ratio, grounded_coverage_ratio, explicit_gap_count}}}`.
- `relationships[]`: `{source_actor_id, target_actor_id, source, target, type, relation_label, basis, evidence_type, claim_valid_at, as_of_date, horizon, status, confidence, source_refs, source_support, qualifiers, claim_id, claim_sha256, relationship_id ("relation_"+20hex), [valence|polarity|sign|strength|grade|since|until|lag]}`.
- `relationship_omission_audit[]`.
- Optional `forecast_inputs{scenarios[], base_rates[]}`, which only pre-v1 casts receive by injection.

**In-memory structures**
- The `research` dict returned by `_load_research_handoff` (PO:3876-3887).
- `state.options["actor_intelligence_reception"]` (PO:5683, PO:5697, PO:5724). It is written but never read by `backend/app` or `frontend/src` (grep).
- `actors["forecast_inputs"]`, mutated in place (PO:5781).
- `lookup` (alias → `source_id`) and `records` (`source_id` → source row) from §6.

**ID and hash formats**
- `actor_` + 16 hex (PO:4031)
- `src_` + 16 hex (PO:4062)
- `claim_` + 20 hex (PO:4703)
- `relation_` + 20 hex (PO:5570-5575)
- `search_result_` + 24 hex (PO:4208)
- `actor_lineage_` + 24 hex (PO:4723)
- question hash: 16 hex (PO:5018)

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `state.options["actor_intelligence_policy_v1"]` | pinned at admission; absent for pre-policy runs | Decides whether reception is required (see §17) | PO:5678; pinned at PO:7962-7963 |
| `DEERFLOW_DUAL_TRACK` (env → `Config`) | `True` | Policy `required = dual_track and engine == legacy`; v3 runs pin `required=False` with `not_required_reason` | config.py:1228; PO:843-851 |
| `Config.DEERFLOW_RESEARCH_DEPTH` | `'deep'` in config; the slice's `getattr` fallback is `"standard"` | `expected_depth` when `state.options["depth"]` is unset | config.py:1159; PO:5717-5720 |
| `state.options["depth"]` | none [verifier: admission pins `options["depth"] = depth or Config.DEERFLOW_RESEARCH_DEPTH` (PO:7955), so it is normally set] | `expected_depth` for the lineage depth check | PO:5718 |
| `state.options["research_budget_epochs"]` | populated by `_activate_research_budget_epoch` | Admissible lineage `attempt_id`s | PO:1806-1812, PO:5709 |
| `RESEARCH_MIN_REPORT_CHARS` | 400 (0 disables) | Degraded-dossier length floor on resume. The report floor in `_load_research_handoff` is a **hard-coded** 400 | config.py:511; PO:2820; PO:3869 |
| `CAST_RECONCILE` (caller) | `True` | Whether `_reconcile_research_cast` runs | config.py:372; PO:12156 |
| `SIM_DECISION_CHANNEL` / calendar mode (caller) | off / depends on `SIM_TEMPORAL_MODE` [verifier: both default ON. `SIM_DECISION_CHANNEL` defaults to `'true'` (config.py:1483), and `SIM_TEMPORAL_MODE` defaults to `'calendar'` (config.py:1067; `_calendar_mode` PO:7296-7303). The PREPARE pass therefore runs by default unless `_run_already_done` (PO:12848, PO:12879)] | Gates the PREPARE-stage forecast-input injection | PO:12878-12885 |
| `RESEARCH_PARALLEL_TRACKS` (caller) | 3 | Number of outer lanes (legacy engine), capped at `len(_RESEARCH_TRACK_ANGLES)` = 3 | PO:5955-5980, PO:11077 |

Hard-coded constants in the slice:
- 400-char report floor (PO:3869).
- Visible-text cap of 900 chars and a 24-word-char floor (PO:4821, PO:4826).
- Sliding window of 2-8 lines with gap ≤ 3 (PO:4750-4756).
- Error list truncated to 12 in the exception message (PO:5736).
- Allowed lineage lanes (PO:5089-5091).
- Tier enum {1, 2} for reception (PO:5279, PO:4881).

## External calls

None in this slice:
- no LLM or provider calls;
- no HTTP (`urllib.parse` is used only for string parsing, PO:3972, PO:4046);
- no subprocess;
- no graph or database access.

I/O is limited to local file reads through `_read_text`, `_read_json` and `_sha256_file`, plus `os.path.isdir`/`realpath` (PO:5036-5037). `_validate_research_contract` (PO:3418) also reads and hashes the files the manifest lists.

## Cross-module edges

**Callers into the slice** (grep across `backend/`):
- `_load_research_handoff`: PO:11052 (synthesis recovery) and PO:11962 (reuse). Tests: backend/scripts/test_pipeline_resume.py:219-238 and backend/tests/test_research_engine_v3_round2.py:899.
- `_reconcile_research_cast`: PO:12158. Tests: backend/tests/test_pipeline_actor_contract.py:427, :456.
- `_is_sealed_actor_intelligence_v1`: PO:7012, PO:7098, PO:7201 (actor-context/role-prompt code, another slice), PO:12199, PO:12248, PO:12402.
- `_enforce_actor_intelligence_reception`: PO:12279. Tests: test_pipeline_actor_contract.py:1325-1365, test_orchestrator_research_wiring.py:1859, test_research_engine_v3_round2.py:892.
- `_actor_intelligence_reception_errors`: PO:5710. Tests: test_pipeline_actor_contract.py:257.
- `inject_forecast_inputs_from_report` / `_forecast_inputs_missing`: PO:12239, PO:12246, PO:12885. Tests: backend/tests/test_sessionb_sim_additivity.py:24-141, test_pipeline_actor_contract.py:1381.
- `_RESEARCH_TRACK_ANGLES`: PO:11077. Tests: backend/tests/test_parallel_research_merge.py:390-401.

**Callees outside the slice**
- Orchestrator helpers: `_read_text` (PO:2925), `_read_json` (PO:2933), `_is_degraded_dossier` (PO:2814), `_research_contract_path` (PO:3321), `_validate_research_contract` (PO:3418), `_research_checkpoint_identity` (PO:2956), `_sha256_file` (PO:7401), `_research_budget_attempt_ids` (PO:1806).
- `backend/app/utils/actors.py`: `reconcile_cast` (:2333), `forecast_inputs_from_report_markdown` (:2765), `valid_scenario_distribution` (:2555, imported at PO:69-76).
- Module constants: PO:107-240.

**Producer mirrors in `deerflow_bridge/deerflow_research.py`.** These are duplicated rather than shared, so any drift on either side breaks reception:
- `_question_hash` (:901)
- `_SEARCH_RESULT_RECEIPT_SCHEMA` / `_search_result_receipt_id` (:1618, :1631)
- `_receipt_scopes` (:2683)
- `_claim_projection_payload` (:3075)
- `_normalize_intelligence_claim` (:3139)
- `_actor_artifact_lineage_id` / `_write_actor_artifact_lineage` (:3930-3995)
- `persist_final_actor_intelligence_contract` (:4131)
- `_sealed_visible_claim_text` (:7559)
- the ledger regex `_ACTOR_LEDGER_RE` (:13344-13347)
- `actor_dossier_coverage_audit` (:13456)

## Invariants, gates, validation

1. **A resumed report must be at least 400 stripped chars**, or resume from research fails (PO:3869-3870). A degraded dossier is treated as absent (PO:3873-3875).
2. **A sealed v1 cast is immutable in the parent.** Cast reconcile returns the original object (PO:3933-3942), forecast injection is a no-op (PO:5767-5768), and an audit failure is fatal (PO:12198-12202).
3. **Reception runs only in full mode** (`state.mode != "research_only"`, PO:12274), and **only blocks when the pinned policy has `required: True`** (PO:5696-5707). Pre-policy runs pass with reason `legacy_run_without_pinned_policy` (PO:5679-5688).
4. **A malformed policy always blocks**, even before validation runs (PO:5689-5695).
5. **Identity is semantic**:
   - `actor_id` must equal `"actor_" + sha256(NFKC casefold name)[:16]` (PO:5274-5276);
   - every fetched `source_id` must equal `"src_" + sha256(identity URL)[:16]` (PO:4161-4165);
   - no normalized name or alias may belong to two actors (PO:5391-5393).
6. **Every actor in `actors.json` must be Tier 1 or 2, as an exact `int`** (PO:5277-5283), and at least one must exist (PO:5402-5403).
7. **Every claim must be byte-canonical**: dict-equal to the parent's re-normalization, quote-bound to a fetched source's content (exact or normalized excerpt), bound to a Track-B receipt scope, and, when content is present, hash-matched to `scope.content_sha256` (PO:4442-4474, PO:5336-5356).
8. **There must be exactly one Track-B actor-research thread** across all source receipt scopes. Otherwise lookups are cleared and every claim fails (PO:4153-4157, PO:4184-4189, PO:4285-4290).
9. **The dossier ledger and `actors.json` must agree**: same ordered actor IDs, same claim-hash multiset and same tier roster (PO:5615-5633). Every actor must have one behavior-ready, sanitizable claim in each of the 5 behavior families (PO:4952-4956).
10. **Lineage binding**: the lineage file is in the manifest, the contract validates, memory equals disk, the four artifact sha256s match, the `question_hash`/`depth`/`run_id`/`attempt_id` match the parent's authority, the lane is one of three, `thread_id` equals `meta.thread_id`, and the optional checkpoint identity matches (PO:5040-5149).
11. **The coverage sidecar and `meta.actor_intelligence`** must equal the parent's recomputation and the top contract (PO:5151-5190).
12. **Forecast injection** happens only for non-v1 dicts whose `forecast_inputs` fail `valid_scenario_distribution` (PO:5740-5749, PO:5767-5770). It never raises (PO:5771-5775).

## Failure modes & recovery

| Condition | Effect | Recovery |
|---|---|---|
| Report missing or shorter than 400 chars on reuse/recovery | `RuntimeError` from `_load_research_handoff` (PO:3870), so RESEARCH fails (PO:13381-13387) | Rerun research (new run or resume without reuse) |
| Degraded dossier on resume | Dossier becomes `""` (PO:3874-3875). For required-v1 runs, reception then fails with `dossier_memory_disk_mismatch` and `dossier_sha256_mismatch` (PO:5060-5061, PO:5428-5431) | Upstream research rerun |
| Malformed pinned policy | `RuntimeError("…policy is malformed")` (PO:5695) | Manual state repair; no automatic path |
| Any reception error with `required=True` | `state.options["actor_intelligence_reception"].errors` is populated and `RuntimeError` names the first 12 errors (PO:5724-5737). The stage and pipeline are marked failed and the task fails (PO:13381-13392). ONTOLOGY/GRAPH never run | Per the code comments, a Stage-1 (producer) rerun. No fallback to the legacy ontology path for required runs (comment PO:12275-12278) |
| `reconcile_cast` raises on a sealed v1 cast | `RuntimeError("sealed actor-intelligence/v1 duplicate audit failed")` (PO:12199-12202) | Fix the producer cast or the reconcile code |
| `reconcile_cast` raises on a legacy cast | Warning only; the original cast is kept (PO:12203) | none needed |
| `cast_reconciliation.json` write fails | Silently swallowed (PO:12176-12177) | none |
| Report has no parseable scenario distribution | `inject_*` returns None; the caller logs "world_state 种子将为空…" (PO:12254-12258) | Decision channel stays off |
| Sealed v1 cast has no `forecast_inputs` | Warning only (PO:12248-12253); never injected | Producer must emit them |
| Parse exception during injection | Returns None (PO:5774-5775), or the caller logs a warning (PO:12259-12261) | none |

## Surprises

1. **Suspected bug: the `actor_reception_handoff_missing` check never fires for an empty `handoff_dir`.** `os.path.realpath("")` returns the process CWD, which is truthy and a directory (verified: `realpath('')` → `/private/tmp` when run from there). An empty `handoff_dir` (the parameter defaults to `""` at PO:5200 and PO:5675) therefore makes lineage reception read `actors.json`, `meta.json`, the manifest and so on from the **CWD** (PO:5036-5053). The production caller always passes `handoff_dir` (PO:12285), so the impact is limited to tests and direct callers.
2. **Suspected: a legacy single-lane run with a required policy cannot pass reception.**
   - `_actor_lineage_reception_errors` requires `research_contract_manifest.json` to list the lineage file (PO:5042-5046).
   - The code comments say single-lane runs (every v3 run, and legacy with one lane) publish no contract manifest (PO:12090-12096, PO:3481-3482).
   - `_promote_research_contract` is only invoked at PO:3724, PO:11040 and PO:11581 (parallel and recovery paths).
   - A policy pinned `required=True` (legacy engine plus `DEERFLOW_DUAL_TRACK`) with `RESEARCH_PARALLEL_TRACKS=1` would therefore always get `actor_lineage_not_manifested` and fail after the full research spend.
   - Tests always call `_promote_research_contract` first (backend/tests/test_pipeline_actor_contract.py:237). Not verified at runtime.
   - [verifier: confirmed from code, and there is a second unmanifested path. With `RESEARCH_GLOBAL_SYNTHESIS` off, a multi-lane run skips the global-synthesis branch (PO:11081-11082, PO:11279) and writes the merged handoff files directly (PO:11776-11792). It never reaches `_promote_research_contract`, so a required-policy run there also fails with `actor_lineage_not_manifested`]
3. **Suspected: lint adoption breaks v1 hash bindings.** For a manifest-owned, non-judge-bound multi-lane report, research lint replaces `report_md` (PO:12133-12136, tested at backend/tests/test_research_round3_parent.py:183-192). `_finalize_research_contract` seals the new bytes, but `actor_intelligence_contract.report_sha256` and `lineage.report_sha256` still bind the producer's pre-lint bytes. Reception would then emit `report_sha256_mismatch` and `actor_lineage_artifact_mismatch:report_sha256` (PO:5424-5427, PO:5134-5143). This only matters if v1 multi-lane runs can be non-judge-bound; unverified. [verifier: the mechanism is confirmed, but exposure is narrower. A manifest at `depth == "deep"` (the default, config.py:1159) must list `research_report_judge.json` (PO:3245-3259). That makes the report judge-bound (PO:3477-3489), so lint stays audit-only. Only non-deep global-synthesis runs without a judge artifact can reach this]
4. **Probability-sum tolerance drift between parser and validator.** `forecast_inputs_from_report_markdown` accepts 2-6 rows whose midpoints sum to [0.9, 1.1] (utils/actors.py:2820-2824). `valid_scenario_distribution`, which `_forecast_inputs_missing` uses, requires |sum − 1| ≤ 0.02 (utils/actors.py:2591). Two consequences:
   - (a) An injected seed summing to, say, 0.95 still counts as "missing", so PREPARE re-parses and re-injects it.
   - (b) For pre-v1 casts, any producer `forecast_inputs` that fails the strict validator is **replaced wholesale** at PO:5781 by `{"scenarios": …, "base_rates": []}`, which silently drops any producer `base_rates` or other keys.
5. **The comment about sealing injected inputs is only half true.** The banner says injected `forecast_inputs` are sealed together with the outer manifest (PO:3902-3903). `_finalize_research_contract` returns None when no manifest exists (PO:3629-3631), so for single-lane runs (all v3 runs) the injection lives **only in memory** and `actors.json` on disk never receives it. The PREPARE re-injection (PO:12885) compensates. By contrast, an applied cast reconcile **does** write `actors.json` directly when no manifest exists (PO:12168-12173). The two post-processors persist asymmetrically.
6. **The ledger regex differs from the producer's.** The consumer requires whitespace after the marker (`ACTOR_INTELLIGENCE_LEDGER_V1\s+`, PO:238). The producer accepts none (`\s*`, deerflow_bridge/deerflow_research.py:13345). A dossier with `ACTOR_INTELLIGENCE_LEDGER_V1{` would pass the producer and fail reception with `dossier_ledger_count:0`. The producer's template emits a newline, so this is latent. [verifier: not merely latent. The ledger is written by the LLM: the "template" is prompt text (deerflow_bridge/deerflow_research.py:13265-13268), and the retry reminder shows a space form (:14313-14319). No deterministic code emits it, so the no-whitespace variant is a real model-output risk. The parsers also differ: the producer parses leniently with `_lenient_json_loads` (deerflow_research.py:13536, def :8902), while reception uses strict `json.loads` (PO:4857). A ledger the producer accepts can therefore fail reception as `dossier_ledger_unparseable`]
7. **Tier type asymmetry.** `actors.json` tiers must be a real `int` (PO:5280-5281). The dossier ledger accepts the string `"1"`/`"2"` through `_actor_explicit_simulation_tier` (PO:3957-3960, PO:4881).
8. **The same condition is reported twice.** A non-unique Track-B thread is reported by `_actor_source_lookup` (`track_b_receipt_thread_unresolvable`, PO:4153-4157) and again by provenance (`actor_dossier_track_b_receipt_thread_unresolvable`, PO:4286-4290). [verifier: the second report appears only when `actor_dossier_coverage.json` is an accountable dict (PO:5151-5158)]
9. **`behavior_ready_family_failures` is hard-coded `[]`** (PO:5008). Because the coverage sidecar must equal it (PO:5163-5168), a producer sidecar that lists failures can never reconcile. The actual failures go to the `errors` list instead (PO:4953-4955).
10. **Positional source aliases `s{n}` / `[s{n}]` count every row in `sources.json`**, including unfetched ones (PO:4158, PO:4174). `[S3]` therefore means "third row", not "third fetched source".
11. **A normalized-excerpt span holds offsets into the normalized text**, not the original source (PO:4125-4133). Downstream highlighters must not treat them as raw offsets.
12. **Dead or unused outputs.** `_load_research_handoff` returns `"resumed": True` and `"exit_code": None` (PO:3885-3886), and `state.options["actor_intelligence_reception"]` is written in three places. Grep finds no consumer of either in `backend/app` or `frontend/src`.
13. **The depth fallback disagrees with config.** The fallback depth `"standard"` (PO:5719) differs from the `Config` default `'deep'` (config.py:1159). It is dead in practice, since `Config` always defines the attribute.
14. **The 400-char report floor is hard-coded** (PO:3869). The neighbouring dossier guard honours `RESEARCH_MIN_REPORT_CHARS` (PO:2820), so setting that knob does not relax the report guard on resume.
15. **About 30 of the slice's 39 top-level functions duplicate producer logic** in `deerflow_bridge/deerflow_research.py` (see Cross-module edges) instead of sharing a module. The docstrings say "mirror the producer exactly" (for example PO:3951, PO:3965, PO:4027, PO:4194, PO:4212, PO:4732, PO:4832), so any one-sided change becomes a reception failure.
16. **The full duplicate detector runs even for sealed v1.** `_reconcile_research_cast` runs the complete `reconcile_cast` (union-find over the actor rows, utils/actors.py:2351-2366) on sealed v1 casts purely as an audit. Its failure blocks the run (PO:12198-12202).
17. **Doc drift.** DRF_ARCHITECTURE.md:423 cites `utils.actors.reconcile_cast` at `:6607-6635`, but the function is now at utils/actors.py:2333, and the doc does not mention that v1 casts get an audit only. README.md:594 describes reception as running right after promotion. In code it runs after lint, cast reconcile, forecast injection and `_finalize_research_contract` (PO:12079-12286). [verifier: the anchor reading is likely wrong. DRF_ARCHITECTURE.md §5.3 cites pipeline_orchestrator.py line numbers (`_run_parallel_research_tracks` at `pipeline_orchestrator.py:5806-6391`, DRF_ARCHITECTURE.md:404; `_run` at `:6446-7618`, DRF_ARCHITECTURE.md:170). So `:6607-6635` most likely pointed at the old cast-reconcile call block inside `_run`, which is now PO:12156-12203, not at utils/actors.py:2333. Either way the anchor is stale. README.md:594 says reception happens "then" after promotion. That is still true, because promotion precedes reception; the README leaves out the intermediate steps but does not get the order wrong]
18. **A missing `actors.json` is silent for the forecast seed.** `_forecast_inputs_missing(None)` is False (PO:5747-5748), so the caller's "loud" missing-seed warning (PO:12246-12258) is skipped. [verifier: it is not fully silent. When the PREPARE gate is on, which is the default, `world_state_seed_from_actors(None)` returns `{}` and the "world_state 种子为空" warning still fires (PO:12890-12894)]
19. **`RESEARCH_PARALLEL_TRACKS > 3` is silently capped** at the 3 defined angles (PO:11077). The comment at PO:5795 states this, but there is no log.

## Verification

An adversarial verifier re-read the cited code on `main` (checkout on disk, 2026-10-11): PO:3857-5820, the callers at PO:11040-11082, PO:11279, PO:11776-11792, PO:11962-12290, PO:12848-12894 and PO:13381-13392, `backend/app/utils/actors.py`, `backend/app/config.py`, `deerflow_bridge/deerflow_research.py`, `DRF_ARCHITECTURE.md` and `README.md`. Nothing was run. Inline `[verifier: …]` notes above mark each corrected statement.

### Verdict counts

| Group | Checked | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|---|
| Load-bearing key claims | 15 | 10 | 5 | 0 | 0 |
| Surprises (reader's list) | 14 | 13 | 1 | 0 | 0 |
| Extra Walkthrough/Control-flow/Config/Surprise statements found wrong | 8 | 0 | 6 | 2 | 0 |

Another 25 or so Walkthrough and Control-flow statements were spot-checked and found correct, including §6-§13, the §16 steps, §17-§20 and Control flow steps 1-3 and 5-9. Examples:
- the 35 qualifier keys (PO:213-221);
- the 11 unsafe patterns (PO:150-203);
- the 12-field relationship comparison (PO:5550-5561);
- the `_complete_stage` save (PO:9009-9050);
- the generic failure handler (PO:13381-13392);
- the 39 top-level functions in the slice.

### Key claims that are not fully confirmed

1. **The gate is a "no-op pass" for a policy that is absent or `required=False`.** Imprecise. It is not a pure no-op: it writes `state.options["actor_intelligence_reception"]` (PO:5683-5687, PO:5697-5706). A policy that is not a dict also raises "malformed" (PO:5690). A present key whose value is `None` is treated as legacy (PO:5679).
2. **The actor_id and tier error codes.** Imprecise. A missing ID gives `actor_id_missing:<index>` (PO:5268-5269) and a repeat gives `actor_id_duplicate` (PO:5270-5271). Only a present but wrong ID gives `actor_id_not_semantic` (PO:5275-5276). The ID is compared after `.strip()` (PO:5264). The tier rule (exact int 1 or 2, `bool` excluded) is correct (PO:5277-5286).
3. **Lineage "compares in-memory objects with the bytes on disk".** Imprecise:
   - `actors`/`sources` are compared as parsed JSON values, and `report`/`dossier` as decoded text (PO:5050-5061).
   - The `sources` passed in is the dict-filtered `source_rows` (PO:5655).
   - Only the four streamed sha256 checks bind bytes (PO:5134-5143).
4. **`inject_forecast_inputs_from_report`: "otherwise it replaces".** Imprecise. It also returns None without mutating in these cases:
   - non-dict `actors` (`_forecast_inputs_missing` returns False, PO:5747-5748);
   - a parse with no non-empty `scenarios`, such as `{}` (PO:5776-5780).
   `valid_scenario_distribution` also requires 1-6 uniquely named rows, each with a parseable probability, not only the sum check (utils/actors.py:2555-2591).
5. **The PREPARE re-injection happens "only when calendar mode or SIM_DECISION_CHANNEL is on".** Imprecise:
   - It also requires `not _run_already_done` (PO:12879, set at PO:12848).
   - Both gates default ON: `SIM_DECISION_CHANNEL='true'` (config.py:1483) and `SIM_TEMPORAL_MODE='calendar'` (config.py:1067). In practice the pass runs by default.

### Surprise that is not fully confirmed

- **Doc drift (DRF_ARCHITECTURE.md:423, README.md:594).** Imprecise:
  - The DRF_ARCHITECTURE §5.3 anchors are pipeline_orchestrator.py lines (DRF_ARCHITECTURE.md:170, :404). So `:6607-6635` was most likely the old cast-reconcile call block inside `_run`, now PO:12156-12203, not utils/actors.py:2333. It is stale either way.
  - README.md:594 says reception happens "then" after promotion. That remains true; the README leaves out steps but does not misorder them.
- **Refinements to confirmed surprises:**
  - #2 also applies to multi-lane runs with `RESEARCH_GLOBAL_SYNTHESIS` off (see below).
  - #3 is reachable only for non-deep runs, because deep manifests must carry a judge (PO:3245-3259).
  - #10's second report appears only when the coverage sidecar is accountable (PO:5151-5158).

### Extra map statements found wrong

| Map location | Verdict | Correction |
|---|---|---|
| §1 "`actor_dossier.md` … through `_read_json`" | refuted | It is read through `_read_text` (PO:3872). Only actors/sources/timeline use `_read_json` (PO:3882-3884). |
| Config table, `SIM_DECISION_CHANNEL` / calendar "off / depends" | refuted | Both default ON (config.py:1483, config.py:1067). |
| §15 "`lineage_file` must equal the lineage values" | imprecise | It must equal the constant filename (PO:5187, PO:109). Only `lineage_id` comes from the lineage (PO:5185). |
| §17 "inherited by forks/continues (PO:8321-8326)" | imprecise | That anchor is `fork` (PO:8280). `continue_to_full` (PO:8214) keeps the same state. |
| Config table, `state.options["depth"]` default "none" | imprecise | Pinned at admission as `depth or Config.DEERFLOW_RESEARCH_DEPTH` (PO:7955). |
| Control flow 4 "always writes `cast_reconciliation.json`" | imprecise | Skipped if the `actors.json` write in the same `try` raises (PO:12166-12177). |
| §5 "`*.wikipedia.org`" | imprecise | `host.endswith("wikipedia.org")` (PO:3991) also matches bare and look-alike hosts. |
| Surprise 6 "template emits a newline, so this is latent" | imprecise | The ledger is LLM-authored from prompt text (deerflow_research.py:13265-13268, :14313-14319), so the risk is live. |
| Surprise 18 "silent" | imprecise | PREPARE still warns that the world_state seed is empty (PO:12890-12894) when its gate is on, which is the default. |

### Omissions (significant)

1. **Second ledger-parser drift.** The producer parses the ledger leniently with `_lenient_json_loads` (deerflow_bridge/deerflow_research.py:13536; def :8902; also :7747). Reception uses strict `json.loads` (PO:4857). A ledger the producer accepts can fail reception with `dossier_ledger_unparseable`. This adds to the regex drift in Surprise 6.
2. **Second unmanifested research path.** With `RESEARCH_GLOBAL_SYNTHESIS` off, multi-lane runs take the merge branch (PO:11081-11082, PO:11279 else-branch). It writes `actors.json`/`sources.json`/`meta.json` directly (PO:11776-11792) and never calls `_promote_research_contract`. A required-policy run there also fails reception with `actor_lineage_not_manifested` (PO:5042-5046).
3. **Reception validates the finalized `meta.json`, not the producer's.** `research["meta"]` is replaced by `_surface_research_quality` output (PO:12210-12213). `_finalize_research_contract` writes it into the new generation when it differs (PO:3663-3667, PO:3705-3708). Reception then reads `meta.json` for `thread_id`, `actor_intelligence` and `dossier_coverage` (PO:5094-5102, PO:5170-5190). So any change that quality surfacing makes to those keys would break reception.
4. **The canonical claim rebuild also reads `epistemic_status`.** `evidence_type` falls back to `epistemic_status` on the claim and in its qualifiers (PO:4632-4636). The §9 description omits this, and a producer/consumer drift here would break `dimension_claim_canonical_mismatch` parity.
