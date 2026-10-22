# Python module navigation index

Source: main `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`. This index contains 146 tracked Python files outside `backend/tests`, totaling 151,957 source lines. The 180 backend test files are separately indexed in `python-inventory.json`. An inventory entry is not a claim of full reading; consult `coverage-validation.json` and reader receipts for that distinction.

All paths and symbols below refer to the frozen source. Local live files may include concurrent edits. Symbols are top-level definitions; the inventory JSON retains their line spans and import lists.

## coordinator

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/models/__init__.py` | 9 | Package exports / initialization | [coordinator](supporting-services.md) |
| `backend/app/models/project.py` | 309 | `ProjectStatus`:17, `Project`:27, `ProjectManager`:101 | [coordinator](supporting-services.md) |
| `backend/app/models/task.py` | 184 | `TaskStatus`:14, `Task`:23, `TaskManager`:54 | [coordinator](supporting-services.md) |
| `backend/app/services/__init__.py` | 73 | Package exports / initialization | [coordinator](supporting-services.md) |
| `backend/app/services/pipeline_orchestrator.py` | 13,492 | `PipelineCancelled`:248, `ProviderOutageHalt`:258, `IncompatiblePipelineSchema`:274, `StageState`:660, `PipelineState`:683, `capture_safety_policy_v1`:776 | [coordinator](orchestrator-execution.md) |
| `backend/app/services/requirement_spec.py` | 105 | `detect_output_language`:34, `parse_requirement_spec`:85 | [coordinator](supporting-services.md) |
| `backend/app/services/research_progress.py` | 564 | `ResearchProgressLimitError`:75, `ProgressTail`:80, `ResearchProgressEstimator`:147, `aggregate_parallel_progress`:371, `merged_research_progress_tail`:500, `merged_research_progress_full`:520 | [coordinator](supporting-services.md) |
| `backend/app/services/text_processor.py` | 86 | `TextProcessor`:15 | [coordinator](supporting-services.md) |
| `backend/app/utils/__init__.py` | 9 | Package exports / initialization | [coordinator](supporting-services.md) |
| `backend/app/utils/atomic.py` | 77 | `write_text_atomic`:20, `write_json_atomic`:53 | [coordinator](supporting-services.md) |
| `backend/app/utils/chart_html.py` | 77 | `inline_plotly_bundle`:30 | [coordinator](supporting-services.md) |
| `backend/app/utils/dates.py` | 69 | `parse_as_of`:38 | [coordinator](supporting-services.md) |
| `backend/app/utils/file_parser.py` | 192 | `FileParser`:61, `split_text_into_chunks`:147 | [coordinator](supporting-services.md) |
| `backend/app/utils/logger.py` | 153 | `ClosedStreamSafeHandler`:12, `setup_logger`:51, `get_logger`:119, `debug`:140, `info`:143, `warning`:146 | [coordinator](supporting-services.md) |
| `backend/app/utils/security.py` | 156 | `redact_secrets`:35, `redact_text`:56, `sanitize_env_value`:68, `quote_env_value`:83, `validate_safe_url`:110 | [coordinator](supporting-services.md) |
| `backend/app/utils/zep_paging.py` | 247 | `fetch_all_nodes`:100, `fetch_all_edges`:178 | [coordinator](supporting-services.md) |
| `backend/app/utils/zep_rate_limit.py` | 52 | `is_zep_rate_limit_error`:14, `zep_retry_delay_seconds`:26 | [coordinator](supporting-services.md) |

## graph-actors

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/services/actor_context.py` | 1,601 | `normalize_evidence_gap`:160, `normalize_evidence_gap_map`:241, `canonical_json_sha256`:396, `text_sha256`:407, `is_hard_public_relationship`:415, `actor_id_for`:447 | [graph-actors](graph-actors.md) |
| `backend/app/services/actor_dossier_compactor.py` | 320 | `render_compact_actor_dossier`:151 | [graph-actors](graph-actors.md) |
| `backend/app/services/actor_role_prompt.py` | 2,026 | `sanitize_untrusted_dossier_text`:122, `sanitize_untrusted_research_text`:133, `delimit_untrusted_research_text`:259, `sanitize_untrusted_dossier`:286, `build_actor_role_contract`:937, `compile_actor_role_prompt`:1653 | [graph-actors](graph-actors.md) |
| `backend/app/services/graph_builder.py` | 2,873 | `ActorGraphSeedError`:81, `build_actor_graph_seed_manifest`:510, `safe_attr_name`:616, `fold_priors_with_aliases`:628, `cast_filter_terms_from_actors`:701, `chunk_mentions_cast`:730 | [graph-actors](graph-actors.md) |
| `backend/app/services/graph_pruner.py` | 428 | `core_norm_names`:57, `core_actor_match_stats`:63, `plan_prune`:94, `prune_graph`:244 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/__init__.py` | 33 | Package exports / initialization | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/client.py` | 357 | `Zep`:349 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/compat.py` | 56 | `EpisodeData`:17, `EntityEdgeSourceTarget`:31, `ApiError`:39, `InternalServerError`:51 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/cross_encoder.py` | 26 | `NoOpCrossEncoder`:17 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/embedder.py` | 362 | `get_embed_pool`:61, `LocalSentenceTransformerEmbedder`:205 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/falkor_driver.py` | 99 | `SanitizingFalkorSession`:72, `SanitizingFalkorDriver`:83 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/llm_adapter.py` | 275 | `get_graph_llm_io_pool`:59, `AppGraphitiLLMClient`:100 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/ontology.py` | 47 | `EntityModel`:22, `EdgeModel`:36 | [graph-actors](graph-actors.md) |
| `backend/app/services/graphiti_client/runtime.py` | 2,387 | `GraphitiRuntime`:184, `get_runtime`:2381 | [graph-actors](graph-actors.md) |
| `backend/app/services/ontology_generator.py` | 1,212 | `OntologyGenerator`:473 | [graph-actors](graph-actors.md) |
| `backend/app/services/zep_entity_reader.py` | 613 | `EntityNode`:127, `FilteredEntities`:159, `ZepEntityReader`:175 | [graph-actors](graph-actors.md) |
| `backend/app/services/zep_entity_resolver.py` | 542 | `canonical_norm_set`:59, `actor_alias_map`:65, `plan_merges`:200, `plan_merges_fast`:352, `resolve_entities`:480 | [graph-actors](graph-actors.md) |
| `backend/app/services/zep_graph_memory_updater.py` | 719 | `AgentActivity`:24, `ZepGraphMemoryUpdater`:201, `ZepGraphMemoryManager`:644 | [graph-actors](graph-actors.md) |
| `backend/app/services/zep_tools.py` | 2,854 | `compact_graph_query`:36, `SearchResult`:76, `NodeInfo`:112, `EdgeInfo`:136, `InsightForgeResult`:193, `PanoramaResult`:269 | [graph-actors](graph-actors.md) |
| `backend/app/utils/actors.py` | 3,006 | `normalize_name`:145, `extract_actor_rows`:180, `actor_intelligence_schema_version`:193, `has_unsupported_actor_intelligence_schema`:203, `actor_intelligence_payload`:216, `actor_intelligence_dimension`:236 | [graph-actors](graph-actors.md) |

## operations

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/utils/llm_client.py` | 1,135 | `llm_call_timeout`:74, `LLMClient`:247 | [operations](operations.md) |
| `backend/app/utils/prediction_markets.py` | 884 | `PolymarketClient`:209, `render_markets_block`:580, `derive_market_queries`:699, `derive_market_queries_llm`:749, `score_market_relevance`:810 | [operations](operations.md) |
| `backend/app/utils/telemetry.py` | 594 | `set_run_context`:42, `set_stage`:58, `get_run_context`:62, `active_run_ids`:66, `BudgetExceeded`:86, `estimate_cost`:158 | [operations](operations.md) |
| `backend/app/utils/token_budget.py` | 174 | `estimate_tokens`:39, `truncate_to_tokens`:50, `context_budget`:69, `slice_budget_chars`:77, `clamp_chars`:123, `fit_to_budget`:140 | [operations](operations.md) |
| `backend/scripts/architecture_baseline.py` | 301 | `cmd_capture`:89, `cmd_verify`:196, `cmd_compare`:236, `build_parser`:272, `main`:295 | [operations](operations.md) |
| `backend/scripts/backfill_report_visuals.py` | 792 | `strip_generated_visuals`:87, `drop_irreparable_language_lines`:139, `ensure_baseline_scenario_label`:192, `strip_circular_binary_rows`:224, `synchronize_market_comparison`:277, `localized_manifest`:324 | [operations](operations.md) |
| `backend/scripts/batch_runs.py` | 841 | `BatchManager`:108, `fork_question`:237, `start_batch`:374, `batch_status`:625, `build_parser`:795, `main`:832 | [operations](operations.md) |
| `backend/scripts/check_env_drift.py` | 327 | `config_env_vars`:103, `documented_env_vars`:112, `config_defaults`:119, `parse_env_text`:135, `parse_env_file`:165, `example_values`:173 | [operations](operations.md) |
| `backend/scripts/disk_usage_report.py` | 108 | `dir_size`:27, `human`:41, `top_children`:49, `main`:64 | [operations](operations.md) |
| `backend/scripts/eval_forecast_quality.py` | 439 | `clamp_score`:63, `normalize_judge_scores`:78, `aggregate_scores`:91, `compare_vs_baseline`:111, `objective_signals`:148, `parse_rubric`:176 | [operations](operations.md) |
| `backend/scripts/export_demo_site_data.py` | 1,093 | `export_research_log`:114, `refresh_demo_research_log`:153, `validate_publishable_run`:221, `copy_markdown_assets`:470, `rebase_markdown_assets`:515, `copy_report_assets`:535 | [operations](operations.md) |
| `backend/scripts/forecast_tools.py` | 76 | `cmd_ensemble`:36, `cmd_backtest`:49, `main`:60 | [operations](operations.md) |
| `backend/scripts/golden_eval.py` | 522 | `binary_brier`:84, `binary_log_score`:93, `calibration_bins`:105, `score_pairs`:147, `load_golden_set`:207, `index_golden`:225 | [operations](operations.md) |
| `backend/scripts/model_comparison.py` | 524 | `provider_credentials_ok`:75, `build_comparison`:281, `compare_models`:362, `cmd_compare`:423, `cmd_providers`:472, `main`:482 | [operations](operations.md) |
| `backend/scripts/preflight.py` | 513 | `environment_report`:73, `deep_probes`:195, `main`:461 | [operations](operations.md) |
| `backend/scripts/process_diagnostics.py` | 118 | `main`:64 | [operations](operations.md) |
| `backend/scripts/reclaim_report_space.py` | 192 | `find_backup_dirs`:49, `purge_backups`:71, `extract_inline_bundle`:82, `deinline_charts`:113, `main`:161 | [operations](operations.md) |
| `backend/scripts/replay_zep_dead_letters.py` | 161 | `replay_file`:55, `main`:120 | [operations](operations.md) |
| `backend/scripts/resolution_monitor.py` | 704 | `recent_n_default`:69, `lookback_days`:73, `drift_threshold`:77, `resolve_report_id`:125, `recent_report_ids`:146, `anchored_forecasts`:183 | [operations](operations.md) |
| `backend/scripts/scheduled_rerun.py` | 938 | `scheduler_enabled`:122, `tick_seconds`:126, `max_concurrent`:130, `default_max_runs`:134, `drift_prob_threshold`:138, `drift_webhook_url`:144 | [operations](operations.md) |
| `backend/scripts/test_deerflow_deep_research.py` | 171 | `load_bridge`:15, `FakeProgressLog`:23, `assert_bridge_synced`:31, `assert_skill_synced`:36, `assert_loop_detection_patch`:64, `assert_harness_marker_stripping`:90 | [operations](operations.md) |
| `backend/scripts/test_graphiti_migration.py` | 118 | `build_ontology`:25, `main`:68 | [operations](operations.md) |
| `backend/scripts/test_graphiti_services.py` | 129 | `main`:51 | [operations](operations.md) |
| `backend/scripts/test_pipeline_resume.py` | 302 | `test_mark_failed_status_param`:69, `test_resume_resets_failed_stage`:85, `test_resume_rejects_terminal_and_live`:107, `test_double_resume_race`:130, `test_cancel_orphan_persists_cancelled`:162, `test_delete_and_clean`:175 | [operations](operations.md) |
| `backend/scripts/test_profile_format.py` | 166 | `test_profile_formats`:20, `show_expected_formats`:130 | [operations](operations.md) |
| `backend/scripts/test_zep_rate_limit.py` | 116 | `assert_rate_limit_parser`:21, `assert_zep_tool_retry_uses_retry_after`:32, `assert_graph_snapshot_is_reused`:57 | [operations](operations.md) |
| `drf2/config/market_tools.py` | 248 | `normalize_market`:104, `snapshot_for_queries`:159, `prediction_market_search_impl`:204 | [operations](operations.md) |
| `drf2/driver/__init__.py` | 36 | Package exports / initialization | [operations](operations.md) |
| `drf2/driver/cli.py` | 227 | `main`:159 | [operations](operations.md) |
| `drf2/driver/ensemble.py` | 126 | `aggregate_ensemble`:28, `fan_out`:103 | [operations](operations.md) |
| `drf2/driver/gates.py` | 226 | `GateResult`:36, `research_gate`:74, `hollow_sim_gate`:112, `binary_conviction_gate`:161, `deliverable_gate`:189 | [operations](operations.md) |
| `drf2/driver/harness_client.py` | 295 | `HarnessError`:33, `RunResult`:38, `Harness`:49, `RunsApiHarness`:56, `DryRunHarness`:146, `SimEngineError`:183 | [operations](operations.md) |
| `drf2/driver/legacy.py` | 25 | `ensure_backend_importable`:18 | [operations](operations.md) |
| `drf2/driver/manifest.py` | 141 | `sha256_file`:27, `probe_artifact`:42, `ArtifactManifest`:53 | [operations](operations.md) |
| `drf2/driver/pipeline.py` | 336 | `build_stage_prompt`:72, `PipelineDriver`:87 | [operations](operations.md) |
| `drf2/driver/state.py` | 236 | `utcnow`:37, `IncompatibleStateSchema`:41, `InvalidTransition`:52, `StageRecord`:57, `DriverState`:80, `StateStore`:188 | [operations](operations.md) |
| `drf2/engines/kg/__init__.py` | 9 | Package exports / initialization | [operations](operations.md) |
| `drf2/engines/kg/server.py` | 173 | `build_server`:135, `main`:156 | [operations](operations.md) |
| `drf2/engines/kg/tools.py` | 402 | `set_default_graph_id`:40, `kg_add_episode`:152, `kg_search`:191, `kg_get_entities`:223, `kg_get_edges`:246, `kg_causal_paths`:276 | [operations](operations.md) |
| `drf2/engines/simulation/__init__.py` | 15 | Package exports / initialization | [operations](operations.md) |
| `drf2/engines/simulation/jobs.py` | 430 | `SimulationJobService`:95 | [operations](operations.md) |
| `drf2/engines/simulation/server.py` | 214 | `sim_start`:61, `sim_status`:105, `sim_results`:131, `sim_stop`:153, `sim_interview_agents`:173 | [operations](operations.md) |
| `scripts/salvage_orphaned_pipelines.py` | 231 | `eligible_report`:76, `salvage_state`:104, `find_candidates`:147, `run`:175, `main`:215 | [operations](operations.md) |
| `scripts/watch_pipeline_progress.py` | 187 | `progress_events`:75, `PipelineProgressWatcher`:126, `main`:153 | [operations](operations.md) |

## report

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/api/report.py` | 2,176 | `generate_report`:268, `get_generate_status`:469, `get_report`:544, `get_report_forecast`:586, `get_report_by_simulation`:631, `list_reports`:670 | [report](report.md) |
| `backend/app/services/backtest.py` | 237 | `score_forecast`:41, `calibration_report`:73, `fit_recalibrator`:188, `apply_recalibration`:230 | [report](report.md) |
| `backend/app/services/exec_brief.py` | 927 | `ExecBriefBuilder`:553 | [report](report.md) |
| `backend/app/services/forecast_extractor.py` | 4,201 | `forecast_language_rule`:38, `audit_scenario_contract`:675, `validate_resolution_criteria`:905, `slice_head_tail`:972, `extract_structured_forecast`:999, `allowed_signal_labels`:1177 | [report](report.md) |
| `backend/app/services/forecast_ledger.py` | 436 | `ledger_dir`:23, `evaluation_ledger_dir`:38, `is_production_calibration_row`:49, `append_forecast`:66, `append_golden_result`:113, `read_ledger`:212 | [report](report.md) |
| `backend/app/services/report_agent.py` | 14,478 | `ReportLogger`:92, `ReportConsoleLogger`:393, `ReportStatus`:478, `ReportSection`:488, `ReportOutline`:516, `Report`:539 | [report](report.md) |
| `backend/app/services/report_lint.py` | 1,632 | `strip_citation_residue`:292, `rewrite_edge_dumps`:307, `rewrite_sim_labels`:359, `strip_tool_tokens`:407, `remove_dangling_attributions`:428, `strip_pass_narration`:481 | [report](report.md) |
| `backend/app/services/report_visualizer.py` | 5,411 | `localize_chart_alt_text`:89, `ReportVisualizer`:1768 | [report](report.md) |
| `backend/app/services/resolution_autorun.py` | 117 | `trigger_once`:63, `is_inflight`:83, `start`:88 | [report](report.md) |
| `backend/app/services/translation_dates.py` | 300 | `DateExpression`:124, `interpret_date_match`:144, `render_date`:171, `canonical_date_fact`:190, `find_dates`:205, `mask_dates`:215 | [report](report.md) |
| `backend/app/services/translation_quantities.py` | 309 | `Quantity`:111, `interpret_quantity_match`:134, `render_quantity`:202, `quantity_facts`:230, `find_quantities`:239, `mask_quantities`:249 | [report](report.md) |

## research

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `deerflow_bridge/cached_fetch.py` | 854 | `get_firecrawl_call_counts`:316, `cached_fetch`:692 | [research](research.md) |
| `deerflow_bridge/deerflow_research.py` | 17,986 | `sanitize_untrusted_evidence_document`:214, `delimit_untrusted_evidence_data`:362, `Stage1ModelPrompt`:435, `skill_activation_estimate`:445, `runtime_skill_sync_telemetry`:480, `load_final_dossier_contract`:542 | [research](research.md) |
| `deerflow_bridge/linear_research.py` | 6,379 | `Preset`:648, `scheduled_tool_calls`:689, `resolve_preset`:698, `detect_language`:778, `RunTerminated`:838, `Kiq`:1041 | [research](research.md) |
| `deerflow_bridge/market_tools.py` | 648 | `normalize_market`:170, `snapshot_for_queries`:249, `prediction_market_search_impl`:532 | [research](research.md) |
| `deerflow_bridge/patches/apply_lead_agent_overlays.py` | 138 | `apply`:92 | [research](research.md) |
| `deerflow_bridge/patches/apply_model_factory_overlays.py` | 65 | `apply`:32 | [research](research.md) |
| `deerflow_bridge/patches/apply_subagent_overlays.py` | 410 | `apply`:293 | [research](research.md) |
| `deerflow_bridge/patches/middlewares/loop_detection_middleware.py` | 635 | `LoopDetectionMiddleware`:174 | [research](research.md) |
| `deerflow_bridge/patches/middlewares/model_concurrency_middleware.py` | 76 | `provider_model_lease`:26, `async_provider_model_lease`:36, `async_subagent_lifecycle_lease`:47, `ModelConcurrencyMiddleware`:57 | [research](research.md) |
| `deerflow_bridge/patches/middlewares/summarization_middleware.py` | 513 | `SummarizationEvent`:71, `BeforeSummarizationHook`:82, `DeerFlowSummarizationMiddleware`:145 | [research](research.md) |
| `deerflow_bridge/patches/middlewares/title_middleware.py` | 194 | `TitleMiddlewareState`:23, `TitleMiddleware`:29 | [research](research.md) |
| `deerflow_bridge/patches/middlewares/tool_error_handling_middleware.py` | 257 | `ToolErrorHandlingMiddleware`:59, `build_lead_runtime_middlewares`:198, `build_subagent_runtime_middlewares`:208 | [research](research.md) |
| `deerflow_bridge/patches/models/claude_provider.py` | 514 | `RetryAfterCapExceededError`:94, `ClaudeChatModel`:112 | [research](research.md) |
| `deerflow_bridge/patches/models/credential_loader.py` | 278 | `is_oauth_token`:31, `ClaudeCodeCredential`:37, `CodexCliCredential`:53, `load_claude_code_credential`:201, `load_codex_cli_credential`:257 | [research](research.md) |
| `deerflow_bridge/patches/models/patched_minimax.py` | 239 | `PatchedChatMiniMax`:98 | [research](research.md) |
| `deerflow_bridge/patches/tests/conftest.py` | 23 | Package exports / initialization | [research](research.md) |
| `deerflow_bridge/patches/tests/test_client_usage_overlay.py` | 137 | `test_unpatched_accounting_reproduces_the_undercount`:78, `test_overlay_applies_and_is_idempotent`:88, `test_patched_accounting_adds_grown_same_id_delta`:97, `test_drifted_context_fails_closed`:123, `test_deployed_client_carries_the_overlay`:130 | [research](research.md) |
| `deerflow_bridge/patches/tests/test_lead_agent_trim_none.py` | 191 | `test_factory_forwards_explicit_null_trim`:57, `test_null_summary_model_inherits_active_run_model`:85, `test_explicit_summary_model_overrides_active_run_model`:119, `test_build_middlewares_forwards_runtime_model_to_summary_factory`:153 | [research](research.md) |
| `deerflow_bridge/patches/tests/test_model_factory_metadata.py` | 42 | `test_context_window_metadata_is_not_forwarded_to_provider`:18 | [research](research.md) |
| `deerflow_bridge/patches/tests/test_subagent_runtime_contract.py` | 369 | `FakeSubagentStatus`:27, `real_executor_module`:37, `test_task_inherits_embedded_client_model_from_configurable`:79, `test_provider_fallback_message_marks_subagent_failed`:160, `test_all_evidence_tools_budget_denied_marks_subagent_failed`:205, `test_successful_evidence_survives_later_budget_denial`:269 | [research](research.md) |
| `deerflow_bridge/patches/tests/test_summarization_trim_env.py` | 90 | `test_unset_env_preserves_explicit_null`:36, `test_unset_env_preserves_configured_integer`:43, `test_unset_env_preserves_langchain_default_when_kwarg_omitted`:49, `test_env_integer_overrides_config_null`:58, `test_env_integer_overrides_configured_integer`:64, `test_env_none_sentinels_force_full_segment`:70 | [research](research.md) |
| `deerflow_bridge/research_budget.py` | 1,508 | `Admission`:58, `enabled`:93, `model_leases_enabled`:99, `subagent_leases_enabled`:104, `admit_attempt`:260, `admit_network`:291 | [research](research.md) |
| `deerflow_bridge/research_gateway.py` | 3,812 | `GatewayError`:113, `ProviderUnavailable`:128, `QuotaExhausted`:134, `ContentFiltered`:140, `BadRequest`:146, `ContextTooLong`:152 | [research](research.md) |
| `deerflow_bridge/runtime_skill_sync.py` | 615 | `SkillSyncError`:67, `sync_runtime_skills`:405, `verify_runtime_sync_payload`:533, `main`:589 | [research](research.md) |
| `deerflow_bridge/search_tools.py` | 746 | `get_firecrawl_call_counts`:391, `web_search_impl`:564 | [research](research.md) |
| `deerflow_bridge/skills/forecast-visuals/scripts/render.py` | 2,138 | `prep_network`:615, `prep_timeline`:736, `prep_quant`:789, `prep_trajectories`:1012, `prep_revisions`:1096, `prep_markets`:1183 | [research](research.md) |

## simulation

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/services/agent_dynamics.py` | 405 | `extract_round_signals`:39, `AgentDynamicsTracker`:86, `classify_organic_action`:231, `sample_engagement_likes`:245, `throttle_seed_follows`:310, `detect_organic_ratio_collapse`:335 | [simulation](simulation.md) |
| `backend/app/services/decision_channel.py` | 775 | `elicit_round`:289, `run_decision_channel`:535 | [simulation](simulation.md) |
| `backend/app/services/ensemble.py` | 419 | `align_scenario_buckets`:55, `aggregate_forecasts`:150, `pool_binary_forecasts`:261 | [simulation](simulation.md) |
| `backend/app/services/oasis_profile_generator.py` | 3,264 | `canonical_reddit_system_message`:62, `OasisAgentProfile`:90, `OasisProfileGenerator`:275 | [simulation](simulation.md) |
| `backend/app/services/simulation_config_generator.py` | 4,006 | `get_activity_profile`:182, `AgentActivityConfig`:194, `TimeSimulationConfig`:251, `EventConfig`:281, `PlatformConfig`:301, `SimulationParameters`:326 | [simulation](simulation.md) |
| `backend/app/services/simulation_ipc.py` | 732 | `CommandType`:117, `CommandStatus`:124, `IPCCommand`:133, `IPCResponse`:159, `SimulationIPCClient`:187, `SimulationIPCServer`:547 | [simulation](simulation.md) |
| `backend/app/services/simulation_manager.py` | 1,544 | `build_simulation_config_seal`:52, `validate_simulation_config_seal`:137, `ensure_dossier_actor_entities`:224, `select_agent_pool`:351, `SimulationStatus`:602, `PlatformType`:614 | [simulation](simulation.md) |
| `backend/app/services/simulation_runner.py` | 3,021 | `RunnerStatus`:36, `AgentAction`:49, `RoundSummary`:76, `SimulationRunState`:102, `SimulationRunner`:266 | [simulation](simulation.md) |
| `backend/app/services/world_delta.py` | 80 | `build_world_delta`:21 | [simulation](simulation.md) |
| `backend/app/services/worldstate.py` | 304 | `commitments_from_decisions`:81, `WorldState`:122 | [simulation](simulation.md) |
| `backend/app/utils/oasis_llm.py` | 616 | `get_llm_fallback_stats`:267, `CLIModel`:379, `create_oasis_model`:557, `get_oasis_semaphore`:603 | [simulation](simulation.md) |
| `backend/app/utils/sim_timeline.py` | 570 | `HorizonResult`:57, `RoundPeriod`:66, `SimulationTimeline`:74, `extract_horizon`:266, `default_horizon`:338, `select_calendar_unit`:352 | [simulation](simulation.md) |
| `backend/scripts/action_logger.py` | 323 | `PlatformActionLogger`:22, `SimulationLogManager`:134, `ActionLogger`:216, `get_logger`:313 | [simulation](simulation.md) |
| `backend/scripts/run_parallel_simulation.py` | 6,154 | `MaxTokensWarningFilter`:138, `disable_oasis_logging`:152, `init_logging_for_simulation`:173, `CommandType`:833, `ParallelIPCHandler`:840, `load_config`:1270 | [simulation](simulation.md) |
| `backend/scripts/run_reddit_simulation.py` | 1,108 | `UnicodeFormatter`:53, `MaxTokensWarningFilter`:70, `setup_oasis_logging`:84, `CommandType`:146, `IPCHandler`:153, `get_agent_names_from_config`:416 | [simulation](simulation.md) |
| `backend/scripts/run_twitter_simulation.py` | 1,117 | `UnicodeFormatter`:53, `MaxTokensWarningFilter`:70, `setup_oasis_logging`:84, `CommandType`:146, `IPCHandler`:153, `get_agent_names_from_config`:416 | [simulation](simulation.md) |

## ui-api

| Python file | Lines | Selected top-level entry points | Area report |
|---|---:|---|---|
| `backend/app/__init__.py` | 260 | `create_app`:84 | [ui-api](ui-api.md) |
| `backend/app/api/__init__.py` | 22 | Package exports / initialization | [ui-api](ui-api.md) |
| `backend/app/api/graph.py` | 725 | `allowed_file`:25, `get_project`:36, `list_projects`:55, `delete_project`:70, `reset_project`:89, `generate_ontology`:122 | [ui-api](ui-api.md) |
| `backend/app/api/research.py` | 921 | `run_pipeline`:51, `cancel_pipeline`:133, `resume_pipeline`:148, `continue_pipeline`:185, `fork_scenario`:220, `delete_pipeline`:261 | [ui-api](ui-api.md) |
| `backend/app/api/sdk.py` | 356 | `v1_run`:77, `v1_status`:157, `v1_list`:174, `v1_dossier`:187, `v1_forecast`:239, `v1_resolve`:284 | [ui-api](ui-api.md) |
| `backend/app/api/settings.py` | 186 | `get_llm_settings`:26, `set_llm_settings`:31, `test_llm_settings`:152 | [ui-api](ui-api.md) |
| `backend/app/api/simulation.py` | 2,871 | `optimize_interview_prompt`:27, `get_graph_entities`:48, `get_entity_detail`:93, `get_entities_by_type`:126, `create_simulation`:165, `prepare_simulation`:400 | [ui-api](ui-api.md) |
| `backend/app/config.py` | 1,656 | `Config`:27 | [ui-api](ui-api.md) |
| `backend/app/mcp/__init__.py` | 24 | Package exports / initialization | [ui-api](ui-api.md) |
| `backend/app/mcp/kg_server.py` | 358 | `kg_search`:223, `kg_trace_cascade`:229, `kg_entity_summary`:235, `kg_get_entities`:240, `kg_centrality_priors`:246, `kg_graph_statistics`:251 | [ui-api](ui-api.md) |
| `backend/app/mcp/sim_server.py` | 312 | `build_server`:200, `main`:295 | [ui-api](ui-api.md) |
| `backend/run.py` | 62 | `main`:25 | [ui-api](ui-api.md) |

## Test reference boundary

Backend test files are indexed by path, symbols, imports and hash. Specialists inspect representative behavior tests where useful, but this study does not claim all 76,278 backend-test source lines were read. Bridge patch tests and operational test scripts are included in the scoped table and retain their actual roles.
