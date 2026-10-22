# orch-d — Orchestrator part D: research engine selection, multi-track merge, market merges, preflight, actor graph seeding, run manifest

Slice: `backend/app/services/pipeline_orchestrator.py` lines 5821-7526 (module-level helpers that sit between the research-angle constants and `class PipelineOrchestrator` at 7527). Branch `main`, read from disk 2026-10-11. All anchors are `path:line` relative to the repo root; un-prefixed `:NNNN` means `backend/app/services/pipeline_orchestrator.py`.

## Purpose & position in the pipeline

This slice holds the module-level, mostly pure helpers that the orchestrator class (`PipelineOrchestrator`, :7527) uses at four points of the research → ontology → graph → prepare → run → report pipeline:

1. **Research stage set-up.** It picks the research engine (`v3` by default, `legacy` on request or when a pinned actor policy needs it), decides how many outer research lanes run, and sizes a shared concurrency envelope across lanes and in-lane harness subagents (:5821-5981).
2. **Research stage merge.** It merges per-lane outputs (reports, `[S#]` citation namespaces, sources, actors, timeline/quant/contested lists, research quality, prediction-market snapshots and price histories) into one handoff. It also runs an optional single LLM pass that rewrites the merged opening (:5984-6741). These mergers run only in the legacy multi-lane path when `RESEARCH_GLOBAL_SYNTHESIS=false`. The default v3 engine runs one lane, and the default legacy multi-lane path uses a global synthesis that needs only `merge_sources_union`. See Control flow.
3. **Launch gate and cross-stage helpers.** `preflight_pipeline` runs cheap offline checks for API routes and CLIs (:6779). `load_research_dossier_for_simulation` lets the manual report and chat paths find a pipeline's research dossier (:6744). `_actors_to_context` turns `actors.json` into ontology-generation context (:6855).
4. **Graph stage contract.** It seeds research actors into the graph and fails closed for sealed `actor-intelligence/v1` casts. It also verifies the deterministic seed by hash and readback after seeding, after mutation, and before reuse (:7003-7231).
5. **Reproducibility and integrity.** It builds the `run.json` reproducibility manifest (:7243-7393), hashes artifacts and probes their schemas for the `handoff/manifest.json` integrity ledger (:7401-7472), and provides the simulation-reuse knob and completion probe (:7475-7519).

## Walkthrough (source order)

### Outer-lane concurrency envelope (LOOP-009)

- **`research_subagent_cap_per_track(n_tracks, global_cap, per_track_max=5)`** (:5821-5830). Splits one global harness-subagent budget across tracks: `max(1, min(lane_max, total // tracks))`, where `lane_max = clamp(per_track_max, 1, 8)` (:5827). Non-integer input returns 1 (:5828-5829). It is pure. Its only production caller is `research_lane_subagent_cap` (:5871).
- **`research_outer_track_workers(n_tracks, global_cap, model_cap=0)`** (:5833-5842). The number of outer lanes that run at the same time: `max(1, min(tracks, total, model_cap or tracks))`, where `model_cap<=0` means no model bound (:5842). Bad input returns 1. Caller: the legacy multi-lane runner (:11085), whose result sets the ThreadPoolExecutor `max_workers` (:11244).
- **`research_model_concurrency_cap(outer_workers, global_subagent_cap, configured=0)`** (:5845-5854). The provider-facing stream envelope. A positive `configured` value is used as-is. Otherwise it returns `outer_workers + global_subagent_cap`, one lead stream per active lane plus the subagents (:5854). Unparsable input returns 2 (:5853). Callers: synthesis recovery `(1, cap, cfg)` (:10885), parallel lanes (:11087), single lane (:12022).
- **`research_lane_subagent_cap(outer_workers, global_subagent_cap, per_track_max, model_concurrency)`** (:5857-5873). Computes `model_room = models // workers - 1`, which reserves one stream per lane for the lead (:5866). If `model_room <= 0` it returns **0**, which callers read as "disable harness subagents" (:5867-5868, :11098-11099, :12069-12071). Otherwise it returns `min(model_room, research_subagent_cap_per_track(workers, ...))` (:5869-5873). The per-track split uses `outer_workers`, not the requested track count.
  - Defaults probed by running the extracted function source in a scratch sandbox: legacy 3 lanes → 3 workers, 12 model streams, 3 subagents per lane. v3 single lane → 10 streams, 5 subagents. An explicit `RESEARCH_GLOBAL_MODEL_CONCURRENCY=4` with 3 lanes → 0 subagents, so harness subagents are disabled.
- **`research_dual_track_for_outer_lane(lane_index, enabled)`** (:5876-5882). Returns True only for lane index 0 when dual-track is enabled. Only the broad baseline lane runs the Track-B actor/ontology dossier (caller :11224-11225). Bad input returns False.

### Research engine selection (engine v3)

- **Constants** (:5888-5903). `RESEARCH_ENGINE_V3="v3"`, `RESEARCH_ENGINE_LEGACY="legacy"`. `_RESEARCH_ENGINE_ALIASES` maps `v3`/`linear` → v3 and `legacy`/`deerflow`/`agentic` → legacy (:5895-5901). A process-wide set and lock make sure each unknown value is warned about only once (:5902-5903). The alias sets match the bridge's `_V3_ENGINE_NAMES={"v3","linear"}` and `_LEGACY_ENGINE_NAMES={"legacy","deerflow","agentic"}` (`deerflow_bridge/deerflow_research.py:16374-16375`).
- **`resolve_research_engine(raw=None)`** (:5906-5934). `raw=None` reads `Config.RESEARCH_ENGINE` (default `'v3'`, `backend/app/config.py:1187`). The value is stripped and lowercased. Empty → v3 (:5921-5922). A known alias → canonical (:5923-5925). Unknown → logs one warning per distinct value per process, truncated to 64 chars (:5926-5933), and returns **v3** (:5934). It never raises. Callers: admission policy pinning (:843), the subprocess env passed to the child (:2298-2299; evidence-only and synthesis-manifest invocations are forced to legacy at :2295-2297), and `research_engine_for_run` (:5952).
- **`research_engine_for_run(options)`** (:5937-5952). If `options["actor_intelligence_policy_v1"]` is a dict with `required is True`, it returns **legacy**, because only the legacy engine produces the sealed actor plane (:5949-5951). Otherwise it returns `resolve_research_engine()` (:5952). The `research_engine` field that admission writes into the policy (:849) is **not** read here. Callers: the research stage (:11983) and the parallel-lane runner (:11080).
- **`research_outer_track_count(configured_tracks, engine, *, pipeline_id="")`** (:5955-5981). Parses `max(1, int(configured or 3))`; a parse error gives 3 (:5968-5971). For a non-v3 engine it returns that value unchanged and does not clamp it to the 3 defined angles. The clamp happens later through `_RESEARCH_TRACK_ANGLES[:max(1,n)]` at :11077. For v3 it always returns **1**, and logs an info line when it overrides a configured value above 1 (:5972-5981). Caller: :11984, with `Config.RESEARCH_PARALLEL_TRACKS` (default 3, `backend/app/config.py:1196`).

### Track merge primitives (PAR-2)

- **`_track_tier_rank(tier)`** (:5984-5990). The regex `[sS]([1-4])` matches at the start of the string: `S1` → 1 … `S4` → 4. Anything else → 9, the worst rank. A lower rank is a better tier.
- **`_track_norm_url(url)`** (:5993-5997). Strips whitespace, strips a trailing `/`, lowercases. Used only as a dedup key; it never rewrites the stored URL.
- **`merge_track_reports(labeled_reports)`** (:6000-6014). Joins non-empty reports as `# Track N: <angle title>\n\n<body>` with `\n\n`. Numbering counts only non-empty tracks, so it stays contiguous. Pure. Callers: :6135 (deterministic report), :11647 (reports), :11648 (dossiers).

### W9-7 opening dedup and LLM reconcile

- **Regexes** (:6022-6024). `_TRACK_H1_RE` matches `^# Track (\d+): (.+?)$`. `_REPORT_HEADING_RE` matches H1-H3 only. `_OPENING_CITATION_RE` matches `[S#]`.
- **`_normalise_report_heading(title)`** (:6027-6032). Casefolds; strips markdown emphasis characters, leading section numbers or roman numerals, and trailing punctuation; collapses separators to spaces.
- **`_report_opening_kind(title)`** (:6035-6071). Classifies a heading as `"executive"` (an exact alias set plus a substring check on `"executive summary"`, including Chinese aliases such as 摘要 and 执行摘要, :6045-6063), `"orientation"` (reader-guide aliases plus substring checks on `how to read this dossier/report`, :6051-6070), or `None`. Matching is exact and bounded on purpose, so a heading like "Summary of risks" is not classified (probed).
- **`_opening_sections(report_md, kind=None)`** (:6074-6095). For each classified heading, the section runs until the next heading of the same or a higher level (:6085-6088). Returns `{kind, start, end, body}`. It does not skip fenced code blocks.
- **`_strip_opening_sections(report_md, kinds)`** (:6098-6104). Deletes the matching spans from last to first and collapses 3+ newlines.
- **`_first_opening_body(tracks, kind)`** (:6107-6118). Returns the first section body, in track order, with at least 80 non-whitespace chars for executive or 20 for orientation (:6110). If none qualifies, it returns the first non-empty body.
- **`_deterministic_track_report(tracks)`** (:6121-6141). Builds a canonical `## Executive Summary` and/or `## How to Read This Dossier` from the first substantive bodies. It then strips both opening kinds from every track, runs `merge_track_reports`, and applies `demote_track_headings`. Returns `(full_text, opening_text)`.
- **`_opening_citation_audit(candidate, fallback, merged_report)`** (:6144-6162). Passes only when the candidate cites no `[S#]` absent from the merged report, cites every marker the deterministic opening cites, and has at least as many distinct markers (:6157-6161).
- **`_track_title_en(title)`** (:6165-6168). Extracts the trailing parenthesised English title, e.g. `基线证据扫描 (Base Evidence Sweep)` → `Base Evidence Sweep`.
- **`demote_track_headings(md)`** (:6171-6179). Rewrites `# Track N: <title>` to `## Part N — <english title>`. Other text is unchanged.
- **`extract_exec_summary(report_md, max_chars=4000)`** (:6182-6192). Returns the first executive section body, cut to `max_chars`. If there is none, it returns the first `max_chars` of the stripped report.
- **`reconcile_track_reports(merged_report, labeled_reports, llm=None, *, max_prompt_chars=30000)`** (:6195-6278). Returns `(report, audit)`.
  - It filters out empty tracks and builds the deterministic fallback first (:6208-6210).
  - If fewer than 2 tracks remain, it returns the **raw `merged_report` unchanged** with `reason="tracks<2"`, not the deterministic fallback (:6217-6219).
  - Prompt budget: `per = max(2000, (max_prompt_chars-2000)//len(tracks))` chars of executive summary per track; the whole payload is cut to `max_prompt_chars` (:6220-6224). [verifier: not strictly "executive summary only": for a track with no (or an empty) executive section, `extract_exec_summary` sends the first `per` chars of the whole track report instead (:6186-6192, :6223)] The Chinese prompt (:6225-6239) asks for one `## Executive Summary` plus `### Cross-track disagreements`, preserving `[S#]` markers.
  - **LLM call:** `LLMClient().chat(..., temperature=0.2, max_tokens=4000)` (:6240-6244). This uses the report/simulation provider (`Config.LLM_PROVIDER`), not the research model.
  - It rejects and falls back to deterministic output when: the output is shorter than 200 chars or contains `_LLM_ERROR_MARKERS` (:6246-6247, markers at :2748); the output has more or fewer than one executive section or more than one orientation section (:6248-6258); the citation audit fails (:6259-6262); or any exception is raised (:6277-6278).
  - On success it swaps only the deterministic opening for the LLM opening and keeps the deterministic evidence body (:6266-6276). Audit keys: `applied`, `reason`, `fallback`, `opening_chars`, `tracks`, `citation_audit`, `opening_sections`.

### Sources, citations, lists, actors, quality

- **`merge_sources_union(track_sources)`** (:6281-6309). Dedups by normalized URL and keeps first-seen order. When the same URL appears again it keeps the best tier (:6304-6305) and backfills empty fields from later rows (:6306-6308). A dict row without a URL is kept as is (:6296-6298). **Non-dict rows are dropped** (:6293-6294), although the docstring at :6284 says they are kept. Caller: :11277. This is the only merge primitive the default legacy global-synthesis path uses.
- **`normalize_track_report_citations(report, track_sources, merged_sources)`** (:6318-6385).
  - Builds a global URL→1-based index over `merged_sources` (:6330-6334). Builds a local tag→URL map, first by position in the track's `sources` (:6335-6339), then overridden by `[S#] … https://…` lines in the track's References section (:6346-6356).
  - The References section starts at a `References|参考来源|参考文献` H1-H3 heading and ends at the next H1-H3 heading. It is removed from the body.
  - Each `[S#]` outside fenced code is remapped to `[S<global>]`. A marker that cannot be resolved is deleted (:6372-6380).
  - Every non-fence line then has whitespace before punctuation removed, and **every run of 2+ spaces or tabs collapsed to one space, including leading indentation** (:6383).
  - Returns `(text, {markers, remapped, stripped})`. Caller: :11640.
- **`append_merged_references(report, merged_sources)`** (:6388-6405). Appends `## References` with one `- [S<n>] <title> — <url>` row for each cited, in-range marker. Returns the report unchanged when nothing is cited. Caller: :11768.
- **`strip_exec_summary_section(report_md)`** (:6408-6410). Wraps `_strip_opening_sections(..., {"executive"})`. It has **no callers** anywhere in the repo, including tests.
- **`merge_list_dedup(track_lists)`** (:6413-6430). Concatenates the lists and dedups by `json.dumps(sort_keys=True)`, falling back to `repr` as the key. Non-list inputs are skipped. Callers: timeline, quantitative and contested (:11689-11691).
- **`merge_actors_objs(track_actor_objs)`** (:6433-6466). The base is the first dict's scalar keys (everything except `actors`, `relationships`, `key_events`), so any `actor_intelligence_contract` is copied from the first track. It concatenates `actors`, `relationships` and `key_events` across tracks, then calls `utils.actors.reconcile_cast` directly (:6462-6463). If that raises, it returns the un-deduplicated union (:6465-6466). With no dict input it returns `(None, {"merged":[], "n_before":0, "n_after":0})`. Caller: :11650.
- **`merge_research_quality(track_metas)`** (:6469-6492). The result is the `research_quality` block of the track with the **minimum** numeric `score`, plus a `per_track` list and `merged_from_tracks=len(track_metas)`. Caller: :11693.
- **`_source_tier_histogram(sources)`** (:6495-6503). Returns `{s1_count..s4_count, s_unknown}`. Caller: merged `meta.source_tiers` (:11719).
- **`_SOURCE_TIER_PENALTY_WEIGHTS` / `_source_tier_penalty_weight(key)`** (:6509-6526). Weights are s1 1.0, s2 0.7, s3 0.4; s4, unknown and any other key 0.2. The function accepts both `s1` and `s1_count` key shapes (IF-10 fix). Caller: the confidence-penalty `source_tier_mix` component, `round(max(0, 1 - wsum/tot) * 0.1, 3)` (:10682-10699).

### Prediction-market merges

- **`pick_freshest_markets(track_markets)`** (:6529-6546). Picks the snapshot with the largest `as_of` string among those with non-empty `markets`; otherwise the first dict; otherwise None. It is **not called in production**: only tests reference it, and `merge_market_snapshots` replaced it.
- **`merge_market_snapshots(track_markets, *, max_total=20, max_per_event=3)`** (:6549-6712). Takes the union of the per-track registries.
  - **Status totals.** Per track it sums `attempted_query_count`, falling back to `query_count` and never counting both (:6591-6597), plus `successful_query_count`, `transport_failure_count`, `inflight_timeout_count` and `tool_observation_count` (:6598-6604). It counts each `empty_reason` (:6605-6607).
  - **Candidate counts.** `candidate_count` is `status.candidate_count`, or the row count if missing (:6616-6621). `raw_candidate_count` is `status.raw_candidate_count`, or the normalized count if missing (:6622-6626).
  - **Union rule.** Rows are keyed by `market_id`; rows without one are skipped. A row whose snapshot `as_of` is newer **or equal** overwrites the existing fields, and every sighting appends `{track, as_of}` to `track_provenance` (:6627-6639).
  - **Ranking and caps.** Rows are ranked by relevance_score (desc), then volume (desc), then `market_id`; NaN and non-numeric values count as 0 (:6641-6655). At most `max_total` rows are taken, with at most `max_per_event` per `event_title`, or per `market_id` when there is no title (:6656-6666).
  - **`status.state`** takes the first of: `markets_selected`, `all_candidates_irrelevant`, `transport_failure` (every attempted query failed in transport), `inflight_timeout`, `partial_transport_failure`, `verified_empty` (:6673-6685).
  - **Return.** `{as_of: max snapshot as_of, source:"polymarket", registry_sources, queries (case-insensitive dedup), markets, no_relevant_markets, status}` (:6704-6712). Returns None when no input is a dict. Caller: :11694-11698, which passes `PREDICTION_MARKETS_MAX` and `PREDICTION_MARKETS_MAX_PER_EVENT`.
- **`merge_market_price_histories(track_histories, selected_market_ids)`** (:6715-6741). Keeps series only for the selected market IDs. Points must parse as `t=int(float)>0` and `0<=p<=1`. When two tracks have the same timestamp, the later track in iteration order wins (:6737). Output is sorted by `t`. Caller: :11704.

### Cross-stage helpers

- **`load_research_dossier_for_simulation(simulation_id)`** (:6744-6776). Scans `PipelineManager.list_pipelines()`, which is sorted newest first (:1220), and loads each pipeline. For the first one whose `simulation_id` matches, it reads `handoff/actors.json`, `research_report.md`, `actor_dossier.md` and `sources.json`, and builds `situation_brief(actors)`. Returns `{situation_brief, actors, sources, research_report, actor_dossier}`, all None when nothing matches. Any exception is swallowed (:6774-6775). Callers: `backend/app/api/report.py:378` (POST `/api/report/generate`), `backend/app/api/report.py:1551` (POST `/api/report/chat`), `backend/scripts/model_comparison.py:162`.
- **`preflight_pipeline(mode="full", model=None)`** (:6779-6852). Returns human-readable errors (Chinese strings); an empty list means ready. It makes no network calls.
  1. Full mode only (:6796-6813): the graph backend. `auto`/`falkordblite` need `redislite.async_falkordb_client`. `auto` also passes when `kuzu` is importable or `FALKORDB_HOST` is set. `kuzu` needs the `kuzu` package. `falkordb` (external) is not checked. [verifier: `importlib.util.find_spec('redislite.async_falkordb_client')` imports the parent package first, so when `redislite` itself is not installed it raises `ModuleNotFoundError` instead of returning None (verified with a missing-parent probe). The friendly "图谱后端未安装" error and the kuzu/FALKORDB_HOST fallbacks are then unreachable and preflight raises (:6800-6811). `falkordblite` is a hard dependency (`backend/pyproject.toml:29`), so this only affects broken environments]
  2. Full mode only (:6816-6823): `PROVIDER_META[LLM_PROVIDER].needs_key` requires `LLM_API_KEY`; `claude-cli` requires `claude` on PATH; `codex-cli` requires `codex` on PATH.
  3. Always (:6826-6831): `Config.DEERFLOW_DIR` must exist and contain `deerflow_research.py`. This one script serves both engines.
  4. Always (:6834-6850): research model credentials. The model is `(model or Config.DEERFLOW_MODEL or 'claude').lower()`. Models in `Config.DEERFLOW_KEY_ENV` (minimax/deepseek/qwen/glm/kimi, `backend/app/config.py:1546-1549`) need that env var. `claude` needs `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `~/.claude/.credentials.json`, or `claude` on PATH. `codex` needs `~/.codex/auth.json` or `codex` on PATH.
- **`_actors_to_context(actors)`** (:6855-7000). Builds the `additional_context` for `OntologyGenerator`. Returns None for a non-dict or an empty roster.
  - **Sealed v1 cast** (`actor_intelligence_contract.schema_version == "actor-intelligence/v1"`, :6864-6966). Header line, then up to 25 actors. Each actor gets identity (`name <actor_id> type= simulation_tier= aliases=` up to 8 aliases). For each of the 17 `ACTOR_INTELLIGENCE_DIMENSIONS` (:114-132) it adds only the first claim that has `claim_[0-9a-f]{20}`, a valid `claim_sha256`, and at least one support entry with `source_id`, `receipt_id` and a valid `content_sha256` (:6911-6930). Claim text is cut to 360 chars and tagged with evidence/confidence/status/horizon/date provenance and source IDs. The output stops before exceeding 12000 chars (:6962-6963). It deliberately leaves out the flat role, stance and brief fields.
  - **Legacy cast** (:6968-7000). Up to 25 `- name（type）：role 立场：stance` lines, up to 10 hot topics, `situation_brief_block`, and up to 30 relationship lines labelled through `REL_LABEL`.
  - Caller: :12337. When `ONTOLOGY_FROM_DOSSIER` is set, `ontology_seed_block` is appended (:12338-12343).

### Actor graph seed contract

- **`_expected_actor_seed_count(actors)`** (:7003-7047). Counts the triplet writes that `seed_actors` should report.
  - Sealed v1: one identity edge per named actor, plus `extract_relationship_rows`, plus aliases whose `normalize_name` differs from the actor name (:7012-7027).
  - Legacy: relationships, plus actors whose exact name string is not a relationship endpoint, plus distinct aliases (:7028-7047). [verifier: not "distinct" — like the v1 branch it counts every non-blank alias string whose `normalize_name` differs from the actor's own name, with no de-duplication across aliases or actors (:7037-7046)] The caller enforces the count only for v1 (:7209, :7222), so the legacy result is never used.
- **`_actor_graph_seed_manifest_sha256(manifest)`** (:7050-7063). SHA-256 of `json.dumps(manifest minus manifest_sha256, ensure_ascii=False, sort_keys=True, separators=(",",":"))`. Raises RuntimeError on a non-dict. This matches graph_builder's `_canonical_json` (`backend/app/services/graph_builder.py:85-96`) except that graph_builder also passes `default=str`.
- **`_load_actor_graph_seed_manifest(state)`** (:7066-7077). Reads `state.artifacts["actor_graph_seed_manifest"]`, or `handoff/actor_graph_seed_manifest.json` if that is unset. Returns a dict or None.
- **`_validate_actor_graph_seed_contract(builder, graph_id, actors, *, phase, expected_manifest=None, state=None, persist=False)`** (:7080-7181).
  - Returns None for a cast that is not sealed v1 (:7098-7099).
  - Rebuilds the manifest with `build_actor_graph_seed_manifest(graph_id, actors)` (`backend/app/services/graph_builder.py:510`). Requires `schema_version=="actor-graph-seed-manifest/v1"`, `strict is True`, matching `graph_id`, and a valid self-hash (:7100-7120).
  - If `expected_manifest` is given, its self-hash must be valid and equal the current hash (:7121-7130).
  - Calls `builder.validate_actor_graph_seed_readback(graph_id, manifest)`, a graph DB read. The audit must have `schema_version=="actor-graph-seed-readback/v1"`, `status=="ok"`, `strict is True`, and matching graph_id, manifest_sha256 and `expected_counts` (:7131-7156).
  - Side effects: writes `state.options["graph_seed_manifest_sha256"]` and `state.options["graph_seed_readback"][phase]` (:7158-7165). With `persist=True` (requires state) it atomically writes `handoff/actor_graph_seed_manifest.json` and records `state.artifacts["actor_graph_seed_manifest"]` (:7166-7180).
  - Every failure raises `RuntimeError("sealed actor-intelligence/v1 graph seed … :<phase>")`.
  - Phases and callers: `reuse` (:12408, which falls back to a rebuild on any exception), `post_seed` with persist (:12527), `post_mutation` against the post_seed manifest (:12644).
- **`_seed_research_actors(builder, graph_id, actors, *, valid_at)`** (:7184-7231).
  - Falsy actors → None.
  - `required = _is_sealed_actor_intelligence_v1(actors)`.
  - If `GRAPH_SEED_FROM_ACTORS` is off: raises when required, else returns None (:7202-7207).
  - When required and `expected<=0`: raises (:7209-7212).
  - Calls `builder.seed_actors(graph_id, actors, valid_at=...)`. An exception raises when required, and is only logged as a warning (returning None) for legacy (:7213-7221).
  - When required, a result that is a bool, not an int, or `< expected` raises "incomplete" (:7222-7230). [verifier: for a legacy cast, `expected<=0` and a bool/non-int/short result are not checked at all; `seed_actors`' return value is passed through unchanged (:7208-7231). Only "seeding disabled" and "seed_actors raised" return None for legacy]
  - Returns the seeded count. Caller: :12524.

### Run manifest (I-8-1) and integrity helpers (I-4-3)

- **`_repo_git_sha()`** (:7243-7255). Runs `git -C <repo root> rev-parse HEAD` with a 5 s timeout. Returns None on failure.
- **`_deerflow_ref()`** (:7258-7273). None if `DEERFLOW_DIR` is missing. `"vendored"` if it has no `.git`; the checked-out `deer-flow/` has none and is gitignored, `.gitignore:84`. Otherwise the result of `git rev-parse HEAD` (5 s timeout), or `"vendored"` on failure.
- **`_capture_key_packages()`** (:7276-7293). `importlib.metadata` versions of graphiti-core, sentence-transformers, openai, flask, redislite, kuzu and falkordb. Returns None if none resolve.
- **`_calendar_mode()`** (:7296-7303). True when `Config.SIM_TEMPORAL_MODE == "calendar"`; the default is `'calendar'` (`backend/app/config.py:1067`). Also used at :8563, :12810, :12878, :12980.
- **`_build_run_manifest(state)`** (:7306-7379). Builds the run.json skeleton:
  - Top level: `schema_version` (PIPELINE_SCHEMA_VERSION=2, :245), `pipeline_id`, `mode`, `created_at`, `updated_at`, `repo_git_sha`, `deerflow_ref`, `redacted_flag: True`.
  - `resolved.research`: `{model, depth, timeout_s, language, actor_intelligence_policy}`. `timeout_s` is `Config.deerflow_depth_budget(depth)`, falling back to the raw tier dict (:7317-7323).
  - `resolved.ontology/graph/report`: `{provider:None, model_name:None}`, filled at stage entry.
  - `resolved.simulation`: `{max_agents, max_rounds, total_rounds:None, recsys_wired, sim_graph_feedback}`. In calendar mode `max_rounds` is only an explicit `options.max_rounds` (:7326-7329).
  - `graph`: `{backend, embed_model, embed_dim, reranker}`.
  - `env_fingerprint`: `{python, package_versions?}`. `package_versions` is added only when `MANIFEST_CAPTURE_VERSIONS` is on.
  - Callers: `_write_run_manifest` (:10385) and `_update_manifest` (:10411), both wrapped in `redact_secrets`.
- **`_python_version_string()`** (:7382-7385). Returns `major.minor.micro`.
- **`_current_provider_pair()`** (:7388-7393). Returns `{provider: Config.LLM_PROVIDER, model_name: Config.LLM_MODEL_NAME}`. Used by `_update_manifest` for ontology/graph/report (:10413-10414).
- **`_sha256_file(path, chunk_size=1MiB)`** (:7401-7417). Streaming SHA-256; None on an OS or value error. Widely reused in the orchestrator (e.g. :2222, :3343, :9866).
- **`_probe_artifact_schema(name, path)`** (:7420-7449). A missing or empty file → False. For `.json`: an unparseable file → False; `actors.json` needs a dict with an `actors` list; `ontology.json` needs non-empty `entity_types`; `communities.json` needs a list; any other JSON must be a dict or list. Non-JSON files pass when non-empty. An unexpected exception → True.
- **`_manifest_entry_for(name, path, stage)`** (:7452-7472). Returns None when the file is missing or zero bytes. Otherwise `{path, sha256, bytes, produced_by_stage, produced_at, schema_ok}`. Callers: :3463 (human-edit refresh), :9750 (per-stage ledger), :10118 (run_summary).
- **`_sim_reuse_completed_enabled()`** (:7475-7487). A non-blank env `SIM_RESUME_REUSE_COMPLETED` wins, and only `1/true/yes/on` count as true. Otherwise `Config.SIM_RESUME_REUSE_COMPLETED` (default true, `backend/app/config.py:596`). Caller: :9995.
- **`_actions_simulation_end_present(path, tail_bytes=262144)`** (:7490-7519). Reads the last 256 KiB and scans lines in reverse for a JSON line with `event_type=="simulation_end"`. Returns False on any OS error. Caller: :9969.

## Control flow

**Admission and engine.** Admission → `admission_actor_intelligence_policy_v1` (:832) → `resolve_research_engine()` (:843). This pins `required = DEERFLOW_DUAL_TRACK and engine==legacy` (:847) and stores the policy in `state.options["actor_intelligence_policy_v1"]`.

**Research stage** (:11979-12075):

1. `_research_engine = research_engine_for_run(state.options)` (:11983) → `_n_tracks = research_outer_track_count(Config.RESEARCH_PARALLEL_TRACKS, engine)` (:11984).
2. **One lane** (always for v3): compute `research_model_concurrency_cap(1, …)` and `research_lane_subagent_cap(1, …)` (:12022-12032), then call `DeerFlowResearchRunner.run(..., research_engine=_research_engine)` (:12047-12075). Inside the runner, `env["RESEARCH_ENGINE"]` is set from `resolve_research_engine(research_engine)` (:2295-2301). For v3 the child also gets `DEERFLOW_RESEARCH_TIMEOUT=<effective budget>` (:2302-2307).
3. **More than one lane** (legacy only): `_run_parallel_research_tracks` (:11060).
   - Angles are `_RESEARCH_TRACK_ANGLES[:n]` (:11077; definitions at :5812-5818).
   - Compute `research_outer_track_workers` → `research_model_concurrency_cap` → `research_lane_subagent_cap` (:11085-11097).
   - Run `ThreadPoolExecutor(max_workers=outer_workers)` (:11243). Each lane passes `dual_track=research_dual_track_for_outer_lane(idx, …)` and `evidence_only=global_synthesis` (:11224-11231).
   - After the lanes: `merge_sources_union` (:11277).
     - **Global synthesis** (`RESEARCH_GLOBAL_SYNTHESIS` default true, `backend/app/config.py:1200`): requires lane 0, then runs one legacy synthesis and returns early (:11279-11634). The other merge primitives in this slice are **not** used on this path.
     - **No global synthesis**, in order: `normalize_track_report_citations` per track (:11638-11643) → `merge_track_reports` for reports and dossiers (:11647-11648) → `merge_actors_objs` (:11650) → `merge_list_dedup` ×3 (:11689-11691) → `merge_research_quality` (:11693) → `merge_market_snapshots` (:11694) → `merge_market_price_histories` (:11704) → `_source_tier_histogram` (:11719) → if at least 2 lanes survived: `reconcile_track_reports` (if `RESEARCH_TRACK_RECONCILE`) or `_deterministic_track_report` (:11744-11763) → `append_merged_references` (:11768) → atomic writes into `handoff/` (:11771-11792).

**Ontology stage.** `_actors_to_context(actors)` (:12337).

**Graph stage.**
- Reuse path: `_load_actor_graph_seed_manifest` → `_validate_actor_graph_seed_contract(phase="reuse")` (:12402-12426).
- Build path: `_seed_research_actors` (:12524) → `_validate_actor_graph_seed_contract(phase="post_seed", persist=True)` (:12527) → text ingest, resolve and prune → `_validate_actor_graph_seed_contract(phase="post_mutation", expected_manifest=…)` (:12644).

**Run manifest.** `_write_run_manifest` at pipeline start (:10374-10391) and `_update_manifest` at each stage entry, e.g. :12391 (:10393-10426), both call `_build_run_manifest`. [verifier: `_update_manifest` is not called at every stage entry. It runs at ontology (:12309), graph (:12391) and report (:13187) entry, and during RUN when the round total is observed (:13041-13042). It is not called for research or prepare. It calls `_build_run_manifest` only when run.json is missing or unreadable (:10408-10411). `_write_run_manifest` is called once, at :11897]

**API launch gates.** `preflight_pipeline` is called from:
- POST `/api/research/run` (`backend/app/api/research.py:101`)
- `/resume` (`backend/app/api/research.py:154`, which passes `mode` only)
- `/continue` (`backend/app/api/research.py:192`)
- `/scenario` (`backend/app/api/research.py:233`)
- GET `/api/research/preflight` (`backend/app/api/research.py:385`)
- POST `/api/v1/run` (`backend/app/api/sdk.py:128`)
- `backend/scripts/preflight.py:107` and `backend/scripts/batch_runs.py:424`

## Data & artifacts

- **Per-lane inputs** (legacy multi-lane, read by the merge path): `handoff/track_<k>/{research_report.md, actor_dossier.md, actors.json, sources.json, timeline.json, quantitative.json, contested.json, meta.json, prediction_markets.json, market_price_history.json}` (:11176, :11690-11705).
- **Merged outputs** written by the caller from slice results: `handoff/research_report.md`, `actor_dossier.md`, `actors.json`, `sources.json`, `timeline.json`, `quantitative.json`, `contested.json`, `prediction_markets.json` (`{as_of, source, registry_sources, queries, markets[+track_provenance], no_relevant_markets, status{attempted, state, snapshot_count, raw_candidate_count, candidate_count, selected_input_count, unique_candidate_count, selected_count, empty_reason_counts, query_count, successful_query_count, transport_failure_count, inflight_timeout_count, tool_observation_count, attempted_query_count, empty_reason}}`), `market_price_history.json` (`{market_id: [{t, p}]}`), `meta.json` (`research_quality` minimum block with per_track and degraded/degradation, `source_tiers` histogram, `sources_count`, `parallel_research.citation_remap`, `actor_dossier_compaction`, `prediction_market_*`) (:11709-11792).
- **`handoff/actor_graph_seed_manifest.json`**: graph-owned manifest (`schema_version`, `strict`, `graph_id`, contract digests, actors/aliases/identity_edges/relationships projections, seed_nodes/seed_edges, `expected_counts`, `seed_nodes_sha256`, `seed_edges_sha256`, `manifest_sha256`; see `backend/app/services/graph_builder.py:470-506`). Written by :7179 and registered as a GRAPH-stage artifact (:9527-9530).
- **`uploads/pipelines/<id>/run.json`** (`PipelineManager.manifest_path`, :915-917). Contents are listed at :7331-7378 and redacted by `backend/app/utils/security.py:35-53`, which masks any key matching `api_key|secret|password|token|credential|key…`. The comment at :7370-7372 explains why the field names avoid those patterns.
- **`handoff/manifest.json`** integrity ledger entries: `{path, sha256, bytes, produced_by_stage, produced_at, schema_ok}` (:7465-7472; path at :1108-1110).
- **In-memory state:**
  - `state.options["graph_seed_manifest_sha256"]`, `["graph_seed_readback"][phase]` (:7159-7165)
  - `["research_track_reconcile"]` (:11759)
  - `["graph_seeded_edges"]` (:12537)
  - `["resumed_stage_validation"]` (:12400, :12418)
  - `state.artifacts["actor_graph_seed_manifest"]` (:7180) and `["run_manifest"]` (:10389)
  - The module-level set `_UNKNOWN_RESEARCH_ENGINES_WARNED` (:5902)

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `RESEARCH_ENGINE` | `v3` | Engine; aliases `linear`/`legacy`/`deerflow`/`agentic`; unknown → v3 plus one warning | `backend/app/config.py:1187`, :5906-5934 |
| `RESEARCH_PARALLEL_TRACKS` | 3 (≥1) | Outer lanes for legacy only; v3 forces 1; effectively capped at 3 angles | `backend/app/config.py:1196`, :5955-5981, :11077 |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` | 9 | Shared harness-subagent envelope | `backend/app/config.py:1205`, :11083 |
| `RESEARCH_SUBAGENTS_PER_TRACK_MAX` | 5 (1..8) | Per-lane subagent ceiling | `backend/app/config.py:1207`, :11095 |
| `RESEARCH_GLOBAL_MODEL_CONCURRENCY` | 0 (= derived `workers + subagents`) | Explicit provider stream envelope; small values disable subagents | `backend/app/config.py:1212`, :5845-5873 |
| `DEERFLOW_DUAL_TRACK` | true | Track-B dossier on lane 0 only; pins the actor policy as `required` only for legacy | `backend/app/config.py:1228`, :5876, :844-851 |
| `DEERFLOW_SUBAGENTS` | true | Harness subagents, if lane cap > 0 | `backend/app/config.py:1168`, :11098 |
| `RESEARCH_GLOBAL_SYNTHESIS` | true | Multi-lane → evidence-only lanes plus one synthesis, which bypasses most merges | `backend/app/config.py:1200`, :11081 |
| `RESEARCH_TRACK_RECONCILE` | true | LLM opening reconcile vs. deterministic dedup | `backend/app/config.py:525`, :11745 |
| `PREDICTION_MARKETS_MAX` (legacy alias `ODDPOOL_MAX_MARKETS`) | 20 | `max_total` for the market union | `backend/app/config.py:1425`, :11696 |
| `PREDICTION_MARKETS_MAX_PER_EVENT` | 3 | Per-event cap; `<=0` means unlimited [verifier: not via the only production caller. :11697 passes `int(... or 3)`, so a configured `0` becomes 3; only a negative value disables the cap. Likewise `PREDICTION_MARKETS_MAX=0` becomes 20 at :11696] | `backend/app/config.py:1431`, :6663 |
| `GRAPH_BACKEND` / `FALKORDB_HOST` | `auto` / None | Preflight graph checks | `backend/app/config.py:1019,1031`, :6799-6813 |
| `LLM_PROVIDER` / `LLM_API_KEY` | `claude-cli` | Preflight provider and CLI checks; reconcile LLM | `backend/app/config.py:750`, :6817-6823 |
| `DEERFLOW_DIR` | `<repo>/deer-flow` | Preflight script existence; `deerflow_ref` | `backend/app/config.py:1148`, :6826, :7261 |
| `DEERFLOW_MODEL` | `claude` | Preflight research credentials; run.json model | `backend/app/config.py:1156`, :6834, :7314 |
| `GRAPH_SEED_FROM_ACTORS` | true | Actor seeding; off + sealed v1 → RuntimeError | `backend/app/config.py:1236`, :7202 |
| `RECORD_RUN_MANIFEST` | true | Write and update run.json | `backend/app/config.py:426`, :10380 |
| `MANIFEST_CAPTURE_VERSIONS` | false | Package versions in run.json | `backend/app/config.py:472`, :7375 |
| `SIM_TEMPORAL_MODE` | `calendar` | `_calendar_mode()`: run.json `max_rounds` semantics | `backend/app/config.py:1067`, :7303 |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` | run.json depth; `timeout_s` via `deerflow_depth_budget` (×1.5 when dual/subagents/fanout) | `backend/app/config.py:1159,1559-1577`, :7313-7323 |
| `SIM_RESUME_REUSE_COMPLETED` | true (a non-blank env value overrides Config) | Reuse a completed simulation | `backend/app/config.py:596`, :7481-7485 |
| `ONTOLOGY_FROM_DOSSIER` | true | Appends the ontology seed block after `_actors_to_context` | `backend/app/config.py:379`, :12338 |
| Env `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `MINIMAX/DEEPSEEK/DASHSCOPE/ZHIPUAI/KIMI_API_KEY` | — | Preflight research credentials (only checked for presence) | :6837-6847, `backend/app/config.py:1546-1549` |

## External calls

- **LLM:** `LLMClient().chat` in `reconcile_track_reports` (:6241-6244), one call per merge with ≥2 surviving lanes. Uses the report/simulation provider.
- **Subprocess:** `git -C <repo> rev-parse HEAD` (:7248-7251) and `git -C <DEERFLOW_DIR> rev-parse HEAD` (:7266-7269), each with a 5 s timeout.
- **PATH lookups and file stats (no network):** `shutil.which('claude'|'codex')` and the credential files `~/.claude/.credentials.json` and `~/.codex/auth.json` (:6820-6850). `importlib.util.find_spec` for graph backends (:6800-6812).
- **Graph DB (through GraphBuilderService):** `builder.seed_actors` writes (:7214) and `builder.validate_actor_graph_seed_readback` reads (:7138). `build_actor_graph_seed_manifest` is pure (`backend/app/services/graph_builder.py:510-526`).
- **Filesystem:** reads pipeline state and handoff files (:6757-6772), writes atomically through `utils.atomic.write_json_atomic` (:7169-7179), streams hashes (:7401-7417).
- There are no HTTP or provider calls in this slice apart from the LLM call above.

## Cross-module edges

- **Inbound (outside this file):**
  - `backend/app/api/research.py:28,101,154,192,233,385`, `backend/app/api/sdk.py:47,128`, `backend/scripts/preflight.py:62,107`, `backend/scripts/batch_runs.py:76,424` → `preflight_pipeline`.
  - `backend/app/api/report.py:16,378,1551`, `backend/scripts/model_comparison.py:60,162` → `load_research_dossier_for_simulation`.
  - `report_agent.py:2574,9022` and `simulation_config_generator.py:1353` mention it as a "same pattern" in docstrings only.
- **Inbound (same file):** see Control flow (:843, :2298, :10385-10414, :10693, :11080-11768, :11983-12032, :12337, :12404-12650, :9750, :9869, :9969, :9995, :3463).
- **Outbound:**
  - `utils.actors.reconcile_cast` (:6462), `extract_relationship_rows` / `situation_brief_block` / `situation_brief` / `REL_LABEL` / `normalize_name` (imported at :69-76)
  - `utils.llm_client.LLMClient` (:6241)
  - `services.graph_builder.build_actor_graph_seed_manifest` (:53, :7101) and the `GraphBuilderService` instance methods `seed_actors` and `validate_actor_graph_seed_readback`
  - `utils.atomic.write_json_atomic` (:7169)
  - `PipelineManager.list_pipelines` / `load` / `handoff_dir` (:6757-6764)
  - Module helpers outside the slice: `_read_json`, `_read_text` (:2925-2940), `_is_sealed_actor_intelligence_v1` (:3906), `_actor_explicit_simulation_tier` (:3950), `_actor_valid_sha256` (:4103), `_LLM_ERROR_MARKERS` (:2748), `_utcnow` (:293)
  - Child-side counterpart of engine selection: `deerflow_bridge/deerflow_research.py:16381-16400`
- **Tests that reference slice functions:** `backend/tests/test_parallel_research_merge.py`, `test_wave9_orchestrator.py`, `test_orchestrator_research_wiring.py`, `test_bridge_overhaul_v3.py`, `test_graph_actor_v1_seed.py`, `test_pipeline_actor_contract.py`.

## Invariants, gates, validation

- **One engine authority.** The parent resolves the engine and passes it to the child explicitly through env. Evidence-only and synthesis-manifest lanes always run legacy (:2290-2301). An unknown value never fails a launch and never silently selects legacy (:5915-5934).
- **v3 runs exactly one outer lane** (:5972-5981).
- **A pinned required actor plane forces legacy**, so a resumed run can honour its pinned contract (:5949-5951).
- **Concurrency envelope.** In-flight lanes ≤ min(tracks, global subagent cap, model cap). The subagent cap per lane is ≤ `model//workers - 1`; 0 disables subagents (:5833-5873).
- **Citation namespace.** After the merge, every surviving `[S#]` indexes `merged_sources` (1-based). Unresolvable markers are deleted, not kept dangling (:6372-6380). A single global References section is appended (:6388-6405).
- **Opening reconcile gates.** Length ≥ 200; no LLM error markers; exactly one executive section; ≤1 orientation section; the citation audit passes (no invented markers, a superset of the deterministic opening's markers) (:6246-6262).
- **Source dedup** keeps the best tier per URL and never loses non-empty fields (:6299-6308).
- **Market union** keeps the most recent quote per `market_id`, gives each event at most `max_per_event` slots, and reports an explicit `status.state` that separates irrelevant candidates, transport failure, inflight timeout and verified-empty (:6673-6685).
- **Price points** are bounded `0<=p<=1` with `t>0` (:6735).
- **Sealed v1 graph seed:**
  - Seeding must be enabled, have a positive expected projection, not raise, and return an int at or above `_expected_actor_seed_count` (:7199-7230).
  - The manifest must be `strict` v1 with a valid self-hash bound to graph_id (:7106-7120).
  - Readback must be `ok`, strict, and agree on the hash and `expected_counts` (:7143-7156).
  - Checked after seeding, after prose ingest/resolve/prune, and before reuse (:12408, :12527, :12644).
- **Integrity ledger.** Entries exist only for non-empty files. `schema_ok` is a coarse structural probe (:7452-7472).

## Failure modes & recovery

- **Engine typo** → v3 plus one warning per value (:5929-5934).
- **Malformed concurrency config** → safe defaults (1 or 2) instead of an exception (:5828-5829, :5840-5841, :5852-5853, :5864-5865).
- **Reconcile LLM** failure, short output, error markers, bad structure, or a failed citation audit → deterministic dedup fallback with `audit.fallback="deterministic"` (:6212-6214, :6277-6278).
- **`reconcile_cast`** exception → raw union of actors (:6465-6466).
- **Market snapshots:** a non-dict snapshot is ignored; all non-dict → None (:6558-6560); unparsable counts are skipped (:6594-6604).
- **`load_research_dossier_for_simulation`**: any exception → all-None dict, so the report agent falls back to blind graph search (:6774-6776).
- **`preflight_pipeline`** collects every error rather than stopping at the first one (:6791-6852). Callers return HTTP 400 with `preflight_errors` (e.g. `backend/app/api/research.py:101-107`).
- **v1 seed contract** failure raises RuntimeError. During reuse the caller catches it, rebuilds the graph and records `resumed_stage_validation="graph_rebuilt_actor_seed_readback_mismatch"` (:12416-12426). During build it fails the graph stage. A legacy cast's seed failure only logs a warning and returns None (:7220-7221).
- **run.json** builders never raise into the run. The `_write_run_manifest` and `_update_manifest` wrappers catch everything at debug level (:10390-10391, :10425-10426). Git probes return None or `"vendored"` (:7254-7273).
- **`_probe_artifact_schema`** returns True on an unexpected exception, so a broken probe never rejects a reusable artifact (:7448-7449).
- **`_actions_simulation_end_present`** returns False on OSError or a missing file (:7518-7519).

## Surprises

1. **Most multi-track merge code does not run with default config** (dead in the default configuration). The default engine is v3, which always uses one lane (:5972-5981; `backend/app/config.py:1187`). Even with legacy and 3 lanes, the default `RESEARCH_GLOBAL_SYNTHESIS=true` returns at :11623 before the deterministic merge. So `merge_track_reports`, `reconcile_track_reports` (and its LLM call), `normalize_track_report_citations`, `merge_actors_objs`, `merge_market_snapshots`, `merge_market_price_histories` and `merge_research_quality` run only with `RESEARCH_ENGINE=legacy` plus `RESEARCH_GLOBAL_SYNTHESIS=false` (:11279, :11636-11792).
2. **Dead code.** `strip_exec_summary_section` (:6408) has no references anywhere. `pick_freshest_markets` (:6529) is referenced only by tests. The legacy branch of `_expected_actor_seed_count` (:7028-7047) is computed but never enforced, because `_seed_research_actors` checks `expected` only when `required` (:7209, :7222).
3. **The pinned engine is not consulted.** Admission records `policy["research_engine"]` (:849), but no code reads it; `research_engine_for_run` looks only at `required` (:5949-5952). A legacy-admitted run with `DEERFLOW_DUAL_TRACK=false` (so `required=False`) resumes under whatever `RESEARCH_ENGINE` is configured at resume time. run.json does not record the effective research engine either; it has only the admission policy (:7340-7348). [verifier: that admission policy carries `research_engine` (:849, stored at :7962-7964 before run.json is first written at :11897), so run.json does record the admission-time engine under `resolved.research.actor_intelligence_policy.research_engine`. What is missing is the engine actually used at research time (:5949-5952, :11983)]
4. **Asymmetric unset defaults between parent and child.** The parent maps unset or unknown to **v3** (:5921-5934). The bridge maps unset or unknown to **legacy** (`deerflow_bridge/deerflow_research.py:16389-16400`). This is safe only because the parent always sets `env["RESEARCH_ENGINE"]` (:2301). The comment at :5890-5893 says only that the alias sets are the same.
5. **Suspected: `normalize_track_report_citations` flattens indentation.** `re.sub(r"[ \t]{2,}", " ", …)` runs on whole lines, including leading whitespace (:6383). Nested markdown lists (`    - item` → ` - item`) and indented blocks outside ``` fences lose their structure. Verified by running the extracted function.
6. **Suspected: opening-section stripping can delete a whole track.** `_opening_sections` ends a section only at a heading of the same or higher level (:6085-6088). A track written as `# Executive Summary` followed by `##` sections has its whole body removed by `_strip_opening_sections` (probe returned `''`). Headings inside code fences are also treated as headings (:6077).
7. **Suspected: `merge_actors_objs` bypasses sealed-v1 immutability.** It calls `reconcile_cast` directly (:6462), not `_reconcile_research_cast` (:3917-3947), which keeps v1 casts immutable. It also copies the first track's scalar keys, including any `actor_intelligence_contract`, onto a roster unioned across tracks (:6447-6456). If lane 0 carries a sealed v1 cast, the merged object's seal would no longer match its actors (seal claims a roster it no longer matches). This only applies to the non-global-synthesis legacy path.
8. **`reconcile_track_reports` with fewer than 2 non-empty tracks** returns the raw `# Track N` concatenation, not the deterministic dedup (:6217-6219). The caller's comment says disabling the LLM "must not re-enable" that defect (:11750-11751).
9. **Market status inconsistency.** `status.state` can be `inflight_timeout` or `partial_transport_failure`, but `status.empty_reason` then reports `no_equivalent_market` (:6679-6683 vs :6698-6702). Also, an older snapshot processed after a newer one only adds provenance; its extra fields are not backfilled (:6634-6639), although the docstring says older rows "backfill provenance" (:6555-6556). [verifier: this is not a contradiction. The docstring promises only that older rows backfill provenance, and the code does exactly that: an older row appends `{track, as_of}` to `track_provenance` and leaves the fields alone (:6632-6639). Probe: newer `{a:1}` then older `{b:2}` gives `{a:1, track_provenance:[t1, t2]}`] Market price-history ties go to the later track in iteration order, not the newest snapshot (:6737).
10. **Docstring drift in `merge_sources_union`.** It says non-dict rows are "原样保留" (kept as-is) (:6284), but the code drops them (:6293-6294; probed).
11. **run.json `timeout_s` can differ from the real watchdog.** The manifest always records `Config.deerflow_depth_budget(depth)` (:7317-7318), but the runner prefers an explicit `timeout`, then a non-blank env `DEERFLOW_RESEARCH_TIMEOUT`, then the depth budget (:2277-2283). [verifier: none of the four `DeerFlowResearchRunner.run` call sites (:10937, :11195, :11491, :12047) passes `timeout`, so in practice only the env override makes them differ] The comment's "与看门狗实际用值一致" (matches the watchdog's actual value, :7315) is false when `.env` sets `DEERFLOW_RESEARCH_TIMEOUT`. The `getattr` fallback for `SIM_GRAPH_FEEDBACK` is True (:7358), while the Config default is false (`backend/app/config.py:1385`); this is harmless because Config always defines it.
12. **Preflight gaps.** `/resume` calls `preflight_pipeline(mode=…)` without the run's pinned `research_model` (`backend/app/api/research.py:154`), so it validates `Config.DEERFLOW_MODEL` credentials, not the run's. `GRAPH_BACKEND=falkordb` (external) is never checked (:6799-6813). The docstring still says research_only "不碰 Zep" (doesn't touch Zep, :6787), a leftover from MiroFish; the graph is local Graphiti now.
13. **Two v1 detectors that disagree.** `_is_sealed_actor_intelligence_v1` checks only the top-level contract (:3906-3915). graph_builder's `_current_actor_seed_contract` also accepts row-level `intelligence.schema_version` markers (`backend/app/services/graph_builder.py:139-164`). A cast that has row markers but no top-level seal is seeded strictly by graph_builder, while the parent treats it as legacy: it is not required and is not validated (:7098-7099, :7201). [verifier: there is a further consequence. `seed_actors` routes such a cast to `_seed_actor_intelligence_v1` (`backend/app/services/graph_builder.py:1369-1374`), whose errors are `ActorGraphSeedError(RuntimeError)` (`graph_builder.py:81`). The parent's non-required branch catches any exception, logs a warning and returns None (:7215-7221). So a strict-seed failure on a row-only v1 cast is silently downgraded instead of failing closed] The parent's hash omits graph_builder's `default=str` (:7058 vs `backend/app/services/graph_builder.py:85-92`). They are equivalent for JSON-native manifests; a non-JSON value would raise TypeError, not RuntimeError, at :7116.
14. **Stale comment.** `_repo_git_sha` says "config.py 在 backend/app/，仓库根 = 上溯三级" (config.py is in backend/app/; repo root is three levels up, :7246). This file is in `backend/app/services/`, where three levels up is indeed the repo root. The code is right and the comment refers to the wrong file.
15. **Doc-vs-code drift:**
    - `DRF_ARCHITECTURE.md:403-423`: line anchors are stale (e.g. `merge_sources_union :2335`, actually :6281). It says merging is "deterministic (no LLM)", but `reconcile_track_reports` calls an LLM. It says "freshest-markets wins", but the code now unions snapshots.
    - `ARCHITECTURE_MAP.md:545,604`: `RESEARCH_PARALLEL_TRACKS` is shown as the active lane count and pool bound. The pool is bounded by `research_outer_track_workers`, and v3 ignores the setting. `ARCHITECTURE_MAP.md:544` gives `DEERFLOW_RESEARCH_DEPTH` default `standard`; the code default is `deep` (`backend/app/config.py:1159`).
    - `backend/app/config.py:1188-1195` still describes "预测市场取最新" (markets: take the freshest) and "# Track N H1 拼接" (concatenate under `# Track N` H1 headings).
    - `.env.example:659` and the `RESEARCH_TRACK_RECONCILE` comment (`backend/app/config.py:522-524`) say failure "降级为纯拼接" (degrades to plain concatenation), and the caller comment at :11741-11743 matches. The code falls back to deterministic dedup (:6210-6214).

## Verification

An adversarial verifier checked this map on 2026-10-11 against `main` on disk. It was a read-only pass: no code was changed and no pipeline, LLM or network call was made. The pure helpers (`research_*_cap`, `_strip_opening_sections`, `_opening_sections`, `_report_opening_kind`, `normalize_track_report_citations`, `merge_sources_union`, `merge_market_snapshots`) were AST-extracted and run in a scratch sandbox.

**Verdict counts.**

| Group | Total | Confirmed | Imprecise | Refuted |
|---|---|---|---|---|
| Key claims | 15 | 12 | 3 | 0 |
| Surprises | 12 | 12 | 0 | 0 |
| Extra Walkthrough/Control-flow spot-checks | 19 | 15 | 4 | 0 |

Inline `[verifier: …]` notes mark each correction in the text above.

**Key claims that are not fully confirmed.**

1. **`reconcile_track_reports` inputs and rejection gates** (:6216-6278). Imprecise. The prompt is not fed "only executive summaries": a track with no executive section (or an empty one) contributes the first `per` chars of its whole report (:6186-6192, :6223). The rejection gates also include more than one orientation section (:6251), not only a wrong executive count. Everything else is correct: one `LLMClient().chat` call at temperature 0.2 with max_tokens 4000, the 200-char floor, error markers, the citation audit, the exception fallback, and the raw `merged_report` returned for fewer than 2 tracks.
2. **`_seed_research_actors` legacy behaviour** (:7199-7231). Imprecise. For a legacy cast, only two cases return None: seeding disabled (:7207) and `seed_actors` raising (:7220-7221, after a warning). `expected<=0` and a bool, non-int or short count are not checked; the raw `seed_actors` return value is passed through (:7208-7231). The sealed-v1 raise conditions are confirmed.
3. **`_build_run_manifest` timeout and engine** (:7313-7379). Imprecise. `timeout_s = Config.deerflow_depth_budget(depth)` is confirmed, and so is calendar-mode `max_rounds = options.max_rounds or None` (:7326-7327).
   - No production `DeerFlowResearchRunner.run` call passes `timeout` (:10937, :11195, :11491, :12047). In practice, only a non-blank env `DEERFLOW_RESEARCH_TIMEOUT` makes the recorded value differ from the watchdog (:2278-2283).
   - The admission-time engine *is* recorded, through `resolved.research.actor_intelligence_policy.research_engine` (:849, :7345-7347; pinned at :7962-7964 before run.json is written at :11897). What is missing is the engine actually resolved at research time (:11983).

**Walkthrough and Control-flow statements corrected.**

- **`_expected_actor_seed_count` legacy aliases** (:7037-7046). They are not "distinct": every non-blank alias whose `normalize_name` differs from the actor name is counted, with no de-duplication.
- **"`_update_manifest` at each stage entry"**. It runs only at ontology (:12309), graph (:12391) and report (:13187) entry, plus during RUN when the round total is first seen (:13041-13042). It never runs for research or prepare. It rebuilds through `_build_run_manifest` only when run.json is missing or unreadable (:10408-10411).
- **`PREDICTION_MARKETS_MAX_PER_EVENT` "`<=0` means unlimited"**. This holds inside `merge_market_snapshots` (:6663), but the only production caller passes `int(Config… or 3)` (:11697). A configured `0` therefore becomes 3, and only a negative value disables the cap. `PREDICTION_MARKETS_MAX=0` likewise becomes 20 (:11696).
- **Surprise 9's docstring "contradiction"** (:6555-6556). There is none. The docstring promises only that older rows backfill *provenance*, which is exactly what :6632-6639 does (probe confirmed).

**Spot-checks confirmed** (anchors re-read): :5871, :11085/:11243-11244, :10885/:11087/:12022, :5895-5901 vs `deerflow_bridge/deerflow_research.py:16374-16375`, :6110, :6157-6161, "Summary of risks" → None (probe), `LLMClient` defaults to `Config.LLM_PROVIDER` (`backend/app/utils/llm_client.py:257`), the 17 dimensions (:114-132), `list_pipelines` sorted newest first (:1220), `.gitignore:84` `deer-flow/`, `_calendar_mode` users (:8563, :12810, :12878, :12980), the penalty formula (:10682-10699), the reuse-phase catch-and-rebuild (:12402-12426), and the global-synthesis early return at :11623 using only `merge_sources_union` from this slice (:11277-11634).

**Omissions (significant behaviour the map did not state).**

1. **`preflight_pipeline` can raise instead of reporting** (:6800-6802). `importlib.util.find_spec('redislite.async_falkordb_client')` imports the parent package. If `redislite` is absent, it raises `ModuleNotFoundError` (verified with a missing-parent probe), so the friendly backend error and the kuzu/`FALKORDB_HOST` fallbacks are unreachable. The impact is mitigated because `falkordblite` is a hard dependency (`backend/pyproject.toml:29`).
2. **Row-only v1 cast: strict-seed failure is swallowed** (:7201, :7215-7221). graph_builder seeds such a cast strictly (`backend/app/services/graph_builder.py:1369-1374`) and raises `ActorGraphSeedError(RuntimeError)` (`graph_builder.py:81`). The parent treats the cast as legacy, so it logs a warning and returns None instead of failing closed.
3. **Single-survivor non-synthesis merge publishes un-deduplicated scaffolding** (:11744). When only one lane survives with `RESEARCH_GLOBAL_SYNTHESIS=false`, neither `reconcile_track_reports` nor `_deterministic_track_report` runs. The published report keeps the `# Track 1: …` H1 and that track's own Executive Summary and reader-guide sections (`merge_track_reports` at :11647, then only `append_merged_references` at :11768).
4. **`merge_actors_objs` docstring drift** (:6437 vs :6447-6449). The docstring says scalar fields come from the "first non-empty track". The code copies the first dict's scalar keys wholesale, even when they are empty.
5. **`normalize_track_report_citations` References detection is not fence-aware** (:6344-6356 vs :6361-6370). Reference stripping runs before fence tracking, so a `References` H1-H3 line inside a code fence starts deleting lines until the next H1-H3 heading.
6. **`merge_market_snapshots` compares `as_of` as raw strings** (:6634, :6667). Snapshots with mixed ISO formats or timezone suffixes can mis-order "newest" for both field overwrite and the top-level `as_of`.
