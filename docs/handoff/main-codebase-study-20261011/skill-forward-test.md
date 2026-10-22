# Independent skill forward test

**Date:** 2026-10-11 UTC. **Status:** Complete, bounded static validation.

**Request under test:** “Study DeepResearchForecast end to end, especially Python, using a team. Focus on main, excluding finharness.”

**Verdict:** The Python reference gives a workable, source-aware procedure for this request. Two material instruction defects remain in the parent skill: a redundant intake wait and unconditional repository-specific metadata/synchronization actions. Neither was executed. No material defect was observed in the reference’s coverage or execution distinctions within this limited test. This is an instruction forward test, not completion of the proposed codebase study.

## Source authority and evidence

The supplied [study-contract.json](study-contract.json) selects commit `c20ec60909fa1aa15154bb6fdb3fdb71c421e10e`, source root `/tmp/drf-main-study-c20ec60-20261011/source`, and this output directory. It prohibits application mutations and live provider calls and excludes `feat/finharness` and `feat/finharness-transplants`. Local `HEAD` and `main` both resolved to that commit. Only main’s recent history was inspected; its latest five commits are dated 2026-09-30. No other branch was inspected or checked out.

[initial-status.txt](initial-status.txt) already records a modified `deerflow_bridge/runtime_skill_sync.py`, modified `handoff.md`, deletions, and untracked material. Current status contains additional modifications, including `backend/app/config.py`, `backend/app/services/pipeline_orchestrator.py`, and startup scripts, plus untracked data-MCP files. Successive status observations also differed. Therefore the initial snapshot is historical context, and current checkout bytes cannot silently stand for committed main. The supplied contract resolves the source choice without another user question.

Git tree metadata contains **326 tracked Python paths**. The contract assigns **326 unique Python paths**, all present in that tree, with no omissions or duplicate ownership. Its eight groups contain coordinator 17, graph-actors 20, operations 44, report 11, research 26, simulation 16, test-reference 180, and ui-api 12 paths. These are assignment counts, not read coverage or application/test classification: the research group also contains patch tests. No tracked pathname contains `finharness`; that filename check does not prove absence of every possible semantic integration.

Three source paths were sampled. Complete byte comparisons against `git show <selected-commit>:<path>` established the following; hashing a complete file did not count as reading its complete contents.

| Source path | Directly read frozen ranges | Other inspection | SHA-256 of committed/frozen bytes |
|---|---|---|---|
| `backend/run.py` | 1–62, complete | Live bytes match selected commit | `885007d53a25098e9914de6d589867f4f580737846bc709643faf84840103c14` |
| `backend/app/__init__.py` | 1–260, complete | Live bytes match selected commit | `6ed3da16027f4e7a328946d2b9738e1389d1e1f46af35f7a4849252b4f86387e` |
| `deerflow_bridge/runtime_skill_sync.py` | 1–65 and 500–555 of 615 lines | Live 1–65 read; complete live bytes differ | `f503ea00d3068cb965cf33dbf80f9ee3e44490a377f56304761365c4a559ab9a` |

The bridge sample makes source ambiguity concrete: frozen lines 45–52 list four required skill bundles; live lines 45–54 list six, adding `data-sources` and `data-visuals`. The sampled live hash was `f34554b3581a17dcbb7118e2175136663e52fc09a32a161b2dbe983087fccb10`. A committed-main report must use the frozen list. Separately, frozen app-factory lines 118–145 contain lifecycle calls to reconcile orphans and register cleanup, while `backend/run.py:37–42` invokes the factory and resolution autorun. These are source-visible reasons to avoid invoking the application for familiarization; their transitive effects were not executed or independently proven here.

## Short plan derived from the instructions

1. **Intake:** Preserve the full request: end-to-end behavior, Python emphasis, a team, main, and the finharness exclusion. Pin the supplied commit and label dirty/untracked checkout material outside committed-source findings. Start from the supplied contract and relevant source; consult historical architecture only as a lead. No checkout change or additional intake question is needed here. See [reference lines 3–11](/Users/rogerlin/.agents/skills/source-command-research-codebase/references/python-workflow-study.md:3).
2. **Coverage:** For the actual study, reuse the eight ownership groups, with one authoritative source and disjoint report ownership. Inventory all 326 tracked Python paths with line counts, hashes, classification, owner, and review depth; retain initializers and scripts. Assign explicit ranges for large files and record actual read ranges and inference separately. Cover necessary non-Python launch/UI/configuration seams as well, because “especially Python” still requires the whole workflow. Trace actual callers before deciding whether an alternative engine or runtime is active. The coordinator owns cross-area handoffs rather than rereading every reader’s area. See [reference lines 11–19](/Users/rogerlin/.agents/skills/source-command-research-codebase/references/python-workflow-study.md:11). No further readers were spawned for this independent validation.
3. **Validation and stopping:** Statically connect public entry points through orchestration, research, graph/actors, preparation, simulation, reporting, and final UI/API consumers. At each boundary record producer, payload/artifact, admission rule, consumer, and stopping condition; include applicable recovery, cancellation, subprocess, overlay, MCP/HTTP, and IPC paths. Independently reconcile boundary claims, coverage unions, hashes, and citation/link anchors. Deliver a concise workflow spine linked to area reports and an inventory, qualifying unresolved facts and separating static evidence from execution. Stop when the requested scope is accounted for and connected, rather than after merely producing an inventory. See [reference lines 23–33](/Users/rogerlin/.agents/skills/source-command-research-codebase/references/python-workflow-study.md:23).

## Evaluation

| Criterion | Observed result |
|---|---|
| Preserve the request | The reference maps entry points, control flow, contracts, processes, recovery, and Python implementation while keeping documentation separate from an improvement audit. Its areas accommodate the supplied team split. The contract’s explicit exclusions and the reference’s required exclusion statement support retaining the main/finharness boundary. The parent’s initial intake wait is unnecessary for this already-complete request; see F1. |
| Handle source ambiguity | Strong in reference lines 7–9: select branch/worktree, record commit and local edits, and use committed bytes for dirty files when studying committed behavior. The sampled bridge divergence demonstrates why this rule matters. Parent line 85’s “live codebase findings” must mean code from the selected authority, rather than whichever bytes happen to be in the live checkout. This wording is a caution; no source-selection failure occurred in this validation. |
| Distinguish inventory, reading, execution | Strong in reference lines 11, 15, 19, 25, 27, and 31: parsing/inventory is not reading, truncated reads require completion, receipts do not prove interpretation, runtime copies require separate provenance, and execution evidence must be separate. The table above applies those distinctions rather than claiming 326 files were read. |
| Avoid unnecessary actions | The reference supports a static study without providers, application imports, saved-run mutations, or integration tests. Delegation is conditional on authorization; the realistic study request authorizes a team, while this validation prohibits further subagents. The parent still mandates unrelated metadata/sync actions; see F2. |

## Concrete instruction defects

**F1 — Unconditional pause repeats an already-complete intake.** [Parent lines 27–34](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:27) prescribe asking for a research question and then: “Then wait for the user's research query.” The realistic request already supplies the question, priority, branch, exclusion, and delegation preference. Literal compliance would stall before source selection and repeat intake. The instruction should make this wait conditional on a missing research question. The forward test proceeded with the supplied request under the user’s explicit authorization.

**F2 — Mandatory environment-specific metadata and sync steps have no applicability check or fallback.** [Parent lines 93–95](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:93) require running `hack/spec_metadata.sh` and choosing a `thoughts/shared/research/` destination; [lines 172–174](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:172) require `humanlayer thoughts sync`. [Lines 203–207](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:203) reinforce exact step ordering. The metadata helper is absent from the selected Git tree, frozen source root, and live checkout, and the live checkout has no `thoughts/` directory. The contract already supplies source/output metadata. Thus the metadata step is concretely unavailable, and the prescribed output/sync path adds work outside this request’s destination and this validation’s single-file authorization. Humanlayer installation and actual sync effects were not tested. These steps should be conditional on the repository workflow and authorized destination, with read-only Git metadata as a fallback. No helper execution, directory creation, install, or sync was attempted.

These are defects in the combined skill instructions, not implementation defects in DeepResearchForecast. No skill changes were applied.

## Limits and integrity

Both skill files and the two supplied metadata files were read completely. One combined tool result truncated part of the contract display; the contract was reread separately in full before conclusions. No prior workflow shortlist, prior study conclusions, or rollout conclusions were read. The live root handoff was not read because this independent test restricts evidence and bars prior conclusions; no handoff was created or modified.

Only three source paths were sampled, with the exact reading limits above. All 326 paths were reconciled as metadata; only three frozen files were compared byte-for-byte to Git. This does not validate all mirror hashes, team reporting behavior, full caller chains, recovery correctness, deployment, provider behavior, or remotely reachable permalinks. No repository tests, builds, app imports, installs, provider calls, other-branch operations, synchronization, or further subagents were used. Python usage was limited to standard-library metadata/text/hash inspection. The only file written by this validation is this report. Concurrent checkout changes prevent claiming a globally unchanged repository; committed main remained the authority.

Input SHA-256 receipts:

- `SKILL.md`: `a998e43b17158c6d830b5e99622034c02c187e02938f1efcaf17ca1e621df135`
- `references/python-workflow-study.md`: `c3d3d0dd9580dbdc70a3401ca33b9b262cf7e8c5fb23e8abd295336c961b3807`
- `study-contract.json`: `839e655923842799ab9d4926351fe183113383be8017efc63705d4411b99c350`
- `initial-status.txt`: `f268d90462a70b4d0bd508ab7612551a2598203a2a0d0e6d9166241b5e804bf3`

Final document checks confirmed all four input hashes unchanged, all nine local links and their line anchors valid, and `HEAD` still at the selected commit. These are document/provenance checks, not repository test runs.

**Next-session starting point:** Review F1/F2 before adopting the parent template unchanged. For the full codebase study, resume from the contract’s frozen main and ownership map and collect actual read/boundary receipts; this validation does not establish that the full study has passed.

## Follow-up rereview — 2026-10-11T15:47:20Z

**Verdict:** F1 and F2 are resolved in the revised parent skill. **No material defects observed in the revised instructions for the request under test**, within this static rereview’s limits. This dated verdict supersedes the original open status of F1/F2; the original findings, evidence, and input hashes above remain historical records.

Both current skill files were reread completely. The same realistic request still provides enough information to proceed with a team study of committed main, excluding finharness. No additional intake question, source checkout change, helper execution, or synchronization is required for that request under the supplied contract.

| Item checked | Revised instruction evidence | Follow-up assessment |
|---|---|---|
| F1: intake wait | [Parent lines 29–34](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:29) condition the question and wait on a missing research question; an already-supplied question, scope, or workflow proceeds directly. | Resolved. The realistic request takes the direct path. |
| F2: metadata and destination | [Parent lines 94–105](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:94) condition the helper on its existence and applicability, provide read-only metadata fallback, permit omitted/unknown optional fields, and use the user’s destination or established repository directory. | Resolved. The absent helper and absent thoughts directory no longer prevent the study or require new infrastructure. |
| F2: sync and exact ordering | [Parent line 173](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:173) requires both a configured repository workflow and user authorization for sync, otherwise retaining the local output and prohibiting sync-service setup. Lines 184 and 206 preserve these conditions for follow-ups and ordering. | Resolved. The later instructions do not reinstate unconditional synchronization or helper use. |
| Selected-source wording | [Parent line 85](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:85) prioritizes the selected branch/checkout authority and separately labels different live bytes; line 94 requests selected commit/branch metadata. | Aligned with reference lines 7–9. The previously sampled live/frozen bridge divergence can be documented without mixing authorities. That source sample was not reread in this follow-up. |
| Complete but bounded reads | [Parent lines 39–40](/Users/rogerlin/.agents/skills/source-command-research-codebase/SKILL.md:39) permit bounded chunks; line 202 requires complete reading before dependent delegation using untruncated chunks. | Aligned with reference lines 11, 15, and 19. Complete reading remains required, while inventory/parsing alone still does not count as reading. |

The reference’s inventory/read/inference distinctions, boundary reconciliation, execution restrictions, and stopping condition are unchanged byte-for-byte. The initial intake/coverage/validation plan therefore still applies. Team authorization comes from the realistic study request; it does not authorize further subagents for this restricted rereview, and none were used.

**Minor remaining template inconsistency:** The example body at parent lines 123 and 125–126 still attributes date/commit/branch metadata to “step 4,” while the operative instruction at line 105 correctly says step 5. This is a documentation cross-reference defect, not an unresolved F1/F2 failure or a material obstacle to this request. No correction was applied to the skill.

**Current input SHA-256 receipts:**

- `SKILL.md` — changed: `5bea206817b4ac38e37319861ee96e4a0f4a0c7405cd480882f90820e2af6ade`.
- `references/python-workflow-study.md` — unchanged: `c3d3d0dd9580dbdc70a3401ca33b9b262cf7e8c5fb23e8abd295336c961b3807`.
- `study-contract.json` — unchanged: `839e655923842799ab9d4926351fe183113383be8017efc63705d4411b99c350`.
- `initial-status.txt` — unchanged: `f268d90462a70b4d0bd508ab7612551a2598203a2a0d0e6d9166241b5e804bf3`.

**Preservation and limits:** The pre-append report was 12,166 bytes with SHA-256 `8151f566e862e5f96ab631f9645bc79290b90c434c88fc1dc20eaf6519d72654`; those bytes are retained as the unchanged prefix. Metadata inspection reconfirmed branch `main` and both `HEAD`/`main` at the contract’s selected commit, with the metadata helper and thoughts directory still absent. This follow-up performed only instruction/text checks and read-only metadata inspection. It did not repeat source sampling, execute repository code or tests, import the app, run helpers, use providers, install anything, synchronize, inspect other branches, or delegate. Only this report was appended; the skill and other outputs were not changed. The verdict establishes the corrections’ static instructional behavior, not a completed end-to-end study or runtime proof.
