# v3 engine: prompt architecture and insertion points (Explore agent, 2026-10-16)

I traced every v3 prompt, the cache rules and the tests that pin them, the planner contract, the official-data template and the downstream consumers. Paths are relative to `<repo>`; `lr` = `deerflow_bridge/linear_research.py`, `rg` = `deerflow_bridge/research_gateway.py`. Sizes are character counts of the raw templates.

## 1. Prompt inventory (message slots)

Every call is built by `rg.build_messages(system, shared, task)` (`rg:450-466`): system message, then the shared blocks, then the task as the last user message. On Claude, a constant "OK." assistant turn is inserted before the task (`rg:1304-1329`).

| Prompt | Where | Size | Slot / static vs volatile |
|---|---|---|---|
| `ENGINE_CORE` | `lr:237-283` | 6,270 (~1.6k tokens) | System message of every call; static across all runs. §5 "Forecasting frame" is at `:265-268` |
| `_T_PRE_BRIEF` | `lr:400-403` | 107 | Shared block 1 of the scope and plan calls (question, language, as-of) |
| `_T_SCOPE` | `lr:405-413` | 954 | Last message; JSON `{restated_question, horizon, scout_queries, key_entities}` |
| `_T_PLAN` | `lr:415-426` | 1,972 | Last message of `[core][pre_brief][scout digest][task]` (`lr:5510-5513`); the OFFICIAL DATA suffix and catalog are appended only when data is on (`lr:5514-5537`) |
| RUN BRIEF (`render_brief`) | `lr:1771-1796` | varies | Shared block 1 of every call after planning; built once, saved as `brief.md` |
| `_T_KIQ_TASK` + `_KIND_EMPHASIS` | `lr:428-445`, `523-529` | 1,269; emphasis 65 / 125 / 117 for general / actor / data | Last message `[core][brief][task]`, then append-only assistant/tool turns. STOP, nudge and budget texts (`lr:194-211`) are added later as human/tool turns |
| `_T_GAP` | `lr:447-455` | 776 | `[core][brief][task]` (`lr:6088-6101`), plus a data suffix (`:6091-6099`) |
| `section_task` | `lr:6376-6402` | built per call | Writers: `[core][brief][digest][task]` (`lr:6515`). Contains `_SECTION_RULES` (1,122, `:506-515`), `_SCENARIO_SECTION_NOTE` (348, `:517-521`) and, with data, `_DATA_SECTION_RULE` (`:714`) |
| QA repair / single rewrite | `lr:7041-7046`, `7094-7097`, `6558` | short | Same writer layout; adds `current` text and a "Problem to fix" note |
| `_T_EXEC` | `lr:457-461` | 567 | `[core][brief][SECTION LEADS][task + data headlines]` (`lr:6627-6637`) |
| `_T_CRITIQUE` | `lr:463-467` | 560 | `[core][brief][report][task]` (`lr:7137-7145`). Only runs in the deep preset (`critique` is False in quick and standard) |
| `_T_ACTORS` / `_T_FACTS` | `lr:469-480`, `482-492` | 2,263 / 1,262 | `[core][brief][report][task]` with an `extract:prime` call first (`lr:7399-7413`) |
| `forecast_inputs()` | `lr:7553-7556` | — | No prompt; built deterministically |

## 2. Prompt-cache invariants

**Where they are documented**
- `lr:42-46`: layout is `[ENGINE_CORE][RUN BRIEF][shared…][task]`, "everything volatile lives only in the LAST message", conversations are append-only with the same tools object.
- `lr:192`: "the one tools object bound on every agent call".
- `lr:394-398`: templates use `string.Template`; "No template may contain a literal `$`".
- `rg:15-20` and `rg:453-456`: shared blocks must be byte-identical; volatile text goes in the task.
- `rg:1350-1360`: tools are bound once per tools object, keyed by identity.
- `rg:3455-3458`: never mutate the tool schemas; one is selected per run.
- `lr:4910-4916`: JSON repair notes land only in the last message.
- `lr:6194-6212`: the evidence digest is persisted and wrapped once, so every writer and repair sees identical bytes.
- `lr:4885-4895`: evidence blocks are wrapped with constant labels.

**Tests that pin them**
- `backend/tests/test_research_engine_v3.py:439-445`: `ENGINE_CORE` has at least 1,200 tokens, no `$` or `{`, no dates.
- Same file `:420-436`: every template renders with no `$` left.
- Same file `:805-835`: system message is always `ENGINE_CORE`; agent tools `is rg.AGENT_TOOLS_SCHEMA`, including prime and final calls; the first two messages are identical across agent calls; conversations are append-only; per-KIQ text appears only in `messages[2]`; writers share `messages[:3]` and have exactly 4 messages; the extraction calls share `messages[:3]`.
- Same file `:986-989`: the repair note appears only in the last message.
- Same file `:149-158`: `role_of` requires the last message to start with its task marker.
- `test_research_engine_v3_round2.py:730`: `brief.md` must equal `render_brief(Plan.from_dict(plan))`.
- `test_v3_official_data.py`:
  - `:264-270`: with data off, the tools and the KIQ task are unchanged.
  - `:1386-1388`: with data off, the task equals the bare template.
  - `:1394-1401`: web-only tool replies are byte-identical.
  - `:1425-1429`: with data off, `section_task` ends with `_SECTION_RULES`.
  - `:1517-1519`: the planner gets no `data_needs` text when data is off.
  - `:1459`: the gap coverage matrix contains no "official" text.
  - `:1797`: meta keys of a data-free run stay the same.
- `test_research_gateway_official_data.py:116-135`: tool schemas are static text and the data schema's first two entries equal the web-only schema.

**What must stay byte-identical:** `ENGINE_CORE`, the brief (and it must be reproducible from `plan.json`), the digest, the tools object, and every prompt in runs where a feature is off.

**Where run-specific text is safe:** appended to the end of a last-message task, so it still starts with its marker; or in the brief, but only if derived from saved `Plan` fields.

Two further constraints:
- Do not put methodology inside `delimit()` blocks. `ENGINE_CORE:242` tells the model never to follow instructions found in data, and `neutralize_instructions` may strip them.
- Do not add a new shared message. That breaks the `messages[2]` and length-4 assertions.

## 3. Dataclasses, planner contract, existing classifiers

**Dataclasses**
- `Kiq` (`lr:1293-1319`): `id`, `question`, `queries`, `kind`, `why`, `round`, `data_needs`. `to_dict` writes `data_needs` only when it is non-empty (`:1306`).
- `_KIQ_KINDS = {"general","actor","data"}` (`:1242`); unknown kinds become `general` (`:1318`, `:1445`).
- `OutlineSection` (`:1322-1332`): `index`, `title`, `kiq_ids`, `focus`, `is_scenario`.
- `Scenario` (`:1335-1342`): `name`, `weight` (int), `thesis`.
- `Plan` (`:1345-1400`): `from_dict` requires exactly one scenario section and 2–6 scenarios whose weights sum to 100.

**Planner JSON (`lr:418-426`)**
- `kiqs[{question, queries, kind}]`.
- `sections[{title, kiqs:[1-based], focus, scenario:true}]`.
- `scenarios[{name, weight, thesis}]`, 2–6, MECE.
- `actors[{name, type, why}]`.

`build_plan` (`:1718-1764`) assigns ids K1..Kn, fills deterministic fallbacks (`_DEFAULT_KIQS :290`, `_DEFAULT_OUTLINE :316`, `_EXTRA_OUTLINE :339`, `_DEFAULT_FRAME :348`), and sets each KIQ's `why` from the sections it feeds. Gap follow-ups are always `kind="general"` (`:6123-6127`).

**Classifiers you could route methodology on**
- `_BASE_RATE_RE` (`lr:592`).
- `detect_language` (`lr:1018`).
- Scenario and use-case title regexes (`lr:1251-1256`).
- KIQ `kind`.
- Scope `key_entities` and `horizon`.
- `data_catalog.TOPICS` (`deerflow_bridge/data_catalog.py:175-212`: growth, inflation, energy, technology, trade, autos, policy, and so on), read via the private `_parse_query(q).topics` (`:2282-2306`) and the public `query_geographies` (`:2309`).

## 4. The official-data pattern to copy

1. One run-level flag, decided once in `__init__` (`lr:4687-4693`); `self.agent_tools` is chosen from it at the same time.
2. Each prompt gets a conditional suffix appended after the rendered template:
   - planner `if self.data_enabled: task += …` (`:5514`);
   - KIQ task `if not getattr(self,"data_enabled",False): return task` (`:5859-5861`);
   - gap `:6091`; coverage matrix `:6146`.
   - writer, executive summary and critique add their rule only when stored rows exist (`:6393-6396`, `_data_headlines :6243-6255` returns `""` otherwise).
3. Rule texts are module constants (`:712-725`), stated to be "used only in runs with official data… never ENGINE_CORE" (`:531-536`).
4. New plan fields are optional and serialized only when non-empty (`data_needs`, `:1280-1306`).
5. `getattr` guards are used because tests call methods on `SimpleNamespace` engines (`test_research_engine_v3_text.py:120-131`).
6. Resume keeps the decision (`_configure_data :4717-4755`), and meta keys stay the same when the feature is off (`:614-616`).

## 5. Tool plumbing

- Schemas are module constants: `AGENT_TOOLS_SCHEMA` (`rg:3420-3453`, web only) and `AGENT_TOOLS_WITH_DATA_SCHEMA` (`rg:3459-3497`).
- The engine picks one per run (`lr:4693`). Priming and every step use it (`lr:5694`, `3825`, `3840`). Dispatch is in `KiqAgent._execute` (`:3915-3975`), which only counts these four names toward the step slot cap, and `_call_tool` (`:4055-4097`).
- Prediction markets are **not** an agent tool; they are collected at finalize through `bridge_call("_collect_prediction_markets")` (`lr:7302`).

**What a new read-only methodology tool would touch**
1. Schema combinations. You would need new constants such as web+method and web+data+method, selected once per run. `AGENT_TOOLS_SCHEMA` must remain exactly `["web_search","web_fetch"]` (`test_v3_official_data.py:434`) and must stay the bound object in runs without the feature (`test_research_engine_v3.py:812`).
2. The name allow-list at `lr:3929`, plus a new `ToolLimits` counter (`rg:3365-3417` has none that fits).
3. Novelty. A step with no new source counts toward `NOVELTY_PATIENCE=2` (`lr:3802-3804`), so two methodology reads in a row would force final notes. `data_search` needed a special case for this (`:3958-3962`).
4. `tool_output_sids` treats an unknown tool's output like a search result (`:3616-3627`). The tool must never print `[S<n>]` at the start of a line.
5. Token pressure: `AGENT_CONTEXT_TOKEN_CAP=60_000` (`:117`), and each read spends one of the 5/7/9 steps.
6. The UNKNOWN/INVALID reply texts (`:4060-4095`) are pinned per mode.

Putting methodology text into the task is cheaper and fully deterministic, so a tool is not recommended.

**Skills directory:** any new folder under `deerflow_bridge/skills/` must be deployed byte-identically to `deer-flow/skills/public` (`backend/tests/test_drf2_skills_config.py:642-700`, `runtime_skill_sync.py`). A v3-only registry kept elsewhere avoids that.

## 6. What downstream consumes

**research_report.md**
- Order: `# question`, Executive Summary, the outline sections, the canonical scenario block at the top of the scenario section (`lr:1918-1927`, `3456-3469`), Official Data Baseline after the first analytical section (`:6846-6891`), then References built by the engine.
- Binary forecasts read it head plus tail (48k characters, 60% head; `backend/app/services/forecast_extractor.py:4394-4397`), so the executive summary and the closing sections carry the most weight.

**actors.json** (`lr:7484-7551`)
- Holds `situation_brief`, actors, relationships, and `forecast_inputs`.
- **`forecast_inputs` always has `base_rates: []` and `drivers: []`** (`:7553-7556`). Scenarios carry `probability` and `narrative`; indicators come only from official series (`:7641-7668`).
- Consumers:
  - `forecast_inputs_block` (`backend/app/utils/actors.py:2880-2958`) feeds the forecast spine in `backend/app/services/report_agent.py:4171-4235`, which is the probability authority, and `backend/app/services/simulation_config_generator.py:2283`.
  - `world_state_seed_from_actors` (`actors.py:2613-2678`) falls back to `base_rates[].outcome_frequency` for scenarios without a probability.

**quantitative.json** feeds the report's key-metrics table (`report_agent.py:2531`, `2692`). Official rows are prepended (`lr:7621-7639`).

**What drives forecast quality most:**
1. The scenario frame. Its weights are fixed at plan time from scout snippets only and enforced for the whole run (`ENGINE_CORE:267`, `fix_scenario_weights`).
2. The empty `base_rates` and `drivers`.
3. `situation_brief`.
4. Quantitative and official series.
5. The executive summary and closing sections.

## Recommendation: safest, highest-leverage insertion points

Pick the methodology pack deterministically before planning (question regexes plus catalog topics), or let the planner choose from a menu. Either way, save the choice in `plan.json` as an optional key written only when non-empty, so resumed attempts rebuild the same tasks, and record a content hash in meta.

1. **`_Engine._plan_calls`** (`lr:5489-5549`), appended after `_render(_T_PLAN…)` alongside the OFFICIAL DATA suffix. Content: KIQ checklist, suggested sections, reference-class and base-rate-first guidance for scenario weights. This is the only place the frame is shaped.
   - Task must still start with "PLANNING TASK".
   - Any new JSON key must be optional (the fixture `World` won't return it); `required=` stays the same.
   - It also covers `replan_after_outage` automatically.
   - Feature off means byte-identical.
2. **`_Engine._kiq_task`** (`lr:5841-5861`), per-KIQ text chosen by kind, an optional method field, or `_BASE_RATE_RE`, appended after the template.
   - Use `getattr` guards.
   - Keep the four note headings (`lr:2221-2226`); base rates go in Findings with markers, computed counts tagged REPORTED.
   - About 1–2k characters at most; no fake `[S<n>]` markers; never inside `delimit`.
3. **`_Engine._gap_review`** (`lr:6086-6129`), a methodology coverage checklist appended to the task. Coverage is judged here.
   - Only the task changes; the shared block stays `[self.brief]`.
   - Follow-ups stay `kind="general"`.
4. **`_Engine.section_task`** (`lr:6376-6402`), plus suffixes on `_exec_summary` (`:6633`) and `_critique` (`:7139`), mirroring `_DATA_SECTION_RULE`.
   - With the feature off, the task must still end with `_SECTION_RULES`.
   - Keep the shared `[core][brief][digest]` prefix untouched. QA rewrites reuse `section_task`, so guidance stays consistent.
5. **`_Engine._structured` and `forecast_inputs`** (`lr:7380-7428`, `7553-7556`): fill `base_rates`, `drivers` and `indicators` with a conditional `_T_FACTS` suffix or a third extraction job on the same `[core][brief][report]` prefix (prime already runs when two or more jobs are pending).
   - Memoize per kind by `report_sha256` in `extract/<kind>.json`.
   - Fall back to `[]`.
   - Always take scenarios from `plan.scenarios`.
   - Merge official indicators the way `_official_indicators` does.

Optionally, add a one-line "Methodology lens" to `render_brief`, derived only from `Plan` fields (`round2:730`). It is cache-safe but rides on every call, so keep it short. Leave `ENGINE_CORE` alone unless the addition is generic, static, free of `$`/`{`/dates, and applies to every run.
