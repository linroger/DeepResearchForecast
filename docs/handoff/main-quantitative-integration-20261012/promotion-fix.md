# Official data promotion fix

Status: Complete for the bounded promotion fix on 2026-10-12. Final acceptance is 53 passing tests with independent review closure below. This is the continuity record for this fix; other handoffs are not owned.

## Request and acceptance
Preserve current hash-bound official data through research promotion and sanctioned finalization, including local source dataset pages needed for provenance. Seal exact data bytes, reject every corrupt required row, omit unrelated stale generations, remove obsolete target data, and restore a prior valid generation on failure. No provider calls, saved runs, Git operations, vendor or finharness work.

## Plan
1. Reproduce source → promotion → official-data consumer loss with real dataset persistence and the frozen offline runner.
2. Add bounded no-symlink current-generation selection and copying, strict complete-manifest admission, research-seal validation, and transactional data rollback.
3. Exercise positive and negative scenarios, inspect guard receipts, bind source hashes and obtain bounded review.

## Findings and decisions
The existing `_research_contract_entries`, promotion and finalization handle root files and charts only. The shared loader validates rows individually and can return a valid subset; promotion must require every manifest row to survive that validation. Legacy `candidate_sources` publishes `dataset.page` and `dataset.file` under `data/candidates`; its receipt consumer reads exact page/JSON bytes. V3 final source rows publish the current dataset file but do not publish the internal ledger page path. Preserve explicitly referenced legacy candidate artifacts, not the full candidate journal or stale generations.

Frozen runner SHA-256: `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.
Initial Data API SHA-256: `511e152c647a17c71f4972170a52082c8cb5b850d3a3786532ce342fc65aed4e`.
Initial orchestrator SHA-256: `ebcbd00e9ba307dcf01e3d1d96ed7b0a748fe7716b8d78c4c8c5d3fba9165664`.

## Progress and evidence
- Initial code and producer/consumer paths inspected. Red test is next.

## Remaining work
Implement and verify the bounded fix. Parent owns broader integration, API review and publication.

## Updates
- 2026-10-12: Created this record before code changes. Existing root handoff was read and left unchanged.

### Red evidence
`backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-promotion-red-20261012-01 -q backend/tests/test_official_data_promotion.py`

22 failed in 1.46s, all behavioral failures. The primary reproducer validates the promoted research seal but the actual backend `load_official_data(target)` returns `None`. Receipt: `/private/tmp/drf-main-promotion-red-20261012-01/completed.json`; JUnit: `/private/tmp/drf-main-promotion-red-20261012-01/junit.xml`. No blocked operations, child processes or source drift; identity preserved, shutdown complete. Test SHA at red: `d571187229d08924c57088c89d5375cd43e6e1e61ec295b2cee117fbaf0063fd`.

### Implementation decision
Read only manifest-selected JSON/CSV and explicitly referenced source dataset pages/candidate JSON, with pinned directory descriptors, `O_NOFOLLOW`, regular-file checks, 2 MiB per artifact, 48 KB per page, 64 MiB per generation and 200 series. Require the public Data API loader to admit every manifest row. Staging preserves original bytes; sealing revalidates the copied generation. Destination data participates in the existing directory rollback and is removed when absent in the new generation. Preflight failure previously unlinked an untouched prior seal; a transaction-start flag now prevents that loss.

### First implementation checks
The first attempted green run (`...green-20261012-01`) was not acceptance: 17 failures and 5 passes because opening `/` for POSIX descriptor traversal was denied by the frozen runner. Its blocked reads remain recorded. The code now uses Darwin `O_NOFOLLOW_ANY` to pin the source root with kernel-enforced ancestor rejection, then relative descriptor traversal; the runner is unchanged. On other POSIX hosts the explicit component traversal remains.

`...green-20261012-02`: the unchanged original 22 tests passed in 1.96s. Receipt records no blocked attempts, no children, no source drift, identity preserved and complete shutdown. Added focused coverage for byte/count bounds, a successful generation replacement, initial seal-move failure, unsupported page paths and finalization rollback. Read-only review is in progress.

### Expanded acceptance
`...green-20261012-03`: 45 passed in 2.62s (33 focused promotion cases plus 12 unchanged existing finalization tests). No blocked attempts, children or source drift. This state additionally proves oversize manifest/JSON/page, aggregate bytes and >200 rows refuse before target replacement; generation replacement retains only current data; finalization seal failures and the first rollback-manifest rename failure preserve prior bytes.

A subsequent self-review found that a wholly absent source `data/` tree could leave local file/page references in `sources.json`. The selector now refuses such dangling references before promotion, with a dedicated regression; a truly absent dataset remains compatible, and an empty dataset manifest is sealed without copying stale files.

### Independent review and corrections
Reviewer `01a12c0e-5312-7fe2-a07f-39308116b72e` found three concrete gaps in the first implementation: rollback restoration errors deleted the remaining backup; destination symlinks were normalized away; and `os.walk` checked the entry limit after directory enumeration. The fix now retains the rollback directory and reports its path on restoration failure, rejects source/destination root aliases before normalization, pins staged data writes with no-follow descriptors, and consumes `scandir` entries one at a time with an immediate 1,001st-entry refusal. Dedicated tests exercise restoration from the retained backup, direct/ancestor destination aliases, and bounded iterator consumption.

`...green-20261012-04` passed 47 tests in 2.72s before these review corrections. These corrections require a fresh run and rereview.

### Review-fix verification
Command: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-promotion-green-20261012-05 -q backend/tests/test_official_data_promotion.py backend/tests/test_research_contract_finalization.py`.

51 passed in 3.02s: 39 promotion cases and 12 unchanged finalization regressions. Receipt and JUnit are in the command's evidence directory. Exit 0; complete shutdown; identity preserved; no blocked attempts, child processes or source drift. Unlike earlier runs, this run binds the concurrent API owner's newer Data API hash (`8424ded36596d4e1a9a301d3d1b7b2d1f3eaf33e23d9af6ae48dc9920e4fe655`) and backend adapter hash (`db1572ad7919e09756f24ac9e72e5b7d35ebd5b15d5e54bc955bb2ef3676824d`). Neither file was edited by this worker.

| Acceptance requirement | Evidence scenario |
| --- | --- |
| Promoted data reaches real backend consumer | `test_promoted_data_reaches_real_consumer_and_seal`, exact original bytes and data seal hashes |
| Sanctioned finalization/no-op reuse | `test_finalization_preserves_data_bytes_and_noop_generation`, plus 12 pre-existing finalization tests |
| Every required row is validated | Missing JSON/CSV, hash/metadata mismatch, duplicate/bad row and corrupt page cases refuse promotion; prior valid target remains byte-identical |
| Seal refuses corruption and incomplete binding | Missing/tampered/unsealed data, stale extra file and linked data reject validation/finalization |
| Transactional replacement and cleanup | Data install failure, seal write failure, initial seal move failure, finalization failure, no-data source and changed-generation tests |
| Recoverability when rollback itself fails | Retained backup is used to restore the prior exact seal and official-data consumer output |
| No-symlink data IO | Source directory/manifest/JSON/CSV/page links and direct/ancestor destination aliases refused |
| Explicit bounds | Per-file/page/manifest/aggregate/count failures plus immediate 1,001st directory-entry refusal |
| Source-page provenance | Original candidate page/JSON bytes and `sources.json` preserved; unsupported escapes and missing entire data tree refused |

## Scope and evidence limits
Only the requested orchestrator functions/constants and five directly required helpers, the new promotion test module and this note were edited. No Git commands, provider operations, saved-run access or excluded source trees were used. The frozen runner and existing tests were not edited. All successful acceptance is deterministic fixture evidence under a CPython audit boundary, not an OS sandbox or provider validation.

All data reads and staged data writes reject symlink traversal through pinned descriptors. The existing chart/root-file transaction still uses pathname operations. Static source/destination aliases are refused; defending the entire research transaction against malicious concurrent replacement of its root would require a broader redesign outside this ownership. If restoration itself fails, the root is deliberately left unsealed and the exception names the retained recovery directory; repair uses the remaining rollback entries together with already restored root files. Source references outside `data/` are rejected rather than rewritten or refetched.

### Second review delta
The reviewer closed the rollback, ordinary alias, enumeration and missing-data findings, but found a static `link/../target` alias mismatch between `abspath` and later `realpath`. The directory helper now rejects literal parent traversal before any normalization or creation. The new test checks promotion, validation and finalization through this alias and confirms neither the lexical nor the symlink-resolved target changes. A separate two-series test also proves that public-loader partial success (one metadata-corrupt row omitted) is not sufficient to seal a generation.

## Final acceptance state

Command: `backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py --evidence-dir /private/tmp/drf-main-promotion-green-20261012-08 -q backend/tests/test_official_data_promotion.py backend/tests/test_research_contract_finalization.py`.

53 passed in 3.23s: 41 focused cases plus 12 unchanged existing finalization regressions. No failures, errors or skips; exit 0, shutdown complete, identity preserved, no blocked operations, children or source drift. Final sources were independently rehashed against the receipt: all match.

| Bound file | SHA-256 |
| --- | --- |
| `backend/scripts/main_offline_pytest.py` | `53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa` |
| `backend/tests/test_official_data_promotion.py` | `11704ba4a759a277939f1e1c4fdced3998ca34d9ed65889af7428bf4524c92c1` |
| `backend/app/services/pipeline_orchestrator.py` | `4626ae8250ca982ebf6e6af37e62d4587fd087b0d959b10862592979d396b6ac` |
| `deerflow_bridge/data_sources.py` | `8424ded36596d4e1a9a301d3d1b7b2d1f3eaf33e23d9af6ae48dc9920e4fe655` |
| `backend/app/services/official_data.py` | `db1572ad7919e09756f24ac9e72e5b7d35ebd5b15d5e54bc955bb2ef3676824d` |

Owned-definition digest: `1106bfb6db7cd87b256e2335462fda4477acdb462e34deeb35b685c02a20e74e`. To reproduce, parse the orchestrator AST, select the three `_RESEARCH_DATA_*` assignments, five new helpers and four owned existing functions in source order; hash UTF-8 of their `name + newline + exact source segment` strings joined with NUL. Segments include their final newline. This distinguishes later unrelated orchestrator changes from changes to this slice.

### Final review disposition and handoff
Reviewer `01a12c0e-5312-7fe2-a07f-39308116b72e` independently checked the final JUnit and completion receipt, matched the current orchestrator/test hashes, and closed all findings with no remaining blockers inside the bounded ownership. Exact JUnit time is 3.226 seconds. The broader concurrent-root-replacement limitation above remains explicitly outside this fix.

No work remains within this worker's requested scope. The coordinator should consume this note and the final receipt, preserve concurrent owners' edits, and rerun the affected acceptance if the bound Data API or owned definitions subsequently change. No Git action was taken. Historical progress and earlier results above remain as an audit trail; this final disposition supersedes their in-progress states.

Next-session prompt: "Review promotion-fix.md and /private/tmp/drf-main-promotion-green-20261012-08/completed.json. Verify bound hashes or the owned-definition digest before integrating the quantitative-data promotion fix. Keep the shared Data API's validation intact and retain the documented no-provider/no-saved-run boundary. Broader integration and publication belong to the coordinator."

- 2026-10-12: Closed the bounded fix after final acceptance, source rehash and independent rereview; retained all failed-attempt evidence and explicit limits.
