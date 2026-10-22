# dfr-5 — deerflow_research.py part 5: prior-notes compaction, actor gaps, judge prompt, actor ontology stage, market phrase extraction

Slice: `deerflow_bridge/deerflow_research.py` lines 12319–15063 (branch `main`, on-disk checkout, read 2026-10-11).
All anchors are `path:line` relative to the repo root; unless a path is given, the file is `deerflow_bridge/deerflow_research.py`.

## Purpose & position in the pipeline

This slice holds the Stage-1 (deep research) entry points that the bridge's `main()` calls for both research tracks, plus the start of the Polymarket helper block:

1. **Track A: the research stage.** `run_research_stage` (12331) runs either the single-turn quick/standard protocol, with an optional KIQ-gap top-up, or the multi-pass deep protocol. The deep protocol runs an opening pass, a brief-drift check, an optional KIQ fan-out, a scope phase, three middle phases in parallel, a forecast-implications phase and adaptive gap-closing passes, then synthesizes and runs the report judge. In evidence-only lanes it returns an evidence pack instead of a report. Late passes run on isolated threads and see only a bounded digest of earlier notes (`_prompt_with_compact_prior_notes`, 12319).
2. **Track B: the actor-ontology dossier.** `run_actor_ontology_stage` (14133) runs a tool-using research turn, then a deterministic cast-wide completion turn, then tool-free dossier synthesis. That synthesis must end in a machine ledger (`<!-- ACTOR_INTELLIGENCE_LEDGER_V1 {...} -->`). An AI judge→refine loop follows (10 dimensions, fail-closed), and a deterministic source-bound coverage audit (`actor_dossier_coverage_audit`, 13456) must also pass. The dossier seeds ontology, actors and simulation further down the pipeline.
3. **Prediction-market helpers.** The block runs from 14492 to the end of the slice: pure query derivation (deterministic salient phrases, an LLM path for queries shaped like market titles, a horizon-degradation ladder), an LLM relevance gate, a keyless stdlib HTTP client for Polymarket Gamma and CLOB, price-history parsing and market-row normalization. The orchestration that uses them (`_pm_snapshot` at 15064, `_collect_prediction_markets` at ~15476, `_collect_market_price_history` at 15753) is just outside this slice. [verifier: `_collect_market_price_history` is defined at deerflow_bridge/deerflow_research.py:15752]

The bridge runs as a subprocess in DeerFlow's own venv, spawned by `backend/app/services/pipeline_orchestrator.py`. It reads its knobs from env only; see `_env_flag` at 2229.

## Walkthrough (source order)

### `_prompt_with_compact_prior_notes(prompt, reports)` — 12319–12328
- Calls `compact_prior_research_notes(reports)` (12295, just before the slice). That function strips empty blocks, reads `RESEARCH_PRIOR_NOTES_CONTEXT_CHARS` (default 60000, floor 8000, invalid → 60000; 12307–12311) and returns `build_stratified_outline_context(blocks, cap, max_blocks=min(48, len(blocks)))` (7311). When the joined text is longer than `cap`, that helper gives an **equal slice to each of the first ≤48 blocks**. It is stratified by position, not by recency.
- If the digest is empty, it returns `prompt` unchanged. Otherwise it appends `\n\n=== COMPACT PRIOR WORKING NOTES ===\n<digest>\n=== END COMPACT PRIOR WORKING NOTES ===\n`.
- Pure (no I/O). Used for the sequential fallback phases (12780), the final forecast-implications phase (12895), sequential-mode phases (12955) and adaptive passes (13033). **Not** used for the parallel middle-phase workers (12722), which get only the frozen seed gaps.

### `run_research_stage(client, question, depth, target_language, model_name, thread_id, plog, *, resume_completed=None, out_dir=None, resume_evidence_pack="") -> str` — 12331–13152
Setup (12344–12351):
- `preset = DEPTH_PRESETS[depth]` (12344): an unknown depth raises `KeyError`. `DEPTH_PRESETS["deep"]` has no `recursion_limit` (102–130); only the non-deep branch reads it.
- `_resume_done = set(resume_completed or [])`, `_resume = bool(_resume_done)`, and `_evidence_only = _env_flag("RESEARCH_EVIDENCE_ONLY", False)`.
- `ckpt = ResearchCheckpointer(out_dir, thread_id, depth, question, enabled=_checkpoint_enabled())`, followed by `ckpt.seed_completed(_resume_done)`. The checkpointer (1077–1196) writes `research_checkpoint.json` atomically after each `record_pass`/`update_progress`. It is a no-op when `out_dir is None` or `RESEARCH_CHECKPOINT=false` (911–913). Gaps are capped at 60 on disk (898, 989). [verifier: the class spans 1077–1169. Lines 1171–1196 hold the fetch-ledger and receipt globals. On resume the saved `gaps` are never read back: `seed_completed` seeds only pass ids, so the on-disk gap list is write-only (deerflow_bridge/deerflow_research.py:1077-1169, 1114-1119)]
- `should_run_pass(pass_id, done, resume)` (1066) always returns True when not resuming.

**A. Non-deep branch (`quick` and `standard`)** (12352–12466)
1. If pass `"standard"` should run, it calls `run_streamed_turn(client, build_research_prompt(question, depth, target_language, evidence_only=...), thread_id, preset["recursion_limit"], plog, "research")` (12354–12364). The budget is quick=100 and standard=360 (109, 119). Non-empty text records pass `"standard"`. Quick depth uses the same pass id.
2. If the pass is already done and this is a resume:
   - In evidence-only mode, `text = ""` with a resume log (12371–12376).
   - Otherwise it calls `synthesize_from_thread(...)`, a cheap re-synthesis (12378–12379).
3. **KIQ top-up** runs only when `depth == "standard"`, `RESEARCH_COVERAGE_GATE` is on (default True) and `RESEARCH_COVERAGE_GATE_STANDARD` is on (default True) (12385–12386).
   - Gaps come from `parse_gaps_from_notes(text)` (10584). It reads bullets under any Markdown heading that matches `gaps?\b`, at most 20.
   - The loop runs up to `RESEARCH_COVERAGE_GATE_MAX_ROUNDS` times (default 2; 12390–12393). Each round runs `build_gap_closing_prompt` on the **same main thread** with recursion **240** and label `research:standard-kiq-topup-N` (12408–12412).
   - Stop conditions:
     - empty top-up text (12413);
     - missing gap section, via `notes_have_gap_section` (12416–12422);
     - plateau from `advance_gap_set_from_notes` (10696), or two consecutive rounds with 0 new fetched sources and 0 closed gaps (12432–12445).
   - If any top-up ran and the run is not evidence-only, it re-synthesizes from the thread and adopts the result only if it is longer (12446–12450).
   - It logs a coverage diagnostic. The source count is telemetry only (12451–12457). Any exception becomes a warn and is not fatal (12458–12459).
4. In evidence-only mode it calls `collect_thread_evidence_parts(client, thread_id, plog)` (7115). That reads the latest checkpoint's messages plus worker notes not yet absorbed. Then `render_evidence_pack(parts or [text])` (7141, sha-deduplicated, `<!-- evidence-block:N -->` markers) and `merge_resume_evidence_packs(resume_evidence_pack, current)` (10031) produce the return value (12460–12465). Otherwise it returns `text` (12466).

**B. Deep branch** (12468–13152)
1. `reports` starts from `parse_evidence_pack(resume_evidence_pack)` on resume, else `[]` (12469–12472).
2. **Opening (pass `deep-opening`)** (12475–12496):
   - The budget is `_env_int("DEERFLOW_DEEP_OPENING_RECURSION_LIMIT", 300, minimum=1)`. When spawned by the orchestrator, the env value comes from Config, default 400 (`backend/app/config.py:1556`, `backend/app/services/pipeline_orchestrator.py:2322`).
   - It runs `build_research_prompt` on the main thread with label `research:deep-opening`. Non-empty text is appended to `reports` and the pass is recorded. When the pass is skipped on resume, `opening = ""`.
3. **Brief-drift check (RQ-6)** (12501–12524): enabled by default via `RESEARCH_BRIEF_DRIFT_CHECK` and requires a non-empty opening.
   - `_detect_year_drift(question, opening)` (10789) flags drift when the most frequent year in the notes is not a brief year, appears ≥2 times, and outnumbers the brief-year hits.
   - The correction comes from `build_brief_correction_prompt` (10818). It is injected as a plain thread message via `inject_thread_message` (10337, LangGraph `update_state`, no model call) when `RESEARCH_BRIEF_DRIFT_AS_MESSAGE` (default True) allows it. Otherwise it runs a recursion-8 agent turn `research:brief-drift-correction`.
   - Either way it calls `_flag_research_degradation(...)` (1277). Exceptions become a warn.
4. **Gap threading and the scheduler** (12529–12548):
   - `_gap_threading = RESEARCH_DEEP_GAP_THREADING` (default True), and `accumulated_gaps` is seeded from the opening's gap section.
   - `planned_deep_phase_indices(opening, shared_actor_track=RESEARCH_SHARED_ACTOR_TRACK (default False), convergence_scheduler=RESEARCH_CONVERGENCE_SCHEDULER (default True))` (10667) drops phase 1 (`scope`) when the opening already has a gap heading. It drops `actors-and-incentives` when the shared actor track flag is set. Skipped phases are logged. [verifier: both drops happen only when the convergence scheduler is on. With `RESEARCH_CONVERGENCE_SCHEDULER=false` the helper returns all 5 phases, even when `RESEARCH_SHARED_ACTOR_TRACK` is true (deerflow_bridge/deerflow_research.py:10683-10684)]
5. **Parallel-path eligibility** (12557–12562): `RESEARCH_PARALLEL_PHASES` (default True) and `len(DEEP_RESEARCH_PHASES) >= 3`. There are 5 phases (574–633): scope 330, primary-evidence 540, actors-and-incentives 450, contradictions-and-risks 450, forecast-implications 390. Each is scaled by `_phase_budget` (`RESEARCH_PHASE_BUDGET_MULT`, default 1.0; 636–648).
6. **KIQ fan-out (I-0-4)** (12572–12627):
   - If `RESEARCH_DEEP_FANOUT` is on, there is an opening, `_bridge_fanout_enabled()` is False and harness delegation is active, it logs that the legacy fan-out is suppressed (12573–12579).
   - If `_bridge_fanout_enabled()` (4572: the flag is on and either harness delegation is inactive or `RESEARCH_ALLOW_STACKED_FANOUT` is set) and there is an opening:
     - `width = RESEARCH_FANOUT_WIDTH` (default `"4"` in the bridge; the orchestrator forwards Config's default 8, `pipeline_orchestrator.py:2350`).
     - **Overlap mode** requires `RESEARCH_FANOUT_OVERLAP_SCOPE` (default True), the parallel path, phase 1 scheduled and pass `deep-phase-1` runnable. It calls `start_deep_fanout(...)` (10511), a non-blocking `ThreadPoolExecutor`, and joins later at 12678.
     - Otherwise it calls the blocking `run_deep_fanout(...)` (10564). The merged notes are appended to `reports` and injected as a tagged plain message (`_tag_parallel_evidence`, 1213, prefix `[DRF_PARALLEL_EVIDENCE_V1]` at 1210). If injection fails, it falls back to a recursion-120 absorption turn `research:deep-fanout-merge:fallback` (12615–12625).
     - Any exception becomes a warn.
7. **Parallel path** (12629–12934):
   - **(1) Scope**, phase 1 (12641–12673). It runs on the **main thread** without compact notes, with label `research:deep-1-scope`. Non-empty output is appended, gaps advance (replace semantics by default via `RESEARCH_GAP_SET_REPLACE`) and `deep-phase-1` is recorded with gaps. If the scheduler skipped it, `deep-phase-1` is still recorded (12663–12670). If skipped on resume, it only logs.
   - **Overlap join** (12678–12711): `join_deep_fanout` (10537), then the same inject-or-absorb sequence. A `finally` clears the handle.
   - **(2) Middle phases**, indices 2–4 that are scheduled (12715–12766):
     - Seed gaps are frozen as `_seed_gaps`.
     - Each worker calls `run_scoped_worker(...)` (10488) on its own thread `{thread_id}-fanout-{idx}-{6hex}` (10507) [verifier: the thread name is built at deerflow_bridge/deerflow_research.py:10499, not 10507], with a `build_deep_phase_prompt` prompt, the phase budget and label `research:deep-{i}-{label}:parallel`. Full notes are kept via `_record_worker_notes` (1282).
     - Phases already done on resume go to `_skipped_phases`.
     - The pool is sized `min(len(_to_run), _model_parallel_slots(1))`; `RESEARCH_MODEL_CONCURRENCY_GLOBAL` defaults to 12 (4538–4546). [verifier: the literal call is `_model_parallel_slots(_stream_model_lease_weight())`. That helper always returns 1, so the size is the same (deerflow_bridge/deerflow_research.py:12748-12750, 4533-4535)]
     - A per-worker exception gives `""`. A pool-level exception logs and falls through to the fallbacks.
   - **(3) Sequential fallback** for every middle phase without a non-empty parallel result that was not skipped on resume (12770–12812):
     - It runs on the isolated thread `{thread_id}-fallback-{i}-{8hex}` with the compact prior notes, label `...:fallback`.
     - Non-empty output is injected into the main thread, and the pass is recorded **only if injection succeeded**.
   - **(4) Absorption** of the successful parallel results (12815–12854): they are joined with `---` under `## 阶段并行调查：<label>`, then injected as a plain message, falling back to an absorption turn (recursion 120). `_absorbed_ok` becomes True on either path.
   - **Recording** (12859–12862): parallel phases are recorded only when `_absorbed_ok`, so a crash before absorption leaves them to rerun on resume.
   - **Gap reconciliation** (12868–12881):
     - When absorbed: `reconcile_parallel_gap_sets(accumulated_gaps, non-empty results)` (10719). An old gap closes if any contract-compliant phase drops it, and new gaps are unioned.
     - When not absorbed: union-only `_merge_gaps` (10614), keeping the oldest 20.
   - **(5)** Phase results are appended to `reports` in index order (12884–12887).
   - **(6) Forecast-implications**, phase 5 (12893–12934):
     - It runs on the isolated thread `{thread_id}-forecast-{8hex}` with the compact prior notes.
     - Non-empty output is appended and gaps advance.
     - The output is injected into the main thread, and pass `deep-phase-5` is recorded only if injection succeeded. Otherwise it warns and leaves the pass resumable.
8. **Sequential path**, when `RESEARCH_PARALLEL_PHASES=false` (12935–12988):
   - For each phase 1..5, a phase skipped by the scheduler is recorded and passed over, and a pass already done is passed over.
   - Each phase runs on the isolated thread `{thread_id}-phase-{idx}-{8hex}` **with compact prior notes**, including scope. This differs from the parallel path, where scope uses the main thread.
   - Output is appended, gaps advance, the result is injected, and the pass is recorded only if injection succeeded.
9. **Coverage diagnostic** (12995–13005): logs only. `_coverage_rounds_run` stays at 0 and nothing increments it.
10. **Adaptive gap-closing (SCALE-5)** (13013–13085):
    - Runs when gap threading is on, gaps remain and `RESEARCH_ADAPTIVE_PASSES` (default True) is set.
    - `_max_adaptive_total = RESEARCH_MAX_ADAPTIVE_PASSES` (default 7).
    - `_budget = adaptive_passes_remaining(0, total)` (10771) = `max(0, total - (1 + 5))`, i.e. **1** by default. The fixed count includes phases the scheduler skipped.
    - Each pass runs `build_gap_closing_prompt` with compact prior notes on the isolated thread `{thread_id}-adaptive-{n}-{8hex}`. Recursion is `int(DEERFLOW_ADAPTIVE_PASS_RECURSION_LIMIT or 360)`; that parse is **not** guarded separately, so a typo raises inside the `try` and is logged as "adaptive gap-closing pass skipped".
    - Stop conditions, in order:
      - empty output;
      - no gap section, in which case the output is still appended to `reports`;
      - no fresh gaps, treated as converged;
      - 0 new fetched sources and 0 closed gaps;
      - plateau.
    - The output is **not** injected into the main thread, and adaptive passes are never recorded as completed passes.
11. `ckpt.update_progress(gaps=accumulated_gaps)` (13089).
12. **Deep evidence-only return** (13091–13113):
    - `parts = list(reports)`. If that is empty, it falls back to `collect_thread_evidence_parts`. Otherwise it calls `append_uncheckpointed_worker_notes` (7091) with `_collected_worker_notes()`.
    - The result is `render_evidence_pack(parts)`, merged with the resume pack (render deduplicates by sha256, 7149–7152).
13. **Deep synthesis** (13118–13138):
    - The parts are built the same way, then `synthesize_from_evidence_parts(parts, ai_parts, question, target_language, model_name, plog, depth)` (7998) runs.
    - Non-empty output goes through `run_report_judge_refine(...)` (11886; default on via `RESEARCH_REPORT_JUDGE`, rounds via `RESEARCH_REPORT_JUDGE_MAX_ROUNDS`, default 1) and is returned.
    - An empty synthesis for deep raises `RuntimeError("deep synthesis produced no usable report; ...")` (13140–13144).
    - The "standard synthesis empty → concatenated notes" fallback at 13145–13152 is unreachable (see Surprises).

### Track B prompts — 13155–13341
- **`build_actor_ontology_prompt(question, depth, target_language)`** (13160–13299). This is a pure string builder; `depth` is unused.
  - It starts with `/actor-ontology-research` (deterministic skill activation).
  - Cast size comes from `_actor_cast_max()` (2299; `ACTOR_CAST_MAX`, default 20, 0 = uncapped). With a cap it says "Aim for roughly min(8,cap)–cap … NEVER more than cap"; without a cap, "8–20 (up to ~35)".
  - It inserts `_agentic_delegation_block()` (4588), which is empty unless `--subagents` and `RESEARCH_AGENTIC_SEARCH` are both on.
  - Tooling rules: web_search/web_fetch only, no ls/glob/bash, `read_file` only for harness paths.
  - It mandates 7 sections: frame, cast in salience order with simulation_tier 1–4 triage (media and pollsters demoted to tier 3), the relationship network as `Source —[TYPE, valence, strength]→ Target — basis` with quote-bound provenance per edge, the per-actor roster, evolution/timeline, drivers/indicators/scenarios plus a tiered source list, and the **ACTOR INTELLIGENCE COVERAGE LEDGER**.
  - The ledger section requires a `### Actor: <name>` heading per Tier-1/2 actor and one trailing `<!-- ACTOR_INTELLIGENCE_LEDGER_V1 {json} -->`. The JSON has schema `actor-intelligence/v1` and 17 dimension objects per actor, each `covered` (claims with exact quote, span, receipt_id, 64-hex sha and publication date) or `gap` (`{reason, attempted_queries, receipt_ids, result_ids, attempt_count, exhausted:true}`). "Critical behavior families require two distinct attempts."
  - A language line is appended if `target_language` is set.
- **`build_actor_intelligence_completion_prompt(question, target_language)`** (13302–13341). Also starts with `/actor-ontology-research`. It runs a cast-wide pass over the same thread, listing all `ACTOR_INTELLIGENCE_DIMENSIONS` (2580–2598, 17 dimensions). Each unsupported dimension gets at most two attempts, then becomes a gap object. It asks for coverage notes, not the dossier.

### Ledger regexes and gap audit — 13344–13453
- `_ACTOR_LEDGER_RE` (13344): `<!--\s*ACTOR_INTELLIGENCE_LEDGER_V1\s*(\{.*?\})\s*-->` with DOTALL. `_ACTOR_PROFILE_HEADING_RE` (13348): `^###\s+Actor:\s*(.+?)\s*$`, case-insensitive and multiline. Both are also used outside the slice (7542, 7746).
- `_critical_actor_gap_dimensions()` (13352) returns the union of `ACTOR_BEHAVIOR_READY_FAMILIES` values (2605–2618): 12 dimensions, identity_history, values_worldview, incentives, motivations, capabilities, constraints, current_actions, future_plans, investments_capital_allocation, decision_rights_process_triggers, likely_actions and red_lines. The non-critical ones are operational_preferences, alliances, opponents_competitors, track_record and knowledge_state.
- `_gap_audit_errors(gap, *, critical, known_receipt_ids, known_result_receipts)` (13360–13453) returns a list of error codes:
  - `gap_schema_not_object` if the gap is not a dict.
  - Queries are normalized by `_search_query_from_args` (1621, whitespace-collapsed). `distinct_queries` is the set of NFKC-casefolded queries. `declared_query_hashes` are sha256 of the non-casefolded normalized queries.
  - `gap_reason_missing`, `gap_attempted_queries_empty`, `gap_receipt_or_result_ids_empty`, `gap_receipt_id_unbound` (receipt id not in known track-b receipts) and `gap_result_id_unbound`.
  - `gap_result_query_mismatch`: a resolved result receipt's `query_sha256` is not among the declared query hashes.
  - `gap_attempt_count_inconsistent`: `attempt_count != len(distinct_queries)` or `< 1`. A bool or unparsable value counts as 0.
  - `gap_not_exhausted`: `exhausted is not True`.
  - Critical dimensions additionally need ≥2 distinct queries, `attempt_count ≥ 2`, ≥2 distinct bound query hashes and ≥2 distinct bound result ids. Otherwise it appends **both** `critical_gap_attempts_lt_2` and `critical_gap_query_result_attempts_lt_2`.

### `actor_dossier_coverage_audit(dossier, sources=None, *, require_source_binding=False, required_receipt_purpose="", required_receipt_thread_id="", search_result_receipts=None) -> dict` — 13456–13880
Pure and deterministic; no I/O.
- **Source binding** is on if `sources is not None` or `require_source_binding`. `source_lookup = _canonical_source_lookup(...)` (2780).
  - It keeps only fetched rows (`_source_is_fetched`, 2647) whose receipt scope matches the purpose, lane and thread. For `track-b`, the lane is forced to `track-b` and the thread is inferred if not given.
  - Rows map URL, identity URL, `s<n>`/`[s<n>]`, source_id and unique title to `source_id`.
  - With binding off it uses an empty `_SourceLookup()`.
- **`known_receipt_ids`** (13491–13512): receipt ids from admitted records whose scope purpose, lane and thread match and that have a valid 64-hex `content_sha256`.
- **`canonical_result_receipts`** (13513–13531): empty if the purpose is `track-b` and no thread is admitted. Otherwise the rows that pass `_validated_search_result_receipt` (1653; schema `stage1-search-result-receipt/v1`, lane `track-b`, matching thread, `query_sha256 == sha256(query)`, and so on), sorted by `result_id`.
- **Ledger checks**:
  - Exactly one ledger match, else `ledger_count:N`; the last match is used.
  - `_lenient_json_loads` must yield a dict, else `ledger_unparseable`.
  - `schema_version == "actor-intelligence/v1"`, else `ledger_schema_version`.
  - `actors` must be a non-empty list, else `ledger_actors_empty`.
- **Profile headings** (13546–13570):
  - Names are normalized by `_cast_norm` (2425, NFKC + casefold + whitespace). A duplicate gives `profile_heading_duplicate:<name>`.
  - A profile section runs until the next `#`/`##`/`###` heading. `####` stays inside the section, and ledger text is removed.
  - Substantive length counts word characters only.
- **Per actor row**:
  - It must be a dict with a name, and the name must not be a duplicate.
  - `_actor_explicit_tier` (2327) must be **exactly 1 or 2** (int, or the string "1"/"2"), else `not_tier_1_2`. That error fails the audit, so a Tier-3/4 row anywhere in the ledger makes the dossier unaccountable.
  - For each of the 17 dimensions:
    - A missing cell gives `:missing`.
    - `covered`:
      - Each claim is normalized via `_normalize_intelligence_claim(raw, source_lookup, "", actor_id, dimension)` (3139). An invalid claim gives `claim_i:invalid`.
      - With binding, a claim must carry `source_support`, else `covered_without_track_b_receipt` or `covered_without_quote_bound_source_support`.
      - Any surviving claim makes the dimension grounded. Claims passing `_claim_is_behavior_ready` (4084: source_support, evidence_type and confidence not empty or unknown, and claim_valid_at, horizon and status all set) make it behavior-ready.
      - Legacy unbound mode accepts plain `source_refs`.
      - Otherwise it records `covered_without_track_b_receipt`, `covered_without_fetched_source` or `covered_without_source`.
    - `gap`: `_gap_audit_errors` with binding, otherwise a non-empty `gap` value.
    - Any other status gives `bad_status`.
  - Actor-level errors: `all_dimensions_gap`, `missing_profile_heading` and `profile_not_substantive` (fewer than **80** word characters).
- **Behavior families** (13718–13795):
  - Each of the 5 families needs a behavior-ready claim whose `_sealed_visible_claim_text` (7559: sanitized, `[S\d+]` removed) has ≥24 word characters.
  - The selected claim is the one with the lowest dimension index in the family, ties broken by the lowest `claim_sha256`. It is projected as `{dimension, claim_id, claim_sha256, visible_claim_text, source_ids}`.
  - Failures are `no_substantive_visible_claim` (bound) or `no_grounded_dimension`. In unbound mode a matched family counts without a projection.
- Error `profile_heading_missing_from_ledger` if a heading exists without a ledger row.
- **Return dict keys**: `schema_version`, `accountable` (= no errors), `tier_1_2_actor_count`, `tier_1_2_actor_roster` (cast-normalized) and its sha, ordered `stable_actor_id`s with ordered and multiset shas, `dimension_slots`, `covered_dimension_slots`, `grounded_dimension_slots`, `explicit_gap_slots`, `coverage_ratio`, `grounded_coverage_ratio` (4 dp), `source_binding_required`, `resolved_source_ref_count`, `required_receipt_purpose`, `required_receipt_lane`, `required_receipt_thread_id`, `admitted_source_ids` and sha, `search_result_receipts` and sha, `claim_projection_count`, `claim_projection_multiset_sha256`, `required_behavior_ready_families`, `behavior_ready_family_count`, `behavior_ready_family_slots` (= tier12 × 5), `behavior_ready_family_failures`, `behavior_family_projection` and sha, and `errors[:100]`.

### `_live_actor_dossier_coverage_audit(dossier)` — 13883–13894
The live, source-bound variant. It calls the audit with `export_fetched_sources_for_manifest()` (7936, the run-scoped fetched ledger), `require_source_binding=True`, `required_receipt_purpose="track-b"`, `required_receipt_thread_id=_ACTOR_TRACK_THREAD_ID` (module global at 1195, set by `_set_actor_track_thread_id`, 1251) and `_track_b_search_result_receipts(_ACTOR_TRACK_THREAD_ID)` (1792).

### Actor-dossier judge — 13897–14130
- `_JUDGE_DIMS` (13902) has 10 entries: cast_correctness, salience_ranking, per_actor_depth, relationship_completeness, history_evolution, evidence_grounding, contradiction_handling, ontology_readiness, forward_behavior_coverage and cast_wide_accountability. `_JUDGE_CRITICAL` (13908) has **7** entries; its comment says "four".
- **`build_judge_prompt(question, target_language, source_context=None)`** (13915–13949). The prompt is in Chinese and defaults to skepticism. It lists the 10 dimensions scored 0–5 and the PASS bar: no dimension below 3, the 7 critical dimensions ≥4, and a mean ≥4. It requires per-actor forward-behavior checks and a check of the coverage ledger. It demands JSON only: `{"scores": {...}, "verdict": "PASS|FAIL", "gaps": [...]}`, then `=== 预测问题 ===\n{question}`. `source_context`, when given, adds a calibration line; production never passes it (see Surprises).
- **`_dossier_source_signal(dossier)`** (13952–13969) counts `\bS1..S4\b` mentions (`_VALID_TIERS`, 879) and `https?://` links, returning e.g. `"tier mentions: S1=3, S2=1; ~12 cited links"` or `""`.
- **`_validated_dossier_scores(scorecard)`** (13972–13997) returns None unless:
  - the scorecard is a dict and its verdict is PASS or FAIL;
  - the `scores` keys equal exactly the 10 dimensions (extra or missing keys fail);
  - `_judge_input.truncated` is not True;
  - every score is a non-bool int or float, finite and within [0, 5].
  Otherwise it returns a tuple of floats.
- **`_dossier_judge_input(dossier)`** (14000–14013) runs `sanitize_untrusted_evidence_document` (214), then slices to `_JUDGE_INPUT_CAP = 600000` characters (10845). It returns `(bounded, {source_chars, source_sha256, sanitized_chars, sanitized_sha256, input_chars, input_sha256, truncated})`.
- **`_dossier_judge_input_matches(scorecard, dossier)`** (14016–14024) requires valid scores, then recomputes the input attestation from the given dossier bytes. It requires the scorecard's `_judge_input` to be exactly equal and `truncated is False`.
- **`dossier_passes(scorecard)`** (14027–14045) returns False when:
  - the scores are invalid;
  - the verdict is FAIL;
  - `ACTOR_DOSSIER_JUDGE_STRICT` is on and min < 4;
  - min < 3;
  - any critical dimension < 4.
  Otherwise it returns `mean >= 4.0`.
- **`build_actor_refinement_prompt(question, gaps, depth, target_language)`** (14048–14074); `depth` is unused.
  - It joins **all** gaps, then sanitizes them as one document, so an injection split across array elements is caught.
  - It keeps the first 12 lines, wrapped with `delimit_untrusted_evidence_data("actor judge authored gaps", ..., max_chars=12000)` (362).
  - The question is sanitized (24000 characters) and the language (160 characters).
  - It starts with `/actor-ontology-research` and asks for targeted research only, returned as working notes.
- **`judge_dossier(dossier, question, target_language, model_name, plog) -> dict|None`** (14077–14130):
  - Model: `DEERFLOW_JUDGE_MODEL`, or `model_name` if that is unset, via `deerflow.models.create_chat_model(..., thinking_enabled=False)`.
  - It computes the live coverage audit and the source signal. The system message is `build_judge_prompt(sanitized question, sanitized language)`. The human evidence block, labelled `"actor dossier judge input"` via `_stage1_model_messages` (391), contains `"DETERMINISTIC SOURCE/COVERAGE SIGNALS:\n<signal>; actor-intelligence coverage audit=<full audit JSON>\n\nACTOR DOSSIER:\n<bounded dossier>"`.
  - The call goes through `_invoke_model` (4555, cross-process model lease), and usage is logged as `actor-dossier-judge`.
  - `extract_json_object` (9040) parses the reply. On a dict it attaches `_judge_input` and `input_sha256`, warns if the input was truncated, and returns the dict. Unparsable output or any exception returns None with a warn.

### `run_actor_ontology_stage(client, question, depth, target_language, model_name, thread_id, plog, out_dir=None) -> str` — 14133–14489
1. `_set_actor_track_thread_id(thread_id)` (14145). `main()` passes `thread_id + "-actor"` (17119).
2. Stale sidecars are deleted when `out_dir` is set: `actor_dossier_coverage.json` and `actor_dossier_judge.json`. OSError is ignored (14155–14163).
3. **Research budget** (14164–14174):
   - Deep: `DEERFLOW_TRACKB_RECURSION_LIMIT`, defaulting to `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT`, defaulting to 300; both are parsed by `_env_int`.
   - Otherwise: `DEPTH_PRESETS.get(depth, standard)["recursion_limit"]`, i.e. quick 100 and standard/unknown 360.
4. **Research turn**: `run_streamed_turn(client, build_actor_ontology_prompt(...), thread_id, research_limit, plog, "actor-ontology")` (14177–14184). Labels starting with `actor-` mark the turn's fetch and search receipts as lane `track-b` (`_turn_receipt_scope`, 1598–1615).
5. **Completion turn** (14189–14214):
   - Budget: `DEERFLOW_ACTOR_COVERAGE_RECURSION_LIMIT`, default `min(research_limit, 180)`, floor 40, invalid values fall back.
   - Label `actor-intelligence-coverage`, same thread. Non-empty text is appended to `research_text`. An exception becomes a warn; the final audit stays authoritative.
6. **`_synthesize()` closure** (14218–14342), tool-free:
   - It loads `client.get_thread(thread_id)`; the embedded client sorts checkpoints by ts ascending (`deer-flow/backend/packages/harness/deerflow/client.py:472–511`), so `reversed()` picks the latest checkpoint with messages.
   - It collects `tool` messages as `[name] text` and `ai` messages as text; human prompts are excluded. It appends the Track-B search-result receipt ledger JSON, then applies `_sanitize_untrusted_evidence_blocks` (322).
   - Guards:
     - If the thread cannot be loaded, has no messages or yields empty context, it returns `research_text`.
     - If the context is shorter than `_synth_min_context_chars()` (`ACTOR_SYNTH_MIN_CONTEXT_CHARS`, default 3000; 813–823), it returns `""` and flags degradation (RES-1, refusing to fabricate).
   - The context is head-truncated to `_synthesis_context_cap(model_name, context)` (689) plus a marker.
   - Model: `create_chat_model(model_name, thinking_enabled=False)`. The system message is the actor-ontology prompt plus "STOP researching. Do NOT call any tools …", and the evidence label is `"actor dossier gathered research"`. Usage is logged as `actor-dossier-synthesis`.
   - **Ledger retry** (14306–14335): if the draft lacks both the literal `ACTOR_INTELLIGENCE_LEDGER_V1` and a regex match, it retries **once** with a FORMAT REMINDER (`actor-dossier-synthesis-retry`). It adopts the retry only if the retry has the ledger; otherwise it keeps the first draft.
   - It returns the dossier if `len(dossier.strip()) >= len(research_text.strip())`, else `research_text`. An exception returns `research_text`.
7. If `dossier = _synthesize()` is empty, it returns `""` without judging (14349–14351).
8. **Judge disabled** (`ACTOR_DOSSIER_JUDGE=false`, 14355–14372): it runs the live coverage audit, writes `actor_dossier_coverage.json` best-effort, and returns the dossier only if accountable, else logs an error and returns `""`.
9. **Latency lever** (`ACTOR_DOSSIER_JUDGE_SKIP_IF_CHARS_GTE`, default 0 = off, 14376–14398): when the dossier is long enough, it skips the judge but still requires coverage accountability, otherwise `""`.
10. **Judge→refine loop** (14399–14436):
    - `max_rounds = ACTOR_DOSSIER_JUDGE_MAX_ROUNDS` (default 2, floor 0).
    - Each round judges and records `judged_dossier_sha`. A None scorecard breaks the loop.
    - It breaks with PASS when `dossier_passes` and `_dossier_judge_input_matches` both hold, and also breaks when there are no gaps.
    - Otherwise it runs a refine turn (`build_actor_refinement_prompt`, budget `research_limit`, label `actor-ontology-refine`) and then `_synthesize()` again. If that comes back empty, it returns `""`. If the refine raises, it warns and breaks.
11. **Final rejudge** (14437–14450): if a scorecard exists but was computed for different bytes than the final dossier, it judges once more.
12. **Final gates** (14451–14489):
    - It runs the live coverage audit, then writes `actor_dossier_judge.json` (only if a scorecard exists) and `actor_dossier_coverage.json` best-effort.
    - If the audit is not accountable, it logs an error and returns `""`.
    - If `dossier_passes` fails or the judge input does not match, it logs an error and returns `""`. This is fail-closed: transport or parse failure, truncation, stale bytes and FAIL all return nothing.
    - Otherwise it returns the dossier.

### Prediction-market constants — 14492–14536
- `PREDICTION_MARKETS_FILENAME = "prediction_markets.json"`, `PREDICTION_MARKET_CANDIDATES_FILENAME = "prediction_market_candidates.jsonl"` and `PRICE_HISTORY_FILENAME = "market_price_history.json"` (14503–14506). The writers are outside the slice (15532/15558/15706, 15369, 15784).
- `_POLYMARKET_BASE_URL = "https://gamma-api.polymarket.com"` and `_CLOB_BASE_URL = "https://clob.polymarket.com"` (14507, 14510). `_POLYMARKET_TRANSIENT = (429, 500, 502, 503, 504)` (14511). `_POLYMARKET_UA` is a Chrome-on-macOS user agent, because Cloudflare blocks `Python-urllib` (14512–14515).
- `_PM_STOPWORDS` (14520–14530): function words plus generic forecasting words (year/years/…, future, likely, impact, effect(s), report, research, question, forecast, prediction, predict, analysis, analyze, scenario(s), outcome(s), cover(s), coverage, key, factor(s), driver(s), overview).
- `_PM_TOKEN_RE = (?:19|20)\d{2}|[A-Za-z][A-Za-z0-9\-]*|[一-鿿]{2,}` (14533). The year alternative has **no** digit boundary.
- `_PM_CLAUSE_SPLIT_RE` (14536): ASCII and CJK punctuation, brackets, quotes, newline, ` - `/` – `/` — ` and bare em/en dashes.

### Pure helpers — 14539–14605
- `_pm_float(v)` (14539): float, or None on TypeError/ValueError/NaN. Infinity passes.
- `_pm_as_list(v)` (14547): a list as-is, a JSON string parsed to a list, or `[]`.
- `_pm_yes_price(outcomes, prices)` (14560): equal-length lists are required; returns the price at the index of the outcome whose name is case-insensitively "yes", else None.
- `_pm_salient_phrases(text, max_words=3)` (14572–14605): runs within clauses.
  - Each CJK token (truncated to 12 characters) is appended to the current run and **immediately flushed** as a phrase, so preceding English tokens join it.
  - A stopword, or a token shorter than 3 characters that is neither upper-case nor digits, flushes the run.
  - A run reaching `max_words` is flushed, and clause ends flush.
  - Output is deduplicated case-insensitively, preserving order.

### Query derivation — 14608–14770
- **`_pm_derive_queries(question, hot_topics=None, actor_names=None, max_queries=12, max_words=5)`** (14608–14646), deterministic.
  - `_add` normalizes whitespace, strips punctuation and truncates to `max_words` words. It skips a candidate if it is a case-insensitive duplicate or `len(out) >= budget`; a candidate rejected only for budget is **not** marked seen.
  - `reserve = min(2, len(actors))` and `primary_budget = max(1, max_queries - reserve)`.
  - Order: the first 6 salient phrases (3 words) and the first 6 hot topics against the primary budget; then the first 6 actors against the full budget; then a backfill of all phrases and all hot topics against the full budget. The result is `out[:max_queries]`.
- **`degrade_market_queries(queries)`** (14649–14687) is the pure PM-HZ ladder.
  - Stage `year_stripped`: queries with `\b(19|20)\d\d\b` removed, minus the originals.
  - Stage `event_level`: the first 3 words of each stage-1 query (or of every year-stripped query when stage 1 is empty), minus the originals and stage 1.
  - `_clean` additionally strips dashes. Empty stages are omitted. The docstring requires callers to treat the relevance gate as a fail-closed precondition; the caller does so at 15650–15653.
- **`build_market_queries_prompt(question, hot_topics, actor_names)`** (14690–14711): hot topics and actors are joined and truncated to 600 characters each. It asks for 10–16 queries shaped like market titles, 2–6 words each, including the year when time-bound, and **only** a JSON array.
- **`_parse_market_queries(raw, max_queries=16, max_words=6)`** (14714–14751).
  - It first tries the first **non-nested** `[...]` (`\[[^\[\]]*\]`) parsed as JSON.
  - Otherwise it falls back line by line, stripping bullets and numbering and skipping lines that start with `[` or `{`.
  - It cleans, truncates to 6 words, deduplicates case-insensitively and caps at 16.
- **`derive_market_queries_llm(question, hot_topics, actor_names, model_name, plog)`** (14754–14770) makes one call to `_bare_synth_invoke(model_name, prompt, plog, "prediction-market-query-derivation")` (6602, tool-free, no thinking) and parses the result. Any exception returns `[]`, and the caller then uses the deterministic path (15430–15439).

### Relevance gate — 14773–14868
- `_pm_min_relevance()` (14773): `PREDICTION_MARKETS_MIN_RELEVANCE`, falling back to `PM_MIN_RELEVANCE`, falling back to 5. Invalid values give 5.0.
- `_parse_relevance_scores(raw, market_ids)` (14784–14813): greedy `\{.*\}|\[.*\]` (DOTALL) parsed as JSON. It accepts a `{id: score}` dict or a list of `{id|market_id, score|relevance}`. Only known ids are kept, with `_pm_float` scores. Parse failure gives `{}`.
- `_apply_relevance_gate(markets, scores, min_relevance)` (14816–14834) copies each row and sets `relevance_score` when the market was scored. It drops scored rows below the floor and **keeps unscored rows**. It sorts by relevance descending (unscored counted as 0), then by volume descending.
- `score_market_relevance(question, markets, model_name, plog)` (14837–14868): one batch bare-model call (`prediction-market-relevance`) listing `- id=<id>: <question[:160]>` and asking for a JSON object of 0–10 integer scores. It logs ok or warn. An exception gives `{}`, meaning "keep all" on the main path. [verifier: "keep all" is true only in `_pm_initial_snapshot`. There, `_apply_relevance_gate` with `{}` drops nothing (15472-15473). In `_collect_prediction_markets` an empty score map keeps every deterministic-refresh row, but it keeps an agent-tool candidate only if the candidate is cited in the report (deerflow_bridge/deerflow_research.py:15589-15610)]

### HTTP transport — 14871–14975
- `_polymarket_backoff(attempt)` (14871): sleeps `min(2.0, 0.5*attempt) + U(0, 0.5)` seconds.
- **`_polymarket_get(path, params, timeout=None, base_url=None)`** (14878–14924):
  - Timeout: `PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS` (default 8, floor 0.5) when not passed.
  - Attempts: `PREDICTION_MARKETS_HTTP_ATTEMPTS` (default 2, clamped to 1..5).
  - The URL is `(base_url or Gamma) + path + "?" + urlencode(params)`, with headers `Accept: application/json` and the user agent above.
  - HTTPError with a transient code is retried after backoff; any other HTTPError breaks immediately.
  - Any other exception (URLError, timeout, JSON decode) is retried after backoff while attempts remain.
  - On exhaustion it raises `RuntimeError("polymarket GET {path} failed: …")` with `.error_class` and `.http_status` attributes, which `_pm_snapshot` aggregates (15138–15146).
- `_pm_parse_price_history(data, days=90)` (14927–14959): reads `data["history"]` or a bare list. It skips points that are not dicts or lack `t`/`p`. When `days > 0` it drops points older than `time.time() - days*86400`. It emits `{t: int, p: round(p, 4)}`; unexpected shapes give `[]`.
- `_pm_fetch_price_history(clob_token_id, interval="1d", days=90, timeout=15.0)` (14962–14975): an empty token gives `[]`. Otherwise it calls `GET {CLOB}/prices-history?market=<token>&interval=<interval>` with an **explicit 15 s timeout**, so the env timeout does not apply. Any exception gives `[]`.

### Market normalization and diversity — 14978–15061
- **`_pm_normalize_market(raw, matched_query, min_volume, event_title="", event_slug="")`** (14978–15044) returns None when:
  - the input is not a dict, or `id` or `question` is missing;
  - `closed` is True or "true";
  - the Yes price is missing or not strictly between 0 and 1;
  - `volume < min_volume`.
  A surviving row has `market_id, exchange="polymarket", question, implied_yes_prob (4 dp), volume, liquidity, event_title (falls back to groupItemTitle), matched_query`. Optional fields:
  - `event_url` and `url` = `https://polymarket.com/event/<slug>`;
  - `end_date`, `one_day_price_change`, `best_bid`, `best_ask`;
  - `outcomes`, and `outcome_prices` (only if every price parses);
  - `clob_token_ids`, and `clob_yes_token_id` taken at the **index of "Yes"** in outcomes, never index 0. [verifier: it takes whatever index "Yes" has. That is often 0, so the accurate wording is "never assumes index 0". The key is omitted when "Yes" is absent or its index is out of range for clob_ids (deerflow_bridge/deerflow_research.py:15040-15043)]
- `_pm_cap_per_event(ranked, max_per_event, max_total)` (15047–15061): at most `max_per_event` rows per `event_title` (falling back to `market_id`), then truncated to `max_total`. `max_per_event ≤ 0` means no per-event cap.

## Control flow

- **Entry from `main()`.** If `_should_run_actor_track(evidence_only=...)` holds, `main()` runs Track A `run_research_stage` and Track B `run_actor_ontology_stage(..., actor_thread_id=thread_id+"-actor", out_dir)` concurrently in a pool of `min(2, _model_parallel_slots(1))` workers (17116–17160). With `RESEARCH_SEQUENTIAL_DUAL_TRACK=1` they run sequentially. Otherwise only `run_research_stage` runs (17246–17257).
- **Deep Track A order:** opening (12477) → drift check (12501) → scheduler (12531) → fan-out (12580: start or blocking) → [parallel: scope (12641) → fan-out join/inject (12678) → parallel middle (12746) → sequential fallbacks (12770) → absorption (12821) → record (12859) → gap reconcile (12868) → final phase on an isolated thread (12893)] or [sequential loop over phases 1..5 on isolated threads (12936)] → coverage diagnostic (12996) → adaptive pass(es) (13013) → `ckpt.update_progress` (13089) → evidence-only return (13091) or synthesis (13126) → `run_report_judge_refine` (13137).
- **Track B order:** set thread global (14145) → delete stale sidecars (14155) → research turn (14177) → completion turn (14198) → `_synthesize` (14344) → [judge off → audit → return] (14355) | [length skip → audit → return] (14380) | [judge loop ×max_rounds → judge, then refine + resynthesize (14407) → final rejudge if bytes changed (14438) → audit + sidecars (14451) → fail-closed gates (14469, 14476)].
- **Market helpers** are called from outside the slice:
  - `_pm_resolve_queries` (15430) tries the LLM path first, then `_pm_derive_queries`.
  - `_pm_initial_snapshot` (15442) calls `_pm_snapshot`, `score_market_relevance` and `_apply_relevance_gate`.
  - `_collect_prediction_markets` (15476–15720) does the refresh plus tool candidates, then `score_market_relevance` (15585). It falls back to `degrade_market_queries` with the fail-closed gate (15632–15666), then `_pm_cap_per_event` (15667).
  - `_collect_market_price_history` (15753) calls `_pm_fetch_price_history` (15778).
  - `_pm_snapshot` (15064) calls `_polymarket_get("/public-search", ...)` (15101) and `_pm_normalize_market` (15167).

## Data & artifacts

| Artifact | Writer (this slice) | Format / key fields |
|---|---|---|
| `<out_dir>/research_checkpoint.json` | `ckpt.record_pass` / `update_progress` (12366, 12491, 12662, 12669, 12806, 12862, 12925, 12944, 12982, 13089) → `write_research_checkpoint` (968) | `{version, thread_id, question_hash, depth, run_id, attempt_id, lane_id, completed_passes[], fetched_source_count, gaps[:60], updated_at, checkpoint_id}`. Pass ids: `standard`, `deep-opening`, `deep-phase-1..5` |
| `<out_dir>/actor_dossier_coverage.json` | 14359, 14385, 14463 (deleted at 14155); `main()` rewrites it after unwrapping the fence (17551–17557) | JSON of the `actor_dossier_coverage_audit` return dict (`accountable`, roster/claim/receipt hashes, `behavior_family_projection`, `errors[:100]`) |
| `<out_dir>/actor_dossier_judge.json` | 14455 (only if a scorecard exists; deleted at 14155) | The judge JSON plus `_judge_input` `{source_chars, source_sha256, sanitized_chars, sanitized_sha256, input_chars, input_sha256, truncated}` plus `input_sha256` |
| `prediction_markets.json`, `prediction_market_candidates.jsonl`, `market_price_history.json` | Names only (14503–14506); writers outside the slice | The market row schema is defined by `_pm_normalize_market` (14998–15043); price history is `{market_id: [{t, p}]}` |

In-memory structures:
- `reports: list[str]` holds the per-pass notes and feeds compaction and synthesis.
- `accumulated_gaps: list[str]` (cap 20) is the KIQ ledger.
- Phase results and success sets.
- The module globals `_FANOUT_WORKER_NOTES` (1208), `_ACTOR_TRACK_THREAD_ID` (1195), `_RESEARCH_FLAGS` (1201) and `_SEARCH_RESULT_RECEIPTS` (1193).

Thread-id patterns:
- `{tid}` main;
- `{tid}-fanout-{i}-{6hex}`;
- `{tid}-fallback-{i}-{8hex}`;
- `{tid}-forecast-{8hex}`;
- `{tid}-phase-{i}-{8hex}`;
- `{tid}-adaptive-{n}-{8hex}`;
- Track B `{tid}-actor`.

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| RESEARCH_PRIOR_NOTES_CONTEXT_CHARS | 60000 (min 8000) | Cap on the compact prior-notes digest | 12307–12311 |
| RESEARCH_EVIDENCE_ONLY | false | Return an evidence pack instead of a report | 12349 |
| RESEARCH_CHECKPOINT | true | Enable `research_checkpoint.json` | 911–913, 12350 |
| RESEARCH_COVERAGE_GATE | true | Standard KIQ top-up and deep coverage diagnostic | 12385, 12996 |
| RESEARCH_COVERAGE_GATE_STANDARD | true | Standard-depth top-up | 12386 |
| RESEARCH_COVERAGE_GATE_MAX_ROUNDS | 2 | Maximum standard top-up rounds | 12390–12393 |
| RESEARCH_MIN_SOURCES | 45 deep / 20 otherwise | Telemetry reference only | 826–841, 12388, 12997 |
| RESEARCH_GAP_SET_REPLACE | true | Replace (vs merge) gap-set semantics | 12427, 12660, 12916, 12973, 13063 |
| DEERFLOW_DEEP_OPENING_RECURSION_LIMIT | 300 (orchestrator Config sends 400) | Opening budget; also Track B deep fallback | 12475, 14168; `backend/app/config.py:1556` |
| RESEARCH_BRIEF_DRIFT_CHECK / RESEARCH_BRIEF_DRIFT_AS_MESSAGE | true / true | Year-drift correction and its message-injection mode | 12501, 12510 |
| RESEARCH_DEEP_GAP_THREADING | true | Carry gaps between deep passes; also gates adaptive passes | 12529, 13013 |
| RESEARCH_SHARED_ACTOR_TRACK | false (orchestrator sets it per call) | Scheduler drops the actors phase | 12533; `pipeline_orchestrator.py:2338–2344` |
| RESEARCH_CONVERGENCE_SCHEDULER | true | Skip scope when the opening has a gap ledger | 12534 |
| RESEARCH_PARALLEL_PHASES | true | Parallel middle phases | 12559 |
| RESEARCH_DEEP_FANOUT / RESEARCH_ALLOW_STACKED_FANOUT | false / false (orchestrator forwards Config true) | Legacy KIQ fan-out | 12573, 4572–4585; `pipeline_orchestrator.py:2348` |
| RESEARCH_FANOUT_WIDTH | 4 (orchestrator forwards 8) | Fan-out width | 12582 |
| RESEARCH_FANOUT_OVERLAP_SCOPE | true | Fan-out overlaps the scope pass | 12584 |
| RESEARCH_PHASE_BUDGET_MULT | 1.0 | Multiplier on phase budgets | 636–648 |
| RESEARCH_MODEL_CONCURRENCY_GLOBAL | 12 | Executor bound for parallel phases | 4538–4546, 12750 |
| RESEARCH_ADAPTIVE_PASSES / RESEARCH_MAX_ADAPTIVE_PASSES | true / 7 | Adaptive gap closing; total-pass ceiling (gives 1 adaptive pass) | 13013–13018 |
| DEERFLOW_ADAPTIVE_PASS_RECURSION_LIMIT | 360 | Adaptive pass budget (unguarded int parse) | 13039 |
| RESEARCH_REPORT_JUDGE (+_MAX_ROUNDS) | true (1) | Deep report judge after synthesis (callee) | 11895–11899, 13137 |
| ACTOR_CAST_MAX | 20 (0 = uncapped) | Dossier cast-size line | 2299–2312, 13174 |
| RESEARCH_AGENTIC_SEARCH / DEER_FLOW_MAX_CONCURRENT_SUBAGENTS | true / 5 | Delegation block in Track B prompts | 4519, 4523–4530, 13201, 13319 |
| DEERFLOW_TRACKB_RECURSION_LIMIT | falls back to opening limit (300) | Track B research and refine budget (deep) | 14166–14172 |
| DEERFLOW_ACTOR_COVERAGE_RECURSION_LIMIT | min(research_limit, 180), floor 40 | Completion-turn budget | 14190–14196 |
| ACTOR_SYNTH_MIN_CONTEXT_CHARS | 3000 (0 = off) | Refuse tool-free fabrication | 813–823, 14267 |
| SYNTHESIS_MAX_CONTEXT_CHARS / SYNTHESIS_CONTEXT_WINDOW_TOKENS / SYNTHESIS_OUTPUT_RESERVE_TOKENS | profile-derived | Dossier synthesis context cap | 689–720, 14272 |
| ACTOR_DOSSIER_JUDGE | true | Judge→refine loop (false = coverage-audit-only gate) | 14355 |
| ACTOR_DOSSIER_JUDGE_SKIP_IF_CHARS_GTE | 0 (off) | Skip the judge for long dossiers | 14377 |
| ACTOR_DOSSIER_JUDGE_MAX_ROUNDS | 2 | Judge/refine rounds | 14402 |
| ACTOR_DOSSIER_JUDGE_STRICT | false | Every dimension must be ≥4 | 14035 |
| DEERFLOW_JUDGE_MODEL | "" (falls back to model_name) | Judge model | 14085 |
| PREDICTION_MARKETS_MIN_RELEVANCE / PM_MIN_RELEVANCE | 5 | Relevance floor | 14773–14781 |
| PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS | 8 (floor 0.5) | Gamma request timeout (not price history) | 14887–14892 |
| PREDICTION_MARKETS_HTTP_ATTEMPTS | 2 (clamped 1..5) | Attempts per GET | 14893–14897 |

## External calls

- **DeerFlow agent turns (tool-using LLM streams)** via `run_streamed_turn` (10190). Labels in this slice:
  - Track A: `research`, `research:standard-kiq-topup-N` (240), `research:deep-opening`, `research:brief-drift-correction` (8), `research:deep-fanout-merge:fallback` (120), `research:deep-{i}-{label}[:parallel|:fallback]`, `research:deep-parallel-phase-merge:fallback` (120) and `research:deep-adaptive-gap-N`.
  - Track B: `actor-ontology`, `actor-intelligence-coverage` and `actor-ontology-refine`.
  - Lines 12354, 12408, 12478, 12515, 12615, 12643, 12697, 12718, 12778, 12839, 12902, 12953, 13031, 14177, 14198, 14425.
- **Thread state writes** (`agent.update_state`, no LLM) via `inject_thread_message` (10337), called at 12511, 12607, 12689, 12798, 12823, 12918 and 12975.
- **Thread reads** via `client.get_thread`: 14220, plus inside `collect_thread_evidence_parts` (7119).
- **Bare LLM calls**:
  - `create_chat_model` plus `_invoke_model` for dossier synthesis (14279, 14292), the ledger retry (14313) and the judge (14086, 14105).
  - `_bare_synth_invoke` for market query derivation (14762) and relevance scoring (14858).
  - Callees: `synthesize_from_thread` (12379, 12448), `synthesize_from_evidence_parts` (13126) and `run_report_judge_refine` (13137).
- **HTTP (stdlib urllib, keyless)**:
  - `GET https://gamma-api.polymarket.com/public-search?...`, path from the caller at 15101.
  - `GET https://clob.polymarket.com/prices-history?market=<token>&interval=<interval>` (14972).
  - Both go through `_polymarket_get` (14906).
- **Filesystem**: atomic writes and unlinks of the sidecars listed above (14161, 14359, 14385, 14455, 14463), plus checkpoint writes through `ResearchCheckpointer`.
- No subprocesses or DB access in this slice.

## Cross-module edges

**Callers into the slice:**
- `run_research_stage`: `main()` (17131, 17246); tests `backend/tests/test_loop010_research_contracts.py`, `test_audit_fixes_research.py`; `backend/scripts/test_deerflow_deep_research.py`.
- `run_actor_ontology_stage`: `main()` (17145); tests `test_actor_intelligence_producer.py`, `test_audit_fixes_research.py`.
- `actor_dossier_coverage_audit`:
  - 4266 (actor extraction admission with a pinned thread and receipts);
  - 7514 (shared dossier manifest admission);
  - 7753 (ledger re-audit);
  - 17297/17303 (evidence-only lane, with or without the Track-B requirement);
  - tests `test_actor_intelligence_producer.py`, `test_stage1_model_boundaries.py`, `test_pipeline_actor_contract.py`.
- `_live_actor_dossier_coverage_audit`: `main()` (17551) after writing `actor_dossier.md`.
- `_dossier_judge_input_matches` and `dossier_passes`: shared dossier admission (7500, 7505).
- `_dossier_source_signal`: report judge (11646).
- `_ACTOR_LEDGER_RE`: 7746. `_ACTOR_PROFILE_HEADING_RE`: 7542.
- Market helpers: `_pm_float` (15239, 15291, 15350, 15606); `_pm_derive_queries` and `derive_market_queries_llm` (15436–15439); `score_market_relevance` and `_apply_relevance_gate` (15472–15473, 15585–15588, 15650–15654); `degrade_market_queries` (15632); `_pm_cap_per_event` (15184, 15667); `_polymarket_get` and `_pm_normalize_market` (15101, 15167); `_pm_fetch_price_history` (15778). Tests: `backend/tests/test_bridge_prediction_markets.py`, `test_wave9_research_quality.py`.

**Calls out (outside the slice):**
- DeerFlow `client.get_thread`, `client._get_runnable_config`, `client._ensure_agent` and `client._agent.update_state` (10337–10355).
- `deerflow.models.create_chat_model`.
- The backend mirror `backend/app/utils/prediction_markets.py`, used as a cross-reference only and not imported.

**Downstream consumers of the artifacts:**
- `pipeline_orchestrator.py` reads `actor_dossier_coverage.json` and `actor_dossier_judge.json` (2872–2915, 5151, 11374, 11413) and merges the market files across tracks (11695–11789).
- `backend/app/api/research.py:413` reads `prediction_markets.json`.
- `backend/app/services/oasis_profile_generator.py:1424` reads it as well.

## Invariants, gates, validation

- **Checkpoint durability.** A deep pass that ran on an isolated thread is recorded as complete only after its notes are injected into the reusable main thread (12797–12812, 12859–12862, 12918–12932, 12975–12988). Adaptive passes are never recorded.
- **Gap ledger contract.** A pass without a gap heading never counts as converged; prior gaps are retained (12416, 13050, `advance_gap_set_from_notes` 10709–10710). An explicitly empty gap section closes the ledger.
- **Convergence guards.** Standard top-ups stop after 2 consecutive no-yield rounds (12436–12445). An adaptive pass stops on no fresh gaps, no yield or a plateau (13071–13083).
- **Source count is telemetry.** It never triggers work (12451–12457, 12999–13005).
- **Deep synthesis must be non-empty.** Otherwise a `RuntimeError` is raised (13140–13144).
- **Track B dossier.** It ships only if:
  - the synthesized context is ≥3000 characters (14267–14271);
  - the coverage audit is accountable (14469–14475);
  - the judge is enabled, its scorecard passes `dossier_passes`, and the scorecard is bound to the exact, untruncated sanitized input (14476–14488).
  The judge-off and length-skip paths still require the coverage audit (14365–14372, 14391–14398).
- **Coverage audit.**
  - Exactly one ledger with the v1 schema.
  - Every ledger row is Tier 1/2.
  - Every one of the 17 dimensions is either covered with quote-bound Track-B receipts or an exhausted gap bound to real search-result receipts. The 12 critical dimensions need ≥2 distinct query/result attempts.
  - Every row has a heading and ≥80 word characters of profile.
  - All 5 behavior families are behavior-ready.
- **Judge score validity.** Exactly the 10 keys, finite values in [0, 5], verdict PASS or FAIL, not truncated (13972–13997).
- **Prompt-injection boundaries.** Judge and refinement inputs are sanitized as whole documents (14054–14066, 14093–14096). Synthesis evidence is sanitized per block (14259). [verifier: `_sanitize_untrusted_evidence_blocks` joins all blocks with hash-derived sentinel lines and sanitizes them as one document. It then splits the result back into blocks, so detection works across block boundaries (deerflow_bridge/deerflow_research.py:322-359)] Evidence goes in delimited human messages separate from the system instructions (`_stage1_model_messages`, 391).
- **Market rows.** Not closed, with 0 < Yes price < 1 and volume ≥ min_volume (14988–14997). The Yes token is taken by name, never by index (15040–15043).

## Failure modes & recovery

- **Brief drift, fan-out, top-ups, adaptive passes and absorption** are additive. Exceptions are logged as `warn` and the stage continues (12458, 12523, 12626, 12708, 12853, 13043).
- **A parallel worker raises or returns empty.** That phase reruns sequentially on an isolated thread (12758–12761, 12770–12795). If the whole pool raises, every phase falls back (12765–12766). [verifier: only phases not already in `_parallel_success` fall back. Results collected before the pool-level exception are kept (deerflow_bridge/deerflow_research.py:12755-12766, 12771)]
- **Injection fails.** It falls back to an absorption agent turn (12615, 12697, 12839). For phase injection there is no fallback; the pass is just left resumable (12808, 12928, 12984).
- **Deep synthesis is empty.** `RuntimeError`; the caller decides.
- **Track B fails at any step.** It returns `""`, and `main()` degrades to single track (docstring at 14143). Specifically:
  - the thread cannot be loaded → research text;
  - the context is too small → `""`;
  - synthesis raises → research text;
  - the judge raises or its output cannot be parsed → None → a final `""` when the judge is enabled;
  - refine raises → break, then the final gates decide.
- **Sidecar writes** are best-effort (`except Exception: pass`; 14363, 14389, 14459, 14467).
- **Market LLM failures** return `[]` or `{}`. On the main path an empty score map keeps all candidates (fail-open); on the degraded ladder, the caller fails closed (15651–15653). [verifier: the fail-open applies only partly on the main `_collect_prediction_markets` path. Refreshed rows are kept, and agent-tool candidates are kept only when cited in the report (deerflow_bridge/deerflow_research.py:15589-15610). Full keep-all applies only to `_pm_initial_snapshot` (15472-15473)]
- **HTTP failures** raise a RuntimeError annotated with the error class and status. The price-history helper swallows it and returns `[]`.

## Surprises

1. **Unreachable fallback (dead code).** Lines 13145–13152 are the "standard synthesis returned empty text; falling back to concatenated pass notes" path. They can only run in the deep branch, because non-deep depths return at 12466. The deep branch raises at 13140–13144 first, so the fallback and its `_flag_research_degradation` never execute.
2. **The judge is fail-closed despite "degrade" comments.**
   - Comments describe judge failure as non-blocking: "judge 失败不阻断，回退发当前稿" (14128) and "transport/parsing failure remains the documented coverage-audit-only degradation path" (14440–14441). The orchestrator says the same: "an absent hash is a safe degraded judge" (`backend/app/services/pipeline_orchestrator.py:2896–2899`).
   - But with `ACTOR_DOSSIER_JUDGE` enabled, a None scorecard makes `dossier_passes(None)` False, so the stage returns `""` (14476–14488).
   - A missing judge sidecar can therefore only come from the judge-off or length-skip paths. This is doc/comment-vs-code drift.
3. **`ACTOR_DOSSIER_JUDGE_MAX_ROUNDS=0` drops every dossier (suspected bug).** With 0 rounds, the loop never judges and `scorecard` stays None. The rejudge is skipped because `scorecard is None` (14438), and the final gate returns `""` (14476). An operator who sets 0 to mean "no refine" loses Track B entirely.
4. **Fenced dossiers may fail the judge binding (suspected).** The judge attestation is computed over the dossier as `run_actor_ontology_stage` returns it (14091, 14442). `main()` then rewrites the file through `unwrap_markdown_fence` (17548–17549, 10097–10114), and the shared-dossier admission recomputes the match over the stripped file bytes (7479, 7500). A dossier wrapped in a ```` ```markdown ```` fence would therefore look "stale" at admission. Whether a fenced dossier can pass the coverage audit first is not verified here. [verifier: the mechanism is confirmed. Admission compares `dossier_bytes.decode().strip()`, while `_dossier_judge_input` hashes the exact judged string (`source_sha256`). Every unfenced return path is already stripped (`_message_text` and `strip_think` both call `.strip()`), so the fence unwrap is the only practical trigger (deerflow_bridge/deerflow_research.py:7479, 14006-14007, 5246, 10097-10114). The ledger and `### Actor:` regexes still match inside a fence, so a fenced dossier can pass the coverage audit (13344-13349)]
5. **`_JUDGE_CRITICAL` comment and docs are stale.** The tuple has 7 dimensions, but the comment says "四个不可妥协维度" (four) (13907–13912). `.env.example:133` says "8 维 AI-judge" while the code has 10 (13902–13906). `.env.example:532` says "4 关键维 >=4" while the code has 7.
6. **The `source_context` parameter of `build_judge_prompt` is unused in production.** `judge_dossier` never passes it (14092–14096); it puts the source signal in the evidence payload instead (14097–14104). Only `backend/tests/test_research_evidence_quality.py:271` exercises it. The `depth` parameters of `build_actor_ontology_prompt` (13160) and `build_actor_refinement_prompt` (14048) are also unused.
7. **The coverage audit rejects any Tier-3/4 ledger row.** Each such row adds `actor_i:not_tier_1_2` (13593–13595), so `accountable` becomes False. The prompt only says "List every Tier-1/2 actor exactly once" (13290). It never says that including a tier-3 source row fails the whole dossier.
8. **The judge payload is uncapped.** The full coverage-audit JSON goes into the judge payload uncapped (14089–14102), including `behavior_family_projection`, receipts and errors. Only the dossier itself is capped at 600K characters. With a large cast, the payload can grow well past the dossier.
9. **The adaptive-pass budget arithmetic is vestigial.** `_coverage_rounds_run` is always 0 (12995). `adaptive_passes_remaining` subtracts all 5 fixed phases even when the scheduler skipped scope or actors (10771–10783), so the default ceiling of 7 always yields exactly 1 adaptive pass.
10. **The adaptive recursion limit has no parse guard.** `int(os.environ.get("DEERFLOW_ADAPTIVE_PASS_RECURSION_LIMIT", "360") or "360")` (13039) is not guarded on its own. A typo raises inside the per-pass `try`, which logs "adaptive gap-closing pass skipped" and breaks; this only silently disables adaptive passes. `RESEARCH_FANOUT_WIDTH` (12582) behaves the same way: a typo means the fan-out is skipped.
11. **Asymmetric thread isolation in deep mode.**
    - In the parallel path, scope runs on the **main** thread without compact notes (12643–12653). In the sequential path, scope runs on an isolated thread **with** compact notes (12950–12962).
    - Parallel middle workers never see compact prior notes (12722–12725).
    - Adaptive-pass notes are never injected into the main thread (13031–13049). On resume they survive only through `reports` and the evidence pack.
12. **Standard and deep evidence-only exports differ.** Standard reads the raw thread checkpoint (12461), while deep deliberately avoids it as noisy (13092–13101).
13. **The bridge and backend market mirrors have drifted, despite the "保持一致" comment at 14517.**
    - The bridge uses `actors[:6]` plus a backfill pass (14640–14645); the backend uses `actors[:3]` and no backfill (`backend/app/utils/prediction_markets.py:724–738`).
    - The year regex differs: bridge `(?:19|20)\d{2}` without digit lookarounds (14533) versus backend `(?<!\d)\d{4}(?!\d)` (`prediction_markets.py:646`).
    - The stopword and blacklist sets differ, and so do the clause splitters (dash handling).
    - The LLM-reply parser differs: the backend accepts dict-element shapes (`prediction_markets.py:788–797`).
14. **The year token can come from longer numbers (suspected, minor).** `_PM_TOKEN_RE` has no boundaries, so digits embedded in longer numbers yield year tokens. For example, in `"120345"` the regex scans to `"2034"`.
15. **The relevance gate leaks unscored markets (suspected).** `_apply_relevance_gate` keeps rows the LLM did not score whenever the score map is non-empty (14823–14829). On the degraded "fail-closed" ladder (15650–15654), a partial score map therefore lets unscored, broadened candidates through, with `horizon_degraded` set.
16. **Prose lines can become queries (suspected, minor).** The fallback in `_parse_market_queries` can turn prose into a query: a reply "Here are the queries:" becomes the query `Here are the queries` (14731–14748). It also drops a JSON array whose strings contain brackets.
17. **Price-history `interval` semantics (suspected; external API, not verifiable offline).** `_pm_fetch_price_history` sends `interval=1d` with no `startTs`/`fidelity` (14970). [verifier: `1d` is only the default. The caller reads `PREDICTION_MARKETS_PRICE_HISTORY_INTERVAL` (default "1d") and `PREDICTION_MARKETS_PRICE_HISTORY_DAYS` (default 90) (deerflow_bridge/deerflow_research.py:15763-15767). The look-back semantics cannot be checked from code] The helper and its caller describe this as "90 天、1d 档", i.e. 90 days at a 1-day granularity (15757). On Polymarket's CLOB `/prices-history` endpoint, however, `interval` is understood to be a look-back window. If so, only about one day of points comes back, and the 90-day client-side crop (14940–14957) never bites.
18. **The price-history timeout ignores the env knob.** `_pm_fetch_price_history` always passes `timeout=15.0` (14962, 14972), so `PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS` does not apply to it.
19. **`.env.example` drift for this slice's knobs.**
    - `PREDICTION_MARKETS_HTTP_TIMEOUT_SECONDS=3 … 默认只试 1 次` (`.env.example:650`) versus code defaults of 8 s and 2 attempts (14889–14897).
    - `RESEARCH_COVERAGE_GATE_STANDARD … 默认关` (`.env.example:533`) versus code default True (12386). The same line also says `RESEARCH_COVERAGE_GATE` applies only to deep, but it also gates the standard top-up (12385).
    - `RESEARCH_FANOUT_WIDTH=8` in `.env.example:373` versus bridge default 4 (12582). The orchestrator forwards 8, so the drift only shows in bridge-standalone runs.
20. **A dead variable.** `_fresh_gaps` at 12423 is computed and never used.
21. **`out_dir / "…"` in the sidecar writes assumes a `Path`** (14360, 14386, 14456, 14464), while the stale deletion wraps with `Path(out_dir)` (14161). Passing a `str` would make the writes fail silently, since they are caught by `except Exception: pass`. `main()` builds `out_dir = Path(args.out_dir).expanduser().resolve()` (16614), so production is safe; only direct or test callers passing a `str` would hit this.

## Verification

Adversarial verification on 2026-10-11, against `main` as checked out on disk. All anchors below are `deerflow_bridge/deerflow_research.py` unless another path is given.

**Verdict counts.** 31 of the reader's load-bearing items were checked: 15 key claims and 16 surprises.
- 27 confirmed.
- 3 imprecise (key claims 12, 13 and 14).
- 1 unverifiable (the price-history `interval` semantics).
- 0 refuted.

Spot checks of 30 further Walkthrough and Control-flow statements found 8 more defects: 1 refuted and 7 imprecise. The 12 inline `[verifier: …]` notes above mark them; some notes add extra detail without marking a defect.

**Non-confirmed key claims, with corrections**
1. **Critical-gap rule (claim 12): imprecise.**
   - A critical-dimension gap needs at least 2 distinct NFKC-casefolded queries.
   - It needs `attempt_count` of at least 2.
   - It needs at least 2 distinct bound result ids.
   - It also needs those bound results to come from **at least 2 distinct query hashes**. Two results from the same query are not enough.
   - Anchor: 13428-13452.
2. **`_polymarket_get` retries (claim 13): imprecise.**
   - `PREDICTION_MARKETS_HTTP_ATTEMPTS` is the **total** number of attempts, i.e. N−1 retries. No backoff follows the last attempt.
   - The env timeout (floor 0.5 s) applies only when the caller passes `timeout=None`. `_pm_fetch_price_history` always passes 15.0.
   - Anchors: 14887-14918, 14962-14972.
3. **`clob_yes_token_id` "never index 0" (claim 14): imprecise.**
   - The value is taken from whatever index "Yes" has, which is commonly 0. The code never *assumes* index 0.
   - The key is omitted when "Yes" is missing or its index is beyond the `clobTokenIds` list.
   - Anchor: 15040-15043.

**Confirmed key claims, with qualifiers worth keeping**
- **Claim 11 (coverage audit).** It holds for the live, source-bound audit. In the legacy unbound mode (`sources=None` and no `require_source_binding`), a `covered` cell passes with plain `source_refs` (13678-13682). Further necessary conditions:
  - no duplicate ledger names or profile headings (13553-13554, 13589-13590);
  - every heading has a ledger row (13797-13798);
  - not every dimension is a gap (13707-13708).
- **Claim 10 (synthesis retry).** The retry fires only when *both* the literal `ACTOR_INTELLIGENCE_LEDGER_V1` and a regex match are absent (14306-14307). The 3000-character floor can be disabled with 0 (813-823).
- **Claim 7 (`dossier_passes`).** It also requires the verdict to be PASS or FAIL and `_judge_input.truncated` not to be True (13977, 13982-13984).

**Unverifiable**
- **Price-history `interval` semantics.** These cannot be settled offline. The code facts are confirmed:
  - `interval` defaults to `1d` via `PREDICTION_MARKETS_PRICE_HISTORY_INTERVAL` (15767);
  - no `startTs` or `fidelity` is sent (14970);
  - the timeout is a fixed 15 s (14962, 14972).

**Defects found in the map body by spot checks**
1. **Scheduler drops: imprecise.** Scope and actor-phase drops both require `RESEARCH_CONVERGENCE_SCHEDULER`. With it off, `RESEARCH_SHARED_ACTOR_TRACK` does not drop the actors phase (10683-10684).
2. **Worker thread-name anchor: imprecise.** The name is built at 10499, not 10507.
3. **Executor size: imprecise (cosmetic).** The literal call is `_model_parallel_slots(_stream_model_lease_weight())`, which equals weight 1 (12748-12750, 4533-4535).
4. **Checkpointer span: imprecise.** The class spans 1077-1169, not 1077-1196.
5. **"Keep all" on the main market path: imprecise** (two places). In `_collect_prediction_markets`, an empty score map keeps refreshed rows. It keeps an agent-tool candidate only if the candidate is cited in the report (15589-15610). True keep-all applies only to `_pm_initial_snapshot` (15472-15473).
6. **"Synthesis evidence is sanitized per block": refuted.** `_sanitize_untrusted_evidence_blocks` sanitizes the joined blocks as **one** document, with sentinel lines between them, and then splits the result (322-359).
7. **"If the whole pool raises, every phase falls back": imprecise.** Phases already in `_parallel_success` keep their results (12755-12766, 12771).
8. **`_collect_market_price_history` anchor: imprecise.** It is at 15752, not 15753.

**Spot checks confirmed** (sample):
- quick and standard budgets 100 and 360 (109, 119);
- phase budgets 330/540/450/450/390 (574-633);
- `_detect_year_drift` rule (10789-10815);
- `inject_thread_message` uses `update_state` with a `HumanMessage` (10337-10358);
- the standard top-up uses recursion 240 on the main thread (12408-12412);
- `record_pass` sites (12366 … 13089);
- the fallback, forecast and adaptive thread-name patterns (12776, 12894, 13027-13030);
- `_absorbed_ok` is set on both the inject and the absorption-turn paths (12823-12852);
- the 7-dimension PASS bar in the judge prompt (13934-13936);
- Track-B budgets (14164-14196);
- DeerFlow `get_thread` sorts by ts ascending (`deer-flow/backend/packages/harness/deerflow/client.py:510`);
- `main()` dual-track dispatch with `thread_id + "-actor"` (17116-17158);
- `_turn_receipt_scope` sets the `track-b` lane for `actor-` labels (1598-1615);
- `_pm_derive_queries` reserve and backfill order (14632-14646);
- `_parse_market_queries` uses the non-nested-array regex (14722);
- `_pm_parse_price_history` crops client-side (14940-14958);
- backend mirror drift: `actors[:3]` (`backend/app/utils/prediction_markets.py:724`) and the year regex (`backend/app/utils/prediction_markets.py:646`).

Extra context for surprise 19: backend `Config.RESEARCH_COVERAGE_GATE_STANDARD` defaults to false (`backend/app/config.py:516`). The orchestrator does not forward it, so the bridge's `True` default governs (12386).

**Omissions (significant behavior the map does not cover)**
1. **Resume does not restore the carried KIQ gap ledger.**
   - The checkpoint's `gaps` field is write-only. `ResearchCheckpointer.seed_completed` seeds only pass ids (1110-1119).
   - `run_research_stage` reseeds `accumulated_gaps` from the opening notes, which are `""` when `deep-opening` is skipped on resume (12493-12496, 12530).
   - A resumed deep run therefore starts gap threading empty. Adaptive gap-closing can be skipped entirely (13013).
   - The first `record_pass` without `gaps=` overwrites the on-disk gap list with `[]` (1149-1159).
2. **Stale PAR-1 comments in the parallel path.** Comments at 12549-12556 and 12814 say that forecast-implications and failed-worker fallbacks run on the **main** thread, and that absorption is capped at 100000. The code runs both on isolated threads (12775-12777, 12894) and injects the merged notes uncapped (12815-12831).
3. **The dossier length heuristic can discard a valid dossier.**
   - `research_text` includes the completion-pass notes (14207-14208).
   - `_synthesize` returns that raw `research_text` whenever the tool-free dossier is shorter (14337-14339).
   - Raw notes normally lack the V1 ledger comment. The judge/refine loop still runs on them, and the final audit then returns `""` (14469-14475).
   - A concise, ledger-bearing dossier can therefore lose to longer raw notes.
4. **Deep fan-out is never checkpoint-recorded.** It is gated on a non-empty opening (12573, 12580). On resume (`opening=""`) it never reruns, and its notes survive only through the main-thread injection or the resume evidence pack.
