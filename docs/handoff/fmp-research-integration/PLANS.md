# Official FMP research integration

Approved scope (2026-10-27): the user requested a reusable Codex skill and automatic DeepResearchForecast research-phase integration, and selected the official FMP MCP endpoint explicitly. The community server is a studied alternative only.

1. Implement a bounded official MCP client with runtime tool/schema discovery, secret-safe transport and explicit error states. No community server or arbitrary endpoint.
2. Integrate focused discovery/call tools into both v3 and legacy research, including source-ledger persistence, quotas/deadlines, no historical look-ahead, and provider-free replay. Expose financial data and news when configured; instruct research to use these for relevant questions.
3. Package the source-aware skill for the application and install a matching Codex copy. Document period/currency/filing/estimate/news semantics and safe local credential configuration.
4. Verify real research-consumer scenarios with scripted MCP HTTP at the transport boundary, negative controls and independent review. Record exact sources and receipts. A live check depends on a locally configured replacement credential.

Acceptance: discovered official schemas drive calls; financial/news results reach actual agent prompts and cited stored evidence; unknown tools/invalid args/auth/entitlement/rate limits/budgets/missing credentials fail clearly; resumed research uses its saved captures; no FMP content is automatically admitted as official statistical series, outcome evidence, or simulation truth. Primary dirty work and live pipelines remain untouched.
