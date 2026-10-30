# Merged-source verification

The acceptance coverage union contains **4,582 distinct passing backend cases**, with no failing case left without a passing closing result. This combines a pinned composed run with affected closures; it does not claim that the first broad command exited successfully. All independent findings are closed on the recorded final source. Independent review is recorded in the three review documents and the machine-readable [verification record](evidence/verification.json).

| Gate | Observed result | Scope |
|---|---:|---|
| Initial composed, 107 modules | 4,442 passed; 1 failed; 2 skipped; 3 separately exercised cases deselected | 861 pre/post pins match. The scalar producer stopped with `storage_unavailable`; the ledger remained halted. |
| Producer closure | 148 passed | Full binder and metadata modules, child transports and busy-database refusal; all nine actual omitted-control scenarios pass. Spending core is unchanged. |
| Reflexive integration | 709 passed | Twenty complete modules, private/public diagnostics, identity, saved policy, authenticated replay, operative commitments and both-channel leakage controls. |
| Required-key follow-up | 69 passed | Full 61-case commitment module plus eight existing controls. Original 52 cases are byte-identical; nine new cases preserve explicit-null positives and reject omission. |
| Target/FMP integration | 282 passed; 1 separately exercised stdin case skipped | Complete capture set, initial admission, reuse, fork, source provenance and unchanged private denial. |
| Cast/preparation integration | 96 passed | Authentic incompatible cast makes zero task calls; valid cast still extracts/reviews task and seals both authorities. |
| Parent controls | 50 passed | Private FMP environment, parsed grounding and explicit grade/fail fixtures. |
| Fresh-process checks | 4 passed | Budget completion, archived target runtime, and two private specimen checks. |

The two skips not covered by another passing case are optional C5 historical-source/private-snapshot fixtures. They were not provisioned for this merge command and are not counted as passing. The complete current-main/historical off comparison retains the old golden and checks every source-reviewed delta, full state, requests and RNG. The private World Anchor specimen separately verifies all 95 raw files and preserves its missing typed contract rather than inventing a target.

The first scalar failure's low-level exception was intentionally sanitized. A fresh isolated rerun and the full producer closure pass with the same spending core; no timeout, ledger rule or guard was relaxed. Its original failure and stopped ledger are retained. This does not establish general storage reliability under every load.

Frontend verification passed **390 tests across 30 modules** and the production build. The one temporary dev-server listener scenario is excluded; its three static configuration tests pass. The build reports a 530.22 kB main-chunk warning. Parent frontend paths and the automatic three-way test merge are preserved; primary dependencies were copied without shared inodes or writes to primary.

Static checks parse all 216 production Python modules, pass `bash -n setup.sh` and scoped whitespace validation, and show no introduced Ruff `F,E9` findings across 165 changed/new Python files. Two findings inherited from main remain: an unused local in the unchanged translation method and an unused test import. Parent-source comparison is preserved privately.

The final 866 source/fixture pins are in [source-hashes.json](evidence/source-hashes.json). Every relevant gate records exact source scope, shutdown and identity. The 709-case snapshot changed only in the declared required-key source/test pair; the 69-case closure covers those final bytes. Reviews retain previous snapshots as history and identify their final accepted hashes.

Raw guard data, original reds, copied source and per-file copy manifests are private under `/Users/rogerlin/.local/share/DeepResearchForecast/evaluations/world-anchor-main-merge-20261030/`. The [archive index](evidence/archive-index.json) records verified copies. Public evidence contains compact gate summaries, compressed JUnit and case IDs; private source corpus and provider envelopes remain outside Git.

Guards use CPython audit hooks, not an OS sandbox. The initial composed parent recorded one denied socket construction, five denied process launches, twenty denied external reads and 52 explicitly registered children. Closing gates retain their own exact event counts. These are offline checks with mocked provider transports, not provider or deployment qualification. The primary checkout, its HEAD/index/staged changes and running services are preserved.
