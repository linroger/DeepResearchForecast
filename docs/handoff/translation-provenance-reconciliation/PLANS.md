# Scheduled translation/S0 reconciliation

The user authorized this integration for2026-10-23 05:00 Asia/Shanghai. Reconcile published translation main with the explicitly named claude/sim-provenance-s0 branch, resolve conflicts by contract, verify current combined bytes, then commit/push/merge main.

1. Capture current refs, dirty ownership and readiness without modifying either Claude checkout.
2. Integrate committed S0 aad41e90 into main0a23a1c3 on this isolated branch. The full S1–S4 branch is separate and is not silently substituted for the named branch.
3. Preserve readable model-led translations, canonical forecast/evidence values, simulation provenance/diagnostic probability policy, native caption labels and old artifact compatibility. Resolve conflicts with these contracts.
4. Run the unchanged guarded runner over the440-case translation baseline and relevant S0 consumer suites, plus frontend tests/build; add affected cases only if a defect is reproduced. Obtain independent review of resolutions/current receipts.
5. Commit the reviewed merge, push the integration branch, fast-forward main and push legacy/main. Verify exact remote SHA and preserve all peer dirt. No provider calls, saved report regeneration, pipeline resume or service restart.
