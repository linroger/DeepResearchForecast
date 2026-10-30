# World Anchor producer map — static inspection

Inspected2026-10-29 on dirty spending worktree, base0d46ccbf. No app imports/tests/network or source changes. This study covers research producers; consumer-map.md covers the model.

| Boundary | Source | Contract consequence |
|---|---|---|
| Engine branch | linear_research.py:5930 | Target-first bypasses phase_finalize; one legacy hook misses it. |
| Legacy extraction | linear_research.py:8353,8414,8682,9095,9116 | sources.json uses positional report citations; quantitative rows lose source_ref during normalization; timeline rows only retain date/event. They are candidates, not complete provenance. |
| KIQ notes | linear_research.py:3043,6743 | Record fields id/question/kind/round/facts/unsourced/conflicts/open_questions/discovered/sources/stats/finished_at. Fact fields kiq/text/sids/tag/verified_numbers, optional verification/missing_numbers. No stable factID/entity/metric/period/span yet. |
| Source ledger | research_gateway.py:2761,2905 | JSON list; integer SIDs local to owning track/v3 directory. Ledger carries full content hash and relative page_path. Target mode adds publication/retrieval/origin/passages. |
| Page reads | research_gateway.py:5381,5583; linear_research.py:5741 | Containment/symlink/hash checks exist and should be reused. |
| Number checks | linear_research.py:2840 | Numeric/page checks support scale/percent checks but union numbers across pages, omit dates and do not prove entity-metric-period entailment. Use passage-local admission, not a VERIFIED-tag shortcut. |
| Official observations | data_sources.py:193,798,1041,1086 | Series JSON retains metadata and per-observation flag; CSV drops flags. Invalid dataset rows can be omitted by the loader, so strict inventory reconciliation must use the stronger generation check at pipeline_orchestrator.py:3617. |
| Snapshot renderer | official_data.py:525,681; data_sources.py:1159 | Bounded text/latest-observation projections are not full evidence inventories; cutoff must be pinned, not extended by current time on replay. |
| Target provenance | target_research.py:521,546 | target checkpoints/findings/mechanism-bindings plus state.targetResearch authenticate prior results. Parent target_evidence.json contains supplemental official/market/news data, not the raw claim/page ledger. |
| Target projections | target_research.py:751 | Same filenames, different schemas: quantitative.json=case.nodes; sources.json=case.sources; timeline.json=[]; forecast_inputs holds typed authority. Dispatch adapters by admitted authority/schema. |
| Case contract | forecast_case.py:204,288,321,454 | Strict top-level schema; source/claim projection does not carry full page hash. Anchor uses separate input/provenance manifest and outer pair seal; no arbitrary top-level fields. |
| Legacy parent seal | pipeline_orchestrator.py:13993,14044,14046 | Research contract/generation completes before ontology; research_only returns first. A post-return sidecar misses research-only mode. |
| Target parent seal | target_pipeline.py:388,395,455,458,460 | Case, supplemental evidence and estimators frozen before ontology. Bind new inputs inside producer before this freeze; never mutate that admitted generation afterward. |
| Gathering closure | linear_research.py:5703 | New official-data admission closes after gathering. W4 must run before closure or create an explicit separately authorized new research generation, not reopen a sealed store. |
| Seal inventory | pipeline_orchestrator.py:3314,3904; official_data.py:107; target_pipeline.py:67 | Existing root/stage manifests do not include all KIQ/page/checkpoint inputs. World Anchor requires a complete explicit input inventory and inclusion of its emitted pack/join/generation receipts. |

The source crosswalk must distinguish track-owned integer SID, report position, URL-derived source_id, target sourceId and official dataset source references. Exact same label never implies same source. Preserve the question's resolution/settlement authority before any numeric binding.
