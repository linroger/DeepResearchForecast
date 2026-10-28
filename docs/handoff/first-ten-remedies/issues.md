# Reconciliation issues

The earlier delivery has broad offline evidence but missed these actual consumer boundaries. All findings are being repaired within this branch; no live-provider or statistical success is implied.

| ID | Priority | Issue | Owner | Status |
|---|---|---|---|---|
| HTTP-REUSE | P2 | HTTP resume/continue/fork unnecessarily require completed research prerequisites | Coordinator | Initial3red→green;14HTTP controls pass including interrupted-fork recovery and parent tamper rejection |
| RPT1 | P1 | Critique changes probabilities without updating prior/posterior ledger | Reporting | Closed: final5306-casegate and independent review |
| RPT2 | P2 | Stored estimator lanes have no report table consumer | Coordinator | Closed: final5306-casegate and independent review |
| G3-EXACT | P1 | Market ID is treated as proof of identical settlement | Reporting | Closed: final5306-casegate and independent review |
| G1-STATUS | P2 | Disabled/successfully empty collector states become unknown | Feedback | Closed: final5306-casegate and independent review |
| G1-PROBE | P2 | Diagnostic probe uses a different HTTP transport than research collector | Feedback | Closed: final5306-casegate and independent review |
| MR1 | P1 | Dimensional/seed checks do not protect normal target model admission | Mechanisms | Closed: final5306-casegate and independent review |
| MR2 | P2 | Settlement scenarios can classify unrelated driver nodes | Mechanisms | Closed: final5306-casegate and independent review |

Existing issue10, https://github.com/linroger/DeepResearchForecast/issues/10, was fetched and confirmed open on2026-10-28. It remains the single tracker for live transport/provider confirmation, production monitor activation, historical episode validation and prospective scoring. Do not duplicate it or present source configuration as runtime activation.

## Independent review corrections

- **HTTP-FORK-RECOVERY (P2):** A fork interrupted before child research resealing was wrongly treated as fresh research. Parent snapshot and child binding are now verified read-only before skipping research prerequisites;14HTTP cases and independent closure pass.
- **MODEL-RECEIPT (P2):** Unknown/malformed validation policies could hide diagnostics. Present receipts now equal their recognized-policy recomputation or the exact policy-free legacy diagnostic. Actual ReportAgent unknown-policy publication is rejected; unsupported/unmeasured receipts remain visible.
- **ZERO-BUDGET (P2):** Admission accepted zero decision requests but the report rejected the resulting budget receipt. The report now accepts this admitted zero-call hold behavior, with a full-pipeline regression.
- **G1-MIXED-FAILURE (P2):** A successful empty query combined with a transport failure looked empty. The explicit failure now takes precedence as offline; the real collector-to-health regression passes.

All reproduced implementation findings have focused fixes and review closure. Combined final regression, source preservation and scoped branch delivery are complete; code722866a5 is remote-verified. Existing issue10 retains the separately authorized empirical work; no issue has been duplicated or silently closed.

- **EVAL-ORDER (pre-existing fixture assumption):** The initial broad gate caught a legitimate concurrent terminal-error ordering. Exact original SQLite attempts and budget totals were verified. The test now verifies exact allowed error codes under native, forced slot-first and forced budget-first schedules. All original budget/denominator/replay assertions remain;9focused checks pass. Production budget behavior is unchanged.
