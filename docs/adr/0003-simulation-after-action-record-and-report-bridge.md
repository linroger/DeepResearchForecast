# ADR 0003 — Simulation After-Action Record and the Forecast-Report Bridge

- **Status:** Implemented and verified offline; fresh-provider operational acceptance remains open (owner requested completion on 2026-10-23)
- **Date:** 2026-10-22
- **Design and change list:** `docs/handoff/simulation-after-action-record/design.md`
- **Continuity record:** `docs/handoff/simulation-after-action-record/handoff.md`
- **Invariants bound by this ADR:** I-11, I-16, I-21 (as defined in `EXECPLAN_FOGLAMP.md` §"Invariants", recoverable from git `92e53486`; ratified for the evidence plane by ADR 0002)
- **Supersedes in part:** the WAVE9 "simulation must never become the narrative subject" editorial rule in `backend/app/services/report_agent.py` (`_repair_simulation_leakage`, `PLAN_SYSTEM_PROMPT`) and the relabel-as-evidence rewrites in `backend/app/services/report_lint.py`

## Context

The pipeline runs a speculative multi-agent simulation (Stage 5) and then writes a
forecast report (Stage 6) that is meant to be factual and evidence-based. The stated
contract (README "Evidence decides; simulation and markets inform") is that simulation
output appears only as labelled analysis and never reaches the scenario spine or the
binary probabilities. The code does not deliver that contract, and it has failed in both
possible directions.

1. **Laundering (June to early July 2026 reports).** Finished demo reports present
   fabricated agent statements as quotations from named real people, cite action counts
   and round numbers as evidence, and in one case describe agent behaviour as "the
   bridge" to the published probability weighting (`docs/demos/us-trade-2028/report.md:296-298`).
   `CODEX_FOGLAMP.md` §4.15 named this failure and Foglamp WP1 item 7 ordered the
   provenance-suppressing instruction removed.
2. **Erasure (reports after WP1 containment).** `ev-2035`, `grid-storage-2040` and
   `datacenter-2030` contain no simulation content at all. The simulation's only
   footprint is a chart titled "Forecast Outcome-Share Trajectory"
   (`report_visualizer.py:3233`), which carries no "simulated" marker. A reader cannot
   learn why Stage 5 ran.
3. **Laundering by construction (current default).** Under `diagnostic_only` the
   simulation signal pack is pinned into every section prompt with a header that
   demands explicit simulation attribution (`report_agent.py:4145-4256`). The final
   lint then rewrites "the simulation shows" into "the evidence indicates" and
   模拟结果显示 into 现有证据表明 (`report_lint.py:927, 999, 1009, 1026-1027`), the
   Part 2 prompt says "NEVER mention the simulation … attribute analytical viewpoints
   to our scenario analysis instead" (`report_agent.py:11829`), and any surviving "the
   simulation" is a hard publish blocker. The only prose that survives is
   simulation-shaped text in evidence clothing. Three attribution conventions coexist.
4. **Isolation is prompt-level on the default engine.** Byte-identical probability
   prompts across differing simulations are proven only for the opt-in world-v1 engine
   (`backend/tests/test_world_report_consumers.py:227`). On the default OASIS engine the
   no-spine fallback (`report_agent.py:2628`) extracts probabilities from prose that the
   pack shaped.
5. **The dynamics narrative already exists but is unread.** Every committed round
   stores an arbiter narrative, a deterministic digest and headline, facts changed with
   causes, decisions with public statements, offers, breaches and red-line crossings in
   `world_state_history.jsonl` (`world_update.py:709`). Only the dashboard reads it. No
   end-of-run account exists; `run_summary.json` is health statistics.
6. **The simulation has earned no probability authority.** The production ledger has
   zero resolved outcomes, no backtest ablation has run, and the world-v1 realism gate
   is "promotion withheld". I-21 forbids promoting a policy without held-out evidence.

The owner's question, "incorporate the simulation into the report, or write a separate
simulation summary", presumes a binary. The defect is that simulation content has no
sanctioned place, so it is either hidden or disguised.

## Decision

1. **Record class.** Simulation output is a `simulated` record class (I-11). It is
   never evidence, never a probability input, and never silently merged with observed
   or forecast records. Promotion to a probability input remains blocked until a
   prospective, held-out paired Brier or log-score lift over the research-only arm
   exists (I-21). `legacy_prompt` stays fixture-only.
2. **A separate, gated Simulation After-Action Record.** Stage 5 finalization writes
   `simulation_record.json` (schema `simulation-record/v1`) and a rendered
   `simulation_record.md` in the run's output language. The record has one section per
   committed period (dates, arbiter narrative labelled as such, moves with public
   statements, facts changed with unit and cause, events and shocks, offers and
   breaches, red-line crossings, alliance shifts) and an overall section (final state
   versus seed, share trajectory and path spread, turning points, track records,
   limits). Its writer sees simulation artifacts only, never the dossier, sources,
   spine or market pack. It uses `public_statement` only, never `private_rationale`.
   A hollow, errored or truncated run yields a deterministic stub and no narrative
   (I-16).
3. **A deterministic record gate.** `simulation_record_audit.json` records hard issues
   for: a period missing or extra relative to committed rounds; a numeric token that
   does not trace to an artifact row; a named entity outside the cast, variable and
   scenario allowlist; a quoted statement that is not a substring of a stored
   `public_statement`; any `[S#]` marker; any `private_rationale` text; a banner that is
   not byte-exact; language contamination. An unaudited or failed record is not served
   and the report carries no link to it.
4. **Exactly one fenced bridge section in the forecast report.** A deterministic
   renderer produces one section titled "Scenario simulation: what the exercise
   explored" (情景模拟：推演探索了什么) from `simulation_record.json`, wrapped in
   `<!-- sim-bridge:start -->` / `<!-- sim-bridge:end -->`, inserted after the publish
   stabilizer at the point where the world-v1 pathway appendix is inserted today
   (`report_agent.py:14993`), excluded from prose lint, and rendered in Chinese
   deterministically for the language variant. It contains the banner, the health line,
   at most eight dated decisive moves selected by a fixed documented rule, red lines
   crossed and commitments broken, a table of final simulated shares beside the
   report's probabilities with the fixed sentence that the probabilities were not
   changed by the exercise, the outcome-share chart retitled "Simulated outcome-share
   trajectory", the what-if comparison table when a base simulation exists, and the
   record's SHA-256. No LLM-written sentence about the simulation appears anywhere in
   the forecast report. Under `no_update` the section and the link are omitted; the
   record is still written for the Simulation tab.
5. **Provenance replaces laundering.** Every lint rewrite whose target is an evidence
   phrase is deleted. Outside the bridge, any simulation vocabulary or simulation-shaped
   claim is a hard issue that is deleted or re-grounded in a `[S#]` citation, never
   relabelled. Inside the bridge, honest attribution is required. One reader-facing
   name per language and one exported constants module supply the header, lint, chart
   titles, UI badge and bridge title.
6. **The signal pack leaves section prompts on the default engine.** `_build_signal_pack`
   returns an empty string under `diagnostic_only` and `no_update` for every engine, as
   it already does for world-v1. The simulation reaches the report only through the
   bridge.
7. **The boundary is a byte-level information-flow test, not an instruction.** The
   existing RW-11 test is extended to the default engine: two runs that differ only in
   simulation artifacts must produce byte-identical spine, binary, section, critique
   and repair prompts and an identical `forecast.json` apart from the bridge hash, and
   their reports may differ only inside the bridge markers.

## Consequences

- Positive: the reader sees what the simulation did and where it disagreed with the
  evidence, in one place, under one banner; the forecast report's probabilities are
  provably research-only on every engine; the laundering path is closed by deletion
  rather than by instruction; the gate checks what is checkable for a speculative
  document (fidelity to the trajectory), and says so.
- Accepted costs: mechanism prose in Parts 2 and 3 gets thinner once the pack leaves
  section prompts; one more artifact per run to audit and translate; three engine
  adapters (reflexive OASIS, world-v1, legacy in-band or hours mode); roughly 1,500
  tests pin current lint and leakage behaviour and must be re-pinned, not loosened;
  pre-policy demo reports stay inconsistent until badged or regenerated.
- Risks accepted with mitigations: a vivid per-period story can out-persuade dry
  probabilities, so per-period sections carry no scenario shares and the banner is on
  every page; the decisive-move selection rule editorializes, so it is fixed,
  documented and tested; marker and label drift has happened before
  (`【预测结果分布` vs `【推演结果分布`), so one constants module is shared by renderers,
  lint and tests.

## Implementation status (2026-10-23)

Claude's S0–S4 integration was recovered from `579c1acf` and completed on
`codex/simulation-report-boundary`. The owner explicitly asked to finish the
attached architecture; version-1 decisions D1–D6 use the recommendations below.
The previous outline-prompt exception is closed, including direct writer tools
and the community-tool fallback. The native world engine remains opt-in.

The record now binds canonical JSON, both deterministic Markdown renderings and
its consumed simulation inputs, including the native world manifest. Every public
record consumer uses the verified snapshot. Missing/stale records are repaired
without rerunning a paid simulation or repeating synthesis. A shared terminal
publisher covers main, reuse, seed and standalone paths; the parallel runner waits
for post-hoc artifacts before announcing completion.

Legacy fallback records are compiled and audited in memory with synthesis off.
Rejected projections produce health-only disclosures. Both primary and translated
bridges must match exact deterministic bytes, including zero-bridge policies and
malformed-marker negatives. The composed Mandarin translator reviews only prose;
its source-bound model receipt and the deterministic envelope are checked again
at publication. Unknown policy never grants a record link.

Verification and exact limits are recorded in
[completion.md](../handoff/simulation-after-action-record/completion.md) and
[verification.json](../handoff/simulation-after-action-record/verification.json):
883 feature-branch backend tests, 321 frontend tests, and 981 backend / 379 frontend
tests on the composed working tree, with explicit skips/expected failures retained.
A copied complete nine-period saved run passes the record gate with zero warnings;
the actual Vue component was exercised in both UI languages and across periods.

The separately defined fresh-provider acceptance runs and optional synthesis
provider check have not been performed. These are operational evidence limits,
not permission to give simulated shares probability authority or to overwrite
existing accepted reports. No prospective calibration claim is made.

## Alternatives considered

1. **Full integration with attribution (status quo plus better prompts).** Rejected:
   attribution is exactly what the lint has been destroying; provenance cannot be
   audited sentence by sentence in a long report; one disguised speculative paragraph
   taxes trust in the binary table, which genuinely is research-only.
2. **Separate simulation summary only, report silent.** Rejected: the reader never
   learns why Stage 5 exists; the demo site and README over-promise; the stage reads as
   decorative.
3. **Trailing JSON appendix only (the world-v1 pattern as the only home).** Rejected:
   exact and gateable but unreadable, and it cannot carry the per-period account the
   owner asked for.
4. **LLM-written bridge paragraphs in a separate context.** Deferred, not rejected:
   two of three design perspectives favoured a few labelled paragraphs on where the
   exercise disagreed with the spine. Version 1 keeps the bridge deterministic so it
   can be byte-gated; a prose variant may follow once the gate and the information-flow
   test are in place (open decision D2 in the design doc).
5. **Enable `validated_update` or `legacy_prompt` so the simulation moves probabilities.**
   Rejected under I-21: zero resolved forecasts, no ablation numbers, realism gate
   withheld, and the world state is seeded from the research prior, so corroboration
   would be circular.
