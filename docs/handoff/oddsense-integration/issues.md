# Scoped issue ledger

All entries were observed on 2026-10-18. Source-observed defects below have not been executed as reproductions. Application fixes require the approved implementation plan. This ledger preserves the findings without editing unrelated issue lists or sending new external messages.

| ID | Status / owner | Evidence and implication | Next validation or disposition |
|---|---|---|---|
| OS-NEWS | Proposed / approved-slice owner to assign | No native NewsAPI/Reddit source path was found in the inspected research/tool/config paths. Existing source projections discard publication metadata. | OS-1 tool → ledger → source-artifact scenarios and explicit pre-QA metadata preservation. |
| OS-VENUE | Proposed / approved-slice owner to assign | Market IDs, refreshes and resolution are effectively Polymarket-specific despite an exchange field. See downstream-paths.md sections 1–2. | OS-2 contextual isolation, provider-qualified identity and no wrong-provider dispatch checks. |
| OS-REPLAY | Proposed / approved-slice owner to assign | A new context artifact is absent from the generation/promotion/reuse file contracts; existing live market refresh does not establish immutable context. | OS-3 pin/tamper/fork checks with zero fresh provider calls during replay. |
| DRF-PM-PRICE | Unreproduced follow-up / future bounded bug task | `forecast_extractor.py:3444–3449` builds both research/current anchor prices from current `implied_yes_prob`, potentially ignoring original `price_at_research`. | Reproduce research 34% → refreshed 41% through anchor/comparison/UI; fix separately only with a failing regression. |
| DRF-PM-STATUS | Unreproduced follow-up / future bounded bug task | Existing report loading drops container time/status; timeout merge and dossier empty presentation can disagree. See downstream-paths.md section 2, items 2, 4 and 7. | Test timeout/partial-failure → API/UI/report meaning; retain original source evidence. |
| UPSTREAM-FIDELITY | Upstream constraint / no vendor maintenance | Missing prices become zero; first-outcome Yes assumption; Kalshi response/field mismatch; tone-to-probability divergence; fuzzy arbitrage. | Do not transplant these semantics. Native-shaped negative fixtures constrain OS-1/OS-2. |
| METACULUS-ACCESS | Needs current evidence / compatibility investigation | Vendor uses an old questions/median schema; the current documentation page yielded no readable text and no configured access was inspected. | Verify official current schema/access before claiming a working community-forecast adapter; explicit unsupported/unavailable otherwise. |
| SOURCE-LIVE | Needs runtime evidence / approved-slice owner | No provider API was called and supplied credential validity/plan is unknown. Public documentation is compatibility guidance, not a successful probe. | Bounded read-only probes after plan approval; retain access/quota/schema failure reasons, without keys. |

No build defect was discovered because no application build or test was run during this documentation-only phase. No P0 issue is inferred from a static study.
