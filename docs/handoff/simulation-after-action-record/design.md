# Simulation After-Action Record and Forecast-Report Bridge — Design

**Status:** Proposed design, 2026-10-22. All slices (S0–S4) are implemented on `claude/sim-provenance-impl` (S0 also on `claude/sim-provenance-s0`); §10 records what each slice actually did where it differs from §3–§6. ADR acceptance still owes the owner's live runs.
**Decision record:** [ADR 0003](../../adr/0003-simulation-after-action-record-and-report-bridge.md).
**Continuity:** [handoff.md](handoff.md) in this folder.

The key words MUST, SHOULD and MAY are to be interpreted as described in RFC 2119.

Every `file:line` anchor below was checked against the working tree on 2026-10-22. Line
numbers drift; the function or constant name next to each anchor is the durable
reference.

---

## 1. Problem

The forecast report (Stage 6) is meant to be factual and evidence-based. The multi-agent
simulation (Stage 5) is speculative by construction. The question was whether the report
should incorporate the simulation or whether a separate summary should close Stage 5.

The code has already tried both answers and both failed.

| Period | What the finished reports did | Evidence |
|---|---|---|
| June to early July 2026 | Simulation laundered into evidence: fabricated statements tagged 「模拟代理人「Donald J. Trump」推演」, action counts cited as insight, agent behaviour called "the bridge" to the 47/28/25 probability weighting | `docs/demos/us-trade-2028/report.md:124-158, 296-302`; `docs/demos/us-midterms-2026/report.md:304-334`; `docs/demos/semiconductors-2030/report.md:39-45` (real BIS rules attributed to "the simulated world") |
| After Foglamp WP1 containment | Simulation erased: zero mentions in `ev-2035`, `grid-storage-2040`, `datacenter-2030`; only footprint is a chart titled "Forecast Outcome-Share Trajectory" with no "simulated" marker | `docs/demos/grid-storage-2040/report.md:149-152`; `backend/app/services/report_visualizer.py:83, 2325, 3233, 5170` |
| Current default (`diagnostic_only`) | Laundering by construction: the signal pack is pinned into every section prompt demanding 「内部情景推演显示…」 attribution, then the final lint rewrites that attribution into evidence wording and any surviving "the simulation" blocks publication | `report_agent.py:4145-4256` (`_build_signal_pack`), `report_agent.py:4009` (`_prepend_research_background`), `report_lint.py:927, 999, 1009, 1026-1027` (`scrub_simulation_mechanics`), `report_lint.py:359-376` (`rewrite_sim_labels`), `report_agent.py:11829` (Part 2 prompt), `report_agent.py:6818-6943` (`_repair_simulation_leakage`) |

Four further facts shape the design.

1. **Probability isolation is byte-proven only for world-v1.** `backend/tests/test_world_report_consumers.py:227` (RW-11) proves two runs differing only in simulated capacity yield identical probability prompts. On the default OASIS engine the no-spine fallback `_probability_source` (`report_agent.py:2628`) extracts probabilities from prose the pack shaped, so isolation rests on prompt compliance plus scrubbing.
2. **The per-period narrative exists and is unread.** Each committed round stores `narrative` (arbiter, ≤700 chars, `world_update.py:50, 214, 339`), a deterministic `digest` (`build_round_digest`, `world_update.py:598`), a `headline` (`world_update_headline`, `world_update.py:684`), `diff`, `decisions`, `deterministic` lists (offers, breaches, shocks fired), `scenario_pressure` and `shares` in `world_state_history.jsonl` (`run_world_round`, `world_update.py:709`; writer `run_parallel_simulation.py:3776`). Only `WorldStatePanel.vue:49` renders the narrative, one period at a time. The report reads two deterministic fields from the same file (`_world_evolution_block`, `report_agent.py:4333`). No end-of-run synthesis exists; `write_run_summary` (`simulation_runner.py:2137`) is deterministic health aggregation.
3. **Three attribution conventions coexist.** Header: 「内部情景推演显示…」 (`report_agent.py:4247-4256`). Tier-2 rewrite and Part 2 prompt: "our scenario analysis indicates" (`report_agent.py:6911-6922, 11829`). Whitelist `_SIM_QUOTE_LABELS` (`report_agent.py:7032`) admits "scenario panel" and "analytical perspective" while the system prompt bans 「专家小组」. The marker `【预测结果分布` in `forecast_extractor.py:1187, 1266` no longer matches the renderer's `【推演结果分布` (`report_agent.py:4283`).
4. **No probability authority has been earned.** `backend/uploads/pipelines/_forecast_ledger/ledger.jsonl` has 214 rows and zero resolved outcomes; no `eval_report.json` exists; the world-v1 realism gate is "promotion withheld". ADR 0002 I-11 already forbids silent merging of simulated and observed records. `CODEX_FOGLAMP.md` §4.23 keeps the simulation at "mechanism exploration" until a prospective paired lift exists.

The defect is therefore not "in the report or out of it". It is that simulation content has no sanctioned place, so it is either hidden or disguised.

---

## 2. Goals and non-goals

**Goals**

- G1. A reader can see, in one place and under one banner, what the simulation did period by period and overall.
- G2. The forecast report's probabilities are provably research-only on every engine, by an information-flow test rather than by instruction.
- G3. Every sentence derived from the simulation is labelled as such wherever it appears, and no lint rule can turn that label into evidence wording.
- G4. A speculative document is gated on what can be checked: fidelity to the trajectory artifacts, not truth.
- G5. Hollow, errored, truncated or invalid runs are never narrated (I-16).
- G6. One reader-facing vocabulary, one constants module, one chart title convention.

**Non-goals**

- Promoting simulation output to a probability input (`validated_update`). Blocked by I-21 until a held-out paired lift exists.
- Improving simulation realism. The record exposes realism limits honestly; it does not fix them.
- Regenerating the pre-policy demo reports. They are badged, not rewritten.
- Changing the world-v1 engine's own pathway appendix beyond sharing constants (version 2 may fold it under the bridge title).

---

## 3. Architecture

```
Stage 5 finalize                       Stage 6 report
────────────────                       ──────────────
world_state_history.jsonl ─┐
world_digest.jsonl        ─┤  simulation_record.py        research-only spine ──► Part 1 · Part 2 · Part 3
world_actions.jsonl       ─┤  (sim artifacts ONLY)             ▲ no sim bytes in any prompt (T1)
world_state.json          ─┼─► simulation_record.json ──┐      │
world_state_trajectory.json┤   simulation_record.md     │  render_sim_bridge(record)  ──► <!-- sim-bridge:start -->
world_paths.json          ─┤                            │  (deterministic, bilingual)      ## Scenario simulation: …
run_summary.json          ─┘                            │                                  <!-- sim-bridge:end -->
                               simulation_record_gate.py ┘  inserted after publish stabilizer,
                               → simulation_record_audit.json  before final audit (as world-v1 appendix today)
                               (fail-closed; unaudited = not served, no link)
```

### 3.1 Simulation After-Action Record

**Artifacts** under `uploads/simulations/<sim_id>/`:

- `simulation_record.json` — schema `simulation-record/v1` (§4). Machine source of truth.
- `simulation_record.md` — rendered in the run's output language; a second rendering for the other language is produced deterministically from the same JSON (no translation call).
- `simulation_record_audit.json` — gate output (§3.2).

**Writer** `backend/app/services/simulation_record.py`, invoked from the orchestrator immediately after `SimulationRunner.write_run_summary` (`pipeline_orchestrator.py:10177` on the main path and `:11558` on the resume path), registered as pipeline artifact `simulation_record` beside `run_summary` (`pipeline_orchestrator.py:10904`; `backend/app/api/research.py:856`).

Input contract (MUST):

- Inputs are simulation artifacts only: `world_state.json`, `world_state_history.jsonl`, `world_digest.jsonl`, `world_actions.jsonl`, `decisions.jsonl`, `world_state_trajectory.json`, `world_paths.json`, `run_summary.json`, and the cast manifest for actor names and agency classes. The research dossier, `sources.json`, the forecast spine, the market pack and `forecast.json` MUST NOT be opened by this module. A test asserts the module imports nothing from the report or research planes.
- From `world_actions.jsonl` only `actor_name`, `option`, `targets`, `magnitude`, `public_statement`, `terms`, `commitment`, `alliance_moves`, `expected_reactions`, `scenario`, `status` are read. `private_rationale` is excluded by field allowlist, not by filtering after the fact.
- Scenario shares appear only in the overall section, labelled `epistemic_status: elicited_model_projection`. Per-period sections carry no shares (herding guard I-1 applied to readers as well as agents).

Generation modes:

- **Deterministic skeleton (always).** Per-period sections are templated from the history row: arbiter narrative verbatim under the label "Arbiter narrative", then moves, held positions, facts changed (`variable`, `from`, `to`, `unit`, `cause`), events and shocks fired, offers (opened, accepted, rejected, countered, lapsed, breached), red-line crossings, alliance shifts, arbiter status and problems, behaviour metrics. The overall section is templated from `world_state.json` (final variables versus seed values, track records), `world_state_trajectory.json` (shares, convergence), `world_paths.json` (per-scenario mean, sd, p10/p50/p90, leaders, shocks fired per path) and `run_summary.json` (health).
- **Bounded synthesis (optional, default on, `SIM_RECORD_SYNTHESIS=true`).** One LLM call writes the overall "Dominant mechanisms, turning points, what did not happen" prose from the deterministic skeleton only. Its output passes the gate's fidelity checks (§3.2); on any hard issue the deterministic skeleton is kept and the synthesis is dropped with a recorded reason. Per-period prose is never LLM-generated in version 1; the arbiter narrative is already LLM prose written at the time and is quoted as such.
- **Health stub.** When `run_summary.simulation_health ∈ {hollow, errored, truncated}` or the decision channel validity is not `valid` (`decision_channel.py:730-745`), the record is a banner plus health table with zero LLM calls and no period sections beyond the committed count. `llm_degraded` produces the deterministic skeleton with no synthesis call. Rounds with `arbiter_status != applied` are marked "mechanical only" in their section.

Engine adapters (one schema, three producers):

| Engine | Source of period sections | Notes |
|---|---|---|
| OASIS + reflexive world model (default, `SIM_WORLD_MODEL=true`, calendar mode) | `world_state_history.jsonl` rows | Full record |
| world-v1 (opt-in) | `world_result.json` events, decisions, commitments, interactions grouped by period | No arbiter narrative exists; sections are tables. Version 1 leaves the existing pathway appendix in place and only shares constants |
| Legacy in-band or hours mode | `world_digest.jsonl` rows written by `world_delta.build_world_delta` | Thin record; the banner states "no world model ran"; never padded |

### 3.2 Record gate

`backend/app/services/simulation_record_gate.py` is deterministic and writes `simulation_record_audit.json` with `{sha256, hard_issues[], warnings[], publication_status}`. It cannot check truth; it checks fidelity.

| ID | Check | Severity |
|---|---|---|
| G1 | Exactly one period section per committed round; none missing, none extra | hard |
| G2 | Every normalized numeric token in the record (percent, decimal, integer with unit, date) appears in the referenced artifact rows or variable histories; shares match `world_state_trajectory.json` after rounding to the rendered precision | hard |
| G3 | Every named entity is in the allowlist: cast names and aliases, variable names, scenario names, period labels; undeclared capitalized multi-word tokens are warnings during a soft-launch window, then hard | hard after soft-launch |
| G4 | Every paragraph has at least one `ref` `{file, round, id}` that resolves; every quoted statement is a substring of a stored `public_statement` | hard |
| G5 | No `[S#]` or `【S#】` marker; no "evidence shows / 证据表明" verbs applied to simulated content | hard |
| G6 | No `private_rationale` substring from any `world_actions.jsonl` row | hard |
| G7 | Banner byte-exact; health line present and matches `run_summary.json` | hard |
| G8 | The words "probability" / 「概率」 are not applied to shares; shares are called "share" / 「份额」 | hard |
| G9 | Language purity for the output language (reuse `report_lint` purity scan in `record` mode) | hard |

An unaudited or failed record is not served by the API, the Simulation tab shows the deterministic digest instead, and the report bridge omits the link line. The record gate never blocks report publication.

### 3.3 Forecast-report bridge

**One section, one place.** `render_sim_bridge(record, *, chinese)` in `report_agent.py`, modelled on `render_world_pathway` (`report_agent.py:163`) and inserted by `_insert_sim_bridge` modelled on `_insert_world_appendix` (`report_agent.py:206`), at the same call site as the world-v1 appendix: after `_stabilize_publish_markdown` and before the read-only final audit (`report_agent.py:14993`). The translated variant receives the Chinese rendering at the same point the world appendix does today (`report_agent.py:10453`). The block is wrapped in `<!-- sim-bridge:start -->` and `<!-- sim-bridge:end -->` and excluded from prose lint via a `_sim_prose` twin of `_world_prose` (`report_agent.py:217`).

**Title and banner** come from the constants module (§3.5): "Scenario simulation: what the exercise explored" / 「情景模拟：推演探索了什么」 and "Simulated under declared assumptions. Not observed facts, not a calibrated probability, and not an input to any probability in this report." / 「声明假设下的模拟；非观察事实，非校准概率，未作为本报告任何概率的输入。」

**Contents (deterministic, in order):**

1. Banner, engine, horizon, periods committed of planned, health line, arbiter-failed-round count, modelling-gap count.
2. **Decisive moves** table, at most 8 rows: period, actor, move, target, public statement truncated at 160 characters. Selection rule, fixed and tested: red-line crossings first; then offers accepted or breached; then the moves whose caused variable change is largest in relative terms; ties by earliest period, then actor name. No action counts, rounds-as-mechanics, or platform vocabulary.
3. **Red lines crossed and commitments broken**, as a list from `deterministic.red_lines_crossed` and track records.
4. **Simulated shares beside this report's probabilities**: scenario, final simulated share (mean and p10–p90 when `K>1`), report probability from the pinned spine, and the fixed sentence "The probabilities in this report were not changed by the exercise (policy: diagnostic_only)." Scenario names are matched by the spine's scenario list; unmatched simulated scenarios are listed with a dash in the probability column, never mapped heuristically.
5. The outcome-share chart, retitled "Simulated outcome-share trajectory" (§3.5), placed here and only here; the "Simulated World Variables" chart likewise.
6. The what-if comparison table (`report_agent.py:12450-12538`), moved here from Part 2 prose, relabelled "simulated outcome shares, baseline versus scenario" without 「权威」.
7. One line "Full record: `simulation_record.md` (SHA-256 …)" when the record passed its gate; omitted otherwise.

**Policy behaviour.** `diagnostic_only`: block present, count exactly one, bytes equal to `render_sim_bridge(record)`; `forecast.json` gains `simulation_bridge: {sha256, forecast_effect, probabilityEvidence: false}`. `no_update`: block absent, no link, no `simulation_bridge` field; the record is still written. `legacy_prompt`: unchanged fixture behaviour. The final audit (`_final_audit_integrity_issues`, `report_agent.py:11180`) adds these as integrity checks.

**No LLM-written sentence about the simulation appears in the forecast report.** Analyst commentary on where the exercise disagreed with the spine is open decision D2 (§7); version 1 gives the reader the table and the record.

### 3.4 Prompt isolation and lint

1. `_build_signal_pack` (`report_agent.py:4145`) returns `""` under `diagnostic_only` and `no_update` for every engine, as it already does for world-v1 (`:4158-4161`). `REPORT_SIGNAL_PACK` (`config.py:398`) defaults to `False`; `FORECAST_SIM_SENSITIVITY` (`config.py:655`) defaults to `False`. The XRUN-1(b) comment at `report_agent.py:5168` is removed with the intent it records.
2. The section critique rubric's signal-pack clause (`report_agent.py:13552-13566`) is removed.
3. `report_lint.scrub_simulation_mechanics` (`report_lint.py:1431`): delete every rewrite whose replacement is an evidence phrase ("the evidence indicates" `:1009`, "the forecast evidence base" `:927`, "the available evidence shows" `:999`, 「现有证据表明」 `:1026`, 「基于现有证据」 `:1027`). Keep deletions of mechanics. `rewrite_sim_labels` (`report_lint.py:359-376`) stops producing "Evidence-based assessment — X" / 「证据分析」; a legacy label becomes a hard leakage issue instead.
4. `LEAKAGE_PATTERNS` (`report_lint.py:153`) remain, but `lint_report` and `_repair_simulation_leakage` become section-aware: text between the bridge markers is skipped entirely (extend `_fence_mask` to treat the marker pair like a code fence). Outside the markers a hit is a hard issue, resolved by deletion or by re-grounding in `[S#]`, never by relabelling.
5. The Tier-2 rewrite prompt (`report_agent.py:6911-6922`) and the Part 2 prompt (`:11829`) replace "attribute to our scenario analysis" with "delete the claim or ground it in a [S#] citation". `PLAN_SYSTEM_PROMPT` (`:869`) loses "读者不应从报告中察觉任何内部方法学机制" and keeps the ban on simulation chapters outside the bridge.
6. `_SIM_QUOTE_LABELS` (`report_agent.py:7032`) drops "scenario panel" and "analytical perspective"; the remaining labels are the constants module's label.
7. The interview summary path (`zep_tools.py:421-463`, `InterviewResult.to_text` with its 「采访摘要」 framing) is left as is but `interview_agents` is removed from the writer tool list on the default engine, since its output cannot survive the fence rule and the tool is already dropped once the OASIS env is offline (`report_agent.py:2548`).

### 3.5 Constants module

`backend/app/services/sim_provenance.py` exports: `SIM_LABEL_EN`, `SIM_LABEL_ZH` ("scenario simulation" / 「情景模拟」), `SIM_BANNER_EN`, `SIM_BANNER_ZH`, `BRIDGE_TITLE_EN`, `BRIDGE_TITLE_ZH`, `BRIDGE_START`, `BRIDGE_END`, `CHART_OUTCOME_SHARES_EN/ZH` ("Simulated outcome-share trajectory" / 「模拟结果份额轨迹」), `CHART_WORLD_VARIABLES_EN/ZH`, `RECORD_SCHEMA = "simulation-record/v1"`. `report_visualizer.py:83-84, 2325, 3166, 3233, 5170, 5176, 5362`, `exec_brief.py`, the lint, the bridge renderer and the record renderer import from it. The frontend badge text (`WorldStatePanel.vue:34`, `WorldSimulationView.vue:6`) is pinned to the same strings by a test that reads the Python constants and the Vue i18n keys.

### 3.6 Surfaces

- **API.** `GET /api/simulation/<id>/record` (JSON) and `/record.md?lang=` serve only a gate-passed record, following the world-state route's containment posture (`backend/app/api/simulation.py:2307`: regular file only, symlinks refused). `GET /api/report/<id>` payload (`backend/app/api/report.py:74`, `_report_publication_payload`) gains `simulation_record_ref: {sha256, url}` when present.
- **Dashboard.** `SimulationView.vue` gets a "Record" view as the default after completion, above the live World State panel and feed: a header card (banner, health, engine, horizon), a period strip, and the selected period's section rendered from `simulation_record.json`; the legacy header gains the caveat `WorldSimulationView.vue:6` already shows. `StageTimeline.vue:142-153` labels the run stage "Scenario simulation". `ForecastReport.vue` shows a provenance legend (Observed `[S#]` / Forecast / Simulated) and renders the bridge block as a shaded box; `BinaryForecastTable.vue` gains the footnote "probabilities from research evidence only" and surfaces `forecast_effect`. `ResearchView.vue:526` keeps auto-switching to the report; the simulation tab badge shows "record ready".
- **Executive brief and digest.** `exec_brief.py:398-420` replaces the health fragment with one line: "Scenario simulation ran (health, N periods); informed mechanism analysis only, not probabilities; see Simulation Record." `_find_scenario_chart` (`exec_brief.py:358`) excludes hint `simulation`.
- **Bilingual.** The record's text fields join the existing `_sim_pairs` inventory (`artifact_translation.py:133, 182`) for the display overlay; the rendered `.md` for the other language is produced deterministically from the JSON, so no unaudited translated numbers are published. The bridge is rendered in Chinese by the renderer, as the world-v1 appendix is today.
- **Demo site.** `docs/demo.html:39` tab 5 becomes "Scenario simulation" with "Record | Raw feed" sub-views; `docs/i18n.js:119` `report.intro` is corrected to "used the simulation for mechanism analysis only, never for probabilities"; each demo folder ships `record.md` (and `record.zh.md`) when regenerated; pre-policy demos are badged "pre-policy report (June–July 2026)".
- **README.** `README.md:1036, 1083, 1249, 1292` are rewritten to state that the simulation reaches the report only through the deterministic bridge and that no signal pack enters section prompts.

---

## 4. Schema sketch — `simulation-record/v1`

```jsonc
{
  "schema": "simulation-record/v1",
  "record_class": "simulated",                 // I-11
  "epistemic_status": "elicited_model_projection",
  "simulation_id": "sim_…", "pipeline_id": "pipe_…", "config_hash": "…",
  "engine": "oasis-reflexive | world-v1 | oasis-inband | oasis-hours",
  "language": "en | zh",
  "as_of": "2026-10-23", "horizon_date": "2027-03-31", "calendar_unit": "week",
  "rounds_planned": 23, "rounds_committed": 23,
  "health": { "simulation_health": "ok", "validity": "valid",
              "arbiter_failed_rounds": 0, "seed_gaps": 3, "organic_actions": 412 },
  "banner": "<byte-exact SIM_BANNER_*>",
  "setup": {
    "cast": [ { "actor": "…", "agency_class": "government", "red_lines": ["…"],
                "documented_plans": ["…"], "source_refs": ["S12"] } ],   // refs are the dossier's ids, shown as text, never as [S#] citations
    "variables": [ { "name": "…", "seed_value": 3.5, "unit": "%", "as_of": "2026-09-30", "provenance": "…" } ],
    "scenarios": ["…"], "shocks": [ { "name": "…", "probability": 0.2, "window": "2026-Q4" } ],
    "seed_gaps": ["actor_without_plans: …"]
  },
  "periods": [ {
    "round": 1, "label": "2026-10-24", "period_start": "2026-10-24", "period_end": "2026-10-30",
    "arbiter_status": "applied", "arbiter_problems": [],
    "narrative": "<verbatim arbiter narrative>",
    "moves": [ { "actor": "…", "option": "…", "targets": ["…"], "magnitude": "…",
                 "public_statement": "…", "commitment": {"text": "…", "due": "…"},
                 "ref": {"file": "world_actions.jsonl", "round": 1, "id": "…"} } ],
    "held_position": ["…"],
    "facts_changed": [ { "variable": "…", "from": 3.5, "to": 3.75, "unit": "%", "cause": "…",
                         "ref": {"file": "world_state.json", "path": "world.variables[3].history[1]"} } ],
    "events": ["…"], "shocks_fired": ["…"], "red_lines_crossed": ["…"],
    "offers": [ { "from": "…", "to": "…", "kind": "talks", "status": "accepted", "terms": "…" } ],
    "alliances": ["…"],
    "behaviour": { "moves": 11, "responsive_moves": 7, "offers_answered": 2 }
  } ],
  "overall": {
    "final_variables": [ { "name": "…", "seed_value": 3.5, "final_value": 4.25, "unit": "%" } ],
    "shares": { "final": {"…": 0.44}, "converged_at": 17,
                "paths": { "k": 4, "per_scenario": { "…": {"mean": 0.42, "sd": 0.05, "p10": 0.36, "p50": 0.43, "p90": 0.49} } } },
    "turning_points": [ { "round": 9, "why": "red line crossed: …", "ref": {…} } ],
    "track_records": [ { "actor": "…", "kept": 2, "lapsed": 1, "broken": 0 } ],
    "synthesis": { "generator": "deterministic | llm", "text": "…",
                   "claims": [ { "paragraph": 0, "refs": [ {…} ] } ] }
  },
  "limits": { "arbiter_failed_rounds": 0, "seed_gaps": [...], "behaviour_note": "textual diagnostic, not a realism verdict" },
  "entities_declared": ["…"],
  "generated_at": "2026-10-22T14:30:00Z", "generator_version": "simulation_record/1.0"
}
```

---

## 5. Concrete change list (ordered; smallest, safest first)

Each slice is independently shippable and leaves the suite green. File anchors are to the current tree.

### Slice S0 — Containment that needs no new artifact

| # | File | Change | Why |
|---|---|---|---|
| S0.1 | `backend/app/services/sim_provenance.py` (new) | Constants module (§3.5) | Single source for labels, titles, banner, markers |
| S0.2 | `backend/app/services/report_visualizer.py:83-84, 2325, 3166, 3233, 5170, 5176, 5362` | Retitle to `CHART_OUTCOME_SHARES_*`; placement hint `scenarios` → `simulation` | A simulated chart must never be titled "Forecast"; `exec_brief._find_scenario_chart` (`exec_brief.py:358`) must not pick it |
| S0.3 | `backend/app/services/exec_brief.py:358-375, 398-420` | Exclude hint `simulation`; replace health fragment with the disclosure line | Brief says what the simulation was for |
| S0.4 | `backend/app/services/report_lint.py:927, 999, 1009, 1026-1027` and `:359-376` | Delete evidence-target rewrites; legacy labels become hard leakage issues | Ends laundering by rewrite |
| S0.5 | `backend/app/services/report_agent.py:6911-6922, 11829, 7032, 869-890` | One attribution rule: delete or `[S#]`-ground; drop "scenario analysis"/"scenario panel"/"analytical perspective" as targets; soften `PLAN_SYSTEM_PROMPT` | Removes the three-way contradiction |
| S0.6 | `backend/app/services/forecast_extractor.py:1187, 1266` | Align `【预测结果分布` with `【推演结果分布` via the constants module, or delete the dormant reconciliation; re-pin `test_sessionb_sim_additivity.py:60` | Marker drift already happened once |
| S0.7 | `backend/app/config.py:655` | `FORECAST_SIM_SENSITIVITY` default `false`; delete the XRUN-1(b) comment at `report_agent.py:5168` | The inert opposite intent stops contradicting the policy |
| S0.8 | `backend/app/services/report_agent.py:12450-12538, 14770-14790` | Relabel the what-if table as simulated shares; drop 「权威」 (moves into the bridge in S3) | Simulated table was labelled authoritative |

### Slice S1 — The record

| # | File | Change |
|---|---|---|
| S1.1 | `backend/app/services/simulation_record.py` (new) | Deterministic compiler per §3.1, three engine adapters, health stub, optional bounded synthesis behind `SIM_RECORD_SYNTHESIS` |
| S1.2 | `backend/app/services/simulation_record_gate.py` (new) | Checks G1–G9 (§3.2), writes `simulation_record_audit.json` |
| S1.3 | `backend/app/services/pipeline_orchestrator.py:10177, 11558, 10904` | Invoke record + gate after `write_run_summary` on both paths; register artifact `simulation_record`; a record failure degrades to the deterministic skeleton and never fails the stage |
| S1.4 | `backend/app/services/simulation_runner.py:1397-1399` | Add the three record files to the stale-artifact rotation list |
| S1.5 | `backend/app/api/simulation.py` (near `:2307`) | `GET /<id>/record`, `/record.md`; same containment posture as `/world-state`; 404 when absent, 409 when gate failed |
| S1.6 | `backend/app/api/research.py:856` and `frontend/src/api/research.js` | Expose `simulation_record` in the artifact list |

### Slice S2 — Dashboard

| # | File | Change |
|---|---|---|
| S2.1 | `frontend/src/components/research/SimulationView.vue` | "Record" view default after completion: header card, period strip, per-period section; legacy header caveat |
| S2.2 | `frontend/src/components/research/WorldStatePanel.vue:34`, `WorldSimulationView.vue:6` | Badge text from the shared constants (i18n keys) |
| S2.3 | `frontend/src/components/research/StageTimeline.vue:142-153` | Run stage label "Scenario simulation" |
| S2.4 | `frontend/src/api/simulation.js` | `fetchRecord(id)` |

### Slice S3 — The bridge and prompt isolation

| # | File | Change |
|---|---|---|
| S3.1 | `backend/app/services/report_agent.py` (beside `render_world_pathway:163`, `_insert_world_appendix:206`, `_world_prose:217`) | `render_sim_bridge`, `_insert_sim_bridge`, `_sim_prose` |
| S3.2 | `backend/app/services/report_agent.py:14993` and `:10453` | Insert the bridge for the default engine at the world-appendix call sites (EN and ZH) |
| S3.3 | `backend/app/services/report_agent.py:4145-4166`, `config.py:398` | `_build_signal_pack` returns `""` under `diagnostic_only`/`no_update` for every engine; `REPORT_SIGNAL_PACK` default `False`; remove the critique clause at `:13552-13566` |
| S3.4 | `backend/app/services/report_agent.py:11180` (`_final_audit_integrity_issues`), `:12279` (`_apply_publish_gate`) | Bridge count and byte checks per policy; `forecast.json.simulation_bridge` |
| S3.5 | `backend/app/services/report_lint.py:1601` (`lint_report`), `_fence_mask`, `report_agent.py:6818` | Section-aware: skip the marker block; outside it, leakage is a hard issue |
| S3.6 | `backend/app/services/report_agent.py:12450-12538` | Move the what-if table into the bridge |
| S3.7 | `backend/app/api/report.py:74` | `simulation_record_ref` in the publication payload |
| S3.8 | `frontend/src/components/research/ForecastReport.vue`, `BinaryForecastTable.vue` | Provenance legend; shaded bridge box; probabilities footnote; `forecast_effect` |

### Slice S4 — Docs, demo, ADR acceptance

| # | File | Change |
|---|---|---|
| S4.1 | `docs/adr/0003-….md` | Status Proposed → Accepted once S0–S3 land with T1 green |
| S4.2 | `README.md:1036, 1083, 1249, 1292`; `docs/i18n.js:111, 119`; `docs/demo.html:39` | State the new contract; rename tab 5; add Record sub-view |
| S4.3 | `docs/demos/*/` | Badge pre-policy demos; ship `record.md` for regenerated ones |
| S4.4 | `docs/handoff/reflexive-world-state/design.md` §2.6, `docs/architecture/DEEPRESEARCHFORECAST_SYSTEM_ATLAS.md` | Artifact tables gain the record and the bridge |

---

## 6. Tests

Frontend tests use the repository's `node --test` + `sfcHarness` SSR pattern, not vitest, and live under `frontend/tests/`.

| ID | Requirement | Test | Location |
|---|---|---|---|
| T1 | G2: byte-level isolation on the default engine | Two OASIS fixtures differing only in simulation artifacts produce byte-identical spine, binary, section, critique and repair prompts; `forecast.json` identical except `simulation_bridge.sha256`; `full_report.md` differs only between the bridge markers. Pattern: `test_world_report_consumers.py:227` (RW-11) | `backend/tests/test_sim_bridge_isolation.py` (new) |
| T2 | G2: no-spine fallback | Prose handed to `extract_structured_forecast` (`forecast_extractor.py:1022`) has zero `LEAKAGE_PATTERNS` hits and none of the fixture's unique simulation tokens | same file |
| T3 | G3: lint flips to provenance | "the simulation shows X" / 「模拟结果显示」 outside the markers → hard leakage issue, never rewritten to evidence wording; inside the markers → no issue. `rewrite_sim_labels` no longer emits "Evidence-based assessment" | `backend/tests/test_report_lint_provenance.py` (new); re-pin `test_wave9_report_focus.py`, `test_smoke_realrun_residue.py` |
| T4 | G4: record gate negatives | Fixtures with an invented actor, a number absent from rows, an `[S#]` marker, a `private_rationale` substring, a missing period, an altered banner, "probability" applied to a share → each a hard issue; the clean fixture passes | `backend/tests/test_simulation_record_gate.py` (new) |
| T5 | G5: hollow runs | `simulation_health=hollow` → stub record, zero LLM calls, bridge says the exercise was not usable; `arbiter_status=failed` rounds marked mechanical-only | `backend/tests/test_simulation_record.py` (new) |
| T6 | Policy | `no_update` → no bridge block, no link, no `simulation_bridge`; record still written. `diagnostic_only` → exactly one block, bytes equal to the renderer | `test_sim_bridge_isolation.py`; extend `test_foglamp_containment.py:316-368` |
| T7 | G6: chart | Visualizer emits `CHART_OUTCOME_SHARES_*`; `_find_scenario_chart` never returns the simulated charts | `backend/tests/test_report_visualizer_titles.py` (new) |
| T8 | What-if table | Appears only inside the bridge, labelled as simulated shares, no 「权威」 | `test_sim_bridge_isolation.py` |
| T9 | G6: single source | Header, lint, bridge, chart titles and Vue i18n strings all equal the constants; a grep-style test fails on any literal copy | `backend/tests/test_sim_provenance_constants.py` (new); `frontend/tests/simProvenanceBadge.test.mjs` (new) |
| T10 | Bilingual | `render_sim_bridge(chinese=True)` is byte-stable; inserted into the translated variant at the world-appendix site; numeric parity EN⇄ZH for every number in the bridge (reuse `translation_quantities` checks) | `backend/tests/test_sim_bridge_bilingual.py` (new) |
| T11 | API | `/record` serves only gate-passed content; 404 absent, 409 failed gate; symlink refused as in `/world-state` | `backend/tests/test_simulation_record_routes.py` (new) |
| T12 | Dashboard | `SimulationView` renders the record header and the selected period's section from a fixture; legacy header shows the caveat | `frontend/tests/simulationRecordView.test.mjs` (new) |
| T13 | Audit integrity | `_final_audit_integrity_issues` flags bridge count ≠ 1 under `diagnostic_only`, ≠ 0 under `no_update`, or bytes ≠ render | extend `backend/tests/test_final_publish_audit.py` |
| T14 | Determinism | Same artifacts → byte-identical `simulation_record.json` (excluding `generated_at`) in deterministic mode; synthesis failure falls back to the skeleton with a recorded reason | `test_simulation_record.py` |
| T15 | Input contract | `simulation_record.py` imports nothing from `report_agent`, `forecast_extractor`, `zep_tools`, research planes; opens no file outside the simulation directory (monkeypatched `open`) | `test_simulation_record.py` |
| T16 | Characterization re-pin | `test_architecture_characterization.py`, `test_context_audit_report.py` expectations updated for empty pack under `diagnostic_only` | existing files |

Acceptance for marking ADR 0003 Accepted: T1–T16 green in the plain suite, one live default-engine run whose published report contains exactly one bridge block and whose Simulation tab shows a gate-passed record, and one live `no_update` run with neither.

---

## 7. Open decisions for the owner

| ID | Decision | Recommendation |
|---|---|---|
| D1 | Should the record's overall synthesis use a bounded LLM call, or stay deterministic? | Bounded call on by default, gated by G2–G6, falling back to the skeleton; per-period prose stays deterministic |
| D2 | Should the bridge carry LLM-written paragraphs on where the exercise disagreed with the spine and why evidence won? | Not in version 1. The deterministic shares-versus-probabilities table gives the reader the divergence; prose commentary can follow once T1 and the gate exist, generated in a separate context with the byte-identical numeric-token rule |
| D3 | Pull the signal pack from section prompts now, accepting thinner mechanism prose in Parts 2–3? | Yes. Measure rubric scores on the demo corpus before and after; the record is where mechanism analysis now lives, honestly labelled |
| D4 | Fold the world-v1 pathway appendix under the bridge title? | Version 2. Version 1 shares constants only |
| D5 | Regenerate or badge pre-policy demos? | Badge now; regenerate only the showcase run |
| D6 | Record translation: deterministic second-language rendering (no translation call) versus audited translation of the `.md`? | Deterministic rendering for version 1; it publishes no unaudited translated numbers |

---

## 8. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Vivid per-period story out-persuades dry probabilities (war-story effect) | Banner on every page; no shares in per-period sections; the bridge table states the probabilities were not changed |
| Reports read drier once the pack leaves section prompts | Record linked from the bridge and shown first on the Simulation tab; measure rubric before/after (D3) |
| Section-aware lint gamed by placing simulation vocabulary just outside the markers | Block inserted after the stabilizer like the world-v1 appendix; outside-marker hits are hard issues; T1 and T13 pin bytes |
| Decisive-move ranking editorializes | Fixed documented rule (§3.3 item 2); T8 pins ordering on a fixture |
| Marker or label drift recurs | Constants module; T9 fails on any literal copy |
| Gate false positives on numeric normalization (60% vs 0.60, 亿 vs 100M) or entity aliases | Normalizer with unit classes reused from `translation_quantities`; alias allowlist from the cast manifest; soft-launch warnings for undeclared entities |
| Provider instability (GLM 1210/1301) breaks the synthesis call | Synthesis is optional and falls back to the skeleton; the record never blocks report publication |
| Three engine adapters diverge silently | The record always states engine and whether a world model ran; thin records are labelled, never padded |
| ~1,500 tests pin current lint behaviour | Re-pin per slice; never loosen a leakage pattern to make a fixture pass |
| Demo site and README advertise the old contract until S4 | S4 ships with S3 in the same release |

---

## 9. Out of scope

- Any change to how probabilities are derived, anchored to markets, or reconciled.
- Realism improvements to the arbiter, the kernel or actor decisions.
- The backtest ablation run that would justify `validated_update` (owned by the backtest program).
- Interview tooling for the arbiter or kernel (no post-run query channel exists beyond OASIS agents).


---

## 10. Deltas — slice S0 as implemented (2026-10-22/23)

Recorded here so §3–§6 can stay the target design. Commits are on `claude/sim-provenance-s0`.

| Area | Design said | S0 did | Why |
|---|---|---|---|
| §3.1–§3.3 | Record, gate and bridge | Not in S0. The shape contract `simulation_record_contract.py` (schema, loaders, `is_published`) was committed first as the shared anchor for S1 and S3 | Lets S1 and S3 proceed in parallel against one contract |
| §3.4 item 3 | Delete evidence-target rewrites; legacy labels become hard leakage issues | Done; plus the first pattern cut over-matched real-world prose and was re-anchored after review (N-agent compounds need a faction noun, 'agent dynamics' excludes hyphen compounds, Chinese forms need a methodology word). `the_simulation` covers this/our/a; `Simulation Agent` is case- and 模拟-prefix-insensitive; laundering labels (情景推演专家视角, scenario panel, 'Analytical perspective —') and 'has an agent for' are leakage patterns | Review found both false positives and missed determiner variants; probe over 15 demo reports: 37 newly flagged sentences, all simulation content in pre-policy reports, 0 in clean reports |
| §3.4 item 4 | Section-aware lint (fence) | Not in S0; S3 owns it. Consequence recorded: the canonical label 情景模拟 / "scenario simulation" is deliberately NOT a leakage pattern yet, so the what-if label survives, and a quote labelled with it is exempt from grounding deletion but not removed | Without a fence, flagging the canonical label would delete the only honest label S0 can place |
| §3.4 item 5 | Tier-2 prompt says delete-or-cite | Done; the numeric guard changed from "every input number survives" to all-or-nothing per leaking sentence (a surviving simulated sentence must have carried [S#] and keep every number; non-leaking numbers survive byte-identically; no new numbers; no growth beyond whitespace). A review blocker (the guard referenced the lint module under an unbound alias; the swallowed NameError dropped the whole repair pass on live runs) is fixed with stub-LLM tests | A delete-oriented rewrite can never pass "every number survives" |
| §3.4 item 5 | Pack header and prompts unified | The pack header's "must attribute to 内部情景推演" bullet is replaced by "must not enter the body"; the section system prompt, interview-tool description and tool hints say the same; `PLAN_SYSTEM_PROMPT` and the Part 2 prompt lose the 'scenario analysis' relabel | Review found four conventions still coexisting after the first S0.5 |
| §3.4 item 7 | Remove `interview_agents` from the default-engine tool list | Deferred to S3; S0 only rewrote its description and hint to forbid body use | Tool removal interacts with the writer tool set S3 rebuilds |
| §3.5 | One constants module | Done, plus `WHATIF_TABLE_*` labels, `BRIEF_SIM_ROLE_*` and `outcome_shares_header_re()`. The world-variables chart became "Simulated state variables": its old title matched the `simulated world` pattern, so its image line had been deleted from every published report | Found by the T9 lint-survival test added after review |
| §3.6 brief | "ran (health, N periods); informed mechanism analysis only, not probabilities; see Simulation Record" | Health plus organic-action count, and the policy sentence is looked up from the run's pinned `safety_policy_v1.simulation_forecast_effect` (diagnostic_only / no_update / legacy_prompt / not recorded); the record link arrives with S1/S3 | The brief must not assert a policy it did not read |
| §3.6 exec brief chart | Exclude hint `simulation` | Done, and `_find_scenario_chart` now reads the WAVE9 schema-v2 manifest it previously ignored | Its exclusion guard was dead code otherwise |
| §5 S0.2 | Placement hint `simulation` | Done; the hint's keyword list was narrowed to simulation words only (trajectory/model/outcome/world matched evidence sections) | Until S3's bridge exists the chart falls to the Visual Annex more often, which is the honest default |
| §5 S0.6 | Align marker or delete reconciliation | Aligned via the shared regex; the legacy `【预测结果分布` wording is accepted for fixtures only | Keeps `legacy_prompt` fixtures parsing |
| §5 S0.7 | Default off, comment removed | Done; the extractor's own fallback default and docstring, and `.env.example`, follow | Second default lived in the extractor |
| §5 S0.8 | Relabel the what-if table | Done via constants; first wording (模拟推演产物) was itself a leakage pattern and would have been deleted, leaving an unlabelled table | Caught by review; T9 now lints every reader-facing string |
| §6 T3/T7/T9 | As named | T3 `test_report_lint_provenance.py`; T7 `test_report_visualizer_titles.py` + `test_exec_brief_sim_disclosure.py`; T9 `test_sim_provenance_constants.py`; plus `test_outcome_header_alignment.py`, `test_simleak_tier2_guard.py`, `test_simulation_record_contract.py` | — |
| Final audit | — | `_final_audit_integrity_issues` also treats a non-zero `legacy_sim_labels` count as a hard issue | Belt and braces beside the leakage patterns |

### Deltas — slice S2 as implemented (2026-10-23, branch `worktree-wf_92affb56-682-2`, merged into `claude/sim-provenance-impl`)

| Area | Design said | S2 did | Why |
|---|---|---|---|
| §3.6 Dashboard | Record view "above the live World State panel and feed" | A **Record | Live** toggle: the Record view is the default after completion and the live layout is one click away | Stacking a long record above the live feed buried the feed; the toggle keeps both whole |
| §3.6 Dashboard | — | New `SimulationRecordView.vue` + pure helpers `utils/simRecord.js`; `utils/markdown.js` gains a generic marked-block splitter used for the bridge box | Keeps the view model testable without a DOM |
| §3.6 Dashboard | Period strip | The first committed period opens by default (an after-action record reads chronologically); WorldStatePanel keeps opening on the latest round | Different reading modes |
| §3.6 Dashboard | — | Bounded post-completion retry: a 404 on a completed run re-asks for the record at most 4 × 15 s; 409 and transport failures are not retried | Stage 5 writes the record seconds after the runner reports completion |
| §3.6 Dashboard | `ResearchView.vue` not in S2's file list | 9-line wiring: `@open-simulation-record` → Simulation tab, `@record-state` → "record ready" badge | The parent had no event or route for tab switching |
| §5 S2.2 | Badge strings | Already delivered by S0 (pinned to `sim_provenance` by T9); S2 made no change | — |
| §5 S2.4 | `fetchRecord(id)` | `fetchRecord(id)` accepts a bare record or a `{success, data}` envelope and returns `{record, status, publicationStatus}` for 404/409 | S1's route did not exist when S2 was written |
| §3.6 footnote | "probabilities from research evidence only (policy: …)" | Policy read from the report payload's `forecast_effect`, then `forecast.simulation_bridge.forecast_effect`, then `forecast.forecast_effect`; the S2 review found the fallback asserted `diagnostic_only` when nothing was read — fixed on the integration branch to "policy not recorded for this run" (mirrors `brief_sim_role`) | The footnote must not assert a policy it did not read |
| Fixtures | — | `frontend/tests/fixtures/sim/*.json` compiled from the live run `sim_3ec25e64209e` through the contract's public-field allowlist, trimmed to three rounds; a synthetic fixture covers K>1 paths, red lines, shocks and a mechanical-only round | Realistic shapes for T12 |

### Deltas — slices S1 and S3 as implemented (2026-10-23, merged into `claude/sim-provenance-impl`)

| Area | Design said | S1/S3 did | Why |
|---|---|---|---|
| §3.1 engine adapters | world-v1 "from `world_result.json` via `world_simulation.results`" | Reads the exported `world_result.json` / `world_spec.json` directly under the same containment (regular files, symlinks refused) | The store path reads SQLite through `Path.read_text`, which the T15 open() contract cannot see |
| §3.1 markdown files | One `.md` in the run's language plus the other language | Always `simulation_record.md` and `simulation_record.zh.md` (contract names); for a Chinese run both are Chinese and `/record.md?lang=en` renders English deterministically from the gate-passed JSON | Fixed file names in the contract; no translation call |
| §3.1 rotation list | Three record files | Four: json, md, zh.md and the audit | A stale passed audit would otherwise publish a stale record |
| §3.1 artifact spec | `simulation_record` beside `run_summary` | Appended only on the non-world-v1 spec path; world-v1 registers the artifact pointer and manifest entry directly | world-v1's strict spec set treats every spec as required |
| §3.2 G2 | Every numeric token traces to a row | Also admits structural integers (round indices, list lengths, status counts) and path statistics recomputed from `world_paths.json`; shares compared to the trajectory within 0.0005 | Those numbers are derived from the artifacts, not authored |
| §3.2 G3 | Entities ⊆ allowlist, hard | Structured actor fields and `entities_declared` are hard; undeclared capitalised multi-word tokens in authored prose are warnings in this version | As the brief specified |
| §3.2 G4 | Every paragraph has a resolvable ref | A synthesis paragraph with no claims entry is grounded by the committed periods whose label it names; the health-stub sentence needs none | Lets a deterministic record pass without fabricated refs |
| §3.2 G9 | Language purity, hard | Hard for compiler/LLM-authored prose; a warning inside a verbatim arbiter narrative | The record cannot change artifact text |
| §3.6 API | Serve only a gate-passed record | Also 409 `stale_audit` when the file's SHA-256 differs from the audit's | Stricter than `is_published`, never looser |
| §3.3 renderer | `render_sim_bridge(record, *, chinese, spine, chart_rel_paths, whatif_table_md)` | Two extra keyword-only arguments: `record_sha256` (the "Full record" line) and `policy` (the fixed sentence) | No constants existed for them |
| §3.3 strings | From `sim_provenance` | Bridge wiring strings (table headers, the fixed "probabilities were not changed" sentence, "record not available") are literals in `report_agent._SIM_BRIDGE_TEXT`; title, banner, markers and chart titles come from `sim_provenance` | `sim_provenance.py` was not S3's file; move them in a follow-up |
| §3.3 adapter path | Record absent → render from trajectory and world state | Renders final shares, red lines, broken commitments and health, states "After-action record not available for this run", and no decisive-moves table | Decisive-move ranking needs the record's refs |
| §3.3 charts | "moved here from wherever `_place_visualizations` put them" | `_place_visualizations` skips simulated charts while the bridge is active and `_insert_sim_bridge` strips any already placed | No simulated chart ever lands in an evidence section or the annex |
| §3.3 translated variant | Rendered in Chinese at the world-appendix site | Inserted iff the primary carries exactly one block, re-rendered in the target language | The translation worker is built without a pinned policy and must not invent one |
| §3.4 item 7 | Remove `interview_agents` from the default tool list | Removed from `_define_tools` (writer and chat paths); the env-alive probe became dead and was removed; the description constant remains unused | Minimal diff |
| §3.4 item 4 | Fence mask is the single mechanism | Also protects ordinary code fences in `strip_internal_basis_traces`, `strip_internal_graph_parentheticals` and `check_scenario_probabilities` | Narrower rewrite scope; needed so one mask governs every pass |
| §3.4 item 1 | No simulation bytes in any prompt | Section, critique, spine, binary and repair prompts are clean and pinned by T1; `plan_outline` still receives `simulation_outcomes` text (and `scenario_diff` + the what-if prompt label with a baseline) under `diagnostic_only` | Known gap, recorded here; the outline prompt produces titles and descriptions, not probabilities or prose |
| §3.3 robustness | — | `_sim_bridge_active` returns False when the policy cannot be resolved (bare backfill/translation agents) instead of raising out of chart placement or the audit | Found by the integrated full suite |
| §6 T1 | `forecast.json` identical except the bridge hash | Compared after dropping `simulation_bridge` and `quality.final_audit` (the per-report audit envelope) | The envelope carries the report id and its own bridge record |
| ADR acceptance | One live default-engine run with exactly one bridge block; one live `no_update` run | Still owed (fixtures only); the record's LLM synthesis path is exercised with a fake client only | Needs the owner's paid run |

Verification at the S0 tip (clean worktree): 7,707 passed, 9 failed, 19 errors, 1,668 skipped; every failure reproduces at the base commit except one Kaleido probe that the standalone-import fix resolved. Adversarial review (3 lenses, 25 confirmed findings, 2 refuted): the blocker and all majors are fixed in the follow-up commits listed in handoff.md.


### Completion deltas — Codex continuation (2026-10-23)

The latest implementation and acceptance authority is completion.md plus verification.json. Historical slice tables above explain the initial implementation, not unresolved exceptions.

- All non-legacy writer inputs, including outline sweeps, direct simulation tools and community fallback, are isolated. T1 now feeds nonempty distinct simulation content through the real report workflow and real record compiler/gate.
- Record publication uses a checked JSON snapshot with canonical JSON, Markdown and source-input seals. Native world export validity is verified before compilation/reuse and its manifest participates in the source seal. State lifecycle timestamps do not invalidate consumed identity fields.
- Native, OASIS, seed, reuse and standalone terminal paths share record publication. A per-launch artifact barrier prevents completion before post-hoc writes. Missing derivatives never force a paid RUN replay; repairs suppress repeat synthesis, including Markdown-only migrations.
- The missing-record bridge fallback uses an audited deterministic projection rather than unchecked raw strings. A failed projection is health-only. No_update and unknown provenance cannot expose record links. Malformed markers and changed translated envelopes fail publication.
- The composed newer Mandarin translation engine keeps its model-review receipts attached to the exact prose-only pair, then checks deterministic reinsertion against full public bytes. Its unrelated implementation remains owned by the existing working changes; scoped compatibility hunks are recorded in translation-compatibility.patch.
- Dashboard fields follow real producer shapes; late completion, generation switches, stale responses, rejected audits, retry and Record/Live navigation have actual SFC consumer tests. Record narration remains verbatim in version 1; the live-view translation control does not claim to translate the record.

The record gate establishes faithful reporting of the exercise, not historical truth, model realism or calibration. Source delivery and operational acceptance remain distinct in the handoff.
