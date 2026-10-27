# Handoff.md

**Last Updated:** 2026-10-27 (Asia/Shanghai)
**Status:** Complete
**Current Focus:** Delivered official FMP integration; running-app adoption remains a separate operation.

## 1) Request & Context
The user requested study of FMP documentation and MCP, a Codex skill, and automatic data/news retrieval by DeepResearchForecast's research agent. They explicitly selected FMP's official MCP server. Work is isolated on codex/fmp-research-skill, based on main 0d4488815c6164eb3f920f928c9e1f9ffc1b63bb. The dirty primary checkout is preserved. The credential supplied in chat will not be copied into source, logs, or configuration. Local replacement configuration is pending.

## 2) Requirements → Acceptance Checks
| Requirement | Scenario | Expected result | Evidence |
|---|---|---|---|
| Official MCP only | Exercise discovery and call through controlled HTTP | Fixed FMP host, discovered schemas, no community dispatch | Client tests and review |
| Automatic deep research | Actual v3 and legacy research tool consumers | Data/news available when configured, calls consume budgets and produce citations | Integration tests |
| Source integrity | Capture, reload and tamper/replay controls | Stable captured bytes; no silent refresh or official-data promotion | Integration tests |
| Skill usability | Validate and independently exercise skill | Correct routing, dates, attribution, bounded calls and clear limits | Skill validator and reviewer |
| Credential hygiene | Synthetic echoed secret and transport failures | No key in source/evidence/error output | Negative controls |

## 3) Plan & Decomposition
Follow [PLANS.md](PLANS.md). Parallel owners will have disjoint client, runtime integration, and skill/documentation paths. The parent owns final verification and delivery.

## 4) To-Do & Progress Ledger
- [x] Read official documentation, community implementation differences and current research interfaces.
- [x] Confirm both consumers and official-only choice with the user.
- [x] Implement bounded client; client96 and live three-capability checks passed.
- [x] Wire and verify actual research consumers; runtime31, deployment26 and composed acceptance passed.
- [x] Create/install skill and validate behavior; skill8 and independent forward-test closure recorded.
- [x] Independent review and scoped delivery; all feature findings closed and source verified on remote main.

## 5) Findings, Decisions, Assumptions
Official endpoint is https://financialmodelingprep.com/mcp with apikey authentication. Tool names must come from live tools/list, not community camelCase names. Existing official-data MCP hub is stdio and serves statistical data; FMP receives its own bounded research evidence path. Current FMP snapshots cannot establish historical point-in-time availability.

## 6) Issues, Mistakes, Recoveries
No FMP key is present in the process environment or primary dotenv. This prevents authenticated live verification but does not prevent implementation or offline validation. The official provider's live schemas are authoritative; documentation examples are hints only.

## 7) Scenario-Focused Resolution Tests
Pending client and real research-boundary scenarios. No runtime or live-provider success is claimed yet.

## 8) Verification Summary
Read-only source and documentation inspection only so far. Evidence will live outside the checkout under ~/.local/share/DeepResearchForecast/verification/fmp-research-integration.

## 9) Remaining Work & Next Steps
Complete the client, v3/legacy integration and skill, then review and run scoped offline gates. Use a replacement credential only if configured locally. No service restart or saved-run mutation is part of the current work.

## 10) Updates
- 2026-10-27: Recorded approved official-only scope, isolation, plan and acceptance criteria before implementation.

### 2026-10-27 implementation progress
Darwin owns the official MCP transport/client and fake-HTTP protocol tests. Meitner owns v3/legacy capture and consumer integration, plus the parent/deployment allowlists and focused tests. The parent owns the skill, Codex helper and installer, bilingual README and configuration documentation. Popper is independently forward-testing the skill against current financial research and historical-cutoff scenarios.

The client uses the MCP SDK against the fixed official HTTPS endpoint; it discovers actual schemas, validates call arguments, limits response bytes and deadlines, and never substitutes REST/community services. The research integration exposes two small static wrapper tools and records exact sanitized responses as vendor evidence. Historical backtests and saved-run replay do not acquire current data. Canonical source skill and installed Codex helper share the same client bytes through the installer.

The user chose to configure a replacement key locally. They have not yet confirmed it is configured, so no authenticated FMP call has been attempted. Skill frontmatter validation passed; client and consumer acceptance tests remain pending.

### Skill fixture correction
The first guarded skill run had 4 passes and 4 fixture setup failures: the offline guard deliberately rejects any `.env` path, including a synthetic file under its test root. The fixtures now use an explicit `fmp-settings.fixture` path with synthetic values. The production helper accepts an explicit file path regardless of basename, so the same parsing behavior is exercised without weakening the guard. The failed receipt is retained at `skill-01`; no credential was read. The helper also now emits fixed, distinguishable local error reasons without raw exception text.

### Official service compatibility and independent skill review
The locally configured key was detected without displaying its value. Two authenticated official `tools/list` operations succeeded; sanitized captures and a receipt are stored at `verification/fmp-research-integration/live-01`. No data/news business call has yet been made. Actual tools are grouped (`quote`, `news`, `statements`) and require a provider-defined `endpoint` enum selector. The initial synthetic protocol tests did not cover that official shape; validation is being corrected to admit exact discovered selectors while continuing to reject network URL overrides and unbounded endpoints. A small fixture preserves the observed official schemas in `backend/tests/fixtures/fmp_official_catalog.json`.

Independent skill forward-testing found three useful corrections, all applied: permission denials must be scoped to the affected capability, ADR/local comparisons need issuer/currency/ratio reconciliation, and analyst estimates can support relevant forward scenarios without being recast as actuals. The transport owner is also testing that a statements-specific denial leaves independently entitled news usable.

The updated standalone skill helper gate passed 8 tests in 1.19 seconds (`skill-02`), with exit 0, complete shutdown and empty source drift. This establishes helper behavior and packaging only; runtime integration, final composed acceptance and live data/news remain pending.

### Live official data/news acceptance
After the grouped-selector fix passed the 96-case client gate (`client-20261027-05`), the same current client bytes completed three bounded live official MCP business calls: `quote`/`quote` for AAPL, `statements`/`income-statement` for one annual AAPL record, and `news`/`search-stock-news` for one AAPL item. All returned status `ok` and one row. The financial response retained reported currency, fiscal year/period, period end, filing and acceptance dates. The news response retained publisher, publication time and original URL. Raw MCP payloads used text blocks containing JSON rows, not structuredContent; integration tests are being aligned with this observed shape.

The sanitized captures, request files, field-level checks, client hash and receipt are under `verification/fmp-research-integration/live-01`. This proves live official provider access for these three capabilities. It does not prove all FMP plan entitlements or a full live-model research run. No paid model, saved-run resume or app restart was performed.

### Codex installation and review closure
The self-contained skill is installed at `/Users/rogerlin/.codex/skills/fmp-research`; its client hash matches the accepted canonical implementation. Skill validation passed and running the installed helper without an explicit credential source returned the expected disabled status without provider access. The local secret scan found zero matches across 52 owned-source, installed-skill and live-capture files; it retains neither credentials nor their hashes. Independent skill rereview closed all three documentation findings. Runtime review findings remain under correction and are not covered by that skill approval.

### Final implementation acceptance
The final composed gate (`composed-03`) passed 1,093 tests in 69.21 seconds, with 21 optional-DeerFlow checks skipped and two explicitly excluded checks. All 46 recorded source hashes still matched after the run, shutdown completed, and all ten registered children exited zero. The parent receipt records two blocked process attempts; child logs add two font-discovery process probes and eighteen font-directory reads. This is not a zero-attempt or OS-sandbox claim. Exact exclusions and reasons are in [verification.json](verification.json). No FMP scenario was skipped or excluded.

The initial broader run found the core skill exceeded its existing 7,000-character prompt budget; its FMP routing was condensed to a short pointer while the engines retain the full dedicated guidance. One existing news-source fixture needed its real engine `records` field initialized. The CLI-concurrency test now uses a small registered fixture that runs the unchanged production sync script, rather than relaxing the offline runner's child-script scope. Renderer and gateway fixture scripts were explicitly registered. The `.claude` litter fixture remains outside the guard's credential-path boundary, and the unchanged report-baseline fixture remains a separate follow-up; neither is silently marked passing.

The original independent runtime reviewer closed all five findings against current source with ten focused scenarios and matching before/after hashes. Final worker runtime31 and deployment26 evidence is preserved privately; the composed gate includes the current feature tests. The client96, skill8 and live-provider checks overlap with other evidence and are not additive totals. The accepted feature flag in `feature_list.json` is now true.

Implementation, documentation, installed skill, source-aware research capture and verification are complete. Commit and remote delivery follow. The running primary checkout has not been switched or restarted, and its unrelated dirty work remains outside this change.

### Next-session prompt
Read this handoff and `verification.json`. The FMP feature is implemented with the official endpoint only. Check the recorded delivery ref and current local service/active-run state before adopting main in the running application. Preserve the dirty primary checkout. Do not refresh sealed research or infer full live-model/native-runtime acceptance from the offline gates. Investigate the separately recorded report-baseline fixture only if that follow-up is requested.

### Main-branch delivery
Implementation commit `2de6eca8ce85f2f89f6b8c3cc3e6e963c95f4255` was pushed atomically and without force to both `legacy/main` and `legacy/codex/fmp-research-skill`; `git ls-remote` independently confirmed both refs. It is a fast-forward from the inspected main base, preserving the preceding history. This closing documentation commit records that result; the final delivered ref is in the private `final-delivery.json` receipt.

The Codex skill is installed, the official MCP credential has passed bounded live checks, and new research runs from the updated code automatically expose and use FMP when relevant. The already running primary application was not restarted or switched from its existing dirty checkout. No paid model run, saved forecast replacement or production-data mutation was performed.
