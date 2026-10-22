# Independent review — translation and S0 reconciliation

**Reviewed at (UTC):** 2026-10-22T21:10:00.932002+00:00
**Source verdict:** ACCEPT. No actionable source-contract or semantic auto-merge finding was identified in the bounded review.
**Gate verdict:** ACCEPT; the frozen combined test results and source bindings are verified, and denied-process attribution is closed by the lightweight diagnostic appendix below. All three denied attempts remain recorded: two font discovery commands and one Choreographer browser-helper launch attempt rejected before launch. The original unprofiled 694-case run remains the acceptance receipt; attempted activity is not reported as zero.

## Scope and frozen candidate

The candidate is the pending merge on `codex/translation-sim-provenance-20261023` of translation main `0a23a1c3ba08bf21ed9dfa2b0d1b101a3942d392` and named S0 `aad41e905895cb2f234ece67f579fc1c6f69a4be`, with common ancestor `589d5d92adad404d18a0e306ee47b1e73e7b7946`. Both parent diffs and the actual combined producers/readers were inspected. This review owns only this file and private notes; no application, test, Git, provider, service, peer checkout, or agent mutation was performed. No tests or application imports were run by this reviewer.

The distinct `claude/sim-provenance-impl` branch is outside this review and was not substituted for S0. Full S1–S4 functionality, ADR promotion, paid live acceptance and the separately documented outline limitation are not requirements of this named-branch merge.

## Findings and merge-resolution assessment

There are no confirmed P0–P3 findings requiring a source change. This is a bounded acceptance of the named integration, not a review of the entire application.

Only `.env.example`, `backend/app/services/report_agent.py` and root `handoff.md` were changed by both parents since their common ancestor. The root textual conflict preserves both translation/provenance pointers and explicitly identifies this S0-only reconciliation. The environment auto-merge preserves main's translation settings and applies S0's default-off `FORECAST_SIM_SENSITIVITY` comment.

All 18 translation-only production paths are byte-identical to main. All eight S0-only production paths are byte-identical to incoming S0: config, executive brief, forecast extractor, report lint, visualizer, provenance constants, record-shape contract and frontend viz-manifest helper. Within the overlapping ReportAgent, all 65 translation/localization/forecast-text methods have identical ASTs to main. All 11 methods whose AST differs from main match incoming S0. Class constants, prompt changes and the remaining actual diff were also inspected; the automatic merge has not spliced an old translator into the new execution path.

## Producer/consumer contract review

| Contract | Actual combined source and consumer | Assessment |
|---|---|---|
| Raw model-led translation remains the default | `translation_tools.py:329` delegates readable pairs to `model_translation.translate_entries`; `report_agent.py:10429` calls `translate_document` and passes its proof to the isolated publication audit at `10488`. `model_translation.py:261` sends whole readable entries, followed by a separate review call at `281`. | No numeric masking, legacy recursive prose-slot repair, or post-review lint rewriting was restored into the active translation path. S0 leakage repair remains in primary report generation. |
| Canonical typed forecast facts remain sealed | `_localize_forecast` at `report_agent.py:9910` deep-copies the sealed forecast and changes the enumerated display fields plus joined display names. `_localized_forecast_payload_valid` at `15440` reconstructs the permitted projection and compares the complete remaining payload with `allow_nan=False`; `load_localized_forecast` at `15489` requires the source fingerprint and validates receipts. | IDs, probabilities and other non-display typed facts are preserved; forged localization metadata does not bypass the reader contract. |
| Reviewed bytes are the published/read bytes | `model_translation.py:199` binds source/target/language/context/structure and positive review; `343` revalidates document chunks, complete proof and reconstructed target. Report audit at `report_agent.py:8760` and publication reader at `16129`, research reader at `api/research.py:571`, and artifact cache `_entry_valid` at `artifact_translation.py:301` use those contracts without provider acquisition on reads. | Source, target or context drift invalidates the result. Legacy artifacts retain their separate compatibility path; the new engine is not silently downgraded. Receipts remain integrity records, not cryptographic attestations or infallible semantic proof. |
| S0 diagnostic probability policy survives | `config.py` and all extractor defaults set sensitivity false. `forecast_extractor.py:4481` admits signal-pack sensitivity only under `legacy_prompt`; `report_agent.py:2643` retains pinned report/world/backtest policy resolution. | Translation does not reopen simulation-driven production probability extraction. This does not assert S3 byte-level isolation for S0. |
| Leakage removal and honest attribution survive | `report_lint.py:393` counts legacy labels; `1380` removes remaining leaking sentences/cells instead of relabelling them as evidence. ReportAgent imports the lint locally in Tier-2, applies deletion/citation and number-retention guards, uses `_sp.SIM_QUOTE_LABELS`, and blocks residual legacy labels in its final audit. | The S0 containment behavior and review fixes are preserved alongside the new translator. Canonical honest labels are intentionally retained under the S0 scope. |
| Caption labels reach the translated UI | `sim_provenance.py:67` defines the simulated placement/title constants; visualizer builders and fallback manifest rows use them. `vizManifest.js:136` maps the two new English simulated captions to Mandarin; `ForecastReport.vue:1073` applies the mapping in the language-specific gallery while retaining provenance attribution. | Native EN/ZH captions retain simulation status; the ordinary scenario probability chart remains distinct. |
| Rendered outcome header and extractor agree | `report_agent.py:4286` renders `_sp.OUTCOME_SHARES_HEADER_ZH`; both extractor taxonomy and world-share parser call `_sp.outcome_shares_header_re()`, which also accepts the legacy fixture wording. | No producer/consumer header drift was introduced by the merge. |
| Brief discloses the run's pinned policy | `exec_brief.py:405` resolves run ID through telemetry and reads `options.safety_policy_v1.simulation_forecast_effect`; `_build_honesty_note` uses `_sp.brief_sim_role`. `_find_scenario_chart` handles list/schema-v2 manifests and excludes simulated IDs/hints/titles. | The brief does not invent a diagnostic policy when the pin is missing, and simulated charts are not selected as its evidence chart. |

## Independently inspected fresh verification

The parent's combined gate is `/private/tmp/drf-model-led-xaklp43s/`. `command.json` names 37 suite files. `junit.xml` contains 694 cases across 37 test classes with zero failures, errors or skips; `pytest.log` records **694 passed, one warning, 43.69s**. The named source-contract cases include raw readable translation/rejection/receipt binding, actual report and research readers, visible simulation cache/restart/tamper checks, localized typed facts, S0 lint removal, label survival, caption titles, header alignment, and pinned executive-brief policy.

I independently rehashed every one of the **753** entries in `source-hashes.json` against both the tested mirror and this candidate: zero missing files and zero mismatches. The 41 parent receipt source hashes and 15 source-hash entries across six child receipts also match their files. The parent and all six children report completed/exit 0, `shutdown_complete=true`, preserved identity and empty source drift. The guarded runner is byte-identical to main; no guard change is used as acceptance evidence.

The fresh frontend log `/private/tmp/drf-s0-translation-frontend-tests.log` records **318/318**, zero failures/skips/cancellations. `/private/tmp/drf-s0-translation-frontend-build.log` ends with **built in 1.74s**. These logs are hashed below. The frontend sources/tests in the 753-entry manifest match current bytes, although these frontend logs do not themselves carry the backend guard's per-process source receipt. Historical 440/318 acceptance was not reused as combined-tree evidence.

## Limits and original evidence accounting (historical; attribution now closed)

The backend warning is U+2212 MINUS SIGN missing from Hiragino Sans GB during `test_cjk_labels_are_preserved_or_explicitly_degraded`; this merge changes no font configuration. This is recorded as a rendering limitation, not a warning-free result or a reason to expand into font work.

The combined parent receipt records three `blocked:process:subprocess.Popen` events, 18 blocked external reads, contained `fc-list=1`, `system_profiler=1`, and `font_directory_scan=18`. At the initial freeze, two process attempts were named font probes and the third was not yet attributed. All remained denied. That initial unknown is now resolved by the lightweight diagnostic appendix below; the original event count is preserved. The parent's follow-up diagnostic is separate from the 694-case acceptance receipt and does not replace it. At this review point its unchanged-source 254-case S0 run passes with the same glyph warning, but its stack file is empty, so it does not yet close the unattributed event. No zero-attempt or stronger OS-sandbox claim is made here. The guard explicitly describes its boundary as CPython audit hooks.

## Frozen receipt bindings

| Artifact | SHA-256 |
|---|---|
| Combined source manifest | `d1b532789251015c770a83da93f43ab2b5d9c36689192af9a4dcbf29afe9f655` |
| Backend completed receipt | `186e0d2c556fead7b9da1bc7f14bbf9c05f8910ea730f1040030c854b5e3d195` |
| Backend JUnit | `674766eac3fb3fdc60ed8523be3a23c4cb94f2fd52d534dd2199d643eeee706c` |
| Frontend tests log | `c7a39a954d6c2e752cb0ea9c49ada1a29ce53be304651493e4940a47e7046e6f` |
| Frontend build log | `7b18f9a5063662657edcc416cf84dd42596ccf14a8273489ea3ac0b8b4285678` |
| Combined ReportAgent | `5b992bf23e39d683a6ac8e0e266d6db3330e7de9f4ab310ca1dc567c474f5d0e` |
| `.env.example` (outside code manifest; reviewed separately) | `e999c8a7bbf4bf97b5274780a454447543ab542a0980697a89eba90ce1f87be1` |
| Root pointer resolution (outside code manifest; reviewed separately) | `854456c65dae10dfdc7aec23ca458f71765a7cd576fb2a5c3b1b6f89ef0a63b8` |

Private notes `/private/tmp/drf-independent-s0-review-xr60fpux/` retain the initial parent/source snapshot, both parent diffs, AST/path inheritance evidence and gate rehash receipt. This acceptance is bound to the 753 code hashes plus the separately recorded environment/pointer bytes; application changes after this freeze require affected review and verification. Parent-owned commit/push/main delivery is not claimed by this review.

## Diagnostic accounting update — 2026-10-22T21:12:46.446058+00:00

The owner reports that a native S0-only 254-case run passes with exactly two font probes. This narrower run does not account for or erase the third denied subprocess attempt in the original full 694-case receipt.

A separate full 694-case diagnostic with all-call profiling produced 693 passes and one failure in the timeout-sensitive 1,000-item inventory deadline case. The owner reports no application, source or assertion change and attributes the failure to instrumentation overhead. This is retained as a diagnostic-run failure; it is not evidence of a production regression and does not replace the original unprofiled 694/694 acceptance result. Global profiling also misses worker threads, so it did not settle the outstanding attribution.

A lighter private observer is now reported running at `/private/tmp/drf-s0-guard-attribution-y_w40rs4/evidence-light-observer`. It attaches to the original `guard.deny`, records the call stack, always calls the original denial, and disables profiling; the owner reports no guard-file or enforcement-semantic weakening. Its outcome is pending. These observer implementation details are owner-reported at this update, not independently certified by this source reviewer. The original third denied attempt remains explicitly **unattributed**, and no zero-CLI/socket assertion is made.

The source-contract ACCEPT verdict remains unchanged. This appendix updates diagnostic history only; it changes no application/test/Git state and does not relabel the profiled diagnostic failure as a passing run.

## Attribution closed — 2026-10-22T21:15:15.688490+00:00

**Final bounded verdict: ACCEPT / review ready.** No material source-contract finding remains, and the original third denied process attempt is now attributed rather than dropped. This update supersedes the earlier timestamped pending/unattributed statements above while retaining their diagnostic history.

I inspected `/private/tmp/drf-s0-guard-attribution-y_w40rs4/evidence-light-observer/completed.json`, its JUnit result, the light-observer log and `/private/tmp/drf-s0-guard-attribution-y_w40rs4/light-observer-stacks.jsonl`. The diagnostic completed with exit 0, **694 passed, one unchanged glyph warning, 43.83s**; its parent and six child receipts report completed/exit 0, clean shutdown, preserved identity and no source drift. Its 41 parent source hashes match their files. The original 694-case acceptance artifacts remain unchanged. A final rehash also confirms all 753 source entries still match both the candidate and tested mirror.

Exactly three stack records have `event=observed_guard_denial`. Records 1 and 2 trace through Matplotlib `font_manager.py` fontconfig/macOS discovery into `GuardedPopen._guarded_init:455`, matching `fc-list` and `system_profiler`. Record 9, the **third observed denial**, traces `_manual_thread_pool.py:66` (`_worker`) → `choreographer/browser_async.py:148` (`run`) → `main_offline_pytest.py:442` → `_guarded_init:465`. The guard branch at 465 rejects a script absent from `allowed_scripts`; `deny` records the blocked attempt and raises `GuardViolation`. The actual superclass process launch is later at 491 and is not reached for that rejection. This is an **attempted unregistered browser-helper script launch, denied before launch**, not an unattributed event or a zero-process-attempt run. No browser helper was authorized or allowed by this diagnostic.

I also read the private `/private/tmp/drf-merge-attribution.py`: the observer captures the original bound `guard.deny`, logs a stack for the process-denial category, unconditionally delegates to `original_deny`, and disables `sys.setprofile` immediately after attachment. It adds observational instrumentation without changing the guard file, allowed-script scope, application source or assertions. Its separate audit hook records subprocess call stacks; allowed test children must not be confused with the three denied attempts.

The observer receipt has 35 blocked external reads, whereas the original acceptance receipt has 18. Its contained font-directory probe count remains 18; these are separate diagnostic and acceptance counters and are not merged or relabelled as zero. The CPython-audit-hook boundary remains explicit.

The heavy all-call-profile diagnostic remains **693 passed / one 1,000-item deadline failure**, consistent with instrumentation overhead in the deadline-sensitive case and not a demonstrated production defect. It neither replaces nor invalidates the original unprofiled 694/694 gate. The lightweight diagnostic supplies attribution only; the original receipt remains the acceptance authority.

| Additional diagnostic artifact | SHA-256 |
|---|---|
| Light observer completed receipt | `833eeb811187a264ed3f9c1fbd21a7e2e755d3f0b65124b078261c47a8ea2610` |
| Light observer JUnit | `6b711458c2b5b294118cfd71998bef1c7f107a776090064e6d9d6eb176b2ad78` |
| Denial stacks | `b2aff749cd2d4e2d42848380b9ceb7183a48fc9e012d01de083535b92f81575e` |
| Light observer log | `073006cde63c6eb0aaae36bcf6ee516b08668dd370a4b582d322ef4018741933` |
| Private observer bootstrap | `43536027c0364373ef98d93705d5e0d71a8c11923f411236ea1acaea464f608c` |

Only this review document and private notes were updated. No new application/code task, provider operation, test run, Git mutation, service action, implementation-branch import or shared-Claude-checkout operation was performed by the reviewer.
