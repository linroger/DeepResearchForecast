# World Anchor specimen owner

Status: Complete. This assignment prepared private evidence only under the approved code/offline World Anchor plan. No application, test, launcher, or other owners' source was edited; no tests, providers, network retrieval, production writes, commits or pushes were executed.

## Request and bounded inputs

Create a new private, content-sealed snapshot of the copied `pipe_9d9b84efcd3d` handoff, supplementing only its ledger-referenced fetched pages from the explicitly named original `handoff/v3/pages` directory when each complete content hash matches. Preserve the historical acceptance snapshot and original run. Retain all ten KIQ JSON objects and their raw schemas, source ledger, relevant actor/time/quantitative/official/forecast-task artifacts, and explicit snippet/missing/hash-mismatch gaps. No target may be inferred from incidental figures.

The expected S107 page SHA-256 is `432d1695e7c86f412348527c2a61ec2d49a3c77101d193df16981716ebbe0146`. The final interpretation must verify its actual passage, period, entity, metric, unit and forecast wording, and preserve the five amounts as same-year revisions rather than observation history.

## Procedure and acceptance

1. Inventory the fixed copied handoff and raw JSON shapes using standard-library file reads with no symlink traversal.
2. Resolve references through the track-owned ledger; copy pages only from the permitted page directory and only after full SHA-256 equality. Record every reference outcome.
3. Capture source-before, copy and source-after hashes, schema/source-mode inventories, private semantic evidence and sanitized coverage/gap receipts.
4. Publish a manifest and seal last in a fresh mode-0700 private root, with read-only private payload files. Reverify the full manifest and frozen spending-source hashes without importing the app or running tests.
5. Provide the exact package path/hash and raw carrier shapes to the coordinator/contract owner. Raw pages and excerpts stay outside Git.

## Progress and decisions

- Approved PLANS.md read; the complete bounded copied-handoff corpus and all valid ledger page references were reconciled.
- Frozen spending hashes were captured before and after the build and match. This owner changed no spending source. The coordinator separately reported AST-identical F401 comments in the launcher test; that is not a specimen-owner edit. The launcher still hashes to 478b2ba636c437c3e707d39453b66ee73bf43e40b84dad09aacb5cf3d2c25612 in the new worktree.
- The input corpus remains untrusted evidence. Unknown availability, missing typed target, snippet-only claims and unsupported cadence remain explicit gaps; the package is not an admitted World Anchor.

## Delivered private package

Use only this final candidate:

`/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-specimen-20261029-055917Z-v3`

- `manifest.json` SHA-256: **9dfa2f0861a6133d174d06fd76d850e3ef4404c0775572721db04f81569c3f27**.
- Package SHA-256 in `seal.json`: **2ce833dadd4edbbaaad6692bfe2258aa2954383ff03193e6d71a47891b35ef39**.
- Package-hash definition: SHA-256 of canonical sorted relative-path-to-file-SHA-256 JSON for every file except `seal.json`, including `manifest.json`. This avoids circular self-hashing.
- Root and directories are mode **0700**; all files are mode **0400**. The exact file set and hashes are sealed. This is content immutability with verification, not protection against an owner deliberately changing filesystem permissions.
- **95 unchanged raw input files**, **1,387,993 raw bytes**, **110 total package files**, including the seal. Every admitted raw file has equal source-before, copied, source-after and final-recheck hashes. All 34 page bytes match their full ledger hashes. No missing or mismatched page was fetched or silently replaced.

The sanitized `coverage.json` is suitable for coordination. Raw material and exact quotations remain inside the private package; they must not be staged in Git.

| Entry point | Purpose |
|---|---|
| `raw/handoff/` | Unchanged bounded handoff artifacts, retaining original relative names. |
| `raw/handoff/v3/kiq/` | Ten original KIQ JSON files and existing Markdown counterparts. |
| `raw/handoff/v3/sources_ledger.json` | Full 201-row track-owned source ledger. |
| `raw/handoff/v3/pages/` | All 34 full-hash-matched retained page captures. |
| `raw_shapes.json`, `source_mode.json` | Actual JSON pointer/type/key inventory through depth five and schema/authority classification; underlying raw files remain complete. |
| `source_page_index.json`, `source_crosswalk.json` | Per-SID references, page outcomes, and explicit report/source/ledger identity joins. |
| `semantic_review.json` | Private exact S107 passages, byte spans, contextual classification and five same-period vintages. |
| `gaps.json`, `coverage.json`, `kiq_inventory.json` | Explicit omissions, source limitations, sanitized counts and raw KIQ flag/degradation inventory. |
| `verification.json`, `historical_manifest_checks.json` | Before/copy/after provenance, bounded read policy, frozen-source preservation and original receipt comparison. |
| `manifest.json`, `seal.json` | Complete file-set identity and integrity seal. |

## Raw carrier shapes for the pure contract owner

The observed source mode is **legacy research v3.0, full, completed**, with no `forecast_authority` declaration in metadata. The name of the historical acceptance directory does not convert this corpus to a target-first case schema.

| Artifact | Observed raw shape |
|---|---|
| Ten KIQs | IDs `K1` through `K7` and `G1F1` through `G1F3`. Each is a dictionary with `id`, `question`, `kind`, `round`, `facts`, `unsourced`, `conflicts`, `open_questions`, `discovered`, `sources`, `stats`, `finished_at`. |
| KIQ facts | **116 rows**. Each uses `kiq`, `text`, `sids: list[int]`, `tag`, and `verified_numbers: bool|null`; some add `missing_numbers`. Raw flag counts are 52 true, 7 false, 57 null. These flags do not authenticate facts. |
| Source ledger | **List of 201 dictionaries**, with integer `sid`; fields include `url`, `canonical`, `title`, `domain`, `tier`, `via`, `fetched`, `content_sha256`, `page_path`, `snippet`, `first_seen_by`, `fetched_at`, `chars`. Page references use `pages/<first-16-hash-characters>.txt`; the entire 64-character hash is required for admission. |
| `quantitative.json` | **List of 52 legacy extracted rows**, not typed case nodes. Fields include `metric`, `value`, `series`, `unit`, `as_of_date`, `period_end`, `geography`, `definition`, `source`, `value_type`, `source_url`, `tier`, `value_num`, `year`, `value_kind`, `region`, `analyst`, and staleness fields. |
| `timeline.json` | **List of 24 dictionaries** using `date`, `event`, `is_stale`, `staleness_days`. A date alone does not prove future scheduling, publication or availability. |
| `actors.json` | Dictionary with `central_question`, `as_of_date`, `situation_brief`, `actors`, `relationships`, `hot_topics`, `key_events`, `quantitative_facts`, `contested_claims`, `forecast_inputs`. It contains 20 actors and 20 relationships. First-party scenario probabilities/inferences are retained privately and are not observed facts or automatically actor-authorized content. |
| `sources.json` | **List of 60 dictionaries** using URL-derived `source_id`, URL/title/tier, `date`, `source_origin`, `reachable`, `content_sha256`, `excerpt`, `supports`, `independent`. These IDs are distinct from track SIDs and report citation numbers. |
| `v3/extract/*.json` | Wrappers with `report_sha256`, `result`, `truncated`. Actors result, facts result (`key_events`, `quantitative_facts`, `contested_claims`), and frame result (`base_rates`, `drivers`, `risks`) remain separate raw schemas. |
| `v3/data/index.json` | `schema_version: 1`, `enabled: true`, `kiqs: {}`. Metadata reports zero stored official series. |
| Typed authority | No `forecast_case.json`, `forecast_task.json`, `forecast_task_v1.json`, standalone `forecast_inputs.json`, official binding, research contract manifest or `data/datasets.json` in the bounded input. Existing narrative/actor forecast inputs do not fill `missing_contract`. |

All 34 fetched ledger rows were copied; **167 rows remain snippet-only**, including **36 of the 70 SIDs explicitly referenced by KIQ facts/source/fetched arrays**. SIDs are qualified by this snapshot and v3 track. For S107 specifically, exact URL plus full content hash links ledger SID 107 to `sources.json` index 1 / `src_a26ba4260de0d6b0`; the report's explicit reference URL identifies **report S2**. The labels S107 and S2 must not be joined by their text alone.

## Contextual S107 finding and limitations

The retained page's forecast wording, named worldwide end-user information-security spending metric, billion-USD unit, and **2026 forecast** table header jointly identify **247.5 as a third-party forecast for 2026 reported through secondary sources**. It is not an observed 2027 value or a settled 2026 actual. The private semantic receipt binds the exact paragraph/table quotes and byte spans to full hash `432d1695e7c86f412348527c2a61ec2d49a3c77101d193df16981716ebbe0146`; the judgment was not made from number occurrence alone.

The five retained values—**239.8, 244.2, 246.2, 248.2, 247.5 billion USD**—are table entries for the **same reference year, 2026**, under successive forecast vintages. They are not five economic periods, usable historical growth observations, or proof of a release cadence. G1F2 fact entries retain `verified_numbers: null` for the relevant secondary reporting. The underlying September 24 publication and October 5 secondary-report dates are source assertions, not independently authenticated primary metadata. Retrieval time does not prove historical availability. The quantitative row's stored September 1 as-of date is not validated by the retained passage and must not be promoted to a publication timestamp.

Other explicit gaps remain:

- No typed target/settlement contract is present; `missing_contract` is blocking and no target was inferred.
- No captured official observations are available in the official index; no live catalog or provider call was attempted.
- S141 is a full-hash-matched **page-not-found response**, retained with a retrieval-error gap.
- S107 and S150 end mid-table. Twenty-two captures are near 12,000 characters; this is a recorded length hint, not proof of complete remote pages. Hash equality establishes the complete retained buffer only.
- K6 has a `content_filter` fallback; K1 and G1F2 record bounded stops. These limitations were preserved.
- Primary forecast documents, historical availability, cadence, elasticities and executable hazard/term assumptions were not invented or authenticated by this packaging step.

## Verification and continuity

The final standalone standard-library recheck verified all 95 raw input files against their current fixed sources, all 34 full page hashes, every exact quotation byte span, all 109 content hashes plus the seal, the exact file set, and every directory/file mode. All seven applicable historical manifest entries match the copied report/dossier/timeline/sources/quantitative/contested/ontology bytes; their embedded absolute paths were never followed. The builder audit records no blocked or admitted network/process operation, app imports or tests. Credential-pattern/path screening found no suspect content in the final copied inputs; no ambient credential files were accessed.

The first candidate failed only its intermediate-directory mode check and is not accepted. The second retained a conservative sensitive-content gap caused by a public Reuters Samsung/SK Hynix URL slug matching an overly broad token regex. The token-boundary check was corrected without relaxing credential-key checks; the final v3 package includes that unchanged, fully hash-matched page. Both earlier candidates remain preserved as superseded artifacts; use only the exact final path/hash above.

The coordinator received the exact package path, both hashes, coverage and raw shapes for Maxwell. Subsequent consumers must open the declared private package, validate its seal, qualify source IDs by snapshot/track, and preserve every explicit gap. This owner has not created a target fixture contract, an admitted `world-anchor/v1` pack, or any application integration.

## Updates

- 2026-10-29: Created before specimen preparation with exact ownership, input boundary, plan and acceptance criteria.
- 2026-10-29: Completed the final v3 private package and independent stdlib hash/mode/span recheck. Relocated final documentation to the new `codex/world-anchor` worktree as directed, leaving frozen spending sources untouched. Raw data, scripts and receipts remain private; no commit or push was made.
- 2026-10-29: Final recheck confirms 95 unchanged raw inputs, 34 full page hashes, 109 sealed content entries plus seal.json, all seven applicable historical manifest matches and empty builder guard events. The final package and raw shapes were relayed for Maxwell; missing_contract and retained-capture limitations remain explicit.
