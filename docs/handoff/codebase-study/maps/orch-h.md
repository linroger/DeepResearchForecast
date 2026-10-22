# orch-h — Orchestrator part H: the main _run stage loop

Slice: `backend/app/services/pipeline_orchestrator.py` lines 11883-13492 (the whole body of
`PipelineOrchestrator._run`). Every line of the slice was read; helpers outside the slice were
read only far enough to say what each call does. All anchors are `path:line` relative to the repo
root; `po:` abbreviates `backend/app/services/pipeline_orchestrator.py`.

---

## Purpose & position in the pipeline

`PipelineOrchestrator._run(cls, state)` (po:11882-11883) is the single background-thread body
that drives one pipeline attempt end to end: RESEARCH → ONTOLOGY → GRAPH → PREPARE → RUN →
REPORT → (optional seed ensemble) → health gate → `completed`. It is always started as a daemon
`threading.Thread(target=cls._run, args=(state,))` by one of four lifecycle entry points:
`start` (po:7972), `resume` (po:8204), `continue_to_full` (po:8269) and `fork` (po:8346). The
same body serves all four: there is no separate resume code path. Each stage first decides
whether it can **reuse** persisted work (stage bit + integrity manifest + stage-specific
identity proofs) and otherwise re-executes. That makes `_run` idempotent across resumes.

The two modes are `full` and `research_only` (`PipelineState.mode`, po:688; validated by the API
at `backend/app/api/research.py:42` and `backend/app/api/sdk.py:62`). `research_only` returns
right after RESEARCH (po:12294-12305). There is no "quick" mode in this loop. Research
*depth* (`state.options["depth"]`) and research *engine* (v3 or legacy) change what RESEARCH
does, not which stages run.

Termination always goes through one of three exception handlers (cancel, provider outage,
generic failure; po:13359-13392) or the success tail (po:13342-13357). After that a `finally`
block (po:13393-13492) flushes telemetry and deregisters the thread.

---

## Walkthrough (source order)

### A. Preamble (po:11883-11900)

| Step | Anchor | What it does |
|---|---|---|
| `self = cls()` | po:11884 | Fresh instance per attempt. `__init__` (po:7538-7547) allocates per-attempt telemetry state (`_tel_path`, `_tel_prev`, `_tel_lock`) and the partial-artifact scan throttle. |
| `task_manager = TaskManager()` | po:11885 | Used for `complete_task`/`fail_task` at the end (`backend/app/models/task.py:145`, `:155`). |
| `set_run_context(state.pipeline_id)` | po:11887-11888 | Sets the telemetry contextvar so every LLM call on this thread is attributed to the pipeline (`backend/app/utils/telemetry.py:42`). The contextvar does not cross into subprocesses (research and OASIS). |
| Outage breaker | po:11891-11892 | `_register_outage_breaker` (po:530) creates a fresh per-attempt `_RunOutageBreaker` with threshold `LLM_OUTAGE_HALT_CONSECUTIVE` (default 10, `backend/app/config.py:69`; resolver po:379-394). It returns None when the threshold is ≤0. Only when a breaker exists does `_install_llm_outage_probe()` (po:597) monkey-wrap `LLMClient.chat` (idempotent). |
| `_init_telemetry_flush(state)` | po:11894 | Points `_tel_path` at `uploads/pipelines/<pid>/run_telemetry.json` and captures the previous attempt's totals as the merge base (po:7557-7573). |
| `_write_run_manifest(state)` | po:11897 | Writes the first `run.json` (redacted) to `uploads/pipelines/<pid>/run.json` and sets `state.artifacts["run_manifest"]`. Gated by `RECORD_RUN_MANIFEST`; swallows errors (po:10374-10391). |
| `hb_stop = _start_heartbeat(state)` | po:11900 | Pins `owner_pid`/`owner_boot_id`/`heartbeat_at`, then starts the daemon `pipeline-hb-<pid>`. Every `PIPELINE_HEARTBEAT_INTERVAL_S` (30 s) it calls `PipelineManager.touch_heartbeat` and an opportunistic telemetry flush. It returns None when `PIPELINE_HEARTBEAT_ENABLED` is false (po:10331-10371). |

Everything after this point runs inside `try:` (po:11901).

### B. Stage 0 — RESEARCH (po:11902-12305)

**B1. Updater and reuse decision (po:11903-11959).**
- `upd = self._make_stage_updater(state, STAGE_RESEARCH)` (po:11903). The updater (po:8949-9007)
  sets the telemetry stage once. On each call it (1) raises `PipelineCancelled` if the cancel
  event is set, (2) raises `ProviderOutageHalt` if the breaker tripped, (3) marks the stage
  `running` and sets progress/message/`started_at`, **sets `state.current_stage`**, refreshes
  `last_progress_at`/`heartbeat_at`, recomputes `global_progress` from bands, (4) registers
  partial artifacts, (5) calls `PipelineManager.save(state)`, (6) attempts a telemetry flush and
  (7) runs `task_manager.update_task`. This is the **only** place `current_stage` changes. [verifier: true only inside the `_run` thread; the lifecycle entry points also assign it before spawning: `resume(force=True)` sets REPORT (po:8164), `continue_to_full` sets ONTOLOGY (po:8263), `fork` sets PREPARE (po:8341). A fresh `start` leaves the dataclass default `""` (po:691). (po:8979)]
- `handoff_dir = state.handoff_dir or PipelineManager.handoff_dir(pid)` (po:11904). For forks this
  is the *base* pipeline's handoff (po:8306).
- `_report_candidate` = `handoff/research_report.md` exists and its stripped text is ≥400 chars
  (po:11905-11909).
- `_contract_present` = `handoff/research_contract_manifest.json` exists (po:11910-11911;
  filename po:3140).
- `_stage_was_complete` = persisted RESEARCH stage status is `completed` (po:11912-11914).
- Decision tree (po:11919-11959):
  - Report candidate **and** contract present:
    - If `_validate_research_contract(handoff_dir)` (po:3418) fails → warn and refuse reuse. If
      `evidence_synthesis_manifest.json` exists, set `_synthesis_recovery_manifest`
      (po:11921-11928).
    - Otherwise run `_research_contract_quality_errors(handoff_dir, require_judge=<evidence
      manifest exists>)` (po:3216). Any error (judge missing/malformed/failed) → refuse reuse
      and set the recovery manifest if present (po:11930-11944). No errors → `_reuse_research =
      True` (po:11946).
  - Report candidate, no contract, stage completed → `_reuse_research =
    self._validate_reuse(state, STAGE_RESEARCH)`. This is a hash/bytes/schema check against
    `handoff/manifest.json` that passes when no manifest exists (po:11947-11949; po:9798-9885).
  - Report candidate, no contract, stage not completed → warn and do not reuse. This forces a
    full research run even if an evidence manifest exists (po:11950-11954).
  - No report candidate but `evidence_synthesis_manifest.json` exists → synthesis-only recovery
    (po:11955-11959).

**B2. Execution branches (po:11960-12078).**
- **Reuse** (po:11960-11963): `upd(95, …)`. Then `research = _load_research_handoff(handoff_dir)`
  (po:3857-3887), which raises if the report is <400 chars, blanks a degraded
  `actor_dossier.md`, and returns `{report, report_path, actor_dossier, actors, sources,
  timeline, exit_code: None, resumed: True}` (po:3876-3887). Finally `state.research_pid = None`.
- **Fresh/recovery** (po:11964-12078): `upd(1, "准备深度研究…")`. Defines `_persist_research_pid`,
  which writes `state.research_pid` and saves (po:11966-11968), so `reconcile_orphans` can kill an
  orphaned research process group.
  - **Synthesis recovery** (po:11970-11976): `_run_research_synthesis_recovery(state,
    handoff_dir, upd, manifest)` (po:10841). It retries only the global synthesis from sealed
    lane packs, with at most two attempts.
  - **Parallel outer tracks** (po:11983-11991): `_research_engine =
    research_engine_for_run(state.options)` (po:5937). It returns `legacy` when the pinned
    `actor_intelligence_policy_v1.required is True`, else `Config.RESEARCH_ENGINE` (default
    `v3`, `backend/app/config.py:1187`). `_n_tracks = research_outer_track_count(
    RESEARCH_PARALLEL_TRACKS (default 3), engine)` (po:5955-5982) is **always 1 for v3**. When
    `_n_tracks > 1` → `_run_parallel_research_tracks(state, handoff_dir, upd, n)` (po:11060), a
    ThreadPoolExecutor of research subprocesses plus a deterministic merge.
  - **Single lane** (po:11992-12075):
    - `_validated_research_checkpoint_lineage(...)` (po:2974) checks
      `handoff/research_checkpoint.json` v2 against prompt, depth (option or
      `DEERFLOW_RESEARCH_DEPTH`), run id, `lane_id="outer-track-1"` and the admitted budget
      epochs. A non-empty `attempt_id` → `_resume_research=True` and `upd(1, "检测到研究断点…")`
      (po:11995-12019).
    - Concurrency envelope (po:12020-12032): with defaults (`RESEARCH_GLOBAL_SUBAGENT_CAP=9`,
      `RESEARCH_GLOBAL_MODEL_CONCURRENCY=0`, `RESEARCH_SUBAGENTS_PER_TRACK_MAX=5`) the model
      concurrency is 1+9=10 (po:5845-5854) and the lane subagent cap is min(10//1-1, min(5, 9))=5
      (po:5857-5872, po:5821-5830).
    - `_activate_research_budget_epoch(state, handoff_dir)` (po:1815) returns `(budget_db,
      telemetry_path, epoch)`, one durable SQLite tool-budget ledger per task id
      (po:12033-12037).
    - **Pre-launch budget gate**: if `_research_budget_exhaustion(telemetry, epoch)`
      (po:1764-1798) reports a saturated `attempts_global`/`search_global`/`fetch_global` cap →
      `raise RuntimeError("research_budget_exhausted before track launch …")`
      (po:12038-12046).
    - `DeerFlowResearchRunner.run(...)` (po:12047-12075; wrapper po:2114, subprocess launch
      `subprocess.Popen(..., start_new_session=True)` po:2428-2441). It receives depth,
      language, model, the **cancel event** (`cls._cancel_events[pid]`), `on_spawn`, the resume
      flag, `kg_graph_id=state.graph_id` (None on a first run), the budget db/lane/telemetry/
      run/epoch, the resume attempt/checkpoint ids, `subagents` (`DEERFLOW_SUBAGENTS` and
      cap>0), `max_concurrent_subagents`, `model_concurrency_global` and `research_engine`.
  - After either fresh branch: `state.research_pid = None` and
    `state.options.pop("research_track_pids")` (po:12076-12078). Not saved immediately; the next
    save persists it.

**B3. Research lint (po:12079-12147).** `report_md = research["report"]` (po:12079). With
`REPORT_LINT` on (default true, `backend/app/config.py:558`) it imports
`report_lint.lint_report` (`backend/app/services/report_lint.py:1534`).
- `_judge_bound_report = _research_report_is_judge_bound(handoff_dir)` (po:3477-3489): the
  contract manifest v1 lists `research_report_judge.json`.
- `_lint_audit_only = judge_bound or no contract manifest` (po:12097-12099). Every single-lane/v3
  run is therefore audit-only.
- Language is `research_language` option → `DEERFLOW_RESEARCH_LANGUAGE` → inferred from CJK share
  >5% of the first 20,000 chars (po:12100-12107).
- `lint_report(report_md, lang, mode="research")` (po:12108). The cleaned text is adopted
  (`report_md` and `research["report"]` replaced) only when the report is manifest-owned and not
  judge-bound (po:12130-12136). Otherwise it logs and, for judge-bound reports, marks
  `post_judge_mutation_suppressed` (po:12110-12129).
- Scalar fields of the lint report plus `audit_only` → `state.options["research_lint"]`
  (po:12137-12143). `ImportError` is ignored silently and other errors only warn
  (po:12144-12147).

**B4. Track B + cast reconciliation (po:12148-12203).** `dossier_md =
research.get("actor_dossier")` and `actors = research.get("actors")` (po:12151-12152). With
`CAST_RECONCILE` (default true) and non-empty actors, `_reconcile_research_cast(actors)`
(po:3917) runs.
- If `_audit["merged"]`: when `applied` (legacy casts) it replaces `actors`/`research["actors"]`
  and, **only when no contract manifest exists**, writes `handoff/actors.json` atomically
  (po:12159-12173). It always writes `handoff/cast_reconciliation.json` and sets
  `state.artifacts["cast_reconciliation"]` (po:12174-12175). Write errors are swallowed
  (po:12176-12177).
- It records `state.options["cast_reconciliation"]` (n_before/n_after/merges/applied/reason/
  hypothetical_n_after) (po:12178-12184).
- Sealed `actor-intelligence/v1` casts are never mutated (audit only, warning po:12189-12197).
  An exception during reconciliation re-raises as `RuntimeError("sealed actor-intelligence/v1
  duplicate audit failed")` for v1 and is only a warning otherwise (po:12198-12203).

**B5. Observability hooks (po:12204-12233).**
- `_record_research_telemetry(state, research.get("research_telemetry"))` (po:12205;
  po:10430-10470) stashes `options["research_telemetry"]` and writes a synthetic `LLMMeter.record(
  stage="research")` when tokens >0. Models `claude`/`codex` are costed as `claude-cli`
  (marginal $0).
- `_maybe_warm_embedder(state, actors)` (po:12208; po:11832-11878): when
  `EMBED_WARM_AT_RESEARCH` is on (default false), a daemon thread pre-encodes ≤600 actor
  names/aliases through `LocalSentenceTransformerEmbedder`.
- `_surface_research_quality(state, handoff_dir)` (po:12210-12213; po:10564-10640) reads
  `handoff/meta.json` and `research_budget.json`. It sets `options["research_budget"]` and
  `options["research_quality"]` (with an optional `research_quality_warning` when
  `RESEARCH_QUALITY_GATE` is on and score < `RESEARCH_QUALITY_FLOOR`). It rewrites `meta.json`
  only when there is no contract manifest, and returns the meta dict, which is stored back as
  `research["meta"]`. [verifier: the rewrite also requires `research_budget.json` to exist and
  report `degraded` or at least one `denied_*` count; without a budget degradation `meta.json` is
  never written, whether or not a contract exists (po:10583-10621)]
- Dossier coverage (po:12215-12233): `utils.actors.dossier_coverage(actors)` →
  `options["dossier_coverage"]`, plus `options["dossier_coverage_warning"]` when incentives
  <34%, tier-1/2 worldview <34%, valenced edges <20%, or there are zero relationships. Errors are
  logged at debug level.

**B6. forecast_inputs fallback (po:12235-12261).** `inject_forecast_inputs_from_report(actors,
report_md)` (po:5752) parses the report's scenario section deterministically, with no LLM, and
injects `actors["forecast_inputs"]` **in place** for pre-v1 casts that lack a valid scenario
distribution. On a hit it rebinds `research["actors"] = actors`. On a miss it logs a "loud" warning
that the world-state seed will be empty, with a different message for sealed v1. It never blocks.

**B7. Seal, penalty, reception, completion (po:12263-12292).**
1. `_finalize_research_contract(handoff_dir, research)` (po:12267; po:3607-3729). It does nothing
   (`None`) when there is no contract manifest. Otherwise it re-validates the root contract,
   rejects post-judge prose mutation, and short-circuits when report/actors/sources/meta are
   byte-identical. If anything differs it copies into a private `.research-final-*` dir and
   promotes with rollback + manifest-last (`_promote_research_contract`). Any inconsistency
   **raises** (fails RESEARCH).
2. `_surface_forecast_confidence_penalty(state, handoff_dir)` (po:12273; po:10716-10735) writes
   advisory `options["forecast_confidence_penalty"]` (0-0.3) plus components. It is only
   observed, never enforced.
3. Mode `!= "research_only"` → `_enforce_actor_intelligence_reception(state, actors,
   report, dossier, sources, handoff_dir)` (po:12274-12286; po:5668-5737). No pinned policy →
   records `legacy_run_without_pinned_policy` and passes. `required: False` → passes with the
   reason. `required: True` → runs `_actor_intelligence_reception_errors` (po:5194) against the
   prompt, depth, **this pipeline id** and admitted budget epochs. Any error → `RuntimeError(
   "actor-intelligence/v1 reception failed before ontology/graph: …")`.
4. `_complete_stage(state, STAGE_RESEARCH, "研究报告已恢复"|"研究完成", reused=…)`
   (po:12287-12292; po:9009-9049) sets status completed and progress 100, keeps the original
   timestamps on reuse, recomputes global progress, registers stage artifacts plus the integrity
   manifest (`_record_stage_artifacts` po:9703-9755), saves, and flushes telemetry.

**B8. research_only exit (po:12294-12305).** It sets `status="completed"`,
`global_progress=100`, saves, and calls `task_manager.complete_task(task_id, {pipeline_id, mode,
report_path})`, then `return`. The `finally` block still runs. No health gate, no reception check
and no telemetry.md (there is no report_id).

### C. Stage 1 — ONTOLOGY (po:12307-12387)

- Updater and `_update_manifest(state, STAGE_ONTOLOGY)` (po:12308-12309). The manifest helper
  pins the current provider/model into `run.json.resolved.ontology` (po:10393-10427).
- `project_name = options.project_name or "研究预测 <pid>"` (po:12310). `project =
  ProjectManager.get_project(state.project_id)` if an id exists (po:12311;
  `backend/app/models/project.py:181`).
- **Reuse gate:** `project is not None and project.ontology` → `upd(100)` and
  `_complete_stage(..., reused=True)` (po:12312-12314). There is no integrity check of
  `ontology.json` here.
- **Fresh:**
  - If there is no project: `upd(10)`, `ProjectManager.create_project(name)`, set
    `simulation_requirement=state.prompt`, `save_extracted_text(report_md)`, set
    `total_text_length`, append a `research_report.md` file entry, `save_project`, set
    `state.project_id` and save state (po:12316-12326).
  - `upd(40, "生成本体（LLM）…")` (po:12328). `_addl_ctx = _actors_to_context(actors)`
    (po:12337; po:6855). With `ONTOLOGY_FROM_DOSSIER` on, `ontology_seed_block(actors)` is
    appended; errors are swallowed (po:12338-12345).
  - `OntologyGenerator().generate(document_texts=[dossier_md] (if non-blank) + [report_md],
    simulation_requirement=prompt, additional_context=_addl_ctx, template=None,
    central_question=actors.central_question, actors=actors)` (po:12346-12360;
    `backend/app/services/ontology_generator.py:539`). This is an **LLM call**.
    `template=None` deliberately enables `ONTOLOGY_AUTO_SELECT` (comment po:12352-12356).
  - With `ONTOLOGY_RICH_SCHEMA` (default true) the full dict is kept with normalized
    `entity_types`/`edge_types`; otherwise only those two keys are kept (po:12366-12374).
    `analysis_summary` and `ProjectStatus.ONTOLOGY_GENERATED` are set and `save_project` runs
    (po:12375-12377).
  - `write_json_atomic(handoff/ontology.json, project.ontology)`; failure only warns
    (po:12381-12386).
  - `_complete_stage(STAGE_ONTOLOGY, "本体生成完成")` (po:12387).

### D. Stage 2 — GRAPH (po:12389-12731)

**D1. Reuse decision (po:12390-12455).**
- Updater and `_update_manifest(STAGE_GRAPH)` (po:12390-12391).
- `_reuse_graph = stage completed AND graph_id`, where `graph_id = state.graph_id or
  project.graph_id` (po:12392-12394).
- Guard 1: `_reuse_ok(state, STAGE_GRAPH)` (po:12398-12401; po:9887-9907). It validates
  `communities.json` and `actor_graph_seed_manifest.json` (specs po:9525-9530). On failure:
  `options["resumed_stage_validation"]="graph_rebuilt_manifest_mismatch"`.
- Guard 2 (sealed v1 only): load the persisted seed manifest (po:7066), build
  `GraphBuilderService(api_key=Config.ZEP_API_KEY)`, and run `_validate_actor_graph_seed_contract
  (..., phase="reuse", expected_manifest=…)` (po:7080). Any exception → rebuild with
  `graph_rebuilt_actor_seed_readback_mismatch` (po:12402-12426).
- Guard 3: `ZepEntityReader().filter_defined_entities(graph_id, enrich_with_edges=False)` count →
  `options["graph_entity_count"]`. Zero entities → `graph_rebuilt_0_entities`; an exception →
  `graph_rebuilt_healthcheck_error` (po:12427-12441;
  `backend/app/services/zep_entity_reader.py:319`).
- Reuse branch: `upd(100)`, `state.graph_id = graph_id`, then re-register the ontology in the
  in-process registry via `set_ontology` (KG-6; failure only warns), then `_complete_stage(...,
  reused=True)` (po:12442-12455).

**D2. Rebuild (po:12456-12731).**
1. `upd(5)`; `builder = GraphBuilderService(api_key=Config.ZEP_API_KEY)` (po:12457-12458).
2. Chunks: `_graph_research_chunks(report_md, "Stage 1 research report")` and the same for the
   dossier (po:12462-12472; po:1298-1338). Each strips data-URI images, sanitizes untrusted text,
   splits with `DEFAULT_CHUNK_SIZE/OVERLAP`, and wraps each chunk in an explicit data boundary.
3. Chunk source (po:12484-12494): `GRAPH_CHUNK_SOURCE` (Config default `dossier_only`,
   `backend/app/config.py:481`). With a non-blank dossier, `dossier_only` → dossier chunks only.
   `report_only` → report chunks only. Any other value with a dossier → dossier chunks first, then
   report chunks (`both`). The choice is recorded in `options["graph_chunk_source"]`, except when
   there is no dossier and the value is not `report_only`.
4. `_recompute_dynamic_bands(state, chunk_count=len(chunks))` (po:12495; po:8904-8947) re-splits
   the 40→100 progress band by cost weights.
5. `graph_id = builder.create_graph(name=project.name)` (po:12496;
   `backend/app/services/graph_builder.py:1221`). `set_ontology` is wrapped in try/except, so
   the build falls back to extraction without an ontology (po:12499-12502).
6. `as_of` anchor (po:12512-12523): with `VALIDATE_AS_OF_DATE` (default true),
   `_validate_as_of_date(actors, sources)` (po:10795-10835) rejects a future date or one earlier
   than the newest source. It falls back to max(source date) clamped to now, then to now, and
   records `options["as_of_date_correction"]`. With the knob off, or on error, it uses plain
   `parse_as_of(actors.as_of_date)`.
7. `_seed_research_actors(builder, graph_id, actors, valid_at=as_of)` (po:12524-12526; po:7184).
   It seeds typed actor/relationship edges and **fails closed** for sealed v1 when
   `GRAPH_SEED_FROM_ACTORS` is off or the seed is partial.
   `_validate_actor_graph_seed_contract(..., phase="post_seed", persist=True)` returns
   `actor_seed_manifest`, or None for non-v1 casts (po:12527-12534). `options["graph_seeded_edges"]`
   is set when seeded (po:12535-12537).
8. `uuids = builder.add_text_batches(graph_id, chunks, batch_size=10,
   progress_callback=add_cb, reference_time=as_of)` (po:12539-12546; graph_builder.py:2288).
   `add_cb` maps progress to 10→65%. This is the **LLM extraction** via Graphiti.
9. Ingest-loss accounting (po:12551-12567): `builder.last_ingest_stats` →
   `options.graph_skipped_chunks/graph_total_chunks`. If failed/total >
   `GRAPH_MAX_SKIPPED_RATIO` (0.3) → `options["graph_ingest_degraded_ratio"]`, which the health
   gate later folds in as GRAPH `degraded` (po:9463-9471).
10. `builder._wait_for_episodes(uuids, wait_cb)` (po:12569-12572; graph_builder.py:2427);
    progress 65→98%.
11. Communities (po:12576-12588): `GRAPH_BUILD_COMMUNITIES` (default **false**). It runs
    `builder.build_communities` and writes `handoff/communities.json` with a plain `open/json.dump`
    (not atomic), then sets `options["graph_communities"]`.
12. Entity resolution (po:12594-12609): `GRAPH_RESOLVE_ENTITIES` (default true). It runs
    `zep_entity_resolver.resolve_entities(graph_id, actors)` (zep_entity_resolver.py:480) and writes
    `handoff/entity_merges.json` (plain write) when merges occurred, plus
    `options["entity_merges"]`.
13. Pruning (po:12614-12637): `GRAPH_PRUNE_ENABLED` (Config default **true**; the getattr
    fallback is False). It runs `graph_pruner.prune_graph(graph_id, actors=rows)`
    (graph_pruner.py:244), puts the scalar audit in `options["graph_prune"]`, writes
    `handoff/graph_prune.json` atomically, and sets `artifacts["graph_prune"]`. `ImportError` is
    debug-only; other errors warn.
14. `_validate_actor_graph_seed_contract(..., phase="post_mutation",
    expected_manifest=actor_seed_manifest)` (po:12644-12651). This is a **hard** re-check that
    extraction, resolution and pruning did not erase the v1 seed (no-op for non-v1).
15. Duplicate-name detection (po:12660-12685): only when `GRAPH_BUILD_CONCURRENCY` > 1 (Config
    default **4**, so it runs by default). It groups `get_runtime().all_entity_nodes(graph_id)` by
    `normalize_name`, sets `options["graph_duplicate_name_groups"]`, and warns when duplicates
    exist while resolution is off.
16. Integrity and priors (po:12689-12725): `builder._get_graph_info(graph_id)` →
    `options.graph_node_count/graph_edge_count/graph_components`. Centrality is folded by alias
    (`fold_priors_with_aliases`, graph_builder.py:628) and written to `handoff/graph_priors.json`
    (`artifacts["graph_priors"]`, `options["graph_centrality_nodes"]`). Betweenness/chokepoints go
    to `handoff/graph_priors_structural.json` (`artifacts["graph_priors_structural"]`).
17. Persist: `project.graph_id`, `ProjectStatus.GRAPH_COMPLETED`, `save_project`, `state.graph_id`,
    `_complete_stage(STAGE_GRAPH, "图谱构建完成")` (po:12727-12731).

### E. Stage 3 — PREPARE (po:12733-12938)

**E1. Reuse decision (po:12734-12767).** `sim_manager = SimulationManager()`, and `sim_state =
sim_manager.get_simulation(state.simulation_id)` if an id exists (po:12735-12737).
`_prepare_reuse = stage completed AND sim_state is not None` (po:12740). Guards:
- `_reuse_ok(state, STAGE_PREPARE)` covers `simulation_config.json` (named `initial_posts`),
  `simulation_config_manifest.json`, personas (twitter csv | reddit json),
  `actor_cast_manifest.json` and both role files (specs po:9531-9549). Failure →
  `prepare_rebuilt_manifest_mismatch` (po:12741-12744).
- `sim_manager.validate_prepared_simulation_config(sim_id)` (simulation_manager.py:1352). Any
  exception → `prepare_rebuilt_config_seal_mismatch` plus `options["artifact_validation_error"]`
  (po:12745-12764).
- Reuse → `upd(100)` and message `"环境已恢复"` (po:12765-12767). **The stage is not completed
  yet**: completion waits for the mutation/reseal block below.

**E2. Rebuild (po:12768-12822).**
- A stage completed but sim missing → self-heal warning (po:12769-12774).
- `upd(5)`; `sim_manager.create_simulation(project_id, graph_id, enable_twitter=True,
  enable_reddit=True)` (po:12775-12776; simulation_manager.py:826). Both platforms are always on.
  This produces a **new** `simulation_id`; any old sim is orphaned.
- Pops every `*_partial` artifact pointer and saves (po:12777-12782).
- `prepare_cb(stage, progress, message)` → `upd(clamp 5..99, "stage: message")`
  (po:12784-12785).
- Persona fan-out: `PARALLEL_PROFILE_COUNT` (16) when `Config.PROVIDER_META[LLM_PROVIDER]
  .openai_compat`, else 3 (po:12789, po:12804, po:12816).
- `_graph_priors` is read from `handoff/graph_priors.json` if present (po:12792-12801).
- `_prep_mr = options.max_rounds or (None in calendar mode, else OASIS_DEFAULT_MAX_ROUNDS or
  None)` (po:12809-12810). `_calendar_mode()` = `SIM_TEMPORAL_MODE=="calendar"` (po:7296-7303;
  Config default `calendar`, `backend/app/config.py:1067`).
- `sim_manager.prepare_simulation(simulation_id, simulation_requirement=prompt,
  document_text=report_md, progress_callback, parallel_profile_count, actors, graph_priors,
  max_rounds, research_language)` (po:12811-12821; simulation_manager.py:862). This is the **LLM**
  persona/config generation; the config is sealed inside the manager.

**E3. Disk-reuse probe for RUN (po:12831-12853).** This runs only when `_prepare_reuse` holds
and the RUN bit is not `completed`. `_completed_sim_reusable(state, sim_state)`
(po:9976-10057) needs `SIM_RESUME_REUSE_COMPLETED` (env first, then Config, default true;
po:7475-7487), the same sim identity, a non-live process, `simulation_end` evidence per enabled
platform, a valid run_summary if one exists, and `validate_simulation_config_seal(require=True)`
plus runtime attestation SHA equality. Passing that **and** `_reuse_ok(STAGE_RUN)` →
`_sim_disk_reuse = True` (po:12835-12842). `_run_already_done = _sim_disk_reuse OR (prepare
reused AND RUN completed AND _run_reuse_ready AND _reuse_ok(RUN))` (po:12848-12853). It is
evaluated **before** any config mutation so a completed run's sealed config bytes are never
touched.

**E4. Post-prepare config mutations (only when `not _run_already_done`).**
- Scenario overlay (po:12825, po:12855-12871): if `options["scenario_overlay"]` (forks) exists,
  load `uploads/simulations/<sim>/simulation_config.json`, run
  `apply_scenario_overlay_to_config` (po:8353-8451; idempotent for injected events), write to
  `.tmp` and `os.replace`, then set `_config_mutated_after_prepare=True`. Errors only warn.
- WorldState seed (po:12878-12917): when calendar mode **or** `SIM_DECISION_CHANNEL` (default
  true). It runs `inject_forecast_inputs_from_report` again (belt-and-suspenders), then
  `world_state_seed_from_actors(actors)`, warning if there are no scenarios. If calendar or
  scenarios: it sets `as_of_date`, sets `horizon_date = _infer_horizon_date(prompt, actors)`
  (po:8462-8486), overrides horizon_date/source/defaulted from `temporal_config` when
  `mode=="calendar"`, writes `world_state_seed` atomically into the config, and sets the mutated
  flag. Errors only warn.
- **Reseal gate** (po:12924-12927): if mutated → `sim_state =
  sim_manager.reseal_simulation_config(sim_id)` (simulation_manager.py:1318-1350). This rebuilds
  and re-validates the config seal. A failure **raises** (PREPARE fails).
- `_complete_stage(STAGE_PREPARE, message, reused=_prepare_reuse)` (po:12933-12938). This comes
  **after** mutation so the integrity manifest hashes the final config.

### F. Stage 4 — RUN (po:12940-13183)

**F1. Reuse decision (po:12941-12972).**
- `previous_run_done` = RUN bit completed (po:12942-12945). `run_stage_done = _prepare_reuse AND
  previous_run_done` (po:12948). A rebuilt PREPARE invalidates the old RUN:
  `run_rebuilt_prepare_identity_changed` (po:12949-12951).
- `_run_reuse_ready(state, sim_state)` (po:9910-9939) needs the same sim id, status COMPLETED, and
  a run_summary that is absent (legacy) or a dict with matching id and valid schema. Failure →
  `run_rebuilt_simulation_state_mismatch` (po:12952-12955).
- `_reuse_ok(STAGE_RUN)` (run_summary manifest entry). Failure → `run_rebuilt_manifest_mismatch`
  (po:12957-12960).
- Disk reuse promotes `run_stage_done=True` with `run_reused_completed_simulation`
  (po:12963-12969).
- Reuse → `upd(100)` and message `"模拟已恢复"` (po:12970-12972).

**F2. Fresh run (po:12973-13097).**
- `upd(2)`; `run_kwargs={"platform": "parallel"}`. `max_rounds = options.max_rounds or (None in
  calendar mode, else OASIS_DEFAULT_MAX_ROUNDS (36) or None)` (po:12974-12982).
- Graph feedback: `cls._pinned_safety(state, "sim_graph_feedback", Config.SIM_GRAPH_FEEDBACK)`
  (po:8517-8527; Config default false) and graph_id → `enable_graph_memory_update=True,
  graph_id` (po:12985-12988).
- `SimulationRunner.start_simulation(simulation_id, **run_kwargs)` (po:12989;
  simulation_runner.py:451). It spawns the OASIS subprocess (`subprocess.Popen` at
  simulation_runner.py:943). No `sim_seed` and no `resume` are passed, so the runner's own
  `SIM_RESUME` auto-detection applies.
- Stall config: `_stall_s = float(PIPELINE_RUN_STALL_S or 1800)` (po:12996-12998).
  `_wd_ctl = _spawn_run_stall_watchdog(pid, sim_id, _stall_s)` (po:13001; po:9113-9159) starts
  the independent daemon `run-stall-wd-*`. Every 30 s it reads
  `backend/uploads/simulations/<sim>/run_state.json` from disk and calls
  `SimulationRunner.stop_simulation` once the round has not advanced for `stall_s`. It exits on
  `completed`/`error`. [verifier: it tests `rs.get("completed") or rs.get("error")` (po:9142),
  but `run_state.json` has no top-level `completed` key. `SimulationRunState` serializes
  `runner_status`, `completed_at` and `twitter_/reddit_completed` instead
  (backend/app/services/simulation_runner.py:209-245). So only a truthy `error` or `ctl["stop"]`
  (set in the poll loop's `finally`, po:13069-13070) ends the thread. It is harmless in practice
  because the poll loop always sets the stop flag.]
- Poll loop (po:13005-13061), every 5 s (`time.sleep(5)`, po:13061):
  1. Cancel event set → `SimulationRunner.stop_simulation` (errors only warn) → `raise
     PipelineCancelled("模拟已被用户取消")` (po:13007-13013).
  2. `rs = SimulationRunner.get_run_state(sim_id)`. None → `RuntimeError("模拟运行状态丢失")`
     (po:13014-13016).
  3. On a change of `(current_round, total_rounds)` (po:13021): the first time total becomes >0 it
     reads `temporal_config` (calendar fingerprint unit/n_rounds/horizon_date), calls
     `_recompute_dynamic_bands(total_rounds, temporal)` and `_update_manifest(STAGE_RUN,
     total_rounds, temporal)` (po:13022-13042). It resets the inline stall clock and calls
     `upd(min(98, cur/total*100))` or `upd(5)` (po:13043-13048). `upd` therefore runs (save plus
     cancel/outage checks) only on round changes.
  4. `runner_status == COMPLETED` → break. `FAILED`/`STOPPED` →
     `RuntimeError("模拟未正常结束: …")` (po:13049-13052).
  5. Inline stall: no round progress for >`_stall_s` → `stop_simulation`, then
     `RuntimeError("模拟约 Ns 无进展…")` (po:13055-13060).
- `except BaseException` (po:13062-13068) catches cancel, outage and errors alike: it calls
  `_record_sim_run_telemetry` exactly once (po:10473-10560; idempotent via
  `meter_run_token`) and re-raises. `finally: _wd_ctl["stop"]=True` (po:13069-13070) retires the
  watchdog on every exit path.
- Confluence barrier (po:13082-13095), only when graph feedback is enabled for the run:
  `SimulationRunner.join_monitor_thread(sim_id, timeout=30)` (simulation_runner.py:322) times out
  with a warning only. Then `ZepGraphMemoryManager.stop_updater(sim_id)`
  (zep_graph_memory_updater.py:684) drains the feedback writer; errors only warn.

**F3. Post-run (shared by fresh and reuse; po:13099-13183).**
- run_summary (po:13101-13117): loads `handoff/communities.json` if present, then calls
  `_publish_run_summary(state, sim_id, communities, regenerate=not run_stage_done)`
  (po:10086-10121). A fresh run always regenerates through `SimulationRunner.write_run_summary`
  (simulation_runner.py:2026). Reuse regenerates only a missing or invalid legacy summary. A
  valid summary is registered in `artifacts["run_summary"]` and the integrity manifest and the
  helper returns True. Exceptions are swallowed (warning), leaving `_run_summary_published=False`.
- `_record_sim_run_telemetry(state, sim_id)` (po:13123) books the RUN spend before the evidence
  gate.
- **Completion evidence gate** (po:13130-13136): `_require_run_completion_evidence(state,
  sim_id, run_state, summary_published)` (po:10059-10084). It raises when any enabled platform
  lacks `simulation_end` (bit or `actions.jsonl` tail; `<no-platform-evidence>` fails closed,
  po:9942-9974) or when the summary was not published. The reuse path uses a fresh
  `get_run_state`.
- Simulation-state reconciliation (po:13142-13166): `_reconcile_completed_simulation_state(ss,
  terminal_rs, terminal_summary)` (po:9052-9099) forces status COMPLETED, sets `current_round =
  max(rs.current_round, summary.rounds_executed)` and per-platform status
  (`completed`/`incomplete`/`disabled`/`unknown`), then `sim_manager._save_simulation_state(ss)`.
  Errors only warn.
- `_complete_stage(STAGE_RUN, message, reused=run_stage_done)` (po:13170-13175).
- `_log_decision_channel_outcome(state, sim_id)` (po:13180-13183; po:10738-10790) writes
  `options["decision_channel_summary"]` (scenarios seeded, `world_state_trajectory.json`
  produced, leader/share, converged_at). Errors are debug-only.

### G. Stage 5 — REPORT (po:13185-13328)

**G1. Reuse decision (po:13186-13244).**
- Updater and `_update_manifest(STAGE_REPORT)` (po:13186-13187). Note that **no `upd` call
  happens before the preflight on the rebuild path**, so `state.current_stage` still says
  `run` during G1/G2 (see Surprises).
- Look up `existing_report = ReportManager.get_report(state.report_id)`
  (report_agent.py:14285). As a fallback, use `ReportManager.get_report_by_simulation(sim_id)`
  (report_agent.py:14353), the newest by created_at. Exceptions → None (po:13195-13206). The
  signal is the persisted report itself, not the stage bit, because `_fail_stage`/`resume`
  always leave REPORT non-completed (comment po:13188-13194).
- Deliverable check (po:13211-13222): when `PIPELINE_HEALTH_GATE` (default true) is on,
  `_assess_report_health(candidate_id)` (po:9161). `failed` → drop the reuse and set
  `options["report_rebuilt_broken_deliverable"]`. An exception counts as `ok`.
- Force regen (po:13224-13226): `options.pop("force_report_regen")` (set by `resume(force=True)`,
  po:8158-8164) skips reuse once.
- Integrity (po:13227-13240): temporarily sets `state.report_id` to the candidate. If
  `_reuse_ok(STAGE_REPORT)` fails (`viz_manifest.json` entry plus viz reference validation,
  po:9880-9884), it sets `options["report_rebuilt_artifact_validation"]` and restores the
  previous id.
- Reuse when the existing report's `status != ReportStatus.FAILED`: `upd(100)`, keep its id,
  `_complete_stage(..., "报告完成（复用）", reused=True)` (po:13241-13244). Note this is a
  not-FAILED check, not a COMPLETED check.

**G2. Regenerate (po:13245-13328).**
1. **LLM preflight** (po:13250-13261): when `REPORT_LLM_PREFLIGHT` (default true) is on, call
   `LLMClient().chat([{"role":"user","content":"ping <8hex> — reply: pong"}], temperature=0.0,
   max_tokens=64)` (`backend/app/utils/llm_client.py:399`). The uuid avoids the LLM cache. Any
   exception → `RuntimeError("报告前置探测失败：主/回退 LLM 提供方均不可用 …")`.
2. `_clear_report_attempt_artifacts(state)` (po:9682-9705) drops `*_partial`,
   `report_viz_manifest`, `report_chart_*` from artifacts and the handoff manifest. Then
   `report_id = "report_" + uuid4().hex[:12]`, `state.report_id = report_id`, save
   (po:13265-13268). **A new id is always minted**; a failed report's id is never reused.
3. `upd(5, "生成预测报告…")` (po:13269).
4. Scenario context: `scenario_label`, and `base_simulation_id` from
   `PipelineManager.load(base_pipeline_id)` for forks (po:13271-13279).
5. `ReportAgent(graph_id, simulation_id, simulation_requirement=prompt,
   situation_brief=situation_brief(actors), actors, sources, research_report=report_md,
   scenario_label, base_simulation_id, quantitative, contested, timeline_events, graph_priors,
   graph_priors_structural)` (po:13285-13311; constructor report_agent.py:1533-1553). The last
   five are read with `_read_json` from the handoff (`quantitative.json`, `contested.json`,
   `timeline.json`, `graph_priors.json`, `graph_priors_structural.json`). A `TypeError` → retry
   without the artifact kwargs (po:13312-13315).
6. `report = agent.generate_report(progress_callback=report_cb, report_id=report_id)`
   (po:13320; report_agent.py:11113). This is the **ReACT multi-tool LLM** stage. `report_cb`
   maps progress to 5..99 (po:13317-13318).
7. `ReportManager.save_report(report)`, with errors silently ignored (po:13321-13324).
   `state.report_id = report.report_id`. `status == FAILED` → `RuntimeError(report.error)`
   (po:13325-13327).
8. `_complete_stage(STAGE_REPORT, "报告完成")` (po:13328).

### H. Seed ensemble (po:13330-13340)

If `state.mode == "full"` (always true here), it calls `_maybe_run_seed_ensemble(state, project,
graph_id, actors, research, report_md)` (po:8529). That returns immediately unless the pinned
`n_forecast_seeds` (fallback `N_FORECAST_SEEDS`, default 1) >1, `REPORT_STRUCTURED_FORECAST` is
on and `ensemble_done` is unset (po:8546-8549). `PipelineCancelled` is re-raised. Any other
exception is only a warning, so the primary report stands.

### I. DONE / publish (po:13342-13357)

1. `_enforce_pipeline_health(state)` (po:13345; po:9445-9501). Gated by `PIPELINE_HEALTH_GATE`.
   It assesses the report (`_assess_report_health`), run (`_assess_run_health`) and graph (skip
   ratio, prune degradation), then writes `options["pipeline_health"] = {status:
   ok|degraded|failed, stages:{…}}`. Report-health `failed` → `RuntimeError("交付物健康检查失败
   （deliverable is broken）: …")`. An exception in the assessment itself is swallowed, so the
   run passes.
2. `state.status = "completed"`, `global_progress = 100`, `PipelineManager.save(state)`
   (po:13346-13348).
3. `task_manager.complete_task(task_id, {pipeline_id, project_id, graph_id, simulation_id,
   report_id})` (po:13349-13356).

"Publish" in this slice means exactly that status flip plus the task completion. The report's own
on-disk publication (sections, forecast.json, full_report.md) happens inside
`ReportAgent.generate_report`. The research contract's publication happens in
`_finalize_research_contract` (B7), and the run summary's in `_publish_run_summary` (F3).
Telemetry is written in the `finally` block.

### J. Exception handlers (po:13359-13392)

| Handler | Anchor | Behavior |
|---|---|---|
| `except PipelineCancelled` | po:13359-13376 | `status="cancelled"`, `error=str(e)`. The current stage gets `cancelled` + error **unless** it is already completed or at progress ≥100. `finished_at` is set if missing. Then save and `task_manager.fail_task(...)`; there is no dedicated cancel task API. |
| `except ProviderOutageHalt` | po:13377-13380 | `_halt_for_provider_outage(state, task_manager, e)` (po:9766-9794): `status="failed"`, `options["provider_outage_halt"]` = breaker snapshot + provider + halted_at + halted_stage + `"POST /api/research/<pid>/resume"`, `_fail_stage(current_stage)`, save, `fail_task`. |
| `except Exception` | po:13381-13392 | Logs with traceback. `status="failed"`, `error=str(e)`, `_fail_stage(state, state.current_stage, msg)` (po:9757-9764: stage failed + finished_at + save + telemetry flush), save, `fail_task`. |

`PipelineCancelled` and `ProviderOutageHalt` are `BaseException` subclasses (po:248, po:258), so
they pass through every inner `except Exception` defense layer. Other `BaseException`s
(KeyboardInterrupt/SystemExit) have no handler: the status is not updated, but `finally` runs.

### K. finally (po:13393-13492)

1. `hb_stop.set()` stops the heartbeat thread (po:13395-13396).
2. Telemetry (po:13398-13485), inside an outer try (errors are debug-only):
   - `extra = {pipeline_id, status, report_id}` plus `report_telemetry` from
     `reports/<report_id>/telemetry.json` (po:13407-13414) plus `sim_llm_health` from
     `uploads/simulations/<sim>/llm_health.json` (po:13417-13424).
   - `_flush_run_telemetry(state, final=True, extra)` (po:13430; po:7575-7614) writes the final
     `uploads/pipelines/<pid>/run_telemetry.json` (fsync; `cumulative_total` merged with the
     previous attempt). `artifacts["run_telemetry"]` is set and state saved (po:13431-13434).
   - Stage telemetry (po:13440-13482): `build_stage_telemetry(pid, _stage_walls(state))`
     (telemetry.py:445; po:3811) → `uploads/pipelines/<pid>/telemetry.json` (atomic,
     `artifacts["telemetry"]`). A compact `options["llm_telemetry"]` = {total, by_stage,
     cost_estimated, cost_basis}, then save. When `status=="completed"` and there is a report_id,
     `render_telemetry_appendix` (telemetry.py:491) → `reports/<rid>/telemetry.md`. When
     `REPORT_TELEMETRY_APPENDIX` (default false) is on, it is also appended to `full_report.md`
     if `## Run Telemetry` is absent.
   - `LLMMeter.reset(pid)` (po:13483; telemetry.py:353).
3. `_clear_outage_breaker(pid)` (po:13488; po:549).
4. `cls._threads.pop(pid)` and `cls._cancel_events.pop(pid)` (po:13491-13492), so
   `reconcile_orphans`/`resume` see the thread as gone.

---

## Control flow — ordered stage table

| # | Stage | Reuse gate(s) | Main work (call → anchor) | Persisted at end | Mode notes |
|---|---|---|---|---|---|
| pre | preamble | — | breaker po:11891, telemetry init po:11894, run.json po:11897, heartbeat po:11900 | run.json, heartbeat_at | all |
| 0 | RESEARCH | report ≥400 chars + (contract valid + judge quality) OR (stage bit + `_validate_reuse`) po:11919-11959 | synthesis recovery po:11971 / parallel tracks po:11990 (legacy only) / `DeerFlowResearchRunner.run` po:12047 | handoff contract (finalize po:12267), cast_reconciliation.json, options, stage artifacts + manifest (po:12287) | `research_only` exits at po:12294-12305 |
| 1 | ONTOLOGY | `project.ontology` truthy po:12312 | `OntologyGenerator.generate` po:12346 | project.json (ProjectManager), handoff/ontology.json po:12384 | full |
| 2 | GRAPH | bit + graph_id + manifest + v1 seed readback + entity count>0 po:12392-12441 | `create_graph` po:12496, seed po:12524, `add_text_batches` po:12544, wait po:12572, communities/resolve/prune po:12576-12637 | graph in FalkorDB, project.graph_id, priors/communities/merges/prune json | full |
| 3 | PREPARE | bit + sim exists + manifest + config seal po:12740-12764 | `create_simulation` po:12776, `prepare_simulation` po:12811, overlay po:12855, world-state seed po:12878, reseal po:12924 | sim dir (config, personas, manifests), stage artifacts (after mutation) po:12933 | forks set overlay |
| 4 | RUN | prepare reused + bit + `_run_reuse_ready` + manifest, or disk reuse po:12942-12969 | `start_simulation` po:12989, poll loop po:13005-13061 | run_summary.json po:13108, sim state po:13160, telemetry | full |
| 5 | REPORT | existing report not FAILED + health not failed + not forced + manifest po:13195-13241 | preflight po:13250, `ReportAgent.generate_report` po:13320 | report dir, state.report_id po:13268/13325 | full |
| 6 | ensemble | pinned n_seeds>1 po:8546 | `_maybe_run_seed_ensemble` po:13335 | ensemble_forecast.json | full |
| 7 | DONE | — | `_enforce_pipeline_health` po:13345 | status=completed, task completed | full |

Lifecycle entry → `_run`: `start` (po:7920-7979) creates fresh stages and options, pins
`actor_intelligence_policy_v1` and `safety_policy_v1`, then spawns. `resume` (po:8107-8211)
resets only the `current_stage` stage if it is failed/cancelled (or REPORT when forced) via
`_reset_stage_attempt` (po:3839), mints a new task id, then spawns. `continue_to_full`
(po:8214-8277) flips mode to full and resets every non-research stage. `fork` (po:8280-8350)
marks RESEARCH/ONTOLOGY/GRAPH completed, shares the base `handoff_dir`/`project_id`/`graph_id`,
and sets `current_stage=PREPARE`.

---

## Data & artifacts

**Directories.**
- Pipeline dir: `backend/uploads/pipelines/<pid>/` (`Config.PIPELINE_DATA_DIR`,
  `backend/app/config.py:1581`; po:875-877).
- Handoff: `<pipeline dir>/handoff/` (po:884-885), or the base pipeline's handoff for forks. [verifier: the
  integrity manifest does not follow `state.handoff_dir`. `artifact_manifest_path` always uses the
  pipeline's own static `handoff_dir(pipeline_id)` (po:1107-1110). For a fork that is the fork's
  empty `uploads/pipelines/<fork>/handoff/manifest.json`. As a result, `_validate_reuse` passes
  vacuously for the fork's RESEARCH/GRAPH reuse, because a missing manifest returns True
  (po:9811-9816).]
- Sim dir: `backend/uploads/simulations/<sim_id>/` (`Config.OASIS_SIMULATION_DATA_DIR`,
  `backend/app/config.py:1080`, which resolves to the same place as
  `SimulationRunner.RUN_STATE_DIR`, `backend/app/services/simulation_runner.py:279-282`, and
  `_sim_dir`, po:9109-9111).
- Reports: `ReportManager._get_report_folder(rid)` under `Config.UPLOAD_FOLDER/reports`
  (`backend/app/services/report_agent.py:11864`, `:11890`).

**Files read by the slice.**
- `handoff/research_report.md` (po:11905, via `_load_research_handoff`)
- `handoff/research_contract_manifest.json` (po:11910)
- `handoff/evidence_synthesis_manifest.json` (po:11916)
- `handoff/research_checkpoint.json` (inside po:11996)
- `handoff/research_budget.json` and `meta.json` (via B5 helpers)
- `handoff/graph_priors.json` (po:12794-12799)
- `handoff/communities.json` (po:13104-13107)
- `handoff/{quantitative,contested,timeline,graph_priors,graph_priors_structural}.json`
  (po:13302-13309)
- `<sim>/simulation_config.json` (po:12857-12862, po:12898-12903, po:13026-13030)
- `<sim>/run_summary.json` (po:13147-13154)
- `reports/<rid>/telemetry.json`, `<sim>/llm_health.json`, `reports/<rid>/full_report.md`
  (finally)

**Files written by the slice (directly).**

| Path | Writer | Format / key fields |
|---|---|---|
| `handoff/actors.json` (legacy cast, no contract) | po:12172-12173 | reconciled actors JSON (atomic) |
| `handoff/cast_reconciliation.json` | po:12174 | reconcile audit (merged, applied, n_before/n_after…) |
| `handoff/ontology.json` | po:12384 | `project.ontology` (entity_types, edge_types, + rich keys) (atomic) |
| `handoff/communities.json` | po:12583-12584 | list of communities (non-atomic) |
| `handoff/entity_merges.json` | po:12602-12603 | resolver audit (merges, merged_nodes, nodes_scanned) (non-atomic) |
| `handoff/graph_prune.json` | po:12628 | prune audit (atomic) |
| `handoff/graph_priors.json` | po:12704 | `{node_name: centrality∈[0,1]}`, alias-folded (atomic) |
| `handoff/graph_priors_structural.json` | po:12716-12720 | `{betweenness:{}, chokepoints:[]}` (atomic) |
| `<sim>/simulation_config.json` | po:12864-12867 (overlay, tmp+replace), po:12910-12911 (`world_state_seed`, atomic) | config with `agent_configs`, `event_config.scheduled_events`, `temporal_config`, `world_state_seed{scenarios, as_of_date, horizon_date, horizon_source, horizon_defaulted}` |
| `uploads/pipelines/<pid>/run_telemetry.json` | po:13430 | LLMMeter snapshot + extra + previous_attempt/cumulative_total |
| `uploads/pipelines/<pid>/telemetry.json` | po:13447 | stage × calls/tokens/cost/wall |
| `reports/<rid>/telemetry.md` / `full_report.md` append | po:13469-13480 | "Run Telemetry" markdown |
| `uploads/pipelines/<pid>/pipeline_state.json` | `PipelineManager.save` (po:945) at po:11968, 12297, 12326, 12782, 13268, 13348, 13371, 13387, 13434, 13459 + every `upd` | full `PipelineState` |

Indirect writes go through helpers: `run.json`, `handoff/manifest.json` (integrity, po:1108),
the research contract generation, the project JSON, the graph DB, the sim dir (prepare/run), the
report dir, and `run_summary.json`.

**In-memory structures.**
- `research: dict` with keys `report, report_path, actor_dossier, actors, sources, timeline,
  exit_code, research_telemetry, resumed, meta` (po:3876-3887, po:12213).
- `actors: dict|None` (actor-intelligence cast; may be mutated in place by
  `inject_forecast_inputs_from_report`).
- `report_md: str`, `dossier_md: str|None`, `project`, `graph_id`, `sim_state`, `rs`.
- Reuse flags `_reuse_research, _reuse_graph, _prepare_reuse, _sim_disk_reuse,
  _run_already_done, run_stage_done`.
- `state.options` keys written directly in the slice: `research_track_pids` (popped),
  `research_lint`, `cast_reconciliation`, `dossier_coverage`, `dossier_coverage_warning`,
  `resumed_stage_validation`, `graph_entity_count`, `graph_chunk_source`,
  `as_of_date_correction`, `graph_seeded_edges`, `graph_skipped_chunks`, `graph_total_chunks`,
  `graph_ingest_degraded_ratio`, `graph_communities`, `entity_merges`, `graph_prune`,
  `graph_duplicate_name_groups`, `graph_node_count`, `graph_edge_count`, `graph_components`,
  `graph_centrality_nodes`, `artifact_validation_error`, `report_rebuilt_broken_deliverable`,
  `report_rebuilt_artifact_validation`, `force_report_regen` (popped), `llm_telemetry`.
- `state.options` keys written via helpers: `research_telemetry`, `research_quality(_warning)`,
  `research_budget`, `forecast_confidence_penalty(_components)`,
  `actor_intelligence_reception`, `dynamic_bands`, `cost_signals`, `sim_llm_telemetry`,
  `sim_llm_telemetry_recorded`, `decision_channel_summary`, `pipeline_health`,
  `provider_outage_halt`.

---

## Config / env knobs

| Knob | Default (config.py) | Effect in slice | Anchor |
|---|---|---|---|
| `LLM_OUTAGE_HALT_CONSECUTIVE` | 10 (`config.py:69`) | ≤0 → no breaker/probe; else consecutive provider failures trip `ProviderOutageHalt` | po:11891, po:379 |
| `PIPELINE_HEARTBEAT_ENABLED` / `_INTERVAL_S` | true / 30 (`config.py:457-458`) | heartbeat thread | po:11900, po:10339, po:10348 |
| `RECORD_RUN_MANIFEST` | true (`config.py:426`) | run.json write/updates | po:11897, po:10380, po:10402 |
| `RESEARCH_ENGINE` | `v3` (`config.py:1187`) | engine; v3 → 1 outer lane | po:11983, po:5919 |
| `RESEARCH_PARALLEL_TRACKS` | 3 (`config.py:1196`) | legacy outer lanes | po:11985 |
| `RESEARCH_GLOBAL_SUBAGENT_CAP` / `RESEARCH_SUBAGENTS_PER_TRACK_MAX` / `RESEARCH_GLOBAL_MODEL_CONCURRENCY` | 9 / 5 / 0 (`config.py:1205-1213`) | single-lane concurrency envelope | po:12020-12032 |
| `DEERFLOW_SUBAGENTS` | true (`config.py:1168`) | subagents flag to runner | po:12069-12071 |
| `DEERFLOW_RESEARCH_DEPTH` | `deep` (`config.py:1159`; slice fallback `"standard"`) | checkpoint lineage depth when option missing | po:12001-12005 |
| `REPORT_LINT` | true (`config.py:558`) | research lint | po:12084 |
| `DEERFLOW_RESEARCH_LANGUAGE` | None (`config.py:1163`) | lint language | po:12100-12101 |
| `CAST_RECONCILE` | true (`config.py:372`) | cast dedup | po:12156 |
| `EMBED_WARM_AT_RESEARCH` | false (`config.py:476`) | embedder warm thread | po:12208, po:11840 |
| `ONTOLOGY_FROM_DOSSIER` | **true** (`config.py:379`; slice fallback False, comment says "默认关") | append ontology seed block | po:12338 |
| `ONTOLOGY_RICH_SCHEMA` | true (`config.py:368`) | keep full ontology dict | po:12366 |
| `PIPELINE_VALIDATE_ARTIFACTS` | true (`config.py:466`) | `_reuse_ok` checks; false → always reuse | po:9895 |
| `GRAPH_CHUNK_SOURCE` | **`dossier_only`** (`config.py:481`; slice fallback `"both"`) | graph ingest source | po:12484 |
| `VALIDATE_AS_OF_DATE` | true (`config.py:477`) | as_of validation | po:12512 |
| `GRAPH_SEED_FROM_ACTORS` | true (`config.py:1236`) | actor seeding; off + v1 → raise | po:7203-7208 |
| `GRAPH_MAX_SKIPPED_RATIO` | 0.3 (`config.py:577`) | ingest degraded threshold (`0` coerced to 0.3) | po:12559 |
| `GRAPH_BUILD_COMMUNITIES` | false (`config.py:1266`) | communities.json | po:12576 |
| `GRAPH_RESOLVE_ENTITIES` | true (`config.py:1282`) | entity resolution | po:12594 |
| `GRAPH_PRUNE_ENABLED` | **true** (`config.py:1297`; slice fallback False) | pruning | po:12614 |
| `GRAPH_BUILD_CONCURRENCY` | **4** (`config.py:1240`; slice fallback 1) | duplicate-name detection when >1 | po:12660 |
| `ZEP_API_KEY` | `local-graphiti` (`config.py:1038`) | GraphBuilderService key | po:12407, po:12458 |
| `PARALLEL_PROFILE_COUNT` | 16 (`config.py:474`) | persona fan-out for openai_compat providers (else 3) | po:12804, po:12816 |
| `SIM_TEMPORAL_MODE` | `calendar` (`config.py:1067`) | calendar mode: no default round cap; unconditional world-state injection | po:12810, po:12878, po:12980 |
| `OASIS_DEFAULT_MAX_ROUNDS` | 36 (`config.py:1063`) | round cap in non-calendar mode | po:12810, po:12980 |
| `SIM_DECISION_CHANNEL` | **true** (`config.py:1483`; slice fallback False, comment "默认关") | world-state seed injection | po:12879 |
| `SIM_RESUME_REUSE_COMPLETED` | true (`config.py:596`; env read first) | disk reuse of completed sim | po:7475-7487 |
| `SIM_GRAPH_FEEDBACK` | false (`config.py:1385`), pinned via `safety_policy_v1` | sim→graph feedback + confluence barrier | po:12985, po:13082 |
| `PIPELINE_RUN_STALL_S` | 1800 (`config.py:355`, doc says ≤0 disables) | inline + independent stall watchdog | po:12996, po:13001 |
| `PIPELINE_HEALTH_GATE` | true (`config.py:167`) | report-reuse deliverable check + final health gate | po:13212, po:9448 |
| `REPORT_LLM_PREFLIGHT` | true (`config.py:503`) | ping before report | po:13250 |
| `N_FORECAST_SEEDS` (pinned `n_forecast_seeds`) | 1 (`config.py:303`) | ensemble | po:8541-8543 |
| `REPORT_STRUCTURED_FORECAST` | true (`config.py:162`) | ensemble precondition | po:8547 |
| `REPORT_TELEMETRY_APPENDIX` | false (`config.py:395`) | append telemetry to full_report.md | po:13475 |
| `LLM_TELEMETRY_ENABLED` | true (`config.py:58`) | synthetic research/run meter records | po:10446, po:10540 |
| `RESEARCH_QUALITY_GATE` / `RESEARCH_QUALITY_FLOOR` | false / 0.45 (`config.py:348`, `:351`) | soft research-quality warning | po:10626-10637 |

---

## External calls

| Target | Kind | Anchor |
|---|---|---|
| DeerFlow research subprocess (`DeerFlowResearchRunner.run` → `subprocess.Popen(start_new_session=True)`) | subprocess + LLM + web | po:12047, po:2428-2441 |
| Parallel research lanes / synthesis recovery subprocesses | subprocess | po:11990, po:11971 |
| `lint_report` | local, deterministic | po:12108 |
| `OntologyGenerator.generate` | LLM | po:12346 |
| `GraphBuilderService.create_graph/set_ontology/seed (via _seed_research_actors)/add_text_batches/_wait_for_episodes/build_communities/_get_graph_info` | Graphiti/FalkorDB + LLM extraction + embeddings | po:12496-12572, po:12579, po:12690 |
| `ZepEntityReader.filter_defined_entities` | graph DB read | po:12432 |
| `resolve_entities` | graph DB (no LLM per comment) | po:12598 |
| `prune_graph` | graph DB mutate | po:12619 |
| `get_runtime().all_entity_nodes` | graph DB read | po:12665 |
| `SimulationManager.create_simulation/prepare_simulation/reseal_simulation_config/validate_prepared_simulation_config` | local + LLM (profiles/config) | po:12776, po:12811, po:12925, po:12747 |
| `SimulationRunner.start_simulation` (OASIS subprocess), `get_run_state`, `stop_simulation`, `join_monitor_thread`, `write_run_summary` | subprocess / IPC / disk | po:12989, po:13014, po:13010, po:13085, po:10108 |
| `ZepGraphMemoryManager.stop_updater` | graph writer drain | po:13090 |
| `LLMClient().chat` ping | LLM | po:13253-13256 |
| `ReportAgent.generate_report` | LLM ReACT + graph tools | po:13320 |
| `TaskManager.update_task/complete_task/fail_task` | in-process task store | po:9001, po:12299, po:13350, po:13374, po:13390 |
| `ProjectManager.*`, `ReportManager.*`, `PipelineManager.*` | local JSON persistence | throughout |

---

## Cross-module edges

**Into this slice (callers of `_run`).** Only via thread spawns in the same class:
- `PipelineOrchestrator.start` (po:7972) ← `POST` handlers `backend/app/api/research.py:109`,
  `backend/app/api/sdk.py:136`
- `resume` (po:8204) ← `backend/app/api/research.py:164`
- `continue_to_full` (po:8269) ← `backend/app/api/research.py:199`
- `fork` (po:8346) ← `backend/app/api/research.py:240`

**Out of this slice.**
- Same file: `_make_stage_updater` po:8949, `_complete_stage` po:9009, `_fail_stage` po:9757,
  `_halt_for_provider_outage` po:9766, `_validate_reuse` po:9798, `_reuse_ok` po:9887,
  `_run_reuse_ready` po:9910, `_completed_sim_reusable` po:9976,
  `_require_run_completion_evidence` po:10059, `_publish_run_summary` po:10086,
  `_start_heartbeat` po:10331, `_write_run_manifest` po:10374, `_update_manifest` po:10393,
  `_record_research_telemetry` po:10430, `_record_sim_run_telemetry` po:10473,
  `_surface_research_quality` po:10564, `_surface_forecast_confidence_penalty` po:10716,
  `_log_decision_channel_outcome` po:10738, `_validate_as_of_date` po:10795,
  `_run_research_synthesis_recovery` po:10841, `_run_parallel_research_tracks` po:11060,
  `_maybe_warm_embedder` po:11832, `_recompute_dynamic_bands` po:8904,
  `_spawn_run_stall_watchdog` po:9113, `_reconcile_completed_simulation_state` po:9052,
  `_assess_report_health` po:9161, `_enforce_pipeline_health` po:9445,
  `_clear_report_attempt_artifacts` po:9682, `_maybe_run_seed_ensemble` po:8529,
  `_pinned_safety` po:8517, `_infer_horizon_date` po:8462, `apply_scenario_overlay_to_config`
  po:8353, plus module functions `_research_contract_path` po:3321,
  `_validate_research_contract` po:3418, `_research_contract_quality_errors` po:3216,
  `_research_report_is_judge_bound` po:3477, `_finalize_research_contract` po:3607,
  `_load_research_handoff` po:3857, `_reconcile_research_cast` po:3917,
  `_is_sealed_actor_intelligence_v1` po:3906, `_enforce_actor_intelligence_reception` po:5668,
  `inject_forecast_inputs_from_report` po:5752, `_forecast_inputs_missing` po:5740,
  `research_engine_for_run` po:5937, `research_outer_track_count` po:5955,
  `research_model_concurrency_cap` po:5845, `research_lane_subagent_cap` po:5857,
  `_validated_research_checkpoint_lineage` po:2974, `_activate_research_budget_epoch` po:1815,
  `_research_budget_exhaustion` po:1764, `_research_budget_attempt_ids` po:1806,
  `_graph_research_chunks` po:1298, `_seed_research_actors` po:7184,
  `_validate_actor_graph_seed_contract` po:7080, `_load_actor_graph_seed_manifest` po:7066,
  `_actors_to_context` po:6855, `_calendar_mode` po:7296, `_stage_walls` po:3811, outage
  helpers po:530/549/597.
- Other modules: `ontology_generator.py:539`, `graph_builder.py:1221/1233/2288/2427/2445/2456/628`,
  `zep_entity_reader.py:319`, `zep_entity_resolver.py:480`, `graph_pruner.py:244`,
  `graphiti_client/runtime.py:1882`, `simulation_manager.py:826/862/1318/1352/1454/757`,
  `simulation_runner.py:310/322/451/1665/2026`, `zep_graph_memory_updater.py:684`,
  `report_agent.py:1533/11113/14263/14285/14353/11890`, `report_lint.py:1534`,
  `utils/telemetry.py:42/58/224/353/445/491`, `utils/llm_client.py:399`,
  `models/task.py:106/145/155`, `models/project.py:133/168/181/279`, `utils/atomic.py:20/53`,
  `utils/actors` (`dossier_coverage`, `ontology_seed_block`, `world_state_seed_from_actors`,
  `normalize_name`, `situation_brief`).

---

## Invariants, gates, validation

1. **Only the stage updater changes `current_stage`** (po:8979). `_complete_stage`/`_fail_stage`
   never do. Failure attribution therefore depends on which `upd` ran last.
2. **Cancel and outage are checked on every progress callback** (po:8961-8969) and every 5 s in
   the RUN loop (po:13007). [verifier: the RUN loop checks only the cancel event every 5 s
   (po:13007-13013). The outage breaker is seen only when `upd` runs, which in RUN happens only
   on a round change (po:13021-13048). Hidden waits without `upd` include the REPORT preflight,
   which observes a tripped breaker as a generic `RuntimeError` (po:627, po:13257-13261).] Both are `BaseException`s, so inner `except Exception` blocks cannot
   absorb them (po:248-271).
3. **Research reuse requires integrity, not just existence.** With a contract, both checksum
   validity and judge quality must pass (po:11921-11946). Without one, a stage bit plus the
   manifest check is required (po:11947-11949). A ≥400-char report alone is never enough
   (po:11950-11954).
4. **The pre-launch budget gate** refuses to spawn research when a global tool cap is already
   saturated for the current epoch (po:12038-12046).
5. **Judge-bound and single-lane research bytes are never mutated by lint** (po:12097-12129). Only
   manifest-owned multi-lane reports adopt lint output, sealed by `_finalize_research_contract`
   (po:12267).
6. **Sealed actor-intelligence/v1 casts are immutable after the producer.** Reconciliation is
   audit-only (po:12189-12197), forecast_inputs injection is a no-op (po:5752 doc), and the seed
   must exist with exact UUIDs post-seed and post-mutation (po:12527-12534, po:12644-12651) and
   on reuse (po:12402-12426).
7. **Reception gate before ONTOLOGY** in full mode (po:12274-12286).
8. **Graph reuse requires ≥1 typed entity** (po:12434-12437).
9. **PREPARE completion hashes the final config.** Overlay and world-state mutations happen before
   `_complete_stage(PREPARE)`, with a mandatory reseal (po:12924-12938).
10. **A completed run's config is never mutated.** `_run_already_done` is computed before the
    mutation blocks (po:12848-12855, po:12879).
11. **RUN reuse is invalid when PREPARE was rebuilt** (po:12948-12951).
12. **The RUN completion evidence gate** needs `simulation_end` per enabled platform plus a valid
    run_summary, for fresh and reused runs alike (po:13130-13136).
13. **RUN spend is booked exactly once** across success, failure and reuse via
    `meter_run_token` (po:13067, po:13123, po:10498-10505).
14. **REPORT reuse is keyed on the persisted report, not the stage bit**, guarded by deliverable
    health, a force flag and the integrity manifest (po:13195-13241). [verifier: the
    deliverable-health guard runs only when `PIPELINE_HEALTH_GATE` is on (po:13211-13212), and an
    exception inside it counts as `ok` (po:13216-13217). The `get_report_by_simulation` fallback
    needs `sim_state is not None` (po:13202).]
15. **The final health gate** hard-fails a broken deliverable before `completed`
    (po:13345, po:9493-9494).
16. **The finally block always** stops the heartbeat, writes final telemetry, resets the meter,
    clears the breaker and deregisters the thread/cancel event (po:13393-13492). [verifier: only the
    heartbeat stop, breaker clear and registry pops are unconditional. The telemetry writes and
    `LLMMeter.reset` share one outer `try` (po:13398-13485). If `PipelineManager.save` at po:13434
    raises, `telemetry.json` and `LLMMeter.reset(pid)` (po:13483) are skipped, with only a debug
    log (po:13484-13485). `_flush_run_telemetry` swallows its own errors (po:7613-7614).]

---

## Failure modes & recovery

| Failure | Where raised | Resulting state | Recovery |
|---|---|---|---|
| Research budget exhausted pre-launch | po:12041 | failed, RESEARCH failed | resume → new task id → new budget epoch (po:1815 doc) [verifier: the number of epochs is capped. `_activate_research_budget_epoch` raises "research budget epoch limit reached" once `len(research_budget_epochs) >= RESEARCH_BUDGET_MAX_EPOCHS` (default 3) (po:1851-1856; backend/app/config.py:543-544). After three research task epochs, a resume that reaches fresh single-lane research fails at RESEARCH.] |
| Research subprocess error/timeout | inside `DeerFlowResearchRunner.run` | failed; failed-attempt spend metered (po:2128-2140) | resume; checkpoint lineage enables a pass-level resume (po:11995-12019) |
| Contract finalize inconsistency | po:3633-3648 | failed (RESEARCH) | resume; the prior valid generation is retained |
| v1 reception errors | po:5732-5736 | failed (RESEARCH) | upstream redo; resume |
| Ontology LLM failure | po:12346 | failed (ONTOLOGY) | resume reruns ONTOLOGY (the project already exists, so no new project) |
| v1 seed missing/partial/mutated | po:12524-12534, po:12644 | failed (GRAPH) | resume rebuilds the graph (a new graph_id is created; the old graph is left behind) |
| Optional graph steps (communities, resolve, prune, dup detect, integrity) | po:12587, 12608, 12636, 12684, 12724 | warning only | — |
| Reseal failure | po:12925 | failed (PREPARE) | resume |
| Sim run state lost / FAILED / STOPPED / stalled | po:13016, 13052, 13060 | failed (RUN), spend booked | resume; the disk-reuse probe may salvage a completed sim |
| Independent watchdog kill | po:9151 | poll sees STOPPED → failed | resume |
| Completion evidence missing | po:10075, 10081 | failed (RUN) | resume reruns RUN |
| Report preflight failure | po:13258 | failed, **attributed to RUN** (see Surprises) | resume (RUN disk-reuse usually rescues it) |
| Report status FAILED | po:13327 | failed (REPORT) | resume → new report_id |
| Broken deliverable at health gate | po:9494 | failed (REPORT) | resume → reuse guard rejects the broken report (po:13218-13222); `resume(force=True)` also works for completed-but-degraded runs (po:8145-8164) |
| User cancel | updater po:8963, RUN loop po:13013, research runner via cancel_event | cancelled; the in-flight stage is cancelled unless already complete | resume (accepts cancelled) |
| Provider outage breaker | updater po:8969 | failed + `options.provider_outage_halt` | `POST /api/research/<pid>/resume` |
| Backend crash mid-run | — | state left `running`; heartbeat goes stale | `reconcile_orphans` (po:7637) or `resume` reclaim (po:8131-8141) |

---

## Surprises

1. **Suspected bug: a REPORT preflight failure is attributed to the RUN stage.** On the rebuild
   path no `upd` runs before the preflight (po:13186-13261; the first `upd(5)` is at po:13269), so
   `state.current_stage` is still `"run"`. The generic handler then calls
   `_fail_stage(state, "run", …)` (po:13385-13386), flipping a completed RUN to `failed`. The
   message at po:13259-13260 promises a resume "from REPORT", but `resume()` resets the
   `current_stage` stage, which is RUN (po:8166-8170). The RUN is only rescued if
   `_completed_sim_reusable` succeeds (`SIM_RESUME_REUSE_COMPLETED`, default on); otherwise the
   simulation re-runs. The same mis-attribution applies to any exception raised between
   `_make_stage_updater(STAGE_X)` and the first `upd` of a stage, for example
   `sim_manager.get_simulation` at po:12737 would be blamed on GRAPH.
2. **Suspected bug: `PIPELINE_RUN_STALL_S=0` does not disable the watchdog.** Config documents
   "<=0 关闭" (`backend/app/config.py:353-355`), but the slice does `float(... or 1800)`
   (po:12996), so 0 becomes 1800 and the `_stall_s > 0` guards (po:13055, po:9125) are reached
   only by negative values. `GRAPH_MAX_SKIPPED_RATIO=0` has the same coercion to 0.3
   (po:12559).
3. **Suspected bug: a scenario fork of a run whose pinned actor policy is `required: True`
   (legacy engine) would likely fail reception.** `fork` copies the base policy (po:8321-8326) and
   shares the base handoff, but `_enforce_actor_intelligence_reception` validates lineage against
   **the fork's** `pipeline_id` and the fork's (empty) `research_budget_epochs` (po:5709-5722,
   po:5079-5085 → `actor_lineage_run_mismatch` / `actor_lineage_attempt_authority_missing`). No
   test covers fork+required policy (only `backend/tests/test_research_fork_handoff.py` exists for
   forks). It is not verified at runtime. v3 runs (default) are unaffected if their policy is not
   required.
4. **Suspected: forks do not pin `safety_policy_v1`** (`fork` options at po:8315-8320 have no
   `safety_policy_v1`). `_pinned_safety` therefore falls back to ambient Config for
   `sim_graph_feedback` (po:12985) and `n_forecast_seeds`. This contradicts the comment at
   po:12983-12984 that runs are immune to service reload. `start` (po:7966) and `resume`
   (po:8186-8189) do pin it.
5. **Forks write into the base pipeline's handoff.** `handoff_dir` is the base's (po:8306). Cast
   reconciliation (po:12172-12174), `_finalize_research_contract` (po:12267), and on a rebuilt
   graph `communities.json`/`graph_priors*.json` (po:12583, po:12704) all target the shared
   directory. Usually these are idempotent no-ops (finalize short-circuits on identical bytes,
   po:3670-3677), but they are not read-only.
6. **Comment/config drift inside the slice.**
   - po:12336 says `ONTOLOGY_FROM_DOSSIER` "默认关", but the default is true
     (`config.py:379`).
   - po:12478-12483 says `GRAPH_CHUNK_SOURCE` default `'both'`, but it is `dossier_only`
     (`config.py:481`).
   - po:12875 says `SIM_DECISION_CHANNEL` "默认关", but the default is true (`config.py:1483`).
   - po:12656 says `GRAPH_RESOLVE_ENTITIES` "默认关", contradicting po:12592 and
     `config.py:1282` (true).
   - po:12659 says "并发==1 … 默认路径逐字节不变", but `GRAPH_BUILD_CONCURRENCY` defaults to 4
     (`config.py:1240`), so duplicate detection runs by default.
   - The getattr fallbacks (`False`, `"both"`, `1`, `"standard"`) disagree with Config defaults.
     That is harmless while Config defines the attributes, but misleading.
7. **Research reuse bypasses `_reuse_ok`.** The no-contract path calls `_validate_reuse` directly
   (po:11948), so `PIPELINE_VALIDATE_ARTIFACTS=false` does not relax it, and an exception there is
   not fail-closed-and-logged like `_reuse_ok` (po:9897-9907). Every other stage uses `_reuse_ok`.
8. **ONTOLOGY reuse has no integrity check.** `project.ontology` being truthy is sufficient
   (po:12312). `ontology.json` is in the manifest specs (po:9523-9524) but is never validated
   on reuse.
9. **REPORT reuse checks `status != FAILED`, not `== COMPLETED`** (po:13241). With
   `PIPELINE_HEALTH_GATE=false` both the deliverable check (po:13211-13212) and the final gate
   (po:9448) are skipped, so a crashed `GENERATING`/`PLANNING` report (`report_agent.py:478-484`)
   could be reused and the run marked completed. This is suspected and only matters with the gate
   off.
10. **Dead or near-dead fallbacks.**
    - The `TypeError` fallback for `ReportAgent(**_ra_artifacts)` (po:13310-13315) is no longer
      needed: the constructor accepts all five kwargs (`report_agent.py:1547-1551`) [verifier: the
      five kwargs are at backend/app/services/report_agent.py:1548-1552; line 1547 is
      `charts_manifest`]. It could
      mask an unrelated `TypeError` raised inside `__init__` by retrying without research
      artifacts.
    - The `ImportError` branches for `report_lint` and `graph_pruner` (po:12144, po:12634)
      describe "module not yet deployed", but both modules exist.
    - `if state.mode == "full"` at po:13333 is always true at that point.
11. **Duplicated logic.** `inject_forecast_inputs_from_report` runs at po:12239 and again at
    po:12885 with the same deterministic inputs. The second call can only hit if the first missed,
    and then it would also miss, so it is redundant. The RUN reuse predicates (`_run_reuse_ready`,
    `_reuse_ok(STAGE_RUN)`) are evaluated in PREPARE (po:12848-12853) and again in RUN
    (po:12952-12960).
12. **Non-atomic writes amid atomic ones.** `communities.json` (po:12583) and
    `entity_merges.json` (po:12602) use plain `open(...,"w")`. The overlay uses a fixed
    `<cfg>.tmp` name (po:12864). `communities.json` is an integrity-tracked GRAPH artifact
    (po:9526), so a torn write forces a graph rebuild on resume.
13. **Silent swallows.**
    - `ReportManager.save_report` failure is ignored (po:13321-13324).
    - Write failures of `actors.json`/`cast_reconciliation.json` are ignored (po:12176-12177).
      In-memory actors can then diverge from disk for legacy casts.
    - `len(communities)` on a None return would raise inside the try and be logged as "community
      detection skipped" (po:12585-12588).
14. **The cancel handler uses `task_manager.fail_task`** (po:13374), so the task store cannot
    distinguish cancel from failure. There is no handler for other `BaseException`s, which leave
    `status="running"` until orphan reconciliation.
15. **The report preflight bypasses the outage handler.** If the outage breaker has tripped, the
    probe makes `chat()` raise `RuntimeError` (po:597 doc). The preflight wraps it as a generic
    `RuntimeError` (po:13258), so the run ends via the generic handler without
    `options.provider_outage_halt`. `ProviderOutageHalt` is raised only from the stage updater
    (po:8969; the only raise site in the backend).
16. **The PREPARE `initial_posts` artifact name points at `simulation_config.json`**
    (po:9535). This is a naming oddity shared with the reuse validator.
17. **Doc drift: architecture docs cite stale line numbers for this loop.**
    - `DRF_ARCHITECTURE.md:575` / `ARCHITECTURE_MAP.md:187` put ONTOLOGY at `:6697-6777` (actual
      po:12307-12387).
    - GRAPH is cited at `:6779-7063` (actual po:12389-12731).
    - PREPARE is cited at `:7065-7174` (actual po:12733-12938).
    - The report preflight is cited at `:7383-7394` (`DRF_ARCHITECTURE.md:275`; actual
      po:13250-13261).
    - The inline watchdog is cited at `:7246-7251` (actual po:13055-13060).
    - `_spawn_run_stall_watchdog` is cited at `:4533-4579` (actual po:9113-9159).
    - Stage constants are cited at `:74-101` (`ARCHITECTURE_MAP.md:116`; actual po:87-105).

    The band values themselves (0-30/30-40/40-60/60-72/72-92/92-100) still match po:95-102.

---

## Verification

An adversarial verifier re-read every cited line on `main` (read-only; no code was run). `po:` means
`backend/app/services/pipeline_orchestrator.py`. Inline `[verifier: …]` notes above mark each
statement that was corrected.

**Verdict counts.**

| Group | Checked | Confirmed | Imprecise | Refuted | Unverifiable |
|---|---|---|---|---|---|
| Key claims | 15 | 13 | 2 | 0 | 0 |
| Surprises (the reader's 14 listed) | 14 | 14 | 0 | 0 | 0 |
| Extra spot-checks (Walkthrough, Control flow, invariants, tables) | 16 | 7 | 9 | 0 | 0 |
| **Total** | **45** | **34** | **11** | **0** | **0** |

Surprise 3 (fork + `required: True`) is confirmed at the code level only. The lineage check uses
the fork's own `pipeline_id` and its empty `research_budget_epochs` (po:5709-5722, po:5079-5085),
and no test exercises `fork()` with a required policy. It has not been seen at runtime.

**Non-confirmed statements and corrections.**

1. *Claim: REPORT reuse is rejected if `_assess_report_health` is `failed`* — **imprecise.** The
   health guard runs only when `PIPELINE_HEALTH_GATE` is on (po:13211-13212), and an exception in
   the assessment counts as `ok` (po:13216-13217). The `get_report_by_simulation` fallback runs only
   when `sim_state is not None` (po:13202).
2. *Claim: the `finally` block always writes `run_telemetry.json`/`telemetry.json` and resets
   `LLMMeter`* — **imprecise.** The heartbeat stop (po:13395-13396), breaker clear (po:13488) and
   registry pops (po:13491-13492) are unconditional. The telemetry writes and `LLMMeter.reset` share
   one outer `try` (po:13398-13485). A `PipelineManager.save` failure at po:13434 skips
   `telemetry.json` and `LLMMeter.reset` (po:13483) with only a debug log. Each write is best-effort.
3. *Walkthrough B1: the updater is "the only place `current_stage` changes"* — **imprecise.** That
   holds inside `_run` (po:8979). The lifecycle methods also set it: `resume(force=True)`
   (po:8164), `continue_to_full` (po:8263) and `fork` (po:8341).
4. *Walkthrough B5: `_surface_research_quality` rewrites `meta.json` only when there is no contract
   manifest* — **imprecise.** It also needs a `research_budget.json` that shows `degraded` or
   `denied_*` counts (po:10583-10621).
5. *Walkthrough F2: the independent watchdog "exits on `completed`/`error`"* — **imprecise.** It
   tests `rs.get("completed")` (po:9142), but `run_state.json` has no `completed` key
   (backend/app/services/simulation_runner.py:209-245). Only `error` or `ctl["stop"]`
   (po:13069-13070) ends it.
6. *Invariant 2: cancel and outage are checked every 5 s in the RUN loop* — **imprecise.** Only
   cancel is polled every 5 s (po:13007-13013). The outage breaker is seen only when `upd` runs on a
   round change (po:13021-13048).
7. *Invariant 14: REPORT reuse is guarded by deliverable health* — **imprecise.** Same gate
   condition as item 1 (po:13211-13217).
8. *Invariant 16: the `finally` block always writes telemetry and resets the meter* —
   **imprecise.** Same correction as item 2 (po:13398-13485).
9. *Data & artifacts: handoff is the base's for forks; the integrity manifest is
   `handoff/manifest.json`* — **imprecise for forks.** `artifact_manifest_path` always uses the
   pipeline's own static handoff (po:1107-1110), so for a fork it is an empty file in the fork's own
   directory. `_validate_reuse` then passes vacuously (po:9811-9816).
10. *Failure modes: research budget exhausted → resume opens a new epoch* — **imprecise.** Epochs
    are capped at `RESEARCH_BUDGET_MAX_EPOCHS` (default 3). After that, `_activate_research_budget_epoch`
    raises (po:1851-1856; backend/app/config.py:543-544).
11. *Surprise 10 body anchor: the five `ReportAgent` kwargs are at `report_agent.py:1547-1551`* —
    **imprecise (anchor).** They are at backend/app/services/report_agent.py:1548-1552. The
    substance of the surprise is confirmed.

**Spot-checks that held** (all confirmed):
- B2 concurrency envelope 10/5 (po:5845-5873; backend/app/config.py:1205-1213).
- D2 chunk-source recording rules (po:12484-12494).
- `pipeline_state.json` save sites (po:11968, 12297, 12326, 12782, 13268, 13348, 13371, 13387,
  13434, 13459).
- E3 `_completed_sim_reusable` requirements (po:9994-10057).
- E4 overlay idempotence for injected events (po:8394-8448).
- The lifecycle-entry paragraph (po:7953-7967, po:8159-8171, po:8245-8263, po:8309-8341).
- The Config/env defaults table (every default re-read in backend/app/config.py).

**Omissions (significant behavior the map did not state).**

1. **Research budget epoch cap.** Each RESEARCH task id gets one ledger epoch. A fourth epoch makes
   `_activate_research_budget_epoch` raise "research budget epoch limit reached". The guard sits
   before the pre-launch exhaustion gate on the single-lane path (po:1851-1856, po:12033-12037;
   backend/app/config.py:543-544).
2. **The integrity manifest is keyed by pipeline id, not by `state.handoff_dir`** (po:1107-1110).
   Forks share the base handoff but check reuse against their own empty manifest, so their
   RESEARCH/GRAPH `_validate_reuse`/`_reuse_ok` checks are vacuous (po:9811-9816). Later
   `_record_stage_artifacts` calls record base-handoff paths into the fork's manifest
   (po:9746-9753).
3. **`fork()` drops the run's research options.** It copies only `scenario_overlay`,
   `scenario_label`, `base_pipeline_id`, `project_name` and the actor policy (po:8315-8326), not
   `depth`, `research_language` or `research_model` (compare `start`, po:7953-7961). Reception
   therefore expects `Config.DEERFLOW_RESEARCH_DEPTH` (po:5717-5720). This can add
   `actor_lineage_depth_mismatch` to Surprise 3 for a non-default-depth base. PREPARE receives
   `research_language=None` (po:12820), and research lint falls back to Config/CJK inference
   (po:12100-12107).
4. **RESEARCH-preamble failure attribution** (the earliest case of Surprise 1). The reuse checks at
   po:11919-11959 run before RESEARCH's first `upd` (po:11961/11965). On a resume, an exception
   there (for example from `_validate_reuse`, which is not wrapped, po:11948) is charged by the
   generic handler to whichever stage the previous attempt left in `current_stage` (po:13385-13386).
   On a fresh `start`, `current_stage` is `""`, so no stage is marked failed (po:691).
