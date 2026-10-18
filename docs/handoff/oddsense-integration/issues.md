# Scoped issue ledger

All entries were observed on 2026-10-18. Source-observed defects below have not been executed as reproductions. Application fixes require the approved implementation plan. This ledger preserves the findings without editing unrelated issue lists or sending new external messages.

| ID | Status / owner | Evidence and implication | Next validation or disposition |
|---|---|---|---|
| OS-NEWS | Done / verified OS-1 | No native NewsAPI/Reddit source path was found in the inspected research/tool/config paths. Existing source projections discard publication metadata. | OS-1 tool → ledger → source-artifact scenarios and explicit pre-QA metadata preservation. |
| OS-VENUE | Done / contextual OS-2 | Market IDs, refreshes and resolution are effectively Polymarket-specific despite an exchange field. See downstream-paths.md sections 1–2. | OS-2 contextual isolation, provider-qualified identity and no wrong-provider dispatch checks. |
| OS-REPLAY | Done / verified OS-1/OS-3 | A new context artifact is absent from the generation/promotion/reuse file contracts; existing live market refresh does not establish immutable context. | OS-3 pin/tamper/fork checks with zero fresh provider calls during replay. |
| DRF-PM-PRICE | Unreproduced follow-up / future bounded bug task | `forecast_extractor.py:3444–3449` builds both research/current anchor prices from current `implied_yes_prob`, potentially ignoring original `price_at_research`. | Reproduce research 34% → refreshed 41% through anchor/comparison/UI; fix separately only with a failing regression. |
| DRF-PM-STATUS | Unreproduced follow-up / future bounded bug task | Existing report loading drops container time/status; timeout merge and dossier empty presentation can disagree. See downstream-paths.md section 2, items 2, 4 and 7. | Test timeout/partial-failure → API/UI/report meaning; retain original source evidence. |
| UPSTREAM-FIDELITY | Upstream constraint / no vendor maintenance | Missing prices become zero; first-outcome Yes assumption; Kalshi response/field mismatch; tone-to-probability divergence; fuzzy arbitrage. | Do not transplant these semantics. Native-shaped negative fixtures constrain OS-1/OS-2. |
| METACULUS-ACCESS | Needs current evidence / compatibility investigation | Vendor uses an old questions/median schema; the current documentation page yielded no readable text and no configured access was inspected. | Verify official current schema/access before claiming a working community-forecast adapter; explicit unsupported/unavailable otherwise. |
| SOURCE-LIVE | Done with explicit source limits / final probes | No provider API was called and supplied credential validity/plan is unknown. Public documentation is compatibility guidance, not a successful probe. | Bounded read-only probes after plan approval; retain access/quota/schema failure reasons, without keys. |

No build defect was discovered because no application build or test was run during this documentation-only phase. No P0 issue is inferred from a static study.

## Implementation review findings — 2026-10-18

The independent reviews are provisional until final source freeze. Provider PR-1 (cross-process market request reservation before I/O) and PR-2 (actual v3 quote/rule/unit presentation) are assigned to the provider/market/research owners. Downstream review identifies same-generation stale/rollback acceptance, deleted-declared-proof resume recovery, late-context addition before PREPARE binding, omitted Markdown quote metadata and ambiguous original source-ref display; these are assigned to their current provider/backend/frontend owners with focused positive and negative regression scenarios. None is closed merely by a broad passing suite. Report table mutation under real publication is also retained as meaningful end-to-end red evidence. No unrelated Polymarket price/status follow-up is mixed into these fixes.

## Final disposition

All concrete integration review findings are closed in the final provider/downstream review records and final-verification.md/json. The owned feature entries are passing on controlled actual workflow plus the separately recorded live compatibility evidence. Original unrelated DRF-PM-PRICE/DRF-PM-STATUS remain unreproduced follow-ups; no unrequested repair was mixed in. Metaculus authenticated access remains a documented optional unsupported capability. Live Reddit returned403; its default-off/degradation contract is tested rather than relabeled as source success. Remote push is blocked by invalid configured GitHub authentication, already observed before this implementation; valid authentication is the external unblocking action.

## OS-TIMING — In progress

The shared ten-second allowance currently measures idle wall time from first prefetch, so ordinary model planning can prevent later investigator tools from acquiring sources. Fix aggregate source-acquisition accounting, preserve absolute caller deadlines and conservative crash reservations, and obtain deterministic red/green plus the actual workflow gate. Earlier receipts remain historical for their source hashes.

### OS-TIMING resolution

Closed by cumulative acquisition accounting, durable pre-I/O time reservations, native residual-deadline propagation and strict invalid-counter/legacy behavior. Meaningful red: idle-budget-red; current-byte green:196 focused cases and1448/two existing skips in delivery-final. Crash test now proves interrupted time cannot be recycled for new I/O. See final-verification.md/json.

### OS-TIMING review follow-through

Independent PR-4/PR-5 reopened the timing closure for pending-write completion classification and missing-marker legacy count migration. Four red cases demonstrate the defects. Fixes preserve the original absolute deadline and deny fresh unknown elapsed time proven by legacy request counts; positive controls retain untouched legacy acquisition and exact sealed replay. Final reviewed gate and closure are recorded below.

### Final OS-TIMING reviewed gate

All seven PR-4/PR-5 regression/positive controls and the full22-suite current-byte matrix pass:1455passed/two existing harness skips. Only independent exact-byte closure and scoped delivery remain; no application defect is left observed in this issue.

### OS-TIMING final closure — 2026-10-18T14:50:06.051873+00:00

Independent provider review closes PR-4/PR-5 on the final1455-pass/two-skip freeze; no concrete scoped P1/P2 remains. Implementation issues OSNEWS, OSVENUE, OSREPLAY and OS-TIMING are done locally. The pre-existing unrelated market findings and separate remote-authentication delivery limitation remain explicit.
