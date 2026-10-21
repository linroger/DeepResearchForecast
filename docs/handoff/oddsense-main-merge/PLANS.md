# Oddsense merge plan

The user explicitly requested merging the already implemented Oddsense integration into main. This authorizes the merge, necessary conflict reconciliation, scoped verification and push. Preserve the dirty primary checkout and all newer main features. Do not change live services, provider credentials, defaults beyond the approved integration, or run paid models.

1. Start from current main and merge codex/oddsense-integration, preserving both histories.
2. Resolve overlapping research cutoff, documented-risk, publication metadata, forecast feedback, translation UI, README and feature-list changes without dropping either side.
3. Re-run guarded source-provider, research, immutable promotion, report, export, restart and forecast-feedback cases on frozen merged bytes. Run frontend unit/build with existing dependencies; do not install dependencies as a shortcut.
4. Independently review affected producer/consumer boundaries; fix concrete regressions, preserve red receipts, then freeze and rerun affected acceptance.
5. Commit the reviewed merge and evidence, fast-forward main only with an expected-old-ref guard, push without force, verify the remote SHA and a clean integration worktree. Preserve historical prior-branch evidence as historical.
