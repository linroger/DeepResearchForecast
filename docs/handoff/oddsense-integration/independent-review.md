# Independent review: Oddsense source study and proposed plan

**Status:** Ready for user consideration with one narrow sequencing correction below. This is a design review, not implementation approval or acceptance.
**Reviewed:** latest amended plan, both finalized reader reports, study, task handoff, inventory and scoped issue ledger. No reader report remains pending.
**Scope:** only this review file is owned. Application/vendor code was inspected as text; no application or vendor execution, tests, provider API probes, credential access, installs, restarts or Git mutations occurred. Public Kalshi documentation was read without credentials.

## Critical issues

None identified in the reviewed proposal. This does not establish application correctness or live provider compatibility.

## Important issues

1. **[P2] Align slice acceptance with immutable replay before enabling OS-1.** `PLANS.md:25` requires resumed/forked consumers to use their bound generation, and `:48` accepts OS-1 using immutable snapshots. However `_RESEARCH_CONTRACT_FILES`, generation promotion and stage reuse changes are assigned to OS-3 (`:70–76`), after OS-1/OS-2 are individually accepted. Current `pipeline_orchestrator.py:3210–3218` excludes the new filename; a provider-local snapshot/hash alone does not make it survive parent promotion or bind parent reuse. **Small correction:** move the generation/promotion/reuse portion of OS-3 into OS-1 acceptance, leaving report/UI presentation in OS-3; alternatively state that OS-1/OS-2 stay disabled outside controlled acceptance until OS-3 is accepted. Validate acquisition → parent promotion → resume/fork with zero new provider calls and a tamper rejection before enabling the feature. No architecture rewrite is needed.

## Suggestions

- The task `handoff.md` progress ledger and open questions still describe upstream/workflow study as unfinished, despite completed study/report files. Parent should reconcile that continuity record before presenting the approval packet. This is documentation bookkeeping, not a reason to expand implementation scope.
- Retain the separate `issues.md` dispositions for existing Polymarket research-price/status defects. They are source observations requiring later reproduction, not acceptance failures that authorize unrelated repairs now.

## Positive notes and source checks

- **Native Python adaptation is justified.** The proposal extends existing research, source-ledger, market and report owners; it does not install another CLI, forecasting engine, model provider or scheduled owner. The upstream normalizers discard information a wrapper cannot recover from their output. That supports the chosen boundary without claiming a raw-HTTP wrapper is impossible.
- **Tone is not event probability.** Upstream `src/analysis/divergence.rs:36–47` maps `(score + 1) / 2`, then weights an absolute market difference by confidence; `:64–83` calls this over/underpricing without an event-direction/calibration contract. Rejecting that semantics is supported. This review did not independently reproduce or statistically evaluate the scorer.
- **Missing prices and Yes orientation are real source defects.** `src/adapters/polymarket.rs:100–111` takes the first outcome and substitutes zero; `:66–70` loses numeric IDs. `src/adapters/kalshi.rs:63–68` and `src/adapters/metaculus.rs:56–71` also substitute zero; Metaculus stores forecaster count as volume. The plan's explicit unknown values, native identity and venue units address these mechanisms.
- **Kalshi shape mismatch is independently confirmed.** Upstream `src/adapters/kalshi.rs:48–50,205–232` decodes a `markets` list at detail lookup, and `:37–41,63–68` expects legacy numeric cents. Current [official Get Market documentation](https://docs.kalshi.com/api-reference/market/get-market) shows singular `market`, dollar-string prices and fixed-point contract counts. The documented host also differs from upstream's constant; the plan correctly defers host/schema compatibility to a bounded later probe. Documentation is not proof either host currently succeeds.
- **Snippet/fetched separation is materially addressed by the amendment.** `research_gateway.py:2499–2512` initializes `fetched=False`; `:2519–2528` marks stored fetched content. Search projection `:4459–4461` drops arbitrary metadata, and `linear_research.py:7488–7498` currently emits `date=None`. `PLANS.md:40–42` now explicitly requires metadata serialization/projection and pre-QA acquisition/citation work. Preserve fetch ownership and content hashes; merely registering NewsAPI snippets must not set fetched status.
- **No new-provider anchoring is proposed.** `PLANS.md:22–23,54–64,74–76` isolates external records from canonical Polymarket rows and requires provider/capture identities, preventing bare-ID routing into Gamma/CLOB or resolution. The downstream report's A1/A3/A7 scenarios correctly require call-trace and actor-boundary evidence. Current source study alone cannot prove this future isolation works.
- **Amendments close the earlier integration omissions.** `PLANS.md:42` identifies fixed v3 schemas/dispatch, stable run tool sets, legacy worker allowlists and preserved-YAML migration. `:76` names generation contracts, citation remapping and report-generation binding; `:88` requires disjoint implementation ownership. There is no need for a second ledger, refresh owner or broad router rewrite.

## Evidence limits and frozen identities

The upstream inventory was independently rehashed: **36 files, 29 Rust files, 4,051 Rust lines; zero SHA-256 mismatches**. This validates the recorded bytes/counts, not the parent's claim that every line was substantively read. Independent source inspection was targeted to the key upstream adapters/divergence and the destination ledger, finalization, tool dispatch, generation tuple and report sealing seams. Both reader reports declare bounded inspections; their additional anchors were not all independently reread.

The study's source SHA is `a625a81ff84091c12148b9fb5c84893466aea282`; destination baseline is the documented dirty `claude-reflexive-world-state-model @ dcff7684f255be358232fdcf989af30cbc032c43`. Current destination hashes below match both reports where applicable. No tests/builds or live NewsAPI, Reddit, Kalshi or Metaculus access were established; NewsAPI key validity/plan, full historical availability and forecast benefit remain unverified. No application, report publication or deployment completion is claimed.

### Report SHA-256 after final reading

| Report | SHA-256 |
|---|---|
| `STUDY.md` | `94a6ee1573545b117472bab1a579fe8ffa19b923844708e2299d7895b2a6008a` |
| `PLANS.md` | `b3a1a2213b3f5f9225b274e7fc2c989076c40dfa37b397fc81cd3979ec4b0527` |
| `handoff.md` | `bb8e5dc4bdb144f5e310b57586887dda82d8314574f0ba6d23c0160874921b41` |
| `upstream-inventory.json` | `b460e9dc853e46ebe174a26a84363529425050c357a230f639c1f217a3b1b6a4` |
| `research-paths.md` | `ee4487189a1a1b05840baf34e98a7f83a524aa1528400cf56b978a31283e2fe4` |
| `downstream-paths.md` | `536f5dd8a342ac482b883292f4a99efefb2f3a76eeb7d41bafd990e5a2630402` |
| `issues.md` | `c36576f1a33e08fdc0039a5b5ffaf4e9659ead10cd7b61dff14bcb6855b5f4b4` |

### Independently checked source SHA-256

| Source | SHA-256 |
|---|---|
| Upstream `src/analysis/divergence.rs` | `436f9c1638ffd9003540f24892c77395ff9216f220d0d6f25fa2418dbb3a28dd` |
| Upstream `src/adapters/kalshi.rs` | `773e1e86d46632e9fe83d442fc8e9762a104613eb389e390beab4d1bed72c148` |
| Upstream `src/adapters/polymarket.rs` | `ec97cfcd57f4b1191321935753604952d4081503293dd768d2372e679e71c17c` |
| Upstream `src/adapters/metaculus.rs` | `7d5ad87ab8383f9deee54b9834fd363dc061e6673a9764058d9fdf6e6b96b09e` |
| DRF `deerflow_bridge/research_gateway.py` | `831dc381b7eafa5fdf443cce48da805ba4f23639111e047184fd24768d2e3929` |
| DRF `deerflow_bridge/linear_research.py` | `ef1cace336782afc558034873c767438f97e323524c443ba4eecb4948dec824c` |
| DRF `backend/app/services/pipeline_orchestrator.py` | `b8d5129074f033fefe3ab27d71629da3402de2477250e6e574793531ed5ed651` |
| DRF `backend/app/services/report_agent.py` | `48690e0358980d333c637709c8c7f5066721207c1fdcda8788fa88f304f0bdb3` |

**Next step:** parent incorporates the sequencing clarification and reconciles the task handoff, then seeks the user’s explicit plan approval. These review recommendations authorize no application changes.

## Follow-up disposition — 2026-10-18T12:24:33Z

**Current review status:** Ready for explicit user plan approval; the sole P2 design finding is **closed**. This disposition supersedes the original conditional status and sequencing next step above; the original review remains intact as history.

- **Verified correction:** `PLANS.md:50` makes core snapshot generation, `_RESEARCH_CONTRACT_FILES`, promotion/fingerprints and stage-reuse registration OS-1 release prerequisites before acquisition is enabled in ordinary runs. Restart, tamper and changed-cutoff acceptance must demonstrate zero silent refetch. OS-2 extends the same sealed schema/owner.
- **Downstream ordering:** `PLANS.md:78` explicitly extends OS-1's existing generation protection to final report/UI consumers and binds loading to the consumed research generation. Read together with `:25` and `:84`, this satisfies the requested design correction without deferring core replay protection to OS-3.
- **Historical review identity:** the original 61-line review bytes remain an unchanged prefix; their SHA-256 is `b890747e1fb072cb846e81ccd6f5ec06afec5e77f9b00a3ef062bfaab069b4be`. The original report/source hash tables and original P2 text are preserved.
- **Current reviewed plan SHA-256:** `82d6e7d91d609adebf8fd0b3fe4f06ff1f80446e78b5a5a914e3d1d90c3af56f`. The previous reviewed plan SHA-256 remains in the original table above.
- **Evidence boundary:** the full revised 94-line plan was reread and its bytes hashed. This follow-up closes a documentation/design finding only; no application change, runtime acceptance, provider compatibility or user implementation approval is claimed. All original execution and ownership limits remain in force.
