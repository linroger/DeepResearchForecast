# Coordinator official-data review

Status: COMPLETE — DOCUMENT FROZEN FOR DELIVERY, 2026-10-12.
No active must-fix finding or follow-up remains for this reviewer. The initial
findings and intermediate holds below describe historical source snapshots;
they are superseded by the correction/closure sections and this delivery notice.

CR-2 through CR-11 and GB-1 have the independent correction evidence recorded
below. Promotion CR-1 was implemented/verified by its separate owner; final
overall acceptance is based on the coordinator's closing confirmation rather
than an invented additional promotion review here. The coordinator reports the
main 2,025-test green and true publication E2E, plus the 43-case fixture-lint
follow-up and attribution of the 169-case actor result, with no production change
from those final fixture edits. Those are coordinator-level results, not extra
runs performed by this reviewer. No further exploration or execution is planned.

Scope: approved PLANS.md and integration-contract.md versus the current main
official-data backend adapter, orchestrator merge/report callers, manual report
callers, simulation snapshot, data-resolution ledger and monitor, plus focused
consumer/downstream tests. No runner/source edits, provider/model requests or
saved-data access. Runner remains frozen at
`53a2cd4105edc92c2241b20974d25cf8f7775858bb294d5dcc9632289007faaa`.

## Historical findings — captured before correction

### CR-1 — P1: research promotion drops the dataset generation

Location: `backend/app/services/pipeline_orchestrator.py:3586` (copy loop),
`:3208` (`_RESEARCH_CONTRACT_FILES`), and `:3391` (fingerprint enumeration).

The new report/simulation/graph consumers load `handoff/data/datasets.json`, but
promotion copies only the fixed root files and `charts/`. A source containing a
valid persisted UNRATE dataset loaded successfully before promotion; after real
`_promote_research_contract`, the destination snapshot was None, the generation
manifest contained no `data/` entries, and `_validate_research_contract` still
returned True. Global synthesis/recovery deletes its source directory after this
promotion, so report callers lose the observations despite preserved charts and
source-ledger rows. An old destination `data/` tree can instead survive outside
the newly validated generation. The non-global merge's write block around
`:11845` likewise persists sources/other artifacts without rebuilding datasets
and citation identities at the merged handoff.

Required correction: include the dataset manifest and exact bound JSON/CSV
generation in promotion, fingerprinting, rollback, stale-file removal and
sanctioned finalization. Ensure the merge publishes canonical dataset identities
and remapped citations, then verify the destination `load_official_data` consumer.
The existing source-union test preserves dictionary metadata only and misses this
disk boundary. Evidence: first probe `promotion` object.

### CR-2 — P1: normal monitor timestamp prevents official resolution

Location: `backend/scripts/resolution_monitor.py:599`, `:650`, `:396`;
delegation at `backend/app/services/official_data.py:77`.

`run_monitor` defaults to `_utcnow_iso()` and computes `as_of_day`, but passes the
full timestamp to the new resolver. The shared helper parses `as_of` with its
date/period-only `_period`. With otherwise identical valid fixtures,
`2026-03-01` resolves True while `2026-03-01T00:00:00+00:00` returns manual with
“Invalid or ambiguous canonical observation metadata.” Thus the actual CLI
default cannot resolve official outcomes, whereas all focused tests inject a
date-only cutoff. Normalize the comparison cutoff at the boundary while retaining
the full timestamp for `resolved_at`. Evidence: first probe `monitor_date` and
`monitor_timestamp` positive/negative pair.

### CR-3 — P1: historical context admits projection and estimate flags

Location: `backend/app/services/official_data.py:146`–`:153`; consumers at
`simulation_config_generator.py:1918` and `pipeline_orchestrator.py:12573`.

The local denylist rejects only exact `projection`, `forecast`, `unknown`, and
`unverified`. It admits flags `P`, `estimate`, `estimated`, and
`forecast; provisional` as “Official historical data.” Every supplied value
4.2 appeared in the probe output. The shared API already treats these strings as
projected/estimated, and its resolution path rejects them. A real projection
encoded with a native flag therefore becomes public historical context in the
unversioned world brief and graph input. The canonical-v1 early-return remains
intact; this finding does not claim a bypass of that return. Use the shared
historical eligibility rules rather than this narrower duplicate policy.
Evidence: first probe `snapshot_*` objects; explicit `projection` resolution
rejection is a passing control in the second probe.

### CR-4 — P1: rerun output contradicts the immutable ledger outcome

Location: `backend/scripts/resolution_monitor.py:649`–`:655`, `:684`–`:692`,
and the `data_records` display/return paths following `:699`.

The skip set contains only market outcomes generated during the current call;
existing official outcomes are never read before refetching. First resolving
4.2 > 4 stores True with Brier 0.09. A repeated call with the same identities and
provider revision 3.8 returns False with Brier 0.49, although append correctly
rejects the duplicate (`newly_recorded_count=0`) and the ledger/data summary still
say True/0.09. `monitor_report.md` is generated from the newly fetched record and
therefore silently replaces the displayed truth while the immutable ledger
retains the original. Reuse the stored outcome on reruns; expose revisions as a
separate review condition rather than an automatic alternate resolution.
Evidence: first probe `replay` object.

### CR-5 — P2: historical cutoff does not establish vintage availability

Location: `backend/app/services/official_data.py:132`–`:135` and `:73`–`:77`;
shared resolver cutoff handling in `deerflow_bridge/data_sources.py`.

At cutoff `2026-02-01`, the snapshot correctly excludes the row retrieved on
March 1. Changing only `retrieved_at` to the empty string causes the same row to
be included, so missing availability metadata fails open despite the helper's
stated unknown-vintage rule. Separately, the backend resolver delegates the
March-retrieved row at the February cutoff and returns resolved True: it checks
the January observation period, not when this vintage was available. A historical
as-of simulation or monitor can therefore use a later release/revision without
proof it existed at the cutoff. Require an established availability/vintage date
for historical admission, or leave the result unavailable/manual when it cannot
be established. A period label alone cannot prove publication time. This is a
backend/shared-helper boundary fix; it may require coordination with the data API
owner. Evidence: second probe `snapshot_unknown_availability`,
`snapshot_known_future_retrieval`, and `backdated_resolution`.

### CR-6 — P2: accepted padded identities bypass ledger deduplication

Location: `backend/app/services/forecast_ledger.py:464`–`:476`, `:481`–`:490`.

The new append function strips IDs to calculate its key, but `entry=dict(record)`
persists their unstripped originals. Its next read reconstructs keys from those
originals without stripping. The exact same accepted record with
`report_id=' report_spaced '` and `forecast_id=' F1 '` appended twice, producing
two rows and two calibration contributions. Persist the normalized identity used
by the key (or reject such input before any write), and normalize existing-key
comparisons consistently. Evidence: second probe `whitespace_identity` reports
both appends True and rows=2. The ordinary unpadded repeat test passes, so this
is an accepted-input identity mismatch rather than a general lock failure.

## Positive controls and source flow checked

| Boundary | Observed result |
|---|---|
| Main and seed report constructors | Both pass the stored `official_data` object through the backend adapter. |
| Manual generate/chat constructors | Both receive `_dossier['official_data']`; dossier lookup test confirms the same stored snapshot. |
| Canonical actor authority | `_build_world_brief` returns the canonical public pack before calling `historical_snapshot`; focused test passes. |
| Data dry run | Zero fake data-client calls and zero created paths; no ledger/report output, status carries `attempted=False`. |
| Exact observed monthly value | January UNRATE 4.2 > 4 with Percent units resolves True at a date-only March cutoff. |
| Units, transform or series mismatch | Each returns manual. |
| Missing exact month | February anchor against January-only observations returns pending. |
| Explicit projection flag | Resolution returns manual. |
| Known later retrieval | Historical snapshot excludes the March-retrieved row at February cutoff. |
| Missing persisted manifest | Backend adapter returns None without fetching a replacement. |
| Standard repeat ledger key | Existing focused test writes one data-resolution row and keeps market resolutions separate. |
| Source-union identity | Distinct dataset snapshot URLs survive source dictionary merging; this does not prove manifest promotion. |

No additional concrete caller-argument defect or canonical-v1 early-return
regression was found. The constructor checks are static; no model/report
generation was executed.

## Evidence and exact probe inputs

Existing suite command (11 passed in 0.85s):

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-coordinator-review-20261012-01 \
  -q backend/tests/test_official_data_consumers.py \
  backend/tests/test_official_data_downstream.py
```

Additional probes used the unchanged runner's `Guard` bootstrap in an isolated
`python -I -S -B` process: verify runner SHA, create a fresh root, instantiate
`Guard`, install `sys.addaudithook(guard.audit)`, register its finalizer, call
`guard.configure()`, then import application modules. They used only synthetic
source/handoff/ledger folders and `SimpleNamespace` fake clients. No source files
were modified or tests added to the repository.

- `/private/tmp/drf-coordinator-review-probes-20261012-01/findings.json` records
  CR-1 through CR-4 and unknown-vintage output. Its `completed.json` records full
  source hashes for all reviewed modules and focused tests.
- `/private/tmp/drf-coordinator-review-controls-20261012-01/inputs.json` retains
  the exact common series, anchor, binary and whitespace-ID record.
- `/private/tmp/drf-coordinator-review-controls-20261012-01/controls.json` records
  the positive controls, CR-5, CR-6 and the zero-write dry run.
- Both probe receipts report `source_drift=[]`, preserved identity variables,
  completed shutdown and only Config/logger/simulation storage redirects. There
  were no network, subprocess, credential, saved-data or external-write attempts.

The common input was exactly:

```json
{
  "series": "fred:UNRATE",
  "title": "Unemployment",
  "units": "Percent",
  "frequency": "M",
  "source_url": "https://fred.stlouisfed.org/series/UNRATE",
  "retrieved_at": "2026-03-01T00:00:00Z",
  "observations": [{"date": "2026-01-01", "value": 4.2, "flag": ""}]
}
```

Anchor: `series=fred:UNRATE`, `observation=2026-01`, `comparator=>`,
`threshold=4`, `units=Percent`, `transform=''`. Binary: `id=F1`,
`probability=0.7`, `resolution_criteria='Reviewed by 2026-03-01'`.
First-probe monitor statement: `January unemployment above four`.

Probe variations, with all other fields unchanged:

1. Snapshot flags were separately `P`, `estimate`, `estimated`, and
   `forecast; provisional`, with cutoff `2026-03-01`.
2. Date/timestamp calls used `report_date` / `report_timestamp`, cutoffs
   `2026-03-01` / `2026-03-01T00:00:00+00:00`, and independent ledger folders.
3. Replay used `report_replay`, the same ledger folder and March date cutoff;
   the second fake response changed only the numeric observation to 3.8.
4. Promotion source wrote `research_report.md` as
   `'# Synthetic reviewed generation\n\n' + 'bounded public observations ' * 45`
   and `meta.json` as `{"producer":"global-synthesis"}`. Real
   `write_dataset_files([Series.from_dict(row)], source,
   citations={'fred:UNRATE':1})` created the dataset before real promotion into a
   new destination. No promotion/validation functions were mocked.
5. Historical availability used cutoff `2026-02-01`; missing-vintage case changed
   only `retrieved_at=''`. The delegated backdated resolution retained the March
   retrieval timestamp.
6. Ledger identity used report/forecast strings with spaces shown in CR-6,
   `series=fred:UNRATE`, `resolved_outcome=True`, `model_p=0.7`, and the same
   observation dictionary. The identical record was appended twice.
7. Positive mismatch controls changed anchor units to `Dollars`, transform to
   `yoy`, series to `fred:GDPC1`, or observation to `2026-02` individually.
   The projection control changed only observation flag to `projection`.
8. Dry run used `report_id='dry'`, date cutoff March 1 and the same binary, a fake
   data client recording calls, empty market client, and `dry_run=True`; before
   and after recursive path inventories were identical.

Snapshot hashes are authoritative in each receipt. Coordinator source files
matched the first probe at the final comparison; `deerflow_bridge/data_sources.py`
changed concurrently afterward, although its inspected resolution logic still
contained the reviewed cutoff behavior. This review is evidence for the recorded
bytes, not sign-off on later fixes. The coordinator acknowledged CR-1 through
CR-4 and is adding regressions before patches; CR-5 and CR-6 were also sent.

## Updates

- 2026-10-12: Opened review; verified bounded ownership and frozen runner SHA.
- 2026-10-12: Existing focused suite passed 11/11; captured four substantive
  producer-consumer failures with real functions and fake inputs; notified lead.
- 2026-10-12: Completed availability/identity checks and passing controls;
  retained exact inputs/results and reported six findings. No source/runner edits.

## Rereview after coordinator corrections — 2026-10-12

Status: requested rereview complete. The original CR-2, CR-3, CR-4 and CR-6
reproductions are fixed, as is the snapshot portion of CR-5. The current shared
resolver also rejects CR-5's original later-vintage example. Four additional
monitor-boundary defects remain below. CR-1 was explicitly assigned to Mill and
was not rerun in this rereview. Original findings above are retained as history.

### Verification and closure

The supplied red JUnit contains 19 tests: 9 failures, 10 passes, no errors/skips.
The supplied green JUnit contains 50 passing tests. Independently rerunning the
same four modules produced **50 passed in 1.67s**:

```sh
backend/.venv/bin/python -I -S -B backend/scripts/main_offline_pytest.py \
  --evidence-dir /private/tmp/drf-coordinator-rereview-suite-20261012-01 \
  -q backend/tests/test_official_data_downstream.py \
  backend/tests/test_resolution_monitor.py \
  backend/tests/test_sim_market_priors.py \
  backend/tests/test_official_data_consumers.py
```

Exact previous probes were repeated with the same common series/anchor inputs,
fresh synthetic ledgers and the unchanged frozen runner's Guard bootstrap.

| Original finding | Rereview observation | Disposition |
|---|---|---|
| CR-2: ISO timestamp rejected | Both original date-only and ISO-midnight cutoffs resolve the same valid row. | Original reproduction closed; precision defect CR-7 is separate. |
| CR-3: unsafe historical flags | `P`, `estimate`, `estimated`, `forecast; provisional` each produce an empty snapshot. The actual-observation control still renders 4.2%. | Closed. |
| CR-4: revised value changes displayed truth | 4.2 then 3.8 returns True/0.09 both times, resolved_count=1, newly_recorded=0 on rerun; total fake fetches=1. | Original normal-ID sequential reproduction closed. |
| CR-5: unknown/later snapshot availability | Empty retrieval metadata and March retrieval at February cutoff both produce an empty snapshot. | Snapshot subfinding closed. |
| CR-5: shared resolver later vintage | Original March-retrieved row at February cutoff now returns manual with availability reason. | Original shared-helper reproduction passes on the API bytes recorded below; no blanket sign-off on the API owner's other changes. |
| CR-6: ledger padded identity duplicates | Exact padded record appends once; second append returns None; persisted IDs are `report_spaced` and `F1`. | Ledger subfinding closed; monitor normalization defect CR-8 is separate. |
| Dry run | Zero data fetches and zero created paths. | Preserved. |
| Canonical-v1 actor early return | Existing focused protection test passes in the 50-test gate. | Preserved. |

### CR-7 — P1: monitor bypasses the shared resolver's exact cutoff

Locations: `backend/scripts/resolution_monitor.py:396` and `:449`–`:453`.

The API owner's new resolver preserves ISO timestamp precision, but the
coordinator slices `as_of` to ten characters before delegating. For an observation
retrieved at `2026-03-01T18:00:00Z` and an explicit cutoff
`2026-03-01T01:00:00Z`, the real shared API correctly returns manual; the real
monitor instead resolves and records the outcome. Its date-only argument turns
the requested instant into the end of the UTC day. The replay path independently
truncates `resolved_at` and cutoff: an outcome recorded at 18:00 is returned as
resolved when the same report is evaluated at 01:00 that day. Neither case
requires network or malformed data.

Preserve the requested instant through first resolution and stored-outcome
admission, using the shared UTC/date semantics consistently. Retain date-only
cutoffs as whole-day requests. Evidence keys: `intraday_direct`,
`intraday_monitor`, `intraday_replay` in the first rereview probe result.

### CR-8 — P2: normalized prior IDs do not match live monitor IDs

Locations: `backend/scripts/resolution_monitor.py:363`–`:364`, `:436`–`:440`,
and the concatenation of prior/new records around `:692`.

Ledger normalization is repaired, but `_recorded_official_outcomes` returns
normalized `F1` in the skip set while `resolve_official_forecasts` compares the
raw binary ID ` F1 `. Running that accepted binary twice refetches on the second
call and concatenates a prior row with a new row. The final postappend mapping
replaces both with the same committed row, leaving `resolved_count=2`, two
returned resolution records, two statuses, and one ledger row for one forecast.
Total fake data calls are 2 instead of 1. Normalize report/forecast/series
identity at the monitor boundary and use the same identity for skip sets,
record/status lookup, counts and output. Evidence: `padded_monitor_replay`.

### CR-9 — P1: postappend winner bypasses contract admission

Location: `backend/scripts/resolution_monitor.py:733`–`:737`.

The new committed-row lookup handles a same-contract competing writer correctly,
but replaces rows solely by forecast ID and series. It does not apply the
contract/cutoff validation used during initial ledger replay. A deterministic
interposed append callback simulates another monitor winning the ledger lock
after this monitor's initial read. The winning row is internally valid:
observation 4.2, threshold 5, outcome False. The current request has threshold 4,
for which the same snapshot resolves True. The monitor returns the winning
threshold-5 row as a resolved answer to the threshold-4 request. The actual
shared resolver confirms both comparisons independently. The sequential prior
check would have classified this contract mismatch as manual.

Reapply complete stored-outcome eligibility after selecting the committed winner,
and rebuild status/count/manual output from that admitted result. A companion
probe with an internally valid same-contract winner (value 3.8, threshold 4,
outcome False, matching snapshot hash) passes and should remain supported.
Evidence: `race_different_threshold` and `race_valid_same_contract` in the
supplemental result. The interposed callback calls the real ledger writer; it
does not mock ledger deduplication or the resolver, and it is not claimed as an
OS-thread concurrency test.

### CR-10 — P1: stored-outcome matching ignores the accepted period alias

Location: `backend/scripts/resolution_monitor.py:431` and `:444`–`:448`.

The monitor and shared validator explicitly accept `period` as an alias for
`observation`, but the new immutable-contract comparison checks only
`observation`. Resolve a January binary using `period='2026-01'`; then change
only that field to `period='2026-02'` and rerun with the same IDs. The monitor
replays January's True result for February without fetching. Direct resolution
of the current anchor against the same snapshot is pending. A second probe
retains `observation='2026-01'` but adds conflicting `period='2026-02'`: the
shared validator returns manual, while stored-outcome replay still returns
resolved. Canonicalize and validate the complete anchor, including both period
fields, before comparing it with recorded truth. Evidence:
`changed_period_alias` and `conflicting_period_alias` in the supplemental result.

### Exact additional inputs and receipts

Rereview artifacts:

- `/private/tmp/drf-coordinator-rereview-probes-20261012-01/inputs.json`
  preserves the original common input, the 18:00 retrieval row and padded record.
- The same directory's `results.json` contains the old-defect closures,
  intraday cases, padded monitor replay and initial postappend checks.
- `/private/tmp/drf-coordinator-rereview-contracts-20261012-01/inputs.json`
  preserves the common input, changed period-only binary and conflicting dual
  period binary. Its `results.json` contains both period failures and the
  internally consistent winning-row comparisons used for CR-9.
- Both probe `completed.json` receipts report no source drift, preserved identity
  and completed shutdown. Events contain only three storage redirects; there
  were no network, subprocess, credential, saved-data or external-write attempts.

Additional variations from the original common input:

1. CR-7 sets only `retrieved_at='2026-03-01T18:00:00Z'`. Fresh monitoring uses
   cutoff `2026-03-01T01:00:00Z`. Replay first records at 18:00, then requests
   01:00 using the same report/forecast/series IDs. The direct-helper control
   receives the exact 01:00 cutoff without truncation.
2. CR-8 changes only binary `id=' F1 '`. Both calls use the same ledger and
   March date cutoff; the second response would be 3.8 instead of 4.2. Actual
   calls=2, returned rows=2, persisted rows=1.
3. CR-9 starts from the real monitor's generated record. Immediately before its
   append, the callback commits a deep copy using the original ledger function.
   For the mismatch case it changes `data_anchor.threshold` to 5 and outcome
   to False; observation and dataset snapshot remain 4.2. For the positive
   same-contract case it changes both observation and snapshot value to 3.8,
   recomputes `dataset_sha256` over sorted compact JSON, and sets outcome False.
   It then calls the original writer for the current record, which loses
   deduplication. No ledger lock or shared resolution function is replaced.
4. CR-10 first replaces the common anchor's `observation` key with
   `period='2026-01'`, records it, and reruns with `period='2026-02'`. The other
   case records the original observation-only anchor and reruns after adding
   conflicting `period='2026-02'`. Both use date cutoff March 1.

Full source hashes are retained in both probe receipts. Key reviewed hashes:

| File | SHA-256 |
|---|---|
| `official_data.py` | `db1572ad7919e09756f24ac9e72e5b7d35ebd5b15d5e54bc955bb2ef3676824d` |
| `forecast_ledger.py` | `72a074e3580164a956b2df7c3a12d4ff0f6a3459ee97e87dc693fc9a61bc6367` |
| `resolution_monitor.py` | `9cf6c4e6b2cca521326d434a4471cfcdd68e2c4664b16b42a162b3c2911b4b88` |
| `data_sources.py` | `8424ded36596d4e1a9a301d3d1b7b2d1f3eaf33e23d9af6ae48dc9920e4fe655` |

The coordinator was notified of all closures and CR-7 through CR-10. No source,
test or runner file was edited. Frozen runner SHA remains unchanged. This
appendix records the reviewed snapshot; it does not certify later fixes.

- 2026-10-12 rereview update: verified supplied red/green receipts, independently
  reran the 50-test gate, repeated original probes and captured four concrete
  additional boundary failures with positive controls. Only this report changed.

## CR-7 through CR-10 closure and CR-11 follow-up — 2026-10-12

The coordinator's supplied replay red receipt contains 8 failures and 21 passes;
the supplied green contains 60 passes. Independent execution of the same four
suites passed **60/60 in 1.81s** at
`/private/tmp/drf-coordinator-final-rereview-suite-20261012-01`.

Real-function probes at
`/private/tmp/drf-coordinator-cr7-10-rereview-probes-20261012-01` close the original
four reproductions. `inputs.json`, `results.json`, `closure-assertions.json` and
`completed.json` preserve exact inputs, outputs, assertions and source hashes.

| Finding/control | Independent observation | Disposition |
|---|---|---|
| CR-7 fresh observation after explicit cutoff | No outcome; manual status and no ledger record. | Closed. |
| CR-7 stored outcome before its recording instant | Pending with zero resolved records; no refetch. | Closed. |
| UTC-offset-equivalent cutoff | Valid outcome admitted at the same actual instant. | Positive control passes. |
| CR-8 padded forecast ID | One normalized F1 result/status, one ledger row and one total fetch across replay. | Closed. |
| CR-9 competing same-contract writer | Its valid revised snapshot/value 3.8 and outcome False are retained. | Positive control passes. |
| CR-9 conflicting threshold / later recorded cutoff | Conflicting contract becomes manual; later cutoff becomes pending. Counts and manual output agree. | Closed. |
| CR-10 changed/conflicting period alias | Both are manual with no replayed outcome and no refetch. | Closed. |
| Equivalent period/observation alias | Replays the original valid outcome. | Positive control passes. |
| Tampered snapshot hash or inconsistent stored outcome | Both rejected as manual without refetch. | New validation controls pass. |
| Current-time dry run | Zero fetches and zero created paths. | Preserved. |

Replay inspection confirms that current and original anchors are normalized by
the shared validator; comparisons use normalized `period`. The stored snapshot
SHA is verified, the outcome is recomputed against its original recorded cutoff,
and the same helper admits the committed winner before display/counts. Monitor
hash for this round was
`40a5fd646779812ea986610ae048fe6f8e764d785e586df0084e3ee4baf03b3f`;
adapter hash was
`eb270f81cc79a64c775a07f5dea719ff076475296f52a1d4587f04ab4032a90d`.
The shared API was
`a0aa7ae237d097de3fb3a9f1294ec14784dd62abd3b6ed6a2c0c85d3179c94ed`.
Full dependent-module hashes and exact time-function hashes are in the receipt
and `api-time-function-hashes.json`. There was no source drift during this run.

### CR-11 — initial default-time failure, now independently closed

The preceding probe exposed one new P1 default-path defect: an omitted `as_of`
was sampled before a fresh fetch, while the provider stamped retrieval afterward.
Default clock 00:00:00 plus retrieval 00:00:01 produced manual/no ledger; a later
invocation at 00:00:02 with that already-cached receipt resolved. An explicit
00:00:00 historical cutoff correctly rejected the later retrieval. This did not
justify weakening explicit cutoff checks.

The coordinator accepted CR-11, captured **1 failure / 1 pass** at
`/private/tmp/drf-main-current-resolution-red-20261012-01`, then **62 passes** at
`/private/tmp/drf-main-current-resolution-green-20261012-01`. The narrow independent
rereview inspected current monitor bytes only and passed **2 tests, 29 deselected**
at `/private/tmp/drf-cr11-independent-focused-20261012-01`.

Independent probes at `/private/tmp/drf-cr11-independent-probes-20261012-01`
confirmed all four cases:

1. With `as_of` omitted, the fake clock starts at `2026-03-01T00:00:00Z` and moves
   to 00:00:01 during `get`, which stamps that retrieval instant. The first
   uncached request resolves and persists `resolved_at=00:00:01`.
2. With the explicit 00:00:00 cutoff and identical fetched data, the result stays
   manual and no ledger path is created.
3. Two current-mode forecasts fetch sequentially at 00:00:01 and 00:00:02. Both
   retain their own post-fetch cutoffs and pass final committed replay. F1 uses
   threshold 4 and is True; F2 uses threshold 5 and is False for value 4.2.
4. Default dry run performs no fetch and creates no paths.

The new implementation passes `as_of=None` only for implicit current mode,
samples the resolution cutoff after each retrieval, stores that cutoff, and
refreshes the implicit run cutoff before committed-row admission. Explicit
cutoffs remain unchanged. **No remaining concrete CR-11 monitor defect was found.**
Final reviewed monitor SHA:
`24fe9d1b20ecfe57c0eeecf9aae279f94e607e97ec72ed75405e96267d0d1e7d`.
The test SHA is
`989263d881d27a0a3cc6440d652e6cc2548e249c71e06f5c177a22598bd37597`;
the shared API hash for the narrow probe was
`a6b51e1ad6195910dbfcb8092e303f4388188a9cad27478101f1c1d44686fa39`.
The API owner changed provider code afterward; closure is bound to these recorded
bytes and the monitor freeze, not a blanket review of subsequent provider work.

## Snapshot normalization-policy rereview — 2026-10-12

The lead separately authorized this narrow adapter review after the transport
advice was prepared. Its three new regressions failed before the patch; the
supplied combined green contains 65 passes. Independent selected acceptance
passed **7/7** at `/private/tmp/drf-snapshot-policy-independent-20261012-01`:
the three policy/malformed-provenance cases, actual historical data with gaps,
the unversioned actual-data world brief, canonical-v1 early-return protection,
and the intraday cutoff check. `explicit-source-hashes.json` captures pre/post
adapter/core/catalog/hub/test/runner hashes with no drift.

The adapter calls the real `Series.from_dict` on every row before eligibility
decisions. It merges normalized fields while preserving manifest fields such as
source_id, rejects constructor validation failures, and excludes
`provenance.resolution_safe=False`. The current canonical status/fiscal rules
therefore also apply to older carriers.

Additional unmocked-core probes at
`/private/tmp/drf-snapshot-policy-carriers-20261012-01` verify:

- FRED actual 4.2% remains present and retains `[S3]`.
- BLS raw P remains preliminary and is omitted from historical-only context.
- Ambiguous FRED P, old WB blank and claimed-observed flags, old SEC Assets,
  old USAspending with a valid keyed FY2025 interval, explicit false fidelity,
  and malformed provenance are omitted.
- All input carriers remain byte-equivalent as JSON values after the calls.

The USAspending control uses interval start `2024-10-01`, end `2025-09-30`,
label FY2025, complete coverage and `fiscal_start_month=10`, following the frozen
contract addendum. Its missingness/status cannot be repaired merely by supplying
complete period metadata. Exact carriers and results are preserved in that
directory's `inputs.json` and `results.json`.

**No concrete defect was found within this requested adapter normalization slice.**
Adapter SHA for the seven-case gate:
`6f22895f3da115db61346387a9576b3b2200fea86255778a77b662f507eda8ac`;
core SHA:
`03ed2d7fdd47fd6887041bf3644f6ba7c2a4ce85b835a3fc28bf1b4e3fb6a91a`;
focused-test SHA:
`159a80a32808cfdb370e4688d7fb8101a8d908b22015ffd5c8cbee8b39f7949a`.
Full hashes for the later carrier probe are in its separate completion receipt.

All independent review probes used the unchanged frozen runner boundary before
application imports, generated fresh synthetic state, preserved identity and
reported only storage redirections. No source/runner/test file was edited, and
no live provider, credential, saved-run or external-write operation occurred.
CR-1 promotion and full provider/transport acceptance remain with their owners.

- 2026-10-12 closure update: independently closed CR-7 through CR-10, reported
  and then narrowly reverified the coordinator's CR-11 fix, and completed the
  separately authorized snapshot-normalization review. Preserved exact source
  hashes and positive/negative controls for each distinct byte generation.

## Simulation generation-binding review — 2026-10-12

Scope: the newly authorized adapter binding helpers, orchestrator main/seed
PREPARE and report lookup changes, and `test_official_data_consumers.py`.
`caller-review.md` findings CR-2/CR-3 define the requested producer-consumer
boundary. Mill's canonical public-denial correction is separate and is not
reviewed here. No application, test, runner or simulation-manager source changed
in this review.

Independent existing acceptance at
`/private/tmp/drf-generation-independent-suite-20261012-01` passed **10/10 in
1.01s**. Its explicit source hashes remained stable: adapter `714d1535...`,
orchestrator `a802b44c...`, consumers `36acfd3c...`, core `419663c3...`. The
coordinator's 46-case receipt used that adapter generation too. The subsequent
adapter change adds `O_NONBLOCK` to the bounded regular-file open; the additional
probe below uses that updated adapter hash and does not retroactively attach it
to the earlier ten-case result.

Verified source/positive behavior:

- Main and extra-seed paths publish a binding before calling PREPARE. The seed
  association is durable and does not replace the parent's primary simulation ID.
- The binding pins report, actors, sources, actor dossier, research seal and
  dataset-manifest bytes, including explicit absence.
- Create-only hard-link publication refuses a conflicting rebind; repeat binding
  of the same generation is idempotent. Read paths use bounded no-follow file and
  directory descriptors; malformed identity/extra fields/symlink bindings fail.
- A valid binding is consulted before mutable pipeline lookup. Changed artifacts
  return unavailable rather than falling back. Unbound legacy lookup retains its
  dossier while omitting unbound official data, as explicitly requested.
- Existing tests exercise replacement **after** seed binding and correctly omit
  G2 afterward. They do not exercise replacement before the seed starts.

### GB-1 — P1: bind the consumed generation, not the disk generation at seed start

Locations in the reviewed orchestrator:
`backend/app/services/pipeline_orchestrator.py:9127`–`:9129` (seed binding),
`:9146`–`:9149` (passed report/actors), and `:9230`–`:9231` (official report pack).
The main path has the same unqualified bind-from-current-directory at `:13145`.
Adapter location: `backend/app/services/official_data.py:88`–`:89`.

`bind_simulation_research` fingerprints whatever is currently on disk. The seed
method still consumes `actors`, `research['sources']`, `report_md` and `graph_id`
passed by the parent; it never verifies those inputs against that newly sampled
generation or requires the parent's original generation to remain valid.

A deterministic real-method probe creates and binds `sim_primary` to G1 with
UNRATE 4.2, then replaces the same handoff with internally valid G2 (UNRATE 8.8
plus G2 report/actor/source bytes) **before** calling `_run_one_seed` with the
original G1 inputs and `graph_G1`. The parent binding correctly becomes invalid,
yet the newly created seed binding is valid for G2. PREPARE receives G1 document
text and actors alongside an official 8.8 carrier; ReportAgent likewise receives
G1 research text plus official 8.8. The unchanged-generation control receives
4.2 at both boundaries. The primary simulation ID stays unchanged in both cases.

This reproduces the remaining generation-substitution problem without corrupt
JSON, a forged dataset hash or a file race. It uses an ordinary generation
replacement before a later seed consumes the parent's already-loaded inputs.
Pin/validate the actually consumed or parent-admitted generation before PREPARE,
and reject or omit enrichment when that generation cannot be established. A
fresh fingerprint of the current mutable handoff cannot establish the ancestry
of already-loaded report/actor/graph inputs. Add this before-binding replacement
case alongside the existing after-binding test.

Evidence:
`/private/tmp/drf-generation-binding-prebind-probe-20261012-01/results.json`.
The probe calls the real `_run_one_seed`, real binding writer/reader, dataset
writer/loader and dossier lookup. Only simulation execution, the LLM-backed
ReportAgent and unrelated orchestration hooks are replaced. The PREPARE stub
records its real arguments and calls the real `load_for_simulation`; no binding
decision is mocked. All directories and records are newly synthetic.

Exact input outline:

1. Create `sim_primary` and `sim_seed` under a new scratch simulation root.
2. Write FRED UNRATE with Percent/M, retrieval `2026-03-01T00:00:00Z`, observation
   `2026-01-01=4.2`, citation S1. Write G1 report/actors/source bytes and bind the
   primary via the real helper. The report is `'# G1 research\n\n' +
   'G1 historical evidence. ' * 30`; actors contain an empty actor list,
   `as_of_date='2026-03-01'` and `situation_brief='G1 briefing'`.
3. For the negative case only, use the real dataset writer to replace the value
   with 8.8, replace report labels with G2, actor briefing with G2 and source title
   with G2. Keep handoff path and pipeline identity unchanged.
4. Call `_run_one_seed(..., graph_id='graph_G1', actors=G1,
   research={'sources':G1_sources}, report_md=G1_report, seed=2, max_rounds=1)`.
   Record PREPARE's document/actors and its lookup result, then ReportAgent's
   research document and official value. Compare with the unchanged positive.

Updated adapter hash:
`63a542e172afb890d26cef5d7bf12c379ea8d84bd52a3c29262ce8513ee96de4`.
Orchestrator hash:
`a802b44c0d6c84038dba4bf732f012d52acda81cfc8314c343d00fa913a8f8b3`.
Consumer-test hash:
`36acfd3c3e9a6ecc20514118727fe524e3adf0af9529e6db29b921c2fb8a6028`.
The completion receipt binds core and imported hub hashes too, with no drift.
The hub was under an announced correction hold; this isolated generation probe
made no hub/provider calls and is not a combined/native gate. Events contain
only storage redirects, no blocked operations or child processes.

- 2026-10-12 generation update: reviewed the three requested paths, independently
  passed ten existing cases, then reproduced GB-1 with an unchanged-generation
  positive control on the post-O_NONBLOCK adapter. Returned the finding to the
  coordinator and preserved the hub final-gate hold.

## GB-1 correction rereview and closure — 2026-10-12

The coordinator captured two failures/two passes before the correction and a
48-pass combined gate afterward. This owner independently ran the complete
current consumer test file: **12 passed in 1.11s** at
`/private/tmp/drf-generation-prebind-independent-20261012-01`. Its six explicit
before/after source hashes match, including adapter, orchestrator, consumers,
API, hub and frozen runner.

Source inspection confirms the corrected seed path reads the parent's durable
binding before creating a simulation. Invalid ancestry raises a generation error
before creation. Valid ancestry supplies the expected generation and the actual
report/source inputs to the create-only bind. A legacy missing parent binding
does not mint a new official-data association. The main full path captures the
consumed generation immediately after final research/actor reception and before
ontology/graph work, then supplies that token at PREPARE. The research-only return
remains outside this capture/binding path.

Independent real-method probes at
`/private/tmp/drf-generation-prebind-closure-probes-20261012-01` confirm:

| Case | Result |
|---|---|
| Valid primary capture token | Bound successfully; lookup status valid. |
| G1 token after a valid G2 replacement | Rejected by expected-generation comparison. |
| Unchanged parent G1 | One seed created; PREPARE and ReportAgent both receive 4.2; seed binding valid. |
| Parent G1 replaced by G2 before seed | Generation error; zero create, PREPARE and ReportAgent calls; no seed binding. |
| Old unbound parent | Seed remains usable with original G1 document, official data None in both consumers, and no new association. |
| Parent simulation ID | Preserved in every case. |

The probe repeats the original G1/G2 fixtures above using the real seed method,
binding capture/read/write and dataset writer/loader. Only unrelated simulation
and model execution is replaced. Exact results are in `results.json`; the
completion receipt reports no source drift, preserved identity, no children and
only storage redirects. No hub/provider request was made.

**GB-1 is closed for this reviewed correction; no additional concrete defect was
found in the requested ancestry/token/legacy boundary.** Main-stage ordering is
source-reviewed; the entire ontology/graph/model pipeline was not executed.

| Reviewed artifact | SHA-256 |
|---|---|
| Adapter | `912cccd6f3700f92368041063ee44aa977524e593c549ac91ddf7eaf33a24541` |
| Orchestrator | `24bb56e40ac3a2e566c70fd0369c3621c048eee067a192abdfdfd12899fdd40d` |
| Consumer tests | `e75100e0211b01e3e068b69a692aa7e6dbf53d9f228fa07be0f6b035c3a25437` |
| API | `419663c3bbd0d1a790212ed229023b6f5b171e9e74adecff16adc4b04f001511` |
| Replacement hub | `0b65ca3e0ef012261faf994b00107c9b0b517a121fc8e583be05bfb6c58934a9` |

- 2026-10-12 GB-1 closure: independently reran twelve consumer tests and original
  prebinding replacement controls, added valid-token and legacy-unbound controls,
  verified current source identity and returned the narrow closure to the lead.

- 2026-10-12 delivery freeze: replaced the stale initial must-fix status with
  current closure, retained all historical findings and source-bound receipts,
  and recorded the coordinator's final acceptance attribution. Documentation only;
  no production, fixture or runtime change and no additional verification run.
