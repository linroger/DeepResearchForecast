# scripts-ops-2 — Backend ops scripts II and root python scripts

Slice: 14 files, 4,866 lines, all read in full from disk on branch `main` on 2026-10-11.

| File | Lines | Kind |
|---|---|---|
| `backend/scripts/export_demo_site_data.py` | 1093 | Demo-site exporter into `docs/demos/<run>/` (writes tracked files) |
| `backend/scripts/backfill_report_visuals.py` | 792 | Offline replay of report visuals, citations, final audit and PDFs (dry run by default) |
| `backend/scripts/golden_eval.py` | 522 | Deterministic golden-question outcome scorer (Brier / log score / ECE) |
| `backend/scripts/eval_forecast_quality.py` | 439 | Rubric LLM-judge regression gate (opt-in, spends API budget) |
| `backend/scripts/model_comparison.py` | 524 | Re-runs the REPORT stage under several LLM providers and compares them (opt-in) |
| `backend/scripts/forecast_tools.py` | 76 | CLI over `ensemble.aggregate_forecasts` and `backtest` |
| `backend/scripts/test_deerflow_deep_research.py` | 171 | Manual regression script for the DeerFlow deep-research bridge contract |
| `backend/scripts/test_graphiti_migration.py` | 118 | Manual smoke test of the local Graphiti `Zep` shim (calls the LLM) |
| `backend/scripts/test_graphiti_services.py` | 129 | Manual smoke test of the graph and report services on local Graphiti (calls the LLM) |
| `backend/scripts/test_pipeline_resume.py` | 302 | Offline regression script for pipeline resume, cancel, delete and clean |
| `backend/scripts/test_profile_format.py` | 166 | Prints OASIS profile CSV/JSON output for a manual check |
| `backend/scripts/test_zep_rate_limit.py` | 116 | Offline regression script for 429 Retry-After handling and graph snapshot reuse |
| `scripts/salvage_orphaned_pipelines.py` | 231 | Repair tool for state files. It has no backend imports and runs as a dry run by default. |
| `scripts/watch_pipeline_progress.py` | 187 | Streams stage transitions from `pipeline_state.json` (used by `scripts/start.sh`) |

**Anchor convention.** A bare file name with a line number means that file inside this slice: `export_demo_site_data.py:N`, `backfill_report_visuals.py:N`, `golden_eval.py:N`, `eval_forecast_quality.py:N`, `model_comparison.py:N`, `forecast_tools.py:N` and the `test_*.py:N` files all mean `backend/scripts/<file>:N`. `salvage_orphaned_pipelines.py:N` and `watch_pipeline_progress.py:N` mean `scripts/<file>:N`. Every other anchor is a full path relative to the repo root.

## Purpose & position in the pipeline

None of these files run inside the Flask app. A repo-wide grep finds no `import` of any slice script from `backend/app`. The only mentions there are in comments: `backend/app/services/ensemble.py:8`, `backend/app/services/forecast_ledger.py:6`, `backend/app/api/sdk.py:287` and `backend/app/services/report_agent.py:3197`. The scripts form four groups.

1. **Publishing (after the pipeline).** `export_demo_site_data.py` takes completed runs in `backend/uploads/{pipelines,projects,reports,simulations}` and writes a static bundle per run into `docs/demos/<run_key>/`. That bundle is the data the GitHub Pages demo site (`docs/demo.html`, `docs/index.html`) renders (`export_demo_site_data.py:1-32`, `:50-52`). It can also enforce the same publication barrier the app uses (`validate_publishable_run`, `export_demo_site_data.py:221-405`). `backfill_report_visuals.py` re-finalizes already-persisted reports offline. It rebuilds charts, binary-forecast blocks, the citation and final audit, translations and PDFs, all inside a transactional backup (`backfill_report_visuals.py:1-8`, `:739-769`).
2. **Evaluation and analysis (offline, after the pipeline).** `golden_eval.py` scores `forecast.json` binary forecasts against resolved golden questions. It uses no LLM (`golden_eval.py:14-17`). `eval_forecast_quality.py` is the opt-in LLM-judge rubric gate (`eval_forecast_quality.py:12-17`). `model_comparison.py` re-runs only the REPORT stage of a finished pipeline under N providers (`model_comparison.py:4-9`). `forecast_tools.py` aggregates and backtests `forecast.json` files (`forecast_tools.py:1-16`).
3. **Manual regression and smoke scripts.** These are the six `backend/scripts/test_*.py` files. pytest never collects them because `testpaths = ["tests"]` (`backend/pyproject.toml:84`). Each must be run by hand. Three need no network (`test_pipeline_resume.py:13-15`, `test_zep_rate_limit.py`, `test_deerflow_deep_research.py`). Two call the configured LLM and the local graph store (`test_graphiti_migration.py:6-7`, `test_graphiti_services.py:13`).
4. **Root ops scripts (stdlib only).** `scripts/watch_pipeline_progress.py` is the progress follower that `npm start` / `scripts/start.sh` launches (`scripts/start.sh:37`, `:503`, `:591`). `scripts/salvage_orphaned_pipelines.py` rewrites historical `failed` states whose report was already complete into `completed (degraded)` (`salvage_orphaned_pipelines.py:2-20`).

## Walkthrough (source order)

### 1. `backend/scripts/export_demo_site_data.py` — demo-site exporter

**Invocation** (`export_demo_site_data.py:25-31`): `cd backend && uv run python scripts/export_demo_site_data.py [--skip-graph] [--only RUN_KEY] [--require-publishable] [--research-log-only | --reports-only] [--graph-api http://127.0.0.1:5001]`.

**Module setup**
- `sys.path.insert(0, backend/)` (`export_demo_site_data.py:45`). It imports `Config` and `merged_research_progress_full` at import time (`export_demo_site_data.py:47-48`). Graph, report and text-processor services are imported lazily inside functions.
- `ROOT` is the repo root, `UPLOADS = ROOT/backend/uploads` and `OUT_ROOT = ROOT/docs/demos` (`export_demo_site_data.py:50-52`). The paths are fixed relative to the script location. `Config.UPLOAD_FOLDER` is not consulted.
- `RUNS` (`export_demo_site_data.py:55-78`) is a hard-coded map of 15 run keys (site URL slugs) to pipeline ids: `us-ai-2030`, `ev-2035`, `russia-ukraine`, `semiconductors-2030`, `memory-semi-2030`, `china-storage-2035`, `us-iran-2026`, `storage-semi-2028`, `cloud-2030`, `collision-decade-2031`, `us-trade-2028`, `us-midterms-2026`, `grid-storage-2040`, `datacenter-2030` and `quantum-2040`. It must match `RUN_KEYS` in `docs/demo.html:56` (it currently does: the same 15 keys).
- `LANGUAGES = ("en","zh")` (`:79`).
- `PLACEHOLDER_MARKER = "本章节生成失败"` (`:81`).
- `REQUIRED_STAGES = research, ontology, graph, prepare, run, report` (`:82`).
- `RUN_SUMMARY_HEALTH_VALUES = {ok, llm_degraded, truncated, errored, hollow}` (`:83-85`).
- `MARKDOWN_LINK_RE` matches `[..](target)` and `![..](target)`. `MARKDOWN_TARGET_RE` splits a target into a URL (bare or `<...>`) and an optional quoted title (`:86-91`).

**Small helpers**
- `_read_json(path)` returns `None` if the file is missing. It does **not** catch JSON errors (`:94-98`).
- `_write_json` writes `ensure_ascii=False, indent=1` (`:101-103`).
- `_sha256_file` reads in 1 MiB chunks (`:106-111`).

**`export_research_log(handoff_dir, output_dir, *, retain_existing_if_missing=False)`** (`:114-150`)
- Calls `merged_research_progress_full(handoff_dir)` (`:125`), defined at `backend/app/services/research_progress.py:520`. That function reads every trusted progress log under the handoff dir: the root `research_progress.log`, `track_<n>/research_progress.log`, and `research_attempts/*.log` (`backend/app/services/research_progress.py:418-466`).
- The read is capped. It raises `ResearchProgressLimitError` above 64 MiB in total (`backend/app/services/research_progress.py:72`, `:539-543`), above 16 tracks or above 16 attempts (`backend/app/services/research_progress.py:67-68`).
- If no source exists and `retain_existing_if_missing` is set and `research_log.txt` already exists in the output, it keeps the old file. It returns `complete: False, retained_legacy_artifact: True` (`:126-137`).
- If no source exists otherwise, it raises `RuntimeError("no research progress logs found for static export")` (`:138`).
- Otherwise it writes all merged lines, newline-terminated, to `<out>/research_log.txt` (`:139-144`). It returns `{line_count, source_count, complete: True, event_fidelity: "summarized_progress_events"}` (`:145-150`).

**`refresh_demo_research_log(key, pipeline_id, *, require_publishable=False)`** (`:153-192`) handles `--research-log-only`.
- Loads `pipeline_state.json`. A missing state raises `RuntimeError` (`:157-159`).
- Optionally runs the full publication barrier (`:160-161`).
- Requires an existing `docs/demos/<key>/meta.json` whose `pipeline_id` matches (`:163-171`).
- Re-exports the log in **strict** mode, with no retain fallback (`:173-176`).
- Updates `meta.prompt`, `meta.research_log` and `meta.artifact_sha256["research_log.txt"]` (`:177-185`).
- Rewrites meta.json with **indent=2** and a trailing newline (`:189-191`).

**`_load_bound_project(uploads, project_id, graph_id)`** (`:195-218`) loads `uploads/projects/<project_id>/project.json`. It raises `RuntimeError` unless that file's `project_id` and `graph_id` both match the pipeline's.

**`validate_publishable_run(pipeline_id, state, uploads=UPLOADS)`** (`:221-405`) is the fail-closed publication gate. It collects every issue and then raises one `RuntimeError("<pid> is not publishable: ...")` (`:403-404`). On success it returns the parsed `final_audit.json`. The checks, in order:
1. `state.pipeline_id` matches the requested id, and `state.status == "completed"` (`:224-227`).
2. Each of the 6 `REQUIRED_STAGES` has `status == "completed"` and no `error` (`:229-233`).
3. `project_id`, `report_id`, `simulation_id` and `graph_id` are present (`:235-246`). The project artifact is bound to `project_id` and `graph_id` (`:248-252`).
4. The report's `meta.json` exists, its `report_id`, `simulation_id` and `graph_id` equal the pipeline's, and its `status == "completed"` (`:254-275`).
5. The simulation dir exists. `state.json` matches the simulation, project and graph ids and has `status == "completed"` (`:277-307`). `simulation_config.json` matches the same 3 ids (`:309-329`). `run_state.json` has the matching `simulation_id` (`:331-340`).
6. `run_summary.json` has the matching `simulation_id`. Its `simulation_health` is in the allowed set and is **not** `hollow`. `agent_count`, `rounds_executed`, `total_actions` and `organic_action_count` are positive non-bool ints (`:342-372`).
7. `final_audit.json` has the matching `report_id`, and `read_only`, `disk_matches_memory`, `hard_passed`, `publish_gate.passed` and `scenario_contract.valid` are all `True` (`:374-390`).
8. The SHA-256 of `full_report.md` equals `audit.markdown_sha256`, and the SHA-256 of `forecast.json` equals `audit.forecast_sha256` (`:392-401`).

**Markdown asset handling**
- `_validate_namespace` only allows `[A-Za-z0-9._-]+` (`:408-411`).
- `_parse_local_markdown_target(target)` (`:414-441`):
  - An empty target or a `#anchor` returns `None` (kept as is) (`:416-418`).
  - An external URL, meaning one with a scheme, a netloc or a leading `//`, returns `None` (`:421-422`, `:429-431`).
  - Any other local link **must** decode to `charts/<[A-Za-z0-9._-]+>`, or the function raises `ValueError("unsafe local Markdown asset")` (`:432-437`).
  - A valid link returns `(path, ?query#fragment suffix, title)` (`:438-441`).
  - The consequence is that a single relative link not under `charts/` aborts the export.
- `_markdown_asset_paths` returns the unique ordered local chart paths (`:444-455`).
- `_copy_static_asset` copies non-HTML bytes verbatim. For `.html` it strips trailing spaces and tabs on each line (`:458-467`).
- `copy_markdown_assets(markdown, source_dir, output_dir, destination_namespace, retained_sha256=None)` (`:470-512`):
  - It first resolves every asset (`:486-499`). Each realpath must stay inside `source_dir`, otherwise it raises `ValueError` (`:488-490`).
  - If the source file is missing, it may reuse the **already-published** copy, but only when that copy's SHA matches `retained_sha256[<namespace>/<file>]` (`:493-497`). Otherwise it raises `FileNotFoundError` (`:498-499`).
  - It then copies into `<namespace>.staging`, deletes the old namespace dir and `os.replace`s staging into place (`:501-511`).
  - With zero assets the namespace dir is deleted and not recreated (`:508-511`).
  - It returns `["<namespace>/<file>", ...]` (`:512`).
- `rebase_markdown_assets` rewrites each local link to `demos/<key>/<namespace>/<basename><suffix><title>`, which is relative to `docs/demo.html` (`:515-532`).
- `copy_report_assets` and `rebase_report_assets` are the same functions with the namespace fixed to `"charts"` (`:535-553`).

**`validate_retained_graph(output_dir, expected_graph_id)`** (`:556-563`) raises if the existing `graph.json.graph_id` differs. Only strict `--skip-graph` uses it (`:985-986`).

**`strip_placeholder_sections(md)`** (`:566-577`) splits on `^## ` headings. It drops any H2 section whose stripped body contains `本章节生成失败` **and** is shorter than 300 chars.

**`export_forum(sim_dir)`** (`:580-610`)
- For `twitter` and `reddit` it reads `<sim>/<platform>/actions.jsonl`. It skips blank lines, bad JSON and rows that carry an `event_type` (round and simulation markers) (`:589-599`).
- Each kept row becomes `{round, agent (agent_name or "Agent_<id>"), type (UPPER action_type), content (action_args.content|text), ok (success, default True)}` (`:600-608`).
- A missing file gives `[]` (`:586-588`).

**`rebuild_graph(key, out_dir)`** (`:613-638`)
- Rebuilds a graph from the **published** `dossier.md` and `ontology.json`.
- It calls `GraphBuilderService.create_graph(name="demo_<key>")`, `set_ontology` and `TextProcessor.split_text(dossier, Config.DEFAULT_CHUNK_SIZE, Config.DEFAULT_CHUNK_OVERLAP)`. Then it calls `add_text_batches(batch_size=10)` and `_wait_for_episodes` (`:627-637`).
- This runs LLM entity extraction and embeddings, because local Graphiti extraction uses `Config.LLM_PROVIDER` (`backend/app/config.py:1010-1016`).
- Only the non-strict 404 branch reaches it (`:978-980`).

**`export_graph(graph_id, graph_api=None)`** (`:641-684`)
- With `graph_api` it does a `GET <graph_api>/api/graph/data/<quoted id>?full=true` through `urllib`, `timeout=120` (`:648-659`). An `HTTPError` becomes `RuntimeError` (`:660-661`), and `success != true` becomes `RuntimeError` (`:662-663`).
- That route is `backend/app/api/graph.py:576-618`. `full=true` overrides `top_k` and `min_degree` (`backend/app/api/graph.py:599-601`).
- Without `graph_api` it opens the graph store directly: `GraphBuilderService(api_key=Config.ZEP_API_KEY).get_graph_data(graph_id)` (`:665-669`).
- Trimming:
  - Nodes become `{id: uuid, name, labels minus "Entity", summary[:600]}` (`:670-675`).
  - Edges become `{source, target, name, fact[:400]}`, and an edge is kept only when both endpoints are among the exported nodes (`:677-683`).
  - It returns `{"nodes", "links"}` (`:684`). The caller adds `graph_id` (`:982`).

**Language variants**
- `_markdown_language(md)` delegates to `ReportAgent._detect_translation_target` (`:687-692`; defined at `backend/app/services/report_agent.py:6084-6106`). It returns `"zh"` / `"en"` / `None`.
- `published_report_variants(report_id, report_dir, primary_lang)` (`:695-719`):
  - Temporarily points `ReportManager.REPORTS_DIR` at `UPLOADS/reports` and restores it in a `finally` (`:705-719`).
  - For each non-primary language it exports `full_report.<lang>.md` only if the file exists **and** `ReportManager.is_publishable(report_id, lang)` (`:713`; that is `publication_status`, `backend/app/services/report_agent.py:12435-12598`).
  - Placeholder sections are stripped (`:716`).
- `published_dossier_variants(handoff, primary_lang)` (`:722-749`) requires all of the following:
  - `research_report.<lang>.md` exists.
  - `research_report.translation.<lang>.json.status == "available"`, and its `source_sha256` equals the SHA of the current `research_report.md`.
  - `research_report.final_audit.<lang>.json.hard_passed is True`, and its `markdown_sha256` equals the variant's SHA (`:739-745`).
- `_write_language_set(out, stem, primary_md, variants, primary_lang)` (`:752-772`):
  - Writes `<stem>.md` (the primary) and `<stem>.<lang>.md` (the variants).
  - Returns `{lang: file}`. The primary key is `primary_lang or "und"` (`:762`).
  - Deletes `<stem>.<lang>.md` for any language no longer published (`:768-771`).
- `export_dossier(key, handoff, out, retained_sha256=None)` (`:775-803`):
  - Reads `handoff/research_report.md`. There is no existence guard, so a missing file raises `FileNotFoundError` (`:779-780`).
  - Copies the charts for **all** languages in one pass into the `research-charts` namespace, because each pass rebuilds the namespace from scratch (`:783-791`).
  - Rebases the links and writes the `dossier*.md` files (`:792-803`).
- `export_report(key, report_id, out, retained_sha256=None)` (`:806-825`) does the same for `uploads/reports/<report_id>/full_report*.md` into the `charts` namespace, with placeholder sections stripped.

**`_publication_summary(audit)`** (`:828-839`) builds meta.json `publication`: `{hard_passed, publish_passed, scenario_contract_valid, citation_coverage (citation_grounding.resolved_coverage), semantic_citations_passed, markdown_sha256, forecast_sha256}`.

**`refresh_demo_reports(key, pipeline_id)`** (`:842-912`) handles `--reports-only`.
- It needs the pipeline state and an existing meta.json with a matching `pipeline_id`. Either missing raises `RuntimeError` (`:851-862`).
- It re-exports the report and its variants, passing the published `artifact_sha256` as the retained manifest (`:863-867`).
- It re-exports the dossier only if a published translation exists now or `meta.dossier_languages` was set before (`:874-881`).
- It recomputes hashes for the refreshed files (`:882-891`). Hash entries are then merged:
  - Old entries keep their order, and refreshed ones get new digests.
  - Old entries under a refreshed prefix (`charts/`, `report.`, plus `research-charts/` and `dossier.` when the dossier was refreshed) that are no longer published are dropped.
  - New entries are appended (`:892-902`).
- It refreshes `publication` from the current `final_audit.json` (`:903-904`).
- It rewrites meta.json, keeping the indentation it detects from line 2. The default is 2 when the line is unindented (`:905-911`).
- It does **not** run `validate_publishable_run`, even with `--require-publishable` (`:1074-1075`).

**`export_run(key, pipeline_id, skip_graph, require_publishable=False, graph_api=None)`** (`:915-1037`) is the full export.
1. Load the state. If it is missing, print `!! <key>: pipeline state missing, skipped` and return without an error (`:922-925`).
2. Get the audit. In strict mode it comes from `validate_publishable_run`. Otherwise `final_audit.json` is read leniently (`:926-930`).
3. `os.makedirs(docs/demos/<key>)` (`:931-932`).
4. Stage 1: research log (retain-if-missing allowed), dossier and variants, then copy `actors.json` / `sources.json` if present (`:935-945`).
5. Stage 2: `ontology.json = {entity_types, edge_types, analysis_summary}` from the bound `project.json` (`:947-958`).
6. Stage 3, unless `--skip-graph`: `export_graph`. On `ApiError` with `status_code == 404`, strict mode raises and non-strict mode rebuilds and re-exports. Any other `ApiError` is re-raised. Then `graph.json` is written with `graph_id` (`:963-984`). With `--skip-graph` plus strict mode it validates the retained `graph.json` (`:985-986`).
7. Stage 5: `forum.json` (`:988-990`).
8. Stage 6: report and variants (`:992-994`).
9. meta.json. `rounds` comes from `run_state.total_rounds`. `personas` is `len(simulation_config.agent_configs or agents)` (`:996-999`). `artifact_sha256` covers every published artifact path that exists (`:1000-1016`). The keys written are `pipeline_id, report_id, simulation_id, graph_id, status, prompt, created_at, mode, rounds, personas, has_actors, research_log, dossier_assets, report_assets, dossier_languages, report_languages, artifact_sha256, publication` (`:1017-1036`).

**`main()`** (`:1040-1089`)
- `--only KEY` indexes `RUNS[KEY]` directly, so an unknown key raises `KeyError` (`:1065`).
- Mode precedence is `--research-log-only` > `--reports-only` > full export (`:1067-1088`).
- `--skip-graph` and `--graph-api` apply only to the full export (`:1082-1088`).
- It always returns 0 unless an exception escapes (`:1089`).

### 2. `backend/scripts/backfill_report_visuals.py` — transactional offline report replay

**Invocation**: `python scripts/backfill_report_visuals.py [--apply] [--target PIPELINE:REPORT ...]` (`backfill_report_visuals.py:772-788`).
- There is **no** `sys.path` insert. `from app...` resolves only when `backend/` is importable (`backfill_report_visuals.py:22-36`): either the editable install of the backend venv (`backend/.venv/lib/*/site-packages/_editable_impl_mirofish_backend.pth`, which points at `backend/`) or pytest's `backend/tests/conftest.py:22`.
- With no `--target` it processes `DEFAULT_TARGETS`, three hard-coded pairs (`backfill_report_visuals.py:39-43`):
  - `pipe_f23527f7d903:report_a03be154febc`
  - `pipe_0f2bee7bd649:report_1c312b400d33`
  - `pipe_a8986bffd918:report_1b70ace5c9e8`
- It prints a JSON list of per-target plans and results and returns 0 (`:786-788`).

**Constants**
- Id regexes `^report_[A-Za-z0-9_-]+$` / `^pipe_[A-Za-z0-9_-]+$` (`:44-45`).
- Visual-annex heading regex (English and `可视化附录`) (`:46`).
- CJK-run regex (≥2 chars) (`:47`). Latin-prose regex (≥40 chars) (`:48`). Inline code and URL protection regex (`:49`).
- Residual scenario keywords (`:50-52`).
- `_ZH_VISUAL_TITLES`: Chinese captions for 11 chart ids (`:53-65`).
- `_Report` is a minimal holder exposing `.markdown_content` (`:68-70`).
- `_read_json` and `_read_text` swallow errors and return `None` / `""` (`:73-84`).

**Pure transforms**
- `strip_generated_visuals(md)` (`:87-136`) removes generated visuals in two passes:
  - First it removes every `## Visual Annex` / `## 可视化附录` section up to the next H2 (`:89-100`).
  - Then it removes every `<!-- viz:... -->` marker block (`:102-135`). A block covers an optional bold title, then a fenced block (```` ``` ```` / `~~~`), or an image line, or a `**label**:` line, then an optional italic caption.
  - It collapses 3 or more newlines to 2.
- `drop_irreparable_language_lines(md, language)` (`:139-189`) is the network-free language-purity repair.
  - For an English report, a line is contaminated if it has a run of 2 or more CJK chars. For a Chinese report, a line is contaminated if it has a Latin prose run of 40 or more chars with 4 or more spaces (`:149-155`).
  - Code fences, everything after `## References` / `## 参考来源`, and blank lines are exempt (`:163-177`).
  - In a contaminated table row, only the bad cells become ` — ` (`:179-182`). In an image line, the alt text becomes `Visualization` (`:183-184`). Any other contaminated line is blanked (`:185-188`).
  - It returns `(markdown, removed_count)`.
- `ensure_baseline_scenario_label(forecast)` (`:192-221`) leaves the forecast alone if any scenario name already contains a residual keyword (`:198-203`). Otherwise it picks the scenario whose name matches `\b(modal|base)\b`, falling back to the highest probability. It prefixes `"Baseline / Status Quo — "` (or `"基线/维持现状 — "` when the name has CJK) and returns `(old, new)` (`:204-221`). A second run is a no-op, because the new prefix contains the keywords.
- `strip_circular_binary_rows(md, forecast_ids, *, quality=None)` (`:224-274`):
  - Drops Markdown table rows whose first cell is a circular forecast id (`:230-239`).
  - Rewrites the first `_N forecasts; ..._` English summary and the first `_共 N 项预测..._` Chinese summary. The counts come from `quality.count`, `conviction_count` and `sharp_criteria_count`. If those are missing it falls back to counting `| F<n> |` rows and ≥70% / ≤30% probabilities (`:241-273`).
- `synchronize_market_comparison(report_dir, forecast)` (`:277-311`):
  - Recomputes each `market_anchor.divergence = round(p_model - implied_yes_prob, 4)` (`:289-299`).
  - Rebuilds the comparison with `build_market_comparison`.
  - If there are any comparisons, it writes both `forecast["market_comparison"]` and `market_comparison.json` atomically. Otherwise it removes both (`:300-311`).
- `_language(md, filename)` (`:314-321`) returns Chinese or English from the `.zh.md` / `.en.md` suffix. Otherwise the text is Chinese when CJK chars are more than 5% of the first 20,000 chars.
- `localized_manifest(manifest, language)` (`:324-339`) swaps chart `title` and `caption` to the Chinese strings for Chinese output only.

**Artifact assembly**
- `_artifacts(report_dir, handoff, simulation_id)` (`:342-364`) builds the input dict for `ReportVisualizer.build_all`:
  - From the report dir: `forecast.json`, `ensemble_forecast.json`, `comparison.json`.
  - From the handoff dir: `actors`, `timeline`, `quantitative`, `sources`, `contested`, `prediction_markets`, `graph_priors`, `graph_priors_structural`.
  - From `Config.OASIS_SIMULATION_DATA_DIR/<sim>/`: `world_state_trajectory.json`.
  - Empty values are skipped.
- `_offline_report_agent(...)` (`:367-388`) builds a `ReportAgent` with `__new__` (no `__init__`, no LLM client). It sets only `sources`, `_citation_index`, `output_language`, `research_report` (from the handoff), the outline/background placeholders, `situation_brief` (from `actors.situation_brief`) and `_forecast_spine`.

**Backup and restore**
- `_backup(report_dir)` (`:391-411`) creates `report_dir/.codex-backup-<YYYYmmddTHHMMSSZ>` with `mkdir(exist_ok=False)`, so two runs in the same second collide. It copies:
  - `full_report*.md` and `full_report*.pdf`
  - `meta.json`, `forecast.json`, `market_comparison.json`, `viz_manifest.json`, `pdf_export.json`
  - `citations*.json` and `final_audit*.json`
  - the `charts/` tree (symlinks preserved)
- `_restore_from_backup(report_dir, backup)` (`:414-442`) deletes the live members of those same artifact families, then copies the backup back. It skips `charts` and `replay_failure.json` in the file loop and restores `charts/` with `copytree`.

**`_backfill_one_impl(pipeline_id, report_id, *, apply)`** (`:445-736`)
1. Validate the id regexes (`:446-447`). Load `Config.PIPELINE_DATA_DIR/<pid>/pipeline_state.json` and require `state.report_id == report_id` (`:448-451`). The report dir is `ReportManager._get_report_folder(report_id)` and must exist (`:452-454`). The handoff dir is `state.handoff_dir`, or `<pipeline_dir>/handoff` by default (`:455`).
2. **Dry run** (no `--apply`): return a plan `{pipeline_id, report_id, simulation_id, markdown_files, apply}` with no writes (`:457-466`).
3. With `--apply`: back up (`:468`), then assemble the artifacts (`:469`).
4. Repair the forecast (`:470-502`):
   - Remove binaries flagged by `_is_circular_market_forecast(statement, resolution_criteria)` (`:474-484`).
   - Run `reconcile_forecast_contract` (`:485`).
   - Recompute `binary_quality = _binary_quality(retained, min_count=10)`, keeping `proposition_consistency` and the old `ensemble` block (`:490-496`).
   - Synchronize the market comparison (`:500`), add the baseline label (`:501`), and write `forecast.json` atomically (`:502`).
5. Rebuild the charts: `ReportVisualizer().build_all(report_id, report_dir, artifacts)`. This writes `charts/` and `viz_manifest.json` (`:503`; `backend/app/services/report_visualizer.py:4313-4316`).
6. Repair the primary `full_report.md`. It is required, or the run raises `FileNotFoundError` (`:514-516`). The steps, in order (`:517-555`):
   - strip generated visuals
   - apply the scenario-label rename
   - strip circular rows
   - re-render and upsert the deterministic binary-forecast block and the market-comparison block
   - drop irreparable language lines
   - `_repair_quote_grounding`
   - `lint_report(mode="final", spine=forecast)`
   - `_place_visualizations` (a second `__new__` agent)
   - `_stabilize_publish_markdown`, a bounded fixed point of up to 4 passes (`backend/app/services/report_agent.py:7991-8015`)
   - atomic write
7. Store the lint result in `forecast.json` `quality.lint` (`:557-561`). Load `meta.json` and set `meta.markdown_content` (`:562-567`).
8. Run the authoritative read-only audit `_enforce_final_publish_audit` (`:573-578`). It raises `RuntimeError` if the audit fails (`backend/app/services/report_agent.py:8423-8435`), and that triggers the rollback in step 12.
9. Handle each translation variant `full_report.(en|zh).md` (`:596-682`):
   - Apply the same strip, rename and circular-row transforms, then place visuals with the localized manifest. There is **no** prose repair on variants (`:511-513`).
   - Run `main_agent._audit_translation_variant(...)` against the finalized primary (`:615-622`).
   - On a failed hard audit, delete the variant `.md`, `.pdf` and `citations.<lang>.json`, write `final_audit.<lang>.json`, and record an `unavailable_translations` entry with `reason: "translation_variant_audit_failed"`, the original SHA and a bundle-relative backup path (`:631-658`).
   - On a pass, write the citations, then the audit, then the Markdown (the "publish barrier" order), and append a `translations` entry (`:660-682`).
10. Write `meta.translations` and `meta.unavailable_translations`; the key is removed when empty (`:684-689`).
11. Export PDFs. For the primary and each passing variant it calls `ReportManager.export_pdf(report_id, force=True, lang=lang)`. The result must exist and start with `%PDF-` (`ReportManager._is_pdf_file`), otherwise the run raises `RuntimeError` (`:691-701`). It then writes `pdf_export.json` (`:712-718`).
12. Return the plan plus `backup, visual_items, visual_ids, outcome_focus_ok, residual_mechanics, circular_market_forecasts_removed, language_lines_removed, ungrounded_quotes_removed, scenario_label_change, final_audit_hard_passed, publish_gate_passed, final_audit_sha256, translation_variants, pdf_exports` (`:720-736`).

**`backfill_one(pipeline_id, report_id, *, apply)`** (`:739-769`) wraps the run in a transaction.
- It records the existing `.codex-backup-*` dirs (`:743-744`).
- On any exception it finds the newest backup created during this run, restores from it, writes `replay_failure.json` into the backup, and re-raises (`:747-769`).
- If the restore itself fails, it raises `RuntimeError` naming both failures (`:764-768`).

### 3. `backend/scripts/golden_eval.py` — deterministic golden-question scorer

**Invocation** (`golden_eval.py:492-518`):
- `score-forecast-file --forecast PATH [--golden PATH] [--bins 10] [-o OUT.json] [--markdown OUT.md] [--to-ledger] [--ledger-dir DIR]`
- `score-ledger [--ledger-dir DIR] [--bins 10] [-o] [--markdown]`

**Setup**
- `sys.path` gets `backend/` (`golden_eval.py:57`).
- `GOLDEN_PATH = backend/tests/eval/golden_questions.json` (`:59-61`). The file currently holds 30 questions, each with `id, question, category, difficulty, as_of_date, resolution_date, resolution_criteria, resolved_outcome`.
- `DEFAULT_BINS = 10` and `_EPS = 1e-9` (`:63-64`).

**Pure core** (`:67-286`)
- `_coerce_prob` returns `None` for non-numeric, NaN, inf, or values outside [0, 1] (`:71-81`).
- `binary_brier = (p − y)²` (`:84-90`).
- `binary_log_score = ln(p or 1−p)` with p clamped to `[eps, 1−eps]` (`:93-102`).
- `calibration_bins` (`:105-144`) uses equal-width bins and puts p in bin `min(bins−1, int(p*bins))`, so p = 1.0 lands in the last bin. Per bin it reports `{range, count, mean_predicted, observed_frequency, gap}`. `ECE = Σ(n_k/N)·gap_k`, rounded to 4 decimals. It is `None` when N = 0.
- `score_pairs(scored, bins, threshold=0.5)` (`:147-182`) returns `n, mean_brier, mean_log_score, resolution_accuracy ((p ≥ 0.5) == outcome), base_rate, calibration, by_category, by_difficulty`.
- `_breakdown` reports per-group `n, mean_brier, resolution_accuracy, base_rate`. A missing key falls into `"unknown"` (`:185-204`).
- `load_golden_set` accepts a list or `{"questions": [...]}`. It raises `ValueError` on an empty set, a missing `id` or a non-bool `resolved_outcome` (`:207-222`).
- `index_golden`: on duplicate ids the later entry overwrites the earlier one (`:225-227`).
- `extract_binary_forecasts` accepts a full dict, `{"forecast": {...}}` or a bare list (`:230-244`).
- `match_forecasts` (`:247-286`):
  - Matching is **by `id` only**.
  - A matched row with a bad probability goes into `invalid_probability_ids` and is not scored. Invalid ids are therefore excluded from `unmatched_forecast_ids` but still appear in `unmatched_golden_ids` (`:283-284`).
  - Each scored row carries per-question `brier` and `log_score`.

**Rendering and output**
- `render_markdown` builds the overview table, the category and difficulty tables, non-empty calibration bins, and a per-question table (`:295-351`).
- `_write_outputs` writes `-o` JSON and/or `--markdown`. If neither is given it prints the JSON to stdout (`:397-409`).

**Ledger bridge (opt-in)**
- `_ledger_enabled` is true when `Config.GOLDEN_EVAL_LEDGER` is set or `--to-ledger` is passed (`:356-364`).
- `_append_matched_to_ledger` calls `forecast_ledger.append_golden_result(...)` once per matched row (`:367-394`).
- That function writes a resolved two-scenario YES/NO entry with `golden: True, record_class: "evaluation", characterization_only: True`. It **redirects** any target that resolves to the production ledger dir to `evaluation_ledger_dir()`, a sibling `_evaluation_ledger`, and marks the entry `ledger_redirected` (`backend/app/services/forecast_ledger.py:113-189`, redirect at `:171-178`, dir at `:38-46`).

**Commands**
- `cmd_score_forecast_file` (`:414-442`): load the golden set and forecast, match, score, optionally append to the ledger, then write the report. **Exit code 3** when nothing matched, which signals misaligned ids; it is not a quality gate (`:440-442`).
- `cmd_score_ledger` (`:445-489`):
  - `read_ledger(dir)` (`backend/app/services/forecast_ledger.py:212`).
  - `backtest.calibration_report` over resolved entries that have `outcome` and `scenarios`.
  - `calibration_summary(include_evaluation=True)` (`backend/app/services/forecast_ledger.py:233-234`).
  - A per-category binary breakdown of `golden` rows that uses the `YES` scenario's probability (`:462-476`).
  - It always exits 0.

### 4. `backend/scripts/eval_forecast_quality.py` — rubric LLM-judge regression gate

**Invocation** (`eval_forecast_quality.py:410-435`):
- `score --report PATH [--scenario JSON] [--judge-provider P] [--api-key K] [--k 3] [--live]`
- `run [--scenarios-dir DIR] [--judge-provider P] [--api-key K] [--k 3] [--tolerance 0.5] [--update-baseline] [-o OUT] [--live]`

**Paths**: `EVAL_DIR = backend/tests/eval`, which holds `scenarios/`, `rubric.md` and `baseline_scores.json` (`eval_forecast_quality.py:43-47`).

**Constants**
- `RUBRIC_DIMENSIONS = (groundedness, coverage, calibration, contradiction, citation_density)` (`:51-53`). These match the headings in `backend/tests/eval/rubric.md:14-49`.
- Scores run 0..5 (`:54`). `DEFAULT_TOLERANCE = 0.5` and `DEFAULT_K = 3` (`:55-56`).

**Pure core**
- `clamp_score` maps garbage, NaN or inf to 0.0, the worst score, so a malformed reply can only fail the gate (`:63-75`).
- `normalize_judge_scores` accepts a flat dict or `{"scores": {...}}`. Missing dimensions become 0 (`:78-88`).
- `aggregate_scores` reports per-dimension `{mean, stdev (population), min, max, n}` (`:91-108`).
- `compare_vs_baseline(agg, baseline, default_tolerance)` (`:111-145`):
  - With no or an empty baseline it returns `{passed: None, missing_baseline: True}` (`:121-122`).
  - `baseline["tolerance"]` overrides the default (`:123-125`).
  - A dimension passes when `mean ≥ baseline − tol` (`:136`). Dimensions absent from the baseline get `passed: None` and do not affect `all_pass` (`:131-134`).
- `objective_signals(md, forecast)` (`:148-173`) returns `forecast_extractor.audit_citation_grounding` coverage, quantitative and cited counts, plus `report_chars`. When `forecast` is given it also returns `scenario_count` and `probability_sum`.
- `parse_rubric` turns `## [n.] <dimension>` headings into a dict (`:176-196`).
- `load_scenario` requires `name` (`:199-205`). `discover_scenarios` returns the sorted `*.json` files (`:208-215`).
- `resolve_report_path` (`:218-228`) uses `scenario.report_path`, relative to the repo root. Otherwise it falls back to `backend/uploads/pipelines/<pid>/report/report.md`.
- `build_judge_messages` (`:231-255`) truncates the report to 48,000 chars (`:235-236`). The system prompt is Chinese and asks for strict JSON with integer scores 0–5 plus the rubric text (`:238-244`). The user message carries the objective signals, the optional `expected_outcome` and the report (`:245-251`).

**Live judge**
- `judge_once` calls `llm.chat_json(messages, temperature=0.0, max_tokens=512)` (`:260-263`).
- `judge_report` runs `k` passes. A pass that raises is recorded as an all-zero sample and a warning goes to stderr (`:266-288`).
- `_load_report_and_forecast` also loads a sibling `forecast.json` if one exists (`:296-306`).
- `_build_judge_client(provider, api_key)` (`:309-330`):
  - With no provider, or the global provider, it returns `LLMClient()`.
  - Otherwise it returns `LLMClient(provider=..., api_key from the flag or PROVIDER_META[key_env], base_url and model from PROVIDER_META defaults)` for OpenAI-compatible providers.
- `_eval_allowed` is true when `Config.EVAL_ENABLED` is set or `--live` is passed (`:333-336`).

**Commands**
- `cmd_score` (`:341-354`): if not allowed, print the opt-in notice and **return 0**. Otherwise judge and print the JSON.
- `cmd_run` (`:357-407`):
  - Not allowed returns 0. No scenarios returns 2.
  - Each scenario is resolved, judged and gated against `baseline[name]`. A missing report gives `{"skipped": True}` (`:376-379`).
  - It writes `-o` or prints.
  - `--update-baseline` overwrites `baseline_scores.json` with the per-dimension means plus `tolerance` and returns 0 regardless of the gate (`:401-405`).
  - Otherwise it **exits 1 when any scenario's gate failed** (`:406-407`).

### 5. `backend/scripts/model_comparison.py` — multi-provider report comparison

**Invocation** (`model_comparison.py:482-520`):
- `compare <pipeline_id> --providers P1 P2 ... [-o OUT] [--api-key provider=key ...] [--no-skip-unavailable] [--self-critique] [--force]`
- `providers`

**Setup**: `sys.path` gets `backend/` (`:49`). Module import pulls in `Config`, `ensemble`, `forecast_extractor`, `pipeline_orchestrator`, `report_agent`, `LLMClient` and telemetry (`:51-66`), so even `providers` imports the full backend. `_PROVIDER_RE = ^[a-z0-9_-]+$` (`:71`).

**Functions**
- `provider_credentials_ok(provider, api_key=None)` (`:75-107`) is a local check with no network.
  - It fails for an unknown provider (`:86-88`).
  - For a non-OpenAI-compatible (CLI) provider, the `claude` / `codex` binary must be on PATH (`shutil.which`) (`:90-95`).
  - For an OpenAI-compatible provider it needs `--api-key`, or `Config.LLM_API_KEY` when the provider is the global one, or the `PROVIDER_META[...]["key_env"]` environment variable (`:97-107`).
  - Providers come from `Config.PROVIDER_META`: `claude-cli, codex-cli, openai, kimi, minimax, deepseek, qwen, glm` (`backend/app/config.py:858`).
- `_build_client_for(provider, api_key)` (`:110-136`) builds a per-instance `LLMClient`. A non-global OpenAI-compatible provider gets the `PROVIDER_META` default base URL and model. It never mutates `Config.LLM_PROVIDER`.
- `_load_base_context(base_pipeline_id)` (`:140-172`) calls `PipelineManager.load`. It requires `simulation_id`, `graph_id` and `prompt` (or `simulation_requirement`), else raises `ValueError` (`:147-160`). It loads `situation_brief / actors / sources / research_report` through `load_research_dossier_for_simulation` (`:162`; `backend/app/services/pipeline_orchestrator.py:6744`).
- `_safe_report_id` returns `cmp__<base[:48] sanitized>__<provider[:24] sanitized>__<uuid8>` (`:175-183`).
- `_run_report_for_provider(ctx, provider, api_key, *, self_critique)` (`:187-272`):
  1. Build the client. A failure is recorded and the provider skipped (`:213-218`).
  2. `set_run_context("compare__<report_id>", "report")` (`:221`).
  3. `ReportAgent(graph_id, simulation_id, simulation_requirement=prompt, llm_client, situation_brief, actors, sources, research_report)` (`:223-232`).
  4. `generate_report(progress_callback, report_id)`. A FAILED status raises `RuntimeError` (`:237-239`).
  5. `extract_structured_forecast(markdown, client, situation_brief)`, then optionally `self_critique_forecast`, then `citation_audit`, then `provider` (`:246-252`).
  6. Write `<reports>/<report_id>/forecast.json` (`:254-255`).
  7. Take an `LLMMeter.snapshot(run_id)`.
  - Any exception is caught and stored in `error` (`:266-268`). The `finally` clears the run context and resets the meter (`:269-271`).
- `_norm_name` lowercases, strips punctuation (keeping CJK) and collapses whitespace (`:276-278`).
- `build_comparison(base, results)` (`:281-351`):
  - Only `ok` results are aggregated, through `aggregate_forecasts(forecasts)`.
  - Each `per_scenario` row has `{scenario, mean_probability, stdev, min, max, support, support_ratio, resolution_criteria, by_provider{provider: prob or None}}`. Rows are sorted by `mean_probability` descending (`:302-329`).
  - It also returns `agreement`, `headline`, `horizon`, `confidence_by_provider`, `citation_coverage_by_provider`, `report_paths`, `telemetry_by_provider` (the `snapshot.total` slice, `:354-358`), `failed` and `schema_version: 1`.
- `compare_models(...)` (`:362-419`) dedupes and lowercases providers and drops names failing the regex. If none remain it raises `ValueError` (`:384-396`). For each provider in sequence, a credentials failure is skipped (the default) or recorded as failed (`--no-skip-unavailable`) (`:403-412`).
- `cmd_compare` (`:423-469`):
  - The gate needs `Config.MODEL_COMPARISON_ENABLED` or `--force`, else it prints to stderr and **exits 3** (`:426-433`).
  - A malformed `--api-key` (no `=`) exits 2 (`:436-441`). A `ValueError` from `compare_models` exits 2 (`:451-453`).
  - On success it writes `-o` atomically or prints, and exits 0.
- `cmd_providers` prints `{provider, available, reason}` for every `PROVIDER_META` key (`:472-479`).

### 6. `backend/scripts/forecast_tools.py` — ensemble and backtest CLI

- `sys.path` gets `backend/` (`forecast_tools.py:25`). It imports `aggregate_forecasts`, `calibration_report` and `score_forecast` (`:27-28`).
- `ensemble FILES... [-o OUT]` (`:36-46`, `:63-66`) loads each `forecast.json` and runs `aggregate_forecasts`, then writes or prints. The `-o` summary prints `n_runs`, the scenario count and `agreement`.
  - The aggregation uses semantic bucket alignment by default (`backend/app/config.py:340`) and log-odds pooling with `ENSEMBLE_EXTREMIZE_A=1.0` (`backend/app/config.py:333`; `backend/app/services/ensemble.py:204-240`, `:118`).
- `backtest RESOLVED.json [--bins 5]` (`:49-57`, `:67-70`): the input must be a JSON list of `{forecast, outcome}`, else it exits 2. It prints `calibration_report(...)` plus a `per_forecast` list of `score_forecast(...)` (multi-class Brier, `backend/app/services/backtest.py:41-44`).

### 7. `backend/scripts/test_deerflow_deep_research.py` — DeerFlow bridge contract checks

Run with `python backend/scripts/test_deerflow_deep_research.py`. It uses only the stdlib and loads the bridge by file path (`test_deerflow_deep_research.py:15-20`). The checks run in the order of `:163-171`:
1. `assert_bridge_synced` (`:31-33`): `deerflow_bridge/deerflow_research.py` must be byte-identical to the deployed `deer-flow/deerflow_research.py`. They are currently identical.
2. `assert_skill_synced` (`:36-61`):
   - The overlay `deerflow_bridge/skills/deep-research/SKILL.md` must contain 8 literal markers: `"S1 — Primary / authoritative"`, `"Evidence Ledger"`, `"Synthesis Gate"` and five others.
   - The deployed `deer-flow/skills/public/deep-research/SKILL.md` must equal the overlay, if it exists.
3. `assert_loop_detection_patch` (`:64-87`):
   - The overlay middleware must contain `_reset_run_scoped_loop_state`, called within 400 chars of `def before_agent` and `async def abefore_agent`.
   - The deployed copy under `deer-flow/backend/packages/harness/.../loop_detection_middleware.py` must be byte-identical.
4. `assert_deep_prompt_contract` (`:104-118`): the deep prompt contains `MULTI-PASS` and `Do NOT write the final dossier yet`. `DEEP_RESEARCH_PHASES` has 5 labels in a fixed order. The deep synthesis prompt contains `"8,000"` and `"multi-pass deep investigation"`.
5. `assert_deep_runner_sequence` (`:121-160`): it monkeypatches `run_streamed_turn` and `synthesize_from_thread`. It expects 6 turns with fixed labels, an opening recursion limit of 220 and a sum of limits of 1660.
6. `assert_harness_marker_stripping` (`:90-101`): `strip_think` removes `[FORCED STOP]` and `[LOOP DETECTED]` lines and keeps the substantive lines.

### 8. `backend/scripts/test_graphiti_migration.py` — shim smoke test (live LLM)

- `main()` (`test_graphiti_migration.py:68-114`) runs these steps:
  1. `Zep(api_key="ignored")`, then `graph.create(graph_id="mirofish_test<hex10>")`.
  2. `set_ontology` with classes built dynamically, using the same construction as `graph_builder.set_ontology` (`:25-54`): `Person{role}`, `Organization{kind}`, and edge `INVOLVES{detail}` from Organization to Organization.
  3. `add_batch` with 3 mixed English and Chinese semiconductor chunks (`:57-65`).
  4. `fetch_all_nodes` / `fetch_all_edges`.
  5. `graph.search` with `scope=edges` and with `scope=nodes`.
  6. `node.get(uuid_)` without a `graph_id`, then `node.get_entity_edges`.
- It asserts at least 1 node and at least 1 edge (`:112-113`).
- There is no cleanup. The test graph persists in the local store under `GRAPHITI_DATA_DIR`, which defaults to `backend/uploads/graphiti_db` (`backend/app/config.py:1021-1023`).

### 9. `backend/scripts/test_graphiti_services.py` — service-stack smoke test (live LLM)

`main()` (`test_graphiti_services.py:51-125`) runs these steps:
1. `GraphBuilderService().create_graph`, `set_ontology(ONTOLOGY)` (`:27-39`), `TextProcessor.split_text(TEXT, 350, 40)`, `add_text_batches(batch_size=5)`, then `_wait_for_episodes`, a no-op on local Graphiti (`:52-67`).
2. `get_graph_data`, then key-contract assertions on the node and edge dicts (`:70-81`).
3. `ZepEntityReader.filter_defined_entities(enrich_with_edges=True)`, which needs `filtered_count > 0` (`:84-89`).
4. `ZepToolsService.quick_search`, `panorama_search` and `insight_forge`. `insight_forge` makes LLM sub-queries. Each call needs non-empty results (`:92-106`).
5. `ZepGraphMemoryUpdater(graph_id)`, which starts, takes 2 `AgentActivity` posts, sleeps 2 s, stops and prints stats (`:109-122`).

The graph is not cleaned up.

### 10. `backend/scripts/test_pipeline_resume.py` — offline resume and cancel regression

- `main()` (`test_pipeline_resume.py:265-298`) points `Config.PIPELINE_DATA_DIR` at a fresh `tempfile.mkdtemp(prefix="mirofish_resume_test_")` (`:266-267`). It replaces `PipelineOrchestrator._run` with a fake that blocks on a `threading.Event` for up to 30 s (`:271-277`) and restores it in a `finally` (`:293-295`).
- `_write_state(pid, **overrides)` (`:36-66`) writes a minimal failed state: the graph stage is failed and research and ontology are completed, with `updated_at "2026-06-10T00:10:00+00:00"`.
- The tests:

| Test | Lines | What it checks |
|---|---|---|
| mark_failed status | `:69-82` | The `mark_failed` status parameter accepts `failed` and `cancelled` |
| Resume reset | `:85-104` | Resume resets failed stages to pending, gives a new `task_id`, sets `research_pid=None`, makes `resume_count=1`, keeps completed stages, and adds the bands for `prepare`, `run` and `report` |
| Resume rejections | `:107-127` | Resume rejects a completed pipeline ("已完成"), a running one ("仍在运行"), and a missing one (`FileNotFoundError`) |
| Double-resume race | `:130-159` | 8 concurrent resumes, exactly one wins |
| Orphan cancel | `:162-172` | Cancelling an orphan returns `{"ok": True, "status": "cancelled"}` and persists it |
| Delete and clean | `:175-216` | Delete removes terminal pipelines only, path traversal is refused, a live pipeline returns `still_running`, and `clean_terminal` removes failed and cancelled ones |
| Research handoff | `:219-238` | `_load_research_handoff` rejects a short error-text report and tolerates missing actors and sources once the text is at least 400 chars |
| Log rotation | `:241-262` | `SimulationRunner._rotate_stale_action_logs` rotates to `actions.prev.jsonl`, overwrites the previous rotation, and is a no-op on a missing dir (`backend/app/services/simulation_runner.py:1310`) |

### 11. `backend/scripts/test_profile_format.py` — prints OASIS profile output

- `test_profile_formats()` (`test_profile_format.py:20-127`) builds 2 `OasisAgentProfile`s and a `__new__`-constructed `OasisProfileGenerator`. In a temp dir it calls `_save_twitter_csv` and `_save_reddit_json` and **prints** whether the required fields exist. There are no asserts and the exit code is always 0.
  - The Twitter required list it checks is `user_id, user_name, name, bio, friend_count, follower_count, statuses_count, created_at` (`:89-90`).
  - The Reddit required list is `realname, username, bio, persona` (`:113`).
- `show_expected_formats()` (`:130-159`) prints sample formats.

### 12. `backend/scripts/test_zep_rate_limit.py` — offline 429 and graph-cache regression

There is no `sys.path` insert (`test_zep_rate_limit.py:8-10`). It needs the backend venv's editable install or `PYTHONPATH=backend`.
1. `assert_rate_limit_parser` (`:21-29`): a 429 text with `retry-after: 44` must be classified as a rate limit and give a delay of 45 (buffer 1, max 90).
2. `assert_zep_tool_retry_uses_retry_after` (`:32-54`): it monkeypatches `zep_tools.time.sleep`. `_call_with_retry(flaky, ..., max_retries=2)` must succeed on attempt 2 after sleeping `[45]` (`backend/app/services/zep_tools.py:580-610`). This assumes the default `ZEP_RATE_LIMIT_BUFFER_SECONDS=1.0` and `ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS=90.0` (`backend/app/config.py:1043-1044`).
3. `assert_graph_snapshot_is_reused` (`:57-109`): `get_simulation_context` followed by `get_graph_statistics` must call `fetch_all_nodes` and `fetch_all_edges` exactly once each, which proves the graph snapshot is cached.

### 13. `scripts/salvage_orphaned_pipelines.py` — failed-to-completed (degraded) repair

**Invocation**: `python scripts/salvage_orphaned_pipelines.py [--apply] [--include-cancelled] [--pipelines-dir D] [--reports-dir D]` (`salvage_orphaned_pipelines.py:22-28`, `:215-227`).
- The default dirs are `<repo>/backend/uploads/{pipelines,reports}`, anchored at the script's location (`:208-212`).
- It uses only the stdlib and never imports `app` (`:18-20`).

**Pieces**
- `SALVAGE_NOTE` (`:40-41`) is byte-identical to the note `reconcile_orphans` uses (`backend/app/services/pipeline_orchestrator.py:7693-7694`, relative lines 57-58 of the `reconcile_orphans` block).
- `_read_json` treats a corrupt file as missing (`:48-55`).
- `_write_json_atomic` writes `mkstemp` `.salvage-*.tmp` in the same dir, then `fsync`, then `os.replace` (`:58-73`).
- `eligible_report(data, reports_dir)` (`:76-101`) mirrors `PipelineOrchestrator._orphan_completed_report` (`backend/app/services/pipeline_orchestrator.py:7738-7770`), with one addition: it rejects a `report_id` containing a path separator or `..` (`:86-87`). The criteria are:
  - `report_id` is a non-empty str.
  - `stages.report.status == "completed"`.
  - `full_report.md` is a file larger than 0 bytes.
  - `forecast.json` parses to a non-empty dict.
- `salvage_state(data, note)` (`:104-144`) mirrors `PipelineManager.mark_salvaged_completed` (`backend/app/services/pipeline_orchestrator.py:1024-1074`):
  - `status="completed"`, `error=None`, `global_progress=100`, and a new `updated_at`.
  - `options.pipeline_health` is created as `degraded`, or an `ok` value is downgraded to `degraded`; the note is appended to its `issues`.
  - `options.ensemble_done=True`, `options.ensemble_skipped=note`, and `options.salvaged_orphan_at`.
  - The report stage gets `completed`, progress 100 and no error, plus `finished_at` if it was missing. A `多种子集成` message is replaced.
  - `current_stage="report"`.
- `find_candidates` (`:147-172`) scans `sorted(os.listdir(pipelines_dir))/*/pipeline_state.json`. It keeps states with status `failed`, plus `cancelled` when `--include-cancelled` is set, that also pass eligibility.
- `run(...)` (`:175-205`) prints `[DRY-RUN]` / `[APPLY]` lines. On apply it re-reads each state and **skips it if it has become `running`** (`:195-198`), otherwise it rewrites atomically (`:199`). It returns the candidate list. `main` always exits 0.

### 14. `scripts/watch_pipeline_progress.py` — stage-transition follower

**Invocation**: `python scripts/watch_pipeline_progress.py --pipelines-dir DIR [--interval 1.0] [--once]` (`watch_pipeline_progress.py:153-163`). `scripts/start.sh` runs `--once >/dev/null` as a preflight (`scripts/start.sh:503`) and then runs it in the background with restarts (`scripts/start.sh:591`, `:635-640`).

**Constants** (`:15-35`)
- Active states: `pending, running, processing, resuming`. Terminal states: `completed, failed, cancelled`.
- `STAGE_ORDER` lists the 6 stages. `STAGE_LABELS` maps `run` to `SIMULATION`.
- `STATUS_MARKS`: ○ pending, ▶ running, ↻ resuming, ✓ completed, ✕ failed, ■ cancelled, ↷ skipped.

**Functions**
- `_clean` collapses whitespace and truncates to 220 chars (`:38-39`).
- `_progress_bucket` clamps to 0..100 and buckets to multiples of 5, keeping 0 and 100 exact (`:42-49`).
- `_stage_signature = (status, progress bucket, error)`. The stage `message` is not part of it (`:52-57`).
- `_ordered_stage_names` returns the known stages first, then any extras sorted (`:60-62`).
- `_format_stage` produces `"[workflow <pid>] <mark> <LABEL>[ <p>%][ — <error or message>]"` (`:65-72`).
- `progress_events(previous, current, pid)` (`:75-115`):
  - For a newly seen pipeline it emits `◆ PIPELINE <status>` plus every non-pending stage.
  - Otherwise it emits a line for each stage whose signature changed.
  - It also emits a `PIPELINE <terminal status>[ — error]` line when the status changes into a terminal state.
- `_read_state` returns `None` on I/O, decode or JSON errors, or a non-dict (`:118-123`).
- `PipelineProgressWatcher.poll(initial=False)` (`:126-150`):
  - It globs `*/pipeline_state.json` in sorted order. On the first poll in follow mode it records non-active pipelines silently (`:143-145`).
  - Pipelines that vanish from disk are dropped from memory (`:148-149`).
- `main` (`:153-183`) installs SIGINT and SIGTERM handlers that set a stop flag (`:166-173`). It prints the first poll, with `initial` set unless `--once`. In follow mode it then loops with `sleep(max(0.2, interval))`.

## Control flow

**Export (full)**: `main` (`export_demo_site_data.py:1040`) → `export_run` (`:915`) → [strict: `validate_publishable_run` (`:221`)] → `export_research_log` (`:114`) → `export_dossier` (`:775`), which calls `published_dossier_variants` → `copy_markdown_assets` → `rebase_markdown_assets` → `_write_language_set` → copy actors and sources → `_load_bound_project` (`:195`) → ontology.json → `export_graph` (`:641`), with `rebuild_graph` (`:613`) on a non-strict 404 → graph.json → `export_forum` (`:580`) → `export_report` (`:806`) → meta.json (`:1017`).

**Export (refresh)**: `--research-log-only` → `refresh_demo_research_log` (`:153`). `--reports-only` → `refresh_demo_reports` (`:842`) → `export_report` and, conditionally, `export_dossier` → meta.json merge.

**Backfill**: `main` (`backfill_report_visuals.py:772`) → `backfill_one` (`:739`) → `_backfill_one_impl` (`:445`). That runs `_backup` (`:391`), then `_artifacts` (`:342`), then the forecast repair and `synchronize_market_comparison` (`:277`). Next come `ReportVisualizer.build_all` and the primary repair chain (`:517-555`), then `_enforce_final_publish_audit` (`:577`). The variant loop calls `_audit_translation_variant` (`:615`), then `ReportManager.export_pdf` runs (`:697`). On an exception, `_restore_from_backup` (`:414`) runs and `replay_failure.json` is written.

**Golden eval**: `main` (`golden_eval.py:492`) → `cmd_score_forecast_file` (`:414`) → `load_golden_set` → `index_golden` → `extract_binary_forecasts` → `match_forecasts` → `score_pairs`, optionally `_append_matched_to_ledger`, then `_write_outputs`. `cmd_score_ledger` (`:445`) → `read_ledger` → `calibration_report` + `calibration_summary` → golden breakdown.

**LLM-judge**: `cmd_run` (`eval_forecast_quality.py:357`) → `discover_scenarios` → for each scenario `resolve_report_path` → `judge_report` (`:266`), which is `objective_signals` → `build_judge_messages` → k × `judge_once` → `aggregate_scores` → `compare_vs_baseline` → output, with an optional baseline overwrite.

**Model comparison**: `cmd_compare` (`model_comparison.py:423`) → gate → `compare_models` (`:362`) → `_load_base_context` → for each provider `provider_credentials_ok` → `_run_report_for_provider` (`:187`) → `build_comparison` (`:281`).

**Watcher in production**: `scripts/start.sh` (`:499-504` preflight, `:591` background launch, `:635-640` restart up to `FOLLOWER_RESTART_LIMIT`) → `watch_pipeline_progress.main` → `PipelineProgressWatcher.poll` every `interval`.

## Data & artifacts

### Exporter inputs (read)

| Path | Fields used | Anchor |
|---|---|---|
| `backend/uploads/pipelines/<pid>/pipeline_state.json` | `pipeline_id, status, stages.*.{status,error}, project_id, graph_id, report_id, simulation_id, prompt, created_at, mode` | `export_demo_site_data.py:224-246`, `:1017-1026` |
| `backend/uploads/pipelines/<pid>/handoff/` | `research_progress.log`, `track_<n>/research_progress.log`, `research_attempts/*.log`, `research_report.md`, `research_report.<lang>.md`, `research_report.translation.<lang>.json{status,source_sha256}`, `research_report.final_audit.<lang>.json{hard_passed,markdown_sha256}`, `actors.json`, `sources.json`, `charts/*` | `export_demo_site_data.py:728-748`, `:942-945`; `backend/app/services/research_progress.py:418-466` |
| `backend/uploads/projects/<project_id>/project.json` | `project_id, graph_id, ontology.{entity_types,edge_types}, analysis_summary` | `export_demo_site_data.py:197-217`, `:953-958` |
| `backend/uploads/reports/<rid>/` | `meta.json{report_id,simulation_id,graph_id,status}`, `full_report.md`, `full_report.<lang>.md`, `forecast.json`, `final_audit.json{report_id,read_only,disk_matches_memory,hard_passed,publish_gate.passed,scenario_contract.valid,markdown_sha256,forecast_sha256,citation_grounding.resolved_coverage,semantic_citations.passed}`, `charts/*` | `export_demo_site_data.py:254-401`, `:828-839` |
| `backend/uploads/simulations/<sid>/` | `state.json`, `simulation_config.json{agent_configs|agents}`, `run_state.json{total_rounds}`, `run_summary.json{simulation_health, agent_count, rounds_executed, total_actions, organic_action_count}`, `{twitter,reddit}/actions.jsonl` | `export_demo_site_data.py:277-372`, `:580-610`, `:997-999` |

### Exporter outputs (`docs/demos/<key>/`)

| File | Shape |
|---|---|
| `research_log.txt` | Merged progress lines (`export_demo_site_data.py:139-144`) |
| `dossier.md`, `dossier.<lang>.md`, `research-charts/*` | Rebased dossier text and its charts (`export_demo_site_data.py:775-803`) |
| `actors.json`, `sources.json` | Verbatim copies (`export_demo_site_data.py:942-945`) |
| `ontology.json` | `{entity_types, edge_types, analysis_summary}` (`export_demo_site_data.py:954-958`) |
| `graph.json` | `{nodes:[{id,name,labels,summary}], links:[{source,target,name,fact}], graph_id}` (`export_demo_site_data.py:670-684`, `:982-983`) |
| `forum.json` | `{twitter:[{round,agent,type,content,ok}], reddit:[...]}` (`export_demo_site_data.py:580-610`) |
| `report.md`, `report.<lang>.md`, `charts/*` | Report text and its charts (`export_demo_site_data.py:806-825`) |
| `meta.json` | Keys listed at `export_demo_site_data.py:1017-1036`. `research_log` is `{line_count, source_count, complete, event_fidelity[, retained_legacy_artifact]}`. `*_languages` is `{en|zh|und: file}`. `artifact_sha256` maps a relative path to its SHA-256. |

The site consumes these in `docs/demo.html`: the language maps at `:99-117`, the research log and meta at `:155-156`, the graph at `:249-279` and the forum at `:321`.

### Backfill (per report dir, `Config.PIPELINE_DATA_DIR` plus `ReportManager.REPORTS_DIR`)

- **Reads** `forecast.json`, `ensemble_forecast.json`, `comparison.json`, `meta.json` and `citations.json`. From the handoff it reads `actors, timeline, quantitative, sources, contested, prediction_markets, graph_priors(_structural), research_report.md`, and from the simulation dir `world_state_trajectory.json` (`backfill_report_visuals.py:342-364`, `:375`, `:580`).
- **Writes**:
  - `.codex-backup-<UTC>/` (`:391-411`) and, on failure, `replay_failure.json` (`:756-763`).
  - `forecast.json` with `binary_forecasts`, `binary_quality`, `market_comparison` and `quality.lint` (`:502`, `:561`).
  - `market_comparison.json`, which may be deleted (`:300-310`).
  - `charts/*` and `viz_manifest.json`, through `build_all`.
  - `full_report.md` (`:555`).
  - `final_audit.json` and `citations.json`, written by the audit and citation finalization in `report_agent`.
  - Per variant: `full_report.<lang>.md`, `citations.<lang>.json` and `final_audit.<lang>.json` (`:661-663`), or deletions for a failing variant (`:634-639`).
  - `meta.json` with `markdown_content`, `translations` and `unavailable_translations` (`:689`).
  - `full_report[.<lang>].pdf` and `pdf_export.json` (`:697-718`).

### Eval and comparison

- **golden_eval** reads `backend/tests/eval/golden_questions.json` and a `forecast.json` with `binary_forecasts[{id, probability}]`. It writes the `-o` / `--markdown` files you name. With the ledger option it appends to `<FORECAST_LEDGER_DIR or backend/uploads/pipelines/_forecast_ledger>/../_evaluation_ledger/ledger.jsonl` (`backend/app/services/forecast_ledger.py:23-46`, `:171-182`).
- **eval_forecast_quality** reads `rubric.md`, `baseline_scores.json` (per-scenario dimension floors plus `tolerance`, and a `_comment` key) and `scenarios/*.json` (`name, question, report_path, expected_outcome`). All 3 committed scenarios point at `docs/demos/*/report.md`. It writes the `-o` file you name and, with `--update-baseline`, `baseline_scores.json` (`eval_forecast_quality.py:401-404`).
- **model_comparison** writes a full report bundle per provider under `uploads/reports/cmp__...` through `generate_report`, overwrites that bundle's `forecast.json` (`model_comparison.py:254-255`), and writes the `-o` comparison JSON you name.
- **forecast_tools** reads `forecast.json` files or a resolved list, and writes `-o` or stdout.

### Root scripts

- **salvage** reads and writes `<pipelines>/<pid>/pipeline_state.json`. It reads `<reports>/<rid>/{full_report.md, forecast.json}`.
- **watcher** reads `<pipelines-dir>/*/pipeline_state.json` and writes only to stdout. It keeps `states: {pipeline_id: last payload}` in memory (`watch_pipeline_progress.py:129`).

## Config / env knobs

| Name | Default | Effect | Anchor |
|---|---|---|---|
| `EVAL_ENABLED` | `False` | Enables the live LLM judge (otherwise `--live` is needed) | `backend/app/config.py:431`; `eval_forecast_quality.py:336` |
| `GOLDEN_EVAL_LEDGER` | `False` | Lets golden_eval append matched outcomes to the (evaluation) ledger | `backend/app/config.py:435`; `golden_eval.py:361` |
| `MODEL_COMPARISON_ENABLED` | `False` | Gate for `model_comparison compare` (`--force` bypasses it) | `backend/app/config.py:389`; `model_comparison.py:426` |
| `FORECAST_LEDGER_DIR` | `''`, which means `PIPELINE_DATA_DIR/_forecast_ledger` | Ledger location for golden_eval; the evaluation ledger is its sibling `_evaluation_ledger` | `backend/app/config.py:278`; `backend/app/services/forecast_ledger.py:23-46` |
| `REPORT_PDF_EXPORT` | `True` | When false, `export_pdf` returns `None`, so `backfill --apply` raises and rolls back | `backend/app/config.py:244`; `backend/app/services/report_agent.py:13479`; `backfill_report_visuals.py:699-701` |
| `ENSEMBLE_SEMANTIC_ALIGN` | `true` | Scenario bucket alignment in `forecast_tools ensemble` and `model_comparison` | `backend/app/config.py:340`; `backend/app/services/ensemble.py:167` |
| `ENSEMBLE_EXTREMIZE_A` | `1.0` | Log-odds pooling exponent for ensemble probabilities | `backend/app/config.py:333`; `backend/app/services/ensemble.py:206-210` |
| `DEFAULT_CHUNK_SIZE` / `DEFAULT_CHUNK_OVERLAP` | 2500 / 250 | Chunking in the exporter's `rebuild_graph` | `backend/app/config.py:1055-1057`; `export_demo_site_data.py:633` |
| `ZEP_API_KEY` | `'local-graphiti'` sentinel | Passed to `GraphBuilderService` by the exporter | `backend/app/config.py:1038`; `export_demo_site_data.py:627`, `:668` |
| `GRAPHITI_DATA_DIR` | `backend/uploads/graphiti_db` | Where smoke-test graphs persist | `backend/app/config.py:1021-1023` |
| `ZEP_RATE_LIMIT_BUFFER_SECONDS` / `ZEP_RATE_LIMIT_MAX_SLEEP_SECONDS` | 1.0 / 90.0 | `test_zep_rate_limit` hard-codes the resulting 45 s | `backend/app/config.py:1043-1044`; `test_zep_rate_limit.py:29`, `:54` |
| `PIPELINE_DATA_DIR`, `OASIS_SIMULATION_DATA_DIR` | `backend/uploads/{pipelines,simulations}` | Backfill input roots; `test_pipeline_resume` overrides the first | `backend/app/config.py:1581`, `:1080`; `backfill_report_visuals.py:360`, `:448`; `test_pipeline_resume.py:267` |
| `LLM_PROVIDER`, `LLM_API_KEY`, `PROVIDER_META[*].key_env` (for example `KIMI_API_KEY`, `MINIMAX_API_KEY`) | from `.env` | Judge and comparison client construction and credential checks | `model_comparison.py:97-136`; `eval_forecast_quality.py:309-330`; `backend/app/config.py:858-870` |
| `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT`, `RESEARCH_PARALLEL_PHASES` | 300, `true` | Change the deep-runner turn plan that `test_deerflow_deep_research` asserts | `deerflow_bridge/deerflow_research.py:12476`, `:12559` |
| CLI-only knobs | — | `--require-publishable`, `--skip-graph`, `--graph-api`, `--only`, `--research-log-only`, `--reports-only` (exporter); `--apply` / `--target` (backfill, salvage); `--to-ledger` / `--ledger-dir` / `--bins` (golden); `--k` / `--tolerance` / `--update-baseline` / `--live` (judge); `--force` / `--self-critique` / `--no-skip-unavailable` (comparison); `--interval` / `--once` (watcher) | Argument parsers listed in the walkthrough |

## External calls

| Script | Call | Anchor |
|---|---|---|
| export_demo_site_data | HTTP GET `<graph_api>/api/graph/data/<id>?full=true` (urllib, 120 s timeout) | `export_demo_site_data.py:653-659` |
| export_demo_site_data | Local graph store read through `GraphBuilderService.get_graph_data` (embedded FalkorDB) | `export_demo_site_data.py:665-669`; `backend/app/services/graph_builder.py:2674-2720` |
| export_demo_site_data | Graph rebuild: LLM extraction plus embeddings (non-strict 404 path only) | `export_demo_site_data.py:613-638` |
| backfill_report_visuals | No LLM by design. PDF export through `ReportManager.export_pdf`, which runs pandoc and xelatex (`/opt/homebrew/bin/pandoc`, `/Library/TeX/texbin/xelatex`) with a limited PyMuPDF fallback | `backfill_report_visuals.py:697`; `backend/app/services/report_agent.py:12604-12605`, `:13461-13478` |
| eval_forecast_quality | LLM judge `LLMClient.chat_json(temperature=0.0, max_tokens=512)`, k times per report. The provider may be a CLI subprocess (claude-cli, codex-cli) | `eval_forecast_quality.py:262`, `:276-281` |
| model_comparison | Per provider: full `ReportAgent.generate_report` (many LLM calls plus graph tools), one `extract_structured_forecast` LLM pass and an optional `self_critique_forecast` pass; `shutil.which` for CLI providers | `model_comparison.py:237`, `:246-250`, `:93` |
| test_graphiti_migration / test_graphiti_services | LLM extraction, local sentence-transformers embeddings, embedded FalkorDB; `insight_forge` makes LLM sub-queries | `test_graphiti_migration.py:82`; `test_graphiti_services.py:64`, `:102-103` |
| test_pipeline_resume | No network. `resume()` creates a `TaskManager` task (`backend/app/services/pipeline_orchestrator.py:8174-8178`, relative lines 68-72 of the `resume` block) | `test_pipeline_resume.py:87` |
| golden_eval, forecast_tools, test_deerflow_deep_research, test_zep_rate_limit, test_profile_format, salvage, watcher | None, only file I/O | — |

## Cross-module edges

### Callers into this slice

| Caller | Target | Anchor |
|---|---|---|
| `scripts/start.sh` | `watch_pipeline_progress.py` | `scripts/start.sh:37`, `:503`, `:591` |
| `backend/tests/test_start_script_progress.py` | `watch_pipeline_progress.py` (copied and exercised: `test_progress_events_*`, `test_watcher_ignores_completed_history_then_discovers_new_pipeline`) | `backend/tests/test_start_script_progress.py:14`, `:163-224` |
| `backend/tests/test_wave9_orchestrator.py` | salvage script, loaded via `spec_from_file_location` (dry run is read-only, mutation equals backend semantics, path-escape rejection) | `backend/tests/test_wave9_orchestrator.py:441-442`, `:487-518` |
| `backend/tests/test_export_demo_site_data.py` (28 tests) | `import scripts.export_demo_site_data` | `backend/tests/test_export_demo_site_data.py:9-11` |
| `backend/tests/test_backfill_report_visuals.py` (13 tests) | `from scripts.backfill_report_visuals import ...` | `backend/tests/test_backfill_report_visuals.py:7`, `:231` |
| `backend/tests/test_golden_eval.py` (18 tests) | `import golden_eval` via `sys.path` | `backend/tests/test_golden_eval.py:17-20` |
| `backend/tests/test_eval_forecast_quality.py` (15 tests) | `import eval_forecast_quality` via `sys.path` | `backend/tests/test_eval_forecast_quality.py:16-19` |
| `backend/tests/test_foglamp_containment.py` | Checks the golden fixture is characterization-only | `backend/tests/test_foglamp_containment.py:415` |
| `backend/tests/eval/scenarios/*.json` | Point `report_path` at the exporter's output `docs/demos/<key>/report.md`, so the LLM judge scores the exported demo reports | `backend/tests/eval/scenarios/us-iran-2026.json:4` |
| `docs/demo.html` | Consumes every exporter output file; `RUN_KEYS` must match `RUNS` | `docs/demo.html:56`, `:99-117`, `:155`, `:267`, `:321` |
| README | Documents the helper scripts and the 4-step "add a run" recipe | `README.md:1596-1621` |

No runtime module under `backend/app` imports any slice file.

### Calls out of this slice

- **export_demo_site_data**:
  - `research_progress.merged_research_progress_full` (`backend/app/services/research_progress.py:520`)
  - `ReportManager.is_publishable` / `REPORTS_DIR` (`backend/app/services/report_agent.py:12597`, `:11864`)
  - `ReportAgent._detect_translation_target` (`backend/app/services/report_agent.py:6084`)
  - `GraphBuilderService.{create_graph, set_ontology, add_text_batches, _wait_for_episodes, get_graph_data}` (`backend/app/services/graph_builder.py:1221`, `:1233`, `:2288`, `:2427`, `:2674`)
  - `TextProcessor.split_text`
  - `graphiti_client.ApiError` (`backend/app/services/graphiti_client/compat.py:39-48`)
  - `/api/graph/data/<id>` (`backend/app/api/graph.py:576`)
- **backfill_report_visuals**:
  - `forecast_extractor.{_binary_quality, _is_circular_market_forecast, build_market_comparison, reconcile_forecast_contract, render_binary_forecasts_block, upsert_binary_forecasts_block}` (`backend/app/services/forecast_extractor.py:1599`, `:1446`, `:1948`, `:2435`, `:3353`, `:3459`)
  - `report_lint.lint_report` (`backend/app/services/report_lint.py:1534`)
  - `ReportVisualizer.build_all` (`backend/app/services/report_visualizer.py:4313`)
  - `ReportAgent.{_repair_quote_grounding, _place_visualizations, _stabilize_publish_markdown, _enforce_final_publish_audit, _audit_translation_variant}` (`backend/app/services/report_agent.py:3741`, `:9043`, `:7991`, `:8423`, `:6393`)
  - `render_market_comparison_block` (`backend/app/services/report_agent.py:1347`)
  - `ReportManager.{_get_report_folder, export_pdf, _is_pdf_file}` (`backend/app/services/report_agent.py:11890`, `:13461`, `:12621`)
  - `utils.atomic`
- **golden_eval**: `forecast_ledger.{append_golden_result, read_ledger, calibration_summary}` (`backend/app/services/forecast_ledger.py:113`, `:212`, `:233`); `backtest.calibration_report` (`backend/app/services/backtest.py:73`).
- **eval_forecast_quality**: `forecast_extractor.audit_citation_grounding` (`backend/app/services/forecast_extractor.py:4033`); `LLMClient.chat_json` (`backend/app/utils/llm_client.py:597`).
- **model_comparison**:
  - `ensemble.aggregate_forecasts` (`backend/app/services/ensemble.py:150`)
  - `forecast_extractor.{extract_structured_forecast, self_critique_forecast, audit_citation_grounding}` (`backend/app/services/forecast_extractor.py:999`, `:3582`, `:4033`)
  - `PipelineManager.load`, `load_research_dossier_for_simulation` (`backend/app/services/pipeline_orchestrator.py:1136`, `:6744`)
  - `ReportAgent.__init__` / `generate_report` (`backend/app/services/report_agent.py:1533`, `:11113`)
  - `LLMMeter`, `set_run_context` (`backend/app/utils/telemetry.py:42`, `:273`, `:353`)
- **forecast_tools**: `ensemble.aggregate_forecasts`, `backtest.{calibration_report, score_forecast}`.
- **test_\*** scripts:
  - Deep-research bridge functions (`deerflow_bridge/deerflow_research.py:574`, `:4842`, `:5138`, `:8140`, `:10070`, `:10190`, `:12331`)
  - The Graphiti `Zep` shim (`backend/app/services/graphiti_client/client.py:96-153`)
  - `ZepEntityReader`, `ZepToolsService`, `ZepGraphMemoryUpdater`
  - `PipelineManager` / `PipelineOrchestrator` (`backend/app/services/pipeline_orchestrator.py:993`, `:8107`, `:7982`, `:8043`, `:8089`)
  - `OasisProfileGenerator._save_twitter_csv` / `_save_reddit_json` (`backend/app/services/oasis_profile_generator.py:3062`, `:3150`)
  - `zep_rate_limit` (`backend/app/utils/zep_rate_limit.py:14`, `:26`)
- **salvage / watcher**: stdlib only. Salvage deliberately duplicates orchestrator logic; see Surprises.

## Invariants, gates, validation

- **Publication barrier (exporter, strict).** It fails closed on any id mismatch across the pipeline, project, report meta, simulation state and config, run state and run summary. It also fails on a non-completed stage, a hollow simulation, or a non-positive count. On the audit side it fails on a non-read-only or failed audit, or on a hash mismatch between the report or forecast bytes and the audit (`export_demo_site_data.py:221-405`). Strict mode also refuses to substitute a rebuilt graph (`export_demo_site_data.py:973-977`) or keep a stale `graph.json` (`export_demo_site_data.py:556-563`, `:985-986`).
- **Translation publication.** A report variant needs `ReportManager.is_publishable(id, lang)` (`export_demo_site_data.py:713`). A dossier variant needs translation status `available` bound to the current source SHA plus a hard-passed audit bound to the variant SHA (`export_demo_site_data.py:739-745`).
- **Asset safety.** Only `charts/<safe-name>` local links are allowed. A realpath must stay inside its source dir. Namespace and run key must match `[A-Za-z0-9._-]+`. Every asset is resolved before the namespace is replaced (`export_demo_site_data.py:408-512`).
- **Provenance.** `meta.json.artifact_sha256` covers every published artifact (`export_demo_site_data.py:1000-1016`). `research_log.complete=false` marks a retained, unverified legacy log (`export_demo_site_data.py:126-137`).
- **Backfill.** Writes need `--apply` (`backfill_report_visuals.py:465-466`). The id regexes and the ownership check (`state.report_id == report_id`) guard against path abuse (`:446-451`). All mutations happen after the backup, and any exception restores it (`:739-769`). The primary report is the only target of prose repair (`:511-513`). Variants are published only after a hard-passed audit, in the order citations, then audit, then Markdown (`:660-663`). Each PDF must start with `%PDF-` (`:699-701`).
- **golden_eval.** Malformed golden entries raise `ValueError` (`golden_eval.py:215-221`). Invalid probabilities are reported, never scored (`golden_eval.py:263-266`). Golden rows can never land in the production ledger (`backend/app/services/forecast_ledger.py:171-178`).
- **eval_forecast_quality.** The cost guard (`eval_forecast_quality.py:333-336`). Malformed judge output scores 0 (`:63-75`, `:278-281`). The gate is `mean ≥ baseline − tolerance` (`:136`).
- **model_comparison.** Double opt-in: the script plus `MODEL_COMPARISON_ENABLED` or `--force` (`model_comparison.py:426-433`). Provider names are whitelisted to `[a-z0-9_-]` (`:71`, `:390-392`). A failed provider is isolated and does not abort the run (`:266-268`). Report folder names are sanitized and randomized (`:175-183`).
- **Salvage.** It is a dry run unless `--apply` (`salvage_orphaned_pipelines.py:175-205`). It requires the full eligibility tuple (`:76-101`), rejects path-escape report ids (`:86-87`), will not touch a state that became `running` (`:195-198`), and writes atomically (`:58-73`).
- **Watcher.** It only reads. Malformed or partial JSON is skipped (`watch_pipeline_progress.py:118-123`), and progress noise is bucketed to 5% (`:42-49`).

## Failure modes & recovery

- **Exporter: missing pipeline state.** A full export prints a skip and continues to the next run (`export_demo_site_data.py:922-925`). Refresh modes raise `RuntimeError` (`:157-159`, `:851-853`). `pipe_85d91bafe6fd` (`cloud-2030`, `:65`) has no local `backend/uploads/pipelines/<id>/pipeline_state.json` in this checkout.
- **Exporter: research logs garbage-collected.** A full export keeps an existing `research_log.txt` with `complete:false`. If none exists it raises (`export_demo_site_data.py:126-138`). `--research-log-only` always raises in that case (`:173-176`). Logs over 64 MiB, or with more than 16 tracks or attempts, raise `ResearchProgressLimitError` (`backend/app/services/research_progress.py:434-438`, `:456-460`, `:539-543`).
- **Exporter: chart source missing.** A full export raises `FileNotFoundError` before touching the published namespace (`export_demo_site_data.py:498-499`). `--reports-only` can keep a published chart whose bytes still match the manifest (`:493-497`, `:865`).
- **Exporter: the run is not transactional.** Assets and Markdown are written stage by stage, and meta.json is written last (`export_demo_site_data.py:935-1036`). An exception mid-run leaves a mixed bundle whose meta.json and `artifact_sha256` predate the new files. Recovery is to re-run the export.
- **Exporter: graph errors.** With `--graph-api`, an HTTP error or `success:false` becomes `RuntimeError`, and there is no rebuild (`export_demo_site_data.py:660-663`). Without it, only an `ApiError` 404 triggers a rebuild, in non-strict mode only (`:970-980`). Local Graphiti never raises that 404 (`backend/app/services/graphiti_client/compat.py:42-43`). A missing local graph therefore most likely exports an empty `nodes` / `links` set, because `get_graph_data` just pages through whatever `fetch_all_nodes` returns (`backend/app/services/graph_builder.py:2610-2611`). Not executed; inferred from the code.
- **Backfill.** Any exception triggers a restore from the newest backup created during this run, writes `replay_failure.json` and re-raises (`backfill_report_visuals.py:747-769`). A failed final audit, a failed PDF export (including `REPORT_PDF_EXPORT=false`) or a failed primary-report check aborts the run (`:577`, `:699-701`, `:514-516`). Two `--apply` runs in the same second hit `FileExistsError` on the backup dir (`:394`).
- **golden_eval.** Exit 3 when no ids match (`golden_eval.py:442`). Ledger append failures return `None` and are not counted (`backend/app/services/forecast_ledger.py:184-185`).
- **eval_forecast_quality.** A judge-pass exception becomes an all-zero sample (`eval_forecast_quality.py:278-281`). A missing report is skipped (`:376-379`). Exit 1 means a gate regression and exit 2 means no scenarios (`:365-367`, `:407`).
- **model_comparison.** Credential failures are skipped or recorded (`model_comparison.py:403-412`). A report or forecast failure is recorded in `failed` (`:266-268`). A bad base pipeline exits 2 (`:451-453`).
- **Salvage.** A corrupt state is ignored (`salvage_orphaned_pipelines.py:48-55`). A state whose read-back fails is skipped with `!!` (`:191-194`).
- **Watcher.** A crash is restarted by `start.sh` up to `FOLLOWER_RESTART_LIMIT` (`scripts/start.sh:635-640`). Unreadable state files are skipped (`watch_pipeline_progress.py:136-138`).

## Surprises

1. **Doc drift, exporter header.** The docstring says graph export "hits the Zep API (read-only) and respects the same 429 retry-after handling" (`export_demo_site_data.py:15-17`). The graph is now local Graphiti on embedded FalkorDB (`backend/app/config.py:1010-1038`). The `rebuild_graph` path describes re-creating a graph "on Zep" (`export_demo_site_data.py:613-620`). `ApiError`'s own docstring calls the 404 branch "effectively dead" (`backend/app/services/graphiti_client/compat.py:42-43`).
2. **Suspected bug, exporter.** In a non-strict export, `state.get("report_id", "")` returns `None` when the key exists with a null value. `os.path.join(..., None, ...)` then raises `TypeError` before any useful error (`export_demo_site_data.py:929`). Non-strict mode also uses `state["project_id"]`, `state["graph_id"]` and `state["simulation_id"]` without guards (`:950-951`, `:989`). So a pipeline missing any of them crashes with `KeyError` instead of the "skipped" path.
3. **Suspected inconsistency, exporter indentation.** `refresh_demo_research_log` always rewrites meta.json with indent=2, claiming the tracked metadata "conventionally uses a two-space indent" (`export_demo_site_data.py:186-191`). The full exporter writes indent=1 (`:101-103`), and 13 of the 15 committed `docs/demos/*/meta.json` files use a 1-space indent (only `datacenter-2030` and `ev-2035` use 2). A research-log refresh therefore reformats the whole file. `refresh_demo_reports` detects the indent correctly (`:905-910`).
4. **Suspected, exporter `graph_id`.** With non-strict `--skip-graph`, meta.json `graph_id` is set from the pipeline state (`export_demo_site_data.py:963`, `:1021`) even when the retained `graph.json` came from an earlier rebuilt graph with a different id. Strict mode guards against this (`:985-986`); lenient mode does not.
5. **Legacy demo bundles.** Several committed meta.json files predate the current exporter schema. For example `docs/demos/us-ai-2030/meta.json` and `docs/demos/russia-ukraine/meta.json` have only 7 keys and no `artifact_sha256`, `publication` or `*_languages`.
6. **Working tree state.** The working tree has 38 tracked files under `docs/demos/` deleted but uncommitted (`git status`). They are `research_log.txt` files and `charts/` / `research-charts/` PNGs, for example under `docs/demos/quantum-2040/charts/`, while `docs/demos/quantum-2040/meta.json` still lists them in `report_assets` and `artifact_sha256`. The repo also contains `docs/demos/logs/` and `docs/demos/*/CLAUDE.md`, which the exporter never writes.
7. **Doc drift, golden_eval.**
   - The usage example points at `backend/uploads/pipelines/<pid>/report/forecast.json` (`golden_eval.py:27`). Reports actually live at `backend/uploads/reports/<report_id>/forecast.json` (`backend/app/services/report_agent.py:11864`, `:11890`).
   - The docstring says golden outcomes accumulate in the calibration ledger so `report_visualizer` curves grow (`golden_eval.py:32-36`), and `backend/app/config.py:432-434` says the same. Since Foglamp WP1, `append_golden_result` redirects them to the isolated `_evaluation_ledger` (`backend/app/services/forecast_ledger.py:171-178`).
   - `score-ledger` without `--ledger-dir` reads the **production** ledger (`golden_eval.py:448`), so its `golden` block will be `n=0` unless pointed at `_evaluation_ledger`.
8. **Dead path, eval_forecast_quality.** The `pipeline_id` fallback `backend/uploads/pipelines/<pid>/report/report.md` (`eval_forecast_quality.py:225-227`) matches no layout the pipeline writes; a glob of `backend/uploads/pipelines/*/report` finds nothing. All committed scenarios use `report_path` into `docs/demos` (for example `backend/tests/eval/scenarios/us-iran-2026.json:4`). Those bundles have no `forecast.json`, so `scenario_count` and `probability_sum` are never part of the judge's signals (`eval_forecast_quality.py:164-172`, `:300-305`).
9. **Gotcha, eval_forecast_quality.** `--update-baseline` exits 0 and overwrites the baseline even when the current run regressed (`eval_forecast_quality.py:401-405`). Skipped scenarios keep their old baseline entries (`:371`).
10. **Doc drift, model_comparison `agreement`.** The comment describes `agreement` as "1 - 2×平均 spread" (`model_comparison.py:286-287`). `aggregate_forecasts.agreement` is now TV-distance plus support. The old formula survives as `agreement_spread` (`backend/app/services/ensemble.py:249-252`), which the comparison does not surface.
11. **Suspected, model_comparison scenario lookup.** `by_provider` looks up each provider's scenario by exact `_norm_name` match against the bucket's display name (`model_comparison.py:302`, `:318-327`). `aggregate_forecasts` aligns buckets semantically by default, through resolution-criteria overlap and aliases (`backend/app/services/ensemble.py:167-184`; `backend/app/config.py:340`). A provider merged into a bucket under a different name therefore shows `None` even though it contributed. Rows also omit the renormalized pooled `probability` and sort by the arithmetic `mean_probability` (`model_comparison.py:308-329`).
12. **Suspected drift, model_comparison report inputs.** It claims "与 PipelineOrchestrator 的 report 阶段同口径" (the same inputs as the pipeline's report stage) (`model_comparison.py:196`). However it builds `ReportAgent` without `quantitative`, `contested`, `timeline_events`, `graph_priors(_structural)` or `scenario_spine` (`:223-232` vs `backend/app/services/report_agent.py:1533-1553`). Comparison reports are therefore not like-for-like with pipeline reports.
13. **Minor drift, forecast_tools.** The docstring says `forecast.json` is emitted "when REPORT_STRUCTURED_FORECAST=true" (`forecast_tools.py:5-6`), as though it were opt-in. The default is already `True` (`backend/app/config.py:162`).
14. **Stale (confirmed by reading, not executed), `test_deerflow_deep_research.py`.**
    - Several overlay SKILL.md markers asserted at `:47-56` are absent from `deerflow_bridge/skills/deep-research/SKILL.md`, which was rewritten as a compact core. Examples are `"S1 — Primary / authoritative"`, `"Evidence Ledger"` and `"Synthesis Gate"`; the file has `## Synthesis gate`, lowercase, at line 76.
    - The deep opening limit is now `DEERFLOW_DEEP_OPENING_RECURSION_LIMIT` with a default of 300, not 220 (`deerflow_bridge/deerflow_research.py:12476` vs `test_deerflow_deep_research.py:159`).
    - Phase limits now sum to 2160 (330 + 540 + 450 + 450 + 390), and the bridge's own comment calls the `1660` literal dead (`deerflow_bridge/deerflow_research.py:129`).
    - The deep synthesis prompt says "at least 15,000 words", with no `"8,000"` (`deerflow_bridge/deerflow_research.py:5151` vs `test_deerflow_deep_research.py:117`).
    - The middle passes now run as parallel scoped workers by default (`deerflow_bridge/deerflow_research.py:12559`).
    - Because pytest never collects `backend/scripts/test_*.py` (`backend/pyproject.toml:84`), this rot is silent. The byte-sync checks for the bridge, skill and middleware do currently pass (`cmp`).
15. **Suspected stale, `test_pipeline_resume.py`.**
    - `test_resume_rejects_terminal_and_live` expects `resume()` of a `running` pipeline to raise "仍在运行" (`test_pipeline_resume.py:115-120`). `resume()` now reclaims a running orphan when `_orphan_is_dead` (`backend/app/services/pipeline_orchestrator.py:8131-8141`). With no owner pid or heartbeat, that check falls back to `updated_at` age ≤ 120 s (`:7837-7839`). The fixture's `updated_at` is `2026-06-10T00:10:00+00:00` (`test_pipeline_resume.py:54`), so the pipeline is judged dead and resumed, and the assertion `"resume of running pipeline must raise"` most likely fires. Not executed.
    - `resume()` creates a `TaskManager` task. Where that persists outside the temp dir was not verified.
16. **Stale, `test_profile_format.py`.** It checks Twitter CSV fields `user_name, bio, friend_count, follower_count, statuses_count, created_at` (`test_profile_format.py:89-90`), and `show_expected_formats` prints that header (`:138`). `_save_twitter_csv` now writes `user_id, name, username, user_char, description` (`backend/app/services/oasis_profile_generator.py:3089`). The script prints `[错误] 缺少字段` (missing fields) and still exits 0.
17. **Import gotcha.** `backfill_report_visuals.py` and `test_zep_rate_limit.py` have no `sys.path` bootstrap (`backfill_report_visuals.py:22-36`; `test_zep_rate_limit.py:8-10`). Every other backend script inserts `backend/`. They work under `backend/.venv` only because that venv has an editable install of `mirofish-backend`, whose `.pth` points at `backend/`. Under any other interpreter they fail on `import app`.
18. **Backfill gotchas.**
    - The scenario rename is applied with a plain `str.replace(old, new)` over the whole report and every variant (`backfill_report_visuals.py:520-521`, `:606-607`). A short or common scenario name could be rewritten inside unrelated prose or references. Suspected.
    - The backup globs `full_report*.pdf` (`:397`). They do not match the PDF cache manifests `full_report[.<lang>].pdf.manifest.json` (`backend/app/services/report_agent.py:12615-12618`), so a rollback leaves the replay-era manifests in place. The impact is likely low, because cache reuse also re-checks the PDF SHA (`backend/app/services/report_agent.py:13475-13476`).
    - The module says "offline and deterministic" (`backfill_report_visuals.py:4`) but shells out to pandoc and xelatex for the PDFs.
    - `DEFAULT_TARGETS` includes `pipe_0f2bee7bd649` and `pipe_a8986bffd918` (`backfill_report_visuals.py:41-42`). These are the same two runs the salvage script was written for (`salvage_orphaned_pipelines.py:5-6`).
19. **Duplicated logic with a gap, salvage script.** By design (`salvage_orphaned_pipelines.py:19-20`), `eligible_report` and `salvage_state` are hand-synced copies of `_orphan_completed_report` and `mark_salvaged_completed` (`backend/app/services/pipeline_orchestrator.py:7738-7770`, `:1024-1074`). A test keeps them in sync (`backend/tests/test_wave9_orchestrator.py:502`). The script differs in three ways:
    - (a) It adds a path-escape guard that the orchestrator lacks.
    - (b) It ignores `schema_version`. `PipelineManager.load` turns a newer-schema file into an incompatible sentinel (`backend/app/services/pipeline_orchestrator.py:1151-1162`), and `mark_salvaged_completed` refuses it (`:1034`). The script would rewrite a newer-schema state file.
    - (c) It takes no `_state_lock`. Its only race guard is the re-read check for `running` (`salvage_orphaned_pipelines.py:195-198`), so a state that moved to `completed` or `cancelled` between scan and apply is still rewritten.
20. **Watcher gotchas.**
    - Message-only stage updates are invisible, because the signature excludes `message` (`watch_pipeline_progress.py:52-57`).
    - `--once` sets `initial=False` and so dumps every pipeline in history, completed ones included (`:175`). `start.sh` uses it only as a smoke check with stdout discarded (`scripts/start.sh:503`).
    - A newly discovered terminal pipeline emits both `◆ PIPELINE completed` and `✓ PIPELINE completed` (`watch_pipeline_progress.py:93-114`).
21. **Smoke tests leave residue.** `test_graphiti_migration.py` and `test_graphiti_services.py` create `mirofish_test*` / `mirofish_*` graphs in the persistent local store and never delete them (`test_graphiti_migration.py:69-73`; `test_graphiti_services.py:53`). This feeds `GRAPH_RETAIN_COUNT` GC pressure (`backend/app/services/pipeline_orchestrator.py:7773-7783`).
