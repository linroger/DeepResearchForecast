# dfr-4 — deerflow_research.py part 4: dossier richness, quant rows, scoped workers, gap passes, research judge and patching

Slice owned: `deerflow_bridge/deerflow_research.py` lines 9252-12318 (main branch, on-disk checkout as of 2026-10-11).

Anchor legend: `DR:N` = `deerflow_bridge/deerflow_research.py` line N (the same legend as the sibling `dfr-3.md`). Any other file is written as its full repo-relative path. Everything below was read from source. Statements that are my inference rather than something the code states outright are marked "(inference)". Suspected defects are marked "suspected". Three behaviours were confirmed by running the pure functions in isolation (AST-extracted, no module import, no network): `_quant_value_num('2025-01-15') == 1013.0`, `_detect_year_drift('… by 2030?', '2025 … 2025 … 2024 2025')` returns a drift dict, and how `apply_report_patch` handles a section with no match.

---

## Purpose & position in the pipeline

This slice is the middle-to-late part of the **legacy Stage-1 research bridge**. That bridge runs as a subprocess, which the orchestrator spawns and which drives an embedded DeerFlow client. The slice is not one subsystem. It is eight groups of helpers, and `run_research_stage` (`DR:12331`) and `main()` (`DR:16570`) use them at different points:

1. **Deterministic post-extraction analytics.** These are source-diversity, source-tier mix, dossier richness, the 0-1 `research_quality` score, the named-entity coverage probe, the triangulation (single-origin) audit, numeric reconciliation, quant-row canonical enrichment (`value_num/year/value_kind/region/technology/analyst/metric_family`), the as-of clamp, implausible-quant flags and recency annotation (`DR:9252-9940`). `main()` calls them while it writes `actors.json`/`quantitative.json`/`contested.json`/`sources.json` (`DR:17655-17830`). The v3 linear engine also calls three of them (`deerflow_bridge/linear_research.py:5745-5790`).
2. **Text guards.** These are the LLM-error sentinels, typed control-failure blocks, evidence-pack failure predicates, the resume-pack merge, the degraded-artifact gate, `strip_think` and `unwrap_markdown_fence` (`DR:9943-10116`).
3. **The streaming agent-turn runner.** `run_streamed_turn` (`DR:10190`) is the one function through which every agentic DeerFlow turn of the legacy engine runs. It does tool-call validation and accounting, breaks degenerate loops, breaks on budget denial and salvages partial text. `inject_thread_message` (`DR:10337`) writes into the checkpoint with no model call.
4. **Deep-protocol breadth and convergence.** This group covers KIQ/actor seed parsing and scoped fan-out workers (`DR:10361-10578`), plus the KIQ gap ledger: parsing, replace-or-merge, plateau detection, a scheduler that drops redundant phases, parallel-ledger reconciliation and the adaptive-pass budget (`DR:10581-10783`). It also holds the brief year-drift detector (`DR:10786-10829`).
5. **The research-report AI judge (RQ-3).** It builds a 7-dimension "INSIGHT CONTRACT" prompt and runs the tool-free judge call. It then applies deterministic scorecard normalisation (prose-word length override, scenario-probability conflict gate, global actor-coverage audit). It also holds the strict schema validation, `report_passes`, the adoption and improvement gates, exact-byte judge provenance, persistence to `research_report_judge.json`, and the bounded judge→top-up→re-judge loop (`DR:10832-11990`).
6. **Incremental report patching (WAVE9).** One bare-model call emits `<<<SECTION:…>>>`/`<<<APPEND>>>` patch blocks. These are spliced into the report deterministically, in place of a full multipart re-synthesis (`DR:11993-12210`).
7. **Triangulation top-up (SCALE-5).** This is one dedicated verification pass for the single-origin, load-bearing claims flagged by `audit_triangulation`, followed by patch or re-synthesis (`DR:12213-12292`).
8. **Compact prior-notes digest.** It provides the bounded context for isolated late passes (`DR:12295-12316`).

---

## Walkthrough (source order)

### A. Small numeric/text helpers

- **`_first_number(s)`** (`DR:9252-9262`) returns the first signed or comma-grouped number in `str(s)` as a float, using the regex `-?\d[\d,]*\.?\d*` (`DR:9256`) with commas removed (`DR:9260`). For example, `'52-56'` gives `52.0`. It returns `None` for `None`, for no match, or for a `ValueError`. Its only caller is `reconcile_quantitative` (`DR:9609`).
- **`_norm_text(s)`** (`DR:9265-9267`) lowercases, replaces every character except `\w`, whitespace and `%` with a space, collapses whitespace and strips. Callers are the coverage probe (`DR:9483`, `DR:9509`, `DR:9512`) and quant reconcile (`DR:9603`, `DR:9606`).

### B. R2-RES-12 source-diversity histogram

- **`source_diversity_histogram(sources)`** (`DR:9272-9309`) returns `{by_jurisdiction, by_language, n_total, n_with_jurisdiction, dominant_jurisdiction, dominant_share, single_region_warning}`. A non-list input gives the zeroed dict (`DR:9285-9286`), and non-dict rows are skipped. Jurisdiction keys are lowercased (`DR:9295`). Language comes from `lang` or `language` (`DR:9297`). The dominant entry is the max count; ties go to the first one in insertion order through `max` (`DR:9303`). `single_region_warning = share > 0.7 and total >= 3` (`DR:9308`). The caller is `main()` when `RESEARCH_SOURCE_DIVERSITY` is on (default True), and the result goes to `meta["source_diversity"]` (`DR:17740-17744`).

### C. R2-RES-1 research-quality scorecard

- **`_TIER_WEIGHT`** (`DR:9314`) is `S1=1.0, S2=0.7, S3=0.4, S4=0.0`.
- **`_source_tier_mix(sources)`** (`DR:9317-9329`) is the mean tier weight. An untagged or unknown tier counts as **0.3** (`DR:9326`). It returns `None` for a non-list or for no dict rows, and rounds to 3 places.
- **`_dossier_richness(obj)`** (`DR:9332-9374`) needs `obj["actors"]` to be a non-empty list, otherwise it returns `None`. It computes four equally weighted parts (`DR:9373-9374`):
  - `pct_inc`: the share of actors with a non-empty `incentives` list (`DR:9347-9348`).
  - `pct_world`: among "tier-1/2" actors only, the share whose `worldview` dict has any of `values/beliefs/identity/frame`. An actor counts as tier-1/2 when `influence` ∈ {high, medium} or `simulation_tier` ∈ {1, 2, "1", "2"} (`DR:9349-9356`).
  - `pct_val`: the share of relationships with a non-empty `valence` (`DR:9362-9371`).
  - `edges_per_actor = min(1, (n_rel/n)/2)`. About 2 edges per actor saturates this part (`DR:9372`).
- **`_judge_mean01(scorecard)`** (`DR:9377-9392`) takes the mean of every float-coercible value in `scorecard["scores"]` and divides by 5. It returns `None` when it cannot parse.
- **`compute_research_quality(sources, actors_obj, judge_scorecard=None, grounding=None, quant_penalty=0.0)`** (`DR:9395-9444`):
  - The components are `source_tier_mix`, `dossier_richness`, `judge_mean` and the caller-computed `grounding` (`DR:9406-9411`). Weights are `0.35/0.40/0.25/0.25` (`DR:9412`). Only non-`None` components count, and they are renormalised by the sum of the weights used (`DR:9413-9420`).
  - `score = round(max(0, num/den - min(0.15, max(0, quant_penalty))), 3)`. It is `None` when no component exists (`DR:9421`).
  - **Report-judge FAIL cap.** It applies only if `_validated_report_scores(judge_scorecard)` is a complete schema (`DR:9430-9433`; the `NameError` guard is for a partial import). Then `out["judge_passed"] = report_passes(...)`. If that is false: `score_before_judge_fail_cap` is set, `score = min(0.44, score)` (or `0.44` if score was `None`), `degraded = True`, and `degradation = ["research report judge failed"]` (`DR:9434-9441`). The docstring says the comment intends the cap to sit "below the default 0.45 quality floor" (`DR:9423-9429`).
  - `quant_penalty` is echoed, clamped to 0.15 (`DR:9442-9443`).
  - The docstring (RES-4) explains why grounding was added: the old three components could all be satisfied by fabrication, so a fake run scored 0.889 (`DR:9401-9404`).
  - Callers: `main()` passes the on-disk `research_report_judge.json`, a grounding ratio (halved if the "refused tool-free fabrication" flag exists) and an implausible-quant penalty `0.15*min(1, n_impl/len(quant))` (`DR:17755-17806`). The v3 engine passes `judge_scorecard=None` and `grounding = fetched/len(sources)` (`deerflow_bridge/linear_research.py:5787-5790`).

### D. R2-RES-6 completeness probe (named entities vs. cast)

- **`_NAMED_ENTITY_RE`** (`DR:9449`) matches capitalized token runs, optionally joined by `of/the/for/and/&`. **`_ENTITY_STOPWORDS`** (`DR:9450`) is a small closed set.
- **`_named_entities(text)`** (`DR:9453-9465`) returns unique (case-insensitive) capitalized candidates. It drops stopwords and candidates under 3 characters. A multi-word match that starts with a stopword, such as "Will China", is kept as a whole (inference from `DR:9459`: the stopword test is on the full string).
- **`_CONCEPT_HEAD_STOPWORDS`** (`DR:9471-9478`) and **`_is_abstract_concept`** (`DR:9481-9484`) handle RES-11. If the last normalized token of an entity is an abstract head noun (intelligence, policy, trade, war, ai, …), the entity is treated as a tier-4 concept and never reported missing.
- **`compute_coverage_gaps(obj)`** (`DR:9487-9535`) works in four steps:
  1. It builds a haystack from each actor's `name`, `aliases` and `role` (`DR:9498-9509`).
  2. `_grounded(entity)` returns true when the normalized entity is a substring of the haystack, or when **any** token of the entity longer than 3 characters is a substring (`DR:9511-9518`). This is lenient; see Surprises.
  3. `missing_named_entities` holds up to 20 ungrounded, non-abstract entities from the first 40 found in `central_question` (`DR:9520-9525`).
  4. `orphan_fault_lines` holds up to 20 entries of `situation_brief.fault_lines` where an entity exists but none of them is grounded (`DR:9527-9534`).
  - Caller: `main()` when `RESEARCH_COMPLETENESS_PROBE` is on → `meta["coverage_gaps"]` (`DR:17770-17774`).

### E. R2-RES-10 triangulation / single-origin audit

- **`audit_triangulation(sources, contested_claims)`** (`DR:9540-9584`) returns a list of `{claim, reason, independent_sources}`. Two signals feed it:
  1. A contested claim with `status == "single-origin"` (case-insensitive) gives `reason="status=single-origin"` with `independent_sources: 0` (`DR:9550-9555`).
  2. **This signal applies only if at least one source has a boolean `independent` flag** (`DR:9563-9565`, `DR:9575`). In that case, every `sources[].supports` reference with at most 1 independent supporter is flagged as `single-independent-source` (`DR:9576-9583`). Deduplication is case-insensitive across both signals (`DR:9549`, `DR:9577-9578`).
  - Caller: `main()` when `RESEARCH_TRIANGULATION_AUDIT` is on → `meta["single_origin_loadbearing"]` (`DR:17775-17779`). That list later drives the triangulation top-up (`DR:17840-17848`).

### F. R2-RES-11 numeric reconciliation

- **`reconcile_quantitative(quant_facts)`** (`DR:9589-9648`) returns `(extra_contested, unit_errors)`. It works as follows:
  - Rows are grouped by `(_norm_text(metric), _norm_text(unit))`. Rows without a metric are skipped (`DR:9600-9607`).
  - Per group, it keeps the rows whose `_first_number(value) > 0` and needs at least 2 of them (`DR:9609-9612`).
  - It computes `ratio = max/min`. A ratio below **1.1** means no material disagreement (`DR:9617-9619`).
  - It then synthesizes a contested claim `{claim: metric, positions[{stance: "<value> <unit> (<source>)", sources, tier}], status: "contested", why_they_differ, origin: "quant_reconcile"}` (`DR:9620-9640`).
  - A ratio in **[300, 3000]** also yields a `unit_errors` row `{metric, unit, ratio, values}`, described as a "probable unit-scale (~1000x) error" (`DR:9628`, `DR:9641-9647`).
  - Callers: `main()` (`DR:17709-17716`; it sets `meta["quant_unit_warnings"]`, and the synthesized claims are appended to `contested.json` at `DR:17730`) and `run_extract_only` (`DR:16255-16259`).

### G. SESSION-B quant canonical enrichment (`DR:9651-9855`)

The design comment (`DR:9651-9657`) explains the purpose. The canonical schema fields let `render.py` connect same-family, multi-year series. Evidence fields are only filled in when missing. `metric_family` is the one exception: it is overridden.

- **`_QUANT_REGION_ALIASES`** (`DR:9660-9669`) maps US, China, EU/Europe, India and Global variants to canonical names.
- **`_QUANT_FAMILY_RULES`** (`DR:9674-9711`) is an **ordered** list of `(family, regex)` pairs, and the first match wins. The order is: scenario probability → round-trip efficiency → task success rate → intervention rate → duration → utilization → project lead time → cycle life → curtailment → LCOS → power capex → energy capex → growth rate → market share → success rate → average selling price → BOM cost → installed cost → manufacturing capacity → electricity demand → water use → valuation → annual revenue → net income → order book → cumulative deployment → annual installations → annual shipments. Chinese keywords are included.
- **`_QUANT_ACTUAL_KINDS`** / **`_QUANT_FORECAST_KINDS`** (`DR:9712-9716`) are the label vocabularies for actual and forecast.
- **`_canonical_region(text)`** (`DR:9719-9724`) collapses whitespace and returns the alias mapping by casefold. On a miss it returns the raw string (no title-casing despite the docstring), and it returns `None` for empty input.
- **`_quant_value_num(value)`** (`DR:9727-9754`):
  - A real number passes through, with `NaN` turned into `None` and `bool` excluded (`DR:9733-9734`).
  - Otherwise it strips `, $ € £ ¥` (`DR:9739`).
  - A **range** of the form `num [-–—~|to] num` returns the midpoint (`DR:9741-9747`). Otherwise it returns the first `-?\d+(\.\d+)?` (`DR:9748-9754`).
  - Examples in the docstring: `'>250000'→250000`, `'13-17'→15`, `'~$54B'→54` (`DR:9730`).
- **`_quant_metric_family(metric, definition, unit, series=None)`** (`DR:9757-9764`) casefolds the joined text `"{metric} {series} {definition} {unit}"` and returns the first family whose regex matches, or `None`.
- **`_quant_year_of(row)`** (`DR:9767-9785`) takes the year from structured dates only, in priority order `period_end` → `target_date` → `period.period_end|period.end` → `as_of_date`, each via `_parse_date` (`DR:9226`). It deliberately never reads years out of free text (`DR:9770-9771`).
- **`_quant_value_kind(row)`** (`DR:9788-9803`) returns `"actual"` or `"forecast"`. It checks these sources in order:
  1. The keys `value_kind, value_type, observation_type, fact_type, status`, each normalized to `[a-z]` only and looked up in the vocabularies (`DR:9790-9795`).
  2. A boolean `is_projection` (`DR:9796-9798`).
  3. A text regex over metric + definition, which can only return `"forecast"` or `None` (`DR:9799-9803`).
- **`enrich_quantitative_rows(rows)`** (`DR:9806-9855`) works **in place** and returns the same list. A non-list input returns `[]` (`DR:9817-9818`). For each dict row it fills, only when the field is currently `None`: `value_num`, `year`, `value_kind`, `region` (from `geography`), `technology` (from `technology_route`, unless that is "all routes/all/n/a/none") and `analyst` (from `source`) (`DR:9825-9848`). **`metric_family` is always recomputed** when a rule matches. A conflicting claimed value is kept in `metric_family_claimed` via `setdefault` (`DR:9849-9854`).
  - Callers: `main()` (`DR:17700-17705`; `RESEARCH_QUANT_ENRICH` default True), `run_extract_only` (`DR:16249-16253`) and the v3 engine (`deerflow_bridge/linear_research.py:5745`).

### H. R2-RES-4 recency, as-of clamp, implausible quant

- **`_clamp_asof_reference(extracted, run_date)`** (`DR:9860-9877`) handles RES-3. MiniMax reports its training cutoff as the research cutoff, so an extracted as-of date older than `run_date - RESEARCH_ASOF_MAX_LAG_DAYS` (default **45**; an invalid value falls back to 45, `DR:9871-9874`) is replaced by `run_date`. In that case it returns `(run_date, {"extracted", "used"})`. Otherwise it returns `(extracted, None)`, and `(run_date, None)` when nothing was extracted (`DR:9869-9870`). Caller: `main()` with `_dt.date.today()` → `meta["as_of_date_overridden"]` (`DR:17655-17659`).
- **`flag_implausible_quant(facts, ref_date)`** (`DR:9880-9910`) returns a list of human-readable strings. It flags two cases:
  - **Future-dated "actuals"**: `as_of_date > ref_date`, unless the metric/definition/unit text contains a projection word (`projection, forecast, estimate, target, outlook, guidance, "by 20", 预测, 预计, 目标, 展望` …, `DR:9895-9900`).
  - **Extreme growth**: `abs(value) > 150` where the unit contains `%`/`yoy`/`growth` or the metric contains `增长`/`同比` (`DR:9901-9909`). A value is parsed by stripping `%` and `,`, so a range value cannot be parsed and is skipped.
  - Caller: `main()` → `meta["quant_implausible"]` (`DR:17720-17723`). The count then feeds the quality `quant_penalty` (`DR:17798-17800`).
- **`annotate_recency_rows(rows, ref_date, stale_days, date_key="date")`** (`DR:9913-9940`) works in place. It reads the date from `row[date_key] or row["as_of_date"] or row["date"]` (`DR:9924`). An undated row only increments `undated` (`DR:9925-9927`). A dated row gets `staleness_days` and `is_stale = age > stale_days` (`DR:9928-9931`). The histogram buckets are `fresh_le_90` (age ≤90, **including negative/future ages**), `recent_le_365` and `stale_gt_365`, plus `n_stale` (`DR:9932-9939`). Callers: `main()` for quant (`date_key="as_of_date"`) and sources (`date_key="date"`), gated by `RESEARCH_RECENCY_WEIGHTING` (default True), with `stale_days = RESEARCH_STALE_DAYS` (default 365) (`DR:17660-17664`, `DR:17718-17719`, `DR:17736-17738`). The v3 engine annotates both quant and timeline (`deerflow_bridge/linear_research.py:5750-5751`).

### I. LLM-error / control-failure detection

- **`_LLM_ERROR_SENTINELS`** (`DR:9953-9960`): `"The configured LLM provider"` (DeerFlow `LLMErrorHandlingMiddleware` fallback), `"LLM request failed"`, `"unprocessable_entity"`, `"new_sensitive"` (MiniMax 1026), `"Error code: 4"` and `"Error code: 5"`. The orchestrator keeps a byte-identical copy, `_LLM_ERROR_MARKERS` (`backend/app/services/pipeline_orchestrator.py:2748-2754`).
- **`looks_like_llm_error(text)`** (`DR:9963-9972`) returns True for empty text. Otherwise it returns `len < 400 and any(sentinel)`. Because both conditions must hold, a real long report cannot be misclassified. Callers include `main()`, which fails with exit 2 (`DR:17434-17439`), the refine/triangulation adoption checks (`DR:11946`, `DR:12285`), the patch validator (`DR:12200`) and `_is_degraded_artifact` (`DR:10057`).
- **`evidence_pack_is_provider_error_only(text)`** (`DR:9975-9987`) is true when the pack has no blocks or every block contains a sentinel **anywhere**. It has no production caller; only `backend/tests/test_loop010_global_synthesis.py:233` uses it.
- **`_is_control_failure_block(text)`** (`DR:9990-10022`) returns True when any of these hold:
  - The block is empty.
  - The first line starts with `SUBAGENT_OUTCOME: BLOCKED`.
  - The block is a JSON object whose `error` ∈ {`research_budget_exhausted`, `llm_provider_unavailable`}.
  - **Any sentinel substring appears anywhere in the block (no length gate)**.
  - Lowercased, the block contains `research_budget_exhausted` and one of 8 "blocked/halted/cannot fetch" phrases.

  Callers: `evidence_pack_is_control_failure_only`, `merge_resume_evidence_packs`, the shared-actor-dossier admission (`DR:7480-7482`) and the evidence-lane dossier usability check (`DR:17314-17318`). The orchestrator mirrors it as `_control_failure_block` (`backend/app/services/pipeline_orchestrator.py:2761-2791`).
- **`evidence_pack_is_control_failure_only(text)`** (`DR:10025-10028`) is true when `parse_evidence_pack` (`DR:7171`) yields no parts or all parts are control failures. Callers: resume acceptance of a prior `evidence_pack.md` (`DR:16767-16770`) and evidence-lane failure (exit 2) when no sources exist (`DR:17275-17291`). The orchestrator mirrors it as `_evidence_pack_is_control_failure_only` (`backend/app/services/pipeline_orchestrator.py:2794-2811`).
- **`merge_resume_evidence_packs(previous, current)`** (`DR:10031-10044`) concatenates the parsed blocks of both packs, drops control-failure blocks and re-renders with `render_evidence_pack` (`DR:7141`), which de-duplicates by sha256. Callers: standard evidence-only return (`DR:12464`), deep evidence-only return (`DR:13105`) and `main()` evidence-lane (`DR:17265-17267`).
- **`_is_degraded_artifact(text, min_chars)`** (`DR:10047-10057`) handles RES-8. Empty text returns **False**, because callers handle emptiness separately. Otherwise it returns `looks_like_llm_error(t) or len(t) < max(0, min_chars)`. Callers: `DR:7480` (min 400), `DR:17316` (min 400) and `DR:17541` (min `_min_report`, which is 2000 deep / 400 other by default, `DR:17414`).

### J. Output cleaning

- **`_THINK_RE`, `_DANGLING_THINK_RE`, `_THINK_CLOSE_RE`, `_HARNESS_MARKER_RE`** (`DR:10060-10067`). The last one removes whole lines starting with `[FORCED STOP]` or `[LOOP DETECTED]`, which DeerFlow loop-detection middleware injects.
- **`strip_think(text)`** (`DR:10070-10091`) runs four steps in order:
  1. Removes paired `<think>…</think>`.
  2. If any orphan `</think>` remains, drops everything up to and including the **last** one (for templates that inject the opening tag).
  3. Drops a dangling unclosed `<think>…EOF`.
  4. Strips harness marker lines, then `.strip()`.

  Callers: `_message_text` (`DR:5246`), the end of `run_streamed_turn` (`DR:10332`), `parse_report_patch` (`DR:12031`) and the incremental patch (`DR:12185`).
- **`unwrap_markdown_fence(text)`** (`DR:10094-10116`) removes the outer fence only when all of these hold:
  - The text starts with ```` ``` ```` / ```` ```markdown ```` / ```` ```md ````.
  - The last line is exactly ```` ``` ````.
  - The inner fence-line count is even.

  When it unwraps, it returns `inner.strip("\n") + "\n"`. Otherwise it returns the original (unstripped) text. Callers: `_finalize_and_judge_report` (`DR:11737`) and `main()` for the report and the dossier (`DR:17343`, `DR:17441`, `DR:17549`).

### K. Streaming agent turn (WAVE9 degenerate-loop / budget-denial breakers)

- **`_DegenerateToolLoopError`** (`DR:10124`) and **`_ResearchToolBudgetExhausted`** (`DR:10128`) are `RuntimeError` subclasses that act as internal control-flow signals.
- **`_DEGEN_CORRECTIVE_MESSAGE`** (`DR:10135-10140`) is a fixed one-line correction about malformed `web_search`/`web_fetch` arguments.
- **`_degen_loop_thresholds()`** (`DR:10143-10158`) returns `(RESEARCH_DEGENERATE_TOOL_CORRECT_AT=8, RESEARCH_DEGENERATE_TOOL_BREAK_AT=16)`. Blank or invalid values fall back to the defaults, and ≤0 disables the action (`DR:10147-10149`).
- **`_budget_denial_break_at()`** (`DR:10161-10167`) reads `RESEARCH_BUDGET_DENIAL_BREAK_AT` (default **3**).
- **`_stream_end_usage_line(usage)`** (`DR:10170-10187`) emits `tokens in=.. out=.. total=..`, byte-compatible with the orchestrator's `_USAGE_RE`. It appends the cache/reasoning suffix (`_usage_cache_details`, `DR:6260`; `_usage_detail_suffix`, `DR:6322`) **only** when some detail is non-`None`, so no fake `cached=0` is printed.
- **`run_streamed_turn(client, message, thread_id, recursion_limit, plog, label)`** (`DR:10190-10334`):
  - **State** (`DR:10200-10215`):
    - `chunks{msg_id: [deltas]}` and `last_id`.
    - The `tool_calls` counter.
    - The v2 per-turn pending fetch/search tables (`_fetch_accounting_v2()` = `RESEARCH_FETCH_ACCOUNTING_V2` default True, `DR:1594`).
    - The thresholds, `_consec_rejected` and `_consec_budget_denials`.
    - The corrective flags (`_corrective_pending`, and `_corrective_sent`, which ensures the correction is sent at most once).
  - **Loop** (`DR:10219-10311`): a `while True` loop over `_leased_client_stream(client, msg, thread_id=…, recursion_limit=…)` (`DR:4561`, which yields `client.stream(...)` without holding a provider lease around the iterator). For each event:
    - `messages-tuple`/`ai` with `tool_calls`: increments `tool_calls` for **every** call, including rejected ones (`DR:10232`). It validates and repairs the arguments with `_validate_tool_args` (`DR:1470`), logs `[tool]`, and then handles three cases:
      - On **reject**: logs a warning and increments `_consec_rejected`. If `≥ break_at`, it raises `_DegenerateToolLoopError` (`DR:10242-10245`). If `≥ correct_at` and no correction has been sent yet, it sets `_corrective_pending` (`DR:10246-10247`), then continues to the next call (no accounting) (`DR:10239-10248`).
      - On **accept**: resets `_consec_rejected` (`DR:10249`).
      - In v2 mode it records `_pending_record_fetch` and `_pending_record_search` with `call_id` and a receipt scope from `_turn_receipt_scope(label, thread_id)` (`DR:10250-10265`). Otherwise it calls the legacy global `_record_fetched_url` (`DR:10267`).
    - `ai` content deltas are appended to `chunks[id]`, and `last_id` is updated (`DR:10268-10272`).
    - `tool` result: logs `[result]` (truncated) and parses `_structured_fetch_control_result` (`DR:1545`). An `error == "research_budget_exhausted"` increments `_consec_budget_denials`; reaching `RESEARCH_BUDGET_DENIAL_BREAK_AT` raises `_ResearchToolBudgetExhausted` (`DR:10275-10285`). **Any other tool result resets the counter** (`DR:10286-10287`). The result is then paired to pending rows by `tool_call_id` in v2 (`DR:10288-10295`), or legacy `_mark_fetch_result` LIFO (`DR:10297`).
    - `custom`: logged as JSON (`DR:10298-10299`).
    - `end`: logs the `[usage]` line (`DR:10300-10302`).
    - If `_corrective_pending` is set at the top of the next event, it `break`s the stream (`DR:10223-10224`). After the loop it sends `_DEGEN_CORRECTIVE_MESSAGE` as a new stream segment on the **same thread**, with `recursion_limit = max(32, recursion_limit - tool_calls)`. It flags a degradation and continues (`DR:10303-10310`).
  - **Salvage** (`DR:10312-10327`): **every `Exception` is caught**. The "kind" is classified as research tool budget exhausted, degenerate tool-loop break, `GraphRecursionError` → "recursion-limit/budget exhausted", or the class name. It logs `salvaging N chars` and calls `_flag_research_degradation(...)` (`DR:1277`; appends to `_RESEARCH_FLAGS`).
  - **Post** (`DR:10329-10334`): in v2 it runs `_retry_dead_fetches` (one programmatic retry of dead fetches, `DR:1879`) and `_merge_pending_fetches` (merge under the lock, `DR:1891`). It returns `strip_think("".join(chunks[last_id]))`, i.e. **only the last AI message's text**.
- **`inject_thread_message(client, thread_id, text)`** (`DR:10337-10358`) appends a `HumanMessage` to the thread checkpoint through `client._get_runnable_config`, `client._ensure_agent` and `client._agent.update_state({"configurable": {"thread_id"}}, {"messages": [HumanMessage]})`. These are private DeerFlow client internals. It makes zero model/tool calls and returns False on any exception or a missing handle, after which callers fall back to an agent turn.

### L. EXECPLAN2 I-0-4 per-KIQ/per-actor fan-out (`DR:10361-10578`)

- The regexes `_FANOUT_PRIORITY_RE` (actor/stakeholder/KIQ/key question + Chinese equivalents), `_FANOUT_BULLET_RE` (`- * +` or `1.`/`1)` bullets) and `_FANOUT_BOLD_RE` are at `DR:10371-10377`.
- **`_clean_seed(text)`** (`DR:10380-10388`) strips leading `**`, unbolds, and cuts at the first of `： : — - — – （ (`. It then strips `*#\`"'。.`.
- **`extract_kiqs_from_opening(opening_text, width=4)`** (`DR:10391-10428`) is pure. A heading toggles `in_priority` when its text matches the priority regex. Bullets anywhere are candidates, but bold-only lines count only inside priority sections. Candidates must be 2-80 characters. Priority items come first, then the others, de-duplicated case-insensitively and capped at `width`. It returns `[]` when `width<1` or the text is empty.
- **`build_scoped_worker_prompt(question, kiq, target_language)`** (`DR:10431-10454`) is a `/deep-research` slash prompt for a "scoped sub-investigator". Its stopping rule is "B2-or-better and opposing case checked, or S1/S2 classes exhausted; two angles with no evidence upgrade end the search". It also carries a WAVE9 **notes-first** instruction, because a hard step budget truncates unwritten findings (`DR:10446-10453`).
- **`build_fanout_absorption_prompt(question, fanout_notes, target_language, prior_gaps=None)`** (`DR:10457-10485`):
  - The notes are capped at **100000** characters (PAR-1 raised it from 24000, `DR:10463-10467`).
  - Up to 20 prior gaps form a "PRIOR OPEN KIQ LEDGER".
  - The prompt asks the agent to internalize the notes, not re-search, and to end with the complete `## Gaps to carry into the next pass` ledger.
  - It is used only as the **fallback** when `inject_thread_message` fails (`DR:12615-12625`, `DR:12697-12707`, `DR:12839-12851`).
- **`run_scoped_worker(client, kiq, question, parent_thread_id, depth, target_language, model_name, plog, index, recursion_limit=None, prompt=None, label=None)`** (`DR:10488-10508`) creates the thread `"{parent}-fanout-{index}-{uuid6}"` (`DR:10500`). It runs `run_streamed_turn` with the given prompt (default: the scoped-worker prompt), a budget of `recursion_limit` or `_fanout_worker_budget()` (`RESEARCH_FANOUT_WORKER_BUDGET`, default 260, `DR:1297-1309`), and the label `research:fanout:{kiq[:24]}`. `depth` and `model_name` are unused. The deep path reuses it for parallel middle phases with an explicit prompt, budget and label (`DR:12717-12730`).
- **`start_deep_fanout(...)`** (`DR:10511-10534`) is non-blocking. It parses seeds and returns `None` if there are none (logging a warning). Otherwise it starts `ThreadPoolExecutor(max_workers=min(width, len(seeds), _model_parallel_slots(1)))` [verifier: the literal argument is `_model_parallel_slots(_stream_model_lease_weight())` (`DR:10527-10528`); that weight function returns 1 today (`DR:4533-4535`), so the bound is the same in effect] (`_model_parallel_slots` = `RESEARCH_MODEL_CONCURRENCY_GLOBAL`, default 12, `DR:4538-4545`), submits one `run_scoped_worker` per seed, and returns `(executor, {future: seed})`.
- **`join_deep_fanout(handle, plog)`** (`DR:10537-10561`) consumes `as_completed`. Each non-empty note becomes `## 子调查：{seed}` and is also recorded through `_record_worker_notes` (`DR:1282`; a run-scoped list folded into synthesis later). A failure in one worker is logged and skipped. A `finally` calls `ex.shutdown(wait=False)`. It returns `"# 并行子调查汇总（per-KIQ/per-actor fan-out）\n\n" + "\n\n---\n\n".join(notes)` or `''`.
- **`run_deep_fanout(...)`** (`DR:10564-10578`) is a blocking start+join.

### M. KIQ gap ledger and convergence (`DR:10581-10783`)

- **`_GAP_HEADING_RE = r"gaps?\b"`** (`DR:10581`), case-insensitive with **no leading `\b`**. Any heading containing a word that ends in "gap"/"gaps" matches, e.g. "Data gaps".
- **`parse_gaps_from_notes(notes, limit=20)`** (`DR:10584-10611`) treats every markdown heading as a toggle for `in_gaps`. While in a gaps section, it collects bullet items (`_FANOUT_BULLET_RE`), stripped of `*#\`"'。.` and 3-200 characters long, up to `limit`.
- **`_merge_gaps(accumulated, new_gaps, cap=20)`** (`DR:10614-10627`) appends new gaps case-insensitively **into the passed list (mutating it)** and returns `accumulated[:cap]`, keeping the **oldest**. SCALE-2 changed it from 12 / keep-newest (`DR:10617-10621`).
- **`_normalize_gap(gap)`** (`DR:10630-10633`) collapses whitespace, lowercases and strips trailing `。.;；,，`.
- **`advance_gap_set(previous, fresh, *, replace=True, cap=20)`** (`DR:10636-10655`) does three things:
  - `fresh_list` = the non-blank fresh items capped at `max(1, cap)`.
  - `plateau` = the fresh normalized set is non-empty and equals the previous normalized set (`DR:10649-10652`).
  - `replace` → it returns `fresh_list`. Otherwise it returns `_merge_gaps(previous, fresh)` (the `RESEARCH_GAP_SET_REPLACE=false` legacy path).

  WAVE9 rationale: merge-only ledgers could never converge, as seen in a run that took 44 minutes and about 15.6M prompt tokens (`DR:10640-10642`).
- **`notes_have_gap_section(notes)`** (`DR:10658-10664`) is true if any markdown heading matches `_GAP_HEADING_RE`.
- **`planned_deep_phase_indices(opening_notes, *, shared_actor_track, convergence_scheduler=True)`** (`DR:10667-10693`) starts from `[1..len(DEEP_RESEARCH_PHASES)]`, which is 5 phases: scope, primary-evidence, actors-and-incentives, contradictions-and-risks, forecast-implications (`DR:574-633`). If the scheduler is off, it returns all of them. Otherwise it drops phase 1 (scope) when the opening already has a gap section, and drops the phase labelled `actors-and-incentives` when `shared_actor_track` is set.
- **`advance_gap_set_from_notes(previous, notes, *, replace=True, cap=20)`** (`DR:10696-10716`): with **no gap heading**, it returns `(previous[:cap], False)`, i.e. a contract violation keeps the ledger. With a heading, it advances using the parsed bullets. An **explicitly empty** section closes the ledger in replace mode.
- **`reconcile_parallel_gap_sets(previous, note_sets, *, cap=20)`** (`DR:10719-10768`) reconciles independent workers that all started from the same carried ledger:
  - It parses each note set that has a gap section; a note set without one is ignored.
  - If none has a section, it returns `(previous[:cap], False)`.
  - A carried gap stays open only if **every** compliant worker still lists it (intersection, `DR:10748-10750`), in the original order (`DR:10752-10753`).
  - Newly discovered gaps (not in previous) are unioned in, up to `cap` (`DR:10754-10765`).
  - `plateau` is true when the merged normalized set equals the previous one and is non-empty.
- **`adaptive_passes_remaining(coverage_rounds_run, max_adaptive_total)`** (`DR:10771-10783`) computes `max(0, total - (1 + len(DEEP_RESEARCH_PHASES) + coverage_rounds_run))`. Invalid input gives 0. With the default `RESEARCH_MAX_ADAPTIVE_PASSES=7` and 5 phases, at most **1** adaptive pass runs (`DR:13015-13018`).

### N. RQ-6 brief year drift

- **`_YEAR_RE = r"\b(?:19|20)\d{2}\b"`** (`DR:10786`).
- **`_detect_year_drift(brief, notes)`** (`DR:10789-10815`) returns a drift dict `{brief_years, notes_year, notes_year_count, brief_year_count}` when all of these hold:
  - The brief has years.
  - The notes' most common year is **not** among them.
  - That year appears ≥2 times and more often than the brief's years combined.

  Otherwise it returns `None`.
- **`build_brief_correction_prompt(question, drift, target_language)`** (`DR:10818-10829`) builds "CORRECTION — RE-ANCHOR TO THE BRIEF … Do NOT search now … NOT {notes_year}", followed by the brief. The deep path injects it as a plain thread message by default (`RESEARCH_BRIEF_DRIFT_AS_MESSAGE`). It falls back to an 8-step agent turn and always flags a degradation (`DR:12501-12524`).

### O. RQ-3 research-report judge (`DR:10832-11990`)

**Constants:**
- `_JUDGE_INPUT_CAP = 600000` characters (`DR:10845`). The comment notes that the old 200K cap made long multipart reports unpublishable (`DR:10841-10844`).
- `_REPORT_JUDGE_DIMS` (7): thesis_specificity, base_rate_usage, mechanism_chains, quantitative_density, contrarian_coverage, length_vs_target, citation_coverage (`DR:10847-10850`).
- `_REPORT_JUDGE_CRITICAL` (4): thesis_specificity, mechanism_chains, contrarian_coverage, citation_coverage (`DR:10852`).
- `_REPORT_JUDGE_FATAL_GAP_RE` (`DR:10853-10865`) covers truncation, "mid-sentence", "cut off", "not delivered/provided/included/completed", "no actual/source data table", "chart ideas/specifications alone|only|without", "incomplete … citation/marker/table/section/list/forecast/scenario/milestone/deliverable", and Chinese equivalents.
- Filenames: `research_report_judge.json`, `research_report_failure_candidate.md`, `research_report_failure_candidate_judge.json` (`DR:10866-10868`).
- Scenario regexes: `_SCENARIO_KEY_PATTERNS` (`SCN-A`, `Scenario A`, leading `A.`/`A)`/`A:`; keys A-F), `_PERCENT_RE`, `_MD_HEADING` and `_MD_TABLE_DELIMITER` (`DR:10871-10880`).

**Helpers:**
- **`_scenario_key`** (`DR:10883-10888`) returns the first matching pattern's letter, uppercased.
- **`_scenario_percent`** (`DR:10891-10895`) returns the single percent value in (0, 100]. Zero or several percents give `None`.
- **`_table_cells`** (`DR:10898-10899`) splits a pipe row into cells.
- **`scenario_probability_conflicts(report)`** (`DR:10902-10988`) works as follows:
  1. **Canonical section candidates** are H1/H2 headings containing "scenario" that either start with `[N.] Scenario(s)` or contain "mutually exclusive" (`DR:10920-10926`).
  2. Their **sub-headings** (deeper level, until a heading at the same or a higher level) give `{key: pct}` rows (`DR:10928-10937`).
  3. A candidate needs 2-6 rows summing to 90-110 (`DR:10938`). The winner is the max of `(starts-with-Scenarios, -level, index)`, so the **latest** among ties wins (`DR:10939-10943`).
  4. It then scans **only lines after the canonical heading** for markdown tables whose header has a column containing "probability"/"概率" (`DR:10948-10962`).
  5. Each row's key comes from the **first cell** and its percent from the probability column (`DR:10966-10973`).
  6. If at least 2 keys overlap and the table sums to 90-110, each key differing by more than **0.5 pp** becomes `{scenario_key, canonical_probability_pct, repeated_probability_pct, repeated_table_heading}` (`DR:10974-10986`).
- **`build_report_judge_prompt(question, target_language, target_words, source_context=None)`** (`DR:10991-11028`) builds a Chinese "default-skeptical" judge prompt. It gives criteria per dimension.
  - The **PASS rule**: no dimension below 3, the 4 critical dimensions each at least 4, and a mean of at least 4 (`DR:11012-11013`).
  - Three hard **FAIL** gates:
    - Structural truncation or unfinished enumerations, with the relevant dimension scored ≤2 (`DR:11014-11015`).
    - Chart ideas without a renderable data table (missing images alone is not a FAIL) (`DR:11016-11018`).
    - Scenario name or probability inconsistent across restatements (`DR:11019-11021`).
  - The output must be JSON only: `{"scores":{…},"verdict":"PASS|FAIL","gaps":[…]}` (`DR:11023-11025`).

**Global actor coverage audit:**
- **`_GLOBAL_ACTOR_FAMILY_TERMS`**, **`_GLOBAL_ACTOR_CITATION_RE`** and **`_GLOBAL_ACTOR_HTML_COMMENT_RE`** (`DR:11031-11057`) are keyword tables and regexes for the actor audit. The family terms and citation regex are used only by the dead legacy function below.
- **`_visible_actor_audit_text(value)`** (`DR:11060-11065`) removes HTML comments, applies NFKC, casefolds and collapses whitespace.
- **`_legacy_keyword_global_actor_report_coverage(report, actor_coverage)`** (`DR:11068-11175`) is a keyword-window audit per actor (section-owned regions, or a ±2400-character fallback). **It has no callers anywhere** (module, tests or backend).
- **`audit_global_actor_report_coverage(report, actor_coverage, admitted_sources=None)`** (`DR:11178-11391`) is the live sealed audit:
  - It validates the sealed projection with `_validated_behavior_family_projection` (`DR:7576`).
  - It builds `[S n] → stable_source_id(url)` from `build_citation_index(admitted_sources, _citation_index_cap())` (`DR:11196-11205`). If no index exists it records the error `final_report_admitted_source_index_missing`. If a projected source is missing from the index it records `sealed_actor_source_missing_from_final_source_index` (`DR:11212-11215`).
  - It parses every `<!-- ACTOR_FAMILY_EVIDENCE_V1 {json} -->` marker (`_ACTOR_FAMILY_EVIDENCE_RE`, `DR:7553`) in the **raw** report and keys it by `(actor_id, family)` (`DR:11217-11238`). Markers not in the expected set are errors (`DR:11240-11248`).
  - For each actor/family slot it requires the following, with error codes `marker_count:N`, `marker_not_exact_sealed_projection`, `actor_local_mention_missing`, `sealed_claim_visible_prose_missing`, `admitted_family_citation_missing`, `actor_claim_citation_not_colocated` and `marker_payload_unparseable` (`DR:11262-11352`):
    - Exactly one marker.
    - Byte equality with `_actor_family_evidence_marker(actor_id, family, evidence)` (`DR:7711`).
    - Within ±2400 characters on either side, bounded by the neighbouring markers, a chunk that contains, in **visible** text, the actor name, the sealed `visible_claim_text` and a `[S n]` citation that resolves to one of that family's sealed `source_ids`, **all colocated in the same chunk**.
  - It returns `{required: True, complete, schema_version, canonical_roster, required_behavior_families, behavior_family_projection_sha256, admitted_source_ids_sha256, actors[...], errors, report_input_sha256, report_input_chars}` (`DR:11371-11391`).

**Scorecard validation and pass rule:**
- **`_validated_report_scores(scorecard)`** (`DR:11394-11423`) returns the 7 ordered floats, or `None` when any of these hold:
  - The input is not a dict.
  - The verdict is not PASS/FAIL.
  - **`_judge_input.truncated is True`**.
  - The score keys are not exactly the 7 dimensions.
  - Any score is a bool or non-number (numeric strings are rejected), non-finite, or outside [0, 5].
- **`report_passes(scorecard)`** (`DR:11426-11460`) checks in order:
  1. A valid schema.
  2. Not an explicit `FAIL`.
  3. If `_global_actor_coverage.required` is set, then `complete is True`.
  4. No gap matches the fatal regex.
  5. `RESEARCH_REPORT_JUDGE_STRICT` → all dimensions at least 4.
  6. Minimum at least 3.
  7. The critical dimensions at least 4.
  8. Mean at least 4.0.

  The orchestrator mirrors this as `_research_judge_passes` (`backend/app/services/pipeline_orchestrator.py:3196-3212`) without the actor-audit check. That check is redundant there, because an incomplete audit also forces `verdict=FAIL` (`DR:11693-11694`).

**Normalisation, refine prompt and identity:**
- **`_judge_length_floor_words(depth)`** (`DR:11463-11465`): 15000 for deep, otherwise 3500.
- **`_normalize_judge_scorecard(sc, report, depth, plog)`** (`DR:11468-11521`) does nothing if the schema is invalid.
  1. **Length override**: if `count_prose_words(report)` (`DR:5936`; it excludes tables, URLs and code fences) is at least the floor while the judge scored `length_vs_target < 4`, the score is set to 4.0 and `length_override{measured_prose_words, floor_words, judge_score}` is recorded (`DR:11484-11501`). This **never** changes the verdict (`DR:11476-11480`).
  2. **Scenario gate**: any `scenario_probability_conflicts` sets `verdict="FAIL"`, records `scenario_probability_conflicts`, and appends a fixed gap string (`DR:11502-11520`).
- **`build_report_refine_prompt(question, gaps, depth, target_language)`** (`DR:11524-11550`) builds a Chinese `/deep-research` top-up prompt. The gaps are sanitized as one document, the first 12 lines become bullets, and the result is wrapped in an untrusted-data delimiter capped at 12000 (`DR:11528-11536`). The question is sanitized to 24000 characters and the language to 160. It includes `_agentic_delegation_block(chinese=True)` (`DR:4588`). `depth` is unused.
- **`_report_judge_input(report)`** (`DR:11553-11565`) returns `(bounded, identity)`. Here `bounded = sanitize_untrusted_evidence_document(report)[:600000]` and `identity = {report_chars: len(sanitized), input_chars, input_sha256: sha256(bounded), truncated}`. The identity is over the **sanitized** copy (`DR:11558`; see Surprises).
- **`_judge_input_matches_report(scorecard, report)`** (`DR:11568-11576`) requires a valid schema, `scorecard["_judge_input"] == _report_judge_input(report)[1]` and `truncated is False`.

**Adoption gates:**
- **`_report_scorecard_adoptable(candidate, previous=None)`** (`DR:11579-11596`): the candidate must be valid **and** pass. If the previous scorecard is invalid or not passing, the candidate is adoptable. Otherwise every one of the 7 dimensions must be at least the previous score (`zip(..., strict=True)`).
- **`_report_scorecard_improves(candidate, previous)`** (`DR:11599-11622`) compares two valid scorecards lexicographically by `(min dimension, mean, -len(gaps))` and returns true only if the candidate is strictly greater (GLM-run 2026-09-18).

**Judge call, finalize and persistence:**
- **`judge_research_report(report, question, target_language, depth, model_name, plog, *, actor_coverage=None)`** (`DR:11625-11727`):
  - Model: `DEERFLOW_JUDGE_MODEL` or `model_name` (`DR:11631`).
  - `target_words` is "15,000-22,000 evidence-dense words" for deep and "4,500-7,000" otherwise (`DR:11632-11636`).
  - The governing prompt comes from `build_report_judge_prompt` with the sanitized question and language. The `source_context` argument is not passed (`DR:11638-11643`).
  - The evidence payload is `DETERMINISTIC SOURCE SIGNAL:` + `_dossier_source_signal(sanitized report)` (S1-S4 mention counts plus a link count, `DR:13952`), optionally the canonical actor roster/families JSON, then `RESEARCH REPORT:` + the bounded copy (`DR:11644-11660`).
  - Call: `_invoke_tool_free_model(judge_model, _stage1_model_messages(governing, "research report judge input", payload), max_output_tokens=2500, label="research-report-judge")` (`DR:11661-11671`; `DR:6490` handles primary→fallback failover). Usage is logged (`DR:11672-11677`).
  - It parses JSON with `extract_json_object` (`DR:9040`). On a dict it copies the result and **overwrites** `_judge_input` with the producer identity (`DR:11681-11685`).
  - If `actor_coverage` is set, it runs `audit_global_actor_report_coverage(report, actor_coverage, export_fetched_sources_for_manifest())` and stores `_global_actor_coverage`. If the audit is incomplete, it forces `verdict=FAIL`, appends `"Global actor coverage: {error}"` gaps (total capped at 80) and clamps `citation_coverage` to at most 2.0 (`DR:11686-11715`).
  - A truncated input only logs a warning here; the PASS refusal comes from `_validated_report_scores` (`DR:11716-11721`).
  - It returns `_normalize_judge_scorecard(...)`. A non-dict parse, or **any exception**, logs a warning and returns `None` (pass-through) (`DR:11723-11727`).
- **`_finalize_and_judge_report(report, …, *, context, actor_coverage=None)`** (`DR:11730-11749`) runs `unwrap_markdown_fence`, then `finalize_report_citations` (`DR:4802`, a deterministic `[S n]` validation and References repair), then the judge. If finalizing raises, it returns `(report, None)` and refuses to judge unfinalized bytes.
- **`_persist_report_judge(out_dir, report, scorecard, meta, *, stage, targeted_refinement_applied=None)`** (`DR:11752-11787`):
  - It requires `_judge_input_matches_report`, otherwise it returns False.
  - It writes `research_report_judge.json` atomically. The file is the scorecard plus `_judged_prose{sha256(raw report), chars, stage, scope:"llm-prose"}` (`DR:11758-11770`).
  - It sets `meta["research_report_judge"] = {verdict, scores, passed, judged_prose_sha256, judged_prose_chars, judge_scope, stage[, targeted_refinement_applied]}`. It mirrors the summary to `meta["global_synthesis_judge"]` when the stage starts with "global" or that key already exists (`DR:11771-11786`).
- **`_record_persisted_report_identity(out_dir, meta)`** (`DR:11790-11801`) re-reads `research_report.md` and sets `meta.report_chars` and `meta.persisted_report_sha256`. On an I/O or decode error it pops the sha and returns False.
- **`_adopt_judged_report_candidate(out_dir, current_report, candidate_report, …, meta, plog, *, stage)`** (`DR:11804-11883`) is used for late mutations after the report has been persisted:
  1. Finalize and judge the candidate. Reject it if the result is empty, identical, or **shorter** than the current report (`DR:11815-11827`).
  2. Load the previous scorecard from disk and require `_report_scorecard_adoptable` (`DR:11828-11841`).
  3. Snapshot the previous judge file text and the two meta keys. Write the report atomically, then `_persist_report_judge(..., targeted_refinement_applied=True)`. On **any exception**, restore the report, the judge file (or unlink it) and the meta keys, then **re-raise** (`DR:11843-11876`).
  4. Return `(finalized, True)`.

**Refine loop:**
- **`run_report_judge_refine(client, thread_id, question, depth, target_language, model_name, report, plog)`** (`DR:11886-11990`):
  - It is off when `RESEARCH_REPORT_JUDGE` is false or the report is empty. `max_rounds = RESEARCH_REPORT_JUDGE_MAX_ROUNDS` (default 1, floored at 0) (`DR:11894-11899`).
  - Pre-judge (`DR:11902-11910`). With no scorecard it returns the finalized report.
  - The loop is `for judge_round in 1..max_rounds+1` (`DR:11913`). It breaks on an invalid schema, on PASS, when `judge_round > max_rounds` ("budget exhausted after final rejudge") or when there are no gaps (`DR:11917-11928`).
  - **Refine round** (`DR:11931-11986`):
    1. `run_streamed_turn(build_report_refine_prompt, thread_id, DEERFLOW_REPORT_REFINE_RECURSION_LIMIT=360, label "research:report-refine-N")`.
    2. Try `run_incremental_report_patch(..., "judge-refine")`; if that gives `None`, fall back to `synthesize_from_thread` (`DR:8140`).
    3. Proceed only if the new text is non-empty, not an LLM error and **not shorter**. Then finalize and re-judge.
    4. If adoptable: adopt. Else if strictly improved: adopt and `continue` (this consumes a round). Otherwise break.
    5. Any exception breaks the loop and keeps the current report (`DR:11987-11989`).
  - It returns **only the report**; the final scorecard is discarded (`DR:11990`).

### P. WAVE9 incremental report patch (`DR:11993-12210`)

- **`_H2_HEADING_RE = ^##\s+(\S.*)$`** (`DR:12002`) matches H2 only. **`_PATCH_BLOCK_RE`** (`DR:12003-12006`) matches `<<<SECTION: title>>> body <<<END>>>` or `<<<APPEND>>> body <<<END>>>` (DOTALL). **`_PATCH_NO_CHANGES_RE`** (`DR:12007`) matches `<<<NO_CHANGES>>>`.
- **`_normalize_heading`** (`DR:12010-12012`) strips `#*\`` and spaces, collapses whitespace and lowercases. **`list_report_section_titles`** (`DR:12015-12017`) lists the H2 titles in order.
- **`parse_report_patch(text)`** (`DR:12020-12046`) applies `strip_think` and then collects `(title, body)` replacements and `appends`; empty bodies are skipped. It returns `None` when the text is blank, or when nothing is parseable and no NO_CHANGES token is present. Otherwise it returns `(replacements, appends, no_changes)`.
- **`apply_report_patch(report, replacements, appends)`** (`DR:12049-12091`) splits the report into the preamble and H2 segments.
  - A replacement whose normalized title matches an existing segment replaces that segment's body and keeps the original `## title` line. Only the first block per title is used (`setdefault`, `DR:12061`).
  - An **unmatched replacement is appended** as a new `## title` section, so evidence is never dropped (`DR:12083-12087`).
  - Appends go at the end. Parts are joined with `"\n\n"`, which drops the trailing newline. It returns `(patched, matched_count)`.
- **`build_report_patch_prompt(question, section_titles, report, notes, target_language, kind, max_sections)`** (`DR:12094-12139`) sets an intent per `kind`: "triangulation" folds corroborations and refutations in, while the other kinds strengthen judge-flagged sections. Its hard rules: at most `max_sections` patches, keep every existing fact, base new claims only on the notes, and use exact titles.
- **`run_incremental_report_patch(question, report, notes, target_language, model_name, plog, kind)`** (`DR:12142-12210`):
  - It returns `None` (the caller then runs a full re-synthesis) in these cases: `RESEARCH_INCREMENTAL_TOPUP` is false, the report or notes are empty, nothing parses, the number of affected sections (distinct replacement titles + appends) exceeds `RESEARCH_TOPUP_PATCH_MAX_SECTIONS` (default 4), the patched text is empty or looks like an LLM error, the patched text is **shorter** than the report, or any exception occurs.
  - It returns `report` unchanged for a NO_CHANGES-only reply.
  - Inputs are sanitized, and section titles are capped at 240 characters each. Model: `DEERFLOW_SYNTHESIS_MODEL` or `model_name`.
  - The governing prompt is built with **empty** report and notes. The evidence goes into a `Stage1ModelPrompt` evidence message (`DR:435`): `"VERIFICATION OR TOP-UP NOTES:\n" + notes[:60000] + "\n\nCURRENT REPORT:\n" + report[:600000]` (`DR:12171-12184`).
  - Call: `_bare_synth_invoke(synth_model, prompt, plog, f"incremental-patch-{kind}")` (`DR:6602`) with no `max_output_tokens`. Its output goes through `strip_think`.
  - The patch is applied to the **raw** report (`DR:12199`).
  - Callers: `run_report_judge_refine` (`DR:11942`), `run_triangulation_topup` (`DR:12282`) and the global judge-refine in `main()` with kind `"global-judge-refine"` (`DR:17062-17070`).

### Q. SCALE-5 triangulation top-up (`DR:12213-12292`)

- **`_triangulation_claim_text(c)`** (`DR:12219-12223`) reads the text from the dict keys `claim|text|statement|summary`, or uses `str(c)`.
- **`build_triangulation_verification_prompt(question, claims, target_language)`** (`DR:12226-12256`) builds a `/deep-research` "TRIANGULATION VERIFICATION PASS". It covers the first 10 claims, each truncated to 240 characters. Its rules: record only sources that were actually fetched, and a second copy of a wire story is not independent. It ends with the standard working-note headings, including `## Gaps…`.
- **`run_triangulation_topup(client, thread_id, question, depth, target_language, model_name, report, flagged, plog)`** (`DR:12259-12292`):
  1. Take claims that have text, top 10. With no claims or no report, return the report.
  2. Run `run_streamed_turn(..., thread_id, DEERFLOW_TRIANGULATION_RECURSION_LIMIT=360, "research:triangulation-verify")`.
  3. Try the incremental patch (kind "triangulation"); fall back to `synthesize_from_thread`.
  4. Adopt only a non-empty, non-error, not-shorter result. Any exception keeps the report.

  `main()` then routes the candidate through `_adopt_judged_report_candidate(stage="triangulation-topup")`. This applies only to deep runs without a synthesis manifest, with `RESEARCH_TRIANGULATION_TOPUP` default True (`DR:17840-17866`).

### R. Compact prior notes

- **`compact_prior_research_notes(reports)`** (`DR:12295-12316`) drops blank blocks. The cap is `RESEARCH_PRIOR_NOTES_CONTEXT_CHARS` (default 60000, minimum 8000, invalid → 60000). It returns `build_stratified_outline_context(blocks, cap, max_blocks=min(48, n))` (`DR:7311`). Over the cap, that gives each of the first ≤48 blocks an equal **head** slice (`DR:7322-7334`). The only consumer is `_prompt_with_compact_prior_notes` (`DR:12319`, just outside the slice). That function wraps the digest in `=== COMPACT PRIOR WORKING NOTES ===` for the isolated deep fallback, final-phase, sequential-phase and adaptive passes (`DR:12780`, `DR:12895`, `DR:12955`, `DR:13033`).

---

## Control flow

**1. Standard/quick depth, inside `run_research_stage`** (`DR:12352-12466`):
- One `run_streamed_turn(build_research_prompt, …, "research")` (`DR:12354-12364`).
- When `RESEARCH_COVERAGE_GATE` and `RESEARCH_COVERAGE_GATE_STANDARD` are on (both default True): `parse_gaps_from_notes(text)` seeds the ledger (`DR:12389`). [verifier: the gate also requires `depth == "standard"` (`DR:12385`), so quick depth never runs these top-ups] Up to `RESEARCH_COVERAGE_GATE_MAX_ROUNDS` (default 2) targeted `run_streamed_turn(build_gap_closing_prompt, 240 steps)` turns follow (`DR:12396-12412`).
- Each turn must contain a gap section (`notes_have_gap_section`, `DR:12416`), or the loop stops. The ledger advances via `advance_gap_set_from_notes` (`DR:12424-12428`). The loop stops on a plateau or after 2 rounds with no yield, i.e. no new sources and no closed gaps (`DR:12432-12445`).
- A `synthesize_from_thread` result is adopted only if it is longer (`DR:12446-12450`).
- In evidence-only mode, `merge_resume_evidence_packs` is applied (`DR:12460-12465`).

**2. Deep depth** (`DR:12468-13152`):
1. The opening turn runs on the main thread (`DR:12477-12491`).
2. The brief year-drift check: `_detect_year_drift`, then `inject_thread_message`, or a fallback 8-step `run_streamed_turn` (`DR:12501-12524`).
3. `accumulated_gaps = parse_gaps_from_notes(opening)`, then `planned_deep_phase_indices(...)` (`DR:12529-12548`).
4. Fan-out. If `_bridge_fanout_enabled()` (`DR:4572`; `RESEARCH_DEEP_FANOUT`, suppressed when harness delegation is active), then either `start_deep_fanout` overlapped with scope and later `join_deep_fanout` (`DR:12583-12594`, `DR:12678-12711`), or the blocking `run_deep_fanout` (`DR:12595-12625`). The notes are injected with `inject_thread_message`, falling back to `build_fanout_absorption_prompt` and a 120-step turn.
5. Parallel phase path (default). Scope runs sequentially, then `advance_gap_set_from_notes` (`DR:12641-12662`). The middle phases run through `run_scoped_worker` in a pool (`DR:12717-12766`). A middle phase that fails runs again sequentially on an isolated thread with `_prompt_with_compact_prior_notes` (`DR:12770-12812`). Merged notes are injected (`DR:12815-12854`). If the injection succeeded, gaps go through `reconcile_parallel_gap_sets`; otherwise `_merge_gaps` with `parse_gaps_from_notes` (`DR:12868-12881`). [verifier: `_absorbed_ok` is also set True after the fallback absorption turn runs (`DR:12839-12852`). So reconciliation runs whenever injection or the fallback turn completed. `_merge_gaps` is used only when no parallel phase produced notes or an exception occurred during absorption (`DR:12820-12854`)] Then forecast-implications runs on an isolated thread with compact prior notes, followed by `advance_gap_set_from_notes` and injection (`DR:12893-12932`).
6. The sequential path (`RESEARCH_PARALLEL_PHASES=false`) runs each scheduled phase on an isolated thread with compact notes (`DR:12935-12988`).
7. Adaptive gap closing. `_budget = adaptive_passes_remaining(0, RESEARCH_MAX_ADAPTIVE_PASSES=7)`, so at most 1 pass by default. Each pass is `run_streamed_turn(_prompt_with_compact_prior_notes(build_gap_closing_prompt), isolated thread, DEERFLOW_ADAPTIVE_PASS_RECURSION_LIMIT=360)`. The loop stops when the gap section is missing, no fresh gaps appear, there is no yield, or a plateau is reached (`DR:13013-13085`).
8. Synthesis runs via `synthesize_from_evidence_parts` (outside the slice), then **`run_report_judge_refine`** (`DR:13126-13138`). An empty deep synthesis raises (`DR:13140-13144`).

**3. `main()` around the report** (outside the slice; anchors show where slice functions fire):
- **Global synthesis (manifest) path.** `_finalize_and_judge_report(..., context="global pre-judge", actor_coverage=dossier_coverage)` runs first (`DR:17033-17042`). On a FAIL with gaps comes one `run_incremental_report_patch(kind="global-judge-refine")` from routed evidence, then a re-judge. The forensic sidecars `research_report_refinement_candidate.md/_judge.json` are written. The patch is adopted only if `_report_scorecard_adoptable` holds (`DR:17043-17111`).
- **Final persistence.** In order (`DR:17434-17534`):
  1. `looks_like_llm_error(report)` → exit 2.
  2. `unwrap_markdown_fence`.
  3. `finalize_report_citations`.
  4. If the judge is required (a synthesis manifest, or a deep run with `RESEARCH_REPORT_JUDGE` on) and the bytes differ from the last judged bytes, `_finalize_and_judge_report(context="final persistence")`.
  5. `_judge_input_matches_report`. If false, write `research_report_failure_candidate.md` and `…_judge.json` and raise `RuntimeError`.
  6. Write `research_report.md`.
  7. `_record_persisted_report_identity`.
  8. `_persist_report_judge`, which raises if it returns False.
  9. If `not report_passes(...)`, set `meta.research_report_quality_gate` and status failed, then **exit 2**.
- **Dossier gate.** `_is_degraded_artifact(dossier, _min_report)` → single-track (`DR:17541-17543`).
- **Extraction analytics.** In order: `_clamp_asof_reference` → `enrich_quantitative_rows` → `reconcile_quantitative` → `annotate_recency_rows(quant)` → `flag_implausible_quant` → write `quantitative.json` / `contested.json` → `annotate_recency_rows(sources)` → `source_diversity_histogram` → `compute_coverage_gaps` → `audit_triangulation` → `compute_research_quality` (`DR:17655-17829`).
- **Triangulation top-up.** `run_triangulation_topup`, then `_adopt_judged_report_candidate`, then `_record_persisted_report_identity` (`DR:17840-17866`).

**4. Evidence lane / resume.** A prior pack is accepted only if `parse_evidence_pack(...)` is non-empty and `not evidence_pack_is_control_failure_only(...)` (`DR:16767-16770`). The final pack is `merge_resume_evidence_packs(resume, current)` (`DR:17265-17267`). The lane fails if it has no sources (when required) or is failure-only (`DR:17275-17291`). [verifier: the lane fails only when it has no source rows AND (sources are required OR the pack is failure-only), per `not source_rows and (_require_lane_sources or evidence_pack_is_control_failure_only(...))` (`DR:17275-17277`). A failure-only pack that has sources does not fail here] The dossier is usable only if it is non-empty, `not _is_degraded_artifact(…, 400)`, `not _is_control_failure_block` and accountable (`DR:17314-17319`).

**5. v3 linear engine.** `bridge_call("enrich_quantitative_rows")`, `bridge_call("annotate_recency_rows")` for quant and timeline, and `bridge_call("compute_research_quality", …, judge_scorecard=None, grounding=…)` (`deerflow_bridge/linear_research.py:5745-5790`).

**6. Track B.** The actor-ontology stage also uses `run_streamed_turn` for its research, completion and refine turns (`DR:14177`, `DR:14198`, `DR:14425`).

---

## Data & artifacts

| Artifact / key | Writer (anchor) | Format / key fields |
|---|---|---|
| `research_report_judge.json` (`_REPORT_JUDGE_FILENAME`, `DR:10866`) | `_persist_report_judge` (`DR:11767-11770`) | The judge JSON `{scores{7 dims 0-5}, verdict, gaps[], _judge_input{report_chars,input_chars,input_sha256,truncated}, [_global_actor_coverage{…}], [length_override{…}], [scenario_probability_conflicts[…]], _judged_prose{sha256,chars,stage,scope:"llm-prose"}}` |
| `research_report.md` (`REPORT_FILENAME`, `DR:861`) | `_adopt_judged_report_candidate` (`DR:11853`, restored at `DR:11863`); main `DR:17490` | Markdown; read back by `_record_persisted_report_identity` (`DR:11792-11795`) |
| `research_report_failure_candidate.md` / `research_report_failure_candidate_judge.json` (`DR:10867-10868`) | main (`DR:17474-17486`) | Forensic sidecars when the final judge is not bound to the bytes. The orchestrator lists them (`backend/app/services/pipeline_orchestrator.py:3125-3126`) |
| `meta["research_report_judge"]`, `meta["global_synthesis_judge"]` | `DR:11771-11786` | `{verdict, scores, passed, judged_prose_sha256, judged_prose_chars, judge_scope:"llm-prose", stage, targeted_refinement_applied?}` |
| `meta["report_chars"]`, `meta["persisted_report_sha256"]` | `DR:11799-11800` | On-disk report identity |
| `meta["research_quality"]` | main from `compute_research_quality` (`DR:17806-17819`) | `{score, components{source_tier_mix,dossier_richness,judge_mean,grounding}, judge_passed?, score_before_judge_fail_cap?, degraded?, degradation?, quant_penalty?}` |
| `meta["coverage_gaps"]` | `DR:17772` | `{missing_named_entities[≤20], orphan_fault_lines[≤20]}` |
| `meta["single_origin_loadbearing"]` | `DR:17778` | List of `{claim, reason, independent_sources}` |
| `meta["quant_unit_warnings"]` | `DR:17712` | `[{metric, unit, ratio, values}]` |
| `meta["quant_freshness"]`, `meta["source_freshness"]` | `DR:17719`, `DR:17738` | `{fresh_le_90, recent_le_365, stale_gt_365, undated, n_stale}` |
| `meta["quant_implausible"]` | `DR:17722` | List of strings |
| `meta["as_of_date_overridden"]` | `DR:17657-17658` | `{extracted, used}` |
| `meta["source_diversity"]` | `DR:17741` | See §B |
| `quantitative.json` rows | enriched in place (`DR:9819-9854`), annotated (`DR:9929-9931`) | Added: `value_num, year, value_kind, region, technology, analyst, metric_family, metric_family_claimed?, staleness_days, is_stale` |
| `contested.json` | main appends `reconcile_quantitative` output (`DR:17730`) | `{claim, positions[{stance,sources,tier}], status:"contested", why_they_differ, origin:"quant_reconcile"}` |
| `research_progress.log` (via `ProgressLog`, `DR:4418`) | `plog.write(kind, msg)` everywhere | Kinds used here: `stage, tool, result, custom, usage, warn, ok` |
| LangGraph thread checkpoint | `inject_thread_message` → `agent.update_state` (`DR:10354-10355`) | Appended `HumanMessage` |

**In-memory structures:**
- `_RESEARCH_FLAGS`: run-scoped degradation reasons, appended by `_flag_research_degradation` from `run_streamed_turn` (`DR:10307`, `DR:10327`). They are folded into `research_quality.degradation` (`DR:17810-17817`).
- `_FANOUT_WORKER_NOTES`: full worker notes from `join_deep_fanout` (`DR:10554`), read by synthesis via `_collected_worker_notes` (`DR:1291`).
- The per-turn pending fetch/search tables (`DR:10206-10207`) are merged into the global `_FETCHED_SOURCES` under a lock (`DR:10331`).
- `chunks` holds the per-AI-message deltas within one turn (`DR:10200`).

---

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_ASOF_MAX_LAG_DAYS` | 45 | How much older than the run date an extracted as-of may be before it is replaced by the run date | `DR:9872` |
| `RESEARCH_DEGENERATE_TOOL_CORRECT_AT` | 8 | Consecutive rejected tool calls → one corrective message (≤0 disables) | `DR:10157` |
| `RESEARCH_DEGENERATE_TOOL_BREAK_AT` | 16 | Consecutive rejected calls → `_DegenerateToolLoopError` and salvage (≤0 disables) | `DR:10158` |
| `RESEARCH_BUDGET_DENIAL_BREAK_AT` | 3 | Consecutive `research_budget_exhausted` tool results → end the turn and salvage (≤0 disables) | `DR:10163-10167`, `DR:10280-10285` |
| `RESEARCH_FETCH_ACCOUNTING_V2` | true | Per-turn id-paired fetch/search accounting vs the legacy global LIFO | `DR:1594-1595`, `DR:10205` |
| `RESEARCH_FANOUT_WORKER_BUDGET` | 260 | Default recursion limit per scoped worker | `DR:1305`, `DR:10505` |
| `RESEARCH_MODEL_CONCURRENCY_GLOBAL` | 12 | Upper bound on fan-out executor workers | `DR:4541-4545`, `DR:10527-10528` |
| `RESEARCH_REPORT_JUDGE` | true | Enables `run_report_judge_refine`; main also uses it to decide `judge_required` | `DR:11894`, `DR:17448-17451` |
| `RESEARCH_REPORT_JUDGE_MAX_ROUNDS` | 1 | Maximum refine mutations (judge observations = rounds + 1) | `DR:11897` |
| `RESEARCH_REPORT_JUDGE_STRICT` | false | When true, all 7 dimensions must be ≥4 | `DR:11453` |
| `DEERFLOW_JUDGE_MODEL` | (= model_name) | Judge model route | `DR:11631` |
| `DEERFLOW_REPORT_REFINE_RECURSION_LIMIT` | 360 | Step budget for the refine top-up turn | `DR:11936` |
| `RESEARCH_INCREMENTAL_TOPUP` | true | Enables section-level patching before falling back to full re-synthesis | `DR:12152` |
| `RESEARCH_TOPUP_PATCH_MAX_SECTIONS` | 4 | Maximum sections a patch may touch | `DR:12157` |
| `DEERFLOW_SYNTHESIS_MODEL` | (= model_name) | Model used by the patch call | `DR:12172` |
| `DEERFLOW_TRIANGULATION_RECURSION_LIMIT` | 360 | Step budget for the triangulation verify turn | `DR:12276` |
| `RESEARCH_PRIOR_NOTES_CONTEXT_CHARS` | 60000 (min 8000) | Size of the compact prior-notes digest | `DR:12307-12311` |
| Call-site knobs (outside the slice) that gate slice functions | — | `RESEARCH_SOURCE_DIVERSITY`, `RESEARCH_COMPLETENESS_PROBE`, `RESEARCH_TRIANGULATION_AUDIT`, `RESEARCH_QUANT_ENRICH`, `RESEARCH_QUANT_RECONCILE`, `RESEARCH_RECENCY_WEIGHTING`, `RESEARCH_STALE_DAYS`=365, `RESEARCH_QUALITY_GROUNDING`, `RESEARCH_QUALITY_FLOOR`=0.45 (log only in the bridge), `RESEARCH_TRIANGULATION_TOPUP`, `RESEARCH_BRIEF_DRIFT_CHECK`, `RESEARCH_BRIEF_DRIFT_AS_MESSAGE`, `RESEARCH_DEEP_GAP_THREADING`, `RESEARCH_GAP_SET_REPLACE`, `RESEARCH_CONVERGENCE_SCHEDULER`, `RESEARCH_SHARED_ACTOR_TRACK`, `RESEARCH_DEEP_FANOUT`, `RESEARCH_FANOUT_WIDTH`(4 in bridge), `RESEARCH_FANOUT_OVERLAP_SCOPE`, `RESEARCH_PARALLEL_PHASES`, `RESEARCH_ADAPTIVE_PASSES`, `RESEARCH_MAX_ADAPTIVE_PASSES`=7, `DEERFLOW_ADAPTIVE_PASS_RECURSION_LIMIT`=360 | `DR:17740`, `DR:17770`, `DR:17775`, `DR:17700`, `DR:17709`, `DR:17660-17664`, `DR:17786`, `DR:17820-17825`, `DR:17843`, `DR:12501`, `DR:12510`, `DR:12529`, `DR:12427`, `DR:12534`, `DR:12533`, `DR:4581`, `DR:12582`, `DR:12584`, `DR:12559`, `DR:13013`, `DR:13015`, `DR:13039` |

---

## External calls

- **LLM, tool-free.**
  - `judge_research_report` → `_invoke_tool_free_model(judge_model, …, max_output_tokens=2500, label="research-report-judge")` (`DR:11661-11671`). This uses primary/fallback failover with a process-local circuit (`DR:6490-6530`) and a model-call lease (`DR:4550-4558`).
  - `run_incremental_report_patch` → `_bare_synth_invoke(synth_model, Stage1ModelPrompt, label="incremental-patch-{kind}")` (`DR:12185-12186`, `DR:6602-6633`).
- **LLM + tools, agentic.** `run_streamed_turn` → `client.stream(message, thread_id, recursion_limit)` through `_leased_client_stream` (`DR:4561-4569`, `DR:10220-10222`). The DeerFlow embedded client runs the LangGraph lead agent, whose tool calls (web_search/web_fetch/task …) execute inside the harness. Higher-level callers of this path in the slice:
  - `run_scoped_worker` (`DR:10501`).
  - `run_report_judge_refine` (`DR:11932`), which may also call `synthesize_from_thread` (`DR:11944`).
  - `run_triangulation_topup` (`DR:12272`, `DR:12284`).
- **Checkpoint write, no model.** `inject_thread_message` → `client._agent.update_state` (`DR:10354-10355`).
- **Concurrency.** A `ThreadPoolExecutor` runs the fan-out workers (`DR:10527-10533`).
- **Filesystem.** `_atomic_write_text` (`DR:76`) writes to `research_report_judge.json` and `research_report.md` (`DR:11767-11770`, `DR:11853`, `DR:11863`, `DR:11870`). `_record_persisted_report_identity` reads the report (`DR:11794`). `_adopt_judged_report_candidate` reads the judge file (`DR:11832`, `DR:11845`) and may unlink it (`DR:11866`).
- No subprocess, direct HTTP or DB access occurs in this slice.

---

## Cross-module edges

**Callers into this slice:**
- **Same module:** `run_research_stage` (`DR:12331-13152`), `run_actor_ontology_stage` (`DR:14177`, `DR:14198`, `DR:14425`), `main()` (`DR:16767-17892`), `run_extract_only` (`DR:16251`, `DR:16257`), `_message_text` (`DR:5246`), the shared-actor-dossier loader (`DR:7480-7481`), and the `build_deep_phase_prompt` gap block (it mirrors the 20-cap of `parse_gaps_from_notes`, `DR:4971`).
- **`deerflow_bridge/linear_research.py`** (v3 engine) calls through `bridge_call`: `enrich_quantitative_rows` (`:5745`), `annotate_recency_rows` (`:5750-5751`) and `compute_research_quality` (`:5789`).
- **Orchestrator.** It does not import the slice. It **mirrors** several pieces: `_LLM_ERROR_MARKERS`, `_control_failure_block` and `_evidence_pack_is_control_failure_only` (`backend/app/services/pipeline_orchestrator.py:2748-2811`); the judge dims, critical dims, fatal regex, schema and pass rule (`backend/app/services/pipeline_orchestrator.py:3151-3212`); and judge-to-prose binding checks over `_judge_input`/`_judged_prose` (`backend/app/services/pipeline_orchestrator.py:3231-3309`). It forwards `RESEARCH_DEEP_FANOUT`, `RESEARCH_FANOUT_WIDTH` and `RESEARCH_SHARED_ACTOR_TRACK` to this subprocess (`backend/app/services/pipeline_orchestrator.py:2343-2350`).
- **Tests:**
  - `backend/tests/test_research_evidence_quality.py`: diversity, triangulation, reconcile, recency, coverage, gaps, quality.
  - `backend/tests/test_audit_fixes_research.py`: quality, as-of clamp, implausible, degraded artifact, abstract concepts.
  - `backend/tests/test_sessionb_research_viz.py`: enrich, value_num.
  - `backend/tests/test_sessionb_judge_normalization.py`: normalize, scenario conflicts, report_passes, judge.
  - `backend/tests/test_bridge_prediction_markets.py`: judge input cap, adoption/persist, refine, drift, adaptive passes.
  - `backend/tests/test_stage1_model_boundaries.py`: actor audit, judge, patch.
  - `backend/tests/test_wave9_research_speed.py`: run_streamed_turn, patch parse/apply, inject, advance_gap_set, degen thresholds.
  - `backend/tests/test_multipart_synthesis.py`: scheduler, ledger reconcile.
  - `backend/tests/test_research_fanout.py`: KIQ seeds.
  - `backend/tests/test_loop010_global_synthesis.py`: pack predicates, resume merge.
  - `backend/tests/test_bridge_overhaul_v3.py`: usage line.

  These were found by `grep -rl` over `backend/tests` and `backend/scripts`.

**Callees outside the slice:**
- Sanitizers and message builders: `sanitize_untrusted_evidence_document` (`DR:214`), `delimit_untrusted_evidence_data` (`DR:362`), `_stage1_model_messages` (`DR:391`), `Stage1ModelPrompt` (`DR:435`).
- Tool-call accounting: `_validate_tool_args` (`DR:1470`), `_structured_fetch_control_result` (`DR:1545`), the `_pending_*` accounting functions (`DR:1709-1891`), `_record_fetched_url`/`_mark_fetch_result` (`DR:1511`, `DR:1572`).
- Run-scoped state: `_flag_research_degradation` (`DR:1277`), `_record_worker_notes` (`DR:1282`).
- Streaming: `_leased_client_stream` (`DR:4561`).
- Citations and source export: `finalize_report_citations` (`DR:4802`), `build_citation_index` (`DR:4695`), `stable_source_id` (`DR:1348`), `export_fetched_sources_for_manifest` (`DR:7936`).
- Prose and evidence packs: `count_prose_words` (`DR:5936`), `parse_evidence_pack`/`render_evidence_pack` (`DR:7171`, `DR:7141`), `build_stratified_outline_context` (`DR:7311`).
- Actor evidence: `_validated_behavior_family_projection` (`DR:7576`), `_actor_family_evidence_marker` (`DR:7711`).
- Model calls and synthesis: `_invoke_tool_free_model` (`DR:6490`), `_bare_synth_invoke` (`DR:6602`), `synthesize_from_thread` (`DR:8140`), `extract_json_object` (`DR:9040`).
- Other: `_parse_date` (`DR:9226`), `_dossier_source_signal` (`DR:13952`), `DEEP_RESEARCH_PHASES` (`DR:574`).

---

## Invariants, gates, validation

- **No silent pass from a malformed judge.** Only an explicit `PASS` with exactly 7 finite numeric scores in [0, 5] and an untruncated input can pass (`DR:11403-11423`, `DR:11434-11437`). A judge transport or parse failure gives `None`, i.e. unknown, never an invented FAIL (`DR:11723-11727`).
- **Explicit FAIL is authoritative** over numbers (`DR:11437-11438`). Deterministic gates can **only downgrade**: scenario conflicts force FAIL (`DR:11502-11505`), an incomplete actor audit forces FAIL and caps `citation_coverage` at 2 (`DR:11693-11710`), and fatal gap text blocks PASS (`DR:11444-11451`). The length override changes a number only (`DR:11490-11496`).
- **Exact-byte provenance.** `_judge_input` is producer-owned and overwritten after parsing (`DR:11685`). Persisting requires `_judge_input_matches_report` (`DR:11756-11757`). `_judged_prose.sha256` is the sha of the raw persisted prose (`DR:11758-11764`).
- **Monotonic adoption.** A late mutation is adopted only if it passes and does not regress any dimension of a prior PASS (`DR:11587-11596`). It must also be non-empty, different and not shorter (`DR:11824-11827`). I/O failure during adoption rolls back the report, judge file and meta before re-raising (`DR:11862-11876`).
- **"Never shorter" rule.** It holds for the patch (`DR:12203-12205`), refine (`DR:11946-11947`), triangulation (`DR:12285-12286`) and adoption (`DR:11825`).
- **Patch bound.** A patch touches at most `RESEARCH_TOPUP_PATCH_MAX_SECTIONS` sections (`DR:12195-12198`), and unmatched replacements become appends, so content is never lost (`DR:12083-12087`).
- **Gap-ledger contract.** A pass without a gap heading cannot shrink the ledger (`DR:10709-10710`). In parallel reconciliation, a carried gap closes when any compliant worker omits it (`DR:10748-10753`).
- **Error-text gate.** It requires both a short length and a sentinel (`DR:9972`).
- **Tool-call validation.** It happens before accounting. Rejected calls are never counted as fetches (`DR:10237-10248`).
- **Quality score bounds.** It is ≥0 after the penalty, the penalty is capped at 0.15 (`DR:9421`), and a judge FAIL caps it at 0.44 (`DR:9439`). [verifier: the cap applies to any schema-valid scorecard for which `report_passes` is False (`DR:9434-9441`). That covers an explicit FAIL, and also a PASS verdict with sub-threshold numbers, a fatal-gap phrase or an incomplete actor audit. When the score was `None` the cap sets it to 0.44]

---

## Failure modes & recovery

- **Agent-turn failure of any kind** (recursion limit, provider error, degenerate loop, budget denial): `run_streamed_turn` logs a warning, flags a degradation and returns the salvaged text of the last AI message. It does not raise for `Exception` subclasses (`DR:10312-10334`).
- **Malformed tool loops**: one deterministic correction at 8 consecutive rejections, then a hard break at 16 (`DR:10241-10248`, `DR:10303-10310`).
- **Budget exhausted**: 3 consecutive denials end the turn instead of replaying full context into denied tools (`DR:10277-10285`).
- **Checkpoint injection fails**: `inject_thread_message` returns False, and callers fall back to an agent turn (`DR:10357-10358`; for example `DR:12510-12519`).
- **Worker failure**: it contributes nothing, and the executor is always shut down (`DR:10555-10558`).
- **Judge unavailable or unparseable**: `None`, and the current draft continues (`DR:11911-11912`). In `main()`, however, a required judge that is not bound to the bytes raises `RuntimeError` after writing the failure-candidate sidecars (`DR:17470-17488`). An explicit judge FAIL causes exit 2 with `meta.research_report_quality_gate` (`DR:17506-17534`).
- **Citation finalizer raises**: the judge is refused (`(report, None)`) (`DR:11740-11745`).
- **Refine, patch or triangulation exceptions**: the current report is kept (`DR:11987-11989`, `DR:12208-12210`, `DR:12290-12292`).
- **Adoption I/O failure**: rollback, then re-raise to the caller's non-fatal wrapper (`DR:11862-11876`; the wrapper is at `DR:17867-17868`).
- **Analytics on a malformed obj**: each helper tolerates non-list or non-dict input (for example `DR:9285`, `DR:9319`, `DR:9333-9338`, `DR:9496-9497`, `DR:9919-9920`). `main()` also wraps them in try/except (`DR:17827-17828`).
- **Over-cap report (>600000 sanitized chars)**: never PASS (`DR:11406-11407`). In `main()` the binding check fails and the stage raises (`DR:17470-17488`).

---

## Surprises

1. **(suspected, cross-module) The judge-input identity is over sanitized text, but the orchestrator verifies it against raw text.**
   - `_report_judge_input` hashes and counts `sanitize_untrusted_evidence_document(report)` (`DR:11558-11564`). `_persist_report_judge` records `_judged_prose.sha256` and `chars` from the **raw** report (`DR:11758-11764`).
   - The orchestrator requires `_judge_input == {"report_chars": chars, "input_chars": chars, "input_sha256": sha256(report[:chars]), "truncated": False}`, with `chars = _judged_prose.chars` (`backend/app/services/pipeline_orchestrator.py:3261-3289`).
   - The two agree only if sanitization is the identity on the report. The sanitizer applies NFKC (which rewrites full-width CJK punctuation such as `，（：`), strips each line, collapses runs of spaces and tabs, merges consecutive blank lines (`DR:229-233`, `DR:277-313`) and replaces instruction-like lines.
   - So a Chinese report, an indented nested list or a double blank line would plausibly trip `judge_input_identity_mismatch`.
   - The orchestrator test fixture builds the identity from raw prose by hand and does not go through the bridge (`backend/tests/test_research_contract_finalization.py:44-57`). I have not verified this end-to-end.
2. **(suspected) `_quant_value_num` misparses dates.** The comment at `DR:9740` says date-like `YYYY-MM-DD` values were "excluded above", but there is no such check. `'2025-01-15'` parses as the "range" 2025–01 and returns **1013.0**, and `'Q3 2025'` returns 3.0 (both confirmed by isolated execution).
3. **(suspected) The `_quant_value_kind` text fallback** uses `\bproject\b` etc. (`DR:9800-9802`). The family "project lead time" (`DR:9684`) is therefore always tagged `forecast`, [verifier: "always" overstates it. The text fallback runs only when no `value_kind/value_type/observation_type/fact_type/status` label and no boolean `is_projection` decided first (`DR:9790-9798`); `{'metric':'project lead time','value_type':'actual'}` gives `actual`. It reads only metric and definition, so family members named "construction lead time", "interconnection lead time" or 项目周期 are not tagged (isolated execution gives `None`). "expected" does match] while "projected", "forecasted" and "estimated" do not match. The fallback can never return `"actual"`.
4. **(suspected) `reconcile_quantitative` treats time series as disagreements.** It groups only by `(metric, unit)` (`DR:9607`) and ignores year, region and value_kind. So a time series of one metric (a 2024 actual vs a 2030 forecast) becomes a synthesized "contested" claim in `contested.json`, and a ratio between 300 and 3000 is also reported as a unit-scale error.
5. **(suspected) `flag_implausible_quant` misreads non-growth percentages.** Any value >150 whose unit contains `%` is reported as "extreme growth" (`DR:9906-9909`), e.g. a 250% debt-to-GDP. The future-date projection check is a plain substring test (`"by 20"`, `DR:9898`).
6. **(suspected) `_is_control_failure_block` has no length gate.** It matches sentinels **anywhere** in a block (`DR:10007-10008`), unlike `looks_like_llm_error`, which requires fewer than 400 characters (`DR:9972`). `"Error code: 4"` is a substring of, e.g., `"Error code: 403"`. A long, genuine evidence block or actor dossier that quotes a 4xx fetch error would therefore be dropped by `merge_resume_evidence_packs` (`DR:10042`) or rejected as a dossier (`DR:7481`, `DR:17317`). The orchestrator duplicates the same logic (`backend/app/services/pipeline_orchestrator.py:2775-2776`).
7. **(suspected) `_detect_year_drift` misfires on long-horizon briefs.** A brief "by 2030" with opening notes dominated by current data ("2025" three times) returns a drift dict (confirmed). That injects "investigate … NOT 2025" (`DR:10823-10827`) and flags the run as degraded (`DR:12520-12522`), which lowers quality signals. [verifier: the flag sets `research_quality.degraded=True` plus `degradation[]` and `meta.research_degradation` (`DR:17810-17816`). It does not change the numeric `research_quality.score`]
8. **Dead or test-only code.**
   - `_legacy_keyword_global_actor_report_coverage` (`DR:11068-11175`) has zero references, along with its only users `_GLOBAL_ACTOR_FAMILY_TERMS` (`DR:11031`) and `_GLOBAL_ACTOR_CITATION_RE` (`DR:11055`).
   - `evidence_pack_is_provider_error_only` (`DR:9975`) is used only by a test.
9. **Unused parameters and empty prompt slots.**
   - `build_report_judge_prompt(source_context=…)` is never passed by its only caller (`DR:11638-11643`); the source signal goes into the payload instead (`DR:11644-11648`).
   - `build_report_refine_prompt(depth)`, `run_scoped_worker(depth, model_name)` and `start_deep_fanout(depth, model_name)` pass these through unused.
   - `build_report_patch_prompt` is called with `report=""` and `notes=""` (`DR:12173-12176`). Its governing text therefore ends with **empty** `=== VERIFICATION / TOP-UP NOTES ===` / `=== CURRENT REPORT ===` sections and says "notes below". The real content arrives in a separate evidence message under different labels (`DR:12177-12184`).
10. **The classic deep path judges twice.** `run_report_judge_refine` discards its final scorecard (`DR:11990`). In `main()`, `final_judged_report` is `None` on the non-manifest path (`DR:16989`), so `main()` finalizes and judges again at "final persistence" (`DR:17453-17467`). That costs at least one extra judge LLM call per deep run, and `finalize_report_citations` runs again as well (it is idempotent by its docstring, `DR:4803`).
11. **`_judge_length_floor_words` does not match the prompt it claims to mirror.** The docstring says it is "strictly consistent" with the prompt's `target_words`. The non-deep floor is 3500 (`DR:11465`), but the prompt says "4,500-7,000" (`DR:11635`).
12. **The length override cannot rescue the case it was written for.** The docstring cites run `pipe_bef6879b2e94` (`DR:11470-11473`), which had length 3 and verdict FAIL. Because an explicit FAIL stays authoritative (`DR:11437`), the override only adjusts numbers (judge_mean and the improvement ordering).
13. **The judge-FAIL cap in `compute_research_quality` is mostly defensive.** In `main()`, a judge FAIL exits 2 (`DR:17506-17534`) before extraction runs (`DR:17636+`). v3 passes `judge_scorecard=None` (`deerflow_bridge/linear_research.py:5789-5790`). A truncated-input FAIL is not capped, because `_validated_report_scores` rejects it (`DR:9431`, `DR:11406`).
14. **`run_streamed_turn` hides some failures and drops some text.**
    - It swallows every `Exception`, including programming errors, and turns them into a degradation flag plus salvage (`DR:10312-10327`).
    - It returns only the **last** AI message's text (`DR:10332`).
    - "Rejected" tool calls are only excluded from bridge accounting. The harness has already dispatched them, and `_validate_tool_args` repairs never reach the harness (inference from the stream-only position, `DR:10237-10248`).
    - `tool_calls` counts rejected calls too, which shrinks the corrective segment's budget (`DR:10232`, `DR:10309`).
15. **Gap-heading parsing is loose in one way and ASCII-only in another.** `_GAP_HEADING_RE` has no leading `\b` and matches any heading word ending in gap/gaps (`DR:10581`), so "## Data gaps & caveats" opens a gap section. [verifier: the cause is misattributed. "Data gaps" would match even with a leading `\b`, because `re.search` scans the whole heading (`DR:10600`). The missing leading `\b` only matters for words ending in "gap", e.g. "## Stopgap measures" opens a gap section (isolated execution)] It requires ASCII "gap", while prompts also say "Write your pass notes in {target_language}" (for example `DR:4968`). A translated heading such as "缺口" is never detected, so the ledger is retained and `notes_have_gap_section` fails (suspected; it depends on the model keeping the English heading). A bullet like "- None" is accepted as a 4-character gap even though the prompt forbids placeholders (`DR:5048-5050` vs `DR:10606-10607`).
16. **`_merge_gaps` mutates its input.** It appends to the caller's list beyond the cap before returning a slice (`DR:10623-10627`).
17. **`annotate_recency_rows` counts future-dated rows as fresh.** They get a negative `staleness_days` and are counted as `fresh_le_90` (`DR:9928-9933`).
18. **`_clamp_asof_reference` clamps in one direction only.** It corrects too-old as-of dates but never future ones (`DR:9875-9877`). `RESEARCH_ASOF_MAX_LAG_DAYS=0` overrides every past extracted date.
19. **`_canonical_region` does not title-case.** Its docstring promises "Title-Case" on a miss, but it returns the raw string (`DR:9724`).
20. **The compact prior-notes digest head-truncates each block.** Over the cap, each block keeps only its **head** (`DR:7330-7333`). Every pass ends with its `## Gaps …` ledger, so isolated late passes see the earliest evidence of each pass and lose its conclusions (inference). Blocks after the 48th are dropped entirely (`DR:7322-7326`).
21. **Doc-vs-code drift.**
    - `DRF_ARCHITECTURE.md:448` gives `start_deep_fanout` at `:4899`, and `DRF_ARCHITECTURE.md:457`/`:466`/`:470` give `run_streamed_turn` and thresholds at `:4702`/`:4616`/`:4598`. The real locations are `DR:10511`, `DR:10190` and `DR:10143`.
    - Fan-out width: the bridge default is 4 (`DR:12582`), but `backend/app/config.py:1174`, `.env.example:373` and `DRF_ARCHITECTURE.md:448` say 8. The orchestrator always forwards the Config value (`backend/app/services/pipeline_orchestrator.py:2350`).
    - `RESEARCH_DEEP_FANOUT` defaults to False in the bridge (`DR:4581`; the comment at `DR:10367` says "default off"), but Config defaults to true (`backend/app/config.py:1172`).
    - `README.md:1160` says the judge runs "over the exact dossier bytes". The judge actually sees the sanitized, capped copy (`DR:11558-11559`). Only `_judged_prose` refers to the exact raw bytes.
22. **Duplicated logic that must stay in sync by hand.** The judge dims, critical set, fatal-gap regex, schema validation and pass rule are copied into the orchestrator (`backend/app/services/pipeline_orchestrator.py:3151-3212`). So are the error sentinels and control-failure predicate (`backend/app/services/pipeline_orchestrator.py:2748-2811`). Nothing enforces equality.

---

## Verification

An adversarial verifier checked this map on 2026-10-11 against the main-branch checkout on disk. Every claim was checked against source. Isolated execution ran AST-extracted pure functions only: no module import, no network, no LLM.

**Verdict counts.**

| Group | Total | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims | 15 | 13 | 2 | 0 |
| Surprises (the 15 load-bearing ones, covering map items #1-#12, #15, #16, #20, #21 and #22) | 15 | 13 | 2 | 0 |
| Extra walkthrough/control-flow spot-checks | 16 | 11 | 5 | 0 |

The 11 confirmed spot-checks:
- `_is_degraded_artifact` callers and the `_min_report` 2000/400 default (`DR:17414`).
- `strip_think` callers (`DR:5246`, `DR:10332`, `DR:12031`, `DR:12185`).
- `unwrap_markdown_fence` callers (`DR:11737`, `DR:17343`, `DR:17441`, `DR:17549`).
- The actor-audit error codes and the ±2400-character window (`DR:11262-11352`).
- The scenario-conflict winner rule and the 0.5 pp threshold (`DR:10938-10986`).
- The compact-notes consumers (`DR:12780`, `DR:12895`, `DR:12955`, `DR:13033`).
- The order of the extraction analytics in `main()` (`DR:17655-17829`).
- The adaptive-loop stop conditions (`DR:13047-13083`).
- `_H2_HEADING_RE` matching H2 only, and the `parse_report_patch` None semantics (`DR:12002`, `DR:12029-12045`).
- An untagged tier weighing 0.3 (`DR:9326`).
- `planned_deep_phase_indices` (`DR:10682-10693`).

**Non-confirmed key claims.**
- *`run_incremental_report_patch` "returns the report unchanged on NO_CHANGES"* is imprecise. The report comes back unchanged only when the reply carries `<<<NO_CHANGES>>>` and no SECTION/APPEND blocks (`DR:12192-12194`). A mixed reply still applies its blocks. `RESEARCH_TOPUP_PATCH_MAX_SECTIONS` is also floored at 1 (`DR:12157`). The walkthrough's "NO_CHANGES-only" wording is correct.
- *`compute_research_quality` "a schema-valid report-judge FAIL caps the score at 0.44"* is imprecise. The cap applies to any schema-valid scorecard for which `report_passes` is False (`DR:9434-9441`). That includes a PASS verdict with sub-threshold numbers, a fatal-gap phrase or an incomplete actor audit. When the score is `None` it is set to 0.44. `degradation` is overwritten with `["research report judge failed"]`.

**Non-confirmed surprises.**
- *#3 `_quant_value_kind`*: "the project lead time family is always tagged forecast" is overstated. The text fallback runs only after the explicit label keys and `is_projection` (`DR:9790-9798`), and it reads only metric and definition. Family rows named "construction/interconnection lead time" or 项目周期 are not tagged. The rest is confirmed: "projected/forecasted/estimated" miss `\bproject\b`, and the fallback can never return `actual` (`DR:9799-9803`).
- *#15 gap-heading looseness*: the cause is misattributed. "Data gaps" matches because `re.search` is unanchored (`DR:10600`), not because of the missing leading `\b`. The missing `\b` admits words ending in "gap", such as "Stopgap". The rest is confirmed by isolated execution: "缺口" and "待补缺口" are not detected, "- None" is parsed as a gap, and `_merge_gaps` grows the caller's list past the cap.

**Non-confirmed spot-checks** (each also annotated inline above).
- `start_deep_fanout` bound: the literal call is `_model_parallel_slots(_stream_model_lease_weight())` (`DR:10527-10528`), which is equivalent today.
- The standard coverage gate also requires `depth == "standard"` (`DR:12385`).
- Parallel-phase reconciliation also runs after the fallback absorption turn (`DR:12852`).
- The evidence lane fails only when it has no sources AND (sources are required OR the pack is failure-only) (`DR:17275-17277`).
- Brief drift flags `degraded` but does not change the score (`DR:17810-17816`).

**Confirmed, with extra evidence or nuance worth keeping.**
- *Surprise #1 (judge identity, sanitized vs raw)* is confirmed and is broader than stated.
  - The sanitizer `.strip()`s the whole document (`DR:313`), so any report ending in `\n` gets a sanitized length one shorter than the raw length.
  - `finalize_report_citations` appends `References` ending in `"\n"` (`DR:4830`), and `unwrap_markdown_fence` returns text ending in `"\n"` (`DR:10116`).
  - Isolated execution showed sanitization changing all of these: `'…line.\n'` (28→27 chars), a CJK line with `（，：` (same length, different bytes), an indented list item (22→19) and a double blank line (9→7).
  - The orchestrator check compares `_judge_input` against `sha256(raw[:chars])` with `chars = len(raw)` (`backend/app/services/pipeline_orchestrator.py:3271-3289`). It runs inside `_research_contract_validation_errors` (`:3392`), which gates reuse and promotion (`:3571`, `:3633`, `:3720`, `:5047`, `:11921`).
  - The test fixture's prose ends in a trailing space (`backend/tests/test_research_contract_finalization.py:43`), which the bridge sanitizer would strip. So the fixture is not a bridge-produced identity.
  - This has still not been run end-to-end.
- *Surprise #22 (orchestrator copies)* is confirmed, and the copies have already drifted. `_research_judge_scores` and `_research_judge_passes` omit the `_judge_input.truncated` check and the actor-audit check that the bridge has (`backend/app/services/pipeline_orchestrator.py:3175-3213` vs `DR:11405-11407`, `DR:11439-11443`). Grep found no test that asserts the copies are equal.
- *Claim on `run_streamed_turn`*: the v2 post-processing (`_retry_dead_fetches`, `_merge_pending_fetches`) sits outside the `try` (`DR:10329-10331`), so an error there still propagates. `BaseException` is not caught.
- *Claim on the degenerate-loop breaker*: the segment ends on the next event after the threshold (`DR:10223-10224`). `_consec_rejected` is not reset after the correction (`DR:10303-10310`), so with defaults the hard break comes after only 8 more consecutive rejections.
- *Surprise #10 (double judge)*: the final gate at `DR:17453-17465` is a fresh LLM judgement. It can disagree with the refine loop's last verdict, and it alone decides exit 2 (`DR:17506-17536`).

**Omissions** (significant behaviour the map does not state).
1. **Patch titles are taken from the sanitized report, but the patch is applied to the raw report.** Titles come from `list_report_section_titles(safe_report)` (`DR:12161-12170`), but `apply_report_patch(report, …)` runs on the raw text (`DR:12199`). `_normalize_heading` does not apply NFKC (`DR:12010-12012`). So a heading with full-width punctuation never matches its sanitized title, and the replacement is appended as a duplicate section (`DR:12083-12087`). That passes the "not shorter" check and is adopted.
   - Isolated execution: `## 情景（Scenarios）` gave `matched=0` and a new `## 情景(Scenarios)` section at the end.
   - Chinese-language reports are affected (suspected, high likelihood).
2. **`apply_report_patch` rewrites separators in sections it did not touch.** Each segment is `rstrip("\n")`-ed and the parts are re-joined with `"\n\n"` (`DR:12082`, `DR:12091`). This inserts a blank line where none existed and collapses runs of blank lines. The docstring says the preamble and untouched sections are kept byte-for-byte (`DR:12055`).
3. **The refine top-up and triangulation-verify turns run on the main `thread_id`** (`DR:11932-11939`, `DR:12272-12279`). The final phase, the adaptive passes and the fallback phases were moved to isolated threads with compact notes specifically to stop full-history replay (`DR:12295-12302`, `DR:12889-12892`, `DR:13012`). These two late turns therefore still replay the whole main-thread checkpoint: the opening, the injected parallel notes and the tool history (inference about cost).
4. **`_judge_mean01` is more permissive than the schema check.** It accepts numeric strings, bools and extra keys (`DR:9384-9389`). A scorecard that `_validated_report_scores` rejects therefore still feeds `judge_mean` into `compute_research_quality`, yet it never triggers the FAIL cap (`DR:9430-9441`).
5. **The adaptive pass budget ignores scheduler skips.** `adaptive_passes_remaining` always subtracts all 5 fixed phases (`DR:10777`), even when `planned_deep_phase_indices` skipped scope and/or actors-and-incentives (`DR:10685-10692`). `_coverage_rounds_run` is hard-wired to 0 (`DR:12995`). Skipping phases does not free an adaptive pass.
